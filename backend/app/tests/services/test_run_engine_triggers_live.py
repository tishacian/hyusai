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
from app.models.run_dispatch_outbox import RunDispatchOutbox
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.run_engine import triggers
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_publication
from app.tests.publication_baseline import LEGACY_FLOW_AUTHORITY


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
    # These fixtures bind Skills they never seed, so a publication contract
    # cannot compile for them; the published path has its own fixture below.
    ws = Workspace(
        id=str(uuid.uuid4()),
        name="WS",
        slug=f"ws-{uuid.uuid4().hex[:6]}",
        settings=dict(LEGACY_FLOW_AUTHORITY),
    )
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


def _published_event_system(db):
    workspace = Workspace(
        id=str(uuid.uuid4()),
        name="Published trigger WS",
        slug=f"published-trigger-{uuid.uuid4().hex[:6]}",
        settings={"features": {"flow_publication_v1": True}},
    )
    flow = {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": [
            {
                "id": "src.dep.v1",
                "kind": "source",
                "type": "source.deposit_promoted",
                "config": {
                    "ingress_kind": "event",
                    "input_schema": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
            },
            {"id": "result.v1", "kind": "sink"},
        ],
        "edges": [{"from": "src.dep.v1", "to": "result.v1"}],
    }
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        name="Published Trigger System",
        objective="test",
        flow_definition=flow,
        settings={"event_trigger": {"mode": "live"}},
        status="active",
    )
    db.add_all([workspace, system])
    db.flush()
    contract = flow_publication.compile_execution_contract(
        db,
        flow,
        workspace,
        system=system,
    )
    version = SystemVersion(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=1,
        flow_definition=flow,
        flow_sha256=canonical_flow_sha256(flow),
        release_kind="publish",
        draft_revision=1,
        execution_contract=contract,
        message="published trigger v1",
        created_by="test",
    )
    db.add(version)
    db.flush()
    system.published_flow_version_id = version.id
    db.commit()
    return workspace, system, version, flow


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
    """Prove the legacy in-process dispatch path is no longer used."""
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

    assert results[0]["status"] == "queued"
    runs = _real_runs(db_session, system.id)
    assert len(runs) == 1
    assert runs[0].status == "pending"
    assert runs[0].trigger == "webhook"
    meta = runs[0].input_ref["_event_trigger"]
    assert meta["simulated"] is False
    assert meta["mode"] == "live"
    assert dispatched == []
    event = db_session.query(RunDispatchOutbox).filter_by(run_id=runs[0].id).one()
    assert event.event_type == "trigger_run"
    assert event.source_id == runs[0].trigger_dedup_key


def test_live_dedup_suppresses_second(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    payload = {"file_id": "f1"}

    first = triggers.emit_event(triggers.EVENT_DEPOSIT_PROMOTED, ws.id, payload, db=db_session)
    second = triggers.emit_event(triggers.EVENT_DEPOSIT_PROMOTED, ws.id, payload, db=db_session)

    assert first[0]["status"] == "queued"
    assert second[0]["status"] == "duplicate"
    assert len(_real_runs(db_session, system.id)) == 1
    assert dispatched == []
    assert db_session.query(RunDispatchOutbox).count() == 1


def test_live_queue_respects_caller_transaction_rollback(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    original_objective = system.objective
    system.objective = "caller-owned mutation"

    result = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED,
        ws.id,
        {"file_id": "rollback-live"},
        db=db_session,
    )
    assert result[0]["status"] == "queued"
    db_session.rollback()

    assert db_session.get(System, system.id).objective == original_objective
    assert db_session.query(Run).filter_by(system_id=system.id).count() == 0
    assert db_session.query(RunDispatchOutbox).count() == 0
    assert dispatched == []


def test_published_trigger_freezes_the_locked_version_and_atomic_claim(
    db_session,
    dispatched,
):
    workspace, system, version, flow = _published_event_system(db_session)
    payload = {"file_id": "published-1"}

    result = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED,
        workspace.id,
        payload,
        db=db_session,
        system_id=system.id,
    )

    assert result[0]["status"] == "queued"
    run = db_session.get(Run, result[0]["run_id"])
    assert run is not None
    assert run.published_flow_version_id == version.id
    assert run.flow_sha256 == version.flow_sha256
    assert run.flow_snapshot == flow
    assert run.trigger_dedup_key == result[0]["dedup_key"]
    assert dispatched == []
    assert db_session.query(RunDispatchOutbox).filter_by(run_id=run.id).count() == 1


