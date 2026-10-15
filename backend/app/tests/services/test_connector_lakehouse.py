"""Protocol fixtures and real local Parquet; never provider certification."""

import hashlib
import io
import json
from datetime import UTC, datetime, timedelta

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.services.connectors.adapters import lakehouse
from app.services.connectors.adapters.sql import AdapterError
from app.services.connectors.profiles import get_profile


def deadline():
    return (datetime.now(UTC) + timedelta(minutes=5)).isoformat()


CONFIG = {
    "base_url": "https://catalog.example",
    "allowed_origins": ["https://catalog.example"],
    "download_origins": ["https://files.example"],
    "share": "sales",
}


def parquet_bytes(data, schema=None):
    target = io.BytesIO()
    pq.write_table(pa.table(data, schema=schema), target)
    return target.getvalue()


def fake_download(monkeypatch, files):
    calls = []

    def download(url, path, *, deadline_at, max_bytes, headers=None):
        calls.append((url, headers))
        data = files[url]
        if len(data) > max_bytes:
            raise AdapterError("CONNECTOR_IMPORT_TOO_LARGE")
        path.write_bytes(data)
        return {}, len(data), hashlib.sha256(data).hexdigest()

    monkeypatch.setattr(lakehouse.http, "download", download)
    return calls


def sharing_response(monkeypatch, file_data, *, extra=None, protocol=None):
    schema = {
        "type": "struct",
        "fields": [
            {"name": "value", "type": "long", "nullable": False},
            {"name": "region", "type": "string", "nullable": False},
        ],
    }
    lines = [
        {"protocol": protocol or {"minReaderVersion": 1}},
        {"metaData": {"id": "table-id", "schemaString": json.dumps(schema)}},
    ]
    for index, (url, data) in enumerate(file_data.items()):
        lines.append(
            {
                "file": {
                    "id": f"file-{index}",
                    "url": url,
                    "size": len(data),
                    "partitionValues": {"region": "FR"},
                    **(extra or {}),
                }
            }
        )

    def request(method, url, **kwargs):
        assert method == "POST" and url.endswith("/shares/sales/schemas/public/tables/scores/query")
        assert kwargs["headers"]["Authorization"] == "Bearer catalog-token"
        assert kwargs["content"] == b"{}"
        return {"delta-table-version": "7"}, b"\n".join(json.dumps(line).encode() for line in lines)

    monkeypatch.setattr(lakehouse.http, "request", request)


def execute(tmp_path, dialect="delta_sharing", operation="import", config=None, parameters=None):
    return lakehouse.execute(
        operation,
        config or CONFIG,
        {"token": "catalog-token"},
        parameters if parameters is not None else {"schema": "public", "table": "scores"},
        deadline(),
        str(tmp_path),
        dialect=dialect,
    )


@pytest.mark.parametrize("dialect", ["delta_sharing", "unity_catalog", "iceberg_rest"])
def test_live_catalog_diagnostic_is_connected_without_inventing_version(
    monkeypatch, tmp_path, dialect
):
    from app.services.connectors import runtime_identity

    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url))
        assert method == "GET" and kwargs["headers"]["Authorization"] == "Bearer catalog-token"
        if dialect == "delta_sharing":
            return {}, {"items": [{"name": "scores" if url.endswith("/tables") else "public"}]}
        if dialect == "unity_catalog":
            return (
                ({}, {"schemas": [{"name": "public"}]})
                if "/schemas?" in url
                else ({}, {"tables": [{"name": "scores", "data_source_format": "DELTA"}]})
            )
        return (
            ({}, {"namespaces": [["public"]]})
            if url.endswith("/namespaces")
            else ({}, {"identifiers": [{"name": "scores"}]})
        )

    monkeypatch.setattr(lakehouse.http, "json_request", request)
    result = execute(
        tmp_path,
        dialect=dialect,
        operation="test",
        config={**CONFIG, "catalog": "main"},
        parameters={},
    )
    assert len(calls) == 2
    assert result["connected"] is True and result["source"] == "real"
    assert result["tables"][0]["name"] == "scores"
    assert "server_version" not in result
    monkeypatch.setattr(runtime_identity.settings, "connector_runner_image_sha256", "a" * 64)
    assert runtime_identity.observe(dialect, result) is None


