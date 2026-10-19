"""Real multipart Delta/legacy interoperability, journal authority and streamed export."""

import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.core.config import settings
from app.resources.dataops_storage import PartWriter
from app.services.dataops import storage
from app.services.dataops.exports import stream_dataset
from app.services.tabular_datasets import materialize_dataset, read_frame, read_page, read_rows


@pytest.fixture
def parts(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    monkeypatch.setattr(settings, "dataops_batch_rows", 2)
    key = "workspaces/ws/tabular/datasets/multi/delta"
    root = tmp_path / key
    schema = pa.schema([("id", pa.int64()), ("label", pa.string())])
    writer = PartWriter(root, schema, target_bytes=1)
    for i in range(3):
        writer.write_batch(pa.record_batch([[i * 2, i * 2 + 1], ["a", "b"]], schema=schema))
    writer.close()
    pq.write_table(pa.table({"id": [999], "label": ["orphan"]}), root / "orphan.parquet")
    row = SimpleNamespace(
        id="multi",
        workspace_id="ws",
        storage_key=key,
        lineage_json={},
        version=1,
        row_count=6,
        status="ready",
        size_bytes=writer.size_bytes,
    )
    return row, writer.paths, tmp_path


def test_commit_zero_only_and_no_consolidation(parts, monkeypatch):
    row, originals, root = parts
    manifest = storage.delta_manifest(row)
    assert len(manifest["files"]) == 3
    assert len(storage.dataset_files(row)) == 3
    assert storage.dataset_digest(row) == hashlib.sha256(manifest["log"]).hexdigest()
    copied = materialize_dataset(row, root / "scratch")
    assert len(copied) == 3
    assert sorted(p.read_bytes() for p in copied) == sorted(p.read_bytes() for p in originals)
    monkeypatch.setattr(
        storage, "materialize_files", lambda *a, **k: pytest.fail("lazy reader copied full input")
    )
    arrow = storage.open_dataset_arrow(row)
    assert arrow.count_rows() == 6
    assert sorted(arrow.to_table()["id"].to_pylist()) == list(range(6))
    assert sum(batch.num_rows for batch in storage.iter_dataset_batches(row)) == 6


def test_native_conversion_commits_footer_statistics_without_reencoding(tmp_path):
    from deltalake import DeltaTable

    table = pa.table({"id": [1, 2, 3, 4], "label": [None, "a", "z", None]})
    writer = PartWriter(tmp_path / "native", table.schema, target_bytes=1)
    for batch in table.to_batches(max_chunksize=2):
        writer.write_batch(batch)
    before = {path.name: storage.file_digest(path) for path in writer.paths}
    writer.close()
    assert {path.name: storage.file_digest(path) for path in writer.paths} == before
    log = writer.directory / "_delta_log/00000000000000000000.json"
    original = log.read_bytes()
    actions = [json.loads(line) for line in original.splitlines()]
    commit = next(action["commitInfo"] for action in actions if "commitInfo" in action)
    assert commit["operation"] == "CONVERT"
    assert commit["engineInfo"].startswith("delta-rs:")
    additions = {action["add"]["path"]: action["add"] for action in actions if "add" in action}
    assert set(additions) == set(before)
    for path in writer.paths:
        item = additions[path.name]
        stats = json.loads(item["stats"])
        assert item["size"] == path.stat().st_size
        assert stats["numRecords"] == pq.read_metadata(path).num_rows == 2
        assert stats["nullCount"] == {"id": 0, "label": 1}
        assert stats["minValues"]["id"] in {1, 3}
        assert stats["maxValues"]["id"] in {2, 4}
    assert DeltaTable(writer.directory).version() == 0
    writer.close()
    assert log.read_bytes() == original
    assert [path.name for path in log.parent.glob("*.json")] == [log.name]
    with pytest.raises(ValueError, match="WRITER_CLOSED"):
        writer.write_batch(table.to_batches()[0])


def test_native_empty_output_has_metadata_only_commit_and_profile_sentinel(tmp_path):
    from deltalake import DeltaTable

    schema = pa.schema([("id", pa.int64()), ("label", pa.string())])
    writer = PartWriter(tmp_path / "empty", schema, target_bytes=1)
    writer.close()
    delta = DeltaTable(writer.directory)
    assert delta.version() == 0 and delta.file_uris() == []
    assert delta.to_pyarrow_dataset().count_rows() == 0
    assert [path.name for path in writer.paths] == ["empty-profile.parquet"]
    assert pq.read_schema(writer.paths[0]) == schema
    actions = [
        json.loads(line)
        for line in (writer.directory / "_delta_log/00000000000000000000.json")
        .read_text().splitlines()
    ]
    assert not any("add" in action for action in actions)
    assert next(a["commitInfo"]["engineInfo"] for a in actions if "commitInfo" in a).startswith(
        "delta-rs:"
    )


@pytest.mark.parametrize("foreign", ["parquet", "directory", "symlink"])
def test_native_conversion_refuses_unowned_staging_entries_before_commit(tmp_path, foreign):
    table = pa.table({"id": [1]})
    writer = PartWriter(tmp_path / "output", table.schema, target_bytes=1)
    writer.write_batch(table.to_batches()[0])
    extra = writer.directory / "foreign.parquet"
    if foreign == "parquet":
        pq.write_table(table, extra)
    elif foreign == "directory":
        extra.mkdir()
        pq.write_table(table, extra / "nested.parquet")
    else:
        extra.symlink_to(writer.paths[0])
    with pytest.raises(ValueError, match="STAGING_CHANGED"):
        writer.close()
    assert not (writer.directory / "_delta_log").exists()
    writer.abort()


def test_native_writer_refuses_existing_table_and_abort_publishes_nothing(tmp_path):
    table = pa.table({"id": [1]})
    writer = PartWriter(tmp_path / "output", table.schema, target_bytes=1024**2)
    writer.write_batch(table.to_batches()[0])
    writer.abort()
    writer.close()
    assert pq.read_metadata(writer.paths[0]).num_rows == 1
    assert not (writer.directory / "_delta_log").exists()
    with pytest.raises(ValueError, match="STAGING_NOT_EMPTY"):
        PartWriter(writer.directory, table.schema, target_bytes=1)
    committed = PartWriter(tmp_path / "committed", table.schema, target_bytes=1)
    committed.write_batch(table.to_batches()[0])
    committed.close()
    with pytest.raises(ValueError, match="STAGING_NOT_EMPTY"):
        PartWriter(committed.directory, table.schema, target_bytes=1)


def test_readers_and_work_projection(parts):
    from app.services.work_datasets import read_projected_rows

    row, _, _ = parts
    assert read_frame(row).height == 6
    assert len(read_rows(row, columns=["label"], limit=3)) == 3
    assert len(read_page(row, offset=3, limit=2)["rows"]) == 2
    values, total = read_projected_rows(row, ["id"], 4)
    assert len(values) == 4 and total == 6
    assert all(set(value) == {"id"} for value in values)


@pytest.mark.parametrize("format", ["parquet", "csv"])
def test_export_forward_stream(parts, format):
    row, _, _ = parts
    chunks = stream_dataset(row, format=format)
    first = next(chunks)
    assert first
    content = first + b"".join(chunks)
    frame = (
        pl.read_parquet(io.BytesIO(content))
        if format == "parquet"
        else pl.read_csv(io.BytesIO(content))
    )
    assert sorted(frame["id"].to_list()) == list(range(6))


def test_digest_legacy_bytes_and_previous_delta_identity(parts):
    row, files, root = parts
    legacy = SimpleNamespace(storage_key=str(files[0].relative_to(root)), lineage_json={})
    assert storage.dataset_digest(legacy) == hashlib.sha256(files[0].read_bytes()).hexdigest()
    previous = hashlib.sha256(
        json.dumps({"log": storage.dataset_digest(row), "parts": {}}, sort_keys=True).encode()
    ).hexdigest()
    assert storage.dataset_digest_matches(row, previous)
    assert not storage.dataset_digest_matches(row, "f" * 64)


@pytest.mark.parametrize(
    "mutation", ["remove", "writer3", "duplicate", "traversal", "mapping", "second_commit"]
)
def test_refuse_mutable_or_unsupported_journal(parts, mutation):
    row, _, root = parts
    log = root / row.storage_key / "_delta_log/00000000000000000000.json"
    actions = [json.loads(line) for line in log.read_text().splitlines()]
    protocol = next(action["protocol"] for action in actions if "protocol" in action)
    metadata = next(action["metaData"] for action in actions if "metaData" in action)
    added = next(action for action in actions if "add" in action)
    if mutation == "remove":
        actions.append({"remove": {"path": "other.parquet"}})
    if mutation == "writer3":
        protocol["minWriterVersion"] = 3
    if mutation == "duplicate":
        actions.append(added)
    if mutation == "traversal":
        added["add"]["path"] = "../foreign.parquet"
    if mutation == "mapping":
        metadata["configuration"]["delta.columnMapping.mode"] = "name"
    if mutation == "second_commit":
        (log.parent / "00000000000000000001.json").write_text("{}")
    log.write_text("\n".join(json.dumps(action) for action in actions))
    with pytest.raises(ValueError):
        storage.open_dataset_arrow(row)


def test_corrupt_committed_part_is_rejected(parts):
    row, files, root = parts
    row.lineage_json = {"storage": {"parts": {p.name: storage.file_digest(p) for p in files}}}
    files[0].write_bytes(b"x" * files[0].stat().st_size)
    with pytest.raises(ValueError, match="INTEGRITY"):
        materialize_dataset(row, root / "copy")


def test_manifests_and_harnesses_preserve_three_paths(parts, tmp_path):
    import duckdb

    from app.resources.dbt_harness import _load_inputs
    from app.services import tabular_dbt, tabular_polars
    from app.services.dataops.sql_execution import write_manifest

    row, _, _ = parts
    source = SimpleNamespace(dataset=row, view="records")
    for kind in ("sql", "polars", "dbt"):
        scratch = tmp_path / kind
        scratch.mkdir()
        if kind == "sql":
            manifest = write_manifest(scratch, [source], sql="SELECT * FROM records")
            paths = manifest["views"][0]["paths"]
        elif kind == "polars":
            manifest = tabular_polars._write_manifest(scratch, [source], row_limit=100)
            paths = manifest["inputs"]["records"]
        else:
            manifest = tabular_dbt._write_manifest(scratch, [source], {}, row_limit=100)
            paths = manifest["sources"]["records"]
            db = str(scratch / "test.duckdb")
            _load_inputs(duckdb, db, manifest["sources"])
            with duckdb.connect(db) as connection:
                assert connection.execute("SELECT count(*) FROM records").fetchone()[0] == 6
                assert connection.execute("SELECT count(*) FROM input").fetchone()[0] == 6
        assert len(paths) == 3 and pl.read_parquet(paths).height == 6


def test_actual_parquet_footer_and_commit_must_match_before_upload(parts, db_session):
    from app.models.workspace import Workspace
    from app.services.tabular_datasets import reserve_frame

    row, paths, root = parts
    workspace = Workspace(id="ws", name="Integrity", slug="integrity", settings={})
    db_session.add(workspace)
    db_session.commit()
    target = reserve_frame(db_session, workspace_id="ws", name="Wrong count", commit=False)
    with pytest.raises(ValueError, match="CARDINALITY"):
        storage.settle_files(
            db_session,
            target,
            paths,
            delta_root=root / row.storage_key,
            profile={
                "row_count": 7,
                "column_count": 2,
                "schema": [{"name": "id"}, {"name": "label"}],
            },
        )
    assert target.status == "ingesting" and target.storage_key is None
    assert not storage.get_object_store().exists(
        f"workspaces/ws/tabular/datasets/{target.id}/delta/_delta_log/00000000000000000000.json"
    )


def test_bounded_profile_matches_legacy_stats(parts):
    from app.services.tabular_datasets import profile_frame

    _, paths, _ = parts
    expected = profile_frame(pl.read_parquet(paths))
    profile = storage.profile_files(paths)
    assert profile["row_count"] == expected["row_count"]
    assert profile["schema"] == expected["schema"]
    for name, details in expected["stats"].items():
        for key, value in details.items():
            if key not in {"histogram", "top_values"}:
                # The committed file order may differ from discovery order;
                # DuckDB and Polars also accumulate floating aggregates with
                # different algorithms. Counts and non-floats stay exact.
                assert profile["stats"][name][key] == (
                    pytest.approx(value, rel=1e-12, abs=1e-12)
                    if isinstance(value, float) else value
                )
    assert profile["stats"]["id"]["histogram"] == expected["stats"]["id"]["histogram"]
    assert profile["preview"] == expected["preview"]


def test_bounded_profile_counts_duplicates_and_nulls_exactly(tmp_path):
    from app.services.tabular_datasets import profile_frame

    frame = pl.DataFrame({"n": [2, None, 1, 2], "s": ["z", None, "a", "z"]})
    table = frame.to_arrow()
    writer = PartWriter(tmp_path / "nullable", table.schema, target_bytes=1)
    for _ in range(3):
        writer.write_batch(table.to_batches()[0])
    writer.close()
    expected = profile_frame(pl.concat([frame] * 3))
    actual = storage.profile_files(writer.paths)
    assert actual["preview"] == expected["preview"]
    for column in frame.columns:
        for statistic in ("nulls", "null_ratio", "distinct"):
            assert actual["stats"][column][statistic] == expected["stats"][column][statistic]


def test_real_ml_harness_reads_multipart_without_single_file_fallback(tmp_path):
    import subprocess
    import sys

    from app.tests.services.test_ml_training import _manifest_for

    schema = pa.schema([("x", pa.float64()), ("y", pa.float64())])
    writer = PartWriter(tmp_path / "delta", schema, target_bytes=1)
    for i in range(3):
        x = [float(n) for n in range(i * 40, (i + 1) * 40)]
        writer.write_batch(pa.record_batch([x, [v * 3 + 1 for v in x]], schema=schema))
    writer.close()
    manifest = _manifest_for(
        tmp_path / "must-not-read.parquet",
        tmp_path,
        task="regression",
        target="y",
        features=["x"],
        estimator="sklearn.linear_model.LinearRegression",
        params={},
        min_rows=40,
        curve_points=10,
        data_paths=[str(p) for p in writer.paths],
    )
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    result = tmp_path / "result.json"
    run = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[2] / "resources/ml_train_harness.py"),
            str(tmp_path / "manifest.json"),
            str(result),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        env={**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
    )
    assert run.returncode == 0, run.stderr[-2000:]
    summary = json.loads(result.read_text())
    assert summary["metrics"]["primary"]["value"] > 0.99


