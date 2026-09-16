from __future__ import annotations

from app.models.run import SkillInvocation
from app.services.outcome.derive import derive_outcome


def _invocation(
    invocation_id: str,
    *,
    cost: float,
    cost_measured: bool | None,
) -> SkillInvocation:
    return SkillInvocation(
        id=invocation_id,
        run_id="run-cost-measurement",
        skill_slug=invocation_id,
        status="completed",
        cost=cost,
        cost_measured=cost_measured,
    )


def test_derive_outcome_aggregates_only_explicit_cost_measurements() -> None:
    outcome = derive_outcome(
        invocations=[
            _invocation("measured", cost=1.5, cost_measured=True),
            _invocation("synthetic", cost=999.0, cost_measured=False),
            _invocation("historical", cost=500.0, cost_measured=None),
        ],
        capability=None,
        duration_ms=100.0,
    )

    assert outcome.cost == 1.5


def test_derive_outcome_preserves_unknown_and_measured_zero_cost_states() -> None:
    unknown = derive_outcome(
        invocations=[_invocation("historical", cost=0.0, cost_measured=None)],
        capability=None,
        duration_ms=100.0,
    )
    assert unknown.cost is None
    assert unknown.efficiency is None
    assert unknown.as_outcome().cost is None

    measured_zero = derive_outcome(
        invocations=[_invocation("free-tariff", cost=0.0, cost_measured=True)],
        capability=None,
        duration_ms=100.0,
    )
    assert measured_zero.cost == 0.0
    assert measured_zero.efficiency is None


def test_completed_invocations_do_not_manufacture_confidence():
    from types import SimpleNamespace
    from app.services.outcome.derive import _extract_confidence

    assert _extract_confidence([SimpleNamespace(output_ref={})]) is None
    for value in [True, -0.1, 1.1, float('nan'), float('inf'), 'invalid']:
        assert _extract_confidence([SimpleNamespace(output_ref={'confidence': value})]) is None
    assert _extract_confidence([SimpleNamespace(output_ref={'confidence': 0})]) == 0
    assert _extract_confidence([SimpleNamespace(output_ref={'confidence': 0.8})]) == 0.8


def test_completion_is_not_an_approval_and_failed_invocations_remain_visible():
    from types import SimpleNamespace
    from app.services.outcome.derive import _derive_decision

    completed = [SimpleNamespace(status="completed")]
    failed = [SimpleNamespace(status="failed")]
    assert _derive_decision(completed, [], None, None) is None
    assert _derive_decision(completed, [], None, 0.99) is None
    assert _derive_decision(completed, failed, None, None) == "partial"
    assert _derive_decision([], failed, None, None) == "failed"
    assert _derive_decision(completed, [], 0.8, None) == "hitl_escalated"


def test_declared_value_projection_does_not_require_manufactured_approval():
    from types import SimpleNamespace
    from app.services.outcome.derive import _estimate_value
    from app.schemas.canonical import ValueSource

    capability = SimpleNamespace(roi_model={"value_per_outcome": 100}, value_per_outcome=100)
    assert _estimate_value(capability, None, None) == (100.0, ValueSource.auto)
