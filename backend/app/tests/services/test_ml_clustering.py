"""Segmentation contracts across validation, Flow training and serving."""
# ruff: noqa: F811 - imported pytest fixtures are requested by function arguments.

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services import (
    ml_comparison,
    ml_retraining,
    ml_shadow,
    tabular_ml,
    tabular_monitoring,
    tabular_predict,
)
from app.services.ml.families import family_of_task
from app.services.ml.metrics import METRIC_BY_KEY
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_training import (  # noqa: F401
    _stub_harness,
    dataset,
    enabled,
    store,
    workspace,
)


def _validate(dataset, **changes):
    return tabular_ml.validate_training(dataset, **{
        "task": "clustering", "target": "", "features": ["arpu", "tenure_months"], **changes,
    })


def test_targetless_clustering_is_bounded_and_normalized(dataset, enabled):
    spec = _validate(dataset, test_size=0.25)
    assert spec.family == spec.task == "clustering"
    assert spec.target == "" and spec.test_size == 0 and spec.cross_validation == 0
    assert spec.knobs == {"n_clusters": 5, "max_iter": 300}
    params = tabular_ml.estimator_params(spec.algo, spec.task, spec.knobs)
    assert params["n_init"] == 10 and params["random_state"] == settings.ml_train_random_state
    assert family_of_task("clustering").serving == "in_process"
    assert family_of_task("clustering").train_queue() == (settings.celery_ml_tabular_queue or settings.celery_task_default_queue)
    for key in ("silhouette", "stability_ari"):
        assert METRIC_BY_KEY[key].direction == "max"
        assert METRIC_BY_KEY[key].good is None


@pytest.mark.parametrize(("changes", "code"), [
    ({"target": "arpu"}, "ML_CLUSTER_TARGET_UNSUPPORTED"),
    ({"target": "missing"}, "ML_CLUSTER_TARGET_UNSUPPORTED"),
    ({"features": []}, "ML_FEATURES_REQUIRED"),
    ({"features": ["plan"]}, "ML_CLUSTER_FEATURE_NOT_NUMERIC"),
    ({"features": ["unknown"]}, "ML_FEATURE_UNKNOWN"),
    ({"algo": "linear"}, "ML_ALGO_TASK_MISMATCH"),
    ({"cross_validation": 2}, "ML_CLUSTER_OPTION_UNSUPPORTED"),
    ({"cross_validation": True}, "ML_CLUSTER_OPTION_UNSUPPORTED"),
    ({"test_size": 0.3}, "ML_CLUSTER_OPTION_UNSUPPORTED"),
    ({"spec": {"tuning": "budget"}}, "ML_SPEC_INVALID"),
    ({"spec": {"text_encoder": "embedding"}}, "ML_SPEC_INVALID"),
    ({"knobs": {"n_clusters": 1}}, "ML_CLUSTER_KNOB_INVALID"),
    ({"knobs": {"n_clusters": 21}}, "ML_CLUSTER_KNOB_INVALID"),
    ({"knobs": {"n_clusters": 2.5}}, "ML_CLUSTER_KNOB_INVALID"),
    ({"knobs": {"n_clusters": True}}, "ML_CLUSTER_KNOB_INVALID"),
    ({"knobs": {"n_clusters": float("nan")}}, "ML_CLUSTER_KNOB_INVALID"),
    ({"knobs": {"n_clusters": 10 ** 400}}, "ML_CLUSTER_KNOB_INVALID"),
    ({"knobs": {"max_iter": 501}}, "ML_CLUSTER_KNOB_INVALID"),
    ({"knobs": {"n_init": 1000}}, "ML_CLUSTER_KNOB_INVALID"),
])
def test_supervised_and_unbounded_requests_are_refused(dataset, enabled, changes, code):
    with pytest.raises(TabularError) as caught:
        _validate(dataset, **changes)
    assert caught.value.code == code