def test_protocol_one_writer_canonicalizes_naive_timestamps(tmp_path):
    from datetime import datetime

    schema = pa.schema([("at", pa.timestamp("us"))])
    writer = PartWriter(tmp_path / "delta-time", schema, target_bytes=128 * 1024**2)
    writer.write_batch(pa.record_batch([[datetime(2026, 10, 13)]], schema=schema))
    writer.close()
    from deltalake import DeltaTable

    table = DeltaTable(str(writer.directory)).to_pyarrow_table()
    assert table.schema.field("at").type.tz == "UTC"
    assert table["at"][0].as_py().hour == 0


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
@pytest.mark.parametrize("zone", [None, "UTC", "Europe/Paris"])
def test_protocol_one_timestamp_parts_match_committed_schema(tmp_path, unit, zone):
    from deltalake import DeltaTable, Schema

    scale = {"s": 1, "ms": 1000, "us": 1_000_000, "ns": 1_000_000_000}[unit]
    epoch_seconds = 1_720_000_000
    values = pa.array([epoch_seconds * scale, None], type=pa.timestamp(unit, tz=zone))
    batch = pa.record_batch([values], names=["at"])
    writer = PartWriter(tmp_path / "timestamp", batch.schema, target_bytes=128 * 1024**2)
    writer.write_batch(batch)
    writer.close()

    committed = DeltaTable(writer.directory)
    parquet_schema = Schema.from_arrow(pq.read_schema(writer.paths[0]))
    assert json.loads(parquet_schema.to_json()) == json.loads(committed.schema().to_json())
    table = committed.to_pyarrow_table()
    assert table.schema.field("at").type == pa.timestamp("us", tz="UTC")
    assert table["at"].cast(pa.int64()).to_pylist() == [epoch_seconds * 1_000_000, None]


