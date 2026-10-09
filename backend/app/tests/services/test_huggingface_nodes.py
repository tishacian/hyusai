"""Artifact node protocol never sends unverified weights to legacy nodes."""

from __future__ import annotations

import copy
import hashlib
from types import SimpleNamespace

import pytest

from app.services.huggingface import nodes
from app.services.huggingface.errors import HFError
from app.services.model_plane import registration, serving_nodes


@pytest.fixture
def manifest():
    return {
        "version": 2,
        "artifact_id": "artifact-a",
        "kind": "model",
        "format": "gguf",
        "hub_endpoint": "https://huggingface.co",
        "repo_id": "owner/model",
        "revision": "a" * 40,
        "variant": "q4",
        "selection_digest": "b" * 64,
        "private": False,
        "gated": False,
        "total_bytes": 4,
        "files": {"model.gguf": {"size_bytes": 4, "sha256": hashlib.sha256(b"test").hexdigest()}},
    }


@pytest.fixture
def capabilities():
    return {
        "artifact_api_version": 1,
        "manifest_versions": [2],
        "sha256_verification": True,
        "offline_inference": True,
        "read_only_weights": True,
        "idempotent_deployments": True,
        "deployment_states": list(nodes.DEPLOYMENT_STATES),
        "hub_network_access": True,
        "max_signed_url_seconds": 180,
        "runtimes": {
            "llamacpp": {
                "version": "b1",
                "formats": ["gguf"],
                "architectures": ["llama"],
                "max_context_length": 4096,
                "available_memory_bytes": 1024,
            }
        },
    }


@pytest.fixture
def portal(monkeypatch, capabilities):
    requests = []
    monkeypatch.setattr(
        serving_nodes,
        "get_node",
        lambda *a, **kw: serving_nodes.ServingNodeConfig("gpu", "https://gpu", "control-secret"),
    )

    async def request(node, method, path, *, json_body=None, **kw):
        requests.append((method, path, json_body))
        if path.endswith("/capabilities"):
            return capabilities
        identity = path.split("/deployments/")[1].split("/")[0]
        return {"deployment_id": identity, "artifact_id": "artifact-a", "state": "preparing"}

    monkeypatch.setattr(serving_nodes, "_portal_request", request)
    return requests


async def deploy(manifest, **kwargs):
    return await nodes.deploy_artifact(
        "gpu",
        manifest,
        workspace=SimpleNamespace(id="workspace-a"),
        architecture="llama",
        context_length=2048,
        required_memory_bytes=64,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_public_exact_revision_no_signed_urls_and_stable_request(manifest, portal):
    def no_presign(*_):
        raise AssertionError("Public Hub source must not request a signed URL")

    first = await deploy(manifest, authorize=lambda _: None, presign=no_presign)
    second = await deploy(manifest, authorize=lambda _: None, presign=no_presign)
    assert first == second
    request = portal[-1][2]
    assert request["source"]["type"] == "huggingface"
    assert request["source"]["files"] == {
        "model.gguf": f"https://huggingface.co/owner/model/resolve/{'a' * 40}/model.gguf"
    }
    assert request["runtime"]["environment"]["HF_HUB_OFFLINE"] == "1"
    assert request["runtime"]["network_access"] is False
    assert request["manifest"] == manifest
    assert "control-secret" not in str(request)
    assert request["provenance"]["variant"] == "q4"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "private,gated,connected,available",
    [
        (True, False, True, True),
        (False, True, True, True),
        (False, False, False, True),
        (False, False, True, False),
    ],
)
async def test_restricted_isolated_or_removed_revision_uses_minio(
    manifest, capabilities, portal, private, gated, connected, available
):
    manifest.update(private=private, gated=gated)
    capabilities["hub_network_access"] = connected
    signs = []

    def presign(path, ttl):
        signs.append((path, ttl))
        return "https://minio/object?signature=short"

    await deploy(manifest, authorize=lambda _: None, presign=presign, hub_available=available)
    assert portal[-1][2]["source"]["type"] == "minio"
    assert signs == [("model.gguf", 180)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["version", "memory", "architecture", "verification", "context", "url_ttl"]
)
async def test_preflight_refuses_before_transfer(manifest, capabilities, portal, change):
    if change == "version":
        capabilities["artifact_api_version"] = 0
    elif change == "memory":
        capabilities["runtimes"]["llamacpp"]["available_memory_bytes"] = 3
    elif change == "architecture":
        capabilities["runtimes"]["llamacpp"]["architectures"] = ["unsupported"]
    elif change == "verification":
        capabilities["sha256_verification"] = False
    elif change == "context":
        capabilities["runtimes"]["llamacpp"]["max_context_length"] = 8
    else:
        capabilities["max_signed_url_seconds"] = 3600
    with pytest.raises(HFError) as error:
        await deploy(
            manifest,
            authorize=lambda _: None,
            presign=lambda *_: pytest.fail("No URLs before preflight"),
        )
    assert error.value.code == "HF_NODE_INCOMPATIBLE"
    assert all(method == "GET" for method, _, _ in portal)


