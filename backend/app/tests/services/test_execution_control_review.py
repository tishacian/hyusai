"""Failure paths found during the execution-plane integration review."""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, current_thread
from uuid import uuid4

import pytest
from sqlalchemy import event

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.compute_run import ComputeRun
from app.models.execution_control import ExecutionCapacity, ExecutionDispatch, ExecutionReservation
from app.models.recipe import RecipeExecution
from app.models.run import Run
from app.models.tabular import MLModel
from app.services import compute_runs
from app.services.dataops import compute_registry as bridge
from app.services.execution import admission, dispatch, io_lease, ml_lifecycle, run_worker
from app.services.execution.contracts import ExecutionPolicy
from app.tests.services.test_execution_control import pending
from app.tests.services.test_execution_control import plane as plane


def compute(db, workspace):
    row = ComputeRun(id=str(uuid4()), workspace_id=workspace.id, kind="connector_read",
                     operation="preview", deadline_at=datetime.utcnow()+timedelta(minutes=5),
                     metrics_json={"coordination_version": 1})
    db.add(row)
    dispatch.stage(db, "compute_run", row, deadline_at=row.deadline_at)
    db.commit()
    return row


def test_paused_compute_preserves_durable_intent_without_effect(plane):
    db, ws = plane
    row = compute(db, ws)
    db.add(ExecutionCapacity(scope="global", paused=1))
    db.commit()
    assert compute_runs.claim_run(db, row.id) is None
    db.refresh(row)
    intent = db.query(ExecutionDispatch).one()
    assert row.status == "queued" and row.lease_token is None
    assert intent.state == "pending" and intent.error_code == "EXECUTION_ADMISSION_PAUSED"
    assert not db.query(ExecutionReservation).count()


def test_late_stopped_compute_releases_capacity_without_publishing(plane):
    db, ws = plane
    row = compute(db, ws)
    token = compute_runs.claim_run(db, row.id)
    assert compute_runs.advance_run(db, row.id, token, "launching")
    assert compute_runs.advance_run(db, row.id, token, "running")
    db.refresh(row)
    assert compute_runs.reap_runs(db, now=row.lease_expires_at+timedelta(seconds=1)) == 1
    allocation = db.query(ExecutionReservation).one()
    assert allocation.released_at is None
    assert not compute_runs.finish_run(db, row.id, "wrong-owner", status="succeeded")
    db.refresh(allocation)
    assert allocation.released_at is None
    assert not compute_runs.finish_run(db, row.id, token, status="succeeded",
                                       publish=lambda: pytest.fail("late publication"))
    db.refresh(allocation)
    db.refresh(row)
    assert allocation.released_at is not None and allocation.cpu_seconds is None
    assert row.status == "lost" and row.output_json is None


def test_unknown_old_process_cannot_reset_its_budget_at_midnight(plane):
    db, ws = plane
    now = datetime.utcnow()
    old = admission.reserve(db, workspace_id=ws.id, entity_kind="recipe_execution", entity_id="old",
                            cpu_cores=1, memory_mb=512, now=now-timedelta(days=2),
                            deadline_at=now-timedelta(days=1, hours=23))
    admission.settle(db, entity_kind="recipe_execution", entity_id=old.entity_id,
                     token=old.lease_token, outcome="reconciliation_required", process_stopped=False)
    db.commit()
    with pytest.raises(admission.AdmissionError, match="RECONCILIATION_REQUIRED"):
        admission.reserve(db, workspace_id=ws.id, entity_kind="recipe_execution", entity_id="next",
                          cpu_cores=1, memory_mb=512, deadline_at=now+timedelta(minutes=1))


def model(db, ws):
    row = MLModel(id=str(uuid4()), workspace_id=ws.id, name="One", slug=str(uuid4()),
                  task="classification", target="label", algo="logistic_regression")
    db.add(row)
    db.commit()
    return row


def test_durable_only_ml_claim_rechecks_current_owner(plane, monkeypatch):
    db, ws = plane
    monkeypatch.setattr(settings, "execution_control_enabled", False)
    row = model(db, ws)
    ml_lifecycle.register(db, row)
    db.commit()
    assert row.execution_policy is None
    with SessionLocal() as duplicate:
        stale = duplicate.get(MLModel, row.id)
        assert stale.status == "pending"
        assert ml_lifecycle.start(db, row)
        row.status = "training"
        db.commit()
        assert not ml_lifecycle.start(duplicate, stale)
    assert db.query(ExecutionReservation).count() == 0


