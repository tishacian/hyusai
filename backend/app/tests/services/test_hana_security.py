"""Exercise HANA credential, TLS, destination and SQL boundaries without a server."""

from __future__ import annotations

import socket
import sys
from types import SimpleNamespace

import pytest

from app.services.connectors.hana import network_policy as network
from app.services.connectors.hana import service

CONFIG = {"host": "hana.example.test", "user": "WORKSPACE_USER", "password": "workspace-password"}


@pytest.fixture(autouse=True)
def policy(monkeypatch):
    for key, value in {
        "hana_network_policy_mode": "enforce",
        "hana_allowed_hosts": "hana.example.test",
        "hana_allowed_cidrs": "",
        "hana_allow_insecure_tls": False,
        "hana_insecure_tls_allowed_hosts": "",
        "hana_writes_enabled": False,
    }.items():
        monkeypatch.setattr(service.settings, key, value)


def _dns(monkeypatch, *addresses):
    monkeypatch.setattr(
        network.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (address, 443),
            )
            for address in addresses
        ],
    )


def test_global_password_is_never_available_to_workspace(monkeypatch):
    monkeypatch.setenv("HANA_CONNECTOR_PASSWORD", "platform-password")
    workspace = SimpleNamespace(
        settings={"connectors": {"sap_hana": {"host": "attacker.example.test", "user": "ATTACKER"}}}
    )
    config = service.get_config(workspace, include_secrets=True)
    assert config["password"] == ""
    assert config["password_set"] is False
    assert config["configured"] is False
    with pytest.raises(network.HanaConnectorError, match="HANA_NOT_CONFIGURED"):
        service._connect(config)


def test_verified_tls_and_dns_ip_pinning(monkeypatch):
    _dns(monkeypatch, "93.184.216.34")
    calls = []
    connection = object()

    def connect(**kwargs):
        calls.append(kwargs)
        return connection

    monkeypatch.setitem(
        sys.modules, "hdbcli", SimpleNamespace(dbapi=SimpleNamespace(connect=connect))
    )
    assert service._connect(CONFIG) is connection
    assert calls[0]["address"] == "93.184.216.34"
    assert calls[0]["sslHostNameInCertificate"] == "hana.example.test"
    assert calls[0]["sslValidateCertificate"] is True
    assert calls[0]["encrypt"] is True
    assert calls[0]["distributionMode"] == "off"


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "10.42.0.4"]
)
def test_private_or_metadata_dns_answers_blocked_without_approval(monkeypatch, ip):
    _dns(monkeypatch, ip)
    with pytest.raises(network.HanaConnectorError, match="HANA_DESTINATION_DENIED"):
        service._connect(CONFIG)


def test_mixed_dns_response_is_checked_in_full(monkeypatch):
    _dns(monkeypatch, "93.184.216.34", "169.254.169.254")
    with pytest.raises(network.HanaConnectorError, match="HANA_DESTINATION_DENIED"):
        network.resolve_destination("hana.example.test", 443)


def test_explicit_internal_network_continues_to_work(monkeypatch):
    _dns(monkeypatch, "10.42.0.4")
    monkeypatch.setattr(service.settings, "hana_allowed_cidrs", "10.42.0.0/24")
    assert network.resolve_destination("hana.example.test", 443).address == "10.42.0.4"


def test_report_mode_warns_without_blocking_or_printing_host(monkeypatch, caplog):
    _dns(monkeypatch, "10.42.0.4")
    monkeypatch.setattr(service.settings, "hana_network_policy_mode", "report")
    assert network.resolve_destination("hana.example.test", 443).address == "10.42.0.4"
    assert "mode=report reason=private_address" in caplog.text
    assert "hana.example.test" not in caplog.text
    assert CONFIG["password"] not in caplog.text


def test_public_attacker_host_also_needs_allowlist(monkeypatch):
    _dns(monkeypatch, "93.184.216.34")
    with pytest.raises(network.HanaConnectorError, match="HANA_DESTINATION_DENIED"):
        network.resolve_destination("attacker.example.test", 443)


@pytest.mark.parametrize(
    "host",
    [
        "https://hana.example.test",
        "user@hana.example.test",
        "hana.example.test:443",
        "127.1",
        "hana.example.test/path",
    ],
)
def test_non_host_values_cannot_be_driver_destinations(monkeypatch, host):
    if host == "127.1":
        _dns(monkeypatch, "127.0.0.1")
        with pytest.raises(network.HanaConnectorError, match="HANA_DESTINATION_DENIED"):
            network.resolve_destination(host, 443)
    else:
        with pytest.raises(network.HanaConnectorError, match="HANA_HOST_INVALID"):
            network.resolve_destination(host, 443)


