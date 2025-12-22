"""Settings management endpoints"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.core.logging import get_logger
from app.core.config import settings as app_config
from app.db.base import get_db
from app.services.settings_service import SettingsService
from app.core.settings_manager import reload_app_settings

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
    """Get current application settings from database"""
    try:
        app_settings = SettingsService.get_settings(db)
        return SettingsResponse(settings=app_settings, version="1.0")
    except Exception as e:
        logger.error("Failed to get settings", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("")
async def update_settings(
    request: SettingsUpdate,
    db: Session = Depends(get_db)
) -> SettingsResponse:
    """Update application settings (persisted to database)"""
    try:
        updated_settings = SettingsService.update_settings(db, request.settings)
        # Reload settings in settings manager
        reload_app_settings()
        logger.info("Settings updated and persisted", updated_keys=list(request.settings.keys()))
        return SettingsResponse(settings=updated_settings, version="1.0")
    except Exception as e:
        logger.error("Failed to update settings", error=str(e), exc_info=True)
        # Return more detailed error message
        error_detail = str(e)
        if "no such column" in error_detail.lower() or "does not exist" in error_detail.lower():
            error_detail = f"Database schema mismatch: {error_detail}. Please run database migrations."
        raise HTTPException(status_code=500, detail=error_detail)


@router.patch("")
async def partial_update_settings(
    request: SettingsUpdate,
    db: Session = Depends(get_db)
) -> SettingsResponse:
    """Partially update application settings"""
    try:
        updated_settings = SettingsService.update_settings(db, request.settings)
        # Reload settings in settings manager
        reload_app_settings()
        return SettingsResponse(settings=updated_settings, version="1.0")
    except Exception as e:
        logger.error("Failed to partially update settings", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def settings_health() -> Dict[str, Any]:
    """Get settings health status"""
    return {
        "status": "healthy",
        "settings_loaded": True,
        "config_source": "environment"
    }

