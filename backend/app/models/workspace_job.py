"""Workspace-scoped operational job ledger."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text

from app.db.base import Base


WORKSPACE_JOB_STATUSES = ("created", "queued", "running", "completed", "failed", "cancelled")


class WorkspaceJob(Base):
    """Generic workspace job for operator-facing lifecycle and SSE.

    WorkerJob remains the ingestion/collection ledger. This table is for
    product-level jobs such as briefing preparation, map scoring or scenario
    generation, where the target is a workspace/system rather than a collection.
    """

    __tablename__ = "workspace_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    system_id = Column(String(36), ForeignKey("systems.id", ondelete="SET NULL"), nullable=True, index=True)
    run_id = Column(String(36), ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    collection_id = Column(String(36), ForeignKey("knowledge_collections.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_message_id = Column(String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)
    message_id = Column(String(36), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True)

    kind = Column(String(80), nullable=False)
    title = Column(String(255), nullable=False, default="")
    status = Column(String(32), nullable=False, default="created")
    progress = Column(Integer, nullable=False, default=0)
    stage = Column(String(80), nullable=False, default="created")
    error = Column(Text, nullable=True)
    input_ref = Column(JSON, nullable=False, default=dict)
    result = Column(JSON, nullable=False, default=dict)
    events = Column(JSON, nullable=False, default=list)

    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    queued_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_workspace_jobs_status",
        ),
        Index("ix_workspace_jobs_workspace_status", "workspace_id", "status"),
        Index("ix_workspace_jobs_workspace_kind", "workspace_id", "kind"),
        Index("ix_workspace_jobs_workspace_session_status", "workspace_id", "session_id", "status"),
        Index("ix_workspace_jobs_workspace_user_status", "workspace_id", "created_by_user_id", "status"),
        Index("ix_workspace_jobs_workspace_kind_status", "workspace_id", "kind", "status"),
    )
