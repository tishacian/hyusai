"""Canonical action-pack identifiers and configuration validation.

The registry owns the manifests, while this dependency-free module owns the
identifiers accepted at API/configuration boundaries. Keeping it free of
models and FastAPI avoids import cycles for auth, systems and admin routers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from enum import Enum
from typing import Any


class ActionPack(str, Enum):
    global_voice_v1 = "global_voice_v1"
    andritz_industrial_v1 = "andritz_industrial_v1"
    sentinel_ci_aya_v1 = "sentinel_ci_aya_v1"
    sentinel_ci_aya_security_v1 = "sentinel_ci_aya_security_v1"
    octave_mission_room_v1 = "octave_mission_room_v1"
    octave_security_v1 = "octave_security_v1"


ACTION_PACK_IDS: tuple[str, ...] = tuple(item.value for item in ActionPack)
ACTION_PACK_ID_SET = frozenset(ACTION_PACK_IDS)


def normalize_action_pack_ids(value: Any, *, path: str) -> list[str]:
    """Validate and de-duplicate a JSON action-pack list, preserving order."""

    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{path} must be an array of action-pack identifiers")

    normalized: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise ValueError(f"{path} must contain only strings")
        pack_id = raw.strip()
        if pack_id not in ACTION_PACK_ID_SET:
            raise ValueError(f"Unknown action pack at {path}: {pack_id or '<empty>'}")
        if pack_id not in normalized:
            normalized.append(pack_id)
    return normalized


def _validate_pack_field(config: Mapping[str, Any], key: str, *, path: str) -> None:
    if key in config:
        normalize_action_pack_ids(config[key], path=f"{path}.{key}")


def _validate_action_config(value: Any, *, path: str) -> None:
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    _validate_pack_field(value, "enabled_packs", path=path)
    _validate_pack_field(value, "hidden_packs", path=path)
    _validate_pack_field(value, "action_packs", path=path)


def _normalize_action_config(value: Any, *, path: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    normalized = deepcopy(dict(value))
    for key in ("enabled_packs", "hidden_packs", "action_packs"):
        if key in normalized:
            normalized[key] = normalize_action_pack_ids(
                normalized[key],
                path=f"{path}.{key}",
            )
    return normalized


def normalize_workspace_action_pack_settings(
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Return workspace settings with every declared pack list canonicalized."""

    normalized = deepcopy(dict(settings))
    if "actions" in normalized:
        normalized["actions"] = _normalize_action_config(
            normalized.get("actions"),
            path="settings.actions",
        )

    if "voice_loop" in normalized:
        voice_loop = normalized.get("voice_loop")
        if not isinstance(voice_loop, Mapping):
            raise ValueError("settings.voice_loop must be an object")
        normalized_voice_loop = deepcopy(dict(voice_loop))
        if "command_packs" in normalized_voice_loop:
            normalized_voice_loop["command_packs"] = normalize_action_pack_ids(
                normalized_voice_loop["command_packs"],
                path="settings.voice_loop.command_packs",
            )
        normalized["voice_loop"] = normalized_voice_loop

    if "assistant_profiles" in normalized:
        profiles = normalized.get("assistant_profiles")
        if isinstance(profiles, (str, bytes)) or not isinstance(profiles, Sequence):
            raise ValueError("settings.assistant_profiles must be an array")
        normalized_profiles: list[Any] = []
        for index, profile in enumerate(profiles):
            if not isinstance(profile, Mapping):
                raise ValueError(f"settings.assistant_profiles[{index}] must be an object")
            item = deepcopy(dict(profile))
            path = f"settings.assistant_profiles[{index}]"
            if "action_packs" in item:
                item["action_packs"] = normalize_action_pack_ids(
                    item["action_packs"],
                    path=f"{path}.action_packs",
                )
            if "actions" in item:
                item["actions"] = _normalize_action_config(
                    item.get("actions"),
                    path=f"{path}.actions",
                )
            normalized_profiles.append(item)
        normalized["assistant_profiles"] = normalized_profiles
    return normalized


def normalize_system_action_pack_settings(
    *,
    settings: Mapping[str, Any] | None,
    execution_profile: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return System JSON fields with every declared pack list canonicalized."""

    normalized_settings = deepcopy(dict(settings)) if settings is not None else None
    if normalized_settings is not None and "actions" in normalized_settings:
        normalized_settings["actions"] = _normalize_action_config(
            normalized_settings.get("actions"),
            path="settings.actions",
        )

    normalized_profile = (
        deepcopy(dict(execution_profile)) if execution_profile is not None else None
    )
    if normalized_profile is not None:
        if "action_packs" in normalized_profile:
            normalized_profile["action_packs"] = normalize_action_pack_ids(
                normalized_profile["action_packs"],
                path="execution_profile.action_packs",
            )
        if "actions" in normalized_profile:
            normalized_profile["actions"] = _normalize_action_config(
                normalized_profile.get("actions"),
                path="execution_profile.actions",
            )
    return normalized_settings, normalized_profile


def validate_workspace_action_pack_settings(settings: Mapping[str, Any]) -> None:
    """Validate every supported workspace-level action-pack declaration."""

    normalize_workspace_action_pack_settings(settings)


def validate_system_action_pack_settings(
    *,
    settings: Mapping[str, Any] | None,
    execution_profile: Mapping[str, Any] | None,
) -> None:
    """Validate action packs accepted by the canonical System API."""

    normalize_system_action_pack_settings(
        settings=settings,
        execution_profile=execution_profile,
    )
