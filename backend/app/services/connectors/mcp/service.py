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
    ALLOWED_AUTH_MODES,
    ALLOWED_TRANSPORTS,
    AUTH_INHERIT,
    AUTH_OAUTH,
    DEFAULT_AUTH_MODE,
    DEFAULT_TRANSPORT,
    default_aliases,
    normalize_auth_mode,
    normalize_transport,
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


ENV_SHARED_OAUTH_TOKEN_URL = "MCP_OAUTH_TOKEN_URL"
ENV_SHARED_OAUTH_CLIENT_ID = "MCP_OAUTH_CLIENT_ID"
ENV_SHARED_OAUTH_CLIENT_SECRET = "MCP_OAUTH_CLIENT_SECRET"
ENV_SHARED_OAUTH_SCOPE = "MCP_OAUTH_SCOPE"


def env_url_key(server_id: str) -> str:
    return f"MCP_{str(server_id).strip().upper()}_URL"


def env_token_key(server_id: str) -> str:
    return f"MCP_{str(server_id).strip().upper()}_TOKEN"


def env_oauth_token_url_key(server_id: str) -> str:
    return f"MCP_{str(server_id).strip().upper()}_OAUTH_TOKEN_URL"


def env_oauth_client_id_key(server_id: str) -> str:
    return f"MCP_{str(server_id).strip().upper()}_OAUTH_CLIENT_ID"


def env_oauth_client_secret_key(server_id: str) -> str:
    return f"MCP_{str(server_id).strip().upper()}_OAUTH_CLIENT_SECRET"


def _env_url(server_id: str) -> str:
    return (os.environ.get(env_url_key(server_id)) or "").strip().rstrip("/")


def _env_token(server_id: str) -> str:
    return (os.environ.get(env_token_key(server_id)) or "").strip()


def _env_oauth_field(server_id: str, suffix: str, shared_env: str) -> str:
    per_server = (os.environ.get(f"MCP_{str(server_id).strip().upper()}_{suffix}") or "").strip()
    if per_server:
        return per_server
    return (os.environ.get(shared_env) or "").strip()


def _http_url(raw: Any, *, field: str) -> str:
    url = str(raw or "").strip().rstrip("/")
    if url and not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(f"{field} must start with http:// or https://")
    return url


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


def _raw_shared_auth(workspace: "Workspace") -> dict[str, Any]:
    raw = _blob(workspace).get("shared_auth")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _shared_oauth_from_env() -> dict[str, str]:
    return {
        "oauth_token_url": (os.environ.get(ENV_SHARED_OAUTH_TOKEN_URL) or "").strip().rstrip("/"),
        "oauth_client_id": (os.environ.get(ENV_SHARED_OAUTH_CLIENT_ID) or "").strip(),
        "oauth_client_secret": (os.environ.get(ENV_SHARED_OAUTH_CLIENT_SECRET) or "").strip(),
        "oauth_scope": (os.environ.get(ENV_SHARED_OAUTH_SCOPE) or "").strip(),
    }


def get_decrypted_oauth_secret(workspace: "Workspace", server_id: str = "") -> str:
    wanted = str(server_id or "").strip()
    if wanted:
        for item in _raw_servers(workspace):
            if str(item.get("id") or "") != wanted:
                continue
            blob = str(item.get("oauth_client_secret_encrypted") or "")
            if blob:
                secret = _decrypt_secret(blob)
                if secret:
                    return secret
            env_secret = (os.environ.get(env_oauth_client_secret_key(wanted)) or "").strip()
            if env_secret:
                return env_secret
            break
    blob = str(_raw_shared_auth(workspace).get("oauth_client_secret_encrypted") or "")
    if blob:
        secret = _decrypt_secret(blob)
        if secret:
            return secret
    return _shared_oauth_from_env()["oauth_client_secret"]


