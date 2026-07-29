"""Runtime authority for installed Workspace Apps.

The lifecycle tables become authoritative only when the workspace-scoped
``features.workspace_app_platform_v1`` flag is the literal boolean ``True``.
With the flag disabled callers keep the historical settings-based behaviour.
With it enabled every installation is resolved against the exact built-in
manifest digest and invalid state fails closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import object_session

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.workspace import Workspace
from app.models.workspace_app import WorkspaceAppInstallation
from app.schemas.canonical import WorkspaceFamily
from app.services.workspace_app_boundaries import (
    WorkspaceAppBoundaryContractError,
    manifest_api_prefixes,
    slash_boundary_paths_overlap,
    workspace_app_relational_integrity_errors,
)
from app.services.workspace_app_manifests import (
    GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS,
    GENERIC_MISSION_ROOM_PROVIDER_KIND,
    CompiledWorkspaceAppManifest,
    WorkspaceAppManifestError,
    WorkspaceAppManifestNotFound,
    get_builtin_workspace_app_manifest,
    validate_manifest_configuration,
)

WORKSPACE_APP_PLATFORM_FEATURE = "workspace_app_platform_v1"
WORKSPACE_APP_ROLLOUT_STATE_KEY = "_workspace_app_platform_rollout_v1"
WORKSPACE_APP_CANARY_MARKER = "workspace_app_platform_canary"
WORKSPACE_APP_CANARY_MARKER_VALUE = "v1"
MISSION_ROOM_APP_IDS = frozenset(
    {
        "mission-room.extension",
        "sentinel.mission-room",
        "octocity.mission-room",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_TRUSTED_RUNNER_FIELDS = frozenset(
    {
        "issuer",
        "project_id",
        "pipeline_id",
        "job_id",
        "commit_sha",
        "ref",
        "ref_protected",
    }
)
WORKSPACE_APP_PROBATION_MAX_AGE = timedelta(minutes=30)
WORKSPACE_APP_PREFLIGHT_CHECK_COUNT = 3
WORKSPACE_APP_POSTACTIVATION_CHECK_COUNT = 4
# Sentinel and Octocity keep their existing, app-owned providers.  The generic
# extension is authorized independently by the exact provider contract in its
# immutable manifest rather than by app identity alone.
SENTINEL_MISSION_ROOM_APP_ID = "sentinel.mission-room"
OCTOCITY_MISSION_ROOM_APP_ID = "octocity.mission-room"
MISSION_ROOM_PROVIDER_APP_IDS = frozenset(
    {SENTINEL_MISSION_ROOM_APP_ID, OCTOCITY_MISSION_ROOM_APP_ID}
)


class WorkspaceAppRuntimeError(RuntimeError):
    """An enabled platform cannot derive a trusted runtime projection."""

    def __init__(self, message: str, *, code: str = "runtime_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedWorkspaceApp:
    installation: WorkspaceAppInstallation
    manifest: CompiledWorkspaceAppManifest
    payload: dict[str, Any]
    configuration: dict[str, Any]


@dataclass(frozen=True)
class WorkspaceAppRuntime:
    mode: str
    enabled: bool
    rollout_phase: str
    rollout_ref: str | None
    installations: tuple[ResolvedWorkspaceApp, ...]
    shell: str
    routes: tuple[str, ...]
    primary_surface_ids: tuple[str, ...]
    default_routes: dict[str, str]
    branding_namespaces: tuple[str, ...]
    api_prefixes: tuple[str, ...]
    action_packs: tuple[str, ...]
    mission_room: dict[str, Any] | None

    @property
    def app_ids(self) -> tuple[str, ...]:
        return tuple(item.manifest.app_id for item in self.installations)

    def as_public_payload(self) -> dict[str, Any]:
        """Return the secret-free bootstrap contract consumed by the shell."""

        return {
            "schema_version": 1,
            "mode": self.mode,
            "enabled": self.enabled,
            "rollout_phase": self.rollout_phase,
            "rollout_ref": self.rollout_ref,
            "valid": True,
            "installations": [
                {
                    "app_id": item.manifest.app_id,
                    "version": item.manifest.version,
                    "manifest_digest": item.manifest.digest,
                    "category": item.payload["category"],
                    "routes": list(item.payload["routes"]),
                    "primary_surface_id": item.payload["experience"]["primary_surface_id"],
                    "default_route": item.payload["experience"]["default_route"],
                    "branding_namespace": item.payload["branding"]["namespace"],
                    "api_prefixes": list(_application_api_prefixes(item.payload)),
                    "action_packs": list(item.payload["action_packs"]),
                    "entitlement_keys": list(item.payload["entitlement_keys"]),
                }
                for item in self.installations
            ],
            "experience": {
                "shell": self.shell,
                "routes": list(self.routes),
                "primary_surface_ids": list(self.primary_surface_ids),
                "default_routes": deepcopy(self.default_routes),
                "branding_namespaces": list(self.branding_namespaces),
                "api_prefixes": list(self.api_prefixes),
                "action_packs": list(self.action_packs),
                "mission_room": deepcopy(self.mission_room),
            },
        }


def workspace_app_platform_enabled(workspace: Workspace | None) -> bool:
    settings = workspace.settings if workspace is not None else None
    features = settings.get("features") if isinstance(settings, Mapping) else None
    return isinstance(features, Mapping) and features.get(WORKSPACE_APP_PLATFORM_FEATURE) is True


def _session(workspace: Workspace, db: DBSession | None) -> DBSession:
    session = db or object_session(workspace)
    if session is None:
        raise WorkspaceAppRuntimeError(
            "workspace app runtime requires an attached database session",
            code="runtime_session_unavailable",
        )
    return session


def _trusted_installations(
    db: DBSession,
    workspace: Workspace,
) -> tuple[ResolvedWorkspaceApp, ...]:
    integrity_errors = workspace_app_relational_integrity_errors(db)
    if integrity_errors:
        raise WorkspaceAppRuntimeError(
            "Workspace App relational integrity migration is not applied",
            code="runtime_schema_unsatisfied",
        )
    rows = (
        db.query(WorkspaceAppInstallation)
        .filter(
            WorkspaceAppInstallation.workspace_id == workspace.id,
            WorkspaceAppInstallation.state == "installed",
        )
        .order_by(WorkspaceAppInstallation.app_id.asc())
        .all()
    )
    resolved: list[ResolvedWorkspaceApp] = []
    for row in rows:
        if not row.version or not row.manifest_digest:
            raise WorkspaceAppRuntimeError(
                "installed workspace app state is incomplete",
                code="installation_incomplete",
            )
        try:
            manifest = get_builtin_workspace_app_manifest(
                row.app_id,
                row.version,
                expected_digest=row.manifest_digest,
            )
            configuration = validate_manifest_configuration(
                manifest,
                row.configuration if isinstance(row.configuration, Mapping) else None,
            )
        except (WorkspaceAppManifestError, WorkspaceAppManifestNotFound) as exc:
            raise WorkspaceAppRuntimeError(
                "installed workspace app is not backed by a trusted manifest",
                code="manifest_untrusted",
            ) from exc
        resolved.append(
            ResolvedWorkspaceApp(
                installation=row,
                manifest=manifest,
                payload=manifest.as_dict(),
                configuration=configuration,
            )
        )
    _validate_workspace_compatibility(workspace, resolved)
    _validate_coinstallation_contracts(resolved)
    return tuple(resolved)


def _validate_workspace_compatibility(
    workspace: Workspace,
    applications: Sequence[ResolvedWorkspaceApp],
) -> None:
    settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    try:
        family = WorkspaceFamily(str(settings.get("family") or "").strip().lower()).value
    except ValueError as exc:
        raise WorkspaceAppRuntimeError(
            "workspace has no canonical family",
            code="workspace_family_invalid",
        ) from exc
    mission_room = settings.get("mission_room")
    mission_room = mission_room if isinstance(mission_room, Mapping) else {}
    raw_profile = mission_room.get("profile")
    profile = str(raw_profile).strip() if isinstance(raw_profile, str) else None
    profile = profile or None
    for application in applications:
        compatibility = application.payload.get("compatibility")
        if not isinstance(compatibility, Mapping):
            raise WorkspaceAppRuntimeError(
                "trusted manifest compatibility is invalid",
                code="manifest_untrusted",
            )
        allowed_families = compatibility.get("workspace_families")
        allowed_profiles = compatibility.get("workspace_profiles")
        forbidden_profiles = compatibility.get("forbidden_workspace_profiles")
        if (
            not isinstance(allowed_families, list)
            or not isinstance(allowed_profiles, list)
            or not isinstance(forbidden_profiles, list)
        ):
            raise WorkspaceAppRuntimeError(
                "trusted manifest compatibility is invalid",
                code="manifest_untrusted",
            )
        if family not in allowed_families:
            raise WorkspaceAppRuntimeError(
                "installed app is incompatible with the workspace family",
                code="workspace_family_incompatible",
            )
        if allowed_profiles and profile not in allowed_profiles:
            raise WorkspaceAppRuntimeError(
                "installed app is incompatible with the workspace profile",
                code="workspace_profile_incompatible",
            )
        if profile in forbidden_profiles:
            raise WorkspaceAppRuntimeError(
                "installed app claims a reserved workspace profile",
                code="workspace_profile_reserved",
            )


def _validate_coinstallation_contracts(
    applications: Sequence[ResolvedWorkspaceApp],
) -> None:
    api_boundaries: list[tuple[str, ...]] = []
    for application in applications:
        try:
            api_boundaries.append(manifest_api_prefixes(application.payload))
        except WorkspaceAppBoundaryContractError as exc:
            raise WorkspaceAppRuntimeError(
                "installed app API authority contract is invalid",
                code="manifest_untrusted",
            ) from exc

    for index, left in enumerate(applications):
        left_group = left.payload.get("conflict_group")
        left_routes = left.payload.get("routes")
        left_exclusive = left.payload.get("exclusive_routes") is True
        left_api_prefixes = api_boundaries[index]
        for right_index, right in enumerate(applications[index + 1 :], start=index + 1):
            if left_group is not None and left_group == right.payload.get("conflict_group"):
                raise WorkspaceAppRuntimeError(
                    "installed apps share an exclusive conflict group",
                    code="conflict_group",
                )
            right_routes = right.payload.get("routes")
            right_exclusive = right.payload.get("exclusive_routes") is True
            if (
                (left_exclusive or right_exclusive)
                and isinstance(left_routes, list)
                and isinstance(right_routes, list)
                and any(
                    slash_boundary_paths_overlap(left_route, right_route)
                    for left_route in left_routes
                    for right_route in right_routes
                )
            ):
                raise WorkspaceAppRuntimeError(
                    "installed apps claim overlapping exclusive routes",
                    code="route_conflict",
                )
            if any(
                slash_boundary_paths_overlap(left_prefix, right_prefix)
                for left_prefix in left_api_prefixes
                for right_prefix in api_boundaries[right_index]
            ):
                raise WorkspaceAppRuntimeError(
                    "installed apps claim overlapping API authority prefixes",
                    code="api_prefix_conflict",
                )


def _resolve_source(
    source: Any,
    *,
    configuration: Mapping[str, Any],
    field: str,
) -> Any:
    if not isinstance(source, str) or not source.startswith("configuration."):
        raise WorkspaceAppRuntimeError(
            f"invalid declarative source for {field}",
            code="experience_contract_invalid",
        )
    key = source.removeprefix("configuration.")
    if not key or key not in configuration:
        raise WorkspaceAppRuntimeError(
            f"missing declarative source for {field}",
            code="experience_contract_invalid",
        )
    return deepcopy(configuration[key])


def _mission_room_projection(
    applications: Sequence[ResolvedWorkspaceApp],
) -> dict[str, Any] | None:
    candidates: list[tuple[ResolvedWorkspaceApp, Mapping[str, Any]]] = []
    for application in applications:
        experience = application.payload.get("experience")
        mission_room = experience.get("mission_room") if isinstance(experience, Mapping) else None
        if isinstance(mission_room, Mapping):
            candidates.append((application, mission_room))
    if not candidates:
        return None
    if len(candidates) != 1:
        raise WorkspaceAppRuntimeError(
            "multiple primary Mission Room applications are installed",
            code="mission_room_conflict",
        )
    application, contract = candidates[0]
    projected = deepcopy(dict(contract))
    for field in ("profile", "assistant_profile"):
        source_key = f"{field}_source"
        if source_key in projected:
            projected[field] = _resolve_source(
                projected.pop(source_key),
                configuration=application.configuration,
                field=field,
            )
        value = projected.get(field)
        if not isinstance(value, str) or not value.strip():
            raise WorkspaceAppRuntimeError(
                f"Mission Room {field} is invalid",
                code="experience_contract_invalid",
            )
    navigation = projected.get("navigation_keys")
    if (
        not isinstance(navigation, list)
        or not navigation
        or any(not isinstance(key, str) or not key.strip() for key in navigation)
    ):
        raise WorkspaceAppRuntimeError(
            "Mission Room navigation contract is invalid",
            code="experience_contract_invalid",
        )
    experience = application.payload["experience"]
    projected.update(
        {
            "app_id": application.manifest.app_id,
            "version": application.manifest.version,
            "manifest_digest": application.manifest.digest,
            "default_route": experience["default_route"],
            "primary_surface_id": experience["primary_surface_id"],
        }
    )
    return projected


def _ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _application_api_prefixes(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the compiled manifest's complete API authority boundary."""

    try:
        return manifest_api_prefixes(payload)
    except WorkspaceAppBoundaryContractError as exc:
        raise WorkspaceAppRuntimeError(
            "installed app API authority contract is invalid",
            code="experience_contract_invalid",
        ) from exc


