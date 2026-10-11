#!/usr/bin/env python3
"""Validate an old MinIO store before its backing volume is retired.

The helper is deliberately read-only.  It accepts only loopback MinIO
endpoints, issues only signed S3 ``GET`` requests, proves that every old
object version or delete marker is represented by the active store, and reads
a deterministic sample from both stores.  Its receipt contains keyed
pseudonyms instead of bucket names, object keys, version identifiers or
ETags, and is authenticated with a domain-separated HMAC.

Missing versions may be covered by an explicit, closed-schema justification
file.  Metadata or content mismatches can never be justified.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple
from xml.etree import ElementTree

SCHEMA_VERSION = 1
PROFILE = "agentium-minio-retirement-validation-v1"
RECEIPT_KIND = "agentium-minio-retirement-validation-receipt"
JUSTIFICATION_PROFILE = "agentium-minio-retirement-missing-justifications-v1"
INVENTORY_ALGORITHM = "s3-version-inventory-hmac-sha256-v1"
SAMPLE_ALGORITHM = "bucket-round-robin-hmac-order-v1"
SIGNATURE_ALGORITHM = "hmac-sha256-v1"
DEFAULT_SAMPLE_SIZE = 100
MAX_XML_BYTES = 32 * 1024 * 1024
MAX_SECRET_FILE_BYTES = 64 * 1024
MAX_INVENTORY_PAGES = 100_000
MAX_RECEIPT_EXAMPLES = 100
READ_CHUNK_SIZE = 1024 * 1024
MIN_KEY_BYTES = 32


class RetirementAttestationError(RuntimeError):
    """Raised when the retirement proof cannot be established safely."""


class InventoryEntry(NamedTuple):
    bucket: str
    key: str
    version_id: str
    size: int
    etag: str
    last_modified: str
    is_latest: bool
    delete_marker: bool


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RetirementAttestationError("attestation value is not canonical JSON") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise RetirementAttestationError(f"{label} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise RetirementAttestationError(f"{label} must be a SHA-256 digest") from exc
    return value


def _read_private_file(path: Path, *, label: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RetirementAttestationError(f"{label} file is unavailable") from exc
    try:
        row = os.fstat(descriptor)
        if (
            not stat.S_ISREG(row.st_mode)
            or row.st_uid != os.geteuid()
            or stat.S_IMODE(row.st_mode) & 0o077
            or row.st_size > MAX_SECRET_FILE_BYTES
        ):
            raise RetirementAttestationError(
                f"{label} file must be owned by the caller, regular and private"
            )
        payload = bytearray()
        while len(payload) <= MAX_SECRET_FILE_BYTES:
            chunk = os.read(
                descriptor,
                min(8192, MAX_SECRET_FILE_BYTES + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > MAX_SECRET_FILE_BYTES:
            raise RetirementAttestationError(f"{label} file exceeds its size bound")
        return bytes(payload)
    except OSError as exc:
        raise RetirementAttestationError(f"{label} file is unreadable") from exc
    finally:
        os.close(descriptor)


def _read_attestation_key(path: Path) -> bytes:
    key = _read_private_file(path, label="attestation key")
    if len(key) < MIN_KEY_BYTES:
        raise RetirementAttestationError(
            f"attestation key must contain at least {MIN_KEY_BYTES} bytes"
        )
    return key


def _dotenv_credentials(path: Path) -> tuple[str, str]:
    payload = _read_private_file(path, label="MinIO credential")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RetirementAttestationError("MinIO credential file is not UTF-8") from exc
    values: dict[str, str] = {}
    wanted = {"MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in wanted:
            continue
        if name in values:
            raise RetirementAttestationError("MinIO credential is duplicated")
        candidate = value.strip()
        if (
            len(candidate) >= 2
            and candidate[0] == candidate[-1]
            and candidate[0] in {"'", '"'}
        ):
            candidate = candidate[1:-1]
        values[name] = candidate
    access_key = values.get("MINIO_ROOT_USER", "")
    secret_key = values.get("MINIO_ROOT_PASSWORD", "")
    if not access_key or not secret_key:
        raise RetirementAttestationError("MinIO credentials are incomplete")
    return access_key, secret_key


def _endpoint(url: str) -> tuple[str, urllib.parse.SplitResult]:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RetirementAttestationError(
            "MinIO retirement endpoints must be loopback-only origins"
        )
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise RetirementAttestationError("MinIO endpoint port is invalid") from exc
    identity = f"{parsed.scheme}://loopback:{port}"
    return identity, parsed


def _derive(key: bytes, purpose: bytes) -> bytes:
    return hmac.new(key, b"agentium-minio-retirement\x00" + purpose, hashlib.sha256).digest()


def _pseudonym(key: bytes, kind: str, *parts: str) -> str:
    pseudonym_key = _derive(key, b"pseudonym-v1")
    encoded = bytearray(kind.encode("ascii"))
    for part in parts:
        raw = part.encode("utf-8", errors="surrogateescape")
        encoded.extend(b"\x00")
        encoded.extend(len(raw).to_bytes(8, "big"))
        encoded.extend(raw)
    return hmac.new(pseudonym_key, bytes(encoded), hashlib.sha256).hexdigest()


def _entry_identity(entry: InventoryEntry) -> tuple[str, str, str]:
    return entry.bucket, entry.key, entry.version_id


def _identity_pseudonyms(entry: InventoryEntry, key: bytes) -> dict[str, str]:
    return {
        "bucket_id_hmac": _pseudonym(key, "bucket", entry.bucket),
        "object_id_hmac": _pseudonym(key, "object", entry.bucket, entry.key),
        "version_id_hmac": _pseudonym(
            key, "version", entry.bucket, entry.key, entry.version_id
        ),
    }


def _pseudonym_identity_tuple(
    entry: InventoryEntry, key: bytes
) -> tuple[str, str, str]:
    row = _identity_pseudonyms(entry, key)
    return row["bucket_id_hmac"], row["object_id_hmac"], row["version_id_hmac"]


def _entry_manifest_row(entry: InventoryEntry, key: bytes) -> list[Any]:
    identity = _identity_pseudonyms(entry, key)
    return [
        identity["bucket_id_hmac"],
        identity["object_id_hmac"],
        identity["version_id_hmac"],
        entry.size,
        _pseudonym(key, "etag", entry.etag),
        _pseudonym(key, "last-modified", entry.last_modified),
        entry.is_latest,
        entry.delete_marker,
    ]


def _inventory_digest(entries: Sequence[InventoryEntry], key: bytes) -> str:
    rows = sorted(_entry_manifest_row(entry, key) for entry in entries)
    return _sha256(_canonical_json(rows))


def _signing_key(secret: bytes) -> bytes:
    return _derive(secret, b"receipt-signature-v1")


def sign_receipt(unsigned: Mapping[str, Any], key: bytes) -> dict[str, Any]:
    if "signature" in unsigned:
        raise RetirementAttestationError("unsigned receipt contains a signature")
    signature = hmac.new(_signing_key(key), _canonical_json(unsigned), hashlib.sha256)
    return {
        **unsigned,
        "signature": {
            "algorithm": SIGNATURE_ALGORITHM,
            "key_id_sha256": _sha256(key),
            "value": signature.hexdigest(),
        },
    }


def verify_receipt(receipt: Mapping[str, Any], key: bytes) -> None:
    signature = receipt.get("signature")
    if not isinstance(signature, dict) or set(signature) != {
        "algorithm",
        "key_id_sha256",
        "value",
    }:
        raise RetirementAttestationError("receipt signature is invalid")
    if (
        signature.get("algorithm") != SIGNATURE_ALGORITHM
        or signature.get("key_id_sha256") != _sha256(key)
    ):
        raise RetirementAttestationError("receipt signature authority differs")
    supplied = _require_digest(signature.get("value"), label="receipt signature")
    unsigned = dict(receipt)
    del unsigned["signature"]
    expected = hmac.new(
        _signing_key(key), _canonical_json(unsigned), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise RetirementAttestationError("receipt signature verification failed")


def _aws_signing_key(secret_key: str, date: str, region: str) -> bytes:
    date_key = hmac.new(
        f"AWS4{secret_key}".encode("utf-8"), date.encode("ascii"), hashlib.sha256
    ).digest()
    region_key = hmac.new(date_key, region.encode("ascii"), hashlib.sha256).digest()
    service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


class S3ReadOnlyClient:
    """Minimal SigV4 S3 client that has no mutating operation."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str):
        self.endpoint_id, self._parsed = _endpoint(endpoint)
        self._access_key = access_key
        self._secret_key = secret_key
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(
        self,
        *,
        bucket: str = "",
        key: str = "",
        query: Sequence[tuple[str, str]] = (),
    ) -> urllib.request.Request:
        if key and not bucket:
            raise RetirementAttestationError("S3 object request has no bucket")
        if "\x00" in bucket or "\x00" in key:
            raise RetirementAttestationError("S3 identifier contains NUL")
        path = "/"
        if bucket:
            path += urllib.parse.quote(bucket, safe="-_.~")
        if key:
            path += "/" + urllib.parse.quote(key, safe="/-_.~")
        canonical_query = urllib.parse.urlencode(
            sorted(query),
            doseq=True,
            quote_via=urllib.parse.quote,
            safe="-_.~",
        )
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")
        region = "us-east-1"
        payload_hash = hashlib.sha256(b"").hexdigest()
        host = self._parsed.netloc
        canonical_headers = (
            f"host:{host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            [
                "GET",
                path,
                canonical_query,
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )
        scope = f"{date}/{region}/s3/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(
            _aws_signing_key(self._secret_key, date, region),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        url = urllib.parse.urlunsplit(
            (
                self._parsed.scheme,
                self._parsed.netloc,
                path,
                canonical_query,
                "",
            )
        )
        return urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/xml",
                "Authorization": (
                    "AWS4-HMAC-SHA256 "
                    f"Credential={self._access_key}/{scope}, "
                    f"SignedHeaders={signed_headers}, Signature={signature}"
                ),
                "User-Agent": "agentium-minio-retirement-attestor/1",
                "x-amz-content-sha256": payload_hash,
                "x-amz-date": amz_date,
            },
        )

    def _open(self, request: urllib.request.Request, *, timeout: int):
        try:
            return self._opener.open(request, timeout=timeout)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RetirementAttestationError("local MinIO read failed") from exc

    def _xml(
        self,
        *,
        bucket: str = "",
        query: Sequence[tuple[str, str]] = (),
    ) -> ElementTree.Element:
        request = self._request(bucket=bucket, query=query)
        with self._open(request, timeout=30) as response:
            if response.status != 200:
                raise RetirementAttestationError(
                    f"local MinIO returned HTTP {response.status}"
                )
            payload = response.read(MAX_XML_BYTES + 1)
        if len(payload) > MAX_XML_BYTES:
            raise RetirementAttestationError("MinIO inventory page exceeds its bound")
        try:
            return ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise RetirementAttestationError("MinIO inventory XML is invalid") from exc

    @staticmethod
    def _text(element: ElementTree.Element, name: str) -> str:
        for child in element:
            if child.tag.rsplit("}", 1)[-1] == name:
                return child.text or ""
        return ""

    def list_buckets(self) -> list[str]:
        root = self._xml()
        buckets: list[str] = []
        for child in root.iter():
            if child.tag.rsplit("}", 1)[-1] != "Bucket":
                continue
            name = self._text(child, "Name")
            if not name or "\x00" in name:
                raise RetirementAttestationError("MinIO returned an invalid bucket")
            buckets.append(name)
        if len(buckets) != len(set(buckets)):
            raise RetirementAttestationError("MinIO returned duplicate buckets")
        return sorted(buckets)

    def _bucket_inventory(self, bucket: str) -> list[InventoryEntry]:
        rows: list[InventoryEntry] = []
        key_marker = ""
        version_marker = ""
        seen_markers: set[tuple[str, str]] = set()
        for _page in range(MAX_INVENTORY_PAGES):
            query = [("encoding-type", "url"), ("max-keys", "1000"), ("versions", "")]
            if key_marker:
                query.append(("key-marker", key_marker))
            if version_marker:
                query.append(("version-id-marker", version_marker))
            root = self._xml(bucket=bucket, query=query)
            for element in root:
                kind = element.tag.rsplit("}", 1)[-1]
                if kind not in {"Version", "DeleteMarker"}:
                    continue
                key = urllib.parse.unquote(self._text(element, "Key"))
                version_id = self._text(element, "VersionId")
                try:
                    size = int(self._text(element, "Size") or 0)
                except ValueError as exc:
                    raise RetirementAttestationError(
                        "MinIO returned an invalid object size"
                    ) from exc
                last_modified = self._text(element, "LastModified")
                etag = self._text(element, "ETag").strip('"')
                if (
                    not key
                    or not version_id
                    or size < 0
                    or not last_modified
                    or (kind == "Version" and not etag)
                    or (kind == "DeleteMarker" and size != 0)
                ):
                    raise RetirementAttestationError(
                        "MinIO returned invalid version metadata"
                    )
                rows.append(
                    InventoryEntry(
                        bucket=bucket,
                        key=key,
                        version_id=version_id,
                        size=size,
                        etag=etag,
                        last_modified=last_modified,
                        is_latest=self._text(element, "IsLatest").lower() == "true",
                        delete_marker=kind == "DeleteMarker",
                    )
                )
            if self._text(root, "IsTruncated").lower() != "true":
                return rows
            next_markers = (
                urllib.parse.unquote(self._text(root, "NextKeyMarker")),
                self._text(root, "NextVersionIdMarker"),
            )
            if not next_markers[0] or next_markers in seen_markers:
                raise RetirementAttestationError(
                    "MinIO inventory pagination did not advance"
                )
            seen_markers.add(next_markers)
            key_marker, version_marker = next_markers
        raise RetirementAttestationError("MinIO inventory exceeded its page bound")

    def inventory(self) -> list[InventoryEntry]:
        rows = [
            entry
            for bucket in self.list_buckets()
            for entry in self._bucket_inventory(bucket)
        ]
        identities = [_entry_identity(entry) for entry in rows]
        if len(identities) != len(set(identities)):
            raise RetirementAttestationError("MinIO inventory has duplicate versions")
        return sorted(rows, key=_entry_identity)

    def read_version(self, entry: InventoryEntry) -> tuple[int, str]:
        if entry.delete_marker:
            raise RetirementAttestationError("delete markers are not readable objects")
        request = self._request(
            bucket=entry.bucket,
            key=entry.key,
            query=[("versionId", entry.version_id)],
        )
        digest = hashlib.sha256()
        count = 0
        with self._open(request, timeout=120) as response:
            if response.status != 200:
                raise RetirementAttestationError(
                    f"local MinIO returned HTTP {response.status}"
                )
            while True:
                chunk = response.read(READ_CHUNK_SIZE)
                if not chunk:
                    break
                count += len(chunk)
                digest.update(chunk)
        if count != entry.size:
            raise RetirementAttestationError("MinIO version size changed during read")
        return count, digest.hexdigest()


