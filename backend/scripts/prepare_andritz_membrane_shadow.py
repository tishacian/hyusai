#!/usr/bin/env python3
"""Prepare MembraneSpec v2 shadow policies for canonically stamped Andritz.

Selection is based only on ``Workspace.settings.family == \"andritz\"`` and
the existing membrane-origin marker on a System-bound ControlPolicy.  Mutable
slugs/names and fixed database ids are deliberately ignored.

The transition is append-only:

* the current ControlPolicy and every historical SystemVersion stay untouched;
* a new v2 ``shadow`` ControlPolicy is cloned from the current contract;
* the current System is rebound to that clone;
* an explicit, new SystemVersion snapshot records the configuration transition.

The SystemVersion stores only an allowlisted configuration envelope: source and
target policy references, enforcement mode, and contract SHA-256 digests.  It
never copies the policy body or workspace settings.  The cloned policy stores
the same rollback anchor and the source policy is never deleted or edited.  Any
malformed or ambiguous target blocks the whole transaction.  This tool has
intentionally no enforce mode. Preparation also requires the authoritative
database status of the Showcase Lot 6 rollout to report ``ready=true``;
rollback deliberately remains independent from that forward-only prerequisite.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.base import SessionLocal  # noqa: E402
from app.models.policy import ControlPolicy  # noqa: E402
from app.models.system import System  # noqa: E402
from app.models.system_version import SystemVersion  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.audit_logger import emit_audit_event  # noqa: E402
from app.services.chains.version_service import (  # noqa: E402
    CONFIGURATION_SNAPSHOT_SCHEMA_VERSION,
    record_new_version,
)
from app.services.membrane.spec import FACET_NAMES, EnforcementMode, MembraneSpec  # noqa: E402
from app.services.workspace_features import workspace_family  # noqa: E402
from scripts.rollout_system360_canary import (  # noqa: E402
    RolloutError as Lot6RolloutError,
)
from scripts.rollout_system360_canary import status as _lot6_showcase_status  # noqa: E402

CANONICAL_FAMILY = "andritz"
SHADOW_MARKER_KEY = "_lot7_andritz_membrane_shadow_v1"
SHADOW_MARKER_SCHEMA_VERSION = 2
ROLLOUT_ADVISORY_LOCK = "agentium:lot7:andritz_membrane_shadow"
LOT6_SHOWCASE_PREREQUISITE_KIND = "lot6_showcase_system360_status"


class AndritzShadowError(ValueError):
    """Raised before an unsafe or ambiguous shadow preparation."""


def _record(value: Any) -> dict[str, Any]:
    return copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _raw_membrane(policy: ControlPolicy) -> dict[str, Any]:
    raw = _record(policy.extra).get("membrane_spec")
    if not isinstance(raw, Mapping):
        raise AndritzShadowError("bound marked ControlPolicy has no membrane_spec object")
    return copy.deepcopy(dict(raw))


def _shadow_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade a readable v1/v2 contract to strict v2 shadow without loss."""

    source = copy.deepcopy(dict(raw))
    try:
        parsed = MembraneSpec.from_dict(source, authoritative=True)
    except (TypeError, ValueError) as exc:
        raise AndritzShadowError(f"invalid source MembraneSpec: {exc}") from exc
    if parsed.effective_mode is EnforcementMode.ENFORCE:
        raise AndritzShadowError("refusing to replace an enforce MembraneSpec")

    canonical = parsed.to_dict()
    desired = copy.deepcopy(source)
    for facet in FACET_NAMES:
        current = desired.get(facet)
        if current is not None and not isinstance(current, Mapping):
            raise AndritzShadowError(f"membrane_spec.{facet} must be an object")
        merged = _record(current)
        for key, value in _record(canonical.get(facet)).items():
            merged.setdefault(key, copy.deepcopy(value))
        desired[facet] = merged
    desired["version"] = 2
    desired["enforcement_mode"] = EnforcementMode.SHADOW.value
    try:
        validated = MembraneSpec.from_dict(desired, authoritative=True)
    except (TypeError, ValueError) as exc:
        raise AndritzShadowError(
            f"source contract cannot be upgraded safely to MembraneSpec v2: {exc}"
        ) from exc
    if validated.effective_mode is not EnforcementMode.SHADOW:
        raise AndritzShadowError("prepared MembraneSpec is not shadow")
    return desired


