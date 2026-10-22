from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.run_follow_up import run_follow_up


def _run(status, *, error=None, checkpoints=None, parent_run_id=None, evaluation_binding=None):
    return SimpleNamespace(
        status=status,
        error=error,
        checkpoints=checkpoints or [],
        parent_run_id=parent_run_id,
        evaluation_binding=evaluation_binding,
    )


def test_evaluation_stop_at_human_gate_is_a_planned_boundary_not_a_failure():
    run = _run(
        "cancelled",
        error="EVALUATION_STOPPED_AT_HUMAN_GATE",
        checkpoints=[
            {"kind": "hitl_pause", "node_id": "review", "decision_id": "dec-1"},
            {
                "kind": "evaluation_boundary",
                "boundary": "human_gate",
                "node_id": "review",
                "decision_id": "dec-1",
            },
        ],
    )

    assert run_follow_up(run) == {
        "native_status": "cancelled",
        "business_state": "stopped_at_review_boundary",
        "cause": {
            "code": "evaluation_stopped_at_review_boundary",
            "boundary": "human_gate",
            "node_id": "review",
            "decision_id": "dec-1",
        },
        "attempt": None,
    }


def test_policy_gate_boundary_is_kept_in_the_cause():
    run = _run(
        "cancelled",
        error="EVALUATION_STOPPED_AT_HUMAN_GATE",
        checkpoints=[{"kind": "evaluation_boundary", "boundary": "policy_gate"}],
    )

    follow_up = run_follow_up(run)

    assert follow_up["business_state"] == "stopped_at_review_boundary"
    assert follow_up["cause"]["boundary"] == "policy_gate"


def test_boundary_error_without_checkpoint_still_projects_the_boundary():
    follow_up = run_follow_up(_run("cancelled", error="EVALUATION_STOPPED_AT_HUMAN_GATE"))

    assert follow_up["business_state"] == "stopped_at_review_boundary"
    assert follow_up["cause"] == {
        "code": "evaluation_stopped_at_review_boundary",
        "boundary": "human_gate",
    }


def test_operator_cancellation_stays_a_cancellation():
    assert run_follow_up(_run("cancelled")) == {
        "native_status": "cancelled",
        "business_state": "cancelled",
        "cause": None,
        "attempt": None,
    }


def test_pending_human_decision_points_to_its_pause():
    run = _run(
        "hitl_pending",
        checkpoints=[{"kind": "hitl_pause", "node_id": "gate", "decision_id": "dec-9"}],
    )

    assert run_follow_up(run)["cause"] == {
        "code": "human_decision_required",
        "node_id": "gate",
        "decision_id": "dec-9",
    }
    assert run_follow_up(run)["business_state"] == "awaiting_human_decision"


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("pending", "in_progress"),
        ("running", "in_progress"),
        ("waiting_subflows", "in_progress"),
        ("debug_pending", "paused_for_debug"),
        ("completed", "completed"),
        ("failed", "failed"),
        ("something_new", "unknown"),
        (None, "unknown"),
    ],
)
def test_native_statuses_map_to_one_business_state(status, state):
    assert run_follow_up(_run(status))["business_state"] == state


def test_hidden_payload_keeps_the_state_but_drops_identifiers():
    run = _run(
        "cancelled",
        error="EVALUATION_STOPPED_AT_HUMAN_GATE",
        checkpoints=[
            {"kind": "evaluation_boundary", "boundary": "human_gate", "decision_id": "dec-1"}
        ],
    )

    follow_up = run_follow_up(run, payload_visible=False)

    assert follow_up["business_state"] == "stopped_at_review_boundary"
    assert follow_up["cause"] == {"code": "evaluation_stopped_at_review_boundary"}


def test_a_retry_names_its_attempt_and_the_run_it_repeats():
    run = _run(
        "cancelled",
        error="EVALUATION_STOPPED_AT_HUMAN_GATE",
        parent_run_id="run-initial",
        evaluation_binding={"attempt_index": 1, "attempt_id": "a-1"},
    )

    assert run_follow_up(run)["attempt"] == {"index": 1, "previous_run_id": "run-initial"}
    assert run_follow_up(run, payload_visible=False)["attempt"] is None


