"""Per-workspace provisioning of the agentic chat System.

Mirrors ``ensure_workspace_chat_system_default`` for the *agentic* surface:
every active workspace owns one ``chat_agentic`` / ``chat_agentic_thinking_v1``
System rendered from ``agentic_chat_template`` with the workspace's own
profile, bound to a membrane ``ControlPolicy``, and a ``chat_execution``
policy that keeps the classic runtime in charge until an operator raises the
rollout (``hybrid`` at 0 %).

Adoption, never duplication: a workspace that already has an active agentic
System (Andritz, provisioned by migrations 048..078) keeps it.  When that
System still sits on the migration-pinned flow revision, its graph, retrieval
contract and membrane stay migration-owned — the bootstrap only records the
profile the skills read.  Any other adopted System is reconciled through
``flow_publication.reconcile_system_flow`` so operator drafts are preserved and
canvas positions survive.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import get_logger
from app.models.capability import Capability
from app.models.policy import ControlPolicy
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.chat_agentic_contract import (
    AGENTIC_SYSTEM_TYPE,
    AGENTIC_VARIANT,
    ANDRITZ_MIGRATION_FLOW_REVISION,
    TEMPLATE_FLOW_REVISION,
)
from app.services.chat_execution_policy import (
    ANDRITZ_MIGRATION_MARKER,
    CHAT_EXECUTION_HYBRID,
    migration_059_system_id,
)
from app.services.systems import flow_publication
from app.services.systems.agentic_chat_template import (
    AgenticChatProfile,
    RenderedAgenticChat,
    render,
    workspace_agentic_chat_profile,
)

logger = get_logger(__name__)

AGENTIC_CHAT_SEED_ACTOR = "system:workspace_agentic_chat_seed"
WORKSPACE_AGENTIC_CHAT_SYSTEM_NAME = "Agentium Chat Agentic"
WORKSPACE_AGENTIC_CHAT_CAPABILITY_SLUG = "workspace_assistant"
DEFAULT_CHAT_EXECUTION_SALT = "workspace-agentic-v1"
AGENTIC_EXECUTION_PROFILE = {
    "surface": "chat",
    "latency_profile": "balanced",
    "max_runtime_s": 40,
    "durability": "run_ledger",
}

# ``reconcile_system_flow`` outcomes after which the live graph IS the template.
_LIVE_FLOW_STATUSES = frozenset(
    {"legacy_no_op", "legacy_mirror_updated", "published", "published_no_op"}
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def default_chat_execution_policy() -> dict[str, Any]:
    """The policy a workspace gets when it has none: valid, targeted, inert.

    ``hybrid`` at 0 % resolves every turn to ``rollout_cohort_classic`` (or
    ``hybrid_profile_classic``), i.e. the same classic route the missing-policy
    path took, while making the agentic System selectable as an explicit canary
    and the rollout a one-field change for the workspace admin.
    """
    return {
        "version": 1,
        "mode": CHAT_EXECUTION_HYBRID,
        "target": {"system_type": AGENTIC_SYSTEM_TYPE, "variant": AGENTIC_VARIANT},
        "fallback": "classic",
        "rollout": {"percentage": 0, "salt": DEFAULT_CHAT_EXECUTION_SALT},
    }


def _is_agentic_target(system: System) -> bool:
    return (
        _as_dict(system.settings).get("system_type") == AGENTIC_SYSTEM_TYPE
        and _as_dict(system.flow_definition).get("variant") == AGENTIC_VARIANT
    )


def find_workspace_agentic_chat_system(db: DBSession, workspace: Workspace) -> Optional[System]:
    """The workspace's agentic chat System: the 059 marker's, else the oldest."""
    rows = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.status != "retired")
        .order_by(System.created_at.asc(), System.id.asc())
        .all()
    )
    targets = [row for row in rows if _is_agentic_target(row)]
    marker_id = migration_059_system_id(workspace)
    if marker_id:
        for row in targets:
            if row.id == marker_id:
                return row
    return targets[0] if targets else None


def _migration_owned(workspace: Workspace, system: System) -> bool:
    """True when migrations 048..078 own the System's graph and contract."""
    if _as_dict(system.settings).get("flow_revision") == ANDRITZ_MIGRATION_FLOW_REVISION:
        return True
    marker_id = migration_059_system_id(workspace)
    return bool(marker_id and marker_id == system.id)


def _bind_skill_ids(flow: dict[str, Any], skills: dict[str, Skill]) -> None:
    for node in flow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        slug = config.get("skill_slug")
        if slug:
            config["skill_id"] = skills[slug].id if slug in skills else None


def _membrane_columns(membrane: dict[str, Any]) -> dict[str, Any]:
    valves = _as_dict(membrane.get("valves"))
    caps = _as_dict(membrane.get("capabilities"))
    return {
        "max_cost_per_decision": valves.get("max_cost_per_decision"),
        "max_latency_ms": valves.get("max_latency_ms"),
        "mandatory_hitl_if_confidence_below": valves.get("mandatory_hitl_if_confidence_below"),
        "allowed_models": list(caps.get("allowed_models") or []),
        "allowed_skills": list(caps.get("allowed_skills") or []),
    }


