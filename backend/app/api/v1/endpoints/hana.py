"""SAP HANA Cloud connector API (workspace-gated beta)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.connectors.hana import service as hana_service

router = APIRouter()


def _is_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> bool:
    membership = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id)
        .first()
    )
    return bool(membership) and is_admin_template(
        getattr(membership, "role_template", None), membership.role
    )


def _require_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> None:
    if not _is_workspace_admin(db, user, workspace):
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})


class HanaConfigUpdate(BaseModel):
    host: str = Field(..., min_length=1, max_length=512)
    port: int = Field(default=443, ge=1, le=65535)
    user: str = Field(..., min_length=1, max_length=256)
    password: str | None = Field(default=None, max_length=512)
    password_encrypted: str | None = Field(default=None, max_length=4096)
    encrypt: bool = True
    ssl_validate_certificate: bool = True
    demo_mode: bool = False


class HanaQueryRequest(BaseModel):
    sql: str = Field(..., min_length=1)
    params: Any | None = None
    max_rows: int = Field(default=200, ge=1, le=5000)
    allow_writes: bool = False


def _require_enabled(workspace: Workspace) -> None:
    if not hana_service.is_workspace_enabled(workspace):
        raise HTTPException(
            status_code=403,
            detail="SAP HANA connector is not enabled for this workspace",
        )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, hana_service.HanaConnectorError):
        return HTTPException(status_code=exc.status_code, detail={"code": exc.code})
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail={"code": "HANA_INVALID_REQUEST"})
    return HTTPException(status_code=502, detail={"code": "HANA_OPERATION_FAILED"})


def _run_operation(workspace: Workspace, operation, **kwargs):
    config = hana_service.get_config(workspace, include_secrets=True)
    return operation(config, **kwargs)


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
    _require_workspace_admin(db, user, workspace)
    if body.password_encrypted is not None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "WORKSPACE_SECRET_WRITE_ONLY",
                "message": "A connector secret is set on its connector, not as an encrypted field",
                "fields": ["password_encrypted"],
            },
        )
    try:
        return await asyncio.to_thread(
            hana_service.set_config, db, workspace, body.model_dump(exclude={"password_encrypted"})
        )
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/test")
async def test_hana_connection(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _require_workspace_admin(db, user, workspace)
    try:
        return await asyncio.to_thread(_run_operation, workspace, hana_service.test_connection)
    except hana_service.HanaConnectorError as exc:
        status = {
            "HANA_AUTH_FAILED": "auth_failed",
            "HANA_RESOURCE_DENIED": "access_denied",
            "HANA_NOT_CONFIGURED": "not_configured",
        }.get(exc.code)
        if status:
            return {"ok": False, "status": status}
        raise _http_error(exc) from None
    except Exception as exc:
        raise _http_error(exc) from None


@router.post("/query")
async def run_hana_query(
    body: HanaQueryRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    if body.allow_writes:
        _require_workspace_admin(db, user, workspace)
        if getattr(settings, "hana_writes_enabled", False) is not True:
            raise HTTPException(status_code=403, detail={"code": "HANA_WRITES_DISABLED"})
    try:
        return await asyncio.to_thread(
            _run_operation,
            workspace,
            hana_service.run_query,
            sql=body.sql,
            params=body.params,
            max_rows=body.max_rows,
            allow_writes=body.allow_writes,
        )
    except Exception as exc:
        raise _http_error(exc) from None


@router.get("/preview")
async def preview_hana_catalog(
    table: str | None = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    """Read-only schema list + a capped sample of one table."""
    _require_enabled(workspace)
    try:
        return await asyncio.to_thread(
            _run_operation, workspace, hana_service.preview_catalog, table=table
        )
    except Exception as exc:
        raise _http_error(exc) from None
