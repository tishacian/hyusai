"""Canonical Decision log — what the Hypervisor recommended and what was
acted upon. Mirrors the "decision trail" of the executive cockpit.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), nullable=True, index=True)

    # Nullable for every pre-Lot-8 and non-value-loop Decision.  A non-null
    # value binds exactly one authoritative Decision to its ValueScenario.
    scenario_id = Column(String(36), nullable=True)

    scope = Column(String(20), default="capability")  # capability | system | run | portfolio
    target_id = Column(String(36), nullable=True, index=True)

    kind = Column(String(40), default="recommendation")
    # Canonical state machine: proposed -> accepted|rejected -> applied
    # (legacy `open` rows migrated to `proposed` by revision 007).
    status = Column(String(20), default="proposed")
    title = Column(String(255), nullable=False)
    rationale = Column(JSON, default=dict)

    impact_estimate = Column(JSON, default=dict)  # forecasted ROI delta, cost delta, …
    notes = Column(Text, default="")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    approved_by = Column(String(255), nullable=True)
    approved_at = Column(DateTime, nullable=True)

    # Gate TTL (HITL / membrane HOLD). When ``expires_at`` elapses while still
    # ``proposed``, ``scheduler_tick`` applies ``expiry_action``.
    # expiry_action: reject | approve | escalate
    expires_at = Column(DateTime, nullable=True, index=True)
    expiry_action = Column(String(20), nullable=True)

    # Enactment trace — filled when a decision transitions to `applied`.
    applied_at = Column(DateTime, nullable=True)
    applied_patch = Column(JSON, nullable=True)
    applied_by = Column(String(255), nullable=True)

    __table_args__ = (
        UniqueConstraint("scenario_id", name="uq_decisions_scenario_id"),
        ForeignKeyConstraint(
            ["workspace_id", "scenario_id", "target_id"],
            [
                "value_scenarios.workspace_id",
                "value_scenarios.id",
                "value_scenarios.system_id",
            ],
            name="fk_decisions_scenario_lineage",
            ondelete="RESTRICT",
        ),
        # Composite foreign keys use MATCH SIMPLE by default, so any NULL
        # component would otherwise bypass lineage enforcement.  Legacy and
        # non-value-loop Decisions may keep scenario_id NULL; a scenario-linked
        # Decision must carry the complete tenant/System identity.
        CheckConstraint(
            "scenario_id IS NULL OR "
            "(workspace_id IS NOT NULL AND target_id IS NOT NULL)",
            name="ck_decisions_scenario_lineage_complete",
        ),
    )