def _ensure_seed_control_policy(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    rendered: RenderedAgenticChat,
) -> Optional[ControlPolicy]:
    """Bind (or refresh) the seed-owned membrane; never touch another owner's."""
    bound: Optional[ControlPolicy] = None
    if system.control_policy_id:
        bound = (
            db.query(ControlPolicy).filter(ControlPolicy.id == system.control_policy_id).first()
        )
        if bound is not None and _as_dict(bound.extra).get("membrane_origin") != AGENTIC_CHAT_SEED_ACTOR:
            return bound
    columns = _membrane_columns(rendered.membrane_spec)
    extra = {"membrane_origin": AGENTIC_CHAT_SEED_ACTOR, "membrane_spec": deepcopy(rendered.membrane_spec)}
    if bound is None:
        bound = ControlPolicy(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name=f"{system.name} Membrane",
            scope="system",
            target_id=system.id,
            extra=extra,
            **columns,
        )
        db.add(bound)
        db.flush()
        system.control_policy_id = bound.id
        return bound
    for key, value in columns.items():
        setattr(bound, key, value)
    bound.scope = "system"
    bound.target_id = system.id
    bound.extra = extra
    flag_modified(bound, "extra")
    return bound


def _profile_settings(profile: AgenticChatProfile) -> dict[str, Any]:
    return {"chat_profile": profile.to_dict(), "family": profile.family}


def _adopt_existing(
    db: DBSession,
    *,
    workspace: Workspace,
    system: System,
    capability: Capability,
    profile: AgenticChatProfile,
    rendered: RenderedAgenticChat,
    skill_ids: list[str],
) -> System:
    settings = _as_dict(system.settings)
    settings.update(_profile_settings(profile))
    settings.setdefault("system_type", AGENTIC_SYSTEM_TYPE)
    settings.setdefault("variant", AGENTIC_VARIANT)
    if _migration_owned(workspace, system):
        # Graph, retrieval contract, membrane and 059 marker stay migration
        # state; the skills only need the profile to stop hardcoding Andritz.
        system.settings = settings
        flag_modified(system, "settings")
        system.status = "active"
        logger.info(
            "workspace_agentic_chat_seed.adopted_migration_owned",
            workspace_id=workspace.id,
            system_id=system.id,
            flow_revision=settings.get("flow_revision"),
        )
        return system

    system.capability_id = system.capability_id or capability.id
    system.skill_ids = skill_ids
    system.status = "active"
    profile_settings = _as_dict(system.execution_profile)
    profile_settings.setdefault("max_runtime_s", AGENTIC_EXECUTION_PROFILE["max_runtime_s"])
    system.execution_profile = profile_settings
    system.settings = settings
    flag_modified(system, "settings")
    result = flow_publication.reconcile_system_flow(
        db,
        system=system,
        workspace=workspace,
        flow_definition=rendered.flow_definition,
        actor=AGENTIC_CHAT_SEED_ACTOR,
        publish_if_owned=True,
        ownership_prefix=AGENTIC_CHAT_SEED_ACTOR,
        message="Agentic chat template reconciliation",
    )
    if result.status in _LIVE_FLOW_STATUSES:
        settings = _as_dict(system.settings)
        settings["flow_revision"] = TEMPLATE_FLOW_REVISION
        settings["retrieval_contract"] = deepcopy(rendered.retrieval_contract)
        system.settings = settings
        flag_modified(system, "settings")
    _ensure_seed_control_policy(db, workspace=workspace, system=system, rendered=rendered)
    logger.info(
        "workspace_agentic_chat_seed.reconciled",
        workspace_id=workspace.id,
        system_id=system.id,
        flow_status=result.status,
    )
    return system


def _create_system(
    db: DBSession,
    *,
    workspace: Workspace,
    capability: Capability,
    profile: AgenticChatProfile,
    rendered: RenderedAgenticChat,
    skill_ids: list[str],
) -> System:
    label = workspace.name or workspace.slug or "the workspace"
    system = System(
        workspace_id=workspace.id,
        name=WORKSPACE_AGENTIC_CHAT_SYSTEM_NAME,
        objective=(
            f"Bounded agentic chat for {label}: plan, route retrieval, generate, "
            "evaluate and self-correct under the workspace membrane; the planner "
            "decides the model tier, the workspace routing policy the model."
        ),
        capability_id=capability.id,
        skill_ids=skill_ids,
        flow_definition=rendered.flow_definition,
        settings={
            "seed_origin": AGENTIC_CHAT_SEED_ACTOR,
            "system_type": AGENTIC_SYSTEM_TYPE,
            "variant": AGENTIC_VARIANT,
            "surface": "chat",
            "flow_revision": TEMPLATE_FLOW_REVISION,
            "retrieval_contract": deepcopy(rendered.retrieval_contract),
            **_profile_settings(profile),
        },
        execution_mode="real_time_decision",
        execution_profile=deepcopy(AGENTIC_EXECUTION_PROFILE),
        coordination_pattern="single_agent",
        status="active",
        created_by=AGENTIC_CHAT_SEED_ACTOR,
        default_prompt_type="factual",
        # No model pin: the tier the planner emits and the workspace routing
        # policy decide.  (Andritz keeps its migration pin, resolver priority 2.)
        default_model=None,
        retrieval_mode_default="auto",
    )
    db.add(system)
    db.flush()
    _ensure_seed_control_policy(db, workspace=workspace, system=system, rendered=rendered)
    flow_publication.initialize_new_system_publication_if_enabled(
        db,
        system=system,
        workspace=workspace,
        actor=AGENTIC_CHAT_SEED_ACTOR,
    )
    logger.info(
        "workspace_agentic_chat_seed.created",
        workspace_id=workspace.id,
        system_id=system.id,
        profile=profile.key,
        collection=profile.collection_slug,
    )
    return system


