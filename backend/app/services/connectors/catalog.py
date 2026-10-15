"""Public projection of what Agentium can connect to.

The connector catalogue is product information, not a connection: it lists the
declared profiles and the official tool servers so a workspace member can see
the breadth of the platform even while the connector framework is switched off
in this deployment. It exposes no parameter, package, endpoint URL or secret,
and it never claims a qualification that the evidence does not establish.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from app.services.connectors.profiles import PROFILE_DIRECTORY, ConnectorProfile, list_profiles

TOOL_FAMILIES = frozenset({"mcp", "openapi"})
TOOL_CATALOG_PATH = PROFILE_DIRECTORY.parent / "mcp_catalog.yaml"


def profile_certification(profile: ConnectorProfile) -> str:
    """Catalogue level of a profile before any evidence store is consulted.

    Third-party tool families can never become native; every other profile
    stays unverified here. A verified or certified level comes only from the
    evidence attached to a connection, never from this static projection.
    """
    return "third_party" if profile.family in TOOL_FAMILIES else "unverified"


@lru_cache(maxsize=1)
def official_tool_servers() -> tuple[dict[str, Any], ...]:
    """Official publisher MCP servers, as declared in the versioned catalogue file."""
    catalog = yaml.safe_load(TOOL_CATALOG_PATH.read_text(encoding="utf-8")) or {}
    return tuple(dict(entry) for entry in catalog.get("servers", []))


def public_catalog(*, framework_enabled: bool) -> dict[str, Any]:
    profiles = [
        {
            "key": profile.key,
            "family": profile.family,
            "label_key": profile.label_key,
            "capabilities": profile.capabilities.model_dump(mode="json"),
            "certification": profile_certification(profile),
        }
        for profile in list_profiles()
    ]
    servers = [
        {
            "key": entry["key"],
            "publisher": entry["publisher"],
            "documentation": entry.get("documentation"),
            "auth_mode": entry.get("auth_mode"),
            "certification": "third_party",
        }
        for entry in official_tool_servers()
    ]
    return {
        "framework_enabled": framework_enabled,
        "profiles": profiles,
        "tool_servers": servers,
    }
