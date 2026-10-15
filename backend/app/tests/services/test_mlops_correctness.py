"""Row alignment, unchanged holdout, source pinning and task-specific drift."""

from copy import deepcopy

import polars as pl
import pytest

from app.models.tabular import MLPrediction
from app.services.ml_feedback import iter_labeled_samples, sample_id, samples_metadata
from app.services.ml_retraining_data import RetrainingDataPolicy, materialize, verify_sources
from app.services.tabular_datasets import TabularError, read_frame, register_frame
from app.services.tabular_monitoring import attach_feedback, concept_drift, score_drift
from app.tests.services.test_ml_retraining import case, enabled, store  # noqa: F401


def _rows(db, model):
    return db.query(MLPrediction).filter_by(served_id=model.id).order_by(MLPrediction.id).all()


def _materialize(db, case, mode="original_plus_feedback", **kw):
    return materialize(
        db,
        model=case.model,
        rows=_rows(db, case.model),
        features=["x"],
        policy=RetrainingDataPolicy(mode=mode, **kw),
    )


def test_batch_feedback_needs_sample_and_never_replicates_label(db_session, case):
    row = _rows(db_session, case.model)[0]
    row.row_count = 2
    row.payload_json = [{"x": 101}, {"x": 102}]
    row.output_json = [{"prediction": "0", "score": 0.2}, {"prediction": "1", "score": 0.8}]
    row.label = "ambiguous historical label"
    db_session.commit()
    assert list(iter_labeled_samples(row)) == []
    with pytest.raises(TabularError) as error:
        attach_feedback(db_session, model=case.model, prediction_id=row.id, label="1")
    assert error.value.code == "ML_FEEDBACK_SAMPLE_REQUIRED"
    attach_feedback(
        db_session, model=case.model, prediction_id=row.id, label="0", sample_id=sample_id(row, 1)
    )
    samples = list(iter_labeled_samples(row))
    assert len(samples) == 1 and samples[0]["payload"] == {"x": 102}
    assert samples[0]["label"] == "0" and samples[0]["score"] == 0.8
    assert samples_metadata(row)[0]["label"] is None
    with pytest.raises(TabularError) as error:
        attach_feedback(
            db_session,
            model=case.model,
            prediction_id=row.id,
            label="0",
            sample_id=sample_id(row, 99),
        )
    assert error.value.code == "ML_FEEDBACK_SAMPLE_INVALID"


def test_no_retained_input_means_no_feedback(db_session, case):
    row = _rows(db_session, case.model)[0]
    row.input_storage_allowed = False
    with pytest.raises(TabularError) as error:
        attach_feedback(db_session, model=case.model, prediction_id=row.id, label="0")
    assert error.value.code == "ML_FEEDBACK_NOT_STORED"
    assert list(iter_labeled_samples(row)) == []


@pytest.mark.parametrize(
    "mode,train_count,feedback", [("original_plus_feedback", 80, 20), ("feedback_only", 80, 80)]
)
def test_modes_keep_recorded_holdout_and_cap_only_training_feedback(
    db_session, case, mode, train_count, feedback
):
    dataset, ids, evidence, partition = _materialize(db_session, case, mode)
    frame = read_frame(dataset)
    assert frame.tail(20)["x"].to_list() == list(range(60, 80))
    assert set(frame.head(train_count)["x"]).isdisjoint(range(60, 80))
    assert partition["train_rows"] == train_count and partition["test_rows"] == 20
    assert len(ids) == feedback and evidence["mode"] == mode
    assert evidence["sources"][0]["dataset_id"] == case.data.id
    assert evidence["evaluation_sha256"] == case.model.metrics_json["evaluation"]["sha256"]


def test_latest_source_is_pinned_and_never_trains_on_old_holdout(db_session, case):
    latest = register_frame(
        db_session,
        workspace_id=case.workspace.id,
        name="latest",
        frame=pl.DataFrame({"x": list(range(120)), "label": [str(i % 2) for i in range(120)]}),
    )
    latest.slug, latest.version = case.data.slug, 2
    db_session.commit()
    dataset, ids, evidence, partition = _materialize(db_session, case, "latest_dataset_version")
    assert ids == [] and partition["train_rows"] == 100
    assert read_frame(dataset).tail(20)["x"].to_list() == list(range(60, 80))
    assert evidence["sources"][1]["dataset_id"] == latest.id
    latest.status = "deleted"
    with pytest.raises(TabularError) as error:
        verify_sources(db_session, case.model, evidence)
    assert error.value.code == "ML_RETRAIN_SOURCE_CHANGED"


