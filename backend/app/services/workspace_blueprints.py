"""Workspace Blueprint export/import helpers.

Blueprints sit one level above the existing System export envelope: they
capture the workspace structure and configuration needed to recreate a
reference workspace without leaking members, credentials, raw files or
vector payloads.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.models.capability import Capability
from app.models.context import Context
from app.models.evaluation_preset import EvaluationPreset
from app.models.knowledge_collection import KnowledgeCollection
from app.models.rag_preset import RagPreset
from app.models.skill import Skill
from app.models.system import System
from app.models.user import User
from app.models.workspace import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberAppEntitlement,
)
from app.schemas.canonical import (
    ExecutionMode,
    SystemStatus,
    WorkspaceFamily,
    WorkspaceMode,
)
from app.services import knowledge_collections
from app.services.audit_logger import emit_audit_event
from app.services.chains import dag_validator, export_service, version_service
from app.services.iam.app_entitlements import (
    APP_ENTITLEMENTS_FEATURE,
    BUSINESS_APP_KEYS,
    WORKSPACE_EXPERIENCE_FEATURE,
    WorkspaceEntitlementMutationConflictError,
    lock_workspace_for_app_entitlement_mutation,
    normalize_app_entitlements,
)
from app.services.iam.config_service import load_iam_config, patch_iam_config
from app.services.workspace_features import workspace_family

BLUEPRINT_KIND = "agentium.workspace.blueprint"
SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, SCHEMA_VERSION})

EXPERIENCE_POLICIES = frozenset({"preserve_target", "merge_missing", "replace_portable"})
ENTITLEMENT_POLICIES = frozenset({"preserve_target", "grant_all_existing_members"})
DEFAULT_EXPERIENCE_POLICY = "preserve_target"
DEFAULT_ENTITLEMENT_POLICY = "preserve_target"

PORTABLE_WORKSPACE_MODES = frozenset(item.value for item in WorkspaceMode)
PORTABLE_SYSTEM_STATUSES = frozenset(item.value for item in SystemStatus)
PORTABLE_EXECUTION_MODES = frozenset(item.value for item in ExecutionMode)
PORTABLE_FEATURE_KEYS = (
    WORKSPACE_EXPERIENCE_FEATURE,
    "chat_document_upload",
    "cockpit_router_axes_v3",
)
PORTABLE_PROFILE_KEYS = ("family", "demo_profile", "hide_provider_details")
PORTABLE_NAVIGATION_KEYS = (
    "key",
    "default_route",
    "primary_surfaces",
    "advanced_access",
)
PORTABLE_SHELL_KEYS = (
    "default_route",
    "workspace_app_shell",
    "workspace_app_label",
    "workspace_app_default_view",
    "workspace_app_brand",
)
PORTABLE_ACTION_KEYS = (
    "enabled_packs",
    "hidden_packs",
    "enabled_actions",
    "hidden_actions",
    "confirmation_policy",
)
PORTABLE_MISSION_ROOM_KEYS = (
    "profile",
    "country",
    "country_code",
    "region_scope",
    "news_source_policy",
    "label",
    "assistant_label",
    "root_route",
    "default_view",
    "navigation",
    "brand",
)
PORTABLE_MISSION_DEPENDENCY_KEYS = (
    "calendar",
    "action_planner",
    "document_intelligence",
    "visual_intelligence",
    "feature_flags",
    "connectors",
)
PORTABLE_CALENDAR_KEYS = (
    "mode",
    "connector_id",
    "connector_label",
    "write_policy",
    "timezone",
)
PORTABLE_ACTION_PLANNER_KEYS = (
    "write_policy",
    "default_owner",
    "advisory_only",
)
PORTABLE_DOCUMENT_INTELLIGENCE_KEYS = (
    "enabled",
    "default_profile",
    "profiles",
    "ocr",
    "citation_policy",
)
PORTABLE_DOCUMENT_PROFILE_KEYS = (
    "key",
    "label",
    "synonyms",
    "max_candidate_facts",
    "max_evidence_rows",
)
PORTABLE_OCR_KEYS = (
    "enabled",
    "provider_priority",
    "languages",
    "min_confidence",
    "timeout_seconds",
    "required",
    "openai_vision_enabled",
)
PORTABLE_VISUAL_INTELLIGENCE_KEYS = (
    "enabled",
    "capture_cadence_minutes",
    "allowed_adapters",
    "storage_policy",
    "analysis_policy",
    "source_model",
)
PORTABLE_MISSION_FEATURE_FLAG_KEYS = ("security_live_osint",)
PORTABLE_MISSION_CONNECTOR_KEYS = (
    "institutional_calendar",
    "visual_streams",
)
PORTABLE_MISSION_CONNECTOR_CONFIG_KEYS = (
    "enabled",
    "status",
    "mode",
    "label",
)
PORTABLE_BRAND_KEYS = ("label", "lines", "emblem", "style", "accent")
PORTABLE_ASSISTANT_PROFILE_KEYS = (
    "key",
    "label",
    "subtitle",
    "default_knowledge_scope",
    "executive_mode",
    "tone",
    "grounding",
    "actions",
    "voice_loop",
    "voice_output",
    "response_style",
    "allowed_actions",
    "allowed_calendar_actions",
    "hidden_controls",
    "prompt_pack",
)
PORTABLE_GROUNDING_KEYS = (
    "default_mode",
    "allowed_modes",
    "fallback_disclaimer",
    "strict_guard",
)
PORTABLE_VOICE_LOOP_KEYS = (
    "default_mode",
    "enabled_default",
    "manual_start_required",
    "auto_send_final_transcript",
    "auto_endpoint",
    "auto_rearm_after_tts",
    "barge_in",
    "commands_enabled",
    "command_packs",
    "trigger_word",
    "stop_phrases",
    "silence_ms",
    "dictation_silence_ms",
    "min_speech_ms",
    "dictation_min_speech_ms",
    "max_turn_ms",
    "cooldown_ms",
    "rms_threshold",
    "endpoint_grace_ms",
    "vad_hangover_ms",
    "vad_calibration_ms",
    "vad_min_silence_frames_ms",
)
PORTABLE_VOICE_OUTPUT_KEYS = (
    "latency_profile",
    "voice",
    "flush_first_chars",
    "flush_next_chars",
    "flush_timeout_ms",
    "interrupt_on_user_speech",
)
PORTABLE_RESPONSE_STYLE_KEYS = (
    "address_as",
    "tone",
    "format",
    "max_bullets",
)
PORTABLE_KNOWLEDGE_SCOPE_KEYS = (
    "key",
    "label",
    "description",
    "collection_slugs",
    "default_mode",
    "top_k",
    "is_default",
    "table_profile_key",
    "document_profile_key",
)
MISSION_ROOM_EXTENSION_ID = "mission-room"
MISSION_ROOM_ROUTE_ROOT = "/hypervisor/mission-room"

_PROFILE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
_CREDENTIAL_DESCRIPTOR_KEYS = frozenset({"name", "key", "header", "variable", "var", "env"})
_CREDENTIAL_KEY_NAMES = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "private_key",
        "credential",
        "credentials",
        "authorization",
        "token",
        "bearer",
        "dsn",
    }
)
_CREDENTIAL_KEY_SUFFIXES = (
    "_password",
    "_passwd",
    "_secret",
    "_api_key",
    "_apikey",
    "_access_token",
    "_refresh_token",
    "_auth_token",
    "_id_token",
    "_session_token",
    "_private_key",
    "_credential",
    "_credentials",
    "_authorization",
    "_token",
    "_dsn",
)
_PORTABLE_OBJECT_LIST_PATHS = frozenset(
    {
        ("workspace", "settings", "assistant_profiles"),
        ("workspace", "settings", "knowledge_scopes"),
        ("workspace", "settings", "mission_room", "navigation"),
        ("workspace", "settings", "document_intelligence", "profiles"),
    }
)
_MISSING = object()


class WorkspaceBlueprintError(ValueError):
    """Raised when a workspace blueprint payload is malformed."""


class WorkspaceBlueprintConflictError(WorkspaceBlueprintError):
    """Raised when an apply no longer matches its validated target plan."""


def actor_display_name(user: User | None) -> str:
    if not user:
        return "system"
    return user.email or user.username or user.id or "system"


def export_workspace_blueprint(
    *,
    db: DBSession,
    workspace: Workspace,
    exported_by: User | None,
) -> dict[str, Any]:
    """Build a portable workspace blueprint.

    Data policy is intentionally conservative: the blueprint exports
    structure, model/config choices and collection metadata only. It never
    exports secure-deposit files, passwords, members, raw documents, vectors
    or Keycloak identity data.
    """
    actor = actor_display_name(exported_by)
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id)
        .order_by(System.created_at.asc(), System.name.asc())
        .all()
    )

    capability_ids = {s.capability_id for s in systems if s.capability_id}
    capability_filter = Capability.workspace_id == workspace.id
    if capability_ids:
        capability_filter = or_(capability_filter, Capability.id.in_(capability_ids))
    capabilities = (
        db.query(Capability)
        .filter(capability_filter)
        .order_by(Capability.workspace_id.is_(None), Capability.slug.asc())
        .all()
    )

    contexts = (
        db.query(Context)
        .filter(Context.workspace_id == workspace.id, Context.ephemeral.is_(False))
        .order_by(Context.name.asc(), Context.version.asc())
        .all()
    )
    collections = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id)
        .order_by(KnowledgeCollection.slug.asc())
        .all()
    )
    rag_presets = (
        db.query(RagPreset)
        .filter(RagPreset.workspace_id == workspace.id)
        .order_by(RagPreset.scope.asc(), RagPreset.name.asc())
        .all()
    )
    evaluation_presets = (
        db.query(EvaluationPreset)
        .filter(EvaluationPreset.workspace_id == workspace.id)
        .order_by(EvaluationPreset.scope.asc(), EvaluationPreset.name.asc())
        .all()
    )
    iam_config = load_iam_config(db, workspace.id, create=False)

    systems_by_id = {s.id: s for s in systems}
    capabilities_by_id = {c.id: c for c in capabilities}
    contexts_by_id = {c.id: c for c in contexts}
    capability_skill_ids = {
        skill_id for capability in capabilities for skill_id in (capability.skill_ids or [])
    }
    skill_slugs_by_id = (
        {
            row.id: row.slug
            for row in db.query(Skill.id, Skill.slug)
            .filter(Skill.id.in_(capability_skill_ids))
            .all()
        }
        if capability_skill_ids
        else {}
    )

    payload = {
        "kind": BLUEPRINT_KIND,
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "exported_by": actor,
        "source": {
            "workspace_id": workspace.id,
            "workspace_slug": workspace.slug,
            "workspace_name": workspace.name,
        },
        "workspace": {
            "name": workspace.name,
            "slug": workspace.slug,
            "mode": workspace.mode,
        },
        "experience": _serialize_workspace_experience(workspace),
        "capabilities": [
            _serialize_capability(c, workspace_id=workspace.id, skill_slugs_by_id=skill_slugs_by_id)
            for c in capabilities
        ],
        "contexts": [_serialize_context(c, systems_by_id=systems_by_id) for c in contexts],
        "systems": [
            _serialize_system(
                db=db,
                system=s,
                actor=actor,
                capabilities_by_id=capabilities_by_id,
                contexts_by_id=contexts_by_id,
            )
            for s in systems
        ],
        "knowledge": {
            "collections": [_serialize_collection(c) for c in collections],
            "exports_raw_documents": False,
            "exports_vectors": False,
        },
        "presets": {
            "rag": [
                _serialize_preset(
                    p, systems_by_id=systems_by_id, capabilities_by_id=capabilities_by_id
                )
                for p in rag_presets
            ],
            "evaluation": [
                _serialize_preset(
                    p, systems_by_id=systems_by_id, capabilities_by_id=capabilities_by_id
                )
                for p in evaluation_presets
            ],
        },
        "iam": {
            "exports_members": False,
            "role_flags": _without_secret_keys((iam_config.role_flags or {}) if iam_config else {}),
            "capability_overrides": _without_secret_keys(
                (iam_config.capability_overrides or {}) if iam_config else {}
            ),
        },
        "connectors": {
            "secure_deposit": {
                "enabled": True,
                "exports_links": False,
                "exports_passwords": False,
                "exports_files": False,
                "staging_policy": "manual_promotion",
            }
        },
        "data_policy": {
            "workspace_members": "excluded",
            "workspace_member_app_entitlements": "excluded",
            "keycloak_identities": "excluded",
            "workspace_settings": "positive_allowlist_only",
            "action_runtime_state": "excluded",
            "secure_deposit_links": "excluded",
            "secure_deposit_passwords": "excluded",
            "secure_deposit_files": "excluded",
            "raw_documents": "excluded",
            "knowledge_vectors": "excluded",
            "run_history": "excluded",
            "audit_log": "excluded",
            "collections": "metadata_only",
            "systems": "structure_and_config",
        },
    }
    emit_audit_event(
        workspace_id=workspace.id,
        event_type="workspace.blueprint.exported",
        actor=actor,
        details={
            "system_count": len(payload["systems"]),
            "capability_count": len(payload["capabilities"]),
            "collection_count": len(payload["knowledge"]["collections"]),
        },
        db=db,
    )
    return payload


def apply_workspace_blueprint(
    *,
    db: DBSession,
    workspace: Workspace,
    blueprint: Mapping[str, Any],
    actor: User | None,
    dry_run: bool = True,
    activate_systems: bool = False,
    experience_policy: str = DEFAULT_EXPERIENCE_POLICY,
    entitlement_policy: str = DEFAULT_ENTITLEMENT_POLICY,
    expected_plan_token: str | None = None,
    locked_workspace_guard: Callable[[Workspace], None] | None = None,
) -> dict[str, Any]:
    """Apply a workspace blueprint to ``workspace``.

    Dry-run is the default and performs no writes. Real import is additive:
    existing objects are reused by stable keys (slug/name/scope), and no raw
    data, members, credentials or historical runs are created.
    """
    schema_version = _validate_blueprint(blueprint)
    _validate_apply_policies(
        experience_policy=experience_policy,
        entitlement_policy=entitlement_policy,
    )
    if not dry_run:
        workspace = _lock_workspace(db, workspace)
        if locked_workspace_guard is not None:
            locked_workspace_guard(workspace)

    actor_name = actor_display_name(actor)
    blueprint_digest = _payload_digest(blueprint)
    experience_plan = _build_experience_plan(
        db=db,
        workspace=workspace,
        blueprint=blueprint,
        schema_version=schema_version,
        experience_policy=experience_policy,
        entitlement_policy=entitlement_policy,
        blueprint_digest=blueprint_digest,
        activate_systems=activate_systems,
    )
    plan_token = experience_plan["plan_token"]
    if not dry_run:
        if experience_plan["conflicts"]:
            raise WorkspaceBlueprintConflictError(
                "Blueprint experience conflicts with the target workspace; "
                "run a new dry-run or choose an explicit replacement policy."
            )
        if not expected_plan_token:
            raise WorkspaceBlueprintConflictError(
                "A plan_token from a dry-run is required before applying a workspace Blueprint."
            )
        if expected_plan_token is not None and expected_plan_token != plan_token:
            raise WorkspaceBlueprintConflictError(
                "The Blueprint plan no longer matches the target workspace. "
                "Run a new dry-run before applying."
            )

    report: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "activate_systems": bool(activate_systems),
        "workspace": {"id": workspace.id, "slug": workspace.slug, "name": workspace.name},
        "blueprint": {"schema_version": schema_version, "digest": blueprint_digest},
        "plan_token": plan_token,
        "can_apply": not bool(experience_plan["conflicts"]),
        "experience": experience_plan,
        "created": {"capabilities": 0, "contexts": 0, "collections": 0, "systems": 0, "presets": 0},
        "reused": {"capabilities": 0, "contexts": 0, "collections": 0, "systems": 0, "presets": 0},
        "skipped": [],
        "unresolved_skills": [],
        "actions": [],
    }

    capability_map = _apply_capabilities(
        db=db,
        workspace=workspace,
        capabilities=list(blueprint.get("capabilities") or []),
        dry_run=dry_run,
        report=report,
    )
    context_map = _apply_contexts(
        db=db,
        workspace=workspace,
        contexts=list(blueprint.get("contexts") or []),
        dry_run=dry_run,
        report=report,
    )
    _apply_collections(
        db=db,
        workspace=workspace,
        collections=list(((blueprint.get("knowledge") or {}).get("collections")) or []),
        actor=actor,
        dry_run=dry_run,
        report=report,
    )
    system_map = _apply_systems(
        db=db,
        workspace=workspace,
        systems=list(blueprint.get("systems") or []),
        capability_map=capability_map,
        context_map=context_map,
        actor_name=actor_name,
        dry_run=dry_run,
        activate_systems=activate_systems,
        report=report,
    )
    _apply_presets(
        db=db,
        workspace=workspace,
        presets_by_kind=blueprint.get("presets") or {},
        capability_map=capability_map,
        system_map=system_map,
        dry_run=dry_run,
        report=report,
    )
    _apply_iam_config(
        db=db,
        workspace=workspace,
        iam=blueprint.get("iam") or {},
        actor=actor,
        dry_run=dry_run,
        report=report,
    )

    if schema_version == SCHEMA_VERSION and not dry_run:
        _apply_workspace_experience_plan(
            workspace=workspace,
            plan=experience_plan,
        )
        _apply_app_access_plan(
            db=db,
            workspace=workspace,
            actor=actor,
            plan=experience_plan["app_access"],
        )

    if not dry_run:
        emit_audit_event(
            workspace_id=workspace.id,
            event_type="workspace.blueprint.applied",
            actor=actor_name,
            details={
                "source": blueprint.get("source") or {},
                "blueprint_digest": blueprint_digest,
                "schema_version": schema_version,
                "experience_policy": experience_policy,
                "entitlement_policy": entitlement_policy,
                "experience_paths_changed": len(experience_plan["applied"]),
                "created": report["created"],
                "reused": report["reused"],
                "skipped_count": len(report["skipped"]),
                "dry_run": dry_run,
            },
            db=db,
        )
    return report


def _validate_blueprint(blueprint: Mapping[str, Any]) -> int:
    if not isinstance(blueprint, Mapping):
        raise WorkspaceBlueprintError("Blueprint must be a JSON object.")
    if blueprint.get("kind") != BLUEPRINT_KIND:
        raise WorkspaceBlueprintError(
            f"Unexpected blueprint kind: {blueprint.get('kind')!r} (expected {BLUEPRINT_KIND!r})."
        )
    version = blueprint.get("schema_version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version not in SUPPORTED_SCHEMA_VERSIONS
    ):
        raise WorkspaceBlueprintError(
            f"Unsupported schema_version: {version!r} "
            f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)})."
        )
    for key in ("capabilities", "contexts", "systems"):
        value = blueprint.get(key)
        if value is not None and (
            not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value)
        ):
            raise WorkspaceBlueprintError(f"{key} must be an array of JSON objects.")
    _validate_system_contracts(list(blueprint.get("systems") or []))
    knowledge = blueprint.get("knowledge")
    if knowledge is not None and not isinstance(knowledge, Mapping):
        raise WorkspaceBlueprintError("knowledge must be a JSON object.")
    if isinstance(knowledge, Mapping):
        collections = knowledge.get("collections")
        if collections is not None and (
            not isinstance(collections, list)
            or any(not isinstance(item, Mapping) for item in collections)
        ):
            raise WorkspaceBlueprintError("knowledge.collections must be an array of JSON objects.")
    for key in ("presets", "iam"):
        value = blueprint.get(key)
        if value is not None and not isinstance(value, Mapping):
            raise WorkspaceBlueprintError(f"{key} must be a JSON object.")
    presets = blueprint.get("presets")
    if isinstance(presets, Mapping):
        for kind in ("rag", "evaluation"):
            items = presets.get(kind)
            if items is not None and (
                not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items)
            ):
                raise WorkspaceBlueprintError(f"presets.{kind} must be an array of JSON objects.")
    _validate_portable_config_security(blueprint)
    if version == SCHEMA_VERSION:
        _validate_v2_experience(blueprint)
    return int(version)


def _validate_system_contracts(systems: list[Mapping[str, Any]]) -> None:
    for index, item in enumerate(systems):
        raw_mode = item.get("execution_mode")
        if raw_mode is not None:
            mode = _string(raw_mode)
            if mode not in PORTABLE_EXECUTION_MODES:
                raise WorkspaceBlueprintError(
                    f"systems[{index}].execution_mode is not canonical: {raw_mode!r}."
                )
        raw_status = item.get("source_status")
        if raw_status is not None:
            status = _string(raw_status)
            if status not in PORTABLE_SYSTEM_STATUSES:
                raise WorkspaceBlueprintError(
                    f"systems[{index}].source_status is not canonical: {raw_status!r}."
                )


def _validate_portable_config_security(blueprint: Mapping[str, Any]) -> None:
    """Reject credential-shaped fields in every configuration we import."""

    for index, item in enumerate(blueprint.get("capabilities") or []):
        for key in ("pricing", "sla", "roi_model"):
            if key in item:
                _assert_no_secret_keys(item[key], f"/capabilities/{index}/{key}")
    for index, item in enumerate(blueprint.get("contexts") or []):
        for key in (
            "data_refs",
            "memory_refs",
            "history_refs",
            "environment_state",
            "business_constraints",
            "permissions",
        ):
            if key in item:
                _assert_no_secret_keys(item[key], f"/contexts/{index}/{key}")
    for index, item in enumerate(blueprint.get("systems") or []):
        for key in ("flow_definition", "execution_profile"):
            if key in item:
                _assert_no_secret_keys(item[key], f"/systems/{index}/{key}")
    knowledge = _as_dict(blueprint.get("knowledge"))
    for index, item in enumerate(knowledge.get("collections") or []):
        if "chunking_params" in item:
            _assert_no_secret_keys(
                item["chunking_params"],
                f"/knowledge/collections/{index}/chunking_params",
            )
    presets = _as_dict(blueprint.get("presets"))
    for kind in ("rag", "evaluation"):
        for index, item in enumerate(presets.get(kind) or []):
            if "config" in item:
                _assert_no_secret_keys(item["config"], f"/presets/{kind}/{index}/config")
    iam = _as_dict(blueprint.get("iam"))
    for key in ("role_flags", "capability_overrides"):
        if key in iam:
            _assert_no_secret_keys(iam[key], f"/iam/{key}")


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for raw in value:
        item = _string(raw)
        if item and item not in out:
            out.append(item)
    return out


def _credential_shaped_key(value: Any) -> bool:
    text = str(value).strip()
    snake_case = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", snake_case).strip("_").lower()
    return normalized in _CREDENTIAL_KEY_NAMES or normalized.endswith(_CREDENTIAL_KEY_SUFFIXES)


def _mapping_declares_credential(value: Mapping[Any, Any]) -> bool:
    """Detect indirections such as {name: OPENAI_API_KEY, value: ...}."""

    for key, item in value.items():
        normalized_key = str(key).strip().lower().replace("-", "_")
        if (
            normalized_key in _CREDENTIAL_DESCRIPTOR_KEYS
            and isinstance(item, str)
            and _credential_shaped_key(item)
        ):
            return True
    return False


def _contains_inline_credential(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if re.match(r"^bearer\s+\S+", text, re.IGNORECASE):
        return True
    try:
        parsed = urlsplit(text)
    except ValueError:
        return False
    if (
        parsed.scheme
        and parsed.netloc
        and (parsed.username is not None or parsed.password is not None)
    ):
        return True
    return any(_credential_shaped_key(key) for key, _item in parse_qsl(parsed.query))


def _without_secret_keys(value: Any) -> Any:
    """Copy portable JSON while dropping credential keys and inline values."""

    if isinstance(value, Mapping):
        if _mapping_declares_credential(value):
            return {}
        return {
            str(key): _without_secret_keys(item)
            for key, item in value.items()
            if not _credential_shaped_key(key) and not _contains_inline_credential(item)
        }
    if isinstance(value, list):
        return [
            _without_secret_keys(item)
            for item in value
            if not _contains_inline_credential(item)
            and not (isinstance(item, Mapping) and _mapping_declares_credential(item))
        ]
    if isinstance(value, tuple):
        return [
            _without_secret_keys(item)
            for item in value
            if not _contains_inline_credential(item)
            and not (isinstance(item, Mapping) and _mapping_declares_credential(item))
        ]
    if _contains_inline_credential(value):
        return None
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _sanitize_brand(value: Any) -> dict[str, Any]:
    source = _as_dict(value)
    out: dict[str, Any] = {}
    for key in PORTABLE_BRAND_KEYS:
        if key not in source:
            continue
        if key == "lines":
            lines = _string_list(source[key])
            if lines:
                out[key] = lines
        else:
            item = _string(source[key])
            if item:
                out[key] = item
    return out


def _sanitize_actions(value: Any) -> dict[str, Any]:
    source = _as_dict(value)
    out: dict[str, Any] = {}
    for key in PORTABLE_ACTION_KEYS:
        if key not in source:
            continue
        if key.endswith("_packs") or key.endswith("_actions"):
            values = _string_list(source[key])
            if values:
                out[key] = values
        elif key == "confirmation_policy":
            item = _string(source[key])
            if item:
                out[key] = item
    return out


def _sanitize_simple_config(value: Any, allowed_keys: tuple[str, ...]) -> dict[str, Any]:
    source = _as_dict(value)
    return {
        key: _without_secret_keys(deepcopy(source[key]))
        for key in allowed_keys
        if key in source
        and (
            source[key] is None
            or isinstance(source[key], str | int | float | bool | list | Mapping)
        )
    }


def _sanitize_prompt_pack(value: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for raw in value if isinstance(value, list) else []:
        source = _as_dict(raw)
        item = {
            key: text for key in ("icon", "label", "prompt") if (text := _string(source.get(key)))
        }
        if item:
            out.append(item)
    return out


def _sanitize_assistant_profile(value: Any) -> dict[str, Any] | None:
    source = _as_dict(value)
    key = _string(source.get("key"))
    if not key or not _PROFILE_KEY_RE.match(key):
        return None
    out: dict[str, Any] = {"key": key}
    for field in ("label", "subtitle", "default_knowledge_scope", "tone"):
        if text := _string(source.get(field)):
            out[field] = text
    if "executive_mode" in source and isinstance(source["executive_mode"], bool):
        out["executive_mode"] = source["executive_mode"]
    grounding = _sanitize_simple_config(source.get("grounding"), PORTABLE_GROUNDING_KEYS)
    if grounding:
        out["grounding"] = grounding
    actions = _sanitize_actions(source.get("actions"))
    if actions:
        out["actions"] = actions
    voice_loop = _sanitize_simple_config(source.get("voice_loop"), PORTABLE_VOICE_LOOP_KEYS)
    if voice_loop:
        out["voice_loop"] = voice_loop
    voice_output = _sanitize_simple_config(source.get("voice_output"), PORTABLE_VOICE_OUTPUT_KEYS)
    if voice_output:
        out["voice_output"] = voice_output
    response_style = _sanitize_simple_config(
        source.get("response_style"), PORTABLE_RESPONSE_STYLE_KEYS
    )
    if response_style:
        out["response_style"] = response_style
    for field in ("allowed_actions", "allowed_calendar_actions", "hidden_controls"):
        values = _string_list(source.get(field))
        if values:
            out[field] = values
    prompt_pack = _sanitize_prompt_pack(source.get("prompt_pack"))
    if prompt_pack:
        out["prompt_pack"] = prompt_pack
    return out


def _sanitize_assistant_profiles(value: Any) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value if isinstance(value, list) else []:
        profile = _sanitize_assistant_profile(raw)
        if not profile or profile["key"] in seen:
            continue
        seen.add(profile["key"])
        profiles.append(profile)
    return profiles


def _sanitize_knowledge_scopes(value: Any) -> list[dict[str, Any]]:
    scopes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value if isinstance(value, list) else []:
        source = _as_dict(raw)
        key = _string(source.get("key"))
        collections = _string_list(source.get("collection_slugs"))
        if not key or not _PROFILE_KEY_RE.match(key) or not collections or key in seen:
            continue
        seen.add(key)
        item = _sanitize_simple_config(source, PORTABLE_KNOWLEDGE_SCOPE_KEYS)
        item["key"] = key
        item["collection_slugs"] = collections
        scopes.append(item)
    return scopes


def _sanitize_navigation_items(value: Any) -> list[dict[str, str]] | None:
    if not isinstance(value, list):
        return None
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value:
        source = _as_dict(raw)
        item: dict[str, str] = {}
        for field in ("key", "label", "glyph", "variant", "object"):
            text = _string(source.get(field))
            if not text:
                return None
            item[field] = text
        if item["key"] in seen:
            return None
        seen.add(item["key"])
        items.append(item)
    return items or None


def _sanitize_typed_config(
    value: Any,
    *,
    string_keys: tuple[str, ...] = (),
    boolean_keys: tuple[str, ...] = (),
    numeric_keys: tuple[str, ...] = (),
    string_list_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    source = _as_dict(value)
    out: dict[str, Any] = {}
    for key in string_keys:
        if text := _string(source.get(key)):
            out[key] = text
    for key in boolean_keys:
        if isinstance(source.get(key), bool):
            out[key] = source[key]
    for key in numeric_keys:
        item = source.get(key)
        if not isinstance(item, bool) and isinstance(item, int | float) and item >= 0:
            out[key] = item
    for key in string_list_keys:
        values = _string_list(source.get(key))
        if values:
            out[key] = values
    return out


def _sanitize_document_profiles(value: Any) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value if isinstance(value, list) else []:
        source = _as_dict(raw)
        key = _string(source.get("key"))
        if not key or not _PROFILE_KEY_RE.match(key) or key in seen:
            continue
        seen.add(key)
        profile = _sanitize_typed_config(
            source,
            string_keys=("key", "label"),
            numeric_keys=("max_candidate_facts", "max_evidence_rows"),
        )
        synonyms: dict[str, list[str]] = {}
        for raw_name, raw_values in _as_dict(source.get("synonyms")).items():
            name = _string(raw_name)
            values = _string_list(raw_values)
            if name and _PROFILE_KEY_RE.match(name) and values:
                synonyms[name] = values
        if synonyms:
            profile["synonyms"] = synonyms
        profiles.append(profile)
    return profiles


def _sanitize_document_intelligence(value: Any) -> dict[str, Any]:
    source = _as_dict(value)
    out = _sanitize_typed_config(
        source,
        string_keys=("default_profile", "citation_policy"),
        boolean_keys=("enabled",),
    )
    profiles = _sanitize_document_profiles(source.get("profiles"))
    if profiles:
        out["profiles"] = profiles
    ocr = _sanitize_typed_config(
        source.get("ocr"),
        boolean_keys=("enabled", "required", "openai_vision_enabled"),
        numeric_keys=("min_confidence", "timeout_seconds"),
        string_list_keys=("provider_priority", "languages"),
    )
    if ocr:
        out["ocr"] = ocr
    return out


def _sanitize_mission_dependencies(settings: Mapping[str, Any]) -> dict[str, Any]:
    dependencies: dict[str, Any] = {}
    calendar = _sanitize_typed_config(
        settings.get("calendar"),
        string_keys=PORTABLE_CALENDAR_KEYS,
    )
    if calendar:
        dependencies["calendar"] = calendar
    action_planner = _sanitize_typed_config(
        settings.get("action_planner"),
        string_keys=("write_policy", "default_owner"),
        boolean_keys=("advisory_only",),
    )
    if action_planner:
        dependencies["action_planner"] = action_planner
    document_intelligence = _sanitize_document_intelligence(settings.get("document_intelligence"))
    if document_intelligence:
        dependencies["document_intelligence"] = document_intelligence
    visual_intelligence = _sanitize_typed_config(
        settings.get("visual_intelligence"),
        string_keys=("storage_policy", "analysis_policy", "source_model"),
        boolean_keys=("enabled",),
        numeric_keys=("capture_cadence_minutes",),
        string_list_keys=("allowed_adapters",),
    )
    if visual_intelligence:
        dependencies["visual_intelligence"] = visual_intelligence
    feature_flags = {
        key: value
        for key in PORTABLE_MISSION_FEATURE_FLAG_KEYS
        if isinstance((value := _as_dict(settings.get("feature_flag")).get(key)), bool)
    }
    if feature_flags:
        dependencies["feature_flags"] = feature_flags
    connectors: dict[str, Any] = {}
    raw_connectors = _as_dict(settings.get("connectors"))
    for key in PORTABLE_MISSION_CONNECTOR_KEYS:
        connector = _sanitize_typed_config(
            raw_connectors.get(key),
            string_keys=("status", "mode", "label"),
            boolean_keys=("enabled",),
        )
        if connector:
            connectors[key] = connector
    if connectors:
        dependencies["connectors"] = connectors
    return dependencies


def _sanitize_mission_room(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    source = dict(value)
    config: dict[str, Any] = {}
    for key in PORTABLE_MISSION_ROOM_KEYS:
        if key not in source:
            continue
        if key == "brand":
            brand = _sanitize_brand(source[key])
            if brand:
                config[key] = brand
        elif key == "navigation":
            navigation = _sanitize_navigation_items(source[key])
            if navigation:
                config[key] = navigation
        elif key == "region_scope":
            values = _string_list(source[key])
            if values:
                config[key] = values
        else:
            item = _string(source[key])
            if item:
                config[key] = item
    if "enabled" not in source and not config:
        return None
    return {"enabled": source.get("enabled") is True, "config": config}


def _serialize_workspace_experience(workspace: Workspace) -> dict[str, Any]:
    settings = _as_dict(workspace.settings)
    raw_features = _as_dict(settings.get("features"))
    features = {
        key: raw_features[key]
        for key in PORTABLE_FEATURE_KEYS
        if isinstance(raw_features.get(key), bool)
    }
    profile: dict[str, Any] = {}
    for key in PORTABLE_PROFILE_KEYS:
        if key == "hide_provider_details":
            if isinstance(settings.get(key), bool):
                profile[key] = settings[key]
        elif key == "family":
            # Runtime resolution is deliberately fail-safe: malformed or
            # pre-migration values behave as ``generic`` and must never be
            # re-exported as a new non-canonical contract value.
            profile[key] = workspace_family(workspace)
        elif text := _string(settings.get(key)):
            profile[key] = text

    raw_navigation = _as_dict(settings.get("navigation_profile"))
    navigation: dict[str, Any] = {}
    for key in PORTABLE_NAVIGATION_KEYS:
        if key == "primary_surfaces":
            values = _string_list(raw_navigation.get(key))
            if values:
                navigation[key] = values
        elif text := _string(raw_navigation.get(key)):
            navigation[key] = text

    shell: dict[str, Any] = {}
    for key in PORTABLE_SHELL_KEYS:
        if key == "workspace_app_brand":
            brand = _sanitize_brand(settings.get(key))
            if brand:
                shell[key] = brand
        elif text := _string(settings.get(key)):
            shell[key] = text

    assistant: dict[str, Any] = {}
    if default_profile := _string(settings.get("assistant_profile_default")):
        assistant["default_profile"] = default_profile
    profiles = _sanitize_assistant_profiles(settings.get("assistant_profiles"))
    if profiles:
        assistant["profiles"] = profiles
    scopes = _sanitize_knowledge_scopes(settings.get("knowledge_scopes"))
    if scopes:
        assistant["knowledge_scopes"] = scopes
    voice_loop = _sanitize_simple_config(settings.get("voice_loop"), PORTABLE_VOICE_LOOP_KEYS)
    if voice_loop:
        assistant["voice_loop"] = voice_loop
    voice_output = _sanitize_simple_config(settings.get("voice_output"), PORTABLE_VOICE_OUTPUT_KEYS)
    if voice_output:
        assistant["voice_output"] = voice_output

    actions = _sanitize_actions(settings.get("actions"))
    extensions: dict[str, Any] = {}
    mission_room = _sanitize_mission_room(settings.get("mission_room"))
    if mission_room is not None:
        dependencies = _sanitize_mission_dependencies(settings)
        if dependencies:
            mission_room["dependencies"] = dependencies
        extensions[MISSION_ROOM_EXTENSION_ID] = mission_room

    declared_apps = _string_list(navigation.get("primary_surfaces"))
    required_apps = [key for key in BUSINESS_APP_KEYS if key in declared_apps]
    if not required_apps:
        required_apps = list(BUSINESS_APP_KEYS)
    app_access = {
        "enforcement_requested": raw_features.get(APP_ENTITLEMENTS_FEATURE) is True,
        "required_apps": required_apps,
        "member_grants": "excluded",
    }
    return {
        "contract_version": 1,
        "profile": profile,
        "features": features,
        "navigation": navigation,
        "shell": shell,
        "assistant": assistant,
        "actions": actions,
        "extensions": extensions,
        "app_access": app_access,
    }


def _assert_known_keys(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(str(key) for key in value if key not in allowed)
    if unknown:
        raise WorkspaceBlueprintError(f"Unknown fields at {path}: {', '.join(unknown)}.")


def _assert_no_secret_keys(value: Any, path: str = "/experience") -> None:
    if _contains_inline_credential(value):
        raise WorkspaceBlueprintError(f"Credential-shaped value is not portable: {path}.")
    if isinstance(value, Mapping):
        if _mapping_declares_credential(value):
            raise WorkspaceBlueprintError(f"Credential-shaped indirection is not portable: {path}.")
        for key, item in value.items():
            key_text = str(key)
            if _credential_shaped_key(key_text):
                raise WorkspaceBlueprintError(
                    f"Credential-shaped field is not portable: {path}/{key_text}."
                )
            _assert_no_secret_keys(item, f"{path}/{key_text}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_secret_keys(item, f"{path}/{index}")


def _validate_route(value: Any, path: str, *, prefix: str | None = None) -> None:
    route = _string(value)
    if not route or not route.startswith("/"):
        raise WorkspaceBlueprintError(f"{path} must be an absolute application route.")
    route_path = route.split("?", 1)[0].split("#", 1)[0]
    if prefix and route_path != prefix and not route_path.startswith(f"{prefix}/"):
        raise WorkspaceBlueprintError(f"{path} must stay under {prefix}.")


def _action_catalog() -> tuple[set[str], set[str]]:
    from app.services.actions.registry import PACKS, all_action_manifests

    packs = set(PACKS)
    actions = {manifest.action_id for manifest in all_action_manifests()}
    return packs, actions


def _validate_actions_payload(value: Any, path: str) -> None:
    if not isinstance(value, Mapping):
        raise WorkspaceBlueprintError(f"{path} must be a JSON object.")
    _assert_known_keys(value, set(PORTABLE_ACTION_KEYS), path)
    known_packs, known_actions = _action_catalog()
    for key in ("enabled_packs", "hidden_packs"):
        if key not in value:
            continue
        raw = value[key]
        if not isinstance(raw, list) or any(not _string(item) for item in raw):
            raise WorkspaceBlueprintError(f"{path}/{key} must be an array of strings.")
        normalized = _string_list(raw)
        unknown = sorted(set(normalized) - known_packs)
        if unknown:
            raise WorkspaceBlueprintError(
                f"Unknown action packs at {path}/{key}: {', '.join(unknown)}."
            )
        if normalized != raw:
            raise WorkspaceBlueprintError(
                f"Action packs at {path}/{key} must be trimmed and unique."
            )
    for key in ("enabled_actions", "hidden_actions"):
        if key not in value:
            continue
        raw = value[key]
        if not isinstance(raw, list) or any(not _string(item) for item in raw):
            raise WorkspaceBlueprintError(f"{path}/{key} must be an array of strings.")
        normalized = _string_list(raw)
        unknown = sorted(set(normalized) - known_actions)
        if unknown:
            raise WorkspaceBlueprintError(f"Unknown actions at {path}/{key}: {', '.join(unknown)}.")
        if normalized != raw:
            raise WorkspaceBlueprintError(f"Actions at {path}/{key} must be trimmed and unique.")
    pack_overlap = set(_string_list(value.get("enabled_packs"))) & set(
        _string_list(value.get("hidden_packs"))
    )
    if pack_overlap:
        raise WorkspaceBlueprintError(
            f"Action packs cannot be both enabled and hidden at {path}: "
            + ", ".join(sorted(pack_overlap))
        )
    action_overlap = set(_string_list(value.get("enabled_actions"))) & set(
        _string_list(value.get("hidden_actions"))
    )
    if action_overlap:
        raise WorkspaceBlueprintError(
            f"Actions cannot be both enabled and hidden at {path}: "
            + ", ".join(sorted(action_overlap))
        )
    if "confirmation_policy" in value and value["confirmation_policy"] not in {
        "confirm",
        "confirm_side_effects",
        "direct_safe",
    }:
        raise WorkspaceBlueprintError(
            f"Unsupported confirmation policy at {path}/confirmation_policy."
        )


def _validate_navigation_items(value: Any, path: str) -> None:
    if not isinstance(value, list) or not value:
        raise WorkspaceBlueprintError(f"{path} must be a non-empty array.")
    seen: set[str] = set()
    required = {"key", "label", "glyph", "variant", "object"}
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise WorkspaceBlueprintError(f"{path}/{index} must be a JSON object.")
        _assert_known_keys(raw, required, f"{path}/{index}")
        if set(raw) != required or any(not _string(raw.get(key)) for key in required):
            raise WorkspaceBlueprintError(
                f"{path}/{index} must define key, label, glyph, variant and object."
            )
        key = str(raw["key"])
        if key in seen:
            raise WorkspaceBlueprintError(f"Duplicate navigation key at {path}: {key}.")
        seen.add(key)


def _validate_string_array(value: Any, path: str, *, allow_empty: bool = False) -> None:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or any(not _string(item) for item in value)
        or len(_string_list(value)) != len(value)
    ):
        raise WorkspaceBlueprintError(f"{path} must be an array of unique non-empty strings.")


def _validate_brand_payload(value: Any, path: str) -> None:
    if not isinstance(value, Mapping):
        raise WorkspaceBlueprintError(f"{path} must be a JSON object.")
    _assert_known_keys(value, set(PORTABLE_BRAND_KEYS), path)
    for key, item in value.items():
        if key == "lines":
            _validate_string_array(item, f"{path}/lines")
        elif not _string(item):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a non-empty string.")


def _validate_allowed_config(value: Any, allowed: tuple[str, ...], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkspaceBlueprintError(f"{path} must be a JSON object.")
    _assert_known_keys(value, set(allowed), path)
    return value


def _validate_grounding_payload(value: Any, path: str) -> None:
    config = _validate_allowed_config(value, PORTABLE_GROUNDING_KEYS, path)
    for key in ("default_mode", "fallback_disclaimer"):
        if key in config and not _string(config[key]):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a string.")
    if "allowed_modes" in config:
        _validate_string_array(config["allowed_modes"], f"{path}/allowed_modes")
    if "strict_guard" in config and not (
        isinstance(config["strict_guard"], bool) or _string(config["strict_guard"])
    ):
        raise WorkspaceBlueprintError(
            f"{path}/strict_guard must be a boolean or named guard policy."
        )


def _validate_voice_loop_payload(value: Any, path: str) -> None:
    config = _validate_allowed_config(value, PORTABLE_VOICE_LOOP_KEYS, path)
    boolean_keys = {
        "enabled_default",
        "manual_start_required",
        "auto_send_final_transcript",
        "auto_endpoint",
        "auto_rearm_after_tts",
        "barge_in",
        "commands_enabled",
    }
    numeric_keys = {
        "silence_ms",
        "dictation_silence_ms",
        "min_speech_ms",
        "dictation_min_speech_ms",
        "max_turn_ms",
        "cooldown_ms",
        "rms_threshold",
        "endpoint_grace_ms",
        "vad_hangover_ms",
        "vad_calibration_ms",
        "vad_min_silence_frames_ms",
    }
    for key in boolean_keys:
        if key in config and not isinstance(config[key], bool):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a boolean.")
    for key in numeric_keys:
        if key in config and (
            isinstance(config[key], bool)
            or not isinstance(config[key], int | float)
            or config[key] < 0
        ):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a non-negative number.")
    for key in ("default_mode", "trigger_word"):
        if key in config and not _string(config[key]):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a string.")
    if "stop_phrases" in config:
        _validate_string_array(config["stop_phrases"], f"{path}/stop_phrases")
    if "command_packs" in config:
        _validate_command_packs(config["command_packs"], f"{path}/command_packs")


def _validate_voice_output_payload(value: Any, path: str) -> None:
    config = _validate_allowed_config(value, PORTABLE_VOICE_OUTPUT_KEYS, path)
    for key in ("latency_profile", "voice"):
        if key in config and not _string(config[key]):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a string.")
    for key in ("flush_first_chars", "flush_next_chars", "flush_timeout_ms"):
        if key in config and (
            isinstance(config[key], bool)
            or not isinstance(config[key], int | float)
            or config[key] < 0
        ):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a non-negative number.")
    if "interrupt_on_user_speech" in config and not isinstance(
        config["interrupt_on_user_speech"], bool
    ):
        raise WorkspaceBlueprintError(f"{path}/interrupt_on_user_speech must be a boolean.")


def _validate_response_style_payload(value: Any, path: str) -> None:
    config = _validate_allowed_config(value, PORTABLE_RESPONSE_STYLE_KEYS, path)
    for key in ("address_as", "tone", "format"):
        if key in config and not _string(config[key]):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a string.")
    if "max_bullets" in config and (
        isinstance(config["max_bullets"], bool)
        or not isinstance(config["max_bullets"], int)
        or config["max_bullets"] < 0
    ):
        raise WorkspaceBlueprintError(f"{path}/max_bullets must be a non-negative integer.")


def _validate_prompt_pack(value: Any, path: str) -> None:
    if not isinstance(value, list):
        raise WorkspaceBlueprintError(f"{path} must be an array.")
    allowed = {"icon", "label", "prompt"}
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise WorkspaceBlueprintError(f"{path}/{index} must be a JSON object.")
        _assert_known_keys(item, allowed, f"{path}/{index}")
        if not item or any(not _string(raw) for raw in item.values()):
            raise WorkspaceBlueprintError(f"{path}/{index} values must be non-empty strings.")


def _validate_assistant_payload(value: Any, path: str) -> None:
    if not isinstance(value, Mapping):
        raise WorkspaceBlueprintError(f"{path} must be a JSON object.")
    allowed = {
        "default_profile",
        "profiles",
        "knowledge_scopes",
        "voice_loop",
        "voice_output",
    }
    _assert_known_keys(value, allowed, path)
    if "default_profile" in value and not _string(value["default_profile"]):
        raise WorkspaceBlueprintError(f"{path}/default_profile must be a string.")
    profiles = value.get("profiles")
    if profiles is not None:
        if not isinstance(profiles, list):
            raise WorkspaceBlueprintError(f"{path}/profiles must be an array.")
        seen: set[str] = set()
        for index, raw in enumerate(profiles):
            if not isinstance(raw, Mapping):
                raise WorkspaceBlueprintError(f"{path}/profiles/{index} must be an object.")
            _assert_known_keys(
                raw,
                set(PORTABLE_ASSISTANT_PROFILE_KEYS),
                f"{path}/profiles/{index}",
            )
            key = _string(raw.get("key"))
            if not key or not _PROFILE_KEY_RE.match(key) or key in seen:
                raise WorkspaceBlueprintError(
                    f"Invalid or duplicate assistant profile key at {path}/profiles/{index}."
                )
            seen.add(key)
            for field in (
                "label",
                "subtitle",
                "default_knowledge_scope",
                "tone",
            ):
                if field in raw and not _string(raw[field]):
                    raise WorkspaceBlueprintError(
                        f"{path}/profiles/{index}/{field} must be a string."
                    )
            if "executive_mode" in raw and not isinstance(raw["executive_mode"], bool):
                raise WorkspaceBlueprintError(
                    f"{path}/profiles/{index}/executive_mode must be a boolean."
                )
            if "grounding" in raw:
                _validate_grounding_payload(raw["grounding"], f"{path}/profiles/{index}/grounding")
            if "actions" in raw:
                _validate_actions_payload(raw["actions"], f"{path}/profiles/{index}/actions")
            if "voice_loop" in raw:
                _validate_voice_loop_payload(
                    raw["voice_loop"], f"{path}/profiles/{index}/voice_loop"
                )
            if "voice_output" in raw:
                _validate_voice_output_payload(
                    raw["voice_output"], f"{path}/profiles/{index}/voice_output"
                )
            if "response_style" in raw:
                _validate_response_style_payload(
                    raw["response_style"],
                    f"{path}/profiles/{index}/response_style",
                )
            for field in (
                "allowed_actions",
                "allowed_calendar_actions",
                "hidden_controls",
            ):
                if field in raw:
                    _validate_string_array(raw[field], f"{path}/profiles/{index}/{field}")
            if "prompt_pack" in raw:
                _validate_prompt_pack(raw["prompt_pack"], f"{path}/profiles/{index}/prompt_pack")
    scopes = value.get("knowledge_scopes")
    if scopes is not None:
        if not isinstance(scopes, list):
            raise WorkspaceBlueprintError(f"{path}/knowledge_scopes must be an array.")
        for index, raw in enumerate(scopes):
            if not isinstance(raw, Mapping):
                raise WorkspaceBlueprintError(f"{path}/knowledge_scopes/{index} must be an object.")
            _assert_known_keys(
                raw,
                set(PORTABLE_KNOWLEDGE_SCOPE_KEYS),
                f"{path}/knowledge_scopes/{index}",
            )
            if not _string(raw.get("key")) or not _string_list(raw.get("collection_slugs")):
                raise WorkspaceBlueprintError(
                    f"{path}/knowledge_scopes/{index} needs key and collection_slugs."
                )
            _validate_string_array(
                raw["collection_slugs"],
                f"{path}/knowledge_scopes/{index}/collection_slugs",
            )
    if "voice_loop" in value:
        _validate_voice_loop_payload(value["voice_loop"], f"{path}/voice_loop")
    if "voice_output" in value:
        _validate_voice_output_payload(value["voice_output"], f"{path}/voice_output")


def _validate_command_packs(value: Any, path: str) -> None:
    if not isinstance(value, list) or any(not _string(item) for item in value):
        raise WorkspaceBlueprintError(f"{path} must be an array of strings.")
    known_packs, _known_actions = _action_catalog()
    normalized = _string_list(value)
    unknown = sorted(set(normalized) - known_packs)
    if unknown:
        raise WorkspaceBlueprintError(f"Unknown command packs at {path}: {', '.join(unknown)}.")
    if normalized != value:
        raise WorkspaceBlueprintError(f"Command packs at {path} must be trimmed and unique.")


def _all_enabled_packs(experience: Mapping[str, Any]) -> set[str]:
    packs = set(_string_list(_as_dict(experience.get("actions")).get("enabled_packs")))
    assistant = _as_dict(experience.get("assistant"))
    packs.update(_string_list(_as_dict(assistant.get("voice_loop")).get("command_packs")))
    for raw in assistant.get("profiles") if isinstance(assistant.get("profiles"), list) else []:
        profile = _as_dict(raw)
        packs.update(_string_list(_as_dict(profile.get("actions")).get("enabled_packs")))
        packs.update(_string_list(_as_dict(profile.get("voice_loop")).get("command_packs")))
    return packs


def _all_enabled_actions(experience: Mapping[str, Any]) -> set[str]:
    actions = set(_string_list(_as_dict(experience.get("actions")).get("enabled_actions")))
    assistant = _as_dict(experience.get("assistant"))
    for raw in assistant.get("profiles") if isinstance(assistant.get("profiles"), list) else []:
        actions.update(_string_list(_as_dict(_as_dict(raw).get("actions")).get("enabled_actions")))
    return actions


def _validate_typed_config_payload(
    value: Any,
    *,
    path: str,
    allowed: tuple[str, ...],
    string_keys: tuple[str, ...] = (),
    boolean_keys: tuple[str, ...] = (),
    numeric_keys: tuple[str, ...] = (),
    string_list_keys: tuple[str, ...] = (),
) -> Mapping[str, Any]:
    config = _validate_allowed_config(value, allowed, path)
    for key in string_keys:
        if key in config and not _string(config[key]):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a string.")
    for key in boolean_keys:
        if key in config and not isinstance(config[key], bool):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a boolean.")
    for key in numeric_keys:
        if key in config and (
            isinstance(config[key], bool)
            or not isinstance(config[key], int | float)
            or config[key] < 0
        ):
            raise WorkspaceBlueprintError(f"{path}/{key} must be a non-negative number.")
    for key in string_list_keys:
        if key in config:
            _validate_string_array(config[key], f"{path}/{key}")
    return config


def _validate_document_intelligence(value: Any, path: str) -> None:
    config = _validate_typed_config_payload(
        value,
        path=path,
        allowed=PORTABLE_DOCUMENT_INTELLIGENCE_KEYS,
        string_keys=("default_profile", "citation_policy"),
        boolean_keys=("enabled",),
    )
    profiles = config.get("profiles")
    if profiles is not None:
        if not isinstance(profiles, list):
            raise WorkspaceBlueprintError(f"{path}/profiles must be an array.")
        seen: set[str] = set()
        for index, raw in enumerate(profiles):
            profile_path = f"{path}/profiles/{index}"
            profile = _validate_typed_config_payload(
                raw,
                path=profile_path,
                allowed=PORTABLE_DOCUMENT_PROFILE_KEYS,
                string_keys=("key", "label"),
                numeric_keys=("max_candidate_facts", "max_evidence_rows"),
            )
            key = _string(profile.get("key"))
            if not key or not _PROFILE_KEY_RE.match(key) or key in seen:
                raise WorkspaceBlueprintError(
                    f"Invalid or duplicate document profile key at {profile_path}."
                )
            seen.add(key)
            synonyms = profile.get("synonyms")
            if synonyms is not None:
                if not isinstance(synonyms, Mapping):
                    raise WorkspaceBlueprintError(f"{profile_path}/synonyms must be a JSON object.")
                for synonym, values in synonyms.items():
                    if not _string(synonym) or not _PROFILE_KEY_RE.match(str(synonym)):
                        raise WorkspaceBlueprintError(
                            f"Invalid synonym group at {profile_path}/synonyms."
                        )
                    _validate_string_array(
                        values,
                        f"{profile_path}/synonyms/{synonym}",
                    )
    if "ocr" in config:
        ocr = _validate_typed_config_payload(
            config["ocr"],
            path=f"{path}/ocr",
            allowed=PORTABLE_OCR_KEYS,
            boolean_keys=("enabled", "required", "openai_vision_enabled"),
            numeric_keys=("min_confidence", "timeout_seconds"),
            string_list_keys=("provider_priority", "languages"),
        )
        if "min_confidence" in ocr and ocr["min_confidence"] > 1:
            raise WorkspaceBlueprintError(f"{path}/ocr/min_confidence must be at most 1.")


def _validate_mission_dependencies(value: Any, path: str) -> None:
    if not isinstance(value, Mapping):
        raise WorkspaceBlueprintError(f"{path} must be a JSON object.")
    _assert_known_keys(value, set(PORTABLE_MISSION_DEPENDENCY_KEYS), path)
    if "calendar" in value:
        _validate_typed_config_payload(
            value["calendar"],
            path=f"{path}/calendar",
            allowed=PORTABLE_CALENDAR_KEYS,
            string_keys=PORTABLE_CALENDAR_KEYS,
        )
    if "action_planner" in value:
        _validate_typed_config_payload(
            value["action_planner"],
            path=f"{path}/action_planner",
            allowed=PORTABLE_ACTION_PLANNER_KEYS,
            string_keys=("write_policy", "default_owner"),
            boolean_keys=("advisory_only",),
        )
    if "document_intelligence" in value:
        _validate_document_intelligence(
            value["document_intelligence"], f"{path}/document_intelligence"
        )
    if "visual_intelligence" in value:
        _validate_typed_config_payload(
            value["visual_intelligence"],
            path=f"{path}/visual_intelligence",
            allowed=PORTABLE_VISUAL_INTELLIGENCE_KEYS,
            string_keys=("storage_policy", "analysis_policy", "source_model"),
            boolean_keys=("enabled",),
            numeric_keys=("capture_cadence_minutes",),
            string_list_keys=("allowed_adapters",),
        )
    if "feature_flags" in value:
        flags = _validate_allowed_config(
            value["feature_flags"],
            PORTABLE_MISSION_FEATURE_FLAG_KEYS,
            f"{path}/feature_flags",
        )
        if any(not isinstance(item, bool) for item in flags.values()):
            raise WorkspaceBlueprintError(f"{path}/feature_flags values must be booleans.")
    if "connectors" in value:
        connectors = _validate_allowed_config(
            value["connectors"],
            PORTABLE_MISSION_CONNECTOR_KEYS,
            f"{path}/connectors",
        )
        for key, connector in connectors.items():
            _validate_typed_config_payload(
                connector,
                path=f"{path}/connectors/{key}",
                allowed=PORTABLE_MISSION_CONNECTOR_CONFIG_KEYS,
                string_keys=("status", "mode", "label"),
                boolean_keys=("enabled",),
            )


def _validate_mission_room_extension(value: Any, experience: Mapping[str, Any]) -> None:
    path = f"/experience/extensions/{MISSION_ROOM_EXTENSION_ID}"
    if not isinstance(value, Mapping):
        raise WorkspaceBlueprintError(f"{path} must be a JSON object.")
    _assert_known_keys(value, {"enabled", "config", "dependencies"}, path)
    if not isinstance(value.get("enabled"), bool):
        raise WorkspaceBlueprintError(f"{path}/enabled must be a boolean.")
    config = value.get("config")
    if not isinstance(config, Mapping):
        raise WorkspaceBlueprintError(f"{path}/config must be a JSON object.")
    _assert_known_keys(config, set(PORTABLE_MISSION_ROOM_KEYS), f"{path}/config")
    profile = _string(config.get("profile"))
    if profile and not _PROFILE_KEY_RE.match(profile):
        raise WorkspaceBlueprintError(f"{path}/config/profile is invalid.")
    for key in (
        "profile",
        "country",
        "country_code",
        "news_source_policy",
        "label",
        "assistant_label",
        "default_view",
    ):
        if key in config and not _string(config[key]):
            raise WorkspaceBlueprintError(f"{path}/config/{key} must be a string.")
    if "region_scope" in config:
        _validate_string_array(config["region_scope"], f"{path}/config/region_scope")
    for key in ("root_route",):
        if key in config:
            _validate_route(config[key], f"{path}/config/{key}", prefix=MISSION_ROOM_ROUTE_ROOT)
    if "navigation" in config:
        _validate_navigation_items(config["navigation"], f"{path}/config/navigation")
    if "brand" in config:
        _validate_brand_payload(config["brand"], f"{path}/config/brand")
    if "dependencies" in value:
        _validate_mission_dependencies(value["dependencies"], f"{path}/dependencies")

    packs = _all_enabled_packs(experience)
    enabled_actions = _all_enabled_actions(experience)
    fallback_profile = _string(_as_dict(experience.get("profile")).get("demo_profile"))
    normalized_profile = (profile or fallback_profile or "").lower()
    config_text = json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    if normalized_profile.startswith("octocity"):
        crossed = sorted(pack for pack in packs if pack.startswith("sentinel_ci_aya_"))
        if crossed:
            raise WorkspaceBlueprintError(
                "Octocity Mission Room cannot enable Sentinel action packs: " + ", ".join(crossed)
            )
        crossed_actions = sorted(action for action in enabled_actions if action.startswith("aya."))
        if crossed_actions:
            raise WorkspaceBlueprintError(
                "Octocity Mission Room cannot enable Sentinel actions: "
                + ", ".join(crossed_actions)
            )
        if "sentinel" in config_text:
            raise WorkspaceBlueprintError(
                "Octocity Mission Room branding cannot contain Sentinel terms."
            )
    if normalized_profile.startswith("sentinel") or normalized_profile == "government_mission_room":
        crossed = sorted(pack for pack in packs if pack.startswith("octave_"))
        if crossed:
            raise WorkspaceBlueprintError(
                "Sentinel Mission Room cannot enable Octocity action packs: " + ", ".join(crossed)
            )
        crossed_actions = sorted(
            action for action in enabled_actions if action.startswith("octave.")
        )
        if crossed_actions:
            raise WorkspaceBlueprintError(
                "Sentinel Mission Room cannot enable Octocity actions: "
                + ", ".join(crossed_actions)
            )
        if "octocity" in config_text or "octave" in config_text:
            raise WorkspaceBlueprintError(
                "Sentinel Mission Room branding cannot contain Octocity terms."
            )


def _validate_v2_experience(blueprint: Mapping[str, Any]) -> None:
    workspace = blueprint.get("workspace")
    if not isinstance(workspace, Mapping):
        raise WorkspaceBlueprintError("workspace must be a JSON object in a v2 Blueprint.")
    _assert_known_keys(workspace, {"name", "slug", "mode"}, "/workspace")
    for key in ("name", "slug"):
        if key in workspace and not _string(workspace[key]):
            raise WorkspaceBlueprintError(f"workspace.{key} must be a non-empty string.")
    mode = workspace.get("mode")
    if mode is not None and mode not in PORTABLE_WORKSPACE_MODES:
        raise WorkspaceBlueprintError(f"Unsupported workspace mode: {mode!r}.")
    experience = blueprint.get("experience")
    if not isinstance(experience, Mapping):
        raise WorkspaceBlueprintError("experience must be a JSON object in a v2 Blueprint.")
    allowed_sections = {
        "contract_version",
        "profile",
        "features",
        "navigation",
        "shell",
        "assistant",
        "actions",
        "extensions",
        "app_access",
    }
    _assert_known_keys(experience, allowed_sections, "/experience")
    contract_version = experience.get("contract_version")
    if (
        not isinstance(contract_version, int)
        or isinstance(contract_version, bool)
        or contract_version != 1
    ):
        raise WorkspaceBlueprintError("Unsupported experience.contract_version.")
    _assert_no_secret_keys(experience)

    profile = experience.get("profile", {})
    if not isinstance(profile, Mapping):
        raise WorkspaceBlueprintError("experience.profile must be a JSON object.")
    _assert_known_keys(profile, set(PORTABLE_PROFILE_KEYS), "/experience/profile")
    if "hide_provider_details" in profile and not isinstance(
        profile["hide_provider_details"], bool
    ):
        raise WorkspaceBlueprintError("experience.profile.hide_provider_details must be a boolean.")
    if "family" in profile:
        raw_family = profile["family"]
        if not isinstance(raw_family, str) or raw_family not in {
            family.value for family in WorkspaceFamily
        }:
            raise WorkspaceBlueprintError(
                "experience.profile.family must be a canonical workspace family."
            )
    if "demo_profile" in profile and not _string(profile["demo_profile"]):
        raise WorkspaceBlueprintError("experience.profile.demo_profile must be a string.")

    features = experience.get("features", {})
    if not isinstance(features, Mapping):
        raise WorkspaceBlueprintError("experience.features must be a JSON object.")
    _assert_known_keys(features, set(PORTABLE_FEATURE_KEYS), "/experience/features")
    if any(not isinstance(value, bool) for value in features.values()):
        raise WorkspaceBlueprintError("Portable feature values must be booleans.")

    navigation = experience.get("navigation", {})
    if not isinstance(navigation, Mapping):
        raise WorkspaceBlueprintError("experience.navigation must be a JSON object.")
    _assert_known_keys(navigation, set(PORTABLE_NAVIGATION_KEYS), "/experience/navigation")
    if "key" in navigation and navigation["key"] not in {"standard", "business_end_user"}:
        raise WorkspaceBlueprintError("Unsupported experience.navigation.key.")
    if "default_route" in navigation:
        _validate_route(navigation["default_route"], "/experience/navigation/default_route")
    if "primary_surfaces" in navigation:
        raw_apps = navigation["primary_surfaces"]
        if not isinstance(raw_apps, list):
            raise WorkspaceBlueprintError(
                "experience.navigation.primary_surfaces must be an array."
            )
        try:
            normalized_apps = normalize_app_entitlements(raw_apps)
        except ValueError as exc:
            raise WorkspaceBlueprintError(str(exc)) from exc
        if raw_apps != normalized_apps:
            raise WorkspaceBlueprintError(
                "experience.navigation.primary_surfaces must contain unique known apps "
                "in canonical order."
            )
    if "advanced_access" in navigation and navigation["advanced_access"] not in {
        "admin_only",
        "link",
        "hidden",
    }:
        raise WorkspaceBlueprintError("Unsupported experience.navigation.advanced_access.")

    shell = experience.get("shell", {})
    if not isinstance(shell, Mapping):
        raise WorkspaceBlueprintError("experience.shell must be a JSON object.")
    _assert_known_keys(shell, set(PORTABLE_SHELL_KEYS), "/experience/shell")
    if "default_route" in shell:
        _validate_route(shell["default_route"], "/experience/shell/default_route")
    if "workspace_app_shell" in shell and shell["workspace_app_shell"] not in {
        "standard",
        "immersive",
    }:
        raise WorkspaceBlueprintError("Unsupported experience.shell.workspace_app_shell.")
    if "workspace_app_brand" in shell:
        _validate_brand_payload(
            shell["workspace_app_brand"],
            "/experience/shell/workspace_app_brand",
        )
    for key in ("workspace_app_label", "workspace_app_default_view"):
        if key in shell and not _string(shell[key]):
            raise WorkspaceBlueprintError(f"experience.shell.{key} must be a string.")

    assistant = experience.get("assistant", {})
    _validate_assistant_payload(assistant, "/experience/assistant")
    actions = experience.get("actions", {})
    _validate_actions_payload(actions, "/experience/actions")
    extensions = experience.get("extensions", {})
    if not isinstance(extensions, Mapping):
        raise WorkspaceBlueprintError("experience.extensions must be a JSON object.")
    _assert_known_keys(extensions, {MISSION_ROOM_EXTENSION_ID}, "/experience/extensions")
    if MISSION_ROOM_EXTENSION_ID in extensions:
        _validate_mission_room_extension(extensions[MISSION_ROOM_EXTENSION_ID], experience)

    app_access = experience.get("app_access", {})
    if not isinstance(app_access, Mapping):
        raise WorkspaceBlueprintError("experience.app_access must be a JSON object.")
    _assert_known_keys(
        app_access,
        {"enforcement_requested", "required_apps", "member_grants"},
        "/experience/app_access",
    )
    if not isinstance(app_access.get("enforcement_requested"), bool):
        raise WorkspaceBlueprintError(
            "experience.app_access.enforcement_requested must be a boolean."
        )
    try:
        apps = normalize_app_entitlements(app_access.get("required_apps"))
    except ValueError as exc:
        raise WorkspaceBlueprintError(str(exc)) from exc
    if not apps or apps != app_access.get("required_apps"):
        raise WorkspaceBlueprintError(
            "experience.app_access.required_apps must be non-empty and canonically ordered."
        )
    if app_access.get("member_grants") != "excluded":
        raise WorkspaceBlueprintError("Workspace member application grants must remain excluded.")


def _validate_apply_policies(*, experience_policy: str, entitlement_policy: str) -> None:
    if experience_policy not in EXPERIENCE_POLICIES:
        raise WorkspaceBlueprintError(f"Unsupported experience_policy: {experience_policy!r}.")
    if entitlement_policy not in ENTITLEMENT_POLICIES:
        raise WorkspaceBlueprintError(f"Unsupported entitlement_policy: {entitlement_policy!r}.")


def _payload_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _lock_workspace(db: DBSession, workspace: Workspace) -> Workspace:
    try:
        return lock_workspace_for_app_entitlement_mutation(db, workspace.id)
    except WorkspaceEntitlementMutationConflictError as exc:
        raise WorkspaceBlueprintConflictError("The target workspace no longer exists.") from exc


def _experience_settings_patch(experience: Mapping[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    features = _as_dict(experience.get("features"))
    if features:
        patch["features"] = deepcopy(features)
    profile = _as_dict(experience.get("profile"))
    for key in PORTABLE_PROFILE_KEYS:
        if key in profile:
            patch[key] = deepcopy(profile[key])
    navigation = _as_dict(experience.get("navigation"))
    if navigation:
        patch["navigation_profile"] = deepcopy(navigation)
    shell = _as_dict(experience.get("shell"))
    for key in PORTABLE_SHELL_KEYS:
        if key in shell:
            patch[key] = deepcopy(shell[key])
    assistant = _as_dict(experience.get("assistant"))
    assistant_mapping = {
        "default_profile": "assistant_profile_default",
        "profiles": "assistant_profiles",
        "knowledge_scopes": "knowledge_scopes",
        "voice_loop": "voice_loop",
        "voice_output": "voice_output",
    }
    for source_key, target_key in assistant_mapping.items():
        if source_key in assistant:
            patch[target_key] = deepcopy(assistant[source_key])
    actions = _as_dict(experience.get("actions"))
    if actions:
        patch["actions"] = deepcopy(actions)
    extensions = _as_dict(experience.get("extensions"))
    mission = extensions.get(MISSION_ROOM_EXTENSION_ID)
    if isinstance(mission, Mapping):
        mission_settings = deepcopy(_as_dict(mission.get("config")))
        mission_settings["enabled"] = mission.get("enabled") is True
        patch["mission_room"] = mission_settings
        dependencies = _as_dict(mission.get("dependencies"))
        dependency_mapping = {
            "calendar": "calendar",
            "action_planner": "action_planner",
            "document_intelligence": "document_intelligence",
            "visual_intelligence": "visual_intelligence",
            "feature_flags": "feature_flag",
            "connectors": "connectors",
        }
        for source_key, target_key in dependency_mapping.items():
            if source_key in dependencies:
                patch[target_key] = deepcopy(dependencies[source_key])
    return patch


def _flatten_mapping(
    value: Mapping[str, Any], prefix: tuple[str, ...]
) -> list[tuple[tuple[str, ...], Any]]:
    out: list[tuple[tuple[str, ...], Any]] = []
    for key in sorted(value):
        item = value[key]
        path = (*prefix, str(key))
        if isinstance(item, Mapping) and item:
            out.extend(_flatten_mapping(item, path))
        elif not isinstance(item, Mapping):
            out.append((path, deepcopy(item)))
    return out


def _lookup_path(root: Any, path: tuple[str, ...]) -> tuple[bool, Any, bool]:
    current = root
    for key in path:
        if not isinstance(current, Mapping):
            return False, None, True
        if key not in current:
            return False, None, False
        current = current[key]
    return True, deepcopy(current), False


def _pointer(path: tuple[str, ...]) -> str:
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in path)


def _pointer_parts(pointer: str) -> list[str]:
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]


def _entitlement_state(db: DBSession, workspace_id: str) -> dict[str, Any]:
    member_ids = [
        int(row[0])
        for row in db.query(WorkspaceMember.id)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.id.asc())
        .all()
    ]
    rows = (
        db.query(
            WorkspaceMemberAppEntitlement.workspace_member_id,
            WorkspaceMemberAppEntitlement.app_key,
        )
        .join(
            WorkspaceMember,
            WorkspaceMember.id == WorkspaceMemberAppEntitlement.workspace_member_id,
        )
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .order_by(
            WorkspaceMemberAppEntitlement.workspace_member_id.asc(),
            WorkspaceMemberAppEntitlement.app_key.asc(),
        )
        .all()
    )
    return {
        "member_ids": member_ids,
        "grants": [[int(member_id), str(app_key)] for member_id, app_key in rows],
    }


def _collect_keyed_strings(value: Any, key: str) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            if raw_key == key and (text := _string(item)):
                found.add(text)
            found.update(_collect_keyed_strings(item, key))
    elif isinstance(value, list):
        for item in value:
            found.update(_collect_keyed_strings(item, key))
    return found


def _blueprint_object_target_state(
    db: DBSession,
    *,
    workspace: Workspace,
    blueprint: Mapping[str, Any],
) -> dict[str, Any]:
    """Snapshot every stable key that can change an import plan."""

    capability_slugs = {
        slug for item in blueprint.get("capabilities") or [] if (slug := _string(item.get("slug")))
    }
    collision_prefixes = {f"{slug}-{workspace.slug}" for slug in capability_slugs}
    capability_rows = db.query(Capability.id, Capability.slug, Capability.workspace_id).all()
    capability_state = sorted(
        [
            [str(row.id), str(row.slug), row.workspace_id]
            for row in capability_rows
            if row.slug in capability_slugs
            or any(
                row.slug == prefix or row.slug.startswith(f"{prefix}-")
                for prefix in collision_prefixes
            )
        ],
        key=lambda item: (item[1], item[0]),
    )

    skill_slugs: set[str] = set()
    for item in blueprint.get("capabilities") or []:
        skill_slugs.update(_string_list(item.get("skill_slugs")))
    for item in blueprint.get("systems") or []:
        skill_slugs.update(_string_list(item.get("skill_slugs")))
        skill_slugs.update(_collect_keyed_strings(item.get("flow_definition"), "skill_slug"))
    skill_rows = (
        db.query(Skill.id, Skill.slug, Skill.workspace_id)
        .filter(Skill.slug.in_(sorted(skill_slugs)))
        .all()
        if skill_slugs
        else []
    )

    context_names = {
        name for item in blueprint.get("contexts") or [] if (name := _string(item.get("name")))
    }
    collection_slugs = {
        slug
        for item in _as_dict(blueprint.get("knowledge")).get("collections") or []
        if (slug := _string(item.get("slug")))
    }
    system_names = {
        name for item in blueprint.get("systems") or [] if (name := _string(item.get("name")))
    }
    preset_names = {
        name
        for kind in ("rag", "evaluation")
        for item in _as_dict(blueprint.get("presets")).get(kind) or []
        if (name := _string(item.get("name")))
    }

    contexts = (
        db.query(Context.id, Context.name, Context.version)
        .filter(
            Context.workspace_id == workspace.id,
            Context.name.in_(sorted(context_names)),
            Context.ephemeral.is_(False),
        )
        .order_by(Context.name.asc(), Context.id.asc())
        .all()
        if context_names
        else []
    )
    collections = (
        db.query(KnowledgeCollection.id, KnowledgeCollection.slug)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            KnowledgeCollection.slug.in_(sorted(collection_slugs)),
        )
        .order_by(KnowledgeCollection.slug.asc(), KnowledgeCollection.id.asc())
        .all()
        if collection_slugs
        else []
    )
    systems = (
        db.query(System.id, System.name, System.status)
        .filter(
            System.workspace_id == workspace.id,
            System.name.in_(sorted(system_names)),
        )
        .order_by(System.name.asc(), System.id.asc())
        .all()
        if system_names
        else []
    )

    preset_state: dict[str, list[list[Any]]] = {}
    for kind, model in (("rag", RagPreset), ("evaluation", EvaluationPreset)):
        rows = (
            db.query(model.id, model.name, model.scope, model.scope_id)
            .filter(
                model.workspace_id == workspace.id,
                model.name.in_(sorted(preset_names)),
            )
            .order_by(model.name.asc(), model.id.asc())
            .all()
            if preset_names
            else []
        )
        preset_state[kind] = [
            [str(row.id), str(row.name), str(row.scope), row.scope_id] for row in rows
        ]

    iam = load_iam_config(db, workspace.id, create=False)
    return {
        "capabilities": capability_state,
        "skills": sorted(
            [[str(row.id), str(row.slug), row.workspace_id] for row in skill_rows],
            key=lambda item: (item[1], item[0]),
        ),
        "contexts": [[str(row.id), str(row.name), int(row.version)] for row in contexts],
        "collections": [[str(row.id), str(row.slug)] for row in collections],
        "systems": [[str(row.id), str(row.name), str(row.status)] for row in systems],
        "presets": preset_state,
        "iam": {
            "role_flags": _without_secret_keys(iam.role_flags or {}) if iam else {},
            "capability_overrides": _without_secret_keys(iam.capability_overrides or {})
            if iam
            else {},
        },
    }


def _build_app_access_plan(
    *,
    db: DBSession,
    workspace: Workspace,
    experience: Mapping[str, Any],
    entitlement_policy: str,
) -> dict[str, Any]:
    source = _as_dict(experience.get("app_access"))
    requested = source.get("enforcement_requested") is True
    required_apps = normalize_app_entitlements(source.get("required_apps"))
    settings = _as_dict(workspace.settings)
    current_features = _as_dict(settings.get("features"))
    currently_enabled = current_features.get(APP_ENTITLEMENTS_FEATURE) is True
    state = _entitlement_state(db, workspace.id)
    current_grants = {(member_id, app_key) for member_id, app_key in state["grants"]}
    missing = [
        (member_id, app_key)
        for member_id in state["member_ids"]
        for app_key in required_apps
        if (member_id, app_key) not in current_grants
    ]
    grant_all = entitlement_policy == "grant_all_existing_members" and requested
    return {
        "policy": entitlement_policy,
        "enforcement_requested": requested,
        "required_apps": required_apps,
        "member_grants": "excluded",
        "member_count": len(state["member_ids"]),
        "grants_planned": len(missing) if grant_all else 0,
        "grants_created": 0,
        "feature_currently_enabled": currently_enabled,
        "feature_activated": bool(grant_all and not currently_enabled),
        "preserved": bool(entitlement_policy == "preserve_target"),
    }


def _build_experience_plan(
    *,
    db: DBSession,
    workspace: Workspace,
    blueprint: Mapping[str, Any],
    schema_version: int,
    experience_policy: str,
    entitlement_policy: str,
    blueprint_digest: str,
    activate_systems: bool,
) -> dict[str, Any]:
    applied: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    preserved: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    legacy_ignored: list[str] = []
    experience = _as_dict(blueprint.get("experience")) if schema_version == SCHEMA_VERSION else {}

    if schema_version == 1:
        legacy_workspace = _as_dict(blueprint.get("workspace"))
        if "mode" in legacy_workspace:
            legacy_ignored.append("/workspace/mode")
        if "settings" in legacy_workspace:
            legacy_ignored.append("/workspace/settings")
    else:
        workspace_payload = _as_dict(blueprint.get("workspace"))
        candidates: list[tuple[tuple[str, ...], Any, Any, bool]] = []
        if "mode" in workspace_payload:
            candidates.append(
                (("workspace", "mode"), workspace_payload["mode"], workspace.mode, False)
            )
        patch = _experience_settings_patch(experience)
        target_settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
        target_portable_patch = _experience_settings_patch(
            _serialize_workspace_experience(workspace)
        )
        source_leaves = dict(_flatten_mapping(patch, ("workspace", "settings")))
        candidate_leaves: list[tuple[tuple[str, ...], Any, bool]] = [
            (path, source_value, False) for path, source_value in source_leaves.items()
        ]
        if experience_policy == "replace_portable":
            for path, _target_value in _flatten_mapping(
                target_portable_patch, ("workspace", "settings")
            ):
                if path not in source_leaves:
                    candidate_leaves.append((path, None, True))

        for path, source_value, remove_source_missing in candidate_leaves:
            planned_source = _MISSING if remove_source_missing else source_value
            exists, target_value, incompatible_parent = _lookup_path(
                target_settings,
                path[2:],
            )
            nonportable_list_state = False
            if path in _PORTABLE_OBJECT_LIST_PATHS and not incompatible_parent:
                portable_exists, portable_value, _portable_parent_incompatible = _lookup_path(
                    target_portable_patch,
                    path[2:],
                )
                if exists and planned_source is not _MISSING and target_value == planned_source:
                    # Empty arrays are valid but intentionally absent from the
                    # exported projection. Equality proves no write is needed.
                    pass
                elif exists and (not portable_exists or target_value != portable_value):
                    nonportable_list_state = True
                    target_value = (
                        portable_value if portable_exists else ("__nonportable_list_state__",)
                    )
                elif portable_exists:
                    target_value = portable_value
                    exists = True
            if incompatible_parent:
                target_value = ("__incompatible_parent__",)
                exists = True
            candidates.append(
                (
                    path,
                    planned_source,
                    target_value if exists else _MISSING,
                    nonportable_list_state,
                )
            )

        for path, source_value, raw_target, nonportable_list_state in candidates:
            incompatible_parent = raw_target == ("__incompatible_parent__",)
            private_list_only = raw_target == ("__nonportable_list_state__",)
            target_missing = raw_target is _MISSING
            source_missing = source_value is _MISSING
            target_value = (
                None if target_missing or incompatible_parent or private_list_only else raw_target
            )
            item = {
                "path": _pointer(path),
                "source": None if source_missing else deepcopy(source_value),
                "target": deepcopy(target_value),
            }
            if source_missing:
                if target_missing:
                    item["action"] = "reuse"
                    reused.append(item)
                elif nonportable_list_state:
                    item["action"] = "conflict"
                    item["reason"] = "target_contains_nonportable_list_state"
                    conflicts.append(item)
                else:
                    item["action"] = "remove"
                    applied.append(item)
                continue
            if not target_missing and not incompatible_parent and target_value == source_value:
                item["action"] = "reuse"
                reused.append(item)
            elif experience_policy == "preserve_target":
                item["action"] = "preserve_target"
                item["reason"] = (
                    "target_parent_incompatible"
                    if incompatible_parent
                    else ("target_missing" if target_missing else "target_differs")
                )
                preserved.append(item)
            elif experience_policy == "merge_missing":
                if target_missing and not incompatible_parent:
                    item["action"] = "set_missing"
                    applied.append(item)
                else:
                    item["action"] = "conflict"
                    item["reason"] = (
                        "target_parent_incompatible" if incompatible_parent else "target_differs"
                    )
                    conflicts.append(item)
            else:
                if nonportable_list_state:
                    item["action"] = "conflict"
                    item["reason"] = "target_contains_nonportable_list_state"
                    conflicts.append(item)
                else:
                    item["action"] = "replace" if not target_missing else "set_missing"
                    if incompatible_parent:
                        item["reason"] = "replace_incompatible_parent"
                    applied.append(item)

    app_access = (
        _build_app_access_plan(
            db=db,
            workspace=workspace,
            experience=experience,
            entitlement_policy=entitlement_policy,
        )
        if schema_version == SCHEMA_VERSION
        else {
            "policy": entitlement_policy,
            "enforcement_requested": False,
            "required_apps": [],
            "member_grants": "excluded",
            "member_count": 0,
            "grants_planned": 0,
            "grants_created": 0,
            "feature_currently_enabled": False,
            "feature_activated": False,
            "preserved": True,
        }
    )
    target_state = {
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "workspace_name": workspace.name,
        "mode": workspace.mode,
        "experience": _serialize_workspace_experience(workspace),
        "entitlements": _entitlement_state(db, workspace.id),
        "objects": _blueprint_object_target_state(db, workspace=workspace, blueprint=blueprint),
    }
    token_payload = {
        "blueprint_digest": blueprint_digest,
        "target": target_state,
        "experience_policy": experience_policy,
        "entitlement_policy": entitlement_policy,
        "activate_systems": bool(activate_systems),
    }
    return {
        "policy": experience_policy,
        "applied": applied,
        "reused": reused,
        "preserved": preserved,
        "conflicts": conflicts,
        "legacy_ignored": legacy_ignored,
        "app_access": app_access,
        "plan_token": _payload_digest(token_payload),
    }


def _set_path(root: dict[str, Any], path: list[str], value: Any) -> None:
    current = root
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, Mapping):
            child = {}
        else:
            child = deepcopy(dict(child))
        current[key] = child
        current = child
    current[path[-1]] = deepcopy(value)


def _delete_path(root: dict[str, Any], path: list[str]) -> None:
    parents: list[tuple[dict[str, Any], str]] = []
    current: Any = root
    for key in path[:-1]:
        if not isinstance(current, dict) or not isinstance(current.get(key), Mapping):
            return
        parents.append((current, key))
        current = current[key]
    if not isinstance(current, dict):
        return
    current.pop(path[-1], None)
    for parent, key in reversed(parents):
        child = parent.get(key)
        if isinstance(child, Mapping) and not child:
            parent.pop(key, None)
        else:
            break


def _apply_workspace_experience_plan(*, workspace: Workspace, plan: Mapping[str, Any]) -> None:
    settings = deepcopy(_as_dict(workspace.settings))
    for item in plan.get("applied") or []:
        path = _pointer_parts(str(item["path"]))
        if path == ["workspace", "mode"]:
            workspace.mode = str(item["source"])
            continue
        if path[:2] != ["workspace", "settings"] or len(path) < 3:
            raise WorkspaceBlueprintError(f"Unsupported planned experience path: {item['path']}.")
        if item.get("action") == "remove":
            _delete_path(settings, path[2:])
        else:
            _set_path(settings, path[2:], item["source"])
    workspace.settings = settings


def _apply_app_access_plan(
    *,
    db: DBSession,
    workspace: Workspace,
    actor: User | None,
    plan: dict[str, Any],
) -> None:
    if plan.get("policy") != "grant_all_existing_members" or not plan.get("enforcement_requested"):
        return
    required_apps = normalize_app_entitlements(plan.get("required_apps"))
    memberships = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id)
        .order_by(WorkspaceMember.id.asc())
        .with_for_update()
        .all()
    )
    member_ids = [membership.id for membership in memberships]
    existing_rows = (
        db.query(WorkspaceMemberAppEntitlement)
        .filter(WorkspaceMemberAppEntitlement.workspace_member_id.in_(member_ids))
        .with_for_update()
        .all()
        if member_ids
        else []
    )
    existing = {(row.workspace_member_id, row.app_key) for row in existing_rows}
    created = 0
    for membership in memberships:
        for app_key in required_apps:
            if (membership.id, app_key) in existing:
                continue
            db.add(
                WorkspaceMemberAppEntitlement(
                    workspace_member_id=membership.id,
                    app_key=app_key,
                    granted_by_user_id=actor.id if actor else None,
                    grant_source="workspace_blueprint_v2",
                )
            )
            created += 1
    db.flush()

    if member_ids:
        covered = {
            (int(member_id), str(app_key))
            for member_id, app_key in db.query(
                WorkspaceMemberAppEntitlement.workspace_member_id,
                WorkspaceMemberAppEntitlement.app_key,
            )
            .filter(
                WorkspaceMemberAppEntitlement.workspace_member_id.in_(member_ids),
                WorkspaceMemberAppEntitlement.app_key.in_(required_apps),
            )
            .all()
        }
        missing = [
            (membership.id, app_key)
            for membership in memberships
            for app_key in required_apps
            if (membership.id, app_key) not in covered
        ]
        if missing:
            raise WorkspaceBlueprintConflictError(
                "Application entitlement backfill is incomplete; refusing to activate enforcement."
            )

    settings = deepcopy(_as_dict(workspace.settings))
    features = deepcopy(_as_dict(settings.get("features")))
    features[APP_ENTITLEMENTS_FEATURE] = True
    settings["features"] = features
    workspace.settings = settings
    plan["grants_created"] = created


def _serialize_capability(
    capability: Capability,
    *,
    workspace_id: str,
    skill_slugs_by_id: dict[str, str],
) -> dict[str, Any]:
    return {
        "slug": capability.slug,
        "name": capability.name,
        "description": capability.description or "",
        "tier": capability.tier,
        "industry": capability.industry,
        "input_unit": capability.input_unit,
        "output_unit": capability.output_unit,
        "skill_slugs": [
            skill_slugs_by_id[skill_id]
            for skill_id in (capability.skill_ids or [])
            if skill_id in skill_slugs_by_id
        ],
        "pricing": _without_secret_keys(capability.pricing or {}),
        "value_per_outcome": capability.value_per_outcome,
        "confidence_threshold": capability.confidence_threshold,
        "sla": _without_secret_keys(capability.sla or {}),
        "roi_model": _without_secret_keys(capability.roi_model or {}),
        "source_scope": "workspace"
        if capability.workspace_id == workspace_id
        else "global_reference",
    }


def _serialize_context(context: Context, *, systems_by_id: dict[str, System]) -> dict[str, Any]:
    system = systems_by_id.get(context.system_id or "")
    return {
        "name": context.name,
        "version": context.version,
        "system_name": system.name if system else None,
        "data_refs": _without_secret_keys(context.data_refs or []),
        "memory_refs": _without_secret_keys(context.memory_refs or []),
        "history_refs": _without_secret_keys(context.history_refs or []),
        "environment_state": _without_secret_keys(context.environment_state or {}),
        "business_constraints": _without_secret_keys(context.business_constraints or {}),
        "permissions": _without_secret_keys(context.permissions or {}),
    }


def _serialize_system(
    *,
    db: DBSession,
    system: System,
    actor: str,
    capabilities_by_id: dict[str, Capability],
    contexts_by_id: dict[str, Context],
) -> dict[str, Any]:
    envelope = export_service.serialize_for_export(db=db, system=system, exported_by=actor)
    payload = _as_dict(_without_secret_keys(envelope["system"]))
    capability = capabilities_by_id.get(system.capability_id or "")
    context = contexts_by_id.get(system.context_id or "")
    payload.update(
        {
            "capability_slug": capability.slug if capability else None,
            "context_name": context.name if context else None,
            "source_status": system.status,
            "import_status_default": "draft",
        }
    )
    return payload


def _serialize_collection(collection: KnowledgeCollection) -> dict[str, Any]:
    return {
        "slug": collection.slug,
        "name": collection.name,
        "description": collection.description or "",
        "embedding_model": collection.embedding_model,
        "chunking_method": collection.chunking_method,
        "chunking_params": _without_secret_keys(collection.chunking_params or {}),
        "source_status": collection.status,
        "source_document_count": collection.document_count or 0,
        "source_chunk_count": collection.chunk_count or 0,
    }


def _serialize_preset(
    preset: RagPreset | EvaluationPreset,
    *,
    systems_by_id: dict[str, System],
    capabilities_by_id: dict[str, Capability],
) -> dict[str, Any]:
    scope_ref = None
    if preset.scope == "system":
        system = systems_by_id.get(preset.scope_id or "")
        scope_ref = system.name if system else None
    elif preset.scope == "capability":
        capability = capabilities_by_id.get(preset.scope_id or "")
        scope_ref = capability.slug if capability else None
    return {
        "name": preset.name,
        "scope": preset.scope,
        "scope_ref": scope_ref,
        "config": _without_secret_keys(preset.config or {}),
        "is_default": bool(preset.is_default),
    }


def _apply_capabilities(
    *,
    db: DBSession,
    workspace: Workspace,
    capabilities: list[Mapping[str, Any]],
    dry_run: bool,
    report: dict[str, Any],
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for item in capabilities:
        slug = str(item.get("slug") or "").strip()
        if not slug:
            report["skipped"].append({"kind": "capability", "reason": "missing_slug"})
            continue
        existing = (
            db.query(Capability)
            .filter(Capability.slug == slug)
            .filter((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None)))
            .first()
        )
        if existing:
            out[slug] = existing.id
            report["reused"]["capabilities"] += 1
            report["actions"].append({"kind": "capability", "slug": slug, "action": "reuse"})
            continue
        target_slug = slug
        collision = db.query(Capability).filter(Capability.slug == slug).first()
        if collision:
            target_slug = _unique_capability_slug(db, f"{slug}-{workspace.slug}")
        report["created"]["capabilities"] += 1
        report["actions"].append(
            {
                "kind": "capability",
                "slug": target_slug,
                "source_slug": slug,
                "action": "create" if target_slug == slug else "create_renamed",
            }
        )
        skill_ids = _resolve_skill_slugs(
            db=db,
            workspace_id=workspace.id,
            slugs=list(item.get("skill_slugs") or []),
        )
        if dry_run:
            out[slug] = f"dry-run:{target_slug}"
            continue
        capability = Capability(
            id=str(uuid4()),
            workspace_id=workspace.id,
            slug=target_slug,
            name=item.get("name") or slug,
            description=item.get("description") or "",
            tier=item.get("tier") or "client",
            industry=item.get("industry"),
            input_unit=item.get("input_unit") or "request",
            output_unit=item.get("output_unit") or "answer",
            skill_ids=skill_ids,
            pricing=item.get("pricing") or {},
            value_per_outcome=item.get("value_per_outcome"),
            confidence_threshold=item.get("confidence_threshold"),
            sla=item.get("sla") or {},
            roi_model=item.get("roi_model") or {},
            is_seeded="N",
        )
        db.add(capability)
        db.flush()
        out[slug] = capability.id
    return out


def _unique_capability_slug(db: DBSession, base_slug: str) -> str:
    base = (base_slug or "capability").strip("-_")[:110] or "capability"
    candidate = base
    index = 2
    while db.query(Capability).filter(Capability.slug == candidate).first():
        suffix = f"-{index}"
        candidate = f"{base[: 120 - len(suffix)]}{suffix}"
        index += 1
    return candidate


def _resolve_skill_slugs(
    *,
    db: DBSession,
    workspace_id: str,
    slugs: list[str],
) -> list[str]:
    if not slugs:
        return []
    rows = (
        db.query(Skill)
        .filter(Skill.slug.in_(slugs))
        .filter((Skill.workspace_id == workspace_id) | (Skill.workspace_id.is_(None)))
        .all()
    )
    by_slug = {row.slug: row.id for row in rows}
    return [by_slug[slug] for slug in slugs if slug in by_slug]


def _apply_contexts(
    *,
    db: DBSession,
    workspace: Workspace,
    contexts: list[Mapping[str, Any]],
    dry_run: bool,
    report: dict[str, Any],
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for item in contexts:
        name = str(item.get("name") or "").strip()
        if not name:
            report["skipped"].append({"kind": "context", "reason": "missing_name"})
            continue
        existing = (
            db.query(Context)
            .filter(
                Context.workspace_id == workspace.id,
                Context.name == name,
                Context.ephemeral.is_(False),
            )
            .first()
        )
        if existing:
            out[name] = existing.id
            report["reused"]["contexts"] += 1
            report["actions"].append({"kind": "context", "name": name, "action": "reuse"})
            continue
        report["created"]["contexts"] += 1
        report["actions"].append({"kind": "context", "name": name, "action": "create"})
        if dry_run:
            out[name] = f"dry-run:{name}"
            continue
        context = Context(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            version=int(item.get("version") or 1),
            data_refs=item.get("data_refs") or [],
            memory_refs=item.get("memory_refs") or [],
            history_refs=item.get("history_refs") or [],
            environment_state=item.get("environment_state") or {},
            business_constraints=item.get("business_constraints") or {},
            permissions=item.get("permissions") or {},
            ephemeral=False,
        )
        db.add(context)
        db.flush()
        out[name] = context.id
    return out


def _apply_collections(
    *,
    db: DBSession,
    workspace: Workspace,
    collections: list[Mapping[str, Any]],
    actor: User | None,
    dry_run: bool,
    report: dict[str, Any],
) -> None:
    for item in collections:
        slug = str(item.get("slug") or "").strip()
        name = str(item.get("name") or slug or "").strip()
        if not slug or not name:
            report["skipped"].append({"kind": "collection", "reason": "missing_slug_or_name"})
            continue
        existing = (
            db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == slug
            )
            .first()
        )
        if existing:
            report["reused"]["collections"] += 1
            report["actions"].append({"kind": "collection", "slug": slug, "action": "reuse"})
            continue
        report["created"]["collections"] += 1
        report["actions"].append(
            {"kind": "collection", "slug": slug, "action": "create_metadata_only"}
        )
        if not dry_run:
            collection = knowledge_collections.create_collection(
                db,
                workspace=workspace,
                name=name,
                description=item.get("description") or "",
                created_by_user_id=actor.id if actor else None,
                slug=slug,
            )
            collection.embedding_model = item.get("embedding_model") or collection.embedding_model
            collection.chunking_method = item.get("chunking_method")
            collection.chunking_params = item.get("chunking_params") or {}


def _apply_systems(
    *,
    db: DBSession,
    workspace: Workspace,
    systems: list[Mapping[str, Any]],
    capability_map: dict[str, str | None],
    context_map: dict[str, str | None],
    actor_name: str,
    dry_run: bool,
    activate_systems: bool,
    report: dict[str, Any],
) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for item in systems:
        name = str(item.get("name") or "").strip()
        if not name:
            report["skipped"].append({"kind": "system", "reason": "missing_name"})
            continue
        existing = (
            db.query(System)
            .filter(System.workspace_id == workspace.id, System.name == name)
            .first()
        )
        if existing:
            out[name] = existing.id
            report["reused"]["systems"] += 1
            report["actions"].append({"kind": "system", "name": name, "action": "reuse"})
            continue

        envelope = {
            "kind": export_service.ENVELOPE_KIND,
            "schema_version": export_service.SCHEMA_VERSION,
            "system": dict(item),
        }
        try:
            create_kwargs, rebind_report = export_service.prepare_import(
                db=db,
                envelope=envelope,
                workspace_id=workspace.id,
                target_name=name,
            )
        except export_service.ChainExportError as exc:
            report["skipped"].append({"kind": "system", "name": name, "reason": str(exc)})
            continue

        execution_mode = _string(create_kwargs.get("execution_mode"))
        if execution_mode not in PORTABLE_EXECUTION_MODES:
            report["skipped"].append(
                {
                    "kind": "system",
                    "name": name,
                    "reason": "invalid_execution_mode",
                    "value": create_kwargs.get("execution_mode"),
                }
            )
            continue
        target_status = SystemStatus.draft.value
        if activate_systems:
            target_status = _string(item.get("source_status")) or SystemStatus.draft.value
            if target_status not in PORTABLE_SYSTEM_STATUSES:
                report["skipped"].append(
                    {
                        "kind": "system",
                        "name": name,
                        "reason": "invalid_source_status",
                        "value": item.get("source_status"),
                    }
                )
                continue

        flow = create_kwargs.get("flow_definition") or {}
        issues = dag_validator.validate_flow(flow)
        if dag_validator.has_errors(issues):
            report["skipped"].append(
                {
                    "kind": "system",
                    "name": name,
                    "reason": "flow_invalid",
                    "issues": dag_validator.issues_to_payload(issues),
                }
            )
            continue

        report["unresolved_skills"].extend(rebind_report.get("unresolved_skills", []))
        report["created"]["systems"] += 1
        report["actions"].append({"kind": "system", "name": name, "action": "create"})
        if dry_run:
            out[name] = f"dry-run:{name}"
            continue
        system = System(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=name,
            objective=create_kwargs["objective"],
            capability_id=capability_map.get(item.get("capability_slug") or "") or None,
            skill_ids=create_kwargs["skill_ids"],
            flow_definition=flow,
            execution_mode=execution_mode,
            execution_profile=create_kwargs["execution_profile"] or None,
            coordination_pattern=create_kwargs["coordination_pattern"],
            context_id=context_map.get(item.get("context_name") or "") or None,
            status=target_status,
            created_by=actor_name,
            default_prompt_type=create_kwargs["default_prompt_type"],
            default_model=create_kwargs["default_model"],
            retrieval_mode_default=create_kwargs["retrieval_mode_default"] or "auto",
        )
        db.add(system)
        db.flush()
        version_service.record_new_version(
            db=db,
            system=system,
            flow_definition=flow,
            created_by=actor_name,
            message="Imported from workspace blueprint",
        )
        out[name] = system.id
    report["unresolved_skills"] = sorted(set(report["unresolved_skills"]))
    return out


def _apply_presets(
    *,
    db: DBSession,
    workspace: Workspace,
    presets_by_kind: Mapping[str, Any],
    capability_map: dict[str, str | None],
    system_map: dict[str, str | None],
    dry_run: bool,
    report: dict[str, Any],
) -> None:
    for kind, model in (("rag", RagPreset), ("evaluation", EvaluationPreset)):
        for item in presets_by_kind.get(kind) or []:
            name = str(item.get("name") or "").strip()
            scope = str(item.get("scope") or "workspace")
            if not name or scope not in {"workspace", "capability", "system"}:
                report["skipped"].append(
                    {"kind": f"{kind}_preset", "name": name, "reason": "invalid_scope_or_name"}
                )
                continue
            scope_id = None
            if scope == "capability":
                scope_id = capability_map.get(str(item.get("scope_ref") or ""))
            elif scope == "system":
                scope_id = system_map.get(str(item.get("scope_ref") or ""))
            if scope != "workspace" and not scope_id:
                report["skipped"].append(
                    {"kind": f"{kind}_preset", "name": name, "reason": "unresolved_scope_ref"}
                )
                continue
            existing = (
                db.query(model)
                .filter(
                    model.workspace_id == workspace.id,
                    model.name == name,
                    model.scope == scope,
                    model.scope_id == scope_id,
                )
                .first()
            )
            if existing:
                report["reused"]["presets"] += 1
                report["actions"].append(
                    {"kind": f"{kind}_preset", "name": name, "action": "reuse"}
                )
                continue
            report["created"]["presets"] += 1
            report["actions"].append({"kind": f"{kind}_preset", "name": name, "action": "create"})
            if not dry_run:
                db.add(
                    model(
                        id=str(uuid4()),
                        workspace_id=workspace.id,
                        name=name,
                        scope=scope,
                        scope_id=scope_id,
                        config=item.get("config") or {},
                        is_default=bool(item.get("is_default")),
                    )
                )
                db.flush()


def _apply_iam_config(
    *,
    db: DBSession,
    workspace: Workspace,
    iam: Mapping[str, Any],
    actor: User | None,
    dry_run: bool,
    report: dict[str, Any],
) -> None:
    role_flags = iam.get("role_flags")
    capability_overrides = iam.get("capability_overrides")
    if not role_flags and not capability_overrides:
        return
    report["actions"].append(
        {"kind": "iam_config", "action": "patch" if not dry_run else "dry_run_patch"}
    )
    if not dry_run:
        patch_iam_config(
            db,
            workspace_id=workspace.id,
            role_flags=role_flags if isinstance(role_flags, dict) else None,
            capability_overrides=capability_overrides
            if isinstance(capability_overrides, dict)
            else None,
            updated_by_user_id=actor.id if actor else None,
        )
