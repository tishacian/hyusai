import sys
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.run_engine import dag, engine
from app.services.run_engine.subflow_orchestration import (
    _cancel_losers,
    cancel_waiting_children,
    delegation_acl_result,
    resolve_waiting,
    resume_parent_for_child,
    retry_ambiguous_dispatches,
    validate_contract,
)


def test_delegation_key_is_stable_and_branch_scoped():
    first = dag.delegation_key("parent", "node", 3, "left")
    assert first == dag.delegation_key("parent", "node", 3, "left")
    assert first != dag.delegation_key("parent", "node", 3, "right")
    assert len(first) == 64


def test_subflow_celery_requires_both_gates(monkeypatch):
    system = SimpleNamespace(settings={"features": {"subflow_celery": True}})
    monkeypatch.setattr(dag.settings, "enable_subflow_celery", False)
    assert dag.subflow_celery_enabled(system) is False
    monkeypatch.setattr(dag.settings, "enable_subflow_celery", True)
    assert dag.subflow_celery_enabled(system) is True
    system.settings = {"features": {}}
    assert dag.subflow_celery_enabled(system) is False


def test_ambiguous_dispatch_never_falls_back_in_process(monkeypatch):
    called = False

    class Task:
        @staticmethod
        def delay(_child_id):
            raise OSError("broker acknowledgement lost")

    monkeypatch.setitem(sys.modules, "app.workers.tasks", SimpleNamespace(subflow_run=Task()))

    def forbidden(_child_id):
        nonlocal called
        called = True

    monkeypatch.setattr(engine, "run_subflow_child", forbidden)
    with pytest.raises(RuntimeError, match="ambiguous subflow dispatch"):
        engine.schedule_subflow_run("child-1")
    assert called is False


def test_join_strategies_are_deterministic():
    entries = {
        "_meta": {"strategy": "any"},
        "b": {"child_run_id": "b", "status": "completed", "completed_at": "2026-01-02"},
        "a": {"child_run_id": "a", "status": "completed", "completed_at": "2026-01-01"},
        "c": {"child_run_id": "c", "status": "running"},
    }
    assert resolve_waiting(entries) == (True, "a")
    entries["_meta"]["strategy"] = "all"
    assert resolve_waiting(entries) == (False, None)
    entries["_meta"]["strategy"] = "race"
    assert resolve_waiting(entries) == (True, "a")


def test_typed_delegation_acl_enforces_target_branch_and_input_contract():
    from app.services.membrane.spec import MembraneSpec

    spec = MembraneSpec.from_dict(
        {
            "version": 2,
            "enforcement_mode": "enforce",
            "capabilities": {
                "allowed_delegations": [
                    {
                        "system_id": "target",
                        "branches": ["legal"],
                        "input_contract": {
                            "type": "object",
                            "required": ["query"],
                            "properties": {"query": {"type": "string"}},
                        },
                        "output_contract": {"answer": "string"},
                    }
                ]
            },
        }
    )
    assert delegation_acl_result(
        spec, target_system_id="target", branch="legal", input_payload={"query": "q"}
    ) == (True, None, {"answer": "string"}, True)
    allowed, reason, _, enforced = delegation_acl_result(
        spec, target_system_id="target", branch="finance", input_payload={"query": "q"}
    )
    assert (allowed, reason, enforced) == (False, "branch_not_allowed", True)
    allowed, reason, _, _ = delegation_acl_result(
        spec, target_system_id="target", branch="legal", input_payload={"query": 7}
    )
    assert (allowed, reason) == (False, "input_contract_mismatch")
    assert validate_contract({"answer": "ok"}, {"answer": "string"}) is True
    assert validate_contract({"answer": 4}, {"answer": "string"}) is False
    assert validate_contract({"answer": "ok"}, {"answer": "strng"}) is False
    empty = MembraneSpec.from_dict(
        {"version": 2, "enforcement_mode": "enforce", "capabilities": {"allowed_delegations": []}}
    )
    assert delegation_acl_result(
        empty, target_system_id="target", branch="legal", input_payload={}
    )[:2] == (False, "target_not_allowed")
    shadow_payload = spec.to_dict()
    shadow_payload["enforcement_mode"] = "shadow"
    shadow = MembraneSpec.from_dict(shadow_payload)
    assert delegation_acl_result(
        shadow, target_system_id="target", branch="finance", input_payload={"query": "q"}
    )[:2] == (True, "branch_not_allowed")


