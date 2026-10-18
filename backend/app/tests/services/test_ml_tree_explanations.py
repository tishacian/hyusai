"""TreeSHAP per prediction: exactness, grouping, fallbacks and privacy (M5).

Every model here is fitted by the **production harness** and loaded through
the serving path, because what has to hold is a property of the pipeline the
platform actually ships: ``base + Σ contributions`` equals the served model's
output in the space the answer names, and one input field stays one
contribution however many columns its encoder made of it.

``shap`` happens to be importable in the shared test interpreter; the API
image has no ``shap``, so that case is simulated explicitly.
"""

from __future__ import annotations

import json
import math
import platform
from datetime import datetime
from uuid import uuid4

import numpy as np
import pytest

from app.core.config import settings
from app.models.run import Run
from app.models.tabular import MLModel, MLPrediction, MLRuntimeHeartbeat
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import tabular_predict
from app.services.ml import tree_explanations
from app.services.tabular_datasets import TabularError
from app.services.tabular_ml import upload_model_dir
from app.tests.ml_artifacts import CHURN_FEATURES, CHURN_ROWS, churn_frame, fit_churn_artifact

pytest.importorskip("polars")
pytest.importorskip("skrub")
pytest.importorskip("mlflow.sklearn")
shap = pytest.importorskip("shap")


def _commented_frame():
    """Churn plus a free-text field skrub's StringEncoder spreads over 30 columns."""

    frame = churn_frame()
    rng = np.random.default_rng(3)
    words = ["late", "bill", "network", "slow", "great", "price", "support", "fiber"]
    frame["comment"] = [" ".join(rng.choice(words, 4)) + f" #{i}" for i in range(len(frame))]
    return frame


@pytest.fixture(scope="module")
def hgb_classifier(tmp_path_factory):
    # ``plan`` is categorical: HGB splits on it with bitsets, the case shap
    # 0.52 cannot read on its own.
    return fit_churn_artifact(tmp_path_factory.mktemp("shap-hgb"))


@pytest.fixture(scope="module")
def forest_classifier(tmp_path_factory):
    return fit_churn_artifact(
        tmp_path_factory.mktemp("shap-rf"),
        estimator="sklearn.ensemble.RandomForestClassifier",
        params={"n_estimators": 20, "random_state": 42},
        frame=_commented_frame(),
        features=[*CHURN_FEATURES, "comment"],
    )


@pytest.fixture(scope="module")
def boosting_regressor(tmp_path_factory):
    return fit_churn_artifact(
        tmp_path_factory.mktemp("shap-hgbr"),
        task="regression",
        target="arpu",
        frame=_commented_frame(),
        features=[*CHURN_FEATURES, "churn", "comment"],
    )


@pytest.fixture(scope="module")
def numeric_boosting(tmp_path_factory):
    # No categorical column: shap's own HGB reader is correct here, which makes
    # it the oracle for the per-row tree rebuild.
    return fit_churn_artifact(
        tmp_path_factory.mktemp("shap-hgb-numeric"),
        features=["tenure_months", "arpu", "support_tickets"],
    )


@pytest.fixture(scope="module")
def linear_classifier(tmp_path_factory):
    return fit_churn_artifact(
        tmp_path_factory.mktemp("shap-logit"),
        estimator="sklearn.linear_model.LogisticRegression",
        params={"max_iter": 200},
    )


@pytest.fixture()
def workspace(db_session) -> Workspace:
    row = Workspace(id=uuid4().hex, name="Explain", slug=f"explain-{uuid4().hex[:8]}", settings={})
    db_session.add(row)
    actor = User(
        id=str(uuid4()),
        username="explain-" + uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
        is_active=True,
    )
    db_session.add(actor)
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=row.id,
            user_id=actor.id,
            role="member",
            role_template="workspace_contributor",
        )
    )
    db_session.add(Run(id=row.id, workspace_id=row.id, initiated_by_user_id=actor.id))
    db_session.commit()
    return row


@pytest.fixture(autouse=True)
def serving(tmp_path, monkeypatch, db_session):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    tabular_predict.reset_cache()
    tree_explanations.reset_cache()
    yield
    tabular_predict.reset_cache()
    tree_explanations.reset_cache()
    db_session.query(MLRuntimeHeartbeat).delete()
    db_session.commit()


