"""Content-addressed built-in Workspace App manifests.

The registry is deliberately compiled from literals shipped with the backend.
Callers never accept an arbitrary manifest document from a workspace: they
select an exact ``(app_id, version, sha256)`` already present in this registry.
This is the trust boundary used by the Lot-9 installation lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.schemas.canonical import WorkspaceApp, WorkspaceFamily
from app.services.actions.contracts import normalize_action_pack_ids

MANIFEST_SCHEMA_VERSION = 1
WORKSPACE_APP_PLATFORM_VERSION = 1
AGENTIUM_API_CONTRACT = "v1"
SUPPORTED_BLUEPRINT_VERSIONS = frozenset({2})
MANIFEST_LOCK_SCHEMA_VERSION = 1
DEFAULT_MANIFEST_LOCK_PATH = (
    Path(__file__).resolve().parents[3]
    / "config"
    / "agentium"
    / "workspace-app-manifests.v1.json"
)

_APP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{2,119}$")
_ENTITLEMENT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WORKSPACE_APP_MIGRATION_EXECUTORS = frozenset({"platform_schema_contract_v1"})
WORKSPACE_APP_BACKFILL_EXECUTORS = frozenset({"explicit_legacy_backfill_v1"})


class WorkspaceAppManifestError(ValueError):
    """A manifest identity, version, digest or contract is invalid."""


class WorkspaceAppManifestNotFound(WorkspaceAppManifestError):  # noqa: N818 - public API
    """No precompiled manifest matches the requested identity."""


def _credential_shaped_configuration_key(value: Any) -> bool:
    """Recognize credential-bearing field names without blocking business terms."""

    if not isinstance(value, str):
        return True
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value.strip())
    parts = tuple(
        part
        for part in re.split(r"[^a-z0-9]+", camel_split.lower())
        if part
    )
    if not parts:
        return True
    if set(parts).intersection(
        {"password", "passwd", "secret", "credential", "credentials"}
    ):
        return True
    credential_sequences = {
        ("api", "key"),
        ("api", "token"),
        ("access", "key"),
        ("access", "token"),
        ("auth", "token"),
        ("authorization", "token"),
        ("bearer", "token"),
        ("client", "key"),
        ("private", "key"),
        ("refresh", "token"),
    }
    if len(parts) == 1 and parts[0] in {
        "apikey",
        "apitoken",
        "accesskey",
        "accesstoken",
        "authtoken",
        "authorizationtoken",
        "bearertoken",
        "clientkey",
        "privatekey",
        "refreshtoken",
    }:
        return True
    return any(tuple(parts[index : index + 2]) in credential_sequences for index in range(len(parts) - 1))


@dataclass(frozen=True)
class CompiledWorkspaceAppManifest:
    """Immutable registry entry backed by canonical JSON bytes."""

    app_id: str
    version: str
    digest: str
    canonical_json: str

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_json)

    @property
    def configuration_contract(self) -> dict[str, Any]:
        return self.as_dict()["configuration_contract"]


def parse_semver(version: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.fullmatch(str(version or "").strip())
    if match is None:
        raise WorkspaceAppManifestError("workspace app version must be strict semantic versioning")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _canonical_json(payload: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise WorkspaceAppManifestError("workspace app manifest must be canonical JSON") from exc


def _configuration_contract(
    *,
    defaults: Mapping[str, Any],
    properties: Mapping[str, Mapping[str, Any]],
    required: Sequence[str] | None = None,
) -> dict[str, Any]:
    return {
        "additional_properties": False,
        "defaults": dict(defaults),
        "properties": {key: dict(value) for key, value in properties.items()},
        "required": list(required or defaults.keys()),
    }


def _manifest(
    *,
    app_id: str,
    version: str,
    display_name: str,
    category: str,
    routes: Sequence[str],
    api_prefix: str,
    api_prefixes: Sequence[str] | None = None,
    branding_namespace: str,
    action_packs: Sequence[str],
    entitlement_keys: Sequence[str],
    configuration_contract: Mapping[str, Any],
    shell: str,
    primary_surface_id: str,
    default_route: str,
    workspace_families: Sequence[str],
    workspace_profiles: Sequence[str] = (),
    forbidden_workspace_profiles: Sequence[str] = (),
    conflict_group: str | None = None,
    exclusive_routes: bool = True,
    mission_room: Mapping[str, Any] | None = None,
    migrations: Sequence[Mapping[str, Any]] | None = None,
    backfills: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "app_id": app_id,
        "version": version,
        "display_name": display_name,
        "category": category,
        "compatibility": {
            "workspace_app_platform": WORKSPACE_APP_PLATFORM_VERSION,
            "agentium_api": AGENTIUM_API_CONTRACT,
            "blueprint_versions": sorted(SUPPORTED_BLUEPRINT_VERSIONS),
            "workspace_families": list(workspace_families),
            "workspace_profiles": list(workspace_profiles),
            "forbidden_workspace_profiles": list(forbidden_workspace_profiles),
        },
        "conflict_group": conflict_group,
        "exclusive_routes": exclusive_routes,
        "routes": list(routes),
        **(
            {"api_prefixes": list(api_prefixes)}
            if api_prefixes is not None
            else {}
        ),
        "surfaces": [
            {
                "id": f"{app_id}.surface.{index + 1}",
                "route": route,
                "api_prefix": api_prefix,
            }
            for index, route in enumerate(routes)
        ],
        "branding": {
            "namespace": branding_namespace,
            "contract": f"{branding_namespace}.workspace-app-theme.v1",
        },
        "action_packs": list(action_packs),
        "entitlement_keys": list(entitlement_keys),
        "experience": {
            "shell": shell,
            "primary_surface_id": primary_surface_id,
            "default_route": default_route,
            "mission_room": dict(mission_room) if mission_room is not None else None,
        },
        "configuration_contract": dict(configuration_contract),
        "migrations": [
            dict(item)
            for item in (
                migrations
                or (
                    {
                        "id": "workspace_app_platform.schema.069",
                        "kind": "platform_schema",
                        "phase": "precondition",
                        "executor": "platform_schema_contract_v1",
                        "required": True,
                        "reversibility": "persistent_additive_schema",
                    },
                    {
                        "id": "workspace_app_platform.lifecycle_steps.073",
                        "kind": "platform_schema",
                        "phase": "precondition",
                        "executor": "platform_schema_contract_v1",
                        "required": True,
                        "reversibility": "persistent_additive_schema",
                    },
                )
            )
        ],
        "backfills": [
            dict(item)
            for item in (
                backfills
                or (
                    {
                        "id": f"{app_id}.legacy_installation.v1",
                        "kind": "explicit_application_backfill",
                        "phase": "legacy_adoption",
                        "executor": "explicit_legacy_backfill_v1",
                        "required": True,
                        "runner": "backend/scripts/backfill_workspace_app_installations.py",
                        "selection": "explicit_workspace_ids",
                        "mutates_member_entitlements": False,
                        "reversibility": "installation_transaction",
                    },
                )
            )
        ],
    }


_STRING = {"type": "string"}
_MISSION_NAVIGATION_KEYS = (
    "cockpit",
    "strategie",
    "securite",
    "reputation",
    "agenda",
    "presse",
    "decisions",
)
GENERIC_MISSION_ROOM_PROVIDER_KIND = "workspace_objects_v1"
GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS = (
    "GET /overview",
    "GET /navigation",
    "GET /cockpit",
    "GET /briefing",
    "GET /timeline",
    "GET /projects",
    "GET /decisions",
    "GET /library",
    "GET /search",
    "GET /map",
    "GET /monitor",
    "GET /news",
    "POST /actions/draft",
)

_MANIFEST_LITERALS: tuple[dict[str, Any], ...] = (
    _manifest(
        app_id="andritz.chat",
        version="1.0.0",
        display_name="Andritz Chat",
        category="business_app",
        routes=("/chat",),
        api_prefix="/api/v1/chat",
        api_prefixes=("/api/v1/chat", "/api/v1/sessions"),
        branding_namespace="andritz",
        action_packs=("andritz_industrial_v1",),
        entitlement_keys=("chat",),
        shell="business",
        primary_surface_id="chat",
        default_route="/chat",
        workspace_families=(WorkspaceFamily.andritz.value,),
        configuration_contract=_configuration_contract(
            defaults={"api_contract": "andritz.chat.v1"},
            properties={
                "api_contract": {"type": "string", "enum": ["andritz.chat.v1"]},
            },
        ),
    ),
    _manifest(
        app_id="andritz.client360-pdr",
        version="1.0.0",
        display_name="Andritz Client360 PDR",
        category="business_app",
        routes=("/client360",),
        api_prefix="/api/v1/client360",
        branding_namespace="andritz",
        action_packs=("andritz_industrial_v1",),
        entitlement_keys=("client360-pdr",),
        shell="business",
        primary_surface_id="client360-pdr",
        default_route="/client360",
        workspace_families=(WorkspaceFamily.andritz.value,),
        configuration_contract=_configuration_contract(
            defaults={"api_contract": "andritz.client360-pdr.v1"},
            properties={
                "api_contract": {
                    "type": "string",
                    "enum": ["andritz.client360-pdr.v1"],
                },
            },
        ),
    ),
    _manifest(
        app_id="andritz.knowledge-capture",
        version="1.0.0",
        display_name="Andritz Knowledge Capture",
        category="business_app",
        routes=("/knowledge/capture", "/knowledge/interventions"),
        api_prefix="/api/v1/knowledge-capture",
        branding_namespace="andritz",
        action_packs=("andritz_industrial_v1",),
        entitlement_keys=("knowledge-capture", "fse-reports"),
        shell="business",
        primary_surface_id="knowledge-capture",
        default_route="/knowledge/capture",
        workspace_families=(WorkspaceFamily.andritz.value,),
        configuration_contract=_configuration_contract(
            defaults={"api_contract": "andritz.knowledge-capture.v1"},
            properties={
                "api_contract": {
                    "type": "string",
                    "enum": ["andritz.knowledge-capture.v1"],
                },
            },
        ),
    ),
    _manifest(
        app_id="mission-room.extension",
        version="1.0.0",
        display_name="Mission Room",
        category="workspace_extension",
        routes=("/hypervisor/mission-room",),
        api_prefix="/api/v1/mission-room",
        branding_namespace="mission-room",
        action_packs=("global_voice_v1",),
        entitlement_keys=(),
        shell="immersive",
        primary_surface_id="mission-room",
        default_route="/hypervisor/mission-room/cockpit",
        workspace_families=(WorkspaceFamily.generic.value,),
        forbidden_workspace_profiles=(
            "sentinel_government_v1",
            "government_mission_room",
            "octocity_institutional_v1",
            "octocity_mission_room",
        ),
        conflict_group="mission-room.primary",
        mission_room={
            "profile_source": "configuration.profile",
            "assistant_profile_source": "configuration.assistant_profile",
            "label": "Mission Room",
            "assistant_label": "Assistant",
            "brand_style": "agentium",
            "navigation_keys": list(_MISSION_NAVIGATION_KEYS),
        },
        configuration_contract=_configuration_contract(
            defaults={"profile": "generic", "assistant_profile": "default"},
            properties={
                "profile": {
                    **_STRING,
                    "forbidden_prefixes": ["sentinel", "octocity"],
                    "forbidden_values": [
                        "government_mission_room",
                        "octocity_mission_room",
                    ],
                },
                "assistant_profile": {
                    **_STRING,
                    "forbidden_prefixes": ["vigie", "octave", "sentinel", "octocity"],
                },
            },
        ),
    ),
    _manifest(
        app_id="mission-room.extension",
        version="1.1.0",
        display_name="Mission Room",
        category="workspace_extension",
        routes=("/hypervisor/mission-room",),
        api_prefix="/api/v1/mission-room",
        branding_namespace="mission-room",
        action_packs=("global_voice_v1",),
        entitlement_keys=(),
        shell="immersive",
        primary_surface_id="mission-room",
        default_route="/hypervisor/mission-room/cockpit",
        workspace_families=(WorkspaceFamily.generic.value,),
        forbidden_workspace_profiles=(
            "sentinel_government_v1",
            "government_mission_room",
            "octocity_institutional_v1",
            "octocity_mission_room",
        ),
        conflict_group="mission-room.primary",
        mission_room={
            "profile_source": "configuration.profile",
            "assistant_profile_source": "configuration.assistant_profile",
            "label": "Mission Room",
            "assistant_label": "Assistant",
            "brand_style": "agentium",
            "navigation_keys": list(_MISSION_NAVIGATION_KEYS),
        },
        configuration_contract=_configuration_contract(
            defaults={
                "profile": "generic",
                "assistant_profile": "default",
                "decision_surfaces": True,
            },
            properties={
                "profile": {
                    **_STRING,
                    "forbidden_prefixes": ["sentinel", "octocity"],
                    "forbidden_values": [
                        "government_mission_room",
                        "octocity_mission_room",
                    ],
                },
                "assistant_profile": {
                    **_STRING,
                    "forbidden_prefixes": ["vigie", "octave", "sentinel", "octocity"],
                },
                "decision_surfaces": {"type": "boolean"},
            },
        ),
    ),
    _manifest(
        app_id="mission-room.extension",
        version="1.2.0",
        display_name="Mission Room",
        category="workspace_extension",
        routes=("/hypervisor/mission-room",),
        api_prefix="/api/v1/mission-room",
        branding_namespace="mission-room",
        action_packs=("global_voice_v1",),
        entitlement_keys=(),
        shell="immersive",
        primary_surface_id="mission-room",
        default_route="/hypervisor/mission-room/cockpit",
        workspace_families=(WorkspaceFamily.generic.value,),
        forbidden_workspace_profiles=(
            "sentinel_government_v1",
            "government_mission_room",
            "octocity_institutional_v1",
            "octocity_mission_room",
        ),
        conflict_group="mission-room.primary",
        mission_room={
            "profile_source": "configuration.profile",
            "assistant_profile_source": "configuration.assistant_profile",
            "label": "Mission Room",
            "assistant_label": "Assistant",
            "brand_style": "agentium",
            "navigation_keys": list(_MISSION_NAVIGATION_KEYS),
            "provider_kind": GENERIC_MISSION_ROOM_PROVIDER_KIND,
            "provider_endpoints": list(GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS),
        },
        configuration_contract=_configuration_contract(
            defaults={
                "profile": "generic",
                "assistant_profile": "default",
                "decision_surfaces": True,
            },
            properties={
                "profile": {
                    **_STRING,
                    "forbidden_prefixes": ["sentinel", "octocity"],
                    "forbidden_values": [
                        "government_mission_room",
                        "octocity_mission_room",
                    ],
                },
                "assistant_profile": {
                    **_STRING,
                    "forbidden_prefixes": ["vigie", "octave", "sentinel", "octocity"],
                },
                "decision_surfaces": {"type": "boolean"},
            },
        ),
    ),
    _manifest(
        app_id="sentinel.mission-room",
        version="1.0.0",
        display_name="Sentinel Mission Room",
        category="workspace_extension",
        routes=("/hypervisor/mission-room",),
        api_prefix="/api/v1/mission-room",
        branding_namespace="sentinel",
        action_packs=(
            "global_voice_v1",
            "sentinel_ci_aya_v1",
            "sentinel_ci_aya_security_v1",
        ),
        entitlement_keys=(),
        shell="immersive",
        primary_surface_id="mission-room",
        default_route="/hypervisor/mission-room/cockpit",
        workspace_families=(WorkspaceFamily.sentinel_ci.value,),
        workspace_profiles=("sentinel_government_v1",),
        conflict_group="mission-room.primary",
        mission_room={
            "profile": "sentinel_government_v1",
            "assistant_profile": "vigie_executive",
            "label": "SENTINEL-CI",
            "assistant_label": "AYA",
            "brand_style": "sentinel",
            "navigation_keys": list(_MISSION_NAVIGATION_KEYS),
        },
        configuration_contract=_configuration_contract(
            defaults={
                "profile": "government_mission_room",
                "assistant_profile": "vigie_executive",
            },
            properties={
                "profile": {
                    "type": "string",
                    "enum": ["government_mission_room"],
                },
                "assistant_profile": {
                    "type": "string",
                    "enum": ["vigie_executive"],
                },
            },
        ),
    ),
    _manifest(
        app_id="octocity.mission-room",
        version="1.0.0",
        display_name="Octocity Mission Room",
        category="workspace_extension",
        routes=("/hypervisor/mission-room",),
        api_prefix="/api/v1/mission-room",
        branding_namespace="octocity",
        action_packs=(
            "global_voice_v1",
            "octave_mission_room_v1",
            "octave_security_v1",
        ),
        entitlement_keys=(),
        shell="immersive",
        primary_surface_id="mission-room",
        default_route="/hypervisor/mission-room/cockpit",
        workspace_families=(WorkspaceFamily.generic.value,),
        workspace_profiles=("octocity_institutional_v1",),
        conflict_group="mission-room.primary",
        mission_room={
            "profile": "octocity_institutional_v1",
            "assistant_profile": "octave_executive",
            "label": "Octocity Mission Room",
            "assistant_label": "OCTAVE",
            "brand_style": "agentium",
            "navigation_keys": list(_MISSION_NAVIGATION_KEYS),
        },
        configuration_contract=_configuration_contract(
            defaults={
                "profile": "octocity_mission_room",
                "assistant_profile": "octave_executive",
            },
            properties={
                "profile": {
                    "type": "string",
                    "enum": ["octocity_mission_room"],
                },
                "assistant_profile": {
                    "type": "string",
                    "enum": ["octave_executive"],
                },
            },
        ),
    ),
)


def _validate_scalar(value: Any, schema: Mapping[str, Any], path: str) -> None:
    expected = schema.get("type")
    if expected == "string":
        if not isinstance(value, str) or not value.strip():
            raise WorkspaceAppManifestError(f"{path} must be a non-empty string")
    elif expected == "boolean":
        if not isinstance(value, bool):
            raise WorkspaceAppManifestError(f"{path} must be a boolean")
    elif expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise WorkspaceAppManifestError(f"{path} must be an integer")
    elif expected == "array_string":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise WorkspaceAppManifestError(f"{path} must be a list of strings")
    else:
        raise WorkspaceAppManifestError(f"{path} declares an unsupported type")
    allowed = schema.get("enum")
    if isinstance(allowed, list) and value not in allowed:
        raise WorkspaceAppManifestError(f"{path} is not one of the allowed values")
    if isinstance(value, str):
        normalized = value.strip().lower()
        forbidden_values = schema.get("forbidden_values", [])
        forbidden_prefixes = schema.get("forbidden_prefixes", [])
        if (
            not isinstance(forbidden_values, list)
            or any(not isinstance(item, str) for item in forbidden_values)
            or not isinstance(forbidden_prefixes, list)
            or any(not isinstance(item, str) for item in forbidden_prefixes)
        ):
            raise WorkspaceAppManifestError(f"{path} has an invalid reserved-value contract")
        if normalized in {item.strip().lower() for item in forbidden_values} or any(
            normalized.startswith(item.strip().lower())
            for item in forbidden_prefixes
            if item.strip()
        ):
            raise WorkspaceAppManifestError(f"{path} uses a reserved workspace-app identity")


def validate_manifest_configuration(
    manifest: CompiledWorkspaceAppManifest,
    configuration: Mapping[str, Any] | None,
    *,
    base: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply manifest defaults and validate a complete, secret-free config."""

    if configuration is not None and not isinstance(configuration, Mapping):
        raise WorkspaceAppManifestError("workspace app configuration must be an object")
    contract = manifest.configuration_contract
    properties = contract.get("properties")
    defaults = contract.get("defaults")
    required = contract.get("required")
    if not isinstance(properties, Mapping) or not isinstance(defaults, Mapping):
        raise WorkspaceAppManifestError("manifest configuration contract is invalid")
    credential_fields = sorted(
        str(key)
        for key in properties
        if _credential_shaped_configuration_key(key)
    )
    if credential_fields:
        raise WorkspaceAppManifestError(
            "workspace app configuration contract contains credential-shaped fields: "
            + ", ".join(credential_fields)
        )
    result = deepcopy(dict(defaults))
    if base is not None:
        if not isinstance(base, Mapping):
            raise WorkspaceAppManifestError("existing workspace app configuration is invalid")
        result.update(deepcopy(dict(base)))
    if configuration is not None:
        result.update(deepcopy(dict(configuration)))
    unknown = sorted(set(result) - set(str(key) for key in properties))
    if unknown and contract.get("additional_properties") is not True:
        raise WorkspaceAppManifestError(
            f"unknown workspace app configuration keys: {', '.join(unknown)}"
        )
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise WorkspaceAppManifestError("manifest required configuration keys are invalid")
    missing = [key for key in required if key not in result]
    if missing:
        raise WorkspaceAppManifestError(
            f"missing workspace app configuration keys: {', '.join(sorted(missing))}"
        )
    for key, value in result.items():
        schema = properties.get(key)
        if not isinstance(schema, Mapping):
            raise WorkspaceAppManifestError(f"configuration contract for {key} is invalid")
        _validate_scalar(value, schema, f"configuration.{key}")
    # Ensure callers cannot smuggle a non-JSON object into a JSON column.
    _canonical_json(result)
    return result


