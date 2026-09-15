"""Reviewed draft changes; deliberately separate from human Run decisions."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey, UniqueConstraint
from app.db.base import Base


class EvaluationCorrection(Base):
    __tablename__ = "evaluation_corrections"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    system_id = Column(String(36), ForeignKey("systems.id"), nullable=False)
    run_id = Column(String(36), ForeignKey("runs.id"), nullable=False)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    request_sha256 = Column(String(64), nullable=False)
    proposal_sha256 = Column(String(64), nullable=False)
    proposal = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="proposed")
    applied_revision = Column(Integer, nullable=True)
    applied_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    applied_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("workspace_id", "created_by_user_id", "idempotency_key", name="uq_evaluation_correction_request"),)
