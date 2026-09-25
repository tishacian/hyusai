"""Public workspace settings, secret-keeping writes and the unencrypted-storage warning."""

from __future__ import annotations

import copy
import json
import logging
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import flow_workbench
from app.services.connectors.generic import service as generic_service
from app.services.connectors.hana import service as hana_service
from app.services.connectors.mcp import service as mcp_service
from app.services.connectors.rpa import service as rpa_service
from app.services.model_plane import workspace_config
from app.services.run_engine import dag
from app.services.run_engine.variable_pool import VariablePool
from app.services.workspace_secrets import (
    public_checkpoint,
    public_workspace_settings,
    warn_unencrypted_connector_secrets,
    with_stored_secrets,
)

SETTINGS = {
    "family": "generic",
    "connectors": {
        "sap_hana": {"host": "hana.example.test", "password_encrypted": "HANA-ENVELOPE"},
        "mcp": {
            "servers": [
                {"id": "erp", "url": "https://erp.example.test", "token_encrypted": "ERP-ENVELOPE"}
            ]
        },
    },
    "client360_pdr_mail": {"smtp": {"host": "smtp.example.test", "password": "SMTP-PLAIN"}},
    generic_service.SETTINGS_KEY: {
        "s3": {"values": {"bucket": "reports"}, "secrets": {"secret_access_key": "S3-ENVELOPE"}}
    },
}
PUBLIC = {
    "family": "generic",
    "connectors": {
        "sap_hana": {"host": "hana.example.test"},
        "mcp": {"servers": [{"id": "erp", "url": "https://erp.example.test"}]},
    },
    "client360_pdr_mail": {"smtp": {"host": "smtp.example.test"}},
}
FERNET_KEYS = (
    "HANA_CONNECTOR_FERNET_KEY",
    "RPA_CONNECTOR_FERNET_KEY",
    "MCP_CONNECTOR_FERNET_KEY",
    "LLM_PORTAL_FERNET_KEY",
    "CONNECTOR_SECRETS_FERNET_KEY",
)


def _legacy_checkpoint() -> dict:
    return {
        "kind": "hitl_pause",
        "state": {
            "pool": {"workspace": {"id": "ws", "settings": copy.deepcopy(SETTINGS)}},
            "node_outputs": {"answer": "kept"},
        },
    }


def test_public_settings_drop_every_secret_and_leave_the_stored_ones_alone():
    stored = copy.deepcopy(SETTINGS)
    assert public_workspace_settings(stored) == PUBLIC
    assert stored == SETTINGS
    assert public_workspace_settings(None) == {}


def test_a_write_keeps_secrets_only_where_it_keeps_their_object():
    stored = {
        "connectors": {
            "sap_hana": {"host": "old.example.test", "password_encrypted": "P"},
            "rpa_bridge": {"base_url": "https://rpa.example.test", "auth_token_encrypted": "T"},
        }
    }
    requested = {"connectors": {"sap_hana": {"host": "new.example.test"}}, "demo_safe": True}

    assert with_stored_secrets(stored, requested) == {
        "connectors": {"sap_hana": {"host": "new.example.test", "password_encrypted": "P"}},
        "demo_safe": True,
    }


def test_the_run_pool_holds_only_public_workspace_settings():
    pool = VariablePool()
    run = SimpleNamespace(input_ref={}, id="run", workspace_id="ws")
    system = SimpleNamespace(
        settings={},
        id="sys",
        default_model=None,
        default_prompt_type=None,
        retrieval_mode_default=None,
        workspace_id="ws",
        context_id=None,
    )
    workspace = SimpleNamespace(
        settings=copy.deepcopy(SETTINGS), slug="ws", name="Workspace", mode="executive"
    )

    dag._seed_pool(None, pool, run, system, workspace=workspace)

    assert pool.to_dict()["workspace"]["settings"] == PUBLIC


def test_a_legacy_checkpoint_leaves_the_api_with_public_settings_only():
    checkpoint = _legacy_checkpoint()
    public = public_checkpoint(checkpoint)
    assert public["state"]["pool"]["workspace"]["settings"] == PUBLIC
    assert public["state"]["node_outputs"] == {"answer": "kept"}
    assert checkpoint == _legacy_checkpoint()
    assert public_checkpoint({"kind": "run_start"}) == {"kind": "run_start"}

    run = SimpleNamespace(
        id="run",
        system_id="sys",
        status="completed",
        execution_surface="flow_workbench",
        execution_contract={},
        flow_sha256="0" * 64,
        input_ref={},
        output_ref={},
        error=None,
        checkpoints=[_legacy_checkpoint()],
    )
    assert "_encrypted" not in json.dumps(flow_workbench._run_payload(run))


def test_startup_names_each_connector_that_stores_secrets_in_clear(monkeypatch, caplog):
    for name in FERNET_KEYS:
        monkeypatch.delenv(name, raising=False)
    with caplog.at_level(logging.WARNING, logger="app.services.workspace_secrets"):
        assert warn_unencrypted_connector_secrets() == [
            "SAP HANA",
            "RPA Bridge",
            "MCP",
            "model portal",
            "catalog connectors",
        ]
    assert "RPA_CONNECTOR_FERNET_KEY" in caplog.text
    assert "WITHOUT encryption" in caplog.text

    caplog.clear()
    value = "configured-key-value-never-logged"
    monkeypatch.setenv("HANA_CONNECTOR_FERNET_KEY", value)
    with caplog.at_level(logging.WARNING, logger="app.services.workspace_secrets"):
        assert warn_unencrypted_connector_secrets() == []
    assert caplog.records == []
    assert value not in caplog.text


@pytest.mark.parametrize(
    "configured",
    [(), *((name,) for name in FERNET_KEYS)],
)
def test_the_warning_names_exactly_the_connectors_that_would_store_in_clear(
    monkeypatch, configured
):
    for name in FERNET_KEYS:
        monkeypatch.delenv(name, raising=False)
    if configured:
        fernet = pytest.importorskip("cryptography.fernet")
        for name in configured:
            monkeypatch.setenv(name, fernet.Fernet.generate_key().decode())
    encryptors = {
        "SAP HANA": hana_service._encrypt_secret,
        "RPA Bridge": rpa_service._encrypt_secret,
        "MCP": mcp_service._encrypt_secret,
        "model portal": workspace_config.encrypt_secret,
        "catalog connectors": generic_service._encrypt_secret,
    }

    stored_in_clear = [
        connector
        for connector, encrypt in encryptors.items()
        if "plaintext" in json.loads(encrypt("a-secret"))
    ]

    assert warn_unencrypted_connector_secrets() == stored_in_clear
