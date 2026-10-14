"""Opt-in real MinIO qualification. D3_MINIO_SESSION points to a private fixture directory."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import boto3
import pyarrow as pa
import pytest
from botocore.exceptions import ClientError

from app.core.config import settings
from app.models.workspace import Workspace
from app.resources.dataops_storage import PartWriter
from app.services.dataops import storage
from app.services.object_store import get_object_store
from app.services.tabular_datasets import reserve_frame


@pytest.fixture
def minio(monkeypatch):
    location = os.environ.get("D3_MINIO_SESSION")
    if not location:
        pytest.skip("real MinIO fixture is explicitly opt-in")
    root = Path(location)
    cfg = json.loads((root / "container.json").read_text())
    secret = json.loads((root / "credentials.json").read_text())
    for key, value in {
        "object_store_backend": "s3",
        "object_store_s3_endpoint_url": cfg["endpoint"],
        "object_store_s3_bucket": "d3-qualification",
        "object_store_s3_access_key": secret["app_user"],
        "object_store_s3_secret_key": secret["app_secret"],
    }.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setenv("HF_TABULAR_PURGE_ACCESS_KEY", secret["purge_user"])
    monkeypatch.setenv("HF_TABULAR_PURGE_SECRET_KEY", secret["purge_secret"])

    def client(role):
        return boto3.client(
            "s3",
            endpoint_url=cfg["endpoint"],
            aws_access_key_id=secret[role + "_user"],
            aws_secret_access_key=secret[role + "_secret"],
        )

    return client


def test_real_minio_conditional_commit_race_and_purge_identity(minio):
    key = f"workspaces/ws/tabular/datasets/{uuid4()}/delta/_delta_log/00000000000000000000.json"

    def put(index):
        try:
            get_object_store().write_once(key, str(index).encode())
            return "won"
        except ClientError as exc:
            assert exc.response["ResponseMetadata"]["HTTPStatusCode"] in {409, 412}
            return "lost"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(put, range(8)))
    assert results.count("won") == 1
    with pytest.raises(ClientError) as refused:
        minio("app").delete_object(Bucket="d3-qualification", Key=key)
    assert refused.value.response["Error"]["Code"] == "AccessDenied"
    versions = (
        minio("purge")
        .list_object_versions(Bucket="d3-qualification", Prefix=key)
        .get("Versions", [])
    )
    assert len(versions) == 1
    for version in versions:
        minio("purge").delete_object(
            Bucket="d3-qualification", Key=key, VersionId=version["VersionId"]
        )
    foreign = "workspaces/ws/knowledge-collections/private/data.bin"
    with pytest.raises(ClientError) as refused:
        minio("purge").delete_object(Bucket="d3-qualification", Key=foreign)
    assert refused.value.response["Error"]["Code"] == "AccessDenied"


def test_real_minio_dedicated_adapter_removes_versions_and_delete_markers(minio):
    from scripts.purge_tabular_dataset import deletion_adapter

    prefix = f"workspaces/ws/tabular/datasets/{uuid4()}/"
    key = prefix + "data.parquet"
    app = minio("app")
    for payload in (b"first", b"second"):
        app.put_object(Bucket="d3-qualification", Key=key, Body=payload)
    purge = minio("purge")
    purge.delete_object(Bucket="d3-qualification", Key=key)
    before = purge.list_object_versions(Bucket="d3-qualification", Prefix=prefix)
    assert len(before["Versions"]) == 2 and len(before["DeleteMarkers"]) == 1
    remove = deletion_adapter()
    assert remove(prefix) == 3
    after = purge.list_object_versions(Bucket="d3-qualification", Prefix=prefix)
    assert not after.get("Versions") and not after.get("DeleteMarkers")
    assert remove(prefix) == 0


def test_real_minio_writer_sample_profile_and_lazy_journal_reader(minio, db_session, tmp_path):
    workspace = Workspace(
        id=str(uuid4()), name="MinIO qualification", slug="minio-qualification", settings={}
    )
    db_session.add(workspace)
    db_session.commit()
    dataset = reserve_frame(db_session, workspace_id=workspace.id, name="Multipart", commit=False)
    schema = pa.schema([("id", pa.int64()), ("label", pa.string())])
    writer = PartWriter(tmp_path / "delta", schema, target_bytes=1)
    for i in range(3):
        writer.write_batch(pa.record_batch([[i * 2, i * 2 + 1], ["a", "b"]], schema=schema))
    writer.close()
    storage.settle_files(db_session, dataset, writer.paths, delta_root=writer.directory)
    db_session.commit()
    assert dataset.status == "ready" and dataset.row_count == 6
    assert len(storage.dataset_files(dataset)) == 3
    assert get_object_store().exists(dataset.lineage_json["sample"]["key"])
    get_object_store().write_bytes(dataset.storage_key + "/orphan.parquet", b"not a parquet")
    arrow = storage.open_dataset_arrow(dataset)
    assert arrow.count_rows() == 6
    assert sorted(arrow.to_table()["id"].to_pylist()) == list(range(6))
    copies = storage.materialize_files(dataset, tmp_path / "readback")
    assert len(copies) == 3
    assert [storage.file_digest(p) for p in copies] == [
        storage.file_digest(p) for p in writer.paths
    ]


def test_real_minio_multi_output_failure_never_publishes_partial_set(
    minio, db_session, monkeypatch
):
    import polars as pl

    from app.models.tabular import TabularDataset
    from app.services.dataops.preparation import submit_preparation
    from app.services.object_store import ObjectStore
    from app.services.tabular_datasets import register_frame

    workspace = Workspace(id=str(uuid4()), name="MinIO atomic", slug="minio-atomic", settings={})
    db_session.add(workspace)
    db_session.commit()
    monkeypatch.setattr(settings, "dataops_enabled", True)
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    source = register_frame(
        db_session, workspace_id=workspace.id, name="Source", frame=pl.DataFrame({"id": range(30)})
    )
    db_session.commit()
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", True)
    original = ObjectStore.write_once
    committed = []

    def fail_second(self, key, content):
        if key.endswith("00000000000000000000.json"):
            if committed:
                raise RuntimeError("controlled second commit transport failure")
            committed.append(key)
        return original(self, key, content)

    monkeypatch.setattr(ObjectStore, "write_once", fail_second)
    execution = submit_preparation(
        db_session,
        workspace_id=workspace.id,
        spec={
            "operation": "split",
            "params": {"keys": ["id"], "ratios": [0.5, 0.5]},
            "outputs": [{"name": "First", "port": "a"}, {"name": "Second", "port": "b"}],
        },
        inputs={"in": {"dataset_id": source.id}},
    )
    assert execution.status == "failed"
    assert len(committed) == 1 and get_object_store().exists(committed[0])
    targets = [
        db_session.get(TabularDataset, identifier)
        for identifier in execution.input_json["outputs"].values()
    ]
    assert all(row.status == "failed" for row in targets)
    assert all(row.storage_key is None for row in targets)
