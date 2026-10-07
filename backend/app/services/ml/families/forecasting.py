"""The forecasting family: skforecast, trained and served by the ml-ts image.

A forecast is a regression on the series' own past (lags, calendar) plus
covariates, fitted by an estimator from the tabular catalog — or a statistical
model per series — and judged by backtesting rather than a random split.
Three shapes:

* ``single`` — one series (``ForecasterRecursive`` or ``ForecasterDirect``);
* ``panel`` — many series of the same quantity, one global model
  (``ForecasterRecursiveMultiSeries``), the series named by ``series_columns``;
* ``multivariate`` — one target forecast from other series that move with it
  (``ForecasterDirectMultiVariate``), those series marked ``past`` in ``exog``.

Covariates carry a role: ``future`` (known over the horizon: calendar, promo,
planned capacity), ``static`` (an attribute of the series) or ``past`` (only
known up to now, so usable only as a lagged series — the multivariate shape).

Validation reads the dataset profile only; the harness checks what only the
data can tell (gaps, frequency, length per series).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.ml.families.base import Family, SpecField

FORECASTING = "forecasting"
SHAPES = ("single", "panel", "multivariate")
STRATEGIES = ("recursive", "direct")
FREQUENCIES = ("auto", "h", "D", "W", "MS", "QS")
ROLES = ("future", "static", "past")
# Algorithms that fit one statistical model per series rather than a regressor
# on lags: no strategy, no panel, no lagged covariates.
STATISTICAL_ALGOS = frozenset({"ets", "arima"})
NAIVE_ALGO = "seasonal_naive"

SPEC_FIELDS = (
    SpecField("time_column", "column", required=True, column_kinds=("datetime",)),
    SpecField("shape", "enum", default="single", choices=SHAPES),
    SpecField("series_columns", "columns", required=True, max_items=3, when=(("shape", ("panel",)),)),
    SpecField("horizon", "int", required=True, minimum=1, maximum=float(settings.ml_ts_max_horizon)),
    SpecField("frequency", "enum", default="auto", choices=FREQUENCIES),
    SpecField("strategy", "enum", default="recursive", choices=STRATEGIES),
    SpecField("lags", "int_list", minimum=1, maximum=float(settings.ml_ts_max_lag), max_items=24),
    SpecField("exog", "column_roles", choices=ROLES, max_items=16),
    SpecField("calendar", "bool", default=True),
    SpecField("interval_level", "float", default=0.8, minimum=0.5, maximum=0.99),
    SpecField("backtest_folds", "int", default=3, minimum=1, maximum=8),
    SpecField("fill", "enum", default="refuse", choices=("refuse", "interpolate", "zero")),
)


def _refuse(code: str, message: str, **details: Any):
    from app.services.tabular_datasets import TabularError

    return TabularError(code=code, message=message, details=details or None)


def _distinct(dataset: Any, column: str) -> int:
    stats = (dataset.stats_json or {}).get(column) or {}
    try:
        return int(stats.get("distinct") or 0)
    except (TypeError, ValueError):
        return 0


def validate_forecast(
    dataset: Any,
    *,
    task: str,
    target: str,
    features: Any,
    algo: Any,
    knobs: Any,
    test_size: Any,
    cross_validation: Any,
    name: Any,
    spec: dict[str, Any],
):
    """A forecasting request, checked against the dataset profile."""

    from app.services.tabular_datasets import NUMERIC_KINDS
    from app.services.tabular_ml import ALGO_BY_KEY, TrainingSpec

    kinds = {
        str(column.get("name")): str(column.get("kind") or "other")
        for column in (dataset.schema_json or [])
        if column.get("name")
    }
    time_column = spec["time_column"]
    if time_column not in kinds:
        raise _refuse("ML_TS_TIME_COLUMN_REQUIRED", f"'{time_column}' is not a column of this dataset.", field="time_column")
    if kinds[time_column] != "datetime":
        raise _refuse(
            "ML_TS_TIME_COLUMN_NOT_DATETIME",
            f"'{time_column}' is not a date column.",
            field="time_column",
            kind=kinds[time_column],
        )
    if kinds.get(target) not in NUMERIC_KINDS:
        raise _refuse("ML_TARGET_NOT_NUMERIC", f"'{target}' is not numeric, so it cannot be forecast.", target=target)

    shape = spec.get("shape", "single")
    series_columns = list(spec.get("series_columns") or []) if shape == "panel" else []
    roles: dict[str, str] = dict(spec.get("exog") or {})
    for column in [*series_columns, *roles]:
        if column not in kinds:
            raise _refuse("ML_FEATURE_UNKNOWN", f"'{column}' is not a column of this dataset.", features=[column])
        if column in (target, time_column):
            raise _refuse("ML_TS_COLUMN_REUSED", f"'{column}' is already the target or the time column.", field=column)
    for column, role in roles.items():
        if role != "static" and kinds[column] not in (*NUMERIC_KINDS, "boolean"):
            raise _refuse("ML_TS_EXOG_NOT_NUMERIC", f"'{column}' must be numeric to be a covariate.", field=column)
        if role == "past" and shape != "multivariate":
            raise _refuse(
                "ML_TS_PAST_NEEDS_MULTIVARIATE",
                f"'{column}' is only known up to now: use the multivariate shape to forecast from it.",
                field=column,
            )
        if role == "static" and shape != "panel":
            raise _refuse("ML_TS_STATIC_NEEDS_PANEL", f"'{column}' is static: it describes a series of a panel.", field=column)
    if shape == "multivariate" and not any(role == "past" for role in roles.values()):
        raise _refuse(
            "ML_TS_MULTIVARIATE_NEEDS_SERIES",
            "A multivariate forecast needs at least one other series marked as known up to now.",
            field="exog",
        )

    rows = int(dataset.row_count or 0)
    timestamps = _distinct(dataset, time_column) or rows
    if shape != "panel" and timestamps < rows:
        raise _refuse(
            "ML_TS_DUPLICATE_TIMESTAMPS",
            f"'{time_column}' repeats ({rows:,} rows, {timestamps:,} dates): name the series columns of the panel.",
            field="series_columns",
        )
    if shape == "panel":
        series = max((_distinct(dataset, column) for column in series_columns), default=0)
        if series > int(settings.ml_ts_max_series):
            raise _refuse(
                "ML_TS_TOO_MANY_SERIES",
                f"{series:,} series, above the {int(settings.ml_ts_max_series)} a panel model is offered for.",
                series=series,
            )

    algo_key = str(algo or "").strip() or "gradient_boosting"
    resolved = ALGO_BY_KEY.get(algo_key)
    if resolved is None:
        raise _refuse("ML_ALGO_UNKNOWN", f"'{algo_key}' is not an offered algorithm.", algos=sorted(ALGO_BY_KEY))
    if not resolved.supports(FORECASTING):
        raise _refuse("ML_ALGO_TASK_MISMATCH", f"'{algo_key}' does not forecast.", algo=algo_key, task=FORECASTING)
    strategy = spec.get("strategy", "recursive")
    if shape == "multivariate":
        strategy = "direct"
    if algo_key in STATISTICAL_ALGOS | {NAIVE_ALGO} and shape != "single":
        raise _refuse(
            "ML_TS_ALGO_SHAPE_MISMATCH",
            f"'{algo_key}' fits one series at a time: choose a regressor for a {shape} forecast.",
            algo=algo_key,
            shape=shape,
        )
    if shape == "panel" and strategy == "direct":
        strategy = "recursive"

    horizon = int(spec["horizon"])
    folds = int(spec.get("backtest_folds") or cross_validation or 3)
    # Lags left to the harness follow the frequency it finds, trimmed to the
    # history; only lags the author chose are held against the history here.
    lags = list(spec.get("lags") or [])
    needed = max(2, folds + 1) * horizon + max(lags or [1])
    if timestamps < needed:
        raise _refuse(
            "ML_TS_HISTORY_TOO_SHORT",
            f"{timestamps:,} dates of history; a {horizon}-step forecast backtested {folds} times with lags up to "
            f"{max(lags or [1])} needs at least {needed:,}.",
            field="horizon",
            history=timestamps,
            needed=needed,
        )
    if rows < int(settings.ml_train_min_rows):
        raise _refuse("ML_ROWS_INSUFFICIENT", f"The dataset has {rows:,} rows.", rows=rows)
    if rows > int(settings.ml_train_max_rows):
        raise _refuse("ML_ROWS_TOO_MANY", f"The dataset has {rows:,} rows.", rows=rows)

    problem = {**spec, "shape": shape, "strategy": strategy, "backtest_folds": folds}
    if lags:
        problem["lags"] = lags
    else:
        problem.pop("lags", None)
    if shape != "panel":
        problem.pop("series_columns", None)
    default_name = f"{dataset.name} · {target} +{horizon}"
    return TrainingSpec(
        dataset=dataset,
        task=FORECASTING,
        target=target,
        features=list(roles),
        algo=resolved,
        knobs=resolved.resolve(knobs),
        test_size=round(min(0.5, horizon * folds / max(timestamps, 1)), 4),
        cross_validation=folds,
        name=(str(name or "").strip() or default_name)[:200],
        warnings=[],
        family=FORECASTING,
        spec=problem,
    )


FORECASTING_FAMILY = Family(
    key=FORECASTING,
    tasks=(FORECASTING,),
    runtime="ml-ts",
    queue_setting="celery_ml_ts_queue",
    serving="remote",
    required_modules=("skforecast", "statsmodels"),
    harness=Path(__file__).resolve().parents[3] / "resources" / "ml_forecast_harness.py",
    spec_fields=SPEC_FIELDS,
    steps=("queued", "reading", "fitting", "backtesting", "saving"),
    exit_codes={2: "ML_TS_SERIES_UNUSABLE", 3: "ML_TS_HISTORY_TOO_SHORT"},
    validator=validate_forecast,
    serve_queue_setting="celery_ml_ts_serve_queue",
)
