"""SQL adapter contract and bounded artifact publication, without live drivers."""

import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.connectors.adapters import sql
from app.services.connectors.artifacts import parquet_artifact


def deadline():
    return (datetime.now(UTC) + timedelta(seconds=30)).isoformat()


class Cursor:
    def __init__(self, batches=None):
        self.batches = iter(batches or [])
        self.statements = []
        self.description = [("id",), ("value",)]
        self.fetch_sizes = []
        self.closed = False

    def execute(self, text, params=None):
        self.statements.append((text, params))

    def fetchmany(self, size):
        self.fetch_sizes.append(size)
        return next(self.batches, [])

    def fetchone(self):
        return (1,)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def connect_fixture(monkeypatch, cursor):
    calls = []

    @contextmanager
    def connected(*args):
        calls.append(args)
        yield SimpleNamespace(cursor=lambda **kwargs: cursor)

    monkeypatch.setattr(sql, "_connection", connected)
    return calls


def test_absent_write_capability_fails_before_any_connection(monkeypatch, tmp_path):
    calls = connect_fixture(monkeypatch, Cursor())
    with pytest.raises(sql.AdapterError, match="OPERATION_UNSUPPORTED"):
        sql.execute("write_append", {}, {"password": "x"}, {}, deadline(), tmp_path, dialect="hana")
    assert calls == []


def test_no_arbitrary_query_or_driver_option(monkeypatch, tmp_path):
    calls = connect_fixture(monkeypatch, Cursor())
    with pytest.raises(sql.AdapterError, match="PARAMETERS_INVALID"):
        sql.execute(
            "preview",
            {},
            {},
            {"sql": "DROP DATABASE app"},
            deadline(),
            tmp_path,
            dialect="postgresql",
        )
    assert calls == []


def test_source_scope_checked_before_query(monkeypatch, tmp_path):
    calls = connect_fixture(monkeypatch, Cursor())
    with pytest.raises(sql.AdapterError, match="SOURCE_FORBIDDEN"):
        sql.execute(
            "preview",
            {},
            {},
            {"schema": "private", "table": "payroll"},
            deadline(),
            tmp_path,
            dialect="postgresql",
            access={"allowed_schemas": ["public"]},
        )
    assert calls == []


def test_identifiers_cannot_turn_preview_into_write(monkeypatch, tmp_path):
    cursor = Cursor([[(1, "safe")]])
    connect_fixture(monkeypatch, cursor)
    output = sql.execute(
        "preview",
        {},
        {},
        {"table": 'orders"; DELETE FROM users;--', "limit": 2},
        deadline(),
        tmp_path,
        dialect="postgresql",
    )
    assert cursor.statements == [
        ('SELECT * FROM "public"."orders""; DELETE FROM users;--" LIMIT 2', None)
    ]
    assert output["row_count"] == 1
    assert cursor.closed


def test_catalog_filters_forbidden_schemas_and_tables(monkeypatch, tmp_path):
    cursor = Cursor([[("public", "allowed"), ("private", "allowed"), ("public", "forbidden")]])
    connect_fixture(monkeypatch, cursor)
    output = sql.execute(
        "catalog",
        {},
        {},
        {},
        deadline(),
        tmp_path,
        dialect="postgresql",
        access={"allowed_schemas": ["public"], "allowed_tables": ["public.allowed"]},
    )
    assert output == {"tables": [{"schema": "public", "table": "allowed"}]}


def test_import_streams_and_enforces_total_budget(monkeypatch, tmp_path):
    cursor = Cursor([[(1, "a")], [(2, "b")]])
    connect_fixture(monkeypatch, cursor)
    with pytest.raises(sql.AdapterError, match="IMPORT_TOO_LARGE"):
        sql.execute(
            "import",
            {},
            {},
            {"table": "orders", "max_rows": 1},
            deadline(),
            tmp_path,
            dialect="postgresql",
        )
    assert cursor.fetch_sizes == [1000, 1000]
    assert cursor.closed


