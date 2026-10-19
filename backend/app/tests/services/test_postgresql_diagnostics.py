"""Connection failures stay actionable without exposing libpq's sensitive text."""

from unittest.mock import MagicMock

import psycopg2
import pytest

from app.services.connectors.generic import postgresql_browser as browser
from app.services.connectors.generic import service
from app.services.connectors.postgresql_diagnostics import diagnose

SENSITIVE = "private-account password=do-not-return /private/certificate/path"


@pytest.mark.parametrize(
    ("message", "code", "status"),
    [
        ('root certificate file "/private/root.crt" does not exist', "PG_TLS_TRUST_REQUIRED", 503),
        ("could not read root certificate file: Permission denied", "PG_TLS_TRUST_REQUIRED", 503),
        ("SSL error: certificate verify failed", "PG_TLS_VERIFICATION_FAILED", 503),
        (
            'server certificate for "db" does not match host name "ip"',
            "PG_TLS_VERIFICATION_FAILED",
            503,
        ),
        ("server does not support SSL, but SSL was required", "PG_TLS_UNAVAILABLE", 503),
        ("SSL error: tlsv1 alert unknown ca", "PG_TLS_FAILED", 503),
        ('FATAL: password authentication failed for user "reader"', "PG_AUTH_FAILED", 403),
        ('FATAL: no pg_hba.conf entry for host "private"', "PG_AUTH_FAILED", 403),
        ('FATAL: database "missing" does not exist', "PG_DATABASE_NOT_FOUND", 409),
        ("connection to server failed: Connection refused", "PG_CONNECTION_REFUSED", 503),
        ("connection to server failed: timeout expired", "PG_CONNECTION_TIMEOUT", 504),
        ("connection to server failed: Connection timed out", "PG_CONNECTION_TIMEOUT", 504),
        ("unfamiliar driver error", "PG_UNAVAILABLE", 503),
    ],
)
def test_connection_diagnostics_are_closed_and_shared_by_test_and_explorer(
    monkeypatch, caplog, message, code, status
):
    error = psycopg2.OperationalError(f"{message}\n{SENSITIVE}")
    diagnostic = diagnose(error)
    assert (diagnostic.code, diagnostic.status, diagnostic.sqlstate) == (code, status, None)
    assert SENSITIVE not in repr(diagnostic)

    config = {
        "values": {"host": "database.example.test", "database": "db", "username": "reader"},
        "secrets": {"password": SENSITIVE},
    }

    def fail(**kwargs):
        raise error

    monkeypatch.setattr(psycopg2, "connect", fail)
    # No external DNS/DB in classification tests; network policy has its own
    # entrypoint tests and remains mandatory in production.
    monkeypatch.setattr(
        "app.services.connectors.network_policy.postgresql_connection_options", lambda *a, **kw: {}
    )
    monkeypatch.setattr(browser, "postgresql_connection_options", lambda *a, **kw: {})
    monkeypatch.setattr(browser, "get_config", lambda *a, **kw: config)
    outcome, detail = service._test_postgresql(config["values"], config["secrets"])
    if code == "PG_AUTH_FAILED":
        assert outcome == "auth_failed"
    elif code in {"PG_UNAVAILABLE", "PG_CONNECTION_REFUSED", "PG_CONNECTION_TIMEOUT"}:
        assert outcome == "unreachable"
    else:
        assert outcome == "error"
    assert detail == code
    with caplog.at_level("WARNING"), pytest.raises(browser.PostgresBrowseError) as caught:
        browser.catalog(object())
    assert (caught.value.code, caught.value.status) == (code, status)
    assert SENSITIVE not in caplog.text
    assert code in caplog.text


def test_sqlstate_takes_precedence_and_non_driver_messages_are_not_interpreted():
    class Refused(psycopg2.OperationalError):
        pgcode = "28P01"

    result = diagnose(Refused("certificate verify failed"))
    assert (result.code, result.sqlstate) == ("PG_AUTH_FAILED", "28P01")
    assert diagnose(RuntimeError("certificate verify failed")).code == "PG_UNAVAILABLE"

    class InvalidState(psycopg2.OperationalError):
        pgcode = "密码ab1"

    assert diagnose(InvalidState(SENSITIVE)).sqlstate is None


def test_query_errors_are_not_misreported_as_connection_failures_and_close(monkeypatch):
    class TimedOut(psycopg2.OperationalError):
        pgcode = "57014"

    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.execute.side_effect = TimedOut(SENSITIVE)
    monkeypatch.setattr(psycopg2, "connect", lambda **kw: connection)
    monkeypatch.setattr(
        "app.services.connectors.network_policy.postgresql_connection_options", lambda *a, **kw: {}
    )
    outcome = service._test_postgresql(
        {"host": "database.example.test", "database": "db", "username": "reader"},
        {"password": SENSITIVE},
    )
    assert outcome == ("error", "PG_TIMEOUT")
    connection.close.assert_called_once()
