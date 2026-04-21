"""Canonical Capability model — the value-producing unit Hypervisor lives on.

Capabilities are the marketplace surface (Universal / Industry / Client tiers)
that admins can configure with pricing, value-per-outcome and SLAs. ROI
computations in Hypervisor read from these knobs against the actual cost
of the underlying Skill invocations.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, JSON, String, Text


from app.db.base import Base


class Capability(Base):
    __tablename__ = "capabilities"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)

    slug = Column(String(120), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    tier = Column(String(20), default="universal")  # universal | industry | client
    industry = Column(String(80), nullable=True)

    input_unit = Column(String(60), default="request")
    output_unit = Column(String(60), default="answer")

    skill_ids = Column(JSON, default=list)  # canonical skills bundled by the capability

    # Economics — fully configurable per workspace.
    pricing = Column(JSON, default=lambda: {"unit": "per_outcome", "unit_price": 0.0, "currency": "USD"})
    value_per_outcome = Column(Float, nullable=True)
    confidence_threshold = Column(Float, nullable=True)
    sla = Column(JSON, default=dict)
    roi_model = Column(JSON, default=dict)

    is_seeded = Column(String(1), default="N")  # Y if part of the universal seed catalog

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
