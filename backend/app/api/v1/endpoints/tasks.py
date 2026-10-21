"""Mission composition, explicit launch and observation of durable executions."""

import asyncio
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import WORKSPACE_VIEWER, normalize_role_template
from app.db.base import SessionLocal, get_db
from app.models.task import Task
from app.models.task_execution import TaskExecution
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.tasks.execution import (
    TERMINAL,
    MissionConflict,
    dispatch_execution,
    execution_public,
    queue_execution,
    resume_execution,
)

router = APIRouter()


class TaskCreate(BaseModel):
    title: str = Field(default="", max_length=255)
    description: str = Field(min_length=1, max_length=20000)
    agent_id: str | None = None


class TaskLaunch(BaseModel):
    confirm_rerun: bool = False


def _task(db, task_id, workspace_id):
    task = db.query(Task).filter_by(id=task_id, workspace_id=workspace_id).first()
    if task is None:
        raise HTTPException(404, detail={"code": "MISSION_NOT_FOUND"})
    return task


def _can_launch(db, workspace_id, user_id):
    membership = (
        db.query(WorkspaceMember).filter_by(workspace_id=workspace_id, user_id=user_id).first()
    )
    if (
        membership is None
        or normalize_role_template(membership.role_template, membership.role) == WORKSPACE_VIEWER
    ):
        raise HTTPException(403, detail={"code": "MISSION_LAUNCH_FORBIDDEN"})


def _public(db, task, *, detail=False):
    latest = (
        db.query(TaskExecution)
        .filter_by(task_id=task.id, workspace_id=task.workspace_id)
        .order_by(TaskExecution.created_at.desc(), TaskExecution.id)
        .first()
    )
    result = {
        key: getattr(task, key)
        for key in (
            "id",
            "title",
            "description",
            "status",
            "agent_id",
            "progress",
            "created_at",
            "started_at",
            "completed_at",
            "total_duration_ms",
        )
    }
    result["execution_id"] = latest.id if latest else None
    result["durable"] = latest is not None
    if latest:
        result.update(
            status=latest.status,
            progress=latest.progress,
            started_at=latest.started_at,
            completed_at=latest.completed_at,
            total_duration_ms=task.total_duration_ms
            if latest.status in {"completed", "failed"}
            else None,
        )
    if task.status == "running" and latest is None:
        result["status"] = "unverified"
    if (
        latest
        and latest.status == "running"
        and latest.lease_until
        and latest.lease_until <= datetime.utcnow()
    ):
        result["status"] = "interrupted"
    if detail:
        result.update(
            steps=(latest.steps if latest else task.steps) or [],
            artifacts=(latest.artifacts if latest else task.artifacts) or {},
            error=latest.error if latest else task.error,
        )
        result["executions"] = [
            execution_public(row)
            for row in db.query(TaskExecution)
            .filter_by(task_id=task.id, workspace_id=task.workspace_id)
            .order_by(TaskExecution.created_at.desc())
            .all()
        ]
    return result


@router.post("")
async def create_task(
    req: TaskCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _can_launch(db, workspace.id, user.id)
    if not req.description.strip():
        raise HTTPException(422, detail={"code": "MISSION_DESCRIPTION_REQUIRED"})
    if req.agent_id:
        raise HTTPException(422, detail={"code": "MISSION_SYSTEM_EXECUTION_UNSUPPORTED"})
    task = Task(
        id=str(uuid.uuid4()),
        title=req.title.strip() or req.description.strip()[:80],
        description=req.description.strip(),
        status="pending",
        agent_id=req.agent_id,
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db.add(task)
    db.commit()
    return {"id": task.id, "status": "pending", "title": task.title}


@router.get("")
async def list_tasks(
    limit: int = Query(20, ge=1, le=100),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    rows = (
        db.query(Task)
        .filter_by(workspace_id=workspace.id)
        .order_by(Task.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"tasks": [_public(db, row) for row in rows]}


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    return _public(db, _task(db, task_id, workspace.id), detail=True)


def _stream(execution_id, workspace_id, user_id):
    async def events():
        seen = 0
        # A bounded observation window does not limit the worker's execution.
        for _ in range(300):
            with SessionLocal() as db:
                membership = (
                    db.query(WorkspaceMember)
                    .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
                    .filter(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.user_id == user_id,
                        Workspace.is_active.is_(True),
                        Workspace.deleted_at.is_(None),
                    )
                    .first()
                )
                if membership is None:
                    yield 'data: {"type":"task_error","message":"WORKSPACE_ACCESS_DENIED"}\n\n'
                    return
                row = (
                    db.query(TaskExecution)
                    .filter_by(id=execution_id, workspace_id=workspace_id)
                    .first()
                )
                if row is None:
                    return
                state = row.status
                payload = list(row.events or [])
                for event in payload[seen:]:
                    yield f"data: {json.dumps(event)}\n\n"
                seen = len(payload)
                yield f"data: {json.dumps({'type': 'task_execution', 'execution_id': row.id, 'status': state, 'started_at': row.started_at.isoformat() if row.started_at else None, 'progress': row.progress})}\n\n"
                if state in TERMINAL:
                    yield "data: [DONE]\n\n"
                    return
            await asyncio.sleep(0.5)
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/{task_id}/run")
async def run_task(
    task_id: str,
    body: TaskLaunch = TaskLaunch(),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    task = _task(db, task_id, workspace.id)
    _can_launch(db, workspace.id, user.id)
    try:
        row = queue_execution(db, task, user.id, confirm_rerun=body.confirm_rerun)
        db.commit()
    except MissionConflict as exc:
        db.rollback()
        raise HTTPException(409, detail={"code": str(exc)}) from None
    dispatch_execution(row.id)
    return _stream(row.id, workspace.id, user.id)


@router.post("/{task_id}/executions/{execution_id}/resume")
async def resume_task(
    task_id: str,
    execution_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    task = _task(db, task_id, workspace.id)
    _can_launch(db, workspace.id, user.id)
    try:
        row = resume_execution(db, task, execution_id)
        db.commit()
    except MissionConflict as exc:
        db.rollback()
        raise HTTPException(409, detail={"code": str(exc)}) from None
    dispatch_execution(row.id)
    return _stream(row.id, workspace.id, user.id)


@router.post("/{task_id}/executions/{execution_id}/events")
async def observe_task(
    task_id: str,
    execution_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _task(db, task_id, workspace.id)
    if (
        not db.query(TaskExecution)
        .filter_by(id=execution_id, task_id=task_id, workspace_id=workspace.id)
        .first()
    ):
        raise HTTPException(404, detail={"code": "MISSION_EXECUTION_NOT_FOUND"})
    return _stream(execution_id, workspace.id, user.id)