@pytest.mark.parametrize("dialect", ["delta_sharing", "unity_catalog", "iceberg_rest"])
def test_forbidden_catalog_cannot_be_reported_connected(monkeypatch, tmp_path, dialect):
    def denied(*args, **kwargs):
        raise AdapterError("CONNECTOR_AUTH_DENIED")

    monkeypatch.setattr(lakehouse.http, "json_request", denied)
    with pytest.raises(AdapterError, match="CONNECTOR_AUTH_DENIED"):
        execute(
            tmp_path,
            dialect=dialect,
            operation="test",
            config={**CONFIG, "catalog": "main"},
            parameters={},
        )


def test_demo_catalog_cannot_be_reported_as_real_connection(monkeypatch, tmp_path):
    monkeypatch.setattr(lakehouse, "_sharing", lambda *a: {"source": "demo", "tables": []})
    with pytest.raises(AdapterError, match="CONNECTOR_RESPONSE_INVALID"):
        execute(tmp_path, operation="test", parameters={})


def test_delta_sharing_reads_parts_partition_columns_and_hides_signed_urls(monkeypatch, tmp_path):
    files = {
        "https://files.example/a?sig=private-a": parquet_bytes({"value": [1, 2]}),
        "https://files.example/b?sig=private-b": parquet_bytes({"value": [3]}),
    }
    sharing_response(monkeypatch, files)
    calls = fake_download(monkeypatch, files)
    result = execute(tmp_path)
    assert result["columns"] == ["value", "region"] and result["row_count"] == 3
    assert [json.loads(line) for line in (tmp_path / "rows.jsonl").read_text().splitlines()] == [
        [1, "FR"],
        [2, "FR"],
        [3, "FR"],
    ]
    assert result["snapshot"]["version"] == 7 and result["consistency"] == "snapshot"
    assert all(headers is None for _, headers in calls)
    assert "private-" not in json.dumps(result) and "catalog-token" not in json.dumps(result)
    assert not list(tmp_path.glob("*.parquet"))


def test_delta_sharing_unapproved_file_origin_blocked_before_download(monkeypatch, tmp_path):
    sharing_response(monkeypatch, {"https://evil.example/a": parquet_bytes({"value": [1]})})
    monkeypatch.setattr(lakehouse.http, "download", lambda *a, **kw: pytest.fail("origin bypass"))
    with pytest.raises(AdapterError, match="DOWNLOAD_ORIGIN_DENIED"):
        execute(tmp_path)


@pytest.mark.parametrize(
    "extra,protocol",
    [
        ({"deletionVector": {"path": "x"}}, None),
        ({}, {"minReaderVersion": 2}),
        ({}, {"readerFeatures": ["deletionVectors"]}),
    ],
)
def test_delta_sharing_never_ignores_delete_semantics(monkeypatch, tmp_path, extra, protocol):
    sharing_response(
        monkeypatch,
        {"https://files.example/a": parquet_bytes({"value": [1]})},
        extra=extra,
        protocol=protocol,
    )
    with pytest.raises(AdapterError, match="DELTA_FEATURE_UNSUPPORTED"):
        execute(tmp_path)


def test_delta_sharing_bounds_preview_and_refuses_truncated_import(monkeypatch, tmp_path):
    files = {"https://files.example/a": parquet_bytes({"value": [1, 2]})}
    sharing_response(monkeypatch, files)
    fake_download(monkeypatch, files)
    preview = tmp_path / "preview"
    preview.mkdir()
    assert execute(
        preview, operation="preview", parameters={"schema": "public", "table": "scores", "limit": 1}
    )["rows"] == [[1, "FR"]]
    imported = tmp_path / "import"
    imported.mkdir()
    with pytest.raises(AdapterError, match="IMPORT_TOO_LARGE"):
        execute(imported, parameters={"schema": "public", "table": "scores", "max_rows": 1})


