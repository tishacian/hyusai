"""Legacy calls derive network authority from a live workspace, never JSON ids."""

import json
import socket
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.connector_governance import ConnectorNetworkException
from app.services.compute_runs import utcnow
from app.services.connectors import legacy_network as legacy
from app.services.connectors.network_policy import ConnectorNetworkError, resolve_destination
from app.tests.services.test_connection_registry import setup as registry_setup

setup = registry_setup


@pytest.fixture()
def grant(db_session, setup, monkeypatch):
    monkeypatch.setattr(settings, "connector_network_policy_mode", "enforce")
    monkeypatch.setattr(settings, "hana_network_policy_mode", "enforce")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.22.33.7", port))
        ],
    )
    row = ConnectorNetworkException(
        workspace_id=setup[0].id,
        cidr="10.22.33.0/24",
        ports=[443, 5432],
        reason="Dedicated private database bench",
        created_by=setup[2][0].id,
        expires_at=utcnow() + timedelta(hours=1),
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_scope_isolated_and_public_mapping_cannot_retain_authority(db_session, setup, grant):
    bound = legacy.bind_config({"host": "private.example.test"}, setup[0])
    with legacy.network_scope(bound):
        assert resolve_destination(bound["host"], 5432).address == "10.22.33.7"
        with pytest.raises(ConnectorNetworkError):
            resolve_destination(bound["host"], 5433)
    for config in (
        legacy.bind_config(dict(bound), setup[1]),
        {**bound, "workspace_id": setup[0].id},
        json.loads(json.dumps(bound)),
    ):
        with legacy.network_scope(config), pytest.raises(ConnectorNetworkError):
            resolve_destination(config["host"], 5432)


@pytest.mark.parametrize("change", ["revoke", "expire", "disable_workspace"])
def test_cached_config_reloads_revocation_from_other_session(db_session, setup, grant, change):
    bound = legacy.bind_config({"host": "private.example.test"}, setup[0])
    with legacy.network_scope(bound):
        resolve_destination(bound["host"], 5432)
    with SessionLocal() as admin:
        if change == "disable_workspace":
            admin.get(type(setup[0]), setup[0].id).is_active = False
        else:
            other = admin.get(type(grant), grant.id)
            if change == "revoke":
                other.revoked_at = utcnow()
            else:
                other.expires_at = utcnow() - timedelta(seconds=1)
        admin.commit()
    with pytest.raises(ConnectorNetworkError), legacy.network_scope(bound):
        resolve_destination(bound["host"], 5432)


def test_detached_workspace_fails_closed(db_session, setup, grant):
    bound = legacy.bind_config({}, setup[0])
    db_session.expunge(setup[0])
    with pytest.raises(ConnectorNetworkError, match="CONTEXT_UNAVAILABLE"):
        with legacy.network_scope(bound):
            pytest.fail("Detached workspace cannot authorize egress")


def test_hana_and_pg_runtime_configs_bind_only_persistent_workspace(db_session, setup, grant):
    from app.services.connectors.generic.service import get_config as pg_config
    from app.services.connectors.hana.service import get_config as hana_config

    for get in (
        lambda secret: pg_config(setup[0], "postgresql", include_secrets=secret),
        lambda secret: hana_config(setup[0], include_secrets=secret),
    ):
        with legacy.network_scope(get(True)):
            resolve_destination("private.example.test", 5432)
        with legacy.network_scope(get(False)), pytest.raises(ConnectorNetworkError):
            resolve_destination("private.example.test", 5432)


def test_postgresql_browser_and_tester_resolve_inside_bound_scope(
    db_session, setup, grant, monkeypatch
):
    import psycopg2

    from app.services.connectors.generic import postgresql_browser as browser
    from app.services.connectors.generic import service

    config = legacy.bind_config(
        {
            "values": {"host": "private.example.test", "database": "bench", "username": "reader"},
            "secrets": {"password": "not-exported"},
        },
        setup[0],
    )
    captured = []
    connection = MagicMock()
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: captured.append(kw) or connection)
    monkeypatch.setattr(browser, "get_config", lambda *a, **kw: config)
    with browser._connection(setup[0]):
        pass
    assert captured[0]["hostaddr"] == "10.22.33.7"
    assert captured[0]["host"] == "private.example.test"
    assert captured[0]["sslmode"] == "verify-full"
    assert service.test_connection("postgresql", config)["status"] == "connected"


def test_mcp_binding_covers_both_rpc_and_token_resolution(db_session, setup, grant, monkeypatch):
    from app.services.connectors.mcp import client, service

    monkeypatch.setattr(
        service,
        "get_server",
        lambda *a: {
            "id": "private",
            "url": "https://private.example.test/mcp",
            "configured": True,
            "auth_mode": "bearer",
        },
    )
    monkeypatch.setattr(service, "get_decrypted_token", lambda *a: "test-token")
    server = service.resolve_server(setup[0], "private")
    checked = []

    def token(config, **kwargs):
        checked.append(resolve_destination("private.example.test", 443))
        raise RuntimeError("stop before network")

    monkeypatch.setattr(client, "access_token_for_server", token)
    with pytest.raises(Exception):
        client.jsonrpc(server=server, method="tools/list")
    assert checked and checked[0].address == "10.22.33.7"
    grant.revoked_at = utcnow()
    db_session.commit()
    checked.clear()
    with pytest.raises(Exception):
        client.jsonrpc(server=server, method="tools/list")
    assert checked == []
