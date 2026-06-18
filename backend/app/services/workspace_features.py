"""Workspace family resolution and per-workspace feature toggles.

Families and feature flags historically lived in global config CSVs plus
substring matches on the workspace slug/name ("andritz" in slug). The
workspace settings are now the source of truth:

- ``settings["family"]`` — stamped family ("andritz" | "sentinel_ci" | "generic")
- ``settings["features"][<feature>]`` — boolean toggle per feature

The legacy substring heuristic and the global CSV fallbacks stay in place
until every deployment has been stamped (scripts/stamp_workspace_families.py),
then they can be retired.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

KNOWN_FAMILIES = {"andritz", "sentinel_ci", "generic"}


def _workspace_settings(workspace: Any) -> Mapping[str, Any]:
    raw = getattr(workspace, "settings", None)
    return raw if isinstance(raw, Mapping) else {}


def family_heuristic(workspace: Any) -> str:
    """Legacy substring heuristic — fallback only, do not extend."""
    slug = str(getattr(workspace, "slug", "") or "").lower()
    name = str(getattr(workspace, "name", "") or "").lower()
    if "andritz" in slug or "andritz" in name:
        return "andritz"
    if slug == "sentinel-ci" or "sentinel" in slug:
        return "sentinel_ci"
    return "generic"


def workspace_family(workspace: Any) -> str:
    """Resolve the workspace family: stamped settings first, heuristic fallback."""
    stamped = str(_workspace_settings(workspace).get("family") or "").strip().lower()
    if stamped in KNOWN_FAMILIES:
        return stamped
    return family_heuristic(workspace)


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
    allowed = {
        item.strip().lower()
        for item in str(csv_fallback or "").split(",")
        if item.strip()
    }
    return slug in allowed


def chat_document_upload_enabled(workspace: Any) -> bool:
    """Drop-and-ask upload in transverse chat. Enabled unless explicitly off."""
    features = _workspace_settings(workspace).get("features")
    if isinstance(features, Mapping) and "chat_document_upload" in features:
        return bool(features["chat_document_upload"])
    return True
