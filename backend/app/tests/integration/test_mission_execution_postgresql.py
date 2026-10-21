"""Real PostgreSQL gates for mission ownership and overlapping lifecycle writes.

Use a disposable database whose name passes the pytest destructive-reset guard::

    PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET=1 \
      DATABASE_URL=postgresql://.../test_mission_execution \
      pytest -m postgresql app/tests/integration/test_mission_execution_postgresql.py

These tests exercise independent database connections. They do not call a model
provider or require a Celery broker, and do not establish broker crash recovery.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from app.db.base import SessionLocal
from app.models.task import Task
from app.models.task_execution import TaskExecution
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.tasks.execution import (
    MissionConflict,
    checkpoint,
    claim_execution,
    queue_execution,
    recover_executions,
    resume_execution,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgresql]


@pytest.fixture()
def mission(db_session):
    if db_session.get_bind().dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL row-lock semantics")
    suffix = uuid4().hex
    workspace = Workspace(id=f"ws-{suffix}", slug=f"mission-{suffix}", name="Mission concurrency")
    author = User(id=str(uuid4()), username=f"mission-{suffix}")
    db_session.add_all([workspace, author])
    db_session.flush()
    task = Task(
        id=str(uuid4()),
        workspace_id=workspace.id,
        created_by=author.id,
        title="Concurrent mission",
        description="Preserve evidence across worker recovery",
        status="pending",
    )
    db_session.add(task)
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=author.id, role="member"))
    db_session.commit()
    return task.id, author.id


def _queued(db, mission):
    task_id, author_id = mission
    row = queue_execution(db, db.get(Task, task_id), author_id)
    db.commit()
    return row.id


def _parallel(first, second):
    barrier = threading.Barrier(2)

    def run(operation):
        with SessionLocal() as db:
            db.execute(text("SET LOCAL statement_timeout = '5s'"))
            barrier.wait(timeout=10)
            return operation(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, operation) for operation in (first, second)]
        return [future.result(timeout=15) for future in futures]


def test_simultaneous_launches_create_one_attempt(db_session, mission):
    task_id, author_id = mission

    def launch(db):
        try:
            row = queue_execution(db, db.get(Task, task_id), author_id)
            db.commit()
            return row.id
        except MissionConflict as exc:
            db.rollback()
            return str(exc)

    outcomes = _parallel(launch, launch)
    rows = db_session.query(TaskExecution).filter_by(task_id=task_id).all()
    assert len(rows) == 1
    assert sorted(outcomes) == sorted([rows[0].id, "MISSION_ALREADY_STARTED"])


def test_simultaneous_deliveries_claim_one_worker(db_session, mission):
    execution_id = _queued(db_session, mission)
    outcomes = _parallel(
        lambda db: claim_execution(db, execution_id),
        lambda db: claim_execution(db, execution_id),
    )
    assert outcomes.count(1) == 1
    assert outcomes.count(None) == 1
    row = db_session.get(TaskExecution, execution_id)
    db_session.refresh(row)
    assert row.status == "running" and row.fence == 1


def test_competing_recovery_fences_once_and_late_worker_cannot_overwrite(db_session, mission):
    execution_id = _queued(db_session, mission)
    old_fence = claim_execution(db_session, execution_id)
    completed = {"id": "evidence", "status": "completed", "result": "retained"}
    assert checkpoint(
        db_session,
        execution_id,
        old_fence,
        {"type": "task_step_complete", "step": completed, "progress": 50},
    )
    row = db_session.get(TaskExecution, execution_id)
    row.lease_until = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()

    assert _parallel(recover_executions, recover_executions) == [[], []]
    db_session.refresh(row)
    assert row.status == "interrupted" and row.fence == old_fence + 1
    resume_execution(db_session, db_session.get(Task, mission[0]), execution_id)
    db_session.commit()
    new_fence = claim_execution(db_session, execution_id)
    assert new_fence > old_fence

    outcomes = _parallel(
        lambda db: checkpoint(
            db, execution_id, old_fence, {"type": "task_complete", "artifacts": {"report": "late"}}
        ),
        lambda db: checkpoint(
            db,
            execution_id,
            new_fence,
            {"type": "task_complete", "artifacts": {"report": "current"}, "progress": 100},
        ),
    )
    assert outcomes == [False, True]
    db_session.refresh(row)
    assert row.status == "completed"
    assert row.steps == [completed]
    assert row.artifacts == {"report": "current"}
    task = db_session.get(Task, mission[0])
    db_session.refresh(task)
    assert task.artifacts == row.artifacts


@pytest.mark.parametrize("worker_operation", ["checkpoint", "recovery"])
def test_resume_overlapping_worker_write_does_not_deadlock(db_session, mission, worker_operation):
    """Hold the worker's attempt lock while resume reaches that same lock.

    If resume locks the parent Task first, the worker's later parent update
    closes a real PostgreSQL deadlock cycle. Synchronization observes SQL on
    each connection; no production service behavior or SQL is replaced.
    """
    execution_id = _queued(db_session, mission)
    fence = claim_execution(db_session, execution_id)
    if worker_operation == "recovery":
        row = db_session.get(TaskExecution, execution_id)
        row.lease_until = datetime.utcnow() - timedelta(seconds=1)
        db_session.commit()

    worker_locked = threading.Event()
    resume_reached_attempt = threading.Event()

    def attempt_lock(statement):
        return "FROM task_executions" in statement and "FOR UPDATE" in statement

    def worker():
        with SessionLocal() as db:
            db.execute(text("SET LOCAL statement_timeout = '5s'"))
            connection = db.connection()

            def after_statement(conn, cursor, statement, parameters, context, executemany):
                if attempt_lock(statement):
                    worker_locked.set()
                    assert resume_reached_attempt.wait(timeout=10), "resume never reached attempt"

            event.listen(connection, "after_cursor_execute", after_statement)
            try:
                if worker_operation == "recovery":
                    return recover_executions(db)
                return checkpoint(
                    db,
                    execution_id,
                    fence,
                    {"type": "task_complete", "artifacts": {"report": "confirmed"}},
                )
            finally:
                event.remove(connection, "after_cursor_execute", after_statement)

    def resume():
        assert worker_locked.wait(timeout=10), "worker never locked attempt"
        with SessionLocal() as db:
            db.execute(text("SET LOCAL statement_timeout = '5s'"))
            connection = db.connection()

            def before_statement(conn, cursor, statement, parameters, context, executemany):
                if attempt_lock(statement):
                    resume_reached_attempt.set()

            event.listen(connection, "before_cursor_execute", before_statement)
            try:
                resume_execution(db, db.get(Task, mission[0]), execution_id)
                db.commit()
                return "queued"
            except MissionConflict as exc:
                db.rollback()
                return str(exc)
            finally:
                event.remove(connection, "before_cursor_execute", before_statement)

    with ThreadPoolExecutor(max_workers=2) as pool:
        worker_future = pool.submit(worker)
        resume_future = pool.submit(resume)
        worker_outcome = worker_future.result(timeout=15)
        resume_outcome = resume_future.result(timeout=15)

    row = db_session.get(TaskExecution, execution_id)
    db_session.refresh(row)
    if worker_operation == "checkpoint":
        assert worker_outcome is True
        assert resume_outcome == "MISSION_NOT_INTERRUPTED"
        assert row.status == "completed" and row.artifacts == {"report": "confirmed"}
    else:
        assert worker_outcome == []
        assert resume_outcome == "queued" and row.status == "queued"
        assert row.fence > fence
