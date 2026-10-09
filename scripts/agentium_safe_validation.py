#!/usr/bin/env python3
"""Build and verify the evidence-bound validation gate for a VM deployment.

The resulting ``validation.json`` contains hashes and aggregate outcomes only.
It never copies proof payloads, JUnit testcase names, Secure Deposit paths, or
credentials into the release artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 2
MAX_AGE_SECONDS = 60 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60
MAX_PROOF_BYTES = 32 * 1024 * 1024
MAX_STORAGE_BYTES = 96 * 1024 * 1024
MAX_RUNTIME_ENV_MANIFEST_BYTES = 1024 * 1024
MAX_RUNTIME_ENV_FILE_BYTES = 8 * 1024 * 1024
MAX_DEPLOYMENT_METADATA_BYTES = 128 * 1024
MAX_DATABASE_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_DATABASE_LEDGER_BYTES = 1024 * 1024
MAX_CONTROLLED_DATABASE_INVOCATIONS = 10_000
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
WORKSPACE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{5,95}$")
ALEMBIC_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+,-]{0,255}$")
CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{12,64}$")
DOCKER_CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
DOCKER_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SSH_FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{20,}={0,2}$")
STORAGE_PROFILE = "agentium-storage-attestation-v3"
STORAGE_EXACT_COMPARISON_PROFILE = "agentium-storage-exact-comparison-v1"
RUNTIME_ENV_SCHEMA_VERSION = 3
RUNTIME_ENV_PROFILE = "agentium-runtime-env-bundle-v3"
RUNTIME_ENV_CHECKS = {
    "object_store_minio_credentials_separated": True,
    "placeholder_secrets_rejected": True,
    "production_credentials_explicit": True,
    "source_files_private": True,
    "storage_paths_explicit": True,
    "systemd_revision_bound": True,
}
RUNTIME_ENV_ROLES = frozenset(
    {"compose_main", "application", "qdrant", "keycloak", "systemd"}
)
RUNTIME_ENV_REFERENCE_KEYS = {
    "application": "AGENTIUM_ENV_FILE",
    "qdrant": "AGENTIUM_QDRANT_ENV_FILE",
    "keycloak": "AGENTIUM_KEYCLOAK_ENV_FILE",
    "hub": "AGENTIUM_HUB_ENV_FILE",
}
DEPLOYMENT_METADATA_KEYS = frozenset(
    {
        "format",
        "deployment_id",
        "branch",
        "candidate_sha",
        "previous_sha",
        "sftp_release_sha",
        "sftp_image_id",
        "previous_database_revision",
        "canary_workspace_ids",
        "workspace_targets_sha256",
        "env_manifest_sha256",
        "release_a_attestation_sha256",
        "release_a_receipt_sha256",
        "release_a_manifest_sha256",
        "release_a_review_policy_sha256",
        "release_a_manifest_receipt_sha256",
        "created_at",
    }
)
DEPLOYMENT_METADATA_ARTIFACTS = {
    "workspace_targets_sha256": "workspace-targets.json",
    "release_a_attestation_sha256": "release-a-attestation.json",
    "release_a_receipt_sha256": "release-a-verification-receipt.json",
    "release_a_manifest_sha256": "release-a-diff-manifest.json",
    "release_a_review_policy_sha256": "release-a-semantic-review.json",
    "release_a_manifest_receipt_sha256": (
        "release-a-manifest-verification-receipt.json"
    ),
}
REQUIRED_STORAGE_CONTAINERS = frozenset(
    {"agentium-pg", "qdrant", "agentium-minio", "agentium-sftp"}
)
STABLE_MOUNT_FIELDS = (
    "source",
    "normalized_source",
    "expected_source",
    "source_matches_expected",
    "target",
    "fstype",
    "device_id",
)
OBJECT_STORE_ENTRY_FIELDS = ("path_sha256", "size", "content_sha256")
MINIO_ENTRY_FIELDS = (
    "object_id_sha256",
    "version_id_sha256",
    "size",
    "etag_sha256",
    "last_modified",
    "is_latest",
    "delete_marker",
)
OBJECT_STORE_MODIFICATION_FIELDS = (
    "path_sha256",
    "before_entry_sha256",
    "after_entry_sha256",
)
MINIO_MODIFICATION_FIELDS = (
    "object_id_sha256",
    "version_id_sha256",
    "before_entry_sha256",
    "after_entry_sha256",
)
EXPECTED_STORAGE_ADDITIONS_CHECKS = frozenset(
    {
        "secure_deposit.aggregate",
        "object_store_bindings",
        "qdrant.inventory",
        "container_mounts",
        "object_store.algorithm",
        "object_store.entry_fields",
        "object_store.preexisting_entries_preserved",
        "minio.bucket_id_sha256",
        "minio.versioning_status",
        "minio.algorithm",
        "minio.entry_fields",
        "minio.preexisting_entries_preserved",
        "minio.preexisting_object_keys_not_reversioned",
        "minio.no_delete_marker_additions",
        "minio.delete_markers_unchanged",
    }
) | frozenset(
    f"mounts.{mount}.{field}"
    for mount in ("data", "secure_deposit")
    for field in STABLE_MOUNT_FIELDS
)
EXPECTED_STORAGE_COMPARISON_CHECKS = frozenset(
    {
        "secure_deposit.aggregate",
        "object_store_bindings",
        "object_store.algorithm",
        "object_store.files",
        "object_store.bytes",
        "object_store.content_manifest_sha256",
        "minio.algorithm",
        "minio.bucket_id_sha256",
        "minio.versioning_status",
        "minio.versions",
        "minio.latest_versions",
        "minio.delete_markers",
        "minio.bytes",
        "minio.inventory_sha256",
        "qdrant.collections",
        "qdrant.aliases",
        "qdrant.inventory",
        "container_mounts",
    }
) | frozenset(
    f"mounts.{mount}.{field}"
    for mount in ("data", "secure_deposit")
    for field in STABLE_MOUNT_FIELDS
)

PROOF_CHECKS = ("provenance", "showcase", "andritz", "sentinel", "octocity")
REQUIRED_CHAT_LINEAGE_CHECKS = frozenset(
    {
        "workspace_exists",
        "workspace_is_andritz",
        "workspace_family_is_andritz",
        "run_exists",
        "run_completed",
        "trigger_is_strict_agentic_chat",
        "input_marker_present",
        "system_exists",
        "system_is_active_andritz_system",
        "system_type_is_agentic_chat",
        "system_flow_variant_is_agentic_chat",
        "run_flow_variant_matches_system",
        "migration_marker_targets_system",
        "run_capability_matches_system",
        "capability_exists",
        "capability_is_visible_to_andritz",
        "chat_execution_routes_agentic",
        "chat_execution_targets_system",
        "chat_execution_variant_is_agentic_chat",
        "system_retrieval_contract_is_andritz",
        "run_retrieval_contract_is_andritz",
        "knowledge_collection_exists",
        "knowledge_collection_is_ready",
        "knowledge_collection_has_chunks",
    }
)
QDRANT_ENTRIES = (
    "qdrant_preflight_barrier",
    "qdrant_validation_barrier",
    "qdrant_backend_probe",
    "qdrant_worker_probe",
    "qdrant_post_canary_barrier",
)
DATABASE_ENTRIES = (
    "database_canary_baseline",
    "database_post_canary",
    "database_final",
    "database_post_canary_comparison",
)
SFTP_ENTRIES = ("sftp_closed_before", "sftp_closed_after")
KEYCLOAK_VOLATILE_TABLES = frozenset(
    {
        "admin_event_entity",
        "authentication_session",
        "authentication_session_auth_note",
        "authentication_session_client_note",
        "authentication_session_execution",
        "client_session",
        "client_session_auth_status",
        "client_session_note",
        "event_entity",
        "offline_client_session",
        "offline_user_session",
        "user_session",
        "user_session_note",
    }
)
EXPECTED_DATABASE_CHECKS = frozenset(
    {
        "schema_unchanged",
        "baseline_inventory_bound",
        "post_canary_inventory_bound",
        "final_inventory_bound",
        "preexisting_business_rows_preserved",
        "preexisting_business_rows_unmodified",
        "no_business_deletions",
        "users_only_last_login_normalized",
        "keycloak_volatility_limited",
        "controlled_run_addition_exact",
        "controlled_invocations_addition_exact",
        "no_other_business_additions",
        "navigation_audit_additions_canonical",
        "ledger_lineage_exact",
    }
)
DATABASE_SCHEMA_VERSION = 2
DATABASE_INVENTORY_PROFILE = "agentium-postgresql-row-inventory-v2"
DATABASE_COMPARISON_PROFILE = "agentium-controlled-canary-postgresql-v2"
DATABASE_DETAIL_POLICY = (
    "controlled-ledger-rows-and-navigation-workspace-aggregates-only"
)
DATABASE_ACCUMULATOR_ALGORITHM = "sha256-domain-sum-mod-2^256-v1"
DATABASE_ACCUMULATOR_DOMAINS = {
    "primary_key": "agentium.postgresql.multiset.primary-key.v1",
    "row_state": "agentium.postgresql.multiset.row-state.v1",
}
DATABASE_ACCUMULATOR_MODULUS = 1 << 256
WORKSPACE_TARGET_SELECTORS = {
    "showcase": {"showcase_seed": True},
    "andritz": {"family": "andritz"},
    "sentinel": {
        "family": "sentinel_ci",
        "mission_room_enabled": True,
        "mission_room_profile": "sentinel_government_v1",
        "assistant_profile": "vigie_executive",
    },
    "octocity": {
        "family": "generic",
        "mission_room_enabled": True,
        "mission_room_profile": "octocity_institutional_v1",
        "assistant_profile": "octave_executive",
    },
}
SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REQUIRED_CHECKS = (
    "runtime_env",
    "provenance",
    "storage",
    "sftp_closed_boundary",
    "qdrant_write_barrier",
    "database_integrity",
    "showcase",
    "andritz",
    "sentinel",
    "octocity",
)
STORAGE_ENTRIES = ("storage_before", "storage_after", "storage_comparison")
ALL_ENTRIES = (
    *PROOF_CHECKS,
    *STORAGE_ENTRIES,
    *SFTP_ENTRIES,
    *QDRANT_ENTRIES,
    *DATABASE_ENTRIES,
)
ANDRITZ_BUNDLE_INPUTS = {
    "workspace_junit": "andritz.xml",
    "spl_probe": "spl-probe.json",
    "chat_delivery": "controlled-chat-state.json",
    "chat_ledger": "chat-ledger.json",
    "runtime_bindings": "runtime-bindings.json",
    "storage_canary_comparison": "../storage-canary-comparison.json",
}
TENANT_BUNDLE_INPUTS = {
    "sentinel": {
        "workspace_junit": "sentinel.xml",
        "runtime_bindings": "runtime-bindings.json",
    },
    "octocity": {
        "workspace_junit": "octocity.xml",
        "runtime_bindings": "runtime-bindings.json",
    },
}
EXPECTED_TENANT_TEST_TITLES = {
    "sentinel": "Sentinel workspace keeps its immersive Mission Room shell",
    "octocity": "Octocity workspace keeps its immersive Mission Room shell",
}
EXPECTED_ANDRITZ_TEST_TITLES = frozenset(
    {
        "Andritz business preview exposes the three-app shell",
        "the three Andritz surfaces survive deep links, history and reload",
        "a forced access-token expiry retries inside the selected workspace",
        "business preview redirects advanced routes while admin mode keeps the full cockpit",
        "deployed Andritz profile, entitlements and active Systems match the Lot 4 contract",
        "resolved navigation is persisted with canonical routes and no user identity",
    }
)
FORBIDDEN_CONTENT_KEYS = frozenset(
    {
        "query",
        "answer",
        "response",
        "citation",
        "citations",
        "source",
        "sources",
        "content",
        "text",
    }
)


class SafeValidationError(ValueError):
    """Raised when deployment validation evidence is incomplete or unsafe."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: object, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise SafeValidationError(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise SafeValidationError(f"{label} timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def canonical_sha256(value: object) -> str:
    """Hash JSON with the same canonical form used by the deployment gate."""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_identity(
    deployment_id: str, candidate_sha: str, database_revision: str
) -> None:
    if DEPLOYMENT_ID_RE.fullmatch(deployment_id) is None:
        raise SafeValidationError("deployment-id is invalid")
    if FULL_SHA_RE.fullmatch(candidate_sha) is None:
        raise SafeValidationError("candidate SHA must be a full lowercase Git SHA")
    if ALEMBIC_REVISION_RE.fullmatch(database_revision) is None:
        raise SafeValidationError("Alembic revision is invalid")


def _assert_not_writable_by_others(path: Path, *, label: str) -> os.stat_result:
    try:
        details = path.stat()
    except OSError as exc:
        raise SafeValidationError(f"{label} is unavailable") from exc
    if details.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise SafeValidationError(f"{label} is group/world writable")
    return details


def _deployment_root(path: Path) -> Path:
    try:
        if path.is_symlink():
            raise SafeValidationError("deployment-dir cannot be a symlink")
        root = path.resolve(strict=True)
    except OSError as exc:
        raise SafeValidationError("deployment-dir is unavailable") from exc
    if not root.is_dir():
        raise SafeValidationError("deployment-dir must be a directory")
    _assert_not_writable_by_others(root, label="deployment-dir")
    return root


