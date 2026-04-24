"""Canonical Run + SkillInvocation models — supersede `traces`.

A Run is a single execution of a System against an input. It carries the
canonical Outcome block (decision, value, confidence, efficiency) and a
ledger of SkillInvocations. Hypervisor's Balance Sheet aggregates Runs
into Impact (per System / per Capability / portfolio).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)
    # Nullable since migration 012 — chat turns without a System
    # attachment are still first-class Runs (audit/eval on workspace
    # scope). Set to the System id when chat is launched from a
    # System-scoped UI (/systems/:id), NULL otherwise.
    system_id = Column(String(36), ForeignKey("systems.id"), nullable=True, index=True)
    capability_id = Column(String(36), nullable=True, index=True)

    input_ref = Column(JSON, default=dict)
    output_ref = Column(JSON, default=dict)

    status = Column(String(20), default="pending", index=True)  # pending | running | completed | failed | cancelled
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Float, nullable=True)

    # Outcome block — canonical {cost, value, confidence, efficiency} + source
    decision = Column(String(40), nullable=True)
    confidence = Column(Float, nullable=True)
    value_estimated = Column(Float, nullable=True)
    cost_internal = Column(Float, nullable=True)
    revenue_allocated = Column(Float, nullable=True)
    efficiency = Column(Float, nullable=True)
    # value_source: 'auto' (derived from Capability.roi_model), 'operator'
    # (declared post-run), or 'unset' (no roi_model, no operator input yet).
    value_source = Column(String(16), default="unset", nullable=False)
    operator_value_note = Column(Text, nullable=True)

    checkpoints = Column(JSON, default=list)
    retries = Column(Integer, default=0)
    error = Column(Text, nullable=True)

    # Vague E / E3.1 — immutable snapshot of the flow_definition the
    # run executed against. Written at run start by the engine so that:
    #   - editing the parent System after a run doesn't change what
    #     that run represents (replayability),
    #   - purging old SystemVersion rows (rolling window 500) never
    #     orphans runs: even after v34 is gone, run #abc still has
    #     its dag_json inline.
    # Optional flow_version_id links back to the exact SystemVersion
    # row when still present, NULL once purged (snapshot still usable).
    flow_snapshot = Column(JSON, nullable=True)
    flow_version_id = Column(String(36), nullable=True, index=True)

    # Vague E / E1 — snapshot of the auto-eval pass fired at run completion.
    # Shape: {"composite_score": float, "hallucination_rate": float,
    #         "scores": {...dimension->0-100...}, "threshold_breach": bool,
    #         "preset_id": str | None, "evaluation_id": str | None}.
    # Nullable because eval runs off for most systems (gated by workspace
    # preset + capability.eval_enabled) and pre-E1 runs never produced one.
    evaluation_scores = Column(JSON, nullable=True)

    trigger = Column(String(40), default="manual")  # manual | scheduler | webhook | adaptive | hitl

    system = relationship("System", back_populates="runs")
    invocations = relationship(
        "SkillInvocation", back_populates="run", cascade="all, delete-orphan", order_by="SkillInvocation.started_at"
    )


class SkillInvocation(Base):
    __tablename__ = "skill_invocations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id = Column(String(36), ForeignKey("runs.id"), nullable=False, index=True)
    skill_id = Column(String(36), nullable=True, index=True)
    skill_slug = Column(String(160), nullable=True, index=True)

    input_ref = Column(JSON, default=dict)
    output_ref = Column(JSON, default=dict)

    status = Column(String(20), default="pending")
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    latency_ms = Column(Float, nullable=True)

    cost = Column(Float, default=0.0)
    metrics = Column(JSON, default=dict)
    trace = Column(JSON, default=dict)

    error = Column(Text, nullable=True)

    run = relationship("Run", back_populates="invocations")