def test_import_preserves_typed_values_then_publishes_parquet(monkeypatch, tmp_path):
    import pyarrow.parquet as pq

    cursor = Cursor([[(1, Decimal("12.34"))], [(2, Decimal("567.890"))]])
    connect_fixture(monkeypatch, cursor)
    output = sql.execute(
        "import", {}, {}, {"table": "orders"}, deadline(), tmp_path, dialect="postgresql"
    )
    parquet = parquet_artifact(output, tmp_path, deadline())
    table = pq.read_table(tmp_path / parquet["artifact"])
    assert table.to_pydict() == {"id": [1, 2], "value": [Decimal("12.340"), Decimal("567.890")]}
    assert parquet["row_count"] == 2
    assert parquet["sha256"] == hashlib.sha256((tmp_path / "data.parquet").read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "document",
    [
        {"type": "date", "value": "2026-10-14"},
        {"type": "datetime", "value": "2026-10-14T12:00:00"},
        {"type": "decimal", "value": "123.45"},
        {"type": "binary", "value": "YWJj"},
        {"type": "float", "value": "NaN"},
        {"type": "object", "value": {"type": "date", "value": "2026-10-14"}},
        {"nested": [{"type": "decimal", "value": "12.34"}]},
    ],
)
def test_json_documents_resembling_scalar_tags_remain_documents(monkeypatch, tmp_path, document):
    import pyarrow.parquet as pq

    connect_fixture(monkeypatch, Cursor([[(1, document)]]))
    output = sql.execute(
        "import", {}, {}, {"table": "orders"}, deadline(), tmp_path, dialect="postgresql"
    )
    assert output["format"] == "typed-jsonl-v2"
    parquet_artifact(output, tmp_path, deadline())
    assert pq.read_table(tmp_path / "data.parquet").to_pylist() == [{"id": 1, "value": document}]
    # The private wire envelope must never leak into outbound JSON requests.
    assert sql._json_value(document) == document


def test_typed_objects_can_contain_actual_scalars_and_literal_tags():
    from app.services.connectors.artifacts import decode_value

    value = {
        "actual": [date(2026, 10, 14), Decimal("1.250"), b"bytes"],
        "literal": {"type": "object", "value": {"type": "binary", "value": "YWJj"}},
    }
    assert decode_value(json.loads(json.dumps(sql._typed_value(value)))) == value


def test_ambiguous_old_stream_format_is_refused(tmp_path):
    (tmp_path / "rows.jsonl").write_text('[{"type":"date","value":"2026-10-14"}]\n')
    with pytest.raises(sql.AdapterError, match="CONNECTOR_ARTIFACT_INVALID"):
        parquet_artifact(
            {"columns": ["document"], "row_count": 1, "format": "typed-jsonl-v1"},
            tmp_path,
            deadline(),
        )


def test_schema_inference_handles_leading_null_batch_without_losing_later_values(tmp_path):
    import pyarrow.parquet as pq

    lines = [[None, None]] * 1000 + [[7, {"type": "date", "value": "2026-10-14"}]]
    (tmp_path / "rows.jsonl").write_text("".join(json.dumps(row) + "\n" for row in lines))
    parquet_artifact(
        {"columns": ["number", "day"], "row_count": 1001, "format": "typed-jsonl-v2"},
        tmp_path,
        deadline(),
    )
    result = pq.read_table(tmp_path / "data.parquet").slice(1000).to_pylist()
    assert result == [{"number": 7, "day": date(2026, 10, 14)}]


def test_incompatible_heterogeneous_types_fail_closed(tmp_path):
    (tmp_path / "rows.jsonl").write_text('[1]\n["not-an-integer"]\n')
    with pytest.raises(sql.AdapterError, match="TYPE_UNSUPPORTED"):
        parquet_artifact(
            {"columns": ["x"], "row_count": 2, "format": "typed-jsonl-v2"}, tmp_path, deadline()
        )


def test_postgresql_connection_uses_pinned_tls_and_read_only_transaction(monkeypatch):
    import socket

    import psycopg2

    from app.services.connectors import network_policy

    monkeypatch.setattr(
        network_policy.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 5432))
        ],
    )
    cursor = Cursor()
    captures, sessions = [], []
    connection = SimpleNamespace(
        cursor=lambda: cursor,
        set_session=lambda **kwargs: sessions.append(kwargs),
        rollback=lambda: None,
        close=lambda: None,
    )
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: captures.append(kwargs) or connection)
    with sql._connection(
        "postgresql",
        {"host": "db.example.test", "database": "app", "username": "reader"},
        {"password": "private"},
        deadline(),
    ):
        pass
    assert captures[0]["hostaddr"] == "93.184.216.34"
    assert captures[0]["host"] == "db.example.test"
    assert captures[0]["sslmode"] == "verify-full"
    assert sessions == [
        {"readonly": True, "autocommit": False},
        {"isolation_level": "REPEATABLE READ"},
    ]
    assert cursor.statements[0][0].startswith("SET LOCAL statement_timeout")


