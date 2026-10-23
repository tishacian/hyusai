"""External runners: administration, probe, catalog and jobs.

Declaring a runner, probing it and submitting a job are administrator actions;
members may read jobs. The routes do not exist while the feature is disabled.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.endpoints.connections import _access
from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.remote_runner import RemoteRunner, RemoteRunnerJob
from app.services.remote_runners import catalog
from app.services.remote_runners import service as runners


def _enabled():
    if not settings.remote_runners_enabled:
        raise HTTPException(status_code=404, detail={"code": "REMOTE_RUNNERS_DISABLED"})


router = APIRouter(dependencies=[Depends(_enabled)])


def _call(db: Session, fn):
    try:
        value = fn()
        db.commit()
        return value
    except runners.RunnerError as exc:
        db.rollback()
        raise HTTPException(
            exc.status_code, detail={"code": exc.code, "message": str(exc)}
        ) from None


@router.get("/catalog")
def list_catalog(
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    return [spec.view() for spec in catalog.all_commands()]


@router.get("")
def list_runners(
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    rows = (
        db.query(RemoteRunner)
        .filter_by(workspace_id=workspace.id)
        .order_by(RemoteRunner.slug)
        .all()
    )
    return [runners.runner_view(row) for row in rows]


@router.post("", status_code=201)
def create_runner(
    body: dict = Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return _call(
        db,
        lambda: runners.runner_view(
            runners.create_runner(db, workspace_id=workspace.id, user_id=user.id, values=body)
        ),
    )


@router.patch("/{runner_id}")
def update_runner(
    runner_id: str,
    body: dict = Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return _call(
        db,
        lambda: runners.runner_view(
            runners.update_runner(
                db, runners.get_runner(db, workspace.id, runner_id), user_id=user.id, values=body
            )
        ),
    )


@router.post("/{runner_id}/probe")
def probe_runner(
    runner_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return _call(
        db,
        lambda: runners.probe_runner(
            db, runners.get_runner(db, workspace.id, runner_id), user_id=user.id
        ),
    )


@router.post("/{runner_id}/jobs", status_code=202)
def submit_job(
    runner_id: str,
    body: dict = Body(...),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    if (
        not isinstance(body, dict)
        or set(body)
        - {
            "command",
            "params",
            "timeout_s",
            "correlation_key",
            "notify_system_id",
            "file_ids",
            "documents",
        }
        or not isinstance(body.get("command"), str)
    ):
        raise HTTPException(400, detail={"code": "REMOTE_JOB_INVALID"})
    return _call(
        db,
        lambda: runners.job_view(
            runners.submit_job(
                db,
                workspace_id=workspace.id,
                runner_id=runner_id,
                command=body["command"],
                params=body.get("params"),
                timeout_s=body.get("timeout_s"),
                correlation_key=body.get("correlation_key"),
                notify_system_id=body.get("notify_system_id"),
                input_file_ids=body.get("file_ids"),
                input_documents=body.get("documents"),
                user_id=user.id,
            )
        ),
    )


@router.get("/{runner_id}/jobs")
def list_jobs(
    runner_id: str,
    limit: int = Query(50, ge=1, le=500),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    rows = (
        db.query(RemoteRunnerJob)
        .filter_by(workspace_id=workspace.id, runner_id=runner_id)
        .order_by(RemoteRunnerJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return [runners.job_view(row) for row in rows]


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user)
    return _call(db, lambda: runners.job_view(runners.get_job(db, workspace.id, job_id)))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return _call(
        db,
        lambda: runners.job_view(
            runners.cancel_job(db, runners.get_job(db, workspace.id, job_id), user_id=user.id)
        ),
    )


@router.get("/jobs/{job_id}/log")
def job_log(
    job_id: str,
    stream: str = Query("stderr"),
    max_bytes: int = Query(65536, ge=1, le=1048576),
    user=Depends(get_current_user),
    workspace=Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    _access(db, workspace, user, admin=True)
    return _call(
        db,
        lambda: {
            "stream": stream,
            "text": runners.read_job_log(
                db, runners.get_job(db, workspace.id, job_id), stream=stream, max_bytes=max_bytes
            ),
        },
    )
