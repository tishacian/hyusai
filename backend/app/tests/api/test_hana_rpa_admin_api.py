"""HANA and RPA config/test routes: admin write, masked reads, no secret echo."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import hana, rpa
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR, WORKSPACE_OWNER
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.connectors.hana import service as hana_service
from app.services.connectors.rpa import service as rpa_service

HANA_PASSWORD = "hana-password-never-echoed"
RPA_TOKEN = "rpa-token-never-echoed"


def _user(db_session, suffix: str) -> User:
    user = User(
        id=str(uuid4()),
        username=f"{suffix}-{uuid4().hex[:8]}",
        email=f"{suffix}-{uuid4().hex[:8]}@example.test",
        role="user",
    )
    db_session.add(user)
    return user


def _seed(db_session):
    workspace = Workspace(
        id=str(uuid4()),
        name="Connector admin API",
        slug=f"connector-admin-{uuid4().hex[:8]}",
        settings={
            "family": "generic",
            "features": {"sap_hana_connector": True, "rpa_bridge": True},
        },
    )
    owner, member = _user(db_session, "owner"), _user(db_session, "member")
    db_session.add(workspace)
    db_session.add_all(
        [
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner.id,
                role="owner",
                role_template=WORKSPACE_OWNER,
            ),
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=member.id,
                role="member",
                role_template=WORKSPACE_CONTRIBUTOR,
            ),
        ]
    )
    db_session.commit()
    return workspace, owner, member


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(hana.router, prefix="/hana")
    app.include_router(rpa.router, prefix="/rpa")
    app.dependency_overrides[hana.get_current_user] = lambda: user
    app.dependency_overrides[hana.get_current_workspace] = lambda: workspace
    app.dependency_overrides[hana.get_db] = lambda: db_session
    app.dependency_overrides[rpa.get_current_user] = lambda: user
    app.dependency_overrides[rpa.get_current_workspace] = lambda: workspace
    app.dependency_overrides[rpa.get_db] = lambda: db_session
    return TestClient(app)


def test_a_member_cannot_write_or_test_hana_or_rpa(db_session):
    workspace, _owner, member = _seed(db_session)
    client = _client(db_session, workspace, member)

    assert client.get("/hana/config").status_code == 200
    assert client.get("/rpa/config").status_code == 200
    assert (
        client.put(
            "/hana/config",
            json={"host": "hana.example.test", "user": "DEMO", "password": HANA_PASSWORD},
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/rpa/config",
            json={"base_url": "https://rpa.example.test", "auth_token": RPA_TOKEN},
        ).status_code
        == 403
    )
    assert client.post("/hana/test").status_code == 403
    assert client.post("/rpa/test").status_code == 403
    db_session.refresh(workspace)
    assert "connectors" not in (workspace.settings or {})


def test_an_admin_writes_hana_and_rpa_without_echoing_secrets(db_session, monkeypatch):
    monkeypatch.delenv(hana_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(rpa_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(rpa_service.ENV_MASTER_KEY_FALLBACK, raising=False)
    workspace, owner, _member = _seed(db_session)
    client = _client(db_session, workspace, owner)

    hana_saved = client.put(
        "/hana/config",
        json={"host": "hana.example.test", "user": "DEMO", "password": HANA_PASSWORD},
    )
    rpa_saved = client.put(
        "/rpa/config",
        json={"base_url": "https://rpa.example.test", "auth_token": RPA_TOKEN},
    )
    assert hana_saved.status_code == 200, hana_saved.text
    assert rpa_saved.status_code == 200, rpa_saved.text
    assert hana_saved.json()["password_set"] is True
    assert rpa_saved.json()["auth_token_set"] is True
    assert "password" not in hana_saved.json()
    assert "auth_token" not in rpa_saved.json()
    assert HANA_PASSWORD not in hana_saved.text
    assert RPA_TOKEN not in rpa_saved.text

    hana_get = client.get("/hana/config")
    rpa_get = client.get("/rpa/config")
    assert hana_get.status_code == 200
    assert rpa_get.status_code == 200
    assert "password" not in hana_get.json()
    assert "auth_token" not in rpa_get.json()
    assert HANA_PASSWORD not in hana_get.text
    assert RPA_TOKEN not in rpa_get.text

    db_session.refresh(workspace)
    stored = workspace.settings["connectors"]
    assert HANA_PASSWORD not in str(stored)
    assert RPA_TOKEN not in str(stored)
    assert hana_service.get_config(workspace, include_secrets=True)["password"] == HANA_PASSWORD
    assert rpa_service.get_config(workspace, include_secrets=True)["auth_token"] == RPA_TOKEN


def test_an_admin_test_route_is_allowed_and_does_not_echo_secrets(db_session, monkeypatch):
    workspace, owner, _member = _seed(db_session)
    client = _client(db_session, workspace, owner)
    monkeypatch.setattr(
        hana_service,
        "test_connection",
        lambda config: {"ok": True, "duration_ms": 1},
    )
    monkeypatch.setattr(
        rpa_service,
        "test_connection",
        lambda config: {"ok": True, "duration_ms": 1},
    )

    assert client.post("/hana/test").status_code == 200
    assert client.post("/rpa/test").status_code == 200
    assert HANA_PASSWORD not in client.post("/hana/test").text
    assert RPA_TOKEN not in client.post("/rpa/test").text


def test_encrypted_fields_cannot_be_written_on_hana_or_rpa(db_session):
    workspace, owner, _member = _seed(db_session)
    client = _client(db_session, workspace, owner)

    hana_forged = client.put(
        "/hana/config",
        json={
            "host": "hana.example.test",
            "user": "DEMO",
            "password_encrypted": "forged-envelope",
        },
    )
    rpa_forged = client.put(
        "/rpa/config",
        json={
            "base_url": "https://rpa.example.test",
            "auth_token_encrypted": "forged-envelope",
        },
    )
    assert hana_forged.status_code == 422
    assert hana_forged.json()["detail"]["code"] == "WORKSPACE_SECRET_WRITE_ONLY"
    assert rpa_forged.status_code == 422
    assert rpa_forged.json()["detail"]["code"] == "WORKSPACE_SECRET_WRITE_ONLY"


@pytest.mark.parametrize("writes_enabled", [False, True])
def test_member_cannot_authorize_hana_writes_in_payload(db_session, monkeypatch, writes_enabled):
    workspace, _owner, member = _seed(db_session)
    monkeypatch.setattr(hana.settings, "hana_writes_enabled", writes_enabled)
    calls = []
    monkeypatch.setattr(hana_service, "run_query", lambda *args, **kwargs: calls.append(kwargs))
    response = _client(db_session, workspace, member).post(
        "/hana/query", json={"sql": "DELETE FROM BUSINESS_RECORDS", "allow_writes": True}
    )
    assert response.status_code == 403
    assert calls == []


@pytest.mark.parametrize(
    "sql",
    ["DELETE FROM BUSINESS_RECORDS", "WITH C AS (DELETE FROM BUSINESS_RECORDS) SELECT * FROM C"],
)
def test_member_cannot_hide_write_in_readonly_query(db_session, monkeypatch, sql):
    workspace, _owner, member = _seed(db_session)
    connections = []
    monkeypatch.setattr(hana_service, "_connect", lambda config: connections.append(config))
    response = _client(db_session, workspace, member).post("/hana/query", json={"sql": sql})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "HANA_INVALID_REQUEST"
    assert connections == []


@pytest.mark.parametrize("writes_enabled", [False, True])
def test_hana_admin_writes_also_need_server_flag(db_session, monkeypatch, writes_enabled):
    workspace, owner, _member = _seed(db_session)
    monkeypatch.setattr(hana.settings, "hana_writes_enabled", writes_enabled)
    calls = []

    def execute(config, **kwargs):
        calls.append(kwargs)
        return {"rows": [], "row_count": 1}

    monkeypatch.setattr(hana_service, "run_query", execute)
    response = _client(db_session, workspace, owner).post(
        "/hana/query", json={"sql": "UPDATE BUSINESS_RECORDS SET X = 1", "allow_writes": True}
    )
    assert response.status_code == (200 if writes_enabled else 403)
    assert len(calls) == int(writes_enabled)
    if calls:
        assert calls[0]["allow_writes"] is True


@pytest.mark.parametrize(
    "route,method,operation",
    [
        ("/hana/query", "post", "run_query"),
        ("/hana/test", "post", "test_connection"),
        ("/hana/preview", "get", "preview_catalog"),
    ],
)
def test_hana_driver_errors_are_closed_and_blocking_work_runs_off_loop(
    db_session, monkeypatch, route, method, operation
):
    import asyncio

    workspace, owner, _member = _seed(db_session)

    def fail(*args, **kwargs):
        # A hdbcli call must not occupy the FastAPI event-loop thread.
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        raise RuntimeError(f"driver error: password={HANA_PASSWORD}")

    monkeypatch.setattr(hana_service, operation, fail)
    client = _client(db_session, workspace, owner)
    response = getattr(client, method)(
        route, **({"json": {"sql": "SELECT 1 FROM DUMMY"}} if route.endswith("query") else {})
    )
    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "HANA_OPERATION_FAILED"}}
    assert HANA_PASSWORD not in response.text


def test_hana_password_cannot_be_reused_on_another_destination(db_session):
    workspace, owner, _member = _seed(db_session)
    client = _client(db_session, workspace, owner)
    assert (
        client.put(
            "/hana/config",
            json={"host": "hana.example.test", "user": "DEMO", "password": HANA_PASSWORD},
        ).status_code
        == 200
    )
    response = client.put("/hana/config", json={"host": "attacker.example.test", "user": "DEMO"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "HANA_CREDENTIAL_DESTINATION_CHANGED"
    db_session.refresh(workspace)
    assert workspace.settings["connectors"]["sap_hana"]["host"] == "hana.example.test"


def test_hana_tls_cannot_be_disabled_by_workspace_payload(db_session, monkeypatch):
    workspace, owner, _member = _seed(db_session)
    monkeypatch.setattr(hana.settings, "hana_allow_insecure_tls", False)
    response = _client(db_session, workspace, owner).put(
        "/hana/config",
        json={
            "host": "hana.example.test",
            "user": "DEMO",
            "password": HANA_PASSWORD,
            "ssl_validate_certificate": False,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "HANA_TLS_REQUIRED"
