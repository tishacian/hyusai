import sys
from datetime import datetime, timedelta
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


def test_dispatch_reuses_persisted_absolute_deadline(db_session, monkeypatch):
    from app.models.run import Run

    child = Run(
        id=str(uuid4()),
        status="pending",
        input_ref={
            "_delegation": {
                "deadline_at": (datetime.utcnow() + timedelta(seconds=3)).isoformat(),
            }
        },
    )
    db_session.add(child)
    db_session.commit()
    published = {}

    class Result:
        id = "deadline-task"

    class Task:
        @staticmethod
        def delay(_child_id):
            raise AssertionError("deadline dispatch must use apply_async")

        @staticmethod
        def apply_async(*, args, task_id, soft_time_limit, time_limit):
            published.update(
                args=args,
                task_id=task_id,
                soft_time_limit=soft_time_limit,
                time_limit=time_limit,
            )
            return Result()

    monkeypatch.setitem(sys.modules, "app.workers.tasks", SimpleNamespace(subflow_run=Task()))
    assert engine.schedule_subflow_run(child.id, task_id="deadline-task") == "deadline-task"
    assert published["args"] == [child.id]
    assert published["task_id"] == "deadline-task"
    assert 1 <= published["soft_time_limit"] <= 3
    assert published["time_limit"] == published["soft_time_limit"] + 5


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


@pytest.mark.parametrize("coerced_wave", [True, 1.0, "1"])
def test_active_wave_never_uses_python_scalar_coercion(coerced_wave):
    waiting = {
        "_meta": {"strategy": "all", "wave_id": 1},
        "coerced": {
            "child_run_id": "coerced",
            "status": "completed",
            "wave_id": coerced_wave,
        },
    }

    assert resolve_waiting(waiting) == (False, None)


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
    assert validate_contract(
        {"answer": "ok"},
        {"type": "object", "properties": {"answer": 7}},
    ) is False
    assert validate_contract(
        {"answer": "ok"},
        {"type": "object", "properties": {"answer": {"typ": "string"}}},
    ) is False
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
    from app.models.run_dispatch_outbox import RunDispatchOutbox
    from app.models.workspace import Workspace

    workspace = Workspace(id=str(uuid4()), slug=f"retry-{uuid4()}", name="Retry")
    parent = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        status="waiting_subflows",
    )
    child = Run(
        id=str(uuid4()), workspace_id=workspace.id, parent_run_id=parent.id, status="pending",
        delegation_key="a" * 64,
        delegation_node_id="delegate",
        delegation_branch="main",
        input_ref={
            "_delegation": {
                "parent_run_id": parent.id,
                "execution_plane": "celery",
            }
        },
    )
    parent.waiting_subflows = {
        "_meta": {
            "strategy": "all",
            "state": "waiting",
            "execution_plane": "celery",
            "wave_id": 1,
        },
        child.delegation_key: {
            "child_run_id": child.id,
            "dispatch_state": "ambiguous",
            "status": "pending",
            "node_id": "delegate",
            "branch": "main",
            "wave_id": 1,
        },
    }
    db_session.add_all([workspace, parent, child])
    db_session.commit()

    class Result:
        def __init__(self, task_id):
            self.id = task_id

    published = []

    def send_task(_name, *, args, kwargs, **options):
        published.append((args, kwargs, options))
        return Result(options["task_id"])

    monkeypatch.setattr("app.workers.celery_app.celery_app.send_task", send_task)
    assert retry_ambiguous_dispatches(parent.id) == {child.delegation_key: "dispatched"}
    assert published[0][0] == [child.id]
    assert published[0][1] == {}
    assert db_session.query(Run).filter(Run.parent_run_id == parent.id).count() == 1
    assert db_session.query(RunDispatchOutbox).filter_by(state="published").count() == 1


