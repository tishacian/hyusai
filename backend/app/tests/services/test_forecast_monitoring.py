"""Observed quality measures retained, pre-outcome forecasts and pinned bytes."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import polars as pl
import pytest
from app.models.tabular import MLModel, MLPrediction
from app.models.workspace import Workspace
from app.services.ml import forecast_monitoring as service
from app.services.ml.forecast_serving import _journal_forecast
from app.services.tabular_datasets import TabularError, register_frame, read_frame
from app.tests.api.test_runs_hitl_auth import _seed_pending_run
from app.tests.services.test_ml_training import enabled, store  # noqa: F401

START = datetime(2025, 1, 1)
NOW = datetime(2025, 4, 1)

@pytest.fixture()
def observed(db_session, enabled, store):
    workspace, owner, other, member, _, _, _ = _seed_pending_run(db_session)
    member.role_template = "workspace_admin"
    data = register_frame(db_session, workspace_id=workspace.id, name="Forecast history",
        frame=pl.DataFrame({"date": [START + timedelta(days=i) for i in range(40)], "value": [float(i) for i in range(40)]}))
    model = MLModel(id=str(uuid4()), workspace_id=workspace.id, name="Demand", slug="demand",
        family="forecasting", task="forecasting", target="value", features=[], algo="linear", status="ready",
        dataset_id=data.id, is_champion=True, version=1, params_json={"knobs": {}},
        spec_json={"time_column": "date", "shape": "single", "horizon": 30, "frequency": "D", "interval_level": .8},
        metrics_json={"mae": 999}, signature_json={})
    db_session.add(model)
    db_session.commit()
    return SimpleNamespace(workspace=workspace, owner=owner, member=member, model=model, data=data)

def actuals(db, case, *, records=None, name="Observed"):
    records = records if records is not None else {"date": [START + timedelta(days=i) for i in range(40, 70)],
                                                  "value": [float(i) for i in range(40, 70)]}
    dataset = register_frame(db, workspace_id=case.workspace.id, name=name, frame=pl.DataFrame(records))
    db.commit()
    return dataset

def associate(db, case, dataset, **options):
    return service.associate(db, model=case.model, workspace=case.workspace, user=case.owner,
                             body=service.ActualsBinding(dataset_id=dataset.id, **options))

def predict(db, case, *, offset=0, when=START + timedelta(days=39), version=1, workspace=None, rows=None):
    answers = rows if rows is not None else [{"series": "value", "timestamp": (START + timedelta(days=i)).isoformat(),
        "pred": float(i) + offset, "lower_bound": float(i)-1 + offset, "upper_bound": float(i)+1 + offset} for i in range(40, 70)]
    row = MLPrediction(id=str(uuid4()), workspace_id=workspace or case.workspace.id,
        model_id=case.model.id, served_id=case.model.id, served_version=version, slug=case.model.slug,
        caller="session", row_count=len(answers), payload_json=[], output_json=_journal_forecast(answers, .8),
        scores_json={}, created_at=when)
    db.add(row)
    db.commit()
    return row

def test_observed_quality_is_separate_and_deduplicates_calls(db_session, observed):
    associate(db_session, observed, actuals(db_session, observed))
    first = predict(db_session, observed, offset=2)
    predict(db_session, observed, offset=0, when=START + timedelta(days=39, hours=1))
    result = service.snapshot(db_session, model=observed.model, now=NOW)
    metrics = result.report["overall"]
    assert metrics["count"] == 30 and metrics["interval_count"] == 30 and metrics["anomalies"] == 30
    assert metrics["mae"] == metrics["rmse"] == metrics["mean_interval_width"] == 2
    assert metrics["coverage"] == 0 and metrics["nominal_coverage"] == .8
    assert 3 < metrics["smape"] < 4
    assert result.report["status"] == "alert" and result.report["window"]["duplicates"] == 30
    assert {row["prediction_id"] for row in result.report["anomalies"]} == {first.id}
    assert len(result.report["by_horizon"]) == 30 and result.report["by_series"][0]["series"] == "value"
    assert observed.model.metrics_json["mae"] == 999
    assert service.snapshot(db_session, model=observed.model, now=NOW).fingerprint == result.fingerprint

def test_excludes_late_future_other_workspace_and_other_version(db_session, observed):
    associate(db_session, observed, actuals(db_session, observed))
    predict(db_session, observed, when=NOW)
    predict(db_session, observed, version=2)
    other = Workspace(id=str(uuid4()), slug=uuid4().hex, name="Other")
    db_session.add(other)
    db_session.commit()
    predict(db_session, observed, workspace=other.id)
    predict(db_session, observed)
    report = service.snapshot(db_session, model=observed.model, now=START + timedelta(days=49)).report
    assert report["overall"]["count"] == 10 and report["window"]["excluded_late"] == 30
    assert report["window"]["excluded_future"] == 20 and report["window"]["calls"] == 2
    assert report["status"] == "insufficient"

@pytest.mark.parametrize("records,code", [
    ({"date": ["bad"], "value": [1.]}, "ML_FORECAST_ACTUALS_DATE"),
    ({"date": [START], "value": [float("nan")]}, "ML_FORECAST_ACTUALS_NUMERIC"),
    ({"date": [START], "value": [float("inf")]}, "ML_FORECAST_ACTUALS_NUMERIC"),
    ({"date": [START], "value": [True]}, "ML_FORECAST_ACTUALS_NUMERIC"),
    ({"date": [START, START], "value": [1., 1.]}, "ML_FORECAST_ACTUALS_DUPLICATE"),
    ({"date": ["2025-01-01T01:00:00+01:00", "2025-01-01T00:00:00Z"], "value": [1., 2.]}, "ML_FORECAST_ACTUALS_DUPLICATE"),
    ({"wrong_time": [START], "value": [1.]}, "ML_FORECAST_ACTUALS_COLUMNS"),
])
def test_invalid_actuals_are_refused_atomically(db_session, observed, records, code):
    dataset = actuals(db_session, observed, records=records)
    with pytest.raises(TabularError, match=code):
        associate(db_session, observed, dataset)
    assert service.binding_for(observed.model) == {}

def test_actual_bytes_and_ready_state_reverified(db_session, observed):
    dataset = actuals(db_session, observed)
    associate(db_session, observed, dataset)
    register_frame(db_session, workspace_id=observed.workspace.id, name=dataset.name,
                   frame=pl.DataFrame({"date": [START], "value": [99.]}), into=dataset)
    db_session.commit()
    assert service.report(db_session, model=observed.model)["reason"] == "ML_FORECAST_ACTUALS_CHANGED"
    dataset.status = "deleted"
    db_session.commit()
    assert service.report(db_session, model=observed.model)["status"] == "unavailable"

def test_follow_latest_is_explicit_and_snapshot_pins_exact_version(db_session, observed):
    first = actuals(db_session, observed)
    associate(db_session, observed, first)
    second = actuals(db_session, observed, records={"date": [START + timedelta(days=40)], "value": [41.]})
    assert second.slug == first.slug and second.version == 2
    assert service.snapshot(db_session, model=observed.model, now=NOW).actuals.id == first.id
    associate(db_session, observed, first, follow_latest=True)
    pinned = service.snapshot(db_session, model=observed.model, now=NOW)
    assert pinned.actuals.id == second.id and pinned.report["dataset"]["follow_latest"]
    third = actuals(db_session, observed, records={"date": ["bad"], "value": [99.]})
    assert service.report(db_session, model=observed.model)["reason"] == "ML_FORECAST_ACTUALS_DATE"
    assert third.version == 3  # Invalid latest never silently falls back.
    history, provenance = service.materialize_training_history(db_session, model=observed.model, snapshot=pinned)
    assert history.row_count == 41 and provenance["actuals_dataset"]["id"] == second.id

def test_combined_history_preserves_train_and_excludes_future(db_session, observed):
    associate(db_session, observed, actuals(db_session, observed))
    snap = service.snapshot(db_session, model=observed.model, now=START + timedelta(days=49))
    history, provenance = service.materialize_training_history(db_session, model=observed.model, snapshot=snap)
    assert history.row_count == 50 and provenance["new_rows"] == 10
    assert read_frame(history)["value"].to_list() == list(range(50))
    assert provenance["training_dataset"]["sha256"] and provenance["actuals_dataset"]["sha256"]
    assert history.lineage_json["window_sha256"] == snap.fingerprint

def test_retraining_refuses_conflicts_and_missing_covariates(db_session, observed):
    observed.model.spec_json = {**observed.model.spec_json, "shape": "multivariate", "exog": {"other": "past"}}
    db_session.commit()
    associate(db_session, observed, actuals(db_session, observed))
    snap = service.snapshot(db_session, model=observed.model, now=NOW)
    with pytest.raises(TabularError, match="ML_FORECAST_ACTUALS_COLUMNS"):
        service.materialize_training_history(db_session, model=observed.model, snapshot=snap)
    observed.model.spec_json = {**observed.model.spec_json, "shape": "single", "exog": {}}
    db_session.commit()
    conflicted = actuals(db_session, observed, records={"date": [START, START + timedelta(days=41)], "value": [999., 41.]})
    associate(db_session, observed, conflicted)
    with pytest.raises(TabularError, match="ML_FORECAST_HISTORY_CONFLICT"):
        service.materialize_training_history(db_session, model=observed.model,
            snapshot=service.snapshot(db_session, model=observed.model, now=NOW))

def test_panel_series_and_horizon_alignment(db_session, observed):
    observed.model.spec_json = {**observed.model.spec_json, "shape": "panel", "series_columns": ["shop", "item"]}
    db_session.commit()
    associate(db_session, observed, actuals(db_session, observed, records={"date": [START + timedelta(days=40)]*2,
        "value": [10., 20.], "shop": ["A", "B"], "item": ["x", "x"]}))
    predict(db_session, observed, rows=[{"series": "A · x", "timestamp": "2025-02-10", "pred": 10.},
                                      {"series": "B · x", "timestamp": "2025-02-10", "pred": 19.}])
    report = service.snapshot(db_session, model=observed.model, now=NOW).report
    assert report["overall"]["count"] == 2 and report["overall"]["mae"] == .5
    assert report["by_horizon"][0]["horizon"] == 1 and len(report["by_horizon"]) == 1
    assert len(report["by_series"]) == 2

def test_panel_identifier_collision_refused(db_session, observed):
    observed.model.spec_json = {**observed.model.spec_json, "shape": "panel", "series_columns": ["shop", "item"]}
    db_session.commit()
    dataset = actuals(db_session, observed, records={"date": [START, START+timedelta(days=1)], "value": [1., 2.],
        "shop": ["A · B", "A"], "item": ["C", "B · C"]})
    with pytest.raises(TabularError, match="ML_FORECAST_ACTUALS_SERIES_COLLISION"):
        associate(db_session, observed, dataset)

def test_legacy_intervals_have_no_invented_nominal_level(db_session, observed):
    associate(db_session, observed, actuals(db_session, observed))
    row = predict(db_session, observed)
    row.output_json = [{k:v for k,v in point.items() if k != "interval_level"} for point in row.output_json]
    db_session.commit()
    report = service.snapshot(db_session, model=observed.model, now=NOW).report
    assert report["overall"]["count"] == 30 and report["overall"]["mae"] == 0
    assert report["overall"]["interval_count"] == 0 and report["status"] == "insufficient"

def test_budget_and_journal_truncation_are_explicit(db_session, observed, monkeypatch):
    associate(db_session, observed, actuals(db_session, observed))
    row = predict(db_session, observed)
    row.row_count = 300
    db_session.commit()
    assert service.snapshot(db_session, model=observed.model, now=NOW).report["window"]["truncated"]
    monkeypatch.setattr(service, "MAX_ROWS", 5)
    with pytest.raises(TabularError, match="ML_FORECAST_ACTUALS_TOO_LARGE"):
        service.snapshot(db_session, model=observed.model, now=NOW)

def test_extreme_finite_metrics_are_json_safe():
    import json
    result = service._metrics([{"pred": 1e308, "actual": -1e308, "lower_bound": None, "upper_bound": None},
                               {"pred": 0., "actual": 0., "lower_bound": None, "upper_bound": None}])
    assert result["smape"] == 100
    json.dumps(result, allow_nan=False)
