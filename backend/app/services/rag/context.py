"""Canonical RAG context retrieval contract.

This module isolates the retrieval-only part of the RAG pipeline so it can run
inline in the chat process or out-of-band in a Celery worker without changing
the payload consumed by ``OmniRAGAgent``.
"""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Mapping
from datetime import date, datetime
from hashlib import sha1
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.db.base import SessionLocal
from app.services.knowledge_guides import effective_guides, guide_context_entries, guide_query_hint
from app.services.document_intelligence import DocumentQueryEngine, should_run_document_analysis
from app.services.rag.knowledge_scopes import fallback_scope, resolve_knowledge_scope
from app.services.rag.mode_selector import resolve_retrieval_mode
from app.services.rag.pipeline_retrieval import retrieve_for_mode
from app.services.rag.retrieval_policy import (
    RetrievalPolicy,
    clarification_from_policy,
    filter_aligned_to_required_terms,
    is_document_discovery_query,
    policy_prompt,
    rerank_aligned_with_policy,
    retrieval_policy_from_guides,
)
from app.services.rag.vector_store_config import resolve_vector_db_type
from app.services.table_intelligence import TableQueryEngine, should_run_table_analysis
from app.models.workspace import Workspace

logger = get_logger(__name__)

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


def _explicit_mode(value: Any) -> str | None:
    """Return a real retrieval-mode override, treating UI ``Auto`` as unset."""
    mode = str(value or "").strip().lower()
    if not mode or mode == "auto":
        return None
    return mode


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


