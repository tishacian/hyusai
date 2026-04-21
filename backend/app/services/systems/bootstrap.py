"""Canonical System seed hooks.

`/intelligence` is no longer a bespoke feature page: it is a real ``System``
row bound to the ``market_signal_brief`` capability, so the frontend can
use the same SystemViewComponent to render it with the intelligence-specific
facets. This module provides the idempotent seeding hook called at startup
for every existing workspace (Vague A — P0, commit 2/5).
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy.orm import Session as DBSession

from app.core.logging import get_logger
from app.models.capability import Capability
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace

logger = get_logger(__name__)


INTELLIGENCE_SYSTEM_NAME = "News Lab"
INTELLIGENCE_OBJECTIVE = (
    "Continuous market intelligence tuned to your semantic targets. "
    "The scheduler harvests RSS feeds every hour, scores articles against "
    "your targets, and surfaces decision-grade briefs."
)
INTELLIGENCE_CAPABILITY_SLUG = "market_signal_brief"
INTELLIGENCE_SKILL_SLUG = "intelligence_batch_v1"


def ensure_intelligence_system_default(
    db: DBSession, workspace_id: str
) -> Optional[System]:
    """Create the workspace's default Intelligence System if missing.

    Idempotent on ``(workspace_id, capability_id, name=INTELLIGENCE_SYSTEM_NAME)``.
    Returns the (existing or newly created) System, or ``None`` if the
    required capability/skill haven't been seeded yet.
    """
    capability = (
        db.query(Capability)
        .filter(Capability.slug == INTELLIGENCE_CAPABILITY_SLUG)
        .first()
    )
    if not capability:
        logger.warning(
            "intel_system_seed.skip.missing_capability",
            workspace_id=workspace_id,
            slug=INTELLIGENCE_CAPABILITY_SLUG,
        )
        return None

    skill = (
        db.query(Skill).filter(Skill.slug == INTELLIGENCE_SKILL_SLUG).first()
    )
    skill_ids: List[str] = [skill.id] if skill else []

    existing = (
        db.query(System)
        .filter(
            System.workspace_id == workspace_id,
            System.capability_id == capability.id,
            System.name == INTELLIGENCE_SYSTEM_NAME,
        )
        .first()
    )
    if existing:
        # Lightweight refresh so flow_definition.variant stays in sync even
        # if an older seed produced a bare row.
        flow = dict(existing.flow_definition or {})
        if flow.get("variant") != "intelligence":
            flow["variant"] = "intelligence"
            flow.setdefault("nodes", [])
            flow.setdefault("edges", [])
            existing.flow_definition = flow
            db.commit()
        return existing

    flow_definition: Dict[str, object] = {
        "variant": "intelligence",
        "nodes": [
            {
                "id": "source.feeds",
                "type": "source",
                "label": "RSS feeds",
            },
            {
                "id": "skill.intelligence_batch_v1",
                "type": "skill",
                "skill_slug": INTELLIGENCE_SKILL_SLUG,
                "label": "Intelligence batch",
            },
            {
                "id": "sink.brief",
                "type": "sink",
                "label": "Decision-grade brief",
            },
        ],
        "edges": [
            {"from": "source.feeds", "to": "skill.intelligence_batch_v1"},
            {"from": "skill.intelligence_batch_v1", "to": "sink.brief"},
        ],
    }

    system = System(
        workspace_id=workspace_id,
        name=INTELLIGENCE_SYSTEM_NAME,
        objective=INTELLIGENCE_OBJECTIVE,
        capability_id=capability.id,
        skill_ids=skill_ids,
        flow_definition=flow_definition,
        execution_mode="continuous_monitoring",
        coordination_pattern="single_agent",
        status="active",
        created_by="system:intelligence_seed",
        retrieval_mode_default="auto",
    )
    db.add(system)
    db.commit()
    db.refresh(system)

    logger.info(
        "intel_system_seed.created",
        workspace_id=workspace_id,
        system_id=system.id,
        capability_id=capability.id,
    )
    return system


def ensure_intelligence_system_for_all_workspaces(
    db: DBSession,
) -> Dict[str, int]:
    """Ensure every active workspace has its Intelligence System seeded.

    Safe to call on every boot — the per-workspace helper is idempotent.
    Returns a small report (``{"created": N, "skipped": M}``) so the startup
    log stays readable.
    """
    report = {"created": 0, "skipped": 0, "already": 0}
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.is_active.is_(True), Workspace.deleted_at.is_(None))
        .all()
    )
    for ws in workspaces:
        before = (
            db.query(System)
            .filter(
                System.workspace_id == ws.id,
                System.name == INTELLIGENCE_SYSTEM_NAME,
            )
            .count()
        )
        system = ensure_intelligence_system_default(db, ws.id)
        if system is None:
            report["skipped"] += 1
        elif before == 0:
            report["created"] += 1
        else:
            report["already"] += 1
    return report