def _bound_policy(
    db: DBSession,
    workspace: Workspace,
    system: System,
    *,
    lock: bool,
) -> ControlPolicy | None:
    if not system.control_policy_id:
        return None
    query = db.query(ControlPolicy).filter(
        ControlPolicy.id == system.control_policy_id,
        ControlPolicy.workspace_id == workspace.id,
        ControlPolicy.scope == "system",
        ControlPolicy.target_id == system.id,
    )
    if lock:
        query = query.with_for_update(of=ControlPolicy)
    rows = query.all()
    return rows[0] if len(rows) == 1 else None


def _marked_policy(policy: ControlPolicy) -> bool:
    extra = _record(policy.extra)
    marker = extra.get("membrane_origin")
    return (
        isinstance(marker, str)
        and bool(marker.strip())
        and isinstance(extra.get("membrane_spec"), Mapping)
    )


def _prepared_marker(policy: ControlPolicy) -> dict[str, Any]:
    marker = _record(_record(policy.extra).get(SHADOW_MARKER_KEY))
    if marker and marker.get("schema_version") != SHADOW_MARKER_SCHEMA_VERSION:
        raise AndritzShadowError("unsupported Andritz shadow marker schema")
    return marker


def _transition_snapshot(
    *,
    source_policy_id: str,
    target_policy_id: str,
    source_contract_sha256: str,
    target_contract_sha256: str,
    enforcement_mode: str = EnforcementMode.SHADOW.value,
) -> dict[str, Any]:
    """Return the only configuration evidence this rollout may persist."""

    return {
        "schema_version": CONFIGURATION_SNAPSHOT_SCHEMA_VERSION,
        "bindings": {"control_policy_id": target_policy_id},
        "transition": {
            "kind": "control_policy_rebind",
            "previous_control_policy_id": source_policy_id,
            "enforcement_mode": enforcement_mode,
            "source_contract_sha256": source_contract_sha256,
            "target_contract_sha256": target_contract_sha256,
        },
    }


def _target_fingerprint(target: Mapping[str, Any]) -> dict[str, Any]:
    workspace: Workspace = target["workspace"]
    system: System = target["system"]
    policy: ControlPolicy = target.get("policy") or target.get("shadow_policy")
    source_policy: ControlPolicy = target["source_policy"]
    return {
        "workspace_id": workspace.id,
        "workspace_family": workspace_family(workspace),
        "system_id": system.id,
        "system_status": system.status,
        "system_control_policy_id": system.control_policy_id,
        "system_flow_sha256": _sha256(system.flow_definition),
        "policy_id": policy.id,
        "policy_sha256": _sha256(policy.extra),
        "source_policy_id": source_policy.id,
        "source_policy_sha256": _sha256(source_policy.extra),
        "desired_membrane_sha256": (
            _sha256(target["desired_membrane"])
            if "desired_membrane" in target
            else None
        ),
        "changed": bool(target["changed"]),
    }


def _analysis_fingerprint(report: Mapping[str, Any]) -> str:
    return _sha256(
        {
            "schema_version": report.get("schema_version"),
            "family": report.get("family"),
            "ready": report.get("ready"),
            "prerequisite": report.get("prerequisite"),
            "workspace_count": report.get("workspace_count"),
            "target_count": report.get("target_count"),
            "changed_count": report.get("changed_count"),
            "blockers": report.get("blockers"),
            "targets": sorted(
                (_target_fingerprint(target) for target in report.get("_targets", [])),
                key=lambda row: (row["workspace_id"], row["system_id"], row["policy_id"]),
            ),
        }
    )


def _showcase_prerequisite(db: DBSession) -> dict[str, Any]:
    """Read and content-address the authoritative Lot 6 Showcase status."""

    try:
        status = _lot6_showcase_status(db)
    except (Lot6RolloutError, TypeError, ValueError) as exc:
        return {
            "kind": LOT6_SHOWCASE_PREREQUISITE_KIND,
            "source": "database",
            "ready": False,
            "error": str(exc),
        }
    proof = {
        "kind": LOT6_SHOWCASE_PREREQUISITE_KIND,
        "source": "database",
        "ready": status.get("ready") is True,
        "workspace_id": status.get("workspace_id"),
        "capability_id": status.get("capability_id"),
        "system_id": status.get("system_id"),
        "phase": status.get("phase"),
    }
    return {**proof, "status_ref": f"sha256:{_sha256(proof)}"}


