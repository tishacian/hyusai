"""Health check endpoints.

The public health endpoint is intentionally lightweight so login and browser
startup never wait on Qdrant, object storage or any external provider. Readiness
is exposed separately for operators and Docker/Kubernetes-style probes.
"""
from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal

logger = get_logger(__name__)
router = APIRouter()


@router.get("")
async def health():
    return _live_payload()


@router.get("/live")
async def health_live():
    return _live_payload()


@router.get("/ready")
async def health_ready():
    started = time.perf_counter()
    checks: dict[str, Any] = {
        "database": _check_database(),
        "qdrant": _check_qdrant(),
        "object_store": _check_object_store(),
    }
    healthy = all(item.get("status") == "ok" for item in checks.values())
    return {
        "status": "healthy" if healthy else "degraded",
        "service": settings.app_name,
        "version": settings.app_version,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "checks": checks,
    }


def _live_payload() -> dict[str, str]:
    return {"status": "healthy", "service": settings.app_name, "version": settings.app_version}


def _check_database() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        with SessionLocal() as db:
            db.execute(text("select 1"))
        return {"status": "ok", "duration_ms": round((time.perf_counter() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_ready_database_failed", error=str(exc))
        return {"status": "error", "duration_ms": round((time.perf_counter() - started) * 1000), "error": str(exc)[:160]}


def _check_qdrant() -> dict[str, Any]:
    started = time.perf_counter()
    scheme = "https" if settings.qdrant_https else "http"
    url = f"{scheme}://{settings.qdrant_host}:{settings.qdrant_port}/healthz"
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else None
    try:
        with httpx.Client(timeout=1.5, follow_redirects=False) as client:
            response = client.get(url, headers=headers)
        ok = response.status_code < 500
        return {
            "status": "ok" if ok else "error",
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "status_code": response.status_code,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_ready_qdrant_failed", error=str(exc), url=url)
        return {"status": "error", "duration_ms": round((time.perf_counter() - started) * 1000), "error": str(exc)[:160]}


def _check_object_store() -> dict[str, Any]:
    started = time.perf_counter()
    if settings.object_store_backend == "local":
        return {
            "status": "ok",
            "backend": "local",
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }
    configured = bool(settings.object_store_s3_bucket and settings.object_store_s3_endpoint_url)
    return {
        "status": "ok" if configured else "error",
        "backend": settings.object_store_backend,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "configured": configured,
    }
