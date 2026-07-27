#!/usr/bin/env python3
"""Verify the private, content-free pre-mutation gate for Release A.

The one-time safety adoption cannot use its final Release A attestation before
the runtime has been adopted.  This smaller gate proves the only evidence that
must exist *before* the maintenance window: three distinct off-VM backups,
successful restore rehearsals and a recent capacity reading for each live
filesystem.  The executor independently re-measures the three filesystems; the
JSON therefore cannot weaken its configured minimums.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROFILE = "agentium-release-a-preconditions-v1"
RECEIPT_PROFILE = "agentium-release-a-preconditions-receipt-v1"
MAX_BYTES = 64 * 1024
# 96h: the window may legitimately open days after the attested off-VM
# backups completed.  Once the maintenance gates are closed (ingress shut,
# writers stopped, secure deposit read-only) no mutation can age the backups,
# and the executor still re-measures capacity independently at preflight.
MAX_AGE = timedelta(hours=96)
MAX_CLOCK_SKEW = timedelta(minutes=5)
MINIMUMS = {
    "/": ("/dev/sda1", 40 * 1024**3),
    "/srv/agentium-data": ("/dev/sdb", 64 * 1024**3),
    "/home/ubuntu/omnirag/backend/data/secure_deposit": (
        "/dev/sdc",
        64 * 1024**3,
    ),
}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")
_TOP_KEYS = {
    "profile",
    "result",
    "environment",
    "live_sha",
    "release_a_sha",
    "hostname",
    "attested_at",
    "off_vm_backups",
    "capacity",
}


class PreconditionsError(RuntimeError):
    """The Release A pre-mutation evidence is incomplete or unsafe."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise PreconditionsError("preconditions are not canonical JSON") from exc


