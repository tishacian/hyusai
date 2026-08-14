"""Business /work resolver — slug → live (else entitled pilot) release.

Feature-gated by ``settings.features.experience_v1``. Audience filter for
pilot: ``audience.roles`` / ``audience.role_templates``; empty means open.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import current_membership
from app.core.iam.roles import WORKSPACE_ADMIN, normalize_role_template
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.experience import bindings as binding_service
from app.services.experience import lifecycle as experience_service
from app.services.iam.decision_plane import enforce_action

router = APIRouter()


def _require_enabled(workspace: Workspace) -> None:
    try:
        binding_service.require_experience_v1(workspace)
    except binding_service.BindingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _enforce_view(db: DBSession, *, user: User, workspace: Workspace) -> None:
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="experience",
        action="view",
        legacy_allowed=True,
        resource_attrs={"scope": "collection"},
    )


def _viewer_role(db: DBSession, *, user: User, workspace: Workspace) -> str:
    if getattr(user, "role", None) == "admin":
        return WORKSPACE_ADMIN
    membership = current_membership(db, user, workspace)
    if membership is None:
        return ""
    return normalize_role_template(membership.role_template, membership.role) or ""


@router.get("/{slug}")
async def get_work_app(
    slug: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    try:
        experience, deployment, release = experience_service.resolve_work(
            db,
            workspace_id=workspace.id,
            slug=slug,
            role=_viewer_role(db, user=user, workspace=workspace),
        )
    except experience_service.ExperienceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    return experience_service.serialize_work(experience, deployment, release)
