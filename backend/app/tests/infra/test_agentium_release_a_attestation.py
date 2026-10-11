"""Mutation tests for the content-free three-filesystem Release A gate."""

from __future__ import annotations

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
HELPER = ROOT / "scripts" / "agentium_release_a_attestation.py"
SHA = "a" * 40
SFTP_SHA = "b" * 40
HOSTNAME = "agentium.papai.ai"
NOW = datetime(2026, 7, 22, 18, 0, tzinfo=UTC)
CANARY_NAMES = {"showcase", "andritz", "sentinel", "octocity", "livekit"}
DATA_INTEGRITY_NAMES = {
    "postgresql",
    "qdrant",
    "minio_object_store",
    "faiss",
    "secure_deposit",
    "rabbitmq",
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agentium_release_a_attestation_test", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def module() -> ModuleType:
    return _load()


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _stamp(minutes_before: int, *, now: datetime = NOW) -> str:
    return (now - timedelta(minutes=minutes_before)).isoformat().replace("+00:00", "Z")


def _attestation(*, now: datetime = NOW) -> dict[str, object]:
    return {
        "schema_version": 4,
        "kind": "agentium-release-a-attestation",
        "result": "passed",
        "environment": "production",
        "release_a_sha": SHA,
        "sftp_release_sha": SFTP_SHA,
        "hostname": HOSTNAME,
        "attested_at": _stamp(0, now=now),
        "evidence": {
            "off_vm_backups": [
                {
                    "source_device": "/dev/sda1",
                    "provider": "root-volume-backup",
                    "backup_id_sha256": _digest("sda1-backup-id"),
                    "completed_at": _stamp(23, now=now),
                    "restore_check": {
                        "result": "passed",
                        "proof_sha256": _digest("sda1-restore-proof"),
                        "completed_at": _stamp(21, now=now),
                    },
                },
                {
                    "source_device": "/dev/sdb",
                    "provider": "ovh-backup",
                    "backup_id_sha256": _digest("sdb-backup-id"),
                    "completed_at": _stamp(20, now=now),
                    "restore_check": {
                        "result": "passed",
                        "proof_sha256": _digest("sdb-restore-proof"),
                        "completed_at": _stamp(18, now=now),
                    },
                },
                {
                    "source_device": "/dev/sdc",
                    "provider": "secondary-vault",
                    "backup_id_sha256": _digest("sdc-backup-id"),
                    "completed_at": _stamp(17, now=now),
                    "restore_check": {
                        "result": "passed",
                        "proof_sha256": _digest("sdc-restore-proof"),
                        "completed_at": _stamp(15, now=now),
                    },
                },
            ],
            "canaries": {
                name: {
                    "result": "passed",
                    "proof_sha256": _digest(f"{name}-canary-proof"),
                    "completed_at": _stamp(4, now=now),
                }
                for name in CANARY_NAMES
            },
            "data_integrity": {
                name: {
                    "result": "passed",
                    "before_sha256": _digest(f"{name}-before"),
                    "before_at": _stamp(13, now=now),
                    "after_sha256": _digest(f"{name}-after"),
                    "after_at": _stamp(12, now=now),
                    "comparison_sha256": _digest(f"{name}-comparison"),
                    "completed_at": _stamp(11, now=now),
                }
                for name in DATA_INTEGRITY_NAMES
            },
            "minio": {
                "versioning": "Enabled",
                "application_credential_fingerprint_sha256": _digest("minio-application"),
                "root_credential_fingerprint_sha256": _digest("minio-root"),
                "canary": {"delete_denied": True, "config_denied": True},
                "proof_sha256": _digest("minio-proof"),
                "completed_at": _stamp(14, now=now),
            },
            "qdrant": {
                "admin_key_fingerprint_sha256": _digest("qdrant-admin"),
                "read_only_key_fingerprint_sha256": _digest("qdrant-read-only"),
                "read_only_write_denied": True,
                "inventory_sha256": _digest("qdrant-inventory"),
                "proof_sha256": _digest("qdrant-proof"),
                "completed_at": _stamp(12, now=now),
            },
            "runtime": {
                "maintenance_gate": {
                    "survived_reboot": True,
                    "proof_sha256": _digest("maintenance-reboot-proof"),
                    "completed_at": _stamp(10, now=now),
                },
                "backend": {
                    "listener": "127.0.0.1:8000",
                    "public_listener_count": 0,
                    "proof_sha256": _digest("backend-listener-proof"),
                    "completed_at": _stamp(9, now=now),
                },
                "restart_contract": {
                    "result": "passed",
                    "proof_sha256": _digest("restart-contract-proof"),
                    "completed_at": _stamp(8, now=now),
                },
            },
            "tenant_audit": {
                "cross_workspace_binding_count": 0,
                "report_sha256": _digest("tenant-audit-report"),
                "completed_at": _stamp(6, now=now),
            },
            "sftp": {
                "image_revision": SFTP_SHA,
                "runtime_ready_receipt_sha256": _digest("sftp-runtime-ready"),
                "runtime_ready_at": _stamp(6, now=now),
                "authentication_result": "passed",
                "subsystem_result": "passed",
                "revocation_result": "passed",
                "post_revocation_authentication_result": "denied",
                "ledger_result": "passed",
                "postgres_ledger_receipt_sha256": _digest("sftp-postgres-ledger"),
                "postgres_ledger_completed_at": _stamp(5, now=now),
                "credential_fingerprint_sha256": _digest("sftp-canary-credential"),
                "proof_sha256": _digest("positive-sftp-proof"),
                "completed_at": _stamp(4, now=now),
            },
            "principals": {
                "browser_canary": {
                    "principal_kind": "service_account",
                    "non_personal": True,
                    "least_privilege": True,
                    "credential_fingerprint_sha256": _digest("browser-canary-credential"),
                    "permission_probe_sha256": _digest("browser-canary-permission-probe"),
                    "permission_probe_result": "passed",
                    "completed_at": _stamp(4, now=now),
                },
                "sftp_canary": {
                    "principal_kind": "disposable_sftp",
                    "disposable": True,
                    "credential_fingerprint_sha256": _digest("sftp-canary-credential"),
                    "completed_at": _stamp(4, now=now),
                },
            },
        },
    }


def _verify(module: ModuleType, payload: object, **kwargs: object) -> dict[str, object]:
    return module.verify_attestation(
        payload,
        expected_release_a_sha=kwargs.pop("expected_release_a_sha", SHA),
        expected_sftp_sha=kwargs.pop("expected_sftp_sha", SFTP_SHA),
        expected_hostname=kwargs.pop("expected_hostname", HOSTNAME),
        max_age_hours=kwargs.pop("max_age_hours", 24),
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


def _write_private(path: Path, payload: object | str) -> Path:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_valid_attestation_emits_exact_bounded_sha_bound_content_free_receipt(module) -> None:
    payload = _attestation()
    receipt = _verify(module, payload)

    assert set(receipt) == {
        "schema_version",
        "kind",
        "result",
        "environment",
        "release_a_sha",
        "sftp_release_sha",
        "hostname_sha256",
        "attestation_sha256",
        "evidence_sha256",
        "verified_at",
        "fresh_until",
    }
    assert receipt["schema_version"] == 4
    assert receipt["kind"] == "agentium-release-a-verification-receipt"
    assert receipt["result"] == "passed"
    assert receipt["environment"] == "production"
    assert receipt["release_a_sha"] == SHA
    assert receipt["sftp_release_sha"] == SFTP_SHA
    assert receipt["hostname_sha256"] == _digest(HOSTNAME)
    assert len(json.dumps(receipt, separators=(",", ":")).encode()) < 4096
    rendered = json.dumps(receipt, sort_keys=True)
    for forbidden in (
        HOSTNAME,
        "root-volume-backup",
        "ovh-backup",
        "secondary-vault",
        "/dev/sda1",
        "/dev/sdb",
        "/dev/sdc",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 1, "schema_version"),
        ("schema_version", True, "schema_version"),
        ("kind", "some-other-kind", "kind"),
        ("result", "waived", "result"),
        ("environment", "staging", "environment"),
        ("release_a_sha", "b" * 40, "differs"),
        ("sftp_release_sha", "c" * 40, "differs"),
        ("hostname", "other.example", "differs"),
    ],
)
def test_top_level_identity_mutations_fail_closed(module, field, value, message) -> None:
    payload = _attestation()
    payload[field] = value
    with pytest.raises(module.ReleaseAAttestationError, match=message):
        _verify(module, payload)