def test_durable_only_sql_redelivery_does_not_declare_live_worker_lost(plane, monkeypatch):
    from app.services.dataops.sql_execution import run_sql_execution
    db, ws = plane
    monkeypatch.setattr(settings, "execution_control_enabled", False)
    row = RecipeExecution(id=str(uuid4()), workspace_id=ws.id, status="running",
                          lifecycle_controller="legacy", input_json={"kind": "sql_transform"})
    db.add(row)
    dispatch.stage(db, "recipe_execution", row, deadline_at=datetime.utcnow()+timedelta(minutes=1))
    db.commit()
    assert run_sql_execution(row.id)["status"] == "running"
    db.refresh(row)
    assert row.status == "running" and row.error is None


@pytest.mark.parametrize("kind", ["recipe", "recipe_legacy", "ml", "compute"])
def test_child_created_after_parent_cancel_scan_never_starts(plane, kind):
    db, ws = plane
    parent = Run(id=str(uuid4()), workspace_id=ws.id, status="running", cancel_requested=True)
    db.add(parent)
    db.commit()
    if kind in {"recipe", "recipe_legacy"}:
        row = pending(db, ws)
        if kind == "recipe_legacy":
            row.lifecycle_controller = "legacy"
        row.run_id = parent.id
        db.commit()
        assert not bridge.start(db, row)
    elif kind == "ml":
        row = model(db, ws)
        row.run_id = parent.id
        ml_lifecycle.register(db, row)
        db.commit()
        assert not ml_lifecycle.start(db, row)
    else:
        row = compute(db, ws)
        row.run_id = parent.id
        db.commit()
        assert compute_runs.claim_run(db, row.id) is None
    db.refresh(row)
    assert row.status == "cancelled"
    assert not db.query(ExecutionReservation).count()


@pytest.mark.parametrize("terminal_status", ["ready", "failed", "cancelled"])
def test_ml_allocation_remains_occupied_until_registry_publication_returns(
    plane,
    monkeypatch,
    terminal_status,
):
    db, ws = plane
    row = model(db, ws)
    ml_lifecycle.register(db, row)
    db.commit()
    assert ml_lifecycle.start(db, row)
    row.status = "training"
    row.status_detail = "saving"
    db.commit()
    allocation = db.query(ExecutionReservation).one()
    assert ml_lifecycle.begin_settlement(db, row, "ready", None) == ("ready", None)
    assert allocation.released_at is None
    after_upload = datetime.utcnow() + timedelta(seconds=45)

    class Clock(datetime):
        @classmethod
        def utcnow(cls):
            return after_upload

    monkeypatch.setattr(ml_lifecycle, "datetime", Clock)
    row.status = terminal_status
    row.status_detail = None
    row.error = None if terminal_status == "ready" else "harness stopped"
    if terminal_status == "ready":
        row.model_uri = "workspaces/test/ml/models/model"
        row.metrics_json = {"primary": {"key": "roc_auc", "value": 0.91}}
        row.runtime_json = {"fingerprint": "producer-runtime"}
        row.trained_at = after_upload
    assert ml_lifecycle.settle(db, row, terminal_status, row.error) == (
        terminal_status,
        row.error,
    )
    db.commit()
    db.refresh(row)
    assert row.status == terminal_status
    assert row.status_detail is None
    assert row.error == (None if terminal_status == "ready" else "harness stopped")
    if terminal_status == "ready":
        assert row.model_uri == "workspaces/test/ml/models/model"
        assert row.metrics_json["primary"]["value"] == 0.91
        assert row.runtime_json == {"fingerprint": "producer-runtime"}
        assert row.trained_at == after_upload
    db.refresh(allocation)
    assert allocation.released_at == after_upload
    assert allocation.allocated_core_hours >= 45 * allocation.cpu_cores / 3600


