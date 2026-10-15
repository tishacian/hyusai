"""A busy native row must not monopolize the optional short bridge worker."""

import time
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.models.run import Run
from app.tests.services.test_activity_observability_postgres import pg as pg
from app.workers import temporal_execution


def test_terminal_reconciliation_defers_a_busy_native_lock(pg, monkeypatch):
    identifier = str(uuid4())
    factory = sessionmaker(pg)
    monkeypatch.setattr(temporal_execution, "SessionLocal", factory)
    with Session(pg) as db:
        db.add(Run(id=identifier, workspace_id="pg-activity-ws", status="running"))
        db.commit()
    with Session(pg) as owner:
        owner.query(Run).filter_by(id=identifier).with_for_update().one()
        started = time.monotonic()
        with pytest.raises(DBAPIError) as deferred:
            temporal_execution._reconcile_terminal(identifier, "EXECUTION_OUTCOME_UNKNOWN")
        assert getattr(deferred.value.orig, "pgcode", None) == "55P03"
        assert time.monotonic() - started < 2
        owner.rollback()
    with Session(pg) as db:
        assert db.get(Run, identifier).status == "running"
    temporal_execution._reconcile_terminal(identifier, "EXECUTION_OUTCOME_UNKNOWN")
    with Session(pg) as db:
        assert db.get(Run, identifier).status == "failed"
