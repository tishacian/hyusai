#!/usr/bin/env python3
"""Attest the Secure Deposit SFTP deployment boundary without credentials.

This helper has deliberately narrow proof surfaces:

* ``validation-ready`` proves that the already-started Release A SFTP
  container is the exact expected OCI image, remains restart-disabled behind
  all four deployment ingress rules, exposes SSH only through the tested
  loopback publication, and sees the dedicated Secure Deposit mount read-only
  in both host and container namespaces. It performs no authentication and
  emits a canonical, content-free receipt which a later positive canary can
  bind to.
* ``verify-runtime-identity-live`` re-reads that canonical receipt and proves
  that the exact same container process, image revision, host key and loopback
  binding are still live behind the closed ingress gates.  The caller declares
  the intentional Secure Deposit mode (``ro`` or ``rw``) and whether the
  restart policy must still be disabled or restored to the historical value.
* ``closed-boundary`` proves that SFTP is stopped, restart-disabled, protected
  by the deployment-specific IPv4/IPv6 ingress rules, and backed by the
  expected read-only Secure Deposit filesystem. The server image is pinned to
  ``--sftp-sha`` (the already-attested Release A), while ``--sha`` identifies
  the distinct Release B candidate.
* ``docker-protocol`` runs ``protocol-client`` from the already-running
  Release B candidate backend container against that pinned Release A server.
  The client completes SSH version/key exchange and asks the server for its
  authentication methods using SSH's ``none`` method. It never submits a
  password or opens the SFTP subsystem.
* ``host-banner`` proves that the published loopback host port carries SSH
  while the deployment-specific external ingress gate is still closed. It reads and
  validates the identification line but never serializes it.
* ``rollback-continuity`` starts from a fresh Release B ``closed-boundary``
  proof, then proves that the exact pinned SFTP container/image is still used
  by the restored previous runtime while ingress remains closed and the Secure
  Deposit remains read-only. Its SSH ``none`` probe compares the authentication
  audit inventory before/after without submitting credentials or reading SFTP
  content.

Every live protocol probe compares a content-free inventory of
``deposit.sftp.auth.*`` audit rows before and after the probe. Any addition,
removal, or modification fails the proof. No command accepts an SFTP username,
access id, password, private key, hostname, or IP address.

No command performs a positive login. Positive SFTP authentication belongs to
the Release A attestation which authorized the pinned server image; these
Release B proofs only establish continuity of that exact server while the
candidate client and its database audit inventory are exercised.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import errno
import hashlib
import json
import os
import re
import shlex
import socket
import stat as stat_module
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{12,64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{12,64}$")
FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{20,}={0,2}$")
SSH_IDENT_RE = re.compile(rb"^SSH-2\.0-[\x21-\x7e][\x20-\x7e]{0,252}\r?\n$")
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\."
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)
DOCKER_STARTED_AT_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?Z$"
)
DEVICE_SOURCE_RE = re.compile(
    r"^/dev/[A-Za-z0-9._:+-]+(?:/[A-Za-z0-9._:+-]+)*$"
)

PROFILE_CLOSED = "agentium-sftp-closed-boundary-v2"
PROFILE_PROTOCOL_CLIENT = "agentium-sftp-none-auth-client-v1"
PROFILE_DOCKER_PROTOCOL = "agentium-sftp-docker-protocol-v2"
PROFILE_HOST_BANNER = "agentium-sftp-published-banner-v2"
PROFILE_DB_INVENTORY = "agentium-sftp-auth-audit-inventory-v1"
PROFILE_ROLLBACK_CONTINUITY = "agentium-sftp-rollback-continuity-v1"

SFTP_CONTAINER = "agentium-sftp"
CLIENT_CONTAINER = "agentium-backend"
EXPECTED_NETWORK = "agentium-net"
SFTP_CONTAINER_PORT = 2222
SFTP_CONTAINER_ROOT = PurePosixPath("/data/secure_deposit")
DEFAULT_CONTAINER_HOST_KEY = PurePosixPath("/data/secure_deposit/sftp_host_key")
RELEASE_A_SECURE_SOURCE = "/dev/sdc"
LEGACY_SFTP_UNIT = "agentium-sftp.service"
GATE_PREFIX = "agentium-safe-sftp-"
PROBE_TIMEOUT_SECONDS = 5.0
MAX_IDENTIFICATION_BYTES = 255
MAX_VALIDATION_PROOF_BYTES = 8 * 1024 * 1024
MAX_RUNTIME_STATE_BYTES = 1024 * 1024
MAX_CLOSED_PROOF_BYTES = 1024 * 1024
ROLLBACK_CLOSED_MAX_AGE_SECONDS = 300
SAFE_NONE_AUTH_RESPONSE_METHODS = frozenset({"keyboard-interactive", "password"})

# This principal is used only in SSH_MSG_USERAUTH_REQUEST(method="none"). The
# server's begin_auth() is intentionally reached, while validate_password() is
# not. It is never serialized in a proof or included in an error message.
_AUTH_METHOD_PROBE_PRINCIPAL = "agentium-safe-protocol-probe"


class SFTPBoundaryError(RuntimeError):
    """Fail-closed error whose message contains no runtime content."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _validate_identity(sha: str, deployment_id: str) -> None:
    if SHA_RE.fullmatch(sha) is None:
        raise SFTPBoundaryError("sha must be a complete lowercase Git SHA")
    if DEPLOYMENT_ID_RE.fullmatch(deployment_id) is None:
        raise SFTPBoundaryError("deployment-id is invalid")


def _validate_release_a_identity(
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
) -> None:
    _validate_identity(live_sha, deployment_id)
    _validate_identity(release_a_sha, deployment_id)
    if SHA_RE.fullmatch(sftp_sha) is None:
        raise SFTPBoundaryError(
            "sftp-sha must be a complete lowercase Git SHA"
        )
    if live_sha == release_a_sha:
        raise SFTPBoundaryError("live-sha must differ from release-a-sha")


def runtime_identity_sha256(
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    hostname_sha256: str,
    sftp_container_id: str,
    sftp_image_id: str,
    sftp_port: int,
    sftp_started_at: str,
) -> str:
    """Return the positive-canary Release A runtime identity digest."""

    digest = hashlib.sha256(b"agentium-release-a-sftp-runtime-identity-v1")
    for value in (
        live_sha,
        release_a_sha,
        sftp_sha,
        deployment_id,
        hostname_sha256,
        sftp_container_id,
        sftp_image_id,
        str(sftp_port),
        sftp_started_at,
    ):
        digest.update(b"\0")
        digest.update(value.encode("utf-8"))
    return digest.hexdigest()


def _parse_utc_timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str) or DOCKER_STARTED_AT_RE.fullmatch(value) is None:
        raise SFTPBoundaryError(f"{label} timestamp is invalid")
    raw = value[:-1]
    if "." in raw:
        prefix, fraction = raw.rsplit(".", 1)
        raw = f"{prefix}.{(fraction + '000000')[:6]}"
    try:
        parsed = datetime.fromisoformat(raw + "+00:00").astimezone(UTC)
    except ValueError as exc:
        raise SFTPBoundaryError(f"{label} timestamp is invalid") from exc
    if parsed.year < 2000:
        raise SFTPBoundaryError(f"{label} timestamp is invalid")
    return parsed


def _validate_boundary_identity(
    sha: str, sftp_sha: str, deployment_id: str
) -> None:
    _validate_identity(sha, deployment_id)
    if SHA_RE.fullmatch(sftp_sha) is None:
        raise SFTPBoundaryError("sftp-sha must be a complete lowercase Git SHA")
    if sftp_sha == sha:
        raise SFTPBoundaryError("sftp-sha must differ from the candidate SHA")


def _validate_rollback_identity(
    previous_sha: str,
    candidate_sha: str,
    sftp_sha: str,
    deployment_id: str,
) -> None:
    _validate_identity(previous_sha, deployment_id)
    if SHA_RE.fullmatch(candidate_sha) is None:
        raise SFTPBoundaryError("candidate-sha must be a complete lowercase Git SHA")
    if SHA_RE.fullmatch(sftp_sha) is None:
        raise SFTPBoundaryError("sftp-sha must be a complete lowercase Git SHA")
    if previous_sha == candidate_sha:
        raise SFTPBoundaryError("previous runtime SHA must differ from candidate-sha")
    if candidate_sha == sftp_sha:
        raise SFTPBoundaryError("sftp-sha must differ from candidate-sha")


def _revision_binding(
    sha: str, sftp_sha: str, *, client_image_revision_verified: bool
) -> dict[str, Any]:
    return {
        "candidate_sha": sha,
        "client_sha": sha,
        "sftp_sha": sftp_sha,
        "revisions_distinct": True,
        "client_image_revision_verified": client_image_revision_verified,
        "sftp_image_revision_verified": True,
    }


