"""Catalog connectors without a page of their own: workspace config, write-only secrets.

Config lives under ``workspace.settings["generic_connectors"][<id>]``. The
workspace API never returns that key and a settings PATCH cannot overwrite it,
so this module is the only way in or out. Only the fields declared in
``CONNECTORS`` are stored. Secret fields are encrypted at rest with a Fernet
master key (``CONNECTOR_SECRETS_FERNET_KEY``, falling back to
``HANA_CONNECTOR_FERNET_KEY``), using the same envelope as the SAP HANA
connector. When no key is configured (dev), they are stored in a plaintext
envelope. Reads report ``secrets_set`` only; the decrypted values are handed
to the connection test and nowhere else.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

import httpx
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.services.audit_logger import emit_audit_event

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

ENV_MASTER_KEY = "CONNECTOR_SECRETS_FERNET_KEY"
ENV_MASTER_KEY_FALLBACK = "HANA_CONNECTOR_FERNET_KEY"
SETTINGS_KEY = "generic_connectors"
ENVELOPE_VERSION = 1
MAX_VALUE_LENGTH = 4096
TEST_TIMEOUT_S = 8.0


class EncryptionNotConfigured(RuntimeError):
    """Fernet master key missing or invalid."""


@dataclass(frozen=True)
class ConnectorSpec:
    fields: tuple[str, ...]
    secrets: tuple[str, ...] = ()


# The connectors of ``resources.catalog.ts`` that open the generic drawer.
# Planned ones (WhatsApp, Elasticsearch) are left out: nothing runs them, so
# nothing of theirs is stored.
CONNECTORS: dict[str, ConnectorSpec] = {
    "dynamics365": ConnectorSpec(("tenant_url", "client_id", "default_entity"), ("client_secret",)),
    # A Teams incoming-webhook URL is the credential: whoever holds it can post.
    "teams": ConnectorSpec(("tenant_id", "bot_id"), ("webhook_url",)),
    "outlook": ConnectorSpec(("mailbox", "tenant_id", "shared")),
    "telegram": ConnectorSpec(("chat_id", "webhook_url"), ("bot_token",)),
    "smtp": ConnectorSpec(("host", "port", "username"), ("password",)),
    "rest_api": ConnectorSpec(("base_url", "auth_header"), ("api_key",)),
    "mqtt": ConnectorSpec(("broker_url", "topic", "client_id", "username"), ("password",)),
    "postgresql": ConnectorSpec(("host", "port", "database", "username"), ("password",)),
    "s3": ConnectorSpec(("bucket", "region", "access_key_id"), ("secret_access_key",)),
}


def _fernet_from_env():
    raw = (os.environ.get(ENV_MASTER_KEY) or os.environ.get(ENV_MASTER_KEY_FALLBACK) or "").strip()
    if not raw:
        return None
    try:
        key = raw.encode("ascii")
        if len(base64.urlsafe_b64decode(key)) != 32:
            raise ValueError("expected 32 bytes after base64 decode")
    except Exception as exc:
        raise EncryptionNotConfigured(
            f"{ENV_MASTER_KEY} is not a valid urlsafe base64 Fernet key: {exc}"
        ) from exc
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"generic_connectors:v1",
        info=b"generic_connectors",
    ).derive(base64.urlsafe_b64decode(key))
    return Fernet(base64.urlsafe_b64encode(derived))


def _encrypt_secret(plaintext: str) -> str:
    payload = plaintext.encode("utf-8")
    fernet = _fernet_from_env()
    if fernet is None:
        logger.warning(
            "%s not set; persisting connector secrets in a PLAINTEXT envelope. "
            "Set %s to a urlsafe-base64 Fernet key before going to production.",
            ENV_MASTER_KEY,
            ENV_MASTER_KEY,
        )
        return json.dumps(
            {"v": ENVELOPE_VERSION, "plaintext": base64.b64encode(payload).decode("ascii")}
        )
    return json.dumps(
        {"v": ENVELOPE_VERSION, "ciphertext": fernet.encrypt(payload).decode("ascii")}
    )


def _decrypt_secret(blob: str) -> str:
    envelope = json.loads(blob)
    if "plaintext" in envelope:
        return base64.b64decode(envelope["plaintext"]).decode("utf-8")
    fernet = _fernet_from_env()
    if fernet is None:
        raise EncryptionNotConfigured(f"{ENV_MASTER_KEY} required to decrypt but is not set.")
    return fernet.decrypt(envelope["ciphertext"].encode("ascii")).decode("utf-8")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _entries(workspace: "Workspace") -> dict[str, Any]:
    settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    return _mapping(settings.get(SETTINGS_KEY))


def get_config(
    workspace: "Workspace",
    connector_id: str,
    *,
    include_secrets: bool = False,
) -> dict[str, Any]:
    """Return one connector: its plain values and which secrets are set.

    ``include_secrets=True`` adds decrypted secrets for the connection test
    and verified server-side readers. Never return that envelope to a client.
    """
    spec = CONNECTORS[connector_id]
    entry = _mapping(_entries(workspace).get(connector_id))
    stored_values = _mapping(entry.get("values"))
    stored_secrets = _mapping(entry.get("secrets"))
    values = {key: str(stored_values[key]) for key in spec.fields if stored_values.get(key)}
    secrets_set = {key: bool(stored_secrets.get(key)) for key in spec.secrets}
    config: dict[str, Any] = {
        "id": connector_id,
        "values": values,
        "secrets_set": secrets_set,
        "configured": bool(values) or any(secrets_set.values()),
        "testable": connector_id in _TESTERS,
    }
    if include_secrets:
        config["secrets"] = {
            key: _decrypt_secret(str(stored_secrets[key]))
            for key in spec.secrets
            if stored_secrets.get(key)
        }
    return config


def list_configs(workspace: "Workspace") -> list[dict[str, Any]]:
    return [get_config(workspace, connector_id) for connector_id in CONNECTORS]


def _text(key: str, value: Any) -> str:
    # Errors name the field, never the value: the value may be a secret.
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"{key} must be text")
    text = str(value)
    if len(text) > MAX_VALUE_LENGTH:
        raise ValueError(f"{key} is longer than {MAX_VALUE_LENGTH} characters")
    return text


def _persist(db: DBSession, workspace: "Workspace", entries: dict[str, Any]) -> None:
    settings = dict(workspace.settings or {})
    settings[SETTINGS_KEY] = entries
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)


def set_config(
    db: DBSession,
    workspace: "Workspace",
    connector_id: str,
    values: Mapping[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    """Replace the plain fields. A secret sent non-empty replaces the stored
    one; omitted or empty, the stored one is kept."""
    spec = CONNECTORS[connector_id]
    unknown = sorted(set(values) - set(spec.fields) - set(spec.secrets))
    if unknown:
        raise ValueError(f"Unknown fields for {connector_id}: {', '.join(unknown)}")

    entries = _entries(workspace)
    current = _mapping(entries.get(connector_id))
    previous = _mapping(current.get("values"))
    plain: dict[str, str] = {}
    for key in spec.fields:
        text = _text(key, values.get(key)).strip()
        if text:
            plain[key] = text
    secrets = _mapping(current.get("secrets"))
    replaced: list[str] = []
    for key in spec.secrets:
        text = _text(key, values.get(key))
        if text.strip():
            secrets[key] = _encrypt_secret(text)
            replaced.append(key)

    entries[connector_id] = {"values": plain, "secrets": secrets}
    _persist(db, workspace, entries)
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="connector.config.updated",
        actor=actor,
        details={
            "connector_id": connector_id,
            "changed_fields": sorted(
                key for key in set(plain) | set(previous) if plain.get(key) != previous.get(key)
            ),
            "secrets_replaced": replaced,
        },
        db=db,
    )
    db.commit()
    db.refresh(workspace)
    return get_config(workspace, connector_id)


def clear_config(
    db: DBSession,
    workspace: "Workspace",
    connector_id: str,
    *,
    actor: str,
) -> dict[str, Any]:
    entries = _entries(workspace)
    removed = _mapping(entries.pop(connector_id, None))
    _persist(db, workspace, entries)
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="connector.config.cleared",
        actor=actor,
        details={
            "connector_id": connector_id,
            "secrets_cleared": sorted(_mapping(removed.get("secrets"))),
        },
        db=db,
    )
    db.commit()
    db.refresh(workspace)
    return get_config(workspace, connector_id)


def _port(value: Any, default: int) -> int:
    try:
        port = int(str(value).strip())
    except ValueError:
        return default
    return port if 0 < port < 65536 else default


_Outcome = tuple[str, Optional[str]]


def _test_telegram(values: Mapping[str, Any], secrets: Mapping[str, Any]) -> _Outcome:
    token = secrets.get("bot_token")
    if not token:
        return "not_configured", None
    # The token is part of the URL, and httpx logs every request URL at INFO.
    url = f"https://api.telegram.org/bot{urllib.parse.quote(token, safe=':')}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=TEST_TIMEOUT_S) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 404):
            return "auth_failed", None
        return "error", f"HTTP {exc.code}"
    except OSError:
        return "unreachable", None
    try:
        username = (json.loads(raw).get("result") or {}).get("username")
    except (ValueError, AttributeError):
        username = None
    return "connected", f"@{username}" if username else None


def _test_smtp(values: Mapping[str, Any], secrets: Mapping[str, Any]) -> _Outcome:
    host = values.get("host")
    if not host:
        return "not_configured", None
    port = _port(values.get("port"), 587)
    context = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=TEST_TIMEOUT_S, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=TEST_TIMEOUT_S)
        try:
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls(context=context)
                server.ehlo()
            username, password = values.get("username"), secrets.get("password")
            if username and password:
                server.login(username, password)
        finally:
            server.close()
    except smtplib.SMTPAuthenticationError:
        return "auth_failed", None
    except smtplib.SMTPException as exc:
        return "error", type(exc).__name__
    except OSError:
        return "unreachable", None
    return "connected", None


def _test_postgresql(values: Mapping[str, Any], secrets: Mapping[str, Any]) -> _Outcome:
    host, database = values.get("host"), values.get("database")
    username, password = values.get("username"), secrets.get("password")
    # libpq fills an empty user or password from the backend's own environment
    # (PGUSER, PGPASSWORD, .pgpass) and would send it to whatever host is set.
    if not (host and database and username and password):
        return "not_configured", None
    import psycopg2

    try:
        conn = psycopg2.connect(
            host=host,
            port=_port(values.get("port"), 5432),
            dbname=database,
            user=username,
            password=password,
            connect_timeout=int(TEST_TIMEOUT_S),
        )
    except psycopg2.OperationalError as exc:
        message = str(exc).lower()
        if "authentication failed" in message or "pg_hba.conf" in message:
            return "auth_failed", None
        return "unreachable", None
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
    finally:
        conn.close()
    return "connected", None


def _test_rest_api(values: Mapping[str, Any], secrets: Mapping[str, Any]) -> _Outcome:
    base_url = values.get("base_url")
    if not base_url:
        return "not_configured", None
    headers = {"Accept": "application/json"}
    if secrets.get("api_key"):
        headers[values.get("auth_header") or "Authorization"] = secrets["api_key"]
    try:
        # A custom auth header is not dropped on a cross-host redirect.
        with httpx.Client(timeout=TEST_TIMEOUT_S, follow_redirects=False) as client:
            response = client.get(base_url, headers=headers)
    except httpx.HTTPError:
        return "unreachable", None
    if response.status_code in (401, 403):
        return "auth_failed", f"HTTP {response.status_code}"
    if response.status_code >= 500:
        return "error", f"HTTP {response.status_code}"
    return "connected", f"HTTP {response.status_code}"


_TESTERS: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], _Outcome]] = {
    "telegram": _test_telegram,
    "smtp": _test_smtp,
    "postgresql": _test_postgresql,
    "rest_api": _test_rest_api,
}


def test_connection(connector_id: str, config: Mapping[str, Any]) -> dict[str, Any]:
    """Contact the service with the stored config. The result never carries a secret."""
    tester = _TESTERS.get(connector_id)
    if tester is None:
        status, detail = "unsupported", None
    else:
        try:
            status, detail = tester(_mapping(config.get("values")), _mapping(config.get("secrets")))
        except Exception as exc:  # noqa: BLE001 — a driver message can quote the request
            logger.warning("Connector test %s failed: %s", connector_id, type(exc).__name__)
            status, detail = "error", type(exc).__name__
    return {
        "id": connector_id,
        "status": status,
        "detail": detail,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
