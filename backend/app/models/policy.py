"""Canonical Control & Adaptive policies — the cockpit dials.

ControlPolicy = hard guardrails (cost, latency, model whitelist, HITL).
AdaptivePolicy = soft directives the runtime uses to adjust behaviour
during a Run (switch skill, fall back to cheaper model, escalate HITL…).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, Boolean, DateTime, Float, JSON, String

from app.db.base import Base


class ControlPolicy(Base):
    __tablename__ = "control_policies"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)

    name = Column(String(200), nullable=False, default="default")
    scope = Column(String(20), default="system")  # global | capability | system | run
    target_id = Column(String(36), nullable=True, index=True)

    max_cost_per_decision = Column(Float, nullable=True)
    max_latency_ms = Column(Float, nullable=True)
    mandatory_hitl_if_confidence_below = Column(Float, nullable=True)
    allowed_models = Column(JSON, default=list)
    allowed_skills = Column(JSON, default=list)

    extra = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class AdaptivePolicy(Base):
    __tablename__ = "adaptive_policies"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)

    name = Column(String(200), nullable=False, default="default")
    enabled = Column(Boolean, default=False)
    adaptation_level = Column(String(20), default="moderate")  # off | conservative | moderate | aggressive

    # Canonical scope binding: policies apply to a portfolio, capability or
    # specific system. `target_id` points at the capability/system (nullable
    # when scope is "portfolio").
    scope = Column(String(20), nullable=True)
    target_id = Column(String(36), nullable=True)

    triggers = Column(JSON, default=dict)        # e.g. {confidence_below: 0.7, latency_above_ms: 5000}
    allowed_actions = Column(JSON, default=list) # e.g. ["switch_model","escalate_hitl","fallback_skill"]
    constraints = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