@pytest.mark.parametrize("operation", ["missing", "extra"])
def test_every_object_has_an_exact_field_set(module, operation) -> None:
    payload = _attestation()
    minio = payload["evidence"]["minio"]
    if operation == "missing":
        minio.pop("proof_sha256")
    else:
        minio["credential"] = "must-never-be-present"
    with pytest.raises(module.ReleaseAAttestationError, match="invalid field set"):
        _verify(module, payload)


@pytest.mark.parametrize(
    ("timestamp", "message"),
    [
        ("2026-07-22T17:59:00+00:00", "ending in Z"),
        ("not-a-time", "ending in Z"),
        (_stamp(24 * 60 + 1), "stale"),
        ((NOW + timedelta(minutes=6)).isoformat().replace("+00:00", "Z"), "future"),
    ],
)
def test_attestation_timestamp_is_strict_utc_fresh_and_bounded(module, timestamp, message) -> None:
    payload = _attestation()
    payload["attested_at"] = timestamp
    with pytest.raises(module.ReleaseAAttestationError, match=message):
        _verify(module, payload)


@pytest.mark.parametrize("max_age", [0, 0.1, 169, float("inf"), float("nan"), True])
def test_max_age_cannot_disable_the_freshness_gate(module, max_age) -> None:
    with pytest.raises(module.ReleaseAAttestationError, match="max age"):
        _verify(module, _attestation(), max_age_hours=max_age)


