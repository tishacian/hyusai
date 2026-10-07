"""Acceptance checks for independently delivered tabular extensions together."""
from __future__ import annotations

import json

import mlflow.sklearn
import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import cross_val_score, train_test_split

from app.resources.ml_knob_translation import translate
from app.resources.ml_train_harness import _fold_splitter, _make_pipeline
from app.services.ml.model_structure import inner_pipeline
from app.tests.services.test_ml_training import _manifest_for, _run_harness


@pytest.mark.parametrize("task", ["regression", "classification"])
def test_search_text_postprocessing_and_explanations_use_the_same_model(tmp_path, task):
    rng = np.random.default_rng(42)
    size = 2000 if task == "classification" else 1000
    x = pd.DataFrame({"usage": rng.normal(size=size), "balance": rng.normal(size=size)})
    groups = np.where(x.usage > 0, "north", "south")
    x["ticket"] = [f"Customer requests help for service category {i % 70} in region {groups[i]}" for i in range(size)]
    continuous = 8 * x.usage + 2 * x.balance + rng.normal(scale=2, size=size)
    y = (continuous > 3).astype(int) if task == "classification" else continuous
    path = tmp_path / "dataset.parquet"
    x.assign(target=y, protected_group=groups).to_parquet(path)
    options = {"tuning": "budget", "text_encoder": "minhash", "explain": "pack", "fairness_columns": ["protected_group"]}
    options.update({"calibration": "sigmoid", "threshold": "f1"} if task == "classification" else {"intervals": "conformal"})
    estimator = "sklearn.linear_model." + ("LogisticRegression" if task == "classification" else "Ridge")
    baseline = {"alpha": 1.0, "max_iter": 500}
    manifest = _manifest_for(path, tmp_path, task=task, target="target", features=list(x.columns),
        algo="linear", estimator=estimator, params=translate("linear", task, baseline, random_state=42, forest_leaves=2048),
        spec=options, cv=2, importance_rows=40, tuning={"trials": 5, "budget_s": 30,
            "metric": "roc_auc" if task == "classification" else "r2", "direction": "max", "folds": 3,
            "start": baseline, "space": [{"key": "alpha", "kind": "float", "low": .01, "high": 10, "log": True}],
            "forest_leaves": 2048})
    code, result, stderr = _run_harness(tmp_path / "run", manifest)
    assert code == 0, stderr
    metrics = result["metrics"]
    tuning = metrics["tuning"]
    assert tuning["best"]["score"] >= tuning["start"]["score"]
    assert tuning["elapsed_s"] <= 33
    fitted = mlflow.sklearn.load_model(manifest["model_dir"])
    pipeline = inner_pipeline(fitted)
    assert type(pipeline.named_steps["tablevectorizer"].high_cardinality).__name__ == "MinHashEncoder"
    assert "protected_group" not in result["metrics"]["columns"]["used"]
    explanation = metrics["explain"]
    assert explanation["error_tree"]["rules"] and explanation["surrogate"]["rules"]
    assert explanation["pdp"] and all("error" not in row for row in explanation["pdp"])
    assert sum(row["n"] for row in explanation["fairness"][0]["groups"]) == metrics["rows"]["test"]
    assert explanation["elapsed_s"] <= 60.5 and len(json.dumps(explanation).encode()) < 200_000
    if task == "classification":
        assert type(fitted).__name__ == "FixedThresholdClassifier"
        assert fitted.threshold == metrics["decision"]["threshold"]
        assert metrics["calibration"]["calibration_rows"] == 300
        assert metrics["cv"]["mean"] is not None
    else:
        assert len(metrics["intervals"]["levels"]) == 3
        # Recompute the baseline with the explicitly selected encoder: tuning
        # must not silently compare StringEncoder and fit MinHash afterwards.
        x_train, _, y_train, _ = train_test_split(x, y, test_size=.25, random_state=42)
        base = _make_pipeline(estimator, manifest["params"], spec=options, seed=42)
        expected = cross_val_score(base, x_train, y_train, scoring="r2", cv=_fold_splitter(3, task, y_train), n_jobs=1).mean()
        assert tuning["start"]["score"] == pytest.approx(expected, abs=1e-8)
    json.dumps(result, allow_nan=False)
