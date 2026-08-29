"""MCP connector registry: several HTTP servers per workspace.

Config lives under ``workspace.settings["connectors"]["mcp"]["servers"]``.
Tokens use the same Fernet envelope as HANA (``MCP_CONNECTOR_FERNET_KEY``,
dev fallback ``HANA_CONNECTOR_FERNET_KEY``). Never store secrets on the
flow JSON or run input.

Resolution for a server id:
  1. workspace row (url / token_encrypted) when present
  2. env ``MCP_<SERVER_ID>_URL`` / ``MCP_<SERVER_ID>_TOKEN``
  3. else ``configured: false`` — skills fail closed (``mcp_unconfigured``)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import TYPE_CHECKING, Any, Mapping, Optional

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.services.connectors.mcp.contract import (
    ALLOWED_TRANSPORTS,
    DEFAULT_TRANSPORT,
    default_aliases,
)
from app.services.connectors.mcp.errors import McpUnconfigured

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

ENV_MASTER_KEY = "MCP_CONNECTOR_FERNET_KEY"
ENV_MASTER_KEY_FALLBACK = "HANA_CONNECTOR_FERNET_KEY"
CONNECTOR_KEY = "mcp"
FEATURE_FLAG = "mcp_connector"
ENVELOPE_VERSION = 1

_SERVER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class EncryptionNotConfigured(RuntimeError):
    """Fernet master key missing or invalid."""


def is_workspace_enabled(workspace: "Workspace") -> bool:
    from app.services.workspace_features import feature_enabled

    return feature_enabled(workspace, FEATURE_FLAG, csv_fallback="")


def _connectors(workspace: "Workspace") -> dict[str, Any]:
    settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    raw = settings.get("connectors")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _env_master_key() -> str:
    return (os.environ.get(ENV_MASTER_KEY) or os.environ.get(ENV_MASTER_KEY_FALLBACK) or "").strip()


def _fernet_from_env():
    raw = _env_master_key()
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
        salt=b"mcp_connector:v1",
        info=b"mcp",
    ).derive(raw_master)
    return Fernet(base64.urlsafe_b64encode(derived))


def _encrypt_secret(plaintext: str) -> str:
    payload = plaintext.encode("utf-8")
    fernet = _fernet_from_env()
    if fernet is None:
        logger.warning(
            "%s not set; persisting MCP connector token in PLAINTEXT. "
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
    raise ValueError(f"Unknown MCP token envelope keys={sorted(envelope)}")


def env_url_key(server_id: str) -> str:
    return f"MCP_{str(server_id).strip().upper()}_URL"


def env_token_key(server_id: str) -> str:
    return f"MCP_{str(server_id).strip().upper()}_TOKEN"


def _env_url(server_id: str) -> str:
    return (os.environ.get(env_url_key(server_id)) or "").strip().rstrip("/")


def _env_token(server_id: str) -> str:
    return (os.environ.get(env_token_key(server_id)) or "").strip()


def _normalize_aliases(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        contract = str(key or "").strip()
        tool = str(value or "").strip()
        if contract and tool:
            out[contract] = tool
    return out


def _normalize_server_id(raw: Any) -> str:
    server_id = str(raw or "").strip().lower()
    if not _SERVER_ID_RE.match(server_id):
        raise ValueError(
            "server id must be a lowercase identifier (letter, then letters/digits/_)"
        )
    return server_id


def _blob(workspace: "Workspace") -> dict[str, Any]:
    stored = _connectors(workspace).get(CONNECTOR_KEY)
    stored = dict(stored) if isinstance(stored, Mapping) else {}
    return stored


def _raw_servers(workspace: "Workspace") -> list[dict[str, Any]]:
    blob = _blob(workspace)
    raw = blob.get("servers")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping):
            out.append(dict(item))
    return out


def _public_server(stored: Mapping[str, Any]) -> dict[str, Any]:
    server_id = str(stored.get("id") or "").strip()
    url = str(stored.get("url") or "").strip().rstrip("/")
    token_blob = str(stored.get("token_encrypted") or "")
    env_url = _env_url(server_id) if server_id else ""
    env_token = _env_token(server_id) if server_id else ""
    token_set = bool(token_blob) or bool(env_token)
    effective_url = url or env_url
    if url or token_blob:
        credential_source: Optional[str] = "workspace"
    elif env_url or env_token:
        credential_source = "env"
    else:
        credential_source = None
    aliases = _normalize_aliases(stored.get("tool_aliases"))
    if not aliases and server_id:
        aliases = default_aliases(server_id)
    return {
        "id": server_id,
        "label": str(stored.get("label") or server_id),
        "transport": str(stored.get("transport") or DEFAULT_TRANSPORT),
        "url": effective_url,
        "url_stored": bool(url),
        "token_set": token_set,
        "enabled": bool(stored.get("enabled", True)),
        "tool_aliases": aliases,
        "configured": bool(effective_url),
        "credential_source": credential_source,
    }


def get_servers(workspace: "Workspace") -> dict[str, Any]:
    """Return the workspace MCP server list. Tokens are never echoed."""
    servers = [_public_server(item) for item in _raw_servers(workspace)]
    # Env-only servers (fixture / live URL without a stored row) stay invisible
    # until the operator or seed writes a row. Health still resolves via env
    # when the row exists with an empty url.
    return {"servers": servers}


def get_server(workspace: "Workspace", server_id: str) -> Optional[dict[str, Any]]:
    wanted = str(server_id or "").strip()
    for item in get_servers(workspace)["servers"]:
        if item.get("id") == wanted:
            return item
    return None


def get_decrypted_token(workspace: "Workspace", server_id: str) -> str:
    wanted = str(server_id or "").strip()
    for item in _raw_servers(workspace):
        if str(item.get("id") or "") != wanted:
            continue
        blob = str(item.get("token_encrypted") or "")
        if blob:
            token = _decrypt_secret(blob)
            if token:
                return token
        break
    return _env_token(wanted)


def resolve_server(workspace: "Workspace", server_id: str) -> dict[str, Any]:
    """Runtime view: url, token, aliases, credential_source. Fail closed."""
    public = get_server(workspace, server_id)
    if public is None:
        raise McpUnconfigured(f"MCP server {server_id!r} is not attached to this workspace")
    if not public.get("enabled", True):
        raise McpUnconfigured(f"MCP server {server_id!r} is disabled")
    if not public.get("configured"):
        raise McpUnconfigured(
            f"MCP server {server_id!r} is not configured "
            f"(set url or {env_url_key(server_id)})"
        )
    token = get_decrypted_token(workspace, str(public["id"]))
    return {
        **public,
        "token": token,
    }


def _persist_servers(db: DBSession, workspace: "Workspace", servers: list[dict[str, Any]]) -> dict[str, Any]:
    settings = dict(workspace.settings or {})
    connectors = dict(settings.get("connectors") or {})
    connectors[CONNECTOR_KEY] = {"servers": servers}
    settings["connectors"] = connectors
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return get_servers(workspace)


def _incoming_row(
    payload: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    server_id = _normalize_server_id(payload.get("id"))
    label = str(payload.get("label") or server_id).strip() or server_id
    transport = str(payload.get("transport") or DEFAULT_TRANSPORT).strip() or DEFAULT_TRANSPORT
    if transport not in ALLOWED_TRANSPORTS:
        raise ValueError(f"transport {transport!r} is not supported in v1 (http_sse only)")
    url = str(payload.get("url") or "").strip().rstrip("/")
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("url must start with http:// or https://")
    enabled = bool(payload.get("enabled", True))
    aliases = _normalize_aliases(payload.get("tool_aliases"))
    if not aliases:
        aliases = default_aliases(server_id)
    stored: dict[str, Any] = {
        "id": server_id,
        "label": label,
        "transport": transport,
        "url": url,
        "enabled": enabled,
        "tool_aliases": aliases,
    }
    token = payload.get("token")
    if token is not None and str(token) != "":
        stored["token_encrypted"] = _encrypt_secret(str(token))
    elif current and current.get("token_encrypted"):
        stored["token_encrypted"] = current["token_encrypted"]
    return stored


def replace_servers(
    db: DBSession, workspace: "Workspace", payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Replace the whole server list. Omit token on a row to keep the stored one."""
    raw = payload.get("servers")
    if raw is None:
        raise ValueError("servers is required")
    if not isinstance(raw, list):
        raise ValueError("servers must be a list")
    current_by_id = {str(item.get("id") or ""): item for item in _raw_servers(workspace)}
    stored: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("each server must be an object")
        row = _incoming_row(item, current=current_by_id.get(str(item.get("id") or "")))
        if row["id"] in seen:
            raise ValueError(f"duplicate MCP server id {row['id']!r}")
        seen.add(row["id"])
        stored.append(row)
    return _persist_servers(db, workspace, stored)


def upsert_server(
    db: DBSession, workspace: "Workspace", payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Insert or update one server. Token is write-only (omit to keep current)."""
    current_rows = _raw_servers(workspace)
    incoming = _incoming_row(
        payload,
        current=next(
            (
                row
                for row in current_rows
                if str(row.get("id") or "") == str(payload.get("id") or "").strip().lower()
            ),
            None,
        ),
    )
    replaced = False
    next_rows: list[dict[str, Any]] = []
    for row in current_rows:
        if str(row.get("id") or "") == incoming["id"]:
            next_rows.append(incoming)
            replaced = True
        else:
            next_rows.append(row)
    if not replaced:
        next_rows.append(incoming)
    return _persist_servers(db, workspace, next_rows)