def test_each_evidence_timestamp_must_be_fresh_and_not_later_than_attestation(module) -> None:
    stale = _attestation()
    stale["evidence"]["qdrant"]["completed_at"] = _stamp(24 * 60 + 1)
    with pytest.raises(module.ReleaseAAttestationError, match="stale"):
        _verify(module, stale)

    future = _attestation()
    future["evidence"]["sftp"]["completed_at"] = _stamp(-1)
    with pytest.raises(module.ReleaseAAttestationError, match="later than attested_at"):
        _verify(module, future)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows.pop(), "exactly three"),
        (lambda rows: rows[2].update(source_device="/dev/sdb"), "duplicated"),
        (lambda rows: rows[0].update(source_device="/dev/sdz"), "invalid"),
        (
            lambda rows: rows[1].update(backup_id_sha256=rows[0]["backup_id_sha256"]),
            "identifiers must be distinct",
        ),
        (lambda rows: rows[0].update(provider="https://backup.example/tenant"), "provider"),
        (lambda rows: rows[0]["restore_check"].update(result="skipped"), "result"),
        (
            lambda rows: rows[0]["restore_check"].update(proof_sha256="not-a-digest"),
            "proof_sha256",
        ),
        (
            lambda rows: rows[1]["restore_check"].update(
                proof_sha256=rows[0]["restore_check"]["proof_sha256"]
            ),
            "restore proofs",
        ),
        (
            lambda rows: rows[0]["restore_check"].update(completed_at=_stamp(24)),
            "predates",
        ),
    ],
)
def test_all_three_distinct_off_vm_backups_and_restore_checks_are_mandatory(
    module, mutation, message
) -> None:
    payload = _attestation()
    mutation(payload["evidence"]["off_vm_backups"])
    with pytest.raises(module.ReleaseAAttestationError, match=message):
        _verify(module, payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows.pop("showcase"), "invalid field set"),
        (
            lambda rows: rows.update(
                unexpected={
                    "result": "passed",
                    "proof_sha256": _digest("unexpected-canary"),
                    "completed_at": _stamp(4),
                }
            ),
            "invalid field set",
        ),
        (lambda rows: rows["andritz"].update(result="failed"), "result"),
        (
            lambda rows: rows["sentinel"].update(proof_sha256="tampered"),
            "proof_sha256",
        ),
        (
            lambda rows: rows["octocity"].update(completed_at=_stamp(24 * 60 + 1)),
            "stale",
        ),
    ],
)
def test_all_fixed_release_a_canaries_require_fresh_content_free_proofs(
    module, mutation, message
) -> None:
    payload = _attestation()
    mutation(payload["evidence"]["canaries"])
    with pytest.raises(module.ReleaseAAttestationError, match=message):
        _verify(module, payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows.pop("postgresql"), "invalid field set"),
        (
            lambda rows: rows.update(
                unexpected={
                    "result": "passed",
                    "before_sha256": _digest("unexpected-before"),
                    "before_at": _stamp(13),
                    "after_sha256": _digest("unexpected-after"),
                    "after_at": _stamp(12),
                    "comparison_sha256": _digest("unexpected-comparison"),
                    "completed_at": _stamp(11),
                }
            ),
            "invalid field set",
        ),
        (lambda rows: rows["qdrant"].update(result="failed"), "result"),
        (
            lambda rows: rows["minio_object_store"].update(before_sha256="tampered"),
            "before_sha256",
        ),
        (
            lambda rows: rows["faiss"].update(after_sha256="tampered"),
            "after_sha256",
        ),
        (
            lambda rows: rows["secure_deposit"].update(comparison_sha256="tampered"),
            "comparison_sha256",
        ),
        (
            lambda rows: rows["rabbitmq"].update(after_at=_stamp(14)),
            "after_at predates before_at",
        ),
        (
            lambda rows: rows["postgresql"].update(completed_at=_stamp(13)),
            "completed_at predates after_at",
        ),
    ],
)
def test_all_fixed_data_surfaces_require_ordered_before_after_comparison_proofs(
    module, mutation, message
) -> None:
    payload = _attestation()
    mutation(payload["evidence"]["data_integrity"])
    with pytest.raises(module.ReleaseAAttestationError, match=message):
        _verify(module, payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row.update(versioning="Suspended"), "versioning"),
        (
            lambda row: row.update(
                root_credential_fingerprint_sha256=row["application_credential_fingerprint_sha256"]
            ),
            "not separated",
        ),
        (lambda row: row["canary"].update(delete_denied=False), "delete_denied"),
        (lambda row: row["canary"].update(config_denied=False), "config_denied"),
        (lambda row: row.update(proof_sha256="not-a-digest"), "proof_sha256"),
    ],
)
def test_minio_versioning_separation_and_denial_canary_are_mandatory(
    module, mutation, message
) -> None:
    payload = _attestation()
    mutation(payload["evidence"]["minio"])
    with pytest.raises(module.ReleaseAAttestationError, match=message):
        _verify(module, payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda row: row.update(
                read_only_key_fingerprint_sha256=row["admin_key_fingerprint_sha256"]
            ),
            "not separated",
        ),
        (lambda row: row.update(read_only_write_denied=False), "write_denied"),
        (lambda row: row.update(inventory_sha256="1" * 40), "inventory_sha256"),
    ],
)
def test_qdrant_keys_write_denial_and_inventory_digest_are_mandatory(
    module, mutation, message
) -> None:
    payload = _attestation()
    mutation(payload["evidence"]["qdrant"])
    with pytest.raises(module.ReleaseAAttestationError, match=message):
        _verify(module, payload)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("maintenance_gate", "survived_reboot"), False, "survived_reboot"),
        (("backend", "listener"), "0.0.0.0:8000", "listener"),
        (("backend", "public_listener_count"), 1, "integer zero"),
        (("backend", "public_listener_count"), False, "integer zero"),
        (("restart_contract", "result"), "failed", "result"),
    ],
)
def test_reboot_gate_loopback_backend_and_restart_contract_are_mandatory(
    module, path, value, message
) -> None:
    payload = _attestation()
    payload["evidence"]["runtime"][path[0]][path[1]] = value
    with pytest.raises(module.ReleaseAAttestationError, match=message):
        _verify(module, payload)


