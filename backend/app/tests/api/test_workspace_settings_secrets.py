"""Workspace settings reach the browser without a connector secret, whatever the role."""

from __future__ import annotations

import base64
import copy
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth, runs
from app.core.auth import get_current_workspace
from app.core.iam.roles import WORKSPACE_OWNER
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.connectors.generic import service as generic_service
from app.services.connectors.hana import service as hana_service
from app.services.connectors.mcp import service as mcp_service
from app.services.connectors.rpa import service as rpa_service
from app.services.model_plane import workspace_config
from app.services.run_engine import dag

SECRETS = {
    "hana": "hana-password-never-echoed",
    "rpa": "rpa-token-never-echoed",
    "erp_token": "erp-token-never-echoed",
    "erp_oauth": "erp-oauth-secret-never-echoed",
    "crm_token": "crm-token-never-echoed",
    "shared_oauth": "shared-oauth-secret-never-echoed",
    "openai": "openai-key-never-echoed",
    "azure": "azure-key-never-echoed",
    "node_a": "node-a-token-never-echoed",
    "node_b": "node-b-token-never-echoed",
    "smtp": "smtp-password-never-echoed",
    "postgres": "pg-password-never-echoed",
}
FERNET_KEYS = (
    "HANA_CONNECTOR_FERNET_KEY",
    "RPA_CONNECTOR_FERNET_KEY",
    "MCP_CONNECTOR_FERNET_KEY",
    "LLM_PORTAL_FERNET_KEY",
    "CONNECTOR_SECRETS_FERNET_KEY",
)


@pytest.fixture(autouse=True)
def _plaintext_envelopes(monkeypatch):
    # Without a key every envelope is base64: the case a leak exposes in clear.
    for name in FERNET_KEYS:
        monkeypatch.delenv(name, raising=False)


def _stored_settings() -> dict:
    return {
        "family": "generic",
        "connectors": {
            "sap_hana": {
                "host": "hana.example.test",
                "port": 443,
                "user": "AGENT",
                "encrypt": True,
                "password_encrypted": hana_service._encrypt_secret(SECRETS["hana"]),
            },
            "rpa_bridge": {
                "base_url": "https://rpa.example.test",
                "job_mapping": {},
                "auth_token_encrypted": rpa_service._encrypt_secret(SECRETS["rpa"]),
            },
            "mcp": {
                "servers": [
                    {
                        "id": "erp",
                        "label": "ERP",
                        "url": "https://erp.example.test/mcp",
                        "auth_mode": "oauth_client_credentials",
                        "oauth_token_url": "https://login.example.test/token",
                        "oauth_client_id": "agentium",
                        "token_encrypted": mcp_service._encrypt_secret(SECRETS["erp_token"]),
                        "oauth_client_secret_encrypted": mcp_service._encrypt_secret(
                            SECRETS["erp_oauth"]
                        ),
                    },
                    {
                        "id": "crm",
                        "label": "CRM",
                        "url": "https://crm.example.test/mcp",
                        "token_encrypted": mcp_service._encrypt_secret(SECRETS["crm_token"]),
                    },
                ],
                "shared_auth": {
                    "oauth_client_id": "agentium",
                    "oauth_client_secret_encrypted": mcp_service._encrypt_secret(
                        SECRETS["shared_oauth"]
                    ),
                },
            },
        },
        workspace_config.SETTINGS_KEY: {
            "cloud_credentials": {
                "openai": {"api_key_encrypted": workspace_config.encrypt_secret(SECRETS["openai"])},
                "azure_openai": {
                    "endpoint": "https://aoai.example.test",
                    "api_key_encrypted": workspace_config.encrypt_secret(SECRETS["azure"]),
                },
            },
            "serving_nodes": [
                {
                    "name": "gpu-a",
                    "base_url": "https://gpu-a.example.test",
                    "token_encrypted": workspace_config.encrypt_secret(SECRETS["node_a"]),
                },
                {
                    "name": "gpu-b",
                    "base_url": "https://gpu-b.example.test",
                    "token_encrypted": workspace_config.encrypt_secret(SECRETS["node_b"]),
                },
            ],
        },
        "client360_pdr_mail": {
            "smtp": {"host": "smtp.example.test", "username": "bot", "password": SECRETS["smtp"]}
        },
        generic_service.SETTINGS_KEY: {
            "postgresql": {
                "values": {"host": "db.example.test"},
                "secrets": {"password": generic_service._encrypt_secret(SECRETS["postgres"])},
            }
        },
    }


