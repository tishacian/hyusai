from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import stat
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "backend" / "scripts" / "audit_sftp_deploy_boundary.py"
SHA = "a" * 40
LIVE_SHA = "1" * 40
SFTP_SHA = "b" * 40
DEPLOYMENT_ID = "deploy-sftp-001"
SFTP_ID = "b" * 64
CLIENT_ID = "c" * 64
SFTP_IMAGE = "sha256:" + "d" * 64
CLIENT_IMAGE = "sha256:" + "e" * 64
FINGERPRINT = "SHA256:" + "A" * 43
EXPECTED_SECURE_SOURCE = "/dev/mapper/agentium-secure-deposit"
PREVIOUS_SHA = SFTP_SHA
SFTP_STARTED_AT = "2026-07-23T08:00:00.123456789Z"
READY_AT = "2026-07-23T09:00:00Z"
RELEASE_A_SECURE_SOURCE = "/dev/sdc"


def _revision_for_image(image_id: str) -> str:
    return SFTP_SHA if image_id == SFTP_IMAGE else SHA


def _module():
    spec = importlib.util.spec_from_file_location(
        "audit_sftp_deploy_boundary", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _container(
    name: str,
    *,
    container_id: str,
    image_id: str,
    running: bool,
    healthy: bool = True,
    restart: str = "no",
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "Running": running,
        "Paused": False,
        "Restarting": False,
        "Dead": False,
        "Pid": 1234 if running else 0,
        "StartedAt": SFTP_STARTED_AT,
    }
    if running:
        state["Health"] = {"Status": "healthy" if healthy else "unhealthy"}
    return {
        "Id": container_id,
        "Image": image_id,
        "Name": f"/{name}",
        "State": state,
        "Config": {
            "Hostname": container_id[:12],
            "Env": [
                "SECURE_DEPOSIT_SFTP_HOST_KEY_PATH=/data/secure_deposit/sftp_host_key"
            ],
        },
        "HostConfig": {
            "RestartPolicy": {"Name": restart, "MaximumRetryCount": 0},
            "PortBindings": {
                "2222/tcp": [{"HostIp": "127.0.0.1", "HostPort": "2223"}]
            },
        },
        "NetworkSettings": {"Networks": {"agentium-net": {}}},
        "Mounts": [
            {
                "Type": "bind",
                "Source": "/hidden/secure-deposit",
                "Destination": "/data/secure_deposit",
                "RW": True,
            }
        ],
    }


def _auth_inventory(*rows: dict[str, Any]) -> dict[str, Any]:
    module = _module()
    return module._auth_inventory_from_rows(rows)


def _protocol_payload() -> dict[str, Any]:
    return {
        "ssh_v2_identification_validated": True,
        "key_exchange_completed": True,
        "host_key_algorithm": "ssh-ed25519",
        "host_key_fingerprint": FINGERPRINT,
        "host_key_stable": True,
        "none_auth_rejected": True,
        "auth_methods": ["keyboard-interactive", "password"],
        "password_offered": True,
        "password_submitted": False,
        "sftp_subsystem_requested": False,
        "directory_enumeration_requested": False,
    }


def _audit_comparison() -> dict[str, Any]:
    empty = _auth_inventory()
    module = _module()
    return module._compare_auth_inventory(empty, empty)


def _docker_protocol_proof() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "kind": "agentium_sftp_deploy_boundary",
        "profile": "agentium-sftp-docker-protocol-v2",
        "sha": SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "result": "passed",
        "sftp_identity": {
            "container_id": SFTP_ID,
            "image_id": SFTP_IMAGE,
            "revision": SFTP_SHA,
            "healthy": True,
            "restart_policy_disabled": True,
        },
        "client_identity": {
            "container_id": CLIENT_ID,
            "image_id": CLIENT_IMAGE,
            "revision": SHA,
        },
        "revision_binding": {
            "candidate_sha": SHA,
            "client_sha": SHA,
            "sftp_sha": SFTP_SHA,
            "revisions_distinct": True,
            "client_image_revision_verified": True,
            "sftp_image_revision_verified": True,
        },
        "internal_network_shared": True,
        "closed_proof_sha256": "1" * 64,
        "closed_boundary_binding": {
            "same_candidate_sha": True,
            "same_sftp_sha": True,
            "server_client_sha_distinct": True,
            "same_deployment_id": True,
            "same_container_id": True,
            "same_image_id": True,
            "same_host_key_fingerprint": True,
        },
        "protocol": _protocol_payload(),
        "authentication_audit": _audit_comparison(),
        "credentials_used": False,
        "content_serialized": False,
        "raw_identification_serialized": False,
    }


def _rollback_protocol_client_proof() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "agentium_sftp_protocol_client",
        "profile": "agentium-sftp-none-auth-client-v1",
        "sha": PREVIOUS_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "result": "passed",
        "client_identity": {"container_id": CLIENT_ID[:12]},
        "protocol": _protocol_payload(),
        "authentication_audit": _audit_comparison(),
        "credentials_used": False,
        "content_serialized": False,
        "raw_identification_serialized": False,
    }


def _closed_proof() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "kind": "agentium_sftp_deploy_boundary",
        "profile": "agentium-sftp-closed-boundary-v2",
        "sha": SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "result": "passed",
        "container": {
            "container_id": SFTP_ID,
            "image_id": SFTP_IMAGE,
            "revision": SFTP_SHA,
            "running": False,
            "paused": False,
            "process_count": 0,
            "secure_deposit_open_fd_count": 0,
            "restart_policy_disabled": True,
        },
        "legacy_service": {"active": False, "enabled": False},
        "ingress_gate": {
            "ipv4_input": True,
            "ipv4_docker_user": True,
            "ipv6_input": True,
            "ipv6_docker_user": True,
        },
        "network": {
            "listener_count": 0,
            "established_connection_count": 0,
            "ipv4_connect_rejected": True,
            "ipv6_connect_rejected": True,
        },
        "secure_deposit": {
            "source_matches_expected": True,
            "autonomous_mountpoint": True,
            "read_only": True,
            "device_id": 123,
        },
        "host_key": {
            "present": True,
            "nonempty": True,
            "regular_file": True,
            "symlink": False,
            "algorithm": "ssh-ed25519",
            "fingerprint": FINGERPRINT,
        },
        "revision_binding": {
            "candidate_sha": SHA,
            "client_sha": SHA,
            "sftp_sha": SFTP_SHA,
            "revisions_distinct": True,
            "client_image_revision_verified": False,
            "sftp_image_revision_verified": True,
        },
        "credentials_used": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
    }


def _validation_proof() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "safe_deployment_validation",
        "deployment_id": DEPLOYMENT_ID,
        "candidate_sha": SHA,
        "database_revision": "076_safe_deploy",
        "deployment_dir": "/private/deployment",
        "generated_at": "2026-07-22T12:00:00Z",
        "max_age_seconds": 3600,
        "result": "passed",
        "checks": {
            "sha_bound": True,
            "storage_preserved": True,
            "sftp_closed_boundary": True,
        },
        "runtime_env": {"result": "passed"},
        "evidence": {
            "showcase": {"outcome": "passed"},
            "sftp_closed_after": {"outcome": "passed", "sha256": "1" * 64},
        },
        "digests": {"storage": "2" * 64},
    }


def _install_validation_ready_mocks(
    module: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, Any]:
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    monkeypatch.setattr(module, "_docker_inspect", lambda _name: deepcopy(sftp))
    monkeypatch.setattr(module, "_image_revision", lambda _image_id: SFTP_SHA)
    monkeypatch.setattr(module, "_published_sftp_port", lambda _payload: 2223)
    monkeypatch.setattr(
        module,
        "_gate_contract",
        lambda **_kwargs: {
            "ipv4_input": True,
            "ipv4_docker_user": True,
            "ipv6_input": True,
            "ipv6_docker_user": True,
        },
    )
    monkeypatch.setattr(module, "_listener_count", lambda _port: 1)
    monkeypatch.setattr(module, "_established_connection_count", lambda _port: 0)
    monkeypatch.setattr(
        module,
        "_secure_mount_contract",
        lambda *_args, expected_source, expected_mode="ro": (
            {
                "source_matches_expected": expected_source
                == RELEASE_A_SECURE_SOURCE,
                "autonomous_mountpoint": True,
                "read_only": expected_mode == "ro",
                "device_id": 123,
            },
            tmp_path,
        ),
    )
    monkeypatch.setattr(module, "_secure_namespace_read_only", lambda: True)
    monkeypatch.setattr(
        module, "_secure_namespace_mode", lambda mode, **_kwargs: mode
    )
    monkeypatch.setattr(module, "_host_key_path", lambda *_args: tmp_path / "hidden")
    monkeypatch.setattr(
        module,
        "_host_key_fingerprint",
        lambda _path: {
            "present": True,
            "nonempty": True,
            "regular_file": True,
            "symlink": False,
            "algorithm": "ssh-ed25519",
            "fingerprint": FINGERPRINT,
        },
    )
    monkeypatch.setattr(
        module,
        "_read_published_ssh_identification",
        lambda _port: {
            "ssh_v2_identification_validated": True,
            "raw_identification_serialized": False,
            "connection_closed_before_authentication": True,
        },
    )
    monkeypatch.setattr(module, "_runtime_hostname_sha256", lambda: "f" * 64)
    monkeypatch.setattr(module, "_utc_now", lambda: READY_AT)
    return sftp


def _write_runtime_ready_receipt(module: Any, path: Path) -> dict[str, Any]:
    payload = module.build_validation_ready_contract(
        live_sha=LIVE_SHA,
        release_a_sha=SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        expected_secure_source=RELEASE_A_SECURE_SOURCE,
    )
    module._write_canonical_json(payload, str(path))
    return payload


