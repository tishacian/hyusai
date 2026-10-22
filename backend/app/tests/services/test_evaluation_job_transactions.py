"""A Judge must not retain a database transaction while waiting on a provider."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import inspect

from app.db.base import SessionLocal
from app.models.run import Run
from app.models.workspace_job import WorkspaceJob
from app.services.evaluation import auto_eval, lifecycle
from app.tests.services.test_auto_eval import _seed_minimal_run


def _queued(db, monkeypatch):
    run = _seed_minimal_run(db)
    monkeypatch.setattr(lifecycle, "dispatch_workspace_job", lambda *a, **kw: "task")
    job = lifecycle.enqueue_run_evaluation(db, run, user=None, idempotency_key="once")
    ids = run.id, job.id
    db.commit()
    return ids


def _track_sessions(monkeypatch):
    sessions = []

    def factory():
        session = SessionLocal()
        sessions.append(session)
        return session

    monkeypatch.setattr(lifecycle, "SessionLocal", factory)
    monkeypatch.setattr(auto_eval, "SessionLocal", factory)
    return sessions


@pytest.mark.parametrize("provider_fails", [False, True])
def test_provider_wait_has_no_transaction_and_redelivery_does_not_repeat(
    db_session, monkeypatch, provider_fails
):
    run_id, job_id = _queued(db_session, monkeypatch)
    sessions = _track_sessions(monkeypatch)
    calls = []

    class Judge:
        async def evaluate(self, **kwargs):
            calls.append(kwargs["session_id"])
            # Reading the resolver's configuration cannot silently reacquire
            # a connection through an expired SQLAlchemy attribute.
            assert inspect(kwargs["workspace"]).detached
            assert kwargs["workspace"].id
            assert isinstance(kwargs["workspace"].settings, dict)
            assert all(not session.in_transaction() for session in sessions)
            with SessionLocal() as observer:
                assert observer.get(WorkspaceJob, job_id).status == "running"
            # The provider await no longer has a row lock, but a duplicate
            # delivery must still never call the provider a second time.
            assert lifecycle.run_evaluation_job(job_id) == {"status": "running", "job_id": job_id}
            assert all(not session.in_transaction() for session in sessions)
            if provider_fails:
                raise RuntimeError("provider offline")
            return {
                "id": str(uuid4()),
                "status": "completed",
                "scores": {},
                "composite_score": None,
                "hallucination_rate": None,
            }

    monkeypatch.setattr(auto_eval, "get_judge_service", lambda: Judge())
    first = lifecycle.run_evaluation_job(job_id)
    assert first["status"] == ("failed" if provider_fails else "completed")
    assert all(not session.in_transaction() for session in sessions)
    repeated = lifecycle.run_evaluation_job(job_id)
    assert repeated["status"] == first["status"]
    assert calls == [run_id]
    assert all(not session.in_transaction() for session in sessions)


def test_external_terminal_settlement_is_reloaded_and_releases_read_transaction(
    db_session, monkeypatch
):
    run_id, job_id = _queued(db_session, monkeypatch)
    sessions = _track_sessions(monkeypatch)
    settled = {"status": "cancelled", "reason": "operator_cancelled"}

    async def evaluate(*args, **kwargs):
        assert all(not session.in_transaction() for session in sessions)
        with SessionLocal() as other:
            job = other.get(WorkspaceJob, job_id)
            job.status = "cancelled"
            job.result = settled
            other.get(Run, run_id).evaluation_scores = settled
            other.commit()
        return {"status": "completed", "evaluation_id": "late-result"}

    monkeypatch.setattr(auto_eval, "evaluate_run_async", evaluate)
    assert lifecycle.run_evaluation_job(job_id) == settled
    assert all(not session.in_transaction() for session in sessions)
    with SessionLocal() as other:
        assert other.get(Run, run_id).evaluation_scores == settled
    # A second worker reuses the terminal command, with no stale identity map
    # or aborted transaction retained by the first settlement's early return.
    assert lifecycle.run_evaluation_job(job_id) == settled
    assert all(not session.in_transaction() for session in sessions)


@pytest.mark.parametrize("provider_fails", [False, True])
def test_late_provider_result_cannot_overwrite_concurrent_settlement(
    db_session, monkeypatch, provider_fails
):
    run_id, job_id = _queued(db_session, monkeypatch)
    sessions = _track_sessions(monkeypatch)
    settled = {"status": "cancelled", "reason": "operator_cancelled"}

    class Judge:
        async def evaluate(self, **kwargs):
            with SessionLocal() as other:
                job = other.get(WorkspaceJob, job_id)
                job.status = "cancelled"
                job.result = settled
                other.get(Run, run_id).evaluation_scores = settled
                other.commit()
            if provider_fails:
                raise RuntimeError("provider offline")
            return {"id": str(uuid4()), "status": "completed", "scores": {}}

    monkeypatch.setattr(auto_eval, "get_judge_service", lambda: Judge())
    assert lifecycle.run_evaluation_job(job_id) == settled
    assert all(not session.in_transaction() for session in sessions)
    with SessionLocal() as other:
        assert other.get(Run, run_id).evaluation_scores == settled


def test_worker_exception_releases_delivery_lock_for_recovery(db_session, monkeypatch):
    _, job_id = _queued(db_session, monkeypatch)
    sessions = _track_sessions(monkeypatch)

    async def crashed(*args, **kwargs):
        raise RuntimeError("worker interrupted")

    monkeypatch.setattr(auto_eval, "evaluate_run_async", crashed)
    with pytest.raises(RuntimeError, match="worker interrupted"):
        lifecycle.run_evaluation_job(job_id)
    assert all(not session.in_transaction() for session in sessions)

    async def recovered(*args, **kwargs):
        return {"status": "partial", "evaluation_id": "recovered"}

    monkeypatch.setattr(auto_eval, "evaluate_run_async", recovered)
    assert lifecycle.run_evaluation_job(job_id)["evaluation_id"] == "recovered"
    assert all(not session.in_transaction() for session in sessions)


def test_skipped_auto_evaluation_returns_without_expired_attribute_read(db_session, monkeypatch):
    run = _seed_minimal_run(db_session)
    run_id = run.id
    db_session.commit()
    sessions = _track_sessions(monkeypatch)
    result = asyncio.run(auto_eval.evaluate_run_async(run_id, preset_override={"enabled": False}))
    assert result["reason"] == "preset_disabled"
    assert all(not session.in_transaction() for session in sessions)
