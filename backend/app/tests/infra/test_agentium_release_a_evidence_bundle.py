"""Adversarial tests for byte-bound Release A evidence receipts."""

from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "scripts" / "agentium_release_a_evidence_bundle.py"
LIVE_SHA = "a" * 40
RELEASE_A_SHA = "b" * 40
SFTP_SHA = "c" * 40
HOSTNAME = "agentium.papai.ai"
DEPLOYMENT_ID = "release-a-20260722"
NOW = datetime(2026, 7, 22, 18, 0, tzinfo=UTC)
SFTP_IMAGE_ID = "sha256:" + "d" * 64
SFTP_CONTAINER_ID = "e" * 64
SFTP_PORT = 2223
SFTP_HOST_KEY_FINGERPRINT = "SHA256:" + base64.b64encode(b"k" * 32).decode("ascii").rstrip("=")
CANARIES = ("showcase", "andritz", "sentinel", "octocity", "livekit")
DATA_STORES = (
    "postgresql",
    "qdrant",
    "minio_object_store",
    "faiss",
    "secure_deposit",
    "rabbitmq",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agentium_release_a_evidence_bundle_test", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module() -> ModuleType:
    return _load()


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _stamp(now: datetime, minutes: int) -> str:
    return (now - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _preconditions(now: datetime = NOW) -> dict[str, object]:
    mounts = (
        ("/", "/dev/sda1", 400 * 1024**3),
        ("/srv/agentium-data", "/dev/sdb", 500 * 1024**3),
        (
            "/home/ubuntu/omnirag/backend/data/secure_deposit",
            "/dev/sdc",
            1200 * 1024**3,
        ),
    )
    return {
        "profile": "agentium-release-a-preconditions-v1",
        "result": "passed",
        "environment": "production",
        "live_sha": LIVE_SHA,
        "release_a_sha": RELEASE_A_SHA,
        "hostname": HOSTNAME,
        "attested_at": _stamp(now, 0),
        "off_vm_backups": [
            {
                "source_device": device,
                "provider": f"provider-{index}",
                "backup_id_sha256": _digest(f"backup-id-{index}"),
                "completed_at": _stamp(now, 20 - index),
                "restore_check": {
                    "result": "passed",
                    "proof_sha256": _digest(f"restore-{index}"),
                    "completed_at": _stamp(now, 10 - index),
                },
            }
            for index, device in enumerate(("/dev/sda1", "/dev/sdb", "/dev/sdc"))
        ],
        "capacity": [
            {
                "mountpoint": mountpoint,
                "source_device": device,
                "total_bytes": total,
                "available_bytes": max(64 * 1024**3, total // 10) + 1024**3,
                "total_inodes": 1_000_000,
                "available_inodes": 200_000,
                "proof_sha256": _digest(f"capacity-{index}"),
                "measured_at": _stamp(now, 5),
            }
            for index, (mountpoint, device, total) in enumerate(mounts)
        ],
    }


def _attestation(now: datetime = NOW) -> dict[str, object]:
    return {
        "schema_version": 4,
        "kind": "agentium-release-a-attestation",
        "result": "passed",
        "environment": "production",
        "release_a_sha": RELEASE_A_SHA,
        "sftp_release_sha": SFTP_SHA,
        "hostname": HOSTNAME,
        "attested_at": _stamp(now, 0),
        "evidence": {
            "off_vm_backups": [
                {
                    "source_device": device,
                    "provider": f"provider-{index}",
                    "backup_id_sha256": _digest(f"backup-id-{index}"),
                    "completed_at": _stamp(now, 20 - index),
                    "restore_check": {
                        "result": "passed",
                        "proof_sha256": _digest(f"restore-{index}"),
                        "completed_at": _stamp(now, 10 - index),
                    },
                }
                for index, device in enumerate(("/dev/sda1", "/dev/sdb", "/dev/sdc"))
            ],
            "canaries": {
                name: {
                    "result": "passed",
                    "proof_sha256": _digest(f"canary-{name}"),
                    "completed_at": _stamp(now, 4),
                }
                for name in CANARIES
            },
            "data_integrity": {
                name: {
                    "result": "passed",
                    "before_sha256": _digest(f"{name}-before"),
                    "before_at": _stamp(now, 13),
                    "after_sha256": _digest(f"{name}-after"),
                    "after_at": _stamp(now, 12),
                    "comparison_sha256": _digest(f"{name}-comparison"),
                    "completed_at": _stamp(now, 11),
                }
                for name in DATA_STORES
            },
            "minio": {
                "versioning": "Enabled",
                "application_credential_fingerprint_sha256": _digest(
                    "minio-application-credential"
                ),
                "root_credential_fingerprint_sha256": _digest("minio-root-credential"),
                "canary": {"delete_denied": True, "config_denied": True},
                "proof_sha256": _digest("minio-proof"),
                "completed_at": _stamp(now, 10),
            },
            "qdrant": {
                "admin_key_fingerprint_sha256": _digest("qdrant-admin-key"),
                "read_only_key_fingerprint_sha256": _digest("qdrant-read-only-key"),
                "read_only_write_denied": True,
                "inventory_sha256": _digest("qdrant-inventory"),
                "proof_sha256": _digest("qdrant-proof"),
                "completed_at": _stamp(now, 9),
            },
            "runtime": {
                "maintenance_gate": {
                    "survived_reboot": True,
                    "proof_sha256": _digest("maintenance-reboot-proof"),
                    "completed_at": _stamp(now, 8),
                },
                "backend": {
                    "listener": "127.0.0.1:8000",
                    "public_listener_count": 0,
                    "proof_sha256": _digest("backend-listener-proof"),
                    "completed_at": _stamp(now, 7),
                },
                "restart_contract": {
                    "result": "passed",
                    "proof_sha256": _digest("restart-contract-proof"),
                    "completed_at": _stamp(now, 6),
                },
            },
            "tenant_audit": {
                "cross_workspace_binding_count": 0,
                "report_sha256": _digest("tenant-audit-report"),
                "completed_at": _stamp(now, 5),
            },
            "sftp": {
                "image_revision": SFTP_SHA,
                "runtime_ready_receipt_sha256": _digest("sftp-runtime-ready"),
                "runtime_ready_at": _stamp(now, 6),
                "authentication_result": "passed",
                "subsystem_result": "passed",
                "revocation_result": "passed",
                "post_revocation_authentication_result": "denied",
                "ledger_result": "passed",
                "postgres_ledger_receipt_sha256": _digest("sftp-postgres-ledger"),
                "postgres_ledger_completed_at": _stamp(now, 4),
                "credential_fingerprint_sha256": _digest("sftp-credential"),
                "proof_sha256": _digest("sftp-proof"),
                "completed_at": _stamp(now, 3),
            },
            "principals": {
                "browser_canary": {
                    "principal_kind": "service_account",
                    "non_personal": True,
                    "least_privilege": True,
                    "credential_fingerprint_sha256": _digest("browser-credential"),
                    "permission_probe_sha256": _digest("browser-permission-proof"),
                    "permission_probe_result": "passed",
                    "completed_at": _stamp(now, 3),
                },
                "sftp_canary": {
                    "principal_kind": "disposable_sftp",
                    "disposable": True,
                    "credential_fingerprint_sha256": _digest("sftp-credential"),
                    "completed_at": _stamp(now, 3),
                },
            },
        },
    }


def _precondition_labels() -> list[str]:
    return [
        *(f"restore-{index}" for index in range(3)),
        *(f"capacity-{index}" for index in range(3)),
    ]


def _final_labels() -> list[str]:
    labels = [*(f"restore-{index}" for index in range(3))]
    labels.extend(f"canary-{name}" for name in CANARIES)
    for name in DATA_STORES:
        labels.extend((f"{name}-before", f"{name}-after", f"{name}-comparison"))
    labels.extend(
        (
            "minio-proof",
            "qdrant-inventory",
            "qdrant-proof",
            "maintenance-reboot-proof",
            "backend-listener-proof",
            "restart-contract-proof",
            "tenant-audit-report",
            "browser-permission-proof",
        )
    )
    return labels


def _private_json(path: Path, payload: object) -> tuple[object, str]:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path.write_bytes(body)
    path.chmod(0o600)
    return payload, hashlib.sha256(body).hexdigest()


def _evidence_root(path: Path, labels: list[str]) -> Path:
    path.mkdir(mode=0o700)
    nested = path / "nested"
    nested.mkdir(mode=0o700)
    for index, label in enumerate(labels):
        parent = nested if index % 2 else path
        artifact = parent / f"artifact-{index:03d}.proof"
        artifact.write_bytes(label.encode("utf-8"))
        artifact.chmod(0o600 if index % 3 else 0o400)
    return path


def _write_private_json(path: Path, payload: object) -> bytes:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    path.write_bytes(body)
    path.chmod(0o600)
    return body


def _authority_fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, Path]]:
    authorities: list[dict[str, str]] = []
    private_keys: dict[str, Path] = {}
    for producer in ("backup_provider", "protected_runner", "release_a_host_collector"):
        private_key = tmp_path / f"{producer}.private.pem"
        public_key = tmp_path / f"{producer}.public.pem"
        subprocess.run(
            ["openssl", "genrsa", "-out", str(private_key), "2048"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["openssl", "rsa", "-in", str(private_key), "-pubout", "-out", str(public_key)],
            check=True,
            capture_output=True,
        )
        pem = public_key.read_text(encoding="ascii")
        authorities.append(
            {
                "issuer": f"{producer}-issuer",
                "producer": producer,
                "signature_algorithm": "rsa-pkcs1v15-sha256",
                "public_key_pem": pem,
                "public_key_sha256": hashlib.sha256(pem.encode("ascii")).hexdigest(),
            }
        )
        private_keys[producer] = private_key
    return {
        "schema_version": 1,
        "kind": "agentium-release-a-evidence-authority-keyring",
        "authorities": authorities,
    }, private_keys


def _canonical_journal(path: Path, attestation: dict[str, object], now: datetime = NOW) -> Path:
    path.mkdir(mode=0o700)
    evidence = attestation["evidence"]
    pg_common = {
        "schema_version": 2,
        "kind": "postgresql_row_inventory",
        "profile": "agentium-postgresql-row-inventory-v2",
        "candidate_sha": RELEASE_A_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "content_serialized": False,
    }
    pg_before = _write_private_json(
        path / "postgres-inventory-before.json", {**pg_common, "marker": "before"}
    )
    pg_after = _write_private_json(
        path / "postgres-inventory-after.json", {**pg_common, "marker": "after"}
    )
    comparison_payload = {
        "schema_version": 1,
        "kind": "agentium-release-a-postgres-comparison",
        "profile": "business_inventory_exact_v1",
        "result": "passed",
        "deployment_id": DEPLOYMENT_ID,
        "release_a_sha": RELEASE_A_SHA,
        "before_sha256": hashlib.sha256(pg_before).hexdigest(),
        "after_sha256": hashlib.sha256(pg_after).hexdigest(),
        "verified_at": _stamp(now, 11),
    }
    pg_comparison = _write_private_json(
        path / "postgres-inventory-comparison.json", comparison_payload
    )
    storage_before = _write_private_json(
        path / "storage-before.json",
        {
            "schema_version": 1,
            "profile": "agentium-storage-attestation-v3",
            "captured_at": _stamp(now, 13),
        },
    )
    storage_after = _write_private_json(
        path / "storage-after.json",
        {
            "schema_version": 1,
            "profile": "agentium-storage-attestation-v3",
            "captured_at": _stamp(now, 12),
        },
    )
    storage_comparison = _write_private_json(
        path / "storage-comparison.json",
        {
            "schema_version": 1,
            "profile": "agentium-storage-release-a-versioning-comparison-v1",
            "result": "passed",
            "failed_checks": [],
        },
    )
    minio = _write_private_json(
        path / "minio-bootstrap-proof.json",
        {
            "schema_version": 1,
            "kind": "agentium-release-a-minio-bootstrap",
            "result": "passed",
            "versioning": "Enabled",
            "delete_denied": True,
            "config_denied": True,
        },
    )
    qdrant = _write_private_json(
        path / "qdrant-bootstrap-proof.json",
        {
            "schema_version": 1,
            "kind": "agentium-release-a-qdrant-bootstrap",
            "result": "passed",
            "read_only_write_denied": True,
            "probe_absent_after": True,
        },
    )
    hostname_sha256 = hashlib.sha256(HOSTNAME.encode("ascii")).hexdigest()
    sftp_started_at = _stamp(now, 7)
    runtime_ready_at = evidence["sftp"]["runtime_ready_at"]
    runtime_identity = hashlib.sha256(
        b"agentium-release-a-sftp-runtime-identity-v1"
        + b"\0"
        + b"\0".join(
            value.encode("utf-8")
            for value in (
                LIVE_SHA,
                RELEASE_A_SHA,
                SFTP_SHA,
                DEPLOYMENT_ID,
                hostname_sha256,
                SFTP_CONTAINER_ID,
                SFTP_IMAGE_ID,
                str(SFTP_PORT),
                sftp_started_at,
            )
        )
    ).hexdigest()
    runtime_ready_payload = {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-runtime-ready",
        "result": "passed",
        "live_sha": LIVE_SHA,
        "release_a_sha": RELEASE_A_SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "hostname_sha256": hostname_sha256,
        "sftp_container_id": SFTP_CONTAINER_ID,
        "sftp_image_id": SFTP_IMAGE_ID,
        "sftp_port": SFTP_PORT,
        "sftp_started_at": sftp_started_at,
        "image_revision": SFTP_SHA,
        "runtime_identity_sha256": runtime_identity,
        "host_key_fingerprint": SFTP_HOST_KEY_FINGERPRINT,
        "state": "running",
        "health_status": "healthy",
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
        "published_transport": {
            "protocol": "tcp",
            "container_port": 2222,
            "host_port": SFTP_PORT,
            "binding_count": 1,
            "binding_sha256": _digest("sftp-binding"),
            "listener_count": 1,
            "established_connection_count_before": 0,
            "established_connection_count_after": 0,
            "external_established_connection_count": 0,
            "ssh_v2_identification_validated": True,
            "connection_closed_before_authentication": True,
            "raw_identification_serialized": False,
        },
        "secure_deposit": {
            "source_matches_dev_sdc": True,
            "source_device_sha256": _digest("/dev/sdc"),
            "autonomous_mountpoint": True,
            "host_read_only": True,
            "namespace_autonomous_mountpoint": True,
            "namespace_read_only": True,
            "device_id": 12345,
        },
        "host_key": {
            "algorithm": "ssh-ed25519",
            "fingerprint": SFTP_HOST_KEY_FINGERPRINT,
            "fingerprint_sha256": hashlib.sha256(
                SFTP_HOST_KEY_FINGERPRINT.encode("ascii")
            ).hexdigest(),
            "present": True,
            "nonempty": True,
            "regular_file": True,
            "symlink": False,
        },
        "credentials_used": False,
        "authentication_attempted": False,
        "sftp_subsystem_requested": False,
        "content_serialized": False,
        "raw_network_data_serialized": False,
        "raw_identification_serialized": False,
        "ready_at": runtime_ready_at,
    }
    runtime_ready = _write_private_json(
        path / "sftp-validation-runtime-ready.json", runtime_ready_payload
    )
    auth_started_at = _stamp(now, 5)
    revoked_at = _stamp(now, 5)
    denial_completed_at = _stamp(now, 4)

    def sftp_event(name: str, event_type: str, occurred_at: str) -> dict[str, object]:
        return {
            "event_type": event_type,
            "event_id_sha256": _digest(f"sftp-{name}-id"),
            "event_digest_sha256": _digest(f"sftp-{name}-digest"),
            "count": 1,
            "occurred_at": occurred_at,
        }

    ledger_payload = {
        "schema_version": 1,
        "kind": "agentium-release-a-sftp-postgres-ledger",
        "result": "passed",
        "live_sha": LIVE_SHA,
        "release_a_sha": RELEASE_A_SHA,
        "sftp_sha": SFTP_SHA,
        "deployment_id": DEPLOYMENT_ID,
        "hostname_sha256": hostname_sha256,
        "workspace_id_sha256": _digest("sftp-workspace-id"),
        "link_id_sha256": _digest("sftp-link-id"),
        "access_id_sha256": _digest("sftp-access-id"),
        "credential_fingerprint_sha256": evidence["sftp"]["credential_fingerprint_sha256"],
        "sftp_container_id": SFTP_CONTAINER_ID,
        "sftp_image_id": SFTP_IMAGE_ID,
        "sftp_port": SFTP_PORT,
        "runtime_identity_sha256": runtime_identity,
        "link_status": "revoked",
        "auth_failed_reason": "inactive_or_expired",
        "remaining_active_link_count": 0,
        "active_sftp_session_count": 0,
        "deposit_file_delta_count": 0,
        "audits": {
            "created": sftp_event("created", "deposit.link.created", auth_started_at),
            "auth_success": sftp_event(
                "auth-success", "deposit.sftp.auth.success", auth_started_at
            ),
            "revoked": sftp_event("revoked", "deposit.link.revoked", revoked_at),
            "auth_failed_inactive": sftp_event(
                "auth-failed", "deposit.sftp.auth.failed", denial_completed_at
            ),
        },
        "binding_sha256": "0" * 64,
        "collected_at": evidence["sftp"]["postgres_ledger_completed_at"],
    }
    ledger_payload["binding_sha256"] = hashlib.sha256(
        b"agentium-release-a-sftp-ledger-v1"
        + b"\0"
        + b"\0".join(
            str(value).encode("utf-8")
            for value in (
                ledger_payload["live_sha"],
                ledger_payload["release_a_sha"],
                ledger_payload["sftp_sha"],
                ledger_payload["deployment_id"],
                ledger_payload["hostname_sha256"],
                ledger_payload["workspace_id_sha256"],
                ledger_payload["link_id_sha256"],
                ledger_payload["access_id_sha256"],
                ledger_payload["credential_fingerprint_sha256"],
                ledger_payload["sftp_container_id"],
                ledger_payload["sftp_image_id"],
                ledger_payload["sftp_port"],
                ledger_payload["runtime_identity_sha256"],
                ledger_payload["link_status"],
                ledger_payload["auth_failed_reason"],
                ledger_payload["remaining_active_link_count"],
                ledger_payload["active_sftp_session_count"],
                ledger_payload["deposit_file_delta_count"],
                *(
                    item
                    for name in (
                        "created",
                        "auth_success",
                        "revoked",
                        "auth_failed_inactive",
                    )
                    for item in (
                        ledger_payload["audits"][name]["event_type"],
                        ledger_payload["audits"][name]["event_id_sha256"],
                        ledger_payload["audits"][name]["event_digest_sha256"],
                        ledger_payload["audits"][name]["count"],
                        ledger_payload["audits"][name]["occurred_at"],
                    )
                ),
                ledger_payload["collected_at"],
            )
        )
    ).hexdigest()
    ledger = _write_private_json(path / "sftp-postgres-ledger-receipt.json", ledger_payload)
    pg = evidence["data_integrity"]["postgresql"]
    pg["before_sha256"] = hashlib.sha256(pg_before).hexdigest()
    pg["after_sha256"] = hashlib.sha256(pg_after).hexdigest()
    pg["comparison_sha256"] = hashlib.sha256(pg_comparison).hexdigest()
    for store in ("qdrant", "minio_object_store", "faiss", "secure_deposit", "rabbitmq"):
        row = evidence["data_integrity"][store]
        row["before_sha256"] = hashlib.sha256(storage_before).hexdigest()
        row["after_sha256"] = hashlib.sha256(storage_after).hexdigest()
        row["comparison_sha256"] = hashlib.sha256(storage_comparison).hexdigest()
    evidence["minio"]["proof_sha256"] = hashlib.sha256(minio).hexdigest()
    evidence["qdrant"]["inventory_sha256"] = hashlib.sha256(storage_after).hexdigest()
    evidence["qdrant"]["proof_sha256"] = hashlib.sha256(qdrant).hexdigest()
    evidence["sftp"]["runtime_ready_receipt_sha256"] = hashlib.sha256(runtime_ready).hexdigest()
    evidence["sftp"]["postgres_ledger_receipt_sha256"] = hashlib.sha256(ledger).hexdigest()
    return path


def _signed_external_root(
    module: ModuleType,
    path: Path,
    attestation: dict[str, object],
    private_keys: dict[str, Path],
    journal_root: Path,
) -> Path:
    path.mkdir(mode=0o700)
    labels = {hashlib.sha256(label.encode()).hexdigest(): label for label in _final_labels()}
    claims = module._attestation_claims(attestation)
    for claim, (token, producer) in module._EXTERNAL_BINDINGS.items():
        if claim == "evidence.sftp.proof_sha256":
            runtime_ready_raw = (journal_root / "sftp-validation-runtime-ready.json").read_bytes()
            ledger_raw = (journal_root / "sftp-postgres-ledger-receipt.json").read_bytes()
            runtime_ready = json.loads(runtime_ready_raw)
            ledger = json.loads(ledger_raw)
            audits = ledger["audits"]
            known_hosts_sha256 = _digest("known-hosts")
            positive_proof = {
                "schema_version": 1,
                "kind": "agentium_release_a_sftp_positive_canary",
                "profile": "agentium-release-a-sftp-positive-canary-v1",
                "result": "passed",
                "live_sha": LIVE_SHA,
                "release_a_sha": RELEASE_A_SHA,
                "sftp_sha": SFTP_SHA,
                "deployment_id": DEPLOYMENT_ID,
                "hostname_sha256": runtime_ready["hostname_sha256"],
                "access_id_sha256": ledger["access_id_sha256"],
                "credential_fingerprint_sha256": ledger["credential_fingerprint_sha256"],
                "known_hosts_sha256": known_hosts_sha256,
                "host_key_fingerprint": runtime_ready["host_key_fingerprint"],
                "sftp_container_id": SFTP_CONTAINER_ID,
                "sftp_image_id": SFTP_IMAGE_ID,
                "sftp_port": SFTP_PORT,
                "sftp_started_at": runtime_ready["sftp_started_at"],
                "runtime_identity_sha256": runtime_ready["runtime_identity_sha256"],
                "runtime_ready_receipt_sha256": hashlib.sha256(runtime_ready_raw).hexdigest(),
                "auth_started_at": audits["created"]["occurred_at"],
                "auth_completed_at": audits["auth_success"]["occurred_at"],
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
            positive_raw = module.sftp_gate._canonical_json_bytes(positive_proof)
            positive_sha256 = hashlib.sha256(positive_raw).hexdigest()
            post_revoke_proof = {
                "schema_version": 1,
                "kind": "agentium_release_a_sftp_post_revoke",
                "profile": "agentium-release-a-sftp-post-revoke-v1",
                "result": "passed",
                "live_sha": LIVE_SHA,
                "release_a_sha": RELEASE_A_SHA,
                "sftp_sha": SFTP_SHA,
                "deployment_id": DEPLOYMENT_ID,
                "hostname_sha256": runtime_ready["hostname_sha256"],
                "access_id_sha256": ledger["access_id_sha256"],
                "credential_fingerprint_sha256": ledger["credential_fingerprint_sha256"],
                "known_hosts_sha256": known_hosts_sha256,
                "host_key_fingerprint": runtime_ready["host_key_fingerprint"],
                "sftp_container_id": SFTP_CONTAINER_ID,
                "sftp_image_id": SFTP_IMAGE_ID,
                "sftp_port": SFTP_PORT,
                "sftp_started_at": runtime_ready["sftp_started_at"],
                "runtime_identity_sha256": runtime_ready["runtime_identity_sha256"],
                "runtime_ready_receipt_sha256": hashlib.sha256(runtime_ready_raw).hexdigest(),
                "positive_evidence_sha256": positive_sha256,
                "positive_completed_at": positive_proof["auth_completed_at"],
                "revocation_check_started_at": audits["revoked"]["occurred_at"],
                "completed_at": audits["auth_failed_inactive"]["occurred_at"],
                "authentication_denied": True,
                "sftp_subsystem_requested_after_revocation": False,
                "directory_enumeration_operations": 0,
                "content_read_operations": 0,
                "mutation_operations": 0,
            }
            post_revoke_raw = module.sftp_gate._canonical_json_bytes(post_revoke_proof)
            post_revoke_sha256 = hashlib.sha256(post_revoke_raw).hexdigest()
            artifact_payload = {
                "schema_version": 1,
                "kind": "sftp-positive-auth.artifact",
                "profile": "agentium-release-a-sftp-positive-auth-lifecycle-v1",
                "result": "passed",
                "live_sha": LIVE_SHA,
                "release_a_sha": RELEASE_A_SHA,
                "sftp_sha": SFTP_SHA,
                "deployment_id": DEPLOYMENT_ID,
                "hostname_sha256": runtime_ready["hostname_sha256"],
                "workspace_id_sha256": ledger["workspace_id_sha256"],
                "link_id_sha256": ledger["link_id_sha256"],
                "access_id_sha256": ledger["access_id_sha256"],
                "credential_fingerprint_sha256": ledger["credential_fingerprint_sha256"],
                "known_hosts_sha256": known_hosts_sha256,
                "host_key_fingerprint": runtime_ready["host_key_fingerprint"],
                "sftp_container_id": SFTP_CONTAINER_ID,
                "sftp_image_id": SFTP_IMAGE_ID,
                "sftp_port": SFTP_PORT,
                "sftp_started_at": runtime_ready["sftp_started_at"],
                "image_revision": SFTP_SHA,
                "runtime_identity_sha256": runtime_ready["runtime_identity_sha256"],
                "runtime_ready_receipt_sha256": hashlib.sha256(runtime_ready_raw).hexdigest(),
                "ingress_closed": True,
                "restart_disabled": True,
                "restart_policy_disabled": True,
                "secure_deposit_mode": "ro",
                "secure_deposit_source": "/dev/sdc",
                "external_established_connection_count": 0,
                "ingress_gate": runtime_ready["ingress_gate"],
                "positive_evidence_sha256": positive_sha256,
                "post_revoke_evidence_sha256": post_revoke_sha256,
                "positive_proof": positive_proof,
                "post_revoke_proof": post_revoke_proof,
                "ledger_sha256": hashlib.sha256(ledger_raw).hexdigest(),
                "auth_started_at": audits["created"]["occurred_at"],
                "auth_completed_at": audits["auth_success"]["occurred_at"],
                "revoked_at": audits["revoked"]["occurred_at"],
                "denial_started_at": audits["revoked"]["occurred_at"],
                "denial_completed_at": audits["auth_failed_inactive"]["occurred_at"],
                "completed_at": attestation["evidence"]["sftp"]["completed_at"],
                "authentication_result": "passed",
                "subsystem_result": "passed",
                "revoke_result": "passed",
                "post_revoke_authentication_result": "denied_inactive",
                "link_status": "revoked",
                "remaining_active_link_count": 0,
                "active_sftp_session_count": 0,
                "deposit_file_delta_count": 0,
                "audit_summary": {
                    "workspace_id_sha256": ledger["workspace_id_sha256"],
                    "link_id_sha256": ledger["link_id_sha256"],
                    "access_id_sha256": ledger["access_id_sha256"],
                    "created_event_id_sha256": audits["created"]["event_id_sha256"],
                    "created_event_digest_sha256": audits["created"]["event_digest_sha256"],
                    "auth_success_event_id_sha256": audits["auth_success"]["event_id_sha256"],
                    "auth_success_event_digest_sha256": audits["auth_success"][
                        "event_digest_sha256"
                    ],
                    "revoked_event_id_sha256": audits["revoked"]["event_id_sha256"],
                    "revoked_event_digest_sha256": audits["revoked"]["event_digest_sha256"],
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
                },
            }
            artifact = module.sftp_gate._canonical_json_bytes(artifact_payload)
            attestation["evidence"]["sftp"]["proof_sha256"] = hashlib.sha256(artifact).hexdigest()
            claims = module._attestation_claims(attestation)
        else:
            artifact = labels[claims[claim]["digest"]].encode()
        artifact_path = path / f"{token}.artifact"
        artifact_path.write_bytes(artifact)
        artifact_path.chmod(0o600)
        provenance = {
            "schema_version": 1,
            "kind": "agentium-release-a-external-proof-provenance",
            "result": "passed",
            "environment": "production",
            "claim": claim,
            "producer": producer,
            "issuer": f"{producer}-issuer",
            "deployment_id": DEPLOYMENT_ID,
            "live_sha": LIVE_SHA,
            "release_a_sha": RELEASE_A_SHA,
            "sftp_release_sha": SFTP_SHA,
            "hostname_sha256": hashlib.sha256(HOSTNAME.encode()).hexdigest(),
            "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
            "captured_at": claims[claim]["event_at"],
        }
        provenance_path = path / f"{token}.provenance.json"
        _write_private_json(provenance_path, provenance)
        signature_path = path / f"{token}.signature"
        subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                str(private_keys[producer]),
                "-out",
                str(signature_path),
                str(provenance_path),
            ],
            check=True,
            capture_output=True,
        )
        signature_path.chmod(0o600)
    return path


def _precondition_receipt(module: ModuleType, tmp_path: Path) -> dict[str, object]:
    payload, digest = _private_json(tmp_path / "preconditions.json", _preconditions())
    return module.verify_preconditions_bundle(
        payload,
        input_sha256=digest,
        evidence_root=_evidence_root(tmp_path / "pre-evidence", _precondition_labels()),
        live_sha=LIVE_SHA,
        release_a_sha=RELEASE_A_SHA,
        hostname=HOSTNAME,
        deployment_id=DEPLOYMENT_ID,
        now=NOW,
    )


def test_two_phase_receipts_bind_exact_bytes_and_remain_content_free(
    module: ModuleType, tmp_path: Path
) -> None:
    preconditions, preconditions_sha = _private_json(
        tmp_path / "preconditions.json", _preconditions()
    )
    pre = module.verify_preconditions_bundle(
        preconditions,
        input_sha256=preconditions_sha,
        evidence_root=_evidence_root(tmp_path / "pre-evidence", _precondition_labels()),
        live_sha=LIVE_SHA,
        release_a_sha=RELEASE_A_SHA,
        hostname=HOSTNAME,
        deployment_id=DEPLOYMENT_ID,
        now=NOW,
    )
    assert pre["evidence_file_count"] == 6
    assert pre["evidence_digest_count"] == 6

    pre_path = tmp_path / "pre-receipt.json"
    prerequisite, prerequisite_sha = _private_json(pre_path, pre)
    attestation = _attestation()
    journal_root = _canonical_journal(tmp_path / "journal", attestation)
    authority_keyring, private_keys = _authority_fixture(tmp_path)
    final_root = _signed_external_root(
        module, tmp_path / "final-evidence", attestation, private_keys, journal_root
    )
    attestation, attestation_sha = _private_json(tmp_path / "attestation.json", attestation)
    final = module.verify_final_bundle(
        attestation,
        input_sha256=attestation_sha,
        preconditions_receipt=prerequisite,
        preconditions_receipt_sha256=prerequisite_sha,
        evidence_root=final_root,
        journal_root=journal_root,
        authority_keyring=authority_keyring,
        authority_keyring_sha256=hashlib.sha256(
            module._canonical_json(authority_keyring) + b"\n"
        ).hexdigest(),
        live_sha=LIVE_SHA,
        release_a_sha=RELEASE_A_SHA,
        sftp_sha=SFTP_SHA,
        hostname=HOSTNAME,
        deployment_id=DEPLOYMENT_ID,
        now=NOW,
    )
    assert final["evidence_file_count"] == 24
    assert final["evidence_digest_count"] == 24
    assert final["evidence_reference_count"] == 37
    assert final["attestation_sha256"] == attestation_sha
    assert final["preconditions_receipt_sha256"] == prerequisite_sha
    external_crypto_digests = [
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in final_root.iterdir()
        if path.name.endswith((".provenance.json", ".signature"))
    ]
    assert len(external_crypto_digests) == 28
    assert final["external_provenance_set_sha256"] == module._proof_set_sha256(
        external_crypto_digests
    )
    rendered = json.dumps(final, sort_keys=True)
    for forbidden in (
        HOSTNAME,
        "artifact-",
        "restore-0",
        "minio-proof",
        "browser-credential",
        str(tmp_path),
    ):
        assert forbidden not in rendered


def test_only_real_artifact_digests_are_extracted(module: ModuleType) -> None:
    payload = _attestation()
    extracted = set(module._attestation_digests(payload))
    assert len(extracted) == 37
    for identity_only in (
        "backup-id-0",
        "minio-application-credential",
        "minio-root-credential",
        "qdrant-admin-key",
        "qdrant-read-only-key",
        "browser-credential",
        "sftp-credential",
    ):
        assert _digest(identity_only) not in extracted


def test_forged_external_proof_signed_by_unapproved_key_is_rejected(
    module: ModuleType, tmp_path: Path
) -> None:
    pre = _precondition_receipt(module, tmp_path)
    attestation = _attestation()
    journal_root = _canonical_journal(tmp_path / "journal", attestation)
    approved_keyring, approved_keys = _authority_fixture(tmp_path)
    evidence_root = _signed_external_root(
        module,
        tmp_path / "final-evidence",
        attestation,
        approved_keys,
        journal_root,
    )
    attacker_root = tmp_path / "attacker"
    attacker_root.mkdir(mode=0o700)
    _, attacker_keys = _authority_fixture(attacker_root)
    claim = "evidence.canaries.showcase.proof_sha256"
    token, producer = module._EXTERNAL_BINDINGS[claim]
    artifact = evidence_root / f"{token}.artifact"
    artifact.write_bytes(b"forged-showcase-proof")
    artifact.chmod(0o600)
    attestation["evidence"]["canaries"]["showcase"]["proof_sha256"] = hashlib.sha256(
        artifact.read_bytes()
    ).hexdigest()
    provenance_path = evidence_root / f"{token}.provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    provenance["artifact_sha256"] = attestation["evidence"]["canaries"]["showcase"]["proof_sha256"]
    _write_private_json(provenance_path, provenance)
    signature = evidence_root / f"{token}.signature"
    subprocess.run(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(attacker_keys[producer]),
            "-out",
            str(signature),
            str(provenance_path),
        ],
        check=True,
        capture_output=True,
    )
    signature.chmod(0o600)
    with pytest.raises(module.EvidenceBundleError, match="signature is invalid"):
        module.verify_final_bundle(
            attestation,
            input_sha256=_digest("forged-attestation"),
            preconditions_receipt=pre,
            preconditions_receipt_sha256=_digest("precondition-receipt"),
            evidence_root=evidence_root,
            journal_root=journal_root,
            authority_keyring=approved_keyring,
            authority_keyring_sha256=hashlib.sha256(
                module._canonical_json(approved_keyring) + b"\n"
            ).hexdigest(),
            live_sha=LIVE_SHA,
            release_a_sha=RELEASE_A_SHA,
            sftp_sha=SFTP_SHA,
            hostname=HOSTNAME,
            deployment_id=DEPLOYMENT_ID,
            now=NOW,
        )