def _public_shared_auth(workspace: "Workspace") -> dict[str, Any]:
    stored = _raw_shared_auth(workspace)
    env = _shared_oauth_from_env()
    token_url = str(stored.get("oauth_token_url") or "").strip().rstrip("/") or env["oauth_token_url"]
    client_id = str(stored.get("oauth_client_id") or "").strip() or env["oauth_client_id"]
    scope = str(stored.get("oauth_scope") or "").strip() or env["oauth_scope"]
    secret_set = bool(stored.get("oauth_client_secret_encrypted")) or bool(env["oauth_client_secret"])
    if (
        stored.get("oauth_token_url")
        or stored.get("oauth_client_id")
        or stored.get("oauth_client_secret_encrypted")
    ):
        credential_source: Optional[str] = "workspace"
    elif env["oauth_token_url"] or env["oauth_client_id"] or env["oauth_client_secret"]:
        credential_source = "env"
    else:
        credential_source = None
    return {
        "auth_mode": AUTH_OAUTH,
        "oauth_token_url": token_url,
        "oauth_client_id": client_id,
        "oauth_scope": scope,
        "secret_set": secret_set,
        "credential_source": credential_source,
    }


def _oauth_fields_for_server(
    stored: Mapping[str, Any],
    *,
    server_id: str,
    shared: Mapping[str, Any],
    inherit: bool,
) -> dict[str, Any]:
    env_token_url = _env_oauth_field(server_id, "OAUTH_TOKEN_URL", ENV_SHARED_OAUTH_TOKEN_URL)
    env_client_id = _env_oauth_field(server_id, "OAUTH_CLIENT_ID", ENV_SHARED_OAUTH_CLIENT_ID)
    env_secret = _env_oauth_field(server_id, "OAUTH_CLIENT_SECRET", ENV_SHARED_OAUTH_CLIENT_SECRET)
    stored_token_url = str(stored.get("oauth_token_url") or "").strip().rstrip("/")
    stored_client_id = str(stored.get("oauth_client_id") or "").strip()
    stored_scope = str(stored.get("oauth_scope") or "").strip()
    stored_secret = bool(stored.get("oauth_client_secret_encrypted"))
    if inherit:
        token_url = stored_token_url or str(shared.get("oauth_token_url") or "") or env_token_url
        client_id = stored_client_id or str(shared.get("oauth_client_id") or "") or env_client_id
        scope = stored_scope or str(shared.get("oauth_scope") or "")
        secret_set = stored_secret or bool(shared.get("secret_set")) or bool(env_secret)
    else:
        token_url = stored_token_url or env_token_url
        client_id = stored_client_id or env_client_id
        scope = stored_scope
        secret_set = stored_secret or bool(env_secret)
    return {
        "oauth_token_url": token_url,
        "oauth_client_id": client_id,
        "oauth_scope": scope,
        "oauth_secret_set": secret_set,
    }


