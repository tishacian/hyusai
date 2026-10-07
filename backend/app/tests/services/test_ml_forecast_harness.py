"""The forecasting harness, run for real on Nawa's network cells.

These fit skforecast models in the harness subprocess, exactly as the ml-ts
worker does, so they only run where that stack is installed (the ml-ts image,
or a development venv with ``skforecast[stats]``). Each shape is fitted once
per module and read by several tests: a fit is the expensive part, and what is
under test is the evidence it leaves behind and the model it saves.

The data is the demo's own generator: hourly PRB load per cell, a busy hour, a
weekend, and cells that degrade — the series the pilot forecasts.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("skforecast")
pytest.importorskip("mlflow.pyfunc")

import pandas as pd  # noqa: E402

from app.resources import ml_forecast_harness as harness  # noqa: E402
from scripts.gen_nawa_telecom_data import network_cell_frame  # noqa: E402

pytestmark = pytest.mark.slow

HORIZON = 24
TARGET = "prb_utilization_pct"
GBM = "sklearn.ensemble.HistGradientBoostingRegressor"
RIDGE = "sklearn.linear_model.Ridge"


def _cells(cells: int, days: int = 28) -> pd.DataFrame:
    return network_cell_frame(cells=cells, days=days).to_pandas()


def _one_cell(days: int = 28) -> pd.DataFrame:
    frame = _cells(1, days)
    return frame.drop(columns=["cell_id", "site_code", "region", "technology"])


def _fit(root: Path, frame: pd.DataFrame, *, algo: str, estimator: str | None, params=None, **spec) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(root / "data.parquet")
    problem = {
        "time_column": "ts",
        "horizon": HORIZON,
        "backtest_folds": 3,
        "interval_level": 0.8,
        "fill": "refuse",
        "calendar": True,
        **spec,
    }
    manifest = {
        "family": "forecasting",
        "spec": problem,
        "data_path": str(root / "data.parquet"),
        "model_dir": str(root / "model"),
        "task": "forecasting",
        "algo": algo,
        "target": TARGET,
        "features": list((problem.get("exog") or {})),
        "estimator": estimator,
        "params": params or {},
        "progress_path": str(root / "progress.txt"),
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    completed = subprocess.run(  # noqa: S603 - our interpreter, our harness
        [sys.executable, str(Path(harness.__file__)), str(root / "manifest.json"), str(root / "result.json")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=900,
        env={"PATH": "/usr/bin:/bin", "MLFLOW_TRACKING_URI": str(root / "mlruns"), "OMP_NUM_THREADS": "2"},
    )
    result = json.loads((root / "result.json").read_text()) if (root / "result.json").exists() else {}
    progress = (root / "progress.txt").read_text().split() if (root / "progress.txt").exists() else []
    return {"code": completed.returncode, "stderr": completed.stderr, "result": result, "root": root, "progress": progress}


@pytest.fixture(scope="module")
def recursive(tmp_path_factory):
    return _fit(
        tmp_path_factory.mktemp("recursive"), _one_cell(), algo="gradient_boosting", estimator=GBM,
        params={"random_state": 0},
    )


@pytest.fixture(scope="module")
def direct(tmp_path_factory):
    frame = _one_cell()
    # A covariate known in advance: planned works, one hour a week.
    frame["maintenance"] = (frame["ts"].dt.dayofweek == 2) & (frame["ts"].dt.hour == 3)
    frame["maintenance"] = frame["maintenance"].astype(float)
    return _fit(
        tmp_path_factory.mktemp("direct"), frame, algo="linear", estimator=RIDGE, params={"alpha": 1.0},
        strategy="direct", exog={"maintenance": "future"},
    )


@pytest.fixture(scope="module")
def ets(tmp_path_factory):
    return _fit(tmp_path_factory.mktemp("ets"), _one_cell(21), algo="ets", estimator="skforecast.stats.Ets")


@pytest.fixture(scope="module")
def panel(tmp_path_factory):
    return _fit(
        tmp_path_factory.mktemp("panel"), _cells(4), algo="gradient_boosting", estimator=GBM,
        params={"random_state": 0}, shape="panel", series_columns=["cell_id"], exog={"technology": "static"},
    )


@pytest.fixture(scope="module")
def multivariate(tmp_path_factory):
    return _fit(
        tmp_path_factory.mktemp("multivariate"), _one_cell(), algo="linear", estimator=RIDGE,
        params={"alpha": 1.0}, shape="multivariate", exog={"active_users": "past", "throughput_mbps": "past"},
        lags=[1, 2, 24],
    )


def _ok(run: dict) -> dict:
    assert run["code"] == 0, run["stderr"][-3000:]
    return run["result"]


def _scores(result: dict) -> dict:
    return {score["key"]: score["value"] for score in result["metrics"]["scores"]}


def _load(run: dict):
    import mlflow.pyfunc

    return mlflow.pyfunc.load_model(str(run["root"] / "model"))


def _no_rows(*columns: str) -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series([], dtype=str) for column in ("series", "timestamp", *columns)})


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def test_a_backtest_scores_the_forecast_on_horizons_it_never_saw(recursive):
    result = _ok(recursive)
    metrics = result["metrics"]

    assert metrics["task"] == "forecasting"
    assert metrics["primary"]["key"] == "mase"
    scores = _scores(result)
    assert set(scores) == {"mae", "rmse", "mape", "smape", "mase", "coverage", "interval_width"}
    assert all(math.isfinite(value) for value in scores.values())
    assert scores["rmse"] >= scores["mae"] > 0
    forecast = metrics["forecast"]
    assert forecast["frequency"] == "h" and forecast["season"] == 24
    # Hourly data, so the default lags reach the same hour yesterday and last week.
    assert forecast["lags"] == [1, 2, 3, 24, 168]
    assert forecast["calendar"] == ["hour", "day_of_week"]
    assert forecast["interval_method"] == "conformal"
    assert metrics["rows"]["backtest"] == 3 * HORIZON
    # The steps a polled row walks through, in order, with the counts the UI shows.
    assert recursive["progress"] == ["reading", "backtesting:0/3", "backtesting:3/3", f"fitting:{28 * 24}", "saving"]


def test_the_interval_is_calibrated_on_earlier_folds_and_covers_about_its_level(recursive, panel):
    for run in (recursive, panel):
        result = _ok(run)
        points = result["metrics"]["backtest"]
        # The first fold has no earlier errors to be bracketed with.
        assert all(point["lower"] is None for point in points if point["fold"] == 0)
        assert all(point["lower"] < point["pred"] < point["upper"] for point in points if point["fold"] > 0)
        # 80% asked; a calibrated interval lands near it, not at 30% or 100%.
        assert 0.6 <= _scores(result)["coverage"] <= 0.97


def test_the_error_is_read_per_step_and_against_the_seasonal_naive(recursive):
    metrics = _ok(recursive)["metrics"]

    assert [entry["step"] for entry in metrics["per_horizon"]] == list(range(1, HORIZON + 1))
    assert all(entry["mae"] >= 0 for entry in metrics["per_horizon"])
    assert metrics["baseline"]["key"] == "seasonal_naive" and metrics["baseline"]["mae"] > 0
    # The context the chart opens on ends where the first fold begins.
    assert len(metrics["history_tail"]) == 2 * HORIZON
    first_fold = min(pd.Timestamp(point["t"]) for point in metrics["backtest"])
    assert max(pd.Timestamp(point["t"]) for point in metrics["history_tail"]) < first_fold
    assert {point["series"] for point in metrics["backtest"]} == {TARGET}


def test_a_panel_is_one_model_with_an_error_per_series(panel):
    metrics = _ok(panel)["metrics"]

    assert metrics["forecast"]["series_count"] == 4
    assert len(metrics["per_series"]) == 4
    assert all(entry["mae"] > 0 for entry in metrics["per_series"])
    # The worst series first: it is the one an engineer opens.
    mase = [entry["mase"] for entry in metrics["per_series"]]
    assert mase == sorted(mase, reverse=True)
    # A static covariate is coded once over the panel, with its labels kept.
    assert set(metrics["static_codes"]["technology"]) <= {"4G", "5G"}
    assert 1 <= len({point["series"] for point in metrics["backtest"]}) <= 3


def test_a_statistical_model_keeps_its_own_intervals_and_is_saved_by_joblib(ets):
    result = _ok(ets)
    forecast = result["metrics"]["forecast"]

    assert forecast["interval_method"] == "model" and forecast["lags"] == []
    # skops does not describe statsmodels-style estimators: joblib, by hash.
    assert forecast["serialization"] == "joblib" and result["artifact"]["serialization"] == "joblib"
    assert 0.5 <= _scores(result)["coverage"] <= 1.0


def test_a_multivariate_forecast_reads_the_series_that_move_with_it(multivariate):
    metrics = _ok(multivariate)["metrics"]

    assert metrics["forecast"]["strategy"] == "direct" and metrics["forecast"]["lags"] == [1, 2, 24]
    features = {entry["feature"] for entry in metrics["importances"]}
    assert any(feature.startswith("active_users") for feature in features)


# ---------------------------------------------------------------------------
# The saved model
# ---------------------------------------------------------------------------


def test_the_saved_model_forecasts_what_the_fitted_one_does(recursive):
    from skforecast.utils import load_forecaster

    result = _ok(recursive)
    model_dir = recursive["root"] / "model"
    assert result["artifact"]["serialization"] == "skops"
    # The artifact on disk is the one the result vouches for.
    assert harness._sha256(model_dir / "artifacts" / "forecaster.skops") == result["artifact"]["sha256"]
    assert harness._sha256(harness.PYFUNC) == result["artifact"]["code_sha256"]

    loaded = _load(recursive)
    answer = loaded.predict(_no_rows(), params={"horizon": 12, "interval_level": 0.9})
    assert list(answer.columns) == ["series", "timestamp", "pred", "lower_bound", "upper_bound"]
    assert len(answer) == 12 and set(answer["series"]) == {TARGET}
    assert (answer["lower_bound"] < answer["pred"]).all() and (answer["pred"] < answer["upper_bound"]).all()

    meta = json.loads((model_dir / "artifacts" / "meta.json").read_text())
    reference = load_forecaster(
        str(model_dir / "artifacts" / "forecaster.skops"), backend="skops", trusted=meta["trusted"], verbose=False
    )
    assert answer["pred"].tolist() == pytest.approx(reference.predict(steps=12).tolist())
    # Forecasts start one step after the last date seen, on its frequency.
    last = pd.Timestamp(result["metrics"]["forecast"]["last_timestamp"])
    assert pd.Timestamp(answer["timestamp"].iloc[0]) == last + pd.Timedelta(hours=1)

    # The signature carries the horizon as a parameter, defaulting to the trained one.
    assert len(loaded.predict(_no_rows())) == HORIZON
    wider = loaded.predict(_no_rows(), params={"interval_level": 0.95})
    narrower = loaded.predict(_no_rows(), params={"interval_level": 0.6})
    assert (wider["upper_bound"] - wider["lower_bound"]).mean() > (narrower["upper_bound"] - narrower["lower_bound"]).mean()


def test_a_direct_model_needs_its_future_covariates_and_its_horizon(direct):
    result = _ok(direct)
    assert result["signature"]["inputs"] == [
        {"name": "maintenance", "type": "double", "kind": "number", "role": "future"}
    ]
    loaded = _load(direct)
    last = pd.Timestamp(result["metrics"]["forecast"]["last_timestamp"])
    future = pd.DataFrame(
        {
            "series": [""] * HORIZON,
            "timestamp": [str(last + pd.Timedelta(hours=step)) for step in range(1, HORIZON + 1)],
            "maintenance": [0.0] * HORIZON,
        }
    )

    assert len(loaded.predict(future, params={"horizon": 6})) == 6
    with pytest.raises(Exception, match="maintenance"):
        loaded.predict(_no_rows("maintenance"), params={"horizon": 6})
    with pytest.raises(Exception, match="lack a value"):
        loaded.predict(future.head(3), params={"horizon": 6})
    # One model per step ahead: there is no step 25 to ask.
    with pytest.raises(Exception, match="at most 24"):
        loaded.predict(future, params={"horizon": HORIZON + 1})


def test_a_panel_model_forecasts_the_series_it_is_asked_for(panel):
    result = _ok(panel)
    loaded = _load(panel)
    levels = result["signature"]["output"]["levels"]

    everything = loaded.predict(_no_rows(), params={"horizon": 6})
    assert len(everything) == 6 * len(levels) and set(everything["series"]) == set(levels)
    one = loaded.predict(pd.DataFrame({"series": [levels[1]], "timestamp": [""]}), params={"horizon": 6})
    assert set(one["series"]) == {levels[1]} and len(one) == 6
    with pytest.raises(Exception, match="unknown series"):
        loaded.predict(pd.DataFrame({"series": ["XXX-000-L00"], "timestamp": [""]}), params={"horizon": 6})


def test_a_statistical_model_round_trips_through_joblib(ets):
    _ok(ets)
    answer = _load(ets).predict(_no_rows(), params={"horizon": 6})
    assert len(answer) == 6 and answer["pred"].notna().all()


# ---------------------------------------------------------------------------
# What the data can refuse
# ---------------------------------------------------------------------------


def test_gaps_are_refused_unless_the_author_chose_how_to_fill_them(tmp_path):
    frame = _one_cell(21)
    holed = frame.drop(index=frame.index[[100, 101, 300]])

    refused = _fit(tmp_path / "refuse", holed, algo="seasonal_naive", estimator=None)
    assert refused["code"] == 2 and "3 missing steps" in refused["stderr"]

    filled = _ok(_fit(tmp_path / "fill", holed, algo="seasonal_naive", estimator=None, fill="interpolate"))
    assert filled["metrics"]["forecast"]["filled_steps"] == 3
    assert filled["metrics"]["baseline"]["mae"] is None  # it is the baseline


def test_too_little_history_exits_with_the_history_code(tmp_path):
    run = _fit(tmp_path, _one_cell(3), algo="linear", estimator=RIDGE, lags=[1, 48])
    assert run["code"] == 3 and "ml_ts_history" in run["stderr"]


def test_only_a_catalog_regressor_is_ever_instantiated(tmp_path):
    run = _fit(tmp_path, _one_cell(21), algo="linear", estimator="os.system", params={"command": "true"})
    assert run["code"] == 5 and "estimator_not_allowed" in run["stderr"]


# ---------------------------------------------------------------------------
# The worker's lifecycle, end to end
# ---------------------------------------------------------------------------

from app.tests.services.test_ml_training import enabled, store, workspace  # noqa: E402,F401


def test_a_forecast_trains_through_the_worker_lifecycle_and_lands_ready(
    db_session, workspace, store, enabled  # noqa: F811
):
    """submit → eager run_training → the real harness → upload → registry.

    The path a Flow node or the studio takes, with nothing stubbed but the
    queue: the row a user polls ends ready, with the forecast's evidence."""

    import polars as pl

    from app.models.tabular import MLModel
    from app.services.tabular_datasets import register_frame
    from app.services.tabular_ml import serialize_model, submit_training

    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Cell CAS load",
        frame=pl.from_pandas(_one_cell(21)),
        source="upload",
    )
    db_session.commit()

    model = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        task="forecasting",
        target=TARGET,
        algo="gradient_boosting",
        spec={"time_column": "ts", "horizon": HORIZON, "backtest_folds": 2},
    )

    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=model.id).one()
    assert row.status == "ready", row.error
    assert row.family == "forecasting" and row.task == "forecasting"
    assert row.spec_json["horizon"] == HORIZON and row.spec_json["shape"] == "single"
    assert row.metrics_json["task"] == "forecasting"
    assert row.metrics_json["primary"]["key"] == "mase"
    assert row.model_uri and row.artifact_bytes
    assert row.runtime_json["fingerprint"]
    assert row.is_champion is True
    card = serialize_model(row)
    assert card["family"] == "forecasting"