def _build_authoritative_runtime(
    applications: tuple[ResolvedWorkspaceApp, ...],
) -> WorkspaceAppRuntime:
    shells = {
        str(application.payload["experience"].get("shell") or "")
        for application in applications
        if str(application.payload["experience"].get("shell") or "") != "standard"
    }
    if len(shells) > 1:
        raise WorkspaceAppRuntimeError(
            "installed Workspace Apps declare incompatible shells",
            code="shell_conflict",
        )
    shell = next(iter(shells), "standard")
    routes = _ordered_unique(
        [route for application in applications for route in application.payload["routes"]]
    )
    primary_surfaces = _ordered_unique(
        [
            str(application.payload["experience"]["primary_surface_id"])
            for application in applications
        ]
    )
    default_routes = {
        application.manifest.app_id: str(application.payload["experience"]["default_route"])
        for application in applications
    }
    branding = _ordered_unique(
        [str(application.payload["branding"]["namespace"]) for application in applications]
    )
    api_prefixes = _ordered_unique(
        [
            prefix
            for application in applications
            for prefix in _application_api_prefixes(application.payload)
        ]
    )
    action_packs = _ordered_unique(
        [pack for application in applications for pack in application.payload["action_packs"]]
    )
    return WorkspaceAppRuntime(
        mode="authoritative",
        enabled=True,
        rollout_phase="inspection",
        rollout_ref=None,
        installations=applications,
        shell=shell,
        routes=routes,
        primary_surface_ids=primary_surfaces,
        default_routes=default_routes,
        branding_namespaces=branding,
        api_prefixes=api_prefixes,
        action_packs=action_packs,
        mission_room=_mission_room_projection(applications),
    )


