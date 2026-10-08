"""The served classifier owns its calibration and decision, including exports."""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_classification
from sklearn.ensemble import RandomForestClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.model_selection import FixedThresholdClassifier, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.resources import ml_classification_extensions as extension
from app.resources import ml_train_harness as harness
from app.services.ml.model_structure import inner_pipeline


def data(rows=6000, classes=2):
    x, y = make_classification(n_samples=rows, n_features=8, n_informative=5, n_redundant=1,
                               n_classes=classes, weights=[0.8, 0.2] if classes == 2 else None,
                               class_sep=1.5, random_state=42)
    return pd.DataFrame(x, columns=[f"x{i}" for i in range(x.shape[1])]), pd.Series(y)


def pipeline():
    return make_pipeline(StandardScaler(), RandomForestClassifier(n_estimators=25, max_depth=5,
                                                                  random_state=42, n_jobs=1))


def fit(x, y, **spec):
    return extension.fit(pipeline(), x, y, spec=spec, seed=42, folds=3, progress=lambda _: None)


def test_probability_calibration_improves_reference_and_is_measured_on_holdout():
    x, y = data()
    x_train, x_test, y_train, y_test = train_test_split(x, y, stratify=y, random_state=42)
    model, context = fit(x_train, y_train, calibration="sigmoid", threshold="f1")
    metrics = extension.evaluate(model, context, x_test, y_test, number=harness._number)
    cal = metrics["calibration"]
    assert cal["after"]["brier_score"] < cal["before"]["brier_score"]
    assert cal["fit_rows"] + cal["calibration_rows"] == len(x_train)
    assert 1 <= len(cal["after"]["curve"]) <= 10
    assert metrics["decision"]["source"] == "calibration"
    assert inner_pipeline(model) is context["base"]
    assert len(json.dumps(metrics, allow_nan=False)) < 8000


@pytest.mark.parametrize("method", ["sigmoid", "auto", "isotonic"])
def test_small_calibration_split_keeps_every_train_row_and_warns(method):
    x, y = data(400)
    model, context = fit(x, y, calibration=method)
    assert "calibration" not in context
    assert context["warnings"] == [{"code": "ML_CALIBRATION_TOO_FEW"}]
    assert model is context["base"]


def test_calibration_missing_a_rare_class_keeps_the_full_training_fit():
    x, _ = data(1000)
    y = pd.Series([0] * 998 + [1] * 2)
    model, context = fit(x, y, calibration="sigmoid")
    assert "calibration" not in context
    assert context["warnings"] == [{"code": "ML_CALIBRATION_TOO_FEW"}]
    assert model is context["base"]
    assert list(model.classes_) == [0, 1]


@pytest.mark.parametrize("criterion", ["f1", "youden"])
@pytest.mark.parametrize("calibration", ["off", "sigmoid"])
def test_threshold_selection_cannot_read_the_holdout(monkeypatch, criterion, calibration):
    x, y = data(2000)
    x_train, x_test, y_train, y_test = train_test_split(x, y, stratify=y, random_state=42)
    real = extension._threshold
    seen = []
    def checked(truth, probability, criterion, positive):
        assert set(truth.index).isdisjoint(x_test.index)
        seen.extend(truth.index)
        return real(truth, probability, criterion, positive)
    monkeypatch.setattr(extension, "_threshold", checked)
    model, context = fit(x_train, y_train, calibration=calibration, threshold=criterion)
    assert seen
    assert context["decision"]["source"] == ("calibration" if calibration != "off" else "cross_validation")
    assert 0 <= model.threshold <= 1


def test_multiclass_calibration_has_no_binary_curve_or_threshold():
    x, y = data(1600, classes=3)
    model, context = fit(x, y, calibration="auto", threshold="youden")
    metrics = extension.evaluate(model, context, x.head(50), y.head(50), number=harness._number)
    assert metrics["calibration"]["method"] == "sigmoid"
    assert metrics["calibration"]["after"]["brier_score"] >= 0
    assert "curve" not in metrics["calibration"]["after"]
    assert "decision" not in metrics
    assert {"code": "ML_THRESHOLD_BINARY_ONLY"} in metrics["warnings"]


def test_cross_validation_refits_the_extensions_on_each_fold(monkeypatch):
    x, y = data(500)
    real = extension.fit
    seen = []
    def checked(model, train, truth, **kwargs):
        seen.append(set(train.index))
        return real(model, train, truth, **kwargs)
    monkeypatch.setattr(extension, "fit", checked)
    result = extension.cross_validation(pipeline(), x, y, spec={"threshold": "f1"}, seed=42,
        folds=2, progress=lambda _: None, number=harness._number,
        summarize=lambda report, labels: harness._classification_metrics(report, labels, curve_points=20))
    assert len(seen) == 2 and seen[0].isdisjoint(seen[1])
    assert result["folds"] == 2 and result["mean"] is not None


