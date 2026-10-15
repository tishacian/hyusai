"""Real PostgreSQL uniqueness/fencing; private schema, no production operations."""

import asyncio
import threading
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.models.run import Run, SkillInvocation
from app.services.execution.runtimes import native_port as port
from app.services.run_engine import engine
from app.tests.services.test_activity_observability_postgres import pg as pg
from app.tests.services.test_native_temporal_port import candidate


@pytest.fixture
def native_pg(pg, tmp_path, monkeypatch):
    from app.db import base
    from app.services.execution import control

    factory = sessionmaker(pg, expire_on_commit=False)
    monkeypatch.setattr(base, "SessionLocal", factory)
    monkeypatch.setattr(control, "SessionLocal", factory)
    with Session(pg) as db:
        setup = candidate.__wrapped__(
            db, tmp_path, monkeypatch, SimpleNamespace(param="agent_data_agent")
        )
        port.begin(db, setup.request)
        yield setup, factory


def test_concurrent_same_invocation_has_one_provider_effect(native_pg, monkeypatch):
    s, factory = native_pg
    barrier = threading.Barrier(2)
    original = engine.capture_skill_execution_evidence

    def synchronized(*args, **kwargs):
        result = original(*args, **kwargs)
        barrier.wait(5)
        return result

    monkeypatch.setattr(engine, "capture_skill_execution_evidence", synchronized)
    results, errors = [], []

    def execute():
        try:
            with factory() as db:
                results.append(asyncio.run(port.submit(db, s.request, "agent_plan")))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=execute) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert not errors and all(not thread.is_alive() for thread in threads), errors
    assert s.calls == ["plan"] and len(results) == 2
    with factory() as db:
        row = db.query(SkillInvocation).filter_by(run_id=s.run.id).one()
        assert row.status == "completed"


def test_unknown_settlement_fences_real_concurrent_late_publication(native_pg, monkeypatch):
    s, factory = native_pg
    entered, release = threading.Event(), threading.Event()
    errors = []

    async def provider(payload, ctx):
        entered.set()
        await asyncio.to_thread(release.wait, 10)
        return {"answer": "late provider response"}

    monkeypatch.setattr(engine, "resolve_skill", lambda slug: provider)

    def execute():
        try:
            with factory() as db:
                asyncio.run(port.submit(db, s.request, "agent_plan"))
        except asyncio.CancelledError:
            pass
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=execute)
    thread.start()
    try:
        assert entered.wait(5)
        with factory() as db:
            assert port.uncertain(db, s.request, "agent_plan")["status"] == "failed"
    finally:
        release.set()
        thread.join(15)
    assert not errors and not thread.is_alive(), errors
    with factory() as db:
        row = db.query(SkillInvocation).filter_by(run_id=s.run.id).one()
        assert row.status == "lost" and row.output_ref == {}
        assert db.get(Run, s.run.id).status == "failed"
