from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[4]
HELPER = ROOT / "scripts" / "agentium_minio_retirement_attestation.py"
KEY = b"retirement-attestation-test-key-32-bytes-minimum"
CAPTURED_AT = "2026-08-06T12:00:00Z"


def _module():
    name = "agentium_minio_retirement_attestation_unit"
    spec = importlib.util.spec_from_file_location(name, HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _entry(
    module: Any,
    *,
    bucket: str,
    key: str,
    version: str,
    body: bytes = b"payload",
    etag: str = "etag-value",
    latest: bool = True,
    delete_marker: bool = False,
):
    return module.InventoryEntry(
        bucket=bucket,
        key=key,
        version_id=version,
        size=0 if delete_marker else len(body),
        etag="" if delete_marker else etag,
        last_modified="2026-07-20T09:37:06.000Z",
        is_latest=latest,
        delete_marker=delete_marker,
    )


class _FakeClient:
    def __init__(self, entries: list[Any], bodies: dict[tuple[str, str, str], bytes]):
        self.entries = sorted(entries, key=lambda entry: tuple(entry[:3]))
        self.bodies = bodies
        self.reads: list[tuple[str, str, str]] = []

    def inventory(self) -> list[Any]:
        return list(self.entries)

    def read_version(self, entry: Any) -> tuple[int, str]:
        identity = tuple(entry[:3])
        self.reads.append(identity)
        body = self.bodies[identity]
        return len(body), hashlib.sha256(body).hexdigest()


def _client(entries: list[Any], bodies: dict[tuple[str, str, str], bytes]):
    return _FakeClient(entries, bodies)


def _identity(entry: Any) -> tuple[str, str, str]:
    return entry.bucket, entry.key, entry.version_id


def test_passes_with_additions_and_reads_every_version_when_under_100() -> None:
    module = _module()
    old_rows = [
        _entry(
            module,
            bucket="bucket-customer-alpha",
            key="private/contract-one.pdf",
            version="opaque-version-one",
            body=b"first-body",
            etag="private-etag-one",
        ),
        _entry(
            module,
            bucket="bucket-customer-alpha",
            key="private/contract-two.pdf",
            version="opaque-version-two",
            body=b"second-body",
            etag="private-etag-two",
            latest=False,
        ),
        _entry(
            module,
            bucket="bucket-customer-beta",
            key="archive/drawing.png",
            version="opaque-version-three",
            body=b"third-body",
            etag="private-etag-three",
        ),
        _entry(
            module,
            bucket="bucket-customer-beta",
            key="archive/removed.txt",
            version="opaque-delete-version",
            delete_marker=True,
        ),
    ]
    bodies = {
        _identity(row): body
        for row, body in zip(
            old_rows[:3],
            (b"first-body", b"second-body", b"third-body"),
            strict=True,
        )
    }
    active_rows = [
        row._replace(is_latest=False) if row.version_id == "opaque-version-one" else row
        for row in old_rows
    ]
    addition = _entry(
        module,
        bucket="bucket-customer-alpha",
        key="private/new-after-migration.pdf",
        version="active-only-version",
        body=b"new-body",
        etag="active-only-etag",
    )
    active_rows.append(addition)
    active_bodies = {**bodies, _identity(addition): b"new-body"}
    old_client = _client(old_rows, bodies)
    active_client = _client(active_rows, active_bodies)

    receipt = module.validate_retirement(
        old_client=old_client,
        active_client=active_client,
        key=KEY,
        captured_at=CAPTURED_AT,
    )

    assert receipt["result"] == "passed"
    assert receipt["comparison"] == {
        "preserved_versions": 4,
        "missing_versions": 0,
        "justified_missing_versions": 0,
        "unjustified_missing_versions": 0,
        "metadata_mismatches": 0,
        "missing_manifest_sha256": hashlib.sha256(b"[]").hexdigest(),
        "missing_examples": [],
        "missing_examples_truncated": False,
        "metadata_mismatch_examples": [],
        "metadata_mismatch_examples_truncated": False,
    }
    assert receipt["reads"]["selected"] == 3
    assert len(receipt["reads"]["sampled_bucket_ids_hmac"]) == 2
    assert len(old_client.reads) == len(active_client.reads) == 3
    assert set(old_client.reads) == set(bodies)
    module.verify_receipt(receipt, KEY)

    serialized = json.dumps(receipt)
    for private_value in (
        "bucket-customer-alpha",
        "bucket-customer-beta",
        "private/contract-one.pdf",
        "opaque-version-one",
        "private-etag-one",
        "first-body",
        "new-after-migration",
    ):
        assert private_value not in serialized


def test_selects_exactly_100_deterministically_and_spreads_across_buckets() -> None:
    module = _module()
    rows = []
    bodies: dict[tuple[str, str, str], bytes] = {}
    for index in range(135):
        body = f"object-content-{index:03d}".encode()
        row = _entry(
            module,
            bucket=f"secret-bucket-{index % 5}",
            key=f"object/{index:03d}",
            version=f"version-{index:03d}",
            body=body,
            etag=f"etag-{index:03d}",
        )
        rows.append(row)
        bodies[_identity(row)] = body

    first = module.validate_retirement(
        old_client=_client(rows, bodies),
        active_client=_client(rows, bodies),
        key=KEY,
        captured_at=CAPTURED_AT,
    )
    second = module.validate_retirement(
        old_client=_client(list(reversed(rows)), bodies),
        active_client=_client(list(reversed(rows)), bodies),
        key=KEY,
        captured_at=CAPTURED_AT,
    )

    assert first["result"] == "passed"
    assert first["reads"]["selected"] == 100
    assert len(first["reads"]["sampled_bucket_ids_hmac"]) == 5
    assert first["reads"] == second["reads"]


def test_unjustified_missing_version_fails_with_only_pseudonymous_example() -> None:
    module = _module()
    present = _entry(
        module,
        bucket="sensitive-bucket",
        key="present.pdf",
        version="present-version",
        body=b"present",
    )
    missing = _entry(
        module,
        bucket="sensitive-bucket",
        key="missing-customer-file.pdf",
        version="missing-private-version",
        body=b"missing",
    )
    old_bodies = {_identity(present): b"present", _identity(missing): b"missing"}

    receipt = module.validate_retirement(
        old_client=_client([present, missing], old_bodies),
        active_client=_client([present], {_identity(present): b"present"}),
        key=KEY,
        captured_at=CAPTURED_AT,
    )

    assert receipt["result"] == "failed"
    assert receipt["comparison"]["missing_versions"] == 1
    assert receipt["comparison"]["unjustified_missing_versions"] == 1
    assert len(receipt["comparison"]["missing_examples"]) == 1
    assert "no_unjustified_missing_versions" in receipt["failed_checks"]
    serialized = json.dumps(receipt)
    assert "missing-customer-file.pdf" not in serialized
    assert "missing-private-version" not in serialized
    module.verify_receipt(receipt, KEY)


def test_exact_missing_justification_is_bound_but_not_disclosed() -> None:
    module = _module()
    present = _entry(
        module,
        bucket="sensitive-bucket",
        key="present.pdf",
        version="present-version",
        body=b"present",
    )
    missing = _entry(
        module,
        bucket="sensitive-bucket",
        key="approved-legacy-omission.pdf",
        version="approved-missing-version",
        body=b"missing",
    )
    identity = module._identity_pseudonyms(missing, KEY)
    justifications = {
        "schema_version": 1,
        "profile": module.JUSTIFICATION_PROFILE,
        "entries": [
            {
                **identity,
                "reason": "Approved duplicate of the authoritative active object",
                "approved_by": "named-production-owner",
                "reference": "CHANGE-PRIVATE-42",
            }
        ],
    }

    receipt = module.validate_retirement(
        old_client=_client(
            [present, missing],
            {_identity(present): b"present", _identity(missing): b"missing"},
        ),
        active_client=_client([present], {_identity(present): b"present"}),
        key=KEY,
        captured_at=CAPTURED_AT,
        justifications=justifications,
    )

    assert receipt["result"] == "passed"
    assert receipt["comparison"]["justified_missing_versions"] == 1
    assert receipt["justifications"]["provided"] == 1
    assert receipt["justifications"]["applied"] == 1
    serialized = json.dumps(receipt)
    assert "Approved duplicate" not in serialized
    assert "named-production-owner" not in serialized
    assert "CHANGE-PRIVATE-42" not in serialized
    module.verify_receipt(receipt, KEY)


def test_metadata_mismatch_cannot_be_justified() -> None:
    module = _module()
    old = _entry(
        module,
        bucket="bucket",
        key="object",
        version="version",
        body=b"old",
        etag="old-etag",
    )
    active = old._replace(etag="different-etag")

    receipt = module.validate_retirement(
        old_client=_client([old], {_identity(old): b"old"}),
        active_client=_client([active], {_identity(active): b"old"}),
        key=KEY,
        captured_at=CAPTURED_AT,
    )

    assert receipt["result"] == "failed"
    assert receipt["comparison"]["metadata_mismatches"] == 1
    assert "immutable_metadata_preserved" in receipt["failed_checks"]
    assert receipt["reads"]["selected"] == 0


def test_sample_content_mismatch_fails_even_when_inventory_matches() -> None:
    module = _module()
    row = _entry(
        module,
        bucket="bucket",
        key="object",
        version="version",
        body=b"123456",
    )

    receipt = module.validate_retirement(
        old_client=_client([row], {_identity(row): b"123456"}),
        active_client=_client([row], {_identity(row): b"abcdef"}),
        key=KEY,
        captured_at=CAPTURED_AT,
    )

    assert receipt["result"] == "failed"
    assert receipt["reads"]["content_mismatches"] == 1
    assert "sample_content_matches" in receipt["failed_checks"]


def test_signature_verification_rejects_receipt_tampering() -> None:
    module = _module()
    row = _entry(
        module,
        bucket="bucket",
        key="object",
        version="version",
        body=b"body",
    )
    receipt = module.validate_retirement(
        old_client=_client([row], {_identity(row): b"body"}),
        active_client=_client([row], {_identity(row): b"body"}),
        key=KEY,
        captured_at=CAPTURED_AT,
    )
    receipt["reads"]["selected"] = 0

    with pytest.raises(module.RetirementAttestationError, match="verification failed"):
        module.verify_receipt(receipt, KEY)


def test_rejects_empty_old_inventory_and_insufficient_bucket_sample() -> None:
    module = _module()
    with pytest.raises(module.RetirementAttestationError, match="inventory is empty"):
        module.validate_retirement(
            old_client=_client([], {}),
            active_client=_client([], {}),
            key=KEY,
            captured_at=CAPTURED_AT,
        )

    rows = [
        _entry(
            module,
            bucket=f"bucket-{index}",
            key="object",
            version="version",
            body=b"x",
        )
        for index in range(3)
    ]
    bodies = {_identity(row): b"x" for row in rows}
    with pytest.raises(module.RetirementAttestationError, match="cannot cover every bucket"):
        module.validate_retirement(
            old_client=_client(rows, bodies),
            active_client=_client(rows, bodies),
            key=KEY,
            sample_size=2,
            captured_at=CAPTURED_AT,
        )


def test_endpoints_are_loopback_only_and_requests_are_get_only() -> None:
    module = _module()
    with pytest.raises(module.RetirementAttestationError, match="loopback-only"):
        module._endpoint("https://minio.production.example")
    with pytest.raises(module.RetirementAttestationError, match="loopback-only"):
        module._endpoint("http://127.0.0.1:9000/tenant")

    client = module.S3ReadOnlyClient(
        "http://127.0.0.1:19000", "access-key", "secret-key"
    )
    request = client._request(
        bucket="private bucket",
        key="folder/name with spaces.pdf",
        query=[("versionId", "opaque+/version=")],
    )
    assert request.get_method() == "GET"
    assert request.data is None
    assert request.full_url.startswith(
        "http://127.0.0.1:19000/private%20bucket/folder/name%20with%20spaces.pdf?"
    )
    assert "versionId=opaque%2B%2Fversion%3D" in request.full_url
    assert "secret-key" not in request.full_url
    assert request.get_header("Authorization").startswith("AWS4-HMAC-SHA256 ")


def test_secret_files_must_be_private_and_key_has_a_minimum_size(
    tmp_path: Path,
) -> None:
    module = _module()
    key_file = tmp_path / "attestation.key"
    key_file.write_bytes(KEY)
    key_file.chmod(0o600)
    assert module._read_attestation_key(key_file) == KEY

    key_file.chmod(0o644)
    with pytest.raises(module.RetirementAttestationError, match="regular and private"):
        module._read_attestation_key(key_file)

    key_file.chmod(0o600)
    key_file.write_bytes(b"too-short")
    with pytest.raises(module.RetirementAttestationError, match="at least 32 bytes"):
        module._read_attestation_key(key_file)
