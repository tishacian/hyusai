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
from app.services.rag.knowledge_scopes import fallback_scope, resolve_knowledge_scope
from app.services.rag.mode_selector import resolve_retrieval_mode
from app.services.rag.pipeline_retrieval import retrieve_for_mode
from app.services.rag.vector_store_config import resolve_vector_db_type

logger = get_logger(__name__)

_SPREADSHEET_SHEET_PREFIX_RE = re.compile(
    r"\bspreadsheet\s+sheet:\s*.*?(?=\s+row\s+\d+:)",
    re.IGNORECASE,
)


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
        "query": request.get("rewritten_query") or request.get("query") or "",
        "rag_mode": rag_mode,
        "top_k": top_k,
        "collection": collections[0],
        "collections": collections,
        "knowledge_scope": scope.get("key"),
        "scope_label": scope.get("label"),
        "vector_db": vector_db_type,
        "workspace_slug": request.get("workspace_slug"),
    }


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
    }

    if len(collections) > 1 and doc_svc is None:
        return await _retrieve_multi_collection_context(
            request,
            profile=profile,
            started=started,
            metrics=metrics,
            fallback_reason=fallback_reason,
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
        return {
            "chunks": [],
            "scores": [],
            "metadatas": [],
            "pipeline": "fallback_hybrid",
            "label": "none",
            "reason": "DocumentService unavailable",
            "detail": str(exc),
            "mode_label": "none",
            "mode_reason": "DocumentService unavailable",
            "use_hybrid": True,
            "query": query,
            "metrics": _jsonable(metrics),
            "collections_touched": [],
            "collection_errors": [{"collection": profile["collection"], "error": str(exc)}],
        }

    use_hybrid, mode_label, mode_reason = await resolve_retrieval_mode(
        doc_svc,
        query,
        profile["rag_mode"],
    )
    result = await retrieve_for_mode(
        doc_svc,
        query,
        profile["rag_mode"],
        top_k=profile["top_k"],
        use_hybrid=use_hybrid,
        hah_chah_enabled=settings.rag_hah_chah_enabled,
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
    metrics.update(
        {
            "duration_ms": duration_ms,
            "chunks_retrieved": len(chunks),
            "raw_chunks_retrieved": raw_chunk_count,
            "duplicates_removed": duplicates_removed,
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
            "collection": profile["collection"],
            "collections": collections,
            "knowledge_scope": profile.get("knowledge_scope"),
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
) -> dict[str, Any]:
    query = profile["query"]
    collection_results: list[dict[str, Any]] = []
    collection_errors: list[dict[str, str]] = []

    for collection in profile.get("collections") or []:
        try:
            doc_svc = _document_service_for_profile(profile, collection)
            use_hybrid, mode_label, mode_reason = await resolve_retrieval_mode(
                doc_svc,
                query,
                profile["rag_mode"],
            )
            result = await retrieve_for_mode(
                doc_svc,
                query,
                profile["rag_mode"],
                top_k=profile["top_k"],
                use_hybrid=use_hybrid,
                hah_chah_enabled=settings.rag_hah_chah_enabled,
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

    chunks, scores, metadatas = _fuse_collection_results(
        collection_results,
        limit=profile["top_k"],
    )
    raw_chunk_count = len(chunks)
    chunks, scores, metadatas, duplicates_removed = _dedupe_aligned_results(
        chunks,
        scores,
        metadatas,
    )
    duration_ms = int((time.time() - started) * 1000)
    touched = [item["collection"] for item in collection_results]
    metrics.update(
        {
            "duration_ms": duration_ms,
            "chunks_retrieved": len(chunks),
            "raw_chunks_retrieved": raw_chunk_count,
            "duplicates_removed": duplicates_removed,
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
            "collection": profile["collection"],
            "collections": profile.get("collections") or [],
            "knowledge_scope": profile.get("knowledge_scope"),
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
