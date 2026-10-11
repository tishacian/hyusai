"""Retained authoring inputs; no executable object is created by retention."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint

from app.db.base import Base


class BrdDocument(Base):
    __tablename__ = "brd_documents"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    sha256 = Column(String(64), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    filename = Column(String(255), nullable=False)
    storage_key = Column(String(1024), nullable=False)
    extraction = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint(
        "workspace_id", "created_by_user_id", "sha256", name="uq_brd_document_upload"
    ),)
