"""Unified provider registry with live health checks (TTL cache ~60s)."""

from __future__ import annotations

from contextvars import ContextVar
import hashlib
import os
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.model_plane.errors import classify_provider_error, provider_failure
from app.services.model_plane.registration import list_routable_providers, provider_key

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = get_logger(__name__)

HEALTH_TTL_SECONDS = 60.0
_HEALTH_TIMEOUT = 5.0

# key -> (expires_at, payload)
_cache: Dict[tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
_cache_workspace: ContextVar[str] = ContextVar("model_probe_workspace", default="global")
RUNTIME_PROVIDERS = frozenset({"openai", "azure_openai", "ollama"})


def _env(*names: str) -> bool:
    return all(bool(os.getenv(name)) for name in names)


def _workspace_keys(workspace: Optional["Workspace"]) -> Dict[str, str]:
    """Decrypted workspace API keys (provider → key), empty when none."""
    if workspace is None:
        return {}
    from app.services.model_plane import workspace_config as ws_cfg

    out: Dict[str, str] = {}
    for provider in ws_cfg.CLOUD_PROVIDERS:
        key = ws_cfg.get_decrypted_api_key(workspace, provider)
        if key:
            out[provider] = key
    return out


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    entry = _cache.get((_cache_workspace.get(), key))
    if not entry:
        return None
    expires_at, payload = entry
    if time.monotonic() >= expires_at:
        return None
    return dict(payload)


def _cache_set(key: str, payload: Dict[str, Any]) -> None:
    _cache[(_cache_workspace.get(), key)] = (time.monotonic() + HEALTH_TTL_SECONDS, dict(payload))


def _scoped_cache_key(provider: str, *configuration: Optional[str]) -> str:
    """Keep health results isolated without retaining credentials in cache keys."""
    material = "\0".join(str(item or "") for item in configuration).encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()[:16]
    return f"{provider}:{digest}"


def clear_health_cache(*, workspace: Optional["Workspace"] = None) -> None:
    if workspace is None:
        _cache.clear()
        return
    scope = f"workspace:{workspace.id}"
    for key in list(_cache):
        if key[0] == scope:
            del _cache[key]


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
            failure = classify_provider_error(
                httpx.HTTPStatusError(
                    "Provider health probe returned an error",
                    request=httpx.Request(method, "https://provider.invalid"),
                    response=response,
                )
            )
            return {
                "status": "unreachable",
                "latency_ms": latency_ms,
                "models": [],
                "models_verified": False,
                "error": failure.message,
                "error_code": failure.code,
                "retryable": failure.retryable,
            }
        models = _extract_models(response)
        return {
            "status": "active",
            "latency_ms": latency_ms,
            "models": models,
            "models_verified": bool(models),
            "error": None,
            "error_code": None,
            "retryable": False,
        }
    except Exception as exc:  # noqa: BLE001 — surface as unreachable for UI
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        failure = classify_provider_error(exc)
        logger.debug(
            "Provider health probe failed",
            error_code=failure.code,
            exception_type=type(exc).__name__,
        )
        return {
            "status": "unreachable",
            "latency_ms": latency_ms,
            "models": [],
            "models_verified": False,
            "error": failure.message,
            "error_code": failure.code,
            "retryable": failure.retryable,
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
        return ids[:500]

    # Ollama: {"models":[{"name":...}, ...]}
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        names: List[str] = []
        for item in data["models"]:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model")
                if name:
                    names.append(str(name).removeprefix("models/"))
        return names[:500]

    # Gemini: {"models":[{"name":"models/gemini-..."}, ...]}
    if isinstance(data, dict) and "models" in data and isinstance(data["models"], list):
        names = []
        for item in data["models"]:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]).removeprefix("models/"))
        return names[:500]

    # Azure AI Model Inference /info: {"model_name": "...", ...}
    if isinstance(data, dict) and data.get("model_name"):
        return [str(data["model_name"])]

    return []


