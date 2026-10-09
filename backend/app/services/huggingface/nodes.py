"""Versioned artifact protocol for external omnirag-llm-portal preparation agents.

The GPU service is a separate repository. Older nodes deliberately fail preflight;
none of these calls downgrade to the legacy, unverified instance-creation API.
Authorization and object signing are supplied by the registry/API transaction.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, urlsplit

from app.services.huggingface.errors import HFError

ARTIFACT_API_VERSION = 1
MAX_SIGNED_URL_SECONDS = 300
DEPLOYMENT_STATES = frozenset(
    {"preparing", "verifying", "starting", "ready", "failed", "draining", "stopped"}
)
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")


def _refused(message: str) -> HFError:
    return HFError("HF_NODE_INCOMPATIBLE", message, 409)


async def _call(callback: Callable, *args: Any) -> Any:
    value = callback(*args)
    return await value if inspect.isawaitable(value) else value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _deployment_id(value: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise _refused("Invalid deployment identifier")
    return value


def validate_node_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("version", manifest.get("manifest_version")) != 2:
        raise _refused("The node requires an immutable manifest v2")
    if manifest.get("kind") != "model" or manifest.get("format") not in {"safetensors", "gguf"}:
        raise _refused("Only safetensors and GGUF model artifacts can be deployed")
    if not manifest.get("artifact_id") or not re.fullmatch(
        r"[a-f0-9]{40}", str(manifest.get("revision", ""))
    ):
        raise _refused("Artifact identity and pinned revision are required")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or not files:
        raise _refused("Artifact manifest has no files")
    total = 0
    for path, item in files.items():
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or "\\" in path
            or any(p in {"", ".", ".."} for p in path.split("/"))
            or any(ord(c) < 32 for c in path)
            or not isinstance(item, Mapping)
            or not _SHA256.fullmatch(str(item.get("sha256", "")))
            or type(item.get("size_bytes")) is not int
            or item["size_bytes"] < 0
        ):
            raise _refused("Invalid manifest file or checksum")
        total += item["size_bytes"]
    if total != manifest.get("total_bytes"):
        raise _refused("Manifest total differs from its exact file selection")


def preflight(
    capabilities: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    architecture: str,
    context_length: int,
    required_memory_bytes: int,
) -> dict[str, Any]:
    """Refuse unsupported protocol, runtime, architecture or hardware before transfer.

    Memory must include weights and the requested KV cache/runtime overhead. The node
    must repeat its own admission check atomically when accepting the deployment.
    """
    validate_node_manifest(manifest)
    if capabilities.get("artifact_api_version") != ARTIFACT_API_VERSION:
        raise _refused("Serving node must implement artifact API version 1")
    versions = capabilities.get("manifest_versions")
    if not isinstance(versions, list) or 2 not in versions:
        raise _refused("Serving node cannot verify artifact manifest v2")
    if not all(
        capabilities.get(key) is True
        for key in (
            "sha256_verification",
            "offline_inference",
            "read_only_weights",
            "idempotent_deployments",
        )
    ):
        raise _refused(
            "Serving node must verify all files and run inference offline with read-only weights"
        )
    states = capabilities.get("deployment_states")
    if (
        not isinstance(states, list)
        or not all(isinstance(state, str) for state in states)
        or not DEPLOYMENT_STATES.issubset(set(states))
    ):
        raise _refused("Serving node lacks artifact progress or drain states")
    engine = "vllm" if manifest["format"] == "safetensors" else "llamacpp"
    runtimes = capabilities.get("runtimes")
    runtime = runtimes.get(engine) if isinstance(runtimes, Mapping) else None
    if not isinstance(runtime, Mapping) or not runtime.get("version"):
        raise _refused(f"Serving node does not advertise a versioned {engine} runtime")
    formats, architectures = runtime.get("formats"), runtime.get("architectures")
    if (
        not isinstance(formats, list)
        or not isinstance(architectures, list)
        or manifest["format"] not in formats
        or architecture not in architectures
    ):
        raise _refused("Serving node does not support this format and architecture")
    maximum_context = runtime.get("max_context_length")
    available_memory = runtime.get("available_memory_bytes")
    if type(maximum_context) is not int or type(available_memory) is not int:
        raise _refused("Serving node did not declare numeric runtime capacities")
    if type(context_length) is not int or context_length <= 0 or context_length > maximum_context:
        raise _refused("Requested context exceeds the declared runtime capacity")
    if (
        type(required_memory_bytes) is not int
        or required_memory_bytes < int(manifest["total_bytes"])
        or required_memory_bytes > available_memory
    ):
        raise _refused("Requested weights and context exceed the declared runtime memory capacity")
    maximum_ttl = capabilities.get("max_signed_url_seconds")
    if type(maximum_ttl) is not int or not 1 <= maximum_ttl <= MAX_SIGNED_URL_SECONDS:
        raise _refused("Serving node must support URL expiry of at most 300 seconds")
    return {"engine": engine, "runtime_version": str(runtime["version"]), "url_ttl": maximum_ttl}


async def _node(node_name: str, workspace: Any):
    from app.services.model_plane import serving_nodes

    node = serving_nodes.get_node(node_name, workspace=workspace)
    if node is None:
        raise HFError("HF_NODE_INCOMPATIBLE", "Unknown serving node", 404)
    # Artifact transfer must not occur through an unauthenticated control plane.
    if not node.token:
        raise _refused("Artifact deployments require an authenticated serving node")
    return node


async def get_capabilities(node_name: str, *, workspace: Any = None) -> dict[str, Any]:
    from app.services.model_plane import serving_nodes

    node = await _node(node_name, workspace)
    try:
        result = await serving_nodes._portal_request(node, "GET", "/api/v1/artifacts/capabilities")
    except serving_nodes.PortalClientError as exc:
        if exc.status_code in {404, 405}:
            raise _refused("This serving node has not implemented artifact API version 1") from exc
        raise
    if not isinstance(result, dict):
        raise _refused("Serving node returned invalid artifact capabilities")
    return result


def _public_hub_source(manifest: Mapping[str, Any]) -> dict[str, Any]:
    endpoint = str(manifest.get("hub_endpoint", "")).rstrip("/")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise _refused("The manifest must contain a credential-free HTTPS Hub endpoint")
    repo = str(manifest.get("repo_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise _refused("Invalid Hub repository identifier")
    return {
        "type": "huggingface",
        "hub_endpoint": endpoint,
        "repo_id": repo,
        "revision": manifest["revision"],
        "files": {
            path: f"{endpoint}/{repo}/resolve/{manifest['revision']}/{quote(path, safe='/')}"
            for path in manifest["files"]
        },
        # The preparation agent reports source_unavailable and waits for an
        # authorized refresh; it must not follow a mobile ref or obtain a token.
        "fallback": "authorized_minio_refresh",
        "send_hub_credentials": False,
    }


async def signed_sources(
    manifest: Mapping[str, Any],
    *,
    authorize: Callable,
    presign: Callable,
    ttl_seconds: int = MAX_SIGNED_URL_SECONDS,
) -> dict[str, Any]:
    validate_node_manifest(manifest)
    if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_SIGNED_URL_SECONDS:
        raise _refused("Signed URL lifetime must be between 1 and 300 seconds")
    await _call(authorize, str(manifest["artifact_id"]))
    urls = {}
    for path in manifest["files"]:
        # Repeat before every signature, so a long batch does not mint URLs
        # after a concurrent revocation becomes visible.
        await _call(authorize, str(manifest["artifact_id"]))
        url = await _call(presign, path, ttl_seconds)
        parsed = urlsplit(str(url))
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise _refused("Object store returned an invalid signed URL")
        urls[path] = url
    return {"type": "minio", "expires_in_seconds": ttl_seconds, "files": urls}


async def deploy_artifact(
    node_name: str,
    manifest: Mapping[str, Any],
    *,
    workspace: Any,
    architecture: str,
    context_length: int,
    required_memory_bytes: int,
    authorize: Callable,
    presign: Callable,
    deployment_id: str | None = None,
    hub_available: bool = True,
) -> dict[str, Any]:
    from app.services.model_plane import serving_nodes

    await _call(authorize, str(manifest.get("artifact_id", "")))
    node = await _node(node_name, workspace)
    capabilities = await get_capabilities(node_name, workspace=workspace)
    runtime = preflight(
        capabilities,
        manifest,
        architecture=architecture,
        context_length=context_length,
        required_memory_bytes=required_memory_bytes,
    )
    workspace_id = str(getattr(workspace, "id", workspace))
    fingerprint = {
        "workspace_id": workspace_id,
        "node": node_name,
        "manifest_sha256": hashlib.sha256(_canonical(dict(manifest))).hexdigest(),
        "architecture": architecture,
        "context_length": context_length,
        "required_memory_bytes": required_memory_bytes,
        "engine": runtime["engine"],
        "runtime_version": runtime["runtime_version"],
    }
    deployment_id = _deployment_id(
        deployment_id or hashlib.sha256(_canonical(fingerprint)).hexdigest()
    )
    use_minio = (
        bool(manifest.get("private") or manifest.get("gated"))
        or capabilities.get("hub_network_access") is not True
        or not hub_available
    )
    source = (
        await signed_sources(
            manifest, authorize=authorize, presign=presign, ttl_seconds=runtime["url_ttl"]
        )
        if use_minio
        else _public_hub_source(manifest)
    )
    payload = {
        "artifact_api_version": ARTIFACT_API_VERSION,
        "deployment_id": deployment_id,
        **fingerprint,
        "artifact_id": str(manifest["artifact_id"]),
        "manifest": dict(manifest),
        "source": source,
        "runtime": {
            "engine": runtime["engine"],
            "version": runtime["runtime_version"],
            "environment": {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
            "weights_read_only": True,
            "network_access": False,
        },
        "provenance": {
            key: manifest.get(key)
            for key in ("artifact_id", "repo_id", "revision", "variant", "selection_digest")
        }
        | {"runtime_version": runtime["runtime_version"]},
    }
    await _call(authorize, str(manifest["artifact_id"]))
    result = await serving_nodes._portal_request(
        node,
        "PUT",
        f"/api/v1/artifacts/deployments/{deployment_id}",
        json_body=payload,
        timeout=serving_nodes._LIFECYCLE_TIMEOUT,
    )
    return _validate_state(result, deployment_id, str(manifest["artifact_id"]))


def _validate_state(result: Any, deployment_id: str, artifact_id: str) -> dict[str, Any]:
    if (
        not isinstance(result, dict)
        or result.get("deployment_id") != deployment_id
        or result.get("artifact_id") != artifact_id
        or result.get("state") not in DEPLOYMENT_STATES
    ):
        raise _refused("Serving node returned an invalid artifact deployment state")
    return result


async def deployment_status(
    node_name: str,
    deployment_id: str,
    *,
    workspace: Any,
    artifact_id: str,
    authorize_control: Callable,
) -> dict[str, Any]:
    from app.services.model_plane import serving_nodes

    # Revoked deployments must remain observable while they drain. Control
    # checks verify workspace ownership/role, rather than an active grant.
    await _call(authorize_control, artifact_id, deployment_id)
    node = await _node(node_name, workspace)
    result = await serving_nodes._portal_request(
        node,
        "GET",
        f"/api/v1/artifacts/deployments/{_deployment_id(deployment_id)}",
    )
    return _validate_state(result, deployment_id, artifact_id)


async def stop_deployment(
    node_name: str,
    deployment_id: str,
    *,
    workspace: Any,
    artifact_id: str,
    authorize_control: Callable,
) -> dict[str, Any]:
    """Control authorization must allow draining a revoked artifact's own usage."""
    from app.services.model_plane import serving_nodes

    await _call(authorize_control, artifact_id, deployment_id)
    node = await _node(node_name, workspace)
    result = await serving_nodes._portal_request(
        node,
        "POST",
        f"/api/v1/artifacts/deployments/{_deployment_id(deployment_id)}/stop",
        json_body={"drain": True},
        timeout=serving_nodes._LIFECYCLE_TIMEOUT,
    )
    return _validate_state(result, deployment_id, artifact_id)


