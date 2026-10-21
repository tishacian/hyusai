"""Fenced mission lifecycle; HTTP observes persisted results, it never owns work."""

from __future__ import annotations

import asyncio
import copy
import uuid
from datetime import datetime, timedelta

from app.core.iam.roles import WORKSPACE_VIEWER, normalize_role_template
from app.models.task import Task
from app.models.task_execution import TaskExecution
from app.models.workspace import Workspace, WorkspaceMember

LEASE_SECONDS = 90
TERMINAL = {"completed", "failed", "interrupted"}


class MissionConflict(ValueError):
    pass


def execution_authorized(db, row):
    member = (
        db.query(WorkspaceMember)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .filter(
            WorkspaceMember.workspace_id == row.workspace_id,
            WorkspaceMember.user_id == row.created_by,
            Workspace.is_active.is_(True),
            Workspace.deleted_at.is_(None),
        )
        .first()
    )
    return (
        member is not None
        and normalize_role_template(member.role_template, member.role) != WORKSPACE_VIEWER
    )


def _revoke_execution(db, row, now):
    row.status, row.error = "failed", "MISSION_ACCESS_REVOKED"
    row.completed_at, row.lease_until = now, None
    row.fence += 1
    task = db.query(Task).filter_by(id=row.task_id, workspace_id=row.workspace_id).one()
    task.status, task.error, task.completed_at = row.status, row.error, now


def execution_public(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "task_id",
            "status",
            "progress",
            "steps",
            "artifacts",
            "error",
            "created_at",
            "started_at",
            "completed_at",
        )
    }


def queue_execution(db, task, user_id, *, confirm_rerun=False):
    # All launch/resume writers lock this same task before selecting its attempts.
    db.query(Task).filter_by(id=task.id, workspace_id=task.workspace_id).with_for_update().one()
    active = (
        db.query(TaskExecution)
        .filter_by(task_id=task.id, workspace_id=task.workspace_id)
        .filter(TaskExecution.status.in_(["queued", "running", "interrupted"]))
        .first()
    )
    if active:
        raise MissionConflict("MISSION_ALREADY_STARTED")
    if (
        task.status != "pending" or db.query(TaskExecution).filter_by(task_id=task.id).first()
    ) and not confirm_rerun:
        raise MissionConflict("MISSION_RELAUNCH_CONFIRMATION_REQUIRED")
    if task.artifacts and not db.query(TaskExecution).filter_by(task_id=task.id).first():
        db.add(
            TaskExecution(
                id=str(uuid.uuid4()),
                task_id=task.id,
                workspace_id=task.workspace_id,
                created_by=task.created_by or user_id,
                description=task.description,
                agent_id=task.agent_id,
                status=task.status if task.status in {"completed", "failed"} else "unverified",
                fence=0,
                created_at=task.created_at,
                started_at=task.started_at,
                completed_at=task.completed_at,
                steps=copy.deepcopy(task.steps or []),
                artifacts=copy.deepcopy(task.artifacts),
                progress=task.progress or 0,
                events=[],
            )
        )
    row = TaskExecution(
        id=str(uuid.uuid4()),
        task_id=task.id,
        workspace_id=task.workspace_id,
        created_by=user_id,
        description=task.description,
        agent_id=task.agent_id,
        status="queued",
        fence=0,
        steps=[],
        artifacts={},
        progress=0,
        events=[],
    )
    db.add(row)
    task.status = "queued"
    task.error = None
    db.flush()
    return row


def resume_execution(db, task, execution_id):
    db.query(Task).filter_by(id=task.id, workspace_id=task.workspace_id).with_for_update().one()
    row = (
        db.query(TaskExecution)
        .filter_by(id=execution_id, task_id=task.id, workspace_id=task.workspace_id)
        .with_for_update()
        .first()
    )
    if row and row.status == "running" and row.lease_until and row.lease_until <= datetime.utcnow():
        row.status = "interrupted"
    if row is None or row.status != "interrupted":
        raise MissionConflict("MISSION_NOT_INTERRUPTED")
    row.status = "queued"
    row.error = None
    row.fence += 1
    row.lease_until = None
    task.status = "queued"
    return row


def claim_execution(db, execution_id, now=None):
    now = now or datetime.utcnow()
    pending = db.query(TaskExecution).filter_by(id=execution_id, status="queued").first()
    if pending is None:
        return None
    if not execution_authorized(db, pending):
        _revoke_execution(db, pending, now)
        db.commit()
        return None
    changed = (
        db.query(TaskExecution)
        .filter_by(id=execution_id, status="queued")
        .update(
            {
                TaskExecution.status: "running",
                TaskExecution.fence: TaskExecution.fence + 1,
                TaskExecution.lease_until: now + timedelta(seconds=LEASE_SECONDS),
            },
            synchronize_session=False,
        )
    )
    if not changed:
        db.rollback()
        return None
    db.flush()
    db.expire_all()
    row = db.query(TaskExecution).filter_by(id=execution_id).one()
    if row.started_at is None:
        row.started_at = now
    task = db.query(Task).filter_by(id=row.task_id, workspace_id=row.workspace_id).one()
    task.status = "running"
    task.started_at = row.started_at
    db.commit()
    return row.fence


