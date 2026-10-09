"""Which way every metric ranks, and how it reads — one registry for API and UI.

The direction used to live twice: ``_HIGHER_IS_BETTER`` in the lifecycle and a
``higherIsBetter`` flag in the frontend, which answered *true* for any key it
did not know. A forecast's MASE or sMAPE is an error, so that default would
rank the worst version first. Here a metric absent from the registry has no
direction, and an unranked metric is never used to pick a challenger.

Thresholds exist only where the scale is absolute (an AUC of 0.5 is a coin
toss on any dataset); an error in the target's own units gets no verdict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

MAX, MIN, NONE = "max", "min", "none"


@dataclass(frozen=True, slots=True)
class MetricSpec:
    key: str
    direction: str  # max | min | none
    scale: str  # ratio (0–1) | percent (0–100) | value (target units)
    good: float | None = None
    poor: float | None = None

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"key": self.key, "direction": self.direction, "scale": self.scale}
        if self.good is not None and self.poor is not None:
            body.update({"good": self.good, "poor": self.poor})
        return body


METRICS: tuple[MetricSpec, ...] = (
    # Both scores can be negative; neither has a universal quality threshold.
    MetricSpec("silhouette", MAX, "value"),
    MetricSpec("stability_ari", MAX, "value"),
    MetricSpec("roc_auc", MAX, "ratio", 0.8, 0.65),
    MetricSpec("accuracy", MAX, "ratio", 0.85, 0.7),
    MetricSpec("balanced_accuracy", MAX, "ratio", 0.8, 0.65),
    MetricSpec("f1", MAX, "ratio", 0.8, 0.6),
    MetricSpec("precision", MAX, "ratio", 0.8, 0.6),
    MetricSpec("recall", MAX, "ratio", 0.8, 0.6),
    MetricSpec("r2", MAX, "ratio", 0.7, 0.4),
    MetricSpec("mape", MIN, "percent", 10, 25),
    MetricSpec("mae", MIN, "value"),
    MetricSpec("rmse", MIN, "value"),
    # Calibration: what counts as a good log loss depends on the class balance,
    # so no absolute verdict; the delta against the previous version still reads.
    MetricSpec("log_loss", MIN, "value"),
    MetricSpec("brier_score", MIN, "value"),
    # Forecasting. MASE/RMSSE are scaled by the seasonal-naive error, so 1.0 is
    # "no better than repeating last season" on any series — an absolute scale.
    MetricSpec("mase", MIN, "value", 0.8, 1.0),
    MetricSpec("rmsse", MIN, "value", 0.8, 1.0),
    MetricSpec("smape", MIN, "percent", 10, 25),
    # Coverage is judged against the interval's nominal level, not by size.
    MetricSpec("coverage", NONE, "ratio"),
    MetricSpec("interval_width", MIN, "value"),
)
METRIC_BY_KEY = {spec.key: spec for spec in METRICS}


def direction(key: Any) -> int | None:
    """+1 when higher is better, -1 when lower is, ``None`` when unranked."""

    spec = METRIC_BY_KEY.get(str(key))
    if spec is None or spec.direction == NONE:
        return None
    return 1 if spec.direction == MAX else -1


def rank_value(key: Any, value: Any) -> float | None:
    """A value where larger always means better, or ``None`` if not rankable."""

    sign = direction(key)
    if sign is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return sign * float(value)


def payload() -> list[dict[str, Any]]:
    return [spec.payload() for spec in METRICS]
