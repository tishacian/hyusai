"""Recoverable publication, one fit claim and cancellation of reviewed retrains."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event

import pytest

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.run import Run
from app.models.tabular import MLModel
from app.models.workspace_job import WorkspaceJob
from app.services import ml_retraining as service, tabular_ml
from app.tests.services.test_ml_retraining import case, propose, approve, enabled, store  # noqa: F401
from app.tests.services.test_ml_training import _stub_harness
from app.tests.services.test_ml_registry import registry  # noqa: F401


@pytest.fixture
def staged(db_session, case, monkeypatch):
    run, job = propose(db_session, case, monkeypatch)
    run.status = "running"
    db_session.commit()
    decision = approve(db_session, case, run, job)
    model_id = service.stage_retraining(db_session, proposal_id=job.id, decision_id=decision.id, run_id=run.id)
    model = db_session.get(MLModel, model_id)
    return run, job, model, decision


def test_ambiguous_ack_recovers_same_task_id_without_early_republish(db_session, staged, monkeypatch):
    run, job, model, _ = staged
    attempts = []
    def fail(*args):
        attempts.append(args)
        raise ConnectionError("ACK lost")
    monkeypatch.setattr(service, "_publish_retraining", fail)
    assert service.recover_retraining() == {"dispatched": 0}
    db_session.refresh(job)
    db_session.refresh(model)
    task_id = model.celery_task_id
    assert job.stage == "dispatching" and task_id
    assert service.recover_retraining() == {"dispatched": 0}
    assert len(attempts) == 1
    job.updated_at = datetime.utcnow() - timedelta(seconds=61)
    db_session.commit()
    monkeypatch.setattr(service, "_publish_retraining", lambda *args: attempts.append(args))
    assert service.recover_retraining() == {"dispatched": 1}
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    db_session.refresh(job)
    assert job.stage == "dispatched" and job.result["task_id"] == task_id


def test_two_recoverers_publish_only_one_active_dispatch(db_session, staged, monkeypatch):
    run, job, model, _ = staged
    entered, release = Event(), Event()
    calls = []
    def publish(*args):
        calls.append(args)
        entered.set()
        assert release.wait(10)
    monkeypatch.setattr(service, "_publish_retraining", publish)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(service.recover_retraining)
        assert entered.wait(10)
        try:
            assert service.recover_retraining() == {"dispatched": 0}
        finally:
            release.set()
        assert first.result(timeout=10) == {"dispatched": 1}
    assert len(calls) == 1


def test_duplicate_training_message_is_neutral_while_first_worker_fits(db_session, staged, monkeypatch, registry):
    run, job, model, _ = staged
    captured = _stub_harness(monkeypatch)
    fake = tabular_ml.supervise_harness
    entered, release = Event(), Event()
    calls = []
    def fit(*args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(10)
        return fake(*args, **kwargs)
    monkeypatch.setattr(tabular_ml, "supervise_harness", fit)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(tabular_ml.run_training, model.id)
        assert entered.wait(10)
        try:
            duplicate = tabular_ml.run_training(model.id)
            assert duplicate["status"] == "training"
            db_session.refresh(model)
            assert model.status == "training" and model.error is None
        finally:
            release.set()
        assert first.result(timeout=20)["status"] == "ready"
    db_session.refresh(model)
    assert len(calls) == 1 and captured["manifest"]
    assert not model.is_champion
    assert tabular_ml.run_training(model.id)["status"] == "ready"
    assert len(calls) == 1


def test_lost_worker_after_claim_is_never_refit(db_session, staged, monkeypatch):
    run, job, model, _ = staged
    assert service.claim_training(db_session, model)
    db_session.refresh(job)
    job.result = {**job.result, "worker_claimed_at": (datetime.utcnow() - timedelta(seconds=130)).isoformat()}
    job.updated_at = datetime.utcnow() - timedelta(seconds=130)
    db_session.commit()
    monkeypatch.setattr(settings, "ml_train_timeout_s", 1)
    monkeypatch.setattr(service, "_publish_retraining", lambda *args: pytest.fail("a claimed fit must not be replayed"))
    assert service.recover_retraining() == {"dispatched": 0}
    db_session.refresh(model)
    db_session.refresh(job)
    assert model.status == job.status == "failed"
    assert model.cancel_requested and job.error == "ML_RETRAIN_WORKER_LOST"
    assert tabular_ml.run_training(model.id)["status"] == "failed"


@pytest.mark.parametrize("status", ["cancelled", "failed"])
def test_terminal_run_cancels_pending_fit_before_dispatch(db_session, staged, monkeypatch, status):
    run, job, model, _ = staged
    run.status = status
    db_session.commit()
    monkeypatch.setattr(service, "_publish_retraining", lambda *args: pytest.fail("cancelled authority"))
    assert service.recover_retraining() == {"dispatched": 0}
    db_session.refresh(job)
    db_session.refresh(model)
    assert job.status == model.status == "cancelled"
    assert tabular_ml.run_training(model.id)["status"] == "cancelled"


@pytest.mark.parametrize("stage", ["created", "queued"])
def test_abandoned_gate_releases_the_proposal_slot(db_session, case, monkeypatch, stage):
    run, job = propose(db_session, case, monkeypatch)
    if stage == "queued":
        decision = approve(db_session, case, run, job)
        decision.status = "rejected"
    else:
        run.status = "failed"
    db_session.commit()
    service.recover_retraining()
    db_session.refresh(job)
    assert job.status == "cancelled" and job.error == "ML_RETRAIN_RUN_TERMINAL"


def test_poll_observes_run_cancellation_during_fit(db_session, staged):
    run, job, model, _ = staged
    assert service.claim_training(db_session, model)
    assert not service.retraining_cancel_requested(db_session, model)
    with SessionLocal() as other:
        other.get(Run, run.id).status = "cancelled"
        other.commit()
    assert service.retraining_cancel_requested(db_session, model)


def test_authority_revoked_before_dispatch_fails_intent_without_spending(db_session, case, staged, monkeypatch):
    run, job, model, _ = staged
    case.member.role_template = "workspace_viewer"
    db_session.commit()
    monkeypatch.setattr(service, "_publish_retraining", lambda *args: pytest.fail("revoked authority"))
    service.recover_retraining()
    db_session.refresh(job)
    db_session.refresh(model)
    assert job.status == model.status == "failed"
    assert job.error == "ML_MONITORING_DISABLED"


def test_worker_claim_is_atomic_across_two_sessions(db_session, staged):
    _, job, model, _ = staged
    with SessionLocal() as first, SessionLocal() as second:
        one, two = first.get(MLModel, model.id), second.get(MLModel, model.id)
        assert service.claim_training(first, one) is True
        assert service.claim_training(second, two) is False
    db_session.refresh(job)
    assert job.stage == "training" and job.result["worker_claimed_at"]


def test_late_harness_result_cannot_publish_ready_after_run_cancelled(db_session, staged, monkeypatch, registry):
    run, job, model, _ = staged
    _stub_harness(monkeypatch)
    fake = tabular_ml.supervise_harness
    def finish(*args, **kwargs):
        result = fake(*args, **kwargs)
        with SessionLocal() as other:
            other.get(Run, run.id).status = "cancelled"
            other.commit()
        return result
    monkeypatch.setattr(tabular_ml, "supervise_harness", finish)
    assert tabular_ml.run_training(model.id)["status"] == "cancelled"
    db_session.refresh(model)
    assert model.model_uri is None and not model.is_champion


def test_active_fit_does_not_starve_next_intent_with_one_job_budget(db_session, case, staged, monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    from uuid import uuid4
    from app.models.run_schedule import RunSchedule
    from app.models.tabular import MLPrediction

    run, active_job, model, _ = staged
    assert service.claim_training(db_session, model)
    db_session.refresh(active_job)
    active_job.updated_at = datetime.utcnow() - timedelta(seconds=20)
    # A second independent lineage has its own scheduled, approved proposal.
    source = MLModel(id=str(uuid4()), workspace_id=case.workspace.id, name="Second", slug="second-model",
        task=case.model.task, target=case.model.target, features=case.model.features, algo=case.model.algo,
        status="ready", dataset_id=case.model.dataset_id, is_champion=True, test_size=.25,
        cross_validation=0, version=1, params_json={"knobs": {}}, spec_json={},
        metrics_json=deepcopy(case.model.metrics_json), signature_json=deepcopy(case.model.signature_json))
    db_session.add(source)
    for row in db_session.query(MLPrediction).filter_by(served_id=case.model.id).all():
        db_session.add(MLPrediction(id=str(uuid4()), workspace_id=case.workspace.id, model_id=source.id,
            served_id=source.id, served_version=1, slug=source.slug, caller="session", row_count=1,
            payload_json=row.payload_json, output_json=row.output_json, scores_json={}, label=row.label,
            labeled_at=row.labeled_at))
    db_session.commit()
    service.configure(db_session, model=source, workspace=case.workspace, user=case.owner,
        body=service.MonitoringPolicy(enabled=True, propose_retraining=True))
    next_case = SimpleNamespace(**{**vars(case), "model": source,
        "schedule": db_session.get(RunSchedule, service.policy_for(source)["schedule_id"])})
    next_run, next_job = propose(db_session, next_case, monkeypatch)
    decision = approve(db_session, next_case, next_run, next_job)
    next_model_id = service.stage_retraining(db_session, proposal_id=next_job.id, decision_id=decision.id, run_id=next_run.id)
    calls = []
    monkeypatch.setattr(service, "_publish_retraining", lambda *args: calls.append(args))
    assert service.recover_retraining(limit=1) == {"dispatched": 0}
    assert not calls
    assert service.recover_retraining(limit=1) == {"dispatched": 1}
    assert calls[0][0] == next_model_id
