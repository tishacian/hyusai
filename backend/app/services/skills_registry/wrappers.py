"""Callable wrappers for canonical Skills.

Each wrapper translates a typed canonical-skill input into a real call
against the existing OmniRAG service layer. Wrappers are intentionally
thin — they never introduce new business logic.

Runtime status (returned by `bound_slugs()`) is tri-state:
 - ``bound``     : an actual implementation module is resolvable and will be invoked.
 - ``stub``      : a placeholder that logs + returns a degraded payload (no hard-fail).
 - ``unbound``   : no wrapper declared for that slug (`resolve()` refuses it).

The check happens lazily on first use, cached in
``_RESOLVED_STATUS`` so the admin `/skills/runtime-health` endpoint is
cheap to call. Imports of the underlying services stay lazy to avoid
pulling heavy deps at registry introspection time.
"""

from __future__ import annotations

import base64
import importlib
import re
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from app.core.logging import get_logger
from app.services.evaluation.judge import (
    contractual_zero_token_usage,
    new_provider_usage_accumulator,
    normalize_provider_usage,
    provider_usage_evidence,
    record_provider_usage,
)
from app.services.rag.project_references import (
    extract_query_project_codes,
    numeric_project_candidates,
)
from app.services.skills_registry.binding import (
    SkillBindingError,
    SkillCallable,
    is_workspace_skill_slug,
)

logger = get_logger(__name__)


# workspace_id -> slug cache (process-lifetime). The run_engine ctx
# (``_build_initial_ctx``) carries ``workspace_id`` but NOT ``workspace_slug``,
# yet retrieval needs the slug to build the tenant-scoped physical Qdrant
# collection name (``VectorDBFactory.scoped_name`` -> ``{slug}__{collection}``).
# Without it every DAG retrieval targets a non-existent un-prefixed collection
# (0 chunks, embedding never reached). We resolve the slug from the id once and
# memoise it. Only successful lookups are cached so a transient failure retries.
_WORKSPACE_SLUG_CACHE: dict[str, str] = {}
_PROVIDER_USAGE_CTX_KEY = "_provider_usage_v1"


def _start_provider_usage_scope(ctx: dict[str, Any]) -> dict[str, Any]:
    """Start one invocation-local provider usage scope in the ephemeral ctx."""

    accumulator = new_provider_usage_accumulator()
    ctx[_PROVIDER_USAGE_CTX_KEY] = accumulator
    return accumulator


def _provider_usage_scope(ctx: dict[str, Any]) -> dict[str, Any]:
    accumulator = ctx.get(_PROVIDER_USAGE_CTX_KEY)
    if not isinstance(accumulator, dict):
        accumulator = _start_provider_usage_scope(ctx)
    return accumulator


def _usage_candidate(payload: Any) -> Any:
    """Return the nearest explicit provider usage container, if present."""

    if not isinstance(payload, dict):
        return payload
    if normalize_provider_usage(payload) is not None:
        return payload
    metrics = payload.get("metrics")
    if isinstance(metrics, dict) and normalize_provider_usage(metrics) is not None:
        return metrics
    meta = payload.get("meta")
    if isinstance(meta, dict) and normalize_provider_usage(meta) is not None:
        return meta
    return payload


def _provider_usage_contract(payload: Any) -> dict[str, Any] | None:
    """Locate canonical complete/partial provider evidence without mirroring it."""

    if not isinstance(payload, dict):
        return None
    for candidate in (
        payload,
        payload.get("metrics"),
        payload.get("meta"),
    ):
        if not isinstance(candidate, dict):
            continue
        if normalize_provider_usage(candidate) is not None or isinstance(
            candidate.get("provider_usage"), dict
        ):
            return candidate
    return None


def _record_provider_usage_contract(
    accumulator: dict[str, Any],
    contract: dict[str, Any],
    *,
    provider: str,
    model: str,
) -> bool:
    """Append every evidenced call, preserving incomplete coverage exactly."""

    complete = contract.get("usage")
    if isinstance(complete, dict):
        calls = complete.get("calls")
        if isinstance(calls, list) and calls:
            for call in calls:
                if not isinstance(call, dict):
                    continue
                record_provider_usage(
                    accumulator,
                    call,
                    provider=str(call.get("provider") or provider),
                    model=str(call.get("model") or model),
                )
            return True
        if normalize_provider_usage(contract) is not None:
            record_provider_usage(
                accumulator,
                contract,
                provider=provider,
                model=model,
            )
            return True

    partial = contract.get("provider_usage")
    if isinstance(partial, dict):
        calls = partial.get("calls")
        if isinstance(calls, list) and calls:
            for call in calls:
                if not isinstance(call, dict):
                    continue
                reported_payload = (
                    {"total_tokens": call.get("reported_total")}
                    if call.get("reported") is True
                    and call.get("reported_total") is not None
                    else None
                )
                record_provider_usage(
                    accumulator,
                    reported_payload,
                    provider=str(call.get("provider") or provider),
                    model=str(call.get("model") or model),
                )
            return True
    return False


def _without_direct_meta_usage(meta: Any) -> dict[str, Any]:
    """Move direct token evidence to the canonical top-level contract."""

    cleaned = dict(meta) if isinstance(meta, dict) else {}
    cleaned.pop("usage", None)
    cleaned.pop("token_usage", None)
    return cleaned


def _retrieval_token_path(
    accumulator: dict[str, Any],
    result: dict[str, Any],
) -> bool:
    """Record retrieval usage and return whether its path is non-token.

    Local sentence-transformer, cross-encoder and hash paths cannot call a
    token-billed provider.  Remote/unknown embedding paths are deliberately
    unreported unless the retrieval service exposes real usage counters.
    """

    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    provider = str(metrics.get("embedding_provider") or "retrieval")
    model = str(metrics.get("embedding_model") or "unknown")
    contract = _provider_usage_contract(result)
    if contract is not None and _record_provider_usage_contract(
        accumulator,
        contract,
        provider=provider,
        model=model,
    ):
        return False
    normalized_provider = provider.strip().lower()
    canonical_zero_calls = (
        metrics.get("embedding_provider_usage_scope") == "canonical_request_v1"
        and metrics.get("embedding_provider_calls") == 0
    )
    if (
        canonical_zero_calls
        or metrics.get("retrieval_context_cache_hit") is True
        or normalized_provider
        in {
            "local",
            "hash",
            "sentence-transformers",
            "sentence_transformers",
        }
    ):
        return True
    record_provider_usage(
        accumulator,
        None,
        provider=normalized_provider or "unknown_retrieval_provider",
        model=model,
    )
    return False


def _resolve_workspace_slug(payload: dict[str, Any], ctx: dict[str, Any]) -> Optional[str]:
    """Resolve the workspace slug, falling back to a DB lookup by id.

    Parity with the classic ``/chat`` path which always sets ``workspace_slug``.
    The fallback only fires when the slug is absent but the id is present (the
    run_engine DAG case), so callers that already pass a slug are untouched.
    """
    slug = ctx.get("workspace_slug") or payload.get("workspace_slug")
    if slug:
        return str(slug)
    workspace_id = ctx.get("workspace_id") or payload.get("workspace_id")
    if not workspace_id:
        return None
    cached = _WORKSPACE_SLUG_CACHE.get(workspace_id)
    if cached is not None:
        return cached
    try:
        from app.db.base import SessionLocal
        from app.models.workspace import Workspace

        db = SessionLocal()
        try:
            ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
            resolved = getattr(ws, "slug", None) if ws else None
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 — never crash retrieval on a slug lookup
        logger.warning(
            "skills_registry: workspace slug lookup failed",
            workspace_id=workspace_id,
            error=str(exc),
        )
        return None
    if resolved:
        _WORKSPACE_SLUG_CACHE[workspace_id] = resolved
    return resolved


