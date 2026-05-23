"""Celery task definitions for Agentium."""
from __future__ import annotations

from app.services.rag.context import run_rag_retrieve_context
from app.services.visual_intelligence import run_visual_capture_job
from app.services.worker_bm25 import run_bm25_rebuild
from app.services.worker_ingest import run_document_ingest_index
from app.workers.celery_app import celery_app


@celery_app.task(name="agentium.document_ingest_index")
def document_ingest_index(job_id: str) -> dict:
    return run_document_ingest_index(job_id)


@celery_app.task(name="agentium.bm25_rebuild")
def bm25_rebuild(job_id: str) -> dict:
    return run_bm25_rebuild(job_id)


@celery_app.task(name="agentium.rag_retrieve_context")
def rag_retrieve_context(payload: dict) -> dict:
    return run_rag_retrieve_context(payload)


@celery_app.task(name="agentium.visual_snapshot_capture")
def visual_snapshot_capture(job_id: str) -> dict:
    return run_visual_capture_job(job_id)
