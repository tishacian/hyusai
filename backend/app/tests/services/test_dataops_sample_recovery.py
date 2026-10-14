"""Real ledger CAS interleavings and broker-loss recovery for sample jobs."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Update

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.dataops import samples
from app.workers.celery_app import celery_app


@pytest.fixture
def ledger(db_session, monkeypatch):
    clock = [datetime(2026, 10, 13, 12)]

    class Clock(datetime):
        @classmethod
        def utcnow(cls):
            return clock[0]

    monkeypatch.setattr(samples, "datetime", Clock)
    workspace = Workspace(id=str(uuid4()), name="Recovery", slug=uuid4().hex)
    db_session.add(workspace)
    db_session.commit()

    def create(status="queued", *, age=61, started_age=None, kind=samples.KIND, commit=True):
        job = WorkspaceJob(
            id=str(uuid4()), workspace_id=workspace.id, kind=kind, status=status,
            input_ref={"dataset_id": str(uuid4()), "version": 1, "storage_key": "source.parquet",
                       "lease": "old-worker"},
            updated_at=clock[0] - timedelta(seconds=age),
            started_at=clock[0] - timedelta(seconds=started_age) if started_age else None,
        )
        db_session.add(job)
        if commit:
            db_session.commit()
        return job

    return create, clock


def test_recovers_only_uncertain_queued_and_expired_running_intentions(db_session, ledger, monkeypatch):
    create, clock = ledger
    queued = create()
    expired = create("running", started_age=settings.dataops_t0_max_timeout_s + 91)
    excluded = [
        create(age=59),
        create("running", started_age=30),
        create("running", age=59, started_age=settings.dataops_t0_max_timeout_s + 91),
        create("failed"), create("completed"), create("cancelled"), create(kind="other"),
    ]
    calls = []
    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert samples.recover_samples() == {"scanned": 2, "claimed": 2, "published": 2, "publish_failed": 0}
    assert {kwargs["task_id"] for _, kwargs in calls} == {queued.id, expired.id}
    for args, kwargs in calls:
        assert args == ("agentium.dataops_build_sample",)
        assert kwargs["args"] == [kwargs["task_id"]]
        assert kwargs["queue"] == settings.celery_dataops_queue
        assert kwargs["retry"] is False
    db_session.expire_all()
    for job in (queued, expired):
        assert job.status == "queued" and job.stage == "sample_pending"
        assert job.input_ref["lease"] != "old-worker"
        assert job.updated_at == clock[0]
    assert all(job.input_ref["lease"] == "old-worker" for job in excluded)
    assert samples.recover_samples()["published"] == 0


def test_competing_recovery_after_selection_loses_real_sql_cas(db_session, ledger, monkeypatch):
    create, _ = ledger
    create()
    calls, competing = [], []
    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: calls.append(kwargs))
    original = Session.execute
    entered = False

    def interleave(session, statement, *args, **kwargs):
        nonlocal entered
        if isinstance(statement, Update) and statement.table.name == "workspace_jobs" and not entered:
            entered = True
            # Both recoverers observed the old ledger row. The second commits
            # its claim before the first executes its conditional UPDATE.
            competing.append(samples.recover_samples())
        return original(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", interleave)
    first = samples.recover_samples()
    assert first == {"scanned": 1, "claimed": 0, "published": 0, "publish_failed": 0}
    assert competing[0]["published"] == 1
    assert len(calls) == 1


def test_completed_during_recovery_selection_is_never_requeued(db_session, ledger, monkeypatch):
    create, _ = ledger
    job = create()
    identity, observed_at = job.id, job.updated_at
    calls = []
    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: calls.append(kwargs))
    original = Session.execute
    entered = False

    def interleave(session, statement, *args, **kwargs):
        nonlocal entered
        if isinstance(statement, Update) and statement.table.name == "workspace_jobs" and not entered:
            entered = True
            with SessionLocal() as other:
                original(other, update(WorkspaceJob).where(WorkspaceJob.id == identity).values(
                    status="completed", updated_at=observed_at
                ))
                other.commit()
        return original(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", interleave)
    assert samples.recover_samples()["claimed"] == 0
    assert calls == []
    db_session.expire_all()
    assert job.status == "completed"


def test_broker_failure_stays_durable_and_obeys_sixty_second_throttle(db_session, ledger, monkeypatch):
    create, clock = ledger
    job = create()
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(kwargs)
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(celery_app, "send_task", unavailable)
    assert samples.recover_samples() == {"scanned": 1, "claimed": 1, "published": 0, "publish_failed": 1}
    db_session.expire_all()
    assert job.status == "queued" and job.updated_at == clock[0]
    clock[0] += timedelta(seconds=59)
    assert samples.recover_samples()["claimed"] == 0
    assert len(calls) == 1
    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: calls.append(kwargs))
    clock[0] += timedelta(seconds=1)
    assert samples.recover_samples()["published"] == 1
    assert len(calls) == 2 and calls[0]["task_id"] == calls[1]["task_id"] == job.id


def test_worker_loss_between_claim_and_publish_is_recovered(db_session, ledger, monkeypatch):
    create, clock = ledger
    job = create("running", started_age=settings.dataops_t0_max_timeout_s + 91)

    class WorkerLost(BaseException):
        pass

    def lost(*args, **kwargs):
        raise WorkerLost()

    monkeypatch.setattr(celery_app, "send_task", lost)
    with pytest.raises(WorkerLost):
        samples.recover_samples()
    db_session.expire_all()
    assert job.status == "queued" and job.updated_at == clock[0]
    assert job.input_ref["lease"] != "old-worker"
    clock[0] += timedelta(seconds=60)
    calls = []
    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: calls.append(kwargs))
    assert samples.recover_samples()["published"] == 1
    assert calls[0]["task_id"] == job.id


def test_each_claim_uses_its_actual_time_when_prior_publication_is_slow(ledger, monkeypatch):
    create, clock = ledger
    create()
    create()
    calls = []

    def slow_first_publish(*args, **kwargs):
        calls.append(kwargs["task_id"])
        if len(calls) == 1:
            clock[0] += timedelta(seconds=55)

    monkeypatch.setattr(celery_app, "send_task", slow_first_publish)
    assert samples.recover_samples()["published"] == 2
    clock[0] += timedelta(seconds=5)
    assert samples.recover_samples()["published"] == 1
    assert calls[2] == calls[0]


def test_scan_limit_is_enforced_and_hard_capped(db_session, ledger, monkeypatch):
    create, _ = ledger
    for _ in range(103):
        create(commit=False)
    db_session.commit()
    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: None)
    assert samples.recover_samples(limit=2)["published"] == 2
    assert samples.recover_samples(limit=1000)["published"] == 100
    assert samples.recover_samples()["published"] == 1


def test_recovery_runs_periodically_on_cpu_and_only_dispatches_sample_work(monkeypatch):
    from app.workers.tasks import dataops_sample_recovery_task

    entry = celery_app.conf.beat_schedule["dataops-sample-recovery-60s"]
    assert entry["task"] == "agentium.dataops_sample_recovery" and entry["schedule"] == 60.0
    assert entry["options"]["queue"] == settings.celery_task_default_queue
    assert celery_app.conf.task_routes[entry["task"]]["queue"] == settings.celery_task_default_queue
    monkeypatch.setattr(samples, "recover_samples", lambda: {"published": 0})
    assert dataops_sample_recovery_task.run() == {"published": 0}
