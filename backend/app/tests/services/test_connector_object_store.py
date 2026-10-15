"""Imports freeze source identities; conditional writes protect immutable versions."""

import base64
from datetime import UTC, datetime, timedelta

import pytest

from app.services.connectors.adapters import object_store as adapter
from app.services.connectors.adapters.object_clients import (
    AzureClient,
    GCSClient,
    S3Client,
    object_key,
)
from app.services.connectors.adapters.sql import AdapterError


def deadline():
    return (datetime.now(UTC) + timedelta(minutes=1)).isoformat()


def item(key="root/a.csv", size=22, etag='"v1"'):
    return dict(key=key, size=size, etag=etag)


class Store:
    def __init__(self, items, content=b"id,name\n1,Alice\n2,Bob\n"):
        self.items, self.content, self.downloads = items, content, []

    def list_page(self, prefix, cursor=None):
        return [r for r in self.items if r["key"].startswith(prefix)], None

    def download(self, item, path, max_bytes):
        self.downloads.append(item)
        path.write_bytes(self.content)
        return {}, len(self.content), "d" * 64


def execute(monkeypatch, path, operation, store, parameters=None):
    monkeypatch.setattr(adapter, "client_for", lambda *args: store)
    return adapter.execute(
        operation, {"prefix": "root"}, {}, parameters or {}, deadline(), path, dialect="s3"
    )


def test_import_has_frozen_identity_and_streamed_rows(monkeypatch, tmp_path):
    result = execute(monkeypatch, tmp_path, "import", Store([item()]))
    assert result["row_count"] == 2 and result["columns"] == ["id", "name"]
    assert result["source_objects"][0]["etag"] == '"v1"'
    assert result["format"] == "typed-jsonl-v2"
    assert (tmp_path / "rows.jsonl").read_text().splitlines() == ['["1", "Alice"]', '["2", "Bob"]']
    assert not (tmp_path / "object-0").exists()


def test_json_object_import_preserves_literal_typed_tags(monkeypatch, tmp_path):
    import pyarrow.parquet as pq

    from app.services.connectors.artifacts import parquet_artifact

    result = execute(
        monkeypatch,
        tmp_path,
        "import",
        Store([item("root/a.ndjson")], b'{"document":{"type":"date","value":"2026-10-14"}}\n'),
    )
    parquet_artifact(result, tmp_path, deadline())
    assert pq.read_table(tmp_path / "data.parquet").to_pylist() == [
        {"document": {"type": "date", "value": "2026-10-14"}}
    ]


def test_source_change_aborts(monkeypatch, tmp_path):
    store = Store([item()])

    def changed(*args):
        raise AdapterError("CONNECTOR_SOURCE_CHANGED")

    store.download = changed
    with pytest.raises(AdapterError, match="CONNECTOR_SOURCE_CHANGED"):
        execute(monkeypatch, tmp_path, "import", store)


@pytest.mark.parametrize("key", ["other/a", "root/../secret", "/root/a", "root/./a", "root\\a"])
def test_root_boundary(key):
    with pytest.raises(AdapterError):
        object_key(key, "root")


def test_manifest_limits_before_download(monkeypatch, tmp_path):
    store = Store([item(size=2048)])
    with pytest.raises(AdapterError, match="CONNECTOR_IMPORT_TOO_LARGE"):
        execute(monkeypatch, tmp_path, "import", store, {"max_bytes": 1024})
    assert not store.downloads


def test_changed_schema_aborts(monkeypatch, tmp_path):
    with pytest.raises(AdapterError, match="CONNECTOR_SCHEMA_CHANGED"):
        execute(
            monkeypatch, tmp_path, "import", Store([item("root/a.ndjson")], b'{"a":1}\n{"b":2}\n')
        )


def test_watch_compares_manifest_without_download(monkeypatch, tmp_path):
    store = Store([item()])
    first = execute(monkeypatch, tmp_path, "watch", store)
    second = execute(
        monkeypatch, tmp_path, "watch", store, {"previous_fingerprint": first["source_fingerprint"]}
    )
    assert first["changed"] and not second["changed"] and not store.downloads