def _register(db_session, workspace, artifact, *, task="classification", target="churn"):
    directory, summary = artifact
    model = MLModel(
        id=uuid4().hex,
        workspace_id=workspace.id,
        name="Explained",
        slug=f"explained-{uuid4().hex[:6]}",
        version=1,
        task=task,
        algo="gradient_boosting",
        target=target,
        features=[spec["name"] for spec in summary["signature"]["inputs"]],
        params_json={},
        status="ready",
        row_count=CHURN_ROWS,
        test_size=0.25,
        cross_validation=0,
        metrics_json=summary["metrics"],
        signature_json=summary["signature"],
        input_example_json=summary["input_example"],
        classes_json=summary["classes"],
        is_champion=True,
    )
    db_session.add(model)
    db_session.flush()
    uri, size = upload_model_dir(directory, workspace_id=workspace.id, model_id=model.id)
    model.model_uri, model.artifact_bytes = uri, size
    model.trained_at = datetime(2026, 9, 1, 9, 30)
    db_session.commit()
    return model


def _row(model, **overrides):
    """A plausible row for any of the fitted contracts above."""

    frame = _commented_frame()
    names = [spec["name"] for spec in model.signature_json["inputs"]]
    base = {
        name: (value.item() if hasattr(value, "item") else value)
        for name, value in frame.iloc[7][names].to_dict().items()
    }
    base.update(overrides)
    return base


def _closes(explanation):
    total = explanation["base"] + sum(item["contribution"] for item in explanation["contributions"])
    if explanation["other"]:
        total += explanation["other"]["contribution"]
    return total


def _sigmoid(value):
    return 1 / (1 + math.exp(-value))


# ---------------------------------------------------------------------------
# Exactness on the pipelines the harness ships
# ---------------------------------------------------------------------------


def test_boosting_classifier_with_categorical_splits_closes_on_its_log_odds(
    db_session, workspace, hgb_classifier
):
    model = _register(db_session, workspace, hgb_classifier)
    for overrides in ({}, {"plan": "hybrid", "tenure_months": 3}, {"plan": None, "arpu": None}):
        answer = tabular_predict.predict_rows(
            db_session, model, [_row(model, **overrides)], explain=True, explain_method="shap"
        )
        prediction = answer["predictions"][0]
        explanation = prediction["explanation"]
        assert explanation["method"] == "tree_shap"
        assert explanation["output_space"] == "log_odds"
        assert explanation["class"] == answer["positive_label"]
        # Additivity: base + Σ contributions is the model's log-odds …
        assert _closes(explanation) == pytest.approx(explanation["output"], abs=1e-5)
        assert explanation["additivity_gap"] < 1e-6
        # … and that log-odds is the probability the caller was served.
        assert _sigmoid(explanation["output"]) == pytest.approx(prediction["score"], abs=1e-5)
        # The counterfactual is not computed when TreeSHAP answered.
        assert "contributions" not in prediction
        json.dumps(answer, allow_nan=False)


def test_forest_classifier_closes_on_the_served_probability(
    db_session, workspace, forest_classifier
):
    model = _register(db_session, workspace, forest_classifier)
    answer = tabular_predict.predict_rows(
        db_session, model, [_row(model)], explain=True, explain_method="auto"
    )
    prediction = answer["predictions"][0]
    explanation = prediction["explanation"]
    assert explanation["method"] == "tree_shap"
    assert explanation["output_space"] == "probability"
    assert explanation["output"] == pytest.approx(prediction["score"], abs=1e-6)
    assert _closes(explanation) == pytest.approx(explanation["output"], abs=1e-5)


def test_boosting_regressor_closes_on_the_served_value(db_session, workspace, boosting_regressor):
    model = _register(db_session, workspace, boosting_regressor, task="regression", target="arpu")
    answer = tabular_predict.predict_rows(
        db_session, model, [_row(model)], explain=True, explain_method="shap"
    )
    prediction = answer["predictions"][0]
    explanation = prediction["explanation"]
    assert explanation["output_space"] == "value"
    assert explanation["class"] is None
    assert explanation["output"] == pytest.approx(prediction["prediction"], abs=1e-5)
    assert _closes(explanation) == pytest.approx(explanation["output"], abs=1e-5)


