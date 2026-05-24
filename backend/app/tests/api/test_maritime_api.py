from __future__ import annotations

import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import maritime
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace
from app.services import maritime_tracking


@pytest.fixture(autouse=True)
def _reset_provider_cache():
    """Ensure each test starts with a fresh provider cache."""
    maritime_tracking._clear_cache()  # noqa: SLF001 — internal but stable for tests
    yield
    maritime_tracking._clear_cache()  # noqa: SLF001


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(maritime.router, prefix="/api/v1/mission-room/maritime")
    app.dependency_overrides[maritime.get_current_workspace] = lambda: workspace
    app.dependency_overrides[maritime.get_current_user] = lambda: user
    app.dependency_overrides[maritime.get_db] = lambda: db_session
    return TestClient(app)


def _workspace_and_user(db_session) -> tuple[Workspace, User]:
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    return workspace, user


def test_baseline_snapshot_contains_mv_atlantic_trader():
    snapshot = maritime_tracking.fetch_snapshot()
    assert snapshot.source == "baseline"
    assert snapshot.provider == "baseline"
    mmsis = {vessel.mmsi for vessel in snapshot.vessels}
    assert "627012345" in mmsis
    atlantic = next(vessel for vessel in snapshot.vessels if vessel.mmsi == "627012345")
    assert atlantic.imo == "9876543"
    assert atlantic.name.upper().startswith("MV ATLANTIC")
    assert atlantic.linked_cargo_id == "cargo-abidjan-supply-001"
    assert atlantic.linked_project_ref == "proj-drone-centre-napie"


def test_bbox_filtering_keeps_abidjan_anchorage():
    abidjan = maritime_tracking.BBox(west=-4.1, south=5.20, east=-3.9, north=5.30)
    vessels = maritime_tracking.fetch_vessels_in_bbox(abidjan, limit=50)
    assert vessels, "expected at least one vessel in the Abidjan anchorage bbox"
    for vessel in vessels:
        assert -4.1 <= vessel.lon <= -3.9
        assert 5.20 <= vessel.lat <= 5.30
    assert vessels[0].linked_cargo_id == "cargo-abidjan-supply-001"


def test_bbox_filter_can_return_empty_outside_perimeter():
    out_of_zone = maritime_tracking.BBox(west=10.0, south=-10.0, east=20.0, north=-5.0)
    vessels = maritime_tracking.fetch_vessels_in_bbox(out_of_zone, limit=50)
    assert vessels == []


def test_vessel_type_filter():
    vessels = maritime_tracking.fetch_vessels_in_bbox(limit=200, vessel_types=["tanker"])
    assert vessels
    assert all((vessel.vessel_type or "").lower() == "tanker" for vessel in vessels)


