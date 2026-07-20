"""Protected P4 gate against a real PostgreSQL + RabbitMQ + worker stack.

Run with::

    RUN_RABBITMQ_INTEGRATION=1 ENABLE_SUBFLOW_CELERY=true \
      DATABASE_URL=postgresql://... CELERY_BROKER_URL=amqp://... \
      pytest -m rabbitmq app/tests/integration/test_subflow_celery_rabbitmq.py
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
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


def _child_flow(*, hitl: bool = False) -> dict:
    if hitl:
        node = {"id": "approval", "kind": "hitl", "config": {"prompt": "P4 child approval"}}
    else:
        node = {"id": "route", "kind": "decision", "config": {"branches": []}}
    return {"schema_version": 3, "nodes": [node], "edges": []}


def _parent_flow(target_ids: list[str], strategy: str) -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            {
                "id": f"delegate-{index}",
                "kind": "subflow",
                "config": {
                    "system_id": target_id,
                    "branch": f"branch-{index}",
                    "join_strategy": strategy,
                },
            }
            for index, target_id in enumerate(target_ids)
        ],
        "edges": [],
    }


async def _wait_run(run_id: str, statuses: set[str], timeout: float = 30.0):
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


def _build_scenario(db, *, strategy: str, child_hitl: list[bool]):
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
            flow_definition=_child_flow(hitl=hitl),
            settings={},
        )
        for index, hitl in enumerate(child_hitl)
    ]
    parent_system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name=f"Parent {strategy}",
        objective="P4 integration parent",
        flow_definition=_parent_flow([child.id for child in children], strategy),
        settings={"features": {"subflow_celery": True}},
    )
    parent_run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=parent_system.id,
        status="pending",
        input_ref={"query": "p4"},
    )
    db.add_all([*children, parent_system, parent_run])
    db.commit()
    return workspace, parent_system, parent_run


@pytest.mark.asyncio
async def test_real_rabbitmq_redelivery_fanout_joins_hitl_and_cancellation(db_session):
    """One protected test exercises the complete durable delegation lifecycle."""
    from kombu import Connection
    from sqlalchemy import inspect

    from app.core.config import settings
    from app.db.base import SessionLocal
    from app.models.decision import Decision
    from app.models.run import Run
    from app.services.run_engine.dag import execute_run_dag, resume_run_dag
    from app.services.run_engine.subflow_orchestration import resume_parent_for_child
    from app.workers.tasks import subflow_run

    assert settings.database_url.startswith("postgresql"), "RabbitMQ gate requires dedicated PostgreSQL"
    assert settings.enable_subflow_celery is True, "ENABLE_SUBFLOW_CELERY=true is mandatory"
    assert "waiting_subflows" in {c["name"] for c in inspect(db_session.bind).get_columns("runs")}

    # Broker-level redelivery proves the immutable message is only a child id.
    with Connection(settings.celery_broker_url, connect_timeout=2) as connection:
        connection.ensure_connection(max_retries=0)
        queue_name = f"agentium-p4-redelivery-{uuid4()}"
        with connection.SimpleQueue(queue_name) as queue:
            queue.put({"child_run_id": "stable-child"})
            first = queue.get(block=True, timeout=3)
            assert first.payload == {"child_run_id": "stable-child"}
            first.reject(requeue=True)
            again = queue.get(block=True, timeout=3)
            assert again.payload == first.payload
            again.ack()

    # all: three messages are persisted/dispatched before the parent waits;
    # worker callbacks resume it once, under the parent row lock.
    _, _, all_parent = _build_scenario(db_session, strategy="all", child_hitl=[False, False, False])
    started = await execute_run_dag(all_parent.id)
    assert started["status"] == "waiting_subflows"
    assert await _wait_run(all_parent.id, {"completed"}) == "completed"
    with SessionLocal() as db:
        all_children = db.query(Run).filter(Run.parent_run_id == all_parent.id).all()
        assert len(all_children) == 3
        assert len({row.delegation_key for row in all_children}) == 3
        assert all(row.celery_task_id for row in all_children)
        original_ids = {row.id for row in all_children}
        redelivered_child = all_children[0]

    # Actual worker redelivery of a terminal child is a no-op and cannot add a
    # second child Run. No result-backend assumption is required.
    subflow_run.delay(redelivered_child.id)
    await asyncio.sleep(1)
    with SessionLocal() as db:
        assert {row.id for row in db.query(Run).filter(Run.parent_run_id == all_parent.id)} == original_ids

    # Child HITL propagates as child state while the parent keeps its durable
    # wait; accepting it resumes the same child and then the same parent.
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
        decision.status = "accepted"
        decision.approved_at = datetime.utcnow()
        db.commit()
    await resume_run_dag(hitl_child_id, decision_id=decision_id)
    await resume_parent_for_child(hitl_child_id)
    assert await _wait_run(hitl_parent.id, {"completed"}) == "completed"
    with SessionLocal() as db:
        assert db.query(Run).filter(Run.parent_run_id == hitl_parent.id).count() == 1

    # any and race both choose deterministically; race explicitly persists
    # cancellation of its non-terminal HITL loser before broker revoke.
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


def test_acks_late_redelivers_after_dedicated_worker_crash():
    """Kill worker A mid-task; worker B must receive the same task id."""
    from app.workers.celery_app import celery_app
    from app.workers.tasks import subflow_crash_probe

    token = str(uuid4())
    queue = f"agentium-p4-crash-{token}"
    root = Path(os.getenv("SUBFLOW_CRASH_PROBE_DIR", "/tmp"))
    first = root / f"agentium-p4-crash-{token}.first"
    redelivered = root / f"agentium-p4-crash-{token}.redelivered"
    first.unlink(missing_ok=True)
    redelivered.unlink(missing_ok=True)

    def worker(name: str):
        env = dict(os.environ)
        env["RUN_RABBITMQ_INTEGRATION"] = "1"
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "app.workers.celery_app",
                "worker",
                "--pool=solo",
                "--concurrency=1",
                "--without-gossip",
                "--without-mingle",
                "--without-heartbeat",
                "--loglevel=WARNING",
                "-Q",
                queue,
                "-n",
                name,
            ],
            cwd=str(Path(__file__).resolve().parents[3]),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    first_worker = worker(f"p4-crash-a-{token}@%h")
    second_worker = None
    try:
        # Give the dedicated worker a bounded boot window, then publish only
        # to its isolated queue. Failure to boot is a gate failure, not a skip.
        deadline = time.monotonic() + 15
        ready = False
        prefix = f"p4-crash-a-{token}@"
        while time.monotonic() < deadline and first_worker.poll() is None:
            replies = celery_app.control.inspect(timeout=1).ping() or {}
            if any(str(name).startswith(prefix) for name in replies):
                ready = True
                break
        assert ready, "dedicated crash worker failed during boot"
        result = subflow_crash_probe.apply_async(args=[token], queue=queue)

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and first_worker.poll() is None:
            time.sleep(0.1)
        assert first_worker.returncode == 91
        assert first.read_text(encoding="utf-8") == result.id

        second_worker = worker(f"p4-crash-b-{token}@%h")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not redelivered.exists():
            assert second_worker.poll() is None, "redelivery worker exited before ACK"
            time.sleep(0.1)
        assert redelivered.exists(), "acks_late message was not redelivered after worker loss"
        assert redelivered.read_text(encoding="utf-8") == result.id
    finally:
        for process in (first_worker, second_worker):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        first.unlink(missing_ok=True)
        redelivered.unlink(missing_ok=True)