def inspect_authoritative_workspace_app_runtime(
    workspace: Workspace,
    *,
    db: DBSession | None = None,
) -> WorkspaceAppRuntime:
    """Validate installed state before the rollout flag is enabled."""

    applications = _trusted_installations(_session(workspace, db), workspace)
    return _build_authoritative_runtime(applications)


def workspace_app_installation_subject(
    runtime: WorkspaceAppRuntime,
) -> list[dict[str, str]]:
    """Return the canonical, content-addressed installation identity.

    Configuration is part of runtime behaviour (for example Mission Room's
    profile and assistant).  Its canonical digest is therefore bound without
    exposing the configuration itself in evidence or bootstrap payloads.
    """

    return [
        {
            "app_id": item.manifest.app_id,
            "version": item.manifest.version,
            "manifest_digest": item.manifest.digest,
            "configuration_sha256": hashlib.sha256(
                json.dumps(
                    item.configuration,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
        }
        for item in runtime.installations
    ]


def workspace_app_installations_sha256(runtime: WorkspaceAppRuntime) -> str:
    """Hash the exact canonical installation set used by rollout evidence."""

    payload = json.dumps(
        workspace_app_installation_subject(runtime),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rollout_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise WorkspaceAppRuntimeError(
            f"Workspace App rollout {field} is missing",
            code="rollout_attestation_invalid",
        )
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkspaceAppRuntimeError(
            f"Workspace App rollout {field} is invalid",
            code="rollout_attestation_invalid",
        ) from exc
    if parsed.tzinfo is None:
        raise WorkspaceAppRuntimeError(
            f"Workspace App rollout {field} must include a timezone",
            code="rollout_attestation_invalid",
        )
    return parsed.astimezone(UTC)


def _rollout_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise WorkspaceAppRuntimeError(
            f"Workspace App rollout {field} is invalid",
            code="rollout_runner_untrusted",
        )
    return value


def _validated_persisted_trusted_runner(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("trusted_runner")
    if not isinstance(raw, Mapping) or set(raw) != _TRUSTED_RUNNER_FIELDS:
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout runner metadata is incomplete",
            code="rollout_runner_untrusted",
        )
    revision = _rollout_text(row.get("revision"), field="revision").lower()
    if _REVISION_RE.fullmatch(revision) is None:
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout runner revision is invalid",
            code="rollout_runner_untrusted",
        )
    issuer = _rollout_text(raw.get("issuer"), field="trusted_runner.issuer").rstrip("/")
    project_id = _rollout_text(
        raw.get("project_id"),
        field="trusted_runner.project_id",
    )
    pipeline_id = _rollout_text(
        raw.get("pipeline_id"),
        field="trusted_runner.pipeline_id",
    )
    job_id = _rollout_text(raw.get("job_id"), field="trusted_runner.job_id")
    commit_sha = _rollout_text(
        raw.get("commit_sha"),
        field="trusted_runner.commit_sha",
    ).lower()
    ref = _rollout_text(raw.get("ref"), field="trusted_runner.ref")
    trusted_issuer = str(settings.authorization_v2_trusted_oidc_issuer or "").rstrip("/")
    trusted_project_id = str(settings.authorization_v2_trusted_project_id or "").strip()
    trusted_ref = str(settings.authorization_v2_trusted_ref or "").strip()
    if (
        not issuer.startswith("https://")
        or not trusted_issuer.startswith("https://")
        or issuer != trusted_issuer
        or not trusted_project_id
        or project_id != trusted_project_id
        or not trusted_ref
        or ref != trusted_ref
        or raw.get("ref_protected") is not True
        or commit_sha != revision
    ):
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout runner no longer matches current trust anchors",
            code="rollout_runner_untrusted",
        )
    return {
        "issuer": issuer,
        "project_id": project_id,
        "pipeline_id": pipeline_id,
        "job_id": job_id,
        "commit_sha": revision,
        "ref": ref,
        "ref_protected": True,
    }


def _workspace_app_probation_audit_details(
    probation: Mapping[str, Any],
    *,
    trusted_runner: Mapping[str, Any],
) -> dict[str, Any]:
    runner = deepcopy(dict(trusted_runner))
    return {
        "revision": probation.get("revision"),
        "probation_ref": probation.get("probation_ref"),
        "staged_at": probation.get("staged_at"),
        "expires_at": probation.get("expires_at"),
        "preflight_evidence_ref": probation.get("preflight_evidence_ref"),
        "preflight_artifact_ref": probation.get("preflight_artifact_ref"),
        "preflight_source_junit_ref": probation.get("preflight_source_junit_ref"),
        "preflight_artifact_tests": probation.get("preflight_artifact_tests"),
        "trusted_runner": runner,
        "pipeline_id": runner.get("pipeline_id"),
        "job_id": runner.get("job_id"),
        "installations_sha256": probation.get("installations_sha256"),
        "installation_count": probation.get("installation_count"),
    }


def _workspace_app_activation_audit_details(
    activation: Mapping[str, Any],
    *,
    trusted_runner: Mapping[str, Any],
) -> dict[str, Any]:
    runner = deepcopy(dict(trusted_runner))
    return {
        "revision": activation.get("revision"),
        "probation_ref": activation.get("probation_ref"),
        "activated_at": activation.get("activated_at"),
        "preflight_evidence_ref": activation.get("preflight_evidence_ref"),
        "preflight_artifact_ref": activation.get("preflight_artifact_ref"),
        "preflight_source_junit_ref": activation.get("preflight_source_junit_ref"),
        "evidence_ref": activation.get("evidence_ref"),
        "artifact_ref": activation.get("artifact_ref"),
        "source_junit_ref": activation.get("source_junit_ref"),
        "preflight_artifact_tests": activation.get("preflight_artifact_tests"),
        "postactivation_artifact_tests": activation.get("postactivation_artifact_tests"),
        "artifact_tests": activation.get("artifact_tests"),
        "trusted_runner": runner,
        "pipeline_id": runner.get("pipeline_id"),
        "job_id": runner.get("job_id"),
        "installations_sha256": activation.get("installations_sha256"),
        "installation_count": activation.get("installation_count"),
    }


def _require_workspace_app_rollout_audit(
    workspace: Workspace,
    row: Mapping[str, Any],
    *,
    db: DBSession | None,
    event_type: str,
    actor_field: str,
    details: Mapping[str, Any],
) -> None:
    audit_id = str(row.get("audit_id") or "").strip().lower()
    try:
        canonical_audit_id = str(UUID(audit_id))
    except (ValueError, AttributeError):
        canonical_audit_id = ""
    session = db or object_session(workspace)
    if canonical_audit_id != audit_id or session is None:
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout has no exact server audit",
            code="rollout_audit_invalid",
        )
    audit = session.query(AuditLog).filter(AuditLog.id == audit_id).one_or_none()
    expected_actor = str(row.get(actor_field) or "").strip()
    if (
        audit is None
        or audit.workspace_id != workspace.id
        or audit.event_type != event_type
        or audit.actor != expected_actor
        or audit.severity != "info"
        or audit.details != dict(details)
    ):
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout server audit differs from persisted authority",
            code="rollout_audit_invalid",
        )


