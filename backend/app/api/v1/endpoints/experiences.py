"""Experience draft / release / deploy HTTP surface.

Feature-gated by ``settings.features.experience_v1``. A release is immutable
evidence; it does not move a channel pointer.
"""

from __future__ import annotations

from datetime import datetime
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
    description: Optional[str] = Field(default=None, max_length=500)
    emblem: Optional[str] = Field(default=None, max_length=32)
    slug: str = Field(min_length=1, max_length=120)
    pattern: str = Field(min_length=1, max_length=32)
    languages: list[str] = Field(default_factory=list)
    theme: dict[str, Any] = Field(default_factory=dict)
    access_policy: dict[str, Any] = Field(default_factory=dict)


class ExperiencePatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=500)
    emblem: Optional[str] = Field(default=None, max_length=32)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=120)
    pattern: Optional[str] = Field(default=None, min_length=1, max_length=32)
    languages: Optional[list[str]] = None
    theme: Optional[dict[str, Any]] = None
    access_policy: Optional[dict[str, Any]] = None
    expected_updated_at: Optional[datetime] = None


class DraftSaveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pages: dict[str, Any]
    binding_keys: list[str] = Field(default_factory=list)
    expected_revision: int = Field(ge=1)


class DraftRestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


class StagedBindingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_key: str = Field(min_length=1, max_length=120)
    system_id: str = Field(min_length=1, max_length=36)
    published_flow_version_id: str = Field(min_length=1, max_length=36)
    ingress_id: str = Field(min_length=1, max_length=160)
    confirmation_policy: str = "confirm"
    on_unavailable: str = "unavailable"


class DraftFinalizeBody(DraftSaveBody):
    bindings: list[StagedBindingBody] = Field(default_factory=list)
    description: Optional[str] = Field(default=None, max_length=500)
    emblem: Optional[str] = Field(default=None, max_length=32)
    languages: list[str]
    theme: dict[str, Any]
    access_policy: dict[str, Any]
    expected_experience_updated_at: datetime


class ExperienceCreateFinalizeBody(ExperienceCreateBody):
    pages: dict[str, Any]
    binding_keys: list[str] = Field(default_factory=list)
    bindings: list[StagedBindingBody] = Field(default_factory=list)


class ReleaseCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str = Field(min_length=1)
    expected_draft_revision: int = Field(ge=1)
    expected_content_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    expected_experience_updated_at: datetime
    expected_bindings_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )


class DeployBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str = Field(min_length=1, max_length=16)
    release_id: str = Field(min_length=1, max_length=36)
    expected_current_release_id: Optional[str] = Field(min_length=1, max_length=36)
    expected_deployment_updated_at: Optional[datetime]
    audience: Optional[dict[str, Any]] = None


class RollbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_id: str = Field(min_length=1, max_length=36)
    expected_current_release_id: str = Field(min_length=1, max_length=36)
    expected_deployment_updated_at: datetime


def _raise_experience(db: DBSession, exc: experience_service.ExperienceError) -> None:
    db.rollback()
    raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _require_runtime_enabled(workspace: Workspace) -> None:
    try:
        binding_service.require_experience_v1(workspace)
    except binding_service.BindingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _require_studio_enabled(workspace: Workspace) -> None:
    try:
        binding_service.require_experience_studio_v1(workspace)
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


def _enforce_binding_manage(db: DBSession, *, user: User, workspace: Workspace) -> None:
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="binding",
        action="manage",
        legacy_allowed=_legacy_role(db, user=user, workspace=workspace, allowed=_EDIT_ROLES),
        resource_attrs={"scope": "collection"},
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


