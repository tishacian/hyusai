"""Business /work catalogue, immutable release resolver, and invocation."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
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
from app.services.run_engine import schedule_run

router = APIRouter()


class WorkRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any] = Field(default_factory=dict)
    confirmed: Optional[bool] = None
    page_id: Optional[str] = Field(default=None, min_length=1, max_length=160)
    component_id: Optional[str] = Field(default=None, min_length=1, max_length=160)


def _require_enabled(workspace: Workspace) -> None:
    try:
        binding_service.require_experience_v1(workspace)
    except binding_service.BindingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc


def _enforce_consume(db: DBSession, *, user: User, workspace: Workspace) -> None:
    membership = current_membership(db, user, workspace)
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="experience",
        action="consume",
        legacy_allowed=getattr(user, "role", None) == "admin" or membership is not None,
        resource_attrs={"scope": "collection"},
    )


def _viewer_claims(
    db: DBSession, *, user: User, workspace: Workspace
) -> tuple[str, tuple[str, ...]]:
    membership = current_membership(db, user, workspace)
    role = (
        WORKSPACE_ADMIN
        if getattr(user, "role", None) == "admin"
        else normalize_role_template(membership.role_template, membership.role)
        if membership is not None
        else ""
    )
    raw_groups = membership.custom_labels if membership is not None else []
    groups = (
        tuple(item for item in raw_groups)
        if isinstance(raw_groups, list)
        and all(
            isinstance(item, str) and item and item == item.strip()
            for item in raw_groups
        )
        else ()
    )
    return role, groups


def _actor(user: User) -> str:
    for field in ("email", "username", "id"):
        value = str(getattr(user, field, "") or "").strip()
        if value:
            return value
    return "unknown"


def _resolve_for_user(
    db: DBSession, *, workspace: Workspace, user: User, slug: str
):
    role, groups = _viewer_claims(db, user=user, workspace=workspace)
    return experience_service.resolve_work(
        db,
        workspace_id=workspace.id,
        slug=slug,
        role=role,
        groups=groups,
    )


@router.get("")
async def list_work_apps(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_consume(db, user=user, workspace=workspace)
    role, groups = _viewer_claims(db, user=user, workspace=workspace)
    rows = experience_service.list_work(
        db, workspace_id=workspace.id, role=role, groups=groups
    )
    return {
        "experiences": [
            experience_service.serialize_work_catalog_item(*item) for item in rows
        ]
    }


@router.get("/{slug}")
async def get_work_app(
    slug: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_consume(db, user=user, workspace=workspace)
    try:
        experience, deployment, release = _resolve_for_user(
            db, workspace=workspace, user=user, slug=slug
        )
    except experience_service.ExperienceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    return experience_service.serialize_work(experience, deployment, release)


@router.get("/{slug}/bindings/{key}/resolve")
async def resolve_work_binding(
    slug: str,
    key: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_consume(db, user=user, workspace=workspace)
    try:
        experience, deployment, release = _resolve_for_user(
            db, workspace=workspace, user=user, slug=slug
        )
        snapshot = experience_service.work_binding_snapshot(release, binding_key=key)
        resolved = binding_service.resolve_binding_snapshot(
            db, workspace=workspace, snapshot=snapshot
        )
        identity = experience_service.release_identity(release)
    except experience_service.ExperienceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    except binding_service.BindingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    return {
        **experience_service.serialize_public_binding_resolution(resolved),
        "experience_slug": identity["slug"],
        "experience_release_id": release.id,
        "experience_deployment_id": deployment.id,
        "channel": deployment.channel,
        "origin": f"experience:{identity['slug']}",
    }


@router.post("/{slug}/bindings/{key}/runs", status_code=201)
async def invoke_work_binding(
    slug: str,
    key: str,
    body: WorkRunBody,
    background_tasks: BackgroundTasks,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_consume(db, user=user, workspace=workspace)
    try:
        experience, deployment, release = _resolve_for_user(
            db, workspace=workspace, user=user, slug=slug
        )
        snapshot = experience_service.work_binding_snapshot(release, binding_key=key)
        page_id, component_id = experience_service.work_binding_context(
            release,
            binding_key=key,
            page_id=body.page_id,
            component_id=body.component_id,
        )
        identity = experience_service.release_identity(release)
        provenance = {
            "surface": "experience",
            "origin": f"experience:{identity['slug']}",
            "experience_id": experience.id,
            "experience_slug": identity["slug"],
            "experience_release_id": release.id,
            "experience_deployment_id": deployment.id,
            "channel": deployment.channel,
            "binding_key": key,
            "page_id": page_id,
            "component_id": component_id,
        }
        run = binding_service.invoke_binding_snapshot(
            db,
            workspace=workspace,
            snapshot=snapshot,
            payload=body.payload,
            confirmed=body.confirmed,
            initiated_by_user_id=getattr(user, "id", None),
            actor=_actor(user),
            provenance=provenance,
        )
        db.commit()
        db.refresh(run)
    except experience_service.ExperienceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    except binding_service.BindingError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    background_tasks.add_task(schedule_run, run.id)
    return {
        "id": run.id,
        "status": run.status,
        "execution_surface": run.execution_surface,
        **provenance,
    }
