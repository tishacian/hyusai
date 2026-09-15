"""Workspace-scoped LLM portal configuration (routing, cloud keys, serving nodes).

Stored under ``workspace.settings["llm_portal"]``. Secrets use the same Fernet
envelope pattern as the HANA connector (``LLM_PORTAL_FERNET_KEY``, with a
plaintext envelope fallback when the key is unset in dev).
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Mapping, Optional

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = logging.getLogger(__name__)

ENV_MASTER_KEY = "LLM_PORTAL_FERNET_KEY"
SETTINGS_KEY = "llm_portal"
ENVELOPE_VERSION = 1

CLOUD_PROVIDERS = (
    "openai",
    "azure_openai",
    "azure_foundry",
    "openrouter",
    "anthropic",
    "gemini",
)

# Non-secret fields allowed per cloud provider (stored in clear).
_AZURE_META = ("endpoint", "api_version", "deployment")

# Providers whose non-secret endpoint metadata is stored alongside the key.
_ENDPOINT_PROVIDERS = ("azure_openai", "azure_foundry")


class EncryptionNotConfigured(RuntimeError):
    """Fernet master key missing or invalid."""


def _portal_blob(workspace: "Workspace") -> dict[str, Any]:
    settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    raw = settings.get(SETTINGS_KEY)
    return dict(raw) if isinstance(raw, Mapping) else {}


def _fernet_from_env():
    raw = os.environ.get(ENV_MASTER_KEY) or os.environ.get("HANA_CONNECTOR_FERNET_KEY")
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
        salt=b"llm_portal:v1",
        info=b"workspace_llm_portal",
    ).derive(raw_master)
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(plaintext: str) -> str:
    payload = plaintext.encode("utf-8")
    fernet = _fernet_from_env()
    if fernet is None:
        logger.warning(
            "%s not set; persisting LLM portal secret in PLAINTEXT envelope. "
            "Set %s before production.",
            ENV_MASTER_KEY,
            ENV_MASTER_KEY,
        )
        return json.dumps(
            {
                "v": ENVELOPE_VERSION,
                "plaintext": base64.b64encode(payload).decode("ascii"),
            }
        )
    return json.dumps(
        {
            "v": ENVELOPE_VERSION,
            "ciphertext": fernet.encrypt(payload).decode("ascii"),
        }
    )


def decrypt_secret(blob: str) -> str:
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
    ciphertext = envelope.get("ciphertext")
    if not ciphertext:
        return ""
    fernet = _fernet_from_env()
    if fernet is None:
        raise EncryptionNotConfigured(
            f"Encrypted secret present but {ENV_MASTER_KEY} is not configured"
        )
    return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")


def _persist(db: DBSession, workspace: "Workspace", portal: dict[str, Any]) -> dict[str, Any]:
    settings = dict(workspace.settings or {})
    settings[SETTINGS_KEY] = portal
    workspace.settings = settings
    # Real SQLAlchemy models need the JSON column marked dirty.
    if hasattr(workspace, "_sa_instance_state"):
        flag_modified(workspace, "settings")
        db.add(workspace)
        db.commit()
        db.refresh(workspace)
    return get_public_config(workspace)


# ---------------------------------------------------------------------------
# Public read
# ---------------------------------------------------------------------------


def get_routing(workspace: "Workspace") -> dict[str, Any]:
    from app.core.config import settings

    blob = _portal_blob(workspace)
    routing = blob.get("routing") if isinstance(blob.get("routing"), Mapping) else {}
    provider = str(routing.get("default_provider") or settings.default_provider or "openai")
    model = str(routing.get("default_model") or settings.default_model or "gpt-5")
    chain_raw = routing.get("fallback_chain")
    if isinstance(chain_raw, list):
        chain = [str(x) for x in chain_raw if str(x).strip()]
    else:
        chain = [provider]
        if "ollama" not in chain:
            chain.append("ollama")
    return {
        "default_provider": provider,
        "default_model": model,
        "fallback_chain": chain,
        "source": "workspace" if routing else "global",
    }


def get_cloud_credentials_public(workspace: "Workspace") -> list[dict[str, Any]]:
    """Credential status without secrets (write-only keys)."""
    blob = _portal_blob(workspace)
    stored = (
        blob.get("cloud_credentials") if isinstance(blob.get("cloud_credentials"), Mapping) else {}
    )
    rows: list[dict[str, Any]] = []
    for key in CLOUD_PROVIDERS:
        entry = stored.get(key) if isinstance(stored.get(key), Mapping) else {}
        meta: dict[str, Any] = {"key": key, "api_key_set": bool(entry.get("api_key_encrypted"))}
        if key in _ENDPOINT_PROVIDERS:
            for field in _AZURE_META:
                if entry.get(field):
                    meta[field] = entry[field]
        rows.append(meta)
    return rows


def get_decrypted_api_key(workspace: "Workspace", provider: str) -> Optional[str]:
    blob = _portal_blob(workspace)
    stored = (
        blob.get("cloud_credentials") if isinstance(blob.get("cloud_credentials"), Mapping) else {}
    )
    entry = stored.get(provider) if isinstance(stored.get(provider), Mapping) else {}
    enc = entry.get("api_key_encrypted")
    if not enc:
        return None
    try:
        return decrypt_secret(str(enc)) or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to decrypt workspace LLM key", provider=provider, error=str(exc))
        return None


def get_provider_meta(workspace: "Workspace", provider: str = "azure_openai") -> dict[str, str]:
    """Non-secret endpoint metadata (endpoint / api_version / deployment)."""
    blob = _portal_blob(workspace)
    stored = (
        blob.get("cloud_credentials") if isinstance(blob.get("cloud_credentials"), Mapping) else {}
    )
    entry = stored.get(provider) if isinstance(stored.get(provider), Mapping) else {}
    out: dict[str, str] = {}
    for field in _AZURE_META:
        if entry.get(field):
            out[field] = str(entry[field])
    return out


def get_runtime_provider_config(workspace_id: Optional[str], provider: str) -> dict[str, str]:
    """Resolve one workspace's private provider configuration for execution.

    The public model portal deliberately returns only credential status. Runtime
    callers use this short-lived lookup instead of copying API keys into chat or
    Run payloads, where secrets could be persisted in the execution ledger.
    """

    workspace_ref = str(workspace_id or "").strip()
    provider_key = str(provider or "").strip()
    if not workspace_ref or provider_key not in CLOUD_PROVIDERS:
        return {}

    # Local imports keep the configuration helpers usable in migrations and
    # focused tests that do not initialise the application database.
    from app.db.base import SessionLocal
    from app.models.workspace import Workspace

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.id == workspace_ref).one_or_none()
        if workspace is None:
            return {}
        resolved: dict[str, str] = {}
        api_key = get_decrypted_api_key(workspace, provider_key)
        if api_key:
            resolved["api_key"] = api_key
        if provider_key in _ENDPOINT_PROVIDERS:
            resolved.update(get_provider_meta(workspace, provider_key))
        return resolved
    finally:
        db.close()


def get_runtime_routing(workspace_id: Optional[str]) -> dict[str, Any]:
    """Resolve the authoritative model route for one workspace at runtime.

    Run-engine Skills only carry the workspace id in their ephemeral context.
    This helper gives those callers the same server-owned provider/model pair
    used by Chat without copying credentials or mutable settings into a Run.
    """

    workspace_ref = str(workspace_id or "").strip()
    if not workspace_ref:
        return {}

    from app.db.base import SessionLocal
    from app.models.workspace import Workspace

    db = SessionLocal()
    try:
        workspace = db.query(Workspace).filter(Workspace.id == workspace_ref).one_or_none()
        return get_routing(workspace) if workspace is not None else {}
    finally:
        db.close()


def get_azure_meta(workspace: "Workspace") -> dict[str, str]:
    return get_provider_meta(workspace, "azure_openai")


def list_serving_node_configs(workspace: "Workspace") -> list[dict[str, Any]]:
    """Decrypted serving-node configs from workspace (not env)."""
    blob = _portal_blob(workspace)
    raw = blob.get("serving_nodes")
    if not isinstance(raw, list):
        return []
    nodes: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        base_url = str(item.get("base_url") or "").strip().rstrip("/")
        if not name or not base_url:
            continue
        token = ""
        enc = item.get("token_encrypted")
        if enc:
            try:
                token = decrypt_secret(str(enc))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to decrypt serving node token", name=name, error=str(exc))
        nodes.append({"name": name, "base_url": base_url, "token": token})
    return nodes


def list_serving_nodes_public(workspace: "Workspace") -> list[dict[str, Any]]:
    blob = _portal_blob(workspace)
    raw = blob.get("serving_nodes")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or "").strip()
        base_url = str(item.get("base_url") or "").strip().rstrip("/")
        if name and base_url:
            out.append(
                {
                    "name": name,
                    "base_url": base_url,
                    "token_set": bool(item.get("token_encrypted")),
                }
            )
    return out


def get_public_config(workspace: "Workspace") -> dict[str, Any]:
    return {
        "routing": get_routing(workspace),
        "cloud_credentials": get_cloud_credentials_public(workspace),
        "serving_nodes": list_serving_nodes_public(workspace),
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def set_routing(
    db: DBSession,
    workspace: "Workspace",
    *,
    default_provider: str,
    default_model: str,
    fallback_chain: Optional[list[str]] = None,
) -> dict[str, Any]:
    provider = (default_provider or "").strip()
    model = (default_model or "").strip()
    if not provider or not model:
        raise ValueError("default_provider and default_model are required")
    from app.services.model_plane.providers import RUNTIME_PROVIDERS, model_compatibility

    if provider not in RUNTIME_PROVIDERS:
        raise ValueError("This provider is not supported by the workspace text generation runtime")
    from app.services.model_plane.execution import resolve_model_execution
    resolved = resolve_model_execution(workspace, provider=provider, model=model)
    model = resolved.model
    if model_compatibility(provider, model) == "other":
        raise ValueError("Choose a text generation model, not an embedding, image or audio model")
    chain = list(dict.fromkeys(str(x).strip() for x in (fallback_chain or []) if str(x).strip()))
    if any(item not in RUNTIME_PROVIDERS for item in chain):
        raise ValueError("The fallback chain contains an unsupported text generation provider")
    if len(chain) > len(RUNTIME_PROVIDERS):
        raise ValueError("The fallback chain is too long")
    if provider not in chain:
        chain = [provider, *chain]
    portal = _portal_blob(workspace)
    portal["routing"] = {
        "default_provider": provider,
        "default_model": model,
        "fallback_chain": chain,
    }
    return _persist(db, workspace, portal)


def set_cloud_credential(
    db: DBSession,
    workspace: "Workspace",
    provider: str,
    *,
    api_key: Optional[str] = None,
    clear_api_key: bool = False,
    endpoint: Optional[str] = None,
    api_version: Optional[str] = None,
    deployment: Optional[str] = None,
) -> dict[str, Any]:
    key = (provider or "").strip()
    if key not in CLOUD_PROVIDERS:
        raise ValueError(f"Unsupported provider {provider!r}")
    portal = _portal_blob(workspace)
    creds = (
        dict(portal.get("cloud_credentials"))
        if isinstance(portal.get("cloud_credentials"), Mapping)
        else {}
    )
    entry = dict(creds.get(key)) if isinstance(creds.get(key), Mapping) else {}

    if clear_api_key:
        entry.pop("api_key_encrypted", None)
    elif api_key is not None and str(api_key).strip():
        entry["api_key_encrypted"] = encrypt_secret(str(api_key).strip())

    if key in _ENDPOINT_PROVIDERS:
        if endpoint is not None:
            entry["endpoint"] = endpoint.strip().rstrip("/")
        if api_version is not None:
            entry["api_version"] = api_version.strip()
        if deployment is not None:
            entry["deployment"] = deployment.strip()

    if entry:
        creds[key] = entry
    else:
        creds.pop(key, None)
    portal["cloud_credentials"] = creds
    return _persist(db, workspace, portal)


def upsert_serving_node(
    db: DBSession,
    workspace: "Workspace",
    *,
    name: str,
    base_url: str,
    token: Optional[str] = None,
) -> dict[str, Any]:
    node_name = (name or "").strip()
    url = (base_url or "").strip().rstrip("/")
    if not node_name or not url:
        raise ValueError("name and base_url are required")
    portal = _portal_blob(workspace)
    nodes = list(portal.get("serving_nodes") or [])
    if not isinstance(nodes, list):
        nodes = []
    updated = False
    new_nodes: list[dict[str, Any]] = []
    for item in nodes:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("name") or "").strip() == node_name:
            row = {
                "name": node_name,
                "base_url": url,
                "token_encrypted": item.get("token_encrypted"),
            }
            if token is not None and str(token).strip():
                row["token_encrypted"] = encrypt_secret(str(token).strip())
            new_nodes.append(row)
            updated = True
        else:
            new_nodes.append(dict(item))
    if not updated:
        row = {"name": node_name, "base_url": url}
        if token is not None and str(token).strip():
            row["token_encrypted"] = encrypt_secret(str(token).strip())
        new_nodes.append(row)
    portal["serving_nodes"] = new_nodes
    return _persist(db, workspace, portal)


def delete_serving_node(
    db: DBSession,
    workspace: "Workspace",
    name: str,
) -> dict[str, Any]:
    node_name = (name or "").strip()
    if not node_name:
        raise ValueError("name is required")
    portal = _portal_blob(workspace)
    nodes = list(portal.get("serving_nodes") or [])
    if not isinstance(nodes, list):
        nodes = []
    portal["serving_nodes"] = [
        dict(item)
        for item in nodes
        if isinstance(item, Mapping) and str(item.get("name") or "").strip() != node_name
    ]
    return _persist(db, workspace, portal)