def _validate_inventory(entries: Sequence[InventoryEntry], *, label: str) -> None:
    identities: list[tuple[str, str, str]] = []
    for entry in entries:
        if (
            not isinstance(entry, InventoryEntry)
            or not entry.bucket
            or not entry.key
            or not entry.version_id
            or not isinstance(entry.size, int)
            or isinstance(entry.size, bool)
            or entry.size < 0
            or not entry.last_modified
            or (not entry.delete_marker and not entry.etag)
            or not isinstance(entry.is_latest, bool)
            or not isinstance(entry.delete_marker, bool)
            or (entry.delete_marker and entry.size != 0)
        ):
            raise RetirementAttestationError(f"{label} inventory entry is invalid")
        identities.append(_entry_identity(entry))
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise RetirementAttestationError(
            f"{label} inventory identities are not unique and sorted"
        )


def _immutable_metadata(entry: InventoryEntry) -> tuple[Any, ...]:
    return entry.size, entry.etag, entry.last_modified, entry.delete_marker


def _missing_example(entry: InventoryEntry, key: bytes) -> dict[str, Any]:
    return {**_identity_pseudonyms(entry, key), "delete_marker": entry.delete_marker}


def _mismatch_example(
    before: InventoryEntry, after: InventoryEntry, key: bytes
) -> dict[str, Any]:
    fields = [
        field
        for field, left, right in zip(
            ("size", "etag", "last_modified", "delete_marker"),
            _immutable_metadata(before),
            _immutable_metadata(after),
            strict=True,
        )
        if left != right
    ]
    return {**_identity_pseudonyms(before, key), "differing_fields": fields}