def test_published_trigger_rejects_pointer_interleaving_instead_of_mixing_graphs(
    db_session,
    dispatched,
    monkeypatch,
):
    workspace, system, version_v1, flow_v1 = _published_event_system(db_session)
    flow_v2 = {
        **flow_v1,
        "nodes": [
            {
                **flow_v1["nodes"][0],
                "id": "src.dep.v2",
            },
            {"id": "result.v2", "kind": "sink"},
        ],
        "edges": [{"from": "src.dep.v2", "to": "result.v2"}],
    }
    contract_v2 = flow_publication.compile_execution_contract(
        db_session,
        flow_v2,
        workspace,
        system=system,
    )
    version_v2 = SystemVersion(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        version_number=2,
        flow_definition=flow_v2,
        flow_sha256=canonical_flow_sha256(flow_v2),
        release_kind="publish",
        draft_revision=2,
        execution_contract=contract_v2,
        message="interleaving candidate",
        created_by="test",
    )
    db_session.add(version_v2)
    db_session.commit()

    captured: dict[str, str | None] = {}
    original = triggers.flow_ingress.create_published_ingress_run

    def interleave_pointer(db, **kwargs):
        captured["expected_version"] = kwargs.get("expected_published_version_id")
        captured["expected_hash"] = kwargs.get("expected_flow_sha256")
        captured["ingress_id"] = kwargs.get("ingress_id")
        current = db.get(System, system.id)
        current.published_flow_version_id = version_v2.id
        current.flow_definition = flow_v2
        db.flush()
        return original(db, **kwargs)

    monkeypatch.setattr(
        triggers.flow_ingress,
        "create_published_ingress_run",
        interleave_pointer,
    )

    result = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED,
        workspace.id,
        {"file_id": "interleaving"},
        db=db_session,
        system_id=system.id,
    )

    assert result[0]["status"] == "rejected"
    assert result[0]["reason"] == "published_flow_version_mismatch"
    assert captured == {
        "expected_version": version_v1.id,
        "expected_hash": version_v1.flow_sha256,
        "ingress_id": "src.dep.v1",
    }
    assert db_session.query(Run).filter(Run.system_id == system.id).count() == 0
    assert dispatched == []


def test_published_ingress_rejection_does_not_rollback_caller_work(
    db_session,
    dispatched,
    monkeypatch,
):
    workspace, system, _version, _flow = _published_event_system(db_session)
    workspace.name = "caller mutation survives trigger rejection"
    original = triggers.flow_ingress.create_published_ingress_run

    def reject_ingress(db, **kwargs):
        raise triggers.flow_ingress.FlowIngressError(
            "FLOW_INGRESS_TEST_REJECTION",
            "reject without rolling back caller",
        )

    monkeypatch.setattr(triggers.flow_ingress, "create_published_ingress_run", reject_ingress)
    result = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED,
        workspace.id,
        {"file_id": "reject-without-rollback"},
        db=db_session,
        system_id=system.id,
    )
    monkeypatch.setattr(triggers.flow_ingress, "create_published_ingress_run", original)

    assert result[0]["status"] == "rejected"
    db_session.commit()
    db_session.expire(workspace)
    assert workspace.name == "caller mutation survives trigger rejection"
    assert db_session.query(Run).filter_by(system_id=system.id).count() == 0
    assert dispatched == []


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

    assert results[0]["status"] == "queued"
    assert dispatched == []
    assert db_session.query(RunDispatchOutbox).count() == 1


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


def test_circuit_breaker_respects_caller_transaction_rollback(db_session, dispatched):
    ws = _make_workspace(db_session)
    system = _make_system(db_session, workspace_id=ws.id, flow=_deposit_analysis_flow())
    for _ in range(triggers.CIRCUIT_BREAKER_FAILURE_THRESHOLD):
        _seed_triggered_run(db_session, system, status="failed")
    original_objective = system.objective
    system.objective = "caller-owned circuit mutation"

    result = triggers.emit_event(
        triggers.EVENT_DEPOSIT_PROMOTED,
        ws.id,
        {"file_id": "circuit-rollback"},
        db=db_session,
    )
    assert result[0]["status"] == "circuit_open"
    db_session.rollback()

    refreshed = db_session.get(System, system.id)
    assert refreshed.objective == original_objective
    assert (refreshed.settings.get("event_trigger") or {}).get("disabled") is not True
    assert (
        db_session.query(Decision)
        .filter(Decision.target_id == system.id, Decision.kind == "trigger_circuit_open")
        .count()
        == 0
    )
    assert dispatched == []


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
    system = _make_system(
        db_session, workspace_id=ws.id, flow=_deposit_analysis_flow(), mode="dry_run"
    )

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
        workspace_id=ws.id,
        scope="system",
        target_id=system.id,
        extra={"event_trigger_max_runs_per_hour": 2},
    )
    system.control_policy_id = policy.id
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
