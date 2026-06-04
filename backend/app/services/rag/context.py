"""Canonical RAG context retrieval contract.

This module isolates the retrieval-only part of the RAG pipeline so it can run
inline in the chat process or out-of-band in a Celery worker without changing
the payload consumed by ``OmniRAGAgent``.
"""
from __future__ import annotations

import asyncio
import copy
import json
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
from app.services.knowledge_guides import effective_guides, guide_context_entries, guide_query_hint
from app.services.knowledge_collections import collection_inventory
from app.services.document_intelligence import DocumentQueryEngine, should_run_document_analysis
from app.services.rag.knowledge_scopes import fallback_scope, resolve_knowledge_scope
from app.services.rag.mode_selector import resolve_retrieval_mode
from app.services.rag.corpus_planner import is_catalogue_query, normalize_latency_profile, plan_corpus
from app.services.rag.pipeline_retrieval import retrieve_for_mode
from app.services.rag.retrieval_profiles import normalize_retrieval_profile_name, retrieval_profile_for
from app.services.rag.retrieval_policy import (
    RetrievalPolicy,
    clarification_from_policy,
    filter_aligned_to_required_terms,
    is_document_discovery_query,
    policy_prompt,
    rerank_aligned_with_policy,
    retrieval_policy_from_guides,
)
from app.services.rag.summary_artifacts import load_summary_index_records
from app.services.rag.vector_store_config import resolve_vector_db_type
from app.services.table_intelligence import TableQueryEngine, should_run_table_analysis
from app.models.workspace import Workspace
from app.models.knowledge_collection import KnowledgeCollection

logger = get_logger(__name__)

_RETRIEVAL_CONTEXT_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

