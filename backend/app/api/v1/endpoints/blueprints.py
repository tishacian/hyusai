"""Workspace Blueprint API.

Blueprints export and recreate workspace structure/configuration only. They
intentionally exclude users, credentials, raw files, vectors and historical
runtime evidence.
"""

from __future__ import annotations

from typing import Any, Literal

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
    blueprint: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = True
    activate_systems: bool = False
    experience_policy: Literal["preserve_target", "merge_missing", "replace_portable"] = (
        workspace_blueprints.DEFAULT_EXPERIENCE_POLICY
    )
    entitlement_policy: Literal["preserve_target", "grant_all_existing_members"] = (
        workspace_blueprints.DEFAULT_ENTITLEMENT_POLICY
    )
    plan_token: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


def _require_workspace_admin(
    db: DBSession,
    user: User,
    workspace: Workspace,
    *,
    refresh: bool = False,
) -> None:
    query = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == workspace.id,
    )
    if refresh:
        query = query.populate_existing()
    membership = query.first()
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
) -> dict[str, Any]:
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
) -> dict[str, Any]:
    _require_workspace_admin(db, user, workspace)
    try:
        report = workspace_blueprints.apply_workspace_blueprint(
            db=db,
            workspace=workspace,
            blueprint=body.blueprint,
            actor=user,
            dry_run=True,
            activate_systems=body.activate_systems,
            experience_policy=body.experience_policy,
            entitlement_policy=body.entitlement_policy,
        )
        db.rollback()
        return report
    except workspace_blueprints.WorkspaceBlueprintError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_blueprint", "message": str(exc)},
        ) from exc
    except Exception:
        db.rollback()
        raise


@router.post("/workspace/apply")
async def apply_workspace_blueprint(
    body: WorkspaceBlueprintApplyRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    _require_workspace_admin(db, user, workspace)
    try:
        report = workspace_blueprints.apply_workspace_blueprint(
            db=db,
            workspace=workspace,
            blueprint=body.blueprint,
            actor=user,
            dry_run=body.dry_run,
            activate_systems=body.activate_systems,
            experience_policy=body.experience_policy,
            entitlement_policy=body.entitlement_policy,
            expected_plan_token=body.plan_token,
            locked_workspace_guard=(
                lambda locked_workspace: _require_workspace_admin(
                    db,
                    user,
                    locked_workspace,
                    refresh=True,
                )
            )
            if not body.dry_run
            else None,
        )
        if body.dry_run:
            db.rollback()
        else:
            db.commit()
    except workspace_blueprints.WorkspaceBlueprintConflictError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "blueprint_conflict", "message": str(exc)},
        ) from exc
    except workspace_blueprints.WorkspaceBlueprintError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_blueprint", "message": str(exc)},
        ) from exc
    except Exception:
        db.rollback()
        raise
    return report
