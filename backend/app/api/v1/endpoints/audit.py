"""Audit log endpoints for governance demo.

Tenant-scoped (Vague D / D1). Every audit event is tied to the caller's
active workspace and reads are filtered accordingly so one tenant can
never see another's audit trail. `actor` is always controlled server-side:
generic audit events use the authenticated identity while privacy-preserving
navigation telemetry uses a non-identifying constant.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, get_current_workspace
from app.core.logging import get_logger
from app.db.base import get_db
from app.models.audit import AuditLog
from app.models.run import Run, SkillInvocation
from app.models.decision import Decision
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_access import enforce_audit_read
from app.services.surface_catalog import SURFACE_METADATA

logger = get_logger(__name__)
router = APIRouter()
NAVIGATION_RESOLVED_EVENT = "navigation.resolved"
NAVIGATION_TRANSITION_EVENT = "navigation.transition"
_SERVER_AUDIT_PREFIXES = (
    "action.",
    "admin.",
    "calendar.",
    "canonical_answer.",
    "chain.",
    "decision.",
    "deposit.",
    "evaluation.",
    "experience.",
    "iam.",
    "kc.",
    "knowledge.",
    "lot7.",
    "lot8.",
    "lot9.",
    "map.",
    "maritime.",
    "meeting.",
    "mission_room.",
    "notice.",
    "recommendation.",
    "report.",
    "run.",
    "runtime.",
    "sharepoint.",
    "spl.",
    "system.",
    "system360.",
    "value_loop.",
    "video_demo.",
    "visual.",
    "webcam.",
    "workspace.",
    "workspace_app.",
)

_MACHINE_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_EMAIL_IN_PATH = re.compile(r"[^/\s@]+@[^/\s@]+\.[^/\s@]+", re.IGNORECASE)

# Every `id` declared in the frontend's navigation catalogue must appear here,
# or that surface's page views are answered 422 and never reach the trail. The
# two lists are held together by
# `app/tests/api/test_navigation_surface_contract.py`, which is what four
# surfaces had been missing.
_NAVIGATION_SURFACES = frozenset(
    {
        "account",
        "apps",
        "capabilities",
        "chat",
        "client360-pdr",
        "connectors",
        "conversations",
        "mcp",
        "work",
        "contexts",
        "create",
        "create-apps",
        "data",
        "external-deposit",
        "fse-reports",
        "governance",
        "hypervisor",
        "intelligence",
        "knowledge",
        "knowledge-capture",
        "legacy-settings",
        "mission-room",
        "model-portal",
        "models",
        "nawa-itsd",
        "observability",
        "orchestration",
        "presets",
        "resources",
        "review-queue",
        "runs",
        "sap-hana",
        "secure-deposit",
        "sharepoint",
        "skill-invocations",
        "skills",
        "steering",
        "surface-map",
        "system-capture",
        "systems",
        "tasks",
        "unknown",
        "workspace-admin",
        "workspace-app-platform",
        "workspace-blueprints",
        "workspace-chat",
    }
)
_REDIRECT_OWNERS = frozenset(
    {
        "angular_router",
        "navigation_resolver",
    }
)
_LEGACY_REDIRECT_OWNER_ALIASES = {
    "navigation_profile": "navigation_resolver",
    "workspace_entrypoint": "navigation_resolver",
    "workspace_shell": "navigation_resolver",
}
_REDIRECT_REASONS = frozenset(
    {
        "angular_route_redirect",
        "business_knowledge_compatibility",
        "business_profile_disallowed",
        "business_system_capture_compatibility",
        "direct",
        "legacy_hypervisor_object_lens",
        "legacy_focus_query",
        "legacy_tab_query",
        "legacy_system_id_query",
        "legacy_mission_room_path",
        "legacy_theme_query",
        "workspace_mode_home",
        "workspace_default_route",
        "workspace_extension_unavailable",
        "workspace_settings_entrypoint",
    }
)

_REDIRECT_OWNER_BY_REASON = {
    "direct": "angular_router",
    "angular_route_redirect": "angular_router",
    "business_knowledge_compatibility": "navigation_resolver",
    "business_profile_disallowed": "navigation_resolver",
    "business_system_capture_compatibility": "navigation_resolver",
    "legacy_hypervisor_object_lens": "navigation_resolver",
    "legacy_focus_query": "navigation_resolver",
    "legacy_tab_query": "navigation_resolver",
    "legacy_system_id_query": "navigation_resolver",
    "legacy_mission_room_path": "navigation_resolver",
    "legacy_theme_query": "navigation_resolver",
    "workspace_mode_home": "navigation_resolver",
    "workspace_default_route": "navigation_resolver",
    "workspace_extension_unavailable": "navigation_resolver",
    "workspace_settings_entrypoint": "navigation_resolver",
}

# Runtime values are canonicalized against the existing backend surface
# catalog. These additions are privacy masks for parameterized Angular routes
# not yet represented by that catalog; they do not resolve or own navigation.
_PRIVACY_ROUTE_TEMPLATES = {
    "/apps",
    "/orchestration",
    "/workspace/:slug/chat",
    "/systems/:id/flow",
    "/hypervisor/mission-room/agenda/meeting/:id",
}
_CATALOG_UI_ROUTES = {
    route
    for surface in SURFACE_METADATA
    for route in surface.ui_routes
    if route.startswith("/")
}
_NAVIGATION_ROUTE_TEMPLATES = tuple(
    sorted(
        _CATALOG_UI_ROUTES | _PRIVACY_ROUTE_TEMPLATES,
        key=lambda route: (
            len(route.strip("/").split("/")),
            sum(not segment.startswith(":") for segment in route.split("/")),
        ),
        reverse=True,
    )
)

# Ordered most-specific-first. Values are the stable ids exported by the
# frontend surface catalog; the backend derives them from the canonical route
# so a client cannot relabel a Systems navigation as Chat telemetry.
_SURFACE_ROUTE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/hypervisor/mission-room", "mission-room"),
    ("/systems/:id/capture", "system-capture"),
    ("/knowledge/interventions", "fse-reports"),
    ("/knowledge/capture", "knowledge-capture"),
    ("/workspace/:slug/chat", "workspace-chat"),
    ("/steering/review-queue", "review-queue"),
    ("/steering/contexts", "contexts"),
    ("/governance/surface-map", "surface-map"),
    ("/governance/blueprints", "workspace-blueprints"),
    ("/connectors/sharepoint", "sharepoint"),
    ("/connectors/mcp", "mcp"),
    ("/conversations", "conversations"),
    ("/work", "work"),
    ("/connectors/sftp", "secure-deposit"),
    ("/settings/legacy", "legacy-settings"),
    ("/client360", "client360-pdr"),
    ("/create/apps", "create-apps"),
    ("/create", "create"),
    ("/capabilities", "capabilities"),
    ("/observability", "observability"),
    ("/orchestration", "orchestration"),
    ("/intelligence", "intelligence"),
    ("/governance", "governance"),
    ("/hypervisor", "hypervisor"),
    ("/knowledge", "knowledge"),
    ("/connectors", "connectors"),
    ("/workspace", "workspace-admin"),
    ("/resources", "resources"),
    ("/steering", "steering"),
    ("/systems", "systems"),
    ("/skills", "skills"),
    ("/presets", "presets"),
    ("/account", "account"),
    ("/deposit", "external-deposit"),
    ("/tasks", "tasks"),
    ("/runs", "runs"),
    ("/apps", "apps"),
    ("/chat", "chat"),
)


def _route_segments(route: str) -> list[str]:
    return [unquote(segment) for segment in route.strip("/").split("/") if segment]


def _canonical_navigation_route(route: str) -> str:
    """Return a code-authored route template, never runtime path values."""
    path_segments = _route_segments(route)
    if not path_segments:
        return "/"

    best: tuple[list[str], tuple[int, int]] | None = None
    for template in _NAVIGATION_ROUTE_TEMPLATES:
        template_segments = _route_segments(template)
        if len(path_segments) < len(template_segments):
            continue
        if not all(
            expected.startswith(":") or expected == path_segments[index]
            for index, expected in enumerate(template_segments)
        ):
            continue
        score = (
            len(template_segments),
            sum(not segment.startswith(":") for segment in template_segments),
        )
        if best is None or score > best[1]:
            best = (template_segments, score)

    if best is not None:
        safe_segments = list(best[0])
        safe_segments.extend(":segment" for _ in path_segments[len(safe_segments) :])
        return "/" + "/".join(safe_segments)

    # A top-level/static prefix of a catalogued route is safe even if it is
    # not itself a leaf (e.g. /governance before its default child redirect).
    for template in _NAVIGATION_ROUTE_TEMPLATES:
        template_segments = _route_segments(template)
        if len(path_segments) >= len(template_segments):
            continue
        if all(
            not template_segments[index].startswith(":")
            and template_segments[index] == segment
            for index, segment in enumerate(path_segments)
        ):
            return "/" + "/".join(path_segments)

    known_roots = {
        segments[0]
        for template in _NAVIGATION_ROUTE_TEMPLATES
        if (segments := _route_segments(template))
        and not segments[0].startswith(":")
    }
    safe_segments = (
        [path_segments[0], *(":segment" for _ in path_segments[1:])]
        if path_segments[0] in known_roots
        else [":segment" for _ in path_segments]
    )
    return "/" + "/".join(safe_segments)


def _navigation_surface_for_route(route: str) -> str:
    for prefix, surface in _SURFACE_ROUTE_PREFIXES:
        if route == prefix or route.startswith(prefix + "/"):
            return surface
    return "unknown"


class NavigationResolvedDetails(BaseModel):
    """Strict, PII-free payload persisted for ``navigation.resolved``.

    The active workspace is replaced server-side before validation. Query
    strings and fragments are discarded because they may contain search text,
    user identifiers or other free-form values. ``extra='forbid'`` prevents a
    caller from smuggling arbitrary fields into this telemetry event.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    requested_route: str
    resolved_route: str
    effective_workspace: str
    effective_surface: str
    redirect_owner: str
    redirect_reason: str
    redirected: bool

    @field_validator("requested_route", "resolved_route")
    @classmethod
    def _privacy_safe_route(cls, value: str) -> str:
        route = str(value or "/").split("?", 1)[0].split("#", 1)[0] or "/"
        if not route.startswith("/"):
            raise ValueError("navigation routes must be absolute paths")
        if len(route) > 512:
            raise ValueError("navigation routes must be at most 512 characters")
        if _EMAIL_IN_PATH.search(unquote(route)):
            raise ValueError("navigation routes must not contain e-mail addresses")
        return _canonical_navigation_route(route)

    @field_validator(
        "effective_workspace",
        "effective_surface",
        "redirect_owner",
        "redirect_reason",
    )
    @classmethod
    def _machine_token(cls, value: str) -> str:
        token = str(value or "").strip().lower()
        if not _MACHINE_TOKEN.fullmatch(token):
            raise ValueError("navigation dimensions must be lowercase machine tokens")
        return token

    @field_validator("effective_surface")
    @classmethod
    def _known_surface(cls, value: str) -> str:
        if value not in _NAVIGATION_SURFACES:
            raise ValueError("unknown navigation surface")
        return value

    @field_validator("redirect_owner")
    @classmethod
    def _known_redirect_owner(cls, value: str) -> str:
        value = _LEGACY_REDIRECT_OWNER_ALIASES.get(value, value)
        if value not in _REDIRECT_OWNERS:
            raise ValueError("unknown navigation redirect owner")
        return value

    @field_validator("redirect_reason")
    @classmethod
    def _known_redirect_reason(cls, value: str) -> str:
        if value not in _REDIRECT_REASONS:
            raise ValueError("unknown navigation redirect reason")
        return value

    @model_validator(mode="after")
    def _redirect_contract(self) -> NavigationResolvedDetails:
        self.effective_surface = _navigation_surface_for_route(self.resolved_route)
        if self.redirected and self.redirect_reason == "direct":
            raise ValueError("redirected navigation requires a redirect reason")
        if not self.redirected and self.redirect_reason != "direct":
            raise ValueError("direct navigation must use redirect_reason=direct")
        expected_owner = _REDIRECT_OWNER_BY_REASON[self.redirect_reason]
        if self.redirect_owner != expected_owner:
            raise ValueError("redirect owner does not own the selected reason")
        if not self.redirected and self.requested_route != self.resolved_route:
            raise ValueError("direct navigation must preserve the requested route")
        return self


