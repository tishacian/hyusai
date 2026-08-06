"""Normalized manual operator ingress endpoints bound to the published Flow.

Non-manual adapters enter through their dedicated, authenticated boundaries
(scheduler, webhook and event services).  Letting an authenticated operator
label a request as one of those adapters would bypass their evidence,
deduplication and rate-limit controls.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.systems import (
    _enforce_system_read,
    _enforce_system_run_authority,
)
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.run_engine import schedule_run
from app.services.systems import flow_ingress

router = APIRouter()


class IngressRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["manual"]
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_published_version_id: str = Field(min_length=1, max_length=36)
    expected_flow_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _system_or_404(
    db: DBSession,
    *,
    system_id: str,
    workspace_id: str,
) -> System:
    system = (
        db.query(System)
        .filter(System.id == system_id, System.workspace_id == workspace_id)
        .one_or_none()
    )
    if system is None:
        raise HTTPException(404, "System not found")
    return system


def _raise_ingress(db: DBSession, exc: flow_ingress.FlowIngressError) -> None:
    db.rollback()
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


@router.get("/{system_id}/ingresses")
async def list_flow_ingresses(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    try:
        return flow_ingress.list_published_ingresses(
            db,
            system_id=system.id,
            workspace=workspace,
        )
    except flow_ingress.FlowIngressError as exc:
        _raise_ingress(db, exc)


@router.post("/{system_id}/ingresses/{ingress_id}/runs", status_code=201)
async def create_flow_ingress_run(
    system_id: str,
    ingress_id: str,
    body: IngressRunBody,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    system = _system_or_404(db, system_id=system_id, workspace_id=workspace.id)
    _enforce_system_read(db, user=user, workspace=workspace, system=system)
    _enforce_system_run_authority(
        db,
        user=user,
        workspace=workspace,
        system=system,
        execution_source="published_manual_ingress_api",
    )
    try:
        run = flow_ingress.create_published_ingress_run(
            db,
            system_id=system.id,
            workspace=workspace,
            ingress_id=ingress_id,
            kind=body.kind,
            payload=body.payload,
            initiated_by_user_id=getattr(user, "id", None),
            expected_published_version_id=body.expected_published_version_id,
            expected_flow_sha256=body.expected_flow_sha256,
            adapter_evidence={"surface": "operator_api"},
        )
        db.commit()
        db.refresh(run)
    except flow_ingress.FlowIngressError as exc:
        _raise_ingress(db, exc)
    background_tasks.add_task(schedule_run, run.id)
    return {
        "id": run.id,
        "status": run.status,
        "system_id": run.system_id,
        "execution_surface": run.execution_surface,
        "published_flow_version_id": run.published_flow_version_id,
        "flow_sha256": run.flow_sha256,
        "ingress_id": ingress_id,
        "runtime_mode": (run.execution_contract or {}).get("runtime_mode"),
    }
