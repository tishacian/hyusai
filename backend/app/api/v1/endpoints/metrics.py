"""Metrics and monitoring endpoints"""
from fastapi import APIRouter
from app.core.monitoring import metrics_collector
from app.core.cache import cache
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("")
async def get_metrics():
    """Get all metrics"""
    return {
        "metrics": metrics_collector.get_metrics(),
        "summary": metrics_collector.get_summary()
    }


@router.get("/summary")
async def get_metrics_summary():
    """Get metrics summary"""
    return metrics_collector.get_summary()


@router.get("/cache")
async def get_cache_stats():
    """Get cache statistics"""
    return cache.get_stats()

