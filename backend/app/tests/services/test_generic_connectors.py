"""Generic catalog connectors keep their secrets on the server, write-only."""

from __future__ import annotations

import io
import json
import smtplib
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.services.connectors.generic import service as generic_service

SECRET = "s3cr3t-value-never-echoed"


def _workspace(settings: dict | None = None):
    return SimpleNamespace(id="ws-1", slug="acme", settings=settings if settings is not None else {})


@pytest.fixture()
def audit(monkeypatch):
    events: list[dict] = []
    monkeypatch.delenv(generic_service.ENV_MASTER_KEY, raising=False)
    monkeypatch.delenv(generic_service.ENV_MASTER_KEY_FALLBACK, raising=False)
    monkeypatch.setattr(generic_service, "flag_modified", lambda *_a, **_k: None)
    monkeypatch.setattr(generic_service, "emit_audit_event", lambda **kwargs: events.append(kwargs))
    return events


def test_a_saved_secret_is_reported_as_set_and_never_returned(audit):
    ws = _workspace()
    public = generic_service.set_config(
        MagicMock(),
        ws,
        "smtp",
        {"host": "smtp.example.test", "port": "587", "username": "agent", "password": SECRET},
        actor="admin-1",
    )

    assert public["values"] == {"host": "smtp.example.test", "port": "587", "username": "agent"}
    assert public["secrets_set"] == {"password": True}
    assert public["configured"] is True
    assert SECRET not in json.dumps(public)
    assert SECRET not in json.dumps(generic_service.list_configs(ws))
    assert SECRET not in json.dumps(ws.settings)
    assert generic_service.get_config(ws, "smtp", include_secrets=True)["secrets"] == {
        "password": SECRET
    }


def test_with_a_master_key_the_secret_is_encrypted_at_rest(audit, monkeypatch):
    fernet = pytest.importorskip("cryptography.fernet")
    monkeypatch.setenv(generic_service.ENV_MASTER_KEY, fernet.Fernet.generate_key().decode())
    ws = _workspace()
    generic_service.set_config(
        MagicMock(), ws, "s3", {"bucket": "docs", "secret_access_key": SECRET}, actor="admin-1"
    )

    envelope = json.loads(ws.settings["generic_connectors"]["s3"]["secrets"]["secret_access_key"])
    assert set(envelope) == {"v", "ciphertext"}
    assert generic_service.get_config(ws, "s3", include_secrets=True)["secrets"] == {
        "secret_access_key": SECRET
    }


def test_an_omitted_or_empty_secret_keeps_the_stored_one(audit):
    ws = _workspace()
    db = MagicMock()
    base = {"host": "db", "database": "erp", "username": "agent"}
    generic_service.set_config(db, ws, "postgresql", {**base, "password": SECRET}, actor="a")
    generic_service.set_config(db, ws, "postgresql", {**base, "host": "db2", "password": ""}, actor="a")
    generic_service.set_config(db, ws, "postgresql", {**base, "host": "db3"}, actor="a")

    config = generic_service.get_config(ws, "postgresql", include_secrets=True)
    assert config["values"]["host"] == "db3"
    assert config["secrets"] == {"password": SECRET}
    assert audit[-1]["details"]["secrets_replaced"] == []


def test_the_audit_names_fields_and_never_carries_a_value(audit):
    ws = _workspace()
    generic_service.set_config(
        MagicMock(), ws, "telegram", {"chat_id": "-100", "bot_token": SECRET}, actor="admin-1"
    )
    generic_service.clear_config(MagicMock(), ws, "telegram", actor="admin-1")

    assert [event["event_type"] for event in audit] == [
        "connector.config.updated",
        "connector.config.cleared",
    ]
    assert audit[0]["details"] == {
        "connector_id": "telegram",
        "changed_fields": ["chat_id"],
        "secrets_replaced": ["bot_token"],
    }
    assert audit[1]["details"] == {"connector_id": "telegram", "secrets_cleared": ["bot_token"]}
    assert SECRET not in json.dumps(audit, default=str)
    assert generic_service.get_config(ws, "telegram")["configured"] is False


def test_unknown_fields_and_bad_values_are_refused_by_name_only(audit):
    ws = _workspace()
    with pytest.raises(ValueError, match="Unknown fields for smtp: token"):
        generic_service.set_config(MagicMock(), ws, "smtp", {"token": SECRET}, actor="a")
    with pytest.raises(ValueError) as too_long:
        generic_service.set_config(MagicMock(), ws, "smtp", {"password": SECRET * 500}, actor="a")
    assert SECRET not in str(too_long.value)
    with pytest.raises(ValueError) as not_text:
        generic_service.set_config(MagicMock(), ws, "smtp", {"password": {"v": SECRET}}, actor="a")
    assert SECRET not in str(not_text.value)
    assert audit == []
    assert ws.settings == {}


def test_planned_connectors_store_nothing():
    assert "whatsapp" not in generic_service.CONNECTORS
    assert "elasticsearch" not in generic_service.CONNECTORS


def test_a_connector_without_a_real_test_says_so():
    for connector_id in ("dynamics365", "teams", "outlook", "mqtt", "s3"):
        assert generic_service.get_config(_workspace(), connector_id)["testable"] is False
        result = generic_service.test_connection(connector_id, {})
        assert result["status"] == "unsupported"
        assert result["checked_at"]


