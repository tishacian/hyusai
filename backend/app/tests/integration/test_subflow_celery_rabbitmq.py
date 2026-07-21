"""Destructive P4 gate against dedicated PostgreSQL + RabbitMQ services.

Run only with an isolated database whose name starts with ``agentium_p4``::

    RUN_RABBITMQ_INTEGRATION=1 ENABLE_SUBFLOW_CELERY=true \
      PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET=1 \
      DATABASE_URL=postgresql://.../agentium_p4... CELERY_BROKER_URL=amqp://... \
      pytest -m rabbitmq app/tests/integration/test_subflow_celery_rabbitmq.py
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.rabbitmq,
    pytest.mark.skipif(
        os.getenv("RUN_RABBITMQ_INTEGRATION") != "1",
        reason="RUN_RABBITMQ_INTEGRATION is not configured",
    ),
]


def _child_flow(*, hitl: bool = False, retry_backoff_ms: int | None = None) -> dict:
    if hitl:
        node = {"id": "approval", "kind": "hitl", "config": {"prompt": "P4 child approval"}}
    elif retry_backoff_ms is not None:
        # The unknown skill deterministically records a skipped invocation.
        # Two attempts separated by this backoff form a DB-visible barrier:
        # with real fan-out every branch's first attempt precedes every second
        # attempt; a single worker cannot satisfy that ordering.
        node = {
            "id": "parallel-probe",
            "kind": "retry",
            "config": {
                "skill_slug": "p4_unimplemented_parallel_probe",
                "max_attempts": 2,
                "backoff_ms": retry_backoff_ms,
            },
        }
    else:
        node = {"id": "route", "kind": "decision", "config": {"branches": []}}
    return {"schema_version": 3, "nodes": [node], "edges": []}


def _parent_flow(
    target_ids: list[str],
    strategy: str,
    *,
    timeout_seconds: float | None = None,
) -> dict:
    nodes = []
    for index, target_id in enumerate(target_ids):
        config = {
            "system_id": target_id,
            "branch": f"branch-{index}",
            "join_strategy": strategy,
        }
        if timeout_seconds is not None:
            config["timeout_seconds"] = timeout_seconds
        nodes.append({"id": f"delegate-{index}", "kind": "subflow", "config": config})
    return {"schema_version": 3, "nodes": nodes, "edges": []}


async def _wait_run(run_id: str, statuses: set[str], timeout: float = 60.0):
    from app.db.base import SessionLocal
    from app.models.run import Run

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            row = db.query(Run).filter(Run.id == run_id).first()
            if row is not None and row.status in statuses:
                return row.status
        await asyncio.sleep(0.1)
    raise AssertionError(f"Run {run_id} did not reach {sorted(statuses)} within {timeout}s")


async def _wait_until(predicate, *, timeout: float = 30.0, label: str = "condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.1)
    raise AssertionError(f"{label} was not observed within {timeout}s")


def _build_scenario(
    db,
    *,
    strategy: str,
    child_hitl: list[bool],
    parent_celery: bool = True,
    retry_backoff_ms: int | None = None,
    timeout_seconds: float | None = None,
    input_ref: dict | None = None,
):
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace

    workspace = Workspace(id=str(uuid4()), name="P4 Rabbit", slug=f"p4-rabbit-{uuid4()}")
    db.add(workspace)
    db.flush()
    children = [
        System(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=f"Child {index}",
            objective="P4 integration child",
            flow_definition=_child_flow(hitl=hitl, retry_backoff_ms=retry_backoff_ms),
            settings={},
        )
        for index, hitl in enumerate(child_hitl)
    ]
    parent_system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=f"Parent {strategy}",
        objective="P4 integration parent",
        flow_definition=_parent_flow(
            [child.id for child in children],
            strategy,
            timeout_seconds=timeout_seconds,
        ),
        settings={
            "features": {
                "subflow_celery": parent_celery,
                "run_hitl_celery": True,
            }
        },
    )
    parent_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=parent_system.id,
        status="pending",
        input_ref={"query": "p4", **(input_ref or {})},
    )
    db.add_all([*children, parent_system])
    db.flush()
    db.add(parent_run)
    db.commit()
    return workspace, parent_system, parent_run


def _message_args_and_kwargs(body) -> tuple[list, dict]:
    # Celery protocol v2 exposes (args, kwargs, embed) to before_task_publish.
    if isinstance(body, (list, tuple)) and len(body) >= 2:
        return list(body[0] or []), dict(body[1] or {})
    if isinstance(body, dict):
        return list(body.get("args") or []), dict(body.get("kwargs") or {})
    raise AssertionError(f"Unsupported Celery body: {type(body).__name__}")


def test_real_postgresql_outbox_claimers_take_disjoint_batches(db_session):
    """Two reconcilers must never own the same due row concurrently."""

    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.models.run_dispatch_outbox import RunDispatchOutbox
    from app.models.workspace import Workspace
    from app.services.run_engine.dispatch_outbox import (
        RUN_HITL_RESUME,
        claim_dispatch_batch,
        enqueue_dispatch,
    )

    workspace = Workspace(
        id=str(uuid4()),
        name="P4 claimers",
        slug=f"p4-claimers-{uuid4()}",
    )
    db_session.add(workspace)
    db_session.flush()
    expected_ids = set()
    for _index in range(6):
        run = Run(id=str(uuid4()), workspace_id=workspace.id, status="hitl_pending")
        db_session.add(run)
        db_session.flush()
        event = enqueue_dispatch(
            db_session,
            event_type=RUN_HITL_RESUME,
            workspace_id=workspace.id,
            run_id=run.id,
            decision_id=str(uuid4()),
        )
        expected_ids.add(event.id)
    db_session.commit()

    barrier = threading.Barrier(2)

    def claim() -> set[str]:
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            return {
                row.id
                for row in claim_dispatch_batch(
                    db,
                    batch_size=3,
                    lease_seconds=30,
                )
            }

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(claim)
        second_future = pool.submit(claim)
        first = first_future.result(timeout=15)
        second = second_future.result(timeout=15)

    assert len(first) == 3
    assert len(second) == 3
    assert first.isdisjoint(second)
    assert first | second == expected_ids
    with SessionLocal() as db:
        rows = db.query(RunDispatchOutbox).filter(RunDispatchOutbox.id.in_(expected_ids)).all()
        for row in rows:
            row.state = "cancelled"
            row.lease_token = None
            row.lease_expires_at = None
        db.commit()


def test_real_postgresql_gate_ttl_serializes_resolution_and_competing_sweeps(
    db_session,
    monkeypatch,
):
    """A locked human resolution wins, and competing sweeps apply once."""

    from app.db.base import SessionLocal
    from app.models.decision import Decision
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace
    from app.services.decisions.state_machine import accept
    from app.services.run_engine import gate_ttl

    workspace = Workspace(
        id=str(uuid4()),
        name="P4 gate TTL",
        slug=f"p4-gate-ttl-{uuid4()}",
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="P4 gate TTL",
        objective="Serialize Decision and Run ownership",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
        settings={},
    )
    db_session.add(workspace)
    db_session.flush()
    db_session.add(system)
    db_session.flush()

    def add_expired_gate(index: int) -> tuple[str, str]:
        decision_id = str(uuid4())
        run = Run(
            id=str(uuid4()),
            workspace_id=workspace.id,
            system_id=system.id,
            status="hitl_pending",
            checkpoints=[
                {
                    "kind": "hitl_pause",
                    "node_id": f"gate-{index}",
                    "decision_id": decision_id,
                }
            ],
        )
        decision = Decision(
            id=decision_id,
            workspace_id=workspace.id,
            scope="run",
            target_id=run.id,
            kind="hitl_approval",
            status="proposed",
            title=f"Gate {index}",
            expires_at=datetime.utcnow(),
            expiry_action="reject",
        )
        db_session.add_all([run, decision])
        return run.id, decision.id

    human_run_id, human_decision_id = add_expired_gate(0)
    db_session.commit()
    resume_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        gate_ttl,
        "_resume_paused_run",
        lambda run_id, decision_id: resume_calls.append((run_id, decision_id)),
    )

    locked = threading.Event()
    release = threading.Event()

    def human_resolution() -> None:
        with SessionLocal() as db:
            decision = (
                db.query(Decision)
                .filter(Decision.id == human_decision_id)
                .with_for_update()
                .one()
            )
            db.query(Run).filter(Run.id == human_run_id).with_for_update().one()
            locked.set()
            assert release.wait(timeout=15)
            accept(db, decision, actor="integration:human", commit=False)
            db.commit()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(human_resolution)
        assert locked.wait(timeout=10)
        try:
            skipped = gate_ttl.sweep_expired_gates(limit=10)
        finally:
            release.set()
        future.result(timeout=15)

    assert skipped["swept"] == 0
    assert skipped["skipped"] == 1
    assert resume_calls == []
    with SessionLocal() as db:
        human_decision = db.query(Decision).filter(
            Decision.id == human_decision_id
        ).one()
        human_run = db.query(Run).filter(Run.id == human_run_id).one()
        assert human_decision.status == "accepted"
        assert not any(
            checkpoint.get("kind") == "gate_ttl_expired"
            for checkpoint in human_run.checkpoints or []
        )

    competing = [add_expired_gate(index) for index in range(1, 9)]
    db_session.commit()
    barrier = threading.Barrier(2)

    def sweep() -> dict:
        barrier.wait(timeout=10)
        return gate_ttl.sweep_expired_gates(limit=20)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(sweep)
        second_future = pool.submit(sweep)
        first = first_future.result(timeout=30)
        second = second_future.result(timeout=30)

    assert first["errors"] == 0
    assert second["errors"] == 0
    assert first["swept"] + second["swept"] == len(competing)
    observed = defaultdict(int)
    for call in resume_calls:
        observed[call] += 1
    assert observed == {(run_id, decision_id): 1 for run_id, decision_id in competing}
    with SessionLocal() as db:
        decisions = db.query(Decision).filter(
            Decision.id.in_([decision_id for _run_id, decision_id in competing])
        ).all()
        assert {decision.status for decision in decisions} == {"rejected"}


def test_real_postgresql_watchdog_nowait_avoids_bottom_up_deadlock(db_session):
    """A top-down parent lock makes quarantine retry, never deadlock."""

    from sqlalchemy.exc import OperationalError

    from app.db.base import SessionLocal
    from app.models.decision import Decision
    from app.models.run import Run
    from app.models.workspace import Workspace
    from app.services.run_engine.hitl_watchdog import _reconcile_candidate

    workspace = Workspace(
        id=str(uuid4()),
        name="P4 watchdog lock order",
        slug=f"p4-watchdog-lock-{uuid4()}",
    )
    parent = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        status="waiting_subflows",
        waiting_subflows={},
    )
    decision_id = str(uuid4())
    child = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        parent_run_id=parent.id,
        status="hitl_pending",
        delegation_key=uuid4().hex * 2,
        delegation_node_id="delegate",
        delegation_branch="main",
        delegation_deadline_at=None,
        input_ref={
            "_delegation": {
                "parent_run_id": parent.id,
                "execution_plane": "celery",
            }
        },
        checkpoints=[{"kind": "hitl_pause", "decision_id": decision_id}],
    )
    decision = Decision(
        id=decision_id,
        workspace_id=workspace.id,
        scope="run",
        target_id=child.id,
        kind="hitl_approval",
        status="proposed",
        title="Malformed delegated approval",
    )
    db_session.add_all([workspace, parent, child, decision])
    db_session.commit()

    blocker = SessionLocal()
    try:
        blocker.query(Run).filter(Run.id == parent.id).with_for_update().one()
        started = time.monotonic()

        def reconcile_while_parent_is_locked() -> str:
            with SessionLocal() as db:
                return _reconcile_candidate(
                    db,
                    run_id=child.id,
                    now=datetime.utcnow(),
                )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reconcile_while_parent_is_locked)
            with pytest.raises(OperationalError):
                future.result(timeout=10)
        assert time.monotonic() - started < 5
    finally:
        blocker.rollback()
        blocker.close()

    with SessionLocal() as db:
        assert (
            _reconcile_candidate(
                db,
                run_id=child.id,
                now=datetime.utcnow(),
            )
            == "quarantined"
        )
    with SessionLocal() as db:
        child_row = db.query(Run).filter(Run.id == child.id).one()
        parent_row = db.query(Run).filter(Run.id == parent.id).one()
        decision_row = db.query(Decision).filter(Decision.id == decision.id).one()
        assert child_row.status == "failed"
        assert child_row.delegation_quarantined_at is not None
        assert parent_row.status == "failed"
        assert decision_row.status == "rejected"


@pytest.mark.asyncio
async def test_real_rabbitmq_redelivery_fanout_joins_hitl_and_cancellation(db_session):
    """Exercise identifiers, joins, durable HITL and explicit cancellation."""
    from celery.signals import before_task_publish
    from sqlalchemy import inspect

    from app.core.config import settings
    from app.db.base import SessionLocal
    from app.models.decision import Decision
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace
    from app.services.run_engine.dag import execute_run_dag
    from app.services.run_engine.engine import (
        schedule_run_hitl_resume,
        schedule_subflow_hitl_resume,
    )
    from app.services.run_engine.subflow_orchestration import (
        cancel_waiting_children,
        postgres_coordination_lease,
    )
    from app.workers.tasks import subflow_run

    assert settings.database_url.startswith("postgresql"), "P4 gate requires dedicated PostgreSQL"
    assert "/agentium_p4" in settings.database_url, "P4 gate database must be disposable"
    assert os.getenv("PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET") == "1"
    assert settings.enable_subflow_celery is True, "ENABLE_SUBFLOW_CELERY=true is mandatory"
    assert int(os.getenv("P4_EXPECT_WORKER_CONCURRENCY", "0")) >= 2
    assert "waiting_subflows" in {c["name"] for c in inspect(db_session.bind).get_columns("runs")}

    # Capture the actual Celery publication. The mutable/secret Run payload is
    # persisted in PostgreSQL and must never enter the broker envelope.
    secret = f"must-not-enter-broker-{uuid4()}"
    published: list[tuple[object, dict]] = []

    def capture(sender=None, body=None, headers=None, **_kwargs):
        if sender == "agentium.subflow_run":
            published.append((body, headers or {}))

    before_task_publish.connect(capture, weak=False)
    try:
        _, _, all_parent = _build_scenario(
            db_session,
            strategy="all",
            child_hitl=[False, False, False],
            input_ref={"secret_probe": secret},
        )
        started = await execute_run_dag(all_parent.id)
    finally:
        before_task_publish.disconnect(capture)
    assert started["status"] == "waiting_subflows"
    assert len(published) == 3
    for body, headers in published:
        args, kwargs = _message_args_and_kwargs(body)
        assert headers.get("task") == "agentium.subflow_run"
        assert len(args) == 1 and isinstance(args[0], str)
        assert kwargs == {}
        assert secret not in json.dumps(body, default=str)

    assert await _wait_run(all_parent.id, {"completed"}) == "completed"
    with SessionLocal() as db:
        all_children = db.query(Run).filter(Run.parent_run_id == all_parent.id).all()
        assert len(all_children) == 3
        assert len({row.delegation_key for row in all_children}) == 3
        assert {row.delegation_node_id for row in all_children} == {
            "delegate-0",
            "delegate-1",
            "delegate-2",
        }
        assert {row.delegation_branch for row in all_children} == {
            "branch-0",
            "branch-1",
            "branch-2",
        }
        assert all(row.celery_task_id for row in all_children)
        original_ids = {row.id for row in all_children}
        redelivered_child_id = all_children[0].id

    # A new delivery of the same terminal child must be observed and ACKed,
    # while the unique delegation key prevents a second child Run.
    terminal_delivery = subflow_run.delay(redelivered_child_id)

    def terminal_delivery_observed():
        with SessionLocal() as db:
            child = db.query(Run).filter(Run.id == redelivered_child_id).one()
            return any(
                cp.get("kind") == "subflow_terminal_redelivery"
                and cp.get("task_id") == terminal_delivery.id
                for cp in child.checkpoints or []
                if isinstance(cp, dict)
            )

    await _wait_until(terminal_delivery_observed, label="terminal child ACK marker")
    with SessionLocal() as db:
        assert {row.id for row in db.query(Run).filter(Run.parent_run_id == all_parent.id)} == original_ids

    # Three-level lineage proves that a child which delegates its own child is
    # resumed first, then durably wakes the root instead of leaving it stuck.
    nested_workspace = Workspace(
        id=str(uuid4()),
        name="P4 nested",
        slug=f"p4-nested-{uuid4()}",
    )
    nested_leaf_system = System(
        id=str(uuid4()),
        workspace_id=nested_workspace.id,
        name="Nested leaf",
        objective="P4 nested leaf",
        flow_definition=_child_flow(),
        settings={},
    )
    nested_child_system = System(
        id=str(uuid4()),
        workspace_id=nested_workspace.id,
        name="Nested child",
        objective="P4 nested child",
        flow_definition=_parent_flow([nested_leaf_system.id], "all"),
        settings={"features": {"subflow_celery": True}},
    )
    nested_root_system = System(
        id=str(uuid4()),
        workspace_id=nested_workspace.id,
        name="Nested root",
        objective="P4 nested root",
        flow_definition=_parent_flow([nested_child_system.id], "all"),
        settings={"features": {"subflow_celery": True}},
    )
    nested_root = Run(
        id=str(uuid4()),
        workspace_id=nested_workspace.id,
        system_id=nested_root_system.id,
        status="pending",
        input_ref={"query": "nested"},
    )
    db_session.add(nested_workspace)
    db_session.flush()
    db_session.add_all([nested_leaf_system, nested_child_system, nested_root_system])
    db_session.flush()
    db_session.add(nested_root)
    db_session.commit()
    assert (await execute_run_dag(nested_root.id))["status"] == "waiting_subflows"
    assert await _wait_run(nested_root.id, {"completed"}, timeout=45) == "completed"
    with SessionLocal() as db:
        nested_child = db.query(Run).filter(Run.parent_run_id == nested_root.id).one()
        nested_leaf = db.query(Run).filter(Run.parent_run_id == nested_child.id).one()
        assert nested_child.status == "completed"
        assert nested_leaf.status == "completed"

    # Child HITL resumes through Celery, not an in-process FastAPI continuation.
    _, _, hitl_parent = _build_scenario(db_session, strategy="all", child_hitl=[True])
    assert (await execute_run_dag(hitl_parent.id))["status"] == "waiting_subflows"
    with SessionLocal() as db:
        hitl_child = db.query(Run).filter(Run.parent_run_id == hitl_parent.id).one()
        hitl_child_id = hitl_child.id
    assert await _wait_run(hitl_child_id, {"hitl_pending"}) == "hitl_pending"
    with SessionLocal() as db:
        parent = db.query(Run).filter(Run.id == hitl_parent.id).one()
        assert parent.status == "waiting_subflows"
        assert db.query(Run).filter(Run.parent_run_id == parent.id).count() == 1
        decision = db.query(Decision).filter(Decision.target_id == hitl_child_id).one()
        decision_id = decision.id
        assert decision.workspace_id == hitl_child.workspace_id
        decision.status = "accepted"
        decision.approved_at = datetime.utcnow()
        db.commit()
    schedule_subflow_hitl_resume(hitl_child_id, decision_id=decision_id)
    assert await _wait_run(hitl_parent.id, {"completed"}) == "completed"
    with SessionLocal() as db:
        assert db.query(Run).filter(Run.parent_run_id == hitl_parent.id).count() == 1

    # Ordinary HITL is also durable: an API retry republishes the same task id,
    # while the worker lease prevents a second walker.
    ordinary_workspace = Workspace(
        id=str(uuid4()),
        name="P4 ordinary HITL",
        slug=f"p4-ordinary-hitl-{uuid4()}",
    )
    ordinary_system = System(
        id=str(uuid4()),
        workspace_id=ordinary_workspace.id,
        name="Ordinary HITL",
        objective="P4 durable ordinary resume",
        flow_definition=_child_flow(hitl=True),
        settings={"features": {"run_hitl_celery": True}},
    )
    ordinary_run = Run(
        id=str(uuid4()),
        workspace_id=ordinary_workspace.id,
        system_id=ordinary_system.id,
        status="pending",
        input_ref={"query": "ordinary hitl"},
    )
    db_session.add(ordinary_workspace)
    db_session.flush()
    db_session.add(ordinary_system)
    db_session.flush()
    db_session.add(ordinary_run)
    db_session.commit()
    assert (await execute_run_dag(ordinary_run.id))["status"] == "hitl_pending"
    with SessionLocal() as db:
        ordinary_decision = db.query(Decision).filter(Decision.target_id == ordinary_run.id).one()
        ordinary_decision.status = "accepted"
        ordinary_decision.approved_at = datetime.utcnow()
        ordinary_run_row = db.query(Run).filter(Run.id == ordinary_run.id).one()
        ordinary_run_row.checkpoints = [
            *(ordinary_run_row.checkpoints or []),
            {
                "kind": "hitl_resume_dispatch",
                "decision_id": ordinary_decision.id,
                "plane": "run_celery",
            },
        ]
        db.commit()
        ordinary_decision_id = ordinary_decision.id
    first_resume_task = schedule_run_hitl_resume(
        ordinary_run.id,
        decision_id=ordinary_decision_id,
    )
    assert await _wait_run(ordinary_run.id, {"completed"}) == "completed"
    retry_resume_task = schedule_run_hitl_resume(
        ordinary_run.id,
        decision_id=ordinary_decision_id,
    )
    assert retry_resume_task == first_resume_task
    await asyncio.sleep(0.3)
    with SessionLocal() as db:
        persisted = db.query(Run).filter(Run.id == ordinary_run.id).one()
        assert persisted.status == "completed"
        assert sum(
            cp.get("kind") == "hitl_resume"
            for cp in persisted.checkpoints or []
            if isinstance(cp, dict)
        ) == 1

    # An in-process subflow exposes the child's Decision through both Run
    # endpoints. Publish both generic continuations while holding the exact
    # Decision lease used by the worker: neither Run may advance until that
    # single canonical mutex is released, and only one walker may settle the
    # child HITL afterwards.
    _, _, in_process_parent = _build_scenario(
        db_session,
        strategy="all",
        child_hitl=[True],
        parent_celery=False,
    )
    assert (await execute_run_dag(in_process_parent.id))["status"] == "hitl_pending"
    with SessionLocal() as db:
        paused_parent = db.query(Run).filter(Run.id == in_process_parent.id).one()
        in_process_child = (
            db.query(Run).filter(Run.parent_run_id == in_process_parent.id).one()
        )
        assert paused_parent.status == "hitl_pending"
        in_process_child_id = in_process_child.id
        assert in_process_child.status == "hitl_pending"
        in_process_decision = (
            db.query(Decision).filter(Decision.target_id == in_process_child_id).one()
        )
        in_process_decision_id = in_process_decision.id
        parent_pause = next(
            cp
            for cp in reversed(paused_parent.checkpoints or [])
            if isinstance(cp, dict) and cp.get("kind") == "hitl_pause"
        )
        assert parent_pause.get("decision_id") == in_process_decision_id
        in_process_decision.status = "accepted"
        in_process_decision.approved_at = datetime.utcnow()
        paused_parent.checkpoints = [
            *(paused_parent.checkpoints or []),
            {
                "kind": "hitl_resume_dispatch",
                "decision_id": in_process_decision_id,
                "plane": "run_celery",
            },
        ]
        db.commit()

    resume_publications: list[tuple[object, dict]] = []

    def capture_run_resume(sender=None, body=None, headers=None, **_kwargs):
        if sender == "agentium.run_hitl_resume":
            resume_publications.append((body, headers or {}))

    before_task_publish.connect(capture_run_resume, weak=False)
    try:
        with postgres_coordination_lease(
            "run-hitl-decision",
            in_process_decision_id,
        ) as decision_lease_acquired:
            assert decision_lease_acquired is True
            parent_resume_task, child_resume_task = await asyncio.gather(
                asyncio.to_thread(
                    schedule_run_hitl_resume,
                    in_process_parent.id,
                    decision_id=in_process_decision_id,
                ),
                asyncio.to_thread(
                    schedule_run_hitl_resume,
                    in_process_child_id,
                    decision_id=in_process_decision_id,
                ),
            )
            assert parent_resume_task != child_resume_task
            assert len(resume_publications) == 2
            published_targets = set()
            published_task_ids = set()
            for body, headers in resume_publications:
                args, kwargs = _message_args_and_kwargs(body)
                assert headers.get("task") == "agentium.run_hitl_resume"
                assert len(args) == 2
                assert args[1] == in_process_decision_id
                assert kwargs == {}
                published_targets.add(args[0])
                published_task_ids.add(headers.get("id"))
            assert published_targets == {in_process_parent.id, in_process_child_id}
            assert published_task_ids == {parent_resume_task, child_resume_task}

            # Give both live workers enough time to attempt the held lease.
            # If they used independent Run-scoped locks, one or both walkers
            # would have advanced despite this Decision-scoped barrier.
            await asyncio.sleep(1.5)
            with SessionLocal() as db:
                held_parent = db.query(Run).filter(Run.id == in_process_parent.id).one()
                held_child = db.query(Run).filter(Run.id == in_process_child_id).one()
                assert held_parent.status == "hitl_pending"
                assert held_child.status == "hitl_pending"
    finally:
        before_task_publish.disconnect(capture_run_resume)

    assert await _wait_run(in_process_parent.id, {"completed"}) == "completed"
    assert await _wait_run(in_process_child_id, {"completed"}) == "completed"
    with SessionLocal() as db:
        persisted_parent = db.query(Run).filter(Run.id == in_process_parent.id).one()
        persisted_children = (
            db.query(Run).filter(Run.parent_run_id == in_process_parent.id).all()
        )
        assert len(persisted_children) == 1
        persisted_child = persisted_children[0]
        assert persisted_child.id == in_process_child_id
        assert persisted_child.status == "completed"
        assert persisted_child.delegation_key
        assert sum(
            cp.get("kind") == "hitl_resume"
            for cp in persisted_child.checkpoints or []
            if isinstance(cp, dict)
        ) == 1
        assert sum(
            cp.get("kind") == "hitl_resume"
            for cp in persisted_parent.checkpoints or []
            if isinstance(cp, dict)
        ) == 1

    # any and race choose deterministically and cancel their live HITL loser.
    for strategy in ("any", "race"):
        _, _, parent_run = _build_scenario(db_session, strategy=strategy, child_hitl=[False, True])
        assert (await execute_run_dag(parent_run.id))["status"] == "waiting_subflows"
        assert await _wait_run(parent_run.id, {"completed"}) == "completed"
        with SessionLocal() as db:
            children = db.query(Run).filter(Run.parent_run_id == parent_run.id).all()
            assert len(children) == 2
            assert sorted(row.status for row in children) == ["cancelled", "completed"]
            cancelled = next(row for row in children if row.status == "cancelled")
            expected = "subflow_race_lost" if strategy == "race" else "subflow_any_join_satisfied"
            assert cancelled.error == expected

    # Explicit parent cancellation propagates to the exact active child IDs;
    # late worker completion cannot publish output or create a replacement.
    _, _, cancelled_parent = _build_scenario(
        db_session,
        strategy="all",
        child_hitl=[False, False],
        retry_backoff_ms=5000,
    )
    assert (await execute_run_dag(cancelled_parent.id))["status"] == "waiting_subflows"

    def active_children():
        with SessionLocal() as db:
            rows = db.query(Run).filter(Run.parent_run_id == cancelled_parent.id).all()
            return rows if len(rows) == 2 and all(row.status == "running" for row in rows) else None

    children = await _wait_until(active_children, label="two active delegated children")
    child_ids = {row.id for row in children}
    with SessionLocal() as db:
        parent = db.query(Run).filter(Run.id == cancelled_parent.id).one()
        parent.status = "cancelled"
        parent.completed_at = datetime.utcnow()
        db.commit()
    assert cancel_waiting_children(cancelled_parent.id, reason="parent_cancelled") == 2
    await asyncio.sleep(1)
    with SessionLocal() as db:
        rows = db.query(Run).filter(Run.parent_run_id == cancelled_parent.id).all()
        assert {row.id for row in rows} == child_ids
        assert all(row.status == "cancelled" and row.output_ref == {} for row in rows)


@pytest.mark.asyncio
async def test_real_subflow_fanout_is_parallel_and_timeout_propagates(db_session):
    """Prove overlap from DB timestamps and exercise a real Celery timeout."""
    from app.db.base import SessionLocal
    from app.models.run import Run, SkillInvocation
    from app.services.run_engine.dag import execute_run_dag

    _, _, parallel_parent = _build_scenario(
        db_session,
        strategy="all",
        child_hitl=[False, False],
        retry_backoff_ms=2500,
    )
    assert (await execute_run_dag(parallel_parent.id))["status"] == "waiting_subflows"
    assert await _wait_run(parallel_parent.id, {"completed"}, timeout=45) == "completed"
    with SessionLocal() as db:
        children = db.query(Run).filter(Run.parent_run_id == parallel_parent.id).all()
        attempts: dict[str, list[SkillInvocation]] = defaultdict(list)
        for child in children:
            attempts[child.id] = (
                db.query(SkillInvocation)
                .filter(SkillInvocation.run_id == child.id)
                .order_by(SkillInvocation.started_at.asc())
                .all()
            )
        assert len(attempts) == 2 and all(len(rows) == 2 for rows in attempts.values())
        first_starts = [rows[0].started_at for rows in attempts.values()]
        second_starts = [rows[1].started_at for rows in attempts.values()]
        assert max(first_starts) < min(second_starts), "subflow branches did not overlap"

    _, _, timeout_parent = _build_scenario(
        db_session,
        strategy="all",
        child_hitl=[False],
        retry_backoff_ms=5000,
        timeout_seconds=1.5,
    )
    assert (await execute_run_dag(timeout_parent.id))["status"] == "waiting_subflows"
    assert await _wait_run(timeout_parent.id, {"failed"}, timeout=45) == "failed"
    with SessionLocal() as db:
        children = db.query(Run).filter(Run.parent_run_id == timeout_parent.id).all()
        assert len(children) == 1
        child = children[0]
        assert child.status in {"failed", "cancelled"}
        assert "deadline" in (child.error or "").lower()
        delegation = (child.input_ref or {}).get("_delegation") or {}
        assert delegation.get("deadline_at")
        assert delegation.get("timeout_seconds") == 1.5


@pytest.mark.asyncio
async def test_acks_late_redelivers_after_dedicated_worker_crash(db_session):
    """Crash after the real parent claim; redelivery must recover that parent."""
    from app.db.base import SessionLocal
    from app.models.run import Run
    from app.services.run_engine.dag import execute_run_dag

    token = str(uuid4())
    root = Path(os.getenv("SUBFLOW_CRASH_PROBE_DIR", "/tmp"))
    marker = root / f"agentium-p4-parent-claim-{token}.first"
    marker.unlink(missing_ok=True)
    try:
        _, _, parent = _build_scenario(
            db_session,
            strategy="all",
            child_hitl=[False],
            input_ref={"_p4_crash_after_parent_claim": token},
        )
        assert (await execute_run_dag(parent.id))["status"] == "waiting_subflows"
        assert await _wait_run(parent.id, {"completed"}, timeout=60) == "completed"
        assert marker.exists(), "worker did not crash after the real parent claim"
        first_owner = marker.read_text(encoding="utf-8")
        with SessionLocal() as db:
            persisted = db.query(Run).filter(Run.id == parent.id).one()
            meta = (persisted.waiting_subflows or {}).get("_meta") or {}
            assert int(meta.get("resume_generation") or 0) >= 2
            assert meta.get("resume_owner") == first_owner
            assert meta.get("last_delivery_redelivered") is True
            assert any(
                cp.get("kind") == "subflow_resume_recovered"
                and cp.get("redelivered") is True
                for cp in persisted.checkpoints or []
                if isinstance(cp, dict)
            )
            assert db.query(Run).filter(Run.parent_run_id == parent.id).count() == 1
    finally:
        marker.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_real_outbox_recovers_missing_publish_and_watchdog_expires_hitl(
    db_session,
    monkeypatch,
):
    """Prove both P4.2 repair loops against the real broker and database."""

    from celery.signals import before_task_publish

    from app.db.base import SessionLocal
    from app.models.decision import Decision
    from app.models.run import Run
    from app.models.run_dispatch_outbox import RunDispatchOutbox
    from app.services.run_engine import dispatch_outbox
    from app.services.run_engine.dag import execute_run_dag
    from app.services.run_engine.dispatch_outbox import (
        SUBFLOW_PARENT_RESUME,
        SUBFLOW_RUN,
    )
    from app.services.run_engine.hitl_watchdog import (
        WATCHDOG_ACTOR,
        WATCHDOG_ERROR,
        expire_overdue_hitl_waits,
    )

    # Simulate the exact commit/publish gap: DAG state + outbox commit, then an
    # API/worker crash before the fast path can touch RabbitMQ.
    _, _, parent = _build_scenario(
        db_session,
        strategy="all",
        child_hitl=[False],
    )
    real_reconcile = dispatch_outbox.reconcile_dispatch_outbox
    monkeypatch.setattr(
        dispatch_outbox,
        "reconcile_dispatch_outbox",
        lambda **_kwargs: {"claimed": 0, "published": 0},
    )
    assert (await execute_run_dag(parent.id))["status"] == "waiting_subflows"
    monkeypatch.setattr(dispatch_outbox, "reconcile_dispatch_outbox", real_reconcile)

    with SessionLocal() as db:
        child = db.query(Run).filter(Run.parent_run_id == parent.id).one()
        child_id = child.id
        initial = (
            db.query(RunDispatchOutbox)
            .filter(
                RunDispatchOutbox.run_id == child.id,
                RunDispatchOutbox.event_type == SUBFLOW_RUN,
            )
            .one()
        )
        initial_task_id = initial.task_id
        assert child.status == "pending"
        assert initial.state == "pending"

    published: list[tuple[object, dict]] = []

    def capture(sender=None, body=None, headers=None, **_kwargs):
        if sender == "agentium.subflow_run":
            published.append((body, headers or {}))

    before_task_publish.connect(capture, weak=False)
    try:
        report = real_reconcile(batch_size=20, lease_seconds=5)
    finally:
        before_task_publish.disconnect(capture)
    assert report["published"] >= 1
    assert len(published) == 1
    args, kwargs = _message_args_and_kwargs(published[0][0])
    assert args == [child_id]
    assert kwargs == {}
    assert published[0][1].get("id") == initial_task_id
    assert await _wait_run(parent.id, {"completed"}, timeout=45) == "completed"
    with SessionLocal() as db:
        assert db.query(Run).filter(Run.parent_run_id == parent.id).count() == 1
        assert (
            db.query(RunDispatchOutbox)
            .filter(
                RunDispatchOutbox.run_id == child_id,
                RunDispatchOutbox.event_type == SUBFLOW_RUN,
            )
            .one()
            .state
            == "published"
        )

    # Conversely, a child-only claim cannot use a normal parent resume when
    # that parent's waiting envelope is corrupt. The watchdog terminalises
    # both sides directly so no ancestor is left waiting forever.
    _, _, broken_parent = _build_scenario(
        db_session,
        strategy="all",
        child_hitl=[True],
        timeout_seconds=30.0,
    )
    assert (await execute_run_dag(broken_parent.id))["status"] == "waiting_subflows"
    with SessionLocal() as db:
        broken_child = db.query(Run).filter(Run.parent_run_id == broken_parent.id).one()
        broken_child_id = broken_child.id
    assert await _wait_run(broken_child_id, {"hitl_pending"}) == "hitl_pending"
    with SessionLocal() as db:
        broken_child = db.query(Run).filter(Run.id == broken_child_id).one()
        broken_parent_row = db.query(Run).filter(Run.id == broken_parent.id).one()
        broken_child.delegation_deadline_at = None
        broken_parent_row.waiting_subflows = {}
        db.commit()

    broken = expire_overdue_hitl_waits(batch_size=10)
    assert broken["quarantined"] == 1
    with SessionLocal() as db:
        child_row = db.query(Run).filter(Run.id == broken_child_id).one()
        parent_row = db.query(Run).filter(Run.id == broken_parent.id).one()
        assert child_row.status == "failed"
        assert child_row.error == "subflow_hitl_watchdog_invalid_state"
        assert parent_row.status == "failed"
        assert parent_row.error == "subflow_hitl_watchdog_invalid_state"

    # A delegated HITL has no live worker after it pauses. Its immutable
    # deadline must therefore be enforced by the watchdog, which atomically
    # fails the child and persists the parent wake-up in the same outbox.
    _, _, timeout_parent = _build_scenario(
        db_session,
        strategy="all",
        child_hitl=[True],
        timeout_seconds=1.0,
    )
    assert (await execute_run_dag(timeout_parent.id))["status"] == "waiting_subflows"
    with SessionLocal() as db:
        timeout_child = db.query(Run).filter(Run.parent_run_id == timeout_parent.id).one()
        timeout_child_id = timeout_child.id
    assert await _wait_run(timeout_child_id, {"hitl_pending"}) == "hitl_pending"
    await asyncio.sleep(1.2)

    expired = expire_overdue_hitl_waits(batch_size=10)
    assert expired["expired"] == 1
    repeated = expire_overdue_hitl_waits(batch_size=10)
    assert repeated["expired"] == 0
    real_reconcile(batch_size=20, lease_seconds=5)
    assert await _wait_run(timeout_parent.id, {"failed"}, timeout=45) == "failed"
    with SessionLocal() as db:
        timed_out = db.query(Run).filter(Run.id == timeout_child_id).one()
        decision = db.query(Decision).filter(Decision.target_id == timeout_child_id).one()
        assert timed_out.status == "failed"
        assert timed_out.error == WATCHDOG_ERROR
        assert decision.status == "rejected"
        assert decision.approved_by == WATCHDOG_ACTOR
        assert (
            db.query(RunDispatchOutbox)
            .filter(
                RunDispatchOutbox.run_id == timeout_parent.id,
                RunDispatchOutbox.event_type == SUBFLOW_PARENT_RESUME,
                RunDispatchOutbox.source_id == timeout_child_id,
            )
            .count()
            == 1
        )

    # A malformed historical row may have lost the indexed deadline and the
    # child-side execution-plane claim.  The parent envelope still owns the
    # exact child/key.  The PostgreSQL selector must discover that claim via a
    # workspace-scoped self join and quarantine it instead of ignoring it.
    _, _, malformed_parent = _build_scenario(
        db_session,
        strategy="all",
        child_hitl=[True],
        timeout_seconds=30.0,
    )
    assert (await execute_run_dag(malformed_parent.id))["status"] == "waiting_subflows"
    with SessionLocal() as db:
        malformed_child = db.query(Run).filter(
            Run.parent_run_id == malformed_parent.id
        ).one()
        malformed_child_id = malformed_child.id
    assert await _wait_run(malformed_child_id, {"hitl_pending"}) == "hitl_pending"
    with SessionLocal() as db:
        malformed_child = db.query(Run).filter(Run.id == malformed_child_id).one()
        delegation = dict((malformed_child.input_ref or {}).get("_delegation") or {})
        delegation.pop("execution_plane")
        malformed_child.input_ref = {"_delegation": delegation}
        malformed_child.delegation_deadline_at = None
        db.commit()

    malformed = expire_overdue_hitl_waits(batch_size=10)
    assert malformed["quarantined"] == 1
    repeated_malformed = expire_overdue_hitl_waits(batch_size=10)
    assert repeated_malformed["quarantined"] == 0
    repair = real_reconcile(batch_size=20, lease_seconds=5)
    assert repair["published"] >= 1
    assert await _wait_run(malformed_parent.id, {"failed"}, timeout=45) == "failed"
    with SessionLocal() as db:
        quarantined = db.query(Run).filter(Run.id == malformed_child_id).one()
        malformed_decision = db.query(Decision).filter(
            Decision.target_id == malformed_child_id
        ).one()
        assert quarantined.status == "failed"
        assert quarantined.error == "subflow_hitl_watchdog_invalid_state"
        assert quarantined.checkpoints[-2]["reason"] == "missing_delegation_deadline"
        assert malformed_decision.status == "rejected"
        assert (
            db.query(RunDispatchOutbox)
            .filter(
                RunDispatchOutbox.run_id == malformed_parent.id,
                RunDispatchOutbox.event_type == SUBFLOW_PARENT_RESUME,
                RunDispatchOutbox.source_id == malformed_child_id,
            )
            .one()
            .state
            == "published"
        )
