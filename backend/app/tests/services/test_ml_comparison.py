"""Two versions on one test split: what the comparison refuses, and what it warns about.

The delta tiles on a model card subtract two recorded results, which is honest
because that is what they say they are. This service answers the harder question
— *which model is better* — and that answer is only worth anything if both were
measured on the same rows. So the interesting assertions here are about the
guards: which mismatches are refused outright, which are allowed through with a
warning, and that the rows really are shared.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.tabular import MLModel
from app.services import ml_comparison
from app.services.tabular_datasets import TabularError

# The training plane's fixtures, plus its stubbed harness.
from app.tests.services.test_ml_training import (  # noqa: F401
    _stub_harness,
    dataset,
    enabled,
    store,
    workspace,
)

pytest.importorskip("skore")


def _train(db, workspace, dataset, **overrides):
    from app.services.tabular_ml import submit_training

    request = {
        "workspace_id": workspace.id,
        "dataset_ref": {"dataset_id": dataset.id},
        "target": "churn",
        "algo": "gradient_boosting",
    }
    request.update(overrides)
    return submit_training(db, **request)


@pytest.fixture()
def two_fits(db_session, workspace, dataset, enabled, monkeypatch, store):
    """Two ready versions of one lineage, from the stubbed harness."""

    _stub_harness(monkeypatch)
    first = _train(db_session, workspace, dataset)
    second = _train(db_session, workspace, dataset, algo="linear")
    db_session.expire_all()
    return (
        db_session.query(MLModel).filter_by(id=first.id).one(),
        db_session.query(MLModel).filter_by(id=second.id).one(),
    )


# ---------------------------------------------------------------------------
# Refusals — each one names what does not line up
# ---------------------------------------------------------------------------


def test_a_version_is_not_compared_with_itself(db_session, two_fits):
    first, _ = two_fits
    with pytest.raises(TabularError) as raised:
        ml_comparison.compare(db_session, left=first, right=first)
    assert raised.value.code == "ML_COMPARE_SAME_VERSION"


def test_two_versions_answering_different_questions_are_refused(db_session, two_fits):
    """One table cannot rank a churn classifier against an ARPU regressor."""

    first, second = two_fits
    second.target = "arpu"
    second.task = "regression"
    db_session.commit()

    with pytest.raises(TabularError) as raised:
        ml_comparison.compare(db_session, left=first, right=second)
    assert raised.value.code == "ML_COMPARE_DIFFERENT_QUESTION"


def test_a_model_that_never_trained_has_nothing_to_compare(db_session, two_fits):
    first, second = two_fits
    second.status = "failed"
    db_session.commit()

    with pytest.raises(TabularError) as raised:
        ml_comparison.compare(db_session, left=first, right=second)
    assert raised.value.code == "ML_MODEL_NOT_READY"


def test_a_dataset_missing_a_feature_is_refused_by_name(db_session, two_fits):
    """Silently comparing on the columns that happen to be shared would be worse."""

    first, second = two_fits
    second.features = list(second.features or []) + ["a_column_nobody_stored"]
    db_session.commit()

    with pytest.raises(TabularError) as raised:
        ml_comparison.compare(db_session, left=first, right=second)
    assert raised.value.code == "ML_COMPARE_NO_COMMON_DATASET"
    assert "a_column_nobody_stored" in raised.value.details["missing"]


def test_serving_switched_off_stops_the_comparison_too(db_session, two_fits, monkeypatch):
    monkeypatch.setattr(settings, "ml_predict_enabled", False)
    first, second = two_fits
    with pytest.raises(TabularError) as raised:
        ml_comparison.compare(db_session, left=first, right=second)
    assert raised.value.code == "ML_PREDICT_DISABLED"


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_both_versions_are_scored_on_the_very_same_rows(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    """The property the whole service exists for: one split, two columns."""

    first = _train(db_session, workspace, dataset)
    second = _train(db_session, workspace, dataset, algo="linear")
    db_session.expire_all()
    left = db_session.query(MLModel).filter_by(id=first.id).one()
    right = db_session.query(MLModel).filter_by(id=second.id).one()
    assert left.status == "ready" and right.status == "ready", (left.error, right.error)

    table = ml_comparison.compare(db_session, left=left, right=right)

    assert table["task"] == "classification"
    assert table["target"] == "churn"
    assert table["dataset"]["id"] == dataset.id
    # One split, quoted so a reader can reproduce it.
    assert table["split"]["random_state"] == settings.ml_train_random_state
    assert 0 < table["split"]["rows"] < int(dataset.row_count)
    # Both versions trained on this dataset with these knobs, so nothing to warn.
    assert table["warnings"] == []

    columns = {entry["model_id"] for entry in table["models"]}
    assert columns == {left.id, right.id}
    rows = {row["key"]: row for row in table["metrics"]}
    assert {"accuracy", "roc_auc"} <= set(rows)
    for key, row in rows.items():
        # Every metric carries a value for *both* sides, which is what makes the
        # table a comparison rather than two lists.
        assert isinstance(row[left.id], float), key
        assert isinstance(row[right.id], float), key
    # A timing is a property of this machine, not of a model.
    assert not [key for key in rows if key.endswith("_time")]


@pytest.mark.slow
def test_the_table_reproduces_each_version_s_own_recorded_score(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    """The split rebuild is right: re-scoring finds what training recorded.

    Both versions were trained on this dataset with the same seed and test size,
    so the reconstructed split *is* their test split, and the comparison has to
    agree with `metrics_json` — otherwise the rows being compared are not the
    rows the card reports on.
    """

    first = _train(db_session, workspace, dataset)
    second = _train(db_session, workspace, dataset, algo="linear")
    db_session.expire_all()
    left = db_session.query(MLModel).filter_by(id=first.id).one()
    right = db_session.query(MLModel).filter_by(id=second.id).one()

    table = ml_comparison.compare(db_session, left=left, right=right)
    rows = {row["key"]: row for row in table["metrics"]}
    for model in (left, right):
        recorded = {
            score["key"]: score["value"] for score in (model.metrics_json or {}).get("scores") or []
        }
        for key in ("roc_auc", "accuracy"):
            # The card's copy is rounded to six decimals on the way into JSON;
            # agreement to that precision is agreement.
            assert rows[key][model.id] == pytest.approx(recorded[key], abs=1e-6), key


@pytest.mark.slow
def test_a_recorded_version_with_changed_dataset_is_refused(
    db_session, workspace, dataset, enabled, monkeypatch, store
):
    """The Flow case: a version fitted on a derived dataset is the one worth ranking.

    Refusing would make the comparison that matters impossible; answering without
    saying so would hide that some of these rows may have trained that model.
    """

    from app.services.tabular_datasets import register_frame
    from app.tests.services.test_ml_training import _frame

    first = _train(db_session, workspace, dataset)
    second = _train(db_session, workspace, dataset, algo="linear")
    db_session.expire_all()
    left = db_session.query(MLModel).filter_by(id=first.id).one()
    right = db_session.query(MLModel).filter_by(id=second.id).one()

    # A derived table, as a Polars node would leave behind: same rows, extra
    # column. The comparison should land on the *right* model's dataset and say
    # that the left one was fitted somewhere else.
    derived = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Churn features derived",
        frame=_frame().with_columns(extra=_frame()["arpu"] * 2),
        source="transform",
    )
    db_session.commit()
    left.dataset_id = derived.id
    db_session.commit()

    with pytest.raises(TabularError) as raised:
        ml_comparison.compare(db_session, left=left, right=right)
    assert raised.value.code == "ML_COMPARE_UNVERIFIED_PARTITION"
