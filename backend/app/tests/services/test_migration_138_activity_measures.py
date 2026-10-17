import json
from datetime import datetime

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from app.models.activity import Activity, measured_columns
from app.tests.services.test_migration_127_connector_connections import load

SNAPSHOTS = [
    {"finished_at": "2026-01-01T12:00:00Z", "measurements": {"duration_ms": 12.5}},
    {"finished_at": "2026-01-01T12:00:00+01:00", "measurements": {"duration_ms": 0}},
    {"finished_at": "2026-W01-4T12:00:00Z", "measurements": {"duration_ms": -3}},
    {"finished_at": "2026-01-01T24:00:00Z", "measurements": {"duration_ms": True}},
    {"finished_at": "0001-01-01T00:00:00+01:00", "measurements": {"duration_ms": "12"}},
    {"finished_at": None, "measurements": None},
    {"finished_at": 17, "measurements": {"duration_ms": 10**400}},
    {},
]


def test_frozen_derivation_matches_the_model():
    migration = load("138_activity_measures")
    for snapshot in SNAPSHOTS:
        assert migration.derive(snapshot) == measured_columns(snapshot)
        assert migration.derive(json.dumps(snapshot)) == measured_columns(snapshot)


def test_138_backfills_existing_rows_matches_model_and_reverses():
    migration = load("138_activity_measures")
    assert migration.down_revision == "137_mlops_operations"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as bind:
        metadata = sa.MetaData()
        for name in ("users", "workspaces"):
            sa.Table(name, metadata, sa.Column("id", sa.String(36), primary_key=True))
        metadata.create_all(bind)
        load_133 = load("133_activity_observability")
        load_133.op = Operations(MigrationContext.configure(bind))
        load_133.upgrade()
        bind.execute(sa.text("INSERT INTO workspaces (id) VALUES ('ws')"))
        now = datetime(2026, 1, 1)
        for index, snapshot in enumerate(SNAPSHOTS):
            bind.execute(
                sa.text(
                    "INSERT INTO activities (id, workspace_id, kind, native_id, status,"
                    " native_status, version, snapshot, snapshot_digest, origin, created_at,"
                    " updated_at) VALUES (:id, 'ws', 'run', :id, 'succeeded', 'completed', 1,"
                    " :snapshot, :digest, 'observed', :now, :now)"
                ),
                {
                    "id": f"a{index:02d}",
                    "snapshot": json.dumps(snapshot),
                    "digest": "0" * 64,
                    "now": now,
                },
            )
        migration.BATCH = 3  # Several bounded batches, including a partial one.
        migration.op = Operations(MigrationContext.configure(bind))
        migration.upgrade()
        columns = {column["name"] for column in sa.inspect(bind).get_columns("activities")}
        assert columns == set(Activity.__table__.columns.keys())
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("activities")}
        assert "ix_activities_workspace_finished" in indexes
        rows = bind.execute(
            sa.text("SELECT id, finished_at, duration_ms FROM activities ORDER BY id")
        ).all()
        for row, snapshot in zip(rows, SNAPSHOTS, strict=True):
            expected = measured_columns(snapshot)
            finished = row.finished_at
            if isinstance(finished, str):  # SQLite text affinity
                finished = datetime.fromisoformat(finished)
            assert finished == expected["finished_at"]
            assert row.duration_ms == expected["duration_ms"]
        migration.downgrade()
        columns = {column["name"] for column in sa.inspect(bind).get_columns("activities")}
        assert not columns.intersection({"finished_at", "duration_ms"})
        assert bind.execute(sa.text("SELECT count(*) FROM activities")).scalar_one() == len(
            SNAPSHOTS
        )
