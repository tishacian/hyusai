"""Killable Optuna search over an isolated temporal training prefix.

The child receives neither the source parquet path nor the final backtest rows.
Every trial, including the exact form settings, uses the same expanding folds.
Completed trials are atomically checkpointed so a native fit can be killed at
its budget without losing the baseline or the best completed candidate.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validation(config, train):
    horizon, folds = int(config["spec"]["horizon"]), int(config["tuning"]["folds"])
    initial = len(train["truth"]) - folds * horizon
    minimum = max(
        max(config["lags"]) + 2 * horizon,
        _sibling("ml_forecast_harness")._season(config["frequency"]),
    )
    cutoff = train["truth"].index[initial] if initial > 0 else None
    series = train["series"]
    histories = list(series.values()) if isinstance(series, dict) else [train["truth"]]
    if cutoff is None or any(
        len(values.loc[values.index < cutoff].dropna()) < minimum for values in histories
    ):
        raise ValueError(
            f"ml_ts_tuning_history: each series needs {minimum} training steps before the inner folds"
        )
    if train["truth"].iloc[initial:].isna().any().any():
        raise ValueError(
            "ml_ts_tuning_history: every series must cover every inner validation timestamp"
        )
    return {
        "method": "expanding_window",
        "metric": "mae",
        "aggregation": "mean_per_series",
        "train_start": str(train["truth"].index[0]),
        "train_end": str(train["truth"].index[-1]),
        "initial_train_size": initial,
        "rows": len(train["truth"]),
        "horizon": horizon,
        "folds": folds,
    }


def evaluate(config, train, knobs):
    import numpy as np
    import pandas as pd
    from skforecast.model_selection import (
        TimeSeriesFold,
        backtesting_forecaster,
        backtesting_forecaster_multiseries,
    )

    harness = _sibling("ml_forecast_harness")
    params = _sibling("ml_knob_translation").translate(
        config["algo"],
        "forecasting",
        knobs,
        random_state=config["random_state"],
        forest_leaves=config["tuning"]["forest_leaves"],
    )
    model, _ = harness.build_forecaster(
        {**config, "params": params}, frequency=config["frequency"], lags=config["lags"]
    )
    horizon, folds = int(config["spec"]["horizon"]), int(config["tuning"]["folds"])
    cv = TimeSeriesFold(
        steps=horizon,
        initial_train_size=len(train["truth"]) - folds * horizon,
        refit=True,
        fixed_train_size=False,
        verbose=False,
    )
    common = {"cv": cv, "metric": "mean_absolute_error", "n_jobs": 1, "show_progress": False}
    if config["spec"].get("shape", "single") in ("panel", "multivariate"):
        _, predictions = backtesting_forecaster_multiseries(
            model,
            series=train["series"],
            exog=train["exog"] or None if isinstance(train["exog"], dict) else train["exog"],
            **common,
        )
    else:
        _, predictions = backtesting_forecaster(model, y=train["y"], exog=train["exog"], **common)
    points = predictions.copy()
    if "level" not in points:
        points["level"] = config["target"]
    points["level"] = points["level"].astype(str)
    truth = train["truth"]
    points = points[points["level"].isin([str(c) for c in truth.columns])]
    actual = harness._long(truth).reindex(
        pd.MultiIndex.from_arrays([points.index, points["level"]])
    )
    points["actual"] = actual.to_numpy()
    if "fold" not in points:
        points["fold"] = points.groupby("level").cumcount() // horizon
    points["step"] = points.groupby(["level", "fold"]).cumcount() + 1
    errors = (points["actual"] - points["pred"]).abs()
    if (
        len(points) != folds * horizon * len(truth.columns)
        or set(points["level"]) != {str(column) for column in truth.columns}
        or not np.isfinite(errors.to_numpy()).all()
    ):
        raise ValueError("ml_ts_tuning_non_finite: incomplete validation predictions")
    fold_scores = (
        points.assign(error=errors)
        .groupby(["fold", "level"])["error"]
        .mean()
        .groupby("fold")
        .mean()
    )
    season = harness._season(config["frequency"])
    shifts = (season * np.ceil(points["step"].to_numpy() / season)).astype(int)
    naive = np.full(len(points), np.nan)
    for shift in np.unique(shifts):
        mask = shifts == shift
        reference = harness._long(truth.shift(int(shift))).reindex(
            pd.MultiIndex.from_arrays([points.index[mask], points["level"].to_numpy()[mask]])
        )
        naive[mask] = np.abs(points["actual"].to_numpy()[mask] - reference.to_numpy())
    naive_mae = (
        float(points.assign(error=naive).groupby("level")["error"].mean().mean())
        if np.isfinite(naive).all()
        else None
    )
    return float(fold_scores.mean()), float(fold_scores.std(ddof=0)), naive_mae


def search(config, train, destination):
    import optuna

    _validation(config, train)
    tuning = config["tuning"]
    start, trials = dict(tuning["start"]), min(100, int(tuning["trials"]))
    started = time.monotonic()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="minimize", sampler=optuna.samplers.TPESampler(seed=config["random_state"])
    )

    def objective(trial):
        knobs = dict(start)
        # Trial zero is the form exactly, including None (automatic forest
        # depth). Its values need not belong to finite search distributions.
        if trial.number:
            for field in tuning["space"]:
                key = field["key"]
                if field["kind"] == "int":
                    knobs[key] = trial.suggest_int(
                        key, int(field["low"]), int(field["high"]), log=field.get("log", False)
                    )
                elif field["kind"] == "float":
                    knobs[key] = round(
                        trial.suggest_float(
                            key, field["low"], field["high"], log=field.get("log", False)
                        ),
                        6,
                    )
                else:
                    knobs[key] = trial.suggest_categorical(key, field["choices"])
        trial.set_user_attr("knobs", knobs)
        score, std, naive = evaluate(config, train, knobs)
        if not math.isfinite(score):
            raise ValueError("non-finite temporal validation score")
        trial.set_user_attr("std", std)
        trial.set_user_attr("seasonal_naive_mae", naive)
        return score

    def snapshot(study, trial):
        completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        baseline = next((t for t in completed if t.number == 0), None)
        if trial.number == 0 and baseline is None:
            study.stop()
        best = study.best_trial if baseline else None

        def result(row):
            return {
                "knobs": row.user_attrs["knobs"] if row else start,
                "score": row.value if row else None,
                "std": row.user_attrs.get("std") if row else None,
            }

        payload = {
            "metric": "mae",
            "direction": "min",
            "trials_run": len(study.trials),
            "folds": tuning["folds"],
            "trials_pruned": 0,
            "trials_failed": sum(t.state.name == "FAIL" for t in study.trials),
            "budget_s": tuning["budget_s"],
            "elapsed_s": time.monotonic() - started,
            "start": result(baseline),
            "best": {**result(best), "trial": best.number if best else None},
            "baseline": {
                "key": "seasonal_naive",
                "mae": baseline.user_attrs.get("seasonal_naive_mae") if baseline else None,
            },
            "trials": [
                {
                    "n": t.number,
                    "score": t.value if t.state.name == "COMPLETE" else None,
                    "knobs": t.user_attrs.get("knobs", {}),
                    "state": "failed" if t.state.name == "FAIL" else t.state.name.lower(),
                    "duration_ms": round(t.duration.total_seconds() * 1000, 1),
                }
                for t in study.trials
            ],
        }
        if baseline is None:
            payload["warning"] = "ML_TUNING_BASELINE_UNAVAILABLE"
        path = Path(destination)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, allow_nan=False))
        temporary.replace(path)
        _sibling("ml_forecast_harness")._progress(
            config.get("progress_path"), f"tuning:{len(study.trials)}/{trials}"
        )

    study.optimize(
        objective,
        n_trials=trials,
        timeout=float(tuning["budget_s"]),
        n_jobs=1,
        callbacks=[snapshot],
        catch=(Exception,),
    )


def tune(manifest, train, *, frequency, lags):
    import joblib

    config = {key: manifest[key] for key in ("algo", "target", "estimator", "spec", "tuning")}
    config.update(
        random_state=int(manifest.get("random_state", 42)),
        frequency=frequency,
        lags=lags,
        progress_path=manifest.get("progress_path"),
    )
    validation = _validation(config, train)
    tuning = config["tuning"]
    budget = float(tuning["budget_s"])
    started = time.monotonic()
    _sibling("ml_forecast_harness")._progress(
        config["progress_path"], f"tuning:0/{tuning['trials']}"
    )
    result, stopped, failed = {}, False, False
    with tempfile.TemporaryDirectory(prefix="ml-ts-tuning-") as scratch:
        source, destination = Path(scratch) / "train.joblib", Path(scratch) / "result.json"
        joblib.dump((config, train), source)
        remaining = budget - (time.monotonic() - started)
        if remaining > 0:
            env = {
                **os.environ,
                **{
                    key: "1"
                    for key in (
                        "OMP_NUM_THREADS",
                        "OPENBLAS_NUM_THREADS",
                        "MKL_NUM_THREADS",
                        "NUMEXPR_NUM_THREADS",
                    )
                },
            }
            with subprocess.Popen(
                [sys.executable, str(Path(__file__)), str(source), str(destination)], env=env
            ) as child:
                try:
                    child.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    stopped = True
                    child.kill()
                    child.wait()
                failed = bool(child.returncode) and not stopped
            if destination.exists():
                result = json.loads(destination.read_text())
        else:
            stopped = True
    if not result:
        baseline = {"knobs": tuning["start"], "score": None, "std": None}
        result = {
            "metric": "mae",
            "direction": "min",
            "trials_run": 0,
            "trials_pruned": 0,
            "trials_failed": 0,
            "folds": tuning["folds"],
            "budget_s": budget,
            "trials": [],
            "start": baseline,
            "best": {**baseline, "trial": None},
            "baseline": {"key": "seasonal_naive", "mae": None},
            "warning": "ML_TS_TUNING_FAILED" if failed else "ML_TUNING_BASELINE_UNAVAILABLE",
        }
    result["elapsed_s"] = round(time.monotonic() - started, 3)
    result["stopped_by"] = (
        "budget" if stopped or result["elapsed_s"] >= budget else "failed" if failed else "trials"
    )
    result["validation"] = validation
    params = _sibling("ml_knob_translation").translate(
        manifest["algo"],
        "forecasting",
        result["best"]["knobs"],
        random_state=config["random_state"],
        forest_leaves=tuning["forest_leaves"],
    )
    return params, result


if __name__ == "__main__":
    import joblib

    config, train = joblib.load(sys.argv[1])
    search(config, train, sys.argv[2])
