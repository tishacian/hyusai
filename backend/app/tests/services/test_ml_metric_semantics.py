"""Business positive labels and macro F1 agree with reference scorers."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.tree import DecisionTreeClassifier
from skore import EstimatorReport

from app.models.tabular import MLModel
from app.resources import ml_classification_extensions as extensions
from app.resources.ml_train_harness import _classification_metrics, _number
from app.services import ml_comparison, tabular_predict
from app.services.ml.families.tabular import TABULAR


def test_macro_f1_averages_class_f1_including_rare_class():
    x = pd.DataFrame({"x": [0, 0, 0, 1, 1, 1, 2, 2, 2, 2]})
    y = pd.Series([0, 0, 1, 1, 1, 1, 2, 2, 2, 0])
    model = DecisionTreeClassifier(max_depth=2).fit(x, y)
    report = EstimatorReport(model, X_test=x, y_test=y)
    scores = {
        row["key"]: row["value"]
        for row in _classification_metrics(report, model.classes_, curve_points=10)["scores"]
    }
    predicted = model.predict(x)
    assert scores["f1"] == pytest.approx(f1_score(y, predicted, average="macro"), abs=1e-6)
    precision = precision_score(y, predicted, average="macro", zero_division=0)
    recall = recall_score(y, predicted, average="macro", zero_division=0)
    assert scores["f1"] != pytest.approx(2 * precision * recall / (precision + recall), abs=1e-5)


def test_lower_sorted_label_controls_threshold_curves_and_cv():
    rng = np.random.default_rng(1)
    x = pd.DataFrame({"x": rng.normal(size=300)})
    y = pd.Series(np.where(x.x + rng.normal(size=300) > 0.5, "accept", "reject"))
    spec = {"positive_class": "accept", "threshold": "f1"}
    served, context = extensions.fit(
        LogisticRegression(), x, y, spec=spec, seed=1, folds=3, progress=lambda _: None
    )
    assert context["positive"] == "accept" and served.pos_label == "accept"
    probability = served.predict_proba(x)[:, list(served.classes_).index("accept")]
    assert (
        served.predict(x).tolist()
        == np.where(probability >= served.threshold, "accept", "reject").tolist()
    )
    report = EstimatorReport(served, X_test=x, y_test=y, pos_label="accept")
    scores = _classification_metrics(
        report, served.classes_, curve_points=10, positive_class="accept"
    )
    assert dict((row["key"], row["value"]) for row in scores["scores"])["f1"] == pytest.approx(
        f1_score(y, served.predict(x), pos_label="accept"), abs=1e-6
    )
    assert scores["curves"]["baseline"] == pytest.approx((y == "accept").mean(), abs=1e-6)
    measured = []

    def summarize(report, labels):
        result = _classification_metrics(report, labels, curve_points=10, positive_class="accept")
        measured.append({row["key"]: row["value"] for row in result["scores"]})
        return result

    cv = extensions.cross_validation(
        LogisticRegression(),
        x,
        y,
        spec=spec,
        seed=1,
        folds=3,
        progress=lambda _: None,
        summarize=summarize,
        number=_number,
    )
    row = next(row for row in cv["metrics"] if row["key"] == "f1")
    assert row["std"] == pytest.approx(np.std([fold["f1"] for fold in measured], ddof=1), abs=1e-6)


def test_unknown_label_is_refused_and_regression_ignores_hidden_label():
    with pytest.raises(ValueError, match="identify"):
        extensions.positive_label(["a", "b"], {"positive_class": "missing"})
    with pytest.raises(ValueError, match="exactly two"):
        extensions.positive_label([0, 1, 2], {"positive_class": "0"})
    assert extensions.positive_label([False, True], {"positive_class": "false"}) is False
    assert (
        TABULAR.parse_spec({"positive_class": "a"}, task="regression").get("positive_class") is None
    )


def test_comparison_reads_the_original_boolean_class_of_legacy_models(monkeypatch):
    frame = pd.DataFrame({"x": range(10), "target": [False, True] * 5})
    pipeline = DummyClassifier(strategy="constant", constant=True).fit(frame[["x"]], frame.target)
    model = MLModel(
        task="classification", target="target", features=["x"], classes_json=["False", "True"]
    )
    monkeypatch.setattr(
        tabular_predict, "load_pipeline", lambda _: SimpleNamespace(pipeline=pipeline)
    )
    report = ml_comparison._report(model, frame, target="target")
    scores = _classification_metrics(
        report, pipeline.classes_, curve_points=10, positive_class=True
    )
    f1 = next(row["value"] for row in scores["scores"] if row["key"] == "f1")
    assert f1 == pytest.approx(f1_score(frame.target, pipeline.predict(frame[["x"]])), abs=1e-6)
