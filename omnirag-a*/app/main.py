"""FastAPI application entry point"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.core.middleware import error_handler_middleware
from app.core.settings_manager import get_settings_manager
from app.api.v1.router import api_router
from app.agents.orchestrator import AgentOrchestrator
from app.agents.reasoning_agent import ReasoningAgent
from app.agents.rag_agent import RAGAgent
from app.agents.search_agent import SearchAgent
from app.api.v1.endpoints.agents import set_orchestrator

# Setup logging
setup_logging(settings.log_level)
logger = get_logger(__name__)

# Global orchestrator
orchestrator = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global orchestrator
    
    # Startup
    logger.info("Starting application")
    
    # Initialize settings manager to load settings from database
    get_settings_manager()
    logger.info("Settings manager initialized")
    
    orchestrator = AgentOrchestrator()
    
    # Set orchestrator for API endpoints
    set_orchestrator(orchestrator)
    
    # Initialize and register agents
    reasoning_agent = ReasoningAgent()
    await reasoning_agent.initialize()
    orchestrator.register_agent(reasoning_agent)
    
    rag_agent = RAGAgent()
    await rag_agent.initialize()
    orchestrator.register_agent(rag_agent)
    
    search_agent = SearchAgent()
    await search_agent.initialize()
    orchestrator.register_agent(search_agent)
    
    logger.info("Application started", agents_count=len(orchestrator.agents))
    
    yield
    
    # Shutdown
    logger.info("Shutting down application")
    if orchestrator:
        for agent in orchestrator.agents.values():
            await agent.cleanup()
    logger.info("Application shut down")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

# Error handling middleware (must be first)
app.middleware("http")(error_handler_middleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API router
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=4100)

