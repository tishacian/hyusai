"""Safe rollout control for the Andritz Agentic chat runtime.

Migration 059 deliberately installs the runtime at zero percent.  This module
is the only operator-facing mutation path for increasing (or rolling back)
that percentage.  Increases treat every other part of the migration contract
as immutable and fail closed on drift.  A zero-percent rollback deliberately
needs only trusted migration identity and an identifiable current percentage;
runtime and marker-envelope drift is captured in its audit instead of
stranding traffic on an unsafe target.

The caller owns the database transaction.  A successful non-dry-run call
stages both the workspace settings change and its audit row, then flushes
them together.  Committing that transaction makes the two writes atomic;
rolling it back makes neither visible.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings as app_settings
from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chat_agentic_contract import (
    EXPECTED_FLOW_REVISION,
    is_expected_agentic_flow,
)

MIGRATION_MARKER_KEY = "_migration_059_andritz_agentic_default_state"
MIGRATION_REVISION = "059_andritz_agentic_default"
MIGRATION_MARKER_SCHEMA = 1

AGENTIC_SYSTEM_TYPE = "chat_agentic"
AGENTIC_VARIANT = "chat_agentic_thinking_v1"
NOTICES_COLLECTION = "andritz-notices-techniques-spl-pilot"
ROLLOUT_SALT = "andritz-agentic-v1"
AUDIT_EVENT_TYPE = "chat.execution.rollout.updated"

STRICT_RETRIEVAL_CONTRACT = {
    "collection": NOTICES_COLLECTION,
    "asset_binding": "authoritative",
    "empty_bound_collection": "abstain",
    "allow_workspace_fallback": False,
}

_IMMUTABLE_CHAT_EXECUTION = {
    "version": 1,
    "mode": "agentic_default",
    "target": {
        "system_type": AGENTIC_SYSTEM_TYPE,
        "variant": AGENTIC_VARIANT,
    },
    "fallback": "classic",
    "rollout": {
        "percentage": 0,
        "salt": ROLLOUT_SALT,
    },
}


class RolloutInvariantError(RuntimeError):
    """Raised before rollout when a migration-owned invariant has drifted."""


@dataclass(frozen=True)
class WorkspaceRollout:
    workspace_id: str
    workspace_slug: str
    target_system_id: str
    control_policy_id: str
    previous_percentage: int | float
    percentage: int | float
    changed: bool
    flow_revision: str
    collection_status: str | None
    collection_chunk_count: int | None
    degraded_invariants: tuple[str, ...] = ()
    audit_event_id: str | None = None


@dataclass(frozen=True)
class RolloutResult:
    actor: str
    percentage: int | float
    dry_run: bool
    workspaces: tuple[WorkspaceRollout, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "percentage": self.percentage,
            "dry_run": self.dry_run,
            "agentic_kill_switch_enabled": bool(
                getattr(app_settings, "enable_agentic_chat", False)
            ),
            "workspace_count": len(self.workspaces),
            "workspaces": [asdict(item) for item in self.workspaces],
        }


@dataclass(frozen=True)
class _ValidatedWorkspace:
    workspace: Workspace
    system: System | None
    control_policy: ControlPolicy | None
    target_system_id: str
    control_policy_id: str
    collection: KnowledgeCollection | None
    previous_percentage: int | float
    degraded_invariants: tuple[str, ...] = ()


def normalize_percentage(value: Any) -> int | float:
    """Return a JSON-safe percentage, rejecting bools, NaN and infinities."""

    if isinstance(value, bool):
        raise ValueError("percentage must be a number between 0 and 100")
    try:
        percentage = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("percentage must be a number between 0 and 100") from exc
    if not math.isfinite(percentage) or not 0 <= percentage <= 100:
        raise ValueError("percentage must be a number between 0 and 100")
    return int(percentage) if percentage.is_integer() else percentage


def _mapping(value: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RolloutInvariantError(f"{path} must be a JSON object")
    return dict(value)


def _validate_snapshot(value: Any, *, path: str) -> None:
    snapshot = _mapping(value, path=path)
    state = snapshot.get("state")
    if state not in {"absent", "present"}:
        raise RolloutInvariantError(f"{path} is not a migration 059 field snapshot")
    if state == "present" and "value" not in snapshot:
        raise RolloutInvariantError(f"{path} is missing its snapshot value")


def _marker_for(workspace: Workspace) -> dict[str, Any] | None:
    # The migration marker is the durable identity.  ``family`` is validated
    # by positive rollout discovery, but must not hide a marked tenant from an
    # emergency rollback when that mutable field has drifted.
    if not isinstance(workspace.settings, Mapping):
        return None
    settings = dict(workspace.settings)
    if MIGRATION_MARKER_KEY not in settings:
        return None

    marker = _mapping(
        settings[MIGRATION_MARKER_KEY],
        path=f"workspace {workspace.id}.{MIGRATION_MARKER_KEY}",
    )
    control = _mapping(
        marker.get("control_policy"),
        path=f"workspace {workspace.id} migration marker control_policy",
    )
    workspace_snapshot = _mapping(
        marker.get("workspace"),
        path=f"workspace {workspace.id} migration marker workspace",
    )
    system_snapshot = _mapping(
        marker.get("system"),
        path=f"workspace {workspace.id} migration marker system",
    )
    profile_snapshot = _mapping(
        system_snapshot.get("execution_profile"),
        path=f"workspace {workspace.id} migration marker execution_profile",
    )
    applied = _mapping(
        marker.get("applied"),
        path=f"workspace {workspace.id} migration marker applied",
    )
    expected_applied = {
        "chat_execution": _IMMUTABLE_CHAT_EXECUTION,
        "retrieval_contract": STRICT_RETRIEVAL_CONTRACT,
        "execution_profile_max_runtime_s": 40,
        "collection_allowlist": [NOTICES_COLLECTION],
        "flow_revision": EXPECTED_FLOW_REVISION,
    }
    if (
        marker.get("revision") != MIGRATION_REVISION
        or not isinstance(marker.get("schema"), int)
        or isinstance(marker.get("schema"), bool)
        or marker.get("schema") != MIGRATION_MARKER_SCHEMA
        or not isinstance(marker.get("system_id"), str)
        or not marker["system_id"].strip()
        or not isinstance(control.get("id"), str)
        or not control["id"].strip()
        or control.get("inbound_container") not in {"absent", "mapping"}
        or profile_snapshot.get("container") not in {"null", "mapping"}
        or applied != expected_applied
    ):
        raise RolloutInvariantError(
            f"workspace {workspace.slug} has an invalid migration 059 marker"
        )
    _validate_snapshot(
        workspace_snapshot.get("chat_execution"),
        path=f"workspace {workspace.id} migration marker chat_execution snapshot",
    )
    _validate_snapshot(
        system_snapshot.get("retrieval_contract"),
        path=f"workspace {workspace.id} migration marker retrieval_contract snapshot",
    )
    _validate_snapshot(
        profile_snapshot.get("max_runtime_s"),
        path=f"workspace {workspace.id} migration marker max_runtime_s snapshot",
    )
    _validate_snapshot(
        control.get("collection_allowlist"),
        path=f"workspace {workspace.id} migration marker collection_allowlist snapshot",
    )
    return marker


def _rollback_marker_for(
    workspace: Workspace,
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    """Return trusted migration identity and audit-only marker drift.

    Rollback needs the migration revision plus target identifiers, but stale
    restore snapshots or an old ``applied`` envelope cannot be allowed to
    strand a non-zero rollout.  Those fields remain strict for every rollout
    above zero and are recorded as degraded evidence here.
    """

    if not isinstance(workspace.settings, Mapping):
        return None, ()
    settings = dict(workspace.settings)
    if MIGRATION_MARKER_KEY not in settings:
        return None, ()
    marker = _mapping(
        settings[MIGRATION_MARKER_KEY],
        path=f"workspace {workspace.id}.{MIGRATION_MARKER_KEY}",
    )
    control = _mapping(
        marker.get("control_policy"),
        path=f"workspace {workspace.id} migration marker control_policy",
    )
    if (
        marker.get("revision") != MIGRATION_REVISION
        or not isinstance(marker.get("schema"), int)
        or isinstance(marker.get("schema"), bool)
        or marker.get("schema") != MIGRATION_MARKER_SCHEMA
        or not isinstance(marker.get("system_id"), str)
        or not marker["system_id"].strip()
        or not isinstance(control.get("id"), str)
        or not control["id"].strip()
    ):
        raise RolloutInvariantError(
            f"workspace {workspace.slug} has an invalid migration 059 marker"
        )

    degraded: list[str] = []
    if settings.get("family") != "andritz":
        degraded.append(
            f"workspace {workspace.slug} family drift: expected 'andritz', "
            f"got {settings.get('family')!r}"
        )
    try:
        _marker_for(workspace)
    except RolloutInvariantError as exc:
        degraded.append(f"migration marker contract drift: {exc}")
    return marker, tuple(degraded)


def _is_exact_target(system: System) -> bool:
    return is_expected_agentic_flow(system.settings, system.flow_definition)


def _chat_execution_percentage(workspace: Workspace) -> int | float:
    settings = _mapping(workspace.settings, path=f"workspace {workspace.id}.settings")
    policy = _mapping(
        settings.get("chat_execution"),
        path=f"workspace {workspace.id}.settings.chat_execution",
    )
    rollout = _mapping(
        policy.get("rollout"),
        path=f"workspace {workspace.id}.settings.chat_execution.rollout",
    )
    try:
        percentage = normalize_percentage(rollout.get("percentage"))
    except ValueError as exc:
        raise RolloutInvariantError(
            f"workspace {workspace.slug} has an invalid current rollout percentage"
        ) from exc
    return percentage


def _validate_chat_execution(workspace: Workspace) -> int | float:
    settings = _mapping(workspace.settings, path=f"workspace {workspace.id}.settings")
    policy = _mapping(
        settings.get("chat_execution"),
        path=f"workspace {workspace.id}.settings.chat_execution",
    )
    percentage = _chat_execution_percentage(workspace)

    expected = deepcopy(_IMMUTABLE_CHAT_EXECUTION)
    expected["rollout"]["percentage"] = percentage
    if policy != expected:
        raise RolloutInvariantError(
            f"workspace {workspace.slug} chat execution policy has immutable drift"
        )
    return percentage


def _validate_system(workspace: Workspace, system: System) -> None:
    settings = _mapping(system.settings, path=f"system {system.id}.settings")
    if settings.get("retrieval_contract") != STRICT_RETRIEVAL_CONTRACT:
        raise RolloutInvariantError(
            f"system {system.id} does not have the strict Andritz notices retrieval contract"
        )
    profile = _mapping(system.execution_profile, path=f"system {system.id}.execution_profile")
    runtime = profile.get("max_runtime_s")
    if isinstance(runtime, bool) or not isinstance(runtime, int | float) or runtime != 40:
        raise RolloutInvariantError(f"system {system.id} max_runtime_s must be 40")


def _validate_control_policy(
    workspace: Workspace,
    system: System,
    control_policy: ControlPolicy,
) -> None:
    if control_policy.workspace_id != workspace.id:
        raise RolloutInvariantError(
            f"control policy {control_policy.id} is not owned by workspace {workspace.slug}"
        )
    if control_policy.scope != "system" or control_policy.target_id != system.id:
        raise RolloutInvariantError(
            f"control policy {control_policy.id} is not bound to system {system.id}"
        )
    extra = _mapping(control_policy.extra, path=f"control policy {control_policy.id}.extra")
    membrane = _mapping(
        extra.get("membrane_spec"),
        path=f"control policy {control_policy.id}.extra.membrane_spec",
    )
    inbound = _mapping(
        membrane.get("inbound"),
        path=f"control policy {control_policy.id}.extra.membrane_spec.inbound",
    )
    if inbound.get("collection_allowlist") != [NOTICES_COLLECTION]:
        raise RolloutInvariantError(
            f"control policy {control_policy.id} membrane allowlist has drifted"
        )


def _collection_for_workspace(
    db: DBSession,
    *,
    workspace: Workspace,
    required: bool,
) -> KnowledgeCollection | None:
    collection = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            KnowledgeCollection.slug == NOTICES_COLLECTION,
        )
        .with_for_update()
        .one_or_none()
    )
    if not required:
        return collection
    if collection is None:
        raise RolloutInvariantError(
            f"workspace {workspace.slug} is missing collection {NOTICES_COLLECTION}"
        )
    if collection.status != "ready":
        raise RolloutInvariantError(
            f"workspace {workspace.slug} collection {NOTICES_COLLECTION} "
            f"is not ready (status={collection.status})"
        )
    if not isinstance(collection.chunk_count, int) or collection.chunk_count <= 0:
        raise RolloutInvariantError(
            f"workspace {workspace.slug} collection {NOTICES_COLLECTION} has no indexed chunks"
        )
    return collection


def _validate_workspace(
    db: DBSession,
    workspace: Workspace,
    marker: Mapping[str, Any],
    *,
    require_ready_collection: bool,
) -> _ValidatedWorkspace:
    systems = (
        db.query(System)
        .filter(
            System.workspace_id == workspace.id,
            System.status == "active",
        )
        .with_for_update()
        .all()
    )
    targets = [system for system in systems if _is_exact_target(system)]
    if len(targets) != 1:
        raise RolloutInvariantError(
            f"workspace {workspace.slug} must have exactly one active canonical Agentic chat target"
        )
    system = targets[0]
    if marker.get("system_id") != system.id:
        raise RolloutInvariantError(
            f"workspace {workspace.slug} migration marker targets a different System"
        )

    marker_control = _mapping(
        marker.get("control_policy"),
        path=f"workspace {workspace.id} migration marker control_policy",
    )
    if system.control_policy_id != marker_control.get("id"):
        raise RolloutInvariantError(f"system {system.id} ControlPolicy binding has drifted")
    control_policy = (
        db.query(ControlPolicy)
        .filter(ControlPolicy.id == system.control_policy_id)
        .with_for_update()
        .one_or_none()
    )
    if control_policy is None:
        raise RolloutInvariantError(f"system {system.id} bound ControlPolicy does not exist")

    previous_percentage = _validate_chat_execution(workspace)
    _validate_system(workspace, system)
    _validate_control_policy(workspace, system, control_policy)
    collection = _collection_for_workspace(
        db,
        workspace=workspace,
        required=require_ready_collection,
    )
    return _ValidatedWorkspace(
        workspace=workspace,
        system=system,
        control_policy=control_policy,
        target_system_id=system.id,
        control_policy_id=control_policy.id,
        collection=collection,
        previous_percentage=previous_percentage,
    )


def _validate_workspace_for_rollback(
    db: DBSession,
    workspace: Workspace,
    marker: Mapping[str, Any],
    marker_degradations: tuple[str, ...] = (),
) -> _ValidatedWorkspace:
    """Lock rollback evidence without requiring a runnable Agentic target.

    Setting the percentage to zero is a risk-reduction operation.  Migration
    provenance and the current percentage must remain trustworthy, but a
    disabled or drifted runtime must not prevent operators from taking it out
    of traffic.  Every relaxed invariant is retained in the audit envelope.
    """

    previous_percentage = _chat_execution_percentage(workspace)
    degraded = list(marker_degradations)
    try:
        _validate_chat_execution(workspace)
    except RolloutInvariantError as exc:
        degraded.append(str(exc))

    target_system_id = str(marker["system_id"])
    marker_control = _mapping(
        marker.get("control_policy"),
        path=f"workspace {workspace.id} migration marker control_policy",
    )
    control_policy_id = str(marker_control["id"])

    system = db.query(System).filter(System.id == target_system_id).with_for_update().one_or_none()
    if system is None:
        degraded.append(f"migration target system {target_system_id} does not exist")
    else:
        if system.workspace_id != workspace.id:
            degraded.append(f"system {system.id} is not owned by workspace {workspace.slug}")
        if system.status != "active":
            degraded.append(f"system {system.id} status is {system.status!r}; expected 'active'")
        if not _is_exact_target(system):
            degraded.append(f"system {system.id} does not match the canonical Agentic chat flow")
        try:
            system_settings = _mapping(
                system.settings,
                path=f"system {system.id}.settings",
            )
            if system_settings.get("retrieval_contract") != STRICT_RETRIEVAL_CONTRACT:
                degraded.append(
                    f"system {system.id} does not have the strict Andritz notices "
                    "retrieval contract"
                )
        except RolloutInvariantError as exc:
            degraded.append(str(exc))
        try:
            profile = _mapping(
                system.execution_profile,
                path=f"system {system.id}.execution_profile",
            )
            runtime = profile.get("max_runtime_s")
            if isinstance(runtime, bool) or not isinstance(runtime, int | float) or runtime != 40:
                degraded.append(f"system {system.id} max_runtime_s must be 40")
        except RolloutInvariantError as exc:
            degraded.append(str(exc))
        if system.control_policy_id != control_policy_id:
            degraded.append(f"system {system.id} ControlPolicy binding has drifted")

    control_policy = (
        db.query(ControlPolicy)
        .filter(ControlPolicy.id == control_policy_id)
        .with_for_update()
        .one_or_none()
    )
    if control_policy is None:
        degraded.append(f"migration ControlPolicy {control_policy_id} does not exist")
    else:
        if control_policy.workspace_id != workspace.id:
            degraded.append(
                f"control policy {control_policy.id} is not owned by workspace {workspace.slug}"
            )
        if control_policy.scope != "system" or control_policy.target_id != target_system_id:
            degraded.append(
                f"control policy {control_policy.id} is not bound to system {target_system_id}"
            )
        try:
            extra = _mapping(
                control_policy.extra,
                path=f"control policy {control_policy.id}.extra",
            )
            membrane = _mapping(
                extra.get("membrane_spec"),
                path=f"control policy {control_policy.id}.extra.membrane_spec",
            )
            inbound = _mapping(
                membrane.get("inbound"),
                path=f"control policy {control_policy.id}.extra.membrane_spec.inbound",
            )
            if inbound.get("collection_allowlist") != [NOTICES_COLLECTION]:
                degraded.append(
                    f"control policy {control_policy.id} membrane allowlist has drifted"
                )
        except RolloutInvariantError as exc:
            degraded.append(str(exc))

    collection = _collection_for_workspace(db, workspace=workspace, required=False)
    if collection is None:
        degraded.append(f"workspace {workspace.slug} is missing collection {NOTICES_COLLECTION}")
    else:
        if collection.status != "ready":
            degraded.append(
                f"workspace {workspace.slug} collection {NOTICES_COLLECTION} "
                f"is not ready (status={collection.status})"
            )
        if not isinstance(collection.chunk_count, int) or collection.chunk_count <= 0:
            degraded.append(
                f"workspace {workspace.slug} collection {NOTICES_COLLECTION} "
                "has no indexed chunks"
            )
    return _ValidatedWorkspace(
        workspace=workspace,
        system=system,
        control_policy=control_policy,
        target_system_id=target_system_id,
        control_policy_id=control_policy_id,
        collection=collection,
        previous_percentage=previous_percentage,
        degraded_invariants=tuple(dict.fromkeys(degraded)),
    )


def set_andritz_agentic_rollout(
    db: DBSession,
    *,
    percentage: int | float,
    actor: str,
    dry_run: bool = False,
) -> RolloutResult:
    """Validate all marked Andritz workspaces, then stage an atomic rollout.

    The function intentionally does not commit.  The CLI wraps it in one
    transaction so a failure in any workspace (including audit persistence)
    rolls back every workspace.
    """

    requested_percentage = normalize_percentage(percentage)
    normalized_actor = str(actor or "").strip()
    if not normalized_actor:
        raise ValueError("actor must not be empty")
    if len(normalized_actor) > 255:
        raise ValueError("actor must not exceed 255 characters")
    if requested_percentage > 0 and not bool(getattr(app_settings, "enable_agentic_chat", False)):
        raise RolloutInvariantError(
            "ENABLE_AGENTIC_CHAT is disabled; refusing a rollout above zero"
        )

    # Migration 059 is rare operator state.  Locking the workspace rows before
    # filtering avoids a family/marker race between discovery and validation.
    workspaces = db.query(Workspace).order_by(Workspace.id).with_for_update().all()
    marked: list[tuple[Workspace, dict[str, Any], tuple[str, ...]]] = []
    unmarked_andritz: list[str] = []
    for workspace in workspaces:
        workspace_settings = (
            dict(workspace.settings) if isinstance(workspace.settings, Mapping) else {}
        )
        if requested_percentage == 0:
            marker, marker_degradations = _rollback_marker_for(workspace)
        else:
            marker = _marker_for(workspace)
            marker_degradations = ()
        if marker is not None:
            if requested_percentage > 0 and workspace_settings.get("family") != "andritz":
                raise RolloutInvariantError(
                    f"workspace {workspace.slug} family drift: expected 'andritz'"
                )
            marked.append((workspace, marker, marker_degradations))
        elif workspace_settings.get("family") == "andritz":
            unmarked_andritz.append(str(workspace.slug or workspace.id))
    if requested_percentage > 0 and unmarked_andritz:
        raise RolloutInvariantError(
            "family=andritz workspaces missing migration 059 marker: "
            + ", ".join(sorted(unmarked_andritz))
        )
    if not marked:
        raise RolloutInvariantError("no workspace with a valid migration 059 marker was found")

    # Validate the whole fleet before staging the first write.  The enclosing
    # transaction remains the final atomicity boundary if flush itself fails.
    if requested_percentage == 0:
        validated = [
            _validate_workspace_for_rollback(
                db,
                workspace,
                marker,
                marker_degradations,
            )
            for workspace, marker, marker_degradations in marked
        ]
    else:
        validated = [
            _validate_workspace(
                db,
                workspace,
                marker,
                require_ready_collection=True,
            )
            for workspace, marker, _marker_degradations in marked
        ]

    rows: list[WorkspaceRollout] = []
    for item in validated:
        changed = item.previous_percentage != requested_percentage
        audit_id: str | None = None
        if not dry_run:
            workspace_settings = deepcopy(dict(item.workspace.settings or {}))
            chat_execution = deepcopy(workspace_settings["chat_execution"])
            rollout = deepcopy(chat_execution["rollout"])
            rollout["percentage"] = requested_percentage
            chat_execution["rollout"] = rollout
            workspace_settings["chat_execution"] = chat_execution
            item.workspace.settings = workspace_settings
            flag_modified(item.workspace, "settings")

            audit_id = str(uuid4())
            audit_details: dict[str, Any] = {
                "migration_revision": MIGRATION_REVISION,
                "policy_version": 1,
                "target": {
                    "system_type": AGENTIC_SYSTEM_TYPE,
                    "variant": AGENTIC_VARIANT,
                    "system_id": item.target_system_id,
                },
                "previous_percentage": item.previous_percentage,
                "percentage": requested_percentage,
                "changed": changed,
                "retrieval_collection": NOTICES_COLLECTION,
                "collection_status": (
                    item.collection.status if item.collection is not None else None
                ),
                "collection_chunk_count": (
                    item.collection.chunk_count if item.collection is not None else None
                ),
                "flow_revision": EXPECTED_FLOW_REVISION,
                "agentic_kill_switch_enabled": bool(
                    getattr(app_settings, "enable_agentic_chat", False)
                ),
                "control_policy_id": item.control_policy_id,
            }
            if requested_percentage == 0:
                audit_details.update(
                    {
                        "validation_mode": "risk_reduction_rollback",
                        "degraded_invariants": list(item.degraded_invariants),
                    }
                )
            db.add(
                AuditLog(
                    id=audit_id,
                    workspace_id=item.workspace.id,
                    timestamp=datetime.utcnow(),
                    event_type=AUDIT_EVENT_TYPE,
                    actor=normalized_actor,
                    severity="warning" if item.degraded_invariants else "info",
                    agent_id=item.target_system_id,
                    details=audit_details,
                )
            )

        rows.append(
            WorkspaceRollout(
                workspace_id=item.workspace.id,
                workspace_slug=item.workspace.slug,
                target_system_id=item.target_system_id,
                control_policy_id=item.control_policy_id,
                previous_percentage=item.previous_percentage,
                percentage=requested_percentage,
                changed=changed,
                flow_revision=EXPECTED_FLOW_REVISION,
                collection_status=(item.collection.status if item.collection is not None else None),
                collection_chunk_count=(
                    item.collection.chunk_count if item.collection is not None else None
                ),
                degraded_invariants=item.degraded_invariants,
                audit_event_id=audit_id,
            )
        )

    if not dry_run:
        # Ensures settings and audit rows are both persistable before returning
        # control to the transaction owner for the single commit.
        db.flush()

    return RolloutResult(
        actor=normalized_actor,
        percentage=requested_percentage,
        dry_run=dry_run,
        workspaces=tuple(rows),
    )
