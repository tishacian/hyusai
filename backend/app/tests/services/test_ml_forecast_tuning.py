"""Temporal search never sees the final backtest and never loses its baseline."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.core.config import settings
from app.resources import ml_forecast_tuning as tuning
from app.services import tabular_ml
from app.tests.services.test_ml_forecast_validation import (  # noqa: F401
    _refused,
    _validate,
    available,
    enabled,
    panel,
    single,
    store,
    workspace,
)


def config(shape="single", **overrides):
    spec = {
        "time_column": "ts",
        "shape": shape,
        "horizon": 5,
        "backtest_folds": 2,
        "calendar": False,
        "frequency": "D",
        "lags": [1, 2, 7],
        "fill": "refuse",
    }
    if shape == "panel":
        spec["series_columns"] = ["series"]
    if shape == "multivariate":
        spec["exog"] = {"other": "past"}
    return {
        "algo": "linear",
        "task": "forecasting",
        "target": "y",
        "random_state": 42,
        "estimator": "sklearn.linear_model.Ridge",
        "spec": spec,
        "tuning": {
            "trials": 5,
            "budget_s": 30,
            "metric": "mae",
            "direction": "min",
            "folds": 2,
            "start": {"alpha": 1.0, "max_iter": 500},
            "forest_leaves": 2048,
            "space": [{"key": "alpha", "kind": "float", "low": 0.001, "high": 20, "log": True}],
        },
        "params": {"alpha": 1.0, "max_iter": 500},
        **overrides,
    }


def data(shape="single", rows=100):
    index = pd.date_range("2025-01-01", periods=rows, freq="D", name="ts")
    values = np.arange(rows)
    y = pd.Series(10 + 0.05 * values + np.sin(values * 2 * np.pi / 7), index=index, name="y")
    other = pd.Series(np.cos(values * 2 * np.pi / 7), index=index, name="other")
    if shape == "panel":
        truth = pd.DataFrame({"one": y, "two": y * 1.5})
        series = {key: truth[key] for key in truth}
    else:
        truth = y.to_frame()
        series = pd.concat([y, other], axis=1) if shape == "multivariate" else None
    return {"truth": truth, "series": series, "y": y if shape != "panel" else None, "exog": None}


def test_forecast_tuning_validates_algorithm_history_budget_and_shared_catalog(single, monkeypatch):
    monkeypatch.setattr(settings, "ml_train_timeout_s", 100)
    spec = _validate(single, spec={"tuning": "budget", "horizon": 12})
    assert spec.spec["tuning_budget_s"] == 60
    selected = tabular_ml.tuning_configuration(spec)
    assert selected["metric"] == "mae" and selected["direction"] == "min"
    assert selected["folds"] == 3 and selected["start"] == spec.knobs
    payload = tabular_ml.catalog_payload()
    family = next(row for row in payload["families"] if row["key"] == "forecasting")
    budget = next(row for row in family["spec_fields"] if row["key"] == "tuning_budget_s")
    assert budget["default"] == budget["max"] == 60
    for algo in ("ets", "arima", "seasonal_naive"):
        assert (
            _refused(single, algo=algo, spec={"tuning": "budget"}).code
            == "ML_TS_TUNING_UNSUPPORTED"
        )
    assert (
        _refused(single, spec={"tuning": "budget", "tuning_budget_s": 61}).code == "ML_SPEC_INVALID"
    )
    assert (
        _refused(single, spec={"tuning": "budget", "fill": "interpolate"}).code
        == "ML_TS_TUNING_FILL_UNSAFE"
    )
    assert (
        _refused(single, spec={"tuning": "budget", "horizon": 100}).code
        == "ML_TS_HISTORY_TOO_SHORT"
    )
    for invalid in ({"tuning_trials": 101}, {"tuning_folds": 1}, {"tuning_budget_s": 29}):
        assert _refused(single, spec={"tuning": "budget", **invalid}).code == "ML_SPEC_INVALID"


def test_forecast_manifest_persists_temporal_search_and_effective_selected_knobs(
    single, db_session, tmp_path, monkeypatch
):
    spec = _validate(
        single, algo="linear", spec={"tuning": "budget", "horizon": 12, "tuning_folds": 2}
    )
    model = tabular_ml.create_model(db_session, workspace_id=single.workspace_id, spec=spec)
    manifest = json.loads(
        tabular_ml._write_manifest(tmp_path, model, Path("data.parquet")).read_text()
    )
    assert manifest["tuning"]["metric"] == "mae" and manifest["tuning"]["folds"] == 2
    monkeypatch.setattr(settings, "ml_train_timeout_s", 100)
    updated = json.loads(tabular_ml._write_manifest(tmp_path, model, Path("data.parquet")).read_text())
    assert updated["tuning"]["budget_s"] == 60
    tabular_ml._apply_summary(
        model, {"metrics": {"tuning": {"best": {"knobs": {"alpha": 2, "max_iter": 100}}}}}
    )
    assert model.params_json["estimator_params"]["alpha"] == 2
    assert "C" not in model.params_json["estimator_params"]


@pytest.mark.parametrize("shape", ["single", "panel", "multivariate"])
def test_actual_temporal_search_scores_baseline_and_keeps_only_improvements(shape, tmp_path):
    pytest.importorskip("skforecast")
    selected = config(shape)
    selected.update(frequency="D", lags=[1, 2, 7])
    destination = tmp_path / "trials.json"
    tuning.search(selected, data(shape), destination)
    result = json.loads(destination.read_text())
    exact, std, naive = tuning.evaluate(selected, data(shape), selected["tuning"]["start"])
    assert result["start"]["knobs"] == selected["tuning"]["start"]
    assert result["start"]["score"] == pytest.approx(exact)
    assert result["start"]["std"] == pytest.approx(std)
    assert result["baseline"]["mae"] == pytest.approx(naive)
    assert result["best"]["score"] <= exact
    assert len(result["trials"]) == 5 and result["trials_failed"] == 0
    assert all(row["state"] == "complete" and row["knobs"] for row in result["trials"])


def test_search_is_seeded_and_respects_automatic_forest_depth(tmp_path):
    pytest.importorskip("skforecast")
    selected = config(algo="random_forest", estimator="sklearn.ensemble.RandomForestRegressor")
    selected["tuning"].update(
        start={"max_depth": None, "n_estimators": 5, "min_samples_leaf": 1},
        space=[{"key": "max_depth", "kind": "int", "low": 1, "high": 8}],
        trials=3,
    )
    selected.update(frequency="D", lags=[1, 7])
    results = []
    for name in ("first", "second"):
        target = tmp_path / f"{name}.json"
        tuning.search(selected, data(), target)
        results.append(json.loads(target.read_text()))
    first, second = results
    assert first["best"] == second["best"]
    assert first["start"]["knobs"]["max_depth"] is None
    assert first["best"]["score"] <= first["start"]["score"]


def test_budget_interrupts_native_search_and_falls_back_to_form_without_claiming_a_score():
    pytest.importorskip("skforecast")
    selected = config(algo="random_forest", estimator="sklearn.ensemble.RandomForestRegressor")
    selected["tuning"].update(
        budget_s=1, start={"max_depth": None, "n_estimators": 600, "min_samples_leaf": 1}, space=[]
    )
    started = time.monotonic()
    params, result = tuning.tune(selected, data(rows=3000), frequency="D", lags=[1, 2, 7])
    assert time.monotonic() - started < 2.5
    assert result["stopped_by"] == "budget"
    assert result["warning"] == "ML_TUNING_BASELINE_UNAVAILABLE"
    assert result["best"]["knobs"] == selected["tuning"]["start"]
    assert result["best"]["score"] is None and params["max_leaf_nodes"] == 2048


def test_child_receives_only_prefix_data_and_never_source_path(monkeypatch):
    import joblib

    original = joblib.dump
    seen = []

    def record(value, path):
        seen.append(value)
        return original(value, path)

    monkeypatch.setattr(joblib, "dump", record)
    selected = config(data_path="/forbidden/final-test.parquet", forbidden="heldout")
    selected["tuning"]["budget_s"] = 0.000001
    train = data()
    _, result = tuning.tune(selected, train, frequency="D", lags=[1, 2, 7])
    child, actual = seen[0]
    assert "data_path" not in child and "forbidden" not in child
    assert actual is train
    assert result["validation"]["train_end"] == str(train["truth"].index[-1])


def test_short_or_late_starting_panel_is_refused_before_search():
    selected = config("panel")
    train = data("panel")
    train["series"]["two"] = train["series"]["two"].iloc[-20:]
    with pytest.raises(ValueError, match="ml_ts_tuning_history"):
        tuning.tune(selected, train, frequency="D", lags=[1, 2, 7])


def test_failed_trial_retains_baseline_and_failed_baseline_stops_search(tmp_path, monkeypatch):
    pytest.importorskip("skforecast")
    selected = config()
    selected.update(frequency="D", lags=[1, 2, 7])

    def evaluate(_, __, knobs):
        if knobs["alpha"] != 1.0:
            raise ValueError("bad fit")
        return 5.0, 0.2, 6.0

    monkeypatch.setattr(tuning, "evaluate", evaluate)
    destination = tmp_path / "result.json"
    tuning.search(selected, data(), destination)
    result = json.loads(destination.read_text())
    assert result["best"]["trial"] == 0 and result["trials_failed"] == 4
    monkeypatch.setattr(
        tuning, "evaluate", lambda *args: (_ for _ in ()).throw(ValueError("baseline failed"))
    )
    tuning.search(selected, data(), destination)
    result = json.loads(destination.read_text())
    assert result["trials_run"] == 1 and result["warning"] == "ML_TUNING_BASELINE_UNAVAILABLE"


def run_harness(root, shape, monkeypatch, *, holdout_shift=0.0, direct=False):
    from app.resources import ml_forecast_harness as harness

    root.mkdir()
    values = data(shape, rows=100)
    if shape == "panel":
        frame = pd.concat(
            [
                series.rename("y").to_frame().assign(series=name)
                for name, series in values["series"].items()
            ]
        ).reset_index()
    elif shape == "multivariate":
        frame = values["series"].reset_index()
    else:
        frame = values["y"].to_frame().reset_index()
    cutoff = sorted(frame["ts"].unique())[-10]
    frame.loc[frame["ts"] >= cutoff, "y"] += holdout_shift
    frame.to_parquet(root / "data.parquet")
    selected = config(
        shape,
        data_path=str(root / "data.parquet"),
        model_dir=str(root / "model"),
        progress_path=str(root / "progress"),
        report_state_limit_mb=0,
    )
    selected["spec"].update(tuning="budget", tuning_folds=2)
    if direct:
        selected["spec"]["strategy"] = "direct"
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(selected))
    # These explanations are orthogonal to temporal selection. The real
    # forecaster, backtest, final fit, serialization and pyfunc remain active.
    monkeypatch.setattr(harness, "_explain_fit", lambda *a, **kw: ({}, {"kind": "none"}))
    monkeypatch.setattr(harness, "diagnose_regressor", lambda *a, **kw: (None, None))
    result_path = root / "result.json"
    assert harness.main(["harness", str(manifest), str(result_path)]) == 0
    return json.loads(result_path.read_text()), root / "model"


@pytest.mark.parametrize(
    "shape,direct", [("single", False), ("single", True), ("panel", False), ("multivariate", True)]
)
def test_real_harness_fits_selected_model_and_keeps_backtest_out_of_search(
    shape, direct, tmp_path, monkeypatch
):
    pytest.importorskip("skforecast")
    import mlflow.pyfunc

    summary, model_path = run_harness(tmp_path / "fit", shape, monkeypatch, direct=direct)
    search = summary["metrics"]["tuning"]
    assert search["trials_run"] == 5
    assert search["best"]["score"] <= search["start"]["score"]
    assert search["validation"]["train_end"] < search["validation"]["holdout_start"]
    assert search["validation"]["rows"] == 90 and search["validation"]["holdout_rows"] == 10
    assert len(summary["metrics"]["backtest"]) == (20 if shape == "panel" else 10)
    loaded = mlflow.pyfunc.load_model(str(model_path))
    prediction = loaded.predict(
        pd.DataFrame({"series": pd.Series([], dtype=str), "timestamp": pd.Series([], dtype=str)})
    )
    assert len(prediction) == (10 if shape == "panel" else 5)
    assert pd.to_datetime(prediction["timestamp"]).min() > pd.Timestamp("2025-04-10")
    forecaster = loaded.unwrap_python_model().forecaster
    estimator = forecaster.estimators_[1] if direct else forecaster.estimator
    assert estimator.alpha == search["best"]["knobs"]["alpha"]


def test_changing_only_final_holdout_cannot_change_temporal_selection(tmp_path, monkeypatch):
    pytest.importorskip("skforecast")
    original, _ = run_harness(tmp_path / "original", "single", monkeypatch)
    changed, _ = run_harness(tmp_path / "changed", "single", monkeypatch, holdout_shift=1000)
    left, right = original["metrics"]["tuning"], changed["metrics"]["tuning"]
    assert left["start"] == right["start"] and left["best"] == right["best"]
    assert left["baseline"] == right["baseline"]
    assert [row["score"] for row in left["trials"]] == [row["score"] for row in right["trials"]]
    assert original["metrics"]["scores"] != changed["metrics"]["scores"]


def test_tuning_requires_a_full_last_season_and_complete_validation_window():
    selected = config()
    with pytest.raises(ValueError, match="ml_ts_tuning_history"):
        tuning.tune(selected, data(rows=50), frequency="W", lags=[1, 2])
    train = data("panel")
    train["truth"].iloc[-1, 0] = np.nan
    with pytest.raises(ValueError, match="every series must cover"):
        tuning.tune(config("panel"), train, frequency="D", lags=[1, 2, 7])
