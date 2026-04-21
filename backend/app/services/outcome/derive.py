"""Canonical Outcome derivation — hybrid strategy.

Strategy (mental model §22.3):

1. Auto-derive {cost, value, confidence, efficiency} from the Run + its
   Capability ROI model whenever the run completes.
2. Flag `value_source = auto` if a ROI model yielded a concrete number,
   `unset` otherwise.
3. Operator override via `apply_operator_override` re-writes `value` and
   flips `value_source` to `operator`, preserving the auto-derived cost,
   confidence and efficiency as an audit trail.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.schemas.canonical import Outcome, ValueSource


@dataclass
class DerivedOutcome:
    """Internal DTO the engine writes back to the Run row."""

    cost: float
    value: float
    confidence: Optional[float]
    efficiency: Optional[float]
    decision: str
    value_source: ValueSource

    def as_outcome(self) -> Outcome:
        return Outcome(
            cost=self.cost,
            value=self.value,
            confidence=self.confidence,
            efficiency=self.efficiency,
            value_source=self.value_source,
        )


def derive_outcome(
    *,
    invocations: List[SkillInvocation],
    capability: Optional[Capability],
    control_hitl_threshold: Optional[float] = None,
    duration_ms: float,
) -> DerivedOutcome:
    """Main entry point called by the run engine when a run completes."""
    completed = [i for i in invocations if i.status == "completed"]
    failed = [i for i in invocations if i.status == "failed"]

    cost = float(sum((i.cost or 0.0) for i in invocations))
    confidence = _extract_confidence(completed)
    decision = _derive_decision(completed, failed, control_hitl_threshold, confidence)
    value, source = _estimate_value(capability, decision, confidence)
    efficiency = _compute_efficiency(value, cost, duration_ms)

    return DerivedOutcome(
        cost=cost,
        value=value,
        confidence=confidence,
        efficiency=efficiency,
        decision=decision,
        value_source=source,
    )


def apply_operator_override(
    run: Run,
    *,
    value: float,
    note: Optional[str] = None,
) -> Outcome:
    """Operator-side override. Preserves cost/confidence/efficiency from
    the auto-derivation and only re-computes efficiency based on the new
    value. The prior value is kept in operator_value_note for audit.
    """
    previous = run.value_estimated
    run.value_estimated = float(value)
    run.value_source = ValueSource.operator.value
    trail = f"override: {value:.2f} (was {previous}) — {note or ''}".strip()
    run.operator_value_note = trail[:1000]
    # Recompute efficiency against the new value, keeping cost + duration.
    run.efficiency = _compute_efficiency(
        value=run.value_estimated or 0.0,
        cost=run.cost_internal or 0.0,
        duration_ms=run.duration_ms or 0.0,
    )
    return Outcome(
        cost=run.cost_internal,
        value=run.value_estimated,
        confidence=run.confidence,
        efficiency=run.efficiency,
        value_source=ValueSource.operator,
    )


# ---------------------------------------------------------------------------
# Internal helpers — pulled out of the engine so they can be unit-tested.
# ---------------------------------------------------------------------------
def _extract_confidence(invocations: List[SkillInvocation]) -> Optional[float]:
    for inv in invocations:
        out = inv.output_ref or {}
        if "confidence" in out:
            try:
                return float(out["confidence"])
            except (TypeError, ValueError):
                continue
    if not invocations:
        return None
    return round(len(invocations) / max(len(invocations), 1), 3)


def _derive_decision(
    completed: List[SkillInvocation],
    failed: List[SkillInvocation],
    hitl_threshold: Optional[float],
    confidence: Optional[float],
) -> str:
    if not completed and failed:
        return "failed"
    if hitl_threshold is not None:
        if (confidence or 0) < hitl_threshold:
            return "hitl_escalated"
    if failed:
        return "partial"
    return "approved"


def _estimate_value(
    capability: Optional[Capability],
    decision: str,
    confidence: Optional[float],
) -> tuple[float, ValueSource]:
    """Return (value, source). Source is `auto` whenever a ROI model or
    value_per_outcome is declared on the Capability, otherwise `unset`.
    """
    if capability is None:
        return 0.0, ValueSource.unset

    roi_model: Dict[str, Any] = capability.roi_model or {}
    if isinstance(roi_model, dict) and roi_model:
        base = _roi_model_base(roi_model, capability)
        multiplier = _decision_multiplier(decision)
        confidence_factor = _confidence_factor(roi_model, confidence)
        value = max(0.0, base * multiplier * confidence_factor)
        return round(value, 4), ValueSource.auto

    if capability.value_per_outcome is not None:
        multiplier = _decision_multiplier(decision)
        return round(float(capability.value_per_outcome) * multiplier, 4), ValueSource.auto

    return 0.0, ValueSource.unset


def _roi_model_base(roi_model: Dict[str, Any], capability: Capability) -> float:
    """Extract the base value. Supported keys (union):
    - `value_per_outcome` (float, preferred)
    - `expected_value` (float, legacy alias)
    - `base_value` (float, even older alias)
    Falls back to `capability.value_per_outcome`.
    """
    for key in ("value_per_outcome", "expected_value", "base_value"):
        try:
            raw = roi_model.get(key)
            if raw is not None:
                return float(raw)
        except (TypeError, ValueError):
            continue
    if capability.value_per_outcome is not None:
        return float(capability.value_per_outcome)
    return 0.0


def _decision_multiplier(decision: str) -> float:
    return {
        "approved": 1.0,
        "partial": 0.5,
        "hitl_escalated": 0.0,
        "failed": 0.0,
        "blocked": 0.0,
    }.get(decision, 0.0)


def _confidence_factor(roi_model: Dict[str, Any], confidence: Optional[float]) -> float:
    """Optional blending: `confidence_weight` in [0,1] controls how much the
    reported confidence discounts the auto-derived value. Defaults to 0.5
    so a 0.7-confidence answer delivers 85% of the nominal value.
    """
    if confidence is None:
        return 1.0
    try:
        weight = float(roi_model.get("confidence_weight", 0.5))
    except (TypeError, ValueError):
        weight = 0.5
    weight = max(0.0, min(1.0, weight))
    return max(0.0, min(1.0, 1.0 - weight * (1.0 - confidence)))


def _compute_efficiency(value: float, cost: float, duration_ms: float) -> Optional[float]:
    if cost <= 0:
        return None
    roi = (value - cost) / cost if cost else 0.0
    speed = 1.0 / (1.0 + duration_ms / 5000.0)
    return round(max(0.0, roi) * speed, 3)