def test_protocol_evidence_uses_host_key_and_none_auth_methods_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    calls: list[tuple[str, dict[str, Any]]] = []

    class Key:
        def get_algorithm(self) -> str:
            return "ssh-ed25519"

        def get_fingerprint(self, algorithm: str) -> str:
            assert algorithm == "sha256"
            return FINGERPRINT

    async def get_server_host_key(**kwargs: Any) -> Key:
        calls.append(("host_key", kwargs))
        return Key()

    async def get_server_auth_methods(**kwargs: Any) -> list[str]:
        calls.append(("auth_methods", kwargs))
        return ["keyboard-interactive", "password"]

    fake_asyncssh = SimpleNamespace(
        get_server_host_key=get_server_host_key,
        get_server_auth_methods=get_server_auth_methods,
    )
    monkeypatch.setitem(sys.modules, "asyncssh", fake_asyncssh)

    evidence = asyncio.run(module._protocol_evidence(timeout=1))

    assert evidence == _protocol_payload()
    assert [name for name, _ in calls] == ["host_key", "auth_methods", "host_key"]
    for _name, kwargs in calls:
        assert "password" not in kwargs
        assert "client_keys" not in kwargs
        assert kwargs["server_host_key_algs"] == ["ssh-ed25519"]
        assert kwargs["config"] is None
    auth_kwargs = calls[1][1]
    assert auth_kwargs["username"] == module._AUTH_METHOD_PROBE_PRINCIPAL
    assert not any("sftp" in name.lower() for name, _ in calls)


@pytest.mark.parametrize(
    "methods",
    [
        [],
        ["publickey"],
        ["password", "publickey"],
        ["keyboard-interactive"],
        ["password", "password"],
    ],
)
def test_protocol_evidence_rejects_any_method_contract_other_than_password(
    monkeypatch: pytest.MonkeyPatch, methods: list[str]
) -> None:
    module = _module()

    class Key:
        def get_algorithm(self) -> str:
            return "ssh-ed25519"

        def get_fingerprint(self, _algorithm: str) -> str:
            return FINGERPRINT

    async def get_server_host_key(**_kwargs: Any) -> Key:
        return Key()

    async def get_server_auth_methods(**_kwargs: Any) -> list[str]:
        return methods

    monkeypatch.setitem(
        sys.modules,
        "asyncssh",
        SimpleNamespace(
            get_server_host_key=get_server_host_key,
            get_server_auth_methods=get_server_auth_methods,
        ),
    )
    with pytest.raises(module.SFTPBoundaryError, match="methods are unexpected"):
        asyncio.run(module._protocol_evidence(timeout=1))


def test_protocol_evidence_accepts_password_only_for_older_asyncssh_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    class Key:
        def get_algorithm(self) -> str:
            return "ssh-ed25519"

        def get_fingerprint(self, _algorithm: str) -> str:
            return FINGERPRINT

    async def get_server_host_key(**_kwargs: Any) -> Key:
        return Key()

    async def get_server_auth_methods(**_kwargs: Any) -> list[str]:
        return ["password"]

    monkeypatch.setitem(
        sys.modules,
        "asyncssh",
        SimpleNamespace(
            get_server_host_key=get_server_host_key,
            get_server_auth_methods=get_server_auth_methods,
        ),
    )
    evidence = asyncio.run(module._protocol_evidence(timeout=1))
    assert evidence["auth_methods"] == ["password"]
    assert evidence["password_offered"] is True


def test_protocol_client_contract_is_content_free_and_requires_zero_auth_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    sensitive = {
        "id": "audit-private-id",
        "workspace_id": "workspace-private-id",
        "timestamp": "2026-07-22T12:00:00",
        "event_type": "deposit.sftp.auth.success",
        "actor": "sftp:private-access-id",
        "details": {
            "access_id": "private-access-id",
            "link_id": "private-link-id",
        },
        "trace_id": None,
        "agent_id": None,
        "severity": "info",
    }
    inventory = module._auth_inventory_from_rows([sensitive])
    calls = 0

    def inventory_reader() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return deepcopy(inventory)

    monkeypatch.setattr(module, "_client_container_id", lambda: CLIENT_ID[:12])
    payload = module.build_protocol_client_contract(
        sha=SHA,
        deployment_id=DEPLOYMENT_ID,
        inventory_reader=inventory_reader,
        protocol_reader=_protocol_payload,
    )

    assert calls == 2
    assert payload["result"] == "passed"
    assert payload["authentication_audit"]["added_count"] == 0
    assert payload["authentication_audit"]["removed_count"] == 0
    assert payload["authentication_audit"]["changed_count"] == 0
    assert payload["credentials_used"] is False
    assert payload["protocol"]["password_submitted"] is False
    assert payload["protocol"]["sftp_subsystem_requested"] is False
    assert payload["protocol"]["directory_enumeration_requested"] is False
    serialized = json.dumps(payload)
    for forbidden in (
        "audit-private-id",
        "workspace-private-id",
        "private-access-id",
        "private-link-id",
        module._AUTH_METHOD_PROBE_PRINCIPAL,
        "127.0.0.1",
        "/data/",
    ):
        assert forbidden not in serialized


def test_protocol_client_contract_fails_on_added_auth_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    before = module._auth_inventory_from_rows([])
    after = module._auth_inventory_from_rows(
        [
            {
                "id": "new-audit",
                "event_type": "deposit.sftp.auth.success",
                "actor": "hidden",
            }
        ]
    )
    inventories = iter((before, after))
    monkeypatch.setattr(module, "_client_container_id", lambda: CLIENT_ID[:12])
    with pytest.raises(module.SFTPBoundaryError, match="changed authentication audit"):
        module.build_protocol_client_contract(
            sha=SHA,
            deployment_id=DEPLOYMENT_ID,
            inventory_reader=lambda: next(inventories),
            protocol_reader=_protocol_payload,
        )


def test_auth_inventory_detects_add_remove_and_change_without_serializing_rows() -> None:
    module = _module()
    base = {"id": "one", "event_type": "deposit.sftp.auth.success", "actor": "secret"}
    before = module._auth_inventory_from_rows([base])
    changed = module._auth_inventory_from_rows([{**base, "severity": "warning"}])
    removed = module._auth_inventory_from_rows([])
    added = module._auth_inventory_from_rows(
        [base, {"id": "two", "event_type": "deposit.sftp.auth.failed"}]
    )
    for after in (changed, removed, added):
        with pytest.raises(module.SFTPBoundaryError, match="changed authentication audit"):
            module._compare_auth_inventory(before, after)
    assert "secret" not in json.dumps(before)


def test_docker_protocol_contract_binds_runtime_identity_and_candidate_images(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    client = _container(
        "agentium-backend",
        container_id=CLIENT_ID,
        image_id=CLIENT_IMAGE,
        running=True,
    )
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda name: deepcopy(sftp if name == "agentium-sftp" else client),
    )
    monkeypatch.setattr(module, "_image_revision", _revision_for_image)
    client_proof = {
        "profile": module.PROFILE_PROTOCOL_CLIENT,
        "sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "result": "passed",
        "client_identity": {"container_id": CLIENT_ID[:12]},
        "protocol": _protocol_payload(),
        "authentication_audit": _audit_comparison(),
        "credentials_used": False,
        "content_serialized": False,
    }
    monkeypatch.setattr(
        module, "_docker_protocol_client", lambda **_kwargs: deepcopy(client_proof)
    )
    closed_path = tmp_path / "closed.json"
    closed_path.write_text(json.dumps(_closed_proof()), encoding="utf-8")

    payload = module.build_docker_protocol_contract(
        sha=SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        closed_proof_path=closed_path,
    )

    assert payload["result"] == "passed"
    assert payload["sftp_identity"]["container_id"] == SFTP_ID
    assert payload["sftp_identity"]["revision"] == SFTP_SHA
    assert payload["client_identity"]["container_id"] == CLIENT_ID
    assert payload["client_identity"]["revision"] == SHA
    assert payload["revision_binding"] == {
        "candidate_sha": SHA,
        "client_sha": SHA,
        "sftp_sha": SFTP_SHA,
        "revisions_distinct": True,
        "client_image_revision_verified": True,
        "sftp_image_revision_verified": True,
    }
    assert payload["authentication_audit"]["unchanged"] is True
    assert payload["credentials_used"] is False
    assert payload["closed_proof_sha256"] == hashlib.sha256(
        closed_path.read_bytes()
    ).hexdigest()
    assert payload["closed_boundary_binding"] == {
        "same_candidate_sha": True,
        "same_sftp_sha": True,
        "server_client_sha_distinct": True,
        "same_deployment_id": True,
        "same_container_id": True,
        "same_image_id": True,
        "same_host_key_fingerprint": True,
    }


def test_docker_protocol_contract_rejects_runtime_identity_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    client = _container(
        "agentium-backend",
        container_id=CLIENT_ID,
        image_id=CLIENT_IMAGE,
        running=True,
    )
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda name: deepcopy(sftp if name == "agentium-sftp" else client),
    )
    monkeypatch.setattr(module, "_image_revision", _revision_for_image)
    proof = {
        "profile": module.PROFILE_PROTOCOL_CLIENT,
        "sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "result": "passed",
        "client_identity": {"container_id": "f" * 12},
        "protocol": _protocol_payload(),
        "authentication_audit": _audit_comparison(),
        "credentials_used": False,
        "content_serialized": False,
    }
    monkeypatch.setattr(module, "_docker_protocol_client", lambda **_kwargs: proof)
    closed_path = tmp_path / "closed.json"
    closed_path.write_text(json.dumps(_closed_proof()), encoding="utf-8")
    with pytest.raises(module.SFTPBoundaryError, match="runtime identity"):
        module.build_docker_protocol_contract(
            sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            closed_proof_path=closed_path,
        )