def test_demo_never_counts_as_real_sql_source(monkeypatch, tmp_path):
    calls = connect_fixture(monkeypatch, Cursor())
    output = sql.execute("test", {"demo_mode": True}, {}, {}, deadline(), tmp_path, dialect="hana")
    assert output == {"connected": False, "source": "demo", "demo_mode": True}
    assert calls == []


def test_real_dataset_publication_inherits_workspace_and_lineage(db_session, tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq

    from app.core.config import settings
    from app.models.tabular import TabularDataset
    from app.models.workspace import Workspace
    from app.workers.tasks_connectors import _publish_stream

    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    workspace = Workspace(id=str(uuid4()), name="publication", slug=str(uuid4()))
    db_session.add(workspace)
    db_session.commit()
    row = SimpleNamespace(
        workspace_id=workspace.id,
        connection_id="source-id",
        connection_revision=3,
        id=str(uuid4()),
        profile="postgresql",
        run_id=None,
        node_id=None,
        metrics_json={},
    )
    path = tmp_path / "data.parquet"
    pq.write_table(pa.table({"number": [1, 2]}), path)
    output = {
        "artifact": "data.parquet",
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "row_count": 2,
        "consistency": "none",
    }
    published = _publish_stream(db_session, row, output, tmp_path)
    db_session.commit()
    dataset = db_session.query(TabularDataset).filter_by(workspace_id=workspace.id).one()
    assert dataset.status == "ready"
    assert dataset.row_count == 2
    assert dataset.lineage_json["connection_revision"] == 3
    assert dataset.lineage_json["compute_run_id"] == row.id
    assert published["dataset"]["dataset_id"] == dataset.id


def test_native_pinning_rejects_driver_routing_before_credentials(monkeypatch):
    import socket

    from app.services.connectors.adapters.sql_transport import pinned_sql_destination
    from app.services.connectors.network_policy import ConnectorNetworkError

    calls = []

    def dns(host, port, *args, **kwargs):
        calls.append((host, port, args, kwargs))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    with pinned_sql_destination("sql.example.test", 1433):
        socket.getaddrinfo("sql.example.test", 1433)
        assert calls[-1][0] == "93.184.216.34"
        assert calls[-1][2][-1] & socket.AI_NUMERICHOST
        with pytest.raises(ConnectorNetworkError, match="REDIRECT_DENIED"):
            socket.getaddrinfo("attacker.example.test", 1433)
        with pytest.raises(ConnectorNetworkError, match="REDIRECT_DENIED"):
            socket.getaddrinfo("sql.example.test", 4444)
    assert socket.getaddrinfo is dns


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        ("mysql", "`"),
        ("mariadb", "`"),
        ("sql_server", '"'),
        ("oracle", '"'),
        ("redshift", '"'),
        ("databricks_sql", "`"),
    ],
)
def test_sql_dialects_quote_identifiers_and_limit_queries(dialect, expected):
    target = sql._target(dialect, {}, "public", 'order"`s')
    assert target.startswith(expected)
    limited = sql._limited("SELECT * FROM source", dialect, 7)
    assert (
        ("TOP 7" in limited)
        if dialect == "sql_server"
        else ("FETCH FIRST 7 ROWS ONLY" in limited)
        if dialect == "oracle"
        else limited.endswith("LIMIT 7")
    )


def test_snowflake_pages_use_configured_origin_and_preserve_decimal(monkeypatch):
    from app.services.connectors.adapters import sql_cloud

    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "POST":
            return {}, {
                "statementHandle": "statement-1",
                "resultSetMetaData": {
                    "rowType": [{"name": "price", "type": "fixed"}],
                    "partitionInfo": [{}, {}],
                },
                "data": [["12.34"]],
            }
        return {}, {"data": [["56.789"]]}

    monkeypatch.setattr(sql_cloud, "json_request", request)
    connection = sql_cloud.CloudConnection(
        "snowflake",
        {"host": "account.snowflakecomputing.com", "warehouse": "WH"},
        {"access_token": "private"},
        deadline(),
    )
    cursor = connection.cursor()
    cursor.execute("SELECT 1")
    assert cursor.fetchmany(1) == [(Decimal("12.34"),)]
    assert cursor.fetchmany(5) == [(Decimal("56.789"),)]
    assert len(calls) == 2
    assert (
        calls[1][1]
        == "https://account.snowflakecomputing.com/api/v2/statements/statement-1?partition=1"
    )
    assert json.loads(calls[0][2]["content"])["parameters"]["MULTI_STATEMENT_COUNT"] == "1"