def test_race_cancels_non_terminal_losers(db_session, monkeypatch):
    from app.models.run import Run

    parent = Run(id=str(uuid4()), status="waiting_subflows")
    winner = Run(
        id=str(uuid4()), parent_run_id=parent.id, delegation_key="1" * 64,
        status="completed", completed_at=datetime.utcnow(),
    )
    loser = Run(
        id=str(uuid4()), parent_run_id=parent.id, delegation_key="2" * 64,
        status="running", celery_task_id="task-loser",
    )
    db_session.add_all([parent, winner, loser])
    db_session.commit()
    waiting = {
        "_meta": {"strategy": "race"},
        winner.delegation_key: {"child_run_id": winner.id, "status": "completed"},
        loser.delegation_key: {"child_run_id": loser.id, "status": "running"},
    }
    _cancel_losers(db_session, parent, waiting, winner.id)
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


def test_late_hitl_pause_cannot_resurrect_coordinator_cancellation(db_session):
    from app.db.base import SessionLocal
    from app.models.run import Run

    run = Run(id=str(uuid4()), status="running")
    db_session.add(run)
    db_session.commit()
    with SessionLocal() as other:
        cancelled = other.query(Run).filter(Run.id == run.id).one()
        cancelled.status = "cancelled"
        cancelled.error = "subflow_any_join_satisfied"
        cancelled.completed_at = datetime.utcnow()
        other.commit()

    result = dag._emit_hitl_pause(
        db_session,
        run,
        dag.WalkerState(start_monotonic=0.0),
        {
            "node_id": "approval",
            "decision_id": str(uuid4()),
            "prompt": "must not be published",
        },
    )

    db_session.refresh(run)
    assert result == {
        "id": run.id,
        "status": "cancelled",
        "error": "subflow_any_join_satisfied",
    }
    assert run.status == "cancelled"
    assert not any(cp.get("kind") == "hitl_pause" for cp in run.checkpoints or [])


@pytest.mark.parametrize("pause_kind", ["hitl", "debug"])
def test_pause_checkpoint_and_status_use_one_commit(db_session, monkeypatch, pause_kind):
    from app.models.run import Run

    run = Run(id=str(uuid4()), status="running", checkpoints=[])
    db_session.add(run)
    db_session.commit()
    commits = 0
    original_commit = db_session.commit

    def counted_commit():
        nonlocal commits
        commits += 1
        return original_commit()

    monkeypatch.setattr(db_session, "commit", counted_commit)
    state = dag.WalkerState(start_monotonic=0.0)
    if pause_kind == "hitl":
        result = dag._emit_hitl_pause(
            db_session,
            run,
            state,
            {
                "node_id": "approval",
                "decision_id": str(uuid4()),
                "prompt": "approve",
            },
        )
        expected_status = "hitl_pending"
        checkpoint_kind = "hitl_pause"
    else:
        result = dag._emit_debug_pause(db_session, run, state, "inspect")
        expected_status = "debug_pending"
        checkpoint_kind = "debug_pause"

    db_session.refresh(run)
    assert commits == 1
    assert result["status"] == expected_status
    assert run.status == expected_status
    assert (run.checkpoints or [])[-1]["kind"] == checkpoint_kind


@pytest.mark.asyncio
async def test_debug_stop_persists_canonical_cancellation(db_session):
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace

    workspace = Workspace(id=str(uuid4()), name="Debug stop", slug=f"debug-stop-{uuid4()}")
    db_session.add(workspace)
    db_session.flush()
    flow = {
        "schema_version": 3,
        "nodes": [{"id": "task", "kind": "task", "config": {}}],
        "edges": [],
    }
    system = System(
        id=str(uuid4()), workspace_id=workspace.id, name="Debug", objective="test",
        flow_definition=flow,
    )
    db_session.add(system)
    db_session.flush()
    run = Run(
        id=str(uuid4()), workspace_id=workspace.id, system_id=system.id,
        status="debug_pending", flow_snapshot=flow,
        checkpoints=[{
            "kind": "debug_pause",
            "node_id": "task",
            "state": {"pending_counts": {"task": 0}},
        }],
    )
    db_session.add(run)
    db_session.commit()

    result = await dag.resume_run_dag_debug(run.id, action="stop")

    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert result == {
        "id": run.id,
        "status": "cancelled",
        "error": "debugger_stopped",
    }
    assert persisted.status == "cancelled"
    assert persisted.error == "debugger_stopped"
    assert (persisted.checkpoints or [])[-1]["kind"] == "run_end"


