from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import maritime, mission_room, webcam_proxy
from app.extensions.registry import WORKSPACE_EXTENSION_NOT_FOUND_CODE
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace
from app.services.mission_room import (
    OCTOCITY_MISSION_ROOM_PROFILE,
    SENTINEL_MISSION_ROOM_PROFILE,
)


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(mission_room.router, prefix="/api/v1/mission-room")
    app.include_router(
        maritime.router,
        prefix="/api/v1/mission-room/maritime",
    )
    app.include_router(
        webcam_proxy.router,
        prefix="/api/v1/mission-room/webcams",
    )
    app.dependency_overrides[mission_room.get_current_workspace] = lambda: workspace
    app.dependency_overrides[mission_room.get_current_user] = lambda: user
    app.dependency_overrides[mission_room.get_db] = lambda: db_session
    return TestClient(app)


def test_generic_workspace_cannot_discover_mission_room(
    db_session,
    monkeypatch,
):
    workspace = Workspace(
        id="workspace-generic",
        slug="generic",
        name="Generic Workspace",
        settings={},
    )
    user = User(
        id="user-generic",
        username="generic-user",
        email="generic@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()

    def unexpected_provider_call(*_args, **_kwargs):
        pytest.fail("disabled Mission Room reached an extension provider")

    monkeypatch.setattr(maritime, "fetch_snapshot", unexpected_provider_call)
    monkeypatch.setattr(
        webcam_proxy,
        "fetch_webcam_snapshot",
        unexpected_provider_call,
    )

    client = _client(db_session, workspace, user)
    responses = [
        client.get("/api/v1/mission-room/overview"),
        client.get("/api/v1/mission-room/maritime/snapshot"),
        client.get("/api/v1/mission-room/webcams/sources"),
    ]
    head_response = client.head(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "apm-apapa-gate-1"},
    )

    for response in responses:
        assert response.status_code == 404
        assert response.json() == {"detail": {"code": WORKSPACE_EXTENSION_NOT_FOUND_CODE}}
    assert head_response.status_code == 404
    assert head_response.content == b""
    assert db_session.query(AuditLog).count() == 0


@pytest.mark.parametrize(
    ("slug", "name", "settings", "expected_terms", "forbidden_terms"),
    [
        (
            "sentinel-ci",
            "SENTINEL-CI",
            {
                "workspace_app_label": "SENTINEL-CI",
                "actions": {
                    "enabled_packs": [
                        "global_voice_v1",
                        "sentinel_ci_aya_v1",
                        "sentinel_ci_aya_security_v1",
                    ]
                },
                "mission_room": {
                    "enabled": True,
                    "profile": SENTINEL_MISSION_ROOM_PROFILE,
                    "label": "AYA",
                },
            },
            ("SENTINEL-CI", "AYA", SENTINEL_MISSION_ROOM_PROFILE),
            ("Octocity", "OCTAVE", "octocity_", "octave."),
        ),
        (
            "octocity-mission-room",
            "Octocity Mission Room",
            {
                "workspace_app_label": "Octocity Mission Room",
                "workspace_app_brand": {
                    "label": "Octocity Mission Room",
                    "lines": ["AGENTIUM", "MISSION ROOM"],
                    "emblem": "/assets/brand/agentium-mark.svg",
                    "style": "agentium",
                },
                "actions": {
                    "enabled_packs": [
                        "global_voice_v1",
                        "octave_mission_room_v1",
                        "octave_security_v1",
                    ]
                },
                "mission_room": {
                    "enabled": True,
                    "profile": OCTOCITY_MISSION_ROOM_PROFILE,
                    "label": "OCTAVE",
                },
            },
            ("Octocity Mission Room", "OCTAVE", OCTOCITY_MISSION_ROOM_PROFILE),
            ("SENTINEL-CI", "AYA", "sentinel-ci", "sentinel_ci"),
        ),
    ],
)
def test_configured_mission_room_profiles_are_allowed_and_presented(
    db_session,
    slug,
    name,
    settings,
    expected_terms,
    forbidden_terms,
):
    workspace = Workspace(
        id=f"workspace-{slug}",
        slug=slug,
        name=name,
        mode="demo",
        settings=settings,
    )
    user = User(
        id=f"user-{slug}",
        username=f"user-{slug}",
        email=f"{slug}@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    client = _client(db_session, workspace, user)

    overview = client.get("/api/v1/mission-room/overview")
    navigation = client.get("/api/v1/mission-room/navigation")

    assert overview.status_code == 200
    assert navigation.status_code == 200
    runtime_payload = {
        "overview": overview.json(),
        "navigation": navigation.json(),
    }
    serialized = json.dumps(runtime_payload, ensure_ascii=False)
    for expected in expected_terms:
        assert expected in serialized
    for forbidden in forbidden_terms:
        assert forbidden not in serialized
