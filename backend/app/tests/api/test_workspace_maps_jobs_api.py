from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import maps, workspace_jobs
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_map import WorkspaceMap, WorkspaceMapScore, WorkspaceMapZone
from app.services.workspace_maps import (
    OCTOCITY_MAP_FIXTURE_PROFILE,
    OCTOCITY_MAP_SLUG,
    ensure_workspace_map_seed,
)


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
    assert listed.json()["maps"][0]["map_version"] == "situation_map_v3"
    assert listed.json()["maps"][0]["renderer_config"]["renderer"] == "maplibre"
    assert listed.json()["maps"][0]["rendering_profile"] == "executive_command_v1"
    assert listed.json()["maps"][0]["renderer_config"]["basemap_policy"] == "public_osm_carto_with_self_hosted_ready"
    assert listed.json()["maps"][0]["renderer_config"]["default_basemap"] == "command"
    assert -8.8 <= listed.json()["maps"][0]["renderer_config"]["bounds"][0][0] <= -8.4
    assert listed.json()["maps"][0]["renderer_config"]["regional_bounds"][0][0] <= -13.0
    assert {item["key"] for item in listed.json()["maps"][0]["basemap_options"]} >= {"command", "administrative", "dark", "contours"}
    assert listed.json()["maps"][0]["default_map_state"]["camera"]["pitch"] == 0
    assert listed.json()["maps"][0]["default_map_state"]["camera"]["zoom"] <= 5.9
    assert listed.json()["maps"][0]["default_map_state"]["time_range"] == "7d"
    assert {item["key"] for item in listed.json()["maps"][0]["available_time_ranges"]} >= {"24h", "7d", "30d"}
    layer_keys = {item["key"] for item in listed.json()["maps"][0]["layer_catalog"]}
    registry_keys = {item["key"] for item in listed.json()["maps"][0]["layer_registry"]}
    assert listed.json()["maps"][0]["layer_catalog"][0]["key"] == "territorial-risk"
    assert "regional-context" in layer_keys
    assert "maritime-traffic" in layer_keys
    assert "maritime-traffic" in registry_keys
    maritime_registry = next(item for item in listed.json()["maps"][0]["layer_registry"] if item["key"] == "maritime-traffic")
    assert maritime_registry["status"] == "ready"
    assert maritime_registry["freshness_at"]
    assert maritime_registry["source_kind"] == "maritime_snapshot"
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
    assert listed.json()["maps"][0]["event_points"]["features"]
    assert listed.json()["maps"][0]["geojson_sources"]["maritime_points"]["features"]
    assert listed.json()["maps"][0]["maritime_snapshot"]["mode"] == "snapshot_demo_safe"
    assert listed.json()["maps"][0]["maritime_snapshot"]["density_zones"]
    assert listed.json()["maps"][0]["maritime_snapshot"]["disruptions"]
    assert listed.json()["maps"][0]["tooltip_templates"]["maritime_snapshot"]
    assert "maritime" in listed.json()["maps"][0]["default_layer_groups"]
    assert listed.json()["maps"][0]["source_health"]["status"] == "ready"
    assert {item["key"] for item in listed.json()["maps"][0]["scenario_modes"]} == {
        "explorer",
        "comprendre",
        "decider",
    }
    assert listed.json()["maps"][0]["forecast_signals"]
    assert listed.json()["maps"][0]["renderer_config"]["interaction_contract"]["scenario_modes"] == [
        "explorer",
        "comprendre",
        "decider",
    ]

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
    assert command_body["map_state"]["basemap"] == "command"
    assert command_body["map_state"]["active_layers"] == ["territorial-risk", "open-intelligence"]
    assert command_body["map_state"]["camera"]["longitude"]

    port_command = client.post(
        "/api/v1/maps/sentinel-ci-strategic-map/command",
        json={"intent": "focus_port", "target": "abidjan"},
    )
    assert port_command.status_code == 200
    assert port_command.json()["intent"] == "focus_port"
    assert port_command.json()["target"] == "port-abidjan"
    assert "maritime-traffic" in port_command.json()["map_state"]["active_layers"]
    assert port_command.json()["map_state"]["selected_port"] == "port-abidjan"

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


