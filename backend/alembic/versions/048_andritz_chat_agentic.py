"""Seed the "Andritz Chat Agentic" run_engine System + its process-membrane.

Materialises a NEW custom run_engine System (NOT the ``chat_transverse_v1``
workspace-chat variant) for the andritz workspace, walked by
``execute_run_dag()`` because its ``flow_definition`` carries real control
nodes (decision/fork/join/hitl). The flow is loaded verbatim from the pinned
artifact ``app/resources/flows/andritz_chat_agentic_v3.json`` (schema_version 3,
``variant=chat_agentic_thinking_v1``, 22 nodes / 27 edges), and each task
node's ``config.skill_id`` is RESOLVED from its ``config.skill_slug`` against
the ``skills`` table (the three agentic skills — ``chat_agentic_plan_v1``,
``chat_self_correct_v1``, ``response_eval_v1`` — are upserted first so the
resolution never leaves a hole and the System is runnable regardless of seed
ordering).

The ``membrane_spec`` from the same artifact is materialised as a canonical
``ControlPolicy`` (scope=``system``, ``target_id`` = the new System id,
``extra["membrane_spec"]``) and the System is bound to it via
``System.control_policy_id`` — the engine loads the membrane through
``scope="system" AND target_id=system.id`` (``_load_control_policy``). The
System's ``default_model`` is pinned to ``gpt-4o-mini`` so the provider-neutral
LLM skills resolve a live model via ``ModelRouter`` (parity with A/B arm A).

Idempotent and marker-scoped: the System carries ``settings.seed_origin`` and
the policy carries ``extra.membrane_origin`` (both = this revision id), so a
re-run updates in place and the downgrade removes ONLY what we seeded
(detaching/deleting the System's runs + invocations first to satisfy the FK).
Data-only: no DDL (all columns already exist).

Revision ID: 048_andritz_chat_agentic  (<= 32 chars — the 046 lesson)
Revises: 047_andritz_membrane
Create Date: 2026-06-25
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "048_andritz_chat_agentic"
down_revision = "047_andritz_membrane"
branch_labels = None
depends_on = None


# Marker stamped into ``systems.settings`` and ``control_policies.extra`` so the
# downgrade only ever removes the rows WE created (never an operator-authored
# System/policy that happens to share the name).
_SEED_ORIGIN = "048_andritz_chat_agentic"
_SYSTEM_NAME = "Andritz Chat Agentic"
_CAPABILITY_SLUG = "workspace_assistant"
_DEFAULT_MODEL = "gpt-4o-mini"

_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "resources"
    / "flows"
    / "andritz_chat_agentic_v3.json"
)

# Minimal metadata for the three agentic skills the flow references. Upserted by
# slug if absent so ``skill_id`` resolution is always complete and the System is
# runnable even if the catalog seed hasn't run yet. The authoritative schemas
# live in ``app/services/skills_registry/seed.py`` (catalog seed reconciles).
_REQUIRED_SKILLS = [
    {
        "slug": "chat_agentic_plan_v1",
        "name": "Chat Agentic Plan",
        "type": "planning",
        "description": "Provider-neutral agentic planner (ModelRouter): classifies the request and exposes the retrieval config.",
        "certification_level": "production",
        "provider": "internal",
    },
    {
        "slug": "chat_self_correct_v1",
        "name": "Chat Self Correct",
        "type": "generation",
        "description": "Provider-neutral bounded self-correction reactor (ModelRouter): one repair pass, returns answer/citations/action_taken.",
        "certification_level": "production",
        "provider": "internal",
    },
    {
        "slug": "response_eval_v1",
        "name": "Response Eval",
        "type": "analysis",
        "description": "ResponseEvaluator wrapper: authoritative 0-100 composite + hallucination_rate + context_count.",
        "certification_level": "production",
        "provider": "internal",
    },
]


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _load_artifact() -> Optional[dict[str, Any]]:
    try:
        with _ARTIFACT_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _tables():
    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
    )
    capabilities = sa.table(
        "capabilities",
        sa.column("id"),
        sa.column("slug"),
    )
    skills = sa.table(
        "skills",
        sa.column("id"),
        sa.column("slug"),
        sa.column("version"),
        sa.column("name"),
        sa.column("description"),
        sa.column("type"),
        sa.column("certification_level"),
        sa.column("is_seeded"),
        sa.column("provider"),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    systems = sa.table(
        "systems",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("objective"),
        sa.column("capability_id"),
        sa.column("skill_ids", sa.JSON()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("settings", sa.JSON()),
        sa.column("execution_mode"),
        sa.column("coordination_pattern"),
        sa.column("control_policy_id"),
        sa.column("status"),
        sa.column("created_by"),
        sa.column("default_model"),
        sa.column("retrieval_mode_default"),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    control_policies = sa.table(
        "control_policies",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("scope"),
        sa.column("target_id"),
        sa.column("max_cost_per_decision", sa.Float()),
        sa.column("max_latency_ms", sa.Float()),
        sa.column("mandatory_hitl_if_confidence_below", sa.Float()),
        sa.column("allowed_models", sa.JSON()),
        sa.column("allowed_skills", sa.JSON()),
        sa.column("extra", sa.JSON()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    runs = sa.table(
        "runs",
        sa.column("id"),
        sa.column("system_id"),
    )
    skill_invocations = sa.table(
        "skill_invocations",
        sa.column("id"),
        sa.column("run_id"),
    )
    return (
        workspaces,
        capabilities,
        skills,
        systems,
        control_policies,
        runs,
        skill_invocations,
    )


def _ensure_required_skills(bind, skills, now) -> None:
    """Upsert the three agentic skills by slug (insert-if-absent)."""
    for meta in _REQUIRED_SKILLS:
        exists = bind.execute(
            sa.select(skills.c.id).where(skills.c.slug == meta["slug"])
        ).first()
        if exists:
            continue
        bind.execute(
            skills.insert().values(
                id=str(uuid4()),
                slug=meta["slug"],
                version="1",
                name=meta["name"],
                description=meta["description"],
                type=meta["type"],
                certification_level=meta["certification_level"],
                is_seeded="Y",
                provider=meta["provider"],
                created_at=now,
                updated_at=now,
            )
        )


def _resolve_flow_skill_ids(bind, skills, flow: dict[str, Any]) -> list[str]:
    """Fill each task node's ``config.skill_id`` from its ``skill_slug``.

    Mutates ``flow`` in place and returns the de-duplicated list of resolved
    skill ids (for ``System.skill_ids``).
    """
    slugs = set()
    for node in flow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        slug = (node.get("config") or {}).get("skill_slug")
        if slug:
            slugs.add(slug)
    if not slugs:
        return []
    rows = bind.execute(
        sa.select(skills.c.id, skills.c.slug).where(skills.c.slug.in_(slugs))
    ).all()
    id_by_slug = {r._mapping["slug"]: r._mapping["id"] for r in rows}

    ordered_ids: list[str] = []
    seen: set[str] = set()
    for node in flow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        slug = config.get("skill_slug")
        if not slug:
            continue
        skill_id = id_by_slug.get(slug)
        config["skill_id"] = skill_id
        if skill_id and skill_id not in seen:
            seen.add(skill_id)
            ordered_ids.append(skill_id)
    return ordered_ids


def _membrane_columns(membrane: dict[str, Any]) -> dict[str, Any]:
    valves = membrane.get("valves") if isinstance(membrane.get("valves"), dict) else {}
    caps = membrane.get("capabilities") if isinstance(membrane.get("capabilities"), dict) else {}
    return {
        "max_cost_per_decision": valves.get("max_cost_per_decision"),
        "max_latency_ms": valves.get("max_latency_ms"),
        "mandatory_hitl_if_confidence_below": valves.get("mandatory_hitl_if_confidence_below"),
        "allowed_models": caps.get("allowed_models") or [],
        "allowed_skills": caps.get("allowed_skills") or [],
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    required = {"workspaces", "systems", "control_policies", "skills"}
    if not required.issubset(table_names):
        return

    artifact = _load_artifact()
    if not artifact:
        return
    flow = _as_dict(artifact.get("flow_definition"))
    membrane = _as_dict(artifact.get("membrane_spec"))
    if not flow:
        return

    (
        workspaces,
        capabilities,
        skills,
        systems,
        control_policies,
        runs,
        skill_invocations,
    ) = _tables()

    ws = bind.execute(
        sa.select(workspaces.c.id).where(workspaces.c.slug == "andritz")
    ).first()
    if not ws:
        return
    workspace_id = ws._mapping["id"]

    now = datetime.utcnow()
    _ensure_required_skills(bind, skills, now)
    skill_ids = _resolve_flow_skill_ids(bind, skills, flow)

    cap = bind.execute(
        sa.select(capabilities.c.id).where(capabilities.c.slug == _CAPABILITY_SLUG)
    ).first()
    capability_id = cap._mapping["id"] if cap else None

    settings = {
        "seed_origin": _SEED_ORIGIN,
        "system_type": "chat_agentic",
        "variant": flow.get("variant") or "chat_agentic_thinking_v1",
    }

    # Locate the System WE seeded (marker-scoped) for this workspace.
    existing_rows = bind.execute(
        sa.select(systems.c.id, systems.c.settings, systems.c.control_policy_id).where(
            systems.c.workspace_id == workspace_id,
            systems.c.name == _SYSTEM_NAME,
        )
    ).all()
    ours = None
    for row in existing_rows:
        if _as_dict(row._mapping["settings"]).get("seed_origin") == _SEED_ORIGIN:
            ours = row._mapping
            break

    if ours is None:
        system_id = str(uuid4())
        bind.execute(
            systems.insert().values(
                id=system_id,
                workspace_id=workspace_id,
                name=_SYSTEM_NAME,
                objective="Chat agentique (raisonnement borne, membrane-governed) pour Andritz.",
                capability_id=capability_id,
                skill_ids=skill_ids,
                flow_definition=flow,
                settings=settings,
                execution_mode=artifact.get("system", {}).get("execution_mode") or "real_time_decision",
                coordination_pattern=artifact.get("system", {}).get("coordination_pattern") or "single_agent",
                control_policy_id=None,
                status="active",
                created_by="migration",
                default_model=_DEFAULT_MODEL,
                retrieval_mode_default="auto",
                created_at=now,
                updated_at=now,
            )
        )
    else:
        system_id = ours["id"]
        bind.execute(
            sa.update(systems)
            .where(systems.c.id == system_id)
            .values(
                capability_id=capability_id,
                skill_ids=skill_ids,
                flow_definition=flow,
                settings=settings,
                status="active",
                default_model=_DEFAULT_MODEL,
                updated_at=now,
            )
        )

    # Materialise / refresh the membrane ControlPolicy bound to this System.
    cols = _membrane_columns(membrane)
    existing_policies = bind.execute(
        sa.select(control_policies.c.id, control_policies.c.extra).where(
            control_policies.c.scope == "system",
            control_policies.c.target_id == system_id,
        )
    ).all()
    policy_id = None
    for row in existing_policies:
        if _as_dict(row._mapping["extra"]).get("membrane_origin") == _SEED_ORIGIN:
            policy_id = row._mapping["id"]
            break

    extra = {"membrane_origin": _SEED_ORIGIN, "membrane_spec": membrane}
    if policy_id is None:
        policy_id = str(uuid4())
        bind.execute(
            control_policies.insert().values(
                id=policy_id,
                workspace_id=workspace_id,
                name="Andritz Chat Agentic Membrane",
                scope="system",
                target_id=system_id,
                max_cost_per_decision=cols["max_cost_per_decision"],
                max_latency_ms=cols["max_latency_ms"],
                mandatory_hitl_if_confidence_below=cols["mandatory_hitl_if_confidence_below"],
                allowed_models=cols["allowed_models"],
                allowed_skills=cols["allowed_skills"],
                extra=extra,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        bind.execute(
            sa.update(control_policies)
            .where(control_policies.c.id == policy_id)
            .values(
                max_cost_per_decision=cols["max_cost_per_decision"],
                max_latency_ms=cols["max_latency_ms"],
                mandatory_hitl_if_confidence_below=cols["mandatory_hitl_if_confidence_below"],
                allowed_models=cols["allowed_models"],
                allowed_skills=cols["allowed_skills"],
                extra=extra,
                updated_at=now,
            )
        )

    bind.execute(
        sa.update(systems)
        .where(systems.c.id == system_id)
        .values(control_policy_id=policy_id, updated_at=now)
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    required = {"workspaces", "systems", "control_policies"}
    if not required.issubset(table_names):
        return

    (
        workspaces,
        _capabilities,
        _skills,
        systems,
        control_policies,
        runs,
        skill_invocations,
    ) = _tables()

    ws_rows = bind.execute(
        sa.select(workspaces.c.id).where(workspaces.c.slug == "andritz")
    ).all()
    ws_ids = [row._mapping["id"] for row in ws_rows]
    if not ws_ids:
        return

    sys_rows = bind.execute(
        sa.select(systems.c.id, systems.c.settings).where(
            systems.c.workspace_id.in_(ws_ids),
            systems.c.name == _SYSTEM_NAME,
        )
    ).all()
    for row in sys_rows:
        if _as_dict(row._mapping["settings"]).get("seed_origin") != _SEED_ORIGIN:
            continue
        system_id = row._mapping["id"]

        # Detach + delete the membrane policy we seeded for this System.
        bind.execute(
            sa.update(systems)
            .where(systems.c.id == system_id)
            .values(control_policy_id=None)
        )
        policy_rows = bind.execute(
            sa.select(control_policies.c.id, control_policies.c.extra).where(
                control_policies.c.scope == "system",
                control_policies.c.target_id == system_id,
            )
        ).all()
        for prow in policy_rows:
            if _as_dict(prow._mapping["extra"]).get("membrane_origin") != _SEED_ORIGIN:
                continue
            bind.execute(
                sa.delete(control_policies).where(
                    control_policies.c.id == prow._mapping["id"]
                )
            )

        # Remove runs (and their invocations) created against this System so the
        # System row can be deleted without violating the runs.system_id FK.
        run_rows = bind.execute(
            sa.select(runs.c.id).where(runs.c.system_id == system_id)
        ).all()
        run_ids = [r._mapping["id"] for r in run_rows]
        if run_ids:
            if "skill_invocations" in table_names:
                bind.execute(
                    sa.delete(skill_invocations).where(
                        skill_invocations.c.run_id.in_(run_ids)
                    )
                )
            bind.execute(sa.delete(runs).where(runs.c.system_id == system_id))

        bind.execute(sa.delete(systems).where(systems.c.id == system_id))