def _load_justifications(
    value: Mapping[str, Any] | None, key: bytes
) -> tuple[dict[tuple[str, str, str], Mapping[str, str]], str]:
    if value is None:
        return {}, _sha256(_canonical_json([]))
    if set(value) != {"schema_version", "profile", "entries"} or (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("profile") != JUSTIFICATION_PROFILE
        or not isinstance(value.get("entries"), list)
    ):
        raise RetirementAttestationError("missing-version justification schema is invalid")
    normalized: list[dict[str, str]] = []
    result: dict[tuple[str, str, str], Mapping[str, str]] = {}
    for raw in value["entries"]:
        if not isinstance(raw, dict) or set(raw) != {
            "bucket_id_hmac",
            "object_id_hmac",
            "version_id_hmac",
            "reason",
            "approved_by",
            "reference",
        }:
            raise RetirementAttestationError(
                "missing-version justification entry is invalid"
            )
        identity = (
            _require_digest(raw["bucket_id_hmac"], label="justified bucket"),
            _require_digest(raw["object_id_hmac"], label="justified object"),
            _require_digest(raw["version_id_hmac"], label="justified version"),
        )
        for field, limit in (("reason", 500), ("approved_by", 200), ("reference", 200)):
            field_value = raw[field]
            if (
                not isinstance(field_value, str)
                or not field_value.strip()
                or len(field_value) > limit
                or "\x00" in field_value
            ):
                raise RetirementAttestationError(
                    f"missing-version justification {field} is invalid"
                )
        if identity in result:
            raise RetirementAttestationError("missing-version justification is duplicated")
        result[identity] = raw
        normalized.append(
            {
                "bucket_id_hmac": identity[0],
                "object_id_hmac": identity[1],
                "version_id_hmac": identity[2],
                "reason_hmac": _pseudonym(key, "justification-reason", raw["reason"]),
                "approver_hmac": _pseudonym(
                    key, "justification-approver", raw["approved_by"]
                ),
                "reference_hmac": _pseudonym(
                    key, "justification-reference", raw["reference"]
                ),
            }
        )
    return result, _sha256(_canonical_json(sorted(normalized, key=_canonical_json)))