def checkpoint(db, execution_id, fence, event, now=None):
    now = now or datetime.utcnow()
    row = (
        db.query(TaskExecution)
        .filter_by(id=execution_id, fence=fence, status="running")
        .filter(TaskExecution.lease_until > now)
        .with_for_update()
        .first()
    )
    if row is None:
        db.rollback()
        return False
    event = copy.deepcopy(event)
    if not execution_authorized(db, row):
        _revoke_execution(db, row, now)
        db.commit()
        return False
    row.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    if "steps" in event:
        row.steps = event["steps"]
    if event.get("step"):
        step = event["step"]
        rows = copy.deepcopy(row.steps or [])
        index = next(
            (i for i, existing in enumerate(rows) if existing.get("id") == step.get("id")), None
        )
        if index is None:
            rows.append(step)
        else:
            rows[index] = step
        row.steps = rows
    row.progress = event.get("progress", row.progress)
    if event["type"] == "task_complete":
        row.status = (
            "failed" if any(step.get("status") == "failed" for step in row.steps) else "completed"
        )
        row.artifacts = event.get("artifacts", {})
        row.completed_at = now
        row.error = "MISSION_STEP_FAILED" if row.status == "failed" else None
    elif event["type"] in ("task_error", "task_interrupted"):
        row.status = "interrupted" if event["type"] == "task_interrupted" else "failed"
        row.error = event.get("message", "MISSION_FAILED")
        if row.status == "failed":
            row.completed_at = now
    task = db.query(Task).filter_by(id=row.task_id, workspace_id=row.workspace_id).one()
    task.status, task.progress, task.error = row.status, row.progress, row.error
    task.steps = copy.deepcopy(row.steps)
    if row.status in {"completed", "failed"}:
        task.artifacts = copy.deepcopy(row.artifacts)
        task.completed_at = row.completed_at
        task.total_duration_ms = event.get("total_duration_ms")
    event["status"] = row.status
    row.events = [*(row.events or []), event][-500:]
    db.commit()
    return True


def renew_lease(db, execution_id, fence, now=None):
    """A heartbeat retains write authority only while membership is still valid."""
    now = now or datetime.utcnow()
    row = (
        db.query(TaskExecution)
        .filter_by(id=execution_id, fence=fence, status="running")
        .filter(TaskExecution.lease_until > now)
        .with_for_update()
        .first()
    )
    if row is None:
        db.rollback()
        return False
    if not execution_authorized(db, row):
        _revoke_execution(db, row, now)
        db.commit()
        return False
    row.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    db.commit()
    return True


def recover_executions(db, now=None):
    now = now or datetime.utcnow()
    expired = (
        db.query(TaskExecution)
        .filter_by(status="running")
        .filter(TaskExecution.lease_until <= now)
        .with_for_update(skip_locked=True)
        .all()
    )
    for row in expired:
        row.status = "interrupted"
        row.error = "MISSION_WORKER_LOST"
        row.lease_until = None
        row.fence += 1
        task = db.query(Task).filter_by(id=row.task_id, workspace_id=row.workspace_id).one()
        task.status = "interrupted"
        task.error = row.error
    queued = [
        row.id
        for row in db.query(TaskExecution)
        .filter_by(status="queued")
        .order_by(TaskExecution.created_at)
        .limit(100)
        .all()
    ]
    db.commit()
    return queued


def dispatch_execution(execution_id):
    from app.workers.mission_tasks import run_mission

    try:
        run_mission.apply_async(args=[execution_id], retry=False)
        return True
    except Exception:
        # The committed queued row is the outbox; the scheduled recovery retries.
        return False


async def execute_mission(execution_id, session_factory, engine):
    with session_factory() as db:
        fence = claim_execution(db, execution_id)
        if fence is None:
            return {"status": "already_claimed"}
        row = db.query(TaskExecution).filter_by(id=execution_id).one()
        description, agent_id, task_id = row.description, row.agent_id, row.task_id
        resume_steps = copy.deepcopy(row.steps)
    lost = asyncio.Event()

    async def heartbeat():
        while not lost.is_set():
            await asyncio.sleep(15)
            with session_factory() as db:
                if not renew_lease(db, execution_id, fence):
                    lost.set()

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        async for event in engine.execute_task(
            task_id, description, agent_id, resume_steps=resume_steps
        ):
            if lost.is_set():
                return {"status": "lease_lost"}
            with session_factory() as db:
                if not checkpoint(db, execution_id, fence, event):
                    return {"status": "lease_lost"}
        with session_factory() as db:
            row = db.query(TaskExecution).filter_by(id=execution_id).one()
            if row.status == "running":
                checkpoint(
                    db,
                    execution_id,
                    fence,
                    {"type": "task_interrupted", "message": "MISSION_STREAM_INCOMPLETE"},
                )
        return {"status": "finished"}
    except BaseException:
        with session_factory() as db:
            checkpoint(
                db,
                execution_id,
                fence,
                {"type": "task_interrupted", "message": "MISSION_INTERRUPTED"},
            )
        raise
    finally:
        lost.set()
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
