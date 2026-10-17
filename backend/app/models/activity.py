"""Read projections and a transactionally ordered journal, never execution authorities."""

import math
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
)

from app.db.base import Base


def non_negative_number(value):
    """A finite, non-negative JSON number; booleans and strings are not numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value if value >= 0 else None


def parse_instant(value):
    """The native reader's date: ISO text, offsets normalized to naive UTC."""
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC).replace(tzinfo=None) if result.tzinfo else result
    except ValueError:
        return None


def measured_columns(snapshot):
    """Typed copies of snapshot fields, derived with the native reader's parsers.

    An overflowing date or number is stored as NULL. Readers that use these
    columns detect such snapshots and fall back to the native reader, which keeps
    its own error semantics.
    """
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    try:
        finished = parse_instant(snapshot.get("finished_at"))
    except OverflowError:
        finished = None
    measurements = snapshot.get("measurements")
    try:
        duration = non_negative_number(
            measurements.get("duration_ms") if isinstance(measurements, dict) else None
        )
    except OverflowError:
        duration = None
    return {"finished_at": finished, "duration_ms": duration}


class ActivityWorkspaceCursor(Base):
    __tablename__ = "activity_workspace_cursors"
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    sequence = Column(BigInteger, nullable=False, default=0)


class Activity(Base):
    __tablename__ = "activities"
    id = Column(String(36), primary_key=True)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    kind = Column(String(32), nullable=False)
    native_id = Column(String(36), nullable=False)
    system_id = Column(String(36))
    run_id = Column(String(36))
    owner_id = Column(String(36))
    parent_activity_id = Column(String(36))
    status = Column(String(24), nullable=False)
    native_status = Column(String(32), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot = Column(JSON, nullable=False)
    snapshot_digest = Column(String(64), nullable=False)
    origin = Column(String(24), nullable=False, default="observed")
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Typed copies of snapshot["finished_at"] and snapshot["measurements"]
    # ["duration_ms"] (migration 138). Every write derives them from the
    # snapshot through measured_columns(); series aggregate on them instead of
    # re-parsing JSON text for each row.
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Float, nullable=True)
    __table_args__ = (
        UniqueConstraint("kind", "native_id", name="uq_activity_native"),
        Index("ix_activities_workspace_status", "workspace_id", "status"),
        Index("ix_activities_workspace_system", "workspace_id", "system_id"),
        Index("ix_activities_workspace_created", "workspace_id", "created_at", "id"),
        Index("ix_activities_workspace_finished", "workspace_id", "finished_at"),
    )


@event.listens_for(Activity, "before_insert")
@event.listens_for(Activity, "before_update")
def _derive_measured_columns(mapper, connection, target):
    """ORM writes (tests, maintenance) keep the typed copies in step with the snapshot."""
    for key, value in measured_columns(target.snapshot).items():
        setattr(target, key, value)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    sequence = Column(BigInteger, nullable=False)
    activity_id = Column(
        String(36), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    version = Column(Integer, nullable=False)
    event_type = Column(String(32), nullable=False)
    payload = Column(JSON, nullable=False)
    occurred_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("workspace_id", "sequence", name="uq_activity_event_sequence"),
        UniqueConstraint("activity_id", "version", name="uq_activity_event_version"),
        Index("ix_activity_events_activity_sequence", "activity_id", "sequence"),
    )


class ActivityCommand(Base):
    """The pending rows are the durable control outbox; replay uses the same id."""

    __tablename__ = "activity_commands"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    activity_id = Column(
        String(36), ForeignKey("activities.id", ondelete="CASCADE"), nullable=False
    )
    actor_id = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action = Column(String(24), nullable=False)
    expected_version = Column(Integer, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    status = Column(String(24), nullable=False, default="requested")
    error_code = Column(String(64))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime)
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "actor_id", "idempotency_key", name="uq_activity_command_idempotency"
        ),
        Index("ix_activity_commands_dispatch", "status", "created_at"),
    )