def _lock_exact_subjects(
    db: DBSession,
    *,
    targets: list[dict[str, Any]],
) -> None:
    """Lock only the discovered rollout cohort, in one deterministic order."""

    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": ROLLOUT_ADVISORY_LOCK},
        )

    workspace_ids = sorted({target["workspace"].id for target in targets})
    system_ids = sorted({target["system"].id for target in targets})
    policies = {
        policy.id: policy
        for target in targets
        for policy in (
            target.get("policy"),
            target.get("shadow_policy"),
            target.get("source_policy"),
        )
        if policy is not None
    }
    policy_ids = sorted(policies)
    version_ids = sorted(
        {
            str(_prepared_marker(policy).get("system_version_id") or "")
            for policy in policies.values()
            if _prepared_marker(policy)
        }
        - {""}
    )

    locked_workspaces = (
        db.query(Workspace)
        .filter(Workspace.id.in_(workspace_ids))
        .order_by(Workspace.id.asc())
        .with_for_update(of=Workspace)
        .populate_existing()
        .all()
        if workspace_ids
        else []
    )
    locked_systems = (
        db.query(System)
        .filter(System.id.in_(system_ids))
        .order_by(System.id.asc())
        .with_for_update(of=System)
        .populate_existing()
        .all()
        if system_ids
        else []
    )
    locked_policies = (
        db.query(ControlPolicy)
        .filter(ControlPolicy.id.in_(policy_ids))
        .order_by(ControlPolicy.id.asc())
        .with_for_update(of=ControlPolicy)
        .populate_existing()
        .all()
        if policy_ids
        else []
    )
    locked_versions = (
        db.query(SystemVersion)
        .filter(SystemVersion.id.in_(version_ids))
        .order_by(SystemVersion.id.asc())
        .with_for_update(of=SystemVersion)
        .populate_existing()
        .all()
        if version_ids
        else []
    )
    if (
        len(locked_workspaces) != len(workspace_ids)
        or len(locked_systems) != len(system_ids)
        or len(locked_policies) != len(policy_ids)
        or len(locked_versions) != len(version_ids)
    ):
        raise AndritzShadowError("concurrent_preflight_drift")


def _revalidate_under_exact_locks(
    db: DBSession,
    *,
    discovered: dict[str, Any],
    analyzer: Any,
) -> dict[str, Any]:
    expected = _analysis_fingerprint(discovered)
    _lock_exact_subjects(db, targets=discovered["_targets"])
    current = analyzer(db, lock=False)
    if _analysis_fingerprint(current) != expected:
        raise AndritzShadowError("concurrent_preflight_drift")
    return current