_TRANSITION_TRIGGERS = frozenset(
    {
        "rail",
        "minirail",
        "breadcrumb",
        "inpage",
        "palette",
        "history",
        "redirect",
    }
)


class NavigationTransitionDetails(BaseModel):
    """Additive Lot 6 v2 payload. Surfaces only — never object ids.

    ``extra='forbid'`` keeps the same privacy boundary as ``navigation.resolved``.
    Depth is a signed delta of the five-level hierarchy, not a path.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    from_surface: str
    to_surface: str
    trigger: str
    zone_changed: bool
    depth_delta: int
    facet_changed: bool

    @field_validator("from_surface", "to_surface")
    @classmethod
    def _known_transition_surface(cls, value: str) -> str:
        token = str(value or "").strip().lower()
        if token not in _NAVIGATION_SURFACES:
            raise ValueError("unknown navigation surface")
        return token

    @field_validator("trigger")
    @classmethod
    def _known_trigger(cls, value: str) -> str:
        token = str(value or "").strip().lower()
        if token not in _TRANSITION_TRIGGERS:
            raise ValueError("unknown navigation transition trigger")
        return token

    @field_validator("depth_delta")
    @classmethod
    def _bounded_depth_delta(cls, value: int) -> int:
        delta = int(value)
        if delta < -8 or delta > 8:
            raise ValueError("depth_delta must be between -8 and 8")
        return delta


class AuditEvent(BaseModel):
    event_type: str
    # `actor` is advisory only — we override it server-side with the
    # server-selected actor so clients cannot spoof identity in the audit
    # trail (navigation telemetry is deliberately pseudonymous).
    actor: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    agent_id: str | None = None
    severity: str = "info"


@router.post("")
async def create_audit_event(
    event: AuditEvent,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: Session = Depends(get_db),
):
    if any(event.event_type.startswith(prefix) for prefix in _SERVER_AUDIT_PREFIXES):
        raise HTTPException(
            status_code=403,
            detail="Audit event namespace is reserved for server-side emitters",
        )
    details = event.details
    actor = user.username or user.email or "unknown"
    trace_id = event.trace_id
    agent_id = event.agent_id
    severity = event.severity

    if event.event_type == NAVIGATION_RESOLVED_EVENT:
        # Workspace scope and privacy are authoritative server-side. Navigation
        # telemetry supports aggregate resolver analysis, not user tracking.
        raw_details = dict(event.details)
        raw_details["effective_workspace"] = workspace.slug
        try:
            details = NavigationResolvedDetails.model_validate(raw_details).model_dump()
        except ValidationError as exc:
            # Do not echo rejected values: the whole point of this boundary is
            # to keep accidental PII out of both storage and HTTP responses.
            raise HTTPException(
                status_code=422,
                detail="Invalid navigation.resolved details",
            ) from exc
        actor = "authenticated_user"
        trace_id = None
        agent_id = None
        severity = "info"

    if event.event_type == NAVIGATION_TRANSITION_EVENT:
        try:
            details = NavigationTransitionDetails.model_validate(event.details).model_dump()
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail="Invalid navigation.transition details",
            ) from exc
        actor = "authenticated_user"
        trace_id = None
        agent_id = None
        severity = "info"

    log_entry = AuditLog(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        timestamp=datetime.utcnow(),
        event_type=event.event_type,
        # Actor is selected above from server-side authentication/event policy.
        actor=actor,
        details=details,
        trace_id=trace_id,
        agent_id=agent_id,
        severity=severity,
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    logger.info(
        "Audit event created",
        event_type=event.event_type,
        workspace_id=workspace.id,
        actor=log_entry.actor,
    )
    return {
        "id": log_entry.id,
        "timestamp": log_entry.timestamp.isoformat(),
        "event_type": log_entry.event_type,
        "actor": log_entry.actor,
        "details": log_entry.details,
        "severity": log_entry.severity,
    }


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _cursor(value: str) -> tuple[datetime, str]:
    try:
        timestamp, row_id = value.rsplit(",", 1)
        if not row_id or len(row_id) > 36:
            raise ValueError()
        return _utc(datetime.fromisoformat(timestamp)), row_id
    except ValueError as exc:
        raise HTTPException(422, "Invalid audit cursor") from exc


def _audit_run_ids(db: Session, logs: list[AuditLog], workspace: Workspace, user: User) -> dict[str, str]:
    """Resolve persisted execution references, never guess from a trace string."""
    from app.services.run_access import readable_runs

    candidates = {}
    decision_ids = set()
    for log in logs:
        details = log.details if isinstance(log.details, dict) else {}
        candidates[log.id] = [value for value in (
            log.trace_id, details.get("run_id"), details.get("canonical_run_id"),
            details.get("new_run_id"), details.get("invocation_id"),
            details.get("skill_invocation_id"),
        ) if isinstance(value, str) and value]
        if isinstance(details.get("decision_id"), str):
            decision_ids.add(details["decision_id"])
    decisions = {row.id: row.target_id for row in db.query(Decision).filter(
        Decision.workspace_id == workspace.id, Decision.scope == "run",
        Decision.id.in_(decision_ids),
    ).all()} if decision_ids else {}
    for log in logs:
        details = log.details if isinstance(log.details, dict) else {}
        decision_id = details.get("decision_id")
        target = decisions.get(decision_id) if isinstance(decision_id, str) else None
        if target:
            candidates[log.id].append(target)
    refs = {ref for values in candidates.values() for ref in values}
    if not refs:
        return {}
    invocations = dict(db.query(SkillInvocation.id, SkillInvocation.run_id).join(
        Run, Run.id == SkillInvocation.run_id,
    ).filter(Run.workspace_id == workspace.id, SkillInvocation.id.in_(refs)).all())
    runs = db.query(Run).filter(
        Run.workspace_id == workspace.id, Run.id.in_(refs | set(invocations.values())),
    ).all()
    visible = {run.id for run in readable_runs(db, runs=runs, user=user, workspace=workspace)}
    resolved = {}
    for log_id, values in candidates.items():
        for ref in values:
            run_id = ref if ref in visible else invocations.get(ref)
            if run_id in visible:
                resolved[log_id] = run_id
                break
    return resolved


@router.get("")
async def list_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    event_type: str | None = None,
    event_type_prefix: str | None = None,
    exclude_navigation: bool = False,
    before: str | None = Query(None, max_length=100),
    actor: str | None = Query(None, max_length=255),
    since: datetime | None = None,
    until: datetime | None = None,
    trace_id: str | None = Query(None, max_length=36),
    severity: str | None = Query(None, max_length=20),
    search: str | None = Query(None, max_length=255),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_audit_read(db, user=user, workspace=workspace)
    if since and until and _utc(since) > _utc(until):
        raise HTTPException(422, "Audit period start must precede end")
    query = db.query(AuditLog).filter(AuditLog.workspace_id == workspace.id)
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)
    elif event_type_prefix:
        query = query.filter(AuditLog.event_type.startswith(event_type_prefix, autoescape=True))
    if exclude_navigation:
        query = query.filter(~AuditLog.event_type.startswith("navigation.", autoescape=True))
    if actor:
        query = query.filter(AuditLog.actor == actor)
    if since:
        query = query.filter(AuditLog.timestamp >= _utc(since))
    if until:
        query = query.filter(AuditLog.timestamp <= _utc(until))
    if trace_id:
        invocation_ids = [row[0] for row in db.query(SkillInvocation.id).join(
            Run, Run.id == SkillInvocation.run_id,
        ).filter(Run.workspace_id == workspace.id, Run.id == trace_id).all()]
        decision_ids = [row[0] for row in db.query(Decision.id).filter(
            Decision.workspace_id == workspace.id, Decision.scope == "run",
            Decision.target_id == trace_id,
        ).all()]
        query = query.filter(or_(AuditLog.trace_id.in_([trace_id, *invocation_ids]), *(
            AuditLog.details[key].as_string() == trace_id
            for key in ("run_id", "canonical_run_id", "new_run_id")
        ), *(
            AuditLog.details[key].as_string().in_(invocation_ids)
            for key in ("invocation_id", "skill_invocation_id")
        ), AuditLog.details["decision_id"].as_string().in_(decision_ids)))
    if severity:
        query = query.filter(AuditLog.severity == severity)
    if search:
        from sqlalchemy import String, cast
        query = query.filter(or_(*(
            column.icontains(search, autoescape=True)
            for column in (AuditLog.event_type, AuditLog.actor, AuditLog.agent_id,
                           AuditLog.trace_id, cast(AuditLog.details, String))
        )))
    total = query.count()
    if before:
        timestamp, row_id = _cursor(before)
        query = query.filter(or_(AuditLog.timestamp < timestamp, and_(
            AuditLog.timestamp == timestamp, AuditLog.id < row_id,
        )))
    rows = query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(limit + 1).all()
    logs = rows[:limit]
    run_ids = _audit_run_ids(db, logs, workspace, user)
    has_more = len(rows) > limit
    return {
        "logs": [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "event_type": log.event_type,
                "actor": log.actor,
                "details": log.details,
                "trace_id": log.trace_id,
                "run_id": run_ids.get(log.id),
                "agent_id": log.agent_id,
                "severity": log.severity,
            }
            for log in logs
        ],
        "total": total,
        "has_more": has_more,
        "next_cursor": f"{logs[-1].timestamp.isoformat()},{logs[-1].id}" if has_more else None,
    }


@router.get("/summary")
async def audit_summary(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_audit_read(db, user=user, workspace=workspace)
    total = (
        db.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .count()
    )
    event_types = (
        db.query(AuditLog.event_type)
        .filter(AuditLog.workspace_id == workspace.id)
        .distinct()
        .all()
    )
    return {
        "total_events": total,
        "event_types": [e[0] for e in event_types],
        "governance_status": "active",
        "access_control": {
            "roles": ["Admin", "Auditor", "User"],
            "sso_provider": "Keycloak (OIDC)",
            "mfa_enabled": True,
        },
    }