def test_invalid_v2_enforce_delegation_is_fail_closed():
    from app.models.system import System

    control = SimpleNamespace(
        extra={
            "membrane_spec": {
                "version": 2,
                "enforcement_mode": "enforce",
                "capabilities": {"allowed_delegations": ["legacy-token"]},
            }
        }
    )
    allowed, reason, _, enforced, error = dag._delegation_acl(
        control, System(id="target", name="T", objective=""), "default", {}
    )
    assert (allowed, reason, enforced) == (False, "invalid_membrane_spec", True)
    assert error


def test_ambiguous_retry_reuses_same_child_id(db_session, monkeypatch):
    from app.models.run import Run

    parent = Run(id=str(uuid4()), status="waiting_subflows")
    child = Run(
        id=str(uuid4()), parent_run_id=parent.id, status="pending",
        delegation_key="a" * 64,
    )
    parent.waiting_subflows = {
        "_meta": {"strategy": "all"},
        child.delegation_key: {
            "child_run_id": child.id,
            "dispatch_state": "ambiguous",
            "status": "pending",
        },
    }
    db_session.add_all([parent, child])
    db_session.commit()
    dispatched = []
    monkeypatch.setattr(engine, "schedule_subflow_run", lambda child_id: dispatched.append(child_id) or "task-1")
    assert retry_ambiguous_dispatches(parent.id) == {child.delegation_key: "dispatched"}
    assert dispatched == [child.id]
    assert db_session.query(Run).filter(Run.parent_run_id == parent.id).count() == 1


def test_race_cancels_non_terminal_losers(db_session, monkeypatch):
    from app.models.run import Run

    winner = Run(id=str(uuid4()), status="completed", completed_at=datetime.utcnow())
    loser = Run(id=str(uuid4()), status="running", celery_task_id="task-loser")
    db_session.add_all([winner, loser])
    db_session.commit()
    waiting = {
        "_meta": {"strategy": "race"},
        "winner": {"child_run_id": winner.id, "status": "completed"},
        "loser": {"child_run_id": loser.id, "status": "running"},
    }
    _cancel_losers(db_session, waiting, winner.id)
    db_session.commit()
    db_session.refresh(loser)
    assert loser.status == "cancelled"
    assert loser.error == "subflow_race_lost"


def test_parent_cancellation_propagates_to_same_children(db_session):
    from app.models.run import Run

    parent = Run(id=str(uuid4()), status="waiting_subflows")
    child = Run(id=str(uuid4()), parent_run_id=parent.id, status="running", delegation_key="c" * 64)
    parent.waiting_subflows = {
        "_meta": {"strategy": "all"},
        child.delegation_key: {"child_run_id": child.id, "status": "running"},
    }
    db_session.add_all([parent, child])
    db_session.commit()
    assert cancel_waiting_children(parent.id, reason="parent_cancelled") == 1
    db_session.refresh(child)
    assert child.status == "cancelled"
    assert child.error == "parent_cancelled"
    assert db_session.query(Run).filter(Run.parent_run_id == parent.id).count() == 1


def test_late_worker_completion_cannot_overwrite_coordinator_cancellation(db_session):
    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.models.system import System

    system = System(id=str(uuid4()), name="Cancelled target", objective="test")
    run = Run(id=str(uuid4()), system_id=system.id, status="running")
    db_session.add_all([system, run])
    db_session.commit()
    with SessionLocal() as other:
        cancelled = other.query(Run).filter(Run.id == run.id).one()
        cancelled.status = "cancelled"
        cancelled.error = "subflow_race_lost"
        cancelled.completed_at = datetime.utcnow()
        other.commit()
    summary = engine._finalize_run(
        db_session,
        run,
        system=system,
        capability=None,
        control=None,
        invocations=[],
        duration_ms=1,
        last_output={"should_not_publish": True},
    )
    db_session.refresh(run)
    assert summary["status"] == "cancelled"
    assert run.status == "cancelled"
    assert run.output_ref == {}


