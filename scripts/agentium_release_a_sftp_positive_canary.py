#!/usr/bin/env python3
"""Produce a content-free positive SFTP canary for Agentium Release A.

The canary proves password authentication and creation of a real SFTP
subsystem. It deliberately performs only ``getcwd()`` and a single ``stat``
of the absolute root path. It never enumerates, reads, creates, modifies, or
removes remote content.

The password and known-hosts inputs are snapshotted through no-follow file
descriptors before any network operation. Runtime identities and credentials
are represented in the resulting evidence only by cryptographic hashes.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import stat
import sys
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
HOST_KEY_FINGERPRINT_RE = re.compile(r"^SHA256:([A-Za-z0-9+/]{43}=?)$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RUNTIME_ID_RE = re.compile(r"^[0-9a-f]{64}$")
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ACCESS_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)

DEFAULT_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 30.0
MAX_PASSWORD_BYTES = 4096
MAX_KNOWN_HOSTS_BYTES = 1024 * 1024
MAX_PRIVATE_RECEIPT_BYTES = 256 * 1024
MAX_READY_TO_AUTH_SECONDS = 300
# The positive->revoke and revoke->ledger windows must each fully span one
# PostgreSQL inventory snapshot of the protected database.  That snapshot
# streams and hashes every row of every public table, so its wall-clock cost
# scales with data volume, not with any security property: on the production
# database (knowledge_document_facts ~1.7M rows / 4 GB, audit_logs ~694k rows)
# a single snapshot measures ~460 s.  The 300 s ceiling therefore made
# record-sftp-final structurally impossible on a real corpus even though the
# gates (ingress shut, writers stopped, read-only barriers) enforce isolation
# independently.  1200 s (~2.5x the measured snapshot) leaves headroom for
# corpus growth while keeping the evidence-staleness guard meaningful.
MAX_POSITIVE_TO_REVOKE_SECONDS = 1200
MAX_REVOKE_TO_LEDGER_SECONDS = 1200
MAX_ATTEMPT_RECOVERY_SECONDS = 300
RELEASE_A_ACCESS_ID_PREFIX = "ra1_"

PROFILE = "agentium-release-a-sftp-positive-canary-v1"
KIND = "agentium_release_a_sftp_positive_canary"
POST_REVOKE_PROFILE = "agentium-release-a-sftp-post-revoke-v1"
POST_REVOKE_KIND = "agentium_release_a_sftp_post_revoke"
LIFECYCLE_PROFILE = "agentium-release-a-sftp-positive-auth-lifecycle-v1"
LIFECYCLE_KIND = "sftp-positive-auth.artifact"


class SFTPPositiveCanaryError(RuntimeError):
    """Fail-closed error whose message contains no sensitive runtime value."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise SFTPPositiveCanaryError("invalid command arguments")


def _sha256_domain(domain: bytes, value: bytes) -> str:
    return hashlib.sha256(domain + b"\0" + value).hexdigest()


def _sha256_parts(domain: bytes, *values: str | bytes) -> str:
    digest = hashlib.sha256(domain)
    for value in values:
        digest.update(b"\0")
        digest.update(value if isinstance(value, bytes) else value.encode("utf-8"))
    return digest.hexdigest()


def _credential_fingerprint(
    *, deployment_id: str, access_id: str, password: bytes
) -> str:
    return _sha256_parts(
        b"agentium-release-a-sftp-credential-v1",
        deployment_id,
        access_id,
        password,
    )


def _validate_bindings(
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    sftp_image_id: str,
    sftp_runtime_id: str,
) -> None:
    if SHA_RE.fullmatch(live_sha) is None:
        raise SFTPPositiveCanaryError("live release binding is invalid")
    if SHA_RE.fullmatch(release_a_sha) is None:
        raise SFTPPositiveCanaryError("release binding is invalid")
    if SHA_RE.fullmatch(sftp_sha) is None:
        raise SFTPPositiveCanaryError("SFTP release binding is invalid")
    if DEPLOYMENT_ID_RE.fullmatch(deployment_id) is None:
        raise SFTPPositiveCanaryError("deployment binding is invalid")
    if IMAGE_ID_RE.fullmatch(sftp_image_id) is None:
        raise SFTPPositiveCanaryError("SFTP image binding is invalid")
    if RUNTIME_ID_RE.fullmatch(sftp_runtime_id) is None:
        raise SFTPPositiveCanaryError("SFTP runtime binding is invalid")
    if live_sha == release_a_sha:
        raise SFTPPositiveCanaryError("live and candidate release bindings must differ")


def _canonical_absolute_path(raw_path: str) -> PurePath:
    if (
        not raw_path
        or "\x00" in raw_path
        or not raw_path.startswith("/")
        or raw_path.startswith("//")
        or os.path.normpath(raw_path) != raw_path
    ):
        raise SFTPPositiveCanaryError("input path is not canonical")
    path = PurePath(raw_path)
    if any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise SFTPPositiveCanaryError("input path is not canonical")
    return path


