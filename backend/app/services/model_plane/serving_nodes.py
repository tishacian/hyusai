"""Serving-node registry + authenticated HTTP client for omnirag-llm-portal.

Zero configured nodes is a first-class empty state (demo VM has no GPU host).
Portal credentials never leave the backend.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.model_plane.registration import sync_from_node_snapshots

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = get_logger(__name__)

_READ_TIMEOUT = 8.0
_LIFECYCLE_TIMEOUT = 60.0


@dataclass(frozen=True)
class ServingNodeConfig:
    name: str
    base_url: str
    token: str = ""


def parse_serving_nodes(
    raw: Optional[str] = None,
    *,
    workspace: Optional["Workspace"] = None,
) -> List[ServingNodeConfig]:
    """Parse env ``LLM_SERVING_NODES_JSON`` and merge workspace-attached nodes.

    Workspace entries override env nodes with the same ``name``.
    Accepted env shapes:
    - ``[]`` / empty / whitespace → no env nodes
    - JSON list of ``{"name","base_url","token"}``
    """
    by_name: Dict[str, ServingNodeConfig] = {}

    text = (raw if raw is not None else settings.llm_serving_nodes_json) or ""
    text = text.strip()
    if text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid LLM_SERVING_NODES_JSON", error=str(exc))
            data = []
        if not isinstance(data, list):
            logger.warning("LLM_SERVING_NODES_JSON must be a JSON list")
            data = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            base_url = (
                str(item.get("base_url") or item.get("baseUrl") or "").strip().rstrip("/")
            )
            token = str(item.get("token") or "").strip()
            if name and base_url:
                by_name[name] = ServingNodeConfig(
                    name=name, base_url=base_url, token=token
                )

    if workspace is not None:
        from app.services.model_plane import workspace_config as ws_cfg

        for item in ws_cfg.list_serving_node_configs(workspace):
            name = str(item.get("name") or "").strip()
            base_url = str(item.get("base_url") or "").strip().rstrip("/")
            token = str(item.get("token") or "").strip()
            if name and base_url:
                by_name[name] = ServingNodeConfig(
                    name=name, base_url=base_url, token=token
                )

    return list(by_name.values())


def get_node(
    name: str, *, workspace: Optional["Workspace"] = None
) -> Optional[ServingNodeConfig]:
    for node in parse_serving_nodes(workspace=workspace):
        if node.name == name:
            return node
    return None


def _auth_headers(token: str) -> Dict[str, str]:
    """Headers accepted by omnirag-llm-portal SharedTokenAuthMiddleware.

    Portal accepts ``Authorization: Bearer`` and/or ``X-LLM-Portal-Token``.
    Send both so either path works end-to-end.
    """
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-LLM-Portal-Token"] = token
    return headers


def _bytes_to_mb(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    # NVML reports bytes; treat large values as bytes.
    if n >= 1024 * 1024:
        return int(n / (1024 * 1024))
    return int(n)


def normalize_gpu(raw: Any) -> Optional[Dict[str, Any]]:
    """Map llm-portal GPU payload to the Resources UI contract."""
    if not isinstance(raw, dict):
        return None
    # Already in UI shape (or passthrough after a previous normalize).
    if any(k in raw for k in ("count", "devices", "memory_total_mb")):
        return raw

    gpus = raw.get("gpus") if isinstance(raw.get("gpus"), list) else []
    devices: List[Dict[str, Any]] = []
    mem_total = 0
    mem_used = 0
    util_sum = 0.0
    util_n = 0
    for gpu in gpus:
        if not isinstance(gpu, dict):
            continue
        mem = gpu.get("memory") if isinstance(gpu.get("memory"), dict) else {}
        total_mb = _bytes_to_mb(mem.get("total"))
        used_mb = _bytes_to_mb(mem.get("used"))
        util = None
        util_block = gpu.get("utilization")
        if isinstance(util_block, dict) and util_block.get("gpu") is not None:
            try:
                util = float(util_block["gpu"])
            except (TypeError, ValueError):
                util = None
        elif isinstance(util_block, (int, float)):
            util = float(util_block)
        if total_mb is not None:
            mem_total += total_mb
        if used_mb is not None:
            mem_used += used_mb
        if util is not None:
            util_sum += util
            util_n += 1
        devices.append(
            {
                "index": gpu.get("index"),
                "name": gpu.get("name"),
                "memory_total_mb": total_mb,
                "memory_used_mb": used_mb,
                "utilization": util,
            }
        )

    count = raw.get("total_count")
    if count is None:
        count = len(devices)
    return {
        "available": bool(raw.get("available")) and int(count or 0) > 0,
        "count": int(count or 0),
        "memory_total_mb": mem_total or None,
        "memory_used_mb": mem_used or None,
        "utilization": round(util_sum / util_n, 1) if util_n else None,
        "devices": devices,
        "notes": raw.get("error"),
    }


def normalize_instance(raw: Any) -> Dict[str, Any]:
    """Ensure instance dicts expose both ``provider`` and UI ``engine`` alias."""
    if hasattr(raw, "model_dump"):
        data = raw.model_dump()
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        return {"id": str(raw), "status": "unknown"}

    provider = data.get("provider") or data.get("engine")
    if hasattr(provider, "value"):
        provider = provider.value
    status = data.get("status")
    if hasattr(status, "value"):
        status = status.value
    data["provider"] = str(provider) if provider is not None else None
    data["engine"] = data.get("engine") or data["provider"]
    data["status"] = str(status).lower() if status is not None else None
    if data.get("id") is not None:
        data["id"] = str(data["id"])
    return data


class PortalClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


async def _portal_request(
    node: ServingNodeConfig,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    timeout: float = _READ_TIMEOUT,
) -> Any:
    url = urljoin(node.base_url.rstrip("/") + "/", path.lstrip("/"))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(
                method,
                url,
                headers=_auth_headers(node.token),
                json=json_body,
            )
    except httpx.HTTPError as exc:
        raise PortalClientError(f"Serving node {node.name!r} unreachable: {exc}") from exc

    if response.status_code == 404:
        raise PortalClientError(response.text or "Not found", status_code=404)
    if response.status_code >= 400:
        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict) and payload.get("detail"):
                detail = str(payload["detail"])
        except Exception:  # noqa: BLE001
            pass
        raise PortalClientError(
            detail or f"Portal error HTTP {response.status_code}",
            status_code=502 if response.status_code >= 500 else response.status_code,
        )
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return {"raw": response.text}


async def _fetch_node_snapshot(node: ServingNodeConfig) -> Dict[str, Any]:
    """Health + GPU + instances for one node."""
    snapshot: Dict[str, Any] = {
        "name": node.name,
        "base_url": node.base_url,
        "status": "configured",
        "health": None,
        "gpu": None,
        "instances": [],
        "error": None,
    }
    try:
        health = await _portal_request(node, "GET", "/api/v1/health/")
        snapshot["health"] = health
        snapshot["status"] = "active"
    except PortalClientError as exc:
        snapshot["status"] = "unreachable"
        snapshot["error"] = str(exc)
        return snapshot

    try:
        snapshot["gpu"] = normalize_gpu(
            await _portal_request(node, "GET", "/api/v1/gpu/status")
        )
    except PortalClientError as exc:
        # GPU absence is valid (CPU-only node); keep node active.
        snapshot["gpu"] = normalize_gpu(
            {"available": False, "error": str(exc), "gpus": [], "total_count": 0}
        )

    try:
        instances = await _portal_request(node, "GET", "/api/v1/instances/")
        if isinstance(instances, list):
            snapshot["instances"] = [normalize_instance(item) for item in instances]
        else:
            snapshot["instances"] = []
    except PortalClientError as exc:
        snapshot["error"] = str(exc)
        snapshot["instances"] = []
    return snapshot


async def list_nodes(
    *,
    sync_registry: bool = True,
    workspace: Optional["Workspace"] = None,
) -> Dict[str, Any]:
    """List configured serving nodes with live portal state.

    Zero nodes → ``empty: true`` (first-class empty state for the demo VM).
    """
    configs = parse_serving_nodes(workspace=workspace)
    if not configs:
        return {
            "nodes": [],
            "empty": True,
            "message": "No serving node attached",
        }

    nodes = [await _fetch_node_snapshot(node) for node in configs]
    if sync_registry:
        sync_from_node_snapshots(nodes)
    return {
        "nodes": nodes,
        "empty": False,
        "message": None,
    }


async def create_instance(
    node_name: str,
    body: Dict[str, Any],
    *,
    workspace: Optional["Workspace"] = None,
) -> Any:
    node = get_node(node_name, workspace=workspace)
    if not node:
        raise PortalClientError(f"Unknown serving node {node_name!r}", status_code=404)
    result = await _portal_request(
        node,
        "POST",
        "/api/v1/instances/",
        json_body=body,
        timeout=_LIFECYCLE_TIMEOUT,
    )
    await list_nodes(sync_registry=True, workspace=workspace)
    return result


async def start_instance(
    node_name: str,
    instance_id: str,
    *,
    workspace: Optional["Workspace"] = None,
) -> Any:
    node = get_node(node_name, workspace=workspace)
    if not node:
        raise PortalClientError(f"Unknown serving node {node_name!r}", status_code=404)
    result = await _portal_request(
        node,
        "POST",
        f"/api/v1/instances/{instance_id}/start",
        timeout=_LIFECYCLE_TIMEOUT,
    )
    await list_nodes(sync_registry=True, workspace=workspace)
    return result


async def stop_instance(
    node_name: str,
    instance_id: str,
    *,
    workspace: Optional["Workspace"] = None,
) -> Any:
    node = get_node(node_name, workspace=workspace)
    if not node:
        raise PortalClientError(f"Unknown serving node {node_name!r}", status_code=404)
    result = await _portal_request(
        node,
        "POST",
        f"/api/v1/instances/{instance_id}/stop",
        timeout=_LIFECYCLE_TIMEOUT,
    )
    await list_nodes(sync_registry=True, workspace=workspace)
    return result


async def delete_instance(
    node_name: str,
    instance_id: str,
    *,
    workspace: Optional["Workspace"] = None,
) -> Any:
    node = get_node(node_name, workspace=workspace)
    if not node:
        raise PortalClientError(f"Unknown serving node {node_name!r}", status_code=404)
    result = await _portal_request(
        node,
        "DELETE",
        f"/api/v1/instances/{instance_id}",
        timeout=_LIFECYCLE_TIMEOUT,
    )
    await list_nodes(sync_registry=True, workspace=workspace)
    return result
