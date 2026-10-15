"""Real PostgreSQL contention in the dedicated control worker's transactions."""

import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.db import base
from app.models.recipe import RecipeExecution
from app.services.execution import dispatch, ml_lifecycle, recipe_lifecycle, run_worker
from app.tests.services.test_activity_observability_postgres import pg as pg
from app.workers import execution_control


@pytest.mark.parametrize("blocked", ["recipe", "ml", "run"])
def test_blocked_reaper_rolls_back_alone_and_other_controllers_and_outbox_progress(
    pg, monkeypatch, blocked
):
    factory = sessionmaker(pg)
    monkeypatch.setattr(base, "SessionLocal", factory)
    with factory() as db:
        db.add_all(
            [
                RecipeExecution(id="held", workspace_id="pg-activity-ws", status="running"),
                RecipeExecution(id="partial", workspace_id="pg-activity-ws", status="running"),
            ]
        )
        db.commit()
    visited = []

    def controller(label):
        def reap(db, **kwargs):
            visited.append(label)
            if label == blocked:
                db.query(RecipeExecution).filter_by(id="partial").update({"status": "failed"})
                db.query(RecipeExecution).filter_by(id="held").with_for_update().one()
            return 1

        return reap

    for label, module in [("recipe", recipe_lifecycle), ("ml", ml_lifecycle), ("run", run_worker)]:
        monkeypatch.setattr(module, "reap", controller(label))
    monkeypatch.setattr(
        "app.services.activity_observability.commands.process_commands",
        lambda db, **kw: visited.append("commands") or 0,
    )
    monkeypatch.setattr(dispatch, "publish_due", lambda *a, **kw: visited.append("outbox") or 1)
    owner = Session(pg)
    owner.query(RecipeExecution).filter_by(id="held").with_for_update().one()
    try:
        started = time.monotonic()
        result = execution_control.tick.run()
        assert time.monotonic() - started < 3  # Lock remains held throughout.
        assert result == {"commands": 0, "expired": 2, "published": 1}
        assert visited == ["commands", "recipe", "ml", "run", "outbox"]
        with factory() as db:
            assert db.get(RecipeExecution, "partial").status == "running"
    finally:
        owner.rollback()
        owner.close()
    visited.clear()
    assert execution_control.tick.run() == {"commands": 0, "expired": 3, "published": 1}
    with factory() as db:
        assert db.get(RecipeExecution, "partial").status == "failed"


def test_statement_deadline_defers_but_other_database_errors_are_not_swallowed(pg, caplog):
    def slow(db, **kw):
        db.execute(text("SELECT pg_sleep(5)"))
        raise AssertionError("statement deadline did not fire")

    started = time.monotonic()
    assert execution_control._reap_bounded(sessionmaker(pg), slow, limit=1) == 0
    assert time.monotonic() - started < 3

    def invalid(db, **kw):
        db.execute(text("SELECT 1 / 0"))

    with pytest.raises(DBAPIError) as exc:
        execution_control._reap_bounded(sessionmaker(pg), invalid, limit=1)
    assert getattr(exc.value.orig, "pgcode", None) == "22012"
    assert "pg_sleep" not in caplog.text and "SELECT 1 / 0" not in caplog.text
