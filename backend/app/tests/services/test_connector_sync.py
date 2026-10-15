"""Incremental publication rolls back with its checkpoint; watches retry delivery."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.models.connector_sync import ConnectorSyncState
from app.services import compute_runs
from app.services.connectors import checkpoints, watches
from app.services.connectors.incremental_merge import merge_incremental
from app.tests.services.test_connector_writes import seeded as seeded_fixture

seeded = seeded_fixture


def make_run(db, seed):
    ws, admin, _, conn, _ = seed
    return compute_runs.create_run(
        db,
        workspace_id=ws.id,
        user_id=admin.id,
        connection_id=conn.id,
        operation="import",
        parameters={
            "schema": "public",
            "table": "scores",
            "incremental": {
                "watermark_column": "updated",
                "key_column": "id",
                "type": "integer",
                "overlap": 2,
            },
        },
    )


def test_checkpoint_and_dataset_publication_share_transaction(db_session, seeded):
    run = make_run(db_session, seeded)
    observed = checkpoints.snapshot(db_session, run)
    db_session.commit()
    checkpoints.advance(db_session, run, seeded[4], {"next_checkpoint": [4, 2]})
    db_session.rollback()
    assert db_session.get(ConnectorSyncState, observed["state_id"]).checkpoint is None
    checkpoints.advance(db_session, run, seeded[4], {"next_checkpoint": [4, 2]})
    db_session.commit()
    state = db_session.get(ConnectorSyncState, observed["state_id"])
    assert state.checkpoint == [4, 2] and state.dataset_id == seeded[4].id


def test_late_reader_cannot_regress_checkpoint(db_session, seeded):
    first = make_run(db_session, seeded)
    second = make_run(db_session, seeded)
    checkpoints.snapshot(db_session, first)
    checkpoints.snapshot(db_session, second)
    checkpoints.advance(db_session, first, seeded[4], {"next_checkpoint": [10, 9]})
    db_session.commit()
    with pytest.raises(compute_runs.ComputeRunError, match="CONNECTOR_CHECKPOINT_CONFLICT"):
        checkpoints.advance(db_session, second, seeded[4], {"next_checkpoint": [8, 3]})


def test_client_cannot_supply_uncommitted_watermark(db_session, seeded):
    run = make_run(db_session, seeded)
    run.input_json = {
        **run.input_json,
        "incremental": {**run.input_json["incremental"], "after": [1, 2]},
    }
    with pytest.raises(compute_runs.ComputeRunError, match="CONNECTOR_WATERMARK_INVALID"):
        checkpoints.snapshot(db_session, run)


def test_incremental_merge_retains_old_keys_and_replaces_overlap(tmp_path):
    old = tmp_path / "old.parquet"
    new = tmp_path / "data.parquet"
    pq.write_table(pa.table({"id": [1, 2], "value": ["keep", "old"]}), old)
    pq.write_table(pa.table({"id": [2, 3], "value": ["new", "added"]}), new)
    output = merge_incremental(
        {"row_count": 2},
        tmp_path,
        (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        {"previous_files": [str(old)]},
        "id",
    )
    assert sorted(pq.read_table(new).to_pylist(), key=lambda r: r["id"]) == [
        {"id": 1, "value": "keep"},
        {"id": 2, "value": "new"},
        {"id": 3, "value": "added"},
    ]
    assert (
        output["row_count"] == 3
        and output["increment_rows"] == 2
        and output["deletions_captured"] is False
    )


def test_empty_increment_preserves_prior_typed_dataset_and_checkpoint(tmp_path):
    from app.services.connectors.artifacts import parquet_artifact

    old = tmp_path / "old.parquet"
    expected = pa.table({"id": [1, 2], "value": ["keep", "also keep"]})
    pq.write_table(expected, old)
    (tmp_path / "rows.jsonl").touch()
    deadline = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    output = parquet_artifact(
        {
            "format": "typed-jsonl-v2",
            "columns": ["id", "value"],
            "row_count": 0,
            "next_checkpoint": [10, 2],
        },
        tmp_path,
        deadline,
    )
    merged = merge_incremental(output, tmp_path, deadline, {"previous_files": [str(old)]}, "id")
    table = pq.read_table(tmp_path / "data.parquet")
    assert table.schema == expected.schema
    assert sorted(table.to_pylist(), key=lambda row: row["id"]) == expected.to_pylist()
    assert merged["row_count"] == 2 and merged["increment_rows"] == 0
    assert merged["next_checkpoint"] == [10, 2]


@pytest.mark.parametrize("drift", ["renamed", "reordered", "typed", "nonempty", "previous"])
def test_empty_increment_schema_recovery_does_not_hide_drift(tmp_path, drift):
    from app.services.connectors.adapters.sql import AdapterError

    old = tmp_path / "old.parquet"
    pq.write_table(pa.table({"id": [1], "value": ["keep"]}), old)
    current = pa.table({"id": pa.nulls(0), "value": pa.nulls(0)})
    if drift == "renamed":
        current = current.rename_columns(["id", "changed"])
    elif drift == "reordered":
        current = current.select(["value", "id"])
    elif drift == "typed":
        current = pa.table({"id": pa.array([], type=pa.string()), "value": pa.nulls(0)})
    elif drift == "nonempty":
        current = pa.table({"id": [None], "value": [None]})
    pq.write_table(current, tmp_path / "data.parquet")
    previous = [str(old)]
    if drift == "previous":
        other = tmp_path / "old2.parquet"
        pq.write_table(pa.table({"id": ["changed type"], "value": ["keep"]}), other)
        previous.append(str(other))
    with pytest.raises(AdapterError, match="CONNECTOR_SCHEMA_CHANGED"):
        merge_incremental(
            {"row_count": 0},
            tmp_path,
            (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
            {"previous_files": previous},
            "id",
        )


def test_watch_baseline_then_failed_delivery_does_not_advance(monkeypatch):
    from unittest.mock import Mock

    db = Mock()
    monkeypatch.setattr("app.services.connectors.source_requalification.invalidate", lambda *a: 0)
    watch = SimpleNamespace(
        id="watch",
        workspace_id="workspace",
        connection_id="connection",
        connection_revision=1,
        system_id="system",
        objects=[],
        fingerprint=None,
        sequence=0,
        last_error=None,
        pending_run_id="run",
    )
    first = {"key": "root/a.csv", "etag": "v1", "size": 10}
    run = SimpleNamespace(
        status="succeeded", output_json={"objects": [first], "source_fingerprint": "a" * 64}
    )
    watches._settle(db, watch, run)
    assert watch.fingerprint == "a" * 64 and watch.sequence == 1
    watch.pending_run_id = "next"
    run.output_json = {"objects": [{**first, "etag": "v2"}], "source_fingerprint": "b" * 64}
    monkeypatch.setattr(watches.triggers, "is_event_triggers_enabled", lambda *a, **kw: True)
    emit = Mock(return_value=[{"status": "dispatch_failed"}])
    monkeypatch.setattr(watches.triggers, "emit_event", emit)
    watches._settle(db, watch, run)
    assert watch.fingerprint == "a" * 64 and watch.pending_run_id == "next"
    emit.return_value = [{"status": "dispatched"}]
    watches._settle(db, watch, run)
    assert watch.fingerprint == "b" * 64 and watch.sequence == 2 and watch.pending_run_id is None
    assert emit.call_args.args[0] == "connector.objects_changed"


def test_watch_event_keeps_human_gate_for_side_effects():
    from app.services.run_engine.triggers import evaluate_governance

    flow = {
        "nodes": [
            {"id": "watch", "kind": "source", "type": "source.connector_watch"},
            {"id": "load", "kind": "ingestion", "type": "ingestion"},
        ],
        "edges": [{"from": "watch", "to": "load"}],
    }
    assert evaluate_governance(watches.EVENT, flow).eligible is False


def test_object_change_invalidates_only_source_and_transitive_descendants():
    from app.services.connectors.source_requalification import affected_datasets

    def row(identifier, connection=None, etag=None, parents=None):
        return SimpleNamespace(
            id=identifier,
            parent_ids=parents or [],
            lineage_json={
                "connection_id": connection,
                "source_objects": [{"key": "root/a.csv", "etag": etag}],
            }
            if connection
            else {},
        )

    rows = [
        row("input", "one", "v1"),
        row("fresh", "one", "v2"),
        row("other", "two", "v1"),
        row("derived", parents=["input"]),
        row("scored", parents=["derived"]),
    ]
    roots, affected = affected_datasets(rows, "one", [{"key": "root/a.csv", "etag": "v2"}])
    assert roots == {"input"} and affected == {"input", "derived", "scored"}