def test_map_command_builds_payload_from_the_requested_map_in_a_multi_map_workspace(db_session):
    workspace = Workspace(
        id="workspace-multi-map-command",
        slug="multi-map-command",
        name="Multi-map command",
        mode="standard",
    )
    user = User(
        id="user-multi-map-command",
        username="multi-map-operator",
        email="multi-map-operator@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    default_map = ensure_workspace_map_seed(db_session, workspace)

    requested_map = WorkspaceMap(
        id="requested-map-id",
        workspace_id=workspace.id,
        slug="requested-operating-map",
        name="Requested operating map",
        description="A second operator-owned map.",
        country="France",
        projection="operator_projection_v1",
        view_box="0 0 100 100",
        center={"x": 50, "y": 50},
        settings={"operator": True},
    )
    requested_zone = WorkspaceMapZone(
        id="requested-zone-id",
        map_id=requested_map.id,
        zone_key="requested-zone",
        name="Requested map zone",
        level=88,
        tone="critical",
        polygon="10,10 90,10 90,90 10,90",
        centroid={"x": 50, "y": 50},
        meta_data={
            "signals": ["Second-map signal"],
            "recommendations": ["Review the requested map"],
        },
        source_refs=["requested-map-source"],
    )
    requested_score = WorkspaceMapScore(
        id="requested-score-id",
        map_id=requested_map.id,
        zone_id=requested_zone.id,
        score=88,
        level_label="critical",
        drivers=["Second-map signal"],
        recommendations=[{"title": "Review the requested map"}],
        recommended_windows=[{"label": "Requested-map window"}],
    )
    db_session.add_all([requested_map, requested_zone, requested_score])
    db_session.commit()

    command = _client(db_session, workspace, user).post(
        "/api/v1/maps/requested-operating-map/command",
        json={"intent": "focus_zone", "target": "requested-zone"},
    )

    assert command.status_code == 200
    body = command.json()
    assert body["map_id"] == requested_map.id
    assert body["map_id"] != default_map.id
    assert body["map_slug"] == requested_map.slug
    assert body["target"] == requested_zone.zone_key
    assert body["target_label"] == requested_zone.name
    assert body["map_state"]["selected_zone"] == requested_zone.zone_key
    assert body["sources"][0]["title"] == "requested-map-source"


def test_octocity_multi_map_detail_and_score_keep_the_requested_operator_map(db_session):
    workspace = Workspace(
        id="workspace-octocity-multi-map",
        slug="octocity-mission-room",
        name="Octocity multi-map",
        mode="demo",
        settings={"mission_room": {"profile": "octocity_institutional_v1"}},
    )
    user = User(
        id="user-octocity-multi-map",
        username="octocity-multi-map-operator",
        email="octocity-multi-map@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    fixture_map = ensure_workspace_map_seed(db_session, workspace)
    fixture_score_ids = {
        score.id
        for score in db_session.query(WorkspaceMapScore)
        .filter_by(map_id=fixture_map.id)
        .all()
    }

    operator_map = WorkspaceMap(
        id="octocity-operator-map-id",
        workspace_id=workspace.id,
        slug="octocity-operator-map",
        name="Octocity operator map",
        description="An independently managed operator map.",
        country="France",
        projection="operator_local_grid_v1",
        view_box="0 0 100 100",
        center={"x": 50, "y": 50},
        settings={
            "operator": True,
            "renderer_config": {"bounds": [[1.0, 43.0], [5.0, 49.0]]},
        },
    )
    operator_zone = WorkspaceMapZone(
        id="octocity-operator-zone-id",
        map_id=operator_map.id,
        zone_key="operator-sector-alpha",
        name="Operator sector Alpha",
        level=91,
        tone="critical",
        polygon="10,10 90,10 90,90 10,90",
        centroid={"x": 50, "y": 50},
        meta_data={
            "signals": ["Operator-only signal"],
            "recommendations": ["Operator-only review"],
        },
        source_refs=["operator-only-source"],
    )
    db_session.add_all([operator_map, operator_zone])
    db_session.commit()

    client = _client(db_session, workspace, user)
    detailed = client.get(f"/api/v1/maps/{operator_map.slug}")
    scored = client.post(f"/api/v1/maps/{operator_map.slug}/score")
    fixture_detail = client.get(f"/api/v1/maps/{fixture_map.slug}")

    assert detailed.status_code == 200
    assert scored.status_code == 200
    assert fixture_detail.status_code == 200
    for body in (detailed.json(), scored.json()):
        assert body["map_system"]["id"] == operator_map.id
        assert body["map_system"]["slug"] == operator_map.slug
        assert body["map_system"]["map_version"] == "workspace_map_v1"
        assert body["map_system"]["rendering_profile"] == "workspace_operator_v1"
        assert body["map_system"]["renderer_config"]["bounds"] == [
            [1.0, 43.0],
            [5.0, 49.0],
        ]
        assert {zone["id"] for zone in body["zones"]} == {
            operator_zone.zone_key,
        }
        assert body["score_summary"]["top_zone"]["id"] == operator_zone.zone_key
        assert body["map"]["projection"] == operator_map.projection
        rendered_zones = body["map_system"]["geojson_sources"]["zones"]["features"]
        assert {feature["properties"]["zone_id"] for feature in rendered_zones} == {
            operator_zone.zone_key,
        }
        assert operator_zone.zone_key in body["map_system"]["camera_presets"]

    assert scored.json()["result"]["map_id"] == operator_map.id
    assert {
        score.id
        for score in db_session.query(WorkspaceMapScore)
        .filter_by(map_id=fixture_map.id)
        .all()
    } == fixture_score_ids
    assert fixture_detail.json()["map_system"]["id"] == fixture_map.id
    assert fixture_detail.json()["map_system"]["map_version"] == "octocity_map_v1"
    assert fixture_detail.json()["map_system"]["renderer_config"]["bounds"] == [
        [-5.3, 42.35],
        [8.1, 50.8],
    ]


def test_octocity_maps_api_returns_only_the_octocity_fixture(db_session):
    workspace = Workspace(
        id="workspace-octocity-map-api",
        slug="octocity-mission-room",
        name="Octocity Mission Room",
        mode="demo",
        settings={
            "mission_room": {"profile": "octocity_institutional_v1"},
        },
    )
    user = User(
        id="user-octocity-map-api",
        username="octocity-operator",
        email="octocity-operator@example.test",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.commit()
    map_row = ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    client = _client(db_session, workspace, user)
    listed = client.get("/api/v1/maps/")
    detailed = client.get(f"/api/v1/maps/{OCTOCITY_MAP_SLUG}")
    zones = client.get(f"/api/v1/maps/{OCTOCITY_MAP_SLUG}/zones")
    command = client.post(
        f"/api/v1/maps/{OCTOCITY_MAP_SLUG}/command",
        json={"intent": "focus_zone", "target": "zone-sud"},
    )
    port_command = client.post(
        f"/api/v1/maps/{OCTOCITY_MAP_SLUG}/command",
        json={"intent": "focus_port", "target": "abidjan"},
    )
    reset_command = client.post(
        f"/api/v1/maps/{OCTOCITY_MAP_SLUG}/command",
        json={"intent": "reset_view"},
    )
    scored = client.post(f"/api/v1/maps/{OCTOCITY_MAP_SLUG}/score")
    recommendations = client.get(f"/api/v1/maps/{OCTOCITY_MAP_SLUG}/recommendations")

    assert listed.status_code == 200
    assert detailed.status_code == 200
    assert zones.status_code == 200
    assert command.status_code == 200
    assert port_command.status_code == 200
    assert reset_command.status_code == 200
    assert scored.status_code == 200
    assert recommendations.status_code == 200
    listed_map = listed.json()["maps"][0]
    assert listed_map["id"] == map_row.id
    assert listed_map["slug"] == OCTOCITY_MAP_SLUG
    assert listed_map["country"] == "France"
    assert listed_map["settings"]["fixture_profile"] == OCTOCITY_MAP_FIXTURE_PROFILE
    assert listed_map["map_version"] == "octocity_map_v1"
    assert listed_map["rendering_profile"] == "octocity_operating_v1"
    assert listed_map["country_boundary"]["features"] == []
    assert listed_map["district_boundaries"]["features"] == []
    assert listed_map["admin_boundaries"]["features"] == []
    assert {feature["properties"]["name"] for feature in listed_map["cities"]["features"]} >= {
        "Paris",
        "Lyon",
        "Marseille",
    }
    assert {feature["properties"]["zone_id"] for feature in listed_map["geojson_sources"]["markers"]["features"]} == {
        "zone-nord",
        "zone-ouest",
        "zone-centre",
        "zone-est",
        "zone-sud",
    }
    assert command.json()["map_slug"] == OCTOCITY_MAP_SLUG
    assert command.json()["target"] == "zone-sud"
    assert port_command.json()["target"] == "port-marseille"
    assert port_command.json()["map_state"]["selected_port"] == "port-marseille"
    assert "maritime-traffic" not in port_command.json()["map_state"]["active_layers"]
    assert reset_command.json()["explanation"].startswith("Vue Octocity")

    api_text = json.dumps(
        {
            "listed": listed.json(),
            "detailed": detailed.json(),
            "zones": zones.json(),
            "command": command.json(),
            "port_command": port_command.json(),
            "reset_command": reset_command.json(),
            "scored": scored.json(),
            "recommendations": recommendations.json(),
        },
        ensure_ascii=False,
    ).lower()
    for forbidden in ("sentinel", "cote d'ivoire", "côte d'ivoire", "abidjan", "aya"):
        assert forbidden not in api_text
