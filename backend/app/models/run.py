"""Canonical Run + SkillInvocation models — supersede `traces`.

A Run is a single execution of a System against an input. It carries the
canonical Outcome block (decision, value, confidence, efficiency) and a
ledger of SkillInvocations. Hypervisor's Balance Sheet aggregates Runs
into Impact (per System / per Capability / portfolio).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)
    initiated_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    # Nullable since migration 012 — chat turns without a System
    # attachment are still first-class Runs (audit/eval on workspace
    # scope). Set to the System id when chat is launched from a
    # System-scoped UI (/systems/:id), NULL otherwise.
    system_id = Column(String(36), ForeignKey("systems.id"), nullable=True, index=True)
    capability_id = Column(String(36), nullable=True, index=True)

    input_ref = Column(JSON, default=dict)
    output_ref = Column(JSON, default=dict)

    # pending | running | waiting_subflows | hitl_pending | completed | failed | cancelled
    status = Column(String(20), default="pending", index=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Float, nullable=True)

    # Outcome block — canonical {cost, value, confidence, efficiency} + source
    decision = Column(String(40), nullable=True)
    confidence = Column(Float, nullable=True)
    value_estimated = Column(Float, nullable=True)
    cost_internal = Column(Float, nullable=True)
    provider_cost_usd = Column(Float, nullable=True)
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
    # P1 execution authority, frozen when the Run row is inserted. Historical
    # rows stay nullable and retain their existing engine fallback semantics.
    published_flow_version_id = Column(
        String(36),
        ForeignKey("system_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    flow_sha256 = Column(String(64), nullable=True, index=True)
    execution_contract = Column(JSON, nullable=True)
    execution_surface = Column(String(32), nullable=True, index=True)
    runner_session_id = Column(
        String(36),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Vague E / E1 — snapshot of the auto-eval pass fired at run completion.
    # Shape: {"composite_score": float, "hallucination_rate": float,
    #         "scores": {...dimension->0-100...}, "threshold_breach": bool,
    #         "preset_id": str | None, "evaluation_id": str | None}.
    # Nullable because eval runs off for most systems (gated by workspace
    # preset + capability.eval_enabled) and pre-E1 runs never produced one.
    evaluation_scores = Column(JSON, nullable=True)

    trigger = Column(
        String(40), default="manual"
    )  # manual | scheduler | webhook | adaptive | hitl | replay
    # Durable event-trigger idempotency claim. The key includes the System,
    # event kind and canonical payload hash; NULL keeps historical/manual Runs
    # outside this uniqueness domain.
    trigger_dedup_key = Column(String(255), nullable=True)
    # Stable claim for a business-app action. Unlike trigger_dedup_key, this
    # identity intentionally survives a deployment pointer change.
    experience_idempotency_key = Column(String(64), nullable=True, unique=True)

    # Vague E / E1.5.2 — replay lineage. ``parent_run_id`` points to the
    # run that was the source for a "Re-run with override" replay
    # triggered from the review queue or run-detail view. NULL on
    # original (non-replay) runs. ``replay_overrides`` captures the
    # dict of fields the operator changed (``query``, ``rag_pipeline_mode``,
    # ``model``, …) so audit can answer "what did they tweak?" without
    # diff'ing two ``input_ref`` blobs. NULL on non-replay runs.
    # No FK to keep hard-deletes cheap (workspace teardown, GDPR purge).
    parent_run_id = Column(String(36), nullable=True, index=True)
    replay_overrides = Column(JSON, nullable=True)

    # P4 durable delegation envelope.  The logical key is stable across broker
    # redeliveries, so retries always recover the same child Run.
    delegation_key = Column(String(64), nullable=True, unique=True)
    delegation_node_id = Column(String(160), nullable=True)
    delegation_branch = Column(String(160), nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    # Indexed absolute deadline used by the durable dispatcher/watchdog.  The
    # immutable delegation envelope remains the audit source; this projection
    # makes recovery queries bounded without JSON scans.
    delegation_deadline_at = Column(DateTime, nullable=True, index=True)
    # Typed, system-owned marker for a malformed delegated wait that the P4
    # watchdog terminalised.  Checkpoints remain the audit trail; this scalar
    # lets recovery queries distinguish an authorised weak parent handoff from
    # arbitrary historical error text without dialect-specific JSON scans.
    delegation_quarantined_at = Column(DateTime, nullable=True, index=True)
    waiting_subflows = Column(JSON, default=dict, nullable=False)

    system = relationship("System", back_populates="runs")
    invocations = relationship(
        "SkillInvocation",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="SkillInvocation.started_at",
    )

    __table_args__ = (
        UniqueConstraint(
            "system_id",
            "trigger_dedup_key",
            name="uq_runs_trigger_dedup_key",
        ),
        UniqueConstraint(
            "workspace_id",
            "system_id",
            "id",
            name="uq_runs_workspace_system_id",
        ),
    )


class SkillInvocation(Base):
    __tablename__ = "skill_invocations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id = Column(String(36), ForeignKey("runs.id"), nullable=False, index=True)
    skill_id = Column(String(36), nullable=True, index=True)
    skill_slug = Column(String(160), nullable=True, index=True)

    # Immutable, positive-allowlisted identity/contract evidence captured when
    # the invocation is created.  Historical rows intentionally remain NULL:
    # resolving their Skill from the mutable catalogue would rewrite history.
    execution_snapshot = Column(JSON, nullable=True)

    input_ref = Column(JSON, default=dict)
    output_ref = Column(JSON, default=dict)

    status = Column(String(20), default="pending")
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    latency_ms = Column(Float, nullable=True)

    cost = Column(Float, default=0.0)
    # Provider tariff in USD. NULL means unavailable; a genuine zero tariff is
    # represented by 0.0 with cost_measured=True.
    provider_cost_usd = Column(Float, nullable=True)
    # NULL means "unknown / historical".  New producers explicitly write
    # False while a cost is pending or synthetic.  True is reserved for a
    # provider measurement or a calculation backed by an identifiable,
    # explicitly configured tariff (including a genuine zero-cost tariff).
    # This prevents a legacy/default 0.0 from masquerading as evidence.
    cost_measured = Column(Boolean, nullable=True)
    metrics = Column(JSON, default=dict)
    trace = Column(JSON, default=dict)

    error = Column(Text, nullable=True)

    run = relationship("Run", back_populates="invocations")
