"""Coordination records, never a second authority for native activity results."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.base import Base


class ExecutionCapacity(Base):
    __tablename__ = "execution_capacity"
    scope = Column(String(100), primary_key=True)
    generation = Column(Integer, nullable=False, default=0)
    paused = Column(Integer, nullable=False, default=0)


class ExecutionReservation(Base):
    __tablename__ = "execution_reservations"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    entity_kind = Column(String(32), nullable=False)
    entity_id = Column(String(36), nullable=False)
    lane = Column(String(16), nullable=False)
    cpu_cores = Column(Float, nullable=False)
    memory_mb = Column(Integer, nullable=False)
    reserved_core_hours = Column(Float, nullable=False)
    # Policy and tariffs are frozen at admission. Missing measurements stay NULL.
    policy = Column(JSON, nullable=False)
    lease_token = Column(String(36), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deadline_at = Column(DateTime, nullable=False)
    released_at = Column(DateTime, nullable=True)
    allocated_core_hours = Column(Float, nullable=True)
    cpu_seconds = Column(Float, nullable=True)
    peak_rss_bytes = Column(Float, nullable=True)
    outcome = Column(String(32), nullable=True)
    __table_args__ = (
        UniqueConstraint("entity_kind", "entity_id", name="uq_execution_reservation_native"),
        CheckConstraint(
            "cpu_cores > 0 AND memory_mb > 0 AND reserved_core_hours >= 0",
            name="ck_execution_reservation_resources",
        ),
        CheckConstraint("lane IN ('interactive','batch')", name="ck_execution_reservation_lane"),
        Index("ix_execution_reservations_active", "released_at", "workspace_id"),
    )


class ExecutionDispatch(Base):
    """Durable identifier-only command; publisher retries reuse the same task id."""

    __tablename__ = "execution_dispatches"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    entity_kind = Column(String(32), nullable=False)
    entity_id = Column(String(36), nullable=False)
    task_name = Column(String(120), nullable=False)
    task_queue = Column(String(120), nullable=False)
    task_id = Column(String(36), nullable=False, unique=True)
    dedupe_key = Column(String(255), nullable=False, unique=True)
    state = Column(String(16), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    deadline_at = Column(DateTime, nullable=True)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)
    reconciled_at = Column(DateTime, nullable=True)
    error_code = Column(String(80), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','leased','published','cancelled','dead')",
            name="ck_execution_dispatch_state",
        ),
        Index("ix_execution_dispatch_due", "state", "available_at", "lease_expires_at"),
        Index("ix_execution_dispatch_reconcile", "task_name", "reconciled_at"),
    )
