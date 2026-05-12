"""Workspace-scoped action plan items."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, JSON, String, Text

from app.db.base import Base


ACTION_ITEM_STATUSES = ("planned", "in_progress", "completed", "cancelled")
ACTION_ITEM_PRIORITIES = ("critical", "high", "medium", "low")


class WorkspaceActionItem(Base):
    """Advisory action item created from a workspace signal or assistant action."""

    __tablename__ = "workspace_action_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    target_kind = Column(String(64), nullable=False, default="cabinet")
    target_id = Column(String(128), nullable=False, default="")
    target_label = Column(String(255), nullable=False, default="")

    priority = Column(String(32), nullable=False, default="medium")
    status = Column(String(32), nullable=False, default="planned")
    due_at = Column(DateTime, nullable=True, index=True)
    owner_label = Column(String(255), nullable=False, default="Cabinet")

    source_kind = Column(String(64), nullable=False, default="assistant")
    source_id = Column(String(128), nullable=False, default="")
    calendar_event_id = Column(String(36), ForeignKey("workspace_calendar_events.id", ondelete="SET NULL"), nullable=True)
    run_id = Column(String(36), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True)
    confidence = Column(String(32), nullable=False, default="medium")
    recommended_window = Column(JSON, nullable=False, default=dict)
    scenario_options = Column(JSON, nullable=False, default=list)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)

    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'in_progress', 'completed', 'cancelled')",
            name="ck_workspace_action_items_status",
        ),
        CheckConstraint(
            "priority IN ('critical', 'high', 'medium', 'low')",
            name="ck_workspace_action_items_priority",
        ),
        Index("ix_workspace_action_items_workspace_status", "workspace_id", "status"),
        Index("ix_workspace_action_items_workspace_due", "workspace_id", "due_at"),
    )
