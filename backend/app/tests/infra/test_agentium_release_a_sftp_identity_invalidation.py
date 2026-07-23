"""Fail-closed contract for loss of the Release A attested SFTP process."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
EXECUTOR = ROOT / "scripts" / "deploy-agentium-release-a-safe.sh"


def _function(script: str, name: str) -> str:
    """Extract one complete Bash function, including heredoc bodies."""

    marker = f"{name}() {{"
    start = script.index(marker)
    cursor = start
    depth = 0
    quote: str | None = None
    escaped = False
    heredocs: list[str] = []
    while cursor < len(script):
        line_end = script.find("\n", cursor)
        if line_end == -1:
            line_end = len(script)
        line = script[cursor:line_end]
        if heredocs:
            if line == heredocs[0]:
                heredocs.pop(0)
            cursor = line_end + 1
            continue
        index = 0
        while index < len(line):
            character = line[index]
            if escaped:
                escaped = False
            elif character == "\\" and quote != "'":
                escaped = True
            elif quote:
                if character == quote:
                    quote = None
            elif character in ("'", '"'):
                quote = character
            elif line.startswith("<<'", index) or line.startswith('<<"', index):
                delimiter_quote = line[index + 2]
                delimiter_end = line.find(delimiter_quote, index + 3)
                heredocs.append(line[index + 3 : delimiter_end])
                index = delimiter_end
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
            index += 1
        cursor = line_end + 1
        if depth == 0 and cursor > start:
            return script[start:cursor]
    raise AssertionError(f"unterminated Bash function: {name}")


@pytest.fixture(scope="module")
def executor() -> str:
    return EXECUTOR.read_text(encoding="utf-8")


def _run_bash(body: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", "-c", "set -Eeuo pipefail\n" + body],
        capture_output=True,
        text=True,
        env=merged,
        check=False,
    )


def _runtime_ready(path: Path, *, started_at: str = "2026-07-23T08:00:00Z") -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-runtime-ready",
        "result": "passed",
        "sftp_container_id": "a" * 64,
        "sftp_image_id": "sha256:" + "b" * 64,
        "sftp_started_at": started_at,
        "runtime_identity_sha256": "c" * 64,
    }
    path.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return payload


def _fake_docker(directory: Path, *, started_at: str, running: bool = True) -> None:
    docker = directory / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import json,os,sys
if sys.argv[1:4] == ["inspect","--type","container"]:
    print(json.dumps([{"Id":"a"*64,"Image":"sha256:"+"b"*64,"State":{"StartedAt":os.environ["FAKE_STARTED_AT"],"Running":os.environ.get("FAKE_RUNNING","true")=="true","Paused":False}}]))
elif sys.argv[1:3] == ["image","inspect"]:
    print(json.dumps([{"Config":{"Labels":{"org.opencontainers.image.revision":"d"*40}}}]))
else:
    raise SystemExit(2)
""",
        encoding="utf-8",
    )
    docker.chmod(0o700)


def test_process_probe_distinguishes_stable_restart_and_unsafe_proof(
    executor: str, tmp_path: Path
) -> None:
    proof = tmp_path / "runtime.json"
    _runtime_ready(proof)
    _fake_docker(tmp_path, started_at="2026-07-23T08:00:00Z")
    script = _function(executor, "probe_sftp_process_identity_core")
    harness = f"""
SFTP_RUNTIME_READY={proof!s}
metadata() {{ printf '%s\\n' "{'d' * 40}"; }}
{script}
probe_sftp_process_identity_core
"""
    base_env = {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_STARTED_AT": "2026-07-23T08:00:00Z",
        "FAKE_RUNNING": "true",
    }
    assert _run_bash(harness, env=base_env).returncode == 0

    restarted = dict(base_env, FAKE_STARTED_AT="2026-07-23T08:00:01Z")
    assert _run_bash(harness, env=restarted).returncode == 1

    stopped = dict(base_env, FAKE_RUNNING="false")
    assert _run_bash(harness, env=stopped).returncode == 1

    proof.chmod(0o644)
    assert _run_bash(harness, env=base_env).returncode == 2

    proof.chmod(0o600)
    proof.write_text("not-json\n", encoding="utf-8")
    assert _run_bash(harness, env=base_env).returncode == 2


