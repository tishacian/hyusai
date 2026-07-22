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
