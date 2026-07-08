"""Re-wire the "Andritz Chat Agentic" System flow_definition (latency + multi-hop).

Updates the live System's ``flow_definition`` (and refreshes ``skill_ids`` +
the bound membrane ``ControlPolicy.allowed_skills`` / ``extra.membrane_spec``)
from the corrected pinned artifact
``app/resources/flows/andritz_chat_agentic_v3.json`` so the seeded DAG reflects
the Phase 2 (latency) + Phase 4 (multi-hop) roadmap items on top of migration
050:

  * LATENCY (Phase 2) — the two LLM judges (``eval_radar_v1`` /
    ``claim_audit_v1``) are pulled OFF the verdict/egress critical path.
    ``task.generate`` now feeds ``task.response_eval`` (embeddings) directly, and
    ``response_eval`` feeds ``decision.verdict`` directly; ``fork.self_eval`` fans
    only the two judges into ``join.eval``, which becomes a TERMINAL telemetry
    sink (computed + logged, no longer gating the answer). The verdict/egress
    path is therefore no longer a static descendant of the LLM judges.
  * MULTI-HOP (Phase 4) — a new retrieval lane ``task.retrieve_multihop``
    (skill ``multi_hop_retrieve_v1``) is selected FIRST by
    ``decision.route_mode`` when the planner emitted ``sub_queries`` (comparison
    / multi-hop / transversal profiles). It runs N parallel ``semantic_search_v1``
    passes and merges/dedupes into the uniform ``results[]`` shape, feeding
    ``join.retrieval`` with single-active-lane semantics preserved. The planner
    (``chat_agentic_plan_v1``) now also emits the ``sub_queries`` port.

The behavioural changes live in the provider-neutral skills
(``skills_registry/wrappers.py`` + ``seed.py``); this migration re-seeds the
*flow shape* AND the capability allow-list so the DB matches the artifact and
the new ``multi_hop_retrieve_v1`` lane is not blocked by the membrane gate. It
also upserts the ``multi_hop_retrieve_v1`` skill by slug (insert-if-absent) so
``skill_id`` resolution never leaves a hole regardless of seed ordering.

Idempotent and revertible:

  * idempotent — re-running updates in place; the pre-051 (i.e. 050) flow AND
    the pre-051 policy allow-list/membrane are snapshotted into
    ``systems.settings['flow_backup_pre_051']`` / ``['policy_backup_pre_051']``
    exactly ONCE (guarded by ``settings['flow_revision'] == this revision``).
  * revertible — ``downgrade`` restores both snapshots and resets
    ``flow_revision`` to the prior (050) tag so the 050 downgrade chain stays
    intact.

Data-only (no DDL). Marker-scoped to the System 048 seeded
(``settings.seed_origin == '048_andritz_chat_agentic'``) so an operator-authored
System sharing the name is never touched.

Revision ID: 051_andritz_chat_latency_mh  (<= 32 chars)
Revises: 050_andritz_chat_parity
Create Date: 2026-07-08
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


revision = "051_andritz_chat_latency_mh"
down_revision = "050_andritz_chat_parity"
branch_labels = None
depends_on = None


_REVISION_TAG = "051_andritz_chat_latency_mh"
_PRIOR_REVISION_TAG = "050_andritz_chat_parity"  # restored on downgrade
_SEED_ORIGIN = "048_andritz_chat_agentic"  # marker stamped by migration 048
_SYSTEM_NAME = "Andritz Chat Agentic"
_FLOW_BACKUP_KEY = "flow_backup_pre_051"
_POLICY_BACKUP_KEY = "policy_backup_pre_051"
_REVISION_KEY = "flow_revision"

# New skill this revision wires into the flow — upserted by slug (insert-if-
# absent) so skill_id resolution is complete even before the catalog seed runs.
# The authoritative schema lives in ``app/services/skills_registry/seed.py``.
_REQUIRED_SKILLS = [
    {
        "slug": "multi_hop_retrieve_v1",
        "name": "Multi-Hop Retrieve",
        "type": "retrieval",
        "description": "Decomposed multi-hop retrieval: N parallel semantic_search_v1 passes over the planner sub_queries, merged/deduped into the same results[] shape.",
        "certification_level": "production",
        "provider": "internal",
    },
]

_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "resources"
    / "flows"
    / "andritz_chat_agentic_v3.json"
)


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
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _tables():
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
        sa.column("skill_ids", sa.JSON()),
        sa.column("flow_definition", sa.JSON()),
        sa.column("settings", sa.JSON()),
        sa.column("control_policy_id"),
        sa.column("status"),
        sa.column("updated_at", sa.DateTime()),
    )
    control_policies = sa.table(
        "control_policies",
        sa.column("id"),
        sa.column("allowed_skills", sa.JSON()),
        sa.column("extra", sa.JSON()),
        sa.column("updated_at", sa.DateTime()),
    )
    return skills, systems, control_policies


def _ensure_required_skills(bind, skills, now) -> None:
    """Upsert the new skill(s) by slug (insert-if-absent)."""
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
    """Fill each task node's ``config.skill_id`` from ``skill_slug`` (in place)."""
    slugs = {
        (node.get("config") or {}).get("skill_slug")
        for node in flow.get("nodes") or []
        if isinstance(node, dict) and (node.get("config") or {}).get("skill_slug")
    }
    id_by_slug: dict[str, str] = {}
    if slugs:
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


