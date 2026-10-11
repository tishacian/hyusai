"""Workspace-scoped internal calendar events."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, JSON, String, Text

from app.db.base import Base


CALENDAR_EVENT_STATUSES = ("scheduled", "tentative", "completed", "cancelled")
CALENDAR_EVENT_PRIORITIES = ("critical", "high", "medium", "low")


class WorkspaceCalendarEvent(Base):
    """Internal shared calendar event for a workspace.

    This is the canonical Agentium calendar primitive. External providers can
    sync into it later; SENTINEL-CI uses it as a demo-safe institutional agenda.
    """

    __tablename__ = "workspace_calendar_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False, index=True)
    timezone = Column(String(64), nullable=False, default="Africa/Abidjan")
    location = Column(String(255), nullable=False, default="")
    participants = Column(JSON, nullable=False, default=list)

    category = Column(String(64), nullable=False, default="ministerial")
    priority = Column(String(32), nullable=False, default="medium")
    status = Column(String(32), nullable=False, default="scheduled")

    source_kind = Column(String(64), nullable=False, default="internal_shared")
    source_label = Column(String(255), nullable=False, default="Agenda institutionnel")
    meta_data = Column("metadata", JSON, nullable=False, default=dict)

    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'tentative', 'completed', 'cancelled')",
            name="ck_workspace_calendar_events_status",
        ),
        CheckConstraint(
            "priority IN ('critical', 'high', 'medium', 'low')",
            name="ck_workspace_calendar_events_priority",
        ),
        Index("ix_workspace_calendar_events_workspace_start", "workspace_id", "start_at"),
        Index("ix_workspace_calendar_events_workspace_status", "workspace_id", "status"),
    )
