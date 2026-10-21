"""SAP HANA Cloud connector: encrypted workspace config + SQL execution.

Config lives under ``workspace.settings["connectors"]["sap_hana"]``. The
password is encrypted at rest with a Fernet master key
(``HANA_CONNECTOR_FERNET_KEY``), using the same envelope pattern as the
SharePoint OTP connector. When no key is configured (dev), the password is
stored in a plaintext envelope. Runtime credentials always belong to the
workspace; there is no platform password fallback.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.services.connectors.hana.network_policy import (
    HanaConnectorError,
    assert_tls_policy,
    canonical_host,
    resolve_destination,
)
from app.services.connectors.legacy_network import bind_config, network_scoped
from app.services.secrets.compat import read_secret_field, write_secret_field
from app.services.secrets.registry import SecretConsumer

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

ENV_MASTER_KEY = "HANA_CONNECTOR_FERNET_KEY"
CONNECTOR_KEY = "sap_hana"
ENVELOPE_VERSION = 1
DEFAULT_PORT = 443
DEFAULT_MAX_ROWS = 200
DEFAULT_CONNECT_TIMEOUT_MS = 10_000
# Bound each connection attempt, including explicit demo mode.
CONNECT_TIMEOUT_MS = 3_000


class EncryptionNotConfigured(RuntimeError):  # noqa: N818 - legacy public exception name
    """Fernet master key missing or invalid."""


def is_workspace_enabled(workspace: Workspace) -> bool:
    from app.services.workspace_features import feature_enabled

    return feature_enabled(workspace, "sap_hana_connector")


def _connectors(workspace: Workspace) -> dict[str, Any]:
    settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    raw = settings.get("connectors")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _fernet_from_env():
    raw = os.environ.get(ENV_MASTER_KEY)
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

    raw_master = base64.urlsafe_b64decode(key)
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"hana_connector:v1",
        info=b"sap_hana",
    ).derive(raw_master)
    return Fernet(base64.urlsafe_b64encode(derived))


def _encrypt_secret(plaintext: str) -> str:
    payload = plaintext.encode("utf-8")
    fernet = _fernet_from_env()
    if fernet is None:
        logger.warning(
            "%s not set; persisting HANA connector password in PLAINTEXT. "
            "Set %s to a urlsafe-base64 Fernet key before going to production.",
            ENV_MASTER_KEY,
            ENV_MASTER_KEY,
        )
        envelope = {
            "v": ENVELOPE_VERSION,
            "plaintext": base64.b64encode(payload).decode("ascii"),
        }
        return json.dumps(envelope)
    envelope = {
        "v": ENVELOPE_VERSION,
        "ciphertext": fernet.encrypt(payload).decode("ascii"),
    }
    return json.dumps(envelope)


def _decrypt_secret(blob: str) -> str:
    if not blob:
        return ""
    try:
        envelope = json.loads(blob)
    except Exception:
        # Legacy bare password string.
        return blob
    if not isinstance(envelope, dict) or "v" not in envelope:
        return blob
    if "plaintext" in envelope:
        return base64.b64decode(envelope["plaintext"]).decode("utf-8")
    if "ciphertext" in envelope:
        fernet = _fernet_from_env()
        if fernet is None:
            raise EncryptionNotConfigured(f"{ENV_MASTER_KEY} required to decrypt but is not set.")
        return fernet.decrypt(envelope["ciphertext"].encode("ascii")).decode("utf-8")
    raise ValueError(f"Unknown password envelope keys={sorted(envelope)}")


def get_config(workspace: Workspace, *, include_secrets: bool = False) -> dict[str, Any]:
    """Return the workspace HANA connector config.

    By default the password is masked (``password_set`` bool only). Pass
    ``include_secrets=True`` for runtime connection (test/query/skill).
    """
    stored = _connectors(workspace).get(CONNECTOR_KEY)
    stored = dict(stored) if isinstance(stored, Mapping) else {}
    password_blob = stored.get("password_encrypted") or ""
    password_set = bool(password_blob)
    config: dict[str, Any] = {
        "host": str(stored.get("host") or ""),
        "port": int(stored.get("port") or DEFAULT_PORT),
        "user": str(stored.get("user") or ""),
        "encrypt": bool(stored.get("encrypt", True)),
        "ssl_validate_certificate": bool(stored.get("ssl_validate_certificate", True)),
        "demo_mode": stored.get("demo_mode") is True,
        "password_set": password_set,
        "configured": bool(stored.get("host") and stored.get("user") and password_set),
    }
    if include_secrets:
        password = ""
        if password_blob:
            password = (
                read_secret_field(
                    password_blob,
                    legacy=_decrypt_secret,
                    consumer=SecretConsumer(
                        "connector", CONNECTOR_KEY, workspace_id=getattr(workspace, "id", None)
                    ),
                    owner=workspace,
                )
                or ""
            )
        config["password"] = password
        return bind_config(config, workspace)
    return config


def set_config(db: DBSession, workspace: Workspace, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist connector settings. Password is write-only (omit to keep current)."""
    host = canonical_host(str(payload.get("host") or ""))
    user = str(payload.get("user") or "").strip()
    if not host or not user:
        raise ValueError("host and user are required")
    try:
        port = int(payload.get("port") or DEFAULT_PORT)
    except (TypeError, ValueError) as exc:
        raise ValueError("port must be an integer") from exc
    if port <= 0 or port > 65535:
        raise ValueError("port must be between 1 and 65535")
    encrypt = bool(payload.get("encrypt", True))
    verify = bool(payload.get("ssl_validate_certificate", True))
    assert_tls_policy(host, encrypt=encrypt, verify=verify)

    settings = dict(workspace.settings or {})
    connectors = dict(settings.get("connectors") or {})
    current = dict(connectors.get(CONNECTOR_KEY) or {})
    stored: dict[str, Any] = {
        "host": host,
        "port": port,
        "user": user,
        "encrypt": encrypt,
        "ssl_validate_certificate": verify,
        "demo_mode": payload.get("demo_mode") is True,
    }
    password = payload.get("password")
    if password is not None and str(password) != "":
        stored["password_encrypted"] = write_secret_field(
            db,
            str(password),
            scope="workspace",
            name="sap-hana-password",
            legacy=_encrypt_secret,
            kind="password",
            workspace_id=getattr(workspace, "id", None),
        )
    elif current.get("password_encrypted"):
        previous = (
            canonical_host(str(current.get("host") or "")),
            int(current.get("port") or DEFAULT_PORT),
            str(current.get("user") or ""),
        )
        if (host, port, user) != previous:
            raise HanaConnectorError("HANA_CREDENTIAL_DESTINATION_CHANGED", 409)
        stored["password_encrypted"] = current["password_encrypted"]

    connectors[CONNECTOR_KEY] = stored
    settings["connectors"] = connectors
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return get_config(workspace)


