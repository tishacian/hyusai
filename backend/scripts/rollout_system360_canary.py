"""Fail-closed, staged rollout for the single System 360 canary.

Runtime discovery is marker-only: exactly one active workspace stamped with
``settings.showcase_seed`` and exactly one System carrying
``settings.experience.system_360_canary == "v1"``.  The dedicated bootstrap
selects the pre-marker candidate from structural seed metadata only.  No
workspace, Capability or System slug, name or id is encoded in either path.

Commands are dry-run by default; ``--apply`` is required for writes::

    python -m scripts.rollout_system360_canary bootstrap
    python -m scripts.rollout_system360_canary bootstrap --apply
    python -m scripts.rollout_system360_canary prepare
    python -m scripts.rollout_system360_canary prepare --apply
    python -m scripts.rollout_system360_canary activate-flow --apply
    python -m scripts.rollout_system360_canary exercise --apply --exercise-query "..."
    python -m scripts.rollout_system360_canary activate-membrane --apply
    python -m scripts.rollout_system360_canary activate-axes --apply
    python -m scripts.rollout_system360_canary activate-projection --apply
    python -m scripts.rollout_system360_canary status
    python -m scripts.rollout_system360_canary rollback --apply

``bootstrap`` links the existing structural composition, installs the five-
facet MembraneSpec v2 in shadow mode, sets the marker and keeps all feature
flags off. ``prepare`` then installs the canonical strict flow as a new
append-only SystemVersion. Later commands enforce the order above. ``exercise``
executes the real DAG and accepts only a
completed Run carrying real SkillInvocation rows, non-empty grounded citations
and one canonical Membrane provenance URI/SHA-256 pair.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.db.base import SessionLocal
from app.models.capability import Capability
from app.models.context import Context
from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.chains.version_service import record_new_version, rollback_to_version
from app.services.membrane.spec import (
    FACET_NAMES,
    EnforcementMode,
    MembraneSpec,
)

CANARY_MARKER = "v1"
ROLLOUT_STATE_KEY = "_lot6_system360_rollout_v1"
ROLLOUT_SCHEMA_VERSION = 1
EXERCISE_TRIGGER = "lot6_system360_exercise"
FEATURE_FLOW = "flow_v3_dag_authoritative"
FEATURE_AXES = "cockpit_router_axes_v4"
FEATURE_PROJECTION = "system_360_projection_v1"
ROLLOUT_FEATURES = (FEATURE_FLOW, FEATURE_AXES, FEATURE_PROJECTION)
REQUIRED_SKILLS = (
    "semantic_search_v1",
    "llm_rag_answer_v1",
    "claim_audit_v1",
    "audit_log_v1",
)
REQUIRED_NODE_IDS = ("retrieve", "answer", "claim_audit", "audit_log")
PHASES = (
    "prepared",
    "flow_active",
    "exercised",
    "membrane_active",
    "axes_active",
    "projection_active",
    "rolled_back",
)

_PHASE_FEATURE_CONTRACT = {
    "prepared": {
        FEATURE_FLOW: False,
        FEATURE_AXES: False,
        FEATURE_PROJECTION: False,
    },
    "flow_active": {
        FEATURE_FLOW: True,
        FEATURE_AXES: False,
        FEATURE_PROJECTION: False,
    },
    "exercised": {
        FEATURE_FLOW: True,
        FEATURE_AXES: False,
        FEATURE_PROJECTION: False,
    },
    "membrane_active": {
        FEATURE_FLOW: True,
        FEATURE_AXES: False,
        FEATURE_PROJECTION: False,
    },
    "axes_active": {
        FEATURE_FLOW: True,
        FEATURE_AXES: True,
        FEATURE_PROJECTION: False,
    },
    "projection_active": {
        FEATURE_FLOW: True,
        FEATURE_AXES: True,
        FEATURE_PROJECTION: True,
    },
}

_PHASE_MEMBRANE_CONTRACT = {
    "prepared": EnforcementMode.SHADOW.value,
    "flow_active": EnforcementMode.SHADOW.value,
    "exercised": EnforcementMode.SHADOW.value,
    "membrane_active": EnforcementMode.ENFORCE.value,
    "axes_active": EnforcementMode.ENFORCE.value,
    "projection_active": EnforcementMode.ENFORCE.value,
}


class RolloutError(ValueError):
    """Raised before a partial or out-of-order rollout mutation."""


def _record(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _same_json(left: Any, right: Any) -> bool:
    return _canonical_json(left) == _canonical_json(right)


def _nonempty_citations(value: Any) -> list[Any]:
    """Return substantive citations from the authoritative answer output."""

    if not isinstance(value, list):
        return []
    return [
        citation
        for citation in value
        if citation is not None
        and citation != ""
        and citation != []
        and citation != {}
    ]


def _canonical_provenance_pair(value: Any) -> tuple[str, str] | None:
    """Validate the immutable URI/checksum pair emitted by Membrane v2."""

    evidence = _record(value)
    uri = evidence.get("uri")
    sha256 = evidence.get("sha256")
    if (
        not isinstance(uri, str)
        or not uri.startswith("object://")
        or len(uri) <= len("object://")
        or not isinstance(sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
    ):
        return None
    return uri, sha256


def _phase_index(phase: str) -> int:
    try:
        return PHASES.index(phase)
    except ValueError as exc:
        raise RolloutError(f"unknown rollout phase: {phase!r}") from exc


def canonical_strict_flow() -> dict[str, Any]:
    """Return the versioned strict flow shared with the canonical seed.

    Importing lazily keeps this CLI testable without running the seed.  The
    structural assertions below make a future seed edit fail closed instead of
    silently changing the production rollout contract.
    """

    from scripts.seed_showcase_workspace import flow_contract_risk_system360

    flow = copy.deepcopy(flow_contract_risk_system360())
    nodes = flow.get("nodes") if isinstance(flow, dict) else None
    skills = tuple(
        str(_record(_record(node).get("config")).get("skill_slug") or "")
        for node in (nodes or [])
    )
    node_ids = tuple(str(_record(node).get("id") or "") for node in (nodes or []))
    if (
        flow.get("schema_version") != 3
        or flow.get("io_mode") != "strict"
        or skills != REQUIRED_SKILLS
        or node_ids != REQUIRED_NODE_IDS
        or len(flow.get("edges") or []) != 3
    ):
        raise RolloutError("canonical System 360 flow contract drifted")
    return flow


def _discover_showcase_workspace(db: DBSession, *, lock: bool = False) -> Workspace:
    workspace_query = db.query(Workspace).filter(
        Workspace.is_active.is_(True),
        Workspace.deleted_at.is_(None),
    )
    if lock:
        workspace_query = workspace_query.with_for_update(of=Workspace)
    workspaces = [
        workspace
        for workspace in workspace_query.all()
        if _record(workspace.settings).get("showcase_seed") is True
    ]
    if len(workspaces) != 1:
        raise RolloutError(
            f"expected exactly one active showcase_seed workspace, found {len(workspaces)}"
        )
    return workspaces[0]


def _marked_systems(
    db: DBSession,
    workspace: Workspace,
    *,
    lock: bool = False,
) -> list[System]:
    query = db.query(System).filter(System.workspace_id == workspace.id)
    if lock:
        query = query.with_for_update(of=System)
    return [
        system
        for system in query.all()
        if _experience(system).get("system_360_canary") == CANARY_MARKER
    ]


def _capability_for_system(
    db: DBSession,
    workspace: Workspace,
    system: System,
    *,
    lock: bool = False,
) -> Capability:
    if not system.capability_id:
        raise RolloutError("the canary System has no linked Capability")
    query = db.query(Capability).filter(
        Capability.id == system.capability_id,
        or_(
            Capability.workspace_id == workspace.id,
            Capability.workspace_id.is_(None),
        ),
    )
    if lock:
        query = query.with_for_update(of=Capability)
    capabilities = query.all()
    if len(capabilities) != 1:
        raise RolloutError("the linked Capability is missing or crosses workspace scope")
    return capabilities[0]


def _policy_for_system(
    db: DBSession,
    workspace: Workspace,
    system: System,
    *,
    lock: bool = False,
) -> ControlPolicy:
    if not system.control_policy_id:
        raise RolloutError("the canary System has no explicitly bound ControlPolicy")
    query = db.query(ControlPolicy).filter(
        ControlPolicy.id == system.control_policy_id,
        ControlPolicy.workspace_id == workspace.id,
        ControlPolicy.scope == "system",
        ControlPolicy.target_id == system.id,
    )
    if lock:
        query = query.with_for_update(of=ControlPolicy)
    policies = query.all()
    if len(policies) != 1:
        raise RolloutError("the bound ControlPolicy is missing or crosses System scope")
    return policies[0]


def discover_target(
    db: DBSession,
    *,
    lock: bool = False,
) -> tuple[Workspace, Capability, System, ControlPolicy]:
    """Discover the runtime canary exclusively through its experience marker."""

    workspace = _discover_showcase_workspace(db, lock=lock)
    marked = _marked_systems(db, workspace, lock=lock)
    if len(marked) != 1:
        raise RolloutError(
            "expected exactly one System 360 marker in the active Showcase, "
            f"found {len(marked)}"
        )
    system = marked[0]
    if system.status != "active":
        raise RolloutError("the marked System 360 canary is not active")
    capability = _capability_for_system(db, workspace, system, lock=lock)
    policy = _policy_for_system(db, workspace, system, lock=lock)
    return workspace, capability, system, policy


def _discover_bootstrap_candidate(
    db: DBSession,
    *,
    lock: bool = False,
) -> tuple[Workspace, System]:
    """Find the one pre-marker canary candidate from non-business metadata."""

    workspace = _discover_showcase_workspace(db, lock=lock)
    query = db.query(System).filter(
        System.workspace_id == workspace.id,
        System.status == "active",
    )
    if lock:
        query = query.with_for_update(of=System)
    candidates = []
    for system in query.all():
        settings = _system_settings(system)
        if (
            settings.get("showcase_seed") is True
            and settings.get("system_type") == "contract"
        ):
            candidates.append(system)
    if len(candidates) != 1:
        raise RolloutError(
            "expected exactly one active structural System 360 bootstrap candidate, "
            f"found {len(candidates)}"
        )
    candidate = candidates[0]
    marked = _marked_systems(db, workspace, lock=lock)
    if len(marked) > 1:
        raise RolloutError(
            "expected at most one System 360 marker before bootstrap, "
            f"found {len(marked)}"
        )
    if marked and marked[0].id != candidate.id:
        raise RolloutError("the existing System 360 marker is on another System")
    return workspace, candidate


def _required_skill_rows(
    db: DBSession,
    workspace: Workspace,
    *,
    lock: bool = False,
) -> list[Skill]:
    query = db.query(Skill).filter(
        Skill.slug.in_(REQUIRED_SKILLS),
        or_(Skill.workspace_id == workspace.id, Skill.workspace_id.is_(None)),
    )
    if lock:
        query = query.with_for_update(of=Skill)
    rows = query.all()
    by_slug = {row.slug: row for row in rows}
    missing = [slug for slug in REQUIRED_SKILLS if slug not in by_slug]
    if missing:
        raise RolloutError(
            "the structural canary is missing required registered Skills: "
            + ", ".join(missing)
        )
    return [by_slug[slug] for slug in REQUIRED_SKILLS]


def _context_for_system(
    db: DBSession,
    workspace: Workspace,
    system: System,
    *,
    lock: bool = False,
) -> Context:
    query = db.query(Context).filter(
        Context.workspace_id == workspace.id,
        Context.system_id == system.id,
    )
    if lock:
        query = query.with_for_update(of=Context)
    contexts = query.all()
    if len(contexts) != 1:
        raise RolloutError(
            "expected exactly one existing Context linked by system_id, "
            f"found {len(contexts)}"
        )
    return contexts[0]


def _bootstrap_policy_candidate(
    db: DBSession,
    workspace: Workspace,
    system: System,
    *,
    lock: bool = False,
) -> ControlPolicy | None:
    if system.control_policy_id:
        query = db.query(ControlPolicy).filter(
            ControlPolicy.id == system.control_policy_id,
            ControlPolicy.workspace_id == workspace.id,
        )
        if lock:
            query = query.with_for_update(of=ControlPolicy)
        policies = query.all()
        if len(policies) != 1:
            raise RolloutError("the existing ControlPolicy link is missing or cross-workspace")
        policy = policies[0]
        if policy.scope != "system" or policy.target_id != system.id:
            raise RolloutError("the existing ControlPolicy is not dedicated to the canary System")
        return policy

    query = db.query(ControlPolicy).filter(
        ControlPolicy.workspace_id == workspace.id,
        ControlPolicy.scope == "system",
        ControlPolicy.target_id == system.id,
    )
    if lock:
        query = query.with_for_update(of=ControlPolicy)
    policies = query.all()
    if len(policies) > 1:
        raise RolloutError("multiple unbound ControlPolicies target the canary System")
    return policies[0] if policies else None


def _bootstrap_membrane_payload(system: System, policy: ControlPolicy | None) -> dict[str, Any]:
    from scripts.seed_showcase_workspace import system360_membrane_v2_template

    template = system360_membrane_v2_template(
        object_store_prefix=f"system-360/{system.id}"
    )
    required_models = list(template["capabilities"]["allowed_models"])
    extra = _record(policy.extra) if policy is not None else {}
    raw = extra.get("membrane_spec")
    if raw is not None and not isinstance(raw, Mapping):
        raise RolloutError("existing membrane_spec is not an object")
    if isinstance(raw, Mapping):
        # Preserve explicit facet choices while filling only the required v2
        # contract. The canary-specific capability and provenance bindings are
        # authoritative and therefore always reconciled.
        for facet in FACET_NAMES:
            current = raw.get(facet)
            if current is not None and not isinstance(current, Mapping):
                raise RolloutError(f"existing MembraneSpec facet {facet} is not an object")
            template[facet] = {
                **_record(template.get(facet)),
                **_record(current),
            }
        # Retain forward-compatible extension keys while the five canonical
        # facets and rollout posture remain authoritative.
        template = {**copy.deepcopy(dict(raw)), **template}
        capabilities = _record(template.get("capabilities"))
        capabilities["allowed_skills"] = list(
            dict.fromkeys(
                [
                    *[str(value) for value in capabilities.get("allowed_skills") or []],
                    *REQUIRED_SKILLS,
                ]
            )
        )
        capabilities["allowed_actions"] = list(
            dict.fromkeys(
                [
                    *[str(value) for value in capabilities.get("allowed_actions") or []],
                    "system.engine.run",
                ]
            )
        )
        capabilities["allowed_models"] = list(
            dict.fromkeys(
                [
                    *[str(value) for value in capabilities.get("allowed_models") or []],
                    *required_models,
                ]
            )
        )
        template["capabilities"] = capabilities
    template["version"] = 2
    template["enforcement_mode"] = EnforcementMode.SHADOW.value
    provenance = _record(template.get("provenance"))
    provenance["object_store_prefix"] = f"system-360/{system.id}"
    template["provenance"] = provenance
    try:
        spec = MembraneSpec.from_dict(template, authoritative=True)
    except ValueError as exc:
        raise RolloutError(f"cannot bootstrap MembraneSpec v2: {exc}") from exc
    if spec.version != 2 or set(spec.configured_facets()) != set(FACET_NAMES):
        raise RolloutError("bootstrap MembraneSpec must configure all five facets")
    if not set(REQUIRED_SKILLS).issubset(spec.capabilities.allowed_skills):
        raise RolloutError("bootstrap MembraneSpec is missing required Skills")
    if "system.engine.run" not in spec.capabilities.allowed_actions:
        raise RolloutError("bootstrap MembraneSpec is missing system.engine.run")
    return template


def _linked_ids(current: Any, required: Sequence[str]) -> list[str]:
    existing = [str(value) for value in current or [] if value]
    return list(dict.fromkeys([*existing, *required]))


def bootstrap(db: DBSession, *, apply: bool, actor: str) -> dict[str, Any]:
    """Install the structural marker and bindings required before ``prepare``."""

    workspace, system = _discover_bootstrap_candidate(db, lock=apply)
    capability = _capability_for_system(db, workspace, system, lock=apply)
    skills = _required_skill_rows(db, workspace, lock=apply)
    context = _context_for_system(db, workspace, system, lock=apply)
    policy = _bootstrap_policy_candidate(db, workspace, system, lock=apply)
    rollout_state = _rollout_state(system, required=False)
    rollout_phase = str(rollout_state.get("phase") or "")
    if rollout_phase and rollout_phase != "rolled_back":
        if policy is None:
            raise RolloutError("an active rollout lost its bound ControlPolicy")
        # A deploy retry must never rewind an already advanced canary. Validate
        # the persisted phase contract and every bootstrap relationship, then
        # return without rewriting flags or the Membrane mode.
        _require_phase_contract(
            db,
            workspace,
            system,
            policy,
            state=rollout_state,
        )
        required_skill_ids = {skill.id for skill in skills}
        if not required_skill_ids.issubset(set(system.skill_ids or [])):
            raise RolloutError("an active rollout lost required System Skill links")
        if not required_skill_ids.issubset(set(capability.skill_ids or [])):
            raise RolloutError("an active rollout lost required Capability Skill links")
        if system.context_id != context.id:
            raise RolloutError("an active rollout lost its Context link")
        report = _base_report(
            command="bootstrap",
            apply=apply,
            workspace=workspace,
            capability=capability,
            system=system,
        )
        report.update(
            {
                "changed": False,
                "changed_fields": [],
                "already_bootstrapped": True,
                "phase": rollout_phase,
                "rollout_phase": rollout_phase,
            }
        )
        return report
    desired_membrane = _bootstrap_membrane_payload(system, policy)
    required_skill_ids = [skill.id for skill in skills]
    desired_system_skill_ids = _linked_ids(system.skill_ids, required_skill_ids)
    desired_capability_skill_ids = _linked_ids(capability.skill_ids, required_skill_ids)

    changed_fields: list[str] = []
    if desired_system_skill_ids != list(system.skill_ids or []):
        changed_fields.append("system.skill_ids")
    if desired_capability_skill_ids != list(capability.skill_ids or []):
        changed_fields.append("capability.skill_ids")
    if system.context_id != context.id:
        changed_fields.append("system.context_id")
    if _experience(system).get("system_360_canary") != CANARY_MARKER:
        changed_fields.append("system.settings.experience.system_360_canary")
    for key in ROLLOUT_FEATURES:
        settings, features = _workspace_features(workspace)
        if key not in features or features.get(key) is not False:
            changed_fields.append(f"workspace.settings.features.{key}")

    desired_policy_fields = {
        "scope": "system",
        "target_id": system.id,
        "max_cost_per_decision": float(
            desired_membrane["valves"]["max_cost_per_decision"]
        ),
        "max_latency_ms": float(desired_membrane["valves"]["max_latency_ms"]),
        "mandatory_hitl_if_confidence_below": float(
            desired_membrane["valves"]["mandatory_hitl_if_confidence_below"]
        ),
        "allowed_models": list(desired_membrane["capabilities"]["allowed_models"]),
        "allowed_skills": list(desired_membrane["capabilities"]["allowed_skills"]),
    }
    desired_extra = _record(policy.extra) if policy is not None else {}
    desired_extra["membrane_spec"] = desired_membrane
    if policy is None:
        changed_fields.extend(
            [
                *[f"control_policy.{field}" for field in desired_policy_fields],
                "control_policy.extra.membrane_spec",
                "system.control_policy_id",
            ]
        )
    else:
        if system.control_policy_id != policy.id:
            changed_fields.append("system.control_policy_id")
        for field, value in desired_policy_fields.items():
            if not _same_json(getattr(policy, field), value):
                changed_fields.append(f"control_policy.{field}")
        if not _same_json(policy.extra, desired_extra):
            changed_fields.append("control_policy.extra.membrane_spec")

    changed_fields = sorted(set(changed_fields))
    report = _base_report(
        command="bootstrap",
        apply=apply,
        workspace=workspace,
        capability=capability,
        system=system,
    )
    report.update(
        {
            "changed": bool(changed_fields),
            "changed_fields": changed_fields,
            "policy_created": policy is None,
            "marker": CANARY_MARKER,
            "feature_targets": {key: False for key in ROLLOUT_FEATURES},
            "membrane_target": EnforcementMode.SHADOW.value,
        }
    )
    if not apply or not changed_fields:
        return report

    system.skill_ids = desired_system_skill_ids
    capability.skill_ids = desired_capability_skill_ids
    system.context_id = context.id
    for key in ROLLOUT_FEATURES:
        _set_feature(workspace, key, False)
    _set_marker(system, CANARY_MARKER)
    if policy is None:
        policy = ControlPolicy(
            id=str(uuid4()),
            workspace_id=workspace.id,
            name="System 360 canary membrane",
            extra={},
            **desired_policy_fields,
        )
        db.add(policy)
        db.flush()
    else:
        for field, value in desired_policy_fields.items():
            setattr(policy, field, copy.deepcopy(value))
    policy.extra = desired_extra
    system.control_policy_id = policy.id
    audit_id = emit_audit_event(
        workspace_id=workspace.id,
        event_type="system360.bootstrap.applied",
        actor=actor,
        agent_id=system.id,
        details={"changed_fields": changed_fields},
        db=db,
    )
    if audit_id is None:
        raise RolloutError("the bootstrap audit event could not be persisted")
    db.commit()
    return report


def _raw_membrane(policy: ControlPolicy) -> dict[str, Any]:
    raw = _record(policy.extra).get("membrane_spec")
    if not isinstance(raw, Mapping) or not raw:
        raise RolloutError("the bound ControlPolicy needs an explicit MembraneSpec")
    payload = copy.deepcopy(dict(raw))
    try:
        spec = MembraneSpec.from_dict(payload, authoritative=True)
    except ValueError as exc:
        raise RolloutError(f"invalid MembraneSpec v2: {exc}") from exc
    if spec.version != 2 or set(spec.configured_facets()) != set(FACET_NAMES):
        raise RolloutError("the canary requires all five configured MembraneSpec v2 facets")
    if not set(REQUIRED_SKILLS).issubset(spec.capabilities.allowed_skills):
        raise RolloutError("MembraneSpec does not allow every strict-flow Skill")
    if "system.engine.run" not in spec.capabilities.allowed_actions:
        raise RolloutError("MembraneSpec does not allow system.engine.run")
    return payload


def _set_membrane_mode(policy: ControlPolicy, mode: EnforcementMode) -> None:
    payload = _raw_membrane(policy)
    payload["enforcement_mode"] = mode.value
    # Parse the final payload before it can reach persistence.
    MembraneSpec.from_dict(payload, authoritative=True)
    extra = _record(policy.extra)
    extra["membrane_spec"] = payload
    policy.extra = extra


def _membrane_mode(policy: ControlPolicy) -> str:
    return MembraneSpec.from_dict(_raw_membrane(policy), authoritative=True).effective_mode.value


def _workspace_features(workspace: Workspace) -> tuple[dict[str, Any], dict[str, Any]]:
    settings = _record(workspace.settings)
    features = _record(settings.get("features"))
    return settings, features


def _set_feature(workspace: Workspace, key: str, value: bool) -> None:
    settings, features = _workspace_features(workspace)
    features[key] = value
    settings["features"] = features
    workspace.settings = settings


def _feature(workspace: Workspace, key: str) -> bool:
    return _workspace_features(workspace)[1].get(key) is True


def _system_settings(system: System) -> dict[str, Any]:
    return _record(system.settings)


def _experience(system: System) -> dict[str, Any]:
    return _record(_system_settings(system).get("experience"))


def _rollout_state(system: System, *, required: bool = True) -> dict[str, Any]:
    raw = _system_settings(system).get(ROLLOUT_STATE_KEY)
    if not isinstance(raw, Mapping):
        if required:
            raise RolloutError("System 360 has not been prepared")
        return {}
    state = copy.deepcopy(dict(raw))
    if state.get("schema_version") != ROLLOUT_SCHEMA_VERSION:
        raise RolloutError("unsupported System 360 rollout state")
    _phase_index(str(state.get("phase") or ""))
    return state


def _save_state(system: System, state: Mapping[str, Any]) -> None:
    settings = _system_settings(system)
    settings[ROLLOUT_STATE_KEY] = copy.deepcopy(dict(state))
    system.settings = settings


def _set_marker(system: System, value: Any, *, present: bool = True) -> None:
    settings = _system_settings(system)
    experience = _record(settings.get("experience"))
    if present:
        experience["system_360_canary"] = value
    else:
        experience.pop("system_360_canary", None)
    if experience:
        settings["experience"] = experience
    else:
        settings.pop("experience", None)
    system.settings = settings


def _require_unique_marker(db: DBSession, workspace: Workspace, system: System) -> None:
    marked = [
        candidate.id
        for candidate in db.query(System).filter(System.workspace_id == workspace.id).all()
        if _experience(candidate).get("system_360_canary") == CANARY_MARKER
    ]
    foreign = [system_id for system_id in marked if system_id != system.id]
    if foreign:
        raise RolloutError("another System already owns the System 360 marker")


def _latest_version(db: DBSession, system: System) -> SystemVersion | None:
    return (
        db.query(SystemVersion)
        .filter(
            SystemVersion.system_id == system.id,
            SystemVersion.workspace_id == system.workspace_id,
        )
        .order_by(SystemVersion.version_number.desc())
        .first()
    )


def _ensure_version(
    db: DBSession,
    system: System,
    flow: Mapping[str, Any],
    *,
    actor: str,
    message: str,
) -> SystemVersion:
    version = record_new_version(
        db=db,
        system=system,
        flow_definition=flow,
        created_by=actor,
        audit_actor=actor,
        message=message,
        purge=False,
    )
    latest = version or _latest_version(db, system)
    if latest is None or not _same_json(latest.flow_definition, flow):
        raise RolloutError("failed to create or resolve the append-only SystemVersion")
    return latest


def _emit(db: DBSession, *, workspace: Workspace, system: System, actor: str, event: str, phase: str) -> None:
    audit_id = emit_audit_event(
        workspace_id=workspace.id,
        event_type=event,
        actor=actor,
        agent_id=system.id,
        details={
            "system_id": system.id,
            "capability_id": system.capability_id,
            "phase": phase,
        },
        db=db,
    )
    if audit_id is None:
        raise RolloutError("the rollout audit event could not be persisted")


def _base_report(
    *,
    command: str,
    apply: bool,
    workspace: Workspace,
    capability: Capability,
    system: System,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "command": command,
        "mode": "apply" if apply else "dry_run",
        "workspace_id": workspace.id,
        "capability_id": capability.id,
        "system_id": system.id,
    }


def prepare(db: DBSession, *, apply: bool, actor: str) -> dict[str, Any]:
    workspace, capability, system, policy = discover_target(db, lock=apply)
    report = _base_report(
        command="prepare", apply=apply, workspace=workspace, capability=capability, system=system
    )
    _require_unique_marker(db, workspace, system)
    strict_flow = canonical_strict_flow()
    raw_membrane = _raw_membrane(policy)
    current_state = _rollout_state(system, required=False)
    if current_state and current_state.get("phase") != "rolled_back":
        current_state = _require_phase_contract(
            db,
            workspace,
            system,
            policy,
            state=current_state,
        )
        report.update(
            {
                "phase": current_state["phase"],
                "changed": False,
                "already_prepared": True,
            }
        )
        return report

    settings, features = _workspace_features(workspace)
    experience = _experience(system)
    original = {
        "flow_definition": copy.deepcopy(system.flow_definition or {}),
        "features": {
            key: {"present": key in features, "value": copy.deepcopy(features.get(key))}
            for key in ROLLOUT_FEATURES
        },
        "marker": {
            "present": "system_360_canary" in experience,
            "value": copy.deepcopy(experience.get("system_360_canary")),
        },
        "membrane_spec": copy.deepcopy(raw_membrane),
    }
    report.update(
        {
            "phase": "prepared",
            "changed": True,
            "flow_changed": not _same_json(system.flow_definition, strict_flow),
            "feature_targets": {key: False for key in ROLLOUT_FEATURES},
            "membrane_target": "shadow",
        }
    )
    if not apply:
        return report

    original_version = _ensure_version(
        db,
        system,
        original["flow_definition"],
        actor=actor,
        message="Lot 6 pre-rollout flow snapshot",
    )
    prepared_version = _ensure_version(
        db,
        system,
        strict_flow,
        actor=actor,
        message="Lot 6 System 360 strict flow",
    )
    system.flow_definition = strict_flow
    for key in ROLLOUT_FEATURES:
        _set_feature(workspace, key, False)
    _set_membrane_mode(policy, EnforcementMode.SHADOW)
    _set_marker(system, CANARY_MARKER)
    state = {
        "schema_version": ROLLOUT_SCHEMA_VERSION,
        "phase": "prepared",
        "prepared_at": datetime.utcnow().isoformat(),
        "actor": actor,
        "original": original,
        "original_version_number": original_version.version_number,
        "prepared_version_number": prepared_version.version_number,
        "exercise_run_id": None,
    }
    _save_state(system, state)
    _emit(
        db,
        workspace=workspace,
        system=system,
        actor=actor,
        event="system360.rollout.prepared",
        phase="prepared",
    )
    db.commit()
    report.update(
        {
            "original_version_number": original_version.version_number,
            "prepared_version_number": prepared_version.version_number,
        }
    )
    return report


def _require_prepared_contract(
    db: DBSession,
    workspace: Workspace,
    system: System,
    policy: ControlPolicy,
) -> dict[str, Any]:
    state = _rollout_state(system)
    _require_unique_marker(db, workspace, system)
    if _experience(system).get("system_360_canary") != CANARY_MARKER:
        raise RolloutError("the structural target does not own the canary marker")
    if not _same_json(system.flow_definition, canonical_strict_flow()):
        raise RolloutError("the structural target does not carry the canonical strict flow")
    if policy.scope != "system" or policy.target_id != system.id:
        raise RolloutError("the ControlPolicy is not bound to the target System")
    return state


def _require_phase_contract(
    db: DBSession,
    workspace: Workspace,
    system: System,
    policy: ControlPolicy,
    *,
    state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate every persisted invariant claimed by the current phase.

    Idempotent deploy retries call all activation commands again.  A phase may
    therefore be ahead of the command's target, but it is a safe no-op only
    when marker, flow, policy, feature flags, Membrane mode and (once present)
    the real exercise proof still agree with that later phase.
    """

    current = (
        copy.deepcopy(dict(state))
        if isinstance(state, Mapping)
        else _rollout_state(system)
    )
    phase = str(current.get("phase") or "")
    _phase_index(phase)
    if phase == "rolled_back":
        raise RolloutError("a rolled-back rollout must be prepared again")

    # Reuse the structural checks so prepare retries cannot silently bless a
    # copied marker, a changed flow or a policy rebound to another object.
    persisted = _require_prepared_contract(db, workspace, system, policy)
    if persisted != current:
        raise RolloutError("rollout state changed while validating its phase")

    expected_features = _PHASE_FEATURE_CONTRACT.get(phase)
    expected_membrane = _PHASE_MEMBRANE_CONTRACT.get(phase)
    if expected_features is None or expected_membrane is None:
        raise RolloutError(f"phase {phase} has no runtime contract")

    feature_mismatches = [
        f"{key}={str(_feature(workspace, key)).lower()}"
        for key, expected in expected_features.items()
        if _feature(workspace, key) is not expected
    ]
    if feature_mismatches:
        raise RolloutError(
            f"phase {phase} feature contract diverged: " + ", ".join(feature_mismatches)
        )

    observed_membrane = _membrane_mode(policy)
    if observed_membrane != expected_membrane:
        raise RolloutError(
            f"phase {phase} requires MembraneSpec mode {expected_membrane}, "
            f"found {observed_membrane}"
        )

    if _phase_index(phase) >= _phase_index("exercised"):
        proof = _exercise_proof(db, current, system)
        if not proof["required_skills_observed"]:
            raise RolloutError(
                f"phase {phase} claims an invalid strict-flow exercise proof"
            )
    return current


