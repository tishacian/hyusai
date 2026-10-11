"""Audit log model"""
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON, ForeignKey
from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    event_type = Column(String(100), nullable=False)
    actor = Column(String(255), default="demo-user")
    details = Column(JSON, default=dict)
    trace_id = Column(String(36), nullable=True)
    agent_id = Column(String(100), nullable=True)
    severity = Column(String(20), default="info")
