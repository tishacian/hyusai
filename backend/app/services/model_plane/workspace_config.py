"""Workspace-scoped LLM portal configuration (routing, cloud keys, serving nodes).

Stored under ``workspace.settings["llm_portal"]``. Secrets use the same Fernet
envelope pattern as the HANA connector (``LLM_PORTAL_FERNET_KEY``, with a
plaintext envelope fallback when the key is unset in dev).
"""

from __future__ import annotations

import base64
import json
import os
from typing import TYPE_CHECKING, Any, Mapping, Optional

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = get_logger(__name__)

ENV_MASTER_KEY = "LLM_PORTAL_FERNET_KEY"
ENV_MASTER_KEY_FALLBACK = "HANA_CONNECTOR_FERNET_KEY"
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
    raw = os.environ.get(ENV_MASTER_KEY) or os.environ.get(ENV_MASTER_KEY_FALLBACK)
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
            "Persisting LLM portal secret in a PLAINTEXT envelope; set the key before production",
            key=ENV_MASTER_KEY,
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
    named_routes_raw = routing.get("named_routes")
    named_routes = dict(named_routes_raw) if isinstance(named_routes_raw, Mapping) else {}
    return {
        "default_provider": provider,
        "default_model": model,
        "fallback_chain": chain,
        "named_routes": named_routes,
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
    named_routes: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    provider = (default_provider or "").strip()
    model = (default_model or "").strip()
    if not provider or not model:
        raise ValueError("default_provider and default_model are required")
    from app.services.model_plane.execution import routable_runtime_providers
    from app.services.model_plane.providers import model_compatibility

    supported_providers = routable_runtime_providers(workspace)

    if provider not in supported_providers:
        raise ValueError("This provider is not supported by the workspace text generation runtime")
    from app.services.model_plane.execution import resolve_model_execution

    resolved = resolve_model_execution(workspace, provider=provider, model=model)
    model = resolved.model
    if model_compatibility(provider, model) == "other":
        raise ValueError("Choose a text generation model, not an embedding, image or audio model")
    chain = list(dict.fromkeys(str(x).strip() for x in (fallback_chain or []) if str(x).strip()))
    if any(item not in supported_providers for item in chain):
        raise ValueError("The fallback chain contains an unsupported text generation provider")
    if len(chain) > len(supported_providers):
        raise ValueError("The fallback chain is too long")
    if provider not in chain:
        chain = [provider, *chain]
    routes: dict[str, dict[str, Any]] = {}
    for raw_name, raw_route in (named_routes or {}).items():
        name = str(raw_name or "").strip()
        route = raw_route if isinstance(raw_route, Mapping) else {}
        route_provider = str(route.get("provider") or "").strip()
        route_model = str(route.get("model") or "").strip()
        if not name or name in supported_providers or name == "workspace":
            raise ValueError("A model route name must be non-empty and reserved")
        if route_provider not in supported_providers:
            raise ValueError(f"Model route {name!r} uses an unsupported provider")
        resolved_route = resolve_model_execution(
            workspace,
            provider=route_provider,
            model=route_model,
        )
        if model_compatibility(route_provider, resolved_route.model) == "other":
            raise ValueError(f"Model route {name!r} is not a text generation model")
        route_chain = list(
            dict.fromkeys(
                str(item).strip()
                for item in (route.get("fallback_chain") or [])
                if str(item).strip()
            )
        )
        if any(item not in supported_providers for item in route_chain):
            raise ValueError(f"Model route {name!r} has an unsupported fallback")
        routes[name] = {
            "provider": route_provider,
            "model": resolved_route.model,
            "fallback_chain": route_chain,
        }
    portal = _portal_blob(workspace)
    portal["routing"] = {
        "default_provider": provider,
        "default_model": model,
        "fallback_chain": chain,
        "named_routes": routes,
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
