"""Forecasting harness: one supervised subprocess per fit, in the ml-ts image.

Same contract as ``ml_train_harness`` (manifest in, ``result.json`` and an
MLflow model directory out, step names appended to the progress file, exit
codes 1–5), different science: the model is a skforecast forecaster, and it is
judged by **backtesting** — fitting once on the past and forecasting each of
the last ``folds`` horizons from the data before it — rather than by a random
split, which would let the model see the future it is scored on.

What a run produces
-------------------
* the forecaster, serialized by **skops** when its type allows it, otherwise
  by joblib (statsmodels-style estimators embed objects skops refuses); the
  result names which, with the file's sha256, so the loader can check it was
  not swapped;
* an MLflow pyfunc directory whose model is ``ml_forecast_pyfunc.py``, copied
  in ("models from code"), with a signature carrying ``horizon`` and
  ``interval_level`` as parameters;
* the evidence the model card reads: MAE, RMSE, MAPE, sMAPE, MASE, interval
  coverage and width on the backtest, the error per step of the horizon and
  per series, what repeating the last season would have scored, the backtest
  points and the tail of history to plot them against.

Intervals are conformal, and calibrated on errors the model made **without**
the future: each backtest fold is bracketed with the errors of the folds before
it, so the coverage reported is the one a user would have seen; the final model
carries every backtest error as its out-of-sample residuals, which is what
serving widens its forecasts with. Statistical models (ETS, ARIMA) keep their
own model-based intervals.

Gaps are not silently invented: with ``fill: refuse`` a missing step or value
exits 2, naming how many; ``interpolate`` and ``zero`` say what they filled.

Exit codes: 0 success · 1 the fit raised · 2 the series is unusable (gaps,
duplicates, frequency) · 3 too little history · 4 the artifact could not be
written · 5 harness/manifest error.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
from pathlib import Path

PYFUNC = Path(__file__).resolve().parent / "ml_forecast_pyfunc.py"
# Types a forecaster serialized by skops may reference. The regressor comes
# from the tabular catalog; anything else means the artifact is not what this
# harness built, and it is refused rather than trusted.
TRUSTED_MODULE_PREFIXES = (
    "sklearn.",
    "skforecast.",
    "numpy.",
    "scipy.",
    "pandas.",
    "builtins.",
    "collections.",
    "functools.",
)
# Keyed by the frequencies the spec offers. One table for the platform: the
# validator imports it, so a default the form promises is the one fitted.
SEASON = {"h": 24, "D": 7, "W": 52, "MS": 12, "QS": 4}
DEFAULT_LAGS = {
    "h": (1, 2, 3, 24, 168),
    "D": (1, 2, 7, 14, 28),
    "W": (1, 2, 4, 52),
    "MS": (1, 2, 3, 12),
    "QS": (1, 2, 4),
}
FALLBACK_LAGS = (1, 2, 3, 7)
FALLBACK_SEASON = 7
METRICS = [
    "mean_absolute_error",
    "mean_squared_error",
    "mean_absolute_percentage_error",
    "symmetric_mean_absolute_percentage_error",
    "mean_absolute_scaled_error",
]
SUMMARY_LEVELS = ("average", "weighted_average", "pooling")
# The read model is a card, not a warehouse: a few series plotted in full, the
# rest summarized per series.
_PLOTTED_SERIES = 3
_POINTS = 1200
_PER_SERIES = 200


# Calendar features skforecast derives (cyclical: ``hour_sin``, ``hour_cos``).
CALENDAR_PREFIXES = (
    "hour",
    "day_of_week",
    "day_of_month",
    "day_of_year",
    "week",
    "month",
    "quarter",
    "year",
    "is_weekend",
)
# Rows of the training matrix an explanation is measured on: enough for a
# stable mean |SHAP|, few enough that a large panel explains in seconds.
EXPLAIN_ROWS = 1000
# Exact tree SHAP is linear in the rows but grows with the trees' depth: a
# 200-tree forest grown to full depth on a large panel costs seconds per row.
# Past this budget the explanation switches to Saabas attributions (additive,
# approximate) and says so, rather than turning a fit into an hour.
EXPLAIN_BUDGET_S = 60.0
_EXPLAIN_PROBE_ROWS = 5
_TOP_FEATURES = 20
# The one-step diagnostic refits the regressor once more: on a large panel it
# keeps the most recent rows, so a slow forest does not pay a full third fit.
DIAGNOSTIC_ROWS = 50_000
_DIAGNOSTIC_HOLDOUT = 0.2
_CURVE_POINTS = 200


def feature_group(
    name: str, *, target: str, future=(), static=(), past=()
) -> tuple[str, int | None]:
    """Which family a model feature belongs to, and its lag when it is one.

    The families are what a reader can act on: the series' own recent past
    (``lags``), the calendar, covariates known in advance (``future``), the
    attributes of a series of a panel (``static``), which series it is
    (``series``), and other series moving with it (``past``, multivariate).
    A direct model suffixes per-step features (``hour_sin_step_3``); they
    belong to the same family as the unsuffixed one.
    """

    base = re.sub(r"_step_\d+$", "", name)
    if base == "_level_skforecast":
        return "series", None
    match = re.fullmatch(r"(?:(.+)_)?lag_(\d+)", base)
    if match:
        source = match.group(1)
        if source and source != target:
            return "past", int(match.group(2))
        return "lags", int(match.group(2))
    if base in static:
        return "static", None
    if base in future:
        return "future", None
    if base in past:
        return "past", None
    if base.startswith(CALENDAR_PREFIXES):
        return "calendar", None
    return "other", None


def _fail(code: int, message: str) -> int:
    print(message, file=sys.stderr, flush=True)
    return code


def _progress(path, step: str) -> None:
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{step}\n")
            handle.flush()
    except OSError:
        pass


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve_regressor(dotted: str, params: dict):
    import importlib

    if not dotted or not dotted.startswith("sklearn."):
        raise RuntimeError(f"estimator_not_allowed: {dotted}")
    module, _, name = dotted.rpartition(".")
    return getattr(importlib.import_module(module), name)(**params)


def _frequency(index, requested: str):
    import pandas as pd

    if requested and requested != "auto":
        return requested
    inferred = pd.infer_freq(index[: min(len(index), 500)])
    if inferred:
        return pd.tseries.frequencies.to_offset(inferred).freqstr
    deltas = index.to_series().diff().dropna()
    if deltas.empty:
        return None
    return pd.tseries.frequencies.to_offset(deltas.mode().iloc[0]).freqstr


def frequency_key(frequency: str | None) -> str | None:
    """The spec's name for a pandas frequency ('W-SUN' → 'W'), or None.

    Only a single-step frequency has a key: two-hourly data has a 12-step day,
    not the 24-step one hourly defaults assume.
    """

    if not frequency:
        return None
    if frequency[0].isdigit() and not frequency.startswith("1"):
        return None
    head = frequency.lstrip("1").split("-")[0]
    if head.lower() == "h":
        return "h"
    return {"D": "D", "B": "D", "W": "W", "MS": "MS", "ME": "MS", "M": "MS", "QS": "QS", "QE": "QS", "Q": "QS"}.get(
        head.upper()
    )


def _season(frequency: str) -> int:
    return SEASON.get(frequency_key(frequency) or "", FALLBACK_SEASON)


def default_lags(frequency: str | None, *, history: int, reserved: int) -> list[int]:
    """The frequency's lags that leave ``reserved`` steps of history to backtest."""

    lags = DEFAULT_LAGS.get(frequency_key(frequency) or "", FALLBACK_LAGS)
    return [lag for lag in lags if lag + reserved <= history] or [1]