def test_subflow_child_fails_closed_on_cross_workspace_system(db_session):
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace

    left = Workspace(id=str(uuid4()), name="Left", slug=f"left-{uuid4()}")
    right = Workspace(id=str(uuid4()), name="Right", slug=f"right-{uuid4()}")
    db_session.add_all([left, right])
    db_session.flush()
    foreign_system = System(
        id=str(uuid4()), workspace_id=right.id, name="Foreign", objective="test",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
    )
    db_session.add(foreign_system)
    db_session.flush()
    child = Run(
        id=str(uuid4()), workspace_id=left.id, system_id=foreign_system.id,
        status="pending",
    )
    db_session.add(child)
    db_session.commit()

    result = engine.run_subflow_child(child.id)

    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == child.id).one()
    assert result == {
        "id": child.id,
        "status": "failed",
        "error": "delegated_system_scope_mismatch",
    }
    assert persisted.status == "failed"
    assert persisted.error == "delegated_system_scope_mismatch"


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


def test_enforced_output_contract_quarantines_nonconforming_payload(db_session):
    from app.models.run import Run

    child = Run(
        id=str(uuid4()),
        status="completed",
        output_ref={"secret": "must-not-publish"},
        input_ref={
            "_delegation": {
                "output_contract": {"answer": "string"},
                "contract_enforced": True,
            }
        },
    )
    db_session.add(child)
    db_session.commit()

    outcome = dag._settle_subflow_output(
        db_session,
        dag.WalkerState(),
        child.id,
        "target",
    )

    db_session.refresh(child)
    assert child.status == "failed"
    assert child.output_ref == {}
    assert "secret" not in outcome["output"]
    assert outcome["output"]["_error"] == "delegation_output_contract_mismatch"


@pytest.mark.asyncio
async def test_resume_never_crosses_a_proposed_hitl_boundary(db_session):
    from app.models.decision import Decision
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace

    workspace = Workspace(
        id=str(uuid4()),
        name="P4 HITL boundary",
        slug=f"p4-hitl-{uuid4()}",
    )
    db_session.add(workspace)
    db_session.flush()
    flow = {
        "schema_version": 3,
        "nodes": [{"id": "approval", "kind": "hitl", "config": {}}],
        "edges": [],
    }
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="HITL",
        objective="test",
        flow_definition=flow,
    )
    db_session.add(system)
    db_session.flush()
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="hitl_pending",
        flow_snapshot=flow,
    )
    decision = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        status="proposed",
        title="Approval",
    )
    run.checkpoints = [
        {
            "kind": "hitl_pause",
            "node_id": "approval",
            "decision_id": decision.id,
            "state": {},
        }
    ]
    db_session.add_all([run, decision])
    db_session.commit()

    summary = await dag.resume_run_dag(run.id)

    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == run.id).one()
    assert summary == {
        "id": run.id,
        "status": "hitl_pending",
        "awaiting_decision": decision.id,
    }
    assert persisted.status == "hitl_pending"
    assert not any(
        checkpoint.get("kind") == "hitl_resume"
        for checkpoint in persisted.checkpoints or []
        if isinstance(checkpoint, dict)
    )