def test_guard_routes_loss_to_invalidation_and_never_rearms(executor: str) -> None:
    guard = _function(executor, "guard_sftp_process_identity_or_invalidate")
    completed = _run_bash(
        f"""
SFTP_RUNTIME_READY=/dev/null
phase() {{ printf 'completed\\n'; }}
probe_sftp_process_identity_core() {{ return 1; }}
observed_sftp_process_identity_sha256() {{ printf '%064d\\n' 0; }}
invalidate_lost_sftp_identity() {{ printf 'invalidated:%s:%s\\n' "$1" "$2"; }}
die() {{ printf 'die:%s\\n' "$*" >&2; exit 1; }}
{guard}
guard_sftp_process_identity_or_invalidate
"""
    )
    assert completed.returncode == 0
    assert completed.stdout == f"invalidated:completed:{'0' * 64}\n"

    stable = _run_bash(
        f"""
SFTP_RUNTIME_READY=/dev/null
phase() {{ printf 'sftp_canary_pending\\n'; }}
probe_sftp_process_identity_core() {{ return 0; }}
observed_sftp_process_identity_sha256() {{ return 99; }}
invalidate_lost_sftp_identity() {{ return 98; }}
die() {{ exit 97; }}
{guard}
guard_sftp_process_identity_or_invalidate
"""
    )
    assert stable.returncode == 0

    unsafe = _run_bash(
        f"""
SFTP_RUNTIME_READY=/dev/null
phase() {{ printf 'completed\\n'; }}
probe_sftp_process_identity_core() {{ return 2; }}
observed_sftp_process_identity_sha256() {{ return 99; }}
invalidate_lost_sftp_identity() {{ return 98; }}
fail_closed_unattestable_sftp_proof() {{ printf 'unsafe-closed\\n'; exit 42; }}
die() {{ exit 97; }}
{guard}
guard_sftp_process_identity_or_invalidate
"""
    )
    assert unsafe.returncode == 42
    assert unsafe.stdout == "unsafe-closed\n"


def test_invalidation_receipt_is_canonical_bound_and_write_once(
    executor: str, tmp_path: Path
) -> None:
    proof = tmp_path / "sftp-validation-runtime-ready.json"
    proof_payload = _runtime_ready(proof)
    event = tmp_path / "sftp-runtime-identity-invalidation.json"
    functions = "\n".join(
        _function(executor, name)
        for name in (
            "durable_replace",
            "assert_sftp_identity_invalidation",
            "publish_sftp_identity_invalidation",
        )
    )
    release = "d" * 40
    live = "e" * 40
    body = f"""
DEPLOY_DIR={tmp_path!s}
SFTP_IDENTITY_INVALIDATION={event!s}
SFTP_RUNTIME_READY={proof!s}
COMPLETION_RECEIPT={tmp_path / 'absent-completion.json'!s}
DEPLOYMENT_ID=release-a-test-001
LIVE_SHA={live}
RELEASE_A_SHA={release}
metadata() {{ printf '%s\\n' "$SFTP_SHA"; }}
SFTP_SHA={'f' * 40}
die() {{ printf '%s\\n' "$*" >&2; exit 1; }}
assert_private() {{ [[ -f "$1" && ! -L "$1" ]]; }}
{functions}
publish_sftp_identity_invalidation sftp_canary_recorded {'1' * 64} passed passed passed passed passed
sha256sum "$SFTP_IDENTITY_INVALIDATION"
publish_sftp_identity_invalidation sftp_canary_recorded {'2' * 64} incomplete incomplete incomplete incomplete incomplete
sha256sum "$SFTP_IDENTITY_INVALIDATION"
"""
    result = _run_bash(body)
    assert result.returncode == 0, result.stderr
    digests = [line.split()[0] for line in result.stdout.splitlines()]
    assert len(digests) == 2
    assert digests[0] == digests[1]

    payload = json.loads(event.read_text(encoding="utf-8"))
    assert event.read_bytes() == (
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    )
    assert payload["old_runtime_ready_receipt_sha256"] == hashlib.sha256(
        proof.read_bytes()
    ).hexdigest()
    assert payload["old_runtime_identity_sha256"] == proof_payload["runtime_identity_sha256"]
    assert payload["observed_runtime_identity_sha256"] == "1" * 64
    assert payload["completion_receipt_sha256"] is None
    assert payload["recovery"] == "new_deployment_id_required"
    assert payload["automatic_rearm_allowed"] is False
    assert (
        payload["operator_gate"]
        == "revoke_old_canary_and_verify_zero_active_links_sessions_before_new_deployment"
    )
    assert payload["reclosure"] == {
        "http_gate_closed": "passed",
        "restart_disabled": "passed",
        "secure_deposit_read_only": "passed",
        "writer_ingress_closed": "passed",
        "writers_stopped": "passed",
    }


