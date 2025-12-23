"""Health check endpoints"""
from fastapi import APIRouter
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("")
async def health():
    """Health check endpoint"""
    return {"status": "healthy", "service": "omnirag-a*"}

