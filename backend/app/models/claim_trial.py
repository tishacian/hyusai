"""Human benchmark sessions, independent of production value baselines."""
from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, UniqueConstraint
from app.db.base import Base


class ClaimTrial(Base):
    __tablename__ = "claim_trials"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    operator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    protocol_sha256 = Column(String(64), nullable=False)
    pair_id = Column(String(40), nullable=False)
    condition = Column(String(20), nullable=False)
    claim_id = Column(String(80), nullable=False)
    state = Column(String(20), nullable=False)
    evidence = Column(JSON, nullable=False)
    events = Column(JSON, nullable=False)
    result = Column(JSON, nullable=True)
    review = Column(JSON, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("workspace_id", "protocol_sha256", "pair_id", "condition", name="uq_claim_trials_condition"),)
