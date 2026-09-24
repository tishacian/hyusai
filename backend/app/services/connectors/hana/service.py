"""SAP HANA Cloud connector: encrypted workspace config + SQL execution.

Config lives under ``workspace.settings["connectors"]["sap_hana"]``. The
password is encrypted at rest with a Fernet master key
(``HANA_CONNECTOR_FERNET_KEY``), using the same envelope pattern as the
SharePoint OTP connector. When no key is configured (dev), the password is
stored in a plaintext envelope. ``HANA_CONNECTOR_PASSWORD`` can supply a
demo password when none is stored on the workspace.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from typing import TYPE_CHECKING, Any, Mapping, Optional

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

ENV_MASTER_KEY = "HANA_CONNECTOR_FERNET_KEY"
ENV_FALLBACK_PASSWORD = "HANA_CONNECTOR_PASSWORD"
CONNECTOR_KEY = "sap_hana"
ENVELOPE_VERSION = 1
DEFAULT_PORT = 443
DEFAULT_MAX_ROWS = 200
DEFAULT_CONNECT_TIMEOUT_MS = 10_000
# Short TCP connect timeout so demo fallback kicks in within a few seconds.
CONNECT_TIMEOUT_MS = 3_000

_READ_ONLY_PREFIX = re.compile(r"^\s*(?:/\*.*?\*/\s*)*(?:\(\s*)?(SELECT|WITH)\b", re.IGNORECASE | re.DOTALL)


class EncryptionNotConfigured(RuntimeError):
    """Fernet master key missing or invalid."""


def is_workspace_enabled(workspace: "Workspace") -> bool:
    from app.services.workspace_features import feature_enabled

    return feature_enabled(workspace, "sap_hana_connector")


def _connectors(workspace: "Workspace") -> dict[str, Any]:
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
            raise EncryptionNotConfigured(
                f"{ENV_MASTER_KEY} required to decrypt but is not set."
            )
        return fernet.decrypt(envelope["ciphertext"].encode("ascii")).decode("utf-8")
    raise ValueError(f"Unknown password envelope keys={sorted(envelope)}")


def get_config(workspace: "Workspace", *, include_secrets: bool = False) -> dict[str, Any]:
    """Return the workspace HANA connector config.

    By default the password is masked (``password_set`` bool only). Pass
    ``include_secrets=True`` for runtime connection (test/query/skill).
    """
    stored = _connectors(workspace).get(CONNECTOR_KEY)
    stored = dict(stored) if isinstance(stored, Mapping) else {}
    password_blob = str(stored.get("password_encrypted") or "")
    password_set = bool(password_blob) or bool(os.environ.get(ENV_FALLBACK_PASSWORD))
    config: dict[str, Any] = {
        "host": str(stored.get("host") or ""),
        "port": int(stored.get("port") or DEFAULT_PORT),
        "user": str(stored.get("user") or ""),
        "encrypt": bool(stored.get("encrypt", True)),
        "password_set": password_set,
        "configured": bool(stored.get("host") and stored.get("user") and password_set),
    }
    if include_secrets:
        password = ""
        if password_blob:
            password = _decrypt_secret(password_blob)
        if not password:
            password = os.environ.get(ENV_FALLBACK_PASSWORD) or ""
        config["password"] = password
    return config


def set_config(db: DBSession, workspace: "Workspace", payload: Mapping[str, Any]) -> dict[str, Any]:
    """Persist connector settings. Password is write-only (omit to keep current)."""
    host = str(payload.get("host") or "").strip()
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

    settings = dict(workspace.settings or {})
    connectors = dict(settings.get("connectors") or {})
    current = dict(connectors.get(CONNECTOR_KEY) or {})
    stored: dict[str, Any] = {
        "host": host,
        "port": port,
        "user": user,
        "encrypt": encrypt,
    }
    password = payload.get("password")
    if password is not None and str(password) != "":
        stored["password_encrypted"] = _encrypt_secret(str(password))
    elif current.get("password_encrypted"):
        stored["password_encrypted"] = current["password_encrypted"]

    connectors[CONNECTOR_KEY] = stored
    settings["connectors"] = connectors
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return get_config(workspace)


def _connect(config: Mapping[str, Any]):
    try:
        from hdbcli import dbapi
    except ImportError as exc:  # pragma: no cover - optional until installed
        raise RuntimeError(
            "hdbcli is not installed. Add hdbcli>=2.20 to backend requirements."
        ) from exc

    host = str(config.get("host") or "").strip()
    user = str(config.get("user") or "").strip()
    password = str(config.get("password") or "")
    if not host or not user or not password:
        raise ValueError("HANA connector is not fully configured (host/user/password)")
    port = int(config.get("port") or DEFAULT_PORT)
    encrypt = bool(config.get("encrypt", True))
    return dbapi.connect(
        address=host,
        port=port,
        user=user,
        password=password,
        encrypt=encrypt,
        sslValidateCertificate=False,
        communicationTimeout=DEFAULT_CONNECT_TIMEOUT_MS,
        connectTimeout=CONNECT_TIMEOUT_MS,
    )


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
            cursor.close()
    finally:
        conn.close()
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
    if not _READ_ONLY_PREFIX.match(sql or ""):
        raise ValueError(
            "Only SELECT/WITH statements are allowed unless allow_writes=true"
        )
    # Reject stacked statements (simple heuristic).
    stripped = (sql or "").strip().rstrip(";")
    if ";" in stripped:
        raise ValueError("Multiple SQL statements are not allowed in read-only mode")


def run_query(
    config: Mapping[str, Any],
    sql: str,
    params: Optional[Any] = None,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    allow_writes: bool = False,
) -> dict[str, Any]:
    """Execute a parameterized SQL statement and return columns/rows."""
    sql = str(sql or "").strip()
    if not sql:
        raise ValueError("sql is required")
    _assert_read_only(sql, allow_writes=allow_writes)
    try:
        limit = max(1, min(int(max_rows or DEFAULT_MAX_ROWS), 5_000))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_rows must be an integer") from exc

    started = time.perf_counter()
    try:
        conn = _connect(config)
    except Exception as exc:
        # Demo resilience: when the live HANA instance is unreachable and the
        # statement is read-only, answer from the in-memory demo dataset.
        if allow_writes:
            raise
        logger.warning(
            "HANA connection failed (%s); falling back to in-memory demo dataset",
            exc,
        )
        from app.services.connectors.hana import demo_dataset

        return demo_dataset.run_demo_query(sql, params, limit=limit)
    try:
        cursor = conn.cursor()
        try:
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
            cursor.close()
    finally:
        conn.close()

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
    from app.seeds.hana_demo_rows import (
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
    table: Optional[str] = None,
    max_rows: int = PREVIEW_ROW_CAP,
) -> dict[str, Any]:
    """Read-only schema + sample rows. Live HANA when reachable, else demo tables."""
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
    except Exception:
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