def _dedupe_seeded_agentic_systems(db: DBSession, workspace_id: str) -> int:
    """Keep the oldest seed-created agentic chat; retire concurrent twins."""
    rows = (
        db.query(System)
        .filter(
            System.workspace_id == workspace_id,
            System.status != "retired",
            System.created_by == AGENTIC_CHAT_SEED_ACTOR,
        )
        .order_by(System.created_at.asc(), System.id.asc())
        .all()
    )
    twins = [row for row in rows if _is_agentic_target(row)]
    for row in twins[1:]:
        row.status = "retired"
    if len(twins) > 1:
        logger.info(
            "workspace_agentic_chat_seed.dedupe.retired",
            workspace_id=workspace_id,
            retired=len(twins) - 1,
            kept=twins[0].id,
        )
    return max(0, len(twins) - 1)


def ensure_default_chat_execution(db: DBSession, workspace: Workspace) -> bool:
    """Write the inert default policy on a workspace that has none.

    Existing policies — including the Andritz ``agentic_default`` the 059
    migration owns — are never rewritten here; that is the rollout service's job.
    """
    settings = _as_dict(workspace.settings)
    if isinstance(settings.get("chat_execution"), dict) and settings["chat_execution"]:
        return False
    if ANDRITZ_MIGRATION_MARKER in settings:
        return False
    settings["chat_execution"] = default_chat_execution_policy()
    workspace.settings = settings
    flag_modified(workspace, "settings")
    logger.info("workspace_agentic_chat_seed.chat_execution.defaulted", workspace_id=workspace.id)
    return True


def ensure_workspace_agentic_chat_system_default(
    db: DBSession, workspace_id: str
) -> Optional[System]:
    """Create or adopt the workspace's agentic chat System (idempotent)."""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if workspace is None:
        return None
    capability = (
        db.query(Capability)
        .filter(Capability.slug == WORKSPACE_AGENTIC_CHAT_CAPABILITY_SLUG)
        .first()
    )
    if capability is None:
        logger.warning(
            "workspace_agentic_chat_seed.skip.missing_capability",
            workspace_id=workspace_id,
            slug=WORKSPACE_AGENTIC_CHAT_CAPABILITY_SLUG,
        )
        return None

    profile = workspace_agentic_chat_profile(workspace, db=db)
    rendered = render(profile)
    skills = {
        skill.slug: skill
        for skill in db.query(Skill).filter(Skill.slug.in_(rendered.skill_slugs)).all()
    }
    missing = [slug for slug in rendered.skill_slugs if slug not in skills]
    if missing:
        logger.warning(
            "workspace_agentic_chat_seed.skip.missing_skills",
            workspace_id=workspace_id,
            missing=missing,
        )
        return None
    _bind_skill_ids(rendered.flow_definition, skills)
    skill_ids = [skills[slug].id for slug in rendered.skill_slugs]

    existing = find_workspace_agentic_chat_system(db, workspace)
    if existing is not None:
        system = _adopt_existing(
            db,
            workspace=workspace,
            system=existing,
            capability=capability,
            profile=profile,
            rendered=rendered,
            skill_ids=skill_ids,
        )
    else:
        system = _create_system(
            db,
            workspace=workspace,
            capability=capability,
            profile=profile,
            rendered=rendered,
            skill_ids=skill_ids,
        )
    ensure_default_chat_execution(db, workspace)
    _dedupe_seeded_agentic_systems(db, workspace_id)
    db.commit()
    db.refresh(system)
    return system


def ensure_workspace_agentic_chat_system_for_all_workspaces(db: DBSession) -> dict[str, int]:
    report = {"created": 0, "adopted": 0, "skipped": 0}
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
    )
    for workspace in workspaces:
        before = find_workspace_agentic_chat_system(db, workspace)
        try:
            system = ensure_workspace_agentic_chat_system_default(db, workspace.id)
        except Exception as exc:  # noqa: BLE001 - one workspace must not block the fleet
            db.rollback()
            logger.warning(
                "workspace_agentic_chat_seed.failed",
                workspace_id=workspace.id,
                error=str(exc),
            )
            report["skipped"] += 1
            continue
        if system is None:
            report["skipped"] += 1
        elif before is None:
            report["created"] += 1
        else:
            report["adopted"] += 1
    return report
