"""Catalog connectors without a page of their own (write-only secrets, live test)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.connectors.generic import service as generic_service

router = APIRouter()


class ConnectorConfigUpdate(BaseModel):
    # Values stay untyped: a validation error echoes its input, and the input
    # can be a secret. The service rejects a bad value by field name only.
    values: dict[str, Any] = Field(default_factory=dict)


def _is_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> bool:
    membership = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id, WorkspaceMember.workspace_id == workspace.id)
        .first()
    )
    return bool(membership) and is_admin_template(getattr(membership, "role_template", None), membership.role)


def _require_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> None:
    if not _is_workspace_admin(db, user, workspace):
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})


def _require_connector(connector_id: str) -> None:
    if connector_id not in generic_service.CONNECTORS:
        raise HTTPException(status_code=404, detail="Unknown connector")


@router.get("")
async def list_connectors(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    return {
        "connectors": generic_service.list_configs(workspace),
        "can_configure": _is_workspace_admin(db, user, workspace),
    }


@router.put("/{connector_id}")
async def put_connector(
    connector_id: str,
    body: ConnectorConfigUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_connector(connector_id)
    _require_workspace_admin(db, user, workspace)
    try:
        return generic_service.set_config(db, workspace, connector_id, body.values, actor=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except generic_service.EncryptionNotConfigured as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{connector_id}")
async def delete_connector(
    connector_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_connector(connector_id)
    _require_workspace_admin(db, user, workspace)
    return generic_service.clear_config(db, workspace, connector_id, actor=user.id)


# Sync on purpose: the test waits on the remote service, so it runs in the
# threadpool instead of the event loop.
@router.post("/{connector_id}/test")
def test_connector(
    connector_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_connector(connector_id)
    _require_workspace_admin(db, user, workspace)
    try:
        config = generic_service.get_config(workspace, connector_id, include_secrets=True)
    except generic_service.EncryptionNotConfigured as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return generic_service.test_connection(connector_id, config)