@pytest.mark.parametrize("drifted_image", [SFTP_IMAGE, CLIENT_IMAGE])
def test_docker_protocol_rejects_server_or_client_revision_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, drifted_image: str
) -> None:
    module = _module()
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    client = _container(
        "agentium-backend",
        container_id=CLIENT_ID,
        image_id=CLIENT_IMAGE,
        running=True,
    )
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda name: deepcopy(sftp if name == "agentium-sftp" else client),
    )

    def revision(image_id: str) -> str:
        if image_id == drifted_image:
            return "f" * 40
        return _revision_for_image(image_id)

    monkeypatch.setattr(module, "_image_revision", revision)
    monkeypatch.setattr(
        module,
        "_docker_protocol_client",
        lambda **_kwargs: pytest.fail("must reject before the protocol probe"),
    )
    closed_path = tmp_path / "closed.json"
    closed_path.write_text(json.dumps(_closed_proof()), encoding="utf-8")

    with pytest.raises(module.SFTPBoundaryError, match="required SHA"):
        module.build_docker_protocol_contract(
            sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            closed_proof_path=closed_path,
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("sha", "f" * 40, "not bound"),
        ("sftp_sha", "f" * 40, "not bound"),
        ("deployment_id", "deploy-sftp-other", "not bound"),
        ("container_revision", "f" * 40, "required boundary"),
        ("binding_sftp_sha", "f" * 40, "required boundary"),
        ("container_id", "f" * 64, "identity differs"),
        ("image_id", "sha256:" + "f" * 64, "identity differs"),
        ("fingerprint", "SHA256:" + "B" * 43, "host key differs"),
        ("read_only", False, "required boundary"),
    ],
)
def test_docker_protocol_rejects_tampered_or_mismatched_closed_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    replacement: Any,
    message: str,
) -> None:
    module = _module()
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    client = _container(
        "agentium-backend",
        container_id=CLIENT_ID,
        image_id=CLIENT_IMAGE,
        running=True,
    )
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda name: deepcopy(sftp if name == "agentium-sftp" else client),
    )
    monkeypatch.setattr(module, "_image_revision", _revision_for_image)
    client_proof = {
        "profile": module.PROFILE_PROTOCOL_CLIENT,
        "sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "result": "passed",
        "client_identity": {"container_id": CLIENT_ID[:12]},
        "protocol": _protocol_payload(),
        "authentication_audit": _audit_comparison(),
        "credentials_used": False,
        "content_serialized": False,
    }
    monkeypatch.setattr(module, "_docker_protocol_client", lambda **_kwargs: client_proof)
    closed = _closed_proof()
    if field == "sha":
        closed["sha"] = replacement
    elif field == "sftp_sha":
        closed["sftp_sha"] = replacement
    elif field == "deployment_id":
        closed["deployment_id"] = replacement
    elif field == "container_revision":
        closed["container"]["revision"] = replacement
    elif field == "binding_sftp_sha":
        closed["revision_binding"]["sftp_sha"] = replacement
    elif field in {"container_id", "image_id"}:
        closed["container"][field] = replacement
    elif field == "read_only":
        closed["secure_deposit"][field] = replacement
    else:
        closed["host_key"][field] = replacement
    path = tmp_path / "closed.json"
    path.write_text(json.dumps(closed), encoding="utf-8")

    with pytest.raises(module.SFTPBoundaryError, match=message):
        module.build_docker_protocol_contract(
            sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            closed_proof_path=path,
        )


def test_rollback_continuity_binds_previous_runtime_to_fresh_closed_boundary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    closed = _closed_proof()
    closed["captured_at"] = module._utc_now()
    closed_path = tmp_path / "rollback-closed.json"
    closed_path.write_text(json.dumps(closed), encoding="utf-8")
    closed_path.chmod(0o600)
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    client = _container(
        "agentium-backend",
        container_id=CLIENT_ID,
        image_id=CLIENT_IMAGE,
        running=True,
    )
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda name: deepcopy(sftp if name == "agentium-sftp" else client),
    )
    monkeypatch.setattr(module, "_image_revision", lambda _image: PREVIOUS_SHA)
    monkeypatch.setattr(module, "_published_sftp_port", lambda _payload: 2223)
    gate_calls: list[dict[str, Any]] = []

    def gate(**kwargs: Any) -> dict[str, bool]:
        gate_calls.append(kwargs)
        return {
            "ipv4_input": True,
            "ipv4_docker_user": True,
            "ipv6_input": True,
            "ipv6_docker_user": True,
        }

    monkeypatch.setattr(module, "_gate_contract", gate)
    mount_calls: list[str] = []

    def secure_mount(
        _payload: dict[str, Any], *, expected_source: str
    ) -> tuple[dict[str, Any], Path]:
        mount_calls.append(expected_source)
        return (
            {
                "source_matches_expected": True,
                "autonomous_mountpoint": True,
                "read_only": True,
                "device_id": 123,
            },
            tmp_path,
        )

    monkeypatch.setattr(module, "_secure_mount_contract", secure_mount)
    monkeypatch.setattr(module, "_host_key_path", lambda *_args: tmp_path / "hidden")
    monkeypatch.setattr(
        module,
        "_host_key_fingerprint",
        lambda _path: deepcopy(closed["host_key"]),
    )
    monkeypatch.setattr(
        module,
        "_docker_protocol_client",
        lambda **kwargs: (
            deepcopy(_rollback_protocol_client_proof())
            if kwargs == {"sha": PREVIOUS_SHA, "deployment_id": DEPLOYMENT_ID}
            else pytest.fail("unexpected protocol client identity")
        ),
    )
    monkeypatch.setattr(
        module,
        "_read_published_ssh_identification",
        lambda port: (
            {
                "ssh_v2_identification_validated": True,
                "raw_identification_serialized": False,
                "connection_closed_before_authentication": True,
            }
            if port == 2223
            else pytest.fail("unexpected published SFTP port")
        ),
    )

    payload = module.build_rollback_continuity_contract(
        sha=PREVIOUS_SHA,
        candidate_sha=SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        closed_proof_path=closed_path,
        expected_secure_source=EXPECTED_SECURE_SOURCE,
    )

    assert payload["profile"] == module.PROFILE_ROLLBACK_CONTINUITY
    assert payload["sha"] == PREVIOUS_SHA
    assert payload["candidate_sha"] == SHA
    assert payload["sftp_identity"] == {
        "container_id": SFTP_ID,
        "image_id": SFTP_IMAGE,
        "revision": SFTP_SHA,
        "healthy": True,
        "restart_policy_disabled": True,
    }
    assert payload["client_identity"] == {
        "container_id": CLIENT_ID,
        "image_id": CLIENT_IMAGE,
        "revision": PREVIOUS_SHA,
        "is_previous_runtime": True,
    }
    assert payload["closed_boundary"]["sha256"] == hashlib.sha256(
        closed_path.read_bytes()
    ).hexdigest()
    assert payload["closed_boundary"]["same_container_id"] is True
    assert payload["closed_boundary"]["same_image_id"] is True
    assert payload["ingress_gate"]["remained_closed"] is True
    assert payload["secure_deposit"]["remained_read_only"] is True
    assert payload["secure_deposit"]["same_device"] is True
    assert payload["host_key"]["same_as_closed_boundary"] is True
    assert payload["published_transport"] == {
        "ssh_v2_identification_validated": True,
        "connection_closed_before_authentication": True,
        "raw_identification_serialized": False,
        "loopback_probe": True,
        "external_gate_closed_during_probe": True,
    }
    assert all(isinstance(value, bool) for value in payload["published_transport"].values())
    assert payload["authentication_audit"]["unchanged"] is True
    assert payload["credentials_used"] is False
    assert payload["content_serialized"] is False
    assert payload["raw_network_data_serialized"] is False
    assert len(gate_calls) == 3
    assert all(call["expected_closed"] is True for call in gate_calls)
    assert mount_calls == [EXPECTED_SECURE_SOURCE, EXPECTED_SECURE_SOURCE]
    serialized = json.dumps(payload)
    for forbidden in (
        module._AUTH_METHOD_PROBE_PRINCIPAL,
        EXPECTED_SECURE_SOURCE,
        "/hidden/",
        "127.0.0.1",
        "password-value",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("drift", "message"),
    [
        ("protocol-host-key", "different SFTP host key"),
        ("auth-inventory", "auth inventory evidence is invalid"),
        ("protocol-extra", "protocol evidence is invalid"),
        ("audit-extra", "auth inventory evidence is invalid"),
        ("published-failure", "published SFTP transport is unavailable"),
        ("published-substitution", "published SFTP transport evidence is invalid"),
        ("gate-after", "ingress gate is not fully closed"),
        ("secure-after", "not unchanged and read-only"),
        ("container-after", "changed during proof"),
    ],
)
def test_rollback_continuity_rejects_runtime_or_boundary_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    drift: str,
    message: str,
) -> None:
    module = _module()
    closed = _closed_proof()
    closed["captured_at"] = module._utc_now()
    closed_path = tmp_path / "rollback-closed.json"
    closed_path.write_text(json.dumps(closed), encoding="utf-8")
    closed_path.chmod(0o600)
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    client = _container(
        "agentium-backend",
        container_id=CLIENT_ID,
        image_id=CLIENT_IMAGE,
        running=True,
    )
    sftp_inspections = 0

    def inspect(name: str) -> dict[str, Any]:
        nonlocal sftp_inspections
        if name != "agentium-sftp":
            return deepcopy(client)
        sftp_inspections += 1
        current = deepcopy(sftp)
        if drift == "container-after" and sftp_inspections == 2:
            current["Id"] = "f" * 64
        return current

    monkeypatch.setattr(module, "_docker_inspect", inspect)
    monkeypatch.setattr(module, "_image_revision", lambda _image: PREVIOUS_SHA)
    monkeypatch.setattr(module, "_published_sftp_port", lambda _payload: 2223)
    gate_calls = 0

    def gate(**_kwargs: Any) -> dict[str, bool]:
        nonlocal gate_calls
        gate_calls += 1
        return {
            "ipv4_input": drift != "gate-after" or gate_calls == 1,
            "ipv4_docker_user": True,
            "ipv6_input": True,
            "ipv6_docker_user": True,
        }

    monkeypatch.setattr(module, "_gate_contract", gate)
    mount_calls = 0

    def secure_mount(
        _payload: dict[str, Any], *, expected_source: str
    ) -> tuple[dict[str, Any], Path]:
        nonlocal mount_calls
        assert expected_source == EXPECTED_SECURE_SOURCE
        mount_calls += 1
        return (
            {
                "source_matches_expected": True,
                "autonomous_mountpoint": True,
                "read_only": drift != "secure-after" or mount_calls == 1,
                "device_id": 123,
            },
            tmp_path,
        )

    monkeypatch.setattr(module, "_secure_mount_contract", secure_mount)
    monkeypatch.setattr(module, "_host_key_path", lambda *_args: tmp_path / "hidden")
    monkeypatch.setattr(
        module,
        "_host_key_fingerprint",
        lambda _path: deepcopy(closed["host_key"]),
    )
    protocol_proof = _rollback_protocol_client_proof()
    if drift == "protocol-host-key":
        protocol_proof["protocol"]["host_key_fingerprint"] = "SHA256:" + "B" * 43
    if drift == "auth-inventory":
        protocol_proof["authentication_audit"]["changed_count"] = 1
        protocol_proof["authentication_audit"]["unchanged"] = False
    if drift == "protocol-extra":
        protocol_proof["protocol"]["credential"] = "must-not-be-serialized"
    if drift == "audit-extra":
        protocol_proof["authentication_audit"]["row"] = "must-not-be-serialized"
    monkeypatch.setattr(
        module,
        "_docker_protocol_client",
        lambda **_kwargs: deepcopy(protocol_proof),
    )

    def published_transport(_port: int) -> dict[str, Any]:
        if drift == "published-failure":
            raise module.SFTPBoundaryError("published SFTP transport is unavailable")
        payload: dict[str, Any] = {
            "ssh_v2_identification_validated": True,
            "raw_identification_serialized": False,
            "connection_closed_before_authentication": True,
        }
        if drift == "published-substitution":
            payload["identification"] = "must-not-be-serialized"
        return payload

    monkeypatch.setattr(
        module,
        "_read_published_ssh_identification",
        published_transport,
    )

    with pytest.raises(module.SFTPBoundaryError, match=message):
        module.build_rollback_continuity_contract(
            sha=PREVIOUS_SHA,
            candidate_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            closed_proof_path=closed_path,
            expected_secure_source=EXPECTED_SECURE_SOURCE,
        )


