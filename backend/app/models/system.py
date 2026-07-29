"""Canonical System model — supersedes the localStorage `agent` draft.

A System is the deployable composition: an Objective + a Capability + a
Context + a flow of certified Skills, governed by a ControlPolicy and an
optional AdaptivePolicy. Every Run executes against a single System.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.schemas.canonical import ExecutionMode, SystemStatus


def _enum_check(column: str, values: list[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class System(Base):
    __tablename__ = "systems"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True, index=True)
    # Portable, opaque identity used by Workspace Blueprints. Names remain
    # presentation data and are deliberately not unique inside a workspace.
    blueprint_key = Column(String(120), nullable=False, default=lambda: str(uuid4()))

    name = Column(String(200), nullable=False)
    objective = Column(Text, nullable=False, default="")
    capability_id = Column(String(36), ForeignKey("capabilities.id"), nullable=True, index=True)

    # Composition
    skill_ids = Column(JSON, default=list)  # list[str] — refs Skill.id
    flow_definition = Column(JSON, default=dict)  # drawflow-style JSON for the Flow
    settings = Column(JSON, nullable=False, default=dict)

    # Execution — canonical modes: real_time_decision | batch_processing |
    # event_driven_automation | continuous_monitoring | human_augmented.
    # execution_profile carries SLA (latency target, max runtime), durability
    # flags and pricing profile associated with the mode.
    execution_mode = Column(String(40), nullable=False, default="real_time_decision")
    execution_profile = Column(JSON, nullable=True)
    coordination_pattern = Column(String(40), default="single_agent")

    control_policy_id = Column(String(36), ForeignKey("control_policies.id"), nullable=True)
    adaptive_policy_id = Column(String(36), ForeignKey("adaptive_policies.id"), nullable=True)
    context_id = Column(String(36), ForeignKey("contexts.id"), nullable=True)

    status = Column(
        String(20), nullable=False, default="draft", index=True
    )  # draft | active | paused | retired
    created_by = Column(String(255), default="demo-user")

    # Per-system defaults exposed by the Builder (Wave B + C).
    #   default_prompt_type      -> SystemPromptType slug (factual / analytical / ...)
    #   default_model            -> LLM model override (provider/model string)
    #   retrieval_mode_default   -> naive | hybrid | hah | chah | auto
    default_prompt_type = Column(String(40), nullable=True)
    default_model = Column(String(120), nullable=True)
    retrieval_mode_default = Column(String(20), nullable=True, default="auto")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    capability = relationship("Capability", lazy="joined", foreign_keys=[capability_id])
    runs = relationship("Run", back_populates="system", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_systems_workspace_id",
        ),
        CheckConstraint(
            _enum_check("status", [item.value for item in SystemStatus]),
            name="ck_systems_status",
        ),
        CheckConstraint(
            _enum_check("execution_mode", [item.value for item in ExecutionMode]),
            name="ck_systems_execution_mode",
        ),
        UniqueConstraint(
            "workspace_id",
            "blueprint_key",
            name="uq_systems_workspace_blueprint_key",
        ),
        Index(
            "uq_systems_global_blueprint_key",
            "blueprint_key",
            unique=True,
            postgresql_where=text("workspace_id IS NULL"),
            sqlite_where=text("workspace_id IS NULL"),
        ),
    )
