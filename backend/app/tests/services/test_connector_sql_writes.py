"""Transactional write behaviour against a disposable SQLite DBAPI surrogate.

This checks atomicity/reconciliation logic, not PostgreSQL/SQL Server qualification.
"""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.services.connectors.adapters import sql_write
from app.services.connectors.adapters.sql import AdapterError


@pytest.fixture
def writer(tmp_path, monkeypatch):
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": [1, 2], "value": ["new", "second"]}), path)
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest()]
    execution = {
        "operation_id": str(uuid4()),
        "input_files": [str(path)],
        "input_sha256": hashlib.sha256(
            json.dumps(hashes, separators=(",", ":")).encode()
        ).hexdigest(),
        "contract_digest": "a" * 64,
    }
    database = tmp_path / "target.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO orders VALUES (1, 'old')")
        connection.execute(sql_write.marker_table_ddl("postgresql", "main"))
    controls = {"lose_commit": False, "fail_insert": False, "calls": []}

    class Cursor:
        def __init__(self, connection):
            self.native = connection.cursor()

        def execute(self, statement, params=()):
            controls["calls"].append(statement)
            if controls["fail_insert"] and statement.startswith('INSERT INTO "main"."orders"'):
                raise RuntimeError("lost during insertion")
            self.native.execute(statement.replace("%s", "?").replace(" FOR UPDATE", ""), params)

        def fetchone(self):
            return self.native.fetchone()

        @property
        def rowcount(self):
            return self.native.rowcount

        def close(self):
            self.native.close()

    class Connection:
        def __init__(self):
            self.native = sqlite3.connect(database)

        def cursor(self):
            return Cursor(self.native)

        def commit(self):
            self.native.commit()
            if controls["lose_commit"]:
                raise RuntimeError("response lost after database committed")

    @contextmanager
    def connected(*args, **kwargs):
        connection = Connection()
        try:
            yield connection
        finally:
            connection.native.rollback()
            connection.native.close()

    monkeypatch.setattr(sql_write, "_connection", connected)

    def execute(operation="write_upsert"):
        return sql_write.execute_write(
            operation,
            {},
            {},
            {"schema": "main", "table": "orders", "keys": ["id"]},
            (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            tmp_path,
            dialect="postgresql",
            access={},
            execution=execution,
        )

    return execute, execution, database, controls, path


def rows(path, table="orders"):
    with sqlite3.connect(path) as connection:
        return connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def test_upsert_counts_and_marker_commit_atomically(writer):
    execute, execution, database, controls, path = writer
    receipt = execute()
    assert receipt["inserted"] == 1
    assert receipt["updated"] == 1
    assert receipt["row_count"] == 2
    assert rows(database) == [(1, "new"), (2, "second")]
    marker = rows(database, "_agentium_operations")
    assert len(marker) == 1
    assert marker[0][0] == execution["operation_id"]
    assert json.loads(marker[0][3]) == receipt


def test_exception_before_commit_leaves_target_and_marker_unchanged(writer):
    execute, execution, database, controls, path = writer
    controls["fail_insert"] = True
    with pytest.raises(RuntimeError):
        execute()
    assert rows(database) == [(1, "old")]
    assert rows(database, "_agentium_operations") == []


def test_lost_commit_response_can_be_reconciled_without_rewrite(writer):
    execute, execution, database, controls, path = writer
    controls["lose_commit"] = True
    with pytest.raises(RuntimeError, match="response lost"):
        execute()
    assert rows(database) == [(1, "new"), (2, "second")]
    controls["calls"].clear()
    controls["lose_commit"] = False
    receipt = execute("reconcile_write")
    assert receipt["applied"] is True
    assert receipt["operation_id"] == execution["operation_id"]
    assert all(statement.startswith("SELECT ") for statement in controls["calls"])
    assert len(rows(database, "_agentium_operations")) == 1


def test_overwrite_uses_transactional_delete_and_rollback(writer):
    execute, execution, database, controls, path = writer
    controls["fail_insert"] = True
    with pytest.raises(RuntimeError):
        execute("write_overwrite")
    assert rows(database) == [(1, "old")]
    assert any(statement.startswith("DELETE FROM") for statement in controls["calls"])
    assert not any("TRUNCATE" in statement for statement in controls["calls"])


def test_modified_input_bytes_refused_before_destination_connection(writer):
    execute, execution, database, controls, path = writer
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(AdapterError, match="CONTRACT_CHANGED"):
        execute()
    assert controls["calls"] == []


def test_absent_marker_is_not_authorization_to_replay(writer):
    execute, execution, database, controls, path = writer
    receipt = execute("reconcile_write")
    assert receipt["outcome"] == "unknown"
    assert receipt["applied"] is False
    assert rows(database) == [(1, "old")]


def test_missing_private_execution_is_refused(tmp_path):
    with pytest.raises(AdapterError, match="APPROVAL_REQUIRED"):
        sql_write.execute_write(
            "write_append",
            {},
            {},
            {"schema": "main", "table": "orders"},
            (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            tmp_path,
            dialect="postgresql",
            access={},
            execution=None,
        )