def _target_systems(bind, systems) -> list[dict[str, Any]]:
    """Return the System rows we (migration 048) seeded, marker-scoped."""
    rows = bind.execute(
        sa.select(
            systems.c.id,
            systems.c.settings,
            systems.c.flow_definition,
            systems.c.control_policy_id,
        ).where(systems.c.name == _SYSTEM_NAME)
    ).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        if _as_dict(row._mapping["settings"]).get("seed_origin") == _SEED_ORIGIN:
            out.append(row._mapping)
    return out


def _refresh_membrane_policy(
    bind, control_policies, policy_id, membrane, settings, now
) -> None:
    """Refresh the bound membrane policy's allow-list from the artifact.

    Snapshots the pre-051 ``allowed_skills`` + ``extra`` into ``settings`` exactly
    once so downgrade restores them, then updates the policy's ``allowed_skills``
    column and ``extra['membrane_spec']`` to the artifact's (which now lists
    ``multi_hop_retrieve_v1``) — the runtime capability gate reads
    ``extra['membrane_spec'].capabilities.allowed_skills``.
    """
    if not policy_id:
        return
    caps = membrane.get("capabilities") if isinstance(membrane.get("capabilities"), dict) else {}
    allowed_skills = caps.get("allowed_skills") or []

    prow = bind.execute(
        sa.select(control_policies.c.allowed_skills, control_policies.c.extra).where(
            control_policies.c.id == policy_id
        )
    ).first()
    if prow is None:
        return

    if _POLICY_BACKUP_KEY not in settings:
        settings[_POLICY_BACKUP_KEY] = {
            "allowed_skills": prow._mapping["allowed_skills"],
            "extra": prow._mapping["extra"],
        }

    extra = _as_dict(prow._mapping["extra"])
    extra["membrane_spec"] = membrane
    bind.execute(
        sa.update(control_policies)
        .where(control_policies.c.id == policy_id)
        .values(allowed_skills=allowed_skills, extra=extra, updated_at=now)
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not {"systems", "skills"}.issubset(set(inspector.get_table_names())):
        return

    artifact = _load_artifact()
    if not artifact:
        return
    flow = _as_dict(artifact.get("flow_definition"))
    membrane = _as_dict(artifact.get("membrane_spec"))
    if not flow:
        return

    has_policies = "control_policies" in set(inspector.get_table_names())
    skills, systems, control_policies = _tables()
    now = datetime.utcnow()
    _ensure_required_skills(bind, skills, now)
    skill_ids = _resolve_flow_skill_ids(bind, skills, flow)

    for sysrow in _target_systems(bind, systems):
        system_id = sysrow["id"]
        settings = _as_dict(sysrow["settings"])
        # Snapshot the pre-051 (050) flow exactly once (so downgrade is faithful).
        if settings.get(_REVISION_KEY) != _REVISION_TAG and _FLOW_BACKUP_KEY not in settings:
            settings[_FLOW_BACKUP_KEY] = sysrow["flow_definition"]
        # Refresh the bound membrane allow-list (snapshots into settings once).
        if has_policies and membrane:
            _refresh_membrane_policy(
                bind, control_policies, sysrow.get("control_policy_id"), membrane, settings, now
            )
        settings[_REVISION_KEY] = _REVISION_TAG
        bind.execute(
            sa.update(systems)
            .where(systems.c.id == system_id)
            .values(
                flow_definition=flow,
                skill_ids=skill_ids,
                settings=settings,
                status="active",
                updated_at=now,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not {"systems"}.issubset(set(inspector.get_table_names())):
        return

    has_policies = "control_policies" in set(inspector.get_table_names())
    _skills, systems, control_policies = _tables()
    now = datetime.utcnow()

    for sysrow in _target_systems(bind, systems):
        system_id = sysrow["id"]
        settings = _as_dict(sysrow["settings"])
        if settings.get(_REVISION_KEY) != _REVISION_TAG:
            continue
        restored_flow = settings.pop(_FLOW_BACKUP_KEY, None)
        policy_backup = settings.pop(_POLICY_BACKUP_KEY, None)
        # Reset the shared revision marker to the prior tag so the 050 downgrade
        # chain (which guards on flow_revision == 050 tag) still works.
        settings[_REVISION_KEY] = _PRIOR_REVISION_TAG

        # Restore the pre-051 membrane allow-list on the bound policy.
        if has_policies and isinstance(policy_backup, dict) and sysrow.get("control_policy_id"):
            bind.execute(
                sa.update(control_policies)
                .where(control_policies.c.id == sysrow["control_policy_id"])
                .values(
                    allowed_skills=policy_backup.get("allowed_skills") or [],
                    extra=policy_backup.get("extra"),
                    updated_at=now,
                )
            )

        values: dict[str, Any] = {"settings": settings, "updated_at": now}
        if isinstance(restored_flow, dict) and restored_flow:
            values["flow_definition"] = restored_flow
        bind.execute(
            sa.update(systems).where(systems.c.id == system_id).values(**values)
        )
