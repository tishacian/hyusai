"""Functional fail-closed contract for Release A terminal gate exits."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
GATE = ROOT / "scripts" / "agentium-maintenance-gate.sh"
DEPLOYMENT_ID = "release-a-terminal-contract"
RELEASE_A_SHA = "a" * 40
LIVE_SHA = "b" * 40


@dataclass(frozen=True)
class TerminalCase:
    root: Path
    deployment_parent: Path
    deployment: Path
    frozen_gate: Path
    phase: Path
    receipt: Path
    authorization: Path
    marker: Path
    nginx_calls: Path
    env: dict[str, str]
    purpose: str
    terminal_phase: str


def _canonical_json(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() + b"\n"


def _write_private(path: Path, body: bytes) -> None:
    path.write_bytes(body)
    path.chmod(0o600)


def _terminal_identity(purpose: str) -> tuple[str, str, str]:
    if purpose == "forward-terminal-open":
        return (
            "completed",
            "release-a-transaction-receipt.json",
            "release-a-forward-open-authorization.json",
        )
    if purpose == "rollback-terminal-open":
        return (
            "rolled_back",
            "release-a-rollback-receipt.json",
            "release-a-rollback-open-authorization.json",
        )
    raise AssertionError(f"unsupported purpose: {purpose}")


def _receipt_payload(purpose: str) -> dict[str, object]:
    if purpose == "forward-terminal-open":
        return {
            "schema_version": 3,
            "kind": "agentium-release-a-transaction-receipt",
            "result": "passed",
            "deployment_id": DEPLOYMENT_ID,
            "release_a_sha": RELEASE_A_SHA,
            "release_a_attestation_receipt_sha256": "1" * 64,
            "final_evidence_receipt_sha256": "2" * 64,
            "manifest_receipt_sha256": "3" * 64,
            "preconditions_receipt_sha256": "4" * 64,
            "preconditions_evidence_receipt_sha256": "5" * 64,
            "runtime_oci_receipt_sha256": "6" * 64,
            "sftp_runtime_ready_receipt_sha256": "7" * 64,
            "sftp_postgres_ledger_receipt_sha256": "8" * 64,
            "completed_at": "2026-07-23T10:00:00Z",
        }
    return {
        "schema_version": 2,
        "kind": "agentium-release-a-rollback-receipt",
        "result": "passed",
        "deployment_id": DEPLOYMENT_ID,
        "restored_sha": LIVE_SHA,
        "rollback_state_sha256": "9" * 64,
        "runtime_state_sha256": "c" * 64,
        "completed_at": "2026-07-23T10:00:00Z",
    }


def _build_case(tmp_path: Path, purpose: str) -> TerminalCase:
    terminal_phase, receipt_name, authorization_name = _terminal_identity(purpose)
    deployment_parent = tmp_path / "deployments"
    deployment_parent.mkdir(mode=0o700, parents=True)
    deployment = deployment_parent / DEPLOYMENT_ID
    deployment.mkdir(mode=0o700)
    frozen_gate = deployment / GATE.name
    frozen_gate.write_bytes(GATE.read_bytes())
    frozen_gate.chmod(0o700)

    metadata = deployment / "metadata.tsv"
    _write_private(
        metadata,
        (
            f"deployment_id\t{DEPLOYMENT_ID}\n"
            f"live_sha\t{LIVE_SHA}\n"
            f"release_a_sha\t{RELEASE_A_SHA}\n"
        ).encode(),
    )
    phase = deployment / "phase"
    _write_private(phase, f"{terminal_phase}\n".encode())

    receipt = deployment / receipt_name
    receipt_body = _canonical_json(_receipt_payload(purpose))
    _write_private(receipt, receipt_body)
    authorization = deployment / authorization_name
    _write_private(
        authorization,
        _canonical_json(
            {
                "schema_version": 1,
                "kind": "agentium-release-a-terminal-gate-authorization",
                "deployment_id": DEPLOYMENT_ID,
                "release_a_sha": RELEASE_A_SHA,
                "purpose": purpose,
                "terminal_phase": terminal_phase,
                "receipt_name": receipt_name,
                "receipt_sha256": hashlib.sha256(receipt_body).hexdigest(),
            }
        ),
    )

    maintenance = tmp_path / "maintenance"
    maintenance.mkdir()
    marker = maintenance / "deploy-maintenance"
    marker.write_text(f"deployment_id\t{DEPLOYMENT_ID}\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text('#!/usr/bin/env bash\nexec "$@"\n', encoding="utf-8")
    fake_sudo.chmod(0o700)
    fake_nginx = fake_bin / "nginx"
    fake_nginx.write_text(
        "#!/usr/bin/env bash\n" 'printf \'%s\\n\' "$*" >>"$AGENTIUM_TEST_NGINX_CALLS"\n' "exit 0\n",
        encoding="utf-8",
    )
    fake_nginx.chmod(0o700)
    nginx_calls = tmp_path / "nginx.calls"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "AGENTIUM_SAFE_DEPLOY_ORCHESTRATED": "1",
        "AGENTIUM_SAFE_DEPLOYMENT_DIR": str(deployment),
        "AGENTIUM_SAFE_DEPLOYMENT_ID": DEPLOYMENT_ID,
        "AGENTIUM_SAFE_GATE_PURPOSE": purpose,
        "AGENTIUM_SAFE_GATE_AUTHORIZATION": str(authorization),
        "AGENTIUM_MAINTENANCE_DIR": str(maintenance),
        "AGENTIUM_TEST_NGINX_CALLS": str(nginx_calls),
    }
    return TerminalCase(
        root=tmp_path,
        deployment_parent=deployment_parent,
        deployment=deployment,
        frozen_gate=frozen_gate,
        phase=phase,
        receipt=receipt,
        authorization=authorization,
        marker=marker,
        nginx_calls=nginx_calls,
        env=env,
        purpose=purpose,
        terminal_phase=terminal_phase,
    )


@contextmanager
def _parent_fd(path: Path, *, locked: bool = True) -> Iterator[int]:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield descriptor
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _invoke(case: TerminalCase, descriptor: int | None) -> subprocess.CompletedProcess[str]:
    env = dict(case.env)
    pass_fds: tuple[int, ...] = ()
    if descriptor is not None:
        env["AGENTIUM_SAFE_GATE_LOCK_FD"] = str(descriptor)
        pass_fds = (descriptor,)
    return subprocess.run(
        ["bash", str(case.frozen_gate), "exit"],
        capture_output=True,
        text=True,
        env=env,
        pass_fds=pass_fds,
        check=False,
    )


def _assert_refused_before_nginx(
    case: TerminalCase, result: subprocess.CompletedProcess[str]
) -> None:
    assert result.returncode != 0, result.stdout
    assert case.marker.exists(), result.stderr
    assert not case.nginx_calls.exists(), result.stderr


def test_terminal_gate_script_is_valid_bash() -> None:
    result = subprocess.run(["bash", "-n", str(GATE)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("purpose", ("forward-terminal-open", "rollback-terminal-open"))
def test_exact_locked_authorized_terminal_exit_opens_gate(tmp_path: Path, purpose: str) -> None:
    case = _build_case(tmp_path, purpose)
    with _parent_fd(case.deployment_parent) as descriptor:
        result = _invoke(case, descriptor)
    assert result.returncode == 0, result.stderr
    assert not case.marker.exists()
    assert case.nginx_calls.read_text(encoding="utf-8") == "-t\n"


@pytest.mark.parametrize("purpose", ("forward-terminal-open", "rollback-terminal-open"))
def test_direct_terminal_exit_without_inherited_lock_is_refused(
    tmp_path: Path,
    purpose: str,
) -> None:
    case = _build_case(tmp_path, purpose)
    _assert_refused_before_nginx(case, _invoke(case, None))


def test_unlocked_or_wrong_inherited_fd_is_refused(tmp_path: Path) -> None:
    unlocked = _build_case(tmp_path / "unlocked", "forward-terminal-open")
    with _parent_fd(unlocked.deployment_parent, locked=False) as descriptor:
        _assert_refused_before_nginx(unlocked, _invoke(unlocked, descriptor))

    wrong = _build_case(tmp_path / "wrong", "forward-terminal-open")
    unrelated = wrong.root / "unrelated"
    unrelated.mkdir()
    with _parent_fd(unrelated) as descriptor:
        _assert_refused_before_nginx(wrong, _invoke(wrong, descriptor))


def test_lock_held_by_another_open_description_does_not_authorize_exit(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path, "forward-terminal-open")
    with _parent_fd(case.deployment_parent):
        with _parent_fd(case.deployment_parent, locked=False) as unrelated_description:
            _assert_refused_before_nginx(case, _invoke(case, unrelated_description))


def test_missing_or_noncanonical_authorization_path_is_refused(tmp_path: Path) -> None:
    missing = _build_case(tmp_path / "missing", "forward-terminal-open")
    missing.env.pop("AGENTIUM_SAFE_GATE_AUTHORIZATION")
    with _parent_fd(missing.deployment_parent) as descriptor:
        _assert_refused_before_nginx(missing, _invoke(missing, descriptor))

    alternate = _build_case(tmp_path / "alternate", "forward-terminal-open")
    alternate_path = alternate.deployment / "alternate-authorization.json"
    alternate_path.write_bytes(alternate.authorization.read_bytes())
    alternate_path.chmod(0o600)
    alternate.env["AGENTIUM_SAFE_GATE_AUTHORIZATION"] = str(alternate_path)
    with _parent_fd(alternate.deployment_parent) as descriptor:
        _assert_refused_before_nginx(alternate, _invoke(alternate, descriptor))

    absent = _build_case(tmp_path / "absent", "forward-terminal-open")
    absent.authorization.unlink()
    with _parent_fd(absent.deployment_parent) as descriptor:
        _assert_refused_before_nginx(absent, _invoke(absent, descriptor))


@pytest.mark.parametrize(
    "mutation",
    ("symlink", "permissive_mode", "hardlink", "noncanonical_json"),
)
def test_unsafe_authorization_file_is_refused(tmp_path: Path, mutation: str) -> None:
    case = _build_case(tmp_path, "forward-terminal-open")
    if mutation == "symlink":
        external = case.root / "authorization-target.json"
        external.write_bytes(case.authorization.read_bytes())
        external.chmod(0o600)
        case.authorization.unlink()
        case.authorization.symlink_to(external)
    else:
        if mutation == "permissive_mode":
            case.authorization.chmod(0o644)
        elif mutation == "hardlink":
            os.link(case.authorization, case.root / "authorization-hardlink.json")
        else:
            case.authorization.write_bytes(case.authorization.read_bytes() + b" ")
    with _parent_fd(case.deployment_parent) as descriptor:
        _assert_refused_before_nginx(case, _invoke(case, descriptor))


def test_receipt_tampering_after_authorization_is_refused(tmp_path: Path) -> None:
    case = _build_case(tmp_path, "forward-terminal-open")
    payload = json.loads(case.receipt.read_text(encoding="utf-8"))
    payload["completed_at"] = "2026-07-23T10:00:01Z"
    _write_private(case.receipt, _canonical_json(payload))
    with _parent_fd(case.deployment_parent) as descriptor:
        _assert_refused_before_nginx(case, _invoke(case, descriptor))


@pytest.mark.parametrize("field", ("purpose", "terminal_phase", "receipt_name"))
def test_authorization_with_wrong_terminal_identity_is_refused(
    tmp_path: Path,
    field: str,
) -> None:
    case = _build_case(tmp_path, "forward-terminal-open")
    payload = json.loads(case.authorization.read_text(encoding="utf-8"))
    payload[field] = {
        "purpose": "rollback-terminal-open",
        "terminal_phase": "rolled_back",
        "receipt_name": "release-a-rollback-receipt.json",
    }[field]
    _write_private(case.authorization, _canonical_json(payload))
    with _parent_fd(case.deployment_parent) as descriptor:
        _assert_refused_before_nginx(case, _invoke(case, descriptor))


def test_invocation_with_wrong_purpose_or_phase_is_refused(tmp_path: Path) -> None:
    wrong_purpose = _build_case(tmp_path / "purpose", "forward-terminal-open")
    wrong_purpose.env["AGENTIUM_SAFE_GATE_PURPOSE"] = "rollback-terminal-open"
    with _parent_fd(wrong_purpose.deployment_parent) as descriptor:
        _assert_refused_before_nginx(wrong_purpose, _invoke(wrong_purpose, descriptor))

    wrong_phase = _build_case(tmp_path / "phase", "forward-terminal-open")
    _write_private(wrong_phase.phase, b"opening_forward\n")
    with _parent_fd(wrong_phase.deployment_parent) as descriptor:
        _assert_refused_before_nginx(wrong_phase, _invoke(wrong_phase, descriptor))