def test_duplicate_and_relabelled_holdout_feedback_cannot_leak(db_session, case):
    rows = _rows(db_session, case.model)
    rows[0].payload_json = [{"x": 65}]
    rows[0].label = "0"  # Different label must not make an old test row trainable.
    rows[1].payload_json = rows[2].payload_json
    rows[1].label = rows[2].label
    db_session.commit()
    dataset, ids, evidence, partition = _materialize(db_session, case, "feedback_only")
    assert len(ids) == 78
    assert 65 not in read_frame(dataset).head(partition["train_rows"])["x"].to_list()
    assert evidence["excluded_holdout"] >= 21


def test_original_source_change_and_unverified_holdout_refuse(db_session, case):
    metrics = deepcopy(case.model.metrics_json)
    case.model.metrics_json = {**metrics, "evaluation": {}}
    with pytest.raises(TabularError) as error:
        _materialize(db_session, case)
    assert error.value.code == "ML_RETRAIN_HOLDOUT_UNVERIFIED"


def test_regression_and_multiclass_concept_drift_use_correct_sample_pairs(db_session, case):
    rows = _rows(db_session, case.model)
    case.model.task = "regression"
    case.model.metrics_json = {"scores": [{"key": "mae", "value": 1}, {"key": "rmse", "value": 1}]}
    for index, row in enumerate(rows):
        row.label = str(index)
        row.output_json = [{"prediction": index + 2}]
    measured = concept_drift(case.model, rows)
    assert measured["status"] == "alert"
    assert {value["metric"]: value["value"] for value in measured["metrics"]} == {
        "mae": 2,
        "rmse": 2,
    }
    case.model.task = "classification"
    case.model.classes_json = ["a", "b", "c"]
    case.model.metrics_json = {
        "scores": [{"key": "accuracy", "value": 1}],
        "monitoring_reference": {"concept": {"f1_macro": 1}},
    }
    for index, row in enumerate(rows):
        row.label = ["a", "b", "c"][index % 3]
        row.output_json = [{"prediction": ["a", "b", "c"][(index + 1) % 3]}]
    measured = concept_drift(case.model, rows)
    assert measured["status"] == "alert"
    assert {v["metric"]: v["value"] for v in measured["metrics"]} == {"accuracy": 0, "f1_macro": 0}


def test_score_reference_compares_training_even_if_recent_windows_match(db_session, case):
    case.model.metrics_json = {
        "monitoring_reference": {
            "scores": {"source": "final_test", "values": list(range(40)), "mean": 19.5, "n": 40}
        }
    }
    rows = _rows(db_session, case.model)
    for row in rows:
        row.scores_json = {"scores": [100.0]}
    assert score_drift(rows)["status"] == "ok"
    result = score_drift(rows, case.model)
    assert result["status"] == "alert" and result["reference_source"] == "final_test"


def test_fractional_feedback_does_not_get_truncated_to_source_integer_dtype(db_session, case):
    rows = _rows(db_session, case.model)
    rows[0].payload_json = [{"x": 900.25}]
    db_session.commit()
    dataset, _, _, partition = _materialize(db_session, case, "feedback_only")
    assert 900.25 in read_frame(dataset).head(partition["train_rows"])["x"].to_list()


def test_each_scheduled_run_records_measurement_without_reproposing_same_window(
    db_session, case, monkeypatch
):
    from app.services import ml_retraining as service
    from app.tests.services.test_ml_retraining import fire

    first = fire(db_session, case, monkeypatch)
    result1 = service.monitor_cycle(db_session, model_id=case.model.id, run_id=first.id)
    second = fire(db_session, case, monkeypatch)
    result2 = service.monitor_cycle(db_session, model_id=case.model.id, run_id=second.id)
    assert result1["snapshot_id"] != result2["snapshot_id"]
    assert result2["reason"] == "ML_RETRAIN_PROPOSAL_EXISTS"
    history = service.monitoring_view(db_session, case.model)["history"]
    assert len(history) == 2
    assert all(
        "concept_drift" in value and "score_drift" in value and "data_drift" in value
        for value in history
    )