_SPREADSHEET_SHEET_PREFIX_RE = re.compile(
    r"\bspreadsheet\s+sheet:\s*.*?(?=\s+row\s+\d+:)",
    re.IGNORECASE,
)
_FOLLOW_UP_RE = re.compile(
    r"\b("
    r"diff[ée]rentes?|plusieurs|autres?|reste|documents?|valeurs?|"
    r"ce|ces|celle|celui|cela|ça|m[êe]me|ailleurs|compare|compar[ée]r|"
    r"globalement|partout|tous|toutes|ensemble|connais|connues?|"
    r"different|multiple|other|same|those|these|it|them|compare|globally|all|known"
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
_INVENTORY_QUERY_RE = re.compile(
    r"\b("
    r"combien|nombre|count|how\s+many|liste|lister|list|inventaire|inventory|"
    r"typolog(?:ie|y)|types?|formats?|extensions?|donn[ée]es?|data|datasets?|"
    r"disposes?-?tu|available\s+data"
    r")\b",
    re.IGNORECASE,
)
_INVENTORY_OBJECT_RE = re.compile(
    r"\b("
    r"docs?|documents?|sources?|fichiers?|files?|collection|knowledge\s+collection"
    r")\b",
    re.IGNORECASE,
)
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
_TABLE_VALUE_LOOKUP_RE = re.compile(
    r"\b(que\s+vaut|valeur|value|label|table|feuille|sheet|cellule|cell|ligne|row|colonne|column)\b",
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
    text = str(query or "").strip()
    if not text:
        return False
    # "Quels documents parlent de X ?" is a content-discovery query, not an
    # inventory/cardinality question. Keep that path on vector retrieval.
    if _DOCUMENT_DISCOVERY_RE.search(text) or (
        re.search(r"\b(?:quels?|which|what)\b", text, re.IGNORECASE)
        and _CONTENT_SEARCH_HINT_RE.search(text)
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
    if not (_INVENTORY_QUERY_RE.search(text) and _INVENTORY_OBJECT_RE.search(text)):
        return False
    return True


def _explicit_mode(value: Any) -> str | None:
    """Return a real retrieval-mode override, treating UI ``Auto`` as unset."""
    mode = str(value or "").strip().lower()
    if not mode or mode == "auto":
        return None
    return mode


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
        return chunks, scores, metadatas, {
            "score_threshold": threshold,
            "score_threshold_applied": False,
            "score_threshold_filtered": 0,
            "score_threshold_skipped_reason": "disabled" if threshold <= 0 else "empty",
        }

    if str(pipeline or "").strip().lower() != "naive":
        return chunks, scores, metadatas, {
            "score_threshold": threshold,
            "score_threshold_applied": False,
            "score_threshold_filtered": 0,
            "score_threshold_skipped_reason": "non_vector_score_scale",
        }

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
    return kept_chunks, kept_scores, kept_metadatas, {
        "score_threshold": threshold,
        "score_threshold_applied": True,
        "score_threshold_filtered": removed,
        "score_threshold_skipped_reason": None,
    }


def _conversation_history(request: dict[str, Any]) -> list[dict[str, Any]]:
    context = request.get("context") if isinstance(request.get("context"), Mapping) else {}
    history = context.get("conversation_history") if isinstance(context, Mapping) else None
    return [item for item in history if isinstance(item, Mapping)] if isinstance(history, list) else []


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
    if not anchors:
        return query
    return " | ".join([query, "Previous user context:", *reversed(anchors[:2])])


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
    scope = metrics.get("retrieval_scope") if isinstance(metrics.get("retrieval_scope"), Mapping) else {}
    existing_timings = metrics.get("stage_timings") if isinstance(metrics.get("stage_timings"), Mapping) else {}
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
        _first_present(metrics.get("sparse_ms"), metrics.get("sparse_elapsed_ms"), existing_timings.get("sparse_ms"))
    )
    retrieval_ms = _int_or_none(
        _first_present(metrics.get("retrieval_ms"), metrics.get("retrieval_elapsed_ms"), existing_timings.get("retrieval_ms"))
    )
    inventory_ms = _int_or_none(_first_present(metrics.get("inventory_ms"), existing_timings.get("inventory_ms")))
    rerank_ms = _int_or_none(_first_present(metrics.get("rerank_ms"), existing_timings.get("rerank_ms")))
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
    embedding_ms = _int_or_none(_first_present(metrics.get("embedding_ms"), existing_timings.get("embedding_ms")))
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
        "exact_table_hits": _int_or_none(metrics.get("exact_table_hits")),
    }
    metrics["planner_ms"] = planner_ms
    metrics["qdrant_ms"] = qdrant_ms
    metrics["sparse_ms"] = sparse_ms
    metrics["retrieval_ms"] = retrieval_ms
    metrics["stage_timings"] = stage_timings
    metrics["candidate_counts"] = candidate_counts
    trace = metrics.get("retrieval_trace")
    if isinstance(trace, dict):
        trace["timings"] = stage_timings
        trace["candidate_counts"] = candidate_counts
    return metrics


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
            scope["label"] = f"{scope.get('label') or scope.get('key') or 'Knowledge'} + Session docs"
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
    if retrieval_profile == "oracle_fast":
        latency_profile = profile_contract.latency_profile
    elif retrieval_profile == "deep_async":
        latency_profile = profile_contract.latency_profile
    scope_default_mode = scope.get("default_mode")
    if scope_default_mode == "auto":
        scope_default_mode = None
    explicit_rag_mode = (
        _explicit_mode(request.get("rag_pipeline_mode"))
        or _explicit_mode(agent_preferences.get("rag_pipeline_mode"))
    )
    rag_mode = (
        explicit_rag_mode
        or scope_default_mode
        or app_settings.get("ragPipelineMode")
        or app_settings.get("mode")
    )
    if retrieval_profile == "oracle_fast":
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
    app_source_display = None if explicit_top_k and not explicit_budget else app_settings.get("ragSourceDisplayK")
    source_display_k = _int_clamped(
        request.get("source_display_k") or app_source_display,
        source_display_default,
        minimum=1,
        maximum=24,
    )
    synthesis_default = top_k if explicit_top_k and not explicit_budget else max(top_k, source_display_k, 12)
    app_synthesis = None if explicit_top_k and not explicit_budget else app_settings.get("ragSynthesisK")
    synthesis_k = _int_clamped(
        request.get("synthesis_k") or app_synthesis,
        synthesis_default,
        minimum=source_display_k,
        maximum=48,
    )
    candidate_default = top_k if explicit_top_k and not explicit_budget else max(synthesis_k * 4, 40)
    app_candidate_pool = None if explicit_top_k and not explicit_budget else app_settings.get("ragCandidatePoolK")
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
    if retrieval_profile == "oracle_fast":
        top_k = min(top_k, profile_contract.max_top_k)
        source_display_k = min(source_display_k, profile_contract.max_source_display_k)
        synthesis_k = min(max(synthesis_k, source_display_k), profile_contract.max_synthesis_k)
        candidate_pool_k = min(max(candidate_pool_k, synthesis_k), profile_contract.max_candidate_pool_k)
        deadline_seconds = profile_contract.deadline_seconds or deadline_seconds
    collections = scope.get("collection_slugs") or [fallback_collection]
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
        "deep_retrieval": bool(request.get("deep_retrieval") or agent_preferences.get("deep_retrieval")),
        "deadline_seconds": deadline_seconds,
        "latency_budget": {
            "profile": latency_profile,
            "retrieval_profile": retrieval_profile,
            "allow_cross_encoder": profile_contract.allow_cross_encoder,
            "deadline_seconds": deadline_seconds,
            "top_k": top_k,
            "candidate_pool_k": candidate_pool_k,
        },
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


def _retrieval_policy_summary(policy: RetrievalPolicy, clarification: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "enabled": policy.enabled,
        "blocks": len(policy.raw_blocks),
        "aliases": len(policy.aliases),
        "protected_terms": len(policy.protected_terms),
        "facets": len(policy.facets),
        "source_family_rules": len(policy.source_family_rules),
        "require_project_code_match": policy.require_project_code_match,
        "clarification_required": bool(clarification and clarification.get("required")),
    }


def _retrieval_policy_payload(policy: RetrievalPolicy, clarification: dict[str, Any] | None) -> dict[str, Any]:
    return {
        **_retrieval_policy_summary(policy, clarification),
        "prompt": policy_prompt(policy, clarification),
    }


def _table_analysis_for_profile(request: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
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


def _document_analysis_for_profile(request: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any] | None:
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
    filtered_sources = sum(int(item.get("sources_total") or item.get("source_count") or 0) for item in inventories)
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
        return ", ".join(f"{key}: {value}" for key, value in sorted(payload.items(), key=lambda kv: (-kv[1], kv[0])))

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
        filters = item.get("source_filters") if isinstance(item.get("source_filters"), Mapping) else {}
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
            remaining = max(0, int(item.get("sources_total") or 0) - int(item.get("sources_returned") or 0))
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
        query = db.query(KnowledgeCollection).filter(KnowledgeCollection.workspace_id == str(workspace_id))
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
    filtered_sources = sum(int(item.get("sources_total") or item.get("source_count") or 0) for item in inventories)
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
    metadatas = [
        {
            "source_type": "collection_inventory",
            "semantic_type": "collection_inventory",
            "title": "Inventaire Knowledge collection",
            "document_filename": "knowledge-collection-inventory",
            "collection": ", ".join(touched),
            "collection_name": ", ".join(touched),
            "citation_label": "Inventaire Knowledge collection",
        }
    ] if inventories else []
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
            f'{label} = {value}{unit}; '
            f'file="{row.get("document_filename")}", '
            f'sheet="{row.get("sheet_name")}", cell="{row.get("cell_ref")}". '
            f'{row.get("content") or ""}'
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
    return evidence_chunks + chunks, evidence_scores + scores, evidence_metas + metadatas, len(evidence_chunks)


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
            f'{row.get("semantic_type") or "fact"}; '
            f'file="{row.get("document_filename")}", '
            f'locator="{", ".join(locator) or "document"}". '
            f'{row.get("content") or row.get("value_raw") or ""}'
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
    return evidence_chunks + chunks, evidence_scores + scores, evidence_metas + metadatas, len(evidence_chunks)


def _summary_artifact_for_profile(
    profile: dict[str, Any],
    *,
    metrics: dict[str, Any],
    query: str,
) -> dict[str, Any] | None:
    plan = metrics.get("retrieval_plan") if isinstance(metrics.get("retrieval_plan"), Mapping) else {}
    layers = plan.get("layers") if isinstance(plan.get("layers"), Mapping) else {}
    summaries_layer = layers.get("summaries") if isinstance(layers.get("summaries"), Mapping) else {}
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
                ((KnowledgeCollection.slug == collection_ref) | (KnowledgeCollection.id == collection_ref)),
                KnowledgeCollection.workspace_id == workspace_id,
            )
            .first()
        )
        if not collection:
            return None
        scope = metrics.get("retrieval_scope") if isinstance(metrics.get("retrieval_scope"), Mapping) else {}
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
    return evidence_chunks + chunks, evidence_scores + scores, evidence_metas + metadatas, len(evidence_chunks)


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


