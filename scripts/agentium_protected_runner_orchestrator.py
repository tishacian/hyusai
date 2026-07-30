#!/usr/bin/env python3
"""Run, validate, sign and cold-verify Agentium protected-runner canaries.

This controller is deliberately independent from the Agentium deployment VM.
It is installed on the isolated Carakai evidence host and invokes only the
already-provisioned constrained runner and signer.  It never invokes Docker,
Git, a deployment script, or an Agentium host shell.

Two evidence classes are supported:

``acceptance``
    May use the named operator account.  Every artifact is explicitly marked
    ``formal_release_eligible=false``.  This is the only mode allowed while the
    deployed SHA is still the pre-Release-A SHA.

``release``
    Fails closed unless the tested SHA is a distinct deployed candidate, the
    source checkout is that exact SHA, and a non-personal automation principal
    is used.

The signer validates provenance and transaction identity.  This controller
adds the missing semantic boundary: it validates a closed schema and
token-specific business checks before an artifact can be staged for signing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1
ENVIRONMENT = "production"
HOSTNAME = "agentium.papai.ai"
ISSUER = "carakai-protected-runner-v1"

RUNNER_EXECUTOR = Path("/usr/local/sbin/agentium-protected-runner-exec")
RUNNER_EXECUTOR_SHA256 = (
    "d05a4e4a6ae6fa75b99a92c637d9b7b600cbe482ac8c3fc6dce4a6314d0143ae"
)
RUNNER_SIGNER = Path("/usr/local/sbin/agentium-protected-runner-sign")
RUNNER_SIGNER_SHA256 = (
    "7ea104866d3e3dd5ae0b4eb07949de93fbf91c7370d4832bc69f7a8064701698"
)
RUNNER_ROOT = Path("/var/lib/agentium-protected-runner")
JOB_ROOT = RUNNER_ROOT / "jobs"
EVIDENCE_ROOT = RUNNER_ROOT / "evidence"
FROZEN_ROOT = Path("/var/lib/agentium-protected-signer/frozen")
CONFIG_ROOT = Path("/etc/agentium-protected-runner")
JOB_ENV_ROOT = CONFIG_ROOT / "jobs"
AUTHORIZATION_ROOT = CONFIG_ROOT / "authorizations"
PUBLIC_KEY = Path("/var/lib/agentium-protected-signer/protected-runner.public.pem")
NODE_MODULES_ROOT = Path("/opt/agentium-protected-runner/frontend-deps")

PACKAGE_LOCK_SHA256 = (
    "e2d450397339be6fe89cdbcaf63ff7261e4bd915ef66a9d84d3e94bbc22218c7"
)
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_CAPTURE_AGE = timedelta(hours=4)

TOKENS = (
    "browser-permission-probe",
    "canary-andritz",
    "canary-livekit",
    "canary-octocity",
    "canary-sentinel",
    "canary-showcase",
    "sftp-positive-auth",
)
TOKEN_CLAIMS = {
    "browser-permission-probe": (
        "evidence.principals.browser_canary.permission_probe_sha256"
    ),
    "canary-andritz": "evidence.canaries.andritz.proof_sha256",
    "canary-livekit": "evidence.canaries.livekit.proof_sha256",
    "canary-octocity": "evidence.canaries.octocity.proof_sha256",
    "canary-sentinel": "evidence.canaries.sentinel.proof_sha256",
    "canary-showcase": "evidence.canaries.showcase.proof_sha256",
    "sftp-positive-auth": "evidence.sftp.proof_sha256",
}

COMMON_CANARY_KEYS = {
    "schema_version",
    "kind",
    "profile",
    "token",
    "result",
    "evidence_class",
    "formal_release_eligible",
    "deployment_id",
    "tested_sha",
    "principal_class",
    "workspace_sha256",
    "checks",
    "captured_at",
}
SFTP_KEYS = {
    "access_id_sha256",
    "captured_at",
    "checks",
    "claim",
    "credential_fingerprint_sha256",
    "deployment_id",
    "environment",
    "evidence_class",
    "formal_release_eligible",
    "hostname_sha256",
    "kind",
    "link_id_sha256",
    "principal_class",
    "principal_sha256",
    "profile",
    "result",
    "schema_version",
    "sftp_host_key_sha256",
    "tested_sha",
    "workspace_id_sha256",
}

REQUIRED_CHECKS: dict[str, frozenset[str]] = {
    "canary-showcase": frozenset(
        {
            "build_revision",
            "unique_marker_discovery",
            "four_distinct_projections",
            "invariant_identity_header_breadcrumb_tabs",
            "ui_value_matches_api_per_lens",
            "deep_link_reload_history_and_facet",
            "workspace_switch_purges_object",
            "explicit_missing_state",
            "explicit_restricted_state",
        }
    ),
    "canary-andritz": frozenset(
        {
            "backend_build_info_exact",
            "frontend_build_info_exact",
            "settings_role_unique",
            "role_marker_current",
            "authenticated_dry_run",
            "dry_run_confirmed",
            "dry_run_created_zero",
            "dry_run_updated_zero",
            "dry_run_counters_content_free",
        }
    ),
    "canary-sentinel": frozenset(
        {
            "backend_build_info_exact",
            "frontend_build_info_exact",
            "settings_role_unique",
            "role_marker_current",
            "navigation_read",
            "navigation_profile_bound",
            "navigation_system_bindings_complete",
            "branding_settings_complete",
            "branding_api_bound",
            "branding_ui_bound",
            "action_packs_exact",
            "action_pack_namespace_isolated",
            "cross_terms_absent",
        }
    ),
    "canary-octocity": frozenset(
        {
            "backend_build_info_exact",
            "frontend_build_info_exact",
            "settings_role_unique",
            "role_marker_current",
            "navigation_read",
            "navigation_profile_bound",
            "navigation_system_bindings_complete",
            "branding_settings_complete",
            "branding_api_bound",
            "branding_ui_bound",
            "action_packs_exact",
            "action_pack_namespace_isolated",
            "cross_terms_absent",
        }
    ),
    "canary-livekit": frozenset(
        {
            "backend_build_info_exact",
            "frontend_build_info_exact",
            "settings_role_unique",
            "authenticated_config_read",
            "public_state_shape_valid",
            "secret_fields_absent",
            "token_values_absent",
        }
    ),
    "browser-permission-probe": frozenset(
        {
            "backend_build_info_exact",
            "frontend_build_info_exact",
            "settings_role_unique",
            "microphone_not_granted",
            "capture_ui_accessible",
        }
    ),
    "sftp-positive-auth": frozenset(
        {
            "backend_build_bound",
            "frontend_build_bound",
            "secure_deposit_enabled",
            "temporary_link_created",
            "password_authentication",
            "host_key_pin_matched",
            "content_free_getcwd",
            "content_free_stat_dot",
            "temporary_link_revoked",
            "post_revoke_authentication_denied",
        }
    ),
}

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
DEPLOYMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
CHECK_RE = re.compile(r"^[a-z][a-z0-9_]{2,95}$")
IPV4_RE = re.compile(
    r"^(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})"
    r"(?:\.(?:25[0-5]|2[0-4][0-9]|1?[0-9]{1,2})){3}$"
)
UUID_RE = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}\b"
)


class OrchestratorError(RuntimeError):
    """A fail-closed orchestration or evidence error."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise OrchestratorError("invalid command arguments")