def _attested_digest(row: Mapping[str, Any], field: str) -> str:
    digest = str(row.get(field) or "").strip().lower()
    if _SHA256_RE.fullmatch(digest) is None:
        raise WorkspaceAppRuntimeError(
            f"Workspace App rollout {field} is invalid",
            code="rollout_attestation_invalid",
        )
    reference = str(row.get(field.removesuffix("_sha256") + "_ref") or "").strip()
    if reference != f"sha256:{digest}":
        raise WorkspaceAppRuntimeError(
            f"Workspace App rollout {field} reference is invalid",
            code="rollout_attestation_invalid",
        )
    return digest


def _rollout_state(workspace: Workspace, *, required: bool) -> Mapping[str, Any] | None:
    workspace_settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    raw_state = workspace_settings.get(WORKSPACE_APP_ROLLOUT_STATE_KEY)
    if raw_state is None and not required:
        return None
    if not isinstance(raw_state, Mapping):
        raise WorkspaceAppRuntimeError(
            "Workspace App runtime has no rollout attestation",
            code="rollout_attestation_missing",
        )
    if raw_state.get("schema_version") != 1:
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout schema is unsupported",
            code="rollout_attestation_invalid",
        )
    return raw_state


def _validated_rollout_history(
    workspace: Workspace,
    raw_state: Mapping[str, Any],
    *,
    active: bool,
    db: DBSession | None = None,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    activations = raw_state.get("activations")
    deactivations = raw_state.get("deactivations")
    expected_delta = 1 if active else 0
    if (
        not isinstance(activations, list)
        or not isinstance(deactivations, list)
        or any(not isinstance(row, Mapping) for row in activations)
        or any(not isinstance(row, Mapping) for row in deactivations)
        or len(activations) != len(deactivations) + expected_delta
    ):
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout history has an invalid phase",
            code="rollout_attestation_invalid",
        )

    activation_times: list[datetime] = []
    for index, activation in enumerate(activations):
        if activation.get("workspace_id") != workspace.id:
            raise WorkspaceAppRuntimeError(
                "Workspace App activation belongs to a different workspace",
                code="rollout_workspace_mismatch",
            )
        activation_times.append(
            _rollout_timestamp(activation.get("activated_at"), field="activated_at")
        )
        evidence_digest = _attested_digest(activation, "evidence_sha256")
        _attested_digest(activation, "artifact_sha256")
        trusted_runner = _validated_persisted_trusted_runner(activation)
        _require_workspace_app_rollout_audit(
            workspace,
            activation,
            db=db,
            event_type="lot9.workspace_app_platform.activated",
            actor_field="actor",
            details=_workspace_app_activation_audit_details(
                activation,
                trusted_runner=trusted_runner,
            ),
        )
        if index < len(deactivations):
            deactivation = deactivations[index]
            if deactivation.get("workspace_id") != workspace.id:
                raise WorkspaceAppRuntimeError(
                    "Workspace App deactivation belongs to a different workspace",
                    code="rollout_workspace_mismatch",
                )
            deactivated_at = _rollout_timestamp(
                deactivation.get("deactivated_at"),
                field="deactivated_at",
            )
            if deactivated_at < activation_times[index]:
                raise WorkspaceAppRuntimeError(
                    "Workspace App rollout history is out of order",
                    code="rollout_attestation_invalid",
                )
            if deactivation.get("previous_activation_ref") != f"sha256:{evidence_digest}":
                raise WorkspaceAppRuntimeError(
                    "Workspace App deactivation does not reference its activation",
                    code="rollout_attestation_invalid",
                )
            if index + 1 < len(activations):
                next_activated_at = _rollout_timestamp(
                    activations[index + 1].get("activated_at"),
                    field="activated_at",
                )
                if next_activated_at < deactivated_at:
                    raise WorkspaceAppRuntimeError(
                        "Workspace App rollout history is out of order",
                        code="rollout_attestation_invalid",
                    )
    return activations, deactivations