@network_scoped
def _connect(config: Mapping[str, Any]):
    host = canonical_host(str(config.get("host") or ""))
    user = str(config.get("user") or "").strip()
    password = str(config.get("password") or "")
    if not host or not user or not password:
        raise HanaConnectorError("HANA_NOT_CONFIGURED")
    port = int(config.get("port") or DEFAULT_PORT)
    encrypt = bool(config.get("encrypt", True))
    verify = bool(config.get("ssl_validate_certificate", True))
    assert_tls_policy(host, encrypt=encrypt, verify=verify)
    destination = resolve_destination(host, port)
    try:
        from hdbcli import dbapi
    except ImportError:  # pragma: no cover - optional until installed
        raise HanaConnectorError("HANA_DRIVER_UNAVAILABLE", 503) from None
    try:
        return dbapi.connect(
            address=destination.address,
            port=port,
            user=user,
            password=password,
            encrypt=encrypt,
            sslValidateCertificate=verify,
            sslHostNameInCertificate=destination.host,
            distributionMode="off",
            communicationTimeout=DEFAULT_CONNECT_TIMEOUT_MS,
            connectTimeout=CONNECT_TIMEOUT_MS,
        )
    except Exception as exc:
        code = getattr(exc, "errorcode", None) or (exc.args[0] if exc.args else None)
        if code == 10:
            raise HanaConnectorError("HANA_AUTH_FAILED", 502) from None
        raise HanaConnectorError("HANA_CONNECTION_FAILED", 502) from None


def _close(resource: Any) -> None:
    try:
        resource.close()
    except Exception:
        logger.warning("HANA_CLOSE_FAILED")