def test_protocol_one_writer_refuses_nanosecond_loss_before_publication(tmp_path):
    values = pa.array([1001], type=pa.timestamp("ns", tz="UTC"))
    batch = pa.record_batch([values], names=["at"])
    writer = PartWriter(tmp_path / "too-precise", batch.schema, target_bytes=128 * 1024**2)
    with pytest.raises(pa.ArrowInvalid, match="lose data"):
        writer.write_batch(batch)
    writer.abort()
    assert writer.paths == []
    assert not (writer.directory / "_delta_log").exists()


def test_wide_sample_is_uniform_seeded_and_within_byte_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "dataops_sample_rows", 10000)
    schema = pa.schema([("id", pa.int64()), ("payload", pa.binary(4096))])
    path = tmp_path / "wide.parquet"
    with pq.ParquetWriter(path, schema) as writer:
        for offset in range(0, 4000, 1000):
            writer.write_batch(
                pa.record_batch(
                    [list(range(offset, offset + 1000)), [b"x" * 4096] * 1000], schema=schema
                )
            )
    row = SimpleNamespace(id="wide", workspace_id="ws", lineage_json={})
    storage.persist_sample(row, [path])
    sample = row.lineage_json["sample"]
    assert 0 < sample["rows"] < 4000
    assert sample["size_bytes"] < 16 * 1024**2
    table = pq.read_table(storage.get_object_store()._local_path(sample["key"]))
    assert table.nbytes <= 8 * 1024**2
    identifiers = table["id"].to_pylist()
    assert identifiers != list(range(sample["rows"]))
    assert min(identifiers) < 100 and max(identifiers) > 3900
    assert sample["method"] == "reservoir_seeded" and sample["seed"] == 42
    repeated = SimpleNamespace(id="wide-repeat", workspace_id="ws", lineage_json={})
    storage.persist_sample(repeated, [path])
    repeat = pq.read_table(
        storage.get_object_store()._local_path(repeated.lineage_json["sample"]["key"])
    )
    assert repeat["id"].to_pylist() == identifiers


