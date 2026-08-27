"""PSI, rolling AUC and the feedback → dataset hop, without a live fit.

The serving path is covered in ``test_ml_predict_api``. This module pins the
arithmetic and the journal mutations: a PSI that stays silent on a shifted
sample, or a feedback row that does not name the prediction_id, is a
monitoring tab that lies.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from app.models.tabular import MLModel, MLPrediction, TabularDataset
from app.models.workspace import Workspace
from app.services.tabular_datasets import TabularError
from app.services.tabular_monitoring import (
    attach_feedback,
    badges_for,
    concept_drift,
    drift_status,
    frequency_stability,
    materialize_labeled,
    population_stability,
    report,
    rolling_auc,
    score_drift,
    worst_status,
)


def test_psi_is_near_zero_on_the_same_sample():
    sample = [float(i) for i in range(40)]
    value = population_stability(sample, list(sample))
    assert value is not None
    assert value < 0.01


def test_psi_rises_when_the_mass_moves():
    expected = [float(i) for i in range(40)]
    shifted = [float(i) + 30 for i in range(40)]
    value = population_stability(expected, shifted)
    assert value is not None
    assert value > 0.25
    assert drift_status(value) == "alert"


def test_psi_stays_silent_on_a_thin_sample():
    assert population_stability([1.0, 2.0], [3.0, 4.0]) is None
    assert frequency_stability({"a": 2}, {"a": 2}) is None


def test_frequency_psi_flags_a_category_that_took_over():
    expected = {"prepaid": 80, "postpaid": 20}
    actual = {"prepaid": 20, "postpaid": 80}
    value = frequency_stability(expected, actual)
    assert value is not None
    assert value > 0.25


def test_rolling_auc_recovers_a_perfect_ranking():
    labels = ["0"] * 8 + ["1"] * 8
    scores = [0.1] * 8 + [0.9] * 8
    assert rolling_auc(labels, scores, positive="1") == pytest.approx(1.0)


def test_rolling_auc_refuses_a_single_class():
    assert rolling_auc(["1"] * 12, [0.8] * 12, positive="1") is None


def test_worst_status_prefers_an_alert_to_a_watch():
    assert worst_status(["ok", "watch", "unknown"]) == "watch"
    assert worst_status(["ok", "alert", "watch"]) == "alert"
    assert worst_status([]) == "unknown"


@pytest.fixture()
def workspace(db_session) -> Workspace:
    row = Workspace(
        id=str(uuid4()),
        name="Monitor",
        slug=f"monitor-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def model(db_session, workspace) -> MLModel:
    row = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Churn Radar",
        slug="churn-radar",
        version=1,
        task="classification",
        algo="linear",
        target="churn",
        features=["arpu", "plan"],
        status="ready",
        metrics_json={
            "primary": {"key": "roc_auc", "value": 0.84},
            "target": {"positive": "1"},
        },
        signature_json={
            "inputs": [
                {"name": "arpu", "kind": "number"},
                {"name": "plan", "kind": "category", "choices": ["prepaid", "postpaid"]},
            ]
        },
    )
    db_session.add(row)
    db_session.commit()
    return row


def _journal(
    db_session,
    model,
    *,
    payload,
    score,
    prediction="1",
    label=None,
):
    row = MLPrediction(
        workspace_id=model.workspace_id,
        model_id=model.id,
        served_id=model.id,
        served_version=1,
        slug=model.slug,
        caller="session",
        row_count=1,
        payload_json=[payload],
        output_json=[{"prediction": prediction, "score": score}],
        scores_json={"n": 1, "scores": [score], "mean": score},
        created_at=datetime.utcnow(),
        label=label,
        labeled_at=datetime.utcnow() if label is not None else None,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_feedback_writes_the_label_onto_the_prediction_id(db_session, model):
    row = _journal(db_session, model, payload={"arpu": 40, "plan": "prepaid"}, score=0.7)
    attached = attach_feedback(
        db_session, model=model, prediction_id=row.id, label="1"
    )
    assert attached.label == "1"
    assert attached.labeled_at is not None


def test_feedback_refuses_a_prediction_from_another_lineage(db_session, model, workspace):
    other = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Other",
        slug="other",
        version=1,
        task="classification",
        algo="linear",
        target="churn",
        features=["arpu"],
        status="ready",
    )
    db_session.add(other)
    db_session.commit()
    row = _journal(db_session, other, payload={"arpu": 10}, score=0.2)
    with pytest.raises(TabularError) as caught:
        attach_feedback(db_session, model=model, prediction_id=row.id, label="1")
    assert caught.value.code == "ML_PREDICTION_WRONG_MODEL"


def test_a_thin_feedback_set_cannot_become_a_dataset(db_session, model):
    row = _journal(
        db_session, model, payload={"arpu": 40, "plan": "prepaid"}, score=0.7, label="1"
    )
    assert row.label == "1"
    with pytest.raises(TabularError) as caught:
        materialize_labeled(db_session, model=model)
    assert caught.value.code == "ML_FEEDBACK_TOO_FEW"


def test_labeled_rows_materialize_as_a_dataset_the_studio_can_open(db_session, model):
    pytest.importorskip("polars")
    for index in range(3):
        _journal(
            db_session,
            model,
            payload={"arpu": 30 + index, "plan": "prepaid"},
            score=0.4 + index / 10,
            label=str(index % 2),
        )
    dataset = materialize_labeled(db_session, model=model)
    assert isinstance(dataset, TabularDataset)
    assert dataset.source == "generated"
    assert dataset.produced_by == "ml_feedback"
    assert dataset.lineage_json["kind"] == "feedback"
    assert "churn" in {col["name"] for col in dataset.schema_json}


def test_the_report_stays_unknown_until_something_has_been_served(db_session, model):
    body = report(db_session, model=model)
    assert body["badge"] is None
    assert body["window"]["predictions"] == 0
    assert body["data_drift"]["status"] == "unknown"


def test_score_drift_compares_the_recent_half_to_the_older_half(db_session, model):
    for index in range(20):
        _journal(
            db_session,
            model,
            payload={"arpu": 20.0, "plan": "prepaid"},
            score=0.2 if index < 10 else 0.9,
        )
    # Newest first in the query: the last inserts are the high scores.
    body = score_drift(
        __import__(
            "app.services.tabular_monitoring", fromlist=["_recent"]
        )._recent(db_session, model)
    )
    assert body["n"] == 20
    assert body["status"] in {"watch", "alert"}


def test_the_list_badge_agrees_with_the_tab_when_features_drift(
    db_session, model, workspace
):
    """A list that says Stable while the tab says Alerte is a lie.

    ``badges_for`` used to skip data PSI. Score and concept stay quiet on a
    shifted feature with a flat score, so the list would print ok.
    """

    dataset = TabularDataset(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Train",
        slug=f"train-{uuid4().hex[:8]}",
        version=1,
        source="upload",
        status="ready",
        stats_json={
            "arpu": {
                "kind": "number",
                "min": 10.0,
                "histogram": [
                    {"upper": 20.0, "count": 20},
                    {"upper": 30.0, "count": 20},
                    {"upper": 40.0, "count": 20},
                ],
            }
        },
    )
    db_session.add(dataset)
    model.dataset_id = dataset.id
    db_session.commit()
    for _ in range(16):
        _journal(
            db_session, model, payload={"arpu": 90.0, "plan": "prepaid"}, score=0.5
        )

    body = report(db_session, model=model)
    assert body["data_drift"]["status"] == "alert"
    assert body["badge"] == "alert"
    assert badges_for(db_session, [model])[model.id] == body["badge"]


def test_concept_drift_flags_a_drop_from_the_train_auc(db_session, model):
    # Rank the positive class below the negative one — AUC ~ 0.
    for index in range(10):
        _journal(
            db_session,
            model,
            payload={"arpu": 20.0, "plan": "prepaid"},
            score=0.9 if index < 5 else 0.1,
            prediction="0" if index < 5 else "1",
            label="0" if index < 5 else "1",
        )
    body = concept_drift(
        model,
        __import__(
            "app.services.tabular_monitoring", fromlist=["_recent"]
        )._recent(db_session, model),
    )
    assert body["labeled"] == 10
    assert body["rolling_auc"] is not None
    assert body["rolling_auc"] < 0.2
    assert body["status"] == "alert"
