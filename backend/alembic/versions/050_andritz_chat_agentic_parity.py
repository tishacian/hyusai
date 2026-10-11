"""Re-wire the "Andritz Chat Agentic" System flow_definition (A/B parity fix).

Updates the live System's ``flow_definition`` (and refreshes ``skill_ids``) from
the corrected pinned artifact
``app/resources/flows/andritz_chat_agentic_v3.json`` so the seeded DAG reflects
the recall / OOS / routing parity fixes (2026-06-26) on top of migration 049:

  * RECALL — retrieve_* nodes now carry the full per-lane budget triple
    (top_k/synthesis_k/candidate_pool_k = chat._apply_retrieval_budget_policy),
    so a lone top_k pin no longer collapses the candidate pool (DAG was ~6 ctx
    vs classic ~12 and missed carrier chunks);
  * OOS — decision.deliver only honours ``reject_oos`` when ``context_count == 0``
    (runtime backstop to the planner-side known-entity demotion);
  * ROUTING — inventory/transversal questions are forced to the deep lane
    (planner-side, reflected in the deep retrieve node);
  * VERDICT — decision.verdict drops the unusable ``hallucination_rate`` term
    (response_eval derives it as 1 - embedding factuality ~0.3-0.5, so the
    >0.15 threshold fired self_correct on EVERY run -> latency aborts + lossy
    deep swaps). The quality floor is now ``composite < 50 or context_count == 0``;
  * SELF_CORRECT — task.self_correct receives the original ``context``
    (join.retrieval.results) so escalate_deep MERGES it with the deep re-retrieval
    (never loses carrier chunks) and never downgrades a grounded draft to an
    abstention.

Generation/skill-side companions (in ``skills_registry/wrappers.py``, not flow
shape): the grounded synthesis prompt now mirrors the classic FACTUAL framing
(extract values from FR/EN/DE HTML tables instead of abstaining);
``_pick_self_correct_action`` no longer triggers on the embedding hallucination
proxy; and ``semantic_search_v1`` arms the classic ``transversal_inventory``
project_code facet for "which projects use X" questions, surfacing the
exhaustive enumeration as the top context passage.

The behavioural fixes themselves live in the provider-neutral skills
(``skills_registry/wrappers.py``); this migration only re-seeds the *flow shape*
(new retrieve budgets inputs_map, deliver context_count gate, descriptions) so
the DB matches the artifact. Idempotent and revertible:

  * idempotent — re-running updates in place; the pre-050 (i.e. 049) flow is
    snapshotted into ``systems.settings['flow_backup_pre_050']`` exactly ONCE
    (guarded by ``settings['flow_revision'] == this revision``).
  * revertible — ``downgrade`` restores the snapshot and resets ``flow_revision``
    to the prior (049) tag so the 049 downgrade chain stays intact.

Data-only (no DDL). Marker-scoped to the System 048 seeded
(``settings.seed_origin == '048_andritz_chat_agentic'``) so an operator-authored
System sharing the name is never touched.

Revision ID: 050_andritz_chat_agentic_parity  (<= 32 chars)
Revises: 049_andritz_chat_grounding
Create Date: 2026-06-26
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from alembic import op
import sqlalchemy as sa


revision = "050_andritz_chat_agentic_parity"
down_revision = "049_andritz_chat_grounding"
branch_labels = None
depends_on = None


_REVISION_TAG = "050_andritz_chat_agentic_parity"
_PRIOR_REVISION_TAG = "049_andritz_chat_grounding"  # restored on downgrade
_SEED_ORIGIN = "048_andritz_chat_agentic"  # marker stamped by migration 048
_SYSTEM_NAME = "Andritz Chat Agentic"
_BACKUP_KEY = "flow_backup_pre_050"
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


def _load_flow() -> Optional[dict[str, Any]]:
    try:
        with _ARTIFACT_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    flow = _as_dict(data.get("flow_definition")) if isinstance(data, dict) else {}
    return flow or None


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
        sa.column("status"),
        sa.column("updated_at", sa.DateTime()),
    )
    return skills, systems


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
        sa.select(systems.c.id, systems.c.settings, systems.c.flow_definition).where(
            systems.c.name == _SYSTEM_NAME
        )
    ).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        if _as_dict(row._mapping["settings"]).get("seed_origin") == _SEED_ORIGIN:
            out.append(row._mapping)
    return out


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not {"systems", "skills"}.issubset(set(inspector.get_table_names())):
        return

    flow = _load_flow()
    if not flow:
        return

    skills, systems = _tables()
    skill_ids = _resolve_flow_skill_ids(bind, skills, flow)
    now = datetime.utcnow()

    for sysrow in _target_systems(bind, systems):
        system_id = sysrow["id"]
        settings = _as_dict(sysrow["settings"])
        # Snapshot the pre-050 (049) flow exactly once (so downgrade is faithful).
        if settings.get(_REVISION_KEY) != _REVISION_TAG and _BACKUP_KEY not in settings:
            settings[_BACKUP_KEY] = sysrow["flow_definition"]
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

    _skills, systems = _tables()
    now = datetime.utcnow()

    for sysrow in _target_systems(bind, systems):
        system_id = sysrow["id"]
        settings = _as_dict(sysrow["settings"])
        if settings.get(_REVISION_KEY) != _REVISION_TAG:
            continue
        restored = settings.pop(_BACKUP_KEY, None)
        # Reset the shared revision marker to the prior tag so the 049 downgrade
        # chain (which guards on flow_revision == 049 tag) still works.
        settings[_REVISION_KEY] = _PRIOR_REVISION_TAG
        values: dict[str, Any] = {"settings": settings, "updated_at": now}
        if isinstance(restored, dict) and restored:
            values["flow_definition"] = restored
        bind.execute(
            sa.update(systems).where(systems.c.id == system_id).values(**values)
        )
