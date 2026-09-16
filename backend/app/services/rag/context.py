"""Canonical RAG context retrieval contract.

This module isolates the retrieval-only part of the RAG pipeline so it can run
inline in the chat process or out-of-band in a Celery worker without changing
the payload consumed by ``OmniRAGAgent``.
"""

from __future__ import annotations

import asyncio
import copy
import json
import math
import re
import time
from collections import OrderedDict
from collections.abc import Mapping
from datetime import date, datetime
from hashlib import sha1, sha256
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace
from app.services.document_intelligence import DocumentQueryEngine, should_run_document_analysis
from app.services.knowledge_collections import collection_inventory
from app.services.knowledge_guides import effective_guides, guide_context_entries, guide_query_hint
from app.services.rag.comparative_retrieval import (
    augment_with_comparative_subqueries,
    build_comparative_plan,
    ensure_entity_coverage,
)
from app.services.rag.corpus_planner import (
    is_catalogue_query,
    normalize_latency_profile,
    plan_corpus,
)
from app.services.rag.cross_encoder_stage import rerank_with_cross_encoder
from app.services.rag.decision_trace import build_retrieval_decision_trace
from app.services.rag.knowledge_scopes import (
    fallback_scope,
    resolve_expert_fiche_collection,
    resolve_knowledge_scope,
)
from app.services.rag.lexical_retrieval import analyze_query, lexical_match_details
from app.services.rag.mode_selector import resolve_retrieval_mode
from app.services.rag.pipeline_retrieval import (
    prioritise_temporary_measure_evidence_aligned,
    retrieve_for_mode,
)
from app.services.rag.project_inventory import (
    build_project_inventory,
    query_targets_projects,
)
from app.services.rag.project_references import extract_query_project_codes
from app.services.rag.retrieval_policy import (
    RetrievalPolicy,
    clarification_from_policy,
    filter_aligned_to_required_terms,
    is_document_discovery_query,
    policy_prompt,
    rerank_aligned_with_policy,
    retrieval_policy_from_guides,
)
from app.services.rag.retrieval_profiles import (
    normalize_retrieval_profile_name,
    retrieval_profile_for,
)
from app.services.rag.source_facets import expanded_terms_for_query
from app.services.rag.summary_artifacts import load_summary_index_records
from app.services.rag.vector_store_config import resolve_vector_db_type
from app.services.table_intelligence import TableQueryEngine, should_run_table_analysis

logger = get_logger(__name__)

_RETRIEVAL_CONTEXT_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

