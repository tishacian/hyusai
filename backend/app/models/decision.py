"""Canonical Decision log — what the Hypervisor recommended and what was
acted upon. Mirrors the "decision trail" of the executive cockpit.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, JSON, String, Text

from app.db.base import Base


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)

    scope = Column(String(20), default="capability")  # capability | system | run | portfolio
    target_id = Column(String(36), nullable=True, index=True)

    kind = Column(String(40), default="recommendation")  # recommendation | what_if | adaptive_action | manual
    status = Column(String(20), default="open")          # open | accepted | rejected | applied
    title = Column(String(255), nullable=False)
    rationale = Column(JSON, default=dict)

    impact_estimate = Column(JSON, default=dict)        # forecasted ROI delta, cost delta, …
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    approved_by = Column(String(255), nullable=True)
    approved_at = Column(DateTime, nullable=True)
