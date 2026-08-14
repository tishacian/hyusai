"""SystemBinding HTTP surface. Feature-gated by ``settings.features.experience_v1``."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session as DBSession

from app.api.v1.endpoints.systems import _enforce_system_run_authority
from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import current_membership
from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_OWNER,
    normalize_role_template,
)
from app.db.base import get_db
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.experience import bindings as binding_service
from app.services.iam.decision_plane import enforce_action
from app.services.run_engine import schedule_run

router = APIRouter()

_MANAGE_ROLES = {WORKSPACE_CONTRIBUTOR, WORKSPACE_ADMIN, WORKSPACE_OWNER}


class BindingCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_key: str = Field(min_length=1, max_length=120)
    system_id: str = Field(min_length=1, max_length=36)
    published_flow_version_id: str = Field(min_length=1, max_length=36)
    ingress_id: str = Field(min_length=1, max_length=160)
    confirmation_policy: str = "confirm"
    on_unavailable: str = "unavailable"


class BindingPatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_policy: Optional[str] = None
    on_unavailable: Optional[str] = None
    published_flow_version_id: Optional[str] = Field(default=None, min_length=1, max_length=36)
    ingress_id: Optional[str] = Field(default=None, min_length=1, max_length=160)


class BindingRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any] = Field(default_factory=dict)
    confirmed: Optional[bool] = None


def _raise_binding(db: DBSession, exc: binding_service.BindingError) -> None:
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


def _legacy_binding_manage(db: DBSession, *, user: User, workspace: Workspace) -> bool:
    if getattr(user, "role", None) == "admin":
        return True
    membership = current_membership(db, user, workspace)
    if membership is None:
        return False
    return (
        normalize_role_template(membership.role_template, membership.role) in _MANAGE_ROLES
    )


def _enforce_view(db: DBSession, *, user: User, workspace: Workspace) -> None:
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="binding",
        action="view",
        legacy_allowed=True,
        resource_attrs={"scope": "collection"},
    )


def _enforce_manage(db: DBSession, *, user: User, workspace: Workspace) -> None:
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="binding",
        action="manage",
        legacy_allowed=_legacy_binding_manage(db, user=user, workspace=workspace),
        resource_attrs={"scope": "collection"},
    )


@router.get("")
async def list_system_bindings(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    rows = binding_service.list_bindings(db, workspace_id=workspace.id)
    return {"bindings": [binding_service.serialize_binding(row) for row in rows]}


@router.get("/drift")
async def list_drifted_system_bindings(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    return {"bindings": binding_service.list_drifted_bindings(db, workspace=workspace)}


@router.get("/{key}")
async def get_system_binding(
    key: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    try:
        row = binding_service.get_binding(db, workspace_id=workspace.id, binding_key=key)
    except binding_service.BindingError as exc:
        _raise_binding(db, exc)
    return binding_service.serialize_binding(row)


@router.get("/{key}/resolve")
async def resolve_system_binding(
    key: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    try:
        return binding_service.resolve_binding(db, workspace=workspace, binding_key=key)
    except binding_service.BindingError as exc:
        _raise_binding(db, exc)


@router.post("", status_code=201)
async def create_system_binding(
    body: BindingCreateBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_manage(db, user=user, workspace=workspace)
    try:
        row = binding_service.create_binding(
            db,
            workspace=workspace,
            actor=_actor(user),
            binding_key=body.binding_key,
            system_id=body.system_id,
            published_flow_version_id=body.published_flow_version_id,
            ingress_id=body.ingress_id,
            confirmation_policy=body.confirmation_policy,
            on_unavailable=body.on_unavailable,
        )
        db.commit()
        db.refresh(row)
    except binding_service.BindingError as exc:
        _raise_binding(db, exc)
    return binding_service.serialize_binding(row)


@router.patch("/{key}")
async def patch_system_binding(
    key: str,
    body: BindingPatchBody,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_manage(db, user=user, workspace=workspace)
    try:
        row = binding_service.update_binding(
            db,
            workspace=workspace,
            binding_key=key,
            confirmation_policy=body.confirmation_policy,
            on_unavailable=body.on_unavailable,
            published_flow_version_id=body.published_flow_version_id,
            ingress_id=body.ingress_id,
        )
        db.commit()
        db.refresh(row)
    except binding_service.BindingError as exc:
        _raise_binding(db, exc)
    return binding_service.serialize_binding(row)


@router.post("/{key}/retarget")
async def retarget_system_binding(
    key: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_manage(db, user=user, workspace=workspace)
    try:
        row = binding_service.retarget_binding(
            db,
            workspace=workspace,
            binding_key=key,
            actor=_actor(user),
        )
        db.commit()
        db.refresh(row)
    except binding_service.BindingError as exc:
        _raise_binding(db, exc)
    return binding_service.serialize_binding(row)


@router.delete("/{key}", status_code=204)
async def delete_system_binding(
    key: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_manage(db, user=user, workspace=workspace)
    try:
        binding_service.delete_binding(db, workspace_id=workspace.id, binding_key=key)
        db.commit()
    except binding_service.BindingError as exc:
        _raise_binding(db, exc)


@router.post("/{key}/runs", status_code=201)
async def invoke_system_binding(
    key: str,
    body: BindingRunBody,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_view(db, user=user, workspace=workspace)
    try:
        preview = binding_service.resolve_binding(db, workspace=workspace, binding_key=key)
    except binding_service.BindingError as exc:
        _raise_binding(db, exc)
    if preview["status"] != "ok":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BINDING_NOT_OK",
                "message": "The binding is not currently invokable.",
                **preview,
            },
        )
    system = (
        db.query(System)
        .filter(
            System.id == preview["binding"]["system_id"],
            System.workspace_id == workspace.id,
        )
        .one_or_none()
    )
    if system is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BINDING_NOT_OK",
                "status": "unavailable",
                "reasons": ["system_missing"],
                "binding": preview["binding"],
            },
        )
    _enforce_system_run_authority(
        db,
        user=user,
        workspace=workspace,
        system=system,
        execution_source="experience_binding_invoke",
    )
    try:
        run = binding_service.invoke_binding(
            db,
            workspace=workspace,
            binding_key=key,
            payload=body.payload,
            confirmed=body.confirmed,
            initiated_by_user_id=getattr(user, "id", None),
            actor=_actor(user),
        )
        db.commit()
        db.refresh(run)
    except binding_service.BindingError as exc:
        _raise_binding(db, exc)
    background_tasks.add_task(schedule_run, run.id)
    return {
        "id": run.id,
        "status": run.status,
        "system_id": run.system_id,
        "execution_surface": run.execution_surface,
        "published_flow_version_id": run.published_flow_version_id,
        "flow_sha256": run.flow_sha256,
        "ingress_id": preview["binding"]["ingress_id"],
        "binding_key": key,
        "origin": f"experience:{key}",
    }
