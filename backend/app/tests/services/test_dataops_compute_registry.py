"""DataOps projects the durable lifecycle without dispatching a second job."""

from datetime import timedelta
from uuid import uuid4

import polars as pl
import pytest

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.compute_run import ComputeRun
from app.models.recipe import RecipeExecution
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.schemas.data_prep import DataPrepSpec
from app.services import compute_runs as runs
from app.services.dataops import compute_registry as bridge
from app.services.dataops.preparation import submit_preparation
from app.services.recipe_executions import finalize_execution
from app.services.tabular_datasets import register_frame, reserve_frame


@pytest.fixture
def plane(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "connector_framework_enabled", True)
    monkeypatch.setattr(settings, "dataops_enabled", True)
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "objects"))
    workspace = Workspace(id=str(uuid4()), name="shared lifecycle", slug=str(uuid4()), settings={})
    db_session.add(workspace)
    db_session.commit()
    return workspace


def execution(db, plane):
    output = reserve_frame(db, workspace_id=plane.id, name="pending", commit=False)
    row = RecipeExecution(
        workspace_id=plane.id,
        status="queued",
        timeout_s=60,
        input_json={"kind": "data_prep", "outputs": {"out": output.id}},
    )
    db.add(row)
    compute = bridge.register(db, row)
    db.commit()
    return row, compute, output


def test_real_preparation_uses_single_shared_lifecycle(db_session, plane):
    dataset = register_frame(
        db_session, workspace_id=plane.id, name="Input", frame=pl.DataFrame({"n": [1, 2]})
    )
    db_session.commit()
    row = submit_preparation(
        db_session,
        workspace_id=plane.id,
        spec=DataPrepSpec(operation="prepare", outputs=[{"name": "Result", "port": "out"}]),
        inputs={"in": {"dataset_id": dataset.id}},
    )
    assert row.status == "succeeded", row.error
    compute = db_session.query(ComputeRun).filter_by(recipe_execution_id=row.id).one()
    assert compute.status == "succeeded", compute.error_code
    assert compute.output_json == row.output_json
    assert compute.core_hours > 0
    assert compute.cost_usd is None
    assert db_session.get(TabularDataset, row.output_json["dataset_id"]).status == "ready"


def test_pending_deadline_includes_queue_and_fails_reserved_output(db_session, plane):
    row, compute, output = execution(db_session, plane)
    compute.deadline_at = runs.utcnow() - timedelta(seconds=1)
    db_session.commit()
    assert not bridge.start(db_session, row)
    assert row.status == "timed_out"
    assert output.status == "failed"


def test_shared_cancel_fences_legacy_success(db_session, plane):
    row, compute, output = execution(db_session, plane)
    assert bridge.start(db_session, row)
    row.status = "running"
    db_session.commit()
    runs.request_cancel(db_session, compute)
    output.status = "ready"
    row.output_json = {"dataset_id": output.id}
    finalize_execution(row, status="succeeded")
    db_session.commit()
    assert compute.status == "cancelled"
    assert row.status == "cancelled"
    assert row.output_json is None
    assert output.status == "failed"


def test_stale_legacy_owner_cannot_publish(db_session, plane):
    row, compute, output = execution(db_session, plane)
    assert bridge.start(db_session, row)
    row._compute_lease_token = "stale-owner"
    output.status = "ready"
    row.output_json = {"dataset_id": output.id}
    finalize_execution(row, status="succeeded")
    db_session.commit()
    assert row.status == "failed"
    assert output.status == "failed"
    assert compute.status == "running"
    assert compute.output_json is None


def test_heartbeat_committed_without_locking_lifecycle_until_completion(db_session, plane):
    row, compute, _ = execution(db_session, plane)
    assert bridge.start(db_session, row)
    row.status = "running"
    db_session.commit()
    assert not bridge.poll(db_session, row.id)
    with SessionLocal() as observer:
        current = observer.get(ComputeRun, compute.id)
        assert current.lease_expires_at > runs.utcnow()
        # Independent cancellation can proceed before final publication.
        runs.request_cancel(observer, current)
    assert bridge.poll(db_session, row.id)


@pytest.mark.parametrize("delay, expected", [(35, "succeeded"), (65, "timed_out")])
def test_publication_holds_shared_fence_until_absolute_deadline(
    db_session, plane, monkeypatch, delay, expected
):
    row, compute, output = execution(db_session, plane)
    assert bridge.start(db_session, row)
    row.status = "running"
    db_session.commit()
    now = runs.utcnow()
    bridge.begin_settlement(db_session, row)
    assert compute.status == "committing"
    assert compute.lease_expires_at == compute.deadline_at
    monkeypatch.setattr(runs, "utcnow", lambda: now + timedelta(seconds=delay))
    output.status = "ready"
    row.output_json = {"dataset_id": output.id}
    finalize_execution(row, status="succeeded")
    db_session.commit()
    assert compute.status == expected
    assert row.status == expected
    assert output.status == ("ready" if expected == "succeeded" else "failed")


def test_settlement_cannot_revive_an_expired_owner(db_session, plane):
    row, compute, _ = execution(db_session, plane)
    assert bridge.start(db_session, row)
    compute.lease_expires_at = runs.utcnow() - timedelta(seconds=1)
    db_session.commit()
    with pytest.raises(runs.ComputeRunError, match="COMPUTE_LEASE_LOST"):
        bridge.begin_settlement(db_session, row)
