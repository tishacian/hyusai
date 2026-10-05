"""Opt-in against an owned local PostgreSQL 16 test instance, never demo data.

Create `agentium_pg_browser_test` on 127.0.0.1:55432, then enable
RUN_POSTGRESQL_BROWSER_INTEGRATION=1. Application metadata remains on the
isolated SQLite database supplied by conftest; each test owns its SQL schema.
"""

import os
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

from app.models.user import User
from app.models.workspace import Workspace
from app.services import tabular_datasets
from app.services.connectors.generic import postgresql_browser as browser

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_POSTGRESQL_BROWSER_INTEGRATION") != "1",
    reason="Owned local PostgreSQL integration instance required",
)


@pytest.fixture()
def postgres(monkeypatch):
    admin = psycopg2.connect(
        host="127.0.0.1",
        port=55432,
        dbname="agentium_pg_browser_test",
        user="postgres",
        connect_timeout=3,
    )
    admin.autocommit = True
    suffix = uuid4().hex[:12]
    schema, hidden, role = f"qa_{suffix}", f"hidden_{suffix}", f"reader_{suffix}"
    with admin.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(hidden)))
        cursor.execute(
            sql.SQL(
                "CREATE TABLE {}.claims (id bigint PRIMARY KEY, amount numeric(38,20), facts jsonb, at timestamptz, attachment bytea)"
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL("CREATE TABLE {}.private (secret text)").format(sql.Identifier(hidden))
        )
        cursor.execute(
            sql.SQL(
                "INSERT INTO {}.claims VALUES (%s, %s, %s, %s, NULL), (%s, NULL, NULL, NULL, NULL)"
            ).format(sql.Identifier(schema)),
            (
                9223372036854775807,
                "123456789012345678.12345678901234567890",
                '{"n":123456789012345678.12345678901234567890}',
                "2026-10-02 14:00:00+02",
                1,
            ),
        )
        cursor.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
        cursor.execute(
            sql.SQL("GRANT SELECT ON {}.claims TO {}").format(
                sql.Identifier(schema), sql.Identifier(role)
            )
        )
    config = {
        "configured": True,
        "values": {
            "host": "127.0.0.1",
            "port": "55432",
            "database": "agentium_pg_browser_test",
            "username": role,
        },
        "secrets": {"password": "isolated-test"},
    }
    monkeypatch.setattr(browser, "get_config", lambda *args, **kwargs: config)
    try:
        yield schema, hidden, admin
    finally:
        with admin.cursor() as cursor:
            for owned in (schema, hidden):
                cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(owned)))
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
        admin.close()


def selection(schema):
    metadata = browser.describe(object(), schema, "claims")
    return {
        "schema": schema,
        "table": "claims",
        "columns": ["id", "amount", "facts", "at"],
        "fingerprint": metadata["fingerprint"],
    }


def test_real_catalog_role_permissions_quoted_queries_and_exact_preview(postgres):
    schema, hidden, _ = postgres
    catalog = browser.catalog(object())
    assert {"schema": schema, "name": "claims", "kind": "table"} in catalog["tables"]
    assert not any(table["schema"] == hidden for table in catalog["tables"])
    metadata = browser.describe(object(), schema, "claims")
    assert (
        next(col for col in metadata["columns"] if col["name"] == "attachment")["supported"]
        is False
    )
    result = browser.read(object(), **selection(schema), limit=1)
    assert result["has_more"] is True and result["rows"][0]["id"] == 1
    complete = browser.read(object(), **selection(schema), limit=25)
    row = complete["rows"][1]
    assert row["id"] == "9223372036854775807"
    assert row["amount"] == "123456789012345678.12345678901234567890"
    assert "123456789012345678.12345678901234567890" in row["facts"]
    assert row["at"] == "2026-10-02T12:00:00+00:00"
    with browser._connection(object()) as (connection, _):
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            assert cursor.fetchone()[0] == "on"


