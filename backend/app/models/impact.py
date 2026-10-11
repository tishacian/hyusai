"""Canonical Impact aggregate — materialised view of Outcome over time.

Hypervisor's Balance Sheet reads from this table to render the hero value
panel and the Capability portfolio. Population is best-effort and lazily
recomputed by `app.services.run_engine.aggregate_impact`.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, JSON, String

from app.db.base import Base


class Impact(Base):
    __tablename__ = "impacts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)

    scope = Column(String(20), default="capability")  # capability | system | portfolio
    target_id = Column(String(36), nullable=True, index=True)
    period = Column(String(20), default="qtd")        # qtd | mtd | wtd | rolling_30d | rolling_90d

    runs_count = Column(Float, default=0.0)
    total_cost = Column(Float, default=0.0)
    total_revenue = Column(Float, default=0.0)
    estimated_value = Column(Float, default=0.0)
    roi = Column(Float, nullable=True)
    time_saved_minutes = Column(Float, default=0.0)

    breakdown = Column(JSON, default=dict)
    trend = Column(JSON, default=list)               # 12-point sparkline values

    computed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
