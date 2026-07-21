"""Unit tests for HITL / membrane gate TTL sweep (orchestration Phase 4)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from app.models.decision import Decision
from app.models.run import Run
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
    cps = list(run.checkpoints or [])
    cps[0]["decision_id"] = dec.id
    run.checkpoints = cps
    db_session.commit()

    with patch.object(gate_ttl, "_resume_paused_run") as resume:
        result = gate_ttl.sweep_expired_gates()

    assert result["status"] == "ok"
    assert result["swept"] == 1
    db_session.refresh(dec)
    assert dec.status == "rejected"
    assert any(g["action"] == "reject" for g in result["gates"])
    resume.assert_called_once_with(run.id, dec.id)


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
    db_session.commit()

    with patch.object(gate_ttl, "_resume_paused_run") as resume:
        result = gate_ttl.sweep_expired_gates()

    assert result["swept"] == 1
    db_session.refresh(dec)
    db_session.refresh(run)
    assert dec.status == "proposed"
    assert dec.expires_at is None  # disarmed
    assert any(cp.get("kind") == "gate_ttl_escalated" for cp in (run.checkpoints or []))
    resume.assert_not_called()


def test_scheduler_tick_includes_gate_sweep(db_session):
    from app.services.run_engine import scheduler

    with patch.object(gate_ttl, "sweep_expired_gates", return_value={"status": "ok", "swept": 0}) as sweep:
        with patch.object(scheduler, "_dispatch_run"):
            result = scheduler.scheduler_tick()

    assert "gates" in result
    sweep.assert_called_once()
