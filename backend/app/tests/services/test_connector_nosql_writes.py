"""Native bulk protocol: exact receipts, deterministic IDs, closed uncertain outcomes."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.services.connectors.adapters import nosql_write
from app.services.connectors.adapters.sql import AdapterError


def envelope(tmp_path, ids=(1, 2)):
    path = tmp_path / "input.parquet"
    pq.write_table(pa.table({"id": list(ids), "value": ["é"] * len(ids)}), path)
    return {
        "operation_id": str(uuid4()),
        "contract_digest": "a" * 64,
        "input_sha256": "b" * 64,
        "input_files": [str(path)],
    }


def execute(operation, env, **kwargs):
    return nosql_write.execute(
        operation,
        {"endpoint": "https://search.example.test"},
        {"api_key": "fixture"},
        {"schema": "default", "table": "scores", "keys": ["id"]},
        (datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        dialect="elasticsearch",
        access=kwargs.get("access", {"mode": "read_write"}),
        execution=env,
    )


def test_bulk_partial_failure_never_emits_success_marker(monkeypatch, tmp_path):
    env = envelope(tmp_path)
    calls = []

    def req(method, url, **kwargs):
        calls.append(url)
        return {}, {
            "errors": True,
            "items": [{"index": {"status": 200}}, {"index": {"status": 409}}],
        } if "_bulk" in url else {}

    monkeypatch.setattr(nosql_write.http, "json_request", req)
    with pytest.raises(AdapterError, match="CONNECTOR_WRITE_OUTCOME_UNKNOWN"):
        execute("write_upsert", env)
    assert not any("/_create/" in url for url in calls)


def test_lost_bulk_marker_reply_reconciles_without_replaying(monkeypatch, tmp_path):
    env = envelope(tmp_path)
    receipts = {}
    calls = []

    def req(method, url, **kwargs):
        calls.append((method, url))
        if "_bulk" in url:
            lines = kwargs["content"].splitlines()
            assert len(lines) == 4
            return {}, {
                "errors": False,
                "items": [{"index": {"status": 201}}, {"index": {"status": 200}}],
            }
        if "/_create/" in url:
            receipts[env["operation_id"]] = json.loads(kwargs["content"])
            raise AdapterError("CONNECTOR_TIMEOUT")
        if "/_doc/" in url:
            return {}, {"_source": receipts[env["operation_id"]]}
        return {}, {}

    monkeypatch.setattr(nosql_write.http, "json_request", req)
    with pytest.raises(AdapterError, match="CONNECTOR_TIMEOUT"):
        execute("write_upsert", env)
    count = sum("_bulk" in url for _, url in calls)
    result = execute("reconcile_write", env)
    assert result["applied"] and result["contract_digest"] == env["contract_digest"]
    assert sum("_bulk" in url for _, url in calls) == count


def test_duplicate_upsert_keys_rejected_before_bulk(monkeypatch, tmp_path):
    env = envelope(tmp_path, (1, 1))
    calls = []
    monkeypatch.setattr(
        nosql_write.http, "json_request", lambda method, url, **kw: calls.append(url) or ({}, {})
    )
    with pytest.raises(AdapterError, match="CONNECTOR_DUPLICATE_KEY"):
        execute("write_upsert", env)
    assert all("_bulk" not in url for url in calls)


def test_readonly_write_rejected_before_network(monkeypatch, tmp_path):
    monkeypatch.setattr(
        nosql_write.http, "json_request", lambda *a, **kw: pytest.fail("network forbidden")
    )
    with pytest.raises(AdapterError, match="CONNECTOR_READ_ONLY"):
        execute("write_append", envelope(tmp_path), access={"mode": "read"})