def _open_parent_nofollow(path: PurePath) -> tuple[int, str]:
    """Open every parent component with O_NOFOLLOW and return its dir fd."""

    if len(path.parts) < 2 or path.name in {"", ".", ".."}:
        raise SFTPPositiveCanaryError("input path is invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:-1]:
            next_descriptor = os.open(
                component,
                flags | nofollow,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, path.name
    except BaseException:
        os.close(descriptor)
        raise


def _file_signature(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_stable_regular_file(
    raw_path: str,
    *,
    max_bytes: int,
    private_modes: frozenset[int] | None,
) -> bytes:
    path = _canonical_absolute_path(raw_path)
    parent_fd, name = _open_parent_nofollow(path)
    descriptor = -1
    try:
        before_path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        before_mode = stat.S_IMODE(before_path.st_mode)
        if (
            not stat.S_ISREG(before_path.st_mode)
            or before_path.st_uid != os.geteuid()
            or before_path.st_nlink != 1
            or before_path.st_size <= 0
            or before_path.st_size > max_bytes
        ):
            raise SFTPPositiveCanaryError("input file is unsafe")
        if private_modes is not None:
            if before_mode not in private_modes:
                raise SFTPPositiveCanaryError("private input mode is unsafe")
        elif before_mode & 0o022:
            raise SFTPPositiveCanaryError("trusted input is writable by others")
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        before_fd = os.fstat(descriptor)
        mode = stat.S_IMODE(before_fd.st_mode)
        if (
            not stat.S_ISREG(before_fd.st_mode)
            or before_fd.st_uid != os.geteuid()
            or before_fd.st_nlink != 1
            or before_fd.st_size <= 0
            or before_fd.st_size > max_bytes
            or _file_signature(before_path) != _file_signature(before_fd)
        ):
            raise SFTPPositiveCanaryError("input file is unsafe")
        if private_modes is not None:
            if mode not in private_modes:
                raise SFTPPositiveCanaryError("private input mode is unsafe")
        elif mode & 0o022:
            raise SFTPPositiveCanaryError("trusted input is writable by others")

        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        body = b"".join(chunks)
        after_fd = os.fstat(descriptor)
        after_path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            len(body) != before_fd.st_size
            or len(body) > max_bytes
            or _file_signature(before_fd) != _file_signature(after_fd)
            or _file_signature(after_fd) != _file_signature(after_path)
        ):
            raise SFTPPositiveCanaryError("input file changed during read")
        return body
    except SFTPPositiveCanaryError:
        raise
    except (OSError, ValueError) as exc:
        raise SFTPPositiveCanaryError("input file could not be read safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def _read_password(raw_path: str) -> bytes:
    body = _read_stable_regular_file(
        raw_path,
        max_bytes=MAX_PASSWORD_BYTES,
        private_modes=frozenset({0o400, 0o600}),
    )
    if body.endswith(b"\r\n"):
        body = body[:-2]
    elif body.endswith(b"\n"):
        body = body[:-1]
    if not body or b"\n" in body or b"\r" in body or b"\x00" in body:
        raise SFTPPositiveCanaryError("password file content is invalid")
    try:
        body.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SFTPPositiveCanaryError("password file encoding is invalid") from exc
    return body


def _read_known_hosts(raw_path: str) -> bytes:
    body = _read_stable_regular_file(
        raw_path,
        max_bytes=MAX_KNOWN_HOSTS_BYTES,
        private_modes=None,
    )
    if b"\x00" in body:
        raise SFTPPositiveCanaryError("known-hosts content is invalid")
    return body


def _normalize_host(host: str) -> str:
    if (
        not isinstance(host, str)
        or not 1 <= len(host) <= 253
        or host != host.strip()
        or any(ord(character) < 33 or ord(character) == 127 for character in host)
        or any(character in host for character in ("/", "@", "?", "#", "[", "]"))
    ):
        raise SFTPPositiveCanaryError("SFTP endpoint identity is invalid")
    normalized = host.rstrip(".").lower()
    if not normalized:
        raise SFTPPositiveCanaryError("SFTP endpoint identity is invalid")
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SFTPPositiveCanaryError("SFTP endpoint identity is invalid") from exc


def _normalize_loopback_endpoint(host: str) -> str:
    if not isinstance(host, str) or host != host.strip():
        raise SFTPPositiveCanaryError("SFTP endpoint is not a loopback literal")
    try:
        endpoint = ipaddress.ip_address(host)
    except ValueError:
        raise SFTPPositiveCanaryError(
            "SFTP endpoint is not a loopback literal"
        ) from None
    if endpoint not in {
        ipaddress.IPv4Address("127.0.0.1"),
        ipaddress.IPv6Address("::1"),
    }:
        raise SFTPPositiveCanaryError("SFTP endpoint is not loopback-bound")
    return endpoint.compressed


def _validate_username(username: str) -> str:
    if (
        not isinstance(username, str)
        or ACCESS_ID_RE.fullmatch(username) is None
        or not username.startswith(RELEASE_A_ACCESS_ID_PREFIX)
        or len(username) <= len(RELEASE_A_ACCESS_ID_PREFIX)
    ):
        raise SFTPPositiveCanaryError("SFTP principal identity is invalid")
    return username


def _normalize_fingerprint(value: str) -> str:
    match = HOST_KEY_FINGERPRINT_RE.fullmatch(value)
    if match is None:
        raise SFTPPositiveCanaryError("host-key fingerprint is invalid")
    encoded = match.group(1).rstrip("=")
    try:
        digest = base64.b64decode(encoded + "=", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise SFTPPositiveCanaryError("host-key fingerprint is invalid") from exc
    if len(digest) != hashlib.sha256().digest_size:
        raise SFTPPositiveCanaryError("host-key fingerprint is invalid")
    return f"SHA256:{encoded}"


def _validate_timeout(value: float) -> float:
    if not MIN_TIMEOUT_SECONDS <= value <= MAX_TIMEOUT_SECONDS:
        raise SFTPPositiveCanaryError("network timeout is outside the safe bound")
    return value


async def _positive_sftp_probe(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    known_hosts: bytes,
    expected_host_key_fingerprint: str,
    timeout: float,
) -> None:
    try:
        import asyncssh
    except ImportError as exc:  # pragma: no cover - runtime-image condition
        raise SFTPPositiveCanaryError("AsyncSSH runtime is unavailable") from exc

    try:
        async with asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password,
            known_hosts=known_hosts,
            config=None,
            client_keys=None,
            client_certs=[],
            agent_path=None,
            pkcs11_provider=None,
            gss_kex=False,
            gss_auth=False,
            host_based_auth=False,
            public_key_auth=False,
            kbdint_auth=False,
            password_auth=True,
            preferred_auth=("password",),
            disable_trivial_auth=True,
            connect_timeout=timeout,
            login_timeout=timeout,
            server_host_key_algs=["ssh-ed25519"],
            client_version="AgentiumReleaseASFTPPositiveCanary",
        ) as connection:
            server_key = connection.get_server_host_key()
            if str(server_key.get_algorithm()) != "ssh-ed25519":
                raise SFTPPositiveCanaryError("host-key algorithm mismatch")
            actual_fingerprint = _normalize_fingerprint(
                str(server_key.get_fingerprint("sha256"))
            )
            if not hmac.compare_digest(
                actual_fingerprint, expected_host_key_fingerprint
            ):
                raise SFTPPositiveCanaryError("host-key fingerprint mismatch")
            async with connection.start_sftp_client() as sftp:
                await sftp.getcwd()
                # Stat the absolute root explicitly. A bare "." is composed by
                # AsyncSSH against the working directory returned by getcwd()
                # into the wire path "/.", which the Secure Deposit SFTP server
                # does not normalise back to root; an absolute "/" is
                # unambiguous and independent of the client working directory.
                attributes = await sftp.stat("/")
                if attributes is None:
                    raise SFTPPositiveCanaryError("SFTP stat proof is absent")
    except SFTPPositiveCanaryError:
        raise
    except BaseException:
        # AsyncSSH exceptions routinely embed endpoint and principal values.
        raise SFTPPositiveCanaryError("positive SFTP protocol proof failed") from None


async def _post_revoke_probe(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    known_hosts: bytes,
    expected_host_key_fingerprint: str,
    timeout: float,
) -> None:
    """Prove that the formerly valid password is now rejected.

    A content-free host-key handshake first binds the current endpoint to the
    expected fingerprint. The authenticated connection must then fail with
    AsyncSSH's dedicated ``PermissionDenied`` exception. Any other outcome is
    a failure, and no SFTP subsystem is requested in this phase.
    """

    try:
        import asyncssh
    except ImportError as exc:  # pragma: no cover - runtime-image condition
        raise SFTPPositiveCanaryError("AsyncSSH runtime is unavailable") from exc

    common = {
        "host": host,
        "port": port,
        "config": None,
        "connect_timeout": timeout,
        "server_host_key_algs": ["ssh-ed25519"],
        "client_version": "AgentiumReleaseASFTPPositiveCanary",
    }
    try:
        current_key = await asyncssh.get_server_host_key(**common)
        if str(current_key.get_algorithm()) != "ssh-ed25519":
            raise SFTPPositiveCanaryError("host-key algorithm mismatch")
        current_fingerprint = _normalize_fingerprint(
            str(current_key.get_fingerprint("sha256"))
        )
        if not hmac.compare_digest(
            current_fingerprint, expected_host_key_fingerprint
        ):
            raise SFTPPositiveCanaryError("host-key fingerprint mismatch")
        credential_accepted = False
        try:
            async with asyncssh.connect(
                host,
                port=port,
                username=username,
                password=password,
                known_hosts=known_hosts,
                config=None,
                client_keys=None,
                client_certs=[],
                agent_path=None,
                pkcs11_provider=None,
                gss_kex=False,
                gss_auth=False,
                host_based_auth=False,
                public_key_auth=False,
                kbdint_auth=False,
                password_auth=True,
                preferred_auth=("password",),
                disable_trivial_auth=True,
                connect_timeout=timeout,
                login_timeout=timeout,
                server_host_key_algs=["ssh-ed25519"],
                client_version="AgentiumReleaseASFTPPositiveCanary",
            ):
                credential_accepted = True
        except asyncssh.PermissionDenied:
            if credential_accepted:
                raise SFTPPositiveCanaryError(
                    "revoked credential was accepted before close failure"
                ) from None
            return
        if credential_accepted:
            raise SFTPPositiveCanaryError("revoked credential was accepted")
        raise SFTPPositiveCanaryError("post-revocation authentication was ambiguous")
    except SFTPPositiveCanaryError:
        raise
    except BaseException:
        raise SFTPPositiveCanaryError("post-revocation SFTP proof failed") from None


def _completed_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SFTPPositiveCanaryError("evidence JSON has duplicate keys")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise SFTPPositiveCanaryError("evidence JSON contains an invalid number")

    try:
        payload = json.loads(
            raw,
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise SFTPPositiveCanaryError("evidence JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise SFTPPositiveCanaryError("evidence JSON is not an object")
    return payload


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _strict_canonical_json_object(raw: bytes) -> dict[str, Any]:
    payload = _strict_json_object(raw)
    if not hmac.compare_digest(raw, _canonical_json_bytes(payload)):
        raise SFTPPositiveCanaryError("evidence JSON is not canonical")
    return payload


def _require_exact_keys(
    value: dict[str, Any], expected: frozenset[str], *, label: str
) -> None:
    if frozenset(value) != expected:
        raise SFTPPositiveCanaryError(f"{label} schema is not closed")


def _is_exact_int(value: Any, expected: int | None = None) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and (expected is None or value == expected)
    )


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or TIMESTAMP_RE.fullmatch(value) is None:
        raise SFTPPositiveCanaryError("evidence timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise SFTPPositiveCanaryError("evidence timestamp is invalid") from exc
    if parsed.tzinfo != UTC:
        raise SFTPPositiveCanaryError("evidence timestamp is invalid")
    return parsed


_POSITIVE_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "profile",
        "result",
        "live_sha",
        "release_a_sha",
        "sftp_sha",
        "deployment_id",
        "hostname_sha256",
        "access_id_sha256",
        "credential_fingerprint_sha256",
        "known_hosts_sha256",
        "host_key_fingerprint",
        "sftp_container_id",
        "sftp_image_id",
        "sftp_port",
        "sftp_started_at",
        "runtime_identity_sha256",
        "runtime_ready_receipt_sha256",
        "auth_started_at",
        "auth_completed_at",
        "checks",
    }
)
_POSITIVE_CHECK_KEYS = frozenset(
    {
        "password_source_private_nofollow",
        "known_hosts_pinned",
        "host_key_fingerprint_matched",
        "password_only_authentication",
        "sftp_subsystem_started",
        "sftp_subsystem_closed",
        "getcwd_completed",
        "stat_dot_completed",
        "directory_enumeration_operations",
        "content_read_operations",
        "mutation_operations",
    }
)
_POST_REVOKE_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "profile",
        "result",
        "live_sha",
        "release_a_sha",
        "sftp_sha",
        "deployment_id",
        "hostname_sha256",
        "access_id_sha256",
        "credential_fingerprint_sha256",
        "known_hosts_sha256",
        "host_key_fingerprint",
        "sftp_container_id",
        "sftp_image_id",
        "sftp_port",
        "sftp_started_at",
        "runtime_identity_sha256",
        "runtime_ready_receipt_sha256",
        "positive_evidence_sha256",
        "positive_completed_at",
        "revocation_check_started_at",
        "completed_at",
        "authentication_denied",
        "sftp_subsystem_requested_after_revocation",
        "directory_enumeration_operations",
        "content_read_operations",
        "mutation_operations",
    }
)
_RUNTIME_READY_KEYS = frozenset(
    {
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
        "sftp_port",
        "sftp_started_at",
        "image_revision",
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
        "ready_at",
    }
)
_LEDGER_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "result",
        "live_sha",
        "release_a_sha",
        "sftp_sha",
        "deployment_id",
        "hostname_sha256",
        "workspace_id_sha256",
        "link_id_sha256",
        "access_id_sha256",
        "credential_fingerprint_sha256",
        "sftp_container_id",
        "sftp_image_id",
        "sftp_port",
        "runtime_identity_sha256",
        "link_status",
        "auth_failed_reason",
        "remaining_active_link_count",
        "active_sftp_session_count",
        "deposit_file_delta_count",
        "audits",
        "binding_sha256",
        "collected_at",
    }
)
_AUDIT_KEYS = frozenset(
    {"event_type", "event_id_sha256", "event_digest_sha256", "count", "occurred_at"}
)
_AUDIT_NAMES = {
    "created": "deposit.link.created",
    "auth_success": "deposit.sftp.auth.success",
    "revoked": "deposit.link.revoked",
    "auth_failed_inactive": "deposit.sftp.auth.failed",
}
_AUDIT_SUMMARY_KEYS = frozenset(
    {
        "workspace_id_sha256",
        "link_id_sha256",
        "access_id_sha256",
        "created_event_id_sha256",
        "created_event_digest_sha256",
        "auth_success_event_id_sha256",
        "auth_success_event_digest_sha256",
        "revoked_event_id_sha256",
        "revoked_event_digest_sha256",
        "auth_failed_event_id_sha256",
        "auth_failed_event_digest_sha256",
        "created_count",
        "auth_success_count",
        "revoked_count",
        "auth_failed_inactive_count",
    }
)
_LIFECYCLE_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "profile",
        "result",
        "live_sha",
        "release_a_sha",
        "sftp_sha",
        "deployment_id",
        "hostname_sha256",
        "workspace_id_sha256",
        "link_id_sha256",
        "access_id_sha256",
        "credential_fingerprint_sha256",
        "known_hosts_sha256",
        "host_key_fingerprint",
        "sftp_container_id",
        "sftp_image_id",
        "sftp_port",
        "sftp_started_at",
        "image_revision",
        "runtime_identity_sha256",
        "runtime_ready_receipt_sha256",
        "ingress_closed",
        "restart_disabled",
        "restart_policy_disabled",
        "secure_deposit_mode",
        "secure_deposit_source",
        "external_established_connection_count",
        "ingress_gate",
        "positive_evidence_sha256",
        "post_revoke_evidence_sha256",
        "positive_proof",
        "post_revoke_proof",
        "ledger_sha256",
        "auth_started_at",
        "auth_completed_at",
        "revoked_at",
        "denial_started_at",
        "denial_completed_at",
        "completed_at",
        "authentication_result",
        "subsystem_result",
        "revoke_result",
        "post_revoke_authentication_result",
        "link_status",
        "remaining_active_link_count",
        "active_sftp_session_count",
        "deposit_file_delta_count",
        "audit_summary",
    }
)


