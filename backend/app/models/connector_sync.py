"""Commit-fenced incremental checkpoints and durable object polling subscriptions."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.base import Base


class ConnectorSyncState(Base):
    __tablename__ = "connector_sync_states"
    __table_args__ = (
        UniqueConstraint("workspace_id", "scope_digest", name="uq_connector_sync_scope"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id = Column(
        String(36), ForeignKey("connections.id", ondelete="RESTRICT"), nullable=False
    )
    scope_digest = Column(String(64), nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    checkpoint = Column(JSON)
    dataset_id = Column(String(36), ForeignKey("tabular_datasets.id", ondelete="RESTRICT"))
    compute_run_id = Column(String(36), ForeignKey("compute_runs.id", ondelete="RESTRICT"))
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class ConnectorWatch(Base):
    __tablename__ = "connector_watches"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id = Column(
        String(36), ForeignKey("connections.id", ondelete="RESTRICT"), nullable=False
    )
    connection_revision = Column(Integer, nullable=False)
    system_id = Column(String(36), ForeignKey("systems.id", ondelete="RESTRICT"), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    prefix = Column(String(1024), nullable=False)
    interval_s = Column(Integer, nullable=False, default=300)
    enabled = Column(Boolean, nullable=False, default=True)
    sequence = Column(Integer, nullable=False, default=0)
    fingerprint = Column(String(64))
    objects = Column(JSON, nullable=False, default=list)
    pending_run_id = Column(String(36), ForeignKey("compute_runs.id", ondelete="RESTRICT"))
    next_poll_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    last_error = Column(String(160))
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
