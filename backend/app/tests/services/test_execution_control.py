"""Behavioural contracts: atomic admission, crash-safe dispatch, native fencing."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import polars as pl
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.compute_run import ComputeRun
from app.models.execution_control import ExecutionDispatch, ExecutionReservation
from app.models.recipe import RecipeExecution
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.schemas.data_prep import DataPrepSpec
from app.services.dataops import compute_registry as bridge
from app.services.dataops.preparation import submit_preparation
from app.services.execution import admission, dispatch, recipe_lifecycle
from app.services.execution.contracts import ExecutionPolicy, wait_for_result
from app.services.recipe_executions import finalize_execution, request_cancel
from app.services.tabular_datasets import register_frame


@pytest.fixture
def plane(db_session, monkeypatch, tmp_path):
    for key, value in {
        "execution_control_enabled": True,
        "execution_durable_dispatch_enabled": True,
        "execution_canary_workspaces": "*",
        "connector_framework_enabled": True,
        "dataops_enabled": True,
        "dataops_write_delta_enabled": False,
        "worker_eager_mode": False,
        "object_store_backend": "local",
        "object_store_base_path": str(tmp_path / "objects"),
        "execution_workspace_cpu": 4,
        "execution_workspace_memory_mb": 8192,
        "execution_global_cpu": 8,
        "execution_global_memory_mb": 16384,
    }.items():
        monkeypatch.setattr(settings, key, value)
    workspace = Workspace(id=str(uuid4()), slug=str(uuid4()), name="Execution")
    db_session.add(workspace)
    db_session.commit()
    return db_session, workspace


def pending(db, workspace, *, timeout=60):
    row = RecipeExecution(
        id=str(uuid4()),
        workspace_id=workspace.id,
        status="queued",
        timeout_s=timeout,
        input_json={"kind": "data_prep"},
    )
    db.add(row)
    bridge.register(db, row)
    return row


def test_native_and_dispatch_intent_rollback_together(plane):
    db, ws = plane
    row = pending(db, ws)
    identifier = row.id
    assert db.query(ExecutionDispatch).one().entity_id == identifier
    assert db.query(ComputeRun).count() == 0
    db.rollback()
    assert db.get(RecipeExecution, identifier) is None
    assert db.query(ExecutionDispatch).count() == 0


def test_broker_failure_and_crash_after_send_reuse_identity(plane):
    db, ws = plane
    row = pending(db, ws)
    db.commit()
    seen = []

    def offline(*args, **kwargs):
        seen.append(kwargs)
        raise RuntimeError("secret broker credentials")

    now = datetime.utcnow()
    assert dispatch.publish_due(SessionLocal, publisher=offline, now=now) == 0
    db.expire_all()
    intent = db.query(ExecutionDispatch).one()
    assert intent.state == "pending" and intent.error_code == "EXECUTION_BROKER_UNAVAILABLE"
    assert (
        dispatch.publish_due(
            SessionLocal, publisher=lambda *a, **kw: seen.append(kw), now=now + timedelta(seconds=3)
        )
        == 1
    )
    db.expire_all()
    assert intent.state == "published"
    # Simulate publisher death after confirm, before its DB acknowledgement.
    intent.state, intent.lease_token, intent.lease_expires_at = "leased", "lost", now
    db.commit()
    assert (
        dispatch.publish_due(
            SessionLocal, publisher=lambda *a, **kw: seen.append(kw), now=now + timedelta(seconds=4)
        )
        == 1
    )
    assert len({entry["task_id"] for entry in seen}) == 1
    assert all(entry["args"] == [row.id] for entry in seen)


def test_expired_submission_settles_native_without_publishing(plane):
    db, ws = plane
    row = pending(db, ws)
    db.commit()
    assert (
        dispatch.publish_due(
            SessionLocal,
            publisher=lambda *a, **kw: pytest.fail("expired work sent"),
            now=datetime.utcnow() + timedelta(minutes=2),
        )
        == 0
    )
    db.expire_all()
    assert row.status == "timed_out" and db.query(ExecutionDispatch).one().state == "dead"


def test_resource_reservation_preserves_interactive_capacity(plane, monkeypatch):
    db, ws = plane
    monkeypatch.setattr(settings, "execution_global_slots", 3)
    monkeypatch.setattr(settings, "execution_workspace_slots", 3)
    deadline = datetime.utcnow() + timedelta(minutes=1)

    def allocate(identifier, lane="batch"):
        return admission.reserve(
            db,
            workspace_id=ws.id,
            entity_kind="recipe_execution",
            entity_id=identifier,
            cpu_cores=1,
            memory_mb=512,
            deadline_at=deadline,
            lane=lane,
        )

    batch1 = allocate("batch1")
    allocate("batch2")
    with pytest.raises(admission.AdmissionError, match="SLOTS_EXHAUSTED"):
        allocate("batch3")
    allocate("ui", "interactive")
    db.commit()
    assert admission.snapshot(db)["active"] == 3
    admission.settle(
        db,
        entity_kind="recipe_execution",
        entity_id="batch1",
        token=batch1.lease_token,
        outcome="worker_lost",
        process_stopped=False,
    )
    db.commit()
    assert admission.snapshot(db)["active"] == 3
    assert batch1.cpu_seconds is None and batch1.allocated_core_hours is None


def test_budget_reserves_both_days_and_tariff_is_frozen(plane, monkeypatch):
    db, ws = plane
    monkeypatch.setattr(settings, "execution_workspace_core_hours", 0.1)
    monkeypatch.setattr(settings, "dataops_core_hour_usd", 1.25)
    start = datetime(2026, 10, 15, 23, 59)
    row = admission.reserve(
        db,
        workspace_id=ws.id,
        entity_kind="recipe_execution",
        entity_id="midnight",
        cpu_cores=1,
        memory_mb=512,
        now=start,
        deadline_at=start + timedelta(minutes=2),
    )
    assert set(row.policy["budget_days"]) == {"2026-10-15", "2026-10-16"}
    monkeypatch.setattr(settings, "dataops_core_hour_usd", 999)
    assert row.policy["cpu_hour_usd"] == 1.25
    with pytest.raises(admission.AdmissionError, match="BUDGET_EXHAUSTED"):
        admission.reserve(
            db,
            workspace_id=ws.id,
            entity_kind="recipe_execution",
            entity_id="over",
            cpu_cores=1,
            memory_mb=512,
            now=start,
            deadline_at=start + timedelta(minutes=8),
        )


def test_controller_frozen_and_duplicate_cannot_claim(plane, monkeypatch):
    db, ws = plane
    row = pending(db, ws)
    db.commit()
    monkeypatch.setattr(settings, "execution_control_enabled", False)
    assert bridge.start(db, row)
    row.status, row.started_at = "running", datetime.utcnow()
    db.commit()
    token = row.lease_token
    with SessionLocal() as other:
        duplicate = other.get(RecipeExecution, row.id)
        assert not bridge.start(other, duplicate)
    db.refresh(row)
    assert row.status == "running" and row.lease_token == token
    assert db.query(ComputeRun).count() == 0


def test_cancel_and_expired_lease_fence_publication(plane):
    db, ws = plane
    row = pending(db, ws)
    db.commit()
    assert bridge.start(db, row)
    row.status, row.started_at = "running", datetime.utcnow()
    db.commit()
    with SessionLocal() as other:
        request_cancel(other, other.get(RecipeExecution, row.id))
    with pytest.raises(admission.AdmissionError, match="LEASE_LOST"):
        bridge.begin_settlement(db, row)
    db.rollback()
    finalize_execution(row, status="succeeded")
    db.commit()
    assert row.status == "cancelled" and row.output_json is None
    assert db.query(ExecutionReservation).one().released_at is not None


def test_reaper_does_not_claim_lost_process_stopped(plane):
    db, ws = plane
    row = pending(db, ws)
    db.commit()
    assert bridge.start(db, row)
    row.status, row.started_at = "running", datetime.utcnow()
    row.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.commit()
    assert recipe_lifecycle.reap(db) == 1
    db.commit()
    assert row.status == "failed"
    allocation = db.query(ExecutionReservation).one()
    assert allocation.released_at is None and allocation.outcome == "reconciliation_required"


def test_real_native_preparation_and_allocated_cost(plane, monkeypatch):
    db, ws = plane
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    dataset = register_frame(
        db, workspace_id=ws.id, name="Input", frame=pl.DataFrame({"n": [1, 2]})
    )
    db.commit()
    row = submit_preparation(
        db,
        workspace_id=ws.id,
        spec=DataPrepSpec(operation="prepare", outputs=[{"name": "Result", "port": "out"}]),
        inputs={"in": {"dataset_id": dataset.id}},
    )
    assert row.status == "succeeded", row.error
    assert db.get(TabularDataset, row.output_json["dataset_id"]).row_count == 2
    allocation = db.query(ExecutionReservation).one()
    assert allocation.released_at is not None and allocation.allocated_core_hours > 0
    assert allocation.cpu_seconds is None  # allocation must not masquerade as CPU telemetry
    assert db.query(ComputeRun).count() == 0


def test_http_wait_does_not_spawn_or_cancel_execution():
    reads = []

    async def state():
        reads.append(1)
        return {"id": "durable", "status": "running"}

    code, result = asyncio.run(wait_for_result(state, wait_s=0))
    assert code == 202 and result["id"] == "durable" and len(reads) == 1

    async def done():
        return {"status": "completed"}

    assert asyncio.run(wait_for_result(done, wait_s=1))[0] == 200
    with pytest.raises(ValidationError):
        ExecutionPolicy(runtime_revision="test", effect="reconcile", max_attempts=2)
    assert (
        ExecutionPolicy(
            runtime_revision="test", deadline_at=datetime.now(UTC) - timedelta(seconds=1)
        ).remaining_seconds()
        == 0
    )


def test_new_controller_and_dispatch_only_apply_to_canary(plane, monkeypatch):
    db, ws = plane
    monkeypatch.setattr(settings, "execution_canary_workspaces", "showcase")
    row = pending(db, ws)
    db.commit()
    assert row.lifecycle_controller == "compute_v1"
    assert db.query(ExecutionDispatch).count() == 0
    assert db.query(ComputeRun).filter_by(recipe_execution_id=row.id).count() == 1
    ws.slug = "showcase"
    db.commit()
    next_row = pending(db, ws)
    db.commit()
    assert next_row.lifecycle_controller == "recipe_v1"
    assert db.query(ExecutionDispatch).count() == 1


def test_training_uses_native_fence_and_shared_resource_budget(plane):
    from app.models.tabular import MLModel
    from app.services.execution import ml_lifecycle

    db, ws = plane
    model = MLModel(
        id=str(uuid4()),
        workspace_id=ws.id,
        name="Training",
        slug="training",
        version=1,
        task="classification",
        algo="logistic",
        target="target",
        status="pending",
    )
    db.add(model)
    intent = ml_lifecycle.register(db, model)
    db.commit()
    assert intent is not None
    assert ml_lifecycle.start(db, model)
    model.status = "training"
    db.commit()
    assert not ml_lifecycle.poll(db, model)
    with SessionLocal() as other:
        from app.services.tabular_ml import request_cancel as cancel_training

        cancel_training(other, other.get(MLModel, model.id))
    assert ml_lifecycle.poll(db, model)
    assert ml_lifecycle.settle(db, model, "ready", None) == ("cancelled", "EXECUTION_CANCELLED")
    db.commit()
    assert db.query(ExecutionReservation).one().released_at is not None


def test_native_cancel_does_not_cancel_replayed_sibling(plane):
    from app.models.run import Run
    from app.services.execution.control import request_run_cancel

    db, ws = plane
    parent = Run(id="parent", workspace_id=ws.id, status="pending")
    replay = Run(
        id="replay", workspace_id=ws.id, parent_run_id="parent", status="pending", trigger="rerun"
    )
    delegated = Run(
        id="child",
        workspace_id=ws.id,
        parent_run_id="parent",
        delegation_key="delegation",
        status="pending",
    )
    db.add_all([parent, replay, delegated])
    db.commit()
    request_run_cancel(db, parent)
    assert parent.status == delegated.status == "cancelled"
    assert replay.status == "pending" and not replay.cancel_requested


def test_wait_api_returns_same_identity_without_dispatch(plane, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import activities as api
    from app.models.user import User
    from app.services.activity_observability.projection import activity_id

    db, ws = plane
    monkeypatch.setattr(settings, "activity_observability_enabled", True)
    user = User(id="wait-user", username="wait-user", role="admin", is_active=True)
    row = RecipeExecution(id="wait-recipe", workspace_id=ws.id, status="running")
    db.add_all([user, row])
    db.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/observability")
    app.dependency_overrides[api.get_db] = lambda: db
    app.dependency_overrides[api.get_current_user] = lambda: user
    app.dependency_overrides[api.get_current_workspace] = lambda: ws
    client = TestClient(app)
    url = f"/observability/activities/{activity_id('recipe_execution', row.id)}/wait?wait_s=0"
    response = client.get(url)
    assert response.status_code == 202
    assert response.json()["native_id"] == row.id
    row.status = "succeeded"
    db.commit()
    response = client.get(url)
    assert response.status_code == 200 and response.json()["native_id"] == row.id
    assert db.query(ExecutionDispatch).count() == 0
