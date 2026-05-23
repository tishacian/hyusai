"""Workspace-scoped persistent log of meeting arbitration decisions.

Decisions are advisory and workspace-scoped: they are never propagated
outside the SENTINEL-CI workspace, and they back the
``aya.log_decision`` / ``aya.recall_past_decisions`` actions used in
the demo S2 live-meeting flow.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, String, Text

from app.db.base import Base


MEETING_DECISION_STATUSES = ("logged", "applied", "superseded")


class MeetingDecision(Base):
    __tablename__ = "meeting_decisions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    calendar_event_id = Column(String(36), nullable=False, index=True)
    agenda_item_ref = Column(String(160), nullable=False, default="")
    decided_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    decided_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    decided_by_label = Column(String(160), nullable=False, default="")

    options_offered = Column(JSON, nullable=False, default=list)
    chosen_option = Column(String(64), nullable=False, default="")
    rationale = Column(Text, nullable=False, default="")
    source_refs = Column(JSON, nullable=False, default=list)
    status = Column(String(32), nullable=False, default="logged")
    audit_log_ref = Column(String(36), nullable=True)
    meta_data = Column("metadata", JSON, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_meeting_decisions_workspace_event", "workspace_id", "calendar_event_id"),
        Index("ix_meeting_decisions_workspace_decided_at", "workspace_id", "decided_at"),
    )
