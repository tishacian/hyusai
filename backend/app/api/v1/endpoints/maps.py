"""Workspace map system API."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.models.workspace_map import WorkspaceMapScore, WorkspaceMapZone
from app.services.workspace_jobs import create_workspace_job, serialize_job
from app.services.workspace_maps import (
    ensure_workspace_map_seed,
    get_workspace_map,
    list_workspace_maps,
    mission_room_map_payload,
    score_map_zones,
    serialize_map,
    serialize_score,
    serialize_zone,
)


router = APIRouter()


class MapSignalCreate(BaseModel):
    zone_key: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=1, max_length=255)
    summary: str = ""
    weight: int = Field(default=10, ge=0, le=100)
    confidence: float = Field(default=0.65, ge=0, le=1)
    source_kind: str = "operator"
    source_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/")
async def maps_list(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    rows = list_workspace_maps(db, workspace)
    return {"maps": [serialize_map(row, db) for row in rows]}


@router.get("/{map_id_or_slug}")
async def maps_detail(
    map_id_or_slug: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        row = get_workspace_map(db, workspace, map_id_or_slug)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Workspace map not found") from exc
    return {"map": serialize_map(row, db), **mission_room_map_payload(db, workspace)}


@router.get("/{map_id_or_slug}/zones")
async def maps_zones(
    map_id_or_slug: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        row = get_workspace_map(db, workspace, map_id_or_slug)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Workspace map not found") from exc
    zones = db.query(WorkspaceMapZone).filter(WorkspaceMapZone.map_id == row.id).order_by(WorkspaceMapZone.level.desc()).all()
    scores = {
        score.zone_id: score
        for score in db.query(WorkspaceMapScore).filter(WorkspaceMapScore.map_id == row.id).order_by(WorkspaceMapScore.computed_at.desc()).all()
    }
    return {"zones": [serialize_zone(zone, scores.get(zone.id)) for zone in zones]}


@router.post("/{map_id_or_slug}/score")
async def maps_score(
    map_id_or_slug: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        row = get_workspace_map(db, workspace, map_id_or_slug)
    except LookupError:
        row = ensure_workspace_map_seed(db, workspace)
    job = create_workspace_job(
        db,
        workspace,
        user,
        kind="map_zone_scoring",
        title=f"Scoring carte · {row.name}",
        input_ref={"map_id": row.id, "slug": row.slug},
        status="queued",
    )
    result = score_map_zones(db, workspace, row, job=job, user=user)
    db.commit()
    return {"job": serialize_job(job), "result": result, **mission_room_map_payload(db, workspace)}


@router.get("/{map_id_or_slug}/recommendations")
async def maps_recommendations(
    map_id_or_slug: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        row = get_workspace_map(db, workspace, map_id_or_slug)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Workspace map not found") from exc
    scores = db.query(WorkspaceMapScore).filter(WorkspaceMapScore.map_id == row.id).order_by(WorkspaceMapScore.score.desc()).all()
    return {"recommendations": [serialize_score(score) for score in scores]}