@pytest.mark.asyncio
async def test_legacy_node_returns_named_incompatible_error(manifest, monkeypatch, portal):
    async def unsupported(*a, **kw):
        raise serving_nodes.PortalClientError("missing", status_code=404)

    monkeypatch.setattr(serving_nodes, "_portal_request", unsupported)
    with pytest.raises(HFError, match="not implemented artifact API"):
        await deploy(manifest, authorize=lambda _: None, presign=lambda *_: None)


@pytest.mark.asyncio
async def test_refresh_rechecks_grant_before_any_url(manifest, portal):
    def revoked(_):
        raise HFError("HF_ACCESS_REVOKED", "revoked", 403)

    with pytest.raises(HFError) as error:
        await nodes.refresh_deployment_urls(
            "gpu",
            "dep",
            manifest,
            workspace=SimpleNamespace(id="workspace-a"),
            authorize=revoked,
            authorize_control=lambda *_: None,
            presign=lambda *_: pytest.fail("Revoked grants cannot sign URLs"),
        )
    assert error.value.code == "HF_ACCESS_REVOKED"
    assert not any(path.endswith("/sources") for _, path, _ in portal)


@pytest.mark.asyncio
async def test_stop_and_status_need_control_ownership_not_active_grant(portal):
    checks = []
    await nodes.stop_deployment(
        "gpu",
        "dep",
        workspace=SimpleNamespace(id="workspace-a"),
        artifact_id="artifact-a",
        authorize_control=lambda *args: checks.append(args),
    )
    await nodes.deployment_status(
        "gpu",
        "dep",
        workspace=SimpleNamespace(id="workspace-a"),
        artifact_id="artifact-a",
        authorize_control=lambda *args: checks.append(args),
    )
    assert checks == [("artifact-a", "dep"), ("artifact-a", "dep")]
    assert portal[0][2] == {"drain": True}


def test_registration_keeps_immutable_artifact_provenance(manifest):
    instance = {
        "id": "instance",
        "provider": "llamacpp",
        "model": "q4",
        "port": 9000,
        "status": "running",
        "artifact_id": "artifact-a",
        "workspace_id": "workspace-a",
        "deployment_id": "dep-a",
        "provenance": {**manifest, "runtime_version": "b1"},
    }
    snapshot = {
        "name": "gpu",
        "base_url": "https://gpu",
        "status": "active",
        "instances": [instance],
    }
    rows = registration.sync_from_node_snapshots([snapshot])
    assert rows[0]["artifact_id"] == "artifact-a"
    assert rows[0]["revision"] == "a" * 40
    assert rows[0]["runtime_version"] == "b1"
    assert rows[0]["openai_base_url"] == "https://gpu/api/v1/artifacts/deployments/dep-a/v1"
    assert rows[0]["api_key"] == "local"
    for field, value in (("workspace_id", None), ("deployment_id", None), ("deployment_id", "../x")):
        bad = copy.deepcopy(snapshot)
        bad["instances"][0][field] = value
        assert registration.sync_from_node_snapshots([bad]) == []