def _object(value: Any, keys: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise PreconditionsError(f"{path} has an invalid field set")
    return value


def _digest(value: Any, path: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise PreconditionsError(f"{path} must be a lowercase SHA-256 digest")
    return value


def _sha(value: Any, path: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise PreconditionsError(f"{path} must be a lowercase Git SHA")
    return value


def _timestamp(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PreconditionsError(f"{path} must be an UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PreconditionsError(f"{path} is not a timestamp") from exc
    return parsed.astimezone(timezone.utc)


def _private_json(path: Path, expected_uid: int | None = None) -> tuple[Any, str]:
    uid = os.geteuid() if expected_uid is None else expected_uid
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise PreconditionsError("preconditions file is unavailable or unsafe") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise PreconditionsError("preconditions must be a single-link regular file")
        if before.st_uid != uid or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}:
            raise PreconditionsError("preconditions ownership or mode is unsafe")
        if before.st_size > MAX_BYTES:
            raise PreconditionsError("preconditions file is too large")
        body = b""
        while len(body) <= MAX_BYTES:
            chunk = os.read(fd, min(65536, MAX_BYTES + 1 - len(body)))
            if not chunk:
                break
            body += chunk
        after = os.fstat(fd)
    finally:
        os.close(fd)
    identity = lambda row: (  # noqa: E731 - compact immutable identity tuple
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
    if identity(before) != identity(after) or len(body) > MAX_BYTES:
        raise PreconditionsError("preconditions changed while being read")
    try:
        return json.loads(body, object_pairs_hook=_no_duplicates), hashlib.sha256(body).hexdigest()
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreconditionsError("preconditions are not strict JSON") from exc


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreconditionsError("preconditions contain a duplicate field")
        result[key] = value
    return result


def verify(
    payload: Any,
    *,
    live_sha: str,
    release_a_sha: str,
    hostname: str,
    now: datetime | None = None,
    input_sha256: str | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = _object(payload, _TOP_KEYS, "preconditions")
    if root["profile"] != PROFILE or root["result"] != "passed":
        raise PreconditionsError("preconditions profile/result is invalid")
    if root["environment"] != "production":
        raise PreconditionsError("preconditions environment must be production")
    if _sha(root["live_sha"], "live_sha") != _sha(live_sha, "expected live_sha"):
        raise PreconditionsError("live_sha differs")
    if _sha(root["release_a_sha"], "release_a_sha") != _sha(
        release_a_sha, "expected release_a_sha"
    ):
        raise PreconditionsError("release_a_sha differs")
    if not isinstance(root["hostname"], str) or root["hostname"] != hostname:
        raise PreconditionsError("hostname differs")
    attested_at = _timestamp(root["attested_at"], "attested_at")
    if attested_at < current - MAX_AGE or attested_at > current + MAX_CLOCK_SKEW:
        raise PreconditionsError("preconditions are stale or future-dated")

    backups = root["off_vm_backups"]
    if not isinstance(backups, list) or len(backups) != 3:
        raise PreconditionsError("exactly three off-VM backups are required")
    expected_devices = {item[0] for item in MINIMUMS.values()}
    seen_devices: set[str] = set()
    seen_ids: set[str] = set()
    seen_restore_proofs: set[str] = set()
    for index, candidate in enumerate(backups):
        row = _object(
            candidate,
            {
                "source_device",
                "provider",
                "backup_id_sha256",
                "completed_at",
                "restore_check",
            },
            f"off_vm_backups[{index}]",
        )
        device = row["source_device"]
        if device not in expected_devices or device in seen_devices:
            raise PreconditionsError("backup devices are incomplete or duplicated")
        seen_devices.add(device)
        if not isinstance(row["provider"], str) or _TOKEN_RE.fullmatch(row["provider"]) is None:
            raise PreconditionsError("backup provider is invalid")
        identifier = _digest(row["backup_id_sha256"], "backup_id_sha256")
        if identifier in seen_ids:
            raise PreconditionsError("backup identifiers must be distinct")
        seen_ids.add(identifier)
        completed = _timestamp(row["completed_at"], "backup.completed_at")
        restore = _object(
            row["restore_check"],
            {"result", "proof_sha256", "completed_at"},
            "restore_check",
        )
        if restore["result"] != "passed":
            raise PreconditionsError("every restore rehearsal must pass")
        restore_proof = _digest(
            restore["proof_sha256"], "restore_check.proof_sha256"
        )
        if restore_proof in seen_restore_proofs:
            raise PreconditionsError("restore proofs must be distinct per filesystem")
        seen_restore_proofs.add(restore_proof)
        restored = _timestamp(restore["completed_at"], "restore_check.completed_at")
        if completed < current - MAX_AGE or restored < completed or restored > attested_at:
            raise PreconditionsError("backup/restore timestamps are invalid or stale")

    capacity = root["capacity"]
    if not isinstance(capacity, list) or len(capacity) != 3:
        raise PreconditionsError("capacity must cover exactly three filesystems")
    seen_mounts: set[str] = set()
    seen_capacity_proofs: set[str] = set()
    for index, candidate in enumerate(capacity):
        row = _object(
            candidate,
            {
                "mountpoint",
                "source_device",
                "total_bytes",
                "available_bytes",
                "total_inodes",
                "available_inodes",
                "proof_sha256",
                "measured_at",
            },
            f"capacity[{index}]",
        )
        mountpoint = row["mountpoint"]
        if mountpoint not in MINIMUMS or mountpoint in seen_mounts:
            raise PreconditionsError("capacity mountpoints are incomplete or duplicated")
        seen_mounts.add(mountpoint)
        expected_device, minimum = MINIMUMS[mountpoint]
        if row["source_device"] != expected_device:
            raise PreconditionsError("capacity source device differs")
        total = row["total_bytes"]
        available = row["available_bytes"]
        total_inodes = row["total_inodes"]
        available_inodes = row["available_inodes"]
        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or total <= 0
            or isinstance(available, bool)
            or not isinstance(available, int)
            or available < max(minimum, (total + 9) // 10)
        ):
            raise PreconditionsError("capacity is below the non-lowerable minimum")
        if (
            isinstance(total_inodes, bool)
            or not isinstance(total_inodes, int)
            or total_inodes <= 0
            or isinstance(available_inodes, bool)
            or not isinstance(available_inodes, int)
            or available_inodes < (total_inodes + 9) // 10
        ):
            raise PreconditionsError("inode capacity is below ten percent")
        capacity_proof = _digest(row["proof_sha256"], "capacity.proof_sha256")
        if capacity_proof in seen_capacity_proofs:
            raise PreconditionsError("capacity proofs must be distinct per filesystem")
        seen_capacity_proofs.add(capacity_proof)
        measured = _timestamp(row["measured_at"], "capacity.measured_at")
        if measured < current - MAX_AGE or measured > attested_at:
            raise PreconditionsError("capacity measurement is stale or future-dated")

    digest = input_sha256 or hashlib.sha256(_canonical(root)).hexdigest()
    _digest(digest, "preconditions byte digest")
    return {
        "profile": RECEIPT_PROFILE,
        "result": "passed",
        "live_sha": live_sha,
        "release_a_sha": release_a_sha,
        "hostname_sha256": hashlib.sha256(hostname.encode()).hexdigest(),
        "preconditions_sha256": digest,
        "verified_at": current.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


def _write_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical(payload) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preconditions", type=Path, required=True)
    parser.add_argument("--expected-live-sha", required=True)
    parser.add_argument("--expected-release-a-sha", required=True)
    parser.add_argument("--expected-hostname", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload, digest = _private_json(args.preconditions)
        receipt = verify(
            payload,
            live_sha=args.expected_live_sha,
            release_a_sha=args.expected_release_a_sha,
            hostname=args.expected_hostname,
            input_sha256=digest,
        )
        _write_exclusive(args.output, receipt)
    except (OSError, PreconditionsError) as exc:
        print(f"Release A preconditions refused: {exc}", file=sys.stderr)
        return 1
    print("passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
