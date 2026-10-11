"""SQL transforms: what the author can express, and what the engine refuses."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.workspace import Workspace
from app.services.tabular_datasets import TabularError, register_frame
from app.services.tabular_transforms import (
    execute_sql,
    preview_sql,
    resolve_sources,
    run_sql_transform,
    source_catalog,
    validate_sql,
    view_name_for,
)

pl = pytest.importorskip("polars")
pytest.importorskip("duckdb")


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="Transforms",
        slug=f"transforms-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def object_store_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    return tmp_path / "store"


@pytest.fixture()
def customers(db_session, workspace, object_store_root):
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Customers",
        frame=pl.DataFrame(
            {
                "customer_id": ["C1", "C2", "C3", "C4"],
                "tenure_months": [12, 36, 3, 24],
                "monthly_charges": [45.5, 80.25, 20.0, 60.0],
                "contract": ["monthly", "yearly", "monthly", "yearly"],
                "churn": [1, 0, 1, 0],
            }
        ),
        source="upload",
    )
    db_session.commit()
    return dataset


@pytest.fixture()
def usage(db_session, workspace, object_store_root):
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Usage monthly",
        frame=pl.DataFrame(
            {
                "customer_id": ["C1", "C2", "C3", "C4"],
                "gb_used": [12.5, 40.0, 2.0, 18.0],
            }
        ),
        source="upload",
    )
    db_session.commit()
    return dataset


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM input",
        "with base as (select 1 as x) select * from base",
        "FROM input SELECT customer_id",
        "SELECT count(*) AS n FROM input WHERE contract = 'monthly'",
        "  \nSELECT 1\n  ",
        "SELECT * FROM input; ",  # a single trailing semicolon is fine
    ],
)
def test_read_only_statements_are_accepted(sql):
    assert validate_sql(sql)


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("", "SQL_EMPTY"),
        ("   ", "SQL_EMPTY"),
        ("DROP TABLE input", "SQL_FORBIDDEN_KEYWORD"),
        ("CREATE TABLE t AS SELECT 1", "SQL_FORBIDDEN_KEYWORD"),
        ("INSERT INTO input VALUES (1)", "SQL_FORBIDDEN_KEYWORD"),
        ("ATTACH 'x.db' AS x", "SQL_FORBIDDEN_KEYWORD"),
        ("COPY input TO '/tmp/out.csv'", "SQL_FORBIDDEN_KEYWORD"),
        ("PRAGMA database_list", "SQL_FORBIDDEN_KEYWORD"),
        ("SET memory_limit='99GB'", "SQL_FORBIDDEN_KEYWORD"),
        ("INSTALL httpfs", "SQL_FORBIDDEN_KEYWORD"),
        # Stacking a second statement is reported as such: that is the first
        # thing the author has to fix, whatever the second statement does.
        ("SELECT * FROM input; DROP TABLE input", "SQL_MULTIPLE_STATEMENTS"),
        ("SELECT 1; SELECT 2", "SQL_MULTIPLE_STATEMENTS"),
        ("SELECT * FROM read_csv('/etc/passwd')", "SQL_FORBIDDEN_FUNCTION"),
        ("SELECT * FROM read_parquet('/data/secret.parquet')", "SQL_FORBIDDEN_FUNCTION"),
        ("SELECT * FROM glob('/**')", "SQL_FORBIDDEN_FUNCTION"),
        ("EXPLAIN ANALYZE SELECT 1", "SQL_NOT_READ_ONLY"),
    ],
)
def test_dangerous_statements_are_refused_with_an_actionable_code(sql, code):
    with pytest.raises(TabularError) as error:
        validate_sql(sql)
    assert error.value.code == code
    assert error.value.message


def test_a_keyword_inside_a_literal_or_comment_does_not_trip_validation():
    """False positives would make legitimate business SQL unwritable."""

    assert validate_sql("SELECT * FROM input WHERE reason = 'delete requested'")
    assert validate_sql("SELECT * FROM input -- drop the yearly ones later\n")
    assert validate_sql("/* create a cohort */ SELECT 1")
    # A column literally named after a keyword still has to be refused: the
    # scan cannot tell it from a statement, and failing closed is the right side.
    with pytest.raises(TabularError):
        validate_sql("SELECT create FROM input")


def test_the_engine_itself_refuses_to_reach_the_filesystem_or_the_network(tmp_path):
    """The parser is the readable refusal; this is the one that has to hold.

    An allow-list of function names is a guess about syntax — duckdb grows
    readers, and ``FROM 'path'`` needs no function name at all. So the guard
    that matters is the connection the author's SQL actually runs on, and both
    of its settings have to be *on*: ``disabled_filesystems`` alone says nothing
    about an httpfs or S3 filesystem, which is exactly what an exfiltration
    attempt would use.

    The parquet read before the seal is not decoration. It is the state the real
    connection is in — ``execute_sql`` loads every source eagerly and only then
    seals — and it is the state in which the two ``SET``s stop being
    interchangeable: once ``LocalFileSystem`` is disabled, the *next* ``SET``
    raises, because duckdb touches the filesystem while applying it. A
    connection that had read nothing accepts either order and would prove
    nothing.
    """

    import duckdb
    import polars as pl

    from app.services.tabular_transforms import _seal_filesystem

    source = tmp_path / "input.parquet"
    pl.DataFrame({"a": [1]}).write_parquet(source)

    connection = duckdb.connect(database=":memory:")
    connection.execute(f"CREATE TABLE input AS SELECT * FROM read_parquet('{source}')")
    _seal_filesystem(connection)

    # ``enable_external_access`` reads back; ``disabled_filesystems`` does not
    # (duckdb reports it empty however it was set), so it is the refusals below
    # that stand for it rather than a settings row.
    external_access = connection.execute(
        "SELECT value FROM duckdb_settings() WHERE name = 'enable_external_access'"
    ).fetchone()
    assert external_access == ("false",), (
        "the seal applied in the wrong order: disabling the local filesystem "
        "first makes this SET fail, and only the weaker guard survives"
    )

    for statement in (
        "SELECT * FROM read_csv('/etc/hostname')",
        "SELECT * FROM '/etc/hostname'",
        "SELECT * FROM 'https://example.com/x.parquet'",
        "SELECT * FROM read_parquet('s3://bucket/key.parquet')",
        f"SELECT * FROM read_parquet('{source}')",
    ):
        with pytest.raises(Exception):
            connection.execute(statement).fetchall()

    # And the input the transform is about still reads, or the seal would have
    # closed the door on the query it exists to run.
    assert connection.execute("SELECT a FROM input").fetchall() == [(1,)]
    connection.close()


def test_statement_length_is_capped(monkeypatch):
    monkeypatch.setattr(settings, "tabular_sql_max_chars", 20)
    with pytest.raises(TabularError) as error:
        validate_sql("SELECT * FROM input WHERE customer_id = 'C1'")
    assert error.value.code == "SQL_TOO_LONG"


# ---------------------------------------------------------------------------
# Source naming
# ---------------------------------------------------------------------------


def test_view_names_are_duckdb_safe_and_never_collide():
    assert view_name_for("Usage monthly", []) == "usage_monthly"
    assert view_name_for("Churn — Été 2026", []) == "churn_ete_2026"
    assert view_name_for("Usage monthly", ["usage_monthly"]) == "usage_monthly_2"
    # A name that survives slugification as nothing usable still yields a view.
    assert view_name_for("...", []) == "input"
    assert view_name_for("2024 revenue", []).startswith("_") is False


def test_sources_resolve_from_upstream_payload_and_declared_pins(
    db_session, workspace, customers, usage
):
    from_payload = resolve_sources(
        db_session,
        workspace_id=workspace.id,
        payload={"dataset_id": customers.id},
    )
    assert [source.view for source in from_payload] == ["customers"]

    declared = resolve_sources(
        db_session,
        workspace_id=workspace.id,
        declared=[
            {"view": "c", "dataset_id": customers.id},
            {"view": "u", "dataset_slug": usage.slug},
        ],
    )
    assert [source.view for source in declared] == ["c", "u"]

    # A dataset pinned on the node and also arriving upstream is loaded once.
    deduped = resolve_sources(
        db_session,
        workspace_id=workspace.id,
        declared=[{"view": "c", "dataset_id": customers.id}],
        payload={"dataset_id": customers.id},
    )
    assert len(deduped) == 1


def test_a_transform_with_no_input_refuses_before_touching_the_engine(
    db_session, workspace
):
    with pytest.raises(TabularError) as error:
        resolve_sources(db_session, workspace_id=workspace.id, payload={})
    assert error.value.code == "TRANSFORM_NO_INPUT"


def test_source_catalog_describes_what_the_editor_can_autocomplete(
    db_session, workspace, customers, usage
):
    sources = resolve_sources(
        db_session,
        workspace_id=workspace.id,
        declared=[
            {"view": "customers", "dataset_id": customers.id},
            {"view": "usage", "dataset_id": usage.id},
        ],
    )

    catalog = source_catalog(sources)

    assert [entry["view"] for entry in catalog] == ["customers", "usage"]
    # The first source is always reachable as `input`, so a one-input transform
    # has a name the author can type without looking anything up.
    assert "input" in catalog[0]["aliases"]
    assert "input_1" in catalog[0]["aliases"]
    assert "input_2" in catalog[1]["aliases"]
    assert {col["name"] for col in catalog[0]["columns"]} >= {"customer_id", "churn"}


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def test_execute_reads_the_input_alias_and_the_slug_view(
    db_session, workspace, customers
):
    sources = resolve_sources(
        db_session, workspace_id=workspace.id, payload={"dataset_id": customers.id}
    )

    by_alias = execute_sql(sources, "SELECT count(*) AS n FROM input")
    by_slug = execute_sql(sources, "SELECT count(*) AS n FROM customers")

    assert by_alias.get_column("n").to_list() == [4]
    assert by_slug.get_column("n").to_list() == [4]


def test_execute_joins_two_sources_and_computes_business_columns(
    db_session, workspace, customers, usage
):
    sources = resolve_sources(
        db_session,
        workspace_id=workspace.id,
        declared=[
            {"view": "customers", "dataset_id": customers.id},
            {"view": "usage", "dataset_id": usage.id},
        ],
    )

    frame = execute_sql(
        sources,
        """
        SELECT c.customer_id,
               c.tenure_months,
               u.gb_used,
               c.monthly_charges / NULLIF(u.gb_used, 0) AS cost_per_gb,
               c.churn
        FROM customers c
        JOIN usage u USING (customer_id)
        WHERE c.contract = 'monthly'
        ORDER BY c.customer_id
        """,
    )

    assert frame.height == 2
    assert frame.get_column("customer_id").to_list() == ["C1", "C3"]
    assert round(frame.get_column("cost_per_gb").to_list()[0], 2) == 3.64


def test_the_engine_seals_the_filesystem_after_loading_inputs(
    db_session, workspace, customers, tmp_path
):
    """Defence in depth: even a statement validation missed must not read files."""

    secret = tmp_path / "secret.csv"
    secret.write_text("a\n1\n", encoding="utf-8")
    sources = resolve_sources(
        db_session, workspace_id=workspace.id, payload={"dataset_id": customers.id}
    )

    with pytest.raises(TabularError) as error:
        # Bypass validate_sql the way a validation gap would, by calling the
        # engine with a statement the scanner would have refused.
        execute_sql(sources, f"SELECT * FROM \"{secret}\"")
    assert error.value.code == "SQL_EXECUTION_FAILED"


def test_a_broken_statement_returns_the_engine_message_not_a_stack_trace(
    db_session, workspace, customers
):
    sources = resolve_sources(
        db_session, workspace_id=workspace.id, payload={"dataset_id": customers.id}
    )

    with pytest.raises(TabularError) as error:
        execute_sql(sources, "SELECT nope FROM input")

    assert error.value.code == "SQL_EXECUTION_FAILED"
    assert "nope" in error.value.message
    assert "\n" not in error.value.message


def test_an_oversized_result_is_refused_rather_than_silently_trimmed(
    db_session, workspace, customers, monkeypatch
):
    monkeypatch.setattr(settings, "tabular_transform_max_rows", 2)
    sources = resolve_sources(
        db_session, workspace_id=workspace.id, payload={"dataset_id": customers.id}
    )

    with pytest.raises(TabularError) as error:
        execute_sql(sources, "SELECT * FROM input")
    assert error.value.code == "SQL_RESULT_TOO_LARGE"


def test_preview_returns_the_same_profile_shape_the_dataset_pages_render(
    db_session, workspace, customers
):
    result = preview_sql(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT contract, avg(monthly_charges) AS arpu FROM input GROUP BY 1 ORDER BY 1",
        payload={"dataset_id": customers.id},
    )

    assert result["row_count"] == 2
    assert [col["name"] for col in result["schema"]] == ["contract", "arpu"]
    assert result["preview"][0]["contract"] == "monthly"
    assert result["stats"]["arpu"]["kind"] == "float"
    # The timing badge the workshop shows comes from here.
    assert result["duration_ms"] >= 0
    assert result["sources"][0]["view"] == "customers"


def test_preview_caps_rows_without_failing_on_a_wide_input(
    db_session, workspace, customers
):
    result = preview_sql(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT * FROM input",
        payload={"dataset_id": customers.id},
        row_limit=2,
    )

    assert result["row_count"] == 2


def test_run_persists_a_versioned_dataset_with_its_lineage(
    db_session, workspace, customers, usage
):
    first = run_sql_transform(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT customer_id, churn FROM customers",
        output_name="Churn labels",
        declared=[
            {"view": "customers", "dataset_id": customers.id},
            {"view": "usage", "dataset_id": usage.id},
        ],
        run_id="run-42",
        node_id="node-sql",
    )

    from app.models.tabular import TabularDataset

    row = db_session.query(TabularDataset).filter_by(id=first["dataset_id"]).one()
    assert row.status == "ready"
    assert row.source == "transform"
    assert row.produced_by == "sql_transform_v1"
    assert row.row_count == 4 and row.column_count == 2
    assert sorted(row.parent_ids) == sorted([customers.id, usage.id])
    assert row.run_id == "run-42" and row.node_id == "node-sql"
    assert row.lineage_json["engine"] == "duckdb"
    assert "customer_id" in row.lineage_json["sql"]

    # The envelope carries what the canvas badge shows, by reference.
    assert first["rows"] == 4 and first["columns"] == 2
    assert first["sources"] == ["customers", "usage"]

    # Re-running the same node versions the slug instead of overwriting.
    second = run_sql_transform(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT customer_id FROM customers",
        output_name="Churn labels",
        declared=[{"view": "customers", "dataset_id": customers.id}],
    )
    assert second["slug"] == first["slug"]
    assert second["version"] == first["version"] + 1


def test_the_result_of_a_transform_can_feed_the_next_one(
    db_session, workspace, customers
):
    """Chaining is the whole point: a transform output is a first-class input."""

    first = run_sql_transform(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT customer_id, monthly_charges * 12 AS annual FROM input",
        output_name="Annualized",
        payload={"dataset_id": customers.id},
    )

    second = run_sql_transform(
        db_session,
        workspace_id=workspace.id,
        sql="SELECT count(*) AS n, sum(annual) AS total FROM input",
        output_name="Annual totals",
        payload=first,
    )

    from app.models.tabular import TabularDataset

    row = db_session.query(TabularDataset).filter_by(id=second["dataset_id"]).one()
    assert row.parent_ids == [first["dataset_id"]]
    assert row.preview_json[0]["n"] == 4


@pytest.mark.parametrize(
    "sql,line,column,token",
    [
        # A typo in the first keyword: the caret is at the very start.
        ("SELEC a FROM input", 1, 1, "SELEC"),
        # A bad column on the third line of a formatted query — the case the
        # message alone handles worst, because it names the column and leaves
        # the author to find which of the lines it is on.
        ("SELECT\n  a,\n  nosuchcol\nFROM input", 3, 3, "nosuchcol"),
        ("SELECT a FROM nosuchtable", 1, 15, "nosuchtable"),
        ("SELECT a FROM input WHERE a > 'x'", 1, 31, "'x'"),
    ],
)
def test_a_refused_statement_carries_the_place_the_engine_stopped(sql, line, column, token):
    """duckdb already knows where; throwing it away is what makes it a hunt.

    Every parser, binder, catalog and conversion error echoes the offending line
    and puts a ``^`` under the token. Keeping only the sentence leaves the
    author counting lines under "Referenced column not found". The coordinate is
    asserted by slicing the author's own SQL at it: an off-by-one in the caret
    arithmetic would land the cursor next to the problem rather than on it,
    which is worse than not moving it at all.
    """

    import duckdb

    from app.services.tabular_transforms import _positioned_failure

    connection = duckdb.connect()
    connection.execute("CREATE TABLE input AS SELECT 1 AS a")
    try:
        # Through the relational API, which is the one `execute_sql` runs the
        # author's statement on — and the one that drops the position for a
        # binder or catalog error, so this exercises the second ask too.
        connection.sql(sql).limit(51).arrow()
    except Exception as exc:  # noqa: BLE001 - the error is the subject
        found = _positioned_failure(connection, sql, exc)
    else:  # pragma: no cover - every case above is a refusal
        raise AssertionError(f"{sql!r} did not fail")
    finally:
        connection.close()

    assert found is not None, "duckdb reported a place and it was dropped"
    at = found["position"]
    assert (at["line"], at["column"]) == (line, column)
    # The caret lands ON the token, not beside it.
    assert sql.splitlines()[at["line"] - 1][at["column"] - 1 :].startswith(token)


def test_an_error_with_no_place_says_so_rather_than_guessing_one():
    """A cursor sent to line 1 on every failure is worse than a cursor unmoved.

    Not every refusal belongs to a token — a result-too-large or an engine-level
    fault has no coordinate — and inventing one would move the author's caret
    away from wherever they were working, for no reason.
    """

    from app.services.tabular_transforms import _error_position

    statement = "SELECT a FROM input"
    assert _error_position(RuntimeError("Out of Memory Error"), statement) is None
    assert _error_position(RuntimeError(""), statement) is None

    # And the guard that matters: duckdb's relational API reports positions
    # against its own rewritten SQL. A coordinate whose echoed line is not the
    # author's line would send their cursor into text they never typed, so it is
    # refused rather than trusted.
    rewritten = RuntimeError(
        'Conversion Error: Could not convert string\n\n'
        'LINE 1: SELECT a FROM "input" WHERE (a > \'x\') LIMIT 5\n'
        '                                          ^'
    )
    assert _error_position(rewritten, "SELECT a FROM input WHERE a > 'x'") is None


def test_the_refusal_the_workshop_receives_includes_the_coordinate(
    db_session, workspace, customers
):
    """End to end, because the position has to survive the error payload.

    ``TabularError.payload()`` flattens ``details`` into the response body, so
    this is the shape the editor actually reads back — and the reason the
    coordinate goes in ``details`` rather than into the message text.
    """

    with pytest.raises(TabularError) as error:
        preview_sql(
            db_session,
            workspace_id=workspace.id,
            sql="SELECT\n  contract,\n  nosuchcol\nFROM input",
            payload={"dataset_id": customers.id},
        )

    body = error.value.payload()
    assert body["code"] == "SQL_EXECUTION_FAILED"
    assert body["position"] == {"line": 3, "column": 3, "excerpt": "  nosuchcol"}
    # The sentence still stands on its own; the coordinate is an addition.
    assert "nosuchcol" in body["message"]