def _validate_manifest_experience(
    payload: Mapping[str, Any],
    *,
    app_id: str,
    version: str,
    routes: Sequence[str],
) -> None:
    experience = payload.get("experience")
    expected_keys = {"shell", "primary_surface_id", "default_route", "mission_room"}
    if not isinstance(experience, Mapping) or set(experience) != expected_keys:
        raise WorkspaceAppManifestError(
            f"experience contract is invalid for {app_id}@{version}"
        )

    shell = experience.get("shell")
    if shell not in {"standard", "business", "immersive"}:
        raise WorkspaceAppManifestError(
            f"experience shell is invalid for {app_id}@{version}"
        )
    primary_surface_id = experience.get("primary_surface_id")
    if (
        not isinstance(primary_surface_id, str)
        or not primary_surface_id.strip()
        or primary_surface_id != primary_surface_id.strip()
    ):
        raise WorkspaceAppManifestError(
            f"experience primary surface is invalid for {app_id}@{version}"
        )
    default_route = experience.get("default_route")
    if not isinstance(default_route, str) or not any(
        default_route == route or default_route.startswith(f"{route.rstrip('/')}/")
        for route in routes
    ):
        raise WorkspaceAppManifestError(
            f"experience default route is outside declared routes for {app_id}@{version}"
        )

    mission_room = experience.get("mission_room")
    if shell != "immersive":
        if mission_room is not None:
            raise WorkspaceAppManifestError(
                f"non-immersive app declares Mission Room metadata for {app_id}@{version}"
            )
        return
    if not isinstance(mission_room, Mapping):
        raise WorkspaceAppManifestError(
            f"immersive app is missing Mission Room metadata for {app_id}@{version}"
        )
    common = {"label", "assistant_label", "brand_style", "navigation_keys"}
    fixed = common | {"profile", "assistant_profile"}
    derived = common | {"profile_source", "assistant_profile_source"}
    provider = {"provider_kind", "provider_endpoints"}
    mission_room_keys = frozenset(mission_room)
    if mission_room_keys not in {
        frozenset(fixed),
        frozenset(derived),
        frozenset(derived | provider),
    }:
        raise WorkspaceAppManifestError(
            f"Mission Room metadata is invalid for {app_id}@{version}"
        )
    for key in set(mission_room) - {"navigation_keys", "provider_endpoints"}:
        value = mission_room.get(key)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise WorkspaceAppManifestError(
                f"Mission Room {key} is invalid for {app_id}@{version}"
            )
    if frozenset(derived).issubset(mission_room_keys) and (
        mission_room.get("profile_source") != "configuration.profile"
        or mission_room.get("assistant_profile_source")
        != "configuration.assistant_profile"
    ):
        raise WorkspaceAppManifestError(
            f"Mission Room configuration sources are invalid for {app_id}@{version}"
        )
    navigation_keys = mission_room.get("navigation_keys")
    if navigation_keys != list(_MISSION_NAVIGATION_KEYS):
        raise WorkspaceAppManifestError(
            f"Mission Room navigation contract is invalid for {app_id}@{version}"
        )
    if provider.issubset(mission_room_keys):
        if (
            app_id != "mission-room.extension"
            or mission_room.get("provider_kind")
            != GENERIC_MISSION_ROOM_PROVIDER_KIND
            or mission_room.get("provider_endpoints")
            != list(GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS)
        ):
            raise WorkspaceAppManifestError(
                f"Mission Room provider contract is invalid for {app_id}@{version}"
            )


