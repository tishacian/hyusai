"""Atomic idempotency ledger for inbound event-trigger deliveries."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, UniqueConstraint

from app.db.base import Base


class TriggerEventClaim(Base):
    __tablename__ = "trigger_event_claims"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True
    )
    system_id = Column(
        String(36), ForeignKey("systems.id", ondelete="CASCADE"), nullable=False
    )
    dedup_key = Column(String(255), nullable=False)
    outcome = Column(String(20), nullable=False)
    run_id = Column(String(36), ForeignKey("runs.id", ondelete="CASCADE"), nullable=True)
    inbox_id = Column(
        String(36), ForeignKey("run_inbox.id", ondelete="CASCADE"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "system_id",
            "dedup_key",
            name="uq_trigger_event_claim_system_key",
        ),
        CheckConstraint(
            "outcome IN ('run', 'simulated', 'inbox')",
            name="ck_trigger_event_claim_outcome",
        ),
        CheckConstraint(
            "(outcome IN ('run', 'simulated') AND run_id IS NOT NULL AND inbox_id IS NULL) "
            "OR (outcome = 'inbox' AND run_id IS NULL AND inbox_id IS NOT NULL)",
            name="ck_trigger_event_claim_target",
        ),
    )