@pytest.mark.parametrize("delta", [False, True])
def test_frame_writer_flag_sample_and_immutable_version(db_session, tmp_path, monkeypatch, delta):
    from app.models.workspace import Workspace
    from app.services.tabular_datasets import TabularError, register_frame

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", delta)
    workspace = Workspace(id="immutable", name="Immutable", slug="immutable", settings={})
    db_session.add(workspace)
    db_session.commit()
    row = register_frame(
        db_session, workspace_id=workspace.id, name="Version", frame=pl.DataFrame({"id": [1, 2]})
    )
    db_session.commit()
    assert row.storage_key.endswith("/delta" if delta else "/data.parquet")
    assert row.lineage_json["sample"]["rows"] == 2
    initial = storage.dataset_digest(row)
    with pytest.raises(TabularError, match="reserved dataset"):
        register_frame(
            db_session,
            workspace_id=workspace.id,
            name="Version",
            frame=pl.DataFrame({"id": [999]}),
            into=row,
        )
    assert storage.dataset_digest(row) == initial


def test_ingest_redelivery_does_not_write_the_active_version(db_session, monkeypatch):
    from app.models.workspace import Workspace
    from app.services import tabular_datasets

    workspace = Workspace(id="redelivery", name="Redelivery", slug="redelivery", settings={})
    db_session.add(workspace)
    db_session.commit()
    row = tabular_datasets.reserve_frame(
        db_session, workspace_id=workspace.id, name="Active", source="upload"
    )
    monkeypatch.setattr(
        tabular_datasets, "mark_step", lambda *args, **kwargs: pytest.fail("second writer claimed")
    )
    assert tabular_datasets.ingest_dataset(row.id) == {"id": row.id, "status": "ingesting"}
    db_session.refresh(row)
    assert row.status == "ingesting"