def _compile_manifest(payload: Mapping[str, Any]) -> CompiledWorkspaceAppManifest:
    app_id = str(payload.get("app_id") or "")
    version = str(payload.get("version") or "")
    if _APP_ID_RE.fullmatch(app_id) is None:
        raise WorkspaceAppManifestError(f"invalid workspace app id: {app_id!r}")
    parse_semver(version)
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise WorkspaceAppManifestError(f"unsupported manifest schema for {app_id}@{version}")
    compatibility = payload.get("compatibility")
    if not isinstance(compatibility, Mapping):
        raise WorkspaceAppManifestError(f"missing compatibility for {app_id}@{version}")
    if compatibility.get("workspace_app_platform") != WORKSPACE_APP_PLATFORM_VERSION:
        raise WorkspaceAppManifestError(f"incompatible app platform for {app_id}@{version}")
    if compatibility.get("agentium_api") != AGENTIUM_API_CONTRACT:
        raise WorkspaceAppManifestError(f"incompatible Agentium API for {app_id}@{version}")
    blueprints = compatibility.get("blueprint_versions")
    if not isinstance(blueprints, list) or not set(blueprints).intersection(
        SUPPORTED_BLUEPRINT_VERSIONS
    ):
        raise WorkspaceAppManifestError(f"incompatible Blueprint contract for {app_id}@{version}")
    workspace_families = compatibility.get("workspace_families")
    known_families = {family.value for family in WorkspaceFamily}
    if (
        not isinstance(workspace_families, list)
        or not workspace_families
        or any(
            not isinstance(family, str) or family not in known_families
            for family in workspace_families
        )
        or len(workspace_families) != len(set(workspace_families))
    ):
        raise WorkspaceAppManifestError(
            f"workspace family compatibility is invalid for {app_id}@{version}"
        )
    workspace_profiles = compatibility.get("workspace_profiles")
    if (
        not isinstance(workspace_profiles, list)
        or any(
            not isinstance(profile, str)
            or not profile.strip()
            or profile != profile.strip()
            for profile in workspace_profiles
        )
        or len(workspace_profiles) != len(set(workspace_profiles))
    ):
        raise WorkspaceAppManifestError(
            f"workspace profile compatibility is invalid for {app_id}@{version}"
        )
    forbidden_workspace_profiles = compatibility.get("forbidden_workspace_profiles")
    if (
        not isinstance(forbidden_workspace_profiles, list)
        or any(
            not isinstance(profile, str)
            or not profile.strip()
            or profile != profile.strip()
            for profile in forbidden_workspace_profiles
        )
        or len(forbidden_workspace_profiles) != len(set(forbidden_workspace_profiles))
        or set(forbidden_workspace_profiles).intersection(workspace_profiles)
    ):
        raise WorkspaceAppManifestError(
            f"forbidden workspace profile contract is invalid for {app_id}@{version}"
        )
    conflict_group = payload.get("conflict_group")
    if conflict_group is not None and (
        not isinstance(conflict_group, str)
        or not conflict_group.strip()
        or conflict_group != conflict_group.strip()
    ):
        raise WorkspaceAppManifestError(
            f"conflict group is invalid for {app_id}@{version}"
        )
    if payload.get("exclusive_routes") is not True:
        raise WorkspaceAppManifestError(
            f"exclusive route ownership is required for {app_id}@{version}"
        )
    for sequence_key in ("routes", "action_packs", "entitlement_keys"):
        value = payload.get(sequence_key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise WorkspaceAppManifestError(f"{sequence_key} is invalid for {app_id}@{version}")
        if len(value) != len(set(value)):
            raise WorkspaceAppManifestError(f"{sequence_key} contains duplicates")
    if any(_ENTITLEMENT_KEY_RE.fullmatch(key) is None for key in payload["entitlement_keys"]):
        raise WorkspaceAppManifestError(
            f"entitlement_keys contain a non-canonical key for {app_id}@{version}"
        )
    legacy_entitlements = {item.value for item in WorkspaceApp}
    manifest_defined_entitlements = set(payload["entitlement_keys"]) - legacy_entitlements
    routes = payload["routes"]
    if not routes or any(
        not route.startswith("/") or route == "/" or route.endswith("/") for route in routes
    ):
        raise WorkspaceAppManifestError(f"routes must be absolute for {app_id}@{version}")
    try:
        normalized_action_packs = normalize_action_pack_ids(
            payload["action_packs"],
            path=f"workspace_app_manifest.{app_id}.action_packs",
        )
    except ValueError as exc:
        raise WorkspaceAppManifestError(str(exc)) from exc
    if normalized_action_packs != payload["action_packs"]:
        raise WorkspaceAppManifestError(
            f"action_packs must use canonical identifiers for {app_id}@{version}"
        )
    _validate_manifest_experience(
        payload,
        app_id=app_id,
        version=version,
        routes=routes,
    )
    surfaces = payload.get("surfaces")
    if not isinstance(surfaces, list) or len(surfaces) != len(routes):
        raise WorkspaceAppManifestError(f"surfaces do not match routes for {app_id}@{version}")
    for index, surface in enumerate(surfaces):
        if not isinstance(surface, Mapping):
            raise WorkspaceAppManifestError(f"surface {index} is invalid for {app_id}@{version}")
        if surface.get("route") != routes[index]:
            raise WorkspaceAppManifestError(f"surface route mismatch for {app_id}@{version}")
        api_prefix = surface.get("api_prefix")
        if not isinstance(api_prefix, str) or not api_prefix.startswith("/api/v1/"):
            raise WorkspaceAppManifestError(
                f"surface API contract is invalid for {app_id}@{version}"
            )
    declared_api_prefixes = payload.get("api_prefixes")
    if declared_api_prefixes is None:
        effective_api_prefixes = [str(surface["api_prefix"]) for surface in surfaces]
    elif (
        not isinstance(declared_api_prefixes, list)
        or not declared_api_prefixes
        or any(
            not isinstance(prefix, str)
            or not prefix.startswith("/api/v1/")
            or prefix.endswith("/")
            or prefix != prefix.strip()
            for prefix in declared_api_prefixes
        )
        or len(declared_api_prefixes) != len(set(declared_api_prefixes))
    ):
        raise WorkspaceAppManifestError(
            f"API prefixes are invalid for {app_id}@{version}"
        )
    else:
        effective_api_prefixes = declared_api_prefixes
    if any(
        str(surface["api_prefix"]) not in effective_api_prefixes
        for surface in surfaces
    ):
        raise WorkspaceAppManifestError(
            f"surface API prefix is outside the application boundary for {app_id}@{version}"
        )
    for lifecycle_key in ("migrations", "backfills"):
        lifecycle = payload.get(lifecycle_key)
        if not isinstance(lifecycle, list) or not lifecycle:
            raise WorkspaceAppManifestError(
                f"{lifecycle_key} contract is invalid for {app_id}@{version}"
            )
        identifiers: set[str] = set()
        for index, item in enumerate(lifecycle):
            if not isinstance(item, Mapping):
                raise WorkspaceAppManifestError(
                    f"{lifecycle_key}[{index}] is invalid for {app_id}@{version}"
                )
            identifier = item.get("id")
            kind = item.get("kind")
            if not isinstance(identifier, str) or not identifier.strip():
                raise WorkspaceAppManifestError(
                    f"{lifecycle_key}[{index}].id is invalid for {app_id}@{version}"
                )
            if identifier in identifiers:
                raise WorkspaceAppManifestError(
                    f"{lifecycle_key} contains duplicate ids for {app_id}@{version}"
                )
            identifiers.add(identifier)
            if not isinstance(kind, str) or not kind.strip():
                raise WorkspaceAppManifestError(
                    f"{lifecycle_key}[{index}].kind is invalid for {app_id}@{version}"
                )
        if lifecycle_key == "backfills":
            for index, item in enumerate(lifecycle):
                runner = item.get("runner")
                selection = item.get("selection")
                if (
                    not isinstance(runner, str)
                    or not runner.startswith("backend/scripts/")
                    or item.get("phase") != "legacy_adoption"
                    or item.get("executor") not in WORKSPACE_APP_BACKFILL_EXECUTORS
                    or item.get("required") is not True
                    or selection != "explicit_workspace_ids"
                    or item.get("mutates_member_entitlements") is not False
                    or item.get("reversibility") != "installation_transaction"
                ):
                    raise WorkspaceAppManifestError(
                        f"backfills[{index}] is not an explicit safe backfill for {app_id}@{version}"
                    )
        else:
            for index, item in enumerate(lifecycle):
                if (
                    item.get("kind") != "platform_schema"
                    or item.get("phase") != "precondition"
                    or item.get("executor") not in WORKSPACE_APP_MIGRATION_EXECUTORS
                    or item.get("required") is not True
                    or item.get("reversibility") != "persistent_additive_schema"
                ):
                    raise WorkspaceAppManifestError(
                        f"migrations[{index}] is not a closed platform schema step for {app_id}@{version}"
                    )
    if manifest_defined_entitlements and not any(
        item.get("id") == "workspace_app_platform.entitlement_registry.070"
        and item.get("kind") == "platform_schema"
        and item.get("required") is True
        for item in payload["migrations"]
    ):
        raise WorkspaceAppManifestError(
            f"manifest-defined entitlements require schema 070 for {app_id}@{version}"
        )
    canonical = _canonical_json(payload)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    compiled = CompiledWorkspaceAppManifest(app_id, version, digest, canonical)
    validate_manifest_configuration(compiled, None)
    return compiled


def _build_registry() -> Mapping[tuple[str, str], CompiledWorkspaceAppManifest]:
    registry: dict[tuple[str, str], CompiledWorkspaceAppManifest] = {}
    for literal in _MANIFEST_LITERALS:
        compiled = _compile_manifest(literal)
        key = (compiled.app_id, compiled.version)
        if key in registry:
            raise WorkspaceAppManifestError(f"duplicate built-in manifest {key[0]}@{key[1]}")
        registry[key] = compiled
    return MappingProxyType(registry)


BUILTIN_WORKSPACE_APP_MANIFESTS = _build_registry()


def verify_builtin_workspace_app_manifest_lock(
    lock_path: Path = DEFAULT_MANIFEST_LOCK_PATH,
    *,
    registry: Mapping[
        tuple[str, str], CompiledWorkspaceAppManifest
    ] = BUILTIN_WORKSPACE_APP_MANIFESTS,
) -> Mapping[tuple[str, str], str]:
    """Reject in-place changes to a published ``app_id@version`` contract."""

    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceAppManifestError("Workspace App manifest lockfile is unavailable") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != (
        MANIFEST_LOCK_SCHEMA_VERSION
    ):
        raise WorkspaceAppManifestError("Workspace App manifest lockfile schema is invalid")
    entries = payload.get("manifests")
    if not isinstance(entries, list) or not entries:
        raise WorkspaceAppManifestError("Workspace App manifest lockfile is empty")
    locked: dict[tuple[str, str], str] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or set(entry) != {"app_id", "version", "sha256"}:
            raise WorkspaceAppManifestError(
                f"Workspace App manifest lockfile entry {index} is invalid"
            )
        app_id = str(entry.get("app_id") or "")
        version = str(entry.get("version") or "")
        digest = str(entry.get("sha256") or "").lower()
        if _APP_ID_RE.fullmatch(app_id) is None or _SEMVER_RE.fullmatch(version) is None:
            raise WorkspaceAppManifestError(
                f"Workspace App manifest lockfile entry {index} has invalid identity"
            )
        if _SHA256_RE.fullmatch(digest) is None:
            raise WorkspaceAppManifestError(
                f"Workspace App manifest lockfile entry {index} has invalid digest"
            )
        key = (app_id, version)
        if key in locked:
            raise WorkspaceAppManifestError(
                f"Workspace App manifest lockfile duplicates {app_id}@{version}"
            )
        locked[key] = digest
    expected = {key: manifest.digest for key, manifest in registry.items()}
    if locked != expected:
        raise WorkspaceAppManifestError(
            "Workspace App manifest lockfile differs from compiled contracts; "
            "published versions are immutable and require a SemVer bump"
        )
    return MappingProxyType(locked)


BUILTIN_WORKSPACE_APP_MANIFEST_LOCK = verify_builtin_workspace_app_manifest_lock()


def list_builtin_workspace_app_manifests(
    app_id: str | None = None,
) -> tuple[CompiledWorkspaceAppManifest, ...]:
    entries = [
        manifest
        for (registered_id, _), manifest in BUILTIN_WORKSPACE_APP_MANIFESTS.items()
        if app_id is None or registered_id == app_id
    ]
    return tuple(sorted(entries, key=lambda item: (item.app_id, parse_semver(item.version))))


def get_builtin_workspace_app_manifest(
    app_id: str,
    version: str,
    *,
    expected_digest: str,
) -> CompiledWorkspaceAppManifest:
    """Resolve only an exact precompiled version and content digest."""

    normalized_id = str(app_id or "").strip()
    normalized_version = str(version or "").strip()
    normalized_digest = str(expected_digest or "").strip().lower()
    if _SHA256_RE.fullmatch(normalized_digest) is None:
        raise WorkspaceAppManifestError("expected manifest digest must be a SHA-256 hex digest")
    manifest = BUILTIN_WORKSPACE_APP_MANIFESTS.get((normalized_id, normalized_version))
    if manifest is None:
        raise WorkspaceAppManifestNotFound(
            f"unknown built-in workspace app manifest {normalized_id}@{normalized_version}"
        )
    if manifest.digest != normalized_digest:
        raise WorkspaceAppManifestError(
            f"manifest digest mismatch for {normalized_id}@{normalized_version}"
        )
    return manifest