def analyze(db: DBSession, *, lock: bool = False) -> dict[str, Any]:
    """Return a complete preflight report; never mutates the database."""

    prerequisite = _showcase_prerequisite(db)
    workspace_query = db.query(Workspace).filter(
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    )
    workspaces = [
        workspace
        for workspace in workspace_query.order_by(Workspace.id.asc()).all()
        if workspace_family(workspace) == CANONICAL_FAMILY
    ]
    blockers: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    if not workspaces:
        blockers.append({"code": "no_canonical_family", "family": CANONICAL_FAMILY})

    for workspace in workspaces:
        system_query = db.query(System).filter(
            System.workspace_id == workspace.id,
            System.status == "active",
        )
        marked_count = 0
        for system in system_query.order_by(System.id.asc()).all():
            policy = _bound_policy(db, workspace, system, lock=False)
            if policy is None:
                continue
            try:
                prepared_marker = _prepared_marker(policy)
            except AndritzShadowError as exc:
                blockers.append(
                    {
                        "code": "invalid_shadow_marker",
                        "workspace_id": workspace.id,
                        "system_id": system.id,
                        "reason": str(exc),
                    }
                )
                continue
            if prepared_marker:
                marked_count += 1
                if not isinstance(system.flow_definition, Mapping):
                    blockers.append(
                        {
                            "code": "flow_definition_not_object",
                            "workspace_id": workspace.id,
                            "system_id": system.id,
                        }
                    )
                    continue
                try:
                    current_membrane = _raw_membrane(policy)
                    spec = MembraneSpec.from_dict(current_membrane, authoritative=True)
                except (AndritzShadowError, TypeError, ValueError) as exc:
                    blockers.append(
                        {
                            "code": "invalid_prepared_policy",
                            "workspace_id": workspace.id,
                            "system_id": system.id,
                            "policy_id": policy.id,
                            "reason": str(exc),
                        }
                    )
                    continue
                if spec.effective_mode is not EnforcementMode.SHADOW:
                    blockers.append(
                        {
                            "code": "prepared_policy_not_shadow",
                            "workspace_id": workspace.id,
                            "system_id": system.id,
                            "policy_id": policy.id,
                        }
                    )
                    continue
                source_id = str(prepared_marker.get("source_policy_id") or "")
                source_policy = (
                    db.query(ControlPolicy)
                    .filter(
                        ControlPolicy.id == source_id,
                        ControlPolicy.workspace_id == workspace.id,
                        ControlPolicy.scope == "system",
                        ControlPolicy.target_id == system.id,
                    )
                    .one_or_none()
                    if source_id
                    else None
                )
                if source_policy is None or source_policy.id == policy.id:
                    blockers.append(
                        {
                            "code": "source_policy_missing",
                            "workspace_id": workspace.id,
                            "system_id": system.id,
                            "policy_id": policy.id,
                        }
                    )
                    continue
                try:
                    current_source_sha = _sha256(_raw_membrane(source_policy))
                except AndritzShadowError as exc:
                    blockers.append(
                        {
                            "code": "source_policy_invalid",
                            "workspace_id": workspace.id,
                            "system_id": system.id,
                            "policy_id": policy.id,
                            "reason": str(exc),
                        }
                    )
                    continue
                if prepared_marker.get(
                    "source_membrane_sha256"
                ) != current_source_sha or prepared_marker.get("target_membrane_sha256") != _sha256(
                    current_membrane
                ):
                    blockers.append(
                        {
                            "code": "prepared_policy_digest_drift",
                            "workspace_id": workspace.id,
                            "system_id": system.id,
                            "policy_id": policy.id,
                        }
                    )
                    continue
                transition_version_id = str(prepared_marker.get("system_version_id") or "")
                transition_version = (
                    db.query(SystemVersion)
                    .filter(
                        SystemVersion.id == transition_version_id,
                        SystemVersion.system_id == system.id,
                        SystemVersion.workspace_id == workspace.id,
                    )
                    .one_or_none()
                    if transition_version_id
                    else None
                )
                if transition_version is None:
                    blockers.append(
                        {
                            "code": "transition_system_version_missing",
                            "workspace_id": workspace.id,
                            "system_id": system.id,
                            "policy_id": policy.id,
                        }
                    )
                    continue
                expected_snapshot = _transition_snapshot(
                    source_policy_id=source_policy.id,
                    target_policy_id=policy.id,
                    source_contract_sha256=current_source_sha,
                    target_contract_sha256=_sha256(current_membrane),
                )
                if (
                    _canonical_json(transition_version.configuration_snapshot)
                    != _canonical_json(expected_snapshot)
                    or prepared_marker.get("configuration_snapshot_sha256")
                    != _sha256(expected_snapshot)
                ):
                    blockers.append(
                        {
                            "code": "transition_configuration_snapshot_drift",
                            "workspace_id": workspace.id,
                            "system_id": system.id,
                            "policy_id": policy.id,
                            "system_version_id": transition_version.id,
                        }
                    )
                    continue
                targets.append(
                    {
                        "workspace": workspace,
                        "system": system,
                        "policy": policy,
                        "source_policy": source_policy,
                        "source_policy_id": source_id,
                        "desired_membrane": _raw_membrane(policy),
                        "changed": False,
                    }
                )
                continue
            if not _marked_policy(policy):
                continue
            marked_count += 1
            if not isinstance(system.flow_definition, Mapping):
                blockers.append(
                    {
                        "code": "flow_definition_not_object",
                        "workspace_id": workspace.id,
                        "system_id": system.id,
                    }
                )
                continue
            try:
                source = _raw_membrane(policy)
                desired = _shadow_payload(source)
            except AndritzShadowError as exc:
                blockers.append(
                    {
                        "code": "unsafe_membrane_contract",
                        "workspace_id": workspace.id,
                        "system_id": system.id,
                        "policy_id": policy.id,
                        "reason": str(exc),
                    }
                )
                continue
            targets.append(
                {
                    "workspace": workspace,
                    "system": system,
                    "policy": policy,
                    "source_policy": policy,
                    "source_policy_id": policy.id,
                    "desired_membrane": desired,
                    "changed": True,
                }
            )
        if marked_count == 0:
            blockers.append(
                {
                    "code": "no_marked_membrane_system",
                    "workspace_id": workspace.id,
                }
            )

    return {
        "schema_version": 1,
        "family": CANONICAL_FAMILY,
        "model_contract": {
            "system_version_scope": "flow_and_allowlisted_configuration_evidence",
            "configuration_snapshot_schema_version": (
                CONFIGURATION_SNAPSHOT_SCHEMA_VERSION
            ),
            "rollback_anchor": "source_control_policy_preserved",
            "enforce_supported": False,
        },
        "ready": not blockers,
        "prerequisite": prerequisite,
        "workspace_count": len(workspaces),
        "target_count": len(targets),
        "changed_count": sum(1 for target in targets if target["changed"]),
        "blockers": blockers,
        "_targets": targets,
    }


