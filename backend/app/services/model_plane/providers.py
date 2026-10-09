"""Unified provider registry with live health checks (TTL cache ~60s)."""

from __future__ import annotations

import os
import time
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.model_plane.registration import list_routable_providers, provider_key

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = get_logger(__name__)

HEALTH_TTL_SECONDS = 60.0
_HEALTH_TIMEOUT = 5.0

# key -> (expires_at, payload)
_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_cache_workspace: ContextVar[str] = ContextVar("model_probe_workspace", default="global")
RUNTIME_PROVIDERS = frozenset({"openai", "azure_openai", "ollama", "huggingface"})


def _env(*names: str) -> bool:
    return all(bool(os.getenv(name)) for name in names)


def _workspace_keys(workspace: Optional["Workspace"]) -> dict[str, str]:
    """Decrypted workspace API keys (provider → key), empty when none."""
    if workspace is None:
        return {}
    from app.services.model_plane import workspace_config as ws_cfg

    out: dict[str, str] = {}
    for provider in ws_cfg.CLOUD_PROVIDERS:
        key = ws_cfg.get_decrypted_api_key(workspace, provider)
        if key:
            out[provider] = key
    return out


def _cache_get(key: str) -> Optional[dict[str, Any]]:
    entry = _cache.get((_cache_workspace.get(), key))
    if not entry:
        return None
    expires_at, payload = entry
    if time.monotonic() >= expires_at:
        return None
    return dict(payload)


def _cache_set(key: str, payload: dict[str, Any]) -> None:
    _cache[(_cache_workspace.get(), key)] = (time.monotonic() + HEALTH_TTL_SECONDS, dict(payload))


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
    headers: Optional[dict[str, str]] = None,
    params: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
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
            "error": f"{type(exc).__name__}: provider request failed",
        }


def _extract_models(response: httpx.Response) -> list[str]:
    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        return []

    # OpenAI / OpenRouter / Azure / Anthropic: {"data":[{"id":...}, ...]}
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        ids: list[str] = []
        for item in data["data"]:
            if isinstance(item, dict):
                mid = item.get("id") or item.get("name")
                if mid:
                    ids.append(str(mid))
        return ids[:500]

    # Ollama: {"models":[{"name":...}, ...]}
    if isinstance(data, dict) and isinstance(data.get("models"), list):
        names: list[str] = []
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


async def _health_openai(*, api_key: Optional[str] = None) -> dict[str, Any]:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cache_key = f"openai:{'ws' if api_key else 'env'}"
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
) -> dict[str, Any]:
    resolved_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
    resolved_endpoint = (endpoint or os.getenv("AZURE_OPENAI_ENDPOINT") or "").rstrip("/")
    if not resolved_key or not resolved_endpoint:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cache_key = f"azure_openai:{'ws' if api_key else 'env'}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
    result = await _probe(
        method="GET",
        url=f"{resolved_endpoint}/openai/models",
        headers={"api-key": resolved_key},
        params={"api-version": version},
    )
    dep = deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT")
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
) -> dict[str, Any]:
    resolved_key = api_key or os.getenv("AZURE_FOUNDRY_API_KEY")
    resolved_endpoint = (endpoint or os.getenv("AZURE_FOUNDRY_ENDPOINT") or "").rstrip("/")
    if not resolved_key or not resolved_endpoint:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cache_key = f"azure_foundry:{'ws' if api_key else 'env'}"
    cached = _cache_get(cache_key)
    if cached:
        return cached
    version = api_version or os.getenv("AZURE_FOUNDRY_API_VERSION", "2024-05-01-preview")
    # Foundry serverless / Models-as-a-Service endpoints expose the Azure AI
    # Model Inference API; /info returns the deployed model's metadata.
    result = await _probe(
        method="GET",
        url=f"{resolved_endpoint}/info",
        headers={"api-key": resolved_key, "Authorization": f"Bearer {resolved_key}"},
        params={"api-version": version},
    )
    dep = deployment or os.getenv("AZURE_FOUNDRY_MODEL")
    if not result["models"] and dep:
        result["models"] = [dep]
    _cache_set(cache_key, result)
    return result


async def _health_openrouter(*, api_key: Optional[str] = None) -> dict[str, Any]:
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cache_key = f"openrouter:{'ws' if api_key else 'env'}"
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


async def _health_anthropic(*, api_key: Optional[str] = None) -> dict[str, Any]:
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cache_key = f"anthropic:{'ws' if api_key else 'env'}"
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


