#!/usr/bin/env python3
"""Bind Release A JSON claims to private, immutable evidence bytes.

Release A has two evidence moments.  ``verify-preconditions`` runs before the
first mutation and binds the backup-restore and capacity proofs.  ``verify-final``
runs while the public maintenance gate is still closed and binds every artifact
referenced by the v4 Release A attestation, plus the preconditions receipt.

The emitted receipts contain only release identity and hashes.  Evidence paths,
filenames and bodies never leave the private evidence directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# ``python -I /absolute/path/to/this-script`` keeps the script directory on the
# trusted import path, but importing this file in a test does not.  Pin imports
# to this checked-out sibling directory in both cases.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import agentium_release_a_attestation as final_gate  # noqa: E402
import agentium_release_a_preconditions as pre_gate  # noqa: E402
import agentium_release_a_sftp_positive_canary as sftp_gate  # noqa: E402

SCHEMA_VERSION = 1
PRECONDITIONS_RECEIPT_KIND = "agentium-release-a-preconditions-evidence-receipt"
FINAL_RECEIPT_KIND = "agentium-release-a-final-evidence-receipt"
FINAL_BINDING_KIND = "agentium-release-a-final-evidence-bindings"
EXTERNAL_PROVENANCE_KIND = "agentium-release-a-external-proof-provenance"
ENVIRONMENT = "production"

MAX_JSON_BYTES = 1024 * 1024
MAX_EVIDENCE_FILES = 256
MAX_EVIDENCE_DIRECTORIES = 64
MAX_EVIDENCE_DEPTH = 8
MAX_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE_TOTAL_BYTES = 512 * 1024 * 1024
MAX_RECEIPT_BYTES = 8192
MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_PRECONDITIONS_RECEIPT_AGE = timedelta(hours=24)

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\."
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)
_ISSUER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,95}$")

_PRECONDITIONS_RECEIPT_KEYS = {
    "schema_version",
    "kind",
    "result",
    "environment",
    "deployment_id",
    "live_sha",
    "release_a_sha",
    "hostname_sha256",
    "preconditions_sha256",
    "evidence_file_count",
    "evidence_digest_count",
    "evidence_reference_count",
    "evidence_set_sha256",
    "restore_proof_set_sha256",
    "capacity_proof_set_sha256",
    "verified_at",
}
_FINAL_RECEIPT_KEYS = {
    "schema_version",
    "kind",
    "result",
    "environment",
    "deployment_id",
    "live_sha",
    "release_a_sha",
    "sftp_release_sha",
    "hostname_sha256",
    "attestation_sha256",
    "preconditions_receipt_sha256",
    "preconditions_sha256",
    "evidence_file_count",
    "evidence_digest_count",
    "evidence_reference_count",
    "evidence_set_sha256",
    "binding_manifest_sha256",
    "authority_keyring_sha256",
    "canonical_reference_count",
    "external_reference_count",
    "external_provenance_set_sha256",
    "verified_at",
}

# These are the only final claims allowed to come from outside the Release A
# journal.  Each one requires an exact-name artifact plus a schema-closed
# provenance receipt issued by the expected authority class.  Everything else
# is byte-bound to an executor-generated journal artifact below.
_EXTERNAL_BINDINGS: dict[str, tuple[str, str]] = {
    "evidence.off_vm_backups[sda1].restore_check.proof_sha256": (
        "backup-sda1-restore",
        "backup_provider",
    ),
    "evidence.off_vm_backups[sdb].restore_check.proof_sha256": (
        "backup-sdb-restore",
        "backup_provider",
    ),
    "evidence.off_vm_backups[sdc].restore_check.proof_sha256": (
        "backup-sdc-restore",
        "backup_provider",
    ),
    "evidence.canaries.showcase.proof_sha256": ("canary-showcase", "protected_runner"),
    "evidence.canaries.andritz.proof_sha256": ("canary-andritz", "protected_runner"),
    "evidence.canaries.sentinel.proof_sha256": ("canary-sentinel", "protected_runner"),
    "evidence.canaries.octocity.proof_sha256": ("canary-octocity", "protected_runner"),
    "evidence.canaries.livekit.proof_sha256": ("canary-livekit", "protected_runner"),
    "evidence.runtime.maintenance_gate.proof_sha256": (
        "runtime-maintenance-gate",
        "release_a_host_collector",
    ),
    "evidence.runtime.backend.proof_sha256": (
        "runtime-backend-listener",
        "release_a_host_collector",
    ),
    "evidence.runtime.restart_contract.proof_sha256": (
        "runtime-restart-contract",
        "release_a_host_collector",
    ),
    "evidence.tenant_audit.report_sha256": (
        "tenant-audit",
        "release_a_host_collector",
    ),
    "evidence.sftp.proof_sha256": ("sftp-positive-auth", "protected_runner"),
    "evidence.principals.browser_canary.permission_probe_sha256": (
        "browser-permission-probe",
        "protected_runner",
    ),
}

_CANONICAL_BINDINGS: dict[str, tuple[str, str]] = {
    "evidence.data_integrity.postgresql.before_sha256": (
        "postgres-inventory-before.json",
        "postgres_inventory",
    ),
    "evidence.data_integrity.postgresql.after_sha256": (
        "postgres-inventory-after.json",
        "postgres_inventory",
    ),
    "evidence.data_integrity.postgresql.comparison_sha256": (
        "postgres-inventory-comparison.json",
        "postgres_comparison",
    ),
    **{
        f"evidence.data_integrity.{store}.{field}_sha256": (filename, kind)
        for store in (
            "qdrant",
            "minio_object_store",
            "faiss",
            "secure_deposit",
            "rabbitmq",
        )
        for field, filename, kind in (
            ("before", "storage-before.json", "storage_snapshot"),
            ("after", "storage-after.json", "storage_snapshot"),
            ("comparison", "storage-comparison.json", "storage_comparison"),
        )
    },
    "evidence.minio.proof_sha256": ("minio-bootstrap-proof.json", "minio_proof"),
    "evidence.qdrant.inventory_sha256": ("storage-after.json", "storage_snapshot"),
    "evidence.qdrant.proof_sha256": ("qdrant-bootstrap-proof.json", "qdrant_proof"),
    "evidence.sftp.runtime_ready_receipt_sha256": (
        "sftp-validation-runtime-ready.json",
        "sftp_runtime_ready",
    ),
    "evidence.sftp.postgres_ledger_receipt_sha256": (
        "sftp-postgres-ledger-receipt.json",
        "sftp_postgres_ledger",
    ),
}

_FINAL_REFERENCE_COUNT = 37


class EvidenceBundleError(RuntimeError):
    """The evidence bundle is incomplete, mutable, over-broad or misbound."""


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceBundleError("receipt value is not canonical JSON") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise EvidenceBundleError(f"{path} is not a lowercase SHA-256 digest")
    return value


def _git_sha(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or _GIT_SHA_RE.fullmatch(value) is None:
        raise EvidenceBundleError(f"{path} is not a lowercase Git SHA")
    return value


def _deployment_id(value: Any) -> str:
    if not isinstance(value, str) or _DEPLOYMENT_ID_RE.fullmatch(value) is None:
        raise EvidenceBundleError("deployment-id is invalid")
    return value


def _hostname(value: Any) -> str:
    if not isinstance(value, str) or _HOSTNAME_RE.fullmatch(value) is None:
        raise EvidenceBundleError("hostname is invalid")
    return value


def _positive_int(value: Any, *, path: str, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 < value <= maximum
    ):
        raise EvidenceBundleError(f"{path} is outside its bound")
    return value


def _timestamp(value: Any, *, path: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceBundleError(f"{path} is not an UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise EvidenceBundleError(f"{path} is not an UTC timestamp") from exc
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return (
        value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceBundleError("JSON input contains a duplicate field")
        result[key] = value
    return result


def _identity(row: os.stat_result) -> tuple[int, ...]:
    return (
        row.st_dev,
        row.st_ino,
        row.st_mode,
        row.st_uid,
        row.st_gid,
        row.st_nlink,
        row.st_size,
        row.st_mtime_ns,
        row.st_ctime_ns,
    )


def _read_bounded(descriptor: int, *, expected_size: int, maximum: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while size <= maximum:
        chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    body = b"".join(chunks)
    if size > maximum:
        raise EvidenceBundleError("file exceeds its byte bound")
    if len(body) != expected_size:
        raise EvidenceBundleError("file was read incompletely or changed size")
    return body


def load_private_json(path: Path) -> tuple[Any, str]:
    """Read strict private JSON through one stable, no-follow descriptor."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise EvidenceBundleError(
            "private JSON input is unavailable or unsafe"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise EvidenceBundleError(
                "private JSON input is not a single-link regular file"
            )
        if before.st_uid != os.geteuid():
            raise EvidenceBundleError("private JSON input owner is unexpected")
        if stat.S_IMODE(before.st_mode) not in {0o400, 0o600}:
            raise EvidenceBundleError("private JSON input mode must be 0400 or 0600")
        if before.st_size <= 0 or before.st_size > MAX_JSON_BYTES:
            raise EvidenceBundleError("private JSON input exceeds its byte bound")
        body = _read_bounded(
            descriptor, expected_size=before.st_size, maximum=MAX_JSON_BYTES
        )
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if _identity(before) != _identity(after):
        raise EvidenceBundleError("private JSON input changed while being read")
    try:
        payload = json.loads(
            body.decode("utf-8"), object_pairs_hook=_no_duplicate_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceBundleError(
            "private JSON input is not strict UTF-8 JSON"
        ) from exc
    return payload, _sha256(body)


def _read_private_file(path: Path, *, maximum: int = MAX_EVIDENCE_FILE_BYTES) -> bytes:
    """Read one owner-private single-link file without a path substitution window."""

    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        linked_before = os.lstat(path)
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise EvidenceBundleError(
            f"private evidence is unavailable: {path.name}"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if _identity(linked_before) != _identity(opened):
            raise EvidenceBundleError(
                f"private evidence changed while opening: {path.name}"
            )
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            raise EvidenceBundleError(
                f"private evidence is not single-link: {path.name}"
            )
        if opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) not in {
            0o400,
            0o600,
        }:
            raise EvidenceBundleError(
                f"private evidence owner/mode differs: {path.name}"
            )
        if opened.st_size <= 0 or opened.st_size > maximum:
            raise EvidenceBundleError(
                f"private evidence exceeds its bound: {path.name}"
            )
        body = _read_bounded(descriptor, expected_size=opened.st_size, maximum=maximum)
        after = os.fstat(descriptor)
        linked_after = os.lstat(path)
        if not (_identity(opened) == _identity(after) == _identity(linked_after)):
            raise EvidenceBundleError(
                f"private evidence changed while read: {path.name}"
            )
        return body
    finally:
        os.close(descriptor)


def _strict_json_bytes(body: bytes, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(
            body.decode("utf-8"), object_pairs_hook=_no_duplicate_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceBundleError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise EvidenceBundleError(f"{label} is not a JSON object")
    return payload


def _validate_real_private_directory(path: Path, *, label: str) -> os.stat_result:
    try:
        linked = os.lstat(path)
    except OSError as exc:
        raise EvidenceBundleError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(linked.st_mode) or not stat.S_ISDIR(linked.st_mode):
        raise EvidenceBundleError(f"{label} must be a real directory")
    if linked.st_uid != os.geteuid() or stat.S_IMODE(linked.st_mode) != 0o700:
        raise EvidenceBundleError(f"{label} must be owner-owned mode 0700")
    return linked


def _proof_set_sha256(digests: Sequence[str]) -> str:
    return _sha256(_canonical_json(sorted(set(digests))))


def _precondition_digests(payload: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    try:
        restore = [
            _digest(row["restore_check"]["proof_sha256"], path="restore proof")
            for row in payload["off_vm_backups"]
        ]
        capacity = [
            _digest(row["proof_sha256"], path="capacity proof")
            for row in payload["capacity"]
        ]
    except (KeyError, TypeError) as exc:
        raise EvidenceBundleError("preconditions proof fields are incomplete") from exc
    return restore, capacity


def _attestation_digests(payload: Mapping[str, Any]) -> list[str]:
    """Extract only digests that name real artifacts, never identity hashes."""

    try:
        evidence = payload["evidence"]
        values: list[Any] = [
            row["restore_check"]["proof_sha256"] for row in evidence["off_vm_backups"]
        ]
        values.extend(row["proof_sha256"] for row in evidence["canaries"].values())
        for row in evidence["data_integrity"].values():
            values.extend(
                (row["before_sha256"], row["after_sha256"], row["comparison_sha256"])
            )
        values.extend(
            (
                evidence["minio"]["proof_sha256"],
                evidence["qdrant"]["inventory_sha256"],
                evidence["qdrant"]["proof_sha256"],
                evidence["runtime"]["maintenance_gate"]["proof_sha256"],
                evidence["runtime"]["backend"]["proof_sha256"],
                evidence["runtime"]["restart_contract"]["proof_sha256"],
                evidence["tenant_audit"]["report_sha256"],
                evidence["sftp"]["runtime_ready_receipt_sha256"],
                evidence["sftp"]["postgres_ledger_receipt_sha256"],
                evidence["sftp"]["proof_sha256"],
                evidence["principals"]["browser_canary"]["permission_probe_sha256"],
            )
        )
    except (KeyError, TypeError) as exc:
        raise EvidenceBundleError(
            "attestation artifact digest fields are incomplete"
        ) from exc
    return [_digest(value, path="attestation artifact digest") for value in values]


def _attestation_claims(payload: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Return the exact 37 semantic proof references and their event time."""

    try:
        evidence = payload["evidence"]
        claims: dict[str, dict[str, str]] = {}
        backup_tokens = {"/dev/sda1": "sda1", "/dev/sdb": "sdb", "/dev/sdc": "sdc"}
        for row in evidence["off_vm_backups"]:
            token = backup_tokens[row["source_device"]]
            claims[f"evidence.off_vm_backups[{token}].restore_check.proof_sha256"] = {
                "digest": _digest(
                    row["restore_check"]["proof_sha256"], path="restore proof"
                ),
                "event_at": row["restore_check"]["completed_at"],
            }
        for name, row in evidence["canaries"].items():
            claims[f"evidence.canaries.{name}.proof_sha256"] = {
                "digest": _digest(row["proof_sha256"], path=f"{name} canary proof"),
                "event_at": row["completed_at"],
            }
        for name, row in evidence["data_integrity"].items():
            claims[f"evidence.data_integrity.{name}.before_sha256"] = {
                "digest": _digest(row["before_sha256"], path=f"{name} before proof"),
                "event_at": row["before_at"],
            }
            claims[f"evidence.data_integrity.{name}.after_sha256"] = {
                "digest": _digest(row["after_sha256"], path=f"{name} after proof"),
                "event_at": row["after_at"],
            }
            claims[f"evidence.data_integrity.{name}.comparison_sha256"] = {
                "digest": _digest(
                    row["comparison_sha256"], path=f"{name} comparison proof"
                ),
                "event_at": row["completed_at"],
            }
        direct = {
            "evidence.minio.proof_sha256": (
                evidence["minio"]["proof_sha256"],
                evidence["minio"]["completed_at"],
            ),
            "evidence.qdrant.inventory_sha256": (
                evidence["qdrant"]["inventory_sha256"],
                evidence["qdrant"]["completed_at"],
            ),
            "evidence.qdrant.proof_sha256": (
                evidence["qdrant"]["proof_sha256"],
                evidence["qdrant"]["completed_at"],
            ),
            "evidence.runtime.maintenance_gate.proof_sha256": (
                evidence["runtime"]["maintenance_gate"]["proof_sha256"],
                evidence["runtime"]["maintenance_gate"]["completed_at"],
            ),
            "evidence.runtime.backend.proof_sha256": (
                evidence["runtime"]["backend"]["proof_sha256"],
                evidence["runtime"]["backend"]["completed_at"],
            ),
            "evidence.runtime.restart_contract.proof_sha256": (
                evidence["runtime"]["restart_contract"]["proof_sha256"],
                evidence["runtime"]["restart_contract"]["completed_at"],
            ),
            "evidence.tenant_audit.report_sha256": (
                evidence["tenant_audit"]["report_sha256"],
                evidence["tenant_audit"]["completed_at"],
            ),
            "evidence.sftp.proof_sha256": (
                evidence["sftp"]["proof_sha256"],
                evidence["sftp"]["completed_at"],
            ),
            "evidence.sftp.runtime_ready_receipt_sha256": (
                evidence["sftp"]["runtime_ready_receipt_sha256"],
                evidence["sftp"]["runtime_ready_at"],
            ),
            "evidence.sftp.postgres_ledger_receipt_sha256": (
                evidence["sftp"]["postgres_ledger_receipt_sha256"],
                evidence["sftp"]["postgres_ledger_completed_at"],
            ),
            "evidence.principals.browser_canary.permission_probe_sha256": (
                evidence["principals"]["browser_canary"]["permission_probe_sha256"],
                evidence["principals"]["browser_canary"]["completed_at"],
            ),
        }
        for claim, (digest, event_at) in direct.items():
            claims[claim] = {
                "digest": _digest(digest, path=f"{claim} proof"),
                "event_at": event_at,
            }
    except (KeyError, TypeError) as exc:
        raise EvidenceBundleError("attestation proof mapping is incomplete") from exc
    expected = set(_CANONICAL_BINDINGS) | set(_EXTERNAL_BINDINGS)
    if set(claims) != expected or len(claims) != _FINAL_REFERENCE_COUNT:
        raise EvidenceBundleError("attestation proof mapping is not the closed v1 set")
    for claim, row in claims.items():
        _timestamp(row["event_at"], path=f"{claim} event_at")
    return claims


def _validate_directory(row: os.stat_result, *, root_device: int) -> None:
    if not stat.S_ISDIR(row.st_mode):
        raise EvidenceBundleError(
            "evidence directory contains a non-directory traversal"
        )
    if row.st_uid != os.geteuid() or stat.S_IMODE(row.st_mode) != 0o700:
        raise EvidenceBundleError("evidence directories must be owner-owned mode 0700")
    if row.st_dev != root_device:
        raise EvidenceBundleError("evidence directory must not cross a mount boundary")


def verify_evidence_root(
    root: Path, expected_digests: Sequence[str]
) -> dict[str, int | str]:
    """Hash a closed evidence tree without following links or trusting path stats."""

    expected = {
        _digest(value, path="expected evidence digest") for value in expected_digests
    }
    if not expected:
        raise EvidenceBundleError("evidence digest set is empty")
    try:
        path_before = os.lstat(root)
    except OSError as exc:
        raise EvidenceBundleError("evidence root is unavailable") from exc
    if stat.S_ISLNK(path_before.st_mode) or not stat.S_ISDIR(path_before.st_mode):
        raise EvidenceBundleError("evidence root must be a real directory")

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        root_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise EvidenceBundleError("evidence root cannot be opened safely") from exc

    directory_handles: list[tuple[int, tuple[int, ...]]] = []
    file_handles: list[tuple[int, tuple[int, ...]]] = []
    found: dict[str, int] = {}
    file_count = 0
    directory_count = 0
    total_bytes = 0

    def walk(descriptor: int, depth: int, root_device: int) -> None:
        nonlocal file_count, directory_count, total_bytes
        if depth > MAX_EVIDENCE_DEPTH:
            raise EvidenceBundleError("evidence directory depth exceeds its bound")
        before = os.fstat(descriptor)
        _validate_directory(before, root_device=root_device)
        directory_handles.append((descriptor, _identity(before)))
        directory_count += 1
        if directory_count > MAX_EVIDENCE_DIRECTORIES:
            raise EvidenceBundleError("evidence directory count exceeds its bound")
        try:
            with os.scandir(descriptor) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            raise EvidenceBundleError(
                "evidence directory cannot be scanned safely"
            ) from exc
        for entry in entries:
            try:
                kind = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise EvidenceBundleError(
                    "evidence entry changed during traversal"
                ) from exc
            if stat.S_ISLNK(kind):
                raise EvidenceBundleError("evidence tree must not contain symlinks")
            if stat.S_ISDIR(kind):
                try:
                    child = os.open(entry.name, directory_flags, dir_fd=descriptor)
                except OSError as exc:
                    raise EvidenceBundleError(
                        "evidence subdirectory is unsafe"
                    ) from exc
                try:
                    walk(child, depth + 1, root_device)
                except BaseException:
                    if all(item[0] != child for item in directory_handles):
                        os.close(child)
                    raise
                continue
            try:
                child = os.open(entry.name, file_flags, dir_fd=descriptor)
            except OSError as exc:
                raise EvidenceBundleError(
                    "evidence file cannot be opened safely"
                ) from exc
            keep_open = False
            try:
                file_before = os.fstat(child)
                if not stat.S_ISREG(file_before.st_mode) or file_before.st_nlink != 1:
                    raise EvidenceBundleError(
                        "evidence files must be single-link regular files"
                    )
                if file_before.st_uid != os.geteuid():
                    raise EvidenceBundleError("evidence file owner is unexpected")
                if stat.S_IMODE(file_before.st_mode) not in {0o400, 0o600}:
                    raise EvidenceBundleError("evidence file mode must be 0400 or 0600")
                if file_before.st_dev != root_device:
                    raise EvidenceBundleError(
                        "evidence file must not cross a mount boundary"
                    )
                if file_before.st_size > MAX_EVIDENCE_FILE_BYTES:
                    raise EvidenceBundleError("evidence file exceeds its byte bound")
                file_count += 1
                total_bytes += file_before.st_size
                if file_count > MAX_EVIDENCE_FILES:
                    raise EvidenceBundleError("evidence file count exceeds its bound")
                if total_bytes > MAX_EVIDENCE_TOTAL_BYTES:
                    raise EvidenceBundleError("evidence total bytes exceed their bound")
                body = _read_bounded(
                    child,
                    expected_size=file_before.st_size,
                    maximum=MAX_EVIDENCE_FILE_BYTES,
                )
                file_after = os.fstat(child)
                if _identity(file_before) != _identity(file_after):
                    raise EvidenceBundleError("evidence file changed while being read")
                digest = _sha256(body)
                if digest not in expected:
                    raise EvidenceBundleError(
                        "evidence tree contains an unexpected file"
                    )
                found[digest] = found.get(digest, 0) + 1
                file_handles.append((child, _identity(file_after)))
                keep_open = True
            finally:
                if not keep_open:
                    os.close(child)

    try:
        root_open = os.fstat(root_fd)
        if _identity(root_open) != _identity(path_before):
            raise EvidenceBundleError("evidence root changed before traversal")
        _validate_directory(root_open, root_device=root_open.st_dev)
        walk(root_fd, 0, root_open.st_dev)
        missing = expected - set(found)
        if missing:
            raise EvidenceBundleError(
                "one or more required evidence digests are absent"
            )
        for descriptor, identity in file_handles:
            if _identity(os.fstat(descriptor)) != identity:
                raise EvidenceBundleError(
                    "evidence file changed during bundle verification"
                )
        for descriptor, identity in directory_handles:
            if _identity(os.fstat(descriptor)) != identity:
                raise EvidenceBundleError(
                    "evidence directory changed during bundle verification"
                )
        path_after = os.lstat(root)
        if _identity(path_after) != _identity(path_before):
            raise EvidenceBundleError("evidence root path changed during verification")
    finally:
        for descriptor, _ in reversed(file_handles):
            os.close(descriptor)
        for descriptor, _ in reversed(directory_handles):
            os.close(descriptor)
        if all(item[0] != root_fd for item in directory_handles):
            os.close(root_fd)

    return {
        "file_count": file_count,
        "digest_count": len(expected),
        "reference_count": len(expected_digests),
        "set_sha256": _proof_set_sha256(list(expected)),
    }


def _validate_canonical_payload(
    body: bytes,
    *,
    kind: str,
    release_a_sha: str,
    deployment_id: str,
) -> None:
    payload = _strict_json_bytes(body, label=f"canonical {kind} artifact")
    if kind == "postgres_inventory":
        if (
            payload.get("schema_version") != 2
            or payload.get("kind") != "postgresql_row_inventory"
            or payload.get("profile") != "agentium-postgresql-row-inventory-v2"
            or payload.get("candidate_sha") != release_a_sha
            or payload.get("deployment_id") != deployment_id
            or payload.get("content_serialized") is not False
        ):
            raise EvidenceBundleError("canonical PostgreSQL inventory identity differs")
    elif kind == "postgres_comparison":
        expected = {
            "schema_version",
            "kind",
            "profile",
            "result",
            "deployment_id",
            "release_a_sha",
            "before_sha256",
            "after_sha256",
            "verified_at",
        }
        if (
            set(payload) != expected
            or payload.get("schema_version") != 1
            or payload.get("kind") != "agentium-release-a-postgres-comparison"
            or payload.get("profile") != "business_inventory_exact_v1"
            or payload.get("result") != "passed"
            or payload.get("deployment_id") != deployment_id
            or payload.get("release_a_sha") != release_a_sha
        ):
            raise EvidenceBundleError(
                "canonical PostgreSQL comparison identity differs"
            )
        for key in ("before_sha256", "after_sha256"):
            _digest(payload.get(key), path=f"PostgreSQL comparison {key}")
        _timestamp(payload.get("verified_at"), path="PostgreSQL comparison verified_at")
    elif kind == "storage_snapshot":
        if (
            payload.get("schema_version") != 1
            or payload.get("profile") != "agentium-storage-attestation-v3"
        ):
            raise EvidenceBundleError("canonical storage snapshot identity differs")
        _timestamp(payload.get("captured_at"), path="storage snapshot captured_at")
    elif kind == "storage_comparison":
        if (
            payload.get("schema_version") != 1
            or payload.get("profile")
            != "agentium-storage-release-a-versioning-comparison-v1"
            or payload.get("result") != "passed"
            or payload.get("failed_checks") != []
        ):
            raise EvidenceBundleError("canonical storage comparison did not pass")
    elif kind == "minio_proof":
        if (
            payload.get("schema_version") != 1
            or payload.get("kind") != "agentium-release-a-minio-bootstrap"
            or payload.get("result") != "passed"
            or payload.get("versioning") != "Enabled"
            or payload.get("delete_denied") is not True
            or payload.get("config_denied") is not True
        ):
            raise EvidenceBundleError("canonical MinIO proof did not pass")
    elif kind == "qdrant_proof":
        if (
            payload.get("schema_version") != 1
            or payload.get("kind") != "agentium-release-a-qdrant-bootstrap"
            or payload.get("result") != "passed"
            or payload.get("read_only_write_denied") is not True
            or payload.get("probe_absent_after") is not True
        ):
            raise EvidenceBundleError("canonical Qdrant proof did not pass")
    elif kind == "sftp_runtime_ready":
        if (
            payload.get("schema_version") != 1
            or payload.get("kind") != "agentium-release-a-sftp-runtime-ready"
            or payload.get("result") != "passed"
            or payload.get("release_a_sha") != release_a_sha
            or payload.get("deployment_id") != deployment_id
            or payload.get("credentials_used") is not False
            or payload.get("authentication_attempted") is not False
            or payload.get("sftp_subsystem_requested") is not False
            or payload.get("content_serialized") is not False
            or payload.get("raw_network_data_serialized") is not False
            or payload.get("raw_identification_serialized") is not False
        ):
            raise EvidenceBundleError("canonical SFTP runtime-ready proof did not pass")
        _timestamp(payload.get("ready_at"), path="SFTP runtime-ready ready_at")
    elif kind == "sftp_postgres_ledger":
        if (
            payload.get("schema_version") != 1
            or payload.get("kind") != "agentium-release-a-sftp-postgres-ledger"
            or payload.get("result") != "passed"
            or payload.get("release_a_sha") != release_a_sha
            or payload.get("deployment_id") != deployment_id
            or payload.get("link_status") != "revoked"
            or payload.get("auth_failed_reason") != "inactive_or_expired"
            or payload.get("remaining_active_link_count") != 0
            or payload.get("active_sftp_session_count") != 0
            or payload.get("deposit_file_delta_count") != 0
        ):
            raise EvidenceBundleError("canonical SFTP PostgreSQL ledger did not pass")
        _timestamp(payload.get("collected_at"), path="SFTP ledger collected_at")
    else:
        raise EvidenceBundleError(f"unknown canonical evidence kind: {kind}")


def _canonical_entries(
    *,
    journal_root: Path,
    claims: Mapping[str, Mapping[str, str]],
    release_a_sha: str,
    deployment_id: str,
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    root_row = _validate_real_private_directory(journal_root, label="Release A journal")
    entries: list[dict[str, Any]] = []
    cache: dict[str, bytes] = {}
    for claim in sorted(_CANONICAL_BINDINGS):
        relative_path, kind = _CANONICAL_BINDINGS[claim]
        if relative_path not in cache:
            artifact = journal_root / relative_path
            body = _read_private_file(artifact)
            linked = os.lstat(artifact)
            if linked.st_dev != root_row.st_dev:
                raise EvidenceBundleError("canonical evidence crossed a mount boundary")
            _validate_canonical_payload(
                body,
                kind=kind,
                release_a_sha=release_a_sha,
                deployment_id=deployment_id,
            )
            cache[relative_path] = body
        digest = _sha256(cache[relative_path])
        if digest != claims[claim]["digest"]:
            raise EvidenceBundleError(
                f"attestation digest is not bound to canonical journal artifact: {claim}"
            )
        entries.append(
            {
                "claim": claim,
                "source": "release_a_journal",
                "artifact": relative_path,
                "artifact_sha256": digest,
                "event_at": claims[claim]["event_at"],
                "artifact_kind": kind,
            }
        )
    return entries, cache


def _external_expected_names() -> set[str]:
    return {
        name
        for token, _ in _EXTERNAL_BINDINGS.values()
        for name in (
            f"{token}.artifact",
            f"{token}.provenance.json",
            f"{token}.signature",
        )
    }


def _authority_keyring(
    payload: Any, *, require_complete: bool = True
) -> dict[tuple[str, str], bytes]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "kind",
        "authorities",
    }:
        raise EvidenceBundleError("evidence authority keyring schema differs")
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "agentium-release-a-evidence-authority-keyring"
    ):
        raise EvidenceBundleError("evidence authority keyring identity differs")
    rows = payload.get("authorities")
    minimum = 3 if require_complete else 0
    if not isinstance(rows, list) or not minimum <= len(rows) <= 32:
        raise EvidenceBundleError("evidence authority keyring cardinality differs")
    result: dict[tuple[str, str], bytes] = {}
    digest_producers: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != {
            "issuer",
            "producer",
            "signature_algorithm",
            "public_key_pem",
            "public_key_sha256",
        }:
            raise EvidenceBundleError("evidence authority row schema differs")
        issuer = row.get("issuer")
        producer = row.get("producer")
        if row.get("signature_algorithm") != "rsa-pkcs1v15-sha256":
            raise EvidenceBundleError("evidence authority signature algorithm differs")
        pem = row.get("public_key_pem")
        if not isinstance(issuer, str) or _ISSUER_RE.fullmatch(issuer) is None:
            raise EvidenceBundleError("evidence authority issuer is invalid")
        if producer not in {value[1] for value in _EXTERNAL_BINDINGS.values()}:
            raise EvidenceBundleError("evidence authority producer is not allowed")
        if (
            not isinstance(pem, str)
            or not pem.startswith("-----BEGIN PUBLIC KEY-----\n")
            or not pem.endswith("-----END PUBLIC KEY-----\n")
            or len(pem.encode("ascii", errors="ignore")) > 16 * 1024
        ):
            raise EvidenceBundleError("evidence authority public key is invalid")
        try:
            encoded = pem.encode("ascii")
        except UnicodeEncodeError as exc:
            raise EvidenceBundleError(
                "evidence authority public key is not ASCII"
            ) from exc
        key_digest = _digest(
            row.get("public_key_sha256"), path="evidence authority public key digest"
        )
        if key_digest != _sha256(encoded):
            raise EvidenceBundleError("evidence authority public key digest differs")
        previous_producer = digest_producers.get(key_digest)
        if previous_producer is not None and previous_producer != producer:
            raise EvidenceBundleError(
                "one authority key is reused across producer classes"
            )
        digest_producers[key_digest] = str(producer)
        with tempfile.TemporaryFile() as key_handle:
            key_handle.write(encoded)
            key_handle.flush()
            key_handle.seek(0)
            try:
                inspected = subprocess.run(
                    [
                        "openssl",
                        "rsa",
                        "-pubin",
                        "-in",
                        f"/dev/fd/{key_handle.fileno()}",
                        "-text",
                        "-noout",
                    ],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                    close_fds=True,
                    pass_fds=(key_handle.fileno(),),
                    env={
                        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
                    },
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise EvidenceBundleError(
                    "evidence authority key inspection failed"
                ) from exc
        match = re.search(r"Public-Key:\s*\(([0-9]+) bit\)", inspected.stdout)
        if (
            inspected.returncode != 0
            or match is None
            or not 2048 <= int(match.group(1)) <= 4096
        ):
            raise EvidenceBundleError(
                "evidence authority key must be RSA 2048..4096 bits"
            )
        key = (producer, issuer)
        if key in result:
            raise EvidenceBundleError("evidence authority is duplicated")
        result[key] = encoded
    required = {value[1] for value in _EXTERNAL_BINDINGS.values()}
    if require_complete and {producer for producer, _ in result} != required:
        raise EvidenceBundleError("evidence authority keyring misses a producer class")
    return result


def _verify_authority_signature(
    *, public_key: bytes, receipt: bytes, signature: bytes, claim: str
) -> None:
    if not 128 <= len(signature) <= 16 * 1024:
        raise EvidenceBundleError(
            f"external authority signature size differs for {claim}"
        )
    handles = [tempfile.TemporaryFile() for _ in range(3)]
    try:
        for handle, body in zip(handles, (public_key, signature, receipt), strict=True):
            handle.write(body)
            handle.flush()
            handle.seek(0)
        key_handle, signature_handle, receipt_handle = handles
        command = [
            "openssl",
            "dgst",
            "-sha256",
            "-verify",
            f"/dev/fd/{key_handle.fileno()}",
            "-signature",
            f"/dev/fd/{signature_handle.fileno()}",
            f"/dev/fd/{receipt_handle.fileno()}",
        ]
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
            close_fds=True,
            pass_fds=tuple(handle.fileno() for handle in handles),
            env={
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
            },
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EvidenceBundleError(
            "external authority signature verifier failed"
        ) from exc
    finally:
        for handle in handles:
            handle.close()
    if completed.returncode != 0:
        raise EvidenceBundleError(
            f"external authority signature is invalid for {claim}"
        )


def _external_entries(
    *,
    evidence_root: Path,
    claims: Mapping[str, Mapping[str, str]],
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    hostname: str,
    deployment_id: str,
    authority_keys: Mapping[tuple[str, str], bytes],
    sftp_runtime_ready_raw: bytes,
    sftp_postgres_ledger_raw: bytes,
    expected_sftp_runtime_ready_sha256: str,
    expected_sftp_postgres_ledger_sha256: str,
    expected_sftp_credential_fingerprint_sha256: str,
    expected_sftp_completed_at: str,
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    root_before = _validate_real_private_directory(
        evidence_root, label="external final evidence root"
    )
    try:
        observed = {entry.name for entry in os.scandir(evidence_root)}
    except OSError as exc:
        raise EvidenceBundleError(
            "external final evidence root cannot be scanned"
        ) from exc
    expected_names = _external_expected_names()
    if observed != expected_names:
        raise EvidenceBundleError(
            "external evidence filenames differ from the closed mapping"
        )
    host_digest = _sha256(hostname.encode("utf-8"))
    entries: list[dict[str, Any]] = []
    frozen: dict[str, bytes] = {}
    artifact_digests: set[str] = set()
    for claim in sorted(_EXTERNAL_BINDINGS):
        token, producer = _EXTERNAL_BINDINGS[claim]
        artifact_name = f"{token}.artifact"
        provenance_name = f"{token}.provenance.json"
        signature_name = f"{token}.signature"
        artifact_body = _read_private_file(evidence_root / artifact_name)
        provenance_body = _read_private_file(
            evidence_root / provenance_name, maximum=MAX_JSON_BYTES
        )
        signature_body = _read_private_file(
            evidence_root / signature_name, maximum=16 * 1024
        )
        artifact_digest = _sha256(artifact_body)
        if artifact_digest != claims[claim]["digest"]:
            raise EvidenceBundleError(f"external proof digest differs for {claim}")
        if artifact_digest in artifact_digests:
            raise EvidenceBundleError("external proof artifact is reused across claims")
        artifact_digests.add(artifact_digest)
        provenance = _strict_json_bytes(
            provenance_body, label=f"external provenance {claim}"
        )
        expected_keys = {
            "schema_version",
            "kind",
            "result",
            "environment",
            "claim",
            "producer",
            "issuer",
            "deployment_id",
            "live_sha",
            "release_a_sha",
            "sftp_release_sha",
            "hostname_sha256",
            "artifact_sha256",
            "captured_at",
        }
        if (
            set(provenance) != expected_keys
            or provenance.get("schema_version") != 1
            or provenance.get("kind") != EXTERNAL_PROVENANCE_KIND
            or provenance.get("result") != "passed"
            or provenance.get("environment") != ENVIRONMENT
            or provenance.get("claim") != claim
            or provenance.get("producer") != producer
            or provenance.get("deployment_id") != deployment_id
            or provenance.get("live_sha") != live_sha
            or provenance.get("release_a_sha") != release_a_sha
            or provenance.get("sftp_release_sha") != sftp_sha
            or provenance.get("hostname_sha256") != host_digest
            or provenance.get("artifact_sha256") != artifact_digest
            or provenance.get("captured_at") != claims[claim]["event_at"]
        ):
            raise EvidenceBundleError(
                f"external provenance identity differs for {claim}"
            )
        issuer = provenance.get("issuer")
        if not isinstance(issuer, str) or _ISSUER_RE.fullmatch(issuer) is None:
            raise EvidenceBundleError(f"external provenance issuer differs for {claim}")
        public_key = authority_keys.get((producer, issuer))
        if public_key is None:
            raise EvidenceBundleError(
                f"external provenance issuer is not trusted for {claim}"
            )
        if provenance_body != _canonical_json(provenance) + b"\n":
            raise EvidenceBundleError(
                f"external provenance is not canonical for {claim}"
            )
        _verify_authority_signature(
            public_key=public_key,
            receipt=provenance_body,
            signature=signature_body,
            claim=claim,
        )
        if claim == "evidence.sftp.proof_sha256":
            try:
                summary = sftp_gate.validate_final_artifact_bytes(
                    artifact_body,
                    expected_live_sha=live_sha,
                    expected_release_a_sha=release_a_sha,
                    expected_sftp_sha=sftp_sha,
                    expected_deployment_id=deployment_id,
                    expected_hostname_sha256=host_digest,
                    runtime_ready_receipt_raw=sftp_runtime_ready_raw,
                    postgres_ledger_receipt_raw=sftp_postgres_ledger_raw,
                    expected_completed_at=expected_sftp_completed_at,
                )
            except sftp_gate.SFTPPositiveCanaryError as exc:
                raise EvidenceBundleError(
                    "external SFTP lifecycle proof is invalid"
                ) from exc
            if (
                summary.get("runtime_ready_receipt_sha256")
                != expected_sftp_runtime_ready_sha256
                or summary.get("postgres_ledger_receipt_sha256")
                != expected_sftp_postgres_ledger_sha256
                or summary.get("credential_fingerprint_sha256")
                != expected_sftp_credential_fingerprint_sha256
                or summary.get("completed_at") != expected_sftp_completed_at
            ):
                raise EvidenceBundleError(
                    "external SFTP lifecycle proof differs from the attestation"
                )
        captured_at = _timestamp(
            provenance.get("captured_at"), path=f"external provenance time for {claim}"
        )
        provenance_digest = _sha256(provenance_body)
        signature_digest = _sha256(signature_body)
        entries.append(
            {
                "claim": claim,
                "source": "authorized_external",
                "artifact": f"external-final-evidence/{artifact_name}",
                "artifact_sha256": artifact_digest,
                "event_at": _utc_text(captured_at),
                "artifact_kind": "external_proof",
                "producer": producer,
                "provenance": f"external-final-evidence/{provenance_name}",
                "provenance_sha256": provenance_digest,
                "producer_issuer": issuer,
                "signature": f"external-final-evidence/{signature_name}",
                "signature_sha256": signature_digest,
            }
        )
        frozen[artifact_name] = artifact_body
        frozen[provenance_name] = provenance_body
        frozen[signature_name] = signature_body
    root_after = os.lstat(evidence_root)
    if _identity(root_before) != _identity(root_after):
        raise EvidenceBundleError("external evidence root changed during verification")
    return entries, frozen


def _binding_manifest(
    *,
    canonical: Sequence[Mapping[str, Any]],
    external: Sequence[Mapping[str, Any]],
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    hostname: str,
    deployment_id: str,
    verified_at: datetime,
    authority_keyring_sha256: str,
) -> dict[str, Any]:
    entries = sorted([*canonical, *external], key=lambda row: str(row["claim"]))
    if (
        len(entries) != _FINAL_REFERENCE_COUNT
        or len({str(row["claim"]) for row in entries}) != _FINAL_REFERENCE_COUNT
    ):
        raise EvidenceBundleError("final binding manifest cardinality differs")
    times = [_timestamp(row["event_at"], path="binding event_at") for row in entries]
    if any(value > verified_at + MAX_CLOCK_SKEW for value in times):
        raise EvidenceBundleError("final evidence event is later than verification")
    return {
        **_base_identity(
            deployment_id=deployment_id,
            live_sha=live_sha,
            release_a_sha=release_a_sha,
            hostname=hostname,
        ),
        "kind": FINAL_BINDING_KIND,
        "sftp_release_sha": sftp_sha,
        "reference_count": len(entries),
        "canonical_reference_count": len(canonical),
        "external_reference_count": len(external),
        "authority_keyring_sha256": authority_keyring_sha256,
        "entries": entries,
        "verified_at": _utc_text(verified_at),
    }


def _base_identity(
    *,
    deployment_id: str,
    live_sha: str,
    release_a_sha: str,
    hostname: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result": "passed",
        "environment": ENVIRONMENT,
        "deployment_id": _deployment_id(deployment_id),
        "live_sha": _git_sha(live_sha, path="expected live SHA"),
        "release_a_sha": _git_sha(release_a_sha, path="expected Release A SHA"),
        "hostname_sha256": _sha256(_hostname(hostname).encode("utf-8")),
    }


def verify_preconditions_bundle(
    payload: Any,
    *,
    input_sha256: str,
    evidence_root: Path,
    live_sha: str,
    release_a_sha: str,
    hostname: str,
    deployment_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise EvidenceBundleError("verification time must include a timezone")
    current = current.astimezone(UTC)
    try:
        pre_gate.verify(
            payload,
            live_sha=live_sha,
            release_a_sha=release_a_sha,
            hostname=hostname,
            now=current,
            input_sha256=_digest(input_sha256, path="preconditions byte digest"),
        )
    except pre_gate.PreconditionsError as exc:
        raise EvidenceBundleError(f"preconditions gate failed: {exc}") from exc
    restore, capacity = _precondition_digests(payload)
    bundle = verify_evidence_root(evidence_root, [*restore, *capacity])
    receipt = {
        **_base_identity(
            deployment_id=deployment_id,
            live_sha=live_sha,
            release_a_sha=release_a_sha,
            hostname=hostname,
        ),
        "kind": PRECONDITIONS_RECEIPT_KIND,
        "preconditions_sha256": input_sha256,
        "evidence_file_count": bundle["file_count"],
        "evidence_digest_count": bundle["digest_count"],
        "evidence_reference_count": bundle["reference_count"],
        "evidence_set_sha256": bundle["set_sha256"],
        "restore_proof_set_sha256": _proof_set_sha256(restore),
        "capacity_proof_set_sha256": _proof_set_sha256(capacity),
        "verified_at": _utc_text(current),
    }
    if set(receipt) != _PRECONDITIONS_RECEIPT_KEYS:
        raise EvidenceBundleError("internal preconditions receipt schema differs")
    if len(_canonical_json(receipt)) > MAX_RECEIPT_BYTES:
        raise EvidenceBundleError("preconditions receipt exceeds its byte bound")
    return receipt


def _validate_preconditions_receipt(
    payload: Any,
    *,
    input_sha256: str,
    live_sha: str,
    release_a_sha: str,
    hostname: str,
    deployment_id: str,
    now: datetime,
) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != _PRECONDITIONS_RECEIPT_KEYS:
        raise EvidenceBundleError("preconditions evidence receipt schema differs")
    if payload["schema_version"] != SCHEMA_VERSION or isinstance(
        payload["schema_version"], bool
    ):
        raise EvidenceBundleError("preconditions evidence receipt version differs")
    expected = _base_identity(
        deployment_id=deployment_id,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        hostname=hostname,
    )
    for key, value in expected.items():
        if payload[key] != value:
            raise EvidenceBundleError(f"preconditions evidence receipt {key} differs")
    if payload["kind"] != PRECONDITIONS_RECEIPT_KIND:
        raise EvidenceBundleError("preconditions evidence receipt kind differs")
    for key in (
        "preconditions_sha256",
        "evidence_set_sha256",
        "restore_proof_set_sha256",
        "capacity_proof_set_sha256",
    ):
        _digest(payload[key], path=f"preconditions receipt {key}")
    _digest(input_sha256, path="preconditions receipt byte digest")
    _positive_int(
        payload["evidence_file_count"],
        path="preconditions receipt evidence_file_count",
        maximum=MAX_EVIDENCE_FILES,
    )
    _positive_int(
        payload["evidence_digest_count"],
        path="preconditions receipt evidence_digest_count",
        maximum=MAX_EVIDENCE_FILES,
    )
    _positive_int(
        payload["evidence_reference_count"],
        path="preconditions receipt evidence_reference_count",
        maximum=MAX_EVIDENCE_FILES,
    )
    verified_at = _timestamp(payload["verified_at"], path="preconditions verified_at")
    if (
        verified_at > now + MAX_CLOCK_SKEW
        or verified_at < now - MAX_PRECONDITIONS_RECEIPT_AGE
    ):
        raise EvidenceBundleError(
            "preconditions evidence receipt is stale or future-dated"
        )
    return payload


def _freeze_external_evidence(target: Path, files: Mapping[str, bytes]) -> None:
    """Publish the exact verified external proof set as one durable directory."""

    expected_names = set(files)
    if expected_names != _external_expected_names():
        raise EvidenceBundleError("frozen external evidence set is incomplete")
    if target.exists() or target.is_symlink():
        _validate_real_private_directory(target, label="frozen external evidence")
        try:
            existing = {entry.name for entry in os.scandir(target)}
        except OSError as exc:
            raise EvidenceBundleError(
                "frozen external evidence cannot be scanned"
            ) from exc
        if existing != expected_names:
            raise EvidenceBundleError("frozen external evidence filenames differ")
        for name, expected in files.items():
            if _read_private_file(target / name) != expected:
                raise EvidenceBundleError("frozen external evidence bytes differ")
        return
    parent_row = _validate_real_private_directory(
        target.parent, label="frozen evidence parent"
    )
    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        parent_fd = os.open(target.parent, parent_flags)
    except OSError as exc:
        raise EvidenceBundleError("frozen evidence parent cannot be opened") from exc
    opened_parent = os.fstat(parent_fd)
    if _identity(opened_parent) != _identity(parent_row):
        os.close(parent_fd)
        raise EvidenceBundleError("frozen evidence parent changed while opening")
    temporary_name = f".{target.name}.{os.getpid()}"
    temporary_fd: int | None = None
    published = False
    try:
        try:
            os.stat(temporary_name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise EvidenceBundleError("frozen evidence temporary path already exists")
        os.mkdir(temporary_name, 0o700, dir_fd=parent_fd)
        temporary_fd = os.open(temporary_name, parent_flags, dir_fd=parent_fd)
        temporary_row = os.fstat(temporary_fd)
        if (
            not stat.S_ISDIR(temporary_row.st_mode)
            or temporary_row.st_uid != os.geteuid()
            or stat.S_IMODE(temporary_row.st_mode) != 0o700
        ):
            raise EvidenceBundleError("frozen evidence temporary directory is unsafe")
        for name in sorted(files):
            descriptor = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=temporary_fd,
            )
            try:
                body = files[name]
                offset = 0
                while offset < len(body):
                    written = os.write(descriptor, body[offset:])
                    if written <= 0:
                        raise EvidenceBundleError(
                            "frozen evidence write made no progress"
                        )
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        try:
            os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise EvidenceBundleError("frozen evidence target appeared concurrently")
        os.fsync(temporary_fd)
        os.rename(
            temporary_name,
            target.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        published = True
        os.fsync(parent_fd)
        linked_parent = os.lstat(target.parent)
        stable_parent_fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid")
        if any(
            getattr(linked_parent, field) != getattr(opened_parent, field)
            for field in stable_parent_fields
        ):
            raise EvidenceBundleError("frozen evidence parent changed")
    finally:
        if not published:
            try:
                if temporary_fd is not None:
                    for name in expected_names:
                        try:
                            os.unlink(name, dir_fd=temporary_fd)
                        except FileNotFoundError:
                            pass
                    os.close(temporary_fd)
                    temporary_fd = None
                    os.rmdir(temporary_name, dir_fd=parent_fd)
            except OSError:
                # A failed publication remains fail-closed.  Never recurse into
                # a path whose identity may have changed under another process.
                pass
        if temporary_fd is not None:
            os.close(temporary_fd)
        os.close(parent_fd)
    _validate_real_private_directory(target, label="frozen external evidence")
    for name, expected in files.items():
        if _read_private_file(target / name) != expected:
            raise EvidenceBundleError("published frozen external evidence differs")


def _final_bundle_details(
    payload: Any,
    *,
    input_sha256: str,
    preconditions_receipt: Any,
    preconditions_receipt_sha256: str,
    evidence_root: Path,
    journal_root: Path,
    authority_keyring: Any,
    authority_keyring_sha256: str,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    hostname: str,
    deployment_id: str,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise EvidenceBundleError("verification time must include a timezone")
    current = current.astimezone(UTC)
    prerequisite = _validate_preconditions_receipt(
        preconditions_receipt,
        input_sha256=preconditions_receipt_sha256,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        hostname=hostname,
        deployment_id=deployment_id,
        now=current,
    )
    try:
        final_gate.verify_attestation(
            payload,
            expected_release_a_sha=release_a_sha,
            expected_sftp_sha=sftp_sha,
            expected_hostname=hostname,
            now=current,
            attestation_sha256=_digest(input_sha256, path="attestation byte digest"),
        )
    except final_gate.ReleaseAAttestationError as exc:
        raise EvidenceBundleError(f"final attestation gate failed: {exc}") from exc
    claims = _attestation_claims(payload)
    keyring_digest = _digest(
        authority_keyring_sha256, path="approved authority keyring digest"
    )
    authority_keys = _authority_keyring(authority_keyring)
    try:
        final_restore = [
            row["restore_check"]["proof_sha256"]
            for row in payload["evidence"]["off_vm_backups"]
        ]
    except (KeyError, TypeError) as exc:
        raise EvidenceBundleError("final restore proof fields are incomplete") from exc
    if _proof_set_sha256(final_restore) != prerequisite["restore_proof_set_sha256"]:
        raise EvidenceBundleError("final restore proofs differ from preconditions")
    canonical, canonical_bodies = _canonical_entries(
        journal_root=journal_root,
        claims=claims,
        release_a_sha=release_a_sha,
        deployment_id=deployment_id,
    )
    try:
        sftp_evidence = payload["evidence"]["sftp"]
        runtime_ready_raw = canonical_bodies["sftp-validation-runtime-ready.json"]
        ledger_raw = canonical_bodies["sftp-postgres-ledger-receipt.json"]
        runtime_ready_payload = _strict_json_bytes(
            runtime_ready_raw, label="canonical SFTP runtime-ready receipt"
        )
        ledger_payload = _strict_json_bytes(
            ledger_raw, label="canonical SFTP PostgreSQL ledger receipt"
        )
        if (
            runtime_ready_payload.get("ready_at") != sftp_evidence["runtime_ready_at"]
            or ledger_payload.get("collected_at")
            != sftp_evidence["postgres_ledger_completed_at"]
        ):
            raise EvidenceBundleError(
                "SFTP receipt chronology differs from the attestation"
            )
    except (KeyError, TypeError) as exc:
        raise EvidenceBundleError("SFTP attestation binding is incomplete") from exc
    external, frozen = _external_entries(
        evidence_root=evidence_root,
        claims=claims,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        hostname=hostname,
        deployment_id=deployment_id,
        authority_keys=authority_keys,
        sftp_runtime_ready_raw=runtime_ready_raw,
        sftp_postgres_ledger_raw=ledger_raw,
        expected_sftp_runtime_ready_sha256=sftp_evidence[
            "runtime_ready_receipt_sha256"
        ],
        expected_sftp_postgres_ledger_sha256=sftp_evidence[
            "postgres_ledger_receipt_sha256"
        ],
        expected_sftp_credential_fingerprint_sha256=sftp_evidence[
            "credential_fingerprint_sha256"
        ],
        expected_sftp_completed_at=sftp_evidence["completed_at"],
    )
    manifest = _binding_manifest(
        canonical=canonical,
        external=external,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        hostname=hostname,
        deployment_id=deployment_id,
        verified_at=current,
        authority_keyring_sha256=keyring_digest,
    )
    manifest_sha256 = _sha256(_canonical_json(manifest) + b"\n")
    all_digests = [str(row["artifact_sha256"]) for row in manifest["entries"]]
    provenance_digests = [
        str(row[key])
        for row in external
        for key in ("provenance_sha256", "signature_sha256")
    ]
    receipt = {
        **_base_identity(
            deployment_id=deployment_id,
            live_sha=live_sha,
            release_a_sha=release_a_sha,
            hostname=hostname,
        ),
        "kind": FINAL_RECEIPT_KIND,
        "sftp_release_sha": _git_sha(sftp_sha, path="expected SFTP SHA"),
        "attestation_sha256": input_sha256,
        "preconditions_receipt_sha256": preconditions_receipt_sha256,
        "preconditions_sha256": prerequisite["preconditions_sha256"],
        "evidence_file_count": len(
            {str(row["artifact"]) for row in manifest["entries"]}
        ),
        "evidence_digest_count": len(set(all_digests)),
        "evidence_reference_count": len(all_digests),
        "evidence_set_sha256": _proof_set_sha256(all_digests),
        "binding_manifest_sha256": manifest_sha256,
        "authority_keyring_sha256": keyring_digest,
        "canonical_reference_count": len(canonical),
        "external_reference_count": len(external),
        "external_provenance_set_sha256": _proof_set_sha256(provenance_digests),
        "verified_at": _utc_text(current),
    }
    if set(receipt) != _FINAL_RECEIPT_KEYS:
        raise EvidenceBundleError("internal final receipt schema differs")
    if len(_canonical_json(receipt)) > MAX_RECEIPT_BYTES:
        raise EvidenceBundleError("final receipt exceeds its byte bound")
    return receipt, manifest, frozen


def verify_final_bundle(
    payload: Any,
    *,
    input_sha256: str,
    preconditions_receipt: Any,
    preconditions_receipt_sha256: str,
    evidence_root: Path,
    journal_root: Path,
    authority_keyring: Any,
    authority_keyring_sha256: str,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    hostname: str,
    deployment_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    receipt, _, _ = _final_bundle_details(
        payload,
        input_sha256=input_sha256,
        preconditions_receipt=preconditions_receipt,
        preconditions_receipt_sha256=preconditions_receipt_sha256,
        evidence_root=evidence_root,
        journal_root=journal_root,
        authority_keyring=authority_keyring,
        authority_keyring_sha256=authority_keyring_sha256,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        hostname=hostname,
        deployment_id=deployment_id,
        now=now,
    )
    return receipt


def verify_final_frozen(
    payload: Any,
    *,
    input_sha256: str,
    preconditions_receipt: Any,
    preconditions_receipt_sha256: str,
    evidence_receipt: Any,
    binding_manifest: Any,
    authority_keyring: Any,
    authority_keyring_sha256: str,
    evidence_root: Path,
    journal_root: Path,
    live_sha: str,
    release_a_sha: str,
    sftp_sha: str,
    hostname: str,
    deployment_id: str,
    now: datetime | None = None,
) -> None:
    if (
        not isinstance(evidence_receipt, Mapping)
        or set(evidence_receipt) != _FINAL_RECEIPT_KEYS
    ):
        raise EvidenceBundleError("frozen final evidence receipt schema differs")
    verified_at = _timestamp(
        evidence_receipt.get("verified_at"), path="final evidence verified_at"
    )
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if verified_at > current + MAX_CLOCK_SKEW:
        raise EvidenceBundleError("final evidence receipt is future-dated")
    rebuilt_receipt, rebuilt_manifest, _ = _final_bundle_details(
        payload,
        input_sha256=input_sha256,
        preconditions_receipt=preconditions_receipt,
        preconditions_receipt_sha256=preconditions_receipt_sha256,
        evidence_root=evidence_root,
        journal_root=journal_root,
        authority_keyring=authority_keyring,
        authority_keyring_sha256=authority_keyring_sha256,
        live_sha=live_sha,
        release_a_sha=release_a_sha,
        sftp_sha=sftp_sha,
        hostname=hostname,
        deployment_id=deployment_id,
        now=verified_at,
    )
    if evidence_receipt != rebuilt_receipt:
        raise EvidenceBundleError(
            "frozen final evidence receipt differs from its proofs"
        )
    if binding_manifest != rebuilt_manifest:
        raise EvidenceBundleError(
            "frozen final binding manifest differs from its proofs"
        )
    manifest_digest = _sha256(_canonical_json(binding_manifest) + b"\n")
    if evidence_receipt.get("binding_manifest_sha256") != manifest_digest:
        raise EvidenceBundleError("final evidence binding manifest digest differs")


def _ensure_outside_evidence(root: Path, paths: Sequence[Path]) -> None:
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise EvidenceBundleError("evidence root is unavailable") from exc
    for path in paths:
        candidate = path if path.exists() else path.parent
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise EvidenceBundleError("input/output parent is unavailable") from exc
        if resolved == resolved_root or resolved_root in resolved.parents:
            raise EvidenceBundleError(
                "inputs and receipts must stay outside evidence root"
            )


def _write_exclusive_private(
    path: Path,
    payload: Mapping[str, Any],
    *,
    maximum: int = MAX_RECEIPT_BYTES,
) -> None:
    body = _canonical_json(payload) + b"\n"
    if len(body) > maximum:
        raise EvidenceBundleError("receipt exceeds its byte bound")
    if path.name in {"", ".", ".."}:
        raise EvidenceBundleError("receipt filename is invalid")
    try:
        parent_row = os.lstat(path.parent)
    except OSError as exc:
        raise EvidenceBundleError("receipt parent directory is unavailable") from exc
    if (
        stat.S_ISLNK(parent_row.st_mode)
        or not stat.S_ISDIR(parent_row.st_mode)
        or parent_row.st_uid != os.geteuid()
        or stat.S_IMODE(parent_row.st_mode) != 0o700
    ):
        raise EvidenceBundleError(
            "receipt parent must be a real owner-owned mode 0700 directory"
        )
    parent_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_fd = os.open(path.parent, parent_flags)
    created = False
    try:
        if _identity(os.fstat(parent_fd)) != _identity(parent_row):
            raise EvidenceBundleError("receipt parent changed before creation")
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
        created = True
        try:
            offset = 0
            while offset < len(body):
                written = os.write(descriptor, body[offset:])
                if written <= 0:
                    raise EvidenceBundleError("receipt write made no progress")
                offset += written
            os.fsync(descriptor)
            row = os.fstat(descriptor)
            if (
                not stat.S_ISREG(row.st_mode)
                or row.st_nlink != 1
                or row.st_uid != os.geteuid()
                or stat.S_IMODE(row.st_mode) != 0o600
                or row.st_size != len(body)
            ):
                raise EvidenceBundleError("created receipt is unsafe")
        finally:
            os.close(descriptor)
        os.fsync(parent_fd)
    except BaseException:
        if created:
            try:
                os.unlink(path.name, dir_fd=parent_fd)
            except OSError:
                pass
        raise
    finally:
        os.close(parent_fd)


def _write_or_verify_private(
    path: Path,
    payload: Mapping[str, Any],
    *,
    maximum: int = MAX_RECEIPT_BYTES,
) -> None:
    expected = _canonical_json(payload) + b"\n"
    if path.exists() or path.is_symlink():
        if _read_private_file(path, maximum=maximum) != expected:
            raise EvidenceBundleError("existing private receipt/manifest differs")
        return
    _write_exclusive_private(path, payload, maximum=maximum)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    keyring = commands.add_parser(
        "verify-authority-keyring",
        help="require the complete preflight-pinned public evidence trust roots",
    )
    keyring.add_argument("--authority-keyring", type=Path, required=True)

    def identity(command: argparse.ArgumentParser) -> None:
        command.add_argument("--evidence-root", type=Path, required=True)
        command.add_argument("--expected-live-sha", required=True)
        command.add_argument("--expected-release-a-sha", required=True)
        command.add_argument("--expected-hostname", required=True)
        command.add_argument("--deployment-id", required=True)
        command.add_argument("--output", type=Path, required=True)

    preconditions = commands.add_parser(
        "verify-preconditions", help="bind pre-mutation restore and capacity artifacts"
    )
    identity(preconditions)
    preconditions.add_argument("--preconditions", type=Path, required=True)

    final = commands.add_parser(
        "verify-final", help="bind the v4 final attestation to all artifact bytes"
    )
    identity(final)
    final.add_argument("--attestation", type=Path, required=True)
    final.add_argument("--preconditions-receipt", type=Path, required=True)
    final.add_argument("--expected-sftp-sha", required=True)
    final.add_argument("--journal-root", type=Path, required=True)
    final.add_argument("--authority-keyring", type=Path, required=True)
    final.add_argument("--expected-authority-keyring-sha256", required=True)
    final.add_argument("--binding-manifest-output", type=Path, required=True)
    final.add_argument("--frozen-evidence-output", type=Path, required=True)

    frozen = commands.add_parser(
        "verify-final-frozen",
        help="revalidate a frozen final binding without the operator source tree",
    )
    frozen.add_argument("--attestation", type=Path, required=True)
    frozen.add_argument("--preconditions-receipt", type=Path, required=True)
    frozen.add_argument("--evidence-receipt", type=Path, required=True)
    frozen.add_argument("--binding-manifest", type=Path, required=True)
    frozen.add_argument("--evidence-root", type=Path, required=True)
    frozen.add_argument("--journal-root", type=Path, required=True)
    frozen.add_argument("--authority-keyring", type=Path, required=True)
    frozen.add_argument("--expected-authority-keyring-sha256", required=True)
    frozen.add_argument("--expected-live-sha", required=True)
    frozen.add_argument("--expected-release-a-sha", required=True)
    frozen.add_argument("--expected-sftp-sha", required=True)
    frozen.add_argument("--expected-hostname", required=True)
    frozen.add_argument("--deployment-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "verify-authority-keyring":
            payload, _ = load_private_json(args.authority_keyring)
            # This is the transaction preflight gate, not a permissive schema
            # linter.  An incomplete reviewed registry must stop the release
            # before any stateful adoption can begin.
            _authority_keyring(payload, require_complete=True)
            print("passed")
            return 0
        if args.command == "verify-preconditions":
            _ensure_outside_evidence(
                args.evidence_root, (args.preconditions, args.output)
            )
            payload, input_sha256 = load_private_json(args.preconditions)
            receipt = verify_preconditions_bundle(
                payload,
                input_sha256=input_sha256,
                evidence_root=args.evidence_root,
                live_sha=args.expected_live_sha,
                release_a_sha=args.expected_release_a_sha,
                hostname=args.expected_hostname,
                deployment_id=args.deployment_id,
            )
        elif args.command == "verify-final":
            _ensure_outside_evidence(
                args.evidence_root,
                (
                    args.attestation,
                    args.preconditions_receipt,
                    args.output,
                    args.binding_manifest_output,
                    args.frozen_evidence_output,
                    args.journal_root,
                    args.authority_keyring,
                ),
            )
            payload, input_sha256 = load_private_json(args.attestation)
            prerequisite, prerequisite_sha256 = load_private_json(
                args.preconditions_receipt
            )
            authority_keyring, authority_keyring_sha256 = load_private_json(
                args.authority_keyring
            )
            if authority_keyring_sha256 != _digest(
                args.expected_authority_keyring_sha256,
                path="expected authority keyring digest",
            ):
                raise EvidenceBundleError(
                    "authority keyring differs from approved digest"
                )
            receipt, manifest, frozen_files = _final_bundle_details(
                payload,
                input_sha256=input_sha256,
                preconditions_receipt=prerequisite,
                preconditions_receipt_sha256=prerequisite_sha256,
                evidence_root=args.evidence_root,
                journal_root=args.journal_root,
                authority_keyring=authority_keyring,
                authority_keyring_sha256=authority_keyring_sha256,
                live_sha=args.expected_live_sha,
                release_a_sha=args.expected_release_a_sha,
                sftp_sha=args.expected_sftp_sha,
                hostname=args.expected_hostname,
                deployment_id=args.deployment_id,
            )
            _freeze_external_evidence(args.frozen_evidence_output, frozen_files)
            # Rebuild from the durable copy before publishing either receipt.
            frozen_receipt, frozen_manifest, _ = _final_bundle_details(
                payload,
                input_sha256=input_sha256,
                preconditions_receipt=prerequisite,
                preconditions_receipt_sha256=prerequisite_sha256,
                evidence_root=args.frozen_evidence_output,
                journal_root=args.journal_root,
                authority_keyring=authority_keyring,
                authority_keyring_sha256=authority_keyring_sha256,
                live_sha=args.expected_live_sha,
                release_a_sha=args.expected_release_a_sha,
                sftp_sha=args.expected_sftp_sha,
                hostname=args.expected_hostname,
                deployment_id=args.deployment_id,
                now=_timestamp(receipt["verified_at"], path="final verified_at"),
            )
            if frozen_receipt != receipt or frozen_manifest != manifest:
                raise EvidenceBundleError("durable external evidence copy differs")
            _write_or_verify_private(
                args.binding_manifest_output, manifest, maximum=MAX_JSON_BYTES
            )
            _write_or_verify_private(args.output, receipt)
            print("passed")
            return 0
        elif args.command == "verify-final-frozen":
            payload, input_sha256 = load_private_json(args.attestation)
            prerequisite, prerequisite_sha256 = load_private_json(
                args.preconditions_receipt
            )
            evidence_receipt, _ = load_private_json(args.evidence_receipt)
            binding_manifest, _ = load_private_json(args.binding_manifest)
            authority_keyring, authority_keyring_sha256 = load_private_json(
                args.authority_keyring
            )
            if authority_keyring_sha256 != _digest(
                args.expected_authority_keyring_sha256,
                path="expected authority keyring digest",
            ):
                raise EvidenceBundleError(
                    "authority keyring differs from approved digest"
                )
            verify_final_frozen(
                payload,
                input_sha256=input_sha256,
                preconditions_receipt=prerequisite,
                preconditions_receipt_sha256=prerequisite_sha256,
                evidence_receipt=evidence_receipt,
                binding_manifest=binding_manifest,
                authority_keyring=authority_keyring,
                authority_keyring_sha256=authority_keyring_sha256,
                evidence_root=args.evidence_root,
                journal_root=args.journal_root,
                live_sha=args.expected_live_sha,
                release_a_sha=args.expected_release_a_sha,
                sftp_sha=args.expected_sftp_sha,
                hostname=args.expected_hostname,
                deployment_id=args.deployment_id,
            )
            print("passed")
            return 0
        else:
            raise EvidenceBundleError("unknown evidence bundle command")
        _write_exclusive_private(args.output, receipt)
    except (EvidenceBundleError, OSError) as exc:
        print(f"Release A evidence bundle refused: {exc}", file=sys.stderr)
        return 1
    print("passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
