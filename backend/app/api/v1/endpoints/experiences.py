"""Experience draft / release / deploy HTTP surface.

Feature-gated by ``settings.features.experience_v1``. A release is immutable
evidence; it does not move a channel pointer.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import current_membership
from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_OWNER,
    WORKSPACE_REVIEWER,
    normalize_role_template,
)
from app.db.base import get_db
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_access import enforce_audit_read
from app.services.experience import bindings as binding_service
from app.services.experience import lifecycle as experience_service
from app.services.iam.decision_plane import enforce_action

router = APIRouter()

_EDIT_ROLES = {WORKSPACE_CONTRIBUTOR, WORKSPACE_ADMIN, WORKSPACE_OWNER}
_VIEW_ROLES = _EDIT_ROLES | {WORKSPACE_REVIEWER}
_RELEASE_ROLES = {WORKSPACE_REVIEWER, WORKSPACE_ADMIN, WORKSPACE_OWNER}
_DEPLOY_ROLES = {WORKSPACE_REVIEWER, WORKSPACE_ADMIN, WORKSPACE_OWNER}


class ExperienceCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=120)
    pattern: str = Field(min_length=1, max_length=32)
    languages: list[str] = Field(default_factory=list)
    theme: dict[str, Any] = Field(default_factory=dict)
    access_policy: dict[str, Any] = Field(default_factory=dict)


class ExperiencePatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=120)
    pattern: Optional[str] = Field(default=None, min_length=1, max_length=32)
    languages: Optional[list[str]] = None
    theme: Optional[dict[str, Any]] = None
    access_policy: Optional[dict[str, Any]] = None


class DraftSaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pages: dict[str, Any]
    binding_keys: list[str] = Field(default_factory=list)
    expected_revision: int = Field(ge=1)


class ReleaseCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str = Field(min_length=1)
    expected_draft_revision: int = Field(ge=1)
    expected_content_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class DeployBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str = Field(min_length=1, max_length=16)
    release_id: str = Field(min_length=1, max_length=36)
    audience: Optional[dict[str, Any]] = None


class RollbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: Optional[str] = Field(default=None, min_length=1, max_length=36)


def _raise_experience(db: DBSession, exc: experience_service.ExperienceError) -> None:
    db.rollback()
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _require_enabled(workspace: Workspace) -> None:
    try:
        binding_service.require_experience_v1(workspace)
    except binding_service.BindingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _actor(user: User) -> str:
    for field in ("email", "username", "id"):
        value = str(getattr(user, field, "") or "").strip()
        if value:
            return value
    return "unknown"


def _legacy_role(db: DBSession, *, user: User, workspace: Workspace, allowed: set[str]) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    membership = current_membership(db, user, workspace)
    if membership is None:
        return False
    return normalize_role_template(membership.role_template, membership.role) in allowed


def _enforce(db: DBSession, *, user: User, workspace: Workspace, action: str, legacy_allowed: bool) -> None:
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="experience",
        action=action,
        legacy_allowed=legacy_allowed,
        resource_attrs={"scope": "collection"},
    )


def _enforce_view(db: DBSession, *, user: User, workspace: Workspace) -> None:
    _enforce(
        db,
        user=user,
        workspace=workspace,
        action="view",
        legacy_allowed=_legacy_role(db, user=user, workspace=workspace, allowed=_VIEW_ROLES),
    )


def _enforce_edit(db: DBSession, *, user: User, workspace: Workspace) -> None:
    _enforce(
        db,
        user=user,
        workspace=workspace,
        action="edit",
        legacy_allowed=_legacy_role(db, user=user, workspace=workspace, allowed=_EDIT_ROLES),
    )


def _enforce_release(db: DBSession, *, user: User, workspace: Workspace) -> None:
    _enforce(
        db,
        user=user,
        workspace=workspace,
        action="release",
        legacy_allowed=_legacy_role(db, user=user, workspace=workspace, allowed=_RELEASE_ROLES),
    )


def _enforce_deploy(db: DBSession, *, user: User, workspace: Workspace) -> None:
    _enforce(
        db,
        user=user,
        workspace=workspace,
        action="deploy",
        legacy_allowed=_legacy_role(db, user=user, workspace=workspace, allowed=_DEPLOY_ROLES),
    )


@router.get("")
async def list_experiences(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    rows = experience_service.list_experiences(db, workspace_id=workspace.id)
    deployments = experience_service.list_deployments_for_workspace(
        db, workspace_id=workspace.id
    )
    extras = experience_service.inventory_index(db, workspace_id=workspace.id)
    by_id: dict[str, list] = {}
    for item in deployments:
        by_id.setdefault(item.experience_id, []).append(item)
    listed: list[dict] = []
    for row in rows:
        payload = experience_service.serialize_experience(
            row, deployments=by_id.get(row.id, [])
        )
        payload.update(extras.get(row.id, {
            "binding_keys": [],
            "draft_revision": None,
            "latest_release_number": None,
        }))
        listed.append(payload)
    return {"experiences": listed}


@router.get("/audit")
async def list_experience_audit(
    limit: int = Query(50, ge=1, le=500),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Experience events from the existing audit store. Prefix: ``experience.``

    Same read authority as ``GET /api/v1/audit``. Equivalent filter:
    ``GET /api/v1/audit?event_type_prefix=experience.``
    """
    _require_enabled(workspace)
    enforce_audit_read(db, user=user, workspace=workspace)
    logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type.startswith("experience."),
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return {
        "logs": [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "event_type": log.event_type,
                "actor": log.actor,
                "details": log.details,
                "trace_id": log.trace_id,
                "agent_id": log.agent_id,
                "severity": log.severity,
            }
            for log in logs
        ],
        "total": len(logs),
    }


