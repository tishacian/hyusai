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


@celery_app.task(
    name="agentium.subflow_run",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def subflow_run(self, child_run_id: str) -> dict:
    """Execute a delegated child run (P4 multi-agent fan-out).

    Thin wrapper over ``run_engine.engine.run_subflow_child`` so the heavy
    engine import stays lazy (keeps worker boot light and avoids import cycles).
    """
    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.services.run_engine.engine import run_subflow_child
    from app.services.run_engine.subflow_orchestration import resume_parent_for_child_sync

    with SessionLocal() as db:
        child = db.query(Run).filter(Run.id == child_run_id).first()
        terminal = child is not None and child.status in {"completed", "failed", "cancelled"}
        terminal_result = {
            "id": child_run_id,
            "status": child.status if child else "missing",
            "error": child.error if child else "run_not_found",
        }
    execution_error = None
    try:
        result = terminal_result if terminal else run_subflow_child(child_run_id)
    except Exception as exc:  # includes Celery soft time limits
        from datetime import datetime

        execution_error = str(exc)[:400]
        with SessionLocal() as db:
            failed = db.query(Run).filter(Run.id == child_run_id).first()
            if failed is not None and failed.status not in {"completed", "failed", "cancelled"}:
                failed.status = "failed"
                failed.error = failed.error or f"subflow_worker_failed:{execution_error}"
                failed.completed_at = datetime.utcnow()
                db.commit()
        result = {"id": child_run_id, "status": "failed", "error": execution_error}
    coordination = resume_parent_for_child_sync(child_run_id)
    if coordination.get("status") == "checkpoint_pending":
        # A very fast child may beat the parent checkpoint commit. Redeliver
        # the same task/child id; terminal child execution is idempotent and no
        # second child can be created because delegation_key is unique.
        raise self.retry(countdown=1, max_retries=5)
    if execution_error is not None:
        raise RuntimeError(execution_error)
    return {**result, "parent_coordination": coordination}


@celery_app.task(
    name="agentium.subflow_crash_probe",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def subflow_crash_probe(self, token: str) -> dict:
    """Protected integration probe proving RabbitMQ worker-loss redelivery.

    It is inert outside the explicit protected-test environment. A dedicated
    solo worker dies on first delivery; a second worker receives the same task
    and writes the redelivery marker. This must never be routed to production.
    """
    import os
    from pathlib import Path
    from uuid import UUID

    if os.getenv("RUN_RABBITMQ_INTEGRATION") != "1":
        raise RuntimeError("subflow crash probe is disabled")
    safe_token = str(UUID(str(token)))
    root = Path(os.getenv("SUBFLOW_CRASH_PROBE_DIR", "/tmp"))
    first = root / f"agentium-p4-crash-{safe_token}.first"
    redelivered = root / f"agentium-p4-crash-{safe_token}.redelivered"
    if not first.exists():
        first.write_text(str(self.request.id), encoding="utf-8")
        os._exit(91)  # dedicated integration worker only
    redelivered.write_text(str(self.request.id), encoding="utf-8")
    return {"status": "redelivered", "task_id": str(self.request.id)}


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