def test_real_source_snapshot_becomes_native_dataset_and_survives_source_changes(
    postgres, db_session, tmp_path, monkeypatch
):
    from app.core.config import settings

    schema, _, admin = postgres
    workspace = Workspace(
        id=str(uuid4()), name="PG integration", slug=f"pg-{uuid4().hex[:8]}", settings={}
    )
    user = User(
        id=str(uuid4()),
        username=f"pg-{uuid4().hex[:8]}",
        email=f"pg-{uuid4().hex[:8]}@example.test",
        role="user",
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    selected = selection(schema)
    dataset, replayed = browser.import_dataset(
        db_session, workspace, user, name="Claims snapshot", request_id=str(uuid4()), **selected
    )
    db_session.commit()
    assert replayed is False and dataset.source == "postgresql" and dataset.row_count == 2
    frame = tabular_datasets.read_frame(dataset)
    assert frame["id"].to_list() == [1, 9223372036854775807]
    assert frame["amount"][1] == "123456789012345678.12345678901234567890"
    from app.services.tabular_transforms import run_sql_transform

    transformed = run_sql_transform(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT id, amount AS amount_exact FROM claims_snapshot WHERE amount IS NOT NULL",
        output_name="Prepared claims",
        declared=[{"view": "claims_snapshot", "dataset_id": dataset.id}],
    )
    prepared = tabular_datasets.get_dataset(
        db_session, workspace_id=workspace.id, dataset_id=transformed["dataset_id"]
    )
    assert (
        prepared.source == "transform"
        and prepared.parent_ids == [dataset.id]
        and prepared.row_count == 1
    )
    with admin.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER TABLE {}.claims ADD COLUMN new_column text").format(
                sql.Identifier(schema)
            )
        )
        cursor.execute(sql.SQL("DELETE FROM {}.claims").format(sql.Identifier(schema)))
    assert (
        tabular_datasets.read_frame(dataset).height == 2
    ), "the native snapshot is independent of the live table"
    with pytest.raises(browser.PostgresBrowseError) as error:
        browser.read(object(), **selected, limit=25)
    assert error.value.code == "PG_SOURCE_CHANGED"


def test_real_oversized_row_is_refused_before_transfer(postgres, monkeypatch):
    schema, _, _ = postgres
    selected = selection(schema)
    monkeypatch.setattr(browser, "MAX_PREVIEW_BYTES", 1)
    with pytest.raises(browser.PostgresBrowseError) as error:
        browser.read(object(), **selected, limit=25)
    assert error.value.code == "PG_RESULT_TOO_LARGE"


def test_schema_recheck_sees_ddl_committed_while_acquiring_the_table_lock(postgres, monkeypatch):
    schema, _, admin = postgres
    selected = selection(schema)
    original = browser._describe
    calls = 0

    def concurrent_ddl(connection, config, schema_name, table):
        nonlocal calls
        result = original(connection, config, schema_name, table)
        calls += 1
        if calls == 1:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("ALTER TABLE {}.claims ADD COLUMN concurrent_column text").format(
                        sql.Identifier(schema)
                    )
                )
        return result

    monkeypatch.setattr(browser, "_describe", concurrent_ddl)
    with pytest.raises(browser.PostgresBrowseError) as error:
        browser.read(object(), **selected, limit=25)
    assert error.value.code == "PG_SOURCE_CHANGED"


def test_real_batches_odd_identifiers_and_a_running_byte_budget(postgres, monkeypatch):
    schema, _, admin = postgres
    with admin.cursor() as cursor:
        cursor.execute(
            sql.SQL('CREATE TABLE {}.ratios (id int PRIMARY KEY, "growth_%" text)').format(
                sql.Identifier(schema)
            )
        )
        cursor.execute(
            sql.SQL(
                "INSERT INTO {}.ratios SELECT i, repeat('x', 10) FROM generate_series(1, 7) i"
            ).format(sql.Identifier(schema))
        )
    with browser._connection(object()) as (_, config):
        reader = config["values"]["username"]
    with admin.cursor() as cursor:
        cursor.execute(
            sql.SQL("GRANT SELECT ON {}.ratios TO {}").format(
                sql.Identifier(schema), sql.Identifier(reader)
            )
        )
    metadata = browser.describe(object(), schema, "ratios")
    selected = {
        "schema": schema,
        "table": "ratios",
        "columns": ["id", "growth_%"],
        "fingerprint": metadata["fingerprint"],
    }
    # Several round trips, read in primary-key order, with a "%" in a name.
    monkeypatch.setattr(browser, "FETCH_BATCH_ROWS", 2)
    result = browser.read(object(), **selected, limit=7)
    assert [row["id"] for row in result["rows"]] == list(range(1, 8))
    assert result["rows"][0]["growth_%"] == "x" * 10 and result["has_more"] is False
    # Each row weighs 11 bytes of text: from the fourth, the running total
    # crosses 40 bytes and the server sends the flag and NULLs, not the cells.
    columns = [col for col in metadata["columns"] if col["name"] in {"id", "growth_%"}]
    query = browser._bounded_query(
        schema, "ratios", columns, ["id"], "__fits", byte_limit=40, limit=8
    )
    with admin.cursor() as cursor:
        cursor.execute(query)
        flagged = cursor.fetchall()
    assert [row[0] for row in flagged] == [True] * 3 + [False] * 4
    assert flagged[3][1:] == (None, None)
    monkeypatch.setattr(browser, "MAX_PREVIEW_BYTES", 40)
    with pytest.raises(browser.PostgresBrowseError) as error:
        browser.read(object(), **selected, limit=7)
    assert error.value.code == "PG_RESULT_TOO_LARGE"