def test_invalidation_tampering_is_rejected(executor: str, tmp_path: Path) -> None:
    proof = tmp_path / "sftp-validation-runtime-ready.json"
    _runtime_ready(proof)
    event = tmp_path / "sftp-runtime-identity-invalidation.json"
    payload = {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-runtime-identity-invalidation",
        "result": "invalidated",
        "deployment_id": "release-a-test-001",
        "live_sha": "e" * 40,
        "release_a_sha": "d" * 40,
        "sftp_sha": "f" * 40,
        "detected_phase": "completed",
        "reason": "attested_process_identity_lost",
        "old_runtime_ready_receipt_sha256": hashlib.sha256(proof.read_bytes()).hexdigest(),
        "old_runtime_identity_sha256": "c" * 64,
        "observed_runtime_identity_sha256": "1" * 64,
        "completion_receipt_sha256": None,
        "reclosure": {
            "http_gate_closed": "passed",
            "restart_disabled": "passed",
            "secure_deposit_read_only": "passed",
            "writer_ingress_closed": "passed",
            "writers_stopped": "passed",
        },
        "recovery": "reuse_current_deployment",
        "automatic_rearm_allowed": False,
        "operator_gate": (
            "revoke_old_canary_and_verify_zero_active_links_sessions_before_new_deployment"
        ),
        "invalidated_at": "2026-07-23T10:00:00Z",
    }
    event.write_text(
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    event.chmod(0o600)
    functions = "\n".join(
        _function(executor, name)
        for name in ("assert_sftp_identity_invalidation",)
    )
    result = _run_bash(
        f"""
SFTP_IDENTITY_INVALIDATION={event!s}
SFTP_RUNTIME_READY={proof!s}
COMPLETION_RECEIPT={tmp_path / 'absent.json'!s}
DEPLOYMENT_ID=release-a-test-001
LIVE_SHA={'e' * 40}
RELEASE_A_SHA={'d' * 40}
metadata() {{ printf '%s\\n' "{'f' * 40}"; }}
die() {{ printf '%s\\n' "$*" >&2; exit 1; }}
assert_private() {{ [[ -f "$1" && ! -L "$1" ]]; }}
{functions}
assert_sftp_identity_invalidation
"""
    )
    assert result.returncode != 0
    assert "binding differs" in result.stderr


def test_executor_wires_terminal_state_before_git_or_resume_work(executor: str) -> None:
    assert "completed:sftp_identity_invalidated" in executor
    assert "sftp_canary_recorded:sftp_identity_invalidated" in executor
    assert 'recovery":"new_deployment_id_required' in executor
    main = executor[executor.index('if [[ "$MODE" != preflight ]]'):]
    assert main.index("guard_sftp_process_identity_or_invalidate") < main.index(
        "stage_helpers"
    )
    assert main.index("SFTP_IDENTITY_INVALIDATION") < main.index(
        "guard_sftp_process_identity_or_invalidate"
    )
    assert "set_phase sftp_identity_invalidated" in main
    invalidation = _function(executor, "invalidate_lost_sftp_identity")
    assert invalidation.index("install_gate_closed") < invalidation.index(
        "enter_writer_ingress_gates"
    ) < invalidation.index("disable_writer_restarts") < invalidation.index(
        "emergency_stop_writers_after_sftp_identity_loss"
    ) < invalidation.index("set_secure_mode ro") < invalidation.index(
        "publish_sftp_identity_invalidation"
    )
    replay = main[main.index('if [[ -e "$SFTP_IDENTITY_INVALIDATION"'):]
    assert replay.index("install_gate_closed") < replay.index(
        "enter_writer_ingress_gates"
    ) < replay.index("disable_writer_restarts") < replay.index(
        "emergency_stop_writers_after_sftp_identity_loss"
    ) < replay.index("set_secure_mode ro") < replay.index(
        "assert_sftp_identity_invalidation"
    )
    invalidated_case = executor[executor.index("arm_sftp_canary_impl() {") :]
    assert "sftp_identity_invalidated" not in invalidated_case.split(
        "record_sftp_active_impl() {", 1
    )[0]
