"""A brand-new SQLite database, migrated all the way to the single head.

Agentium's local and demo installs are SQLite. Its deployments are PostgreSQL,
and for years only PostgreSQL ran the migrations end to end — every SQLite
database in existence was built by ``Base.metadata.create_all`` at startup,
which reads the ORM and never opens a revision file. So a whole class of
revision was written, reviewed, and shipped without anyone running it on
SQLite:

* ``op.add_column(..., sa.ForeignKey(...))`` — one ``ALTER TABLE ADD COLUMN``
  plus one ``ALTER TABLE ADD CONSTRAINT`` on PostgreSQL, and on SQLite a flat
  ``NotImplementedError: No support for ALTER of constraints in SQLite
  dialect``, because SQLite has no ALTER for constraints at all;
* ``op.create_foreign_key`` / ``op.create_check_constraint`` — the same wall,
  reached directly;
* ``op.alter_column(..., server_default=None)`` — ``ALTER TABLE t ALTER COLUMN
  c DROP DEFAULT``, which SQLite parses as a syntax error.

Each one stops ``alembic upgrade head`` dead and stamps nothing past the
revision before it, so the install has no schema, not one missing column. The
repair is ``batch_alter_table`` with named constraints: a pass-through to the
identical ALTERs on PostgreSQL, and a copy-and-move of the table on SQLite.

This module therefore drives real ``alembic`` subprocesses against real
temporary SQLite files, the way a deployment does. ``create_all`` is not an
option here even as a shortcut — it is precisely the thing that hid every one
of these failures, and it builds the schema from the same model an assertion
would read, so it can agree with itself while the migrations are broken.

What is asserted is schema and behaviour, never source text: the columns,
indexes and foreign keys the revisions intend, that the foreign keys actually
reject an orphan row, that the check constraints the rewrite replayed still
reject a bad value, and that the default 031 drops is really gone.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

BACKEND_ROOT = Path(__file__).resolve().parents[3]

# The revisions repaired for this bootstrap, each with the revision a
# downgrade lands on. Listed in the order a clean upgrade reaches them, which
# is also the order the failures appeared.
REPAIRED = (
    ("023_capture_attribution", "022_workspace_iam_foundations"),
    ("031_table_intelligence", "030_knowledge_guides"),
    ("037_chat_sessions_workspace_jobs", "036_retrieval_job_kinds"),
    ("052_client360_campaigns", "051_client360_pdr_merge"),
    ("099_data_plane_attached", "098_ml_predictions"),
)

# (revision, table, column, index, referred table, on delete) for every link
# the repaired revisions attach. All of them are nullable by design: they are
# attribution and lineage, not requirements.
REPAIRED_LINKS = (
    (
        "023_capture_attribution",
        "expert_capture_sessions",
        "created_by_user_id",
        "ix_expert_capture_sessions_created_by_user_id",
        "users",
        None,
    ),
    (
        "023_capture_attribution",
        "knowledge_update_proposals",
        "created_by_user_id",
        "ix_knowledge_update_proposals_created_by_user_id",
        "users",
        None,
    ),
    (
        "023_capture_attribution",
        "knowledge_update_proposals",
        "reviewer_user_id",
        "ix_knowledge_update_proposals_reviewer_user_id",
        "users",
        None,
    ),
    (
        "023_capture_attribution",
        "runs",
        "initiated_by_user_id",
        "ix_runs_initiated_by_user_id",
        "users",
        None,
    ),
    (
        "037_chat_sessions_workspace_jobs",
        "workspace_jobs",
        "session_id",
        "ix_workspace_jobs_session_id",
        "sessions",
        "SET NULL",
    ),
    (
        "037_chat_sessions_workspace_jobs",
        "workspace_jobs",
        "collection_id",
        "ix_workspace_jobs_collection_id",
        "knowledge_collections",
        "SET NULL",
    ),
    (
        "037_chat_sessions_workspace_jobs",
        "workspace_jobs",
        "parent_message_id",
        "ix_workspace_jobs_parent_message_id",
        "messages",
        "SET NULL",
    ),
    (
        "037_chat_sessions_workspace_jobs",
        "workspace_jobs",
        "message_id",
        "ix_workspace_jobs_message_id",
        "messages",
        "SET NULL",
    ),
    (
        "052_client360_campaigns",
        "client360_mail_drafts",
        "campaign_id",
        "ix_client360_mail_drafts_campaign_id",
        "client360_campaigns",
        "SET NULL",
    ),
    (
        "052_client360_campaigns",
        "client360_impact_events",
        "campaign_id",
        "ix_client360_impact_events_campaign_id",
        "client360_campaigns",
        "SET NULL",
    ),
    (
        "099_data_plane_attached",
        "tabular_datasets",
        "system_id",
        "ix_tabular_datasets_system_id",
        "systems",
        "SET NULL",
    ),
    (
        "099_data_plane_attached",
        "ml_models",
        "system_id",
        "ix_ml_models_system_id",
        "systems",
        "SET NULL",
    ),
    (
        "099_data_plane_attached",
        "ml_models",
        "published_skill_id",
        "ix_ml_models_published_skill_id",
        "skills",
        "SET NULL",
    ),
)

# Indexes 037 adds that are not a single foreign key column, and so are not
# covered by REPAIRED_LINKS. The composite ones are what the chat surface
# actually reads on.
REPAIRED_INDEXES = (
    ("sessions", "ix_sessions_context_signature", ("context_signature",)),
    (
        "sessions",
        "ix_sessions_workspace_user_status",
        ("workspace_id", "user_id", "status"),
    ),
    (
        "workspace_jobs",
        "ix_workspace_jobs_workspace_session_status",
        ("workspace_id", "session_id", "status"),
    ),
    (
        "workspace_jobs",
        "ix_workspace_jobs_workspace_user_status",
        ("workspace_id", "created_by_user_id", "status"),
    ),
    (
        "workspace_jobs",
        "ix_workspace_jobs_workspace_kind_status",
        ("workspace_id", "kind", "status"),
    ),
)

# The rows a child row needs before it can exist at all. Inserted with foreign
# key enforcement already on, so this is itself a check that the tenant and
# lineage links the repaired revisions did *not* touch still resolve.
SEED = (
    "insert into workspaces (id, name, slug, mode) "
    "values ('ws-1', 'Bootstrap', 'bootstrap', 'builder')",
    "insert into client360_opportunities "
    "(id, workspace_id, customer_key, customer_name, part_family) "
    "values ('opp-1', 'ws-1', 'cust-1', 'Customer', 'family')",
    "insert into expert_capture_sessions (id, workspace_id, objective) "
    "values ('ecs-1', 'ws-1', 'capture something')",
)

NOW = "2026-09-13 00:00:00"

# (table, foreign key column, the rest of a legal row). The column under test
# is filled in twice: once with an id no parent has, once with NULL.
ORPHAN_ROWS = {
    ("runs", "initiated_by_user_id"): {"started_at": NOW},
    ("expert_capture_sessions", "created_by_user_id"): {
        "workspace_id": "ws-1",
        "objective": "capture something",
    },
    ("knowledge_update_proposals", "created_by_user_id"): {
        "workspace_id": "ws-1",
        "session_id": "ecs-1",
    },
    ("knowledge_update_proposals", "reviewer_user_id"): {
        "workspace_id": "ws-1",
        "session_id": "ecs-1",
    },
    ("workspace_jobs", "session_id"): {
        "workspace_id": "ws-1",
        "kind": "deep_retrieval",
        "created_at": NOW,
        "updated_at": NOW,
    },
    ("workspace_jobs", "collection_id"): {
        "workspace_id": "ws-1",
        "kind": "deep_retrieval",
        "created_at": NOW,
        "updated_at": NOW,
    },
    ("workspace_jobs", "parent_message_id"): {
        "workspace_id": "ws-1",
        "kind": "deep_retrieval",
        "created_at": NOW,
        "updated_at": NOW,
    },
    ("workspace_jobs", "message_id"): {
        "workspace_id": "ws-1",
        "kind": "deep_retrieval",
        "created_at": NOW,
        "updated_at": NOW,
    },
    ("client360_mail_drafts", "campaign_id"): {
        "workspace_id": "ws-1",
        "opportunity_id": "opp-1",
        "subject": "Subject",
        "generated_body": "Body",
    },
    ("client360_impact_events", "campaign_id"): {
        "workspace_id": "ws-1",
        "impact_type": "note",
    },
    ("tabular_datasets", "system_id"): {
        "workspace_id": "ws-1",
        "name": "Dataset",
        "slug": "dataset",
        "created_at": NOW,
        "updated_at": NOW,
    },
    ("ml_models", "system_id"): {
        "workspace_id": "ws-1",
        "name": "Model",
        "slug": "model",
        "task": "classification",
        "algo": "logistic_regression",
        "target": "label",
        "created_at": NOW,
        "updated_at": NOW,
    },
    ("ml_models", "published_skill_id"): {
        "workspace_id": "ws-1",
        "name": "Model",
        "slug": "model",
        "task": "classification",
        "algo": "logistic_regression",
        "target": "label",
        "created_at": NOW,
        "updated_at": NOW,
    },
}


def _alembic(database: Path, *argv: str) -> str:
    """Alembic against ``database``, run the way the deployment runs it.

    ``sys.executable -m`` so the subprocess is the interpreter running the
    suite, and ``AGENTIUM_DISABLE_DOTENV`` so a developer's ``backend/.env``
    cannot redirect the upgrade onto a real database: ``env.py`` builds the URL
    from ``settings``, which reads that file by default.
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
    return result.stdout