def test_a_trained_forecast_answers_on_demand_and_refuses_a_swapped_artifact(
    db_session, workspace, store, enabled, monkeypatch  # noqa: F811
):
    """train → /forecast's service in eager mode → the journal; then tamper.

    The same path the ml-ts serving worker takes (download, verify the code
    file and the artifact against what training recorded, load, answer), with
    the broker hop replaced by eager mode."""

    import polars as pl

    from app.core.config import settings
    from app.models.tabular import MLModel, MLPrediction
    from app.services.ml import forecast_serving
    from app.services.object_store import get_object_store
    from app.services.tabular_datasets import TabularError, register_frame
    from app.services.tabular_ml import submit_training

    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    forecast_serving.reset_cache()
    dataset = register_frame(
        db_session, workspace_id=workspace.id, name="Cell load", frame=pl.from_pandas(_one_cell(21)), source="upload"
    )
    db_session.commit()
    model = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        task="forecasting",
        target=TARGET,
        algo="linear",
        spec={"time_column": "ts", "horizon": HORIZON, "backtest_folds": 2},
    )
    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=model.id).one()
    assert row.status == "ready", row.error
    assert row.metrics_json["artifact"]["code_sha256"]

    first = forecast_serving.request_forecast(db_session, row, horizon=12, level=0.9, explain=True)
    assert first["rows"] == 12 and first["horizon"] == 12 and first["interval_level"] == 0.9
    steps = first["explanation"]["steps"]
    assert len(steps) == 12
    assert all(step["base"] + sum(step["groups"].values()) == pytest.approx(step["pred"], abs=1e-6) for step in steps)
    assert first["cached"] is False and first["served"]["version"] == 1
    point = first["forecast"][0]
    assert point["lower_bound"] < point["pred"] < point["upper_bound"]
    second = forecast_serving.request_forecast(db_session, row)
    assert second["cached"] is True and second["rows"] == HORIZON
    journal = db_session.query(MLPrediction).filter_by(model_id=row.id).all()
    assert len(journal) == 2
    db_session.refresh(row)
    assert row.predict_count == 12 + HORIZON

    with pytest.raises(TabularError) as caught:
        forecast_serving.request_forecast(db_session, row, horizon=10_000)
    assert caught.value.code == "ML_FORECAST_HORIZON_INVALID"

    # Someone rewrites the stored code file: it runs at load, so it is refused.
    store_root = get_object_store()
    code_key = next(key for key in store_root.list_keys(row.model_uri) if key.endswith("ml_forecast_pyfunc.py"))
    local = store / code_key
    local.write_text(local.read_text() + "\n# tampered\n")
    forecast_serving.reset_cache()
    with pytest.raises(TabularError) as caught:
        forecast_serving.request_forecast(db_session, row, horizon=6)
    assert caught.value.code == "ML_ARTIFACT_TAMPERED"


