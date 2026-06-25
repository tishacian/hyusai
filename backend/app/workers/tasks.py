"""Celery task definitions for Agentium."""
from __future__ import annotations

from app.services.rag.context import run_rag_retrieve_context
from app.services.secure_deposit_operations import run_sftp_reconciliation_job
from app.services.visual_intelligence import run_visual_capture_job
from app.services.worker_bm25 import run_bm25_rebuild
from app.services.worker_deep_retrieval import run_deep_retrieval, run_workspace_deep_retrieval
from app.services.worker_ingest import run_document_ingest_index
from app.services.worker_offline_retrieval_artifacts import run_offline_retrieval_artifact_job
from app.workers.celery_app import celery_app


@celery_app.task(name="agentium.document_ingest_index")
def document_ingest_index(job_id: str) -> dict:
    return run_document_ingest_index(job_id)


@celery_app.task(name="agentium.bm25_rebuild")
def bm25_rebuild(job_id: str) -> dict:
    return run_bm25_rebuild(job_id)


@celery_app.task(name="agentium.rag_deep_retrieval")
def rag_deep_retrieval(job_id: str) -> dict:
    return run_deep_retrieval(job_id)


@celery_app.task(name="agentium.workspace_rag_deep_retrieval")
def workspace_rag_deep_retrieval(job_id: str) -> dict:
    return run_workspace_deep_retrieval(job_id)


@celery_app.task(name="agentium.sftp_reconciliation")
def sftp_reconciliation(job_id: str) -> dict:
    return run_sftp_reconciliation_job(job_id)


@celery_app.task(name="agentium.offline_retrieval_artifact")
def offline_retrieval_artifact(job_id: str) -> dict:
    return run_offline_retrieval_artifact_job(job_id)


@celery_app.task(name="agentium.rag_retrieve_context")
def rag_retrieve_context(payload: dict) -> dict:
    return run_rag_retrieve_context(payload)


@celery_app.task(name="agentium.subflow_run")
def subflow_run(child_run_id: str) -> dict:
    """Execute a delegated child run (P4 multi-agent fan-out).

    Thin wrapper over ``run_engine.engine.run_subflow_child`` so the heavy
    engine import stays lazy (keeps worker boot light and avoids import cycles).
    """
    from app.services.run_engine.engine import run_subflow_child

    return run_subflow_child(child_run_id)


@celery_app.task(name="agentium.visual_snapshot_capture")
def visual_snapshot_capture(job_id: str) -> dict:
    return run_visual_capture_job(job_id)


@celery_app.task(name="agentium.refresh_macro_indicators")
def refresh_macro_indicators_task(workspace_slug: str = "sentinel-ci", force: bool = False) -> dict:
    """Periodic refresh (24h) of the macro indicators cache.

    Defaults to the SENTINEL-CI workspace so the demo cockpit always has
    fresh data; can be parameterised by Celery beat for other workspaces.
    """
    from app.db.base import SessionLocal
    from app.models.workspace import Workspace
    from app.services.macro_indicators import fetch_civ_indicators

    with SessionLocal() as db:
        workspace = db.query(Workspace).filter(Workspace.slug == workspace_slug).first()
        if not workspace:
            return {"status": "skipped", "reason": "workspace_not_found", "workspace_slug": workspace_slug}
        result = fetch_civ_indicators(db, workspace, force=bool(force))
    return {"status": "ok", **result}
