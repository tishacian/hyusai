"""A targeted retry adds evidence without replacing the original comparison."""

import copy
from datetime import datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.api.v1.endpoints import evaluation_campaigns as api
from app.models.run import Run, SkillInvocation
from app.models.system_flow_draft import SystemFlowDraft
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.evaluation import campaign_retries, campaigns, isolation, qualification
from app.tests.services.test_evaluation_qualified_prefix import qualified_campaign


def failed_case(db, monkeypatch, *, repetitions=1):
    http, _, campaign, workspace = qualified_campaign(db, monkeypatch, repetitions=repetitions)
    item = campaign.results[0]
    source = db.get(Run, item["candidate"]["run_id"])
    source.status, source.error, source.completed_at = (
        "failed",
        "Original failure",
        datetime.utcnow(),
    )
    db.commit()
    body = {
        "result_key": item["result_key"],
        "side": "candidate",
        "source_run_id": source.id,
        "request_key": "retry-1",
        "reason": "Dependency restored",
    }
    return http, campaign, source, workspace, body


def retry(http, campaign, body):
    return http.post(f"/evaluation/campaigns/{campaign.id}/retries", json=body)


def test_retry_adds_one_frozen_run_and_keeps_initial_comparison(db_session, monkeypatch):
    http, campaign, source, workspace, body = failed_case(db_session, monkeypatch, repetitions=2)
    original = http.get(f"/evaluation/campaigns/{campaign.id}").json()
    original_run_count = db_session.query(Run).count()
    original_jobs = db_session.query(WorkspaceJob).count()
    frozen_flow, frozen_contract = (
        copy.deepcopy(source.flow_snapshot),
        copy.deepcopy(source.execution_contract),
    )
    draft = db_session.get(SystemFlowDraft, campaign.system_id)
    draft.flow_definition = {**draft.flow_definition, "label": "Unpublished user edit"}
    db_session.commit()
    saved_draft = copy.deepcopy(draft.flow_definition)
    response = retry(http, campaign, body)
    assert response.status_code == 201, response.text
    payload = response.json()
    side = payload["results"][0]["candidate"]
    attempt = side["attempts"][0]
    assert db_session.query(Run).count() == original_run_count + 1
    assert db_session.query(WorkspaceJob).count() == original_jobs + 1
    assert len(payload["results"]) == len(original["results"])
    for before, after in zip(original["results"], payload["results"]):
        assert before["change"] == after["change"]
        for name in ("baseline", "candidate"):
            for field in ("run_id", "verdict", "status", "execution_cost", "flow_sha256"):
                assert before[name].get(field) == after[name].get(field)
    assert side["run_id"] == source.id and side["status"] == "failed"
    assert payload["status"] != "completed" and payload["retry_pending"]
    assert not side["can_retry"] and side["retry_blocked_reason"] == "attempt_active"
    assert attempt["initial_run_id"] == attempt["source_run_id"] == source.id
    assert attempt["attempt_index"] == 1 and attempt["status"] == "pending"
    assert "request_key_sha256" not in attempt and "request_sha256" not in attempt
    run = db_session.get(Run, attempt["run_id"])
    assert run.flow_snapshot == frozen_flow and run.execution_contract == frozen_contract
    assert run.parent_run_id == source.id and run.evaluation_campaign_id == campaign.id
    assert run.evaluation_binding["attempt_id"] == attempt["id"]
    assert qualification.bound_profile(db_session, run)
    assert run.input_ref["case"] == "pressure"
    assert run.execution_surface == "golden_preview"
    assert run.input_ref["execution"]["evaluation_retry_id"] == attempt["id"]
    assert draft.flow_definition == saved_draft
    assert source.error == "Original failure"
    original_slug, _ = isolation.dataset_slug(
        db_session, workspace_id=workspace.id, name="Facts", run_id=source.id
    )
    retry_slug, owner = isolation.dataset_slug(
        db_session, workspace_id=workspace.id, name="Facts", run_id=run.id
    )
    assert retry_slug != original_slug and owner == campaign.id
    with pytest.raises(ValueError, match="INVOCATION_NOT_QUALIFIED"):
        qualification.authorize_invocation(
            db_session, run, node_id="result", skill_slug="ecommerce_resolution_simulate_v1"
        )
    run.evaluation_binding = {**run.evaluation_binding, "attempt_index": 99}
    with pytest.raises(ValueError, match="BINDING_INVALID"):
        qualification.bound_profile(db_session, run)


