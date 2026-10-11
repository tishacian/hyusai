"""The read model that names Systems whose dispatch surfaces are refused."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from app.models.run_schedule import RunSchedule
from app.models.system import System
from app.models.workspace import Workspace
from app.services.systems import dispatch_readiness
from app.tests.publication_baseline import baseline_flow_publication


def _workspace(db) -> Workspace:
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="Readiness WS",
        slug=f"readiness-{uuid.uuid4().hex[:6]}",
    )
    db.add(ws)
    db.commit()
    return ws


def _flow(source_id: str, source_type: str) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": source_id, "kind": "source", "type": source_type},
            {"id": "snk", "kind": "sink"},
        ],
        "edges": [{"from": source_id, "to": "snk", "kind": "control"}],
    }


def _system(
    db,
    workspace_id: str,
    *,
    name: str,
    flow: dict[str, Any],
    published: bool = True,
    status: str = "active",
) -> System:
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name=name,
        objective="dispatch",
        flow_definition=flow,
        status=status,
    )
    db.add(system)
    db.commit()
    return baseline_flow_publication(db, system) if published else system


def _schedule(db, system: System, *, name: str = "Monday report") -> RunSchedule:
    row = RunSchedule(
        id=str(uuid.uuid4()),
        workspace_id=system.workspace_id,
        system_id=system.id,
        name=name,
        cron_expr="0 8 * * 1",
        timezone="UTC",
        enabled=True,
        next_fire_at=datetime.utcnow() + timedelta(days=1),
    )
    db.add(row)
    db.commit()
    return row


def _surface(report: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(item for item in report["surfaces"] if item["kind"] == kind)


def test_a_published_schedule_reports_ready_with_its_pinned_identity(db_session):
    ws = _workspace(db_session)
    system = _system(
        db_session,
        ws.id,
        name="Healthy",
        flow=_flow("src.cron", "source.schedule"),
    )
    schedule = _schedule(db_session, system)

    report = dispatch_readiness.system_dispatch_readiness(
        db_session,
        system=system,
        workspace=ws,
    )

    assert report["ready"] is True
    assert report["blocked"] is None
    assert report["published_flow_version_id"] == system.published_flow_version_id
    surface = _surface(report, "schedule")
    assert surface["surface_id"] == schedule.id
    assert surface["name"] == "Monday report"
    assert surface["ingress_id"] == "src.cron"
    assert surface["blocked"] is None


def test_a_system_the_backfill_missed_names_the_refusal_on_every_surface(db_session):
    ws = _workspace(db_session)
    system = _system(
        db_session,
        ws.id,
        name="Unrepaired",
        flow=_flow("src.hook", "source.webhook"),
        published=False,
    )
    _schedule(db_session, system)

    report = dispatch_readiness.system_dispatch_readiness(
        db_session,
        system=system,
        workspace=ws,
    )

    assert report["ready"] is False
    assert report["blocked"] == {
        "code": "PUBLISHED_FLOW_VERSION_INVALID",
        "message": "The published pointer does not reference an owned immutable version.",
    }
    # The surfaces stay named off the mirror so the operator sees what is inert.
    assert {item["kind"] for item in report["surfaces"]} == {"schedule", "http"}
    assert all(item["ready"] is False for item in report["surfaces"])
    assert all(item["blocked"] == report["blocked"] for item in report["surfaces"])


def test_a_surface_with_no_published_ingress_is_refused_on_its_own(db_session):
    """A live webhook and a silently inert cron on one healthy System."""

    ws = _workspace(db_session)
    system = _system(
        db_session,
        ws.id,
        name="Half wired",
        flow=_flow("src.hook", "source.webhook"),
    )
    _schedule(db_session, system)

    report = dispatch_readiness.system_dispatch_readiness(
        db_session,
        system=system,
        workspace=ws,
    )

    assert report["ready"] is False
    # Nothing is wrong with the publication itself, only with one surface.
    assert report["blocked"] is None
    assert _surface(report, "http")["ready"] is True
    assert _surface(report, "schedule")["blocked"] == {
        "code": "FLOW_INGRESS_KIND_UNAVAILABLE",
        "message": "The published Flow has no ingress for this adapter kind.",
    }


def test_an_inactive_system_is_reported_blocked_rather_than_omitted(db_session):
    ws = _workspace(db_session)
    system = _system(
        db_session,
        ws.id,
        name="Paused",
        flow=_flow("src.cron", "source.schedule"),
        status="draft",
    )
    _schedule(db_session, system)

    report = dispatch_readiness.system_dispatch_readiness(
        db_session,
        system=system,
        workspace=ws,
    )

    assert report["ready"] is False
    assert report["blocked"]["code"] == "FLOW_INGRESS_SYSTEM_INACTIVE"


def test_the_estate_view_counts_only_systems_that_declare_a_dispatch_surface(db_session):
    ws = _workspace(db_session)
    healthy = _system(
        db_session,
        ws.id,
        name="A healthy",
        flow=_flow("src.cron", "source.schedule"),
    )
    _schedule(db_session, healthy)
    unrepaired = _system(
        db_session,
        ws.id,
        name="B unrepaired",
        flow=_flow("src.cron", "source.schedule"),
        published=False,
    )
    _schedule(db_session, unrepaired)
    # No schedule row and no trigger node: this System dispatches by design only
    # when an operator asks, which already fails loudly.
    _system(
        db_session,
        ws.id,
        name="C manual only",
        flow=_flow("src.manual", "source.manual"),
    )
    # Archived: its surfaces are inert on purpose.
    retired = _system(
        db_session,
        ws.id,
        name="D retired",
        flow=_flow("src.cron", "source.schedule"),
        published=False,
        status="retired",
    )
    _schedule(db_session, retired)

    estate = dispatch_readiness.workspace_dispatch_readiness(db_session, workspace=ws)

    assert estate["summary"] == {"dispatching_systems": 2, "ready": 1, "blocked": 1}
    assert [item["system_name"] for item in estate["systems"]] == [
        "A healthy",
        "B unrepaired",
    ]
    blocked = [item for item in estate["systems"] if not item["ready"]]
    assert [item["system_id"] for item in blocked] == [unrepaired.id]
