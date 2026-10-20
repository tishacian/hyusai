"""Native Delta transactions with a conditional object-store surrogate."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from deltalake import DeltaTable

from app.services.connectors.adapters import delta_export
from app.services.connectors.adapters.sql import AdapterError


class Store:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.downloads = []
        self.lose = False
        self.conflict = False

    def list_page(self, prefix, cursor=None):
        return [
            {"key": key, "size": len(value), "etag": hashlib.sha256(value).hexdigest()}
            for key, value in self.objects.items()
            if key.startswith(prefix)
        ], None

    def download(self, item, path, max_bytes):
        data = self.objects[item["key"]]
        assert hashlib.sha256(data).hexdigest() == item["etag"]
        assert len(data) <= max_bytes
        self.downloads.append(item["key"])
        path.write_bytes(data)
        return {}, len(data), item["etag"]

    def put(self, key, data, *, expected_etag=None):
        assert expected_etag is None
        self.writes.append(key)
        if key in self.objects or (self.conflict and "/_delta_log/" in key):
            raise AdapterError("CONNECTOR_PRECONDITION_FAILED")
        self.objects[key] = data
        if self.lose and "/_delta_log/" in key:
            raise OSError("response lost after storing committed log")
        return hashlib.sha256(data).hexdigest()


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    store = Store()
    monkeypatch.setattr(delta_export, "client_for", lambda *args: store)
    sequence = [0]

    def invocation(values, mode="append", operation_id=None):
        sequence[0] += 1
        directory = tmp_path / str(sequence[0])
        directory.mkdir()
        path = directory / "input.parquet"
        pq.write_table(pa.table({"id": values}), path)
        hashes = [hashlib.sha256(path.read_bytes()).hexdigest()]
        execution = {
            "operation_id": operation_id or str(uuid4()),
            "input_files": [str(path)],
            "input_sha256": hashlib.sha256(
                json.dumps(hashes, separators=(",", ":")).encode()
            ).hexdigest(),
            "contract_digest": "a" * 64,
        }
        args = (
            {"prefix": "root"},
            {},
            {"prefix": "root/table", "format": "delta", "mode": mode},
            (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            directory,
        )
        return args, execution

    return store, invocation


def published(store, tmp_path, version=None):
    directory = tmp_path / str(uuid4())
    directory.mkdir()
    for key, data in store.objects.items():
        path = directory / Path(key).relative_to("root/table")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return DeltaTable(str(directory), version=version).to_pyarrow_table().column("id").to_pylist()


def test_native_append_commits_next_version_after_immutable_parts(prepared, tmp_path):
    store, invocation = prepared
    args, execution = invocation([1, 2])
    first = delta_export.execute(*args, dialect="s3", execution=execution)
    assert first["applied"] and first["delta_version"] == 0 and first["row_count"] == 2
    assert store.writes[-1].endswith("/00000000000000000000.json")
    args, execution = invocation([3])
    second = delta_export.execute(*args, dialect="s3", execution=execution)
    assert second["delta_version"] == 1
    assert sorted(published(store, tmp_path)) == [1, 2, 3]
    assert all("/_delta_log/" in key for key in store.downloads)


def test_overwrite_retains_old_parts_and_time_travel(prepared, tmp_path):
    store, invocation = prepared
    args, execution = invocation([1, 2])
    delta_export.execute(*args, dialect="s3", execution=execution)
    previous = dict(store.objects)
    args, execution = invocation([7], "overwrite")
    receipt = delta_export.execute(*args, dialect="s3", execution=execution)
    assert receipt["delta_version"] == 1
    assert all(store.objects[key] == value for key, value in previous.items())
    assert published(store, tmp_path) == [7]
    assert sorted(published(store, tmp_path, version=0)) == [1, 2]


def test_concurrent_log_conflict_never_overwrites_or_retries(prepared):
    store, invocation = prepared
    store.conflict = True
    args, execution = invocation([1])
    with pytest.raises(AdapterError, match="PRECONDITION_FAILED"):
        delta_export.execute(*args, dialect="s3", execution=execution)
    assert sum("/_delta_log/" in key for key in store.writes) == 1
    assert not any("/_delta_log/" in key for key in store.objects)


def test_lost_commit_reply_reconciles_exact_contract_without_mutation(prepared, tmp_path):
    store, invocation = prepared
    store.lose = True
    args, execution = invocation([1, 2])
    with pytest.raises(OSError):
        delta_export.execute(*args, dialect="s3", execution=execution)
    count = len(store.writes)
    directory = tmp_path / "reconcile"
    directory.mkdir()
    receipt = delta_export.reconcile(*args[:4], directory, dialect="s3", execution=execution)
    assert (
        receipt["applied"]
        and receipt["reconciled"]
        and receipt["contract_digest"] == execution["contract_digest"]
    )
    assert receipt["delta_version"] == 0
    assert len(store.writes) == count


def test_missing_commit_is_unknown_and_never_replayed(prepared):
    store, invocation = prepared
    args, execution = invocation([1])
    assert delta_export.reconcile(*args, dialect="s3", execution=execution)["outcome"] == "unknown"
    assert not store.writes


def test_forged_matching_operation_id_with_different_contract_refused(prepared, tmp_path):
    store, invocation = prepared
    args, execution = invocation([1])
    delta_export.execute(*args, dialect="s3", execution=execution)
    directory = tmp_path / "lookup"
    directory.mkdir()
    with pytest.raises(AdapterError, match="IDEMPOTENCY_CONFLICT"):
        delta_export.reconcile(
            *args[:4], directory, dialect="s3", execution={**execution, "contract_digest": "b" * 64}
        )
