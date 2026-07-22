"""Transactional lifecycle for precompiled Workspace App manifests.

``plan_workspace_app_lifecycle`` is read-only.  ``apply_workspace_app_lifecycle``
locks the Workspace row (the tenant-wide lifecycle mutex), rebuilds that exact
plan, verifies its SHA-256 and commits installation state, idempotency receipt
and audit event atomically.

This service does not mutate legacy ``workspace.settings["apps"]`` or member
entitlements.  Those contracts remain separate until an explicit backfill is
reviewed and applied.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, NoReturn
from uuid import uuid4

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.models.audit import AuditLog
from app.models.workspace import Workspace
from app.models.workspace_app import (
    WorkspaceAppInstallation,
    WorkspaceAppLifecycleStepReceipt,
    WorkspaceAppOperation,
)
from app.schemas.canonical import WorkspaceFamily
from app.services.workspace_app_boundaries import (
    WORKSPACE_APP_REQUIRED_FOREIGN_KEYS,
    WORKSPACE_APP_REQUIRED_UNIQUE_CONSTRAINTS,
    WorkspaceAppBoundaryContractError,
    manifest_api_prefixes,
    slash_boundary_paths_overlap,
    workspace_app_relational_integrity_errors,
)
from app.services.workspace_app_manifests import (
    CompiledWorkspaceAppManifest,
    WorkspaceAppManifestError,
    WorkspaceAppManifestNotFound,
    get_builtin_workspace_app_manifest,
    parse_semver,
    validate_manifest_configuration,
)
from app.services.workspace_app_runtime import workspace_app_platform_enabled

LIFECYCLE_OPERATIONS = frozenset({"install", "upgrade", "rollback", "uninstall"})
LIFECYCLE_PHASES = frozenset({"normal", "legacy_adoption"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class WorkspaceAppLifecycleError(RuntimeError):
    """Base lifecycle error with a stable machine-readable code."""

    code = "workspace_app_lifecycle_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class WorkspaceAppLifecycleNotFound(WorkspaceAppLifecycleError):  # noqa: N818
    code = "not_found"


class WorkspaceAppLifecycleConflict(WorkspaceAppLifecycleError):  # noqa: N818
    code = "conflict"


class WorkspaceAppLifecycleValidationError(WorkspaceAppLifecycleError):
    code = "invalid_request"


@dataclass(frozen=True)
class WorkspaceAppLifecycleStep:
    position: int
    manifest_role: str
    manifest_digest: str
    step_id: str
    kind: str
    phase: str
    executor: str
    required: bool
    reversibility: str
    step_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "manifest_role": self.manifest_role,
            "manifest_digest": self.manifest_digest,
            "step_id": self.step_id,
            "kind": self.kind,
            "phase": self.phase,
            "executor": self.executor,
            "required": self.required,
            "reversibility": self.reversibility,
            "step_sha256": self.step_sha256,
        }


@dataclass(frozen=True)
class WorkspaceAppLifecyclePlan:
    workspace_id: str
    app_id: str
    operation: str
    from_state: str
    from_version: str | None
    from_manifest_digest: str | None
    from_revision: int
    to_state: str
    to_version: str | None
    to_manifest_digest: str | None
    configuration: dict[str, Any]
    configuration_fields: tuple[str, ...]
    lifecycle_phase: str
    steps: tuple[WorkspaceAppLifecycleStep, ...]
    steps_sha256: str
    compensation: dict[str, Any]
    plan_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "app_id": self.app_id,
            "operation": self.operation,
            "from": {
                "state": self.from_state,
                "version": self.from_version,
                "manifest_digest": self.from_manifest_digest,
                "revision": self.from_revision,
            },
            "to": {
                "state": self.to_state,
                "version": self.to_version,
                "manifest_digest": self.to_manifest_digest,
                "configuration": deepcopy(self.configuration),
            },
            "configuration_fields": list(self.configuration_fields),
            "lifecycle_phase": self.lifecycle_phase,
            "steps": [step.as_dict() for step in self.steps],
            "steps_sha256": self.steps_sha256,
            "compensation": deepcopy(self.compensation),
            "plan_sha256": self.plan_sha256,
        }


@dataclass(frozen=True)
class WorkspaceAppLifecycleResult:
    operation: WorkspaceAppOperation
    installation: WorkspaceAppInstallation
    step_receipts: tuple[WorkspaceAppLifecycleStepReceipt, ...]
    result_snapshot: dict[str, Any]
    idempotent_replay: bool


@dataclass(frozen=True)
class WorkspaceAppLifecycleCompensationResult:
    """One exact, idempotent inverse of a committed lifecycle operation."""

    source_operation: WorkspaceAppOperation
    inverse: WorkspaceAppLifecycleResult


def _required_text(value: Any, name: str, *, maximum: int) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkspaceAppLifecycleValidationError(f"{name} is required")
    if len(text) > maximum:
        raise WorkspaceAppLifecycleValidationError(f"{name} exceeds {maximum} characters")
    return text


def _sha256(value: Any, name: str) -> str:
    digest = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(digest) is None:
        raise WorkspaceAppLifecycleValidationError(f"{name} must be a SHA-256 hex digest")
    return digest


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
        raise WorkspaceAppLifecycleValidationError("request must be canonical JSON") from exc


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalize_configuration(configuration: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if configuration is None:
        return None
    if not isinstance(configuration, Mapping):
        raise WorkspaceAppLifecycleValidationError("configuration must be an object")
    normalized = deepcopy(dict(configuration))
    _canonical_json(normalized)
    return normalized


def _normalize_prerequisite_evidence(
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if evidence is None:
        return None
    if not isinstance(evidence, Mapping):
        raise WorkspaceAppLifecycleValidationError("prerequisite_evidence must be an object")
    normalized = deepcopy(dict(evidence))
    _canonical_json(normalized)
    return normalized


def _workspace(
    db: DBSession,
    workspace_id: str,
    *,
    lock: bool,
) -> Workspace:
    query = db.query(Workspace).filter(Workspace.id == workspace_id)
    if lock:
        query = query.with_for_update(of=Workspace)
    workspace = query.first()
    if workspace is None:
        raise WorkspaceAppLifecycleNotFound("Workspace not found")
    return workspace


def _installation(
    db: DBSession,
    *,
    workspace_id: str,
    app_id: str,
    lock: bool,
) -> WorkspaceAppInstallation | None:
    query = db.query(WorkspaceAppInstallation).filter(
        WorkspaceAppInstallation.workspace_id == workspace_id,
        WorkspaceAppInstallation.app_id == app_id,
    )
    if lock:
        query = query.with_for_update(of=WorkspaceAppInstallation)
    return query.first()


def _snapshot(installation: WorkspaceAppInstallation | None) -> dict[str, Any]:
    if installation is None:
        return {
            "state": "absent",
            "version": None,
            "manifest_digest": None,
            "configuration": {},
            "revision": 0,
        }
    return {
        "state": installation.state,
        "version": installation.version,
        "manifest_digest": installation.manifest_digest,
        "configuration": deepcopy(
            installation.configuration if isinstance(installation.configuration, Mapping) else {}
        ),
        "revision": int(installation.revision or 0),
    }


def _compensation_request(
    source: WorkspaceAppOperation,
) -> tuple[str, str | None, str, dict[str, Any] | None, bool]:
    """Derive the only valid semantic inverse from an immutable receipt."""

    before = source.before_state if isinstance(source.before_state, Mapping) else {}
    after = source.after_state if isinstance(source.after_state, Mapping) else {}
    before_version = before.get("version")
    before_digest = before.get("manifest_digest")
    before_configuration = before.get("configuration")
    after_digest = after.get("manifest_digest")

    if source.operation == "install":
        return "uninstall", None, _sha256(after_digest, "after manifest digest"), None, False
    if source.operation == "upgrade":
        return (
            "rollback",
            _required_text(before_version, "before version", maximum=40),
            _sha256(before_digest, "before manifest digest"),
            _normalize_configuration(before_configuration),
            True,
        )
    if source.operation == "rollback":
        return (
            "upgrade",
            _required_text(before_version, "before version", maximum=40),
            _sha256(before_digest, "before manifest digest"),
            _normalize_configuration(before_configuration),
            False,
        )
    if source.operation == "uninstall":
        return (
            "install",
            _required_text(before_version, "before version", maximum=40),
            _sha256(before_digest, "before manifest digest"),
            _normalize_configuration(before_configuration),
            False,
        )
    raise WorkspaceAppLifecycleConflict(
        "source receipt has no supported inverse operation",
        code="compensation_source_invalid",
    )


def _resolve_manifest(
    app_id: str,
    version: str,
    expected_digest: str,
) -> CompiledWorkspaceAppManifest:
    try:
        return get_builtin_workspace_app_manifest(
            app_id,
            version,
            expected_digest=expected_digest,
        )
    except WorkspaceAppManifestNotFound as exc:
        raise WorkspaceAppLifecycleNotFound(
            str(exc),
            code="manifest_not_found",
        ) from exc
    except WorkspaceAppManifestError as exc:
        raise WorkspaceAppLifecycleValidationError(
            str(exc),
            code="manifest_contract_invalid",
        ) from exc


def _validated_configuration(
    manifest: CompiledWorkspaceAppManifest,
    configuration: Mapping[str, Any] | None,
    *,
    base: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return validate_manifest_configuration(manifest, configuration, base=base)
    except WorkspaceAppManifestError as exc:
        raise WorkspaceAppLifecycleValidationError(
            str(exc),
            code="configuration_invalid",
        ) from exc


def validate_workspace_app_compatibility(
    workspace: Workspace,
    manifest: CompiledWorkspaceAppManifest,
) -> dict[str, str | None]:
    """Validate canonical family/profile compatibility without identity heuristics.

    The returned context is deliberately limited to non-sensitive structural
    markers and can be included in deterministic lifecycle plans. Workspace
    slug and display name are never consulted.
    """

    settings = workspace.settings if isinstance(workspace.settings, Mapping) else {}
    raw_family = settings.get("family")
    try:
        family = WorkspaceFamily(str(raw_family or "").strip().lower()).value
    except ValueError as exc:
        raise WorkspaceAppLifecycleConflict(
            "Workspace has no canonical family for this Workspace App",
            code="workspace_family_invalid",
        ) from exc

    mission_room = settings.get("mission_room")
    mission_room = mission_room if isinstance(mission_room, Mapping) else {}
    raw_profile = mission_room.get("profile")
    profile = str(raw_profile).strip() if isinstance(raw_profile, str) else None
    profile = profile or None

    payload = manifest.as_dict()
    compatibility = payload.get("compatibility")
    if not isinstance(compatibility, Mapping):
        raise WorkspaceAppLifecycleValidationError(
            "trusted Workspace App compatibility contract is invalid",
            code="manifest_contract_invalid",
        )
    allowed_families = compatibility.get("workspace_families")
    if not isinstance(allowed_families, list) or family not in allowed_families:
        raise WorkspaceAppLifecycleConflict(
            "Workspace App is incompatible with the canonical workspace family",
            code="workspace_family_incompatible",
        )
    allowed_profiles = compatibility.get("workspace_profiles")
    forbidden_profiles = compatibility.get("forbidden_workspace_profiles")
    if not isinstance(allowed_profiles, list) or not isinstance(forbidden_profiles, list):
        raise WorkspaceAppLifecycleValidationError(
            "trusted Workspace App profile contract is invalid",
            code="manifest_contract_invalid",
        )
    if allowed_profiles and profile not in allowed_profiles:
        raise WorkspaceAppLifecycleConflict(
            "Workspace App is incompatible with the structural workspace profile",
            code="workspace_profile_incompatible",
        )
    if profile in forbidden_profiles:
        raise WorkspaceAppLifecycleConflict(
            "Generic Workspace App cannot claim a reserved workspace profile",
            code="workspace_profile_reserved",
        )
    return {"family": family, "profile": profile}


def workspace_app_is_compatible(
    workspace: Workspace,
    manifest: CompiledWorkspaceAppManifest,
) -> bool:
    """Return whether a trusted manifest is structurally compatible."""

    try:
        validate_workspace_app_compatibility(workspace, manifest)
    except WorkspaceAppLifecycleConflict:
        return False
    return True


def _validate_coinstallation_contracts(
    db: DBSession,
    *,
    workspace_id: str,
    app_id: str,
    target_manifest: CompiledWorkspaceAppManifest,
    lock: bool,
) -> None:
    target = target_manifest.as_dict()
    target_routes = target.get("routes")
    target_exclusive = target.get("exclusive_routes") is True
    target_group = target.get("conflict_group")
    target_experience = target.get("experience")
    target_shell = (
        target_experience.get("shell") if isinstance(target_experience, Mapping) else None
    )
    try:
        target_api_prefixes = manifest_api_prefixes(target)
    except WorkspaceAppBoundaryContractError as exc:
        raise WorkspaceAppLifecycleValidationError(
            "trusted Workspace App API authority contract is invalid",
            code="manifest_contract_invalid",
        ) from exc

    query = db.query(WorkspaceAppInstallation).filter(
        WorkspaceAppInstallation.workspace_id == workspace_id,
        WorkspaceAppInstallation.state == "installed",
        WorkspaceAppInstallation.app_id != app_id,
    )
    if lock:
        query = query.with_for_update(of=WorkspaceAppInstallation)
    for other in query.order_by(WorkspaceAppInstallation.app_id.asc()).all():
        if not other.version or not other.manifest_digest:
            raise WorkspaceAppLifecycleConflict(
                "An installed Workspace App has an incomplete trusted state",
                code="installed_manifest_invalid",
            )
        try:
            other_manifest = _resolve_manifest(
                other.app_id,
                other.version,
                other.manifest_digest,
            )
        except WorkspaceAppLifecycleError as exc:
            raise WorkspaceAppLifecycleConflict(
                "An installed Workspace App no longer resolves to a trusted manifest",
                code="installed_manifest_invalid",
            ) from exc
        other_payload = other_manifest.as_dict()
        try:
            other_api_prefixes = manifest_api_prefixes(other_payload)
        except WorkspaceAppBoundaryContractError as exc:
            raise WorkspaceAppLifecycleConflict(
                "An installed Workspace App has an invalid API authority contract",
                code="installed_manifest_invalid",
            ) from exc
        other_group = other_payload.get("conflict_group")
        if target_group is not None and target_group == other_group:
            raise WorkspaceAppLifecycleConflict(
                "Workspace Apps belong to the same exclusive conflict group",
                code="conflict_group",
            )
        other_routes = other_payload.get("routes")
        other_exclusive = other_payload.get("exclusive_routes") is True
        if (
            (target_exclusive or other_exclusive)
            and isinstance(target_routes, list)
            and isinstance(other_routes, list)
            and any(
                slash_boundary_paths_overlap(target_route, other_route)
                for target_route in target_routes
                for other_route in other_routes
            )
        ):
            raise WorkspaceAppLifecycleConflict(
                "Workspace Apps claim overlapping exclusive routes",
                code="route_conflict",
            )
        if any(
            slash_boundary_paths_overlap(target_prefix, other_prefix)
            for target_prefix in target_api_prefixes
            for other_prefix in other_api_prefixes
        ):
            raise WorkspaceAppLifecycleConflict(
                "Workspace Apps claim overlapping API authority prefixes",
                code="api_prefix_conflict",
            )
        other_experience = other_payload.get("experience")
        other_shell = (
            other_experience.get("shell") if isinstance(other_experience, Mapping) else None
        )
        if (
            target_shell in {"business", "immersive"}
            and other_shell in {"business", "immersive"}
            and target_shell != other_shell
        ):
            raise WorkspaceAppLifecycleConflict(
                "Workspace Apps require incompatible workspace shells",
                code="shell_conflict",
            )


def _lifecycle_phase(value: Any) -> str:
    phase = _required_text(value, "lifecycle_phase", maximum=32).lower()
    if phase not in LIFECYCLE_PHASES:
        raise WorkspaceAppLifecycleValidationError("unsupported Workspace App lifecycle phase")
    return phase


def _transition_compensation(
    operation: str,
    before: Mapping[str, Any],
) -> dict[str, Any]:
    post_commit = {
        "install": "uninstall",
        "upgrade": "rollback_exact_before_state",
        "rollback": "upgrade_exact_before_state",
        "uninstall": "install_exact_before_state",
    }[operation]
    return {
        "failure": "database_transaction_rollback",
        "post_commit": post_commit,
        "before_state_sha256": _hash_payload({"state": dict(before)}),
    }


def _compile_lifecycle_steps(
    *,
    operation: str,
    lifecycle_phase: str,
    source_manifest: CompiledWorkspaceAppManifest | None,
    target_manifest: CompiledWorkspaceAppManifest | None,
) -> tuple[WorkspaceAppLifecycleStep, ...]:
    if lifecycle_phase == "legacy_adoption" and (operation != "install" or target_manifest is None):
        raise WorkspaceAppLifecycleValidationError(
            "legacy_adoption is only valid for an explicit install"
        )

    raw_steps: list[tuple[str, CompiledWorkspaceAppManifest, Mapping[str, Any]]] = []
    manifests = (
        (("source", source_manifest), ("target", target_manifest))
        if source_manifest is not None and target_manifest is not None
        else (("source", source_manifest),)
        if source_manifest is not None
        else (("target", target_manifest),)
    )
    for role, manifest in manifests:
        if manifest is None:
            continue
        payload = manifest.as_dict()
        migrations = payload.get("migrations")
        if not isinstance(migrations, list):
            raise WorkspaceAppLifecycleValidationError(
                "trusted manifest migrations contract is invalid",
                code="manifest_contract_invalid",
            )
        raw_steps.extend((role, manifest, item) for item in migrations)
        if role == "target" and lifecycle_phase == "legacy_adoption":
            backfills = payload.get("backfills")
            if not isinstance(backfills, list):
                raise WorkspaceAppLifecycleValidationError(
                    "trusted manifest backfills contract is invalid",
                    code="manifest_contract_invalid",
                )
            raw_steps.extend((role, manifest, item) for item in backfills)

    steps: list[WorkspaceAppLifecycleStep] = []
    for position, (role, manifest, raw) in enumerate(raw_steps):
        if not isinstance(raw, Mapping):
            raise WorkspaceAppLifecycleValidationError(
                "trusted manifest lifecycle step is invalid",
                code="manifest_contract_invalid",
            )
        step_body = {
            "position": position,
            "manifest_role": role,
            "manifest_digest": manifest.digest,
            "step_id": str(raw.get("id") or ""),
            "kind": str(raw.get("kind") or ""),
            "phase": str(raw.get("phase") or ""),
            "executor": str(raw.get("executor") or ""),
            "required": raw.get("required") is True,
            "reversibility": str(raw.get("reversibility") or ""),
            "manifest_contract": dict(raw),
        }
        step_sha256 = _hash_payload(step_body)
        steps.append(
            WorkspaceAppLifecycleStep(
                position=position,
                manifest_role=role,
                manifest_digest=manifest.digest,
                step_id=step_body["step_id"],
                kind=step_body["kind"],
                phase=step_body["phase"],
                executor=step_body["executor"],
                required=step_body["required"],
                reversibility=step_body["reversibility"],
                step_sha256=step_sha256,
            )
        )
    return tuple(steps)


def _steps_sha256(steps: tuple[WorkspaceAppLifecycleStep, ...]) -> str:
    return _hash_payload({"steps": [step.step_sha256 for step in steps]})


def _require_schema_contract(
    db: DBSession,
    *,
    step: WorkspaceAppLifecycleStep,
    **_context: Any,
) -> dict[str, Any]:
    contracts = {
        "workspace_app_platform.schema.069": {
            "workspace_app_installations": {
                "workspace_id",
                "app_id",
                "manifest_digest",
                "revision",
            },
            "workspace_app_operations": {
                "workspace_id",
                "installation_id",
                "plan_sha256",
                "before_state",
                "after_state",
            },
        },
        "workspace_app_platform.lifecycle_steps.073": {
            "workspace_app_operations": {
                "lifecycle_phase",
                "steps_sha256",
                "compensation",
            },
            "workspace_app_lifecycle_step_receipts": {
                "operation_id",
                "installation_id",
                "step_sha256",
                "executor",
                "outcome",
            },
        },
        "workspace_app_platform.entitlement_registry.070": {
            "workspace_member_app_entitlements": {
                "workspace_member_id",
                "app_key",
                "grant_source",
            },
        },
    }
    required = contracts.get(step.step_id)
    if required is None:
        raise WorkspaceAppLifecycleValidationError(
            f"no closed schema executor contract exists for {step.step_id}",
            code="lifecycle_executor_contract_unknown",
        )
    inspector = inspect(db.get_bind())
    missing: dict[str, list[str]] = {}
    tables = set(inspector.get_table_names())
    for table, columns in required.items():
        observed = (
            {item["name"] for item in inspector.get_columns(table)} if table in tables else set()
        )
        absent = sorted(columns - observed)
        if absent:
            missing[table] = absent
    if missing:
        raise WorkspaceAppLifecycleConflict(
            f"required platform schema is not applied for {step.step_id}",
            code="lifecycle_schema_unsatisfied",
        )
    return {
        "outcome": "verified",
        "evidence_sha256": _hash_payload(
            {
                "step_id": step.step_id,
                "tables": {table: sorted(columns) for table, columns in sorted(required.items())},
            }
        ),
        "compensation": {
            "failure": "database_transaction_rollback",
            "post_commit": "none_required_persistent_additive_schema",
        },
    }


def _require_explicit_legacy_backfill(
    _db: DBSession,
    *,
    workspace: Workspace,
    plan: WorkspaceAppLifecyclePlan,
    step: WorkspaceAppLifecycleStep,
    prerequisite_evidence: Mapping[str, Any] | None,
    **_context: Any,
) -> dict[str, Any]:
    evidence = (
        prerequisite_evidence.get(step.step_id)
        if isinstance(prerequisite_evidence, Mapping)
        else None
    )
    if not isinstance(evidence, Mapping):
        raise WorkspaceAppLifecycleConflict(
            f"explicit legacy backfill evidence is required for {step.step_id}",
            code="lifecycle_prerequisite_unsatisfied",
        )
    report = deepcopy(dict(evidence))
    claimed_sha256 = str(report.pop("analysis_sha256", "")).strip().lower()
    if _SHA256_RE.fullmatch(claimed_sha256) is None or _hash_payload(report) != claimed_sha256:
        raise WorkspaceAppLifecycleValidationError(
            "legacy backfill analysis is not content-addressed",
            code="lifecycle_prerequisite_invalid",
        )
    if (
        report.get("schema_version") != 1
        or report.get("selection") != "explicit_workspace_ids"
        or report.get("ready") is not True
        or report.get("blockers") != []
    ):
        raise WorkspaceAppLifecycleConflict(
            "legacy backfill analysis is not an applicable explicit prerequisite",
            code="lifecycle_prerequisite_unsatisfied",
        )
    requested = report.get("requested_workspace_ids")
    if not isinstance(requested, list) or workspace.id not in requested:
        raise WorkspaceAppLifecycleConflict(
            "legacy backfill analysis does not explicitly select this Workspace",
            code="lifecycle_prerequisite_unsatisfied",
        )
    changes = report.get("changes")
    matching = (
        [
            item
            for item in changes
            if isinstance(item, Mapping)
            and item.get("workspace_id") == workspace.id
            and item.get("app_id") == plan.app_id
            and item.get("version") == plan.to_version
            and item.get("manifest_digest") == plan.to_manifest_digest
            and item.get("operation") == "install"
            and item.get("reason") == "legacy_contract_detected"
            and item.get("plan_sha256") == plan.plan_sha256
        ]
        if isinstance(changes, list)
        else []
    )
    if len(matching) != 1:
        raise WorkspaceAppLifecycleConflict(
            "legacy backfill analysis does not attest this exact lifecycle plan",
            code="lifecycle_prerequisite_unsatisfied",
        )
    return {
        "outcome": "verified",
        "evidence_sha256": claimed_sha256,
        "compensation": {
            "failure": "database_transaction_rollback",
            "post_commit": "restore_operation_before_state",
        },
    }


def _require_relational_integrity_contract(
    db: DBSession,
    *,
    step: WorkspaceAppLifecycleStep,
    **_context: Any,
) -> dict[str, Any]:
    """Verify the tenant/installation lineage constraints added by 074.

    Merely observing columns from migrations 069/073 is insufficient: a
    runtime without the composite keys can still accept a cross-workspace app
    operation. The lifecycle receipt therefore binds the exact relational
    constraints before an installation becomes activatable.
    """

    missing = workspace_app_relational_integrity_errors(db)
    if missing:
        raise WorkspaceAppLifecycleConflict(
            "required relational integrity schema is not applied: " + ", ".join(missing),
            code="lifecycle_schema_unsatisfied",
        )
    return {
        "outcome": "verified",
        "evidence_sha256": _hash_payload(
            {
                "step_id": step.step_id,
                "unique_constraints": sorted(WORKSPACE_APP_REQUIRED_UNIQUE_CONSTRAINTS),
                "foreign_keys": sorted(WORKSPACE_APP_REQUIRED_FOREIGN_KEYS),
            }
        ),
        "compensation": {
            "failure": "database_transaction_rollback",
            "post_commit": "none_required_persistent_additive_schema",
        },
    }


LIFECYCLE_STEP_EXECUTORS = MappingProxyType(
    {
        "platform_schema_contract_v1": _require_schema_contract,
        "relational_integrity_contract_v1": _require_relational_integrity_contract,
        "explicit_legacy_backfill_v1": _require_explicit_legacy_backfill,
    }
)


def _execute_lifecycle_steps(
    db: DBSession,
    *,
    workspace: Workspace,
    plan: WorkspaceAppLifecyclePlan,
    prerequisite_evidence: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for step in plan.steps:
        executor = LIFECYCLE_STEP_EXECUTORS.get(step.executor)
        if executor is None:
            raise WorkspaceAppLifecycleValidationError(
                f"lifecycle executor {step.executor} is not registered",
                code="lifecycle_executor_unknown",
            )
        result = executor(
            db,
            workspace=workspace,
            plan=plan,
            step=step,
            prerequisite_evidence=prerequisite_evidence,
        )
        if not isinstance(result, Mapping) or result.get("outcome") not in {
            "verified",
            "executed",
            "compensated",
        }:
            raise WorkspaceAppLifecycleValidationError(
                f"lifecycle executor {step.executor} returned an invalid receipt",
                code="lifecycle_executor_invalid_result",
            )
        results.append(dict(result))
    return results


def _build_plan(
    db: DBSession,
    *,
    workspace_id: str,
    operation: str,
    app_id: str,
    target_version: str | None,
    expected_manifest_digest: str,
    configuration: Mapping[str, Any] | None,
    lifecycle_phase: str,
    allow_unrecorded_rollback: bool,
    lock: bool,
) -> tuple[WorkspaceAppLifecyclePlan, WorkspaceAppInstallation | None]:
    workspace_key = _required_text(workspace_id, "workspace_id", maximum=36)
    operation_key = _required_text(operation, "operation", maximum=24).lower()
    if operation_key not in LIFECYCLE_OPERATIONS:
        raise WorkspaceAppLifecycleValidationError("unsupported Workspace App operation")
    app_key = _required_text(app_id, "app_id", maximum=120)
    phase_key = _lifecycle_phase(lifecycle_phase)
    expected_digest = _sha256(expected_manifest_digest, "expected_manifest_digest")
    normalized_config = _normalize_configuration(configuration)
    workspace = _workspace(db, workspace_key, lock=lock)
    integrity_errors = workspace_app_relational_integrity_errors(db)
    if integrity_errors:
        raise WorkspaceAppLifecycleConflict(
            "required relational integrity schema is not applied: " + ", ".join(integrity_errors),
            code="lifecycle_schema_unsatisfied",
        )
    if workspace_app_platform_enabled(workspace):
        raise WorkspaceAppLifecycleConflict(
            "Deactivate Workspace App runtime authority before changing installations",
            code="runtime_authority_active",
        )
    installation = _installation(
        db,
        workspace_id=workspace_key,
        app_id=app_key,
        lock=lock,
    )
    before = _snapshot(installation)

    source_manifest: CompiledWorkspaceAppManifest | None = None
    target_manifest: CompiledWorkspaceAppManifest | None = None
    target_config: dict[str, Any] = {}
    target_version_key: str | None = None

    if operation_key == "install":
        if installation is not None and installation.state == "installed":
            raise WorkspaceAppLifecycleConflict("Workspace App is already installed")
        target_version_key = _required_text(target_version, "target_version", maximum=40)
        target_manifest = _resolve_manifest(app_key, target_version_key, expected_digest)
        target_config = _validated_configuration(target_manifest, normalized_config)
    elif operation_key in {"upgrade", "rollback"}:
        if installation is None or installation.state != "installed":
            raise WorkspaceAppLifecycleConflict("Workspace App is not installed")
        if not installation.version or not installation.manifest_digest:
            raise WorkspaceAppLifecycleConflict("installed Workspace App state is incomplete")
        source_manifest = _resolve_manifest(
            app_key,
            installation.version,
            installation.manifest_digest,
        )
        target_version_key = _required_text(target_version, "target_version", maximum=40)
        target_manifest = _resolve_manifest(app_key, target_version_key, expected_digest)
        try:
            current_semver = parse_semver(installation.version)
            target_semver = parse_semver(target_version_key)
        except WorkspaceAppManifestError as exc:
            raise WorkspaceAppLifecycleValidationError(str(exc)) from exc
        if operation_key == "upgrade" and target_semver <= current_semver:
            raise WorkspaceAppLifecycleValidationError(
                "upgrade target must be newer than the installed version"
            )
        if operation_key == "rollback" and target_semver >= current_semver:
            raise WorkspaceAppLifecycleValidationError(
                "rollback target must be older than the installed version"
            )
        current_config = (
            installation.configuration if isinstance(installation.configuration, Mapping) else {}
        )
        if operation_key == "rollback":
            historical = (
                db.query(WorkspaceAppOperation)
                .filter(
                    WorkspaceAppOperation.workspace_id == workspace_key,
                    WorkspaceAppOperation.installation_id == installation.id,
                    WorkspaceAppOperation.app_id == app_key,
                    WorkspaceAppOperation.to_version == target_version_key,
                    WorkspaceAppOperation.manifest_digest == target_manifest.digest,
                )
                .order_by(WorkspaceAppOperation.created_at.desc())
                .first()
            )
            historical_after = historical.after_state if historical is not None else None
            historical_config = (
                historical_after.get("configuration")
                if isinstance(historical_after, Mapping)
                else None
            )
            if not isinstance(historical_config, Mapping) and not allow_unrecorded_rollback:
                raise WorkspaceAppLifecycleConflict(
                    "rollback target was never installed with this exact manifest",
                    code="rollback_target_not_recorded",
                )
            if allow_unrecorded_rollback:
                if normalized_config is None:
                    raise WorkspaceAppLifecycleValidationError(
                        "an authoritative Blueprint restore requires exact configuration"
                    )
                target_config = _validated_configuration(
                    target_manifest,
                    normalized_config,
                )
            elif normalized_config is not None and dict(normalized_config) != dict(
                historical_config
            ):
                raise WorkspaceAppLifecycleConflict(
                    "rollback configuration differs from the recorded target state",
                    code="rollback_configuration_mismatch",
                )
            else:
                target_config = _validated_configuration(
                    target_manifest,
                    historical_config,
                )
        else:
            target_config = _validated_configuration(
                target_manifest,
                normalized_config,
                base=current_config if normalized_config is None else None,
            )
    else:
        if target_version is not None:
            raise WorkspaceAppLifecycleValidationError("uninstall does not accept a target version")
        if normalized_config is not None:
            raise WorkspaceAppLifecycleValidationError("uninstall does not accept configuration")
        if installation is None or installation.state != "installed":
            raise WorkspaceAppLifecycleConflict("Workspace App is not installed")
        if not installation.version or not installation.manifest_digest:
            raise WorkspaceAppLifecycleConflict("installed Workspace App state is incomplete")
        # The caller must acknowledge the exact manifest being removed, and
        # that installed digest must still exist in the trusted registry.
        source_manifest = _resolve_manifest(
            app_key,
            installation.version,
            expected_digest,
        )
        if installation.manifest_digest != expected_digest:
            raise WorkspaceAppLifecycleConflict(
                "installed manifest digest changed before uninstall",
                code="stale_manifest",
            )

    workspace_context: dict[str, str | None] | None = None
    if target_manifest is not None:
        workspace_context = validate_workspace_app_compatibility(workspace, target_manifest)
        _validate_coinstallation_contracts(
            db,
            workspace_id=workspace_key,
            app_id=app_key,
            target_manifest=target_manifest,
            lock=lock,
        )

    to_state = "uninstalled" if operation_key == "uninstall" else "installed"
    to_digest = target_manifest.digest if target_manifest is not None else None
    steps = _compile_lifecycle_steps(
        operation=operation_key,
        lifecycle_phase=phase_key,
        source_manifest=source_manifest,
        target_manifest=target_manifest,
    )
    steps_digest = _steps_sha256(steps)
    compensation = _transition_compensation(operation_key, before)
    plan_body = {
        "workspace_id": workspace_key,
        "app_id": app_key,
        "operation": operation_key,
        "from": before,
        "to": {
            "state": to_state,
            "version": target_version_key,
            "manifest_digest": to_digest,
            "configuration": target_config,
        },
        "workspace_context": workspace_context,
        "lifecycle_phase": phase_key,
        "steps": [step.as_dict() for step in steps],
        "steps_sha256": steps_digest,
        "compensation": compensation,
    }
    plan_digest = _hash_payload(plan_body)
    plan = WorkspaceAppLifecyclePlan(
        workspace_id=workspace_key,
        app_id=app_key,
        operation=operation_key,
        from_state=str(before["state"]),
        from_version=before["version"],
        from_manifest_digest=before["manifest_digest"],
        from_revision=int(before["revision"]),
        to_state=to_state,
        to_version=target_version_key,
        to_manifest_digest=to_digest,
        configuration=target_config,
        configuration_fields=tuple(sorted(target_config)),
        lifecycle_phase=phase_key,
        steps=steps,
        steps_sha256=steps_digest,
        compensation=compensation,
        plan_sha256=plan_digest,
    )
    return plan, installation


def plan_workspace_app_lifecycle(
    db: DBSession,
    *,
    workspace_id: str,
    operation: str,
    app_id: str,
    target_version: str | None,
    expected_manifest_digest: str,
    configuration: Mapping[str, Any] | None = None,
    lifecycle_phase: str = "normal",
    allow_unrecorded_rollback: bool = False,
) -> WorkspaceAppLifecyclePlan:
    """Return a deterministic, read-only plan for one lifecycle transition."""

    plan, _ = _build_plan(
        db,
        workspace_id=workspace_id,
        operation=operation,
        app_id=app_id,
        target_version=target_version,
        expected_manifest_digest=expected_manifest_digest,
        configuration=configuration,
        lifecycle_phase=lifecycle_phase,
        allow_unrecorded_rollback=allow_unrecorded_rollback,
        lock=False,
    )
    return plan


def _request_sha256(
    *,
    workspace_id: str,
    operation: str,
    app_id: str,
    target_version: str | None,
    expected_manifest_digest: str,
    configuration: Mapping[str, Any] | None,
    expected_plan_sha256: str,
    lifecycle_phase: str,
    allow_unrecorded_rollback: bool,
    prerequisite_evidence_sha256: str | None,
    actor: str,
) -> str:
    return _hash_payload(
        {
            "workspace_id": workspace_id,
            "operation": operation,
            "app_id": app_id,
            "target_version": target_version,
            "expected_manifest_digest": expected_manifest_digest,
            "configuration": configuration,
            "expected_plan_sha256": expected_plan_sha256,
            "lifecycle_phase": lifecycle_phase,
            "allow_unrecorded_rollback": allow_unrecorded_rollback,
            "prerequisite_evidence_sha256": prerequisite_evidence_sha256,
            "actor": actor,
        }
    )


def _legacy_request_sha256(
    *,
    workspace_id: str,
    operation: str,
    app_id: str,
    target_version: str | None,
    expected_manifest_digest: str,
    configuration: Mapping[str, Any] | None,
    expected_plan_sha256: str,
    actor: str,
) -> str:
    """Reproduce pre-073 receipt hashing for exact idempotent replays only."""

    return _hash_payload(
        {
            "workspace_id": workspace_id,
            "operation": operation,
            "app_id": app_id,
            "target_version": target_version,
            "expected_manifest_digest": expected_manifest_digest,
            "configuration": configuration,
            "expected_plan_sha256": expected_plan_sha256,
            "actor": actor,
        }
    )


def _mandatory_audit(
    db: DBSession,
    *,
    workspace_id: str,
    actor: str,
    plan: WorkspaceAppLifecyclePlan,
    operation_id: str,
    step_receipts: tuple[WorkspaceAppLifecycleStepReceipt, ...],
) -> None:
    db.add(
        AuditLog(
            id=str(uuid4()),
            workspace_id=workspace_id,
            timestamp=datetime.utcnow(),
            event_type=f"workspace_app.{plan.operation}.applied",
            actor=actor,
            severity="info",
            details={
                "operation_id": operation_id,
                "app_id": plan.app_id,
                "from_state": plan.from_state,
                "from_version": plan.from_version,
                "to_state": plan.to_state,
                "to_version": plan.to_version,
                "manifest_digest": plan.to_manifest_digest or plan.from_manifest_digest,
                "plan_sha256": plan.plan_sha256,
                "lifecycle_phase": plan.lifecycle_phase,
                "steps_sha256": plan.steps_sha256,
                "step_receipt_ids": [row.id for row in step_receipts],
                "step_count": len(step_receipts),
                "compensation": deepcopy(plan.compensation),
                "configuration_fields": list(plan.configuration_fields),
                "entitlements_mutated": False,
            },
        )
    )
    # Audit is part of the authority boundary; unlike best-effort application
    # audit helpers, a failed flush must abort the lifecycle mutation.
    db.flush()


def _rollback_and_raise(db: DBSession, exc: Exception) -> NoReturn:
    db.rollback()
    if isinstance(exc, WorkspaceAppLifecycleError):
        raise exc
    if isinstance(exc, IntegrityError):
        raise WorkspaceAppLifecycleConflict(
            "concurrent Workspace App lifecycle transition conflicted",
            code="concurrent_transition",
        ) from exc
    raise exc


def _idempotent_result(
    db: DBSession,
    receipt: WorkspaceAppOperation,
    *,
    app_id: str,
    commit: bool,
) -> WorkspaceAppLifecycleResult:
    if receipt.app_id != app_id:
        raise WorkspaceAppLifecycleConflict("idempotency receipt has an invalid app identity")
    installation = (
        db.query(WorkspaceAppInstallation)
        .filter(
            WorkspaceAppInstallation.id == receipt.installation_id,
            WorkspaceAppInstallation.workspace_id == receipt.workspace_id,
            WorkspaceAppInstallation.app_id == receipt.app_id,
        )
        .first()
    )
    if installation is None:
        raise WorkspaceAppLifecycleConflict("idempotency receipt points to a missing installation")
    step_receipts = tuple(
        db.query(WorkspaceAppLifecycleStepReceipt)
        .filter(
            WorkspaceAppLifecycleStepReceipt.workspace_id == receipt.workspace_id,
            WorkspaceAppLifecycleStepReceipt.operation_id == receipt.id,
        )
        .order_by(WorkspaceAppLifecycleStepReceipt.position.asc())
        .all()
    )
    observed_steps_sha256 = _hash_payload({"steps": [row.step_sha256 for row in step_receipts]})
    if observed_steps_sha256 != receipt.steps_sha256:
        raise WorkspaceAppLifecycleConflict(
            "idempotency receipt lifecycle steps are incomplete",
            code="lifecycle_receipt_drift",
        )
    result = WorkspaceAppLifecycleResult(
        operation=receipt,
        installation=installation,
        step_receipts=step_receipts,
        result_snapshot=deepcopy(receipt.after_state),
        idempotent_replay=True,
    )
    # Standalone API calls release the Workspace row lock here. Blueprint
    # imports keep the receipt in their wider transaction so every app and
    # every imported object succeeds or rolls back together.
    if commit:
        db.commit()
    else:
        db.flush()
    return result


def apply_workspace_app_lifecycle(
    db: DBSession,
    *,
    workspace_id: str,
    operation: str,
    app_id: str,
    target_version: str | None,
    expected_manifest_digest: str,
    expected_plan_sha256: str,
    actor: str,
    idempotency_key: str,
    configuration: Mapping[str, Any] | None = None,
    lifecycle_phase: str = "normal",
    allow_unrecorded_rollback: bool = False,
    prerequisite_evidence: Mapping[str, Any] | None = None,
    commit: bool = True,
) -> WorkspaceAppLifecycleResult:
    """Apply exactly the supplied plan and write an immutable receipt.

    ``commit=False`` lets a higher-level authority, such as Blueprint v2,
    compose several app transitions into one transaction. Any failure still
    rolls that whole session transaction back.
    """

    workspace_key = _required_text(workspace_id, "workspace_id", maximum=36)
    operation_key = _required_text(operation, "operation", maximum=24).lower()
    app_key = _required_text(app_id, "app_id", maximum=120)
    target_key = str(target_version).strip() if target_version is not None else None
    digest = _sha256(expected_manifest_digest, "expected_manifest_digest")
    plan_digest = _sha256(expected_plan_sha256, "expected_plan_sha256")
    actor_key = _required_text(actor, "actor", maximum=255)
    idempotency = _required_text(idempotency_key, "idempotency_key", maximum=160)
    phase_key = _lifecycle_phase(lifecycle_phase)
    normalized_config = _normalize_configuration(configuration)
    normalized_prerequisites = _normalize_prerequisite_evidence(prerequisite_evidence)
    prerequisite_digest = (
        _hash_payload({"evidence": normalized_prerequisites})
        if normalized_prerequisites is not None
        else None
    )
    request_hash = _request_sha256(
        workspace_id=workspace_key,
        operation=operation_key,
        app_id=app_key,
        target_version=target_key,
        expected_manifest_digest=digest,
        configuration=normalized_config,
        expected_plan_sha256=plan_digest,
        lifecycle_phase=phase_key,
        allow_unrecorded_rollback=allow_unrecorded_rollback,
        prerequisite_evidence_sha256=prerequisite_digest,
        actor=actor_key,
    )

    try:
        # This row is the serialization mutex even before the first
        # installation row exists, so concurrent installs cannot both plan an
        # "absent" starting state.
        locked_workspace = _workspace(db, workspace_key, lock=True)
        existing = (
            db.query(WorkspaceAppOperation)
            .filter(
                WorkspaceAppOperation.workspace_id == workspace_key,
                WorkspaceAppOperation.idempotency_key == idempotency,
            )
            .first()
        )
        if existing is not None:
            request_matches = existing.request_sha256 == request_hash
            if (
                not request_matches
                and existing.lifecycle_phase == "legacy_unorchestrated"
                and phase_key == "normal"
                and normalized_prerequisites is None
            ):
                request_matches = existing.request_sha256 == _legacy_request_sha256(
                    workspace_id=workspace_key,
                    operation=operation_key,
                    app_id=app_key,
                    target_version=target_key,
                    expected_manifest_digest=digest,
                    configuration=normalized_config,
                    expected_plan_sha256=plan_digest,
                    actor=actor_key,
                )
            if not request_matches or existing.operation != operation_key:
                raise WorkspaceAppLifecycleConflict(
                    "idempotency key was already used for a different request",
                    code="idempotency_conflict",
                )
            return _idempotent_result(db, existing, app_id=app_key, commit=commit)

        plan, installation = _build_plan(
            db,
            workspace_id=workspace_key,
            operation=operation_key,
            app_id=app_key,
            target_version=target_key,
            expected_manifest_digest=digest,
            configuration=normalized_config,
            lifecycle_phase=phase_key,
            allow_unrecorded_rollback=allow_unrecorded_rollback,
            lock=True,
        )
        if plan.plan_sha256 != plan_digest:
            raise WorkspaceAppLifecycleConflict(
                "Workspace App lifecycle plan changed before apply",
                code="stale_plan",
            )
        step_results = _execute_lifecycle_steps(
            db,
            workspace=locked_workspace,
            plan=plan,
            prerequisite_evidence=normalized_prerequisites,
        )

        now = datetime.utcnow()
        if installation is None:
            if operation_key != "install":
                raise WorkspaceAppLifecycleConflict("Workspace App installation disappeared")
            installation = WorkspaceAppInstallation(
                id=str(uuid4()),
                workspace_id=workspace_key,
                app_id=app_key,
                state="uninstalled",
                configuration={},
                revision=0,
                updated_at=now,
                updated_by=actor_key,
            )
            db.add(installation)
            db.flush()

        before_state = _snapshot(installation)
        if operation_key == "uninstall":
            installation.state = "uninstalled"
            installation.version = None
            installation.manifest_digest = None
            installation.configuration = {}
            installation.installed_at = None
        else:
            installation.state = "installed"
            installation.version = plan.to_version
            installation.manifest_digest = plan.to_manifest_digest
            installation.configuration = deepcopy(plan.configuration)
            if operation_key == "install":
                installation.installed_at = now
        installation.revision = int(installation.revision or 0) + 1
        installation.updated_at = now
        installation.updated_by = actor_key
        db.flush()
        after_state = _snapshot(installation)

        receipt = WorkspaceAppOperation(
            id=str(uuid4()),
            workspace_id=workspace_key,
            installation_id=installation.id,
            app_id=app_key,
            idempotency_key=idempotency,
            request_sha256=request_hash,
            operation=operation_key,
            from_version=plan.from_version,
            to_version=plan.to_version,
            manifest_digest=plan.to_manifest_digest or digest,
            plan_sha256=plan.plan_sha256,
            lifecycle_phase=plan.lifecycle_phase,
            steps_sha256=plan.steps_sha256,
            compensation=deepcopy(plan.compensation),
            before_state=before_state,
            after_state=after_state,
            actor=actor_key,
            created_at=now,
        )
        db.add(receipt)
        db.flush()
        step_receipts = tuple(
            WorkspaceAppLifecycleStepReceipt(
                id=str(uuid4()),
                workspace_id=workspace_key,
                operation_id=receipt.id,
                installation_id=installation.id,
                app_id=app_key,
                position=step.position,
                manifest_role=step.manifest_role,
                manifest_digest=step.manifest_digest,
                step_id=step.step_id,
                step_sha256=step.step_sha256,
                phase=step.phase,
                executor=step.executor,
                outcome=str(result["outcome"]),
                reversibility=step.reversibility,
                compensation=deepcopy(dict(result.get("compensation") or {})),
                evidence_sha256=result.get("evidence_sha256"),
                created_at=now,
            )
            for step, result in zip(plan.steps, step_results, strict=True)
        )
        db.add_all(step_receipts)
        db.flush()
        _mandatory_audit(
            db,
            workspace_id=workspace_key,
            actor=actor_key,
            plan=plan,
            operation_id=receipt.id,
            step_receipts=step_receipts,
        )
        if commit:
            db.commit()
            db.refresh(installation)
            db.refresh(receipt)
        else:
            db.flush()
        return WorkspaceAppLifecycleResult(
            operation=receipt,
            installation=installation,
            step_receipts=step_receipts,
            result_snapshot=deepcopy(receipt.after_state),
            idempotent_replay=False,
        )
    except Exception as exc:  # noqa: BLE001 - transaction boundary
        _rollback_and_raise(db, exc)


def compensate_workspace_app_lifecycle(
    db: DBSession,
    *,
    workspace_id: str,
    source_operation_id: str,
    expected_source_plan_sha256: str,
    actor: str,
    idempotency_key: str,
    commit: bool = True,
) -> WorkspaceAppLifecycleCompensationResult:
    """Apply the server-derived inverse of one exact committed operation.

    The caller cannot choose the inverse version, manifest, configuration, or
    operation.  They acknowledge the immutable source receipt and its plan
    digest; this function locks the tenant, rejects state drift, applies the
    derived inverse through the regular lifecycle authority, and binds both
    receipts in the same transaction.
    """

    workspace_key = _required_text(workspace_id, "workspace_id", maximum=36)
    source_key = _required_text(source_operation_id, "source_operation_id", maximum=36)
    source_plan = _sha256(
        expected_source_plan_sha256,
        "expected_source_plan_sha256",
    )
    actor_key = _required_text(actor, "actor", maximum=255)
    idempotency = _required_text(idempotency_key, "idempotency_key", maximum=160)

    try:
        _workspace(db, workspace_key, lock=True)
        source = (
            db.query(WorkspaceAppOperation)
            .filter(
                WorkspaceAppOperation.workspace_id == workspace_key,
                WorkspaceAppOperation.id == source_key,
            )
            .one_or_none()
        )
        if source is None:
            raise WorkspaceAppLifecycleNotFound(
                "source Workspace App operation was not found",
                code="compensation_source_not_found",
            )
        if source.plan_sha256 != source_plan:
            raise WorkspaceAppLifecycleConflict(
                "source lifecycle plan digest changed",
                code="compensation_source_drift",
            )
        source_compensation = (
            source.compensation if isinstance(source.compensation, Mapping) else {}
        )
        if source_compensation.get("compensates_operation_id") is not None:
            raise WorkspaceAppLifecycleConflict(
                "a compensation receipt cannot itself be compensated",
                code="compensation_chain_forbidden",
            )

        existing = (
            db.query(WorkspaceAppOperation)
            .filter(
                WorkspaceAppOperation.workspace_id == workspace_key,
                WorkspaceAppOperation.idempotency_key == idempotency,
            )
            .one_or_none()
        )
        if existing is not None:
            existing_contract = (
                existing.compensation if isinstance(existing.compensation, Mapping) else {}
            )
            if (
                existing.actor != actor_key
                or existing.app_id != source.app_id
                or existing_contract.get("compensates_operation_id") != source.id
                or existing_contract.get("compensates_plan_sha256") != source.plan_sha256
            ):
                raise WorkspaceAppLifecycleConflict(
                    "idempotency key was already used for another lifecycle request",
                    code="idempotency_conflict",
                )
            inverse = _idempotent_result(
                db,
                existing,
                app_id=source.app_id,
                commit=commit,
            )
            return WorkspaceAppLifecycleCompensationResult(
                source_operation=source,
                inverse=inverse,
            )

        installation = _installation(
            db,
            workspace_id=workspace_key,
            app_id=source.app_id,
            lock=True,
        )
        if installation is None or _snapshot(installation) != source.after_state:
            raise WorkspaceAppLifecycleConflict(
                "installation no longer matches the source operation result",
                code="compensation_state_drift",
            )

        (
            inverse_operation,
            target_version,
            manifest_digest,
            configuration,
            allow_unrecorded_rollback,
        ) = _compensation_request(source)
        inverse_plan = plan_workspace_app_lifecycle(
            db,
            workspace_id=workspace_key,
            operation=inverse_operation,
            app_id=source.app_id,
            target_version=target_version,
            expected_manifest_digest=manifest_digest,
            configuration=configuration,
            allow_unrecorded_rollback=allow_unrecorded_rollback,
        )
        inverse = apply_workspace_app_lifecycle(
            db,
            workspace_id=workspace_key,
            operation=inverse_operation,
            app_id=source.app_id,
            target_version=target_version,
            expected_manifest_digest=manifest_digest,
            expected_plan_sha256=inverse_plan.plan_sha256,
            actor=actor_key,
            idempotency_key=idempotency,
            configuration=configuration,
            allow_unrecorded_rollback=allow_unrecorded_rollback,
            commit=False,
        )
        inverse.operation.compensation = {
            **deepcopy(inverse.operation.compensation or {}),
            "compensates_operation_id": source.id,
            "compensates_plan_sha256": source.plan_sha256,
        }
        db.add(
            AuditLog(
                id=str(uuid4()),
                workspace_id=workspace_key,
                timestamp=datetime.utcnow(),
                event_type="workspace_app.compensation.applied",
                actor=actor_key,
                severity="warning",
                details={
                    "source_operation_id": source.id,
                    "source_plan_sha256": source.plan_sha256,
                    "inverse_operation_id": inverse.operation.id,
                    "inverse_plan_sha256": inverse.operation.plan_sha256,
                    "app_id": source.app_id,
                    "source_operation": source.operation,
                    "inverse_operation": inverse.operation.operation,
                    "configuration_fields": sorted((configuration or {}).keys()),
                },
            )
        )
        db.flush()
        if commit:
            db.commit()
            db.refresh(inverse.installation)
            db.refresh(inverse.operation)
        return WorkspaceAppLifecycleCompensationResult(
            source_operation=source,
            inverse=inverse,
        )
    except Exception as exc:  # noqa: BLE001 - transaction boundary
        _rollback_and_raise(db, exc)
