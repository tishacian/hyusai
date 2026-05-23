"""Custom middleware for error handling and monitoring"""
import time
import uuid

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.core.errors import BaseAppError, ErrorCategory
from app.core.logging import get_logger
from app.core.monitoring import metrics_collector, normalize_endpoint

logger = get_logger(__name__)
SLOW_REQUEST_MS = 2500.0


async def error_handler_middleware(request: Request, call_next):
    """Global error handler middleware"""
    start_time = time.time()
    path = normalize_endpoint(request.url.path)
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    metrics_collector.start_request(path, request_id=request_id, method=request.method)
    
    try:
        response = await call_next(request)
        
        # Log request duration
        duration = time.time() - start_time
        duration_ms = duration * 1000
        
        # Record metrics
        metrics_collector.record_latency(path, duration_ms)
        metrics_collector.record_request(path, response.status_code)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 2))
        if duration_ms >= SLOW_REQUEST_MS:
            metrics_collector.record_slow_request(
                method=request.method,
                endpoint=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                request_id=request_id,
            )
            logger.warning(
                "Slow request completed",
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                request_id=request_id,
                pending_requests=metrics_collector.get_runtime_snapshot()["pending_requests"]["total"],
            )
        
        logger.info(
            "Request completed",
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        
        return response
    
    except BaseAppError as e:
        duration = time.time() - start_time
        duration_ms = duration * 1000
        
        # Record error metrics
        metrics_collector.record_latency(path, duration_ms)
        metrics_collector.record_error(e.category.value)
        
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        if e.category == ErrorCategory.VALIDATION:
            status_code = status.HTTP_400_BAD_REQUEST
        elif e.category == ErrorCategory.MODEL_UNAVAILABLE:
            status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        metrics_collector.record_request(path, status_code)

        logger.error(
            "Application error",
            error_type=type(e).__name__,
            message=e.message,
            category=e.category.value,
            recoverable=e.recoverable,
            details=e.details,
            duration_ms=duration_ms,
            status_code=status_code,
            request_id=request_id,
        )
        
        return JSONResponse(
            status_code=status_code,
            headers={"X-Request-ID": request_id, "X-Response-Time-Ms": str(round(duration_ms, 2))},
            content={
                "error": {
                    "type": e.category.value,
                    "message": e.message,
                    "recoverable": e.recoverable,
                    "details": e.details
                }
            }
        )
    
    except RequestValidationError as e:
        duration = time.time() - start_time
        duration_ms = duration * 1000
        metrics_collector.record_latency(path, duration_ms)
        metrics_collector.record_error("validation_error")
        metrics_collector.record_request(path, status.HTTP_422_UNPROCESSABLE_ENTITY)
        logger.warning(
            "Validation error",
            errors=e.errors(),
            duration_ms=duration_ms,
            request_id=request_id,
        )
        
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            headers={"X-Request-ID": request_id, "X-Response-Time-Ms": str(round(duration_ms, 2))},
            content={
                "error": {
                    "type": "validation_error",
                    "message": "Request validation failed",
                    "details": e.errors()
                }
            }
        )
    
    except StarletteHTTPException as e:
        duration = time.time() - start_time
        duration_ms = duration * 1000
        metrics_collector.record_latency(path, duration_ms)
        metrics_collector.record_error("http_error")
        metrics_collector.record_request(path, e.status_code)
        logger.warning(
            "HTTP exception",
            status_code=e.status_code,
            detail=e.detail,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        
        return JSONResponse(
            status_code=e.status_code,
            headers={"X-Request-ID": request_id, "X-Response-Time-Ms": str(round(duration_ms, 2))},
            content={
                "error": {
                    "type": "http_error",
                    "message": e.detail or "HTTP error occurred"
                }
            }
        )
    
    except Exception as e:
        duration = time.time() - start_time
        duration_ms = duration * 1000
        metrics_collector.record_latency(path, duration_ms)
        metrics_collector.record_error(type(e).__name__)
        metrics_collector.record_request(path, status.HTTP_500_INTERNAL_SERVER_ERROR)
        logger.exception(
            "Unhandled exception",
            error_type=type(e).__name__,
            error=str(e),
            duration_ms=duration_ms,
            request_id=request_id,
        )
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers={"X-Request-ID": request_id, "X-Response-Time-Ms": str(round(duration_ms, 2))},
            content={
                "error": {
                    "type": "internal_error",
                    "message": "An internal error occurred",
                    "recoverable": False
                }
            }
        )
    finally:
        metrics_collector.finish_request(path, request_id=request_id)
