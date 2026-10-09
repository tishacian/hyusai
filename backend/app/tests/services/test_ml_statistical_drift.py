"""Genuine train samples, valid statistical tests and version-isolated windows."""
from datetime import datetime, timedelta
from uuid import uuid4

import pandas as pd
import pytest

from app.models.tabular import MLModel, MLPrediction
from app.resources.ml_drift import build_reference, feature_test, adjust_tests, category_key
from app.services.tabular_monitoring import report, badges_for, data_drift
from app.tests.services.test_tabular_monitoring import model, workspace, _journal  # noqa: F401
from app.tests.services.test_ml_training import _run_harness


def test_ks_detects_shift_without_fabricating_histogram_samples():
    sample = list(range(100))
    reference = build_reference(pd.DataFrame({"x": sample}))["features"]["x"]
    same = feature_test(reference, sample)
    shifted = feature_test(reference, list(range(200, 300)))
    adjust_tests([same, shifted])
    assert same["status"] == "ok" and same["p_value"] == 1
    assert shifted["status"] == "alert" and shifted["statistic"] == 1
    assert shifted["n_reference"] == shifted["n_current"] == 100
    assert feature_test(None, sample)["reason"] == "reference_unavailable"


def test_chi_square_handles_new_categories_but_refuses_sparse_tables():
    reference = build_reference(pd.DataFrame({"x": ["a"] * 50 + ["b"] * 50}))["features"]["x"]
    same = feature_test(reference, ["a"] * 50 + ["b"] * 50)
    changed = feature_test(reference, ["a"] * 20 + ["b"] * 20 + ["new"] * 60)
    sparse = feature_test(reference, ["a"] * 49 + ["b"] * 50 + ["rare"])
    adjust_tests([same, changed, sparse])
    assert same["status"] == "ok" and same["statistic"] == 0
    assert changed["status"] == "alert" and changed["method"] == "chi2"
    assert sparse["status"] == "unknown" and sparse["reason"] == "sparse_categories"
    assert sparse["p_value"] is None
    assert set(reference["counts"]) == {category_key("a"), category_key("b")}


def test_holm_adjustment_preserves_monotonicity_and_ignores_unavailable_tests():
    tests = [{"p_value": p, "status": "unknown"} for p in (.03, .01, None, .04)]
    adjust_tests(tests)
    assert [test.get("p_value_adjusted") for test in tests] == [.06, .03, None, .06]
    assert [test["status"] for test in tests] == ["ok", "watch", "unknown", "ok"]


def test_references_are_bounded_deterministic_and_nonfinite_values_are_excluded():
    frame = pd.DataFrame({"x": list(range(1000)), "text": [f"unique {i}" for i in range(1000)]})
    reference = build_reference(frame)
    assert reference == build_reference(frame)
    assert reference["train_rows"] == 1000
    assert reference["features"]["x"]["n"] == 400
    assert reference["features"]["text"]["reason"] == "high_cardinality"
    assert reference["features"]["text"]["counts"] == {}
    result = feature_test({"kind": "number", "values": list(range(25)), "n": 25},
                          [float("nan"), float("inf"), True, None] + list(range(10)))
    assert result["n_current"] == 10 and result["reason"] == "insufficient_samples"


def test_monitoring_retains_psi_when_old_models_have_no_statistical_reference(model):
    data = data_drift(model, [], None)
    assert all(feature["test"]["reason"] == "reference_unavailable" for feature in data["features"])
    assert all(feature["psi_status"] == "unknown" for feature in data["features"])


def test_monitoring_and_list_badges_do_not_mix_versions_or_starve_quiet_models(db_session, model):
    other = MLModel(id=str(uuid4()), workspace_id=model.workspace_id, name=model.name, slug=model.slug,
                    version=2, task=model.task, target=model.target, algo=model.algo,
                    features=model.features, status="ready", metrics_json={}, signature_json=model.signature_json)
    db_session.add(other)
    model.metrics_json = {**model.metrics_json, "monitoring_reference": build_reference(
        pd.DataFrame({"arpu": list(range(100)), "plan": ["prepaid", "postpaid"] * 50}))}
    db_session.commit()
    for i in range(30):
        _journal(db_session, model, payload={"arpu": 200 + i, "plan": "prepaid"}, score=.5)
    now = datetime.utcnow()
    for i in range(810):
        db_session.add(MLPrediction(workspace_id=model.workspace_id, model_id=model.id,
            served_id=other.id, served_version=2, slug=model.slug, caller="session", row_count=1,
            payload_json=[{"arpu": i % 100}], output_json=[], scores_json={}, created_at=now + timedelta(seconds=i)))
    db_session.commit()
    first = report(db_session, model=model)
    second = report(db_session, model=other)
    assert first["window"]["predictions"] == 30 and first["window"]["served_version"] == 1
    assert second["window"]["predictions"] == 400 and second["window"]["served_version"] == 2
    assert first["data_drift"]["features"][0]["test"]["status"] == "alert"
    assert badges_for(db_session, [model, other])[model.id] == first["badge"] == "alert"


def test_real_fit_records_only_train_rows_as_statistical_reference(tmp_path):
    from sklearn.model_selection import train_test_split

    frame = pd.DataFrame({"x": list(range(120)), "y": [i % 2 for i in range(120)]})
    path = tmp_path / "source.parquet"
    frame.to_parquet(path)
    code, summary, stderr = _run_harness(tmp_path / "run", {
        "data_path": str(path), "model_dir": str(tmp_path / "model"),
        "task": "classification", "target": "y", "features": ["x"],
        "estimator": "sklearn.linear_model.LogisticRegression", "params": {"max_iter": 100},
        "random_state": 42, "test_size": .25, "cv": 0, "importance_rows": 20,
    })
    assert code == 0, stderr
    train, test = train_test_split(frame, test_size=.25, stratify=frame.y, random_state=42)
    reference = summary["metrics"]["monitoring_reference"]
    assert reference["source"] == "train" and reference["train_rows"] == 90
    values = set(reference["features"]["x"]["values"])
    assert values == set(train.x) and not values.intersection(test.x)
