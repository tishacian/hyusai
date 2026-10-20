"""Catalogue tariff evidence from trusted inference counts, never model payloads.

The collector lives only in a server-created invocation context. The engine
keeps its own reference; replacing JSON input/output or a context dictionary
entry cannot inject a price. Wrappers report completed rows, not money.
"""

from dataclasses import replace
from threading import Lock

from app.services.skill_invocation_snapshot import (
    _unmeasured_cost,
    resolve_skill_invocation_cost,
)

INFERENCE_UNITS = frozenset({"per_prediction", "per_1000_predictions"})
_CONTEXT_KEY = "_ml_inference_cost_collector"


def _valid_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _calculate(unit_price, row_count):
    if not unit_price.cost_measured:
        return unit_price
    unit = unit_price.evidence.get("unit")
    if unit not in INFERENCE_UNITS | {"per_call"}:
        return _unmeasured_cost("inference_pricing_unit_unsupported")
    if not _valid_count(row_count):
        return _unmeasured_cost("inference_quantity_not_measured")
    quantity = row_count / 1000 if unit == "per_1000_predictions" else row_count
    if unit == "per_call":
        quantity = 1
    return replace(
        unit_price,
        cost=round(unit_price.cost * quantity, 6),
        evidence={
            **unit_price.evidence,
            "quantity": quantity,
            "observed_rows": row_count,
            "quantity_source": "inference_runtime",
        },
    )


def inference_tariff(db, *, model, row_count):
    """Price an API call using its published Skill's explicit current tariff."""
    evidence = resolve_skill_invocation_cost(
        db,
        workspace_id=model.workspace_id,
        skill_id=model.published_skill_id,
        skill_slug=model.published_skill_slug,
        quantity=1,
    )
    result = _calculate(evidence, row_count)
    if result.cost_measured and result.evidence.get("currency") != "USD":
        return _unmeasured_cost("inference_pricing_currency_not_usd")
    return result


class InferenceCostCollector:
    """One invocation, immutable tariff snapshot, observed successful rows."""

    def __init__(self, unit_price):
        self._unit_price = unit_price
        self._rows = None
        self._lock = Lock()

    @classmethod
    def create(cls, db, *, workspace_id, skill_id, skill_slug):
        return cls(
            resolve_skill_invocation_cost(
                db,
                workspace_id=workspace_id,
                skill_id=skill_id,
                skill_slug=skill_slug,
                quantity=1,
            )
        )

    def record(self, row_count):
        if not _valid_count(row_count):
            raise ValueError("ML_COST_ROW_COUNT_INVALID")
        with self._lock:
            self._rows = (self._rows or 0) + row_count

    def settle(self, fallback):
        with self._lock:
            rows = self._rows
        if rows is None:
            return fallback
        return _calculate(self._unit_price, rows)


def install_collector(ctx, collector):
    ctx[_CONTEXT_KEY] = collector


def record_skill_inference(ctx, *, row_count):
    """Wrapper hook after execution; takes no cost and no prediction payload."""
    collector = (ctx or {}).get(_CONTEXT_KEY)
    if isinstance(collector, InferenceCostCollector):
        collector.record(row_count)
