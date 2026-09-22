"""Business /work catalogue, immutable release resolver, and invocation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import current_membership
from app.core.iam.roles import WORKSPACE_ADMIN, is_admin_template, normalize_role_template
from app.db.base import get_db
from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.chat_execution_policy import migration_059_system_id
from app.services.experience import bindings as binding_service
from app.services.experience import lifecycle as experience_service
from app.services.iam.config_service import load_iam_config
from app.services.iam.decision_plane import (
    ModeResolutionCache,
    emit_shadow_diff_summary,
    enforce_action,
    resolve_action,
)
from app.services.run_access import run_read_attrs
from app.services.run_engine.dispatch_outbox import (
    TRIGGER_RUN,
    durable_initial_dispatch_source,
    enqueue_dispatch,
    reconcile_dispatch_outbox,
)

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


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _idempotent_run(
    db: DBSession,
    *,
    workspace_id: str,
    experience_idempotency_key: str,
    request_sha256: str,
) -> Run | None:
    run = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace_id,
            Run.experience_idempotency_key == experience_idempotency_key,
        )
        .one_or_none()
    )
    if run is None:
        return None
    ingress = (run.input_ref or {}).get("_ingress")
    adapter = ingress.get("adapter") if isinstance(ingress, dict) else None
    if not isinstance(adapter, dict) or adapter.get("request_sha256") != request_sha256:
        raise experience_service.ExperienceError(
            code="WORK_IDEMPOTENCY_KEY_REUSED",
            message="This Idempotency-Key was already used for a different request.",
            status_code=409,
        )
    return run


def _work_run_response(run: Run, *, replayed: bool) -> dict[str, Any]:
    ingress = (run.input_ref or {}).get("_ingress")
    adapter = ingress.get("adapter") if isinstance(ingress, dict) else None
    provenance = adapter if isinstance(adapter, dict) else {}
    public_provenance = {
        field: provenance.get(field)
        for field in (
            "surface",
            "origin",
            "experience_id",
            "experience_slug",
            "experience_release_id",
            "experience_deployment_id",
            "channel",
            "binding_key",
            "page_id",
            "component_id",
        )
    }
    return {
        "id": run.id,
        "status": run.status,
        "execution_surface": run.execution_surface,
        "idempotent_replay": replayed,
        **public_provenance,
    }


def _ensure_work_dispatch(db: DBSession, run: Run) -> None:
    """Persist the initial handoff in the same transaction as the Run."""
    source = durable_initial_dispatch_source(run)
    if source is None or not run.workspace_id:
        raise RuntimeError("Experience Run has no durable dispatch claim")
    enqueue_dispatch(
        db,
        event_type=TRIGGER_RUN,
        workspace_id=str(run.workspace_id),
        run_id=run.id,
        source_id=source,
    )


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


@router.get("/{slug}/validations")
async def list_work_validations(
    slug: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Project only HITL items this user is actually authorised to decide."""
    _require_enabled(workspace)
    _enforce_consume(db, user=user, workspace=workspace)
    try:
        _experience, _deployment, release = _resolve_for_user(
            db, workspace=workspace, user=user, slug=slug
        )
        identity = experience_service.release_identity(release)
    except experience_service.ExperienceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    origin = f"experience:{identity['slug']}"
    bound_system_ids = {
        str(item.get("system_id"))
        for item in (release.bindings_snapshot or [])
        if isinstance(item, dict) and item.get("system_id")
    }
    # The queue is the paused Run itself. A decision on a bound System counts
    # even when Work did not start it. Scheduled ticks stay out: they are not
    # someone's approval.
    membership = [
        Run.input_ref["_ingress"]["adapter"]["origin"].as_string() == origin,
    ]
    if bound_system_ids:
        membership.append(
            and_(
                Run.system_id.in_(bound_system_ids),
                or_(Run.trigger.is_(None), Run.trigger != "scheduler"),
            )
        )
    rows = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace.id,
            Run.status == "hitl_pending",
            or_(*membership),
        )
        .order_by(Run.started_at.desc())
        .yield_per(100)
    )
    membership = current_membership(db, user, workspace)
    admin = getattr(user, "role", None) == "admin" or bool(
        membership and is_admin_template(membership.role_template, membership.role)
    )
    config = load_iam_config(db, workspace.id, create=False)
    mode_cache: ModeResolutionCache = {}
    managed_system_id = migration_059_system_id(workspace)
    visible: list[dict[str, Any]] = []
    resolutions = []

    def project_batch(batch: list[Run]) -> None:
        system_ids = {str(run.system_id) for run in batch if run.system_id}
        known_system_ids = {
            row[0]
            for row in db.query(System.id)
            .filter(System.workspace_id == workspace.id, System.id.in_(system_ids))
            .all()
        } if system_ids else set()
        decision_ids = {
            checkpoint.get("decision_id")
            for run in batch
            for checkpoint in list(run.checkpoints or [])
            if isinstance(checkpoint, dict)
            and checkpoint.get("kind") == "hitl_pause"
            and checkpoint.get("decision_id")
        }
        decision_status = {
            row.id: row.status
            for row in db.query(Decision.id, Decision.status)
            .filter(
                Decision.id.in_(decision_ids),
                or_(
                    Decision.workspace_id == workspace.id,
                    Decision.workspace_id.is_(None),
                ),
            )
            .all()
        } if decision_ids else {}
        managed_decision_ids = {
            row[0]
            for row in db.query(Decision.id)
            .join(Run, Decision.target_id == Run.id)
            .filter(
                Decision.id.in_(decision_ids),
                Decision.scope == "run",
                or_(
                    Decision.workspace_id == workspace.id,
                    Decision.workspace_id.is_(None),
                ),
                Run.workspace_id == workspace.id,
                Run.system_id == managed_system_id,
            )
            .all()
        } if managed_system_id and decision_ids else set()

        for run in batch:
            managed = run.system_id == managed_system_id or any(
                isinstance(checkpoint, dict)
                and checkpoint.get("decision_id") in managed_decision_ids
                for checkpoint in list(run.checkpoints or [])
            )
            if managed and not admin:
                continue
            lineage_valid = not run.system_id or str(run.system_id) in known_system_ids
            legacy_allowed = lineage_valid and (
                admin or run.initiated_by_user_id == user.id
            )
            resolution = resolve_action(
                db,
                user=user,
                workspace=workspace,
                resource_kind="run",
                action="approve",
                legacy_allowed=legacy_allowed,
                resource_attrs=run_read_attrs(run),
                membership=membership,
                config=config,
                mode_cache=mode_cache,
                audit_shadow_diff=False,
                audit_shadow_evidence=False,
            )
            resolutions.append((run.id, resolution))
            if not resolution.effective_allowed:
                continue
            checkpoint = next(
                (
                    item
                    for item in reversed(list(run.checkpoints or []))
                    if isinstance(item, dict) and item.get("kind") == "hitl_pause"
                ),
                {},
            )
            visible.append(
                {
                    "id": run.id,
                    "system_id": run.system_id,
                    "capability_id": run.capability_id,
                    "status": run.status,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "hitl": {
                        "node_id": checkpoint.get("node_id"),
                        "prompt": checkpoint.get("prompt"),
                        "decision_id": checkpoint.get("decision_id"),
                        "decision_title": checkpoint.get("decision_title"),
                        "decision_status": decision_status.get(checkpoint.get("decision_id")),
                        "expires_at": checkpoint.get("expires_at"),
                    },
                }
            )
            if len(visible) == 100:
                return

    batch: list[Run] = []
    for run in rows.execution_options(stream_results=True).yield_per(200):
        batch.append(run)
        if len(batch) < 200:
            continue
        project_batch(batch)
        if len(visible) == 100:
            break
        batch = []
    if batch and len(visible) < 100:
        project_batch(batch)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind="run",
        action="approve",
        resolutions=resolutions,
    )
    return {"runs": visible}


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
    idempotency_key: str = Header(
        ..., alias="Idempotency-Key", min_length=16, max_length=160
    ),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_consume(db, user=user, workspace=workspace)
    try:
        request_sha256 = _canonical_sha256(
            {
                "binding_key": key,
                "component_id": body.component_id,
                "confirmed": body.confirmed,
                "page_id": body.page_id,
                "payload": body.payload,
                "slug": slug,
            }
        )
        experience_idempotency_key = _canonical_sha256(
            {
                "binding_key": key,
                "idempotency_key": idempotency_key,
                "slug": slug,
                "user_id": getattr(user, "id", None),
                "workspace_id": workspace.id,
            }
        )
        run = _idempotent_run(
            db,
            workspace_id=workspace.id,
            experience_idempotency_key=experience_idempotency_key,
            request_sha256=request_sha256,
        )
        if run is not None:
            # Idempotency preserves the original Run identity, not stale access.
            # Re-resolve the currently deployed app before revealing or
            # rescheduling it so a withdrawn audience takes effect immediately.
            _resolve_for_user(db, workspace=workspace, user=user, slug=slug)
            if run.status in {"pending", "running"}:
                _ensure_work_dispatch(db, run)
                db.commit()
                background_tasks.add_task(reconcile_dispatch_outbox)
            return _work_run_response(run, replayed=True)
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
        dedup_key = f"experience:{experience_idempotency_key}"
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
        adapter_provenance = {**provenance, "request_sha256": request_sha256}
        replayed = False
        try:
            with db.begin_nested():
                run = binding_service.invoke_binding_snapshot(
                    db,
                    workspace=workspace,
                    snapshot=snapshot,
                    payload=body.payload,
                    confirmed=body.confirmed,
                    initiated_by_user_id=getattr(user, "id", None),
                    actor=_actor(user),
                    provenance=adapter_provenance,
                    trigger_dedup_key=dedup_key,
                    experience_idempotency_key=experience_idempotency_key,
                )
        except IntegrityError:
            run = _idempotent_run(
                db,
                workspace_id=workspace.id,
                experience_idempotency_key=experience_idempotency_key,
                request_sha256=request_sha256,
            )
            if run is None:
                raise
            replayed = True
        _ensure_work_dispatch(db, run)
        db.commit()
        db.refresh(run)
    except experience_service.ExperienceError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    except binding_service.BindingError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.payload()) from exc
    if run.status in {"pending", "running"}:
        background_tasks.add_task(reconcile_dispatch_outbox)
    return _work_run_response(run, replayed=replayed)
