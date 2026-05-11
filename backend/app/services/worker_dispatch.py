"""Dispatch helpers for Agentium worker jobs."""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.knowledge_collection import WorkerJob
from app.services.knowledge_collections import set_job_task_id, update_job
from app.services.worker_ingest import run_document_ingest_index


def dispatch_worker_job(db: DBSession, job: WorkerJob) -> str | None:
    """Dispatch a WorkerJob and persist the Celery task id when available."""
    if job.kind == "document_ingest_index":
        if settings.worker_eager_mode:
            set_job_task_id(db, job.id, f"eager:{job.id}")
            db.commit()
            run_document_ingest_index(job.id)
            return f"eager:{job.id}"

        try:
            from app.workers.tasks import document_ingest_index

            async_result = document_ingest_index.apply_async(
                args=(job.id,),
                queue=settings.celery_task_default_queue,
            )
            set_job_task_id(db, job.id, async_result.id)
            return async_result.id
        except Exception as exc:
            update_job(db, job.id, status="failed", progress=100, error=str(exc))
            db.commit()
            raise
    raise ValueError(f"Unsupported worker job kind: {job.kind}")
