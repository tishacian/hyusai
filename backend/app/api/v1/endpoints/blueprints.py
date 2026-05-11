"""Workspace Blueprint API.

Blueprints export and recreate workspace structure/configuration only. They
intentionally exclude users, credentials, raw files, vectors and historical
runtime evidence.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.roles import is_admin_template
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import workspace_blueprints

router = APIRouter()


class WorkspaceBlueprintApplyRequest(BaseModel):
    blueprint: Dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True
    activate_systems: bool = False


def _require_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> None:
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    if not membership or not is_admin_template(
        getattr(membership, "role_template", None),
        membership.role,
    ):
        raise HTTPException(status_code=403, detail={"code": "WORKSPACE_PERMISSION_DENIED"})


@router.get("/workspace/current")
async def export_current_workspace_blueprint(
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    _require_workspace_admin(db, user, workspace)
    payload = workspace_blueprints.export_workspace_blueprint(
        db=db,
        workspace=workspace,
        exported_by=user,
    )
    db.commit()
    return payload


@router.post("/workspace/validate")
async def validate_workspace_blueprint(
    body: WorkspaceBlueprintApplyRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    _require_workspace_admin(db, user, workspace)
    try:
        return workspace_blueprints.apply_workspace_blueprint(
            db=db,
            workspace=workspace,
            blueprint=body.blueprint,
            actor=user,
            dry_run=True,
            activate_systems=False,
        )
    except workspace_blueprints.WorkspaceBlueprintError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_blueprint", "message": str(exc)},
        ) from exc


@router.post("/workspace/apply")
async def apply_workspace_blueprint(
    body: WorkspaceBlueprintApplyRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    _require_workspace_admin(db, user, workspace)
    try:
        report = workspace_blueprints.apply_workspace_blueprint(
            db=db,
            workspace=workspace,
            blueprint=body.blueprint,
            actor=user,
            dry_run=body.dry_run,
            activate_systems=body.activate_systems,
        )
    except workspace_blueprints.WorkspaceBlueprintError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_blueprint", "message": str(exc)},
        ) from exc
    if body.dry_run:
        db.rollback()
    else:
        db.commit()
    return report