def validate_workspace_app_inactive_rollout_history(
    workspace: Workspace,
    *,
    db: DBSession | None = None,
) -> None:
    """Validate the disabled phase before a new probation is staged."""

    raw_state = _rollout_state(workspace, required=False)
    if raw_state is None:
        return
    if raw_state.get("probation") is not None:
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout already contains a probation",
            code="rollout_probation_conflict",
        )
    _validated_rollout_history(workspace, raw_state, active=False, db=db)


def _validate_runtime_binding(
    workspace: Workspace,
    runtime: WorkspaceAppRuntime,
    row: Mapping[str, Any],
) -> None:
    if row.get("workspace_id") != workspace.id:
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout belongs to a different workspace",
            code="rollout_workspace_mismatch",
        )
    revision = str(settings.agentium_image_revision or "").strip().lower()
    if _REVISION_RE.fullmatch(revision) is None or row.get("revision") != revision:
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout targets a different runtime revision",
            code="runtime_revision_mismatch",
        )
    subject = workspace_app_installation_subject(runtime)
    if not subject:
        raise WorkspaceAppRuntimeError(
            "Workspace App rollout has no installed application",
            code="rollout_attestation_stale",
        )
    expected_digest = workspace_app_installations_sha256(runtime)
    installation_digest = str(row.get("installations_sha256") or "").strip().lower()
    installation_count = row.get("installation_count")
    if (
        _SHA256_RE.fullmatch(installation_digest) is None
        or installation_digest != expected_digest
        or isinstance(installation_count, bool)
        or not isinstance(installation_count, int)
        or installation_count != len(subject)
    ):
        raise WorkspaceAppRuntimeError(
            "Workspace App installation set differs from its rollout proof",
            code="rollout_attestation_stale",
        )


