"""Worker for asynchronous deep RAG retrieval jobs."""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.knowledge_collection import WorkerJob
from app.services.knowledge_collections import update_job
from app.services.rag.context import retrieve_rag_context

logger = get_logger(__name__)

_MAX_SOURCE_PREVIEW = 12
_MAX_SOURCE_SNIPPET_CHARS = 1200
_PREVIEW_METADATA_KEYS = (
    "chunk_id",
    "chunk_index",
    "document_id",
    "document_title",
    "document_filename",
    "filename",
    "source",
    "source_name",
    "collection",
    "collection_name",
    "collection_slug",
    "source_kind",
    "extension",
    "project_code",
    "archive_name",
    "language",
    "status",
    "page",
    "page_number",
    "section",
    "section_title",
)


def _compact_text(value: Any, *, max_chars: int = _MAX_SOURCE_SNIPPET_CHARS) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _clean_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None and value != ""}


def _safe_float(value: Any) -> float | None:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _source_label(meta: Any) -> str | None:
    if not isinstance(meta, dict):
        return None
    for key in (
        "document_title",
        "document_filename",
        "filename",
        "source",
        "source_name",
        "document_id",
    ):
        value = meta.get(key)
        if value:
            return str(value)
    return None


def _compact_deep_retrieval_sources(
    context: dict[str, Any],
    *,
    limit: int = _MAX_SOURCE_PREVIEW,
) -> list[dict[str, Any]]:
    chunks = context.get("chunks") if isinstance(context.get("chunks"), list) else []
    scores = context.get("scores") if isinstance(context.get("scores"), list) else []
    metadatas = context.get("metadatas") if isinstance(context.get("metadatas"), list) else []
    collection = context.get("collection") if context.get("collection") else None
    preview: list[dict[str, Any]] = []
    for index, raw_chunk in enumerate(chunks[: max(0, limit)]):
        meta = metadatas[index] if index < len(metadatas) and isinstance(metadatas[index], dict) else {}
        score = _safe_float(scores[index]) if index < len(scores) else None
        document_id = meta.get("document_id") or meta.get("id")
        filename = meta.get("document_filename") or meta.get("filename") or meta.get("source") or meta.get("source_name")
        title = meta.get("document_title") or meta.get("title") or filename or document_id
        snippet = _compact_text(raw_chunk)
        metadata = {key: meta.get(key) for key in _PREVIEW_METADATA_KEYS if meta.get(key) is not None}
        preview.append(
            _clean_dict(
                {
                    "id": meta.get("chunk_id") or f"{document_id or 'deep'}:{index}",
                    "document_id": str(document_id) if document_id else None,
                    "title": str(title) if title else None,
                    "filename": str(filename) if filename else None,
                    "snippet": snippet,
                    "content": snippet,
                    "score": score,
                    "collection": meta.get("collection") or meta.get("collection_slug") or collection,
                    "collection_name": meta.get("collection_name") or meta.get("collection") or collection,
                    "page": meta.get("page") or meta.get("page_number"),
                    "metadata": metadata,
                }
            )
        )
    return preview


def _summarize_deep_retrieval_context(context: dict[str, Any]) -> dict[str, Any]:
    chunks = context.get("chunks") if isinstance(context.get("chunks"), list) else []
    scores = context.get("scores") if isinstance(context.get("scores"), list) else []
    metadatas = context.get("metadatas") if isinstance(context.get("metadatas"), list) else []
    metrics = context.get("metrics") if isinstance(context.get("metrics"), dict) else {}
    source_counts: dict[str, int] = {}
    for meta in metadatas:
        label = _source_label(meta)
        if not label:
            continue
        source_counts[label] = source_counts.get(label, 0) + 1
    top_sources = [
        {"label": label, "chunks": count}
        for label, count in sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]
    top_score: float | None = None
    if scores:
        try:
            top_score = round(float(scores[0]), 4)
        except (TypeError, ValueError):
            top_score = None
    return {
        "chunks_retrieved": len(chunks),
        "sources_returned": len(source_counts),
        "top_sources": top_sources,
        "top_score": top_score,
        "sources_preview_count": min(len(chunks), _MAX_SOURCE_PREVIEW),
        "pipeline": context.get("pipeline"),
        "mode_label": context.get("mode_label") or context.get("label"),
        "collection": context.get("collection"),
        "dense_policy": context.get("dense_policy") or metrics.get("dense_policy"),
        "retrieval_plan": context.get("retrieval_plan") or metrics.get("retrieval_plan"),
        "scope_confidence": context.get("scope_confidence") or metrics.get("scope_confidence"),
        "fallback_reason": context.get("fallback_reason") or metrics.get("fallback_reason"),
        "duration_ms": metrics.get("duration_ms"),
    }


