"""PostgreSQL-only concurrency gate for Lot 8 authority refresh.

This test is collected in ordinary suites but intentionally skips on SQLite;
only PostgreSQL can prove that an Act waiting on the tenant mutex observes the
System/ControlPolicy state committed by the concurrent administrator::

    PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET=1 \
      DATABASE_URL=postgresql://.../test_lot8_value_loop \
      pytest -m postgresql app/tests/integration/test_value_loop_postgresql.py
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event

pytestmark = [pytest.mark.integration, pytest.mark.postgresql]


def test_act_waits_for_admin_and_refreshes_current_policy_on_postgresql(db_session):
    if db_session.get_bind().dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL row-lock semantics")

    from app.db.base import SessionLocal
    from app.models.policy import ControlPolicy
    from app.models.run import Run
    from app.models.system import System
    from app.models.workspace import Workspace
    from app.services import value_loop
    from app.services.control_policy_snapshot import control_policy_execution_contract

    actuator = value_loop.CONTROL_POLICY_GUARDRAILS_PATCH_V1
    workspace = Workspace(
        id=str(uuid4()),
        name="Lot 8 lock refresh",
        slug=f"lot8-lock-refresh-{uuid4()}",
    )
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Lot 8 concurrent policy",
        scope="system",
        max_cost_per_decision=8.0,
        max_latency_ms=8_000.0,
        mandatory_hitl_if_confidence_below=0.45,
        extra={
            "membrane_spec": {
                "version": 2,
                "enforcement_mode": "enforce",
                "capabilities": {"allowed_actions": [actuator]},
            }
        },
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Lot 8 concurrent System",
        objective="Prove current authority at Act time",
        status="active",
        control_policy_id=policy.id,
        settings={
            "value_loop": {
                "actuators": {
                    actuator: {
                        "enabled": True,
                        "fields": {
                            "max_cost_per_decision": {"min": 0, "max": 50},
                            "max_latency_ms": {"min": 100, "max": 30_000},
                            "mandatory_hitl_if_confidence_below": {
                                "min": 0,
                                "max": 1,
                            },
                        },
                    }
                }
            },
            "steering_model": {
                "version": "value-model-v1",
                "confidence": 0.8,
                "assumptions": ["Comparable run mix"],
                "forecasts": {
                    "mandatory_hitl_if_confidence_below": [
                        {
                            "minimum": 0,
                            "maximum": 1,
                            "include_maximum": True,
                            "cost_multiplier": 0.9,
                            "value_multiplier": 1.25,
                        }
                    ]
                },
            },
        },
    )
    policy.target_id = system.id
    baseline = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        started_at=datetime.utcnow() - timedelta(hours=2),
        completed_at=datetime.utcnow() - timedelta(hours=1),
        value_estimated=100.0,
        value_source="auto",
        input_ref={
            "execution": {
                "control_policy": control_policy_execution_contract(policy),
            }
        },
    )
    db_session.add_all([workspace, policy, system, baseline])
    db_session.commit()

    scenario, _decision = value_loop.create_value_scenario(
        db_session,
        workspace_id=workspace.id,
        system_id=system.id,
        source_run_id=baseline.id,
        objective="Refresh authority",
        title="Concurrent authority",
        rationale={"source": "postgresql-gate"},
        actor="owner@example.test",
        idempotency_key=f"create-{uuid4()}",
    )
    simulation = value_loop.simulate_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        recommended_patch={"mandatory_hitl_if_confidence_below": 0.6},
        actor="builder@example.test",
        idempotency_key=f"simulate-{uuid4()}",
    )
    value_loop.approve_value_scenario(
        db_session,
        workspace_id=workspace.id,
        scenario_id=scenario.id,
        simulation_id=simulation.id,
        actor="approver@example.test",
        idempotency_key=f"approve-{uuid4()}",
    )

    actor_loaded = threading.Event()
    admin_locked = threading.Event()
    actor_issued_lock = threading.Event()

    def administer() -> None:
        with SessionLocal() as db:
            assert actor_loaded.wait(timeout=10)
            db.query(Workspace).filter(Workspace.id == workspace.id).populate_existing().with_for_update(
                of=Workspace
            ).one()
            db.query(System).filter(System.id == system.id).populate_existing().with_for_update(
                of=System
            ).one()
            current = (
                db.query(ControlPolicy)
                .filter(ControlPolicy.id == policy.id)
                .populate_existing()
                .with_for_update(of=ControlPolicy)
                .one()
            )
            current.mandatory_hitl_if_confidence_below = 0.55
            db.flush()
            admin_locked.set()
            assert actor_issued_lock.wait(timeout=10)
            # Keep the transaction open long enough to prove the other
            # connection's FOR UPDATE is genuinely waiting on PostgreSQL.
            time.sleep(0.25)
            db.commit()

    def execute() -> tuple[str, float, float]:
        with SessionLocal() as db:
            stale_system = db.query(System).filter(System.id == system.id).one()
            stale_policy = db.query(ControlPolicy).filter(ControlPolicy.id == policy.id).one()
            assert stale_system.control_policy_id == stale_policy.id
            assert stale_policy.mandatory_hitl_if_confidence_below == 0.45
            actor_loaded.set()
            assert admin_locked.wait(timeout=10)

            connection = db.connection()

            def before_cursor_execute(
                _conn,
                _cursor,
                statement,
                _parameters,
                _context,
                _executemany,
            ) -> None:
                if "FOR UPDATE" in statement and "workspaces" in statement:
                    actor_issued_lock.set()

            event.listen(connection, "before_cursor_execute", before_cursor_execute)
            started = time.monotonic()
            try:
                action = value_loop.act_value_scenario(
                    db,
                    workspace_id=workspace.id,
                    scenario_id=scenario.id,
                    actuator=actuator,
                    patch={"mandatory_hitl_if_confidence_below": 0.6},
                    actor="operator@example.test",
                    idempotency_key="postgresql-concurrent-act",
                )
            finally:
                event.remove(connection, "before_cursor_execute", before_cursor_execute)
            return action.id, action.before_state["mandatory_hitl_if_confidence_below"], (
                time.monotonic() - started
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        admin_future = pool.submit(administer)
        actor_future = pool.submit(execute)
        action_id, before_value, elapsed = actor_future.result(timeout=20)
        admin_future.result(timeout=20)

    db_session.expire_all()
    persisted = db_session.query(ControlPolicy).filter(ControlPolicy.id == policy.id).one()
    assert action_id
    assert before_value == 0.55
    assert persisted.mandatory_hitl_if_confidence_below == 0.6
    assert elapsed >= 0.2