def _probation_digest(probation: Mapping[str, Any]) -> str:
    payload = {
        key: deepcopy(value)
        for key, value in probation.items()
        if key not in {"audit_id", "probation_sha256", "probation_ref"}
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_probation(
    workspace: Workspace,
    runtime: WorkspaceAppRuntime,
    raw_state: Mapping[str, Any],
    *,
    db: DBSession | None = None,
) -> str:
    _validated_rollout_history(workspace, raw_state, active=False, db=db)
    probation = raw_state.get("probation")
    if not isinstance(probation, Mapping):
        raise WorkspaceAppRuntimeError(
            "Workspace App runtime has neither probation nor activation",
            code="rollout_attestation_missing",
        )
    _validate_runtime_binding(workspace, runtime, probation)
    _attested_digest(probation, "preflight_evidence_sha256")
    _attested_digest(probation, "preflight_artifact_sha256")
    probation_digest = _attested_digest(probation, "probation_sha256")
    if probation_digest != _probation_digest(probation):
        raise WorkspaceAppRuntimeError(
            "Workspace App probation digest is invalid",
            code="rollout_attestation_invalid",
        )
    tests = probation.get("preflight_artifact_tests")
    if tests != WORKSPACE_APP_PREFLIGHT_CHECK_COUNT or isinstance(tests, bool):
        raise WorkspaceAppRuntimeError(
            "Workspace App probation has no valid preflight proof",
            code="rollout_attestation_invalid",
        )
    staged_at = _rollout_timestamp(probation.get("staged_at"), field="staged_at")
    expires_at = _rollout_timestamp(probation.get("expires_at"), field="expires_at")
    now = datetime.now(UTC)
    if expires_at <= staged_at or expires_at - staged_at > WORKSPACE_APP_PROBATION_MAX_AGE:
        raise WorkspaceAppRuntimeError(
            "Workspace App probation lease is invalid",
            code="rollout_attestation_invalid",
        )
    if now >= expires_at:
        raise WorkspaceAppRuntimeError(
            "Workspace App probation has expired",
            code="rollout_probation_expired",
        )
    trusted_runner = _validated_persisted_trusted_runner(probation)
    _require_workspace_app_rollout_audit(
        workspace,
        probation,
        db=db,
        event_type="lot9.workspace_app_platform.staged",
        actor_field="staged_by",
        details=_workspace_app_probation_audit_details(
            probation,
            trusted_runner=trusted_runner,
        ),
    )
    return f"sha256:{probation_digest}"


def validate_workspace_app_runtime_activation(
    workspace: Workspace,
    runtime: WorkspaceAppRuntime,
    *,
    db: DBSession | None = None,
) -> tuple[str, str]:
    """Return the explicit rollout phase and proof ref, or fail closed.

    Lifecycle rows are mutable operational state. The feature flag alone must
    therefore never authorize them. A short probation may expose the
    authoritative runtime solely to generate post-activation behaviour proof;
    it is bound to workspace, SHA, canonical configuration and installation set
    and expires fail-closed. Final activation additionally binds that proof.
    """

    raw_state = _rollout_state(workspace, required=True)
    assert raw_state is not None
    if raw_state.get("probation") is not None:
        probation_ref = _validate_probation(workspace, runtime, raw_state, db=db)
        return "probation", probation_ref

    activations, _deactivations = _validated_rollout_history(
        workspace,
        raw_state,
        active=True,
        db=db,
    )
    if not activations:
        raise WorkspaceAppRuntimeError(
            "Workspace App runtime has no final activation",
            code="rollout_attestation_missing",
        )
    latest = activations[-1]
    _validate_runtime_binding(workspace, runtime, latest)
    _attested_digest(latest, "preflight_evidence_sha256")
    _attested_digest(latest, "preflight_artifact_sha256")
    artifact_tests = latest.get("artifact_tests")
    if (
        isinstance(artifact_tests, bool)
        or artifact_tests
        != WORKSPACE_APP_PREFLIGHT_CHECK_COUNT + WORKSPACE_APP_POSTACTIVATION_CHECK_COUNT
        or latest.get("preflight_artifact_tests") != WORKSPACE_APP_PREFLIGHT_CHECK_COUNT
        or latest.get("postactivation_artifact_tests") != WORKSPACE_APP_POSTACTIVATION_CHECK_COUNT
    ):
        raise WorkspaceAppRuntimeError(
            "Workspace App activation has no valid runner proof",
            code="rollout_attestation_invalid",
        )
    probation_ref = str(latest.get("probation_ref") or "").strip()
    if (
        not probation_ref.startswith("sha256:")
        or _SHA256_RE.fullmatch(probation_ref.removeprefix("sha256:")) is None
    ):
        raise WorkspaceAppRuntimeError(
            "Workspace App activation has no probation lineage",
            code="rollout_attestation_invalid",
        )
    return "active", str(latest["evidence_ref"])


def resolve_workspace_app_runtime(
    workspace: Workspace,
    *,
    db: DBSession | None = None,
) -> WorkspaceAppRuntime:
    """Resolve the authoritative app projection, or a no-op legacy marker."""

    if not workspace_app_platform_enabled(workspace):
        return WorkspaceAppRuntime(
            mode="legacy",
            enabled=False,
            rollout_phase="disabled",
            rollout_ref=None,
            installations=(),
            shell="legacy",
            routes=(),
            primary_surface_ids=(),
            default_routes={},
            branding_namespaces=(),
            api_prefixes=(),
            action_packs=(),
            mission_room=None,
        )

    runtime = inspect_authoritative_workspace_app_runtime(
        workspace,
        db=db,
    )
    rollout_phase, rollout_ref = validate_workspace_app_runtime_activation(
        workspace,
        runtime,
        db=db,
    )
    return replace(runtime, rollout_phase=rollout_phase, rollout_ref=rollout_ref)


def resolve_mission_room_provider_runtime(
    workspace: Workspace,
    *,
    db: DBSession | None = None,
) -> WorkspaceAppRuntime:
    """Resolve the installed provider that may serve Mission Room payloads.

    Legacy provider apps are recognized by their immutable app identity.  A
    generic extension is recognized only when its immutable manifest declares
    the exact provider kind and endpoint contract implemented by the backend.
    An older installable manifest therefore remains provider-less and cannot
    inherit Sentinel fixtures merely because it claims the same route.
    """

    if not workspace_app_platform_enabled(workspace):
        raise WorkspaceAppRuntimeError(
            "authoritative Mission Room provider requires the Workspace App platform",
            code="workspace_app_platform_disabled",
        )
    runtime = resolve_workspace_app_runtime(workspace, db=db)
    projection = runtime.mission_room
    app_id = projection.get("app_id") if isinstance(projection, Mapping) else None
    is_generic_provider = (
        (
            app_id == "mission-room.extension"
            and projection.get("provider_kind") == GENERIC_MISSION_ROOM_PROVIDER_KIND
            and projection.get("provider_endpoints")
            == list(GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS)
        )
        if isinstance(projection, Mapping)
        else False
    )
    if app_id not in MISSION_ROOM_PROVIDER_APP_IDS and not is_generic_provider:
        raise WorkspaceAppRuntimeError(
            "installed Mission Room application has no runtime provider",
            code="mission_room_provider_unavailable",
        )
    return runtime


def mission_room_provider_request_allowed(
    runtime: WorkspaceAppRuntime,
    method: str,
    request_path: str,
) -> bool:
    """Authorize one exact route against the resolved provider contract.

    Sentinel and Octocity retain the complete historical Mission Room router.
    The provider-neutral extension gets only the core endpoints explicitly
    declared by its manifest.  Prefix ownership alone is intentionally
    insufficient because maritime, webcam, satellite and document endpoints
    share that prefix while remaining tenant-app-specific.
    """

    projection = runtime.mission_room
    if not isinstance(projection, Mapping):
        return False
    path = str(request_path or "").split("?", 1)[0].rstrip("/") or "/"
    prefix = "/api/v1/mission-room"
    if not path.startswith(f"{prefix}/"):
        return False
    app_id = str(projection.get("app_id") or "")
    if app_id in MISSION_ROOM_PROVIDER_APP_IDS:
        return True
    if (
        app_id != "mission-room.extension"
        or projection.get("provider_kind") != GENERIC_MISSION_ROOM_PROVIDER_KIND
        or projection.get("provider_endpoints") != list(GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS)
    ):
        return False
    relative_path = path.removeprefix(prefix)
    contract = f"{str(method or '').upper()} {relative_path}"
    return contract in GENERIC_MISSION_ROOM_PROVIDER_ENDPOINTS


def safe_workspace_app_runtime_payload(
    workspace: Workspace,
    *,
    db: DBSession | None = None,
) -> dict[str, Any]:
    """Bootstrap payload that never exposes invalid row contents."""

    try:
        return resolve_workspace_app_runtime(workspace, db=db).as_public_payload()
    except WorkspaceAppRuntimeError as exc:
        return {
            "schema_version": 1,
            "mode": "authoritative",
            "enabled": True,
            "rollout_phase": "invalid",
            "rollout_ref": None,
            "valid": False,
            "error_code": exc.code,
            "installations": [],
            "experience": None,
        }


def installed_app_ids(
    workspace: Workspace,
    *,
    db: DBSession | None = None,
) -> frozenset[str]:
    runtime = resolve_workspace_app_runtime(workspace, db=db)
    return frozenset(runtime.app_ids)


def installed_action_packs(
    workspace: Workspace,
    *,
    db: DBSession | None = None,
) -> tuple[str, ...]:
    return resolve_workspace_app_runtime(workspace, db=db).action_packs


def installed_entitlement_keys(
    workspace: Workspace,
    *,
    db: DBSession | None = None,
) -> frozenset[str]:
    """Return entry entitlements owned by the exact installed manifests.

    The manifest is the Workspace App contract. Keeping a parallel mapping in
    application code would make a newly versioned app installable while its
    declared surface remains unreachable until another hardcoded list is
    updated. Trusted-manifest resolution already fails closed on digest or
    compatibility drift, so deriving the keys here preserves that boundary.
    """

    runtime = resolve_workspace_app_runtime(workspace, db=db)
    return frozenset(
        entitlement
        for application in runtime.installations
        for entitlement in application.payload["entitlement_keys"]
    )


def installed_api_prefixes(
    workspace: Workspace,
    *,
    db: DBSession | None = None,
    app_ids: Sequence[str] | None = None,
    entitlement_keys: Sequence[str] | None = None,
) -> frozenset[str]:
    """Return API prefixes owned by the selected installed manifests.

    A manifest surface is an authority boundary, not documentation.  Callers
    may select the owner either by app identity (extensions) or by an
    entitlement declared by the app (business routers).  With no selector the
    complete installed prefix set is returned.
    """

    runtime = resolve_workspace_app_runtime(workspace, db=db)
    selected_apps = {str(value).strip() for value in (app_ids or ()) if str(value).strip()}
    selected_entitlements = {
        str(value).strip() for value in (entitlement_keys or ()) if str(value).strip()
    }
    prefixes: set[str] = set()
    for application in runtime.installations:
        payload = application.payload
        if selected_apps and application.manifest.app_id not in selected_apps:
            continue
        declared_entitlements = {str(value) for value in payload.get("entitlement_keys", ())}
        if selected_entitlements and not selected_entitlements.intersection(declared_entitlements):
            continue
        for declared_prefix in _application_api_prefixes(payload):
            prefix = declared_prefix.rstrip("/")
            if not prefix.startswith("/api/v1/"):
                raise WorkspaceAppRuntimeError(
                    "installed app API prefix is invalid",
                    code="experience_contract_invalid",
                )
            prefixes.add(prefix)
    return frozenset(prefixes)


def workspace_app_api_path_allowed(
    workspace: Workspace,
    request_path: str,
    *,
    db: DBSession | None = None,
    app_ids: Sequence[str] | None = None,
    entitlement_keys: Sequence[str] | None = None,
) -> bool:
    """Fail-closed path matcher for an authoritative app API surface."""

    path = str(request_path or "").split("?", 1)[0].rstrip("/") or "/"
    prefixes = installed_api_prefixes(
        workspace,
        db=db,
        app_ids=app_ids,
        entitlement_keys=entitlement_keys,
    )
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)