def _select_sample(
    entries: Sequence[InventoryEntry], *, key: bytes, sample_size: int
) -> list[InventoryEntry]:
    if sample_size <= 0:
        raise RetirementAttestationError("sample size must be positive")
    by_bucket: dict[str, list[InventoryEntry]] = defaultdict(list)
    for entry in entries:
        if not entry.delete_marker:
            by_bucket[entry.bucket].append(entry)
    if not by_bucket:
        return []
    target = min(sample_size, sum(len(rows) for rows in by_bucket.values()))
    if len(by_bucket) > target:
        raise RetirementAttestationError(
            "sample size cannot cover every bucket containing readable versions"
        )
    bucket_order = sorted(
        by_bucket, key=lambda bucket: _pseudonym(key, "sample-bucket", bucket)
    )
    for bucket, rows in by_bucket.items():
        rows.sort(
            key=lambda entry: _pseudonym(
                key,
                "sample-version",
                entry.bucket,
                entry.key,
                entry.version_id,
            )
        )
    selected: list[InventoryEntry] = []
    offset = 0
    while len(selected) < target:
        advanced = False
        for bucket in bucket_order:
            rows = by_bucket[bucket]
            if offset < len(rows) and len(selected) < target:
                selected.append(rows[offset])
                advanced = True
        if not advanced:  # pragma: no cover - defensive; target is derived above.
            raise RetirementAttestationError("sample selection did not advance")
        offset += 1
    return selected