def test_combined_population_beats_feedback_only_on_a_planted_biased_feedback_case(
    db_session, case
):
    """One synthetic regression counterexample, never a production score guarantee."""
    from sklearn.linear_model import LinearRegression
    from sklearn.metrics import mean_absolute_error

    from app.tests.services.test_ml_retraining import record_partition

    source = register_frame(
        db_session,
        workspace_id=case.workspace.id,
        name="linear source",
        frame=pl.DataFrame({"x": list(range(80)), "label": [float(2 * x) for x in range(80)]}),
    )
    case.model.task, case.model.dataset_id = "regression", source.id
    record_partition(case.model, source)
    for index, row in enumerate(_rows(db_session, case.model)):
        row.payload_json = [{"x": 200 + index}]
        row.label = str(2 * (200 + index) + 10)
    db_session.commit()
    errors, heldout = [], []
    for mode in ("original_plus_feedback", "feedback_only"):
        dataset, _, _, partition = _materialize(db_session, case, mode)
        frame = read_frame(dataset).to_pandas()
        train, test = frame.iloc[: partition["train_rows"]], frame.iloc[partition["train_rows"] :]
        fitted = LinearRegression().fit(train[["x"]], train["label"])
        errors.append(mean_absolute_error(test["label"], fitted.predict(test[["x"]])))
        heldout.append(test.to_dict("records"))
    assert heldout[0] == heldout[1]
    assert errors[0] < errors[1]


def test_multiclass_score_drift_compares_confidence_not_numeric_class_ids(db_session, case):
    case.model.metrics_json = {
        "monitoring_reference": {
            "scores": {
                "source": "final_test",
                "kind": "confidence",
                "values": [0.9] * 40,
                "n": 40,
                "mean": 0.9,
            }
        }
    }
    rows = _rows(db_session, case.model)
    for row in rows:
        row.output_json = [{"prediction": "999", "confidence": 0.1}]
        row.scores_json = {"scores": [999.0]}
    result = score_drift(rows, case.model)
    assert result["status"] == "alert" and result["served_mean"] == pytest.approx(0.1)


def test_source_budget_and_class_loss_refuse_without_silent_sampling(db_session, case):
    case.data.row_count = 100001
    with pytest.raises(TabularError) as error:
        _materialize(db_session, case)
    assert error.value.code == "ML_RETRAIN_SOURCE_TOO_LARGE"
    case.data.row_count = 80
    for row in _rows(db_session, case.model):
        row.label = "0"
    with pytest.raises(TabularError) as error:
        _materialize(db_session, case, "feedback_only")
    assert error.value.code == "ML_RETRAINING_DATA_INCOMPATIBLE"


def test_feedback_migration_creates_unique_samples_and_cascades_then_downgrades():
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError

    path = Path(__file__).parents[3] / "alembic" / "versions" / "136_mlops_correctness.py"
    spec = importlib.util.spec_from_file_location("mlops_correctness_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("CREATE TABLE workspaces(id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE ml_predictions(id VARCHAR(36) PRIMARY KEY)"))
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        assert "ml_prediction_feedback" in inspect(connection).get_table_names()
        connection.execute(text("INSERT INTO workspaces VALUES ('w')"))
        connection.execute(text("INSERT INTO ml_predictions VALUES ('p')"))
        connection.execute(
            text(
                "INSERT INTO ml_prediction_feedback VALUES ('sample','p','w',0,'yes','2026-10-15',NULL)"
            )
        )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO ml_prediction_feedback VALUES ('other','p','w',0,'no','2026-10-15',NULL)"
                    )
                )
        connection.execute(text("DELETE FROM ml_predictions WHERE id='p'"))
        assert connection.execute(text("SELECT count(*) FROM ml_prediction_feedback")).scalar() == 0
        module.downgrade()
        assert "ml_prediction_feedback" not in inspect(connection).get_table_names()
