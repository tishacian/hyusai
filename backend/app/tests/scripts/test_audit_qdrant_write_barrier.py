from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "backend" / "scripts" / "audit_qdrant_write_barrier.py"
SHA = "a" * 40
DEPLOYMENT_ID = "deploy-qdrant-001"
ADMIN = "admin-" + "A" * 40
READ_ONLY = "readonly-" + "R" * 40


def _module():
    spec = importlib.util.spec_from_file_location("audit_qdrant_write_barrier", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inspect(
    name: str,
    *,
    env: dict[str, str],
    networks: tuple[str, ...] = ("agentium-net",),
    image: str = "agentium-backend:local",
    image_id: str | None = None,
) -> dict[str, Any]:
    container_id = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return {
        "Id": container_id,
        "Image": image_id or f"sha256:image-{name}",
        "State": {"Running": True},
        "Config": {
            "Image": image,
            "Hostname": container_id[:12],
            "Env": [f"{key}={value}" for key, value in env.items()],
        },
        "NetworkSettings": {
            "Networks": {network: {} for network in networks},
            "Ports": {},
        },
    }


def _fixtures(module):
    qdrant = _inspect(
        "qdrant",
        env={
            "QDRANT__SERVICE__API_KEY": ADMIN,
            "QDRANT__SERVICE__READ_ONLY_API_KEY": READ_ONLY,
        },
        image=module.DEFAULT_QDRANT_IMAGE,
        image_id="sha256:qdrant-image",
    )
    qdrant["NetworkSettings"]["Ports"] = {
        "6333/tcp": [{"HostIp": "127.0.0.1", "HostPort": "6333"}],
        "6334/tcp": [{"HostIp": "127.0.0.1", "HostPort": "6334"}],
    }
    backend = _inspect(
        "agentium-backend",
        env={"QDRANT_API_KEY": READ_ONLY},
    )
    worker = _inspect(
        "agentium-worker-cpu",
        env={"QDRANT_API_KEY": READ_ONLY},
        image="agentium-worker:local",
    )
    return {
        "qdrant": qdrant,
        "agentium-backend": backend,
        "agentium-worker-cpu": worker,
    }


def _http_fixture(module):
    calls: list[tuple[str, str, str | None]] = []
    guard = module._guard_collection_name(SHA, DEPLOYMENT_ID)

    def fake(base_url: str, method: str, path: str, *, api_key: str | None):
        calls.append((method, path, api_key))
        if path == "/cluster":
            assert api_key == ADMIN
            return 200, {"result": {"status": "disabled", "peers": {}}}
        if path == "/collections":
            if api_key is None:
                return 401, None
            return 200, {"result": {"collections": [{"name": "private-name"}]}}
        assert path == f"/collections/{guard}"
        if method == "DELETE":
            return 403, None
        return 404, None

    return fake, calls


def test_host_contract_proves_read_only_without_serializing_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    inspections = _fixtures(module)
    fake_http, calls = _http_fixture(module)
    monkeypatch.setattr(module, "_inspect_container", lambda name: deepcopy(inspections[name]))
    monkeypatch.setattr(module, "_http_status", fake_http)

    payload = module.build_host_contract(
        sha=SHA,
        deployment_id=DEPLOYMENT_ID,
        qdrant_container="qdrant",
        client_containers=["agentium-backend", "agentium-worker-cpu"],
        qdrant_url="http://127.0.0.1:6333",
        expected_image=module.DEFAULT_QDRANT_IMAGE,
        expected_network="agentium-net",
        running_names=list(inspections),
    )

    assert payload["result"] == "passed"
    assert payload["clients"]["all_read_only"] is True
    assert payload["clients"]["identities"]["agentium-backend"] == {
        "container_id": inspections["agentium-backend"]["Config"]["Hostname"],
        "docker_inspect_id": inspections["agentium-backend"]["Id"],
    }
    assert payload["clients"]["container_id_by_name"] == {
        "agentium-backend": inspections["agentium-backend"]["Config"]["Hostname"],
        "agentium-worker-cpu": inspections["agentium-worker-cpu"]["Config"]["Hostname"],
    }
    assert payload["qdrant"]["cluster_mode"] == "standalone"
    assert payload["probe"]["write_rejected"] is True
    assert payload["proof_ceiling"] == "runner_verified"
    serialized = json.dumps(payload)
    assert ADMIN not in serialized
    assert READ_ONLY not in serialized
    assert "private-name" not in serialized
    delete_calls = [call for call in calls if call[0] == "DELETE"]
    assert len(delete_calls) == 1
    assert "agentium_guard_absent_" in delete_calls[0][1]


def test_admin_ready_contract_proves_write_route_without_mutating_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    inspections = _fixtures(module)
    for name in ("agentium-backend", "agentium-worker-cpu"):
        inspections[name]["Config"]["Env"] = [f"QDRANT_API_KEY={ADMIN}"]
    fake_http, calls = _http_fixture(module)
    admin_deletes = 0

    def admin_http(base_url: str, method: str, path: str, *, api_key: str | None):
        nonlocal admin_deletes
        if method == "DELETE" and api_key == ADMIN:
            admin_deletes += 1
            return 404, None
        return fake_http(base_url, method, path, api_key=api_key)

    monkeypatch.setattr(module, "_inspect_container", lambda name: deepcopy(inspections[name]))
    monkeypatch.setattr(module, "_http_status", admin_http)

    payload = module.build_host_contract(
        sha=SHA,
        deployment_id=DEPLOYMENT_ID,
        qdrant_container="qdrant",
        client_containers=["agentium-backend", "agentium-worker-cpu"],
        qdrant_url="http://127.0.0.1:6333",
        expected_image=module.DEFAULT_QDRANT_IMAGE,
        expected_network="agentium-net",
        expected_client_access="admin",
        running_names=list(inspections),
    )

    assert payload["profile"] == "agentium-qdrant-admin-ready-v1"
    assert payload["clients"]["all_admin_ready"] is True
    assert payload["clients"]["all_read_only"] is False
    assert payload["probe"]["delete_status"] == 404
    assert payload["probe"]["write_route_authorized"] is True
    assert payload["probe"]["guard_remained_absent"] is True
    assert ADMIN not in json.dumps(payload)
    assert READ_ONLY not in json.dumps(payload)
    assert admin_deletes == 1
    assert [call for call in calls if call[0] == "DELETE"] == []


def test_admin_client_probe_reads_effective_key_only_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setenv("QDRANT_HOST", "agentium-qdrant")
    monkeypatch.setenv("QDRANT_PORT", "6333")
    monkeypatch.setenv("QDRANT_HTTPS", "false")
    monkeypatch.setenv("QDRANT_API_KEY", ADMIN)
    monkeypatch.setattr(module, "_client_container_id", lambda: "b" * 12)
    fake_http, _ = _http_fixture(module)

    def admin_http(base_url: str, method: str, path: str, *, api_key: str | None):
        if method == "DELETE" and api_key == ADMIN:
            return 404, None
        return fake_http(base_url, method, path, api_key=api_key)

    monkeypatch.setattr(module, "_http_status", admin_http)

    payload = module.build_client_probe(
        sha=SHA,
        deployment_id=DEPLOYMENT_ID,
        expected_access="admin",
    )

    assert payload["profile"] == "agentium-qdrant-admin-ready-client-v1"
    assert payload["client_identity"]["container_id"] == "b" * 12
    assert payload["probe"]["write_route_authorized"] is True
    assert payload["probe"]["guard_remained_absent"] is True
    assert ADMIN not in json.dumps(payload)


@pytest.mark.parametrize(
    ("admin", "read_only", "message"),
    [
        ("", READ_ONLY, "admin API key"),
        (ADMIN, "", "read-only API key"),
        (READ_ONLY, READ_ONLY, "not distinct"),
        ("tiny-secret-value", READ_ONLY, "admin API key"),
        (ADMIN, "tiny-secret-value", "read-only API key"),
    ],
)
def test_server_key_contract_fails_closed_without_exposing_values(
    admin: str,
    read_only: str,
    message: str,
) -> None:
    module = _module()
    with pytest.raises(module.QdrantBarrierError, match=message) as raised:
        module._assert_server_keys(
            {
                "QDRANT__SERVICE__API_KEY": admin,
                "QDRANT__SERVICE__READ_ONLY_API_KEY": read_only,
            }
        )
    error = str(raised.value)
    for value in (admin, read_only):
        if value:
            assert value not in error


def test_host_contract_rejects_public_qdrant_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    inspections = _fixtures(module)
    inspections["qdrant"]["NetworkSettings"]["Ports"]["6333/tcp"][0]["HostIp"] = "0.0.0.0"
    monkeypatch.setattr(module, "_inspect_container", lambda name: deepcopy(inspections[name]))
    fake_http, _ = _http_fixture(module)
    monkeypatch.setattr(module, "_http_status", fake_http)

    with pytest.raises(module.QdrantBarrierError, match="non-loopback"):
        module.build_host_contract(
            sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            qdrant_container="qdrant",
            client_containers=["agentium-backend"],
            qdrant_url="http://127.0.0.1:6333",
            expected_image=module.DEFAULT_QDRANT_IMAGE,
            expected_network="agentium-net",
            running_names=list(inspections),
        )


def test_host_contract_rejects_admin_key_in_candidate_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    inspections = _fixtures(module)
    inspections["agentium-backend"]["Config"]["Env"] = [f"QDRANT_API_KEY={ADMIN}"]
    monkeypatch.setattr(module, "_inspect_container", lambda name: deepcopy(inspections[name]))
    fake_http, _ = _http_fixture(module)
    monkeypatch.setattr(module, "_http_status", fake_http)

    with pytest.raises(module.QdrantBarrierError, match="does not use the read-only key"):
        module.build_host_contract(
            sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            qdrant_container="qdrant",
            client_containers=["agentium-backend"],
            qdrant_url="http://127.0.0.1:6333",
            expected_image=module.DEFAULT_QDRANT_IMAGE,
            expected_network="agentium-net",
            running_names=list(inspections),
        )


def test_host_contract_rejects_any_other_network_peer_with_write_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    inspections = _fixtures(module)
    inspections["unexpected"] = _inspect(
        "unexpected",
        env={"QDRANT_API_KEY": ADMIN},
    )
    monkeypatch.setattr(module, "_inspect_container", lambda name: deepcopy(inspections[name]))
    fake_http, _ = _http_fixture(module)
    monkeypatch.setattr(module, "_http_status", fake_http)

    with pytest.raises(module.QdrantBarrierError, match="non-read-only Qdrant credential"):
        module.build_host_contract(
            sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            qdrant_container="qdrant",
            client_containers=["agentium-backend", "agentium-worker-cpu"],
            qdrant_url="http://127.0.0.1:6333",
            expected_image=module.DEFAULT_QDRANT_IMAGE,
            expected_network="agentium-net",
            running_names=list(inspections),
        )


def test_host_contract_rejects_clustered_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    inspections = _fixtures(module)
    fake_http, _ = _http_fixture(module)

    def clustered(base_url: str, method: str, path: str, *, api_key: str | None):
        if path == "/cluster":
            return 200, {
                "result": {
                    "status": "enabled",
                    "peers": {"peer": {"uri": "hidden"}},
                }
            }
        return fake_http(base_url, method, path, api_key=api_key)

    monkeypatch.setattr(module, "_inspect_container", lambda name: deepcopy(inspections[name]))
    monkeypatch.setattr(module, "_http_status", clustered)

    with pytest.raises(module.QdrantBarrierError, match="standalone single-node"):
        module.build_host_contract(
            sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            qdrant_container="qdrant",
            client_containers=["agentium-backend", "agentium-worker-cpu"],
            qdrant_url="http://127.0.0.1:6333",
            expected_image=module.DEFAULT_QDRANT_IMAGE,
            expected_network="agentium-net",
            running_names=list(inspections),
        )


def test_negative_probe_aborts_if_guard_exists_or_delete_is_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    guard_path = f"/collections/{module._guard_collection_name(SHA, DEPLOYMENT_ID)}"

    def existing(_base: str, method: str, path: str, *, api_key: str | None):
        if path == "/collections":
            return (401, None) if api_key is None else (200, {"result": {"collections": []}})
        assert path == guard_path and method == "GET"
        return 200, {"result": {}}

    monkeypatch.setattr(module, "_http_status", existing)
    with pytest.raises(module.QdrantBarrierError, match="unexpectedly present"):
        module.probe_read_only_key(
            base_url="http://qdrant:6333",
            api_key=READ_ONLY,
            sha=SHA,
            deployment_id=DEPLOYMENT_ID,
        )

    calls = 0

    def writable(_base: str, method: str, path: str, *, api_key: str | None):
        nonlocal calls
        calls += 1
        if path == "/collections":
            return (401, None) if api_key is None else (200, {"result": {"collections": []}})
        if method == "DELETE":
            return 404, None
        return 404, None

    monkeypatch.setattr(module, "_http_status", writable)
    with pytest.raises(module.QdrantBarrierError, match="not read-only"):
        module.probe_read_only_key(
            base_url="http://qdrant:6333",
            api_key=READ_ONLY,
            sha=SHA,
            deployment_id=DEPLOYMENT_ID,
        )
    assert calls == 4


def test_client_probe_reads_key_only_from_environment_and_is_content_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    monkeypatch.setenv("QDRANT_HOST", "agentium-qdrant")
    monkeypatch.setenv("QDRANT_PORT", "6333")
    monkeypatch.setenv("QDRANT_HTTPS", "false")
    monkeypatch.setenv("QDRANT_API_KEY", READ_ONLY)
    monkeypatch.setattr(module, "_client_container_id", lambda: "c" * 12)
    fake_http, _ = _http_fixture(module)
    monkeypatch.setattr(module, "_http_status", fake_http)

    payload = module.build_client_probe(sha=SHA, deployment_id=DEPLOYMENT_ID)

    assert payload["result"] == "passed"
    assert payload["client_identity"]["container_id"] == "c" * 12
    assert payload["secrets_serialized"] is False
    assert READ_ONLY not in json.dumps(payload)
    option_strings = {
        option for action in module._parser()._actions for option in action.option_strings
    }
    assert not any("key" in option.lower() for option in option_strings)


def test_atomic_output_is_private_and_fsyncs_file_and_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _module()
    output = tmp_path / "barrier.json"
    real_fsync = os.fsync
    synced_modes: list[int] = []

    def recording_fsync(descriptor: int) -> None:
        synced_modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", recording_fsync)
    module._write_json({"result": "passed"}, str(output))
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text(encoding="utf-8"))["result"] == "passed"
    assert any(stat.S_ISREG(mode) for mode in synced_modes)
    assert any(stat.S_ISDIR(mode) for mode in synced_modes)


