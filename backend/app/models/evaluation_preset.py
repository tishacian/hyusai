"""Evaluation preset — tunable thresholds for the post-run auto-eval loop.

Mirrors :mod:`app.models.rag_preset` intentionally: scope +
``scope_id`` + ``workspace_id`` + JSON ``config`` + ``is_default``.
The config shape is small and stable so we keep it typed at the
service layer (:class:`~app.services.evaluation_preset_service`) rather
than polluting the DB with dozens of nullable columns.

Canonical config keys (see ``DEFAULT_EVAL_CONFIG`` in the service):

- ``enabled`` (bool) — master kill-switch per scope.
- ``composite_min`` (0-100) — below this, the run is flagged as
  ``review_required``.
- ``hallucination_max`` (0-1) — above this, ditto.
- ``dimension_min`` (dict[str, float]) — per-dimension floor,
  e.g. ``{"coherence": 60, "safety": 80}``.
- ``sample_rate`` (0-1) — probabilistic gate, avoids hammering the
  LLM judge on every single run. Default 1.0 (all runs).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
)

from app.db.base import Base


class EvaluationPreset(Base):
    __tablename__ = "evaluation_presets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(120), nullable=False)

    scope = Column(String(16), nullable=False)
    scope_id = Column(String(36), nullable=True)

    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    config = Column(JSON, nullable=False, default=dict)

    is_default = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "scope IN ('workspace', 'capability', 'system')",
            name="ck_evaluation_presets_scope",
        ),
        Index("ix_evaluation_presets_scope", "scope", "scope_id"),
    )
