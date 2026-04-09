"""API v1 router"""
from fastapi import APIRouter
from app.api.v1.endpoints import (
    health,
    models,
    chat,
    documents,
    agents,
    sessions,
    metrics,
    settings,
    traces,
    audit,
)

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(traces.router, prefix="/traces", tags=["traces"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