def test_http_retry_is_idempotent_and_changed_request_is_rejected(db_session, monkeypatch):
    http, campaign, _, _, body = failed_case(db_session, monkeypatch)
    dispatches = []

    def dispatch(db, workspace, job, **kwargs):
        dispatches.append(job.id)
        job.input_ref = {**job.input_ref, "celery_task_id": "task-1"}
        return "task-1"

    monkeypatch.setattr(api, "dispatch_workspace_job", dispatch)
    first = retry(http, campaign, body)
    assert first.status_code == 201, first.text
    attempt = first.json()["results"][0]["candidate"]["attempts"][0]
    again = retry(http, campaign, body)
    assert again.status_code == 201, again.text
    assert again.json()["results"][0]["candidate"]["attempts"][0] == attempt
    assert dispatches == [attempt["job_id"]]
    assert db_session.query(Run).count() == 4
    rejected = retry(http, campaign, {**body, "reason": "Changed request"})
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "EVALUATION_RETRY_REQUEST_CHANGED"


def test_next_attempt_requires_latest_failed_source_and_keeps_history(db_session, monkeypatch):
    http, campaign, source, _, body = failed_case(db_session, monkeypatch)
    first = retry(http, campaign, body).json()["results"][0]["candidate"]["attempts"][0]
    stale = retry(http, campaign, {**body, "request_key": "second"})
    assert (
        stale.status_code == 409
        and stale.json()["detail"]["code"] == "EVALUATION_RETRY_SOURCE_CHANGED"
    )
    active = retry(
        http, campaign, {**body, "request_key": "second", "source_run_id": first["run_id"]}
    )
    assert active.status_code == 409 and active.json()["detail"]["reason"] == "attempt_active"
    run = db_session.get(Run, first["run_id"])
    run.status, run.completed_at = "failed", datetime.utcnow()
    db_session.commit()
    second = retry(http, campaign, {**body, "request_key": "second", "source_run_id": run.id})
    assert second.status_code == 201, second.text
    attempts = second.json()["results"][0]["candidate"]["attempts"]
    assert len(attempts) == 2 and attempts[0]["status"] == "failed"
    assert attempts[1]["attempt_index"] == 2 and attempts[1]["source_run_id"] == run.id
    assert attempts[1]["initial_run_id"] == source.id


@pytest.mark.parametrize("status", ["pending", "running", "hitl_pending", "completed"])
def test_nonfailed_or_active_source_is_rejected(db_session, monkeypatch, status):
    http, campaign, source, _, body = failed_case(db_session, monkeypatch)
    source.status = status
    db_session.commit()
    response = retry(http, campaign, body)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EVALUATION_RETRY_NOT_ELIGIBLE"
    assert db_session.query(Run).count() == 3


def test_successful_human_boundary_and_inflight_invocation_cannot_retry(db_session, monkeypatch):
    http, campaign, source, _, body = failed_case(db_session, monkeypatch)
    source.status = "cancelled"
    source.checkpoints = [{"kind": "evaluation_boundary", "boundary": "human_gate"}]
    db_session.commit()
    assert retry(http, campaign, body).status_code == 409
    source.status, source.checkpoints = "failed", []
    db_session.add(
        SkillInvocation(run_id=source.id, skill_slug="workbench_echo_v1", status="running")
    )
    db_session.commit()
    state = http.get(f"/evaluation/campaigns/{campaign.id}").json()["results"][0]["candidate"]
    assert not state["can_retry"] and state["retry_blocked_reason"] == "attempt_active"
    response = retry(http, campaign, body)
    assert response.status_code == 409 and response.json()["detail"]["reason"] == "attempt_active"


def test_invalid_frozen_source_and_corpus_change_refuse_before_dispatch(db_session, monkeypatch):
    http, campaign, source, _, body = failed_case(db_session, monkeypatch)
    original = copy.deepcopy(source.flow_snapshot)
    source.flow_snapshot = {**original, "label": "Tampered"}
    db_session.commit()
    response = retry(http, campaign, body)
    assert (
        response.status_code == 409
        and response.json()["detail"]["code"] == "EVALUATION_RETRY_SOURCE_INVALID"
    )
    source.flow_snapshot = original
    db_session.commit()
    monkeypatch.setattr(campaigns, "corpus_manifest", lambda *args: [{"id": "changed"}])
    response = retry(http, campaign, body)
    assert (
        response.status_code == 409
        and response.json()["detail"]["code"] == "EVALUATION_RETRY_CORPUS_CHANGED"
    )
    assert db_session.query(Run).count() == 3


