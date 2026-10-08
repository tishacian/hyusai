"""Workspace job lifecycle API."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import is_admin_template
from app.db.base import SessionLocal, get_db
from app.models.user import Session as ChatSession, User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services.workspace_jobs import (
    create_workspace_job,
    get_workspace_job,
    list_workspace_jobs,
    serialize_job,
    transition_job,
)


router = APIRouter()


def _is_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> bool:
    if user.role == "admin":
        return True
    membership = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id)
        .first()
    )
    return bool(membership and is_admin_template(membership.role_template, membership.role))


def _user_session_ids(db: DBSession, user: User, workspace: Workspace) -> list[str]:
    return [
        row.id
        for row in (
            db.query(ChatSession.id)
            .filter(
                ChatSession.workspace_id == workspace.id,
                ChatSession.user_id == user.id,
                ChatSession.status != "deleted",
            )
            .all()
        )
    ]


def _can_access_job(db: DBSession, job: WorkspaceJob, user: User, workspace: Workspace) -> bool:
    if job.kind == "brd_generation":
        from app.models.brd_document import BrdDocument
        from app.services.skills_registry.brd_generation import authorized_catalog
        if job.created_by_user_id != user.id:
            return False
        document = db.query(BrdDocument).filter_by(id=(job.input_ref or {}).get("document_id"), workspace_id=workspace.id).first()
        if document is None:
            return False
        try:
            authorized_catalog(db, workspace, user, (job.input_ref.get("request") or {}).get("skill_slugs", []))
        except HTTPException:
            return False
        return True
    if _is_workspace_admin(db, user, workspace):
        return True
    if job.created_by_user_id == user.id:
        return True
    if job.session_id:
        return (
            db.query(ChatSession.id)
            .filter(
                ChatSession.id == job.session_id,
                ChatSession.workspace_id == workspace.id,
                ChatSession.user_id == user.id,
                ChatSession.status != "deleted",
            )
            .first()
            is not None
        )
    return False


class WorkspaceJobCreate(BaseModel):
    kind: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=255)
    input_ref: dict[str, Any] = Field(default_factory=dict)
    system_id: Optional[str] = None
    run_id: Optional[str] = None


class WorkspaceJobTransition(BaseModel):
    status: str
    progress: Optional[int] = None
    stage: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


@router.get("/")
async def jobs_list(
    kind: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    include_admin: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    statuses = [item.strip() for item in str(status or "").split(",") if item.strip()]
    admin = include_admin and _is_workspace_admin(db, user, workspace)
    session_ids = None if admin else _user_session_ids(db, user, workspace)
    if not admin and session_id and session_id not in set(session_ids or []):
        return {"jobs": []}
    rows = list_workspace_jobs(
        db,
        workspace,
        kind=kind,
        statuses=statuses or None,
        session_id=session_id,
        session_ids=session_ids,
        created_by_user_id=None if admin else user.id,
        limit=limit,
    )
    return {"jobs": [serialize_job(row) for row in rows if row.kind != "brd_generation" or _can_access_job(db, row, user, workspace)]}


@router.post("/")
async def jobs_create(
    body: WorkspaceJobCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    from app.services.mlops_jobs import SERVER_MANAGED_JOB_KINDS

    if body.kind in SERVER_MANAGED_JOB_KINDS:
        raise HTTPException(403, "This job kind is managed by its service")
    job = create_workspace_job(
        db,
        workspace,
        user,
        kind=body.kind,
        title=body.title,
        input_ref=body.input_ref,
        system_id=body.system_id,
        run_id=body.run_id,
        status="queued",
    )
    db.commit()
    return serialize_job(job)


@router.get("/{job_id}")
async def jobs_detail(
    job_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        job = get_workspace_job(db, workspace, job_id)
        if not _can_access_job(db, job, user, workspace):
            raise LookupError("workspace_job_not_found")
        return serialize_job(job)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Workspace job not found") from exc


@router.post("/{job_id}/transition")
async def jobs_transition(
    job_id: str,
    body: WorkspaceJobTransition,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        job = get_workspace_job(db, workspace, job_id)
        if not _can_access_job(db, job, user, workspace):
            raise LookupError("workspace_job_not_found")
        from app.services.mlops_jobs import SERVER_MANAGED_JOB_KINDS

        if job.kind in SERVER_MANAGED_JOB_KINDS:
            raise HTTPException(403, "This job state is managed by its service")
        transition_job(
            db,
            workspace,
            job,
            body.status,
            progress=body.progress,
            stage=body.stage,
            result=body.result,
            error=body.error,
            user=user,
        )
        db.commit()
        return serialize_job(job)
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail="Workspace job not found") from exc


@router.get("/{job_id}/events")
async def jobs_events(
    job_id: str,
    request: Request,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    async def stream():
        offset = 0
        for _ in range(180):
            if await request.is_disconnected():
                break
            db = SessionLocal()
            try:
                job = db.query(WorkspaceJob).filter(WorkspaceJob.id == job_id, WorkspaceJob.workspace_id == workspace.id).first()
                if not job:
                    yield _sse("error", {"code": "workspace_job_not_found", "is_final": True})
                    break
                if not _can_access_job(db, job, user, workspace):
                    yield _sse("error", {"code": "workspace_job_not_found", "is_final": True})
                    break
                events = list(job.events or [])
                for event in events[offset:]:
                    yield _sse("workspace_job", {"job_id": job.id, **event})
                offset = len(events)
                if job.status in {"completed", "failed", "cancelled"}:
                    yield _sse("done", {"job_id": job.id, "status": job.status, "is_final": True})
                    break
            finally:
                db.close()
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream")


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