async def _health_openai(*, api_key: Optional[str] = None) -> Dict[str, Any]:
    key = api_key or settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cache_key = _scoped_cache_key("openai", key)
    cached = _cache_get(cache_key)
    if cached:
        return cached
    result = await _probe(
        method="GET",
        url="https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    if result["status"] == "active" and not result["models"]:
        result["models"] = [settings.default_model] if settings.default_model else []
    _cache_set(cache_key, result)
    return result


async def _health_azure(
    *,
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    api_version: Optional[str] = None,
    deployment: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
    resolved_endpoint = (endpoint or os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    if not resolved_key or not resolved_endpoint:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
    dep = deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT")
    cache_key = _scoped_cache_key(
        "azure_openai",
        resolved_key,
        resolved_endpoint,
        version,
        dep,
    )
    cached = _cache_get(cache_key)
    if cached:
        return cached
    result = await _probe(
        method="GET",
        url=f"{resolved_endpoint}/openai/models",
        headers={"api-key": resolved_key},
        params={"api-version": version},
    )
    if result["status"] == "active" and not result["models"] and dep:
        result["models"] = [dep]
    elif result["status"] != "active" and dep:
        result["models"] = [dep]
    _cache_set(cache_key, result)
    return result


async def _health_foundry(
    *,
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    api_version: Optional[str] = None,
    deployment: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_key = api_key or os.getenv("AZURE_FOUNDRY_API_KEY")
    resolved_endpoint = (endpoint or os.getenv("AZURE_FOUNDRY_ENDPOINT") or "").rstrip("/")
    if not resolved_key or not resolved_endpoint:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    version = api_version or os.getenv("AZURE_FOUNDRY_API_VERSION", "2024-05-01-preview")
    dep = deployment or os.getenv("AZURE_FOUNDRY_MODEL")
    cache_key = _scoped_cache_key(
        "azure_foundry",
        resolved_key,
        resolved_endpoint,
        version,
        dep,
    )
    cached = _cache_get(cache_key)
    if cached:
        return cached
    # Foundry serverless / Models-as-a-Service endpoints expose the Azure AI
    # Model Inference API; /info returns the deployed model's metadata.
    result = await _probe(
        method="GET",
        url=f"{resolved_endpoint}/info",
        headers={"api-key": resolved_key, "Authorization": f"Bearer {resolved_key}"},
        params={"api-version": version},
    )
    if not result["models"] and dep:
        result["models"] = [dep]
    _cache_set(cache_key, result)
    return result


async def _health_openrouter(*, api_key: Optional[str] = None) -> Dict[str, Any]:
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cache_key = _scoped_cache_key("openrouter", key)
    cached = _cache_get(cache_key)
    if cached:
        return cached
    result = await _probe(
        method="GET",
        url="https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    if result["status"] == "active" and not result["models"]:
        result["models"] = [os.getenv("OPENROUTER_DEFAULT_MODEL", "z-ai/glm-4.5")]
    _cache_set(cache_key, result)
    return result


async def _health_anthropic(*, api_key: Optional[str] = None) -> Dict[str, Any]:
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cache_key = _scoped_cache_key("anthropic", key)
    cached = _cache_get(cache_key)
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
    _cache_set(cache_key, result)
    return result


async def _health_gemini(*, api_key: Optional[str] = None) -> Dict[str, Any]:
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cache_key = _scoped_cache_key("gemini", key)
    cached = _cache_get(cache_key)
    if cached:
        return cached
    result = await _probe(
        method="GET",
        url="https://generativelanguage.googleapis.com/v1beta/models",
        params={"key": key},
    )
    if result["status"] == "active" and not result["models"]:
        result["models"] = [os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash")]
    _cache_set(cache_key, result)
    return result


async def _health_ollama() -> Dict[str, Any]:
    base = (settings.ollama_base_url or "").rstrip("/")
    if not base:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    # Ollama is "configured" when a base URL is set; probe for active/unreachable.
    cache_key = _scoped_cache_key("ollama", base)
    cached = _cache_get(cache_key)
    if cached:
        return cached
    result = await _probe(method="GET", url=f"{base}/api/tags")
    if result["status"] == "active" and not result["models"]:
        result["models"] = [settings.ollama_default_model] if settings.ollama_default_model else []
    # URL present but never verified successfully → still report configured when
    # the probe did not run (shouldn't happen); unreachable/active cover live.
    if result["status"] == "unreachable" and not result.get("error"):
        result["status"] = "configured"
    _cache_set(cache_key, result)
    return result


def _base_catalog(
    *,
    workspace: Optional["Workspace"] = None,
    ws_keys: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    keys = ws_keys if ws_keys is not None else _workspace_keys(workspace)
    azure_meta: Dict[str, str] = {}
    foundry_meta: Dict[str, str] = {}
    if workspace is not None:
        from app.services.model_plane import workspace_config as ws_cfg

        azure_meta = ws_cfg.get_provider_meta(workspace, "azure_openai")
        foundry_meta = ws_cfg.get_provider_meta(workspace, "azure_foundry")
    azure_deployment = azure_meta.get("deployment") or os.getenv("AZURE_OPENAI_DEPLOYMENT")
    azure_endpoint = azure_meta.get("endpoint") or os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_key = keys.get("azure_openai") or os.getenv("AZURE_OPENAI_API_KEY")
    foundry_model = foundry_meta.get("deployment") or os.getenv("AZURE_FOUNDRY_MODEL")
    foundry_endpoint = foundry_meta.get("endpoint") or os.getenv("AZURE_FOUNDRY_ENDPOINT")
    foundry_key = keys.get("azure_foundry") or os.getenv("AZURE_FOUNDRY_API_KEY")
    openai_key = keys.get("openai") or settings.openai_api_key or os.getenv("OPENAI_API_KEY")

    return [
        {
            "key": "ollama",
            "label": "Ollama",
            "kind": "local",
            "configured": bool(settings.ollama_base_url),
            "fallback_models": [settings.ollama_default_model] if settings.ollama_default_model else [],
            "notes": "Local / sovereign serving",
            "health": lambda: _health_ollama(),
            "api_key_set": False,
            "credential_source": None,
        },
        {
            "key": "openai",
            "label": "OpenAI",
            "kind": "cloud",
            "configured": bool(openai_key),
            "fallback_models": [settings.default_model] if settings.default_model else ["gpt-5"],
            "notes": "OpenAI API (chat completions, streaming)",
            "health": lambda: _health_openai(api_key=keys.get("openai")),
            "api_key_set": bool(openai_key),
            "credential_source": "workspace" if keys.get("openai") else ("env" if openai_key else None),
        },
        {
            "key": "azure_openai",
            "label": "Azure OpenAI",
            "kind": "cloud",
            "configured": bool(azure_key and azure_endpoint),
            "fallback_models": [azure_deployment] if azure_deployment else [],
            "notes": "Azure-hosted OpenAI deployments (*.openai.azure.com)",
            "health": lambda: _health_azure(
                api_key=keys.get("azure_openai"),
                endpoint=azure_meta.get("endpoint"),
                api_version=azure_meta.get("api_version"),
                deployment=azure_meta.get("deployment"),
            ),
            "api_key_set": bool(azure_key),
            "credential_source": "workspace" if keys.get("azure_openai") else ("env" if azure_key else None),
        },
        {
            "key": "azure_foundry",
            "label": "Azure AI Foundry",
            "kind": "cloud",
            "configured": bool(foundry_key and foundry_endpoint),
            "fallback_models": [foundry_model] if foundry_model else [],
            "notes": "Foundry model catalog — Llama, Mistral, Phi, ... (*.services.ai.azure.com)",
            "health": lambda: _health_foundry(
                api_key=keys.get("azure_foundry"),
                endpoint=foundry_meta.get("endpoint"),
                api_version=foundry_meta.get("api_version"),
                deployment=foundry_meta.get("deployment"),
            ),
            "api_key_set": bool(foundry_key),
            "credential_source": "workspace" if keys.get("azure_foundry") else ("env" if foundry_key else None),
        },
        {
            "key": "openrouter",
            "label": "OpenRouter",
            "kind": "cloud",
            "configured": bool(keys.get("openrouter") or os.getenv("OPENROUTER_API_KEY")),
            "fallback_models": [os.getenv("OPENROUTER_DEFAULT_MODEL", "z-ai/glm-4.5")],
            "notes": "Multi-provider gateway (Anthropic, Meta, Mistral, ...)",
            "health": lambda: _health_openrouter(api_key=keys.get("openrouter")),
            "api_key_set": bool(keys.get("openrouter") or os.getenv("OPENROUTER_API_KEY")),
            "credential_source": "workspace" if keys.get("openrouter") else ("env" if os.getenv("OPENROUTER_API_KEY") else None),
        },
        {
            "key": "anthropic",
            "label": "Anthropic",
            "kind": "cloud",
            "configured": bool(keys.get("anthropic") or os.getenv("ANTHROPIC_API_KEY")),
            "fallback_models": ["claude-3-5-sonnet-latest"],
            "notes": "Claude models via the Anthropic API",
            "health": lambda: _health_anthropic(api_key=keys.get("anthropic")),
            "api_key_set": bool(keys.get("anthropic") or os.getenv("ANTHROPIC_API_KEY")),
            "credential_source": "workspace" if keys.get("anthropic") else ("env" if os.getenv("ANTHROPIC_API_KEY") else None),
        },
        {
            "key": "gemini",
            "label": "Google Gemini",
            "kind": "cloud",
            "configured": bool(keys.get("gemini") or os.getenv("GEMINI_API_KEY")),
            "fallback_models": [os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash")],
            "notes": "Gemini models via the Google AI API",
            "health": lambda: _health_gemini(api_key=keys.get("gemini")),
            "api_key_set": bool(keys.get("gemini") or os.getenv("GEMINI_API_KEY")),
            "credential_source": "workspace" if keys.get("gemini") else ("env" if os.getenv("GEMINI_API_KEY") else None),
        },
    ]


def model_compatibility(provider: str, model: str) -> str:
    """Conservative name-based classification, never an inference attestation."""
    name = model.lower().strip()
    if any(part in name for part in (
        "embedding", "embed-", "nomic-embed", "bge-", "e5-", "rerank",
        "whisper", "transcrib", "tts", "dall-e", "image", "moderation", "realtime", "audio", "sora",
    )):
        return "other"
    if name.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4", "claude-", "gemini-")):
        return "text_generation"
    if provider == "ollama" and any(part in name for part in ("llama", "qwen", "mistral", "gemma", "deepseek", "phi", "command-r")):
        return "text_generation"
    return "unknown"


async def list_providers(
    *, include_local_serving: bool = True, workspace: Optional["Workspace"] = None,
    provider_key: str | None = None,
    node_snapshots: list[dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    # A probe result may contain account-specific model IDs. ContextVar keeps
    # concurrent requests and global/env probes in separate cache namespaces.
    scope = f"workspace:{workspace.id}" if workspace is not None else "global"
    token = _cache_workspace.set(scope)
    try:
        return await _list_providers(include_local_serving=include_local_serving, workspace=workspace, provider_key=provider_key, node_snapshots=node_snapshots)
    finally:
        _cache_workspace.reset(token)


def scoped_serving_providers(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Public projection from this request's snapshots, never the global registry."""
    rows = []
    for node in nodes:
        if node.get("status") not in ("active", "configured"):
            continue
        for instance in node.get("instances") or []:
            if not isinstance(instance, dict) or instance.get("status") != "running" or not instance.get("id"):
                continue
            model = str(instance.get("model") or "")
            node_name = str(node.get("name") or "")
            rows.append({
                "key": provider_key(node_name, str(instance["id"])),
                "label": instance.get("name") or model or instance["id"],
                "kind": "local", "runtime": instance.get("provider") or instance.get("engine"),
                "node": node_name, "instance_id": instance["id"], "model": model,
                "models": [model] if model else [], "status": "active",
                "runtime_available": False, "notes": "Serving instance on " + node_name,
            })
    return rows


async def list_models(*, workspace: "Workspace") -> List[Dict[str, Any]]:
    rows = await list_providers(workspace=workspace)
    return [
        {
            "id": f"{provider['key']}:{model}", "name": model, "model": model,
            "provider": provider["key"], "status": provider["status"],
            "configured": provider.get("configured", False),
            "discovered": provider.get("models_source") == "provider_catalog",
            "runtime_available": provider.get("runtime_available", False),
            "compatibility": model_compatibility(provider["key"], model),
            "compatibility_source": "name_heuristic",
            "credential_source": provider.get("credential_source"),
            "generation_verified": False,
        }
        for provider in rows for model in dict.fromkeys(provider.get("models") or [])
    ]


async def _list_providers(
    *,
    include_local_serving: bool = True,
    workspace: Optional["Workspace"] = None,
    provider_key: str | None = None,
    node_snapshots: list[dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    """Return live provider statuses + real model lists where available."""
    ws_keys = _workspace_keys(workspace)
    from app.services.model_plane import workspace_config as ws_cfg
    stored = {row["key"]: row for row in ws_cfg.get_cloud_credentials_public(workspace)} if workspace is not None else {}
    providers: List[Dict[str, Any]] = []
    for entry in _base_catalog(workspace=workspace, ws_keys=ws_keys):
        if provider_key is not None and entry["key"] != provider_key:
            continue
        health_fn = entry["health"]
        unreadable_key = stored.get(entry["key"], {}).get("api_key_set") and not ws_keys.get(entry["key"])
        if unreadable_key:
            entry = {**entry, "configured": True, "api_key_set": True, "credential_source": "workspace"}
        if entry["configured"]:
            health = ({"status": "unreachable", "models": [], "latency_ms": None,
                       "error": "Workspace credential cannot be read; reconnect this provider."}
                      if unreadable_key else await health_fn())
            status = health["status"]
            # Credentials present but probe not yet conclusive → configured.
            if status == "available":
                status = "configured"
            models = health.get("models") or entry["fallback_models"]
            latency_ms = health.get("latency_ms")
            error = health.get("error")
            error_code = health.get("error_code")
            retryable = health.get("retryable")
        else:
            status = "available"
            models = entry["fallback_models"]
            latency_ms = None
            error = None
            error_code = None
            retryable = False
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
                "error_code": error_code,
                "retryable": retryable,
                "api_key_set": entry.get("api_key_set"),
                "credential_source": entry.get("credential_source"),
                "configured": entry["configured"],
                "runtime_available": entry["key"] in RUNTIME_PROVIDERS,
                "models_source": "provider_catalog" if entry["configured"] and health.get("models") and status == "active" else "configured_default",
                "models_truncated": len(models) >= 500,
                "generation_verified": False,
            }
        )

    if include_local_serving:
        if workspace is not None:
            if node_snapshots is None:
                from app.services.model_plane import serving_nodes
                node_snapshots = (await serving_nodes.list_nodes(workspace=workspace, sync_registry=False))["nodes"]
            local_rows = scoped_serving_providers(node_snapshots)
        else:
            local_rows = list_routable_providers()
        for local in local_rows:
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
                    "error_code": None,
                    "retryable": False,
                    "runtime": local.get("runtime"),
                    "node": local.get("node"),
                    "openai_base_url": local.get("openai_base_url"),
                    "configured": True,
                    "runtime_available": False,
                    "models_source": "serving_configuration",
                    "generation_verified": False,
                }
            )
    return providers


async def get_readiness(*, workspace: "Workspace") -> Dict[str, Any]:
    """Report readiness for only the workspace's selected provider and model."""
    from app.services.model_plane import workspace_config as ws_cfg

    routing = ws_cfg.get_routing(workspace)
    provider_key = str(routing["default_provider"])
    model = str(routing["default_model"])
    ws_keys = _workspace_keys(workspace)

    entry = next(
        (
            item
            for item in _base_catalog(workspace=workspace, ws_keys=ws_keys)
            if item["key"] == provider_key
        ),
        None,
    )
    local = next(
        (item for item in list_routable_providers() if item.get("key") == provider_key),
        None,
    )

    base = {
        "provider": provider_key,
        "model": model,
        "source": routing["source"],
    }
    if entry is None and local is None:
        if provider_key.startswith("serving_"):
            failure = provider_failure("provider_unreachable")
            return {
                **base,
                "status": "unavailable",
                "reason": failure.code,
                "message": failure.message,
                "retryable": failure.retryable,
                "provider_status": "unreachable",
            }
        return {
            **base,
            "status": "needs_setup",
            "reason": "provider_not_configured",
            "message": "The selected model provider is not configured.",
            "retryable": False,
        }

    if local is not None:
        provider_status = str(local.get("status") or "unavailable")
        models = [str(item) for item in (local.get("models") or [])]
        if provider_status != "active":
            failure = provider_failure("provider_unreachable")
            return {
                **base,
                "status": "unavailable",
                "reason": failure.code,
                "message": failure.message,
                "retryable": failure.retryable,
                "provider_status": provider_status,
            }
        if model not in models:
            failure = provider_failure("model_missing")
            return {
                **base,
                "status": "needs_setup",
                "reason": failure.code,
                "message": failure.message,
                "retryable": failure.retryable,
                "provider_status": provider_status,
            }
        return {
            **base,
            "status": "ready",
            "reason": "ready",
            "message": "The selected provider and model are ready.",
            "retryable": False,
            "provider_status": provider_status,
        }

    if not entry["configured"]:
        return {
            **base,
            "status": "needs_setup",
            "reason": "provider_not_configured",
            "message": "The selected model provider is not configured.",
            "retryable": False,
            "provider_status": "available",
        }

    health = await entry["health"]()
    provider_status = str(health.get("status") or "unavailable")
    if provider_status != "active":
        reason = str(health.get("error_code") or "provider_unreachable")
        if reason not in {
            "provider_unreachable",
            "credentials_invalid",
            "model_missing",
            "rate_limited",
            "timeout",
            "generation_failed",
        }:
            reason = "generation_failed"
        failure = provider_failure(reason)  # type: ignore[arg-type]
        status = (
            "needs_setup"
            if reason in {"credentials_invalid", "model_missing"}
            else "unavailable"
        )
        return {
            **base,
            "status": status,
            "reason": reason,
            "message": failure.message,
            "retryable": failure.retryable,
            "provider_status": provider_status,
        }

    # Only models returned by the successful live probe count here. Catalog
    # fallbacks remain useful display hints in list_providers, but are not proof
    # that the selected model exists.
    verified_models = (
        [str(item) for item in (health.get("models") or [])]
        if health.get("models_verified") is not False
        else []
    )
    if model not in verified_models:
        failure = provider_failure("model_missing")
        return {
            **base,
            "status": "needs_setup",
            "reason": failure.code,
            "message": failure.message,
            "retryable": failure.retryable,
            "provider_status": provider_status,
        }
    return {
        **base,
        "status": "ready",
        "reason": "ready",
        "message": "The selected provider and model are ready.",
        "retryable": False,
        "provider_status": provider_status,
    }
