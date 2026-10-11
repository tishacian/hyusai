"""Task model for autonomous agent missions"""
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, Integer, Float, ForeignKey
from app.db.base import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String(20), default="pending")
    agent_id = Column(String(100), nullable=True)
    created_by = Column(String(255), default="demo-user")
    steps = Column(JSON, default=list)
    artifacts = Column(JSON, default=dict)
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    total_duration_ms = Column(Float, nullable=True)
