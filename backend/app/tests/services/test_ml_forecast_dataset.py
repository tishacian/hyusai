"""Forecast worker output reaches the shared dataset plane and inference journal."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.config import settings
from app.db import base
from app.models.tabular import MLModel, MLPrediction
from app.models.workspace import Workspace
from app.services.ml import forecast_serving
from app.services.tabular_datasets import read_frame, reserve_frame


@pytest.mark.parametrize("delta", [False, True])
def test_forecast_worker_persists_timestamped_dataset_and_journal(
    db_session, tmp_path, monkeypatch, delta
):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "dataops_write_delta_enabled", delta)
    monkeypatch.setattr(base, "SessionLocal", lambda: nullcontext(db_session))
    workspace = Workspace(id=str(uuid4()), name="Forecast", slug="forecast-output", settings={})
    model = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Demand",
        slug="demand",
        version=2,
        family="forecasting",
        task="forecasting",
        target="count",
        features=[],
        algo="linear",
        status="ready",
        spec_json={},
        metrics_json={},
    )
    db_session.add_all([workspace, model])
    db_session.commit()
    output = reserve_frame(
        db_session,
        workspace_id=workspace.id,
        name="Demand forecast",
        source="score",
        produced_by="ml_forecast_v1",
        node_id="forecast",
    )
    first = datetime(2026, 10, 9, tzinfo=UTC)
    rows = [
        {
            "series": "count",
            "timestamp": str(first + timedelta(days=step)),
            "pred": float(20 + step),
            "lower_bound": float(17 + step),
            "upper_bound": float(23 + step),
        }
        for step in range(28)
    ]
    monkeypatch.setattr(
        forecast_serving,
        "answer",
        lambda *args, **kwargs: {
            "forecast": rows,
            "horizon": 28,
            "interval_level": 0.8,
            "frequency": "D",
            "series": ["count"],
        },
    )

    result = forecast_serving.forecast_into(output.id, model.id, horizon=28, level=0.8)

    assert result["status"] == "ready", output.error
    assert result["block"]["version"] == 2
    db_session.refresh(output)
    frame = read_frame(output)
    assert frame.columns == ["series", "timestamp", "step", "pred", "lower_bound", "upper_bound"]
    assert frame["timestamp"].to_list() == [first + timedelta(days=step) for step in range(28)]
    assert frame["step"].to_list() == list(range(1, 29))
    assert frame["pred"].to_list() == [row["pred"] for row in rows]
    assert output.lineage_json["storage"]["format"] == ("delta" if delta else "parquet")
    assert output.lineage_json["model"]["model_id"] == model.id
    journal = db_session.query(MLPrediction).filter(MLPrediction.dataset_id == output.id).one()
    assert journal.served_id == model.id and journal.served_version == 2
    assert journal.row_count == 28 and journal.output_json[-1]["step"] == 28

    # A delivered result cannot be overwritten or double-counted on redelivery.
    assert forecast_serving.forecast_into(output.id, model.id)["status"] == "ready"
    assert db_session.query(MLPrediction).filter(MLPrediction.dataset_id == output.id).count() == 1
