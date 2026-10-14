"""Legacy samples are durable worker work; API previews never scan full inputs."""

from datetime import datetime, timedelta
from uuid import uuid4

import polars as pl
import pytest

from app.core.config import settings
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.schemas.data_prep import DataPrepSpec
from app.services.dataops import samples, storage
from app.services.dataops.preparation import preview_preparation
from app.services.tabular_datasets import TabularError, register_frame


@pytest.fixture
def legacy(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "dataops_enabled", True)
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    workspace = Workspace(id=str(uuid4()), name="Sample", slug=uuid4().hex)
    db_session.add(workspace)
    db_session.commit()
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Legacy",
        frame=pl.DataFrame({"id": list(range(20))}),
    )
    original = dataset.lineage_json["sample"]
    dataset.lineage_json = {k: v for k, v in dataset.lineage_json.items() if k != "sample"}
    db_session.commit()
    return workspace, dataset, original


def test_missing_sample_is_queued_once_without_api_scanning(db_session, legacy, monkeypatch):
    from app.workers.celery_app import celery_app

    workspace, dataset, original = legacy
    calls = []
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: calls.append((a, kw)))
    spec = DataPrepSpec(operation="prepare", outputs=[{"name": "Preview"}])
    with monkeypatch.context() as local:

        def forbidden(*args, **kwargs):
            pytest.fail("The API must not materialize a full dataset")

        local.setattr(storage, "materialize_files", forbidden)
        for _ in range(2):
            with pytest.raises(TabularError) as error:
                preview_preparation(
                    db_session,
                    workspace_id=workspace.id,
                    spec=spec,
                    inputs={"in": {"dataset_id": dataset.id}},
                )
            assert error.value.code == "DATAPREP_SAMPLE_PENDING"
    assert len(calls) == 1
    assert calls[0][0] == ("agentium.dataops_build_sample",)
    assert calls[0][1]["queue"] == settings.celery_dataops_queue
    assert dataset.status == "ready"
    assert dataset.lineage_json["sample_status"] == "sample_pending"
    job_id = calls[0][1]["args"][0]
    # The old file remains: recovery must verify identical bytes, not replace it.
    result = samples.run_sample(job_id)
    assert result["status"] == "completed", result
    assert samples.run_sample(job_id) == result
    db_session.expire_all()
    assert dataset.lineage_json["sample"]["sha256"] == original["sha256"]
    result = preview_preparation(
        db_session, workspace_id=workspace.id, spec=spec, inputs={"in": {"dataset_id": dataset.id}}
    )
    assert [row["id"] for row in result["rows"]] == list(range(20))


def test_sample_worker_refuses_retired_input(db_session, legacy, monkeypatch):
    from app.workers.celery_app import celery_app

    workspace, dataset, _ = legacy
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: None)
    with pytest.raises(TabularError):
        samples.ensure_samples(db_session, workspace.id, {"in": dataset})
    job_id = dataset.lineage_json["sample_job_id"]
    dataset.status = "deleted"
    db_session.commit()
    result = samples.run_sample(job_id)
    assert result == {"status": "failed", "code": "DATAPREP_INPUT_UNAVAILABLE"}


def test_lost_broker_publish_can_be_redispatched_after_delay(db_session, legacy, monkeypatch):
    from app.workers.celery_app import celery_app

    workspace, dataset, _ = legacy

    def disconnected(*args, **kwargs):
        raise OSError("broker unavailable")

    monkeypatch.setattr(celery_app, "send_task", disconnected)
    with pytest.raises(TabularError) as error:
        samples.ensure_samples(db_session, workspace.id, {"in": dataset})
    assert error.value.code == "DATAPREP_SAMPLE_QUEUE_UNAVAILABLE"
    job = db_session.get(WorkspaceJob, dataset.lineage_json["sample_job_id"])
    job.updated_at = datetime.utcnow() - timedelta(seconds=61)
    db_session.commit()
    sent = []
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: sent.append(kw))
    with pytest.raises(TabularError):
        samples.ensure_samples(db_session, workspace.id, {"in": dataset})
    assert len(sent) == 1 and sent[0]["args"] == [job.id]


