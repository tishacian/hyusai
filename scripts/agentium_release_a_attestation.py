#!/usr/bin/env python3
"""Verify the operator-supplied safety gate between Agentium Releases A and B.

The input is deliberately content-free: it records only fixed outcomes,
timestamps and SHA-256 fingerprints.  It must never contain credentials,
customer data, backup identifiers in clear text, or proof bodies.  Successful
verification emits a compact receipt bound to the exact Release A commit and
to the exact input bytes.  The closed backup gate covers the three live data
filesystems: /dev/sda1, /dev/sdb and /dev/sdc.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 4
ATTESTATION_KIND = "agentium-release-a-attestation"
RECEIPT_KIND = "agentium-release-a-verification-receipt"
ENVIRONMENT = "production"
MAX_INPUT_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 4096
MAX_CLOCK_SKEW = timedelta(minutes=5)
MIN_MAX_AGE_HOURS = 0.25
MAX_MAX_AGE_HOURS = 168.0
DEFAULT_MAX_AGE_HOURS = 24.0

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\."
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)
_PROVIDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")

_TOP_LEVEL_KEYS = {
    "schema_version",
    "kind",
    "result",
    "environment",
    "release_a_sha",
    "sftp_release_sha",
    "hostname",
    "attested_at",
    "evidence",
}
_EVIDENCE_KEYS = {
    "canaries",
    "data_integrity",
    "off_vm_backups",
    "minio",
    "qdrant",
    "runtime",
    "tenant_audit",
    "sftp",
    "principals",
}
_CANARY_KEYS = {"showcase", "andritz", "sentinel", "octocity", "livekit"}
_DATA_INTEGRITY_KEYS = {
    "postgresql",
    "qdrant",
    "minio_object_store",
    "faiss",
    "secure_deposit",
    "rabbitmq",
}
_PRINCIPAL_KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{2,47}$")


class ReleaseAAttestationError(RuntimeError):
    """The Release A operator attestation is unsafe, stale or incomplete."""


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
        raise ReleaseAAttestationError("attestation is not canonical JSON") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _object(value: Any, *, path: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseAAttestationError(f"{path} must be an object")
    if set(value) != keys:
        raise ReleaseAAttestationError(f"{path} has an invalid field set")
    return value


def _exact_text(value: Any, *, expected: str, path: str) -> str:
    if not isinstance(value, str) or value != expected:
        raise ReleaseAAttestationError(f"{path} must equal {expected!r}")
    return value


def _sha(value: Any, *, path: str, git: bool = False) -> str:
    pattern = _GIT_SHA_RE if git else _SHA256_RE
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        label = "Git SHA" if git else "SHA-256 digest"
        raise ReleaseAAttestationError(f"{path} must be a lowercase {label}")
    return value


def _passed(value: Any, *, path: str) -> None:
    _exact_text(value, expected="passed", path=path)


def _true(value: Any, *, path: str) -> None:
    if value is not True:
        raise ReleaseAAttestationError(f"{path} must be true")


def _zero(value: Any, *, path: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 0:
        raise ReleaseAAttestationError(f"{path} must be the integer zero")


def _timestamp(value: Any, *, path: str) -> datetime:
    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise ReleaseAAttestationError(
            f"{path} must be an ISO-8601 UTC timestamp ending in Z"
        )
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ReleaseAAttestationError(f"{path} is not a valid timestamp") from exc
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    rendered = value.astimezone(UTC).isoformat(timespec="seconds")
    return rendered.replace("+00:00", "Z")


def _fresh_timestamp(
    value: Any,
    *,
    path: str,
    now: datetime,
    oldest: datetime,
    attested_at: datetime,
) -> datetime:
    parsed = _timestamp(value, path=path)
    if parsed < oldest:
        raise ReleaseAAttestationError(f"{path} is stale")
    if parsed > attested_at:
        raise ReleaseAAttestationError(f"{path} is later than attested_at")
    if parsed > now + MAX_CLOCK_SKEW:
        raise ReleaseAAttestationError(f"{path} is too far in the future")
    return parsed


def _validate_max_age(value: float) -> timedelta:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReleaseAAttestationError("max age must be numeric")
    rendered = float(value)
    if (
        not math.isfinite(rendered)
        or rendered < MIN_MAX_AGE_HOURS
        or rendered > MAX_MAX_AGE_HOURS
    ):
        raise ReleaseAAttestationError(
            f"max age must be between {MIN_MAX_AGE_HOURS:g} and "
            f"{MAX_MAX_AGE_HOURS:g} hours"
        )
    return timedelta(hours=rendered)


def _validate_hostname(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or _HOSTNAME_RE.fullmatch(value) is None:
        raise ReleaseAAttestationError(f"{path} must be a lowercase DNS hostname")
    return value


def _validate_backups(
    value: Any,
    *,
    now: datetime,
    oldest: datetime,
    attested_at: datetime,
) -> None:
    expected_devices = {"/dev/sda1", "/dev/sdb", "/dev/sdc"}
    if not isinstance(value, list) or len(value) != len(expected_devices):
        raise ReleaseAAttestationError(
            "evidence.off_vm_backups must contain exactly three rows"
        )
    seen_devices: set[str] = set()
    seen_identifiers: set[str] = set()
    seen_restore_proofs: set[str] = set()
    for index, candidate in enumerate(value):
        path = f"evidence.off_vm_backups[{index}]"
        row = _object(
            candidate,
            path=path,
            keys={
                "source_device",
                "provider",
                "backup_id_sha256",
                "completed_at",
                "restore_check",
            },
        )
        device = row["source_device"]
        if device not in expected_devices or device in seen_devices:
            raise ReleaseAAttestationError(
                f"{path}.source_device is invalid or duplicated"
            )
        seen_devices.add(device)
        provider = row["provider"]
        if not isinstance(provider, str) or _PROVIDER_RE.fullmatch(provider) is None:
            raise ReleaseAAttestationError(
                f"{path}.provider must be a safe provider token"
            )
        identifier = _sha(row["backup_id_sha256"], path=f"{path}.backup_id_sha256")
        if identifier in seen_identifiers:
            raise ReleaseAAttestationError("off-VM backup identifiers must be distinct")
        seen_identifiers.add(identifier)
        completed_at = _fresh_timestamp(
            row["completed_at"],
            path=f"{path}.completed_at",
            now=now,
            oldest=oldest,
            attested_at=attested_at,
        )
        restore = _object(
            row["restore_check"],
            path=f"{path}.restore_check",
            keys={"result", "proof_sha256", "completed_at"},
        )
        _passed(restore["result"], path=f"{path}.restore_check.result")
        restore_proof = _sha(
            restore["proof_sha256"],
            path=f"{path}.restore_check.proof_sha256",
        )
        if restore_proof in seen_restore_proofs:
            raise ReleaseAAttestationError(
                "off-VM restore proofs must be distinct per filesystem"
            )
        seen_restore_proofs.add(restore_proof)
        restored_at = _fresh_timestamp(
            restore["completed_at"],
            path=f"{path}.restore_check.completed_at",
            now=now,
            oldest=oldest,
            attested_at=attested_at,
        )
        if restored_at < completed_at:
            raise ReleaseAAttestationError(
                f"{path}.restore_check.completed_at predates the backup"
            )
    if seen_devices != expected_devices:
        raise ReleaseAAttestationError(
            "off-VM backups must cover /dev/sda1, /dev/sdb and /dev/sdc"
        )


def _validate_canaries(
    value: Any,
    *,
    now: datetime,
    oldest: datetime,
    attested_at: datetime,
) -> None:
    canaries = _object(
        value,
        path="evidence.canaries",
        keys=_CANARY_KEYS,
    )
    for name in sorted(_CANARY_KEYS):
        path = f"evidence.canaries.{name}"
        row = _object(
            canaries[name],
            path=path,
            keys={"result", "proof_sha256", "completed_at"},
        )
        _passed(row["result"], path=f"{path}.result")
        _sha(row["proof_sha256"], path=f"{path}.proof_sha256")
        _fresh_timestamp(
            row["completed_at"],
            path=f"{path}.completed_at",
            now=now,
            oldest=oldest,
            attested_at=attested_at,
        )


def _validate_data_integrity(
    value: Any,
    *,
    now: datetime,
    oldest: datetime,
    attested_at: datetime,
) -> None:
    integrity = _object(
        value,
        path="evidence.data_integrity",
        keys=_DATA_INTEGRITY_KEYS,
    )
    for name in sorted(_DATA_INTEGRITY_KEYS):
        path = f"evidence.data_integrity.{name}"
        row = _object(
            integrity[name],
            path=path,
            keys={
                "result",
                "before_sha256",
                "before_at",
                "after_sha256",
                "after_at",
                "comparison_sha256",
                "completed_at",
            },
        )
        _passed(row["result"], path=f"{path}.result")
        _sha(row["before_sha256"], path=f"{path}.before_sha256")
        before_at = _fresh_timestamp(
            row["before_at"],
            path=f"{path}.before_at",
            now=now,
            oldest=oldest,
            attested_at=attested_at,
        )
        _sha(row["after_sha256"], path=f"{path}.after_sha256")
        after_at = _fresh_timestamp(
            row["after_at"],
            path=f"{path}.after_at",
            now=now,
            oldest=oldest,
            attested_at=attested_at,
        )
        _sha(row["comparison_sha256"], path=f"{path}.comparison_sha256")
        completed_at = _fresh_timestamp(
            row["completed_at"],
            path=f"{path}.completed_at",
            now=now,
            oldest=oldest,
            attested_at=attested_at,
        )
        if after_at < before_at:
            raise ReleaseAAttestationError(f"{path}.after_at predates before_at")
        if completed_at < after_at:
            raise ReleaseAAttestationError(f"{path}.completed_at predates after_at")


def _validate_minio(
    value: Any,
    *,
    now: datetime,
    oldest: datetime,
    attested_at: datetime,
) -> None:
    row = _object(
        value,
        path="evidence.minio",
        keys={
            "versioning",
            "application_credential_fingerprint_sha256",
            "root_credential_fingerprint_sha256",
            "canary",
            "proof_sha256",
            "completed_at",
        },
    )
    _exact_text(row["versioning"], expected="Enabled", path="evidence.minio.versioning")
    application = _sha(
        row["application_credential_fingerprint_sha256"],
        path="evidence.minio.application_credential_fingerprint_sha256",
    )
    root = _sha(
        row["root_credential_fingerprint_sha256"],
        path="evidence.minio.root_credential_fingerprint_sha256",
    )
    if application == root:
        raise ReleaseAAttestationError(
            "MinIO application and root credentials are not separated"
        )
    canary = _object(
        row["canary"],
        path="evidence.minio.canary",
        keys={"delete_denied", "config_denied"},
    )
    _true(canary["delete_denied"], path="evidence.minio.canary.delete_denied")
    _true(canary["config_denied"], path="evidence.minio.canary.config_denied")
    _sha(row["proof_sha256"], path="evidence.minio.proof_sha256")
    _fresh_timestamp(
        row["completed_at"],
        path="evidence.minio.completed_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )


def _validate_qdrant(
    value: Any,
    *,
    now: datetime,
    oldest: datetime,
    attested_at: datetime,
) -> None:
    row = _object(
        value,
        path="evidence.qdrant",
        keys={
            "admin_key_fingerprint_sha256",
            "read_only_key_fingerprint_sha256",
            "read_only_write_denied",
            "inventory_sha256",
            "proof_sha256",
            "completed_at",
        },
    )
    admin = _sha(
        row["admin_key_fingerprint_sha256"],
        path="evidence.qdrant.admin_key_fingerprint_sha256",
    )
    read_only = _sha(
        row["read_only_key_fingerprint_sha256"],
        path="evidence.qdrant.read_only_key_fingerprint_sha256",
    )
    if admin == read_only:
        raise ReleaseAAttestationError(
            "Qdrant admin and read-only keys are not separated"
        )
    _true(
        row["read_only_write_denied"],
        path="evidence.qdrant.read_only_write_denied",
    )
    _sha(row["inventory_sha256"], path="evidence.qdrant.inventory_sha256")
    _sha(row["proof_sha256"], path="evidence.qdrant.proof_sha256")
    _fresh_timestamp(
        row["completed_at"],
        path="evidence.qdrant.completed_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )


def _validate_runtime(
    value: Any,
    *,
    now: datetime,
    oldest: datetime,
    attested_at: datetime,
) -> None:
    runtime = _object(
        value,
        path="evidence.runtime",
        keys={"maintenance_gate", "backend", "restart_contract"},
    )
    maintenance = _object(
        runtime["maintenance_gate"],
        path="evidence.runtime.maintenance_gate",
        keys={"survived_reboot", "proof_sha256", "completed_at"},
    )
    _true(
        maintenance["survived_reboot"],
        path="evidence.runtime.maintenance_gate.survived_reboot",
    )
    _sha(
        maintenance["proof_sha256"],
        path="evidence.runtime.maintenance_gate.proof_sha256",
    )
    _fresh_timestamp(
        maintenance["completed_at"],
        path="evidence.runtime.maintenance_gate.completed_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )

    backend = _object(
        runtime["backend"],
        path="evidence.runtime.backend",
        keys={"listener", "public_listener_count", "proof_sha256", "completed_at"},
    )
    _exact_text(
        backend["listener"],
        expected="127.0.0.1:8000",
        path="evidence.runtime.backend.listener",
    )
    _zero(
        backend["public_listener_count"],
        path="evidence.runtime.backend.public_listener_count",
    )
    _sha(backend["proof_sha256"], path="evidence.runtime.backend.proof_sha256")
    _fresh_timestamp(
        backend["completed_at"],
        path="evidence.runtime.backend.completed_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )

    restart = _object(
        runtime["restart_contract"],
        path="evidence.runtime.restart_contract",
        keys={"result", "proof_sha256", "completed_at"},
    )
    _passed(restart["result"], path="evidence.runtime.restart_contract.result")
    _sha(
        restart["proof_sha256"],
        path="evidence.runtime.restart_contract.proof_sha256",
    )
    _fresh_timestamp(
        restart["completed_at"],
        path="evidence.runtime.restart_contract.completed_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )


def _validate_tenant_audit(
    value: Any,
    *,
    now: datetime,
    oldest: datetime,
    attested_at: datetime,
) -> None:
    row = _object(
        value,
        path="evidence.tenant_audit",
        keys={"cross_workspace_binding_count", "report_sha256", "completed_at"},
    )
    _zero(
        row["cross_workspace_binding_count"],
        path="evidence.tenant_audit.cross_workspace_binding_count",
    )
    _sha(row["report_sha256"], path="evidence.tenant_audit.report_sha256")
    _fresh_timestamp(
        row["completed_at"],
        path="evidence.tenant_audit.completed_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )


def _validate_sftp(
    value: Any,
    *,
    expected_sftp_sha: str,
    now: datetime,
    oldest: datetime,
    attested_at: datetime,
) -> tuple[str, str]:
    row = _object(
        value,
        path="evidence.sftp",
        keys={
            "image_revision",
            "runtime_ready_receipt_sha256",
            "runtime_ready_at",
            "authentication_result",
            "subsystem_result",
            "revocation_result",
            "post_revocation_authentication_result",
            "ledger_result",
            "postgres_ledger_receipt_sha256",
            "postgres_ledger_completed_at",
            "credential_fingerprint_sha256",
            "proof_sha256",
            "completed_at",
        },
    )
    image_revision = _sha(
        row["image_revision"],
        path="evidence.sftp.image_revision",
        git=True,
    )
    if image_revision != expected_sftp_sha:
        raise ReleaseAAttestationError(
            "evidence.sftp.image_revision differs from the expected SFTP SHA"
        )
    _passed(row["authentication_result"], path="evidence.sftp.authentication_result")
    _passed(row["subsystem_result"], path="evidence.sftp.subsystem_result")
    _passed(row["revocation_result"], path="evidence.sftp.revocation_result")
    _exact_text(
        row["post_revocation_authentication_result"],
        expected="denied",
        path="evidence.sftp.post_revocation_authentication_result",
    )
    _passed(row["ledger_result"], path="evidence.sftp.ledger_result")
    _sha(
        row["postgres_ledger_receipt_sha256"],
        path="evidence.sftp.postgres_ledger_receipt_sha256",
    )
    _fresh_timestamp(
        row["postgres_ledger_completed_at"],
        path="evidence.sftp.postgres_ledger_completed_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )
    _sha(
        row["runtime_ready_receipt_sha256"],
        path="evidence.sftp.runtime_ready_receipt_sha256",
    )
    _fresh_timestamp(
        row["runtime_ready_at"],
        path="evidence.sftp.runtime_ready_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )
    credential_fingerprint = _sha(
        row["credential_fingerprint_sha256"],
        path="evidence.sftp.credential_fingerprint_sha256",
    )
    _sha(row["proof_sha256"], path="evidence.sftp.proof_sha256")
    _fresh_timestamp(
        row["completed_at"],
        path="evidence.sftp.completed_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )
    ready_at = _timestamp(row["runtime_ready_at"], path="evidence.sftp.runtime_ready_at")
    ledger_at = _timestamp(
        row["postgres_ledger_completed_at"],
        path="evidence.sftp.postgres_ledger_completed_at",
    )
    completed_at = _timestamp(row["completed_at"], path="evidence.sftp.completed_at")
    if not ready_at <= ledger_at <= completed_at:
        raise ReleaseAAttestationError("evidence.sftp chronology is invalid")
    return credential_fingerprint, row["completed_at"]


def _validate_principals(
    value: Any,
    *,
    now: datetime,
    oldest: datetime,
    attested_at: datetime,
    expected_sftp_credential_fingerprint: str,
    expected_sftp_completed_at: str,
) -> None:
    """Require a non-personal browser canary distinct from disposable SFTP."""

    principals = _object(
        value,
        path="evidence.principals",
        keys={"browser_canary", "sftp_canary"},
    )
    browser = _object(
        principals["browser_canary"],
        path="evidence.principals.browser_canary",
        keys={
            "principal_kind",
            "non_personal",
            "least_privilege",
            "credential_fingerprint_sha256",
            "permission_probe_sha256",
            "permission_probe_result",
            "completed_at",
        },
    )
    if (
        not isinstance(browser["principal_kind"], str)
        or _PRINCIPAL_KIND_RE.fullmatch(browser["principal_kind"]) is None
        or browser["principal_kind"] not in {"service_account", "automation_client"}
    ):
        raise ReleaseAAttestationError(
            "browser canary must use a service_account or automation_client"
        )
    _true(browser["non_personal"], path="evidence.principals.browser_canary.non_personal")
    _true(
        browser["least_privilege"],
        path="evidence.principals.browser_canary.least_privilege",
    )
    browser_fingerprint = _sha(
        browser["credential_fingerprint_sha256"],
        path="evidence.principals.browser_canary.credential_fingerprint_sha256",
    )
    _sha(
        browser["permission_probe_sha256"],
        path="evidence.principals.browser_canary.permission_probe_sha256",
    )
    _passed(
        browser["permission_probe_result"],
        path="evidence.principals.browser_canary.permission_probe_result",
    )
    _fresh_timestamp(
        browser["completed_at"],
        path="evidence.principals.browser_canary.completed_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )

    sftp = _object(
        principals["sftp_canary"],
        path="evidence.principals.sftp_canary",
        keys={
            "principal_kind",
            "disposable",
            "credential_fingerprint_sha256",
            "completed_at",
        },
    )
    _exact_text(
        sftp["principal_kind"],
        expected="disposable_sftp",
        path="evidence.principals.sftp_canary.principal_kind",
    )
    _true(sftp["disposable"], path="evidence.principals.sftp_canary.disposable")
    sftp_fingerprint = _sha(
        sftp["credential_fingerprint_sha256"],
        path="evidence.principals.sftp_canary.credential_fingerprint_sha256",
    )
    if sftp_fingerprint != expected_sftp_credential_fingerprint:
        raise ReleaseAAttestationError(
            "SFTP canary credential fingerprint differs from the SFTP proof"
        )
    if browser_fingerprint == sftp_fingerprint:
        raise ReleaseAAttestationError(
            "browser and SFTP canary credentials must be distinct"
        )
    _fresh_timestamp(
        sftp["completed_at"],
        path="evidence.principals.sftp_canary.completed_at",
        now=now,
        oldest=oldest,
        attested_at=attested_at,
    )
    if sftp["completed_at"] != expected_sftp_completed_at:
        raise ReleaseAAttestationError(
            "SFTP canary completion differs from the SFTP proof"
        )


def verify_attestation(
    payload: Any,
    *,
    expected_release_a_sha: str,
    expected_sftp_sha: str,
    expected_hostname: str,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now: datetime | None = None,
    attestation_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate an exact Release A gate and return a bounded content-free receipt."""

    expected_sha = _sha(expected_release_a_sha, path="expected Release A SHA", git=True)
    expected_sftp = _sha(expected_sftp_sha, path="expected SFTP SHA", git=True)
    expected_host = _validate_hostname(expected_hostname, path="expected hostname")
    max_age = _validate_max_age(max_age_hours)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ReleaseAAttestationError("verification time must include a timezone")
    current = current.astimezone(UTC)

    root = _object(payload, path="attestation", keys=_TOP_LEVEL_KEYS)
    if (
        isinstance(root["schema_version"], bool)
        or root["schema_version"] != SCHEMA_VERSION
    ):
        raise ReleaseAAttestationError("attestation.schema_version must equal four")
    _exact_text(root["kind"], expected=ATTESTATION_KIND, path="attestation.kind")
    _passed(root["result"], path="attestation.result")
    _exact_text(
        root["environment"], expected=ENVIRONMENT, path="attestation.environment"
    )
    if (
        _sha(root["release_a_sha"], path="attestation.release_a_sha", git=True)
        != expected_sha
    ):
        raise ReleaseAAttestationError(
            "attestation.release_a_sha differs from the expected SHA"
        )
    if (
        _sha(root["sftp_release_sha"], path="attestation.sftp_release_sha", git=True)
        != expected_sftp
    ):
        raise ReleaseAAttestationError(
            "attestation.sftp_release_sha differs from the expected SFTP SHA"
        )
    hostname = _validate_hostname(root["hostname"], path="attestation.hostname")
    if hostname != expected_host:
        raise ReleaseAAttestationError(
            "attestation.hostname differs from the expected hostname"
        )

    attested_at = _timestamp(root["attested_at"], path="attestation.attested_at")
    oldest = current - max_age
    if attested_at < oldest:
        raise ReleaseAAttestationError("attestation.attested_at is stale")
    if attested_at > current + MAX_CLOCK_SKEW:
        raise ReleaseAAttestationError(
            "attestation.attested_at is too far in the future"
        )

    evidence = _object(
        root["evidence"], path="attestation.evidence", keys=_EVIDENCE_KEYS
    )
    time_context = {"now": current, "oldest": oldest, "attested_at": attested_at}
    _validate_backups(evidence["off_vm_backups"], **time_context)
    _validate_canaries(evidence["canaries"], **time_context)
    _validate_data_integrity(evidence["data_integrity"], **time_context)
    _validate_minio(evidence["minio"], **time_context)
    _validate_qdrant(evidence["qdrant"], **time_context)
    _validate_runtime(evidence["runtime"], **time_context)
    _validate_tenant_audit(evidence["tenant_audit"], **time_context)
    sftp_fingerprint, sftp_completed_at = _validate_sftp(
        evidence["sftp"],
        expected_sftp_sha=expected_sftp,
        **time_context,
    )
    _validate_principals(
        evidence["principals"],
        expected_sftp_credential_fingerprint=sftp_fingerprint,
        expected_sftp_completed_at=sftp_completed_at,
        **time_context,
    )

    canonical = _canonical_json(root)
    input_digest = attestation_sha256 or _sha256(canonical)
    _sha(input_digest, path="attestation byte digest")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "kind": RECEIPT_KIND,
        "result": "passed",
        "environment": ENVIRONMENT,
        "release_a_sha": expected_sha,
        "sftp_release_sha": expected_sftp,
        "hostname_sha256": _sha256(expected_host.encode("utf-8")),
        "attestation_sha256": input_digest,
        "evidence_sha256": _sha256(_canonical_json(evidence)),
        "verified_at": _utc_text(current),
        "fresh_until": _utc_text(attested_at + max_age),
    }
    if len(_canonical_json(receipt)) > MAX_RECEIPT_BYTES:
        raise ReleaseAAttestationError("verification receipt exceeds its size bound")
    return receipt


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseAAttestationError(
                "attestation contains a duplicate JSON field"
            )
        result[key] = value
    return result


