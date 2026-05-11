"""Canonical RAG context retrieval contract.

This module isolates the retrieval-only part of the RAG pipeline so it can run
inline in the chat process or out-of-band in a Celery worker without changing
the payload consumed by ``OmniRAGAgent``.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.services.rag.mode_selector import resolve_retrieval_mode
from app.services.rag.pipeline_retrieval import retrieve_for_mode

logger = get_logger(__name__)


def _int_or_default(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


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
    rag_mode = request.get("rag_pipeline_mode") or (
        request.get("agent_preferences") or {}
    ).get("rag_pipeline_mode")
    top_k = _int_or_default(
        request.get("top_k") or app_settings.get("ragTopK"),
        5,
    )
    return {
        "query": request.get("rewritten_query") or request.get("query") or "",
        "rag_mode": rag_mode,
        "top_k": top_k,
        "collection": app_settings.get("ragCollectionName", "documents"),
        "vector_db": app_settings.get("ragVectorDBType", "faiss"),
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
    metrics: dict[str, Any] = {
        "duration_ms": 0,
        "chunks_retrieved": 0,
        "collections_touched": [profile["collection"]],
        "collection": profile["collection"],
        "vector_db": profile["vector_db"],
        "top_k": profile["top_k"],
        "fallback": bool(fallback_reason),
        "fallback_reason": fallback_reason,
    }

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
    metrics.update(
        {
            "duration_ms": duration_ms,
            "chunks_retrieved": len(result.chunks),
            "pipeline": result.pipeline,
            "mode_label": mode_label,
            "no_context": len(result.chunks) == 0,
        }
    )
    return _jsonable(
        {
            "chunks": result.chunks,
            "scores": result.scores,
            "metadatas": result.metadatas,
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
            "vector_db": profile["vector_db"],
            "workspace_slug": profile["workspace_slug"],
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
