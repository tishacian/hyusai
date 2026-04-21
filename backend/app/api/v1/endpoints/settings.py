"""Settings management endpoints.

NOTE (Vague A — P0): this router is now a *thin compatibility proxy* over
the workspace-default row of the ``rag_presets`` catalog. The table
``app_settings`` is still updated on write so the legacy
``SettingsManager`` singleton and any caller relying on it keep working.
All modern clients should migrate to ``/api/v1/presets`` for multi-scope
CRUD and set-default semantics.
"""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.settings_manager import reload_app_settings
from app.db.base import get_db
from app.services.rag_preset_service import RagPresetService
from app.services.settings_service import SettingsService

logger = get_logger(__name__)
router = APIRouter()


class SettingsUpdate(BaseModel):
    """Settings update request"""
    settings: Dict[str, Any]


class SettingsResponse(BaseModel):
    """Settings response"""
    settings: Dict[str, Any]
    version: str = "1.0"


@router.get("")
async def get_settings(db: Session = Depends(get_db)) -> SettingsResponse:
    """Get current application settings.

    Resolution order:
      1. workspace-default ``rag_presets`` row
      2. ``app_settings`` singleton (legacy)
      3. in-memory ``SettingsManager`` defaults
    """
    try:
        preset = RagPresetService.get_or_create_workspace_default(db, workspace_id=None)
        return SettingsResponse(
            settings=dict(preset.config or {}), version="1.0"
        )
    except Exception as preset_error:
        logger.debug(
            "Falling back to legacy app_settings",
            error=str(preset_error),
        )

    try:
        app_settings = SettingsService.get_settings(db)
        return SettingsResponse(settings=app_settings, version="1.0")
    except Exception as e:
        error_str = str(e)
        if "no such column" in error_str.lower() or "rag_vector_db_type" in error_str:
            from app.core.settings_manager import get_app_settings
            try:
                app_settings = SettingsService.get_settings(db, ignore_missing_columns=True)
                defaults = get_app_settings()
                merged = {**defaults, **app_settings}
                return SettingsResponse(settings=merged, version="1.0")
            except Exception:
                return SettingsResponse(settings=get_app_settings(), version="1.0")
        logger.error("Failed to get settings", error=error_str)
        raise HTTPException(status_code=500, detail=str(e))


def _persist_update(
    db: Session, patch: Dict[str, Any]
) -> Dict[str, Any]:
    """Apply the frontend patch to both the legacy ``app_settings`` row and
    the workspace-default preset, then return the merged config."""
    SettingsService.update_settings(db, patch)

    preset = RagPresetService.get_or_create_workspace_default(db, workspace_id=None)
    RagPresetService.update_preset(db, preset.id, config_patch=patch)
    preset = RagPresetService.get_preset(db, preset.id)
    return dict(preset.config or {})


@router.post("")
async def update_settings(
    request: SettingsUpdate,
    db: Session = Depends(get_db),
) -> SettingsResponse:
    """Update application settings (persisted to database)."""
    try:
        merged = _persist_update(db, request.settings)
        reload_app_settings()
        logger.info(
            "Settings updated and persisted",
            updated_keys=list(request.settings.keys()),
        )
        return SettingsResponse(settings=merged, version="1.0")
    except Exception as e:
        logger.error("Failed to update settings", error=str(e), exc_info=True)
        error_detail = str(e)
        if "no such column" in error_detail.lower() or "does not exist" in error_detail.lower():
            error_detail = (
                f"Database schema mismatch: {error_detail}. "
                "Please run database migrations."
            )
        raise HTTPException(status_code=500, detail=error_detail)


@router.patch("")
async def partial_update_settings(
    request: SettingsUpdate,
    db: Session = Depends(get_db),
) -> SettingsResponse:
    """Partially update application settings."""
    try:
        merged = _persist_update(db, request.settings)
        reload_app_settings()
        return SettingsResponse(settings=merged, version="1.0")
    except Exception as e:
        logger.error("Failed to partially update settings", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def settings_health() -> Dict[str, Any]:
    """Get settings health status"""
    return {
        "status": "healthy",
        "settings_loaded": True,
        "config_source": "rag_presets (workspace default)",
    }
