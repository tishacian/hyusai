"""Legacy envelope -> registry reference: dual read, write path and migration script."""

from __future__ import annotations

import base64
import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

from app.models.huggingface import HFPlatformConfig
from app.models.secret import Secret, SecretVersion
from app.models.workspace import Workspace
from app.services.client360_pdr import _encrypt_smtp_password, _smtp_stored_password
from app.services.connectors.generic import service as generic
from app.services.connectors.hana import service as hana
from app.services.connectors.mcp import service as mcp
from app.services.connectors.rpa import service as rpa
from app.services.huggingface.connection import Connection
from app.services.model_plane import workspace_config
from app.services.secrets.backends.base import reset_backends
from app.services.secrets.compat import is_ref

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "agentium_secret_registry_migrate.py"
KEY = base64.urlsafe_b64encode(b"m" * 32).decode()

VALUES = {
    "smtp": "smtp-pass-0001",
    "hf": "hf_workspace_token_0001",
    "mcp_token": "mcp-token-0001",
    "mcp_oauth": "mcp-oauth-0001",
    "mcp_shared": "mcp-shared-0001",
    "rpa": "rpa-token-0001",
    "hana": "hana-pass-0001",
    "llm": "sk-llm-0001",
    "node": "node-token-0001",
    "c360": "c360-pass-0001",
    "hf_platform": "hf_platform_token_0001",
}


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    for name in (
        "SECRET_REGISTRY_FERNET_KEY",
        "CONNECTOR_SECRETS_FERNET_KEY",
        "HANA_CONNECTOR_FERNET_KEY",
        "MCP_CONNECTOR_FERNET_KEY",
        "RPA_CONNECTOR_FERNET_KEY",
        "LLM_PORTAL_FERNET_KEY",
        "CLIENT360_SMTP_FERNET_KEY",
    ):
        monkeypatch.setenv(name, KEY)
    reset_backends()
    yield
    reset_backends()


