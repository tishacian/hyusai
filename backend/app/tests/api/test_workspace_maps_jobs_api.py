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
    assert listed.json()["maps"][0]["geojson_sources"]["zones"]["features"]

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
    assert command_body["map_state"]["camera"]["longitude"]
