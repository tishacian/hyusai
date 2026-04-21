"""Canonical System model — supersedes the localStorage `agent` draft.

A System is the deployable composition: an Objective + a Capability + a
Context + a flow of certified Skills, governed by a ControlPolicy and an
optional AdaptivePolicy. Every Run executes against a single System.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from app.db.base import Base


class System(Base):
    __tablename__ = "systems"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True, index=True)

    name = Column(String(200), nullable=False)
    objective = Column(Text, nullable=False, default="")
    capability_id = Column(String(36), ForeignKey("capabilities.id"), nullable=True, index=True)

    # Composition
    skill_ids = Column(JSON, default=list)         # list[str] — refs Skill.id
    flow_definition = Column(JSON, default=dict)   # drawflow-style JSON for the Flow

    # Execution — canonical modes: real_time_decision | batch_processing |
    # event_driven_automation | continuous_monitoring | human_augmented.
    # execution_profile carries SLA (latency target, max runtime), durability
    # flags and pricing profile associated with the mode.
    execution_mode = Column(String(40), default="real_time_decision")
    execution_profile = Column(JSON, nullable=True)
    coordination_pattern = Column(String(40), default="single_agent")

    control_policy_id = Column(String(36), ForeignKey("control_policies.id"), nullable=True)
    adaptive_policy_id = Column(String(36), ForeignKey("adaptive_policies.id"), nullable=True)
    context_id = Column(String(36), ForeignKey("contexts.id"), nullable=True)

    status = Column(String(20), default="draft", index=True)  # draft | active | paused | retired
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