def test_a_text_field_spread_over_many_columns_is_one_contribution(
    db_session, workspace, forest_classifier, monkeypatch
):
    monkeypatch.setattr(settings, "ml_explain_shap_top_fields", 50)
    model = _register(db_session, workspace, forest_classifier)
    answer = tabular_predict.predict_rows(
        db_session, model, [_row(model)], explain=True, explain_method="shap"
    )
    explanation = answer["predictions"][0]["explanation"]
    fields = [item["field"] for item in explanation["contributions"]]
    contract = [spec["name"] for spec in model.signature_json["inputs"]]
    # StringEncoder turns ``comment`` into 30 columns; the answer names it once.
    assert sorted(fields) == sorted(contract)
    assert fields.count("comment") == 1
    assert explanation["other"] is None
    # Sorted by magnitude, and each field carries the caller's own value.
    magnitudes = [abs(item["contribution"]) for item in explanation["contributions"]]
    assert magnitudes == sorted(magnitudes, reverse=True)
    comment = next(item for item in explanation["contributions"] if item["field"] == "comment")
    assert comment["value"] == _row(model)["comment"]


def test_the_top_fields_and_an_other_remainder_still_close(
    db_session, workspace, forest_classifier, monkeypatch
):
    monkeypatch.setattr(settings, "ml_explain_shap_top_fields", 2)
    model = _register(db_session, workspace, forest_classifier)
    explanation = tabular_predict.predict_rows(
        db_session, model, [_row(model)], explain=True, explain_method="shap"
    )["predictions"][0]["explanation"]
    assert len(explanation["contributions"]) == 2
    assert explanation["other"]["fields"] == len(model.signature_json["inputs"]) - 2
    assert _closes(explanation) == pytest.approx(explanation["output"], abs=1e-5)


def test_the_per_row_tree_rebuild_matches_shap_where_shap_reads_hgb_itself(numeric_boosting):
    """Without categorical columns shap's own HGB reader is right: same values."""

    directory, summary = numeric_boosting
    pipeline = tabular_predict._load_mlflow_model(directory)
    fields = summary["signature"]["inputs"]
    names = [spec["name"] for spec in fields]
    frame = churn_frame()
    estimator = pipeline[-1]
    native = shap.TreeExplainer(estimator)
    for index in range(10):
        row = {name: float(frame.iloc[index][name]) for name in names}
        typed = tabular_predict.build_frame(fields, [row])
        ours = tree_explanations.explain_pipeline(
            pipeline,
            typed,
            row=row,
            fields=names,
            task="classification",
            classes=[str(value) for value in summary["classes"]],
            label=str(summary["classes"][-1]),
            top=10,
        )
        matrix = np.asarray(pipeline[:-1].transform(typed), dtype=np.float64)
        reference = np.ravel(native.shap_values(matrix, check_additivity=False))
        by_field = {item["field"]: item["contribution"] for item in ours["contributions"]}
        for position, name in enumerate(names):
            assert by_field[name] == pytest.approx(float(reference[position]), abs=1e-6)
        assert ours["base"] == pytest.approx(float(np.ravel(native.expected_value)[0]), abs=1e-6)


def test_a_threshold_wrapper_is_explained_and_a_calibrator_is_not():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import FixedThresholdClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    forest = make_pipeline(StandardScaler(), RandomForestClassifier())
    assert tree_explanations.tree_pipeline(FixedThresholdClassifier(forest))[1] is None
    assert tree_explanations.tree_pipeline(CalibratedClassifierCV(forest)) == (
        None,
        "calibrated_model",
    )
    assert tree_explanations.tree_pipeline(make_pipeline(LogisticRegression())) == (
        None,
        "not_a_tree_model",
    )


# ---------------------------------------------------------------------------
# Fallbacks: the counterfactual answers, and says why
# ---------------------------------------------------------------------------


def _counterfactual_answer(db_session, model, method="auto"):
    answer = tabular_predict.predict_rows(
        db_session,
        model,
        [_row(model, tenure_months=2, support_tickets=6)],
        explain=True,
        explain_method=method,
    )
    return answer["predictions"][0]


def test_a_linear_model_keeps_the_counterfactual(db_session, workspace, linear_classifier):
    model = _register(db_session, workspace, linear_classifier)
    prediction = _counterfactual_answer(db_session, model)
    assert prediction["explanation"] == {"method": "counterfactual", "reason": "not_a_tree_model"}
    assert prediction["contributions"], "today's explanation still answers"


