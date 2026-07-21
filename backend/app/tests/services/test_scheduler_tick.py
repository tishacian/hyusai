"""Unit tests for cron ``scheduler_tick`` (orchestration Phase 3)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.models.run import Run
from app.models.run_schedule import RunSchedule
from app.models.system import System
from app.models.workspace import Workspace
from app.services.run_engine import scheduler


def _workspace(db) -> Workspace:
    ws = Workspace(id=str(uuid.uuid4()), name="Sched WS", slug=f"sched-{uuid.uuid4().hex[:6]}")
    db.add(ws)
    db.commit()
    return ws


def _system(db, workspace_id: str, *, status: str = "active") -> System:
    system = System(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="Scheduled System",
        objective="tick",
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "src", "kind": "source", "type": "source.schedule"},
                {"id": "snk", "kind": "sink"},
            ],
            "edges": [{"from": "src", "to": "snk", "kind": "control"}],
        },
        status=status,
    )
    db.add(system)
    db.commit()
    return system


def test_compute_next_fire_at_valid():
    nxt = scheduler.compute_next_fire_at("0 * * * *", "UTC")
    assert nxt is not None
    assert isinstance(nxt, datetime)


def test_compute_next_fire_at_invalid_cron():
    assert scheduler.compute_next_fire_at("not a cron", "UTC") is None


def test_scheduler_tick_fires_due_schedule(db_session):
    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    past = datetime.utcnow() - timedelta(minutes=2)
    sched = RunSchedule(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        system_id=system.id,
        name="Due",
        cron_expr="* * * * *",
        timezone="UTC",
        input_payload={"hello": "world"},
        enabled=True,
        next_fire_at=past,
    )
    db_session.add(sched)
    db_session.commit()

    with patch.object(scheduler, "_dispatch_run") as dispatch:
        result = scheduler.scheduler_tick()

    assert result["status"] == "ok"
    assert result["fired"] == 1
    db_session.refresh(sched)
    assert sched.last_run_id is not None
    assert sched.next_fire_at is not None
    assert sched.next_fire_at > past
    run = db_session.query(Run).filter(Run.id == sched.last_run_id).first()
    assert run is not None
    assert run.trigger == "scheduler"
    assert run.status == "pending"
    assert (run.input_ref or {}).get("hello") == "world"
    dispatch.assert_called_once_with(run.id)


def test_scheduler_tick_skips_disabled(db_session):
    ws = _workspace(db_session)
    system = _system(db_session, ws.id)
    sched = RunSchedule(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        system_id=system.id,
        name="Off",
        cron_expr="* * * * *",
        timezone="UTC",
        enabled=False,
        next_fire_at=datetime.utcnow() - timedelta(minutes=1),
    )
    db_session.add(sched)
    db_session.commit()

    with patch.object(scheduler, "_dispatch_run") as dispatch:
        result = scheduler.scheduler_tick()

    assert result["fired"] == 0
    dispatch.assert_not_called()


def test_scheduler_tick_skips_inactive_system(db_session):
    ws = _workspace(db_session)
    system = _system(db_session, ws.id, status="draft")
    past = datetime.utcnow() - timedelta(minutes=1)
    sched = RunSchedule(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        system_id=system.id,
        name="Draft sys",
        cron_expr="* * * * *",
        timezone="UTC",
        enabled=True,
        next_fire_at=past,
    )
    db_session.add(sched)
    db_session.commit()

    with patch.object(scheduler, "_dispatch_run") as dispatch:
        result = scheduler.scheduler_tick()

    assert result["fired"] == 0
    assert result["skipped"] == 1
    dispatch.assert_not_called()
    db_session.refresh(sched)
    # next_fire_at advanced so we do not hot-loop
    assert sched.next_fire_at is not None
    assert sched.next_fire_at > past
