"""API tests for GET/PUT /api/v1/workspaces/{slug}/apps."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import apps as apps_endpoint
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def _client(db_session, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(apps_endpoint.router, prefix="/api/v1/workspaces")
    app.dependency_overrides[apps_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[apps_endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _seed_workspace(
    db_session,
    *,
    slug: str = "agentium-showcase",
    role: str = "owner",
    role_template: str = "workspace_owner",
    settings: dict | None = None,
):
    workspace = Workspace(
        id=str(uuid4()),
        slug=slug,
        name=slug.upper(),
        mode="portfolio",
        settings=settings or {},
    )
    user = User(
        id=str(uuid4()),
        username=f"user-{slug}",
        email=f"{slug}@example.test",
        is_active=True,
    )
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
        role_template=role_template,
    )
    db_session.add_all([workspace, user, member])
    db_session.commit()
    db_session.refresh(workspace)
    return workspace, user


def test_get_apps_empty_defaults(db_session):
    workspace, user = _seed_workspace(db_session)
    client = _client(db_session, user)

    res = client.get(f"/api/v1/workspaces/{workspace.slug}/apps")
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] == []
    assert body["has_wired_apps"] is True
    rpa = next(a for a in body["apps"] if a["id"] == "rpa_bridge")
    assert rpa["wiring"] == "wired"
    assert rpa["enabled"] is False
    assert rpa["skills"] == ["rpa_dispatch_v1"]
    assert rpa["connector_route"] == "/connectors/rpa-bridge"
    catalog = next(a for a in body["apps"] if a["id"] == "sql_query")
    assert catalog["wiring"] == "catalog"


def test_put_apps_enables_wired_and_syncs_skills(db_session):
    workspace, user = _seed_workspace(
        db_session,
        settings={"catalog": {"enabled_skills": ["sap_hana_query_v1"]}},
    )
    client = _client(db_session, user)

    res = client.put(
        f"/api/v1/workspaces/{workspace.slug}/apps",
        json={"enabled": ["rpa_bridge", "sql_query"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] == ["rpa_bridge", "sql_query"]
    rpa = next(a for a in body["apps"] if a["id"] == "rpa_bridge")
    assert rpa["enabled"] is True
    assert body["wired_enabled_count"] == 1

    db_session.refresh(workspace)
    settings = workspace.settings or {}
    assert settings["apps"]["enabled"] == ["rpa_bridge", "sql_query"]
    assert "rpa_dispatch_v1" in settings["catalog"]["enabled_skills"]
    assert "sap_hana_query_v1" in settings["catalog"]["enabled_skills"]


def test_put_apps_accepts_bool_map_and_disables_wired_skill(db_session):
    workspace, user = _seed_workspace(
        db_session,
        settings={
            "apps": {"enabled": ["rpa_bridge"]},
            "catalog": {"enabled_skills": ["rpa_dispatch_v1", "sap_hana_query_v1"]},
        },
    )
    client = _client(db_session, user)

    res = client.put(
        f"/api/v1/workspaces/{workspace.slug}/apps",
        json={"enabled": {"rpa_bridge": False, "memory": True}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] == ["memory"]

    db_session.refresh(workspace)
    skills = workspace.settings["catalog"]["enabled_skills"]
    assert "rpa_dispatch_v1" not in skills
    assert "sap_hana_query_v1" in skills


def test_put_apps_requires_admin(db_session):
    workspace, user = _seed_workspace(
        db_session,
        role="member",
        role_template="workspace_contributor",
    )
    client = _client(db_session, user)

    res = client.put(
        f"/api/v1/workspaces/{workspace.slug}/apps",
        json={"enabled": ["rpa_bridge"]},
    )
    assert res.status_code == 403


def test_get_apps_unknown_workspace(db_session):
    _, user = _seed_workspace(db_session)
    client = _client(db_session, user)
    res = client.get("/api/v1/workspaces/missing-ws/apps")
    assert res.status_code == 404