def test_the_flow_node_writes_every_series_forecast_as_a_dataset(
    db_session, workspace, store, enabled, monkeypatch  # noqa: F811
):
    """train (panel) → the ml_forecast_v1 node → a dataset of series × steps.

    The node runs in the general worker and cannot load a forecast, so it
    reserves a dataset row, hands the work to the ml-ts worker (eager here) and
    polls the row. The training node's reference on the wire names the
    training table: it must not be read as future values."""

    import asyncio

    import polars as pl

    from app.core.config import settings
    from app.models.tabular import MLModel, TabularDataset
    from app.services.ml import forecast_serving
    from app.services.skills_registry.wrappers import _ml_forecast_v1
    from app.services.tabular_datasets import read_frame, register_frame
    from app.services.tabular_ml import model_reference, submit_training

    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    forecast_serving.reset_cache()
    cells = _cells(3, 21).drop(columns=["site_code", "region"])
    dataset = register_frame(
        db_session, workspace_id=workspace.id, name="Cells", frame=pl.from_pandas(cells), source="upload"
    )
    db_session.commit()
    model = submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        task="forecasting",
        target=TARGET,
        algo="linear",
        spec={
            "time_column": "ts",
            "horizon": 12,
            "backtest_folds": 2,
            "shape": "panel",
            "series_columns": ["cell_id"],
            "exog": {"technology": "static"},
        },
    )
    db_session.expire_all()
    row = db_session.query(MLModel).filter_by(id=model.id).one()
    assert row.status == "ready", row.error

    upstream = {**model_reference(row), "dataset_id": dataset.id}
    answer = asyncio.run(
        _ml_forecast_v1(
            {
                "model": upstream,
                "_forecast": {"model_slug": row.slug, "horizon": 6, "interval_level": 0.9, "node_id": "fc"},
            },
            {"workspace_id": workspace.id, "run_id": None},
        )
    )
    assert answer["rows"] == 3 * 6
    assert answer["forecast"]["horizon"] == 6 and answer["forecast"]["series"] == 3
    peaks = answer["forecast"]["peaks"]
    assert len(peaks) == 3 and all(peak["upper_bound"] >= peak["pred"] for peak in peaks)
    # The series most likely to cross a line first comes first.
    assert peaks[0]["upper_bound"] == max(peak["upper_bound"] for peak in peaks)

    db_session.expire_all()
    written = db_session.query(TabularDataset).filter_by(id=answer["dataset_id"]).one()
    assert written.status == "ready" and written.produced_by == "ml_forecast_v1"
    assert written.lineage_json["kind"] == "forecast"
    assert written.lineage_json["sources"] == []  # the training table was not taken for the future
    frame = read_frame(written)
    assert frame.columns == ["series", "timestamp", "step", "pred", "lower_bound", "upper_bound"]
    assert sorted(frame["step"].unique().to_list()) == [1, 2, 3, 4, 5, 6]
    assert (frame["lower_bound"] < frame["upper_bound"]).all()