def _materialize_binding(
    db: DBSession,
    *,
    workspace: Workspace,
    actor: str,
    spec: StagedBindingBody,
) -> None:
    """Create a staged binding, or accept an identical one on a safe retry."""

    try:
        existing = binding_service.get_binding(
            db,
            workspace_id=workspace.id,
            binding_key=spec.binding_key,
        )
    except binding_service.BindingError as exc:
        if exc.code != "BINDING_NOT_FOUND":
            raise
        binding_service.create_binding(
            db,
            workspace=workspace,
            actor=actor,
            binding_key=spec.binding_key,
            system_id=spec.system_id,
            published_flow_version_id=spec.published_flow_version_id,
            ingress_id=spec.ingress_id,
            confirmation_policy=spec.confirmation_policy,
            on_unavailable=spec.on_unavailable,
        )
        return

    requested = (
        spec.system_id,
        spec.published_flow_version_id,
        spec.ingress_id,
        spec.confirmation_policy,
        spec.on_unavailable,
    )
    actual = (
        existing.system_id,
        existing.published_flow_version_id,
        existing.ingress_id,
        existing.confirmation_policy,
        existing.on_unavailable,
    )
    if actual != requested:
        raise binding_service.BindingError(
            code="BINDING_KEY_EXISTS",
            message="A different binding with this key already exists in the workspace.",
            status_code=409,
            details={"binding_key": spec.binding_key},
        )


def _validate_staged_bindings(
    *,
    pages: dict[str, Any],
    binding_keys: list[str],
    bindings: list[StagedBindingBody],
) -> None:
    declared = set(binding_keys)
    referenced = set(experience_service.referenced_binding_keys(pages))
    staged: set[str] = set()
    for spec in bindings:
        key = spec.binding_key
        if key in staged:
            raise experience_service.ExperienceError(
                code="STAGED_BINDING_DUPLICATE",
                message="A staged binding key may only appear once.",
                status_code=422,
                details={"binding_key": key},
            )
        staged.add(key)
        if key not in declared or key not in referenced:
            raise experience_service.ExperienceError(
                code="STAGED_BINDING_UNUSED",
                message="Every staged binding must be declared and used by the draft.",
                status_code=422,
                details={"binding_key": key},
            )