def load_attestation_file(
    path: Path,
    *,
    expected_uid: int | None = None,
) -> tuple[Any, str]:
    """Read one private, single-link regular file without following symlinks."""

    uid = os.geteuid() if expected_uid is None else expected_uid
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ReleaseAAttestationError(
            "attestation file is unavailable or unsafe"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ReleaseAAttestationError("attestation path is not a regular file")
        if before.st_nlink != 1:
            raise ReleaseAAttestationError("attestation file must not be hard-linked")
        permissions = stat.S_IMODE(before.st_mode)
        if permissions & ~0o600 or not permissions & 0o400:
            raise ReleaseAAttestationError(
                "attestation file mode is too open or unreadable"
            )
        if before.st_uid != uid:
            raise ReleaseAAttestationError("attestation file owner is unexpected")
        if before.st_size > MAX_INPUT_BYTES:
            raise ReleaseAAttestationError("attestation file exceeds one MiB")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, MAX_INPUT_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_INPUT_BYTES:
                raise ReleaseAAttestationError("attestation file exceeds one MiB")
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_gid,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_gid,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after:
        raise ReleaseAAttestationError("attestation file changed while being read")
    content = b"".join(chunks)
    if not content or len(content) != before.st_size:
        raise ReleaseAAttestationError(
            "attestation file is empty or was read incompletely"
        )
    try:
        payload = json.loads(
            content.decode("utf-8"), object_pairs_hook=_no_duplicate_object
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseAAttestationError(
            "attestation file is not valid UTF-8 JSON"
        ) from exc
    return payload, _sha256(content)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify", help="verify an operator-supplied Release A gate"
    )
    verify.add_argument("--attestation", type=Path, required=True)
    verify.add_argument("--expected-release-a-sha", required=True)
    verify.add_argument("--expected-sftp-sha", required=True)
    verify.add_argument("--expected-hostname", required=True)
    verify.add_argument(
        "--max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload, byte_digest = load_attestation_file(args.attestation)
        receipt = verify_attestation(
            payload,
            expected_release_a_sha=args.expected_release_a_sha,
            expected_sftp_sha=args.expected_sftp_sha,
            expected_hostname=args.expected_hostname,
            max_age_hours=args.max_age_hours,
            attestation_sha256=byte_digest,
        )
    except ReleaseAAttestationError as exc:
        print(f"Release A attestation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
