"""Unit tests for workspace-scoped LLM portal configuration."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.model_plane import serving_nodes as serving_nodes_mod
from app.services.model_plane import workspace_config as ws_cfg


class _FakeDB:
    def add(self, *_a, **_k):
        return None

    def commit(self):
        return None

    def refresh(self, obj):
        return None


def _workspace(settings=None):
    return SimpleNamespace(id=str(uuid4()), settings=settings or {})


def test_encrypt_decrypt_plaintext_envelope(monkeypatch):
    monkeypatch.delenv(ws_cfg.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv("HANA_CONNECTOR_FERNET_KEY", raising=False)
    blob = ws_cfg.encrypt_secret("sk-test-secret")
    assert "plaintext" in blob
    assert ws_cfg.decrypt_secret(blob) == "sk-test-secret"


def test_set_routing_and_credentials():
    db = _FakeDB()
    ws = _workspace()
    out = ws_cfg.set_routing(
        db,
        ws,
        default_provider="openai",
        default_model="gpt-4o-mini",
        fallback_chain=["openai", "ollama"],
    )
    assert out["routing"]["default_provider"] == "openai"
    assert out["routing"]["default_model"] == "gpt-4o-mini"
    assert out["routing"]["source"] == "workspace"

    ws_cfg.set_cloud_credential(db, ws, "openai", api_key="sk-workspace")
    assert ws_cfg.get_decrypted_api_key(ws, "openai") == "sk-workspace"
    public = ws_cfg.get_cloud_credentials_public(ws)
    openai = next(c for c in public if c["key"] == "openai")
    assert openai["api_key_set"] is True


def test_serving_node_upsert_and_merge_with_env(monkeypatch):
    db = _FakeDB()
    ws = _workspace()
    ws_cfg.upsert_serving_node(
        db,
        ws,
        name="lab",
        base_url="http://127.0.0.1:9000/",
        token="portal-tok",
    )
    public = ws_cfg.list_serving_nodes_public(ws)
    assert public == [
        {"name": "lab", "base_url": "http://127.0.0.1:9000", "token_set": True}
    ]

    monkeypatch.setattr(
        serving_nodes_mod.settings,
        "llm_serving_nodes_json",
        '[{"name":"env-only","base_url":"http://10.0.0.1:9000","token":"e"}]',
        raising=False,
    )
    nodes = serving_nodes_mod.parse_serving_nodes(workspace=ws)
    by_name = {n.name: n for n in nodes}
    assert "env-only" in by_name
    assert by_name["lab"].token == "portal-tok"
    assert by_name["lab"].base_url == "http://127.0.0.1:9000"

    ws_cfg.delete_serving_node(db, ws, "lab")
    assert ws_cfg.list_serving_nodes_public(ws) == []


def test_set_routing_requires_fields():
    db = _FakeDB()
    ws = _workspace()
    with pytest.raises(ValueError):
        ws_cfg.set_routing(db, ws, default_provider="", default_model="x")
