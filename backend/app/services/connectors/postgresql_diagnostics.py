"""Closed PostgreSQL diagnostics shared by the connection test and explorer.

libpq often omits SQLSTATE for failures during connection establishment. Inspect
its known messages locally to identify a next action, but never return or log
those messages: they can contain hostnames, accounts, file paths and secrets.
Unknown messages remain unavailable instead of guessing the cause.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PostgresDiagnostic:
    code: str
    status: int = 503
    sqlstate: str | None = None


def sqlstate(error: BaseException) -> str | None:
    value = getattr(error, "pgcode", None)
    return value if isinstance(value, str) and re.fullmatch(r"[0-9A-Z]{5}", value) else None


def diagnose(error: BaseException, *, stage: str = "connect") -> PostgresDiagnostic:
    import psycopg2

    state = sqlstate(error)
    if state and state.startswith("28"):
        return PostgresDiagnostic("PG_AUTH_FAILED", 403, state)
    known = {
        "3D000": ("PG_DATABASE_NOT_FOUND", 409),
        "42501": ("PG_PERMISSION_DENIED", 403),
        "57014": ("PG_TIMEOUT", 504),
        "55P03": ("PG_TIMEOUT", 504),
        "42P01": ("PG_SOURCE_CHANGED", 409),
        "42703": ("PG_SOURCE_CHANGED", 409),
    }
    if state in known:
        code, status = known[state]
        return PostgresDiagnostic(code, status, state)
    if stage == "query":
        if isinstance(error, psycopg2.Error) and not (state or "").startswith("08"):
            return PostgresDiagnostic("PG_QUERY_FAILED", 502, state)
        return PostgresDiagnostic("PG_UNAVAILABLE", 503, state)
    if not isinstance(error, psycopg2.OperationalError):
        return PostgresDiagnostic("PG_UNAVAILABLE", 503, state)

    # Fixed libpq English phrases only. Translated or unfamiliar errors fall
    # back safely; no substring of the driver's text enters the result.
    message = str(error).lower()
    if (
        "root certificate file" in message
        or "could not read root certificate" in message
        or "could not load root certificate" in message
    ):
        return PostgresDiagnostic("PG_TLS_TRUST_REQUIRED", 503, state)
    if "certificate verify failed" in message or (
        "server certificate" in message and "does not match" in message
    ):
        return PostgresDiagnostic("PG_TLS_VERIFICATION_FAILED", 503, state)
    if "server does not support ssl" in message:
        return PostgresDiagnostic("PG_TLS_UNAVAILABLE", 503, state)
    if "ssl error:" in message:
        return PostgresDiagnostic("PG_TLS_FAILED", 503, state)
    if "authentication failed" in message or "no pg_hba.conf entry" in message:
        return PostgresDiagnostic("PG_AUTH_FAILED", 403, state)
    if re.search(r'database "[^\n]+" does not exist', message):
        return PostgresDiagnostic("PG_DATABASE_NOT_FOUND", 409, state)
    if "connection refused" in message:
        return PostgresDiagnostic("PG_CONNECTION_REFUSED", 503, state)
    if "timeout expired" in message or "connection timed out" in message:
        return PostgresDiagnostic("PG_CONNECTION_TIMEOUT", 504, state)
    return PostgresDiagnostic("PG_UNAVAILABLE", 503, state)