def test_connection(config: Mapping[str, Any]) -> dict[str, Any]:
    """Run ``SELECT CURRENT_USER, CURRENT_SCHEMA FROM DUMMY`` with a short timeout."""
    started = time.perf_counter()
    conn = _connect(config)
    try:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT CURRENT_USER, CURRENT_SCHEMA FROM DUMMY")
            row = cursor.fetchone()
        finally:
            _close(cursor)
    except Exception as exc:
        code = getattr(exc, "errorcode", None) or (exc.args[0] if exc.args else None)
        if code == 258:
            raise HanaConnectorError("HANA_RESOURCE_DENIED", 502) from None
        raise HanaConnectorError("HANA_CONNECTION_FAILED", 502) from None
    finally:
        _close(conn)
    duration_ms = int((time.perf_counter() - started) * 1000)
    current_user = row[0] if row else None
    current_schema = row[1] if row else None
    return {
        "ok": True,
        "current_user": current_user,
        "current_schema": current_schema,
        "duration_ms": duration_ms,
    }


def _assert_read_only(sql: str, *, allow_writes: bool) -> None:
    if allow_writes:
        return
    # Ignore comments and quoted values before checking operations. WITH by
    # itself is not read-only: a CTE can wrap a modifying statement.
    token_pattern = re.compile(
        r"--[^\n]*(?:\n|$)|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|[A-Za-z_][A-Za-z_0-9]*|[^\s]",
        re.DOTALL,
    )
    tokens = [
        token.upper()
        for token in token_pattern.findall(sql or "")
        if not token.startswith(("--", "/*", "'", '"'))
    ]
    if not tokens or tokens[0] not in {"SELECT", "WITH"}:
        raise ValueError("Only read-only SELECT/WITH statements are allowed")
    if tokens[-1:] == [";"]:
        tokens.pop()
    if ";" in tokens:
        raise ValueError("Multiple SQL statements are not allowed in read-only mode")
    if set(tokens) & {
        "INSERT",
        "UPDATE",
        "DELETE",
        "UPSERT",
        "MERGE",
        "DROP",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "CALL",
        "EXEC",
        "EXECUTE",
        "GRANT",
        "REVOKE",
        "IMPORT",
        "EXPORT",
        "INTO",
        "COMMIT",
        "ROLLBACK",
        "SET",
    }:
        raise ValueError("Only read-only SELECT/WITH statements are allowed")


def run_query(
    config: Mapping[str, Any],
    sql: str,
    params: Any | None = None,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    allow_writes: bool = False,
) -> dict[str, Any]:
    """Execute a parameterized SQL statement and return columns/rows."""
    sql = str(sql or "").strip()
    if not sql:
        raise ValueError("sql is required")
    if allow_writes and getattr(settings, "hana_writes_enabled", False) is not True:
        raise HanaConnectorError("HANA_WRITES_DISABLED", 403)
    _assert_read_only(sql, allow_writes=allow_writes)
    try:
        limit = max(1, min(int(max_rows or DEFAULT_MAX_ROWS), 5_000))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_rows must be an integer") from exc

    started = time.perf_counter()
    try:
        conn = _connect(config)
    except Exception as exc:
        # Never disguise policy rejection as a successful demo result.
        demo_allowed = config.get("demo_mode") is True and not allow_writes
        if isinstance(exc, HanaConnectorError) and exc.code not in {
            "HANA_CONNECTION_FAILED",
            "HANA_DNS_FAILED",
            "HANA_NOT_CONFIGURED",
            "HANA_DRIVER_UNAVAILABLE",
        }:
            raise
        if not demo_allowed:
            raise HanaConnectorError("HANA_CONNECTION_FAILED", 502) from None
        logger.warning("HANA_DEMO_FALLBACK")
        from app.services.connectors.hana import demo_dataset

        return demo_dataset.run_demo_query(sql, params, limit=limit)
    try:
        cursor = conn.cursor()
        try:
            if not allow_writes:
                conn.setautocommit(False)
                cursor.execute("SET TRANSACTION READ ONLY")
            if params is None:
                cursor.execute(sql)
            elif isinstance(params, Mapping):
                cursor.execute(sql, dict(params))
            else:
                cursor.execute(sql, list(params))
            description = cursor.description or []
            columns = [str(col[0]) for col in description]
            if not columns:
                # DDL/DML without a result set.
                row_count = cursor.rowcount if cursor.rowcount is not None else 0
                if allow_writes:
                    conn.commit()
                return {
                    "columns": [],
                    "rows": [],
                    "row_count": max(row_count, 0),
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "source": "hana_live",
                }
            fetched = cursor.fetchmany(limit)
            rows = [
                [
                    (value if not isinstance(value, (bytes, bytearray)) else value.hex())
                    for value in row
                ]
                for row in fetched
            ]
        finally:
            _close(cursor)
    except Exception:
        raise HanaConnectorError("HANA_QUERY_FAILED", 502) from None
    finally:
        _close(conn)

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "source": "hana_live",
    }


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PREVIEW_TABLE_CAP = 20
PREVIEW_ROW_CAP = 8
_TABLES_SQL = (
    "SELECT TABLE_NAME, TABLE_TYPE FROM TABLES "
    "WHERE SCHEMA_NAME = CURRENT_SCHEMA ORDER BY TABLE_NAME"
)