def test_access_enforced_before_query(monkeypatch, tmp_path):
    monkeypatch.setattr(lakehouse.http, "request", lambda *a, **kw: pytest.fail("source queried"))
    with pytest.raises(AdapterError, match="SOURCE_FORBIDDEN"):
        lakehouse.execute(
            "preview",
            CONFIG,
            {"token": "token"},
            {"schema": "private", "table": "scores"},
            deadline(),
            str(tmp_path),
            dialect="delta_sharing",
            access={"allowed_schemas": ["public"]},
        )


def test_catalog_cycle_cannot_run_forever(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lakehouse.http,
        "json_request",
        lambda *a, **kw: ({}, {"items": [], "nextPageToken": "same"}),
    )
    with pytest.raises(AdapterError, match="PAGINATION_INVALID"):
        execute(tmp_path, operation="catalog", parameters={})


def test_unity_uses_temporary_credentials_and_delta_local_helper(monkeypatch, tmp_path):
    from app.services.connectors.adapters import delta_reader

    config = {
        **CONFIG,
        "catalog": "main",
        "download_origins": ["https://s3.us-east-1.amazonaws.com"],
    }
    responses = []

    def json_request(method, url, **kwargs):
        responses.append((method, url, kwargs.get("content")))
        if method == "GET":
            return {}, {
                "table_id": "id",
                "data_source_format": "DELTA",
                "storage_location": "s3://bucket/table",
            }
        return {}, {
            "expiration_time": int((datetime.now(UTC) + timedelta(minutes=5)).timestamp() * 1000),
            "aws_temp_credentials": {
                "access_key_id": "access",
                "secret_access_key": "secret",
                "session_token": "session",
            },
        }

    monkeypatch.setattr(lakehouse.http, "json_request", json_request)

    def snapshot(client, *args):
        assert (
            client.root == "table"
            and client.secret_key == "secret"
            and client.session_token == "session"
        )
        return [{"key": "table/_delta_log/00000000000000000000.json", "size": 1, "etag": "x"}]

    monkeypatch.setattr(lakehouse, "_snapshot", snapshot)
    monkeypatch.setattr(
        delta_reader, "stage_delta", lambda *a, **kw: {"delta_version": 2, "row_count": 3}
    )
    result = execute(tmp_path, dialect="unity_catalog", config=config)
    assert json.loads(responses[1][2]) == {"table_id": "id", "operation": "READ"}
    assert result["snapshot"] == {"protocol": "unity_catalog", "table_id": "id", "version": 2}
    assert "secret" not in json.dumps(result)


def test_unity_rejects_undeclared_storage_origin_before_listing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lakehouse.http,
        "json_request",
        lambda method, *a, **kw: (
            {},
            {
                "table_id": "id",
                "data_source_format": "DELTA",
                "storage_location": "s3://bucket/table",
            }
            if method == "GET"
            else {
                "expiration_time": int(
                    (datetime.now(UTC) + timedelta(minutes=5)).timestamp() * 1000
                ),
                "aws_temp_credentials": {
                    "access_key_id": "access",
                    "secret_access_key": "secret",
                    "session_token": "session",
                },
            },
        ),
    )
    monkeypatch.setattr(lakehouse, "_snapshot", lambda *a, **kw: pytest.fail("storage bypass"))
    with pytest.raises(AdapterError, match="DOWNLOAD_ORIGIN_DENIED"):
        execute(tmp_path, dialect="unity_catalog", config={**CONFIG, "catalog": "main"})


def avro_bytes(schema, rows):
    from fastavro import writer

    target = io.BytesIO()
    writer(target, schema, rows)
    return target.getvalue()


