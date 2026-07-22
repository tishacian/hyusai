"""PostgreSQL-only concurrency gate for authoritative System history.

This gate is independent from the P4 RabbitMQ topology.  It runs whenever the
test suite is connected to PostgreSQL and otherwise skips solely because the
active database cannot prove ``FOR UPDATE`` semantics::

    PYTEST_ALLOW_DESTRUCTIVE_DATABASE_RESET=1 \
      DATABASE_URL=postgresql://.../test_lot7_system_versions \
      pytest -m postgresql \
        app/tests/integration/test_system_version_postgresql.py
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.postgresql]


def test_system_version_allocation_is_serialized_on_postgresql(db_session):
    """Concurrent editors allocate distinct, monotonic System versions."""

    if db_session.get_bind().dialect.name != "postgresql":
        pytest.skip("requires PostgreSQL row-lock semantics")

    from app.db.base import SessionLocal
    from app.models.system import System
    from app.models.system_version import SystemVersion
    from app.models.workspace import Workspace
    from app.services.chains.version_service import record_new_version

    workspace = Workspace(
        id=str(uuid4()),
        name="SystemVersion concurrency",
        slug=f"system-version-concurrency-{uuid4()}",
    )
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Concurrent editor target",
        objective="Prove serialized history allocation",
        flow_definition={"schema_version": 3, "nodes": [], "edges": []},
    )
    db_session.add_all([workspace, system])
    system_id = system.id
    db_session.commit()

    barrier = threading.Barrier(2)

    def append(index: int) -> int:
        with SessionLocal() as db:
            local_system = db.query(System).filter(System.id == system_id).one()
            barrier.wait(timeout=10)
            version = record_new_version(
                db=db,
                system=local_system,
                flow_definition={
                    "schema_version": 3,
                    "nodes": [{"id": f"editor-{index}", "kind": "task"}],
                    "edges": [],
                },
                created_by=f"editor-{index}",
            )
            assert version is not None
            db.commit()
            return version.version_number

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(append, 1)
        second = pool.submit(append, 2)
        allocated = sorted([first.result(timeout=15), second.result(timeout=15)])

    assert allocated == [1, 2]
    rows = (
        db_session.query(SystemVersion)
        .filter(SystemVersion.system_id == system_id)
        .order_by(SystemVersion.version_number.asc())
        .all()
    )
    assert [row.version_number for row in rows] == [1, 2]
    assert {row.created_by for row in rows} == {"editor-1", "editor-2"}
