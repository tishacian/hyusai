"""Streaming serving writes accounting with settlement, never sample-sized totals."""

import pytest

from app.core.config import settings
from app.models.ml_operations import MLInferenceUsage
from app.models.tabular import MLPrediction, TabularDataset
from app.services import ml_operations, tabular_predict
from app.services.dataops import rollout, scoring
from app.tests.services.test_ml_predict import (  # noqa: F401
    churn_artifact,
    scoring_dataset,
    store,
    workspace,
)
from app.tests.services.test_ml_predict import model as scoring_model  # noqa: F401


@pytest.fixture(name="case")
def _case(request, monkeypatch):
    model = request.getfixturevalue("scoring_model")
    dataset = request.getfixturevalue("scoring_dataset")
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    monkeypatch.setattr(settings, "connector_framework_enabled", False)
    monkeypatch.setitem(settings.__dict__, "ml_operations_enabled", True)
    monkeypatch.setattr(rollout, "enabled", lambda *args: True)
    return model, dataset


def submit(db, case):
    model, dataset = case
    return scoring.submit_score(
        db,
        workspace_id=model.workspace_id,
        model_id=model.id,
        dataset_ref={"dataset_id": dataset.id},
    )


def test_stream_success_counts_full_output_and_honors_storage_policy(db_session, case):
    from app.models.workspace import Workspace

    model, dataset = case
    workspace_row = db_session.get(Workspace, model.workspace_id)
    workspace_row.settings = {"ml": {"store_inputs": False}}
    db_session.commit()
    execution = submit(db_session, case)
    assert execution.status == "succeeded", execution.error
    db_session.expire_all()
    journal = db_session.query(MLPrediction).one()
    usage = db_session.query(MLInferenceUsage).one()
    assert usage.row_count == journal.row_count == dataset.row_count == 30
    assert usage.error_code is None and usage.caller == "score"
    assert usage.id == ml_operations.digest(model.workspace_id, journal.id)
    assert usage.measured_cost_usd is None and usage.cpu_seconds is None
    assert journal.input_storage_allowed is False
    assert journal.payload_json == [] and journal.dataset_id is None
    scoring.run_score(execution.id)
    assert db_session.query(MLInferenceUsage).count() == 1


def test_stream_failure_records_no_success_rows_and_no_duplicate(db_session, case, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("ML_SCORE_TEST_FAILED")

    monkeypatch.setattr(tabular_predict, "load_pipeline", fail)
    execution = submit(db_session, case)
    assert execution.status == "failed"
    db_session.expire_all()
    usage = db_session.query(MLInferenceUsage).one()
    assert usage.row_count == 0 and usage.error_code == "ML_SCORE_TEST_FAILED"
    assert db_session.query(MLPrediction).count() == 0
    scoring.run_score(execution.id)
    assert db_session.query(MLInferenceUsage).count() == 1


def test_stream_journal_and_usage_roll_back_with_failed_settlement(db_session, case, monkeypatch):
    actual = ml_operations.record_inference

    def fail_success_record(db, **kwargs):
        if not kwargs.get("error_code"):
            assert db.query(MLPrediction).count() == 1
            actual(db, **kwargs)
            raise RuntimeError("abort usage transaction")
        return actual(db, **kwargs)

    monkeypatch.setattr(ml_operations, "record_inference", fail_success_record)
    execution = submit(db_session, case)
    assert execution.status == "failed"
    db_session.expire_all()
    assert db_session.query(MLPrediction).count() == 0
    usage = db_session.query(MLInferenceUsage).one()
    assert usage.row_count == 0 and usage.error_code == "ML_INFERENCE_FAILED"
    output = db_session.get(TabularDataset, execution.input_json["output_id"])
    assert output.status == "failed"
