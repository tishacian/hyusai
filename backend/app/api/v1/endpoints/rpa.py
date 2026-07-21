"""RPA Bridge connector API (workspace-gated)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.connectors.rpa import service as rpa_service

router = APIRouter()


class RpaConfigUpdate(BaseModel):
    base_url: str = Field(..., min_length=1, max_length=1024)
    auth_token: Optional[str] = Field(default=None, max_length=2048)
    job_mapping: Optional[dict[str, str]] = None
    callback_webhook_url: Optional[str] = Field(default=None, max_length=1024)


class RpaJobStartRequest(BaseModel):
    job_key: str = Field(..., min_length=1, max_length=256)
    input: Optional[dict[str, Any]] = None
    callback_url: Optional[str] = Field(default=None, max_length=1024)
    wait: bool = False
    timeout_s: float = Field(default=30.0, ge=0.1, le=300.0)
    poll_interval_s: float = Field(default=0.5, ge=0.05, le=30.0)


def _require_enabled(workspace: Workspace) -> None:
    if not rpa_service.is_workspace_enabled(workspace):
        raise HTTPException(
            status_code=403,
            detail="RPA Bridge connector is not enabled for this workspace",
        )


@router.get("/config")
async def get_rpa_config(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    return rpa_service.get_config(workspace)


@router.put("/config")
async def put_rpa_config(
    body: RpaConfigUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    try:
        return rpa_service.set_config(db, workspace, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/test")
async def test_rpa_connection(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    config = rpa_service.get_config(workspace, include_secrets=True)
    try:
        return rpa_service.test_connection(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface upstream errors to the operator UI
        raise HTTPException(
            status_code=502,
            detail=f"RPA Bridge connection failed: {exc}",
        ) from exc


@router.post("/jobs")
async def start_rpa_job(
    body: RpaJobStartRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    config = rpa_service.get_config(workspace, include_secrets=True)
    try:
        if body.wait:
            return rpa_service.dispatch_and_poll(
                config,
                job_key=body.job_key,
                input_payload=body.input,
                callback_url=body.callback_url,
                timeout_s=body.timeout_s,
                poll_interval_s=body.poll_interval_s,
            )
        return rpa_service.start_job(
            config,
            job_key=body.job_key,
            input_payload=body.input,
            callback_url=body.callback_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"RPA job dispatch failed: {exc}",
        ) from exc


@router.get("/jobs/{job_id}")
async def get_rpa_job(
    job_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    config = rpa_service.get_config(workspace, include_secrets=True)
    try:
        return rpa_service.get_job(config, job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"RPA job status failed: {exc}",
        ) from exc