def _document_diversity_key(metadata: Mapping[str, Any], index: int) -> str:
    for key in ("document_id", "source_id", "document_filename", "filename", "source_path", "object_key"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    return f"_chunk_{index}"


def _diversify_aligned_by_document(
    chunks: list[str],
    scores: list[float],
    metadatas: list[dict[str, Any]],
    *,
    limit: int,
) -> tuple[list[str], list[float], list[dict[str, Any]], dict[str, Any]]:
    target = min(max(0, int(limit or 0)), len(chunks))
    if target <= 1:
        return chunks, scores, metadatas, {
            "document_diversity_applied": False,
            "document_diversity_groups": len(chunks),
            "document_diversity_limit": target,
        }

    buckets: OrderedDict[str, list[int]] = OrderedDict()
    for index, metadata in enumerate(metadatas):
        buckets.setdefault(_document_diversity_key(metadata or {}, index), []).append(index)
    if len(buckets) <= 1:
        return chunks, scores, metadatas, {
            "document_diversity_applied": False,
            "document_diversity_groups": len(buckets),
            "document_diversity_limit": target,
        }

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
    reordered_indices = [*selected, *[index for index in range(len(chunks)) if index not in selected_set]]
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
) -> str | None:
    if not settings.rag_context_cache_enabled:
        return None
    if profile.get("latency_profile") == "deep" or profile.get("deep_retrieval"):
        return None
    scope = metrics.get("retrieval_scope") if isinstance(metrics.get("retrieval_scope"), Mapping) else {}
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
                "id": getattr(guide, "id", None) or (guide.get("id") if isinstance(guide, Mapping) else None),
                "version": getattr(guide, "version", None) or (guide.get("version") if isinstance(guide, Mapping) else None),
            }
            for guide in guides
        ],
    }
    try:
        raw = json.dumps(key_payload, sort_keys=True, default=str)
    except TypeError:
        raw = str(key_payload)
    return sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _get_cached_retrieval_context(cache_key: str | None, *, started: float) -> dict[str, Any] | None:
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


