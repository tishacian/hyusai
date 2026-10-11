"""Evaluation feedback persistence — E1.5.1.

This service is the single write path into ``evaluation_feedback``.
Going through it (rather than directly instantiating the model) gives
us:

- Validation of ``label`` against ``FEEDBACK_LABELS`` so callers can't
  drift the enum silently.
- Audit emission (``evaluation.feedback.recorded``) using the caller's
  DB session, so the row + audit are atomic when the caller commits.
- A single place to extend the signal later (idempotency by
  ``(decision_id, run_id, label)``, dedup, downstream fan-out) without
  touching the endpoints.

The function intentionally does NOT call ``db.commit()``: the caller
(typically the hypervisor accept/reject endpoint) commits as part of
its own transaction. That keeps the feedback row tied to the Decision
status flip — they either both land or neither.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.evaluation_feedback import EvaluationFeedback, FEEDBACK_LABELS
from app.services.audit_logger import emit_audit_event


class InvalidFeedback(ValueError):
    """Raised on bad inputs (unknown label, missing run_id, …)."""


def record_feedback(
    db: DBSession,
    *,
    workspace_id: str,
    run_id: str,
    label: str,
    decision_id: Optional[str] = None,
    evaluation_score_id: Optional[str] = None,
    notes: Optional[str] = None,
    corrected_output: Optional[Dict[str, Any]] = None,
    actor: Optional[str] = None,
) -> EvaluationFeedback:
    if not workspace_id:
        raise InvalidFeedback("workspace_id is required")
    if not run_id:
        raise InvalidFeedback("run_id is required")
    if label not in FEEDBACK_LABELS:
        raise InvalidFeedback(
            f"unknown feedback label {label!r}; expected one of {FEEDBACK_LABELS}"
        )

    fb = EvaluationFeedback(
        id=str(uuid4()),
        workspace_id=workspace_id,
        decision_id=decision_id,
        run_id=run_id,
        evaluation_score_id=evaluation_score_id,
        label=label,
        notes=notes or None,
        corrected_output=corrected_output or None,
        created_by=actor or "demo-user",
        created_at=datetime.utcnow(),
    )
    db.add(fb)
    db.flush()

    emit_audit_event(
        workspace_id=workspace_id,
        event_type="evaluation.feedback.recorded",
        actor=actor or "demo-user",
        details={
            "feedback_id": fb.id,
            "decision_id": decision_id,
            "run_id": run_id,
            "evaluation_score_id": evaluation_score_id,
            "label": label,
            "has_correction": bool(corrected_output),
        },
        db=db,
    )
    return fb


def serialize_feedback(fb: EvaluationFeedback) -> Dict[str, Any]:
    return {
        "id": fb.id,
        "workspace_id": fb.workspace_id,
        "decision_id": fb.decision_id,
        "run_id": fb.run_id,
        "evaluation_score_id": fb.evaluation_score_id,
        "label": fb.label,
        "notes": fb.notes,
        "corrected_output": fb.corrected_output,
        "created_by": fb.created_by,
        "created_at": fb.created_at.isoformat() if fb.created_at else None,
    }
