"""FastAPI application entry point"""

import asyncio
import mimetypes
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.agents.orchestrator import AgentOrchestrator
from app.agents.procurement_agent import OmniRAGAgent
from app.api.v1.endpoints.agents import set_orchestrator
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.middleware import error_handler_middleware
from app.core.monitoring import metrics_collector
from app.core.settings_manager import get_settings_manager
from app.db.base import Base, SessionLocal, engine
from app.seed_knowledge_base import seed_knowledge_base
from app.services.rag.sparse_backends import sparse_runtime_config

setup_logging(settings.log_level)
logger = get_logger(__name__)

orchestrator = None
_loop_lag_task = None


async def _record_event_loop_lag(interval_seconds: float = 1.0):
    """Record worker event-loop lag without touching DB or external services."""
    expected = time.monotonic() + interval_seconds
    while True:
        await asyncio.sleep(interval_seconds)
        now = time.monotonic()
        metrics_collector.record_event_loop_lag((now - expected) * 1000.0)
        expected = now + interval_seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    global orchestrator, _loop_lag_task

    logger.info("Starting application")

    startup_reconciliation_enabled = settings.startup_reconciliation == "enabled"

    # Create all tables only in the legacy/demo startup mode. Transactional
    # deployment runs Alembic explicitly while all writers are quiesced.
    import app.models  # noqa: F401  ensure models are registered

    if startup_reconciliation_enabled:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables reconciled")
    else:
        logger.info("Database startup reconciliation disabled")

    get_settings_manager(create_if_missing=startup_reconciliation_enabled)
    logger.info("Settings manager initialized")

    orchestrator = AgentOrchestrator()
    set_orchestrator(orchestrator)

    omnirag_agent = OmniRAGAgent()
    await omnirag_agent.initialize()
    orchestrator.register_agent(omnirag_agent)

    # Seed knowledge base with sample docs (idempotent) only outside a
    # transactional deployment startup.
    if startup_reconciliation_enabled:
        try:
            await seed_knowledge_base()
        except Exception as e:
            logger.warning("Knowledge base seeding failed (non-blocking)", error=str(e))

    # Warm the cross-encoder so the first balanced chat does not pay the
    # model load inside its rerank budget (opt-in: weights must be available).
    if settings.rag_cross_encoder_enabled and settings.rag_cross_encoder_preload:
        try:
            from app.services.rag.cross_encoder_stage import preload_cross_encoder

            await asyncio.get_running_loop().run_in_executor(None, preload_cross_encoder)
        except Exception as e:  # noqa: BLE001
            logger.warning("Cross-encoder preload failed (non-blocking)", error=str(e))

    # Seed canonical Skills + Capabilities registry (idempotent).
    if startup_reconciliation_enabled:
        try:
            from app.db.base import SessionLocal
            from app.services.skills_registry import seed_skills_and_capabilities

            with SessionLocal() as _db:
                report = seed_skills_and_capabilities(_db)
            logger.info("Canonical registry seeded", **report)
        except Exception as e:
            logger.warning("Canonical registry seeding failed (non-blocking)", error=str(e))

    # Seed Intelligence System per workspace (idempotent, Vague A commit 2).
    if startup_reconciliation_enabled:
        try:
            from app.db.base import SessionLocal
            from app.services.systems.bootstrap import (
                ensure_client360_pdr_system_for_all_workspaces,
                ensure_expert_capture_system_for_all_workspaces,
                ensure_fse_report_system_for_andritz,
                ensure_intelligence_system_for_all_workspaces,
                ensure_workspace_chat_system_for_all_workspaces,
            )
            from app.services.mission_room import ensure_sentinel_ci_workspace

            with SessionLocal() as _db:
                sentinel_report = ensure_sentinel_ci_workspace(_db)
                intel_report = ensure_intelligence_system_for_all_workspaces(_db)
                expert_capture_report = ensure_expert_capture_system_for_all_workspaces(_db)
                fse_report_report = ensure_fse_report_system_for_andritz(_db)
                workspace_chat_report = ensure_workspace_chat_system_for_all_workspaces(_db)
                client360_report = ensure_client360_pdr_system_for_all_workspaces(_db)
            logger.info("Intelligence System seeded", **intel_report)
            logger.info("Expert Knowledge Capture System seeded", **expert_capture_report)
            logger.info("FSE intervention report System seeded", **fse_report_report)
            logger.info("Workspace Chat System seeded", **workspace_chat_report)
            logger.info("Client360 PDR System seeded", **client360_report)
            logger.info("SENTINEL-CI demo workspace seeded", **sentinel_report)
        except Exception as e:
            logger.warning("System seeding failed (non-blocking)", error=str(e))

    logger.info("Application started", agents_count=len(orchestrator.agents))

    # Start intelligence RSS scheduler only when explicitly enabled. The
    # mission-room demo is designed to stay responsive with stored signals and
    # deterministic fallbacks; long external RSS/LLM batches must not compete
    # with live executive screens by default.
    if startup_reconciliation_enabled and settings.intelligence_scheduler_enabled:
        try:
            from app.services.intelligence.scheduler import start_scheduler

            start_scheduler(interval_seconds=settings.intelligence_scheduler_interval_seconds)
        except Exception as e:
            logger.warning("Intelligence scheduler failed to start (non-blocking)", error=str(e))
    else:
        logger.info(
            "Intelligence scheduler disabled",
            reason=(
                "startup_reconciliation=disabled"
                if not startup_reconciliation_enabled
                else "settings.intelligence_scheduler_enabled=false"
            ),
        )

    _loop_lag_task = asyncio.create_task(_record_event_loop_lag())

    yield

    logger.info("Shutting down application")

    if _loop_lag_task:
        _loop_lag_task.cancel()
        with suppress(asyncio.CancelledError):
            await _loop_lag_task
        _loop_lag_task = None

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
def health_check():
    return {"status": "healthy", "app": settings.app_name, "version": settings.app_version}


