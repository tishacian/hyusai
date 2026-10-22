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
