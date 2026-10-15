"""Protocol fixtures: real Avro manifests and Parquet, no server qualification."""

import copy
import hashlib
import io
import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastavro import reader

from app.services.connectors.adapters import iceberg_write as adapter
from app.services.connectors.adapters import lakehouse
from app.services.connectors.adapters.sql import AdapterError


def deadline():
    return (datetime.now(UTC) + timedelta(minutes=5)).isoformat()


CONFIG = {
    "base_url": "https://catalog.example",
    "allowed_origins": ["https://catalog.example"],
    "download_origins": ["https://bucket.s3.us-east-1.amazonaws.com"],
}
SCHEMA = {
    "type": "struct",
    "schema-id": 0,
    "identifier-field-ids": [1],
    "fields": [
        {"id": 1, "name": "id", "required": True, "type": "long"},
        {"id": 2, "name": "value", "required": False, "type": "string"},
    ],
}


@pytest.fixture()
def server(monkeypatch):
    state = {
        "metadata": {
            "format-version": 2,
            "table-uuid": str(uuid4()),
            "location": "s3://bucket/warehouse/table",
            "last-sequence-number": 0,
            "schemas": [SCHEMA],
            "current-schema-id": 0,
            "partition-specs": [{"spec-id": 0, "fields": []}],
            "default-spec-id": 0,
            "sort-orders": [{"order-id": 0, "fields": []}],
            "default-sort-order-id": 0,
            "current-snapshot-id": -1,
            "snapshots": [],
            "refs": {},
        },
        "objects": {},
        "commits": [],
        "conflict": False,
    }

    def get(self, path, *, params=None):
        assert path == "/v1/namespaces/public/tables/scores"
        assert self.headers["X-Iceberg-Access-Delegation"] == "vended-credentials"
        return {"metadata": copy.deepcopy(state["metadata"]), "config": {}}

    def download(location, catalog, config, path, maximum):
        data = state["objects"][location]
        if len(data) > maximum:
            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        path.write_bytes(data)
        return {}, len(data), hashlib.sha256(data).hexdigest()

    def put(catalog, config, location, data):
        assert location not in state["objects"], "immutable files must not be overwritten"
        assert location.startswith("s3://bucket/warehouse/table/")
        state["objects"][location] = data

    def commit(catalog, path, body):
        state["commits"].append(copy.deepcopy(body))
        if state["conflict"]:
            raise AdapterError("CONNECTOR_SOURCE_CHANGED")
        requirements = {r["type"]: r for r in body["requirements"]}
        current = state["metadata"]["current-snapshot-id"]
        assert requirements["assert-ref-snapshot-id"] == {
            "type": "assert-ref-snapshot-id",
            "ref": "main",
            "snapshot-id": current if current != -1 else None,
        }
        assert requirements["assert-table-uuid"]["uuid"] == state["metadata"]["table-uuid"]
        assert requirements["assert-current-schema-id"]["current-schema-id"] == 0
        assert requirements["assert-default-spec-id"]["default-spec-id"] == 0
        assert requirements["assert-default-sort-order-id"]["default-sort-order-id"] == 0
        snapshot = body["updates"][0]["snapshot"]
        assert body["updates"][1] == {
            "action": "set-snapshot-ref",
            "ref-name": "main",
            "type": "branch",
            "snapshot-id": snapshot["snapshot-id"],
        }
        state["metadata"]["snapshots"].append(copy.deepcopy(snapshot))
        state["metadata"]["current-snapshot-id"] = snapshot["snapshot-id"]
        state["metadata"]["last-sequence-number"] = snapshot["sequence-number"]
        return {"metadata": copy.deepcopy(state["metadata"])}

    monkeypatch.setattr(lakehouse.Catalog, "get", get)
    monkeypatch.setattr(lakehouse, "_iceberg_location", download)
    monkeypatch.setattr(adapter, "_iceberg_location", download)
    monkeypatch.setattr(adapter, "_iceberg_client", lambda *args: None)
    monkeypatch.setattr(adapter, "_put", put)
    monkeypatch.setattr(adapter, "_commit", commit)
    return state


