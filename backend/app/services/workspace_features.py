"""Workspace family resolution and per-workspace feature toggles.

Families and feature flags historically lived in global config CSVs plus
substring matches on the workspace slug/name ("andritz" in slug). Migration
058 stamps the legacy result once; runtime settings are now the source of
truth:

- ``settings["family"]`` — canonical stamped family (``WorkspaceFamily``)
- ``settings["features"][<feature>]`` — boolean toggle per feature

An absent or malformed family is deliberately fail-safe ``generic``. Runtime
code must never infer a business specialization from a mutable slug or name.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.schemas.canonical import WorkspaceFamily

KNOWN_FAMILIES = frozenset(family.value for family in WorkspaceFamily)


def _workspace_settings(workspace: Any) -> Mapping[str, Any]:
    raw = getattr(workspace, "settings", None)
    return raw if isinstance(raw, Mapping) else {}


def workspace_family(workspace: Any) -> str:
    """Resolve only a canonical stamped family, otherwise fail safe."""
    stamped = str(_workspace_settings(workspace).get("family") or "").strip().lower()
    if stamped in KNOWN_FAMILIES:
        return stamped
    return WorkspaceFamily.generic.value


def feature_enabled(workspace: Any, feature: str, *, csv_fallback: str = "") -> bool:
    """Per-workspace feature toggle with the legacy global CSV as fallback.

    ``workspace.settings["features"][feature]`` wins when present; otherwise
    the slug is matched (exact, case-insensitive) against the comma-separated
    global config value the flag historically used.
    """
    features = _workspace_settings(workspace).get("features")
    if isinstance(features, Mapping) and feature in features:
        return bool(features[feature])
    slug = str(getattr(workspace, "slug", "") or "").strip().lower()
    allowed = {item.strip().lower() for item in str(csv_fallback or "").split(",") if item.strip()}
    return slug in allowed


def chat_document_upload_enabled(workspace: Any) -> bool:
    """Drop-and-ask upload in transverse chat. Enabled unless explicitly off."""
    features = _workspace_settings(workspace).get("features")
    if isinstance(features, Mapping) and "chat_document_upload" in features:
        return bool(features["chat_document_upload"])
    return True