async def retrieve_rag_context(
    request: dict[str, Any],
    *,
    doc_svc: Any | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    """Run retrieval only and return a stable, serialisable context payload."""
    started = time.time()
    profile = get_retrieval_profile(request)
    query = profile["query"]
    guides = _effective_guides_for_profile(profile)
    guide_hint = guide_query_hint(guides)
    retrieval_policy = retrieval_policy_from_guides(guides)
    clarification = clarification_from_policy(query, retrieval_policy)
    table_analysis = _table_analysis_for_profile(request, profile)
    document_analysis = _document_analysis_for_profile(request, profile)
    retrieval_query = query
    collections = profile.get("collections") or [profile["collection"]]
    corpus_plan = None
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
        planned_collections = corpus_plan.retrieval_scope.get("collections") if isinstance(corpus_plan.retrieval_scope, Mapping) else None
        if isinstance(planned_collections, list) and planned_collections:
            profile["collections"] = [str(item) for item in planned_collections if str(item or "").strip()]
            if profile["collections"]:
                profile["collection"] = profile["collections"][0]
                collections = profile["collections"]
        profile["top_k"] = corpus_plan.top_k
        profile["candidate_pool_k"] = corpus_plan.candidate_pool_k
        profile["synthesis_k"] = corpus_plan.synthesis_k
        profile["source_display_k"] = corpus_plan.source_display_k
        profile["latency_profile"] = corpus_plan.latency_profile
        profile["retrieval_filters"] = corpus_plan.filters
        profile["deadline_seconds"] = corpus_plan.deadline_seconds
        profile["latency_budget"] = {
            "profile": corpus_plan.latency_profile,
            "deadline_seconds": corpus_plan.deadline_seconds,
            "top_k": corpus_plan.top_k,
            "candidate_pool_k": corpus_plan.candidate_pool_k,
        }
        profile["_corpus_plan_use_hybrid"] = corpus_plan.use_hybrid
        profile["_corpus_plan_allow_hah_chah"] = corpus_plan.allow_hah_chah
        profile["_corpus_plan_allow_legacy_hybrid"] = corpus_plan.allow_legacy_hybrid
        profile["_corpus_plan_max_variants"] = corpus_plan.max_variants
        profile["_corpus_plan_max_candidates"] = corpus_plan.max_candidates
    retrieval_filters = dict(profile.get("retrieval_filters") or {})
    metrics: dict[str, Any] = {
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
        "fallback_reason": fallback_reason or (corpus_plan.fallback_reason if corpus_plan else None),
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
        "deep_retrieval_recommended": corpus_plan.deep_retrieval_recommended if corpus_plan else False,
    }
    cache_key = _retrieval_context_cache_key(
        profile=profile,
        query=retrieval_query,
        retrieval_filters=retrieval_filters,
        metrics=metrics,
        guides=guides,
    )
    cached_context = _get_cached_retrieval_context(cache_key, started=started)
    if cached_context is not None:
        return cached_context

    if is_collection_inventory_query(query) or (corpus_plan is not None and corpus_plan.intent == "catalogue"):
        inventory_context = _retrieve_collection_inventory_context(
            profile,
            started=started,
            metrics=metrics,
        )
        if inventory_context is not None:
            _set_cached_retrieval_context(cache_key, inventory_context)
            return inventory_context

    if (
        corpus_plan is not None
        and corpus_plan.dense
        and not corpus_plan.filters
        and not retrieval_filters
    ):
        coarse_context = _retrieve_dense_unscoped_coarse_context(
            profile,
            started=started,
            metrics=metrics,
        )
        if coarse_context is not None:
            _set_cached_retrieval_context(cache_key, coarse_context)
            return coarse_context

    if len(collections) > 1 and doc_svc is None:
        return await _retrieve_multi_collection_context(
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
        return {
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
            "collections_touched": [],
            "collection_errors": [{"collection": profile["collection"], "error": str(exc)}],
        }

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
    is_discovery = is_document_discovery_query(retrieval_query)
    pool_top_k = (
        profile["candidate_pool_k"]
        if profile.get("latency_profile") == "fast"
        else _discovery_pool_top_k(profile["candidate_pool_k"], is_discovery)
    )
    synthesis_k = profile["synthesis_k"]
    try:
        retrieval_started_perf = time.perf_counter()
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
                filters=retrieval_filters,
                deadline_seconds=deadline_seconds,
                max_variants=max_variants,
                max_candidates=max_candidates,
                allow_legacy_hybrid=allow_legacy_hybrid,
                retrieval_profile=profile.get("retrieval_profile"),
            ),
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
        return _jsonable(
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

    duration_ms = int((time.time() - started) * 1000)
    raw_chunk_count = len(result.chunks)
    retrieval_diagnostics = {
        key: value for key, value in (getattr(result, "diagnostics", {}) or {}).items() if value is not None
    }
    sparse_status = str(retrieval_diagnostics.get("sparse_status") or "").strip().lower()
    dense_only = bool(
        not use_hybrid
        or (
            retrieval_diagnostics.get("sparse_backend")
            and sparse_status not in {"ok"}
        )
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
    chunks, scores, metadatas, threshold_metrics = _apply_similarity_threshold(
        chunks,
        scores,
        metadatas,
        pipeline=result.pipeline,
    )
    chunks, scores, metadatas, diversity_metrics = _diversify_aligned_by_document(
        chunks,
        scores,
        metadatas,
        limit=synthesis_k,
    )
    if len(chunks) > synthesis_k:
        # The wide candidate pool exists to improve recall before policy rerank /
        # dedupe. Only the synthesis budget is sent to the LLM.
        chunks = chunks[:synthesis_k]
        scores = scores[:synthesis_k]
        metadatas = metadatas[:synthesis_k]
    rerank_ms = int((time.perf_counter() - rerank_started_perf) * 1000)
    document_chunk_count = len(chunks)
    context_build_started_perf = time.perf_counter()
    summary_artifact = _summary_artifact_for_profile(profile, metrics=metrics, query=retrieval_query)
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
    context_build_ms = int((time.perf_counter() - context_build_started_perf) * 1000)
    metrics.update(
        {
            "duration_ms": duration_ms,
            "retrieval_elapsed_ms": retrieval_diagnostics.get("retrieval_elapsed_ms") or retrieval_elapsed_ms,
            "dense_elapsed_ms": retrieval_diagnostics.get("dense_elapsed_ms"),
            "sparse_elapsed_ms": retrieval_diagnostics.get("sparse_elapsed_ms"),
            "rerank_ms": rerank_ms,
            "context_build_ms": context_build_ms,
            "chunks_retrieved": len(chunks),
            "document_chunks_retrieved": document_chunk_count,
            "raw_chunks_retrieved": raw_chunk_count,
            "duplicates_removed": duplicates_removed,
            "knowledge_guides": guide_count,
            "summary_artifact_evidence": summary_artifact_count,
            "summary_artifact_status": (summary_artifact or {}).get("status") if summary_artifact else None,
            "summary_artifact_path": (summary_artifact or {}).get("jsonl_path") if summary_artifact else None,
            "table_analysis_evidence": table_evidence_count,
            "document_analysis_evidence": document_evidence_count,
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
    _set_cached_retrieval_context(cache_key, payload)
    return payload


def _content_key(chunk: Any, meta: dict[str, Any]) -> str:
    document_id = str(meta.get("document_id") or meta.get("id") or "")
    page = str(meta.get("page") or "")
    text = str(chunk or "")[:240]
    return sha1(f"{document_id}|{page}|{text}".encode("utf-8", errors="ignore")).hexdigest()


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
            meta = dict(metadatas[rank] if rank < len(metadatas) and isinstance(metadatas[rank], Mapping) else {})
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
    latency_budget = metrics.get("latency_budget") if isinstance(metrics.get("latency_budget"), Mapping) else {}
    deadline_seconds = float(latency_budget.get("deadline_seconds") or settings.rag_fast_retrieval_deadline_seconds)
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

    retrieval_loop_started_perf = time.perf_counter()
    retrieval_loop_deadline_perf = retrieval_loop_started_perf + max(deadline_seconds, 0.01)
    deadline_exceeded = False
    for collection in profile.get("collections") or []:
        remaining_seconds = retrieval_loop_deadline_perf - time.perf_counter()
        if remaining_seconds <= 0:
            deadline_exceeded = True
            collection_errors.append({"collection": collection, "error": "retrieval_deadline_exceeded"})
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
                    filters=retrieval_filters,
                    deadline_seconds=remaining_seconds,
                    max_variants=max_variants,
                    max_candidates=max_candidates,
                    allow_legacy_hybrid=allow_legacy_hybrid,
                    retrieval_profile=profile.get("retrieval_profile"),
                ),
                timeout=remaining_seconds,
            )
            metadatas = []
            for meta in result.metadatas or []:
                annotated = dict(meta or {})
                annotated["collection"] = collection
                annotated["collection_name"] = collection
                metadatas.append(annotated)
            collection_results.append(
                {
                    "collection": collection,
                    "chunks": result.chunks,
                    "scores": result.scores,
                    "metadatas": metadatas,
                    "pipeline": result.pipeline,
                    "label": result.label,
                    "mode_label": mode_label,
                    "mode_reason": mode_reason,
                    "detail": result.detail,
                    "chunks_retrieved": len(result.chunks),
                    "diagnostics": {
                        key: value
                        for key, value in (getattr(result, "diagnostics", {}) or {}).items()
                        if value is not None
                    },
                }
            )
        except TimeoutError:
            deadline_exceeded = True
            collection_errors.append({"collection": collection, "error": "retrieval_deadline_exceeded"})
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rag_context: collection retrieval failed",
                collection=collection,
                error=str(exc),
            )
            collection_errors.append({"collection": collection, "error": str(exc)})
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
    chunks, scores, metadatas, threshold_metrics = _apply_similarity_threshold(
        chunks,
        scores,
        metadatas,
        pipeline="multi",
    )
    chunks, scores, metadatas, diversity_metrics = _diversify_aligned_by_document(
        chunks,
        scores,
        metadatas,
        limit=synthesis_k,
    )
    if len(chunks) > synthesis_k:
        # The wide fused pool only existed to feed policy rerank / dedupe; trim
        # to the synthesis budget before prompt assembly.
        chunks = chunks[:synthesis_k]
        scores = scores[:synthesis_k]
        metadatas = metadatas[:synthesis_k]
    rerank_ms = int((time.perf_counter() - rerank_started_perf) * 1000)
    document_chunk_count = len(chunks)
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
    context_build_ms = int((time.perf_counter() - context_build_started_perf) * 1000)
    duration_ms = int((time.time() - started) * 1000)
    touched = [item["collection"] for item in collection_results]
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
            "dense_elapsed_ms": dense_elapsed_sum if any(value is not None for value in dense_elapsed_values) else None,
            "sparse_elapsed_ms": sparse_elapsed_sum if any(value is not None for value in sparse_elapsed_values) else None,
            "rerank_ms": rerank_ms,
            "context_build_ms": context_build_ms,
            "chunks_retrieved": len(chunks),
            "document_chunks_retrieved": document_chunk_count,
            "raw_chunks_retrieved": raw_chunk_count,
            "duplicates_removed": duplicates_removed,
            "knowledge_guides": guide_count,
            "table_analysis_evidence": table_evidence_count,
            "document_analysis_evidence": document_evidence_count,
            "retrieval_constraints": retrieval_constraints,
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
            "fallback": bool(fallback_reason) or deadline_exceeded or bool(collection_errors and not chunks),
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


def dispatch_rag_retrieval_task(request: dict[str, Any]):
    from app.workers.tasks import rag_retrieve_context

    return rag_retrieve_context.apply_async(
        args=(_jsonable(request),),
        queue=settings.celery_task_default_queue,
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