def _transition_feature(
    db: DBSession,
    *,
    command: str,
    target_phase: str,
    required_phase: str,
    feature: str,
    apply: bool,
    actor: str,
) -> dict[str, Any]:
    workspace, capability, system, policy = discover_target(db, lock=apply)
    state = _require_phase_contract(db, workspace, system, policy)
    report = _base_report(
        command=command, apply=apply, workspace=workspace, capability=capability, system=system
    )
    current = str(state["phase"])
    if _phase_index(current) >= _phase_index(target_phase):
        report.update({"phase": current, "changed": False})
        return report
    if current != required_phase:
        raise RolloutError(f"{command} requires phase {required_phase}, found {current}")
    report.update({"phase": target_phase, "changed": True, "feature": feature})
    if not apply:
        return report
    _set_feature(workspace, feature, True)
    state["phase"] = target_phase
    state[f"{target_phase}_at"] = datetime.utcnow().isoformat()
    _save_state(system, state)
    _emit(
        db,
        workspace=workspace,
        system=system,
        actor=actor,
        event=f"system360.rollout.{command.replace('-', '_')}",
        phase=target_phase,
    )
    db.commit()
    return report


def activate_flow(db: DBSession, *, apply: bool, actor: str) -> dict[str, Any]:
    return _transition_feature(
        db,
        command="activate-flow",
        target_phase="flow_active",
        required_phase="prepared",
        feature=FEATURE_FLOW,
        apply=apply,
        actor=actor,
    )


