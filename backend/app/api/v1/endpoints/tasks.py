"""Task API — create, list, stream autonomous agent missions"""
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.task import Task
from app.models.workspace import Workspace
from app.services.tasks.engine import get_task_engine

router = APIRouter()


class TaskCreate(BaseModel):
    title: str = ""
    description: str
    agent_id: str = None


@router.post("")
async def create_task(
    req: TaskCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        title=req.title or req.description[:80],
        description=req.description,
        status="pending",
        agent_id=req.agent_id,
        workspace_id=workspace.id,
    )
    db.add(task)
    db.commit()
    return {"id": task_id, "status": "pending", "title": task.title}


@router.get("")
async def list_tasks(
    limit: int = 20,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    rows = (
        db.query(Task)
        .filter(Task.workspace_id == workspace.id)
        .order_by(Task.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description[:200],
                "status": t.status,
                "agent_id": t.agent_id,
                "progress": t.progress,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "total_duration_ms": t.total_duration_ms,
            }
            for t in rows
        ]
    }


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == workspace.id,
    ).first()
    if not task:
        return {"error": "Task not found"}
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "agent_id": task.agent_id,
        "steps": task.steps,
        "artifacts": task.artifacts,
        "progress": task.progress,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "total_duration_ms": task.total_duration_ms,
    }


@router.post("/{task_id}/run")
async def run_task(
    task_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.workspace_id == workspace.id,
    ).first()
    if not task:
        return {"error": "Task not found"}

    engine = get_task_engine()

    async def stream():
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()

        async for event in engine.execute_task(task.id, task.description, task.agent_id):
            if event["type"] == "task_complete":
                task.status = "completed"
                task.steps = event.get("steps", [])
                task.artifacts = event.get("artifacts", {})
                task.progress = 100
                task.completed_at = datetime.utcnow()
                task.total_duration_ms = event.get("total_duration_ms")
                db.commit()
            elif event["type"] == "task_plan":
                task.steps = event.get("steps", [])
                task.status = "running"
                db.commit()
            elif event["type"] in ("task_step", "task_step_complete"):
                task.progress = event.get("progress", task.progress)
                db.commit()

            yield f"data: {json.dumps(event)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