async def refresh_deployment_urls(
    node_name: str,
    deployment_id: str,
    manifest: Mapping[str, Any],
    *,
    workspace: Any,
    authorize: Callable,
    authorize_control: Callable,
    presign: Callable,
) -> dict[str, Any]:
    from app.services.model_plane import serving_nodes

    await _call(authorize_control, str(manifest["artifact_id"]), deployment_id)
    node = await _node(node_name, workspace)
    capabilities = await get_capabilities(node_name, workspace=workspace)
    ttl = capabilities.get("max_signed_url_seconds")
    if type(ttl) is not int or not 1 <= ttl <= MAX_SIGNED_URL_SECONDS:
        raise _refused("Serving node must support URL expiry of at most 300 seconds")
    source = await signed_sources(manifest, authorize=authorize, presign=presign, ttl_seconds=ttl)
    result = await serving_nodes._portal_request(
        node,
        "PUT",
        f"/api/v1/artifacts/deployments/{_deployment_id(deployment_id)}/sources",
        json_body={"artifact_id": str(manifest["artifact_id"]), "source": source},
    )
    return _validate_state(result, deployment_id, str(manifest["artifact_id"]))


async def delete_deployment_copy(
    node_name: str,
    deployment_id: str,
    *,
    workspace: Any,
    artifact_id: str,
    authorize_control: Callable,
) -> dict[str, Any]:
    """Only a node's explicit confirmation is evidence of physical deletion."""
    from app.services.model_plane import serving_nodes

    await _call(authorize_control, artifact_id, deployment_id)
    node = await _node(node_name, workspace)
    result = await serving_nodes._portal_request(
        node,
        "DELETE",
        f"/api/v1/artifacts/deployments/{_deployment_id(deployment_id)}",
        timeout=serving_nodes._LIFECYCLE_TIMEOUT,
    )
    result = _validate_state(result, deployment_id, artifact_id)
    if result.get("state") != "stopped" or result.get("copies_deleted") is not True:
        raise HFError(
            "HF_PURGE_BLOCKED", "The serving node has not confirmed physical deletion", 409
        )
    return result
