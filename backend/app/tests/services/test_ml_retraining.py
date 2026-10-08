"""Schedule → evidence → human gate → separate challenger, without auto-promotion."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from app.models.decision import Decision
from app.models.run import Run
from app.models.run_schedule import RunSchedule
from app.models.skill import Skill
from app.models.tabular import MLModel, MLPrediction, TabularDataset
from app.models.workspace_job import WorkspaceJob
from app.resources.ml_drift import build_reference
from app.services import ml_retraining as service
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.tabular_datasets import TabularError, register_frame
from app.tests.api.test_runs_hitl_auth import _seed_pending_run, _client, _stub_durable_ordinary_hitl_resume  # noqa: F401
from app.tests.services.test_ml_training import enabled, store, _stub_harness  # noqa: F401
from app.tests.services.test_ml_registry import registry  # noqa: F401


@pytest.fixture()
def case(db_session, enabled, store):
    import polars as pl
    workspace, owner, other, member, _, _, _ = _seed_pending_run(db_session)
    member.role_template = "workspace_admin"
    skills = [Skill(id=str(uuid4()), is_seeded="Y", **deepcopy(next(
        row for row in SEED_SKILLS if row["slug"] == slug)))
        for slug in (service.MONITOR_SKILL, service.RETRAIN_SKILL)]
    db_session.add_all(skills)
    data = register_frame(db_session, workspace_id=workspace.id, name="Source",
        frame=pl.DataFrame({"x": list(range(80)), "label": [str(i % 2) for i in range(80)]}))
    model = MLModel(id=str(uuid4()), workspace_id=workspace.id, name="Classifier", slug="original-slug",
        task="classification", target="label", features=["x"], algo="linear", status="ready",
        dataset_id=data.id, is_champion=True, test_size=.25, cross_validation=0, version=1,
        params_json={"knobs": {}}, spec_json={},
        metrics_json={"monitoring_reference": build_reference(pd.DataFrame({"x": list(range(80))}))},
        signature_json={"inputs": [{"name": "x", "kind": "number"}]})
    db_session.add(model)
    for i in range(80):
        db_session.add(MLPrediction(id=str(uuid4()), workspace_id=workspace.id, model_id=model.id,
            served_id=model.id, served_version=1, slug=model.slug, caller="session", row_count=2,
            payload_json=[{"x": 200+i}, {"x": -999}], output_json=[{"prediction": str(i % 2)}],
            scores_json={}, label=str(i % 2), labeled_at=datetime.utcnow()))
    db_session.commit()
    service.configure(db_session, model=model, workspace=workspace, user=owner,
        body=service.MonitoringPolicy(enabled=True, propose_retraining=True))
    schedule = db_session.get(RunSchedule, service.policy_for(model)["schedule_id"])
    return SimpleNamespace(workspace=workspace, owner=owner, other=other, member=member,
                           model=model, data=data, schedule=schedule, skills=skills)


def fire(db, case, monkeypatch):
    from app.services.run_engine import scheduler
    dispatched=[]
    monkeypatch.setattr(scheduler, "_dispatch_run", dispatched.append)
    outcome = scheduler._fire_schedule(db, case.schedule, now=datetime.utcnow())
    assert outcome.run_id, outcome
    assert dispatched == [outcome.run_id]
    return db.get(Run, outcome.run_id)


def propose(db, case, monkeypatch):
    run = fire(db, case, monkeypatch)
    if run.flow_snapshot is None:
        run.flow_snapshot = service._flow(case.model.id)
        db.commit()
    result = service.monitor_cycle(db, model_id=case.model.id, run_id=run.id)
    assert result["proposed"], result
    job = db.get(WorkspaceJob, result["proposal_id"])
    return run, job


def approve(db, case, run, job):
    binding = service.make_binding(db, proposal_id=job.id, run=run)
    decision = Decision(id=str(uuid4()), workspace_id=case.workspace.id, scope="run", target_id=run.id,
        kind="hitl_approval", status="accepted", title="Retrain", rationale={"model_retraining": binding},
        human_confirmed_by=case.owner.id, human_confirmed_at=datetime.utcnow())
    db.add(decision)
    service.bind_decision(db, decision, binding)
    db.commit()
    return decision


def test_schedule_is_canonical_and_policy_reuses_existing_flow(db_session, case, monkeypatch):
    from app.services.chains.dag_validator import validate_flow
    assert not [issue for issue in validate_flow(service._flow(case.model.id)) if issue.level == "error"]
    run = fire(db_session, case, monkeypatch)
    assert run.trigger == "scheduler"
    assert run.flow_version_id and run.flow_snapshot == service._flow(case.model.id)
    assert case.schedule.cron_expr == "0 * * * *"
    original_id = case.schedule.id
    service.configure(db_session, model=case.model, workspace=case.workspace, user=case.owner,
        body=service.MonitoringPolicy(enabled=True, interval_minutes=360))
    assert service.policy_for(case.model)["schedule_id"] == original_id
    assert case.schedule.cron_expr == "0 */6 * * *"
    service.configure(db_session, model=case.model, workspace=case.workspace, user=case.owner,
        body=service.MonitoringPolicy(enabled=False))
    assert not case.schedule.enabled and case.schedule.next_fire_at is None


def test_snapshot_is_immutable_bounded_feedback_and_repeated_window_deduplicates(db_session, case, monkeypatch):
    from app.services.tabular_datasets import read_frame
    case.model.spec_json = {"text_encoder": "minhash", "threshold": "f1"}
    db_session.commit()
    run, job = propose(db_session, case, monkeypatch)
    assert job.input_ref["training"]["spec"] == case.model.spec_json
    assert job.input_ref["training"]["name"] == "original-slug"
    assert job.input_ref["labeled_rows"] == 80
    data = db_session.get(TabularDataset, job.input_ref["dataset_id"])
    assert set(read_frame(data)["x"]) == set(range(200,280))
    result = service.monitor_cycle(db_session, model_id=case.model.id, run_id=run.id)
    assert not result["proposed"] and result["reason"] == "ML_RETRAIN_PROPOSAL_EXISTS"
    assert db_session.query(WorkspaceJob).filter_by(kind=service.SNAPSHOT_KIND).count() == 1
    assert db_session.query(MLModel).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["human", "human_real", "rejected", "automatic"])
async def test_real_scheduled_flow_pauses_and_only_a_human_can_create_challenger(
    db_session, case, registry, monkeypatch, verdict
):
    from app.services.run_engine.dag import execute_run_dag, resume_run_dag
    captured = _stub_harness(monkeypatch) if verdict != "human_real" else {}
    from app.core.config import settings
    monkeypatch.setattr(settings, "ml_train_memory_limit_mb", 4096)
    monkeypatch.setattr(settings, "ml_train_report_state_limit_mb", 0)
    run = fire(db_session, case, monkeypatch)
    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending", paused
    db_session.expire_all()
    decision = db_session.get(Decision, paused["awaiting_decision"])
    binding = decision.rationale["model_retraining"]
    assert decision.expiry_action == "reject"
    assert binding["labeled_rows"] == 80
    assert db_session.query(MLModel).count() == 1 and not captured
    if verdict.startswith("human"):
        response = _client(db_session, case.workspace, case.owner).post(
            f"/runs/{run.id}/hitl", json={"action": "accept", "expected_decision_id": decision.id})
        assert response.status_code == 200, response.text
        db_session.refresh(decision)
        assert decision.human_confirmed_by == case.owner.id
    else:
        decision.status = "rejected" if verdict == "rejected" else "accepted"
        decision.approved_by = "system:ttl"
        db_session.commit()
    result = await resume_run_dag(run.id, decision_id=decision.id)
    db_session.expire_all()
    if verdict.startswith("human"):
        assert result["status"] == "completed", result
        job = db_session.get(WorkspaceJob, binding["proposal_id"])
        model = db_session.get(MLModel, job.result["model_id"])
        assert model.status == "ready", model.error
        assert run.output_ref["model_id"] == model.id
        assert model.slug == case.model.slug and model.version == 2
        assert not model.is_champion and case.model.is_champion
        assert model.dataset_id == binding["dataset_id"]
        if verdict == "human":
            assert captured["manifest"]["features"] == ["x"]
        else:
            assert model.metrics_json["monitoring_reference"]["train_rows"] == 60
            assert model.model_uri
    else:
        assert result["status"] == "failed", result
        assert result["error"] == ("ML_RETRAIN_REJECTED" if verdict == "rejected" else "ML_RETRAIN_HUMAN_REQUIRED")
        assert db_session.query(MLModel).count() == 1 and not captured


@pytest.mark.parametrize("change,code", [
    ("policy", "ML_MONITORING_DISABLED"), ("actor", "ML_MONITORING_DISABLED"),
    ("champion", "ML_RETRAIN_PROPOSAL_CHANGED"), ("spec", "ML_RETRAIN_PROPOSAL_CHANGED"),
    ("dataset", "ML_RETRAIN_SOURCE_CHANGED"), ("bytes", "ML_RETRAIN_SOURCE_CHANGED"),
    ("missing_file", "ML_RETRAIN_SOURCE_UNAVAILABLE"), ("forged_decision", "ML_RETRAIN_HUMAN_REQUIRED"),
    ("flow", "ML_MONITORING_BINDING_INVALID"), ("binding", "ML_RETRAIN_PROPOSAL_INVALID"),
])
def test_changed_authority_or_evidence_prevents_staging(db_session, case, monkeypatch, change, code):
    run, job = propose(db_session, case, monkeypatch)
    decision = approve(db_session, case, run, job)
    if change == "policy":
        case.model.params_json = {**case.model.params_json, "mlops": {"monitoring": {"enabled": False}}}
    elif change == "actor":
        case.member.role_template = "workspace_viewer"
    elif change == "champion":
        case.model.is_champion = False
    elif change == "spec":
        case.model.spec_json = {"text_encoder": "minhash"}
    elif change == "dataset":
        data = db_session.get(TabularDataset, job.input_ref["dataset_id"])
        data.version += 1
    elif change in {"bytes", "missing_file"}:
        from pathlib import Path
        from app.core.config import settings
        data = db_session.get(TabularDataset, job.input_ref["dataset_id"])
        path = Path(settings.object_store_base_path) / data.storage_key
        if change == "bytes":
            path.write_bytes(path.read_bytes() + b"changed")
        else:
            path.unlink()
    elif change == "forged_decision":
        decision.id = str(uuid4())
    elif change == "flow":
        run.flow_snapshot = {"nodes": []}
    else:
        job.input_ref = {**job.input_ref, "labeled_rows": 1}
    db_session.commit()
    with pytest.raises(TabularError) as error:
        service.stage_retraining(db_session, proposal_id=job.id, decision_id=decision.id, run_id=run.id)
    assert error.value.code == code
    assert db_session.query(MLModel).count() == 1


def test_dropped_constant_features_do_not_block_feedback_and_evidence_is_frozen(db_session, case, monkeypatch):
    case.model.features = ["x", "constant"]
    db_session.commit()
    run, job = propose(db_session, case, monkeypatch)
    assert job.input_ref["training"]["features"] == ["x"]
    assert job.input_ref["evidence"]["badge"] == "alert"
    db_session.delete(db_session.get(WorkspaceJob, job.input_ref["snapshot_id"]))
    db_session.commit()
    assert service.make_binding(db_session, proposal_id=job.id, run=run)["evidence"]["data_drift"]["features"]


@pytest.mark.parametrize("mode", ["thin", "unlabeled", "monitor_only", "quiet"])
def test_no_proposal_without_actionable_signal_and_enough_feedback(db_session, case, monkeypatch, mode):
    rows=db_session.query(MLPrediction).filter_by(served_id=case.model.id).all()
    if mode == "thin":
        for row in rows[10:]:
            row.label = None
    elif mode == "unlabeled":
        for row in rows:
            row.label = None
    elif mode == "quiet":
        for i,row in enumerate(rows):
            row.payload_json=[{"x": i}]
    else:
        policy=service.policy_for(case.model)
        case.model.params_json={"mlops": {"monitoring": {**policy, "propose_retraining": False}}}
    db_session.commit()
    run=fire(db_session,case,monkeypatch)
    if run.flow_snapshot is None:
        run.flow_snapshot=service._flow(case.model.id)
        db_session.commit()
    result=service.monitor_cycle(db_session,model_id=case.model.id,run_id=run.id)
    assert not result["proposed"]
    assert db_session.query(WorkspaceJob).filter_by(kind=service.PROPOSAL_KIND).count() == 0


def test_approved_retrain_never_becomes_fallback_champion(db_session, case, monkeypatch, registry):
    from app.services.tabular_ml import champion_for, set_champion
    run, job=propose(db_session,case,monkeypatch)
    decision=approve(db_session,case,run,job)
    model_id=service.stage_retraining(db_session,proposal_id=job.id,decision_id=decision.id,run_id=run.id)
    model=db_session.get(MLModel,model_id)
    assert service.stage_retraining(db_session,proposal_id=job.id,decision_id=decision.id,run_id=run.id) == model_id
    model.status="ready"
    case.model.is_champion=False
    case.model.status="failed"
    db_session.commit()
    assert champion_for(db_session,workspace_id=case.workspace.id,slug=case.model.slug) is None
    set_champion(db_session,model)
    assert champion_for(db_session,workspace_id=case.workspace.id,slug=model.slug).id == model_id


@pytest.mark.asyncio
async def test_scheduled_run_without_alert_completes_without_a_gate(db_session, case, monkeypatch):
    from app.services.run_engine.dag import execute_run_dag
    for i,row in enumerate(db_session.query(MLPrediction).filter_by(served_id=case.model.id).all()):
        row.payload_json=[{"x": i}]
    db_session.commit()
    run=fire(db_session,case,monkeypatch)
    result=await execute_run_dag(run.id)
    assert result["status"] == "completed", result
    assert db_session.query(Decision).filter_by(target_id=run.id).count() == 0
    assert db_session.query(WorkspaceJob).filter_by(kind=service.SNAPSHOT_KIND).count() == 1
    assert db_session.query(MLModel).count() == 1


@pytest.mark.asyncio
async def test_retraining_run_link_projects_canonical_approval_rights(db_session, case, monkeypatch):
    from datetime import timedelta
    from app.services.run_engine.dag import execute_run_dag
    run=fire(db_session,case,monkeypatch)
    paused=await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending", paused
    db_session.expire_all()
    admin=_client(db_session,case.workspace,case.owner)
    reader=_client(db_session,case.workspace,case.other)
    detail=admin.get(f"/runs/{run.id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["hitl"]["can_decide"] is True
    assert detail.json()["hitl"]["model_retraining"]["labeled_rows"] == 80
    readonly=reader.get(f"/runs/{run.id}")
    assert readonly.status_code == 200, readonly.text
    assert readonly.json()["hitl"]["can_decide"] is False
    rejected=reader.post(f"/runs/{run.id}/hitl",json={"action":"accept","expected_decision_id":paused["awaiting_decision"]})
    assert rejected.status_code == 403
    decision=db_session.get(Decision,paused["awaiting_decision"])
    decision.expires_at=datetime.utcnow()-timedelta(seconds=1)
    db_session.commit()
    assert admin.get(f"/runs/{run.id}").json()["hitl"]["can_decide"] is False