def _append_transition_version(
    db: DBSession,
    *,
    system: System,
    actor: str,
    source_policy_id: str,
    target_policy_id: str,
    source_contract_sha256: str,
    target_contract_sha256: str,
    enforcement_mode: str = EnforcementMode.SHADOW.value,
    message: str | None = None,
) -> SystemVersion:
    version = record_new_version(
        db=db,
        system=system,
        flow_definition=_record(system.flow_definition),
        created_by=actor,
        audit_actor=actor,
        message=message
        or f"Lot 7 Membrane shadow v2 policy transition ({target_policy_id})",
        purge=False,
        configuration_snapshot=_transition_snapshot(
            source_policy_id=source_policy_id,
            target_policy_id=target_policy_id,
            source_contract_sha256=source_contract_sha256,
            target_contract_sha256=target_contract_sha256,
            enforcement_mode=enforcement_mode,
        ),
    )
    if version is None:
        raise AndritzShadowError(
            "SystemVersion refused a distinct configuration transition"
        )
    return version


def prepare(db: DBSession, *, apply: bool, actor: str) -> dict[str, Any]:
    actor_value = str(actor or "").strip()
    if apply and not actor_value:
        raise AndritzShadowError("--apply requires a non-empty actor")
    preflight = analyze(db, lock=False)
    if apply:
        prerequisite_ready = _record(preflight.get("prerequisite")).get("ready") is True
        if not preflight["ready"] or not prerequisite_ready:
            reasons = [blocker["code"] for blocker in preflight["blockers"]]
            if not prerequisite_ready:
                reasons.append("lot6_showcase_not_ready")
            raise AndritzShadowError(
                "Andritz Membrane shadow preflight is blocked: "
                + ", ".join(reasons)
            )
        preflight = _revalidate_under_exact_locks(
            db,
            discovered=preflight,
            analyzer=analyze,
        )
    targets = preflight.pop("_targets")
    prerequisite = _record(preflight.get("prerequisite"))
    report = {
        **preflight,
        "operation": "apply" if apply else "dry_run",
        "targets": [
            {
                "workspace_id": target["workspace"].id,
                "system_id": target["system"].id,
                "source_policy_id": target["source_policy_id"],
                "changed": target["changed"],
                "target_mode": EnforcementMode.SHADOW.value,
                "source_membrane_sha256": _sha256(_raw_membrane(target["source_policy"])),
                "target_membrane_sha256": _sha256(target["desired_membrane"]),
            }
            for target in targets
        ],
    }
    if not apply:
        return report
    applied: list[dict[str, Any]] = []
    for target in targets:
        if not target["changed"]:
            applied.append(
                {
                    "workspace_id": target["workspace"].id,
                    "system_id": target["system"].id,
                    "policy_id": target["policy"].id,
                    "changed": False,
                }
            )
            continue
        workspace: Workspace = target["workspace"]
        system: System = target["system"]
        source_policy: ControlPolicy = target["policy"]
        desired_membrane = target["desired_membrane"]
        new_policy_id = str(uuid4())
        source_membrane_sha = _sha256(_raw_membrane(source_policy))
        target_membrane_sha = _sha256(desired_membrane)
        version = _append_transition_version(
            db,
            system=system,
            actor=actor_value,
            source_policy_id=source_policy.id,
            target_policy_id=new_policy_id,
            source_contract_sha256=source_membrane_sha,
            target_contract_sha256=target_membrane_sha,
        )
        source_extra = _record(source_policy.extra)
        extra = copy.deepcopy(source_extra)
        extra["membrane_spec"] = copy.deepcopy(desired_membrane)
        extra[SHADOW_MARKER_KEY] = {
            "schema_version": SHADOW_MARKER_SCHEMA_VERSION,
            "source_policy_id": source_policy.id,
            "source_membrane_sha256": source_membrane_sha,
            "target_membrane_sha256": target_membrane_sha,
            "system_version_id": version.id,
            "system_version_number": version.version_number,
            "configuration_snapshot_sha256": _sha256(
                version.configuration_snapshot
            ),
            "lot6_showcase_status_ref": prerequisite["status_ref"],
            "lot6_showcase_system_id": prerequisite["system_id"],
            "prepared_by": actor_value,
            "prepared_at": datetime.now(UTC).isoformat(),
        }
        shadow_policy = ControlPolicy(
            id=new_policy_id,
            workspace_id=workspace.id,
            name=(f"{source_policy.name} [shadow v2]")[:200],
            scope="system",
            target_id=system.id,
            max_cost_per_decision=source_policy.max_cost_per_decision,
            max_latency_ms=source_policy.max_latency_ms,
            mandatory_hitl_if_confidence_below=source_policy.mandatory_hitl_if_confidence_below,
            allowed_models=copy.deepcopy(source_policy.allowed_models or []),
            allowed_skills=copy.deepcopy(source_policy.allowed_skills or []),
            extra=extra,
        )
        db.add(shadow_policy)
        db.flush()
        system.control_policy_id = shadow_policy.id
        db.add(system)
        audit_id = emit_audit_event(
            workspace_id=workspace.id,
            event_type="lot7.andritz.membrane_shadow.prepared",
            actor=actor_value,
            agent_id=system.id,
            details={
                "system_id": system.id,
                "source_policy_id": source_policy.id,
                "shadow_policy_id": shadow_policy.id,
                "system_version_id": version.id,
                "system_version_number": version.version_number,
                "source_membrane_sha256": source_membrane_sha,
                "target_membrane_sha256": target_membrane_sha,
                "configuration_snapshot_sha256": _sha256(
                    version.configuration_snapshot
                ),
                "lot6_showcase_status_ref": prerequisite["status_ref"],
                "lot6_showcase_system_id": prerequisite["system_id"],
                "enforcement_mode": EnforcementMode.SHADOW.value,
            },
            db=db,
        )
        if audit_id is None:
            raise AndritzShadowError("the shadow preparation audit could not be persisted")
        applied.append(
            {
                "workspace_id": workspace.id,
                "system_id": system.id,
                "source_policy_id": source_policy.id,
                "policy_id": shadow_policy.id,
                "system_version_id": version.id,
                "system_version_number": version.version_number,
                "changed": True,
            }
        )
    db.commit()
    report["targets"] = applied
    return report