def test_completed_child_payload_is_republished_through_normal_settlement(db_session):
    from app.models.run import Run

    child = Run(
        id=str(uuid4()),
        status="completed",
        output_ref={"answer": "branch-a"},
        input_ref={
            "_delegation": {
                "output_contract": {"answer": "string"},
                "contract_enforced": True,
            }
        },
    )
    db_session.add(child)
    db_session.commit()
    graph = dag.DagGraph.from_flow_definition(
        {"schema_version": 3, "nodes": [{"id": "delegate-a", "kind": "subflow"}], "edges": []}
    )
    state = dag.WalkerState(pending_counts={"delegate-a": 0})
    outcome = dag._settle_subflow_output(db_session, state, child.id, "target")
    dag._settle_node(graph, state, "delegate-a", outcome)
    assert state.node_outputs["delegate-a"]["answer"] == "branch-a"
    assert state.pool.get({"node_id": "delegate-a", "path": ["answer"]}) == "branch-a"


def test_output_contract_mismatch_is_failed_before_parent_claim(db_session):
    from app.models.run import Run
    from app.services.run_engine.subflow_orchestration import _refresh_entries

    child = Run(
        id=str(uuid4()), status="completed", output_ref={"answer": 7},
        input_ref={"_delegation": {"output_contract": {"answer": "string"}, "contract_enforced": True}},
    )
    db_session.add(child)
    db_session.commit()
    waiting = {"_meta": {"strategy": "all"}, "edge": {"child_run_id": child.id}}
    refreshed = _refresh_entries(db_session, waiting)
    db_session.commit()
    db_session.refresh(child)
    assert refreshed["edge"]["status"] == "failed"
    assert child.status == "failed"
    assert child.error == "delegation_output_contract_mismatch"


@pytest.mark.asyncio
async def test_parent_resume_claim_is_idempotent_and_child_hitl_does_not_duplicate(
    db_session, monkeypatch
):
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace
    from app.services.run_engine import dag as dag_module

    workspace = Workspace(id=str(uuid4()), name="P4", slug=f"p4-{uuid4()}")
    system = System(
        id=str(uuid4()), workspace_id=workspace.id, name="Parent", objective="test",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
    )
    parent = Run(
        id=str(uuid4()), workspace_id=workspace.id, system_id=system.id,
        status="waiting_subflows",
        checkpoints=[{"kind": "subflow_wait", "state": {}}],
    )
    child = Run(
        id=str(uuid4()), workspace_id=workspace.id, system_id=system.id,
        parent_run_id=parent.id, status="hitl_pending", delegation_key="d" * 64,
    )
    parent.waiting_subflows = {
        "_meta": {"strategy": "all", "state": "waiting"},
        child.delegation_key: {"child_run_id": child.id, "status": "pending"},
    }
    db_session.add_all([workspace, system, parent, child])
    db_session.commit()

    calls = 0
    async def fake_walk(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"id": parent.id, "status": "completed"}
    monkeypatch.setattr(dag_module, "_walk", fake_walk)

    waiting = await resume_parent_for_child(child.id)
    assert waiting["status"] == "waiting_hitl"
    assert calls == 0
    child.status = "completed"
    child.completed_at = datetime.utcnow()
    db_session.commit()
    first = await resume_parent_for_child(child.id)
    second = await resume_parent_for_child(child.id)
    assert first["status"] == "completed"
    assert second["status"] == "already_claimed"
    assert calls == 1


@pytest.mark.asyncio
async def test_child_timeout_failure_is_propagated_to_parent(db_session):
    from app.models.run import Run

    parent = Run(
        id=str(uuid4()), status="waiting_subflows",
        checkpoints=[{"kind": "subflow_wait", "state": {}}],
    )
    child = Run(
        id=str(uuid4()), parent_run_id=parent.id, status="failed",
        error="subflow_worker_failed:SoftTimeLimitExceeded", completed_at=datetime.utcnow(),
        delegation_key="f" * 64,
    )
    parent.waiting_subflows = {
        "_meta": {"strategy": "all", "state": "waiting"},
        child.delegation_key: {"child_run_id": child.id, "node_id": "delegate", "status": "running"},
    }
    db_session.add_all([parent, child])
    db_session.commit()
    result = await resume_parent_for_child(child.id)
    db_session.refresh(parent)
    assert result["status"] == "failed"
    assert parent.status == "failed"
    assert parent.output_ref["subflows"]["delegate"]["error"].startswith("subflow_worker_failed")
    assert db_session.query(Run).filter(Run.parent_run_id == parent.id).count() == 1
