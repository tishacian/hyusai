"""Celery task definitions for Agentium."""
from __future__ import annotations

from app.services.worker_ingest import run_document_ingest_index
from app.workers.celery_app import celery_app


@celery_app.task(name="agentium.document_ingest_index")
def document_ingest_index(job_id: str) -> dict:
    return run_document_ingest_index(job_id)
