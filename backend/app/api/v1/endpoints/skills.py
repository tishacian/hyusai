"""Canonical /skills endpoints — Registry with certification + metrics.

Skills are mostly read-only from the UI: the registry is seeded from the
in-process `app.services.skills_registry` and metrics are aggregated from
`SkillInvocation` records.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.workspace import Workspace
from app.services.catalog_visibility import (
    skill_is_visible,
    visible_capabilities,
    visible_skill_ids_from_capabilities,
    workspace_catalog_policy,
)

router = APIRouter()


def _runtime_status(slug: str) -> str:
    """Resolve the canonical 4-state runtime status for a skill slug.

    Returns one of ``bound`` | ``stub`` | ``unbound`` | ``catalog_only``.
    ``catalog_only`` means the Skill row exists in the database but has
    no registered wrapper — useful to flag "declared-but-unimplemented"
    capabilities in the UI.
    """
    from app.services.skills_registry import registry_snapshot

    snap = registry_snapshot()
    entry = snap.get(slug)
    if entry is None:
        return "catalog_only"
    return entry.get("status", "unbound")


def _serialize(s: Skill, metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "id": s.id,
        "slug": s.slug,
        "version": s.version,
        "name": s.name,
        "description": s.description,
        "type": s.type,
        "input_schema": s.input_schema or {},
        "output_schema": s.output_schema or {},
        "execution": s.execution or {},
        "pricing": s.pricing or {},
        "certification_level": s.certification_level,
        "is_seeded": s.is_seeded == "Y",
        "provider": s.provider,
        "metrics": metrics or s.metrics or {},
        "runtime_status": _runtime_status(s.slug),
        "workspace_scope": "global" if s.workspace_id is None else "workspace",
    }


def _visible_skill_rows(db: DBSession, workspace: Workspace) -> list[Skill]:
    """Return Skill rows visible in the current workspace catalog.

    The database registry is global, but the product surface is workspace
    filtered through visible capabilities plus explicit workspace overrides.
    """

    policy = workspace_catalog_policy(workspace)
    cap_rows = (
        db.query(Capability)
        .filter((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None)))
        .all()
    )
    visible_caps = visible_capabilities(cap_rows, workspace, policy)
    visible_skill_ids = visible_skill_ids_from_capabilities(visible_caps)
    rows = (
        db.query(Skill)
        .filter((Skill.workspace_id == workspace.id) | (Skill.workspace_id.is_(None)))
        .all()
    )
    return [s for s in rows if skill_is_visible(s, workspace, visible_skill_ids, policy)]


@router.get("/runtime-health")
async def runtime_health(
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Report the live runtime status of every registered skill wrapper.

    Canonical 4-state: ``bound`` (real implementation), ``stub`` (degraded
    stand-in), ``unbound`` (declared in the registry but no wrapper) or
    ``catalog_only`` (exists in the Skill catalog but has no registry
    entry at all).
    """
    from app.services.skills_registry import registry_snapshot

    snapshot = registry_snapshot()
    visible_rows = _visible_skill_rows(db, workspace)
    visible_slugs = {s.slug for s in visible_rows}
    snapshot = {
        slug: entry
        for slug, entry in snapshot.items()
        if slug in visible_slugs
    }
    summary = {"bound": 0, "stub": 0, "unbound": 0, "catalog_only": 0}
    for entry in snapshot.values():
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1

    catalog_slugs = visible_slugs
    catalog_only = catalog_slugs - set(snapshot.keys())
    summary["catalog_only"] = len(catalog_only)
    for slug in catalog_only:
        snapshot[slug] = {"status": "catalog_only", "declared_status": None, "module": None}
    return {"skills": snapshot, "summary": summary}


@router.get("")
async def list_skills(
    skill_type: Optional[str] = None,
    certification: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    rows = _visible_skill_rows(db, workspace)
    if skill_type:
        rows = [row for row in rows if row.type == skill_type]
    if certification:
        rows = [row for row in rows if row.certification_level == certification]
    rows = sorted(rows, key=lambda row: (row.type or "", row.name or ""))

    # Aggregate live metrics per slug.
    metrics_by_slug = _aggregate_metrics(db, workspace.id, [r.slug for r in rows])
    return {"skills": [_serialize(s, metrics_by_slug.get(s.slug)) for s in rows]}


@router.get("/{slug}")
async def get_skill(
    slug: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    s = db.query(Skill).filter(
        Skill.slug == slug,
        ((Skill.workspace_id == workspace.id) | (Skill.workspace_id.is_(None))),
    ).first()
    if not s:
        raise HTTPException(404, "Skill not found")
    if s.slug not in {row.slug for row in _visible_skill_rows(db, workspace)}:
        raise HTTPException(404, "Skill not found")
    metrics = _aggregate_metrics(db, workspace.id, [s.slug]).get(s.slug)
    return _serialize(s, metrics)


def _aggregate_metrics(db: DBSession, workspace_id: str, slugs):
    """Light-weight aggregation: count + avg latency + success rate per slug."""
    if not slugs:
        return {}
    rows = (
        db.query(
            SkillInvocation.skill_slug,
            func.count(SkillInvocation.id),
            func.avg(SkillInvocation.latency_ms),
            func.sum(SkillInvocation.cost),
            func.sum(
                case((SkillInvocation.status == "completed", 1), else_=0)
            ),
        )
        .join(Run, Run.id == SkillInvocation.run_id)
        .filter(Run.workspace_id == workspace_id)
        .filter(SkillInvocation.skill_slug.in_(slugs))
        .group_by(SkillInvocation.skill_slug)
        .all()
    )
    out: Dict[str, Dict[str, Any]] = {}
    for slug, count, avg_lat, total_cost, ok in rows:
        out[slug] = {
            "calls": int(count or 0),
            "avg_latency_ms": float(avg_lat) if avg_lat is not None else None,
            "total_cost": float(total_cost or 0.0),
            "success_rate": float(ok or 0) / float(count) if count else None,
        }
    return out