def _assert_no_secret(text: str) -> None:
    assert "_encrypted" not in text
    assert generic_service.SETTINGS_KEY not in text
    for secret in SECRETS.values():
        assert secret not in text
        assert base64.b64encode(secret.encode()).decode() not in text


def _user(db_session) -> User:
    user = User(
        id=str(uuid4()),
        username=f"settings-{uuid4().hex[:8]}",
        email=f"settings-{uuid4().hex[:8]}@example.test",
        role="user",
    )
    db_session.add(user)
    return user


def _seed(db_session):
    workspace = Workspace(
        id=str(uuid4()),
        name="Workspace secrets",
        slug=f"workspace-secrets-{uuid4().hex[:8]}",
        settings=_stored_settings(),
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
    app.include_router(auth.router, prefix="/auth")
    app.include_router(runs.router, prefix="/runs")
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[get_current_workspace] = lambda: workspace
    app.dependency_overrides[auth.get_db] = lambda: db_session
    return TestClient(app)


@pytest.mark.parametrize("role", ["member", "owner"])
def test_no_workspace_response_hands_back_a_secret(db_session, role):
    workspace, owner, member = _seed(db_session)
    client = _client(db_session, workspace, owner if role == "owner" else member)
    path = f"/auth/workspaces/{workspace.slug}"

    listed = client.get("/auth/workspaces")
    detail = client.get(path)
    settings = detail.json()["settings"]
    responses = [
        listed,
        detail,
        client.patch(path, json={"settings": {**settings, "demo_safe": True}}),
        client.patch(f"{path}/mode", json={"mode": "operator"}),
        client.post("/auth/workspaces", json={"name": f"Created by {role}"}),
    ]

    expected = [200, 200, 200, 200, 201] if role == "owner" else [200, 200, 403, 403, 201]
    assert [response.status_code for response in responses] == expected
    for response in responses:
        _assert_no_secret(response.text)
    assert settings["connectors"]["sap_hana"]["host"] == "hana.example.test"
    assert [row["url"] for row in settings["connectors"]["mcp"]["servers"]] == [
        "https://erp.example.test/mcp",
        "https://crm.example.test/mcp",
    ]
    assert settings["client360_pdr_mail"]["smtp"] == {
        "host": "smtp.example.test",
        "username": "bot",
    }


def test_a_settings_round_trip_keeps_every_secret_and_every_indicator(db_session):
    workspace, owner, _member = _seed(db_session)
    client = _client(db_session, workspace, owner)
    before = copy.deepcopy(workspace.settings)
    path = f"/auth/workspaces/{workspace.slug}"

    settings = client.get(path).json()["settings"]
    assert client.patch(path, json={"settings": {**settings, "demo_safe": True}}).status_code == 200

    db_session.refresh(workspace)
    assert workspace.settings == {**before, "demo_safe": True}
    assert hana_service.get_config(workspace, include_secrets=True)["password"] == SECRETS["hana"]
    assert rpa_service.get_config(workspace, include_secrets=True)["auth_token"] == SECRETS["rpa"]
    assert mcp_service.get_decrypted_token(workspace, "erp") == SECRETS["erp_token"]
    assert mcp_service.get_decrypted_oauth_secret(workspace, "erp") == SECRETS["erp_oauth"]
    assert workspace_config.get_decrypted_api_key(workspace, "openai") == SECRETS["openai"]

    assert hana_service.get_config(workspace)["password_set"] is True
    assert rpa_service.get_config(workspace)["auth_token_set"] is True
    mcp_public = mcp_service.get_servers(workspace)
    assert [row["token_set"] for row in mcp_public["servers"]] == [True, True]
    assert mcp_public["servers"][0]["oauth_secret_set"] is True
    assert mcp_public["shared_auth"]["secret_set"] is True
    portal = workspace_config.get_public_config(workspace)
    assert {row["key"]: row["api_key_set"] for row in portal["cloud_credentials"]}["openai"] is True
    assert [node["token_set"] for node in portal["serving_nodes"]] == [True, True]


def test_a_settings_patch_cannot_write_a_secret(db_session):
    workspace, owner, member = _seed(db_session)
    path = f"/auth/workspaces/{workspace.slug}"
    client = _client(db_session, workspace, owner)
    before = copy.deepcopy(workspace.settings)
    settings = client.get(path).json()["settings"]
    forged = "forged-value-never-stored"

    hana = copy.deepcopy(settings)
    hana["connectors"]["sap_hana"]["password_encrypted"] = forged
    mcp = copy.deepcopy(settings)
    mcp["connectors"]["mcp"]["servers"][1]["token_encrypted"] = forged
    smtp = copy.deepcopy(settings)
    smtp["client360_pdr_mail"]["smtp"]["password"] = forged
    attempts = [
        (hana, "settings.connectors.sap_hana.password_encrypted"),
        (mcp, "settings.connectors.mcp.servers[1].token_encrypted"),
        (smtp, "settings.client360_pdr_mail.smtp.password"),
    ]
    for payload, field in attempts:
        refused = client.patch(path, json={"settings": payload})
        assert refused.status_code == 422
        assert refused.json()["detail"]["code"] == "WORKSPACE_SECRET_WRITE_ONLY"
        assert refused.json()["detail"]["fields"] == [field]
        assert forged not in refused.text

    as_member = _client(db_session, workspace, member)
    assert as_member.patch(path, json={"settings": hana}).status_code == 403
    db_session.refresh(workspace)
    assert workspace.settings == before


def test_list_items_keep_their_secrets_by_id_or_by_name(db_session):
    workspace, owner, _member = _seed(db_session)
    client = _client(db_session, workspace, owner)
    path = f"/auth/workspaces/{workspace.slug}"
    settings = client.get(path).json()["settings"]
    erp, crm = settings["connectors"]["mcp"]["servers"]
    gpu_a, _gpu_b = settings[workspace_config.SETTINGS_KEY]["serving_nodes"]

    settings["connectors"]["mcp"]["servers"] = [
        crm,
        {**erp, "label": "ERP renamed"},
        {"id": "erp_copy", "label": "Same URL, other id", "url": erp["url"]},
    ]
    settings[workspace_config.SETTINGS_KEY]["serving_nodes"] = [
        {"name": "gpu-c", "base_url": "https://gpu-c.example.test"},
        gpu_a,
    ]
    assert client.patch(path, json={"settings": settings}).status_code == 200

    db_session.refresh(workspace)
    servers = {row["id"]: row for row in workspace.settings["connectors"]["mcp"]["servers"]}
    assert list(servers) == ["crm", "erp", "erp_copy"]
    assert servers["erp"]["label"] == "ERP renamed"
    assert mcp_service.get_decrypted_token(workspace, "erp") == SECRETS["erp_token"]
    assert mcp_service.get_decrypted_oauth_secret(workspace, "erp") == SECRETS["erp_oauth"]
    assert mcp_service.get_decrypted_token(workspace, "crm") == SECRETS["crm_token"]
    assert "token_encrypted" not in servers["erp_copy"]
    assert {
        node["name"]: node["token"]
        for node in workspace_config.list_serving_node_configs(workspace)
    } == {"gpu-c": "", "gpu-a": SECRETS["node_a"]}


def test_a_paused_run_hands_back_no_secret_its_pool_copied(db_session):
    workspace, _owner, member = _seed(db_session)
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Ordinary workflow",
        objective="test",
        status="active",
        settings={},
        flow_definition={},
    )
    # What the pool copied before it read only public settings.
    copied = dag._without_secret_values(workspace.settings)
    assert "password_encrypted" in copied["connectors"]["sap_hana"]
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=member.id,
        status="completed",
        checkpoints=[
            {
                "kind": "hitl_pause",
                "node_id": "approve",
                "state": {"pool": {"workspace": {"id": workspace.id, "settings": copied}}},
            }
        ],
    )
    db_session.add_all([system, run])
    db_session.commit()
    client = _client(db_session, workspace, member)

    detail = client.get(f"/runs/{run.id}")
    listed = client.get("/runs")
    assert [detail.status_code, listed.status_code] == [200, 200]
    for response in (detail, listed):
        _assert_no_secret(response.text)
    pooled = detail.json()["checkpoints"][0]["state"]["pool"]["workspace"]["settings"]
    assert pooled["connectors"]["sap_hana"]["host"] == "hana.example.test"