@pytest.mark.parametrize("value", ["1", "2"])
def test_bigquery_connection_probe_executes_query_without_fabricating_version(
    monkeypatch, tmp_path, value
):
    from app.services.connectors import runtime_identity
    from app.services.connectors.adapters import sql_cloud

    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, json.loads(kwargs["content"])))
        return {}, {
            "jobComplete": True,
            "jobReference": {"jobId": "probe-job", "location": "EU"},
            "schema": {"fields": [{"name": "f0_", "type": "INTEGER"}]},
            "rows": [{"f": [{"v": value}]}],
        }

    monkeypatch.setattr(sql_cloud, "json_request", request)

    def probe():
        return sql.execute(
            "test",
            {"project": "fixture-project", "location": "EU"},
            {"access_token": "fixture-token"},
            {},
            deadline(),
            tmp_path,
            dialect="bigquery",
        )

    if value != "1":
        with pytest.raises(sql.AdapterError, match="CONNECTOR_RESPONSE_INVALID"):
            probe()
    else:
        output = probe()
        assert output["connected"] is True and output["source"] == "real"
        assert output["identity_error_code"] == "CONNECTOR_SERVER_VERSION_UNAVAILABLE"
        assert "server_version" not in output
        monkeypatch.setattr(runtime_identity.settings, "connector_runner_image_sha256", "a" * 64)
        assert runtime_identity.observe("bigquery", output) is None
    assert len(calls) == 1
    assert calls[0][0] == "POST" and calls[0][2]["query"] == "SELECT 1"


def test_bigquery_job_pages_preserve_values_and_billing_cap(monkeypatch):
    from app.services.connectors.adapters import sql_cloud

    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return {}, {
            "jobComplete": True,
            "jobReference": {"jobId": "job-1", "location": "EU"},
            "schema": {"fields": [{"name": "count", "type": "INTEGER"}]},
            "rows": [{"f": [{"v": "9007199254740993"}]}],
        }

    monkeypatch.setattr(sql_cloud, "json_request", request)
    cursor = sql_cloud.CloudConnection(
        "bigquery",
        {"project": "fixture-project", "dataset": "ds", "location": "EU"},
        {"access_token": "private"},
        deadline(),
    ).cursor()
    cursor.execute("SELECT 1")
    assert cursor.fetchone() == (9007199254740993,)
    body = json.loads(calls[0][2]["content"])
    assert body["maximumBytesBilled"] == "1073741824"
    assert body["jobTimeoutMs"]
    assert calls[0][1].startswith("https://bigquery.googleapis.com/")


def test_databricks_rejects_cross_origin_chunk_link(monkeypatch):
    from app.services.connectors.adapters import sql_cloud

    calls = []

    def request(*args, **kwargs):
        calls.append(args)
        return {}, {
            "statement_id": "statement-1",
            "status": {"state": "SUCCEEDED"},
            "manifest": {"schema": {"columns": [{"name": "x", "type_name": "INT"}]}},
            "result": {
                "data_array": [["1"]],
                "next_chunk_internal_link": "https://evil.example/chunk",
            },
        }

    monkeypatch.setattr(sql_cloud, "json_request", request)
    cursor = sql_cloud.CloudConnection(
        "databricks_sql",
        {"host": "dbc-123.cloud.databricks.com", "warehouse_id": "wh"},
        {"access_token": "private"},
        deadline(),
    ).cursor()
    cursor.execute("SELECT 1")
    assert cursor.fetchone() == (1,)
    with pytest.raises(sql.AdapterError, match="REDIRECT_DENIED"):
        cursor.fetchone()
    assert len(calls) == 1


def test_cloud_generated_query_bindings_cannot_inject_statement():
    from app.services.connectors.adapters.sql_cloud import _bind

    assert (
        _bind("SELECT * WHERE table_name=%s", ("table'; DROP TABLE x;--",))
        == "SELECT * WHERE table_name='table''; DROP TABLE x;--'"
    )


def test_hana_demo_is_labelled_and_importable_without_live_driver(tmp_path):
    import pyarrow.parquet as pq

    from app.services.connectors.hana.demo_rows import TABLE_EQUIPMENT

    output = sql.execute(
        "import",
        {"demo_mode": True},
        {},
        {"table": TABLE_EQUIPMENT},
        deadline(),
        tmp_path,
        dialect="hana",
    )
    assert output["source"] == "demo"
    parquet_artifact(output, tmp_path, deadline())
    assert pq.read_metadata(tmp_path / "data.parquet").num_rows == output["row_count"]
