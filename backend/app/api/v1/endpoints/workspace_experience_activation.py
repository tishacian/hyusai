"""Work and Studio activation for one workspace.

The generic ``PATCH /auth/workspaces/{slug}`` replaces the whole ``settings``
document, so a toggle sent through it can silently undo a concurrent edit.
This endpoint changes one flag, ``settings.features.experience_v1``, and only
when the caller's view of it is still current (compare-and-set under the
workspace row lock). Every change is audited.

The read side tells an administrator, before confirming, who the change
affects: every member sees Work, members with an editing role can open the
Studio, reviewers can inspect and release.
"""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.auth import (
    _lock_workspace_and_role_for_membership_mutation,
    _require_admin,
    _resolve_workspace_and_role,
)
from app.core.auth import get_current_user
from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_OWNER,
    WORKSPACE_REVIEWER,
    normalize_role_template,
)
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.audit_logger import emit_audit_event
from app.services.experience.bindings import (
    FEATURE_KEY,
    experience_studio_v1_enabled,
    experience_v1_enabled,
)

router = APIRouter()

#: Role templates that may compose applications in the Studio. Mirrors
#: ``canEditExperienceStudio`` in frontend-ng/src/app/features/experience/experience-access.ts.
STUDIO_EDITOR_TEMPLATES = frozenset({WORKSPACE_CONTRIBUTOR, WORKSPACE_ADMIN, WORKSPACE_OWNER})


class ExperienceActivationMembers(BaseModel):
    total: int
    studio_editors: int
    studio_reviewers: int


class ExperienceActivationState(BaseModel):
    enabled: bool
    studio_enabled: bool
    members: ExperienceActivationMembers


class ExperienceActivationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    #: The value the caller read before asking. A mismatch means another
    #: administrator changed it in between: the write is refused, not merged.
    expected_enabled: bool


def _members(db: DBSession, workspace: Workspace) -> ExperienceActivationMembers:
    rows = (
        db.query(WorkspaceMember.role_template, WorkspaceMember.role)
        .filter(WorkspaceMember.workspace_id == workspace.id)
        .all()
    )
    templates = [normalize_role_template(template, role) for template, role in rows]
    return ExperienceActivationMembers(
        total=len(templates),
        studio_editors=sum(1 for template in templates if template in STUDIO_EDITOR_TEMPLATES),
        studio_reviewers=sum(1 for template in templates if template == WORKSPACE_REVIEWER),
    )


def _state(db: DBSession, workspace: Workspace) -> ExperienceActivationState:
    return ExperienceActivationState(
        enabled=experience_v1_enabled(workspace),
        studio_enabled=experience_studio_v1_enabled(workspace),
        members=_members(db, workspace),
    )


@router.get(
    "/workspaces/{slug}/features/experience",
    response_model=ExperienceActivationState,
)
async def get_experience_activation(
    slug: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)
    return _state(db, workspace)


@router.put(
    "/workspaces/{slug}/features/experience",
    response_model=ExperienceActivationState,
)
async def set_experience_activation(
    slug: str,
    body: ExperienceActivationUpdate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    workspace, membership = _lock_workspace_and_role_for_membership_mutation(db, user, workspace)
    _require_admin(membership)

    current = experience_v1_enabled(workspace)
    if current != body.expected_enabled:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKSPACE_FEATURE_CONFLICT",
                "message": "Work was changed by someone else since it was read; read it again.",
                "feature": FEATURE_KEY,
                "current_enabled": current,
            },
        )

    if current != body.enabled:
        next_settings = dict(workspace.settings) if isinstance(workspace.settings, Mapping) else {}
        features = next_settings.get("features")
        next_features = dict(features) if isinstance(features, Mapping) else {}
        next_features[FEATURE_KEY] = body.enabled
        next_settings["features"] = next_features
        workspace.settings = next_settings
        emit_audit_event(
            event_type="workspace.feature.updated",
            workspace_id=workspace.id,
            actor=user.id,
            details={"feature": FEATURE_KEY, "before": current, "after": body.enabled},
            db=db,
        )
    db.commit()
    db.refresh(workspace)
    return _state(db, workspace)