def test_the_flow_node_refuses_an_unknown_model_before_reserving_anything(
    db_session, workspace, store, enabled, monkeypatch  # noqa: F811
):
    import asyncio

    from app.core.config import settings
    from app.models.tabular import TabularDataset
    from app.services.skills_registry.wrappers import _ml_forecast_v1

    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    with pytest.raises(ValueError, match="ML_MODEL_NOT_FOUND"):
        asyncio.run(_ml_forecast_v1({"_forecast": {"model_slug": "nope"}}, {"workspace_id": workspace.id}))
    with pytest.raises(ValueError, match="forecast_config_missing"):
        asyncio.run(_ml_forecast_v1({}, {"workspace_id": workspace.id}))
    assert db_session.query(TabularDataset).filter_by(produced_by="ml_forecast_v1").count() == 0


# ---------------------------------------------------------------------------
# What a forecast leans on
# ---------------------------------------------------------------------------


def _explained(run: dict) -> dict:
    return _ok(run)["metrics"]["explanation"]


def test_a_fit_says_which_families_of_features_carry_the_forecast(recursive, panel, multivariate, direct):
    hourly = _explained(recursive)
    assert hourly["method"] == "shap"
    shares = {entry["group"]: entry["share"] for entry in hourly["groups"]}
    assert set(shares) >= {"lags", "calendar"}
    assert sum(shares.values()) == pytest.approx(1.0, abs=1e-6)
    # The lag profile is the reading an operator wants: which past it repeats.
    assert [entry["lag"] for entry in hourly["lags"]] == [1, 2, 3, 24, 168]
    assert all(item["group"] in {"lags", "calendar"} for item in hourly["features"])

    # A panel's static attribute, another series moving with the target, a
    # covariate known in advance: each is named as its own family.
    assert "static" in {entry["group"] for entry in _explained(panel)["groups"]}
    assert "past" in {entry["group"] for entry in _explained(multivariate)["groups"]}
    with_covariate = _explained(direct)
    assert with_covariate["step"] == 1  # a direct model explains its first step
    assert "future" in {entry["group"] for entry in with_covariate["groups"]}


