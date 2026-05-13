"""Workspace visual intelligence API."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.object_store import get_object_store
from app.services.visual_intelligence import (
    capture_source,
    create_source,
    dashboard_payload,
    ensure_visual_intelligence_seed,
    get_capture,
    get_source,
    list_captures,
    list_sources,
    serialize_capture,
    serialize_source,
    update_source,
)


router = APIRouter()


class VisualSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    source_url: str = Field(..., min_length=1)
    description: str = ""
    source_type: str = "webcam"
    adapter: str = "http_image"
    region: str = ""
    capture_cadence_minutes: int = Field(default=60, ge=1, le=1440)
    enabled: bool = True
    policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisualSourcePatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    source_url: Optional[str] = None
    description: Optional[str] = None
    source_type: Optional[str] = None
    adapter: Optional[str] = None
    region: Optional[str] = None
    status: Optional[str] = None
    enabled: Optional[bool] = None
    capture_cadence_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    policy: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None


@router.get("/sources")
async def visual_sources(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    settings = dict((workspace.settings or {}).get("visual_intelligence") or {})
    if settings.get("enabled") or workspace.slug == "sentinel-ci":
        ensure_visual_intelligence_seed(db, workspace)
        db.commit()
    rows = list_sources(db, workspace)
    return {"sources": [serialize_source(row) for row in rows]}


@router.post("/sources")
async def visual_source_create(
    body: VisualSourceCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    row = create_source(
        db,
        workspace,
        user,
        name=body.name,
        source_url=body.source_url,
        description=body.description,
        source_type=body.source_type,
        adapter=body.adapter,
        region=body.region,
        capture_cadence_minutes=body.capture_cadence_minutes,
        enabled=body.enabled,
        policy=body.policy or None,
        metadata=body.metadata or None,
    )
    db.commit()
    return serialize_source(row)


@router.patch("/sources/{source_id}")
async def visual_source_patch(
    source_id: str,
    body: VisualSourcePatch,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    updates = {key: value for key, value in body.model_dump().items() if value is not None}
    try:
        row = update_source(db, workspace, user, source_id, updates)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Visual source not found") from exc
    db.commit()
    return serialize_source(row)


@router.post("/sources/{source_id}/capture")
async def visual_source_capture(
    source_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        source = get_source(db, workspace, source_id)
        result = capture_source(db, workspace, source, user=user)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Visual source not found") from exc
    except Exception as exc:  # noqa: BLE001
        db.commit()
        raise HTTPException(status_code=502, detail=f"Visual capture failed: {exc}") from exc
    db.commit()
    return result


@router.get("/sources/{source_id}/captures")
async def visual_source_captures(
    source_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        get_source(db, workspace, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Visual source not found") from exc
    rows = list_captures(db, workspace, source_id)
    return {"captures": [serialize_capture(row) for row in rows]}


@router.get("/captures/{capture_id}/image")
async def visual_capture_image(
    capture_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    try:
        capture = get_capture(db, workspace, capture_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Visual capture not found") from exc
    if not capture.object_key:
        raise HTTPException(status_code=404, detail="Visual capture has no stored image")
    content = get_object_store().read_bytes(capture.object_key)
    return Response(content=content, media_type=capture.mime_type)


@router.get("/dashboard")
async def visual_dashboard(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    settings = dict((workspace.settings or {}).get("visual_intelligence") or {})
    if settings.get("enabled") or workspace.slug == "sentinel-ci":
        ensure_visual_intelligence_seed(db, workspace)
        db.commit()
    return dashboard_payload(db, workspace)
