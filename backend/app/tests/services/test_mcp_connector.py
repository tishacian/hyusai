"""Unit tests for the multi-server MCP connector registry."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.connectors.mcp import service as mcp_service
from app.services.connectors.mcp.contract import normalize_auth_mode, normalize_transport
from app.services.connectors.mcp.errors import McpUnconfigured


def _workspace(slug: str = "nawa", settings: dict | None = None):
    return SimpleNamespace(
        slug=slug,
        name="NAWA",
        settings=settings if settings is not None else {},
    )


def _mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


def test_transport_and_auth_aliases():
    assert normalize_transport("streamableHttp") == "streamable_http"
    assert normalize_transport("http_sse") == "http_sse"
    assert normalize_auth_mode("oauth") == "oauth_client_credentials"
    assert normalize_auth_mode("shared") == "inherit"


def test_feature_gate_is_opt_in():
    assert not mcp_service.is_workspace_enabled(_workspace())
    assert mcp_service.is_workspace_enabled(
        _workspace(settings={"features": {"mcp_connector": True}})
    )
    assert not mcp_service.is_workspace_enabled(
        _workspace(settings={"features": {"mcp_connector": False}})
    )


def test_replace_servers_masks_token_and_keeps_it_when_omitted(monkeypatch):
    monkeypatch.delenv(mcp_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(mcp_service.ENV_MASTER_KEY_FALLBACK, raising=False)
    monkeypatch.setattr(mcp_service, "flag_modified", lambda *_a, **_k: None)
    ws = _workspace()
    db = _mock_db()
    first = mcp_service.replace_servers(
        db,
        ws,
        {
            "servers": [
                {
                    "id": "sap",
                    "label": "SAP MCP",
                    "url": "http://127.0.0.1:8765/sap",
                    "token": "secret-token",
                }
            ]
        },
    )
    row = first["servers"][0]
    assert row["id"] == "sap"
    assert row["url"] == "http://127.0.0.1:8765/sap"
    assert row["token_set"] is True
    assert row["configured"] is True
    assert row["credential_source"] == "workspace"
    assert "token" not in row
    assert "token_encrypted" not in row

    mcp_service.replace_servers(
        db,
        ws,
        {
            "servers": [
                {
                    "id": "sap",
                    "label": "SAP MCP",
                    "url": "http://127.0.0.1:8765/sap",
                }
            ]
        },
    )
    assert mcp_service.get_decrypted_token(ws, "sap") == "secret-token"


def test_env_overlay_marks_credential_source_env(monkeypatch):
    monkeypatch.delenv(mcp_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.setattr(mcp_service, "flag_modified", lambda *_a, **_k: None)
    monkeypatch.setenv("MCP_SAP_URL", "http://127.0.0.1:8765/sap")
    monkeypatch.setenv("MCP_SAP_TOKEN", "env-token")
    ws = _workspace()
    db = _mock_db()
    mcp_service.replace_servers(
        db,
        ws,
        {"servers": [{"id": "sap", "label": "SAP MCP", "url": ""}]},
    )
    public = mcp_service.get_server(ws, "sap")
    assert public is not None
    assert public["configured"] is True
    assert public["credential_source"] == "env"
    assert public["url"] == "http://127.0.0.1:8765/sap"
    assert mcp_service.get_decrypted_token(ws, "sap") == "env-token"


def test_resolve_unconfigured_fails_closed(monkeypatch):
    monkeypatch.delenv("MCP_SAP_URL", raising=False)
    monkeypatch.delenv("MCP_SAP_TOKEN", raising=False)
    monkeypatch.setattr(mcp_service, "flag_modified", lambda *_a, **_k: None)
    ws = _workspace()
    db = _mock_db()
    mcp_service.replace_servers(
        db,
        ws,
        {"servers": [{"id": "sap", "label": "SAP MCP", "url": ""}]},
    )
    with pytest.raises(McpUnconfigured, match="mcp_unconfigured"):
        mcp_service.resolve_server(ws, "sap")
    with pytest.raises(McpUnconfigured, match="mcp_unconfigured"):
        mcp_service.resolve_server(ws, "missing")


def test_shared_oauth_is_masked_and_kept_when_omitted(monkeypatch):
    monkeypatch.delenv(mcp_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(mcp_service.ENV_MASTER_KEY_FALLBACK, raising=False)
    monkeypatch.delenv(mcp_service.ENV_SHARED_OAUTH_CLIENT_SECRET, raising=False)
    monkeypatch.setattr(mcp_service, "flag_modified", lambda *_a, **_k: None)
    ws = _workspace()
    db = _mock_db()
    first = mcp_service.replace_servers(
        db,
        ws,
        {
            "shared_auth": {
                "oauth_token_url": "https://auth.example/oauth/token",
                "oauth_client_id": "client-id",
                "oauth_client_secret": "client-secret",
            },
            "servers": [
                {
                    "id": "sap",
                    "label": "Purchase Requisition",
                    "url": "https://mcp.example/pr",
                    "transport": "streamableHttp",
                    "auth_mode": "inherit",
                }
            ],
        },
    )
    shared = first["shared_auth"]
    row = first["servers"][0]
    assert shared["oauth_token_url"] == "https://auth.example/oauth/token"
    assert shared["oauth_client_id"] == "client-id"
    assert shared["secret_set"] is True
    assert "oauth_client_secret" not in shared
    assert row["auth_mode"] == "inherit"
    assert row["transport"] == "streamable_http"
    assert row["oauth_secret_set"] is True
    assert row["configured"] is True
    assert "oauth_client_secret" not in row

    mcp_service.replace_servers(
        db,
        ws,
        {
            "shared_auth": {
                "oauth_token_url": "https://auth.example/oauth/token",
                "oauth_client_id": "client-id",
            },
            "servers": [
                {
                    "id": "sap",
                    "label": "Purchase Requisition",
                    "url": "https://mcp.example/pr",
                    "auth_mode": "inherit",
                }
            ],
        },
    )
    resolved = mcp_service.resolve_server(ws, "sap")
    assert resolved["oauth_client_secret"] == "client-secret"
    assert resolved["auth_mode"] == "inherit"


def test_oauth_without_secret_fails_closed(monkeypatch):
    monkeypatch.delenv(mcp_service.ENV_SHARED_OAUTH_CLIENT_SECRET, raising=False)
    monkeypatch.setattr(mcp_service, "flag_modified", lambda *_a, **_k: None)
    ws = _workspace()
    db = _mock_db()
    mcp_service.replace_servers(
        db,
        ws,
        {
            "shared_auth": {
                "oauth_token_url": "https://auth.example/oauth/token",
                "oauth_client_id": "client-id",
            },
            "servers": [
                {
                    "id": "sap",
                    "url": "https://mcp.example/pr",
                    "auth_mode": "inherit",
                }
            ],
        },
    )
    public = mcp_service.get_server(ws, "sap")
    assert public is not None
    assert public["configured"] is False
    with pytest.raises(McpUnconfigured, match="mcp_unconfigured"):
        mcp_service.resolve_server(ws, "sap")


def test_shared_oauth_env_overlay(monkeypatch):
    monkeypatch.setattr(mcp_service, "flag_modified", lambda *_a, **_k: None)
    monkeypatch.setenv("MCP_OAUTH_TOKEN_URL", "https://auth.example/oauth/token")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "env-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "env-secret")
    ws = _workspace()
    db = _mock_db()
    mcp_service.replace_servers(
        db,
        ws,
        {
            "servers": [
                {
                    "id": "sap_inbox",
                    "label": "Approval",
                    "url": "https://mcp.example/inbox",
                    "auth_mode": "inherit",
                    "transport": "streamable_http",
                }
            ]
        },
    )
    public = mcp_service.get_server(ws, "sap_inbox")
    assert public is not None
    assert public["configured"] is True
    assert public["oauth_client_id"] == "env-client"
    resolved = mcp_service.resolve_server(ws, "sap_inbox")
    assert resolved["oauth_client_secret"] == "env-secret"


def test_replace_servers_keeps_shared_auth_when_omitted(monkeypatch):
    monkeypatch.delenv(mcp_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(mcp_service.ENV_MASTER_KEY_FALLBACK, raising=False)
    monkeypatch.setattr(mcp_service, "flag_modified", lambda *_a, **_k: None)
    ws = _workspace()
    db = _mock_db()
    mcp_service.replace_servers(
        db,
        ws,
        {
            "shared_auth": {
                "oauth_token_url": "https://auth.example/oauth/token",
                "oauth_client_id": "keep-me",
                "oauth_client_secret": "keep-secret",
            },
            "servers": [{"id": "sap", "url": "https://mcp.example/pr", "auth_mode": "inherit"}],
        },
    )
    mcp_service.replace_servers(
        db,
        ws,
        {"servers": [{"id": "hikma", "url": "https://mcp.example/po", "auth_mode": "inherit"}]},
    )
    body = mcp_service.get_servers(ws)
    assert [row["id"] for row in body["servers"]] == ["hikma"]
    assert body["shared_auth"]["oauth_client_id"] == "keep-me"
    assert mcp_service.get_decrypted_oauth_secret(ws) == "keep-secret"
