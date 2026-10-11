"""Versioned Markdown guides attached to Knowledge scopes or collections."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from app.db.base import Base


class KnowledgeGuide(Base):
    """Human-authored context notes used alongside indexed documents.

    ``guide_key`` is the stable logical identifier; every edit creates a new
    row with an incremented ``version`` and ``is_current=True`` while older rows
    are kept for audit/history.
    """

    __tablename__ = "knowledge_guides"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    guide_key = Column(String(80), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    target_type = Column(String(32), nullable=False)
    target_ref = Column(String(255), nullable=False)
    title = Column(String(255), nullable=False)
    markdown = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="draft", index=True)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    supersedes_id = Column(String(36), ForeignKey("knowledge_guides.id"), nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    published_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("workspace_id", "guide_key", "version", name="uq_knowledge_guides_workspace_key_version"),
        Index("ix_knowledge_guides_target_current", "workspace_id", "target_type", "target_ref", "is_current"),
    )
