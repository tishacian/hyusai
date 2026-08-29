"""SAP HANA Cloud connector API (workspace-gated beta)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.connectors.hana import service as hana_service

router = APIRouter()


class HanaConfigUpdate(BaseModel):
    host: str = Field(..., min_length=1, max_length=512)
    port: int = Field(default=443, ge=1, le=65535)
    user: str = Field(..., min_length=1, max_length=256)
    password: Optional[str] = Field(default=None, max_length=512)
    encrypt: bool = True


class HanaQueryRequest(BaseModel):
    sql: str = Field(..., min_length=1)
    params: Optional[Any] = None
    max_rows: int = Field(default=200, ge=1, le=5000)
    allow_writes: bool = False


def _require_enabled(workspace: Workspace) -> None:
    if not hana_service.is_workspace_enabled(workspace):
        raise HTTPException(
            status_code=403,
            detail="SAP HANA connector is not enabled for this workspace",
        )


@router.get("/config")
async def get_hana_config(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    return hana_service.get_config(workspace)


@router.put("/config")
async def put_hana_config(
    body: HanaConfigUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    try:
        return hana_service.set_config(db, workspace, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/test")
async def test_hana_connection(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    config = hana_service.get_config(workspace, include_secrets=True)
    try:
        return hana_service.test_connection(config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface driver errors to the operator UI
        raise HTTPException(
            status_code=502,
            detail=f"HANA connection failed: {exc}",
        ) from exc


@router.post("/query")
async def run_hana_query(
    body: HanaQueryRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    config = hana_service.get_config(workspace, include_secrets=True)
    try:
        return hana_service.run_query(
            config,
            sql=body.sql,
            params=body.params,
            max_rows=body.max_rows,
            allow_writes=body.allow_writes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface driver errors to the operator UI
        raise HTTPException(
            status_code=502,
            detail=f"HANA query failed: {exc}",
        ) from exc


@router.get("/preview")
async def preview_hana_catalog(
    table: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    """Read-only schema list + a capped sample of one table."""
    _require_enabled(workspace)
    config = hana_service.get_config(workspace, include_secrets=True)
    try:
        return hana_service.preview_catalog(config, table=table)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface driver errors to the operator UI
        raise HTTPException(
            status_code=502,
            detail=f"HANA preview failed: {exc}",
        ) from exc