def _calendar_features(frequency: str) -> list[str]:
    head = frequency.upper().lstrip("0123456789")
    if head.startswith("H"):
        return ["hour", "day_of_week"]
    if head.startswith(("W", "M", "Q")):
        return ["month"]
    return ["day_of_week", "month"]


def _regularize(frame, *, frequency: str, columns: list[str], fill: str):
    """Put a series on its frequency grid; refuse or fill the holes it reveals."""

    grid = frame.asfreq(frequency)
    holes = int(grid[columns].isna().any(axis=1).sum())
    if holes and fill == "refuse":
        raise ValueError(f"ml_ts_gaps: {holes} missing steps or values on the {frequency} grid")
    if holes and fill == "interpolate":
        grid[columns] = grid[columns].interpolate(limit_direction="both")
    elif holes and fill == "zero":
        grid[columns] = grid[columns].fillna(0.0)
    return grid, holes


def _long(frame):
    """A wide frame (one column per series) as a (timestamp, series) lookup."""

    value_column = "__forecast_value"
    while value_column in frame.columns:
        value_column += "_"
    melted = frame.melt(ignore_index=False, var_name="level", value_name=value_column)
    return melted.set_index("level", append=True)[value_column].rename("value")


def _conformal_quantile(errors, level: float):
    import numpy as np

    errors = np.asarray(errors, dtype=float)
    errors = errors[np.isfinite(errors)]
    if errors.size == 0:
        return None
    rank = min(1.0, math.ceil((errors.size + 1) * level) / errors.size)
    return float(np.quantile(errors, rank))


