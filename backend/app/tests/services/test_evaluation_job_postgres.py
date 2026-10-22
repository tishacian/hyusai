"""Real PostgreSQL checks for the Judge worker's transaction boundaries."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.services.evaluation import auto_eval, lifecycle
from app.tests.services.test_evaluation_job_transactions import _queued


@pytest.fixture
def pg_evaluation(monkeypatch):
    url = os.getenv("MODEL_USAGE_POSTGRES_URL")
    if not url:
        pytest.skip("MODEL_USAGE_POSTGRES_URL required")
    schema = "evaluation_job_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={
            "application_name": schema,
            "options": f"-csearch_path={schema} -clock_timeout=1000 -cstatement_timeout=5000",
        },
    )
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        monkeypatch.setattr(lifecycle, "SessionLocal", factory)
        monkeypatch.setattr(auto_eval, "SessionLocal", factory)
        yield factory, engine, schema
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_judge_does_not_block_job_or_workspace_and_keeps_delivery_exclusive(
    pg_evaluation, monkeypatch
):
    factory, engine, app_name = pg_evaluation
    with factory() as db:
        run_id, job_id = _queued(db, monkeypatch)
    calls = []

    class Judge:
        async def evaluate(self, **kwargs):
            calls.append(kwargs["session_id"])
            # Reading detached provider configuration must not begin another
            # transaction after the worker commits its claim.
            workspace_id = kwargs["workspace"].id
            assert kwargs["workspace"].settings is not None
            with engine.begin() as observer:
                idle = observer.execute(
                    text("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE application_name=:app_name AND pid<>pg_backend_pid()
                      AND state LIKE 'idle in transaction%'
                """),
                    {"app_name": app_name},
                ).scalar_one()
                assert idle == 0
                assert (
                    observer.execute(
                        text("SELECT status FROM workspace_jobs WHERE id=:id FOR UPDATE NOWAIT"),
                        {"id": job_id},
                    ).scalar_one()
                    == "running"
                )
                assert (
                    observer.execute(
                        text("SELECT id FROM workspaces WHERE id=:id FOR UPDATE NOWAIT"),
                        {"id": workspace_id},
                    ).scalar_one()
                    == workspace_id
                )
            assert lifecycle.run_evaluation_job(job_id) == {"status": "running", "job_id": job_id}
            return {
                "id": str(uuid4()),
                "status": "completed",
                "scores": {},
                "composite_score": None,
                "hallucination_rate": None,
            }

    monkeypatch.setattr(auto_eval, "get_judge_service", lambda: Judge())
    assert lifecycle.run_evaluation_job(job_id)["status"] == "completed"
    assert lifecycle.run_evaluation_job(job_id)["status"] == "completed"
    assert calls == [run_id]
    with engine.begin() as observer:
        assert (
            observer.execute(
                text("""
            SELECT count(*) FROM pg_stat_activity
            WHERE application_name=:app_name AND pid<>pg_backend_pid()
              AND state LIKE 'idle in transaction%'
        """),
                {"app_name": app_name},
            ).scalar_one()
            == 0
        )
        assert (
            observer.execute(
                text("""
            SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid=l.pid
            WHERE a.application_name=:app_name AND l.locktype='advisory'
        """),
                {"app_name": app_name},
            ).scalar_one()
            == 0
        )


def test_advisory_lock_released_after_worker_failure_and_terminal_return(
    pg_evaluation, monkeypatch
):
    factory, engine, app_name = pg_evaluation
    with factory() as db:
        _, job_id = _queued(db, monkeypatch)

    async def interrupted(*args, **kwargs):
        raise RuntimeError("interrupted worker")

    monkeypatch.setattr(auto_eval, "evaluate_run_async", interrupted)
    with pytest.raises(RuntimeError, match="interrupted worker"):
        lifecycle.run_evaluation_job(job_id)
    with lifecycle._evaluation_job_lock(engine, job_id) as acquired:
        assert acquired

    async def recovered(*args, **kwargs):
        return {"status": "partial", "evaluation_id": "recovered"}

    monkeypatch.setattr(auto_eval, "evaluate_run_async", recovered)
    assert lifecycle.run_evaluation_job(job_id)["evaluation_id"] == "recovered"
    assert lifecycle.run_evaluation_job(job_id)["evaluation_id"] == "recovered"
    with engine.begin() as observer:
        assert (
            observer.execute(
                text("""
            SELECT count(*) FROM pg_stat_activity
            WHERE application_name=:app_name AND pid<>pg_backend_pid()
              AND state LIKE 'idle in transaction%'
        """),
                {"app_name": app_name},
            ).scalar_one()
            == 0
        )