def _exercise_proof(db: DBSession, state: Mapping[str, Any], system: System) -> dict[str, Any]:
    run_id = state.get("exercise_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise RolloutError("no exercise Run is recorded")
    run = (
        db.query(Run)
        .filter(
            Run.id == run_id,
            Run.workspace_id == system.workspace_id,
            Run.system_id == system.id,
            Run.trigger == EXERCISE_TRIGGER,
        )
        .first()
    )
    if run is None:
        raise RolloutError("the recorded exercise Run is missing or out of scope")
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc(), SkillInvocation.id.asc())
        .all()
    )
    observed_skills = tuple(str(item.skill_slug or "") for item in invocations)
    observed_node_ids = tuple(
        str(_record(item.trace).get("node_id") or "") for item in invocations
    )
    invocation_rows_valid = all(
        item.status == "completed" and not item.error for item in invocations
    )
    canonical_snapshot = _same_json(run.flow_snapshot, canonical_strict_flow())

    answer_invocation = next(
        (item for item in invocations if item.skill_slug == "llm_rag_answer_v1"),
        None,
    )
    citations = _nonempty_citations(
        _record(answer_invocation.output_ref).get("citations")
        if answer_invocation is not None
        else None
    )
    egress_checkpoint = next(
        (
            checkpoint
            for checkpoint in reversed(list(run.checkpoints or []))
            if _record(checkpoint).get("kind") == "membrane_egress_evaluated"
        ),
        None,
    )
    egress_citation_count = _record(egress_checkpoint).get("citation_count")
    citations_grounded = bool(citations) and (
        isinstance(egress_citation_count, int)
        and not isinstance(egress_citation_count, bool)
        and egress_citation_count > 0
    )

    output_provenance = _canonical_provenance_pair(
        _record(run.output_ref).get("_membrane_provenance")
    )
    audit_invocation = next(
        (item for item in invocations if item.skill_slug == "audit_log_v1"),
        None,
    )
    audit_provenance = _canonical_provenance_pair(
        _record(audit_invocation.trace).get("membrane_provenance")
        if audit_invocation is not None
        else None
    )
    provenance_checkpoint = next(
        (
            checkpoint
            for checkpoint in reversed(list(run.checkpoints or []))
            if _record(checkpoint).get("kind") == "membrane_provenance"
        ),
        None,
    )
    checkpoint_provenance = _canonical_provenance_pair(provenance_checkpoint)
    canonical_provenance = (
        output_provenance is not None
        and output_provenance == audit_provenance == checkpoint_provenance
    )
    valid = (
        run.status == "completed"
        and run.completed_at is not None
        and not run.error
        and canonical_snapshot
        and observed_skills == REQUIRED_SKILLS
        and observed_node_ids == REQUIRED_NODE_IDS
        and invocation_rows_valid
        and citations_grounded
        and canonical_provenance
    )
    return {
        "run_id": run.id,
        "status": run.status,
        "invocation_count": len(invocations),
        "canonical_flow_snapshot": canonical_snapshot,
        "observed_skills": list(observed_skills),
        "observed_node_ids": list(observed_node_ids),
        "invocations_completed_without_error": invocation_rows_valid,
        "citation_count": len(citations),
        "egress_citation_count": (
            egress_citation_count if isinstance(egress_citation_count, int) else None
        ),
        "grounded_output_verified": citations_grounded,
        "provenance_uri": output_provenance[0] if output_provenance else None,
        "provenance_sha256": output_provenance[1] if output_provenance else None,
        "canonical_provenance_verified": canonical_provenance,
        "required_skills_observed": valid,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def exercise(
    db: DBSession,
    *,
    apply: bool,
    actor: str,
    query: str | None,
) -> dict[str, Any]:
    workspace, capability, system, policy = discover_target(db, lock=apply)
    state = _require_phase_contract(db, workspace, system, policy)
    report = _base_report(
        command="exercise", apply=apply, workspace=workspace, capability=capability, system=system
    )
    phase = str(state["phase"])
    if _phase_index(phase) >= _phase_index("exercised") and phase != "rolled_back":
        proof = _exercise_proof(db, state, system)
        if not proof["required_skills_observed"]:
            raise RolloutError(
                "recorded exercise is not a grounded, provenance-backed strict-flow Run"
            )
        report.update({"phase": phase, "changed": False, "exercise": proof})
        return report
    if phase != "flow_active":
        raise RolloutError(f"exercise requires phase flow_active, found {phase}")
    if not _feature(workspace, FEATURE_FLOW):
        raise RolloutError("strict DAG feature is not active")
    if _membrane_mode(policy) != EnforcementMode.SHADOW.value:
        raise RolloutError("exercise must run while MembraneSpec is in shadow mode")
    clean_query = (query or "").strip()
    if apply and not clean_query:
        raise RolloutError("--exercise-query is required for a real exercise")
    report.update({"phase": "exercised", "changed": True})
    if not apply:
        report["requires_real_query"] = True
        return report

    existing_id = state.get("exercise_run_id")
    run = db.query(Run).filter(Run.id == existing_id).first() if existing_id else None
    if run is None:
        run = Run(
            id=str(uuid4()),
            workspace_id=workspace.id,
            system_id=system.id,
            capability_id=capability.id,
            initiated_by_user_id=None,
            input_ref={
                "query": clean_query,
                "rollout_contract": {"schema_version": 1, "kind": "system360_exercise"},
            },
            status="pending",
            started_at=datetime.utcnow(),
            trigger=EXERCISE_TRIGGER,
        )
        db.add(run)
        state["exercise_run_id"] = run.id
        _save_state(system, state)
        db.commit()
    elif run.status in {"failed", "cancelled"}:
        raise RolloutError(f"existing exercise Run is terminal with status {run.status}")

    from app.services.run_engine.dag import execute_run_dag

    asyncio.run(execute_run_dag(run.id))
    db.expire_all()
    workspace, capability, system, policy = discover_target(db, lock=True)
    state = _require_prepared_contract(db, workspace, system, policy)
    proof = _exercise_proof(db, state, system)
    if not proof["required_skills_observed"]:
        raise RolloutError(
            "real strict-flow exercise did not produce the required invocations, "
            "grounded citations and canonical provenance"
        )
    state["phase"] = "exercised"
    state["exercised_at"] = datetime.utcnow().isoformat()
    _save_state(system, state)
    _emit(
        db,
        workspace=workspace,
        system=system,
        actor=actor,
        event="system360.rollout.exercised",
        phase="exercised",
    )
    db.commit()
    report["exercise"] = proof
    return report


def activate_membrane(db: DBSession, *, apply: bool, actor: str) -> dict[str, Any]:
    workspace, capability, system, policy = discover_target(db, lock=apply)
    state = _require_phase_contract(db, workspace, system, policy)
    report = _base_report(
        command="activate-membrane", apply=apply, workspace=workspace, capability=capability, system=system
    )
    phase = str(state["phase"])
    if _phase_index(phase) >= _phase_index("membrane_active") and phase != "rolled_back":
        report.update({"phase": phase, "changed": False})
        return report
    if phase != "exercised":
        raise RolloutError(f"activate-membrane requires phase exercised, found {phase}")
    proof = _exercise_proof(db, state, system)
    if not proof["required_skills_observed"]:
        raise RolloutError(
            "Membrane activation requires a grounded, provenance-backed exercise Run"
        )
    report.update({"phase": "membrane_active", "changed": True, "exercise": proof})
    if not apply:
        return report
    _set_membrane_mode(policy, EnforcementMode.ENFORCE)
    state["phase"] = "membrane_active"
    state["membrane_active_at"] = datetime.utcnow().isoformat()
    _save_state(system, state)
    _emit(
        db,
        workspace=workspace,
        system=system,
        actor=actor,
        event="system360.rollout.activate_membrane",
        phase="membrane_active",
    )
    db.commit()
    return report


def activate_axes(db: DBSession, *, apply: bool, actor: str) -> dict[str, Any]:
    return _transition_feature(
        db,
        command="activate-axes",
        target_phase="axes_active",
        required_phase="membrane_active",
        feature=FEATURE_AXES,
        apply=apply,
        actor=actor,
    )


def activate_projection(db: DBSession, *, apply: bool, actor: str) -> dict[str, Any]:
    return _transition_feature(
        db,
        command="activate-projection",
        target_phase="projection_active",
        required_phase="axes_active",
        feature=FEATURE_PROJECTION,
        apply=apply,
        actor=actor,
    )


def status(db: DBSession) -> dict[str, Any]:
    workspace, capability, system, policy = discover_target(db)
    state = _rollout_state(system, required=False)
    phase = str(state.get("phase") or "unprepared")
    report = _base_report(
        command="status", apply=False, workspace=workspace, capability=capability, system=system
    )
    marker_count = sum(
        1
        for candidate in db.query(System).filter(System.workspace_id == workspace.id).all()
        if _experience(candidate).get("system_360_canary") == CANARY_MARKER
    )
    exercise_status: dict[str, Any] | None = None
    if state.get("exercise_run_id"):
        try:
            exercise_status = _exercise_proof(db, state, system)
        except RolloutError as exc:
            exercise_status = {"valid": False, "error": str(exc)}
    report.update(
        {
            "phase": phase,
            "marker_count": marker_count,
            "marker_on_target": _experience(system).get("system_360_canary") == CANARY_MARKER,
            "strict_flow": _same_json(system.flow_definition, canonical_strict_flow()),
            "features": {key: _feature(workspace, key) for key in ROLLOUT_FEATURES},
            "membrane_mode": _membrane_mode(policy),
            "exercise": exercise_status,
        }
    )
    report["ready"] = bool(
        phase == "projection_active"
        and report["marker_count"] == 1
        and report["marker_on_target"]
        and report["strict_flow"]
        and all(report["features"].values())
        and report["membrane_mode"] == "enforce"
        and exercise_status
        and exercise_status.get("required_skills_observed") is True
    )
    return report


def rollback(db: DBSession, *, apply: bool, actor: str) -> dict[str, Any]:
    workspace, capability, system, policy = discover_target(db, lock=apply)
    state = _rollout_state(system)
    report = _base_report(
        command="rollback", apply=apply, workspace=workspace, capability=capability, system=system
    )
    if state["phase"] == "rolled_back":
        report.update({"phase": "rolled_back", "changed": False})
        return report
    original = state.get("original")
    if not isinstance(original, Mapping) or not isinstance(original.get("flow_definition"), Mapping):
        raise RolloutError("rollout state has no restorable flow snapshot")
    report.update(
        {
            "phase": "rolled_back",
            "changed": True,
            "ordered_actions": [
                "projection_off",
                "axes_off",
                "membrane_shadow",
                "strict_flow_off",
                "previous_flow_version",
            ],
        }
    )
    if not apply:
        return report

    # Keep the inverse order explicit even though a single transaction makes
    # the externally visible change atomic.
    _set_feature(workspace, FEATURE_PROJECTION, False)
    _set_feature(workspace, FEATURE_AXES, False)
    _set_membrane_mode(policy, EnforcementMode.SHADOW)
    _set_feature(workspace, FEATURE_FLOW, False)
    restored_flow = copy.deepcopy(dict(original["flow_definition"]))
    original_version_number = state.get("original_version_number")
    if not isinstance(original_version_number, int):
        raise RolloutError("rollout state has no original SystemVersion number")
    restored_version = rollback_to_version(
        db=db,
        system=system,
        version_number=original_version_number,
        created_by=actor,
        audit_actor=actor,
        message="Lot 6 rollback to pre-rollout flow",
        purge=False,
    )
    if not _same_json(system.flow_definition, restored_flow):
        raise RolloutError("rollback target no longer matches the captured pre-rollout flow")
    marker = _record(original.get("marker"))
    _set_marker(system, marker.get("value"), present=marker.get("present") is True)
    state["phase"] = "rolled_back"
    state["rolled_back_at"] = datetime.utcnow().isoformat()
    state["rollback_version_number"] = restored_version.version_number
    _save_state(system, state)
    _emit(
        db,
        workspace=workspace,
        system=system,
        actor=actor,
        event="system360.rollout.rolled_back",
        phase="rolled_back",
    )
    db.commit()
    report["rollback_version_number"] = restored_version.version_number
    return report


COMMANDS = {
    "bootstrap": bootstrap,
    "prepare": prepare,
    "activate-flow": activate_flow,
    "activate-membrane": activate_membrane,
    "activate-axes": activate_axes,
    "activate-projection": activate_projection,
    "status": status,
    "rollback": rollback,
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(*COMMANDS, "exercise"))
    parser.add_argument("--apply", action="store_true", help="Persist the requested transition")
    parser.add_argument("--actor", default="system:lot6-system360-rollout")
    parser.add_argument(
        "--exercise-query",
        default=os.environ.get("AGENTIUM_LOT6_EXERCISE_QUERY"),
        help="Real query used only by exercise --apply",
    )
    parser.add_argument(
        "--exercise-query-stdin",
        action="store_true",
        help="Read the exercise query from stdin instead of exposing it in the process list",
    )
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def _write_report(path: Path | None, report: Mapping[str, Any]) -> None:
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    print(payload, end="")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "status" and args.apply:
        print("rollout failed: status is always read-only", file=sys.stderr)
        return 2
    db = SessionLocal()
    try:
        if args.command == "exercise":
            if args.exercise_query_stdin and args.exercise_query:
                raise RolloutError(
                    "--exercise-query-stdin cannot be combined with --exercise-query or its environment fallback"
                )
            query = sys.stdin.read(1_000_001) if args.exercise_query_stdin else args.exercise_query
            if args.exercise_query_stdin and len(query) > 1_000_000:
                raise RolloutError("exercise query from stdin exceeds 1,000,000 characters")
            report = exercise(
                db,
                apply=args.apply,
                actor=args.actor,
                query=query,
            )
        elif args.exercise_query_stdin:
            raise RolloutError("--exercise-query-stdin is valid only for the exercise command")
        elif args.command == "status":
            report = status(db)
        else:
            report = COMMANDS[args.command](db, apply=args.apply, actor=args.actor)
        if not args.apply:
            db.rollback()
        _write_report(args.report, report)
        return 0
    except RolloutError as exc:
        db.rollback()
        failure = {
            "schema_version": 1,
            "command": args.command,
            "mode": "apply" if args.apply else "dry_run",
            "ok": False,
            "error": str(exc),
        }
        if args.report:
            _write_report(args.report, failure)
        else:
            print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
