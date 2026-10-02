"""Receipts for explicitly simulated e-commerce resolutions; no payment rail."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, UniqueConstraint
from app.db.base import Base


class ClaimAction(Base):
    __tablename__ = "claim_actions"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    order_id = Column(String(80), nullable=False)
    claim_id = Column(String(80), nullable=False)
    action = Column(String(40), nullable=False)
    run_id = Column(String(36), ForeignKey("runs.id"), nullable=False)
    decision_id = Column(String(36), ForeignKey("decisions.id"), nullable=False)
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    receipt = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("workspace_id", "order_id", "action", name="uq_claim_actions_order_action"),
        UniqueConstraint("workspace_id", "run_id", name="uq_claim_actions_run"),
    )
