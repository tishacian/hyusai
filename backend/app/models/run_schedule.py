"""Cron-driven run schedules (orchestration Phase 3)."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, JSON, String, Text

from app.db.base import Base


class RunSchedule(Base):
    """Periodic schedule that creates ``Run(trigger='scheduler')`` rows.

    ``next_fire_at`` is maintained by the Celery beat tick
    (``agentium.scheduler_tick``) via croniter. Disabled rows are ignored.
    """

    __tablename__ = "run_schedules"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    system_id = Column(
        String(36),
        ForeignKey("systems.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name = Column(String(255), nullable=False, default="Schedule")
    cron_expr = Column(String(120), nullable=False)
    timezone = Column(String(64), nullable=False, default="UTC")
    input_payload = Column(JSON, nullable=False, default=dict)
    enabled = Column(Boolean, nullable=False, default=True)

    next_fire_at = Column(DateTime, nullable=True, index=True)
    last_run_id = Column(String(36), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    last_fired_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_run_schedules_due", "enabled", "next_fire_at"),
        Index("ix_run_schedules_workspace_system", "workspace_id", "system_id"),
    )