def test_rollback_continuity_requires_private_fresh_candidate_closed_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    closed = _closed_proof()
    closed["captured_at"] = "2020-01-01T00:00:00Z"
    path = tmp_path / "rollback-closed.json"
    path.write_text(json.dumps(closed), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda _name: pytest.fail("must reject before inspecting runtime containers"),
    )

    with pytest.raises(module.SFTPBoundaryError, match="not fresh"):
        module.build_rollback_continuity_contract(
            sha=PREVIOUS_SHA,
            candidate_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            closed_proof_path=path,
            expected_secure_source=EXPECTED_SECURE_SOURCE,
        )

    closed["captured_at"] = module._utc_now()
    path.write_text(json.dumps(closed), encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(module.SFTPBoundaryError, match="file is unsafe"):
        module.build_rollback_continuity_contract(
            sha=PREVIOUS_SHA,
            candidate_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            closed_proof_path=path,
            expected_secure_source=EXPECTED_SECURE_SOURCE,
        )

    path.chmod(0o600)
    closed["sha"] = "f" * 40
    path.write_text(json.dumps(closed), encoding="utf-8")
    with pytest.raises(module.SFTPBoundaryError, match="not bound"):
        module.build_rollback_continuity_contract(
            sha=PREVIOUS_SHA,
            candidate_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            closed_proof_path=path,
            expected_secure_source=EXPECTED_SECURE_SOURCE,
        )


def test_validation_ready_contract_is_exact_canonical_and_content_free(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    _install_validation_ready_mocks(module, monkeypatch, tmp_path)

    payload = module.build_validation_ready_contract(
        live_sha=LIVE_SHA,
        release_a_sha=SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        expected_secure_source=RELEASE_A_SECURE_SOURCE,
    )

    assert set(payload) == {
        "schema_version",
        "kind",
        "result",
        "live_sha",
        "release_a_sha",
        "sftp_sha",
        "deployment_id",
        "hostname_sha256",
        "sftp_container_id",
        "sftp_image_id",
        "image_revision",
        "sftp_port",
        "sftp_started_at",
        "runtime_identity_sha256",
        "host_key_fingerprint",
        "state",
        "health_status",
        "ingress_closed",
        "restart_disabled",
        "restart_policy_disabled",
        "secure_deposit_mode",
        "secure_deposit_source",
        "external_established_connection_count",
        "ready_at",
        "ingress_gate",
        "published_transport",
        "secure_deposit",
        "host_key",
        "credentials_used",
        "authentication_attempted",
        "sftp_subsystem_requested",
        "content_serialized",
        "raw_network_data_serialized",
        "raw_identification_serialized",
    }
    assert payload["kind"] == "agentium-release-a-sftp-runtime-ready"
    assert payload["result"] == "passed"
    assert payload["state"] == "running"
    assert payload["health_status"] == "healthy"
    assert payload["ingress_closed"] is True
    assert payload["restart_disabled"] is True
    assert payload["restart_policy_disabled"] is True
    assert payload["secure_deposit_mode"] == "ro"
    assert payload["secure_deposit_source"] == RELEASE_A_SECURE_SOURCE
    assert payload["external_established_connection_count"] == 0
    assert payload["sftp_container_id"] == SFTP_ID
    assert payload["sftp_image_id"] == SFTP_IMAGE
    assert payload["image_revision"] == SFTP_SHA
    assert payload["sftp_started_at"] == SFTP_STARTED_AT
    assert payload["ready_at"] == READY_AT
    assert payload["runtime_identity_sha256"] == module.runtime_identity_sha256(
        live_sha=LIVE_SHA,
        release_a_sha=SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        hostname_sha256="f" * 64,
        sftp_container_id=SFTP_ID,
        sftp_image_id=SFTP_IMAGE,
        sftp_port=2223,
        sftp_started_at=SFTP_STARTED_AT,
    )
    assert set(payload["ingress_gate"]) == {
        "ipv4_input",
        "ipv4_docker_user",
        "ipv6_input",
        "ipv6_docker_user",
    }
    assert set(payload["published_transport"]) == {
        "protocol",
        "container_port",
        "host_port",
        "binding_count",
        "binding_sha256",
        "listener_count",
        "established_connection_count_before",
        "established_connection_count_after",
        "external_established_connection_count",
        "ssh_v2_identification_validated",
        "connection_closed_before_authentication",
        "raw_identification_serialized",
    }
    assert set(payload["secure_deposit"]) == {
        "source_matches_dev_sdc",
        "source_device_sha256",
        "autonomous_mountpoint",
        "host_read_only",
        "namespace_autonomous_mountpoint",
        "namespace_read_only",
        "device_id",
    }
    assert set(payload["host_key"]) == {
        "algorithm",
        "fingerprint",
        "fingerprint_sha256",
        "present",
        "nonempty",
        "regular_file",
        "symlink",
    }
    assert payload["published_transport"]["listener_count"] == 1
    assert (
        payload["published_transport"]["external_established_connection_count"]
        == 0
    )
    assert payload["secure_deposit"]["host_read_only"] is True
    assert payload["secure_deposit"]["namespace_read_only"] is True
    assert payload["host_key_fingerprint"] == FINGERPRINT
    assert payload["credentials_used"] is False
    assert payload["authentication_attempted"] is False
    assert payload["sftp_subsystem_requested"] is False

    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "/data/secure_deposit",
        "/hidden/secure-deposit",
        "127.0.0.1",
        "SSH-2.0-",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("Id", "f" * 64),
        ("Image", "sha256:" + "f" * 64),
    ],
)
def test_validation_ready_rejects_container_or_image_drift_during_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    module = _module()
    sftp = _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    after = deepcopy(sftp)
    after[field] = replacement
    inspections = iter((deepcopy(sftp), after))
    monkeypatch.setattr(module, "_docker_inspect", lambda _name: next(inspections))

    with pytest.raises(module.SFTPBoundaryError, match="changed during proof"):
        module.build_validation_ready_contract(
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["State"].update(Running=False), "not healthy"),
        (lambda value: value["State"].update(StartedAt="invalid"), "timestamp"),
        (lambda value: value.update(Id="f" * 12), "container ID is not exact"),
        (
            lambda value: value.update(Image="sha256:" + "f" * 12),
            "image ID is not exact",
        ),
        (
            lambda value: value["HostConfig"]["RestartPolicy"].update(
                Name="unless-stopped"
            ),
            "restart policy",
        ),
    ],
)
def test_validation_ready_rejects_invalid_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: Any,
    message: str,
) -> None:
    module = _module()
    sftp = _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    mutation(sftp)

    with pytest.raises(module.SFTPBoundaryError, match=message):
        module.build_validation_ready_contract(
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
        )


def test_validation_ready_rejects_wrong_image_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "_image_revision", lambda _image_id: "f" * 40)

    with pytest.raises(module.SFTPBoundaryError, match="required SHA"):
        module.build_validation_ready_contract(
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
        )


def test_validation_ready_requires_all_four_ingress_gates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "_gate_contract",
        lambda **_kwargs: {
            "ipv4_input": True,
            "ipv4_docker_user": True,
            "ipv6_input": True,
        },
    )

    with pytest.raises(module.SFTPBoundaryError, match="not fully closed"):
        module.build_validation_ready_contract(
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
        )


