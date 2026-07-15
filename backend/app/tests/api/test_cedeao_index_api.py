"""API integration tests for the Vague 2.2 /cedeao-index endpoint.

These tests stand up a minimal FastAPI app overriding the auth + DB
dependencies so we can hit the route without booting Keycloak / Postgres.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import mission_room
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace
from app.services.intelligence import cache as intel_cache


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(mission_room.router, prefix="/api/v1/mission-room")
    app.dependency_overrides[mission_room.get_current_workspace] = lambda: workspace
    app.dependency_overrides[mission_room.get_current_user] = lambda: user
    app.dependency_overrides[mission_room.get_db] = lambda: db_session
    return TestClient(app)


def test_cedeao_index_endpoint_returns_baseline_payload_for_demo_workspace(db_session):
    """Demo workspaces must receive the deterministic baseline composite."""
    intel_cache.clear_memory_cache()
    workspace = Workspace(
        id="ws-cedeao-demo",
        slug="sentinel-ci-cedeao-demo",
        name="SENTINEL-CI",
        mode="demo",
        settings={
            "feature_flag": {"security_live_osint": True},
            "mission_room": {"enabled": True, "profile": "sentinel_government_v1"},
        },
    )
    user = User(
        id="user-cedeao",
        username="vp",
        email="vp@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()

    response = _client(db_session, workspace, user).get("/api/v1/mission-room/cedeao-index")
    assert response.status_code == 200
    body = response.json()
    assert body["live"] is False
    assert body["source_badge"] == "CACHE BASELINE"
    assert body["policy"] == "advisory_only"
    assert body["demo_mode"] is True
    assert body["unit"] == "/100"
    assert 40 <= body["score"] <= 90
    assert set(body["components"].keys()) == {
        "unrest",
        "conflict",
        "security_advisories",
        "information",
    }
    assert len(body["series"]) >= 7


def test_cedeao_index_endpoint_emits_audit_event(db_session):
    intel_cache.clear_memory_cache()
    workspace = Workspace(
        id="ws-cedeao-audit",
        slug="sentinel-ci-cedeao-audit",
        name="SENTINEL-CI",
        mode="demo",
        settings={
            "mission_room": {"enabled": True, "profile": "sentinel_government_v1"},
        },
    )
    user = User(
        id="user-cedeao-audit",
        username="vp",
        email="vp@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()

    _client(db_session, workspace, user).get("/api/v1/mission-room/cedeao-index")
    events = (
        db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .filter(AuditLog.event_type == "mission_room.cedeao_index.viewed")
        .all()
    )
    assert len(events) == 1
    details = events[0].details or {}
    assert details.get("advisory_only") is True
    assert details.get("source_badge") in {"LIVE", "CACHE BASELINE"}


def test_cedeao_index_endpoint_serves_cached_live_when_flag_on(db_session):
    """When feature_flag is on AND workspace not in demo mode, cached live payload is served."""
    intel_cache.clear_memory_cache()
    workspace = Workspace(
        id="ws-cedeao-live",
        slug="sentinel-ci-cedeao-live",
        name="SENTINEL-CI",
        mode="operator",
        settings={
            "feature_flag": {"security_live_osint": True},
            "mission_room": {"enabled": True, "profile": "sentinel_government_v1"},
        },
    )
    user = User(
        id="user-cedeao-live",
        username="vp",
        email="vp@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()

    intel_cache.cache_set(
        "intelligence:security:cedeao:v1",
        {
            "live": True,
            "source": "live composite",
            "source_kind": "cedeao_index",
            "source_badge": "LIVE",
            "fetched_at": "2026-05-25T12:00:00Z",
            "score": 73.1,
            "unit": "/100",
            "delta_7d": 1.2,
            "trend": "up",
            "components": {
                "unrest": 60.0,
                "conflict": 72.0,
                "security_advisories": 70.0,
                "information": 64.0,
            },
            "component_weights": {
                "unrest": 0.30,
                "conflict": 0.25,
                "security_advisories": 0.25,
                "information": 0.20,
            },
            "series": [{"date": "2026-05-25", "value": 73.1}],
            "attribution": "composite",
        },
        1800,
    )

    response = _client(db_session, workspace, user).get("/api/v1/mission-room/cedeao-index")
    body = response.json()
    assert response.status_code == 200
    assert body["live"] is True
    assert body["source_badge"] == "LIVE"
    assert body["demo_mode"] is False
    assert body["score"] == 73.1