async def _health_gemini(*, api_key: Optional[str] = None) -> dict[str, Any]:
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        return {"status": "available", "latency_ms": None, "models": [], "error": None}
    cache_key = f"gemini:{'ws' if api_key else 'env'}"
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


async def _health_ollama() -> dict[str, Any]:
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


def _huggingface_entry(workspace):
    from app.services.huggingface.connection import (
        DEFAULT_ENDPOINT,
        INFERENCE_ENDPOINT,
        resolve_for_workspace,
    )
    from app.services.huggingface.errors import HFError

    connection = None
    error = None
    try:
        connection = resolve_for_workspace(workspace)
        if connection.endpoint != DEFAULT_ENDPOINT:
            error = "HF_INFERENCE_ENDPOINT_UNSUPPORTED"
    except HFError as exc:
        error = exc.code

    async def health():
        if error:
            return {"status": "unreachable", "models": [], "latency_ms": None, "error": error}
        return await _probe(
            method="GET",
            url=INFERENCE_ENDPOINT + "/models",
            headers={"Authorization": "Bearer " + connection.token},
        )

    return {
        "key": "huggingface",
        "label": "Hugging Face Inference",
        "kind": "cloud",
        "configured": bool(error or (connection and connection.token)),
        "fallback_models": [],
        "notes": "Hugging Face connection; license policy checked before every call",
        "health": health,
        "api_key_set": bool(connection and connection.token),
        "credential_source": connection.source if connection else None,
    }