def test_bounds_respect_both_platform_and_segmentation_limits(dataset, enabled, monkeypatch):
    dataset.row_count = 39
    with pytest.raises(TabularError) as caught:
        _validate(dataset, knobs={"n_clusters": 20})
    assert caught.value.code == "ML_ROWS_INSUFFICIENT"
    dataset.row_count = 50_001
    with pytest.raises(TabularError) as caught:
        _validate(dataset)
    assert caught.value.code == "ML_ROWS_TOO_MANY"
    dataset.row_count = 60
    monkeypatch.setattr(settings, "ml_train_max_features", 1)
    with pytest.raises(TabularError) as caught:
        _validate(dataset)
    assert caught.value.code == "ML_TOO_MANY_FEATURES"
    dataset.stats_json = {**dataset.stats_json, "arpu": {"nulls": 60}}
    with pytest.raises(TabularError) as caught:
        _validate(dataset, features=["arpu"])
    assert caught.value.code == "ML_CLUSTER_DATA_UNUSABLE"


def test_creation_and_manifest_preserve_no_target_no_split(db_session, workspace, dataset, enabled, tmp_path):
    spec = _validate(dataset)
    model = tabular_ml.create_model(db_session, workspace_id=workspace.id, spec=spec)
    db_session.commit()
    assert model.target == "" and model.family == "clustering"
    manifest = json.loads(tabular_ml._write_manifest(tmp_path, model, Path("data.parquet")).read_text())
    assert manifest["test_size"] == 0 and manifest["cv"] == 0
    assert manifest["params"]["n_init"] == 10
    assert tabular_ml._harness_for(family_of_task("clustering")).name == "ml_clustering_harness.py"


@pytest.mark.asyncio
async def test_flow_accepts_a_targetless_graph_owned_training_request(
    db_session, workspace, dataset, enabled, monkeypatch, store,
):
    from app.services.skills_registry.wrappers import _ml_train_sklearn_v1

    _stub_harness(monkeypatch)
    result = await _ml_train_sklearn_v1({
        "input": {"dataset_id": dataset.id},
        "_train": {"task": "clustering", "algo": "kmeans", "features": ["arpu", "tenure_months"],
                   "model_name": "Customer segments", "node_id": "segments"},
    }, {"workspace_id": workspace.id})
    assert result["task"] == "clustering" and result["target"] == ""
    model = tabular_ml.get_model(db_session, workspace_id=workspace.id, model_id=result["model_id"])
    assert model.family == "clustering" and model.node_id == "segments"


def test_cluster_labels_are_not_scores_or_explanations():
    model = SimpleNamespace(task="clustering", metrics_json={})
    answers = tabular_predict._rows_from(model, [], None, [0, 2], None)
    assert answers == [{"prediction": 0}, {"prediction": 2}]
    assert all(type(answer["prediction"]) is int for answer in answers)
    assert tabular_predict._measure_of(answers[0], "clustering") is None
    assert tabular_predict._score_summary(answers, task="clustering") == {
        "n": 2, "predictions": {"0": 1, "2": 1},
    }
    assert tabular_predict.predict_output_schema(model)["properties"] == {
        "prediction": {"type": "integer"}, "served": {"type": "object"},
    }


def test_supervised_lifecycle_actions_refuse_segmentation(db_session, workspace, dataset, enabled):
    model = tabular_ml.create_model(db_session, workspace_id=workspace.id, spec=_validate(dataset))
    model.status = "ready"
    model.model_uri = "object://segmentation"
    assert ml_retraining.supported(model) is False
    assert ml_shadow.supported(model) is False
    for invoke in (
        lambda: tabular_monitoring.attach_feedback(db_session, model=model, prediction_id="unused", label=0),
        lambda: tabular_monitoring.materialize_labeled(db_session, model=model),
    ):
        with pytest.raises(TabularError) as caught:
            invoke()
        assert caught.value.code == "ML_CLUSTER_FEEDBACK_UNSUPPORTED"
    with pytest.raises(TabularError) as caught:
        ml_comparison.compare(db_session, left=model, right=model)
    assert caught.value.code == "ML_COMPARE_NOT_TABULAR"


def test_published_description_does_not_promise_supervised_test_accuracy():
    model = SimpleNamespace(task="clustering", name="Profiles", version=2,
                            metrics_json={"primary": {"key": "silhouette", "value": 0.6}})
    description = tabular_predict._skill_description(model)
    assert "cluster identifier" in description and "Training silhouette" in description
    assert "Test" not in description and "Estimates ''" not in description