def test_the_api_image_without_shap_falls_back(db_session, workspace, hgb_classifier, monkeypatch):
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *args, **kwargs: None if name == "shap" else real(name, *args, **kwargs),
    )
    model = _register(db_session, workspace, hgb_classifier)
    prediction = _counterfactual_answer(db_session, model)
    assert prediction["explanation"] == {"method": "counterfactual", "reason": "shap_unavailable"}
    assert prediction["contributions"]


def test_a_worker_without_shap_returns_a_reason_not_an_error(
    db_session, workspace, hgb_classifier, monkeypatch
):
    import sys

    model = _register(db_session, workspace, hgb_classifier)
    monkeypatch.setitem(sys.modules, "shap", None)  # ``import shap`` raises ImportError
    result = tree_explanations.answer_for(model.id, _row(model), label="1")
    assert result["error"]["reason"] == "shap_unavailable"


def test_no_listening_ml_ts_consumer_falls_back(db_session, workspace, hgb_classifier, monkeypatch):
    monkeypatch.setattr(settings, "worker_eager_mode", False)
    model = _register(db_session, workspace, hgb_classifier)
    prediction = _counterfactual_answer(db_session, model)
    assert prediction["explanation"]["reason"] == "shap_unavailable"


def _heartbeat(db_session, model, **package_overrides):
    from app.resources.ml_artifact_contract import runtime_versions

    artifact = (model.metrics_json or {}).get("artifact") or {}
    packages = {
        name: version
        for name, version in runtime_versions("tabular", artifact.get("serialization")).items()
        if name != "python"
    }
    packages.update(package_overrides)
    db_session.add(
        MLRuntimeHeartbeat(
            runtime="ml-ts",
            hostname="ml-ts-serve-" + uuid4().hex[:6],
            queues=[settings.celery_ml_ts_serve_queue],
            packages_json={**packages, "agentium_python": platform.python_version()},
            seen_at=datetime.utcnow(),
        )
    )
    db_session.commit()


class _Pending:
    def __init__(self, outcome):
        self.outcome = outcome
        self.forgotten = False

    def get(self, timeout=None, propagate=True):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome()

    def forget(self):
        self.forgotten = True


def test_a_live_consumer_answers_through_the_rpc_queue(
    db_session, workspace, hgb_classifier, monkeypatch
):
    from app.workers.celery_app import celery_app

    monkeypatch.setattr(settings, "worker_eager_mode", False)
    model = _register(db_session, workspace, hgb_classifier)
    _heartbeat(db_session, model)
    sent = {}

    def send_task(name, args, kwargs, queue, expires):
        sent.update(name=name, queue=queue, expires=expires)
        # The worker side, run here with the eager runtime gate open.
        monkeypatch.setattr(settings, "worker_eager_mode", True)
        try:
            outcome = tree_explanations.answer_for(*args, **kwargs)
        finally:
            monkeypatch.setattr(settings, "worker_eager_mode", False)
        return _Pending(lambda: outcome)

    monkeypatch.setattr(celery_app, "send_task", send_task)
    prediction = _counterfactual_answer(db_session, model)
    assert prediction["explanation"]["method"] == "tree_shap"
    assert sent == {
        "name": "agentium.ml_tree_shap",
        "queue": settings.celery_ml_ts_serve_queue,
        "expires": settings.ml_explain_timeout_s,
    }


def test_a_slow_worker_times_out_into_the_counterfactual(
    db_session, workspace, hgb_classifier, monkeypatch
):
    from celery.exceptions import TimeoutError as CeleryTimeout

    from app.workers.celery_app import celery_app

    monkeypatch.setattr(settings, "worker_eager_mode", False)
    model = _register(db_session, workspace, hgb_classifier)
    _heartbeat(db_session, model)
    pending = _Pending(CeleryTimeout("late"))
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **k: pending)
    prediction = _counterfactual_answer(db_session, model)
    assert prediction["explanation"] == {"method": "counterfactual", "reason": "timeout"}
    assert prediction["contributions"]
    assert pending.forgotten


