"""API v1 router"""
from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    health,
    models,
    chat,
    documents,
    agents,
    sessions,
    metrics,
    settings,
    presets,
    traces,
    audit,
    voice,
    tasks,
    evaluation,
    intelligence,
    sharepoint,
    # Canonical (mental-model) layer.
    systems,
    capabilities,
    skills,
    runs,
    impact,
    hypervisor,
    control_plane,
    contexts,
    reasoning,
    help_content,
    telemetry,
    knowledge,
    knowledge_capture,
    iam,
    secure_deposit,
    catalog,
    blueprints,
    mission_room,
    calendar,
)

api_router = APIRouter()

# OmniRAG engine — preserved.
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(models.router, prefix="/models", tags=["models"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(documents.router, prefix="/documents", tags=["documents"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents (legacy alias of /systems)"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings (legacy proxy over /presets default)"])
api_router.include_router(presets.router, prefix="/presets", tags=["presets"])
api_router.include_router(traces.router, prefix="/traces", tags=["traces (legacy alias of /runs)"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(voice.router, prefix="/voice", tags=["voice"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(evaluation.router, prefix="/evaluation", tags=["evaluation"])
api_router.include_router(intelligence.router, prefix="/intelligence", tags=["intelligence"])
api_router.include_router(sharepoint.router, prefix="/sharepoint", tags=["sharepoint"])

# Canonical mental-model layer.
api_router.include_router(systems.router,       prefix="/systems",       tags=["systems"])
api_router.include_router(capabilities.router,  prefix="/capabilities",  tags=["capabilities"])
api_router.include_router(skills.router,        prefix="/skills",        tags=["skills"])
api_router.include_router(runs.router,          prefix="/runs",          tags=["runs"])
api_router.include_router(impact.router,        prefix="/impact",        tags=["impact"])
api_router.include_router(hypervisor.router,    prefix="/hypervisor",    tags=["hypervisor"])
api_router.include_router(control_plane.router, prefix="/control-plane", tags=["control-plane"])
api_router.include_router(contexts.router,      prefix="/contexts",      tags=["contexts"])
api_router.include_router(reasoning.router,     prefix="/reasoning",     tags=["reasoning"])
api_router.include_router(help_content.router,  prefix="/help-content",  tags=["help-content"])
api_router.include_router(telemetry.router,      prefix="/telemetry",     tags=["telemetry"])
api_router.include_router(knowledge.router,      prefix="/knowledge",     tags=["knowledge"])
api_router.include_router(knowledge_capture.router, prefix="/knowledge-capture", tags=["knowledge-capture"])
api_router.include_router(iam.router, prefix="/iam", tags=["iam"])
api_router.include_router(secure_deposit.internal_router, prefix="/sftp", tags=["secure-deposit"])
api_router.include_router(secure_deposit.public_router, prefix="/deposit-links", tags=["deposit-links"])
api_router.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
api_router.include_router(blueprints.router, prefix="/blueprints", tags=["blueprints"])
api_router.include_router(mission_room.router, prefix="/mission-room", tags=["mission-room"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