@pytest.mark.parametrize("count", [1, -1, False])
def test_any_cross_workspace_binding_blocks_release_b(module, count) -> None:
    payload = _attestation()
    payload["evidence"]["tenant_audit"]["cross_workspace_binding_count"] = count
    with pytest.raises(module.ReleaseAAttestationError, match="integer zero"):
        _verify(module, payload)


@pytest.mark.parametrize(
    "field",
    ["authentication_result", "subsystem_result", "revocation_result", "ledger_result"],
)
def test_sftp_requires_a_positive_authenticated_subsystem_proof(module, field) -> None:
    payload = _attestation()
    payload["evidence"]["sftp"][field] = "waived"
    with pytest.raises(module.ReleaseAAttestationError, match=field):
        _verify(module, payload)


def test_sftp_requires_post_revocation_authentication_denial(module) -> None:
    payload = _attestation()
    payload["evidence"]["sftp"]["post_revocation_authentication_result"] = "passed"
    with pytest.raises(
        module.ReleaseAAttestationError,
        match="post_revocation_authentication_result",
    ):
        _verify(module, payload)


@pytest.mark.parametrize(
    "field",
    [
        "runtime_ready_receipt_sha256",
        "postgres_ledger_receipt_sha256",
        "credential_fingerprint_sha256",
    ],
)
def test_sftp_requires_runtime_and_credential_bindings(module, field) -> None:
    payload = _attestation()
    payload["evidence"]["sftp"][field] = "not-a-digest"
    with pytest.raises(module.ReleaseAAttestationError, match=field):
        _verify(module, payload)


