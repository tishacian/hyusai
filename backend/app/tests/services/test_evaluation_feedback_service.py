"""Tests for ``services.evaluation.feedback_service`` — E1.5.1.

Exercises the single write path into ``evaluation_feedback`` plus the
audit emission. Hypervisor accept/reject integration is covered by
the smoke script in ``/tmp`` (live VM) since it crosses the API
boundary.
"""
from __future__ import annotations

import pytest

from app.models.audit import AuditLog
from app.models.evaluation_feedback import EvaluationFeedback, FEEDBACK_LABELS
from app.services.evaluation.feedback_service import (
    InvalidFeedback,
    record_feedback,
    serialize_feedback,
)


def test_record_feedback_persists_row_and_audit(db_session) -> None:
    fb = record_feedback(
        db_session,
        workspace_id="ws-1",
        run_id="run-abc",
        label="false_positive",
        decision_id="dec-xyz",
        evaluation_score_id="score-1",
        notes="judge over-flagged",
        actor="alice",
    )
    assert fb.id
    assert fb.label == "false_positive"
    assert fb.workspace_id == "ws-1"
    assert fb.run_id == "run-abc"
    assert fb.decision_id == "dec-xyz"
    assert fb.notes == "judge over-flagged"
    assert fb.created_by == "alice"

    rows = db_session.query(EvaluationFeedback).all()
    assert len(rows) == 1

    audit_rows = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "evaluation.feedback.recorded")
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].details["feedback_id"] == fb.id
    assert audit_rows[0].details["label"] == "false_positive"
    assert audit_rows[0].details["has_correction"] is False


def test_record_feedback_with_corrected_output_flags_audit(db_session) -> None:
    fb = record_feedback(
        db_session,
        workspace_id="ws-1",
        run_id="run-abc",
        label="correct_with_fix",
        corrected_output={"answer": "the right one"},
        actor="bob",
    )
    assert fb.corrected_output == {"answer": "the right one"}
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "evaluation.feedback.recorded")
        .first()
    )
    assert audit is not None
    assert audit.details["has_correction"] is True


def test_invalid_label_rejected(db_session) -> None:
    with pytest.raises(InvalidFeedback):
        record_feedback(
            db_session,
            workspace_id="ws-1",
            run_id="run-abc",
            label="not-a-real-label",
        )
    assert db_session.query(EvaluationFeedback).count() == 0


def test_missing_run_id_rejected(db_session) -> None:
    with pytest.raises(InvalidFeedback):
        record_feedback(
            db_session,
            workspace_id="ws-1",
            run_id="",
            label="false_positive",
        )


def test_missing_workspace_rejected(db_session) -> None:
    with pytest.raises(InvalidFeedback):
        record_feedback(
            db_session,
            workspace_id="",
            run_id="run-abc",
            label="false_positive",
        )


def test_serialize_feedback_round_trip(db_session) -> None:
    fb = record_feedback(
        db_session,
        workspace_id="ws-1",
        run_id="run-abc",
        label="true_breach",
        notes="reviewer agrees with judge",
        actor="carol",
    )
    payload = serialize_feedback(fb)
    assert payload["id"] == fb.id
    assert payload["label"] == "true_breach"
    assert payload["created_at"] is not None
    assert payload["corrected_output"] is None


def test_all_canonical_labels_accepted(db_session) -> None:
    for label in FEEDBACK_LABELS:
        record_feedback(
            db_session,
            workspace_id="ws-1",
            run_id=f"run-{label}",
            label=label,
        )
    assert db_session.query(EvaluationFeedback).count() == len(FEEDBACK_LABELS)
