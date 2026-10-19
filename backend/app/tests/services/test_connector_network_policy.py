"""Connector egress boundary: DNS, TLS identity, origin and closed failures."""

from __future__ import annotations

import socket
from datetime import UTC

import httpx
import pytest

from app.services.connectors import http_transport as transport
from app.services.connectors import network_policy as policy
from app.services.connectors.generic import postgresql_browser, postgresql_claims, service
from app.services.connectors.mcp import client as mcp
from app.services.connectors.mcp import oauth
from app.services.connectors.mcp.errors import McpUnreachable

PUBLIC = "93.184.216.34"
SECRET = "credential-must-not-escape"


@pytest.fixture(autouse=True)
def enforced(monkeypatch):
    monkeypatch.setattr(policy.settings, "connector_network_policy_mode", "enforce")
    oauth.clear_token_cache()
    yield
    oauth.clear_token_cache()


def dns(monkeypatch, *addresses):
    calls = []

    def resolve(host, port, *args, **kwargs):
        calls.append((host, port))
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (ip, port),
            )
            for ip in addresses
        ]

    monkeypatch.setattr(policy.socket, "getaddrinfo", resolve)
    return calls


@pytest.mark.parametrize(
    "bad", ["127.0.0.1", "::1", "169.254.169.254", "10.0.0.1", "::ffff:127.0.0.1"]
)
def test_entire_dns_answer_must_pass(monkeypatch, bad):
    dns(monkeypatch, PUBLIC, bad)
    with pytest.raises(policy.ConnectorNetworkError, match="CONNECTOR_DESTINATION_DENIED"):
        policy.resolve_destination("db.example.test", 5432)


def test_report_retains_pinning_but_does_not_claim_enforcement(monkeypatch, caplog):
    monkeypatch.setattr(policy.settings, "connector_network_policy_mode", "report")
    dns(monkeypatch, "10.0.0.1")
    found = policy.resolve_destination("private.example.test", 5432)
    assert found.address == "10.0.0.1"
    assert "mode=report reason=private_address" in caplog.text
    assert "private.example.test" not in caplog.text


@pytest.mark.parametrize(
    "host", ["/var/run/postgresql", "host1,host2", "user@host", "fe80::1%eth0"]
)
def test_driver_host_syntax_cannot_escape_policy(host):
    with pytest.raises(policy.ConnectorNetworkError, match="CONNECTOR_HOST_INVALID"):
        policy.resolve_destination(host, 5432)


def test_postgresql_pins_ip_and_verifies_original_hostname(monkeypatch):
    calls = dns(monkeypatch, PUBLIC)
    assert policy.postgresql_connection_options("DB.EXAMPLE.TEST.", 5432) == {
        "host": "db.example.test",
        "hostaddr": PUBLIC,
        "port": 5432,
        "sslmode": "verify-full",
    }
    assert calls == [("db.example.test", 5432)]


@pytest.mark.parametrize("consumer", ["test", "browser", "claims"])
@pytest.mark.parametrize("sslmode", ["verify-full", "disable"])
def test_every_postgresql_entrypoint_refuses_before_driver(monkeypatch, consumer, sslmode):
    import psycopg2

    dns(monkeypatch, PUBLIC, "169.254.169.254")
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: pytest.fail("driver must not run"))
    config = {
        "values": {
            "host": "db.example.test",
            "database": "db",
            "username": "reader",
            "sslmode": sslmode,
        },
        "secrets": {"password": SECRET},
    }
    if consumer == "test":
        assert service._test_postgresql(config["values"], config["secrets"]) == (
            "error",
            "CONNECTOR_DESTINATION_DENIED",
        )
    elif consumer == "browser":
        monkeypatch.setattr(postgresql_browser, "get_config", lambda *a, **k: config)
        with pytest.raises(
            postgresql_browser.PostgresBrowseError, match="CONNECTOR_DESTINATION_DENIED"
        ):
            with postgresql_browser._connection(None):
                pytest.fail("must not yield")
    else:
        monkeypatch.setattr(postgresql_claims, "get_config", lambda *a, **k: config)
        with pytest.raises(postgresql_claims.ClaimReadError, match="CONNECTOR_DESTINATION_DENIED"):
            postgresql_claims._read(None, (), {})