def _prepared_policies_for_system(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    lock: bool,
) -> list[ControlPolicy]:
    query = db.query(ControlPolicy).filter(
        ControlPolicy.workspace_id == workspace.id,
        ControlPolicy.scope == "system",
        ControlPolicy.target_id == system.id,
    )
    if lock:
        query = query.with_for_update(of=ControlPolicy)
    prepared = [
        policy
        for policy in query.order_by(ControlPolicy.id.asc()).all()
        if _prepared_marker(policy)
    ]
    # The currently bound prepared policy is always the active generation.
    bound = [policy for policy in prepared if policy.id == system.control_policy_id]
    if bound:
        return bound

    # After rollback the source is bound and historical prepared policies stay
    # append-only. Select the latest generation anchored to that source so a
    # prepare -> rollback -> prepare lifecycle cannot create an ambiguous
    # rollback target. Equal/malformed generations remain ambiguous and fail
    # closed in the caller.
    anchored = [
        policy
        for policy in prepared
        if str(_prepared_marker(policy).get("source_policy_id") or "")
        == str(system.control_policy_id or "")
    ]
    if not anchored:
        return prepared
    try:
        generations = {
            int(_prepared_marker(policy).get("system_version_number") or 0): policy
            for policy in anchored
        }
    except (TypeError, ValueError) as exc:
        raise AndritzShadowError("invalid prepared policy generation") from exc
    if len(generations) != len(anchored) or 0 in generations:
        return anchored
    return [generations[max(generations)]]


