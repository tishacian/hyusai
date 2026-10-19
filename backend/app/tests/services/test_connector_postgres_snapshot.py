"""Optional PostgreSQL protocol probe; does not qualify TLS or live connector IO."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.services.connectors.adapters import sql


def test_postgres_repeatable_read_holds_one_snapshot_across_partition_queries(monkeypatch):
    dsn = os.environ.get("AGENTIUM_SQL_PROTOCOL_PROBE_DSN")
    if not dsn:
        pytest.skip("explicit disposable PostgreSQL protocol probe only")
    import psycopg2

    connect = psycopg2.connect
    writer = connect(dsn)
    writer.autocommit = True
    with writer.cursor() as cursor:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS d7_read_probe")
        cursor.execute("CREATE TABLE d7_read_probe.snapshot_rows(id INTEGER PRIMARY KEY)")
        cursor.execute("INSERT INTO d7_read_probe.snapshot_rows VALUES (1),(2)")
    # The disposable server has no TLS. Inject only the connection factory;
    # this test claims transaction semantics, never a certified TLS transport.
    monkeypatch.setattr(
        sql,
        "postgresql_connection_options",
        lambda *a, **kw: {"host": "probe", "hostaddr": "127.0.0.1", "sslmode": "verify-full"},
    )
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: connect(dsn))
    try:
        with sql._connection(
            "postgresql",
            {"host": "probe", "database": "probe", "username": "postgres"},
            {},
            (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
        ) as reader:
            with reader.cursor() as first:
                first.execute("SHOW transaction_isolation")
                assert first.fetchone()[0] == "repeatable read"
                first.execute("SHOW transaction_read_only")
                assert first.fetchone()[0] == "on"
                first.execute("SELECT COUNT(*) FROM d7_read_probe.snapshot_rows")
                assert first.fetchone()[0] == 2
            with writer.cursor() as changed:
                changed.execute("INSERT INTO d7_read_probe.snapshot_rows VALUES (3)")
            with reader.cursor(name="second_partition") as second:
                second.execute("SELECT id FROM d7_read_probe.snapshot_rows ORDER BY id")
                assert list(second) == [(1,), (2,)]
        with writer.cursor() as current:
            current.execute("SELECT COUNT(*) FROM d7_read_probe.snapshot_rows")
            assert current.fetchone()[0] == 3
    finally:
        with writer.cursor() as cleanup:
            cleanup.execute("DROP TABLE IF EXISTS d7_read_probe.snapshot_rows")
            cleanup.execute("DROP SCHEMA IF EXISTS d7_read_probe")
        writer.close()