def test_validation_ready_requires_pinned_ed25519_host_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "_host_key_fingerprint",
        lambda _path: {
            "present": True,
            "nonempty": True,
            "regular_file": True,
            "symlink": False,
            "algorithm": "ssh-rsa",
            "fingerprint": FINGERPRINT,
        },
    )

    with pytest.raises(module.SFTPBoundaryError, match="not pinned Ed25519"):
        module.build_validation_ready_contract(
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
        )


@pytest.mark.parametrize(
    ("host_read_only", "namespace_read_only"),
    [(False, True), (True, False)],
)
def test_validation_ready_requires_host_and_namespace_read_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    host_read_only: bool,
    namespace_read_only: bool,
) -> None:
    module = _module()
    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "_secure_mount_contract",
        lambda *_args, expected_source: (
            {
                "source_matches_expected": expected_source
                == RELEASE_A_SECURE_SOURCE,
                "autonomous_mountpoint": True,
                "read_only": host_read_only,
                "device_id": 123,
            },
            tmp_path,
        ),
    )
    monkeypatch.setattr(
        module, "_secure_namespace_read_only", lambda: namespace_read_only
    )

    with pytest.raises(module.SFTPBoundaryError, match="autonomous and read-only"):
        module.build_validation_ready_contract(
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
        )


def test_validation_ready_rejects_external_established_connection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "_established_connection_count", lambda _port: 1)

    with pytest.raises(module.SFTPBoundaryError, match="established external"):
        module.build_validation_ready_contract(
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
        )


def test_validation_ready_rejects_non_loopback_published_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sftp = _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    sftp["HostConfig"]["PortBindings"]["2222/tcp"][0]["HostIp"] = "0.0.0.0"

    with pytest.raises(module.SFTPBoundaryError, match="not loopback-only"):
        module.build_validation_ready_contract(
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
        )


@pytest.mark.parametrize("secure_mode", ["ro", "rw"])
def test_verify_runtime_identity_live_binds_exact_receipt_in_declared_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    secure_mode: str,
) -> None:
    module = _module()
    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    receipt_path = tmp_path / "runtime-ready.json"
    receipt = _write_runtime_ready_receipt(module, receipt_path)

    payload = module.verify_runtime_identity_live_contract(
        receipt_path=receipt_path,
        live_sha=LIVE_SHA,
        release_a_sha=SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        expected_secure_source=RELEASE_A_SECURE_SOURCE,
        expected_secure_mode=secure_mode,
        expected_restart="disabled",
    )

    assert payload == {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-runtime-identity-live",
        "result": "passed",
        "live_sha": LIVE_SHA,
        "release_a_sha": SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "runtime_ready_receipt_sha256": hashlib.sha256(
            receipt_path.read_bytes()
        ).hexdigest(),
        "runtime_identity_sha256": receipt["runtime_identity_sha256"],
        "sftp_container_id": SFTP_ID,
        "sftp_image_id": SFTP_IMAGE,
        "sftp_started_at": SFTP_STARTED_AT,
        "image_revision": SFTP_SHA,
        "sftp_port": 2223,
        "published_binding_sha256": receipt["published_transport"][
            "binding_sha256"
        ],
        "host_key_fingerprint_sha256": receipt["host_key"][
            "fingerprint_sha256"
        ],
        "ingress_closed": True,
        "secure_deposit_mode": secure_mode,
        "restart_expectation": "disabled",
        "restart_policy": {"name": "no", "maximum_retry_count": 0},
        "listener_count": 1,
        "established_connection_count": 0,
        "paused": False,
        "transport_probe_performed": True,
        "ssh_v2_identification_validated": True,
        "credentials_used": False,
        "authentication_attempted": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
        "checked_at": READY_AT,
    }


def test_verify_runtime_identity_live_allows_explicit_paused_recovery_without_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sftp = _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    receipt_path = tmp_path / "runtime-ready.json"
    _write_runtime_ready_receipt(module, receipt_path)
    sftp["State"]["Paused"] = True
    monkeypatch.setattr(
        module,
        "_read_published_ssh_identification",
        lambda _port: pytest.fail("paused recovery must not open a transport"),
    )

    with pytest.raises(module.SFTPBoundaryError, match="not healthy"):
        module.verify_runtime_identity_live_contract(
            receipt_path=receipt_path,
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
            expected_secure_mode="ro",
            expected_restart="disabled",
        )

    payload = module.verify_runtime_identity_live_contract(
        receipt_path=receipt_path,
        live_sha=LIVE_SHA,
        release_a_sha=SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        expected_secure_source=RELEASE_A_SECURE_SOURCE,
        expected_secure_mode="ro",
        expected_restart="disabled",
        allow_paused=True,
    )

    assert payload["paused"] is True
    assert payload["transport_probe_performed"] is False
    assert payload["ssh_v2_identification_validated"] is False
    assert payload["established_connection_count"] == 0


@pytest.mark.parametrize("mode", ["ro", "rw"])
def test_secure_namespace_mode_reads_paused_process_mountinfo(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    module = _module()
    inspected = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    inspected["State"]["Paused"] = True
    commands: list[list[str]] = []

    def run_text(command: list[str], **_kwargs: Any) -> str:
        commands.append(command)
        return (
            f"36 25 8:32 / /data/secure_deposit {mode},relatime "
            "- ext4 /dev/sdc rw,errors=remount-ro"
        )

    monkeypatch.setattr(module, "_run_text", run_text)

    assert module._secure_namespace_mode(mode, inspect_payload=inspected) == mode
    assert commands == [["sudo", "-n", "cat", "/proc/1234/mountinfo"]]
    with pytest.raises(module.SFTPBoundaryError, match="namespace mode differs"):
        module._secure_namespace_mode(
            "rw" if mode == "ro" else "ro", inspect_payload=inspected
        )


def test_verify_runtime_identity_live_accepts_only_recorded_historical_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sftp = _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    receipt_path = tmp_path / "runtime-ready.json"
    _write_runtime_ready_receipt(module, receipt_path)
    sftp["HostConfig"]["RestartPolicy"] = {
        "Name": "unless-stopped",
        "MaximumRetryCount": 0,
    }
    runtime_state = tmp_path / "runtime-state.tsv"
    runtime_state.write_text(
        "format\t1\n"
        f"container\tagentium-sftp\ttrue\t{SFTP_IMAGE}\tunless-stopped\t0\n",
        encoding="utf-8",
    )
    runtime_state.chmod(0o600)

    payload = module.verify_runtime_identity_live_contract(
        receipt_path=receipt_path,
        live_sha=LIVE_SHA,
        release_a_sha=SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        expected_secure_source=RELEASE_A_SECURE_SOURCE,
        expected_secure_mode="rw",
        expected_restart="historical",
        runtime_state_path=runtime_state,
    )

    assert payload["restart_expectation"] == "historical"
    assert payload["restart_policy"] == {
        "name": "unless-stopped",
        "maximum_retry_count": 0,
    }

    sftp["HostConfig"]["RestartPolicy"]["Name"] = "always"
    with pytest.raises(module.SFTPBoundaryError, match="restart policy differs"):
        module.verify_runtime_identity_live_contract(
            receipt_path=receipt_path,
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
            expected_secure_mode="rw",
            expected_restart="historical",
            runtime_state_path=runtime_state,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(sftp_container_id="f" * 64),
        lambda value: value.update(sftp_started_at="2026-07-23T08:00:01Z"),
        lambda value: value["host_key"].update(fingerprint="SHA256:" + "B" * 43),
        lambda value: value["published_transport"].update(binding_sha256="0" * 64),
        lambda value: value["ingress_gate"].update(ipv4_input=False),
        lambda value: value.update(unexpected=True),
    ],
)
def test_verify_runtime_identity_live_rejects_canonical_receipt_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: Any,
) -> None:
    module = _module()
    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    receipt_path = tmp_path / "runtime-ready.json"
    receipt = _write_runtime_ready_receipt(module, receipt_path)
    mutation(receipt)
    module._write_canonical_json(receipt, str(receipt_path))

    with pytest.raises(module.SFTPBoundaryError, match="receipt"):
        module.verify_runtime_identity_live_contract(
            receipt_path=receipt_path,
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
            expected_secure_mode="ro",
            expected_restart="disabled",
        )


def test_verify_runtime_identity_live_rejects_noncanonical_receipt_before_live_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    receipt_path = tmp_path / "runtime-ready.json"
    receipt = _write_runtime_ready_receipt(module, receipt_path)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    receipt_path.chmod(0o600)
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda _name: pytest.fail("noncanonical receipt must fail before live inspection"),
    )

    with pytest.raises(module.SFTPBoundaryError, match="not canonical JSON"):
        module.verify_runtime_identity_live_contract(
            receipt_path=receipt_path,
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
            expected_secure_mode="ro",
            expected_restart="disabled",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(Id="f" * 64), "identity differs"),
        (
            lambda value: value["State"].update(
                StartedAt="2026-07-23T08:00:01.123456789Z"
            ),
            "identity differs",
        ),
        (lambda value: value["State"].update(Health={"Status": "unhealthy"}), "not healthy"),
    ],
)
def test_verify_runtime_identity_live_rejects_live_process_substitution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: Any,
    message: str,
) -> None:
    module = _module()
    sftp = _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    receipt_path = tmp_path / "runtime-ready.json"
    _write_runtime_ready_receipt(module, receipt_path)
    mutation(sftp)

    with pytest.raises(module.SFTPBoundaryError, match=message):
        module.verify_runtime_identity_live_contract(
            receipt_path=receipt_path,
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
            expected_secure_mode="ro",
            expected_restart="disabled",
        )