def _validate_rollback_target(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    shadow_policy: ControlPolicy,
) -> dict[str, Any]:
    marker = _prepared_marker(shadow_policy)
    source_policy_id = str(marker.get("source_policy_id") or "")
    source_policy = (
        db.query(ControlPolicy)
        .filter(
            ControlPolicy.id == source_policy_id,
            ControlPolicy.workspace_id == workspace.id,
            ControlPolicy.scope == "system",
            ControlPolicy.target_id == system.id,
        )
        .one_or_none()
        if source_policy_id
        else None
    )
    if source_policy is None or source_policy.id == shadow_policy.id:
        raise AndritzShadowError("rollback source policy is missing or out of scope")

    source_membrane = _raw_membrane(source_policy)
    target_membrane = _raw_membrane(shadow_policy)
    source_sha = _sha256(source_membrane)
    target_sha = _sha256(target_membrane)
    if (
        marker.get("source_membrane_sha256") != source_sha
        or marker.get("target_membrane_sha256") != target_sha
    ):
        raise AndritzShadowError("rollback policy contract digest drift")
    target_spec = MembraneSpec.from_dict(target_membrane, authoritative=True)
    if target_spec.effective_mode is not EnforcementMode.SHADOW:
        raise AndritzShadowError("rollback target policy is no longer shadow")
    source_spec = MembraneSpec.from_dict(source_membrane, authoritative=True)
    if source_spec.effective_mode is EnforcementMode.ENFORCE:
        raise AndritzShadowError("rollback source unexpectedly resolves to enforce")

    transition_version_id = str(marker.get("system_version_id") or "")
    transition_version = (
        db.query(SystemVersion)
        .filter(
            SystemVersion.id == transition_version_id,
            SystemVersion.system_id == system.id,
            SystemVersion.workspace_id == workspace.id,
        )
        .one_or_none()
        if transition_version_id
        else None
    )
    if transition_version is None:
        raise AndritzShadowError("rollback transition SystemVersion is missing")
    expected_snapshot = _transition_snapshot(
        source_policy_id=source_policy.id,
        target_policy_id=shadow_policy.id,
        source_contract_sha256=source_sha,
        target_contract_sha256=target_sha,
    )
    if (
        _canonical_json(transition_version.configuration_snapshot)
        != _canonical_json(expected_snapshot)
        or marker.get("configuration_snapshot_sha256") != _sha256(expected_snapshot)
    ):
        raise AndritzShadowError("rollback transition evidence drift")
    if system.control_policy_id not in {shadow_policy.id, source_policy.id}:
        raise AndritzShadowError("rollback binding drift")
    return {
        "workspace": workspace,
        "system": system,
        "shadow_policy": shadow_policy,
        "source_policy": source_policy,
        "source_membrane_sha256": source_sha,
        "target_membrane_sha256": target_sha,
        "source_mode": source_spec.effective_mode.value,
        "changed": system.control_policy_id == shadow_policy.id,
    }


def analyze_rollback(db: DBSession, *, lock: bool = False) -> dict[str, Any]:
    """Discover only rollback anchors created by this rollout."""

    workspace_query = db.query(Workspace).filter(
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    )
    workspaces = [
        workspace
        for workspace in workspace_query.order_by(Workspace.id.asc()).all()
        if workspace_family(workspace) == CANONICAL_FAMILY
    ]
    blockers: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    if not workspaces:
        blockers.append({"code": "no_canonical_family", "family": CANONICAL_FAMILY})

    for workspace in workspaces:
        system_query = db.query(System).filter(
            System.workspace_id == workspace.id,
            System.status == "active",
        )
        workspace_target_count = 0
        for system in system_query.order_by(System.id.asc()).all():
            try:
                prepared = _prepared_policies_for_system(
                    db,
                    workspace=workspace,
                    system=system,
                    lock=False,
                )
            except AndritzShadowError as exc:
                workspace_target_count += 1
                blockers.append(
                    {
                        "code": "invalid_shadow_marker",
                        "workspace_id": workspace.id,
                        "system_id": system.id,
                        "reason": str(exc),
                    }
                )
                continue
            if not prepared:
                continue
            workspace_target_count += 1
            if len(prepared) != 1:
                blockers.append(
                    {
                        "code": "ambiguous_shadow_rollback_anchor",
                        "workspace_id": workspace.id,
                        "system_id": system.id,
                        "policy_ids": [policy.id for policy in prepared],
                    }
                )
                continue
            try:
                targets.append(
                    _validate_rollback_target(
                        db,
                        workspace=workspace,
                        system=system,
                        shadow_policy=prepared[0],
                    )
                )
            except (AndritzShadowError, TypeError, ValueError) as exc:
                blockers.append(
                    {
                        "code": "unsafe_shadow_rollback",
                        "workspace_id": workspace.id,
                        "system_id": system.id,
                        "policy_id": prepared[0].id,
                        "reason": str(exc),
                    }
                )
        if workspace_target_count == 0:
            blockers.append(
                {
                    "code": "no_prepared_shadow_system",
                    "workspace_id": workspace.id,
                }
            )

    return {
        "schema_version": 1,
        "family": CANONICAL_FAMILY,
        "ready": not blockers,
        "workspace_count": len(workspaces),
        "target_count": len(targets),
        "changed_count": sum(1 for target in targets if target["changed"]),
        "blockers": blockers,
        "_targets": targets,
    }


