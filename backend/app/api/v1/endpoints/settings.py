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
        error_str = str(e)
        # Check if it's a missing column error (migration not run yet)
        if "no such column" in error_str.lower() or "rag_vector_db_type" in error_str:
            logger.warning("Database migration may not be complete. Using defaults for missing columns.", error=error_str)
            # Try to get partial settings with defaults
            try:
                app_settings = SettingsService.get_settings(db, ignore_missing_columns=True)
                # Merge with defaults from settings manager
                from app.core.settings_manager import get_app_settings
                defaults = get_app_settings()
                app_settings = {**defaults, **app_settings}  # Defaults take precedence
                return SettingsResponse(settings=app_settings, version="1.0")
            except Exception as fallback_error:
                logger.error("Failed to get settings even with fallback", error=str(fallback_error))
                # Return defaults directly
                from app.core.settings_manager import get_app_settings
                app_settings = get_app_settings()
                return SettingsResponse(settings=app_settings, version="1.0")
        else:
            logger.error("Failed to get settings", error=error_str)
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

