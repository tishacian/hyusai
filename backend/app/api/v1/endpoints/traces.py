"""RAG execution traces endpoints"""
from fastapi import APIRouter, HTTPException
from typing import Optional
from app.services.tracing.rag_tracer import get_tracer
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@router.get("/traces")
async def get_traces(operation_type: Optional[str] = None):
    """Get all execution traces"""
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
    """Get a specific trace by ID"""
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