def test_a_statistical_model_shows_its_own_parameters(ets):
    explanation = _explained(ets)
    assert explanation["method"] == "model"
    assert explanation["parameters"] and all(param["name"] for param in explanation["parameters"])


def test_the_backtest_lists_where_the_actuals_left_the_interval(recursive):
    metrics = _ok(recursive)["metrics"]
    excursions = metrics["excursions"]
    outside = 1 - _scores(_ok(recursive))["coverage"]
    assert excursions["share"] == pytest.approx(outside, abs=1e-9)
    points = excursions["points"]
    assert all(point["gap"] > 0 for point in points)
    assert [point["gap"] for point in points] == sorted((point["gap"] for point in points), reverse=True)
    for point in points:
        assert (point["actual"] > point["upper"]) if point["side"] == "above" else (point["actual"] < point["lower"])


@pytest.mark.parametrize("shape", ["recursive", "direct", "panel", "multivariate"])
def test_each_forecast_step_is_base_plus_its_families_exactly(shape, request):
    """The same explanation serving gives, run on the saved model: whatever the
    shape (one estimator per step, standardized series, a panel), base plus the
    families' contributions is the forecast."""

    import mlflow.pyfunc

    from app.services.ml.forecast_serving import LoadedForecaster, _model_input, explain_forecast

    run = request.getfixturevalue(shape)
    result = _ok(run)
    model_dir = run["root"] / "model"
    meta = json.loads((model_dir / "artifacts" / "meta.json").read_text())
    entry = LoadedForecaster(
        fingerprint="t", pyfunc=mlflow.pyfunc.load_model(str(model_dir)), meta=meta, load_ms=0.0, directory=model_dir
    )
    inputs = []
    if meta["exog_future"]:
        last = pd.Timestamp(result["metrics"]["forecast"]["last_timestamp"])
        inputs = [
            {"timestamp": str(last + pd.Timedelta(hours=step)), **{name: 0.0 for name in meta["exog_future"]}}
            for step in range(1, 7)
        ]
    model_input = _model_input(inputs, meta)
    answered = entry.pyfunc.predict(model_input, params={"horizon": 6}).to_dict(orient="records")
    explanation = explain_forecast(entry, model_input, steps=6, answered=answered)
    assert explanation is not None and len(explanation["steps"]) == 6
    for step in explanation["steps"]:
        assert step["base"] + sum(step["groups"].values()) == pytest.approx(step["pred"], abs=1e-6)
    peak = explanation["peak"]
    assert peak["pred"] == max(row["pred"] for row in answered if row["series"] == explanation["series"])
    assert peak["features"] and abs(peak["features"][0]["contribution"]) >= abs(peak["features"][-1]["contribution"])