def input_contract(tmp_path, rows):
    path = tmp_path / (str(uuid4()) + ".parquet")
    pq.write_table(
        pa.Table.from_pylist(
            rows, schema=pa.schema([pa.field("id", pa.int64()), pa.field("value", pa.string())])
        ),
        path,
    )
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "operation_id": str(uuid4()),
        "contract_digest": "d" * 64,
        "input_sha256": hashlib.sha256(
            json.dumps([sha], separators=(",", ":")).encode()
        ).hexdigest(),
        "input_files": [str(path)],
    }


def invoke(
    server, tmp_path, operation="write_append", rows=None, *, parameters=None, execution=None
):
    execution = execution or input_contract(tmp_path, rows or [{"id": 1, "value": "one"}])
    directory = tmp_path / str(uuid4())
    directory.mkdir()
    current = server["metadata"]["current-snapshot-id"]
    params = {
        "schema": "public",
        "table": "scores",
        "expected_table_uuid": server["metadata"]["table-uuid"],
        "expected_snapshot_id": current if current != -1 else None,
        "expected_schema_id": 0,
        **(parameters or {}),
    }
    return lakehouse.execute(
        operation,
        CONFIG,
        {"token": "private-catalog-token"},
        params,
        deadline(),
        directory,
        dialect="iceberg_rest",
        access={"mode": "read_write"},
        execution=execution,
    )


def rows_current(server):
    metadata = server["metadata"]
    snapshot = next(
        s for s in metadata["snapshots"] if s["snapshot-id"] == metadata["current-snapshot-id"]
    )
    manifests = list(reader(io.BytesIO(server["objects"][snapshot["manifest-list"]])))
    rows = []
    for manifest in manifests:
        source = reader(io.BytesIO(server["objects"][manifest["manifest_path"]]))
        assert source.metadata["format-version"] == "2"
        assert json.loads(source.metadata["schema"])["schema-id"] == 0
        for entry in source:
            assert entry["status"] == 1 and entry["data_file"]["content"] == 0
            table = pq.read_table(io.BytesIO(server["objects"][entry["data_file"]["file_path"]]))
            assert table.schema.field("id").metadata[b"PARQUET:field_id"] == b"1"
            rows.extend(table.to_pylist())
    return sorted(rows, key=lambda r: r["id"])


def test_append_keeps_snapshot_history_and_native_receipts(server, tmp_path):
    first = invoke(server, tmp_path)
    original_objects = dict(server["objects"])
    second = invoke(server, tmp_path, rows=[{"id": 2, "value": "two"}])
    assert rows_current(server) == [{"id": 1, "value": "one"}, {"id": 2, "value": "two"}]
    assert first["snapshot_id"] != second["snapshot_id"] and second["applied"] is True
    assert all(server["objects"][k] == v for k, v in original_objects.items())
    assert "private-catalog-token" not in json.dumps(second)
    assert len(server["metadata"]["snapshots"]) == 2


def test_overwrite_replaces_current_membership_without_deleting_history(server, tmp_path):
    invoke(server, tmp_path)
    old = dict(server["objects"])
    invoke(server, tmp_path, "write_overwrite", [{"id": 3, "value": "three"}])
    assert rows_current(server) == [{"id": 3, "value": "three"}]
    assert all(server["objects"][k] == v for k, v in old.items())


def test_upsert_rewrites_snapshot_typed_and_preserves_nonmatching_rows(server, tmp_path):
    invoke(server, tmp_path, rows=[{"id": 1, "value": "old"}, {"id": 2, "value": "keep"}])
    result = invoke(
        server,
        tmp_path,
        "write_upsert",
        [{"id": 1, "value": "new"}, {"id": 3, "value": None}],
        parameters={"keys": ["id"]},
    )
    assert result["row_count"] == 2
    assert rows_current(server) == [
        {"id": 1, "value": "new"},
        {"id": 2, "value": "keep"},
        {"id": 3, "value": None},
    ]


def test_preview_has_no_remote_mutation_and_exposes_frozen_destination(server, tmp_path):
    execution = input_contract(tmp_path, [{"id": 1, "value": "one"}]) | {
        "write_operation": "write_upsert"
    }
    result = invoke(
        server, tmp_path, "write_preview", parameters={"keys": ["id"]}, execution=execution
    )
    assert result["dry_run"] and result["input_rows"] == 1
    assert result["expected_schema_id"] == 0 and result["expected_snapshot_id"] is None
    assert not server["objects"] and not server["commits"]


