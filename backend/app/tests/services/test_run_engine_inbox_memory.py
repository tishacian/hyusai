"""Unit tests for run inbox buffering + SystemMemory reinjection (Phase 4)."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from sqlalchemy.orm.attributes import flag_modified

from app.models.decision import Decision
from app.models.run import Run
from app.models.run_dispatch_outbox import RunDispatchOutbox
from app.models.run_inbox import RunInbox
from app.models.system import System
from app.models.system_memory import SystemMemory
from app.models.trigger_event_claim import TriggerEventClaim
from app.models.workspace import Workspace
from app.services.run_engine import inbox
from app.services.run_engine.dag import WalkerState
from app.services.run_engine.variable_pool import VariablePool


def _workspace(db) -> Workspace:
    ws = Workspace(id=str(uuid.uuid4()), name="Inbox WS", slug=f"inbox-{uuid.uuid4().hex[:6]}")
    db.add(ws)
    db.commit()
    return ws


def _system(db, workspace_id: str) -> System:
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="Inbox System",
        objective="buffer",
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "src", "kind": "source", "type": "source.webhook"},
                {"id": "gate", "kind": "hitl", "config": {"prompt": "Approve?"}},
                {"id": "snk", "kind": "sink"},
            ],
            "edges": [
                {"from": "src", "to": "gate", "kind": "control"},
                {"from": "gate", "to": "snk", "kind": "control"},
            ],
        },
        status="active",
        settings={"event_trigger": {"mode": "live"}},
    )
    db.add(system)
    db.commit()
    return system


def _paused_run(
    db, *, workspace_id: str, system_id: str, correlation_key: str | None = "tx-9"
) -> Run:
    input_ref = {"correlation_key": correlation_key} if correlation_key else {}
    run = Run(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        system_id=system_id,
        status="hitl_pending",
        trigger="webhook",
        input_ref=input_ref,
        checkpoints=[
            {
                "kind": "hitl_pause",
                "node_id": "gate",
                "correlation_key": correlation_key,
                "state": {"pool": {"run": input_ref}, "ctx": {}},
            }
        ],
    )
    db.add(run)
    db.commit()
    return run


def test_extract_correlation_key_variants():
    assert inbox.extract_correlation_key({"correlation_key": "a"}) == "a"
    assert inbox.extract_correlation_key({"correlation_id": "b"}) == "b"
    assert inbox.extract_correlation_key({"transaction_id": "c"}) == "c"
    assert inbox.extract_correlation_key({"_correlation": "d"}) == "d"
    assert inbox.extract_correlation_key({}) is None


def test_try_buffer_event_writes_inbox_and_memory(db_session):
    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    run = _paused_run(db_session, workspace_id=ws.id, system_id=system.id, correlation_key="tx-9")

    result = inbox.try_buffer_event(
        db_session,
        system_id=system.id,
        event_kind="webhook.received",
        payload={"correlation_key": "tx-9", "amount": 42},
    )
    assert result is not None
    assert result["status"] == "buffered"
    assert result["run_id"] == run.id

    rows = db_session.query(RunInbox).filter(RunInbox.run_id == run.id).all()
    assert len(rows) == 1
    assert rows[0].payload.get("amount") == 42

    mem = (
        db_session.query(SystemMemory)
        .filter(
            SystemMemory.system_id == system.id,
            SystemMemory.correlation_key == "tx-9",
        )
        .first()
    )
    assert mem is not None
    assert mem.version == 1
    assert (mem.state or {}).get("event_count") == 1
    assert (mem.state or {}).get("latest", {}).get("amount") == 42


def test_try_buffer_event_none_when_no_paused_run(db_session):
    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    result = inbox.try_buffer_event(
        db_session,
        system_id=system.id,
        event_kind="webhook.received",
        payload={"correlation_key": "orphan"},
    )
    assert result is None


def test_emit_event_buffers_instead_of_dispatch(db_session, monkeypatch):
    from app.services.run_engine import triggers

    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    run = _paused_run(db_session, workspace_id=ws.id, system_id=system.id, correlation_key="tx-9")

    monkeypatch.setattr(triggers.settings, "enable_event_triggers", True)
    dispatched = []
    monkeypatch.setattr(triggers, "_dispatch_live_run", lambda rid: dispatched.append(rid))

    results = triggers.emit_event(
        triggers.EVENT_WEBHOOK_RECEIVED,
        ws.id,
        {"correlation_key": "tx-9", "file": "a.csv"},
        db=db_session,
        system_id=system.id,
    )
    assert len(results) == 1
    assert results[0]["status"] == "buffered"
    assert results[0]["run_id"] == run.id
    assert dispatched == []
    assert db_session.query(RunInbox).filter(RunInbox.run_id == run.id).count() == 1


def test_emit_event_buffers_one_copy_on_identical_redelivery(db_session, monkeypatch):
    from app.services.run_engine import triggers

    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    run = _paused_run(db_session, workspace_id=ws.id, system_id=system.id, correlation_key="tx-9")
    payload = {"correlation_key": "tx-9", "file": "same.csv"}
    monkeypatch.setattr(triggers.settings, "enable_event_triggers", True)

    first = triggers.emit_event(
        triggers.EVENT_WEBHOOK_RECEIVED,
        ws.id,
        payload,
        db=db_session,
        system_id=system.id,
    )
    second = triggers.emit_event(
        triggers.EVENT_WEBHOOK_RECEIVED,
        ws.id,
        payload,
        db=db_session,
        system_id=system.id,
    )

    assert first[0]["status"] == "buffered"
    assert second[0]["status"] == "duplicate"
    assert second[0]["claim_outcome"] == "inbox"
    assert second[0]["inbox_id"] == first[0]["inbox_id"]
    assert db_session.query(RunInbox).filter(RunInbox.run_id == run.id).count() == 1
    assert db_session.query(TriggerEventClaim).filter_by(system_id=system.id).count() == 1
    memory = db_session.query(SystemMemory).filter_by(system_id=system.id).one()
    assert memory.state["event_count"] == 1


def test_buffering_respects_caller_transaction_rollback(db_session, monkeypatch):
    from app.services.run_engine import triggers

    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    run = _paused_run(db_session, workspace_id=ws.id, system_id=system.id)
    original_objective = system.objective
    system.objective = "must rollback with caller"
    monkeypatch.setattr(triggers.settings, "enable_event_triggers", True)

    result = triggers.emit_event(
        triggers.EVENT_WEBHOOK_RECEIVED,
        ws.id,
        {"correlation_key": "tx-9", "file": "rollback.csv"},
        db=db_session,
        system_id=system.id,
    )
    assert result[0]["status"] == "buffered"
    db_session.rollback()

    assert db_session.get(System, system.id).objective == original_objective
    assert db_session.query(RunInbox).filter(RunInbox.run_id == run.id).count() == 0
    assert db_session.query(TriggerEventClaim).filter_by(system_id=system.id).count() == 0


def test_inbox_failure_is_fail_closed_and_preserves_caller_transaction(
    db_session,
    monkeypatch,
):
    from app.services.run_engine import triggers

    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    run = _paused_run(db_session, workspace_id=ws.id, system_id=system.id)
    original_objective = system.objective
    system.objective = "caller mutation must remain pending"
    monkeypatch.setattr(triggers.settings, "enable_event_triggers", True)
    real_try_buffer_event = inbox.try_buffer_event

    def fail_after_partial_buffer(*args, **kwargs):
        buffered = real_try_buffer_event(*args, **kwargs)
        assert buffered is not None
        raise RuntimeError("synthetic inbox failure")

    monkeypatch.setattr(inbox, "try_buffer_event", fail_after_partial_buffer)

    result = triggers.emit_event(
        triggers.EVENT_WEBHOOK_RECEIVED,
        ws.id,
        {"correlation_key": "tx-9", "file": "fail-closed.csv"},
        db=db_session,
        system_id=system.id,
    )

    assert result[0]["status"] == "rejected"
    assert result[0]["reason"] == "inbox_buffer_failed"
    assert db_session.query(Run).filter_by(system_id=system.id).count() == 1
    assert db_session.query(RunInbox).filter_by(run_id=run.id).count() == 0
    assert db_session.query(SystemMemory).filter_by(system_id=system.id).count() == 0
    assert db_session.query(TriggerEventClaim).filter_by(system_id=system.id).count() == 0
    assert db_session.query(RunDispatchOutbox).filter_by(run_id=run.id).count() == 0

    db_session.flush()
    assert system.objective == "caller mutation must remain pending"
    db_session.rollback()
    assert db_session.get(System, system.id).objective == original_objective


def test_reinject_memory_into_state_on_resume(db_session):
    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    run = _paused_run(db_session, workspace_id=ws.id, system_id=system.id, correlation_key="tx-9")

    inbox.buffer_event_for_paused_run(
        db_session,
        run,
        event_kind="sftp.file_arrived",
        payload={"correlation_key": "tx-9", "path": "/in/x.csv"},
        correlation_key="tx-9",
    )
    # Second event bumps version.
    inbox.buffer_event_for_paused_run(
        db_session,
        run,
        event_kind="sftp.file_arrived",
        payload={"correlation_key": "tx-9", "path": "/in/y.csv"},
        correlation_key="tx-9",
    )

    state = WalkerState()
    state.pool = VariablePool()
    payload = inbox.reinject_memory_into_state(db_session, run, state)

    assert payload is not None
    assert payload["version"] == 2
    assert payload["event_count"] == 2
    assert state.pool.get(["memory", "version"]) == 2
    assert state.pool.get(["memory", "latest", "path"]) == "/in/y.csv"
    assert state.ctx["memory"]["correlation_key"] == "tx-9"


def test_resume_run_dag_calls_memory_reinject(db_session, monkeypatch):
    """resume_run_dag must call reinject before walking (memory.* contract)."""
    import asyncio

    from app.services.run_engine import dag as dag_mod

    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    run = _paused_run(db_session, workspace_id=ws.id, system_id=system.id, correlation_key="tx-9")
    dec = Decision(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        status="accepted",
        title="Gate",
        rationale={"node_id": "gate"},
    )
    db_session.add(dec)
    # Rebuild the checkpoint list with fresh dicts: in-place mutation of a
    # JSON column is invisible to SQLAlchemy's change detection and the
    # decision_id would never reach the DB (resume would then reject the
    # operator decision as a mismatch).
    cps = [dict(cp) for cp in (run.checkpoints or [])]
    cps[0] = {
        **cps[0],
        "decision_id": dec.id,
        "state": {
            "node_outputs": {},
            "done": ["src", "gate"],
            "pending_counts": {"snk": 0},
            "dead_edges": [],
            "ctx": {},
            "pool": {"run": {"correlation_key": "tx-9"}},
            "subflow_children": {},
        },
    }
    run.checkpoints = cps
    flag_modified(run, "checkpoints")
    run.flow_snapshot = system.flow_definition
    db_session.commit()

    called = {"n": 0}

    def fake_reinject(db, run_obj, state):
        called["n"] += 1
        state.pool.set_namespace("memory", {"version": 7, "event_count": 3})
        state.ctx["memory"] = {"version": 7}
        return {"version": 7, "event_count": 3}

    captured = {}

    async def fake_walk(db, run_obj, graph, state, **kwargs):
        captured["memory"] = state.pool.get(["memory"])
        return {"id": run_obj.id, "status": "completed"}

    gate = MagicMock(allowed=True, would_block=False, mode="off", violations=[])
    monkeypatch.setattr(dag_mod, "reinject_memory_into_state", fake_reinject, raising=False)
    # Patch at the import site used inside resume_run_dag.
    monkeypatch.setattr(
        "app.services.run_engine.inbox.reinject_memory_into_state",
        fake_reinject,
    )
    monkeypatch.setattr(dag_mod, "_walk", fake_walk)
    monkeypatch.setattr(dag_mod, "_evaluate_run_capability", lambda *a, **k: gate)
    monkeypatch.setattr(dag_mod, "_load_control_policy", lambda *a, **k: None)
    monkeypatch.setattr(dag_mod, "_load_adaptive_policy", lambda *a, **k: None)

    class _SessionCtx:
        def __call__(self):
            return db_session

    # Avoid closing the shared pytest session in resume_run_dag's finally.
    original_close = db_session.close
    db_session.close = lambda: None  # type: ignore[method-assign]
    monkeypatch.setattr(dag_mod, "SessionLocal", _SessionCtx())
    try:
        result = asyncio.run(dag_mod.resume_run_dag(run.id, decision_id=dec.id))
    finally:
        db_session.close = original_close  # type: ignore[method-assign]

    assert result.get("status") == "completed"
    assert called["n"] == 1
    assert captured["memory"]["version"] == 7