def rollback(db: DBSession, *, apply: bool, actor: str) -> dict[str, Any]:
    actor_value = str(actor or "").strip()
    if apply and not actor_value:
        raise AndritzShadowError("--apply requires a non-empty actor")
    preflight = analyze_rollback(db, lock=False)
    if apply:
        if not preflight["ready"]:
            raise AndritzShadowError(
                "Andritz Membrane shadow rollback preflight is blocked: "
                + ", ".join(blocker["code"] for blocker in preflight["blockers"])
            )
        preflight = _revalidate_under_exact_locks(
            db,
            discovered=preflight,
            analyzer=analyze_rollback,
        )
    targets = preflight.pop("_targets")
    report = {
        **preflight,
        "operation": "rollback_apply" if apply else "rollback_dry_run",
        "targets": [
            {
                "workspace_id": target["workspace"].id,
                "system_id": target["system"].id,
                "shadow_policy_id": target["shadow_policy"].id,
                "source_policy_id": target["source_policy"].id,
                "changed": target["changed"],
                "restored_mode": target["source_mode"],
            }
            for target in targets
        ],
    }
    if not apply:
        return report
    applied: list[dict[str, Any]] = []
    for target in targets:
        workspace: Workspace = target["workspace"]
        system: System = target["system"]
        shadow_policy: ControlPolicy = target["shadow_policy"]
        source_policy: ControlPolicy = target["source_policy"]
        if not target["changed"]:
            applied.append(
                {
                    "workspace_id": workspace.id,
                    "system_id": system.id,
                    "shadow_policy_id": shadow_policy.id,
                    "source_policy_id": source_policy.id,
                    "changed": False,
                }
            )
            continue
        version = _append_transition_version(
            db,
            system=system,
            actor=actor_value,
            source_policy_id=shadow_policy.id,
            target_policy_id=source_policy.id,
            source_contract_sha256=target["target_membrane_sha256"],
            target_contract_sha256=target["source_membrane_sha256"],
            enforcement_mode=target["source_mode"],
            message=f"Lot 7 Membrane shadow rollback ({source_policy.id})",
        )
        system.control_policy_id = source_policy.id
        db.add(system)
        audit_id = emit_audit_event(
            workspace_id=workspace.id,
            event_type="lot7.andritz.membrane_shadow.rolled_back",
            actor=actor_value,
            agent_id=system.id,
            details={
                "system_id": system.id,
                "shadow_policy_id": shadow_policy.id,
                "source_policy_id": source_policy.id,
                "system_version_id": version.id,
                "system_version_number": version.version_number,
                "shadow_membrane_sha256": target["target_membrane_sha256"],
                "restored_membrane_sha256": target["source_membrane_sha256"],
                "restored_enforcement_mode": target["source_mode"],
            },
            db=db,
        )
        if audit_id is None:
            raise AndritzShadowError("the shadow rollback audit could not be persisted")
        applied.append(
            {
                "workspace_id": workspace.id,
                "system_id": system.id,
                "shadow_policy_id": shadow_policy.id,
                "source_policy_id": source_policy.id,
                "system_version_id": version.id,
                "system_version_number": version.version_number,
                "changed": True,
            }
        )
    db.commit()
    report["targets"] = applied
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="restore only source policies anchored by this rollout",
    )
    parser.add_argument("--actor")
    return parser


def main() -> int:
    args = _parser().parse_args()
    db = SessionLocal()
    try:
        operation = rollback if args.rollback else prepare
        report = operation(db, apply=args.apply, actor=args.actor or "")
    except AndritzShadowError as exc:
        db.rollback()
        print(json.dumps({"error": str(exc)}, sort_keys=True))
        return 2
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    structural_ready = report.get("ready") is True
    prerequisite_ready = (
        True
        if args.rollback
        else _record(report.get("prerequisite")).get("ready") is True
    )
    return 0 if structural_ready and prerequisite_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