@pytest.mark.parametrize("consumer", ["test", "browser", "claims"])
@pytest.mark.parametrize("sslmode", [None, "verify-full", "disable"])
def test_every_postgresql_entrypoint_pins_and_honours_explicit_transport(
    monkeypatch, consumer, sslmode
):
    import psycopg2

    dns(monkeypatch, PUBLIC)
    captured = []

    def driver(**kwargs):
        captured.append(kwargs)
        raise psycopg2.OperationalError("server unreachable " + SECRET)

    monkeypatch.setattr(psycopg2, "connect", driver)
    config = {
        "values": {"host": "db.example.test", "database": "db", "username": "reader"},
        "secrets": {"password": SECRET},
    }
    if sslmode is not None:
        config["values"]["sslmode"] = sslmode
    if consumer == "test":
        assert service._test_postgresql(config["values"], config["secrets"]) == (
            "unreachable",
            "PG_UNAVAILABLE",
        )
    elif consumer == "browser":
        monkeypatch.setattr(postgresql_browser, "get_config", lambda *a, **k: config)
        with pytest.raises(postgresql_browser.PostgresBrowseError, match="PG_UNAVAILABLE"):
            with postgresql_browser._connection(None):
                pytest.fail("driver failed")
    else:
        monkeypatch.setattr(postgresql_claims, "get_config", lambda *a, **k: config)
        with pytest.raises(postgresql_claims.ClaimReadError, match="POSTGRESQL_READ_UNAVAILABLE"):
            postgresql_claims._read(None, (), {})
    assert captured[0]["host"] == "db.example.test"
    assert captured[0]["hostaddr"] == PUBLIC
    assert captured[0]["sslmode"] == (sslmode or "verify-full")
    assert len(captured) == 1


@pytest.mark.parametrize(
    "invalid", ["prefer", "require", "allow", "verify-ca", "", None, False, 0, {}, " disable"]
)
def test_invalid_postgresql_transport_is_refused_before_dns(monkeypatch, invalid):
    monkeypatch.setattr(
        policy.socket, "getaddrinfo", lambda *a, **k: pytest.fail("no DNS for invalid transport")
    )
    with pytest.raises(policy.ConnectorNetworkError, match="^PG_SSLMODE_INVALID$"):
        policy.postgresql_connection_options("db.example.test", 5432, sslmode=invalid)


@pytest.mark.parametrize("consumer", ["test", "browser", "claims"])
def test_postgresql_tls_failure_does_not_retry_without_tls(monkeypatch, consumer):
    import psycopg2

    dns(monkeypatch, PUBLIC)
    attempted = []

    def refuse(**options):
        attempted.append(options["sslmode"])
        raise psycopg2.OperationalError(
            "server does not support SSL, but SSL was required " + SECRET
        )

    monkeypatch.setattr(psycopg2, "connect", refuse)
    config = {
        "values": {"host": "db.example.test", "database": "db", "username": "reader"},
        "secrets": {"password": SECRET},
    }
    if consumer == "test":
        assert service._test_postgresql(config["values"], config["secrets"]) == (
            "error",
            "PG_TLS_UNAVAILABLE",
        )
    elif consumer == "browser":
        monkeypatch.setattr(postgresql_browser, "get_config", lambda *a, **k: config)
        with pytest.raises(postgresql_browser.PostgresBrowseError, match="^PG_TLS_UNAVAILABLE$"):
            with postgresql_browser._connection(None):
                pytest.fail("TLS must not fall back")
    else:
        monkeypatch.setattr(postgresql_claims, "get_config", lambda *a, **k: config)
        with pytest.raises(postgresql_claims.ClaimReadError, match="^PG_TLS_UNAVAILABLE$"):
            postgresql_claims._read(None, (), {})
    assert attempted == ["verify-full"]


def test_http_pinning_preserves_host_and_sni_without_second_dns(monkeypatch):
    calls = dns(monkeypatch, PUBLIC)
    url, destination = transport.destination_for_url("https://mcp.example.test:8443/rpc")
    pinned = transport.PinnedHTTPTransport(url, destination)
    captured = []
    pinned._inner.close()
    pinned._inner = httpx.MockTransport(
        lambda request: (captured.append(request), httpx.Response(200))[1]
    )
    # A rebinding answer must never be consulted once the address is checked.
    monkeypatch.setattr(policy.socket, "getaddrinfo", lambda *a, **k: pytest.fail("second DNS"))
    with httpx.Client(transport=pinned) as client:
        client.post(str(url), headers={"Authorization": "Bearer " + SECRET})
    assert calls == [("mcp.example.test", 8443)]
    assert captured[0].url.host == PUBLIC
    assert captured[0].headers["Host"] == "mcp.example.test:8443"
    assert captured[0].extensions["sni_hostname"] == "mcp.example.test"


def test_origin_change_refused_before_secret_can_leave(monkeypatch):
    dns(monkeypatch, PUBLIC)
    url, destination = transport.destination_for_url("https://mcp.example.test/rpc")
    with transport.PinnedHTTPTransport(url, destination) as pinned:
        for target in [
            "http://mcp.example.test/rpc",
            "https://other.example.test/rpc",
            "https://mcp.example.test:8443/rpc",
        ]:
            with pytest.raises(policy.ConnectorNetworkError, match="CONNECTOR_ORIGIN_DENIED"):
                pinned.handle_request(
                    httpx.Request("POST", target, headers={"Authorization": SECRET})
                )


@pytest.mark.parametrize(
    "url", ["http://auth.example.test/token", "https://user:pass@auth.example.test/token"]
)
def test_oauth_never_sends_secret_to_plaintext_or_userinfo_url(monkeypatch, url):
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("no HTTP client"))
    with pytest.raises(McpUnreachable, match="CONNECTOR_(TLS_REQUIRED|URL_INVALID)"):
        oauth.fetch_access_token(token_url=url, client_id="app", client_secret=SECRET)


