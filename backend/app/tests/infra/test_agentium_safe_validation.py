"""Contracts for the evidence-bound VM deployment validation artifact."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[4]
SHA = "a" * 40
SFTP_SHA = "9" * 40
REVISION = "076_decision_scenario_lineage"
DEPLOYMENT_ID = "20260722T160000Z-aaaaaaaaaaaa"
RUN_ID = "11111111-1111-4111-8111-111111111111"
WORKSPACE_ID = "22222222-2222-4222-8222-222222222222"
SYSTEM_ID = "55555555-5555-4555-8555-555555555555"
CAPABILITY_ID = "66666666-6666-4666-8666-666666666666"
KNOWLEDGE_COLLECTION_ID = "77777777-7777-4777-8777-777777777777"
ARTIFACT_KEY = "membrane/andritz/provenance.json"
ARTIFACT_CONTENT_SHA256 = "f" * 64
ARTIFACT_SIZE = 432
ANDRITZ_TEST_TITLES = (
    "Andritz business preview exposes the three-app shell",
    "the three Andritz surfaces survive deep links, history and reload",
    "a forced access-token expiry retries inside the selected workspace",
    "business preview redirects advanced routes while admin mode keeps the full cockpit",
    "deployed Andritz profile, entitlements and active Systems match the Lot 4 contract",
    "resolved navigation is persisted with canonical routes and no user identity",
)
QDRANT_CONTAINER_ID = "1" * 64
QDRANT_IMAGE_ID = "sha256:" + "2" * 64
BACKEND_CONTAINER_ID = "b" * 12
WORKER_CONTAINER_ID = "c" * 12
SFTP_CONTAINER_ID = "d" * 64
SFTP_IMAGE_ID = "sha256:" + "e" * 64
SFTP_HOST_KEY_FINGERPRINT = "SHA256:" + "A" * 43
INVOCATION_IDS = (
    "33333333-3333-4333-8333-333333333331",
    "33333333-3333-4333-8333-333333333332",
    "33333333-3333-4333-8333-333333333333",
)
CHAT_LINEAGE_CHECK_NAMES = (
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
)
CANARY_WORKSPACES = {
    "alpha": "44444444-4444-4444-8444-444444444441",
    "bravo": "44444444-4444-4444-8444-444444444442",
    "charlie": "44444444-4444-4444-8444-444444444443",
    "delta": "44444444-4444-4444-8444-444444444444",
}
WORKSPACE_TARGET_SLUGS = {
    "showcase": "alpha",
    "andritz": "bravo",
    "sentinel": "charlie",
    "octocity": "delta",
}
RUNTIME_ENV_SECRET = "runtime-env-super-secret-value"
RUNTIME_ENV_SOURCE_PATH = "/private/live/customer-runtime.env"


def _load() -> ModuleType:
    name = "agentium_safe_validation_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts/agentium_safe_validation.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module() -> ModuleType:
    return _load()


def _write(path: Path, value: object | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if isinstance(value, str):
        path.write_text(value, encoding="utf-8")
    else:
        path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
    return path


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _storage_canary_comparison() -> dict[str, object]:
    empty = _canonical_sha256([])
    object_fields = ["path_sha256", "size", "content_sha256"]
    minio_fields = [
        "object_id_sha256",
        "version_id_sha256",
        "size",
        "etag_sha256",
        "last_modified",
        "is_latest",
        "delete_marker",
    ]
    stable_fields = [
        "source",
        "normalized_source",
        "expected_source",
        "source_matches_expected",
        "target",
        "fstype",
        "device_id",
    ]
    check_names = [
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
        *[
            f"mounts.{mount}.{field}"
            for mount in ("data", "secure_deposit")
            for field in stable_fields
        ],
    ]
    entry = {
        "path_sha256": hashlib.sha256(ARTIFACT_KEY.encode()).hexdigest(),
        "size": ARTIFACT_SIZE,
        "content_sha256": ARTIFACT_CONTENT_SHA256,
    }
    return {
        "schema_version": 1,
        "profile": "agentium-storage-object-additions-v1",
        "assurance": "cryptographic_entry_inclusion",
        "result": "passed",
        "failed_checks": [],
        "checks": [{"name": name, "passed": True} for name in check_names],
        "additions": {
            "object_store": {
                "count": 1,
                "bytes": ARTIFACT_SIZE,
                "entry_fields": object_fields,
                "entries": [entry],
                "digest": _canonical_sha256([entry]),
            },
            "minio": {
                "count": 0,
                "bytes": 0,
                "entry_fields": minio_fields,
                "entries": [],
                "digest": empty,
            },
        },
        "deletions": {
            "object_store": {
                "count": 0,
                "bytes": 0,
                "entry_fields": object_fields,
                "entries": [],
                "digest": empty,
            },
            "minio": {
                "count": 0,
                "bytes": 0,
                "entry_fields": minio_fields,
                "entries": [],
                "digest": empty,
            },
        },
        "modifications": {
            "object_store": {
                "count": 0,
                "entry_fields": [
                    "path_sha256",
                    "before_entry_sha256",
                    "after_entry_sha256",
                ],
                "entries": [],
                "digest": empty,
            },
            "minio": {
                "count": 0,
                "entry_fields": [
                    "object_id_sha256",
                    "version_id_sha256",
                    "before_entry_sha256",
                    "after_entry_sha256",
                ],
                "entries": [],
                "digest": empty,
            },
        },
    }


def _junit(
    *,
    sha: str = SHA,
    failure: bool = False,
    skipped: bool = False,
    name: str = "tenant",
) -> str:
    child = '<failure message="no" />' if failure else "<skipped />" if skipped else ""
    return (
        f'<testsuite tests="1" failures="{int(failure)}" errors="0" skipped="{int(skipped)}">'
        f'<testcase classname="safe" name="{name}">{child}<properties>'
        f'<property name="commit_sha" value="{sha}" />'
        "</properties></testcase>"
        "</testsuite>"
    )


def _qdrant_probe(access: str) -> dict[str, object]:
    read_only = access == "read-only"
    return {
        "unauthenticated_read_status": 401,
        "authenticated_read_status": 200,
        "absent_guard_before_status": 404,
        "delete_status": 403 if read_only else 404,
        "absent_guard_after_status": 404,
        "collection_count": 33,
        "expected_access": access,
        "read_allowed": True,
        "write_rejected": read_only,
        "write_route_authorized": not read_only,
        "guard_remained_absent": True,
    }


def _qdrant_host_barrier(access: str) -> dict[str, object]:
    read_only = access == "read-only"
    identities = {
        "agentium-backend": {
            "container_id": BACKEND_CONTAINER_ID,
            "docker_inspect_id": "b" * 64,
        },
        "agentium-worker-cpu": {
            "container_id": WORKER_CONTAINER_ID,
            "docker_inspect_id": "c" * 64,
        },
    }
    return {
        "schema_version": 1,
        "kind": "agentium_qdrant_write_barrier",
        "profile": (
            "agentium-qdrant-read-only-validation-v1"
            if read_only
            else "agentium-qdrant-admin-ready-v1"
        ),
        "deployment_id": DEPLOYMENT_ID,
        "sha": SHA,
        "captured_at": "2026-07-22T16:00:00Z",
        "result": "passed",
        "qdrant": {
            "container_id": QDRANT_CONTAINER_ID,
            "image_id": QDRANT_IMAGE_ID,
            "image": "qdrant/qdrant:v1.12.5-unprivileged",
            "internal_network_present": True,
            "port_contract": {
                "published_bindings_checked": 2,
                "loopback_only": True,
            },
            "admin_key_present": True,
            "read_only_key_present": True,
            "keys_distinct": True,
            "cluster_mode": "standalone",
        },
        "clients": {
            "expected_count": 2,
            "identities": identities,
            "container_id_by_name": {
                name: identity["container_id"] for name, identity in identities.items()
            },
            "all_running": True,
            "expected_access": access,
            "all_expected_access": True,
            "all_read_only": read_only,
            "all_admin_ready": not read_only,
        },
        "network_guard": {
            "running_peer_count": 2,
            "credentialed_peer_count": 2,
            "non_read_only_peer_count": 0,
        },
        "probe": _qdrant_probe(access),
        "secrets_serialized": False,
        "assurance": (
            "server_key_separation_plus_negative_write_probe"
            if read_only
            else "server_key_separation_plus_admin_ready_probe"
        ),
        "proof_ceiling": "runner_verified",
        "limitations": [],
    }


def _qdrant_client_probe(container_id: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "agentium_qdrant_client_write_barrier",
        "profile": "agentium-qdrant-read-only-client-v1",
        "deployment_id": DEPLOYMENT_ID,
        "sha": SHA,
        "captured_at": "2026-07-22T16:00:00Z",
        "result": "passed",
        "client_identity": {"container_id": container_id},
        "probe": _qdrant_probe("read-only"),
        "secrets_serialized": False,
        "assurance": "server_rejected_absent_target_delete",
    }


def _sftp_closed_boundary(captured_at: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "agentium_sftp_deploy_boundary",
        "profile": "agentium-sftp-closed-boundary-v2",
        "sha": SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "captured_at": captured_at,
        "result": "passed",
        "container": {
            "container_id": SFTP_CONTAINER_ID,
            "image_id": SFTP_IMAGE_ID,
            "revision": SFTP_SHA,
            "running": False,
            "paused": False,
            "process_count": 0,
            "secure_deposit_open_fd_count": 0,
            "restart_policy_disabled": True,
        },
        "legacy_service": {"active": False, "enabled": False},
        "ingress_gate": {
            "ipv4_input": True,
            "ipv4_docker_user": True,
            "ipv6_input": True,
            "ipv6_docker_user": True,
        },
        "network": {
            "listener_count": 0,
            "established_connection_count": 0,
            "ipv4_connect_rejected": True,
            "ipv6_connect_rejected": True,
        },
        "secure_deposit": {
            "source_matches_expected": True,
            "autonomous_mountpoint": True,
            "read_only": True,
            "device_id": 3,
        },
        "host_key": {
            "present": True,
            "nonempty": True,
            "regular_file": True,
            "symlink": False,
            "algorithm": "ssh-ed25519",
            "fingerprint": SFTP_HOST_KEY_FINGERPRINT,
        },
        "revision_binding": {
            "candidate_sha": SHA,
            "client_sha": SHA,
            "sftp_sha": SFTP_SHA,
            "revisions_distinct": True,
            "client_image_revision_verified": False,
            "sftp_image_revision_verified": True,
        },
        "credentials_used": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
        "assurance": "release_a_sftp_pinned_stopped_restart_disabled_ingress_rejected_storage_read_only_without_positive_login",
        "proof_ceiling": "runner_verified",
    }


def _storage_snapshot() -> dict[str, object]:
    object_entries: list[dict[str, object]] = []
    minio_entries: list[list[object]] = []
    qdrant: dict[str, object] = {
        "collections": [{"name": "opaque", "status": "green", "points_count": 12}],
        "aliases": [{"alias_name": "current", "collection_name": "opaque"}],
    }
    qdrant["inventory_sha256"] = hashlib.sha256(
        json.dumps(
            {"collections": qdrant["collections"], "aliases": qdrant["aliases"]},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": 1,
        "profile": "agentium-storage-attestation-v3",
        "captured_at": "2026-07-22T16:00:00Z",
        "qdrant": qdrant,
        "secure_deposit": {
            "files": 42,
            "bytes": 1024,
            "partial_files": 0,
            "manifest_sha256": "b" * 64,
        },
        "object_store": {
            "files": 0,
            "bytes": 0,
            "algorithm": "sha256-merkle-v1",
            "entry_fields": ["path_sha256", "size", "content_sha256"],
            "entries": object_entries,
            "content_manifest_sha256": _canonical_sha256(object_entries),
        },
        "object_store_bindings": {
            name: {
                "backend": "s3",
                "local_path_id_sha256": None,
                "s3_bucket_id_sha256": "c" * 64,
                "s3_endpoint_id_sha256": "d" * 64,
            }
            for name in ("backend", "worker_cpu")
        },
        "minio": {
            "versioning_status": "enabled",
            "versions": 0,
            "latest_versions": 0,
            "delete_markers": 0,
            "bytes": 0,
            "bucket_id_sha256": "e" * 64,
            "algorithm": "s3-version-inventory-sha256-v1",
            "entry_fields": [
                "object_id_sha256",
                "version_id_sha256",
                "size",
                "etag_sha256",
                "last_modified",
                "is_latest",
                "delete_marker",
            ],
            "entries": minio_entries,
            "inventory_sha256": _canonical_sha256(minio_entries),
        },
        "container_mounts": {
            "agentium-pg": [
                {
                    "type": "bind",
                    "source": "/var/lib/agentium/postgres",
                    "destination": "/var/lib/postgresql/data",
                    "rw": True,
                    "name": "",
                }
            ],
            "qdrant": [
                {
                    "type": "bind",
                    "source": "/srv/agentium-data/qdrant",
                    "destination": "/qdrant/storage",
                    "rw": True,
                    "name": "",
                }
            ],
            "agentium-minio": [],
            "agentium-sftp": [],
        },
        "mounts": {
            "data": {
                "source": "/dev/sdb",
                "normalized_source": "/dev/sdb",
                "expected_source": "/dev/sdb",
                "source_matches_expected": True,
                "target": "/srv/agentium-data",
                "fstype": "ext4",
                "device_id": 2,
            },
            "secure_deposit": {
                "source": "/dev/sdc",
                "normalized_source": "/dev/sdc",
                "expected_source": "/dev/sdc",
                "source_matches_expected": True,
                "target": "/home/ubuntu/omnirag/backend/data/secure_deposit",
                "fstype": "ext4",
                "device_id": 3,
            },
        },
    }


def _comparison(*, passed: bool = True) -> dict[str, object]:
    names = [
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
        *[
            f"mounts.{mount}.{field}"
            for mount in ("data", "secure_deposit")
            for field in (
                "source",
                "normalized_source",
                "expected_source",
                "source_matches_expected",
                "target",
                "fstype",
                "device_id",
            )
        ],
    ]
    return {
        "schema_version": 1,
        "profile": "agentium-storage-exact-comparison-v1",
        "result": "passed" if passed else "failed",
        "failed_checks": [] if passed else ["qdrant.collections"],
        "checks": [
            {"name": name, "passed": passed if name == "qdrant.collections" else True}
            for name in names
        ],
    }


def _file_evidence(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _tenant_bundles(deployment_dir: Path) -> dict[str, Path]:
    proofs = deployment_dir / "proofs"
    marker_sha256 = hashlib.sha256(
        f"agentium_safe_chat::{DEPLOYMENT_ID}::{SHA[:12]}".encode()
    ).hexdigest()
    storage_canary = _write(
        deployment_dir / "storage-canary-comparison.json",
        _storage_canary_comparison(),
    )
    andritz_cases = "".join(
        f'<testcase classname="safe" name="{title}"><properties>'
        f'<property name="commit_sha" value="{SHA}" />'
        "</properties></testcase>"
        for title in ANDRITZ_TEST_TITLES
    )
    junit = {
        "andritz": _write(
            proofs / "andritz.xml",
            '<testsuite tests="6" failures="0" errors="0" skipped="0">'
            f"{andritz_cases}</testsuite>",
        ),
        "sentinel": _write(
            proofs / "sentinel.xml",
            _junit(name="Sentinel workspace keeps its immersive Mission Room shell"),
        ),
        "octocity": _write(
            proofs / "octocity.xml",
            _junit(name="Octocity workspace keeps its immersive Mission Room shell"),
        ),
    }
    bindings = _write(
        proofs / "runtime-bindings.json",
        {
            "result": "passed",
            "requested_workspace_slugs": [],
            "missing_workspace_slugs": [],
            "workspace_count": 3,
        },
    )
    spl = _write(
        proofs / "spl-probe.json",
        {
            "kind": "andritz_spl_controlled_probe",
            "outcome": "passed",
            "commit_sha": SHA,
            "deployment_id": DEPLOYMENT_ID,
            "actual_chat_requests": 1,
            "run_id": RUN_ID,
            "input_marker_sha256": marker_sha256,
            "checks": {"exactly_one": {"passed": True}},
        },
    )
    delivery = _write(
        proofs / "controlled-chat-state.json",
        {
            "kind": "controlled_chat_delivery",
            "status": "completed",
            "commit_sha": SHA,
            "deployment_id": DEPLOYMENT_ID,
            "attempt_ceiling": 1,
            "actual_chat_requests": 1,
            "run_id": RUN_ID,
            "input_marker_sha256": marker_sha256,
        },
    )
    ledger = _write(
        proofs / "chat-ledger.json",
        {
            "schema_version": 2,
            "kind": "safe_controlled_chat_ledger",
            "outcome": "passed",
            "commit_sha": SHA,
            "deployment_id": DEPLOYMENT_ID,
            "run_id": RUN_ID,
            "workspace_id": WORKSPACE_ID,
            "system_id": SYSTEM_ID,
            "capability_id": CAPABILITY_ID,
            "knowledge_collection_id": KNOWLEDGE_COLLECTION_ID,
            "input_marker_sha256": marker_sha256,
            "input_query_sha256": "b" * 64,
            "run_trigger_sha256": "c" * 64,
            "system_type_sha256": "1" * 64,
            "flow_variant_sha256": "2" * 64,
            "retrieval_contract_sha256": "3" * 64,
            "knowledge_collection_slug_sha256": "4" * 64,
            "knowledge_collection_chunk_count": 87,
            "run_status_counts": {"completed": 1},
            "invocation_count": 3,
            "invocation_ids": list(INVOCATION_IDS),
            "invocation_status_counts": {"completed": 3},
            "skill_sequence_sha256": "d" * 64,
            "flow_skill_contract_sha256": "a" * 64,
            "read_generation_allowlist_sha256": "b" * 64,
            "unexpected_skill_count": 0,
            "artifact_count": 1,
            "provenance_artifact": {
                "backend": "local",
                "key_sha256": hashlib.sha256(ARTIFACT_KEY.encode()).hexdigest(),
                "content_sha256": ARTIFACT_CONTENT_SHA256,
                "size": ARTIFACT_SIZE,
            },
            "checks": {
                "ledger": {"passed": True},
                **{name: {"passed": True} for name in CHAT_LINEAGE_CHECK_NAMES},
            },
        },
    )
    andritz = _write(
        proofs / "andritz.json",
        {
            "schema_version": 2,
            "kind": "andritz_safe_deployment_bundle",
            "outcome": "passed",
            "commit_sha": SHA,
            "deployment_id": DEPLOYMENT_ID,
            "actual_chat_requests": 1,
            "chat_run_id": RUN_ID,
            "input_marker_sha256": marker_sha256,
            "workspace_id": WORKSPACE_ID,
            "system_id": SYSTEM_ID,
            "capability_id": CAPABILITY_ID,
            "knowledge_collection_id": KNOWLEDGE_COLLECTION_ID,
            "knowledge_collection_chunk_count": 87,
            "system_type_sha256": "1" * 64,
            "flow_variant_sha256": "2" * 64,
            "retrieval_contract_sha256": "3" * 64,
            "knowledge_collection_slug_sha256": "4" * 64,
            "artifact_backend": "local",
            "artifact_key_sha256": hashlib.sha256(ARTIFACT_KEY.encode()).hexdigest(),
            "artifact_content_sha256": ARTIFACT_CONTENT_SHA256,
            "artifact_size": ARTIFACT_SIZE,
            "invocation_count": 3,
            "workspace_test_count": 6,
            "checks": {"composite": {"passed": True}},
            "evidence": {
                "workspace_junit": _file_evidence(junit["andritz"]),
                "spl_probe": _file_evidence(spl),
                "chat_delivery": _file_evidence(delivery),
                "chat_ledger": _file_evidence(ledger),
                "runtime_bindings": _file_evidence(bindings),
                "storage_canary_comparison": _file_evidence(storage_canary),
            },
        },
    )
    bundles = {"andritz": andritz}
    for tenant in ("sentinel", "octocity"):
        bundles[tenant] = _write(
            proofs / f"{tenant}.json",
            {
                "kind": "tenant_safe_deployment_bundle",
                "tenant_key": tenant,
                "outcome": "passed",
                "commit_sha": SHA,
                "workspace_test_count": 1,
                "checks": {"composite": {"passed": True}},
                "evidence": {
                    "workspace_junit": _file_evidence(junit[tenant]),
                    "runtime_bindings": _file_evidence(bindings),
                },
            },
        )
    return bundles


DATABASE_ACCUMULATOR_ALGORITHM = "sha256-domain-sum-mod-2^256-v1"
DATABASE_ACCUMULATOR_DOMAINS = {
    "primary_key": "agentium.postgresql.multiset.primary-key.v1",
    "row_state": "agentium.postgresql.multiset.row-state.v1",
}
DATABASE_ACCUMULATOR_MODULUS = 1 << 256


def _database_multiset(rows: dict[str, str]) -> dict[str, object]:
    sums = {domain: 0 for domain in DATABASE_ACCUMULATOR_DOMAINS}
    for primary_key_sha256, row_sha256 in rows.items():
        for name, row_hash in (
            ("primary_key", None),
            ("row_state", row_sha256),
        ):
            digest = hashlib.sha256()
            digest.update(DATABASE_ACCUMULATOR_DOMAINS[name].encode("ascii"))
            digest.update(b"\x00")
            digest.update(bytes.fromhex(primary_key_sha256))
            if row_hash is not None:
                digest.update(b"\x00")
                digest.update(bytes.fromhex(row_hash))
            sums[name] = (
                sums[name] + int.from_bytes(digest.digest(), "big")
            ) % DATABASE_ACCUMULATOR_MODULUS
    return {
        "algorithm": DATABASE_ACCUMULATOR_ALGORITHM,
        "domains": DATABASE_ACCUMULATOR_DOMAINS,
        "sums": {name: f"{value:064x}" for name, value in sums.items()},
    }


def _database_table(
    rows: dict[str, str],
    *,
    normalization: list[str] | None = None,
    controlled_rows: dict[str, str] | None = None,
    navigation_rows: dict[str, str] | None = None,
) -> dict[str, object]:
    navigation: dict[str, dict[str, str]] = {}
    for primary_key_sha256, workspace_hash in (navigation_rows or {}).items():
        navigation.setdefault(workspace_hash, {})[primary_key_sha256] = rows[primary_key_sha256]
    return {
        "primary_key_columns": ["id"],
        "row_count": len(rows),
        "multiset": _database_multiset(rows),
        "normalization": normalization or [],
        "controlled_rows": dict(sorted((controlled_rows or {}).items())),
        "canonical_navigation_by_workspace": {
            workspace_hash: {
                "row_count": len(group),
                "multiset": _database_multiset(group),
            }
            for workspace_hash, group in sorted(navigation.items())
        },
    }


def _database_inventory(
    tables: dict[str, dict[str, object]],
    *,
    ledger_binding: dict[str, object],
) -> dict[str, object]:
    volatile = {
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
    business = {name: value for name, value in tables.items() if name not in volatile}
    workspace_identities = [
        {
            "slug": slug,
            "workspace_id_sha256": _canonical_sha256([CANARY_WORKSPACES[slug]]),
        }
        for slug in sorted(CANARY_WORKSPACES)
    ]
    payload = {
        "schema_version": 2,
        "kind": "postgresql_row_inventory",
        "profile": "agentium-postgresql-row-inventory-v2",
        "candidate_sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "content_serialized": False,
        "detail_policy": ("controlled-ledger-rows-and-navigation-workspace-aggregates-only"),
        "table_count": len(tables),
        "tables": tables,
        "inventory_sha256": "",
        "business_inventory_sha256": _canonical_sha256(business),
        "workspace_identities": workspace_identities,
        "workspace_identities_sha256": _canonical_sha256(workspace_identities),
        "ledger_binding": ledger_binding,
    }
    payload["inventory_sha256"] = _canonical_sha256(
        {
            "tables": tables,
            "workspace_identities": workspace_identities,
            "ledger_binding": ledger_binding,
        }
    )
    return payload


def _refresh_database_inventory(payload: dict[str, object]) -> None:
    tables = payload["tables"]
    assert isinstance(tables, dict)
    volatile = {
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
    payload["inventory_sha256"] = _canonical_sha256(
        {
            "tables": tables,
            "workspace_identities": payload["workspace_identities"],
            "ledger_binding": payload["ledger_binding"],
        }
    )
    payload["business_inventory_sha256"] = _canonical_sha256(
        {name: table for name, table in tables.items() if name not in volatile}
    )


def _database_absent_binding() -> dict[str, object]:
    return {
        "provided": False,
        "ledger_sha256": None,
        "controlled_run_primary_key_sha256": None,
        "controlled_invocation_count": 0,
        "controlled_invocation_primary_keys_sha256": None,
    }


def _database_controlled_binding(ledger_path: Path) -> dict[str, object]:
    invocation_hashes = sorted(_canonical_sha256([value]) for value in INVOCATION_IDS)
    return {
        "provided": True,
        "ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        "controlled_run_primary_key_sha256": _canonical_sha256([RUN_ID]),
        "controlled_invocation_count": len(INVOCATION_IDS),
        "controlled_invocation_primary_keys_sha256": _canonical_sha256(invocation_hashes),
    }


def _database_payloads(deployment_dir: Path) -> dict[str, object]:
    existing = {
        "users": {_canonical_sha256(["existing-user"]): "1" * 64},
        "runs": {_canonical_sha256(["existing-run"]): "2" * 64},
        "skill_invocations": {_canonical_sha256(["existing-invocation"]): "3" * 64},
        "audit_logs": {_canonical_sha256(["existing-audit"]): "4" * 64},
        "user_session": {_canonical_sha256(["existing-session"]): "5" * 64},
    }
    workspace_hashes = {
        slug: _canonical_sha256([workspace_id]) for slug, workspace_id in CANARY_WORKSPACES.items()
    }
    navigation_rows = {
        _canonical_sha256([f"navigation-{slug}"]): workspace_hash
        for slug, workspace_hash in workspace_hashes.items()
    }
    ledger_path = deployment_dir / "proofs" / "chat-ledger.json"
    controlled_binding = _database_controlled_binding(ledger_path)

    def tables(*, with_canary: bool, volatile_suffix: str) -> dict[str, dict[str, object]]:
        run_rows = dict(existing["runs"])
        invocation_rows = dict(existing["skill_invocations"])
        audit_rows = dict(existing["audit_logs"])
        classified: dict[str, str] = {}
        controlled_runs: dict[str, str] = {}
        controlled_invocations: dict[str, str] = {}
        if with_canary:
            controlled_runs = {_canonical_sha256([RUN_ID]): "6" * 64}
            controlled_invocations = {
                _canonical_sha256([value]): "7" * 64 for value in INVOCATION_IDS
            }
            run_rows.update(controlled_runs)
            invocation_rows.update(controlled_invocations)
            audit_rows.update({primary_key: "8" * 64 for primary_key in navigation_rows})
            classified = navigation_rows
        return {
            "users": _database_table(existing["users"], normalization=["last_login"]),
            "runs": _database_table(
                run_rows,
                controlled_rows=controlled_runs,
            ),
            "skill_invocations": _database_table(
                invocation_rows,
                controlled_rows=controlled_invocations,
            ),
            "audit_logs": _database_table(
                audit_rows,
                navigation_rows=classified,
            ),
            "user_session": _database_table(
                {_canonical_sha256([f"session-{volatile_suffix}"]): "9" * 64}
            ),
        }

    baseline = _database_inventory(
        tables(with_canary=False, volatile_suffix="before"),
        ledger_binding=_database_absent_binding(),
    )
    post_canary = _database_inventory(
        tables(with_canary=True, volatile_suffix="post"),
        ledger_binding=controlled_binding,
    )
    final = _database_inventory(
        tables(with_canary=True, volatile_suffix="final"),
        ledger_binding=controlled_binding,
    )
    additions = {
        "runs": 1,
        "skill_invocations": len(INVOCATION_IDS),
        "audit_logs": len(CANARY_WORKSPACES),
    }
    comparison = {
        "schema_version": 2,
        "kind": "controlled_canary_database_comparison",
        "profile": "agentium-controlled-canary-postgresql-v2",
        "sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "result": "passed",
        "content_serialized": False,
        "checks": {
            name: True
            for name in (
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
            )
        },
        "canary_workspaces": [
            {"slug": slug, "workspace_id_sha256": workspace_hashes[slug]}
            for slug in sorted(workspace_hashes)
        ],
        "canary_workspaces_sha256": _canonical_sha256(
            [
                {"slug": slug, "workspace_id_sha256": workspace_hashes[slug]}
                for slug in sorted(workspace_hashes)
            ]
        ),
        "baseline_business_sha256": baseline["business_inventory_sha256"],
        "post_canary_business_sha256": post_canary["business_inventory_sha256"],
        "final_business_sha256": final["business_inventory_sha256"],
        "controlled_run_primary_key_sha256": _canonical_sha256([RUN_ID]),
        "controlled_invocation_primary_keys_sha256": _canonical_sha256(
            sorted(_canonical_sha256([value]) for value in INVOCATION_IDS)
        ),
        "controlled_invocation_count": len(INVOCATION_IDS),
        "ledger_sha256": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
        "failed_tables": [],
        "stages": {
            stage: {
                "audit_logs": {
                    "result": "passed",
                    "before_count": 1,
                    "after_count": 1 + len(CANARY_WORKSPACES),
                    "observed_delta_count": len(CANARY_WORKSPACES),
                    "expected_delta_count": len(CANARY_WORKSPACES),
                    "canonical_navigation_delta_counts": {
                        workspace_hash: 1 for workspace_hash in sorted(workspace_hashes.values())
                    },
                },
                "runs": {
                    "result": "passed",
                    "before_count": 1,
                    "after_count": 2,
                    "observed_delta_count": 1,
                    "expected_delta_count": 1,
                    "canonical_navigation_delta_counts": {},
                },
                "skill_invocations": {
                    "result": "passed",
                    "before_count": 1,
                    "after_count": 1 + len(INVOCATION_IDS),
                    "observed_delta_count": len(INVOCATION_IDS),
                    "expected_delta_count": len(INVOCATION_IDS),
                    "canonical_navigation_delta_counts": {},
                },
                "user_session": {
                    "result": "allowed_keycloak_session_or_event_volatility",
                    "before_count": 1,
                    "after_count": 1,
                    "observed_delta_count": 0,
                    "expected_delta_count": None,
                    "canonical_navigation_delta_counts": {},
                },
                "users": {
                    "result": "passed",
                    "before_count": 1,
                    "after_count": 1,
                    "observed_delta_count": 0,
                    "expected_delta_count": 0,
                    "canonical_navigation_delta_counts": {},
                },
            }
            for stage in ("post_canary", "final")
        },
        "summary": {
            "table_count": len(baseline["tables"]),
            "preexisting_rows": 4,
            "added_rows": sum(additions.values()),
            "added_rows_by_table": additions,
            "modified_preexisting_rows": 0,
            "deleted_preexisting_rows": 0,
            "normalized_columns": {"users": ["last_login"]},
            "volatile_tables": [
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
            ],
            "accumulator_algorithm": DATABASE_ACCUMULATOR_ALGORITHM,
            "accumulator_domains": DATABASE_ACCUMULATOR_DOMAINS,
        },
    }
    return {
        "baseline": baseline,
        "post_canary": post_canary,
        "final": final,
        "comparison": comparison,
    }


def _runtime_env_fixture(deployment_dir: Path) -> str:
    bundle = deployment_dir / "runtime-env"
    bundle.mkdir(mode=0o700, exist_ok=True)
    bundle.chmod(0o700)
    content = {
        "source-000.env": f"COMPOSE_SECRET={RUNTIME_ENV_SECRET}\n",
        "source-001.env": "OBJECT_STORE_S3_ACCESS_KEY=agentium-app\n",
        "source-002.env": "QDRANT_API_KEY=read-only-key\n",
        "source-003.env": "KEYCLOAK_ADMIN_PASSWORD=keycloak-private\n",
        "source-004.env": "DATABASE_URL=postgresql://private\n",
        "compose.effective.env": (
            f"AGENTIUM_ENV_FILE={bundle / 'source-001.env'}\n"
            f"AGENTIUM_QDRANT_ENV_FILE={bundle / 'source-002.env'}\n"
            f"AGENTIUM_KEYCLOAK_ENV_FILE={bundle / 'source-003.env'}\n"
        ),
    }
    for filename, value in content.items():
        _write(bundle / filename, value)
    role_files = {
        "compose_main": "source-000.env",
        "application": "source-001.env",
        "qdrant": "source-002.env",
        "keycloak": "source-003.env",
        "systemd": "source-004.env",
    }
    manifest = {
        "schema_version": 3,
        "profile": "agentium-runtime-env-bundle-v3",
        "candidate_sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "files": {
            filename: {
                "sha256": hashlib.sha256((bundle / filename).read_bytes()).hexdigest(),
                "size": (bundle / filename).stat().st_size,
            }
            for filename in content
        },
        "roles": {
            role: {
                "file": filename,
                "source_path_sha256": hashlib.sha256(
                    (
                        RUNTIME_ENV_SOURCE_PATH
                        if role == "application"
                        else f"/private/live/{role}.env"
                    ).encode()
                ).hexdigest(),
                "source_device": 2049,
                "source_inode": index + 10,
                "source_mtime_ns": 1_721_667_200_000_000_000 + index,
            }
            for index, (role, filename) in enumerate(role_files.items())
        },
        "effective_compose_file": "compose.effective.env",
        "effective_references": {
            "AGENTIUM_ENV_FILE": "source-001.env",
            "AGENTIUM_QDRANT_ENV_FILE": "source-002.env",
            "AGENTIUM_KEYCLOAK_ENV_FILE": "source-003.env",
        },
        "checks": {
            "object_store_minio_credentials_separated": True,
            "placeholder_secrets_rejected": True,
            "production_credentials_explicit": True,
            "source_files_private": True,
            "storage_paths_explicit": True,
            "systemd_revision_bound": True,
        },
    }
    manifest_path = _write(bundle / "manifest.json", manifest)
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    workspace_target_selectors = {
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
    workspace_ids = sorted(CANARY_WORKSPACES.values())
    workspace_targets = {
        "schema_version": 2,
        "profile": "agentium-workspace-target-gate-v2",
        "candidate_sha": SHA,
        "deployment_id": DEPLOYMENT_ID,
        "selection": "explicit_operator_workspace_ids",
        "operator_workspace_ids": workspace_ids,
        "targets": {
            role: {
                "workspace_id": CANARY_WORKSPACES[slug],
                "workspace_slug": slug,
                "selector": workspace_target_selectors[role],
            }
            for role, slug in WORKSPACE_TARGET_SLUGS.items()
        },
    }
    metadata_artifacts = {
        "workspace_targets_sha256": _write(
            deployment_dir / "workspace-targets.json", workspace_targets
        ),
        "release_a_attestation_sha256": _write(
            deployment_dir / "release-a-attestation.json", {"result": "passed"}
        ),
        "release_a_receipt_sha256": _write(
            deployment_dir / "release-a-verification-receipt.json",
            {"result": "passed"},
        ),
        "release_a_manifest_sha256": _write(
            deployment_dir / "release-a-diff-manifest.json", {"schema_version": 2}
        ),
        "release_a_review_policy_sha256": _write(
            deployment_dir / "release-a-semantic-review.json", {"decision": "approved"}
        ),
        "release_a_manifest_receipt_sha256": _write(
            deployment_dir / "release-a-manifest-verification-receipt.json",
            {"result": "passed"},
        ),
    }
    metadata_digests = {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in metadata_artifacts.items()
    }
    workspace_ids_csv = ",".join(workspace_ids)
    _write(
        deployment_dir / "metadata.tsv",
        (
            "format\t5\n"
            f"deployment_id\t{DEPLOYMENT_ID}\n"
            "branch\tdemo/agentic\n"
            f"candidate_sha\t{SHA}\n"
            f"previous_sha\t{'b' * 40}\n"
            f"sftp_release_sha\t{SFTP_SHA}\n"
            f"sftp_image_id\tsha256:{'e' * 64}\n"
            f"previous_database_revision\t{REVISION}\n"
            f"canary_workspace_ids\t{workspace_ids_csv}\n"
            f"workspace_targets_sha256\t{metadata_digests['workspace_targets_sha256']}\n"
            f"env_manifest_sha256\t{manifest_sha256}\n"
            f"release_a_attestation_sha256\t{metadata_digests['release_a_attestation_sha256']}\n"
            f"release_a_receipt_sha256\t{metadata_digests['release_a_receipt_sha256']}\n"
            f"release_a_manifest_sha256\t{metadata_digests['release_a_manifest_sha256']}\n"
            f"release_a_review_policy_sha256\t{metadata_digests['release_a_review_policy_sha256']}\n"
            f"release_a_manifest_receipt_sha256\t{metadata_digests['release_a_manifest_receipt_sha256']}\n"
            "created_at\t2026-07-22T16:00:00Z\n"
        ),
    )
    return manifest_sha256


def _fixture_inputs(deployment_dir: Path) -> dict[str, Path]:
    deployment_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    deployment_dir.chmod(0o700)
    _runtime_env_fixture(deployment_dir)
    snapshot = _storage_snapshot()
    bundles = _tenant_bundles(deployment_dir)
    database = _database_payloads(deployment_dir)
    baseline_path = _write(
        deployment_dir / "database-pre-canary-row-inventory.json",
        database["baseline"],
    )
    post_canary_path = _write(
        deployment_dir / "database-post-canary-row-inventory.json",
        database["post_canary"],
    )
    final_path = _write(
        deployment_dir / "database-final-open-row-inventory.json",
        database["final"],
    )
    comparison = dict(database["comparison"])
    comparison.update(
        {
            "baseline_sha256": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
            "post_canary_sha256": hashlib.sha256(post_canary_path.read_bytes()).hexdigest(),
            "final_sha256": hashlib.sha256(final_path.read_bytes()).hexdigest(),
        }
    )
    return {
        "provenance": _write(
            deployment_dir / "proofs" / "provenance.json",
            {
                "schema_version": 1,
                "outcome": "passed",
                "commit_sha": SHA,
                "checks": {"sha": {"passed": True}},
            },
        ),
        "showcase": _write(
            deployment_dir / "proofs" / "showcase.json",
            {"result": "passed", "candidate_sha": SHA, "checks": {"canary": True}},
        ),
        **bundles,
        "storage_before": _write(deployment_dir / "storage-before.json", snapshot),
        "storage_after": _write(deployment_dir / "storage-after.json", snapshot),
        "storage_comparison": _write(
            deployment_dir / "storage-comparison.json",
            _comparison(),
        ),
        "sftp_closed_before": _write(
            deployment_dir / "proofs" / "sftp-closed-before.json",
            _sftp_closed_boundary("2026-07-22T16:00:00Z"),
        ),
        "sftp_closed_after": _write(
            deployment_dir / "proofs" / "sftp-closed-after.json",
            _sftp_closed_boundary("2026-07-22T16:05:00Z"),
        ),
        "qdrant_preflight_barrier": _write(
            deployment_dir / "qdrant-preflight-barrier.json",
            _qdrant_host_barrier("admin"),
        ),
        "qdrant_validation_barrier": _write(
            deployment_dir / "qdrant-validation-barrier.json",
            _qdrant_host_barrier("read-only"),
        ),
        "qdrant_backend_probe": _write(
            deployment_dir / "qdrant-backend-probe.json",
            _qdrant_client_probe(BACKEND_CONTAINER_ID),
        ),
        "qdrant_worker_probe": _write(
            deployment_dir / "qdrant-worker-probe.json",
            _qdrant_client_probe(WORKER_CONTAINER_ID),
        ),
        "qdrant_post_canary_barrier": _write(
            deployment_dir / "qdrant-post-canary-barrier.json",
            _qdrant_host_barrier("read-only"),
        ),
        "database_canary_baseline": _write(
            baseline_path,
            database["baseline"],
        ),
        "database_post_canary": _write(
            post_canary_path,
            database["post_canary"],
        ),
        "database_final": _write(
            final_path,
            database["final"],
        ),
        "database_post_canary_comparison": _write(
            deployment_dir / "database-post-canary-comparison.json",
            comparison,
        ),
    }


def _build(module: ModuleType, deployment_dir: Path, entries: dict[str, Path]) -> dict[str, object]:
    return module.build_validation(
        deployment_id=DEPLOYMENT_ID,
        candidate_sha=SHA,
        sftp_sha=SFTP_SHA,
        database_revision=REVISION,
        deployment_dir=deployment_dir,
        entries=entries,
    )


def _verify(
    module: ModuleType, deployment_dir: Path, entries: dict[str, Path]
) -> dict[str, object]:
    return module.verify_validation(
        deployment_id=DEPLOYMENT_ID,
        candidate_sha=SHA,
        sftp_sha=SFTP_SHA,
        database_revision=REVISION,
        deployment_dir=deployment_dir,
        entries=entries,
    )


def test_build_and_verify_bind_mixed_proofs_without_copying_names_or_payloads(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    # A sensitive-looking source name must never be copied into validation.json.
    sensitive = entries["andritz"].with_name("sftp-customer-secret.xml")
    entries["andritz"].replace(sensitive)
    entries["andritz"] = sensitive

    artifact = _build(module, deployment_dir, entries)
    artifact_path = deployment_dir / "validation.json"
    serialized = artifact_path.read_text(encoding="utf-8")

    assert artifact_path.stat().st_mode & 0o777 == 0o600
    assert artifact["result"] == "passed"
    assert artifact["checks"] == {name: True for name in module.REQUIRED_CHECKS}
    assert artifact["runtime_env"] == {
        "profile": "agentium-runtime-env-bundle-v3",
        "schema_version": 3,
        "manifest_sha256": hashlib.sha256(
            (deployment_dir / "runtime-env" / "manifest.json").read_bytes()
        ).hexdigest(),
        "candidate_sha_checked": True,
        "deployment_id_checked": True,
        "metadata_digest_checked": True,
        "private_identity_checked": True,
        "file_count": 6,
        "role_count": 5,
    }
    assert set(artifact["evidence"]) == set(module.ALL_ENTRIES)
    assert (
        artifact["evidence"]["andritz"]["sha256"]
        == hashlib.sha256(sensitive.read_bytes()).hexdigest()
    )
    assert artifact["evidence"]["andritz"]["test_count"] == 6
    assert artifact["evidence"]["andritz"]["commit_sha_checked"] is True
    assert artifact["digests"]["qdrant_before"] == artifact["digests"]["qdrant_after"]
    assert artifact["digests"]["secure_deposit_before"] == "b" * 64
    snapshot = _storage_snapshot()
    assert (
        artifact["digests"]["object_store_before"]
        == snapshot["object_store"]["content_manifest_sha256"]
    )
    assert artifact["digests"]["minio_before"] == snapshot["minio"]["inventory_sha256"]
    assert (
        artifact["digests"]["object_store_bindings_before"]
        == artifact["digests"]["object_store_bindings_after"]
    )
    assert (
        artifact["digests"]["container_mounts_before"]
        == artifact["digests"]["container_mounts_after"]
    )
    assert artifact["digests"]["stable_mounts_before"] == artifact["digests"]["stable_mounts_after"]
    assert "sftp-customer-secret" not in serialized.lower()
    assert SFTP_HOST_KEY_FINGERPRINT not in serialized
    assert artifact["checks"]["sftp_closed_boundary"] is True
    assert artifact["evidence"]["sftp_closed_before"]["container_id"] == SFTP_CONTAINER_ID
    assert (
        artifact["evidence"]["sftp_closed_before"]["host_key_fingerprint_sha256"]
        == hashlib.sha256(SFTP_HOST_KEY_FINGERPRINT.encode()).hexdigest()
    )
    assert "opaque" not in serialized
    assert RUNTIME_ENV_SECRET not in serialized
    assert RUNTIME_ENV_SOURCE_PATH not in serialized
    assert _verify(module, deployment_dir, entries) == artifact


def test_runtime_env_attestation_rejects_manifest_and_metadata_identity_mismatch(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    metadata_path = deployment_dir / "metadata.tsv"
    metadata = metadata_path.read_text(encoding="utf-8")
    _write(
        metadata_path,
        re.sub(
            r"(?m)^env_manifest_sha256\t[0-9a-f]{64}$",
            f"env_manifest_sha256\t{'0' * 64}",
            metadata,
        ),
    )
    with pytest.raises(module.SafeValidationError, match="manifest digest differs"):
        _build(module, deployment_dir, entries)

    entries = _fixture_inputs(deployment_dir)
    manifest_path = deployment_dir / "runtime-env" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["candidate_sha"] = "b" * 40
    _write(manifest_path, manifest)
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    _write(
        metadata_path,
        metadata_path.read_text(encoding="utf-8").replace(
            next(
                line
                for line in metadata_path.read_text(encoding="utf-8").splitlines()
                if line.startswith("env_manifest_sha256\t")
            ),
            f"env_manifest_sha256\t{digest}",
        ),
    )
    with pytest.raises(module.SafeValidationError, match="manifest identity differs"):
        _build(module, deployment_dir, entries)


def test_runtime_env_attestation_rejects_file_tamper_and_non_private_manifest(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    artifact = _build(module, deployment_dir, entries)
    assert artifact["runtime_env"]["private_identity_checked"] is True

    _write(
        deployment_dir / "runtime-env" / "source-001.env",
        "OBJECT_STORE_S3_ACCESS_KEY=tampered\n",
    )
    with pytest.raises(module.SafeValidationError, match="differs from its manifest"):
        _verify(module, deployment_dir, entries)

    entries = _fixture_inputs(deployment_dir)
    _build(module, deployment_dir, entries)
    manifest_path = deployment_dir / "runtime-env" / "manifest.json"
    manifest_path.chmod(0o640)
    with pytest.raises(module.SafeValidationError, match="private deployment file"):
        _verify(module, deployment_dir, entries)


def test_runtime_env_attestation_rejects_metadata_schema_drift(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    metadata_path = deployment_dir / "metadata.tsv"
    _write(
        metadata_path,
        metadata_path.read_text(encoding="utf-8") + "unexpected\tvalue\n",
    )

    with pytest.raises(module.SafeValidationError, match="metadata schema differs"):
        _build(module, deployment_dir, entries)


def test_runtime_env_attestation_rejects_frozen_release_a_artifact_tamper(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    _write(
        deployment_dir / "release-a-semantic-review.json",
        {"decision": "tampered"},
    )

    with pytest.raises(module.SafeValidationError, match="artifact .* digest differs"):
        _build(module, deployment_dir, entries)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("selector", "target sentinel identity differs"),
        ("duplicate_slug", "target identities are ambiguous"),
        ("resolved_slug_drift", "omits or changes a resolved canary workspace"),
    ],
)
def test_validation_workspace_targets_fail_closed_after_digest_rebinding(
    module: ModuleType,
    tmp_path: Path,
    mutation: str,
    match: str,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    target_path = deployment_dir / "workspace-targets.json"
    targets = json.loads(target_path.read_text(encoding="utf-8"))
    if mutation == "selector":
        targets["targets"]["sentinel"]["selector"]["family"] = "generic"
    elif mutation == "duplicate_slug":
        targets["targets"]["octocity"]["workspace_slug"] = targets["targets"][
            "showcase"
        ]["workspace_slug"]
    else:
        targets["targets"]["octocity"]["workspace_slug"] = "echo"
    _write(target_path, targets)
    digest = hashlib.sha256(target_path.read_bytes()).hexdigest()
    metadata_path = deployment_dir / "metadata.tsv"
    metadata = re.sub(
        r"(?m)^workspace_targets_sha256\t[0-9a-f]{64}$",
        f"workspace_targets_sha256\t{digest}",
        metadata_path.read_text(encoding="utf-8"),
    )
    _write(metadata_path, metadata)

    with pytest.raises(module.SafeValidationError, match=match):
        _build(module, deployment_dir, entries)


def test_runtime_env_manifest_cannot_serialize_a_raw_source_path(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    manifest_path = deployment_dir / "runtime-env" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["roles"]["application"]["source_path"] = RUNTIME_ENV_SOURCE_PATH
    _write(manifest_path, manifest)
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    metadata_path = deployment_dir / "metadata.tsv"
    metadata = metadata_path.read_text(encoding="utf-8")
    metadata = re.sub(
        r"(?m)^env_manifest_sha256\t[0-9a-f]{64}$",
        f"env_manifest_sha256\t{digest}",
        metadata,
    )
    _write(metadata_path, metadata)

    with pytest.raises(module.SafeValidationError, match="role contract is invalid"):
        _build(module, deployment_dir, entries)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({"result": "failed", "checks": {"canary": False}}, "did not pass"),
        (_junit(failure=True), "not fully green"),
        (_junit(skipped=True), "not fully green"),
    ],
)
def test_build_rejects_failed_json_and_non_green_junit(
    module: ModuleType,
    tmp_path: Path,
    payload: object,
    match: str,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    entries["showcase"] = _write(deployment_dir / "proofs" / "showcase-proof", payload)

    with pytest.raises(module.SafeValidationError, match=match):
        _build(module, deployment_dir, entries)


def test_build_checks_any_declared_commit_sha(module: ModuleType, tmp_path: Path) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    sentinel = json.loads(entries["sentinel"].read_text(encoding="utf-8"))
    sentinel["commit_sha"] = "c" * 40
    _write(entries["sentinel"], sentinel)

    with pytest.raises(module.SafeValidationError, match="commit SHA"):
        _build(module, deployment_dir, entries)


def test_validator_rejects_an_unrelated_green_tenant_junit(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    junit_path = deployment_dir / "proofs" / "sentinel.xml"
    _write(junit_path, _junit(name="unrelated green test"))
    bundle = json.loads(entries["sentinel"].read_text(encoding="utf-8"))
    bundle["evidence"]["workspace_junit"] = _file_evidence(junit_path)
    _write(entries["sentinel"], bundle)

    with pytest.raises(module.SafeValidationError, match="expected tenant canary"):
        _build(module, deployment_dir, entries)


@pytest.mark.parametrize("tenant_key", ["andritz", "sentinel"])
@pytest.mark.parametrize("mutation", ["missing", "wrong", "suite_only", "duplicate"])
def test_validator_requires_testcase_local_candidate_sha(
    module: ModuleType,
    tmp_path: Path,
    tenant_key: str,
    mutation: str,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    junit_path = deployment_dir / "proofs" / f"{tenant_key}.xml"
    root = ElementTree.fromstring(junit_path.read_bytes())
    testcases = root.findall("testcase")
    assert testcases
    first_properties = testcases[0].find("properties")
    assert first_properties is not None
    first_binding = first_properties.find("property")
    assert first_binding is not None
    if mutation == "missing":
        first_properties.remove(first_binding)
    elif mutation == "wrong":
        first_binding.set("value", "c" * 40)
    elif mutation == "suite_only":
        for testcase in testcases:
            properties = testcase.find("properties")
            assert properties is not None
            for binding in list(properties):
                properties.remove(binding)
        suite_properties = ElementTree.Element("properties")
        ElementTree.SubElement(
            suite_properties,
            "property",
            {"name": "commit_sha", "value": SHA},
        )
        root.insert(0, suite_properties)
    else:
        ElementTree.SubElement(
            first_properties,
            "property",
            {"name": "commit_sha", "value": SHA},
        )
    _write(junit_path, ElementTree.tostring(root, encoding="unicode"))
    bundle = json.loads(entries[tenant_key].read_text(encoding="utf-8"))
    bundle["evidence"]["workspace_junit"] = _file_evidence(junit_path)
    _write(entries[tenant_key], bundle)

    with pytest.raises(module.SafeValidationError, match="commit_sha|commit SHA"):
        _build(module, deployment_dir, entries)


@pytest.mark.parametrize("tenant_key", ["andritz", "sentinel"])
def test_validator_rejects_retained_workspace_console_output(
    module: ModuleType,
    tmp_path: Path,
    tenant_key: str,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    junit_path = deployment_dir / "proofs" / f"{tenant_key}.xml"
    root = ElementTree.fromstring(junit_path.read_bytes())
    system_out = ElementTree.SubElement(root, "system-out")
    system_out.text = "rendered business content must not persist"
    _write(junit_path, ElementTree.tostring(root, encoding="unicode"))
    bundle = json.loads(entries[tenant_key].read_text(encoding="utf-8"))
    bundle["evidence"]["workspace_junit"] = _file_evidence(junit_path)
    _write(entries[tenant_key], bundle)

    with pytest.raises(module.SafeValidationError, match="console output"):
        _build(module, deployment_dir, entries)


def test_empty_nested_commit_is_ignored_when_root_commit_matches(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    entries["showcase"] = _write(
        deployment_dir / "proofs" / "showcase.json",
        {
            "outcome": "passed",
            "commit_sha": SHA,
            "ci": {"commit_sha": ""},
            "checks": {"canary": True},
        },
    )

    artifact = _build(module, deployment_dir, entries)
    assert artifact["evidence"]["showcase"]["commit_sha_checked"] is True


def test_validation_rejects_duplicate_proof_realpaths_and_digests(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    duplicate_path = {**entries, "sentinel": entries["andritz"]}
    with pytest.raises(module.SafeValidationError, match="same realpath"):
        _build(module, deployment_dir, duplicate_path)

    entries = _fixture_inputs(deployment_dir)
    entries["showcase"].write_bytes(entries["provenance"].read_bytes())
    entries["showcase"].chmod(0o600)
    with pytest.raises(module.SafeValidationError, match="same digest"):
        _build(module, deployment_dir, entries)

    entries = _fixture_inputs(deployment_dir)
    duplicate_database_capture = {
        **entries,
        "database_final": entries["database_post_canary"],
    }
    with pytest.raises(module.SafeValidationError, match="same realpath"):
        _build(module, deployment_dir, duplicate_database_capture)


def test_andritz_bundle_cannot_omit_or_tamper_with_controlled_chat_ledger(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    bundle = json.loads(entries["andritz"].read_text(encoding="utf-8"))
    del bundle["evidence"]["chat_ledger"]
    _write(entries["andritz"], bundle)
    with pytest.raises(module.SafeValidationError, match="inventory is incomplete"):
        _build(module, deployment_dir, entries)

    entries = _fixture_inputs(deployment_dir)
    ledger = deployment_dir / "proofs" / "chat-ledger.json"
    ledger.write_text(ledger.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(module.SafeValidationError, match="digest does not match"):
        _build(module, deployment_dir, entries)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("legacy_schema", "contract is invalid"),
        ("missing_check", "lineage is incomplete"),
        ("missing_system", "System id"),
        ("bundle_mismatch", "lineage is inconsistent"),
        ("empty_collection", "lineage is inconsistent"),
    ],
)
def test_validator_rechecks_strict_postgresql_chat_lineage(
    module: ModuleType,
    tmp_path: Path,
    mutation: str,
    match: str,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    ledger_path = deployment_dir / "proofs" / "chat-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    bundle = json.loads(entries["andritz"].read_text(encoding="utf-8"))
    if mutation == "legacy_schema":
        ledger["schema_version"] = 1
    elif mutation == "missing_check":
        del ledger["checks"]["chat_execution_targets_system"]
    elif mutation == "missing_system":
        ledger["system_id"] = None
    elif mutation == "bundle_mismatch":
        bundle["system_id"] = "88888888-8888-4888-8888-888888888888"
    else:
        ledger["knowledge_collection_chunk_count"] = 0
    _write(ledger_path, ledger)
    bundle["evidence"]["chat_ledger"] = _file_evidence(ledger_path)
    _write(entries["andritz"], bundle)

    with pytest.raises(module.SafeValidationError, match=match):
        _build(module, deployment_dir, entries)


def test_validator_rechecks_that_underlying_chat_evidence_is_content_free(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    spl_path = deployment_dir / "proofs" / "spl-probe.json"
    spl = json.loads(spl_path.read_text(encoding="utf-8"))
    spl["citation"] = "must never be persisted"
    _write(spl_path, spl)
    bundle = json.loads(entries["andritz"].read_text(encoding="utf-8"))
    bundle["evidence"]["spl_probe"] = _file_evidence(spl_path)
    _write(entries["andritz"], bundle)

    with pytest.raises(module.SafeValidationError, match="persisted content"):
        _build(module, deployment_dir, entries)


def test_validator_rechecks_provenance_against_the_only_storage_addition(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    comparison_path = deployment_dir / "storage-canary-comparison.json"
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    comparison["additions"]["object_store"]["entries"][0]["content_sha256"] = "0" * 64
    comparison["additions"]["object_store"]["digest"] = _canonical_sha256(
        comparison["additions"]["object_store"]["entries"]
    )
    _write(comparison_path, comparison)
    bundle = json.loads(entries["andritz"].read_text(encoding="utf-8"))
    bundle["evidence"]["storage_canary_comparison"] = _file_evidence(comparison_path)
    _write(entries["andritz"], bundle)

    with pytest.raises(module.SafeValidationError, match="sole storage addition"):
        _build(module, deployment_dir, entries)


@pytest.mark.parametrize("check", ["provenance", "showcase"])
def test_provenance_and_showcase_require_an_explicit_candidate_commit(
    module: ModuleType,
    tmp_path: Path,
    check: str,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    entries[check] = _write(
        deployment_dir / "proofs" / f"{check}.json",
        {"outcome": "passed", "checks": {"gate": True}},
    )

    with pytest.raises(module.SafeValidationError, match="must declare the candidate commit SHA"):
        _build(module, deployment_dir, entries)


@pytest.mark.parametrize(
    "mutation",
    [
        "qdrant",
        "secure_deposit",
        "object_store",
        "minio",
        "object_store_bindings",
        "container_mounts",
        "mount_identity",
        "comparison",
    ],
)
def test_build_recomputes_and_enforces_storage_equality(
    module: ModuleType,
    tmp_path: Path,
    mutation: str,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    if mutation == "comparison":
        _write(entries["storage_comparison"], _comparison(passed=False))
    else:
        after = _storage_snapshot()
        if mutation == "qdrant":
            after["qdrant"]["collections"][0]["points_count"] = 13  # type: ignore[index]
        elif mutation == "secure_deposit":
            after["secure_deposit"]["manifest_sha256"] = "c" * 64  # type: ignore[index]
        elif mutation == "object_store":
            after["object_store"]["files"] = 4  # type: ignore[index]
        elif mutation == "minio":
            after["minio"]["versions"] = 5  # type: ignore[index]
        elif mutation == "object_store_bindings":
            after["object_store_bindings"]["worker_cpu"]["s3_bucket_id_sha256"] = (  # type: ignore[index]
                "f" * 64
            )
        elif mutation == "container_mounts":
            after["container_mounts"]["qdrant"][0]["rw"] = False  # type: ignore[index]
        else:
            after["mounts"]["secure_deposit"]["device_id"] = 4  # type: ignore[index]
        _write(entries["storage_after"], after)

    with pytest.raises(module.SafeValidationError):
        _build(module, deployment_dir, entries)


def test_build_rejects_legacy_storage_profile_even_when_comparison_passes(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    before = _storage_snapshot()
    before.pop("profile")
    _write(entries["storage_before"], before)

    with pytest.raises(module.SafeValidationError, match="storage profile is unsupported"):
        _build(module, deployment_dir, entries)


def test_large_storage_limit_does_not_widen_general_proof_limit(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    deployment_dir.mkdir(mode=0o700)
    oversized = deployment_dir / "oversized.bin"
    oversized.write_bytes(b"x")
    with oversized.open("r+b") as handle:
        handle.truncate(module.MAX_PROOF_BYTES + 1)
    oversized.chmod(0o600)
    root = module._deployment_root(deployment_dir)

    with pytest.raises(module.SafeValidationError, match="size is invalid"):
        module._entry_path(oversized, root, label="proof")
    resolved, _ = module._entry_path(
        oversized,
        root,
        label="storage",
        max_bytes=module.MAX_STORAGE_BYTES,
    )
    assert resolved == oversized


def test_verify_rejects_changed_hash_permissions_path_and_identity(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    _build(module, deployment_dir, entries)

    octocity = json.loads(entries["octocity"].read_text(encoding="utf-8"))
    octocity["tampered"] = True
    _write(entries["octocity"], octocity)
    with pytest.raises(module.SafeValidationError, match="hashes changed"):
        _verify(module, deployment_dir, entries)

    entries = _fixture_inputs(deployment_dir)
    _build(module, deployment_dir, entries)
    entries["andritz"].chmod(0o620)
    with pytest.raises(module.SafeValidationError, match="group/world writable"):
        _verify(module, deployment_dir, entries)
    entries["andritz"].chmod(0o600)

    outside = _write(tmp_path / "outside.json", {"result": "passed"})
    outside_entries = {**entries, "showcase": outside}
    with pytest.raises(module.SafeValidationError, match="under deployment-dir"):
        _verify(module, deployment_dir, outside_entries)

    with pytest.raises(module.SafeValidationError, match="deployment_id"):
        module.verify_validation(
            deployment_id="another-deployment",
            candidate_sha=SHA,
            sftp_sha=SFTP_SHA,
            database_revision=REVISION,
            deployment_dir=deployment_dir,
            entries=entries,
        )


def test_verify_rejects_stale_artifact_and_stale_entry(module: ModuleType, tmp_path: Path) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    artifact = _build(module, deployment_dir, entries)
    artifact_path = deployment_dir / "validation.json"

    artifact["generated_at"] = (
        (datetime.now(UTC) - timedelta(seconds=module.MAX_AGE_SECONDS + 1))
        .isoformat()
        .replace("+00:00", "Z")
    )
    _write(artifact_path, artifact)
    with pytest.raises(module.SafeValidationError, match="stale"):
        _verify(module, deployment_dir, entries)

    _build(module, deployment_dir, entries)
    stale_epoch = (datetime.now(UTC) - timedelta(seconds=module.MAX_AGE_SECONDS + 1)).timestamp()
    os.utime(entries["provenance"], (stale_epoch, stale_epoch))
    with pytest.raises(module.SafeValidationError, match="provenance evidence is stale"):
        _verify(module, deployment_dir, entries)


def test_verify_rejects_writable_or_tampered_validation_artifact(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    artifact = _build(module, deployment_dir, entries)
    artifact_path = deployment_dir / "validation.json"

    artifact_path.chmod(0o620)
    with pytest.raises(module.SafeValidationError, match="group/world writable"):
        _verify(module, deployment_dir, entries)

    artifact_path.chmod(0o600)
    artifact["checks"]["sentinel"] = False
    _write(artifact_path, artifact)
    with pytest.raises(module.SafeValidationError, match="required passing check"):
        _verify(module, deployment_dir, entries)


def test_validator_rejects_qdrant_identity_change_and_forged_read_only_probe(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    post_barrier = json.loads(entries["qdrant_post_canary_barrier"].read_text())
    post_barrier["qdrant"]["container_id"] = "3" * 64
    _write(entries["qdrant_post_canary_barrier"], post_barrier)
    with pytest.raises(module.SafeValidationError, match="changed during canaries"):
        _build(module, deployment_dir, entries)

    entries = _fixture_inputs(deployment_dir)
    backend_probe = json.loads(entries["qdrant_backend_probe"].read_text())
    backend_probe["probe"].update(
        {
            "delete_status": 404,
            "write_rejected": False,
            "write_route_authorized": True,
        }
    )
    _write(entries["qdrant_backend_probe"], backend_probe)
    with pytest.raises(module.SafeValidationError, match="read-only Qdrant key"):
        _build(module, deployment_dir, entries)


@pytest.mark.parametrize(
    "mutation",
    (
        "wrong_sha",
        "missing_ipv6_gate",
        "storage_rw",
        "restart_enabled",
        "listener_present",
        "host_key_changed",
        "container_identity_drift",
    ),
)
def test_validator_rejects_incomplete_or_drifting_sftp_closed_boundaries(
    module: ModuleType,
    tmp_path: Path,
    mutation: str,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    target = (
        entries["sftp_closed_after"]
        if mutation in {"host_key_changed", "container_identity_drift"}
        else entries["sftp_closed_before"]
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    if mutation == "wrong_sha":
        payload["sha"] = "f" * 40
    elif mutation == "missing_ipv6_gate":
        del payload["ingress_gate"]["ipv6_input"]
    elif mutation == "storage_rw":
        payload["secure_deposit"]["read_only"] = False
    elif mutation == "restart_enabled":
        payload["container"]["restart_policy_disabled"] = False
    elif mutation == "listener_present":
        payload["network"]["listener_count"] = 1
    elif mutation == "host_key_changed":
        payload["host_key"]["fingerprint"] = "SHA256:" + "B" * 43
    else:
        payload["container"]["container_id"] = "f" * 64
    _write(target, payload)

    with pytest.raises(module.SafeValidationError, match="SFTP|Secure Deposit"):
        _build(module, deployment_dir, entries)


def test_validator_independently_rejects_postgresql_preexisting_row_change(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    post = json.loads(entries["database_post_canary"].read_text())
    runs = post["tables"]["runs"]
    runs["multiset"]["sums"]["row_state"] = "e" * 64
    _refresh_database_inventory(post)
    _write(entries["database_post_canary"], post)
    comparison = json.loads(entries["database_post_canary_comparison"].read_text())
    comparison["post_canary_sha256"] = hashlib.sha256(
        entries["database_post_canary"].read_bytes()
    ).hexdigest()
    comparison["post_canary_business_sha256"] = post["business_inventory_sha256"]
    _write(entries["database_post_canary_comparison"], comparison)

    with pytest.raises(module.SafeValidationError, match="pre-existing business row"):
        _build(module, deployment_dir, entries)


def test_validator_rejects_legacy_unbounded_postgresql_inventory_v1(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    baseline = json.loads(entries["database_canary_baseline"].read_text())
    baseline["schema_version"] = 1
    baseline["profile"] = "agentium-postgresql-row-inventory-v1"
    _write(entries["database_canary_baseline"], baseline)

    with pytest.raises(module.SafeValidationError, match="PostgreSQL v2 identity"):
        _build(module, deployment_dir, entries)


def test_validator_requires_post_canary_inventory_ledger_binding(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    post = json.loads(entries["database_post_canary"].read_text())
    post["ledger_binding"] = _database_absent_binding()
    _refresh_database_inventory(post)
    _write(entries["database_post_canary"], post)

    with pytest.raises(module.SafeValidationError, match="Chat ledger"):
        _build(module, deployment_dir, entries)


def test_validator_requires_navigation_aggregate_for_each_protected_workspace(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    post = json.loads(entries["database_post_canary"].read_text())
    navigation = post["tables"]["audit_logs"]["canonical_navigation_by_workspace"]
    navigation.pop(next(iter(navigation)))
    _refresh_database_inventory(post)
    _write(entries["database_post_canary"], post)

    with pytest.raises(module.SafeValidationError, match="canonical navigation"):
        _build(module, deployment_dir, entries)


def test_validator_does_not_treat_unknown_session_table_as_keycloak_volatile(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    for label, suffix in (
        ("database_canary_baseline", "before"),
        ("database_post_canary", "after"),
        ("database_final", "after"),
    ):
        payload = json.loads(entries[label].read_text())
        payload["tables"]["custom_session"] = _database_table(
            {_canonical_sha256([f"custom-{suffix}"]): "a" * 64}
        )
        payload["table_count"] += 1
        _refresh_database_inventory(payload)
        _write(entries[label], payload)

    with pytest.raises(module.SafeValidationError, match="pre-existing business row"):
        _build(module, deployment_dir, entries)


def test_validator_requires_navigation_proof_for_each_protected_workspace(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    comparison = json.loads(entries["database_post_canary_comparison"].read_text())
    comparison["canary_workspaces"] = comparison["canary_workspaces"][:-1]
    comparison["canary_workspaces_sha256"] = _canonical_sha256(comparison["canary_workspaces"])
    _write(entries["database_post_canary_comparison"], comparison)

    with pytest.raises(module.SafeValidationError, match="four canary workspaces"):
        _build(module, deployment_dir, entries)


def test_cli_build_and_verify_require_every_bound_input(
    module: ModuleType,
    tmp_path: Path,
) -> None:
    deployment_dir = tmp_path / DEPLOYMENT_ID
    entries = _fixture_inputs(deployment_dir)
    common = [
        "--deployment-id",
        DEPLOYMENT_ID,
        "--sha",
        SHA,
        "--sftp-sha",
        SFTP_SHA,
        "--alembic-revision",
        REVISION,
        "--deployment-dir",
        str(deployment_dir),
        "--storage-before",
        str(entries["storage_before"]),
        "--storage-after",
        str(entries["storage_after"]),
        "--storage-comparison",
        str(entries["storage_comparison"]),
    ]
    for check in module.PROOF_CHECKS:
        common.extend([f"--{check}", str(entries[check])])
    for entry in (*module.QDRANT_ENTRIES, *module.DATABASE_ENTRIES):
        common.extend([f"--{entry.replace('_', '-')}", str(entries[entry])])
    for entry in module.SFTP_ENTRIES:
        common.extend([f"--{entry.replace('_', '-')}", str(entries[entry])])

    assert module.main(["build", *common]) == 0
    assert module.main(["verify", *common]) == 0
