"""API tests for ``GET /api/v1/mission-room/evidence-graph/trace`` (Phase A)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import mission_room
from app.models.user import User
from app.models.workspace import Workspace


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(mission_room.router, prefix="/api/v1/mission-room")
    app.dependency_overrides[mission_room.get_current_workspace] = lambda: workspace
    app.dependency_overrides[mission_room.get_current_user] = lambda: user
    app.dependency_overrides[mission_room.get_db] = lambda: db_session
    return TestClient(app)


def _seed(db_session) -> tuple[Workspace, User]:
    workspace = Workspace(
        id="workspace-trace",
        slug="sentinel-ci",
        name="SENTINEL-CI",
        mode="demo",
        settings={
            "mission_room": {"enabled": True, "profile": "sentinel_government_v1"},
        },
    )
    user = User(id="user-trace", username="vp", email="vp@example.test", is_active=True)
    db_session.add_all([workspace, user])
    db_session.commit()
    return workspace, user


def test_evidence_graph_trace_returns_caused_by_chain(db_session):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).get(
        "/api/v1/mission-room/evidence-graph/trace",
        params={"from": "zone-nord", "relation": "caused_by", "depth": 4},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["from_node"] == "zone-nord"
    assert body["relation"] == "caused_by"
    path = body.get("path") or []
    assert len(path) >= 3
    first_step = path[0]
    assert (first_step.get("node") or {}).get("id") == "zone-nord"
    edge = first_step.get("edge") or {}
    assert edge.get("relation") == "caused_by"
    chain_ids = [(step.get("node") or {}).get("id") for step in path]
    # The demo causal chain follows zone-nord -> project -> cargo -> customs PV.
    assert chain_ids[0] == "zone-nord"
    assert "cargo-abidjan-supply-001" in chain_ids
    assert "customs-record-non-conformite-2026-05" in chain_ids


def test_evidence_graph_trace_respects_depth_bounds(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    shallow = client.get(
        "/api/v1/mission-room/evidence-graph/trace",
        params={"from": "zone-nord", "relation": "caused_by", "depth": 1},
    )
    assert shallow.status_code == 200
    assert len(shallow.json().get("path") or []) <= 2

    deep = client.get(
        "/api/v1/mission-room/evidence-graph/trace",
        params={"from": "zone-nord", "relation": "caused_by", "depth": 6},
    )
    assert deep.status_code == 200
    assert len(deep.json().get("path") or []) >= 3


def test_evidence_graph_trace_unknown_node_returns_empty_path(db_session):
    workspace, user = _seed(db_session)
    response = _client(db_session, workspace, user).get(
        "/api/v1/mission-room/evidence-graph/trace",
        params={"from": "unknown-node-xyz", "relation": "caused_by", "depth": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["from_node"] == "unknown-node-xyz"
    assert body.get("path") == []
