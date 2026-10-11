"""Actual fitted choices, leakage boundaries and reloadable skrub evidence."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from sklearn.base import clone
from sklearn.model_selection import KFold, train_test_split

from app.resources import ml_preprocessing as preparation
from app.resources import ml_train_harness as harness


def _mixed(rows=120):
    rng = np.random.default_rng(29)
    frame = pd.DataFrame(
        {
            "number": rng.normal(size=rows),
            "date": pd.date_range("2024-01-01", periods=rows),
            "category": ["private_category_a", "private_category_b"] * (rows // 2),
            "text": [f"private_free_text_reference_{index:04d}" for index in range(rows)],
            "constant": [3.0] * rows,
            "all_missing": [None] * rows,
            "presence": [1.0, np.nan] * (rows // 2),
        }
    )
    return frame, (frame.number > 0).astype(int)


def _pipeline(encoder="auto", *, tuning=False):
    return harness._make_pipeline(
        "sklearn.linear_model.LogisticRegression",
        {"max_iter": 200, "random_state": 31},
        spec={"text_encoder": encoder},
        seed=31,
        tuning=tuning,
    )


@pytest.mark.parametrize("encoder", ["auto", "string", "minhash"])
def test_fitted_summary_roundtrips_without_rows_or_category_values(encoder, tmp_path):
    import mlflow.sklearn

    frame, target = _mixed()
    pipeline = _pipeline(encoder).fit(frame, target)
    summary = preparation.record_fitted(pipeline, frame, fit_time_ms=12.3)
    by_name = {entry["name"]: entry for entry in summary["columns"]}
    assert by_name["constant"]["reason"] == "constant"
    assert by_name["all_missing"]["reason"] == "all_missing"
    assert by_name["presence"]["excluded"] is False
    assert by_name["date"]["kind"] == "datetime"
    assert by_name["category"]["kind"] == "low_cardinality"
    assert any(
        ("MinHashEncoder" if encoder == "minhash" else "StringEncoder") in entry
        for entry in by_name["text"]["transformers"]
    )
    assert summary["input_count"] == 7
    assert summary["retained_count"] == 5
    assert summary["output_count"] == pipeline.steps[-1][1].n_features_in_
    assert summary["fit_time_ms"] == 12.3
    assert summary["preprocessing_time_ms"] is None
    serialized = json.dumps(summary, allow_nan=False)
    assert "private_category" not in serialized
    assert "private_free_text" not in serialized
    assert "2024-01" not in serialized
    path = tmp_path / "model"
    mlflow.sklearn.save_model(
        pipeline,
        path=path,
        serialization_format="skops",
        skops_trusted_types=harness._trusted_types(pipeline),
        pip_requirements=[],
    )
    loaded = mlflow.sklearn.load_model(path)
    assert preparation.describe(loaded) == summary
    np.testing.assert_allclose(pipeline.predict_proba(frame), loaded.predict_proba(frame))


@pytest.mark.parametrize("tuning", [False, True])
def test_constant_selection_is_relearned_in_each_fold(tuning):
    # In fold 1 the sole exceptional value is held out. A pre-CV selection
    # would retain this column in both fits and fail this boundary assertion.
    frame = pd.DataFrame({"signal": np.arange(24.0), "fold_only": [9.0] + [1.0] * 23})
    target = pd.Series([0, 1] * 12)
    base = _pipeline(tuning=tuning)
    retained = []
    for train, validation in KFold(2).split(frame):
        pipeline = clone(base).fit(frame.iloc[train], target.iloc[train])
        retained.append(preparation.learned_columns(pipeline)[0])
        assert len(pipeline.predict(frame.iloc[validation])) == len(validation)
    assert "fold_only" not in retained[0]
    assert "fold_only" in retained[1]
    assert not hasattr(base.named_steps["tablevectorizer"], "feature_names_in_")


def test_automatic_text_encoding_repeats_with_the_run_seed():
    frame, target = _mixed()
    first, second = _pipeline().fit(frame, target), _pipeline().fit(frame, target)
    np.testing.assert_allclose(first.predict_proba(frame), second.predict_proba(frame), atol=1e-12)


def test_reserved_test_changes_do_not_change_fitted_selection_or_serving(tmp_path):
    import mlflow.sklearn

    rows = 100
    frame = pd.DataFrame(
        {
            "signal": np.sin(np.arange(rows)),
            "test_only": np.ones(rows),
            "all_missing": [None] * rows,
            "target": [0, 1] * (rows // 2),
        }
    )
    _, test = train_test_split(frame.index, stratify=frame.target, random_state=31)
    summaries, models = [], []
    for variant in (0, 1):
        changed = frame.copy()
        if variant:
            changed.loc[test, "test_only"] = np.arange(len(test)) + 100
        directory = tmp_path / str(variant)
        directory.mkdir()
        data_path = directory / "data.parquet"
        changed.to_parquet(data_path)
        manifest = {
            "data_path": str(data_path),
            "model_dir": str(directory / "model"),
            "target": "target",
            "features": ["signal", "test_only", "all_missing"],
            "task": "classification",
            "estimator": "sklearn.linear_model.LogisticRegression",
            "params": {"random_state": 31},
            "random_state": 31,
            "importance_rows": 10,
        }
        source, result = directory / "manifest.json", directory / "result.json"
        source.write_text(json.dumps(manifest))
        assert harness.main(["harness", str(source), str(result)]) == 0
        summaries.append(json.loads(result.read_text()))
        models.append(mlflow.sklearn.load_model(directory / "model"))
        persisted = json.loads((directory / "model" / "preprocessing.json").read_text())
        assert persisted == summaries[-1]["metrics"]["preprocessing"]
        assert preparation.describe(models[-1]) == persisted
    for summary in summaries:
        assert summary["metrics"]["columns"] == {
            "used": ["signal"],
            "dropped": [
                {"name": "test_only", "reason": "constant"},
                {"name": "all_missing", "reason": "all_missing"},
            ],
        }
        assert {entry["name"] for entry in summary["signature"]["inputs"]} == {
            "signal",
            "test_only",
            "all_missing",
        }
    left, right = (dict(summary["metrics"]["preprocessing"]) for summary in summaries)
    left.pop("fit_time_ms")
    right.pop("fit_time_ms")
    assert left == right
    np.testing.assert_allclose(
        models[0].predict_proba(frame.drop(columns="target")),
        models[1].predict_proba(frame.drop(columns="target")),
    )


def test_preprocessing_evidence_is_bounded_for_wide_data():
    frame = pd.DataFrame({f"column_{index}": np.arange(20) + index for index in range(100)})
    pipeline = _pipeline().fit(frame, [0, 1] * 10)
    summary = preparation.record_fitted(pipeline, frame, fit_time_ms=5)
    assert summary["input_count"] == 100
    assert summary["truncated"] is True
    assert len(summary["columns"]) == preparation.MAX_COLUMNS
    assert len(json.dumps(summary, ensure_ascii=False).encode()) <= preparation.MAX_BYTES


def test_preprocessing_summary_unwraps_calibrated_threshold_model_after_reload():
    import skops.io as sio

    rng = np.random.default_rng(13)
    frame = pd.DataFrame({"number": rng.normal(size=1600), "constant": [1.0] * 1600})
    target = (frame.number + rng.normal(scale=0.5, size=1600) > 0).astype(int)
    model, context = harness._classification_extensions().fit(
        _pipeline(),
        frame,
        target,
        spec={"calibration": "sigmoid", "threshold": "f1"},
        seed=31,
        folds=2,
        progress=lambda step: None,
    )
    assert "calibration" in context
    summary = preparation.record_fitted(
        model,
        frame,
        fit_time_ms=5,
        fit_rows=context["calibration"]["fit_rows"],
    )
    restored = sio.loads(sio.dumps(model), trusted=harness._trusted_types(model))
    assert summary["fit_rows"] == 1280
    assert summary["retained_count"] == 1
    assert preparation.describe(restored) == summary
    np.testing.assert_allclose(
        model.predict_proba(frame.head()), restored.predict_proba(frame.head())
    )