def _public_server(stored: Mapping[str, Any], *, shared: Mapping[str, Any]) -> dict[str, Any]:
    server_id = str(stored.get("id") or "").strip()
    url = str(stored.get("url") or "").strip().rstrip("/")
    token_blob = str(stored.get("token_encrypted") or "")
    env_url = _env_url(server_id) if server_id else ""
    env_token = _env_token(server_id) if server_id else ""
    token_set = bool(token_blob) or bool(env_token)
    effective_url = url or env_url
    auth_mode = normalize_auth_mode(stored.get("auth_mode") or DEFAULT_AUTH_MODE)
    oauth = _oauth_fields_for_server(
        stored, server_id=server_id, shared=shared, inherit=auth_mode == AUTH_INHERIT
    )
    if url or token_blob or stored.get("oauth_client_secret_encrypted"):
        credential_source: Optional[str] = "workspace"
    elif env_url or env_token:
        credential_source = "env"
    elif auth_mode == AUTH_INHERIT and shared.get("credential_source"):
        credential_source = str(shared.get("credential_source"))
    elif oauth["oauth_token_url"] or oauth["oauth_client_id"] or oauth["oauth_secret_set"]:
        credential_source = "env"
    else:
        credential_source = None
    aliases = _normalize_aliases(stored.get("tool_aliases"))
    if not aliases and server_id:
        aliases = default_aliases(server_id)
    if auth_mode in {AUTH_OAUTH, AUTH_INHERIT}:
        configured = bool(
            effective_url
            and oauth["oauth_token_url"]
            and oauth["oauth_client_id"]
            and oauth["oauth_secret_set"]
        )
    else:
        configured = bool(effective_url)
    return {
        "id": server_id,
        "label": str(stored.get("label") or server_id),
        "transport": normalize_transport(stored.get("transport") or DEFAULT_TRANSPORT),
        "url": effective_url,
        "url_stored": bool(url),
        "token_set": token_set,
        "enabled": bool(stored.get("enabled", True)),
        "tool_aliases": aliases,
        "auth_mode": auth_mode,
        "oauth_token_url": oauth["oauth_token_url"],
        "oauth_client_id": oauth["oauth_client_id"],
        "oauth_scope": oauth["oauth_scope"],
        "oauth_secret_set": oauth["oauth_secret_set"],
        "configured": configured,
        "credential_source": credential_source,
    }


def get_servers(workspace: "Workspace") -> dict[str, Any]:
    """Return the workspace MCP server list. Secrets are never echoed."""
    shared = _public_shared_auth(workspace)
    servers = [_public_server(item, shared=shared) for item in _raw_servers(workspace)]
    # Env-only servers (fixture / live URL without a stored row) stay invisible
    # until the operator or seed writes a row. Health still resolves via env
    # when the row exists with an empty url.
    return {"servers": servers, "shared_auth": shared}


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
    """Runtime view: url, token / oauth, aliases, credential_source. Fail closed."""
    public = get_server(workspace, server_id)
    if public is None:
        raise McpUnconfigured(f"MCP server {server_id!r} is not attached to this workspace")
    if not public.get("enabled", True):
        raise McpUnconfigured(f"MCP server {server_id!r} is disabled")
    auth_mode = str(public.get("auth_mode") or DEFAULT_AUTH_MODE)
    if not public.get("url"):
        raise McpUnconfigured(
            f"MCP server {server_id!r} is not configured "
            f"(set url or {env_url_key(server_id)})"
        )
    if auth_mode in {AUTH_OAUTH, AUTH_INHERIT}:
        if not public.get("oauth_token_url") or not public.get("oauth_client_id"):
            raise McpUnconfigured(
                f"MCP server {server_id!r} is missing OAuth client-credentials "
                f"(oauth_token_url / oauth_client_id, or {ENV_SHARED_OAUTH_TOKEN_URL} / "
                f"{ENV_SHARED_OAUTH_CLIENT_ID})"
            )
        secret = get_decrypted_oauth_secret(workspace, str(public["id"]))
        if not secret:
            raise McpUnconfigured(
                f"MCP server {server_id!r} is missing OAuth client secret "
                f"(set oauth_client_secret or {ENV_SHARED_OAUTH_CLIENT_SECRET})"
            )
        return {
            **public,
            "token": get_decrypted_token(workspace, str(public["id"])),
            "oauth_client_secret": secret,
        }
    if not public.get("configured"):
        raise McpUnconfigured(
            f"MCP server {server_id!r} is not configured "
            f"(set url or {env_url_key(server_id)})"
        )
    return {
        **public,
        "token": get_decrypted_token(workspace, str(public["id"])),
    }


