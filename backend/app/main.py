"""FastAPI application entry point"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agents.orchestrator import AgentOrchestrator
from app.agents.procurement_agent import OmniRAGAgent
from app.api.v1.endpoints.agents import set_orchestrator
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.middleware import error_handler_middleware
from app.core.settings_manager import get_settings_manager
from app.db.base import Base, engine
from app.seed_knowledge_base import seed_knowledge_base

setup_logging(settings.log_level)
logger = get_logger(__name__)

orchestrator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global orchestrator

    logger.info("Starting application")

    # Create all tables (demo -- no Alembic migration needed)
    import app.models  # noqa: F401  ensure models are registered

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created")

    get_settings_manager()
    logger.info("Settings manager initialized")

    orchestrator = AgentOrchestrator()
    set_orchestrator(orchestrator)

    omnirag_agent = OmniRAGAgent()
    await omnirag_agent.initialize()
    orchestrator.register_agent(omnirag_agent)

    # Seed knowledge base with sample docs (idempotent)
    try:
        await seed_knowledge_base()
    except Exception as e:
        logger.warning("Knowledge base seeding failed (non-blocking)", error=str(e))

    # Seed canonical Skills + Capabilities registry (idempotent)
    try:
        from app.db.base import SessionLocal
        from app.services.skills_registry import seed_skills_and_capabilities

        with SessionLocal() as _db:
            report = seed_skills_and_capabilities(_db)
        logger.info("Canonical registry seeded", **report)
    except Exception as e:
        logger.warning("Canonical registry seeding failed (non-blocking)", error=str(e))

    # Seed Intelligence System per workspace (idempotent, Vague A commit 2).
    try:
        from app.db.base import SessionLocal
        from app.services.systems.bootstrap import (
            ensure_expert_capture_system_for_all_workspaces,
            ensure_intelligence_system_for_all_workspaces,
        )
        from app.services.mission_room import ensure_sentinel_ci_workspace

        with SessionLocal() as _db:
            intel_report = ensure_intelligence_system_for_all_workspaces(_db)
            expert_capture_report = ensure_expert_capture_system_for_all_workspaces(_db)
            sentinel_report = ensure_sentinel_ci_workspace(_db)
        logger.info("Intelligence System seeded", **intel_report)
        logger.info("Expert Knowledge Capture System seeded", **expert_capture_report)
        logger.info("SENTINEL-CI demo workspace seeded", **sentinel_report)
    except Exception as e:
        logger.warning(
            "System seeding failed (non-blocking)", error=str(e)
        )

    logger.info("Application started", agents_count=len(orchestrator.agents))

    # Start intelligence RSS scheduler only when explicitly enabled. The
    # mission-room demo is designed to stay responsive with stored signals and
    # deterministic fallbacks; long external RSS/LLM batches must not compete
    # with live executive screens by default.
    if settings.intelligence_scheduler_enabled:
        try:
            from app.services.intelligence.scheduler import start_scheduler

            start_scheduler(interval_seconds=settings.intelligence_scheduler_interval_seconds)
        except Exception as e:
            logger.warning("Intelligence scheduler failed to start (non-blocking)", error=str(e))
    else:
        logger.info("Intelligence scheduler disabled", reason="settings.intelligence_scheduler_enabled=false")

    yield

    logger.info("Shutting down application")

    try:
        from app.services.intelligence.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass

    if orchestrator:
        for agent in orchestrator.agents.values():
            await agent.cleanup()
    logger.info("Application shut down")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.middleware("http")(error_handler_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes first (takes priority)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "app": settings.app_name, "version": settings.app_version}


# Serve frontend static files (catch-all, must be LAST)
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    logger.info("Frontend mounted", path=str(frontend_dir))
