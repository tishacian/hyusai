"""Dispatch helpers for Agentium worker jobs."""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.knowledge_collection import WorkerJob
from app.services.knowledge_collections import set_job_task_id, update_job
from app.services.worker_bm25 import run_bm25_rebuild
from app.services.worker_ingest import run_document_ingest_index


def dispatch_worker_job(db: DBSession, job: WorkerJob) -> str | None:
    """Dispatch a WorkerJob and persist the Celery task id when available."""
    if job.kind in {"document_ingest_index", "bm25_rebuild"}:
        if settings.worker_eager_mode:
            set_job_task_id(db, job.id, f"eager:{job.id}")
            db.commit()
            if job.kind == "document_ingest_index":
                run_document_ingest_index(job.id)
            else:
                run_bm25_rebuild(job.id)
            return f"eager:{job.id}"

        try:
            from app.workers.tasks import bm25_rebuild, document_ingest_index

            task = document_ingest_index if job.kind == "document_ingest_index" else bm25_rebuild
            async_result = task.apply_async(
                args=(job.id,),
                queue=settings.celery_task_default_queue,
            )
            set_job_task_id(db, job.id, async_result.id)
            return async_result.id
        except Exception as exc:
            if settings.worker_eager_mode:
                raise
            # Host CLI / dev shells may not have Celery installed; run inline as fallback.
            set_job_task_id(db, job.id, f"eager:{job.id}")
            db.commit()
            if job.kind == "document_ingest_index":
                run_document_ingest_index(job.id)
            else:
                run_bm25_rebuild(job.id)
            return f"eager:{job.id}"
    raise ValueError(f"Unsupported worker job kind: {job.kind}")