def _script():
    from alembic.script import ScriptDirectory

    return ScriptDirectory(str(BACKEND_ROOT / "alembic"))


def _engine(database: Path) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{database}")


def _snapshot(database: Path) -> dict[str, object]:
    """Every table's shape, normalised enough to compare two databases.

    Reflection rather than the DDL string, because a batch rewrite legitimately
    reorders and re-quotes a CREATE TABLE while producing the same schema. What
    must not move is what is read here: columns, nullability, primary keys,
    foreign keys with their delete rule, indexes and named constraints.
    """

    engine = _engine(database)
    try:
        inspector = sa.inspect(engine)
        snapshot: dict[str, object] = {}
        for table in sorted(inspector.get_table_names()):
            snapshot[table] = {
                "columns": {
                    column["name"]: (str(column["type"]), column["nullable"])
                    for column in inspector.get_columns(table)
                },
                "primary_key": tuple(inspector.get_pk_constraint(table)["constrained_columns"]),
                "foreign_keys": frozenset(
                    (
                        tuple(fk["constrained_columns"]),
                        fk["referred_table"],
                        tuple(fk["referred_columns"]),
                        (fk.get("options") or {}).get("ondelete"),
                    )
                    for fk in inspector.get_foreign_keys(table)
                ),
                "indexes": frozenset(
                    (index["name"], tuple(index["column_names"]), bool(index["unique"]))
                    for index in inspector.get_indexes(table)
                ),
                "unique_constraints": frozenset(
                    (uq["name"], tuple(uq["column_names"]))
                    for uq in inspector.get_unique_constraints(table)
                ),
                "check_constraints": frozenset(
                    (check["name"], " ".join(check["sqltext"].split()))
                    for check in inspector.get_check_constraints(table)
                ),
            }
        return snapshot
    finally:
        engine.dispose()