def test_output_contract_mismatch_is_failed_before_parent_claim(db_session):
    from app.models.run import Run
    from app.services.run_engine.subflow_orchestration import _refresh_entries

    parent = Run(id=str(uuid4()), status="waiting_subflows")
    child = Run(
        id=str(uuid4()), parent_run_id=parent.id, delegation_key="e" * 64,
        status="completed", output_ref={"answer": 7},
        input_ref={"_delegation": {"output_contract": {"answer": "string"}, "contract_enforced": True}},
    )
    db_session.add_all([parent, child])
    db_session.commit()
    waiting = {
        "_meta": {"strategy": "all"},
        child.delegation_key: {"child_run_id": child.id},
    }
    refreshed = _refresh_entries(db_session, parent, waiting)
    db_session.commit()
    db_session.refresh(child)
    assert refreshed[child.delegation_key]["status"] == "failed"
    assert child.status == "failed"
    assert child.error == "delegation_output_contract_mismatch"
    assert child.output_ref == {}


@pytest.mark.asyncio
async def test_parent_resume_claim_is_idempotent_and_child_hitl_does_not_duplicate(
    db_session, monkeypatch
):
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace
    from app.services.run_engine import dag as dag_module

    workspace = Workspace(id=str(uuid4()), name="P4", slug=f"p4-{uuid4()}")
    db_session.add(workspace)
    db_session.flush()
    system = System(
        id=str(uuid4()), workspace_id=workspace.id, name="Parent", objective="test",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
    )
    db_session.add(system)
    db_session.flush()
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
    async def fake_walk(db, resumed_parent, *args, **kwargs):
        nonlocal calls
        calls += 1
        resumed_parent.status = "completed"
        resumed_parent.completed_at = datetime.utcnow()
        db.commit()
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
    assert second["status"] == "completed"
    assert calls == 1


@pytest.mark.parametrize("strategy", ["any", "race"])
@pytest.mark.asyncio
async def test_resolved_join_materializes_winner_without_replaying_hitl_loser(
    db_session, monkeypatch, strategy
):
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace
    from app.services.run_engine import dag as dag_module

    workspace = Workspace(id=str(uuid4()), name="P4 join", slug=f"p4-join-{uuid4()}")
    winner_system = System(
        id=str(uuid4()), workspace_id=workspace.id, name="Winner", objective="test",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
    )
    loser_system = System(
        id=str(uuid4()), workspace_id=workspace.id, name="Loser", objective="test",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
    )
    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "winner", "kind": "subflow", "config": {"system_id": winner_system.id}},
            {"id": "loser", "kind": "subflow", "config": {"system_id": loser_system.id}},
        ],
        "edges": [],
    }
    parent_system = System(
        id=str(uuid4()), workspace_id=workspace.id, name="Parent", objective="test",
        flow_definition=flow,
    )
    parent = Run(
        id=str(uuid4()), workspace_id=workspace.id, system_id=parent_system.id,
        status="waiting_subflows", flow_snapshot=flow,
        checkpoints=[{
            "kind": "subflow_wait",
            "state": {"pending_counts": {"winner": 0, "loser": 0}},
        }],
    )
    winner = Run(
        id=str(uuid4()), workspace_id=workspace.id, system_id=winner_system.id,
        parent_run_id=parent.id, delegation_key="a" * 64,
        delegation_node_id="winner", status="completed",
        completed_at=datetime.utcnow(), output_ref={"answer": "winner"},
    )
    loser = Run(
        id=str(uuid4()), workspace_id=workspace.id, system_id=loser_system.id,
        parent_run_id=parent.id, delegation_key="b" * 64,
        delegation_node_id="loser", status="hitl_pending",
    )
    parent.waiting_subflows = {
        "_meta": {"strategy": strategy, "state": "waiting", "wave_id": 1},
        winner.delegation_key: {
            "child_run_id": winner.id, "node_id": "winner",
            "status": "completed", "wave_id": 1,
        },
        loser.delegation_key: {
            "child_run_id": loser.id, "node_id": "loser",
            "status": "hitl_pending", "wave_id": 1,
        },
    }
    db_session.add(workspace)
    db_session.flush()
    db_session.add_all([winner_system, loser_system, parent_system])
    db_session.flush()
    db_session.add_all([parent, winner, loser])
    db_session.commit()

    captured = {}

    async def fake_walk(_db, _parent, _graph, state, **_kwargs):
        captured["done"] = set(state.done)
        captured["winner"] = dict(state.node_outputs.get("winner") or {})
        captured["loser"] = dict(state.node_outputs.get("loser") or {})
        _parent.status = "completed"
        _db.commit()
        return {"id": _parent.id, "status": "completed"}

    monkeypatch.setattr(dag_module, "_walk", fake_walk)
    result = await resume_parent_for_child(winner.id)

    db_session.expire_all()
    persisted_loser = db_session.query(Run).filter(Run.id == loser.id).one()
    assert result["status"] == "completed"
    assert captured["done"] == {"winner", "loser"}
    assert captured["winner"]["answer"] == "winner"
    assert captured["loser"] == {}
    assert persisted_loser.status == "cancelled"
    assert persisted_loser.error == (
        "subflow_race_lost" if strategy == "race" else "subflow_any_join_satisfied"
    )


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