@pytest.mark.parametrize("calibration", ["sigmoid", "isotonic"])
def test_harness_skops_and_mlflow_roundtrip_preserve_decision(tmp_path, calibration):
    import mlflow.sklearn
    import skops.io as sio
    x, y = data(2000)
    parquet = tmp_path / "data.parquet"
    x.assign(target=y).to_parquet(parquet)
    manifest = {"data_path": str(parquet), "model_dir": str(tmp_path / "model"), "target": "target",
                "features": list(x.columns), "task": "classification", "estimator": "sklearn.ensemble.RandomForestClassifier",
                "params": {"n_estimators": 25, "max_depth": 5, "random_state": 42, "n_jobs": 1},
                "spec": {"calibration": calibration, "threshold": "f1"}, "random_state": 42,
                "importance_rows": 50, "cv": 2, "progress_path": str(tmp_path / "progress")}
    source, result = tmp_path / "manifest.json", tmp_path / "result.json"
    source.write_text(json.dumps(manifest))
    assert harness.main(["harness", str(source), str(result)]) == 0
    summary = json.loads(result.read_text())
    model = mlflow.sklearn.load_model(str(tmp_path / "model"))
    assert isinstance(model, FixedThresholdClassifier)
    assert model.threshold == pytest.approx(summary["metrics"]["decision"]["threshold"])
    restored = sio.loads(sio.dumps(model), trusted=harness._trusted_types(model))
    np.testing.assert_array_equal(restored.predict(x.head(50)), model.predict(x.head(50)))
    np.testing.assert_allclose(restored.predict_proba(x.head(50)), model.predict_proba(x.head(50)))
    assert summary["metrics"]["cv"]["mean"] is not None
    assert summary["metrics"]["importances"]
    scores = {entry["key"]: entry["value"] for entry in summary["metrics"]["scores"]}
    assert scores["precision"] == pytest.approx(summary["metrics"]["decision"]["tuned_metrics"]["precision"])
    assert "calibrating" in (tmp_path / "progress").read_text()


def test_classification_fields_are_removed_when_target_becomes_regression():
    from app.services.ml.families.tabular import TABULAR
    warnings = []
    assert TABULAR.parse_spec({"calibration": "sigmoid", "threshold": "f1"}, task="regression", warnings=warnings) == {"intervals": "off", "tuning": "off", "explain": "off"}
    assert len(warnings) == 2
    assert TABULAR.parse_spec({}, task="classification") == {"calibration": "off", "threshold": "default", "tuning": "off", "explain": "off"}


def test_wrapped_serving_explanation_and_comparison_use_outer_model(monkeypatch):
    from app.services import ml_comparison, tabular_predict
    from app.models.tabular import MLModel
    x, y = data(1600)
    calibrated, _ = fit(x, y, calibration="sigmoid", threshold="f1")
    plain = pipeline().fit(x, y)
    model = MLModel(id="calibrated", task="classification", target="target", classes_json=["0", "1"],
                    features=list(x.columns), metrics_json={})
    loaded = SimpleNamespace(pipeline=calibrated, classes=["0", "1"])
    assert tabular_predict._classes_of(model, calibrated) == ["0", "1"]
    fields = [{"name": name, "type": "double", "kind": "number", "default": 0.0} for name in x.columns]
    row = x.iloc[0].to_dict()
    pred, proba = tabular_predict._predict_frame(loaded, model, x.head(1))
    answer = tabular_predict._rows_from(model, ["0", "1"], "1", pred, proba)[0]
    effects = tabular_predict.explain_row(loaded, model, fields, row, base=answer, classes=["0", "1"], positive="1")
    assert effects
    selected = [calibrated]
    monkeypatch.setattr(tabular_predict, "load_pipeline", lambda _: SimpleNamespace(pipeline=selected[0]))
    report_cal = ml_comparison._report(model, x.assign(target=y).head(100), target="target")
    selected[0] = plain
    report_plain = ml_comparison._report(model, x.assign(target=y).head(100), target="target")
    assert report_cal.estimator is calibrated
    assert report_plain.estimator is plain
    assert report_cal.metrics.summarize().frame().shape == report_plain.metrics.summarize().frame().shape


def test_portable_threshold_predicts_positive_below_half():
    from sklearn.dummy import DummyClassifier
    x = pd.DataFrame({"x": range(10)})
    y = pd.Series([0] * 6 + [1] * 4)
    base = DummyClassifier(strategy="prior").fit(x, y)
    model = FixedThresholdClassifier(FrozenEstimator(base), threshold=0.37, pos_label=1).fit(x, y)
    assert model.predict_proba(x)[0, 1] == 0.4
    assert model.predict(x)[0] == 1
    from app.services.tabular_predict import _rows_from
    answer = _rows_from(SimpleNamespace(task="classification"), ["0", "1"], "1", model.predict(x), model.predict_proba(x))[0]
    assert answer["prediction"] == "1" and answer["score"] == 0.4 and answer["confidence"] == 0.4


def test_auto_calibration_uses_isotonic_at_one_thousand_rows():
    x, y = data(5000)
    _, context = fit(x, y, calibration="auto")
    assert context["calibration"] == {"method": "isotonic", "fit_rows": 4000, "calibration_rows": 1000}
