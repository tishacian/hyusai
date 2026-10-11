"""Seed the authoritative Andritz process-membrane (MembraneSpec) — P3.

Materialises the Sympozium-style process membrane for the Andritz chat System
as a canonical ``ControlPolicy.extra["membrane_spec"]`` (scope=``system``,
``target_id`` = the workspace chat System id) and binds it via
``System.control_policy_id``. The spec is *derived from the CURRENT effective
source_policy* (workspace settings layered with the chat System settings — the
System shadows the workspace, parity with ``resolve_workspace_chat_source_policy``)
so it captures Andritz's live contract:

    industrial_grounding, reject_cross_project_sources, preserve_reference_types,
    require_citations, expert_review_required=False, expert_fiche_correction_enabled=True

plus the ``voice_loop`` endpointing budgets (pinned by migration 046) carried in
the membrane *valves* facet as an advisory circuit-breaker.

Authoritative on the membrane CONTRACT (inbound/outbound/capabilities/provenance
facets are recomputed every run), ``set-if-absent`` on operator-tunable VALVE
keys (an operator-tuned cost/latency cap is never clobbered). Idempotent and
slug-scoped (``workspaces.slug == "andritz"``); re-running changes nothing.

This is data-only: it adds NO DDL (``control_policies.extra`` and
``systems.control_policy_id`` already exist). The layering is preserved by
mirroring the expert-correction keys onto the chat System (inline equivalent of
``sync_chat_system_expert_correction_policy``).

Revision ID: 047_andritz_membrane  (<= 32 chars — the 046 lesson)
Revises: 046_andritz_voice_overrides
Create Date: 2026-06-25
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "047_andritz_membrane"
down_revision = "046_andritz_voice_overrides"
branch_labels = None
depends_on = None


_WORKSPACE_CHAT_VARIANT = "chat_transverse_v1"
# Marker stamped into ``extra`` so downgrade only removes the row WE created and
# never an operator-authored membrane policy for the same System.
_MEMBRANE_ORIGIN = "047_andritz_membrane"
_EXPERT_CORRECTION_KEYS = ("expert_fiche_correction_enabled", "expert_review_required")


def _as_settings(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _is_workspace_chat_system(settings: dict[str, Any], flow: dict[str, Any], name: str) -> bool:
    if flow.get("variant") == _WORKSPACE_CHAT_VARIANT:
        return True
    if settings.get("system_type") == "workspace_chat":
        return True
    return name in {"Agentium Workspace Chat", "Andritz Workspace Chat"}


def _effective_source_policy(workspace_settings: dict[str, Any], system_settings: dict[str, Any], system_flow: dict[str, Any]) -> dict[str, Any]:
    """Layer the chat System policy over the workspace policy (System shadows).

    Inline equivalent of ``resolve_workspace_chat_source_policy``: the System
    ``settings.source_policy`` (then ``flow_definition.source_policy``) wins, the
    workspace level only fills keys the System leaves unset.
    """
    workspace_policy = workspace_settings.get("source_policy")
    workspace_policy = workspace_policy if isinstance(workspace_policy, dict) else {}
    system_policy = system_settings.get("source_policy")
    if not isinstance(system_policy, dict) or not system_policy:
        system_policy = system_flow.get("source_policy")
    system_policy = system_policy if isinstance(system_policy, dict) else {}
    return {**workspace_policy, **system_policy}


def _build_membrane_spec(effective: dict[str, Any], voice_loop: dict[str, Any]) -> dict[str, Any]:
    """Canonical MembraneSpec JSON (matches MembraneSpec.to_dict shape).

    Enforcement-inert by default: capabilities/valve thresholds stay empty so a
    derived run behaves exactly as before; the voice budgets are recorded as an
    advisory circuit-breaker, and the inbound/outbound/provenance facets mirror
    the effective source_policy.
    """
    review = effective.get("expert_review_required")
    circuit_breaker = {k: voice_loop[k] for k in ("silence_ms", "min_speech_ms", "max_turn_ms") if k in voice_loop} or None
    return {
        "version": 1,
        "inbound": {
            "collection_allowlist": [],
            "reference_type_filters": [],
            "reject_cross_project_sources": bool(effective.get("reject_cross_project_sources")),
            "preserve_reference_types": bool(effective.get("preserve_reference_types")),
            "expert_fiche_correction_enabled": bool(effective.get("expert_fiche_correction_enabled")),
            "industrial_grounding": bool(effective.get("industrial_grounding")),
        },
        "outbound": {
            "expert_review_required": bool(review) if review is not None else True,
            "gate_if_confidence_below": None,
        },
        "capabilities": {"allowed_skills": [], "allowed_models": []},
        "provenance": {
            "require_citations": bool(effective.get("require_citations")),
            "object_store_prefix": "membrane/andritz/",
        },
        "valves": {
            "max_cost_per_decision": None,
            "max_latency_ms": None,
            "mandatory_hitl_if_confidence_below": None,
            "hard_abort": False,
            "circuit_breaker": circuit_breaker,
            "token_budget": None,
        },
    }


def _tables(bind):
    workspaces = sa.table(
        "workspaces",
        sa.column("id"),
        sa.column("slug"),
        sa.column("settings", sa.JSON()),
    )
    systems = sa.table(
        "systems",
        sa.column("id"),
        sa.column("workspace_id"),
        sa.column("name"),
        sa.column("flow_definition", sa.JSON()),
        sa.column("settings", sa.JSON()),
        sa.column("control_policy_id"),
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
    return workspaces, systems, control_policies


def _find_chat_system(bind, systems, workspace_id) -> Optional[dict[str, Any]]:
    rows = bind.execute(
        sa.select(
            systems.c.id,
            systems.c.name,
            systems.c.flow_definition,
            systems.c.settings,
            systems.c.control_policy_id,
        ).where(systems.c.workspace_id == workspace_id)
    ).all()
    for row in rows:
        data = row._mapping
        settings = _as_settings(data["settings"])
        flow = _as_settings(data["flow_definition"])
        if _is_workspace_chat_system(settings, flow, str(data["name"] or "")):
            return dict(data)
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if not {"workspaces", "systems", "control_policies"}.issubset(table_names):
        return

    workspaces, systems, control_policies = _tables(bind)
    ws_rows = bind.execute(
        sa.select(workspaces.c.id, workspaces.c.settings).where(workspaces.c.slug == "andritz")
    ).all()

    for ws in ws_rows:
        ws_data = ws._mapping
        ws_settings = _as_settings(ws_data["settings"])
        chat = _find_chat_system(bind, systems, ws_data["id"])
        if chat is None:
            continue

        system_settings = _as_settings(chat["settings"])
        system_flow = _as_settings(chat["flow_definition"])
        effective = _effective_source_policy(ws_settings, system_settings, system_flow)
        voice_loop = ws_settings.get("voice_loop") if isinstance(ws_settings.get("voice_loop"), dict) else {}
        spec = _build_membrane_spec(effective, voice_loop)

        # Preserve layering: mirror the expert-correction keys from the
        # effective policy onto the chat System settings (inline equivalent of
        # ``sync_chat_system_expert_correction_policy``), set-if-changed.
        sys_policy = system_settings.get("source_policy")
        sys_policy = sys_policy if isinstance(sys_policy, dict) else {}
        sys_changed = False
        for key in _EXPERT_CORRECTION_KEYS:
            if key in effective and sys_policy.get(key) != effective[key]:
                sys_policy[key] = effective[key]
                sys_changed = True
        if sys_changed:
            system_settings["source_policy"] = sys_policy
            bind.execute(
                sa.update(systems).where(systems.c.id == chat["id"]).values(settings=system_settings)
            )

        # Locate an existing membrane policy WE seeded for this System.
        existing = bind.execute(
            sa.select(control_policies.c.id, control_policies.c.extra).where(
                control_policies.c.scope == "system",
                control_policies.c.target_id == chat["id"],
            )
        ).all()
        ours = None
        for row in existing:
            extra = _as_settings(row._mapping["extra"])
            if extra.get("membrane_origin") == _MEMBRANE_ORIGIN:
                ours = (row._mapping["id"], extra)
                break

        now = datetime.utcnow()
        if ours is None:
            policy_id = str(uuid4())
            extra = {"membrane_origin": _MEMBRANE_ORIGIN, "membrane_spec": spec}
            bind.execute(
                control_policies.insert().values(
                    id=policy_id,
                    workspace_id=ws_data["id"],
                    name="Andritz Process Membrane",
                    scope="system",
                    target_id=chat["id"],
                    max_cost_per_decision=None,
                    max_latency_ms=None,
                    mandatory_hitl_if_confidence_below=None,
                    allowed_models=[],
                    allowed_skills=[],
                    extra=extra,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            policy_id, extra = ours
            prior = extra.get("membrane_spec") if isinstance(extra.get("membrane_spec"), dict) else {}
            prior_valves = prior.get("valves") if isinstance(prior.get("valves"), dict) else {}
            # Authoritative on the contract; set-if-absent on operator-tunable
            # valve keys so a hand-tuned cap/breaker survives re-runs.
            merged_valves = dict(spec["valves"])
            for key, value in prior_valves.items():
                if value is not None:
                    merged_valves[key] = value
            spec["valves"] = merged_valves
            extra["membrane_spec"] = spec
            extra["membrane_origin"] = _MEMBRANE_ORIGIN
            bind.execute(
                sa.update(control_policies)
                .where(control_policies.c.id == policy_id)
                .values(extra=extra, updated_at=now)
            )

        # Bind the System to the membrane policy when not already pointed at one.
        if not chat.get("control_policy_id"):
            bind.execute(
                sa.update(systems).where(systems.c.id == chat["id"]).values(control_policy_id=policy_id)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if not {"workspaces", "systems", "control_policies"}.issubset(table_names):
        return

    workspaces, systems, control_policies = _tables(bind)
    ws_rows = bind.execute(
        sa.select(workspaces.c.id).where(workspaces.c.slug == "andritz")
    ).all()
    ws_ids = [row._mapping["id"] for row in ws_rows]
    if not ws_ids:
        return

    # Find the membrane policies we seeded for Andritz workspaces.
    policy_rows = bind.execute(
        sa.select(control_policies.c.id, control_policies.c.extra).where(
            control_policies.c.workspace_id.in_(ws_ids),
            control_policies.c.scope == "system",
        )
    ).all()
    for row in policy_rows:
        extra = _as_settings(row._mapping["extra"])
        if extra.get("membrane_origin") != _MEMBRANE_ORIGIN:
            continue
        policy_id = row._mapping["id"]
        # Detach any System bound to this policy before deleting it.
        bind.execute(
            sa.update(systems)
            .where(systems.c.control_policy_id == policy_id)
            .values(control_policy_id=None)
        )
        bind.execute(
            sa.delete(control_policies).where(control_policies.c.id == policy_id)
        )
