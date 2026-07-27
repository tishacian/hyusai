#!/usr/bin/env python3
"""Collect a direct, SHA-bound provenance proof on the Agentium VM.

This is deliberately *not* the protected GitLab deployment attestation.  It
exists for the explicitly accepted VM fallback workflow and never claims CI
provenance.  It is read-only apart from atomically writing
``<deployment-dir>/proofs/provenance.json``.

Credentials are neither accepted as command-line arguments nor read by this
collector.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SERVICES = (
    "agentium-backend",
    "agentium-frontend",
    "agentium-worker-cpu",
)
BUILD_INFO_PATHS = {
    "backend": "/api/v1/build-info",
    "frontend": "/build-info.json",
}


class FallbackAttestationError(ValueError):
    """Raised when direct VM provenance cannot be established."""


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    expected: str
    observed: str


CommandRunner = Callable[..., str]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_sha(value: str) -> str:
    normalized = value.strip().lower()
    if FULL_SHA_RE.fullmatch(normalized) is None:
        raise FallbackAttestationError("--sha must be a full lowercase Git SHA")
    return normalized


def _safe_branch(value: str) -> str:
    if BRANCH_RE.fullmatch(value) is None or ".." in Path(value).parts:
        raise FallbackAttestationError("--branch is invalid")
    return value


def _safe_revision(value: str) -> str:
    normalized = value.strip()
    if REVISION_RE.fullmatch(normalized) is None:
        raise FallbackAttestationError("--alembic-revision is invalid")
    return normalized


def _run(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 30.0,
) -> str:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # Command stderr may contain infrastructure details.  Keep it out of
        # both the terminal and the attestation.
        raise FallbackAttestationError(f"read-only command failed: {argv[0]}") from exc
    return completed.stdout.strip()


def _require_private_directory(path: Path, *, label: str, create: bool = False) -> Path:
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise FallbackAttestationError(f"{label} cannot be a symlink")
    try:
        resolved = path.resolve(strict=True)
        details = resolved.stat()
    except OSError as exc:
        raise FallbackAttestationError(f"{label} is unavailable") from exc
    if not resolved.is_dir():
        raise FallbackAttestationError(f"{label} must be a directory")
    if details.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise FallbackAttestationError(f"{label} is group/world writable")
    return resolved


def _json_object(raw: str, *, label: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > 65_536:
        raise FallbackAttestationError(f"{label} is too large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FallbackAttestationError(f"{label} is not JSON") from exc
    if not isinstance(value, dict):
        raise FallbackAttestationError(f"{label} must be a JSON object")
    return value


def _fetch_build_info(path: str, *, runner: CommandRunner) -> dict[str, Any]:
    raw = runner(
        [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--connect-timeout",
            "5",
            "--max-time",
            "15",
            "--noproxy",
            "*",
            "--resolve",
            "agentium.papai.ai:443:127.0.0.1",
            "--header",
            "Accept: application/json",
            f"https://agentium.papai.ai{path}",
        ],
        timeout=20.0,
    )
    return _json_object(raw, label=f"build-info {path}")


def _docker_service(service: str, *, runner: CommandRunner) -> dict[str, Any]:
    raw = runner(
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Running}}|{{.Image}}",
            service,
        ]
    )
    try:
        running_raw, image_id = raw.split("|", 1)
    except ValueError as exc:
        raise FallbackAttestationError(f"invalid Docker state for {service}") from exc
    revision = runner(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            '{{ index .Config.Labels "org.opencontainers.image.revision" }}',
            image_id,
        ]
    ).lower()
    return {
        "service": service,
        "running": running_raw == "true",
        "image_id": image_id,
        "revision": revision,
    }


def _database_heads(*, runner: CommandRunner) -> list[str]:
    raw = runner(["docker", "exec", "agentium-backend", "alembic", "current"])
    return sorted(set(re.findall(r"([A-Za-z0-9_.+-]+)\s+\(head\)", raw)))


def _maintenance_state(
    helper: Path,
    *,
    repo_dir: Path,
    runner: CommandRunner,
) -> str:
    if helper.is_symlink() or not helper.is_file() or not os.access(helper, os.X_OK):
        raise FallbackAttestationError("frozen maintenance helper is unavailable")
    environment = dict(os.environ)
    environment["OMNIRAG_REPO_DIR"] = str(repo_dir)
    return runner([str(helper), "status"], env=environment)


def _sftp_state(*, runner: CommandRunner) -> dict[str, Any]:
    raw = runner(
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Running}}|{{.State.Status}}",
            "agentium-sftp",
        ]
    )
    try:
        running_raw, status = raw.split("|", 1)
    except ValueError as exc:
        raise FallbackAttestationError("invalid Docker state for agentium-sftp") from exc
    return {"running": running_raw == "true", "status": status}


def _container_state(service: str, *, runner: CommandRunner) -> dict[str, Any]:
    raw = runner(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name=^/{service}$",
            "--format",
            "{{.Names}}|{{.State}}",
        ]
    )
    if not raw:
        return {"present": False, "running": False, "state": "absent"}
    rows = [line.split("|", 1) for line in raw.splitlines()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][0] != service:
        raise FallbackAttestationError(f"ambiguous Docker state for {service}")
    state = rows[0][1].strip().lower()
    return {"present": True, "running": state == "running", "state": state}


def _worker_celery_beat(*, runner: CommandRunner) -> str | None:
    raw = runner(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .Config.Env}}",
            "agentium-worker-cpu",
        ]
    )
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FallbackAttestationError("worker environment metadata is invalid") from exc
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise FallbackAttestationError("worker environment metadata is invalid")
    matches = [value.split("=", 1)[1] for value in values if value.startswith("CELERY_BEAT=")]
    if len(matches) != 1:
        return None
    return matches[0]


def _container_environment_value(
    service: str,
    key: str,
    *,
    runner: CommandRunner,
) -> str | None:
    raw = runner(
        [
            "docker",
            "inspect",
            "--format",
            "{{json .Config.Env}}",
            service,
        ]
    )
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FallbackAttestationError(
            f"{service} environment metadata is invalid"
        ) from exc
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise FallbackAttestationError(f"{service} environment metadata is invalid")
    matches = [value.split("=", 1)[1] for value in values if value.startswith(f"{key}=")]
    if len(matches) > 1:
        raise FallbackAttestationError(f"{service} has an ambiguous {key} setting")
    return matches[0] if matches else None


def _listener_count(raw: str, port: int) -> int:
    count = 0
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        if local.rsplit(":", 1)[-1] == str(port):
            count += 1
    return count


def _udp_listener_count(raw: str, start: int, end: int) -> int:
    count = 0
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            port = int(parts[3].rsplit(":", 1)[-1])
        except ValueError:
            continue
        if start <= port <= end:
            count += 1
    return count


def _livekit_udp_range(
    *,
    livekit_present: bool,
    runner: CommandRunner,
) -> tuple[int | None, int | None]:
    raw_start = raw_end = None
    if livekit_present:
        raw_start = _container_environment_value(
            "agentium-livekit", "LIVEKIT_RTC_UDP_RANGE_START", runner=runner
        )
        raw_end = _container_environment_value(
            "agentium-livekit", "LIVEKIT_RTC_UDP_RANGE_END", runner=runner
        )
    try:
        start = int(raw_start or "50000")
        end = int(raw_end or "50100")
    except ValueError:
        return None, None
    if not 1 <= start <= end <= 65535:
        return None, None
    return start, end


def collect_fallback_attestation(
    *,
    sha: str,
    branch: str,
    alembic_revision: str,
    repo_dir: Path,
    deployment_dir: Path,
    runner: CommandRunner = _run,
    gate_marker_path: Path = Path("/var/lib/agentium/deploy-maintenance"),
) -> dict[str, Any]:
    """Collect and evaluate the VM fallback proof without mutating runtime state."""

    expected_sha = _safe_sha(sha)
    expected_branch = _safe_branch(branch)
    expected_revision = _safe_revision(alembic_revision)
    repository = repo_dir.resolve(strict=True)
    deployment = _require_private_directory(deployment_dir, label="deployment-dir")
    proofs = _require_private_directory(
        deployment / "proofs", label="proofs directory", create=True
    )
    try:
        proofs.relative_to(deployment)
    except ValueError as exc:
        raise FallbackAttestationError("proofs directory escaped deployment-dir") from exc

    phase = (deployment / "phase").read_text(encoding="utf-8").strip()
    repo_head = runner(["git", "rev-parse", "HEAD"], cwd=repository).lower()
    current_branch = runner(["git", "branch", "--show-current"], cwd=repository)
    remote_head = runner(
        ["git", "rev-parse", f"refs/remotes/origin/{expected_branch}"], cwd=repository
    ).lower()
    dirty = runner(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repository
    )
    dirty_count = len(dirty.splitlines()) if dirty else 0

    service_rows = [_docker_service(service, runner=runner) for service in SERVICES]
    database_heads = _database_heads(runner=runner)
    backend_build = _fetch_build_info(BUILD_INFO_PATHS["backend"], runner=runner)
    frontend_build = _fetch_build_info(BUILD_INFO_PATHS["frontend"], runner=runner)
    maintenance = _maintenance_state(
        deployment / "agentium-maintenance-gate.sh",
        repo_dir=repository,
        runner=runner,
    )
    gate_marker = gate_marker_path.is_file()
    sftp = _sftp_state(runner=runner)
    p4 = _container_state("agentium-p4-maintenance", runner=runner)
    livekit = _container_state("agentium-livekit", runner=runner)
    livekit_agent = _container_state("agentium-livekit-agent", runner=runner)
    celery_beat = _worker_celery_beat(runner=runner)
    legacy_backend_state = runner(
        ["systemctl", "show", "agentium-backend", "--property", "ActiveState", "--value"]
    ).strip()
    legacy_sftp_state = runner(
        ["systemctl", "show", "agentium-sftp", "--property", "ActiveState", "--value"]
    ).strip()
    legacy_sftp_unit_file_state = runner(
        ["systemctl", "show", "agentium-sftp", "--property", "UnitFileState", "--value"]
    ).strip()
    tcp_listeners = runner(["ss", "-H", "-ltn"])
    udp_listeners = runner(["ss", "-H", "-lun"])
    legacy_backend_listeners = _listener_count(tcp_listeners, 8000)
    livekit_listeners = _listener_count(tcp_listeners, 7881)
    livekit_udp_start, livekit_udp_end = _livekit_udp_range(
        livekit_present=bool(livekit["present"]), runner=runner
    )
    livekit_udp_range_valid = (
        livekit_udp_start is not None and livekit_udp_end is not None
    )
    livekit_udp_listeners = (
        _udp_listener_count(udp_listeners, livekit_udp_start, livekit_udp_end)
        if livekit_udp_range_valid
        else -1
    )

    checks = [
        Check("deployment.phase", phase == "validation_pending", "validation_pending", phase),
        Check("vm.repo_head", repo_head == expected_sha, expected_sha, repo_head),
        Check("vm.branch", current_branch == expected_branch, expected_branch, current_branch),
        Check("vm.origin_head", remote_head == expected_sha, expected_sha, remote_head),
        Check("vm.checkout_clean", dirty_count == 0, "0 dirty entries", str(dirty_count)),
        Check(
            "database.single_expected_head",
            database_heads == [expected_revision],
            expected_revision,
            ",".join(database_heads),
        ),
        Check("maintenance.helper_state", maintenance == "closed", "closed", maintenance),
        Check("maintenance.marker_present", gate_marker, "true", str(gate_marker).lower()),
        Check("sftp.stopped", sftp["running"] is False, "false", str(sftp["running"]).lower()),
        Check(
            "legacy_sftp.systemd_inactive",
            legacy_sftp_state == "inactive",
            "inactive",
            legacy_sftp_state,
        ),
        Check(
            "legacy_sftp.systemd_disabled",
            legacy_sftp_unit_file_state == "disabled",
            "disabled",
            legacy_sftp_unit_file_state,
        ),
        Check(
            "p4_maintenance.stopped",
            p4["present"] is True and p4["running"] is False,
            "present and stopped",
            f"present={str(p4['present']).lower()},state={p4['state']}",
        ),
        Check("worker.celery_beat", celery_beat == "0", "0", str(celery_beat)),
        Check(
            "legacy_backend.systemd_inactive",
            legacy_backend_state == "inactive",
            "inactive",
            legacy_backend_state,
        ),
        Check(
            "legacy_backend.no_listener_8000",
            legacy_backend_listeners == 0,
            "0",
            str(legacy_backend_listeners),
        ),
        Check(
            "livekit.container_stopped",
            livekit["running"] is False,
            "not running",
            livekit["state"],
        ),
        Check(
            "livekit_agent.container_stopped",
            livekit_agent["running"] is False,
            "not running",
            livekit_agent["state"],
        ),
        Check(
            "livekit.no_listener_7881",
            livekit_listeners == 0,
            "0",
            str(livekit_listeners),
        ),
        Check(
            "livekit.udp_range_valid",
            livekit_udp_range_valid,
            "valid configured UDP range",
            (
                f"{livekit_udp_start}-{livekit_udp_end}"
                if livekit_udp_range_valid
                else "invalid"
            ),
        ),
        Check(
            "livekit.no_udp_listener_in_configured_range",
            livekit_udp_range_valid and livekit_udp_listeners == 0,
            "0",
            str(livekit_udp_listeners),
        ),
        Check(
            "backend.build_info.service",
            backend_build.get("service") == "backend",
            "backend",
            str(backend_build.get("service")),
        ),
        Check(
            "backend.build_info.revision",
            backend_build.get("revision") == expected_sha,
            expected_sha,
            str(backend_build.get("revision")),
        ),
        Check(
            "backend.build_info.verified",
            backend_build.get("revision_verified") is True,
            "true",
            str(backend_build.get("revision_verified")).lower(),
        ),
        Check(
            "frontend.build_info.service",
            frontend_build.get("service") == "frontend",
            "frontend",
            str(frontend_build.get("service")),
        ),
        Check(
            "frontend.build_info.revision",
            frontend_build.get("revision") == expected_sha,
            expected_sha,
            str(frontend_build.get("revision")),
        ),
        Check(
            "frontend.build_info.verified",
            frontend_build.get("revision_verified") is True,
            "true",
            str(frontend_build.get("revision_verified")).lower(),
        ),
    ]
    for row in service_rows:
        service = str(row["service"])
        checks.extend(
            [
                Check(
                    f"oci.{service}.running",
                    row["running"] is True,
                    "true",
                    str(row["running"]).lower(),
                ),
                Check(
                    f"oci.{service}.image_id",
                    IMAGE_ID_RE.fullmatch(str(row["image_id"])) is not None,
                    "sha256:<64 hex>",
                    str(row["image_id"]),
                ),
                Check(
                    f"oci.{service}.revision",
                    row["revision"] == expected_sha,
                    expected_sha,
                    str(row["revision"]),
                ),
            ]
        )

    passed = all(check.passed for check in checks)
    return {
        "schema_version": 1,
        "kind": "vm_fallback_provenance",
        "trust_boundary": "direct_operator_vm_fallback",
        "promotion_ceiling": "runner_verified",
        "commit_sha": expected_sha,
        "branch": expected_branch,
        "deployment_id": deployment.name,
        "collected_at": _utc_now(),
        "outcome": "passed" if passed else "failed",
        "vm": {
            "repo_head": repo_head,
            "branch": current_branch,
            "origin_head": remote_head,
            "clean": dirty_count == 0,
            "dirty_entry_count": dirty_count,
        },
        "database_heads": database_heads,
        "services": service_rows,
        "build_info": {"backend": backend_build, "frontend": frontend_build},
        "maintenance": {
            "state": maintenance,
            "marker_present": gate_marker,
            "sftp_running": sftp["running"],
            "sftp_state": sftp["status"],
            "legacy_sftp_systemd": legacy_sftp_state,
            "legacy_sftp_unit_file_state": legacy_sftp_unit_file_state,
            "sftp_required_before_public_reopen": True,
        },
        "writer_exclusion": {
            "celery_beat": celery_beat,
            "legacy_backend_systemd": legacy_backend_state,
            "legacy_backend_listener_count": legacy_backend_listeners,
            "p4_maintenance_state": p4["state"],
            "livekit_state": livekit["state"],
            "livekit_agent_state": livekit_agent["state"],
            "livekit_listener_count": livekit_listeners,
            "livekit_udp_range_start": livekit_udp_start,
            "livekit_udp_range_end": livekit_udp_end,
            "livekit_udp_listener_count": livekit_udp_listeners,
        },
        "checks": {
            check.name: {
                "passed": check.passed,
                "expected": check.expected,
                "observed": check.observed,
            }
            for check in checks
        },
    }


def write_attestation(path: Path, payload: Mapping[str, Any], deployment_dir: Path) -> None:
    deployment = deployment_dir.resolve(strict=True)
    expected = deployment / "proofs" / "provenance.json"
    if path != expected:
        raise FallbackAttestationError("provenance output must use the fixed deployment path")
    if path.exists() and path.is_symlink():
        raise FallbackAttestationError("provenance output cannot be a symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".provenance.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--branch", default="demo/agentic")
    parser.add_argument("--alembic-revision", required=True)
    parser.add_argument("--repo-dir", type=Path, default=Path("/home/ubuntu/omnirag"))
    parser.add_argument("--deployment-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = collect_fallback_attestation(
            sha=args.sha,
            branch=args.branch,
            alembic_revision=args.alembic_revision,
            repo_dir=args.repo_dir,
            deployment_dir=args.deployment_dir,
        )
        output = args.deployment_dir.resolve(strict=True) / "proofs" / "provenance.json"
        write_attestation(output, payload, args.deployment_dir)
        if payload["outcome"] != "passed":
            raise FallbackAttestationError("one or more provenance checks failed")
    except (FallbackAttestationError, OSError) as exc:
        print(f"provenance failed: {exc}", file=sys.stderr)
        return 1
    print("VM fallback provenance passed (not a protected GitLab attestation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
