"""Typed finish time and duration on activity projections (series read path).

The values copy snapshot["finished_at"] and snapshot["measurements"]["duration_ms"]
with the native reader's parsers, frozen below. Existing rows are back-filled in
bounded batches; the snapshot remains the source and is never rewritten.
"""

import json
import math
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "138_activity_measures"
down_revision = "137_mlops_operations"
branch_labels = depends_on = None

BATCH = 1000


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value if value >= 0 else None


def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC).replace(tzinfo=None) if result.tzinfo else result
    except ValueError:
        return None


def derive(snapshot):
    """Frozen copy of app.models.activity.measured_columns (checked by a test)."""
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    try:
        finished = _instant(snapshot.get("finished_at"))
    except OverflowError:
        finished = None
    measurements = snapshot.get("measurements")
    try:
        duration = _number(
            measurements.get("duration_ms") if isinstance(measurements, dict) else None
        )
    except OverflowError:
        duration = None
    return {"finished_at": finished, "duration_ms": duration}


def upgrade():
    op.add_column("activities", sa.Column("finished_at", sa.DateTime(), nullable=True))
    op.add_column("activities", sa.Column("duration_ms", sa.Float(), nullable=True))
    bind = op.get_bind()
    last = ""
    while True:
        rows = bind.execute(
            sa.text(
                "SELECT id, snapshot FROM activities WHERE id > :last ORDER BY id LIMIT :limit"
            ),
            {"last": last, "limit": BATCH},
        ).all()
        if not rows:
            break
        bind.execute(
            sa.text(
                "UPDATE activities SET finished_at = :finished_at, duration_ms = :duration_ms"
                " WHERE id = :id"
            ),
            [{"id": row.id, **derive(row.snapshot)} for row in rows],
        )
        last = rows[-1].id
    op.create_index(
        "ix_activities_workspace_finished", "activities", ["workspace_id", "finished_at"]
    )


def downgrade():
    # Derived copies only: the snapshot keeps every value.
    with op.batch_alter_table("activities") as batch:
        batch.drop_index("ix_activities_workspace_finished")
        batch.drop_column("duration_ms")
        batch.drop_column("finished_at")
