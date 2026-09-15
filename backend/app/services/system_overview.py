"""Truthful, task-oriented read model for one System overview.

Unlike the legacy dashboard, every value here is scoped to the requested
System and evidence window. Missing evidence stays missing; it is never
converted into a healthy-looking zero or percentage.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.models.evaluation import EvaluationScore
from app.models.run import Run
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.services.run_access import readable_runs
from app.services.systems import flow_ingress

WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"pending", "running", "waiting_subflows", "hitl_pending"}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _action(label: str, href: str) -> dict[str, str]:
    return {"label": label, "href": href}


def _blocker(code: str, message: str, action: dict[str, str]) -> dict[str, Any]:
    return {"code": code, "message": message, "action": action}


def _readiness(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    blockers: list[dict[str, Any]] = []
    published: dict[str, Any] | None = None

    if system.status == "draft":
        blockers.append(
            _blocker(
                "system_draft",
                "Finish setup and publish the Flow before running this System.",
                _action("Open Builder", f"/systems/{system.id}/flow"),
            )
        )
    elif system.status == "paused":
        blockers.append(
            _blocker(
                "system_paused",
                "This System is paused and cannot accept new runs.",
                _action("Review settings", f"/systems/{system.id}?facet=design"),
            )
        )
    elif system.status == "retired":
        blockers.append(
            _blocker(
                "system_retired",
                "This System is retired and kept for history only.",
                _action("View runs", f"/systems/{system.id}?facet=runs"),
            )
        )

    if system.published_flow_version_id is None:
        blockers.append(
            _blocker(
                "flow_not_published",
                "No published Flow is available to the run engine.",
                _action("Open Builder", f"/systems/{system.id}/flow"),
            )
        )
    else:
        try:
            published = flow_ingress.assert_dispatchable(
                db,
                system_id=system.id,
                workspace=workspace,
            )
        except flow_ingress.FlowIngressError as exc:
            blockers.append(
                _blocker(
                    exc.code,
                    exc.message,
                    _action("Repair in Builder", f"/systems/{system.id}/flow"),
                )
            )

    if not blockers:
        state = "ready"
        label = "Ready to run"
        primary_action = _action("Run System", f"/systems/{system.id}/run")
    elif system.status == "paused":
        state = "paused"
        label = "Paused"
        primary_action = blockers[0]["action"]
    elif system.status == "retired":
        state = "retired"
        label = "Retired"
        primary_action = blockers[0]["action"]
    elif system.status == "draft" or system.published_flow_version_id is None:
        state = "needs_setup"
        label = "Setup required"
        primary_action = blockers[0]["action"]
    else:
        state = "blocked"
        label = "Run blocked"
        primary_action = blockers[0]["action"]

    return (
        {
            "state": state,
            "label": label,
            "can_run": state == "ready",
            "blockers": blockers,
            "primary_action": primary_action,
        },
        published,
    )


def build_system_overview(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    system: System,
    window: str = "30d",
) -> dict[str, Any]:
    """Build the compact default read model for a System detail page."""

    if window not in WINDOW_DAYS:
        raise ValueError("window must be 7d, 30d or 90d")
    since = datetime.utcnow() - timedelta(days=WINDOW_DAYS[window])
    runs = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace.id,
            Run.system_id == system.id,
            Run.started_at >= since,
        )
        .order_by(Run.started_at.desc())
        .all()
    )
    runs = readable_runs(db, runs=runs, user=user, workspace=workspace)
    run_ids = [row.id for row in runs]
    evaluations = (
        db.query(EvaluationScore)
        .filter(
            EvaluationScore.workspace_id == workspace.id,
            or_(
                EvaluationScore.run_id.in_(run_ids) if run_ids else False,
                EvaluationScore.agent_id == system.id,
            ),
            EvaluationScore.created_at >= since,
        )
        .order_by(EvaluationScore.created_at.desc())
        .all()
    )

    readiness, published = _readiness(db, workspace=workspace, system=system)
    version = None
    if system.published_flow_version_id:
        version = (
            db.query(SystemVersion)
            .filter(
                SystemVersion.id == system.published_flow_version_id,
                SystemVersion.system_id == system.id,
                SystemVersion.workspace_id == workspace.id,
            )
            .first()
        )

    terminal = [row for row in runs if row.status in TERMINAL_STATUSES]
    completed = [row for row in terminal if row.status == "completed"]
    failed = [row for row in terminal if row.status == "failed"]
    active = [row for row in runs if row.status in ACTIVE_STATUSES]
    durations = [float(row.duration_ms) for row in completed if row.duration_ms is not None]
    success_rate = round(len(completed) / len(terminal) * 100.0, 1) if terminal else None
    latest = runs[0] if runs else None
    quality = evaluations[0] if evaluations else None

    return {
        "window": window,
        "since": _iso(since),
        "generated_at": _iso(datetime.utcnow()),
        "system": {
            "id": system.id,
            "name": system.name,
            "objective": system.objective,
            "status": system.status,
        },
        "readiness": readiness,
        "publication": {
            "state": "published" if version is not None else "missing",
            "version_id": version.id if version is not None else None,
            "version_number": version.version_number if version is not None else None,
            "published_at": _iso(system.published_at),
            "flow_sha256": (
                published.get("flow_sha256")
                if published
                else (version.flow_sha256 if version is not None else None)
            ),
        },
        "runs": {
            "total": len(runs),
            "completed": len(completed),
            "failed": len(failed),
            "active": len(active),
            "success_rate": success_rate,
            "avg_latency_ms": round(sum(durations) / len(durations), 1) if durations else None,
            "latest": None
            if latest is None
            else {
                "id": latest.id,
                "status": latest.status,
                "started_at": _iso(latest.started_at),
                "duration_ms": latest.duration_ms,
                "error": latest.error,
            },
        },
        "quality": {
            "state": "available" if quality is not None else "not_measured",
            "score": quality.composite_score if quality is not None else None,
            "hallucination_rate": quality.hallucination_rate if quality is not None else None,
            "measured_at": _iso(quality.created_at) if quality is not None else None,
            "sample_count": len(evaluations),
        },
    }