def test_delta_log_is_detected(monkeypatch, tmp_path):
    with pytest.raises(AdapterError, match="CONNECTOR_TABLE_FORMAT_REQUIRES_NATIVE_READER"):
        execute(monkeypatch, tmp_path, "import", Store([item("root/table.metadata.json")]))


def test_s3_read_is_conditional_and_signed(monkeypatch, tmp_path):
    client = S3Client(
        {"bucket": "test", "prefix": "root"},
        {"access_key": "fixture", "secret_key": "secret"},
        deadline(),
    )
    calls = []
    monkeypatch.setattr(
        "app.services.connectors.adapters.object_clients.http.download",
        lambda *a, **kw: calls.append((a, kw)) or ({}, 22, "d" * 64),
    )
    client.download(item(), tmp_path / "object", 100)
    assert calls[0][1]["headers"]["If-Match"] == '"v1"'
    assert "Authorization" in calls[0][1]["headers"] and "secret" not in calls[0][0][0]


def test_s3_creation_and_pointer_update_use_preconditions(monkeypatch):
    client = S3Client(
        {"bucket": "test", "prefix": "root"},
        {"access_key": "fixture", "secret_key": "secret"},
        deadline(),
    )
    calls = []
    monkeypatch.setattr(
        "app.services.connectors.adapters.object_clients.http.request",
        lambda *a, **kw: calls.append((a, kw)) or ({"etag": "next"}, b""),
    )
    client.put("root/versions/op/part", b"data")
    client.put("root/_LATEST.json", b"pointer", expected_etag="old")
    assert calls[0][1]["headers"]["If-None-Match"] == "*"
    assert (
        calls[1][1]["headers"]["If-Match"] == "old"
        and "If-None-Match" not in calls[1][1]["headers"]
    )


def test_azure_shared_key_stays_out_of_url():
    client = AzureClient(
        {"bucket": "test", "account": "fixture"},
        {"account_key": base64.b64encode(b"x" * 32).decode()},
        deadline(),
    )
    url, headers = client.signed("PUT", "data.csv", content=b"ab", create=True)
    assert "?" not in url and headers["If-None-Match"] == "*"
    assert (
        headers["Authorization"].startswith("SharedKey fixture:")
        and headers["Content-Length"] == "2"
    )


def test_gcs_download_pins_generation(monkeypatch, tmp_path):
    client = object.__new__(GCSClient)
    client.base, client.bucket, client.root, client.token, client.deadline = (
        "https://storage.googleapis.com",
        "test",
        "root",
        "fixture",
        deadline(),
    )
    calls = []
    monkeypatch.setattr(
        "app.services.connectors.adapters.object_clients.http.download",
        lambda *a, **kw: calls.append((a, kw)) or ({}, 22, "d" * 64),
    )
    client.download({**item(), "generation": "123"}, tmp_path / "object", 100)
    assert "generation=123" in calls[0][0][0] and "ifGenerationMatch=123" in calls[0][0][0]


def test_extra_csv_fields_are_not_dropped(tmp_path):
    path = tmp_path / "bad"
    path.write_text("a,b\n1,2,3\n")
    with pytest.raises(AdapterError, match="CONNECTOR_SCHEMA_INVALID"):
        list(adapter.iter_rows(path, "a.csv"))


def test_json_object_is_not_silently_imported_as_an_empty_array(tmp_path):
    path = tmp_path / "object.json"
    path.write_text('{"id": 1}')
    with pytest.raises(AdapterError):
        list(adapter.iter_rows(path, "object.json"))