@router.post("", status_code=201)
async def create_experience(
    body: ExperienceCreateBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_edit(db, user=user, workspace=workspace)
    try:
        row, draft = experience_service.create_experience(
            db,
            workspace=workspace,
            actor=_actor(user),
            name=body.name,
            slug=body.slug,
            pattern=body.pattern,
            languages=body.languages,
            theme=body.theme,
            access_policy=body.access_policy,
        )
        db.commit()
        db.refresh(row)
        db.refresh(draft)
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
    return experience_service.serialize_detail(row, draft, [])


@router.get("/{experience_id}")
async def get_experience(
    experience_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    try:
        row, draft, deployments = experience_service.get_experience(
            db, workspace_id=workspace.id, experience_id=experience_id
        )
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
    return experience_service.serialize_detail(row, draft, deployments)


@router.patch("/{experience_id}")
async def patch_experience(
    experience_id: str,
    body: ExperiencePatchBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_edit(db, user=user, workspace=workspace)
    try:
        row = experience_service.update_experience(
            db,
            workspace_id=workspace.id,
            experience_id=experience_id,
            name=body.name,
            slug=body.slug,
            pattern=body.pattern,
            languages=body.languages,
            theme=body.theme,
            access_policy=body.access_policy,
        )
        db.commit()
        row, draft, deployments = experience_service.get_experience(
            db, workspace_id=workspace.id, experience_id=row.id
        )
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
    return experience_service.serialize_detail(row, draft, deployments)


@router.put("/{experience_id}/draft")
async def save_experience_draft(
    experience_id: str,
    body: DraftSaveBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_edit(db, user=user, workspace=workspace)
    try:
        draft = experience_service.save_draft(
            db,
            workspace_id=workspace.id,
            experience_id=experience_id,
            pages=body.pages,
            binding_keys=body.binding_keys,
            expected_revision=body.expected_revision,
            actor=_actor(user),
        )
        db.commit()
        db.refresh(draft)
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
    return experience_service.serialize_draft(draft)


@router.get("/{experience_id}/ready-check")
async def experience_ready_check(
    experience_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    try:
        return experience_service.ready_check(
            db, workspace=workspace, experience_id=experience_id
        )
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)


@router.post("/{experience_id}/releases", status_code=201)
async def create_experience_release(
    experience_id: str,
    body: ReleaseCreateBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_release(db, user=user, workspace=workspace)
    try:
        row = experience_service.create_release(
            db,
            workspace=workspace,
            experience_id=experience_id,
            notes=body.notes,
            expected_draft_revision=body.expected_draft_revision,
            expected_content_sha256=body.expected_content_sha256,
            actor=_actor(user),
        )
        db.commit()
        db.refresh(row)
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
    return experience_service.serialize_release(row)


@router.get("/{experience_id}/releases")
async def list_experience_releases(
    experience_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    try:
        rows = experience_service.list_releases(
            db, workspace_id=workspace.id, experience_id=experience_id
        )
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
    return {"releases": [experience_service.serialize_release(row) for row in rows]}


@router.post("/{experience_id}/deployments", status_code=201)
async def deploy_experience(
    experience_id: str,
    body: DeployBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_deploy(db, user=user, workspace=workspace)
    try:
        row = experience_service.deploy(
            db,
            workspace=workspace,
            experience_id=experience_id,
            channel=body.channel,
            release_id=body.release_id,
            audience=body.audience,
            actor=_actor(user),
        )
        db.commit()
        db.refresh(row)
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
    return experience_service.serialize_deployment(row)


@router.post("/{experience_id}/deployments/{channel}/rollback")
async def rollback_experience_deployment(
    experience_id: str,
    channel: str,
    body: RollbackBody | None = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_deploy(db, user=user, workspace=workspace)
    payload = body or RollbackBody()
    try:
        row = experience_service.rollback_deployment(
            db,
            workspace=workspace,
            experience_id=experience_id,
            channel=channel,
            release_id=payload.release_id,
            actor=_actor(user),
        )
        db.commit()
        db.refresh(row)
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
    return experience_service.serialize_deployment(row)


@router.delete("/{experience_id}", status_code=204)
async def delete_experience(
    experience_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_edit(db, user=user, workspace=workspace)
    try:
        experience_service.delete_experience(
            db,
            workspace_id=workspace.id,
            experience_id=experience_id,
            actor=_actor(user),
        )
        db.commit()
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