def iceberg_files(*, deletes=False):
    parquet = parquet_bytes(
        {"old_name": [3]},
        schema=pa.schema([pa.field("old_name", pa.int64(), metadata={b"PARQUET:field_id": b"1"})]),
    )
    data_schema = {
        "type": "record",
        "name": "datafile",
        "fields": [
            {"name": "content", "type": "int"},
            {"name": "file_path", "type": "string"},
            {"name": "file_format", "type": "string"},
            {"name": "file_size_in_bytes", "type": "long"},
        ],
    }
    manifest = avro_bytes(
        {
            "type": "record",
            "name": "entry",
            "fields": [
                {"name": "status", "type": "int"},
                {"name": "data_file", "type": data_schema},
            ],
        },
        [
            {
                "status": 1,
                "data_file": {
                    "content": 1 if deletes else 0,
                    "file_path": "https://files.example/data.parquet",
                    "file_format": "PARQUET",
                    "file_size_in_bytes": len(parquet),
                },
            }
        ],
    )
    listing = avro_bytes(
        {
            "type": "record",
            "name": "manifest",
            "fields": [
                {"name": "manifest_path", "type": "string"},
                {"name": "content", "type": "int"},
            ],
        },
        [{"manifest_path": "https://files.example/manifest.avro", "content": 0}],
    )
    return {
        "https://files.example/data.parquet": parquet,
        "https://files.example/manifest.avro": manifest,
        "https://files.example/list.avro": listing,
    }


def iceberg_metadata():
    return {
        "metadata": {
            "format-version": 2,
            "table-uuid": "table-id",
            "current-schema-id": 1,
            "schemas": [
                {
                    "schema-id": 1,
                    "fields": [
                        {"id": 1, "name": "new_name", "type": "long", "required": True},
                        {"id": 2, "name": "added", "type": "string", "required": False},
                    ],
                }
            ],
            "current-snapshot-id": 5,
            "snapshots": [{"snapshot-id": 5, "manifest-list": "https://files.example/list.avro"}],
        }
    }


def test_iceberg_reads_snapshot_manifests_and_field_ids_across_rename(monkeypatch, tmp_path):
    monkeypatch.setattr(lakehouse.http, "json_request", lambda *a, **kw: ({}, iceberg_metadata()))
    fake_download(monkeypatch, iceberg_files())
    result = execute(tmp_path, dialect="iceberg_rest")
    assert result["columns"] == ["new_name", "added"] and result["snapshot"]["snapshot_id"] == "5"
    assert json.loads((tmp_path / "rows.jsonl").read_text()) == [3, None]
    assert not list(tmp_path.glob("*.avro"))


def test_iceberg_refuses_delete_files_instead_of_resurrecting_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(lakehouse.http, "json_request", lambda *a, **kw: ({}, iceberg_metadata()))
    fake_download(monkeypatch, iceberg_files(deletes=True))
    with pytest.raises(AdapterError, match="ICEBERG_DELETES_UNSUPPORTED"):
        execute(tmp_path, dialect="iceberg_rest")


def test_lakehouse_profiles_claim_read_only_without_certification():
    for key in ("unity_catalog", "delta_sharing", "iceberg_rest"):
        profile = get_profile(key)
        assert profile.capabilities.read
        assert profile.capabilities.write_append == (key == "iceberg_rest")
        assert not profile.capabilities.read_partitioned


def test_sharing_lineage_binds_partition_values_as_well_as_file_bytes(monkeypatch, tmp_path):
    files = {"https://files.example/a": parquet_bytes({"value": [1]})}
    fake_download(monkeypatch, files)
    first = tmp_path / "first"
    first.mkdir()
    sharing_response(monkeypatch, files)
    before = execute(first)
    second = tmp_path / "second"
    second.mkdir()
    sharing_response(monkeypatch, files, extra={"partitionValues": {"region": "DE"}})
    after = execute(second)
    assert before["source_fingerprint"] != after["source_fingerprint"]