@app.get("/health/live")
def health_live_check():
    return {"status": "healthy", "app": settings.app_name, "version": settings.app_version}


@app.get("/health/ready")
def health_ready_check():
    checks = {
        "runtime": metrics_collector.get_runtime_health(),
        "database": _ready_database_check(),
        "qdrant": _ready_qdrant_check(),
    }
    healthy = all(item.get("status") == "ok" for item in checks.values())
    return {
        "status": "healthy" if healthy else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "checks": checks,
    }


def _ready_database_check() -> dict[str, str]:
    try:
        with SessionLocal() as db:
            db.execute(text("select 1"))
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:160]}


def _ready_retrieval_sparse_config() -> dict[str, bool | str]:
    return sparse_runtime_config()


def _ready_qdrant_check() -> dict[str, str | int | bool]:
    scheme = "https" if settings.qdrant_https else "http"
    url = f"{scheme}://{settings.qdrant_host}:{settings.qdrant_port}/healthz"
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else None
    try:
        with httpx.Client(timeout=1.5, follow_redirects=False) as client:
            response = client.get(url, headers=headers)
        return {
            "status": "ok" if response.status_code < 500 else "error",
            "status_code": response.status_code,
            **_ready_retrieval_sparse_config(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)[:160], **_ready_retrieval_sparse_config()}


# Older deployment Pythons predate the stdlib `.mjs`/`.wasm` mimetype entries, so
# StaticFiles would serve them as application/octet-stream — which browsers reject
# for ES module scripts (strict MIME). pdf.js ships its worker/viewer as `.mjs`, so
# register the JS/Wasm types explicitly before mounting the SPA.
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")

# Serve frontend static files (catch-all, must be LAST)
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
    logger.info("Frontend mounted", path=str(frontend_dir))
