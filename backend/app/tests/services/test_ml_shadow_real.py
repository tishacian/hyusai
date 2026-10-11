"""Real MLflow artifact and native subprocess boundaries, no provider calls."""

import copy
import json
import time
from types import SimpleNamespace

import pytest

from app.models.tabular import MLPrediction
from app.models.workspace_job import WorkspaceJob
from app.services import ml_shadow as shadow
from app.services import tabular_predict
from app.services.object_store import ObjectStore, get_object_store
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_predict import (
    _register,
    _row,
    churn_artifact,  # noqa: F401
    store,  # noqa: F401
    workspace,  # noqa: F401
)


def test_primary_prediction_unchanged_with_real_isolated_challenger(
    db_session, workspace, churn_artifact, monkeypatch
):
    primary = _register(db_session, workspace, churn_artifact)
    challenger = _register(db_session, workspace, churn_artifact, version=2, champion=False)
    monkeypatch.setattr(
        shadow, "_dispatch", lambda _: pytest.fail("no broker work on primary request")
    )
    baseline = tabular_predict.predict_rows(db_session, primary, [_row()])
    shadow.configure(
        db_session,
        model=primary,
        config=shadow.ShadowConfig(enabled=True, sample_percent=100, timeout_s=60),
    )
    served = tabular_predict.predict_rows(db_session, primary, [_row()])
    variable = {"prediction_id", "captured_at", "duration_ms", "load_ms", "cached"}
    assert {key: value for key, value in served.items() if key not in variable} == {
        key: value for key, value in baseline.items() if key not in variable
    }
    assert set(served) == set(baseline)
    job = (
        db_session.query(WorkspaceJob).filter_by(workspace_id=workspace.id, kind=shadow.KIND).one()
    )
    prediction_before = db_session.get(MLPrediction, served["prediction_id"]).output_json
    result = shadow.run_shadow(job.id)
    assert result["status"] == "completed", result
    db_session.expire_all()
    assert primary.predict_count == 2 and challenger.predict_count == 0
    assert db_session.query(MLPrediction).filter_by(workspace_id=workspace.id).count() == 2
    assert db_session.get(MLPrediction, served["prediction_id"]).output_json == prediction_before
    assert job.result["predictions"] == served["predictions"]
    assert shadow.summary(db_session, model=primary)["comparison"]["agreement"] == 1


def test_timeout_terminates_native_call_in_real_subprocess(
    db_session, workspace, churn_artifact, monkeypatch, tmp_path
):
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


@pytest.mark.parametrize(
    "change,code",
    [
        ("bytes", "ML_ARTIFACT_TAMPERED"),
        ("runtime", "ML_ARTIFACT_RUNTIME_MISMATCH"),
        ("legacy", "ML_ARTIFACT_LEGACY_UNSUPPORTED"),
        ("budget", "ML_ARTIFACT_LIMIT"),
    ],
)
def test_shadow_refuses_unqualified_artifact_before_any_load(
    db_session,
    workspace,
    churn_artifact,
    monkeypatch,
    tmp_path,
    change,
    code,
):
    from app.resources import ml_shadow_harness

    model = _register(db_session, workspace, churn_artifact)
    snapshot = copy.deepcopy(shadow._snapshot(model))
    anchor = snapshot["metrics_json"]["artifact"]
    limit = shadow.MAX_ARTIFACT_BYTES
    if change == "bytes":
        # Preserve the size, so only the producer's hash can detect the change.
        original = (churn_artifact[0] / "model.skops").read_bytes()
        get_object_store().write_bytes(
            f"{model.model_uri}/model.skops", bytes([original[0] ^ 1]) + original[1:]
        )
    elif change == "runtime":
        anchor["runtime"]["scikit-learn"] = "0.0.0"
    elif change == "legacy":
        anchor.pop("contract_version")
    else:
        limit = anchor["total_bytes"] - 1
        monkeypatch.setattr(
            ObjectStore, "copy_to_local", lambda *a, **k: pytest.fail("budget must precede copying")
        )
    source, destination = tmp_path / "shadow.json", tmp_path / "result.json"
    source.write_text(
        json.dumps(
            {
                "model": snapshot,
                "rows": [_row()],
                "max_artifact_bytes": limit,
            }
        )
    )
    # Exercise the real harness gate in process, without changing this test
    # runner's Linux parent-death signal. Normal subprocess coverage is above.
    monkeypatch.setattr(ml_shadow_harness, "sys", SimpleNamespace(platform="test"))
    monkeypatch.setattr(
        tabular_predict, "_load_mlflow_model", lambda *_: pytest.fail("must refuse before MLflow")
    )
    with pytest.raises(TabularError) as refused:
        ml_shadow_harness.main(source, destination)
    assert refused.value.code == code
    assert not destination.exists()
