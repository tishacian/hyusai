"""Transport deduplication only; Runs and Decisions remain the execution evidence."""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, UniqueConstraint
from app.db.base import Base


class AssistantRequest(Base):
    __tablename__ = "assistant_requests"
    id = Column(String(36), primary_key=True)
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=True)
    request_id = Column(String(64), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    state = Column(String(16), nullable=False, default="pending")
    response = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "user_id", "request_id", name="uq_assistant_request_caller"
        ),
    )