_SPREADSHEET_SHEET_PREFIX_RE = re.compile(
    r"\bspreadsheet\s+sheet:\s*.*?(?=\s+row\s+\d+:)",
    re.IGNORECASE,
)
_FOLLOW_UP_RE = re.compile(
    r"\b("
    r"diff[ée]rentes?|plusieurs|autres?|reste|documents?|valeurs?|"
    r"ce|ces|cette|celle|celui|ceux|cela|ça|son|sa|ses|leurs?|m[êe]me|ailleurs|compare|compar[ée]r|"
    r"globalement|partout|tous|toutes|ensemble|connais|connues?|"
    r"et\s+pour|et\s+sur|quid|idem|pareil|aussi|[ée]galement|"
    r"different|multiple|other|same|those|these|this|it|them|compare|globally|all|known|"
    r"what\s+about|and\s+for|likewise|"
    r"und\s+f[üu]r|dieselbe[nr]?|derselbe|dasselbe|auch|ebenfalls|gleiche[nr]?"
    r")\b",
    re.IGNORECASE,
)
_SPREADSHEET_SIGNAL_RE = re.compile(
    r"\b("
    r"diam[eè]tre|diameter|label|lettre|letter|def\s+strips?|strip|strips|"
    r"table|valeur|value|sheet|feuille"
    r")\b",
    re.IGNORECASE,
)
_INVENTORY_EXCLUSION_RE = re.compile(
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
# The Agentic chat membrane is 40 s end-to-end.  Do not let this optional
# evidence lane consume the time reserved for grounded generation/evaluation.
_INVENTORY_EVIDENCE_RETRIEVAL_CUTOFF_SECONDS = 30.0
_CONTENT_SEARCH_HINT_RE = re.compile(
    r"\b("
    r"sur|about|parle(?:nt)?|contien(?:t|nent)|mentionn(?:e|ent)|trait(?:e|ent)|"
    r"au\s+sujet|concerne|couvre|covers?|d[ée]tail|r[ée]sume|explique"
    r")\b",
    re.IGNORECASE,
)
_DOCUMENT_DISCOVERY_RE = re.compile(
    r"\bquels?\s+documents?\b.*\b(?:parle(?:nt)?|pour|sur|concerne|concernent|de\s+[a-z0-9_-]{3,})\b",
    re.IGNORECASE,
)
_SOURCE_LOOKUP_NOT_INVENTORY_RE = re.compile(
    r"\b(?:quel|quelle|quels?|which|what)\b.*\b(?:source|document|fichier|file)\b"
    r".*\b(?:ouvrir|open|citer|cite|contient|contains?|correspond|bonne|right|faut[-\s]?il|dois[-\s]?je)\b",
    re.IGNORECASE,
)
_TABLE_VALUE_LOOKUP_RE = re.compile(
    r"\b(que\s+vaut|valeur|value|label|table|feuille|sheet|cellule|cell|ligne|row|colonne|column|"
    r"inventory\s+line|stock\s+line)\b",
    re.IGNORECASE,
)


# Document-discovery queries ("quels documents… ?") need a wide candidate pool
# *before* the policy rerank so the specific content docs (annex/operating_manual)
# can be promoted above generic cover/index pages. The merged pool is reranked
# and filtered while wide, then truncated back to ``top_k`` so prompt size and
# latency stay identical to non-discovery queries.
#
# The floor is deliberately deep: the CHAH pipeline fans the query into several
# query-variants (incl. bare project-code expansions) and RRF-merges them, which
# pushes a content doc that only matches the *semantic* variant far down the pool
# (observed: a wanted annex doc at CHAH merge rank ~110 while generic project
# cover pages dominate the head). A shallow pool would never feed those docs to
# the rerank, so discovery widens to a pool that reaches them.
_DISCOVERY_POOL_K = 120


def _discovery_pool_top_k(top_k: int, is_discovery: bool) -> int:
    """Widen the per-collection / fusion candidate pool for discovery intent only."""
    return max(top_k, _DISCOVERY_POOL_K) if is_discovery else top_k


def _int_or_default(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _int_clamped(value: Any, default: int, *, minimum: int = 1, maximum: int = 200) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def is_collection_inventory_query(query: str) -> bool:
    from app.services.rag.conversation_anchors import strip_conversation_anchor

    text = strip_conversation_anchor(query).strip()
    if not text:
        return False
    # "Quels documents parlent de X ?" is a content-discovery query, not an
    # inventory/cardinality question. Keep that path on vector retrieval.
    if (
        _DOCUMENT_DISCOVERY_RE.search(text)
        or _SOURCE_LOOKUP_NOT_INVENTORY_RE.search(text)
        or (
            re.search(r"\b(?:quels?|which|what)\b", text, re.IGNORECASE)
            and _CONTENT_SEARCH_HINT_RE.search(text)
        )
    ):
        return False
    if (
        re.search(r"\b(?:source|document|fichier|file)\b", text, re.IGNORECASE)
        and re.search(
            r"\b[A-Z]{2,}[A-Z0-9\s_-]*\d{2,}[A-Z0-9]*\b",
            text,
        )
        and not re.search(
            r"\b(combien|nombre|count|how\s+many|types?|formats?|extensions?)\b",
            text,
            re.IGNORECASE,
        )
    ):
        return False
    if _TABLE_VALUE_LOOKUP_RE.search(text) and not re.search(
        r"\b(combien|nombre|count|how\s+many|types?|formats?|extensions?)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    if is_catalogue_query(text):
        return True
    return False


def _explicit_mode(value: Any) -> str | None:
    """Return a real retrieval-mode override, treating UI ``Auto`` as unset."""
    mode = str(value or "").strip().lower()
    if not mode or mode == "auto":
        return None
    return mode


def _mode_requests_dense_only(value: Any) -> bool:
    return str(value or "").strip().lower() in {"vector", "vector_only", "dense", "dense_only"}


def _native_qdrant_sparse_hybrid_available() -> bool:
    backend = str(getattr(settings, "rag_sparse_backend", "auto") or "auto").strip().lower()
    return bool(
        getattr(settings, "rag_qdrant_sparse_enabled", False)
        and backend in {"auto", "qdrant", "qdrant_sparse"}
    )


def _similarity_threshold() -> float:
    try:
        return max(0.0, min(1.0, float(getattr(settings, "rag_similarity_threshold", 0.0) or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _is_threshold_exempt_metadata(metadata: Mapping[str, Any]) -> bool:
    source_type = str(metadata.get("source_type") or metadata.get("type") or "").strip().lower()
    semantic_type = str(metadata.get("semantic_type") or "").strip().lower()
    return source_type in {
        "knowledge_guide",
        "summary_artifact",
        "table_analysis",
        "document_analysis",
        "collection_inventory",
        "dense_coarse_guardrail",
    } or semantic_type in {
        "knowledge_guide",
        "summary_artifact",
        "table_analysis",
        "document_analysis",
        "collection_inventory",
        "dense_coarse_guardrail",
    }


def _apply_similarity_threshold(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    pipeline: str | None,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    """Apply the configured dense-similarity gate to vector-like scores.

    RRF/HAH scores are rank-fusion weights, not cosine similarities. Applying a
    cosine threshold to those values would drop good sparse/exact evidence, so
    the threshold is enforced only on the pure dense/vector path.
    """
    threshold = _similarity_threshold()
    if threshold <= 0 or not chunks:
        return (
            chunks,
            scores,
            metadatas,
            {
                "score_threshold": threshold,
                "score_threshold_applied": False,
                "score_threshold_filtered": 0,
                "score_threshold_skipped_reason": "disabled" if threshold <= 0 else "empty",
            },
        )

    if str(pipeline or "").strip().lower() != "naive":
        # Fused scores are rank weights, but the per-chunk dense cosine is
        # preserved in metadata at the dense layer (``dense_score``). Gate on
        # it where present; sparse-only chunks carry no dense_score and pass.
        fused_chunks: list[str] = []
        fused_scores: list[float] = []
        fused_metadatas: list[dict[str, Any]] = []
        fused_removed = 0
        for index, chunk in enumerate(chunks):
            score = float(scores[index]) if index < len(scores) else 0.0
            metadata = dict(metadatas[index] if index < len(metadatas) else {})
            try:
                dense_value = (
                    float(metadata["dense_score"])
                    if metadata.get("dense_score") is not None
                    else None
                )
            except (TypeError, ValueError):
                dense_value = None
            if (
                dense_value is None
                or dense_value >= threshold
                or _is_threshold_exempt_metadata(metadata)
            ):
                fused_chunks.append(chunk)
                fused_scores.append(score)
                fused_metadatas.append(metadata)
            else:
                fused_removed += 1
        return (
            fused_chunks,
            fused_scores,
            fused_metadatas,
            {
                "score_threshold": threshold,
                "score_threshold_applied": fused_removed > 0,
                "score_threshold_filtered": fused_removed,
                "score_threshold_skipped_reason": None
                if fused_removed
                else "non_vector_score_scale",
            },
        )

    kept_chunks: list[str] = []
    kept_scores: list[float] = []
    kept_metadatas: list[dict[str, Any]] = []
    removed = 0
    for index, chunk in enumerate(chunks):
        score = float(scores[index]) if index < len(scores) else 0.0
        metadata = dict(metadatas[index] if index < len(metadatas) else {})
        if score >= threshold or _is_threshold_exempt_metadata(metadata):
            kept_chunks.append(chunk)
            kept_scores.append(score)
            kept_metadatas.append(metadata)
        else:
            removed += 1
    return (
        kept_chunks,
        kept_scores,
        kept_metadatas,
        {
            "score_threshold": threshold,
            "score_threshold_applied": True,
            "score_threshold_filtered": removed,
            "score_threshold_skipped_reason": None,
        },
    )


def _conversation_history(request: dict[str, Any]) -> list[dict[str, Any]]:
    context = request.get("context") if isinstance(request.get("context"), Mapping) else {}
    history = context.get("conversation_history") if isinstance(context, Mapping) else None
    return (
        [item for item in history if isinstance(item, Mapping)] if isinstance(history, list) else []
    )


def _history_augmented_query(request: dict[str, Any]) -> str:
    """Keep follow-up retrieval grounded in the previous user turn.

    The LLM prompt already receives conversation history, but retrieval used to
    search only the latest short follow-up ("des valeurs différentes ?"). For
    tabular lookups, that drops the label/sheet anchor from the prior turn and
    the vector search falls back to noisy spreadsheet headers. We only augment
    follow-ups when the current turn is referential/comparative and a recent
    user turn contains spreadsheet/table signals.
    """
    # Retrieval must preserve the user's exact words. An LLM rewrite can be
    # useful for display or generic reasoning, but in document search it can
    # silently corrupt domain terms ("carde" -> "carte") and destroy recall.
    # Keep opt-in support for specialised callers, but default to the raw turn.
    from app.services.rag.conversation_anchors import ANCHOR_PREFIX

    if request.get("use_rewritten_query_for_retrieval") is True:
        query = str(request.get("rewritten_query") or request.get("query") or "").strip()
    else:
        query = str(request.get("query") or "").strip()
    if not query or not _FOLLOW_UP_RE.search(query):
        return query

    recent_user_messages: list[str] = []
    for item in reversed(_conversation_history(request)):
        if str(item.get("role") or "").lower() != "user":
            continue
        content = str(item.get("content") or "").strip()
        if content and content not in recent_user_messages:
            recent_user_messages.append(content)
        if len(recent_user_messages) >= 3:
            break

    anchors = [msg for msg in recent_user_messages if _SPREADSHEET_SIGNAL_RE.search(msg)]
    if anchors:
        return " | ".join([query, ANCHOR_PREFIX, *reversed(anchors[:2])])

    # No tabular anchor: fall back to domain anchors (project/machine codes,
    # document names) so an anaphoric follow-up ("et pour cette machine ?")
    # still searches with the entity established earlier in the conversation.
    # Anchors are short verbatim terms, capped at 2, to avoid diluting the
    # query. Skip when the follow-up already carries its own reference.
    from app.services.rag.conversation_anchors import (
        anchor_terms,
        extract_salient_entities,
        has_reference,
    )

    if has_reference(query):
        return query
    context = request.get("context") if isinstance(request.get("context"), Mapping) else {}
    precomputed = context.get("salient_entities") if isinstance(context, Mapping) else None
    terms = anchor_terms(precomputed)
    if not terms:
        terms = anchor_terms(extract_salient_entities(*recent_user_messages))
    if not terms:
        return query
    return " | ".join([query, ANCHOR_PREFIX, *terms])


def _apply_source_policy_to_retrieval_policy(
    request: Mapping[str, Any],
    retrieval_policy: "RetrievalPolicy | None",
) -> "RetrievalPolicy | None":
    """Fold the workspace chat source_policy into the retrieval policy.

    ``reject_cross_project_sources`` activates the existing project-code match
    enforcement. Rollout is gated by ``rag_reject_cross_project_enforce``:
    until collections carry project_code payloads (backfill), the filter runs
    in shadow/log-only mode so untagged corpora keep their evidence.

    ``source_policy`` is free-form and flows end-to-end untouched, so other
    consumers read their own keys without a schema change. Expert fiche
    correction adds two such keys here: ``expert_fiche_correction_enabled``
    (bool) and ``expert_fiche_collection`` (str|null, resolved via
    ``resolve_expert_fiche_collection``). They are consumed by scope inclusion
    and the ranking boost in Volet 3, not by this retrieval-policy fold.
    """
    source_policy = request.get("source_policy")
    if not isinstance(source_policy, Mapping):
        return retrieval_policy
    if not bool(source_policy.get("reject_cross_project_sources")):
        return retrieval_policy
    from dataclasses import replace as dataclass_replace

    log_only = not bool(settings.rag_reject_cross_project_enforce)
    if retrieval_policy is None:
        return RetrievalPolicy(
            require_project_code_match=True,
            cross_project_log_only=log_only,
        )
    if retrieval_policy.require_project_code_match and not log_only:
        return retrieval_policy
    return dataclass_replace(
        retrieval_policy,
        require_project_code_match=True,
        cross_project_log_only=log_only and not retrieval_policy.require_project_code_match,
    )


def _enabled_expert_fiche_collection(
    *,
    workspace_slug: Any,
    source_policy: Any,
) -> str:
    """Resolve the expert-fiche collection slug when the feature is on, else "".

    Returns ``""`` unless the workspace opted in via
    ``source_policy["expert_fiche_correction_enabled"]``; otherwise the resolved
    ``resolve_expert_fiche_collection`` slug. Shared by the profile-time
    inclusion (``_include_expert_fiche_collection``) and the post-planner union
    in ``retrieve_rag_context`` so both agree on the destination slug.
    """
    if not isinstance(source_policy, Mapping):
        return ""
    if not bool(source_policy.get("expert_fiche_correction_enabled")):
        return ""
    return resolve_expert_fiche_collection({"slug": workspace_slug}, source_policy)


def _include_expert_fiche_collection(
    collections: list[str],
    *,
    workspace_slug: Any,
    source_policy: Any,
) -> list[str]:
    """Add the resolved expert-fiche collection to the searched set (Volet 3).

    No-op unless the workspace opted in via
    ``source_policy["expert_fiche_correction_enabled"]``. The destination slug is
    resolved with ``resolve_expert_fiche_collection`` and appended dedup-preserving
    so a validated expert fiche is always retrievable for the chat turn when the
    feature is on; the order returned when OFF is byte-for-byte unchanged.
    """
    slug = _enabled_expert_fiche_collection(
        workspace_slug=workspace_slug,
        source_policy=source_policy,
    )
    if slug and slug not in collections:
        collections.append(slug)
    return collections


def _apply_membrane_inbound_collections(
    collections: list[str],
    *,
    source_policy: Any,
) -> list[str]:
    """Membrane inbound facet — restrict the searched collections to the
    authoritative allowlist (P3).

    Read-through and v1 remain byte-for-byte compatible.  An authoritative v2
    ``enforce`` contract is fail-closed: an empty intersection is a policy
    error and can never broaden back to the original collection set.
    """
    if not isinstance(source_policy, Mapping):
        return collections
    try:
        from app.services.membrane.enforcement import enforce_inbound_collections
        from app.services.membrane.spec import resolve_membrane_spec

        spec = resolve_membrane_spec(source_policy=source_policy)
        decision = enforce_inbound_collections(spec, collections)
    except ValueError:
        # An invalid explicit v2 contract is unsafe to interpret.
        raise
    except Exception:  # noqa: BLE001 — v1/derived retain fail-soft behaviour.
        return collections
    if decision.blocked:
        from app.services.membrane.enforcement import MembraneEnforcementError

        raise MembraneEnforcementError("membrane_inbound_no_allowed_collections")
    return decision.collections


def _apply_membrane_inbound_evidence(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    profile: Mapping[str, Any],
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    """Apply v2 reference-type/project constraints to the final evidence set."""

    raw_spec = profile.get("_membrane_spec")
    if not isinstance(raw_spec, Mapping):
        return chunks, scores, metadatas, {}
    from app.services.membrane.enforcement import (
        MembraneEnforcementError,
        enforce_inbound_sources,
    )
    from app.services.membrane.spec import resolve_membrane_spec

    spec = resolve_membrane_spec(source_policy={"membrane_spec": raw_spec})
    sources = [
        {"_index": index, "metadata": metadata if isinstance(metadata, Mapping) else {}}
        for index, metadata in enumerate(metadatas)
    ]
    decision = enforce_inbound_sources(
        spec,
        sources,
        expected_project=str(profile.get("_membrane_expected_project") or "") or None,
    )
    if decision.blocked:
        raise MembraneEnforcementError("membrane_inbound_no_allowed_evidence")
    keep = [int(source["_index"]) for source in decision.sources]
    if not keep and not sources:
        keep = []
    telemetry = {
        "mode": decision.mode,
        "violations": list(decision.violations),
        "would_block": decision.would_block,
        "filtered_count": max(0, len(sources) - len(keep)),
    }
    return (
        [chunks[index] for index in keep if index < len(chunks)],
        [scores[index] for index in keep if index < len(scores)],
        [metadatas[index] for index in keep if index < len(metadatas)],
        telemetry,
    )


def _deep_rewrite_variants(
    request: Mapping[str, Any], profile: Mapping[str, Any]
) -> list[str] | None:
    """LLM-rewritten query joins the retrieval fan-out on the deep path only.

    The rewrite is injected as an EXTRA chah variant, never substituting the
    raw query (an LLM rewrite can corrupt domain terms — "carde" -> "carte").
    Fast/balanced paths never pay for or depend on it.
    """
    if str(profile.get("latency_profile") or "") != "deep":
        return None
    rewritten = str(request.get("rewritten_query") or "").strip()
    raw = str(request.get("query") or "").strip()
    if not rewritten or rewritten == raw:
        return None
    return [rewritten]


def _jsonable(value: Any) -> Any:
    """Return a Celery JSON-serialisable copy of nested metadata."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return str(value)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _deadline_seconds_for_profile(latency_profile: str) -> float:
    profile = normalize_latency_profile(latency_profile)
    if profile == "deep":
        return float(settings.rag_deep_retrieval_deadline_seconds)
    if profile == "balanced":
        return float(min(settings.rag_fast_retrieval_deadline_seconds * 2, 20.0))
    return float(settings.rag_fast_retrieval_deadline_seconds)


def _finalize_retrieval_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Normalize observability keys across inventory, guardrail and RAG paths."""
    scope = (
        metrics.get("retrieval_scope")
        if isinstance(metrics.get("retrieval_scope"), Mapping)
        else {}
    )
    existing_timings = (
        metrics.get("stage_timings") if isinstance(metrics.get("stage_timings"), Mapping) else {}
    )
    planner_ms = _int_or_none(_first_present(metrics.get("planner_ms"), scope.get("planner_ms")))
    total_ms = _int_or_none(metrics.get("duration_ms"))
    qdrant_ms = _int_or_none(
        _first_present(
            metrics.get("qdrant_ms"),
            metrics.get("dense_elapsed_ms"),
            metrics.get("dense_ms"),
            existing_timings.get("qdrant_ms"),
        )
    )
    sparse_ms = _int_or_none(
        _first_present(
            metrics.get("sparse_ms"),
            metrics.get("sparse_elapsed_ms"),
            existing_timings.get("sparse_ms"),
        )
    )
    retrieval_ms = _int_or_none(
        _first_present(
            metrics.get("retrieval_ms"),
            metrics.get("retrieval_elapsed_ms"),
            existing_timings.get("retrieval_ms"),
        )
    )
    inventory_ms = _int_or_none(
        _first_present(metrics.get("inventory_ms"), existing_timings.get("inventory_ms"))
    )
    rerank_ms = _int_or_none(
        _first_present(metrics.get("rerank_ms"), existing_timings.get("rerank_ms"))
    )
    context_build_ms = _int_or_none(
        _first_present(metrics.get("context_build_ms"), existing_timings.get("context_build_ms"))
    )
    table_facts_ms = _int_or_none(
        _first_present(
            metrics.get("table_facts_ms"),
            metrics.get("exact_table_elapsed_ms"),
            existing_timings.get("table_facts_ms"),
        )
    )
    embedding_ms = _int_or_none(
        _first_present(metrics.get("embedding_ms"), existing_timings.get("embedding_ms"))
    )
    llm_ms = _int_or_none(_first_present(metrics.get("llm_ms"), existing_timings.get("llm_ms")))
    stage_timings = {
        "planner_ms": planner_ms,
        "inventory_ms": inventory_ms,
        "embedding_ms": embedding_ms,
        "qdrant_ms": qdrant_ms,
        "sparse_ms": sparse_ms,
        "retrieval_ms": retrieval_ms,
        "rerank_ms": rerank_ms,
        "context_build_ms": context_build_ms,
        "table_facts_ms": table_facts_ms,
        "llm_ms": llm_ms,
        "total_ms": total_ms,
    }
    candidate_counts = {
        "source_count": _int_or_none(scope.get("source_count")),
        "chunk_count": _int_or_none(scope.get("chunk_count")),
        "candidate_pool_k": _int_or_none(metrics.get("candidate_pool_k")),
        "synthesis_k": _int_or_none(metrics.get("synthesis_k")),
        "source_display_k": _int_or_none(metrics.get("source_display_k")),
        "raw_chunks_retrieved": _int_or_none(metrics.get("raw_chunks_retrieved")),
        "document_chunks_retrieved": _int_or_none(metrics.get("document_chunks_retrieved")),
        "chunks_retrieved": _int_or_none(metrics.get("chunks_retrieved")),
        "duplicates_removed": _int_or_none(metrics.get("duplicates_removed")),
        "sparse_results": _int_or_none(metrics.get("sparse_results")),
        "exact_metadata_hits": _int_or_none(metrics.get("exact_metadata_hits")),
        "exact_table_hits": _int_or_none(metrics.get("exact_table_hits")),
    }
    metrics["planner_ms"] = planner_ms
    metrics["qdrant_ms"] = qdrant_ms
    metrics["sparse_ms"] = sparse_ms
    metrics["retrieval_ms"] = retrieval_ms
    metrics["stage_timings"] = stage_timings
    metrics["candidate_counts"] = candidate_counts
    try:
        from app.services.embedding.embedder import get_shared_embedder

        embedder_info = get_shared_embedder().describe()
        metrics.setdefault("embedding_provider", embedder_info["provider"])
        metrics.setdefault("embedding_model", embedder_info["model_name"])
        if embedder_info.get("degraded"):
            metrics["embedding_degraded"] = True
    except Exception:  # noqa: BLE001 - telemetry must never break retrieval
        pass
    trace = metrics.get("retrieval_trace")
    if isinstance(trace, dict):
        trace["timings"] = stage_timings
        trace["candidate_counts"] = candidate_counts
    if not isinstance(metrics.get("retrieval_decision_trace"), Mapping):
        try:
            metrics["retrieval_decision_trace"] = build_retrieval_decision_trace(
                metrics=metrics,
                trace_source=str(metrics.get("retrieval_decision_trace_source") or "runtime"),
            )
        except Exception:  # noqa: BLE001 - telemetry must never break retrieval
            metrics["retrieval_decision_trace"] = {
                "version": 1,
                "trace_source": "runtime",
                "selected_route": str(
                    metrics.get("pipeline") or metrics.get("mode_label") or "retrieval"
                ),
                "summary": "Retrieval decision trace unavailable; raw metrics are still present.",
                "fallbacks": [{"kind": "trace_build_error", "reason": "failed_to_build_trace"}],
            }
    return metrics


def _normalise_authoritative_document_refs(
    raw_refs: Any,
    *,
    collections: list[str],
) -> dict[str, list[str]]:
    """Return a bounded collection -> document-id allowlist.

    The collection/document pair is security-significant. Flattening it into a
    single list and applying that list to every collection permits accidental
    cross-collection matches when document identifiers collide.
    """

    if not isinstance(raw_refs, Mapping):
        return {}
    allowed_collections = set(collections)
    normalized: dict[str, list[str]] = {}
    total = 0
    for raw_collection, raw_document_ids in raw_refs.items():
        collection = str(raw_collection or "").strip()
        if (
            not collection
            or collection not in allowed_collections
            or not isinstance(raw_document_ids, list | tuple | set)
        ):
            continue
        document_ids = list(
            dict.fromkeys(
                str(item).strip()
                for item in raw_document_ids
                if isinstance(item, str) and item.strip()
            )
        )
        remaining = max(0, 1000 - total)
        if document_ids and remaining:
            normalized[collection] = document_ids[:remaining]
            total += len(normalized[collection])
        if total >= 1000:
            break
    return normalized


def _authoritative_filters_for_collection(
    profile: Mapping[str, Any],
    collection: Any,
    retrieval_filters: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Narrow filters to the documents explicitly selected for a collection.

    ``None`` is fail-closed: an authoritative pair-map exists but contains no
    selected document for this collection, so that collection must not run.
    """

    filters = dict(retrieval_filters or {})
    if profile.get("authoritative_document_scope") is not True:
        return filters
    refs = profile.get("authoritative_document_refs")
    refs_provided = profile.get("authoritative_document_refs_provided") is True
    if not refs_provided and (not isinstance(refs, Mapping) or not refs):
        # Compatibility for older scoped snapshots that only carried the flat
        # document_id filter. It is safe only for one known collection; applying
        # a flat union to several collections recreates a collection/document
        # cartesian product when identifiers collide.
        document_ids = filters.get("document_id")
        effective_collections = [
            str(item).strip()
            for item in (profile.get("collections") or [])
            if str(item or "").strip()
        ]
        if not effective_collections:
            single_collection = str(profile.get("collection") or "").strip()
            if single_collection:
                effective_collections = [single_collection]
        normalized_document_ids = (
            list(
                dict.fromkeys(
                    item.strip()
                    for item in document_ids
                    if isinstance(item, str) and item.strip() == item
                )
            )
            if isinstance(document_ids, list)
            else []
        )
        if (
            not normalized_document_ids
            or not all(
                isinstance(item, str) and bool(item) and item.strip() == item
                for item in (document_ids or [])
            )
            or len(effective_collections) != 1
            or effective_collections[0] != str(collection)
        ):
            return None
        filters["document_id"] = normalized_document_ids[:1000]
        return filters
    if not isinstance(refs, Mapping) or not refs:
        return None
    document_ids = refs.get(str(collection))
    if not isinstance(document_ids, list) or not document_ids:
        return None
    filters["document_id"] = list(document_ids)
    return filters


def _enforce_authoritative_document_evidence(
    chunks: list[Any],
    scores: list[Any],
    metadatas: list[Any],
    *,
    profile: Mapping[str, Any],
    collection: str | None = None,
) -> tuple[list[Any], list[Any], list[dict[str, Any]], int]:
    """Revalidate backend evidence against the graph-owned document allowlist.

    Some legacy vector adapters reject filters or fall back to an unfiltered
    search. The adapter is therefore not a trust boundary: missing metadata and
    collection/document mismatches are dropped before rerank or synthesis.
    """

    if profile.get("authoritative_document_scope") is not True:
        return (
            list(chunks),
            list(scores),
            [dict(item) if isinstance(item, Mapping) else {} for item in metadatas],
            0,
        )

    kept_chunks: list[Any] = []
    kept_scores: list[Any] = []
    kept_metadatas: list[dict[str, Any]] = []
    dropped = 0
    for index, chunk in enumerate(chunks):
        metadata = (
            dict(metadatas[index])
            if index < len(metadatas) and isinstance(metadatas[index], Mapping)
            else {}
        )
        lane_collection = str(collection or "").strip()
        declared_collections = list(
            dict.fromkeys(
                str(metadata.get(key) or "").strip()
                for key in ("collection", "collection_name", "collection_slug")
                if str(metadata.get(key) or "").strip()
            )
        )
        if len(declared_collections) > 1 or (
            lane_collection and declared_collections and declared_collections[0] != lane_collection
        ):
            dropped += 1
            continue
        effective_collection = declared_collections[0] if declared_collections else lane_collection
        filters = _authoritative_filters_for_collection(
            profile,
            effective_collection,
            profile.get("retrieval_filters")
            if isinstance(profile.get("retrieval_filters"), Mapping)
            else {},
        )
        allowed_document_ids = filters.get("document_id") if isinstance(filters, Mapping) else None
        document_id = metadata.get("document_id")
        if (
            not isinstance(allowed_document_ids, list)
            or not allowed_document_ids
            or not isinstance(document_id, str)
            or document_id not in allowed_document_ids
        ):
            dropped += 1
            continue
        kept_chunks.append(chunk)
        kept_scores.append(scores[index] if index < len(scores) else 0.0)
        kept_metadatas.append(metadata)
    return kept_chunks, kept_scores, kept_metadatas, dropped


def get_retrieval_profile(request: dict[str, Any]) -> dict[str, Any]:
    """Resolve retrieval settings that do not require a live vector search."""
    app_settings = get_resolved_settings(
        workspace_id=request.get("workspace_id"),
        capability_id=request.get("capability_id"),
        system_id=request.get("system_id"),
    )
    raw_retrieval_filters = (
        dict(request.get("retrieval_filters"))
        if isinstance(request.get("retrieval_filters"), Mapping)
        else {}
    )
    system_collection_scope = None
    for key in ("collection_slug", "collection"):
        value = raw_retrieval_filters.get(key)
        if isinstance(value, (list, tuple, set)):
            value = next((item for item in value if str(item or "").strip()), None)
        if str(value or "").strip():
            system_collection_scope = str(value).strip()
            break
    context_collection = str(request.get("context_collection") or "").strip()
    if system_collection_scope:
        context_collection = system_collection_scope
    context_mode = str(request.get("context_mode") or "").strip().lower()
    fallback_collection = context_collection or app_settings.get("ragCollectionName", "documents")
    if context_collection and not request.get("knowledge_scope"):
        context_key = str(request.get("context_id") or context_collection)
        scope = fallback_scope(
            context_collection,
            key=f"context_{sha1(context_key.encode('utf-8')).hexdigest()[:10]}",
        )
        scope["label"] = "System retrieval scope" if system_collection_scope else "Selected context"
    else:
        scope = resolve_knowledge_scope(
            workspace_id=request.get("workspace_id"),
            requested_key=request.get("knowledge_scope"),
            fallback_collection=fallback_collection,
        )
        if context_collection and context_mode == "combine":
            collections = list(scope.get("collection_slugs") or [])
            if context_collection not in collections:
                collections.append(context_collection)
            scope["collection_slugs"] = collections
            scope["label"] = (
                f"{scope.get('label') or scope.get('key') or 'Knowledge'} + Session docs"
            )
    agent_preferences = request.get("agent_preferences") or {}
    latency_profile = normalize_latency_profile(
        request.get("latency_profile") or agent_preferences.get("latency_profile"),
        deep_retrieval=request.get("deep_retrieval") or agent_preferences.get("deep_retrieval"),
    )
    retrieval_profile = normalize_retrieval_profile_name(
        request.get("retrieval_profile") or agent_preferences.get("retrieval_profile"),
        latency_profile=latency_profile,
    )
    profile_contract = retrieval_profile_for(retrieval_profile)
    if retrieval_profile in {"oracle_fast", "oracle_live_fast", "oracle_grounded_async"}:
        latency_profile = profile_contract.latency_profile
    elif retrieval_profile == "deep_async":
        latency_profile = profile_contract.latency_profile
    scope_default_mode = scope.get("default_mode")
    if scope_default_mode == "auto":
        scope_default_mode = None
    explicit_rag_mode = _explicit_mode(request.get("rag_pipeline_mode")) or _explicit_mode(
        agent_preferences.get("rag_pipeline_mode")
    )
    rag_mode = (
        explicit_rag_mode
        or scope_default_mode
        or app_settings.get("ragPipelineMode")
        or app_settings.get("mode")
    )
    if retrieval_profile in {"oracle_fast", "oracle_live_fast", "oracle_grounded_async"}:
        rag_mode = explicit_rag_mode or profile_contract.force_mode or "naive"
    explicit_top_k = request.get("top_k") is not None
    top_k = _int_or_default(
        request.get("top_k") or scope.get("top_k") or app_settings.get("ragTopK"),
        5,
    )
    explicit_budget = any(
        request.get(key) is not None
        for key in ("candidate_pool_k", "synthesis_k", "source_display_k")
    )
    source_display_default = top_k if explicit_top_k else min(max(top_k, 5), 8)
    app_source_display = (
        None if explicit_top_k and not explicit_budget else app_settings.get("ragSourceDisplayK")
    )
    source_display_k = _int_clamped(
        request.get("source_display_k") or app_source_display,
        source_display_default,
        minimum=1,
        maximum=24,
    )
    synthesis_default = (
        top_k if explicit_top_k and not explicit_budget else max(top_k, source_display_k, 12)
    )
    app_synthesis = (
        None if explicit_top_k and not explicit_budget else app_settings.get("ragSynthesisK")
    )
    synthesis_k = _int_clamped(
        request.get("synthesis_k") or app_synthesis,
        synthesis_default,
        minimum=source_display_k,
        maximum=48,
    )
    candidate_default = (
        top_k if explicit_top_k and not explicit_budget else max(synthesis_k * 4, 40)
    )
    app_candidate_pool = (
        None if explicit_top_k and not explicit_budget else app_settings.get("ragCandidatePoolK")
    )
    candidate_pool_k = _int_clamped(
        request.get("candidate_pool_k") or app_candidate_pool,
        candidate_default,
        minimum=synthesis_k,
        maximum=200,
    )
    if latency_profile == "fast":
        top_k = min(top_k, 8)
        source_display_k = min(source_display_k, 8)
        synthesis_k = min(max(synthesis_k, source_display_k), 12)
        candidate_pool_k = min(max(candidate_pool_k, synthesis_k), 20)
    elif latency_profile == "balanced":
        top_k = min(top_k, 12)
        source_display_k = min(source_display_k, 24)
        synthesis_k = min(max(synthesis_k, source_display_k), 24)
        candidate_pool_k = min(max(candidate_pool_k, synthesis_k), 80)
    elif latency_profile == "deep":
        top_k = min(top_k, 24)
        source_display_k = min(source_display_k, 24)
        synthesis_k = min(max(synthesis_k, source_display_k), 48)
        candidate_pool_k = min(max(candidate_pool_k, synthesis_k), 200)
    deadline_seconds = _deadline_seconds_for_profile(latency_profile)
    if retrieval_profile in {"oracle_fast", "oracle_live_fast", "oracle_grounded_async"}:
        top_k = min(top_k, profile_contract.max_top_k)
        source_display_k = min(source_display_k, profile_contract.max_source_display_k)
        synthesis_k = min(max(synthesis_k, source_display_k), profile_contract.max_synthesis_k)
        candidate_pool_k = min(
            max(candidate_pool_k, synthesis_k), profile_contract.max_candidate_pool_k
        )
        deadline_seconds = profile_contract.deadline_seconds or deadline_seconds
    collections = list(scope.get("collection_slugs") or [fallback_collection])
    authoritative_collections = [
        str(item).strip()
        for item in (request.get("authoritative_collections") or [])
        if str(item or "").strip()
    ]
    if authoritative_collections:
        # Runtime/System-owned hard boundary. Unlike the workspace membrane's
        # fail-soft intersection, an empty/mismatched upstream scope cannot
        # broaden this contract.
        collections = list(dict.fromkeys(authoritative_collections))
    else:
        collections = _include_expert_fiche_collection(
            collections,
            workspace_slug=request.get("workspace_slug"),
            source_policy=request.get("source_policy"),
        )
    collections = _apply_membrane_inbound_collections(
        collections,
        source_policy=request.get("source_policy"),
    )
    raw_authoritative_document_refs = request.get("authoritative_document_refs")
    authoritative_document_refs = _normalise_authoritative_document_refs(
        raw_authoritative_document_refs,
        collections=collections,
    )
    vector_db_type = resolve_vector_db_type(app_settings)
    return {
        "query": _history_augmented_query(request),
        "rag_mode": rag_mode,
        "retrieval_profile": retrieval_profile,
        "retrieval_profile_contract": profile_contract.as_dict(),
        "top_k": top_k,
        "candidate_pool_k": candidate_pool_k,
        "synthesis_k": synthesis_k,
        "source_display_k": source_display_k,
        "collection": collections[0],
        "collections": collections,
        "knowledge_scope": scope.get("key"),
        "scope_label": scope.get("label"),
        "vector_db": vector_db_type,
        "workspace_id": request.get("workspace_id"),
        "workspace_slug": request.get("workspace_slug"),
        "latency_profile": latency_profile,
        "deep_retrieval": bool(
            request.get("deep_retrieval") or agent_preferences.get("deep_retrieval")
        ),
        "deadline_seconds": deadline_seconds,
        "latency_budget": {
            "profile": latency_profile,
            "retrieval_profile": retrieval_profile,
            "allow_cross_encoder": profile_contract.allow_cross_encoder,
            "deadline_seconds": deadline_seconds,
            "top_k": top_k,
            "candidate_pool_k": candidate_pool_k,
        },
        "_membrane_spec": (
            request.get("source_policy", {}).get("membrane_spec")
            if isinstance(request.get("source_policy"), Mapping)
            else None
        ),
        "_membrane_expected_project": request.get("project_code"),
        # A Builder-authored document allowlist is a hard authority boundary,
        # not a planner hint. Downstream recovery paths must not drop it.
        "authoritative_document_scope": request.get("authoritative_document_scope") is True,
        "authoritative_document_refs": authoritative_document_refs,
        "authoritative_document_refs_provided": isinstance(
            raw_authoritative_document_refs,
            Mapping,
        ),
        "retrieval_filters": {
            key: value
            for key, value in raw_retrieval_filters.items()
            if key not in {"collection", "collection_slug"}
        },
    }


def apply_retrieval_profile_to_request(request: dict[str, Any]) -> dict[str, Any]:
    """Clamp fan-out and attach latency metadata before dispatching retrieval."""
    profile = get_retrieval_profile(request)
    for key in (
        "top_k",
        "candidate_pool_k",
        "synthesis_k",
        "source_display_k",
        "latency_profile",
        "retrieval_profile",
        "latency_budget",
    ):
        request[key] = profile[key]
    return profile


def _effective_guides_for_profile(profile: dict[str, Any]) -> list[Any]:
    workspace_id = profile.get("workspace_id")
    if not workspace_id:
        return []
    db = SessionLocal()
    try:
        return effective_guides(
            db,
            workspace_id=str(workspace_id),
            scope_key=profile.get("knowledge_scope"),
            collection_slugs=list(profile.get("collections") or []),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag_context: failed to load knowledge guides", error=str(exc))
        return []
    finally:
        db.close()


def _prepend_guide_context(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    guides: list[Any],
) -> tuple[list[str], list[float], list[dict[str, Any]], int]:
    guide_chunks, guide_scores, guide_metas = guide_context_entries(guides)
    if not guide_chunks:
        return chunks, scores, metadatas, 0
    # Knowledge Guides explain how to read a collection. They must not outrank
    # the raw chunks that carry the actual evidence, otherwise broad guide
    # cautions can hide exact spreadsheet hits such as "Def strips / B = 85".
    # Keep them in the prompt as advisory context, but after document evidence.
    return (
        chunks + guide_chunks,
        scores + guide_scores,
        metadatas + guide_metas,
        len(guide_chunks),
    )


def _normalised_project_codes(value: Any) -> set[str]:
    if isinstance(value, list | tuple | set):
        values = value
    else:
        values = (value,)
    return {str(item or "").strip().upper() for item in values if str(item or "").strip()}


def _matched_resolved_project_scope_codes(
    *,
    query: str,
    retrieval_filters: Mapping[str, Any] | None,
    metadatas: list[dict[str, Any]],
) -> set[str]:
    """Return requested project codes proven by both hard scope and results.

    Project identity remains owned by ``project_references``.  The hard filter
    alone is insufficient: a stale/wrong payload must still trip the exact
    guardrail, so a code is satisfied only when retrieved metadata carries the
    same canonical ``project_code``.
    """

    if not isinstance(retrieval_filters, Mapping):
        return set()
    filtered_codes = _normalised_project_codes(retrieval_filters.get("project_code"))
    if not filtered_codes:
        return set()
    requested_codes = set(
        extract_query_project_codes(query, known_codes=filtered_codes)
    ).intersection(filtered_codes)
    if not requested_codes:
        return set()
    retrieved_codes: set[str] = set()
    for metadata in metadatas:
        if isinstance(metadata, Mapping):
            retrieved_codes.update(_normalised_project_codes(metadata.get("project_code")))
    return requested_codes.intersection(retrieved_codes)


def _requested_terms_are_only_project_scope(
    requested_terms: set[str],
    project_codes: set[str],
) -> bool:
    """Whether lexical exact terms contain no identifier beyond the project.

    The generic lexical parser compacts ``projet 61035`` into
    ``PROJET61035``.  Treat that parser artefact as the already-proven project
    scope, but never consume a different document, component or part number.
    """

    project_terms = {
        term for code in project_codes for term in (code, f"PROJET{code}", f"PROJECT{code}")
    }
    return bool(requested_terms) and requested_terms.issubset(project_terms)


def _prepend_exact_match_guardrail_context(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    query: str,
    policy: RetrievalPolicy,
    diagnostics: Mapping[str, Any],
    retrieval_filters: Mapping[str, Any] | None = None,
) -> tuple[list[str], list[float], list[dict[str, Any]], int]:
    if diagnostics.get("exact_match_missing") is not True:
        return chunks, scores, metadatas, 0

    signals = analyze_query(query, policy.lexical_config if policy else None)
    requested = sorted(signals.exact_terms)
    if requested:
        requested_set = set(requested)
        for index, chunk in enumerate(chunks):
            metadata = metadatas[index] if index < len(metadatas) else {}
            details = lexical_match_details(
                content=str(chunk or ""),
                metadata=metadata if isinstance(metadata, Mapping) else {},
                query=query,
                config=policy.lexical_config if policy else None,
            )
            if requested_set.intersection(set(details.get("matched_exact_terms") or [])):
                return chunks, scores, metadatas, 0
    matched_project_codes = _matched_resolved_project_scope_codes(
        query=query,
        retrieval_filters=retrieval_filters,
        metadatas=metadatas,
    )
    if matched_project_codes and _requested_terms_are_only_project_scope(
        set(requested), matched_project_codes
    ):
        return chunks, scores, metadatas, 0
    requested_text = ", ".join(requested) if requested else "an explicit identifier"
    content = (
        "Retrieval exact-match guardrail.\n"
        f"The user asked for: {requested_text}.\n"
        "No retrieved source matched the requested identifier through exact metadata retrieval. "
        "Do not answer as if the requested document or code was found. State that exact evidence "
        "was not found in the scoped collection, and use any remaining context only as non-exact background."
    )
    metadata = {
        "source_type": "retrieval_guardrail",
        "semantic_type": "exact_match_guardrail",
        "document_filename": "retrieval-exact-match-guardrail",
        "citation_label": "Retrieval exact-match guardrail",
        "requested_exact_terms": requested,
        "exact_match_required": True,
        "exact_match_missing": True,
    }
    return [content, *chunks], [1.0, *scores], [metadata, *metadatas], 1


async def _append_parent_context(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    doc_svc: Any,
    max_parents: int = 3,
    max_chars: int = 2500,
) -> tuple[list[str], list[float], list[dict[str, Any]], int]:
    if not chunks or not metadatas:
        return chunks, scores, metadatas, 0
    expander = getattr(doc_svc, "parent_contexts_for_hits", None)
    if not callable(expander):
        return chunks, scores, metadatas, 0
    try:
        rows = await expander(metadatas, max_parents=max_parents, max_chars=max_chars)
    except Exception as exc:  # noqa: BLE001 - parent context is optional.
        logger.debug("rag_context: parent context expansion failed", error=str(exc))
        return chunks, scores, metadatas, 0
    if not rows:
        return chunks, scores, metadatas, 0

    out_chunks = list(chunks)
    out_scores = list(scores)
    out_metas = [dict(meta or {}) for meta in metadatas]
    seen = {_chunk_exact_key(chunk) for chunk in out_chunks}
    added = 0
    for row in rows[: max(1, int(max_parents or 1))]:
        if not isinstance(row, Mapping):
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        key = _chunk_exact_key(content)
        if key in seen:
            continue
        seen.add(key)
        metadata = dict(row.get("metadata") or {})
        metadata["source_type"] = "parent_context"
        metadata["semantic_type"] = metadata.get("semantic_type") or "parent_context"
        metadata["parent_context_expanded"] = True
        if metadata.get("document_filename") and not metadata.get("citation_label"):
            metadata["citation_label"] = f"{metadata.get('document_filename')} · parent context"
        try:
            score = min(max(float(row.get("score") or 0.35), 0.01), 0.65)
        except (TypeError, ValueError):
            score = 0.35
        out_chunks.append(f"Parent context:\n{content}")
        out_scores.append(score)
        out_metas.append(metadata)
        added += 1
    return out_chunks, out_scores, out_metas, added


def _retrieval_policy_summary(
    policy: RetrievalPolicy, clarification: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "blocks": len(policy.raw_blocks),
        "aliases": len(policy.aliases),
        "protected_terms": len(policy.protected_terms),
        "facets": len(policy.facets),
        "source_family_rules": len(policy.source_family_rules),
        "lexical_document_types": len(policy.lexical_config.document_types),
        "lexical_metadata_fields": len(policy.lexical_config.metadata_field_weights),
        "require_project_code_match": policy.require_project_code_match,
        "clarification_required": bool(clarification and clarification.get("required")),
    }


def _retrieval_policy_payload(
    policy: RetrievalPolicy, clarification: dict[str, Any] | None
) -> dict[str, Any]:
    return {
        **_retrieval_policy_summary(policy, clarification),
        "prompt": policy_prompt(policy, clarification),
    }


def _table_analysis_for_profile(
    request: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    question = str(profile.get("query") or request.get("query") or "")
    workspace_id = profile.get("workspace_id")
    if not workspace_id or not should_run_table_analysis(question):
        return None
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.id == str(workspace_id)).first()
        if not workspace:
            return None
        return TableQueryEngine(db).query(
            workspace=workspace,
            question=question,
            collection_or_scope=profile.get("knowledge_scope") or profile.get("collection"),
            mode="auto",
            system_id=request.get("system_id"),
            include_evidence=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag_context: table analysis failed", error=str(exc))
        return {"warnings": [f"table_analysis_failed: {exc}"], "evidence_rows": []}
    finally:
        db.close()


def _document_analysis_for_profile(
    request: dict[str, Any], profile: dict[str, Any]
) -> dict[str, Any] | None:
    question = str(profile.get("query") or request.get("query") or "")
    workspace_id = profile.get("workspace_id")
    if not workspace_id or not should_run_document_analysis(question):
        return None
    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.id == str(workspace_id)).first()
        if not workspace:
            return None
        return DocumentQueryEngine(db).query(
            workspace=workspace,
            question=question,
            collection_or_scope=profile.get("knowledge_scope") or profile.get("collection"),
            mode="auto",
            system_id=request.get("system_id"),
            include_evidence=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag_context: document analysis failed", error=str(exc))
        return {"warnings": [f"document_analysis_failed: {exc}"], "evidence_rows": []}
    finally:
        db.close()


def _inventory_summary(inventories: list[dict[str, Any]]) -> str:
    total_sources = sum(int(item.get("source_count") or 0) for item in inventories)
    filtered_sources = sum(
        int(item.get("sources_total") or item.get("source_count") or 0) for item in inventories
    )
    total_chunks = sum(int(item.get("chunk_count") or 0) for item in inventories)
    kind_counter: dict[str, int] = {}
    ext_counter: dict[str, int] = {}
    status_counter: dict[str, int] = {}
    for item in inventories:
        for key, value in (item.get("by_kind") or {}).items():
            kind_counter[str(key)] = kind_counter.get(str(key), 0) + int(value or 0)
        for key, value in (item.get("by_extension") or {}).items():
            ext_counter[str(key)] = ext_counter.get(str(key), 0) + int(value or 0)
        for key, value in (item.get("by_status") or {}).items():
            status_counter[str(key)] = status_counter.get(str(key), 0) + int(value or 0)

    def _pairs(payload: dict[str, int]) -> str:
        if not payload:
            return "aucun"
        return ", ".join(
            f"{key}: {value}"
            for key, value in sorted(payload.items(), key=lambda kv: (-kv[1], kv[0]))
        )

    lines = [
        "Inventaire Knowledge collection.",
        f"Total sources: {total_sources}.",
        f"Sources matching system scope: {filtered_sources}.",
        f"Total indexed chunks: {total_chunks}.",
        f"Typologie par source_kind: {_pairs(kind_counter)}.",
        f"Typologie par extension: {_pairs(ext_counter)}.",
        f"Statuts: {_pairs(status_counter)}.",
        "",
        "Collections:",
    ]
    for item in inventories:
        filters = (
            item.get("source_filters") if isinstance(item.get("source_filters"), Mapping) else {}
        )
        active_filters = {
            key: value
            for key, value in dict(filters or {}).items()
            if key not in {"sort", "sort_dir"} and value not in ("", [], None)
        }
        lines.append(
            f"- {item.get('collection_slug')}: {item.get('source_count')} source(s), "
            f"{item.get('chunk_count')} chunk(s), "
            f"{item.get('sources_total', item.get('source_count'))} matching source(s), "
            f"statut {item.get('status') or 'unknown'}."
        )
        if active_filters:
            rendered_filters = ", ".join(f"{key}={value}" for key, value in active_filters.items())
            lines.append(f"  Scope filters: {rendered_filters}.")
        for source in (item.get("sources") or [])[:80]:
            bits = [
                str(source.get("filename") or "source"),
                str(source.get("source_kind") or "document"),
                str(source.get("extension") or "unknown"),
                str(source.get("status") or "unknown"),
                f"{int(source.get('chunk_count') or 0)} chunks",
            ]
            if source.get("size_bytes") is not None:
                bits.append(f"{int(source.get('size_bytes') or 0)} bytes")
            lines.append("  - " + " | ".join(bits))
        if item.get("sources_has_more"):
            remaining = max(
                0, int(item.get("sources_total") or 0) - int(item.get("sources_returned") or 0)
            )
            lines.append(f"  - ... {remaining} source(s) supplementaire(s) matching this scope")
    return "\n".join(lines)


def _inventory_filter_kwargs(filters: Mapping[str, Any] | None) -> dict[str, Any]:
    filters = filters or {}

    def one(key: str) -> Any:
        value = filters.get(key)
        if isinstance(value, (list, tuple, set)):
            return next((item for item in value if str(item or "").strip()), None)
        return value

    kwargs: dict[str, Any] = {}
    for key in ("source_kind", "extension", "status", "project_code", "archive_name", "language"):
        value = one(key)
        if str(value or "").strip():
            kwargs[key] = str(value).strip()
    for key in ("document_id", "document_filename"):
        value = filters.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            cleaned = [str(item).strip() for item in value if str(item or "").strip()]
            if cleaned:
                kwargs[key] = cleaned[:80]
        elif str(value).strip():
            kwargs[key] = str(value).strip()
    return kwargs


def _retrieve_collection_inventory_context(
    profile: dict[str, Any],
    *,
    started: float,
    metrics: dict[str, Any],
) -> dict[str, Any] | None:
    workspace_id = profile.get("workspace_id")
    collections = [str(slug) for slug in (profile.get("collections") or []) if str(slug).strip()]
    if not workspace_id:
        return None
    inventory_started = time.perf_counter()
    db = SessionLocal()
    try:
        query = db.query(KnowledgeCollection).filter(
            KnowledgeCollection.workspace_id == str(workspace_id)
        )
        if collections:
            query = query.filter(KnowledgeCollection.slug.in_(collections))
        rows = query.order_by(KnowledgeCollection.slug.asc()).all()
        inventory_filters = _inventory_filter_kwargs(profile.get("retrieval_filters"))
        inventories = [
            collection_inventory(
                db,
                collection=row,
                include_sources=True,
                source_limit=80,
                sort="chunk_count" if inventory_filters else "filename",
                sort_dir="desc" if inventory_filters else "asc",
                **inventory_filters,
            )
            for row in rows
        ]
    finally:
        db.close()
    summary = _inventory_summary(inventories)
    duration_ms = int((time.time() - started) * 1000)
    total_sources = sum(int(item.get("source_count") or 0) for item in inventories)
    filtered_sources = sum(
        int(item.get("sources_total") or item.get("source_count") or 0) for item in inventories
    )
    total_chunks = sum(int(item.get("chunk_count") or 0) for item in inventories)
    touched = [str(item.get("collection_slug")) for item in inventories]
    metrics.update(
        {
            "duration_ms": duration_ms,
            "inventory_ms": int((time.perf_counter() - inventory_started) * 1000),
            "chunks_retrieved": 1 if inventories else 0,
            "document_chunks_retrieved": 0,
            "raw_chunks_retrieved": 0,
            "inventory_sources": total_sources,
            "inventory_filtered_sources": filtered_sources,
            "inventory_chunks": total_chunks,
            "pipeline": "collection_inventory",
            "mode_label": "collection_inventory",
            "no_context": not inventories,
            "collections_touched": touched,
            "candidate_pool_k": profile.get("candidate_pool_k"),
            "synthesis_k": profile.get("synthesis_k"),
            "source_display_k": profile.get("source_display_k"),
        }
    )
    chunks = [summary] if inventories else []
    scores = [1.0] if inventories else []
    metadatas = (
        [
            {
                "source_type": "collection_inventory",
                "semantic_type": "collection_inventory",
                "title": "Inventaire Knowledge collection",
                "document_filename": "knowledge-collection-inventory",
                "collection": ", ".join(touched),
                "collection_name": ", ".join(touched),
                "citation_label": "Inventaire Knowledge collection",
            }
        ]
        if inventories
        else []
    )
    selected_sources = _selected_source_trace(chunks, scores, metadatas)
    metrics["selected_sources"] = selected_sources
    metrics["retrieval_trace"] = {
        "trace_id": str(uuid4()),
        "planner": {
            "intent": (metrics.get("retrieval_scope") or {}).get("intent")
            if isinstance(metrics.get("retrieval_scope"), Mapping)
            else None,
            "dense": (metrics.get("retrieval_scope") or {}).get("dense")
            if isinstance(metrics.get("retrieval_scope"), Mapping)
            else None,
            "dense_policy": metrics.get("dense_policy"),
        },
        "scope": metrics.get("retrieval_scope"),
        "policy": metrics.get("retrieval_plan"),
        "layers": (metrics.get("retrieval_plan") or {}).get("layers")
        if isinstance(metrics.get("retrieval_plan"), Mapping)
        else {},
        "selected_sources": selected_sources,
        "failures": [metrics.get("fallback_reason")] if metrics.get("fallback_reason") else [],
    }
    _finalize_retrieval_metrics(metrics)
    return _jsonable(
        {
            "chunks": chunks,
            "scores": scores,
            "metadatas": metadatas,
            "pipeline": "collection_inventory",
            "label": profile.get("scope_label") or "Collection inventory",
            "reason": "Inventory/cardinality query answered from KnowledgeCollectionSource ledger",
            "detail": f"{len(touched)} collection(s); {total_sources} source(s); {total_chunks} chunk(s)",
            "mode_label": "collection_inventory",
            "mode_reason": "Source inventory request",
            "use_hybrid": False,
            "top_k": profile["top_k"],
            "candidate_pool_k": profile.get("candidate_pool_k"),
            "synthesis_k": profile.get("synthesis_k"),
            "source_display_k": profile.get("source_display_k"),
            "query": profile["query"],
            "retrieval_query": profile["query"],
            "retrieval_policy": {"enabled": False, "prompt": ""},
            "retrieval_constraints": {},
            "clarification": None,
            "collection": profile["collection"],
            "collections": profile.get("collections") or [],
            "knowledge_scope": profile.get("knowledge_scope"),
            "scope_label": profile.get("scope_label"),
            "vector_db": profile["vector_db"],
            "workspace_slug": profile["workspace_slug"],
            "inventory": {
                "total_sources": total_sources,
                "total_chunks": total_chunks,
                "collections": inventories,
            },
            "metrics": metrics,
            "retrieval_decision_trace": metrics.get("retrieval_decision_trace"),
            "retrieval_scope": metrics.get("retrieval_scope"),
            "retrieval_plan": metrics.get("retrieval_plan"),
            "scope_confidence": metrics.get("scope_confidence"),
            "scope_reason": metrics.get("scope_reason"),
            "dense_policy": metrics.get("dense_policy"),
            "fallback_reason": metrics.get("fallback_reason"),
            "latency_budget": metrics.get("latency_budget"),
            "retrieval_profile": profile.get("retrieval_profile"),
            "retrieval_trace": metrics.get("retrieval_trace"),
            "deep_retrieval_recommended": metrics.get("deep_retrieval_recommended"),
            "collections_touched": touched,
            "collection_errors": [],
        }
    )


def _retrieve_dense_unscoped_coarse_context(
    profile: dict[str, Any],
    *,
    started: float,
    metrics: dict[str, Any],
) -> dict[str, Any] | None:
    context = _retrieve_collection_inventory_context(profile, started=started, metrics=metrics)
    if context is None:
        return None
    inventory = context.get("inventory") or {}
    total_sources = int(inventory.get("total_sources") or metrics.get("inventory_sources") or 0)
    total_chunks = int(inventory.get("total_chunks") or metrics.get("inventory_chunks") or 0)
    profile_name = str(profile.get("latency_profile") or metrics.get("latency_profile") or "fast")
    dense_policy = str(metrics.get("dense_policy") or "dense_unscoped_guardrail")
    is_deep = profile_name == "deep"
    deep_recommended = not is_deep
    guardrail = (
        "Dense corpus retrieval guardrail.\n"
        f"User query: {profile['query']}\n"
        f"The collection has {total_sources} source(s) and {total_chunks} indexed chunk(s). "
        "Retrieval intentionally did not run a global chunk/vector search because no high-confidence "
        "system scope was inferred inside the fast latency budget. Use the inventory below for a coarse answer only. "
        "Bounded hierarchical retrieval may continue asynchronously using facts, summaries, metadata, or offline artifacts."
    )
    chunks = [guardrail, *(context.get("chunks") or [])]
    scores = [1.0, *(context.get("scores") or [])]
    metadatas = [
        {
            "source_type": "dense_coarse_guardrail",
            "semantic_type": "dense_coarse_guardrail",
            "title": "Dense retrieval guardrail",
            "document_filename": "dense-retrieval-guardrail",
            "collection": context.get("collection"),
            "collection_name": context.get("collection"),
            "citation_label": "Dense retrieval guardrail",
        },
        *(context.get("metadatas") or []),
    ]
    metrics.update(
        {
            "pipeline": "dense_coarse_inventory",
            "mode_label": dense_policy,
            "dense_global_search_skipped": True,
            "deep_retrieval_recommended": deep_recommended,
            "fallback": True,
            "fallback_reason": metrics.get("fallback_reason") or "dense_unscoped_fast_policy",
            "chunks_retrieved": len(chunks),
            "no_context": False,
        }
    )
    _finalize_retrieval_metrics(metrics)
    context.update(
        {
            "chunks": chunks,
            "scores": scores,
            "metadatas": metadatas,
            "pipeline": "dense_coarse_inventory",
            "label": "Dense corpus coarse inventory",
            "reason": "Dense request answered from SQL inventory because the fast planner did not infer a precise enough system scope.",
            "detail": (
                "Global chunk retrieval skipped; Deep Retrieval can refine content-level evidence asynchronously."
                if deep_recommended
                else "Global chunk retrieval skipped; summaries, facts, sparse indexes, or diagnostics artifacts must provide the coarse layer."
            ),
            "mode_label": dense_policy,
            "mode_reason": metrics.get("scope_reason") or "Dense corpus guardrail",
            "fallback_reason": metrics.get("fallback_reason"),
            "deep_retrieval_recommended": deep_recommended,
            "metrics": metrics,
            "retrieval_decision_trace": metrics.get("retrieval_decision_trace"),
        }
    )
    return _jsonable(context)


def _prepend_table_analysis_context(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    table_analysis: dict[str, Any] | None,
) -> tuple[list[str], list[float], list[dict[str, Any]], int]:
    if not table_analysis:
        return chunks, scores, metadatas, 0
    evidence = table_analysis.get("evidence_rows") or []
    if not evidence:
        return chunks, scores, metadatas, 0
    evidence_chunks: list[str] = []
    evidence_scores: list[float] = []
    evidence_metas: list[dict[str, Any]] = []
    for index, row in enumerate(evidence[:8], start=1):
        if not isinstance(row, Mapping):
            continue
        value = row.get("value_raw")
        unit = f" {row.get('unit')}" if row.get("unit") else ""
        label = row.get("measure") or row.get("row_label") or row.get("column_header") or "value"
        content = (
            "Table analysis evidence: "
            f"{label} = {value}{unit}; "
            f'file="{row.get("document_filename")}", '
            f'sheet="{row.get("sheet_name")}", cell="{row.get("cell_ref")}". '
            f"{row.get('content') or ''}"
        )
        evidence_chunks.append(content)
        evidence_scores.append(1.2 - (index * 0.01))
        evidence_metas.append(
            {
                "source_type": "table_analysis",
                "semantic_type": "table_analysis_evidence",
                "collection": row.get("collection_slug"),
                "collection_name": row.get("collection_slug"),
                "document_id": row.get("document_id"),
                "document_filename": row.get("document_filename"),
                "sheet_name": row.get("sheet_name"),
                "cell_ref": row.get("cell_ref"),
                "cell_range": row.get("cell_range"),
                "row_label": row.get("row_label"),
                "column_header": row.get("column_header"),
                "value_raw": row.get("value_raw"),
                "value_numeric": row.get("value_numeric"),
                "unit": row.get("unit"),
                "citation_label": f"{row.get('document_filename') or 'table'} · {row.get('sheet_name') or 'sheet'} · {row.get('cell_ref') or 'cell'}",
            }
        )
    return (
        evidence_chunks + chunks,
        evidence_scores + scores,
        evidence_metas + metadatas,
        len(evidence_chunks),
    )


def _prepend_document_analysis_context(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    document_analysis: dict[str, Any] | None,
) -> tuple[list[str], list[float], list[dict[str, Any]], int]:
    if not document_analysis:
        return chunks, scores, metadatas, 0
    evidence = document_analysis.get("evidence_rows") or []
    if not evidence:
        return chunks, scores, metadatas, 0
    evidence_chunks: list[str] = []
    evidence_scores: list[float] = []
    evidence_metas: list[dict[str, Any]] = []
    for index, row in enumerate(evidence[:8], start=1):
        if not isinstance(row, Mapping):
            continue
        locator = []
        if row.get("page"):
            locator.append(f"page {row.get('page')}")
        if row.get("section_path"):
            locator.append(str(row.get("section_path")))
        content = (
            "Document analysis evidence: "
            f"{row.get('semantic_type') or 'fact'}; "
            f'file="{row.get("document_filename")}", '
            f'locator="{", ".join(locator) or "document"}". '
            f"{row.get('content') or row.get('value_raw') or ''}"
        )
        evidence_chunks.append(content)
        evidence_scores.append(1.15 - (index * 0.01))
        evidence_metas.append(
            {
                "source_type": "document_analysis",
                "semantic_type": "document_analysis_evidence",
                "collection": row.get("collection_slug"),
                "collection_name": row.get("collection_slug"),
                "document_id": row.get("document_id"),
                "document_filename": row.get("document_filename"),
                "document_type": row.get("document_type"),
                "page": row.get("page"),
                "section_path": row.get("section_path"),
                "paragraph_index": row.get("paragraph_index"),
                "subject": row.get("subject"),
                "predicate": row.get("predicate"),
                "value_raw": row.get("value_raw"),
                "unit": row.get("unit"),
                "citation_label": f"{row.get('document_filename') or 'document'} · {', '.join(locator) or 'source'}",
            }
        )
    return (
        evidence_chunks + chunks,
        evidence_scores + scores,
        evidence_metas + metadatas,
        len(evidence_chunks),
    )


def _summary_artifact_for_profile(
    profile: dict[str, Any],
    *,
    metrics: dict[str, Any],
    query: str,
) -> dict[str, Any] | None:
    plan = (
        metrics.get("retrieval_plan") if isinstance(metrics.get("retrieval_plan"), Mapping) else {}
    )
    layers = plan.get("layers") if isinstance(plan.get("layers"), Mapping) else {}
    summaries_layer = (
        layers.get("summaries") if isinstance(layers.get("summaries"), Mapping) else {}
    )
    if summaries_layer.get("enabled") is not True:
        return None
    workspace_id = str(profile.get("workspace_id") or "")
    collection_ref = str(profile.get("collection") or "")
    if not workspace_id or not collection_ref:
        return None
    db = SessionLocal()
    try:
        collection = (
            db.query(KnowledgeCollection)
            .filter(
                (
                    (KnowledgeCollection.slug == collection_ref)
                    | (KnowledgeCollection.id == collection_ref)
                ),
                KnowledgeCollection.workspace_id == workspace_id,
            )
            .first()
        )
        if not collection:
            return None
        if profile.get("authoritative_document_scope") is True:
            filters = _authoritative_filters_for_collection(
                profile,
                collection_ref,
                profile.get("retrieval_filters")
                if isinstance(profile.get("retrieval_filters"), Mapping)
                else {},
            )
            if filters is None:
                return None
        else:
            scope = (
                metrics.get("retrieval_scope")
                if isinstance(metrics.get("retrieval_scope"), Mapping)
                else {}
            )
            filters = scope.get("filters") if isinstance(scope.get("filters"), Mapping) else {}
        allowed_filters = {
            key: value
            for key, value in dict(filters or {}).items()
            if key
            in {
                "collection",
                "collection_slug",
                "document_id",
                "document_filename",
                "source_kind",
                "extension",
                "project_code",
                "archive_name",
                "status",
                "language",
            }
        }
        return load_summary_index_records(
            collection=collection,
            query=query,
            filters=allowed_filters,
            limit=4,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag_context: summary artifact load failed", error=str(exc))
        return {"status": "error", "reason": str(exc), "records": []}
    finally:
        db.close()


def _prepend_summary_artifact_context(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    summary_artifact: dict[str, Any] | None,
) -> tuple[list[str], list[float], list[dict[str, Any]], int]:
    if not summary_artifact:
        return chunks, scores, metadatas, 0
    records = summary_artifact.get("records") or []
    if not records:
        return chunks, scores, metadatas, 0
    evidence_chunks: list[str] = []
    evidence_scores: list[float] = []
    evidence_metas: list[dict[str, Any]] = []
    for index, record in enumerate(records[:4], start=1):
        if not isinstance(record, Mapping):
            continue
        summary_text = str(record.get("summary_text") or "").strip()
        if not summary_text:
            continue
        evidence_chunks.append(f"Document summary artifact: {summary_text}")
        evidence_scores.append(1.08 - (index * 0.01))
        evidence_metas.append(
            {
                "source_type": "summary_artifact",
                "semantic_type": "document_summary_artifact",
                "collection": record.get("collection_slug"),
                "collection_name": record.get("collection_slug"),
                "document_id": record.get("document_id"),
                "document_filename": record.get("document_filename"),
                "source_kind": record.get("source_kind"),
                "extension": record.get("extension"),
                "project_code": record.get("project_code"),
                "archive_name": record.get("archive_name"),
                "chunk_count": record.get("chunk_count"),
                "fact_count": record.get("fact_count"),
                "citation_label": f"{record.get('document_filename') or 'document'} · summary",
            }
        )
    return (
        evidence_chunks + chunks,
        evidence_scores + scores,
        evidence_metas + metadatas,
        len(evidence_chunks),
    )


def build_document_service(request: dict[str, Any]):
    """Create a request-scoped DocumentService for worker-side retrieval."""
    from app.services.rag.document_service import DocumentService

    profile = get_retrieval_profile(request)
    return DocumentService(
        collection_name=profile["collection"],
        vector_db_type=profile["vector_db"],
        workspace_slug=profile["workspace_slug"],
    )


def _document_service_for_profile(profile: dict[str, Any], collection: str):
    from app.services.rag.document_service import DocumentService

    return DocumentService(
        collection_name=collection,
        vector_db_type=profile["vector_db"],
        workspace_slug=profile["workspace_slug"],
    )


def _chunk_exact_key(chunk: Any) -> str:
    text = " ".join(str(chunk or "").split()).lower()
    return sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _source_identity(meta: Mapping[str, Any]) -> str:
    for key in (
        "document_id",
        "source_path",
        "object_key",
        "document_filename",
        "filename",
        "path",
        "url",
    ):
        value = meta.get(key)
        if value:
            return str(value)
    return ""


def _selected_source_trace(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """Compact, serialisable source trace for replay/evaluation."""
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, meta in enumerate(metadatas[: max(0, limit * 2)]):
        if not isinstance(meta, Mapping):
            continue
        identity = _source_identity(meta)
        if not identity or identity in seen:
            continue
        seen.add(identity)
        snippet = " ".join(str(chunks[index] if index < len(chunks) else "").split())[:240]
        try:
            score = float(scores[index]) if index < len(scores) else None
        except (TypeError, ValueError):
            score = None
        selected.append(
            {
                "rank": len(selected) + 1,
                "source": identity,
                "document_id": meta.get("document_id"),
                "document_filename": meta.get("document_filename") or meta.get("filename"),
                "source_family": meta.get("source_family"),
                "project_code": meta.get("project_code"),
                "score": score,
                "snippet": snippet,
            }
        )
        if len(selected) >= limit:
            break
    return selected


def _spreadsheet_near_key(chunk: Any, meta: Mapping[str, Any]) -> str | None:
    """Return a cautious near-duplicate key for repeated spreadsheet boilerplate.

    Excel workbooks often contain several operational sheets with identical
    header/setup rows. Those rows are useful once, but noisy when the chat UI
    shows them as separate sources. We only ignore the sheet name when the hit
    clearly comes from the same source document, so repeated evidence across
    different files remains visible.
    """
    text = " ".join(str(chunk or "").split()).lower()
    if "spreadsheet sheet:" not in text:
        return None
    source = _source_identity(meta)
    if not source:
        return None
    normalized = _SPREADSHEET_SHEET_PREFIX_RE.sub("spreadsheet sheet:", text)
    if normalized == text:
        return None
    return sha1(f"{source}|{normalized}".encode("utf-8", errors="ignore")).hexdigest()


def _dedupe_aligned_results(
    chunks: list[Any],
    scores: list[Any] | None,
    metadatas: list[Any] | None,
) -> tuple[list[str], list[float], list[dict[str, Any]], int]:
    """Collapse duplicate retrieval chunks while preserving list alignment."""
    deduped_chunks: list[str] = []
    deduped_scores: list[float] = []
    deduped_metadatas: list[dict[str, Any]] = []
    seen: set[str] = set()
    removed = 0

    scores = scores or []
    metadatas = metadatas or []
    for index, chunk in enumerate(chunks or []):
        text = str(chunk or "")
        if not text.strip():
            continue
        meta = (
            dict(metadatas[index])
            if index < len(metadatas) and isinstance(metadatas[index], Mapping)
            else {}
        )
        keys = [f"exact:{_chunk_exact_key(text)}"]
        near_key = _spreadsheet_near_key(text, meta)
        if near_key:
            keys.append(f"spreadsheet:{near_key}")
        if any(key in seen for key in keys):
            removed += 1
            continue
        seen.update(keys)
        deduped_chunks.append(text)
        try:
            score = float(scores[index]) if index < len(scores) else 0.0
        except (TypeError, ValueError):
            score = 0.0
        deduped_scores.append(score)
        deduped_metadatas.append(meta)

    return deduped_chunks, deduped_scores, deduped_metadatas, removed


def _recall_floor_active(
    profile: Mapping[str, Any],
    collection: Any,
    retrieval_filters: Mapping[str, Any] | None,
) -> bool:
    """Whether the bounded unscoped recall-floor pass should run for ``collection``.

    Armed by the planner only when a hard ``document_filename`` allowlist is in
    effect on a large collection (see CorpusPlan.recall_floor_*). It requires the
    hard filter to actually be present (so it never broadens an unscoped query)
    and ``collection`` to be one the planner flagged; a no-op otherwise.
    """
    if profile.get("authoritative_document_scope") is True:
        return False
    recall_floor_collections = profile.get("_corpus_plan_recall_floor_collections") or []
    if not recall_floor_collections:
        return False
    if str(collection) not in {str(ref) for ref in recall_floor_collections}:
        return False
    return bool((retrieval_filters or {}).get("document_filename"))


async def _retrieve_recall_floor_pass(
    doc_svc: Any,
    *,
    retrieval_query: str,
    top_n: int,
    retrieval_policy: "RetrievalPolicy",
    deadline_seconds: float,
    max_candidates: int,
    retrieval_profile: str | None,
    latency_profile: str | None,
) -> Any:
    """Run one bounded UNSCOPED dense recall-floor pass over a scoped collection.

    Dense-only by design: the answer chunk the filename allowlist missed is, by
    construction, a high-similarity dense hit, and a pure vector (HNSW) search is
    sub-second on any corpus size, whereas an unscoped sparse/global search on a
    large collection is exactly what the dense guardrail forbids. Forcing dense
    keeps the floor fast and deterministic so the unioned candidate still ranks
    high even when the rerank cross-encoder later times out.

    The floor embeds the RAW user query with NO guide-hint suffix on purpose.
    Guide hints steer the primary scoped pass toward the workspace corpus, but
    appended to a terse question they shift the embedding enough to push the
    missed answer doc out of the unscoped top-N - exactly the chunk the floor
    exists to recover. A pure raw-query vector match is what ranks it #1.
    """
    bounded_top_n = max(1, int(top_n or 0) or 10)
    return await retrieve_for_mode(
        doc_svc,
        retrieval_query,
        "naive",
        top_k=bounded_top_n,
        use_hybrid=False,
        hah_chah_enabled=False,
        query_hints="",
        retrieval_policy=retrieval_policy,
        filters=None,
        deadline_seconds=deadline_seconds,
        max_variants=1,
        max_candidates=max_candidates,
        allow_legacy_hybrid=False,
        retrieval_profile=retrieval_profile,
        latency_profile=latency_profile,
    )


def _union_recall_floor(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    floor_result: Any,
) -> tuple[list[str], list[float], list[dict[str, Any]], int]:
    """Append recall-floor candidates not already in the pool, marking provenance.

    Duplicates (content the scoped pass already retrieved) are skipped, so the
    floor only ever ADDS documents the hard filter missed. Final ordering is left
    to the existing rerank/fusion pipeline; the floor chunk carries its own dense
    score so it survives even when the cross-encoder is skipped.
    """
    seen = {_chunk_exact_key(str(chunk or "")) for chunk in chunks}
    floor_chunks = list(getattr(floor_result, "chunks", []) or [])
    floor_scores = list(getattr(floor_result, "scores", []) or [])
    floor_metas = list(getattr(floor_result, "metadatas", []) or [])
    added = 0
    for index, chunk in enumerate(floor_chunks):
        text = str(chunk or "")
        if not text.strip():
            continue
        key = _chunk_exact_key(text)
        if key in seen:
            continue
        seen.add(key)
        meta = (
            dict(floor_metas[index])
            if index < len(floor_metas) and isinstance(floor_metas[index], Mapping)
            else {}
        )
        meta["recall_floor"] = True
        chunks.append(text)
        scores.append(float(floor_scores[index]) if index < len(floor_scores) else 0.0)
        metadatas.append(meta)
        added += 1
    return chunks, scores, metadatas, added


def _document_diversity_key(metadata: Mapping[str, Any], index: int) -> str:
    for key in (
        "document_id",
        "source_id",
        "document_filename",
        "filename",
        "source_path",
        "object_key",
    ):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return f"_chunk_{index}"


def _compress_final_context(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    synthesis_k: int,
    cross_encoder_status: str | None,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    """Quality-conditional trim to the synthesis budget (RAGGER Eq. 13).

    The paper keeps the top ``ratio`` of the reranked pool. Transposed here as
    compression-only (never expansion — the pool is larger than synthesis_k):
    when the cross-encoder ran, the low-quality tail below
    ``rag_compression_score_floor`` is cut, bounded between
    ``ceil(synthesis_k * ratio)`` and ``synthesis_k``. Without CE scores the
    historical fixed trim applies. Exempt evidence never counts nor gets cut.
    """
    synthesis_k = max(1, int(synthesis_k or 1))

    def _fixed_trim() -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
        kept = min(len(chunks), synthesis_k)
        return (
            chunks[:synthesis_k],
            scores[:synthesis_k],
            metadatas[:synthesis_k],
            {
                "compression_status": "fixed_trim",
                "compression_kept": kept,
                "compression_dropped": max(0, len(chunks) - kept),
            },
        )

    if not settings.rag_compression_enabled or cross_encoder_status != "applied":
        return _fixed_trim()

    ratio = max(0.1, min(1.0, float(settings.rag_compression_ratio)))
    score_floor = max(0.0, min(1.0, float(settings.rag_compression_score_floor)))
    min_keep = max(1, math.ceil(synthesis_k * ratio))

    qualified = 0
    for metadata in metadatas:
        if _is_threshold_exempt_metadata(metadata or {}):
            continue
        raw = (metadata or {}).get("cross_encoder_score")
        try:
            if raw is not None and float(raw) >= score_floor:
                qualified += 1
        except (TypeError, ValueError):
            continue
    target = min(synthesis_k, max(min_keep, qualified))

    kept_chunks: list[str] = []
    kept_scores: list[float] = []
    kept_metadatas: list[dict[str, Any]] = []
    kept_scored = 0
    for index, chunk in enumerate(chunks):
        metadata = metadatas[index] if index < len(metadatas) else {}
        if _is_threshold_exempt_metadata(metadata or {}):
            kept_chunks.append(chunk)
            kept_scores.append(scores[index] if index < len(scores) else 0.0)
            kept_metadatas.append(metadata)
            continue
        if kept_scored < target:
            kept_chunks.append(chunk)
            kept_scores.append(scores[index] if index < len(scores) else 0.0)
            kept_metadatas.append(metadata)
            kept_scored += 1
    return (
        kept_chunks,
        kept_scores,
        kept_metadatas,
        {
            "compression_status": "proportional",
            "compression_kept": len(kept_chunks),
            "compression_dropped": len(chunks) - len(kept_chunks),
            "compression_ratio_effective": round(len(kept_chunks) / max(1, len(chunks)), 3),
            "compression_score_floor": score_floor,
        },
    )


async def _diversify_final_context(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    query: str,
    latency_profile: str | None,
    limit: int,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    """Embedding-aware MMR when enabled/applicable, round-robin otherwise."""
    from app.services.rag.mmr_stage import diversify_with_mmr

    chunks, scores, metadatas, mmr_diag = await diversify_with_mmr(
        chunks,
        scores,
        metadatas,
        query=query,
        latency_profile=latency_profile,
        limit=limit,
        is_exempt_metadata=_is_threshold_exempt_metadata,
    )
    if mmr_diag.get("mmr_status") == "applied":
        return chunks, scores, metadatas, mmr_diag
    chunks, scores, metadatas, diversity_diag = _diversify_aligned_by_document(
        chunks,
        scores,
        metadatas,
        limit=limit,
    )
    return chunks, scores, metadatas, {**diversity_diag, **mmr_diag}


def _diversify_aligned_by_document(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    limit: int,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    target = min(max(0, int(limit or 0)), len(chunks))
    if target <= 1:
        return (
            chunks,
            scores,
            metadatas,
            {
                "document_diversity_applied": False,
                "document_diversity_groups": len(chunks),
                "document_diversity_limit": target,
            },
        )

    buckets: OrderedDict[str, list[int]] = OrderedDict()
    for index, metadata in enumerate(metadatas):
        buckets.setdefault(_document_diversity_key(metadata or {}, index), []).append(index)
    if len(buckets) <= 1:
        return (
            chunks,
            scores,
            metadatas,
            {
                "document_diversity_applied": False,
                "document_diversity_groups": len(buckets),
                "document_diversity_limit": target,
            },
        )

    selected: list[int] = []
    keys = list(buckets)
    while len(selected) < target and keys:
        next_keys: list[str] = []
        for key in keys:
            queue = buckets.get(key) or []
            if not queue:
                continue
            selected.append(queue.pop(0))
            if queue:
                next_keys.append(key)
            if len(selected) >= target:
                break
        keys = next_keys
    selected_set = set(selected)
    reordered_indices = [
        *selected,
        *[index for index in range(len(chunks)) if index not in selected_set],
    ]
    changed = reordered_indices[:target] != list(range(target))
    return (
        [chunks[index] for index in reordered_indices],
        [scores[index] if index < len(scores) else 0.0 for index in reordered_indices],
        [metadatas[index] if index < len(metadatas) else {} for index in reordered_indices],
        {
            "document_diversity_applied": changed,
            "document_diversity_groups": len(buckets),
            "document_diversity_limit": target,
        },
    )


def retrieval_event(
    phase: str,
    *,
    details: dict[str, Any] | None = None,
    message: str | None = None,
    rag_context: dict[str, Any] | None = None,
    recoverable: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chunk_type": "retrieval",
        "phase": phase,
        "content": "",
        "message": message or phase.replace("_", " ").title(),
        "details": details or {},
        "recoverable": recoverable,
        "is_final": False,
    }
    if rag_context is not None:
        payload["rag_context"] = rag_context
    return payload


def _retrieval_context_cache_key(
    *,
    profile: dict[str, Any],
    query: str,
    retrieval_filters: dict[str, Any],
    metrics: dict[str, Any],
    guides: list[Any],
    retrieval_policy: RetrievalPolicy | None = None,
) -> str | None:
    if not settings.rag_context_cache_enabled:
        return None
    if profile.get("latency_profile") == "deep" or profile.get("deep_retrieval"):
        return None
    scope = (
        metrics.get("retrieval_scope")
        if isinstance(metrics.get("retrieval_scope"), Mapping)
        else {}
    )
    corpus_version = str(scope.get("corpus_version") or "").strip()
    if not corpus_version or corpus_version == "unknown":
        metrics["retrieval_context_cache_hit"] = False
        metrics["retrieval_context_cache_skipped_reason"] = "corpus_version_unknown"
        return None
    key_payload = {
        "workspace_id": profile.get("workspace_id"),
        "workspace_slug": profile.get("workspace_slug"),
        "collection": profile.get("collection"),
        "collections": profile.get("collections") or [],
        "knowledge_scope": profile.get("knowledge_scope"),
        "authoritative_document_scope": profile.get("authoritative_document_scope") is True,
        "authoritative_document_refs": profile.get("authoritative_document_refs") or {},
        "authoritative_document_refs_provided": (
            profile.get("authoritative_document_refs_provided") is True
        ),
        # Cached evidence has already crossed this membrane. Its policy and
        # expected project therefore belong to the cache authority boundary.
        "membrane_spec": profile.get("_membrane_spec") or {},
        "membrane_expected_project": profile.get("_membrane_expected_project"),
        "source_policy_retrieval_boundary": {
            "require_project_code_match": bool(
                retrieval_policy and retrieval_policy.require_project_code_match
            ),
            "cross_project_log_only": bool(
                retrieval_policy and retrieval_policy.cross_project_log_only
            ),
        },
        "query": query,
        "rag_mode": profile.get("rag_mode"),
        "latency_profile": profile.get("latency_profile"),
        "filters": retrieval_filters,
        "top_k": profile.get("top_k"),
        "candidate_pool_k": profile.get("candidate_pool_k"),
        "synthesis_k": profile.get("synthesis_k"),
        "source_display_k": profile.get("source_display_k"),
        "dense_policy": metrics.get("dense_policy"),
        "corpus_version": corpus_version,
        "guides": [
            {
                "id": getattr(guide, "id", None)
                or (guide.get("id") if isinstance(guide, Mapping) else None),
                "version": getattr(guide, "version", None)
                or (guide.get("version") if isinstance(guide, Mapping) else None),
            }
            for guide in guides
        ],
    }
    try:
        raw = json.dumps(key_payload, sort_keys=True, default=str)
    except TypeError:
        raw = str(key_payload)
    return sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _get_cached_retrieval_context(
    cache_key: str | None, *, started: float
) -> dict[str, Any] | None:
    if not cache_key:
        return None
    cached = _RETRIEVAL_CONTEXT_CACHE.get(cache_key)
    if not cached:
        return None
    created_at, payload = cached
    ttl = max(int(settings.rag_context_cache_ttl_seconds), 1)
    if time.time() - created_at > ttl:
        _RETRIEVAL_CONTEXT_CACHE.pop(cache_key, None)
        return None
    _RETRIEVAL_CONTEXT_CACHE.move_to_end(cache_key)
    result = copy.deepcopy(payload)
    metrics = result.setdefault("metrics", {})
    if isinstance(metrics, dict):
        metrics["retrieval_context_cache_hit"] = True
        metrics["duration_ms"] = int((time.time() - started) * 1000)
    return result


def _set_cached_retrieval_context(cache_key: str | None, payload: dict[str, Any]) -> None:
    if not cache_key:
        return
    live_metrics = payload.setdefault("metrics", {})
    if isinstance(live_metrics, dict):
        live_metrics["retrieval_context_cache_hit"] = False
    copy_payload = copy.deepcopy(payload)
    metrics = copy_payload.setdefault("metrics", {})
    if isinstance(metrics, dict):
        metrics["retrieval_context_cache_hit"] = False
    _RETRIEVAL_CONTEXT_CACHE[cache_key] = (time.time(), copy_payload)
    _RETRIEVAL_CONTEXT_CACHE.move_to_end(cache_key)
    max_entries = max(int(settings.rag_context_cache_max_entries), 1)
    while len(_RETRIEVAL_CONTEXT_CACHE) > max_entries:
        _RETRIEVAL_CONTEXT_CACHE.popitem(last=False)


def _should_build_project_inventory(request: dict[str, Any], query: str) -> bool:
    """True for a transversal_inventory question that enumerates projects.

    The answer-profile decision (set on the request before retrieval) marks
    cross-project inventory questions; we additionally require the question to be
    about *projects* so an equipment-only inventory stays on the regular path.
    """
    decision = request.get("answer_profile_decision")
    is_transversal = str(request.get("answer_profile") or "") == "transversal_inventory"
    if not is_transversal and isinstance(decision, Mapping):
        is_transversal = str(decision.get("profile") or "") == "transversal_inventory" or bool(
            decision.get("requires_exhaustive_retrieval")
        )
    return bool(is_transversal and query_targets_projects(query))


def _single_project_inventory_evidence_spec(
    query: str,
    retrieval_filters: Mapping[str, Any] | None,
    retrieval_policy: RetrievalPolicy | None,
) -> dict[str, Any] | None:
    """Describe the tightly scoped lexical lane for equipment inventories.

    The corpus planner remains the owner of scope.  This helper only arms when
    its exact single ``project_code`` filter agrees with the single code written
    in the question, so the additive lane can never broaden tenant/project
    access. Vocabulary comes from the generic source facets. Project-triggered
    guide aliases are deliberately excluded from this additive coverage lane:
    they bias a broad equipment inventory toward a few named suppliers/models.
    The canonical retrieval remains fully policy-aware; no project,
    manufacturer or model is embedded in application code here.
    """
    from app.services.rag.single_project_inventory_intent import (
        parse_single_project_inventory_intent,
    )

    text = str(query or "").strip()
    intent = parse_single_project_inventory_intent(text)
    # The vocabulary-agnostic parser already rejects non-enumeration task
    # shapes. Re-applying the broad legacy exclusion regex to the whole query
    # would incorrectly suppress valid material categories such as "safety
    # valves", "repair kits" or "diagnostic modules".
    if intent is None:
        return None

    query_codes = [intent.project_code]
    active_filters = {
        str(key): value
        for key, value in (retrieval_filters or {}).items()
        if value not in (None, "", [], (), {})
    }
    # This additive lane deliberately relaxes no hard constraint.  Planner
    # filename heuristics are handled by the existing recall-floor machinery;
    # an inventory with any additional filter stays on the canonical pipeline.
    if set(active_filters) != {"project_code"}:
        return None
    raw_filter_codes = active_filters.get("project_code")
    if isinstance(raw_filter_codes, str):
        filter_codes = [raw_filter_codes.strip().upper()]
    elif isinstance(raw_filter_codes, (list, tuple, set)):
        filter_codes = [str(item).strip().upper() for item in raw_filter_codes if str(item).strip()]
    else:
        filter_codes = []
    filter_codes = list(dict.fromkeys(filter_codes))
    if len(query_codes) != 1 or filter_codes != query_codes:
        return None

    terms: list[str] = []
    seen_terms: set[str] = set()

    def add(value: Any) -> None:
        cleaned = " ".join(str(value or "").strip().split())
        if not cleaned or len(cleaned) < 3 or len(cleaned) > 80:
            return
        if cleaned.upper() == query_codes[0]:
            return
        folded = cleaned.lower()
        if folded not in seen_terms:
            seen_terms.add(folded)
            terms.append(cleaned)

    add(intent.category)
    # Expand only the equipment noun and only through generic facets. A guide
    # may map a project code or equipment noun to preferred suppliers; importing
    # those aliases here hides the other equipment families in the same dossier.
    for term in expanded_terms_for_query(intent.category, None):
        add(term)
        if len(terms) >= 12:
            break
    if not terms:
        return None
    return {"project_code": query_codes[0], "terms": terms[:12]}


async def _retrieve_single_project_inventory_evidence(
    doc_svc: Any,
    spec: Mapping[str, Any] | None,
    *,
    timeout_seconds: float = 1.5,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch bounded Qdrant lexical evidence without a second deep retrieval."""
    if not spec:
        return [], {"status": "not_armed"}
    vector_db = getattr(doc_svc, "vector_db", None)
    searcher = getattr(vector_db, "search_inventory_evidence", None)
    if not callable(searcher):
        return [], {"status": "unsupported"}
    started = time.perf_counter()
    try:
        rows = await asyncio.wait_for(
            searcher(
                project_code=str(spec.get("project_code") or ""),
                content_terms=list(spec.get("terms") or []),
                limit=12,
            ),
            timeout=max(0.1, float(timeout_seconds)),
        )
    except (TimeoutError, asyncio.TimeoutError):
        return [], {
            "status": "timeout",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - additive evidence must fail soft.
        logger.warning("rag_context: inventory evidence lane failed", error=str(exc))
        return [], {
            "status": "error",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    valid = [dict(row) for row in (rows or []) if isinstance(row, Mapping)]
    return valid, {
        "status": "ready" if valid else "empty",
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "candidates": len(valid),
        "project_code": spec.get("project_code"),
        "terms": list(spec.get("terms") or []),
    }


def _ensure_inventory_evidence_coverage(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    *,
    synthesis_k: int,
    collection: str,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    """Keep bounded project evidence after CE/compression evicts useful lists."""
    if not evidence_rows:
        return (
            chunks,
            scores,
            metadatas,
            {
                "admission_cap": 0,
                "inserted": 0,
                "replaced": 0,
            },
        )

    limit = max(1, int(synthesis_k or 1))
    # An explicit inventory benefits more from documentary family coverage than
    # from another near-duplicate semantic hit. Reserve up to two fifths of the
    # canonical synthesis budget (hard-capped at eight); the answer wrapper
    # separately bounds the final prompt after guides/guardrails are appended.
    evidence_cap = min(len(evidence_rows), max(2, min(8, (limit * 2 + 4) // 5)))

    def safe_score(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    original = [
        (str(chunk), safe_score(score), dict(metadata or {}))
        for chunk, score, metadata in zip(
            chunks[:limit],
            scores[:limit],
            metadatas[:limit],
            strict=False,
        )
    ]
    original_keys = {_chunk_exact_key(content) for content, _score, _metadata in original}

    # Qdrant deliberately returns one family per functional category before a
    # second family from the same category. For synthesis, keep authoritative
    # spare-parts evidence first and reserve one sibling-family slot when a
    # lower-ranked family lives in a category already represented by equipment
    # explicitly attested in the spare list. This generic bridge protects a
    # distinct supplier family from being hidden by several higher-scoring
    # manuals for already-listed model variants. Remaining rows use score order.
    spare_rows = [
        row
        for row in evidence_rows
        if str((row.get("metadata") or {}).get("source_family") or "").lower() == "spare_parts_list"
    ]
    other_rows = [row for row in evidence_rows if row not in spare_rows]
    attested_categories = {
        str((row.get("metadata") or {}).get("inventory_functional_category") or "")
        for row in other_rows
        if bool((row.get("metadata") or {}).get("inventory_family_attested_by_spare"))
    }
    attested_categories.discard("")
    sibling_family_rows = [
        row
        for row in other_rows
        if not bool((row.get("metadata") or {}).get("inventory_family_attested_by_spare"))
        and str((row.get("metadata") or {}).get("inventory_functional_category") or "")
        in attested_categories
    ]
    sibling_family_rows.sort(key=lambda row: safe_score(row.get("score")), reverse=True)
    reserved_sibling_rows = sibling_family_rows[:1]
    reserved_ids = {id(row) for row in reserved_sibling_rows}
    ordered_rows = [
        *spare_rows,
        *reserved_sibling_rows,
        *sorted(
            (row for row in other_rows if id(row) not in reserved_ids),
            key=lambda row: safe_score(row.get("score")),
            reverse=True,
        ),
    ]

    evidence: list[tuple[str, float, dict[str, Any]]] = []
    evidence_keys: set[str] = set()
    for row in ordered_rows:
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        key = _chunk_exact_key(content)
        if key in evidence_keys:
            continue
        metadata = dict(row.get("metadata") or {})
        metadata["inventory_evidence"] = True
        metadata.setdefault("collection", collection)
        metadata.setdefault("collection_name", collection)
        score = min(max(safe_score(row.get("score"), 0.35), 0.01), 1.0)
        evidence.append((content, score, metadata))
        evidence_keys.add(key)
        if len(evidence) >= evidence_cap:
            break

    # Evidence is intentionally placed first: inventory completeness must not
    # depend on an LLM attending to a spare-parts list buried after a dozen
    # semantic passages. Threshold-exempt context is never evicted.
    protected_original = [item for item in original if _is_threshold_exempt_metadata(item[2])]
    regular_original = [item for item in original if not _is_threshold_exempt_metadata(item[2])]
    evidence = evidence[: max(0, limit - len(protected_original))]
    evidence_keys = {_chunk_exact_key(content) for content, _score, _metadata in evidence}
    combined: list[tuple[str, float, dict[str, Any]]] = list(evidence)
    seen = set(evidence_keys)
    for item in [*protected_original, *regular_original]:
        key = _chunk_exact_key(item[0])
        if key in seen:
            continue
        combined.append(item)
        seen.add(key)
        if len(combined) >= limit:
            break

    admitted_new = sum(
        1
        for content, _score, _metadata in evidence
        if _chunk_exact_key(content) not in original_keys
    )
    free_slots = max(0, limit - len(original))
    inserted = min(admitted_new, free_slots)
    replaced = max(0, admitted_new - inserted)
    out_chunks = [content for content, _score, _metadata in combined[:limit]]
    out_scores = [score for _content, score, _metadata in combined[:limit]]
    out_metas = [metadata for _content, _score, metadata in combined[:limit]]

    return (
        out_chunks,
        out_scores,
        out_metas,
        {
            "admission_cap": evidence_cap,
            "inserted": inserted,
            "replaced": replaced,
        },
    )


def _safe_build_project_inventory(profile: dict[str, Any], query: str) -> dict[str, Any] | None:
    """Wrap the facet aggregation so a Qdrant error never breaks the answer."""
    try:
        return build_project_inventory(profile, query)
    except Exception as exc:  # noqa: BLE001 - inventory is best-effort.
        logger.warning("rag_context: project inventory build failed", error=str(exc))
        return None


async def retrieve_rag_context(
    request: dict[str, Any],
    *,
    doc_svc: Any | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    """Run retrieval and attach request-local embedding provider evidence."""

    from app.services.embedding.embedder import capture_embedding_provider_usage
    from app.services.evaluation.judge import provider_usage_evidence

    with capture_embedding_provider_usage() as embedding_usage:
        result = await _retrieve_rag_context(
            request,
            doc_svc=doc_svc,
            fallback_reason=fallback_reason,
        )
    if not isinstance(result, dict):
        return result
    metrics = result.setdefault("metrics", {})
    if isinstance(metrics, dict):
        calls = embedding_usage.get("calls") or []
        # This marker proves that every canonical Embedder attempt in this
        # retrieval was observed.  Zero calls is therefore a real non-token
        # execution (for example an inner DocumentService cache hit), not an
        # inferred zero from the configured provider name.
        metrics["embedding_provider_usage_scope"] = "canonical_request_v1"
        metrics["embedding_provider_calls"] = len(calls)
        # The scope contains one row per real OpenAI attempt, including failed
        # oversized batches and fallback retries.  ``provider_usage_evidence``
        # emits a metering ``usage`` only when every attempt reported counters.
        if calls:
            metrics.update(provider_usage_evidence(embedding_usage))
    return result


async def _retrieve_rag_context(
    request: dict[str, Any],
    *,
    doc_svc: Any | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    """Run retrieval only and return a stable, serialisable context payload."""
    started = time.time()
    profile = get_retrieval_profile(request)
    requested_authoritative_collections = [
        str(item).strip()
        for item in (request.get("authoritative_collections") or [])
        if str(item or "").strip()
    ]
    requested_authoritative_collections = list(dict.fromkeys(requested_authoritative_collections))
    # `get_retrieval_profile` already applied the tenant Membrane to the
    # graph-owned list. Reassert only that effective intersection after corpus
    # planning; replaying the raw request here would reintroduce a collection
    # the Membrane deliberately removed.
    authoritative_collections = (
        list(profile.get("collections") or []) if requested_authoritative_collections else []
    )
    authoritative_document_scope = profile.get("authoritative_document_scope") is True
    authoritative_retrieval_filters = dict(profile.get("retrieval_filters") or {})
    query = profile["query"]
    guides = _effective_guides_for_profile(profile)
    guide_hint = guide_query_hint(guides)
    retrieval_policy = retrieval_policy_from_guides(guides)
    retrieval_policy = _apply_source_policy_to_retrieval_policy(request, retrieval_policy)
    clarification = clarification_from_policy(query, retrieval_policy)
    # These auxiliary lanes do not currently accept a document allowlist. They
    # must be disabled under a Builder-authored hard scope instead of silently
    # searching the whole collection.
    table_analysis = (
        None if authoritative_document_scope else _table_analysis_for_profile(request, profile)
    )
    document_analysis = (
        None if authoritative_document_scope else _document_analysis_for_profile(request, profile)
    )
    retrieval_query = query
    collections = profile.get("collections") or [profile["collection"]]
    corpus_plan = None
    skip_corpus_planner = bool(
        profile.get("retrieval_profile") == "oracle_fast"
        and _native_qdrant_sparse_hybrid_available()
    )
    if not skip_corpus_planner:
        planner_db = SessionLocal()
        try:
            planner_request = dict(request)
            planner_request["retrieval_filters"] = dict(profile.get("retrieval_filters") or {})
            corpus_plan = plan_corpus(
                db=planner_db,
                profile=profile,
                query=retrieval_query,
                request=planner_request,
                retrieval_policy=retrieval_policy,
            )
        except Exception as exc:  # noqa: BLE001 - planner must never block chat.
            logger.warning("rag_context: corpus planner failed", error=str(exc))
        finally:
            planner_db.close()
    if corpus_plan is not None:
        planned_collections = (
            corpus_plan.retrieval_scope.get("collections")
            if isinstance(corpus_plan.retrieval_scope, Mapping)
            else None
        )
        if authoritative_collections:
            planned_collections = authoritative_collections
        if isinstance(planned_collections, list) and planned_collections:
            profile["collections"] = [
                str(item) for item in planned_collections if str(item or "").strip()
            ]
            if profile["collections"]:
                profile["collection"] = profile["collections"][0]
                collections = profile["collections"]
        profile["top_k"] = corpus_plan.top_k
        profile["candidate_pool_k"] = corpus_plan.candidate_pool_k
        profile["synthesis_k"] = corpus_plan.synthesis_k
        profile["source_display_k"] = corpus_plan.source_display_k
        profile["latency_profile"] = corpus_plan.latency_profile
        profile["retrieval_filters"] = (
            {**dict(corpus_plan.filters or {}), **authoritative_retrieval_filters}
            if authoritative_document_scope
            else corpus_plan.filters
        )
        profile["deadline_seconds"] = corpus_plan.deadline_seconds
        profile_contract = profile.get("retrieval_profile_contract")
        allow_cross_encoder = bool(
            profile_contract.get("allow_cross_encoder")
            if isinstance(profile_contract, Mapping)
            else (profile.get("latency_budget") or {}).get("allow_cross_encoder")
        )
        profile["latency_budget"] = {
            "profile": corpus_plan.latency_profile,
            "retrieval_profile": profile.get("retrieval_profile"),
            "allow_cross_encoder": allow_cross_encoder,
            "deadline_seconds": corpus_plan.deadline_seconds,
            "top_k": corpus_plan.top_k,
            "candidate_pool_k": corpus_plan.candidate_pool_k,
        }
        profile["_corpus_plan_use_hybrid"] = corpus_plan.use_hybrid
        profile["_corpus_plan_allow_hah_chah"] = corpus_plan.allow_hah_chah
        profile["_corpus_plan_allow_legacy_hybrid"] = corpus_plan.allow_legacy_hybrid
        profile["_corpus_plan_max_variants"] = corpus_plan.max_variants
        profile["_corpus_plan_max_candidates"] = corpus_plan.max_candidates
        profile["_corpus_plan_soft_scope_filters"] = dict(corpus_plan.soft_scope_filters or {})
        profile["_corpus_plan_soft_scope_collections"] = [
            item
            for item in (corpus_plan.soft_scope_collections or [])
            if not authoritative_collections or item in authoritative_collections
        ]
        profile["_corpus_plan_recall_floor_collections"] = [
            item
            for item in (corpus_plan.recall_floor_collections or [])
            if not authoritative_collections or item in authoritative_collections
        ]
        profile["_corpus_plan_recall_floor_top_n"] = int(corpus_plan.recall_floor_top_n or 0)
    # Authoritative correction overlay (Volet 3): once a workspace opts into
    # expert-fiche corrections the resolved fiche collection must ALWAYS be a
    # retrieval candidate. ``get_retrieval_profile`` already appends it, but the
    # corpus planner may REPLACE the collection list with a hard ledger/table
    # scope (``plan_corpus`` -> ``retrieval_scope['collections']`` above) that
    # targets other collections, and the membrane inbound allowlist may
    # intersect it away — either drops the fiche before retrieval. Re-union it
    # here, AFTER all scope narrowing, so a hard knowledge_scope can no longer
    # exclude it. Strictly additive and single-collection: only the fiche slug
    # is added, nothing else is broadened. The fan-out then searches the fiche
    # collection unscoped (see ``_expert_fiche_collection`` below) so the
    # planner's document_filename filter — scoped to the OTHER collections'
    # docs — cannot filter every fiche chunk out.
    expert_fiche_collection = (
        ""
        if authoritative_collections
        else _enabled_expert_fiche_collection(
            workspace_slug=request.get("workspace_slug"),
            source_policy=request.get("source_policy"),
        )
    )
    if expert_fiche_collection:
        planned_collections = list(profile.get("collections") or [])
        if expert_fiche_collection not in planned_collections:
            planned_collections.append(expert_fiche_collection)
        # The correction overlay is not a second authority boundary. Reuse the
        # Membrane resolver after planner replacement so explicit v2 enforce
        # can remove (or reject) a collection that the compatibility overlay
        # tried to reintroduce. Derived/v1 behaviour remains unchanged.
        source_policy = request.get("source_policy")
        raw_membrane = (
            source_policy.get("membrane_spec") if isinstance(source_policy, Mapping) else None
        )
        if isinstance(raw_membrane, Mapping) and raw_membrane.get("version") == 2:
            planned_collections = _apply_membrane_inbound_collections(
                planned_collections,
                source_policy=source_policy,
            )
        profile["collections"] = planned_collections
        profile["collection"] = planned_collections[0]
        collections = planned_collections
        if expert_fiche_collection in planned_collections:
            profile["_expert_fiche_collection"] = expert_fiche_collection
        else:
            expert_fiche_collection = ""
    expert_fiche_included = bool(
        expert_fiche_collection and expert_fiche_collection in (collections or [])
    )
    if authoritative_collections:
        profile["collections"] = authoritative_collections
        profile["collection"] = authoritative_collections[0]
        collections = authoritative_collections
    retrieval_filters = dict(profile.get("retrieval_filters") or {})
    metrics: dict[str, Any] = {
        "query": query,
        "retrieval_query": retrieval_query,
        "duration_ms": 0,
        "chunks_retrieved": 0,
        "scope": profile.get("knowledge_scope"),
        "scope_label": profile.get("scope_label"),
        "collections_touched": collections,
        "collection": profile["collection"],
        "collections": collections,
        "vector_db": profile["vector_db"],
        "profile": profile.get("retrieval_profile"),
        "retrieval_profile": profile.get("retrieval_profile"),
        "retrieval_profile_contract": profile.get("retrieval_profile_contract"),
        "top_k": profile["top_k"],
        "candidate_pool_k": profile["candidate_pool_k"],
        "synthesis_k": profile["synthesis_k"],
        "source_display_k": profile["source_display_k"],
        "fallback": bool(fallback_reason or (corpus_plan.fallback_reason if corpus_plan else None)),
        "fallback_reason": fallback_reason
        or (corpus_plan.fallback_reason if corpus_plan else None),
        "knowledge_guides": len(guides),
        "query_expanded_with_guides": bool(guides),
        "knowledge_guide_hint_chars": len(guide_hint),
        "retrieval_policy": _retrieval_policy_summary(retrieval_policy, clarification),
        "retrieval_policy_enabled": retrieval_policy.enabled,
        "retrieval_policy_clarification": bool(clarification and clarification.get("required")),
        "retrieval_constraints": {},
        "latency_profile": profile.get("latency_profile"),
        "latency_budget": {
            "profile": profile.get("latency_profile"),
            "retrieval_profile": profile.get("retrieval_profile"),
            "allow_cross_encoder": bool(
                (profile.get("latency_budget") or {}).get("allow_cross_encoder")
            ),
            "deadline_seconds": profile.get("deadline_seconds")
            or _deadline_seconds_for_profile(str(profile.get("latency_profile") or "fast")),
            "top_k": profile["top_k"],
            "candidate_pool_k": profile["candidate_pool_k"],
        },
        "retrieval_scope": corpus_plan.retrieval_scope if corpus_plan else {},
        "retrieval_plan": corpus_plan.retrieval_plan if corpus_plan else {},
        "scope_confidence": corpus_plan.scope_confidence if corpus_plan else 0.0,
        "scope_reason": corpus_plan.scope_reason if corpus_plan else "",
        "dense_policy": corpus_plan.dense_policy if corpus_plan else "standard",
        "deep_retrieval_recommended": corpus_plan.deep_retrieval_recommended
        if corpus_plan
        else False,
        "soft_scope_filters": dict(corpus_plan.soft_scope_filters or {}) if corpus_plan else {},
        "soft_scope_collections": list(corpus_plan.soft_scope_collections or [])
        if corpus_plan
        else [],
        "recall_floor_collections": list(corpus_plan.recall_floor_collections or [])
        if corpus_plan
        else [],
        "recall_floor_top_n": int(corpus_plan.recall_floor_top_n or 0) if corpus_plan else 0,
        "expert_fiche_collection": expert_fiche_collection or None,
        "expert_fiche_collection_included": expert_fiche_included,
    }
    cache_key = _retrieval_context_cache_key(
        profile=profile,
        query=retrieval_query,
        retrieval_filters=retrieval_filters,
        metrics=metrics,
        guides=guides,
        retrieval_policy=retrieval_policy,
    )
    cached_context = _get_cached_retrieval_context(cache_key, started=started)
    if cached_context is not None:
        return cached_context

    # Exhaustive cross-project enumeration (transversal_inventory). For "which
    # projects have/use <equipment>" questions the LLM otherwise enumerates from
    # the few dozen retrieved chunks and returns a partial list. We compute the
    # COMPLETE list deterministically by faceting Qdrant on the project_code
    # payload key, filtered by the query's discriminating equipment term(s), and
    # attach it to the answer context so the model lists every project. The
    # facet runs concurrently with retrieval and is awaited at payload assembly;
    # any failure leaves the existing deep-retrieval behaviour untouched.
    inventory_task = None
    if not authoritative_document_scope and _should_build_project_inventory(request, query):
        inventory_task = asyncio.ensure_future(
            asyncio.to_thread(_safe_build_project_inventory, dict(profile), query)
        )

    async def _attach_project_inventory(payload: dict[str, Any]) -> dict[str, Any]:
        if inventory_task is None or not isinstance(payload, dict):
            return payload
        try:
            inventory = await inventory_task
        except Exception as exc:  # noqa: BLE001 - inventory is best-effort.
            logger.warning("rag_context: project inventory task failed", error=str(exc))
            inventory = None
        if inventory:
            payload["project_inventory"] = inventory
            payload_metrics = payload.get("metrics")
            if isinstance(payload_metrics, dict):
                payload_metrics["project_inventory_total_projects"] = inventory.get(
                    "total_projects"
                )
                payload_metrics["project_inventory_terms"] = inventory.get("terms")
        return payload

    if not authoritative_document_scope and (
        is_collection_inventory_query(query)
        or (corpus_plan is not None and corpus_plan.intent == "catalogue")
    ):
        inventory_context = _retrieve_collection_inventory_context(
            profile,
            started=started,
            metrics=metrics,
        )
        if inventory_context is not None:
            inventory_context = await _attach_project_inventory(inventory_context)
            _set_cached_retrieval_context(cache_key, inventory_context)
            return inventory_context

    if (
        corpus_plan is not None
        and corpus_plan.dense
        and not corpus_plan.filters
        and not retrieval_filters
        and corpus_plan.fallback_reason
    ):
        coarse_context = _retrieve_dense_unscoped_coarse_context(
            profile,
            started=started,
            metrics=metrics,
        )
        if coarse_context is not None:
            coarse_context = await _attach_project_inventory(coarse_context)
            _set_cached_retrieval_context(cache_key, coarse_context)
            return coarse_context

    if len(collections) > 1 and doc_svc is None:
        multi_context = await _retrieve_multi_collection_context(
            request,
            profile=profile,
            started=started,
            metrics=metrics,
            fallback_reason=fallback_reason,
            guides=guides,
            table_analysis=table_analysis,
            document_analysis=document_analysis,
            retrieval_query=retrieval_query,
            guide_hint=guide_hint,
            retrieval_policy=retrieval_policy,
            clarification=clarification,
        )
        return await _attach_project_inventory(multi_context)

    try:
        if doc_svc is None:
            doc_svc = _document_service_for_profile(profile, str(profile["collection"]))
    except Exception as exc:  # noqa: BLE001
        metrics.update(
            {
                "duration_ms": int((time.time() - started) * 1000),
                "error": str(exc),
                "fallback": True,
                "fallback_reason": fallback_reason or "document_service_unavailable",
            }
        )
        guide_chunks, guide_scores, guide_metas = guide_context_entries(guides)
        metrics["chunks_retrieved"] = len(guide_chunks)
        metrics["no_context"] = len(guide_chunks) == 0
        _finalize_retrieval_metrics(metrics)
        return await _attach_project_inventory(
            {
                "chunks": guide_chunks,
                "scores": guide_scores,
                "metadatas": guide_metas,
                "pipeline": "fallback_hybrid",
                "label": "none",
                "reason": "DocumentService unavailable",
                "detail": str(exc),
                "mode_label": "none",
                "mode_reason": "DocumentService unavailable",
                "use_hybrid": True,
                "query": query,
                "retrieval_query": retrieval_query,
                "retrieval_policy": _retrieval_policy_payload(retrieval_policy, clarification),
                "retrieval_constraints": {},
                "clarification": clarification,
                "metrics": _jsonable(metrics),
                "retrieval_decision_trace": _jsonable(metrics.get("retrieval_decision_trace")),
                "collections_touched": [],
                "collection_errors": [{"collection": profile["collection"], "error": str(exc)}],
            }
        )

    use_hybrid, mode_label, mode_reason = await resolve_retrieval_mode(
        doc_svc,
        retrieval_query,
        profile["rag_mode"],
        latency_profile=profile.get("latency_profile"),
    )
    effective_mode = profile["rag_mode"]
    allow_hah_chah = settings.rag_hah_chah_enabled
    allow_legacy_hybrid = True
    deadline_seconds = float(settings.rag_fast_retrieval_deadline_seconds)
    max_variants = 3
    max_candidates = profile["candidate_pool_k"]
    if corpus_plan is not None:
        deadline_seconds = corpus_plan.deadline_seconds
        max_variants = corpus_plan.max_variants
        max_candidates = corpus_plan.max_candidates
        allow_legacy_hybrid = corpus_plan.allow_legacy_hybrid
        if corpus_plan.use_hybrid is not None:
            use_hybrid = corpus_plan.use_hybrid
        if not corpus_plan.allow_hah_chah:
            allow_hah_chah = False
            if str(effective_mode or "").lower() in {
                "hah",
                "hah_rag",
                "hah rag",
                "chah",
                "c-hah",
                "c_hah",
                "hahcomposite",
                "hah_composite",
            }:
                effective_mode = "naive"
                mode_label = corpus_plan.dense_policy
                mode_reason = (
                    "Dense corpus quick ask policy: HAH/C-HAH runs as deep async retrieval; "
                    "interactive retrieval is bounded over an inferred system scope."
                )
        if corpus_plan.dense_policy.startswith("fast_scoped_dense"):
            mode_label = corpus_plan.dense_policy
            mode_reason = corpus_plan.scope_reason
    planner_disabled_hybrid = bool(corpus_plan is not None and corpus_plan.use_hybrid is False)
    if (
        _native_qdrant_sparse_hybrid_available()
        and not _mode_requests_dense_only(profile.get("rag_mode"))
        and not planner_disabled_hybrid
    ):
        use_hybrid = True
        allow_legacy_hybrid = False
    is_discovery = is_document_discovery_query(retrieval_query)
    pool_top_k = (
        profile["candidate_pool_k"]
        if profile.get("latency_profile") == "fast"
        else _discovery_pool_top_k(profile["candidate_pool_k"], is_discovery)
    )
    synthesis_k = profile["synthesis_k"]

    # Soft fact-scope: a large ledger-backed single collection is searched with
    # the planner's fact-doc filter instead of an unscoped global chunk search
    # (which is too slow on it and times out, starving the answer). Small
    # collections keep the unscoped pass. See the planner note on the additive
    # soft boost. retrieval_filters (explicit/hard scope) always wins.
    soft_scope_filters = dict(profile.get("_corpus_plan_soft_scope_filters") or {})
    soft_scope_collections = set(profile.get("_corpus_plan_soft_scope_collections") or [])
    use_soft_single = bool(
        soft_scope_filters
        and not retrieval_filters
        and str(profile["collection"]) in soft_scope_collections
    )
    primary_filters = (
        soft_scope_filters
        if use_soft_single
        else _authoritative_filters_for_collection(
            profile,
            profile["collection"],
            retrieval_filters,
        )
    )
    if primary_filters is None:
        # This is only reachable for malformed/direct requests: a hard pair-map
        # names documents in other collections but not the selected collection.
        # Use an impossible document id rather than treating an empty filter as
        # an instruction to search the full collection.
        primary_filters = {"document_id": ["__omnirag_no_authoritative_document__"]}
    if use_soft_single:
        metrics["soft_scope_boost"] = {
            "applied": True,
            "scoped_collections": [str(profile["collection"])],
            "filter_keys": sorted(soft_scope_filters),
        }

    def _retrieve_coro(
        call_filters: dict[str, Any] | None, call_deadline: float, query_override: str | None = None
    ):
        return retrieve_for_mode(
            doc_svc,
            query_override or retrieval_query,
            effective_mode,
            top_k=pool_top_k,
            use_hybrid=use_hybrid,
            hah_chah_enabled=allow_hah_chah,
            query_hints=guide_hint,
            retrieval_policy=retrieval_policy,
            filters=call_filters,
            deadline_seconds=call_deadline,
            max_variants=max_variants,
            max_candidates=max_candidates,
            allow_legacy_hybrid=allow_legacy_hybrid,
            retrieval_profile=profile.get("retrieval_profile"),
            latency_profile=profile.get("latency_profile"),
            extra_variants=_deep_rewrite_variants(request, profile),
        )

    try:
        retrieval_started_perf = time.perf_counter()
        result = await asyncio.wait_for(
            _retrieve_coro(primary_filters, deadline_seconds),
            timeout=deadline_seconds,
        )
        retrieval_elapsed_ms = int((time.perf_counter() - retrieval_started_perf) * 1000)
    except TimeoutError:
        metrics.update(
            {
                "fallback": True,
                "fallback_reason": fallback_reason or "retrieval_deadline_exceeded",
                "duration_ms": int((time.time() - started) * 1000),
                "retrieval_elapsed_ms": int((time.perf_counter() - retrieval_started_perf) * 1000),
                "no_context": True,
            }
        )
        guide_chunks, guide_scores, guide_metas = guide_context_entries(guides)
        _finalize_retrieval_metrics(metrics)
        return await _attach_project_inventory(
            _jsonable(
                {
                    "chunks": guide_chunks,
                    "scores": guide_scores,
                    "metadatas": guide_metas,
                    "pipeline": "retrieval_timeout",
                    "label": "Retrieval deadline",
                    "reason": "Interactive retrieval exceeded its latency budget.",
                    "detail": "A deeper retrieval can continue asynchronously without blocking the chat stream.",
                    "mode_label": mode_label,
                    "mode_reason": mode_reason,
                    "use_hybrid": use_hybrid,
                    "top_k": profile["top_k"],
                    "candidate_pool_k": profile["candidate_pool_k"],
                    "synthesis_k": profile["synthesis_k"],
                    "source_display_k": profile["source_display_k"],
                    "query": query,
                    "retrieval_query": retrieval_query,
                    "retrieval_policy": _retrieval_policy_payload(retrieval_policy, clarification),
                    "retrieval_constraints": {},
                    "clarification": clarification,
                    "collection": profile["collection"],
                    "collections": collections,
                    "knowledge_scope": profile.get("knowledge_scope"),
                    "scope_label": profile.get("scope_label"),
                    "vector_db": profile["vector_db"],
                    "workspace_slug": profile["workspace_slug"],
                    "metrics": metrics,
                    "retrieval_decision_trace": metrics.get("retrieval_decision_trace"),
                    "retrieval_scope": metrics.get("retrieval_scope"),
                    "retrieval_plan": metrics.get("retrieval_plan"),
                    "scope_confidence": metrics.get("scope_confidence"),
                    "scope_reason": metrics.get("scope_reason"),
                    "dense_policy": metrics.get("dense_policy"),
                    "fallback_reason": metrics.get("fallback_reason"),
                    "latency_budget": metrics.get("latency_budget"),
                    "deep_retrieval_recommended": True,
                    "collections_touched": [profile["collection"]],
                    "collection_errors": [],
                }
            )
        )

    (
        result.chunks,
        result.scores,
        result.metadatas,
        authoritative_evidence_dropped,
    ) = _enforce_authoritative_document_evidence(
        list(result.chunks or []),
        list(result.scores or []),
        list(result.metadatas or []),
        profile=profile,
        collection=str(profile["collection"]),
    )
    metrics["authoritative_document_evidence_dropped"] = authoritative_evidence_dropped

    # Deep scope-miss recovery. A ledger-inferred document scope can point at
    # documents that exist in the SQL ledger but were never ingested into the
    # vector store (the SQL ledger is a superset of Qdrant on partially-ingested
    # corpora). The payload filter then excludes every candidate and deep would
    # return 0 passages — the empty grounding fallback the user sees as
    # "deep_timeout · 0 passages". Deep (async) has ample deadline headroom, so
    # retry once over the collection without the doc-level scope filters rather
    # than degrading to an empty answer. Only triggers when a doc-level scope was
    # actually inferred and produced nothing, so genuinely-unscoped deep plans
    # (coarse inventory) and successful scoped retrievals are untouched.
    _SCOPE_MISS_FILTER_KEYS = ("document_filename", "document_id", "archive_name")
    scope_miss_recovery = None
    if (
        str(profile.get("latency_profile") or "") == "deep"
        and not result.chunks
        and profile.get("authoritative_document_scope") is not True
        and isinstance(retrieval_filters, dict)
        and any(key in retrieval_filters for key in _SCOPE_MISS_FILTER_KEYS)
    ):
        relaxed_filters = {
            key: value
            for key, value in retrieval_filters.items()
            if key not in _SCOPE_MISS_FILTER_KEYS
        }
        remaining_deadline = deadline_seconds - (time.perf_counter() - retrieval_started_perf)
        if remaining_deadline >= 1.0:
            try:
                retry_result = await asyncio.wait_for(
                    _retrieve_coro(relaxed_filters or None, remaining_deadline),
                    timeout=remaining_deadline,
                )
            except (TimeoutError, asyncio.TimeoutError):
                retry_result = None
            except Exception as exc:  # noqa: BLE001 - recovery must never break deep.
                logger.warning("deep scope-miss recovery failed", error=str(exc))
                retry_result = None
            if retry_result is not None and retry_result.chunks:
                result = retry_result
                retrieval_filters = relaxed_filters
                retrieval_elapsed_ms = int((time.perf_counter() - retrieval_started_perf) * 1000)
                scope_miss_recovery = {
                    "scope_miss_recovery": True,
                    "scope_miss_dropped_filters": [
                        key
                        for key in _SCOPE_MISS_FILTER_KEYS
                        if key in (profile.get("retrieval_filters") or {})
                    ],
                }
                logger.info(
                    "deep scope-miss recovery applied",
                    chunks=len(result.chunks),
                    dropped=scope_miss_recovery["scope_miss_dropped_filters"],
                )

    duration_ms = int((time.time() - started) * 1000)
    raw_chunk_count = len(result.chunks)
    if scope_miss_recovery:
        metrics.update(scope_miss_recovery)

    # Comparative decomposition: an "A vs B" query under-recalls the second
    # entity. When enabled (deep by default; balanced behind a flag) and two
    # entities parse out, run entity-focused sub-queries through this same
    # bounded pipeline and merge so each entity reaches the candidate pool;
    # ensure_entity_coverage later guarantees ≥1 chunk per entity in the top-k.
    comparative_plan = build_comparative_plan(
        retrieval_query, latency_profile=profile.get("latency_profile")
    )
    comparative_sub_results = None
    if comparative_plan is not None and result.chunks:
        comparative_remaining = deadline_seconds - (time.perf_counter() - retrieval_started_perf)
        if comparative_remaining >= 0.5:

            async def _comparative_subretrieve(subquery: str, sub_deadline: float):
                nonlocal authoritative_evidence_dropped
                sub_result = await _retrieve_coro(
                    primary_filters,
                    min(sub_deadline, comparative_remaining),
                    query_override=subquery,
                )
                (
                    sub_result.chunks,
                    sub_result.scores,
                    sub_result.metadatas,
                    dropped,
                ) = _enforce_authoritative_document_evidence(
                    list(sub_result.chunks or []),
                    list(sub_result.scores or []),
                    list(sub_result.metadatas or []),
                    profile=profile,
                    collection=str(profile["collection"]),
                )
                authoritative_evidence_dropped += dropped
                return sub_result

            (
                merged_chunks,
                merged_scores,
                merged_metas,
                comparative_diag,
            ) = await augment_with_comparative_subqueries(
                plan=comparative_plan,
                primary=(result.chunks, result.scores, result.metadatas),
                retrieve=_comparative_subretrieve,
                deadline_seconds=comparative_remaining,
                pool_limit=pool_top_k,
            )
            comparative_sub_results = comparative_diag.pop("_sub_results", None)
            result.chunks, result.scores, result.metadatas = (
                merged_chunks,
                merged_scores,
                merged_metas,
            )
            (
                result.chunks,
                result.scores,
                result.metadatas,
                dropped,
            ) = _enforce_authoritative_document_evidence(
                list(result.chunks or []),
                list(result.scores or []),
                list(result.metadatas or []),
                profile=profile,
                collection=str(profile["collection"]),
            )
            authoritative_evidence_dropped += dropped
            metrics["authoritative_document_evidence_dropped"] = authoritative_evidence_dropped
            metrics.update(comparative_diag)
        else:
            metrics.update(
                {"comparative_decompose": False, "comparative_skipped_reason": "deadline"}
            )
    elif comparative_plan is not None:
        metrics.update(
            {"comparative_decompose": False, "comparative_skipped_reason": "no_primary_hits"}
        )

    # Recall floor: the hard document_filename allowlist is a filename-keyword
    # guess and can omit the real answer doc. Add a bounded UNSCOPED dense pass
    # over the same large collection and union it into the pre-rerank pool so a
    # missed-but-high-relevance answer doc still gets a chance. Strictly gated by
    # the planner (large collection + hard document_filename filter); a no-op
    # otherwise, and the scoped pass remains the primary precision layer.
    if _recall_floor_active(profile, str(profile["collection"]), retrieval_filters):
        floor_remaining = deadline_seconds - (time.perf_counter() - retrieval_started_perf)
        floor_top_n = int(profile.get("_corpus_plan_recall_floor_top_n") or 0) or pool_top_k
        if floor_remaining >= 0.3:
            try:
                floor_result = await asyncio.wait_for(
                    _retrieve_recall_floor_pass(
                        doc_svc,
                        retrieval_query=retrieval_query,
                        top_n=floor_top_n,
                        retrieval_policy=retrieval_policy,
                        deadline_seconds=floor_remaining,
                        max_candidates=max_candidates,
                        retrieval_profile=profile.get("retrieval_profile"),
                        latency_profile=profile.get("latency_profile"),
                    ),
                    timeout=floor_remaining,
                )
            except (TimeoutError, asyncio.TimeoutError):
                floor_result = None
            except Exception as exc:  # noqa: BLE001 - floor must never break retrieval.
                logger.warning("recall floor pass failed", error=str(exc))
                floor_result = None
            if floor_result is not None and getattr(floor_result, "chunks", None):
                (
                    result.chunks,
                    result.scores,
                    result.metadatas,
                    floor_added,
                ) = _union_recall_floor(
                    list(result.chunks),
                    list(result.scores),
                    list(result.metadatas),
                    floor_result,
                )
                metrics["recall_floor"] = {
                    "applied": True,
                    "collection": str(profile["collection"]),
                    "top_n": floor_top_n,
                    "candidates_added": floor_added,
                }
            else:
                metrics["recall_floor"] = {"applied": False, "reason": "no_floor_candidates"}
        else:
            metrics["recall_floor"] = {"applied": False, "reason": "deadline"}

    inventory_evidence_spec = (
        None
        if authoritative_document_scope
        else _single_project_inventory_evidence_spec(
            retrieval_query,
            retrieval_filters,
            retrieval_policy,
        )
    )
    inventory_evidence_rows: list[dict[str, Any]] = []
    inventory_evidence_diag: dict[str, Any] | None = None
    if inventory_evidence_spec is not None:
        retrieval_stage_elapsed = time.perf_counter() - retrieval_started_perf
        inventory_remaining = min(
            deadline_seconds - retrieval_stage_elapsed,
            _INVENTORY_EVIDENCE_RETRIEVAL_CUTOFF_SECONDS - retrieval_stage_elapsed,
        )
        if inventory_remaining >= 0.15:
            (
                inventory_evidence_rows,
                inventory_evidence_diag,
            ) = await _retrieve_single_project_inventory_evidence(
                doc_svc,
                inventory_evidence_spec,
                timeout_seconds=min(1.2, max(0.1, inventory_remaining - 0.05)),
            )
        else:
            inventory_evidence_diag = {
                "status": "skipped_deadline",
                "elapsed_ms": 0,
            }

    retrieval_diagnostics = {
        key: value
        for key, value in (getattr(result, "diagnostics", {}) or {}).items()
        if value is not None
    }
    sparse_status = str(retrieval_diagnostics.get("sparse_status") or "").strip().lower()
    dense_only = bool(
        not use_hybrid
        or (retrieval_diagnostics.get("sparse_backend") and sparse_status not in {"ok"})
    )
    metadatas = []
    for meta in result.metadatas or []:
        annotated = dict(meta or {})
        annotated["collection"] = profile["collection"]
        annotated["collection_name"] = profile["collection"]
        metadatas.append(annotated)
    rerank_started_perf = time.perf_counter()
    chunks, scores, metadatas, duplicates_removed = _dedupe_aligned_results(
        result.chunks,
        result.scores,
        metadatas,
    )
    chunks, scores, metadatas = rerank_aligned_with_policy(
        chunks,
        scores,
        metadatas,
        query=retrieval_query,
        policy=retrieval_policy,
    )
    chunks, scores, metadatas, retrieval_constraints = filter_aligned_to_required_terms(
        chunks,
        scores,
        metadatas,
        query=retrieval_query,
        policy=retrieval_policy,
    )
    chunks, scores, metadatas, cross_encoder_diag = await rerank_with_cross_encoder(
        chunks,
        scores,
        metadatas,
        query=retrieval_query,
        latency_profile=profile.get("latency_profile"),
        allow_cross_encoder=bool((profile.get("latency_budget") or {}).get("allow_cross_encoder")),
        top_k=int(profile.get("top_k") or 0),
        is_exempt_metadata=_is_threshold_exempt_metadata,
    )
    metrics.update(cross_encoder_diag)
    chunks, scores, metadatas, threshold_metrics = _apply_similarity_threshold(
        chunks,
        scores,
        metadatas,
        pipeline=result.pipeline,
    )
    chunks, scores, metadatas, diversity_metrics = await _diversify_final_context(
        chunks,
        scores,
        metadatas,
        query=retrieval_query,
        latency_profile=profile.get("latency_profile"),
        limit=synthesis_k,
    )
    chunks, scores, metadatas = prioritise_temporary_measure_evidence_aligned(
        chunks,
        scores,
        metadatas,
        question=retrieval_query,
    )
    # The wide candidate pool exists to improve recall before policy rerank /
    # dedupe. Only the synthesis budget is sent to the LLM; with cross-encoder
    # scores available, the low-quality tail is cut below synthesis_k.
    chunks, scores, metadatas, compression_diag = _compress_final_context(
        chunks,
        scores,
        metadatas,
        synthesis_k=synthesis_k,
        cross_encoder_status=cross_encoder_diag.get("cross_encoder_status"),
    )
    metrics.update(compression_diag)
    if comparative_plan is not None and comparative_sub_results:
        chunks, scores, metadatas, coverage_diag = ensure_entity_coverage(
            chunks,
            scores,
            metadatas,
            plan=comparative_plan,
            sub_results=comparative_sub_results,
            limit=synthesis_k,
            is_exempt=_is_threshold_exempt_metadata,
        )
        metrics.update(coverage_diag)
    if inventory_evidence_spec is not None:
        (
            chunks,
            scores,
            metadatas,
            inventory_coverage_diag,
        ) = _ensure_inventory_evidence_coverage(
            chunks,
            scores,
            metadatas,
            inventory_evidence_rows,
            synthesis_k=synthesis_k,
            collection=str(profile["collection"]),
        )
        metrics["inventory_evidence"] = {
            **(inventory_evidence_diag or {}),
            **inventory_coverage_diag,
        }
    rerank_ms = int((time.perf_counter() - rerank_started_perf) * 1000)
    document_chunk_count = len(chunks)
    chunks, scores, metadatas, parent_context_count = await _append_parent_context(
        chunks,
        scores,
        metadatas,
        doc_svc=doc_svc,
    )
    chunks, scores, metadatas, dropped = _enforce_authoritative_document_evidence(
        chunks,
        scores,
        metadatas,
        profile=profile,
        collection=str(profile["collection"]),
    )
    authoritative_evidence_dropped += dropped
    parent_context_count = max(0, parent_context_count - dropped)
    metrics["authoritative_document_evidence_dropped"] = authoritative_evidence_dropped
    context_build_started_perf = time.perf_counter()
    summary_artifact = _summary_artifact_for_profile(
        profile, metrics=metrics, query=retrieval_query
    )
    chunks, scores, metadatas, summary_artifact_count = _prepend_summary_artifact_context(
        chunks,
        scores,
        metadatas,
        summary_artifact,
    )
    chunks, scores, metadatas, table_evidence_count = _prepend_table_analysis_context(
        chunks,
        scores,
        metadatas,
        table_analysis,
    )
    chunks, scores, metadatas, document_evidence_count = _prepend_document_analysis_context(
        chunks,
        scores,
        metadatas,
        document_analysis,
    )
    chunks, scores, metadatas, guide_count = _prepend_guide_context(
        chunks,
        scores,
        metadatas,
        guides,
    )
    chunks, scores, metadatas, exact_guardrail_count = _prepend_exact_match_guardrail_context(
        chunks,
        scores,
        metadatas,
        query=retrieval_query,
        policy=retrieval_policy,
        diagnostics=retrieval_diagnostics,
        retrieval_filters=retrieval_filters,
    )
    chunks, scores, metadatas, membrane_inbound = _apply_membrane_inbound_evidence(
        chunks,
        scores,
        metadatas,
        profile=profile,
    )
    context_build_ms = int((time.perf_counter() - context_build_started_perf) * 1000)
    metrics.update(
        {
            "duration_ms": duration_ms,
            "retrieval_elapsed_ms": retrieval_diagnostics.get("retrieval_elapsed_ms")
            or retrieval_elapsed_ms,
            "dense_elapsed_ms": retrieval_diagnostics.get("dense_elapsed_ms"),
            "sparse_elapsed_ms": retrieval_diagnostics.get("sparse_elapsed_ms"),
            "rerank_ms": rerank_ms,
            "context_build_ms": context_build_ms,
            "chunks_retrieved": len(chunks),
            "document_chunks_retrieved": document_chunk_count,
            "parent_context_evidence": parent_context_count,
            "raw_chunks_retrieved": raw_chunk_count,
            "duplicates_removed": duplicates_removed,
            "knowledge_guides": guide_count,
            "summary_artifact_evidence": summary_artifact_count,
            "summary_artifact_status": (summary_artifact or {}).get("status")
            if summary_artifact
            else None,
            "summary_artifact_path": (summary_artifact or {}).get("jsonl_path")
            if summary_artifact
            else None,
            "table_analysis_evidence": table_evidence_count,
            "document_analysis_evidence": document_evidence_count,
            "exact_match_guardrail_inserted": bool(exact_guardrail_count),
            "membrane_inbound": membrane_inbound or None,
            "retrieval_constraints": retrieval_constraints,
            **threshold_metrics,
            **diversity_metrics,
            "candidate_pool_k": profile["candidate_pool_k"],
            "synthesis_k": profile["synthesis_k"],
            "source_display_k": profile["source_display_k"],
            "pipeline": result.pipeline,
            "mode_label": mode_label,
            "dense_only": dense_only,
            "no_context": len(chunks) == 0,
            **retrieval_diagnostics,
        }
    )
    selected_sources = _selected_source_trace(chunks, scores, metadatas)
    metrics["selected_sources"] = selected_sources
    metrics["retrieval_trace"] = {
        "trace_id": str(uuid4()),
        "planner": {
            "intent": (metrics.get("retrieval_scope") or {}).get("intent")
            if isinstance(metrics.get("retrieval_scope"), Mapping)
            else None,
            "dense": (metrics.get("retrieval_scope") or {}).get("dense")
            if isinstance(metrics.get("retrieval_scope"), Mapping)
            else None,
            "dense_policy": metrics.get("dense_policy"),
        },
        "scope": metrics.get("retrieval_scope"),
        "policy": metrics.get("retrieval_plan"),
        "layers": (metrics.get("retrieval_plan") or {}).get("layers")
        if isinstance(metrics.get("retrieval_plan"), Mapping)
        else {},
        "selected_sources": selected_sources,
        "failures": [metrics.get("fallback_reason")] if metrics.get("fallback_reason") else [],
    }
    _finalize_retrieval_metrics(metrics)
    payload = _jsonable(
        {
            "chunks": chunks,
            "scores": scores,
            "metadatas": metadatas,
            "pipeline": result.pipeline,
            "label": result.label,
            "reason": result.reason,
            "detail": result.detail,
            "mode_label": mode_label,
            "mode_reason": mode_reason,
            "use_hybrid": use_hybrid,
            "top_k": profile["top_k"],
            "candidate_pool_k": profile["candidate_pool_k"],
            "synthesis_k": profile["synthesis_k"],
            "source_display_k": profile["source_display_k"],
            "query": query,
            "retrieval_query": retrieval_query,
            "retrieval_policy": _retrieval_policy_payload(retrieval_policy, clarification),
            "retrieval_constraints": retrieval_constraints,
            "clarification": clarification,
            "collection": profile["collection"],
            "collections": collections,
            "knowledge_scope": profile.get("knowledge_scope"),
            "table_analysis": table_analysis,
            "document_analysis": document_analysis,
            "scope_label": profile.get("scope_label"),
            "vector_db": profile["vector_db"],
            "workspace_slug": profile["workspace_slug"],
            "metrics": metrics,
            "retrieval_decision_trace": metrics.get("retrieval_decision_trace"),
            "retrieval_scope": metrics.get("retrieval_scope"),
            "retrieval_plan": metrics.get("retrieval_plan"),
            "scope_confidence": metrics.get("scope_confidence"),
            "scope_reason": metrics.get("scope_reason"),
            "dense_policy": metrics.get("dense_policy"),
            "fallback_reason": metrics.get("fallback_reason"),
            "latency_budget": metrics.get("latency_budget"),
            "retrieval_profile": profile.get("retrieval_profile"),
            "retrieval_trace": metrics.get("retrieval_trace"),
            "deep_retrieval_recommended": metrics.get("deep_retrieval_recommended"),
            "collections_touched": [profile["collection"]],
            "collection_errors": [],
        }
    )
    payload = await _attach_project_inventory(payload)
    _set_cached_retrieval_context(cache_key, payload)
    return payload


def _content_key(chunk: Any, meta: dict[str, Any]) -> str:
    # Exact duplicate evidence uploaded to two collections must fuse before the
    # pool limit is applied. Including collection-specific document ids here
    # allowed duplicate incident/procedure chunks to occupy every slot and
    # crowd out a lower-ranked inventory row. The downstream context deduper
    # already treats exact text as one passage, so use that same identity at
    # collection fusion time.
    return _chunk_exact_key(chunk)


def _fuse_collection_results(
    collection_results: list[dict[str, Any]],
    *,
    limit: int,
) -> tuple[list[str], list[float], list[dict[str, Any]]]:
    fused: dict[str, dict[str, Any]] = {}
    k = 60.0
    for collection_result in collection_results:
        chunks = collection_result.get("chunks") or []
        scores = collection_result.get("scores") or []
        metadatas = collection_result.get("metadatas") or []
        for rank, chunk in enumerate(chunks):
            meta = dict(
                metadatas[rank]
                if rank < len(metadatas) and isinstance(metadatas[rank], Mapping)
                else {}
            )
            meta["collection"] = collection_result.get("collection")
            meta["collection_name"] = collection_result.get("collection")
            key = _content_key(chunk, meta)
            score = float(scores[rank]) if rank < len(scores) else 0.0
            rrf = 1.0 / (k + rank + 1)
            existing = fused.get(key)
            if existing is None:
                fused[key] = {"chunk": chunk, "score": score, "rrf": rrf, "metadata": meta}
            else:
                existing["rrf"] += rrf
                existing["score"] = max(existing["score"], score)

    ranked = sorted(
        fused.values(),
        key=lambda item: (float(item["rrf"]), float(item["score"])),
        reverse=True,
    )[:limit]
    return (
        [str(item["chunk"]) for item in ranked],
        [float(item["score"]) for item in ranked],
        [dict(item["metadata"]) for item in ranked],
    )


async def _retrieve_multi_collection_context(
    request: dict[str, Any],
    *,
    profile: dict[str, Any],
    started: float,
    metrics: dict[str, Any],
    fallback_reason: str | None,
    guides: list[Any],
    table_analysis: dict[str, Any] | None,
    document_analysis: dict[str, Any] | None,
    retrieval_query: str,
    guide_hint: str,
    retrieval_policy: RetrievalPolicy,
    clarification: dict[str, Any] | None,
) -> dict[str, Any]:
    query = profile["query"]
    is_discovery = is_document_discovery_query(retrieval_query)
    pool_top_k = (
        profile["candidate_pool_k"]
        if profile.get("latency_profile") == "fast"
        else _discovery_pool_top_k(profile["candidate_pool_k"], is_discovery)
    )
    synthesis_k = profile["synthesis_k"]
    collection_results: list[dict[str, Any]] = []
    collection_errors: list[dict[str, str]] = []
    retrieval_filters = dict(profile.get("retrieval_filters") or {})
    latency_budget = (
        metrics.get("latency_budget") if isinstance(metrics.get("latency_budget"), Mapping) else {}
    )
    deadline_seconds = float(
        latency_budget.get("deadline_seconds") or settings.rag_fast_retrieval_deadline_seconds
    )
    dense_policy = str(metrics.get("dense_policy") or "")
    allow_legacy_hybrid = bool(
        profile.get(
            "_corpus_plan_allow_legacy_hybrid",
            not dense_policy.startswith(("fast_scoped_dense", "deep_hierarchical_dense")),
        )
    )
    allow_hah_chah = bool(
        profile.get(
            "_corpus_plan_allow_hah_chah",
            settings.rag_hah_chah_enabled and not dense_policy.startswith("fast_scoped_dense"),
        )
    )
    planned_use_hybrid = profile.get("_corpus_plan_use_hybrid")
    max_variants = int(profile.get("_corpus_plan_max_variants") or 3)
    max_candidates = int(profile.get("_corpus_plan_max_candidates") or profile["candidate_pool_k"])
    # Soft fact-scope: large ledger-backed collections (`notices`) are searched
    # with the planner's fact-doc filter instead of an unscoped global chunk
    # search (which is too slow/low-value on them and would time out, starving
    # the answer). Small collections keep the unscoped pass; the per-collection
    # results are unioned by the fuse below. A user/hard scope always wins.
    soft_scope_filters = dict(profile.get("_corpus_plan_soft_scope_filters") or {})
    soft_scope_collections = set(profile.get("_corpus_plan_soft_scope_collections") or [])
    soft_scope_used: list[str] = []
    recall_floor_top_n = int(profile.get("_corpus_plan_recall_floor_top_n") or 0)
    recall_floor_added: dict[str, int] = {}
    # Authoritative correction overlay: the fiche collection (unioned in by
    # ``retrieve_rag_context`` when ``expert_fiche_correction_enabled``) is
    # searched by semantic relevance only — never with the planner's hard
    # document/project scope, which targets the other collections' docs and
    # would filter every fiche chunk out. Affects only this single collection.
    expert_fiche_collection = str(profile.get("_expert_fiche_collection") or "")
    expert_fiche_searched = False

    retrieval_loop_started_perf = time.perf_counter()
    retrieval_loop_deadline_perf = retrieval_loop_started_perf + max(deadline_seconds, 0.01)
    deadline_exceeded = False
    authoritative_evidence_dropped = 0
    for collection in profile.get("collections") or []:
        is_expert_fiche = (
            bool(expert_fiche_collection) and str(collection) == expert_fiche_collection
        )
        use_soft_scope = bool(
            not is_expert_fiche
            and soft_scope_filters
            and not retrieval_filters
            and str(collection) in soft_scope_collections
        )
        authoritative_filters = _authoritative_filters_for_collection(
            profile,
            collection,
            retrieval_filters,
        )
        if authoritative_filters is None:
            # A pair-map exists but no document was selected for this
            # collection. Skipping is the only fail-closed interpretation.
            continue
        if is_expert_fiche:
            call_filters: dict[str, Any] = {}
        elif use_soft_scope:
            call_filters = soft_scope_filters
        else:
            call_filters = authoritative_filters
        remaining_seconds = retrieval_loop_deadline_perf - time.perf_counter()
        if remaining_seconds <= 0:
            deadline_exceeded = True
            collection_errors.append(
                {"collection": collection, "error": "retrieval_deadline_exceeded"}
            )
            break
        try:
            doc_svc = _document_service_for_profile(profile, collection)
            use_hybrid, mode_label, mode_reason = await resolve_retrieval_mode(
                doc_svc,
                retrieval_query,
                profile["rag_mode"],
                latency_profile=profile.get("latency_profile"),
            )
            effective_mode = profile["rag_mode"]
            if planned_use_hybrid is not None:
                use_hybrid = bool(planned_use_hybrid)
            if not allow_hah_chah and str(effective_mode or "").lower() in {
                "hah",
                "hah_rag",
                "hah rag",
                "chah",
                "c-hah",
                "c_hah",
                "hahcomposite",
                "hah_composite",
            }:
                effective_mode = "naive"
                if planned_use_hybrid is None:
                    use_hybrid = False
            if (
                _native_qdrant_sparse_hybrid_available()
                and not _mode_requests_dense_only(profile.get("rag_mode"))
                and planned_use_hybrid is not False
            ):
                use_hybrid = True
                allow_legacy_hybrid = False
            remaining_seconds = max(retrieval_loop_deadline_perf - time.perf_counter(), 0.001)
            result = await asyncio.wait_for(
                retrieve_for_mode(
                    doc_svc,
                    retrieval_query,
                    effective_mode,
                    top_k=pool_top_k,
                    use_hybrid=use_hybrid,
                    hah_chah_enabled=allow_hah_chah,
                    query_hints=guide_hint,
                    retrieval_policy=retrieval_policy,
                    filters=call_filters,
                    deadline_seconds=remaining_seconds,
                    max_variants=max_variants,
                    max_candidates=max_candidates,
                    allow_legacy_hybrid=allow_legacy_hybrid,
                    retrieval_profile=profile.get("retrieval_profile"),
                    extra_variants=_deep_rewrite_variants(request, profile),
                ),
                timeout=remaining_seconds,
            )
            if use_soft_scope:
                soft_scope_used.append(collection)
            if is_expert_fiche:
                expert_fiche_searched = True
            safe_chunks, safe_scores, safe_metadatas, dropped = (
                _enforce_authoritative_document_evidence(
                    list(result.chunks or []),
                    list(result.scores or []),
                    list(result.metadatas or []),
                    profile=profile,
                    collection=str(collection),
                )
            )
            authoritative_evidence_dropped += dropped
            metadatas = []
            for meta in safe_metadatas:
                annotated = dict(meta or {})
                annotated["collection"] = collection
                annotated["collection_name"] = collection
                if use_soft_scope:
                    annotated["soft_scope_boost"] = True
                metadatas.append(annotated)
            collection_results.append(
                {
                    "collection": collection,
                    "chunks": safe_chunks,
                    "scores": safe_scores,
                    "metadatas": metadatas,
                    "pipeline": result.pipeline,
                    "label": result.label,
                    "mode_label": mode_label,
                    "mode_reason": mode_reason,
                    "detail": result.detail,
                    "chunks_retrieved": len(safe_chunks),
                    "diagnostics": {
                        key: value
                        for key, value in (getattr(result, "diagnostics", {}) or {}).items()
                        if value is not None
                    },
                }
            )
            # Recall floor: union a bounded UNSCOPED dense pass over the same
            # large scoped collection so an answer doc the hard document_filename
            # allowlist missed still reaches the fused pool. Appended as its own
            # fuse entry; RRF keeps its top hit high even if the cross-encoder is
            # later skipped. Strictly gated by the planner (a no-op otherwise).
            if _recall_floor_active(profile, collection, retrieval_filters):
                floor_remaining = max(retrieval_loop_deadline_perf - time.perf_counter(), 0.0)
                if floor_remaining >= 0.3:
                    try:
                        floor_result = await asyncio.wait_for(
                            _retrieve_recall_floor_pass(
                                doc_svc,
                                retrieval_query=retrieval_query,
                                top_n=recall_floor_top_n or pool_top_k,
                                retrieval_policy=retrieval_policy,
                                deadline_seconds=floor_remaining,
                                max_candidates=max_candidates,
                                retrieval_profile=profile.get("retrieval_profile"),
                                latency_profile=profile.get("latency_profile"),
                            ),
                            timeout=floor_remaining,
                        )
                    except (TimeoutError, asyncio.TimeoutError):
                        floor_result = None
                    except Exception as exc:  # noqa: BLE001 - floor must never break retrieval.
                        logger.warning(
                            "recall floor pass failed", collection=collection, error=str(exc)
                        )
                        floor_result = None
                    if floor_result is not None and getattr(floor_result, "chunks", None):
                        floor_metas = []
                        for meta in floor_result.metadatas or []:
                            annotated = dict(meta or {})
                            annotated["collection"] = collection
                            annotated["collection_name"] = collection
                            annotated["recall_floor"] = True
                            floor_metas.append(annotated)
                        collection_results.append(
                            {
                                "collection": collection,
                                "chunks": list(floor_result.chunks),
                                "scores": list(floor_result.scores),
                                "metadatas": floor_metas,
                                "pipeline": floor_result.pipeline,
                                "label": floor_result.label,
                                "mode_label": "recall_floor",
                                "mode_reason": "unscoped dense recall floor",
                                "detail": floor_result.detail,
                                "chunks_retrieved": len(floor_result.chunks),
                                "diagnostics": {},
                            }
                        )
                        recall_floor_added[str(collection)] = len(floor_result.chunks)
        except TimeoutError:
            deadline_exceeded = True
            collection_errors.append(
                {"collection": collection, "error": "retrieval_deadline_exceeded"}
            )
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rag_context: collection retrieval failed",
                collection=collection,
                error=str(exc),
            )
            collection_errors.append({"collection": collection, "error": str(exc)})
    if soft_scope_used:
        metrics["soft_scope_boost"] = {
            "applied": True,
            "scoped_collections": soft_scope_used,
            "filter_keys": sorted(soft_scope_filters),
        }
    if recall_floor_added:
        metrics["recall_floor"] = {
            "applied": True,
            "collections": sorted(recall_floor_added),
            "candidates_added": sum(recall_floor_added.values()),
            "top_n": recall_floor_top_n,
        }
    if expert_fiche_collection:
        metrics["expert_fiche_collection_searched"] = expert_fiche_searched
    metrics["authoritative_document_evidence_dropped"] = authoritative_evidence_dropped
    retrieval_loop_ms = int((time.perf_counter() - retrieval_loop_started_perf) * 1000)

    # For discovery intent keep the fused pool wide enough that every collection's
    # candidates reach the policy rerank/filter — otherwise off-project collections
    # (e.g. BBA120/GEOTEX) flood a small fused pool and the project-code filter then
    # drops the very ARA200 annex/operating-manual docs we want to surface.
    fuse_limit = pool_top_k * max(1, len(collection_results)) if is_discovery else pool_top_k
    chunks, scores, metadatas = _fuse_collection_results(
        collection_results,
        limit=fuse_limit,
    )
    chunks, scores, metadatas, dropped = _enforce_authoritative_document_evidence(
        chunks,
        scores,
        metadatas,
        profile=profile,
    )
    authoritative_evidence_dropped += dropped
    metrics["authoritative_document_evidence_dropped"] = authoritative_evidence_dropped
    raw_chunk_count = len(chunks)
    rerank_started_perf = time.perf_counter()
    chunks, scores, metadatas, duplicates_removed = _dedupe_aligned_results(
        chunks,
        scores,
        metadatas,
    )
    chunks, scores, metadatas = rerank_aligned_with_policy(
        chunks,
        scores,
        metadatas,
        query=retrieval_query,
        policy=retrieval_policy,
    )
    chunks, scores, metadatas, retrieval_constraints = filter_aligned_to_required_terms(
        chunks,
        scores,
        metadatas,
        query=retrieval_query,
        policy=retrieval_policy,
    )
    chunks, scores, metadatas, cross_encoder_diag = await rerank_with_cross_encoder(
        chunks,
        scores,
        metadatas,
        query=retrieval_query,
        latency_profile=profile.get("latency_profile"),
        allow_cross_encoder=bool((profile.get("latency_budget") or {}).get("allow_cross_encoder")),
        top_k=int(profile.get("top_k") or 0),
        is_exempt_metadata=_is_threshold_exempt_metadata,
    )
    metrics.update(cross_encoder_diag)
    chunks, scores, metadatas, threshold_metrics = _apply_similarity_threshold(
        chunks,
        scores,
        metadatas,
        pipeline="multi",
    )
    chunks, scores, metadatas, diversity_metrics = await _diversify_final_context(
        chunks,
        scores,
        metadatas,
        query=retrieval_query,
        latency_profile=profile.get("latency_profile"),
        limit=synthesis_k,
    )
    chunks, scores, metadatas = prioritise_temporary_measure_evidence_aligned(
        chunks,
        scores,
        metadatas,
        question=retrieval_query,
    )
    # The wide fused pool only existed to feed policy rerank / dedupe; trim
    # to the synthesis budget before prompt assembly, cutting the low-quality
    # tail when cross-encoder scores are available.
    chunks, scores, metadatas, compression_diag = _compress_final_context(
        chunks,
        scores,
        metadatas,
        synthesis_k=synthesis_k,
        cross_encoder_status=cross_encoder_diag.get("cross_encoder_status"),
    )
    metrics.update(compression_diag)
    rerank_ms = int((time.perf_counter() - rerank_started_perf) * 1000)
    document_chunk_count = len(chunks)
    exact_metadata_attempted = any(
        bool((item.get("diagnostics") or {}).get("exact_metadata_attempted"))
        for item in collection_results
    )
    exact_metadata_hits = sum(
        int(_int_or_none((item.get("diagnostics") or {}).get("exact_metadata_hits")) or 0)
        for item in collection_results
    )
    exact_metadata_elapsed_ms = sum(
        int(_int_or_none((item.get("diagnostics") or {}).get("exact_metadata_elapsed_ms")) or 0)
        for item in collection_results
    )
    exact_match_required = any(
        bool((item.get("diagnostics") or {}).get("exact_match_required"))
        for item in collection_results
    )
    exact_metadata_diagnostics = (
        {
            "exact_metadata_attempted": exact_metadata_attempted,
            "exact_metadata_hits": exact_metadata_hits,
            "exact_metadata_elapsed_ms": exact_metadata_elapsed_ms,
            "exact_match_required": exact_match_required,
            "exact_match_missing": bool(exact_match_required and exact_metadata_hits <= 0),
        }
        if exact_metadata_attempted
        else {}
    )
    context_build_started_perf = time.perf_counter()
    chunks, scores, metadatas, table_evidence_count = _prepend_table_analysis_context(
        chunks,
        scores,
        metadatas,
        table_analysis,
    )
    chunks, scores, metadatas, document_evidence_count = _prepend_document_analysis_context(
        chunks,
        scores,
        metadatas,
        document_analysis,
    )
    chunks, scores, metadatas, guide_count = _prepend_guide_context(
        chunks,
        scores,
        metadatas,
        guides,
    )
    chunks, scores, metadatas, exact_guardrail_count = _prepend_exact_match_guardrail_context(
        chunks,
        scores,
        metadatas,
        query=retrieval_query,
        policy=retrieval_policy,
        diagnostics=exact_metadata_diagnostics,
        retrieval_filters=retrieval_filters,
    )
    chunks, scores, metadatas, membrane_inbound = _apply_membrane_inbound_evidence(
        chunks,
        scores,
        metadatas,
        profile=profile,
    )
    context_build_ms = int((time.perf_counter() - context_build_started_perf) * 1000)
    duration_ms = int((time.time() - started) * 1000)
    # A collection can appear twice in collection_results (unscoped pass + soft
    # fact-scope pass); de-duplicate so collections_touched reflects collections,
    # not passes.
    touched = list(dict.fromkeys(item["collection"] for item in collection_results))
    sparse_by_collection = {
        str(item["collection"]): item["diagnostics"]
        for item in collection_results
        if item.get("diagnostics")
    }
    sparse_statuses = [
        str((item.get("diagnostics") or {}).get("sparse_status") or "").strip().lower()
        for item in collection_results
        if (item.get("diagnostics") or {}).get("sparse_backend")
    ]
    dense_only = bool(not sparse_statuses or all(status != "ok" for status in sparse_statuses))
    dense_elapsed_values = [
        _int_or_none((item.get("diagnostics") or {}).get("dense_elapsed_ms"))
        for item in collection_results
    ]
    sparse_elapsed_values = [
        _int_or_none((item.get("diagnostics") or {}).get("sparse_elapsed_ms"))
        for item in collection_results
    ]
    dense_elapsed_sum = sum(value for value in dense_elapsed_values if value is not None)
    sparse_elapsed_sum = sum(value for value in sparse_elapsed_values if value is not None)
    metrics.update(
        {
            "duration_ms": duration_ms,
            "retrieval_elapsed_ms": retrieval_loop_ms,
            "dense_elapsed_ms": dense_elapsed_sum
            if any(value is not None for value in dense_elapsed_values)
            else None,
            "sparse_elapsed_ms": sparse_elapsed_sum
            if any(value is not None for value in sparse_elapsed_values)
            else None,
            "rerank_ms": rerank_ms,
            "context_build_ms": context_build_ms,
            "chunks_retrieved": len(chunks),
            "document_chunks_retrieved": document_chunk_count,
            "raw_chunks_retrieved": raw_chunk_count,
            "duplicates_removed": duplicates_removed,
            "knowledge_guides": guide_count,
            "table_analysis_evidence": table_evidence_count,
            "document_analysis_evidence": document_evidence_count,
            "exact_match_guardrail_inserted": bool(exact_guardrail_count),
            "membrane_inbound": membrane_inbound or None,
            "retrieval_constraints": retrieval_constraints,
            **exact_metadata_diagnostics,
            **threshold_metrics,
            **diversity_metrics,
            "candidate_pool_k": profile["candidate_pool_k"],
            "synthesis_k": profile["synthesis_k"],
            "source_display_k": profile["source_display_k"],
            "pipeline": f"multi_{profile['rag_mode'] or 'auto'}",
            "mode_label": "multi_collection",
            "dense_only": dense_only,
            "no_context": len(chunks) == 0,
            "collections_touched": touched,
            "collection_errors": collection_errors,
            "fallback": bool(fallback_reason)
            or deadline_exceeded
            or bool(collection_errors and not chunks),
            "fallback_reason": fallback_reason
            or metrics.get("fallback_reason")
            or ("retrieval_deadline_exceeded" if deadline_exceeded else None),
            "deadline_exceeded": deadline_exceeded,
            "sparse_by_collection": sparse_by_collection,
        }
    )
    selected_sources = _selected_source_trace(chunks, scores, metadatas)
    metrics["selected_sources"] = selected_sources
    metrics["retrieval_trace"] = {
        "trace_id": str(uuid4()),
        "planner": {
            "intent": (metrics.get("retrieval_scope") or {}).get("intent")
            if isinstance(metrics.get("retrieval_scope"), Mapping)
            else None,
            "dense": (metrics.get("retrieval_scope") or {}).get("dense")
            if isinstance(metrics.get("retrieval_scope"), Mapping)
            else None,
            "dense_policy": metrics.get("dense_policy"),
        },
        "scope": metrics.get("retrieval_scope"),
        "policy": metrics.get("retrieval_plan"),
        "layers": (metrics.get("retrieval_plan") or {}).get("layers")
        if isinstance(metrics.get("retrieval_plan"), Mapping)
        else {},
        "selected_sources": selected_sources,
        "failures": [metrics.get("fallback_reason")] if metrics.get("fallback_reason") else [],
    }
    _finalize_retrieval_metrics(metrics)
    return _jsonable(
        {
            "chunks": chunks,
            "scores": scores,
            "metadatas": metadatas,
            "pipeline": metrics["pipeline"],
            "label": profile.get("scope_label") or "Multi-collection",
            "reason": "Knowledge Scope retrieval across multiple collections",
            "detail": f"{len(touched)} collection(s) searched; {len(collection_errors)} error(s)",
            "mode_label": "multi_collection",
            "mode_reason": "Workspace Knowledge Scope",
            "use_hybrid": True,
            "top_k": profile["top_k"],
            "candidate_pool_k": profile["candidate_pool_k"],
            "synthesis_k": profile["synthesis_k"],
            "source_display_k": profile["source_display_k"],
            "query": query,
            "retrieval_query": retrieval_query,
            "retrieval_policy": _retrieval_policy_payload(retrieval_policy, clarification),
            "retrieval_constraints": retrieval_constraints,
            "clarification": clarification,
            "collection": profile["collection"],
            "collections": profile.get("collections") or [],
            "knowledge_scope": profile.get("knowledge_scope"),
            "table_analysis": table_analysis,
            "document_analysis": document_analysis,
            "scope_label": profile.get("scope_label"),
            "vector_db": profile["vector_db"],
            "workspace_slug": profile["workspace_slug"],
            "collection_results": collection_results,
            "collection_errors": collection_errors,
            "collections_touched": touched,
            "metrics": metrics,
            "retrieval_decision_trace": metrics.get("retrieval_decision_trace"),
            "retrieval_scope": metrics.get("retrieval_scope"),
            "retrieval_plan": metrics.get("retrieval_plan"),
            "scope_confidence": metrics.get("scope_confidence"),
            "scope_reason": metrics.get("scope_reason"),
            "dense_policy": metrics.get("dense_policy"),
            "fallback_reason": metrics.get("fallback_reason"),
            "latency_budget": metrics.get("latency_budget"),
            "retrieval_profile": profile.get("retrieval_profile"),
            "retrieval_trace": metrics.get("retrieval_trace"),
            "deep_retrieval_recommended": metrics.get("deep_retrieval_recommended"),
        }
    )


def run_rag_retrieve_context(request: dict[str, Any]) -> dict[str, Any]:
    """Synchronous Celery entrypoint."""
    return asyncio.run(retrieve_rag_context(request))


def dispatch_rag_retrieval_task(request: dict[str, Any], queue: str | None = None):
    from app.workers.tasks import rag_retrieve_context

    return rag_retrieve_context.apply_async(
        args=(_jsonable(request),),
        queue=(queue or "").strip() or settings.celery_task_default_queue,
    )


async def await_rag_retrieval_task(async_result: Any, timeout_seconds: float) -> dict[str, Any]:
    """Wait for a Celery retrieval task without blocking the event loop."""
    loop = asyncio.get_running_loop()

    def _get_result() -> dict[str, Any]:
        return async_result.get(timeout=timeout_seconds)

    return await asyncio.wait_for(
        loop.run_in_executor(None, _get_result),
        timeout=timeout_seconds + 1.0,
    )