@pytest.mark.parametrize("authority", ["cancelled", "lost", "deadline", "lease", "owner"])
def test_ml_settlement_preserves_durable_fences_before_pending_success(plane, authority):
    db, ws = plane
    row = model(db, ws)
    ml_lifecycle.register(db, row)
    db.commit()
    assert ml_lifecycle.start(db, row)
    row.status = "training"
    db.commit()
    token = row._native_lease_token
    # A competing cancellation/watchdog update reaches the database before the
    # worker settles. The worker still holds a pending success in its ORM state.
    with SessionLocal() as other:
        native = other.get(MLModel, row.id)
        if authority == "cancelled":
            native.cancel_requested = True
        elif authority == "lost":
            native.status, native.error = "failed", "EXECUTION_WORKER_LOST"
        elif authority == "deadline":
            native.deadline_at = datetime.utcnow() - timedelta(seconds=1)
        elif authority == "lease":
            native.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
        else:
            native.lease_token = "another-owner"
        other.commit()
    row.status, row.error = "ready", None
    row.model_uri = "must-not-become-ready"
    if authority == "owner":
        with pytest.raises(admission.AdmissionError, match="EXECUTION_LEASE_LOST"):
            ml_lifecycle.settle(db, row, "ready", None)
        db.rollback()
        db.refresh(row)
        assert row.model_uri is None and row.status == "training"
        assert db.query(ExecutionReservation).one().released_at is None
        return
    expected = (
        ("cancelled", "EXECUTION_CANCELLED")
        if authority == "cancelled"
        else ("failed", "EXECUTION_WORKER_LOST")
        if authority == "lost"
        else ("failed", "EXECUTION_DEADLINE_EXCEEDED")
    )
    assert ml_lifecycle.settle(db, row, "ready", None) == expected
    row.status, row.error = expected
    db.commit()
    db.refresh(row)
    assert (row.status, row.error) == expected
    allocation = db.query(ExecutionReservation).one()
    assert allocation.lease_token == token and allocation.released_at is not None


def test_blocking_io_keeps_lease_and_cancel_prevents_publication(plane):
    db, ws = plane
    row = pending(db, ws)
    db.commit()
    assert bridge.start(db, row)
    row.status = "running"
    db.commit()
    heartbeat = Event()
    def observed(connection, cursor, statement, parameters, context, executemany):
        if current_thread().name == "execution-io-lease" and statement.startswith("UPDATE recipe_executions"):
            heartbeat.set()
    event.listen(db.bind, "after_cursor_execute", observed)
    try:
        with pytest.raises(admission.AdmissionError, match="LEASE_LOST"):
            with io_lease.maintain(RecipeExecution, row.id, row.lease_token, status="running", interval_s=0.01):
                assert heartbeat.wait(3), "I/O heartbeat did not run on an independent connection"
                with SessionLocal() as other:
                    native = other.get(RecipeExecution, row.id)
                    native.cancel_requested = True
                    other.commit()
    finally:
        event.remove(db.bind, "after_cursor_execute", observed)
    # Cancellation during SDK I/O never fabricates physical stop/accounting.
    assert db.query(ExecutionReservation).one().released_at is None


@contextmanager
def unowned(*args):
    yield True


def staged_run(db, ws, *, revision="review-revision", status="pending"):
    policy = ExecutionPolicy(runtime_revision=revision, deadline_at=datetime.now(UTC)+timedelta(seconds=40))
    row = Run(id=str(uuid4()), workspace_id=ws.id, status=status,
              execution_policy=policy.model_dump(mode="json"))
    db.add(row)
    dispatch.stage(db, "run", row, deadline_at=policy.deadline_at.replace(tzinfo=None))
    db.commit()
    return row


def test_worker_refuses_incompatible_frozen_revision(plane, monkeypatch):
    db, ws = plane
    row = staged_run(db, ws)
    monkeypatch.setattr(settings, "database_url", "postgresql://unused")
    monkeypatch.setattr(settings, "agentium_image_revision", "different")
    monkeypatch.setattr("app.services.run_engine.subflow_orchestration.postgres_coordination_lease", unowned)
    monkeypatch.setattr("app.services.run_engine.engine.schedule_run", lambda _: pytest.fail("different code executed"))
    assert run_worker.execute(row.id)["status"] == "failed"
    db.refresh(row)
    assert row.error == "EXECUTION_VERSION_UNAVAILABLE"
    assert not db.query(ExecutionReservation).count()


def test_orphaned_running_flow_is_uncertain_even_on_new_image(plane, monkeypatch):
    db, ws = plane
    row = staged_run(db, ws, status="running")
    child = pending(db, ws)
    child.run_id = row.id
    db.commit()
    monkeypatch.setattr(settings, "database_url", "postgresql://unused")
    monkeypatch.setattr(settings, "agentium_image_revision", "different")
    monkeypatch.setattr("app.services.run_engine.subflow_orchestration.postgres_coordination_lease", unowned)
    monkeypatch.setattr("app.services.run_engine.engine.schedule_run", lambda _: pytest.fail("uncertain effects replayed"))
    assert run_worker.execute(row.id)["status"] == "failed"
    db.refresh(row)
    db.refresh(child)
    assert row.error == "EXECUTION_OUTCOME_REQUIRES_RECONCILIATION" and row.cancel_requested
    assert child.status == "cancelled" and child.cancel_requested