def canonical_json(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=True,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OrchestratorError("value is not canonical JSON") from exc


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise OrchestratorError(f"{label} is not an UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise OrchestratorError(f"{label} is not an UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise OrchestratorError(f"{label} is not an UTC timestamp")
    return parsed.astimezone(UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def strict_json_bytes(body: bytes, *, label: str, require_canonical: bool) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def no_constant(_value: str) -> None:
        raise ValueError("non-finite number")

    try:
        value = json.loads(
            body,
            object_pairs_hook=no_duplicates,
            parse_constant=no_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise OrchestratorError(f"{label} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise OrchestratorError(f"{label} is not a JSON object")
    if require_canonical and canonical_json(value) != body:
        raise OrchestratorError(f"{label} is not canonical JSON")
    return value


def read_bounded(path: Path, *, label: str, require_canonical: bool) -> tuple[dict[str, Any], bytes]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise OrchestratorError(f"{label} is absent") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size <= 0
        or before.st_size > MAX_ARTIFACT_BYTES
        or stat.S_IMODE(before.st_mode) != 0o600
    ):
        raise OrchestratorError(f"{label} is unsafe")
    body = path.read_bytes()
    after = path.lstat()
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise OrchestratorError(f"{label} changed while reading")
    return (
        strict_json_bytes(body, label=label, require_canonical=require_canonical),
        body,
    )


def validate_mode(
    *,
    evidence_class: str,
    formal_release_eligible: bool,
    principal_class: str,
    live_sha: str,
    release_a_sha: str,
    tested_sha: str,
    source_sha: str | None = None,
) -> None:
    for label, value in (
        ("live SHA", live_sha),
        ("Release A SHA", release_a_sha),
        ("tested SHA", tested_sha),
    ):
        if SHA_RE.fullmatch(value) is None:
            raise OrchestratorError(f"{label} is invalid")
    if source_sha is not None and SHA_RE.fullmatch(source_sha) is None:
        raise OrchestratorError("source SHA is invalid")
    if evidence_class == "acceptance":
        if formal_release_eligible:
            raise OrchestratorError("acceptance evidence cannot be formal")
        if principal_class != "operator_personal_admin":
            raise OrchestratorError("acceptance principal class differs")
        if tested_sha != release_a_sha:
            raise OrchestratorError("acceptance tested and signing SHAs differ")
        return
    if evidence_class != "release":
        raise OrchestratorError("evidence class is invalid")
    if not formal_release_eligible or principal_class != "automation_non_personal":
        raise OrchestratorError("release evidence requires non-personal automation")
    if live_sha == release_a_sha:
        raise OrchestratorError("release evidence requires a distinct candidate")
    if tested_sha != release_a_sha:
        raise OrchestratorError("release evidence is not bound to the candidate")
    if source_sha is None or source_sha != release_a_sha:
        raise OrchestratorError("release source checkout is not the candidate")


def validate_checks(token: str, value: Any) -> dict[str, bool | int]:
    if not isinstance(value, Mapping) or not value:
        raise OrchestratorError(f"{token} checks are absent")
    checks: dict[str, bool | int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or CHECK_RE.fullmatch(key) is None:
            raise OrchestratorError(f"{token} check name is invalid")
        if isinstance(item, bool):
            if not item:
                raise OrchestratorError(f"{token} check {key} did not pass")
        elif not isinstance(item, int) or item < 0:
            raise OrchestratorError(f"{token} check {key} is not content-free")
        checks[key] = item
    missing = REQUIRED_CHECKS[token] - set(checks)
    if missing:
        raise OrchestratorError(f"{token} misses a required business check")
    expected_counts = {
        "canary-andritz": {
            # Post-Release B baseline: three apps surface through four entitled
            # routes (FSE reports rides the capture router as its own surface).
            "configured_app_count": 4,
            "accessible_route_count": 4,
        },
        "canary-sentinel": {
            "navigation_item_count": 7,
            "action_pack_count": 3,
        },
        "canary-octocity": {
            "navigation_item_count": 7,
            "action_pack_count": 3,
        },
    }
    for key, expected in expected_counts.get(token, {}).items():
        if checks.get(key) != expected:
            raise OrchestratorError(f"{token} business count {key} differs")
    return checks


def validate_capture_time(value: Any, *, now: datetime) -> str:
    captured = timestamp(value, label="artifact captured_at")
    if captured > now + MAX_CLOCK_SKEW or now - captured > MAX_CAPTURE_AGE:
        raise OrchestratorError("artifact capture time is outside the bounded window")
    return str(value)


def _content_free_serialization(payload: Mapping[str, Any], body: bytes) -> None:
    text = body.decode("utf-8")
    if (
        "Bearer " in text
        or "generated_password" in text
        or "refresh_token" in text
        or UUID_RE.search(text)
        or "@" in text
    ):
        raise OrchestratorError("artifact serialized a forbidden identity or credential")
    for key in payload:
        lowered = key.lower()
        if lowered in {"password", "authorization", "refresh_token", "email", "slug"}:
            raise OrchestratorError("artifact schema contains a forbidden field")


def validate_canary_artifact(
    payload: Mapping[str, Any],
    body: bytes,
    *,
    token: str,
    deployment_id: str,
    tested_sha: str,
    evidence_class: str,
    principal_class: str,
    formal_release_eligible: bool,
    now: datetime,
) -> str:
    if set(payload) != COMMON_CANARY_KEYS:
        raise OrchestratorError(f"{token} artifact schema differs")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("kind") != "agentium-protected-runner-canary"
        or payload.get("profile") != "agentium-protected-runner-canary-v1"
        or payload.get("token") != token
        or payload.get("result") != "passed"
        or payload.get("deployment_id") != deployment_id
        or payload.get("tested_sha") != tested_sha
        or payload.get("evidence_class") != evidence_class
        or payload.get("principal_class") != principal_class
        or payload.get("formal_release_eligible") is not formal_release_eligible
    ):
        raise OrchestratorError(f"{token} artifact identity differs")
    workspace_digest = payload.get("workspace_sha256")
    if not isinstance(workspace_digest, str) or DIGEST_RE.fullmatch(workspace_digest) is None:
        raise OrchestratorError(f"{token} workspace digest is invalid")
    validate_checks(token, payload.get("checks"))
    captured_at = validate_capture_time(payload.get("captured_at"), now=now)
    _content_free_serialization(payload, body)
    return captured_at


def validate_sftp_artifact(
    payload: Mapping[str, Any],
    body: bytes,
    *,
    deployment_id: str,
    tested_sha: str,
    principal_class: str,
    now: datetime,
) -> str:
    token = "sftp-positive-auth"
    if set(payload) != SFTP_KEYS:
        raise OrchestratorError("SFTP artifact schema differs")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("kind") != "sftp-positive-auth.artifact"
        or payload.get("profile") != "agentium-protected-runner-sftp-acceptance-v1"
        or payload.get("claim") != token
        or payload.get("result") != "passed"
        or payload.get("environment") != ENVIRONMENT
        or payload.get("deployment_id") != deployment_id
        or payload.get("tested_sha") != tested_sha
        or payload.get("evidence_class") != "acceptance"
        or payload.get("formal_release_eligible") is not False
        or payload.get("principal_class") != principal_class
    ):
        raise OrchestratorError("SFTP artifact identity differs")
    for key in (
        "access_id_sha256",
        "credential_fingerprint_sha256",
        "hostname_sha256",
        "link_id_sha256",
        "principal_sha256",
        "sftp_host_key_sha256",
        "workspace_id_sha256",
    ):
        value = payload.get(key)
        if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
            raise OrchestratorError(f"SFTP artifact {key} is invalid")
    validate_checks(token, payload.get("checks"))
    captured_at = validate_capture_time(payload.get("captured_at"), now=now)
    _content_free_serialization(payload, body)
    return captured_at


def derive_showcase_artifact(
    *,
    runner_path: Path,
    behavior_path: Path,
    output_path: Path,
    deployment_id: str,
    tested_sha: str,
    evidence_class: str,
    principal_class: str,
    formal_release_eligible: bool,
    now: datetime,
) -> None:
    runner, _ = read_bounded(
        runner_path,
        label="System 360 runner evidence",
        require_canonical=False,
    )
    behavior, _ = read_bounded(
        behavior_path,
        label="System 360 behavior evidence",
        require_canonical=False,
    )
    if (
        runner.get("schema_version") != 1
        or runner.get("kind") != "runner"
        or runner.get("runner") != "playwright"
        or runner.get("outcome") != "passed"
        or runner.get("commit_sha") != tested_sha
        or behavior.get("schema_version") != 1
        or behavior.get("kind") != "behavior"
        or behavior.get("outcome") != "passed"
        or behavior.get("commit_sha") != tested_sha
        or behavior.get("checks") != runner.get("checks")
    ):
        raise OrchestratorError("System 360 source evidence identity differs")
    checks = validate_checks("canary-showcase", behavior.get("checks"))
    for source in (runner, behavior):
        build_info = source.get("build_info")
        if not isinstance(build_info, Mapping):
            raise OrchestratorError("System 360 build binding is absent")
        for service in ("backend", "frontend"):
            row = build_info.get(service)
            if (
                not isinstance(row, Mapping)
                or row.get("revision") != tested_sha
                or row.get("service") != service
                or row.get("revision_verified") is not True
            ):
                raise OrchestratorError("System 360 build binding differs")
    workspace = behavior.get("workspace")
    raw_workspace_id = workspace.get("id") if isinstance(workspace, Mapping) else None
    if not isinstance(raw_workspace_id, str) or not raw_workspace_id:
        raise OrchestratorError("System 360 workspace identity is absent")
    workspace_digest = hashlib.sha256(raw_workspace_id.encode("utf-8")).hexdigest()
    artifact = {
        "captured_at": utc_text(now),
        "checks": checks,
        "deployment_id": deployment_id,
        "evidence_class": evidence_class,
        "formal_release_eligible": formal_release_eligible,
        "kind": "agentium-protected-runner-canary",
        "principal_class": principal_class,
        "profile": "agentium-protected-runner-canary-v1",
        "result": "passed",
        "schema_version": 1,
        "tested_sha": tested_sha,
        "token": "canary-showcase",
        "workspace_sha256": workspace_digest,
    }
    body = canonical_json(artifact)
    if output_path.exists() or output_path.is_symlink():
        raise OrchestratorError("Showcase artifact already exists")
    descriptor = os.open(
        output_path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.write(descriptor, body)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_output_directory(
    output: Path,
    *,
    deployment_id: str,
    tested_sha: str,
    evidence_class: str,
    principal_class: str,
    formal_release_eligible: bool,
    now: datetime | None = None,
) -> dict[str, dict[str, str]]:
    if DEPLOYMENT_RE.fullmatch(deployment_id) is None:
        raise OrchestratorError("deployment id is invalid")
    current = now or utc_now()
    result: dict[str, dict[str, str]] = {}
    for token in TOKENS:
        path = output / f"{token}.artifact"
        payload, body = read_bounded(
            path,
            label=f"{token} artifact",
            require_canonical=True,
        )
        if token == "sftp-positive-auth":
            if evidence_class != "acceptance" or formal_release_eligible:
                raise OrchestratorError(
                    "the acceptance SFTP producer cannot be promoted to release evidence"
                )
            captured_at = validate_sftp_artifact(
                payload,
                body,
                deployment_id=deployment_id,
                tested_sha=tested_sha,
                principal_class=principal_class,
                now=current,
            )
        else:
            captured_at = validate_canary_artifact(
                payload,
                body,
                token=token,
                deployment_id=deployment_id,
                tested_sha=tested_sha,
                evidence_class=evidence_class,
                principal_class=principal_class,
                formal_release_eligible=formal_release_eligible,
                now=current,
            )
        result[token] = {
            "artifact_sha256": sha256(body),
            "captured_at": captured_at,
        }
    return result


def _ensure_root() -> None:
    if os.geteuid() != 0:
        raise OrchestratorError("root is required for protected orchestration")


def _digest_file(path: Path) -> str:
    return sha256(path.read_bytes())


def _verify_installed_helpers() -> None:
    for path, expected in (
        (RUNNER_EXECUTOR, RUNNER_EXECUTOR_SHA256),
        (RUNNER_SIGNER, RUNNER_SIGNER_SHA256),
    ):
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise OrchestratorError("protected runner helper is absent") from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_mode & 0o022
            or _digest_file(path) != expected
        ):
            raise OrchestratorError("protected runner helper differs from the reviewed bytes")


def _safe_source_root(source_root: Path, source_sha: str) -> Path:
    try:
        root = source_root.resolve(strict=True)
        metadata = root.lstat()
    except OSError as exc:
        raise OrchestratorError("source checkout is unavailable") from exc
    if (
        source_root != root
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_mode & 0o022
    ):
        raise OrchestratorError("source checkout is unsafe")
    marker = root / ".agentium-source-sha"
    if (
        not marker.is_file()
        or marker.is_symlink()
        or marker.read_text(encoding="ascii") != f"{source_sha}\n"
        or marker.stat().st_uid != 0
        or marker.stat().st_mode & 0o022
    ):
        raise OrchestratorError("source checkout SHA marker differs")
    required = (
        root / "frontend-ng/e2e/tests/11-system360-canary.spec.ts",
        root / "frontend-ng/e2e/tests/12-protected-runner-canaries.spec.ts",
        root / "scripts/agentium_protected_runner_sftp_acceptance.py",
        root / "scripts/agentium_protected_runner_orchestrator.py",
    )
    for path in required:
        if not path.is_file() or path.is_symlink() or path.stat().st_uid != 0:
            raise OrchestratorError("source checkout misses reviewed producer bytes")
    lock = root / "frontend-ng/package-lock.json"
    if _digest_file(lock) != PACKAGE_LOCK_SHA256:
        raise OrchestratorError("frontend dependency lock differs")
    modules = root / "frontend-ng/node_modules"
    if (
        not modules.is_symlink()
        or modules.resolve(strict=True) != (NODE_MODULES_ROOT / "node_modules").resolve(strict=True)
    ):
        raise OrchestratorError("frontend dependencies are not the frozen runtime")
    return root


def _read_root_secret(path: Path, *, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise OrchestratorError(f"{label} credential is absent") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or not 0 < metadata.st_size <= 4096
    ):
        raise OrchestratorError(f"{label} credential is unsafe")
    body = path.read_bytes()
    if b"\x00" in body or b"\r" in body or b"\n" in body or not body.strip():
        raise OrchestratorError(f"{label} credential is invalid")
    return body


def _write_file(path: Path, body: bytes, *, mode: int, uid: int, gid: int) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        mode,
    )
    try:
        os.write(descriptor, body)
        os.fsync(descriptor)
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def _authorization(
    *,
    deployment_id: str,
    live_sha: str,
    release_a_sha: str,
    sftp_release_sha: str,
    issued_at: datetime,
) -> dict[str, Any]:
    return {
        "allowed_tokens": list(TOKENS),
        "deployment_id": deployment_id,
        "environment": ENVIRONMENT,
        "expires_at": utc_text(issued_at + timedelta(hours=2)),
        "hostname_sha256": hashlib.sha256(HOSTNAME.encode("ascii")).hexdigest(),
        "issued_at": utc_text(issued_at),
        "kind": "agentium-protected-runner-authorization",
        "live_sha": live_sha,
        "release_a_sha": release_a_sha,
        "schema_version": 1,
        "sftp_release_sha": sftp_release_sha,
    }


def _prepare_job(
    *,
    deployment_id: str,
    source_root: Path,
    username: bytes,
    password: bytes,
    agentium_ip: str,
    sftp_host_key_sha256: str,
    tested_sha: str,
    evidence_class: str,
    principal_class: str,
    formal_release_eligible: bool,
    python_site: Path,
) -> tuple[Path, Path]:
    if IPV4_RE.fullmatch(agentium_ip) is None:
        raise OrchestratorError("Agentium IP allowlist entry is invalid")
    if not sftp_host_key_sha256.startswith("SHA256:"):
        raise OrchestratorError("SFTP host-key pin is invalid")
    if not python_site.is_dir() or python_site.is_symlink() or python_site.stat().st_uid != 0:
        raise OrchestratorError("pinned AsyncSSH runtime is unavailable")
    runner = pwd.getpwnam("agentium-runner")
    job = JOB_ROOT / deployment_id
    env_path = JOB_ENV_ROOT / f"{deployment_id}.env"
    if job.exists() or job.is_symlink() or env_path.exists() or env_path.is_symlink():
        raise OrchestratorError("protected runner job already exists")
    job.mkdir(mode=0o750)
    os.chown(job, 0, runner.pw_gid)
    for name in ("work", "output", "home"):
        child = job / name
        child.mkdir(mode=0o700)
        os.chown(child, runner.pw_uid, runner.pw_gid)
    credentials = job / "credentials"
    credentials.mkdir(mode=0o700)
    os.chown(credentials, runner.pw_uid, runner.pw_gid)
    username_path = credentials / "username"
    password_path = credentials / "password"
    _write_file(
        username_path,
        username,
        mode=0o400,
        uid=runner.pw_uid,
        gid=runner.pw_gid,
    )
    _write_file(
        password_path,
        password,
        mode=0o400,
        uid=runner.pw_uid,
        gid=runner.pw_gid,
    )
    _write_file(
        job / "network.allow",
        f"{agentium_ip}\n".encode("ascii"),
        mode=0o444,
        uid=0,
        gid=0,
    )
    _write_file(
        job / "hosts",
        f"{agentium_ip}\tagentium.papai.ai\n".encode("ascii"),
        mode=0o444,
        uid=0,
        gid=0,
    )
    env = {
        "CI_COMMIT_SHA": tested_sha,
        "CI_COMMIT_REF_NAME": f"protected-runner/{evidence_class}",
        "CI_COMMIT_REF_PROTECTED": "false",
        "E2E_BASE_URL": f"https://{HOSTNAME}",
        "E2E_DEPLOYMENT_ID": deployment_id,
        "E2E_EVIDENCE_CLASS": evidence_class,
        "E2E_EXPECTED_SHA": tested_sha,
        "E2E_FORMAL_RELEASE_ELIGIBLE": str(formal_release_eligible).lower(),
        "E2E_LOT6_BEHAVIOR_ATTESTATION": f"/tmp/{deployment_id}-system360-behavior.json",
        "E2E_LOT6_CANARY": "1",
        "E2E_LOT6_RUNNER_ATTESTATION": f"/tmp/{deployment_id}-system360-runner.json",
        "E2E_PRINCIPAL_CLASS": principal_class,
        "E2E_PROTECTED_EVIDENCE_DIR": str(job / "output"),
        "E2E_PROTECTED_RUNNER_CANARIES": "1",
        "E2E_SAFE_CONTENT_FREE": "1",
        "E2E_SFTP_HOST": HOSTNAME,
        "E2E_SFTP_HOST_KEY_SHA256": sftp_host_key_sha256,
        "E2E_SFTP_PORT": "2222",
        "E2E_SOURCE_ROOT": str(source_root),
        "E2E_USERNAME_FILE": str(username_path),
        "E2E_PASSWORD_FILE": str(password_path),
        "E2E_PLAYWRIGHT_OUTPUT_DIR": str(job / "work/playwright-output"),
        "E2E_PYTHON_SITE": str(python_site),
        "PLAYWRIGHT_HTML_OUTPUT_DIR": str(job / "work/playwright-html"),
        "PLAYWRIGHT_JUNIT_OUTPUT_NAME": str(job / "work/playwright-junit.xml"),
    }
    for key, value in env.items():
        if "\n" in value or "\r" in value or "\x00" in value:
            raise OrchestratorError("runner environment contains unsafe bytes")
    _write_file(
        env_path,
        "".join(f"{key}={value}\n" for key, value in sorted(env.items())).encode("utf-8"),
        mode=0o600,
        uid=0,
        gid=0,
    )
    run_script = """#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export E2E_USERNAME="$(/bin/cat "$E2E_USERNAME_FILE")"
export E2E_PASSWORD="$(/bin/cat "$E2E_PASSWORD_FILE")"
trap 'unset E2E_USERNAME E2E_PASSWORD' EXIT
cd "$E2E_SOURCE_ROOT/frontend-ng"
./node_modules/.bin/playwright test \
  e2e/tests/11-system360-canary.spec.ts \
  e2e/tests/12-protected-runner-canaries.spec.ts \
  --project=chromium \
  --reporter=list \
  --output="$E2E_PLAYWRIGHT_OUTPUT_DIR"
PYTHONPATH="$E2E_PYTHON_SITE" /usr/bin/python3 \
  "$E2E_SOURCE_ROOT/scripts/agentium_protected_runner_sftp_acceptance.py" \
  run --output "$E2E_PROTECTED_EVIDENCE_DIR"
/usr/bin/python3 -I \
  "$E2E_SOURCE_ROOT/scripts/agentium_protected_runner_orchestrator.py" \
  worker-finalize \
  --output "$E2E_PROTECTED_EVIDENCE_DIR" \
  --deployment-id "$E2E_DEPLOYMENT_ID" \
  --tested-sha "$E2E_EXPECTED_SHA" \
  --evidence-class "$E2E_EVIDENCE_CLASS" \
  --principal-class "$E2E_PRINCIPAL_CLASS" \
  --formal-release-eligible "$E2E_FORMAL_RELEASE_ELIGIBLE" \
  --runner-evidence "$E2E_LOT6_RUNNER_ATTESTATION" \
  --behavior-evidence "$E2E_LOT6_BEHAVIOR_ATTESTATION"
"""
    _write_file(
        job / "run.sh",
        run_script.encode("utf-8"),
        mode=0o550,
        uid=0,
        gid=runner.pw_gid,
    )
    return job, env_path


def _write_authorization(
    *,
    deployment_id: str,
    live_sha: str,
    release_a_sha: str,
    sftp_release_sha: str,
    issued_at: datetime,
) -> Path:
    path = AUTHORIZATION_ROOT / f"{deployment_id}.json"
    if path.exists() or path.is_symlink():
        raise OrchestratorError("protected runner authorization already exists")
    payload = _authorization(
        deployment_id=deployment_id,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_release_sha=sftp_release_sha,
        issued_at=issued_at,
    )
    _write_file(path, canonical_json(payload), mode=0o600, uid=0, gid=0)
    return path


def _no_runner_processes() -> None:
    runner = pwd.getpwnam("agentium-runner")
    completed = subprocess.run(
        ["/usr/bin/pgrep", "-u", str(runner.pw_uid)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=10,
    )
    if completed.returncode not in {1}:
        raise OrchestratorError("protected runner processes remain active")


def _stage_and_sign(
    *,
    output: Path,
    deployment_id: str,
    tested_sha: str,
    evidence_class: str,
    principal_class: str,
    formal_release_eligible: bool,
    live_sha: str,
    release_a_sha: str,
    sftp_release_sha: str,
    source_sha: str,
) -> dict[str, Any]:
    _no_runner_processes()
    validated = validate_output_directory(
        output,
        deployment_id=deployment_id,
        tested_sha=tested_sha,
        evidence_class=evidence_class,
        principal_class=principal_class,
        formal_release_eligible=formal_release_eligible,
    )
    runner = pwd.getpwnam("agentium-runner")
    evidence = EVIDENCE_ROOT / deployment_id
    if evidence.exists() or evidence.is_symlink():
        raise OrchestratorError("evidence staging directory already exists")
    evidence.mkdir(mode=0o700)
    os.chown(evidence, runner.pw_uid, runner.pw_gid)
    hostname_digest = hashlib.sha256(HOSTNAME.encode("ascii")).hexdigest()
    for token in TOKENS:
        artifact_body = (output / f"{token}.artifact").read_bytes()
        artifact = evidence / f"{token}.artifact"
        _write_file(
            artifact,
            artifact_body,
            mode=0o600,
            uid=runner.pw_uid,
            gid=runner.pw_gid,
        )
        provenance = {
            "artifact_sha256": validated[token]["artifact_sha256"],
            "captured_at": validated[token]["captured_at"],
            "claim": TOKEN_CLAIMS[token],
            "deployment_id": deployment_id,
            "environment": ENVIRONMENT,
            "hostname_sha256": hostname_digest,
            "issuer": ISSUER,
            "kind": "agentium-release-a-external-proof-provenance",
            "live_sha": live_sha,
            "producer": "protected_runner",
            "release_a_sha": release_a_sha,
            "result": "passed",
            "schema_version": 1,
            "sftp_release_sha": sftp_release_sha,
        }
        _write_file(
            evidence / f"{token}.provenance.json",
            canonical_json(provenance),
            mode=0o600,
            uid=runner.pw_uid,
            gid=runner.pw_gid,
        )
    signer_results: dict[str, Any] = {}
    for token in TOKENS:
        completed = subprocess.run(
            [
                str(RUNNER_SIGNER),
                "--deployment-id",
                deployment_id,
                "--token",
                token,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
        )
        if completed.returncode != 0:
            raise OrchestratorError(f"signer rejected {token}")
        try:
            signer_results[token] = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise OrchestratorError("signer output is invalid") from exc
    verify_frozen(deployment_id)
    return {
        "deployment_id": deployment_id,
        "evidence_class": evidence_class,
        "formal_release_eligible": formal_release_eligible,
        "issuer": ISSUER,
        "orchestrator_sha256": _digest_file(Path(__file__).resolve()),
        "principal_class": principal_class,
        "result": "passed",
        "schema_version": 1,
        "signed_token_count": len(TOKENS),
        "source_sha": source_sha,
        "tested_sha": tested_sha,
        "tokens": {
            token: {
                "artifact_sha256": validated[token]["artifact_sha256"],
                "signature_sha256": signer_results[token]["signature_sha256"],
            }
            for token in TOKENS
        },
        "verified_at": utc_text(utc_now()),
    }


def verify_frozen(deployment_id: str) -> None:
    root = FROZEN_ROOT / deployment_id
    if not root.is_dir() or root.is_symlink() or root.stat().st_uid != 0:
        raise OrchestratorError("frozen signed evidence is absent or unsafe")
    names = {path.name for path in root.iterdir()}
    if names != set(TOKENS):
        raise OrchestratorError("frozen signed evidence token set differs")
    for token in TOKENS:
        directory = root / token
        if (
            not directory.is_dir()
            or directory.is_symlink()
            or directory.stat().st_uid != 0
            or stat.S_IMODE(directory.stat().st_mode) != 0o700
        ):
            raise OrchestratorError("frozen token directory is unsafe")
        expected_names = {
            f"{token}.artifact",
            f"{token}.provenance.json",
            f"{token}.signature",
        }
        if {path.name for path in directory.iterdir()} != expected_names:
            raise OrchestratorError("frozen token file set differs")
        artifact = directory / f"{token}.artifact"
        provenance = directory / f"{token}.provenance.json"
        signature = directory / f"{token}.signature"
        for path in (artifact, provenance, signature):
            row = path.lstat()
            if (
                stat.S_ISLNK(row.st_mode)
                or not stat.S_ISREG(row.st_mode)
                or row.st_uid != 0
                or stat.S_IMODE(row.st_mode) != 0o400
                or row.st_nlink != 1
            ):
                raise OrchestratorError("frozen signed file is unsafe")
        completed = subprocess.run(
            [
                "/usr/bin/openssl",
                "dgst",
                "-sha256",
                "-verify",
                str(PUBLIC_KEY),
                "-signature",
                str(signature),
                str(provenance),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise OrchestratorError("frozen signature verification failed")


def worker_finalize(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve(strict=True)
    formal = args.formal_release_eligible == "true"
    now = utc_now()
    derive_showcase_artifact(
        runner_path=Path(args.runner_evidence),
        behavior_path=Path(args.behavior_evidence),
        output_path=output / "canary-showcase.artifact",
        deployment_id=args.deployment_id,
        tested_sha=args.tested_sha,
        evidence_class=args.evidence_class,
        principal_class=args.principal_class,
        formal_release_eligible=formal,
        now=now,
    )
    validate_output_directory(
        output,
        deployment_id=args.deployment_id,
        tested_sha=args.tested_sha,
        evidence_class=args.evidence_class,
        principal_class=args.principal_class,
        formal_release_eligible=formal,
        now=now,
    )
    print("protected runner produced seven validated artifacts")
    return 0


def execute(args: argparse.Namespace) -> int:
    _ensure_root()
    _verify_installed_helpers()
    formal = args.formal_release_eligible == "true"
    validate_mode(
        evidence_class=args.evidence_class,
        formal_release_eligible=formal,
        principal_class=args.principal_class,
        live_sha=args.live_sha,
        release_a_sha=args.release_a_sha,
        tested_sha=args.tested_sha,
        source_sha=args.source_sha,
    )
    if args.evidence_class == "release":
        raise OrchestratorError(
            "release mode requires the strict Release A SFTP producer, not acceptance SFTP"
        )
    source_root = _safe_source_root(Path(args.source_root), args.source_sha)
    username = _read_root_secret(Path(args.username_file), label="username")
    password = _read_root_secret(Path(args.password_file), label="password")
    issued_at = utc_now()
    authorization = _write_authorization(
        deployment_id=args.deployment_id,
        live_sha=args.live_sha,
        release_a_sha=args.release_a_sha,
        sftp_release_sha=args.sftp_release_sha,
        issued_at=issued_at,
    )
    job: Path | None = JOB_ROOT / args.deployment_id
    env_path: Path | None = JOB_ENV_ROOT / f"{args.deployment_id}.env"
    success = False
    try:
        job, env_path = _prepare_job(
            deployment_id=args.deployment_id,
            source_root=source_root,
            username=username,
            password=password,
            agentium_ip=args.agentium_ip,
            sftp_host_key_sha256=args.sftp_host_key_sha256,
            tested_sha=args.tested_sha,
            evidence_class=args.evidence_class,
            principal_class=args.principal_class,
            formal_release_eligible=formal,
            python_site=Path(args.python_site),
        )
        del username
        del password
        completed = subprocess.run(
            [str(RUNNER_EXECUTOR), args.deployment_id],
            stdin=subprocess.DEVNULL,
            check=False,
            timeout=2800,
            env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
        )
        if completed.returncode != 0:
            raise OrchestratorError("protected runner job failed")
        receipt = _stage_and_sign(
            output=job / "output",
            deployment_id=args.deployment_id,
            tested_sha=args.tested_sha,
            evidence_class=args.evidence_class,
            principal_class=args.principal_class,
            formal_release_eligible=formal,
            live_sha=args.live_sha,
            release_a_sha=args.release_a_sha,
            sftp_release_sha=args.sftp_release_sha,
            source_sha=args.source_sha,
        )
        success = True
        print(canonical_json(receipt).decode("utf-8"), end="")
        return 0
    finally:
        if job is not None:
            shutil.rmtree(job / "credentials", ignore_errors=True)
            shutil.rmtree(job, ignore_errors=True)
        if env_path is not None:
            env_path.unlink(missing_ok=True)
        if not success:
            # The authorization is useless after a failed transaction and must
            # not remain available for an accidental retry.
            authorization.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    worker = subparsers.add_parser("worker-finalize")
    worker.add_argument("--output", required=True)
    worker.add_argument("--deployment-id", required=True)
    worker.add_argument("--tested-sha", required=True)
    worker.add_argument("--evidence-class", choices=("acceptance", "release"), required=True)
    worker.add_argument(
        "--principal-class",
        choices=("operator_personal_admin", "automation_non_personal"),
        required=True,
    )
    worker.add_argument(
        "--formal-release-eligible",
        choices=("true", "false"),
        required=True,
    )
    worker.add_argument("--runner-evidence", required=True)
    worker.add_argument("--behavior-evidence", required=True)

    run = subparsers.add_parser("execute")
    run.add_argument("--deployment-id", required=True)
    run.add_argument("--source-root", required=True)
    run.add_argument("--source-sha", required=True)
    run.add_argument("--tested-sha", required=True)
    run.add_argument("--live-sha", required=True)
    run.add_argument("--release-a-sha", required=True)
    run.add_argument("--sftp-release-sha", required=True)
    run.add_argument("--agentium-ip", required=True)
    run.add_argument("--sftp-host-key-sha256", required=True)
    run.add_argument("--username-file", required=True)
    run.add_argument("--password-file", required=True)
    run.add_argument("--python-site", required=True)
    run.add_argument("--evidence-class", choices=("acceptance", "release"), required=True)
    run.add_argument(
        "--principal-class",
        choices=("operator_personal_admin", "automation_non_personal"),
        required=True,
    )
    run.add_argument(
        "--formal-release-eligible",
        choices=("true", "false"),
        required=True,
    )

    verify = subparsers.add_parser("verify-frozen")
    verify.add_argument("--deployment-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "worker-finalize":
            return worker_finalize(args)
        if args.command == "execute":
            return execute(args)
        if args.command == "verify-frozen":
            _ensure_root()
            _verify_installed_helpers()
            verify_frozen(args.deployment_id)
            print("frozen protected-runner evidence verified")
            return 0
        raise OrchestratorError("invalid command")
    except OrchestratorError as exc:
        print(f"protected runner orchestration failed: {exc}", file=sys.stderr)
        return 1
    except (OSError, subprocess.SubprocessError):
        print("protected runner orchestration failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