def _hostname_fingerprint(host: str) -> str:
    return hashlib.sha256(host.encode("ascii")).hexdigest()


def _runtime_identity_fingerprint(
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
    return _sha256_parts(
        b"agentium-release-a-sftp-runtime-identity-v1",
        live_sha,
        release_a_sha,
        sftp_sha,
        deployment_id,
        hostname_sha256,
        sftp_container_id,
        sftp_image_id,
        str(sftp_port),
        sftp_started_at,
    )


def _read_private_canonical_json(raw_path: str) -> tuple[bytes, dict[str, Any]]:
    raw = _read_stable_regular_file(
        raw_path,
        max_bytes=MAX_PRIVATE_RECEIPT_BYTES,
        private_modes=frozenset({0o400, 0o600}),
    )
    return raw, _strict_canonical_json_object(raw)


def _validate_runtime_ready_receipt(
    payload: dict[str, Any],
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    hostname_sha256: str,
    sftp_container_id: str,
    sftp_image_id: str,
    sftp_port: int,
    host_key_fingerprint: str,
) -> tuple[datetime, str, str]:
    _require_exact_keys(payload, _RUNTIME_READY_KEYS, label="runtime-ready receipt")
    expected: dict[str, Any] = {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-runtime-ready",
        "result": "passed",
        "live_sha": live_sha,
        "release_a_sha": release_a_sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "hostname_sha256": hostname_sha256,
        "sftp_container_id": sftp_container_id,
        "sftp_image_id": sftp_image_id,
        "sftp_port": sftp_port,
        "image_revision": sftp_sha,
        "host_key_fingerprint": host_key_fingerprint,
        "state": "running",
        "health_status": "healthy",
        "ingress_closed": True,
        "restart_disabled": True,
        "restart_policy_disabled": True,
        "secure_deposit_mode": "ro",
        "secure_deposit_source": "/dev/sdc",
        "external_established_connection_count": 0,
        "credentials_used": False,
        "authentication_attempted": False,
        "sftp_subsystem_requested": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
        "raw_identification_serialized": False,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise SFTPPositiveCanaryError("runtime-ready receipt binding is invalid")
    if (
        not _is_exact_int(payload.get("schema_version"), 1)
        or not _is_exact_int(payload.get("sftp_port"), sftp_port)
        or not _is_exact_int(payload.get("external_established_connection_count"), 0)
    ):
        raise SFTPPositiveCanaryError("runtime-ready receipt numeric type is invalid")
    for key in (
        "ingress_closed",
        "restart_disabled",
        "restart_policy_disabled",
    ):
        if payload.get(key) is not True:
            raise SFTPPositiveCanaryError("runtime-ready boolean proof is invalid")
    for key in (
        "credentials_used",
        "authentication_attempted",
        "sftp_subsystem_requested",
        "content_serialized",
        "raw_network_data_serialized",
        "raw_identification_serialized",
    ):
        if payload.get(key) is not False:
            raise SFTPPositiveCanaryError("runtime-ready boolean proof is invalid")
    ingress_gate = payload.get("ingress_gate")
    if ingress_gate != {
        "ipv4_input": True,
        "ipv4_docker_user": True,
        "ipv6_input": True,
        "ipv6_docker_user": True,
    }:
        raise SFTPPositiveCanaryError("runtime-ready ingress proof is incomplete")
    published = payload.get("published_transport")
    if not isinstance(published, dict) or frozenset(published) != frozenset(
        {
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
    ):
        raise SFTPPositiveCanaryError("runtime-ready transport schema is not closed")
    if (
        published.get("protocol") != "tcp"
        or published.get("container_port") != 2222
        or published.get("host_port") != sftp_port
        or not _is_exact_int(published.get("binding_count"))
        or not 1 <= published["binding_count"] <= 2
        or HEX_SHA256_RE.fullmatch(str(published.get("binding_sha256") or ""))
        is None
        or not _is_exact_int(published.get("listener_count"))
        or published["listener_count"] <= 0
        or not _is_exact_int(published.get("established_connection_count_before"), 0)
        or not _is_exact_int(published.get("established_connection_count_after"), 0)
        or not _is_exact_int(published.get("external_established_connection_count"), 0)
        or published.get("ssh_v2_identification_validated") is not True
        or published.get("connection_closed_before_authentication") is not True
        or published.get("raw_identification_serialized") is not False
    ):
        raise SFTPPositiveCanaryError("runtime-ready transport proof is invalid")
    secure_deposit = payload.get("secure_deposit")
    if not isinstance(secure_deposit, dict) or frozenset(secure_deposit) != frozenset(
        {
            "source_matches_dev_sdc",
            "source_device_sha256",
            "autonomous_mountpoint",
            "host_read_only",
            "namespace_autonomous_mountpoint",
            "namespace_read_only",
            "device_id",
        }
    ):
        raise SFTPPositiveCanaryError("runtime-ready Secure Deposit schema is not closed")
    if (
        secure_deposit.get("source_matches_dev_sdc") is not True
        or HEX_SHA256_RE.fullmatch(
            str(secure_deposit.get("source_device_sha256") or "")
        )
        is None
        or secure_deposit.get("source_device_sha256")
        != hashlib.sha256(b"/dev/sdc").hexdigest()
        or secure_deposit.get("autonomous_mountpoint") is not True
        or secure_deposit.get("host_read_only") is not True
        or secure_deposit.get("namespace_autonomous_mountpoint") is not True
        or secure_deposit.get("namespace_read_only") is not True
        or not _is_exact_int(secure_deposit.get("device_id"))
        or secure_deposit["device_id"] <= 0
    ):
        raise SFTPPositiveCanaryError("runtime-ready Secure Deposit proof is invalid")
    host_key = payload.get("host_key")
    if not isinstance(host_key, dict) or frozenset(host_key) != frozenset(
        {
            "algorithm",
            "fingerprint",
            "fingerprint_sha256",
            "present",
            "nonempty",
            "regular_file",
            "symlink",
        }
    ):
        raise SFTPPositiveCanaryError("runtime-ready host-key schema is not closed")
    if (
        host_key.get("algorithm") != "ssh-ed25519"
        or host_key.get("fingerprint") != host_key_fingerprint
        or host_key.get("fingerprint_sha256")
        != hashlib.sha256(host_key_fingerprint.encode("ascii")).hexdigest()
        or host_key.get("present") is not True
        or host_key.get("nonempty") is not True
        or host_key.get("regular_file") is not True
        or host_key.get("symlink") is not False
    ):
        raise SFTPPositiveCanaryError("runtime-ready host-key proof is invalid")
    sftp_started_at_raw = payload.get("sftp_started_at")
    ready_at_raw = payload.get("ready_at")
    started_at = _parse_timestamp(sftp_started_at_raw)
    ready_at = _parse_timestamp(ready_at_raw)
    if ready_at < started_at:
        raise SFTPPositiveCanaryError("runtime-ready receipt chronology is invalid")
    expected_runtime_identity = _runtime_identity_fingerprint(
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        hostname_sha256=hostname_sha256,
        sftp_container_id=sftp_container_id,
        sftp_image_id=sftp_image_id,
        sftp_port=sftp_port,
        sftp_started_at=str(sftp_started_at_raw),
    )
    if payload.get("runtime_identity_sha256") != expected_runtime_identity:
        raise SFTPPositiveCanaryError("runtime-ready identity binding is invalid")
    return ready_at, str(sftp_started_at_raw), expected_runtime_identity


def _validate_positive_evidence(
    payload: dict[str, Any],
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    hostname_sha256: str,
    access_id_sha256: str,
    credential_fingerprint_sha256: str,
    known_hosts_sha256: str,
    host_key_fingerprint: str,
    sftp_container_id: str,
    sftp_image_id: str,
    sftp_port: int,
    sftp_started_at: str,
    runtime_identity_sha256: str,
    runtime_ready_receipt_sha256: str,
    runtime_ready_at: datetime,
) -> None:
    _require_exact_keys(payload, _POSITIVE_KEYS, label="positive evidence")
    expected_scalars: dict[str, Any] = {
        "schema_version": 1,
        "kind": KIND,
        "profile": PROFILE,
        "result": "passed",
        "live_sha": live_sha,
        "release_a_sha": release_a_sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "hostname_sha256": hostname_sha256,
        "access_id_sha256": access_id_sha256,
        "credential_fingerprint_sha256": credential_fingerprint_sha256,
        "known_hosts_sha256": known_hosts_sha256,
        "host_key_fingerprint": host_key_fingerprint,
        "sftp_container_id": sftp_container_id,
        "sftp_image_id": sftp_image_id,
        "sftp_port": sftp_port,
        "sftp_started_at": sftp_started_at,
        "runtime_identity_sha256": runtime_identity_sha256,
        "runtime_ready_receipt_sha256": runtime_ready_receipt_sha256,
    }
    if any(payload.get(key) != value for key, value in expected_scalars.items()):
        raise SFTPPositiveCanaryError("positive evidence binding is invalid")
    if not _is_exact_int(payload.get("schema_version"), 1):
        raise SFTPPositiveCanaryError("positive evidence numeric type is invalid")
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        raise SFTPPositiveCanaryError("positive evidence checks are invalid")
    _require_exact_keys(checks, _POSITIVE_CHECK_KEYS, label="positive checks")
    expected_checks = {
        "password_source_private_nofollow": True,
        "known_hosts_pinned": True,
        "host_key_fingerprint_matched": True,
        "password_only_authentication": True,
        "sftp_subsystem_started": True,
        "sftp_subsystem_closed": True,
        "getcwd_completed": True,
        "stat_dot_completed": True,
        "directory_enumeration_operations": 0,
        "content_read_operations": 0,
        "mutation_operations": 0,
    }
    if checks != expected_checks:
        raise SFTPPositiveCanaryError("positive evidence checks did not pass")
    if any(
        checks[key] is not True
        for key in (
            "password_source_private_nofollow",
            "known_hosts_pinned",
            "host_key_fingerprint_matched",
            "password_only_authentication",
            "sftp_subsystem_started",
            "sftp_subsystem_closed",
            "getcwd_completed",
            "stat_dot_completed",
        )
    ) or any(
        not _is_exact_int(checks[key], 0)
        for key in (
            "directory_enumeration_operations",
            "content_read_operations",
            "mutation_operations",
        )
    ):
        raise SFTPPositiveCanaryError("positive evidence check types are invalid")
    started_at = _parse_timestamp(payload.get("auth_started_at"))
    completed_at = _parse_timestamp(payload.get("auth_completed_at"))
    if (
        completed_at < started_at
        or (completed_at - started_at).total_seconds()
        > MAX_ATTEMPT_RECOVERY_SECONDS
        or started_at < runtime_ready_at
        or (started_at - runtime_ready_at).total_seconds() > MAX_READY_TO_AUTH_SECONDS
    ):
        raise SFTPPositiveCanaryError("positive evidence chronology is invalid")


def _validate_post_revoke_evidence(
    payload: dict[str, Any],
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    hostname_sha256: str,
    access_id_sha256: str,
    credential_fingerprint_sha256: str,
    known_hosts_sha256: str,
    host_key_fingerprint: str,
    sftp_container_id: str,
    sftp_image_id: str,
    sftp_port: int,
    sftp_started_at: str,
    runtime_identity_sha256: str,
    runtime_ready_receipt_sha256: str,
    positive_evidence_sha256: str,
    positive_completed_at: datetime,
) -> tuple[datetime, datetime]:
    _require_exact_keys(payload, _POST_REVOKE_KEYS, label="post-revoke evidence")
    expected: dict[str, Any] = {
        "schema_version": 1,
        "kind": POST_REVOKE_KIND,
        "profile": POST_REVOKE_PROFILE,
        "result": "passed",
        "live_sha": live_sha,
        "release_a_sha": release_a_sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "hostname_sha256": hostname_sha256,
        "access_id_sha256": access_id_sha256,
        "credential_fingerprint_sha256": credential_fingerprint_sha256,
        "known_hosts_sha256": known_hosts_sha256,
        "host_key_fingerprint": host_key_fingerprint,
        "sftp_container_id": sftp_container_id,
        "sftp_image_id": sftp_image_id,
        "sftp_port": sftp_port,
        "sftp_started_at": sftp_started_at,
        "runtime_identity_sha256": runtime_identity_sha256,
        "runtime_ready_receipt_sha256": runtime_ready_receipt_sha256,
        "positive_evidence_sha256": positive_evidence_sha256,
        "positive_completed_at": positive_completed_at.isoformat().replace(
            "+00:00", "Z"
        ),
        "authentication_denied": True,
        "sftp_subsystem_requested_after_revocation": False,
        "directory_enumeration_operations": 0,
        "content_read_operations": 0,
        "mutation_operations": 0,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise SFTPPositiveCanaryError("post-revoke evidence binding is invalid")
    if not _is_exact_int(payload.get("schema_version"), 1):
        raise SFTPPositiveCanaryError("post-revoke evidence numeric type is invalid")
    if (
        payload.get("authentication_denied") is not True
        or payload.get("sftp_subsystem_requested_after_revocation") is not False
        or any(
            not _is_exact_int(payload.get(key), 0)
            for key in (
                "directory_enumeration_operations",
                "content_read_operations",
                "mutation_operations",
            )
        )
    ):
        raise SFTPPositiveCanaryError("post-revoke evidence proof types are invalid")
    denial_started_at = _parse_timestamp(payload.get("revocation_check_started_at"))
    denial_completed_at = _parse_timestamp(payload.get("completed_at"))
    if (
        denial_started_at < positive_completed_at
        or denial_completed_at < denial_started_at
        or (denial_completed_at - denial_started_at).total_seconds()
        > MAX_ATTEMPT_RECOVERY_SECONDS
        or (denial_started_at - positive_completed_at).total_seconds()
        > MAX_POSITIVE_TO_REVOKE_SECONDS
    ):
        raise SFTPPositiveCanaryError("post-revoke evidence chronology is invalid")
    return denial_started_at, denial_completed_at


def _ledger_binding_fingerprint(payload: dict[str, Any]) -> str:
    audits = payload["audits"]
    values: list[str] = [
        str(payload[key])
        for key in (
            "live_sha",
            "release_a_sha",
            "sftp_sha",
            "deployment_id",
            "hostname_sha256",
            "workspace_id_sha256",
            "link_id_sha256",
            "access_id_sha256",
            "credential_fingerprint_sha256",
            "sftp_container_id",
            "sftp_image_id",
            "sftp_port",
            "runtime_identity_sha256",
            "link_status",
            "auth_failed_reason",
            "remaining_active_link_count",
            "active_sftp_session_count",
            "deposit_file_delta_count",
        )
    ]
    for name in _AUDIT_NAMES:
        row = audits[name]
        values.extend(
            str(row[key])
            for key in (
                "event_type",
                "event_id_sha256",
                "event_digest_sha256",
                "count",
                "occurred_at",
            )
        )
    values.append(str(payload["collected_at"]))
    return _sha256_parts(b"agentium-release-a-sftp-ledger-v1", *values)


def _validate_ledger_receipt(
    payload: dict[str, Any],
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    hostname_sha256: str,
    access_id_sha256: str,
    credential_fingerprint_sha256: str,
    sftp_container_id: str,
    sftp_image_id: str,
    sftp_port: int,
    runtime_identity_sha256: str,
    auth_started_at: datetime,
    auth_completed_at: datetime,
    denial_started_at: datetime,
    denial_completed_at: datetime,
) -> tuple[dict[str, Any], datetime, datetime]:
    _require_exact_keys(payload, _LEDGER_KEYS, label="PostgreSQL ledger receipt")
    expected: dict[str, Any] = {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-postgres-ledger",
        "result": "passed",
        "live_sha": live_sha,
        "release_a_sha": release_a_sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "hostname_sha256": hostname_sha256,
        "access_id_sha256": access_id_sha256,
        "credential_fingerprint_sha256": credential_fingerprint_sha256,
        "sftp_container_id": sftp_container_id,
        "sftp_image_id": sftp_image_id,
        "sftp_port": sftp_port,
        "runtime_identity_sha256": runtime_identity_sha256,
        "link_status": "revoked",
        "auth_failed_reason": "inactive_or_expired",
        "remaining_active_link_count": 0,
        "active_sftp_session_count": 0,
        "deposit_file_delta_count": 0,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise SFTPPositiveCanaryError("PostgreSQL ledger binding is invalid")
    if (
        not _is_exact_int(payload.get("schema_version"), 1)
        or not _is_exact_int(payload.get("sftp_port"), sftp_port)
        or not _is_exact_int(payload.get("remaining_active_link_count"), 0)
        or not _is_exact_int(payload.get("active_sftp_session_count"), 0)
        or not _is_exact_int(payload.get("deposit_file_delta_count"), 0)
    ):
        raise SFTPPositiveCanaryError("PostgreSQL ledger numeric type is invalid")
    for key in ("workspace_id_sha256", "link_id_sha256"):
        if HEX_SHA256_RE.fullmatch(str(payload.get(key) or "")) is None:
            raise SFTPPositiveCanaryError("PostgreSQL ledger identity is invalid")
    if len(
        {
            payload["workspace_id_sha256"],
            payload["link_id_sha256"],
            payload["access_id_sha256"],
        }
    ) != 3:
        raise SFTPPositiveCanaryError("PostgreSQL ledger identities are ambiguous")
    audits = payload.get("audits")
    if not isinstance(audits, dict) or frozenset(audits) != frozenset(_AUDIT_NAMES):
        raise SFTPPositiveCanaryError("PostgreSQL audit ledger schema is not closed")
    audit_times: dict[str, datetime] = {}
    event_ids: set[str] = set()
    event_digests: set[str] = set()
    for name, event_type in _AUDIT_NAMES.items():
        row = audits.get(name)
        if not isinstance(row, dict):
            raise SFTPPositiveCanaryError("PostgreSQL audit ledger row is invalid")
        _require_exact_keys(row, _AUDIT_KEYS, label="PostgreSQL audit row")
        if row.get("event_type") != event_type or not _is_exact_int(
            row.get("count"), 1
        ):
            raise SFTPPositiveCanaryError("PostgreSQL audit event is not exact")
        event_id = str(row.get("event_id_sha256") or "")
        event_digest = str(row.get("event_digest_sha256") or "")
        if (
            HEX_SHA256_RE.fullmatch(event_id) is None
            or HEX_SHA256_RE.fullmatch(event_digest) is None
        ):
            raise SFTPPositiveCanaryError("PostgreSQL audit digest is invalid")
        event_ids.add(event_id)
        event_digests.add(event_digest)
        audit_times[name] = _parse_timestamp(row.get("occurred_at"))
    if len(event_ids) != 4 or len(event_digests) != 4:
        raise SFTPPositiveCanaryError("PostgreSQL audit events are not distinct")
    if not (
        audit_times["created"]
        <= auth_started_at
        <= audit_times["auth_success"]
        <= auth_completed_at
        <= audit_times["revoked"]
        <= denial_started_at
        <= audit_times["auth_failed_inactive"]
        <= denial_completed_at
    ):
        raise SFTPPositiveCanaryError("PostgreSQL audit chronology is invalid")
    collected_at = _parse_timestamp(payload.get("collected_at"))
    if (
        collected_at < denial_completed_at
        or (collected_at - denial_completed_at).total_seconds()
        > MAX_REVOKE_TO_LEDGER_SECONDS
    ):
        raise SFTPPositiveCanaryError("PostgreSQL ledger receipt is stale")
    expected_binding = _ledger_binding_fingerprint(payload)
    if not hmac.compare_digest(str(payload.get("binding_sha256")), expected_binding):
        raise SFTPPositiveCanaryError("PostgreSQL ledger receipt binding is invalid")
    summary = {
        "workspace_id_sha256": payload["workspace_id_sha256"],
        "link_id_sha256": payload["link_id_sha256"],
        "access_id_sha256": payload["access_id_sha256"],
        "created_event_id_sha256": audits["created"]["event_id_sha256"],
        "created_event_digest_sha256": audits["created"]["event_digest_sha256"],
        "auth_success_event_id_sha256": audits["auth_success"]["event_id_sha256"],
        "auth_success_event_digest_sha256": audits["auth_success"][
            "event_digest_sha256"
        ],
        "revoked_event_id_sha256": audits["revoked"]["event_id_sha256"],
        "revoked_event_digest_sha256": audits["revoked"][
            "event_digest_sha256"
        ],
        "auth_failed_event_id_sha256": audits["auth_failed_inactive"][
            "event_id_sha256"
        ],
        "auth_failed_event_digest_sha256": audits["auth_failed_inactive"][
            "event_digest_sha256"
        ],
        "created_count": 1,
        "auth_success_count": 1,
        "revoked_count": 1,
        "auth_failed_inactive_count": 1,
    }
    return summary, audit_times["revoked"], collected_at


def validate_final_artifact_bytes(
    raw: bytes,
    *,
    expected_live_sha: str,
    expected_release_a_sha: str,
    expected_sftp_sha: str,
    expected_deployment_id: str,
    expected_hostname_sha256: str,
    runtime_ready_receipt_raw: bytes,
    postgres_ledger_receipt_raw: bytes,
    expected_completed_at: str | None = None,
) -> dict[str, Any]:
    """Validate the canonical final artifact and return a content-free summary."""

    if not all(
        isinstance(value, bytes)
        for value in (raw, runtime_ready_receipt_raw, postgres_ledger_receipt_raw)
    ):
        raise SFTPPositiveCanaryError("final SFTP evidence inputs must be bytes")
    artifact = _strict_canonical_json_object(raw)
    runtime_ready = _strict_canonical_json_object(runtime_ready_receipt_raw)
    ledger = _strict_canonical_json_object(postgres_ledger_receipt_raw)
    _require_exact_keys(artifact, _LIFECYCLE_KEYS, label="final SFTP artifact")
    _require_exact_keys(runtime_ready, _RUNTIME_READY_KEYS, label="runtime-ready receipt")

    sftp_container_id = str(runtime_ready.get("sftp_container_id") or "")
    sftp_image_id = str(runtime_ready.get("sftp_image_id") or "")
    sftp_port = runtime_ready.get("sftp_port")
    if (
        RUNTIME_ID_RE.fullmatch(sftp_container_id) is None
        or IMAGE_ID_RE.fullmatch(sftp_image_id) is None
        or not isinstance(sftp_port, int)
        or isinstance(sftp_port, bool)
        or not 1 <= sftp_port <= 65535
    ):
        raise SFTPPositiveCanaryError("runtime-ready identity is invalid")
    _validate_bindings(
        live_sha=expected_live_sha,
        release_a_sha=expected_release_a_sha,
        sftp_sha=expected_sftp_sha,
        deployment_id=expected_deployment_id,
        sftp_image_id=sftp_image_id,
        sftp_runtime_id=sftp_container_id,
    )
    if HEX_SHA256_RE.fullmatch(expected_hostname_sha256) is None:
        raise SFTPPositiveCanaryError("expected hostname fingerprint is invalid")
    host_key_fingerprint = _normalize_fingerprint(
        str(runtime_ready.get("host_key_fingerprint") or "")
    )
    ready_at, sftp_started_at, runtime_identity_sha256 = (
        _validate_runtime_ready_receipt(
            runtime_ready,
            live_sha=expected_live_sha,
            release_a_sha=expected_release_a_sha,
            sftp_sha=expected_sftp_sha,
            deployment_id=expected_deployment_id,
            hostname_sha256=expected_hostname_sha256,
            sftp_container_id=sftp_container_id,
            sftp_image_id=sftp_image_id,
            sftp_port=sftp_port,
            host_key_fingerprint=host_key_fingerprint,
        )
    )
    runtime_ready_sha256 = hashlib.sha256(runtime_ready_receipt_raw).hexdigest()
    ledger_sha256 = hashlib.sha256(postgres_ledger_receipt_raw).hexdigest()

    expected: dict[str, Any] = {
        "schema_version": 1,
        "kind": LIFECYCLE_KIND,
        "profile": LIFECYCLE_PROFILE,
        "result": "passed",
        "live_sha": expected_live_sha,
        "release_a_sha": expected_release_a_sha,
        "sftp_sha": expected_sftp_sha,
        "deployment_id": expected_deployment_id,
        "hostname_sha256": expected_hostname_sha256,
        "host_key_fingerprint": host_key_fingerprint,
        "sftp_container_id": sftp_container_id,
        "sftp_image_id": sftp_image_id,
        "sftp_port": sftp_port,
        "sftp_started_at": sftp_started_at,
        "image_revision": expected_sftp_sha,
        "runtime_identity_sha256": runtime_identity_sha256,
        "runtime_ready_receipt_sha256": runtime_ready_sha256,
        "ledger_sha256": ledger_sha256,
        "authentication_result": "passed",
        "subsystem_result": "passed",
        "revoke_result": "passed",
        "post_revoke_authentication_result": "denied_inactive",
        "link_status": "revoked",
        "remaining_active_link_count": 0,
        "active_sftp_session_count": 0,
        "deposit_file_delta_count": 0,
        "ingress_closed": True,
        "restart_disabled": True,
        "restart_policy_disabled": True,
        "secure_deposit_mode": "ro",
        "secure_deposit_source": "/dev/sdc",
        "external_established_connection_count": 0,
        "ingress_gate": {
            "ipv4_input": True,
            "ipv4_docker_user": True,
            "ipv6_input": True,
            "ipv6_docker_user": True,
        },
    }
    if any(artifact.get(key) != value for key, value in expected.items()):
        raise SFTPPositiveCanaryError("final SFTP artifact binding is invalid")
    if (
        not _is_exact_int(artifact.get("schema_version"), 1)
        or not _is_exact_int(artifact.get("sftp_port"), sftp_port)
        or not _is_exact_int(artifact.get("remaining_active_link_count"), 0)
        or not _is_exact_int(artifact.get("active_sftp_session_count"), 0)
        or not _is_exact_int(artifact.get("deposit_file_delta_count"), 0)
        or not _is_exact_int(
            artifact.get("external_established_connection_count"), 0
        )
        or artifact.get("ingress_closed") is not True
        or artifact.get("restart_disabled") is not True
        or artifact.get("restart_policy_disabled") is not True
    ):
        raise SFTPPositiveCanaryError("final SFTP artifact numeric type is invalid")
    for key in (
        "workspace_id_sha256",
        "link_id_sha256",
        "access_id_sha256",
        "credential_fingerprint_sha256",
        "known_hosts_sha256",
        "positive_evidence_sha256",
        "post_revoke_evidence_sha256",
    ):
        if HEX_SHA256_RE.fullmatch(str(artifact.get(key) or "")) is None:
            raise SFTPPositiveCanaryError("final SFTP artifact digest is invalid")

    positive_proof = artifact.get("positive_proof")
    post_revoke_proof = artifact.get("post_revoke_proof")
    if not isinstance(positive_proof, dict) or not isinstance(post_revoke_proof, dict):
        raise SFTPPositiveCanaryError("final SFTP embedded proof is invalid")
    _validate_positive_evidence(
        positive_proof,
        live_sha=expected_live_sha,
        release_a_sha=expected_release_a_sha,
        sftp_sha=expected_sftp_sha,
        deployment_id=expected_deployment_id,
        hostname_sha256=expected_hostname_sha256,
        access_id_sha256=str(artifact["access_id_sha256"]),
        credential_fingerprint_sha256=str(
            artifact["credential_fingerprint_sha256"]
        ),
        known_hosts_sha256=str(artifact["known_hosts_sha256"]),
        host_key_fingerprint=host_key_fingerprint,
        sftp_container_id=sftp_container_id,
        sftp_image_id=sftp_image_id,
        sftp_port=sftp_port,
        sftp_started_at=sftp_started_at,
        runtime_identity_sha256=runtime_identity_sha256,
        runtime_ready_receipt_sha256=runtime_ready_sha256,
        runtime_ready_at=ready_at,
    )
    positive_evidence_sha256 = hashlib.sha256(
        _canonical_json_bytes(positive_proof)
    ).hexdigest()
    if not hmac.compare_digest(
        str(artifact["positive_evidence_sha256"]), positive_evidence_sha256
    ):
        raise SFTPPositiveCanaryError("final positive proof digest differs")
    auth_started_at = _parse_timestamp(positive_proof["auth_started_at"])
    auth_completed_at = _parse_timestamp(positive_proof["auth_completed_at"])

    denial_started_at, denial_completed_at = _validate_post_revoke_evidence(
        post_revoke_proof,
        live_sha=expected_live_sha,
        release_a_sha=expected_release_a_sha,
        sftp_sha=expected_sftp_sha,
        deployment_id=expected_deployment_id,
        hostname_sha256=expected_hostname_sha256,
        access_id_sha256=str(artifact["access_id_sha256"]),
        credential_fingerprint_sha256=str(
            artifact["credential_fingerprint_sha256"]
        ),
        known_hosts_sha256=str(artifact["known_hosts_sha256"]),
        host_key_fingerprint=host_key_fingerprint,
        sftp_container_id=sftp_container_id,
        sftp_image_id=sftp_image_id,
        sftp_port=sftp_port,
        sftp_started_at=sftp_started_at,
        runtime_identity_sha256=runtime_identity_sha256,
        runtime_ready_receipt_sha256=runtime_ready_sha256,
        positive_evidence_sha256=positive_evidence_sha256,
        positive_completed_at=auth_completed_at,
    )
    post_revoke_evidence_sha256 = hashlib.sha256(
        _canonical_json_bytes(post_revoke_proof)
    ).hexdigest()
    if not hmac.compare_digest(
        str(artifact["post_revoke_evidence_sha256"]),
        post_revoke_evidence_sha256,
    ):
        raise SFTPPositiveCanaryError("final post-revoke proof digest differs")
    if (
        artifact.get("auth_started_at") != positive_proof["auth_started_at"]
        or artifact.get("auth_completed_at") != positive_proof["auth_completed_at"]
        or artifact.get("denial_started_at")
        != post_revoke_proof["revocation_check_started_at"]
        or artifact.get("denial_completed_at") != post_revoke_proof["completed_at"]
    ):
        raise SFTPPositiveCanaryError("final embedded proof chronology differs")
    completed_at = _parse_timestamp(artifact.get("completed_at"))
    if (
        auth_started_at < ready_at
        or (auth_started_at - ready_at).total_seconds() > MAX_READY_TO_AUTH_SECONDS
        or auth_completed_at < auth_started_at
        or denial_started_at < auth_completed_at
        or (denial_started_at - auth_completed_at).total_seconds()
        > MAX_POSITIVE_TO_REVOKE_SECONDS
        or denial_completed_at < denial_started_at
    ):
        raise SFTPPositiveCanaryError("final SFTP artifact chronology is invalid")

    audit_summary, revoked_at, ledger_collected_at = _validate_ledger_receipt(
        ledger,
        live_sha=expected_live_sha,
        release_a_sha=expected_release_a_sha,
        sftp_sha=expected_sftp_sha,
        deployment_id=expected_deployment_id,
        hostname_sha256=expected_hostname_sha256,
        access_id_sha256=str(artifact["access_id_sha256"]),
        credential_fingerprint_sha256=str(
            artifact["credential_fingerprint_sha256"]
        ),
        sftp_container_id=sftp_container_id,
        sftp_image_id=sftp_image_id,
        sftp_port=sftp_port,
        runtime_identity_sha256=runtime_identity_sha256,
        auth_started_at=auth_started_at,
        auth_completed_at=auth_completed_at,
        denial_started_at=denial_started_at,
        denial_completed_at=denial_completed_at,
    )
    summary_value = artifact.get("audit_summary")
    if not isinstance(summary_value, dict):
        raise SFTPPositiveCanaryError("final SFTP audit summary is invalid")
    _require_exact_keys(summary_value, _AUDIT_SUMMARY_KEYS, label="audit summary")
    if any(
        not _is_exact_int(summary_value.get(key), 1)
        for key in (
            "created_count",
            "auth_success_count",
            "revoked_count",
            "auth_failed_inactive_count",
        )
    ):
        raise SFTPPositiveCanaryError("final SFTP audit counts are invalid")
    if summary_value != audit_summary:
        raise SFTPPositiveCanaryError("final SFTP audit summary binding is invalid")
    if (
        artifact.get("workspace_id_sha256") != ledger["workspace_id_sha256"]
        or artifact.get("link_id_sha256") != ledger["link_id_sha256"]
        or artifact.get("access_id_sha256") != ledger["access_id_sha256"]
        or artifact.get("revoked_at")
        != revoked_at.isoformat().replace("+00:00", "Z")
        or completed_at < ledger_collected_at
        or (completed_at - ledger_collected_at).total_seconds()
        > MAX_REVOKE_TO_LEDGER_SECONDS
    ):
        raise SFTPPositiveCanaryError("final SFTP ledger cross-link is invalid")
    if expected_completed_at is not None and artifact.get("completed_at") != expected_completed_at:
        raise SFTPPositiveCanaryError("final SFTP completion timestamp differs")

    return {
        "schema_version": 1,
        "kind": LIFECYCLE_KIND,
        "result": "passed",
        "live_sha": expected_live_sha,
        "release_a_sha": expected_release_a_sha,
        "sftp_sha": expected_sftp_sha,
        "deployment_id": expected_deployment_id,
        "hostname_sha256": expected_hostname_sha256,
        "runtime_ready_receipt_sha256": runtime_ready_sha256,
        "postgres_ledger_receipt_sha256": ledger_sha256,
        "credential_fingerprint_sha256": artifact[
            "credential_fingerprint_sha256"
        ],
        "completed_at": artifact["completed_at"],
    }


def _write_private_json(payload: dict[str, Any], raw_output_path: str) -> None:
    path = _canonical_absolute_path(raw_output_path)
    parent_fd, name = _open_parent_nofollow(path)
    temp_name = f".{name}.{secrets.token_hex(16)}.tmp"
    temp_fd = -1
    linked = False
    published_inode: int | None = None
    durable = False
    try:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SFTPPositiveCanaryError("evidence output already exists")

        encoded = _canonical_json_bytes(payload)
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        view = memoryview(encoded)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise SFTPPositiveCanaryError("evidence output write failed")
            view = view[written:]
        metadata = os.fstat(temp_fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_size != len(encoded)
        ):
            raise SFTPPositiveCanaryError("temporary evidence output is unsafe")
        os.fsync(temp_fd)
        published_inode = metadata.st_ino
        os.close(temp_fd)
        temp_fd = -1

        # linkat is an atomic no-replace publication primitive. Unlike replace(),
        # it cannot overwrite evidence created concurrently.
        os.link(
            temp_name,
            name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        linked = True
        os.unlink(temp_name, dir_fd=parent_fd)
        published = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            published.st_ino != published_inode
            or not stat.S_ISREG(published.st_mode)
            or stat.S_IMODE(published.st_mode) != 0o600
            or published.st_nlink != 1
            or published.st_size != len(encoded)
        ):
            raise SFTPPositiveCanaryError("published evidence output is unsafe")
        os.fsync(parent_fd)
        durable = True
    except SFTPPositiveCanaryError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise SFTPPositiveCanaryError("evidence output could not be published") from exc
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        try:
            os.unlink(temp_name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        if linked and not durable and published_inode is not None:
            try:
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if current.st_ino == published_inode:
                    os.unlink(name, dir_fd=parent_fd)
                    os.fsync(parent_fd)
            except OSError:
                pass
        os.close(parent_fd)


_ATTEMPT_INTENT_KIND = "agentium_release_a_sftp_attempt_intent"


def _private_path_exists(raw_path: str) -> bool:
    path = _canonical_absolute_path(raw_path)
    parent_fd, name = _open_parent_nofollow(path)
    try:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True
    except OSError as exc:
        raise SFTPPositiveCanaryError("attempt intent path is unsafe") from exc
    finally:
        os.close(parent_fd)


def _attempt_intent_file(*, output: str, intent_file: str | None) -> str:
    raw_path = intent_file if intent_file is not None else f"{output}.intent"
    return str(_canonical_absolute_path(raw_path))


def _load_or_create_attempt_started_at(
    *,
    intent_file: str,
    phase: str,
    profile: str,
    binding: dict[str, Any],
    floor_at: datetime,
    floor_window_seconds: int,
) -> str:
    """Durably pin an attempt start before the first network byte.

    A crash after the server commits its deterministic audit but before the
    final proof is published can then replay the network operation while
    retaining a start timestamp older than that audit. The private canonical
    intent contains hashes and release/runtime identities only, never the raw
    principal or credential.
    """

    expected = {
        "schema_version": 1,
        "kind": _ATTEMPT_INTENT_KIND,
        "phase": phase,
        "profile": profile,
        **binding,
    }
    expected_keys = frozenset({*expected, "started_at"})
    payload: dict[str, Any]
    if _private_path_exists(intent_file):
        _raw, payload = _read_private_canonical_json(intent_file)
    else:
        payload = {**expected, "started_at": _completed_at()}
        try:
            _write_private_json(payload, intent_file)
        except SFTPPositiveCanaryError:
            # A concurrent/replayed process may have won the no-replace
            # publication. Only an exact, safely readable intent is accepted.
            if not _private_path_exists(intent_file):
                raise
            _raw, payload = _read_private_canonical_json(intent_file)

    _require_exact_keys(payload, expected_keys, label="SFTP attempt intent")
    if any(payload.get(key) != value for key, value in expected.items()):
        raise SFTPPositiveCanaryError("SFTP attempt intent binding is invalid")
    started_at = _parse_timestamp(payload.get("started_at"))
    current = _parse_timestamp(_completed_at())
    if (
        started_at < floor_at
        or (started_at - floor_at).total_seconds() > floor_window_seconds
        or current < started_at
        or (current - started_at).total_seconds() > MAX_ATTEMPT_RECOVERY_SECONDS
    ):
        raise SFTPPositiveCanaryError("SFTP attempt intent is stale")
    return str(payload["started_at"])


def produce_evidence(
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    sftp_image_id: str,
    sftp_runtime_id: str,
    host: str,
    expected_hostname: str,
    port: int,
    username: str,
    password_file: str,
    known_hosts_file: str,
    runtime_ready_receipt_file: str,
    expected_host_key_fingerprint: str,
    output: str,
    intent_file: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    _validate_bindings(
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        sftp_image_id=sftp_image_id,
        sftp_runtime_id=sftp_runtime_id,
    )
    normalized_host = _normalize_loopback_endpoint(host)
    normalized_expected_hostname = _normalize_host(expected_hostname)
    principal = _validate_username(username)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise SFTPPositiveCanaryError("SFTP endpoint port is invalid")
    timeout = _validate_timeout(float(timeout))
    expected_fingerprint = _normalize_fingerprint(expected_host_key_fingerprint)

    password_bytes = _read_password(password_file)
    known_hosts = _read_known_hosts(known_hosts_file)
    credential_fingerprint = _credential_fingerprint(
        deployment_id=deployment_id,
        access_id=principal,
        password=password_bytes,
    )
    hostname_sha256 = _hostname_fingerprint(normalized_expected_hostname)
    access_id_sha256 = _sha256_domain(
        b"agentium-release-a-sftp-access-id-v1", principal.encode("utf-8")
    )
    known_hosts_sha256 = _sha256_domain(
        b"agentium-sftp-known-hosts-v1", known_hosts
    )
    runtime_ready_raw, runtime_ready = _read_private_canonical_json(
        runtime_ready_receipt_file
    )
    ready_at, sftp_started_at, runtime_identity_sha256 = (
        _validate_runtime_ready_receipt(
            runtime_ready,
            live_sha=live_sha,
            release_a_sha=release_a_sha,
            sftp_sha=sftp_sha,
            deployment_id=deployment_id,
            hostname_sha256=hostname_sha256,
            sftp_container_id=sftp_runtime_id,
            sftp_image_id=sftp_image_id,
            sftp_port=port,
            host_key_fingerprint=expected_fingerprint,
        )
    )
    runtime_ready_receipt_sha256 = hashlib.sha256(runtime_ready_raw).hexdigest()
    password = password_bytes.decode("utf-8", errors="strict")
    auth_started_at = _load_or_create_attempt_started_at(
        intent_file=_attempt_intent_file(output=output, intent_file=intent_file),
        phase="positive",
        profile=PROFILE,
        binding={
            "live_sha": live_sha,
            "release_a_sha": release_a_sha,
            "sftp_sha": sftp_sha,
            "deployment_id": deployment_id,
            "hostname_sha256": hostname_sha256,
            "access_id_sha256": access_id_sha256,
            "credential_fingerprint_sha256": credential_fingerprint,
            "known_hosts_sha256": known_hosts_sha256,
            "host_key_fingerprint": expected_fingerprint,
            "sftp_container_id": sftp_runtime_id,
            "sftp_image_id": sftp_image_id,
            "sftp_port": port,
            "sftp_started_at": sftp_started_at,
            "runtime_identity_sha256": runtime_identity_sha256,
            "runtime_ready_receipt_sha256": runtime_ready_receipt_sha256,
            "positive_evidence_sha256": None,
            "positive_completed_at": None,
        },
        floor_at=ready_at,
        floor_window_seconds=MAX_READY_TO_AUTH_SECONDS,
    )
    parsed_auth_started_at = _parse_timestamp(auth_started_at)
    if (
        parsed_auth_started_at < ready_at
        or (parsed_auth_started_at - ready_at).total_seconds()
        > MAX_READY_TO_AUTH_SECONDS
    ):
        raise SFTPPositiveCanaryError("runtime-ready receipt is stale")

    try:
        asyncio.run(
            asyncio.wait_for(
                _positive_sftp_probe(
                    host=normalized_host,
                    port=port,
                    username=principal,
                    password=password,
                    known_hosts=known_hosts,
                    expected_host_key_fingerprint=expected_fingerprint,
                    timeout=timeout,
                ),
                timeout=timeout,
            )
        )
    except SFTPPositiveCanaryError:
        raise
    except BaseException:
        raise SFTPPositiveCanaryError("positive SFTP canary timed out") from None

    auth_completed_at = _completed_at()
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "kind": KIND,
        "profile": PROFILE,
        "result": "passed",
        "live_sha": live_sha,
        "release_a_sha": release_a_sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "hostname_sha256": hostname_sha256,
        "access_id_sha256": access_id_sha256,
        "credential_fingerprint_sha256": credential_fingerprint,
        "known_hosts_sha256": known_hosts_sha256,
        "host_key_fingerprint": expected_fingerprint,
        "sftp_container_id": sftp_runtime_id,
        "sftp_image_id": sftp_image_id,
        "sftp_port": port,
        "sftp_started_at": sftp_started_at,
        "runtime_identity_sha256": runtime_identity_sha256,
        "runtime_ready_receipt_sha256": runtime_ready_receipt_sha256,
        "auth_started_at": auth_started_at,
        "auth_completed_at": auth_completed_at,
        "checks": {
            "password_source_private_nofollow": True,
            "known_hosts_pinned": True,
            "host_key_fingerprint_matched": True,
            "password_only_authentication": True,
            "sftp_subsystem_started": True,
            "sftp_subsystem_closed": True,
            "getcwd_completed": True,
            "stat_dot_completed": True,
            "directory_enumeration_operations": 0,
            "content_read_operations": 0,
            "mutation_operations": 0,
        },
    }
    _validate_positive_evidence(
        evidence,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        hostname_sha256=hostname_sha256,
        access_id_sha256=access_id_sha256,
        credential_fingerprint_sha256=credential_fingerprint,
        known_hosts_sha256=known_hosts_sha256,
        host_key_fingerprint=expected_fingerprint,
        sftp_container_id=sftp_runtime_id,
        sftp_image_id=sftp_image_id,
        sftp_port=port,
        sftp_started_at=sftp_started_at,
        runtime_identity_sha256=runtime_identity_sha256,
        runtime_ready_receipt_sha256=runtime_ready_receipt_sha256,
        runtime_ready_at=ready_at,
    )
    _write_private_json(evidence, output)
    return evidence


def verify_post_revoke(
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    sftp_image_id: str,
    sftp_runtime_id: str,
    host: str,
    expected_hostname: str,
    port: int,
    username: str,
    password_file: str,
    known_hosts_file: str,
    runtime_ready_receipt_file: str,
    expected_host_key_fingerprint: str,
    positive_evidence_file: str,
    output: str,
    intent_file: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    _validate_bindings(
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        sftp_image_id=sftp_image_id,
        sftp_runtime_id=sftp_runtime_id,
    )
    normalized_host = _normalize_loopback_endpoint(host)
    normalized_expected_hostname = _normalize_host(expected_hostname)
    principal = _validate_username(username)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise SFTPPositiveCanaryError("SFTP endpoint port is invalid")
    timeout = _validate_timeout(float(timeout))
    expected_fingerprint = _normalize_fingerprint(expected_host_key_fingerprint)

    password_bytes = _read_password(password_file)
    known_hosts = _read_known_hosts(known_hosts_file)
    credential_fingerprint = _credential_fingerprint(
        deployment_id=deployment_id,
        access_id=principal,
        password=password_bytes,
    )
    hostname_sha256 = _hostname_fingerprint(normalized_expected_hostname)
    access_id_sha256 = _sha256_domain(
        b"agentium-release-a-sftp-access-id-v1", principal.encode("utf-8")
    )
    known_hosts_sha256 = _sha256_domain(
        b"agentium-sftp-known-hosts-v1", known_hosts
    )
    runtime_ready_raw, runtime_ready = _read_private_canonical_json(
        runtime_ready_receipt_file
    )
    ready_at, sftp_started_at, runtime_identity_sha256 = (
        _validate_runtime_ready_receipt(
            runtime_ready,
            live_sha=live_sha,
            release_a_sha=release_a_sha,
            sftp_sha=sftp_sha,
            deployment_id=deployment_id,
            hostname_sha256=hostname_sha256,
            sftp_container_id=sftp_runtime_id,
            sftp_image_id=sftp_image_id,
            sftp_port=port,
            host_key_fingerprint=expected_fingerprint,
        )
    )
    runtime_ready_receipt_sha256 = hashlib.sha256(runtime_ready_raw).hexdigest()

    positive_raw, positive_evidence = _read_private_canonical_json(
        positive_evidence_file
    )
    _validate_positive_evidence(
        positive_evidence,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        hostname_sha256=hostname_sha256,
        access_id_sha256=access_id_sha256,
        credential_fingerprint_sha256=credential_fingerprint,
        known_hosts_sha256=known_hosts_sha256,
        host_key_fingerprint=expected_fingerprint,
        sftp_container_id=sftp_runtime_id,
        sftp_image_id=sftp_image_id,
        sftp_port=port,
        sftp_started_at=sftp_started_at,
        runtime_identity_sha256=runtime_identity_sha256,
        runtime_ready_receipt_sha256=runtime_ready_receipt_sha256,
        runtime_ready_at=ready_at,
    )

    positive_completed_at = _parse_timestamp(positive_evidence["auth_completed_at"])
    positive_evidence_sha256 = hashlib.sha256(positive_raw).hexdigest()
    revocation_check_started_at = _load_or_create_attempt_started_at(
        intent_file=_attempt_intent_file(output=output, intent_file=intent_file),
        phase="post_revoke",
        profile=POST_REVOKE_PROFILE,
        binding={
            "live_sha": live_sha,
            "release_a_sha": release_a_sha,
            "sftp_sha": sftp_sha,
            "deployment_id": deployment_id,
            "hostname_sha256": hostname_sha256,
            "access_id_sha256": access_id_sha256,
            "credential_fingerprint_sha256": credential_fingerprint,
            "known_hosts_sha256": known_hosts_sha256,
            "host_key_fingerprint": expected_fingerprint,
            "sftp_container_id": sftp_runtime_id,
            "sftp_image_id": sftp_image_id,
            "sftp_port": port,
            "sftp_started_at": sftp_started_at,
            "runtime_identity_sha256": runtime_identity_sha256,
            "runtime_ready_receipt_sha256": runtime_ready_receipt_sha256,
            "positive_evidence_sha256": positive_evidence_sha256,
            "positive_completed_at": positive_evidence["auth_completed_at"],
        },
        floor_at=positive_completed_at,
        floor_window_seconds=MAX_POSITIVE_TO_REVOKE_SECONDS,
    )
    revocation_started = _parse_timestamp(revocation_check_started_at)
    if (
        revocation_started < positive_completed_at
        or (revocation_started - positive_completed_at).total_seconds()
        > MAX_POSITIVE_TO_REVOKE_SECONDS
    ):
        raise SFTPPositiveCanaryError("positive evidence is stale")
    password = password_bytes.decode("utf-8", errors="strict")
    try:
        asyncio.run(
            asyncio.wait_for(
                _post_revoke_probe(
                    host=normalized_host,
                    port=port,
                    username=principal,
                    password=password,
                    known_hosts=known_hosts,
                    expected_host_key_fingerprint=expected_fingerprint,
                    timeout=timeout,
                ),
                timeout=timeout,
            )
        )
    except SFTPPositiveCanaryError:
        raise
    except BaseException:
        raise SFTPPositiveCanaryError("post-revocation SFTP canary timed out") from None

    completed_at = _completed_at()
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "kind": POST_REVOKE_KIND,
        "profile": POST_REVOKE_PROFILE,
        "result": "passed",
        "live_sha": live_sha,
        "release_a_sha": release_a_sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "hostname_sha256": hostname_sha256,
        "access_id_sha256": access_id_sha256,
        "credential_fingerprint_sha256": credential_fingerprint,
        "known_hosts_sha256": known_hosts_sha256,
        "host_key_fingerprint": expected_fingerprint,
        "sftp_container_id": sftp_runtime_id,
        "sftp_image_id": sftp_image_id,
        "sftp_port": port,
        "sftp_started_at": sftp_started_at,
        "runtime_identity_sha256": runtime_identity_sha256,
        "runtime_ready_receipt_sha256": runtime_ready_receipt_sha256,
        "positive_evidence_sha256": positive_evidence_sha256,
        "positive_completed_at": positive_evidence["auth_completed_at"],
        "revocation_check_started_at": revocation_check_started_at,
        "completed_at": completed_at,
        "authentication_denied": True,
        "sftp_subsystem_requested_after_revocation": False,
        "directory_enumeration_operations": 0,
        "content_read_operations": 0,
        "mutation_operations": 0,
    }
    _validate_post_revoke_evidence(
        evidence,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        hostname_sha256=hostname_sha256,
        access_id_sha256=access_id_sha256,
        credential_fingerprint_sha256=credential_fingerprint,
        known_hosts_sha256=known_hosts_sha256,
        host_key_fingerprint=expected_fingerprint,
        sftp_container_id=sftp_runtime_id,
        sftp_image_id=sftp_image_id,
        sftp_port=port,
        sftp_started_at=sftp_started_at,
        runtime_identity_sha256=runtime_identity_sha256,
        runtime_ready_receipt_sha256=runtime_ready_receipt_sha256,
        positive_evidence_sha256=hashlib.sha256(positive_raw).hexdigest(),
        positive_completed_at=positive_completed_at,
    )
    _write_private_json(evidence, output)
    return evidence


def finalize_evidence(
    *,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    deployment_id: str,
    sftp_image_id: str,
    sftp_runtime_id: str,
    sftp_port: int,
    expected_hostname: str,
    expected_host_key_fingerprint: str,
    runtime_ready_receipt_file: str,
    positive_evidence_file: str,
    post_revoke_evidence_file: str,
    ledger_file: str,
    output: str,
) -> dict[str, Any]:
    if _canonical_absolute_path(output).name != "sftp-positive-auth.artifact":
        raise SFTPPositiveCanaryError("final evidence filename is invalid")
    _validate_bindings(
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        sftp_image_id=sftp_image_id,
        sftp_runtime_id=sftp_runtime_id,
    )
    if (
        not isinstance(sftp_port, int)
        or isinstance(sftp_port, bool)
        or not 1 <= sftp_port <= 65535
    ):
        raise SFTPPositiveCanaryError("SFTP endpoint port is invalid")
    hostname_sha256 = _hostname_fingerprint(_normalize_host(expected_hostname))
    host_key_fingerprint = _normalize_fingerprint(expected_host_key_fingerprint)

    runtime_ready_raw, runtime_ready = _read_private_canonical_json(
        runtime_ready_receipt_file
    )
    ready_at, sftp_started_at, runtime_identity_sha256 = (
        _validate_runtime_ready_receipt(
            runtime_ready,
            live_sha=live_sha,
            release_a_sha=release_a_sha,
            sftp_sha=sftp_sha,
            deployment_id=deployment_id,
            hostname_sha256=hostname_sha256,
            sftp_container_id=sftp_runtime_id,
            sftp_image_id=sftp_image_id,
            sftp_port=sftp_port,
            host_key_fingerprint=host_key_fingerprint,
        )
    )
    runtime_ready_receipt_sha256 = hashlib.sha256(runtime_ready_raw).hexdigest()
    positive_raw, positive = _read_private_canonical_json(positive_evidence_file)
    access_id_sha256 = str(positive.get("access_id_sha256") or "")
    credential_fingerprint = str(
        positive.get("credential_fingerprint_sha256") or ""
    )
    known_hosts_sha256 = str(positive.get("known_hosts_sha256") or "")
    if any(
        HEX_SHA256_RE.fullmatch(value) is None
        for value in (access_id_sha256, credential_fingerprint, known_hosts_sha256)
    ):
        raise SFTPPositiveCanaryError("positive evidence digest is invalid")
    _validate_positive_evidence(
        positive,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        hostname_sha256=hostname_sha256,
        access_id_sha256=access_id_sha256,
        credential_fingerprint_sha256=credential_fingerprint,
        known_hosts_sha256=known_hosts_sha256,
        host_key_fingerprint=host_key_fingerprint,
        sftp_container_id=sftp_runtime_id,
        sftp_image_id=sftp_image_id,
        sftp_port=sftp_port,
        sftp_started_at=sftp_started_at,
        runtime_identity_sha256=runtime_identity_sha256,
        runtime_ready_receipt_sha256=runtime_ready_receipt_sha256,
        runtime_ready_at=ready_at,
    )
    auth_started_at = _parse_timestamp(positive["auth_started_at"])
    auth_completed_at = _parse_timestamp(positive["auth_completed_at"])
    positive_evidence_sha256 = hashlib.sha256(positive_raw).hexdigest()

    post_revoke_raw, post_revoke = _read_private_canonical_json(
        post_revoke_evidence_file
    )
    denial_started_at, denial_completed_at = _validate_post_revoke_evidence(
        post_revoke,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        hostname_sha256=hostname_sha256,
        access_id_sha256=access_id_sha256,
        credential_fingerprint_sha256=credential_fingerprint,
        known_hosts_sha256=known_hosts_sha256,
        host_key_fingerprint=host_key_fingerprint,
        sftp_container_id=sftp_runtime_id,
        sftp_image_id=sftp_image_id,
        sftp_port=sftp_port,
        sftp_started_at=sftp_started_at,
        runtime_identity_sha256=runtime_identity_sha256,
        runtime_ready_receipt_sha256=runtime_ready_receipt_sha256,
        positive_evidence_sha256=positive_evidence_sha256,
        positive_completed_at=auth_completed_at,
    )
    post_revoke_evidence_sha256 = hashlib.sha256(post_revoke_raw).hexdigest()

    ledger_raw, ledger = _read_private_canonical_json(ledger_file)
    audit_summary, revoked_at, ledger_collected_at = _validate_ledger_receipt(
        ledger,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        deployment_id=deployment_id,
        hostname_sha256=hostname_sha256,
        access_id_sha256=access_id_sha256,
        credential_fingerprint_sha256=credential_fingerprint,
        sftp_container_id=sftp_runtime_id,
        sftp_image_id=sftp_image_id,
        sftp_port=sftp_port,
        runtime_identity_sha256=runtime_identity_sha256,
        auth_started_at=auth_started_at,
        auth_completed_at=auth_completed_at,
        denial_started_at=denial_started_at,
        denial_completed_at=denial_completed_at,
    )
    completed_at = _completed_at()
    completed = _parse_timestamp(completed_at)
    if (
        completed < ledger_collected_at
        or (completed - ledger_collected_at).total_seconds()
        > MAX_REVOKE_TO_LEDGER_SECONDS
    ):
        raise SFTPPositiveCanaryError("PostgreSQL ledger receipt is stale")
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "kind": LIFECYCLE_KIND,
        "profile": LIFECYCLE_PROFILE,
        "result": "passed",
        "live_sha": live_sha,
        "release_a_sha": release_a_sha,
        "sftp_sha": sftp_sha,
        "deployment_id": deployment_id,
        "hostname_sha256": hostname_sha256,
        "workspace_id_sha256": ledger["workspace_id_sha256"],
        "link_id_sha256": ledger["link_id_sha256"],
        "access_id_sha256": access_id_sha256,
        "credential_fingerprint_sha256": credential_fingerprint,
        "known_hosts_sha256": known_hosts_sha256,
        "host_key_fingerprint": host_key_fingerprint,
        "sftp_container_id": sftp_runtime_id,
        "sftp_image_id": sftp_image_id,
        "sftp_port": sftp_port,
        "sftp_started_at": sftp_started_at,
        "image_revision": sftp_sha,
        "runtime_identity_sha256": runtime_identity_sha256,
        "runtime_ready_receipt_sha256": runtime_ready_receipt_sha256,
        "ingress_closed": True,
        "restart_disabled": True,
        "restart_policy_disabled": True,
        "secure_deposit_mode": "ro",
        "secure_deposit_source": "/dev/sdc",
        "external_established_connection_count": 0,
        "ingress_gate": runtime_ready["ingress_gate"],
        "positive_evidence_sha256": positive_evidence_sha256,
        "post_revoke_evidence_sha256": post_revoke_evidence_sha256,
        "positive_proof": positive,
        "post_revoke_proof": post_revoke,
        "ledger_sha256": hashlib.sha256(ledger_raw).hexdigest(),
        "auth_started_at": positive["auth_started_at"],
        "auth_completed_at": positive["auth_completed_at"],
        "revoked_at": revoked_at.isoformat().replace("+00:00", "Z"),
        "denial_started_at": post_revoke["revocation_check_started_at"],
        "denial_completed_at": post_revoke["completed_at"],
        "completed_at": completed_at,
        "authentication_result": "passed",
        "subsystem_result": "passed",
        "revoke_result": "passed",
        "post_revoke_authentication_result": "denied_inactive",
        "link_status": "revoked",
        "remaining_active_link_count": 0,
        "active_sftp_session_count": 0,
        "deposit_file_delta_count": 0,
        "audit_summary": audit_summary,
    }
    artifact_raw = _canonical_json_bytes(artifact)
    validate_final_artifact_bytes(
        artifact_raw,
        expected_live_sha=live_sha,
        expected_release_a_sha=release_a_sha,
        expected_sftp_sha=sftp_sha,
        expected_deployment_id=deployment_id,
        expected_hostname_sha256=hostname_sha256,
        runtime_ready_receipt_raw=runtime_ready_raw,
        postgres_ledger_receipt_raw=ledger_raw,
        expected_completed_at=completed_at,
    )
    _write_private_json(artifact, output)
    return artifact


def _bounded_timeout(raw: str) -> float:
    try:
        return _validate_timeout(float(raw))
    except (SFTPPositiveCanaryError, ValueError) as exc:
        raise argparse.ArgumentTypeError("invalid timeout") from exc


def _port(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid port") from exc
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError("invalid port")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        description="Produce private, content-free Release A positive SFTP evidence."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def add_binding_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--live-sha", required=True)
        command.add_argument("--release-a-sha", required=True)
        command.add_argument("--sftp-sha", required=True)
        command.add_argument("--deployment-id", required=True)
        command.add_argument("--sftp-image-id", required=True)
        command.add_argument("--sftp-runtime-id", required=True)
        command.add_argument("--port", required=True, type=_port)
        command.add_argument("--expected-hostname", required=True)
        command.add_argument("--expected-host-key-fingerprint", required=True)
        command.add_argument("--runtime-ready-receipt-file", required=True)
        command.add_argument("--output", required=True)

    def add_network_arguments(command: argparse.ArgumentParser) -> None:
        add_binding_arguments(command)
        command.add_argument("--host", required=True)
        command.add_argument("--username", required=True)
        command.add_argument("--password-file", required=True)
        command.add_argument("--known-hosts-file", required=True)
        command.add_argument(
            "--intent-file",
            help="Private durable attempt intent (defaults to OUTPUT.intent).",
        )
        command.add_argument(
            "--timeout-seconds",
            type=_bounded_timeout,
            default=DEFAULT_TIMEOUT_SECONDS,
        )

    probe = commands.add_parser(
        "probe", help="Authenticate and perform content-free SFTP metadata probes."
    )
    add_network_arguments(probe)
    post_revoke = commands.add_parser(
        "verify-post-revoke",
        help="Prove that the formerly valid credential is rejected.",
    )
    add_network_arguments(post_revoke)
    post_revoke.add_argument("--positive-evidence-file", required=True)
    finalize = commands.add_parser(
        "finalize", help="Bind the complete lifecycle to the protected ledger."
    )
    add_binding_arguments(finalize)
    finalize.add_argument("--positive-evidence-file", required=True)
    finalize.add_argument("--post-revoke-evidence-file", required=True)
    finalize.add_argument("--ledger-file", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        binding = {
            "live_sha": args.live_sha,
            "release_a_sha": args.release_a_sha,
            "sftp_sha": args.sftp_sha,
            "deployment_id": args.deployment_id,
            "sftp_image_id": args.sftp_image_id,
            "sftp_runtime_id": args.sftp_runtime_id,
            "port": args.port,
            "expected_hostname": args.expected_hostname,
            "expected_host_key_fingerprint": args.expected_host_key_fingerprint,
            "runtime_ready_receipt_file": args.runtime_ready_receipt_file,
            "output": args.output,
        }
        if args.command in {"probe", "verify-post-revoke"}:
            network = {
                **binding,
                "host": args.host,
                "username": args.username,
                "password_file": args.password_file,
                "known_hosts_file": args.known_hosts_file,
                "intent_file": args.intent_file,
                "timeout": args.timeout_seconds,
            }
        if args.command == "probe":
            produce_evidence(**network)
        elif args.command == "verify-post-revoke":
            verify_post_revoke(
                **network,
                positive_evidence_file=args.positive_evidence_file,
            )
        elif args.command == "finalize":
            final_binding = dict(binding)
            final_binding["sftp_port"] = final_binding.pop("port")
            finalize_evidence(
                **final_binding,
                positive_evidence_file=args.positive_evidence_file,
                post_revoke_evidence_file=args.post_revoke_evidence_file,
                ledger_file=args.ledger_file,
            )
        else:  # pragma: no cover - argparse enforces a closed command set
            raise SFTPPositiveCanaryError("invalid command")
    except BaseException:  # noqa: BLE001 - no peer/credential diagnostics may escape
        print("Release A positive SFTP canary failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
