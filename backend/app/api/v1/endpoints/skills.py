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
from app.models.run import SkillInvocation
from app.models.skill import Skill
from app.models.workspace import Workspace

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
    }


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
    summary = {"bound": 0, "stub": 0, "unbound": 0, "catalog_only": 0}
    for entry in snapshot.values():
        summary[entry["status"]] = summary.get(entry["status"], 0) + 1

    catalog_slugs = {
        row[0]
        for row in db.query(Skill.slug)
        .filter(
            (Skill.workspace_id == workspace.id) | (Skill.workspace_id.is_(None)),
        )
        .all()
    }
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
    q = db.query(Skill).filter(
        (Skill.workspace_id == workspace.id) | (Skill.workspace_id.is_(None))
    )
    if skill_type:
        q = q.filter(Skill.type == skill_type)
    if certification:
        q = q.filter(Skill.certification_level == certification)
    rows = q.order_by(Skill.type.asc(), Skill.name.asc()).all()

    # Aggregate live metrics per slug.
    metrics_by_slug = _aggregate_metrics(db, [r.slug for r in rows])
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
    metrics = _aggregate_metrics(db, [s.slug]).get(s.slug)
    return _serialize(s, metrics)


def _aggregate_metrics(db: DBSession, slugs):
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