def test_valid_but_unapproved_authority_keyring_digest_is_rejected(
    module: ModuleType, tmp_path: Path
) -> None:
    keyring, _ = _authority_fixture(tmp_path)
    keyring_path = tmp_path / "attacker-keyring.json"
    _private_json(keyring_path, keyring)
    attestation = tmp_path / "attestation.json"
    preconditions = tmp_path / "preconditions-receipt.json"
    _private_json(attestation, {})
    _private_json(preconditions, {})
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir(mode=0o700)
    journal_root = tmp_path / "journal"
    journal_root.mkdir(mode=0o700)
    output_root = tmp_path / "output"
    output_root.mkdir(mode=0o700)
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "verify-final",
            "--attestation",
            str(attestation),
            "--preconditions-receipt",
            str(preconditions),
            "--evidence-root",
            str(evidence_root),
            "--journal-root",
            str(journal_root),
            "--authority-keyring",
            str(keyring_path),
            "--expected-authority-keyring-sha256",
            _digest("review-approved-keyring"),
            "--binding-manifest-output",
            str(output_root / "bindings.json"),
            "--frozen-evidence-output",
            str(output_root / "external-final-evidence"),
            "--expected-live-sha",
            LIVE_SHA,
            "--expected-release-a-sha",
            RELEASE_A_SHA,
            "--expected-sftp-sha",
            SFTP_SHA,
            "--expected-hostname",
            HOSTNAME,
            "--deployment-id",
            DEPLOYMENT_ID,
            "--output",
            str(output_root / "receipt.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "differs from approved digest" in result.stderr


def test_transaction_preflight_refuses_empty_authority_keyring(tmp_path: Path) -> None:
    keyring_path = tmp_path / "empty-authority-keyring.json"
    _private_json(
        keyring_path,
        {
            "schema_version": 1,
            "kind": "agentium-release-a-evidence-authority-keyring",
            "authorities": [],
        },
    )
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "verify-authority-keyring",
            "--authority-keyring",
            str(keyring_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "authority keyring cardinality differs" in result.stderr


def test_authority_keyring_rejects_key_reuse_algorithm_and_weak_rsa(
    module: ModuleType, tmp_path: Path
) -> None:
    keyring, _ = _authority_fixture(tmp_path)
    rows = keyring["authorities"]
    assert isinstance(rows, list)

    reused = json.loads(json.dumps(keyring))
    reused_rows = reused["authorities"]
    reused_rows[1]["public_key_pem"] = reused_rows[0]["public_key_pem"]
    reused_rows[1]["public_key_sha256"] = reused_rows[0]["public_key_sha256"]
    with pytest.raises(module.EvidenceBundleError, match="reused across producer"):
        module._authority_keyring(reused)

    unsupported = json.loads(json.dumps(keyring))
    unsupported["authorities"][0]["signature_algorithm"] = "rsa-pss-sha256"
    with pytest.raises(module.EvidenceBundleError, match="algorithm differs"):
        module._authority_keyring(unsupported)

    weak_private = tmp_path / "weak.private.pem"
    weak_public = tmp_path / "weak.public.pem"
    subprocess.run(
        ["openssl", "genrsa", "-out", str(weak_private), "1024"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "rsa", "-in", str(weak_private), "-pubout", "-out", str(weak_public)],
        check=True,
        capture_output=True,
    )
    weak = json.loads(json.dumps(keyring))
    weak_pem = weak_public.read_text(encoding="ascii")
    weak["authorities"][0]["public_key_pem"] = weak_pem
    weak["authorities"][0]["public_key_sha256"] = hashlib.sha256(
        weak_pem.encode("ascii")
    ).hexdigest()
    with pytest.raises(module.EvidenceBundleError, match="RSA 2048..4096"):
        module._authority_keyring(weak)


def test_missing_unexpected_and_identity_only_files_fail_closed(
    module: ModuleType, tmp_path: Path
) -> None:
    labels = _precondition_labels()
    missing = _evidence_root(tmp_path / "missing", labels[:-1])
    with pytest.raises(module.EvidenceBundleError, match="absent"):
        module.verify_evidence_root(missing, [_digest(label) for label in labels])

    unexpected = _evidence_root(tmp_path / "unexpected", labels)
    extra = unexpected / "extra.proof"
    extra.write_bytes(b"not-declared")
    extra.chmod(0o600)
    with pytest.raises(module.EvidenceBundleError, match="unexpected"):
        module.verify_evidence_root(unexpected, [_digest(label) for label in labels])

    identity = _evidence_root(tmp_path / "identity", labels)
    fingerprint = identity / "credential-fingerprint.proof"
    fingerprint.write_bytes(b"browser-credential")
    fingerprint.chmod(0o600)
    with pytest.raises(module.EvidenceBundleError, match="unexpected"):
        module.verify_evidence_root(identity, [_digest(label) for label in labels])


@pytest.mark.parametrize("attack", ("root-mode", "file-mode", "symlink", "hardlink"))
def test_private_real_single_link_tree_is_mandatory(
    module: ModuleType, tmp_path: Path, attack: str
) -> None:
    root = _evidence_root(tmp_path / attack, ["proof"])
    artifact = root / "artifact-000.proof"
    if attack == "root-mode":
        root.chmod(0o750)
    elif attack == "file-mode":
        artifact.chmod(0o640)
    elif attack == "symlink":
        link = root / "link.proof"
        link.symlink_to(artifact)
    else:
        os.link(artifact, root / "hard.proof")
    with pytest.raises(module.EvidenceBundleError):
        module.verify_evidence_root(root, [_digest("proof")])


def test_duplicate_json_keys_and_json_hardlinks_are_rejected(
    module: ModuleType, tmp_path: Path
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"result":"passed","result":"failed"}', encoding="utf-8")
    duplicate.chmod(0o600)
    with pytest.raises(module.EvidenceBundleError, match="duplicate"):
        module.load_private_json(duplicate)
    hardlink = tmp_path / "hardlink.json"
    os.link(duplicate, hardlink)
    with pytest.raises(module.EvidenceBundleError, match="single-link"):
        module.load_private_json(duplicate)


def test_file_mutation_during_read_is_detected(
    module: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _evidence_root(tmp_path / "race", ["stable-proof"])
    artifact = root / "artifact-000.proof"
    artifact.chmod(0o600)
    original_read = module.os.read
    mutated = False

    def racing_read(descriptor: int, size: int) -> bytes:
        nonlocal mutated
        body = original_read(descriptor, size)
        if body and not mutated:
            mutated = True
            artifact.write_bytes(b"changed-proof")
            artifact.chmod(0o600)
        return body

    monkeypatch.setattr(module.os, "read", racing_read)
    with pytest.raises(module.EvidenceBundleError, match="changed"):
        module.verify_evidence_root(root, [_digest("stable-proof")])


def test_final_receipt_rejects_wrong_identity_stale_receipt_and_restore_drift(
    module: ModuleType, tmp_path: Path
) -> None:
    pre = _precondition_receipt(module, tmp_path)
    attestation = _attestation()
    journal_root = _canonical_journal(tmp_path / "journal", attestation)
    authority_keyring, private_keys = _authority_fixture(tmp_path)
    root = _signed_external_root(
        module, tmp_path / "final-evidence", attestation, private_keys, journal_root
    )
    attestation_path = tmp_path / "attestation.json"
    _, attestation_sha = _private_json(attestation_path, attestation)

    for mutation, message in (
        (lambda row: row.update(deployment_id="different-release"), "deployment_id"),
        (
            lambda row: row.update(verified_at=_stamp(NOW - timedelta(days=2), 0)),
            "stale",
        ),
    ):
        candidate = copy.deepcopy(pre)
        mutation(candidate)
        with pytest.raises(module.EvidenceBundleError, match=message):
            module.verify_final_bundle(
                attestation,
                input_sha256=attestation_sha,
                preconditions_receipt=candidate,
                preconditions_receipt_sha256=_digest("receipt-bytes"),
                evidence_root=root,
                journal_root=journal_root,
                authority_keyring=authority_keyring,
                authority_keyring_sha256=hashlib.sha256(
                    module._canonical_json(authority_keyring) + b"\n"
                ).hexdigest(),
                live_sha=LIVE_SHA,
                release_a_sha=RELEASE_A_SHA,
                sftp_sha=SFTP_SHA,
                hostname=HOSTNAME,
                deployment_id=DEPLOYMENT_ID,
                now=NOW,
            )

    drifted = copy.deepcopy(attestation)
    drifted["evidence"]["off_vm_backups"][0]["restore_check"]["proof_sha256"] = _digest(
        "different-restore"
    )
    with pytest.raises(module.EvidenceBundleError, match="restore proofs differ"):
        module.verify_final_bundle(
            drifted,
            input_sha256=_digest("drifted-attestation"),
            preconditions_receipt=pre,
            preconditions_receipt_sha256=_digest("receipt-bytes"),
            evidence_root=root,
            journal_root=journal_root,
            authority_keyring=authority_keyring,
            authority_keyring_sha256=hashlib.sha256(
                module._canonical_json(authority_keyring) + b"\n"
            ).hexdigest(),
            live_sha=LIVE_SHA,
            release_a_sha=RELEASE_A_SHA,
            sftp_sha=SFTP_SHA,
            hostname=HOSTNAME,
            deployment_id=DEPLOYMENT_ID,
            now=NOW,
        )


def test_cli_two_phase_receipts_are_exclusive_private_canonical_and_optimized(
    module: ModuleType, tmp_path: Path
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    pre_path = tmp_path / "preconditions.json"
    _private_json(pre_path, _preconditions(now))
    pre_root = _evidence_root(tmp_path / "pre-evidence", _precondition_labels())
    receipts = tmp_path / "receipts"
    receipts.mkdir(mode=0o700)
    receipts.chmod(0o700)
    pre_receipt = receipts / "pre.json"
    common = [
        "--evidence-root",
        str(pre_root),
        "--expected-live-sha",
        LIVE_SHA,
        "--expected-release-a-sha",
        RELEASE_A_SHA,
        "--expected-hostname",
        HOSTNAME,
        "--deployment-id",
        DEPLOYMENT_ID,
        "--output",
        str(pre_receipt),
    ]
    command = [
        sys.executable,
        str(HELPER),
        "verify-preconditions",
        "--preconditions",
        str(pre_path),
        *common,
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert pre_receipt.stat().st_mode & 0o777 == 0o600
    parsed = json.loads(pre_receipt.read_text(encoding="utf-8"))
    canonical = module._canonical_json(parsed) + b"\n"
    assert pre_receipt.read_bytes() == canonical
    second = subprocess.run(command, capture_output=True, text=True, check=False)
    assert second.returncode == 1
    assert pre_receipt.read_bytes() == canonical

    attestation_path = tmp_path / "attestation.json"
    attestation = _attestation(now)
    journal_root = _canonical_journal(tmp_path / "journal", attestation, now)
    authority_keyring, private_keys = _authority_fixture(tmp_path)
    keyring_path = tmp_path / "authority-keyring.json"
    _, keyring_sha256 = _private_json(keyring_path, authority_keyring)
    final_root = _signed_external_root(
        module, tmp_path / "final-evidence", attestation, private_keys, journal_root
    )
    _private_json(attestation_path, attestation)
    final_receipt = receipts / "final.json"
    binding_manifest = receipts / "bindings.json"
    frozen_evidence = receipts / "external-final-evidence"
    final = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "verify-final",
            "--attestation",
            str(attestation_path),
            "--preconditions-receipt",
            str(pre_receipt),
            "--expected-sftp-sha",
            SFTP_SHA,
            "--evidence-root",
            str(final_root),
            "--journal-root",
            str(journal_root),
            "--authority-keyring",
            str(keyring_path),
            "--expected-authority-keyring-sha256",
            keyring_sha256,
            "--binding-manifest-output",
            str(binding_manifest),
            "--frozen-evidence-output",
            str(frozen_evidence),
            "--expected-live-sha",
            LIVE_SHA,
            "--expected-release-a-sha",
            RELEASE_A_SHA,
            "--expected-hostname",
            HOSTNAME,
            "--deployment-id",
            DEPLOYMENT_ID,
            "--output",
            str(final_receipt),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert final.returncode == 0, final.stderr
    assert final_receipt.stat().st_mode & 0o777 == 0o600

    missing_root = _evidence_root(tmp_path / "optimized-missing", _precondition_labels()[:-1])
    optimized_receipt = receipts / "optimized.json"
    optimized = subprocess.run(
        [
            sys.executable,
            "-O",
            str(HELPER),
            "verify-preconditions",
            "--preconditions",
            str(pre_path),
            "--evidence-root",
            str(missing_root),
            "--expected-live-sha",
            LIVE_SHA,
            "--expected-release-a-sha",
            RELEASE_A_SHA,
            "--expected-hostname",
            HOSTNAME,
            "--deployment-id",
            DEPLOYMENT_ID,
            "--output",
            str(optimized_receipt),
        ],
        env={**os.environ, "PYTHONOPTIMIZE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert optimized.returncode == 1
    assert "absent" in optimized.stderr
    assert not optimized_receipt.exists()
