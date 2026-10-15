"""Preview observes contracts and source metadata without sending mutations."""

import hashlib
import json
import sys
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.services.connectors.adapters import tools
from app.services.connectors.adapters import write_preview as preview
from app.services.connectors.adapters.sql import AdapterError
from app.tests.services.test_connector_delta_export import prepared as delta_fixture
from app.tests.services.test_connector_tools_oauth import write_config, write_execution

prepared = delta_fixture


def envelope(tmp_path, operation="export", ids=(1, 2)):
    path = tmp_path / "input.parquet"
    pq.write_table(pa.table({"id": list(ids)}), path)
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest()]
    return {
        "operation_id": str(uuid4()),
        "contract_digest": "a" * 64,
        "input_sha256": hashlib.sha256(
            json.dumps(hashes, separators=(",", ":")).encode()
        ).hexdigest(),
        "input_files": [str(path)],
        "write_operation": operation,
    }


def deadline():
    return (datetime.now(UTC) + timedelta(seconds=30)).isoformat()


def run(tmp_path, execution, parameters=None, dialect="s3_compatible", **kw):
    return preview.execute(
        "write_preview",
        kw.get("config", {"prefix": "root"}),
        kw.get("credentials", {}),
        parameters or {"prefix": "root/table"},
        deadline(),
        tmp_path,
        dialect=dialect,
        access={"mode": "read_write"},
        execution=execution,
    )


def test_object_preview_reads_pointer_without_put_and_never_claims_effect_counts(
    tmp_path, monkeypatch
):
    class Store:
        def read_small(self, key):
            assert key == "root/table/_LATEST.json"
            return b'{"manifest":"root/table/v=old/manifest.json"}', "old-etag"

        def put(self, *a, **kw):
            pytest.fail("preview attempted remote mutation")

    monkeypatch.setattr(preview, "client_for", lambda *a: Store())
    result = run(
        tmp_path, envelope(tmp_path), {"prefix": "root/table", "expected_pointer_etag": "old-etag"}
    )
    assert result["dry_run"] is True and result["applied"] is False
    assert result["input_rows"] == 2 and result["target_rows"] is None
    assert result["inserted"] is None and not result["publication_cas_checked"]


def test_changed_pointer_and_forged_source_fail_before_approval(tmp_path, monkeypatch):
    class Store:
        def read_small(self, key):
            return b'{"manifest":"root/table/v=old/manifest.json"}', "changed"

    monkeypatch.setattr(preview, "client_for", lambda *a: Store())
    execution = envelope(tmp_path)
    with pytest.raises(AdapterError, match="SOURCE_CHANGED"):
        run(tmp_path, execution)
    execution["input_sha256"] = "b" * 64
    monkeypatch.setattr(
        preview, "client_for", lambda *a: pytest.fail("bad source contacted target")
    )
    with pytest.raises(AdapterError, match="CONTRACT_CHANGED"):
        run(tmp_path, execution)


def test_parquet_version_publication_cannot_claim_append_or_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(
        preview, "client_for", lambda *a: pytest.fail("invalid mode contacted target")
    )
    with pytest.raises(AdapterError, match="PARAMETERS_INVALID"):
        run(tmp_path, envelope(tmp_path), {"prefix": "root/table", "mode": "append"})


def test_native_delta_preview_freezes_schema_and_version_without_committing(prepared, monkeypatch):
    from app.services.connectors.adapters import delta_export

    store, invocation = prepared
    args, execution = invocation([1, 2])
    delta_export.execute(*args, dialect="s3", execution=execution)
    before = list(store.writes)
    args, execution = invocation([3])
    execution["write_operation"] = "export"
    monkeypatch.setattr(preview, "client_for", lambda *a: store)
    result = run(args[-1], execution, args[2])
    assert result["target_version"] == 0 and result["input_rows"] == 1
    assert result["dry_run"] and not result["applied"]
    assert store.writes == before


