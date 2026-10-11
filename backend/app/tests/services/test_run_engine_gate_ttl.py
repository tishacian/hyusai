"""Unit tests for HITL / membrane gate TTL sweep (orchestration Phase 4)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from app.models.decision import Decision
from app.models.run import Run
from app.models.run_dispatch_outbox import RunDispatchOutbox
from app.models.system import System
from app.models.workspace import Workspace
from app.services.run_engine import gate_ttl


def _workspace(db) -> Workspace:
    ws = Workspace(id=str(uuid.uuid4()), name="TTL WS", slug=f"ttl-{uuid.uuid4().hex[:6]}")
    db.add(ws)
    db.commit()
    return ws


def _system(db, workspace_id: str) -> System:
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="TTL System",
        objective="gate",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
        status="active",
    )
    db.add(system)
    db.commit()
    return system


def _paused_run(db, *, workspace_id: str, system_id: str) -> Run:
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        system_id=system_id,
        status="hitl_pending",
        trigger="manual",
        input_ref={"correlation_key": "ord-1"},
        checkpoints=[
            {
                "kind": "hitl_pause",
                "node_id": "gate",
                "decision_id": None,
                "correlation_key": "ord-1",
            }
        ],
    )
    db.add(run)
    db.commit()
    return run


def test_resolve_gate_ttl_defaults():
    expires_at, action = gate_ttl.resolve_gate_ttl({}, now=datetime(2026, 1, 1))
    assert action == "reject"
    assert expires_at == datetime(2026, 1, 1) + timedelta(days=3)


def test_resolve_gate_ttl_from_node_config():
    expires_at, action = gate_ttl.resolve_gate_ttl(
        {"expires_in_days": 1, "expiry_action": "approve"},
        now=datetime(2026, 1, 1),
    )
    assert action == "approve"
    assert expires_at == datetime(2026, 1, 2)


def test_stamp_decision_ttl(db_session):
    dec = Decision(
        id=str(uuid.uuid4()),
        scope="run",
        target_id="r1",
        kind="hitl_approval",
        status="proposed",
        title="Gate",
        rationale={},
    )
    db_session.add(dec)
    db_session.commit()
    gate_ttl.stamp_decision_ttl(dec, {"expires_in_days": 2, "expiry_action": "escalate"})
    db_session.commit()
    db_session.refresh(dec)
    assert dec.expiry_action == "escalate"
    assert dec.expires_at is not None
    assert (dec.rationale or {}).get("gate_ttl", {}).get("expiry_action") == "escalate"


def test_sweep_expired_gates_rejects_and_resumes(db_session):
    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    run = _paused_run(db_session, workspace_id=ws.id, system_id=system.id)
    dec = Decision(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        status="proposed",
        title="Gate",
        rationale={"node_id": "gate"},
        expires_at=datetime.utcnow() - timedelta(minutes=1),
        expiry_action="reject",
    )
    db_session.add(dec)
    # Link checkpoint decision_id for realism.
    cps = [dict(checkpoint) for checkpoint in run.checkpoints or []]
    cps[0]["decision_id"] = dec.id
    run.checkpoints = cps
    db_session.commit()

    with patch.object(gate_ttl, "_resume_paused_run") as resume:
        result = gate_ttl.sweep_expired_gates()

    assert result["status"] == "ok"
    assert result["swept"] == 1, result
    db_session.refresh(dec)
    assert dec.status == "rejected"
    assert any(g["action"] == "reject" for g in result["gates"])
    resume.assert_called_once_with(run.id, dec.id)


def test_postgresql_lock_failure_never_falls_back_to_unlocked_mutation(
    db_session,
    monkeypatch,
):
    from sqlalchemy.orm import Query

    from app.db.base import engine

    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    run = _paused_run(db_session, workspace_id=ws.id, system_id=system.id)
    decision = Decision(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        status="proposed",
        title="Locked gate",
        expires_at=datetime.utcnow() - timedelta(minutes=1),
        expiry_action="reject",
    )
    checkpoints = [dict(checkpoint) for checkpoint in run.checkpoints or []]
    checkpoints[0]["decision_id"] = decision.id
    run.checkpoints = checkpoints
    db_session.add(decision)
    db_session.commit()

    original_first = Query.first

    def fail_locked_first(query):
        if query._for_update_arg is not None:
            raise RuntimeError("synthetic PostgreSQL lock failure")
        return original_first(query)

    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    monkeypatch.setattr(Query, "first", fail_locked_first)

    result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 0
    assert result["errors"] == 1
    db_session.refresh(decision)
    db_session.refresh(run)
    assert decision.status == "proposed"
    assert not any(
        checkpoint.get("kind") == "gate_ttl_expired"
        for checkpoint in run.checkpoints or []
    )


def test_sweep_expired_gates_escalate_keeps_proposed(db_session):
    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    run = _paused_run(db_session, workspace_id=ws.id, system_id=system.id)
    dec = Decision(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        status="proposed",
        title="Gate",
        rationale={},
        expires_at=datetime.utcnow() - timedelta(minutes=1),
        expiry_action="escalate",
    )
    db_session.add(dec)
    checkpoints = [dict(checkpoint) for checkpoint in run.checkpoints or []]
    checkpoints[0]["decision_id"] = dec.id
    run.checkpoints = checkpoints
    db_session.commit()

    with patch.object(gate_ttl, "_resume_paused_run") as resume:
        result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 1, result
    db_session.refresh(dec)
    db_session.refresh(run)
    assert dec.status == "proposed"
    assert dec.expires_at is None  # disarmed
    assert any(cp.get("kind") == "gate_ttl_escalated" for cp in (run.checkpoints or []))
    resume.assert_not_called()


def test_scheduler_tick_includes_gate_sweep(db_session):
    from app.services.run_engine import scheduler

    with patch.object(
        gate_ttl,
        "sweep_expired_gates",
        return_value={"status": "ok", "swept": 0},
    ) as sweep:
        with patch.object(scheduler, "_dispatch_run"):
            result = scheduler.scheduler_tick()

    assert "gates" in result
    sweep.assert_called_once()


def _delegated_gate(db, *, deadline: datetime) -> tuple[Run, Run, Decision]:
    ws = _workspace(db)
    system = _system(db, ws.id)
    parent = Run(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        system_id=system.id,
        status="waiting_subflows",
    )
    decision = Decision(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        scope="run",
        kind="hitl_approval",
        status="proposed",
        title="Delegated gate",
        expires_at=datetime.utcnow() - timedelta(minutes=1),
        expiry_action="reject",
    )
    child = Run(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        system_id=system.id,
        parent_run_id=parent.id,
        status="hitl_pending",
        delegation_key="a" * 64,
        delegation_node_id="delegate",
        delegation_branch="main",
        delegation_deadline_at=deadline,
        input_ref={
            "_delegation": {
                "parent_run_id": parent.id,
                "execution_plane": "celery",
                "deadline_at": deadline.isoformat(),
            }
        },
        checkpoints=[
            {
                "kind": "hitl_pause",
                "node_id": "approval",
                "decision_id": decision.id,
            }
        ],
    )
    decision.target_id = child.id
    parent.waiting_subflows = {
        "_meta": {
            "strategy": "all",
            "state": "waiting",
            "execution_plane": "celery",
            "wave_id": 1,
        },
        child.delegation_key: {
            "child_run_id": child.id,
            "node_id": child.delegation_node_id,
            "branch": child.delegation_branch,
            "status": "hitl_pending",
            "deadline_at": deadline.isoformat(),
            "wave_id": 1,
        },
    }
    db.add_all([parent, child, decision])
    db.commit()
    return parent, child, decision


def test_delegated_gate_ttl_uses_outbox_before_delegation_deadline(
    db_session,
    monkeypatch,
):
    _parent, child, decision = _delegated_gate(
        db_session,
        deadline=datetime.utcnow() + timedelta(hours=1),
    )
    from app.services.run_engine import dispatch_outbox

    monkeypatch.setattr(
        dispatch_outbox,
        "reconcile_dispatch_outbox",
        lambda **_kwargs: {"claimed": 0, "published": 0},
    )
    monkeypatch.setattr(
        gate_ttl,
        "_resume_paused_run",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("delegated TTL must never resume inline")
        ),
    )

    result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 1, result
    assert result["deferred_to_p4"] == 0
    db_session.expire_all()
    persisted = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert persisted.status == "rejected"
    event = db_session.query(RunDispatchOutbox).one()
    assert (event.event_type, event.run_id, event.decision_id) == (
        "subflow_hitl_resume",
        child.id,
        decision.id,
    )
    child = db_session.query(Run).filter(Run.id == child.id).one()
    assert any(
        checkpoint.get("kind") == "hitl_resume_dispatch"
        and checkpoint.get("plane") == "subflow_celery"
        for checkpoint in child.checkpoints or []
    )


def test_delegation_deadline_defers_generic_ttl_to_p4_watchdog(
    db_session,
    monkeypatch,
):
    deadline = datetime.utcnow() - timedelta(seconds=5)
    _parent, child, decision = _delegated_gate(db_session, deadline=deadline)
    monkeypatch.setattr(
        gate_ttl,
        "_resume_paused_run",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("expired delegation must never resume inline")
        ),
    )

    result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 0
    assert result["deferred_to_p4"] == 1
    db_session.expire_all()
    persisted = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert persisted.status == "proposed"
    assert persisted.expires_at is None
    assert db_session.query(RunDispatchOutbox).count() == 0
    child = db_session.query(Run).filter(Run.id == child.id).one()
    assert any(
        checkpoint.get("kind") == "gate_ttl_deferred_to_p4"
        and checkpoint.get("reason") == "delegation_deadline_reached"
        for checkpoint in child.checkpoints or []
    )


def test_expired_delegated_escalation_is_owned_by_p4(db_session, monkeypatch):
    _parent, child, decision = _delegated_gate(
        db_session,
        deadline=datetime.utcnow() - timedelta(seconds=5),
    )
    decision.expiry_action = "escalate"
    db_session.commit()
    monkeypatch.setattr(
        gate_ttl,
        "_resume_paused_run",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("expired delegated escalation belongs to P4")
        ),
    )

    result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 0
    assert result["deferred_to_p4"] == 1
    db_session.expire_all()
    persisted = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert persisted.status == "proposed"
    assert persisted.expires_at is None
    child = db_session.query(Run).filter(Run.id == child.id).one()
    assert not any(
        checkpoint.get("kind") == "gate_ttl_escalated"
        for checkpoint in child.checkpoints or []
    )


def test_malformed_parent_only_celery_claim_is_handed_to_p4(db_session, monkeypatch):
    _parent, child, decision = _delegated_gate(
        db_session,
        deadline=datetime.utcnow() + timedelta(hours=1),
    )
    child.input_ref = {"_delegation": {"execution_plane": "in_process"}}
    child.delegation_deadline_at = None
    db_session.commit()
    monkeypatch.setattr(
        gate_ttl,
        "_resume_paused_run",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("malformed delegated HITL must fail closed")
        ),
    )

    result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 0
    assert result["deferred_to_p4"] == 1
    db_session.expire_all()
    persisted = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert persisted.status == "proposed"
    assert persisted.expires_at is None
    child = db_session.query(Run).filter(Run.id == child.id).one()
    assert any(
        checkpoint.get("kind") == "gate_ttl_deferred_to_p4"
        and checkpoint.get("reason") == "invalid_delegation_contract"
        for checkpoint in child.checkpoints or []
    )


def test_gate_ttl_fails_closed_on_workspace_mismatch(db_session, monkeypatch):
    first = _workspace(db_session)
    second = _workspace(db_session)
    system = _system(db_session, second.id)
    run = _paused_run(db_session, workspace_id=second.id, system_id=system.id)
    decision = Decision(
        id=str(uuid.uuid4()),
        workspace_id=first.id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        status="proposed",
        title="Cross workspace gate",
        expires_at=datetime.utcnow() - timedelta(minutes=1),
        expiry_action="reject",
    )
    checkpoints = [dict(checkpoint) for checkpoint in run.checkpoints or []]
    checkpoints[0]["decision_id"] = decision.id
    run.checkpoints = checkpoints
    db_session.add(decision)
    db_session.commit()
    monkeypatch.setattr(
        gate_ttl,
        "_resume_paused_run",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("cross-workspace gate must never resume")
        ),
    )

    result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 0
    assert result["skipped"] == 1
    db_session.expire_all()
    persisted = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert persisted.status == "proposed"
    assert persisted.expires_at is None


def test_gate_ttl_resumes_outermost_in_process_pause(db_session, monkeypatch):
    workspace = _workspace(db_session)
    system = _system(db_session, workspace.id)
    decision = Decision(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        scope="run",
        kind="hitl_approval",
        status="proposed",
        title="Nested gate",
        expires_at=datetime.utcnow() - timedelta(minutes=1),
        expiry_action="reject",
    )
    parent = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="hitl_pending",
        checkpoints=[{"kind": "hitl_pause", "decision_id": decision.id}],
    )
    child = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        parent_run_id=parent.id,
        status="hitl_pending",
        checkpoints=[{"kind": "hitl_pause", "decision_id": decision.id}],
    )
    decision.target_id = child.id
    db_session.add_all([parent, child, decision])
    db_session.commit()
    resumed = []
    monkeypatch.setattr(
        gate_ttl,
        "_resume_paused_run",
        lambda run_id, decision_id: resumed.append((run_id, decision_id)),
    )

    result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 1
    assert resumed == [(parent.id, decision.id)]
    db_session.expire_all()
    parent = db_session.query(Run).filter(Run.id == parent.id).one()
    child = db_session.query(Run).filter(Run.id == child.id).one()
    assert any(
        checkpoint.get("kind") == "gate_ttl_expired"
        for checkpoint in parent.checkpoints or []
    )
    assert not any(
        checkpoint.get("kind") == "gate_ttl_expired"
        for checkpoint in child.checkpoints or []
    )


def test_gate_ttl_uses_run_celery_outbox(db_session, monkeypatch):
    workspace = _workspace(db_session)
    system = _system(db_session, workspace.id)
    system.settings = {"features": {"run_hitl_celery": True}}
    run = _paused_run(db_session, workspace_id=workspace.id, system_id=system.id)
    decision = Decision(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        status="proposed",
        title="Durable ordinary gate",
        expires_at=datetime.utcnow() - timedelta(minutes=1),
        expiry_action="approve",
    )
    checkpoints = [dict(checkpoint) for checkpoint in run.checkpoints or []]
    checkpoints[0]["decision_id"] = decision.id
    run.checkpoints = checkpoints
    db_session.add(decision)
    db_session.commit()
    monkeypatch.setattr(gate_ttl.settings, "database_url", "postgresql://p4-test")
    monkeypatch.setattr(gate_ttl.settings, "enable_run_hitl_celery", True)
    from app.services.run_engine import dispatch_outbox

    monkeypatch.setattr(
        dispatch_outbox,
        "reconcile_dispatch_outbox",
        lambda **_kwargs: {"claimed": 0, "published": 0},
    )
    monkeypatch.setattr(
        gate_ttl,
        "_resume_paused_run",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("run_celery must never resume inline")
        ),
    )

    result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 1
    db_session.expire_all()
    persisted = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert persisted.status == "accepted"
    event = db_session.query(RunDispatchOutbox).one()
    assert (event.event_type, event.run_id, event.decision_id) == (
        "run_hitl_resume",
        run.id,
        decision.id,
    )


def test_invalid_nondelegated_dispatch_plane_is_quarantined_locally(
    db_session,
    monkeypatch,
):
    workspace = _workspace(db_session)
    system = _system(db_session, workspace.id)
    run = _paused_run(db_session, workspace_id=workspace.id, system_id=system.id)
    decision = Decision(
        id=str(uuid.uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        status="proposed",
        title="Invalid dispatch plane",
        expires_at=datetime.utcnow() - timedelta(minutes=1),
        expiry_action="escalate",
    )
    checkpoints = [dict(checkpoint) for checkpoint in run.checkpoints or []]
    checkpoints[0]["decision_id"] = decision.id
    checkpoints.append(
        {
            "kind": "hitl_resume_dispatch",
            "decision_id": decision.id,
            "plane": "corrupt-plane",
        }
    )
    run.checkpoints = checkpoints
    db_session.add(decision)
    db_session.commit()
    monkeypatch.setattr(
        gate_ttl,
        "_resume_paused_run",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("invalid local plane must never resume")
        ),
    )

    result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 1
    assert result["gates"][0]["action"] == "quarantined"
    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).one()
    decision = db_session.query(Decision).filter(Decision.id == decision.id).one()
    assert run.status == "failed"
    assert run.error == "subflow_hitl_watchdog_invalid_state"
    assert decision.status == "rejected"
    assert decision.expires_at is not None
    assert db_session.query(RunDispatchOutbox).count() == 0