def test_oauth_endpoint_checked_separately(monkeypatch):
    dns(monkeypatch, "169.254.169.254")
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("no HTTP client"))
    with pytest.raises(McpUnreachable, match="CONNECTOR_DESTINATION_DENIED"):
        oauth.fetch_access_token(
            token_url="https://auth.example.test/token", client_id="app", client_secret=SECRET
        )


@pytest.mark.parametrize("consumer", ["mcp", "oauth"])
def test_redirect_does_not_forward_credentials(monkeypatch, consumer):
    dns(monkeypatch, PUBLIC)
    requests = []
    real_client = httpx.Client

    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://attacker.example.test/collect"})

    def client_factory(*args, **kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        kwargs["transport"].close()
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)
    with pytest.raises(McpUnreachable, match="CONNECTOR_REDIRECT_DENIED"):
        if consumer == "mcp":
            mcp.jsonrpc({"url": "https://mcp.example.test/rpc", "token": SECRET}, "initialize")
        else:
            oauth.fetch_access_token(
                token_url="https://auth.example.test/token", client_id="app", client_secret=SECRET
            )
    assert len(requests) == 1
    assert requests[0].url.host != "attacker.example.test"


@pytest.mark.parametrize("consumer", ["mcp", "oauth"])
def test_transport_errors_are_closed(monkeypatch, caplog, consumer):
    dns(monkeypatch, PUBLIC)

    class BrokenClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            raise httpx.ConnectError("TLS failure with " + SECRET)

    monkeypatch.setattr(httpx, "Client", lambda **kw: BrokenClient())
    with pytest.raises(McpUnreachable) as error:
        if consumer == "mcp":
            mcp.jsonrpc({"url": "https://mcp.example.test/rpc", "token": SECRET}, "initialize")
        else:
            oauth.fetch_access_token(
                token_url="https://auth.example.test/token", client_id="app", client_secret=SECRET
            )
    assert SECRET not in str(error.value) and SECRET not in caplog.text


def test_oauth_cache_isolated_by_scope_credential_and_endpoint(monkeypatch):
    dns(monkeypatch, PUBLIC)
    issued = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def post(self, url, **kwargs):
            issued.append((url, kwargs["auth"], kwargs["data"]))
            return httpx.Response(
                200, json={"access_token": f"token-{len(issued)}", "expires_in": 3600}
            )

    monkeypatch.setattr(httpx, "Client", lambda **kw: Client())
    args = {
        "token_url": "https://auth.example.test/token",
        "client_id": "app",
        "client_secret": SECRET,
    }
    assert oauth.fetch_access_token(**args) == "token-1"
    assert oauth.fetch_access_token(**args) == "token-1"
    assert oauth.fetch_access_token(**{**args, "scope": "other"}) == "token-2"
    assert oauth.fetch_access_token(**{**args, "client_secret": "rotated"}) == "token-3"
    assert (
        oauth.fetch_access_token(**{**args, "token_url": "https://other.example.test/token"})
        == "token-4"
    )
    assert SECRET not in str(oauth._CACHE)


@pytest.mark.parametrize("trusted", [True, False])
def test_real_local_tls_checks_certificate_for_original_sni(monkeypatch, tmp_path, trusted):
    """A real TLS handshake, with only the TCP destination mapped to the fixture."""
    import ssl
    import threading
    from datetime import datetime, timedelta
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import httpcore
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    hostname = "mcp.example.test"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    requests, server_names, tcp_hosts = [], [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(dict(self.headers))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    context.set_servername_callback(lambda sock, name, ctx: server_names.append(name))
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_dns = socket.getaddrinfo
    original_tcp = httpcore.SyncBackend.connect_tcp

    def resolve(host, port, *args, **kwargs):
        if host == hostname:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC, port))]
        return original_dns(host, port, *args, **kwargs)

    def connect(self, host, port, **kwargs):
        tcp_hosts.append(host)
        assert host == PUBLIC
        return original_tcp(self, "127.0.0.1", port, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    try:
        url, destination = transport.destination_for_url(
            f"https://{hostname}:{server.server_port}/rpc"
        )
        pinned = transport.PinnedHTTPTransport(url, destination)
        pinned._inner.close()
        client_context = ssl.create_default_context(cafile=str(cert_path) if trusted else None)
        pinned._inner = httpx.HTTPTransport(verify=client_context, trust_env=False)
        with httpx.Client(transport=pinned, trust_env=False, timeout=2) as client:
            if trusted:
                assert (
                    client.post(str(url), headers={"Authorization": "Bearer " + SECRET}).status_code
                    == 200
                )
                assert requests[0]["Host"] == f"{hostname}:{server.server_port}"
            else:
                with pytest.raises(httpx.ConnectError):
                    client.post(str(url), headers={"Authorization": "Bearer " + SECRET})
                assert requests == []
        assert server_names == [hostname] and tcp_hosts == [PUBLIC]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
