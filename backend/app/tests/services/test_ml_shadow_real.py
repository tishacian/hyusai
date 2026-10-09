"""Real MLflow artifact and native subprocess boundaries, no provider calls."""
import time
from pathlib import Path

import pytest

from app.models.tabular import MLPrediction
from app.models.workspace_job import WorkspaceJob
from app.services import ml_shadow as shadow, tabular_predict
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_predict import (
    churn_artifact, store, workspace, _register, _row,  # noqa: F401
)


def test_primary_prediction_unchanged_with_real_isolated_challenger(db_session, workspace, churn_artifact, monkeypatch):
    primary = _register(db_session, workspace, churn_artifact)
    challenger = _register(db_session, workspace, churn_artifact, version=2, champion=False)
    monkeypatch.setattr(shadow, "_dispatch", lambda _: pytest.fail("no broker work on primary request"))
    baseline = tabular_predict.predict_rows(db_session, primary, [_row()])
    shadow.configure(db_session, model=primary, config=shadow.ShadowConfig(enabled=True, sample_percent=100, timeout_s=60))
    served = tabular_predict.predict_rows(db_session, primary, [_row()])
    variable = {"prediction_id", "duration_ms", "load_ms", "cached"}
    assert {key: value for key, value in served.items() if key not in variable} == {
        key: value for key, value in baseline.items() if key not in variable}
    assert set(served) == set(baseline)
    job = db_session.query(WorkspaceJob).filter_by(workspace_id=workspace.id, kind=shadow.KIND).one()
    prediction_before = db_session.get(MLPrediction, served["prediction_id"]).output_json
    result = shadow.run_shadow(job.id)
    assert result["status"] == "completed", result
    db_session.expire_all()
    assert primary.predict_count == 2 and challenger.predict_count == 0
    assert db_session.query(MLPrediction).filter_by(workspace_id=workspace.id).count() == 2
    assert db_session.get(MLPrediction, served["prediction_id"]).output_json == prediction_before
    assert job.result["predictions"] == served["predictions"]
    assert shadow.summary(db_session, model=primary)["comparison"]["agreement"] == 1


def test_timeout_terminates_native_call_in_real_subprocess(db_session, workspace, churn_artifact, monkeypatch, tmp_path):
    from app.services import recipe_executions
    model = _register(db_session, workspace, churn_artifact)
    native = tmp_path / "native.py"
    native.write_text("import ctypes\nctypes.CDLL(None).sleep(30)\n")
    real = recipe_executions.supervise_harness
    def run_native(argv, **kwargs):
        return real([argv[0], str(native)], **kwargs)
    monkeypatch.setattr(recipe_executions, "supervise_harness", run_native)
    started = time.monotonic()
    with pytest.raises(TabularError) as exc:
        shadow._score_isolated(model, [_row()], timeout_s=1)
    assert exc.value.code == "ML_SHADOW_TIMEOUT"
    assert time.monotonic() - started < 5
