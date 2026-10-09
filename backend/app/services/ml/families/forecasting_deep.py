"""Frozen, local foundation forecasts in the optional ml-deep runtime.

The forecast task and its evidence stay the same. Only the execution family
changes: pretrained weights are never fitted, and every backtest origin gets
only the observations preceding it.
"""
from __future__ import annotations

from pathlib import Path

from app.services.ml.families.base import Family, SpecField
from app.services.ml.families.forecasting import FREQUENCIES, _distinct, _refuse, validate_forecast

MAX_HORIZON = 64
MAX_SERIES = 32
CONTEXT_LENGTH = 512
SPEC_FIELDS = (
    SpecField("time_column", "column", required=True, column_kinds=("datetime",)),
    SpecField("shape", "enum", default="single", choices=("single", "panel")),
    SpecField("series_columns", "columns", required=True, max_items=3, when=(("shape", ("panel",)),)),
    SpecField("horizon", "int", required=True, minimum=1, maximum=MAX_HORIZON),
    SpecField("frequency", "enum", default="auto", choices=FREQUENCIES),
    # Chronos-2's outer native quantiles are .01 and .99.
    SpecField("interval_level", "float", default=0.8, minimum=0.5, maximum=0.98),
    SpecField("backtest_folds", "int", default=3, minimum=1, maximum=5),
    SpecField("fill", "enum", default="refuse", choices=("refuse", "zero")),
)


def validate_foundation(dataset, *, task, target, features, algo, knobs, test_size,
                        cross_validation, name, spec):
    if str(algo or "") != "chronos_zero_shot":
        raise _refuse("ML_ALGO_TASK_MISMATCH", "This family uses the local Chronos zero-shot model.")
    if knobs not in (None, {}):
        raise _refuse("ML_SPEC_INVALID", "The frozen foundation model takes no estimator settings.", field="knobs")
    if features:
        raise _refuse("ML_SPEC_INVALID", "Zero-shot forecasting uses only the target's history.", field="features")
    if spec.get("shape") == "panel" and max(
        (_distinct(dataset, column) for column in spec.get("series_columns", [])), default=0
    ) > MAX_SERIES:
        raise _refuse("ML_TS_TOO_MANY_SERIES", f"Zero-shot forecasting supports at most {MAX_SERIES} series.")
    result = validate_forecast(
        dataset, task=task, target=target, features=[], algo=algo, knobs=knobs,
        test_size=test_size, cross_validation=cross_validation, name=name, spec=spec,
    )
    result.family = "forecasting_deep"
    result.spec.pop("strategy", None)
    return result


FORECASTING_DEEP = Family(
    key="forecasting_deep", tasks=("forecasting",), runtime="ml-deep",
    queue_setting="celery_ml_deep_queue", serving="remote",
    required_modules=("torch", "chronos", "skforecast"),
    harness=Path(__file__).resolve().parents[3] / "resources" / "ml_foundation_harness.py",
    spec_fields=SPEC_FIELDS,
    steps=("queued", "reading", "backtesting", "fitting", "saving"),
    exit_codes={2: "ML_TS_SERIES_UNUSABLE", 3: "ML_TS_HISTORY_TOO_SHORT"},
    validator=validate_foundation, serve_queue_setting="celery_ml_deep_serve_queue",
)