def _quoted_ident(name: str) -> str:
    if not _IDENT.match(name or ""):
        raise ValueError("table name is not a safe SQL identifier")
    return f'"{name}"'


def _demo_tables() -> list[dict[str, str]]:
    from app.services.connectors.hana.demo_rows import (
        TABLE_EQUIPMENT,
        TABLE_ORDERS,
        TABLE_PARTS,
    )

    return [
        {"name": TABLE_EQUIPMENT, "kind": "table"},
        {"name": TABLE_ORDERS, "kind": "table"},
        {"name": TABLE_PARTS, "kind": "table"},
    ]


def _rows_as_tables(result: Mapping[str, Any]) -> list[dict[str, str]]:
    tables: list[dict[str, str]] = []
    for row in result.get("rows") or []:
        if not isinstance(row, (list, tuple)) or not row:
            continue
        name = str(row[0] or "").strip()
        if not name:
            continue
        kind = str(row[1] or "table").strip().lower() if len(row) > 1 else "table"
        tables.append({"name": name, "kind": kind or "table"})
        if len(tables) >= PREVIEW_TABLE_CAP:
            break
    return tables


def preview_catalog(
    config: Mapping[str, Any],
    *,
    table: str | None = None,
    max_rows: int = PREVIEW_ROW_CAP,
) -> dict[str, Any]:
    """Read-only schema + sample rows; synthetic fallback requires demo_mode."""
    started = time.perf_counter()
    try:
        limit = max(1, min(int(max_rows or PREVIEW_ROW_CAP), PREVIEW_ROW_CAP))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_rows must be an integer") from exc

    live_info: dict[str, Any] = {}
    live = False
    try:
        live_info = test_connection(config)
        live = True
    except Exception as exc:
        if isinstance(exc, HanaConnectorError) and exc.code not in {
            "HANA_CONNECTION_FAILED",
            "HANA_DNS_FAILED",
            "HANA_NOT_CONFIGURED",
            "HANA_DRIVER_UNAVAILABLE",
        }:
            raise
        if config.get("demo_mode") is not True:
            raise HanaConnectorError("HANA_CONNECTION_FAILED", 502) from None
        live = False

    tables: list[dict[str, str]] = []
    source = "demo_dataset"
    current_user = live_info.get("current_user")
    current_schema = live_info.get("current_schema")
    if live:
        listed = run_query(
            config,
            _TABLES_SQL,
            max_rows=PREVIEW_TABLE_CAP,
            allow_writes=False,
        )
        if listed.get("source") == "hana_live":
            tables = _rows_as_tables(listed)
            source = "hana_live"
        else:
            tables = _demo_tables()
            source = "demo_dataset"
    else:
        tables = _demo_tables()
        current_user = current_user or "DEMO"
        current_schema = current_schema or "DEMO"

    names = {item["name"] for item in tables}
    requested = str(table or "").strip()
    if requested:
        if requested not in names:
            raise ValueError(f"table {requested!r} is not in the preview catalog")
        picked = requested
    else:
        picked = tables[0]["name"] if tables else ""

    sample: dict[str, Any] = {"columns": [], "rows": [], "row_count": 0, "source": source}
    if picked:
        if source == "hana_live" and current_schema and _IDENT.match(str(current_schema)):
            sql = f"SELECT * FROM {_quoted_ident(str(current_schema))}.{_quoted_ident(picked)}"
        else:
            sql = f"SELECT * FROM {_quoted_ident(picked)}"
        if source == "hana_live":
            sample = run_query(config, sql, max_rows=limit, allow_writes=False)
            if sample.get("source") != "hana_live":
                from app.services.connectors.hana import demo_dataset

                sample = demo_dataset.run_demo_query(f'SELECT * FROM "{picked}"', limit=limit)
                source = "demo_dataset"
        else:
            from app.services.connectors.hana import demo_dataset

            sample = demo_dataset.run_demo_query(sql, limit=limit)

    return {
        "ok": True,
        "source": source,
        "current_user": current_user,
        "current_schema": current_schema,
        "tables": tables,
        "sample_table": picked or None,
        "columns": sample.get("columns") or [],
        "rows": sample.get("rows") or [],
        "row_count": sample.get("row_count") or 0,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