def test_retirement_and_purge_during_materialization_cannot_recreate_bytes(
    db_session, legacy, monkeypatch
):
    from app.db.base import SessionLocal
    from app.models.tabular import TabularDataset
    from app.services.object_store import get_object_store
    from app.services.tabular_datasets import dataset_prefix
    from app.workers.celery_app import celery_app

    workspace, dataset, original = legacy
    identity, workspace_id = dataset.id, workspace.id
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **kw: None)
    with pytest.raises(TabularError):
        samples.ensure_samples(db_session, workspace_id, {"in": dataset})
    job_id = dataset.lineage_json["sample_job_id"]
    materialize = storage.materialize_files
    store = get_object_store()

    def retire_after_read(row, directory):
        paths = materialize(row, directory)
        # Interleave the effects of a committed retirement/physical purge with
        # a worker that already copied the source, using a separate DB session.
        with SessionLocal() as other:
            other.get(TabularDataset, identity).status = "deleted"
            store.delete_prefix(dataset_prefix(workspace_id, identity) + "/")
            other.commit()
        return paths

    monkeypatch.setattr(storage, "materialize_files", retire_after_read)
    monkeypatch.setattr(
        storage, "persist_sample", lambda *a, **kw: pytest.fail("Late worker recreated purged data")
    )
    assert samples.run_sample(job_id) == {"status": "failed", "code": "DATAPREP_INPUT_UNAVAILABLE"}
    assert not store._local_path(original["key"]).exists()


def test_preview_nan_is_json_safe_on_first_call_and_cache(db_session, legacy):
    import json

    workspace, _, _ = legacy
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Non-finite",
        frame=pl.DataFrame({"value": [1.0, float("nan"), float("inf"), -float("inf")]}),
    )
    for cached in (False, True):
        result = preview_preparation(
            db_session,
            workspace_id=workspace.id,
            spec=DataPrepSpec(operation="prepare", outputs=[{"name": "Preview"}]),
            inputs={"in": {"dataset_id": dataset.id}},
        )
        assert result["cache_hit"] is cached
        assert result["stats"]["value"]["non_finite"] == 3
        assert result["stats"]["value"]["mean"] == 1.0
        assert result["rows"] == [{"value": 1.0}, {"value": None}, {"value": None}, {"value": None}]
        json.dumps(result, allow_nan=False)


def test_preview_cache_isolated_by_sample_and_returns_copies(monkeypatch):
    from types import SimpleNamespace

    from app.services.dataops import preview as previews

    calls = []
    monkeypatch.setattr(
        previews, "_preview", lambda *a, **kw: calls.append(1) or {"rows": [{"id": 1}]}
    )
    compiled = SimpleNamespace(fingerprint=uuid4().hex)
    dataset = SimpleNamespace(
        id=uuid4().hex,
        workspace_id=uuid4().hex,
        version=1,
        lineage_json={"sample": {"key": "sample.parquet", "sha256": "one", "version": 1}},
    )
    first = previews.preview(compiled, {"in": dataset}, None)
    first["rows"][0]["id"] = 99
    second = previews.preview(compiled, {"in": dataset}, None)
    assert second["cache_hit"] and second["rows"] == [{"id": 1}]
    assert len(calls) == 1
    dataset.lineage_json["sample"]["sha256"] = "two"
    assert not previews.preview(compiled, {"in": dataset}, None)["cache_hit"]
    dataset.workspace_id = uuid4().hex
    assert not previews.preview(compiled, {"in": dataset}, None)["cache_hit"]
    assert len(calls) == 3
    compiled.sql = "SELECT id FROM a_different_prefix"
    assert not previews.preview(compiled, {"in": dataset}, None)["cache_hit"]
    assert len(calls) == 4
    later = previews.time.monotonic() + 61
    monkeypatch.setattr(previews.time, "monotonic", lambda: later)
    assert not previews.preview(compiled, {"in": dataset}, None)["cache_hit"]
    assert len(calls) == 5


def test_preview_refuses_legacy_head_even_when_populated():
    from types import SimpleNamespace

    from app.services.dataops.preview import preview

    dataset = SimpleNamespace(lineage_json={}, preview_json=[{"id": 1}])
    with pytest.raises(ValueError, match="DATAPREP_SAMPLE_REQUIRED"):
        preview(None, {"in": dataset}, None)
