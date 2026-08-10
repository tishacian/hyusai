"""What a balance-sheet signal is allowed to claim about one run.

The cockpit displayed "High-yield outcome · ROI 1462400.0%" in production. The
percentage was arithmetically right and editorially worthless: several seeded
skills are priced at 0.0, so a run whose measured cost was a fraction of a cent
turned any value at all into a four-digit ratio. These tests pin the two rules
that make the claim honest — a cost floor before yield is asserted, and a single
ratio-to-percent conversion with a cap — plus the sibling branches, so a future
edit cannot reintroduce the number by touching the format alone.
"""
from __future__ import annotations

from app.api.v1.endpoints.hypervisor import (
    MAX_SIGNAL_ROI_RATIO,
    MIN_SIGNAL_COST,
    _signal_label,
    _signals,
)
from app.models.run import Run


def _run(**kwargs) -> Run:
    payload = {"id": "run-signal", "status": "completed"}
    payload.update(kwargs)
    return Run(**payload)


def test_a_negligible_cost_cannot_manufacture_a_high_yield_claim():
    """The exact denominator that produced the 1462400% label."""

    run = _run(value_estimated=1.46, cost_internal=0.0001, decision="approved")

    assert _signal_label(run) == "Run completed · decision approved"
    assert _signals([run])[0]["tone"] == "neutral"


def test_a_measured_cost_reports_the_ratio_as_percent_exactly_once():
    """`(3.0 - 1.0) / 1.0` is a ratio of 2, which is 200% — not 20000%."""

    run = _run(value_estimated=3.0, cost_internal=1.0)

    assert _signal_label(run) == "High-yield outcome · ROI 200.0%"
    assert _signals([run])[0]["tone"] == "pos"


def test_an_extreme_ratio_is_capped_rather_than_printed_in_full():
    run = _run(value_estimated=15_000.0, cost_internal=MIN_SIGNAL_COST)

    assert _signal_label(run) == "High-yield outcome · ROI > 1000%"
    assert f"{MAX_SIGNAL_ROI_RATIO * 100:.0f}" == "1000"


def test_the_cost_floor_is_the_only_thing_between_the_two_verdicts():
    """One cent of measured cost is the boundary, and it is inclusive."""

    at_floor = _run(value_estimated=1.0, cost_internal=MIN_SIGNAL_COST)
    below_floor = _run(value_estimated=1.0, cost_internal=MIN_SIGNAL_COST / 2)

    assert _signal_label(at_floor).startswith("High-yield outcome")
    assert _signal_label(below_floor).startswith("Run completed")


def test_a_run_yielding_less_than_it_cost_states_its_decision_instead():
    run = _run(value_estimated=0.5, cost_internal=1.0, decision="rejected")

    assert _signal_label(run) == "Run completed · decision rejected"
    assert _signals([run])[0]["tone"] == "neutral"


def test_the_sibling_branches_stay_free_of_computed_figures():
    failed = _run(status="failed", error="skill timeout")
    silent = _run(status="failed")
    running = _run(status="running")
    undecided = _run(value_estimated=2.0, cost_internal=None)

    assert _signal_label(failed) == "Run failed · skill timeout"
    assert _signal_label(silent) == "Run failed · unknown error"
    assert _signal_label(running) == "Run running"
    assert _signal_label(undecided) == "Run completed · decision —"
    assert [item["tone"] for item in _signals([failed, running])] == ["neg", "neutral"]


def test_low_confidence_still_outranks_a_yield_claim_in_the_tone():
    run = _run(value_estimated=3.0, cost_internal=1.0, confidence=0.4)

    assert _signals([run])[0]["tone"] == "warn"
    assert _signal_label(run) == "High-yield outcome · ROI 200.0%"
