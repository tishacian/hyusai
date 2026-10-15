"""Planner semantics on a real local SQL engine; no supplier qualification."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.services.connectors.adapters import sql_read
from app.services.connectors.adapters.sql import AdapterError


@pytest.fixture
def database():
    native = sqlite3.connect(":memory:")
    native.execute(
        "CREATE TABLE source (id INTEGER, modified INTEGER, partition_key INTEGER, value TEXT)"
    )
    native.executemany(
        "INSERT INTO source VALUES (?,?,?,?)",
        [(1, 10, -4, "first"), (2, 10, None, "null"), (3, 11, 4, "last")],
    )
    calls = []

    class Cursor:
        def __init__(self):
            self.native = native.cursor()

        def execute(self, query, parameters=()):
            calls.append((query, parameters))
            self.native.execute(query.replace("%s", "?"), parameters)

        def fetchone(self):
            return self.native.fetchone()

        def fetchmany(self, count):
            return self.native.fetchmany(count)

        @property
        def description(self):
            return self.native.description

        def close(self):
            self.native.close()

    class Connection:
        def cursor(self, **kwargs):
            return Cursor()

    yield Connection(), native, calls
    native.close()


def execute(database, tmp_path, parameters, after=None):
    return sql_read.stream(
        database[0],
        "source",
        "*",
        parameters,
        (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        tmp_path,
        dialect="mysql",
        limits={},
        execution={"read_checkpoint": {"after": after, "revision": 2}},
    )


def data(path):
    return [json.loads(line) for line in (path / "rows.jsonl").read_text().splitlines()]


def incremental(**kw):
    return {
        "watermark_column": "modified",
        "key_column": "id",
        "type": "integer",
        "overlap": 0,
        **kw,
    }


def test_tuple_resume_keeps_rows_sharing_watermark(database, tmp_path):
    output = execute(database, tmp_path, {"incremental": incremental()}, after=[10, 1])
    assert [row[0] for row in data(tmp_path)] == [2, 3]
    assert output["next_checkpoint"] == [11, 3]
    assert output["checkpoint_revision"] == 2


def test_overlap_reads_old_values_without_rewinding_checkpoint(database, tmp_path):
    output = execute(database, tmp_path, {"incremental": incremental(overlap=1)}, after=[11, 3])
    assert [row[0] for row in data(tmp_path)] == [1, 2, 3]
    assert output["next_checkpoint"] == [11, 3]


def test_fixed_partitions_include_null_without_gap_or_duplicate(database, tmp_path):
    output = execute(database, tmp_path, {"partitions": {"column": "partition_key", "count": 4}})
    identifiers = [row[0] for row in data(tmp_path)]
    assert sorted(identifiers) == [1, 2, 3]
    assert output["partition_bounds"][-1] == {"column": "partition_key", "null": True}
    assert output["read_consistency"] == "none"  # Partitioning alone does not guarantee isolation.
    assert sum("MIN(" in query for query, params in database[2]) == 1


def test_partition_plus_incremental_is_complete(database, tmp_path):
    output = execute(
        database,
        tmp_path,
        {"partitions": {"column": "partition_key", "count": 2}, "incremental": incremental()},
        after=[10, 1],
    )
    assert sorted(row[0] for row in data(tmp_path)) == [2, 3]
    assert output["next_checkpoint"] == [11, 3]


@pytest.mark.parametrize(
    "values,code", [((1, 12, 0, "duplicate"), "NON_UNIQUE_KEY"), ((4, None, 0, "null"), "NULL_KEY")]
)
def test_unstable_incremental_keys_fail_before_stream(database, tmp_path, values, code):
    database[1].execute("INSERT INTO source VALUES (?,?,?,?)", values)
    with pytest.raises(AdapterError, match=code):
        execute(database, tmp_path, {"incremental": incremental()})
    assert not (tmp_path / "rows.jsonl").exists()


def test_bounds_or_checkpoint_in_public_parameters_are_rejected(database, tmp_path):
    with pytest.raises(AdapterError, match="INCREMENTAL_INVALID"):
        execute(database, tmp_path, {"incremental": incremental(after=[0, 0])})
    with pytest.raises(AdapterError, match="PARTITION_INVALID"):
        execute(
            database,
            tmp_path,
            {"partitions": {"column": "partition_key", "count": 4, "bounds": [0, 4]}},
        )


def test_new_rows_beyond_upper_bound_wait_for_next_import(database, tmp_path, monkeypatch):
    original = sql_read._partition_bounds

    def changed(*args):
        database[1].execute("INSERT INTO source VALUES (4,12,0,'next')")
        return original(*args)

    monkeypatch.setattr(sql_read, "_partition_bounds", changed)
    output = execute(database, tmp_path, {"incremental": incremental()})
    assert [row[0] for row in data(tmp_path)] == [1, 2, 3]
    assert output["next_checkpoint"] == [11, 3]


def test_no_checkpoint_on_partial_stream_limit(database, tmp_path):
    with pytest.raises(AdapterError, match="IMPORT_TOO_LARGE"):
        execute(database, tmp_path, {"incremental": incremental(), "max_rows": 1})
    # An incomplete file may remain private, but no manifest/checkpoint exists.
    assert (tmp_path / "rows.jsonl").exists()
