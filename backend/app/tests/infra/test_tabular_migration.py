"""The slice's migrations, executed against PostgreSQL and compared to the ORM.

Every other suite builds its schema with ``Base.metadata.create_all``, which
never opens a migration file. The VM does the opposite: it restores a dump and
then runs ``alembic upgrade``. So the two schemas come from two different sources
of truth, and nothing was comparing them — which is invisible until a deployment,
and then loud: a column the model maps and the migration forgot fails *every*
``SELECT`` on the table, because SQLAlchemy names all mapped columns.

Both directions of that disagreement have already happened here, which is why
the chain is walked one revision at a time rather than read:

* a column mapped and not migrated — the failure above;
* the same five columns added by **both** 096 and 097, so the second one raised
  ``DuplicateColumn`` and the whole upgrade rolled back. A test that stopped at
  096 and compared to the ORM was satisfied by that, and the VM was not.

So the fixture stamps the parent of the slice and upgrades through the slice's
head, one step at a time: what is asserted is what the ``migrate`` step of the
deployment runbook actually produces.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, inspect

# The slice, in the order the deployment applies it. Listed rather than resolved
# from ``alembic heads`` so that a third revision has to be admitted here
# deliberately, and so a step-by-step upgrade is possible at all.
CHAIN = ("096_tabular_data_plane", "097_ml_training_plane")
HEAD = CHAIN[-1]
PARENT = "095_python_recipes"
SCRATCH_DB = "agentium_p4_migration_data_plane"

# The tables the slice owns. Their DDL has one source of truth per environment,
# and this module's whole job is to prove the two agree.
PLANE_TABLES = ("tabular_datasets", "ml_models", "ml_model_api_keys")


def _connection() -> dict[str, str]:
    """libpq settings for the instance to run the migration against.

    ``DATABASE_URL`` is the suite's own DSN, which ``conftest`` points at a
    throwaway SQLite file — so it is only a source of coordinates when it names
    a PostgreSQL instance. Otherwise the ambient ``PG*`` environment is what
    describes the local instance, including the unix socket directory that a
    container image typically hands over instead of a TCP host.
    """

    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn.startswith("postgres"):
        return {
            key: value
            for key, value in (
                ("PGHOST", os.environ.get("PGHOST", "localhost")),
                ("PGPORT", os.environ.get("PGPORT", "5432")),
                ("PGUSER", os.environ.get("PGUSER", "")),
                ("PGPASSWORD", os.environ.get("PGPASSWORD", "")),
            )
            if value
        }
    url = urlsplit(dsn.replace("postgresql+psycopg2://", "postgresql://", 1))
    environment = {
        "PGHOST": url.hostname or os.environ.get("PGHOST", "localhost"),
        "PGPORT": str(url.port or 5432),
    }
    if url.username:
        environment["PGUSER"] = url.username
    if url.password:
        environment["PGPASSWORD"] = url.password
    return environment


def _psql(database: str, sql: str) -> str:
    result = subprocess.run(
        ["psql", "-d", database, "-At", "-c", sql],
        capture_output=True,
        text=True,
        env={**os.environ, **_connection()},
    )
    if result.returncode != 0:
        raise RuntimeError(f"{sql}: {result.stderr.strip()}")
    return result.stdout.strip()


def _dsn() -> str:
    """The scratch database as a SQLAlchemy URL, socket directories included."""

    env = _connection()
    auth = env.get("PGUSER") or _psql("postgres", "select current_user")
    if env.get("PGPASSWORD"):
        auth = f"{auth}:{env['PGPASSWORD']}"
    host = env.get("PGHOST", "localhost")
    port = env.get("PGPORT", "5432")
    if host.startswith("/"):
        # A directory, not a hostname: libpq reads it as a unix socket, and the
        # URL form has to move it into the query string to say so.
        return f"postgresql://{auth}@/{SCRATCH_DB}?host={host}&port={port}"
    return f"postgresql://{auth}@{host}:{port}/{SCRATCH_DB}"


def _alembic(*argv: str) -> None:
    """Alembic against the scratch database, from the backend root."""

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    result = subprocess.run(
        ["alembic", *argv],
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": _dsn()},
    )
    if result.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(argv)} failed:\n{result.stdout}\n{result.stderr}"
        )


@pytest.fixture()
def migrated():
    """A database holding exactly what the slice's ``alembic upgrade`` produces.

    The pre-096 state is reduced to the one table 096 points a foreign key at.
    Restoring the real 95-revision history is neither possible from scratch in
    this repository nor the point: what has to be proven is the slice's own DDL.

    The upgrade goes one revision at a time. A single jump to the head would
    prove the same end state but not that each step lands — and an intermediate
    revision that fails is exactly what a deployment hits, because it applies
    them in the same order against a database that stops at the failure.
    """

    if not (shutil.which("psql") and shutil.which("alembic")):
        pytest.skip("psql/alembic are not installed")
    try:
        _psql("postgres", "select 1")
    except Exception as exc:  # noqa: BLE001 - no instance is a skip, not a failure
        pytest.skip(f"no reachable PostgreSQL: {exc}")

    _psql("postgres", f'drop database if exists "{SCRATCH_DB}"')
    _psql("postgres", f'create database "{SCRATCH_DB}"')
    try:
        _psql(SCRATCH_DB, "create table workspaces (id varchar(36) primary key)")
        _alembic("stamp", PARENT)
        for revision in CHAIN:
            _alembic("upgrade", revision)
        engine = create_engine(_dsn())
        try:
            yield engine
        finally:
            engine.dispose()
    finally:
        _psql("postgres", f'drop database if exists "{SCRATCH_DB}"')


def _orm_table(name: str):
    import app.models  # noqa: F401 - registers every mapped class
    from app.db.base import Base

    return Base.metadata.tables[name]


@pytest.mark.parametrize("table", PLANE_TABLES)
def test_the_migrated_table_has_every_column_the_model_maps(migrated, table):
    """The failure this module exists for: a column only the ORM knows about.

    A mapped column missing from the migration is invisible until a query runs
    on a migrated database, at which point *every* query on the table fails —
    SQLAlchemy names all of them in its SELECT list.
    """

    migrated_columns = {
        column["name"] for column in inspect(migrated).get_columns(table)
    }
    mapped_columns = {column.name for column in _orm_table(table).columns}

    assert mapped_columns - migrated_columns == set(), (
        f"{table}: mapped but not migrated — every SELECT on this table would "
        "fail on the VM"
    )
    # The other direction is a leftover: harmless to read, but it means the
    # migration and the model disagree about what the table is.
    assert migrated_columns - mapped_columns == set()


@pytest.mark.parametrize("table", PLANE_TABLES)
def test_the_migrated_table_agrees_with_the_model_on_what_may_be_missing(
    migrated, table
):
    """Nullability, because a NOT NULL the model does not know about is an
    insert that fails only in production."""

    migrated_nullable = {
        column["name"]: column["nullable"]
        for column in inspect(migrated).get_columns(table)
    }
    for column in _orm_table(table).columns:
        # A server default satisfies a NOT NULL the ORM fills in Python, so the
        # comparison is only meaningful where neither side supplies a value.
        if column.default is not None or column.server_default is not None:
            continue
        assert migrated_nullable[column.name] == column.nullable, (
            f"{table}.{column.name}: model says nullable={column.nullable}, "
            f"migration says {migrated_nullable[column.name]}"
        )


@pytest.mark.parametrize("table", PLANE_TABLES)
def test_the_indexes_the_queries_rely_on_exist_after_migrating(migrated, table):
    """Every listing in the data plane filters by workspace and by status.

    Those are sequential scans without the indexes, which is a demo that gets
    slower as it gets more interesting rather than a query that fails loudly.
    """

    migrated_indexes = {
        index["name"] for index in inspect(migrated).get_indexes(table)
    }
    mapped_indexes = {index.name for index in _orm_table(table).indexes}

    assert mapped_indexes <= migrated_indexes, (
        f"{table}: indexed on the model but not by the migration: "
        f"{sorted(mapped_indexes - migrated_indexes)}"
    )


@pytest.mark.parametrize("table", PLANE_TABLES)
def test_the_uniqueness_that_makes_a_version_a_version_is_enforced(migrated, table):
    """``(workspace, slug, version)`` is what lets two rows be v2 and v3 of one
    lineage rather than two names that happen to collide."""

    migrated_unique = {
        constraint["name"]
        for constraint in inspect(migrated).get_unique_constraints(table)
    }
    mapped_unique = {
        constraint.name
        for constraint in _orm_table(table).constraints
        if type(constraint).__name__ == "UniqueConstraint"
    }

    assert mapped_unique <= migrated_unique


def test_the_foreign_keys_cascade_the_way_a_deleted_workspace_needs(migrated):
    """Deleting a workspace must take its datasets and models with it, and
    deleting a dataset must not take the models fitted on it."""

    inspector = inspect(migrated)
    by_table = {
        table: {
            fk["referred_table"]: fk["options"].get("ondelete")
            for fk in inspector.get_foreign_keys(table)
        }
        for table in PLANE_TABLES
    }

    assert by_table["tabular_datasets"]["workspaces"] == "CASCADE"
    assert by_table["ml_models"]["workspaces"] == "CASCADE"
    # A model outlives the dataset it was fitted on: the fit already happened,
    # and the card still has to be able to say what it was fitted on.
    assert by_table["ml_models"]["tabular_datasets"] == "SET NULL"
    assert by_table["ml_model_api_keys"]["ml_models"] == "CASCADE"
    assert by_table["ml_model_api_keys"]["workspaces"] == "CASCADE"


def test_a_row_the_application_would_write_actually_inserts(migrated):
    """The end of the argument: the ORM writing through the migrated schema.

    Column lists, nullability and defaults can each look right and still not
    accept the insert the ingest worker makes, so the last check makes it.
    """

    import app.models  # noqa: F401
    from app.models.tabular import MLModel, TabularDataset
    from sqlalchemy.orm import Session

    with migrated.begin() as connection:
        connection.exec_driver_sql("insert into workspaces (id) values ('ws-1')")

    with Session(migrated) as session:
        dataset = TabularDataset(
            id="ds-1",
            workspace_id="ws-1",
            name="Churn",
            slug="churn",
            source="upload",
            status="ready",
        )
        session.add(dataset)
        session.flush()
        model = MLModel(
            id="m-1",
            workspace_id="ws-1",
            name="Churn",
            slug="churn",
            task="classification",
            algo="gradient_boosting",
            target="churn",
            dataset_id="ds-1",
            status="ready",
        )
        session.add(model)
        session.commit()

        stored = session.get(MLModel, "m-1")
        # The five columns the second revision adds are exactly the ones a fresh
        # row has to be able to report, so read them back rather than trusting
        # the insert alone.
        assert stored is not None
        assert stored.cancel_requested is False
        assert stored.predict_count == 0
        assert stored.last_predict_at is None
        assert stored.artifact_bytes is None
        assert stored.dataset_id == "ds-1"


def test_no_two_revisions_of_the_slice_add_the_same_column(migrated):
    """The bug this pins: a column added by 096 *and* by 097.

    The second ``ADD COLUMN`` raises ``DuplicateColumn``, alembic's transaction
    rolls back, and the deployment ends with the whole slice absent — the
    schema is intact, so nothing looks broken until someone reads the log. The
    chain in the fixture is already the reproduction; this states the invariant
    so the failure reads as what it is instead of as a fixture error.
    """

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    added: dict[str, str] = {}
    for revision in CHAIN:
        path = os.path.join(root, "alembic", "versions", f"{revision}.py")
        with open(path) as handle:
            source = handle.read()
        upgrade = source.split("def upgrade", 1)[-1].split("def downgrade", 1)[0]
        for match in re.finditer(
            r"add_column\(\s*\"(?P<table>\w+)\",\s*sa\.Column\(\s*\n?\s*\"(?P<column>\w+)\"",
            upgrade,
        ):
            key = f"{match.group('table')}.{match.group('column')}"
            assert key not in added, (
                f"{key} is added by both {added[key]} and {revision} — the "
                "second one will fail and roll the whole upgrade back"
            )
            added[key] = revision


def test_the_slice_reverts_cleanly_so_a_rollback_is_real(migrated):
    """The deployment runbook dumps before migrating; a downgrade that leaves
    half a schema behind makes that dump the only way back."""

    _alembic("downgrade", PARENT)

    remaining = set(inspect(migrated).get_table_names())
    assert remaining & set(PLANE_TABLES) == set()
    # And forward again, because a one-way downgrade is not a rollback.
    _alembic("upgrade", HEAD)
    assert set(PLANE_TABLES) <= set(inspect(migrated).get_table_names())
