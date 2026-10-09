"""Zero-shot forecasting with local frozen weights and expanding backtests.

The final horizons are never part of their forecast's context. No optimizer or
weight update is used. MLflow exports contain JSON context and safetensors,
with every file fingerprinted before the serving process can execute code.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from importlib.metadata import version
from pathlib import Path

# These helpers contain no application imports and use the same frequency and
# gap policy as the ordinary forecasting runtime.
if __package__:
    from .ml_forecast_harness import _fail, _frequency, _number, _progress, _regularize, _season, _sha256
    from .ml_foundation_pyfunc import build_forecaster
else:
    from ml_forecast_harness import _fail, _frequency, _number, _progress, _regularize, _season, _sha256
    from ml_foundation_pyfunc import build_forecaster

PYFUNC = Path(__file__).with_name("ml_foundation_pyfunc.py")
CONTEXT_LENGTH = 512
MAX_HORIZON = 64
MAX_SERIES = 32
WEIGHT_FILES = ("config.json", "model.safetensors")


def read_series(frame, spec, target):
    import numpy as np
    import pandas as pd

    time_column = spec["time_column"]
    frame = frame.copy()
    stamps = pd.to_datetime(frame[time_column], errors="coerce", utc=True)
    if stamps.isna().any():
        raise ValueError("ml_ts_dates: the history contains invalid dates")
    frame[time_column] = stamps.dt.tz_localize(None).astype("datetime64[ns]")
    series_columns = list(spec.get("series_columns") or []) if spec.get("shape") == "panel" else []
    if series_columns:
        if frame[series_columns].isna().any().any():
            raise ValueError("ml_ts_series: missing series identifiers")
        tuples = frame[series_columns].astype(str).agg(tuple, axis=1)
        frame["_foundation_series"] = tuples.map(lambda values: " · ".join(values))
        if len(set(tuples)) != frame["_foundation_series"].nunique():
            raise ValueError("ml_ts_series: series identifiers collide after formatting")
    else:
        frame["_foundation_series"] = target
    if frame["_foundation_series"].nunique() > MAX_SERIES:
        raise ValueError(f"ml_ts_series: at most {MAX_SERIES} series")
    series, frequency, holes = {}, None, 0
    for name, rows in frame.groupby("_foundation_series", sort=True):
        rows = rows.sort_values(time_column)
        if rows[time_column].duplicated().any():
            raise ValueError("ml_ts_duplicates: a series repeats a date")
        index = pd.DatetimeIndex(rows[time_column])
        found = _frequency(index, spec.get("frequency", "auto"))
        if not found or (frequency is not None and found != frequency):
            raise ValueError("ml_ts_frequency: series must share one regular frequency")
        frequency = found
        values = rows.set_index(time_column)[[target]].astype(float)
        grid, missing = _regularize(values, frequency=frequency, columns=[target], fill=spec.get("fill", "refuse"))
        # asfreq can omit an off-grid observation; reject that rather than
        # silently changing the historical or held-out values being scored.
        if not values.index.isin(grid.index).all():
            raise ValueError("ml_ts_frequency: history contains off-grid timestamps")
        if not np.isfinite(grid[target].to_numpy()).all():
            raise ValueError("ml_ts_values: target values must be finite")
        series[str(name)] = grid[target]
        holes += missing
    if not series:
        raise ValueError("ml_ts_history: empty history")
    first = next(iter(series.values())).index
    if any(not values.index.equals(first) for values in series.values()):
        raise ValueError("ml_ts_panel_alignment: all series must share the same historical dates")
    return series, frequency, holes


def evaluate(forecaster, series, *, horizon, folds, level, season, progress=None):
    """Give each origin its prefix, measure native intervals and a naive peer."""
    import numpy as np
    import pandas as pd

    span = len(next(iter(series.values())))
    initial = span - folds * horizon
    if initial < max(32, season):
        raise ValueError(f"ml_ts_history: at least {max(32, season)} context steps before {folds} held-out horizons required")
    points = []
    _progress(progress, f"backtesting:0/{folds}")
    for fold in range(folds):
        stop = initial + fold * horizon
        prefix = {name: values.iloc[:stop] for name, values in series.items()}
        forecaster.fit(series=prefix)
        predicted = forecaster.predict_interval(steps=horizon, interval=[(1 - level) / 2, (1 + level) / 2])
        for name, values in series.items():
            block = predicted[predicted["level"] == name]
            expected_index = values.index[stop:stop + horizon]
            if not block.index.equals(expected_index) or len(block) != horizon:
                raise ValueError("ml_ts_prediction: incomplete forecast for held-out dates")
            if not np.isfinite(block[["pred", "lower_bound", "upper_bound"]].to_numpy()).all():
                raise ValueError("ml_ts_prediction: non-finite forecast")
            if (block["lower_bound"] > block["upper_bound"]).any():
                raise ValueError("ml_ts_prediction: inverted interval")
            # Seasonal-naive reference repeats the last season visible at this
            # origin, even when the horizon is longer than that season.
            naive = np.resize(prefix[name].iloc[-season:].to_numpy(), horizon)
            # Match the catalogue MASE definition (one-step naive scale),
            # estimated only from the initial training prefix.
            scaling = values.iloc[:initial].diff().abs().dropna().mean()
            for step, (stamp, row) in enumerate(block.iterrows(), start=1):
                actual = float(values.loc[stamp])
                points.append({
                    "t": str(stamp), "series": name, "fold": fold, "step": step,
                    "actual": actual, "pred": float(row["pred"]),
                    "lower": float(row["lower_bound"]), "upper": float(row["upper_bound"]),
                    "naive": float(naive[step - 1]), "scale": float(scaling),
                })
        _progress(progress, f"backtesting:{fold + 1}/{folds}")
    return pd.DataFrame(points), initial


def score(points):
    import numpy as np

    error = (points["actual"] - points["pred"]).abs()
    denominator = points["actual"].abs() + points["pred"].abs()
    scale = points["scale"].where(points["scale"] > 0)
    inside = (points["actual"] >= points["lower"]) & (points["actual"] <= points["upper"])
    return {
        "mae": _number(error.mean()), "rmse": _number(np.sqrt((error ** 2).mean())),
        "smape": _number((200 * error.div(denominator.where(denominator > 0))).fillna(0).mean()),
        "mase": _number(error.div(scale).mean()), "coverage": _number(inside.mean()),
        "interval_width": _number((points["upper"] - points["lower"]).mean()),
    }


def save_export(manifest, series, frequency, weights, weight_hashes, model_dir):
    import mlflow.pyfunc
    from mlflow.models import ModelSignature
    from mlflow.types import ColSpec, ParamSchema, ParamSpec, Schema

    spec = manifest["spec"]
    work = weights.parent
    foundation = {key: value for key, value in manifest["foundation"].items() if key != "path"}
    foundation["files"] = weight_hashes
    context = {"series": {
        name: {"timestamps": [str(stamp) for stamp in values.tail(CONTEXT_LENGTH).index],
               "values": values.tail(CONTEXT_LENGTH).tolist()}
        for name, values in series.items()
    }}
    (work / "forecaster.json").write_text(json.dumps(context, allow_nan=False))
    meta = {
        "serialization": "json", "kind": "foundation", "shape": spec.get("shape", "single"),
        "target": manifest["target"], "levels": list(series), "frequency": frequency,
        "last_timestamp": str(next(iter(series.values())).index[-1]),
        "horizon": spec["horizon"], "max_steps": MAX_HORIZON, "interval_level": spec.get("interval_level", 0.8),
        "context_length": CONTEXT_LENGTH, "foundation": foundation,
        "exog_future": [], "exog_static": [], "explain": {"kind": "none"},
    }
    (work / "meta.json").write_text(json.dumps(meta, allow_nan=False))
    signature = ModelSignature(
        inputs=Schema([ColSpec("string", "series", required=False), ColSpec("string", "timestamp", required=False)]),
        outputs=Schema([ColSpec("string", "series"), ColSpec("string", "timestamp"),
                        ColSpec("double", "pred"), ColSpec("double", "lower_bound"), ColSpec("double", "upper_bound")]),
        params=ParamSchema([ParamSpec("horizon", "long", spec["horizon"]),
                            ParamSpec("interval_level", "double", spec.get("interval_level", 0.8))]),
    )
    requirements = [f"{name}=={version(name)}" for name in (
        "torch", "chronos-forecasting", "transformers", "accelerate", "einops", "safetensors",
        "skforecast", "scikit-learn", "pandas", "numpy", "mlflow",
    )]
    # A CPU wheel is provided by the dedicated index when installing the
    # exported requirements in an otherwise empty Python environment.
    requirements.insert(0, "--extra-index-url https://download.pytorch.org/whl/cpu")
    mlflow.pyfunc.save_model(
        path=str(model_dir), python_model=str(PYFUNC), signature=signature, pip_requirements=requirements,
        artifacts={"forecaster": str(work / "forecaster.json"), "meta": str(work / "meta.json"), "foundation": str(weights)},
    )
    files = {path.relative_to(model_dir).as_posix(): _sha256(path)
             for path in sorted(model_dir.rglob("*")) if path.is_file()}
    return {"serialization": "json", "sha256": files["artifacts/forecaster.json"],
            "code_file": PYFUNC.name, "code_sha256": files[PYFUNC.name], "files": files}


def main(argv):
    if len(argv) != 3:
        return _fail(5, "usage: ml_foundation_harness.py MANIFEST RESULT")
    started = time.monotonic()
    try:
        manifest = json.loads(Path(argv[1]).read_text())
        spec = manifest["spec"]
        horizon, folds = int(spec["horizon"]), int(spec.get("backtest_folds", 3))
        level = float(spec.get("interval_level", 0.8))
        if not 1 <= horizon <= MAX_HORIZON or not 1 <= folds <= 5 or not 0.5 <= level <= 0.98:
            raise ValueError("invalid horizon, folds or interval level")
        if spec.get("shape", "single") not in ("single", "panel") or spec.get("fill", "refuse") not in ("refuse", "zero"):
            raise ValueError("unsupported series shape or fill policy")
        if any(spec.get(key) for key in ("exog", "calendar", "lags")) or spec.get("tuning", "off") != "off":
            raise ValueError("foundation forecasts do not use covariates, calendar, lags or tuning")
        if manifest.get("algo") != "chronos_zero_shot" or manifest.get("params") or manifest.get("features"):
            raise ValueError("foundation forecasting requires the frozen model and no estimator parameters")
        progress = manifest.get("progress_path")
        model_dir = Path(manifest["model_dir"])
        snapshot = Path(manifest["foundation"]["path"])
        hashes = {name: _sha256(snapshot / name) for name in WEIGHT_FILES}
        expected = manifest["foundation"].get("files")
        if not isinstance(expected, dict) or any(expected.get(name) != digest for name, digest in hashes.items()):
            raise ValueError("foundation snapshot changed after submission")
    except Exception as exc:
        return _fail(5, f"manifest_unusable: {exc}")
    _progress(progress, "reading")
    try:
        import pandas as pd
        frame = pd.read_parquet(manifest["data_path"])
        series, frequency, holes = read_series(frame, spec, manifest["target"])
    except Exception as exc:
        return _fail(2, f"ml_ts_series: {exc}")
    work = model_dir.parent / "foundation-artifacts"
    weights = work / "foundation"
    try:
        weights.mkdir(parents=True, exist_ok=True)
        for name in WEIGHT_FILES:
            shutil.copyfile(snapshot / name, weights / name)
        if any(_sha256(weights / name) != digest for name, digest in hashes.items()):
            return _fail(5, "foundation snapshot changed while copying")
        forecaster = build_forecaster(weights, context_length=CONTEXT_LENGTH)
        season = _season(frequency)
        try:
            points, initial = evaluate(forecaster, series, horizon=horizon, folds=folds,
                                       level=level, season=season, progress=progress)
        except ValueError as exc:
            return _fail(3 if str(exc).startswith("ml_ts_history") else 2, str(exc))
        _progress(progress, f"fitting:{len(frame)}")
        # fit stores context only; no neural parameters are optimized.
        forecaster.fit(series=series)
        if any(_sha256(weights / name) != digest for name, digest in hashes.items()):
            return _fail(4, "foundation weights changed during zero-shot evaluation")
        _progress(progress, "saving")
        artifact = save_export(manifest, series, frequency, weights, hashes, model_dir)
    except Exception as exc:
        return _fail(1, f"ml_foundation_failed: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    scores = score(points)
    primary = "mase" if scores["mase"] is not None else "mae"
    per_series = [{"series": name, **score(rows)} for name, rows in points.groupby("series")]
    per_horizon = [{"step": int(step), **score(rows)} for step, rows in points.groupby("step")]
    plotted = list(series)[:8]
    sample = points[points["series"].isin(plotted)].groupby("series", group_keys=False).tail(max(horizon, 600 // len(plotted)))
    backtest = sample[["t", "series", "fold", "step", "actual", "pred", "lower", "upper"]].to_dict("records")
    history_tail = [{"t": str(stamp), "series": name, "value": float(value)}
                    for name in plotted for stamp, value in series[name].iloc[:initial].tail(min(2 * horizon, 200)).items()]
    forecast = {
        "shape": spec.get("shape", "single"), "algo": "chronos_zero_shot", "strategy": "foundation",
        "frequency": frequency, "season": season, "horizon": horizon, "folds": folds,
        "interval_level": level, "interval_method": "model", "lags": [], "calendar": [],
        "series_count": len(series), "filled_steps": holes, "fill": spec.get("fill", "refuse"),
        "last_timestamp": str(next(iter(series.values())).index[-1]), "serialization": "json",
        "context_length": CONTEXT_LENGTH, "max_steps": MAX_HORIZON,
    }
    provenance = {key: value for key, value in manifest["foundation"].items() if key not in ("path", "files")}
    metrics = {
        "task": "forecasting", "primary": {"key": primary, "value": scores[primary]},
        "scores": [{"key": key, "value": value} for key, value in scores.items() if value is not None],
        "rows": {"total": len(frame), "history": len(next(iter(series.values()))), "backtest": len(points)},
        "columns": {"used": [spec["time_column"], manifest["target"], *spec.get("series_columns", [])], "dropped": []},
        "forecast": forecast, "foundation": {**provenance, "zero_shot": True, "weights_unchanged": True, "files": hashes},
        "baseline": {"key": "seasonal_naive", "season": season, "mae": float((points["actual"] - points["naive"]).abs().mean())},
        "per_series": per_series, "per_horizon": per_horizon, "backtest": backtest, "history_tail": history_tail,
        "importances": [], "explanation": {"method": "unavailable", "reason": "Pretrained foundation model; no feature importance is estimated."},
        "analysis": [], "target": {"name": manifest["target"]},
    }
    result = {
        "metrics": metrics,
        "signature": {"inputs": [], "output": {"task": "forecasting", "target": manifest["target"],
                                                     "levels": list(series), "horizon": horizon, "max_steps": MAX_HORIZON}},
        "input_example": [], "classes": [], "artifact": artifact,
        "duration_ms": round(1000 * (time.monotonic() - started), 1),
    }
    Path(argv[2]).write_text(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
