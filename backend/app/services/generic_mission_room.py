"""Provider-neutral Mission Room projections from canonical workspace objects.

This module deliberately imports no demo fixture service.  Every object is
queried with an explicit ``workspace_id`` predicate and missing domain data is
represented as an explicit state instead of a synthetic replacement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession

from app.models.audit import AuditLog
from app.models.calendar import WorkspaceCalendarEvent
from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_access import legacy_audit_read_allowed
from app.services.audit_logger import emit_audit_event
from app.services.decision_access import readable_decisions
from app.services.iam.decision_plane import emit_shadow_diff_summary, resolve_action
from app.services.run_access import readable_runs
from app.services.workspace_app_manifests import GENERIC_MISSION_ROOM_PROVIDER_KIND

_ROOT_ROUTE = "/hypervisor/mission-room"
_LIMIT = 100


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _workspace(workspace: Workspace) -> dict[str, str]:
    return {
        "id": workspace.id,
        "slug": workspace.slug,
        "name": workspace.name,
    }


def _empty_state(
    rows: Sequence[Any],
    *,
    code: str,
    message: str,
) -> tuple[str, dict[str, str] | None]:
    if rows:
        return "available", None
    return "not_configured", {"code": code, "message": message}


def _source(identifier: str, label: str, kind: str) -> dict[str, Any]:
    return {
        "id": identifier,
        "label": label,
        "kind": kind,
        "confidence": None,
        "confidence_state": "not_measured",
        "age": "authoritative",
    }


def _filter_systems(
    db: DBSession,
    workspace: Workspace,
    user: User,
    systems: Sequence[System],
) -> list[System]:
    visible: list[System] = []
    resolutions = []
    for item in systems:
        if item.workspace_id != workspace.id:
            continue
        resolution = resolve_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind="system",
            action="read",
            legacy_allowed=True,
            resource_attrs={
                "system_id": item.id,
                "capability_id": item.capability_id,
            },
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        resolutions.append((item.id, resolution))
        if resolution.effective_allowed:
            visible.append(item)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind="system",
        action="read",
        resolutions=resolutions,
    )
    return visible


def _systems(db: DBSession, workspace: Workspace, user: User) -> list[System]:
    rows = (
        db.query(System)
        .filter(System.workspace_id == workspace.id)
        .order_by(System.updated_at.desc(), System.id.asc())
        .all()
    )
    return _filter_systems(db, workspace, user, rows)[:_LIMIT]


def _runs(db: DBSession, workspace: Workspace, user: User) -> list[Run]:
    rows = (
        db.query(Run)
        .filter(Run.workspace_id == workspace.id)
        .order_by(Run.started_at.desc(), Run.id.asc())
        .limit(_LIMIT)
        .all()
    )
    return readable_runs(db, runs=rows, user=user, workspace=workspace)


def _filter_decisions(
    db: DBSession,
    workspace: Workspace,
    user: User,
    decisions: Sequence[Decision],
) -> list[Decision]:
    return readable_decisions(
        db,
        decisions=decisions,
        user=user,
        workspace=workspace,
    )


def _decisions(db: DBSession, workspace: Workspace, user: User) -> list[Decision]:
    rows = (
        db.query(Decision)
        .filter(Decision.workspace_id == workspace.id)
        .order_by(Decision.created_at.desc(), Decision.id.asc())
        .limit(_LIMIT)
        .all()
    )
    return _filter_decisions(db, workspace, user, rows)


def _audit_run_ids(item: AuditLog) -> set[str]:
    details = item.details if isinstance(item.details, Mapping) else {}
    run_ids: set[str] = set()
    direct = details.get("run_id")
    if direct:
        run_ids.add(str(direct))
    direct_many = details.get("run_ids")
    if isinstance(direct_many, Sequence) and not isinstance(direct_many, str):
        run_ids.update(str(value) for value in direct_many if value)
    resource = details.get("resource")
    if isinstance(resource, Mapping):
        if resource.get("run_id"):
            run_ids.add(str(resource["run_id"]))
        if resource.get("kind") == "run":
            sample_ids = resource.get("sample_ids")
            if isinstance(sample_ids, Sequence) and not isinstance(sample_ids, str):
                run_ids.update(str(value) for value in sample_ids if value)
    return run_ids


def _audits(db: DBSession, workspace: Workspace, user: User) -> list[AuditLog]:
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.asc())
        .limit(_LIMIT)
        .all()
    )
    referenced_run_ids = {
        run_id for item in rows for run_id in _audit_run_ids(item)
    }
    referenced_runs = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace.id,
            Run.id.in_(referenced_run_ids),
        )
        .all()
        if referenced_run_ids
        else []
    )
    readable_run_ids = {
        item.id
        for item in readable_runs(
            db,
            runs=referenced_runs,
            user=user,
            workspace=workspace,
        )
    }
    legacy_role_allowed = legacy_audit_read_allowed(
        db,
        user=user,
        workspace=workspace,
    )
    visible: list[AuditLog] = []
    resolutions = []
    for item in rows:
        run_ids = _audit_run_ids(item)
        legacy_allowed = legacy_role_allowed and (
            not run_ids or run_ids.issubset(readable_run_ids)
        )
        resolution = resolve_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind="audit_log",
            action="read",
            legacy_allowed=legacy_allowed,
            resource_attrs={
                "run_id": min(run_ids) if len(run_ids) == 1 else None,
            },
            audit_shadow_diff=False,
            audit_shadow_evidence=False,
        )
        resolutions.append((item.id, resolution))
        if resolution.effective_allowed:
            visible.append(item)
    emit_shadow_diff_summary(
        workspace=workspace,
        user=user,
        resource_kind="audit_log",
        action="read",
        resolutions=resolutions,
    )
    return visible


def _events(db: DBSession, workspace: Workspace) -> list[WorkspaceCalendarEvent]:
    return (
        db.query(WorkspaceCalendarEvent)
        .filter(WorkspaceCalendarEvent.workspace_id == workspace.id)
        .order_by(WorkspaceCalendarEvent.start_at.asc(), WorkspaceCalendarEvent.id.asc())
        .limit(_LIMIT)
        .all()
    )


def _base(
    workspace: Workspace,
    rows: Sequence[Any],
    *,
    empty_code: str,
    empty_message: str,
) -> dict[str, Any]:
    state, empty = _empty_state(
        rows,
        code=empty_code,
        message=empty_message,
    )
    return {
        "schema_version": "mission_room.workspace_objects.v1",
        "provider_kind": GENERIC_MISSION_ROOM_PROVIDER_KIND,
        "workspace": _workspace(workspace),
        "state": state,
        "empty_state": empty,
    }


def overview_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
) -> dict[str, Any]:
    systems = _systems(db, workspace, user)
    runs = _runs(db, workspace, user)
    decisions = _decisions(db, workspace, user)
    events = _events(db, workspace)
    rows: list[Any] = [*systems, *runs, *decisions, *events]
    payload = _base(
        workspace,
        rows,
        empty_code="workspace_objects_not_configured",
        empty_message="No Systems, Runs, Decisions or calendar events are configured.",
    )
    payload.update(
        {
            "counts": {
                "systems": len(systems),
                "runs": len(runs),
                "decisions": len(decisions),
                "calendar_events": db.query(WorkspaceCalendarEvent)
                .filter(WorkspaceCalendarEvent.workspace_id == workspace.id)
                .count(),
            },
            "latest": {
                "system": _system_record(systems[0]) if systems else None,
                "run": _run_record(runs[0]) if runs else None,
                "decision": _decision_record(decisions[0]) if decisions else None,
                "calendar_event": _event_record(events[0]) if events else None,
            },
            "sources": _sources_for([*systems, *runs, *decisions, *events]),
        }
    )
    return payload


_NAVIGATION = {
    "cockpit": ("Cockpit", "/cockpit", "/cockpit", "Workspace", "Cockpit"),
    "strategie": ("Systems", "/strategie", "/projects", "System", "Systems"),
    "securite": ("Operations", "/securite", "/monitor", "Run", "Operations"),
    "reputation": ("Activity", "/reputation", "/news", "Audit", "Activity"),
    "agenda": ("Calendar", "/agenda", "/timeline", "Calendar", "Calendar"),
    "presse": ("Signals", "/presse", "/news", "Signal", "Signals"),
    "decisions": ("Decisions", "/decisions", "/decisions", "Decision", "Reviews"),
}


def navigation_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    del db, user
    items: list[dict[str, Any]] = []
    for key in projection.get("navigation_keys") or ():
        contract = _NAVIGATION.get(str(key))
        if contract is None:
            continue
        label, route, api, object_label, workbench = contract
        items.append(
            {
                "key": key,
                "label": label,
                "glyph": "ledger",
                "route": f"{_ROOT_ROUTE}{route}",
                "api": f"/api/v1/mission-room{api}",
                "object": object_label,
                "workbench": workbench,
                "system_id": None,
                "system_name": None,
            }
        )
    return {
        "schema_version": "mission_room.workspace_objects.v1",
        "provider_kind": GENERIC_MISSION_ROOM_PROVIDER_KIND,
        "workspace": _workspace(workspace),
        "state": "available",
        "empty_state": None,
        "app": {
            "label": projection["label"],
            "assistant_label": projection["assistant_label"],
            "shell": "immersive",
            "default_route": projection["default_route"],
            "default_view": "cockpit",
            "profile": projection["profile"],
            "brand": {
                "label": projection["label"],
                "style": projection["brand_style"],
            },
        },
        "items": items,
        "exit_routes": [{"label": "Portfolio", "route": "/hypervisor"}],
    }


def cockpit_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
) -> dict[str, Any]:
    systems = _systems(db, workspace, user)
    runs = _runs(db, workspace, user)
    decisions = _decisions(db, workspace, user)
    events = _events(db, workspace)
    rows: list[Any] = [*systems, *runs, *decisions, *events]
    payload = _base(
        workspace,
        rows,
        empty_code="workspace_objects_not_configured",
        empty_message="No workspace objects are available for this cockpit.",
    )
    run_statuses: dict[str, int] = {}
    for run in runs:
        run_statuses[run.status] = run_statuses.get(run.status, 0) + 1
    priorities = [
        {
            "id": system.id,
            "kind": "system",
            "title": system.name,
            "summary": system.objective or f"System status: {system.status}",
            "deadline": _iso(system.updated_at) or "",
            "sources": [system.id],
            "tone": _system_tone(system.status),
        }
        for system in systems[:5]
    ]
    decision_focus = [_decision_item(item) for item in decisions[:5]]
    agenda = [_agenda_item(item) for item in events[:10]]
    system_count = len(systems)
    run_count = len(runs)
    decision_count = len(decisions)
    event_count = (
        db.query(WorkspaceCalendarEvent)
        .filter(WorkspaceCalendarEvent.workspace_id == workspace.id)
        .count()
    )
    payload.update(
        {
            "title": workspace.name,
            "date_label": datetime.now(UTC).date().isoformat(),
            "briefing_status": (
                "Workspace data loaded" if rows else "No workspace objects configured"
            ),
            "priorities": priorities,
            "kpis": {
                "systems": system_count,
                "runs": run_count,
                "decisions": decision_count,
                "calendar_events": event_count,
            },
            "run_statuses": run_statuses,
            "threat_trend": [],
            "communications_flow": [],
            "agenda": agenda,
            "zones": [],
            "reputation": {
                "state": "not_measured",
                "score": None,
                "delta": None,
                "trend": [],
                "items": [],
            },
            "media_sources": [],
            "latest_alerts": [],
            "keywords": [],
            "assistant_prompts": [],
            "messages": [],
            "decision_focus": decision_focus,
            "vp_status_bar": [
                {
                    "key": "systems",
                    "label": "Systems",
                    "value": str(system_count),
                    "detail": "Workspace scoped",
                    "tone": "stable",
                },
                {
                    "key": "runs",
                    "label": "Runs",
                    "value": str(run_count),
                    "detail": "Workspace scoped",
                    "tone": "stable",
                },
                {
                    "key": "decisions",
                    "label": "Decisions",
                    "value": str(decision_count),
                    "detail": "Workspace scoped",
                    "tone": "stable",
                },
            ],
            "arbitration_cards": [],
            "press_preview": [],
            "sources": _sources_for(rows),
        }
    )
    return payload


def briefing_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
) -> dict[str, Any]:
    systems = _systems(db, workspace, user)
    runs = _runs(db, workspace, user)
    decisions = _decisions(db, workspace, user)
    rows: list[Any] = [*systems, *runs, *decisions]
    payload = _base(
        workspace,
        rows,
        empty_code="briefing_sources_not_configured",
        empty_message="No Systems, Runs or Decisions are available for a briefing.",
    )
    sections: list[dict[str, Any]] = []
    if systems:
        sections.append(
            {
                "id": "systems",
                "title": "Systems",
                "content": ", ".join(item.name for item in systems[:10]),
                "sources": [item.id for item in systems[:10]],
            }
        )
    if runs:
        sections.append(
            {
                "id": "runs",
                "title": "Recent Runs",
                "content": ", ".join(f"{item.id}: {item.status}" for item in runs[:10]),
                "sources": [item.id for item in runs[:10]],
            }
        )
    if decisions:
        sections.append(
            {
                "id": "decisions",
                "title": "Decisions",
                "content": ", ".join(
                    f"{item.title}: {item.status}" for item in decisions[:10]
                ),
                "sources": [item.id for item in decisions[:10]],
            }
        )
    payload.update(
        {
            "title": f"{workspace.name} briefing",
            "generated_at": datetime.now(UTC).isoformat(),
            "sections": sections,
            "actions": [],
            "sources": _sources_for(rows),
        }
    )
    return payload


def projects_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
) -> dict[str, Any]:
    systems = _systems(db, workspace, user)
    payload = _base(
        workspace,
        systems,
        empty_code="systems_not_configured",
        empty_message="No Systems are configured in this workspace.",
    )
    projects = [
        {
            "id": item.id,
            "name": item.name,
            "weather": _system_tone(item.status),
            "progress": None,
            "expected": None,
            "delay_days": None,
            "measurement_state": "not_measured",
            "owner": item.created_by or "",
            "cause": item.objective or "",
            "risk": item.status,
            "options": [],
            "sources": [item.id],
        }
        for item in systems
    ]
    payload.update(
        {
            "summary": {
                "total": len(projects),
                "red": sum(1 for item in systems if _system_tone(item.status) == "red"),
                "orange": sum(
                    1 for item in systems if _system_tone(item.status) == "orange"
                ),
                "green": sum(
                    1 for item in systems if _system_tone(item.status) == "green"
                ),
            },
            "projects": projects,
            "sources": _sources_for(systems),
        }
    )
    return payload


def timeline_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
) -> dict[str, Any]:
    del user
    events = _events(db, workspace)
    payload = _base(
        workspace,
        events,
        empty_code="calendar_not_configured",
        empty_message="No workspace calendar events are configured.",
    )
    agenda = [_agenda_item(item) for item in events]
    payload.update(
        {
            "agenda": agenda,
            "action_items": [],
            "messages": [],
            "summary": (
                f"{len(events)} workspace calendar event(s)."
                if events
                else "No workspace calendar events are configured."
            ),
            "calendar": {
                "connector": {
                    "id": "workspace_calendar",
                    "label": "Workspace calendar",
                    "mode": "internal_shared",
                    "status": "available" if events else "not_configured",
                    "write_policy": "workspace_scoped",
                },
                "count": len(events),
                "conflicts": [],
                "free_slots": [],
                "available_windows": [],
                "recommended_moves": [],
                "decision_deadlines": [],
                "conflict_score": None,
                "status": "available" if events else "not_configured",
                "next_event": agenda[0] if agenda else None,
                "summary": (
                    "Calendar events loaded."
                    if events
                    else "Calendar data is not configured."
                ),
            },
            "sources": _sources_for(events),
        }
    )
    return payload


def decisions_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
) -> dict[str, Any]:
    decisions = _decisions(db, workspace, user)
    payload = _base(
        workspace,
        decisions,
        empty_code="decisions_not_configured",
        empty_message="No Decisions are configured in this workspace.",
    )
    payload.update(
        {
            "decisions": [_decision_item(item) for item in decisions],
            "action_items": [],
            "action_summary": {
                "count": len(decisions),
                "active": sum(
                    1 for item in decisions if item.status in {"proposed", "accepted"}
                ),
                "critical": None,
                "completed": sum(
                    1 for item in decisions if item.status == "applied"
                ),
                "cancelled": sum(
                    1 for item in decisions if item.status == "rejected"
                ),
                "next_due": None,
                "write_policy": "approval_required",
            },
            "scenario_options": [],
            "policy": {
                "advisory_only": True,
                "requires_validation": True,
                "scope": "workspace",
            },
            "sources": _sources_for(decisions),
        }
    )
    return payload


def library_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
) -> dict[str, Any]:
    systems = _systems(db, workspace, user)
    decisions = _decisions(db, workspace, user)
    rows: list[Any] = [*systems, *decisions]
    payload = _base(
        workspace,
        rows,
        empty_code="library_objects_not_configured",
        empty_message="No Systems or Decisions are available in the workspace library.",
    )
    items = [
        {
            "id": item.id,
            "title": item.name,
            "kind": "system",
            "collection": "Systems",
            "summary": item.objective or f"Status: {item.status}",
            "sources": [item.id],
        }
        for item in systems
    ] + [
        {
            "id": item.id,
            "title": item.title,
            "kind": "decision",
            "collection": "Decisions",
            "summary": item.notes or f"Status: {item.status}",
            "sources": [item.id],
        }
        for item in decisions
    ]
    collections = [name for name, present in (("Systems", systems), ("Decisions", decisions)) if present]
    payload.update(
        {
            "items": items,
            "collections": collections,
            "sources": _sources_for(rows),
        }
    )
    return payload


def search_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
    query: str,
) -> dict[str, Any]:
    systems = _systems(db, workspace, user)
    runs = _runs(db, workspace, user)
    decisions = _decisions(db, workspace, user)
    audits = _audits(db, workspace, user)
    events = _events(db, workspace)
    rows: list[Any] = [*systems, *runs, *decisions, *audits, *events]
    needle = query.strip().lower()
    candidates = [
        {
            "id": item.id,
            "title": item.name,
            "kind": "system",
            "summary": item.objective or f"Status: {item.status}",
            "sources": [item.id],
        }
        for item in systems
    ] + [
        {
            "id": item.id,
            "title": f"Run {item.id}",
            "kind": "run",
            "summary": f"Status: {item.status}",
            "sources": [item.id],
        }
        for item in runs
    ] + [
        {
            "id": item.id,
            "title": item.title,
            "kind": "decision",
            "summary": item.notes or f"Status: {item.status}",
            "sources": [item.id],
        }
        for item in decisions
    ] + [
        {
            "id": item.id,
            "title": item.event_type,
            "kind": "audit",
            "summary": f"Severity: {item.severity}",
            "sources": [item.id],
        }
        for item in audits
    ] + [
        {
            "id": item.id,
            "title": item.title,
            "kind": "calendar_event",
            "summary": item.description or f"Status: {item.status}",
            "sources": [item.id],
        }
        for item in events
    ]
    results = [
        item
        for item in candidates
        if not needle
        or needle in item["title"].lower()
        or needle in item["summary"].lower()
    ]
    payload = _base(
        workspace,
        results,
        empty_code="search_no_results",
        empty_message="No workspace object matches the query.",
    )
    payload.update(
        {
            "query": query,
            "results": results,
            "total": len(results),
            "sources": _sources_for(rows),
        }
    )
    return payload


def map_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
) -> dict[str, Any]:
    del db, user
    payload = _base(
        workspace,
        (),
        empty_code="geospatial_data_not_configured",
        empty_message="No workspace geospatial data is configured.",
    )
    payload.update(
        {
            "question": "No geospatial question is configured.",
            "map": {
                "country": None,
                "view_box": None,
                "projection": None,
                "accuracy": "not_configured",
            },
            "zones": [],
            "recommended_windows": [],
            "score_summary": {
                "critical": None,
                "watch": None,
                "stable": None,
                "top_zone": None,
            },
            "sources": [],
        }
    )
    return payload


def monitor_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
) -> dict[str, Any]:
    runs = _runs(db, workspace, user)
    audits = _audits(db, workspace, user)
    rows: list[Any] = [*runs, *audits]
    payload = _base(
        workspace,
        rows,
        empty_code="operational_data_not_configured",
        empty_message="No Runs or audit events are available for monitoring.",
    )
    payload.update(
        {
            "title": f"{workspace.name} operations",
            "summary": (
                f"{len(runs)} Run(s) and {len(audits)} audit event(s) available."
                if rows
                else "Operational data is not configured."
            ),
            "posture": {
                "label": "Not measured",
                "score": None,
                "trend": "not_measured",
                "summary": "No provider-neutral posture model is configured.",
                "drivers": [],
            },
            "layers": [
                {
                    "key": "runs",
                    "label": "Runs",
                    "enabled": True,
                    "count": len(runs),
                },
                {
                    "key": "audit",
                    "label": "Audit",
                    "enabled": True,
                    "count": len(audits),
                },
            ],
            "map": {
                "country": None,
                "view_box": None,
                "projection": None,
                "accuracy": "not_configured",
            },
            "zones": [],
            "top_zones": [],
            "visual": {
                "connector": {
                    "id": "none",
                    "label": "Not configured",
                    "status": "not_configured",
                    "mode": "none",
                },
                "source_health": {
                    "active_sources": None,
                    "total_sources": None,
                    "captures": None,
                    "observations": None,
                    "last_capture_at": None,
                    "coverage_label": "not_configured",
                },
                "posture": {
                    "label": "Not measured",
                    "score": None,
                    "trend": "not_measured",
                    "summary": "Visual monitoring is not configured.",
                },
                "sources": [],
                "captures": [],
                "observations": [],
                "latest_observation": None,
            },
            "visual_observations": [],
            "forecasts": [],
            "news_signals": [],
            "source_freshness": {
                "runs": _iso(runs[0].started_at) if runs else "not_configured",
                "audit": _iso(audits[0].timestamp) if audits else "not_configured",
            },
            "sources": _sources_for(rows),
        }
    )
    return payload


def news_payload(
    db: DBSession,
    workspace: Workspace,
    user: User,
) -> dict[str, Any]:
    audits = _audits(db, workspace, user)
    payload = _base(
        workspace,
        (),
        empty_code="signal_feeds_not_configured",
        empty_message="No provider-neutral signal feed is configured.",
    )
    payload.update(
        {
            "summary": "Signal feeds are not configured.",
            "signals": [],
            "all_signals": [],
            "executive_alerts": [],
            "activity": [
                {
                    "id": item.id,
                    "event_type": item.event_type,
                    "severity": item.severity,
                    "actor": item.actor,
                    "timestamp": _iso(item.timestamp),
                }
                for item in audits
            ],
            "sources": _sources_for(audits),
        }
    )
    return payload


def draft_instruction_payload(
    *,
    db: DBSession,
    workspace: Workspace,
    user: User,
    target_id: str,
    target_type: str,
    instruction_type: str,
) -> dict[str, Any]:
    normalized_type = target_type.strip().lower()
    if normalized_type == "system":
        system = (
            db.query(System)
            .filter(System.workspace_id == workspace.id, System.id == target_id)
            .first()
        )
        readable = (
            _filter_systems(db, workspace, user, [system])
            if system is not None
            else []
        )
        target = readable[0] if readable else None
        title = target.name if target is not None else None
    elif normalized_type == "decision":
        decision = (
            db.query(Decision)
            .filter(Decision.workspace_id == workspace.id, Decision.id == target_id)
            .first()
        )
        readable = (
            _filter_decisions(db, workspace, user, [decision])
            if decision is not None
            else []
        )
        target = readable[0] if readable else None
        title = target.title if target is not None else None
    else:
        target = None
        title = None
    if target is None or title is None:
        raise HTTPException(status_code=404, detail="workspace_object_not_found")
    payload = {
        "schema_version": "mission_room.workspace_objects.v1",
        "provider_kind": GENERIC_MISSION_ROOM_PROVIDER_KIND,
        "workspace": _workspace(workspace),
        "state": "available",
        "empty_state": None,
        "status": "draft",
        "requires_validation": True,
        "sent": False,
        "title": f"Review {title}",
        "recipient": "",
        "body": f"Review requested for {normalized_type} {title}.",
        "sources": [target_id],
        "control": {
            "effect": "none",
            "approval": "required",
            "instruction_type": instruction_type,
            "target_type": normalized_type,
            "target_id": target_id,
        },
    }
    audit_id = emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="mission_room.generic_draft.created",
        actor=user.email or user.username or user.id,
        details={
            "target_id": target_id,
            "target_type": normalized_type,
            "instruction_type": instruction_type,
            "sent": False,
        },
    )
    if audit_id is None:
        db.rollback()
        raise RuntimeError("Mission Room draft audit could not be persisted")
    return payload


def _system_tone(status: str) -> str:
    return {
        "active": "green",
        "draft": "orange",
        "paused": "orange",
        "retired": "red",
    }.get(status, "orange")


def _system_record(item: System) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "objective": item.objective,
        "status": item.status,
        "capability_id": item.capability_id,
        "updated_at": _iso(item.updated_at),
    }


def _run_record(item: Run) -> dict[str, Any]:
    return {
        "id": item.id,
        "system_id": item.system_id,
        "capability_id": item.capability_id,
        "status": item.status,
        "started_at": _iso(item.started_at),
        "completed_at": _iso(item.completed_at),
        "duration_ms": item.duration_ms,
    }


def _decision_record(item: Decision) -> dict[str, Any]:
    return {
        "id": item.id,
        "scope": item.scope,
        "target_id": item.target_id,
        "kind": item.kind,
        "status": item.status,
        "title": item.title,
        "created_at": _iso(item.created_at),
    }


def _event_record(item: WorkspaceCalendarEvent) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "start_at": _iso(item.start_at),
        "end_at": _iso(item.end_at),
        "timezone": item.timezone,
        "location": item.location,
        "participants": list(item.participants or []),
        "category": item.category,
        "priority": item.priority,
        "status": item.status,
        "source_label": item.source_label,
    }


def _agenda_item(item: WorkspaceCalendarEvent) -> dict[str, Any]:
    return {
        "id": item.id,
        "date": item.start_at.date().isoformat(),
        "time": item.start_at.strftime("%H:%M"),
        "end_time": item.end_at.strftime("%H:%M"),
        "title": item.title,
        "location": item.location,
        "tone": {
            "critical": "critical",
            "high": "watch",
            "medium": "info",
            "low": "stable",
        }.get(item.priority, "info"),
        "description": item.description,
        "participants": list(item.participants or []),
        "priority": item.priority,
        "status": item.status,
        "category": item.category,
        "source_label": item.source_label,
        "metadata": dict(item.meta_data or {}),
    }


def _decision_item(item: Decision) -> dict[str, Any]:
    rationale = item.rationale if isinstance(item.rationale, Mapping) else {}
    recommendation = next(
        (
            str(rationale[key])
            for key in ("recommendation", "summary", "reason")
            if isinstance(rationale.get(key), str) and str(rationale[key]).strip()
        ),
        item.notes or "",
    )
    return {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "risk": item.kind,
        "recommendation": recommendation,
        "target_id": item.target_id or "",
        "target_type": item.scope,
        "sources": [item.id],
    }


def _sources_for(rows: Sequence[Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        identifier = str(row.id)
        if identifier in seen:
            continue
        seen.add(identifier)
        if isinstance(row, System):
            sources.append(_source(identifier, row.name, "system"))
        elif isinstance(row, Run):
            sources.append(_source(identifier, f"Run {identifier}", "run"))
        elif isinstance(row, Decision):
            sources.append(_source(identifier, row.title, "decision"))
        elif isinstance(row, WorkspaceCalendarEvent):
            sources.append(_source(identifier, row.title, "calendar_event"))
        elif isinstance(row, AuditLog):
            sources.append(_source(identifier, row.event_type, "audit"))
    return sources