async def _run_deep_retrieval_async(job_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
        if not job:
            raise ValueError(f"Deep retrieval job {job_id!r} not found")
        initial_result = dict(job.result or {})
        payload = dict(initial_result.get("request") or {})
        if not payload:
            raise ValueError(f"Deep retrieval job {job_id!r} has no request payload")
        payload["latency_profile"] = "deep"
        payload["deep_retrieval"] = True
        job_metadata = {key: value for key, value in initial_result.items() if key not in {"retrieval_context", "summary"}}
        prepare_result = {
            **job_metadata,
            "request": payload,
            "stage": "deep_prepare",
            "status": "running",
        }
        update_job(db, job_id, status="running", progress=10, result=prepare_result, stage="deep_prepare")
        db.commit()

    try:
        update_payload = {**job_metadata, "request": payload, "stage": "deep_retrieve", "status": "running"}
        with SessionLocal() as db:
            update_job(db, job_id, progress=35, result=update_payload, stage="deep_retrieve")
            db.commit()
        context = await asyncio.wait_for(
            retrieve_rag_context(payload),
            timeout=float(settings.rag_deep_retrieval_deadline_seconds),
        )
        sources_preview = _compact_deep_retrieval_sources(context)
        summary = _summarize_deep_retrieval_context(context)
        summarize_payload = {
            **job_metadata,
            "request": payload,
            "sources_preview": sources_preview,
            "summary": summary,
            "stage": "deep_summarize",
            "status": "running",
        }
        with SessionLocal() as db:
            update_job(db, job_id, progress=85, result=summarize_payload, stage="deep_summarize")
            db.commit()
        result = {
            **job_metadata,
            "request": payload,
            "retrieval_context": context,
            "retrieval_context_available": True,
            "sources_preview": sources_preview,
            "summary": summary,
            "stage": "deep_completed",
            "status": "completed",
        }
        with SessionLocal() as db:
            update_job(db, job_id, status="completed", progress=100, result=result, stage="deep_completed")
            db.commit()
        return result
    except asyncio.TimeoutError:
        partial_result = job_metadata.get("partial_result") if isinstance(job_metadata.get("partial_result"), dict) else {}
        retrieval_summary = (
            partial_result.get("retrieval_summary")
            if isinstance(partial_result.get("retrieval_summary"), dict)
            else {}
        )
        sources_preview = (
            partial_result.get("sources_preview")
            if isinstance(partial_result.get("sources_preview"), list)
            else []
        )
        summary = {
            "chunks_retrieved": retrieval_summary.get("chunks_retrieved") or 0,
            "sources_returned": None,
            "top_sources": [],
            "top_score": None,
            "pipeline": retrieval_summary.get("dense_policy") or job_metadata.get("dense_policy"),
            "mode_label": "deep_timeout",
            "collection": payload.get("collection") or payload.get("context_collection"),
            "dense_policy": retrieval_summary.get("dense_policy") or job_metadata.get("dense_policy"),
            "scope_confidence": retrieval_summary.get("scope_confidence") or job_metadata.get("scope_confidence"),
            "fallback_reason": "deep_retrieval_deadline_exceeded",
            "duration_ms": int(float(settings.rag_deep_retrieval_deadline_seconds) * 1000),
            "partial": True,
        }
        result = {
            **job_metadata,
            "request": payload,
            "stage": "deep_timeout",
            "status": "completed_partial",
            "retrieval_context_available": False,
            "sources_preview": sources_preview,
            "summary": summary,
            "fallback_reason": "deep_retrieval_deadline_exceeded",
            "warning": "Deep retrieval reached its latency budget; showing the partial fast result.",
        }
        with SessionLocal() as db:
            update_job(
                db,
                job_id,
                status="completed",
                progress=100,
                result=result,
                stage="deep_timeout",
            )
            db.commit()
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("deep retrieval worker failed", job_id=job_id, error=str(exc))
        result = {
            **job_metadata,
            "request": payload,
            "stage": "deep_failed",
            "status": "failed",
            "error": str(exc),
        }
        with SessionLocal() as db:
            update_job(db, job_id, status="failed", progress=100, error=str(exc), result=result, stage="deep_failed")
            db.commit()
        return result


def run_deep_retrieval(job_id: str) -> dict[str, Any]:
    return asyncio.run(_run_deep_retrieval_async(job_id))
