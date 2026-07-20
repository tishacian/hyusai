"""Workspace-owned routing policy for the canonical ``/chat`` surface.

The Workspace Chat System remains the owner of sessions, assistant defaults and
the public URL.  This module only decides which runtime executes a knowledge
turn: the hardened classic orchestrator or an active run-engine DAG System.

``ENABLE_AGENTIC_CHAT`` is deliberately a master kill switch, not product
configuration.  Product rollout lives in ``workspace.settings.chat_execution``
and is stable per session so one conversation never oscillates between arms.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection
from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chat_agentic_contract import is_expected_agentic_flow
from app.services.systems.bootstrap import WORKSPACE_CHAT_VARIANT

CHAT_EXECUTION_CLASSIC = "classic"
CHAT_EXECUTION_HYBRID = "hybrid"
CHAT_EXECUTION_AGENTIC_DEFAULT = "agentic_default"
CHAT_EXECUTION_MODES = frozenset(
    {
        CHAT_EXECUTION_CLASSIC,
        CHAT_EXECUTION_HYBRID,
        CHAT_EXECUTION_AGENTIC_DEFAULT,
    }
)
AGENTIC_SYSTEM_TYPE = "chat_agentic"
AGENTIC_VARIANT = "chat_agentic_thinking_v1"
ANDRITZ_MIGRATION_MARKER = "_migration_059_andritz_agentic_default_state"
ANDRITZ_MIGRATION_REVISION = "059_andritz_agentic_default"
ANDRITZ_NOTICES_COLLECTION = "andritz-notices-techniques-spl-pilot"
ANDRITZ_RETRIEVAL_CONTRACT = {
    "collection": ANDRITZ_NOTICES_COLLECTION,
    "asset_binding": "authoritative",
    "empty_bound_collection": "abstain",
    "allow_workspace_fallback": False,
}
AGENTIC_NICHE_PROFILES = frozenset(
    {"transversal_inventory", "comparison", "equipment_detail", "table_extract", "multi_hop"}
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def migration_059_system_id(workspace: Workspace) -> Optional[str]:
    """Return the migration-owned System id independently of mutable family."""

    marker = _as_dict(_as_dict(workspace.settings).get(ANDRITZ_MIGRATION_MARKER))
    system_id = marker.get("system_id")
    if (
        marker.get("revision") != ANDRITZ_MIGRATION_REVISION
        or marker.get("schema") != 1
        or not isinstance(system_id, str)
        or not system_id
    ):
        return None
    return system_id


def migration_059_control_policy_id(workspace: Workspace) -> Optional[str]:
    """Return the migration-owned membrane id without trusting family drift."""

    if migration_059_system_id(workspace) is None:
        return None
    policy_id = _as_dict(
        _as_dict(_as_dict(workspace.settings).get(ANDRITZ_MIGRATION_MARKER)).get("control_policy")
    ).get("id")
    return policy_id if isinstance(policy_id, str) and policy_id else None


def _bounded_percentage(value: Any) -> float:
    try:
        percentage = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, percentage))


def _andritz_classic_retrieval_contract(
    workspace: Workspace,
    *,
    context_id: Optional[str],
) -> Optional[dict[str, Any]]:
    """Keep ordinary Andritz classic turns inside the authoritative corpus.

    The collection boundary belongs to the workspace experience, not only to
    the Agentic runtime.  Consequently a zero-percent rollout, kill switch or
    drift fallback must never silently widen retrieval to every collection in
    the workspace.  An explicit user-selected Context retains its existing
    classic semantics.  A RAG mode override only selects the retrieval
    algorithm and must never change the authoritative collection boundary.
    """

    workspace_settings = _as_dict(workspace.settings)
    is_andritz_contract = bool(
        workspace_settings.get("family") == "andritz"
        or ANDRITZ_MIGRATION_MARKER in workspace_settings
    )
    if not is_andritz_contract or context_id:
        return None
    return deepcopy(ANDRITZ_RETRIEVAL_CONTRACT)


def _stable_bucket(*, workspace_id: str, cohort_key: str, salt: str) -> float:
    digest = hashlib.sha256(f"{workspace_id}:{cohort_key}:{salt}".encode("utf-8")).digest()
    # 10k buckets keep rollout stable and sufficiently fine-grained while the
    # public value remains an intuitive percentage in [0, 100).
    return int.from_bytes(digest[:4], "big") % 10_000 / 100.0


@dataclass(frozen=True)
class ChatExecutionDecision:
    """Immutable routing decision persisted on every attempted Agentic Run."""

    route: str
    reason: str
    mode: str
    policy_version: int
    executor_system: Optional[System] = None
    rollout_percentage: float = 0.0
    rollout_bucket: Optional[float] = None
    fallback: str = CHAT_EXECUTION_CLASSIC
    forced: bool = False
    retrieval_contract: Optional[dict[str, Any]] = None

    @property
    def is_agentic(self) -> bool:
        return self.route == "agentic" and self.executor_system is not None

    def ledger(self) -> dict[str, Any]:
        target = self.executor_system
        target_settings = _as_dict(getattr(target, "settings", None)) if target else {}
        return {
            "policy_version": self.policy_version,
            "mode": self.mode,
            "route": self.route,
            "reason": self.reason,
            "rollout_percentage": self.rollout_percentage,
            "rollout_bucket": self.rollout_bucket,
            "fallback": self.fallback,
            "forced": self.forced,
            "executor_system_id": getattr(target, "id", None),
            "executor_variant": (
                _as_dict(getattr(target, "flow_definition", None)).get("variant")
                if target
                else None
            ),
            "flow_revision": target_settings.get("flow_revision"),
        }


def _active_agentic_targets(
    db: DBSession,
    *,
    workspace_id: str,
    system_type: str,
    variant: str,
) -> list[System]:
    rows = (
        db.query(System)
        .filter(System.workspace_id == workspace_id, System.status == "active")
        .order_by(System.created_at.asc())
        .all()
    )
    return [
        row
        for row in rows
        if _as_dict(row.settings).get("system_type") == system_type
        and _as_dict(row.flow_definition).get("variant") == variant
    ]


def _requested_agentic_system(
    db: DBSession,
    *,
    workspace_id: str,
    requested_system_id: Optional[str],
    system_type: str,
    variant: str,
) -> Optional[System]:
    if not requested_system_id:
        return None
    row = (
        db.query(System)
        .filter(
            System.id == requested_system_id,
            System.workspace_id == workspace_id,
            System.status == "active",
        )
        .first()
    )
    if row is None:
        return None
    if (
        _as_dict(row.settings).get("system_type") == system_type
        and _as_dict(row.flow_definition).get("variant") == variant
    ):
        return row
    return None


def _andritz_contract_is_valid(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
) -> bool:
    """Fail closed when a migration-managed tenant boundary has drifted."""

    workspace_settings = _as_dict(workspace.settings)
    migration_marker_present = ANDRITZ_MIGRATION_MARKER in workspace_settings
    if workspace_settings.get("family") != "andritz" and not migration_marker_present:
        return True
    marker = _as_dict(workspace_settings.get(ANDRITZ_MIGRATION_MARKER))
    if (
        workspace_settings.get("family") != "andritz"
        or marker.get("revision") != ANDRITZ_MIGRATION_REVISION
        or marker.get("schema") != 1
        or marker.get("system_id") != system.id
    ):
        return False
    system_settings = _as_dict(system.settings)
    if not is_expected_agentic_flow(system_settings, system.flow_definition):
        return False
    if system_settings.get("retrieval_contract") != ANDRITZ_RETRIEVAL_CONTRACT:
        return False
    profile = _as_dict(system.execution_profile)
    if profile.get("max_runtime_s") != 40:
        return False
    marker_policy = _as_dict(marker.get("control_policy"))
    if not system.control_policy_id or marker_policy.get("id") != system.control_policy_id:
        return False
    policy = (
        db.query(ControlPolicy)
        .filter(
            ControlPolicy.id == system.control_policy_id,
            ControlPolicy.workspace_id == workspace.id,
            ControlPolicy.scope == "system",
            ControlPolicy.target_id == system.id,
        )
        .first()
    )
    if policy is None:
        return False
    collection = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            KnowledgeCollection.slug == ANDRITZ_NOTICES_COLLECTION,
            KnowledgeCollection.status == "ready",
            KnowledgeCollection.chunk_count > 0,
        )
        .first()
    )
    if collection is None:
        return False
    extra = _as_dict(policy.extra)
    membrane = _as_dict(extra.get("membrane_spec"))
    inbound = _as_dict(membrane.get("inbound"))
    return inbound.get("collection_allowlist") == [ANDRITZ_NOTICES_COLLECTION]


def resolve_chat_execution(
    db: DBSession,
    *,
    workspace: Workspace,
    requested_system_id: Optional[str],
    session_id: Optional[str],
    answer_profile: Optional[str],
    context_id: Optional[str] = None,
    rag_mode_override: Optional[str] = None,
    allow_forced_agentic: bool = False,
) -> ChatExecutionDecision:
    """Resolve one stable execution decision for a chat turn.

    Missing/malformed policy, an ambiguous target, or any unsupported explicit
    Context/RAG override fail closed to classic.  Selecting the active Agentic
    System explicitly is the operator canary escape hatch and bypasses rollout
    percentage, but never bypasses the global kill switch.
    """

    classic_retrieval_contract = _andritz_classic_retrieval_contract(
        workspace,
        context_id=context_id,
    )

    if not bool(getattr(settings, "enable_agentic_chat", False)):
        return ChatExecutionDecision(
            route="classic",
            reason="master_kill_switch_off",
            mode=CHAT_EXECUTION_CLASSIC,
            policy_version=1,
            retrieval_contract=classic_retrieval_contract,
        )

    raw_policy = _as_dict(_as_dict(workspace.settings).get("chat_execution"))
    try:
        version = int(raw_policy.get("version") or 1)
    except (TypeError, ValueError):
        version = 1
    mode = str(raw_policy.get("mode") or "").strip()
    target_cfg = _as_dict(raw_policy.get("target"))
    system_type = str(target_cfg.get("system_type") or "").strip()
    variant = str(target_cfg.get("variant") or "").strip()
    rollout = _as_dict(raw_policy.get("rollout"))
    fallback = str(raw_policy.get("fallback") or "").strip()
    salt = str(rollout.get("salt") or "").strip()
    try:
        percentage = float(rollout.get("percentage"))
        valid_percentage = 0.0 <= percentage <= 100.0
    except (TypeError, ValueError):
        percentage = 0.0
        valid_percentage = False
    if (
        mode not in CHAT_EXECUTION_MODES
        or not system_type
        or not variant
        or fallback != CHAT_EXECUTION_CLASSIC
        or not salt
        or not valid_percentage
    ):
        return ChatExecutionDecision(
            route="classic",
            reason="policy_missing_or_invalid",
            mode=CHAT_EXECUTION_CLASSIC,
            policy_version=version,
            retrieval_contract=classic_retrieval_contract,
        )

    requested_system: Optional[System] = None
    if requested_system_id:
        requested_system = (
            db.query(System)
            .filter(
                System.id == requested_system_id,
                System.workspace_id == workspace.id,
                System.status == "active",
            )
            .first()
        )
        if requested_system is None:
            return ChatExecutionDecision(
                route="classic",
                reason="explicit_system_missing",
                mode=mode,
                policy_version=version,
                fallback=fallback,
                retrieval_contract=classic_retrieval_contract,
            )
        requested_settings = _as_dict(requested_system.settings)
        requested_flow = _as_dict(requested_system.flow_definition)
        is_workspace_chat_surface = bool(
            requested_settings.get("system_type") == "workspace_chat"
            or requested_flow.get("variant") == WORKSPACE_CHAT_VARIANT
        )
        is_declared_agentic_target = bool(
            requested_settings.get("system_type") == system_type
            and requested_flow.get("variant") == variant
        )
        if not is_workspace_chat_surface and not is_declared_agentic_target:
            return ChatExecutionDecision(
                route="classic",
                reason="explicit_business_system_requires_classic",
                mode=mode,
                policy_version=version,
                fallback=fallback,
            )

    explicit_target = (
        _requested_agentic_system(
            db,
            workspace_id=workspace.id,
            requested_system_id=requested_system_id,
            system_type=system_type,
            variant=variant,
        )
        if allow_forced_agentic
        else None
    )
    targets = _active_agentic_targets(
        db,
        workspace_id=workspace.id,
        system_type=system_type,
        variant=variant,
    )
    workspace_settings = _as_dict(workspace.settings)
    if (
        workspace_settings.get("family") == "andritz"
        or ANDRITZ_MIGRATION_MARKER in workspace_settings
    ):
        marker_system_id = migration_059_system_id(workspace)
        targets = [item for item in targets if item.id == marker_system_id]
    if explicit_target is not None:
        target = explicit_target
        forced = True
    elif len(targets) != 1:
        return ChatExecutionDecision(
            route="classic",
            reason="agentic_target_missing" if not targets else "agentic_target_ambiguous",
            mode=mode,
            policy_version=version,
            fallback=fallback,
            retrieval_contract=classic_retrieval_contract,
        )
    else:
        target = targets[0]
        forced = False

    if not _andritz_contract_is_valid(db, workspace=workspace, system=target):
        return ChatExecutionDecision(
            route="classic",
            reason="andritz_agentic_contract_invalid",
            mode=mode,
            policy_version=version,
            fallback=fallback,
            retrieval_contract=classic_retrieval_contract,
        )

    # The current Agentic graph is bound to its declared collection.  A user
    # selected Context or RAG algorithm is an explicit contract the DAG does
    # not yet model, so preserve it through the classic runtime.
    if context_id:
        return ChatExecutionDecision(
            route="classic",
            reason="explicit_context_requires_classic",
            mode=mode,
            policy_version=version,
            executor_system=target,
            fallback=fallback,
            forced=forced,
            retrieval_contract=classic_retrieval_contract,
        )
    if rag_mode_override and str(rag_mode_override).lower() not in {"", "auto"}:
        return ChatExecutionDecision(
            route="classic",
            reason="explicit_rag_override_requires_classic",
            mode=mode,
            policy_version=version,
            executor_system=target,
            fallback=fallback,
            forced=forced,
            retrieval_contract=classic_retrieval_contract,
        )

    if mode == CHAT_EXECUTION_CLASSIC and not forced:
        return ChatExecutionDecision(
            route="classic",
            reason="policy_classic",
            mode=mode,
            policy_version=version,
            executor_system=target,
            fallback=fallback,
            retrieval_contract=classic_retrieval_contract,
        )
    if (
        mode == CHAT_EXECUTION_HYBRID
        and answer_profile not in AGENTIC_NICHE_PROFILES
        and not forced
    ):
        return ChatExecutionDecision(
            route="classic",
            reason="hybrid_profile_classic",
            mode=mode,
            policy_version=version,
            executor_system=target,
            fallback=fallback,
            retrieval_contract=classic_retrieval_contract,
        )

    percentage = _bounded_percentage(percentage)
    bucket = _stable_bucket(
        workspace_id=workspace.id,
        cohort_key=str(session_id or "no-session"),
        salt=salt,
    )
    if not forced and bucket >= percentage:
        return ChatExecutionDecision(
            route="classic",
            reason="rollout_cohort_classic",
            mode=mode,
            policy_version=version,
            executor_system=target,
            rollout_percentage=percentage,
            rollout_bucket=bucket,
            fallback=fallback,
            retrieval_contract=classic_retrieval_contract,
        )

    return ChatExecutionDecision(
        route="agentic",
        reason="explicit_agentic_system" if forced else f"policy_{mode}",
        mode=mode,
        policy_version=version,
        executor_system=target,
        rollout_percentage=percentage,
        rollout_bucket=bucket,
        fallback=fallback,
        forced=forced,
        retrieval_contract=deepcopy(_as_dict(_as_dict(target.settings).get("retrieval_contract"))),
    )