def _bucket_summaries(entries: Sequence[InventoryEntry], key: bytes) -> list[dict[str, Any]]:
    grouped: dict[str, list[InventoryEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.bucket].append(entry)
    result = []
    for bucket, rows in grouped.items():
        result.append(
            {
                "bucket_id_hmac": _pseudonym(key, "bucket", bucket),
                "versions": len(rows),
                "readable_versions": sum(not row.delete_marker for row in rows),
                "delete_markers": sum(row.delete_marker for row in rows),
                "bytes": sum(row.size for row in rows if not row.delete_marker),
            }
        )
    return sorted(result, key=lambda row: row["bucket_id_hmac"])


def validate_retirement(
    *,
    old_client: Any,
    active_client: Any,
    key: bytes,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    justifications: Mapping[str, Any] | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Return a signed, pseudonymous old-store retirement receipt."""

    if len(key) < MIN_KEY_BYTES:
        raise RetirementAttestationError(
            f"attestation key must contain at least {MIN_KEY_BYTES} bytes"
        )
    old_entries = list(old_client.inventory())
    active_entries = list(active_client.inventory())
    _validate_inventory(old_entries, label="old")
    _validate_inventory(active_entries, label="active")
    if not old_entries:
        raise RetirementAttestationError("old MinIO inventory is empty")

    active_by_identity = {_entry_identity(entry): entry for entry in active_entries}
    missing: list[InventoryEntry] = []
    mismatches: list[tuple[InventoryEntry, InventoryEntry]] = []
    preserved: list[InventoryEntry] = []
    for old in old_entries:
        active = active_by_identity.get(_entry_identity(old))
        if active is None:
            missing.append(old)
        elif _immutable_metadata(old) != _immutable_metadata(active):
            mismatches.append((old, active))
        else:
            preserved.append(old)

    justification_rows, justification_digest = _load_justifications(
        justifications, key
    )
    missing_identities = {
        _pseudonym_identity_tuple(entry, key): entry for entry in missing
    }
    unknown_justifications = sorted(set(justification_rows) - set(missing_identities))
    unjustified = [
        entry
        for identity, entry in missing_identities.items()
        if identity not in justification_rows
    ]
    justified = len(missing) - len(unjustified)

    sample = _select_sample(preserved, key=key, sample_size=sample_size)
    read_rows: list[dict[str, Any]] = []
    content_mismatches: list[dict[str, str]] = []
    old_read_bytes = 0
    active_read_bytes = 0
    for old in sample:
        active = active_by_identity[_entry_identity(old)]
        old_size, old_digest = old_client.read_version(old)
        active_size, active_digest = active_client.read_version(active)
        old_read_bytes += old_size
        active_read_bytes += active_size
        identity = _identity_pseudonyms(old, key)
        matches = old_size == active_size and hmac.compare_digest(
            old_digest, active_digest
        )
        if not matches:
            content_mismatches.append(identity)
        read_rows.append(
            {
                **identity,
                "size": old_size,
                "content_hmac": _pseudonym(key, "content-digest", old_digest),
                "matches_active": matches,
            }
        )

    old_readable_buckets = {entry.bucket for entry in old_entries if not entry.delete_marker}
    preserved_readable_buckets = {
        entry.bucket for entry in preserved if not entry.delete_marker
    }
    sampled_buckets = {entry.bucket for entry in sample}
    target_reads = min(
        sample_size, sum(not entry.delete_marker for entry in preserved)
    )
    checks = [
        {
            "name": "old_inventory_nonempty",
            "passed": bool(old_entries),
            "expected": ">0",
            "actual": len(old_entries),
        },
        {
            "name": "no_unjustified_missing_versions",
            "passed": not unjustified,
            "expected": 0,
            "actual": len(unjustified),
        },
        {
            "name": "no_stale_or_unknown_justifications",
            "passed": not unknown_justifications,
            "expected": 0,
            "actual": len(unknown_justifications),
        },
        {
            "name": "immutable_metadata_preserved",
            "passed": not mismatches,
            "expected": 0,
            "actual": len(mismatches),
        },
        {
            "name": "readable_old_buckets_have_preserved_versions",
            "passed": old_readable_buckets == preserved_readable_buckets,
            "expected": len(old_readable_buckets),
            "actual": len(preserved_readable_buckets),
        },
        {
            "name": "deterministic_read_count",
            "passed": len(sample) == target_reads,
            "expected": target_reads,
            "actual": len(sample),
        },
        {
            "name": "all_readable_buckets_sampled",
            "passed": sampled_buckets == preserved_readable_buckets,
            "expected": len(preserved_readable_buckets),
            "actual": len(sampled_buckets),
        },
        {
            "name": "sample_content_matches",
            "passed": not content_mismatches,
            "expected": 0,
            "actual": len(content_mismatches),
        },
    ]
    failed_checks = [row["name"] for row in checks if not row["passed"]]
    missing_sorted = sorted(missing, key=lambda entry: _pseudonym_identity_tuple(entry, key))
    mismatches_sorted = sorted(
        mismatches, key=lambda pair: _pseudonym_identity_tuple(pair[0], key)
    )
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "kind": RECEIPT_KIND,
        "profile": PROFILE,
        "result": "passed" if not failed_checks else "failed",
        "captured_at": captured_at or _utc_now(),
        "inventory": {
            "algorithm": INVENTORY_ALGORITHM,
            "old": {
                "buckets": len({entry.bucket for entry in old_entries}),
                "versions": len(old_entries),
                "readable_versions": sum(
                    not entry.delete_marker for entry in old_entries
                ),
                "delete_markers": sum(entry.delete_marker for entry in old_entries),
                "bytes": sum(
                    entry.size for entry in old_entries if not entry.delete_marker
                ),
                "inventory_sha256": _inventory_digest(old_entries, key),
                "bucket_summaries": _bucket_summaries(old_entries, key),
            },
            "active": {
                "buckets": len({entry.bucket for entry in active_entries}),
                "versions": len(active_entries),
                "readable_versions": sum(
                    not entry.delete_marker for entry in active_entries
                ),
                "delete_markers": sum(
                    entry.delete_marker for entry in active_entries
                ),
                "bytes": sum(
                    entry.size for entry in active_entries if not entry.delete_marker
                ),
                "inventory_sha256": _inventory_digest(active_entries, key),
                "bucket_summaries": _bucket_summaries(active_entries, key),
            },
        },
        "comparison": {
            "preserved_versions": len(preserved),
            "missing_versions": len(missing),
            "justified_missing_versions": justified,
            "unjustified_missing_versions": len(unjustified),
            "metadata_mismatches": len(mismatches),
            "missing_manifest_sha256": _sha256(
                _canonical_json(
                    sorted(
                        (_missing_example(entry, key) for entry in missing),
                        key=_canonical_json,
                    )
                )
            ),
            "missing_examples": [
                _missing_example(entry, key)
                for entry in missing_sorted[:MAX_RECEIPT_EXAMPLES]
            ],
            "missing_examples_truncated": len(missing) > MAX_RECEIPT_EXAMPLES,
            "metadata_mismatch_examples": [
                _mismatch_example(before, after, key)
                for before, after in mismatches_sorted[:MAX_RECEIPT_EXAMPLES]
            ],
            "metadata_mismatch_examples_truncated": (
                len(mismatches) > MAX_RECEIPT_EXAMPLES
            ),
        },
        "justifications": {
            "profile": JUSTIFICATION_PROFILE,
            "provided": len(justification_rows),
            "applied": justified,
            "unknown": len(unknown_justifications),
            "manifest_sha256": justification_digest,
        },
        "reads": {
            "algorithm": SAMPLE_ALGORITHM,
            "requested": sample_size,
            "eligible_preserved_versions": sum(
                not entry.delete_marker for entry in preserved
            ),
            "selected": len(sample),
            "old_bytes": old_read_bytes,
            "active_bytes": active_read_bytes,
            "sampled_bucket_ids_hmac": sorted(
                _pseudonym(key, "bucket", bucket) for bucket in sampled_buckets
            ),
            "entries": sorted(read_rows, key=_canonical_json),
            "manifest_sha256": _sha256(
                _canonical_json(sorted(read_rows, key=_canonical_json))
            ),
            "content_mismatches": len(content_mismatches),
        },
        "checks": checks,
        "failed_checks": failed_checks,
    }
    return sign_receipt(unsigned, key)


def _load_json(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetirementAttestationError(f"{label} JSON is unavailable or invalid") from exc
    if not isinstance(payload, dict):
        raise RetirementAttestationError(f"{label} JSON must be an object")
    return payload


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    compare = subparsers.add_parser("compare-live")
    compare.add_argument("--old-url", required=True)
    compare.add_argument("--old-env", type=Path, required=True)
    compare.add_argument("--active-url", required=True)
    compare.add_argument("--active-env", type=Path, required=True)
    compare.add_argument("--attestation-key", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--justifications", type=Path)
    compare.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)

    verify = subparsers.add_parser("verify-receipt")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--attestation-key", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        key = _read_attestation_key(args.attestation_key)
        if args.command == "compare-live":
            old_identity, _ = _endpoint(args.old_url)
            active_identity, _ = _endpoint(args.active_url)
            if old_identity == active_identity:
                raise RetirementAttestationError(
                    "old and active MinIO endpoints resolve to the same loopback origin"
                )
            old_access, old_secret = _dotenv_credentials(args.old_env)
            active_access, active_secret = _dotenv_credentials(args.active_env)
            justification_payload = (
                _load_json(args.justifications, label="justification")
                if args.justifications
                else None
            )
            receipt = validate_retirement(
                old_client=S3ReadOnlyClient(args.old_url, old_access, old_secret),
                active_client=S3ReadOnlyClient(
                    args.active_url, active_access, active_secret
                ),
                key=key,
                sample_size=args.sample_size,
                justifications=justification_payload,
            )
            _write_atomic(args.output, receipt)
            return 0 if receipt["result"] == "passed" else 1
        if args.command == "verify-receipt":
            verify_receipt(_load_json(args.receipt, label="receipt"), key)
            print("OK  MinIO retirement receipt signature verified")
            return 0
        raise RetirementAttestationError("unsupported command")
    except RetirementAttestationError as exc:
        print(f"XX  {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
