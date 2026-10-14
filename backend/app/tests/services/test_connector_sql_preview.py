"""A write preview reads the destination and never begins a write transaction."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.services.connectors.adapters import sql_preview
from app.services.connectors.adapters.sql import AdapterError


@pytest.fixture
def preview(tmp_path, monkeypatch):
    path = tmp_path / "source.parquet"
    pq.write_table(pa.table({"id": [1, 2], "value": ["updated", "inserted"]}), path)
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest()]
    execution = {
        "operation_id": str(uuid4()),
        "input_files": [str(path)],
        "input_sha256": hashlib.sha256(
            json.dumps(hashes, separators=(",", ":")).encode()
        ).hexdigest(),
        "contract_digest": "b" * 64,
        "write_operation": "write_upsert",
    }
    native = sqlite3.connect(":memory:")
    native.execute("CREATE TABLE target(id INTEGER NOT NULL,value TEXT)")
    native.execute("INSERT INTO target VALUES(1,'original')")
    native.commit()
    queries = []

    class Cursor:
        def execute(self, query, params=()):
            assert query.startswith("SELECT ")
            queries.append(query)
            self.metadata = "information_schema.columns" in query
            if not self.metadata:
                self.cursor = native.execute(query.replace("%s", "?"), params)

        def fetchmany(self, count):
            return [("id", "INTEGER", "NO"), ("value", "TEXT", "YES")]

        def fetchone(self):
            return self.cursor.fetchone()

        def close(self):
            pass

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def connected(*args, **kwargs):
        assert kwargs["read_only"] is True
        yield Connection()

    monkeypatch.setattr(sql_preview, "_connection", connected)

    def run():
        return sql_preview.preview_write(
            {},
            {},
            {"schema": "main", "table": "target", "keys": ["id"]},
            (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
            tmp_path,
            dialect="postgresql",
            access={},
            execution=execution,
        )

    yield run, native, execution, queries
    native.close()


def test_preview_counts_and_schema_without_destination_mutation(preview):
    run, native, execution, queries = preview
    result = run()
    assert result["dry_run"] and not result["applied"]
    assert result["inserted"] == result["updated"] == 1
    assert result["input_rows"] == 2 and result["target_rows"] == 1
    assert result["contract_digest"] == execution["contract_digest"]
    assert native.execute("SELECT * FROM target").fetchall() == [(1, "original")]
    assert all(query.startswith("SELECT ") for query in queries)


def test_preview_reports_overwrite_deletions(preview):
    run, native, execution, _ = preview
    execution["write_operation"] = "write_overwrite"
    result = run()
    assert result["deleted"] == 1 and result["inserted"] == 2 and result["updated"] == 0
    assert native.execute("SELECT COUNT(*) FROM target").fetchone()[0] == 1


def test_preview_rejects_duplicate_destination_key_without_mutation(preview):
    run, native, _, _ = preview
    native.execute("INSERT INTO target VALUES(1,'duplicate')")
    with pytest.raises(AdapterError, match="NON_UNIQUE_TARGET"):
        run()
    assert native.execute("SELECT COUNT(*) FROM target").fetchone()[0] == 2
