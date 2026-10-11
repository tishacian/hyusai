"""Published-only operator Runner HTTP surface."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.systems import (
    _enforce_system_read,
    _enforce_system_run_authority,
)
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.run import Run
from app.models.user import Session as SessionModel
from app.models.user import User
from app.models.workspace import Workspace
from app.services.run_engine import schedule_run
from app.services.systems import flow_runner

router = APIRouter()


class RunnerSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=500)


class RunnerRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingress_id: str = Field(min_length=1, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_published_version_id: str = Field(min_length=1, max_length=36)
    expected_flow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _actor_id(user: User) -> str:
    user_id = str(getattr(user, "id", "") or "")
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "RUNNER_USER_ID_REQUIRED",
                "message": "A durable user identity is required by the Runner.",
            },
        )
    return user_id


def _raise_runner(db: DBSession, exc: flow_runner.FlowRunnerError) -> None:
    db.rollback()
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _session_row(session: SessionModel) -> dict[str, Any]:
    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "last_activity": session.last_activity.isoformat() if session.last_activity else None,
    }


def _run_row(run: Run) -> dict[str, Any]:
    contract = run.execution_contract if isinstance(run.execution_contract, dict) else {}
    return {
        "id": run.id,
        "system_id": run.system_id,
        "runner_session_id": run.runner_session_id,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "duration_ms": run.duration_ms,
        "input_ref": run.input_ref or {},
        "output_ref": run.output_ref if run.output_ref is not None else {},
        "error": run.error,
        "execution_surface": run.execution_surface,
        "published_flow_version_id": run.published_flow_version_id,
        "flow_sha256": run.flow_sha256,
        "runtime_mode": contract.get("runtime_mode"),
    }


def _published_operator_summary(
    db: DBSession,
    *,
    system: Any,
    workspace: Workspace,
) -> dict[str, Any]:
    published = flow_runner.published_summary(
        db,
        system=system,
        workspace=workspace,
    )
    # An authenticated operator must not impersonate schedule, webhook or
    # event adapters.  Runner execution is intentionally manual-only.
    published["ingresses"] = [
        ingress
        for ingress in published["ingresses"]
        if isinstance(ingress, dict) and ingress.get("kind") == "manual"
    ]
    return published


def _resolve_system(
    db: DBSession,
    *,
    system_id: str,
    workspace: Workspace,
    user: User,
):
    system = flow_runner.owned_system(
        db,
        system_id=system_id,
        workspace=workspace,
    )
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    return system


@router.get("/{system_id}/runner")
async def get_runner(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        system = _resolve_system(
            db,
            system_id=system_id,
            workspace=workspace,
            user=user,
        )
        user_id = _actor_id(user)
        sessions = flow_runner.list_sessions(
            db,
            system_id=system.id,
            workspace_id=workspace.id,
            user_id=user_id,
        )
        return {
            "published": _published_operator_summary(
                db,
                system=system,
                workspace=workspace,
            ),
            "sessions": [_session_row(session) for session in sessions],
        }
    except flow_runner.FlowRunnerError as exc:
        _raise_runner(db, exc)


@router.post("/{system_id}/runner/sessions", status_code=201)
async def create_runner_session(
    system_id: str,
    body: RunnerSessionCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        system = _resolve_system(
            db,
            system_id=system_id,
            workspace=workspace,
            user=user,
        )
        published = _published_operator_summary(
            db,
            system=system,
            workspace=workspace,
        )
        session = flow_runner.create_session(
            db,
            system=system,
            workspace_id=workspace.id,
            user_id=_actor_id(user),
            title=body.title,
        )
        db.commit()
        db.refresh(session)
        return {
            "published": published,
            "session": _session_row(session),
            "runs": [],
        }
    except flow_runner.FlowRunnerError as exc:
        _raise_runner(db, exc)


@router.get("/{system_id}/runner/sessions/{session_id}")
async def get_runner_session(
    system_id: str,
    session_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        system = _resolve_system(
            db,
            system_id=system_id,
            workspace=workspace,
            user=user,
        )
        user_id = _actor_id(user)
        session = flow_runner.owned_session(
            db,
            session_id=session_id,
            system_id=system.id,
            workspace_id=workspace.id,
            user_id=user_id,
        )
        runs = flow_runner.session_runs(
            db,
            session=session,
            system_id=system.id,
            workspace_id=workspace.id,
            user_id=user_id,
        )
        return {
            "published": _published_operator_summary(
                db,
                system=system,
                workspace=workspace,
            ),
            "session": _session_row(session),
            "runs": [_run_row(run) for run in runs],
        }
    except flow_runner.FlowRunnerError as exc:
        _raise_runner(db, exc)


@router.post("/{system_id}/runner/sessions/{session_id}/runs", status_code=201)
async def create_runner_run(
    system_id: str,
    session_id: str,
    body: RunnerRunCreate,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        system = _resolve_system(
            db,
            system_id=system_id,
            workspace=workspace,
            user=user,
        )
        user_id = _actor_id(user)
        session = flow_runner.owned_session(
            db,
            session_id=session_id,
            system_id=system.id,
            workspace_id=workspace.id,
            user_id=user_id,
        )
        _enforce_system_run_authority(
            db,
            user=user,
            workspace=workspace,
            system=system,
            execution_source="operator_runner",
        )
        run = flow_runner.create_run(
            db,
            system=system,
            workspace=workspace,
            user_id=user_id,
            session=session,
            ingress_id=body.ingress_id,
            payload=body.payload,
            expected_published_version_id=body.expected_published_version_id,
            expected_flow_sha256=body.expected_flow_sha256,
        )
        db.commit()
        db.refresh(run)
    except flow_runner.FlowRunnerError as exc:
        _raise_runner(db, exc)
    background_tasks.add_task(schedule_run, run.id)
    return _run_row(run)
