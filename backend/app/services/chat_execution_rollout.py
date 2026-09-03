"""Workspace-owned rollout of the agentic chat: mode + percentage, guarded.

``chat_execution`` is a managed workspace setting (the generic settings PATCH
refuses to touch it).  This service is the one writer: it validates the
invariants a routing decision relies on, stages the new policy and its audit
row, and leaves the commit to the caller (API request or CLI transaction).

Generic invariants (every workspace):

* master kill switch ``ENABLE_AGENTIC_CHAT`` on for any rollout above zero;
* exactly one active agentic target (``chat_agentic`` /
  ``chat_agentic_thinking_v1``) whose flow matches its declared contract
  (``is_expected_agentic_flow``) and carries a bound membrane ``ControlPolicy``;
* when the target's retrieval contract binds a collection, that collection is
  ``ready`` with indexed chunks.

Andritz plugin: a workspace carrying the migration-059 marker is validated by
``andritz_agentic_rollout`` (strict notices contract, marker identity,
immutable ``agentic_default`` mode); only its percentage may move here.
Rolling back to 0 % is always accepted as risk reduction — drifted
invariants are recorded on the audit row instead of blocking.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings as app_settings
from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.workspace import Workspace
from app.services.andritz_agentic_rollout import (
    MIGRATION_MARKER_KEY as ANDRITZ_MARKER_KEY,
)
from app.services.andritz_agentic_rollout import (
    MIGRATION_REVISION as ANDRITZ_MIGRATION_REVISION,
)
from app.services.andritz_agentic_rollout import (
    RolloutInvariantError,
    normalize_percentage,
)
from app.services.chat_agentic_contract import (
    AGENTIC_SYSTEM_TYPE,
    AGENTIC_VARIANT,
    is_expected_agentic_flow,
)
from app.services.chat_execution_policy import (
    CHAT_EXECUTION_AGENTIC_DEFAULT,
    CHAT_EXECUTION_CLASSIC,
    CHAT_EXECUTION_MODES,
    migration_059_system_id,
)

AUDIT_EVENT_TYPE = "chat.execution.rollout.updated"
DEFAULT_SALT = "workspace-agentic-v1"

__all__ = [
    "AUDIT_EVENT_TYPE",
    "ChatExecutionState",
    "RolloutInvariantError",
    "describe_chat_execution",
    "set_chat_execution",
]


@dataclass(frozen=True)
class ChatExecutionState:
    workspace_id: str
    workspace_slug: str
    mode: str
    percentage: int | float
    fallback: str
    salt: str
    policy_version: int
    managed_by: str  # "workspace" | "andritz_migration_059"
    agentic_kill_switch_enabled: bool
    target_system_id: Optional[str] = None
    target_system_name: Optional[str] = None
    control_policy_id: Optional[str] = None
    flow_revision: Optional[str] = None
    contract_valid: bool = False
    collection_slug: Optional[str] = None
    collection_status: Optional[str] = None
    collection_chunk_count: Optional[int] = None
    invariants: tuple[str, ...] = ()
    changed: bool = False
    audit_event_id: Optional[str] = None

    @property
    def rollout_ready(self) -> bool:
        return not self.invariants

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["invariants"] = list(self.invariants)
        data["rollout_ready"] = self.rollout_ready
        data["modes"] = sorted(CHAT_EXECUTION_MODES)
        return data


@dataclass
class _Target:
    system: Optional[System] = None
    control_policy: Optional[ControlPolicy] = None
    collection: Optional[KnowledgeCollection] = None
    collection_slug: Optional[str] = None
    invariants: list[str] = field(default_factory=list)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _is_andritz_managed(workspace: Workspace) -> bool:
    return ANDRITZ_MARKER_KEY in _as_dict(workspace.settings)


def _current_policy(workspace: Workspace) -> dict[str, Any]:
    return _as_dict(_as_dict(workspace.settings).get("chat_execution"))


def _current_percentage(policy: Mapping[str, Any]) -> int | float:
    try:
        return normalize_percentage(_as_dict(policy.get("rollout")).get("percentage"))
    except ValueError:
        return 0


def _agentic_targets(db: DBSession, workspace: Workspace) -> list[System]:
    rows = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.status == "active")
        .order_by(System.created_at.asc(), System.id.asc())
        .all()
    )
    targets = [
        row
        for row in rows
        if _as_dict(row.settings).get("system_type") == AGENTIC_SYSTEM_TYPE
        and _as_dict(row.flow_definition).get("variant") == AGENTIC_VARIANT
    ]
    marker_id = migration_059_system_id(workspace)
    if marker_id:
        targets = [row for row in targets if row.id == marker_id]
    return targets


def _inspect_target(db: DBSession, workspace: Workspace) -> _Target:
    """Collect the generic invariants as messages; never raises."""
    found = _Target()
    targets = _agentic_targets(db, workspace)
    if not targets:
        found.invariants.append("no active agentic chat System (chat_agentic / chat_agentic_thinking_v1)")
        return found
    if len(targets) > 1:
        found.invariants.append(
            f"{len(targets)} active agentic chat Systems; exactly one is required"
        )
        return found
    system = targets[0]
    found.system = system
    system_settings = _as_dict(system.settings)
    if not is_expected_agentic_flow(system_settings, system.flow_definition):
        found.invariants.append(
            f"system {system.id} flow does not match its declared contract "
            f"(flow_revision={system_settings.get('flow_revision')!r})"
        )
    if not system.control_policy_id:
        found.invariants.append(f"system {system.id} has no bound membrane ControlPolicy")
    else:
        policy = (
            db.query(ControlPolicy).filter(ControlPolicy.id == system.control_policy_id).first()
        )
        if policy is None or policy.workspace_id != workspace.id:
            found.invariants.append(f"system {system.id} bound ControlPolicy does not exist")
        elif policy.scope != "system" or policy.target_id != system.id:
            found.invariants.append(
                f"control policy {policy.id} is not bound to system {system.id}"
            )
        else:
            found.control_policy = policy
    contract = _as_dict(system_settings.get("retrieval_contract"))
    collection_slug = contract.get("collection")
    if isinstance(collection_slug, str) and collection_slug.strip():
        found.collection_slug = collection_slug
        collection = (
            db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.workspace_id == workspace.id,
                KnowledgeCollection.slug == collection_slug,
            )
            .first()
        )
        found.collection = collection
        if collection is None:
            found.invariants.append(f"bound collection {collection_slug} is missing")
        else:
            if collection.status != "ready":
                found.invariants.append(
                    f"bound collection {collection_slug} is not ready (status={collection.status})"
                )
            if not isinstance(collection.chunk_count, int) or collection.chunk_count <= 0:
                found.invariants.append(f"bound collection {collection_slug} has no indexed chunks")
    return found


def _state(
    workspace: Workspace,
    policy: Mapping[str, Any],
    target: _Target,
    *,
    extra_invariants: tuple[str, ...] = (),
    changed: bool = False,
    audit_event_id: Optional[str] = None,
) -> ChatExecutionState:
    rollout = _as_dict(policy.get("rollout"))
    try:
        version = int(policy.get("version") or 1)
    except (TypeError, ValueError):
        version = 1
    system = target.system
    return ChatExecutionState(
        workspace_id=workspace.id,
        workspace_slug=str(workspace.slug or ""),
        mode=str(policy.get("mode") or CHAT_EXECUTION_CLASSIC),
        percentage=_current_percentage(policy),
        fallback=str(policy.get("fallback") or CHAT_EXECUTION_CLASSIC),
        salt=str(rollout.get("salt") or ""),
        policy_version=version,
        managed_by="andritz_migration_059" if _is_andritz_managed(workspace) else "workspace",
        agentic_kill_switch_enabled=bool(getattr(app_settings, "enable_agentic_chat", False)),
        target_system_id=system.id if system is not None else None,
        target_system_name=system.name if system is not None else None,
        control_policy_id=target.control_policy.id if target.control_policy is not None else None,
        flow_revision=(_as_dict(system.settings).get("flow_revision") if system is not None else None),
        contract_valid=bool(
            system is not None and is_expected_agentic_flow(system.settings, system.flow_definition)
        ),
        collection_slug=target.collection_slug,
        collection_status=target.collection.status if target.collection is not None else None,
        collection_chunk_count=(
            target.collection.chunk_count if target.collection is not None else None
        ),
        invariants=tuple(dict.fromkeys([*target.invariants, *extra_invariants])),
        changed=changed,
        audit_event_id=audit_event_id,
    )


def describe_chat_execution(db: DBSession, workspace: Workspace) -> ChatExecutionState:
    """Read-only view of the policy, its target and what would block a rollout."""
    target = _inspect_target(db, workspace)
    extra: list[str] = []
    if not bool(getattr(app_settings, "enable_agentic_chat", False)):
        extra.append("ENABLE_AGENTIC_CHAT is disabled (master kill switch)")
    if _is_andritz_managed(workspace):
        try:
            from app.services import andritz_agentic_rollout as andritz

            marker = andritz._marker_for(workspace)  # noqa: SLF001 - plugin contract
            if marker is not None:
                andritz._validate_workspace(  # noqa: SLF001
                    db, workspace, marker, require_ready_collection=True
                )
        except RolloutInvariantError as exc:
            extra.append(str(exc))
    return _state(workspace, _current_policy(workspace), target, extra_invariants=tuple(extra))


def _validate_andritz(
    db: DBSession,
    workspace: Workspace,
    *,
    mode: str,
    percentage: int | float,
) -> tuple[str, ...]:
    """Plugin: migration-owned Andritz invariants; returns degraded messages on rollback."""
    from app.services import andritz_agentic_rollout as andritz

    if mode != CHAT_EXECUTION_AGENTIC_DEFAULT:
        raise RolloutInvariantError(
            f"workspace {workspace.slug} chat execution is owned by migration "
            f"{ANDRITZ_MIGRATION_REVISION}: mode stays '{CHAT_EXECUTION_AGENTIC_DEFAULT}', "
            "only the rollout percentage may change"
        )
    if percentage == 0:
        marker, degraded = andritz._rollback_marker_for(workspace)  # noqa: SLF001
        if marker is None:
            raise RolloutInvariantError(f"workspace {workspace.slug} has no migration 059 marker")
        validated = andritz._validate_workspace_for_rollback(  # noqa: SLF001
            db, workspace, marker, degraded
        )
        return tuple(validated.degraded_invariants)
    marker = andritz._marker_for(workspace)  # noqa: SLF001
    if marker is None:
        raise RolloutInvariantError(f"workspace {workspace.slug} has no migration 059 marker")
    andritz._validate_workspace(db, workspace, marker, require_ready_collection=True)  # noqa: SLF001
    return ()


def set_chat_execution(
    db: DBSession,
    workspace: Workspace,
    *,
    mode: str,
    percentage: int | float,
    actor: str,
    dry_run: bool = False,
) -> ChatExecutionState:
    """Validate, then stage the workspace's new chat execution policy + audit row.

    Does not commit.  Raises ``ValueError`` on malformed input and
    ``RolloutInvariantError`` when the workspace cannot safely carry the
    requested rollout.
    """
    requested_mode = str(mode or "").strip()
    if requested_mode not in CHAT_EXECUTION_MODES:
        raise ValueError(f"mode must be one of {sorted(CHAT_EXECUTION_MODES)}")
    requested_percentage = normalize_percentage(percentage)
    normalized_actor = str(actor or "").strip()
    if not normalized_actor:
        raise ValueError("actor must not be empty")
    if len(normalized_actor) > 255:
        raise ValueError("actor must not exceed 255 characters")

    routes_agentic = requested_mode != CHAT_EXECUTION_CLASSIC and requested_percentage > 0
    kill_switch = bool(getattr(app_settings, "enable_agentic_chat", False))
    if routes_agentic and not kill_switch:
        raise RolloutInvariantError("ENABLE_AGENTIC_CHAT is disabled; refusing a rollout above zero")

    # Lock the workspace row so two admins cannot interleave policy writes.
    locked = (
        db.query(Workspace)
        .filter(Workspace.id == workspace.id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    current = _current_policy(locked)
    previous_percentage = _current_percentage(current)
    previous_mode = str(current.get("mode") or "")

    degraded: tuple[str, ...] = ()
    if _is_andritz_managed(locked):
        degraded = _validate_andritz(
            db, locked, mode=requested_mode, percentage=requested_percentage
        )
        target = _inspect_target(db, locked)
    else:
        target = _inspect_target(db, locked)
        if routes_agentic and target.invariants:
            raise RolloutInvariantError(
                f"workspace {locked.slug} cannot roll out the agentic chat: "
                + "; ".join(target.invariants)
            )
        degraded = tuple(target.invariants) if not routes_agentic else ()

    next_policy = {
        "version": 1,
        "mode": requested_mode,
        "target": deepcopy(_as_dict(current.get("target")))
        or {"system_type": AGENTIC_SYSTEM_TYPE, "variant": AGENTIC_VARIANT},
        "fallback": CHAT_EXECUTION_CLASSIC,
        "rollout": {
            "percentage": requested_percentage,
            "salt": str(_as_dict(current.get("rollout")).get("salt") or DEFAULT_SALT),
        },
    }
    if _is_andritz_managed(locked):
        # The 059 policy is immutable apart from its percentage.
        next_policy = deepcopy(current)
        next_policy.setdefault("rollout", {})["percentage"] = requested_percentage
    changed = next_policy != current

    audit_id: Optional[str] = None
    if not dry_run:
        workspace_settings = deepcopy(dict(locked.settings or {}))
        workspace_settings["chat_execution"] = next_policy
        locked.settings = workspace_settings
        flag_modified(locked, "settings")
        if workspace is not locked:
            workspace.settings = workspace_settings

        audit_id = str(uuid4())
        details: dict[str, Any] = {
            "policy_version": 1,
            "managed_by": "andritz_migration_059" if _is_andritz_managed(locked) else "workspace",
            "target": {
                "system_type": AGENTIC_SYSTEM_TYPE,
                "variant": AGENTIC_VARIANT,
                "system_id": target.system.id if target.system is not None else None,
            },
            "previous_mode": previous_mode,
            "mode": requested_mode,
            "previous_percentage": previous_percentage,
            "percentage": requested_percentage,
            "changed": changed,
            "retrieval_collection": target.collection_slug,
            "collection_status": (
                target.collection.status if target.collection is not None else None
            ),
            "collection_chunk_count": (
                target.collection.chunk_count if target.collection is not None else None
            ),
            "flow_revision": (
                _as_dict(target.system.settings).get("flow_revision")
                if target.system is not None
                else None
            ),
            "agentic_kill_switch_enabled": kill_switch,
            "control_policy_id": (
                target.control_policy.id if target.control_policy is not None else None
            ),
        }
        if _is_andritz_managed(locked):
            details["migration_revision"] = ANDRITZ_MIGRATION_REVISION
        if degraded:
            details["validation_mode"] = "risk_reduction_rollback"
            details["degraded_invariants"] = list(degraded)
        db.add(
            AuditLog(
                id=audit_id,
                workspace_id=locked.id,
                timestamp=datetime.utcnow(),
                event_type=AUDIT_EVENT_TYPE,
                actor=normalized_actor,
                severity="warning" if degraded else "info",
                agent_id=target.system.id if target.system is not None else None,
                details=details,
            )
        )
        db.flush()

    return _state(
        locked,
        next_policy,
        target,
        extra_invariants=degraded,
        changed=changed,
        audit_event_id=audit_id,
    )
