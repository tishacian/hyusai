"""Business /work catalogue, immutable release resolver, and invocation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import current_membership
from app.core.iam.roles import WORKSPACE_ADMIN, is_admin_template, normalize_role_template
from app.db.base import get_db
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.services import automation_portfolio
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
from app.services.experience.work_receipt import run_receipt
from app.services.run_access import readable_run_page, readable_runs, run_read_attrs
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


def _project_decidable_hitl(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    origin: str | None = None,
    bound_system_ids: set[str] | frozenset[str] = frozenset(),
    limit: int = 100,
    emit_shadow: bool = True,
    origins: set[str] | frozenset[str] = frozenset(),
    include_origin: bool = False,
) -> list[dict[str, Any]]:
    """HITL pauses this reader may decide — same rights filter as /{slug}/validations.

    ``origins`` widens one query to several apps (L33 home, no per-app loop);
    ``include_origin`` adds the ingress origin so the caller can name the app.
    """
    membership_clauses: list[Any] = []
    origin_col = Run.input_ref["_ingress"]["adapter"]["origin"].as_string()
    if origin:
        membership_clauses.append(origin_col == origin)
    if origins:
        membership_clauses.append(origin_col.in_(sorted(origins)))
    if bound_system_ids:
        # Scheduled ticks stay out: they are not someone's approval.
        membership_clauses.append(
            and_(
                Run.system_id.in_(bound_system_ids),
                or_(Run.trigger.is_(None), Run.trigger != "scheduler"),
            )
        )
    if not membership_clauses:
        return []
    rows = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace.id,
            Run.status == "hitl_pending",
            or_(*membership_clauses),
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
            projected = {
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
            if include_origin:
                projected["origin"] = _run_origin(run)
            visible.append(projected)
            if len(visible) == limit:
                return

    batch: list[Run] = []
    for run in rows.execution_options(stream_results=True).yield_per(200):
        batch.append(run)
        if len(batch) < 200:
            continue
        project_batch(batch)
        if len(visible) == limit:
            break
        batch = []
    if batch and len(visible) < limit:
        project_batch(batch)
    if emit_shadow:
        emit_shadow_diff_summary(
            workspace=workspace,
            user=user,
            resource_kind="run",
            action="approve",
            resolutions=resolutions,
        )
    return visible


def _run_origin(run: Run) -> str | None:
    ingress = run.input_ref.get("_ingress") if isinstance(run.input_ref, dict) else None
    adapter = ingress.get("adapter") if isinstance(ingress, dict) else None
    origin = adapter.get("origin") if isinstance(adapter, dict) else None
    return origin if isinstance(origin, str) and origin else None


def _pending_decisions_payload(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    origin: str | None = None,
    bound_system_ids: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """L17 — count and oldest pause, same filter as validations for this reader."""
    visible = _project_decidable_hitl(
        db,
        workspace=workspace,
        user=user,
        origin=origin,
        bound_system_ids=bound_system_ids,
        limit=100,
        emit_shadow=False,
    )
    oldest_at: str | None = None
    for item in visible:
        started = item.get("started_at")
        if isinstance(started, str) and started and (oldest_at is None or started < oldest_at):
            oldest_at = started
    return {"count": len(visible), "oldest_at": oldest_at}


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
    experiences: list[dict[str, Any]] = []
    for experience, deployment, release in rows:
        item = experience_service.serialize_work_catalog_item(
            experience, deployment, release
        )
        try:
            identity = experience_service.release_identity(release)
            slug = identity["slug"]
        except experience_service.ExperienceError:
            slug = experience.slug
        bound = set(experience_service.binding_system_ids_from_release(release))
        item["pending_decisions"] = _pending_decisions_payload(
            db,
            workspace=workspace,
            user=user,
            origin=f"experience:{slug}",
            bound_system_ids=bound,
        )
        experiences.append(item)
    jobs = automation_portfolio.list_job_explanations(db, workspace, user)
    for card in jobs:
        system_id = card.get("job", {}).get("system_id")
        bound = {str(system_id)} if system_id else set()
        card["pending_decisions"] = _pending_decisions_payload(
            db,
            workspace=workspace,
            user=user,
            origin=None,
            bound_system_ids=bound,
        )
    return {
        "experiences": experiences,
        "automation_jobs": jobs,
    }


HOME_WINDOW_DAYS = 7
HOME_ITEMS_LIMIT = 10
HOME_AGENT_WORK_LIMIT = 5
HOME_REVIEWS_SCAN = 200


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _can_review(db: DBSession, *, workspace: Workspace, user: User) -> bool:
    """Same boundary as the review queue: reviewer or admin, never a plain member."""
    from app.api.v1.endpoints.evaluation import _require_review_queue_access

    try:
        _require_review_queue_access(db, workspace=workspace, user=user)
    except HTTPException:
        return False
    return True


def _home_reviews(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    source_for_run: Any,
) -> Optional[dict[str, Any]]:
    """Proposed review items this reader may open; ``None`` when they cannot review."""
    if not _can_review(db, workspace=workspace, user=user):
        return None
    decisions = (
        db.query(Decision)
        .filter(
            Decision.workspace_id == workspace.id,
            Decision.kind == "review_required",
            Decision.status == "proposed",
        )
        .order_by(Decision.created_at.asc())
        .limit(HOME_REVIEWS_SCAN)
        .all()
    )
    run_ids = [item.target_id for item in decisions if item.target_id]
    runs = (
        db.query(Run).filter(Run.id.in_(run_ids), Run.workspace_id == workspace.id).all()
        if run_ids
        else []
    )
    readable = {run.id: run for run in readable_runs(db, runs=runs, user=user, workspace=workspace)}
    items: list[dict[str, Any]] = []
    for decision in decisions:
        run = readable.get(decision.target_id) if decision.target_id else None
        if run is None:
            continue
        items.append(
            {
                "decision_id": decision.id,
                "run_id": run.id,
                "title": decision.title,
                "created_at": _iso(decision.created_at),
                "source": source_for_run(run),
            }
        )
    return {
        "count": len(items),
        "oldest_at": items[0]["created_at"] if items else None,
        "items": items[:HOME_ITEMS_LIMIT],
    }


@router.get("/_home")
async def work_home(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """L33 — the business home: what waits for this reader, what agents did this week.

    Composes the catalogue this reader may open, one decidable-pause projection
    across all of it (same rights filter as each app's validations), the review
    queue when the reader may review, and the week's completed agent work.
    ``_home`` cannot collide with an app slug (slugs start with a letter).
    """
    _require_enabled(workspace)
    _enforce_consume(db, user=user, workspace=workspace)
    role, groups = _viewer_claims(db, user=user, workspace=workspace)
    rows = experience_service.list_work(
        db, workspace_id=workspace.id, role=role, groups=groups
    )
    by_origin: dict[str, dict[str, Any]] = {}
    by_system: dict[str, dict[str, Any]] = {}
    for experience, _deployment, release in rows:
        try:
            identity = experience_service.release_identity(release)
            slug, name = identity["slug"], identity.get("name") or experience.name
        except experience_service.ExperienceError:
            slug, name = experience.slug, experience.name
        source = {"kind": "app", "slug": slug, "name": name}
        by_origin[f"experience:{slug}"] = source
        for system_id in experience_service.binding_system_ids_from_release(release):
            by_system.setdefault(system_id, source)
    jobs = automation_portfolio.list_job_explanations(db, workspace, user)
    automations: dict[str, dict[str, Any]] = {}
    for card in jobs:
        system_id = str(card.get("job", {}).get("system_id") or "")
        if not system_id:
            continue
        name = (card.get("job", {}).get("name") or "").strip() or system_id
        automations[system_id] = {"kind": "automation", "system_id": system_id, "name": name}

    def source_for(origin: Optional[str], system_id: Optional[str]) -> Optional[dict[str, Any]]:
        if origin and origin in by_origin:
            return by_origin[origin]
        if system_id and system_id in by_system:
            return by_system[system_id]
        if system_id and system_id in automations:
            return automations[system_id]
        return None

    def source_for_run(run: Run) -> Optional[dict[str, Any]]:
        return source_for(_run_origin(run), str(run.system_id) if run.system_id else None)

    # 1. Decisions — one projection across every app and automation.
    pauses = _project_decidable_hitl(
        db,
        workspace=workspace,
        user=user,
        origins=frozenset(by_origin),
        bound_system_ids=frozenset(by_system) | frozenset(automations),
        limit=100,
        emit_shadow=False,
        include_origin=True,
    )
    decisions = []
    for pause in pauses:
        hitl = pause.get("hitl") or {}
        decisions.append(
            {
                "run_id": pause["id"],
                "decision_id": hitl.get("decision_id"),
                "title": hitl.get("decision_title") or hitl.get("prompt") or None,
                "started_at": pause.get("started_at"),
                "source": source_for(pause.get("origin"), pause.get("system_id")),
            }
        )
    decisions.sort(key=lambda item: (item["started_at"] is None, item["started_at"] or ""))

    # 2. Reviews — only for a reader the review queue admits.
    reviews = _home_reviews(db, workspace=workspace, user=user, source_for_run=source_for_run)

    # 3. The week's completed agent work, in Work apps and automations only.
    since = datetime.utcnow() - timedelta(days=HOME_WINDOW_DAYS)
    scope: list[Any] = []
    if by_origin:
        scope.append(
            Run.input_ref["_ingress"]["adapter"]["origin"].as_string().in_(sorted(by_origin))
        )
    if automations:
        scope.append(Run.system_id.in_(sorted(automations)))
    recent: list[Run] = []
    if scope:
        recent = readable_run_page(
            db,
            query=db.query(Run)
            .filter(
                Run.workspace_id == workspace.id,
                Run.status == "completed",
                Run.completed_at.isnot(None),
                Run.completed_at >= since,
                or_(Run.execution_surface.is_(None), Run.execution_surface != "golden_preview"),
                or_(*scope),
            )
            .order_by(Run.completed_at.desc()),
            limit=HOME_AGENT_WORK_LIMIT,
            user=user,
            workspace=workspace,
        )
    calls: dict[str, list[SkillInvocation]] = {}
    if recent:
        for invocation in (
            db.query(SkillInvocation)
            .filter(SkillInvocation.run_id.in_([run.id for run in recent]))
            .all()
        ):
            calls.setdefault(invocation.run_id, []).append(invocation)
    agent_work = [
        {
            "run_id": run.id,
            "completed_at": _iso(run.completed_at),
            "source": source_for_run(run),
            "receipt": run_receipt(run, calls.get(run.id, [])),
        }
        for run in recent
    ]

    # 4. New results — an automation's work finished since it was last opened.
    results = []
    for item, run in zip(agent_work, recent):
        source = item["source"]
        if not source or source.get("kind") != "automation":
            continue
        opened = experience_service.read_work_last_opened(
            workspace,
            experience_service.work_last_opened_key(kind="automation", app_id=source["system_id"]),
        )
        opened_at = _checkpoint_stamp(opened)
        if opened_at is not None and run.completed_at and run.completed_at <= opened_at:
            continue
        results.append(item)

    return {
        "window_days": HOME_WINDOW_DAYS,
        "decisions": {
            "count": len(decisions),
            "oldest_at": decisions[0]["started_at"] if decisions else None,
            "items": decisions[:HOME_ITEMS_LIMIT],
        },
        "reviews": reviews,
        "results": {"items": results[:HOME_ITEMS_LIMIT]},
        "agent_work": {"items": agent_work},
    }


def _checkpoint_stamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    raw = value[:-1] if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except ValueError:
        return None


@router.get("/automation-jobs/{system_id}")
async def get_automation_job(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_consume(db, user=user, workspace=workspace)
    for card in automation_portfolio.list_job_explanations(db, workspace, user):
        if card["job"].get("system_id") == system_id:
            experience_service.touch_work_last_opened(
                db,
                workspace,
                kind="automation",
                app_id=system_id,
            )
            return card
    raise HTTPException(404, "Automation not found")


@router.get("/systems/{system_id}/apps")
async def list_work_apps_for_system(
    system_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """L14 — apps linked to a System that this reader may open."""
    _require_enabled(workspace)
    _enforce_consume(db, user=user, workspace=workspace)
    owned = (
        db.query(System.id)
        .filter(System.id == system_id, System.workspace_id == workspace.id)
        .one_or_none()
    )
    if owned is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "SYSTEM_NOT_FOUND", "message": "System not found."},
        )
    role, groups = _viewer_claims(db, user=user, workspace=workspace)
    rows = experience_service.list_work(
        db, workspace_id=workspace.id, role=role, groups=groups
    )
    jobs = automation_portfolio.list_job_explanations(db, workspace, user)
    apps = experience_service.list_system_work_apps(
        rows,
        system_id=system_id,
        automation_jobs=jobs,
        workspace=workspace,
    )
    return {"apps": apps}


@router.get("/automation-jobs/{system_id}/package")
async def export_automation_package(
    system_id: str,
    run_id: str = Query(min_length=1, max_length=36),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_enabled(workspace)
    _enforce_consume(db, user=user, workspace=workspace)
    card = next(
        (item for item in automation_portfolio.list_job_explanations(db, workspace, user) if item["job"].get("system_id") == system_id),
        None,
    )
    if card is None:
        raise HTTPException(404, "Automation not found")
    run = (
        db.query(Run)
        .filter(Run.id == run_id, Run.system_id == system_id, Run.workspace_id == workspace.id)
        .one_or_none()
    )
    if run is None:
        raise HTTPException(404, "Run not found")
    try:
        return automation_portfolio.run_package(
            card["job"],
            {
                "id": run.id,
                "system_id": run.system_id,
                "status": run.status,
                "flow_sha256": run.flow_sha256,
                "execution_surface": run.execution_surface,
            },
            convention=card["convention"] if card["convention"].get("status") != "absent" else None,
            proof={**automation_portfolio.invocation_proof(db, run), "gap": card["gap"]},
        )
    except automation_portfolio.AutomationPortfolioRefusal as refusal:
        raise HTTPException(
            status_code=422,
            detail={"code": refusal.code, "message": refusal.message},
        ) from refusal


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
    experience_service.touch_work_last_opened(
        db,
        workspace,
        kind="experience",
        app_id=experience.id,
    )
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
    return {
        "runs": _project_decidable_hitl(
            db,
            workspace=workspace,
            user=user,
            origin=origin,
            bound_system_ids=bound_system_ids,
            limit=100,
            emit_shadow=True,
        )
    }


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
