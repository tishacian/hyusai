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
)

api_router = APIRouter()

# Health check
api_router.include_router(health.router, prefix="/health", tags=["health"])

# Models
api_router.include_router(models.router, prefix="/models", tags=["models"])

# Chat
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])

# Documents
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])

# Agents
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])

# Sessions
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])

# Metrics
api_router.include_router(metrics.router, prefix="/metrics", tags=["metrics"])

# Settings
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])

# Traces
api_router.include_router(traces.router, prefix="/traces", tags=["traces"])
