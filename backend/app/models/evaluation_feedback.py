"""Evaluation feedback model — E1.5.1.

Captures the human signal produced when a reviewer triages a
``Decision(kind=review_required)`` (or grades a Run directly). Closes
the open end of the eval loop so accept/reject is no longer a status
change on a graveyard row.

See migration ``016_evaluation_feedback`` for column-by-column rationale.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text

from app.db.base import Base


FEEDBACK_LABELS = ("false_positive", "true_breach", "correct_with_fix")


class EvaluationFeedback(Base):
    __tablename__ = "evaluation_feedback"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id"),
        nullable=False,
        index=True,
    )
    # Optional FK to the triage decision. Nullable so a future
    # `POST /runs/{id}/feedback` (👍 / 👎 from the chat surface) can
    # write here without going through the Decision lifecycle.
    decision_id = Column(String(36), nullable=True, index=True)
    run_id = Column(String(36), nullable=False, index=True)
    # The specific EvaluationScore row whose breach was being judged.
    # Nullable for the same reason as decision_id.
    evaluation_score_id = Column(String(36), nullable=True)

    label = Column(String(40), nullable=False)
    notes = Column(Text, nullable=True)
    corrected_output = Column(JSON, nullable=True)

    created_by = Column(String(255), nullable=False, default="demo-user")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