def _base_catalog(
    *,
    workspace: Optional["Workspace"] = None,
    ws_keys: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    keys = ws_keys if ws_keys is not None else _workspace_keys(workspace)
    azure_meta: dict[str, str] = {}
    foundry_meta: dict[str, str] = {}
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

    return [
        _huggingface_entry(workspace),
        {
            "key": "ollama",
            "label": "Ollama",
            "kind": "local",
            "configured": bool(settings.ollama_base_url),
            "fallback_models": [settings.ollama_default_model]
            if settings.ollama_default_model
            else [],
            "notes": "Local / sovereign serving",
            "health": lambda: _health_ollama(),
            "api_key_set": False,
            "credential_source": None,
        },
        {
            "key": "openai",
            "label": "OpenAI",
            "kind": "cloud",
            "configured": bool(keys.get("openai") or os.getenv("OPENAI_API_KEY")),
            "fallback_models": [settings.default_model] if settings.default_model else ["gpt-5"],
            "notes": "OpenAI API (chat completions, streaming)",
            "health": lambda: _health_openai(api_key=keys.get("openai")),
            "api_key_set": bool(keys.get("openai") or os.getenv("OPENAI_API_KEY")),
            "credential_source": "workspace"
            if keys.get("openai")
            else ("env" if os.getenv("OPENAI_API_KEY") else None),
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
            "credential_source": "workspace"
            if keys.get("azure_openai")
            else ("env" if azure_key else None),
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
            "credential_source": "workspace"
            if keys.get("azure_foundry")
            else ("env" if foundry_key else None),
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
            "credential_source": "workspace"
            if keys.get("openrouter")
            else ("env" if os.getenv("OPENROUTER_API_KEY") else None),
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
            "credential_source": "workspace"
            if keys.get("anthropic")
            else ("env" if os.getenv("ANTHROPIC_API_KEY") else None),
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
            "credential_source": "workspace"
            if keys.get("gemini")
            else ("env" if os.getenv("GEMINI_API_KEY") else None),
        },
    ]


def model_compatibility(provider: str, model: str) -> str:
    """Conservative name-based classification, never an inference attestation."""
    name = model.lower().strip()
    if any(
        part in name
        for part in (
            "embedding",
            "embed-",
            "nomic-embed",
            "bge-",
            "e5-",
            "rerank",
            "whisper",
            "transcrib",
            "tts",
            "dall-e",
            "image",
            "moderation",
            "realtime",
            "audio",
            "sora",
        )
    ):
        return "other"
    if name.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4", "claude-", "gemini-")):
        return "text_generation"
    if provider == "ollama" and any(
        part in name
        for part in ("llama", "qwen", "mistral", "gemma", "deepseek", "phi", "command-r")
    ):
        return "text_generation"
    return "unknown"


async def list_providers(
    *,
    include_local_serving: bool = True,
    workspace: Optional["Workspace"] = None,
    provider_key: str | None = None,
    node_snapshots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    # A probe result may contain account-specific model IDs. ContextVar keeps
    # concurrent requests and global/env probes in separate cache namespaces.
    scope = f"workspace:{workspace.id}" if workspace is not None else "global"
    token = _cache_workspace.set(scope)
    try:
        return await _list_providers(
            include_local_serving=include_local_serving,
            workspace=workspace,
            provider_key=provider_key,
            node_snapshots=node_snapshots,
        )
    finally:
        _cache_workspace.reset(token)


def scoped_serving_providers(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Public projection from this request's snapshots, never the global registry."""
    rows = []
    for node in nodes:
        if node.get("status") not in ("active", "configured"):
            continue
        for instance in node.get("instances") or []:
            if (
                not isinstance(instance, dict)
                or instance.get("status") != "running"
                or not instance.get("id")
            ):
                continue
            model = str(instance.get("model") or "")
            node_name = str(node.get("name") or "")
            rows.append(
                {
                    "key": provider_key(node_name, str(instance["id"])),
                    "label": instance.get("name") or model or instance["id"],
                    "kind": "local",
                    "runtime": instance.get("provider") or instance.get("engine"),
                    "node": node_name,
                    "instance_id": instance["id"],
                    "model": model,
                    "models": [model] if model else [],
                    "status": "active",
                    "runtime_available": False,
                    "notes": "Serving instance on " + node_name,
                    **{
                        field: instance[field]
                        for field in (
                            "artifact_id",
                            "revision",
                            "variant",
                            "runtime_version",
                            "workspace_id",
                            "deployment_id",
                        )
                        if instance.get(field) is not None
                    },
                }
            )
    return rows


async def list_models(*, workspace: "Workspace") -> list[dict[str, Any]]:
    rows = await list_providers(workspace=workspace)
    return [
        {
            "id": f"{provider['key']}:{model}",
            "name": model,
            "model": model,
            "provider": provider["key"],
            "status": provider["status"],
            "configured": provider.get("configured", False),
            "discovered": provider.get("models_source") == "provider_catalog",
            "runtime_available": provider.get("runtime_available", False),
            "compatibility": model_compatibility(provider["key"], model),
            "compatibility_source": "name_heuristic",
            "credential_source": provider.get("credential_source"),
            "generation_verified": False,
        }
        for provider in rows
        for model in dict.fromkeys(provider.get("models") or [])
    ]


async def _list_providers(
    *,
    include_local_serving: bool = True,
    workspace: Optional["Workspace"] = None,
    provider_key: str | None = None,
    node_snapshots: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return live provider statuses + real model lists where available."""
    ws_keys = _workspace_keys(workspace)
    from app.services.model_plane import workspace_config as ws_cfg

    stored = (
        {row["key"]: row for row in ws_cfg.get_cloud_credentials_public(workspace)}
        if workspace is not None
        else {}
    )
    providers: list[dict[str, Any]] = []
    for entry in _base_catalog(workspace=workspace, ws_keys=ws_keys):
        if provider_key is not None and entry["key"] != provider_key:
            continue
        health_fn = entry["health"]
        unreadable_key = stored.get(entry["key"], {}).get("api_key_set") and not ws_keys.get(
            entry["key"]
        )
        if unreadable_key:
            entry = {
                **entry,
                "configured": True,
                "api_key_set": True,
                "credential_source": "workspace",
            }
        if entry["configured"]:
            health = (
                {
                    "status": "unreachable",
                    "models": [],
                    "latency_ms": None,
                    "error": "Workspace credential cannot be read; reconnect this provider.",
                }
                if unreadable_key
                else await health_fn()
            )
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
                "api_key_set": entry.get("api_key_set"),
                "credential_source": entry.get("credential_source"),
                "configured": entry["configured"],
                "runtime_available": entry["key"] in RUNTIME_PROVIDERS,
                "models_source": "provider_catalog"
                if entry["configured"] and health.get("models") and status == "active"
                else "configured_default",
                "models_truncated": len(models) >= 500,
                "generation_verified": False,
            }
        )

    if include_local_serving:
        if workspace is not None:
            if node_snapshots is None:
                from app.services.model_plane import serving_nodes

                node_snapshots = (
                    await serving_nodes.list_nodes(workspace=workspace, sync_registry=False)
                )["nodes"]
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
                    "runtime": local.get("runtime"),
                    "node": local.get("node"),
                    "openai_base_url": local.get("openai_base_url"),
                    "configured": True,
                    "runtime_available": bool(
                        workspace is not None
                        and local.get("artifact_id")
                        and local.get("workspace_id") == workspace.id
                    ),
                    "models_source": "serving_configuration",
                    "generation_verified": False,
                    **{
                        field: local[field]
                        for field in (
                            "artifact_id",
                            "revision",
                            "variant",
                            "runtime_version",
                            "deployment_id",
                        )
                        if local.get(field) is not None
                    },
                }
            )
    return providers
