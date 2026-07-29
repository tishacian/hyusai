#!/usr/bin/env python3
"""Collect Lot-9 Playwright observations into rollout-grade evidence.

The browser never chooses a raw Workspace id: it discovers the unique
structurally marked canary and emits only hashes.  This server-side collector
binds that observation to the authoritative database, exact deployment SHA,
canonical installation/configuration set and (for post-activation evidence)
the live probation lease.  Local collections are useful diagnostics but are
deliberately non-promotable.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.models.workspace_app import (  # noqa: E402
    WorkspaceAppInstallation,
    WorkspaceAppOperation,
)
from app.services.actions.registry import (  # noqa: E402
    all_action_manifests,
    effective_action_manifests,
)
from app.services.workspace_app_runtime import (  # noqa: E402
    WorkspaceAppRuntime,
    WorkspaceAppRuntimeError,
    inspect_authoritative_workspace_app_runtime,
    resolve_workspace_app_runtime,
    workspace_app_installation_subject,
    workspace_app_installations_sha256,
)
from scripts import rollout_workspace_app_platform as rollout  # noqa: E402

OBSERVATION_SCHEMA_VERSION = 1
PREFLIGHT_OBSERVATION_KIND = "lot9_workspace_app_preflight_observation"
POSTACTIVATION_OBSERVATION_KIND = "lot9_workspace_app_postactivation_observation"
PREFLIGHT_CANARY_TEST_NAME = (
    "discovers the dedicated target and leaves a proven nonempty installation set"
)
POSTACTIVATION_CANARY_TEST_NAME = (
    "proves the staged runtime on the same workspace and installation set"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _canonical_sha256(value: Any) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _id_sha256(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _runtime_identity_subject(
    workspace: Workspace,
    runtime: WorkspaceAppRuntime,
) -> dict[str, Any]:
    """Return the closed, secret-free runtime identity observed by Playwright."""

    installations = sorted(
        (
            {
                "app_id": item.manifest.app_id,
                "version": item.manifest.version,
                "manifest_digest": item.manifest.digest,
                "category": item.payload["category"],
                "routes": sorted(item.payload["routes"]),
                "primary_surface_id": item.payload["experience"]["primary_surface_id"],
                "default_route": item.payload["experience"]["default_route"],
                "branding_namespace": item.payload["branding"]["namespace"],
                "action_packs": sorted(item.payload["action_packs"]),
                "entitlement_keys": sorted(item.payload["entitlement_keys"]),
            }
            for item in runtime.installations
        ),
        key=lambda item: item["app_id"],
    )
    mission = _record(runtime.mission_room)
    return {
        "workspace_id": workspace.id,
        "mode": runtime.mode,
        "enabled": runtime.enabled,
        "rollout_phase": runtime.rollout_phase,
        "rollout_ref": runtime.rollout_ref,
        "installations": installations,
        "experience": {
            "shell": runtime.shell,
            "routes": sorted(runtime.routes),
            "primary_surface_ids": sorted(runtime.primary_surface_ids),
            "default_routes": dict(sorted(runtime.default_routes.items())),
            "branding_namespaces": sorted(runtime.branding_namespaces),
            "action_packs": sorted(runtime.action_packs),
            "mission_room": (
                {
                    key: mission.get(key)
                    for key in (
                        "app_id",
                        "version",
                        "manifest_digest",
                        "profile",
                        "brand_style",
                        "default_route",
                        "primary_surface_id",
                    )
                }
                if mission
                else None
            ),
        },
    }


def _runtime_identity_sha256(workspace: Workspace, runtime: WorkspaceAppRuntime) -> str:
    return _canonical_sha256(_runtime_identity_subject(workspace, runtime))


def _route_path(value: Any) -> str:
    path = urlsplit(str(value or "")).path or "/"
    return path.rstrip("/") or "/"


def _runtime_route_surface_hashes(runtime: WorkspaceAppRuntime) -> set[tuple[str, str]]:
    return {
        (
            _id_sha256(_route_path(item.payload["experience"]["default_route"])),
            _id_sha256(item.payload["experience"]["primary_surface_id"]),
        )
        for item in runtime.installations
    }


def _workspace_app_ledger_sha256(db: DBSession, workspace: Workspace) -> str:
    rows = (
        db.query(WorkspaceAppInstallation)
        .filter(WorkspaceAppInstallation.workspace_id == workspace.id)
        .order_by(WorkspaceAppInstallation.app_id.asc())
        .all()
    )
    return _canonical_sha256(
        [
            {
                "app_id": row.app_id,
                "state": row.state,
                "version": row.version,
                "manifest_digest": row.manifest_digest,
                "configuration": _record(row.configuration),
            }
            for row in rows
        ]
    )


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, field: str) -> None:
    actual = set(value)
    if actual != expected:
        raise rollout.WorkspaceAppRolloutError(
            f"{field} fields differ from the contract; "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )


def _sha256(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip().lower()
    if _SHA256_RE.fullmatch(normalized) is None:
        raise rollout.WorkspaceAppRolloutError(f"{field} must be a lowercase SHA-256")
    return normalized


def _phase_contract(
    phase: str,
) -> tuple[str, str, tuple[str, ...], str, str]:
    if phase == "preflight":
        return (
            PREFLIGHT_OBSERVATION_KIND,
            PREFLIGHT_CANARY_TEST_NAME,
            rollout.PREFLIGHT_CHECKS,
            rollout.PREFLIGHT_EVIDENCE_KIND,
            rollout.PREFLIGHT_EVIDENCE_SUITE,
        )
    if phase == "postactivation":
        return (
            POSTACTIVATION_OBSERVATION_KIND,
            POSTACTIVATION_CANARY_TEST_NAME,
            rollout.POSTACTIVATION_CHECKS,
            rollout.POSTACTIVATION_EVIDENCE_KIND,
            rollout.POSTACTIVATION_EVIDENCE_SUITE,
        )
    raise rollout.WorkspaceAppRolloutError("collector phase must be preflight or postactivation")


def _validate_postactivation_entry_policy(
    payload: Mapping[str, Any],
    *,
    runtime: WorkspaceAppRuntime,
) -> str:
    diagnostics = _record(payload.get("diagnostics"))
    entry_policy, declared_count = rollout.workspace_app_canary_entry_policy(runtime)
    observed_count = diagnostics.get("declared_entitlement_count")
    if (
        diagnostics.get("runtime_shell") != runtime.shell
        or diagnostics.get("entry_policy") != entry_policy
        or diagnostics.get("shell_entry_boundary") is not True
        or isinstance(observed_count, bool)
        or not isinstance(observed_count, int)
        or observed_count != declared_count
    ):
        raise rollout.WorkspaceAppRolloutError(
            "post-activation entry proof differs from the installed runtime shell"
        )
    entitlement_gate = diagnostics.get("entitlement_gate")
    if entry_policy == "business_entitlement":
        if entitlement_gate is not True:
            raise rollout.WorkspaceAppRolloutError(
                "business entry proof must exercise a declared entitlement"
            )
    elif entitlement_gate != "not_applicable":
        raise rollout.WorkspaceAppRolloutError(
            "non-business entry proof must not fabricate an entitlement gate"
        )
    return entry_policy


def _semantic_list(value: Any, *, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise rollout.WorkspaceAppRolloutError(f"{field} must be a nonempty array")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise rollout.WorkspaceAppRolloutError(f"{field}[{index}] must be an object")
        rows.append(dict(item))
    return rows


def _validate_preflight_semantic_proof(
    db: DBSession,
    *,
    payload: Mapping[str, Any],
    workspace: Workspace,
    runtime: WorkspaceAppRuntime,
) -> None:
    diagnostics = _record(payload.get("diagnostics"))
    proofs = _semantic_list(
        diagnostics.get("lifecycle_operation_proofs"),
        field="diagnostics.lifecycle_operation_proofs",
    )
    operations = (
        db.query(WorkspaceAppOperation)
        .filter(WorkspaceAppOperation.workspace_id == workspace.id)
        .all()
    )
    operations_by_ref = {_id_sha256(row.id): row for row in operations}
    observed_refs: set[str] = set()
    observed_operations: set[str] = set()
    observed_manifests: set[str] = set()
    observed_apps: set[str] = set()
    generated_at = payload["generated_at"]
    for index, proof in enumerate(proofs):
        _exact_keys(
            proof,
            {"operation", "operation_id_sha256", "plan_sha256", "manifest_digest"},
            field=f"diagnostics.lifecycle_operation_proofs[{index}]",
        )
        operation_ref = _sha256(
            proof.get("operation_id_sha256"),
            field=f"diagnostics.lifecycle_operation_proofs[{index}].operation_id_sha256",
        )
        row = operations_by_ref.get(operation_ref)
        if (
            row is None
            or proof.get("operation") != row.operation
            or proof.get("plan_sha256") != row.plan_sha256
            or proof.get("manifest_digest") != row.manifest_digest
        ):
            raise rollout.WorkspaceAppRolloutError(
                "lifecycle operation proof does not resolve to its immutable receipt"
            )
        created_at = (
            row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at
        )
        if created_at > generated_at or generated_at - created_at > rollout.EVIDENCE_MAX_AGE:
            raise rollout.WorkspaceAppRolloutError(
                "lifecycle operation proof is outside the observation window"
            )
        if operation_ref in observed_refs:
            raise rollout.WorkspaceAppRolloutError(
                "lifecycle operation proofs must reference unique receipts"
            )
        observed_refs.add(operation_ref)
        observed_operations.add(row.operation)
        observed_manifests.add(row.manifest_digest)
        observed_apps.add(row.app_id)
    if observed_operations != {"install", "upgrade", "rollback", "uninstall"}:
        raise rollout.WorkspaceAppRolloutError(
            "preflight proof must cover install, upgrade, rollback and uninstall"
        )

    replay = _record(diagnostics.get("idempotent_replay_proof"))
    _exact_keys(
        replay,
        {"operation_id_sha256", "replayed_operation_id_sha256", "idempotent_replay"},
        field="diagnostics.idempotent_replay_proof",
    )
    replay_ref = _sha256(
        replay.get("operation_id_sha256"),
        field="diagnostics.idempotent_replay_proof.operation_id_sha256",
    )
    replayed_ref = _sha256(
        replay.get("replayed_operation_id_sha256"),
        field="diagnostics.idempotent_replay_proof.replayed_operation_id_sha256",
    )
    if (
        replay.get("idempotent_replay") is not True
        or replay_ref != replayed_ref
        or replay_ref not in observed_refs
    ):
        raise rollout.WorkspaceAppRolloutError(
            "idempotent replay proof must bind the exact same persisted operation"
        )

    entry_policy, declared_count = rollout.workspace_app_canary_entry_policy(runtime)
    exercised = diagnostics.get("exercised_manifest_digests")
    if not isinstance(exercised, list) or not exercised:
        raise rollout.WorkspaceAppRolloutError(
            "preflight proof requires exercised manifest digests"
        )
    exercised_set = {
        _sha256(value, field="diagnostics.exercised_manifest_digests") for value in exercised
    }
    installed_manifests = {item.manifest.digest for item in runtime.installations}
    installed_apps = {item.manifest.app_id for item in runtime.installations}
    final_count = diagnostics.get("final_installed_count")
    entitlement_count = diagnostics.get("restored_declared_entitlement_count")
    if (
        diagnostics.get("exact_initial_ledger_restored") is not True
        or diagnostics.get("exact_initial_reinstalled") is not True
        or diagnostics.get("restored_runtime_shell") != runtime.shell
        or diagnostics.get("restored_entry_policy") != entry_policy
        or isinstance(entitlement_count, bool)
        or entitlement_count != declared_count
        or diagnostics.get("ledger_sha256") != _workspace_app_ledger_sha256(db, workspace)
        or diagnostics.get("restored_manifest_digest") not in installed_manifests
        or isinstance(final_count, bool)
        or final_count != len(runtime.installations)
        or not observed_manifests.issubset(exercised_set)
        or len(observed_apps) != 1
        or not observed_apps.issubset(installed_apps)
    ):
        raise rollout.WorkspaceAppRolloutError(
            "preflight semantic proof differs from the authoritative lifecycle ledger"
        )


def _audit_row(
    db: DBSession,
    *,
    workspace: Workspace,
    audit_id: Any,
    generated_at: datetime,
) -> AuditLog:
    normalized = str(audit_id or "").strip()
    if not normalized:
        raise rollout.WorkspaceAppRolloutError("action proof audit_id is required")
    row = (
        db.query(AuditLog)
        .filter(AuditLog.id == normalized, AuditLog.workspace_id == workspace.id)
        .one_or_none()
    )
    if row is None:
        raise rollout.WorkspaceAppRolloutError(
            "action proof does not resolve to an audit in the canary Workspace"
        )
    timestamp = row.timestamp.replace(tzinfo=UTC) if row.timestamp.tzinfo is None else row.timestamp
    if timestamp > generated_at or generated_at - timestamp > rollout.EVIDENCE_MAX_AGE:
        raise rollout.WorkspaceAppRolloutError(
            "action proof audit is outside the observation window"
        )
    return row


def _validate_action_pack_proof(
    db: DBSession,
    *,
    payload: Mapping[str, Any],
    workspace: Workspace,
    runtime: WorkspaceAppRuntime,
) -> dict[str, Any]:
    diagnostics = _record(payload.get("diagnostics"))
    executions = _semantic_list(
        diagnostics.get("action_pack_executions"),
        field="diagnostics.action_pack_executions",
    )
    generated_at = payload["generated_at"]
    effective = {
        manifest.action_id: manifest
        for manifest in effective_action_manifests(workspace, surface="chat")
    }
    declared_packs = set(runtime.action_packs)
    observed_packs: set[str] = set()
    observed_audits: set[str] = set()
    for index, proof in enumerate(executions):
        _exact_keys(
            proof,
            {
                "pack",
                "action_id",
                "audit_id",
                "http_status",
                "matched",
                "reason",
                "response_action_id",
                "result_action",
                "applied",
                "requires_confirmation",
            },
            field=f"diagnostics.action_pack_executions[{index}]",
        )
        pack = str(proof.get("pack") or "")
        action_id = str(proof.get("action_id") or "")
        manifest = effective.get(action_id)
        if (
            manifest is None
            or manifest.pack != pack
            or pack not in declared_packs
            or manifest.requires_confirmation
            or not manifest.direct_safe
            or manifest.handler.kind == "legacy_adapter"
            or proof.get("http_status") != 200
            or proof.get("matched") is not True
            or proof.get("reason") != "proposed"
            or proof.get("response_action_id") != action_id
            or proof.get("result_action") != action_id
            or proof.get("applied") is not False
            or proof.get("requires_confirmation") is not False
        ):
            raise rollout.WorkspaceAppRolloutError(
                "action-pack proof is not a successful direct-safe chat invocation"
            )
        audit_id = str(proof.get("audit_id") or "")
        if pack in observed_packs or audit_id in observed_audits:
            raise rollout.WorkspaceAppRolloutError(
                "action-pack proof must contain one unique invocation per pack"
            )
        audit = _audit_row(
            db,
            workspace=workspace,
            audit_id=audit_id,
            generated_at=generated_at,
        )
        details = _record(audit.details)
        if (
            audit.event_type != manifest.audit_event
            or details.get("action_id") != action_id
            or details.get("surface") != "chat"
        ):
            raise rollout.WorkspaceAppRolloutError(
                "action-pack proof audit differs from the invoked manifest"
            )
        observed_packs.add(pack)
        observed_audits.add(audit_id)
    if observed_packs != declared_packs:
        raise rollout.WorkspaceAppRolloutError(
            "action-pack proof must invoke exactly one action from every installed pack"
        )

    denied = _record(diagnostics.get("foreign_action_denial"))
    _exact_keys(
        denied,
        {"pack", "action_id", "audit_id", "http_status", "matched", "reason"},
        field="diagnostics.foreign_action_denial",
    )
    foreign_pack = str(denied.get("pack") or "")
    foreign_action_id = str(denied.get("action_id") or "")
    catalog = {manifest.action_id: manifest for manifest in all_action_manifests()}
    foreign_manifest = catalog.get(foreign_action_id)
    if (
        foreign_manifest is None
        or foreign_manifest.pack != foreign_pack
        or foreign_pack in declared_packs
        or denied.get("http_status") != 200
        or denied.get("matched") is not False
        or denied.get("reason") != "not_visible"
    ):
        raise rollout.WorkspaceAppRolloutError(
            "foreign action proof is not an observed installed-pack boundary denial"
        )
    denied_audit = _audit_row(
        db,
        workspace=workspace,
        audit_id=denied.get("audit_id"),
        generated_at=generated_at,
    )
    denied_details = _record(denied_audit.details)
    if (
        denied_audit.event_type != "action.denied"
        or denied_details.get("action_id") != foreign_action_id
        or denied_details.get("reason") != "not_visible"
        or denied_details.get("surface") != "chat"
    ):
        raise rollout.WorkspaceAppRolloutError(
            "foreign action denial does not resolve to the expected audit"
        )
    if denied_audit.id in observed_audits:
        raise rollout.WorkspaceAppRolloutError("action proof audit ids must be unique")
    return {
        "invoked_pack_count": len(observed_packs),
        "foreign_pack": foreign_pack,
    }


def _workspace_by_redacted_id(db: DBSession, digest: Any) -> Workspace:
    normalized = _sha256(digest, field="workspace switch target")
    matches = [
        candidate
        for candidate in db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
        if _id_sha256(candidate.id) == normalized
    ]
    if len(matches) != 1:
        raise rollout.WorkspaceAppRolloutError(
            "workspace switch target does not resolve to one active Workspace"
        )
    return matches[0]


def _validate_workspace_switch_proof(
    db: DBSession,
    *,
    payload: Mapping[str, Any],
    workspace: Workspace,
    runtime: WorkspaceAppRuntime,
    foreign_pack: str,
) -> dict[str, Any]:
    proof = _record(_record(payload.get("diagnostics")).get("workspace_switch"))
    _exact_keys(
        proof,
        {
            "from_workspace_sha256",
            "to_workspace_sha256",
            "from_runtime_identity_sha256",
            "to_runtime_identity_sha256",
            "from_route_sha256",
            "to_route_sha256",
            "from_primary_surface_sha256",
            "to_primary_surface_sha256",
            "from_header_sha256",
            "to_header_sha256",
            "observed_request_paths_sha256",
            "cache_revalidation_path_sha256",
            "observed_request_count",
            "new_header_request_count",
            "old_header_after_new_count",
            "cache_revalidation",
        },
        field="diagnostics.workspace_switch",
    )
    if proof.get("from_workspace_sha256") != _id_sha256(workspace.id):
        raise rollout.WorkspaceAppRolloutError(
            "workspace switch proof starts from a different Workspace"
        )
    alternate = _workspace_by_redacted_id(db, proof.get("to_workspace_sha256"))
    if alternate.id == workspace.id:
        raise rollout.WorkspaceAppRolloutError(
            "workspace switch proof must change Workspace identity"
        )
    try:
        alternate_runtime = inspect_authoritative_workspace_app_runtime(alternate, db=db)
    except WorkspaceAppRuntimeError as exc:
        raise rollout.WorkspaceAppRolloutError(
            f"workspace switch target has no valid app runtime: {exc.code}"
        ) from exc
    if not alternate_runtime.installations:
        raise rollout.WorkspaceAppRolloutError(
            "workspace switch target must be a Workspace App runtime"
        )
    if foreign_pack not in set(alternate_runtime.action_packs):
        raise rollout.WorkspaceAppRolloutError(
            "foreign action denial is not sourced from the switched app Workspace"
        )
    sha_fields = {
        "from_runtime_identity_sha256": _runtime_identity_sha256(workspace, runtime),
        "to_runtime_identity_sha256": _runtime_identity_sha256(alternate, alternate_runtime),
        "from_header_sha256": _id_sha256(workspace.slug),
        "to_header_sha256": _id_sha256(alternate.slug),
    }
    for field, expected in sha_fields.items():
        if proof.get(field) != expected:
            raise rollout.WorkspaceAppRolloutError(
                f"workspace switch proof {field} differs from the authoritative runtime"
            )
    from_pair = (proof.get("from_route_sha256"), proof.get("from_primary_surface_sha256"))
    to_pair = (proof.get("to_route_sha256"), proof.get("to_primary_surface_sha256"))
    if (
        from_pair not in _runtime_route_surface_hashes(runtime)
        or to_pair not in _runtime_route_surface_hashes(alternate_runtime)
        or from_pair == to_pair
    ):
        raise rollout.WorkspaceAppRolloutError(
            "workspace switch proof does not bind two distinct app route/object identities"
        )
    observed_count = proof.get("observed_request_count")
    new_header_count = proof.get("new_header_request_count")
    old_header_count = proof.get("old_header_after_new_count")
    if (
        isinstance(observed_count, bool)
        or not isinstance(observed_count, int)
        or observed_count < 1
        or isinstance(new_header_count, bool)
        or not isinstance(new_header_count, int)
        or new_header_count < 1
        or isinstance(old_header_count, bool)
        or not isinstance(old_header_count, int)
        or old_header_count != 0
        or proof.get("cache_revalidation") != "network_no_store"
    ):
        raise rollout.WorkspaceAppRolloutError(
            "workspace switch proof lacks a clean post-commit request boundary"
        )
    _sha256(
        proof.get("observed_request_paths_sha256"),
        field="diagnostics.workspace_switch.observed_request_paths_sha256",
    )
    if proof.get("cache_revalidation_path_sha256") != _id_sha256(
        f"/api/v1/auth/workspaces/{alternate.slug}"
    ):
        raise rollout.WorkspaceAppRolloutError(
            "workspace switch proof did not revalidate the alternate runtime bootstrap"
        )
    if proof["from_runtime_identity_sha256"] == proof["to_runtime_identity_sha256"]:
        raise rollout.WorkspaceAppRolloutError(
            "workspace switch proof retained the previous runtime identity"
        )
    return {
        "workspace_sha256": _id_sha256(alternate.id),
        "runtime_identity_sha256": _runtime_identity_sha256(alternate, alternate_runtime),
    }


def _validate_observation(
    observation: Mapping[str, Any],
    *,
    phase: str,
    revision: str,
) -> dict[str, Any]:
    observation_kind, _test_name, checks, _evidence_kind, _suite = _phase_contract(phase)
    payload = _record(observation)
    _exact_keys(
        payload,
        {
            "schema_version",
            "kind",
            "tested_revision",
            "generated_at",
            "runner",
            "target",
            "checks",
            "diagnostics",
        },
        field="observation",
    )
    if payload.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise rollout.WorkspaceAppRolloutError("observation schema_version must be 1")
    if payload.get("kind") != observation_kind:
        raise rollout.WorkspaceAppRolloutError("observation kind differs from collector phase")
    if payload.get("tested_revision") != revision:
        raise rollout.WorkspaceAppRolloutError(
            "observation revision differs from the deployed runtime revision"
        )
    generated_at = rollout._parse_utc(payload.get("generated_at"), field="generated_at")
    now = datetime.now(UTC)
    if generated_at > now + rollout.EVIDENCE_FUTURE_TOLERANCE:
        raise rollout.WorkspaceAppRolloutError("observation is dated in the future")
    if now - generated_at > rollout.EVIDENCE_MAX_AGE:
        raise rollout.WorkspaceAppRolloutError("observation is older than 24 hours")
    runner = _record(payload.get("runner"))
    _exact_keys(runner, {"protected_ci", "pipeline_id", "job_id"}, field="runner")
    target = _record(payload.get("target"))
    expected_target = {"workspace_sha256", "installations_sha256"}
    if phase == "postactivation":
        expected_target.add("probation_ref")
    _exact_keys(target, expected_target, field="target")
    target["workspace_sha256"] = _sha256(
        target.get("workspace_sha256"), field="target.workspace_sha256"
    )
    target["installations_sha256"] = _sha256(
        target.get("installations_sha256"), field="target.installations_sha256"
    )
    if phase == "postactivation":
        probation_ref = str(target.get("probation_ref") or "").strip().lower()
        if (
            not probation_ref.startswith("sha256:")
            or _SHA256_RE.fullmatch(probation_ref.removeprefix("sha256:")) is None
        ):
            raise rollout.WorkspaceAppRolloutError("target.probation_ref must be content-addressed")
        target["probation_ref"] = probation_ref
    observed_checks = _record(payload.get("checks"))
    _exact_keys(observed_checks, set(checks), field="checks")
    if any(observed_checks.get(name) is not True for name in checks):
        raise rollout.WorkspaceAppRolloutError("every phase check must pass")
    if not isinstance(payload.get("diagnostics"), Mapping):
        raise rollout.WorkspaceAppRolloutError("diagnostics must be an object")
    diagnostics = _record(payload.get("diagnostics"))
    return {
        **payload,
        "runner": runner,
        "target": target,
        "checks": observed_checks,
        "diagnostics": diagnostics,
        "generated_at": generated_at,
    }


def _validate_playwright_junit(content: bytes, *, phase: str) -> None:
    _kind, test_name, _checks, _evidence_kind, _suite = _phase_contract(phase)
    if not content or len(content) > rollout.EVIDENCE_ARTIFACT_MAX_BYTES:
        raise rollout.WorkspaceAppRolloutError("Playwright JUnit has an invalid size")
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise rollout.WorkspaceAppRolloutError("Playwright JUnit XML declarations are forbidden")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise rollout.WorkspaceAppRolloutError("Playwright JUnit is not valid XML") from exc
    if root.tag not in {"testsuite", "testsuites"}:
        raise rollout.WorkspaceAppRolloutError("Playwright JUnit root must be testsuite(s)")
    for suite in root.iter("testsuite"):
        try:
            failed = sum(int(suite.get(name, "0")) for name in ("failures", "errors", "skipped"))
        except ValueError as exc:
            raise rollout.WorkspaceAppRolloutError(
                "Playwright JUnit counters must be integers"
            ) from exc
        if failed:
            raise rollout.WorkspaceAppRolloutError(
                "Playwright JUnit contains failed, errored or skipped tests"
            )
    matches = [case for case in root.iter("testcase") if test_name in str(case.get("name") or "")]
    if len(matches) != 1:
        raise rollout.WorkspaceAppRolloutError(
            "Playwright JUnit must contain exactly one phase-specific Lot 9 testcase"
        )
    if any(matches[0].find(name) is not None for name in ("failure", "error", "skipped")):
        raise rollout.WorkspaceAppRolloutError("the Lot 9 Playwright testcase did not pass")


def _canonical_runner_artifact(
    *,
    revision: str,
    workspace_id: str,
    installations_sha256: str,
    checks: Sequence[str],
    suite_name: str,
    observation_ref: str,
    probation_ref: str | None,
    source_junit_ref: str,
) -> dict[str, str]:
    root = ElementTree.Element(
        "testsuite",
        {
            "name": suite_name,
            "tests": str(len(checks)),
            "failures": "0",
            "errors": "0",
            "skipped": "0",
        },
    )
    properties = ElementTree.SubElement(root, "properties")
    values = [
        ("revision", revision),
        ("workspace_id", workspace_id),
        ("installations_sha256", installations_sha256),
        ("observation_ref", observation_ref),
        ("source_junit_ref", source_junit_ref),
    ]
    if probation_ref is not None:
        values.append(("probation_ref", probation_ref))
    for name, value in values:
        ElementTree.SubElement(properties, "property", {"name": name, "value": value})
    for name in checks:
        ElementTree.SubElement(root, "testcase", {"classname": "lot9", "name": name})
    content = ElementTree.tostring(root, encoding="utf-8", xml_declaration=False)
    digest = hashlib.sha256(content).hexdigest()
    return {
        "media_type": "application/junit+xml",
        "content_base64": base64.b64encode(content).decode("ascii"),
        "sha256": digest,
        "artifact_ref": f"sha256:{digest}",
    }


def _unique_canary(db: DBSession, workspace_id: str) -> Workspace:
    target = (
        db.query(Workspace)
        .filter(
            Workspace.id == workspace_id,
            Workspace.is_active.is_(True),
            Workspace.deleted_at.is_(None),
        )
        .one_or_none()
    )
    if target is None:
        raise rollout.WorkspaceAppRolloutError("collector target is missing or inactive")
    marked = [
        workspace
        for workspace in db.query(Workspace)
        .filter(
            Workspace.is_active.is_(True),
            Workspace.deleted_at.is_(None),
        )
        .all()
        if rollout._is_canary(workspace)
    ]
    if len(marked) != 1 or marked[0].id != target.id:
        raise rollout.WorkspaceAppRolloutError(
            "collector target must be the unique structurally marked Workspace"
        )
    return target


def collect_evidence(
    db: DBSession,
    *,
    phase: str,
    workspace_id: str,
    observation: Mapping[str, Any],
    playwright_junit: bytes,
    mode: str,
    validated_by: str,
    trusted_runner: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in {"local", "protected"}:
        raise rollout.WorkspaceAppRolloutError("collector mode must be local or protected")
    observation_kind, _test_name, checks, evidence_kind, suite_name = _phase_contract(phase)
    del observation_kind
    revision = rollout._runtime_revision()
    payload = _validate_observation(observation, phase=phase, revision=revision)
    _validate_playwright_junit(playwright_junit, phase=phase)
    source_junit_sha256 = hashlib.sha256(playwright_junit).hexdigest()
    source_junit = {
        "media_type": "application/junit+xml",
        "sha256": source_junit_sha256,
        "artifact_ref": f"sha256:{source_junit_sha256}",
    }
    workspace = _unique_canary(db, workspace_id)
    try:
        if phase == "preflight":
            if rollout._feature_enabled(workspace):
                raise rollout.WorkspaceAppRolloutError(
                    "preflight collection requires runtime authority to be disabled"
                )
            runtime = inspect_authoritative_workspace_app_runtime(workspace, db=db)
            probation_ref = None
        else:
            runtime = resolve_workspace_app_runtime(workspace, db=db)
            if runtime.rollout_phase != "probation" or runtime.rollout_ref is None:
                raise rollout.WorkspaceAppRolloutError(
                    "post-activation collection requires a live probation"
                )
            probation_ref = runtime.rollout_ref
    except WorkspaceAppRuntimeError as exc:
        raise rollout.WorkspaceAppRolloutError(
            f"Workspace App runtime cannot be collected: {exc.code}"
        ) from exc
    installations = workspace_app_installation_subject(runtime)
    installations_sha = workspace_app_installations_sha256(runtime)
    if not installations:
        raise rollout.WorkspaceAppRolloutError(
            "collector requires a nonempty installed application set"
        )
    if (
        payload["target"]["workspace_sha256"] != _id_sha256(workspace.id)
        or payload["target"]["installations_sha256"] != installations_sha
    ):
        raise rollout.WorkspaceAppRolloutError(
            "redacted observation target differs from the authoritative runtime"
        )
    entry_policy: str | None = None
    semantic_proof: dict[str, Any] | None = None
    if phase == "preflight":
        _validate_preflight_semantic_proof(
            db,
            payload=payload,
            workspace=workspace,
            runtime=runtime,
        )
    else:
        entry_policy = _validate_postactivation_entry_policy(payload, runtime=runtime)
        semantic_proof = _validate_action_pack_proof(
            db,
            payload=payload,
            workspace=workspace,
            runtime=runtime,
        )
        _validate_workspace_switch_proof(
            db,
            payload=payload,
            workspace=workspace,
            runtime=runtime,
            foreign_pack=semantic_proof["foreign_pack"],
        )
        if payload["target"].get("probation_ref") != probation_ref:
            raise rollout.WorkspaceAppRolloutError(
                "redacted observation belongs to a different probation"
            )
        state = rollout._state(workspace)
        probation = _record(state.get("probation"))
        generated_at = payload["generated_at"]
        if not (
            rollout._parse_utc(probation.get("staged_at"), field="staged_at")
            <= generated_at
            <= rollout._parse_utc(probation.get("expires_at"), field="expires_at")
        ):
            raise rollout.WorkspaceAppRolloutError(
                "post-activation observation is outside its probation"
            )
    observation_for_hash = {**payload, "generated_at": payload["generated_at"].isoformat()}
    observation_ref = f"sha256:{_canonical_sha256(observation_for_hash)}"
    runner = payload["runner"]
    promotable = bool(
        mode == "protected"
        and runner.get("protected_ci") is True
        and str(runner.get("pipeline_id") or "").strip()
        and str(runner.get("job_id") or "").strip()
        and all(payload["checks"].get(name) is True for name in checks)
    )
    if not promotable:
        return {
            "schema_version": 1,
            "kind": f"lot9_workspace_app_{phase}_local_collection",
            "status": "non_promotable",
            "revision": revision,
            "observation_ref": observation_ref,
            "workspace_sha256": _id_sha256(workspace.id),
            "installations_sha256": installations_sha,
            "runtime_shell": runtime.shell,
            "entry_policy": entry_policy,
            "reason": "protected phase-specific behaviour evidence is required",
        }
    actor = str(validated_by or "").strip()
    if not actor:
        raise rollout.WorkspaceAppRolloutError("protected collection requires validated_by")
    producer = rollout._validated_trusted_runner(trusted_runner, revision=revision)
    if producer["pipeline_id"] != str(runner["pipeline_id"]) or producer["job_id"] != str(
        runner["job_id"]
    ):
        raise rollout.WorkspaceAppRolloutError(
            "protected observation and OIDC producer identify different GitLab jobs"
        )
    subject: dict[str, Any] = {
        "workspace_id": workspace.id,
        "installations": installations,
        "installations_sha256": installations_sha,
    }
    if probation_ref is not None:
        subject["probation_ref"] = probation_ref
        subject["runtime_shell"] = runtime.shell
        subject["entry_policy"] = entry_policy
        subject["declared_entitlement_count"] = payload["diagnostics"]["declared_entitlement_count"]
    return {
        "schema_version": rollout.EVIDENCE_SCHEMA_VERSION,
        "kind": evidence_kind,
        "activation_grade": True,
        "revision": revision,
        "generated_at": payload["generated_at"].isoformat(),
        "validated_by": actor,
        "observation_ref": observation_ref,
        "trusted_runner": producer,
        "source_junit": source_junit,
        "subject": subject,
        "checks": {name: True for name in checks},
        "runner_artifact": _canonical_runner_artifact(
            revision=revision,
            workspace_id=workspace.id,
            installations_sha256=installations_sha,
            checks=checks,
            suite_name=suite_name,
            observation_ref=observation_ref,
            probation_ref=probation_ref,
            source_junit_ref=source_junit["artifact_ref"],
        ),
    }


def _load_json(path: str) -> Mapping[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise rollout.WorkspaceAppRolloutError(f"cannot load observation: {exc}") from exc
    if not isinstance(value, Mapping):
        raise rollout.WorkspaceAppRolloutError("observation root must be an object")
    return value


def _protected_environment(revision: str, observation: Mapping[str, Any]) -> None:
    runner = _record(observation.get("runner"))
    if (
        os.getenv("CI") != "true"
        or os.getenv("CI_COMMIT_REF_PROTECTED") != "true"
        or str(os.getenv("CI_COMMIT_SHA") or "").lower() != revision
        or not os.getenv("CI_PIPELINE_ID")
        or not os.getenv("CI_JOB_ID")
        or runner.get("protected_ci") is not True
        or str(runner.get("pipeline_id") or "") != os.getenv("CI_PIPELINE_ID")
        or str(runner.get("job_id") or "") != os.getenv("CI_JOB_ID")
    ):
        raise rollout.WorkspaceAppRolloutError(
            "protected collection requires a protected CI job on the exact runtime revision"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("preflight", "postactivation"), required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--observation", required=True)
    parser.add_argument("--junit", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--mode", choices=("local", "protected"), default="local")
    parser.add_argument("--validated-by", default="")
    parser.add_argument(
        "--oidc-token-env",
        default="AGENTIUM_ATTESTATION_ID_TOKEN",
    )
    parser.add_argument("--oidc-audience")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        observation = _load_json(args.observation)
        junit = Path(args.junit).read_bytes()
        with SessionLocal() as db:
            trusted_runner = None
            if args.mode == "protected":
                _protected_environment(rollout._runtime_revision(), observation)
                trusted_runner = rollout._current_trusted_runner(
                    token_env=args.oidc_token_env,
                    audience=args.oidc_audience,
                )
            result = collect_evidence(
                db,
                phase=args.phase,
                workspace_id=args.workspace_id,
                observation=observation,
                playwright_junit=junit,
                mode=args.mode,
                validated_by=args.validated_by,
                trusted_runner=trusted_runner,
            )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        output.chmod(0o600)
        print(
            json.dumps(
                {
                    "status": result.get("status", "collected"),
                    "observation_ref": result["observation_ref"],
                    "output": str(output),
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, rollout.WorkspaceAppRolloutError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
