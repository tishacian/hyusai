from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import webcam_proxy as endpoint
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace
from app.services import webcam_proxy as service


@pytest.fixture(autouse=True)
def _reset_proxy_cache():
    service._clear_cache()  # noqa: SLF001
    yield
    service._clear_cache()  # noqa: SLF001


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1/mission-room/webcams")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _workspace_and_user(db_session) -> tuple[Workspace, User]:
    workspace = Workspace(
        id="workspace-sentinel",
        slug="sentinel-ci",
        name="SENTINEL-CI",
        mode="demo",
        settings={"mission_room": {"enabled": True}},
    )
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    return workspace, user


def test_whitelist_blocks_unknown_source(db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.get(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "not-a-known-id"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "webcam_source_not_whitelisted"
    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "webcam.proxy.error" in event_types


def test_upstream_success_streams_jpeg_and_audits(monkeypatch, db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    payload = b"\xff\xd8\xff\xe0fake-jpg-bytes"

    def _fake_fetch(spec: service.WebcamSourceSpec, *, timeout_seconds: float = 12.0):  # noqa: ARG001
        return payload, "image/jpeg", 200

    monkeypatch.setattr(service, "_fetch_upstream", _fake_fetch)

    response = client.get(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "apm-apapa-gate-1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.headers["x-webcam-source"] == "upstream"
    assert response.headers["x-webcam-cache"] == "miss"
    assert response.headers["x-webcam-source-id"] == "apm-apapa-gate-1"
    assert response.content == payload

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "webcam.proxy.served" in event_types


def test_cache_hit_after_first_fetch(monkeypatch, db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    payload = b"\xff\xd8\xff\xe0frame-1"
    calls = {"count": 0}

    def _fake_fetch(spec: service.WebcamSourceSpec, *, timeout_seconds: float = 12.0):  # noqa: ARG001
        calls["count"] += 1
        return payload, "image/jpeg", 200

    monkeypatch.setattr(service, "_fetch_upstream", _fake_fetch)

    first = client.get(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "apm-apapa-gate-2"},
    )
    second = client.get(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "apm-apapa-gate-2"},
    )

    assert first.headers["x-webcam-cache"] == "miss"
    assert second.headers["x-webcam-cache"] == "hit"
    assert second.headers["x-webcam-source"] == "upstream"
    assert calls["count"] == 1  # cache absorbed the second hit


def test_force_refresh_bypasses_cache(monkeypatch, db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    payload = b"\xff\xd8\xff\xe0frame-x"
    calls = {"count": 0}

    def _fake_fetch(spec: service.WebcamSourceSpec, *, timeout_seconds: float = 12.0):  # noqa: ARG001
        calls["count"] += 1
        return payload, "image/jpeg", 200

    monkeypatch.setattr(service, "_fetch_upstream", _fake_fetch)
    client.get(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "apm-apapa-gate-1"},
    )
    refreshed = client.get(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "apm-apapa-gate-1", "force_refresh": "true"},
    )

    assert refreshed.headers["x-webcam-cache"] == "miss"
    assert calls["count"] == 2


def test_upstream_failure_falls_back_to_static_asset(monkeypatch, db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    def _boom(*_args: Any, **_kwargs: Any):
        raise RuntimeError("upstream_dead")

    monkeypatch.setattr(service, "_fetch_upstream", _boom)

    response = client.get(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "apm-apapa-gate-1"},
    )

    assert response.status_code == 200
    assert response.headers["x-webcam-source"] == "fallback"
    assert response.headers["x-webcam-cache"] == "miss"
    assert response.headers["content-type"].startswith("image/")
    assert response.content[:3] == b"\xff\xd8\xff"  # JPEG magic — embedded fallback

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "webcam.proxy.fallback" in event_types


def test_head_proxy_returns_headers_without_body(monkeypatch, db_session):
    """The cockpit vignette pre-flights the snapshot URL with HEAD."""
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    payload = b"\xff\xd8\xff\xe0head-probe-bytes"

    def _fake_fetch(spec: service.WebcamSourceSpec, *, timeout_seconds: float = 12.0):  # noqa: ARG001
        return payload, "image/jpeg", 200

    monkeypatch.setattr(service, "_fetch_upstream", _fake_fetch)

    response = client.head(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "apm-apapa-gate-1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.headers["x-webcam-source-id"] == "apm-apapa-gate-1"
    assert response.headers["x-webcam-source"] == "upstream"
    assert response.headers["content-length"] == str(len(payload))
    assert response.content == b""

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "webcam.proxy.served" in event_types


def test_head_proxy_blocks_unknown_source(db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.head(
        "/api/v1/mission-room/webcams/proxy",
        params={"source_id": "not-a-known-id"},
    )

    assert response.status_code == 404
    assert response.content == b""
    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "webcam.proxy.error" in event_types


def test_sources_inventory_returns_whitelist(monkeypatch, db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.get("/api/v1/mission-room/webcams/sources")

    assert response.status_code == 200
    body = response.json()
    ids = {item["source_id"] for item in body["sources"]}
    assert {"apm-apapa-gate-1", "apm-apapa-gate-2", "paa-aerial-vue"} <= ids
    assert body["policy"] == "advisory_only"


def test_recommended_webcam_for_mv_atlantic_trader():
    assert service.recommended_webcam_for_vessel(mmsi="627012345") == "apm-apapa-gate-1"
    assert (
        service.recommended_webcam_for_vessel(cargo_id="cargo-abidjan-supply-001")
        == "apm-apapa-gate-1"
    )
    assert service.recommended_webcam_for_vessel(mmsi="111111111") is None


def test_webcam_cycle_starts_with_primary_then_canonical_order():
    cycle = service.webcam_cycle_for_vessel(mmsi="627012345")
    assert cycle[0] == "apm-apapa-gate-1"
    # The canonical fallback sources must follow without dropping entries.
    for sid in service.RECOMMENDED_WEBCAM_CYCLE:
        assert sid in cycle
    assert len(cycle) == len(set(cycle))  # no duplicates