@pytest.fixture()
def script():
    spec = importlib.util.spec_from_file_location("agentium_secret_registry_migrate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def _legacy_settings() -> dict:
    return {
        "generic_connectors": {
            "smtp": {
                "values": {"host": "mail.example.test"},
                "secrets": {"password": generic._encrypt_secret(VALUES["smtp"])},
            },
            "huggingface": {
                "values": {"endpoint": "https://huggingface.co"},
                "secrets": {"token": generic._encrypt_secret(VALUES["hf"])},
            },
        },
        "connectors": {
            "mcp": {
                "servers": [
                    {
                        "id": "docs",
                        "url": "https://mcp.example.test",
                        "token_encrypted": mcp._encrypt_secret(VALUES["mcp_token"]),
                        "oauth_client_secret_encrypted": mcp._encrypt_secret(VALUES["mcp_oauth"]),
                    }
                ],
                "shared_auth": {
                    "oauth_client_secret_encrypted": mcp._encrypt_secret(VALUES["mcp_shared"])
                },
            },
            "rpa_bridge": {
                "base_url": "https://rpa.example.test",
                "auth_token_encrypted": rpa._encrypt_secret(VALUES["rpa"]),
            },
            "sap_hana": {
                "host": "hana.example.test",
                "user": "reader",
                "password_encrypted": hana._encrypt_secret(VALUES["hana"]),
            },
        },
        "llm_portal": {
            "cloud_credentials": {
                "openai": {"api_key_encrypted": workspace_config.encrypt_secret(VALUES["llm"])}
            },
            "serving_nodes": [
                {
                    "name": "gpu-1",
                    "base_url": "https://gpu.example.test",
                    "token_encrypted": workspace_config.encrypt_secret(VALUES["node"]),
                }
            ],
        },
        "client360_pdr_mail": {
            "smtp": {
                "host": "smtp.example.test",
                "password_encrypted": _encrypt_smtp_password(VALUES["c360"]),
            }
        },
    }


@pytest.fixture()
def seeded(db_session):
    ws = Workspace(id="mig-ws", slug="mig-ws", name="Migration", settings=_legacy_settings())
    db_session.add(ws)
    db_session.add(
        HFPlatformConfig(
            id="default",
            connection={
                "endpoint": "https://huggingface.co",
                "token_encrypted": generic._encrypt_secret(VALUES["hf_platform"]),
            },
            policy={},
        )
    )
    db_session.commit()
    return ws


def _read_all(db, ws) -> dict:
    """Every secret through its service's own read path."""
    return {
        "smtp": generic.get_config(ws, "smtp", include_secrets=True)["secrets"]["password"],
        "hf": Connection.resolve(db, ws).token,
        "mcp_token": mcp.get_decrypted_token(ws, "docs"),
        "mcp_oauth": mcp.get_decrypted_oauth_secret(ws, "docs"),
        "mcp_shared": mcp.get_decrypted_oauth_secret(ws),
        "rpa": rpa.get_config(ws, include_secrets=True)["auth_token"],
        "hana": hana.get_config(ws, include_secrets=True)["password"],
        "llm": workspace_config.get_decrypted_api_key(ws, "openai"),
        "node": workspace_config.list_serving_node_configs(ws)[0]["token"],
        "c360": _smtp_stored_password(ws.settings["client360_pdr_mail"]["smtp"], ws),
        "hf_platform": Connection.resolve(db, None).token,
    }


def _public_flags(ws) -> dict:
    return {
        "generic": generic.get_config(ws, "smtp")["secrets_set"],
        "hf": generic.get_config(ws, "huggingface")["secrets_set"],
        "mcp": [(s["token_set"], s["oauth_secret_set"]) for s in mcp.get_servers(ws)["servers"]],
        "mcp_shared": mcp.get_servers(ws)["shared_auth"]["secret_set"],
        "rpa": rpa.get_config(ws)["auth_token_set"],
        "hana": hana.get_config(ws)["password_set"],
        "llm": workspace_config.get_cloud_credentials_public(ws),
        "nodes": workspace_config.list_serving_nodes_public(ws),
    }


def test_dry_run_writes_nothing(db_session, seeded, script, tmp_path):
    before = json.dumps(seeded.settings, sort_keys=True)
    result = script.migrate(db_session, dry_run=True, backup_path=None)

    assert result["counts"] == {"would_migrate": 11}
    db_session.refresh(seeded)
    assert json.dumps(seeded.settings, sort_keys=True) == before
    assert db_session.query(Secret).count() == 0
    assert not list(tmp_path.iterdir())


def test_migration_is_idempotent_and_reads_stay_identical(db_session, seeded, script, tmp_path):
    assert _read_all(db_session, seeded) == VALUES
    flags = _public_flags(seeded)
    backup = tmp_path / "backup.json"

    result = script.migrate(db_session, dry_run=False, backup_path=backup)
    assert result["counts"] == {"migrated": 11}
    output = json.dumps(result)
    assert not any(value in output for value in VALUES.values())

    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    saved = json.loads(backup.read_text())
    assert saved["workspaces"]["mig-ws"]["connectors"]["rpa_bridge"]["auth_token_encrypted"]

    db_session.refresh(seeded)
    connectors = seeded.settings["connectors"]
    assert is_ref(connectors["rpa_bridge"]["auth_token_encrypted"])
    assert is_ref(connectors["mcp"]["servers"][0]["token_encrypted"])
    assert is_ref(seeded.settings["generic_connectors"]["huggingface"]["secrets"]["token"])
    assert connectors["sap_hana"]["password_encrypted"] == {
        "ref": "secret://workspace/sap-hana-password"
    }
    platform = db_session.get(HFPlatformConfig, "default")
    assert platform.connection["token_encrypted"] == {"ref": "secret://platform/huggingface-token"}

    assert _read_all(db_session, seeded) == VALUES
    assert _public_flags(seeded) == flags

    versions = db_session.query(SecretVersion).count()
    again = script.migrate(db_session, dry_run=False, backup_path=tmp_path / "again.json")
    assert again["counts"] == {"already_ref": 11}
    assert db_session.query(SecretVersion).count() == versions


def test_undecryptable_envelope_is_reported_not_migrated(db_session, seeded, script, monkeypatch):
    monkeypatch.setenv("RPA_CONNECTOR_FERNET_KEY", base64.urlsafe_b64encode(b"x" * 32).decode())
    result = script.migrate(db_session, dry_run=True, backup_path=None)
    errors = [row for row in result["fields"] if row["action"] == "error"]
    assert [row["field"] for row in errors] == ["connectors.rpa_bridge.auth_token_encrypted"]


def test_service_writes_store_a_reference_and_rotate(db_session):
    ws = Workspace(id="mig-ws-2", slug="mig-ws-2", name="Writes", settings={})
    db_session.add(ws)
    db_session.commit()

    rpa.set_config(db_session, ws, {"base_url": "https://rpa.example.test", "auth_token": "t-1"})
    hana.set_config(db_session, ws, {"host": "h", "user": "u", "password": "p-1"})
    generic.set_config(db_session, ws, "smtp", {"host": "m", "password": "s-1"}, actor="tester")
    mcp.upsert_server(
        db_session, ws, {"id": "docs", "url": "https://mcp.example.test", "token": "m-1"}
    )
    workspace_config.set_cloud_credential(db_session, ws, "openai", api_key="k-1")
    workspace_config.upsert_serving_node(
        db_session, ws, name="gpu-1", base_url="https://gpu.example.test", token="n-1"
    )

    connectors = ws.settings["connectors"]
    assert connectors["rpa_bridge"]["auth_token_encrypted"] == {
        "ref": "secret://workspace/rpa-bridge-auth-token"
    }
    assert is_ref(connectors["sap_hana"]["password_encrypted"])
    assert is_ref(ws.settings["generic_connectors"]["smtp"]["secrets"]["password"])
    assert is_ref(connectors["mcp"]["servers"][0]["token_encrypted"])
    assert is_ref(ws.settings["llm_portal"]["cloud_credentials"]["openai"]["api_key_encrypted"])
    assert rpa.get_config(ws)["auth_token_set"] is True

    rpa.set_config(db_session, ws, {"base_url": "https://rpa.example.test", "auth_token": "t-2"})
    assert rpa.get_config(ws, include_secrets=True)["auth_token"] == "t-2"
    assert hana.get_config(ws, include_secrets=True)["password"] == "p-1"
    assert mcp.get_decrypted_token(ws, "docs") == "m-1"
    assert workspace_config.get_decrypted_api_key(ws, "openai") == "k-1"
    assert workspace_config.list_serving_node_configs(ws)[0]["token"] == "n-1"
    secret = db_session.query(Secret).filter(Secret.name == "rpa-bridge-auth-token").one()
    assert secret.current_version == 2


def test_writes_fall_back_to_the_legacy_envelope_without_a_registry_key(db_session, monkeypatch):
    monkeypatch.delenv("SECRET_REGISTRY_FERNET_KEY")
    monkeypatch.delenv("CONNECTOR_SECRETS_FERNET_KEY")
    monkeypatch.setattr("app.core.config.settings.secret_registry_fernet_key", "")
    reset_backends()
    ws = Workspace(id="mig-ws-3", slug="mig-ws-3", name="Legacy", settings={})
    db_session.add(ws)
    db_session.commit()

    hana.set_config(db_session, ws, {"host": "h", "user": "u", "password": "p-legacy"})
    stored = ws.settings["connectors"]["sap_hana"]["password_encrypted"]
    assert isinstance(stored, str) and "ciphertext" in json.loads(stored)
    assert hana.get_config(ws, include_secrets=True)["password"] == "p-legacy"
    assert db_session.query(Secret).count() == 0
