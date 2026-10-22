"""Concurrent targeted retries use one canonical Run and release locks before work."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.api.v1.endpoints.evaluation_campaigns import authorize_campaign
from app.models.evaluation_campaign import EvaluationCampaign
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.evaluation import campaign_retries, campaigns
from app.tests.services.test_evaluation_campaign_retries import failed_case, retry
from app.tests.services.test_evaluation_job_postgres import pg_evaluation


@pytest.fixture
def pg_retry(monkeypatch):
    yield from pg_evaluation.__wrapped__(monkeypatch)


def failed_pg_case(db, monkeypatch):
    # The shared SQLite seed lists parents first but flushes unrelated ORM
    # objects together. PostgreSQL enforces its FK dependencies immediately.
    def ordered_seed(objects):
        for obj in objects:
            db.add(obj)
            db.flush([obj])

    with monkeypatch.context() as seed_patch:
        seed_patch.setattr(db, "add_all", ordered_seed)
        return failed_case(db, monkeypatch)


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_retry_admission_creates_only_one_attempt(pg_retry, monkeypatch, same_key):
    factory, _, _ = pg_retry
    with factory() as db:
        _, campaign, source, workspace, body = failed_pg_case(db, monkeypatch)
        campaign_id, workspace_id, actor_id = campaign.id, workspace.id, source.initiated_by_user_id
    barrier = threading.Barrier(2)

    def submit(index):
        with factory() as db:
            user, workspace = db.get(User, actor_id), db.get(Workspace, workspace_id)
            request = {**body, "request_key": "same" if same_key else f"request-{index}"}
            barrier.wait(timeout=5)
            campaign = campaign_retries.lock_campaign(db, campaign_id, workspace_id)
            authorize_campaign(db, campaign, workspace, user)
            try:
                job = campaign_retries.create_retry(
                    db, campaign=campaign, workspace=workspace, user=user, body=request
                )
                job_id = job.id
                db.commit()
                return job_id
            except HTTPException as exc:
                db.rollback()
                return exc.detail["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    with factory() as db:
        campaign = db.get(EvaluationCampaign, campaign_id)
        history = campaign.results[0]["candidate"]["attempts"]
        assert len(history) == 1 and db.query(Run).count() == 4
        if same_key:
            assert results == [history[0]["job_id"]] * 2
        else:
            assert sorted(results) == sorted(
                [history[0]["job_id"], "EVALUATION_RETRY_SOURCE_CHANGED"]
            )


def test_worker_claim_is_exclusive_and_holds_no_row_lock_during_dispatch(pg_retry, monkeypatch):
    factory, engine, _ = pg_retry
    with factory() as db:
        http, campaign, _, _, body = failed_pg_case(db, monkeypatch)
        response = retry(http, campaign, body)
        assert response.status_code == 201, response.text
        attempt = response.json()["results"][0]["candidate"]["attempts"][0]
        campaign_id = campaign.id
    monkeypatch.setattr("app.db.base.SessionLocal", factory)
    started, release = threading.Event(), threading.Event()
    scheduled = []

    def schedule(run_id):
        scheduled.append(run_id)
        with engine.begin() as observer:
            assert (
                observer.execute(
                    text("SELECT id FROM evaluation_campaigns WHERE id=:id FOR UPDATE NOWAIT"),
                    {"id": campaign_id},
                ).scalar_one()
                == campaign_id
            )
            assert (
                observer.execute(
                    text("SELECT status FROM workspace_jobs WHERE id=:id FOR UPDATE NOWAIT"),
                    {"id": attempt["job_id"]},
                ).scalar_one()
                == "running"
            )
        started.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr("app.services.run_engine.schedule_run", schedule)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(campaign_retries.run_retry_job, attempt["job_id"])
        try:
            assert started.wait(timeout=5)
            second = pool.submit(campaign_retries.run_retry_job, attempt["job_id"])
            assert second.result(timeout=5) == {"job_id": attempt["job_id"], "status": "running"}
        finally:
            release.set()
        assert first.result(timeout=5)["retry_run_id"] == attempt["run_id"]
    assert scheduled == [attempt["run_id"]]


def test_campaign_refresh_preserves_a_concurrent_retry_append(pg_retry, monkeypatch):
    factory, _, _ = pg_retry
    with factory() as db:
        http, campaign, _, _, body = failed_pg_case(db, monkeypatch)
        with factory() as stale:
            old = stale.get(EvaluationCampaign, campaign.id)
            assert not old.results[0]["candidate"].get("attempts")
            response = retry(http, campaign, body)
            assert response.status_code == 201, response.text
            attempt = response.json()["results"][0]["candidate"]["attempts"][0]
            campaigns.refresh_campaign(stale, old)
            stale.commit()
    with factory() as verify:
        fresh = verify.get(EvaluationCampaign, campaign.id)
        assert fresh.results[0]["candidate"]["attempts"][0]["id"] == attempt["id"]
        assert verify.get(WorkspaceJob, attempt["job_id"]).status == "queued"
