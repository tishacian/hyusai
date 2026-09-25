"""Migration 115 seals leftover RPA tokens and Client360 SMTP passwords."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet

from app.services.client360_pdr import (
    _decrypt_smtp_password,
    reencrypt_workspace_smtp_password,
)
from app.services.connectors.rpa import service as rpa_service


def _load(name: str, filename: str):
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / filename
    saved = sys.modules.get("alembic")
    stub = types.ModuleType("alembic")
    stub.op = types.SimpleNamespace(get_bind=lambda: None)
    sys.modules["alembic"] = stub
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            sys.modules.pop("alembic", None)
    return mod


MIG = _load("migration_115", "115_rpa_smtp_reencrypt.py")
TOKEN = "rpa-token-never-echoed"
SMTP_PASSWORD = "smtp-password-never-echoed"


def _schema(bind):
    metadata = sa.MetaData()
    workspaces = sa.Table(
        "workspaces",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("settings", sa.JSON()),
    )
    metadata.create_all(bind)
    return workspaces


@pytest.fixture()
def bind(monkeypatch):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        monkeypatch.setattr(MIG, "op", types.SimpleNamespace(get_bind=lambda: connection))
        yield connection


def _settings(bind, workspaces, workspace_id="workspace-demo"):
    return bind.execute(
        sa.select(workspaces.c.settings).where(workspaces.c.id == workspace_id)
    ).scalar_one()


def _seed(bind, workspaces, settings, *, workspace_id="workspace-demo"):
    bind.execute(
        workspaces.insert(),
        {"id": workspace_id, "settings": settings},
    )


def test_upgrade_seals_plaintext_rpa_and_smtp_with_the_hana_key(bind, monkeypatch):
    import base64

    key = Fernet.generate_key().decode()
    monkeypatch.delenv(rpa_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(rpa_service.ENV_MASTER_KEY_FALLBACK, raising=False)
    monkeypatch.delenv("CLIENT360_SMTP_FERNET_KEY", raising=False)
    monkeypatch.delenv("HANA_CONNECTOR_FERNET_KEY", raising=False)
    workspaces = _schema(bind)
    open_token = json.dumps({"v": 1, "plaintext": base64.b64encode(TOKEN.encode()).decode()})
    _seed(
        bind,
        workspaces,
        {
            "connectors": {
                "rpa_bridge": {
                    "base_url": "https://rpa.example.test",
                    "auth_token_encrypted": open_token,
                }
            },
            "client360_pdr_mail": {
                "smtp": {"host": "smtp.example.test", "password": SMTP_PASSWORD}
            },
            "demo_safe": True,
        },
    )
    monkeypatch.setenv(rpa_service.ENV_MASTER_KEY_FALLBACK, key)
    monkeypatch.setenv("HANA_CONNECTOR_FERNET_KEY", key)

    MIG.upgrade()

    settings = _settings(bind, workspaces)
    rpa_blob = settings["connectors"]["rpa_bridge"]["auth_token_encrypted"]
    smtp = settings["client360_pdr_mail"]["smtp"]
    assert "ciphertext" in json.loads(rpa_blob)
    assert "plaintext" not in json.loads(rpa_blob)
    assert "password" not in smtp
    assert "ciphertext" in json.loads(smtp["password_encrypted"])
    assert TOKEN not in json.dumps(settings)
    assert SMTP_PASSWORD not in json.dumps(settings)
    assert settings["demo_safe"] is True
    assert rpa_service._decrypt_secret(rpa_blob) == TOKEN
    assert _decrypt_smtp_password(smtp["password_encrypted"]) == SMTP_PASSWORD

    first = json.dumps(settings, sort_keys=True)
    MIG.upgrade()
    assert json.dumps(_settings(bind, workspaces), sort_keys=True) == first


def test_upgrade_leaves_workspaces_without_secrets_alone(bind, monkeypatch):
    monkeypatch.setenv("HANA_CONNECTOR_FERNET_KEY", Fernet.generate_key().decode())
    workspaces = _schema(bind)
    untouched = {"features": {"rpa_bridge": True}, "demo_safe": True}
    _seed(bind, workspaces, untouched, workspace_id="workspace-other")

    MIG.upgrade()

    assert _settings(bind, workspaces, "workspace-other") == untouched


def test_smtp_reencrypt_helper_is_idempotent_once_sealed(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.delenv("CLIENT360_SMTP_FERNET_KEY", raising=False)
    monkeypatch.setenv("HANA_CONNECTOR_FERNET_KEY", key)
    settings = {"client360_pdr_mail": {"smtp": {"host": "smtp.example.test", "password": SMTP_PASSWORD}}}
    sealed, changed = reencrypt_workspace_smtp_password(settings)
    assert changed is True
    again, changed_again = reencrypt_workspace_smtp_password(sealed)
    assert changed_again is False
    assert again["client360_pdr_mail"]["smtp"]["password_encrypted"] == sealed["client360_pdr_mail"]["smtp"]["password_encrypted"]