def _read_private_regular(
    path: Path,
    *,
    label: str,
    owner: tuple[int, int],
    max_bytes: int,
) -> tuple[bytes, os.stat_result]:
    """Read one private transaction file without following or racing a link."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SafeValidationError(f"{label} is unavailable or unsafe") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or (before.st_uid, before.st_gid) != owner
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > max_bytes
        ):
            raise SafeValidationError(f"{label} is not a private deployment file")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
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
    content = b"".join(chunks)
    if identity_before != identity_after or len(content) != after.st_size:
        raise SafeValidationError(f"{label} changed while being read")
    return content, after


def _deployment_metadata_env_digest(
    root: Path,
    *,
    owner: tuple[int, int],
    deployment_id: str,
    candidate_sha: str,
    sftp_sha: str,
) -> str:
    raw, _ = _read_private_regular(
        root / "metadata.tsv",
        label="deployment metadata",
        owner=owner,
        max_bytes=MAX_DEPLOYMENT_METADATA_BYTES,
    )
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SafeValidationError("deployment metadata is not UTF-8") from exc
    values: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("\t")
        if (
            not separator
            or not key
            or "\t" in value
            or key in values
            or re.fullmatch(r"[a-z][a-z0-9_]*", key) is None
        ):
            raise SafeValidationError("deployment metadata is malformed")
        values[key] = value
    if set(values) != DEPLOYMENT_METADATA_KEYS or values.get("format") != "5":
        raise SafeValidationError("deployment metadata schema differs")
    if (
        values.get("deployment_id") != deployment_id
        or values.get("branch") != "demo/agentic"
        or values.get("candidate_sha") != candidate_sha
        or values.get("sftp_release_sha") != sftp_sha
    ):
        raise SafeValidationError("deployment metadata identity differs")
    if (
        FULL_SHA_RE.fullmatch(values.get("previous_sha", "")) is None
        or FULL_SHA_RE.fullmatch(values.get("sftp_release_sha", "")) is None
        or DOCKER_IMAGE_ID_RE.fullmatch(values.get("sftp_image_id", "")) is None
        or re.fullmatch(r"[A-Za-z0-9_]+", values.get("previous_database_revision", ""))
        is None
    ):
        raise SafeValidationError("deployment metadata release lineage is invalid")
    workspace_ids = values.get("canary_workspace_ids", "").split(",")
    if (
        len(workspace_ids) != 4
        or workspace_ids != sorted(set(workspace_ids))
        or any(
            re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                workspace_id,
            )
            is None
            for workspace_id in workspace_ids
        )
    ):
        raise SafeValidationError("deployment metadata workspace inventory is invalid")
    try:
        created_at = datetime.strptime(
            values.get("created_at", ""), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SafeValidationError("deployment metadata timestamp is invalid") from exc
    if created_at.year < 2025:
        raise SafeValidationError("deployment metadata timestamp is implausible")

    for digest_key, filename in DEPLOYMENT_METADATA_ARTIFACTS.items():
        expected_digest = values.get(digest_key, "")
        if SHA256_RE.fullmatch(expected_digest) is None:
            raise SafeValidationError(
                f"deployment metadata {digest_key} digest is invalid"
            )
        artifact, _ = _read_private_regular(
            root / filename,
            label=f"deployment metadata artifact {filename}",
            owner=owner,
            max_bytes=MAX_PROOF_BYTES,
        )
        if hashlib.sha256(artifact).hexdigest() != expected_digest:
            raise SafeValidationError(
                f"deployment metadata artifact {filename} digest differs"
            )
    digest = values.get("env_manifest_sha256", "")
    if SHA256_RE.fullmatch(digest) is None:
        raise SafeValidationError("deployment metadata runtime env digest is invalid")
    return digest


def _runtime_env_attestation(
    root: Path,
    *,
    deployment_id: str,
    candidate_sha: str,
    sftp_sha: str,
) -> dict[str, Any]:
    """Reproduce a content-free attestation of the frozen runtime environment."""

    root_stat = root.stat()
    owner = (root_stat.st_uid, root_stat.st_gid)
    expected_manifest_sha256 = _deployment_metadata_env_digest(
        root,
        owner=owner,
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
        sftp_sha=sftp_sha,
    )
    bundle = root / "runtime-env"
    try:
        bundle_stat = bundle.lstat()
    except OSError as exc:
        raise SafeValidationError("runtime env bundle is unavailable") from exc
    if (
        not stat.S_ISDIR(bundle_stat.st_mode)
        or bundle.is_symlink()
        or stat.S_IMODE(bundle_stat.st_mode) != 0o700
        or (bundle_stat.st_uid, bundle_stat.st_gid) != owner
    ):
        raise SafeValidationError(
            "runtime env bundle is not a private deployment directory"
        )

    manifest_raw, manifest_stat = _read_private_regular(
        bundle / "manifest.json",
        label="runtime env manifest",
        owner=owner,
        max_bytes=MAX_RUNTIME_ENV_MANIFEST_BYTES,
    )
    manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
    if manifest_sha256 != expected_manifest_sha256:
        raise SafeValidationError(
            "runtime env manifest digest differs from deployment metadata"
        )
    try:
        manifest = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeValidationError("runtime env manifest is invalid JSON") from exc
    expected_manifest_keys = {
        "schema_version",
        "profile",
        "candidate_sha",
        "deployment_id",
        "files",
        "roles",
        "effective_compose_file",
        "effective_references",
        "checks",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_manifest_keys:
        raise SafeValidationError("runtime env manifest shape is invalid")
    if (
        manifest.get("schema_version") != RUNTIME_ENV_SCHEMA_VERSION
        or manifest.get("profile") != RUNTIME_ENV_PROFILE
        or manifest.get("candidate_sha") != candidate_sha
        or manifest.get("deployment_id") != deployment_id
        or manifest.get("checks") != RUNTIME_ENV_CHECKS
    ):
        raise SafeValidationError("runtime env manifest identity differs")

    files = manifest.get("files")
    roles = manifest.get("roles")
    references = manifest.get("effective_references")
    effective_name = manifest.get("effective_compose_file")
    if (
        not isinstance(files, dict)
        or not isinstance(roles, dict)
        or not isinstance(references, dict)
        or not RUNTIME_ENV_ROLES <= set(roles) <= RUNTIME_ENV_ROLES | {"hub"}
        or effective_name != "compose.effective.env"
    ):
        raise SafeValidationError("runtime env manifest contract is invalid")

    role_files: dict[str, str] = {}
    for role, contract in roles.items():
        if not isinstance(contract, dict) or set(contract) != {
            "file",
            "source_path_sha256",
            "source_device",
            "source_inode",
            "source_mtime_ns",
        }:
            raise SafeValidationError("runtime env role contract is invalid")
        filename = contract.get("file")
        source_digest = contract.get("source_path_sha256")
        if (
            not isinstance(filename, str)
            or re.fullmatch(r"source-[0-9]{3}\.env", filename) is None
            or not isinstance(source_digest, str)
            or SHA256_RE.fullmatch(source_digest) is None
        ):
            raise SafeValidationError("runtime env role identity is invalid")
        for field in ("source_device", "source_inode", "source_mtime_ns"):
            value = contract.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise SafeValidationError("runtime env role source stat is invalid")
        role_files[role] = filename

    expected_references = {
        key: role_files[role]
        for role, key in RUNTIME_ENV_REFERENCE_KEYS.items()
        if role in role_files
    }
    if references != expected_references:
        raise SafeValidationError("runtime env effective references differ")
    expected_filenames = {*role_files.values(), str(effective_name)}
    if set(files) != expected_filenames:
        raise SafeValidationError("runtime env file inventory is invalid")
    try:
        actual_filenames = {entry.name for entry in bundle.iterdir()}
    except OSError as exc:
        raise SafeValidationError("runtime env bundle cannot be inventoried") from exc
    if actual_filenames != {"manifest.json", *expected_filenames}:
        raise SafeValidationError("runtime env bundle has unexpected files")

    file_identities = {(manifest_stat.st_dev, manifest_stat.st_ino)}
    for filename, contract in files.items():
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not isinstance(contract, dict)
            or set(contract) != {"sha256", "size"}
            or not isinstance(contract.get("sha256"), str)
            or SHA256_RE.fullmatch(contract["sha256"]) is None
            or not isinstance(contract.get("size"), int)
            or isinstance(contract.get("size"), bool)
            or contract["size"] <= 0
            or contract["size"] > MAX_RUNTIME_ENV_FILE_BYTES
        ):
            raise SafeValidationError("runtime env file contract is invalid")
        content, details = _read_private_regular(
            bundle / filename,
            label="runtime env file",
            owner=owner,
            max_bytes=MAX_RUNTIME_ENV_FILE_BYTES,
        )
        identity = (details.st_dev, details.st_ino)
        if identity in file_identities:
            raise SafeValidationError("runtime env files reuse an inode")
        file_identities.add(identity)
        if (
            contract["size"] != len(content)
            or contract["sha256"] != hashlib.sha256(content).hexdigest()
        ):
            raise SafeValidationError("runtime env file differs from its manifest")

    return {
        "profile": RUNTIME_ENV_PROFILE,
        "schema_version": RUNTIME_ENV_SCHEMA_VERSION,
        "manifest_sha256": manifest_sha256,
        "candidate_sha_checked": True,
        "deployment_id_checked": True,
        "metadata_digest_checked": True,
        "private_identity_checked": True,
        "file_count": len(files),
        "role_count": len(roles),
    }


def _workspace_target_hashes(
    root: Path,
    *,
    deployment_id: str,
    candidate_sha: str,
) -> dict[str, str]:
    """Load the private transaction-bound workspace identities without fixed slugs."""

    owner = (root.stat().st_uid, root.stat().st_gid)
    metadata_raw, _ = _read_private_regular(
        root / "metadata.tsv",
        label="deployment metadata",
        owner=owner,
        max_bytes=MAX_DEPLOYMENT_METADATA_BYTES,
    )
    try:
        metadata_lines = metadata_raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise SafeValidationError("deployment metadata is not UTF-8") from exc
    metadata: dict[str, str] = {}
    for line in metadata_lines:
        key, separator, value = line.partition("\t")
        if not separator or not key or "\t" in value or key in metadata:
            raise SafeValidationError("deployment metadata is malformed")
        metadata[key] = value
    if (
        metadata.get("candidate_sha") != candidate_sha
        or metadata.get("deployment_id") != deployment_id
    ):
        raise SafeValidationError("workspace target metadata identity differs")
    metadata_ids = metadata.get("canary_workspace_ids", "").split(",")
    if (
        len(metadata_ids) != 4
        or metadata_ids != sorted(set(metadata_ids))
        or any(UUID_RE.fullmatch(value) is None for value in metadata_ids)
    ):
        raise SafeValidationError("workspace target metadata ids are invalid")

    raw, _ = _read_private_regular(
        root / "workspace-targets.json",
        label="workspace targets",
        owner=owner,
        max_bytes=MAX_PROOF_BYTES,
    )
    expected_digest = metadata.get("workspace_targets_sha256", "")
    if (
        SHA256_RE.fullmatch(expected_digest) is None
        or hashlib.sha256(raw).hexdigest() != expected_digest
    ):
        raise SafeValidationError("workspace targets digest differs")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeValidationError("workspace targets are invalid JSON") from exc
    expected_keys = {
        "schema_version",
        "profile",
        "candidate_sha",
        "deployment_id",
        "selection",
        "operator_workspace_ids",
        "targets",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise SafeValidationError("workspace target schema differs")
    if (
        payload.get("schema_version") != 2
        or payload.get("profile") != "agentium-workspace-target-gate-v2"
        or payload.get("candidate_sha") != candidate_sha
        or payload.get("deployment_id") != deployment_id
        or payload.get("selection") != "explicit_operator_workspace_ids"
        or payload.get("operator_workspace_ids") != metadata_ids
    ):
        raise SafeValidationError("workspace target transaction identity differs")
    targets = payload.get("targets")
    if not isinstance(targets, dict) or set(targets) != set(WORKSPACE_TARGET_SELECTORS):
        raise SafeValidationError("workspace target roles differ")

    ids: list[str] = []
    slugs: list[str] = []
    result: dict[str, str] = {}
    for role, expected_selector in WORKSPACE_TARGET_SELECTORS.items():
        target = targets.get(role)
        if not isinstance(target, dict) or set(target) != {
            "workspace_id",
            "workspace_slug",
            "selector",
        }:
            raise SafeValidationError(f"workspace target {role} is malformed")
        workspace_id = target.get("workspace_id")
        workspace_slug = target.get("workspace_slug")
        if (
            not isinstance(workspace_id, str)
            or UUID_RE.fullmatch(workspace_id) is None
            or not isinstance(workspace_slug, str)
            or WORKSPACE_SLUG_RE.fullmatch(workspace_slug) is None
            or target.get("selector") != expected_selector
        ):
            raise SafeValidationError(f"workspace target {role} identity differs")
        ids.append(workspace_id)
        slugs.append(workspace_slug)
        result[workspace_slug] = canonical_sha256([workspace_id])
    if (
        sorted(ids) != metadata_ids
        or len(set(ids)) != 4
        or len(set(slugs)) != 4
        or len(result) != 4
    ):
        raise SafeValidationError("workspace target identities are ambiguous")
    return result


def _entry_path(
    path: Path,
    root: Path,
    *,
    label: str,
    max_bytes: int = MAX_PROOF_BYTES,
) -> tuple[Path, str]:
    try:
        if path.is_symlink():
            raise SafeValidationError(f"{label} evidence cannot be a symlink")
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise SafeValidationError(
            f"{label} evidence must reside under deployment-dir"
        ) from exc
    if not resolved.is_file():
        raise SafeValidationError(f"{label} evidence must be a regular file")
    details = _assert_not_writable_by_others(resolved, label=f"{label} evidence")
    if details.st_size <= 0 or details.st_size > max_bytes:
        raise SafeValidationError(f"{label} evidence size is invalid")
    return resolved, relative


def _assert_fresh(details: os.stat_result, *, now: datetime, label: str) -> None:
    modified = datetime.fromtimestamp(details.st_mtime, tz=timezone.utc)
    age = (now - modified).total_seconds()
    if age < -MAX_FUTURE_SKEW_SECONDS or age > MAX_AGE_SECONDS:
        raise SafeValidationError(f"{label} is stale or future-dated")


def _load_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeValidationError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise SafeValidationError(f"{label} JSON root must be an object")
    return value


def _explicit_json_outcome(payload: Mapping[str, Any], *, label: str) -> None:
    outcome = next(
        (
            str(payload[key]).strip().lower()
            for key in ("outcome", "result", "status")
            if key in payload and payload[key] is not None
        ),
        None,
    )
    if outcome != "passed":
        raise SafeValidationError(f"{label} JSON proof did not pass")

    checks = payload.get("checks")
    if checks is None:
        return
    if not isinstance(checks, dict) or not checks:
        raise SafeValidationError(f"{label} JSON checks are invalid")
    for value in checks.values():
        if value is True:
            continue
        if isinstance(value, dict) and value.get("passed") is True:
            continue
        raise SafeValidationError(f"{label} JSON contains a failing check")


def _json_commit_values(payload: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"commit_sha", "candidate_sha"} and child is not None:
                    normalized = str(child).strip()
                    if normalized:
                        values.add(normalized)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    vm = payload.get("vm")
    if isinstance(vm, dict) and vm.get("repo_head") is not None:
        normalized = str(vm["repo_head"]).strip()
        if normalized:
            values.add(normalized)
    return values


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_junit(
    raw: bytes,
    *,
    label: str,
    expected_test_title: str | None = None,
    expected_test_titles: Sequence[str] | None = None,
    require_testcase_commit: bool = False,
) -> tuple[int, set[str]]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise SafeValidationError(f"{label} JUnit contains forbidden declarations")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SafeValidationError(f"{label} is not valid JUnit XML") from exc
    if _local_name(root.tag) not in {"testsuite", "testsuites"}:
        raise SafeValidationError(f"{label} has an unsupported JUnit root")

    testcases = [item for item in root.iter() if _local_name(item.tag) == "testcase"]
    if not testcases:
        raise SafeValidationError(f"{label} JUnit contains no testcase")
    if any(
        _local_name(item.tag) in {"failure", "error", "skipped"} for item in root.iter()
    ):
        raise SafeValidationError(f"{label} JUnit is not fully green")
    if expected_test_title is not None:
        if len(testcases) != 1:
            raise SafeValidationError(f"{label} must contain exactly one tenant canary")
        testcase_identity = " ".join(
            str(testcases[0].attrib.get(key, "")).strip()
            for key in ("classname", "name")
        ).strip()
        if expected_test_title not in testcase_identity:
            raise SafeValidationError(
                f"{label} does not prove the expected tenant canary"
            )
    if expected_test_titles is not None:
        testcase_titles = [
            str(testcase.attrib.get("name", "")) for testcase in testcases
        ]
        if (
            len(testcase_titles) != len(expected_test_titles)
            or len(testcase_titles) != len(set(testcase_titles))
            or set(testcase_titles) != set(expected_test_titles)
        ):
            raise SafeValidationError(
                f"{label} must contain the exact expected canary inventory"
            )
    for suite in [
        item
        for item in root.iter()
        if _local_name(item.tag) in {"testsuite", "testsuites"}
    ]:
        for attribute in ("failures", "errors", "skipped", "disabled"):
            raw_count = suite.attrib.get(attribute, "0")
            try:
                count = int(raw_count)
            except ValueError as exc:
                raise SafeValidationError(f"{label} JUnit count is invalid") from exc
            if count != 0:
                raise SafeValidationError(f"{label} JUnit is not fully green")

    commit_property_names = {
        "commit_sha",
        "candidate_sha",
        "ci_commit_sha",
        "git_sha",
    }
    sha_properties = [
        element
        for element in root.iter()
        if _local_name(element.tag) == "property"
        and str(element.attrib.get("name", "")).strip().lower() in commit_property_names
    ]
    commit_values: set[str] = set()
    if require_testcase_commit:
        if any(
            "".join(element.itertext()).strip()
            for element in root.iter()
            if _local_name(element.tag) in {"system-out", "system-err"}
        ):
            raise SafeValidationError(f"{label} contains retained console output")
        if len(sha_properties) != len(testcases):
            raise SafeValidationError(
                f"{label} must bind commit_sha inside every testcase"
            )
        for testcase in testcases:
            bindings = [
                element
                for element in testcase.iter()
                if _local_name(element.tag) == "property"
                and str(element.attrib.get("name", "")).strip().lower()
                in commit_property_names
            ]
            if len(bindings) != 1:
                raise SafeValidationError(
                    f"{label} must bind commit_sha inside every testcase"
                )
            binding = bindings[0]
            if binding.attrib.get("name") != "commit_sha":
                raise SafeValidationError(
                    f"{label} testcase must use the canonical commit_sha property"
                )
            value = str(binding.attrib.get("value", binding.text or "")).strip()
            if not value:
                raise SafeValidationError(
                    f"{label} testcase commit_sha cannot be empty"
                )
            commit_values.add(value)
    else:
        for element in sha_properties:
            value = element.attrib.get("value", element.text or "")
            normalized = str(value).strip()
            if normalized:
                commit_values.add(normalized)
    return len(testcases), commit_values


def _validate_commit_values(
    values: set[str], candidate_sha: str, *, label: str
) -> bool:
    for value in values:
        if FULL_SHA_RE.fullmatch(value) is None or value != candidate_sha:
            raise SafeValidationError(
                f"{label} commit SHA does not match the candidate"
            )
    return bool(values)


def _proof_metadata(
    path: Path,
    relative: str,
    *,
    label: str,
    candidate_sha: str,
) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SafeValidationError(f"{label} evidence is unreadable") from exc
    stripped = raw.lstrip()
    if stripped.startswith(b"<"):
        test_count, commit_values = _parse_junit(raw, label=label)
        proof_format = "junit"
        detail: dict[str, Any] = {"test_count": test_count}
    else:
        payload = _load_json(path, label=label)
        _explicit_json_outcome(payload, label=label)
        if label == "andritz":
            _validate_andritz_bundle(path, payload, candidate_sha=candidate_sha)
        elif label in TENANT_BUNDLE_INPUTS:
            _validate_tenant_bundle(
                path,
                payload,
                tenant_key=label,
                candidate_sha=candidate_sha,
            )
        commit_values = _json_commit_values(payload)
        proof_format = "json"
        detail = (
            {"test_count": int(payload["workspace_test_count"])}
            if label in {"andritz", "sentinel", "octocity"}
            else {}
        )
    commit_sha_checked = _validate_commit_values(
        commit_values, candidate_sha, label=label
    )
    return {
        "format": proof_format,
        "outcome": "passed",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "location_sha256": hashlib.sha256(relative.encode("utf-8")).hexdigest(),
        "commit_sha_checked": commit_sha_checked,
        **detail,
    }


def _bundle_inputs(
    bundle_path: Path,
    payload: Mapping[str, Any],
    expected: Mapping[str, str],
    *,
    label: str,
) -> dict[str, Path]:
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != set(expected):
        raise SafeValidationError(f"{label} evidence inventory is incomplete")
    resolved: dict[str, Path] = {}
    proof_root = bundle_path.parent.resolve(strict=True)
    deployment_root = proof_root.parent
    for key, filename in expected.items():
        candidate = proof_root / filename
        try:
            if candidate.is_symlink():
                raise SafeValidationError(f"{label} {key} cannot be a symlink")
            path = candidate.resolve(strict=True)
            path.relative_to(deployment_root)
        except (OSError, ValueError) as exc:
            raise SafeValidationError(f"{label} {key} is unavailable") from exc
        expected_parent = (
            deployment_root if key == "storage_canary_comparison" else proof_root
        )
        if path.parent != expected_parent or not path.is_file():
            raise SafeValidationError(f"{label} {key} escaped the proof directory")
        details = _assert_not_writable_by_others(path, label=f"{label} {key}")
        max_bytes = (
            MAX_STORAGE_BYTES if key == "storage_canary_comparison" else MAX_PROOF_BYTES
        )
        if details.st_size <= 0 or details.st_size > max_bytes:
            raise SafeValidationError(f"{label} {key} evidence size is invalid")
        row = evidence.get(key)
        if (
            not isinstance(row, dict)
            or row.get("sha256") != _file_sha256(path)
            or row.get("bytes") != details.st_size
        ):
            raise SafeValidationError(f"{label} {key} digest does not match")
        resolved[key] = path
    return resolved


def _matching_candidate(
    payload: Mapping[str, Any], candidate_sha: str, *, label: str
) -> None:
    values = _json_commit_values(payload)
    if (
        not values
        or _validate_commit_values(values, candidate_sha, label=label) is not True
    ):
        raise SafeValidationError(f"{label} must declare the candidate commit SHA")


def _canonical_uuid(value: object, *, label: str) -> str:
    raw = str(value or "")
    if (
        re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", raw
        )
        is None
    ):
        raise SafeValidationError(f"{label} is not a canonical run UUID")
    return raw


def _assert_content_free(value: object, *, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).strip().lower() in FORBIDDEN_CONTENT_KEYS:
                raise SafeValidationError(f"{label} contains persisted content")
            _assert_content_free(child, label=label)
    elif isinstance(value, list):
        for child in value:
            _assert_content_free(child, label=label)


def _storage_addition_matches_artifact(
    comparison: Mapping[str, Any],
    artifact: Mapping[str, Any],
) -> bool:
    backend = artifact.get("backend")
    key_sha256 = artifact.get("key_sha256")
    content_sha256 = artifact.get("content_sha256")
    size = artifact.get("size")
    if (
        backend not in {"local", "s3"}
        or not isinstance(key_sha256, str)
        or SHA256_RE.fullmatch(key_sha256) is None
        or not isinstance(content_sha256, str)
        or SHA256_RE.fullmatch(content_sha256) is None
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or comparison.get("profile") != "agentium-storage-object-additions-v1"
        or comparison.get("assurance") != "cryptographic_entry_inclusion"
        or comparison.get("result") != "passed"
        or comparison.get("failed_checks") != []
    ):
        return False
    checks = comparison.get("checks")
    check_names = (
        [row.get("name") if isinstance(row, dict) else None for row in checks]
        if isinstance(checks, list)
        else []
    )
    if (
        not isinstance(checks, list)
        or not checks
        or any(
            not isinstance(row, dict) or row.get("passed") is not True for row in checks
        )
        or len(check_names) != len(set(check_names))
        or set(check_names) != EXPECTED_STORAGE_ADDITIONS_CHECKS
    ):
        return False
    additions = comparison.get("additions")
    deletions = comparison.get("deletions")
    modifications = comparison.get("modifications")
    if not all(
        isinstance(value, dict) for value in (additions, deletions, modifications)
    ):
        return False
    empty_digest = canonical_sha256([])
    if set(deletions) != {"object_store", "minio"} or set(modifications) != {
        "object_store",
        "minio",
    }:
        return False
    for key, fields in (
        ("object_store", OBJECT_STORE_ENTRY_FIELDS),
        ("minio", MINIO_ENTRY_FIELDS),
    ):
        summary = deletions.get(key)
        if (
            not isinstance(summary, dict)
            or set(summary) != {"count", "bytes", "entry_fields", "entries", "digest"}
            or summary.get("count") != 0
            or summary.get("bytes") != 0
            or summary.get("entry_fields") != list(fields)
            or summary.get("entries") != []
            or summary.get("digest") != empty_digest
        ):
            return False
    for key, fields in (
        ("object_store", OBJECT_STORE_MODIFICATION_FIELDS),
        ("minio", MINIO_MODIFICATION_FIELDS),
    ):
        summary = modifications.get(key)
        if (
            not isinstance(summary, dict)
            or set(summary) != {"count", "entry_fields", "entries", "digest"}
            or summary.get("count") != 0
            or summary.get("entry_fields") != list(fields)
            or summary.get("entries") != []
            or summary.get("digest") != empty_digest
        ):
            return False
    if set(additions) != {"object_store", "minio"}:
        return False
    selected = "object_store" if backend == "local" else "minio"
    other = "minio" if backend == "local" else "object_store"
    selected_summary = additions.get(selected)
    other_summary = additions.get(other)
    if (
        not isinstance(selected_summary, dict)
        or set(selected_summary)
        != {"count", "bytes", "entry_fields", "entries", "digest"}
        or selected_summary.get("count") != 1
        or selected_summary.get("bytes") != size
        or not isinstance(selected_summary.get("entries"), list)
        or len(selected_summary["entries"]) != 1
        or selected_summary.get("digest")
        != canonical_sha256(selected_summary["entries"])
        or not isinstance(other_summary, dict)
        or set(other_summary) != {"count", "bytes", "entry_fields", "entries", "digest"}
        or other_summary.get("count") != 0
        or other_summary.get("bytes") != 0
        or other_summary.get("entries") != []
        or other_summary.get("digest") != empty_digest
    ):
        return False
    entry = selected_summary["entries"][0]
    fields = selected_summary.get("entry_fields")
    if backend == "local":
        return bool(
            isinstance(entry, dict)
            and set(entry) == set(OBJECT_STORE_ENTRY_FIELDS)
            and fields == list(OBJECT_STORE_ENTRY_FIELDS)
            and other_summary.get("entry_fields") == list(MINIO_ENTRY_FIELDS)
            and entry.get("path_sha256") == key_sha256
            and entry.get("content_sha256") == content_sha256
            and entry.get("size") == size
        )
    if (
        not isinstance(entry, list)
        or fields != list(MINIO_ENTRY_FIELDS)
        or other_summary.get("entry_fields") != list(OBJECT_STORE_ENTRY_FIELDS)
        or len(entry) != len(fields)
    ):
        return False
    row = dict(zip(fields, entry, strict=True))
    return bool(
        row.get("object_id_sha256") == key_sha256
        and row.get("size") == size
        and row.get("delete_marker") is False
    )


def _validate_andritz_bundle(
    path: Path,
    payload: Mapping[str, Any],
    *,
    candidate_sha: str,
) -> None:
    if (
        payload.get("schema_version") != 2
        or payload.get("kind") != "andritz_safe_deployment_bundle"
    ):
        raise SafeValidationError("andritz proof is not the required composite bundle")
    _matching_candidate(payload, candidate_sha, label="andritz")
    deployment_id = path.parent.parent.name
    expected_marker_sha256 = hashlib.sha256(
        f"agentium_safe_chat::{deployment_id}::{candidate_sha[:12]}".encode("utf-8")
    ).hexdigest()
    if (
        payload.get("deployment_id") != deployment_id
        or payload.get("input_marker_sha256") != expected_marker_sha256
    ):
        raise SafeValidationError("andritz proof deployment identity does not match")
    run_id = _canonical_uuid(payload.get("chat_run_id"), label="andritz chat_run_id")
    if (
        payload.get("actual_chat_requests") != 1
        or int(payload.get("invocation_count") or 0) <= 0
    ):
        raise SafeValidationError("andritz proof omits the controlled Chat ledger")
    inputs = _bundle_inputs(path, payload, ANDRITZ_BUNDLE_INPUTS, label="andritz")
    test_count, junit_commits = _parse_junit(
        inputs["workspace_junit"].read_bytes(),
        label="andritz JUnit",
        expected_test_titles=EXPECTED_ANDRITZ_TEST_TITLES,
        require_testcase_commit=True,
    )
    if not _validate_commit_values(
        junit_commits,
        candidate_sha,
        label="andritz JUnit",
    ):
        raise SafeValidationError("andritz JUnit must declare the candidate commit SHA")
    if test_count <= 0 or payload.get("workspace_test_count") != test_count:
        raise SafeValidationError("andritz JUnit inventory does not match")

    spl = _load_json(inputs["spl_probe"], label="andritz SPL probe")
    ledger = _load_json(inputs["chat_ledger"], label="andritz Chat ledger")
    delivery = _load_json(inputs["chat_delivery"], label="andritz Chat delivery")
    bindings = _load_json(inputs["runtime_bindings"], label="runtime bindings")
    storage_comparison = _load_json(
        inputs["storage_canary_comparison"],
        label="andritz canary storage comparison",
    )
    for label, evidence in (
        ("andritz SPL probe", spl),
        ("andritz Chat delivery", delivery),
        ("andritz Chat ledger", ledger),
    ):
        _assert_content_free(evidence, label=label)
    _explicit_json_outcome(spl, label="andritz SPL probe")
    _explicit_json_outcome(ledger, label="andritz Chat ledger")
    _matching_candidate(spl, candidate_sha, label="andritz SPL probe")
    _matching_candidate(ledger, candidate_sha, label="andritz Chat ledger")
    for label, evidence in (
        ("andritz SPL probe", spl),
        ("andritz Chat delivery", delivery),
        ("andritz Chat ledger", ledger),
    ):
        if (
            evidence.get("deployment_id") != deployment_id
            or evidence.get("input_marker_sha256") != expected_marker_sha256
        ):
            raise SafeValidationError(f"{label} deployment identity does not match")
    if (
        spl.get("kind") != "andritz_spl_controlled_probe"
        or delivery.get("kind") != "controlled_chat_delivery"
        or delivery.get("attempt_ceiling") != 1
        or ledger.get("kind") != "safe_controlled_chat_ledger"
        or ledger.get("schema_version") != 2
    ):
        raise SafeValidationError("andritz controlled Chat contract is invalid")
    spl_run = _canonical_uuid(spl.get("run_id"), label="andritz SPL run_id")
    ledger_run = _canonical_uuid(ledger.get("run_id"), label="andritz ledger run_id")
    delivery_run = _canonical_uuid(
        delivery.get("run_id"), label="andritz delivery run_id"
    )
    if not (run_id == spl_run == ledger_run == delivery_run):
        raise SafeValidationError("andritz controlled Chat run lineage does not match")
    ledger_checks = ledger.get("checks")
    if not isinstance(ledger_checks, dict) or not REQUIRED_CHAT_LINEAGE_CHECKS.issubset(
        ledger_checks
    ):
        raise SafeValidationError("andritz controlled Chat lineage is incomplete")
    workspace_id = _canonical_uuid(
        ledger.get("workspace_id"),
        label="andritz workspace id",
    )
    system_id = _canonical_uuid(ledger.get("system_id"), label="andritz System id")
    capability_id = _canonical_uuid(
        ledger.get("capability_id"),
        label="andritz Capability id",
    )
    knowledge_collection_id = _canonical_uuid(
        ledger.get("knowledge_collection_id"),
        label="andritz KnowledgeCollection id",
    )
    knowledge_collection_chunk_count = ledger.get("knowledge_collection_chunk_count")
    lineage_hash_fields = (
        "system_type_sha256",
        "flow_variant_sha256",
        "retrieval_contract_sha256",
        "knowledge_collection_slug_sha256",
    )
    if (
        payload.get("workspace_id") != workspace_id
        or payload.get("system_id") != system_id
        or payload.get("capability_id") != capability_id
        or payload.get("knowledge_collection_id") != knowledge_collection_id
        or not isinstance(knowledge_collection_chunk_count, int)
        or isinstance(knowledge_collection_chunk_count, bool)
        or knowledge_collection_chunk_count <= 0
        or payload.get("knowledge_collection_chunk_count")
        != knowledge_collection_chunk_count
        or any(
            SHA256_RE.fullmatch(str(ledger.get(field) or "")) is None
            or payload.get(field) != ledger.get(field)
            for field in lineage_hash_fields
        )
    ):
        raise SafeValidationError("andritz controlled Chat lineage is inconsistent")
    if (
        spl.get("actual_chat_requests") != 1
        or delivery.get("actual_chat_requests") != 1
        or delivery.get("status") != "completed"
        or delivery.get("commit_sha") != candidate_sha
        or int(ledger.get("invocation_count") or 0) <= 0
    ):
        raise SafeValidationError("andritz controlled Chat proof is incomplete")
    invocation_count = int(ledger["invocation_count"])
    invocation_ids = ledger.get("invocation_ids")
    if (
        not isinstance(invocation_ids, list)
        or len(invocation_ids) != invocation_count
        or any(not isinstance(value, str) for value in invocation_ids)
        or len(set(invocation_ids)) != invocation_count
        or any(
            _canonical_uuid(value, label="andritz SkillInvocation id") != value
            for value in invocation_ids
        )
        or ledger.get("invocation_status_counts") != {"completed": invocation_count}
        or ledger.get("run_status_counts") != {"completed": 1}
        or SHA256_RE.fullmatch(str(ledger.get("input_query_sha256") or "")) is None
        or SHA256_RE.fullmatch(str(ledger.get("run_trigger_sha256") or "")) is None
        or SHA256_RE.fullmatch(str(ledger.get("skill_sequence_sha256") or "")) is None
        or SHA256_RE.fullmatch(str(ledger.get("flow_skill_contract_sha256") or ""))
        is None
        or SHA256_RE.fullmatch(
            str(ledger.get("read_generation_allowlist_sha256") or "")
        )
        is None
        or ledger.get("unexpected_skill_count") != 0
    ):
        raise SafeValidationError("andritz controlled Chat ledger is inconsistent")
    artifact = ledger.get("provenance_artifact")
    if (
        ledger.get("artifact_count") != 1
        or not isinstance(artifact, dict)
        or not _storage_addition_matches_artifact(storage_comparison, artifact)
        or payload.get("artifact_backend") != artifact.get("backend")
        or payload.get("artifact_key_sha256") != artifact.get("key_sha256")
        or payload.get("artifact_content_sha256") != artifact.get("content_sha256")
        or payload.get("artifact_size") != artifact.get("size")
    ):
        raise SafeValidationError(
            "andritz provenance artifact does not match the sole storage addition"
        )
    if (
        bindings.get("result") != "passed"
        or bindings.get("requested_workspace_slugs") != []
        or bindings.get("missing_workspace_slugs") != []
        or not isinstance(bindings.get("workspace_count"), int)
        or bindings["workspace_count"] < 3
    ):
        raise SafeValidationError("andritz runtime binding audit did not pass")


def _validate_tenant_bundle(
    path: Path,
    payload: Mapping[str, Any],
    *,
    tenant_key: str,
    candidate_sha: str,
) -> None:
    if (
        payload.get("kind") != "tenant_safe_deployment_bundle"
        or payload.get("tenant_key") != tenant_key
    ):
        raise SafeValidationError(
            f"{tenant_key} proof is not its required composite bundle"
        )
    _matching_candidate(payload, candidate_sha, label=tenant_key)
    inputs = _bundle_inputs(
        path,
        payload,
        TENANT_BUNDLE_INPUTS[tenant_key],
        label=tenant_key,
    )
    test_count, junit_commits = _parse_junit(
        inputs["workspace_junit"].read_bytes(),
        label=f"{tenant_key} JUnit",
        expected_test_title=EXPECTED_TENANT_TEST_TITLES[tenant_key],
        require_testcase_commit=True,
    )
    if not _validate_commit_values(
        junit_commits,
        candidate_sha,
        label=f"{tenant_key} JUnit",
    ):
        raise SafeValidationError(
            f"{tenant_key} JUnit must declare the candidate commit SHA"
        )
    if test_count <= 0 or payload.get("workspace_test_count") != test_count:
        raise SafeValidationError(f"{tenant_key} JUnit inventory does not match")
    bindings = _load_json(inputs["runtime_bindings"], label="runtime bindings")
    if (
        bindings.get("result") != "passed"
        or bindings.get("requested_workspace_slugs") != []
        or bindings.get("missing_workspace_slugs") != []
        or not isinstance(bindings.get("workspace_count"), int)
        or bindings["workspace_count"] < 3
    ):
        raise SafeValidationError(f"{tenant_key} runtime binding audit did not pass")


def _storage_payload(
    path: Path,
    *,
    label: str,
    expected_profile: str,
) -> Mapping[str, Any]:
    payload = _load_json(path, label=label)
    if payload.get("schema_version") != 1 or payload.get("profile") != expected_profile:
        raise SafeValidationError(f"{label} storage profile is unsupported")
    return payload


def _storage_metadata(path: Path, relative: str) -> dict[str, Any]:
    return {
        "format": "json",
        "sha256": _file_sha256(path),
        "bytes": path.stat().st_size,
        "location_sha256": hashlib.sha256(relative.encode("utf-8")).hexdigest(),
    }


def _validate_qdrant_probe(value: object, *, expected_access: str, label: str) -> int:
    if not isinstance(value, dict):
        raise SafeValidationError(f"{label} Qdrant probe is invalid")
    collection_count = value.get("collection_count")
    if (
        not isinstance(collection_count, int)
        or isinstance(collection_count, bool)
        or collection_count < 0
    ):
        raise SafeValidationError(f"{label} Qdrant collection count is invalid")
    if (
        value.get("unauthenticated_read_status") not in {401, 403}
        or value.get("authenticated_read_status") != 200
        or value.get("absent_guard_before_status") != 404
        or value.get("absent_guard_after_status") != 404
        or value.get("expected_access") != expected_access
        or value.get("read_allowed") is not True
        or value.get("guard_remained_absent") is not True
    ):
        raise SafeValidationError(f"{label} Qdrant access proof did not pass")
    if expected_access == "read-only":
        if (
            value.get("delete_status") not in {401, 403}
            or value.get("write_rejected") is not True
            or value.get("write_route_authorized") is not False
        ):
            raise SafeValidationError(f"{label} did not prove a read-only Qdrant key")
    elif (
        value.get("delete_status") != 404
        or value.get("write_rejected") is not False
        or value.get("write_route_authorized") is not True
    ):
        raise SafeValidationError(f"{label} did not prove an admin-ready Qdrant key")
    return collection_count


def _validate_qdrant_host_barrier(
    payload: Mapping[str, Any],
    *,
    deployment_id: str,
    candidate_sha: str,
    expected_access: str,
    expected_clients: frozenset[str] | None,
    label: str,
) -> dict[str, Any]:
    profile = (
        "agentium-qdrant-read-only-validation-v1"
        if expected_access == "read-only"
        else "agentium-qdrant-admin-ready-v1"
    )
    assurance = (
        "server_key_separation_plus_negative_write_probe"
        if expected_access == "read-only"
        else "server_key_separation_plus_admin_ready_probe"
    )
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "agentium_qdrant_write_barrier"
        or payload.get("profile") != profile
        or payload.get("deployment_id") != deployment_id
        or payload.get("sha") != candidate_sha
        or payload.get("result") != "passed"
        or payload.get("secrets_serialized") is not False
        or payload.get("assurance") != assurance
        or payload.get("proof_ceiling") != "runner_verified"
    ):
        raise SafeValidationError(f"{label} Qdrant host barrier identity is invalid")

    qdrant = payload.get("qdrant")
    if not isinstance(qdrant, dict):
        raise SafeValidationError(f"{label} Qdrant server contract is missing")
    qdrant_id = str(qdrant.get("container_id") or "")
    image_id = str(qdrant.get("image_id") or "")
    ports = qdrant.get("port_contract")
    if (
        DOCKER_CONTAINER_ID_RE.fullmatch(qdrant_id) is None
        or DOCKER_IMAGE_ID_RE.fullmatch(image_id) is None
        or qdrant.get("image") != "qdrant/qdrant:v1.12.5-unprivileged"
        or qdrant.get("internal_network_present") is not True
        or qdrant.get("admin_key_present") is not True
        or qdrant.get("read_only_key_present") is not True
        or qdrant.get("keys_distinct") is not True
        or qdrant.get("cluster_mode") != "standalone"
        or not isinstance(ports, dict)
        or ports.get("loopback_only") is not True
        or not isinstance(ports.get("published_bindings_checked"), int)
        or ports["published_bindings_checked"] < 2
    ):
        raise SafeValidationError(f"{label} Qdrant server contract is invalid")

    clients = payload.get("clients")
    if not isinstance(clients, dict):
        raise SafeValidationError(f"{label} Qdrant client contract is missing")
    identities = clients.get("identities")
    by_name = clients.get("container_id_by_name")
    if (
        not isinstance(identities, dict)
        or not identities
        or not isinstance(by_name, dict)
    ):
        raise SafeValidationError(f"{label} Qdrant client identities are invalid")
    if expected_clients is not None and set(identities) != expected_clients:
        raise SafeValidationError(f"{label} Qdrant client inventory is unexpected")
    if not {"agentium-backend", "agentium-worker-cpu"}.issubset(identities):
        raise SafeValidationError(f"{label} omits a required Qdrant client")
    normalized: dict[str, str] = {}
    for name, identity in identities.items():
        if not isinstance(name, str) or not isinstance(identity, dict):
            raise SafeValidationError(f"{label} Qdrant client identity is invalid")
        runtime_id = str(identity.get("container_id") or "")
        inspect_id = str(identity.get("docker_inspect_id") or "")
        if (
            CONTAINER_ID_RE.fullmatch(runtime_id) is None
            or DOCKER_CONTAINER_ID_RE.fullmatch(inspect_id) is None
            or not inspect_id.startswith(runtime_id)
        ):
            raise SafeValidationError(f"{label} Qdrant client identity is inconsistent")
        normalized[name] = runtime_id
    if (
        by_name != normalized
        or clients.get("expected_count") != len(identities)
        or clients.get("all_running") is not True
        or clients.get("expected_access") != expected_access
        or clients.get("all_expected_access") is not True
        or clients.get("all_read_only") is not (expected_access == "read-only")
        or clients.get("all_admin_ready") is not (expected_access == "admin")
    ):
        raise SafeValidationError(f"{label} Qdrant client access contract is invalid")

    network = payload.get("network_guard")
    if (
        not isinstance(network, dict)
        or not isinstance(network.get("running_peer_count"), int)
        or network["running_peer_count"] < len(identities)
        or not isinstance(network.get("credentialed_peer_count"), int)
        or network["credentialed_peer_count"] < len(identities)
        or network.get("non_read_only_peer_count") != 0
    ):
        raise SafeValidationError(f"{label} Qdrant peer inventory is invalid")
    collection_count = _validate_qdrant_probe(
        payload.get("probe"), expected_access=expected_access, label=label
    )
    return {
        "qdrant_container_id": qdrant_id,
        "qdrant_image_id": image_id,
        "client_ids": normalized,
        "collection_count": collection_count,
    }


def _validate_qdrant_client_probe(
    payload: Mapping[str, Any],
    *,
    deployment_id: str,
    candidate_sha: str,
    expected_container_id: str,
    label: str,
) -> None:
    identity = payload.get("client_identity")
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "agentium_qdrant_client_write_barrier"
        or payload.get("profile") != "agentium-qdrant-read-only-client-v1"
        or payload.get("deployment_id") != deployment_id
        or payload.get("sha") != candidate_sha
        or payload.get("result") != "passed"
        or payload.get("secrets_serialized") is not False
        or payload.get("assurance") != "server_rejected_absent_target_delete"
        or not isinstance(identity, dict)
        or identity.get("container_id") != expected_container_id
    ):
        raise SafeValidationError(f"{label} Qdrant client probe identity is invalid")
    _validate_qdrant_probe(
        payload.get("probe"), expected_access="read-only", label=label
    )


def _validate_qdrant_evidence(
    resolved: Mapping[str, tuple[Path, str]],
    *,
    deployment_id: str,
    candidate_sha: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    payloads = {
        label: _load_json(resolved[label][0], label=label) for label in QDRANT_ENTRIES
    }
    preflight = _validate_qdrant_host_barrier(
        payloads["qdrant_preflight_barrier"],
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
        expected_access="admin",
        expected_clients=None,
        label="qdrant_preflight_barrier",
    )
    expected_clients = frozenset({"agentium-backend", "agentium-worker-cpu"})
    validation = _validate_qdrant_host_barrier(
        payloads["qdrant_validation_barrier"],
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
        expected_access="read-only",
        expected_clients=expected_clients,
        label="qdrant_validation_barrier",
    )
    post_canary = _validate_qdrant_host_barrier(
        payloads["qdrant_post_canary_barrier"],
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
        expected_access="read-only",
        expected_clients=expected_clients,
        label="qdrant_post_canary_barrier",
    )
    for field in ("qdrant_container_id", "qdrant_image_id", "collection_count"):
        if preflight[field] != validation[field]:
            raise SafeValidationError(
                "Qdrant server identity or collection count changed before validation"
            )
    if validation != post_canary:
        raise SafeValidationError(
            "Qdrant identity or collection count changed during canaries"
        )
    for label, container in (
        ("qdrant_backend_probe", "agentium-backend"),
        ("qdrant_worker_probe", "agentium-worker-cpu"),
    ):
        _validate_qdrant_client_probe(
            payloads[label],
            deployment_id=deployment_id,
            candidate_sha=candidate_sha,
            expected_container_id=validation["client_ids"][container],
            label=label,
        )
    if payloads["qdrant_backend_probe"].get("client_identity") == payloads[
        "qdrant_worker_probe"
    ].get("client_identity"):
        raise SafeValidationError(
            "Qdrant backend and worker probes reuse one container identity"
        )

    metadata = {label: _storage_metadata(*resolved[label]) for label in QDRANT_ENTRIES}
    digests = {
        "qdrant_preflight_identity": canonical_sha256(preflight),
        "qdrant_validation_identity": canonical_sha256(validation),
        "qdrant_post_canary_identity": canonical_sha256(post_canary),
    }
    return metadata, digests


def _database_multiset(value: object, *, label: str) -> dict[str, int]:
    if (
        not isinstance(value, dict)
        or set(value) != {"algorithm", "domains", "sums"}
        or value.get("algorithm") != DATABASE_ACCUMULATOR_ALGORITHM
        or value.get("domains") != DATABASE_ACCUMULATOR_DOMAINS
        or not isinstance(value.get("sums"), dict)
        or set(value["sums"]) != set(DATABASE_ACCUMULATOR_DOMAINS)
    ):
        raise SafeValidationError(f"{label} multiset contract is invalid")
    result: dict[str, int] = {}
    for domain in DATABASE_ACCUMULATOR_DOMAINS:
        encoded = value["sums"].get(domain)
        if not isinstance(encoded, str) or SHA256_RE.fullmatch(encoded) is None:
            raise SafeValidationError(f"{label} multiset sum is invalid")
        result[domain] = int(encoded, 16)
    return result


def _database_aggregate(
    row_count: object, multiset: object, *, label: str
) -> dict[str, Any]:
    if not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 0:
        raise SafeValidationError(f"{label} row count is invalid")
    return {"count": row_count, "sums": _database_multiset(multiset, label=label)}


def _database_zero_aggregate() -> dict[str, Any]:
    return {
        "count": 0,
        "sums": {domain: 0 for domain in DATABASE_ACCUMULATOR_DOMAINS},
    }


def _database_add_aggregates(*values: Mapping[str, Any]) -> dict[str, Any]:
    result = _database_zero_aggregate()
    for value in values:
        result["count"] += int(value["count"])
        for domain in DATABASE_ACCUMULATOR_DOMAINS:
            result["sums"][domain] = (
                result["sums"][domain] + int(value["sums"][domain])
            ) % DATABASE_ACCUMULATOR_MODULUS
    return result


def _database_subtract_aggregates(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "count": int(after["count"]) - int(before["count"]),
        "sums": {
            domain: (int(after["sums"][domain]) - int(before["sums"][domain]))
            % DATABASE_ACCUMULATOR_MODULUS
            for domain in DATABASE_ACCUMULATOR_DOMAINS
        },
    }


def _database_domain_value(
    domain: str, primary_key_sha256: str, row_sha256: str | None
) -> int:
    digest = hashlib.sha256()
    digest.update(domain.encode("ascii"))
    digest.update(b"\x00")
    digest.update(bytes.fromhex(primary_key_sha256))
    if row_sha256 is not None:
        digest.update(b"\x00")
        digest.update(bytes.fromhex(row_sha256))
    return int.from_bytes(digest.digest(), "big")


def _database_controlled_aggregate(rows: Mapping[str, str]) -> dict[str, Any]:
    result = _database_zero_aggregate()
    for primary_key_sha256, row_sha256 in rows.items():
        result["count"] += 1
        values = {
            "primary_key": _database_domain_value(
                DATABASE_ACCUMULATOR_DOMAINS["primary_key"],
                primary_key_sha256,
                None,
            ),
            "row_state": _database_domain_value(
                DATABASE_ACCUMULATOR_DOMAINS["row_state"],
                primary_key_sha256,
                row_sha256,
            ),
        }
        for domain, value in values.items():
            result["sums"][domain] = (
                result["sums"][domain] + value
            ) % DATABASE_ACCUMULATOR_MODULUS
    return result


def _database_ledger_binding(value: object, *, label: str) -> dict[str, Any]:
    expected_keys = {
        "provided",
        "ledger_sha256",
        "controlled_run_primary_key_sha256",
        "controlled_invocation_count",
        "controlled_invocation_primary_keys_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise SafeValidationError(f"{label} ledger binding is invalid")
    provided = value.get("provided")
    count = value.get("controlled_invocation_count")
    if (
        not isinstance(provided, bool)
        or not isinstance(count, int)
        or isinstance(count, bool)
    ):
        raise SafeValidationError(f"{label} ledger binding is invalid")
    digest_fields = (
        "ledger_sha256",
        "controlled_run_primary_key_sha256",
        "controlled_invocation_primary_keys_sha256",
    )
    if provided:
        if not 1 <= count <= MAX_CONTROLLED_DATABASE_INVOCATIONS or any(
            not isinstance(value.get(field), str)
            or SHA256_RE.fullmatch(str(value[field])) is None
            for field in digest_fields
        ):
            raise SafeValidationError(f"{label} ledger binding is invalid")
    elif count != 0 or any(value.get(field) is not None for field in digest_fields):
        raise SafeValidationError(f"{label} ledger binding is invalid")
    return dict(value)


def _database_workspace_identities(
    payload: Mapping[str, Any],
    *,
    label: str,
    expected_canary_identities: Mapping[str, str],
) -> dict[str, str]:
    identities = payload.get("workspace_identities")
    if not isinstance(identities, list) or payload.get(
        "workspace_identities_sha256"
    ) != canonical_sha256(identities):
        raise SafeValidationError(f"{label} workspace identities are invalid")
    result: dict[str, str] = {}
    hashes: set[str] = set()
    previous_slug = ""
    for identity in identities:
        if not isinstance(identity, dict) or set(identity) != {
            "slug",
            "workspace_id_sha256",
        }:
            raise SafeValidationError(f"{label} workspace identity is invalid")
        slug = identity.get("slug")
        workspace_hash = identity.get("workspace_id_sha256")
        if (
            not isinstance(slug, str)
            or not slug
            or "@" in slug
            or slug <= previous_slug
            or not isinstance(workspace_hash, str)
            or SHA256_RE.fullmatch(workspace_hash) is None
            or workspace_hash in hashes
        ):
            raise SafeValidationError(f"{label} workspace identity is invalid")
        result[slug] = workspace_hash
        hashes.add(workspace_hash)
        previous_slug = slug
    if any(
        result.get(slug) != workspace_hash
        for slug, workspace_hash in expected_canary_identities.items()
    ):
        raise SafeValidationError(
            f"{label} omits or changes a resolved canary workspace"
        )
    return result


def _database_table(
    table: Mapping[str, Any],
    *,
    table_name: str,
    workspace_hashes: frozenset[str],
    label: str,
) -> dict[str, Any]:
    expected_keys = {
        "primary_key_columns",
        "row_count",
        "multiset",
        "normalization",
        "controlled_rows",
        "canonical_navigation_by_workspace",
    }
    primary_keys = table.get("primary_key_columns")
    normalization = table.get("normalization")
    expected_normalization = ["last_login"] if table_name == "users" else []
    if (
        set(table) != expected_keys
        or not isinstance(primary_keys, list)
        or not primary_keys
        or len(primary_keys) != len(set(primary_keys))
        or any(
            not isinstance(column, str) or SQL_IDENTIFIER_RE.fullmatch(column) is None
            for column in primary_keys
        )
        or normalization != expected_normalization
    ):
        raise SafeValidationError(f"{label} table contract is invalid")
    controlled_rows = table.get("controlled_rows")
    if (
        not isinstance(controlled_rows, dict)
        or len(controlled_rows) > MAX_CONTROLLED_DATABASE_INVOCATIONS + 1
    ):
        raise SafeValidationError(f"{label} controlled row details are invalid")
    controlled: dict[str, str] = {}
    for primary_key_sha256, row_sha256 in controlled_rows.items():
        if (
            not isinstance(primary_key_sha256, str)
            or SHA256_RE.fullmatch(primary_key_sha256) is None
            or not isinstance(row_sha256, str)
            or SHA256_RE.fullmatch(row_sha256) is None
        ):
            raise SafeValidationError(f"{label} controlled row hash is invalid")
        controlled[primary_key_sha256] = row_sha256

    raw_navigation = table.get("canonical_navigation_by_workspace")
    if not isinstance(raw_navigation, dict):
        raise SafeValidationError(f"{label} navigation aggregates are invalid")
    navigation: dict[str, dict[str, Any]] = {}
    for workspace_hash, aggregate in raw_navigation.items():
        if (
            not isinstance(workspace_hash, str)
            or workspace_hash not in workspace_hashes
            or not isinstance(aggregate, dict)
            or set(aggregate) != {"row_count", "multiset"}
        ):
            raise SafeValidationError(f"{label} navigation aggregate is invalid")
        parsed = _database_aggregate(
            aggregate["row_count"],
            aggregate["multiset"],
            label=f"{label}.navigation.{workspace_hash[:12]}",
        )
        if parsed["count"] <= 0:
            raise SafeValidationError(f"{label} navigation aggregate is empty")
        navigation[workspace_hash] = parsed
    if table_name != "audit_logs" and navigation:
        raise SafeValidationError(f"{label} contains escaped navigation details")
    return {
        "primary_key_columns": list(primary_keys),
        "normalization": list(normalization),
        "aggregate": _database_aggregate(
            table.get("row_count"), table.get("multiset"), label=label
        ),
        "controlled_rows": controlled,
        "navigation": navigation,
    }


def _validate_database_inventory(
    payload: Mapping[str, Any],
    *,
    deployment_id: str,
    candidate_sha: str,
    label: str,
    expected_canary_identities: Mapping[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, Any]]:
    expected_keys = {
        "schema_version",
        "kind",
        "profile",
        "candidate_sha",
        "deployment_id",
        "content_serialized",
        "detail_policy",
        "table_count",
        "tables",
        "inventory_sha256",
        "business_inventory_sha256",
        "workspace_identities",
        "workspace_identities_sha256",
        "ledger_binding",
    }
    tables = payload.get("tables")
    if (
        set(payload) != expected_keys
        or payload.get("schema_version") != DATABASE_SCHEMA_VERSION
        or payload.get("kind") != "postgresql_row_inventory"
        or payload.get("profile") != DATABASE_INVENTORY_PROFILE
        or payload.get("candidate_sha") != candidate_sha
        or payload.get("deployment_id") != deployment_id
        or payload.get("content_serialized") is not False
        or payload.get("detail_policy") != DATABASE_DETAIL_POLICY
        or not isinstance(tables, dict)
        or not tables
        or not {"users", "runs", "skill_invocations", "audit_logs"}.issubset(tables)
        or payload.get("table_count") != len(tables)
    ):
        raise SafeValidationError(f"{label} PostgreSQL v2 identity is invalid")
    identities = _database_workspace_identities(
        payload,
        label=label,
        expected_canary_identities=expected_canary_identities,
    )
    binding = _database_ledger_binding(payload.get("ledger_binding"), label=label)
    expected_inventory_sha256 = canonical_sha256(
        {
            "tables": tables,
            "workspace_identities": payload["workspace_identities"],
            "ledger_binding": binding,
        }
    )
    business_tables = {
        table_name: table
        for table_name, table in tables.items()
        if table_name not in KEYCLOAK_VOLATILE_TABLES
    }
    if payload.get("inventory_sha256") != expected_inventory_sha256 or payload.get(
        "business_inventory_sha256"
    ) != canonical_sha256(business_tables):
        raise SafeValidationError(f"{label} PostgreSQL v2 digest is invalid")
    workspace_hashes = frozenset(identities.values())
    parsed: dict[str, dict[str, Any]] = {}
    for table_name, table in tables.items():
        if (
            not isinstance(table_name, str)
            or SQL_IDENTIFIER_RE.fullmatch(table_name) is None
            or not isinstance(table, dict)
        ):
            raise SafeValidationError(f"{label} PostgreSQL table inventory is invalid")
        parsed[table_name] = _database_table(
            table,
            table_name=table_name,
            workspace_hashes=workspace_hashes,
            label=f"{label}.{table_name}",
        )
    return parsed, identities, binding


def _database_workspace_hashes(
    comparison: Mapping[str, Any],
    *,
    inventory_identities: Mapping[str, str],
    expected_canary_identities: Mapping[str, str],
) -> frozenset[str]:
    workspaces = comparison.get("canary_workspaces")
    if (
        not isinstance(workspaces, list)
        or len(workspaces) != len(expected_canary_identities)
        or comparison.get("canary_workspaces_sha256") != canonical_sha256(workspaces)
    ):
        raise SafeValidationError(
            "database comparison lacks the four canary workspaces"
        )
    slugs: set[str] = set()
    hashes: set[str] = set()
    for workspace in workspaces:
        if not isinstance(workspace, dict) or set(workspace) != {
            "slug",
            "workspace_id_sha256",
        }:
            raise SafeValidationError("database canary workspace identity is invalid")
        slug = workspace.get("slug")
        workspace_hash = workspace.get("workspace_id_sha256")
        if (
            not isinstance(slug, str)
            or slug in slugs
            or not isinstance(workspace_hash, str)
            or SHA256_RE.fullmatch(workspace_hash) is None
            or workspace_hash in hashes
        ):
            raise SafeValidationError("database canary workspace identity is invalid")
        slugs.add(slug)
        hashes.add(workspace_hash)
    if workspaces != sorted(workspaces, key=lambda item: str(item["slug"])):
        raise SafeValidationError("database canary workspaces are not sorted")
    if slugs != set(expected_canary_identities):
        raise SafeValidationError(
            "database comparison names unexpected canary workspaces"
        )
    comparison_identities = {
        str(workspace["slug"]): str(workspace["workspace_id_sha256"])
        for workspace in workspaces
    }
    if comparison_identities != dict(expected_canary_identities):
        raise SafeValidationError(
            "database comparison differs from the resolved workspace targets"
        )
    if {
        slug: workspace_hash
        for slug, workspace_hash in inventory_identities.items()
        if slug in expected_canary_identities
    } != comparison_identities:
        raise SafeValidationError(
            "database comparison changed a canary workspace identity"
        )
    return frozenset(hashes)


def _database_navigation_delta(
    *,
    before: Mapping[str, Mapping[str, Any]],
    after: Mapping[str, Mapping[str, Any]],
    canary_workspace_hashes: frozenset[str],
    label: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    expected = _database_zero_aggregate()
    counts: dict[str, int] = {}
    for workspace_hash in sorted(
        set(before) | set(after) | set(canary_workspace_hashes)
    ):
        old = before.get(workspace_hash, _database_zero_aggregate())
        new = after.get(workspace_hash, _database_zero_aggregate())
        if workspace_hash in canary_workspace_hashes:
            delta = _database_subtract_aggregates(old, new)
            counts[workspace_hash] = int(delta["count"])
            if delta["count"] <= 0:
                raise SafeValidationError(
                    f"{label} lacks canonical navigation for a protected workspace"
                )
            expected = _database_add_aggregates(expected, delta)
        elif old != new:
            raise SafeValidationError(
                f"{label} changed navigation outside the protected workspaces"
            )
    return expected, counts


def _database_expected_stage(
    *,
    label: str,
    baseline: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
    controlled_primary_keys: Mapping[str, frozenset[str]],
    canary_workspace_hashes: frozenset[str],
) -> tuple[dict[str, Any], dict[str, int]]:
    stage: dict[str, Any] = {}
    additions: dict[str, int] = {}
    for table_name in sorted(baseline):
        before = baseline[table_name]
        after = current[table_name]
        if (
            before["primary_key_columns"] != after["primary_key_columns"]
            or before["normalization"] != after["normalization"]
        ):
            raise SafeValidationError(
                f"{label}.{table_name} changed its PostgreSQL table contract"
            )
        controlled = after["controlled_rows"]
        navigation_counts: dict[str, int] = {}
        if table_name in KEYCLOAK_VOLATILE_TABLES:
            if controlled or after["navigation"]:
                raise SafeValidationError(
                    f"{label}.{table_name} carries forbidden detailed evidence"
                )
            result = "allowed_keycloak_session_or_event_volatility"
            expected_delta_count: int | None = None
        else:
            expected = _database_zero_aggregate()
            if table_name in controlled_primary_keys:
                if (
                    after["primary_key_columns"] != ["id"]
                    or frozenset(controlled) != controlled_primary_keys[table_name]
                ):
                    raise SafeValidationError(
                        f"{label}.{table_name} is not bound exactly to the Chat ledger"
                    )
                expected = _database_controlled_aggregate(controlled)
            elif controlled:
                raise SafeValidationError(
                    f"{label}.{table_name} exposes rows outside the Chat ledger"
                )
            if table_name == "audit_logs":
                expected, navigation_counts = _database_navigation_delta(
                    before=before["navigation"],
                    after=after["navigation"],
                    canary_workspace_hashes=canary_workspace_hashes,
                    label=f"{label}.audit_logs",
                )
            observed = _database_subtract_aggregates(
                before["aggregate"], after["aggregate"]
            )
            if observed != expected:
                raise SafeValidationError(
                    f"{label}.{table_name} modified a pre-existing business row "
                    "or contains an unauthorized delta"
                )
            result = "passed"
            expected_delta_count = int(expected["count"])
            if expected_delta_count:
                additions[table_name] = expected_delta_count
        stage[table_name] = {
            "result": result,
            "before_count": int(before["aggregate"]["count"]),
            "after_count": int(after["aggregate"]["count"]),
            "observed_delta_count": int(after["aggregate"]["count"])
            - int(before["aggregate"]["count"]),
            "expected_delta_count": expected_delta_count,
            "canonical_navigation_delta_counts": navigation_counts,
        }
    return stage, additions


def _validate_database_evidence(
    resolved: Mapping[str, tuple[Path, str]],
    *,
    deployment_id: str,
    candidate_sha: str,
    expected_canary_identities: Mapping[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    for label in DATABASE_ENTRIES:
        if resolved[label][0].stat().st_size > MAX_DATABASE_ARTIFACT_BYTES:
            raise SafeValidationError(f"{label} exceeds the bounded PostgreSQL profile")
    payloads = {
        label: _load_json(resolved[label][0], label=label) for label in DATABASE_ENTRIES
    }
    inventory_labels = (
        "database_canary_baseline",
        "database_post_canary",
        "database_final",
    )
    tables: dict[str, dict[str, dict[str, Any]]] = {}
    workspace_identities: dict[str, dict[str, str]] = {}
    bindings: dict[str, dict[str, Any]] = {}
    for label in inventory_labels:
        (
            inventory_tables,
            inventory_identities,
            inventory_binding,
        ) = _validate_database_inventory(
            payloads[label],
            deployment_id=deployment_id,
            candidate_sha=candidate_sha,
            label=label,
            expected_canary_identities=expected_canary_identities,
        )
        tables[label] = inventory_tables
        workspace_identities[label] = inventory_identities
        bindings[label] = inventory_binding
    if not (
        set(tables["database_canary_baseline"])
        == set(tables["database_post_canary"])
        == set(tables["database_final"])
    ):
        raise SafeValidationError("PostgreSQL table inventory changed during canaries")
    if not (
        workspace_identities["database_canary_baseline"]
        == workspace_identities["database_post_canary"]
        == workspace_identities["database_final"]
    ):
        raise SafeValidationError(
            "PostgreSQL workspace identities changed during canaries"
        )

    ledger_path = resolved["andritz"][0].parent / "chat-ledger.json"
    if ledger_path.stat().st_size > MAX_DATABASE_LEDGER_BYTES:
        raise SafeValidationError("PostgreSQL comparison ledger exceeds its size bound")
    ledger = _load_json(ledger_path, label="andritz Chat ledger")
    run_id = _canonical_uuid(ledger.get("run_id"), label="andritz ledger run_id")
    invocation_ids = ledger.get("invocation_ids")
    if (
        ledger.get("kind") != "safe_controlled_chat_ledger"
        or ledger.get("outcome") != "passed"
        or ledger.get("commit_sha") != candidate_sha
        or ledger.get("deployment_id") != deployment_id
        or not isinstance(invocation_ids, list)
        or not invocation_ids
        or len(invocation_ids) > MAX_CONTROLLED_DATABASE_INVOCATIONS
        or len(invocation_ids) != len(set(map(str, invocation_ids)))
    ):
        raise SafeValidationError("PostgreSQL comparison Chat lineage is invalid")
    invocation_ids = [
        _canonical_uuid(value, label="andritz SkillInvocation id")
        for value in invocation_ids
    ]
    run_primary_key = canonical_sha256([run_id])
    invocation_primary_keys = frozenset(
        canonical_sha256([value]) for value in invocation_ids
    )
    ledger_sha256 = _file_sha256(ledger_path)
    expected_binding = {
        "provided": True,
        "ledger_sha256": ledger_sha256,
        "controlled_run_primary_key_sha256": run_primary_key,
        "controlled_invocation_count": len(invocation_ids),
        "controlled_invocation_primary_keys_sha256": canonical_sha256(
            sorted(invocation_primary_keys)
        ),
    }
    absent_binding = {
        "provided": False,
        "ledger_sha256": None,
        "controlled_run_primary_key_sha256": None,
        "controlled_invocation_count": 0,
        "controlled_invocation_primary_keys_sha256": None,
    }
    if bindings["database_canary_baseline"] != absent_binding:
        raise SafeValidationError(
            "PostgreSQL baseline must be captured without controlled-ledger details"
        )
    if (
        bindings["database_post_canary"] != expected_binding
        or bindings["database_final"] != expected_binding
    ):
        raise SafeValidationError(
            "PostgreSQL post-canary inventories are not bound to the Chat ledger"
        )
    if any(
        table["controlled_rows"]
        for table in tables["database_canary_baseline"].values()
    ):
        raise SafeValidationError("PostgreSQL baseline leaks controlled row details")

    comparison = payloads["database_post_canary_comparison"]
    comparison_keys = {
        "schema_version",
        "kind",
        "profile",
        "sha",
        "deployment_id",
        "result",
        "content_serialized",
        "checks",
        "baseline_sha256",
        "post_canary_sha256",
        "final_sha256",
        "baseline_business_sha256",
        "post_canary_business_sha256",
        "final_business_sha256",
        "controlled_run_primary_key_sha256",
        "controlled_invocation_primary_keys_sha256",
        "controlled_invocation_count",
        "ledger_sha256",
        "canary_workspaces",
        "canary_workspaces_sha256",
        "failed_tables",
        "stages",
        "summary",
    }
    checks = comparison.get("checks")
    if (
        set(comparison) != comparison_keys
        or comparison.get("schema_version") != DATABASE_SCHEMA_VERSION
        or comparison.get("kind") != "controlled_canary_database_comparison"
        or comparison.get("profile") != DATABASE_COMPARISON_PROFILE
        or comparison.get("sha") != candidate_sha
        or comparison.get("deployment_id") != deployment_id
        or comparison.get("result") != "passed"
        or comparison.get("content_serialized") is not False
        or not isinstance(checks, dict)
        or set(checks) != EXPECTED_DATABASE_CHECKS
        or any(value is not True for value in checks.values())
        or comparison.get("failed_tables") != []
    ):
        raise SafeValidationError(
            "PostgreSQL controlled-canary v2 comparison did not pass"
        )
    workspace_hashes = _database_workspace_hashes(
        comparison,
        inventory_identities=workspace_identities["database_canary_baseline"],
        expected_canary_identities=expected_canary_identities,
    )
    controlled_primary_keys = {
        "runs": frozenset({run_primary_key}),
        "skill_invocations": invocation_primary_keys,
    }
    baseline_tables = tables["database_canary_baseline"]
    expected_stages: dict[str, Any] = {}
    stage_additions: dict[str, dict[str, int]] = {}
    for inventory_label, stage_label in (
        ("database_post_canary", "post_canary"),
        ("database_final", "final"),
    ):
        expected_stage, additions = _database_expected_stage(
            label=inventory_label,
            baseline=baseline_tables,
            current=tables[inventory_label],
            controlled_primary_keys=controlled_primary_keys,
            canary_workspace_hashes=workspace_hashes,
        )
        expected_stages[stage_label] = expected_stage
        stage_additions[stage_label] = additions
    expected_additions = {
        "runs": 1,
        "skill_invocations": len(invocation_ids),
        "audit_logs": sum(
            expected_stages["final"]["audit_logs"][
                "canonical_navigation_delta_counts"
            ].values()
        ),
    }
    if (
        stage_additions["post_canary"] != expected_additions
        or stage_additions["final"] != expected_additions
        or set(
            expected_stages["final"]["audit_logs"]["canonical_navigation_delta_counts"]
        )
        != set(workspace_hashes)
    ):
        raise SafeValidationError(
            "PostgreSQL additions are not limited to the controlled canary"
        )
    if comparison.get("stages") != expected_stages:
        raise SafeValidationError(
            "PostgreSQL comparison stages were not independently reproduced"
        )

    post_payload = payloads["database_post_canary"]
    final_payload = payloads["database_final"]
    if post_payload.get("business_inventory_sha256") != final_payload.get(
        "business_inventory_sha256"
    ) or {
        name: post_payload["tables"][name]
        for name in post_payload["tables"]
        if name not in KEYCLOAK_VOLATILE_TABLES
    } != {
        name: final_payload["tables"][name]
        for name in final_payload["tables"]
        if name not in KEYCLOAK_VOLATILE_TABLES
    }:
        raise SafeValidationError(
            "PostgreSQL business state changed after the canaries"
        )

    baseline_path = resolved["database_canary_baseline"][0]
    post_path = resolved["database_post_canary"][0]
    final_path = resolved["database_final"][0]
    expected_file_hashes = {
        "baseline_sha256": _file_sha256(baseline_path),
        "post_canary_sha256": _file_sha256(post_path),
        "final_sha256": _file_sha256(final_path),
        "ledger_sha256": ledger_sha256,
    }
    if any(
        comparison.get(field) != value for field, value in expected_file_hashes.items()
    ):
        raise SafeValidationError(
            "PostgreSQL comparison is not bound to its source files"
        )
    if (
        comparison.get("baseline_business_sha256")
        != payloads["database_canary_baseline"].get("business_inventory_sha256")
        or comparison.get("post_canary_business_sha256")
        != post_payload.get("business_inventory_sha256")
        or comparison.get("final_business_sha256")
        != final_payload.get("business_inventory_sha256")
        or comparison.get("controlled_run_primary_key_sha256") != run_primary_key
        or comparison.get("controlled_invocation_primary_keys_sha256")
        != canonical_sha256(sorted(invocation_primary_keys))
        or comparison.get("controlled_invocation_count") != len(invocation_ids)
    ):
        raise SafeValidationError(
            "PostgreSQL comparison lineage or digests are inconsistent"
        )

    preexisting_rows = sum(
        int(table["aggregate"]["count"])
        for table_name, table in baseline_tables.items()
        if table_name not in KEYCLOAK_VOLATILE_TABLES
    )
    expected_summary = {
        "table_count": len(baseline_tables),
        "preexisting_rows": preexisting_rows,
        "added_rows": sum(expected_additions.values()),
        "added_rows_by_table": expected_additions,
        "modified_preexisting_rows": 0,
        "deleted_preexisting_rows": 0,
        "normalized_columns": {"users": ["last_login"]},
        "volatile_tables": sorted(KEYCLOAK_VOLATILE_TABLES),
        "accumulator_algorithm": DATABASE_ACCUMULATOR_ALGORITHM,
        "accumulator_domains": DATABASE_ACCUMULATOR_DOMAINS,
    }
    if comparison.get("summary") != expected_summary:
        raise SafeValidationError(
            "PostgreSQL comparison summary was not independently reproduced"
        )

    metadata = {
        label: _storage_metadata(*resolved[label]) for label in DATABASE_ENTRIES
    }
    digests = {
        "database_baseline_inventory": str(
            payloads["database_canary_baseline"]["inventory_sha256"]
        ),
        "database_post_canary_inventory": str(post_payload["inventory_sha256"]),
        "database_final_inventory": str(final_payload["inventory_sha256"]),
        "database_final_business_inventory": str(
            final_payload["business_inventory_sha256"]
        ),
        "database_comparison": _file_sha256(
            resolved["database_post_canary_comparison"][0]
        ),
    }
    return metadata, digests


def _storage_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _storage_digest(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise SafeValidationError(f"{label} digest is invalid")
    return value


def _validate_object_store_inventory(value: Mapping[str, Any], *, label: str) -> str:
    expected_fields = ["path_sha256", "size", "content_sha256"]
    entries = value.get("entries")
    if (
        value.get("algorithm") != "sha256-merkle-v1"
        or value.get("entry_fields") != expected_fields
        or not isinstance(entries, list)
    ):
        raise SafeValidationError(f"{label} ObjectStore inventory is invalid")
    identities: list[str] = []
    total_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != set(expected_fields):
            raise SafeValidationError(f"{label} ObjectStore entry is invalid")
        identities.append(_storage_digest(entry.get("path_sha256"), label=label))
        _storage_digest(entry.get("content_sha256"), label=label)
        if not _storage_nonnegative_int(entry.get("size")):
            raise SafeValidationError(f"{label} ObjectStore size is invalid")
        total_bytes += entry["size"]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise SafeValidationError(f"{label} ObjectStore identities are invalid")
    digest = _storage_digest(value.get("content_manifest_sha256"), label=label)
    if (
        value.get("files") != len(entries)
        or value.get("bytes") != total_bytes
        or digest != canonical_sha256(entries)
    ):
        raise SafeValidationError(f"{label} ObjectStore aggregates are inconsistent")
    return digest


def _validate_minio_inventory(value: Mapping[str, Any], *, label: str) -> str:
    expected_fields = [
        "object_id_sha256",
        "version_id_sha256",
        "size",
        "etag_sha256",
        "last_modified",
        "is_latest",
        "delete_marker",
    ]
    entries = value.get("entries")
    if (
        value.get("algorithm") != "s3-version-inventory-sha256-v1"
        or value.get("entry_fields") != expected_fields
        or not isinstance(entries, list)
    ):
        raise SafeValidationError(f"{label} MinIO inventory is invalid")
    identities: list[str] = []
    total_bytes = 0
    latest_versions = 0
    delete_markers = 0
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != len(expected_fields):
            raise SafeValidationError(f"{label} MinIO entry is invalid")
        object_id, version_id, size, etag, modified, is_latest, delete_marker = entry
        _storage_digest(object_id, label=label)
        if version_id is not None:
            _storage_digest(version_id, label=label)
        _storage_digest(etag, label=label)
        if (
            not _storage_nonnegative_int(size)
            or not isinstance(modified, str)
            or not modified
            or not isinstance(is_latest, bool)
            or not isinstance(delete_marker, bool)
            or (delete_marker and size != 0)
        ):
            raise SafeValidationError(f"{label} MinIO entry metadata is invalid")
        identities.append(f"{object_id}:{version_id or ''}")
        total_bytes += 0 if delete_marker else size
        latest_versions += int(is_latest)
        delete_markers += int(delete_marker)
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise SafeValidationError(f"{label} MinIO identities are invalid")
    _storage_digest(value.get("bucket_id_sha256"), label=label)
    digest = _storage_digest(value.get("inventory_sha256"), label=label)
    if (
        value.get("versions") != len(entries)
        or value.get("bytes") != total_bytes
        or value.get("latest_versions") != latest_versions
        or value.get("delete_markers") != delete_markers
        or digest != canonical_sha256(entries)
    ):
        raise SafeValidationError(f"{label} MinIO aggregates are inconsistent")
    return digest


def _validate_object_store_bindings(value: object, *, label: str) -> str:
    if not isinstance(value, dict) or set(value) != {"backend", "worker_cpu"}:
        raise SafeValidationError(f"{label} ObjectStore bindings are invalid")
    if value["backend"] != value["worker_cpu"]:
        raise SafeValidationError(
            f"{label} backend and worker ObjectStore bindings differ"
        )
    binding = value["backend"]
    expected_keys = {
        "backend",
        "local_path_id_sha256",
        "s3_bucket_id_sha256",
        "s3_endpoint_id_sha256",
    }
    if not isinstance(binding, dict) or set(binding) != expected_keys:
        raise SafeValidationError(f"{label} ObjectStore binding is invalid")
    if binding.get("backend") == "local":
        _storage_digest(binding.get("local_path_id_sha256"), label=label)
        if (
            binding.get("s3_bucket_id_sha256") is not None
            or binding.get("s3_endpoint_id_sha256") is not None
        ):
            raise SafeValidationError(f"{label} local ObjectStore binding is invalid")
    elif binding.get("backend") == "s3":
        _storage_digest(binding.get("s3_bucket_id_sha256"), label=label)
        _storage_digest(binding.get("s3_endpoint_id_sha256"), label=label)
        if binding.get("local_path_id_sha256") is not None:
            raise SafeValidationError(f"{label} S3 ObjectStore binding is invalid")
    else:
        raise SafeValidationError(f"{label} ObjectStore backend is invalid")
    return canonical_sha256(value)


def _validate_storage(
    before_path: Path,
    after_path: Path,
    comparison_path: Path,
) -> dict[str, str]:
    before = _storage_payload(
        before_path,
        label="storage_before",
        expected_profile=STORAGE_PROFILE,
    )
    after = _storage_payload(
        after_path,
        label="storage_after",
        expected_profile=STORAGE_PROFILE,
    )
    comparison = _storage_payload(
        comparison_path,
        label="storage_comparison",
        expected_profile=STORAGE_EXACT_COMPARISON_PROFILE,
    )

    sections = {
        "secure_deposit": ("Secure Deposit", "manifest_sha256"),
        "object_store": ("ObjectStore", "content_manifest_sha256"),
        "minio": ("MinIO", "inventory_sha256"),
        "qdrant": ("Qdrant", "inventory_sha256"),
    }
    digests: dict[str, str] = {}
    for key, (display_name, digest_key) in sections.items():
        before_section = before.get(key)
        after_section = after.get(key)
        if not isinstance(before_section, dict) or not isinstance(after_section, dict):
            raise SafeValidationError(f"{display_name} storage section is invalid")
        before_digest = before_section.get(digest_key)
        after_digest = after_section.get(digest_key)
        if (
            not isinstance(before_digest, str)
            or SHA256_RE.fullmatch(before_digest) is None
            or not isinstance(after_digest, str)
            or SHA256_RE.fullmatch(after_digest) is None
        ):
            raise SafeValidationError(f"{display_name} storage digest is invalid")
        if before_section != after_section:
            raise SafeValidationError(f"{display_name} changed during deployment")
        if key == "object_store":
            before_digest = _validate_object_store_inventory(
                before_section, label="before"
            )
            _validate_object_store_inventory(after_section, label="after")
        elif key == "minio":
            before_digest = _validate_minio_inventory(before_section, label="before")
            _validate_minio_inventory(after_section, label="after")
        elif key == "qdrant":
            expected_inventory = canonical_sha256(
                {
                    "collections": before_section.get("collections"),
                    "aliases": before_section.get("aliases"),
                }
            )
            if before_digest != expected_inventory:
                raise SafeValidationError("Qdrant inventory digest is inconsistent")
        digests[f"{key}_before"] = before_digest
        digests[f"{key}_after"] = after_digest

    before_bindings = before.get("object_store_bindings")
    after_bindings = after.get("object_store_bindings")
    before_bindings_digest = _validate_object_store_bindings(
        before_bindings, label="before"
    )
    after_bindings_digest = _validate_object_store_bindings(
        after_bindings, label="after"
    )
    if before_bindings != after_bindings:
        raise SafeValidationError("ObjectStore bindings changed during deployment")
    digests["object_store_bindings_before"] = before_bindings_digest
    digests["object_store_bindings_after"] = after_bindings_digest

    before_container_mounts = before.get("container_mounts")
    after_container_mounts = after.get("container_mounts")
    if (
        not isinstance(before_container_mounts, dict)
        or not before_container_mounts
        or any(
            not isinstance(value, list) for value in before_container_mounts.values()
        )
        or not isinstance(after_container_mounts, dict)
        or not after_container_mounts
        or any(not isinstance(value, list) for value in after_container_mounts.values())
        or not REQUIRED_STORAGE_CONTAINERS.issubset(before_container_mounts)
        or not REQUIRED_STORAGE_CONTAINERS.issubset(after_container_mounts)
    ):
        raise SafeValidationError("container mount inventory is invalid")
    if before_container_mounts != after_container_mounts:
        raise SafeValidationError("container mounts changed during deployment")
    container_mounts_digest = canonical_sha256(before_container_mounts)
    digests["container_mounts_before"] = container_mounts_digest
    digests["container_mounts_after"] = canonical_sha256(after_container_mounts)

    stable_mounts: dict[str, dict[str, Any]] = {}
    for snapshot_label, snapshot in (("before", before), ("after", after)):
        mounts = snapshot.get("mounts")
        if not isinstance(mounts, dict):
            raise SafeValidationError(
                f"{snapshot_label} stable mount identity is missing"
            )
        snapshot_stable: dict[str, dict[str, Any]] = {}
        for mount_name in ("data", "secure_deposit"):
            mount = mounts.get(mount_name)
            if not isinstance(mount, dict):
                raise SafeValidationError(
                    f"{snapshot_label} {mount_name} mount identity is missing"
                )
            identity = {field: mount.get(field) for field in STABLE_MOUNT_FIELDS}
            if (
                not all(
                    identity[field] not in (None, "") for field in STABLE_MOUNT_FIELDS
                )
                or identity["source_matches_expected"] is not True
                or not isinstance(identity["device_id"], int)
                or identity["device_id"] <= 0
            ):
                raise SafeValidationError(
                    f"{snapshot_label} {mount_name} backing device is unverified"
                )
            snapshot_stable[mount_name] = identity
        if (
            snapshot_stable["data"]["normalized_source"]
            == snapshot_stable["secure_deposit"]["normalized_source"]
            or snapshot_stable["data"]["expected_source"]
            == snapshot_stable["secure_deposit"]["expected_source"]
            or snapshot_stable["data"]["device_id"]
            == snapshot_stable["secure_deposit"]["device_id"]
            or snapshot_stable["data"]["target"]
            == snapshot_stable["secure_deposit"]["target"]
        ):
            raise SafeValidationError(
                f"{snapshot_label} data and Secure Deposit are not isolated mounts"
            )
        stable_mounts[snapshot_label] = snapshot_stable
    if stable_mounts["before"] != stable_mounts["after"]:
        raise SafeValidationError("stable mount identity changed during deployment")
    stable_mounts_digest = canonical_sha256(stable_mounts["before"])
    digests["stable_mounts_before"] = stable_mounts_digest
    digests["stable_mounts_after"] = canonical_sha256(stable_mounts["after"])

    checks = comparison.get("checks")
    check_names = (
        {item.get("name") for item in checks if isinstance(item, dict)}
        if isinstance(checks, list)
        else set()
    )
    if (
        comparison.get("result") != "passed"
        or comparison.get("failed_checks") != []
        or not isinstance(checks, list)
        or not checks
        or any(
            not isinstance(item, dict) or item.get("passed") is not True
            for item in checks
        )
        or len(check_names) != len(checks)
        or check_names != EXPECTED_STORAGE_COMPARISON_CHECKS
    ):
        raise SafeValidationError("storage comparison did not pass")
    return digests


def _validate_sftp_closed_payload(
    payload: Mapping[str, Any],
    *,
    label: str,
    deployment_id: str,
    candidate_sha: str,
    sftp_sha: str,
) -> dict[str, Any]:
    if (
        payload.get("schema_version") != 2
        or payload.get("kind") != "agentium_sftp_deploy_boundary"
        or payload.get("profile") != "agentium-sftp-closed-boundary-v2"
        or payload.get("sha") != candidate_sha
        or payload.get("sftp_sha") != sftp_sha
        or payload.get("deployment_id") != deployment_id
        or payload.get("result") != "passed"
        or payload.get("credentials_used") is not False
        or payload.get("content_serialized") is not False
        or payload.get("raw_network_data_serialized") is not False
        or payload.get("assurance")
        != "release_a_sftp_pinned_stopped_restart_disabled_ingress_rejected_storage_read_only_without_positive_login"
        or payload.get("proof_ceiling") != "runner_verified"
    ):
        raise SafeValidationError(f"{label} SFTP closed-boundary identity is invalid")

    container = payload.get("container")
    legacy = payload.get("legacy_service")
    ingress = payload.get("ingress_gate")
    network = payload.get("network")
    deposit = payload.get("secure_deposit")
    host_key = payload.get("host_key")
    revision_binding = payload.get("revision_binding")
    if not all(
        isinstance(value, dict)
        for value in (
            container,
            legacy,
            ingress,
            network,
            deposit,
            host_key,
            revision_binding,
        )
    ):
        raise SafeValidationError(f"{label} SFTP closed-boundary sections are invalid")
    assert isinstance(container, dict)
    assert isinstance(legacy, dict)
    assert isinstance(ingress, dict)
    assert isinstance(network, dict)
    assert isinstance(deposit, dict)
    assert isinstance(host_key, dict)
    assert isinstance(revision_binding, dict)

    container_id = str(container.get("container_id") or "")
    image_id = str(container.get("image_id") or "")
    if (
        DOCKER_CONTAINER_ID_RE.fullmatch(container_id) is None
        or DOCKER_IMAGE_ID_RE.fullmatch(image_id) is None
        or container.get("running") is not False
        or container.get("paused") is not False
        or container.get("process_count") != 0
        or container.get("secure_deposit_open_fd_count") != 0
        or container.get("restart_policy_disabled") is not True
        or container.get("revision") != sftp_sha
    ):
        raise SafeValidationError(f"{label} SFTP stopped-container contract is invalid")
    if legacy != {"active": False, "enabled": False}:
        raise SafeValidationError(f"{label} legacy SFTP service is not disabled")
    if set(ingress) != {
        "ipv4_input",
        "ipv4_docker_user",
        "ipv6_input",
        "ipv6_docker_user",
    } or any(value is not True for value in ingress.values()):
        raise SafeValidationError(f"{label} SFTP IPv4/IPv6 ingress gate is incomplete")
    if network != {
        "listener_count": 0,
        "established_connection_count": 0,
        "ipv4_connect_rejected": True,
        "ipv6_connect_rejected": True,
    }:
        raise SafeValidationError(f"{label} SFTP transport is not fully closed")
    device_id = deposit.get("device_id")
    if (
        set(deposit)
        != {
            "source_matches_expected",
            "autonomous_mountpoint",
            "read_only",
            "device_id",
        }
        or deposit.get("source_matches_expected") is not True
        or deposit.get("autonomous_mountpoint") is not True
        or deposit.get("read_only") is not True
        or not isinstance(device_id, int)
        or isinstance(device_id, bool)
        or device_id <= 0
    ):
        raise SafeValidationError(f"{label} Secure Deposit boundary is invalid")
    fingerprint = str(host_key.get("fingerprint") or "")
    if (
        host_key.get("present") is not True
        or host_key.get("nonempty") is not True
        or host_key.get("regular_file") is not True
        or host_key.get("symlink") is not False
        or host_key.get("algorithm") != "ssh-ed25519"
        or SSH_FINGERPRINT_RE.fullmatch(fingerprint) is None
    ):
        raise SafeValidationError(f"{label} SFTP host-key boundary is invalid")
    if revision_binding != {
        "candidate_sha": candidate_sha,
        "client_sha": candidate_sha,
        "sftp_sha": sftp_sha,
        "revisions_distinct": True,
        "client_image_revision_verified": False,
        "sftp_image_revision_verified": True,
    }:
        raise SafeValidationError(f"{label} SFTP revision binding is invalid")
    return {
        "container_id": container_id,
        "image_id": image_id,
        "sftp_sha": sftp_sha,
        "secure_deposit_device_id": device_id,
        "host_key_fingerprint_sha256": hashlib.sha256(fingerprint.encode()).hexdigest(),
    }


def _validate_sftp_closed_evidence(
    resolved: Mapping[str, tuple[Path, str]],
    *,
    deployment_id: str,
    candidate_sha: str,
    sftp_sha: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    identities: dict[str, dict[str, Any]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    digests: dict[str, str] = {}
    for label in SFTP_ENTRIES:
        path, relative = resolved[label]
        payload = _load_json(path, label=label)
        identities[label] = _validate_sftp_closed_payload(
            payload,
            label=label,
            deployment_id=deployment_id,
            candidate_sha=candidate_sha,
            sftp_sha=sftp_sha,
        )
        digest = _file_sha256(path)
        metadata[label] = {
            "format": "json",
            "outcome": "passed",
            "sha256": digest,
            "bytes": path.stat().st_size,
            "location_sha256": hashlib.sha256(relative.encode()).hexdigest(),
            **identities[label],
        }
        digests[label] = digest
    if identities["sftp_closed_before"] != identities["sftp_closed_after"]:
        raise SafeValidationError(
            "SFTP closed-boundary identity changed during canaries"
        )
    if digests["sftp_closed_before"] == digests["sftp_closed_after"]:
        raise SafeValidationError("SFTP closed-boundary captures must be independent")
    return metadata, digests


def _resolve_entries(
    root: Path,
    paths: Mapping[str, Path],
    *,
    now: datetime,
) -> dict[str, tuple[Path, str]]:
    if set(paths) != set(ALL_ENTRIES):
        raise SafeValidationError("the required validation entries are incomplete")
    resolved: dict[str, tuple[Path, str]] = {}
    for label in ALL_ENTRIES:
        path, relative = _entry_path(
            paths[label],
            root,
            label=label,
            max_bytes=(
                MAX_STORAGE_BYTES if label in STORAGE_ENTRIES else MAX_PROOF_BYTES
            ),
        )
        details = _assert_not_writable_by_others(path, label=f"{label} evidence")
        _assert_fresh(details, now=now, label=f"{label} evidence")
        resolved[label] = (path, relative)
    evidence_realpaths = [resolved[label][0] for label in ALL_ENTRIES]
    if len(set(evidence_realpaths)) != len(evidence_realpaths):
        raise SafeValidationError("validation entries cannot reuse the same realpath")
    return resolved


def _evidence_metadata(
    resolved: Mapping[str, tuple[Path, str]],
    *,
    deployment_id: str,
    candidate_sha: str,
    sftp_sha: str,
    expected_canary_identities: Mapping[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    metadata = {
        label: _proof_metadata(
            resolved[label][0],
            resolved[label][1],
            label=label,
            candidate_sha=candidate_sha,
        )
        for label in PROOF_CHECKS
    }
    proof_digests = [metadata[label]["sha256"] for label in PROOF_CHECKS]
    if len(set(proof_digests)) != len(proof_digests):
        raise SafeValidationError("proof entries cannot reuse the same digest")
    for label in ("provenance", "showcase"):
        if metadata[label]["commit_sha_checked"] is not True:
            raise SafeValidationError(
                f"{label} proof must declare the candidate commit SHA"
            )
    storage_digests = _validate_storage(
        resolved["storage_before"][0],
        resolved["storage_after"][0],
        resolved["storage_comparison"][0],
    )
    for label in STORAGE_ENTRIES:
        metadata[label] = _storage_metadata(*resolved[label])
    sftp_metadata, sftp_digests = _validate_sftp_closed_evidence(
        resolved,
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
        sftp_sha=sftp_sha,
    )
    metadata.update(sftp_metadata)
    storage_digests.update(sftp_digests)
    qdrant_metadata, qdrant_digests = _validate_qdrant_evidence(
        resolved,
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
    )
    metadata.update(qdrant_metadata)
    storage_digests.update(qdrant_digests)
    database_metadata, database_digests = _validate_database_evidence(
        resolved,
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
        expected_canary_identities=expected_canary_identities,
    )
    metadata.update(database_metadata)
    storage_digests.update(database_digests)
    return metadata, storage_digests


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() and path.is_symlink():
        raise SafeValidationError("validation artifact cannot be a symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".validation.", suffix=".tmp", dir=path.parent
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
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def build_validation(
    *,
    deployment_id: str,
    candidate_sha: str,
    sftp_sha: str,
    database_revision: str,
    deployment_dir: Path,
    entries: Mapping[str, Path],
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_identity(deployment_id, candidate_sha, database_revision)
    if FULL_SHA_RE.fullmatch(sftp_sha) is None or sftp_sha == candidate_sha:
        raise SafeValidationError("SFTP Release A SHA is invalid")
    root = _deployment_root(deployment_dir)
    generated = (now or _utc_now()).astimezone(timezone.utc)
    runtime_env = _runtime_env_attestation(
        root,
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
        sftp_sha=sftp_sha,
    )
    expected_canary_identities = _workspace_target_hashes(
        root,
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
    )
    resolved = _resolve_entries(root, entries, now=generated)
    evidence, storage_digests = _evidence_metadata(
        resolved,
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
        sftp_sha=sftp_sha,
        expected_canary_identities=expected_canary_identities,
    )
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "kind": "safe_deployment_validation",
        "deployment_id": deployment_id,
        "candidate_sha": candidate_sha,
        "sftp_sha": sftp_sha,
        "database_revision": database_revision,
        "deployment_dir": str(root),
        "generated_at": _format_time(generated),
        "max_age_seconds": MAX_AGE_SECONDS,
        "result": "passed",
        "checks": {name: True for name in REQUIRED_CHECKS},
        "runtime_env": runtime_env,
        "evidence": evidence,
        "digests": storage_digests,
    }
    _write_atomic(root / "validation.json", artifact)
    return artifact


def verify_validation(
    *,
    deployment_id: str,
    candidate_sha: str,
    sftp_sha: str,
    database_revision: str,
    deployment_dir: Path,
    entries: Mapping[str, Path],
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_identity(deployment_id, candidate_sha, database_revision)
    if FULL_SHA_RE.fullmatch(sftp_sha) is None or sftp_sha == candidate_sha:
        raise SafeValidationError("SFTP Release A SHA is invalid")
    root = _deployment_root(deployment_dir)
    current_time = (now or _utc_now()).astimezone(timezone.utc)
    artifact_path, _ = _entry_path(
        root / "validation.json", root, label="validation artifact"
    )
    artifact_details = _assert_not_writable_by_others(
        artifact_path, label="validation artifact"
    )
    _assert_fresh(artifact_details, now=current_time, label="validation artifact")
    artifact = _load_json(artifact_path, label="validation artifact")

    generated_at = _parse_time(
        artifact.get("generated_at"), label="validation artifact"
    )
    generated_age = (current_time - generated_at).total_seconds()
    if generated_age < -MAX_FUTURE_SKEW_SECONDS or generated_age > MAX_AGE_SECONDS:
        raise SafeValidationError("validation artifact is stale or future-dated")
    expected_identity = {
        "schema_version": SCHEMA_VERSION,
        "kind": "safe_deployment_validation",
        "deployment_id": deployment_id,
        "candidate_sha": candidate_sha,
        "sftp_sha": sftp_sha,
        "database_revision": database_revision,
        "deployment_dir": str(root),
        "max_age_seconds": MAX_AGE_SECONDS,
        "result": "passed",
    }
    for key, expected in expected_identity.items():
        if artifact.get(key) != expected:
            raise SafeValidationError(f"validation artifact {key} does not match")
    checks = artifact.get("checks")
    if (
        not isinstance(checks, dict)
        or set(checks) != set(REQUIRED_CHECKS)
        or any(checks.get(name) is not True for name in REQUIRED_CHECKS)
    ):
        raise SafeValidationError("validation artifact lacks a required passing check")

    runtime_env = _runtime_env_attestation(
        root,
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
        sftp_sha=sftp_sha,
    )
    expected_canary_identities = _workspace_target_hashes(
        root,
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
    )
    if artifact.get("runtime_env") != runtime_env:
        raise SafeValidationError("validation runtime env attestation changed")

    resolved = _resolve_entries(root, entries, now=current_time)
    evidence, storage_digests = _evidence_metadata(
        resolved,
        deployment_id=deployment_id,
        candidate_sha=candidate_sha,
        sftp_sha=sftp_sha,
        expected_canary_identities=expected_canary_identities,
    )
    if artifact.get("evidence") != evidence:
        raise SafeValidationError("validation evidence hashes changed")
    if artifact.get("digests") != storage_digests:
        raise SafeValidationError("validation storage digests changed")
    return dict(artifact)


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--sha", dest="candidate_sha", required=True)
    parser.add_argument("--sftp-sha", required=True)
    parser.add_argument("--alembic-revision", dest="database_revision", required=True)
    parser.add_argument("--deployment-dir", type=Path, required=True)
    parser.add_argument("--storage-before", type=Path, required=True)
    parser.add_argument("--storage-after", type=Path, required=True)
    parser.add_argument("--storage-comparison", type=Path, required=True)
    for check in PROOF_CHECKS:
        parser.add_argument(f"--{check}", type=Path, required=True)
    for entry in QDRANT_ENTRIES:
        parser.add_argument(f"--{entry.replace('_', '-')}", type=Path, required=True)
    for entry in DATABASE_ENTRIES:
        parser.add_argument(f"--{entry.replace('_', '-')}", type=Path, required=True)
    for entry in SFTP_ENTRIES:
        parser.add_argument(f"--{entry.replace('_', '-')}", type=Path, required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    _add_common_arguments(commands.add_parser("build", help="assemble validation.json"))
    _add_common_arguments(
        commands.add_parser("verify", help="verify validation.json and every input")
    )
    return parser


def _entries_from_args(args: argparse.Namespace) -> dict[str, Path]:
    return {
        **{check: getattr(args, check) for check in PROOF_CHECKS},
        **{entry: getattr(args, entry) for entry in QDRANT_ENTRIES},
        **{entry: getattr(args, entry) for entry in DATABASE_ENTRIES},
        **{entry: getattr(args, entry) for entry in SFTP_ENTRIES},
        "storage_before": args.storage_before,
        "storage_after": args.storage_after,
        "storage_comparison": args.storage_comparison,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    operation = build_validation if args.command == "build" else verify_validation
    try:
        operation(
            deployment_id=args.deployment_id,
            candidate_sha=args.candidate_sha,
            sftp_sha=args.sftp_sha,
            database_revision=args.database_revision,
            deployment_dir=args.deployment_dir,
            entries=_entries_from_args(args),
        )
    except SafeValidationError as exc:
        print(f"XX  Safe validation {args.command} failed: {exc}", file=sys.stderr)
        return 1
    print(f"OK  Safe validation {args.command} passed for {args.deployment_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
