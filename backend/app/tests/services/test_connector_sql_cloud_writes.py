"""Cloud protocol contracts against deterministic HTTPS fixtures; no live certification."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import sqlglot

from app.services.connectors.adapters import sql_cloud_write as cloud
from app.services.connectors.adapters.sql import AdapterError


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "input.parquet"
    pq.write_table(
        pa.table({"id": [1, 2], "label": ["Robert'); DELETE FROM target;--", "value\\"]}), path
    )
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest()]
    execution = {
        "operation_id": str(uuid4()),
        "input_files": [str(path)],
        "input_sha256": hashlib.sha256(
            json.dumps(hashes, separators=(",", ":")).encode()
        ).hexdigest(),
        "contract_digest": "a" * 64,
    }
    return path, execution


def deadline():
    return (datetime.now(UTC) + timedelta(seconds=30)).isoformat()


def test_source_literal_cannot_escape_into_second_statement(source):
    path, _ = source
    for dialect, parser in [
        ("bigquery", "bigquery"),
        ("snowflake", "snowflake"),
        ("databricks_sql", "databricks"),
    ]:
        names, columns, query, count = cloud._source([path], {}, dialect)
        expressions = sqlglot.parse(query, read=parser)
        assert len(expressions) == 1
        assert not list(expressions[0].find_all(sqlglot.exp.Delete))
        assert count == 2


def test_large_cloud_source_refused_before_any_mutation(source, tmp_path, monkeypatch):
    path, execution = source
    monkeypatch.setattr(cloud, "MAX_ROWS", 1)
    monkeypatch.setattr(
        cloud, "CloudConnection", lambda *a, **kw: pytest.fail("must refuse before connecting")
    )
    with pytest.raises(AdapterError, match="STAGING_REQUIRED"):
        cloud.execute_write(
            "write_append",
            {"project": "p"},
            {},
            {"schema": "data", "table": "orders"},
            deadline(),
            tmp_path,
            dialect="bigquery",
            access={},
            execution=execution,
        )


class BigQuery:
    config = {"project": "p", "location": "US", "maximum_bytes_billed": 100000}

    def __init__(self, execution, *, lose=False, labels=None):
        self.deadline_at = deadline()
        self.execution, self.lose, self.labels = execution, lose, labels
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "POST":
            assert body["jobReference"]["jobId"] == "agentium_" + self.execution[
                "operation_id"
            ].replace("-", "")
            assert body["configuration"]["query"]["maximumBytesBilled"] == "100000"
            assert "BEGIN TRANSACTION" in body["configuration"]["query"]["query"]
            assert "COMMIT TRANSACTION" in body["configuration"]["query"]["query"]
            self.stored = body
            if self.lose:
                raise OSError("lost after server accepted job")
        if "/queries/" in path:
            values = {
                key: self.execution[key]
                for key in ("operation_id", "contract_digest", "input_sha256")
            } | {"inserted": "1", "updated": "1"}
            return {
                "jobComplete": True,
                "schema": {"fields": [{"name": name} for name in values]},
                "rows": [{"f": [{"v": value} for value in values.values()]}],
            }
        return {
            "status": {"state": "DONE"},
            "configuration": {
                "labels": self.labels if self.labels is not None else cloud._labels(self.execution)
            },
        }


def test_bigquery_lost_response_reconciles_same_job_with_reads_only(source):
    _, execution = source
    connection = BigQuery(execution, lose=True)
    with pytest.raises(OSError):
        cloud._bigquery(
            connection,
            "write_upsert",
            "`p.data.orders`",
            "SELECT 1 AS id",
            ["id"],
            ["`id`"],
            2,
            {"keys": ["id"], "schema": "s", "table": "t"},
            execution,
        )
    connection.calls.clear()
    receipt = cloud._bigquery(connection, "reconcile_write", "", "", [], [], 0, {}, execution)
    assert receipt["applied"] is True
    assert (receipt["inserted"], receipt["updated"]) == (1, 1)
    assert receipt["contract_digest"] == execution["contract_digest"]
    assert all(call[0] == "GET" for call in connection.calls)


def test_bigquery_wrong_job_contract_cannot_be_acknowledged(source):
    _, execution = source
    with pytest.raises(AdapterError, match="IDEMPOTENCY_CONFLICT"):
        cloud._bigquery(
            BigQuery(execution, labels={}), "reconcile_write", "", "", [], [], 0, {}, execution
        )


def test_bigquery_pending_job_remains_unknown_without_resubmission(source):
    _, execution = source
    connection = BigQuery(execution)
    connection.request = lambda method, *args: (
        {"status": {"state": "RUNNING"}} if method == "GET" else pytest.fail("no POST")
    )
    result = cloud._bigquery(connection, "reconcile_write", "", "", [], [], 0, {}, execution)
    assert result["outcome"] == "unknown"
    assert result["applied"] is False


def test_databricks_unknown_never_replays_mutation(source):
    _, execution = source

    class Connection:
        def request(self, *a):
            pytest.fail("no remote action for unsupported outcome lookup")

    assert (
        cloud._databricks(Connection(), "reconcile_write", "", "", [], [], 0, {}, execution)[
            "outcome"
        ]
        == "unknown"
    )


def test_snowflake_marker_is_written_inside_transaction_with_counts(source, monkeypatch):
    _, execution = source
    observations = []
    receipts = iter(
        [{"applied": False}, cloud._receipt(execution, 2, "marker_table", inserted=2, updated=0)]
    )
    monkeypatch.setattr(cloud, "_snowflake_marker", lambda *args: next(receipts))

    class Connection:
        config = {"warehouse": "w", "database": "d", "schema": "s"}
        deadline_at = deadline()

        def request(self, method, path, body=None):
            observations.append((method, path, body))
            return {"statementHandle": "job-1", "resultSetMetaData": {}}

    output = cloud._snowflake(
        Connection(),
        "write_append",
        '"s"."t"',
        '"s"."_agentium_operations"',
        "SELECT 1 AS id",
        ["id"],
        ['"id"'],
        2,
        {},
        execution,
    )
    assert output["applied"]
    statement = observations[0][2]["statement"]
    assert (
        statement.index("BEGIN TRANSACTION")
        < statement.index("_agentium_operations")
        < statement.index("COMMIT")
    )
    assert "EXCEPTION WHEN OTHER THEN ROLLBACK" in statement
    assert execution["operation_id"] in observations[0][1]


def test_databricks_exact_server_counts_are_preserved(source):
    _, execution = source

    class Connection:
        config = {"warehouse_id": "w"}
        deadline_at = deadline()

        def request(self, *args):
            if args[0] == "GET":
                return {"data_source_format": "DELTA"}
            return {
                "statement_id": "job-1",
                "status": {"state": "SUCCEEDED"},
                "manifest": {
                    "schema": {
                        "columns": [
                            {"name": "num_affected_rows"},
                            {"name": "num_inserted_rows"},
                            {"name": "num_updated_rows"},
                        ]
                    }
                },
                "result": {"data_array": [["2", "1", "1"]]},
            }

    receipt = cloud._databricks(
        Connection(),
        "write_upsert",
        "`s`.`t`",
        "SELECT 1 AS id",
        ["id"],
        ["`id`"],
        2,
        {"keys": ["id"], "schema": "s", "table": "t"},
        execution,
    )
    assert receipt["inserted"] == receipt["updated"] == 1
    assert receipt["outcome_check"] == "none"
