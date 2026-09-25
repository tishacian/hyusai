"""Workspace settings never hand a connector secret to the browser.

Connectors keep their secrets in ``workspace.settings``: an envelope under a
``*_encrypted`` key (SAP HANA password, RPA token, MCP tokens and OAuth
secret, model portal keys and node tokens), or a plain value under a secret's
own name (a workspace SMTP password). Settings leave the API without any of
them, whatever the caller's role; each connector's own route says whether its
secret is set. A settings write cannot carry one, and keeps those it could not
have seen.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from app.services.connectors.generic import SETTINGS_KEY as GENERIC_CONNECTORS_KEY

logger = logging.getLogger(__name__)

ENCRYPTED_SUFFIX = "_encrypted"
PLAIN_SECRET_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "secrets",
        "client_secret",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "auth_token",
        "bot_token",
        "private_key",
        "secret_access_key",
    }
)
# A list item keeps its secrets across a write when the request still lists it
# under the same id (MCP servers) or, without one, the same name (serving nodes).
LIST_ITEM_KEYS = ("id", "name")


def is_secret_key(key: Any) -> bool:
    name = str(key).strip().lower()
    return name.endswith(ENCRYPTED_SUFFIX) or name in PLAIN_SECRET_KEYS


def _without_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _without_secrets(item)
            for key, item in value.items()
            if not is_secret_key(key)
        }
    if isinstance(value, list):
        return [_without_secrets(item) for item in value]
    return value


def public_workspace_settings(settings: Any) -> dict[str, Any]:
    """Workspace settings as any member, admin included, reads them."""
    if not isinstance(settings, Mapping):
        return {}
    public = _without_secrets(settings)
    public.pop(GENERIC_CONNECTORS_KEY, None)
    return public


def secret_paths(settings: Any, path: str = "settings") -> list[str]:
    """Where a settings payload names a secret: paths only, never a value."""
    if isinstance(settings, Mapping):
        found: list[str] = []
        for key, item in settings.items():
            child = f"{path}.{key}"
            if is_secret_key(key):
                found.append(child)
            else:
                found.extend(secret_paths(item, child))
        return found
    if isinstance(settings, list):
        return [
            found
            for index, item in enumerate(settings)
            for found in secret_paths(item, f"{path}[{index}]")
        ]
    return []


def _item_key(item: Any) -> tuple[str, str] | None:
    if not isinstance(item, Mapping):
        return None
    for field in LIST_ITEM_KEYS:
        value = item.get(field)
        if isinstance(value, str) and value:
            return field, value
    return None


def with_stored_secrets(stored: Any, requested: Any) -> Any:
    """``requested`` with the secrets ``stored`` keeps at the same place.

    Objects match key by key, list items by ``id``, else ``name``. An object or
    item the request drops takes its secrets with it.
    """
    if isinstance(stored, Mapping) and isinstance(requested, Mapping):
        merged = dict(requested)
        for key, value in stored.items():
            if is_secret_key(key):
                merged[key] = value
            elif key in requested:
                merged[key] = with_stored_secrets(value, requested[key])
        return merged
    if isinstance(stored, list) and isinstance(requested, list):
        by_key: dict[tuple[str, str], Any] = {}
        for item in stored:
            key = _item_key(item)
            if key is not None:
                by_key.setdefault(key, item)
        return [with_stored_secrets(by_key.get(_item_key(item)), item) for item in requested]
    return requested


def public_checkpoint(checkpoint: Any) -> Any:
    """A run checkpoint whose variable pool holds only public workspace settings.

    A paused run's checkpoint carries its pool, and pools seeded by earlier
    versions copied the workspace settings with their secret envelopes.
    """
    state = checkpoint.get("state") if isinstance(checkpoint, Mapping) else None
    pool = state.get("pool") if isinstance(state, Mapping) else None
    workspace = pool.get("workspace") if isinstance(pool, Mapping) else None
    if not isinstance(workspace, Mapping) or "settings" not in workspace:
        return checkpoint
    settings = public_workspace_settings(workspace["settings"])
    return {
        **checkpoint,
        "state": {**state, "pool": {**pool, "workspace": {**workspace, "settings": settings}}},
    }


def warn_unencrypted_connector_secrets() -> list[str]:
    """Warn, naming keys and never values, for each connector with no Fernet key.

    Such a connector stores new secrets in a plaintext envelope, readable by
    anyone who reads the database. It still works, so startup goes on.
    """
    from app.services.connectors.generic import service as generic_service
    from app.services.connectors.hana import service as hana_service
    from app.services.connectors.mcp import service as mcp_service
    from app.services.connectors.rpa import service as rpa_service
    from app.services.model_plane import workspace_config

    # Each connector's _fernet_from_env reads these, in this order.
    master_keys = (
        ("SAP HANA", (hana_service.ENV_MASTER_KEY,)),
        (
            "RPA Bridge",
            (rpa_service.ENV_MASTER_KEY, rpa_service.ENV_MASTER_KEY_FALLBACK),
        ),
        ("MCP", (mcp_service.ENV_MASTER_KEY, mcp_service.ENV_MASTER_KEY_FALLBACK)),
        (
            "model portal",
            (workspace_config.ENV_MASTER_KEY, workspace_config.ENV_MASTER_KEY_FALLBACK),
        ),
        (
            "catalog connectors",
            (generic_service.ENV_MASTER_KEY, generic_service.ENV_MASTER_KEY_FALLBACK),
        ),
    )
    unencrypted: list[str] = []
    for connector, names in master_keys:
        if any((os.environ.get(name) or "").strip() for name in names):
            continue
        unencrypted.append(connector)
        logger.warning(
            "No Fernet key for %s secrets (set %s): they are stored WITHOUT encryption.",
            connector,
            " or ".join(names),
        )
    return unencrypted
