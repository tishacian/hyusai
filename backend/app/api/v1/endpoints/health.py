"""Health check endpoints"""
from fastapi import APIRouter
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("")
async def health():
    return {"status": "healthy", "service": settings.app_name, "version": settings.app_version}