def test_api_list_vessels_baseline_envelope(db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.get(
        "/api/v1/mission-room/maritime/vessels",
        params={"bbox": "-4.1,5.20,-3.9,5.30"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "baseline"
    assert body["provider"] == "baseline"
    assert body["demo_safe"] is True
    assert body["policy"] == "advisory_only"
    assert body["count"] >= 1
    assert body["count"] == len(body["vessels"])
    assert body["filters"]["bbox"] == {"west": -4.1, "south": 5.2, "east": -3.9, "north": 5.3}
    mmsis = {vessel["mmsi"] for vessel in body["vessels"]}
    assert "627012345" in mmsis

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "maritime.vessels.listed" in event_types


def test_api_vessel_detail_links_to_cargo(db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.get("/api/v1/mission-room/maritime/vessels/627012345")

    assert response.status_code == 200
    body = response.json()
    assert body["vessel"]["name"].upper().startswith("MV ATLANTIC")
    assert body["vessel"]["mmsi"] == "627012345"
    assert body["vessel"]["imo"] == "9876543"
    assert body["linked_cargo"]["id"] == "cargo-abidjan-supply-001"
    assert body["linked_cargo"]["project_ref"] == "proj-drone-centre-napie"
    assert body["snapshot"]["provider"] == "baseline"
    # Auto-select webcam wiring (S1 cargo drill).
    assert body["vessel"]["recommended_webcam_source_id"] == "apm-apapa-gate-1"
    assert body["recommended_webcam"]["source_id"] == "apm-apapa-gate-1"
    assert body["recommended_webcam"]["proxy_url"].startswith(
        "/api/v1/mission-room/webcams/proxy"
    )
    cycle_ids = [entry["source_id"] for entry in body["recommended_webcam"]["cycle"]]
    assert cycle_ids[0] == "apm-apapa-gate-1"
    assert "paa-aerial-vue" in cycle_ids

    event_types = {row.event_type for row in db_session.query(AuditLog).all()}
    assert "maritime.vessel.viewed" in event_types


def test_api_list_vessels_attaches_recommended_webcam_to_anchor(db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.get(
        "/api/v1/mission-room/maritime/vessels",
        params={"bbox": "-4.1,5.20,-3.9,5.30"},
    )

    assert response.status_code == 200
    body = response.json()
    anchor = next(v for v in body["vessels"] if v["mmsi"] == "627012345")
    assert anchor["recommended_webcam_source_id"] == "apm-apapa-gate-1"
    # Vessels without the narrative role must not advertise a webcam.
    others = [v for v in body["vessels"] if v["mmsi"] != "627012345"]
    assert all("recommended_webcam_source_id" not in v for v in others)


def test_api_vessel_detail_404_when_missing(db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.get("/api/v1/mission-room/maritime/vessels/999999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "vessel_not_found"


def test_api_vessel_detail_rejects_non_numeric_mmsi(db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.get("/api/v1/mission-room/maritime/vessels/not-a-number")

    assert response.status_code == 400
    assert response.json()["detail"] == "mmsi_must_be_numeric"


def test_api_rejects_invalid_bbox_format(db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    too_few = client.get(
        "/api/v1/mission-room/maritime/vessels",
        params={"bbox": "-4.1,5.2,-3.9"},
    )
    inverted = client.get(
        "/api/v1/mission-room/maritime/vessels",
        params={"bbox": "0,10,-1,5"},
    )

    assert too_few.status_code == 400
    assert too_few.json()["detail"] == "bbox_must_have_4_values_west_south_east_north"
    assert inverted.status_code == 400
    assert inverted.json()["detail"] == "bbox_west_south_must_be_lower_than_east_north"


def test_api_snapshot_metadata_endpoint(db_session):
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.get("/api/v1/mission-room/maritime/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "baseline"
    assert body["source"] == "baseline"
    assert body["policy"] == "advisory_only"
    assert body["workspace"]["slug"] == "sentinel-ci"


def test_marinetraffic_embed_provider_exposes_iframe_url(monkeypatch, db_session):
    monkeypatch.setattr(maritime_tracking.settings, "sentinel_ais_provider", "marinetraffic_embed")
    maritime_tracking._clear_cache()  # noqa: SLF001
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.get("/api/v1/mission-room/maritime/vessels")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "marinetraffic_embed"
    assert body["source"] == "baseline"
    assert body["embed_url"] and "marinetraffic.com" in body["embed_url"]


def test_aisstream_without_key_falls_back_to_baseline_with_warning(monkeypatch, db_session):
    monkeypatch.setattr(maritime_tracking.settings, "sentinel_ais_provider", "aisstream")
    monkeypatch.setattr(maritime_tracking.settings, "sentinel_aisstream_api_key", None)
    maritime_tracking._clear_cache()  # noqa: SLF001
    workspace, user = _workspace_and_user(db_session)
    client = _client(db_session, workspace, user)

    response = client.get("/api/v1/mission-room/maritime/vessels")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "aisstream"
    assert body["source"] == "baseline"
    assert any("baseline" in note.lower() for note in body["limitations"])


def test_provider_cache_returns_same_payload(monkeypatch):
    monkeypatch.setattr(maritime_tracking.settings, "sentinel_ais_provider", "baseline")
    maritime_tracking._clear_cache()  # noqa: SLF001
    first = maritime_tracking.fetch_snapshot()
    second = maritime_tracking.fetch_snapshot()
    assert first is second


def test_serialize_snapshot_includes_attribution_and_limits():
    snapshot = maritime_tracking.fetch_snapshot()
    payload = maritime_tracking.serialize_snapshot(snapshot)
    assert payload["attribution"]
    assert isinstance(payload["limitations"], list)
    assert payload["policy"] == "advisory_only"


def test_unknown_provider_falls_back_to_baseline(monkeypatch):
    monkeypatch.setattr(maritime_tracking.settings, "sentinel_ais_provider", "datalastic")
    maritime_tracking._clear_cache()  # noqa: SLF001
    snapshot = maritime_tracking.fetch_snapshot()
    # unknown provider triggers fallback in _configured_provider
    assert snapshot.provider == "baseline"


def test_module_can_be_reimported_without_side_effects():
    importlib.reload(maritime_tracking)
    snapshot = maritime_tracking.fetch_snapshot()
    assert snapshot.source == "baseline"
    assert snapshot.vessels
