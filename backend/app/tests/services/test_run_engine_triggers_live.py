"""Sub-lot B (live execution) tests for ``run_engine.triggers``.

Covers the per-System ``live`` mode dispatch and its guards — idempotence,
rate limit, circuit breaker (+ proposed Decision), the dry-run no-op and the
governance allowlist still holding on the live path. ``_dispatch_live_run`` is
monkeypatched so no flow is actually executed.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.core.config import settings
from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System
from app.models.workspace import Workspace
from app.services.run_engine import triggers


def _deposit_analysis_flow() -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "src.dep", "kind": "source", "type": "source.deposit_promoted"},
            {"id": "t.analyze", "kind": "task", "config": {"skill_slug": "response_eval_v1"}},
            {"id": "snk", "kind": "sink"},
        ],
        "edges": [
            {"from": "src.dep", "to": "t.analyze", "kind": "control"},
            {"from": "t.analyze", "to": "snk", "kind": "data"},
        ],
    }


def _sftp_ingestion_flow() -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "src.sftp", "kind": "source", "type": "source.sftp_arrival"},
            {
                "id": "t.ingest",
                "kind": "task",
                "config": {"skill_slug": "document_ingest_index", "effect": "ingestion"},
            },
        ],
        "edges": [{"from": "src.sftp", "to": "t.ingest", "kind": "control"}],
    }


def _make_workspace(db) -> Workspace:
    ws = Workspace(id=str(uuid.uuid4()), name="WS", slug=f"ws-{uuid.uuid4().hex[:6]}", settings={})
    db.add(ws)
    db.commit()
    return ws


def _make_system(db, *, workspace_id: str, flow: dict, mode: str = "live") -> System:
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="Live Trigger System",
        objective="test",
        flow_definition=flow,
        settings={"event_trigger": {"mode": mode}},
        status="active",
    )
    db.add(system)
    db.commit()
    return system


def _seed_triggered_run(db, system, *, status: str, started_at=None) -> Run:
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=system.workspace_id,
        system_id=system.id,
        status=status,
        trigger="webhook",
        input_ref={"_event_trigger": {"dedup_key": f"seed-{uuid.uuid4()}", "simulated": False}},
        started_at=started_at or datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    return run


@pytest.fixture()
def dispatched(monkeypatch):
    """Capture ``_dispatch_live_run`` calls instead of executing a flow."""
    calls: list[str] = []
    monkeypatch.setattr(settings, "enable_event_triggers", True)
    monkeypatch.setattr(triggers, "_dispatch_live_run", lambda run_id: calls.append(run_id))
    return calls


def _real_runs(db, system_id):
    return (
        db.query(Run)
        .filter(Run.system_id == system_id, Run.trigger == "webhook", Run.status != "simulated")
        .all()
    )


# ---------------------------------------------------------------------------
def test_live_dispatches_exactly_one_run(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())

    results = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED, ws.id, {"file_id": "f1"}, db=db_session
    )

    assert results[0]["status"] == "dispatched"
    runs = _real_runs(db_session, system.id)
    assert len(runs) == 1
    assert runs[0].status == "pending"
    assert runs[0].trigger == "webhook"
    meta = runs[0].input_ref["_event_trigger"]
    assert meta["simulated"] is False
    assert meta["mode"] == "live"
    assert dispatched == [runs[0].id]


def test_live_dedup_suppresses_second(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    payload = {"file_id": "f1"}

    first = triggers.emit_event(triggers.EVENT_DEPOSIT_PROMOTED, ws.id, payload, db=db_session)
    second = triggers.emit_event(triggers.EVENT_DEPOSIT_PROMOTED, ws.id, payload, db=db_session)

    assert first[0]["status"] == "dispatched"
    assert second[0]["status"] == "duplicate"
    assert len(_real_runs(db_session, system.id)) == 1
    assert len(dispatched) == 1


def test_rate_limit_blocks_over_limit(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    for _ in range(triggers.DEFAULT_MAX_TRIGGERED_RUNS_PER_HOUR):
        _seed_triggered_run(db_session, system, status="completed")

    results = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED, ws.id, {"file_id": "new"}, db=db_session
    )

    assert results[0]["status"] == "rate_limited"
    # No NEW run beyond the 10 seeded, and nothing dispatched.
    assert len(_real_runs(db_session, system.id)) == triggers.DEFAULT_MAX_TRIGGERED_RUNS_PER_HOUR
    assert dispatched == []


def test_rate_limit_ignores_runs_outside_window(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    old = datetime.utcnow() - timedelta(hours=2)
    for _ in range(triggers.DEFAULT_MAX_TRIGGERED_RUNS_PER_HOUR):
        _seed_triggered_run(db_session, system, status="completed", started_at=old)

    results = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED, ws.id, {"file_id": "new"}, db=db_session
    )

    assert results[0]["status"] == "dispatched"
    assert len(dispatched) == 1


def test_circuit_breaker_trips_after_three_failures(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    for _ in range(triggers.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
        _seed_triggered_run(db_session, system, status="failed")

    results = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED, ws.id, {"file_id": "new"}, db=db_session
    )

    assert results[0]["status"] == "circuit_open"
    assert dispatched == []
    # Trigger disabled on the System.
    refreshed = db_session.query(System).filter(System.id == system.id).one()
    assert (refreshed.settings["event_trigger"]["disabled"]) is True
    # A proposed Decision was filed via the Hypervisor mechanism.
    decision = (
        db_session.query(Decision)
        .filter(Decision.target_id == system.id, Decision.kind == "trigger_circuit_open")
        .one()
    )
    assert decision.status == "proposed"


def test_disabled_trigger_stays_open(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    system.settings = {"event_trigger": {"mode": "live", "disabled": True}}
    db_session.commit()

    results = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED, ws.id, {"file_id": "f1"}, db=db_session
    )

    assert results[0]["status"] == "circuit_open"
    assert dispatched == []
    assert _real_runs(db_session, system.id) == []


def test_dry_run_system_never_dispatches(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow(), mode="dry_run")

    results = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED, ws.id, {"file_id": "f1"}, db=db_session
    )

    assert results[0]["status"] == "simulated"
    assert dispatched == []
    run = db_session.query(Run).filter(Run.system_id == system.id).one()
    assert run.status == "simulated"


def test_live_governance_still_enforced(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_sftp_ingestion_flow())

    results = triggers.emit_event(
        triggers.EVENT_SFTP_FILE_ARRIVED, ws.id, {"job_id": "j1"}, db=db_session
    )

    assert results[0]["status"] == "rejected"
    assert results[0]["reason"].startswith("effect_not_permitted:ingestion")
    assert dispatched == []
    assert db_session.query(Run).filter(Run.system_id == system.id).count() == 0


def test_rate_limit_respects_control_policy_override(db_session, dispatched):
    from app.models.policy import ControlPolicy

    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    policy = ControlPolicy(
        id=str(uuid.uuid4()),
        scope="system",
        target_id=system.id,
        extra={"event_trigger_max_runs_per_hour": 2},
    )
    db_session.add(policy)
    db_session.commit()
    for _ in range(2):
        _seed_triggered_run(db_session, system, status="completed")

    results = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED, ws.id, {"file_id": "new"}, db=db_session
    )

    assert results[0]["status"] == "rate_limited"
    assert dispatched == []
    # Clean up the non-truncated control_policies row for suite isolation.
    db_session.delete(policy)
    db_session.commit()
