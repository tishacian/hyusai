"""Durable, separately retained attempts of an autonomous mission."""

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text

from app.db.base import Base


class TaskExecution(Base):
    __tablename__ = "task_executions"
    id = Column(String(36), primary_key=True)
    task_id = Column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    agent_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, default="queued")
    fence = Column(Integer, nullable=False, default=0)
    lease_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    steps = Column(JSON, nullable=False, default=list)
    artifacts = Column(JSON, nullable=False, default=dict)
    progress = Column(Integer, nullable=False, default=0)
    events = Column(JSON, nullable=False, default=list)
    error = Column(Text, nullable=True)
