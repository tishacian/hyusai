from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from connections.celery.app import app as celery_app
from connections.celery.db.celery_task_extra_model import TaskExtra
from connections.celery.db.utils import get_engine
from connections.celery.utils import full_logs_for_task, translate_status_for_core
from connections.models.tasks.responses import TaskStatusResponse

router = APIRouter()


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """Poll the status of a Celery task.

    Returns the translated core status (waiting | running | available | error |
    cancelled), the task result (when available), and any accumulated logs.
    Returns 404 when the task ID is not found in the result backend.
    """
    engine = get_engine()
    with Session(engine) as session:
        task_extra = session.execute(
            select(TaskExtra).where(TaskExtra.task_id == task_id)
        ).scalar_one_or_none()

    if task_extra is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )

    ar = AsyncResult(task_id, app=celery_app)
    core_status = translate_status_for_core(ar.state)
    result = ar.result if ar.state == "SUCCESS" else None
    logs = full_logs_for_task(task_extra.progress_message, task_extra.logs)

    return TaskStatusResponse(
        task_id=task_id,
        status=core_status,
        result=result if isinstance(result, dict) else None,
        logs=logs or None,
        progress=task_extra.progress_message or None,
    )