def _persist_blob(
    db: DBSession,
    workspace: "Workspace",
    servers: list[dict[str, Any]],
    shared_auth: Mapping[str, Any] | None = None,
    *,
    write_shared: bool = False,
) -> dict[str, Any]:
    settings = dict(workspace.settings or {})
    connectors = dict(settings.get("connectors") or {})
    current = dict(connectors.get(CONNECTOR_KEY) or {})
    blob: dict[str, Any] = {
        "servers": servers,
        "shared_auth": dict(current.get("shared_auth") or {}),
    }
    if write_shared:
        blob["shared_auth"] = dict(shared_auth or {})
    connectors[CONNECTOR_KEY] = blob
    settings["connectors"] = connectors
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return get_servers(workspace)


def _persist_servers(db: DBSession, workspace: "Workspace", servers: list[dict[str, Any]]) -> dict[str, Any]:
    return _persist_blob(db, workspace, servers)


def _incoming_shared_auth(
    payload: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    token_url = _http_url(payload.get("oauth_token_url"), field="oauth_token_url")
    client_id = str(payload.get("oauth_client_id") or "").strip()
    scope = str(payload.get("oauth_scope") or "").strip()
    stored: dict[str, Any] = {
        "auth_mode": AUTH_OAUTH,
        "oauth_token_url": token_url,
        "oauth_client_id": client_id,
        "oauth_scope": scope,
    }
    secret = payload.get("oauth_client_secret")
    if secret is not None and str(secret) != "":
        stored["oauth_client_secret_encrypted"] = _encrypt_secret(str(secret))
    elif current and current.get("oauth_client_secret_encrypted"):
        stored["oauth_client_secret_encrypted"] = current["oauth_client_secret_encrypted"]
    return stored


def _incoming_row(
    payload: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    server_id = _normalize_server_id(payload.get("id"))
    label = str(payload.get("label") or server_id).strip() or server_id
    transport = normalize_transport(payload.get("transport") or DEFAULT_TRANSPORT)
    if transport not in ALLOWED_TRANSPORTS:
        raise ValueError(
            f"transport {transport!r} is not supported "
            f"(allowed: {', '.join(sorted(ALLOWED_TRANSPORTS))})"
        )
    url = _http_url(payload.get("url"), field="url")
    auth_mode = normalize_auth_mode(payload.get("auth_mode") or DEFAULT_AUTH_MODE)
    if auth_mode not in ALLOWED_AUTH_MODES:
        raise ValueError(
            f"auth_mode {auth_mode!r} is not supported "
            f"(allowed: {', '.join(sorted(ALLOWED_AUTH_MODES))})"
        )
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
        "auth_mode": auth_mode,
        "oauth_token_url": _http_url(payload.get("oauth_token_url"), field="oauth_token_url"),
        "oauth_client_id": str(payload.get("oauth_client_id") or "").strip(),
        "oauth_scope": str(payload.get("oauth_scope") or "").strip(),
    }
    token = payload.get("token")
    if token is not None and str(token) != "":
        stored["token_encrypted"] = _encrypt_secret(str(token))
    elif current and current.get("token_encrypted"):
        stored["token_encrypted"] = current["token_encrypted"]
    secret = payload.get("oauth_client_secret")
    if secret is not None and str(secret) != "":
        stored["oauth_client_secret_encrypted"] = _encrypt_secret(str(secret))
    elif current and current.get("oauth_client_secret_encrypted"):
        stored["oauth_client_secret_encrypted"] = current["oauth_client_secret_encrypted"]
    return stored


def replace_servers(
    db: DBSession, workspace: "Workspace", payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Replace the whole server list. Omit token / oauth secret to keep the stored one."""
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
    write_shared = "shared_auth" in payload
    shared_raw = payload.get("shared_auth") if write_shared else None
    if write_shared and shared_raw is not None and not isinstance(shared_raw, Mapping):
        raise ValueError("shared_auth must be an object")
    shared_stored = (
        _incoming_shared_auth(shared_raw or {}, current=_raw_shared_auth(workspace))
        if write_shared
        else None
    )
    return _persist_blob(
        db,
        workspace,
        stored,
        shared_stored,
        write_shared=write_shared,
    )


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