def test_sftp_principal_must_match_proof_fingerprint_and_completion(module) -> None:
    payload = _attestation()
    payload["evidence"]["principals"]["sftp_canary"][
        "credential_fingerprint_sha256"
    ] = _digest("other-sftp-credential")
    with pytest.raises(module.ReleaseAAttestationError, match="fingerprint differs"):
        _verify(module, payload)

    payload = _attestation()
    payload["evidence"]["principals"]["sftp_canary"]["completed_at"] = _stamp(3)
    with pytest.raises(module.ReleaseAAttestationError, match="completion differs"):
        _verify(module, payload)


def test_sftp_runtime_ledger_and_final_chronology_is_ordered(module) -> None:
    payload = _attestation()
    payload["evidence"]["sftp"]["runtime_ready_at"] = _stamp(3)
    with pytest.raises(module.ReleaseAAttestationError, match="chronology"):
        _verify(module, payload)


def test_sftp_waiver_fields_are_rejected(module) -> None:
    payload = _attestation()
    payload["evidence"]["sftp"]["waiver"] = True
    with pytest.raises(module.ReleaseAAttestationError, match="invalid field set"):
        _verify(module, payload)


def test_sftp_image_revision_must_match_the_expected_sftp_sha(module) -> None:
    payload = _attestation()
    payload["evidence"]["sftp"]["image_revision"] = "c" * 40
    with pytest.raises(module.ReleaseAAttestationError, match="image_revision differs"):
        _verify(module, payload)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda principals: principals["browser_canary"].update(
                principal_kind="human_user"
            ),
            "service_account or automation_client",
        ),
        (
            lambda principals: principals["browser_canary"].update(non_personal=False),
            "non_personal",
        ),
        (
            lambda principals: principals["browser_canary"].update(
                least_privilege=False
            ),
            "least_privilege",
        ),
        (
            lambda principals: principals["browser_canary"].update(
                permission_probe_result="waived"
            ),
            "permission_probe_result",
        ),
        (
            lambda principals: principals["sftp_canary"].update(disposable=False),
            "disposable",
        ),
        (
            lambda principals: principals["sftp_canary"].update(
                credential_fingerprint_sha256=principals["browser_canary"][
                    "credential_fingerprint_sha256"
                ]
            ),
            "fingerprint differs",
        ),
    ],
)
def test_canary_principals_are_non_personal_least_privilege_and_distinct(
    module, mutation, message
) -> None:
    payload = _attestation()
    mutation(payload["evidence"]["principals"])
    with pytest.raises(module.ReleaseAAttestationError, match=message):
        _verify(module, payload)


def test_browser_and_proof_bound_sftp_credentials_must_be_distinct(module) -> None:
    payload = _attestation()
    browser_fingerprint = payload["evidence"]["principals"]["browser_canary"][
        "credential_fingerprint_sha256"
    ]
    payload["evidence"]["sftp"][
        "credential_fingerprint_sha256"
    ] = browser_fingerprint
    payload["evidence"]["principals"]["sftp_canary"][
        "credential_fingerprint_sha256"
    ] = browser_fingerprint
    with pytest.raises(module.ReleaseAAttestationError, match="must be distinct"):
        _verify(module, payload)


