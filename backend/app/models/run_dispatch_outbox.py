"""Transactional outbox for durable Run/Celery coordination."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.db.base import Base

DISPATCH_EVENT_TYPES = (
    "trigger_run",
    "subflow_run",
    "subflow_parent_resume",
    "subflow_hitl_resume",
    "run_hitl_resume",
)
DISPATCH_STATES = ("pending", "leased", "published", "cancelled", "dead")


class RunDispatchOutbox(Base):
    """One idempotent request to publish an identifier-only Celery message."""

    __tablename__ = "run_dispatch_outbox"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    run_id = Column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(40), nullable=False)
    source_id = Column(String(255), nullable=True)
    decision_id = Column(String(36), nullable=True)
    wave_id = Column(Integer, nullable=True)

    dedupe_key = Column(String(255), nullable=False, unique=True)
    task_id = Column(String(36), nullable=False, unique=True)
    state = Column(String(20), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    lease_token = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    published_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('trigger_run', 'subflow_run', 'subflow_parent_resume', "
            "'subflow_hitl_resume', 'run_hitl_resume')",
            name="ck_run_dispatch_outbox_event_type",
        ),
        CheckConstraint(
            "state IN ('pending', 'leased', 'published', 'cancelled', 'dead')",
            name="ck_run_dispatch_outbox_state",
        ),
        CheckConstraint("attempts >= 0", name="ck_run_dispatch_outbox_attempts"),
        Index(
            "ix_run_dispatch_outbox_due",
            "state",
            "available_at",
            "lease_expires_at",
        ),
        Index("ix_run_dispatch_outbox_workspace_state", "workspace_id", "state"),
        Index("ix_run_dispatch_outbox_run_event", "run_id", "event_type"),
    )