def test_host_contract_rejects_runtime_identity_not_bound_to_docker_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    inspections = _fixtures(module)
    inspections["agentium-backend"]["Config"]["Hostname"] = "f" * 12
    monkeypatch.setattr(module, "_inspect_container", lambda name: deepcopy(inspections[name]))
    fake_http, _ = _http_fixture(module)
    monkeypatch.setattr(module, "_http_status", fake_http)

    with pytest.raises(module.QdrantBarrierError, match="runtime identity"):
        module.build_host_contract(
            sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            qdrant_container="qdrant",
            client_containers=["agentium-backend"],
            qdrant_url="http://127.0.0.1:6333",
            expected_image=module.DEFAULT_QDRANT_IMAGE,
            expected_network="agentium-net",
            running_names=list(inspections),
        )


@pytest.mark.parametrize(
    "value",
    [
        "http://admin:secret@127.0.0.1:6333",
        "http://qdrant:6333",
        "http://127.0.0.1:6333/collections",
        "http://127.0.0.1:6333?api_key=secret",
    ],
)
def test_host_url_rejects_credentials_and_non_loopback_targets(value: str) -> None:
    module = _module()
    with pytest.raises(module.QdrantBarrierError, match="credential-free loopback"):
        module._validate_host_qdrant_url(value)