def test_search_preview_only_gets_mapping_and_checks_duplicate_input(tmp_path, monkeypatch):
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url))
        assert method == "GET" and url.endswith("/_mapping")
        return {}, {"scores": {"mappings": {"properties": {"id": {"type": "long"}}}}}

    monkeypatch.setattr(preview.http, "json_request", request)
    result = run(
        tmp_path,
        envelope(tmp_path, "write_upsert"),
        {"schema": "default", "table": "scores", "keys": ["id"]},
        dialect="elasticsearch",
        config={"endpoint": "https://search.example.test"},
        credentials={"api_key": "private"},
    )
    assert len(calls) == 2 and result["target_mapping_digest"]
    assert result["updated"] is None and result["input_rows"] == 2
    other = tmp_path / "duplicate"
    other.mkdir()
    calls.clear()
    with pytest.raises(AdapterError, match="DUPLICATE_KEY"):
        run(
            other,
            envelope(other, "write_upsert", (1, 1)),
            {"schema": "default", "table": "scores", "keys": ["id"]},
            dialect="elasticsearch",
        )
    assert not calls


def test_mongo_preview_checks_live_unique_index_without_starting_write_session(
    tmp_path, monkeypatch
):
    class Collection:
        def list_indexes(self):
            return [{"key": {"id": 1}, "unique": True}]

    class Database:
        def list_collection_names(self):
            return ["scores", "agentium_operations"]

        def __getitem__(self, name):
            return Collection()

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["tls"] and not kwargs["retryWrites"]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def __getitem__(self, name):
            return Database()

        def start_session(self):
            pytest.fail("preview started mutation transaction")

    monkeypatch.setitem(sys.modules, "pymongo", SimpleNamespace(MongoClient=Client))
    monkeypatch.setattr(preview, "pinned_python_driver", lambda *a: nullcontext())
    result = run(
        tmp_path,
        envelope(tmp_path, "write_upsert"),
        {"schema": "bench", "table": "scores", "keys": ["id"]},
        dialect="mongodb",
        config={"host": "db.example.test", "username": "bench"},
        credentials={"password": "private"},
    )
    assert result["dry_run"] and result["target_indexes"] == [{"keys": ["id"], "unique": True}]
    assert result["inserted"] is None


def test_openapi_preview_validates_exact_contract_without_calling_tool(monkeypatch):
    cfg = write_config()
    params, execution = write_execution(cfg)
    execution.update(
        write_operation="tool_write", input_sha256=execution["tool_contract"]["arguments_digest"]
    )
    monkeypatch.setattr(tools, "mutation_request", lambda *a, **kw: pytest.fail("mutation"))
    monkeypatch.setattr(tools, "json_request", lambda *a, **kw: pytest.fail("business request"))
    result = tools.execute(
        "write_preview",
        cfg,
        {},
        params,
        deadline(),
        None,
        dialect="openapi",
        access={"mode": "read_write"},
        limits={},
        execution=execution,
    )
    assert result["dry_run"] is True and result["applied"] is False
    assert result["write_operation"] == "tool_write" and not result["remote_schema_checked"]
    assert not result["effects_observed"] and result["updated"] is None
    params["arguments"] = {"body": {"name": "different"}}
    with pytest.raises(AdapterError, match="TOOL_CONTRACT_CHANGED"):
        tools.execute(
            "write_preview",
            cfg,
            {},
            params,
            deadline(),
            None,
            dialect="openapi",
            access={"mode": "read_write"},
            limits={},
            execution=execution,
        )


