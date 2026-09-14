"""The sharepoint_sync_jobs slice, migrated onto a genuinely empty SQLite file.

``sharepoint_sync_jobs`` reached every existing environment through
``Base.metadata.create_all`` at startup, never through a migration. So the two
revisions that alter it — 013 adding the ingest counters, 014 adding
``workspace_id`` — were written against a table Alembic had not created, and
nothing noticed: every database they ran on already had it.

A database built only from migrations does not. ``alembic upgrade head`` on a
new SQLite file died at 013 with ``no such table: sharepoint_sync_jobs`` and
stamped nothing past 012, which is the whole bootstrap, not one table.

This is therefore driven as a real ``alembic upgrade`` subprocess against a
fresh file, one revision at a time. ``create_all`` would prove nothing here —
it is the very shortcut that hid the gap, and it builds the schema from the
model the assertions also read. The upgrade is stepped rather than jumped to
the head because a deployment applies revisions in order against a database
that stops at the first failure, so a mid-chain break is exactly the failure
mode worth reproducing.

Both starting states are covered, since the fix has to hold for both:

* empty — nothing exists, 012a must create the table;
* legacy — a ``create_all`` table already present at 012, which 012a must
  leave alone, rows included.

They are asserted to converge on the same schema, and that schema is compared
against ``SharePointSyncJob.__table__`` rather than a restated column list, so
a future model column that no migration adds fails here instead of on the VM.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.models.sharepoint_sync_job import SharePointSyncJob

BACKEND_ROOT = Path(__file__).resolve().parents[3]
TABLE = "sharepoint_sync_jobs"

# The slice in the order a deployment applies it. 012a is the revision this
# module exists for; 013 and 014 are what it has to make runnable.
PARENT = "012_chat_runs_nullable_sys"
CHAIN = ("012a_sp_sync_jobs", "013_sp_ingest_columns", "014_sp_workspace_id")
HEAD = CHAIN[-1]

# The table as ``create_all`` built it before 013/014: the model minus the
# three columns 013 adds and the ``workspace_id`` 014 adds. This is the legacy
# state 012a must detect and step around.
LEGACY_DDL = """
create table sharepoint_sync_jobs (
    id varchar(36) not null primary key,
    session_key varchar(255) not null,
    auth_mode varchar(16) not null,
    state varchar(20) not null,
    status varchar(30),
    progress varchar(120),
    files_total integer,
    files_downloaded integer,
    bytes_total integer,
    login_required_detail text,
    error text,
    output_dir text,
    folder_server_relative_url text,
    created_at datetime not null,
    updated_at datetime not null
)
"""
LEGACY_INDEX = (
    "create index ix_sharepoint_sync_jobs_session_key on sharepoint_sync_jobs (session_key)"
)
LEGACY_ROW = (
    "insert into sharepoint_sync_jobs "
    "(id, session_key, auth_mode, state, status, created_at, updated_at) "
    "values ('legacy-job-1', 'ws_1__operator', 'session', 'completed', "
    "'completed', '2026-04-20 10:00:00', '2026-04-20 10:05:00')"
)


def _alembic(database: Path, *argv: str) -> None:
    """Alembic against ``database``, run the way the deployment runs it.

    ``sys.executable -m`` rather than a bare ``alembic`` so the subprocess is
    the interpreter running the suite, and ``AGENTIUM_DISABLE_DOTENV`` so a
    developer's ``backend/.env`` cannot redirect the upgrade onto a real
    database — ``env.py`` builds the URL from ``settings``, which reads that
    file by default.
    """

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *argv],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DATABASE_URL": f"sqlite:///{database}",
            "AGENTIUM_DISABLE_DOTENV": "1",
        },
    )
    if result.returncode != 0:
        raise AssertionError(f"alembic {' '.join(argv)} failed:\n{result.stdout}\n{result.stderr}")


def _step_up(database: Path, *revisions: str) -> None:
    for revision in revisions:
        _alembic(database, "upgrade", revision)


def _sqlite(database: Path, *statements: str) -> None:
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        with engine.begin() as connection:
            for statement in statements:
                connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


def _inspect(database: Path) -> dict[str, object]:
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        inspector = sa.inspect(engine)
        tables = set(inspector.get_table_names())
        if TABLE not in tables:
            # Before 012a and after its downgrade, so the callers that assert
            # absence can read the same shape as the ones that assert schema.
            return {
                "tables": tables,
                "columns": {},
                "indexes": {},
                "foreign_keys": set(),
            }
        return {
            "tables": tables,
            "columns": {
                column["name"]: column["nullable"] for column in inspector.get_columns(TABLE)
            },
            "indexes": {
                index["name"]: tuple(index["column_names"])
                for index in inspector.get_indexes(TABLE)
            },
            "foreign_keys": {
                (
                    tuple(fk["constrained_columns"]),
                    fk["referred_table"],
                    tuple(fk["referred_columns"]),
                )
                for fk in inspector.get_foreign_keys(TABLE)
            },
        }
    finally:
        engine.dispose()


def _rows(database: Path) -> list[tuple]:
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            return connection.execute(
                sa.text(
                    "select id, state, status, ingested_count, "
                    "ingest_failed_count, collection_name, workspace_id "
                    f"from {TABLE} order by id"
                )
            ).all()
    finally:
        engine.dispose()


@pytest.fixture()
def database(tmp_path: Path) -> Path:
    """A path with no file at it — SQLite creates the database on connect."""

    path = tmp_path / "bootstrap.db"
    assert not path.exists(), "the migration path must start from nothing"
    return path


def test_empty_database_migrates_through_the_slice(database: Path) -> None:
    """Base through 014 on a new file — the bootstrap that used to die at 013."""

    _alembic(database, "upgrade", PARENT)
    assert TABLE not in _inspect(database)["tables"], (
        "Nothing before 012a may create the table, or this test proves nothing about 012a."
    )

    _step_up(database, *CHAIN)

    schema = _inspect(database)
    assert TABLE in schema["tables"]
    assert set(schema["columns"]) == {
        column.name for column in SharePointSyncJob.__table__.columns
    }, (
        "The migrated table and the ORM model disagree on columns. Every mapped "
        "column is named in SQLAlchemy's SELECT, so one the migrations forgot "
        "breaks every read of this table."
    )


def test_migrated_columns_match_the_model_nullability(database: Path) -> None:
    """A column present but wrongly nullable fails writes, not reads."""

    _alembic(database, "upgrade", PARENT)
    _step_up(database, *CHAIN)

    migrated = _inspect(database)["columns"]
    assert migrated == {
        column.name: column.nullable for column in SharePointSyncJob.__table__.columns
    }


def test_slice_creates_the_session_key_index_and_workspace_foreign_key(
    database: Path,
) -> None:
    _alembic(database, "upgrade", PARENT)
    _step_up(database, *CHAIN)

    schema = _inspect(database)
    assert schema["indexes"]["ix_sharepoint_sync_jobs_session_key"] == ("session_key",)
    assert schema["indexes"]["ix_sharepoint_sync_jobs_workspace_id"] == ("workspace_id",)
    assert (
        ("workspace_id",),
        "workspaces",
        ("id",),
    ) in schema["foreign_keys"], (
        "014 must still attach workspace_id to workspaces. On SQLite the batch "
        "rewrite replays the constraint, which needs it to be named."
    )


def test_slice_round_trips_down_to_base_and_back(database: Path) -> None:
    """Downgrade must undo the slice, and the replay must land where it did."""

    _alembic(database, "upgrade", PARENT)
    _step_up(database, *CHAIN)
    before = _inspect(database)

    _alembic(database, "downgrade", PARENT)
    assert TABLE not in _inspect(database)["tables"], (
        "012a's downgrade left the table behind; a re-upgrade would then be "
        "creating a table that already exists."
    )

    _alembic(database, "downgrade", "base")
    _alembic(database, "upgrade", PARENT)
    _step_up(database, *CHAIN)

    assert _inspect(database) == before


def test_legacy_create_all_table_survives_the_slice(database: Path) -> None:
    """The state 013/014 were written for: the table is already there at 012."""

    _alembic(database, "upgrade", PARENT)
    _sqlite(database, LEGACY_DDL, LEGACY_INDEX, LEGACY_ROW)

    _step_up(database, *CHAIN)

    assert _rows(database) == [("legacy-job-1", "completed", "completed", 0, 0, None, None)], (
        "Pre-existing sync history must survive the catch-up, picking up the "
        "documented defaults: 0/0 counters, no collection, no workspace."
    )


def test_empty_and_legacy_bootstraps_converge_on_one_schema(
    tmp_path: Path,
) -> None:
    """Whoever created the table, the slice has to leave the same schema."""

    empty = tmp_path / "empty.db"
    legacy = tmp_path / "legacy.db"

    _alembic(empty, "upgrade", PARENT)
    _step_up(empty, *CHAIN)

    _alembic(legacy, "upgrade", PARENT)
    _sqlite(legacy, LEGACY_DDL, LEGACY_INDEX)
    _step_up(legacy, *CHAIN)

    assert _inspect(empty) == _inspect(legacy)


def test_head_still_descends_from_the_repaired_slice() -> None:
    """012a must sit inside the real chain, not dangle beside it."""

    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(BACKEND_ROOT / "alembic"))
    lineage = {revision.revision for revision in script.walk_revisions()}
    assert set(CHAIN) <= lineage
    assert script.get_revision(HEAD).down_revision == "013_sp_ingest_columns"
    assert script.get_revision("013_sp_ingest_columns").down_revision == ("012a_sp_sync_jobs")
    assert script.get_revision("012a_sp_sync_jobs").down_revision == PARENT
