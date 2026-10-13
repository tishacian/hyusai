"""The streaming worker serves a real serialized production-harness model."""

from uuid import uuid4

import polars as pl
import pytest

from app.core.config import settings
from app.models.recipe import RecipeExecution
from app.models.tabular import MLPrediction, TabularDataset
from app.models.workspace import Workspace
from app.services import tabular_predict
from app.services.dataops.scoring import submit_score
from app.services.tabular_datasets import read_frame, register_frame
from app.tests.ml_artifacts import churn_frame, fit_churn_artifact
from app.tests.services.test_ml_predict import _register


@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    return fit_churn_artifact(tmp_path_factory.mktemp("stream-fit"))


@pytest.fixture(scope="module")
def regression_artifact(tmp_path_factory):
    return fit_churn_artifact(
        tmp_path_factory.mktemp("stream-regression-fit"), task="regression", target="arpu"
    )


def test_worker_preserves_real_predictions_and_pinned_model(
    db_session, monkeypatch, tmp_path, artifact
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "ml_score_streaming_enabled", True)
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", True)
    monkeypatch.setattr(settings, "dataops_batch_rows", 1024)
    workspace = Workspace(id=str(uuid4()), name="Stream", slug="stream", settings={})
    db_session.add(workspace)
    db_session.commit()
    model = _register(db_session, workspace, artifact)
    original = pl.from_pandas(churn_frame(5000).drop(columns=["churn"])).with_row_index("row_id")
    dataset = register_frame(db_session, workspace_id=workspace.id, name="Source", frame=original)
    db_session.commit()
    expected = tabular_predict.predict_rows(
        db_session, model, original.select(model.features).head(3).to_dicts()
    )["predictions"]
    execution = submit_score(
        db_session,
        workspace_id=workspace.id,
        model_id=model.id,
        dataset_ref={"dataset_id": dataset.id},
        version=model.version,
    )
    assert execution.status == "succeeded", execution.error
    output = db_session.get(TabularDataset, execution.output_json["dataset_id"])
    actual = read_frame(output).sort("row_id")
    assert actual.height == 5000 and actual["prediction"].head(3).to_list() == [
        str(row["prediction"]) for row in expected
    ]
    assert execution.output_json["model"]["model_id"] == model.id
    assert actual.select(original.columns).equals(original)
    journal = db_session.get(MLPrediction, execution.output_json["prediction_id"])
    assert journal.row_count == 5000 and len(journal.output_json) <= 64
    assert output.lineage_json["cardinality"] == {
        "input_rows": 5000,
        "scored_rows": 5000,
        "excluded_rows": 0,
    }
    tabular_predict.reset_cache()


@pytest.mark.parametrize("delta", [False, True])
def test_worker_preserves_native_regression_intervals_and_colliding_columns(
    db_session, monkeypatch, tmp_path, regression_artifact, delta
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "ml_score_streaming_enabled", True)
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", delta)
    monkeypatch.setattr(settings, "dataops_batch_rows", 16)
    workspace = Workspace(id=str(uuid4()), name="Intervals", slug="intervals", settings={})
    db_session.add(workspace)
    db_session.commit()
    model = _register(db_session, workspace, regression_artifact, task="regression", target="arpu")
    model.metrics_json = {
        **model.metrics_json,
        "intervals": {
            "default_level": 0.9,
            "levels": [{"level": 0.8, "q": 3.0}, {"level": 0.9, "q": 5.0}],
        },
    }
    original = (
        pl.from_pandas(churn_frame(48).drop(columns=["arpu", "churn"]))
        .with_row_index("row_id")
        .with_columns(
            pl.lit(-1.0).alias("arpu_lower"),
            pl.lit(-2.0).alias("arpu_upper"),
            pl.lit(-3.0).alias("arpu_level"),
        )
    )
    dataset = register_frame(db_session, workspace_id=workspace.id, name="Source", frame=original)
    db_session.commit()
    expected = tabular_predict.predict_rows(
        db_session, model, original.select(model.features).head(3).to_dicts()
    )["predictions"]
    execution = submit_score(
        db_session,
        workspace_id=workspace.id,
        model_id=model.id,
        dataset_ref={"dataset_id": dataset.id},
        version=model.version,
    )
    assert execution.status == "succeeded", execution.error
    output = db_session.get(TabularDataset, execution.output_json["dataset_id"])
    actual = read_frame(output).sort("row_id")
    assert actual.select(original.columns).equals(original)
    metadata = output.lineage_json["prediction_output"]
    assert metadata["target"] == "arpu" and metadata["level"] == 0.9
    for suffix, original_value in (("lower", -1.0), ("upper", -2.0), ("level", -3.0)):
        column = metadata[f"{suffix}_column"]
        assert column == f"arpu_{suffix}_2"
        assert column in execution.output_json["added_columns"]
        assert actual[f"arpu_{suffix}"].to_list() == [original_value] * 48
        assert actual[column].head(3).to_list() == pytest.approx([r[suffix] for r in expected])
    assert actual[metadata["lower_column"]].to_list() == pytest.approx(
        (actual[metadata["value_column"]] - 5.0).to_list()
    )
    assert actual[metadata["upper_column"]].to_list() == pytest.approx(
        (actual[metadata["value_column"]] + 5.0).to_list()
    )
    journal = db_session.get(MLPrediction, execution.output_json["prediction_id"])
    assert journal.output_json[:3] == expected
    assert len(journal.output_json) == 48 and journal.row_count == 48
    tabular_predict.reset_cache()


@pytest.mark.parametrize("terminal_status", [None, "failed"])
def test_worker_fences_watchdog_or_cancel_before_dataset_settlement(
    db_session, monkeypatch, tmp_path, artifact, terminal_status
):
    from app.db.base import SessionLocal
    from app.services.dataops import scoring
    from app.services.recipe_executions import finalize_execution

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "ml_score_streaming_enabled", True)
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", False)
    workspace = Workspace(id=str(uuid4()), name="Fence", slug="fence", settings={})
    db_session.add(workspace)
    db_session.commit()
    model = _register(db_session, workspace, artifact)
    dataset = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Source",
        frame=pl.from_pandas(churn_frame(8).drop(columns=["churn"])),
    )
    db_session.commit()
    original_write = scoring.write_batches

    def finish_writes_then_revoke(*args, **kwargs):
        paths = original_write(*args, **kwargs)
        with SessionLocal() as authority:
            active = authority.query(RecipeExecution).filter_by(workspace_id=workspace.id).one()
            assert active.status == "running"
            active.cancel_requested = True
            if terminal_status:
                finalize_execution(active, status=terminal_status, error="watchdog expired")
            authority.commit()
        return paths

    def refuse_settlement(*args, **kwargs):
        pytest.fail("A revoked execution must not begin dataset settlement")

    monkeypatch.setattr(scoring, "write_batches", finish_writes_then_revoke)
    monkeypatch.setattr(scoring, "settle_files", refuse_settlement)
    execution = submit_score(
        db_session,
        workspace_id=workspace.id,
        model_id=model.id,
        dataset_ref={"dataset_id": dataset.id},
    )
    assert execution.status == (terminal_status or "cancelled")
    if terminal_status:
        assert execution.error == "watchdog expired"
    assert not execution.output_json
    output = db_session.get(TabularDataset, execution.input_json["output_id"])
    assert output.status == "failed" and not output.lineage_json
    assert db_session.query(MLPrediction).filter_by(workspace_id=workspace.id).count() == 0
    db_session.refresh(model)
    assert model.predict_count == 0
    tabular_predict.reset_cache()
