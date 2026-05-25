"""Redis-backed intelligence cache with in-memory fallback."""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_MEMORY: dict[str, tuple[float, dict[str, Any]]] = {}


def _redis_client():
    try:
        import redis

        return redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            decode_responses=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("intelligence.cache.redis_unavailable", error=str(exc))
        return None


def cache_get(key: str) -> Optional[dict[str, Any]]:
    client = _redis_client()
    if client is not None:
        try:
            raw = client.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("intelligence.cache.redis_get_failed", key=key, error=str(exc))
    cached = _MEMORY.get(key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= time.time():
        _MEMORY.pop(key, None)
        return None
    return payload


def cache_set(key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
    encoded = json.dumps(payload, default=str)
    client = _redis_client()
    if client is not None:
        try:
            client.setex(key, max(1, int(ttl_seconds)), encoded)
        except Exception as exc:  # noqa: BLE001
            logger.warning("intelligence.cache.redis_set_failed", key=key, error=str(exc))
    _MEMORY[key] = (time.time() + max(1, int(ttl_seconds)), payload)


def cache_delete(key: str) -> None:
    client = _redis_client()
    if client is not None:
        try:
            client.delete(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("intelligence.cache.redis_delete_failed", key=key, error=str(exc))
    _MEMORY.pop(key, None)


def clear_memory_cache() -> None:
    _MEMORY.clear()