def _stamped(database: Path) -> set[str]:
    engine = _engine(database)
    try:
        with engine.connect() as connection:
            return {
                row[0]
                for row in connection.exec_driver_sql("select version_num from alembic_version")
            }
    finally:
        engine.dispose()


def _execute(database: Path, *statements: str, foreign_keys: bool = False) -> None:
    engine = _engine(database)
    try:
        with engine.begin() as connection:
            if foreign_keys:
                # SQLite enforces foreign keys only when asked to, per
                # connection. The application turns this on; the assertions
                # below are about what the schema says, so they have to as well.
                connection.exec_driver_sql("pragma foreign_keys = on")
            for statement in statements:
                connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


def _insert(table: str, values: dict[str, object]) -> str:
    columns = ", ".join(values)
    literals = ", ".join(
        "null" if value is None else "'" + str(value).replace("'", "''") + "'"
        for value in values.values()
    )
    return f"insert into {table} ({columns}) values ({literals})"


@pytest.fixture()
def empty_database(tmp_path: Path) -> Path:
    """A path with no file at it — SQLite creates the database on connect."""

    path = tmp_path / "bootstrap.db"
    assert not path.exists(), "the bootstrap has to start from nothing"
    return path


@pytest.fixture(scope="module")
def _migrated_head(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One clean replay to head, kept for the read-only assertions to share."""

    path = tmp_path_factory.mktemp("head") / "head.db"
    _alembic(path, "upgrade", "head")
    return path


@pytest.fixture()
def migrated(_migrated_head: Path, tmp_path: Path) -> Path:
    """A private copy of the migrated database, safe to write rows into."""

    path = tmp_path / "head.db"
    shutil.copyfile(_migrated_head, path)
    return path


def test_the_revision_graph_has_exactly_one_head() -> None:
    """Two heads is a different bootstrap failure, and it hides this one."""

    heads = _script().get_heads()
    assert len(heads) == 1, f"expected a single head, found {sorted(heads)}"


def test_an_empty_database_reaches_head(empty_database: Path) -> None:
    """The bootstrap itself: nothing, then ``alembic upgrade head``.

    Jumped to the head rather than stepped, because that is the command the
    install runs, and every revision in between is on the path either way — a
    failure anywhere stops the whole thing, which is the point.
    """

    _alembic(empty_database, "upgrade", "head")

    (head,) = _script().get_heads()
    assert _stamped(empty_database) == {head}, (
        "The database did not land on the head. A partial upgrade leaves the "
        "install with no usable schema, not with one missing table."
    )

    current = _alembic(empty_database, "current")
    assert head in current and "(head)" in current, current


@pytest.mark.parametrize(
    ("revision", "table", "column", "index", "referent", "ondelete"),
    REPAIRED_LINKS,
    ids=[f"{link[1]}.{link[2]}" for link in REPAIRED_LINKS],
)
def test_repaired_revisions_keep_their_columns_indexes_and_foreign_keys(
    migrated: Path, revision, table, column, index, referent, ondelete
) -> None:
    """Batch mode must not have quietly dropped what the revision attaches.

    A SQLite batch rewrite replays the table's constraints onto a copy. That is
    also how a constraint gets lost: anything it fails to carry over simply
    isn't there afterwards, and nothing complains.
    """

    engine = _engine(migrated)
    try:
        inspector = sa.inspect(engine)
        columns = {c["name"]: c for c in inspector.get_columns(table)}
        assert column in columns, f"{revision} did not leave {table}.{column} behind"
        assert columns[column]["nullable"], (
            f"{table}.{column} is attribution or lineage; making it required "
            "would reject rows the application still writes without it"
        )

        indexes = {i["name"]: tuple(i["column_names"]) for i in inspector.get_indexes(table)}
        assert indexes.get(index) == (column,)

        links = {
            (tuple(fk["constrained_columns"]), fk["referred_table"]): fk
            for fk in inspector.get_foreign_keys(table)
        }
        foreign_key = links.get(((column,), referent))
        assert foreign_key is not None, (
            f"{table}.{column} lost its foreign key to {referent}. Referential "
            "integrity is the part of this revision that cannot be restored by "
            "a later one."
        )
        assert foreign_key["referred_columns"] == ["id"]
        assert (foreign_key.get("options") or {}).get("ondelete") == ondelete
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("table", "index", "columns"),
    REPAIRED_INDEXES,
    ids=[index[1] for index in REPAIRED_INDEXES],
)
def test_the_composite_indexes_survive_the_table_rewrite(
    migrated: Path, table, index, columns
) -> None:
    engine = _engine(migrated)
    try:
        indexes = {
            i["name"]: tuple(i["column_names"]) for i in sa.inspect(engine).get_indexes(table)
        }
        assert indexes.get(index) == columns
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("table", "column"),
    sorted(ORPHAN_ROWS),
    ids=[f"{table}.{column}" for table, column in sorted(ORPHAN_ROWS)],
)
def test_the_repaired_foreign_keys_reject_an_orphan_row(migrated: Path, table, column) -> None:
    """Declared is not enforced — so make SQLite actually refuse the row.

    Reflection would still report a foreign key whose referent the rewrite got
    wrong. Only an insert proves the target resolves.
    """

    base = ORPHAN_ROWS[(table, column)]

    with pytest.raises(sa.exc.IntegrityError):
        _execute(
            migrated,
            *SEED,
            _insert(table, {"id": "orphan", **base, column: "no-such-parent"}),
            foreign_keys=True,
        )

    # And the same row with nothing in that column has to be accepted, or the
    # column would be requiring a value the application does not always have.
    _execute(
        migrated,
        *SEED,
        _insert(table, {"id": "unattributed", **base, column: None}),
        foreign_keys=True,
    )


def test_031_leaves_systems_settings_required_and_without_a_default(
    migrated: Path,
) -> None:
    """The reason 031 drops the default it adds in the same breath.

    The default exists only to make the new NOT NULL column legal for rows that
    already exist. Leaving it in place would let a System be written with no
    settings at all and silently acquire ``{}`` — which is what SQLite got when
    the ``DROP DEFAULT`` could not run.
    """

    columns = {}
    engine = _engine(migrated)
    try:
        columns = {c["name"]: c for c in sa.inspect(engine).get_columns("systems")}
    finally:
        engine.dispose()

    assert columns["settings"]["nullable"] is False
    assert columns["settings"]["default"] is None

    with pytest.raises(sa.exc.IntegrityError):
        _execute(
            migrated,
            _insert(
                "systems",
                {
                    "id": "sys-1",
                    "name": "System",
                    "created_at": NOW,
                    "updated_at": NOW,
                    "blueprint_key": "sys-1",
                },
            ),
        )


def test_the_sessions_status_check_survives_the_rewrite(migrated: Path) -> None:
    """037's check constraint, asserted by what it refuses rather than by name."""

    _execute(migrated, _insert("sessions", {"id": "sess-ok", "status": "archived"}))

    with pytest.raises(sa.exc.IntegrityError):
        _execute(migrated, _insert("sessions", {"id": "sess-bad", "status": "deleted_maybe"}))


def test_head_round_trips_through_base_and_lands_on_the_same_schema(
    empty_database: Path,
) -> None:
    """Every revision's downgrade, then every revision's upgrade again.

    This is the widest round trip the chain supports, and it happens to
    support the whole of it: base is reachable from the head and the head is
    reachable again from base. It covers all five repaired revisions in both
    directions at once, which the narrow per-revision trips below then pin
    down individually.
    """

    _alembic(empty_database, "upgrade", "head")
    before = _snapshot(empty_database)

    _alembic(empty_database, "downgrade", "base")
    # Alembic deliberately retains its own empty version table at ``base``;
    # every application table must be gone so the replay still starts from a
    # genuinely blank product schema.
    assert set(_snapshot(empty_database)) == {"alembic_version"}, (
        "Downgrading to base left application tables behind, so a re-upgrade "
        "would be building on top of them rather than from nothing."
    )

    _alembic(empty_database, "upgrade", "head")
    assert _snapshot(empty_database) == before


def test_each_repaired_revision_downgrades_and_re_upgrades(
    empty_database: Path,
) -> None:
    """The narrow trip around each repaired revision, in chain order.

    A downgrade that does not undo its upgrade is only visible on the replay
    after it, which is why each step goes down and back up before the next one
    is applied. One database walked forward, because that is the state a real
    rollback-and-retry happens in.
    """

    for revision, parent in REPAIRED:
        _alembic(empty_database, "upgrade", revision)
        applied = _snapshot(empty_database)

        _alembic(empty_database, "downgrade", parent)
        assert _stamped(empty_database) == {parent}
        assert _snapshot(empty_database) != applied, (
            f"{revision} downgraded without changing the schema, so its "
            "downgrade is not undoing its upgrade"
        )

        _alembic(empty_database, "upgrade", revision)
        assert _snapshot(empty_database) == applied, (
            f"{revision} does not replay: the second upgrade produced a "
            "different schema from the first"
        )

    _alembic(empty_database, "upgrade", "head")
    (head,) = _script().get_heads()
    assert _stamped(empty_database) == {head}