def get_retrieval_profile(request: dict[str, Any]) -> dict[str, Any]:
    """Resolve retrieval settings that do not require a live vector search."""
    app_settings = get_resolved_settings(
        workspace_id=request.get("workspace_id"),
        capability_id=request.get("capability_id"),
        system_id=request.get("system_id"),
    )
    context_collection = str(request.get("context_collection") or "").strip()
    context_mode = str(request.get("context_mode") or "").strip().lower()
    fallback_collection = context_collection or app_settings.get("ragCollectionName", "documents")
    if context_collection and not request.get("knowledge_scope"):
        context_key = str(request.get("context_id") or context_collection)
        scope = fallback_scope(
            context_collection,
            key=f"context_{sha1(context_key.encode('utf-8')).hexdigest()[:10]}",
        )
        scope["label"] = "Selected context"
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
    scope_default_mode = scope.get("default_mode")
    if scope_default_mode == "auto":
        scope_default_mode = None
    agent_preferences = request.get("agent_preferences") or {}
    rag_mode = (
        _explicit_mode(request.get("rag_pipeline_mode"))
        or _explicit_mode(agent_preferences.get("rag_pipeline_mode"))
        or scope_default_mode
        or app_settings.get("ragPipelineMode")
        or app_settings.get("mode")
    )
    top_k = _int_or_default(
        request.get("top_k") or scope.get("top_k") or app_settings.get("ragTopK"),
        5,
    )
    collections = scope.get("collection_slugs") or [fallback_collection]
    vector_db_type = resolve_vector_db_type(app_settings)
    return {
        "query": _history_augmented_query(request),
        "rag_mode": rag_mode,
        "top_k": top_k,
        "collection": collections[0],
        "collections": collections,
        "knowledge_scope": scope.get("key"),
        "scope_label": scope.get("label"),
        "vector_db": vector_db_type,
        "workspace_id": request.get("workspace_id"),
        "workspace_slug": request.get("workspace_slug"),
    }


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
    metrics: dict[str, Any] = {
        "duration_ms": 0,
        "chunks_retrieved": 0,
        "scope": profile.get("knowledge_scope"),
        "scope_label": profile.get("scope_label"),
        "collections_touched": collections,
        "collection": profile["collection"],
        "collections": collections,
        "vector_db": profile["vector_db"],
        "top_k": profile["top_k"],
        "fallback": bool(fallback_reason),
        "fallback_reason": fallback_reason,
        "knowledge_guides": len(guides),
        "query_expanded_with_guides": bool(guides),
        "knowledge_guide_hint_chars": len(guide_hint),
        "retrieval_policy": _retrieval_policy_summary(retrieval_policy, clarification),
        "retrieval_policy_enabled": retrieval_policy.enabled,
        "retrieval_policy_clarification": bool(clarification and clarification.get("required")),
        "retrieval_constraints": {},
    }

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
            doc_svc = build_document_service(request)
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
    )
    is_discovery = is_document_discovery_query(retrieval_query)
    pool_top_k = _discovery_pool_top_k(profile["top_k"], is_discovery)
    result = await retrieve_for_mode(
        doc_svc,
        retrieval_query,
        profile["rag_mode"],
        top_k=pool_top_k,
        use_hybrid=use_hybrid,
        hah_chah_enabled=settings.rag_hah_chah_enabled,
        query_hints=guide_hint,
        retrieval_policy=retrieval_policy,
    )

    duration_ms = int((time.time() - started) * 1000)
    raw_chunk_count = len(result.chunks)
    metadatas = []
    for meta in result.metadatas or []:
        annotated = dict(meta or {})
        annotated["collection"] = profile["collection"]
        annotated["collection_name"] = profile["collection"]
        metadatas.append(annotated)
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
    if is_discovery:
        # Wide pool was only needed to feed the policy rerank above; trim back to
        # the intended top_k so the returned payload matches the non-discovery size.
        chunks = chunks[: profile["top_k"]]
        scores = scores[: profile["top_k"]]
        metadatas = metadatas[: profile["top_k"]]
    document_chunk_count = len(chunks)
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
    metrics.update(
        {
            "duration_ms": duration_ms,
            "chunks_retrieved": len(chunks),
            "document_chunks_retrieved": document_chunk_count,
            "raw_chunks_retrieved": raw_chunk_count,
            "duplicates_removed": duplicates_removed,
            "knowledge_guides": guide_count,
            "table_analysis_evidence": table_evidence_count,
            "document_analysis_evidence": document_evidence_count,
            "retrieval_constraints": retrieval_constraints,
            "pipeline": result.pipeline,
            "mode_label": mode_label,
            "no_context": len(chunks) == 0,
        }
    )
    return _jsonable(
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
            "collections_touched": [profile["collection"]],
            "collection_errors": [],
        }
    )


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
    pool_top_k = _discovery_pool_top_k(profile["top_k"], is_discovery)
    collection_results: list[dict[str, Any]] = []
    collection_errors: list[dict[str, str]] = []

    for collection in profile.get("collections") or []:
        try:
            doc_svc = _document_service_for_profile(profile, collection)
            use_hybrid, mode_label, mode_reason = await resolve_retrieval_mode(
                doc_svc,
                retrieval_query,
                profile["rag_mode"],
            )
            result = await retrieve_for_mode(
                doc_svc,
                retrieval_query,
                profile["rag_mode"],
                top_k=pool_top_k,
                use_hybrid=use_hybrid,
                hah_chah_enabled=settings.rag_hah_chah_enabled,
                query_hints=guide_hint,
                retrieval_policy=retrieval_policy,
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
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "rag_context: collection retrieval failed",
                collection=collection,
                error=str(exc),
            )
            collection_errors.append({"collection": collection, "error": str(exc)})

    # For discovery intent keep the fused pool wide enough that every collection's
    # candidates reach the policy rerank/filter — otherwise off-project collections
    # (e.g. BBA120/GEOTEX) flood a small fused pool and the project-code filter then
    # drops the very ARA200 annex/operating-manual docs we want to surface.
    fuse_limit = pool_top_k * max(1, len(collection_results)) if is_discovery else profile["top_k"]
    chunks, scores, metadatas = _fuse_collection_results(
        collection_results,
        limit=fuse_limit,
    )
    raw_chunk_count = len(chunks)
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
    if is_discovery:
        # The wide fused pool only existed to feed the policy rerank; trim back to
        # the intended top_k so the returned size matches non-discovery queries.
        chunks = chunks[: profile["top_k"]]
        scores = scores[: profile["top_k"]]
        metadatas = metadatas[: profile["top_k"]]
    document_chunk_count = len(chunks)
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
    duration_ms = int((time.time() - started) * 1000)
    touched = [item["collection"] for item in collection_results]
    metrics.update(
        {
            "duration_ms": duration_ms,
            "chunks_retrieved": len(chunks),
            "document_chunks_retrieved": document_chunk_count,
            "raw_chunks_retrieved": raw_chunk_count,
            "duplicates_removed": duplicates_removed,
            "knowledge_guides": guide_count,
            "table_analysis_evidence": table_evidence_count,
            "document_analysis_evidence": document_evidence_count,
            "retrieval_constraints": retrieval_constraints,
            "pipeline": f"multi_{profile['rag_mode'] or 'auto'}",
            "mode_label": "multi_collection",
            "no_context": len(chunks) == 0,
            "collections_touched": touched,
            "collection_errors": collection_errors,
            "fallback": bool(fallback_reason) or bool(collection_errors and not chunks),
            "fallback_reason": fallback_reason,
        }
    )
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
