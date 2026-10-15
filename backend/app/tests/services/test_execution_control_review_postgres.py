"""Concurrent owners/publication on a disposable PostgreSQL schema only."""
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models.execution_control import ExecutionDispatch
from app.models.recipe import RecipeExecution
from app.models.run import Run
from app.models.tabular import MLModel
from app.services.execution import dispatch, ml_lifecycle
from app.services.execution.contracts import ExecutionPolicy
from app.tests.services.test_activity_observability_postgres import pg as pg


def test_expiring_outbox_never_overwrites_concurrently_claimed_native(pg):
    identifier = str(uuid4())
    with Session(pg) as db:
        native = RecipeExecution(id=identifier, workspace_id="pg-activity-ws", status="queued",
                                 input_json={"kind": "data_prep"}, lifecycle_controller="legacy")
        db.add(native)
        dispatch.stage(db, "recipe_execution", native, deadline_at=datetime.utcnow()-timedelta(seconds=1))
        db.commit()
    locked, release, published = (threading.Event() for _ in range(3))
    failures = []
    def claim():
        try:
            with Session(pg) as db:
                row = db.query(RecipeExecution).filter_by(id=identifier).with_for_update().one()
                row.status = "running"
                db.flush()
                locked.set()
                assert release.wait(5)
                db.commit()
        except BaseException as exc:
            failures.append(exc)
    def publish():
        try:
            assert locked.wait(5)
            dispatch.publish_due(sessionmaker(pg), publisher=lambda *args, **kw: failures.append("published busy native"))
            published.set()
        except BaseException as exc:
            failures.append(exc)
    owner, publisher = threading.Thread(target=claim), threading.Thread(target=publish)
    owner.start()
    publisher.start()
    try:
        assert locked.wait(5)
        assert published.wait(3), "Publisher waited on native lock while holding the outbox"
    finally:
        release.set()
        owner.join(10)
        publisher.join(10)
    assert not failures and not owner.is_alive() and not publisher.is_alive()
    with Session(pg) as db:
        assert db.get(RecipeExecution, identifier).status == "running"
        assert db.query(ExecutionDispatch).one().state == "pending"


def test_duplicate_ml_dispatch_without_admission_has_one_claim(pg):
    identifier = str(uuid4())
    with Session(pg) as db:
        native = MLModel(id=identifier, workspace_id="pg-activity-ws", name="One", slug="one",
                         task="classification", target="label", algo="logistic_regression")
        db.add(native)
        dispatch.stage(db, "ml_training", native, deadline_at=datetime.utcnow()+timedelta(minutes=1))
        db.commit()
    barrier = threading.Barrier(2)
    claims, failures = [], []
    def claim():
        try:
            with Session(pg) as db:
                stale = db.get(MLModel, identifier)
                assert stale.status == "pending"
                barrier.wait(timeout=5)
                accepted = ml_lifecycle.start(db, stale)
                if accepted:
                    stale.status = "training"
                    db.commit()
                claims.append(accepted)
        except BaseException as exc:
            failures.append(exc)
    threads = [threading.Thread(target=claim) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not failures and all(not thread.is_alive() for thread in threads)
    assert sorted(claims) == [False, True]


def test_run_reaper_observes_real_postgres_owner_lease(pg, monkeypatch):
    from app.services.execution.run_worker import reap
    from app.services.run_engine import subflow_orchestration
    monkeypatch.setattr(subflow_orchestration, "db_engine", pg)
    identifier = str(uuid4())
    policy = ExecutionPolicy(runtime_revision="pg-probe", deadline_at=datetime.now(UTC)+timedelta(seconds=40))
    with Session(pg) as db:
        row = Run(id=identifier, workspace_id="pg-activity-ws", status="running",
                  execution_policy=policy.model_dump(mode="json"))
        db.add(row)
        dispatch.stage(db, "run", row, deadline_at=policy.deadline_at.replace(tzinfo=None))
        db.commit()
    with subflow_orchestration.postgres_coordination_lease("execution-run", identifier) as owned:
        assert owned
        with Session(pg) as db:
            assert reap(db, now=datetime.utcnow()+timedelta(minutes=1)) == 1
            db.commit()
            row = db.get(Run, identifier)
            assert row.status == "running" and row.cancel_requested
    # Connection release after worker loss makes it safe to declare ownership
    # lost, but not to replay effects or infer remote process stop.
    with Session(pg) as db:
        assert reap(db, now=datetime.utcnow()+timedelta(minutes=1)) == 1
        db.commit()
        row = db.get(Run, identifier)
        assert row.status == "failed"
        assert row.error == "EXECUTION_OUTCOME_REQUIRES_RECONCILIATION"


def test_parent_cancel_locks_child_before_the_workspace_event_cursor(pg):
    from app.services.execution.control import request_run_cancel
    run_id, child_id = str(uuid4()), str(uuid4())
    with Session(pg) as db:
        db.add(Run(id=run_id, workspace_id="pg-activity-ws", status="running"))
        db.add(RecipeExecution(id=child_id, workspace_id="pg-activity-ws", run_id=run_id,
                              status="running", lifecycle_controller="legacy"))
        db.commit()
    locked, flush_child, cancellation_started = (threading.Event() for _ in range(3))
    failures, cancelling_pid = [], []
    def finish_child():
        try:
            with Session(pg) as db:
                row = db.query(RecipeExecution).filter_by(id=child_id).with_for_update().one()
                locked.set()
                assert flush_child.wait(5)
                row.status = "succeeded"
                db.commit()
        except BaseException as exc:
            failures.append(exc)
    def cancel():
        try:
            assert locked.wait(5)
            with Session(pg) as db:
                cancelling_pid.append(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
                cancellation_started.set()
                request_run_cancel(db, db.get(Run, run_id))
        except BaseException as exc:
            failures.append(exc)
    threads = [threading.Thread(target=finish_child), threading.Thread(target=cancel)]
    for thread in threads:
        thread.start()
    try:
        assert locked.wait(5) and cancellation_started.wait(5)
        with pg.connect() as connection:
            deadline = time.monotonic()+3
            waiting = None
            while time.monotonic() < deadline:
                waiting = connection.execute(text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"),
                    {"pid": cancelling_pid[0]}).scalar()
                connection.commit()
                if waiting == "Lock":
                    break
                time.sleep(0.01)
            assert waiting == "Lock", "Cancellation never reached the held child lock"
    finally:
        flush_child.set()
        for thread in threads:
            thread.join(10)
    assert not failures and all(not thread.is_alive() for thread in threads)
    with Session(pg) as db:
        assert db.get(Run, run_id).cancel_requested
        assert db.get(RecipeExecution, child_id).status == "succeeded"
