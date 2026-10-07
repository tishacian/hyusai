"""Bounded explanations describe the served model without changing training."""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import pytest
from sklearn.compose import ColumnTransformer
from sklearn.datasets import make_classification, make_regression
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.frozen import FrozenEstimator
from sklearn.model_selection import FixedThresholdClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.resources import ml_explanation_extensions as explain
from app.resources import ml_train_harness as harness
from app.services.ml.model_structure import inner_pipeline
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_training import dataset, enabled, store, workspace  # noqa: F401


def classification(rows=800):
    x, y = make_classification(n_samples=rows, n_features=4, n_informative=3, n_redundant=0, random_state=42)
    frame, target = pd.DataFrame(x, columns=list("abcd")), pd.Series(y)
    model = make_pipeline(StandardScaler(), RandomForestClassifier(n_estimators=15, max_depth=4, n_jobs=1, random_state=42)).fit(frame, target)
    return model, frame, target


def test_error_tree_and_surrogate_are_deterministic():
    model, x, y = classification()
    a = explain.error_tree(model, x, y, task="classification", seed=42)
    b = explain.error_tree(model, x, y, task="classification", seed=42)
    assert a == b and len(a["rules"]) <= 5
    assert all(row["rows"] >= 20 and len(row["rule"]) <= 3 for row in a["rules"])
    first = explain.surrogate(model, x, task="classification", seed=42)
    assert first == explain.surrogate(model, x, task="classification", seed=42)
    assert 0 <= first["fidelity"] <= 1
    assert first["train_rows"] + first["validation_rows"] == len(x)
    assert first["validation_rows"] > 0


def test_regression_error_rules_and_fidelity_have_numeric_predictions():
    x, y = make_regression(n_samples=250, n_features=3, noise=10, random_state=4)
    x, y = pd.DataFrame(x, columns=list("abc")), pd.Series(y)
    model = make_pipeline(StandardScaler(), RandomForestRegressor(n_estimators=10, max_depth=4, random_state=42)).fit(x, y)
    assert explain.error_tree(model, x, y, task="regression", seed=42)["global_error"] > 0
    summary = explain.surrogate(model, x, task="regression", seed=42)
    assert 0 <= summary["fidelity"] <= 1
    assert all(isinstance(row["prediction"], (float, int)) for row in summary["rules"])


def test_partial_dependence_numeric_and_categorical_keep_raw_feature_names():
    model, x, y = classification()
    numeric = explain.partial_effect(model, x, "a", task="classification", seed=42)
    assert len(numeric["grid"]) == len(numeric["average"]) <= 20
    assert len(numeric["ice"]) == 30
    assert all(len(row) == len(numeric["grid"]) for row in numeric["ice"])
    x["region"] = np.where(x.a > 0, "North", "South")
    transform = ColumnTransformer([("numeric", StandardScaler(), list("abcd")), ("region", OneHotEncoder(), ["region"])])
    categorical_model = make_pipeline(transform, RandomForestClassifier(n_estimators=10, random_state=42)).fit(x, y)
    categorical = explain.partial_effect(categorical_model, x, "region", task="classification", seed=42)
    assert categorical["kind"] == "categorical"
    assert set(categorical["grid"]) == {"North", "South"}
    assert len(categorical["average"]) == 2 and len(categorical["ice"]) == 30
    assert all(len(row) == 2 for row in categorical["ice"])


def test_wrapped_model_is_unwrapped_only_for_structural_features():
    from sklearn.calibration import CalibratedClassifierCV
    model, x, y = classification()
    calibrated = CalibratedClassifierCV(FrozenEstimator(model), method="sigmoid").fit(x, y)
    served = FixedThresholdClassifier(FrozenEstimator(calibrated), threshold=0.2, pos_label=1).fit(x, y)
    assert inner_pipeline(served) is model and explain.inner_pipeline(served) is model
    errors = explain.error_tree(served, x, y, task="classification", seed=42)
    assert errors["global_error"] == pytest.approx(np.mean(served.predict(x) != y), abs=1e-6)
    assert explain.surrogate(served, x, task="classification", seed=42)["fidelity"] >= 0
    assert explain.partial_effect(served, x, "a", task="classification", seed=42)["average"]


class _BiasedClassifier:
    classes_ = [0, 1]
    def predict(self, x):
        return x["prediction"].to_numpy()


def test_planted_fairness_gap_excludes_tiny_groups_and_reports_rates():
    # Two supported groups with selection rates .8/.4; a tiny all-negative
    # third group must not turn the measured ratio into zero.
    x = pd.DataFrame({"prediction": [1] * 80 + [0] * 20 + [1] * 40 + [0] * 60 + [0] * 5})
    y = pd.Series(([1, 0] * 100) + [0] * 5)
    groups = pd.DataFrame({"protected": ["A"] * 100 + ["B"] * 100 + ["tiny"] * 5})
    result = explain.fairness(_BiasedClassifier(), x, y, groups, task="classification")[0]
    assert result["selection_ratio"] == 0.5 and result["signal"] is True
    assert result["equalized_odds_diff"] == 0.4
    assert next(row for row in result["groups"] if row["group"] == "tiny")["low_support"] is True


