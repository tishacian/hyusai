"""RAG execution traces endpoints.

Deprecated — use the canonical ``/runs`` router instead. Every response
from this router is stamped with three RFC-8594 style headers:

- ``X-Deprecated``    : human-readable notice
- ``Sunset``          : RFC-3339 date at which this router is removed
- ``Link``            : ``rel="successor-version"`` pointing at /runs
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from typing import Optional
from app.core.auth import get_current_user
from app.services.tracing.rag_tracer import get_tracer
from app.core.logging import get_logger

logger = get_logger(__name__)

_DEPRECATION_NOTICE = "Use /api/v1/runs (canonical). /traces will be removed."
_SUNSET_DATE = "Wed, 30 Sep 2026 00:00:00 GMT"
_SUCCESSOR = "/api/v1/runs"


def _stamp_deprecated(response: Response) -> Response:
    """FastAPI dependency — stamps every response from this router."""
    response.headers["X-Deprecated"] = _DEPRECATION_NOTICE
    response.headers["Sunset"] = _SUNSET_DATE
    response.headers["Link"] = f'<{_SUCCESSOR}>; rel="successor-version"'
    return response


router = APIRouter(
    dependencies=[
        Depends(_stamp_deprecated),
        # Gate the deprecated surface behind auth so anonymous callers can
        # not scrape the in-memory tracer across tenants.
        Depends(get_current_user),
    ]
)


@router.get("/traces")
async def get_traces(response: Response, operation_type: Optional[str] = None):
    """Get all execution traces.

    .. deprecated:: use ``GET /api/v1/runs`` instead.
    """
    try:
        tracer = get_tracer()
        traces = tracer.get_all_traces()
        
        if operation_type:
            traces = [t for t in traces if t.get("operation_type") == operation_type]
        
        return {
            "traces": traces,
            "total": len(traces),
        }
    except Exception as e:
        logger.error(f"Error getting traces: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traces/{trace_id}")
async def get_trace(trace_id: str):
    """Get a specific trace by ID.

    .. deprecated:: use ``GET /api/v1/runs/{run_id}`` instead.
    """
    try:
        tracer = get_tracer()
        trace = tracer.get_trace(trace_id)
        
        if not trace:
            raise HTTPException(status_code=404, detail="Trace not found")
        
        return trace.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting trace: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