def test_a_replay_without_evaluation_still_links_its_parent():
    run = _run("completed", parent_run_id="run-before", evaluation_binding={"attempt_index": "2"})

    assert run_follow_up(run)["attempt"] == {"index": None, "previous_run_id": "run-before"}


from datetime import datetime, timedelta, timezone  # noqa: E402

from app.services.run_follow_up import (  # noqa: E402
    run_decision_state,
    run_follow_up_detail,
    run_subject,
)

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def _paused(status="hitl_pending", **extra):
    run = _run(
        status,
        checkpoints=[
            {
                "kind": "hitl_pause",
                "node_id": "review",
                "decision_id": "dec-1",
                "prompt": "Open a carrier investigation",
                "expires_at": (NOW + timedelta(hours=2)).replace(tzinfo=None).isoformat(),
                "expiry_action": "reject",
            },
            *extra.pop("checkpoints", []),
        ],
    )
    run.id = "run-1"
    run.input_ref = extra.pop("input_ref", {"claim_id": "RC-1", "_ingress": {"x": 1}})
    run.decision = None
    return run


def test_an_open_decision_carries_its_server_computed_deadline():
    state = run_decision_state(_paused(), now=NOW)

    assert state["state"] == "awaiting"
    assert state["expires_at"] == "2026-10-22T14:00:00Z"
    assert state["seconds_remaining"] == 7200
    assert state["expiry_action"] == "reject"


def test_a_deadline_already_passed_is_expired_even_before_the_sweep():
    state = run_decision_state(_paused(), now=NOW + timedelta(hours=3))

    assert state["state"] == "expired"
    assert state["seconds_remaining"] == 0


def test_an_applied_expiry_is_reported_with_its_time_and_action():
    run = _paused(
        "failed",
        checkpoints=[
            {
                "kind": "gate_ttl_expired",
                "t": "2026-10-22T14:00:05",
                "decision_id": "dec-1",
                "expiry_action": "reject",
            }
        ],
    )

    state = run_decision_state(run, now=NOW)

    assert state["state"] == "expired"
    assert state["expired_at"] == "2026-10-22T14:00:05Z"
    assert state["expiry_action"] == "reject"


def test_the_decision_row_deadline_wins_over_the_checkpoint_copy():
    decision = SimpleNamespace(
        expires_at=datetime(2026, 10, 22, 13, 0),
        expiry_action="escalate",
        title="Approve the refund",
        status="proposed",
    )

    state = run_decision_state(_paused(), decision=decision, now=NOW)

    assert state["expires_at"] == "2026-10-22T13:00:00Z"
    assert state["expiry_action"] == "escalate"
    assert state["title"] == "Approve the refund"


def test_a_run_that_never_paused_has_no_decision():
    assert run_decision_state(_run("completed"), now=NOW) is None


def test_subject_reads_input_identifiers_and_skips_internal_keys():
    run = SimpleNamespace(input_ref={"_case_id": "hidden", "note": "x", "order_number": 42})
    assert run_subject(run) == {"field": "order_number", "value": "42"}
    assert run_subject(SimpleNamespace(input_ref={"flag": True})) is None


def test_detail_hides_payload_facts_when_the_reader_cannot_see_them():
    visible = run_follow_up_detail(_paused(), payload_visible=True, now=NOW)
    hidden = run_follow_up_detail(_paused(), payload_visible=False, now=NOW)

    assert visible["subject"] == {"field": "claim_id", "value": "RC-1"}
    assert visible["proposal"] == "Open a carrier investigation"
    assert visible["business_state"] == "awaiting_human_decision"
    assert hidden["subject"] is None and hidden["proposal"] is None
    assert hidden["decision"]["decision_id"] is None
    assert hidden["decision"]["state"] == "awaiting"
    assert hidden["payload_unavailable_reason"] == "evidence_unavailable"
