"""Workspace Apps & Integrations toggles API."""

from __future__ import annotations

from typing import Any, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user
from app.core.iam.roles import WORKSPACE_ADMIN, WORKSPACE_OWNER, normalize_role_template
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import workspace_apps as apps_service

router = APIRouter()


class AppsUpdateBody(BaseModel):
    """Replace the workspace enabled-apps set.

    Accept either a list of enabled ids or a ``{app_id: bool}`` map.
    """

    enabled: Union[list[str], dict[str, bool]] = Field(...)


def _resolve_workspace_and_role(
    db: DBSession, user: User, slug: str
) -> tuple[Workspace, WorkspaceMember]:
    workspace = (
        db.query(Workspace)
        .filter(Workspace.slug == slug, Workspace.deleted_at.is_(None))
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    return workspace, membership


def _require_admin(membership: WorkspaceMember) -> None:
    if normalize_role_template(getattr(membership, "role_template", None), membership.role) not in (
        WORKSPACE_OWNER,
        WORKSPACE_ADMIN,
    ):
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/{slug}/apps")
async def get_workspace_apps(
    slug: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workspace, _ = _resolve_workspace_and_role(db, user, slug)
    return apps_service.list_workspace_apps(workspace)


@router.put("/{slug}/apps")
async def put_workspace_apps(
    slug: str,
    body: AppsUpdateBody,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)
    return apps_service.set_enabled_apps(db, workspace, body.enabled)
