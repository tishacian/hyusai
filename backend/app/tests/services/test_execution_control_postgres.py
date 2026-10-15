"""Real PG admission/upgrade qualification, no production database reset."""

import threading
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.execution_control import ExecutionReservation
from app.models.run import Run
from app.models.workspace import Workspace
from app.services.execution.admission import AdmissionError, reserve
from app.tests.services.test_activity_observability_postgres import pg  # noqa: F401
from app.tests.services.test_migration_127_connector_connections import load


def test_concurrent_workspaces_cannot_overbook_global_slot(pg, monkeypatch):  # noqa: F811 - imported pytest fixture
    monkeypatch.setattr(settings, "execution_global_slots", 1)
    monkeypatch.setattr(settings, "execution_interactive_reserved_slots", 0)
    monkeypatch.setattr(settings, "execution_interactive_reserved_cpu", 0)
    with Session(pg) as db:
        db.add(Workspace(id="second-ws", slug="second-ws", name="Second"))
        db.commit()
    barrier = threading.Barrier(2)
    outcomes = []
    errors = []

    def claim(identifier):
        try:
            with Session(pg) as db:
                barrier.wait(timeout=5)
                try:
                    reserve(
                        db,
                        workspace_id=identifier,
                        entity_kind="recipe_execution",
                        entity_id=identifier,
                        cpu_cores=1,
                        memory_mb=256,
                        deadline_at=datetime.utcnow() + timedelta(minutes=1),
                    )
                    db.commit()
                    outcomes.append("admitted")
                except AdmissionError as exc:
                    db.rollback()
                    outcomes.append(exc.code)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=claim, args=(ws,)) for ws in ("pg-activity-ws", "second-ws")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not errors and all(not thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["EXECUTION_SLOTS_EXHAUSTED", "admitted"]
    with Session(pg) as db:
        assert db.query(ExecutionReservation).count() == 1


def test_134_upgrade_empty_downgrade_and_refusal_with_evidence(pg):  # noqa: F811 - imported pytest fixture
    migration = load("134_execution_control")
    with pg.begin() as bind:
        migration.op = Operations(MigrationContext.configure(bind))
        migration.downgrade()
        assert "execution_dispatches" not in sa.inspect(bind).get_table_names()
        migration.upgrade()
        for table in ("execution_dispatches", "execution_reservations", "execution_capacity"):
            assert table in sa.inspect(bind).get_table_names()
        assert "cancel_requested" in {col["name"] for col in sa.inspect(bind).get_columns("runs")}
    with Session(pg) as db:
        db.add(Run(id="controlled", workspace_id="pg-activity-ws", execution_policy={"version": 1}))
        db.commit()
    with pg.begin() as bind:
        migration.op = Operations(MigrationContext.configure(bind))
        with pytest.raises(RuntimeError, match="controlled workflows"):
            migration.downgrade()
