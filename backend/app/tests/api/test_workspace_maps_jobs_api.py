from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import maps, workspace_jobs
from app.models.user import User
from app.models.workspace import Workspace
from app.services.workspace_maps import ensure_workspace_map_seed


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(maps.router, prefix="/api/v1/maps")
    app.include_router(workspace_jobs.router, prefix="/api/v1/workspace-jobs")
    app.dependency_overrides[maps.get_current_workspace] = lambda: workspace
    app.dependency_overrides[maps.get_current_user] = lambda: user
    app.dependency_overrides[maps.get_db] = lambda: db_session
    app.dependency_overrides[workspace_jobs.get_current_workspace] = lambda: workspace
    app.dependency_overrides[workspace_jobs.get_current_user] = lambda: user
    app.dependency_overrides[workspace_jobs.get_db] = lambda: db_session
    return TestClient(app)


def test_workspace_map_scoring_creates_job_and_stays_workspace_scoped(db_session):
    workspace = Workspace(id="workspace-sentinel", slug="sentinel-ci", name="SENTINEL-CI", mode="demo")
    other = Workspace(id="workspace-andritz", slug="andritz", name="Andritz", mode="standard")
    user = User(id="user-1", username="minister", email="minister@example.test", is_active=True)
    db_session.add_all([workspace, other, user])
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    ensure_workspace_map_seed(db_session, other)
    db_session.commit()

    client = _client(db_session, workspace, user)
    listed = client.get("/api/v1/maps/")
    assert listed.status_code == 200
    assert listed.json()["maps"][0]["slug"] == "sentinel-ci-strategic-map"
    assert listed.json()["maps"][0]["renderer_config"]["renderer"] == "maplibre"
    assert listed.json()["maps"][0]["renderer_config"]["basemap_policy"] == "public_osm_muted"
    assert listed.json()["maps"][0]["renderer_config"]["default_basemap"] == "administrative"
    assert listed.json()["maps"][0]["renderer_config"]["bounds"][0][0] <= -13.0
    assert {item["key"] for item in listed.json()["maps"][0]["basemap_options"]} >= {"administrative", "dark", "contours"}
    assert listed.json()["maps"][0]["default_map_state"]["camera"]["pitch"] == 0
    assert listed.json()["maps"][0]["default_map_state"]["camera"]["zoom"] <= 5.9
    layer_keys = {item["key"] for item in listed.json()["maps"][0]["layer_catalog"]}
    assert listed.json()["maps"][0]["layer_catalog"][0]["key"] == "territorial-risk"
    assert "regional-context" in layer_keys
    assert listed.json()["maps"][0]["geodata_metadata"]["source"].startswith("geoBoundaries")
    assert listed.json()["maps"][0]["country_boundary"]["features"][0]["properties"]["admin_level"] == "ADM0"
    assert listed.json()["maps"][0]["district_boundaries"]["features"][0]["properties"]["admin_level"] == "ADM1"
    assert listed.json()["maps"][0]["admin_boundaries"]["features"]
    assert listed.json()["maps"][0]["admin_boundaries"]["features"][0]["properties"]["admin_level"] == "ADM2"
    assert listed.json()["maps"][0]["cities"]["features"]
    zone_features = listed.json()["maps"][0]["geojson_sources"]["zones"]["features"]
    assert len(zone_features) >= 14
    assert {feature["properties"]["admin_name"] for feature in zone_features if feature["properties"]["id"] == "zone-nord"} >= {
        "Savanes",
        "Denguele",
        "Woroba",
    }
    context_markers = listed.json()["maps"][0]["geojson_sources"]["context_markers"]["features"]
    assert context_markers
    assert {"Accra", "Bamako", "Ouagadougou"} <= {feature["properties"]["name"] for feature in context_markers}
    assert any(feature["properties"].get("scope") == "regional" for feature in context_markers)

    scored = client.post("/api/v1/maps/sentinel-ci-strategic-map/score")
    assert scored.status_code == 200
    body = scored.json()
    assert body["job"]["kind"] == "map_zone_scoring"
    assert body["job"]["status"] == "completed"
    assert body["result"]["zones_scored"] >= 5
    assert body["score_summary"]["top_zone"]["id"] == "zone-nord"

    jobs = client.get("/api/v1/workspace-jobs/")
    assert jobs.status_code == 200
    assert len(jobs.json()["jobs"]) == 1
    assert jobs.json()["jobs"][0]["workspace_id"] == workspace.id
    assert other.id not in str(jobs.json())

    command = client.post(
        "/api/v1/maps/sentinel-ci-strategic-map/command",
        json={"intent": "focus_zone", "target": "zone-nord", "layers": ["territorial-risk", "open-intelligence"]},
    )
    assert command.status_code == 200
    command_body = command.json()
    assert command_body["intent"] == "focus_zone"
    assert command_body["target"] == "zone-nord"
    assert command_body["map_state"]["renderer"] == "maplibre"
    assert command_body["map_state"]["basemap"] == "administrative"
    assert command_body["map_state"]["active_layers"] == ["territorial-risk", "open-intelligence"]
    assert command_body["map_state"]["camera"]["longitude"]

    basemap_command = client.post(
        "/api/v1/maps/sentinel-ci-strategic-map/command",
        json={"intent": "set_basemap", "basemap": "contours"},
    )
    assert basemap_command.status_code == 200
    assert basemap_command.json()["intent"] == "set_basemap"
    assert basemap_command.json()["map_state"]["basemap"] == "contours"

    reset_command = client.post(
        "/api/v1/maps/sentinel-ci-strategic-map/command",
        json={"intent": "reset_view"},
    )
    assert reset_command.status_code == 200
    assert reset_command.json()["intent"] == "reset_view"
    assert reset_command.json()["map_state"]["selected_zone"] is None
    assert reset_command.json()["map_state"]["camera"]["bearing"] == 0
