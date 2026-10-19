"""Strict Redshift DBAPI protocol + disposable unconstrained table state.

LOCK/timeout syntax is checked by the double; SQLite only supplies transactional
state for rollback and duplicate detection. This is not provider certification.
"""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.services.connectors.adapters import sql, sql_write
from app.services.connectors.profiles import get_profile


@pytest.fixture()
def redshift(tmp_path, monkeypatch):
    import psycopg2

    source = tmp_path / "source.parquet"
    pq.write_table(
        pa.table({"id": [1, 2], "value": ["updated", "Robert'); DELETE FROM orders;--"]}), source
    )
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    execution = {
        "operation_id": str(uuid4()),
        "contract_digest": "a" * 64,
        "input_sha256": hashlib.sha256(
            json.dumps([sha], separators=(",", ":")).encode()
        ).hexdigest(),
        "input_files": [str(source)],
        "write_operation": "write_upsert",
    }
    database = tmp_path / "redshift-state.db"
    with sqlite3.connect(database) as native:
        # Deliberately no UNIQUE/PRIMARY KEY. Redshift cannot enforce either.
        native.execute("CREATE TABLE orders (id INTEGER, value TEXT)")
        native.execute("INSERT INTO orders VALUES (1, 'original')")
        native.execute(sql_write.marker_table_ddl("redshift", "main"))
    controls = {
        "calls": [],
        "sessions": [],
        "lose_commit": False,
        "duplicate_marker": False,
        "bad_rowcount": False,
        "fail_insert": False,
    }

    class Cursor:
        def __init__(self, connection):
            self.connection, self.native = connection, connection.native.cursor()
            self.rows, self.override_count = None, None

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

        def execute(self, statement, parameters=()):
            controls["calls"].append((statement, parameters))
            self.rows, self.override_count = None, None
            assert all(
                word not in statement
                for word in (
                    "FOR UPDATE",
                    "lock_timeout",
                    "SET LOCAL",
                    "SERIALIZABLE",
                    "TRUNCATE",
                    "ON CONFLICT",
                )
            )
            if statement.startswith("SET "):
                assert statement == "SET statement_timeout TO %s"
                assert len(parameters) == 1 and 0 < parameters[0] <= 30_000
                self.rows = []
                return
            if statement.startswith("LOCK "):
                assert not self.connection.readonly and not self.connection.selected
                assert statement in {
                    'LOCK TABLE "main"."orders"',
                    'LOCK TABLE "main"."_agentium_operations"',
                }
                self.connection.locks.append(statement.removeprefix("LOCK TABLE "))
                assert self.connection.locks == sorted(self.connection.locks)
                self.rows = []
                return
            assert statement.startswith(("SELECT ", "INSERT INTO ", "UPDATE "))
            if not self.connection.readonly:
                assert self.connection.locks == sorted(
                    ['"main"."orders"', '"main"."_agentium_operations"']
                )
            self.connection.selected = True
            if self.connection.readonly:
                assert statement.startswith("SELECT ")
            if "information_schema.columns" in statement:
                self.rows = [("id", "BIGINT", "NO"), ("value", "VARCHAR", "YES")]
                return
            is_data_insert = statement.startswith('INSERT INTO "main"."orders"')
            if controls["fail_insert"] and is_data_insert:
                raise OSError("connection lost before commit")
            self.native.execute(statement.replace("%s", "?"), parameters)
            if controls["bad_rowcount"] and is_data_insert:
                self.override_count = 0
            if controls["duplicate_marker"] and statement.startswith(
                'INSERT INTO "main"."_agentium_operations"'
            ):
                self.native.execute(statement.replace("%s", "?"), parameters)

        def fetchone(self):
            if self.rows is not None:
                return self.rows.pop(0) if self.rows else None
            return self.native.fetchone()

        def fetchmany(self, size):
            if self.rows is not None:
                rows, self.rows = self.rows[:size], self.rows[size:]
                return rows
            return self.native.fetchmany(size)

        @property
        def rowcount(self):
            return self.override_count if self.override_count is not None else self.native.rowcount

        def close(self):
            self.native.close()

    class Connection:
        def __init__(self):
            self.native = sqlite3.connect(database)
            self.readonly, self.selected, self.locks = True, False, []

        def cursor(self):
            return Cursor(self)

        def set_session(self, **kwargs):
            assert set(kwargs) == {"readonly", "autocommit"} and kwargs["autocommit"] is False
            self.readonly = kwargs["readonly"]
            controls["sessions"].append(kwargs)

        def commit(self):
            self.native.commit()
            if controls["lose_commit"]:
                raise OSError("commit succeeded but its reply was lost")

        def rollback(self):
            self.native.rollback()

        def close(self):
            self.native.close()

    monkeypatch.setattr(
        sql,
        "postgresql_connection_options",
        lambda *a, **kw: {
            "host": "redshift.example",
            "hostaddr": "93.184.216.34",
            "sslmode": "verify-full",
        },
    )
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: Connection())

    def run(operation="write_upsert", *, value=None, table="orders"):
        directory = tmp_path / str(uuid4())
        directory.mkdir()
        return sql.execute(
            operation,
            {
                "host": "redshift.example",
                "database": "warehouse",
                "username": "writer",
                "port": 5439,
            },
            {"password": "private"},
            {"schema": "main", "table": table, "keys": ["id"]},
            (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            directory,
            dialect="redshift",
            access={"mode": "read_write"},
            execution=value or execution,
        )

    def rows(table="orders"):
        with sqlite3.connect(database) as native:
            return native.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()

    return run, controls, database, execution, rows


def test_native_upsert_locks_before_reading_and_commits_exact_receipt(redshift):
    run, control, _, execution, rows = redshift
    result = run()
    assert (result["inserted"], result["updated"], result["row_count"]) == (1, 1, 2)
    assert rows() == [(1, "updated"), (2, "Robert'); DELETE FROM orders;--")]
    calls = [c[0] for c in control["calls"]]
    assert calls[:3] == [
        "SET statement_timeout TO %s",
        'LOCK TABLE "main"."_agentium_operations"',
        'LOCK TABLE "main"."orders"',
    ]
    receipt = rows("_agentium_operations")
    assert len(receipt) == 1 and receipt[0][0] == execution["operation_id"]
    assert json.loads(receipt[0][3]) == result
    assert control["sessions"] == [{"readonly": False, "autocommit": False}]


def test_append_does_not_assume_primary_key_enforcement(redshift):
    run, _, _, _, rows = redshift
    result = run("write_append")
    assert result["inserted"] == 2 and result["updated"] == 0
    assert len(rows()) == 3
    ddl = sql_write.marker_table_ddl("redshift", "public")
    assert "PRIMARY KEY" not in ddl and "UNIQUE" not in ddl and "VARCHAR(65535)" in ddl
    profile = get_profile("redshift")
    assert profile.capabilities.write_append and profile.capabilities.write_upsert
    assert not profile.capabilities.write_overwrite


def test_duplicate_target_is_refused_before_any_mutation(redshift):
    run, control, database, _, rows = redshift
    with sqlite3.connect(database) as native:
        native.execute("INSERT INTO orders VALUES (1, 'duplicate')")
    with pytest.raises(sql.AdapterError, match="CONNECTOR_UPSERT_NON_UNIQUE_TARGET"):
        run()
    assert len(rows()) == 2 and rows("_agentium_operations") == []
    assert not any(c[0].startswith(("INSERT", "UPDATE")) for c in control["calls"])


def test_duplicate_unenforced_marker_cannot_authorize_reconciliation_or_write(redshift):
    run, _, database, execution, rows = redshift
    fake = {**execution, "applied": True}
    with sqlite3.connect(database) as native:
        native.executemany(
            "INSERT INTO _agentium_operations VALUES (?,?,?,?)",
            [
                (
                    execution["operation_id"],
                    execution["contract_digest"],
                    execution["input_sha256"],
                    json.dumps(fake),
                )
            ]
            * 2,
        )
    for operation in ("reconcile_write", "write_append"):
        with pytest.raises(sql.AdapterError, match="CONNECTOR_MARKER_NON_UNIQUE"):
            run(operation)
    assert rows() == [(1, "original")]


@pytest.mark.parametrize("failure", ["fail_insert", "bad_rowcount", "duplicate_marker"])
def test_statement_or_marker_failure_rolls_back_everything(redshift, failure):
    run, control, _, _, rows = redshift
    control[failure] = True
    with pytest.raises(sql.AdapterError):
        run()
    assert rows() == [(1, "original")] and rows("_agentium_operations") == []


def test_lost_commit_stays_unknown_until_readonly_receipt_lookup(redshift):
    run, control, _, _, rows = redshift
    control["lose_commit"] = True
    with pytest.raises(sql.AdapterError, match="CONNECTOR_SQL_FAILED"):
        run()
    assert len(rows()) == 2 and len(rows("_agentium_operations")) == 1
    control["lose_commit"] = False
    control["calls"].clear()
    result = run("reconcile_write")
    assert result["applied"] is True and result["reconciled"] is True
    assert all(c[0].startswith(("SET statement_timeout", "SELECT ")) for c in control["calls"])
    assert len(rows("_agentium_operations")) == 1


def test_dry_run_uses_only_read_queries_and_native_timeout(redshift):
    run, control, _, _, rows = redshift
    result = run("write_preview")
    assert result["dry_run"] is True and result["applied"] is False
    assert (result["inserted"], result["updated"]) == (1, 1)
    assert all(c[0].startswith(("SET statement_timeout", "SELECT ")) for c in control["calls"])
    assert rows() == [(1, "original")] and rows("_agentium_operations") == []


def test_unsupported_overwrite_is_refused_without_remote_call(redshift):
    run, control, *_ = redshift
    with pytest.raises(sql.AdapterError, match="CONNECTOR_OPERATION_UNSUPPORTED"):
        run("write_overwrite")
    assert control["calls"] == []


def test_reserved_marker_target_cannot_be_written_through_case_alias(redshift):
    run, control, *_ = redshift
    with pytest.raises(sql.AdapterError, match="CONNECTOR_RESERVED_TARGET"):
        run("write_append", table="_AGENTIUM_OPERATIONS")
    assert control["calls"] == []