def test_a_consumer_with_another_reader_stack_is_a_runtime_mismatch(
    db_session, workspace, hgb_classifier, monkeypatch
):
    from app.workers.celery_app import celery_app

    monkeypatch.setattr(settings, "worker_eager_mode", False)
    model = _register(db_session, workspace, hgb_classifier)
    _heartbeat(db_session, model, **{"scikit-learn": "0.0.1"})
    monkeypatch.setattr(
        celery_app, "send_task", lambda *a, **k: pytest.fail("no task for a mismatched reader")
    )
    prediction = _counterfactual_answer(db_session, model)
    assert prediction["explanation"]["reason"] == "runtime_mismatch"


def test_an_explicit_shap_request_is_refused_instead_of_falling_back(
    db_session, workspace, linear_classifier
):
    model = _register(db_session, workspace, linear_classifier)
    with pytest.raises(TabularError) as raised:
        _counterfactual_answer(db_session, model, method="shap")
    assert raised.value.code == "ML_EXPLAIN_UNAVAILABLE"
    assert raised.value.status_code == 409
    assert raised.value.details == {"reason": "not_a_tree_model"}
    # A refused call is not a served answer: nothing was journalled.
    assert db_session.query(MLPrediction).filter_by(served_id=model.id).count() == 0


def test_an_unknown_method_is_refused(db_session, workspace, hgb_classifier):
    model = _register(db_session, workspace, hgb_classifier)
    with pytest.raises(TabularError) as raised:
        tabular_predict.predict_rows(
            db_session, model, [_row(model)], explain=True, explain_method="lime"
        )
    assert raised.value.code == "ML_EXPLAIN_METHOD_INVALID"


def test_the_default_stays_todays_counterfactual_contract(db_session, workspace, hgb_classifier):
    model = _register(db_session, workspace, hgb_classifier)
    prediction = tabular_predict.predict_rows(
        db_session, model, [_row(model, support_tickets=6)], explain=True
    )["predictions"][0]
    assert "explanation" not in prediction
    assert prediction["contributions"]


# ---------------------------------------------------------------------------
# Privacy of the journal
# ---------------------------------------------------------------------------


def test_an_unretained_call_journals_shapley_effects_without_caller_values(
    db_session, workspace, forest_classifier
):
    model = _register(db_session, workspace, forest_classifier)
    sentinel = "sentinel-comment-7291"
    answer = tabular_predict.predict_rows(
        db_session,
        model,
        [_row(model, comment=sentinel)],
        explain=True,
        explain_method="shap",
        store=False,
    )
    served = answer["predictions"][0]["explanation"]
    assert any(item.get("value") == sentinel for item in served["contributions"])
    row = db_session.get(MLPrediction, answer["prediction_id"])
    assert row.payload_json == [] and row.input_storage_allowed is False
    journaled = row.output_json[0]["explanation"]
    assert sentinel not in json.dumps(row.output_json)
    assert all("value" not in item for item in journaled["contributions"])
    # The effects themselves are kept, as for the counterfactual.
    assert [item["contribution"] for item in journaled["contributions"]] == [
        item["contribution"] for item in served["contributions"]
    ]


def test_a_retained_call_journals_the_explanation_as_served(
    db_session, workspace, forest_classifier
):
    model = _register(db_session, workspace, forest_classifier)
    answer = tabular_predict.predict_rows(
        db_session, model, [_row(model)], explain=True, explain_method="shap"
    )
    row = db_session.get(MLPrediction, answer["prediction_id"])
    assert row.output_json[0]["explanation"] == answer["predictions"][0]["explanation"]


def test_an_overrun_exact_explanation_makes_the_next_one_approximate(
    db_session, workspace, forest_classifier, monkeypatch
):
    # Any measured duration exceeds a negative budget: the first explanation is
    # exact and marks the loaded model, the second is TreeSHAP's approximation.
    monkeypatch.setattr(settings, "ml_explain_shap_exact_budget_s", -1.0)
    model = _register(db_session, workspace, forest_classifier)
    first, second = (
        tabular_predict.predict_rows(
            db_session, model, [_row(model)], explain=True, explain_method="shap"
        )["predictions"][0]["explanation"]
        for _ in range(2)
    )
    assert first["method"] == "tree_shap"
    assert second["method"] == "tree_shap_approximate"
    assert _closes(second) == pytest.approx(second["output"], abs=1e-5)
