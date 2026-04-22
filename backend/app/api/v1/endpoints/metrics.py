"""Metrics and monitoring endpoints.

Auth gated (Vague D / D1): process-level metrics (query counts, cache
stats) could leak customer activity if left open, so the whole router
requires an authenticated user.
"""
from fastapi import APIRouter, Depends
from app.core.auth import get_current_user
from app.core.monitoring import metrics_collector
from app.core.cache import cache
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)])


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