def _rag_runtime_kwargs(payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for key in ("top_k", "candidate_pool_k", "synthesis_k", "source_display_k"):
        value = payload.get(key)
        if value is not None:
            kwargs[key] = value
    latency_profile = payload.get("latency_profile") or ctx.get("latency_profile")
    if latency_profile:
        kwargs["latency_profile"] = latency_profile
    retrieval_profile = payload.get("retrieval_profile") or ctx.get("retrieval_profile")
    if retrieval_profile:
        kwargs["retrieval_profile"] = retrieval_profile
    if payload.get("deep_retrieval") is not None:
        kwargs["deep_retrieval"] = bool(payload.get("deep_retrieval"))
    retrieval_filters = payload.get("retrieval_filters")
    if isinstance(retrieval_filters, dict):
        kwargs["retrieval_filters"] = retrieval_filters
    authoritative_collections = payload.get("authoritative_collections")
    if isinstance(authoritative_collections, list):
        normalized = list(
            dict.fromkeys(
                str(item).strip()
                for item in authoritative_collections[:32]
                if isinstance(item, str) and item.strip()
            )
        )
        if normalized:
            kwargs["authoritative_collections"] = normalized
    if payload.get("authoritative_document_scope") is True:
        kwargs["authoritative_document_scope"] = True
        if "authoritative_document_refs" in payload:
            raw_refs = payload.get("authoritative_document_refs")
            allowed_collections = set(kwargs.get("authoritative_collections") or [])
            normalized_refs: dict[str, list[str]] = {}
            total_refs = 0
            ref_items = raw_refs.items() if isinstance(raw_refs, dict) else ()
            for raw_collection, raw_document_ids in ref_items:
                collection = str(raw_collection or "").strip()
                if (
                    not collection
                    or (allowed_collections and collection not in allowed_collections)
                    or not isinstance(raw_document_ids, list)
                ):
                    continue
                document_ids = list(
                    dict.fromkeys(
                        str(item).strip()
                        for item in raw_document_ids
                        if isinstance(item, str) and item.strip()
                    )
                )
                remaining = max(0, 1000 - total_refs)
                if document_ids and remaining:
                    normalized_refs[collection] = document_ids[:remaining]
                    total_refs += len(normalized_refs[collection])
                if total_refs >= 1000:
                    break
            # Presence is security-significant. Forward an explicit empty map so
            # the RAG boundary can distinguish malformed/new input from a legacy
            # snapshot that genuinely omitted pair refs.
            kwargs["authoritative_document_refs"] = normalized_refs
    knowledge_scope = payload.get("knowledge_scope") or ctx.get("knowledge_scope")
    if knowledge_scope:
        kwargs["knowledge_scope"] = knowledge_scope
    source_policy = payload.get("source_policy") or ctx.get("source_policy")
    if isinstance(source_policy, dict):
        kwargs["source_policy"] = source_policy
    context_collection = (
        payload.get("collection")
        or payload.get("collection_name")
        or payload.get("context_collection")
        or ctx.get("collection")
        or ctx.get("collection_name")
        or ctx.get("context_collection")
    )
    if context_collection:
        kwargs["context_collection"] = context_collection
    return kwargs


# ---------------------------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------------------------
async def _stub(payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Degraded placeholder for skills whose runtime is not yet available."""
    logger.info("skills_registry: stub invocation", payload_keys=list(payload.keys()))
    return {
        "status": "degraded",
        "warning": "runtime_unavailable",
        "input_echo": payload,
    }


async def _translation_showcase_stub(
    payload: dict[str, Any],
    ctx: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Structured simulation for showcase Translation Suite stages.

    The real project-mt runtime is intentionally not invoked from Agentium
    showcase seeds. This preserves the canonical skill contract and run
    engine behavior while keeping the demo deterministic and sovereign.
    """
    ctx = ctx or {}
    skill_slug = str(payload.get("skill_slug") or ctx.get("skill_slug") or "translation_stage")
    verdict = str(payload.get("expected_verdict") or payload.get("verdict") or "ACCEPT_4D")
    agent_identity = (
        payload.get("agent_identity") or ctx.get("agent_identity") or "agent.translation.showcase"
    )
    logger.info(
        "translation_showcase_stub: simulated stage",
        skill_slug=skill_slug,
        verdict=verdict,
        agent_identity=agent_identity,
    )
    return {
        "status": "simulated",
        "showcase_seed": True,
        "skill_slug": skill_slug,
        "verdict": verdict,
        "agent_identity": agent_identity,
        "sovereignty": {
            "external_llm_egress": False,
            "model_versions_frozen": True,
            "tenant_scope": ctx.get("workspace_id") or payload.get("workspace_id"),
        },
        "metrics": {
            "deterministic": True,
            "prompt_tokens": payload.get("prompt_tokens", 0),
            "completion_tokens": payload.get("completion_tokens", 0),
        },
        "input_echo": payload,
    }


# ---------------------------------------------------------------------------
# Concrete wrappers
# ---------------------------------------------------------------------------
async def _chat_trivial_bypass_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.chat_trivial_bypass import maybe_trivial_bypass

    bypass = maybe_trivial_bypass(str(payload.get("query") or ""))
    if not bypass:
        return {"bypassed": False, "answer": "", "reason": None}
    return {
        "bypassed": True,
        "answer": bypass.content,
        "reason": bypass.reason,
        "meta": bypass.metadata(),
    }


async def _llm_rag_answer_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    # Preserve an explicitly supplied empty dict: provider usage is accumulated
    # in this invocation-local context before being projected to the ledger.
    ctx = ctx if isinstance(ctx, dict) else {}
    usage_accumulator = _start_provider_usage_scope(ctx)
    query = str(payload.get("query") or "")

    # CONSUME pre-retrieved context when the caller supplies a ``context`` list
    # (the agentic DAG wires ``context <= join.retrieval.results``). This makes
    # task.generate answer FROM the chunks the rest of the graph evaluates,
    # instead of launching a second, independent (and historically empty)
    # retrieval. Other callers (rag_service, mission_room, …) never pass a
    # ``context`` list and keep the orchestrator retrieval path below unchanged.
    context_value = payload.get("context")
    if isinstance(context_value, (list, tuple)):
        passages = _context_passages(context_value)
        lang_target = payload.get("lang_target")
        if not passages:
            # Join produced nothing — abstain honestly, NEVER re-retrieve into
            # the void or free-generate (that is what produced hallucinations).
            return {
                "answer": _no_context_message(lang_target),
                "citations": [],
                "decision_steps": [],
                "meta": {
                    "retrieval": {
                        "raw_chunks_retrieved": 0,
                        "source": "join_context",
                        "no_context": True,
                    }
                },
                **contractual_zero_token_usage("llm_rag_answer:no_context_abstention"),
            }
        passages = _select_inventory_synthesis_passages(
            query,
            payload.get("answer_profile"),
            passages,
        )
        model = payload.get("model") or ctx.get("default_model")
        prompt = _build_grounded_answer_prompt(
            query, passages, lang_target, payload.get("answer_profile")
        )
        answer_text = ""
        try:
            answer_text = await _route_llm_complete(prompt, model, ctx)
        except Exception as exc:  # noqa: BLE001 — degrade to abstention, never crash the DAG
            logger.warning("llm_rag_answer_v1: grounded synthesis failed", error=str(exc))
            answer_text = _no_context_message(lang_target)
        answer_text, coverage_review = await _review_inventory_answer_coverage(
            query=query,
            passages=passages,
            draft=answer_text,
            model=model,
            ctx=ctx,
            lang_target=lang_target,
        )
        output = {
            "answer": answer_text,
            "citations": _citations_from_passages(passages),
            "decision_steps": [],
            "meta": {
                "retrieval": {
                    "raw_chunks_retrieved": len(passages),
                    "source": "join_context",
                    "stage_timings": {},
                },
                "inventory_coverage_review": coverage_review,
            },
        }
        output.update(provider_usage_evidence(usage_accumulator))
        return output

    # No supplied context -> classic orchestrator retrieval (unchanged contract),
    # now with the tenant slug resolved so it never targets a phantom collection.
    from app.services.rag.rag_service import answer

    result = await answer(
        query=query,
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        session_id=payload.get("session_id"),
        rag_mode_override=(
            payload.get("rag_pipeline_mode")
            or payload.get("rag_mode_override")
            or ctx.get("retrieval_mode_default")
        ),
        prompt_type=payload.get("prompt_type") or ctx.get("default_prompt_type"),
        model=payload.get("model") or ctx.get("default_model"),
        provider=payload.get("provider"),
        workspace_slug=_resolve_workspace_slug(payload, ctx),
        **_rag_runtime_kwargs(payload, ctx),
        # Forward the run-engine sink so the orchestrator's text
        # chunks are rebroadcast as SSE token_delta events in real
        # time (Vague D / D2). Non-streaming callers simply don't pass
        # the sink and observe no behavioural change.
        token_sink=ctx.get("token_sink"),
    )
    # The classic orchestrator is a separate generation facade.  It currently
    # exposes no usage; if it starts doing so, consume the real counters.  Until
    # then this provider call remains unavailable instead of being estimated
    # from answer length.
    record_provider_usage(
        usage_accumulator,
        _usage_candidate(result),
        provider=str(payload.get("provider") or "orchestrator"),
        model=str(payload.get("model") or ctx.get("default_model") or "unknown"),
    )
    output = {
        "answer": result.get("answer", ""),
        "citations": result.get("citations", []),
        "decision_steps": result.get("decision_steps", []),
        "meta": _without_direct_meta_usage(result.get("meta", {})),
    }
    output.update(provider_usage_evidence(usage_accumulator))
    return output


async def _semantic_search_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.rag.context import apply_retrieval_profile_to_request, retrieve_rag_context

    ctx = ctx or {}
    usage_accumulator = new_provider_usage_accumulator()
    non_token_retrieval_paths = 0
    runtime_kwargs = _rag_runtime_kwargs(payload, ctx)
    retrieval_contract = (
        ctx.get("retrieval_contract") if isinstance(ctx.get("retrieval_contract"), dict) else {}
    )
    authoritative_collection = None
    if retrieval_contract.get("asset_binding") == "authoritative":
        declared = retrieval_contract.get("collection") or retrieval_contract.get(
            "primary_collection"
        )
        if str(declared or "").strip():
            authoritative_collection = str(declared).strip()
            requested_collection = runtime_kwargs.get("context_collection")
            if requested_collection and requested_collection != authoritative_collection:
                logger.warning(
                    "semantic_search_v1: overriding collection outside retrieval contract",
                    requested=requested_collection,
                    authoritative=authoritative_collection,
                    workspace_id=ctx.get("workspace_id"),
                )
            # The System contract is stronger than the flow asset-binding flag
            # and than any payload supplied by an upstream node.
            runtime_kwargs["context_collection"] = authoritative_collection
            runtime_kwargs.pop("knowledge_scope", None)
    allow_workspace_fallback = (
        retrieval_contract.get("empty_bound_collection") != "abstain"
        and retrieval_contract.get("allow_workspace_fallback", True) is not False
    )
    # Phase 2 (p2-binding): an authoritative asset->collection binding scopes
    # retrieval to a single collection (``context_collection``). If that bound
    # collection resolves to empty/unknown we MUST fall back to workspace scope
    # rather than return a SILENTLY EMPTY retrieval (grounding lesson 2026-06-26,
    # docs/chat-recherche-agentic-grounding-audit-2026-06-26.md). We detect the
    # bound collection here and, on a zero-chunk primary result, retry without it.
    # This safety net is flag-INDEPENDENT (it reacts to context_collection, which
    # the DAG only injects when the flag is ON), so callers with no collection are
    # byte-identical to before.
    bound_collection = runtime_kwargs.get("context_collection")

    def _build_request(*, with_collection: bool) -> dict[str, Any]:
        kwargs = dict(runtime_kwargs)
        if not with_collection:
            kwargs.pop("context_collection", None)
        request = {
            "query": payload["query"],
            "workspace_id": ctx.get("workspace_id") or payload.get("workspace_id"),
            # Resolve the tenant slug (DAG ctx omits it) so retrieval hits the
            # real ``{slug}__{collection}`` Qdrant collection instead of a phantom
            # un-prefixed one (root cause of raw_chunks_retrieved=0 in the A/B).
            "workspace_slug": _resolve_workspace_slug(payload, ctx),
            "capability_id": ctx.get("capability_id") or payload.get("capability_id"),
            "system_id": ctx.get("system_id") or payload.get("system_id"),
            "knowledge_scope": (
                None
                if authoritative_collection
                else payload.get("knowledge_scope") or ctx.get("knowledge_scope")
            ),
            "context_mode": "replace" if authoritative_collection else payload.get("context_mode"),
            "authoritative_collections": (
                [authoritative_collection] if authoritative_collection else None
            ),
            "rag_pipeline_mode": payload.get("mode") or payload.get("rag_pipeline_mode") or "auto",
            # top_k / latency_profile / retrieval_profile / budgets flow from the
            # plan via runtime_kwargs; default to the balanced lane (never hardcode
            # fast) so factual lookups get a real candidate pool, matching classic.
            **kwargs,
        }
        # A persisted System retrieval contract is stronger than a node-local
        # Builder scope. Re-assert it after ``kwargs`` so payload data can never
        # widen the governed collection boundary.
        if authoritative_collection:
            request["authoritative_collections"] = [authoritative_collection]
        run_input = ctx.get("input") if isinstance(ctx.get("input"), dict) else {}
        history = payload.get("conversation_history") or run_input.get("conversation_history")
        salient = payload.get("salient_entities") or run_input.get("salient_entities")
        if isinstance(history, list) and history:
            request["context"] = {"conversation_history": history}
            if isinstance(salient, dict) and salient:
                request["context"]["salient_entities"] = salient
        request.setdefault("latency_profile", "balanced")
        # RECALL PARITY (fix 2026-06-26): backfill the full lane budget triple
        # (top_k/synthesis_k/candidate_pool_k/source_display_k) so a lone top_k pin
        # does not collapse synthesis_k/candidate_pool_k (which starved the DAG to ~6
        # ctx vs classic ~12 and made it miss carrier chunks). When nothing is
        # pinned, the lane sets all budgets = chat._apply_retrieval_budget_policy.
        # Explicit payload values (plan overrides) win via setdefault.
        lane = str(request.get("latency_profile") or "balanced").lower()
        for budget_key, budget_value in _LANE_BUDGETS.get(lane, _LANE_BUDGETS["balanced"]).items():
            request.setdefault(budget_key, budget_value)
        # TRANSVERSAL-INVENTORY PARITY (fix 2026-06-26): "which projects use X"
        # questions need the exhaustive project_code FACET (classic arms it via
        # answer_profile=transversal_inventory), not a handful of deep chunks.
        # retrieve_rag_context only builds the facet when this profile is set AND
        # query_targets_projects(query) — so arming it here is a no-op for ordinary
        # queries and reaches classic parity for inventory ones.
        if _is_inventory_query(str(payload.get("query") or "")) and not request.get(
            "answer_profile"
        ):
            request["answer_profile"] = "transversal_inventory"
        request = {key: value for key, value in request.items() if value is not None}
        apply_retrieval_profile_to_request(request)
        return request

    request = _build_request(with_collection=True)
    result = await retrieve_rag_context(request)
    non_token_retrieval_paths += int(_retrieval_token_path(usage_accumulator, result))
    chunks = list(result.get("chunks") or [])
    if bound_collection and not chunks and allow_workspace_fallback:
        logger.warning(
            "semantic_search_v1: authoritative asset collection returned no context; "
            "falling back to workspace scope (grounding safety net)",
            collection=bound_collection,
            workspace_id=request.get("workspace_id"),
            query=str(payload.get("query") or "")[:120],
        )
        request = _build_request(with_collection=False)
        result = await retrieve_rag_context(request)
        non_token_retrieval_paths += int(_retrieval_token_path(usage_accumulator, result))
        chunks = list(result.get("chunks") or [])
    scores = list(result.get("scores") or [])
    metadatas = list(result.get("metadatas") or [])
    metrics = dict(result.get("metrics") or {})
    reported_collections_raw = metrics.get("collections_touched") or metrics.get("collections")
    if isinstance(reported_collections_raw, str):
        reported_collections = [reported_collections_raw]
    elif isinstance(reported_collections_raw, (list, tuple, set)):
        reported_collections = [
            str(item).strip() for item in reported_collections_raw if str(item).strip()
        ]
    else:
        reported_collections = []
    contradictory_collection_proof = bool(
        authoritative_collection
        and any(item != authoritative_collection for item in reported_collections)
    )
    results = []
    for index, content in enumerate(chunks):
        metadata = (
            dict(metadatas[index])
            if index < len(metadatas) and isinstance(metadatas[index], dict)
            else {}
        )
        if (
            authoritative_collection
            and not contradictory_collection_proof
            and not any(
                metadata.get(key) for key in ("collection", "collection_name", "collection_slug")
            )
        ):
            metadata["collection"] = authoritative_collection
        results.append(
            {
                "content": content,
                "score": scores[index] if index < len(scores) else None,
                "metadata": metadata,
            }
        )
    # Surface the exhaustive enumeration as the TOP authoritative passage so the
    # grounded synthesis lists the projects (the few retrieved chunks otherwise
    # only describe the equipment, not where it is deployed).
    inventory = result.get("project_inventory") if isinstance(result, dict) else None
    inv_passage = _project_inventory_passage(inventory)
    if inv_passage:
        results.insert(0, inv_passage)
    output = {
        "results": results,
        "project_inventory": inventory,
        "pipeline": result.get("pipeline"),
        "label": result.get("label"),
        "reason": result.get("reason"),
        "detail": result.get("detail"),
        "retrieval_scope": metrics.get("retrieval_scope") or result.get("retrieval_scope"),
        "scope_confidence": metrics.get("scope_confidence"),
        "scope_reason": metrics.get("scope_reason"),
        "dense_policy": metrics.get("dense_policy"),
        "fallback_reason": metrics.get("fallback_reason"),
        "latency_budget": metrics.get("latency_budget"),
        # Preserve contradictory backend proof verbatim so the chat adapter's
        # egress gate can block it.  Only infer the authoritative collection
        # when the backend emitted no collection telemetry at all.
        "collections_touched": reported_collections
        or ([authoritative_collection] if authoritative_collection and chunks else []),
        "retrieval_decision_trace": metrics.get("retrieval_decision_trace"),
        # Observable grounding proof — non-zero once workspace_slug is wired.
        "raw_chunks_retrieved": (
            metrics.get("raw_chunks_retrieved")
            if metrics.get("raw_chunks_retrieved") is not None
            else len(chunks)
        ),
        "document_chunks_retrieved": metrics.get("document_chunks_retrieved"),
        "stage_timings": metrics.get("stage_timings"),
    }
    calls = usage_accumulator.get("calls") or []
    if calls:
        output.update(provider_usage_evidence(usage_accumulator))
    elif non_token_retrieval_paths:
        output.update(
            contractual_zero_token_usage("semantic_search:retrieval_without_provider_call")
        )
    else:
        # Defensive: an unknown retrieval implementation is not proof of zero.
        output.update(provider_usage_evidence(usage_accumulator))
    return output


def _merge_multi_hop_searches(
    searches: list[dict[str, Any]], *, limit: int
) -> list[dict[str, Any]]:
    """RRF-merge + dedupe several ``semantic_search_v1`` result sets.

    Reuses ``comparative_retrieval.merge_comparative_results`` (RRF over rank
    position, content-collapsed) so a chunk found by multiple sub-queries ranks
    higher and is never duplicated. Rows keep the uniform
    ``{content, score, metadata}`` shape of ``semantic_search_v1.results`` so the
    lane is interchangeable with a single-lane retrieve at the join.
    """
    from app.services.rag.comparative_retrieval import (
        _SubResult,
        merge_comparative_results,
    )

    def _split(res: dict[str, Any]) -> tuple[list[str], list[float], list[dict[str, Any]]]:
        chunks: list[str] = []
        scores: list[float] = []
        metas: list[dict[str, Any]] = []
        for row in (res or {}).get("results") or []:
            if isinstance(row, dict):
                content = row.get("content") or row.get("text") or row.get("snippet") or ""
            elif isinstance(row, str):
                content = row
            else:
                content = ""
            content = str(content or "").strip()
            if not content:
                continue
            chunks.append(content)
            score = row.get("score") if isinstance(row, dict) else None
            try:
                scores.append(float(score) if score is not None else 0.0)
            except (TypeError, ValueError):
                scores.append(0.0)
            metas.append(dict(row.get("metadata") or {}) if isinstance(row, dict) else {})
        return chunks, scores, metas

    if not searches:
        return []
    primary = _split(searches[0])
    subs: list[Any] = []
    for index, res in enumerate(searches[1:], start=1):
        chunks, scores, metas = _split(res)
        subs.append(
            _SubResult(entity=f"hop_{index}", chunks=chunks, scores=scores, metadatas=metas)
        )
    chunks, scores, metas, _diag = merge_comparative_results(primary, subs, limit=limit)
    return [
        {"content": chunks[i], "score": scores[i], "metadata": metas[i]} for i in range(len(chunks))
    ]


async def _multi_hop_retrieve_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Parallel multi-hop retrieval over decomposed sub-queries (Phase 4).

    Consumes ``plan.thinking.sub_queries`` and runs one ``semantic_search_v1``
    per (deduped) sub-query PLUS the main query, in parallel via
    ``asyncio.gather``, then merges/dedupes the hits (RRF, reusing
    ``comparative_retrieval``) into the SAME output shape as
    ``semantic_search_v1`` (``results[]`` + ``raw_chunks_retrieved``) so it drops
    into ``join.retrieval`` as an interchangeable lane. When ``sub_queries`` is
    empty it degrades to a single search of the main query.  A failing hop does
    not crash the DAG, but it keeps a stable technical failure marker so an
    all-hop backend outage cannot be misclassified as a grounded empty corpus.
    """
    import asyncio

    ctx = ctx or {}
    query = str(payload.get("query") or "").strip()
    raw_subs = payload.get("sub_queries")
    subs = (
        [s.strip() for s in raw_subs if isinstance(s, str) and s.strip()]
        if isinstance(raw_subs, list)
        else []
    )

    # Anchor with the main query so we never under-retrieve vs a single pass,
    # then dedupe (case-insensitive) preserving order.
    seen: set[str] = set()
    queries: list[str] = []
    for candidate in [query, *subs]:
        key = candidate.lower()
        if candidate and key not in seen:
            seen.add(key)
            queries.append(candidate)
    if not queries:
        return {"results": [], "raw_chunks_retrieved": 0, "sub_queries": [], "hop_count": 0}

    # Per-lane budgets / scope shared across every hop (resolved from the plan).
    base = {
        key: payload.get(key)
        for key in (
            "knowledge_scope",
            "latency_profile",
            "retrieval_profile",
            "top_k",
            "synthesis_k",
            "candidate_pool_k",
            "deep_retrieval",
            "rag_pipeline_mode",
            "retrieval_filters",
            "authoritative_collections",
            "authoritative_document_scope",
            "authoritative_document_refs",
            "collection",
            "collection_name",
            "context_collection",
            "context_mode",
            "source_policy",
        )
        if payload.get(key) is not None
    }

    async def _one(sub_query: str) -> dict[str, Any]:
        try:
            return await _semantic_search_v1({**base, "query": sub_query}, ctx)
        except Exception as exc:  # noqa: BLE001 — one bad hop must not sink the lane
            logger.warning("multi_hop_retrieve_v1: sub-query search failed", error=str(exc))
            return {
                "results": [],
                "raw_chunks_retrieved": 0,
                "collections_touched": [],
                "fallback_reason": "retrieval_backend_error",
            }

    searches = list(await asyncio.gather(*[_one(q) for q in queries]))

    limit = 0
    for key in ("synthesis_k", "candidate_pool_k"):
        try:
            limit = max(limit, int(payload.get(key)) if payload.get(key) is not None else 0)
        except (TypeError, ValueError):
            continue
    if limit <= 0:
        limit = _LANE_BUDGETS["balanced"]["synthesis_k"]

    results = _merge_multi_hop_searches(searches, limit=limit)
    raw_total = 0
    collections_touched: list[str] = []
    failure_reasons: list[str] = []
    for res in searches:
        try:
            raw_total += int(res.get("raw_chunks_retrieved") or 0)
        except (TypeError, ValueError):
            pass
        for collection in res.get("collections_touched") or []:
            value = str(collection or "").strip()
            if value and value not in collections_touched:
                collections_touched.append(value)
        reason = str(res.get("fallback_reason") or "").strip()
        if reason and reason not in failure_reasons:
            failure_reasons.append(reason)

    output = {
        "results": results,
        "raw_chunks_retrieved": raw_total or len(results),
        "sub_queries": queries[1:],
        "hop_count": len(queries),
        "collections_touched": collections_touched,
    }
    if failure_reasons:
        output["fallback_reason"] = (
            "retrieval_backend_error"
            if not results and raw_total == 0
            else "partial_retrieval_backend_error"
        )
    return output


async def _document_ingestion_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.rag.document_service import DocumentService

    ctx = ctx or {}
    doc_svc = DocumentService(workspace_slug=ctx.get("workspace_slug"))
    file_path = payload.get("file_path") or payload.get("filename")
    if not file_path:
        raise ValueError("document_ingestion_v1: 'file_path' or 'filename' required")
    result = await doc_svc.ingest_document(file_path)
    return {
        "doc_id": result.get("document_id"),
        "chunks": result.get("chunks_processed", 0),
        "status": result.get("status"),
    }


async def _eval_radar_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.evaluation.judge import get_judge_service

    judge = get_judge_service()
    evaluation = await judge.evaluate(
        query=payload.get("query", ""),
        response=payload["answer"],
        system_prompt=payload.get("system_prompt", ""),
        context_chunks=payload.get("context_chunks"),
        turn_number=payload.get("turn_number", 1),
    )
    output = {
        "axes": evaluation.get("scores", {}),
        "overall": evaluation.get("composite_score"),
        "hallucination_rate": evaluation.get("hallucination_rate"),
        "drift_rate": evaluation.get("drift_rate"),
        "note": evaluation.get("overall_note"),
    }
    if isinstance(evaluation.get("usage"), dict):
        output["usage"] = dict(evaluation["usage"])
    elif isinstance(evaluation.get("provider_usage"), dict):
        output["provider_usage"] = dict(evaluation["provider_usage"])
    return output


async def _claim_audit_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.evaluation.judge import get_judge_service

    judge = get_judge_service()
    evaluation = await judge.evaluate(
        query=payload.get("query", ""),
        response=payload["answer"],
        system_prompt=payload.get("system_prompt", ""),
        context_chunks=payload.get("citations"),
        turn_number=payload.get("turn_number", 1),
    )
    audit = evaluation.get("claim_audit") or {}
    claims = audit.get("claims", [])
    supported = audit.get("supported", 0)
    total = max(1, len(claims))
    verdict = "supported" if supported / total >= 0.8 else "partial" if supported else "unsupported"
    output = {
        "claims": claims,
        "verdict": verdict,
        "supported": supported,
        "unsupported": audit.get("unsupported", 0),
    }
    # JudgeService owns provider-neutral token normalisation.  A missing
    # provider counter remains ``provider_usage: unavailable`` and therefore
    # cannot turn into a false zero in the SkillInvocation ledger.
    if isinstance(evaluation.get("usage"), dict):
        output["usage"] = dict(evaluation["usage"])
    elif isinstance(evaluation.get("provider_usage"), dict):
        output["provider_usage"] = dict(evaluation["provider_usage"])
    return output


async def _intelligence_batch_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.db.base import SessionLocal
    from app.models.workspace import Workspace
    from app.services.intelligence.batch import get_dashboard_data, run_batch
    from app.services.intelligence.knowledge_sync import sync_intelligence_to_knowledge

    ctx = ctx or {}
    ingested = 0
    errors = 0
    events: list[str] = []
    knowledge_sync: dict[str, Any] = {"status": "skipped"}
    target_id = payload.get("target_id") or (payload.get("feed_ids") or [None])[0]
    async for event in run_batch(
        target_id=target_id,
        workspace_id=ctx.get("workspace_id"),
    ):
        kind = event.get("type") or event.get("status")
        if kind:
            events.append(str(kind))
        if event.get("type") == "article_stored":
            ingested += 1
        if event.get("type") == "error" or event.get("status") == "error":
            errors += 1

    workspace_id = ctx.get("workspace_id") or payload.get("workspace_id")
    if workspace_id:
        db = SessionLocal()
        try:
            workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
            if workspace:
                dashboard = get_dashboard_data(db, workspace_id=workspace.id)
                knowledge_sync = await sync_intelligence_to_knowledge(
                    db,
                    workspace,
                    dashboard_payload=dashboard,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "intelligence_batch_v1.knowledge_sync_failed",
                workspace_id=workspace_id,
                error=str(exc),
            )
            knowledge_sync = {"status": "error", "error": str(exc)}
        finally:
            db.close()
    return {
        "ingested": ingested,
        "errors": errors,
        "events": events,
        "knowledge_sync": knowledge_sync,
    }


def _workspace_from_context(payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> Any:
    ctx = ctx or {}
    workspace_id = ctx.get("workspace_id") or payload.get("workspace_id") or "demo-workspace"
    workspace_slug = ctx.get("workspace_slug") or payload.get("workspace_slug") or "workspace"
    workspace_name = payload.get("workspace_name") or workspace_slug
    return SimpleNamespace(id=workspace_id, slug=workspace_slug, name=workspace_name)


async def _ministerial_briefing_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import briefing_payload

    workspace = _workspace_from_context(payload, ctx)
    briefing = briefing_payload(workspace)
    return {
        "briefing": briefing,
        "sources": briefing.get("sources", []),
        "status": "ready",
    }


async def _news_signal_synthesis_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import news_payload

    workspace = _workspace_from_context(payload, ctx)
    news = news_payload(workspace)
    return {
        "summary": news.get("summary"),
        "signals": news.get("signals", []),
        "sources": news.get("sources", []),
    }


async def _project_risk_explainer_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import projects_payload

    workspace = _workspace_from_context(payload, ctx)
    projects = projects_payload(workspace)
    project_id = payload.get("project_id") or payload.get("target_id")
    project = next(
        (item for item in projects.get("projects", []) if item.get("id") == project_id),
        (projects.get("projects") or [None])[0],
    )
    if not project:
        return {"status": "no_project", "project": None, "explanation": {}, "sources": []}
    return {
        "project": project,
        "explanation": {
            "cause": project.get("cause"),
            "risk": project.get("risk"),
            "options": project.get("options", []),
            "advisory_only": True,
        },
        "sources": project.get("sources", []),
    }


async def _territorial_signal_map_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import map_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        return map_payload(workspace, db=db)
    finally:
        if owns_db:
            db.close()


async def _scenario_generate_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.scenario_engine import generate_scenarios

    return {
        "options": generate_scenarios(
            target_kind=str(payload.get("target_kind") or "cabinet"),
            target_id=str(payload.get("target_id") or ""),
            risk_level=str(payload.get("risk_level") or "medium"),
            source_refs=list(payload.get("source_refs") or []),
            agenda_pressure=int(payload.get("agenda_pressure") or 0),
            signal_strength=int(payload.get("signal_strength") or 50),
            context=dict(payload.get("context") or {}),
        )
    }


async def _scenario_compare_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.scenario_engine import compare_scenarios

    return compare_scenarios(list(payload.get("options") or []))


async def _scenario_recommend_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.scenario_engine import recommend_scenario

    return recommend_scenario(
        target_kind=str(payload.get("target_kind") or "cabinet"),
        target_id=str(payload.get("target_id") or ""),
        risk_level=str(payload.get("risk_level") or "medium"),
        source_refs=list(payload.get("source_refs") or []),
        agenda_pressure=int(payload.get("agenda_pressure") or 0),
        signal_strength=int(payload.get("signal_strength") or 50),
        context=dict(payload.get("context") or {}),
    )


async def _instruction_draft_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import draft_instruction_payload

    ctx = ctx or {}
    workspace = _workspace_from_context(payload, ctx)
    actor = ctx.get("actor") or payload.get("actor") or "system:instruction_draft_v1"
    return draft_instruction_payload(
        workspace=workspace,
        actor=str(actor),
        target_id=payload.get("target_id") or payload.get("project_id") or "proj-health-north",
        target_type=payload.get("target_type") or "project",
        instruction_type=payload.get("instruction_type") or "dircab_instruction",
        db=ctx.get("db"),
    )


def _calendar_db_and_workspace(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> tuple[Any, Any]:
    from app.db.base import SessionLocal
    from app.models.workspace import Workspace

    ctx = ctx or {}
    db = ctx.get("db")
    owns_db = False
    if db is None:
        db = SessionLocal()
        owns_db = True
    workspace_id = ctx.get("workspace_id") or payload.get("workspace_id")
    workspace_slug = ctx.get("workspace_slug") or payload.get("workspace_slug")
    query = db.query(Workspace)
    workspace = None
    if workspace_id:
        workspace = query.filter(Workspace.id == workspace_id).first()
    if workspace is None and workspace_slug:
        workspace = query.filter(Workspace.slug == workspace_slug).first()
    if workspace is None:
        if owns_db:
            db.close()
        raise ValueError("calendar skill requires workspace_id or workspace_slug")
    return db, workspace


async def _calendar_read_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.workspace_calendar import list_events, serialize_event

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        events = list_events(db, workspace, status=payload.get("status"))
        return {
            "events": [serialize_event(event, workspace=workspace) for event in events],
            "workspace_id": workspace.id,
        }
    finally:
        if owns_db:
            db.close()


def _hana_rows_as_context(
    columns: list[Any], rows: list[Any]
) -> list[dict[str, Any]]:
    """Format HANA result rows as llm_rag_answer_v1-compatible passages."""
    col_names = [str(c) for c in (columns or [])]
    passages: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)):
            continue
        parts = []
        for idx, value in enumerate(row):
            key = col_names[idx] if idx < len(col_names) else f"c{idx}"
            parts.append(f"{key}={value}")
        content = " | ".join(parts).strip()
        if not content:
            continue
        passages.append(
            {
                "content": content,
                "metadata": {"source": "sap_hana", "source_family": "hana_query"},
                "score": 1.0,
            }
        )
    return passages


async def _sap_hana_query_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.connectors.hana import service as hana_service

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if not hana_service.is_workspace_enabled(workspace):
            raise ValueError("SAP HANA connector is not enabled for this workspace")
        config = hana_service.get_config(workspace, include_secrets=True)
        max_rows = payload.get("max_rows")
        result = hana_service.run_query(
            config,
            sql=str(payload.get("sql") or ""),
            params=payload.get("params"),
            max_rows=int(max_rows) if max_rows is not None else 200,
            allow_writes=bool(payload.get("allow_writes")),
        )
        # Chainable to llm_rag_answer_v1 via inputs_map.context ← task.hana.context
        result["context"] = _hana_rows_as_context(
            list(result.get("columns") or []),
            list(result.get("rows") or []),
        )
        return result
    finally:
        if owns_db:
            db.close()


async def _rpa_dispatch_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.connectors.rpa import service as rpa_service

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if not rpa_service.is_workspace_enabled(workspace):
            raise ValueError("RPA Bridge connector is not enabled for this workspace")
        config = rpa_service.get_config(workspace, include_secrets=True)
        if not config.get("configured"):
            raise ValueError("RPA Bridge connector is not configured (base_url / auth token)")
        timeout_s = payload.get("timeout_s")
        poll_interval_s = payload.get("poll_interval_s")
        input_payload = payload.get("input")
        if input_payload is not None and not isinstance(input_payload, dict):
            raise ValueError("input must be an object")
        return rpa_service.dispatch_and_poll(
            config,
            job_key=str(payload.get("job_key") or ""),
            input_payload=input_payload,
            callback_url=(
                str(payload["callback_url"]) if payload.get("callback_url") else None
            ),
            timeout_s=float(timeout_s) if timeout_s is not None else 30.0,
            poll_interval_s=float(poll_interval_s) if poll_interval_s is not None else 0.5,
        )
    finally:
        if owns_db:
            db.close()


async def _calendar_create_event_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.workspace_calendar import calendar_write_policy, create_event, serialize_event

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        start_at = datetime.fromisoformat(str(payload["start_at"]).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
        end_at = (
            datetime.fromisoformat(str(payload["end_at"]).replace("Z", "+00:00")).replace(
                tzinfo=None
            )
            if payload.get("end_at")
            else None
        )
        if calendar_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        event = create_event(
            db,
            workspace,
            None,
            title=str(payload["title"]),
            start_at=start_at,
            end_at=end_at,
            location=str(payload.get("location") or ""),
            description=str(payload.get("description") or ""),
            participants=list(payload.get("participants") or []),
            priority=str(payload.get("priority") or "medium"),
            metadata={"created_from": "skill", "skill_slug": "calendar_create_event_v1"},
        )
        db.commit()
        return {
            "status": "applied",
            "applied": True,
            "event": serialize_event(event, workspace=workspace),
        }
    finally:
        if owns_db:
            db.close()


async def _calendar_update_event_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.workspace_calendar import calendar_write_policy, serialize_event, update_event

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if calendar_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        updates = dict(payload.get("updates") or {})
        for key in (
            "title",
            "description",
            "location",
            "participants",
            "priority",
            "status",
            "start_at",
            "end_at",
        ):
            if key in payload and key not in updates:
                updates[key] = payload[key]
        event = update_event(db, workspace, None, str(payload["event_id"]), updates=updates)
        db.commit()
        return {
            "status": "applied",
            "applied": True,
            "event": serialize_event(event, workspace=workspace),
        }
    finally:
        if owns_db:
            db.close()


async def _calendar_cancel_event_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.workspace_calendar import calendar_write_policy, cancel_event, serialize_event

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if calendar_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        event = cancel_event(
            db,
            workspace,
            None,
            str(payload["event_id"]),
            reason=str(payload.get("reason") or "skill"),
        )
        db.commit()
        return {
            "status": "applied",
            "applied": True,
            "event": serialize_event(event, workspace=workspace),
        }
    finally:
        if owns_db:
            db.close()


async def _calendar_daily_summary_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from datetime import date as dt_date

    from app.services.workspace_calendar import summary_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        day = dt_date.fromisoformat(str(payload["day"])) if payload.get("day") else None
        return summary_payload(db, workspace, day=day)
    finally:
        if owns_db:
            db.close()


async def _action_plan_create_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.action_plans import (
        action_planner_write_policy,
        create_action_item,
        serialize_action_item,
    )

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if action_planner_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        item = create_action_item(
            db,
            workspace,
            None,
            title=str(payload["title"]),
            description=str(payload.get("description") or ""),
            target_kind=str(payload.get("target_kind") or "cabinet"),
            target_id=str(payload.get("target_id") or ""),
            target_label=str(payload.get("target_label") or ""),
            priority=str(payload.get("priority") or "medium"),
            due_at=payload.get("due_at"),
            owner_label=str(payload.get("owner_label") or "Cabinet"),
            source_kind=str(payload.get("source_kind") or "skill"),
            source_id=str(payload.get("source_id") or ""),
            metadata={"created_from": "skill", "skill_slug": "action_plan_create_v1"},
        )
        db.commit()
        return {"status": "applied", "applied": True, "item": serialize_action_item(item)}
    finally:
        if owns_db:
            db.close()


async def _action_plan_reschedule_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.action_plans import (
        action_planner_write_policy,
        serialize_action_item,
        update_action_item,
    )

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if action_planner_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        item = update_action_item(
            db,
            workspace,
            None,
            str(payload["item_id"]),
            {"due_at": payload.get("due_at"), "status": "planned"},
        )
        db.commit()
        return {"status": "applied", "applied": True, "item": serialize_action_item(item)}
    finally:
        if owns_db:
            db.close()


async def _action_plan_status_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.action_plans import list_action_items, serialize_action_item, summary_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        rows = list_action_items(
            db,
            workspace,
            status=payload.get("status"),
            include_cancelled=bool(payload.get("include_cancelled", True)),
        )
        return {
            "items": [serialize_action_item(row) for row in rows],
            "summary": summary_payload(db, workspace),
        }
    finally:
        if owns_db:
            db.close()


async def _action_plan_cancel_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.action_plans import (
        action_planner_write_policy,
        cancel_action_item,
        serialize_action_item,
    )

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        if action_planner_write_policy(workspace) == "approval_required":
            return {"status": "proposal", "applied": False, "proposal": payload}
        item = cancel_action_item(
            db,
            workspace,
            None,
            str(payload["item_id"]),
            reason=str(payload.get("reason") or "skill"),
        )
        db.commit()
        return {"status": "applied", "applied": True, "item": serialize_action_item(item)}
    finally:
        if owns_db:
            db.close()


async def _time_context_set_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.demo_time_context import demo_time_context_defaults
    from app.services.iam.app_entitlements import (
        lock_workspace_for_app_entitlement_mutation,
    )

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
        settings = dict(workspace.settings or {})
        defaults = demo_time_context_defaults(workspace)
        mode = str(payload.get("mode") or defaults["mode"])
        settings["demo_time_context"] = {
            "mode": mode,
            "current_date": str(
                payload.get("current_date") or payload.get("date") or defaults["current_date"]
            ),
            "current_time": str(
                payload.get("current_time") or defaults.get("current_time") or "10:30:00"
            ),
            "label": str(payload.get("label") or defaults["label"]),
            "timezone": str(payload.get("timezone") or defaults["timezone"]),
            "lock_fixed": bool(
                payload.get("lock_fixed") or payload.get("locked") or mode.lower() == "fixed"
            ),
        }
        workspace.settings = settings
        db.add(workspace)
        db.commit()
        return {
            "status": "applied",
            "applied": True,
            "demo_time_context": settings["demo_time_context"],
        }
    finally:
        if owns_db:
            db.close()


async def _briefing_priorities_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import ATTENTION_REQUIRED, cockpit_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        cockpit = cockpit_payload(workspace, db=db)
        priorities = []
        for item in (cockpit.get("attention_required") or ATTENTION_REQUIRED)[:3]:
            priorities.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "summary": item.get("sentence") or item.get("summary"),
                    "deadline": item.get("deadline"),
                    "tone": item.get("tone"),
                    "sources": item.get("source_refs") or item.get("sources") or [],
                }
            )
        return {
            "status": "ready",
            "priorities": priorities,
            "cockpit": {"decision_sentence": cockpit.get("decision_sentence")},
        }
    finally:
        if owns_db:
            db.close()


def _load_prefet_report_text() -> str:
    from pathlib import Path

    candidates = [
        Path(__file__).resolve().parents[3]
        / "docs"
        / "demo-data"
        / "sentinel-ci-kb"
        / "rapport-prefet-nawa-2026-05-10.md",
        Path(__file__).resolve().parents[2]
        / ".."
        / "docs"
        / "demo-data"
        / "sentinel-ci-kb"
        / "rapport-prefet-nawa-2026-05-10.md",
    ]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


async def _summarize_long_document_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    document_id = str(payload.get("document_id") or "report-prefet-nawa-2026-05-10")
    focus_topics = list(
        payload.get("focus_topics") or ["cacao", "diversification", "infrastructures"]
    )
    report_text = _load_prefet_report_text()
    citations = [
        {
            "source_id": "src-prefet-nawa-report-001",
            "document_id": document_id,
            "title": "Rapport Prefet Nawa — 10 mai 2026",
            "sent_at": "2026-05-10",
            "pages": 70,
        }
    ]
    key_topics = [
        topic for topic in focus_topics if topic.lower() in report_text.lower()
    ] or focus_topics
    summary_lines = [
        "Monsieur le Vice Premier Ministre, synthese des derniers echanges avec le Prefet de Nawa (rapport du 10 mai, ~70 pages) :",
        "- Contexte : region Nawa / Soubre, filiere cacao dominante, pression sur prix FCFA et infrastructures.",
        "- Points saillants : besoin de sechoirs, routes secondaires, electrifiation et diversification cultures.",
        "- Risques : volatilite prix export, dependance monoculture, fenetre climatique.",
        "- Recommandations prefet : transformation locale a court terme, montee en charge cooperative, financement mixte.",
    ]
    if "cacao" in report_text.lower():
        summary_lines.append(
            "- Emergence cacao : sections filiere et chiffrage publics confirment un gap transformation ~4,2-6,8 Mds FCFA."
        )
    return {
        "status": "ready",
        "summary_markdown": "\n".join(summary_lines),
        "key_topics": key_topics,
        "citations": citations,
        "document_id": document_id,
    }


async def _generate_recommendations_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    topic = str(payload.get("topic") or "cacao_diversification")
    chiffrage = bool(payload.get("chiffrage", True))
    options = [
        {
            "label": "Petite industrie transformation + diversification cultures",
            "summary": "Unité locale de transformation cacao + ananas/culture de couverture ; impact emploi Soubre.",
            "cost_estimate": "4,2 Mds FCFA" if chiffrage else None,
            "infra_required": ["Sechoirs", "Mini-usine", "Routes secondaires"],
            "confidence": 0.78,
        },
        {
            "label": "Cooperative regionale renforcee",
            "summary": "Montee en charge cooperative existante, formation qualite export et tracabilite.",
            "cost_estimate": "1,6 Mds FCFA" if chiffrage else None,
            "infra_required": ["Centres de collecte", "Formation"],
            "confidence": 0.71,
        },
        {
            "label": "PPP infrastructure sechoirs",
            "summary": "Partenariat public-prive sur sechoirs solaires ; partage risque prix.",
            "cost_estimate": "6,8 Mds FCFA" if chiffrage else None,
            "infra_required": ["Sechoirs solaires", "Electrification"],
            "confidence": 0.66,
        },
    ]
    return {
        "status": "ready",
        "topic": topic,
        "options": options,
        "sources": [
            {
                "source_id": "src-prefet-nawa-report-001",
                "document_id": "report-prefet-nawa-2026-05-10",
            }
        ],
        "human_validation_required": True,
    }


async def _draft_email_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    template_kind = str(payload.get("template_kind") or "customs_priority")
    target_id = str(payload.get("target_id") or "")
    context_refs = list(payload.get("context_refs") or [])
    if template_kind == "customs_priority":
        return {
            "status": "draft",
            "template_kind": template_kind,
            "subject": (
                "Priorisation dedouanement — composants drones Aerostar Dynamics, "
                "Centre Formation Drones Napié (cargo-abidjan-supply-001)"
            ),
            "recipient": "Direction generale des Douanes — Cellule Port Abidjan",
            "body_markdown": (
                "Monsieur le Directeur,\n\n"
                "Je vous prie de bien vouloir accorder une priorisation de traitement a la cargaison "
                "**MV ATLANTIC TRADER** (ref. cargo-abidjan-supply-001, IMO 9876543) : composants drones "
                "Aerostar Dynamics importes depuis la cote Est des Etats-Unis (hangars de formation, "
                "terrains d'apprentissage, laboratoires de cartographie) destines au "
                "**Centre International de Formation aux Métiers des Drones de Napié** "
                "(ref. proj-drone-centre-napie, region Poro / Nord ; investissement 100 M USD / 60 Mds FCFA ; "
                "alignement Côte d'Ivoire Innovation 2030).\n\n"
                "Le retard actuel (de l'ordre de 120 jours sur la sequence ouverture du centre) impacte le "
                "calendrier de demarrage des formations FAA et la perception institutionnelle du projet sur zone.\n\n"
                "Merci de me confirmer la fenetre de dedouanement envisagee.\n\n"
                "Bien cordialement,\nCabinet Vice Premier Ministre"
            ),
            "sources": [
                {"source_id": "src-maritime-paa-001"},
                {"source_id": "src-cabinet-brief-001", "project_id": "proj-drone-centre-napie"},
                {
                    "source_id": "src-abidjan-net-drone-napie-2025-07-16",
                    "title": "Abidjan.net — Lancement Centre Formation Drones Napié (16/07/2025)",
                    "kind": "rss_news_ci",
                },
            ],
            "requires_validation": True,
        }
    if template_kind == "customs_derogation":
        return {
            "status": "draft",
            "template_kind": template_kind,
            "subject": (
                "Demande de derogation operationnelle — cargaison composants drones "
                "Centre Formation Napié (MV Atlantic Trader)"
            ),
            "recipient": "Direction generale des Douanes — Chef de la cellule portuaire Abidjan",
            "body_markdown": (
                "Monsieur le Chef de la cellule douaniere,\n\n"
                "Faisant suite au proces-verbal de non-conformite declarative du 18 mai 2026 "
                "(ref. DGD-CI/CPA/PV-2026-05-018, page 2), je vous saisis pour solliciter une "
                "**derogation operationnelle ciblee** au benefice du cargo MV ATLANTIC TRADER "
                "(IMO 9876543, MMSI 627012345, ref. cargo-abidjan-supply-001).\n\n"
                "**Le cargo MV Atlantic Trader est distinct du lot non conforme** (LOT-INTRA-IMP-2026-05-018). "
                "Sa cargaison — composants drones AerostarDynamics (hangars de formation, terrains "
                "d'apprentissage, laboratoires de cartographie), importes depuis la cote Est des Etats-Unis — "
                "est exclusivement destinee au **Centre International de Formation aux Métiers des Drones "
                "de Napié** (ref. proj-drone-centre-napie, region Poro / Nord ; partenariat Agence de "
                "Developpement Regional du Poro, Aerostar Dynamics et CEPICI ; alignement Côte d'Ivoire "
                "Innovation 2030 ; investissement 100 M USD / 60 Mds FCFA ; cf. Abidjan.net, "
                "16 juillet 2025).\n\n"
                "Le gel temporaire du couloir d'entree Vridi, motive par la non-conformite d'un **autre** lot, "
                "affecte par effet collateral la cargaison drones Napié sans qu'aucune anomalie declarative "
                "n'ait ete relevee a son encontre.\n\n"
                "Au vu :\n"
                "- de la distinction documentaire claire entre les deux lots ;\n"
                "- du calendrier de livraison engageant l'ouverture du Centre Formation Drones de Napié "
                "(retard cumule de l'ordre de 120 jours en Q2 2026) ;\n"
                "- et de l'absence totale de non-conformite sur le lot drones Napié,\n\n"
                "je sollicite votre accord pour une derogation operationnelle permettant le dedouanement "
                "anticipe du cargo MV Atlantic Trader sous reserve des controles physiques habituels.\n\n"
                "Demande advisory soumise a validation Cabinet et a confirmation du ministere de l'Economie "
                "avant transmission officielle.\n\n"
                "Bien cordialement,\nCabinet Vice Premier Ministre"
            ),
            "sources": [
                {
                    "source_id": "customs-record-non-conformite-2026-05",
                    "title": "PV douanes - non conformite declarative (18 mai)",
                    "kind": "customs_pv",
                    "page": 2,
                },
                {"source_id": "src-maritime-paa-001"},
                {"source_id": "src-cabinet-brief-001", "project_id": "proj-drone-centre-napie"},
                {
                    "source_id": "src-abidjan-net-drone-napie-2025-07-16",
                    "title": "Abidjan.net — Lancement Centre Formation Drones Napié (16/07/2025)",
                    "kind": "rss_news_ci",
                },
            ],
            "context_refs": context_refs,
            "requires_validation": True,
            "advisory_only": True,
            "target_id": target_id or "cargo-abidjan-supply-001",
        }
    if template_kind == "strategic_report_long":
        return {
            "status": "draft",
            "template_kind": template_kind,
            "subject": "Rapport strategique - Diversification cacao region Nawa (anacarde transformee)",
            "recipient": "Cabinet Vice Premier Ministre + Ministere Economie + Ministere Agriculture",
            "body_markdown": (
                "# Rapport strategique - Diversification cacao region Nawa\n\n"
                "## Synthese executive\n"
                "L'option **anacarde transformee** ressort prioritaire (note Banque mondiale 2024, "
                "Reuters 2025, EUDR). Chiffrage indicatif : 4,2 - 6,8 Mds FCFA.\n\n"
                "## Classement des 7 cultures evaluees\n"
                "1. Anacarde transformee (prioritaire)\n"
                "2. Cooperative cacao tracable (court terme)\n"
                "3. Hevea (complement)\n"
                "4. Banane premium (niche)\n"
                "5. PPP sechoirs solaires (infrastructure)\n"
                "6. Palmier a huile RSPO (risque EUDR)\n"
                "7. Statu quo (non recommande)\n\n"
                "## Citations\n"
                "- Banque mondiale - Note climat-developpement 2024\n"
                "- Reglement europeen anti-deforestation (EUDR)\n"
                "- Reuters 2025 - filiere cajou Cote d'Ivoire\n"
                "- Rapport Prefet Nawa - 10 mai 2026 (pp. 42-58)\n\n"
                "Document **advisory-only** soumis a validation Conseil des Ministres."
            ),
            "sources": [
                {"source_id": "report-prefet-nawa-2026-05-10"},
                {"source_id": "sentinel-ci-anacarde-diversification-v1"},
                {"source_id": "src-banque-mondiale-2024"},
                {"source_id": "src-eudr-2023"},
                {"source_id": "src-reuters-cajou-2025"},
            ],
            "context_refs": context_refs,
            "requires_validation": True,
            "advisory_only": True,
            "target_id": target_id,
        }
    return {
        "status": "draft",
        "template_kind": template_kind,
        "subject": "Rapport de diversification cacao — region Nawa (arbitrage cabinet)",
        "recipient": "Ministere de l'Economie — Direction filieres",
        "body_markdown": (
            "# Rapport de diversification cacao — Nawa\n\n"
            "## Contexte\nSuite au rapport Prefet Nawa (10 mai) et aux echanges a Soubre.\n\n"
            "## Option recommandee\nPetite industrie de transformation + diversification cultures.\n\n"
            "## Chiffrage indicatif\n4,2 a 6,8 milliards FCFA (ordres de grandeur publics).\n\n"
            "## Prochaines etapes\nArbitrage cabinet, puis RDV ministere de l'Economie."
        ),
        "sources": [
            {
                "source_id": "src-prefet-nawa-report-001",
                "document_id": "report-prefet-nawa-2026-05-10",
            }
        ],
        "requires_validation": True,
        "target_id": target_id,
    }


async def _causal_drill_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Drill the evidence graph following ``caused_by`` from ``last_focus``.

    Used by ``aya.explain_why`` (Phase A). Returns a path with citations
    so the chat answer can chain "pourquoi -> pourquoi" with sources.
    """
    from app.models.workspace import Workspace
    from app.services.mission_room import evidence_graph_trace

    ctx = ctx or {}
    db = ctx.get("db")
    workspace_id = ctx.get("workspace_id")
    from_node = str(payload.get("from_node") or payload.get("last_focus") or "zone-nord")
    relation = str(payload.get("relation") or "caused_by")
    depth = int(payload.get("depth") or 4)

    if not db or not workspace_id:
        return {"status": "error", "reason": "missing_workspace_context", "path": []}
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        return {"status": "error", "reason": "workspace_not_found", "path": []}

    trace = evidence_graph_trace(
        workspace, from_node=from_node, relation=relation, depth=depth, db=db
    )
    path = trace.get("path") or []
    next_step = path[1] if len(path) > 1 else None
    next_node = (next_step or {}).get("node") or {}
    first_edge = ((path[0] if path else {}) or {}).get("edge") or {}
    return {
        "status": "ready",
        "from_node": from_node,
        "relation": relation,
        "depth": depth,
        "path": path,
        "next_focus": next_node.get("id") or from_node,
        "next_surface": next_node.get("next_surface") or {},
        "explanation": first_edge.get("explanation"),
        "narrative_short": next_node.get("narrative_short"),
        "citations": [
            {"source_id": str(ref), "kind": "evidence_ref"}
            for ref in (next_node.get("evidence_refs") or [])
        ],
    }


async def _schedule_meeting_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.demo_time_context import resolve_demo_date
    from app.services.workspace_calendar import summary_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        day = resolve_demo_date(workspace)
        cal = summary_payload(db, workspace, day=day)
        windows = cal.get("free_slots") or cal.get("available_windows") or []
        slot = (
            windows[0]
            if windows
            else {"start": f"{day.isoformat()}T16:30:00", "end": f"{day.isoformat()}T17:15:00"}
        )
        draft_id = f"draft-{uuid.uuid4().hex[:12]}"
        proposed = {
            "date": day.isoformat(),
            "time": str(slot.get("start", "")).split("T")[-1][:5]
            if isinstance(slot.get("start"), str)
            else "16:30",
            "location": "Ministere de l'Economie — Plateau",
            "duration_min": int(payload.get("duration_min") or 45),
            "participants": ["Vice Premier Ministre", "Ministre de l'Economie", "AYA"],
            "topic": payload.get("topic") or "Diversification cacao",
        }
        return {
            "status": "proposal",
            "applied": False,
            "requires_validation": True,
            "proposed_slot": proposed,
            "calendar_event_draft_id": draft_id,
            "proposal": proposed,
        }
    finally:
        if owns_db:
            db.close()


async def _territorial_action_window_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import map_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        body = map_payload(workspace, db=db)
        target_id = payload.get("target_id") or payload.get("zone_id")
        windows = body.get("recommended_windows") or []
        if target_id:
            windows = [
                window for window in windows if window.get("target_id") == target_id
            ] or windows
        return {"status": "ready", "recommended_windows": windows, "map": body.get("map")}
    finally:
        if owns_db:
            db.close()


async def _map_layer_read_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.workspace_maps import mission_room_map_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        map_row = _workspace_map_for_skill(db, workspace, payload)
        return mission_room_map_payload(db, workspace, map_row=map_row)
    finally:
        if owns_db:
            db.close()


def _workspace_map_for_skill(db: Any, workspace: Any, payload: dict[str, Any]) -> Any:
    """Resolve an explicit map reference or the workspace's seeded map.

    The default must remain workspace-aware: Octocity owns a distinct fixture
    and must never inherit the Sentinel map slug merely because a skill caller
    omitted ``map_slug``.
    """
    from app.services.workspace_maps import ensure_workspace_map_seed, get_workspace_map

    seeded_map = ensure_workspace_map_seed(db, workspace)
    map_ref = payload.get("map_slug") or payload.get("map_id")
    if map_ref is None:
        return seeded_map
    return get_workspace_map(db, workspace, str(map_ref))


async def _map_zone_score_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.workspace_jobs import create_workspace_job, serialize_job
    from app.services.workspace_maps import score_map_zones

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        map_row = _workspace_map_for_skill(db, workspace, payload)
        job = create_workspace_job(
            db,
            workspace,
            None,
            kind="map_zone_scoring",
            title=f"Scoring carte · {map_row.name}",
            input_ref={"map_id": map_row.id, "slug": map_row.slug},
            status="queued",
        )
        result = score_map_zones(db, workspace, map_row, job=job)
        db.commit()
        return {"job": serialize_job(job), "result": result}
    finally:
        if owns_db:
            db.close()


async def _map_signal_attach_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from uuid import uuid4

    from app.models.workspace_map import WorkspaceMapSignal, WorkspaceMapZone

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        map_row = _workspace_map_for_skill(db, workspace, payload)
        zone = (
            db.query(WorkspaceMapZone)
            .filter(
                WorkspaceMapZone.map_id == map_row.id,
                WorkspaceMapZone.zone_key == str(payload["zone_key"]),
            )
            .first()
        )
        if not zone:
            return {"status": "not_found", "warning": "map_zone_not_found"}
        signal = WorkspaceMapSignal(
            id=str(uuid4()),
            map_id=map_row.id,
            zone_id=zone.id,
            source_kind=str(payload.get("source_kind") or "skill"),
            source_id=str(payload.get("source_id") or ""),
            title=str(payload["title"]),
            summary=str(payload.get("summary") or ""),
            weight=int(payload.get("weight") or 10),
            confidence=float(payload.get("confidence") or 0.65),
            occurred_at=datetime.utcnow(),
            meta_data=dict(payload.get("metadata") or {}),
        )
        db.add(signal)
        db.commit()
        return {
            "status": "attached",
            "map_id": map_row.id,
            "map_slug": map_row.slug,
            "signal": {"id": signal.id, "zone_key": zone.zone_key, "title": signal.title},
        }
    finally:
        if owns_db:
            db.close()


async def _map_recommendation_generate_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.workspace_maps import mission_room_map_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        map_row = _workspace_map_for_skill(db, workspace, payload)
        body = mission_room_map_payload(db, workspace, map_row=map_row)
        recommendations = []
        for zone in body.get("zones") or []:
            recommendations.extend(zone.get("scenario_options") or [])
        return {
            "recommendations": recommendations,
            "score_summary": body.get("score_summary") or {},
        }
    finally:
        if owns_db:
            db.close()


async def _map_command_apply_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.workspace_maps import build_map_command

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        map_row = _workspace_map_for_skill(db, workspace, payload)
        command = build_map_command(
            db,
            workspace,
            map_id_or_slug=map_row.id,
            intent=str(payload.get("intent") or "focus_zone"),
            target=payload.get("target"),
            layers=payload.get("layers"),
            basemap=payload.get("basemap"),
            camera=payload.get("camera"),
            annotation=payload.get("annotation"),
        )
        db.commit()
        return {"status": "ready", **command}
    finally:
        if owns_db:
            db.close()


async def _source_registry_refresh_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import cockpit_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        cockpit = cockpit_payload(workspace, db=db)
        return {
            "status": "ready",
            "source_health": cockpit.get("source_freshness") or {},
            "layers": cockpit.get("monitoring_layers") or [],
            "decision_posture": cockpit.get("decision_posture") or {},
        }
    finally:
        if owns_db:
            db.close()


async def _osint_signal_prioritize_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import news_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        news = news_payload(workspace, db=db)
        return {
            "status": "ready",
            "priorities": news.get("executive_alerts") or news.get("signals") or [],
            "geographic_tiers": news.get("geographic_priority") or news.get("geo_sections") or [],
            "source_health": news.get("source_health") or {},
        }
    finally:
        if owns_db:
            db.close()


async def _rumor_origin_trace_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import news_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        news = news_payload(workspace, db=db)
        trace = (news.get("social_listening") or {}).get("rumor_origins") or []
        rumor = trace[0] if trace else (news.get("rumor_trace") or {})
        return {
            "status": "ready",
            "trace": rumor,
            "social_listening": news.get("social_listening") or {},
            "advisory_only": True,
        }
    finally:
        if owns_db:
            db.close()


async def _evidence_graph_build_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import evidence_graph_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        return evidence_graph_payload(workspace, db=db)
    finally:
        if owns_db:
            db.close()


async def _situation_posture_score_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import cockpit_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        cockpit = cockpit_payload(workspace, db=db)
        posture = cockpit.get("decision_posture") or {}
        return {
            "status": "ready",
            "score": posture.get("score"),
            "label": posture.get("label"),
            "axes": posture.get("axes") or [],
            "modes": posture.get("modes") or [],
        }
    finally:
        if owns_db:
            db.close()


async def _maritime_snapshot_read_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.workspace_maps import ensure_workspace_map_seed, mission_room_map_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_workspace_map_seed(db, workspace)
        mapped = mission_room_map_payload(db, workspace)
        map_system = mapped.get("map_system") or {}
        return {
            "status": "ready",
            "maritime_snapshot": map_system.get("maritime_snapshot") or {},
            "source_health": (map_system.get("source_health") or {}),
            "ports": (map_system.get("maritime_snapshot") or {}).get("ports") or [],
            "events": (map_system.get("maritime_snapshot") or {}).get("events") or [],
        }
    finally:
        if owns_db:
            db.close()


async def _decision_option_rank_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import decisions_payload

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        decisions = decisions_payload(workspace, db=db)
        options = list(payload.get("options") or decisions.get("scenario_options") or [])
        ranked = sorted(
            options,
            key=lambda item: (
                int(item.get("recommended_score") or item.get("score") or item.get("impact") or 0),
                int(item.get("confidence") or 0),
            ),
            reverse=True,
        )
        return {
            "status": "ready",
            "recommended": ranked[0] if ranked else None,
            "alternatives": ranked[1:],
            "human_validation_required": True,
        }
    finally:
        if owns_db:
            db.close()


async def _draft_response_email_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.mission_room import draft_instruction_payload

    ctx = ctx or {}
    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not ctx.get("db")
    try:
        return draft_instruction_payload(
            workspace=workspace,
            actor=str(ctx.get("actor") or payload.get("actor") or "system:draft_response_email_v1"),
            target_id=str(payload.get("target_id") or "package-rumeur-emoi"),
            target_type=str(payload.get("target_type") or "communication_email"),
            instruction_type=str(payload.get("instruction_type") or "response_email"),
            db=db,
        )
    finally:
        if owns_db:
            db.close()


async def _visual_source_read_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.visual_intelligence import dashboard_payload, ensure_visual_intelligence_seed

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_visual_intelligence_seed(db, workspace)
        return dashboard_payload(db, workspace)
    finally:
        if owns_db:
            db.close()


async def _visual_snapshot_capture_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.visual_intelligence import (
        dispatch_visual_capture_job,
        ensure_visual_intelligence_seed,
        get_source,
        list_sources,
        queue_visual_capture,
    )

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        ensure_visual_intelligence_seed(db, workspace)
        source_id = payload.get("source_id")
        source = (
            get_source(db, workspace, str(source_id))
            if source_id
            else (list_sources(db, workspace)[0])
        )
        job = queue_visual_capture(db, workspace, source)
        db.commit()
        task_id = dispatch_visual_capture_job(db, workspace, job, source)
        db.commit()
        return {"job_id": job.id, "status": job.status, "task_id": task_id}
    finally:
        if owns_db:
            db.close()


async def _visual_snapshot_analyze_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.models.workspace_visual import WorkspaceVisualObservation
    from app.services.visual_intelligence import serialize_observation

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        capture_id = str(payload.get("capture_id") or "")
        observation = (
            db.query(WorkspaceVisualObservation)
            .filter(
                WorkspaceVisualObservation.workspace_id == workspace.id,
                WorkspaceVisualObservation.capture_id == capture_id,
            )
            .order_by(WorkspaceVisualObservation.created_at.desc())
            .first()
        )
        if not observation:
            return {"status": "not_found", "warning": "visual_observation_not_found"}
        return {"status": "ready", "observation": serialize_observation(observation)}
    finally:
        if owns_db:
            db.close()


async def _visual_observation_sync_knowledge_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.models.workspace_visual import WorkspaceVisualObservation
    from app.services.visual_intelligence import (
        VISUAL_COLLECTION_SLUG,
        sync_observation_to_knowledge,
    )

    db, workspace = _calendar_db_and_workspace(payload, ctx)
    owns_db = not (ctx or {}).get("db")
    try:
        observation_id = str(payload.get("observation_id") or "")
        observation = (
            db.query(WorkspaceVisualObservation)
            .filter(
                WorkspaceVisualObservation.workspace_id == workspace.id,
                WorkspaceVisualObservation.id == observation_id,
            )
            .first()
        )
        if not observation:
            return {"status": "not_found", "warning": "visual_observation_not_found"}
        object_key = sync_observation_to_knowledge(db, workspace, observation)
        db.commit()
        return {"status": "synced", "collection": VISUAL_COLLECTION_SLUG, "object_key": object_key}
    finally:
        if owns_db:
            db.close()


async def _sharepoint_ingestion_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    # Real ingestion goes through the OAuth/MSAL flow in
    # `app.services.connectors.sharepoint_otp.ingester`. Triggering that
    # flow from a background skill still needs a tenant-scoped token
    # context, which is not currently passed in. Until the builder
    # surfaces that, we return a structured degraded response rather
    # than crash the run.
    logger.info(
        "sharepoint_ingestion_v1: degraded (missing tenant token context)",
        site_url=payload.get("site_url"),
    )
    return {
        "files": 0,
        "skipped": 0,
        "status": "degraded",
        "warning": "sharepoint_token_context_unavailable",
    }


async def _voice_transcribe_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider((payload.get("provider") or "cascade_openai"))
    audio_bytes = _audio_bytes_from_payload(payload)
    result = await provider.transcribe(
        audio_bytes,
        filename=payload.get("filename") or "recording.webm",
        content_type=payload.get("content_type") or "audio/webm",
        language=payload.get("language") or payload.get("input_language") or "fr",
    )
    return {
        "transcript": result.get("transcript") or result.get("text", ""),
        "text": result.get("text", ""),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "fallback": result.get("fallback", False),
    }


async def _voice_tts_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider((payload.get("provider") or "cascade_openai"))
    result = await provider.synthesize_bytes(
        payload["text"],
        voice=payload.get("voice"),
        instructions=payload.get("instructions"),
    )
    return {
        "audio_url": None,
        "audio_base64": result.get("audio_base64"),
        "content_type": result.get("content_type"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "bytes": result.get("bytes"),
    }


async def _voice_realtime_session_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.voice_runtime import (
        build_openai_realtime_session,
        list_voice_runtime_providers,
        resolve_voice_runtime_slug,
    )

    ctx = ctx or {}
    provider = resolve_voice_runtime_slug(payload.get("provider") or ctx.get("voice_provider"))
    session = build_openai_realtime_session(
        model=payload.get("model"),
        voice=payload.get("voice") or "marin",
        instructions=payload.get("instructions"),
        input_language=payload.get("language") or payload.get("input_language"),
        output_language=payload.get("output_language"),
        capability=payload.get("capability") or "voice2voice_interaction",
        metadata={"transport": payload.get("transport") or "backend_ws"},
    )
    catalog = list_voice_runtime_providers()
    provider_meta = next(
        (item for item in catalog.get("providers", []) if item.get("slug") == provider), None
    )
    return {
        "provider": provider,
        "model": payload.get("model"),
        "transport": payload.get("transport") or "backend_ws",
        "session": session if provider == "openai_realtime" else None,
        "capabilities": (provider_meta or {}).get("capabilities", {}),
        "fallback_policy": payload.get("fallback_policy") or "cascade_openai",
        "events": catalog.get("events", []),
    }


async def _voice_realtime_transcribe_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider(payload.get("provider") or "cascade_openai")
    audio_bytes = _audio_bytes_from_payload(payload)
    result = await provider.transcribe(
        audio_bytes,
        filename=payload.get("filename") or "recording.webm",
        content_type=payload.get("content_type") or "audio/webm",
        language=payload.get("language") or payload.get("input_language") or "fr",
    )
    text = result.get("text") or result.get("transcript") or ""
    return {
        "transcript": text,
        "text": text,
        "text_events": [
            {"type": "text.partial", "text": text, "provider": result.get("provider")},
            {"type": "text.final", "text": text, "provider": result.get("provider")},
        ],
        "model": result.get("model"),
        "provider": result.get("provider"),
        "requested_provider": result.get("requested_provider") or payload.get("provider"),
        "fallback": result.get("fallback", False),
        "fallback_reason": result.get("fallback_reason"),
    }


async def _voice_realtime_speak_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider(payload.get("provider") or "cascade_openai")
    result = await provider.synthesize_bytes(
        payload["text"],
        voice=payload.get("voice"),
        instructions=payload.get("instructions"),
    )
    return {
        "audio_base64": result.get("audio_base64"),
        "content_type": result.get("content_type"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "requested_provider": result.get("requested_provider") or payload.get("provider"),
        "bytes": result.get("bytes"),
        "fallback": result.get("fallback", False),
        "events": [
            {"type": "audio.out", "bytes": result.get("bytes"), "provider": result.get("provider")}
        ],
    }


async def _voice_realtime_translate_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.voice_runtime import get_voice_runtime_provider

    provider = get_voice_runtime_provider(payload.get("provider") or "openai_realtime")
    if not provider.capabilities.get("translation"):
        return {
            "status": "degraded",
            "warning": "provider_capability_unsupported",
            "provider": provider.slug,
            "source_text": payload.get("text") or "",
            "translated_text": payload.get("text") or "",
        }
    return {
        "status": "deferred",
        "provider": provider.slug,
        "model": payload.get("model"),
        "source_language": payload.get("source_language") or payload.get("language"),
        "target_language": payload.get("target_language") or payload.get("output_language"),
        "events": ["translation.partial", "translation.final"],
    }


async def _voice_oracle_turn_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.knowledge_capture import evaluate_expert_answer

    evaluation = evaluate_expert_answer(
        answer=payload.get("answer") or payload.get("text") or "",
        question=payload.get("question"),
        gap=payload.get("gap"),
    )
    verdict = evaluation.get("verdict")
    action = "next_prompt" if verdict != "sufficient" else "capture_fact"
    return {
        "action": action,
        "evaluation": evaluation,
        "events": [{"type": "oracle.action", "action": action, "verdict": verdict}],
    }


async def _voice_tandem_oracle_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.voice_tandem_oracle import VoiceTandemOracle

    ctx = ctx or {}
    oracle = VoiceTandemOracle(min_interval_ms=0, min_delta_chars=0)
    turn_id = str(payload.get("turn_id") or ctx.get("turn_id") or "flow-turn")
    duration_ms = int(payload.get("duration_ms") or 0)
    events: list[dict[str, Any]] = []
    partial_text = payload.get("partial_text") or payload.get("text")
    if partial_text:
        events.extend(
            oracle.observe_partial(
                str(partial_text),
                turn_id=turn_id,
                input_state={
                    "transcript_state": "partial",
                    "provider": payload.get("provider"),
                    "transport": payload.get("transport") or "backend_ws",
                },
                output_state={"oracle_state": "thinking"},
                duration_ms=duration_ms,
                force=True,
            )
        )
    final_text = payload.get("final_text") or (
        payload.get("text") if payload.get("is_final") else None
    )
    if final_text:
        events.extend(
            oracle.commit_final(
                str(final_text),
                turn_id=turn_id,
                evaluation=payload.get("evaluation")
                if isinstance(payload.get("evaluation"), dict)
                else None,
                next_prompt=payload.get("next_prompt"),
                sources=payload.get("sources")
                if isinstance(payload.get("sources"), list)
                else None,
                duration_ms=duration_ms,
            )
        )
    return {
        "mode": "tandem_oracle",
        "committed": any(event.get("type") == "oracle.commit" for event in events),
        "events": events,
        "provider": payload.get("provider"),
        "transport": payload.get("transport") or "backend_ws",
        "fallback_policy": payload.get("fallback_policy"),
    }


def _audio_bytes_from_payload(payload: dict[str, Any]) -> bytes:
    if payload.get("audio_bytes"):
        raw = payload["audio_bytes"]
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, str):
            return raw.encode("latin1")
        return bytes(raw)
    if payload.get("audio_base64"):
        return base64.b64decode(payload["audio_base64"])
    audio_ref = payload.get("audio_ref")
    if audio_ref:
        path = Path(audio_ref)
        if not path.exists() or not path.is_file():
            raise ValueError("voice_transcribe_v1: audio_ref does not resolve to a local file")
        return path.read_bytes()
    raise ValueError(
        "voice_transcribe_v1: one of audio_bytes, audio_base64 or audio_ref is required"
    )


async def _knowledge_gap_analysis_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.knowledge_capture import build_knowledge_gaps

    return {
        "gaps": build_knowledge_gaps(
            objective=payload["objective"],
            expert_profile=payload.get("expert_profile"),
            context_snapshot=payload.get("context") or {},
            knowledge_refs=payload.get("knowledge_refs") or [],
        )
    }


async def _expert_interview_plan_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.knowledge_capture import build_interview_plan

    return {
        "plan": build_interview_plan(
            objective=payload["objective"],
            expert_profile=payload.get("expert_profile"),
            duration_minutes=int(payload.get("duration_minutes") or 20),
            gaps=payload.get("gaps") or [],
            context_snapshot=payload.get("context") or {},
        )
    }


async def _expert_answer_evaluator_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.knowledge_capture import evaluate_expert_answer

    return evaluate_expert_answer(
        answer=payload["answer"],
        question=payload.get("question"),
        gap=payload.get("gap"),
    )


async def _capture_structuring_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    # The persisted endpoint uses `structure_capture_payload` on an ORM
    # session. The skill contract also supports already-serialized session
    # payloads for DAG/runtime callers.
    session = payload["session"]
    transcript = session.get("transcript") or []
    evaluations = session.get("evaluations") or []
    captured_facts = session.get("captured_facts") or [
        {
            "id": f"fact-{turn.get('id')}",
            "text": turn.get("text", ""),
            "source": "expert_session",
            "confidence": next(
                (ev.get("score") for ev in evaluations if ev.get("turn_id") == turn.get("id")),
                0.5,
            ),
            "needs_review": True,
        }
        for turn in transcript
        if turn.get("speaker") == "expert"
    ]
    proposal = {
        "session_id": session.get("id"),
        "title": session.get("title"),
        "objective": session.get("objective"),
        "captured_facts": captured_facts,
        "open_questions": [
            {
                "gap_id": ev.get("gap_id"),
                "reason": ev.get("verdict"),
                "follow_up": ev.get("follow_up"),
            }
            for ev in evaluations
            if ev.get("verdict") != "sufficient"
        ],
        "transcript": transcript,
        "review": {"required": True},
    }
    return {"proposal": proposal}


async def _audit_log_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Persist a compliance event through the shared audit writer.

    Uses ``emit_audit_event`` — the same path ``chain.version.created`` and
    ``system.updated`` take — so the row lands where the governance screens
    read it (``GET /api/v1/audit``, which filters strictly on
    ``workspace_id``) rather than merely in the database.

    This skill never reports success it did not achieve. It raises when the
    row cannot be written, and it raises when there is no workspace to
    attribute the record to: an audit entry nobody can read is not an audit
    entry, and reporting ``recorded`` for one is the same lie as reporting it
    for a write that never happened. Raising is loud without being fatal — the
    walker marks the node failed in the trace and carries on, so a ledger
    outage costs a red node, not the run.
    """
    from app.services.audit_logger import emit_audit_event

    ctx = ctx or {}
    event_type = str(payload.get("event_type") or "").strip()
    if not event_type:
        raise ValueError("audit_log_v1 requires an event_type")
    details = payload.get("details")
    if details is not None and not isinstance(details, dict):
        raise ValueError("audit_log_v1 details must be an object")
    workspace_id = ctx.get("workspace_id") or payload.get("workspace_id")
    if not workspace_id:
        raise ValueError(
            "audit_log_v1 cannot record an event with no workspace to attribute it to"
        )

    event_id = emit_audit_event(
        workspace_id=str(workspace_id),
        event_type=event_type,
        actor=str(
            payload.get("actor") or ctx.get("actor") or ctx.get("user_id") or "system"
        ),
        details=details or {},
        trace_id=ctx.get("run_id"),
        agent_id=ctx.get("system_id"),
        severity=str(payload.get("severity") or "info"),
    )
    if event_id is None:
        raise RuntimeError(f"audit ledger write failed for event_type={event_type!r}")

    logger.info(
        "audit_log_v1: event recorded",
        event_id=event_id,
        event_type=event_type,
        workspace_id=workspace_id,
        ts=datetime.utcnow().isoformat(),
    )
    return {
        "id": event_id,
        "status": "recorded",
        # This implementation only writes a structured logger event.  It has
        # no generation, embedding or other token-provider branch, so an
        # explicit measured zero is contractually true for the executed path.
        **contractual_zero_token_usage("audit_log:structured_logger_only"),
    }


async def _ollama_llm_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.model_clients.ollama_client import OllamaClient

    client = OllamaClient()
    model = payload.get("model") or "deepseek-r1:14b"
    result = await client.generate(model=model, prompt=payload["prompt"])
    return {
        "completion": result.get("response") or result.get("content", ""),
        "model": model,
    }


async def _azure_llm_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    # Azure OpenAI is OpenAI-compatible — reuse the OpenAI client.
    from app.services.model_clients.openai_client import OpenAIClient

    client = OpenAIClient()
    if not client.api_key:
        return {
            "completion": "",
            "status": "degraded",
            "warning": "openai_key_unavailable",
        }

    ctx = ctx or {}
    token_sink = ctx.get("token_sink")
    model = payload.get("model") or "gpt-4o-mini"
    prompt = payload["prompt"]

    # Stream token-by-token when the run engine provided a sink (Vague D
    # / D2). Every delta is pushed to the live SSE bus so the cockpit's
    # Execution terminal can render a typewriter effect; we also
    # accumulate the final text so the non-streaming contract
    # (`completion` field) keeps working for replay.
    if callable(token_sink):
        try:
            parts: list[str] = []
            async for chunk in client.stream(model=model, prompt=prompt):
                delta = chunk.get("delta") or ""
                if delta:
                    parts.append(delta)
                    token_sink(delta)
            return {
                "completion": "".join(parts),
                "model": model,
                "streamed": True,
            }
        except Exception as exc:  # noqa: BLE001 — fall back to non-streaming
            logger.warning(
                "azure_llm_v1: streaming failed, falling back",
                error=str(exc),
            )

    result = await client.generate(model=model, prompt=prompt)
    return {
        "completion": result.get("content", ""),
        "model": result.get("model"),
        "usage": result.get("usage", {}),
    }


async def _chain_naive_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.rag.chains import answer_naive

    ctx = ctx or {}
    return await answer_naive(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        workspace_slug=ctx.get("workspace_slug") or payload.get("workspace_slug"),
        **_rag_runtime_kwargs(payload, ctx),
    )


async def _chain_hybrid_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.rag.chains import answer_hybrid

    ctx = ctx or {}
    return await answer_hybrid(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        workspace_slug=ctx.get("workspace_slug") or payload.get("workspace_slug"),
        **_rag_runtime_kwargs(payload, ctx),
    )


async def _chain_mixed_hah_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    from app.services.rag.chains import answer_mixed_hah

    ctx = ctx or {}
    return await answer_mixed_hah(
        query=payload["query"],
        context_id=payload.get("context_id"),
        workspace_id=ctx.get("workspace_id"),
        workspace_slug=ctx.get("workspace_slug") or payload.get("workspace_slug"),
        **_rag_runtime_kwargs(payload, ctx),
    )


# ---------------------------------------------------------------------------
# Provider-neutral chat-agentic skills (chat_agentic_thinking_v1 DAG)
#
# These three wrappers back the `andritz_chat_agentic_v3` flow. They are
# PROVIDER-NEUTRAL by contract: the LLM ones resolve their client through
# ``ModelRouter.get_client({"provider","model"})`` and NEVER instantiate a
# provider client directly (no ``OpenAIClient``/``OllamaClient`` here). The
# effective model comes from the node payload ``model`` (= ``system.default_model``)
# else the router default. I/O contracts are frozen in
# ``docs/chat-agentic-thinking-spec.md`` §7 and mirror the node ports of the
# artifact, so downstream ``inputs_map`` VariableRefs resolve.
# ---------------------------------------------------------------------------
_KNOWN_PROVIDERS = {
    "ollama",
    "openai",
    "azure",
    "anthropic",
    "vllm",
    "openrouter",
    "gemini",
    "llamacpp",
    "lmstudio",
    "lmdeploy",
    "sglang",
}

_PLAN_ENUMS = {
    "action": ("answer", "clarify", "reject_oos"),
    "mode": ("fast", "balanced", "deep"),
    "latency_profile": ("fast", "balanced", "deep"),
    "retrieval_profile": ("oracle_fast", "chat", "deep_async"),
    "rag_pipeline_mode": ("chah", "auto"),
}

# Per-lane retrieval BUDGETS — must match the classic path
# (``chat._apply_retrieval_budget_policy``) so arm B reaches the SAME candidate
# pool / synthesis budget as the deterministic ``/chat`` arm (recall-parity fix
# 2026-06-26). A lone ``top_k`` pin makes ``get_retrieval_profile`` treat the
# request as a user pin and COLLAPSE synthesis_k/candidate_pool_k down to top_k
# (DAG returned ~6 ctx vs classic ~12, and missed carrier chunks). Carrying the
# full triple keeps explicit_budget=True so the pool is never collapsed.
_LANE_BUDGETS = {
    "fast": {"top_k": 5, "source_display_k": 5, "synthesis_k": 12, "candidate_pool_k": 20},
    "balanced": {"top_k": 8, "source_display_k": 8, "synthesis_k": 16, "candidate_pool_k": 40},
    "deep": {"top_k": 8, "source_display_k": 8, "synthesis_k": 24, "candidate_pool_k": 80},
}

# Per-mode retrieval defaults — the planner exposes the ``retrieval`` object the
# retrieve_* nodes consume via inputs_map (bug P0 #1). Kept coherent with
# ``mode`` AND with the classic lane budgets above so the deep branch carries
# deep_retrieval=True + the full deep budget downstream.
_RETRIEVAL_BY_MODE = {
    "fast": {
        "latency_profile": "fast",
        "retrieval_profile": "oracle_fast",
        "top_k": 5,
        "synthesis_k": 12,
        "candidate_pool_k": 20,
        "rag_pipeline_mode": "chah",
        "deep_retrieval": False,
    },
    "balanced": {
        "latency_profile": "balanced",
        "retrieval_profile": "chat",
        "top_k": 8,
        "synthesis_k": 16,
        "candidate_pool_k": 40,
        "rag_pipeline_mode": "chah",
        "deep_retrieval": False,
    },
    "deep": {
        "latency_profile": "deep",
        "retrieval_profile": "deep_async",
        "top_k": 8,
        "synthesis_k": 24,
        "candidate_pool_k": 80,
        "rag_pipeline_mode": "chah",
        "deep_retrieval": True,
    },
}

# A single-project equipment inventory now has its own bounded recall floor in
# ``rag.context``. Keep enough synthesis slots for its six diversified evidence
# rows, while avoiding the 80-candidate/deep cross-encoder lane that repeatedly
# exhausted the 40 s interactive membrane after recall was already complete.
_SINGLE_PROJECT_INVENTORY_RETRIEVAL = {
    **_RETRIEVAL_BY_MODE["balanced"],
    "synthesis_k": 18,
}

_SELF_CORRECT_ACTIONS = ("escalate_deep", "translate", "declare_partial")

# Inventory / cross-project / enumeration questions need the DEEP lane to
# aggregate across documents (the planner under-routes them to balanced, fix
# 2026-06-26): "quels projets…", "liste…", "tous les projets", "sur quels", etc.
_INVENTORY_RE = re.compile(
    r"\b(quels?\s+projets?|which\s+projects?|sur\s+quels?|tous\s+les\s+projets?|"
    r"welche\s+projekte|liste[- ]?(?:moi|nous)?|lister|list\s+all|énumère|enumere|"
    r"across\s+projects?|cross[- ]project|combien\s+de)\b",
    re.IGNORECASE,
)

# Named Andritz machines / systems / brands that GUARANTEE the query is in-corpus
# — used to gate a false ``reject_oos``. QMS-12 etc. are NOT project codes
# but ARE in-corpus, so the planner must never reject them (fix 2026-06-26).
_KNOWN_ENTITY_RE = re.compile(
    r"\b(qualiscan|qms[\s-]?\d+|uraca|etachrom|sinamics|simotics|jetlace|servo\s*x|"
    r"pollrich|continental\s*gvjs|wilo|ksb|geotex|excelle|starter|kd724)\b",
    re.IGNORECASE,
)


def _is_inventory_query(query: str) -> bool:
    return bool(_INVENTORY_RE.search(query or ""))


def _project_inventory_passage(inventory: Any) -> Optional[dict[str, Any]]:
    """Turn the project_code facet into a top authoritative context passage.

    ``retrieve_rag_context`` attaches the exhaustive cross-project enumeration
    (shape from ``project_inventory.build_project_inventory``) for transversal
    inventory questions. Surfaced as the #1 passage so the grounded synthesis
    LISTS the projects (parity with the classic transversal_inventory answer).
    """
    if not isinstance(inventory, dict):
        return None
    projects = inventory.get("projects") or []
    codes = [
        str(p.get("project_code"))
        for p in projects
        if isinstance(p, dict) and p.get("project_code")
    ]
    if not codes:
        return None
    terms = ", ".join(str(t) for t in (inventory.get("terms") or []) if t) or "cet equipement"
    total = inventory.get("total_projects") or len(codes)
    suffix = " (liste tronquee)" if inventory.get("truncated") else ""
    enumeration = (
        f"Inventaire transversal (facette project_code, source autoritative) — "
        f"projets utilisant {terms} : {total} projet(s) au total{suffix} : "
        + ", ".join(codes)
        + "."
    )
    return {
        "content": enumeration,
        "score": 999.0,
        "metadata": {"source": "project_inventory_facet", "kind": "transversal_inventory"},
    }


def _authoritative_query_project_codes(
    query: str,
    payload: dict[str, Any],
    ctx: dict[str, Any],
) -> set[str]:
    """Validate bare numeric5 candidates against the bound source ledger.

    The lookup is intentionally collection-exact and never falls back to every
    collection in the workspace. It only answers the early Agentic clarify/OOS
    gate; the corpus planner remains the owner of the eventual retrieval filter.
    """

    candidates = set(numeric_project_candidates(query))
    if not candidates:
        return set()
    workspace_id = ctx.get("workspace_id") or payload.get("workspace_id")
    contract = (
        ctx.get("retrieval_contract")
        if isinstance(ctx.get("retrieval_contract"), dict)
        else {}
    )
    collection_ref = (
        contract.get("collection")
        or contract.get("primary_collection")
        or ctx.get("context_collection")
        or payload.get("context_collection")
    )
    if not workspace_id or not str(collection_ref or "").strip():
        return set()

    try:
        from app.db.base import SessionLocal
        from app.models.knowledge_collection import (
            KnowledgeCollection,
            KnowledgeCollectionSource,
        )

        db = SessionLocal()
        try:
            project_value = KnowledgeCollectionSource.source_metadata[
                "project_code"
            ].as_string()
            rows = (
                db.query(project_value)
                .join(
                    KnowledgeCollection,
                    KnowledgeCollectionSource.collection_id == KnowledgeCollection.id,
                )
                .filter(
                    KnowledgeCollection.workspace_id == workspace_id,
                    (
                        (KnowledgeCollection.slug == str(collection_ref))
                        | (KnowledgeCollection.id == str(collection_ref))
                    ),
                    KnowledgeCollection.status == "ready",
                    KnowledgeCollectionSource.status.in_(
                        ("ready", "indexed", "deduplicated")
                    ),
                    project_value.in_(sorted(candidates)),
                )
                .distinct()
                .limit(len(candidates))
                .all()
            )
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - an unavailable facet fails closed.
        logger.warning(
            "skills_registry: authoritative project-code lookup failed",
            workspace_id=workspace_id,
            collection=str(collection_ref),
            error=str(exc),
        )
        return set()
    return {
        str(row[0] or "").strip().upper()
        for row in rows
        if str(row[0] or "").strip().upper() in candidates
    }


def _has_known_corpus_anchor(
    query: str,
    *,
    known_project_codes: set[str] | None = None,
) -> bool:
    """True when the query names a known project/machine/system in the corpus."""
    q = query or ""
    return bool(
        extract_query_project_codes(q, known_codes=known_project_codes)
        or _SPECIAL_CORPUS_REFERENCE_RE.search(q)
        or _KNOWN_ENTITY_RE.search(q)
    )


# Equipment references that are valid corpus anchors but not project identities.
# Project identity itself is owned by ``project_references``.
_SPECIAL_CORPUS_REFERENCE_RE = re.compile(r"\b(?:D\.\d{2,3}|CU\d{3}[A-Z]?-?\d?)\b")
_QUESTION_WORD_RE = re.compile(
    r"\b(quel|quelle|comment|pourquoi|where|how|what|why|wo|wie|was|warum)\b", re.IGNORECASE
)
# Schema-example phrases the planner must never echo back as a real scope/plan.
_PLACEHOLDER_SCOPES = {
    "perimetre de recherche",
    "périmètre de recherche",
    "perimetre cible",
    "scope_hint",
    "the concrete search scope",
    "search scope",
    "si action=clarify",
    "...",
}


def _is_placeholder_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return text in _PLACEHOLDER_SCOPES or text.startswith(("<", "the concrete search"))


def _assess_clarify_gate(
    query: str,
    *,
    has_history: bool,
    known_project_codes: set[str] | None = None,
) -> dict[str, Any]:
    """Deterministic sufficiency check — should a clarify actually be allowed?

    Mirrors ``agentic_chat_spike.assess_sufficiency``: clarify is only justified
    when the request is genuinely ambiguous AND carries no anchor (project code,
    explicit question on a named subject, or conversational history).
    """
    q = (query or "").strip()
    has_project = bool(
        extract_query_project_codes(q, known_codes=known_project_codes)
        or _SPECIAL_CORPUS_REFERENCE_RE.search(q)
    )
    has_question = bool(_QUESTION_WORD_RE.search(q)) or "?" in q
    word_count = len(q.split())
    # Ambiguous = very short / no question framing AND no anchoring signal.
    ambiguous = not has_project and not has_history and (word_count <= 3 or not has_question)
    return {"has_project_code": has_project, "ambiguous": ambiguous, "allow_clarify": ambiguous}


def _resolve_model_preferences(model: Optional[str]) -> dict[str, Any]:
    """Map a (possibly provider-prefixed) model string to ModelRouter prefs.

    Provider-neutral: produces ``{"provider","model"}`` for
    ``ModelRouter.get_client`` without ever touching a client. Honours an
    explicit ``provider:model`` / ``provider/model`` prefix, otherwise infers
    OpenAI for the gpt/o-series and falls back to the configured default
    provider (Ollama-friendly for on-prem).
    """
    from app.core.config import settings

    default_provider = getattr(settings, "default_provider", None) or "ollama"
    raw = (model or "").strip()
    if not raw:
        return {
            "provider": default_provider,
            "model": getattr(settings, "default_model", None) or "",
        }
    for sep in (":", "/"):
        if sep in raw:
            head, tail = raw.split(sep, 1)
            head_l = head.lower()
            # serving_<node>_<id> keys from model_plane local registration
            if (
                head_l in _KNOWN_PROVIDERS or head_l.startswith("serving_")
            ) and tail.strip():
                provider = "openai" if head_l == "azure" else head_l
                return {"provider": provider, "model": tail.strip()}
    low = raw.lower()
    if low.startswith(("gpt", "o1", "o3", "o4", "chatgpt", "text-", "davinci")):
        return {"provider": "openai", "model": raw}
    return {"provider": default_provider, "model": raw}


async def _route_llm_complete(
    prompt: str,
    model: Optional[str],
    ctx: dict[str, Any],
    *,
    generation_options: Optional[dict[str, Any]] = None,
) -> str:
    """Single-shot completion resolved through ``ModelRouter`` (provider-neutral).

    Normalises the heterogeneous client return shapes (OpenAI ``content`` vs
    Ollama ``response`` vs ``completion``) into a plain string.
    """
    from app.services.model_router import ModelRouter

    prefs = _resolve_model_preferences(model or (ctx or {}).get("default_model"))
    cache_owner = ctx if isinstance(ctx, dict) else {}
    client_cache = cache_owner.get("_resolved_model_client_cache")
    if not isinstance(client_cache, dict):
        client_cache = {}
        cache_owner["_resolved_model_client_cache"] = client_cache
    cache_key = f"{prefs.get('provider')}\x00{prefs.get('model')}"
    client = client_cache.get(cache_key)
    if client is None:
        router = ModelRouter()
        client = await router.get_client(prefs)
        # Skill context is an ephemeral shallow copy and is never persisted;
        # reusing the just-validated client avoids a second remote health probe
        # when a bounded answer audit immediately follows generation.
        client_cache[cache_key] = client
    options = dict(generation_options or {})
    try:
        from app.services.model_clients.ollama_client import OllamaClient

        is_ollama = isinstance(client, OllamaClient)
    except Exception:  # noqa: BLE001 - optional provider-specific translation.
        is_ollama = False
    if is_ollama and options:
        ollama_options = dict(options.pop("options", {}) or {})
        if options.get("max_tokens") is not None:
            ollama_options["num_predict"] = options.pop("max_tokens")
        if options.get("temperature") is not None:
            ollama_options["temperature"] = options.pop("temperature")
        if ollama_options:
            options["options"] = ollama_options
    usage_accumulator = _provider_usage_scope(cache_owner)
    try:
        result = await client.generate(model=prefs["model"], prompt=prompt, **options)
    except Exception:
        # A transport failure can happen after provider-side work.  With no
        # counters, that call is deliberately unavailable rather than zero.
        record_provider_usage(
            usage_accumulator,
            None,
            provider=str(prefs.get("provider") or "unknown"),
            model=str(prefs.get("model") or "unknown"),
        )
        raise
    record_provider_usage(
        usage_accumulator,
        result,
        provider=str(prefs.get("provider") or "unknown"),
        model=str(prefs.get("model") or "unknown"),
    )
    if isinstance(result, dict):
        return str(
            result.get("content") or result.get("response") or result.get("completion") or ""
        ).strip()
    return str(result or "").strip()


def _loads_lenient_json(text: str) -> Optional[dict[str, Any]]:
    """Best-effort JSON-object recovery from an LLM completion.

    Tolerates ```json fences, surrounding prose and trailing commas by
    isolating the outermost ``{...}`` span. Returns ``None`` when nothing
    parses so callers fall back to safe defaults.
    """
    import json
    import re

    if not text:
        return None
    candidate = text.strip()
    if "```" in candidate:
        fence = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL | re.IGNORECASE)
        if fence:
            candidate = fence.group(1).strip()
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = candidate[start : end + 1]
    for attempt in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
        try:
            parsed = json.loads(attempt)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _coerce_enum(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _coerce_chunk_texts(raw: Any) -> list[str]:
    """Flatten retrieval results / citations into plain context strings."""
    out: list[str] = []
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        if isinstance(item, str):
            if item.strip():
                out.append(item)
        elif isinstance(item, dict):
            text = (
                item.get("content") or item.get("text") or item.get("snippet") or item.get("chunk")
            )
            if isinstance(text, str) and text.strip():
                out.append(text)
    return out


def _context_passages(raw: Any) -> list[dict[str, Any]]:
    """Normalise ``semantic_search_v1.results`` into citeable passages.

    Each passage is ``{content, metadata, score}``. Strings are accepted too
    (metadata-less). Empty / blank entries are dropped so an empty join is
    distinguishable from a populated one (drives the abstain-vs-answer split).
    """
    out: list[dict[str, Any]] = []
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        if isinstance(item, str):
            if item.strip():
                out.append({"content": item.strip(), "metadata": {}, "score": None})
        elif isinstance(item, dict):
            text = (
                item.get("content")
                or item.get("text")
                or item.get("snippet")
                or item.get("chunk")
                or item.get("page_content")
            )
            if isinstance(text, str) and text.strip():
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                out.append(
                    {"content": text.strip(), "metadata": metadata, "score": item.get("score")}
                )
    return out


def _select_inventory_synthesis_passages(
    query: str,
    answer_profile: Any,
    passages: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Bound explicit inventory synthesis after retrieval has established recall.

    The project inventory lane places up to eight diversified, citeable evidence
    chunks first. Sending every parent/semantic expansion after those rows made
    the single synthesis call exceed the interactive membrane even though no
    additional equipment family was being discovered. Keep all inventory
    evidence, retrieval guardrails and guide/artifact context plus the first
    complementary canonical passages. If the evidence lane did not arm or
    failed, preserve the full canonical context unchanged. ``answer_profile``
    is deliberately not an activation gate: the planner may label the same
    mono-project inventory differently, while the deterministic query shape is
    the stable contract shared with retrieval.
    """
    _ = answer_profile
    if not _is_single_project_equipment_inventory_query(query):
        return passages
    evidence = [
        passage
        for passage in passages
        if bool((passage.get("metadata") or {}).get("inventory_evidence"))
    ]
    if not evidence:
        return passages

    protected_source_types = {
        "knowledge_guide",
        "summary_artifact",
        "table_analysis",
        "document_analysis",
        "collection_inventory",
        "dense_coarse_guardrail",
    }
    protected_semantic_types = {
        *protected_source_types,
        "exact_match_guardrail",
    }
    protected = []
    for passage in passages:
        metadata = passage.get("metadata") or {}
        source_type = str(metadata.get("source_type") or metadata.get("type") or "").lower()
        semantic_type = str(metadata.get("semantic_type") or "").lower()
        if source_type in protected_source_types or semantic_type in protected_semantic_types:
            protected.append(passage)

    base_limit = min(max(int(limit or 10), 1), 12)
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append_unique(passage: dict[str, Any]) -> None:
        content = " ".join(str(passage.get("content") or "").split())
        if not content:
            return
        key = content[:8000]
        if key in seen:
            return
        seen.add(key)
        selected.append(passage)

    for passage in [*evidence, *protected]:
        append_unique(passage)
    bounded_limit = max(base_limit, len(selected))
    for passage in passages:
        append_unique(passage)
        if len(selected) >= bounded_limit:
            break
    return selected


_INVENTORY_COVERAGE_TIMEOUT_SECONDS = 10.0
_INVENTORY_COVERAGE_TOTAL_EVIDENCE_CHARS = 18000
_INVENTORY_COVERAGE_POST_AUDIT_RESERVE_SECONDS = 5.0
_INVENTORY_COVERAGE_MIN_CALL_BUDGET_SECONDS = 1.5
_INVENTORY_COVERAGE_LABEL_RE = re.compile(r"^[\wÀ-ÿ .,/()&+:'’\-]{2,120}$")


def _bounded_inventory_evidence_excerpt(content: str, limit: int) -> str:
    """Return a literal prefix ending on a source record boundary.

    A clipped token or unfinished final record must never become selectable
    evidence. Very long unstructured records are omitted rather than exposed
    partially to the semantic reviewer.
    """
    bounded_limit = max(int(limit or 0), 0)
    if bounded_limit <= 0:
        return ""
    if len(content) <= bounded_limit:
        return content
    prefix = content[:bounded_limit]
    boundary = 0
    for position, char in enumerate(prefix):
        if char in "\n\r\f;|":
            boundary = position + 1
        elif char in ".!?" and (
            position + 1 == len(content) or content[position + 1].isspace()
        ):
            boundary = position + 1
    return prefix[:boundary].rstrip() if boundary > 0 else ""


def _inventory_coverage_evidence_blocks(
    passages: list[dict[str, Any]],
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Render admitted evidence behind stable server-owned references."""
    remaining = _INVENTORY_COVERAGE_TOTAL_EVIDENCE_CHARS
    blocks: list[str] = []
    evidence_by_ref: dict[str, dict[str, Any]] = {}
    for index, passage in enumerate(passages, start=1):
        metadata = passage.get("metadata") or {}
        if metadata.get("inventory_evidence") is not True or remaining <= 0:
            continue
        source_family = str(metadata.get("source_family") or "").strip().lower()
        per_passage_limit = 8000 if source_family == "spare_parts_list" else 2200
        content = str(passage.get("content") or "").strip()
        if not content:
            continue
        excerpt = _bounded_inventory_evidence_excerpt(
            content,
            min(per_passage_limit, remaining),
        )
        if not excerpt:
            continue
        remaining -= len(excerpt)
        scope = _passage_scope_hint(metadata)
        source = _passage_source_label(metadata, index)
        evidence_ref = f"E{index}"
        header = (
            f"[{evidence_ref} -> citation {index}] ({source}; {scope})"
            if scope
            else f"[{evidence_ref} -> citation {index}] ({source})"
        )
        evidence_by_ref[evidence_ref] = {
            "content": excerpt,
            "metadata": metadata,
            "citation_index": index,
        }
        blocks.append(f"{header}\n{excerpt}")
    return "\n\n".join(blocks), evidence_by_ref


def _build_inventory_coverage_review_prompt(
    *,
    query: str,
    project_code: str,
    requested_category: str,
    evidence_text: str,
    draft: str,
    lang_target: Any,
) -> str:
    """Build a semantic omission audit with no equipment taxonomy in code."""
    return (
        "Tu es le controleur de couverture d'une reponse d'inventaire industriel. "
        "Tu ne fais aucune nouvelle recherche et tu ne connais aucun catalogue metier en dur.\n"
        f"Projet exact demande: {project_code}.\n"
        f"Categorie demandee, extraite de la question: {requested_category}.\n"
        f"Langue de sortie: {lang_target or 'fr'}.\n\n"
        "Compare le brouillon aux preuves admises. Les documents peuvent contenir beaucoup "
        "d'autres categories: IGNORE-LES toutes. Ne controle que la categorie demandee, ses "
        "traductions evidentes et ses variantes singulier/pluriel.\n"
        "Propose une omission uniquement si un item, type, modele ou libelle documentaire "
        "localement associe a cette categorie est explicitement present dans la preuve et absent "
        "du brouillon. Ignore codes article, prix, quantites, composants auxiliaires et details "
        "non demandes. Ne deduis aucun role d'entreprise ni aucune installation.\n"
        "Chaque bloc de preuve porte une reference stable comme [E2]. Pour chaque omission "
        "certaine, retourne uniquement (1) cette evidence_ref sans crochets et (2) un label "
        "source exact et concis, copie dans CE MEME bloc. Le serveur reconstruira lui-meme "
        "la citation et sa section: ne recopie pas de support_quote, ne choisis pas de section "
        "et n'invente aucune qualification. Ne repete rien deja rendu, meme groupe ou abrege. "
        "En cas de doute, status=complete.\n\n"
        "Reponds en JSON STRICT, sans texte autour, selon ce schema:\n"
        '{"status":"complete|missing","requested_category":"categorie",'
        '"additions":[{"evidence_ref":"E2","label":"span exact de ce bloc"}]}\n\n'
        f"Question:\n{query}\n\nBrouillon:\n{draft}\n\nPreuves admises:\n{evidence_text}\n"
    )


def _inventory_section_markers(answer: str) -> tuple[Optional[int], Optional[int]]:
    """Locate the exact Markdown contract, never ordinary numbered list rows."""
    first_match = re.search(r"(?m)^\s{0,3}###\s+\(1\)(?:\s|$)", answer)
    if first_match is None:
        return None, None
    second_match = re.search(
        r"(?m)^\s{0,3}###\s+\(2\)(?:\s|$)",
        answer[first_match.end() :],
    )
    if second_match is None:
        return first_match.start(), None
    return first_match.start(), first_match.end() + second_match.start()


def _normalized_inventory_span(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _normalized_inventory_lines(value: Any) -> str:
    """Normalize intra-line spacing while preserving source record boundaries."""
    return "\n".join(
        " ".join(line.casefold().split()) for line in str(value or "").splitlines()
    )


def _inventory_term_stems(value: Any) -> set[str]:
    import unicodedata

    folded = "".join(
        char
        for char in unicodedata.normalize("NFD", str(value or "").casefold())
        if unicodedata.category(char) != "Mn"
    )
    stems: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", folded):
        candidates = {token}
        # Keep every conservative candidate. In particular, French/English
        # plurals such as pompes/pompe, valves/valve and buses/buse must meet
        # their singular evidence instead of being over-stemmed to pomp/valv/bus.
        if len(token) > 3 and token.endswith(("s", "x")):
            candidates.add(token[:-1])
        if len(token) > 4 and token.endswith("es"):
            candidates.add(token[:-2])
        stems.update(candidate for candidate in candidates if len(candidate) >= 2)
    return stems


def _inventory_label_is_present(label: str, text: str) -> bool:
    """Check a rendered label with Unicode word boundaries, not substrings."""
    normalized_label = _normalized_inventory_span(label)
    normalized_text = _normalized_inventory_span(text)
    if not normalized_label or not normalized_text:
        return False
    return bool(
        re.search(
            rf"(?<!\w){re.escape(normalized_label)}(?!\w)",
            normalized_text,
        )
    )


def _inventory_local_label_contexts(source_record: str, label: str) -> list[str]:
    """Return bounded source clauses for every exact label occurrence."""
    normalized_record = _normalized_inventory_lines(source_record)
    normalized_label = _normalized_inventory_span(label)
    if not normalized_label:
        return []
    contexts: list[str] = []
    for match in re.finditer(
        rf"(?<!\w){re.escape(normalized_label)}(?!\w)",
        normalized_record,
    ):
        label_at, label_end = match.span()
        left = max(
            normalized_record.rfind(separator, 0, label_at)
            for separator in ("\n", ".", ",", ";", ":", "/", "!", "?", "|")
        )
        right_candidates = [
            position
            for separator in ("\n", ".", ",", ";", ":", "/", "!", "?", "|")
            if (position := normalized_record.find(separator, label_end)) >= 0
        ]
        right = min(right_candidates) if right_candidates else len(normalized_record)
        local_start = max(left + 1, label_at - 180)
        local_end = min(right, label_end + 180)
        contexts.append(normalized_record[local_start:local_end])
    return contexts


_INVENTORY_EVIDENCE_REF_RE = re.compile(r"^E[1-9][0-9]*$")


def _normalized_inventory_evidence_ref(value: Any) -> str:
    reference = str(value or "").strip().upper()
    return reference if _INVENTORY_EVIDENCE_REF_RE.fullmatch(reference) else ""


def _inventory_exact_source_label(label: str, source_record: str) -> str:
    """Resolve a reviewer-selected label to the exact source-cased span."""
    parts = [part for part in re.split(r"\s+", str(label or "").strip()) if part]
    if not parts:
        return ""
    pattern = r"\s+".join(re.escape(part) for part in parts)
    match = re.search(rf"(?<!\w){pattern}(?!\w)", source_record, flags=re.IGNORECASE)
    if match is None:
        return ""
    return " ".join(match.group(0).split())


def _validated_inventory_coverage_additions(
    parsed: dict[str, Any],
    *,
    draft: str,
    evidence_by_ref: dict[str, dict[str, Any]],
    project_code: str,
    requested_category: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Accept only server-resolved source spans; reviewer prose is never rendered."""
    if str(parsed.get("status") or "").strip().lower() != "missing":
        return [], []
    raw_additions = parsed.get("additions")
    if not isinstance(raw_additions, list):
        return [], ["invalid_additions"]

    accepted: list[dict[str, Any]] = []
    rejected: list[str] = []
    seen_labels: set[str] = set()
    expected_project_code = str(project_code or "").strip().upper()
    for raw in raw_additions[:8]:
        if not isinstance(raw, dict):
            rejected.append("invalid_row")
            continue
        raw_label = str(raw.get("label") or "")
        label = " ".join(raw_label.split())
        if "evidence_ref" not in raw:
            rejected.append("missing_evidence_ref")
            continue
        evidence_ref = _normalized_inventory_evidence_ref(raw.get("evidence_ref"))
        if not evidence_ref:
            rejected.append("invalid_evidence_ref")
            continue
        evidence = evidence_by_ref.get(evidence_ref)
        if evidence is None:
            rejected.append("unknown_evidence_ref")
            continue
        try:
            citation_index = int(evidence.get("citation_index"))
        except (TypeError, ValueError):
            citation_index = 0
        source_record = str(evidence.get("content") or "")
        if evidence_ref != f"E{citation_index}":
            rejected.append("evidence_citation_mismatch")
            continue
        if (
            citation_index <= 0
            or not _INVENTORY_COVERAGE_LABEL_RE.fullmatch(label)
            or not 1 <= len(source_record) <= 8000
            or any(ord(char) < 32 or ord(char) == 127 for char in raw_label)
            or "http://" in label.lower()
            or "https://" in label.lower()
        ):
            rejected.append("invalid_shape")
            continue
        metadata = evidence.get("metadata") or {}
        if metadata.get("inventory_evidence") is not True:
            rejected.append("non_inventory_evidence")
            continue
        if (
            str(metadata.get("project_code") or "").strip().upper()
            != expected_project_code
        ):
            rejected.append("project_mismatch")
            continue
        source_label = _inventory_exact_source_label(label, source_record)
        if not source_label:
            rejected.append("label_not_literal")
            continue
        normalized_label = _normalized_inventory_span(source_label)
        if _inventory_label_is_present(source_label, draft) or normalized_label in seen_labels:
            rejected.append("already_present")
            continue

        match_terms = metadata.get("inventory_match_terms")
        if isinstance(match_terms, (list, tuple, set)):
            category_terms = [str(term) for term in match_terms if str(term).strip()]
        else:
            category_terms = []
        category_terms.append(requested_category)
        category_stems = set().union(*(_inventory_term_stems(term) for term in category_terms))
        local_contexts = _inventory_local_label_contexts(source_record, source_label)
        # This guard proves literal provenance and category locality, not a
        # hard-coded equipment taxonomy. Semantic membership deliberately
        # remains the generic reviewer's task.
        category_contexts = [
            context
            for context in local_contexts
            if category_stems & _inventory_term_stems(context)
        ]
        label_stems = _inventory_term_stems(source_label)
        if not category_contexts:
            rejected.append("category_not_local")
            continue
        if label_stems and label_stems <= category_stems:
            rejected.append("category_label_not_item")
            continue

        source_family = str(metadata.get("source_family") or "").strip().lower()
        project_grounded = bool(
            source_family == "spare_parts_list"
            or metadata.get("inventory_family_attested_by_spare") is True
        )
        target_section = 1 if project_grounded else 2
        accepted.append(
            {
                "section": target_section,
                "label": source_label,
                "citation_index": citation_index,
            }
        )
        seen_labels.add(normalized_label)
    return accepted, rejected


def _apply_inventory_coverage_review(
    draft: str,
    parsed: dict[str, Any],
    *,
    evidence_by_ref: dict[str, dict[str, Any]],
    project_code: str,
    requested_category: str,
    lang_target: Any,
) -> tuple[str, dict[str, Any]]:
    """Render validated labels only; preserve the original answer byte-for-byte otherwise."""
    status = str(parsed.get("status") or "").strip().lower()
    if status == "complete":
        return draft, {"status": "complete", "accepted": 0, "rejected": []}
    additions, rejected = _validated_inventory_coverage_additions(
        parsed,
        draft=draft,
        evidence_by_ref=evidence_by_ref,
        project_code=project_code,
        requested_category=requested_category,
    )
    if not additions:
        return draft, {"status": "rejected", "accepted": 0, "rejected": rejected}
    first_at, second_at = _inventory_section_markers(draft)
    if first_at is None or second_at is None:
        return draft, {
            "status": "rejected",
            "accepted": 0,
            "rejected": [*rejected, "missing_section_contract"],
        }
    language = str(lang_target or "fr").strip().lower()[:2]
    section_1: list[str] = []
    section_2: list[str] = []
    for addition in additions:
        label = addition["label"]
        citation = addition["citation_index"]
        if language == "en":
            detail = (
                "explicitly documented for the project"
                if addition["section"] == 1
                else "documented in the corpus without proof of installation"
            )
        else:
            detail = (
                "explicitement documenté pour le projet"
                if addition["section"] == 1
                else "documenté dans le corpus sans preuve d’installation"
            )
        line = f"- **{label}** — {detail} [{citation}]."
        (section_1 if addition["section"] == 1 else section_2).append(line)
    updated = draft[:second_at].rstrip()
    if section_1:
        updated += "\n\n" + "\n".join(section_1)
    second_block = draft[second_at:].lstrip()
    if section_2:
        heading_end = second_block.find("\n")
        if heading_end < 0:
            second_block = second_block.rstrip() + "\n\n" + "\n".join(section_2)
        else:
            heading = second_block[:heading_end].rstrip()
            body = second_block[heading_end + 1 :].lstrip()
            second_block = heading + "\n\n" + "\n".join(section_2)
            if body:
                second_block += "\n\n" + body
    updated += "\n\n" + second_block
    return updated, {
        "status": "corrected",
        "accepted": len(additions),
        "rejected": rejected,
    }


async def _review_inventory_answer_coverage(
    *,
    query: str,
    passages: list[dict[str, Any]],
    draft: Any,
    model: Optional[str],
    ctx: dict[str, Any],
    lang_target: Any,
) -> tuple[str, dict[str, Any]]:
    """Run one bounded semantic audit over already-admitted evidence."""
    rendered_draft = str(draft or "").strip()
    if not rendered_draft or _is_abstention(rendered_draft):
        return rendered_draft, {"status": "not_armed", "reason": "non_substantive_draft"}
    try:
        from app.services.rag.single_project_inventory_intent import (
            parse_single_project_inventory_intent,
        )

        intent = parse_single_project_inventory_intent(query)
    except Exception as exc:  # noqa: BLE001 - optional audit must fail soft.
        logger.warning("inventory coverage: intent parser unavailable", error=str(exc))
        return rendered_draft, {"status": "not_armed", "reason": "intent_unavailable"}
    if intent is None:
        return rendered_draft, {"status": "not_armed", "reason": "not_inventory"}
    evidence_text, evidence_by_ref = _inventory_coverage_evidence_blocks(passages)
    if not evidence_text:
        return rendered_draft, {"status": "not_armed", "reason": "no_inventory_evidence"}
    prompt = _build_inventory_coverage_review_prompt(
        query=query,
        project_code=intent.project_code,
        requested_category=intent.category,
        evidence_text=evidence_text,
        draft=rendered_draft,
        lang_target=lang_target,
    )
    import asyncio
    import time

    timeout_seconds = _INVENTORY_COVERAGE_TIMEOUT_SECONDS
    try:
        run_deadline = float(ctx.get("_run_deadline_monotonic"))
    except (TypeError, ValueError):
        run_deadline = 0.0
    if run_deadline > 0:
        remaining = run_deadline - time.monotonic()
        call_budget = remaining - _INVENTORY_COVERAGE_POST_AUDIT_RESERVE_SECONDS
        if call_budget < _INVENTORY_COVERAGE_MIN_CALL_BUDGET_SECONDS:
            return rendered_draft, {
                "status": "not_armed",
                "reason": "insufficient_runtime_budget",
            }
        timeout_seconds = min(timeout_seconds, call_budget)

    try:
        completion = await asyncio.wait_for(
            _route_llm_complete(
                prompt,
                model,
                ctx,
                generation_options={"max_tokens": 700, "temperature": 0.0},
            ),
            timeout=timeout_seconds,
        )
    except (TimeoutError, asyncio.TimeoutError):
        return rendered_draft, {"status": "timeout"}
    except Exception as exc:  # noqa: BLE001 - keep the grounded draft on audit failure.
        logger.warning("inventory coverage: review failed", error=str(exc))
        return rendered_draft, {"status": "error"}
    parsed = _loads_lenient_json(completion)
    if parsed is None:
        return rendered_draft, {"status": "invalid_json"}
    return _apply_inventory_coverage_review(
        rendered_draft,
        parsed,
        evidence_by_ref=evidence_by_ref,
        project_code=intent.project_code,
        requested_category=intent.category,
        lang_target=lang_target,
    )


def _passage_source_label(metadata: dict[str, Any], index: int) -> str:
    md = metadata or {}
    return str(
        md.get("document_filename")
        or md.get("filename")
        or md.get("source")
        or md.get("document_id")
        or f"source {index}"
    )


def _passage_scope_hint(metadata: dict[str, Any]) -> str:
    """Expose only documentary scope metadata useful to grounded synthesis."""
    md = metadata or {}
    fields = (
        ("project", md.get("project_code")),
        ("source_family", md.get("source_family")),
        ("document_type", md.get("document_type") or md.get("source_kind")),
        ("inventory_evidence", "true" if md.get("inventory_evidence") else None),
        ("equipment_family", md.get("inventory_equipment_family")),
        ("functional_category", md.get("inventory_functional_category")),
        (
            "family_attested_by_spare",
            "true"
            if md.get("inventory_family_attested_by_spare")
            else "false"
            if "inventory_family_attested_by_spare" in md
            else None,
        ),
    )
    hints: list[str] = []
    for label, value in fields:
        if isinstance(value, list | tuple | set):
            rendered = ", ".join(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, str | int | float):
            rendered = str(value).strip()
        else:
            rendered = ""
        if rendered:
            hints.append(f"{label}={rendered[:160]}")
    return "; ".join(hints)


def _citations_from_passages(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build citation rows from passage metadata (chunk_id / document / score)."""
    citations: list[dict[str, Any]] = []
    for index, passage in enumerate(passages, start=1):
        md = passage.get("metadata") or {}
        label = _passage_source_label(md, index)
        document_id = md.get("document_id") or md.get("doc_id")
        filename = md.get("document_filename") or md.get("filename") or label
        collection = md.get("collection") or md.get("collection_name") or md.get("collection_slug")
        citations.append(
            {
                "index": index,
                "id": md.get("chunk_id") or md.get("id") or md.get("point_id"),
                "source_id": md.get("chunk_id") or md.get("id") or md.get("point_id"),
                "document": label,
                "title": md.get("document_title") or md.get("title") or filename,
                "filename": filename,
                "document_id": document_id,
                "collection": collection,
                "page": md.get("page") or md.get("page_number"),
                "snippet": str(passage.get("content") or "")[:1000],
                "score": passage.get("score"),
            }
        )
    return citations


def _build_grounded_answer_prompt(
    query: str,
    passages: list[dict[str, Any]],
    lang_target: Optional[str],
    answer_profile: Optional[str],
) -> str:
    """Grounded synthesis prompt: extract a complete factual answer from passages.

    Mirrors the classic synthesis framing (system_prompts FACTUAL: "clear factual
    response ... accuracy and completeness") instead of an abstention-first stance.
    The previous wording ("answer STRICTLY ... say so if absent") made the model
    over-cautious: it abstained on AKK200 even though the carrier chunk (German/
    English HTML table "Arbeitsbreite 0,3 m / Produktionsgeschwindigkeit 10-20
    m/min") was the top-ranked passage. The corpus mixes FR/EN/DE and HTML tables,
    so the prompt must explicitly invite cross-language table extraction while
    still forbidding fabrication.
    """
    profile_contract = _grounded_profile_contract(query, answer_profile)
    blocks = []
    for index, passage in enumerate(passages, start=1):
        metadata = passage.get("metadata") or {}
        src = _passage_source_label(metadata, index)
        scope_hint = _passage_scope_hint(metadata) if profile_contract else ""
        source_header = f"{src}; {scope_hint}" if scope_hint else src
        # Keep enough of each passage to preserve spec tables. Inventory
        # evidence is bounded separately because a source spare-parts chunk can
        # contain several pump sections across a page break.
        is_authoritative_inventory = bool(
            metadata.get("inventory_evidence")
            and str(metadata.get("source_family") or "").lower() == "spare_parts_list"
        )
        passage_limit = 8000 if is_authoritative_inventory else 4000
        blocks.append(
            f"[{index}] ({source_header})\n"
            f"{str(passage.get('content') or '')[:passage_limit]}"
        )
    context_text = "\n\n".join(blocks)
    return (
        "Tu es un assistant technique industriel Andritz, specialise dans des "
        "reponses factuelles, precises et completes. Reponds a la question en "
        "t'appuyant sur les extraits de contexte ci-dessous, issus de notices "
        "techniques. Ces extraits sont souvent en anglais ou en allemand et "
        "contiennent des tableaux HTML : EXTRAIS les valeurs chiffrees, references "
        "et specifications pertinentes meme lorsqu'elles figurent dans un tableau "
        "ou dans une autre langue, et traduis-les si besoin (ex. Arbeitsbreite = "
        "largeur de travail, Produktionsgeschwindigkeit = vitesse de production). "
        "Cite chaque fait avec son repere [n]. N'invente JAMAIS une valeur absente "
        "du contexte. N'ajoute aucun equipement, type, modele ou usage par analogie "
        "avec des installations similaires : un item non explicitement atteste par "
        "un extrait doit etre omis, pas presente comme plausible. Si une donnee "
        "precise est reellement introuvable, dis-le "
        "brievement mais fournis tout de meme les elements pertinents disponibles.\n"
        f"{profile_contract}"
        f"Langue de reponse: {lang_target or 'fr'}. Style attendu: {answer_profile or 'technical'}.\n\n"
        f"Contexte:\n{context_text}\n\n"
        f"Question: {query}\n\nReponse sourcee:"
    )


_NO_CONTEXT_MESSAGES = {
    "fr": "Aucune source indexee dans le perimetre disponible ne permet de repondre a cette question.",
    "en": "No indexed source in the available scope supports an answer to this question.",
    "de": "Keine indexierte Quelle im verfuegbaren Bereich beantwortet diese Frage.",
}


def _no_context_message(lang_target: Optional[str]) -> str:
    lang = str(lang_target or "fr").strip().lower()[:2]
    return _NO_CONTEXT_MESSAGES.get(lang, _NO_CONTEXT_MESSAGES["fr"])


# Phrases that signal an abstention (no grounded content). Used so self-correct
# never DOWNGRADES a substantive grounded draft into an abstention (the deep
# re-retrieval can lose carrier chunks the first pass had — observed on AKK200).
_ABSTENTION_MARKERS = (
    "aucune source",
    "ne contient pas",
    "ne permet pas de repondre",
    "ne mentionne pas",
    "no indexed source",
    "does not contain",
    "keine indexierte quelle",
)


def _is_abstention(text: Any) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return True
    import unicodedata

    folded = "".join(
        c for c in unicodedata.normalize("NFD", raw.lower()) if unicodedata.category(c) != "Mn"
    )
    return any(marker in folded for marker in _ABSTENTION_MARKERS)


def _merge_passages(
    primary: list[dict[str, Any]], extra: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Union two passage lists, de-duplicating on content (primary kept first).

    ``escalate_deep`` re-retrieves on the DEEP lane, whose wider query expansion
    can drop a carrier chunk the original (balanced) pass surfaced. Merging keeps
    the original context so a re-ground never loses ground it already had.
    """
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for passage in list(primary) + list(extra):
        content = str(passage.get("content") or "").strip()
        if not content:
            continue
        key = content[:160]
        if key in seen:
            continue
        seen.add(key)
        merged.append(passage)
    return merged


def _build_plan_prompt(query: str, history: Any) -> str:
    history_lines = ""
    if isinstance(history, (list, tuple)) and history:
        rendered = []
        for turn in list(history)[-6:]:
            if isinstance(turn, dict):
                role = turn.get("role") or turn.get("speaker") or "user"
                content = turn.get("content") or turn.get("text") or ""
                rendered.append(f"{role}: {content}")
            elif isinstance(turn, str):
                rendered.append(turn)
        history_lines = "\n".join(rendered)
    return (
        "Tu es le planificateur d'un agent de chat industriel Andritz. Analyse la requete "
        "et l'historique, puis reponds en JSON STRICT (aucun texte hors JSON), avec ces cles:\n"
        '{"action": one of answer|clarify|reject_oos, "mode": one of fast|balanced|deep, '
        '"answer_profile": short label, "scope_hint": the CONCRETE search scope '
        "(codes projet, equipements, documents cites dans la requete), "
        '"clarifying_question": only if action=clarify, "oos_reason": only if action=reject_oos, '
        '"lang_target": ISO code, "confidence": 0..1, '
        '"retrieval": {"latency_profile": fast|balanced|deep, '
        '"retrieval_profile": oracle_fast|chat|deep_async, "top_k": int, '
        '"rag_pipeline_mode": chah|auto, "deep_retrieval": bool}, '
        '"sub_queries": [liste de 2 a 4 sous-questions autonomes]}\n'
        "Regles STRICTES:\n"
        "- action=answer par defaut, et OBLIGATOIREMENT answer des qu'un code projet / "
        "identifiant machine / reference est present (ex: AKK200, CU250S-2, D.60, "
        "Qualiscan QMS-12, URACA, Etachrom, SINAMICS).\n"
        "- action=clarify UNIQUEMENT si la requete est reellement ambigue ET sans aucun "
        "ancrage (ni code projet, ni identifiant, ni contexte d'historique).\n"
        "- action=reject_oos UNIQUEMENT si la requete n'a AUCUN rapport avec l'industrie "
        "Andritz (machines, pompes, cartes, variateurs, documentation technique). "
        "NE JAMAIS rejeter sur la base de la LANGUE (une question valide en allemand/anglais "
        "reste valide). NE JAMAIS rejeter si un equipement/systeme/projet connu est cite.\n"
        "- mode=deep OBLIGATOIRE pour les questions transversales / inventaire / enumeration "
        "multi-projets ('quels projets utilisent...', 'liste...', 'sur quels projets', "
        "agregation cross-projet) ; mode=fast pour un fait ponctuel trivial ; sinon balanced. "
        "'retrieval' coherent avec 'mode'.\n"
        "- scope_hint doit etre derive de la requete reelle ; ne JAMAIS recopier les libelles "
        "d'exemple de ce schema.\n"
        "- sub_queries : UNIQUEMENT pour un answer_profile comparaison / multi_hop / transversal "
        "(question a plusieurs facettes / plusieurs entites), decompose alors la requete en 2 a 4 "
        "sous-questions AUTONOMES et distinctes (une par entite/facette, reprenant les identifiants "
        "exacts) ; sinon renvoie une liste VIDE []. Ne jamais recopier la requete telle quelle.\n\n"
        f"Historique:\n{history_lines or '(aucun)'}\n\n"
        f"Requete: {query}\n\nJSON:"
    )


# Answer profiles that warrant decomposing the query into parallel sub-queries
# (Phase 4 multi-hop). Cross-project inventory/enumeration is deliberately
# EXCLUDED: it keeps its dedicated deep lane + project_code facet (a
# decomposition would drop the exhaustive cross-project enumeration).
_MULTIHOP_PROFILE_TOKENS = (
    "comparison",
    "comparative",
    "compare",
    "multi_hop",
    "multihop",
    "multi-hop",
    "transversal",
)

# The interactive Agentic chat has a hard 40 s end-to-end budget.  A single,
# explicit project lookup does not need an LLM to decide between the retrieval
# lanes: the deterministic answer-profile resolver has already established that
# it is a summary / precise fact / equipment lookup.  Keeping this gate narrow
# avoids the planner round-trip. A mono-project equipment inventory uses the
# bounded evidence floor; comparisons, analyses, procedures, cross-project
# inventories and follow-ups remain on the full planner.
_SIMPLE_PROJECT_PROFILE_REASONS = {
    "project_summary_query",
    "precise_fact_query",
    "equipment_detail_query",
}
_COMPLEX_PROJECT_QUERY_RE = re.compile(
    r"\b(compare|comparaison|compar[ea]|diff[ée]rences?|versus|vs\.?|"
    r"pourquoi|why|warum|comment|how|wie|si|if|wenn|"
    r"analy[sz]e|analyse[rz]?|expliqu[ea]|explain|erkl[äa]r|"
    r"causes?|cons[ée]quences?|risques?|risk|hypoth[eè]se|hypothetical|sc[ée]nario|"
    r"proc[ée]dure|procedure|diagnostic|troubleshoot|d[ée]pannage|"
    r"pr[ée]cautions?|maintenance|entretien|s[ée]curit[ée]|safety|installation|"
    r"mise\s+en\s+service|commissioning|r[ée]paration|repair)\b|"
    r"\ben\s+profondeur\b|\bdeep\s+(?:analysis|dive)\b|\b[ée]tape\s+par\s+[ée]tape\b",
    re.IGNORECASE,
)
def _grounded_profile_contract(query: str, answer_profile: str | None) -> str:
    """Return narrow synthesis rules for explicitly list-shaped equipment asks.

    ``equipment_detail`` also covers ordinary datasheet questions, where an
    exhaustive scan would add unrelated neighbouring equipment.  Apply this
    contract only when the user explicitly asks for an inventory/enumeration;
    profile labels containing ``inventory`` remain supported for planner- or
    workspace-defined variants.
    """
    from app.services.rag.single_project_inventory_intent import (
        parse_single_project_inventory_intent,
    )

    profile = str(answer_profile or "").strip().lower()
    text = str(query or "")
    intent = parse_single_project_inventory_intent(text)
    is_inventory = "inventory" in profile or (profile == "equipment_detail" and intent is not None)
    if not is_inventory:
        return ""
    requested_equipment = intent.category if intent is not None else "equipements demandes"
    return (
        "CONTROLE D'INVENTAIRE OBLIGATOIRE : avant de rediger, construis en silence "
        "l'union de TOUS les libelles d'equipements rencontres, passage par passage "
        "et ligne par ligne. Dans chaque source_family=spare_parts_list, traite chaque "
        f"bloc ou en-tete correspondant a la famille demandee ({requested_equipment}), "
        "y compris ses formes singulier/pluriel, ses traductions et les blocs situes "
        "apres un saut de page, et "
        "recense en silence tous les identifiants des lignes de maintenance, pieces "
        "de rechange et equipements complets. Ne t'arrete jamais au premier bloc. "
        "Pour cette question d'inventaire, parcours TOUS les extraits avant de "
        "rediger. Enumere chaque equipement, type, modele et reference de modele "
        "directement "
        "atteste par au moins un extrait pertinent, en fusionnant uniquement les "
        "doublons certains, et cite chaque item. Ne privilegie pas seulement les "
        "premiers extraits.\n"
        "Structure obligatoirement la reponse en deux sections dont les titres Markdown "
        "commencent exactement par '### (1)' et '### (2)'. Distingue en (1) tous "
        "les items rattaches au projet ou au perimetre "
        "demande par le contenu, le libelle de source ou ses metadonnees, et (2) les "
        "modeles seulement decrits dans une notice generique ou fournisseur presente "
        "dans le dossier, en les enumerant eux aussi. Un "
        "manuel generique ne prouve jamais a lui seul que le modele est installe "
        "sur le projet.\n"
        "FORMAT COMPACT OBLIGATOIRE : si la question demande seulement quels "
        "equipements sont presents, groupe les variantes d'une meme famille sur une "
        "ligne et ne recopie pas les codes article, prix, moteurs ou details de pieces "
        "de rechange, sauf si la question les demande explicitement.\n"
        "CONTROLE FINAL DE COUVERTURE : pour chaque extrait marque "
        "inventory_evidence=true hors source_family=spare_parts_list, verifie le "
        "couple nom de fichier / equipment_family. Si ce libelle designe bien la "
        "famille d'equipements demandee et qu'il est repete dans le contenu, il doit "
        "apparaitre une fois dans l'une des deux sections, meme si l'extrait est une "
        "page de titre, un glossaire ou une introduction. Place-le en section (1) "
        "seulement si son rattachement au projet est atteste; sinon place-le en "
        "section (2) avec la reserve documentaire. Ignore les libelles de navigation, "
        "de dossier ou de schema qui ne sont pas eux-memes un equipement demande. "
        "Lorsqu'un extrait associe explicitement un constructeur ou une marque a un "
        "modele, un groupe ou une reference de l'equipement demande, conserve le nom "
        "du constructeur avec ce modele; ne supprime pas cet identifiant et ne le "
        "deduis jamais par analogie. Un nom propre d'entreprise repete dans un libelle "
        "de la forme 'NOM ref. no.' au voisinage immediat du modele doit au minimum "
        "etre conserve avec lui comme identifiant documentaire; ce libelle seul ne "
        "suffit pas a qualifier le role de cette entreprise comme constructeur. "
        "Termine chaque ligne factuelle par au moins un repere de source [n].\n"
        "Ne conclus jamais qu'il n'existe aucun autre item si un autre extrait en "
        "nomme un. Si les extraits ne prouvent pas l'exhaustivite du projet, presente "
        "le resultat comme la liste documentee dans les extraits, sans le qualifier "
        "d'exhaustif.\n"
    )


_EXHAUSTIVE_PROJECT_QUERY_RE = re.compile(
    r"\b(exhausti(?:f|ve)|complet(?:e|s)?|tous|toutes|all|liste[rz]?|list|inventaire)\b",
    re.IGNORECASE,
)
_CROSS_PROJECT_TARGET_RE = re.compile(
    r"\b(projets|projects|dossiers)\b|\b(quels?|which)\s+(?:projet|project|dossier)\b",
    re.IGNORECASE,
)
_GERMAN_QUERY_RE = re.compile(
    r"\b(welche[rsn]?|was|wie|warum|zusammenfass(?:en|ung)|projekt|pumpen?|"
    r"wartung|vorsichtsma(?:ss|ß)nahmen|beschreibe|nenne)\b",
    re.IGNORECASE,
)


def _is_single_project_equipment_inventory_query(query: str) -> bool:
    from app.services.rag.single_project_inventory_intent import (
        parse_single_project_inventory_intent,
    )

    return parse_single_project_inventory_intent(query or "") is not None


def _deterministic_single_project_plan(
    query: str,
    *,
    has_history: bool,
    ctx: dict[str, Any],
    known_project_codes: set[str] | None = None,
) -> Optional[dict[str, Any]]:
    """Return a deterministic lane plan for a conservative project lookup.

    The response language is taken from the server-owned chat Run input.  When
    it is absent (for example a generic Systems API invocation), the LLM planner
    remains authoritative.  German is also left to the multilingual planner
    because the public chat language contract currently only normalises FR/EN.
    """
    if has_history:
        return None

    run_input = ctx.get("input") if isinstance(ctx.get("input"), dict) else {}
    response_language = str(run_input.get("response_language") or "").lower()
    if response_language not in {"fr", "en"} or _GERMAN_QUERY_RE.search(query):
        return None

    from app.services.rag.single_project_inventory_intent import (
        parse_single_project_inventory_intent,
    )

    inventory_intent = parse_single_project_inventory_intent(query)
    equipment_inventory = inventory_intent is not None
    if inventory_intent is not None:
        # The generic parser owns both category and scope for this lane. Legacy
        # complexity words such as safety/repair/diagnostic may be part of a
        # perfectly valid requested category and must not veto it.
        project_code = inventory_intent.project_code
    else:
        project_codes = set(
            extract_query_project_codes(query, known_codes=known_project_codes)
        )
        if (
            len(project_codes) != 1
            or _COMPLEX_PROJECT_QUERY_RE.search(query)
            or _CROSS_PROJECT_TARGET_RE.search(query)
            or _EXHAUSTIVE_PROJECT_QUERY_RE.search(query)
        ):
            return None
        project_code = next(iter(project_codes))

    # Reuse the same deterministic classifier as classic chat; do not invent a
    # second intent taxonomy in the Agentic wrapper.
    from app.services.industrial_answer_profile import resolve_answer_profile

    profile = resolve_answer_profile(query, include_agentic_profiles=True)
    if not equipment_inventory and profile.reason not in _SIMPLE_PROJECT_PROFILE_REASONS:
        return None

    mode = "balanced"
    retrieval = (
        dict(_SINGLE_PROJECT_INVENTORY_RETRIEVAL) if equipment_inventory else None
    )
    plan_payload: dict[str, Any] = {
        "action": "answer",
        "mode": mode,
        "answer_profile": "equipment_detail" if equipment_inventory else profile.profile,
        "scope_hint": project_code,
        "lang_target": response_language,
        "confidence": 1.0,
    }
    if retrieval is not None:
        plan_payload["retrieval"] = retrieval
    return _coerce_plan(
        plan_payload,
        query,
        has_history=False,
        known_project_codes=known_project_codes,
    )


def _profile_is_multihop(answer_profile: Any, query: str) -> bool:
    """Whether the plan should decompose into sub-queries for this profile.

    Gated on the answer_profile label, minus inventory questions (which own the
    deep + transversal_inventory facet lane and must not be split).
    """
    if _is_inventory_query(query):
        return False
    profile = str(answer_profile or "").lower()
    return any(token in profile for token in _MULTIHOP_PROFILE_TOKENS)


def _derive_comparative_sub_queries(query: str) -> list[str]:
    """Fallback decomposition reusing the classic comparative splitter.

    When the planner does not emit usable ``sub_queries`` for a comparison
    profile, recover the two compared entities lexically (FR/EN/DE patterns) so
    each entity still gets its own retrieval pass. Never raises.
    """
    try:
        from app.services.rag.comparative_retrieval import parse_comparative_entities

        entities = parse_comparative_entities(query)
    except Exception:  # noqa: BLE001 — decomposition must never break the plan.
        return []
    if not entities:
        return []
    return [entity for entity in entities if isinstance(entity, str) and entity.strip()]


def _coerce_sub_queries(parsed: dict[str, Any], query: str, answer_profile: str) -> list[str]:
    """Coerce the planner's ``sub_queries`` into a clean 0/2-4 item list.

    Contract: populated (2-4 deduped, non-echo sub-questions) only when the
    answer_profile is comparison/multi_hop/transversal; empty otherwise. Robust
    to garbage (non-list, non-string entries) -> defaults to an empty list.
    """
    if not _profile_is_multihop(answer_profile, query):
        return []
    raw = parsed.get("sub_queries")
    subs: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                subs.append(" ".join(item.split()))
    query_norm = " ".join(str(query or "").lower().split())
    seen: set[str] = set()
    cleaned: list[str] = []
    for sub in subs:
        key = sub.lower()
        if key in seen or key == query_norm:
            continue
        seen.add(key)
        cleaned.append(sub)
    # Fallback: a comparison profile with too few usable sub-queries recovers the
    # compared entities lexically so decomposition still happens.
    if len(cleaned) < 2:
        for sub in _derive_comparative_sub_queries(query):
            key = sub.lower()
            if key in seen or key == query_norm:
                continue
            seen.add(key)
            cleaned.append(sub)
    return cleaned[:4]


def _coerce_plan(
    parsed: dict[str, Any],
    query: str,
    *,
    has_history: bool = False,
    known_project_codes: set[str] | None = None,
) -> dict[str, Any]:
    """Coerce a (possibly partial/garbage) plan dict into the frozen contract.

    GATES (2026-06-26):
      * ``clarify`` (C3): reject placeholder scopes and demote to ``answer`` when
        the request is answerable (project code / not genuinely ambiguous).
      * ``reject_oos`` (fix): NEVER reject on language and never when the query
        names a known project/machine/system (QMS-12, URACA, AKK200…) — demote
        to ``answer`` so retrieval gets a chance (a late context gate at
        decision.deliver is the runtime backstop).
      * inventory/transversal routing (fix): cross-project / enumeration
        questions are forced to the ``deep`` lane (full deep budget) — the
        planner under-routes them to balanced and misses the aggregated list.
    """
    parsed = parsed if isinstance(parsed, dict) else {}
    mode = _coerce_enum(parsed.get("mode"), _PLAN_ENUMS["mode"], "balanced")
    action = _coerce_enum(parsed.get("action"), _PLAN_ENUMS["action"], "answer")

    # Inventory / transversal questions need the deep lane to aggregate across
    # documents — deterministic upgrade (the LLM under-routes them to balanced).
    single_project_inventory = _is_single_project_equipment_inventory_query(query)
    inventory = _is_inventory_query(query) and not single_project_inventory
    if single_project_inventory:
        mode = "balanced"
    if inventory:
        mode = "deep"

    retrieval_defaults = dict(_RETRIEVAL_BY_MODE[mode])
    raw_retrieval = parsed.get("retrieval") if isinstance(parsed.get("retrieval"), dict) else {}
    retrieval = {
        "latency_profile": _coerce_enum(
            raw_retrieval.get("latency_profile"),
            _PLAN_ENUMS["latency_profile"],
            retrieval_defaults["latency_profile"],
        ),
        "retrieval_profile": _coerce_enum(
            raw_retrieval.get("retrieval_profile"),
            _PLAN_ENUMS["retrieval_profile"],
            retrieval_defaults["retrieval_profile"],
        ),
        "rag_pipeline_mode": _coerce_enum(
            raw_retrieval.get("rag_pipeline_mode"),
            _PLAN_ENUMS["rag_pipeline_mode"],
            retrieval_defaults["rag_pipeline_mode"],
        ),
        "deep_retrieval": bool(
            raw_retrieval.get("deep_retrieval", retrieval_defaults["deep_retrieval"])
        ),
    }

    def _coerce_budget(key: str) -> int:
        try:
            value = int(raw_retrieval.get(key) or retrieval_defaults[key])
        except (TypeError, ValueError):
            value = retrieval_defaults[key]
        return max(1, min(200, value))

    retrieval["top_k"] = max(1, min(50, _coerce_budget("top_k")))
    retrieval["synthesis_k"] = _coerce_budget("synthesis_k")
    retrieval["candidate_pool_k"] = _coerce_budget("candidate_pool_k")

    # Force the deep lane fields when inventory was detected (the LLM may have
    # emitted a balanced ``retrieval`` block that would otherwise win).
    if inventory:
        deep = _RETRIEVAL_BY_MODE["deep"]
        retrieval["latency_profile"] = "deep"
        retrieval["retrieval_profile"] = "deep_async"
        retrieval["deep_retrieval"] = True
        retrieval["top_k"] = max(retrieval["top_k"], deep["top_k"])
        retrieval["synthesis_k"] = max(retrieval["synthesis_k"], deep["synthesis_k"])
        retrieval["candidate_pool_k"] = max(retrieval["candidate_pool_k"], deep["candidate_pool_k"])
    elif single_project_inventory:
        # This invariant must also hold for follow-ups and LLM-planned runs, not
        # only the no-history deterministic shortcut.
        retrieval = dict(_SINGLE_PROJECT_INVENTORY_RETRIEVAL)

    try:
        confidence = float(parsed.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.6
    confidence = max(0.0, min(1.0, confidence))

    def _as_str(key: str, default: str = "") -> str:
        value = parsed.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else default

    # Reject schema-placeholder scope hints so retrieval scope is never polluted
    # by the literal "perimetre de recherche" the planner copies from the prompt.
    scope_hint = _as_str("scope_hint", "")
    if _is_placeholder_text(scope_hint):
        scope_hint = ""

    clarifying_question = _as_str("clarifying_question", "")
    if _is_placeholder_text(clarifying_question):
        clarifying_question = ""

    # OOS gate: never reject a query that names a known project/machine/system
    # (or matches a project code) — the planner over-rejects valid questions
    # (notably in German). Demote to answer; retrieval + the deliver context
    # gate decide the rest.
    if action == "reject_oos" and _has_known_corpus_anchor(
        query,
        known_project_codes=known_project_codes,
    ):
        action = "answer"

    # C3 gate: only honour clarify when the request is genuinely ambiguous.
    if action == "clarify":
        gate = _assess_clarify_gate(
            query,
            has_history=has_history,
            known_project_codes=known_project_codes,
        )
        if gate["has_project_code"] or not gate["allow_clarify"] or not clarifying_question:
            action = "answer"
            clarifying_question = ""
    if action == "clarify" and not clarifying_question:
        clarifying_question = "Pouvez-vous preciser le projet ou l'equipement concerne ?"

    # oos_reason only survives when the action is still reject_oos (a demoted
    # reject_oos must not leak a stale refusal reason into an answer plan).
    oos_reason = (
        _as_str("oos_reason", "Hors du perimetre Andritz.") if action == "reject_oos" else ""
    )

    answer_profile = _as_str("answer_profile", "technical")
    # Multi-hop decomposition (Phase 4): 2-4 sub-queries for comparison /
    # multi_hop / transversal profiles, empty list otherwise. A clarify /
    # reject_oos plan never decomposes (there is no answer to ground).
    sub_queries = _coerce_sub_queries(parsed, query, answer_profile) if action == "answer" else []

    return {
        "action": action,
        "mode": mode,
        "answer_profile": answer_profile,
        "scope_hint": scope_hint,
        "clarifying_question": clarifying_question,
        "oos_reason": oos_reason,
        "lang_target": _as_str("lang_target", "fr"),
        "confidence": round(confidence, 4),
        "retrieval": retrieval,
        "sub_queries": sub_queries,
    }


async def _chat_agentic_plan_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Provider-neutral agentic planner (LLM via ModelRouter).

    OUT (frozen §7): ``{action, mode, answer_profile, scope_hint,
    clarifying_question, oos_reason, lang_target, confidence,
    retrieval:{latency_profile, retrieval_profile, top_k, rag_pipeline_mode,
    deep_retrieval}, sub_queries:[str]}``. ``sub_queries`` carries 2-4 decomposed
    sub-questions for comparison/multi_hop/transversal profiles (empty otherwise;
    Phase 4). Robust to non-JSON model output -> safe defaults (action=answer,
    mode=balanced, sub_queries=[]).
    """
    ctx = ctx or {}
    query = str(payload.get("query") or "")
    history = payload.get("conversation_history")
    has_history = bool(isinstance(history, (list, tuple)) and history)
    known_project_codes = _authoritative_query_project_codes(query, payload, ctx)
    deterministic_plan = _deterministic_single_project_plan(
        query,
        has_history=has_history,
        ctx=ctx,
        known_project_codes=known_project_codes,
    )
    if deterministic_plan is not None:
        return deterministic_plan
    model = payload.get("model") or ctx.get("default_model")
    prompt = _build_plan_prompt(query, history)
    completion = ""
    try:
        completion = await _route_llm_complete(prompt, model, ctx)
    except Exception as exc:  # noqa: BLE001 — never crash the DAG on a model hiccup
        logger.warning(
            "chat_agentic_plan_v1: model call failed, using safe defaults", error=str(exc)
        )
    return _coerce_plan(
        _loads_lenient_json(completion) or {},
        query,
        has_history=has_history,
        known_project_codes=known_project_codes,
    )


def _build_self_correct_prompt(
    query: str, draft: str, action: str, composite: Any, hallucination_rate: Any
) -> str:
    guidance = {
        "escalate_deep": "Approfondis et re-ancre la reponse sur les sources industrielles Andritz ; supprime toute affirmation non etayee.",
        "translate": "Reformule la reponse dans la langue cible attendue de l'utilisateur, sans changer le fond.",
        "declare_partial": "Conserve uniquement ce qui est etaye, et declare explicitement les limites / l'incertitude restante.",
    }[action]
    return (
        "Tu es le reacteur d'auto-correction (1 passe) d'un agent de chat industriel Andritz.\n"
        f"Action de reparation choisie: {action}. Consigne: {guidance}\n"
        f"Signaux qualite — composite(0-100)={composite} ; hallucination_rate(0-1)={hallucination_rate}.\n"
        "Re-genere une MEILLEURE reponse et reponds en JSON STRICT (aucun texte hors JSON):\n"
        '{"answer":"reponse corrigee","action_taken":"' + action + '"}\n\n'
        f"Question: {query}\n\nBrouillon a corriger:\n{draft}\n\nJSON:"
    )


def _pick_self_correct_action(
    mode: str,
    composite: Any,
    hallucination_rate: Any,
    *,
    draft_is_abstention: bool = False,
) -> str:
    """Deterministic repair-action choice from the verdict signals.

    IMPORTANT (parity fix 2026-06-26): ``hallucination_rate`` is NOT a usable
    trigger here. ``response_eval`` derives it as ``1 - factuality`` from an
    EMBEDDING similarity, which sits structurally ~0.3-0.5 even for clean
    grounded answers — gating on ``halluc > 0.15`` fired escalate_deep on EVERY
    run (latency aborts + lossy deep swaps that turned good answers into
    abstentions). We escalate ONLY when the draft is itself an abstention (the
    first pass found nothing usable, so a deeper retrieval is worth a try) or
    when the composite quality floor is genuinely breached. Otherwise we keep
    the grounded draft (``declare_partial``), matching the classic path that
    does not self-correct grounded answers.
    """
    try:
        comp = float(composite) if composite is not None else None
    except (TypeError, ValueError):
        comp = None
    if draft_is_abstention:
        return "escalate_deep"
    if comp is not None and comp < 50 and mode != "deep":
        return "escalate_deep"
    return "declare_partial"


async def _chat_self_correct_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Provider-neutral bounded self-correction reactor (LLM via ModelRouter).

    Picks ONE action (escalate_deep|translate|declare_partial) and returns the
    frozen §7 shape ``{answer, citations, action_taken}``.

    KEY ANTI-HALLUCINATION RULE (C2): ``escalate_deep`` actually RE-RETRIEVES
    (deep lane, original query, no narrowing) and re-grounds the answer on the
    NEW context — or abstains if retrieval is still empty. It NEVER free-generates
    a "better" answer from the draft alone (that turned honest abstentions into
    confident fabrications). ``translate``/``declare_partial`` only transform the
    existing grounded draft; they introduce no new facts.
    """
    ctx = ctx or {}
    draft = str(payload.get("draft_answer") or payload.get("answer") or "")
    query = str(payload.get("query") or "")
    mode = _coerce_enum(payload.get("mode"), _PLAN_ENUMS["mode"], "balanced")
    citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
    composite = payload.get("composite")
    hallucination_rate = payload.get("hallucination_rate")
    lang_target = payload.get("lang_target")
    answer_profile = payload.get("answer_profile")
    scope_hint = payload.get("scope_hint")
    model = payload.get("model") or ctx.get("default_model")
    # Original (pre-correction) retrieval context, wired from join.retrieval.
    # Kept so a deep re-retrieval can MERGE (never lose) carrier chunks the
    # first pass already surfaced.
    original_passages = _context_passages(payload.get("context"))
    draft_is_abstention = _is_abstention(draft)

    action = _pick_self_correct_action(
        mode, composite, hallucination_rate, draft_is_abstention=draft_is_abstention
    )

    if action == "escalate_deep":
        # Re-run retrieval on the DEEP lane (original query, no rewrite/narrowing)
        # then re-ground on the MERGED context — never fabricate, never downgrade.
        try:
            search = await _semantic_search_v1(
                {
                    "query": query,
                    "knowledge_scope": scope_hint,
                    "latency_profile": "deep",
                    "retrieval_profile": "deep_async",
                    "deep_retrieval": True,
                    # top_k / synthesis_k / candidate_pool_k are backfilled from
                    # _LANE_BUDGETS["deep"] inside _semantic_search_v1 so the
                    # re-retrieval truly uses the FULL deep budget (not a
                    # collapsed lone-top_k pool).
                },
                ctx,
            )
            deep_passages = _context_passages(search.get("results"))
        except Exception as exc:  # noqa: BLE001 — re-retrieval must never crash the DAG
            logger.warning("chat_self_correct_v1: deep re-retrieval failed", error=str(exc))
            deep_passages = []
        # Merge so the deep lane can only ADD recall, never drop the carrier
        # chunks the original (balanced) pass already had.
        passages = _merge_passages(original_passages, deep_passages)
        if not passages:
            # Truly nothing anywhere — honest abstention beats a fabrication.
            return {
                "answer": _no_context_message(lang_target),
                "citations": [],
                "action_taken": "declare_partial",
            }
        grounded = await _llm_rag_answer_v1(
            {
                "query": query,
                "context": [
                    {
                        "content": p["content"],
                        "metadata": p.get("metadata") or {},
                        "score": p.get("score"),
                    }
                    for p in passages
                ],
                "lang_target": lang_target,
                "answer_profile": answer_profile,
                "model": model,
            },
            ctx,
        )
        regrounded = grounded.get("answer") or ""
        # NEVER downgrade: if the re-ground abstains but we already had a
        # substantive grounded draft, keep the draft (and its citations).
        if _is_abstention(regrounded) and not draft_is_abstention:
            return {
                "answer": draft,
                "citations": citations,
                "action_taken": "declare_partial",
            }
        return {
            "answer": regrounded or _no_context_message(lang_target),
            "citations": grounded.get("citations") or [],
            "action_taken": "escalate_deep",
        }

    # translate / declare_partial — bounded transform of the EXISTING draft only.
    prompt = _build_self_correct_prompt(query, draft, action, composite, hallucination_rate)
    answer = draft
    try:
        completion = await _route_llm_complete(prompt, model, ctx)
        parsed = _loads_lenient_json(completion)
        if parsed:
            candidate = parsed.get("answer")
            if isinstance(candidate, str) and candidate.strip():
                answer = candidate.strip()
            action = _coerce_enum(parsed.get("action_taken"), _SELF_CORRECT_ACTIONS, action)
        elif completion.strip():
            # Model returned prose rather than JSON — still a valid transform.
            answer = completion.strip()
    except Exception as exc:  # noqa: BLE001 — degrade to the draft + a partial flag
        logger.warning("chat_self_correct_v1: model call failed, declaring partial", error=str(exc))
        action = "declare_partial"
    return {
        "answer": answer,
        "citations": citations,
        "action_taken": _coerce_enum(action, _SELF_CORRECT_ACTIONS, "declare_partial"),
    }


async def _response_eval_v1(
    payload: dict[str, Any], ctx: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Wrapper around ``ResponseEvaluator`` — SOURCE UNIQUE of the 0-100 composite.

    OUT (frozen §7): ``{composite (0-100), hallucination_rate (0-1),
    context_count (int), hhem, factuality, coherence}``. Reuses the existing
    embedding evaluator (same call as the inline use in procurement_agent
    ~1731-1768); no new metric is invented. The composite is the evaluator's
    interpretable quality axes (relevance/factuality/coherence) averaged ×100,
    and ``hallucination_rate`` is the complement of factuality (the evaluator
    emits neither a single composite nor a hallucination field).
    """
    from app.services.metrics.evaluator import ResponseEvaluator

    answer = str(payload.get("answer") or "")
    query = str(payload.get("query") or "")
    raw_context = payload.get("context_chunks")
    if raw_context is None:
        raw_context = payload.get("context")
    if raw_context is None:
        raw_context = payload.get("citations") or []
    chunk_texts = _coerce_chunk_texts(raw_context)

    metrics = await ResponseEvaluator().evaluate(
        query=query, response=answer, source_chunks=chunk_texts
    )
    relevance = float(metrics.get("relevance") or 0.0)
    factuality = float(metrics.get("factuality") or 0.0)
    coherence = float(metrics.get("coherence") or 0.0)
    hhem = float(metrics.get("hhem") or 0.0)

    composite = round(((relevance + factuality + coherence) / 3.0) * 100.0, 2)
    hallucination_rate = round(max(0.0, min(1.0, 1.0 - factuality)), 4)
    return {
        "composite": composite,
        "hallucination_rate": hallucination_rate,
        "context_count": len(chunk_texts),
        "hhem": round(hhem, 4),
        "factuality": round(factuality, 4),
        "coherence": round(coherence, 4),
    }


# ---------------------------------------------------------------------------
# Line-item reconciliation suite (spreadsheet/invoice extract, reconcile, report)
# ---------------------------------------------------------------------------
def _file_reference_payload(
    payload: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """Backfill file references from the run input when the node has no binding.

    The ingress payload (``deposit.promoted`` event, manual run, cron) carries
    ``file_ids`` / ``collection_slug``; letting the extractors read them from
    ``ctx["input"]`` means the same graph serves all three ingress without an
    explicit ``inputs_map`` on every node. Explicit payload keys always win.
    """
    merged: dict[str, Any] = {}
    run_input = ctx.get("input")
    if isinstance(run_input, dict):
        for key in ("file_ids", "file_id", "collection_slug", "filename_pattern"):
            if run_input.get(key) not in (None, "", []):
                merged[key] = run_input[key]
    for key, value in payload.items():
        if value not in (None, "", []):
            merged[key] = value
    return merged


async def _spreadsheet_table_extract_v1(
    payload: dict[str, Any], ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    from app.db.base import SessionLocal
    from app.services.reconciliation import extract_spreadsheet_table
    from app.services.skills_registry.file_resolution import resolve_skill_file

    ctx = ctx or {}
    db = ctx.get("db")
    owns_db = db is None
    if owns_db:
        db = SessionLocal()
    try:
        resolved = resolve_skill_file(
            db,
            workspace_id=str(ctx.get("workspace_id") or payload.get("workspace_id") or ""),
            payload=_file_reference_payload(payload, ctx),
            extensions=(".xlsx", ".xlsm"),
        )
    finally:
        if owns_db:
            db.close()
    result = extract_spreadsheet_table(
        resolved.data,
        sheet=payload.get("sheet"),
        header_row=payload.get("header_row"),
        filters=payload.get("filters") if isinstance(payload.get("filters"), dict) else None,
    )
    result["source_file"] = resolved.filename
    return result


async def _invoice_document_extract_v1(
    payload: dict[str, Any], ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    from app.db.base import SessionLocal
    from app.services.reconciliation import extract_invoice_fields, extract_pdf_text
    from app.services.skills_registry.file_resolution import resolve_skill_file

    ctx = ctx or {}
    db = ctx.get("db")
    owns_db = db is None
    if owns_db:
        db = SessionLocal()
    try:
        resolved = resolve_skill_file(
            db,
            workspace_id=str(ctx.get("workspace_id") or payload.get("workspace_id") or ""),
            payload=_file_reference_payload(payload, ctx),
            extensions=(".pdf",),
        )
    finally:
        if owns_db:
            db.close()
    result = extract_invoice_fields(extract_pdf_text(resolved.data))
    result["source_file"] = resolved.filename
    return result


async def _line_items_reconcile_v1(
    payload: dict[str, Any], ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    from app.services.reconciliation import reconcile_line_items

    po_lines = payload.get("po_lines")
    invoice_lines = payload.get("invoice_lines")
    if not isinstance(po_lines, list) or not isinstance(invoice_lines, list):
        raise ValueError(
            "line_items_reconcile_v1: 'po_lines' and 'invoice_lines' arrays are required"
        )
    try:
        tolerance_pct = float(payload.get("tolerance_pct") or 2.0)
    except (TypeError, ValueError):
        tolerance_pct = 2.0
    return reconcile_line_items(
        po_lines,
        invoice_lines,
        po_reference=payload.get("po_reference"),
        tolerance_pct=tolerance_pct,
        po_field_map=payload.get("po_field_map")
        if isinstance(payload.get("po_field_map"), dict)
        else None,
        invoice_field_map=payload.get("invoice_field_map")
        if isinstance(payload.get("invoice_field_map"), dict)
        else None,
    )


async def _reconciliation_report_v1(
    payload: dict[str, Any], ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    from app.services.reconciliation import render_reconciliation_report

    reconciliation = payload.get("reconciliation")
    if not isinstance(reconciliation, dict):
        raise ValueError("reconciliation_report_v1: 'reconciliation' object is required")
    verdict = str(payload.get("verdict") or "").strip()
    if verdict not in ("Approved", "Needs Review"):
        verdict = "Approved" if not reconciliation.get("flagged_count") else "Needs Review"
    report_text = render_reconciliation_report(
        reconciliation,
        verdict,
        payload.get("invoice_meta") if isinstance(payload.get("invoice_meta"), dict) else None,
    )
    return {
        "report_text": report_text,
        "verdict": verdict,
        "flagged_count": int(reconciliation.get("flagged_count") or 0),
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# (slug -> (callable, expected_module_path|None, status_hint))
# ``expected_module_path`` is the module whose import must succeed for
# the wrapper to be considered `bound`. A ``None`` path means the
# wrapper is self-contained (loggers, stubs, in-process helpers).
_REGISTRY: dict[str, tuple[SkillCallable, Optional[str], str]] = {
    "llm_rag_answer_v1": (_llm_rag_answer_v1, "app.services.rag.rag_service", "bound"),
    "semantic_search_v1": (_semantic_search_v1, "app.services.rag.context", "bound"),
    "multi_hop_retrieve_v1": (
        _multi_hop_retrieve_v1,
        "app.services.rag.comparative_retrieval",
        "bound",
    ),
    "chat_trivial_bypass_v1": (_chat_trivial_bypass_v1, None, "bound"),
    "chat_grounding_policy_v1": (_stub, None, "stub"),
    "chat_action_resolver_v1": (_stub, None, "stub"),
    "document_ingestion_v1": (_document_ingestion_v1, "app.services.rag.document_service", "bound"),
    "eval_radar_v1": (_eval_radar_v1, "app.services.evaluation.judge", "bound"),
    "claim_audit_v1": (_claim_audit_v1, "app.services.evaluation.judge", "bound"),
    "intelligence_batch_v1": (_intelligence_batch_v1, "app.services.intelligence.batch", "bound"),
    "ministerial_briefing_v1": (_ministerial_briefing_v1, "app.services.mission_room", "bound"),
    "news_signal_synthesis_v1": (_news_signal_synthesis_v1, "app.services.mission_room", "bound"),
    "project_risk_explainer_v1": (_project_risk_explainer_v1, "app.services.mission_room", "bound"),
    "territorial_signal_map_v1": (_territorial_signal_map_v1, "app.services.mission_room", "bound"),
    "instruction_draft_v1": (_instruction_draft_v1, "app.services.mission_room", "bound"),
    "scenario_generate_v1": (_scenario_generate_v1, "app.services.scenario_engine", "bound"),
    "scenario_compare_v1": (_scenario_compare_v1, "app.services.scenario_engine", "bound"),
    "scenario_recommend_v1": (_scenario_recommend_v1, "app.services.scenario_engine", "bound"),
    "calendar_read_v1": (_calendar_read_v1, "app.services.workspace_calendar", "bound"),
    "sap_hana_query_v1": (
        _sap_hana_query_v1,
        "app.services.connectors.hana.service",
        "bound",
    ),
    "rpa_dispatch_v1": (
        _rpa_dispatch_v1,
        "app.services.connectors.rpa.service",
        "bound",
    ),
    "calendar_create_event_v1": (
        _calendar_create_event_v1,
        "app.services.workspace_calendar",
        "bound",
    ),
    "calendar_update_event_v1": (
        _calendar_update_event_v1,
        "app.services.workspace_calendar",
        "bound",
    ),
    "calendar_cancel_event_v1": (
        _calendar_cancel_event_v1,
        "app.services.workspace_calendar",
        "bound",
    ),
    "calendar_daily_summary_v1": (
        _calendar_daily_summary_v1,
        "app.services.workspace_calendar",
        "bound",
    ),
    "action_plan_create_v1": (_action_plan_create_v1, "app.services.action_plans", "bound"),
    "action_plan_reschedule_v1": (_action_plan_reschedule_v1, "app.services.action_plans", "bound"),
    "action_plan_status_v1": (_action_plan_status_v1, "app.services.action_plans", "bound"),
    "action_plan_cancel_v1": (_action_plan_cancel_v1, "app.services.action_plans", "bound"),
    "time_context_set_v1": (_time_context_set_v1, "app.services.demo_time_context", "bound"),
    "briefing_priorities_v1": (_briefing_priorities_v1, "app.services.mission_room", "bound"),
    "summarize_long_document_v1": (
        _summarize_long_document_v1,
        "app.services.mission_room",
        "bound",
    ),
    "generate_recommendations_v1": (
        _generate_recommendations_v1,
        "app.services.mission_room",
        "bound",
    ),
    "draft_email_v1": (_draft_email_v1, "app.services.mission_room", "bound"),
    "causal_drill_v1": (_causal_drill_v1, "app.services.mission_room", "bound"),
    "schedule_meeting_v1": (_schedule_meeting_v1, "app.services.workspace_calendar", "bound"),
    "territorial_action_window_v1": (
        _territorial_action_window_v1,
        "app.services.mission_room",
        "bound",
    ),
    "map_layer_read_v1": (_map_layer_read_v1, "app.services.workspace_maps", "bound"),
    "map_zone_score_v1": (_map_zone_score_v1, "app.services.workspace_maps", "bound"),
    "map_signal_attach_v1": (_map_signal_attach_v1, "app.services.workspace_maps", "bound"),
    "map_recommendation_generate_v1": (
        _map_recommendation_generate_v1,
        "app.services.workspace_maps",
        "bound",
    ),
    "map_command_apply_v1": (_map_command_apply_v1, "app.services.workspace_maps", "bound"),
    "source_registry_refresh_v1": (
        _source_registry_refresh_v1,
        "app.services.mission_room",
        "bound",
    ),
    "osint_signal_prioritize_v1": (
        _osint_signal_prioritize_v1,
        "app.services.mission_room",
        "bound",
    ),
    "rumor_origin_trace_v1": (_rumor_origin_trace_v1, "app.services.mission_room", "bound"),
    "evidence_graph_build_v1": (_evidence_graph_build_v1, "app.services.mission_room", "bound"),
    "situation_posture_score_v1": (
        _situation_posture_score_v1,
        "app.services.mission_room",
        "bound",
    ),
    "maritime_snapshot_read_v1": (
        _maritime_snapshot_read_v1,
        "app.services.workspace_maps",
        "bound",
    ),
    "decision_option_rank_v1": (_decision_option_rank_v1, "app.services.mission_room", "bound"),
    "draft_response_email_v1": (_draft_response_email_v1, "app.services.mission_room", "bound"),
    "visual_source_read_v1": (_visual_source_read_v1, "app.services.visual_intelligence", "bound"),
    "visual_snapshot_capture_v1": (
        _visual_snapshot_capture_v1,
        "app.services.visual_intelligence",
        "bound",
    ),
    "visual_snapshot_analyze_v1": (
        _visual_snapshot_analyze_v1,
        "app.services.visual_intelligence",
        "bound",
    ),
    "visual_observation_sync_knowledge_v1": (
        _visual_observation_sync_knowledge_v1,
        "app.services.visual_intelligence",
        "bound",
    ),
    "sharepoint_ingestion_v1": (_sharepoint_ingestion_v1, None, "stub"),
    "translation_archive_ingest_v1": (_translation_showcase_stub, None, "stub"),
    "translation_memory_retrieve_v1": (_translation_showcase_stub, None, "stub"),
    "translation_label_index_resolve_v1": (_translation_showcase_stub, None, "stub"),
    "translation_pivot_normalize_v1": (_translation_showcase_stub, None, "stub"),
    "translation_fanout_v1": (_translation_showcase_stub, None, "stub"),
    "translation_j2450_qa_v1": (_translation_showcase_stub, None, "stub"),
    "translation_post_guard_v1": (_translation_showcase_stub, None, "stub"),
    "translation_cdt_gate_v1": (_translation_showcase_stub, None, "stub"),
    "translation_package_delivery_v1": (_translation_showcase_stub, None, "stub"),
    "voice_transcribe_v1": (_voice_transcribe_v1, "app.services.voice_runtime", "bound"),
    "voice_tts_v1": (_voice_tts_v1, "app.services.voice_runtime", "bound"),
    "voice_realtime_session_v1": (
        _voice_realtime_session_v1,
        "app.services.voice_runtime",
        "bound",
    ),
    "voice_realtime_transcribe_v1": (
        _voice_realtime_transcribe_v1,
        "app.services.voice_runtime",
        "bound",
    ),
    "voice_realtime_speak_v1": (_voice_realtime_speak_v1, "app.services.voice_runtime", "bound"),
    "voice_realtime_translate_v1": (
        _voice_realtime_translate_v1,
        "app.services.voice_runtime",
        "bound",
    ),
    "voice_oracle_turn_v1": (_voice_oracle_turn_v1, "app.services.knowledge_capture", "bound"),
    "voice_tandem_oracle_v1": (
        _voice_tandem_oracle_v1,
        "app.services.voice_tandem_oracle",
        "bound",
    ),
    "knowledge_gap_analysis_v1": (
        _knowledge_gap_analysis_v1,
        "app.services.knowledge_capture",
        "bound",
    ),
    "expert_interview_plan_v1": (
        _expert_interview_plan_v1,
        "app.services.knowledge_capture",
        "bound",
    ),
    "expert_answer_evaluator_v1": (
        _expert_answer_evaluator_v1,
        "app.services.knowledge_capture",
        "bound",
    ),
    "capture_structuring_v1": (_capture_structuring_v1, "app.services.knowledge_capture", "bound"),
    "audit_log_v1": (_audit_log_v1, None, "bound"),
    "ollama_llm_v1": (_ollama_llm_v1, "app.services.model_clients.ollama_client", "bound"),
    "azure_llm_v1": (_azure_llm_v1, "app.services.model_clients.openai_client", "bound"),
    "chain_naive_v1": (_chain_naive_v1, "app.services.rag.chains.naive", "bound"),
    "chain_hybrid_v1": (_chain_hybrid_v1, "app.services.rag.chains.hybrid", "bound"),
    "chain_mixed_hah_v1": (_chain_mixed_hah_v1, "app.services.rag.chains.mixed_hah", "bound"),
    "chat_agentic_plan_v1": (_chat_agentic_plan_v1, "app.services.model_router", "bound"),
    "chat_self_correct_v1": (_chat_self_correct_v1, "app.services.model_router", "bound"),
    "response_eval_v1": (_response_eval_v1, "app.services.metrics.evaluator", "bound"),
    "spreadsheet_table_extract_v1": (
        _spreadsheet_table_extract_v1,
        "app.services.reconciliation",
        "bound",
    ),
    "invoice_document_extract_v1": (
        _invoice_document_extract_v1,
        "app.services.reconciliation",
        "bound",
    ),
    "line_items_reconcile_v1": (
        _line_items_reconcile_v1,
        "app.services.reconciliation",
        "bound",
    ),
    "reconciliation_report_v1": (
        _reconciliation_report_v1,
        "app.services.reconciliation",
        "bound",
    ),
}

_RESOLVED_STATUS: dict[str, str] = {}


def resolve(slug: str) -> SkillCallable:
    """Return the runtime callable bound to a seeded skill slug.

    Fail-closed, in two different ways because the two mistakes differ.
    Resolution used to hand back a callable that raised only once awaited, so
    the failure surfaced as a node the walker had already committed to running.

    An unknown seeded slug raises ``NotImplementedError``: nothing was ever
    declared for it, which the walker records as a skipped node. A
    workspace-namespaced slug raises instead, because reaching here means a
    caller skipped executor resolution entirely — its runtime binding lives on
    the Skill row (cf. :func:`app.services.skills_registry.executors.bind_executor`)
    and treating that as "not declared" would turn a dispatch bug into a quietly
    skipped node.
    """
    if is_workspace_skill_slug(slug):
        raise SkillBindingError(
            code="workspace_skill_requires_executor",
            message=(
                f"{slug} is a workspace-defined Skill and has no registry wrapper; "
                "it must be resolved through its verified executor binding."
            ),
        )
    entry = _REGISTRY.get(slug)
    if entry is None:
        raise NotImplementedError(
            f"No runtime wrapper is bound to {slug!r}. Add it to `_REGISTRY` in "
            "`skills_registry/wrappers.py` or mark it as a stub."
        )
    return entry[0]


def runtime_status(slug: str) -> str:
    """Return ``bound`` | ``stub`` | ``unbound`` for a slug.

    Evaluates the dependency import on first call so we catch missing
    modules without forcing eager imports at startup.
    """
    if slug in _RESOLVED_STATUS:
        return _RESOLVED_STATUS[slug]
    entry = _REGISTRY.get(slug)
    if entry is None:
        _RESOLVED_STATUS[slug] = "unbound"
        return "unbound"
    _, module_path, hint = entry
    if module_path is None:
        _RESOLVED_STATUS[slug] = hint
        return hint
    try:
        importlib.import_module(module_path)
        _RESOLVED_STATUS[slug] = "bound"
        return "bound"
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "skills_registry: dependency import failed — marking stub",
            slug=slug,
            module=module_path,
            error=str(exc),
        )
        _RESOLVED_STATUS[slug] = "stub"
        return "stub"


def bound_slugs() -> dict[str, str]:
    """Return `{slug: status}` for every registered skill (tri-state)."""
    return {slug: runtime_status(slug) for slug in _REGISTRY}


def registry_snapshot() -> dict[str, dict[str, Any]]:
    """Richer report for admin / observability endpoints."""
    snap: dict[str, dict[str, Any]] = {}
    for slug, (_fn, module_path, hint) in _REGISTRY.items():
        snap[slug] = {
            "status": runtime_status(slug),
            "declared_status": hint,
            "module": module_path,
        }
    return snap