def _telegram(monkeypatch, *, status=200, error: Exception | None = None) -> list[str]:
    seen: list[str] = []

    def urlopen(url, timeout):
        seen.append(url)
        if error is not None:
            raise error
        if status != 200:
            raise urllib.error.HTTPError(url, status, "Unauthorized", None, None)
        return io.BytesIO(b'{"ok": true, "result": {"username": "agentium_bot"}}')

    monkeypatch.setattr(generic_service.urllib.request, "urlopen", urlopen)
    return seen


def test_telegram_is_checked_against_the_bot_api(monkeypatch):
    seen = _telegram(monkeypatch)
    result = generic_service.test_connection("telegram", {"secrets": {"bot_token": "123:abc"}})

    assert seen == ["https://api.telegram.org/bot123:abc/getMe"]
    assert result["status"] == "connected"
    assert result["detail"] == "@agentium_bot"
    assert result["checked_at"]


def test_a_refused_token_reads_as_auth_failed_and_is_never_echoed(monkeypatch, caplog):
    _telegram(monkeypatch, status=401)
    refused = generic_service.test_connection("telegram", {"secrets": {"bot_token": SECRET}})
    _telegram(monkeypatch, error=urllib.error.URLError("name resolution failed"))
    unreachable = generic_service.test_connection("telegram", {"secrets": {"bot_token": SECRET}})
    _telegram(monkeypatch, error=RuntimeError(f"GET https://api.telegram.org/bot{SECRET}/getMe"))
    crashed = generic_service.test_connection("telegram", {"secrets": {"bot_token": SECRET}})

    assert refused["status"] == "auth_failed"
    assert unreachable["status"] == "unreachable"
    assert crashed["status"] == "error"
    assert crashed["detail"] == "RuntimeError"
    assert SECRET not in json.dumps([refused, unreachable, crashed])
    assert SECRET not in caplog.text


def _smtp(monkeypatch, *, login_error: Exception | None = None) -> list[tuple]:
    calls: list[tuple] = []

    class FakeSmtp:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def ehlo(self):
            calls.append(("ehlo",))

        def has_extn(self, name):
            return name == "starttls"

        def starttls(self, context):
            calls.append(("starttls",))

        def login(self, username, password):
            calls.append(("login", username))
            if login_error is not None:
                raise login_error

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(generic_service.smtplib, "SMTP", FakeSmtp)
    return calls


def test_smtp_logs_in_over_starttls(monkeypatch):
    calls = _smtp(monkeypatch)
    config = {
        "values": {"host": "smtp.example.test", "port": "587", "username": "agent"},
        "secrets": {"password": SECRET},
    }
    result = generic_service.test_connection("smtp", config)

    assert result["status"] == "connected"
    assert calls[0] == ("connect", "smtp.example.test", 587)
    assert ("starttls",) in calls
    assert ("login", "agent") in calls
    assert calls[-1] == ("close",)


def test_smtp_refused_credentials_read_as_auth_failed(monkeypatch):
    _smtp(monkeypatch, login_error=smtplib.SMTPAuthenticationError(535, b"5.7.8 rejected"))
    config = {"values": {"host": "smtp.example.test", "username": "agent"}, "secrets": {"password": SECRET}}

    assert generic_service.test_connection("smtp", config)["status"] == "auth_failed"


def test_postgresql_refused_password_reads_as_auth_failed(monkeypatch):
    import psycopg2

    def refuse(**_kwargs):
        raise psycopg2.OperationalError('FATAL:  password authentication failed for user "agent"')

    monkeypatch.setattr(psycopg2, "connect", refuse)
    config = {
        "values": {"host": "db.example.test", "database": "erp", "username": "agent"},
        "secrets": {"password": SECRET},
    }

    assert generic_service.test_connection("postgresql", config)["status"] == "auth_failed"


def test_postgresql_without_credentials_is_never_attempted(monkeypatch):
    import psycopg2

    def connect(**_kwargs):
        pytest.fail("libpq would fill the credentials from the backend's own environment")

    monkeypatch.setattr(psycopg2, "connect", connect)
    config = {"values": {"host": "db.example.test", "database": "erp"}}

    assert generic_service.test_connection("postgresql", config)["status"] == "not_configured"


def _rest(monkeypatch, status: int) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(generic_service.httpx, "Client", client_factory)
    return seen


def test_rest_api_sends_the_key_in_the_configured_header(monkeypatch):
    seen = _rest(monkeypatch, 200)
    config = {
        "values": {"base_url": "https://api.example.test/v1", "auth_header": "X-API-Key"},
        "secrets": {"api_key": SECRET},
    }
    result = generic_service.test_connection("rest_api", config)

    assert result["status"] == "connected"
    assert result["detail"] == "HTTP 200"
    assert seen[0].headers["X-API-Key"] == SECRET
    assert SECRET not in json.dumps(result)


def test_rest_api_rejection_reads_as_auth_failed(monkeypatch):
    _rest(monkeypatch, 401)
    config = {"values": {"base_url": "https://api.example.test"}, "secrets": {"api_key": SECRET}}
    result = generic_service.test_connection("rest_api", config)

    assert result["status"] == "auth_failed"
    assert result["detail"] == "HTTP 401"