def analyse_series(values, *, season: int, lags: list[int]) -> dict:
    """The anatomy of one series, as a forecaster reads it before fitting.

    * STL (robust) — how much of the series is trend and how much is season,
      as strengths in [0, 1] (Hyndman: 1 − Var(R) / Var(component + R));
    * ACF at the lags the model uses and at multiples of the season, and the
      lags the PACF finds significant — the evidence a lag choice rests on;
    * ADF — whether the series wanders (a unit root) or returns to a level.

    Statistics computed from the history alone; nothing here sees the backtest.
    """

    import numpy as np
    from statsmodels.tsa.seasonal import STL
    from statsmodels.tsa.stattools import acf, adfuller, pacf

    series = values.dropna().astype(float)
    count = int(len(series))
    analysis: dict = {"points": count, "season": season}
    if count < 12 or float(series.std() or 0) == 0.0:
        return analysis
    wanted = sorted({lag for lag in lags if lag >= 1} | {season * k for k in (1, 2, 7) if season > 1})
    nlags = int(min(count // 3, max([*wanted, 2 * season, 24])))
    correlations = acf(series, nlags=nlags, fft=True)
    analysis["confidence"] = _number(1.96 / math.sqrt(count))
    analysis["acf"] = [
        {"lag": lag, "value": _number(correlations[lag])} for lag in wanted if lag <= nlags
    ]
    partial_lags = int(min(nlags, count // 2 - 1, 4 * max(season, 7)))
    if partial_lags >= 2:
        partial = pacf(series, nlags=partial_lags, method="ywm")
        confidence = 1.96 / math.sqrt(count)
        significant = [
            (lag, float(partial[lag])) for lag in range(1, partial_lags + 1) if abs(partial[lag]) > confidence
        ]
        significant.sort(key=lambda item: -abs(item[1]))
        analysis["suggested_lags"] = sorted(lag for lag, _ in significant[:6])
    if season >= 2 and count >= 2 * season + 1:
        decomposition = STL(series, period=season, robust=True).fit()
        residual = np.var(decomposition.resid)

        def strength(component) -> float:
            total = np.var(component + decomposition.resid)
            return float(max(0.0, 1.0 - residual / total)) if total > 0 else 0.0

        analysis["stl"] = {
            "period": season,
            "trend_strength": _number(strength(decomposition.trend)),
            "seasonal_strength": _number(strength(decomposition.seasonal)),
        }
    try:
        statistic, pvalue, *_ = adfuller(series, autolag="AIC")
        analysis["adf"] = {
            "statistic": _number(statistic),
            "pvalue": _number(pvalue),
            "stationary": bool(pvalue < 0.05),
        }
    except Exception:  # noqa: BLE001 - a degenerate series has no ADF to report
        pass
    return analysis


def _tabular_reader():
    """The tabular harness's skore readers, loaded by path (it is a sibling
    script that imports nothing at module scope), so one reading of a skore
    regression report — and one way of persisting it — serves both families."""

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "agentium_ml_train_harness", Path(__file__).resolve().with_name("ml_train_harness.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def diagnose_regressor(
    forecaster, *, inputs: dict, direct: bool, report_path=None, limit_bytes: int = 0
) -> tuple[dict, dict | None]:
    """The regressor alone, one step ahead, judged by skore on later rows.

    The backtest judges the whole forecast, recursion included. This judges
    the piece underneath: the regressor refitted on the oldest rows of the lag
    matrix and scored on the most recent ones, in time order — R², error, and
    predicted against actual. When the backtest is poor and this is good, the
    errors come from the recursion compounding; when both are poor, from the
    features. The report's own state is kept beside the model, as for a
    tabular fit, so the evaluation can be reopened.
    """

    import numpy as np
    from sklearn.base import clone
    from skore import EstimatorReport

    X, y = forecaster.create_train_X_y(**inputs)
    estimator = forecaster.estimator
    if direct:
        X, y = forecaster.filter_train_X_y_for_step(step=1, X_train=X, y_train=y, remove_suffix=True)
        estimator = forecaster.estimators_[1]
    order = np.argsort(np.asarray(X.index), kind="stable")
    X, y = X.iloc[order], y.iloc[order]
    if len(X) > DIAGNOSTIC_ROWS:
        X, y = X.iloc[-DIAGNOSTIC_ROWS:], y.iloc[-DIAGNOSTIC_ROWS:]
    cut = int(len(X) * (1 - _DIAGNOSTIC_HOLDOUT))
    model = clone(estimator).fit(X.iloc[:cut], y.iloc[:cut])
    report = EstimatorReport(model, X_test=X.iloc[cut:], y_test=y.iloc[cut:])
    reader = _tabular_reader()
    read = reader._regression_metrics(report, curve_points=_CURVE_POINTS)
    state = reader._persist_report(report, report_path, limit_bytes=limit_bytes) if report_path else None
    return (
        {
            "step": 1 if direct else None,
            "rows": {"train": int(cut), "test": int(len(X) - cut)},
            "scores": read["scores"],
            "curves": read["curves"],
        },
        state,
    )


def _explain_fit(forecaster, *, inputs: dict, direct: bool, groups_of) -> tuple[dict, dict]:
    """Mean |SHAP| per feature on the final model, by family and by lag.

    Measured on the training matrix skforecast builds (lags, calendar,
    covariates), so the families are the ones the model actually saw. A
    direct model has one estimator per step: the first step's is explained,
    which is the forecast an operator reads first. Linear models are
    explained exactly (coefficient × distance to the mean); trees with
    TreeExplainer; anything else by permutation.
    """

    import numpy as np

    X, y = forecaster.create_train_X_y(**inputs)
    estimator = forecaster.estimator
    if direct:
        X, y = forecaster.filter_train_X_y_for_step(step=1, X_train=X, y_train=y, remove_suffix=True)
        estimator = forecaster.estimators_[1]
    sample = X.sample(min(EXPLAIN_ROWS, len(X)), random_state=0) if len(X) > EXPLAIN_ROWS else X
    columns = [str(column) for column in X.columns]
    means = {column: float(value) for column, value in X.mean().items()}
    method = "shap"
    if hasattr(estimator, "coef_"):
        kind = "linear"
        coef = np.ravel(estimator.coef_)
        weights = np.abs(coef * (sample.to_numpy(dtype=float) - X.mean().to_numpy(dtype=float))).mean(axis=0)
    else:
        kind = "tree"
        try:
            import shap

            explainer = shap.TreeExplainer(estimator)
            probe = sample.iloc[:_EXPLAIN_PROBE_ROWS]
            started = time.monotonic()
            explainer.shap_values(probe)
            per_row = (time.monotonic() - started) / max(len(probe), 1)
            if per_row * len(sample) > EXPLAIN_BUDGET_S:
                values = explainer.shap_values(sample, approximate=True)
                method = "shap-approximate"
            else:
                values = explainer.shap_values(sample)
            weights = np.abs(np.asarray(values)).mean(axis=0)
        except Exception:  # noqa: BLE001 - shap absent or the model is not a tree
            from sklearn.inspection import permutation_importance

            ys = y.loc[sample.index] if hasattr(y, "loc") else y
            result = permutation_importance(estimator, sample, ys, n_repeats=3, random_state=0)
            weights = np.clip(result.importances_mean, 0, None)
            kind, method = "none", "permutation"
    total = float(np.sum(weights)) or 1.0
    features, shares, lags = [], {}, {}
    for column, weight in zip(columns, weights):
        group, lag = groups_of(column)
        value = float(weight)
        features.append({"feature": column, "group": group, "lag": lag, "value": _number(value)})
        shares[group] = shares.get(group, 0.0) + value / total
        if group == "lags" and lag is not None:
            lags[lag] = lags.get(lag, 0.0) + value
    features.sort(key=lambda item: -(item["value"] or 0))
    explanation = {
        "method": method,
        "step": 1 if direct else None,
        "groups": [
            {"group": group, "share": _number(share)} for group, share in sorted(shares.items(), key=lambda kv: -kv[1])
        ],
        "features": features[:_TOP_FEATURES],
        "lags": [{"lag": lag, "value": _number(value)} for lag, value in sorted(lags.items())],
        "rows": int(len(sample)),
    }
    explain_meta = {
        "kind": kind,
        "columns": columns,
        "groups": {column: groups_of(column)[0] for column in columns},
        "means": means if kind == "linear" else {},
    }
    return explanation, explain_meta


def main(argv: list[str]) -> int:  # noqa: C901 - one linear pipeline, read top down
    if len(argv) != 3:
        return _fail(5, "usage: ml_forecast_harness.py MANIFEST RESULT")
    try:
        manifest = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _fail(5, f"manifest_unreadable: {exc}")
    result_path = Path(argv[2])
    progress = manifest.get("progress_path")
    spec = dict(manifest.get("spec") or {})
    started = time.monotonic()

    try:
        import numpy as np
        import pandas as pd
        import skforecast  # noqa: F401
    except ImportError as exc:
        return _fail(5, f"runtime_missing: {exc}")

    target = str(manifest.get("target") or "")
    algo = str(manifest.get("algo") or "")
    time_column = spec.get("time_column")
    shape = spec.get("shape", "single")
    horizon = int(spec.get("horizon") or 0)
    folds = int(spec.get("backtest_folds") or 3)
    level = float(spec.get("interval_level") or 0.8)
    fill = spec.get("fill", "refuse")
    roles = dict(spec.get("exog") or {})
    future_cols = [column for column, role in roles.items() if role == "future"]
    static_cols = [column for column, role in roles.items() if role == "static"]
    past_cols = [column for column, role in roles.items() if role == "past"]
    series_cols = list(spec.get("series_columns") or [])
    asked_lags = sorted({int(lag) for lag in (spec.get("lags") or [])})
    if not target or not time_column or horizon < 1:
        return _fail(5, "manifest_incomplete: target, time_column and horizon are required")

    _progress(progress, "reading")
    try:
        frame = pd.read_parquet(manifest["data_path"])
    except Exception as exc:  # noqa: BLE001
        return _fail(5, f"data_unreadable: {exc}")
    frame[time_column] = pd.to_datetime(frame[time_column], errors="coerce")
    frame = frame.dropna(subset=[time_column]).sort_values(time_column)
    total_rows = int(len(frame))

    # ---- shape the data -------------------------------------------------
    series_map: dict = {}
    exog_map: dict = {}
    static_values: dict = {}
    static_codes: dict = {}
    exog = None
    series_frame = None
    try:
        if shape == "panel":
            frame["_series"] = frame[series_cols].astype(str).agg(" · ".join, axis=1)
            if frame.duplicated(["_series", time_column]).any():
                return _fail(2, "ml_ts_duplicates: a series repeats a date")
            first = frame[frame["_series"] == frame["_series"].iloc[0]]
            frequency = _frequency(pd.DatetimeIndex(first[time_column]), spec.get("frequency", "auto"))
            if not frequency:
                return _fail(2, "ml_ts_frequency: the dates follow no regular step")
            # A static covariate is coded once, over the whole panel, so the
            # same region is the same number in every series.
            for column in static_cols:
                if frame.groupby("_series")[column].nunique(dropna=True).gt(1).any():
                    return _fail(2, f"ml_ts_static_varies: '{column}' changes within a series, so it is not static")
                if not pd.api.types.is_numeric_dtype(frame[column]):
                    labels = sorted(frame[column].dropna().astype(str).unique())
                    static_codes[column] = {label: float(code) for code, label in enumerate(labels)}
                    frame[column] = frame[column].astype(str).map(static_codes[column])
            holes = 0
            for name, rows in frame.groupby("_series"):
                grid, missing = _regularize(
                    rows.set_index(time_column)[[target, *future_cols]],
                    frequency=frequency,
                    columns=[target, *future_cols],
                    fill=fill,
                )
                holes += missing
                key = str(name)
                series_map[key] = grid[target].astype(float)
                static_values[key] = {
                    column: _number(rows[column].dropna().iloc[0]) if rows[column].notna().any() else None
                    for column in static_cols
                }
                if future_cols or static_cols:
                    columns = grid[future_cols].astype(float)
                    for column in static_cols:
                        columns[column] = static_values[key][column]
                    exog_map[key] = columns.astype(float)
            truth = pd.DataFrame(series_map)
            history = min(int(series.notna().sum()) for series in series_map.values())
            last_timestamp = truth.index[-1]
        else:
            if frame.duplicated([time_column]).any():
                return _fail(2, "ml_ts_duplicates: the time column repeats a date")
            indexed = frame.set_index(time_column)
            frequency = _frequency(indexed.index, spec.get("frequency", "auto"))
            if not frequency:
                return _fail(2, "ml_ts_frequency: the dates follow no regular step")
            grid, holes = _regularize(
                indexed[[target, *past_cols, *future_cols]],
                frequency=frequency,
                columns=[target, *past_cols, *future_cols],
                fill=fill,
            )
            y = grid[target].astype(float)
            exog = grid[future_cols].astype(float) if future_cols else None
            if shape == "multivariate":
                series_frame = grid[[target, *past_cols]].astype(float)
            truth = y.to_frame(target)
            history = len(y)
            last_timestamp = y.index[-1]
    except ValueError as exc:
        return _fail(2, str(exc))

    season = _season(frequency)
    reserved = max(2, folds + 1) * horizon
    # Lags the author did not choose follow the frequency the data turned out
    # to have, trimmed to what the history can feed.
    lags = asked_lags or default_lags(frequency, history=history, reserved=reserved)
    needed = reserved + max(lags)
    if history < needed:
        return _fail(3, f"ml_ts_history: {history} steps, {needed} needed for this horizon, lags and folds")

    # ---- the forecaster -------------------------------------------------
    from skforecast.direct import ForecasterDirect, ForecasterDirectMultiVariate
    from skforecast.model_selection import (
        TimeSeriesFold,
        backtesting_forecaster,
        backtesting_forecaster_multiseries,
        backtesting_stats,
    )
    from skforecast.preprocessing import CalendarFeatures
    from skforecast.recursive import (
        ForecasterEquivalentDate,
        ForecasterRecursive,
        ForecasterRecursiveMultiSeries,
        ForecasterStats,
    )

    calendar = CalendarFeatures(features=_calendar_features(frequency)) if spec.get("calendar", True) else None

    def build():
        if algo == "seasonal_naive":
            return ForecasterEquivalentDate(offset=season, n_offsets=1), "naive"
        if algo in ("ets", "arima"):
            from skforecast.stats import Arima, Ets

            estimator = Ets(m=season) if algo == "ets" else Arima(order=(1, 1, 1), seasonal_order=(0, 1, 1), m=season)
            return ForecasterStats(estimator=estimator), "stats"
        regressor = _resolve_regressor(manifest.get("estimator"), dict(manifest.get("params") or {}))
        if shape == "panel":
            built = ForecasterRecursiveMultiSeries(
                estimator=regressor, lags=lags, calendar_features=calendar, encoding="ordinal"
            )
        elif shape == "multivariate":
            built = ForecasterDirectMultiVariate(
                estimator=regressor, level=target, steps=horizon, lags=lags, calendar_features=calendar
            )
        elif spec.get("strategy") == "direct":
            built = ForecasterDirect(estimator=regressor, steps=horizon, lags=lags, calendar_features=calendar)
        else:
            built = ForecasterRecursive(estimator=regressor, lags=lags, calendar_features=calendar)
        return built, "regression"

    try:
        forecaster, kind = build()
    except RuntimeError as exc:
        return _fail(5, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _fail(1, f"ml_fit_failed: {type(exc).__name__}: {exc}")

    # ---- backtest -------------------------------------------------------
    _progress(progress, f"backtesting:0/{folds}")
    span = len(truth)
    lower = upper = None
    try:
        cv = TimeSeriesFold(steps=horizon, initial_train_size=span - folds * horizon, refit=kind == "stats")
        # skforecast parallelizes a backtest with joblib workers by default; each
        # one copies the data, and the worker grants a fit a fixed thread budget
        # (OMP_NUM_THREADS) under a memory ceiling. One budget for both.
        jobs = max(1, int(os.environ.get("OMP_NUM_THREADS") or 1))
        common = {"cv": cv, "metric": METRICS, "show_progress": False, "n_jobs": jobs}
        if shape == "panel":
            table, predictions = backtesting_forecaster_multiseries(
                forecaster, series=series_map, exog=exog_map or None, **common
            )
        elif shape == "multivariate":
            table, predictions = backtesting_forecaster_multiseries(
                forecaster, series=series_frame, exog=exog, **common
            )
        elif kind == "stats":
            table, predictions = backtesting_stats(
                forecaster, y=y, exog=exog, interval=[(1 - level) / 2, (1 + level) / 2], **common
            )
            lower = next((c for c in predictions.columns if "lower" in c), None)
            upper = next((c for c in predictions.columns if "upper" in c), None)
        else:
            table, predictions = backtesting_forecaster(forecaster, y=y, exog=exog, **common)
    except Exception as exc:  # noqa: BLE001
        return _fail(1, f"ml_fit_failed: backtest: {type(exc).__name__}: {exc}")
    _progress(progress, f"backtesting:{folds}/{folds}")

    points = predictions.copy()
    if "level" not in points.columns:
        points["level"] = target
    points["level"] = points["level"].astype(str)
    points = points[points["level"].isin([str(column) for column in truth.columns])]
    points["actual"] = _long(truth).reindex(pd.MultiIndex.from_arrays([points.index, points["level"]])).to_numpy()
    if "fold" not in points.columns:
        points["fold"] = points.groupby("level").cumcount() // horizon
    points["step"] = points.groupby(["level", "fold"]).cumcount() + 1
    points["lower"] = points[lower] if lower else np.nan
    points["upper"] = points[upper] if upper else np.nan
    residual = (points["actual"] - points["pred"]).abs()
    if kind != "stats":
        # Fold k is bracketed with the errors of folds 0..k-1 of its own
        # series: the interval a user would have had at that origin.
        for name, rows in points.groupby("level"):
            for fold in sorted(rows["fold"].unique())[1:]:
                earlier = residual[(points["level"] == name) & (points["fold"] < fold)]
                width = _conformal_quantile(earlier, level)
                if width is None:
                    continue
                mask = (points["level"] == name) & (points["fold"] == fold)
                points.loc[mask, "lower"] = points.loc[mask, "pred"] - width
                points.loc[mask, "upper"] = points.loc[mask, "pred"] + width
    bracketed = points.dropna(subset=["lower", "upper", "actual"])
    inside = (bracketed["actual"] >= bracketed["lower"]) & (bracketed["actual"] <= bracketed["upper"])
    covered = inside.mean() if len(bracketed) else None
    width = (bracketed["upper"] - bracketed["lower"]).mean() if len(bracketed) else None

    if "levels" in table.columns:
        overall = table[table["levels"].isin(SUMMARY_LEVELS[:2])].head(1)
        overall = overall.drop(columns=["levels"]) if len(overall) else table.drop(columns=["levels"]).mean().to_frame().T
        per_level = table[~table["levels"].isin(SUMMARY_LEVELS)]
    else:
        overall, per_level = table, None
    raw = {key: _number(value) for key, value in (overall.iloc[0].to_dict() if len(overall) else {}).items()}
    mse = raw.get("mean_squared_error")
    mape = raw.get("mean_absolute_percentage_error")
    scores = {
        "mae": raw.get("mean_absolute_error"),
        "rmse": math.sqrt(mse) if mse is not None else None,
        "mape": mape * 100 if mape is not None else None,
        "smape": raw.get("symmetric_mean_absolute_percentage_error"),
        "mase": raw.get("mean_absolute_scaled_error"),
        "coverage": _number(covered),
        "interval_width": _number(width),
    }

    # What repeating the last season would have scored on the same folds. A
    # step beyond one season repeats the last season it could have seen, never
    # one inside the horizon it is forecasting.
    naive_mae = None
    if algo != "seasonal_naive":
        lag_steps = (season * np.ceil(points["step"].to_numpy() / season)).astype(int)
        errors = []
        for lag in np.unique(lag_steps):
            mask = lag_steps == lag
            reference = _long(truth.shift(int(lag))).reindex(
                pd.MultiIndex.from_arrays([points.index[mask], points["level"].to_numpy()[mask]])
            )
            errors.append(np.abs(points["actual"].to_numpy()[mask] - reference.to_numpy()))
        errors = np.concatenate(errors) if errors else np.array([])
        errors = errors[np.isfinite(errors)]
        naive_mae = _number(errors.mean()) if errors.size else None

    # ---- final fit on everything ------------------------------------------
    _progress(progress, f"fitting:{span}")
    try:
        if shape == "panel":
            forecaster.fit(series=series_map, exog=exog_map or None, store_in_sample_residuals=True)
        elif shape == "multivariate":
            forecaster.fit(series=series_frame, exog=exog, store_in_sample_residuals=True)
        elif kind == "stats":
            forecaster.fit(y=y, exog=exog)
        elif kind == "naive":
            forecaster.fit(y=y, store_in_sample_residuals=True)
        else:
            forecaster.fit(y=y, exog=exog, store_in_sample_residuals=True)
        if kind != "stats":
            # fit() forgets out-of-sample residuals, so they are set after it:
            # every backtest error, made without the future, widens a forecast.
            scored = points.dropna(subset=["actual", "pred"])
            if shape in ("panel", "multivariate"):
                y_true = {name: rows["actual"].to_numpy() for name, rows in scored.groupby("level")}
                y_pred = {name: rows["pred"].to_numpy() for name, rows in scored.groupby("level")}
            else:
                y_true, y_pred = scored["actual"].to_numpy(), scored["pred"].to_numpy()
            forecaster.set_out_sample_residuals(y_true=y_true, y_pred=y_pred)
    except Exception as exc:  # noqa: BLE001
        return _fail(1, f"ml_fit_failed: {type(exc).__name__}: {exc}")

    # ---- what the forecast leans on --------------------------------------
    explanation: dict = {}
    explain_meta: dict = {"kind": "none"}
    importances: list = []
    groups_of = lambda name: feature_group(  # noqa: E731
        name, target=target, future=future_cols, static=static_cols, past=past_cols
    )
    if kind == "regression":
        try:
            explanation, explain_meta = _explain_fit(
                forecaster,
                inputs=(
                    {"series": series_map, "exog": exog_map or None}
                    if shape == "panel"
                    else {"series": series_frame, "exog": exog}
                    if shape == "multivariate"
                    else {"y": y, "exog": exog}
                ),
                direct=isinstance(forecaster, (ForecasterDirect, ForecasterDirectMultiVariate)),
                groups_of=groups_of,
            )
            importances = [
                {"feature": item["feature"], "value": item["value"]} for item in explanation.get("features", [])
            ]
        except Exception as exc:  # noqa: BLE001 - an explanation is evidence, not the fit
            explanation = {"method": "unavailable", "reason": f"{type(exc).__name__}: {exc}"[:200]}
    elif kind == "stats":
        try:
            estimator = forecaster.estimators[0]
            params = forecaster.get_feature_importances()
            explanation = {
                "method": "model",
                "name": str(getattr(estimator, "estimator_name_", "") or algo.upper()),
                "aic": _number(getattr(estimator, "aic_", None)),
                "parameters": [
                    {"name": str(row["feature"]), "value": _number(row["importance"])}
                    for _, row in params.head(12).iterrows()
                ],
            }
        except Exception:  # noqa: BLE001
            explanation = {"method": "model", "name": algo.upper(), "parameters": []}
    else:
        explanation = {"method": "naive", "season": season}

    # ---- the regressor alone, one step ahead (skore) --------------------------
    diagnostic, report_state = None, None
    if kind == "regression":
        try:
            diagnostic, report_state = diagnose_regressor(
                forecaster,
                inputs=(
                    {"series": series_map, "exog": exog_map or None}
                    if shape == "panel"
                    else {"series": series_frame, "exog": exog}
                    if shape == "multivariate"
                    else {"y": y, "exog": exog}
                ),
                direct=isinstance(forecaster, (ForecasterDirect, ForecasterDirectMultiVariate)),
                report_path=manifest.get("report_path"),
                limit_bytes=int(float(manifest.get("report_state_limit_mb") or 0) * 1024 * 1024),
            )
        except Exception as exc:  # noqa: BLE001 - a diagnostic is evidence, not the fit
            print(f"ml_forecast_diagnostic_skipped: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

    # ---- the anatomy of the series it was fitted on -------------------------
    plotted_names = [name for name in (sorted(series_map) if shape == "panel" else [target])][:_PLOTTED_SERIES]
    analyses = []
    for name in plotted_names:
        try:
            analysis = analyse_series(truth[name], season=season, lags=lags)
        except Exception as exc:  # noqa: BLE001 - analysis is evidence, not the fit
            analysis = {"error": f"{type(exc).__name__}"}
        analyses.append({"series": str(name), **analysis})

    # ---- where the actuals left the interval ---------------------------------
    outside = bracketed[~inside] if len(bracketed) else bracketed
    excursions = []
    for stamp, row in outside.iterrows():
        above = row["actual"] > row["upper"]
        excursions.append(
            {
                "t": str(stamp),
                "series": str(row["level"]),
                "step": int(row["step"]),
                "actual": _number(row["actual"]),
                "lower": _number(row["lower"]),
                "upper": _number(row["upper"]),
                "side": "above" if above else "below",
                "gap": _number(row["actual"] - row["upper"] if above else row["lower"] - row["actual"]),
            }
        )
    excursions.sort(key=lambda item: -(item["gap"] or 0))

    # ---- persist ----------------------------------------------------------
    _progress(progress, "saving")
    from skforecast.utils import save_forecaster

    model_dir = Path(manifest["model_dir"])
    work = model_dir.parent / "forecast-artifacts"
    work.mkdir(parents=True, exist_ok=True)
    serialization, trusted = "skops", []
    artifact = work / "forecaster.skops"
    try:
        save_forecaster(forecaster, str(artifact), backend="skops", verbose=False)
        import skops.io as sio

        trusted = list(sio.get_untrusted_types(file=str(artifact)))
        rogue = [name for name in trusted if not name.startswith(TRUSTED_MODULE_PREFIXES)]
        if rogue:
            return _fail(4, f"ml_artifact_unwritable: untrusted types {rogue[:5]}")
    except (NotImplementedError, TypeError):
        # Objects skops will not describe; joblib it is, trusted by hash and
        # only ever loaded in the ml-ts image.
        serialization, trusted = "joblib", []
        artifact.unlink(missing_ok=True)
        artifact = work / "forecaster.joblib"
        save_forecaster(forecaster, str(artifact), backend="joblib", verbose=False)
    levels = sorted(series_map) if shape == "panel" else [target]
    direct = kind == "regression" and (shape == "multivariate" or spec.get("strategy") == "direct")
    meta = {
        "serialization": serialization,
        "trusted": trusted,
        "kind": kind,
        "shape": shape,
        "target": target,
        "levels": levels,
        "frequency": frequency,
        "last_timestamp": str(last_timestamp),
        "horizon": horizon,
        "max_steps": horizon if direct else None,
        "interval_level": level,
        "residuals": "in_model" if kind == "stats" else "out_sample",
        "exog_future": future_cols,
        "exog_static": static_cols,
        "static_values": static_values,
        # How serving explains one forecast: which explainer, which family each
        # feature belongs to, and (linear) the means contributions are taken from.
        "explain": explain_meta,
    }
    (work / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    import mlflow.pyfunc
    from mlflow.models import ModelSignature
    from mlflow.types import ColSpec, ParamSchema, ParamSpec, Schema

    inputs = [ColSpec("string", "series", required=False), ColSpec("string", "timestamp", required=False)]
    inputs += [ColSpec("double", column, required=False) for column in future_cols]
    signature = ModelSignature(
        inputs=Schema(inputs),
        outputs=Schema(
            [
                ColSpec("string", "series"),
                ColSpec("string", "timestamp"),
                ColSpec("double", "pred"),
                ColSpec("double", "lower_bound"),
                ColSpec("double", "upper_bound"),
            ]
        ),
        params=ParamSchema([ParamSpec("horizon", "long", horizon), ParamSpec("interval_level", "double", level)]),
    )
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as package_version

    requirements = []
    for name in ("skforecast", "scikit-learn", "pandas", "numpy", "scipy", "skops", "mlflow"):
        try:
            requirements.append(f"{name}=={package_version(name)}")
        except PackageNotFoundError:
            continue
    try:
        if model_dir.exists():
            shutil.rmtree(model_dir)
        mlflow.pyfunc.save_model(
            path=str(model_dir),
            python_model=str(PYFUNC),
            artifacts={"forecaster": str(artifact), "meta": str(work / "meta.json")},
            signature=signature,
            pip_requirements=requirements,
        )
        artifact_sha = _sha256(model_dir / "artifacts" / artifact.name)
    except Exception as exc:  # noqa: BLE001
        return _fail(4, f"ml_artifact_unwritable: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # ---- the read model ---------------------------------------------------
    per_series = []
    if per_level is not None and shape == "panel":
        for _, row in per_level.iterrows():
            per_series.append(
                {
                    "series": str(row["levels"]),
                    "mae": _number(row.get("mean_absolute_error")),
                    "mase": _number(row.get("mean_absolute_scaled_error")),
                    "smape": _number(row.get("symmetric_mean_absolute_percentage_error")),
                }
            )
        per_series.sort(key=lambda item: -(item["mase"] if item["mase"] is not None else -1))
    plotted = [name for name in levels if name in set(points["level"])][:_PLOTTED_SERIES]
    # Each plotted series keeps its own most recent folds, so a long panel
    # horizon cannot push the first series off the chart.
    share = max(_POINTS // max(len(plotted), 1), horizon)
    sample = points[points["level"].isin(plotted)].groupby("level", group_keys=False).tail(share)
    backtest = [
        {
            "t": str(stamp),
            "series": str(row["level"]),
            "fold": int(row["fold"]),
            "step": int(row["step"]),
            "actual": _number(row["actual"]),
            "pred": _number(row["pred"]),
            "lower": _number(row["lower"]),
            "upper": _number(row["upper"]),
        }
        for stamp, row in sample.iterrows()
    ]
    per_step = points.assign(
        error=residual,
        inside=((points["actual"] >= points["lower"]) & (points["actual"] <= points["upper"])).where(
            points["lower"].notna()
        ),
    )
    per_horizon = [
        {"step": int(step), "mae": _number(rows["error"].mean()), "coverage": _number(rows["inside"].dropna().mean())}
        for step, rows in per_step.groupby("step")
    ]
    # The context the backtest starts from: what the series did just before the
    # first fold, so the chart shows where each forecast came from.
    history_tail = []
    for name in plotted:
        first = sample.index[sample["level"] == name].min()
        series = truth[name].dropna()
        before = series[series.index < first].tail(min(2 * horizon, _POINTS // 3))
        history_tail += [{"t": str(stamp), "series": name, "value": _number(value)} for stamp, value in before.items()]
    scored = {key: value for key, value in scores.items() if value is not None}
    primary_key = "mase" if scored.get("mase") is not None else "mae"
    metrics = {
        "task": "forecasting",
        "primary": {"key": primary_key, "value": scored.get(primary_key)},
        "scores": [{"key": key, "value": value} for key, value in scored.items()],
        "rows": {"total": total_rows, "history": int(history), "backtest": int(len(points))},
        "columns": {"used": [time_column, target, *series_cols, *roles], "dropped": []},
        "forecast": {
            "shape": shape,
            "algo": algo,
            "strategy": "direct" if direct else ("recursive" if kind == "regression" else kind),
            "frequency": frequency,
            "season": season,
            "horizon": horizon,
            "folds": folds,
            "interval_level": level,
            "interval_method": "model" if kind == "stats" else "conformal",
            "lags": lags if kind == "regression" else [],
            "calendar": _calendar_features(frequency) if calendar is not None and kind == "regression" else [],
            "series_count": len(levels),
            "filled_steps": int(holes),
            "fill": fill,
            "last_timestamp": str(last_timestamp),
            "serialization": serialization,
        },
        "baseline": {"key": "seasonal_naive", "season": season, "mae": naive_mae},
        "per_horizon": per_horizon,
        "per_series": per_series[:_PER_SERIES],
        "backtest": backtest,
        "history_tail": history_tail,
        "importances": importances,
        "explanation": explanation,
        "diagnostic": diagnostic,
        "analysis": analyses,
        "excursions": {
            "count": len(excursions),
            "share": _number(len(excursions) / len(bracketed)) if len(bracketed) else None,
            "points": excursions[:20],
        },
        "static_codes": static_codes,
        "target": {"name": target},
    }
    summary = {
        "metrics": metrics,
        "signature": {
            "inputs": [{"name": column, "type": "double", "kind": "number", "role": "future"} for column in future_cols],
            "output": {"task": "forecasting", "target": target, "levels": levels[:_PER_SERIES], "horizon": horizon},
        },
        "input_example": [],
        "classes": [],
        "artifact": {"serialization": serialization, "sha256": artifact_sha, "code_sha256": _sha256(PYFUNC)},
        # The skore report's own state, uploaded by the worker like a tabular one.
        "report_state": report_state,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
    }
    result_path.write_text(json.dumps(summary, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