def test_verify_runtime_identity_live_rejects_mode_gate_host_key_and_connection_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    receipt_path = tmp_path / "runtime-ready.json"
    _write_runtime_ready_receipt(module, receipt_path)

    monkeypatch.setattr(
        module,
        "_secure_mount_contract",
        lambda *_args, **_kwargs: (
            {
                "source_matches_expected": True,
                "autonomous_mountpoint": True,
                "read_only": True,
                "device_id": 123,
            },
            tmp_path,
        ),
    )
    with pytest.raises(module.SFTPBoundaryError, match="live Secure Deposit mode differs"):
        module.verify_runtime_identity_live_contract(
            receipt_path=receipt_path,
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
            expected_secure_mode="rw",
            expected_restart="disabled",
        )

    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    monkeypatch.setattr(module, "_established_connection_count", lambda _port: 1)
    with pytest.raises(module.SFTPBoundaryError, match="identity differs"):
        module.verify_runtime_identity_live_contract(
            receipt_path=receipt_path,
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
            expected_secure_mode="ro",
            expected_restart="disabled",
        )

    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "_gate_contract",
        lambda **_kwargs: {
            "ipv4_input": True,
            "ipv4_docker_user": True,
            "ipv6_input": True,
            "ipv6_docker_user": False,
        },
    )
    with pytest.raises(module.SFTPBoundaryError, match="not fully closed"):
        module.verify_runtime_identity_live_contract(
            receipt_path=receipt_path,
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
            expected_secure_mode="ro",
            expected_restart="disabled",
        )

    _install_validation_ready_mocks(module, monkeypatch, tmp_path)
    monkeypatch.setattr(
        module,
        "_host_key_fingerprint",
        lambda _path: {
            "present": True,
            "nonempty": True,
            "regular_file": True,
            "symlink": False,
            "algorithm": "ssh-ed25519",
            "fingerprint": "SHA256:" + "B" * 43,
        },
    )
    with pytest.raises(module.SFTPBoundaryError, match="identity differs"):
        module.verify_runtime_identity_live_contract(
            receipt_path=receipt_path,
            live_sha=LIVE_SHA,
            release_a_sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=RELEASE_A_SECURE_SOURCE,
            expected_secure_mode="ro",
            expected_restart="disabled",
        )


def test_closed_boundary_contract_is_content_free_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=False,
    )
    monkeypatch.setattr(module, "_docker_inspect", lambda _name: deepcopy(sftp))
    verified_revisions: list[str] = []

    def verify_sftp_revision(_payload: dict[str, Any], expected_sha: str) -> str:
        verified_revisions.append(expected_sha)
        return SFTP_IMAGE

    monkeypatch.setattr(module, "_assert_image_revision", verify_sftp_revision)
    monkeypatch.setattr(module, "_published_sftp_port", lambda _payload: 2223)
    monkeypatch.setattr(
        module,
        "_gate_contract",
        lambda **_kwargs: {
            "ipv4_input": True,
            "ipv4_docker_user": True,
            "ipv6_input": True,
            "ipv6_docker_user": True,
        },
    )
    monkeypatch.setattr(module, "_listener_count", lambda _port: 0)
    monkeypatch.setattr(module, "_established_connection_count", lambda _port: 0)

    def fake_run_text(command: list[str], **_kwargs: Any) -> str:
        if "ActiveState" in command:
            return "inactive"
        if "UnitFileState" in command:
            return "disabled"
        raise AssertionError(command)

    monkeypatch.setattr(module, "_run_text", fake_run_text)
    secure_sources: list[str] = []

    def fake_secure_mount(
        *_args: Any, expected_source: str
    ) -> tuple[dict[str, Any], Path]:
        secure_sources.append(expected_source)
        return (
            {
                "source_matches_expected": True,
                "autonomous_mountpoint": True,
                "read_only": True,
                "device_id": 123,
            },
            tmp_path,
        )

    monkeypatch.setattr(module, "_secure_mount_contract", fake_secure_mount)
    monkeypatch.setattr(module, "_host_key_path", lambda *_args: tmp_path / "hidden")
    monkeypatch.setattr(
        module,
        "_host_key_fingerprint",
        lambda _path: {
            "present": True,
            "nonempty": True,
            "regular_file": True,
            "symlink": False,
            "algorithm": "ssh-ed25519",
            "fingerprint": FINGERPRINT,
        },
    )
    monkeypatch.setattr(module, "_negative_loopback_connect", lambda *_args: True)

    payload = module.build_closed_boundary_contract(
        sha=SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        expected_secure_source=EXPECTED_SECURE_SOURCE,
    )

    assert payload["result"] == "passed"
    assert payload["sha"] == SHA
    assert payload["sftp_sha"] == SFTP_SHA
    assert payload["container"]["revision"] == SFTP_SHA
    assert verified_revisions == [SFTP_SHA]
    assert payload["revision_binding"] == {
        "candidate_sha": SHA,
        "client_sha": SHA,
        "sftp_sha": SFTP_SHA,
        "revisions_distinct": True,
        "client_image_revision_verified": False,
        "sftp_image_revision_verified": True,
    }
    assert payload["container"]["running"] is False
    assert payload["container"]["restart_policy_disabled"] is True
    assert payload["container"]["secure_deposit_open_fd_count"] == 0
    assert payload["network"] == {
        "listener_count": 0,
        "established_connection_count": 0,
        "ipv4_connect_rejected": True,
        "ipv6_connect_rejected": True,
    }
    assert payload["secure_deposit"]["read_only"] is True
    assert secure_sources == [EXPECTED_SECURE_SOURCE]
    serialized = json.dumps(payload)
    for forbidden in (
        "/hidden/secure-deposit",
        "/data/secure_deposit",
        "/dev/sdc",
        "127.0.0.1",
        "::1",
        "SSH-2.0-",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("sftp_sha", "message"),
    [
        (SHA, "must differ"),
        ("B" * 40, "complete lowercase"),
        ("b" * 39, "complete lowercase"),
    ],
)
def test_boundary_rejects_invalid_or_candidate_equal_sftp_sha_before_inspect(
    monkeypatch: pytest.MonkeyPatch, sftp_sha: str, message: str
) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda _name: pytest.fail("must reject before Docker inspection"),
    )

    with pytest.raises(module.SFTPBoundaryError, match=message):
        module.build_closed_boundary_contract(
            sha=SHA,
            sftp_sha=sftp_sha,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=EXPECTED_SECURE_SOURCE,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["State"].update(Running=True), "not stopped"),
        (
            lambda value: value["HostConfig"]["RestartPolicy"].update(
                Name="unless-stopped"
            ),
            "restart policy",
        ),
        (lambda value: value["State"].update(Pid=42), "retains a process"),
    ],
)
def test_closed_boundary_rejects_writer_state_before_any_network_probe(
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
    message: str,
) -> None:
    module = _module()
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=False,
    )
    mutation(sftp)
    monkeypatch.setattr(module, "_docker_inspect", lambda _name: sftp)
    monkeypatch.setattr(module, "_assert_image_revision", lambda *_args: SFTP_IMAGE)
    monkeypatch.setattr(
        module,
        "_published_sftp_port",
        lambda _payload: pytest.fail("port must not be inspected after writer-state failure"),
    )
    with pytest.raises(module.SFTPBoundaryError, match=message):
        module.build_closed_boundary_contract(
            sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=EXPECTED_SECURE_SOURCE,
        )


@pytest.mark.parametrize(
    "source",
    [
        "sdc",
        "/srv/agentium-data",
        "/dev/",
        "/dev/../srv/agentium-data",
        "/dev//sdc",
        "/dev/sdc\n--output=/tmp/leak",
    ],
)
def test_closed_boundary_rejects_non_device_expected_source_before_inspect(
    monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    module = _module()
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda _name: pytest.fail("must reject the source before Docker inspection"),
    )

    with pytest.raises(module.SFTPBoundaryError, match="must be a /dev device path"):
        module.build_closed_boundary_contract(
            sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            expected_secure_source=source,
        )


def test_gate_contract_requires_one_exact_rule_per_family_and_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    comment = f"agentium-safe-sftp-{DEPLOYMENT_ID}"
    input_rule = (
        f'-A INPUT ! -i lo -p tcp -m tcp --dport 2223 -m conntrack --ctstate NEW '
        f'-m comment --comment "{comment}" -j REJECT --reject-with tcp-reset'
    )
    docker_rule = (
        f'-A DOCKER-USER ! -i lo -p tcp -m conntrack --ctorigdstport 2223 --ctstate NEW '
        f'-m comment --comment "{comment}" -j REJECT --reject-with tcp-reset'
    )
    monkeypatch.setattr(module, "_run_text", lambda *_args, **_kwargs: input_rule + "\n" + docker_rule)
    checked: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        checked.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module, "_run", fake_run)
    result = module._gate_contract(
        deployment_id=DEPLOYMENT_ID, host_port=2223, expected_closed=True
    )
    assert result == {
        "ipv4_input": True,
        "ipv4_docker_user": True,
        "ipv6_input": True,
        "ipv6_docker_user": True,
    }
    assert len(checked) == 4


def test_gate_contract_rejects_duplicate_or_foreign_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    comment = f"agentium-safe-sftp-{DEPLOYMENT_ID}"
    rule = (
        f'-A INPUT ! -i lo -p tcp --dport 2223 -m conntrack --ctstate NEW '
        f'-m comment --comment "{comment}" -j REJECT --reject-with tcp-reset'
    )
    monkeypatch.setattr(module, "_run_text", lambda *_args, **_kwargs: rule + "\n" + rule)
    with pytest.raises(module.SFTPBoundaryError, match="incomplete or ambiguous"):
        module._gate_contract(
            deployment_id=DEPLOYMENT_ID, host_port=2223, expected_closed=True
        )

    foreign = rule + "\n" + rule.replace(comment, "agentium-safe-sftp-old")
    monkeypatch.setattr(module, "_run_text", lambda *_args, **_kwargs: foreign)
    with pytest.raises(module.SFTPBoundaryError, match="foreign"):
        module._gate_contract(
            deployment_id=DEPLOYMENT_ID, host_port=2223, expected_closed=True
        )


