"""RAG Preset endpoints — multi-scope successor to `/api/v1/settings`.

Routes:
    GET    /api/v1/presets                  list presets (optional scope=…)
    POST   /api/v1/presets                  create a preset
    GET    /api/v1/presets/{id}             get one
    PATCH  /api/v1/presets/{id}             partial update (name / config / scope_id)
    DELETE /api/v1/presets/{id}             delete (default preset is protected)
    POST   /api/v1/presets/{id}/set-default elect as default for its scope

The legacy `/api/v1/settings` endpoints are now a thin proxy over the
workspace default preset (see `settings.py`).
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_workspace
from app.core.logging import get_logger
from app.core.settings_manager import reload_app_settings
from app.db.base import get_db
from app.models.workspace import Workspace
from app.services.rag_preset_service import RagPresetService, VALID_SCOPES

logger = get_logger(__name__)
router = APIRouter()


class PresetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scope: str = Field("workspace")
    scope_id: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False


class PresetUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    scope_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    config_patch: Optional[Dict[str, Any]] = None


class PresetResponse(BaseModel):
    preset: Dict[str, Any]


class PresetListResponse(BaseModel):
    presets: List[Dict[str, Any]]


@router.get("", response_model=PresetListResponse)
async def list_presets(
    scope: Optional[str] = Query(None, description="workspace | capability | system"),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> PresetListResponse:
    if scope and scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"Invalid scope '{scope}'")
    presets = RagPresetService.list_presets(db, workspace_id=workspace.id, scope=scope)
    return PresetListResponse(presets=presets)


@router.post("", response_model=PresetResponse, status_code=201)
async def create_preset(
    body: PresetCreate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> PresetResponse:
    if body.scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"Invalid scope '{body.scope}'")
    if body.scope != "workspace" and not body.scope_id:
        raise HTTPException(
            status_code=400,
            detail=f"scope_id is required when scope='{body.scope}'",
        )
    try:
        preset = RagPresetService.create_preset(
            db,
            name=body.name,
            scope=body.scope,
            scope_id=body.scope_id if body.scope != "workspace" else workspace.id,
            workspace_id=workspace.id,
            config=body.config,
            is_default=body.is_default,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    reload_app_settings()
    return PresetResponse(preset=preset)


@router.get("/resolve", response_model=PresetResponse)
async def resolve_preset(
    capability_id: Optional[str] = None,
    system_id: Optional[str] = None,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> PresetResponse:
    """Return the resolved preset config for the given run context.

    Used by the frontend to preview which preset will actually power a given
    Capability / System at runtime.
    """
    config = RagPresetService.resolve_for(
        db,
        workspace_id=workspace.id,
        capability_id=capability_id,
        system_id=system_id,
    )
    return PresetResponse(
        preset={
            "scope_hint": (
                "system" if system_id else "capability" if capability_id else "workspace"
            ),
            "config": config,
        }
    )


@router.get("/{preset_id}", response_model=PresetResponse)
async def get_preset(
    preset_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> PresetResponse:
    preset = RagPresetService.get_preset(db, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    if preset.workspace_id and preset.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Preset not found")
    from app.services.rag_preset_service import _serialize
    return PresetResponse(preset=_serialize(preset))


@router.patch("/{preset_id}", response_model=PresetResponse)
async def update_preset(
    preset_id: str,
    body: PresetUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> PresetResponse:
    preset = RagPresetService.get_preset(db, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    if preset.workspace_id and preset.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Preset not found")

    updated = RagPresetService.update_preset(
        db,
        preset_id,
        name=body.name,
        config=body.config,
        config_patch=body.config_patch,
        scope_id=body.scope_id,
    )
    reload_app_settings()
    return PresetResponse(preset=updated)


@router.delete("/{preset_id}", status_code=204)
async def delete_preset(
    preset_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    preset = RagPresetService.get_preset(db, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    if preset.workspace_id and preset.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Preset not found")
    try:
        RagPresetService.delete_preset(db, preset_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    reload_app_settings()
    return None


@router.post("/{preset_id}/set-default", response_model=PresetResponse)
async def set_default(
    preset_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
) -> PresetResponse:
    preset = RagPresetService.get_preset(db, preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    if preset.workspace_id and preset.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Preset not found")
    updated = RagPresetService.set_default(db, preset_id)
    reload_app_settings()
    return PresetResponse(preset=updated)
