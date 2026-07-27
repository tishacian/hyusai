"""Adversarial tests for the Release A positive SFTP credential lifecycle."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "agentium_release_a_sftp_positive_canary.py"

RELEASE_A_SHA = "a" * 40
SFTP_SHA = "b" * 40
LIVE_SHA = "e" * 40
DEPLOYMENT_ID = "release-a-sftp-positive-001"
IMAGE_ID = "sha256:" + "c" * 64
RUNTIME_ID = "d" * 64
HOST = "127.0.0.1"
EXPECTED_HOSTNAME = "private-sftp.agentium.invalid"
USERNAME = "ra1_disposable-release-a-user"
PASSWORD = "one-use-private-password"
FINGERPRINT = "SHA256:" + base64.b64encode(b"k" * 32).decode("ascii").rstrip("=")
OTHER_FINGERPRINT = (
    "SHA256:" + base64.b64encode(b"z" * 32).decode("ascii").rstrip("=")
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "agentium_release_a_sftp_positive_canary_test", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module() -> ModuleType:
    return _load()


def _stamp(seconds: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat().replace(
        "+00:00", "Z"
    )


def _files(tmp_path: Path) -> tuple[Path, Path]:
    password = tmp_path / "sftp-password"
    password.write_text(PASSWORD + "\n", encoding="utf-8")
    password.chmod(0o600)
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text(
        f"{HOST} ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestOnly\n",
        encoding="utf-8",
    )
    known_hosts.chmod(0o600)
    return password, known_hosts


def _runtime_ready(module: ModuleType, tmp_path: Path) -> Path:
    started_at = _stamp(-2)
    ready_at = _stamp(-1)
    hostname_sha256 = hashlib.sha256(EXPECTED_HOSTNAME.encode("ascii")).hexdigest()
    runtime_identity = module._runtime_identity_fingerprint(
        live_sha=LIVE_SHA,
        release_a_sha=RELEASE_A_SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        hostname_sha256=hostname_sha256,
        sftp_container_id=RUNTIME_ID,
        sftp_image_id=IMAGE_ID,
        sftp_port=2223,
        sftp_started_at=started_at,
    )
    gate = {
        "ipv4_input": True,
        "ipv4_docker_user": True,
        "ipv6_input": True,
        "ipv6_docker_user": True,
    }
    receipt = {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-runtime-ready",
        "result": "passed",
        "live_sha": LIVE_SHA,
        "release_a_sha": RELEASE_A_SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "hostname_sha256": hostname_sha256,
        "sftp_container_id": RUNTIME_ID,
        "sftp_image_id": IMAGE_ID,
        "sftp_port": 2223,
        "sftp_started_at": started_at,
        "image_revision": SFTP_SHA,
        "runtime_identity_sha256": runtime_identity,
        "host_key_fingerprint": FINGERPRINT,
        "state": "running",
        "health_status": "healthy",
        "ingress_closed": True,
        "restart_disabled": True,
        "restart_policy_disabled": True,
        "secure_deposit_mode": "ro",
        "secure_deposit_source": "/dev/sdc",
        "external_established_connection_count": 0,
        "ingress_gate": gate,
        "published_transport": {
            "protocol": "tcp",
            "container_port": 2222,
            "host_port": 2223,
            "binding_count": 1,
            "binding_sha256": hashlib.sha256(b"binding").hexdigest(),
            "listener_count": 1,
            "established_connection_count_before": 0,
            "established_connection_count_after": 0,
            "external_established_connection_count": 0,
            "ssh_v2_identification_validated": True,
            "connection_closed_before_authentication": True,
            "raw_identification_serialized": False,
        },
        "secure_deposit": {
            "source_matches_dev_sdc": True,
            "source_device_sha256": hashlib.sha256(b"/dev/sdc").hexdigest(),
            "autonomous_mountpoint": True,
            "host_read_only": True,
            "namespace_autonomous_mountpoint": True,
            "namespace_read_only": True,
            "device_id": 12345,
        },
        "host_key": {
            "algorithm": "ssh-ed25519",
            "fingerprint": FINGERPRINT,
            "fingerprint_sha256": hashlib.sha256(
                FINGERPRINT.encode("ascii")
            ).hexdigest(),
            "present": True,
            "nonempty": True,
            "regular_file": True,
            "symlink": False,
        },
        "credentials_used": False,
        "authentication_attempted": False,
        "sftp_subsystem_requested": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
        "raw_identification_serialized": False,
        "ready_at": ready_at,
    }
    path = tmp_path / "runtime-ready.json"
    path.write_bytes(module._canonical_json_bytes(receipt))
    path.chmod(0o600)
    return path


def _arguments(tmp_path: Path, *, output_name: str = "positive.json") -> dict[str, Any]:
    module = _load()
    password, known_hosts = _files(tmp_path)
    return {
        "live_sha": LIVE_SHA,
        "release_a_sha": RELEASE_A_SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "sftp_image_id": IMAGE_ID,
        "sftp_runtime_id": RUNTIME_ID,
        "host": HOST,
        "expected_hostname": EXPECTED_HOSTNAME,
        "port": 2223,
        "username": USERNAME,
        "password_file": str(password),
        "known_hosts_file": str(known_hosts),
        "runtime_ready_receipt_file": str(_runtime_ready(module, tmp_path)),
        "expected_host_key_fingerprint": FINGERPRINT,
        "output": str(tmp_path / output_name),
        "timeout": 3.0,
    }


class _PermissionDeniedError(Exception):
    pass


class _ServerKey:
    def __init__(self, fingerprint: str) -> None:
        self._fingerprint = fingerprint

    def get_fingerprint(self, algorithm: str) -> str:
        assert algorithm == "sha256"
        return self._fingerprint

    def get_algorithm(self) -> str:
        return "ssh-ed25519"


def _fake_asyncssh(
    monkeypatch: pytest.MonkeyPatch,
    *,
    connect_outcome: str = "success",
    fingerprint: str = FINGERPRINT,
) -> tuple[list[tuple[str, Any]], list[dict[str, Any]]]:
    operations: list[tuple[str, Any]] = []
    connections: list[dict[str, Any]] = []

    class SFTPContext:
        async def __aenter__(self) -> Any:
            if connect_outcome == "subsystem_failure":
                raise RuntimeError(f"subsystem rejected for {USERNAME}@{HOST}")
            operations.append(("sftp_started", None))
            return self

        async def __aexit__(self, *_args: Any) -> None:
            operations.append(("sftp_closed", None))

        async def getcwd(self) -> str:
            operations.append(("getcwd", None))
            return "/private/remote/value-never-serialized"

        async def stat(self, path: str) -> object:
            operations.append(("stat", path))
            return object()

    class Connection:
        async def __aenter__(self) -> Any:
            if connect_outcome == "auth_failure":
                raise _PermissionDeniedError(f"denied {USERNAME}@{HOST} with {PASSWORD}")
            if connect_outcome == "timeout":
                raise asyncio.TimeoutError(f"timeout for {USERNAME}@{HOST}")
            operations.append(("authenticated", None))
            return self

        async def __aexit__(self, *_args: Any) -> None:
            if connect_outcome == "accepted_exit_denied":
                raise _PermissionDeniedError("close failed after accepted auth")
            operations.append(("connection_closed", None))

        def get_server_host_key(self) -> _ServerKey:
            return _ServerKey(fingerprint)

        def start_sftp_client(self) -> SFTPContext:
            operations.append(("sftp_requested", None))
            return SFTPContext()

    def connect(host: str, **kwargs: Any) -> Connection:
        connections.append({"host": host, **kwargs})
        return Connection()

    async def get_server_host_key(**kwargs: Any) -> _ServerKey:
        operations.append(("host_key_probe", kwargs))
        return _ServerKey(fingerprint)

    monkeypatch.setitem(
        sys.modules,
        "asyncssh",
        SimpleNamespace(
            connect=connect,
            get_server_host_key=get_server_host_key,
            PermissionDenied=_PermissionDeniedError,
        ),
    )
    return operations, connections


def _assert_password_only_connection(connection: dict[str, Any]) -> None:
    assert connection["password"] == PASSWORD
    assert connection["known_hosts"].startswith(HOST.encode("utf-8"))
    assert connection["client_keys"] is None
    assert connection["client_certs"] == []
    assert connection["agent_path"] is None
    assert connection["pkcs11_provider"] is None
    assert connection["gss_kex"] is False
    assert connection["gss_auth"] is False
    assert connection["host_based_auth"] is False
    assert connection["public_key_auth"] is False
    assert connection["kbdint_auth"] is False
    assert connection["password_auth"] is True
    assert connection["preferred_auth"] == ("password",)
    assert connection["disable_trivial_auth"] is True
    assert 1 <= connection["connect_timeout"] <= 30
    assert 1 <= connection["login_timeout"] <= 30
    assert connection["config"] is None
    assert connection["server_host_key_algs"] == ["ssh-ed25519"]


def _ledger_receipt(
    module: ModuleType,
    tmp_path: Path,
    *,
    positive: dict[str, Any],
    post_revoke: dict[str, Any],
) -> Path:
    auth_started = module._parse_timestamp(positive["auth_started_at"])
    denial_started = module._parse_timestamp(
        post_revoke["revocation_check_started_at"]
    )
    denial_completed = module._parse_timestamp(post_revoke["completed_at"])

    def event(name: str, event_type: str, occurred_at: datetime) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "event_id_sha256": hashlib.sha256(f"{name}-id".encode()).hexdigest(),
            "event_digest_sha256": hashlib.sha256(
                f"{name}-digest".encode()
            ).hexdigest(),
            "count": 1,
            "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
        }

    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-postgres-ledger",
        "result": "passed",
        "live_sha": LIVE_SHA,
        "release_a_sha": RELEASE_A_SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "hostname_sha256": positive["hostname_sha256"],
        "workspace_id_sha256": module._sha256_domain(
            b"agentium-release-a-sftp-workspace-id-v1", b"workspace-private"
        ),
        "link_id_sha256": module._sha256_domain(
            b"agentium-release-a-sftp-link-id-v1", b"link-private"
        ),
        "access_id_sha256": positive["access_id_sha256"],
        "credential_fingerprint_sha256": positive[
            "credential_fingerprint_sha256"
        ],
        "sftp_container_id": RUNTIME_ID,
        "sftp_image_id": IMAGE_ID,
        "sftp_port": 2223,
        "runtime_identity_sha256": positive["runtime_identity_sha256"],
        "link_status": "revoked",
        "auth_failed_reason": "inactive_or_expired",
        "remaining_active_link_count": 0,
        "active_sftp_session_count": 0,
        "deposit_file_delta_count": 0,
        "audits": {
            "created": event(
                "created",
                "deposit.link.created",
                auth_started - timedelta(milliseconds=1),
            ),
            "auth_success": event(
                "auth-success", "deposit.sftp.auth.success", auth_started
            ),
            "revoked": event(
                "revoked", "deposit.link.revoked", denial_started
            ),
            "auth_failed_inactive": event(
                "auth-failed", "deposit.sftp.auth.failed", denial_completed
            ),
        },
        "binding_sha256": "0" * 64,
        "collected_at": _stamp(),
    }
    payload["binding_sha256"] = module._ledger_binding_fingerprint(payload)
    path = tmp_path / "postgres-ledger.json"
    path.write_bytes(module._canonical_json_bytes(payload))
    path.chmod(0o600)
    return path


def _finalize_arguments(
    tmp_path: Path,
    *,
    positive_path: Path,
    post_revoke_path: Path,
    ledger_path: Path,
    runtime_ready_path: Path,
) -> dict[str, Any]:
    return {
        "live_sha": LIVE_SHA,
        "release_a_sha": RELEASE_A_SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "sftp_image_id": IMAGE_ID,
        "sftp_runtime_id": RUNTIME_ID,
        "sftp_port": 2223,
        "expected_hostname": EXPECTED_HOSTNAME,
        "expected_host_key_fingerprint": FINGERPRINT,
        "runtime_ready_receipt_file": str(runtime_ready_path),
        "positive_evidence_file": str(positive_path),
        "post_revoke_evidence_file": str(post_revoke_path),
        "ledger_file": str(ledger_path),
        "output": str(tmp_path / "sftp-positive-auth.artifact"),
    }


def _complete_lifecycle(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    positive = module.produce_evidence(**arguments)
    positive_path = Path(arguments["output"])
    _fake_asyncssh(monkeypatch, connect_outcome="auth_failure")
    post_path = tmp_path / "post-revoke.json"
    post = module.verify_post_revoke(
        **{
            **arguments,
            "positive_evidence_file": str(positive_path),
            "output": str(post_path),
        }
    )
    ledger_path = _ledger_receipt(
        module,
        tmp_path,
        positive=positive,
        post_revoke=post,
    )
    final_arguments = _finalize_arguments(
        tmp_path,
        positive_path=positive_path,
        post_revoke_path=post_path,
        ledger_path=ledger_path,
        runtime_ready_path=Path(arguments["runtime_ready_receipt_file"]),
    )
    artifact = module.finalize_evidence(**final_arguments)
    return artifact, final_arguments


def test_positive_probe_is_password_only_content_free_and_schema_closed(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operations, connections = _fake_asyncssh(monkeypatch)
    monkeypatch.setenv("SSH_AUTH_SOCK", "/private/agent/socket")
    arguments = _arguments(tmp_path)

    payload = module.produce_evidence(**arguments)

    assert [name for name, _value in operations] == [
        "authenticated",
        "sftp_requested",
        "sftp_started",
        "getcwd",
        "stat",
        "sftp_closed",
        "connection_closed",
    ]
    assert operations[4] == ("stat", "/")
    assert len(connections) == 1
    assert connections[0]["host"] == HOST
    assert connections[0]["username"] == USERNAME
    _assert_password_only_connection(connections[0])

    assert frozenset(payload) == module._POSITIVE_KEYS
    assert frozenset(payload["checks"]) == module._POSITIVE_CHECK_KEYS
    assert payload["checks"]["directory_enumeration_operations"] == 0
    assert payload["checks"]["content_read_operations"] == 0
    assert payload["checks"]["mutation_operations"] == 0
    assert payload["release_a_sha"] == RELEASE_A_SHA
    assert payload["sftp_sha"] == SFTP_SHA
    assert payload["deployment_id"] == DEPLOYMENT_ID
    assert payload["host_key_fingerprint"] == FINGERPRINT
    assert len(payload["hostname_sha256"]) == 64
    assert len(payload["credential_fingerprint_sha256"]) == 64
    assert payload["sftp_image_id"] == IMAGE_ID
    assert payload["sftp_container_id"] == RUNTIME_ID
    assert len(payload["runtime_identity_sha256"]) == 64

    output = Path(arguments["output"])
    raw_output = output.read_text(encoding="utf-8")
    assert json.loads(raw_output) == payload
    for forbidden in (HOST, EXPECTED_HOSTNAME, USERNAME, PASSWORD):
        assert forbidden not in raw_output
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_crash_after_committed_auth_audits_replays_once_with_valid_final_chronology(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path)
    positive_events: dict[str, str] = {}
    positive_calls = 0

    async def positive_probe(**_kwargs: Any) -> None:
        nonlocal positive_calls
        positive_calls += 1
        positive_events.setdefault("deterministic-positive-audit", module._completed_at())
        if positive_calls == 1:
            raise RuntimeError("simulated crash after server audit commit")

    monkeypatch.setattr(module, "_positive_sftp_probe", positive_probe)
    with pytest.raises(module.SFTPPositiveCanaryError):
        module.produce_evidence(**arguments)

    positive_intent_path = Path(f"{arguments['output']}.intent")
    assert positive_intent_path.exists()
    assert stat.S_IMODE(positive_intent_path.stat().st_mode) == 0o600
    positive_intent = json.loads(positive_intent_path.read_text(encoding="utf-8"))
    assert positive_intent["phase"] == "positive"
    assert USERNAME not in positive_intent_path.read_text(encoding="utf-8")
    assert PASSWORD not in positive_intent_path.read_text(encoding="utf-8")

    positive = module.produce_evidence(**arguments)
    assert positive_calls == 2
    assert len(positive_events) == 1
    assert positive["auth_started_at"] == positive_intent["started_at"]
    positive_audit_at = module._parse_timestamp(next(iter(positive_events.values())))
    assert (
        module._parse_timestamp(positive["auth_started_at"])
        <= positive_audit_at
        <= module._parse_timestamp(positive["auth_completed_at"])
    )

    post_path = tmp_path / "post-revoke-replayed.json"
    post_arguments = {
        **arguments,
        "positive_evidence_file": arguments["output"],
        "output": str(post_path),
    }
    denial_events: dict[str, str] = {}
    denial_calls = 0

    async def denial_probe(**_kwargs: Any) -> None:
        nonlocal denial_calls
        denial_calls += 1
        denial_events.setdefault("deterministic-denial-audit", module._completed_at())
        if denial_calls == 1:
            raise RuntimeError("simulated crash after denial audit commit")

    monkeypatch.setattr(module, "_post_revoke_probe", denial_probe)
    with pytest.raises(module.SFTPPositiveCanaryError):
        module.verify_post_revoke(**post_arguments)

    denial_intent_path = Path(f"{post_path}.intent")
    denial_intent = json.loads(denial_intent_path.read_text(encoding="utf-8"))
    post_revoke = module.verify_post_revoke(**post_arguments)
    assert denial_calls == 2
    assert len(denial_events) == 1
    assert (
        post_revoke["revocation_check_started_at"]
        == denial_intent["started_at"]
    )
    denial_audit_at = module._parse_timestamp(next(iter(denial_events.values())))
    assert (
        module._parse_timestamp(post_revoke["revocation_check_started_at"])
        <= denial_audit_at
        <= module._parse_timestamp(post_revoke["completed_at"])
    )

    ledger_path = _ledger_receipt(
        module,
        tmp_path,
        positive=positive,
        post_revoke=post_revoke,
    )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["audits"]["auth_success"]["occurred_at"] = next(
        iter(positive_events.values())
    )
    ledger["audits"]["auth_failed_inactive"]["occurred_at"] = next(
        iter(denial_events.values())
    )
    ledger["binding_sha256"] = module._ledger_binding_fingerprint(ledger)
    ledger_path.write_bytes(module._canonical_json_bytes(ledger))

    artifact = module.finalize_evidence(
        **_finalize_arguments(
            tmp_path,
            positive_path=Path(arguments["output"]),
            post_revoke_path=post_path,
            ledger_path=ledger_path,
            runtime_ready_path=Path(arguments["runtime_ready_receipt_file"]),
        )
    )
    assert {
        key: artifact["audit_summary"][key]
        for key in (
            "created_count",
            "auth_success_count",
            "revoked_count",
            "auth_failed_inactive_count",
        )
    } == {
        "created_count": 1,
        "auth_success_count": 1,
        "revoked_count": 1,
        "auth_failed_inactive_count": 1,
    }


def test_asyncssh_default_keys_and_agent_are_explicitly_disabled(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "home"
    ssh_dir = fake_home / ".ssh"
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "id_ed25519").write_text("must-never-be-loaded", encoding="utf-8")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("SSH_AUTH_SOCK", str(tmp_path / "must-never-be-used.sock"))
    _operations, connections = _fake_asyncssh(monkeypatch)

    module.produce_evidence(**_arguments(tmp_path))

    assert len(connections) == 1
    assert connections[0]["client_keys"] is None
    assert connections[0]["agent_path"] is None
    assert connections[0]["public_key_auth"] is False
    assert connections[0]["host_based_auth"] is False
    assert connections[0]["gss_auth"] is False
    assert connections[0]["gss_kex"] is False
    assert connections[0]["preferred_auth"] == ("password",)


@pytest.mark.parametrize(
    ("outcome", "fingerprint"),
    [
        ("auth_failure", FINGERPRINT),
        ("subsystem_failure", FINGERPRINT),
        ("success", OTHER_FINGERPRINT),
    ],
)
def test_positive_probe_fails_closed_before_publication(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    outcome: str,
    fingerprint: str,
) -> None:
    _fake_asyncssh(
        monkeypatch,
        connect_outcome=outcome,
        fingerprint=fingerprint,
    )
    arguments = _arguments(tmp_path)

    with pytest.raises(module.SFTPPositiveCanaryError):
        module.produce_evidence(**arguments)

    assert not Path(arguments["output"]).exists()


def test_post_revoke_proves_auth_denied_without_opening_sftp(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_asyncssh(monkeypatch)
    positive_arguments = _arguments(tmp_path)
    positive = module.produce_evidence(**positive_arguments)
    positive_path = Path(positive_arguments["output"])

    operations, connections = _fake_asyncssh(
        monkeypatch,
        connect_outcome="auth_failure",
    )
    lifecycle_arguments = {
        **positive_arguments,
        "positive_evidence_file": str(positive_path),
        "output": str(tmp_path / "lifecycle.json"),
    }
    lifecycle = module.verify_post_revoke(**lifecycle_arguments)

    assert frozenset(lifecycle) == module._POST_REVOKE_KEYS
    assert lifecycle["result"] == "passed"
    assert lifecycle["authentication_denied"] is True
    assert lifecycle["sftp_subsystem_requested_after_revocation"] is False
    assert lifecycle["positive_completed_at"] == positive["auth_completed_at"]
    assert [name for name, _value in operations] == ["host_key_probe"]
    assert len(connections) == 1
    _assert_password_only_connection(connections[0])
    raw_output = Path(lifecycle_arguments["output"]).read_text(encoding="utf-8")
    for forbidden in (HOST, EXPECTED_HOSTNAME, USERNAME, PASSWORD):
        assert forbidden not in raw_output


def test_post_revoke_rejects_credential_which_still_authenticates(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_asyncssh(monkeypatch)
    positive_arguments = _arguments(tmp_path)
    module.produce_evidence(**positive_arguments)
    operations, _connections = _fake_asyncssh(monkeypatch)
    lifecycle_output = tmp_path / "lifecycle.json"

    with pytest.raises(module.SFTPPositiveCanaryError, match="was accepted"):
        module.verify_post_revoke(
            **{
                **positive_arguments,
                "positive_evidence_file": positive_arguments["output"],
                "output": str(lifecycle_output),
            }
        )

    assert "sftp_requested" not in [name for name, _value in operations]
    assert not lifecycle_output.exists()


def test_final_artifact_covers_ready_auth_revoke_denial_and_ledger(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact, arguments = _complete_lifecycle(module, monkeypatch, tmp_path)

    assert frozenset(artifact) == module._LIFECYCLE_KEYS
    assert artifact["kind"] == "sftp-positive-auth.artifact"
    assert artifact["authentication_result"] == "passed"
    assert artifact["subsystem_result"] == "passed"
    assert artifact["revoke_result"] == "passed"
    assert artifact["post_revoke_authentication_result"] == "denied_inactive"
    assert artifact["link_status"] == "revoked"
    assert artifact["remaining_active_link_count"] == 0
    assert artifact["active_sftp_session_count"] == 0
    assert artifact["deposit_file_delta_count"] == 0
    assert artifact["sftp_container_id"] == RUNTIME_ID
    assert artifact["sftp_image_id"] == IMAGE_ID
    assert artifact["image_revision"] == SFTP_SHA
    assert artifact["sftp_port"] == 2223
    assert artifact["secure_deposit_source"] == "/dev/sdc"
    assert artifact["secure_deposit_mode"] == "ro"
    assert artifact["restart_policy_disabled"] is True
    assert artifact["ingress_gate"] == {
        "ipv4_input": True,
        "ipv4_docker_user": True,
        "ipv6_input": True,
        "ipv6_docker_user": True,
    }
    assert artifact["audit_summary"]["created_count"] == 1
    assert artifact["audit_summary"]["auth_success_count"] == 1
    assert artifact["audit_summary"]["revoked_count"] == 1
    assert artifact["audit_summary"]["auth_failed_inactive_count"] == 1

    artifact_path = Path(arguments["output"])
    raw = artifact_path.read_bytes()
    assert raw.endswith(b"\n")
    for forbidden in (HOST, EXPECTED_HOSTNAME, USERNAME, PASSWORD):
        assert forbidden.encode() not in raw
    summary = module.validate_final_artifact_bytes(
        raw,
        expected_live_sha=LIVE_SHA,
        expected_release_a_sha=RELEASE_A_SHA,
        expected_sftp_sha=SFTP_SHA,
        expected_deployment_id=DEPLOYMENT_ID,
        expected_hostname_sha256=hashlib.sha256(
            EXPECTED_HOSTNAME.encode("ascii")
        ).hexdigest(),
        runtime_ready_receipt_raw=Path(
            arguments["runtime_ready_receipt_file"]
        ).read_bytes(),
        postgres_ledger_receipt_raw=Path(arguments["ledger_file"]).read_bytes(),
        expected_completed_at=artifact["completed_at"],
    )
    assert summary["kind"] == "sftp-positive-auth.artifact"
    assert summary["completed_at"] == artifact["completed_at"]


def test_credential_fingerprint_is_exactly_deployment_access_and_password_domain(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_asyncssh(monkeypatch)
    payload = module.produce_evidence(**_arguments(tmp_path))
    assert payload["credential_fingerprint_sha256"] == module._sha256_parts(
        b"agentium-release-a-sftp-credential-v1",
        DEPLOYMENT_ID,
        USERNAME,
        PASSWORD.encode("utf-8"),
    )


def test_final_validator_rejects_noncanonical_or_non_newline_artifact(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact, arguments = _complete_lifecycle(module, monkeypatch, tmp_path)
    raw = module._canonical_json_bytes(artifact).rstrip(b"\n")

    with pytest.raises(module.SFTPPositiveCanaryError, match="not canonical"):
        module.validate_final_artifact_bytes(
            raw,
            expected_live_sha=LIVE_SHA,
            expected_release_a_sha=RELEASE_A_SHA,
            expected_sftp_sha=SFTP_SHA,
            expected_deployment_id=DEPLOYMENT_ID,
            expected_hostname_sha256=artifact["hostname_sha256"],
            runtime_ready_receipt_raw=Path(
                arguments["runtime_ready_receipt_file"]
            ).read_bytes(),
            postgres_ledger_receipt_raw=Path(arguments["ledger_file"]).read_bytes(),
        )


@pytest.mark.parametrize(
    "field", ["positive_evidence_sha256", "post_revoke_evidence_sha256"]
)
def test_final_validator_rejects_arbitrary_intermediate_proof_digest(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    artifact, arguments = _complete_lifecycle(module, monkeypatch, tmp_path)
    artifact[field] = "f" * 64

    with pytest.raises(module.SFTPPositiveCanaryError, match="proof digest"):
        module.validate_final_artifact_bytes(
            module._canonical_json_bytes(artifact),
            expected_live_sha=LIVE_SHA,
            expected_release_a_sha=RELEASE_A_SHA,
            expected_sftp_sha=SFTP_SHA,
            expected_deployment_id=DEPLOYMENT_ID,
            expected_hostname_sha256=artifact["hostname_sha256"],
            runtime_ready_receipt_raw=Path(
                arguments["runtime_ready_receipt_file"]
            ).read_bytes(),
            postgres_ledger_receipt_raw=Path(arguments["ledger_file"]).read_bytes(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sftp_container_id", "f" * 64),
        ("sftp_image_id", "sha256:" + "f" * 64),
        ("host_key_fingerprint", OTHER_FINGERPRINT),
        ("restart_policy_disabled", False),
    ],
)
def test_probe_rejects_runtime_ready_identity_or_gate_mismatch(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    ready_path = Path(arguments["runtime_ready_receipt_file"])
    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    ready[field] = value
    ready_path.write_bytes(module._canonical_json_bytes(ready))
    ready_path.chmod(0o600)

    with pytest.raises(module.SFTPPositiveCanaryError):
        module.produce_evidence(**arguments)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda ready: ready["published_transport"].update(binding_count=3),
        lambda ready: ready["secure_deposit"].update(
            source_device_sha256=hashlib.sha256(b"/dev/other").hexdigest()
        ),
    ],
)
def test_probe_rejects_runtime_receipt_outside_boundary_producer_contract(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: Any,
) -> None:
    operations, _connections = _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    ready_path = Path(arguments["runtime_ready_receipt_file"])
    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    mutation(ready)
    ready_path.write_bytes(module._canonical_json_bytes(ready))

    with pytest.raises(module.SFTPPositiveCanaryError):
        module.produce_evidence(**arguments)

    assert operations == []


def test_probe_rejects_old_runtime_ready_receipt_before_network(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operations, _connections = _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    ready_path = Path(arguments["runtime_ready_receipt_file"])
    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    ready["sftp_started_at"] = _stamp(-402)
    ready["ready_at"] = _stamp(-401)
    ready["runtime_identity_sha256"] = module._runtime_identity_fingerprint(
        live_sha=LIVE_SHA,
        release_a_sha=RELEASE_A_SHA,
        sftp_sha=SFTP_SHA,
        deployment_id=DEPLOYMENT_ID,
        hostname_sha256=ready["hostname_sha256"],
        sftp_container_id=RUNTIME_ID,
        sftp_image_id=IMAGE_ID,
        sftp_port=2223,
        sftp_started_at=ready["sftp_started_at"],
    )
    ready_path.write_bytes(module._canonical_json_bytes(ready))

    with pytest.raises(module.SFTPPositiveCanaryError, match="stale"):
        module.produce_evidence(**arguments)

    assert operations == []


@pytest.mark.parametrize("endpoint", ["127.0.0.2", "localhost", "10.0.0.1"])
def test_probe_requires_exact_loopback_endpoint_before_network(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    endpoint: str,
) -> None:
    operations, _connections = _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    arguments["host"] = endpoint

    with pytest.raises(module.SFTPPositiveCanaryError, match="loopback"):
        module.produce_evidence(**arguments)

    assert operations == []


def test_probe_rejects_non_reserved_business_principal_before_network(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    operations, _connections = _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    arguments["username"] = "ordinary-business-access"

    with pytest.raises(module.SFTPPositiveCanaryError, match="principal identity"):
        module.produce_evidence(**arguments)

    assert operations == []
    assert not Path(arguments["output"]).exists()
    assert not Path(f"{arguments['output']}.intent").exists()


def test_post_revoke_rejects_old_positive_proof_before_network(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    positive = module.produce_evidence(**arguments)
    stale_now = (
        module._parse_timestamp(positive["auth_completed_at"])
        + timedelta(seconds=module.MAX_POSITIVE_TO_REVOKE_SECONDS + 1)
    ).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(module, "_completed_at", lambda: stale_now)
    operations, _connections = _fake_asyncssh(
        monkeypatch, connect_outcome="auth_failure"
    )

    with pytest.raises(module.SFTPPositiveCanaryError, match="stale"):
        module.verify_post_revoke(
            **{
                **arguments,
                "positive_evidence_file": arguments["output"],
                "output": str(tmp_path / "post-revoke.json"),
            }
        )

    assert operations == []


def test_post_revoke_timeout_is_never_accepted_as_denial(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    module.produce_evidence(**arguments)
    _fake_asyncssh(monkeypatch, connect_outcome="timeout")
    output = tmp_path / "post-revoke.json"

    with pytest.raises(module.SFTPPositiveCanaryError):
        module.verify_post_revoke(
            **{
                **arguments,
                "positive_evidence_file": arguments["output"],
                "output": str(output),
            }
        )

    assert not output.exists()


def test_post_revoke_never_accepts_permission_denied_from_close_after_auth(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    module.produce_evidence(**arguments)
    _fake_asyncssh(monkeypatch, connect_outcome="accepted_exit_denied")
    output = tmp_path / "post-revoke.json"

    with pytest.raises(module.SFTPPositiveCanaryError, match="accepted before"):
        module.verify_post_revoke(
            **{
                **arguments,
                "positive_evidence_file": arguments["output"],
                "output": str(output),
            }
        )

    assert not output.exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda ledger: ledger.update(
                credential_fingerprint_sha256="f" * 64
            ),
            "ledger binding",
        ),
        (
            lambda ledger: ledger.update(deposit_file_delta_count=1),
            "ledger binding",
        ),
        (
            lambda ledger: ledger["audits"]["revoked"].update(
                occurred_at=ledger["audits"]["created"]["occurred_at"]
            ),
            "audit chronology",
        ),
        (
            lambda ledger: ledger.update(unexpected=True),
            "schema is not closed",
        ),
    ],
)
def test_finalize_rejects_mismatched_ledger_fingerprint_state_order_or_schema(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: Any,
    message: str,
) -> None:
    _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    positive = module.produce_evidence(**arguments)
    _fake_asyncssh(monkeypatch, connect_outcome="auth_failure")
    post_path = tmp_path / "post-revoke.json"
    post = module.verify_post_revoke(
        **{
            **arguments,
            "positive_evidence_file": arguments["output"],
            "output": str(post_path),
        }
    )
    ledger_path = _ledger_receipt(
        module, tmp_path, positive=positive, post_revoke=post
    )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    mutation(ledger)
    if "unexpected" not in ledger:
        ledger["binding_sha256"] = module._ledger_binding_fingerprint(ledger)
    ledger_path.write_bytes(module._canonical_json_bytes(ledger))
    final_arguments = _finalize_arguments(
        tmp_path,
        positive_path=Path(arguments["output"]),
        post_revoke_path=post_path,
        ledger_path=ledger_path,
        runtime_ready_path=Path(arguments["runtime_ready_receipt_file"]),
    )

    with pytest.raises(module.SFTPPositiveCanaryError, match=message):
        module.finalize_evidence(**final_arguments)

    assert not Path(final_arguments["output"]).exists()


def test_post_revoke_rejects_tampered_or_open_schema_positive_evidence(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_asyncssh(monkeypatch)
    positive_arguments = _arguments(tmp_path)
    payload = module.produce_evidence(**positive_arguments)
    payload["unexpected"] = True
    positive_path = Path(positive_arguments["output"])
    positive_path.write_bytes(module._canonical_json_bytes(payload))
    positive_path.chmod(0o600)
    monkeypatch.setattr(
        module,
        "_post_revoke_probe",
        lambda **_kwargs: pytest.fail("network must not run for open schema"),
    )

    with pytest.raises(module.SFTPPositiveCanaryError, match="schema is not closed"):
        module.verify_post_revoke(
            **{
                **positive_arguments,
                "positive_evidence_file": str(positive_path),
                "output": str(tmp_path / "lifecycle.json"),
            }
        )


@pytest.mark.parametrize("mode", [0o000, 0o440, 0o644])
def test_password_file_requires_exact_owner_private_mode(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mode: int,
) -> None:
    _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    Path(arguments["password_file"]).chmod(mode)

    with pytest.raises(module.SFTPPositiveCanaryError, match="mode is unsafe"):
        module.produce_evidence(**arguments)


def test_password_file_symlink_is_rejected_before_network(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    original = Path(arguments["password_file"])
    alias = tmp_path / "password-alias"
    alias.symlink_to(original)
    arguments["password_file"] = str(alias)

    with pytest.raises(module.SFTPPositiveCanaryError):
        module.produce_evidence(**arguments)


def test_password_change_during_descriptor_read_is_rejected(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    password, _known_hosts = _files(tmp_path)
    real_read = module.os.read
    changed = False

    def changing_read(descriptor: int, size: int) -> bytes:
        nonlocal changed
        value = real_read(descriptor, size)
        if value and not changed:
            changed = True
            password.write_text("different-private-password\n", encoding="utf-8")
            password.chmod(0o600)
        return value

    monkeypatch.setattr(module.os, "read", changing_read)
    with pytest.raises(module.SFTPPositiveCanaryError, match="changed during read"):
        module._read_password(str(password))


def test_known_hosts_must_be_stable_nofollow_and_not_writable_by_others(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_asyncssh(monkeypatch)
    arguments = _arguments(tmp_path)
    Path(arguments["known_hosts_file"]).chmod(0o666)

    with pytest.raises(module.SFTPPositiveCanaryError, match="writable by others"):
        module.produce_evidence(**arguments)


def test_cli_failure_never_emits_endpoint_principal_or_secret(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fake_asyncssh(monkeypatch, connect_outcome="auth_failure")
    arguments = _arguments(tmp_path)
    argv = [
        "probe",
        "--live-sha",
        LIVE_SHA,
        "--release-a-sha",
        RELEASE_A_SHA,
        "--sftp-sha",
        SFTP_SHA,
        "--deployment-id",
        DEPLOYMENT_ID,
        "--sftp-image-id",
        IMAGE_ID,
        "--sftp-runtime-id",
        RUNTIME_ID,
        "--host",
        HOST,
        "--expected-hostname",
        EXPECTED_HOSTNAME,
        "--port",
        "2223",
        "--username",
        USERNAME,
        "--password-file",
        arguments["password_file"],
        "--known-hosts-file",
        arguments["known_hosts_file"],
        "--runtime-ready-receipt-file",
        arguments["runtime_ready_receipt_file"],
        "--expected-host-key-fingerprint",
        FINGERPRINT,
        "--output",
        arguments["output"],
    ]

    assert module.main(argv) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    for forbidden in (HOST, USERNAME, PASSWORD):
        assert forbidden not in captured.err
    assert captured.err == "Release A positive SFTP canary failed\n"


def test_password_has_no_direct_cli_or_environment_fallback(module: ModuleType) -> None:
    parser = module._parser()
    options = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            for command in choices.values():
                options.update(
                    option
                    for child in command._actions
                    for option in child.option_strings
                )
    assert "--password" not in options
    assert "--password-file" in options


def test_atomic_private_publication_fsyncs_file_and_parent(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output = tmp_path / "evidence.json"
    synced_modes: list[int] = []
    publication_observations: list[tuple[bool, int, dict[str, Any]]] = []
    real_fsync = os.fsync
    real_link = os.link

    def recording_fsync(descriptor: int) -> None:
        synced_modes.append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    def recording_link(source: str, destination: str, **kwargs: Any) -> None:
        source_path = tmp_path / source
        publication_observations.append(
            (
                output.exists(),
                stat.S_IMODE(source_path.stat().st_mode),
                json.loads(source_path.read_text(encoding="utf-8")),
            )
        )
        real_link(source, destination, **kwargs)

    monkeypatch.setattr(module.os, "fsync", recording_fsync)
    monkeypatch.setattr(module.os, "link", recording_link)
    module._write_private_json({"result": "passed"}, str(output))

    assert publication_observations == [(False, 0o600, {"result": "passed"})]
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text(encoding="utf-8")) == {"result": "passed"}
    assert any(stat.S_ISREG(mode) for mode in synced_modes)
    assert any(stat.S_ISDIR(mode) for mode in synced_modes)
    assert list(tmp_path.glob(".*.tmp")) == []


def test_atomic_publication_never_overwrites_existing_output(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    output = tmp_path / "evidence.json"
    output.write_text("operator-owned", encoding="utf-8")

    with pytest.raises(module.SFTPPositiveCanaryError, match="already exists"):
        module._write_private_json({"result": "passed"}, str(output))

    assert output.read_text(encoding="utf-8") == "operator-owned"


def test_finalize_requires_canonical_artifact_filename(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact, arguments = _complete_lifecycle(module, monkeypatch, tmp_path)
    assert artifact["kind"] == "sftp-positive-auth.artifact"
    Path(arguments["output"]).unlink()
    arguments["output"] = str(tmp_path / "generic.json")

    with pytest.raises(module.SFTPPositiveCanaryError, match="filename"):
        module.finalize_evidence(**arguments)


@pytest.mark.parametrize("timeout", [0.99, 30.01, float("inf"), float("nan")])
def test_timeout_is_bounded(module: ModuleType, timeout: float) -> None:
    with pytest.raises(module.SFTPPositiveCanaryError, match="safe bound"):
        module._validate_timeout(timeout)