class _BannerSocket:
    def __init__(self, banner: bytes):
        self.banner = bytearray(banner)
        self.connected_to: Any = None
        self.closed = False

    def settimeout(self, _timeout: float) -> None:
        pass

    def connect(self, target: Any) -> None:
        self.connected_to = target

    def recv(self, _size: int) -> bytes:
        if not self.banner:
            return b""
        return bytes([self.banner.pop(0)])

    def close(self) -> None:
        self.closed = True


def test_host_identification_probe_validates_but_never_serializes_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    raw_banner = b"SSH-2.0-PrivateRuntimeVersion\r\n"
    fake = _BannerSocket(raw_banner)
    monkeypatch.setattr(module.socket, "socket", lambda *_args: fake)
    payload = module._read_published_ssh_identification(2223)
    assert payload == {
        "ssh_v2_identification_validated": True,
        "raw_identification_serialized": False,
        "connection_closed_before_authentication": True,
    }
    assert fake.connected_to == ("127.0.0.1", 2223)
    assert fake.closed is True
    assert "PrivateRuntimeVersion" not in json.dumps(payload)


@pytest.mark.parametrize(
    "banner",
    [b"HTTP/1.1 200 OK\r\n", b"SSH-1.5-old\r\n", b"SSH-2.0-bad\x00value\r\n", b""],
)
def test_host_identification_probe_rejects_non_ssh2_without_echoing_content(
    monkeypatch: pytest.MonkeyPatch, banner: bytes
) -> None:
    module = _module()
    monkeypatch.setattr(module.socket, "socket", lambda *_args: _BannerSocket(banner))
    with pytest.raises(module.SFTPBoundaryError, match="identification is invalid") as raised:
        module._read_published_ssh_identification(2223)
    if banner:
        assert banner.decode("latin1") not in str(raised.value)


def test_host_banner_contract_is_bound_to_internal_proof_and_zero_db_delta(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    client = _container(
        "agentium-backend",
        container_id=CLIENT_ID,
        image_id=CLIENT_IMAGE,
        running=True,
    )
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda name: deepcopy(sftp if name == "agentium-sftp" else client),
    )
    monkeypatch.setattr(module, "_image_revision", _revision_for_image)
    monkeypatch.setattr(module, "_published_sftp_port", lambda _payload: 2223)
    monkeypatch.setattr(
        module,
        "_gate_contract",
        lambda **_kwargs: {
            "ipv4_input": True,
            "ipv4_docker_user": True,
            "ipv6_input": True,
            "ipv6_docker_user": True,
        },
    )
    monkeypatch.setattr(
        module,
        "_read_published_ssh_identification",
        lambda _port: {
            "ssh_v2_identification_validated": True,
            "raw_identification_serialized": False,
            "connection_closed_before_authentication": True,
        },
    )
    inventory = _auth_inventory()
    db_payload = {
        "profile": module.PROFILE_DB_INVENTORY,
        "sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "result": "passed",
        "content_serialized": False,
        "client_identity": {"container_id": CLIENT_ID[:12]},
        "inventory": inventory,
    }
    monkeypatch.setattr(
        module, "_docker_db_auth_inventory", lambda **_kwargs: deepcopy(db_payload)
    )
    proof_path = tmp_path / "protocol.json"
    proof_path.write_text(json.dumps(_docker_protocol_proof()), encoding="utf-8")
    validation_path = tmp_path / "validation.json"
    validation_path.write_text(json.dumps(_validation_proof()), encoding="utf-8")
    validation_path.chmod(0o600)

    payload = module.build_host_banner_contract(
        sha=SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        protocol_proof_path=proof_path,
        validation_proof_path=validation_path,
    )

    assert payload["result"] == "passed"
    assert payload["sha"] == SHA
    assert payload["sftp_sha"] == SFTP_SHA
    assert payload["sftp_identity"]["revision"] == SFTP_SHA
    assert payload["client_identity"]["revision"] == SHA
    assert payload["revision_binding"] == {
        "candidate_sha": SHA,
        "client_sha": SHA,
        "sftp_sha": SFTP_SHA,
        "revisions_distinct": True,
        "client_image_revision_verified": True,
        "sftp_image_revision_verified": True,
    }
    assert payload["host_key"]["fingerprint"] == FINGERPRINT
    assert payload["host_key"]["bound_to_internal_protocol_proof"] is True
    assert payload["authentication_audit"]["unchanged"] is True
    assert payload["credentials_used"] is False
    assert payload["validation_proof_sha256"] == hashlib.sha256(
        validation_path.read_bytes()
    ).hexdigest()
    assert payload["closed_proof_sha256"] == "1" * 64
    assert payload["protocol_proof_sha256"] == hashlib.sha256(
        proof_path.read_bytes()
    ).hexdigest()
    assert payload["proof_chain"] == {
        "validation_bound": True,
        "closed_boundary_bound": True,
        "docker_protocol_bound": True,
        "published_transport_bound": True,
        "candidate_sha_bound": True,
        "sftp_sha_bound": True,
        "server_client_sha_distinct": True,
    }
    assert payload["ingress_gate"] == {
        "ipv4_input": True,
        "ipv4_docker_user": True,
        "ipv6_input": True,
        "ipv6_docker_user": True,
    }


def test_host_banner_contract_rejects_protocol_proof_container_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    client = _container(
        "agentium-backend",
        container_id=CLIENT_ID,
        image_id=CLIENT_IMAGE,
        running=True,
    )
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda name: deepcopy(sftp if name == "agentium-sftp" else client),
    )
    monkeypatch.setattr(module, "_image_revision", _revision_for_image)
    proof = _docker_protocol_proof()
    proof["sftp_identity"]["container_id"] = "f" * 64
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(proof), encoding="utf-8")
    validation_path = tmp_path / "validation.json"
    validation_path.write_text(json.dumps(_validation_proof()), encoding="utf-8")
    validation_path.chmod(0o600)
    monkeypatch.setattr(
        module,
        "_published_sftp_port",
        lambda _payload: pytest.fail("must reject before opening the transport"),
    )
    with pytest.raises(module.SFTPBoundaryError, match="proven containers"):
        module.build_host_banner_contract(
            sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            protocol_proof_path=path,
            validation_proof_path=validation_path,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda proof: proof.pop("closed_proof_sha256"),
        lambda proof: proof.update(closed_proof_sha256="not-a-digest"),
        lambda proof: proof.update(sha="f" * 40),
        lambda proof: proof.update(sftp_sha="f" * 40),
        lambda proof: proof["sftp_identity"].update(revision="f" * 40),
        lambda proof: proof["client_identity"].update(revision="f" * 40),
        lambda proof: proof["revision_binding"].update(sftp_sha="f" * 40),
        lambda proof: proof["closed_boundary_binding"].update(same_container_id=False),
        lambda proof: proof["closed_boundary_binding"].update(
            server_client_sha_distinct=False
        ),
        lambda proof: proof.pop("closed_boundary_binding"),
        lambda proof: proof["authentication_audit"].update(added_count=1),
        lambda proof: proof["protocol"].update(password_submitted=True),
    ],
)
def test_host_banner_rejects_tampered_closed_boundary_chain_before_network_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: Any,
) -> None:
    module = _module()
    sftp = _container(
        "agentium-sftp",
        container_id=SFTP_ID,
        image_id=SFTP_IMAGE,
        running=True,
    )
    client = _container(
        "agentium-backend",
        container_id=CLIENT_ID,
        image_id=CLIENT_IMAGE,
        running=True,
    )
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda name: deepcopy(sftp if name == "agentium-sftp" else client),
    )
    monkeypatch.setattr(module, "_image_revision", _revision_for_image)
    proof = _docker_protocol_proof()
    mutation(proof)
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(proof), encoding="utf-8")
    validation_path = tmp_path / "validation.json"
    validation_path.write_text(json.dumps(_validation_proof()), encoding="utf-8")
    validation_path.chmod(0o600)
    monkeypatch.setattr(
        module,
        "_published_sftp_port",
        lambda _payload: pytest.fail("must reject before opening the transport"),
    )
    with pytest.raises(module.SFTPBoundaryError, match="proof"):
        module.build_host_banner_contract(
            sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            protocol_proof_path=path,
            validation_proof_path=validation_path,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda proof: proof.update(candidate_sha="f" * 40),
        lambda proof: proof.update(deployment_id="another-deployment"),
        lambda proof: proof.update(result="failed"),
        lambda proof: proof.update(kind="untrusted_validation"),
        lambda proof: proof["checks"].update(storage_preserved=False),
        lambda proof: proof["checks"].update(sftp_closed_boundary=False),
        lambda proof: proof["evidence"]["sftp_closed_after"].update(
            sha256="9" * 64
        ),
        lambda proof: proof.pop("evidence"),
    ],
)
def test_host_banner_rejects_unbound_or_tampered_validation_before_runtime_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: Any,
) -> None:
    module = _module()
    validation = _validation_proof()
    mutation(validation)
    validation_path = tmp_path / "validation.json"
    validation_path.write_text(json.dumps(validation), encoding="utf-8")
    validation_path.chmod(0o600)
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(_docker_protocol_proof()), encoding="utf-8")
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda _name: pytest.fail("must reject before inspecting runtime containers"),
    )

    with pytest.raises(module.SFTPBoundaryError, match="safe deployment validation"):
        module.build_host_banner_contract(
            sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            protocol_proof_path=protocol_path,
            validation_proof_path=validation_path,
        )


def test_host_banner_rejects_validation_proof_with_non_private_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    validation_path = tmp_path / "validation.json"
    validation_path.write_text(json.dumps(_validation_proof()), encoding="utf-8")
    validation_path.chmod(0o644)
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(_docker_protocol_proof()), encoding="utf-8")
    monkeypatch.setattr(
        module,
        "_docker_inspect",
        lambda _name: pytest.fail("must reject before inspecting runtime containers"),
    )

    with pytest.raises(module.SFTPBoundaryError, match="proof file is unsafe"):
        module.build_host_banner_contract(
            sha=SHA,
            sftp_sha=SFTP_SHA,
            deployment_id=DEPLOYMENT_ID,
            protocol_proof_path=protocol_path,
            validation_proof_path=validation_path,
        )