def test_reader_follows_committed_manifest_not_older_version_parts():
    import hashlib
    import json
    from uuid import uuid4

    from app.services.connectors.adapters.object_manifest import published_objects

    operation_id = str(uuid4())
    part_key = f"root/v={operation_id}/part-000000.parquet"
    manifest_key = f"root/v={operation_id}/manifest.json"
    body = json.dumps(
        {
            "operation_id": operation_id,
            "parts": [{"key": part_key, "bytes": 22, "sha256": "a" * 64}],
        }
    ).encode()
    pointer = json.dumps(
        {
            "operation_id": operation_id,
            "manifest": manifest_key,
            "sha256": hashlib.sha256(body).hexdigest(),
        }
    ).encode()
    objects = {"root/_LATEST.json": pointer, manifest_key: body}

    class Client:
        def read_small(self, key):
            return objects[key], "etag"

    listing = [item(part_key), item("root/v=old/unreferenced.parquet"), item("root/_LATEST.json")]
    result = published_objects(Client(), "root", listing)
    assert result == [item(part_key) | {"expected_sha256": "a" * 64}]
    objects[manifest_key] = body + b" "
    with pytest.raises(AdapterError, match="CONNECTOR_MANIFEST_INVALID"):
        published_objects(Client(), "root", listing)


def test_empty_export_is_refused_before_any_remote_access(monkeypatch, tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from app.services.connectors.adapters import object_export

    source = tmp_path / "empty.parquet"
    pq.write_table(pa.table({"id": pa.array([], type=pa.int64())}), source)
    monkeypatch.setattr(object_export, "client_for", lambda *args: pytest.fail("remote access"))
    with pytest.raises(AdapterError, match="CONNECTOR_EMPTY_EXPORT_UNSUPPORTED"):
        object_export.execute(
            {"prefix": "root"},
            {},
            {},
            deadline(),
            dialect="s3",
            execution={"input_files": [str(source)]},
        )


def test_export_publishes_pointer_last_and_reconciles_without_mutation(monkeypatch, tmp_path):
    from uuid import uuid4

    import pyarrow as pa
    import pyarrow.parquet as pq

    from app.services.connectors.adapters import object_export

    operation_id = str(uuid4())
    source = tmp_path / "input.parquet"
    pq.write_table(pa.table({"id": [1, 2]}), source)
    objects = {}
    calls = []

    class Target:
        def put(self, key, data, expected_etag=None):
            assert key not in objects
            calls.append(key)
            objects[key] = data
            return "new-etag"

        def read_small(self, key):
            return objects[key], "new-etag"

    monkeypatch.setattr(object_export, "client_for", lambda *a: Target())
    result = object_export.execute(
        {"prefix": "root"},
        {},
        {"prefix": "root/export"},
        deadline(),
        dialect="s3",
        execution={
            "operation_id": operation_id,
            "input_files": [str(source)],
            "contract_digest": "a" * 64,
            "input_sha256": "b" * 64,
        },
    )
    assert result["applied"] and result["row_count"] == 2
    assert calls[-1] == "root/export/_LATEST.json"
    assert calls[-2].endswith("/manifest.json")
    count = len(calls)
    settled = object_export.reconcile(
        {"prefix": "root"},
        {},
        {"prefix": "root/export"},
        deadline(),
        dialect="s3",
        operation_id=operation_id,
    )
    assert settled["applied"] and len(calls) == count


def test_lost_pointer_reply_is_reconciled_without_new_parts(monkeypatch, tmp_path):
    from uuid import uuid4

    import pyarrow as pa
    import pyarrow.parquet as pq

    from app.services.connectors.adapters import object_export

    operation_id = str(uuid4())
    source = tmp_path / "input.parquet"
    pq.write_table(pa.table({"id": [1]}), source)
    objects = {}

    class Target:
        def put(self, key, data, expected_etag=None):
            objects[key] = data
            if key.endswith("_LATEST.json"):
                raise AdapterError("CONNECTOR_TIMEOUT")

        def read_small(self, key):
            return objects[key], "etag"

    monkeypatch.setattr(object_export, "client_for", lambda *a: Target())
    with pytest.raises(AdapterError, match="CONNECTOR_TIMEOUT"):
        object_export.execute(
            {"prefix": "root"},
            {},
            {},
            deadline(),
            dialect="s3",
            execution={
                "operation_id": operation_id,
                "input_files": [str(source)],
                "contract_digest": "a" * 64,
                "input_sha256": "b" * 64,
            },
        )
    assert object_export.reconcile(
        {"prefix": "root"}, {}, {}, deadline(), dialect="s3", operation_id=operation_id
    )["applied"]
