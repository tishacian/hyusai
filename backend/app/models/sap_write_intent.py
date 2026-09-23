"""One row per PR item Agentium has tried to turn into an SAP purchase order."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.db.base import Base

#: Claimed and about to call SAP, or calling it now.
PENDING = "pending"
#: SAP created and committed the PO; ``po_number`` names it.
COMMITTED = "committed"
#: SAP refused or the create was rolled back: a new approval may try again.
FAILED = "failed"
#: The call left and no answer came back. SAP may have committed; nothing
#: retries until someone, or a read of SAP, says which.
UNKNOWN = "unknown"

INTENT_STATUSES = (PENDING, COMMITTED, FAILED, UNKNOWN)


class SapWriteIntent(Base):
    """The idempotency record of a PO create for one purchase-requisition item.

    The unique key is the business object, not the run: two approvals of the
    same PR item, from two runs or two scheduler ticks, meet on the same row,
    and only a known failure lets a second one through.
    """

    __tablename__ = "sap_write_intents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "pr_id", "pr_item", name="uq_sap_write_intent_pr_item"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    pr_id = Column(String(20), nullable=False)
    pr_item = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False, default=PENDING)
    server_id = Column(String(64), nullable=True)
    tool = Column(String(64), nullable=True)
    run_id = Column(String(36), nullable=True, index=True)
    decision_id = Column(String(36), nullable=True)
    decided_by = Column(String(255), nullable=True)
    reference = Column(String(10), nullable=True)
    po_number = Column(String(20), nullable=True)
    attempts = Column(Integer, nullable=False, default=1)
    error = Column(JSON, nullable=True)
    resolved_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
