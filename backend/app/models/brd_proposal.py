"""Immutable BRD-to-System proposals awaiting explicit application."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, UniqueConstraint
from app.db.base import Base


class BrdProposal(Base):
    __tablename__ = "brd_proposals"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    document_id = Column(String(36), ForeignKey("brd_documents.id"), nullable=False)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    request_key = Column(String(100), nullable=False)
    sha256 = Column(String(64), nullable=False)
    proposal = Column(JSON, nullable=False)
    status = Column(String(24), nullable=False, default="proposed")
    system_id = Column(String(36), ForeignKey("systems.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("workspace_id", "created_by_user_id", "request_key", name="uq_brd_proposal_request"),)
