"""Revisions of an automation's value contract (ADR 0003 lot 3).

Append-only: a proposal is a new revision, and approving it supersedes the
revision it replaces. The content hash covers the terms, so a card, an export
and the conversation can say which terms they show.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base

PROPOSED = "proposed"
APPROVED = "approved"
REJECTED = "rejected"
SUPERSEDED = "superseded"
WITHDRAWN = "withdrawn"
CONTRACT_STATUSES = (PROPOSED, APPROVED, REJECTED, SUPERSEDED, WITHDRAWN)


class ValueContract(Base):
    __tablename__ = "value_contracts"
    __table_args__ = (UniqueConstraint("system_id", "revision", name="uq_value_contract_revision"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    system_id = Column(String(36), ForeignKey("systems.id"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default=PROPOSED)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    indicator = Column(String(40), nullable=False)
    unit = Column(String(20), nullable=False)
    target = Column(Float, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    convention = Column(JSON, nullable=False)
    source = Column(JSON, nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    proposed_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    proposed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    decided_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    decision_note = Column(Text, nullable=True)
