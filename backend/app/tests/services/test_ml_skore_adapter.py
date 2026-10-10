"""Skore's public output boundary preserves the UI/API metric contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_classification, make_regression
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, log_loss, mean_absolute_error
from sklearn.model_selection import cross_val_score, train_test_split
from skore import ComparisonReport, CrossValidationReport, EstimatorReport

from app.resources import ml_skore_adapter as adapter
from app.resources import ml_train_harness as harness


@pytest.fixture(scope="module")
def classifiers():
    x, y = make_classification(n_samples=120, n_features=5, random_state=42)
    train, test, yt, yv = train_test_split(x, y, random_state=42, stratify=y)
    models = [LogisticRegression(C=c).fit(train, yt) for c in (1, 0.1)]
    reports = [EstimatorReport(model, X_test=test, y_test=yv, pos_label=1) for model in models]
    return models, reports, test, yv


def test_estimator_matches_reference_scores_and_harness_contract(classifiers):
    models, reports, x, y = classifiers
    actual = adapter.estimator_metrics(reports[0].metrics.summarize())
    assert actual["accuracy"] == pytest.approx(accuracy_score(y, models[0].predict(x)), abs=1e-6)
    assert actual["log_loss"] == pytest.approx(log_loss(y, models[0].predict_proba(x)), abs=1e-6)
    assert actual == harness._summary_table(reports[0].metrics.summarize())
    assert "default_score" not in actual
    json.dumps(actual, allow_nan=False)


def test_comparison_keeps_model_ids_and_full_precision(classifiers):
    models, reports, x, y = classifiers
    rows = adapter.comparison_metrics(
        ComparisonReport({"v5": reports[0], "v8": reports[1]}).metrics.summarize(),
        names={"model-a": "v5", "model-b": "v8"},
    )
    scores = {row["key"]: row for row in rows}
    assert scores["log_loss"]["model-b"] == pytest.approx(
        log_loss(y, models[1].predict_proba(x)), abs=1e-12
    )
    assert all(set(row) == {"key", "model-a", "model-b"} for row in rows)
    assert not any(row["key"].endswith("_time") for row in rows)
    assert "default_score" not in scores
    json.dumps(rows, allow_nan=False)


def test_cv_matches_independent_folds_and_preserves_percent_mape():
    x, y = make_regression(n_samples=60, n_features=3, noise=2, random_state=42)
    report = CrossValidationReport(Ridge(), x, y, splitter=3, n_jobs=1)
    rows = adapter.cross_validation_metrics(report.metrics.summarize(), keys={"r2", "mape"})
    scores = {row["key"]: row for row in rows}
    expected = cross_val_score(Ridge(), x, y, cv=3, scoring="r2")
    assert scores["r2"]["mean"] == pytest.approx(expected.mean(), abs=1e-6)
    # Skore's std is the sample standard deviation across splits.
    assert scores["r2"]["std"] == pytest.approx(expected.std(ddof=1), abs=1e-6)
    raw = report.metrics.summarize().frame().loc["mape"].iloc[0]
    assert scores["mape"]["mean"] == round(round(raw, 6) * 100, 6)
    json.dumps(rows, allow_nan=False)


def test_regression_and_multiclass_names_are_machine_readable():
    x, y = make_regression(n_samples=60, n_features=3, noise=2, random_state=42)
    model = Ridge().fit(x, y)
    values = adapter.estimator_metrics(
        EstimatorReport(model, X_test=x, y_test=y).metrics.summarize()
    )
    assert values["mae"] == pytest.approx(mean_absolute_error(y, model.predict(x)), abs=1e-6)
    x, y = make_classification(
        n_samples=90, n_features=5, n_informative=3, n_redundant=0, n_classes=3, random_state=42
    )
    report = EstimatorReport(LogisticRegression().fit(x, y), X_test=x, y_test=y)
    values = adapter.estimator_metrics(report.metrics.summarize())
    assert {
        "accuracy",
        "precision_avg_macro",
        "recall_avg_macro",
        "recall_0",
        "log_loss",
    } <= values.keys()


def display(frame):
    return SimpleNamespace(frame=lambda **kwargs: frame)


@pytest.mark.parametrize(
    "frame",
    [
        pd.Series([0.1, 0.2], index=["accuracy", "accuracy"]),
        pd.Series([0.1], index=pd.MultiIndex.from_tuples([("accuracy", "test")])),
        pd.DataFrame({"first": [0.1], "second": [0.9]}, index=["accuracy"]),
    ],
)
def test_ambiguous_estimator_output_is_not_silently_truncated(frame):
    with pytest.raises(ValueError):
        adapter.estimator_metrics(display(frame))


def test_one_column_frames_and_failed_metrics_remain_json_safe():
    frame = pd.DataFrame(
        {"model": [0.12345678, np.nan, np.inf, -np.inf]},
        index=["accuracy", "custom", "fit_time", "predict_time"],
    )
    assert adapter.estimator_metrics(display(frame)) == {
        "accuracy": 0.123457,
        "custom": None,
        "fit_time": None,
        "predict_time": None,
    }
    frame = pd.DataFrame({"v1": [np.nan], "v2": [0.123456789]}, index=["custom"])
    result = adapter.comparison_metrics(display(frame), names={"a": "v1", "b": "v2"})
    assert result == [{"key": "custom", "a": None, "b": 0.123456789}]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "columns",
    [
        {"a_mean": [0.5], "b_std": [0.1]},
        {"a_mean": [0.5], "a_std": [0.1], "b_mean": [0.7], "b_std": [0.1]},
    ],
)
def test_cv_does_not_pair_statistics_of_different_estimators(columns):
    with pytest.raises(ValueError, match="matching pair"):
        adapter.cross_validation_metrics(display(pd.DataFrame(columns, index=["r2"])), keys={"r2"})


def test_comparison_does_not_return_a_partial_model_column():
    with pytest.raises(ValueError, match="requested models"):
        adapter.comparison_metrics(
            display(pd.DataFrame({"v1": [0.5]}, index=["r2"])), names={"a": "v1", "b": "v2"}
        )