def _canonical(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise SFTPBoundaryError("database audit inventory contains an invalid number")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"bytes_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Mapping):
        return {str(key): _canonical(child) for key, child in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_canonical(child) for child in value]
    return str(value)


def _json_sha256(value: Any) -> str:
    encoded = json.dumps(
        _canonical(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run(
    command: Sequence[str],
    *,
    timeout: float = 30.0,
    accepted_codes: frozenset[int] = frozenset({0}),
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SFTPBoundaryError("required boundary command could not run") from exc
    if completed.returncode not in accepted_codes:
        # stdout/stderr and argv are intentionally excluded: they can contain
        # network addresses, filesystem paths, or SSH identification strings.
        raise SFTPBoundaryError("required boundary command failed")
    return completed


def _run_text(command: Sequence[str], *, timeout: float = 30.0) -> str:
    return _run(command, timeout=timeout).stdout.strip()


def _run_json(command: Sequence[str], *, timeout: float = 30.0) -> Any:
    raw = _run_text(command, timeout=timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SFTPBoundaryError("required boundary command returned invalid JSON") from exc


def _docker_inspect(name: str) -> dict[str, Any]:
    payload = _run_json(["docker", "inspect", name])
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise SFTPBoundaryError("Docker inspection is invalid")
    return payload[0]


def _container_id(inspect_payload: Mapping[str, Any]) -> str:
    value = str(inspect_payload.get("Id") or "")
    if CONTAINER_ID_RE.fullmatch(value) is None:
        raise SFTPBoundaryError("container identity is invalid")
    return value


def _image_id(inspect_payload: Mapping[str, Any]) -> str:
    value = str(inspect_payload.get("Image") or "")
    if IMAGE_ID_RE.fullmatch(value) is None:
        raise SFTPBoundaryError("container image identity is invalid")
    return value


def _image_revision(image_id: str) -> str:
    payload = _run_json(["docker", "image", "inspect", image_id])
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise SFTPBoundaryError("Docker image inspection is invalid")
    config = payload[0].get("Config")
    if not isinstance(config, dict):
        raise SFTPBoundaryError("Docker image configuration is invalid")
    labels = config.get("Labels", {})
    if not isinstance(labels, dict):
        raise SFTPBoundaryError("Docker image labels are invalid")
    return str(labels.get("org.opencontainers.image.revision") or "")


def _networks(inspect_payload: Mapping[str, Any]) -> set[str]:
    raw = inspect_payload.get("NetworkSettings", {}).get("Networks", {})
    if not isinstance(raw, dict):
        raise SFTPBoundaryError("Docker network inventory is invalid")
    return {str(value) for value in raw}


def _restart_is_disabled(inspect_payload: Mapping[str, Any]) -> bool:
    host_config = inspect_payload.get("HostConfig")
    if not isinstance(host_config, dict):
        return False
    policy = host_config.get("RestartPolicy", {})
    return (
        isinstance(policy, dict)
        and policy.get("Name") == "no"
        and int(policy.get("MaximumRetryCount") or 0) == 0
    )


def _published_sftp_port(inspect_payload: Mapping[str, Any]) -> int:
    host_config = inspect_payload.get("HostConfig")
    if not isinstance(host_config, dict):
        raise SFTPBoundaryError("SFTP host configuration is invalid")
    bindings = host_config.get("PortBindings", {})
    if not isinstance(bindings, dict):
        raise SFTPBoundaryError("SFTP port binding inventory is invalid")
    rows = bindings.get(f"{SFTP_CONTAINER_PORT}/tcp")
    if not isinstance(rows, list) or not rows:
        raise SFTPBoundaryError("SFTP published port is absent")
    ports = {
        str(row.get("HostPort") or "")
        for row in rows
        if isinstance(row, dict)
    }
    if len(ports) != 1:
        raise SFTPBoundaryError("SFTP published port is ambiguous")
    raw_port = next(iter(ports))
    if not raw_port.isdigit() or not 1 <= int(raw_port) <= 65535:
        raise SFTPBoundaryError("SFTP published port is invalid")
    return int(raw_port)


def _rule_tokens_are_exact(
    line: str,
    *,
    chain: str,
    host_port: int,
    comment: str,
) -> bool:
    try:
        tokens = shlex.split(line)
    except ValueError:
        return False

    def has_pair(flag: str, expected: str) -> bool:
        return any(
            tokens[index] == flag and tokens[index + 1] == expected
            for index in range(len(tokens) - 1)
        )

    port_flag = "--ctorigdstport" if chain == "DOCKER-USER" else "--dport"
    return all(
        (
            has_pair("-A", chain),
            has_pair("-p", "tcp"),
            has_pair(port_flag, str(host_port)),
            has_pair("--ctstate", "NEW"),
            has_pair("--comment", comment),
            has_pair("-j", "REJECT"),
            has_pair("--reject-with", "tcp-reset"),
            any(tokens[index : index + 3] == ["!", "-i", "lo"] for index in range(len(tokens) - 2)),
        )
    )


def _gate_contract(*, deployment_id: str, host_port: int, expected_closed: bool) -> dict[str, bool]:
    comment = f"{GATE_PREFIX}{deployment_id}"
    result: dict[str, bool] = {}
    for family, tool, save_tool in (
        ("ipv4", "iptables", "iptables-save"),
        ("ipv6", "ip6tables", "ip6tables-save"),
    ):
        dump = _run_text(["sudo", "-n", save_tool], timeout=15)
        lines = dump.splitlines()
        foreign = [
            line
            for line in lines
            if GATE_PREFIX in line and comment not in line
        ]
        if foreign:
            raise SFTPBoundaryError("a foreign SFTP deployment gate is present")
        for chain in ("INPUT", "DOCKER-USER"):
            current = [line for line in lines if comment in line and f"-A {chain} " in line]
            key = f"{family}_{chain.lower().replace('-', '_')}"
            if expected_closed:
                if len(current) != 1 or not _rule_tokens_are_exact(
                    current[0], chain=chain, host_port=host_port, comment=comment
                ):
                    raise SFTPBoundaryError("SFTP ingress gate is incomplete or ambiguous")
                check = [
                    "sudo",
                    "-n",
                    tool,
                    "-w",
                    "10",
                    "-C",
                    chain,
                    "!",
                    "-i",
                    "lo",
                    "-p",
                    "tcp",
                ]
                if chain == "DOCKER-USER":
                    check += ["-m", "conntrack", "--ctorigdstport", str(host_port)]
                else:
                    check += ["--dport", str(host_port), "-m", "conntrack"]
                check += [
                    "--ctstate",
                    "NEW",
                    "-m",
                    "comment",
                    "--comment",
                    comment,
                    "-j",
                    "REJECT",
                    "--reject-with",
                    "tcp-reset",
                ]
                _run(check, timeout=15)
                result[key] = True
            else:
                if current:
                    raise SFTPBoundaryError("SFTP ingress gate remains installed")
                result[key] = False
    return result


def _listener_count(host_port: int) -> int:
    output = _run_text(
        ["sudo", "-n", "ss", "-Hltpn", f"sport = :{host_port}"],
        timeout=15,
    )
    return len([line for line in output.splitlines() if line.strip()])


def _established_connection_count(host_port: int) -> int:
    output = _run_text(
        [
            "sudo",
            "-n",
            "ss",
            "-Htn",
            "state",
            "established",
            f"sport = :{host_port}",
        ],
        timeout=15,
    )
    return len([line for line in output.splitlines() if line.strip()])


def _normalize_device_source(value: str) -> str:
    candidate = value.split("[", 1)[0]
    return os.path.realpath(candidate) if candidate.startswith("/dev/") else candidate


def _validate_expected_secure_source(value: str) -> str:
    if (
        not isinstance(value, str)
        or DEVICE_SOURCE_RE.fullmatch(value) is None
        or any(part in {".", ".."} for part in PurePosixPath(value).parts)
    ):
        raise SFTPBoundaryError("expected Secure Deposit source must be a /dev device path")
    return value


def _secure_mount_contract(
    inspect_payload: Mapping[str, Any], *, expected_source: str, expected_mode: str = "ro"
) -> tuple[dict[str, Any], Path]:
    if expected_mode not in {"ro", "rw"}:
        raise SFTPBoundaryError("Secure Deposit expected mode is invalid")
    mounts = inspect_payload.get("Mounts")
    if not isinstance(mounts, list):
        raise SFTPBoundaryError("SFTP mount inventory is invalid")
    candidates = [
        row
        for row in mounts
        if isinstance(row, dict)
        and row.get("Type") == "bind"
        and row.get("Destination") == str(SFTP_CONTAINER_ROOT)
    ]
    if len(candidates) != 1:
        raise SFTPBoundaryError("Secure Deposit bind mount is absent or ambiguous")
    secure_root = Path(str(candidates[0].get("Source") or ""))
    if not secure_root.is_absolute() or ".." in secure_root.parts:
        raise SFTPBoundaryError("Secure Deposit bind source is invalid")
    try:
        secure_root = secure_root.resolve(strict=True)
    except OSError as exc:
        raise SFTPBoundaryError("Secure Deposit bind source is unavailable") from exc

    payload = _run_json(
        [
            "findmnt",
            "--json",
            "--output",
            "SOURCE,TARGET,OPTIONS",
            "--target",
            str(secure_root),
        ]
    )
    try:
        rows = payload["filesystems"]
        row = rows[0]
        source = str(row["source"])
        target = Path(str(row["target"])).resolve(strict=True)
        options = {part for part in str(row["options"]).split(",") if part}
    except (KeyError, IndexError, TypeError, OSError) as exc:
        raise SFTPBoundaryError("Secure Deposit mount state is invalid") from exc
    if len(rows) != 1 or target != secure_root:
        raise SFTPBoundaryError("Secure Deposit is not an autonomous mountpoint")
    if _normalize_device_source(source) != _normalize_device_source(expected_source):
        raise SFTPBoundaryError("Secure Deposit backing device is unexpected")
    if expected_mode not in options or ({"ro", "rw"} - {expected_mode}) & options:
        raise SFTPBoundaryError(
            f"Secure Deposit is not mounted {expected_mode} as required"
        )
    return (
        {
            "source_matches_expected": True,
            "autonomous_mountpoint": True,
            "read_only": expected_mode == "ro",
            "device_id": os.stat(secure_root).st_dev,
        },
        secure_root,
    )


def _container_environment(inspect_payload: Mapping[str, Any]) -> dict[str, str]:
    config = inspect_payload.get("Config")
    if not isinstance(config, dict):
        raise SFTPBoundaryError("container configuration inventory is invalid")
    raw = config.get("Env", [])
    if not isinstance(raw, list):
        raise SFTPBoundaryError("container environment inventory is invalid")
    result: dict[str, str] = {}
    for item in raw:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            result[key] = value
    return result


def _host_key_path(inspect_payload: Mapping[str, Any], secure_root: Path) -> Path:
    configured = _container_environment(inspect_payload).get(
        "SECURE_DEPOSIT_SFTP_HOST_KEY_PATH", str(DEFAULT_CONTAINER_HOST_KEY)
    )
    container_path = PurePosixPath(configured)
    if not container_path.is_absolute() or ".." in container_path.parts:
        raise SFTPBoundaryError("SFTP host-key binding is invalid")
    try:
        relative = container_path.relative_to(SFTP_CONTAINER_ROOT)
    except ValueError as exc:
        raise SFTPBoundaryError("SFTP host key is outside Secure Deposit") from exc
    candidate = secure_root.joinpath(*relative.parts)
    resolved_parent = candidate.parent.resolve(strict=True)
    if resolved_parent != secure_root and secure_root not in resolved_parent.parents:
        raise SFTPBoundaryError("SFTP host-key binding escapes Secure Deposit")
    return candidate


def _host_key_fingerprint(host_key: Path) -> dict[str, Any]:
    if _run(["sudo", "-n", "test", "-f", str(host_key)], accepted_codes=frozenset({0, 1})).returncode:
        raise SFTPBoundaryError("SFTP host key is absent")
    if _run(["sudo", "-n", "test", "-s", str(host_key)], accepted_codes=frozenset({0, 1})).returncode:
        raise SFTPBoundaryError("SFTP host key is empty")
    if _run(["sudo", "-n", "test", "-L", str(host_key)], accepted_codes=frozenset({0, 1})).returncode == 0:
        raise SFTPBoundaryError("SFTP host key cannot be a symbolic link")
    raw = _run_text(
        ["sudo", "-n", "ssh-keygen", "-E", "sha256", "-lf", str(host_key)],
        timeout=15,
    )
    fields = raw.split()
    if len(fields) < 4 or not fields[0].isdigit():
        raise SFTPBoundaryError("SFTP host-key fingerprint is invalid")
    fingerprint = fields[1]
    algorithm = fields[-1].strip("()").upper()
    if FINGERPRINT_RE.fullmatch(fingerprint) is None or algorithm != "ED25519":
        raise SFTPBoundaryError("SFTP host key is not the expected Ed25519 key")
    return {
        "present": True,
        "nonempty": True,
        "regular_file": True,
        "symlink": False,
        "algorithm": "ssh-ed25519",
        "fingerprint": fingerprint,
    }


def _runtime_hostname_sha256() -> str:
    hostname = _run_text(["hostname", "-f"], timeout=10).lower()
    if HOSTNAME_RE.fullmatch(hostname) is None:
        raise SFTPBoundaryError("runtime hostname is invalid")
    return hashlib.sha256(hostname.encode("utf-8")).hexdigest()


def _published_binding_contract(
    inspect_payload: Mapping[str, Any], *, host_port: int
) -> dict[str, Any]:
    host_config = inspect_payload.get("HostConfig")
    if not isinstance(host_config, dict):
        raise SFTPBoundaryError("SFTP host configuration is invalid")
    bindings = host_config.get("PortBindings")
    if not isinstance(bindings, dict):
        raise SFTPBoundaryError("SFTP port binding inventory is invalid")
    rows = bindings.get(f"{SFTP_CONTAINER_PORT}/tcp")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2:
        raise SFTPBoundaryError("SFTP published binding is absent or ambiguous")
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SFTPBoundaryError("SFTP published binding is invalid")
        raw_ip = str(row.get("HostIp") or "0.0.0.0")
        raw_port = str(row.get("HostPort") or "")
        if raw_ip not in {"127.0.0.1", "::1"}:
            raise SFTPBoundaryError("SFTP published binding is not loopback-only")
        try:
            parsed_ip = socket.inet_pton(
                socket.AF_INET6 if ":" in raw_ip else socket.AF_INET,
                raw_ip,
            )
        except OSError as exc:
            raise SFTPBoundaryError("SFTP published binding address is invalid") from exc
        if not raw_port.isdigit() or int(raw_port) != host_port:
            raise SFTPBoundaryError("SFTP published binding port differs")
        family = "ipv6" if len(parsed_ip) == 16 else "ipv4"
        identity = (raw_ip, host_port)
        if identity in seen:
            raise SFTPBoundaryError("SFTP published binding is duplicated")
        seen.add(identity)
        normalized.append(
            {
                "family": family,
                "host_address": raw_ip,
                "host_port": host_port,
            }
        )
    normalized.sort(key=lambda value: (value["family"], value["host_address"]))
    return {
        "binding_count": len(normalized),
        "binding_sha256": _json_sha256(normalized),
    }


def _secure_namespace_mode(
    expected_mode: str, *, inspect_payload: Mapping[str, Any] | None = None
) -> str:
    if expected_mode not in {"ro", "rw"}:
        raise SFTPBoundaryError("Secure Deposit namespace mode is invalid")
    inspected = inspect_payload or _docker_inspect(SFTP_CONTAINER)
    state = inspected.get("State")
    if not isinstance(state, dict):
        raise SFTPBoundaryError("SFTP namespace process state is invalid")
    pid = state.get("Pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise SFTPBoundaryError("SFTP namespace process is unavailable")
    mountinfo = _run_text(
        ["sudo", "-n", "cat", f"/proc/{pid}/mountinfo"], timeout=15
    )
    matches: list[set[str]] = []
    for raw in mountinfo.splitlines():
        fields = raw.split()
        if len(fields) < 10 or "-" not in fields:
            continue
        if fields[4] == str(SFTP_CONTAINER_ROOT):
            separator = fields.index("-")
            if separator + 3 >= len(fields):
                raise SFTPBoundaryError("SFTP namespace mountinfo is invalid")
            matches.append(
                {
                    option
                    for option in fields[5].split(",")
                    if option
                }
            )
    if len(matches) != 1:
        raise SFTPBoundaryError("Secure Deposit namespace mount is ambiguous")
    options = matches[0]
    if expected_mode not in options or ({"ro", "rw"} - {expected_mode}) & options:
        raise SFTPBoundaryError("Secure Deposit namespace mode differs")
    return expected_mode


def _secure_namespace_read_only() -> bool:
    _secure_namespace_mode("ro")
    return True


def _restart_policy(inspect_payload: Mapping[str, Any]) -> tuple[str, int]:
    host_config = inspect_payload.get("HostConfig")
    if not isinstance(host_config, dict):
        raise SFTPBoundaryError("SFTP host configuration is invalid")
    value = host_config.get("RestartPolicy")
    if not isinstance(value, dict):
        raise SFTPBoundaryError("SFTP restart policy is invalid")
    name = value.get("Name")
    maximum = value.get("MaximumRetryCount")
    if (
        name not in {"no", "always", "unless-stopped", "on-failure"}
        or isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or maximum < 0
        or (name != "on-failure" and maximum != 0)
    ):
        raise SFTPBoundaryError("SFTP restart policy is invalid")
    return str(name), maximum


def _validation_runtime_identity(
    inspect_payload: Mapping[str, Any], *, sftp_sha: str,
    expected_restart_policy: tuple[str, int] = ("no", 0),
    allow_paused: bool = False,
) -> dict[str, Any]:
    state = inspect_payload.get("State")
    if not isinstance(state, dict):
        raise SFTPBoundaryError("Release A SFTP runtime state is invalid")
    health = state.get("Health")
    paused = state.get("Paused")
    if (
        state.get("Running") is not True
        or not (paused is False or (allow_paused and paused is True))
        or state.get("Restarting") not in {False, None}
        or state.get("Dead") not in {False, None}
        or isinstance(state.get("Pid"), bool)
        or not isinstance(state.get("Pid"), int)
        or state.get("Pid", 0) <= 0
        or not isinstance(health, dict)
        or health.get("Status") != "healthy"
    ):
        raise SFTPBoundaryError("Release A SFTP runtime is not healthy and running")
    restart_policy = _restart_policy(inspect_payload)
    if restart_policy != expected_restart_policy:
        raise SFTPBoundaryError("Release A SFTP restart policy differs")
    container_id = _container_id(inspect_payload)
    image_id = _assert_image_revision(inspect_payload, sftp_sha)
    if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
        raise SFTPBoundaryError("Release A SFTP container ID is not exact")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise SFTPBoundaryError("Release A SFTP image ID is not exact")
    started_at = state.get("StartedAt")
    _parse_utc_timestamp(started_at, label="SFTP StartedAt")
    return {
        "container_id": container_id,
        "image_id": image_id,
        "image_revision": sftp_sha,
        "image_revision_verified": True,
        "started_at": started_at,
        "running": True,
        "paused": paused,
        "healthy": True,
        "restart_policy_disabled": restart_policy == ("no", 0),
        "restart_policy": {
            "name": restart_policy[0],
            "maximum_retry_count": restart_policy[1],
        },
    }


def _validation_gate_contract(value: Mapping[str, Any]) -> dict[str, bool]:
    expected = {
        "ipv4_input": True,
        "ipv4_docker_user": True,
        "ipv6_input": True,
        "ipv6_docker_user": True,
    }
    if dict(value) != expected:
        raise SFTPBoundaryError("Release A SFTP ingress gate is not fully closed")
    return expected


def _validation_secure_deposit_contract(
    value: Mapping[str, Any], *, namespace_read_only: bool
) -> dict[str, Any]:
    device_id = value.get("device_id")
    if (
        value.get("source_matches_expected") is not True
        or value.get("autonomous_mountpoint") is not True
        or value.get("read_only") is not True
        or namespace_read_only is not True
        or isinstance(device_id, bool)
        or not isinstance(device_id, int)
        or device_id <= 0
    ):
        raise SFTPBoundaryError(
            "Release A Secure Deposit is not autonomous and read-only"
        )
    return {
        "source_matches_dev_sdc": True,
        "source_device_sha256": hashlib.sha256(
            RELEASE_A_SECURE_SOURCE.encode("ascii")
        ).hexdigest(),
        "autonomous_mountpoint": True,
        "host_read_only": True,
        "namespace_autonomous_mountpoint": True,
        "namespace_read_only": True,
        "device_id": device_id,
    }


def _validation_host_key_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    fingerprint = str(value.get("fingerprint") or "")
    if (
        set(value)
        != {
            "present",
            "nonempty",
            "regular_file",
            "symlink",
            "algorithm",
            "fingerprint",
        }
        or value.get("present") is not True
        or value.get("nonempty") is not True
        or value.get("regular_file") is not True
        or value.get("symlink") is not False
        or value.get("algorithm") != "ssh-ed25519"
        or FINGERPRINT_RE.fullmatch(fingerprint) is None
    ):
        raise SFTPBoundaryError("Release A SFTP host key is not pinned Ed25519")
    return {
        "algorithm": "ssh-ed25519",
        "fingerprint": fingerprint,
        "fingerprint_sha256": hashlib.sha256(
            fingerprint.encode("ascii")
        ).hexdigest(),
        "present": True,
        "nonempty": True,
        "regular_file": True,
        "symlink": False,
    }


def _negative_loopback_connect(host_port: int, family: int) -> bool:
    address: tuple[Any, ...]
    if family == socket.AF_INET:
        address = ("127.0.0.1", host_port)
    elif family == socket.AF_INET6:
        address = ("::1", host_port, 0, 0)
    else:  # pragma: no cover - callers are fixed
        raise SFTPBoundaryError("unsupported network family")
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(2.0)
        result = sock.connect_ex(address)
    except OSError as exc:
        result = int(exc.errno or 0)
    finally:
        sock.close()
    if result != errno.ECONNREFUSED:
        raise SFTPBoundaryError("closed SFTP transport did not reject immediately")
    return True


def _assert_image_revision(inspect_payload: Mapping[str, Any], sha: str) -> str:
    image_id = _image_id(inspect_payload)
    if _image_revision(image_id) != sha:
        raise SFTPBoundaryError("container image revision differs from its required SHA")
    return image_id


def _validation_loopback_transport(value: Mapping[str, Any]) -> dict[str, bool]:
    expected = {
        "ssh_v2_identification_validated": True,
        "raw_identification_serialized": False,
        "connection_closed_before_authentication": True,
    }
    if dict(value) != expected:
        raise SFTPBoundaryError(
            "Release A SFTP loopback transport proof is invalid"
        )
    return {
        "ssh_v2_identification_validated": True,
        "connection_closed_before_authentication": True,
        "raw_identification_serialized": False,
    }


def build_validation_ready_contract(
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    expected_secure_source: str,
) -> dict[str, Any]:
    """Attest the exact running Release A SFTP boundary before positive auth."""

    _validate_release_a_identity(live_sha, release_a_sha, sftp_sha, deployment_id)
    expected_secure_source = _validate_expected_secure_source(
        expected_secure_source
    )
    if expected_secure_source != RELEASE_A_SECURE_SOURCE:
        raise SFTPBoundaryError("Release A Secure Deposit source must be /dev/sdc")

    sftp_before = _docker_inspect(SFTP_CONTAINER)
    runtime = _validation_runtime_identity(sftp_before, sftp_sha=sftp_sha)
    host_port = _published_sftp_port(sftp_before)
    binding = _published_binding_contract(sftp_before, host_port=host_port)
    gate_before = _validation_gate_contract(
        _gate_contract(
            deployment_id=deployment_id,
            host_port=host_port,
            expected_closed=True,
        )
    )
    listeners_before = _listener_count(host_port)
    connections_before = _established_connection_count(host_port)
    if listeners_before < 1:
        raise SFTPBoundaryError("Release A SFTP published listener is absent")
    if connections_before != 0:
        raise SFTPBoundaryError(
            "Release A SFTP retains an established external connection"
        )

    secure_before_raw, secure_root_before = _secure_mount_contract(
        sftp_before, expected_source=expected_secure_source
    )
    secure_before = _validation_secure_deposit_contract(
        secure_before_raw,
        namespace_read_only=_secure_namespace_read_only(),
    )
    host_key_before = _validation_host_key_contract(
        _host_key_fingerprint(_host_key_path(sftp_before, secure_root_before))
    )
    loopback = _validation_loopback_transport(
        _read_published_ssh_identification(host_port)
    )

    # Re-read every mutable boundary after the live socket probe. A receipt
    # must describe one stable runtime, not a mix of pre/post-restart facts.
    sftp_after = _docker_inspect(SFTP_CONTAINER)
    runtime_after = _validation_runtime_identity(sftp_after, sftp_sha=sftp_sha)
    host_port_after = _published_sftp_port(sftp_after)
    binding_after = _published_binding_contract(
        sftp_after, host_port=host_port_after
    )
    gate_after = _validation_gate_contract(
        _gate_contract(
            deployment_id=deployment_id,
            host_port=host_port_after,
            expected_closed=True,
        )
    )
    listeners_after = _listener_count(host_port_after)
    connections_after = _established_connection_count(host_port_after)
    secure_after_raw, secure_root_after = _secure_mount_contract(
        sftp_after, expected_source=expected_secure_source
    )
    secure_after = _validation_secure_deposit_contract(
        secure_after_raw,
        namespace_read_only=_secure_namespace_read_only(),
    )
    host_key_after = _validation_host_key_contract(
        _host_key_fingerprint(_host_key_path(sftp_after, secure_root_after))
    )
    if (
        runtime_after != runtime
        or host_port_after != host_port
        or binding_after != binding
        or gate_after != gate_before
        or secure_after != secure_before
        or host_key_after != host_key_before
    ):
        raise SFTPBoundaryError("Release A SFTP boundary changed during proof")
    if listeners_after < 1:
        raise SFTPBoundaryError("Release A SFTP published listener disappeared")
    if connections_after != 0:
        raise SFTPBoundaryError(
            "Release A SFTP retains an established external connection"
        )

    ready_at = _utc_now()
    ready_timestamp = _parse_utc_timestamp(ready_at, label="SFTP ready_at")
    started_timestamp = _parse_utc_timestamp(
        runtime["started_at"], label="SFTP StartedAt"
    )
    if started_timestamp > ready_timestamp:
        raise SFTPBoundaryError("SFTP StartedAt is later than ready_at")

    hostname_sha256 = _runtime_hostname_sha256()
    runtime_digest = runtime_identity_sha256(
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        hostname_sha256=hostname_sha256,
        sftp_container_id=runtime["container_id"],
        sftp_image_id=runtime["image_id"],
        sftp_port=host_port,
        sftp_started_at=runtime["started_at"],
    )
    return {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-runtime-ready",
        "result": "passed",
        "live_sha": live_sha,
        "deployment_id": deployment_id,
        "release_a_sha": release_a_sha,
        "sftp_sha": sftp_sha,
        "hostname_sha256": hostname_sha256,
        "sftp_container_id": runtime["container_id"],
        "sftp_image_id": runtime["image_id"],
        "image_revision": runtime["image_revision"],
        "sftp_port": host_port,
        "sftp_started_at": runtime["started_at"],
        "runtime_identity_sha256": runtime_digest,
        "host_key_fingerprint": host_key_after["fingerprint"],
        "state": "running",
        "health_status": "healthy",
        "ingress_closed": True,
        "restart_disabled": True,
        "restart_policy_disabled": True,
        "secure_deposit_mode": "ro",
        "secure_deposit_source": RELEASE_A_SECURE_SOURCE,
        "external_established_connection_count": 0,
        "ready_at": ready_at,
        "ingress_gate": gate_after,
        "published_transport": {
            "protocol": "tcp",
            "container_port": SFTP_CONTAINER_PORT,
            "host_port": host_port,
            "binding_count": binding["binding_count"],
            "binding_sha256": binding["binding_sha256"],
            "listener_count": listeners_after,
            "established_connection_count_before": 0,
            "established_connection_count_after": 0,
            "external_established_connection_count": 0,
            **loopback,
        },
        "secure_deposit": secure_after,
        "host_key": host_key_after,
        "credentials_used": False,
        "authentication_attempted": False,
        "sftp_subsystem_requested": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
        "raw_identification_serialized": False,
    }


def build_closed_boundary_contract(
    *,
    sha: str,
    sftp_sha: str,
    deployment_id: str,
    expected_secure_source: str,
) -> dict[str, Any]:
    _validate_boundary_identity(sha, sftp_sha, deployment_id)
    expected_secure_source = _validate_expected_secure_source(expected_secure_source)
    sftp = _docker_inspect(SFTP_CONTAINER)
    state = sftp.get("State", {})
    if not isinstance(state, dict):
        raise SFTPBoundaryError("SFTP container state is invalid")
    if state.get("Running") is not False or state.get("Paused") is not False:
        raise SFTPBoundaryError("SFTP container is not stopped and unpaused")
    if int(state.get("Pid") or 0) != 0:
        raise SFTPBoundaryError("stopped SFTP container retains a process")
    if not _restart_is_disabled(sftp):
        raise SFTPBoundaryError("SFTP restart policy is not disabled")
    container_id = _container_id(sftp)
    image_id = _assert_image_revision(sftp, sftp_sha)
    host_port = _published_sftp_port(sftp)
    gates = _gate_contract(
        deployment_id=deployment_id,
        host_port=host_port,
        expected_closed=True,
    )
    listeners = _listener_count(host_port)
    connections = _established_connection_count(host_port)
    if listeners or connections:
        raise SFTPBoundaryError("closed SFTP transport retains network activity")
    active_state = _run_text(
        ["systemctl", "show", LEGACY_SFTP_UNIT, "--property", "ActiveState", "--value"]
    )
    unit_state = _run_text(
        ["systemctl", "show", LEGACY_SFTP_UNIT, "--property", "UnitFileState", "--value"]
    )
    if active_state != "inactive" or unit_state != "disabled":
        raise SFTPBoundaryError("legacy SFTP service is not inactive and disabled")
    mount, secure_root = _secure_mount_contract(
        sftp, expected_source=expected_secure_source
    )
    host_key = _host_key_fingerprint(_host_key_path(sftp, secure_root))
    ipv4_rejected = _negative_loopback_connect(host_port, socket.AF_INET)
    ipv6_rejected = _negative_loopback_connect(host_port, socket.AF_INET6)
    return {
        "schema_version": 2,
        "kind": "agentium_sftp_deploy_boundary",
        "profile": PROFILE_CLOSED,
        "sha": sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "captured_at": _utc_now(),
        "result": "passed",
        "container": {
            "container_id": container_id,
            "image_id": image_id,
            "revision": sftp_sha,
            "running": False,
            "paused": False,
            "process_count": 0,
            "secure_deposit_open_fd_count": 0,
            "restart_policy_disabled": True,
        },
        "legacy_service": {"active": False, "enabled": False},
        "ingress_gate": gates,
        "network": {
            "listener_count": listeners,
            "established_connection_count": connections,
            "ipv4_connect_rejected": ipv4_rejected,
            "ipv6_connect_rejected": ipv6_rejected,
        },
        "secure_deposit": mount,
        "host_key": host_key,
        "revision_binding": _revision_binding(
            sha, sftp_sha, client_image_revision_verified=False
        ),
        "credentials_used": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
        "assurance": "release_a_sftp_pinned_stopped_restart_disabled_ingress_rejected_storage_read_only_without_positive_login",
        "proof_ceiling": "runner_verified",
    }


def _auth_inventory_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        values = dict(row)
        primary_key = values.get("id")
        primary_key_sha256 = _json_sha256([primary_key])
        if primary_key_sha256 in seen:
            raise SFTPBoundaryError("SFTP auth audit inventory has duplicate identities")
        seen.add(primary_key_sha256)
        normalized.append(
            {
                "primary_key_sha256": primary_key_sha256,
                "row_sha256": _json_sha256(values),
            }
        )
    normalized.sort(key=lambda value: value["primary_key_sha256"])
    return {
        "row_count": len(normalized),
        "rows": normalized,
        "inventory_sha256": _json_sha256(normalized),
    }


def _database_auth_inventory() -> dict[str, Any]:
    try:
        from sqlalchemy import text

        from app.db.base import engine
    except ImportError as exc:  # pragma: no cover - exercised in the runtime image
        raise SFTPBoundaryError("application database runtime is unavailable") from exc

    statement = text(
        """
        SELECT id, workspace_id, "timestamp", event_type, actor, details,
               trace_id, agent_id, severity
          FROM audit_logs
         WHERE event_type LIKE 'deposit.sftp.auth.%'
         ORDER BY id
        """
    )
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                if connection.dialect.name == "postgresql":
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                rows = [dict(row) for row in connection.execute(statement).mappings()]
            finally:
                transaction.rollback()
    except Exception as exc:  # noqa: BLE001 - never expose database diagnostics
        raise SFTPBoundaryError("SFTP auth audit inventory could not be read") from exc
    return _auth_inventory_from_rows(rows)


def _validate_auth_inventory(value: Mapping[str, Any]) -> dict[str, tuple[str, str]]:
    rows = value.get("rows")
    if not isinstance(rows, list) or value.get("row_count") != len(rows):
        raise SFTPBoundaryError("SFTP auth audit inventory is malformed")
    if value.get("inventory_sha256") != _json_sha256(rows):
        raise SFTPBoundaryError("SFTP auth audit inventory digest is invalid")
    result: dict[str, tuple[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "primary_key_sha256",
            "row_sha256",
        }:
            raise SFTPBoundaryError("SFTP auth audit row inventory is malformed")
        primary_key = str(row["primary_key_sha256"])
        row_sha = str(row["row_sha256"])
        if (
            re.fullmatch(r"[0-9a-f]{64}", primary_key) is None
            or re.fullmatch(r"[0-9a-f]{64}", row_sha) is None
            or primary_key in result
        ):
            raise SFTPBoundaryError("SFTP auth audit row digest is invalid")
        result[primary_key] = (primary_key, row_sha)
    return result


def _compare_auth_inventory(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    before_rows = _validate_auth_inventory(before)
    after_rows = _validate_auth_inventory(after)
    added = set(after_rows) - set(before_rows)
    removed = set(before_rows) - set(after_rows)
    changed = {
        identity
        for identity in set(before_rows) & set(after_rows)
        if before_rows[identity] != after_rows[identity]
    }
    if added or removed or changed:
        raise SFTPBoundaryError("SFTP protocol probe changed authentication audit rows")
    return {
        "before_inventory_sha256": before["inventory_sha256"],
        "after_inventory_sha256": after["inventory_sha256"],
        "added_count": 0,
        "removed_count": 0,
        "changed_count": 0,
        "unchanged": True,
    }


def _client_container_id() -> str:
    try:
        value = Path("/etc/hostname").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SFTPBoundaryError("client container identity is unavailable") from exc
    if CONTAINER_ID_RE.fullmatch(value) is None:
        raise SFTPBoundaryError("client container identity is invalid")
    return value


async def _protocol_evidence(*, timeout: float = PROBE_TIMEOUT_SECONDS) -> dict[str, Any]:
    try:
        import asyncssh
    except ImportError as exc:  # pragma: no cover - exercised in the runtime image
        raise SFTPBoundaryError("AsyncSSH client runtime is unavailable") from exc

    common = {
        "host": SFTP_CONTAINER,
        "port": SFTP_CONTAINER_PORT,
        "config": None,
        "client_version": "AgentiumSafeCanary",
        "server_host_key_algs": ["ssh-ed25519"],
    }
    try:
        key_before = await asyncio.wait_for(
            asyncssh.get_server_host_key(**common), timeout=timeout
        )
        methods = await asyncio.wait_for(
            asyncssh.get_server_auth_methods(
                username=_AUTH_METHOD_PROBE_PRINCIPAL,
                **common,
            ),
            timeout=timeout,
        )
        key_after = await asyncio.wait_for(
            asyncssh.get_server_host_key(**common), timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001 - never expose SSH peer diagnostics
        raise SFTPBoundaryError("SFTP SSH protocol probe failed") from exc
    if key_before is None or key_after is None:
        raise SFTPBoundaryError("SFTP SSH host key is absent")
    try:
        algorithm_before = str(key_before.get_algorithm())
        algorithm_after = str(key_after.get_algorithm())
        fingerprint_before = str(key_before.get_fingerprint("sha256"))
        fingerprint_after = str(key_after.get_fingerprint("sha256"))
    except Exception as exc:  # noqa: BLE001
        raise SFTPBoundaryError("SFTP SSH host-key evidence is invalid") from exc
    if (
        algorithm_before != "ssh-ed25519"
        or algorithm_after != algorithm_before
        or FINGERPRINT_RE.fullmatch(fingerprint_before) is None
        or fingerprint_after != fingerprint_before
    ):
        raise SFTPBoundaryError("SFTP SSH host key is unexpected or unstable")
    raw_methods = [str(value) for value in methods]
    normalized_methods = sorted(set(raw_methods))
    if (
        len(normalized_methods) != len(raw_methods)
        or "password" not in normalized_methods
        or not set(normalized_methods) <= SAFE_NONE_AUTH_RESPONSE_METHODS
    ):
        raise SFTPBoundaryError("SFTP SSH authentication methods are unexpected")
    return {
        "ssh_v2_identification_validated": True,
        "key_exchange_completed": True,
        "host_key_algorithm": algorithm_before,
        "host_key_fingerprint": fingerprint_before,
        "host_key_stable": True,
        "none_auth_rejected": True,
        "auth_methods": normalized_methods,
        "password_offered": True,
        "password_submitted": False,
        "sftp_subsystem_requested": False,
        "directory_enumeration_requested": False,
    }


def build_protocol_client_contract(
    *,
    sha: str,
    deployment_id: str,
    inventory_reader: Callable[[], dict[str, Any]] = _database_auth_inventory,
    protocol_reader: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    _validate_identity(sha, deployment_id)
    before = inventory_reader()
    if protocol_reader is None:
        protocol = asyncio.run(_protocol_evidence())
    else:
        candidate = protocol_reader()
        protocol = asyncio.run(candidate) if hasattr(candidate, "__await__") else candidate
    if not isinstance(protocol, dict):
        raise SFTPBoundaryError("SFTP SSH protocol evidence is malformed")
    after = inventory_reader()
    audit = _compare_auth_inventory(before, after)
    return {
        "schema_version": 1,
        "kind": "agentium_sftp_protocol_client",
        "profile": PROFILE_PROTOCOL_CLIENT,
        "sha": sha,
        "deployment_id": deployment_id,
        "captured_at": _utc_now(),
        "result": "passed",
        "client_identity": {"container_id": _client_container_id()},
        "transport": "docker_internal_network",
        "protocol": protocol,
        "authentication_audit": audit,
        "credentials_used": False,
        "content_serialized": False,
        "raw_identification_serialized": False,
        "assurance": "ssh_key_exchange_plus_none_auth_methods_with_zero_audit_delta",
    }


def build_db_auth_inventory_contract(*, sha: str, deployment_id: str) -> dict[str, Any]:
    _validate_identity(sha, deployment_id)
    inventory = _database_auth_inventory()
    _validate_auth_inventory(inventory)
    return {
        "schema_version": 1,
        "kind": "agentium_sftp_auth_audit_inventory",
        "profile": PROFILE_DB_INVENTORY,
        "sha": sha,
        "deployment_id": deployment_id,
        "captured_at": _utc_now(),
        "result": "passed",
        "client_identity": {"container_id": _client_container_id()},
        "content_serialized": False,
        "inventory": inventory,
    }


def _validate_boundary_containers(
    *, sha: str, sftp_sha: str, require_sftp_running: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    sftp = _docker_inspect(SFTP_CONTAINER)
    client = _docker_inspect(CLIENT_CONTAINER)
    sftp_state = sftp.get("State", {})
    client_state = client.get("State", {})
    if not isinstance(sftp_state, dict) or not isinstance(client_state, dict):
        raise SFTPBoundaryError("SFTP boundary container state is invalid")
    if require_sftp_running:
        health = sftp_state.get("Health")
        if (
            sftp_state.get("Running") is not True
            or sftp_state.get("Paused") is not False
            or not isinstance(health, dict)
            or health.get("Status") != "healthy"
        ):
            raise SFTPBoundaryError("pinned SFTP container is not healthy")
    if client_state.get("Running") is not True or client_state.get("Paused") is not False:
        raise SFTPBoundaryError("candidate protocol client is not running")
    if not _restart_is_disabled(sftp):
        raise SFTPBoundaryError("pinned SFTP restart policy is not disabled")
    if EXPECTED_NETWORK not in _networks(sftp) or EXPECTED_NETWORK not in _networks(client):
        raise SFTPBoundaryError("SFTP boundary peers do not share the internal network")
    _assert_image_revision(sftp, sftp_sha)
    _assert_image_revision(client, sha)
    return sftp, client


def _docker_protocol_client(*, sha: str, deployment_id: str) -> dict[str, Any]:
    payload = _run_json(
        [
            "docker",
            "exec",
            "-w",
            "/app/backend",
            CLIENT_CONTAINER,
            "python",
            "-m",
            "scripts.audit_sftp_deploy_boundary",
            "protocol-client",
            "--sha",
            sha,
            "--deployment-id",
            deployment_id,
            "--output",
            "-",
        ],
        timeout=30,
    )
    if (
        not isinstance(payload, dict)
        or payload.get("profile") != PROFILE_PROTOCOL_CLIENT
        or payload.get("sha") != sha
        or payload.get("deployment_id") != deployment_id
        or payload.get("result") != "passed"
        or payload.get("credentials_used") is not False
        or payload.get("content_serialized") is not False
    ):
        raise SFTPBoundaryError("candidate SFTP protocol-client proof is invalid")
    if not isinstance(payload.get("client_identity"), dict):
        raise SFTPBoundaryError("candidate SFTP protocol-client identity is invalid")
    return payload


def _read_private_proof_bytes(path: Path, *, maximum: int) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise SFTPBoundaryError("private SFTP proof is unavailable") from exc
    if (
        stat_module.S_ISLNK(before.st_mode)
        or not stat_module.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or stat_module.S_IMODE(before.st_mode) != 0o600
        or before.st_nlink != 1
        or not 0 < before.st_size <= maximum
    ):
        raise SFTPBoundaryError("private SFTP proof file is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SFTPBoundaryError("private SFTP proof could not be opened safely") from exc
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise SFTPBoundaryError("private SFTP proof changed while opening")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                raise SFTPBoundaryError("private SFTP proof exceeds its size limit")
        after = os.fstat(descriptor)
        if (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_nlink,
        ) != (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
            opened.st_nlink,
        ):
            raise SFTPBoundaryError("private SFTP proof changed while reading")
        try:
            path_after = path.lstat()
        except OSError as exc:
            raise SFTPBoundaryError("private SFTP proof disappeared while reading") from exc
        if (
            stat_module.S_ISLNK(path_after.st_mode)
            or (path_after.st_dev, path_after.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise SFTPBoundaryError("private SFTP proof path changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


_VALIDATION_READY_KEYS = {
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
_VALIDATION_READY_TRANSPORT_KEYS = {
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
_VALIDATION_READY_SECURE_KEYS = {
    "source_matches_dev_sdc",
    "source_device_sha256",
    "autonomous_mountpoint",
    "host_read_only",
    "namespace_autonomous_mountpoint",
    "namespace_read_only",
    "device_id",
}
_VALIDATION_READY_HOST_KEY_KEYS = {
    "algorithm",
    "fingerprint",
    "fingerprint_sha256",
    "present",
    "nonempty",
    "regular_file",
    "symlink",
}


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _load_validation_ready_receipt(
    path: Path,
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    expected_secure_source: str,
) -> tuple[dict[str, Any], str]:
    _validate_release_a_identity(live_sha, release_a_sha, sftp_sha, deployment_id)
    expected_secure_source = _validate_expected_secure_source(expected_secure_source)
    if expected_secure_source != RELEASE_A_SECURE_SOURCE:
        raise SFTPBoundaryError("Release A Secure Deposit source must be /dev/sdc")
    raw = _read_private_proof_bytes(path, maximum=MAX_VALIDATION_PROOF_BYTES)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SFTPBoundaryError("runtime-ready receipt is invalid JSON") from exc
    try:
        canonical = _canonical_json_bytes(value) if isinstance(value, dict) else b""
    except (TypeError, ValueError) as exc:
        raise SFTPBoundaryError("runtime-ready receipt is not canonical JSON") from exc
    if not isinstance(value, dict) or raw != canonical:
        raise SFTPBoundaryError("runtime-ready receipt is not canonical JSON")
    if set(value) != _VALIDATION_READY_KEYS:
        raise SFTPBoundaryError("runtime-ready receipt schema differs")

    transport = value.get("published_transport")
    secure = value.get("secure_deposit")
    host_key = value.get("host_key")
    gate = value.get("ingress_gate")
    if not all(isinstance(item, dict) for item in (transport, secure, host_key, gate)):
        raise SFTPBoundaryError("runtime-ready receipt structure differs")
    assert isinstance(transport, dict)
    assert isinstance(secure, dict)
    assert isinstance(host_key, dict)
    assert isinstance(gate, dict)
    if (
        set(transport) != _VALIDATION_READY_TRANSPORT_KEYS
        or set(secure) != _VALIDATION_READY_SECURE_KEYS
        or set(host_key) != _VALIDATION_READY_HOST_KEY_KEYS
    ):
        raise SFTPBoundaryError("runtime-ready receipt nested schema differs")

    expected_gate = {
        "ipv4_input": True,
        "ipv4_docker_user": True,
        "ipv6_input": True,
        "ipv6_docker_user": True,
    }
    sha256_re = re.compile(r"^[0-9a-f]{64}$")
    container_id = value.get("sftp_container_id")
    image_id = value.get("sftp_image_id")
    started_at = value.get("sftp_started_at")
    ready_at = value.get("ready_at")
    port = value.get("sftp_port")
    device_id = secure.get("device_id")
    if (
        value.get("schema_version") != 1
        or value.get("kind") != "agentium-release-a-sftp-runtime-ready"
        or value.get("result") != "passed"
        or value.get("live_sha") != live_sha
        or value.get("release_a_sha") != release_a_sha
        or value.get("sftp_sha") != sftp_sha
        or value.get("deployment_id") != deployment_id
        or value.get("image_revision") != sftp_sha
        or CONTAINER_ID_RE.fullmatch(str(container_id or "")) is None
        or IMAGE_ID_RE.fullmatch(str(image_id or "")) is None
        or isinstance(port, bool)
        or not isinstance(port, int)
        or not 1 <= port <= 65_535
        or value.get("state") != "running"
        or value.get("health_status") != "healthy"
        or value.get("ingress_closed") is not True
        or value.get("restart_disabled") is not True
        or value.get("restart_policy_disabled") is not True
        or value.get("secure_deposit_mode") != "ro"
        or value.get("secure_deposit_source") != expected_secure_source
        or value.get("external_established_connection_count") != 0
        or value.get("credentials_used") is not False
        or value.get("authentication_attempted") is not False
        or value.get("sftp_subsystem_requested") is not False
        or value.get("content_serialized") is not False
        or value.get("raw_network_data_serialized") is not False
        or value.get("raw_identification_serialized") is not False
        or gate != expected_gate
    ):
        raise SFTPBoundaryError("runtime-ready receipt contract differs")

    started_timestamp = _parse_utc_timestamp(started_at, label="SFTP StartedAt")
    ready_timestamp = _parse_utc_timestamp(ready_at, label="SFTP ready_at")
    if started_timestamp > ready_timestamp:
        raise SFTPBoundaryError("runtime-ready receipt chronology differs")
    hostname_sha256 = value.get("hostname_sha256")
    runtime_digest = value.get("runtime_identity_sha256")
    if (
        sha256_re.fullmatch(str(hostname_sha256 or "")) is None
        or hostname_sha256 != _runtime_hostname_sha256()
        or sha256_re.fullmatch(str(runtime_digest or "")) is None
        or runtime_digest
        != runtime_identity_sha256(
            live_sha=live_sha,
            release_a_sha=release_a_sha,
            sftp_sha=sftp_sha,
            deployment_id=deployment_id,
            hostname_sha256=str(hostname_sha256),
            sftp_container_id=str(container_id),
            sftp_image_id=str(image_id),
            sftp_port=port,
            sftp_started_at=str(started_at),
        )
    ):
        raise SFTPBoundaryError("runtime-ready receipt identity digest differs")

    fingerprint = host_key.get("fingerprint")
    if FINGERPRINT_RE.fullmatch(str(fingerprint or "")) is None:
        raise SFTPBoundaryError("runtime-ready receipt host key differs")
    if (
        host_key
        != {
            "algorithm": "ssh-ed25519",
            "fingerprint": fingerprint,
            "fingerprint_sha256": hashlib.sha256(
                str(fingerprint).encode("ascii", errors="strict")
            ).hexdigest(),
            "present": True,
            "nonempty": True,
            "regular_file": True,
            "symlink": False,
        }
        or value.get("host_key_fingerprint") != fingerprint
    ):
        raise SFTPBoundaryError("runtime-ready receipt host key differs")
    if (
        transport.get("protocol") != "tcp"
        or transport.get("container_port") != SFTP_CONTAINER_PORT
        or transport.get("host_port") != port
        or isinstance(transport.get("binding_count"), bool)
        or not isinstance(transport.get("binding_count"), int)
        or not 1 <= int(transport["binding_count"]) <= 2
        or sha256_re.fullmatch(str(transport.get("binding_sha256") or "")) is None
        or isinstance(transport.get("listener_count"), bool)
        or not isinstance(transport.get("listener_count"), int)
        or int(transport["listener_count"]) < 1
        or transport.get("established_connection_count_before") != 0
        or transport.get("established_connection_count_after") != 0
        or transport.get("external_established_connection_count") != 0
        or transport.get("ssh_v2_identification_validated") is not True
        or transport.get("connection_closed_before_authentication") is not True
        or transport.get("raw_identification_serialized") is not False
    ):
        raise SFTPBoundaryError("runtime-ready receipt transport differs")
    if (
        secure.get("source_matches_dev_sdc") is not True
        or secure.get("source_device_sha256")
        != hashlib.sha256(expected_secure_source.encode("ascii")).hexdigest()
        or secure.get("autonomous_mountpoint") is not True
        or secure.get("host_read_only") is not True
        or secure.get("namespace_autonomous_mountpoint") is not True
        or secure.get("namespace_read_only") is not True
        or isinstance(device_id, bool)
        or not isinstance(device_id, int)
        or device_id <= 0
    ):
        raise SFTPBoundaryError("runtime-ready receipt Secure Deposit differs")
    return value, hashlib.sha256(raw).hexdigest()


def _historical_sftp_restart_policy(
    path: Path, *, expected_image_id: str
) -> tuple[str, int]:
    raw = _read_private_proof_bytes(path, maximum=MAX_RUNTIME_STATE_BYTES)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SFTPBoundaryError("historical runtime state is not UTF-8") from exc
    if not text.endswith("\n") or "\r" in text or "\x00" in text:
        raise SFTPBoundaryError("historical runtime state encoding differs")
    lines = text[:-1].split("\n")
    if not lines or lines[0] != "format\t1":
        raise SFTPBoundaryError("historical runtime state format differs")
    matches: list[list[str]] = []
    for line in lines[1:]:
        fields = line.split("\t")
        if fields[:2] == ["container", SFTP_CONTAINER]:
            matches.append(fields)
    if len(matches) != 1 or len(matches[0]) != 6:
        raise SFTPBoundaryError("historical SFTP runtime state is ambiguous")
    _, _, running, image_id, name, maximum_raw = matches[0]
    try:
        maximum = int(maximum_raw)
    except ValueError as exc:
        raise SFTPBoundaryError("historical SFTP restart policy is invalid") from exc
    candidate = {
        "HostConfig": {
            "RestartPolicy": {"Name": name, "MaximumRetryCount": maximum}
        }
    }
    policy = _restart_policy(candidate)
    if running != "true" or image_id != expected_image_id:
        raise SFTPBoundaryError("historical SFTP runtime identity differs")
    return policy


def _live_secure_deposit_mode(
    value: Mapping[str, Any], *, expected_mode: str, namespace_mode: str
) -> dict[str, Any]:
    device_id = value.get("device_id")
    if (
        value.get("source_matches_expected") is not True
        or value.get("autonomous_mountpoint") is not True
        or value.get("read_only") is not (expected_mode == "ro")
        or namespace_mode != expected_mode
        or isinstance(device_id, bool)
        or not isinstance(device_id, int)
        or device_id <= 0
    ):
        raise SFTPBoundaryError("live Secure Deposit mode differs")
    return {"mode": expected_mode, "device_id": device_id}


def verify_runtime_identity_live_contract(
    *,
    receipt_path: Path,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    expected_secure_source: str,
    expected_secure_mode: str,
    expected_restart: str,
    runtime_state_path: Path | None = None,
    allow_paused: bool = False,
) -> dict[str, Any]:
    if expected_secure_mode not in {"ro", "rw"}:
        raise SFTPBoundaryError("expected Secure Deposit mode must be ro or rw")
    if expected_restart not in {"disabled", "historical"}:
        raise SFTPBoundaryError("expected restart policy must be disabled or historical")
    receipt, receipt_sha256 = _load_validation_ready_receipt(
        receipt_path,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        expected_secure_source=expected_secure_source,
    )
    if expected_restart == "disabled":
        if runtime_state_path is not None:
            raise SFTPBoundaryError("runtime state is forbidden for disabled restart policy")
        expected_policy = ("no", 0)
    else:
        if runtime_state_path is None:
            raise SFTPBoundaryError("runtime state is required for historical restart policy")
        expected_policy = _historical_sftp_restart_policy(
            runtime_state_path, expected_image_id=str(receipt["sftp_image_id"])
        )

    def capture() -> dict[str, Any]:
        inspected = _docker_inspect(SFTP_CONTAINER)
        runtime = _validation_runtime_identity(
            inspected,
            sftp_sha=sftp_sha,
            expected_restart_policy=expected_policy,
            allow_paused=allow_paused,
        )
        port = _published_sftp_port(inspected)
        binding = _published_binding_contract(inspected, host_port=port)
        gate = _validation_gate_contract(
            _gate_contract(
                deployment_id=deployment_id,
                host_port=port,
                expected_closed=True,
            )
        )
        listener_count = _listener_count(port)
        connection_count = _established_connection_count(port)
        mount, secure_root = _secure_mount_contract(
            inspected,
            expected_source=expected_secure_source,
            expected_mode=expected_secure_mode,
        )
        secure = _live_secure_deposit_mode(
            mount,
            expected_mode=expected_secure_mode,
            namespace_mode=_secure_namespace_mode(
                expected_secure_mode, inspect_payload=inspected
            ),
        )
        host_key = _validation_host_key_contract(
            _host_key_fingerprint(_host_key_path(inspected, secure_root))
        )
        return {
            "runtime": runtime,
            "port": port,
            "binding": binding,
            "gate": gate,
            "listener_count": listener_count,
            "connection_count": connection_count,
            "secure": secure,
            "host_key": host_key,
        }

    before = capture()
    port = int(before["port"])
    runtime_before = before["runtime"]
    assert isinstance(runtime_before, dict)
    paused = runtime_before.get("paused") is True
    if paused:
        transport = {
            "ssh_v2_identification_validated": False,
            "connection_closed_before_authentication": True,
            "raw_identification_serialized": False,
        }
    else:
        transport = _validation_loopback_transport(
            _read_published_ssh_identification(port)
        )
    after = capture()
    if before != after:
        raise SFTPBoundaryError("SFTP live runtime changed during identity verification")
    runtime = before["runtime"]
    assert isinstance(runtime, dict)
    receipt_transport = receipt["published_transport"]
    receipt_secure = receipt["secure_deposit"]
    receipt_host_key = receipt["host_key"]
    assert isinstance(receipt_transport, dict)
    assert isinstance(receipt_secure, dict)
    assert isinstance(receipt_host_key, dict)
    if (
        runtime.get("container_id") != receipt["sftp_container_id"]
        or runtime.get("image_id") != receipt["sftp_image_id"]
        or runtime.get("image_revision") != receipt["image_revision"]
        or runtime.get("started_at") != receipt["sftp_started_at"]
        or port != receipt["sftp_port"]
        or before["binding"]
        != {
            "binding_count": receipt_transport["binding_count"],
            "binding_sha256": receipt_transport["binding_sha256"],
        }
        or before["gate"] != receipt["ingress_gate"]
        or before["listener_count"] != receipt_transport["listener_count"]
        or before["connection_count"] != 0
        or before["host_key"] != receipt_host_key
        or before["secure"].get("device_id") != receipt_secure["device_id"]
    ):
        raise SFTPBoundaryError("SFTP live runtime identity differs from receipt")
    checked_at = _utc_now()
    _parse_utc_timestamp(checked_at, label="SFTP checked_at")
    return {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-runtime-identity-live",
        "result": "passed",
        "live_sha": live_sha,
        "release_a_sha": release_a_sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "runtime_ready_receipt_sha256": receipt_sha256,
        "runtime_identity_sha256": receipt["runtime_identity_sha256"],
        "sftp_container_id": runtime["container_id"],
        "sftp_image_id": runtime["image_id"],
        "sftp_started_at": runtime["started_at"],
        "image_revision": runtime["image_revision"],
        "sftp_port": port,
        "published_binding_sha256": before["binding"]["binding_sha256"],
        "host_key_fingerprint_sha256": receipt_host_key["fingerprint_sha256"],
        "ingress_closed": True,
        "secure_deposit_mode": expected_secure_mode,
        "restart_expectation": expected_restart,
        "restart_policy": runtime["restart_policy"],
        "listener_count": before["listener_count"],
        "established_connection_count": 0,
        "paused": paused,
        "transport_probe_performed": not paused,
        "ssh_v2_identification_validated": transport[
            "ssh_v2_identification_validated"
        ],
        "credentials_used": False,
        "authentication_attempted": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
        "checked_at": checked_at,
    }


def _load_closed_proof(
    path: Path,
    *,
    sha: str,
    sftp_sha: str,
    deployment_id: str,
    require_private: bool = False,
) -> tuple[dict[str, Any], str]:
    try:
        if require_private:
            raw = _read_private_proof_bytes(path, maximum=MAX_CLOSED_PROOF_BYTES)
        else:
            if path.is_symlink() or not path.is_file():
                raise SFTPBoundaryError("closed SFTP boundary proof is unavailable")
            raw = path.read_bytes()
        value = json.loads(raw)
    except SFTPBoundaryError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise SFTPBoundaryError("closed SFTP boundary proof is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 2
        or value.get("kind") != "agentium_sftp_deploy_boundary"
        or value.get("profile") != PROFILE_CLOSED
        or value.get("sha") != sha
        or value.get("sftp_sha") != sftp_sha
        or value.get("deployment_id") != deployment_id
        or value.get("result") != "passed"
        or value.get("credentials_used") is not False
        or value.get("content_serialized") is not False
        or value.get("raw_network_data_serialized") is not False
    ):
        raise SFTPBoundaryError("closed SFTP proof is not bound to this deployment")
    container = value.get("container")
    host_key = value.get("host_key")
    gate = value.get("ingress_gate")
    network = value.get("network")
    secure_deposit = value.get("secure_deposit")
    legacy = value.get("legacy_service")
    revision_binding = value.get("revision_binding")
    if not all(
        isinstance(item, dict)
        for item in (
            container,
            host_key,
            gate,
            network,
            secure_deposit,
            legacy,
            revision_binding,
        )
    ):
        raise SFTPBoundaryError("closed SFTP proof structure is invalid")
    assert isinstance(container, dict)
    assert isinstance(host_key, dict)
    assert isinstance(gate, dict)
    assert isinstance(network, dict)
    assert isinstance(secure_deposit, dict)
    assert isinstance(legacy, dict)
    assert isinstance(revision_binding, dict)
    container_id = str(container.get("container_id") or "")
    image_id = str(container.get("image_id") or "")
    fingerprint = str(host_key.get("fingerprint") or "")
    if (
        CONTAINER_ID_RE.fullmatch(container_id) is None
        or IMAGE_ID_RE.fullmatch(image_id) is None
        or FINGERPRINT_RE.fullmatch(fingerprint) is None
        or container.get("running") is not False
        or container.get("paused") is not False
        or container.get("process_count") != 0
        or container.get("secure_deposit_open_fd_count") != 0
        or container.get("restart_policy_disabled") is not True
        or container.get("revision") != sftp_sha
        or host_key.get("algorithm") != "ssh-ed25519"
        or host_key.get("present") is not True
        or host_key.get("nonempty") is not True
        or host_key.get("regular_file") is not True
        or host_key.get("symlink") is not False
        or set(gate) != {
            "ipv4_input",
            "ipv4_docker_user",
            "ipv6_input",
            "ipv6_docker_user",
        }
        or not all(value is True for value in gate.values())
        or network.get("listener_count") != 0
        or network.get("established_connection_count") != 0
        or network.get("ipv4_connect_rejected") is not True
        or network.get("ipv6_connect_rejected") is not True
        or secure_deposit.get("source_matches_expected") is not True
        or secure_deposit.get("autonomous_mountpoint") is not True
        or secure_deposit.get("read_only") is not True
        or legacy != {"active": False, "enabled": False}
        or revision_binding
        != _revision_binding(
            sha, sftp_sha, client_image_revision_verified=False
        )
    ):
        raise SFTPBoundaryError("closed SFTP proof did not establish the required boundary")
    return value, hashlib.sha256(raw).hexdigest()


def _assert_fresh_rollback_closed_proof(value: Mapping[str, Any]) -> None:
    raw = value.get("captured_at")
    if not isinstance(raw, str) or not raw.endswith("Z"):
        raise SFTPBoundaryError("rollback closed-boundary timestamp is invalid")
    try:
        captured = datetime.fromisoformat(raw[:-1] + "+00:00")
    except ValueError as exc:
        raise SFTPBoundaryError("rollback closed-boundary timestamp is invalid") from exc
    if captured.tzinfo is None:
        raise SFTPBoundaryError("rollback closed-boundary timestamp is invalid")
    age = (datetime.now(UTC) - captured.astimezone(UTC)).total_seconds()
    if age < -60 or age > ROLLBACK_CLOSED_MAX_AGE_SECONDS:
        raise SFTPBoundaryError("rollback closed-boundary proof is not fresh")


def build_docker_protocol_contract(
    *, sha: str, sftp_sha: str, deployment_id: str, closed_proof_path: Path
) -> dict[str, Any]:
    _validate_boundary_identity(sha, sftp_sha, deployment_id)
    closed_proof, closed_proof_sha256 = _load_closed_proof(
        closed_proof_path,
        sha=sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
    )
    sftp, client = _validate_boundary_containers(
        sha=sha, sftp_sha=sftp_sha, require_sftp_running=True
    )
    sftp_id = _container_id(sftp)
    client_id = _container_id(client)
    closed_container = closed_proof["container"]
    closed_host_key = closed_proof["host_key"]
    if (
        closed_container.get("container_id") != sftp_id
        or closed_container.get("image_id") != _image_id(sftp)
    ):
        raise SFTPBoundaryError("running SFTP identity differs from the closed proof")
    proof = _docker_protocol_client(sha=sha, deployment_id=deployment_id)
    runtime_client_id = str(proof.get("client_identity", {}).get("container_id") or "")
    if not CONTAINER_ID_RE.fullmatch(runtime_client_id) or not client_id.startswith(
        runtime_client_id
    ):
        raise SFTPBoundaryError("protocol-client runtime identity is not Docker-bound")
    protocol = proof.get("protocol")
    audit = proof.get("authentication_audit")
    if (
        not isinstance(protocol, dict)
        or protocol.get("password_offered") is not True
        or protocol.get("password_submitted") is not False
        or protocol.get("sftp_subsystem_requested") is not False
        or protocol.get("directory_enumeration_requested") is not False
        or not isinstance(audit, dict)
        or audit.get("unchanged") is not True
        or any(audit.get(key) != 0 for key in ("added_count", "removed_count", "changed_count"))
    ):
        raise SFTPBoundaryError("candidate SFTP protocol proof is incomplete")
    if protocol.get("host_key_fingerprint") != closed_host_key.get("fingerprint"):
        raise SFTPBoundaryError("running SFTP host key differs from the closed proof")
    return {
        "schema_version": 2,
        "kind": "agentium_sftp_deploy_boundary",
        "profile": PROFILE_DOCKER_PROTOCOL,
        "sha": sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "captured_at": _utc_now(),
        "result": "passed",
        "sftp_identity": {
            "container_id": sftp_id,
            "image_id": _image_id(sftp),
            "revision": sftp_sha,
            "healthy": True,
            "restart_policy_disabled": True,
        },
        "client_identity": {
            "container_id": client_id,
            "image_id": _image_id(client),
            "revision": sha,
        },
        "revision_binding": _revision_binding(
            sha, sftp_sha, client_image_revision_verified=True
        ),
        "internal_network_shared": True,
        "closed_proof_sha256": closed_proof_sha256,
        "closed_boundary_binding": {
            "same_candidate_sha": True,
            "same_sftp_sha": True,
            "server_client_sha_distinct": True,
            "same_deployment_id": True,
            "same_container_id": True,
            "same_image_id": True,
            "same_host_key_fingerprint": True,
        },
        "protocol": protocol,
        "authentication_audit": audit,
        "credentials_used": False,
        "content_serialized": False,
        "raw_identification_serialized": False,
        "assurance": "release_b_candidate_client_to_pinned_release_a_sftp_over_docker_network_with_ssh_key_exchange_none_auth_zero_audit_delta_and_no_positive_login",
        "proof_ceiling": "runner_verified",
    }


def _assert_closed_gate_evidence(value: Mapping[str, Any]) -> dict[str, bool]:
    expected = {
        "ipv4_input": True,
        "ipv4_docker_user": True,
        "ipv6_input": True,
        "ipv6_docker_user": True,
    }
    if dict(value) != expected:
        raise SFTPBoundaryError("SFTP rollback ingress gate is not fully closed")
    return expected


def _assert_read_only_secure_evidence(
    value: Mapping[str, Any], *, expected_device_id: int
) -> dict[str, Any]:
    device_id = value.get("device_id")
    if (
        value.get("source_matches_expected") is not True
        or value.get("autonomous_mountpoint") is not True
        or value.get("read_only") is not True
        or not isinstance(device_id, int)
        or isinstance(device_id, bool)
        or device_id <= 0
        or device_id != expected_device_id
    ):
        raise SFTPBoundaryError("Secure Deposit rollback boundary is not unchanged and read-only")
    return {
        "source_matches_expected": True,
        "autonomous_mountpoint": True,
        "read_only": True,
        "device_id": device_id,
    }


def _sanitize_rollback_protocol_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "ssh_v2_identification_validated",
        "key_exchange_completed",
        "host_key_algorithm",
        "host_key_fingerprint",
        "host_key_stable",
        "none_auth_rejected",
        "auth_methods",
        "password_offered",
        "password_submitted",
        "sftp_subsystem_requested",
        "directory_enumeration_requested",
    }
    raw_methods = value.get("auth_methods")
    methods = (
        [str(method) for method in raw_methods]
        if isinstance(raw_methods, list)
        else []
    )
    fingerprint = str(value.get("host_key_fingerprint") or "")
    if (
        set(value) != expected_keys
        or value.get("ssh_v2_identification_validated") is not True
        or value.get("key_exchange_completed") is not True
        or value.get("host_key_algorithm") != "ssh-ed25519"
        or FINGERPRINT_RE.fullmatch(fingerprint) is None
        or value.get("host_key_stable") is not True
        or value.get("none_auth_rejected") is not True
        or not methods
        or methods != sorted(set(methods))
        or "password" not in methods
        or not set(methods) <= SAFE_NONE_AUTH_RESPONSE_METHODS
        or value.get("password_offered") is not True
        or value.get("password_submitted") is not False
        or value.get("sftp_subsystem_requested") is not False
        or value.get("directory_enumeration_requested") is not False
    ):
        raise SFTPBoundaryError("rollback SFTP protocol evidence is invalid")
    return {
        "ssh_v2_identification_validated": True,
        "key_exchange_completed": True,
        "host_key_algorithm": "ssh-ed25519",
        "host_key_fingerprint": fingerprint,
        "host_key_stable": True,
        "none_auth_rejected": True,
        "auth_methods": methods,
        "password_offered": True,
        "password_submitted": False,
        "sftp_subsystem_requested": False,
        "directory_enumeration_requested": False,
    }


def _sanitize_rollback_auth_audit(value: Mapping[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "before_inventory_sha256",
        "after_inventory_sha256",
        "added_count",
        "removed_count",
        "changed_count",
        "unchanged",
    }
    before = str(value.get("before_inventory_sha256") or "")
    after = str(value.get("after_inventory_sha256") or "")
    if (
        set(value) != expected_keys
        or re.fullmatch(r"[0-9a-f]{64}", before) is None
        or after != before
        or value.get("added_count") != 0
        or value.get("removed_count") != 0
        or value.get("changed_count") != 0
        or value.get("unchanged") is not True
    ):
        raise SFTPBoundaryError("rollback SFTP auth inventory evidence is invalid")
    return {
        "before_inventory_sha256": before,
        "after_inventory_sha256": after,
        "added_count": 0,
        "removed_count": 0,
        "changed_count": 0,
        "unchanged": True,
    }


def _sanitize_rollback_published_transport(
    value: Mapping[str, Any],
) -> dict[str, bool]:
    expected = {
        "ssh_v2_identification_validated": True,
        "raw_identification_serialized": False,
        "connection_closed_before_authentication": True,
    }
    if dict(value) != expected:
        raise SFTPBoundaryError("rollback published SFTP transport evidence is invalid")
    return {
        "ssh_v2_identification_validated": True,
        "connection_closed_before_authentication": True,
        "raw_identification_serialized": False,
        "loopback_probe": True,
        "external_gate_closed_during_probe": True,
    }


def build_rollback_continuity_contract(
    *,
    sha: str,
    candidate_sha: str,
    sftp_sha: str,
    deployment_id: str,
    closed_proof_path: Path,
    expected_secure_source: str,
) -> dict[str, Any]:
    """Prove safe SFTP continuity after restoring the previous application runtime."""

    _validate_rollback_identity(sha, candidate_sha, sftp_sha, deployment_id)
    expected_secure_source = _validate_expected_secure_source(expected_secure_source)
    closed_proof, closed_proof_sha256 = _load_closed_proof(
        closed_proof_path,
        sha=candidate_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        require_private=True,
    )
    _assert_fresh_rollback_closed_proof(closed_proof)
    closed_container = closed_proof["container"]
    closed_host_key = closed_proof["host_key"]
    closed_secure = closed_proof["secure_deposit"]
    assert isinstance(closed_container, dict)
    assert isinstance(closed_host_key, dict)
    assert isinstance(closed_secure, dict)
    closed_device_id = closed_secure.get("device_id")
    if (
        not isinstance(closed_device_id, int)
        or isinstance(closed_device_id, bool)
        or closed_device_id <= 0
    ):
        raise SFTPBoundaryError("closed SFTP proof has an invalid Secure Deposit identity")

    sftp_before, client_before = _validate_boundary_containers(
        sha=sha,
        sftp_sha=sftp_sha,
        require_sftp_running=True,
    )
    sftp_id = _container_id(sftp_before)
    sftp_image = _image_id(sftp_before)
    client_id = _container_id(client_before)
    client_image = _image_id(client_before)
    if (
        closed_container.get("container_id") != sftp_id
        or closed_container.get("image_id") != sftp_image
    ):
        raise SFTPBoundaryError("rollback SFTP container or image differs from closed-boundary")

    host_port = _published_sftp_port(sftp_before)
    gate_before = _assert_closed_gate_evidence(
        _gate_contract(
            deployment_id=deployment_id,
            host_port=host_port,
            expected_closed=True,
        )
    )
    secure_before_raw, secure_root_before = _secure_mount_contract(
        sftp_before, expected_source=expected_secure_source
    )
    secure_before = _assert_read_only_secure_evidence(
        secure_before_raw, expected_device_id=closed_device_id
    )
    host_key_before = _host_key_fingerprint(
        _host_key_path(sftp_before, secure_root_before)
    )
    if host_key_before != closed_host_key:
        raise SFTPBoundaryError("rollback SFTP host key differs from closed-boundary")

    protocol_proof = _docker_protocol_client(
        sha=sha,
        deployment_id=deployment_id,
    )
    runtime_client_id = str(
        protocol_proof.get("client_identity", {}).get("container_id") or ""
    )
    if (
        CONTAINER_ID_RE.fullmatch(runtime_client_id) is None
        or not client_id.startswith(runtime_client_id)
    ):
        raise SFTPBoundaryError("rollback protocol client is not the previous runtime")
    protocol_raw = protocol_proof.get("protocol")
    audit_raw = protocol_proof.get("authentication_audit")
    if not isinstance(protocol_raw, dict) or not isinstance(audit_raw, dict):
        raise SFTPBoundaryError("rollback SFTP protocol or auth inventory proof is incomplete")
    protocol = _sanitize_rollback_protocol_evidence(protocol_raw)
    audit = _sanitize_rollback_auth_audit(audit_raw)
    if protocol.get("host_key_fingerprint") != closed_host_key.get("fingerprint"):
        raise SFTPBoundaryError("rollback protocol observed a different SFTP host key")

    # The external gate rejects non-loopback ingress. Recheck it immediately
    # before the bounded loopback banner probe; the probe closes before auth.
    gate_during = _assert_closed_gate_evidence(
        _gate_contract(
            deployment_id=deployment_id,
            host_port=host_port,
            expected_closed=True,
        )
    )
    published_transport = _sanitize_rollback_published_transport(
        _read_published_ssh_identification(host_port)
    )

    sftp_after, client_after = _validate_boundary_containers(
        sha=sha,
        sftp_sha=sftp_sha,
        require_sftp_running=True,
    )
    if (
        _container_id(sftp_after) != sftp_id
        or _image_id(sftp_after) != sftp_image
        or _container_id(client_after) != client_id
        or _image_id(client_after) != client_image
    ):
        raise SFTPBoundaryError("rollback SFTP or previous client changed during proof")
    if _published_sftp_port(sftp_after) != host_port:
        raise SFTPBoundaryError("rollback SFTP transport identity changed during proof")
    secure_after_raw, secure_root_after = _secure_mount_contract(
        sftp_after, expected_source=expected_secure_source
    )
    secure_after = _assert_read_only_secure_evidence(
        secure_after_raw, expected_device_id=closed_device_id
    )
    host_key_after = _host_key_fingerprint(
        _host_key_path(sftp_after, secure_root_after)
    )
    if host_key_after != host_key_before:
        raise SFTPBoundaryError("rollback SFTP host key changed during proof")
    # Make the external gate the final live assertion before publishing the
    # receipt; no protocol or filesystem probe runs after this boundary check.
    gate_after = _assert_closed_gate_evidence(
        _gate_contract(
            deployment_id=deployment_id,
            host_port=host_port,
            expected_closed=True,
        )
    )

    return {
        "schema_version": 1,
        "kind": "agentium_sftp_deploy_boundary",
        "profile": PROFILE_ROLLBACK_CONTINUITY,
        "sha": sha,
        "candidate_sha": candidate_sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "captured_at": _utc_now(),
        "result": "passed",
        "sftp_identity": {
            "container_id": sftp_id,
            "image_id": sftp_image,
            "revision": sftp_sha,
            "healthy": True,
            "restart_policy_disabled": True,
        },
        "client_identity": {
            "container_id": client_id,
            "image_id": client_image,
            "revision": sha,
            "is_previous_runtime": True,
        },
        "revision_binding": {
            "candidate_sha": candidate_sha,
            "previous_client_sha": sha,
            "sftp_sha": sftp_sha,
            "candidate_previous_distinct": True,
            "candidate_sftp_distinct": True,
            "previous_client_matches_sftp_sha": sha == sftp_sha,
            "client_image_revision_verified": True,
            "sftp_image_revision_verified": True,
        },
        "closed_boundary": {
            "sha256": closed_proof_sha256,
            "candidate_sha_bound": True,
            "sftp_sha_bound": True,
            "deployment_id_bound": True,
            "same_container_id": True,
            "same_image_id": True,
            "same_host_key_fingerprint": True,
            "fresh": True,
        },
        "ingress_gate": {
            "before": gate_before,
            "during_published_probe": gate_during,
            "after": gate_after,
            "remained_closed": True,
        },
        "secure_deposit": {
            "before": secure_before,
            "after": secure_after,
            "same_device": True,
            "remained_read_only": True,
        },
        "host_key": {
            "algorithm": "ssh-ed25519",
            "fingerprint": host_key_after["fingerprint"],
            "same_as_closed_boundary": True,
            "stable_during_probe": True,
        },
        "protocol": protocol,
        "published_transport": published_transport,
        "authentication_audit": audit,
        "credentials_used": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
        "raw_identification_serialized": False,
        "assurance": "previous_runtime_to_same_pinned_sftp_with_internal_none_auth_and_published_loopback_ssh_identification_under_closed_ingress_read_only_secure_deposit_stable_host_key_zero_auth_audit_delta_and_no_credentials",
        "proof_ceiling": "runner_verified",
    }


def _docker_db_auth_inventory(*, sha: str, deployment_id: str) -> dict[str, Any]:
    payload = _run_json(
        [
            "docker",
            "exec",
            "-w",
            "/app/backend",
            CLIENT_CONTAINER,
            "python",
            "-m",
            "scripts.audit_sftp_deploy_boundary",
            "db-auth-inventory",
            "--sha",
            sha,
            "--deployment-id",
            deployment_id,
            "--output",
            "-",
        ],
        timeout=30,
    )
    if (
        not isinstance(payload, dict)
        or payload.get("profile") != PROFILE_DB_INVENTORY
        or payload.get("sha") != sha
        or payload.get("deployment_id") != deployment_id
        or payload.get("result") != "passed"
        or payload.get("content_serialized") is not False
    ):
        raise SFTPBoundaryError("candidate SFTP auth inventory proof is invalid")
    if not isinstance(payload.get("client_identity"), dict):
        raise SFTPBoundaryError("candidate SFTP auth inventory identity is invalid")
    inventory = payload.get("inventory")
    if not isinstance(inventory, dict):
        raise SFTPBoundaryError("candidate SFTP auth inventory is absent")
    _validate_auth_inventory(inventory)
    return payload


def _read_published_ssh_identification(host_port: int) -> dict[str, Any]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(2.0)
        sock.connect(("127.0.0.1", host_port))
        data = b""
        while len(data) <= MAX_IDENTIFICATION_BYTES and not data.endswith(b"\n"):
            chunk = sock.recv(1)
            if not chunk:
                break
            data += chunk
    except OSError as exc:
        raise SFTPBoundaryError("published SFTP SSH identification is unavailable") from exc
    finally:
        sock.close()
    if len(data) > MAX_IDENTIFICATION_BYTES or SSH_IDENT_RE.fullmatch(data) is None:
        raise SFTPBoundaryError("published SFTP SSH identification is invalid")
    return {
        "ssh_v2_identification_validated": True,
        "raw_identification_serialized": False,
        "connection_closed_before_authentication": True,
    }


def _load_protocol_proof(
    path: Path, *, sha: str, sftp_sha: str, deployment_id: str
) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise SFTPBoundaryError("Docker SFTP protocol proof is unavailable")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SFTPBoundaryError("Docker SFTP protocol proof is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 2
        or value.get("kind") != "agentium_sftp_deploy_boundary"
        or value.get("profile") != PROFILE_DOCKER_PROTOCOL
        or value.get("sha") != sha
        or value.get("sftp_sha") != sftp_sha
        or value.get("deployment_id") != deployment_id
        or value.get("result") != "passed"
        or value.get("credentials_used") is not False
        or value.get("content_serialized") is not False
        or value.get("raw_identification_serialized") is not False
        or value.get("internal_network_shared") is not True
    ):
        raise SFTPBoundaryError("Docker SFTP protocol proof is not bound to this deployment")
    if not all(
        isinstance(value.get(key), dict)
        for key in (
            "sftp_identity",
            "client_identity",
            "protocol",
            "authentication_audit",
            "closed_boundary_binding",
            "revision_binding",
        )
    ):
        raise SFTPBoundaryError("Docker SFTP protocol proof structure is invalid")
    closed_proof_sha256 = str(value.get("closed_proof_sha256") or "")
    binding = value["closed_boundary_binding"]
    revision_binding = value["revision_binding"]
    protocol = value["protocol"]
    audit = value["authentication_audit"]
    fingerprint = str(protocol.get("host_key_fingerprint") or "")
    if (
        re.fullmatch(r"[0-9a-f]{64}", closed_proof_sha256) is None
        or binding
        != {
            "same_candidate_sha": True,
            "same_sftp_sha": True,
            "server_client_sha_distinct": True,
            "same_deployment_id": True,
            "same_container_id": True,
            "same_image_id": True,
            "same_host_key_fingerprint": True,
        }
        or revision_binding
        != _revision_binding(
            sha, sftp_sha, client_image_revision_verified=True
        )
        or value["sftp_identity"].get("revision") != sftp_sha
        or value["client_identity"].get("revision") != sha
        or FINGERPRINT_RE.fullmatch(fingerprint) is None
        or protocol.get("ssh_v2_identification_validated") is not True
        or protocol.get("key_exchange_completed") is not True
        or protocol.get("host_key_algorithm") != "ssh-ed25519"
        or protocol.get("host_key_stable") is not True
        or protocol.get("none_auth_rejected") is not True
        or protocol.get("password_offered") is not True
        or protocol.get("password_submitted") is not False
        or protocol.get("sftp_subsystem_requested") is not False
        or protocol.get("directory_enumeration_requested") is not False
        or audit.get("unchanged") is not True
        or any(
            audit.get(key) != 0
            for key in ("added_count", "removed_count", "changed_count")
        )
    ):
        raise SFTPBoundaryError("Docker SFTP protocol proof has no valid closed-boundary chain")
    return value, hashlib.sha256(raw).hexdigest()


def _load_validation_proof(
    path: Path, *, sha: str, deployment_id: str
) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise SFTPBoundaryError("safe deployment validation proof is unavailable")
    try:
        details = path.stat()
        if (
            not stat_module.S_ISREG(details.st_mode)
            or stat_module.S_IMODE(details.st_mode) != 0o600
            or details.st_size <= 0
            or details.st_size > MAX_VALIDATION_PROOF_BYTES
        ):
            raise SFTPBoundaryError("safe deployment validation proof file is unsafe")
        raw = path.read_bytes()
        value = json.loads(raw)
    except SFTPBoundaryError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise SFTPBoundaryError("safe deployment validation proof is invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or value.get("kind") != "safe_deployment_validation"
        or value.get("candidate_sha") != sha
        or value.get("deployment_id") != deployment_id
        or value.get("result") != "passed"
        or not isinstance(value.get("database_revision"), str)
        or not value.get("database_revision")
        or not isinstance(value.get("generated_at"), str)
        or not value.get("generated_at")
        or value.get("max_age_seconds") != 3600
    ):
        raise SFTPBoundaryError("safe deployment validation is not bound to this deployment")
    checks = value.get("checks")
    if (
        not isinstance(checks, dict)
        or not checks
        or any(check is not True for check in checks.values())
        or not all(isinstance(name, str) and name for name in checks)
        or not isinstance(value.get("runtime_env"), dict)
        or not isinstance(value.get("evidence"), dict)
        or not value.get("evidence")
        or not isinstance(value.get("digests"), dict)
        or not value.get("digests")
    ):
        raise SFTPBoundaryError("safe deployment validation lacks passing evidence")
    return value, hashlib.sha256(raw).hexdigest()


def build_host_banner_contract(
    *,
    sha: str,
    sftp_sha: str,
    deployment_id: str,
    protocol_proof_path: Path,
    validation_proof_path: Path,
) -> dict[str, Any]:
    _validate_boundary_identity(sha, sftp_sha, deployment_id)
    validation_proof, validation_proof_sha256 = _load_validation_proof(
        validation_proof_path, sha=sha, deployment_id=deployment_id
    )
    protocol_proof, protocol_proof_sha256 = _load_protocol_proof(
        protocol_proof_path,
        sha=sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
    )
    validation_closed = validation_proof.get("evidence", {}).get(
        "sftp_closed_after"
    )
    if (
        validation_proof.get("checks", {}).get("sftp_closed_boundary") is not True
        or not isinstance(validation_closed, dict)
        or validation_closed.get("outcome") != "passed"
        or validation_closed.get("sha256")
        != protocol_proof.get("closed_proof_sha256")
    ):
        raise SFTPBoundaryError(
            "safe deployment validation is not bound to the final closed SFTP proof"
        )
    sftp, client = _validate_boundary_containers(
        sha=sha, sftp_sha=sftp_sha, require_sftp_running=True
    )
    sftp_id = _container_id(sftp)
    client_id = _container_id(client)
    if (
        protocol_proof.get("sftp_identity", {}).get("container_id") != sftp_id
        or protocol_proof.get("sftp_identity", {}).get("image_id") != _image_id(sftp)
        or protocol_proof.get("client_identity", {}).get("container_id") != client_id
        or protocol_proof.get("client_identity", {}).get("image_id") != _image_id(client)
    ):
        raise SFTPBoundaryError("published SFTP probe does not target the proven containers")
    host_port = _published_sftp_port(sftp)
    gates = _gate_contract(
        deployment_id=deployment_id,
        host_port=host_port,
        expected_closed=True,
    )
    before_payload = _docker_db_auth_inventory(
        sha=sha, deployment_id=deployment_id
    )
    protocol = _read_published_ssh_identification(host_port)
    after_payload = _docker_db_auth_inventory(
        sha=sha, deployment_id=deployment_id
    )
    audit = _compare_auth_inventory(
        before_payload["inventory"], after_payload["inventory"]
    )
    for payload in (before_payload, after_payload):
        runtime_id = str(payload.get("client_identity", {}).get("container_id") or "")
        if not CONTAINER_ID_RE.fullmatch(runtime_id) or not client_id.startswith(runtime_id):
            raise SFTPBoundaryError("database inventory runtime identity is not Docker-bound")
    fingerprint = str(
        protocol_proof.get("protocol", {}).get("host_key_fingerprint") or ""
    )
    if FINGERPRINT_RE.fullmatch(fingerprint) is None:
        raise SFTPBoundaryError("Docker SFTP host-key proof is invalid")
    return {
        "schema_version": 2,
        "kind": "agentium_sftp_deploy_boundary",
        "profile": PROFILE_HOST_BANNER,
        "sha": sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "captured_at": _utc_now(),
        "result": "passed",
        "sftp_identity": {
            "container_id": sftp_id,
            "image_id": _image_id(sftp),
            "revision": sftp_sha,
            "healthy": True,
            "restart_policy_disabled": True,
        },
        "client_identity": {
            "container_id": client_id,
            "image_id": _image_id(client),
            "revision": sha,
        },
        "revision_binding": _revision_binding(
            sha, sftp_sha, client_image_revision_verified=True
        ),
        "ingress_gate": gates,
        "protocol": protocol,
        "host_key": {
            "algorithm": "ssh-ed25519",
            "fingerprint": fingerprint,
            "bound_to_internal_protocol_proof": True,
        },
        "authentication_audit": audit,
        "validation_proof_sha256": validation_proof_sha256,
        "closed_proof_sha256": protocol_proof["closed_proof_sha256"],
        "protocol_proof_sha256": protocol_proof_sha256,
        "proof_chain": {
            "validation_bound": True,
            "closed_boundary_bound": True,
            "docker_protocol_bound": True,
            "published_transport_bound": True,
            "candidate_sha_bound": True,
            "sftp_sha_bound": True,
            "server_client_sha_distinct": True,
        },
        "credentials_used": False,
        "content_serialized": False,
        "raw_identification_serialized": False,
        "assurance": "pinned_release_a_sftp_published_ssh_identification_under_external_gate_bound_to_release_b_client_internal_key_zero_audit_delta_and_no_positive_login",
        "proof_ceiling": "runner_verified",
    }


def _write_serialized(serialized: str, destination: str) -> None:
    if destination == "-":
        sys.stdout.write(serialized)
        return
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        parent_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _write_json(payload: Mapping[str, Any], destination: str) -> None:
    _write_serialized(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        destination,
    )


def _write_canonical_json(payload: Mapping[str, Any], destination: str) -> None:
    _write_serialized(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        destination,
    )


def _add_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sha", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--output", default="-")


def _add_sftp_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sftp-sha", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validation_ready = subparsers.add_parser("validation-ready")
    validation_ready.add_argument("--live-sha", required=True)
    validation_ready.add_argument("--release-a-sha", required=True)
    validation_ready.add_argument("--sftp-sha", required=True)
    validation_ready.add_argument("--deployment-id", required=True)
    validation_ready.add_argument("--expected-secure-source", required=True)
    validation_ready.add_argument("--output", default="-")
    live_identity = subparsers.add_parser("verify-runtime-identity-live")
    live_identity.add_argument("--runtime-proof", required=True)
    live_identity.add_argument("--live-sha", required=True)
    live_identity.add_argument("--release-a-sha", required=True)
    live_identity.add_argument("--sftp-sha", required=True)
    live_identity.add_argument("--deployment-id", required=True)
    live_identity.add_argument("--expected-secure-source", required=True)
    live_identity.add_argument(
        "--expected-secure-mode", required=True, choices=("ro", "rw")
    )
    live_identity.add_argument(
        "--expected-restart", required=True, choices=("disabled", "historical")
    )
    live_identity.add_argument("--runtime-state")
    live_identity.add_argument("--allow-paused", action="store_true")
    live_identity.add_argument("--output", default="-")
    closed = subparsers.add_parser("closed-boundary")
    _add_identity(closed)
    _add_sftp_identity(closed)
    closed.add_argument("--expected-secure-source", required=True)
    protocol_client = subparsers.add_parser("protocol-client")
    _add_identity(protocol_client)
    docker_protocol = subparsers.add_parser("docker-protocol")
    _add_identity(docker_protocol)
    _add_sftp_identity(docker_protocol)
    docker_protocol.add_argument("--closed-proof", required=True)
    inventory = subparsers.add_parser("db-auth-inventory")
    _add_identity(inventory)
    rollback = subparsers.add_parser("rollback-continuity")
    _add_identity(rollback)
    _add_sftp_identity(rollback)
    rollback.add_argument("--candidate-sha", required=True)
    rollback.add_argument("--closed-proof", required=True)
    rollback.add_argument("--expected-secure-source", required=True)
    host = subparsers.add_parser("host-banner")
    _add_identity(host)
    _add_sftp_identity(host)
    host.add_argument("--protocol-proof", required=True)
    host.add_argument("--validation-proof", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validation-ready":
            payload = build_validation_ready_contract(
                live_sha=args.live_sha,
                release_a_sha=args.release_a_sha,
                sftp_sha=args.sftp_sha,
                deployment_id=args.deployment_id,
                expected_secure_source=args.expected_secure_source,
            )
        elif args.command == "verify-runtime-identity-live":
            payload = verify_runtime_identity_live_contract(
                receipt_path=Path(args.runtime_proof),
                live_sha=args.live_sha,
                release_a_sha=args.release_a_sha,
                sftp_sha=args.sftp_sha,
                deployment_id=args.deployment_id,
                expected_secure_source=args.expected_secure_source,
                expected_secure_mode=args.expected_secure_mode,
                expected_restart=args.expected_restart,
                runtime_state_path=(
                    Path(args.runtime_state) if args.runtime_state is not None else None
                ),
                allow_paused=args.allow_paused,
            )
        elif args.command == "closed-boundary":
            payload = build_closed_boundary_contract(
                sha=args.sha,
                sftp_sha=args.sftp_sha,
                deployment_id=args.deployment_id,
                expected_secure_source=args.expected_secure_source,
            )
        elif args.command == "protocol-client":
            payload = build_protocol_client_contract(
                sha=args.sha, deployment_id=args.deployment_id
            )
        elif args.command == "docker-protocol":
            payload = build_docker_protocol_contract(
                sha=args.sha,
                sftp_sha=args.sftp_sha,
                deployment_id=args.deployment_id,
                closed_proof_path=Path(args.closed_proof),
            )
        elif args.command == "db-auth-inventory":
            payload = build_db_auth_inventory_contract(
                sha=args.sha, deployment_id=args.deployment_id
            )
        elif args.command == "rollback-continuity":
            payload = build_rollback_continuity_contract(
                sha=args.sha,
                candidate_sha=args.candidate_sha,
                sftp_sha=args.sftp_sha,
                deployment_id=args.deployment_id,
                closed_proof_path=Path(args.closed_proof),
                expected_secure_source=args.expected_secure_source,
            )
        elif args.command == "host-banner":
            payload = build_host_banner_contract(
                sha=args.sha,
                sftp_sha=args.sftp_sha,
                deployment_id=args.deployment_id,
                protocol_proof_path=Path(args.protocol_proof),
                validation_proof_path=Path(args.validation_proof),
            )
        else:  # pragma: no cover - argparse owns the command vocabulary
            raise SFTPBoundaryError("unsupported command")
        if args.command in {"validation-ready", "verify-runtime-identity-live"}:
            _write_canonical_json(payload, args.output)
        else:
            _write_json(payload, args.output)
    except SFTPBoundaryError as exc:
        print(f"SFTP deployment boundary failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
