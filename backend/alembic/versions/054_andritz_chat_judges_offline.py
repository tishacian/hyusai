"""Re-wire the "Andritz Chat Agentic" flow_definition — LLM judges offline (latency).

Phase A latency fix (2026-07-09). Re-seeds the live System's ``flow_definition``
(and refreshes ``skill_ids`` + the bound membrane ``ControlPolicy``) from the
corrected pinned artifact ``app/resources/flows/andritz_chat_agentic_v3.json``.

Root cause addressed: the DAG walker (``execute_run_dag``) finalises a run only
after EVERY reachable node settles, and each tick's ``asyncio.gather`` waits for
the whole ready set — so the two in-DAG LLM judges (``eval_radar_v1`` ~20s and
``claim_audit_v1`` ~21s), scheduled in the same tick as ``decision.verdict``,
sat on the wall-clock critical path of the answer egress (~+40s, ~60% of runs
tripping the 45s membrane valve) even though Phase 2 had already removed them
from the *content* of the verdict. There is no native fire-and-forget in the
engine.

Fix (lowest-risk, artifact-only): REMOVE ``task.eval_radar`` + ``task.claim_audit``
(and their edges) from the ONLINE serving DAG (23 -> 21 nodes). ``task.generate``
feeds ``task.response_eval`` (embeddings, fast) which feeds ``decision.verdict``
directly (unchanged verdict gate: ``composite < 50 or context_count == 0``). The
``fork.self_eval -> join.eval`` pair is retained as an INSTANT terminal telemetry
no-op (zero skill, zero LLM) — it preserves the fork/join balance the two
data-joins (``join.retrieval`` / ``join.answer``, fan-ins driven by decision
nodes) rely on for a clean ``dag_validator`` pass. The two LLM judges remain in
``membrane_spec.capabilities.allowed_skills`` (available) and are still exercised
OFFLINE by the A/B harness ``backend/scripts/agentic_chat_spike.py`` (which calls
JudgeService / ResponseEvaluator directly) — they were a measurement instrument,
not a serving requirement.

Idempotent and revertible (mirrors migration 051):

  * idempotent — re-running updates in place; the pre-054 flow AND the pre-054
    policy allow-list/membrane are snapshotted into
    ``systems.settings['flow_backup_pre_054']`` / ``['policy_backup_pre_054']``
    exactly ONCE (guarded by ``settings['flow_revision'] == this revision``).
  * revertible — ``downgrade`` restores both snapshots and resets
    ``flow_revision`` to the prior (051) tag so the 051 downgrade chain stays
    intact.

Data-only (no DDL). Marker-scoped to the System 048 seeded
(``settings.seed_origin == '048_andritz_chat_agentic'``) so an operator-authored
System sharing the name is never touched.

Revision ID: 054_andritz_chat_judges_offline  (<= 32 chars)
Revises: 053_client360_chat_merge
Create Date: 2026-07-09
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from alembic import op
import sqlalchemy as sa


revision = "054_andritz_chat_judges_offline"
down_revision = "053_client360_chat_merge"
branch_labels = None
depends_on = None


_REVISION_TAG = "054_andritz_chat_judges_offline"
_PRIOR_REVISION_TAG = "051_andritz_chat_latency_mh"  # restored on downgrade
_SEED_ORIGIN = "048_andritz_chat_agentic"  # marker stamped by migration 048
_SYSTEM_NAME = "Andritz Chat Agentic"
_FLOW_BACKUP_KEY = "flow_backup_pre_054"
_POLICY_BACKUP_KEY = "policy_backup_pre_054"
_REVISION_KEY = "flow_revision"

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


def _resolve_flow_skill_ids(bind, skills, flow: dict[str, Any]) -> list[str]:
    """Fill each task node's ``config.skill_id`` from ``skill_slug`` (in place).

    All skills referenced by the flow are already present (upserted by migrations
    048 / 051); this only resolves ids and returns the deduped ordered list.
    """
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
    """Return the System rows migration 048 seeded, marker-scoped."""
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

    Snapshots the pre-054 ``allowed_skills`` + ``extra`` into ``settings`` exactly
    once so downgrade restores them, then updates the policy's ``allowed_skills``
    column and ``extra['membrane_spec']`` to the artifact's.
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
    skill_ids = _resolve_flow_skill_ids(bind, skills, flow)

    for sysrow in _target_systems(bind, systems):
        system_id = sysrow["id"]
        settings = _as_dict(sysrow["settings"])
        # Snapshot the pre-054 flow exactly once (so downgrade is faithful).
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
        # Reset the shared revision marker to the prior tag so the 051 downgrade
        # chain (which guards on flow_revision == 051 tag) still works.
        settings[_REVISION_KEY] = _PRIOR_REVISION_TAG

        # Restore the pre-054 membrane allow-list on the bound policy.
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