def test_retry_honors_workspace_and_run_acl(db_session, monkeypatch):
    http, campaign, source, _, body = failed_case(db_session, monkeypatch)
    from fastapi import HTTPException

    def deny(*args, **kwargs):
        if kwargs["run_id"] == source.id:
            raise HTTPException(404, "Run not found")

    monkeypatch.setattr(api, "_visible_run_or_404", deny)
    assert retry(http, campaign, body).status_code == 404
    http.app.dependency_overrides[api.get_current_workspace] = lambda: Workspace(id="other")
    assert retry(http, campaign, body).status_code == 404
    assert db_session.query(Run).count() == 3


def test_worker_dispatches_one_run_and_redelivery_does_not_restart_it(db_session, monkeypatch):
    http, campaign, _, _, body = failed_case(db_session, monkeypatch, repetitions=2)
    response = retry(http, campaign, body)
    assert response.status_code == 201, response.text
    attempt = response.json()["results"][0]["candidate"]["attempts"][0]
    factory = sessionmaker(bind=db_session.get_bind())
    monkeypatch.setattr("app.db.base.SessionLocal", factory)
    scheduled = []

    def schedule(run_id):
        scheduled.append(run_id)
        # Nested delivery observes the committed exclusive claim, not a second dispatch.
        assert campaign_retries.run_retry_job(attempt["job_id"])["status"] == "running"
        with factory() as other:
            run = other.get(Run, run_id)
            assert run.status == "pending"
            run.status, run.output_ref = "completed", {"retained": "retry proof"}
            other.commit()

    monkeypatch.setattr("app.services.run_engine.schedule_run", schedule)
    result = campaigns.run_campaign_job(attempt["job_id"])
    assert result["retry_run_id"] == attempt["run_id"]
    assert campaigns.run_campaign_job(attempt["job_id"]) == result
    assert scheduled == [attempt["run_id"]]
    db_session.expire_all()
    updated = http.get(f"/evaluation/campaigns/{campaign.id}").json()
    assert not updated["retry_pending"]
    assert updated["results"][0]["candidate"]["status"] == "failed"
    assert updated["results"][0]["candidate"]["attempts"][0]["status"] == "completed"
    assert db_session.get(WorkspaceJob, campaign.job_id).status == "queued"
    assert len(updated["results"]) == 2


def test_dispatch_failure_changes_only_the_new_attempt(db_session, monkeypatch):
    http, campaign, _, _, body = failed_case(db_session, monkeypatch, repetitions=2)
    monkeypatch.setattr(api, "dispatch_workspace_job", lambda *args, **kwargs: None)
    response = retry(http, campaign, body)
    assert response.status_code == 201, response.text
    side = response.json()["results"][0]["candidate"]
    assert side["status"] == "failed" and side["attempts"][0]["status"] == "cancelled"
    assert side["can_retry"] and not response.json()["retry_pending"]
    assert response.json()["results"][1]["candidate"]["status"] == "pending"
    assert db_session.get(WorkspaceJob, campaign.job_id).status == "queued"


def test_corpus_change_while_queued_closes_only_the_retry_before_execution(db_session, monkeypatch):
    http, campaign, source, _, body = failed_case(db_session, monkeypatch)
    response = retry(http, campaign, body)
    assert response.status_code == 201, response.text
    attempt = response.json()["results"][0]["candidate"]["attempts"][0]
    factory = sessionmaker(bind=db_session.get_bind())
    monkeypatch.setattr("app.db.base.SessionLocal", factory)
    monkeypatch.setattr(campaigns, "corpus_manifest", lambda *args: [{"id": "changed"}])
    scheduled = []
    monkeypatch.setattr(
        "app.services.run_engine.schedule_run", lambda run_id: scheduled.append(run_id)
    )
    assert campaign_retries.run_retry_job(attempt["job_id"])["status"] == "failed"
    assert scheduled == []
    db_session.expire_all()
    payload = http.get(f"/evaluation/campaigns/{campaign.id}").json()
    assert not payload["retry_pending"]
    assert payload["results"][0]["candidate"]["attempts"][0]["status"] == "cancelled"
    assert db_session.get(Run, source.id).error == "Original failure"
    assert db_session.get(WorkspaceJob, campaign.job_id).status == "queued"
