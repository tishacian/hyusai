"""Curation of the workspace Skill catalog.

``workspace.settings.catalog`` has always decided how much of the global
registry a workspace browses, with no surface to read or write it. The dormant
levers are the per-skill ones: production carries no ``hidden_skills`` at all
and ``enabled_skills`` only where a Workspace App wrote it. What actually
decides visibility is which Capabilities are visible and which Skills they
claim, so this surface reports coverage first — the lever behind every
exclusion, ranked by how many skills it releases — and treats the per-skill
overrides as the escape hatch they are.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.skill import Skill
from app.models.user import User
from app.models.workspace import Workspace
from app.services.catalog_visibility import (
    CatalogCoverage,
    capability_visibility,
    catalog_coverage,
)
from app.services.iam.decision_plane import enforce_action
from app.services.iam.legacy_authority import legacy_workspace_admin
from app.services.workspace_apps import app_owned_catalog_skills

router = APIRouter()

# The policy keys this surface owns. Anything else already under
# ``settings.catalog`` is preserved untouched on write.
_POLICY_FLAGS = ("show_universal", "show_unconfigured_industries")
_POLICY_LISTS = (
    "allowed_industries",
    "enabled_capabilities",
    "hidden_capabilities",
    "enabled_skills",
    "hidden_skills",
)


class CatalogPolicyPatch(BaseModel):
    """Replace the named levers only; omitted ones keep their stored value.

    An explicit empty ``allowed_industries`` is a decision, not an absence: it
    means this workspace allows no industry, and the family defaults must stop
    being inferred behind the admin's back.
    """

    show_universal: Optional[bool] = None
    show_unconfigured_industries: Optional[bool] = None
    allowed_industries: Optional[list[str]] = None
    enabled_capabilities: Optional[list[str]] = None
    hidden_capabilities: Optional[list[str]] = None
    enabled_skills: Optional[list[str]] = None
    hidden_skills: Optional[list[str]] = None


def _report(db: DBSession, workspace: Workspace, *, editable: bool) -> dict[str, Any]:
    capabilities = (
        db.query(Capability)
        .filter((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None)))
        .order_by(Capability.tier.asc(), Capability.name.asc())
        .all()
    )
    skills = (
        db.query(Skill)
        .filter((Skill.workspace_id == workspace.id) | (Skill.workspace_id.is_(None)))
        .all()
    )
    coverage: CatalogCoverage = catalog_coverage(
        workspace=workspace,
        capabilities=capabilities,
        skills=skills,
        override_sources=app_owned_catalog_skills(workspace),
    )
    return {
        **coverage.to_dict(),
        # Every capability an override could name, so the surface can offer a
        # choice instead of a free-text slug.
        "capabilities": [
            {
                "slug": row.slug,
                "name": row.name,
                "tier": row.tier,
                "industry": row.industry,
                "skills": len(row.skill_ids or []),
                **capability_visibility(row, workspace, coverage.policy).to_dict(),
            }
            for row in capabilities
        ],
        "editable": editable,
    }


@router.get("/curation")
async def get_catalog_curation(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Report the catalog surface, the levers behind it, and their yield."""

    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="skill",
        action="read",
        # Membership was already resolved by the workspace dependency, which
        # is the whole of the historical gate on reading the catalog.
        legacy_allowed=True,
        resource_attrs={"scope": "collection"},
    )
    return _report(db, workspace, editable=_is_workspace_admin(db, user, workspace))


@router.patch("/curation")
async def patch_catalog_curation(
    body: CatalogPolicyPatch,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Write the catalog levers and return the coverage they produce.

    Unknown slugs are stored rather than rejected: the report already marks
    them ``dangling``, and refusing the whole write would strand an admin whose
    stored policy is already carrying one.
    """

    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="skill",
        action="admin",
        legacy_allowed=_is_workspace_admin(db, user, workspace),
        resource_attrs={"scope": "collection"},
    )
    # A lever is cleared with ``[]`` or ``false``, never with ``null``; taking
    # null as "clear" would let a serialiser that emits every field wipe the
    # policy the caller only meant to read back.
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    settings = dict(workspace.settings or {})
    stored = settings.get("catalog")
    if not isinstance(stored, dict):
        # A workspace configured under the legacy key keeps its content: the
        # resolver prefers ``catalog`` once it exists, so a fresh blob here
        # would silently drop the policy it is meant to edit.
        legacy = settings.get("capability_catalog")
        stored = dict(legacy) if isinstance(legacy, dict) else {}
    catalog = dict(stored)
    for key in _POLICY_FLAGS:
        if key in patch:
            catalog[key] = bool(patch[key])
    for key in _POLICY_LISTS:
        if key in patch:
            catalog[key] = _normalized(patch[key])
    settings["catalog"] = catalog
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return _report(db, workspace, editable=True)


def _normalized(values: Any) -> list[str]:
    """Store what the resolver reads: lowercase, de-duplicated, ordered."""

    if not isinstance(values, (list, tuple, set)):
        return []
    return sorted({str(item).strip().lower() for item in values if str(item).strip()})


def _is_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> bool:
    return legacy_workspace_admin(db, user=user, workspace=workspace)