def test_regression_fairness_measures_bias_and_mae_disparity():
    x = pd.DataFrame({"prediction": [1.0] * 50 + [4.0] * 50})
    groups = pd.DataFrame({"group": ["A"] * 50 + ["B"] * 50})
    result = explain.fairness(_BiasedClassifier(), x, pd.Series([0.0] * 100), groups, task="regression")[0]
    assert result["mae_gap_ratio"] == 1.2
    assert [row["bias"] for row in result["groups"]] == [1.0, 4.0]


def test_tiny_budget_interrupts_work_and_marks_remaining_sections(monkeypatch):
    model, x, y = classification(100)
    def slow(*args, **kwargs):
        # PyDLL holds the GIL in native code: a Python SIGALRM handler cannot
        # interrupt this, while the supervising process can terminate it.
        import ctypes
        ctypes.PyDLL(None).sleep(2)
        return {}
    monkeypatch.setattr(explain, "error_tree", slow)
    started = time.monotonic()
    result = explain.pack(model, x, y, task="classification", seed=42,
                          importances=[{"feature": "a"}], budget_s=0.01)
    assert time.monotonic() - started < 0.2
    assert result["error_tree"] == {"error": "budget"}
    assert result["surrogate"] == {"error": "budget"}
    assert result["pdp"][0]["error"] == "budget"


def test_pack_caps_rows_curves_and_serialized_size(monkeypatch):
    model, x, y = classification(5200)
    result = explain.pack(model, x, y, task="classification", seed=42,
                          importances=[{"feature": name} for name in x.columns])
    assert result["rows"] == 5000 and len(result["pdp"]) == 4
    assert len(json.dumps(result, allow_nan=False).encode()) <= 200_000
    assert all(len(item["ice"]) <= 30 for item in result["pdp"])
    monkeypatch.setattr(explain, "EXPLAIN_MAX_BYTES", 10)
    assert explain.pack(model, x.head(100), y.head(100), task="classification", seed=42, importances=[]) == {"error": "too_large"}


@pytest.mark.parametrize("columns", [["missing"], ["arpu"], ["msisdn"], ["churn"], ["region", "plan", "support_tickets", "tenure_months"]])
def test_invalid_fairness_columns_are_a_field_refusal(dataset, enabled, columns):
    from app.services.tabular_ml import validate_training
    with pytest.raises(TabularError) as raised:
        validate_training(dataset, task="classification", target="churn", spec={"explain": "pack", "fairness_columns": columns})
    assert raised.value.code == "ML_SPEC_INVALID" and raised.value.details["field"] == "fairness_columns"


def test_low_cardinality_numeric_columns_are_valid_groups(dataset, enabled):
    from app.services.tabular_ml import validate_training
    spec = validate_training(dataset, task="classification", target="churn", features=["arpu"],
                             spec={"explain": "pack", "fairness_columns": ["region", "support_tickets"]})
    assert spec.features == ["arpu"] and spec.spec["fairness_columns"] == ["region", "support_tickets"]


def test_harness_reads_fairness_columns_outside_features_and_persists_pack(tmp_path):
    model, x, y = classification(400)
    frame = x.assign(group=np.where(x.a > 0, "North", "South"), target=y)
    # The source's duplicate index labels must not duplicate protected rows.
    frame.index = [0] * len(frame)
    parquet = tmp_path / "data.parquet"
    frame.to_parquet(parquet)
    manifest = {"data_path": str(parquet), "model_dir": str(tmp_path / "model"), "target": "target", "features": list(x.columns),
                "task": "classification", "estimator": "sklearn.ensemble.RandomForestClassifier",
                "params": {"n_estimators": 10, "max_depth": 4, "random_state": 42, "n_jobs": 1},
                "spec": {"explain": "pack", "fairness_columns": ["group"]}, "importance_rows": 40,
                "progress_path": str(tmp_path / "progress")}
    source, output = tmp_path / "manifest.json", tmp_path / "result.json"
    source.write_text(json.dumps(manifest))
    assert harness.main(["harness", str(source), str(output)]) == 0
    result = json.loads(output.read_text())
    pack = result["metrics"]["explain"]
    assert pack["rows"] == 100 and "error" not in pack["error_tree"]
    assert pack["fairness"][0]["column"] == "group"
    assert sum(row["n"] for row in pack["fairness"][0]["groups"]) == 100
    assert "group" not in [field["name"] for field in result["signature"]["inputs"]]
    assert "explaining" in (tmp_path / "progress").read_text()


def test_timeout_preserves_completed_sections(monkeypatch):
    model, x, y = classification(100)
    monkeypatch.setattr(explain, "error_tree", lambda *args, **kwargs: {"rules": [], "rows": len(x)})
    def native(*args, **kwargs):
        import ctypes
        ctypes.PyDLL(None).sleep(2)
        return {}
    monkeypatch.setattr(explain, "surrogate", native)
    result = explain.pack(model, x, y, task="classification", seed=42, importances=[{"feature": "a"}], budget_s=0.1)
    assert result["error_tree"] == {"rules": [], "rows": len(x)}
    assert result["surrogate"] == {"error": "budget"}
    assert result["elapsed_s"] < 0.3
