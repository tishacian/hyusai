"""Register active serving instances as routable OpenAI-compatible providers.

Active (running) instances discovered via llm-portal are cached here so
``ModelRouter`` and ``app.llm`` (vLLM / OpenAI-compatible) can route to them
without exposing portal credentials to the browser.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.core.logging import get_logger

logger = get_logger(__name__)

# OpenAI-compatible runtimes exposed by llm-portal.
_OPENAI_COMPAT_PROVIDERS = frozenset(
    {"vllm", "ollama", "llamacpp", "lmstudio", "lmdeploy", "sglang"}
)

_lock = threading.Lock()
# key -> descriptor used by ModelRouter / providers listing
_routable: Dict[str, Dict[str, Any]] = {}


def _openai_base_url(node_base_url: str, port: int) -> str:
    parsed = urlparse(node_base_url)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "localhost"
    return f"{scheme}://{host}:{int(port)}/v1"


def provider_key(node_name: str, instance_id: str) -> str:
    safe_node = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in node_name)
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in instance_id)[:24]
    return f"serving_{safe_node}_{safe_id}"


def sync_from_node_snapshots(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Replace the routable registry from node list payloads.

    Returns the current routable descriptors (also stored in-memory).
    """
    next_map: Dict[str, Dict[str, Any]] = {}
    for node in nodes:
        if node.get("status") not in ("active", "configured"):
            continue
        node_name = str(node.get("name") or "")
        node_base = str(node.get("base_url") or "")
        if not node_name or not node_base:
            continue
        for inst in node.get("instances") or []:
            if not isinstance(inst, dict):
                continue
            status = str(inst.get("status") or "").lower()
            if status != "running":
                continue
            provider = str(inst.get("provider") or "").lower()
            if provider not in _OPENAI_COMPAT_PROVIDERS:
                continue
            port = inst.get("port")
            if port is None:
                continue
            try:
                port_i = int(port)
            except (TypeError, ValueError):
                continue
            instance_id = str(inst.get("id") or "")
            if not instance_id:
                continue
            key = provider_key(node_name, instance_id)
            model = str(inst.get("model") or "")
            openai_url = _openai_base_url(node_base, port_i)
            next_map[key] = {
                "key": key,
                "label": str(inst.get("name") or f"{provider}:{model}" or key),
                "kind": "local",
                "runtime": provider,
                "node": node_name,
                "instance_id": instance_id,
                "model": model,
                "models": [model] if model else [],
                "openai_base_url": openai_url,
                "api_key": "local",
                "port": port_i,
                "status": "active",
                "notes": f"Serving instance on node {node_name}",
            }

    with _lock:
        _routable.clear()
        _routable.update(next_map)
        snapshot = list(_routable.values())

    logger.info("Serving providers registered", count=len(snapshot), keys=[p["key"] for p in snapshot])
    return snapshot


def list_routable_providers() -> List[Dict[str, Any]]:
    with _lock:
        return [dict(item) for item in _routable.values()]


def get_routable_provider(key: str) -> Optional[Dict[str, Any]]:
    with _lock:
        item = _routable.get(key)
        return dict(item) if item else None


def clear_routable_providers() -> None:
    with _lock:
        _routable.clear()


def build_llm(*, key: str | None = None, provider_meta: Dict[str, Any] | None = None):
    """Return an ``app.llm.LLM`` bound to a registered local OpenAI-compatible endpoint."""
    from app.llm import LLM

    meta = provider_meta or (get_routable_provider(key) if key else None)
    if not meta:
        raise KeyError(f"No routable local provider for key={key!r}")
    runtime = str(meta.get("runtime") or "vllm")
    # vLLM factory is the canonical OpenAI-compatible local adapter; other
    # runtimes share the same wire protocol.
    factory = "vllm" if runtime in _OPENAI_COMPAT_PROVIDERS else runtime
    return LLM(
        provider=factory,
        api_key=str(meta.get("api_key") or "local"),
        base_url=str(meta["openai_base_url"]),
    )
