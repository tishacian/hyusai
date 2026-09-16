"""Workspace job ledger with operator-facing lifecycle events."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WORKSPACE_JOB_STATUSES, WorkspaceJob
from app.services.audit_logger import emit_audit_event


def create_workspace_job(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    kind: str,
    title: str,
    input_ref: Optional[dict[str, Any]] = None,
    system_id: Optional[str] = None,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    parent_message_id: Optional[str] = None,
    message_id: Optional[str] = None,
    status: str = "created",
) -> WorkspaceJob:
    now = datetime.utcnow()
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system_id,
        run_id=run_id,
        session_id=session_id,
        collection_id=collection_id,
        parent_message_id=parent_message_id,
        message_id=message_id,
        kind=kind,
        title=title or kind,
        status=status if status in WORKSPACE_JOB_STATUSES else "created",
        progress=0,
        stage="created",
        input_ref=input_ref or {},
        result={},
        events=[],
        created_by_user_id=user.id if user else None,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.flush()
    transition_job(db, workspace, job, job.status, progress=0, stage="created", user=user, audit=False)
    _audit(db, workspace, user, "workspace_job.created", job)
    return job


def list_workspace_jobs(
    db: DBSession,
    workspace: Workspace,
    *,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    statuses: Optional[list[str]] = None,
    session_id: Optional[str] = None,
    session_ids: Optional[list[str]] = None,
    created_by_user_id: Optional[str] = None,
    limit: int = 50,
) -> list[WorkspaceJob]:
    query = db.query(WorkspaceJob).filter(WorkspaceJob.workspace_id == workspace.id)
    if kind:
        query = query.filter(WorkspaceJob.kind == kind)
    if statuses:
        query = query.filter(WorkspaceJob.status.in_(statuses))
    elif status:
        query = query.filter(WorkspaceJob.status == status)
    if session_id:
        query = query.filter(WorkspaceJob.session_id == session_id)
    if created_by_user_id and session_ids:
        query = query.filter(
            or_(
                WorkspaceJob.created_by_user_id == created_by_user_id,
                WorkspaceJob.session_id.in_(session_ids),
            )
        )
    elif created_by_user_id:
        query = query.filter(WorkspaceJob.created_by_user_id == created_by_user_id)
    elif session_ids:
        query = query.filter(WorkspaceJob.session_id.in_(session_ids))
    return query.order_by(WorkspaceJob.updated_at.desc(), WorkspaceJob.created_at.desc()).limit(max(1, min(limit, 200))).all()


def get_workspace_job(db: DBSession, workspace: Workspace, job_id: str) -> WorkspaceJob:
    job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id, WorkspaceJob.workspace_id == workspace.id).first()
    if not job:
        raise LookupError("workspace_job_not_found")
    return job


def transition_job(
    db: DBSession,
    workspace: Workspace,
    job: WorkspaceJob,
    status: str,
    *,
    progress: Optional[int] = None,
    stage: Optional[str] = None,
    result: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
    user: Optional[User] = None,
    audit: bool = True,
) -> WorkspaceJob:
    now = datetime.utcnow()
    if status not in WORKSPACE_JOB_STATUSES:
        status = "running"
    job.status = status
    if progress is not None:
        job.progress = max(0, min(100, int(progress)))
    if stage:
        job.stage = stage
    if result is not None:
        job.result = result
    if error:
        job.error = error
    if status == "queued" and not job.queued_at:
        job.queued_at = now
    if status == "running" and not job.started_at:
        job.started_at = now
    if status in {"completed", "failed", "cancelled"}:
        job.completed_at = now
        if status == "completed":
            job.progress = 100
    job.updated_at = now
    event = {
        "seq": len(job.events or []) + 1,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "error": job.error,
        "at": now.isoformat(),
    }
    job.events = [*(job.events or []), event]
    db.flush()
    if audit:
        _audit(db, workspace, user, f"workspace_job.{status}", job, details={"stage": job.stage, "progress": job.progress})
    return job


def serialize_job(job: WorkspaceJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "system_id": job.system_id,
        "run_id": job.run_id,
        "session_id": job.session_id,
        "collection_id": job.collection_id,
        "parent_message_id": job.parent_message_id,
        "message_id": job.message_id,
        "kind": job.kind,
        "title": job.title,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "error": job.error,
        "input_ref": job.input_ref or {},
        "result": job.result or {},
        "events": job.events or [],
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "poll_url": f"/workspace-jobs/{job.id}",
    }


def set_workspace_job_task_id(db: DBSession, job_id: str, task_id: str) -> None:
    job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id).first()
    if not job:
        return
    input_ref = dict(job.input_ref or {})
    input_ref["celery_task_id"] = task_id
    job.input_ref = input_ref
    job.updated_at = datetime.utcnow()
    db.flush()


def dispatch_workspace_job(db: DBSession, workspace: Workspace, job: WorkspaceJob, *, allow_inline_fallback: bool = True) -> str | None:
    """Dispatch a product-facing WorkspaceJob and persist its task id in input_ref."""
    if job.kind in {"run_evaluation", "evaluation_campaign", "evaluation_generation", "evaluation_raget", "brd_generation"}:
        from app.workers.tasks import run_evaluation, evaluation_campaign, evaluation_generation, brd_generation
        from app.core.config import settings
        task = {"run_evaluation": run_evaluation, "evaluation_campaign": evaluation_campaign, "evaluation_generation": evaluation_generation, "evaluation_raget": evaluation_generation, "brd_generation": brd_generation}[job.kind]
        try:
            if settings.worker_eager_mode:
                set_workspace_job_task_id(db, job.id, f"eager:{job.id}")
                db.commit()
                task.run(job.id)
                return f"eager:{job.id}"
            result = task.apply_async(args=(job.id,), queue=settings.celery_task_default_queue)
            set_workspace_job_task_id(db, job.id, result.id)
            return result.id
        except Exception:
            return None
    if job.kind not in {"rag_deep_retrieval", "sftp_reconciliation"}:
        raise ValueError(f"Unsupported workspace job kind: {job.kind}")
    from app.core.config import settings
    from app.core.logging import get_logger
    from app.services.secure_deposit_operations import run_sftp_reconciliation_job
    from app.services.worker_deep_retrieval import run_workspace_deep_retrieval

    logger = get_logger(__name__)
    if settings.worker_eager_mode:
        task_id = f"eager:{job.id}"
        set_workspace_job_task_id(db, job.id, task_id)
        db.commit()
        if job.kind == "sftp_reconciliation":
            run_sftp_reconciliation_job(job.id)
        else:
            run_workspace_deep_retrieval(job.id)
        return task_id

    try:
        from app.workers.tasks import sftp_reconciliation, workspace_rag_deep_retrieval

        task = sftp_reconciliation if job.kind == "sftp_reconciliation" else workspace_rag_deep_retrieval
        async_result = task.apply_async(
            args=(job.id,),
            queue=settings.celery_task_default_queue,
        )
        set_workspace_job_task_id(db, job.id, async_result.id)
        return async_result.id
    except Exception as exc:
        if settings.worker_eager_mode:
            raise
        if not allow_inline_fallback:
            input_ref = dict(job.input_ref or {})
            input_ref["dispatch_warning"] = "workspace_job_dispatch_unavailable"
            input_ref["dispatch_error"] = str(exc)
            job.input_ref = input_ref
            transition_job(
                db,
                workspace,
                job,
                "queued",
                progress=job.progress,
                stage="dispatch_pending",
                user=None,
            )
            db.commit()
            logger.warning(
                "workspace job dispatch unavailable; leaving job queued",
                job_id=job.id,
                kind=job.kind,
                error=str(exc),
            )
            return None
        task_id = f"eager:{job.id}"
        set_workspace_job_task_id(db, job.id, task_id)
        db.commit()
        if job.kind == "sftp_reconciliation":
            run_sftp_reconciliation_job(job.id)
        else:
            run_workspace_deep_retrieval(job.id)
        return task_id


def _actor(user: Optional[User]) -> str:
    if not user:
        return "system"
    return user.email or user.username or user.id


def _audit(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    event_type: str,
    job: WorkspaceJob,
    details: Optional[dict[str, Any]] = None,
) -> None:
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=event_type,
        actor=_actor(user),
        details={
            "job_id": job.id,
            "kind": job.kind,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            **(details or {}),
        },
    )
