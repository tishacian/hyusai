"""Real-PostgreSQL ordering tests; opt in with ACTIVITY_POSTGRES_URL.

Uses a generated private schema and never resets the provided database.
"""
import os
import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base
from app.models.activity import Activity, ActivityCommand, ActivityEvent
from app.models.recipe import RecipeExecution
from app.models.run import Run
from app.models.user import User
from app.models.workspace import Workspace
from app.services.activity_observability import commands
from app.services.activity_observability.projection import backfill


@pytest.fixture
def pg(monkeypatch):
    url = os.getenv("ACTIVITY_POSTGRES_URL")
    if not url:
        pytest.skip("ACTIVITY_POSTGRES_URL required for real PostgreSQL concurrency")
    schema = "activity_probe_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema} -clock_timeout=5000 -cstatement_timeout=10000"})
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(Workspace(id="pg-activity-ws", slug="pg-activity-ws", name="PG probe"))
            db.commit()
        monkeypatch.setattr(settings, "activity_observability_enabled", True)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize("first_commits", [True, False])
def test_cursor_cannot_skip_uncommitted_lower_sequence(pg, first_commits):
    first_written, second_started, release_first, second_done = (threading.Event() for _ in range(4))
    failures = []
    second_pid = []
    def first():
        try:
            with Session(pg) as db:
                db.add(Run(id="first", workspace_id="pg-activity-ws", status="pending"))
                db.flush()
                first_written.set()
                assert release_first.wait(5)
                db.commit() if first_commits else db.rollback()
        except BaseException as exc:
            failures.append(exc)
    def second():
        try:
            assert first_written.wait(5)
            with Session(pg) as db:
                second_pid.append(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
                second_started.set()
                db.add(Run(id="second", workspace_id="pg-activity-ws", status="running"))
                db.commit()
                second_done.set()
        except BaseException as exc:
            failures.append(exc)
    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    try:
        assert first_written.wait(5) and second_started.wait(5)
        # Observe the actual PostgreSQL lock wait; a thread merely not yet
        # scheduled would not prove that commit reordering is prevented.
        with pg.connect() as connection:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                waiting = connection.execute(text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"), {"pid": second_pid[0]}).scalar()
                connection.commit()  # pg_stat_activity snapshots are transactional
                if waiting == "Lock":
                    break
                time.sleep(0.01)
            assert waiting == "Lock"
            assert connection.execute(select(ActivityEvent)).all() == []
        assert not second_done.is_set()
    finally:
        release_first.set()
        for thread in threads:
            thread.join(10)
    assert not failures
    assert all(not thread.is_alive() for thread in threads)
    assert second_done.is_set()
    with pg.connect() as connection:
        rows = connection.execute(select(ActivityEvent.sequence, Activity.native_id).join(Activity, Activity.id == ActivityEvent.activity_id).order_by(ActivityEvent.sequence)).all()
    assert rows == ([(1, "first"), (2, "second")] if first_commits else [(1, "second")])


def test_bulk_update_returning_result_is_preserved(pg):
    with Session(pg) as db:
        db.add_all([Run(id="one", workspace_id="pg-activity-ws"), Run(id="two", workspace_id="pg-activity-ws")])
        db.commit()
        result = db.execute(update(Run).where(Run.status == "pending").values(status="completed").returning(Run.id))
        assert set(result.scalars()) == {"one", "two"}
        db.commit()
        assert db.query(ActivityEvent).count() == 4
        assert {row.status for row in db.query(Activity)} == {"succeeded"}


def test_backfill_waits_for_native_owner_and_cannot_revert_projection(pg):
    with Session(pg) as db:
        db.add(Run(id="backfill-race", workspace_id="pg-activity-ws", status="pending"))
        db.commit()
    native = Session(pg)
    native.execute(update(Run).where(Run.id == "backfill-race").values(status="completed"))
    pid, started, failures = [], threading.Event(), []
    def snapshot():
        try:
            with Session(pg) as db:
                pid.append(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
                started.set()
                backfill(db, kind="run")
                db.commit()
        except BaseException as exc:
            failures.append(exc)
    thread = threading.Thread(target=snapshot)
    thread.start()
    try:
        assert started.wait(5)
        with pg.connect() as connection:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                waiting = connection.execute(text("SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid"), {"pid": pid[0]}).scalar()
                connection.commit()
                if waiting == "Lock":
                    break
                time.sleep(0.01)
            assert waiting == "Lock"
    finally:
        native.commit()
        native.close()
        thread.join(10)
    assert not failures and not thread.is_alive()
    with Session(pg) as db:
        assert db.query(Activity).one().status == "succeeded"
        assert db.query(ActivityEvent).count() == 2


def test_busy_native_publication_defers_command_and_control_worker_keeps_draining(pg, monkeypatch):
    from app.db import base
    from app.services.execution import dispatch, ml_lifecycle, recipe_lifecycle, run_worker
    from app.workers.execution_control import tick

    monkeypatch.setattr(settings, "execution_control_enabled", True)
    monkeypatch.setattr(settings, "execution_canary_workspaces", "*")
    with Session(pg) as db:
        workspace = db.get(Workspace, "pg-activity-ws")
        user = User(id="pg-controller", username="pg-controller", role="admin", is_active=True)
        db.add(user)
        db.add(Run(id="busy-parent", workspace_id=workspace.id))
        db.flush()
        db.add_all([RecipeExecution(id="busy-child", workspace_id=workspace.id, run_id="busy-parent", status="running"),
                    RecipeExecution(id="free-recipe", workspace_id=workspace.id, status="running")])
        db.commit()
        for identifier in ("busy-parent", "free-recipe"):
            row = db.query(Activity).filter_by(native_id=identifier).one()
            commands.enqueue(db, row=row, workspace=workspace, user=user, action="cancel", expected_version=row.version, idempotency_key=identifier)
        db.commit()
    marker = []
    monkeypatch.setattr(base, "SessionLocal", sessionmaker(pg))
    for module in (recipe_lifecycle, ml_lifecycle, run_worker):
        monkeypatch.setattr(module, "reap", lambda db, **kw: marker.append("reaper") or 0)
    monkeypatch.setattr(dispatch, "publish_due", lambda *a, **kw: marker.append("outbox") or 0)
    publisher = Session(pg)
    publisher.query(RecipeExecution).filter_by(id="busy-child").with_for_update().one()
    try:
        started = time.monotonic()
        result = tick.run()
        elapsed = time.monotonic() - started
        assert elapsed < 3  # Native lock is still held; no timing-sensitive release.
        assert result == {"commands": 1, "expired": 0, "published": 0}
        assert marker == ["reaper", "reaper", "reaper", "outbox"]
        with Session(pg) as db:
            pending = db.query(ActivityCommand).filter_by(idempotency_key="busy-parent").one()
            assert pending.status == "requested" and pending.error_code is None
            assert not db.get(Run, "busy-parent").cancel_requested
            assert db.get(Run, "busy-parent").status == "pending"
            assert not db.get(RecipeExecution, "busy-child").cancel_requested
            assert db.get(RecipeExecution, "free-recipe").cancel_requested
            assert db.query(ActivityCommand).filter_by(idempotency_key="free-recipe").one().status == "applied"
    finally:
        publisher.rollback()
        publisher.close()
    with Session(pg) as db:
        before = db.execute(text("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")).one()
        assert commands.process_commands(db) == 1
        assert db.execute(text("SELECT current_setting('lock_timeout'), current_setting('statement_timeout')")).one() == before
        db.commit()
        assert db.query(ActivityCommand).filter_by(idempotency_key="busy-parent").one().status == "applied"
        assert db.get(RecipeExecution, "busy-child").cancel_requested
