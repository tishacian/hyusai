"""No API response, audit row or workspace payload hands a connector secret back."""

from __future__ import annotations

import json
import urllib.error
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth, connectors
from app.core.auth import get_current_workspace
from app.core.iam.roles import WORKSPACE_OWNER
from app.models.audit import AuditLog
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.connectors.generic import service as generic_service

SECRET = "pg-password-never-echoed"


@pytest.fixture(autouse=True)
def _no_master_key(monkeypatch):
    monkeypatch.delenv(generic_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(generic_service.ENV_MASTER_KEY_FALLBACK, raising=False)


def _user(db_session) -> User:
    user = User(
        id=str(uuid4()),
        username=f"connectors-{uuid4().hex[:8]}",
        email=f"connectors-{uuid4().hex[:8]}@example.test",
        role="user",
    )
    db_session.add(user)
    return user


def _seed(db_session):
    workspace = Workspace(
        id=str(uuid4()),
        name="Connectors API",
        slug=f"connectors-api-{uuid4().hex[:8]}",
        settings={"family": "generic"},
    )
    db_session.add(workspace)
    owner, member = _user(db_session), _user(db_session)
    db_session.add_all(
        [
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner.id,
                role="owner",
                role_template=WORKSPACE_OWNER,
            ),
            WorkspaceMember(workspace_id=workspace.id, user_id=member.id, role="member"),
        ]
    )
    db_session.commit()
    return workspace, owner, member


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(connectors.router, prefix="/connectors")
    app.include_router(auth.router, prefix="/auth")
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[get_current_workspace] = lambda: workspace
    app.dependency_overrides[auth.get_db] = lambda: db_session
    return TestClient(app)


def _save_postgres(client: TestClient):
    return client.put(
        "/connectors/postgresql",
        json={
            "values": {
                "host": "db.example.test",
                "port": "5432",
                "database": "erp",
                "username": "agent",
                "password": SECRET,
            }
        },
    )


def test_a_saved_secret_comes_back_from_no_response_and_no_audit_row(db_session):
    workspace, owner, _member = _seed(db_session)
    client = _client(db_session, workspace, owner)

    saved = _save_postgres(client)
    assert saved.status_code == 200
    assert saved.json()["secrets_set"] == {"password": True}
    assert saved.json()["values"]["host"] == "db.example.test"

    responses = [
        saved,
        client.get("/connectors"),
        client.get("/auth/workspaces"),
        client.get(f"/auth/workspaces/{workspace.slug}"),
        client.put("/connectors/postgresql", json={"values": {"password": SECRET * 500}}),
    ]
    assert [response.status_code for response in responses] == [200, 200, 200, 200, 400]
    for response in responses:
        assert SECRET not in response.text
        assert generic_service.SETTINGS_KEY not in response.text

    rows = db_session.query(AuditLog).filter(AuditLog.workspace_id == workspace.id).all()
    assert [row.event_type for row in rows] == ["connector.config.updated"]
    assert SECRET not in json.dumps([row.details for row in rows])


def test_a_workspace_settings_round_trip_keeps_the_secret_and_cannot_forge_it(db_session):
    workspace, owner, _member = _seed(db_session)
    client = _client(db_session, workspace, owner)
    assert _save_postgres(client).status_code == 200

    settings = {**client.get(f"/auth/workspaces/{workspace.slug}").json()["settings"], "demo_safe": True}
    patched = client.patch(f"/auth/workspaces/{workspace.slug}", json={"settings": settings})
    assert patched.status_code == 200
    assert SECRET not in patched.text
    db_session.refresh(workspace)
    assert generic_service.get_config(workspace, "postgresql", include_secrets=True)["secrets"] == {
        "password": SECRET
    }

    forged = client.patch(
        f"/auth/workspaces/{workspace.slug}",
        json={"settings": {**settings, generic_service.SETTINGS_KEY: {}}},
    )
    assert forged.status_code == 409
    assert forged.json()["detail"]["code"] == "GENERIC_CONNECTORS_MANAGED"


def test_a_member_reads_the_state_but_cannot_write_clear_or_test(db_session):
    workspace, _owner, member = _seed(db_session)
    client = _client(db_session, workspace, member)

    listing = client.get("/connectors").json()
    assert listing["can_configure"] is False
    assert {row["id"] for row in listing["connectors"]} == set(generic_service.CONNECTORS)
    assert client.put("/connectors/smtp", json={"values": {"password": SECRET}}).status_code == 403
    assert client.delete("/connectors/smtp").status_code == 403
    assert client.post("/connectors/smtp/test").status_code == 403
    assert client.put("/connectors/whatsapp", json={"values": {}}).status_code == 404


def test_the_test_route_answers_from_the_server_with_the_check_time(db_session, monkeypatch):
    workspace, owner, _member = _seed(db_session)
    client = _client(db_session, workspace, owner)

    unsupported = client.post("/connectors/teams/test").json()
    assert unsupported["status"] == "unsupported"
    assert unsupported["checked_at"]
    assert client.post("/connectors/smtp/test").json()["status"] == "not_configured"

    assert client.put("/connectors/telegram", json={"values": {"bot_token": SECRET}}).status_code == 200

    def refuse(url, timeout):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", None, None)

    monkeypatch.setattr(generic_service.urllib.request, "urlopen", refuse)
    tested = client.post("/connectors/telegram/test")
    assert tested.status_code == 200
    assert tested.json()["status"] == "auth_failed"
    assert SECRET not in tested.text

    cleared = client.delete("/connectors/telegram")
    assert cleared.json()["secrets_set"] == {"bot_token": False}
