"""Dispatch helpers for Agentium worker jobs."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.knowledge_collection import WorkerJob
from app.services.knowledge_collections import set_job_task_id
from app.services.worker_bm25 import run_bm25_rebuild
from app.services.worker_deep_retrieval import run_deep_retrieval
from app.services.worker_ingest import run_document_ingest_index
from app.services.worker_offline_retrieval_artifacts import run_offline_retrieval_artifact_job

logger = get_logger(__name__)


def dispatch_worker_job(db: DBSession, job: WorkerJob, *, allow_inline_fallback: bool = True) -> str | None:
    """Dispatch a WorkerJob and persist the Celery task id when available."""
    offline_kinds = {"sparse_index_rebuild", "summary_index_rebuild", "qdrant_sparse_reindex"}
    if job.kind in {"document_ingest_index", "bm25_rebuild", "rag_deep_retrieval"} | offline_kinds:
        if settings.worker_eager_mode:
            set_job_task_id(db, job.id, f"eager:{job.id}")
            db.commit()
            if job.kind == "document_ingest_index":
                run_document_ingest_index(job.id)
            elif job.kind == "bm25_rebuild":
                run_bm25_rebuild(job.id)
            elif job.kind == "rag_deep_retrieval":
                run_deep_retrieval(job.id)
            else:
                run_offline_retrieval_artifact_job(job.id)
            return f"eager:{job.id}"

        try:
            from app.workers.tasks import (
                bm25_rebuild,
                document_ingest_index,
                offline_retrieval_artifact,
                rag_deep_retrieval,
            )

            if job.kind == "document_ingest_index":
                task = document_ingest_index
            elif job.kind == "bm25_rebuild":
                task = bm25_rebuild
            elif job.kind == "rag_deep_retrieval":
                task = rag_deep_retrieval
            else:
                task = offline_retrieval_artifact
            async_result = task.apply_async(
                args=(job.id,),
                queue=settings.celery_task_default_queue,
            )
            set_job_task_id(db, job.id, async_result.id)
            return async_result.id
        except Exception as exc:
            if settings.worker_eager_mode:
                raise
            if not allow_inline_fallback:
                # A broker may accept the task before the acknowledgement fails.
                # Do not overwrite a worker's running or terminal result.
                db.refresh(job)
                if job.status != "queued":
                    return job.celery_task_id
                result = {
                    **(job.result or {}),
                    "stage": "dispatch_pending",
                    "dispatch_warning": "worker_dispatch_unavailable",
                    "dispatch_error": str(exc),
                }
                db.query(WorkerJob).filter(
                    WorkerJob.id == job.id, WorkerJob.status == "queued",
                ).update({WorkerJob.result: result, WorkerJob.updated_at: datetime.utcnow()}, synchronize_session=False)
                db.commit()
                db.refresh(job)
                logger.warning(
                    "worker dispatch unavailable; leaving job queued",
                    job_id=job.id,
                    kind=job.kind,
                    error=str(exc),
                )
                return None
            # Host CLI / dev shells may not have Celery installed; run inline as fallback.
            set_job_task_id(db, job.id, f"eager:{job.id}")
            db.commit()
            if job.kind == "document_ingest_index":
                run_document_ingest_index(job.id)
            elif job.kind == "bm25_rebuild":
                run_bm25_rebuild(job.id)
            elif job.kind == "rag_deep_retrieval":
                run_deep_retrieval(job.id)
            else:
                run_offline_retrieval_artifact_job(job.id)
            return f"eager:{job.id}"
    raise ValueError(f"Unsupported worker job kind: {job.kind}")