def test_mcp_preview_checks_live_definition_without_tools_call(monkeypatch):
    definition = {
        "id": "createItem",
        "write": True,
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
        "output_schema": {},
    }
    cfg = {
        "base_url": "https://api.example.test/mcp",
        "allowed_origins": ["https://api.example.test"],
        "auth_mode": "none",
        "tool_allowlist": ["createItem"],
        "write_tools": ["createItem"],
        "tool_contracts": {"createItem": definition},
    }
    params, execution = write_execution(cfg, "mcp", {"name": "Item"})
    execution.update(
        write_operation="tool_write", input_sha256=execution["tool_contract"]["arguments_digest"]
    )
    calls = []

    def rpc(config, headers, method, params, deadline_at, **kw):
        calls.append(method)
        assert method != "tools/call"
        return (
            {
                "tools": [
                    {
                        "name": "createItem",
                        "inputSchema": definition["input_schema"],
                        "outputSchema": {},
                        "annotations": {"readOnlyHint": False},
                    }
                ]
            }
            if method == "tools/list"
            else {}
        ), None

    monkeypatch.setattr(tools, "_rpc", rpc)
    result = tools.execute(
        "write_preview",
        cfg,
        {},
        params,
        deadline(),
        None,
        dialect="mcp",
        access={"mode": "read_write"},
        limits={},
        execution=execution,
    )
    assert result["remote_schema_checked"] and result["dry_run"]
    assert calls == ["initialize", "notifications/initialized", "tools/list"]


def test_worker_stages_tool_preview_without_dataset_or_sending_intent(
    db_session, tmp_path, monkeypatch
):
    from app.services import tabular_datasets
    from app.services.connectors import writes
    from app.workers import tasks_connectors as worker

    intent = SimpleNamespace(
        id=str(uuid4()),
        connection_id="connection",
        operation="tool_write",
        state="prepared",
        contract_digest="a" * 64,
        contract={
            "tool": {"arguments_digest": "b" * 64},
            "parameters": {"operation_id": "tool", "arguments": {}},
        },
    )
    row = SimpleNamespace(
        operation="write_preview",
        workspace_id="workspace",
        connection_id="connection",
        input_json={"write_operation_id": intent.id},
        metrics_json={},
    )
    monkeypatch.setattr(writes, "get_write", lambda *a: intent)
    monkeypatch.setattr(writes, "validate_current", lambda *a: (None, None))
    monkeypatch.setattr(
        tabular_datasets, "materialize_dataset", lambda *a, **kw: pytest.fail("tool has no dataset")
    )
    params, execution = worker._stage_write(db_session, row, tmp_path)
    assert execution["write_operation"] == "tool_write" and execution["input_sha256"] == "b" * 64
    assert intent.state == "prepared" and not list(tmp_path.iterdir())


def test_cloud_preview_refuses_inline_limit_before_query_or_approval(tmp_path, monkeypatch):
    from app.services.connectors.adapters import sql_cloud_write, sql_preview

    monkeypatch.setattr(sql_cloud_write, "MAX_ROWS", 1)
    monkeypatch.setattr(
        sql_preview, "_connection", lambda *a, **kw: pytest.fail("oversized preview queried target")
    )
    with pytest.raises(AdapterError, match="CLOUD_STAGING_REQUIRED"):
        sql_preview.preview_write(
            {"project": "bench"},
            {},
            {"schema": "bench", "table": "scores"},
            deadline(),
            tmp_path,
            dialect="bigquery",
            access={},
            execution=envelope(tmp_path, "write_append"),
        )


def test_openapi_preview_validates_path_arguments_before_approval(monkeypatch):
    cfg = write_config()
    operation = cfg["openapi_spec"]["paths"].pop("/items")
    operation["post"]["parameters"] = [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
    ]
    cfg["openapi_spec"]["paths"]["/items/{id}"] = operation
    params, execution = write_execution(cfg, arguments={"body": {"name": "Item"}, "id": ".."})
    execution.update(
        write_operation="tool_write", input_sha256=execution["tool_contract"]["arguments_digest"]
    )
    monkeypatch.setattr(tools, "mutation_request", lambda *a, **kw: pytest.fail("mutation"))
    with pytest.raises(AdapterError, match="TOOL_ARGUMENT_INVALID"):
        tools.execute(
            "write_preview",
            cfg,
            {},
            params,
            deadline(),
            None,
            dialect="openapi",
            access={"mode": "read_write"},
            limits={},
            execution=execution,
        )