@pytest.mark.parametrize("config", [{"encrypt": False}, {"ssl_validate_certificate": False}])
def test_unsafe_tls_requires_both_flag_and_exact_host(monkeypatch, config):
    for enabled, allowed in [(False, "hana.example.test"), (True, "other.example.test")]:
        monkeypatch.setattr(service.settings, "hana_allow_insecure_tls", enabled)
        monkeypatch.setattr(service.settings, "hana_insecure_tls_allowed_hosts", allowed)
        with pytest.raises(network.HanaConnectorError, match="HANA_TLS_REQUIRED"):
            service._connect({**CONFIG, **config})
    monkeypatch.setattr(service.settings, "hana_insecure_tls_allowed_hosts", "hana.example.test")
    network.assert_tls_policy(
        "hana.example.test",
        encrypt=config.get("encrypt", True),
        verify=config.get("ssl_validate_certificate", True),
    )


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM T",
        "WITH C AS (DELETE FROM T) SELECT * FROM C",
        "WITH C AS (SELECT 1 FROM DUMMY) UPDATE T SET X = 1",
        "SELECT 1 INTO T FROM DUMMY",
        "SELECT 1 FROM DUMMY; DELETE FROM T",
        "/* harmless */ CALL P()",
    ],
)
def test_readonly_cannot_be_bypassed_with_cte_comments_or_stacked_sql(sql):
    with pytest.raises(ValueError):
        service._assert_read_only(sql, allow_writes=False)


def test_readonly_accepts_cte_and_quoted_keyword():
    service._assert_read_only(
        "-- comment\nWITH C AS (SELECT 'DELETE; INTO' AS X FROM DUMMY) SELECT X FROM C;",
        allow_writes=False,
    )
    service._assert_read_only("SELECT REPLACE('a', 'a', 'b') FROM DUMMY", allow_writes=False)


def test_service_write_flag_checked_before_any_connection(monkeypatch):
    with pytest.raises(network.HanaConnectorError, match="HANA_WRITES_DISABLED"):
        service.run_query(CONFIG, "DELETE FROM T", allow_writes=True)


def test_driver_password_never_survives_error_or_logging(monkeypatch, caplog):
    _dns(monkeypatch, "93.184.216.34")

    def fail(**kwargs):
        raise RuntimeError(f"driver failed with {CONFIG['password']}")

    monkeypatch.setitem(sys.modules, "hdbcli", SimpleNamespace(dbapi=SimpleNamespace(connect=fail)))
    with pytest.raises(network.HanaConnectorError, match="HANA_CONNECTION_FAILED") as raised:
        service.run_query(CONFIG, "SELECT 1 FROM DUMMY")
    assert CONFIG["password"] not in str(raised.value)
    assert CONFIG["password"] not in caplog.text


def test_demo_fallback_is_explicit_and_policy_errors_never_become_demo(monkeypatch):
    def unavailable(*args):
        raise RuntimeError("offline")

    monkeypatch.setattr(service, "_connect", unavailable)
    with pytest.raises(network.HanaConnectorError, match="HANA_CONNECTION_FAILED"):
        service.run_query(CONFIG, "SELECT 1 FROM DUMMY")
    with pytest.raises(network.HanaConnectorError, match="HANA_CONNECTION_FAILED"):
        service.preview_catalog(CONFIG)
    assert service.preview_catalog({**CONFIG, "demo_mode": True})["source"] == "demo_dataset"

    def denied(*args):
        raise network.HanaConnectorError("HANA_DESTINATION_DENIED", 403)

    monkeypatch.setattr(service, "_connect", denied)
    with pytest.raises(network.HanaConnectorError, match="HANA_DESTINATION_DENIED"):
        service.run_query({**CONFIG, "demo_mode": True}, "SELECT 1 FROM DUMMY")
    with pytest.raises(network.HanaConnectorError, match="HANA_DESTINATION_DENIED"):
        service.preview_catalog({**CONFIG, "demo_mode": True})


def test_readonly_transaction_precedes_user_sql(monkeypatch):
    statements = []
    cursor = SimpleNamespace(
        execute=lambda sql: statements.append(sql),
        description=[("X",)],
        fetchmany=lambda limit: [[1]],
        close=lambda: None,
    )
    connection = SimpleNamespace(
        cursor=lambda: cursor,
        setautocommit=lambda flag: statements.append(("autocommit", flag)),
        close=lambda: None,
    )
    monkeypatch.setattr(service, "_connect", lambda config: connection)
    assert service.run_query(CONFIG, "SELECT 1 FROM DUMMY")["rows"] == [[1]]
    assert statements == [("autocommit", False), "SET TRANSACTION READ ONLY", "SELECT 1 FROM DUMMY"]
