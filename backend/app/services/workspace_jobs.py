"""Workspace job ledger with operator-facing lifecycle events."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

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
    status: str = "created",
) -> WorkspaceJob:
    now = datetime.utcnow()
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system_id,
        run_id=run_id,
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
    limit: int = 50,
) -> list[WorkspaceJob]:
    query = db.query(WorkspaceJob).filter(WorkspaceJob.workspace_id == workspace.id)
    if kind:
        query = query.filter(WorkspaceJob.kind == kind)
    if status:
        query = query.filter(WorkspaceJob.status == status)
    return query.order_by(WorkspaceJob.created_at.desc()).limit(max(1, min(limit, 200))).all()


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
    }


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
