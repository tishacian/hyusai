"""The connector catalogue is readable without opening the connector framework."""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import connections, connector_catalog
from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.db.base import get_db
from app.models.user import User
from app.services.connectors.catalog import official_tool_servers, profile_certification
from app.services.connectors.profiles import list_profiles
from app.tests.services.test_connection_registry import setup as connection_setup

setup = connection_setup


def api(db, user, workspace):
    app = FastAPI()
    app.include_router(connector_catalog.router, prefix="/connector-catalog")
    app.include_router(connections.router, prefix="/connections")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_workspace] = lambda: workspace
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_catalog_stays_readable_while_connections_are_closed(db_session, setup, monkeypatch):
    monkeypatch.setattr(settings, "connector_framework_enabled", False)
    client = api(db_session, setup[2][1], setup[0])

    closed = client.get("/connections/profiles")
    assert closed.status_code == 404
    assert closed.json()["detail"]["code"] == "CONNECTOR_FRAMEWORK_DISABLED"

    response = client.get("/connector-catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["framework_enabled"] is False
    assert {row["key"] for row in body["profiles"]} == {p.key for p in list_profiles()}
    assert [row["key"] for row in body["tool_servers"]] == [
        entry["key"] for entry in official_tool_servers()
    ]


def test_catalog_reports_an_open_framework(db_session, setup):
    body = api(db_session, setup[2][1], setup[0]).get("/connector-catalog").json()
    assert body["framework_enabled"] is True


def test_catalog_exposes_no_parameter_package_endpoint_or_secret(db_session, setup):
    body = api(db_session, setup[2][1], setup[0]).get("/connector-catalog").json()
    for row in body["profiles"]:
        assert set(row) == {"key", "family", "label_key", "capabilities", "certification"}
    for row in body["tool_servers"]:
        assert set(row) == {"key", "publisher", "documentation", "auth_mode", "certification"}
        assert row["certification"] == "third_party"
    raw = str(body)
    for forbidden in (
        "parameters",
        "packages",
        "base_url",
        "tool_allowlist",
        "api.githubcopilot.com",
    ):
        assert forbidden not in raw


def test_catalog_levels_match_the_profiles_route(db_session, setup):
    client = api(db_session, setup[2][1], setup[0])
    catalog = {
        row["key"]: row["certification"]
        for row in client.get("/connector-catalog").json()["profiles"]
    }
    profiles = {
        row["key"]: row["certification"]
        for row in client.get("/connections/profiles").json()["profiles"]
    }
    assert catalog == profiles
    assert all(level in {"unverified", "third_party"} for level in catalog.values())
    assert {p.key: profile_certification(p) for p in list_profiles()} == catalog


def test_catalog_requires_workspace_membership(db_session, setup):
    stranger = User(
        id=str(uuid4()),
        username="catalog-stranger",
        email="catalog-stranger@test.example",
        role="user",
    )
    db_session.add(stranger)
    db_session.commit()
    response = api(db_session, stranger, setup[0]).get("/connector-catalog")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