def test_atomic_output_is_private_and_fsyncs_file_and_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    output = tmp_path / "sftp-proof.json"
    synced_modes: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(descriptor: int) -> None:
        synced_modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(module.os, "fsync", recording_fsync)
    module._write_json({"result": "passed"}, str(output))

    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text(encoding="utf-8")) == {"result": "passed"}
    assert any(stat.S_ISREG(mode) for mode in synced_modes)
    assert any(stat.S_ISDIR(mode) for mode in synced_modes)


def test_validation_ready_output_is_private_canonical_json(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "runtime-ready.json"

    module._write_canonical_json({"z": 1, "a": {"b": False}}, str(output))

    assert output.stat().st_mode & 0o777 == 0o600
    assert output.read_bytes() == b'{"a":{"b":false},"z":1}\n'


def test_cli_accepts_no_sftp_credential_or_network_identity_argument() -> None:
    module = _module()
    parser = module._parser()
    option_strings: set[str] = set()
    for action in parser._actions:
        option_strings.update(action.option_strings)
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            for subparser in choices.values():
                for child_action in subparser._actions:
                    option_strings.update(child_action.option_strings)
    forbidden = ("password", "username", "access", "credential", "host", "ip", "key")
    assert not any(
        token in option.lower()
        for option in option_strings
        for token in forbidden
    )


@pytest.mark.parametrize(
    ("command", "extra"),
    [
        ("closed-boundary", ["--expected-secure-source", EXPECTED_SECURE_SOURCE]),
        ("docker-protocol", ["--closed-proof", "/private/closed.json"]),
        (
            "rollback-continuity",
            [
                "--candidate-sha",
                SHA,
                "--closed-proof",
                "/private/rollback-closed.json",
                "--expected-secure-source",
                EXPECTED_SECURE_SOURCE,
            ],
        ),
        (
            "host-banner",
            [
                "--protocol-proof",
                "/private/protocol.json",
                "--validation-proof",
                "/private/validation.json",
            ],
        ),
    ],
)
def test_boundary_commands_require_explicit_sftp_sha(
    command: str, extra: list[str]
) -> None:
    module = _module()
    common = [
        command,
        "--sha",
        SHA,
        "--deployment-id",
        DEPLOYMENT_ID,
        *extra,
    ]
    with pytest.raises(SystemExit):
        module._parser().parse_args(common)
    parsed = module._parser().parse_args(
        [
            command,
            "--sha",
            SHA,
            "--sftp-sha",
            SFTP_SHA,
            "--deployment-id",
            DEPLOYMENT_ID,
            *extra,
        ]
    )
    assert parsed.sftp_sha == SFTP_SHA


@pytest.mark.parametrize("command", ["protocol-client", "db-auth-inventory"])
def test_candidate_only_commands_reject_sftp_sha(command: str) -> None:
    module = _module()
    with pytest.raises(SystemExit):
        module._parser().parse_args(
            [
                command,
                "--sha",
                SHA,
                "--sftp-sha",
                SFTP_SHA,
                "--deployment-id",
                DEPLOYMENT_ID,
            ]
        )


def test_docker_protocol_cli_requires_closed_proof() -> None:
    module = _module()
    parser = module._parser()
    common = [
        "docker-protocol",
        "--sha",
        SHA,
        "--sftp-sha",
        SFTP_SHA,
        "--deployment-id",
        DEPLOYMENT_ID,
    ]
    with pytest.raises(SystemExit):
        parser.parse_args(common)
    parsed = parser.parse_args(common + ["--closed-proof", "/private/proof.json"])
    assert parsed.closed_proof == "/private/proof.json"


def test_closed_boundary_cli_requires_and_transmits_expected_secure_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    common = [
        "closed-boundary",
        "--sha",
        SHA,
        "--sftp-sha",
        SFTP_SHA,
        "--deployment-id",
        DEPLOYMENT_ID,
    ]
    with pytest.raises(SystemExit):
        module._parser().parse_args(common)

    captured: dict[str, Any] = {}

    def fake_build(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"result": "passed"}

    monkeypatch.setattr(module, "build_closed_boundary_contract", fake_build)
    monkeypatch.setattr(module, "_write_json", lambda *_args: None)
    result = module.main(
        common + ["--expected-secure-source", EXPECTED_SECURE_SOURCE]
    )

    assert result == 0
    assert captured == {
        "sha": SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "expected_secure_source": EXPECTED_SECURE_SOURCE,
    }


def test_rollback_continuity_cli_requires_and_transmits_complete_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    common = [
        "rollback-continuity",
        "--sha",
        PREVIOUS_SHA,
        "--candidate-sha",
        SHA,
        "--sftp-sha",
        SFTP_SHA,
        "--deployment-id",
        DEPLOYMENT_ID,
    ]
    parser = module._parser()
    with pytest.raises(SystemExit):
        parser.parse_args(common)
    with pytest.raises(SystemExit):
        parser.parse_args(
            common + ["--closed-proof", "/private/rollback-closed.json"]
        )

    captured: dict[str, Any] = {}

    def fake_build(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"result": "passed"}

    monkeypatch.setattr(module, "build_rollback_continuity_contract", fake_build)
    monkeypatch.setattr(module, "_write_json", lambda *_args: None)
    result = module.main(
        common
        + [
            "--closed-proof",
            "/private/rollback-closed.json",
            "--expected-secure-source",
            EXPECTED_SECURE_SOURCE,
            "--output",
            "/private/rollback-continuity.json",
        ]
    )

    assert result == 0
    assert captured == {
        "sha": PREVIOUS_SHA,
        "candidate_sha": SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "closed_proof_path": Path("/private/rollback-closed.json"),
        "expected_secure_source": EXPECTED_SECURE_SOURCE,
    }


def test_host_banner_cli_requires_protocol_and_validation_proofs() -> None:
    module = _module()
    parser = module._parser()
    common = [
        "host-banner",
        "--sha",
        SHA,
        "--sftp-sha",
        SFTP_SHA,
        "--deployment-id",
        DEPLOYMENT_ID,
    ]
    with pytest.raises(SystemExit):
        parser.parse_args(common)
    with pytest.raises(SystemExit):
        parser.parse_args(common + ["--protocol-proof", "/private/protocol.json"])
    with pytest.raises(SystemExit):
        parser.parse_args(common + ["--validation-proof", "/private/validation.json"])
    parsed = parser.parse_args(
        common
        + [
            "--protocol-proof",
            "/private/protocol.json",
            "--validation-proof",
            "/private/validation.json",
        ]
    )
    assert parsed.protocol_proof == "/private/protocol.json"
    assert parsed.validation_proof == "/private/validation.json"


def test_validation_ready_cli_requires_and_transmits_complete_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    common = [
        "validation-ready",
        "--live-sha",
        LIVE_SHA,
        "--release-a-sha",
        SHA,
        "--sftp-sha",
        SFTP_SHA,
        "--deployment-id",
        DEPLOYMENT_ID,
    ]
    with pytest.raises(SystemExit):
        module._parser().parse_args(common)

    captured: dict[str, Any] = {}
    written: list[tuple[dict[str, Any], str]] = []

    def fake_build(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"result": "passed"}

    monkeypatch.setattr(module, "build_validation_ready_contract", fake_build)
    monkeypatch.setattr(
        module,
        "_write_canonical_json",
        lambda payload, destination: written.append((payload, destination)),
    )
    monkeypatch.setattr(
        module,
        "_write_json",
        lambda *_args: pytest.fail("runtime-ready must use canonical JSON"),
    )
    result = module.main(
        common
        + [
            "--expected-secure-source",
            RELEASE_A_SECURE_SOURCE,
            "--output",
            "/private/runtime-ready.json",
        ]
    )

    assert result == 0
    assert captured == {
        "live_sha": LIVE_SHA,
        "release_a_sha": SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "expected_secure_source": RELEASE_A_SECURE_SOURCE,
    }
    assert written == [
        ({"result": "passed"}, "/private/runtime-ready.json")
    ]


def test_verify_runtime_identity_live_cli_is_strict_and_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    common = [
        "verify-runtime-identity-live",
        "--runtime-proof",
        "/private/runtime-ready.json",
        "--live-sha",
        LIVE_SHA,
        "--release-a-sha",
        SHA,
        "--sftp-sha",
        SFTP_SHA,
        "--deployment-id",
        DEPLOYMENT_ID,
        "--expected-secure-source",
        RELEASE_A_SECURE_SOURCE,
        "--expected-secure-mode",
        "rw",
        "--expected-restart",
        "historical",
        "--runtime-state",
        "/private/runtime-state.tsv",
        "--allow-paused",
    ]
    captured: dict[str, Any] = {}
    written: list[tuple[dict[str, Any], str]] = []

    monkeypatch.setattr(
        module,
        "verify_runtime_identity_live_contract",
        lambda **kwargs: captured.update(kwargs) or {"result": "passed"},
    )
    monkeypatch.setattr(
        module,
        "_write_canonical_json",
        lambda payload, destination: written.append((payload, destination)),
    )
    monkeypatch.setattr(
        module,
        "_write_json",
        lambda *_args: pytest.fail("live runtime identity must use canonical JSON"),
    )

    assert module.main([*common, "--output", "/private/live-identity.json"]) == 0
    assert captured == {
        "receipt_path": Path("/private/runtime-ready.json"),
        "live_sha": LIVE_SHA,
        "release_a_sha": SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "expected_secure_source": RELEASE_A_SECURE_SOURCE,
        "expected_secure_mode": "rw",
        "expected_restart": "historical",
        "runtime_state_path": Path("/private/runtime-state.tsv"),
        "allow_paused": True,
    }
    assert written == [
        ({"result": "passed"}, "/private/live-identity.json")
    ]
