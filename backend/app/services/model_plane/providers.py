"""Unified provider registry with live health checks (TTL cache ~60s)."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.model_plane.registration import list_routable_providers

logger = get_logger(__name__)

HEALTH_TTL_SECONDS = 60.0
_HEALTH_TIMEOUT = 5.0

# key -> (expires_at, payload)
_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def _env(*names: str) -> bool:
    return all(bool(os.getenv(name)) for name in names)


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    entry = _cache.get(key)
    if not entry:
        return None
    expires_at, payload = entry
    if time.monotonic() >= expires_at:
        return None
    return dict(payload)


def _cache_set(key: str, payload: Dict[str, Any]) -> None:
    _cache[key] = (time.monotonic() + HEALTH_TTL_SECONDS, dict(payload))


def clear_health_cache() -> None:
    _cache.clear()


async def _probe(
    *,
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
            response = await client.request(method, url, headers=headers or {}, params=params)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        if response.status_code >= 400:
            return {
                "status": "unreachable",
                "latency_ms": latency_ms,
                "models": [],
                "error": f"HTTP {response.status_code}",
            }
        models = _extract_models(response)
        return {
            "status": "active",
            "latency_ms": latency_ms,
            "models": models,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — surface as unreachable for UI
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.debug("Provider health probe failed", url=url, error=str(exc))
        return {
            "status": "unreachable",
            "latency_ms": latency_ms,
            "models": [],
            "error": str(exc),
        }


def _extract_models(response: httpx.Response) -> List[str]:
    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        return []

    # OpenAI / OpenRouter / Azure / Anthropic: {"data":[{"id":...}, ...]}
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        ids: List[str] = []
        for item in data["data"]:
            if isinstance(item, dict):
                mid = item.get("id") or item.get("name")
                if mid:
                    ids.append(str(mid))
        return ids[:50]

    # Ollama: {"models":[{"name":...}, ...]}
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        names: List[str] = []
        for item in data["models"]:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
                if name:
                    names.append(str(name))
        return names[:50]

    # Gemini: {"models":[{"name":"models/gemini-..."}, ...]}
    if isinstance(data, dict) and "models" in data and isinstance(data["models"], list):
        names = []
        for item in data["models"]:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]).removeprefix("models/"))
        return names[:50]

    return []


async def _health_openai() -> Dict[str, Any]:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cached = _cache_get("openai")
    if cached:
        return cached
    result = await _probe(
        method="GET",
        url="https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    if result["status"] == "active" and not result["models"]:
        result["models"] = [settings.default_model] if settings.default_model else []
    _cache_set("openai", result)
    return result


async def _health_azure() -> Dict[str, Any]:
    if not _env("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"):
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cached = _cache_get("azure_openai")
    if cached:
        return cached
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
    result = await _probe(
        method="GET",
        url=f"{endpoint}/openai/models",
        headers={"api-key": api_key},
        params={"api-version": api_version},
    )
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    if result["status"] == "active" and not result["models"] and deployment:
        result["models"] = [deployment]
    elif result["status"] != "active" and deployment:
        # Keep deployment visible even when listing fails (common on Foundry).
        result["models"] = [deployment]
    _cache_set("azure_openai", result)
    return result


async def _health_openrouter() -> Dict[str, Any]:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cached = _cache_get("openrouter")
    if cached:
        return cached
    result = await _probe(
        method="GET",
        url="https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    if result["status"] == "active" and not result["models"]:
        result["models"] = [os.getenv("OPENROUTER_DEFAULT_MODEL", "z-ai/glm-4.5")]
    _cache_set("openrouter", result)
    return result


async def _health_anthropic() -> Dict[str, Any]:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cached = _cache_get("anthropic")
    if cached:
        return cached
    result = await _probe(
        method="GET",
        url="https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    if result["status"] == "active" and not result["models"]:
        result["models"] = ["claude-3-5-sonnet-latest"]
    _cache_set("anthropic", result)
    return result


async def _health_gemini() -> Dict[str, Any]:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cached = _cache_get("gemini")
    if cached:
        return cached
    result = await _probe(
        method="GET",
        url="https://generativelanguage.googleapis.com/v1beta/models",
        params={"key": key},
    )
    if result["status"] == "active" and not result["models"]:
        result["models"] = [os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash")]
    _cache_set("gemini", result)
    return result


async def _health_ollama() -> Dict[str, Any]:
    base = (settings.ollama_base_url or "").rstrip("/")
    if not base:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    # Ollama is "configured" when a base URL is set; probe for active/unreachable.
    cached = _cache_get("ollama")
    if cached:
        return cached
    result = await _probe(method="GET", url=f"{base}/api/tags")
    if result["status"] == "active" and not result["models"]:
        result["models"] = [settings.ollama_default_model] if settings.ollama_default_model else []
    # URL present but never verified successfully → still report configured when
    # the probe did not run (shouldn't happen); unreachable/active cover live.
    if result["status"] == "unreachable" and not result.get("error"):
        result["status"] = "configured"
    _cache_set("ollama", result)
    return result


def _base_catalog() -> List[Dict[str, Any]]:
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    return [
        {
            "key": "ollama",
            "label": "Ollama",
            "kind": "local",
            "configured": bool(settings.ollama_base_url),
            "fallback_models": [settings.ollama_default_model] if settings.ollama_default_model else [],
            "notes": "Local / sovereign serving",
            "health": _health_ollama,
        },
        {
            "key": "openai",
            "label": "OpenAI",
            "kind": "cloud",
            "configured": _env("OPENAI_API_KEY"),
            "fallback_models": [settings.default_model] if settings.default_model else ["gpt-5"],
            "notes": "OpenAI API (chat completions, streaming)",
            "health": _health_openai,
        },
        {
            "key": "azure_openai",
            "label": "Azure OpenAI / AI Foundry",
            "kind": "cloud",
            "configured": _env("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"),
            "fallback_models": [azure_deployment] if azure_deployment else [],
            "notes": "Azure-hosted OpenAI deployments, incl. AI Foundry endpoints",
            "health": _health_azure,
        },
        {
            "key": "openrouter",
            "label": "OpenRouter",
            "kind": "cloud",
            "configured": _env("OPENROUTER_API_KEY"),
            "fallback_models": [os.getenv("OPENROUTER_DEFAULT_MODEL", "z-ai/glm-4.5")],
            "notes": "Multi-provider gateway (Anthropic, Meta, Mistral, ...)",
            "health": _health_openrouter,
        },
        {
            "key": "anthropic",
            "label": "Anthropic",
            "kind": "cloud",
            "configured": _env("ANTHROPIC_API_KEY"),
            "fallback_models": ["claude-3-5-sonnet-latest"],
            "notes": "Claude models via the Anthropic API",
            "health": _health_anthropic,
        },
        {
            "key": "gemini",
            "label": "Google Gemini",
            "kind": "cloud",
            "configured": _env("GEMINI_API_KEY"),
            "fallback_models": [os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash")],
            "notes": "Gemini models via the Google AI API",
            "health": _health_gemini,
        },
    ]


async def list_providers(*, include_local_serving: bool = True) -> List[Dict[str, Any]]:
    """Return live provider statuses + real model lists where available."""
    providers: List[Dict[str, Any]] = []
    for entry in _base_catalog():
        health_fn = entry["health"]
        if entry["configured"]:
            health = await health_fn()
            status = health["status"]
            # Credentials present but probe not yet conclusive → configured.
            if status == "available":
                status = "configured"
            models = health.get("models") or entry["fallback_models"]
            latency_ms = health.get("latency_ms")
            error = health.get("error")
        else:
            status = "available"
            models = entry["fallback_models"]
            latency_ms = None
            error = None
        providers.append(
            {
                "key": entry["key"],
                "label": entry["label"],
                "kind": entry["kind"],
                "status": status,
                "models": models,
                "latency_ms": latency_ms,
                "notes": entry["notes"],
                "error": error,
            }
        )

    if include_local_serving:
        for local in list_routable_providers():
            providers.append(
                {
                    "key": local["key"],
                    "label": local["label"],
                    "kind": "local",
                    "status": local.get("status") or "active",
                    "models": local.get("models") or [],
                    "latency_ms": None,
                    "notes": local.get("notes"),
                    "error": None,
                    "runtime": local.get("runtime"),
                    "node": local.get("node"),
                    "openai_base_url": local.get("openai_base_url"),
                }
            )
    return providers
