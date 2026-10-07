"""Killable, train-only Optuna search; completed trials survive a hard deadline.

This subprocess has no dataset path or held-out rows. Its parent keeps the final
fit outside the search budget and can kill an estimator stuck in native code.
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
import time
from pathlib import Path


def _sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def search(config, x_train, y_train, snapshot_path, progress_path=None):
    import numpy as np
    import optuna
    from sklearn.metrics import get_scorer

    harness = _sibling("ml_train_harness")
    translate = _sibling("ml_knob_translation").translate
    seed = config["random_state"]
    tuning = config["tuning"]
    start = dict(tuning["start"])
    trials = min(100, int(tuning["trials"]))
    started = time.monotonic()
    splitter = harness._fold_splitter(tuning["folds"], config["task"], y_train)
    splits = list(splitter.split(x_train, y_train))
    scorer = get_scorer(tuning["metric"])
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize" if tuning["direction"] == "max" else "minimize",
        sampler=optuna.samplers.TPESampler(seed=seed),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=5),
    )
    study.enqueue_trial(start)

    def objective(trial):
        knobs = dict(start)
        for field in tuning["space"]:
            key = field["key"]
            # The author's automatic depth is None, outside the finite search
            # distribution. Preserve it in trial zero; never coerce it to 1.
            if trial.number == 0 and start[key] is None:
                continue
            if field["kind"] == "int":
                knobs[key] = trial.suggest_int(key, int(field["low"]), int(field["high"]), log=field.get("log", False))
            elif field["kind"] == "float":
                knobs[key] = round(trial.suggest_float(key, field["low"], field["high"], log=field.get("log", False)), 6)
            else:
                knobs[key] = trial.suggest_categorical(key, field["choices"])
        trial.set_user_attr("knobs", knobs)
        params = translate(config["algo"], config["task"], knobs,
                           random_state=seed, forest_leaves=tuning["forest_leaves"])
        scores = []
        for step, (fit, validation) in enumerate(splits):
            pipeline = harness._make_pipeline(config["estimator"], params, spec=config.get("spec"), seed=seed)
            pipeline.fit(x_train.iloc[fit], y_train.iloc[fit])
            value = float(scorer(pipeline, x_train.iloc[validation], y_train.iloc[validation]))
            if not math.isfinite(value):
                raise ValueError("non-finite validation score")
            scores.append(value)
            trial.report(float(np.mean(scores)), step)
            if trial.number > 0 and trial.should_prune():
                raise optuna.TrialPruned()
        trial.set_user_attr("std", float(np.std(scores)))
        return float(np.mean(scores))

    def snapshot(study, trial):
        completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        baseline = next((t for t in completed if t.number == 0), None)
        # Without a valid baseline there is no comparison: keep the form.
        if trial.number == 0 and baseline is None:
            study.stop()
        best = study.best_trial if baseline else None

        def result(t):
            return {"knobs": t.user_attrs["knobs"] if t else start,
                    "score": t.value if t else None, "std": t.user_attrs.get("std") if t else None}

        payload = {
            "metric": tuning["metric"], "direction": tuning["direction"],
            "trials_run": len(study.trials), "folds": len(splits),
            "trials_pruned": sum(t.state == optuna.trial.TrialState.PRUNED for t in study.trials),
            "trials_failed": sum(t.state == optuna.trial.TrialState.FAIL for t in study.trials),
            "budget_s": tuning["budget_s"], "elapsed_s": time.monotonic() - started,
            "stopped_by": "trials", "start": result(baseline),
            "best": {**result(best), "trial": best.number if best else None},
            "trials": [{"n": t.number, "score": t.value if t.state == optuna.trial.TrialState.COMPLETE else None,
                        "state": ("failed" if t.state.name == "FAIL" else t.state.name.lower()), "duration_ms": round(t.duration.total_seconds() * 1000, 1)}
                       for t in study.trials[:100]],
        }
        if baseline is None:
            payload["warning"] = "ML_TUNING_BASELINE_UNAVAILABLE"
        path = Path(snapshot_path)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, allow_nan=False))
        temporary.replace(path)
        harness._progress(progress_path, f"tuning:{len(study.trials)}/{trials}")

    study.optimize(objective, n_trials=trials, timeout=tuning["budget_s"], n_jobs=1,
                   callbacks=[snapshot], catch=(Exception,))


if __name__ == "__main__":
    import joblib
    config, x_train, y_train = joblib.load(sys.argv[1])
    search(config, x_train, y_train, sys.argv[2], config.get("progress_path"))
