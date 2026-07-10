"""API tests for the per-System event-trigger piloting endpoints.

Covers ``GET /systems/{id}/event-trigger`` (read-only state) and
``PATCH /systems/{id}/event-trigger`` (mode flip + circuit-breaker re-arm),
which merge into ``System.settings['event_trigger']`` — the same JSON blob the
run engine reads through ``triggers.trigger_mode`` (Flow Builder sources DAG,
Phase 3). No migration: the state lives entirely in ``settings``.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import systems
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(systems.router, prefix="/systems")
    app.dependency_overrides[systems.get_current_workspace] = lambda: workspace
    app.dependency_overrides[systems.get_current_user] = lambda: user
    app.dependency_overrides[systems.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session, *, settings_blob: dict | None = None) -> tuple[Workspace, User, System]:
    user = User(id="user-et", username="et@datategy.test", email="et@datategy.test")
    workspace = Workspace(id="ws-et", name="Event Trigger", slug="event-trigger")
    system = System(
        id="sys-et",
        workspace_id=workspace.id,
        name="Trigger pilot",
        status="active",
        settings=settings_blob or {},
        flow_definition={
            "schema_version": 3,
            "nodes": [
                {"id": "src.sftp", "kind": "source", "type": "source.sftp_arrival"},
            ],
            "edges": [],
        },
    )
    db_session.add_all([user, workspace, system])
    db_session.commit()
    return workspace, user, system


def test_get_event_trigger_defaults_to_dry_run(db_session, monkeypatch):
    workspace, user, _system = _seed(db_session)
    monkeypatch.setattr(systems.settings, "enable_event_triggers", True)
    client = _client(db_session, workspace, user)

    res = client.get("/systems/sys-et/event-trigger")
    assert res.status_code == 200
    body = res.json()
    assert body["system_id"] == "sys-et"
    assert body["master_enabled"] is True
    assert body["mode"] == "dry_run"
    assert body["disabled"] is False
    assert body["disabled_reason"] is None


def test_patch_mode_to_live_persists_and_reads_back(db_session):
    workspace, user, system = _seed(db_session)
    client = _client(db_session, workspace, user)

    res = client.patch("/systems/sys-et/event-trigger", json={"mode": "live"})
    assert res.status_code == 200
    assert res.json()["mode"] == "live"

    db_session.refresh(system)
    assert system.settings["event_trigger"]["mode"] == "live"

    # The read endpoint reflects the persisted mode.
    assert client.get("/systems/sys-et/event-trigger").json()["mode"] == "live"


def test_patch_rearm_clears_circuit_breaker_provenance(db_session):
    # Pre-trip the breaker exactly as ``triggers._trip_circuit_breaker`` does.
    workspace, user, system = _seed(
        db_session,
        settings_blob={
            "event_trigger": {
                "mode": "live",
                "disabled": True,
                "disabled_reason": "circuit_breaker",
                "disabled_at": "2026-07-10T00:00:00",
            }
        },
    )
    client = _client(db_session, workspace, user)

    before = client.get("/systems/sys-et/event-trigger").json()
    assert before["disabled"] is True
    assert before["disabled_reason"] == "circuit_breaker"

    res = client.patch("/systems/sys-et/event-trigger", json={"disabled": False})
    assert res.status_code == 200
    body = res.json()
    assert body["disabled"] is False
    assert body["disabled_reason"] is None
    assert body["disabled_at"] is None
    # Mode is preserved when only re-arming.
    assert body["mode"] == "live"

    db_session.refresh(system)
    et = system.settings["event_trigger"]
    assert et["disabled"] is False
    assert et["rearmed_at"] is not None


def test_patch_rejects_invalid_mode(db_session):
    workspace, user, _system = _seed(db_session)
    client = _client(db_session, workspace, user)

    res = client.patch("/systems/sys-et/event-trigger", json={"mode": "turbo"})
    assert res.status_code == 400


def test_patch_rejects_empty_body(db_session):
    workspace, user, _system = _seed(db_session)
    client = _client(db_session, workspace, user)

    res = client.patch("/systems/sys-et/event-trigger", json={})
    assert res.status_code == 400


def test_event_trigger_404_for_unknown_system(db_session):
    workspace, user, _system = _seed(db_session)
    client = _client(db_session, workspace, user)

    assert client.get("/systems/nope/event-trigger").status_code == 404
    assert client.patch("/systems/nope/event-trigger", json={"mode": "live"}).status_code == 404