def test_release_and_sftp_sha_may_be_equal_for_initial_adoption(module) -> None:
    payload = _attestation()
    payload["sftp_release_sha"] = SHA
    payload["evidence"]["sftp"]["image_revision"] = SHA

    receipt = _verify(module, payload, expected_sftp_sha=SHA)

    assert receipt["release_a_sha"] == SHA
    assert receipt["sftp_release_sha"] == SHA


def test_file_loader_rejects_symlinks_hardlinks_open_modes_and_wrong_owner(
    module, tmp_path
) -> None:
    source = _write_private(tmp_path / "attestation.json", _attestation())
    symlink = tmp_path / "attestation-link.json"
    symlink.symlink_to(source)
    with pytest.raises(module.ReleaseAAttestationError, match="unsafe"):
        module.load_attestation_file(symlink)

    hardlink = tmp_path / "attestation-hardlink.json"
    os.link(source, hardlink)
    with pytest.raises(module.ReleaseAAttestationError, match="hard-linked"):
        module.load_attestation_file(source)
    hardlink.unlink()

    source.chmod(0o640)
    with pytest.raises(module.ReleaseAAttestationError, match="mode"):
        module.load_attestation_file(source)
    source.chmod(0o600)
    with pytest.raises(module.ReleaseAAttestationError, match="owner"):
        module.load_attestation_file(source, expected_uid=os.geteuid() + 1)


def test_file_loader_rejects_oversize_duplicate_fields_and_invalid_json(module, tmp_path) -> None:
    oversized = _write_private(tmp_path / "oversized.json", " " * (1024 * 1024 + 1))
    with pytest.raises(module.ReleaseAAttestationError, match="one MiB"):
        module.load_attestation_file(oversized)

    duplicate = _write_private(
        tmp_path / "duplicate.json", '{"schema_version":1,"schema_version":1}'
    )
    with pytest.raises(module.ReleaseAAttestationError, match="duplicate"):
        module.load_attestation_file(duplicate)

    invalid = _write_private(tmp_path / "invalid.json", "{not-json")
    with pytest.raises(module.ReleaseAAttestationError, match="not valid"):
        module.load_attestation_file(invalid)


def test_byte_digest_in_receipt_binds_the_exact_private_input(module, tmp_path) -> None:
    path = _write_private(tmp_path / "attestation.json", _attestation())
    payload, byte_digest = module.load_attestation_file(path)
    receipt = _verify(module, payload, attestation_sha256=byte_digest)

    assert receipt["attestation_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_verify_emits_only_the_compact_receipt(module, tmp_path) -> None:
    current = datetime.now(UTC).replace(microsecond=0)
    payload = _attestation(now=current)
    path = _write_private(tmp_path / "attestation.json", payload)
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "verify",
            "--attestation",
            str(path),
            "--expected-release-a-sha",
            SHA,
            "--expected-sftp-sha",
            SFTP_SHA,
            "--expected-hostname",
            HOSTNAME,
            "--max-age-hours",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    receipt = json.loads(result.stdout)
    assert receipt["result"] == "passed"
    assert receipt["release_a_sha"] == SHA
    assert receipt["sftp_release_sha"] == SFTP_SHA
    assert len(result.stdout.encode()) < 4096


def test_cli_failure_does_not_echo_operator_evidence(module, tmp_path) -> None:
    payload = _attestation(now=datetime.now(UTC).replace(microsecond=0))
    secret_marker = "forbidden-raw-backup-identifier"
    payload["evidence"]["off_vm_backups"][0]["backup_id_sha256"] = secret_marker
    path = _write_private(tmp_path / "attestation.json", payload)
    result = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "verify",
            "--attestation",
            str(path),
            "--expected-release-a-sha",
            SHA,
            "--expected-sftp-sha",
            SFTP_SHA,
            "--expected-hostname",
            HOSTNAME,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert secret_marker not in result.stderr


def test_mutating_any_digest_changes_or_invalidates_the_receipt(module) -> None:
    baseline = _verify(module, _attestation())
    payload = copy.deepcopy(_attestation())
    payload["evidence"]["tenant_audit"]["report_sha256"] = _digest("other-report")
    changed = _verify(module, payload)

    assert changed["evidence_sha256"] != baseline["evidence_sha256"]
    assert changed["attestation_sha256"] != baseline["attestation_sha256"]
