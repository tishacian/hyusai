"""Observed forecast alerts use the existing human gate and isolated ML runtime."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.models.skill import Skill
from app.models.tabular import MLModel, TabularDataset
from app.models.run_schedule import RunSchedule
from app.models.workspace_job import WorkspaceJob
from app.services import ml_retraining as service
from app.services.tabular_datasets import TabularError, read_frame, register_frame
from app.services.skills_registry.seed import SEED_SKILLS
from app.tests.services.test_forecast_monitoring import observed, actuals, associate, predict  # noqa: F401
from app.tests.services.test_ml_training import enabled, store  # noqa: F401
from app.tests.services.test_ml_registry import registry  # noqa: F401
from app.tests.services.test_ml_retraining import fire, approve
from app.tests.api.test_runs_hitl_auth import _stub_durable_ordinary_hitl_resume  # noqa: F401

@pytest.fixture()
def forecast_case(db_session, observed):
    for slug in (service.MONITOR_SKILL, service.RETRAIN_SKILL):
        db_session.add(Skill(id=str(uuid4()), is_seeded="Y", **deepcopy(next(row for row in SEED_SKILLS if row["slug"] == slug))))
    observed.model.spec_json = {**observed.model.spec_json, "lags": [1], "backtest_folds": 1, "fill": "refuse"}
    observed.model.params_json = {"knobs": {"alpha": 1.0}}
    db_session.commit()
    data = actuals(db_session, observed)
    associate(db_session, observed, data, follow_latest=True)
    predict(db_session, observed, offset=8)
    service.configure(db_session, model=observed.model, workspace=observed.workspace, user=observed.owner,
        body=service.MonitoringPolicy(enabled=True, propose_retraining=True))
    return SimpleNamespace(**vars(observed), actuals=data,
        schedule=db_session.get(RunSchedule, service.policy_for(observed.model)["schedule_id"]))

def proposal(db, case, monkeypatch):
    run = fire(db, case, monkeypatch)
    result = service.monitor_cycle(db, model_id=case.model.id, run_id=run.id)
    assert result["proposed"], result
    return run, db.get(WorkspaceJob, result["proposal_id"])

def test_observed_alert_freezes_complete_history_and_routes_only_after_human_approval(db_session, forecast_case, monkeypatch):
    case = forecast_case
    run, job = proposal(db_session, case, monkeypatch)
    assert job.input_ref["forecast_sources"]["new_rows"] == 30
    assert job.input_ref["labeled_rows"] == 70
    assert job.input_ref["evidence"]["forecast_actuals"]["overall"]["coverage"] == 0
    assert job.input_ref["training"]["spec"] == case.model.spec_json
    data = db_session.get(TabularDataset, job.input_ref["dataset_id"])
    assert read_frame(data)["value"].to_list() == list(range(70))
    with pytest.raises(TabularError, match="ML_RETRAIN_HUMAN_REQUIRED"):
        service.stage_retraining(db_session, proposal_id=job.id, decision_id=str(uuid4()), run_id=run.id)
    assert db_session.query(MLModel).count() == 1
    decision = approve(db_session, case, run, job)
    model_id = service.stage_retraining(db_session, proposal_id=job.id, decision_id=decision.id, run_id=run.id)
    challenger = db_session.get(MLModel, model_id)
    assert challenger.family == "forecasting" and challenger.task == "forecasting" and not challenger.is_champion
    assert challenger.spec_json["horizon"] == 30
    assert service.stage_retraining(db_session, proposal_id=job.id, decision_id=decision.id, run_id=run.id) == model_id
    sent = []
    monkeypatch.setattr(service, "_publish_retraining", lambda mid, family, task: sent.append((mid, family, task)))
    assert service.recover_retraining()["dispatched"] == 1
    assert sent[0][:2] == (model_id, "forecasting")
    assert service.claim_training(db_session, challenger)
    assert not service.claim_training(db_session, challenger)
    assert case.model.is_champion

def test_follow_latest_does_not_change_an_existing_proposal(db_session, forecast_case, monkeypatch):
    case = forecast_case
    run, job = proposal(db_session, case, monkeypatch)
    pinned = job.input_ref["forecast_sources"]["actuals_dataset"]["id"]
    next_data = actuals(db_session, case)
    assert next_data.id != pinned
    decision = approve(db_session, case, run, job)
    model_id = service.stage_retraining(db_session, proposal_id=job.id, decision_id=decision.id, run_id=run.id)
    assert db_session.get(MLModel, model_id).dataset_id == job.input_ref["dataset_id"]
    assert job.input_ref["forecast_sources"]["actuals_dataset"]["id"] == pinned

@pytest.mark.parametrize("which", ["actuals_dataset", "training_dataset", "frozen_dataset", "association"])
def test_changed_reviewed_sources_cannot_authorize_training(db_session, forecast_case, monkeypatch, which):
    case = forecast_case
    run, job = proposal(db_session, case, monkeypatch)
    decision = approve(db_session, case, run, job)
    if which == "association":
        associate(db_session, case, case.actuals, follow_latest=False)
    else:
        dataset_id = job.input_ref["dataset_id"] if which == "frozen_dataset" else job.input_ref["forecast_sources"][which]["id"]
        data = db_session.get(TabularDataset, dataset_id)
        import polars as pl
        changed = read_frame(data).with_columns((pl.col("value") + 1).alias("value"))
        register_frame(db_session, workspace_id=case.workspace.id, name=data.name, frame=changed, into=data)
        db_session.commit()
    with pytest.raises(TabularError, match="ML_RETRAIN_SOURCE_CHANGED"):
        service.stage_retraining(db_session, proposal_id=job.id, decision_id=decision.id, run_id=run.id)
    assert db_session.query(MLModel).count() == 1

def test_repeated_window_has_one_proposal_and_deletion_stops_schedule(db_session, forecast_case, monkeypatch):
    case = forecast_case
    run, job = proposal(db_session, case, monkeypatch)
    again = service.monitor_cycle(db_session, model_id=case.model.id, run_id=run.id)
    assert not again["proposed"] and again["reason"] == "ML_RETRAIN_PROPOSAL_EXISTS"
    assert db_session.query(WorkspaceJob).filter_by(kind=service.PROPOSAL_KIND).count() == 1
    from app.services.tabular_ml import delete_model
    delete_model(db_session, case.model)
    db_session.refresh(case.schedule)
    assert not case.schedule.enabled and case.schedule.next_fire_at is None
    assert db_session.get(WorkspaceJob, job.id) is not None

def test_scheduling_requires_an_explicit_valid_actuals_association(db_session, observed):
    with pytest.raises(TabularError, match="ML_FORECAST_ACTUALS_UNCONFIGURED"):
        service.configure(db_session, model=observed.model, workspace=observed.workspace, user=observed.owner,
                          body=service.MonitoringPolicy(enabled=True))
    assert not service.policy_for(observed.model).get("enabled")

@pytest.mark.asyncio
async def test_forecast_flow_stops_at_canonical_human_gate(db_session, forecast_case, monkeypatch):
    from app.services.run_engine.dag import execute_run_dag
    from app.tests.api.test_runs_hitl_auth import _client
    case = forecast_case
    run = fire(db_session, case, monkeypatch)
    result = await execute_run_dag(run.id)
    assert result["status"] == "hitl_pending", result
    db_session.expire_all()
    detail = _client(db_session, case.workspace, case.owner).get(f"/runs/{run.id}")
    assert detail.status_code == 200, detail.text
    binding = detail.json()["hitl"]["model_retraining"]
    assert binding["training"]["task"] == "forecasting"
    assert binding["evidence"]["forecast_actuals"]["overall"]["count"] == 30
    assert binding["forecast_sources"]["history_rows"] == 70
    assert db_session.query(MLModel).count() == 1

@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["human", "rejected", "automatic"])
async def test_forecast_approval_runs_real_fit_only_for_human(db_session, forecast_case, monkeypatch, registry, verdict):
    from app.core.config import settings
    from app.models.decision import Decision
    from app.services.run_engine.dag import execute_run_dag, resume_run_dag
    from app.tests.api.test_runs_hitl_auth import _client
    monkeypatch.setattr(settings, "ml_train_memory_limit_mb", 4096)
    monkeypatch.setattr(settings, "ml_train_report_state_limit_mb", 0)
    case = forecast_case
    run = fire(db_session, case, monkeypatch)
    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending", paused
    db_session.expire_all()
    decision = db_session.get(Decision, paused["awaiting_decision"])
    if verdict == "human":
        # The API persists its durable resume intent; this test explicitly drives
        # that intent through the real DAG to avoid an external broker.
        response = _client(db_session, case.workspace, case.owner).post(f"/runs/{run.id}/hitl",
            json={"action": "accept", "expected_decision_id": decision.id})
        assert response.status_code == 200, response.text
    else:
        decision.status = "rejected" if verdict == "rejected" else "accepted"
        decision.approved_by = "system:ttl"
        db_session.commit()
    result = await resume_run_dag(run.id, decision_id=decision.id)
    db_session.expire_all()
    if verdict == "human":
        assert result["status"] == "completed", result
        challenger = db_session.get(MLModel, run.output_ref["model_id"])
        assert challenger.status == "ready", challenger.error
        assert challenger.family == "forecasting" and challenger.model_uri
        assert not challenger.is_champion and case.model.is_champion
        assert challenger.version == 2 and challenger.metrics_json["forecast"]["horizon"] == 30
    else:
        assert result["status"] == "failed", result
        assert db_session.query(MLModel).count() == 1
