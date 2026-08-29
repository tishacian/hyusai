"""Unit tests for the multi-server MCP connector registry."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.connectors.mcp import service as mcp_service
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