@router.get("")
async def list_experiences(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_runtime_enabled(workspace)
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
    _require_runtime_enabled(workspace)
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
    _require_studio_enabled(workspace)
    _enforce_edit(db, user=user, workspace=workspace)
    try:
        row, draft = experience_service.create_experience(
            db,
            workspace=workspace,
            actor=_actor(user),
            name=body.name,
            description=body.description,
            emblem=body.emblem,
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


@router.post("/finalize", status_code=201)
async def create_finalized_experience(
    body: ExperienceCreateFinalizeBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create the Experience, its bindings, and first usable draft atomically."""

    _require_studio_enabled(workspace)
    _enforce_edit(db, user=user, workspace=workspace)
    if body.bindings:
        _enforce_binding_manage(db, user=user, workspace=workspace)
    actor = _actor(user)
    try:
        _validate_staged_bindings(
            pages=body.pages,
            binding_keys=body.binding_keys,
            bindings=body.bindings,
        )
        row, draft = experience_service.create_experience(
            db,
            workspace=workspace,
            actor=actor,
            name=body.name,
            description=body.description,
            emblem=body.emblem,
            slug=body.slug,
            pattern=body.pattern,
            languages=body.languages,
            theme=body.theme,
            access_policy=body.access_policy,
        )
        for spec in body.bindings:
            _materialize_binding(
                db,
                workspace=workspace,
                actor=actor,
                spec=spec,
            )
        draft = experience_service.save_draft(
            db,
            workspace_id=workspace.id,
            experience_id=row.id,
            pages=body.pages,
            binding_keys=body.binding_keys,
            expected_revision=1,
            actor=actor,
        )
        db.commit()
        db.refresh(row)
        db.refresh(draft)
    except binding_service.BindingError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
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
    _require_studio_enabled(workspace)
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
    _require_studio_enabled(workspace)
    _enforce_edit(db, user=user, workspace=workspace)
    try:
        row = experience_service.update_experience(
            db,
            workspace_id=workspace.id,
            experience_id=experience_id,
            name=body.name,
            description=body.description,
            emblem=body.emblem,
            set_description="description" in body.model_fields_set,
            set_emblem="emblem" in body.model_fields_set,
            slug=body.slug,
            pattern=body.pattern,
            languages=body.languages,
            theme=body.theme,
            access_policy=body.access_policy,
            expected_updated_at=body.expected_updated_at,
            actor=_actor(user),
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
    _require_studio_enabled(workspace)
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


@router.get("/{experience_id}/draft/revisions")
async def list_experience_draft_revisions(
    experience_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_studio_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    try:
        rows = experience_service.list_draft_history(
            db,
            workspace_id=workspace.id,
            experience_id=experience_id,
        )
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
    return {
        "revisions": [experience_service.serialize_draft_history(row) for row in rows]
    }


@router.post("/{experience_id}/draft/revisions/{revision}/restore")
async def restore_experience_draft_revision(
    experience_id: str,
    revision: int,
    body: DraftRestoreBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_studio_enabled(workspace)
    _enforce_edit(db, user=user, workspace=workspace)
    try:
        draft = experience_service.restore_draft_history(
            db,
            workspace_id=workspace.id,
            experience_id=experience_id,
            revision=revision,
            expected_revision=body.expected_revision,
            actor=_actor(user),
        )
        db.commit()
        db.refresh(draft)
    except experience_service.ExperienceError as exc:
        _raise_experience(db, exc)
    return experience_service.serialize_draft(draft)


@router.put("/{experience_id}/draft/finalize")
async def finalize_experience_draft(
    experience_id: str,
    body: DraftFinalizeBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Atomically materialise wizard bindings, draft content, and access."""

    _require_studio_enabled(workspace)
    _enforce_edit(db, user=user, workspace=workspace)
    if body.bindings:
        _enforce_binding_manage(db, user=user, workspace=workspace)
    actor = _actor(user)
    try:
        _validate_staged_bindings(
            pages=body.pages,
            binding_keys=body.binding_keys,
            bindings=body.bindings,
        )
        for spec in body.bindings:
            _materialize_binding(
                db,
                workspace=workspace,
                actor=actor,
                spec=spec,
            )
        draft = experience_service.save_draft(
            db,
            workspace_id=workspace.id,
            experience_id=experience_id,
            pages=body.pages,
            binding_keys=body.binding_keys,
            expected_revision=body.expected_revision,
            actor=actor,
        )
        experience_service.update_experience(
            db,
            workspace_id=workspace.id,
            experience_id=experience_id,
            description=body.description,
            emblem=body.emblem,
            set_description="description" in body.model_fields_set,
            set_emblem="emblem" in body.model_fields_set,
            languages=body.languages,
            theme=body.theme,
            access_policy=body.access_policy,
            expected_updated_at=body.expected_experience_updated_at,
            actor=actor,
        )
        db.commit()
        db.refresh(draft)
    except binding_service.BindingError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
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
    _require_studio_enabled(workspace)
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
    _require_studio_enabled(workspace)
    _enforce_release(db, user=user, workspace=workspace)
    try:
        row = experience_service.create_release(
            db,
            workspace=workspace,
            experience_id=experience_id,
            notes=body.notes,
            expected_draft_revision=body.expected_draft_revision,
            expected_content_sha256=body.expected_content_sha256,
            expected_experience_updated_at=body.expected_experience_updated_at,
            expected_bindings_sha256=body.expected_bindings_sha256,
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
    _require_runtime_enabled(workspace)
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
    _require_studio_enabled(workspace)
    _enforce_deploy(db, user=user, workspace=workspace)
    try:
        row = experience_service.deploy(
            db,
            workspace=workspace,
            experience_id=experience_id,
            channel=body.channel,
            release_id=body.release_id,
            expected_current_release_id=body.expected_current_release_id,
            expected_deployment_updated_at=body.expected_deployment_updated_at,
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
    body: RollbackBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_studio_enabled(workspace)
    _enforce_deploy(db, user=user, workspace=workspace)
    try:
        row = experience_service.rollback_deployment(
            db,
            workspace=workspace,
            experience_id=experience_id,
            channel=channel,
            release_id=body.release_id,
            expected_current_release_id=body.expected_current_release_id,
            expected_deployment_updated_at=body.expected_deployment_updated_at,
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
    _require_studio_enabled(workspace)
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