@pytest.mark.asyncio
async def test_parent_resume_revalidates_immutable_run_catalog_binding_before_walk(
    db_session,
    monkeypatch,
):
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace

    workspace = Workspace(
        id="workspace-resume-catalog",
        slug="resume-catalog",
        name="Resume catalog",
    )
    child_system = System(
        id="system-resume-child",
        workspace_id=workspace.id,
        name="Child",
        objective="Complete one delegated branch",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
    )
    flow = {
        "schema_version": 3,
        "nodes": [{
            "id": "delegate",
            "kind": "subflow",
            "config": {"system_id": child_system.id},
        }],
        "edges": [],
    }
    parent_system = System(
        id="system-resume-parent",
        workspace_id=workspace.id,
        capability_id="capability-current",
        name="Parent",
        objective="Resume only with the snapshotted catalog identity",
        flow_definition=flow,
    )
    parent = Run(
        id="run-resume-parent",
        workspace_id=workspace.id,
        system_id=parent_system.id,
        capability_id="capability-snapshotted",
        status="waiting_subflows",
        flow_snapshot=flow,
        checkpoints=[{
            "kind": "subflow_wait",
            "state": {"pending_counts": {"delegate": 0}},
        }],
    )
    child = Run(
        id="run-resume-child",
        workspace_id=workspace.id,
        system_id=child_system.id,
        parent_run_id=parent.id,
        delegation_key="c" * 64,
        delegation_node_id="delegate",
        delegation_branch="default",
        status="completed",
        completed_at=datetime.utcnow(),
        output_ref={"answer": "must not be settled after catalog drift"},
    )
    parent.waiting_subflows = {
        "_meta": {"strategy": "all", "state": "waiting"},
        child.delegation_key: {
            "child_run_id": child.id,
            "node_id": "delegate",
            "status": "completed",
        },
    }
    db_session.add(workspace)
    db_session.flush()
    db_session.add_all([child_system, parent_system])
    db_session.flush()
    db_session.add_all([parent, child])
    db_session.commit()

    async def forbidden_walk(*_args, **_kwargs):
        raise AssertionError("catalog drift must fail before the parent walker resumes")

    monkeypatch.setattr(dag, "_walk", forbidden_walk)
    result = await resume_parent_for_child(child.id)

    db_session.expire_all()
    persisted = db_session.query(Run).filter(Run.id == parent.id).one()
    assert result == {
        "id": parent.id,
        "status": "failed",
        "error": "system_catalog_binding_invalid:run_system_capability_mismatch",
    }
    assert persisted.status == "failed"
    assert persisted.completed_at is not None
    assert persisted.checkpoints[-1]["kind"] == "run_end"