def test_flow_waiting_for_child_never_reserves_compute_slot(plane, monkeypatch):
    db, ws = plane
    row = staged_run(db, ws)
    monkeypatch.setattr(settings, "database_url", "postgresql://unused")
    monkeypatch.setattr(settings, "agentium_image_revision", "review-revision")
    monkeypatch.setattr(settings, "execution_global_slots", 1)
    monkeypatch.setattr(settings, "execution_interactive_reserved_slots", 0)
    monkeypatch.setattr("app.services.run_engine.subflow_orchestration.postgres_coordination_lease", unowned)
    def schedule(identifier):
        with SessionLocal() as child_db:
            assert child_db.query(ExecutionReservation).count() == 0
            admission.reserve(child_db, workspace_id=ws.id, entity_kind="recipe_execution", entity_id="child",
                              cpu_cores=2, memory_mb=512, deadline_at=datetime.utcnow()+timedelta(seconds=30))
            child_db.get(Run, identifier).status = "completed"
            child_db.commit()
    monkeypatch.setattr("app.services.run_engine.engine.schedule_run", schedule)
    assert run_worker.execute(row.id)["status"] == "scheduled"
    assert {r.entity_kind for r in db.query(ExecutionReservation)} == {"recipe_execution"}


@pytest.mark.parametrize("owner_alive", [False, True])
def test_expired_run_requests_live_owner_or_fails_lost_owner(plane, monkeypatch, owner_alive):
    db, ws = plane
    row = staged_run(db, ws, status="running")
    @contextmanager
    def lease(*args):
        yield not owner_alive
    monkeypatch.setattr("app.services.run_engine.subflow_orchestration.postgres_coordination_lease", lease)
    assert run_worker.reap(db, now=datetime.utcnow()+timedelta(minutes=1)) == 1
    db.commit()
    assert row.cancel_requested
    assert row.status == ("running" if owner_alive else "failed")
    if not owner_alive:
        assert row.error == "EXECUTION_OUTCOME_REQUIRES_RECONCILIATION"


def test_control_worker_drains_after_all_admission_flags_are_disabled(plane, monkeypatch):
    from app.workers import execution_control
    db, ws = plane
    row = pending(db, ws)
    db.commit()
    for flag in ("activity_observability_enabled", "execution_control_enabled", "execution_durable_dispatch_enabled"):
        monkeypatch.setattr(settings, flag, False)
    published, commands = [], []
    monkeypatch.setattr(execution_control.app, "send_task", lambda *args, **kw: published.append(kw))
    monkeypatch.setattr("app.services.activity_observability.commands.process_commands",
                        lambda db, **kw: commands.append(kw) or 0)
    result = execution_control.tick.run()
    assert result["published"] == 1 and published[0]["args"] == [row.id]
    assert commands == [{"limit": 20}]


def test_temporal_backlog_cannot_starve_expired_legacy_runs(plane, monkeypatch):
    db, ws = plane
    temporal = staged_run(db, ws, status="running")
    intent = db.query(ExecutionDispatch).filter_by(entity_id=temporal.id).one()
    intent.task_name = "agentium.execution_temporal_start"
    intent.deadline_at = datetime.utcnow() - timedelta(minutes=2)
    temporal.execution_policy = ExecutionPolicy(
        engine="temporal", runtime_revision="review-revision",
        native_profile={"composition": "agent_data_agent"}, native_profile_digest="a" * 64,
        deadline_at=datetime.now(UTC)-timedelta(minutes=2),
    ).model_dump(mode="json")
    legacy = staged_run(db, ws, status="running")
    db.query(ExecutionDispatch).filter_by(entity_id=legacy.id).one().deadline_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    monkeypatch.setattr("app.services.run_engine.subflow_orchestration.postgres_coordination_lease", unowned)
    assert run_worker.reap(db, limit=1) == 1
    db.commit()
    assert legacy.status == "failed" and legacy.cancel_requested
    assert temporal.status == "running" and not temporal.cancel_requested
