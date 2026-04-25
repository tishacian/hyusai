"""Canonical answer annotations — deterministic Dify-style reply path."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from app.db.base import Base


class CanonicalAnswer(Base):
    __tablename__ = "canonical_answers"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    normalized_question = Column(String(2000), nullable=False, index=True)

    source_decision_id = Column(String(36), nullable=True)
    source_feedback_id = Column(String(36), nullable=True)
    source_run_id = Column(String(36), nullable=True)

    similarity_threshold = Column(Float, default=0.9, nullable=False)
    hit_count = Column(Integer, default=0, nullable=False)
    created_by = Column(String(255), default="demo-user", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
