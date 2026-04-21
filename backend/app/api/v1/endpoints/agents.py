"""Agent management endpoints.

Deprecated — use the canonical ``/systems`` router instead. This module
is kept for back-compat while the cockpit migrates all callsites, and
every response is stamped with an ``X-Deprecated`` header so we can
observe any residual calls in production logs.
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from typing import List, Dict, Any
from app.core.logging import get_logger

logger = get_logger(__name__)

_DEPRECATION_NOTICE = "Use /api/v1/systems (canonical). /agents will be removed."
_SUNSET_DATE = "Wed, 30 Sep 2026 00:00:00 GMT"
_SUCCESSOR = "/api/v1/systems"


def _stamp_deprecated(response: Response) -> Response:
    """Router-level dependency — stamps every response from /agents."""
    response.headers["X-Deprecated"] = _DEPRECATION_NOTICE
    response.headers["Sunset"] = _SUNSET_DATE
    response.headers["Link"] = f'<{_SUCCESSOR}>; rel="successor-version"'
    return response


router = APIRouter(dependencies=[Depends(_stamp_deprecated)])

# This will be set by the main app
_orchestrator = None

def set_orchestrator(orchestrator_instance):
    """Set the orchestrator instance"""
    global _orchestrator
    _orchestrator = orchestrator_instance

def get_orchestrator():
    """Get the orchestrator instance"""
    return _orchestrator


@router.get("")
async def list_agents() -> Dict[str, List[Dict[str, Any]]]:
    """List all registered agents.

    .. deprecated:: use ``GET /api/v1/systems`` instead.
    """
    try:
        orchestrator = get_orchestrator()
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")
        
        agents = orchestrator.list_agents()
        return {"agents": agents}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to list agents", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{agent_id}")
async def get_agent(agent_id: str) -> Dict[str, Any]:
    """Get agent details"""
    try:
        orchestrator = get_orchestrator()
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")
        
        agent = orchestrator.get_agent(agent_id)
        return {
            "id": agent.agent_id,
            "name": agent.name,
            "type": agent.agent_type,
            "status": agent.status
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get agent", agent_id=agent_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{agent_id}/status")
async def get_agent_status(agent_id: str) -> Dict[str, Any]:
    """Get agent status"""
    try:
        orchestrator = get_orchestrator()
        if orchestrator is None:
            raise HTTPException(status_code=503, detail="Orchestrator not initialized")
        
        agent = orchestrator.get_agent(agent_id)
        is_healthy = await agent.health_check()
        
        return {
            "agent_id": agent_id,
            "status": agent.status,
            "healthy": is_healthy
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get agent status", agent_id=agent_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