@pytest.mark.parametrize(
    "parameters",
    [
        {"expected_snapshot_id": 17},
        {"expected_schema_id": 9},
        {"expected_table_uuid": str(uuid4())},
    ],
)
def test_stale_approval_is_refused_before_upload(server, tmp_path, parameters):
    with pytest.raises(AdapterError, match="CONNECTOR_SOURCE_CHANGED"):
        invoke(server, tmp_path, parameters=parameters)
    assert not server["objects"] and not server["commits"]


def test_conflict_at_commit_never_publishes_or_deletes_any_file(server, tmp_path):
    server["conflict"] = True
    with pytest.raises(AdapterError, match="CONNECTOR_SOURCE_CHANGED"):
        invoke(server, tmp_path)
    assert server["objects"] and not server["metadata"]["snapshots"]
    assert len(server["commits"]) == 1


def test_reconcile_uses_exact_historical_summary_and_never_replays(server, tmp_path):
    execution = input_contract(tmp_path, [{"id": 1, "value": "one"}])
    receipt = invoke(server, tmp_path, execution=execution)
    invoke(server, tmp_path, rows=[{"id": 2, "value": "two"}])
    before = len(server["commits"])
    result = invoke(server, tmp_path, "reconcile_write", execution=execution)
    assert result == receipt and len(server["commits"]) == before
    with pytest.raises(AdapterError, match="CONNECTOR_RECEIPT_MISMATCH"):
        invoke(
            server, tmp_path, "reconcile_write", execution=execution | {"contract_digest": "e" * 64}
        )
    unknown = invoke(
        server, tmp_path, "reconcile_write", execution=execution | {"operation_id": str(uuid4())}
    )
    assert unknown["applied"] is None and len(server["commits"]) == before


def test_unsupported_partitions_and_duplicate_keys_fail_before_upload(server, tmp_path):
    server["metadata"]["partition-specs"][0]["fields"] = [
        {"source-id": 1, "field-id": 1000, "name": "id", "transform": "identity"}
    ]
    with pytest.raises(AdapterError, match="CONNECTOR_ICEBERG_FEATURE_UNSUPPORTED"):
        invoke(server, tmp_path)
    server["metadata"]["partition-specs"][0]["fields"] = []
    with pytest.raises(AdapterError, match="CONNECTOR_UPSERT_DUPLICATE_KEY"):
        invoke(
            server,
            tmp_path,
            "write_upsert",
            [{"id": 1, "value": "a"}, {"id": 1, "value": "b"}],
            parameters={"keys": ["id"]},
        )
    assert not server["objects"] and not server["commits"]


def test_bounded_staging_and_input_hash_precede_remote_mutations(server, tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "MAX_BYTES", 10)
    with pytest.raises(AdapterError, match="CONNECTOR_IMPORT_TOO_LARGE"):
        invoke(server, tmp_path)
    execution = input_contract(tmp_path, [{"id": 1, "value": "one"}]) | {"input_sha256": "a" * 64}
    with pytest.raises(AdapterError, match="CONNECTOR_WRITE_CONTRACT_CHANGED"):
        invoke(server, tmp_path, execution=execution)
    assert not server["objects"] and not server["commits"]


def test_commit_requires_final_200_not_an_async_acceptance(monkeypatch):
    @contextmanager
    def response(*args, **kwargs):
        yield type("Reply", (), {"status_code": 202})()

    monkeypatch.setattr(adapter.http, "response", response)
    catalog = lakehouse.Catalog(CONFIG, {"token": "secret"}, deadline())
    with pytest.raises(AdapterError, match="CONNECTOR_WRITE_OUTCOME_UNKNOWN"):
        adapter._commit(catalog, "/v1/namespaces/public/tables/scores", {})


def test_write_url_cannot_be_derived_from_signed_https_download():
    catalog = lakehouse.Catalog(CONFIG, {"token": "secret"}, deadline())
    with pytest.raises(AdapterError, match="CONNECTOR_STORAGE_SCHEME_UNSUPPORTED"):
        lakehouse._iceberg_client(
            "https://bucket.s3.us-east-1.amazonaws.com/file?sig=secret", catalog, {}
        )
