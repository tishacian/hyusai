"""Buffered inbound events while a Run is paused at a HITL / membrane gate.

Correlation strategy (see ``run_engine.inbox``):
  * Match on ``system_id`` of a ``hitl_pending`` run.
  * Optionally refine with ``correlation_key`` from the event payload
    (``correlation_key`` | ``correlation_id`` | ``transaction_id``).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String

from app.db.base import Base


class RunInbox(Base):
    __tablename__ = "run_inbox"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id = Column(
        String(36),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(String(36), nullable=True, index=True)
    system_id = Column(String(36), nullable=True, index=True)
    event_kind = Column(String(120), nullable=False, default="event")
    correlation_key = Column(String(255), nullable=True, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_run_inbox_system_correlation", "system_id", "correlation_key"),
    )
