#!/usr/bin/env python3
"""Capture and compare privacy-preserving Agentium storage invariants.

The deployment orchestrator uses this helper before and after a quiesced
rollout. It records hashed identifiers and aggregate statistics for the Secure
Deposit, local ObjectStore, MinIO and Qdrant. No secret or business object name
is written to the resulting artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat as stat_module
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

DEFAULT_DATA_SOURCE = "/dev/sdb"
DEFAULT_SECURE_DEPOSIT_SOURCE = "/dev/sdc"
DEFAULT_MINIO_URL = "http://127.0.0.1:9000"
DEFAULT_MINIO_BUCKET = "agentium-artifacts"
READ_CHUNK_SIZE = 1024 * 1024
MAX_HTTP_RESPONSE_BYTES = 16 * 1024 * 1024
QDRANT_SCROLL_PAGE_SIZE = 256
MAX_QDRANT_SCROLL_PAGES = 1_000_000
QDRANT_POINT_MANIFEST_ALGORITHM = "qdrant-scroll-canonical-json-sha256-v1"
QDRANT_POINT_MANIFEST_FIELDS = [
    "id",
    "payload_presence_and_value",
    "vector_presence_and_value",
]
QDRANT_READ_CONSISTENCY = "all"
SNAPSHOT_PROFILE = "agentium-storage-attestation-v3"
EXACT_COMPARISON_PROFILE = "agentium-storage-exact-comparison-v1"
ADDITIONS_COMPARISON_PROFILE = "agentium-storage-object-additions-v1"


class StorageAttestationError(RuntimeError):
    """Raised when a storage invariant cannot be established safely."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run(argv: list[str], *, sensitive: bool = False) -> str:
    try:
        completed = subprocess.run(
            argv,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = (
            ""
            if sensitive
            else " ".join((getattr(exc, "stderr", "") or "").split())[:240]
        )
        suffix = f": {detail}" if detail else ""
        raise StorageAttestationError(f"command failed: {argv[0]}{suffix}") from exc
    return completed.stdout.strip()


def _dotenv_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        candidate, value = line.split("=", 1)
        if candidate.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def _require_loopback_endpoint(url: str, *, label: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.netloc
    ):
        raise StorageAttestationError(f"{label} endpoint must be loopback-only")
    return parsed


def _direct_urlopen(request: urllib.request.Request, *, timeout: int):
    # Secrets attached to a local Qdrant/MinIO request must never be forwarded
    # to an HTTP(S)_PROXY inherited from the operator environment.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def _http_json(
    url: str,
    *,
    api_key: str = "",
    json_body: Mapping[str, Any] | None = None,
    timeout: int = 15,
) -> Mapping[str, Any]:
    _require_loopback_endpoint(url, label="Qdrant")
    headers = {
        "Accept": "application/json",
        "User-Agent": "agentium-storage-attestor/1",
    }
    if api_key:
        headers["api-key"] = api_key
    body = None
    if json_body is not None:
        try:
            body = json.dumps(
                json_body,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise StorageAttestationError("Qdrant request is not valid JSON") from exc
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, headers=headers, data=body)
    try:
        with _direct_urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if response.status != 200:
                raise StorageAttestationError(f"Qdrant returned HTTP {response.status}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise StorageAttestationError("cannot read the local Qdrant API") from exc
    if len(payload) > MAX_HTTP_RESPONSE_BYTES:
        raise StorageAttestationError("Qdrant response is unexpectedly large")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StorageAttestationError("Qdrant returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise StorageAttestationError("Qdrant returned a non-object payload")
    return value


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identifier_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="surrogateescape")).hexdigest()


def _normalized_device_source(source: str) -> str:
    # findmnt represents a bind mount as /dev/sdX[/relative/path].  The
    # deployment contract is about the backing block device, not that suffix.
    candidate = source.split("[", 1)[0]
    if candidate.startswith("/dev/") and Path(candidate).exists():
        return str(Path(candidate).resolve())
    return candidate


def _mount(path: Path, *, expected_source: str = "") -> dict[str, Any]:
    if not path.exists():
        raise StorageAttestationError(f"required path does not exist: {path}")
    try:
        payload = json.loads(
            _run(
                [
                    "findmnt",
                    "--json",
                    "--output",
                    "SOURCE,TARGET,FSTYPE,OPTIONS",
                    "--target",
                    str(path),
                ]
            )
        )
        filesystems = payload["filesystems"]
        row = filesystems[0]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise StorageAttestationError(f"cannot resolve mount for {path}") from exc
    stat = os.statvfs(path)
    source = str(row.get("source", ""))
    normalized_source = _normalized_device_source(source)
    normalized_expected = (
        _normalized_device_source(expected_source) if expected_source else ""
    )
    if normalized_expected and normalized_source != normalized_expected:
        raise StorageAttestationError(
            f"unexpected backing device for {path}: expected {expected_source}"
        )
    return {
        "path": str(path),
        "source": source,
        "normalized_source": normalized_source,
        "expected_source": expected_source or None,
        "source_matches_expected": not normalized_expected
        or normalized_source == normalized_expected,
        "target": str(row.get("target", "")),
        "fstype": str(row.get("fstype", "")),
        "options": sorted(str(row.get("options", "")).split(",")),
        "device_id": os.stat(path).st_dev,
        "bytes_total": stat.f_blocks * stat.f_frsize,
        "bytes_free": stat.f_bavail * stat.f_frsize,
        "inodes_total": stat.f_files,
        "inodes_free": stat.f_favail,
    }


def _secure_deposit_aggregate(root: Path) -> dict[str, Any]:
    file_count = 0
    directory_count = 0
    byte_count = 0
    partial_count = 0
    manifest_rows: list[tuple[str, str, int, int, int, int]] = []
    errors: list[str] = []
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = os.scandir(directory)
        except OSError as exc:
            errors.append(exc.__class__.__name__)
            continue
        with entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        entry_stat = entry.stat(follow_symlinks=False)
                        relative = str(Path(entry.path).relative_to(root))
                        directory_count += 1
                        manifest_rows.append(
                            (
                                "directory",
                                _identifier_sha256(relative),
                                0,
                                entry_stat.st_ino,
                                entry_stat.st_mtime_ns,
                                entry_stat.st_ctime_ns,
                            )
                        )
                        stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        entry_stat = entry.stat(follow_symlinks=False)
                        size = entry_stat.st_size
                        file_count += 1
                        byte_count += size
                        if entry.name.endswith(".part"):
                            partial_count += 1
                        manifest_rows.append(
                            (
                                "file",
                                _identifier_sha256(
                                    str(Path(entry.path).relative_to(root))
                                ),
                                size,
                                entry_stat.st_ino,
                                entry_stat.st_mtime_ns,
                                entry_stat.st_ctime_ns,
                            )
                        )
                    else:
                        raise StorageAttestationError(
                            "Secure Deposit contains a symlink or special entry"
                        )
                except OSError as exc:
                    errors.append(exc.__class__.__name__)
    if errors:
        raise StorageAttestationError(
            f"Secure Deposit aggregate is incomplete ({len(errors)} inaccessible entries)"
        )
    digest = hashlib.sha256()
    for row in sorted(manifest_rows):
        digest.update("\0".join(str(value) for value in row).encode("ascii"))
        digest.update(b"\n")
    return {
        "files": file_count,
        "directories": directory_count,
        "bytes": byte_count,
        "partial_files": partial_count,
        "manifest_fields": [
            "kind",
            "path_sha256",
            "size",
            "inode",
            "mtime_ns",
            "ctime_ns",
        ],
        "manifest_sha256": digest.hexdigest(),
    }


def _stable_file_sha256(path: Path, expected_stat: os.stat_result) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise StorageAttestationError(
            "ObjectStore contains an unreadable file"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat_module.S_ISREG(opened.st_mode):
            raise StorageAttestationError("ObjectStore contains a non-regular entry")
        observed_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(
            getattr(opened, field) != getattr(expected_stat, field)
            for field in observed_fields
        ):
            raise StorageAttestationError(
                "ObjectStore changed while it was being attested"
            )
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, READ_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
        final = os.fstat(descriptor)
        if any(
            getattr(opened, field) != getattr(final, field) for field in observed_fields
        ):
            raise StorageAttestationError(
                "ObjectStore changed while it was being attested"
            )
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _object_store_snapshot(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise StorageAttestationError(
            f"required ObjectStore path does not exist: {root}"
        )
    rows: list[dict[str, Any]] = []
    directories: list[tuple[Path, tuple[int, int, int, int]]] = []
    total_bytes = 0
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            directory_stat = directory.stat(follow_symlinks=False)
        except OSError as exc:
            raise StorageAttestationError(
                "ObjectStore inventory is incomplete"
            ) from exc
        if not stat_module.S_ISDIR(directory_stat.st_mode):
            raise StorageAttestationError("ObjectStore root must not be a symlink")
        directories.append(
            (
                directory,
                (
                    directory_stat.st_dev,
                    directory_stat.st_ino,
                    directory_stat.st_mtime_ns,
                    directory_stat.st_ctime_ns,
                ),
            )
        )
        try:
            entries = os.scandir(directory)
        except OSError as exc:
            raise StorageAttestationError(
                "ObjectStore inventory is incomplete"
            ) from exc
        with entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        raise StorageAttestationError(
                            "ObjectStore contains a symlink or special entry"
                        )
                    entry_stat = entry.stat(follow_symlinks=False)
                    relative = str(Path(entry.path).relative_to(root))
                    content_sha256 = _stable_file_sha256(Path(entry.path), entry_stat)
                    rows.append(
                        {
                            "path_sha256": _identifier_sha256(relative),
                            "size": entry_stat.st_size,
                            "content_sha256": content_sha256,
                        }
                    )
                    total_bytes += entry_stat.st_size
                except OSError as exc:
                    raise StorageAttestationError(
                        "ObjectStore inventory is incomplete"
                    ) from exc
    for directory, expected in directories:
        try:
            current_stat = directory.stat(follow_symlinks=False)
        except OSError as exc:
            raise StorageAttestationError(
                "ObjectStore changed while it was being attested"
            ) from exc
        current = (
            current_stat.st_dev,
            current_stat.st_ino,
            current_stat.st_mtime_ns,
            current_stat.st_ctime_ns,
        )
        if current != expected:
            raise StorageAttestationError(
                "ObjectStore changed while it was being attested"
            )
    sorted_rows = sorted(rows, key=lambda row: row["path_sha256"])
    return {
        "files": len(rows),
        "bytes": total_bytes,
        "algorithm": "sha256-merkle-v1",
        "entry_fields": ["path_sha256", "size", "content_sha256"],
        "entries": sorted_rows,
        "content_manifest_sha256": _canonical_json_sha256(sorted_rows),
    }


def _docker_environment(container: str) -> dict[str, str]:
    try:
        payload = json.loads(
            _run(
                ["docker", "inspect", "--format", "{{json .Config.Env}}", container],
                sensitive=True,
            )
        )
    except json.JSONDecodeError as exc:
        raise StorageAttestationError(
            "cannot read the local MinIO credentials"
        ) from exc
    if not isinstance(payload, list):
        raise StorageAttestationError("cannot read the local MinIO credentials")
    values: dict[str, str] = {}
    for raw in payload:
        if isinstance(raw, str) and "=" in raw:
            key, value = raw.split("=", 1)
            values[key] = value
    return values


def _minio_credentials(env_path: Path | None) -> tuple[str, str]:
    access_key = _dotenv_value(env_path, "MINIO_ROOT_USER") if env_path else ""
    secret_key = _dotenv_value(env_path, "MINIO_ROOT_PASSWORD") if env_path else ""
    if not access_key or not secret_key:
        environment = _docker_environment("agentium-minio")
        access_key = access_key or environment.get("MINIO_ROOT_USER", "")
        secret_key = secret_key or environment.get("MINIO_ROOT_PASSWORD", "")
    if not access_key or not secret_key:
        raise StorageAttestationError("local MinIO credentials are unavailable")
    return access_key, secret_key


def _object_store_binding(container: str) -> dict[str, Any]:
    environment = _docker_environment(container)
    backend = (environment.get("OBJECT_STORE_BACKEND") or "local").strip().lower()
    if backend == "local":
        base_path = environment.get("OBJECT_STORE_BASE_PATH") or "/data/object_store"
        return {
            "backend": "local",
            "local_path_id_sha256": _identifier_sha256(base_path),
            "s3_bucket_id_sha256": None,
            "s3_endpoint_id_sha256": None,
        }
    if backend == "s3":
        bucket = environment.get("OBJECT_STORE_S3_BUCKET", "")
        endpoint = environment.get("OBJECT_STORE_S3_ENDPOINT_URL", "")
        if not bucket or not endpoint:
            raise StorageAttestationError(
                f"ObjectStore S3 binding is incomplete for {container}"
            )
        return {
            "backend": "s3",
            "local_path_id_sha256": None,
            "s3_bucket_id_sha256": _identifier_sha256(bucket),
            "s3_endpoint_id_sha256": _identifier_sha256(endpoint),
        }
    raise StorageAttestationError(f"unsupported ObjectStore backend for {container}")


def _object_store_bindings() -> dict[str, Any]:
    bindings = {
        "backend": _object_store_binding("agentium-backend"),
        "worker_cpu": _object_store_binding("agentium-worker-cpu"),
    }
    if bindings["backend"] != bindings["worker_cpu"]:
        raise StorageAttestationError("backend and worker ObjectStore bindings differ")
    return bindings


def _signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    date_key = hmac.new(
        f"AWS4{secret_key}".encode(), date_stamp.encode(), hashlib.sha256
    ).digest()
    region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
    service_key = hmac.new(region_key, service.encode(), hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def _signed_s3_xml(
    endpoint: str,
    *,
    bucket: str,
    query: Sequence[tuple[str, str]],
    access_key: str,
    secret_key: str,
) -> bytes:
    parsed = _require_loopback_endpoint(endpoint, label="MinIO attestation")
    if parsed.path not in {"", "/"} or not parsed.netloc:
        raise StorageAttestationError("MinIO attestation endpoint is invalid")

    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    region = "us-east-1"
    service = "s3"
    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_uri = "/" + urllib.parse.quote(bucket, safe="-_.~")
    canonical_query = urllib.parse.urlencode(
        sorted(query),
        doseq=True,
        quote_via=urllib.parse.quote,
        safe="-_.~",
    )
    host = parsed.netloc
    canonical_headers = (
        f"host:{host}\n"
        f"x-amz-content-sha256:{payload_hash}\n"
        f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        [
            "GET",
            canonical_uri,
            canonical_query,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    signature = hmac.new(
        _signing_key(secret_key, date_stamp, region, service),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, canonical_uri, canonical_query, "")
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/xml",
            "Authorization": authorization,
            "User-Agent": "agentium-storage-attestor/1",
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        },
    )
    try:
        with _direct_urlopen(request, timeout=30) as response:
            payload = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
            if response.status != 200:
                raise StorageAttestationError(f"MinIO returned HTTP {response.status}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise StorageAttestationError("cannot read the local MinIO inventory") from exc
    if len(payload) > MAX_HTTP_RESPONSE_BYTES:
        raise StorageAttestationError("MinIO inventory page is unexpectedly large")
    return payload


def _xml_text(element: ElementTree.Element, name: str) -> str:
    for child in element:
        if child.tag.rsplit("}", 1)[-1] == name:
            return child.text or ""
    return ""


def _minio_inventory_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    bucket: str,
    versioning_status: str = "enabled",
) -> dict[str, Any]:
    if versioning_status not in {"enabled", "unversioned"}:
        raise StorageAttestationError(
            "MinIO bucket versioning status is not attestable"
        )
    normalized: list[list[Any]] = []
    bytes_total = 0
    latest_versions = 0
    delete_markers = 0
    for row in rows:
        key = str(row.get("key", ""))
        version_id = str(row.get("version_id", ""))
        size = int(row.get("size", 0) or 0)
        is_delete_marker = bool(row.get("delete_marker", False))
        is_latest = bool(row.get("is_latest", False))
        if not key:
            raise StorageAttestationError(
                "MinIO returned an object without an identifier"
            )
        etag = str(row.get("etag", "")).strip('"')
        last_modified = str(row.get("last_modified", ""))
        normalized.append(
            [
                _identifier_sha256(key),
                _identifier_sha256(version_id) if version_id else None,
                size,
                _identifier_sha256(etag),
                last_modified,
                is_latest,
                is_delete_marker,
            ]
        )
        if is_delete_marker:
            delete_markers += 1
        else:
            bytes_total += size
        if is_latest:
            latest_versions += 1
    normalized.sort(key=lambda row: (row[0], row[1] or ""))
    return {
        "bucket_id_sha256": _identifier_sha256(bucket),
        "versioning_status": versioning_status,
        "versions": len(normalized),
        "latest_versions": latest_versions,
        "delete_markers": delete_markers,
        "bytes": bytes_total,
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
        "entries": normalized,
        "inventory_sha256": _canonical_json_sha256(normalized),
    }


def _minio_versioning_status(
    endpoint: str,
    *,
    bucket: str,
    access_key: str,
    secret_key: str,
    require_enabled: bool = True,
) -> str:
    """Return the authoritative S3 bucket versioning state.

    An empty VersioningConfiguration is the normal S3 response for a bucket
    that has never enabled versioning.  That state, and ``Suspended``, are
    both unsafe for the transactional deployment contract: an in-place
    overwrite or delete would only be detected by the inventory and could not
    be restored from a previous object version.
    """

    payload = _signed_s3_xml(
        endpoint,
        bucket=bucket,
        query=[("versioning", "")],
        access_key=access_key,
        secret_key=secret_key,
    )
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise StorageAttestationError(
            "MinIO returned an invalid versioning contract"
        ) from exc
    status = _xml_text(root, "Status")
    if status != "Enabled":
        normalized = "suspended" if status == "Suspended" else "unversioned"
        if not require_enabled and normalized == "unversioned":
            return normalized
        raise StorageAttestationError(
            f"MinIO bucket versioning is {normalized}; safe deployment refused"
        )
    return "enabled"


def _minio_snapshot(
    endpoint: str,
    *,
    bucket: str,
    env_path: Path | None,
    require_versioning: bool = True,
) -> dict[str, Any]:
    if not bucket or "/" in bucket or "\x00" in bucket:
        raise StorageAttestationError("MinIO bucket identifier is invalid")
    access_key, secret_key = _minio_credentials(env_path)
    versioning_status = _minio_versioning_status(
        endpoint,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
        require_enabled=require_versioning,
    )
    rows: list[dict[str, Any]] = []
    key_marker = ""
    version_marker = ""
    seen_markers: set[tuple[str, str]] = set()
    for _page in range(100_000):
        query = [("encoding-type", "url"), ("max-keys", "1000"), ("versions", "")]
        if key_marker:
            query.append(("key-marker", key_marker))
        if version_marker:
            query.append(("version-id-marker", version_marker))
        payload = _signed_s3_xml(
            endpoint,
            bucket=bucket,
            query=query,
            access_key=access_key,
            secret_key=secret_key,
        )
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise StorageAttestationError(
                "MinIO returned an invalid inventory"
            ) from exc
        for element in root:
            kind = element.tag.rsplit("}", 1)[-1]
            if kind not in {"Version", "DeleteMarker"}:
                continue
            raw_size = _xml_text(element, "Size")
            try:
                size = int(raw_size or 0)
            except ValueError as exc:
                raise StorageAttestationError(
                    "MinIO returned an invalid object size"
                ) from exc
            rows.append(
                {
                    "key": urllib.parse.unquote(_xml_text(element, "Key")),
                    "version_id": _xml_text(element, "VersionId"),
                    "size": size,
                    "etag": _xml_text(element, "ETag"),
                    "last_modified": _xml_text(element, "LastModified"),
                    "is_latest": _xml_text(element, "IsLatest").lower() == "true",
                    "delete_marker": kind == "DeleteMarker",
                }
            )
        if _xml_text(root, "IsTruncated").lower() != "true":
            return _minio_inventory_from_rows(
                rows,
                bucket=bucket,
                versioning_status=versioning_status,
            )
        next_markers = (
            urllib.parse.unquote(_xml_text(root, "NextKeyMarker")),
            _xml_text(root, "NextVersionIdMarker"),
        )
        if not next_markers[0] or next_markers in seen_markers:
            raise StorageAttestationError("MinIO inventory pagination did not advance")
        seen_markers.add(next_markers)
        key_marker, version_marker = next_markers
    raise StorageAttestationError("MinIO inventory exceeded the safe page limit")


def _container_mounts(container: str) -> list[dict[str, Any]]:
    try:
        raw = _run(["docker", "inspect", "--format", "{{json .Mounts}}", container])
        mounts = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StorageAttestationError(
            f"invalid Docker mount data for {container}"
        ) from exc
    if not isinstance(mounts, list):
        raise StorageAttestationError(
            f"Docker mount data is not a list for {container}"
        )
    result = []
    for item in mounts:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "type": str(item.get("Type", "")),
                "source": str(item.get("Source", "")),
                "destination": str(item.get("Destination", "")),
                "rw": bool(item.get("RW", False)),
                "name": str(item.get("Name", "")),
            }
        )
    return sorted(result, key=lambda item: (item["destination"], item["source"]))


def _faiss_snapshot() -> dict[str, Any]:
    sources: set[str] = set()
    for container in ("agentium-backend", "agentium-worker-cpu"):
        matches = [
            mount
            for mount in _container_mounts(container)
            if mount["destination"] == "/data/faiss_db"
        ]
        if len(matches) != 1 or matches[0]["type"] != "bind":
            raise StorageAttestationError(
                f"{container} FAISS bind mount is missing or ambiguous"
            )
        sources.add(matches[0]["source"])
    if len(sources) != 1:
        raise StorageAttestationError("backend and worker FAISS bind sources differ")
    source = Path(sources.pop())
    try:
        stat = source.stat(follow_symlinks=False)
    except OSError as exc:
        raise StorageAttestationError("FAISS bind source is unavailable") from exc
    if not source.is_dir() or source.is_symlink():
        raise StorageAttestationError("FAISS bind source must be a real directory")
    inventory = _object_store_snapshot(source)
    return {
        **inventory,
        "source_id_sha256": _identifier_sha256(str(source)),
        "device_id": int(stat.st_dev),
        "inode": int(stat.st_ino),
    }


def _qdrant_consistent_url(base: str, path: str) -> str:
    query = urllib.parse.urlencode({"consistency": QDRANT_READ_CONSISTENCY})
    return f"{base}{path}?{query}"


def _qdrant_point_id_sort_key(value: Any) -> tuple[int, int]:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value < 2**64
    ):
        return (0, value)
    if isinstance(value, str) and value:
        try:
            return (1, uuid.UUID(value).int)
        except (ValueError, AttributeError) as exc:
            raise StorageAttestationError("Qdrant returned an invalid point ID") from exc
    raise StorageAttestationError("Qdrant returned an invalid point ID")


def _qdrant_point_id_is_valid(value: Any) -> bool:
    try:
        _qdrant_point_id_sort_key(value)
    except StorageAttestationError:
        return False
    return True


def _qdrant_exact_count(
    base: str,
    encoded_collection: str,
    *,
    api_key: str,
) -> int:
    payload = _http_json(
        _qdrant_consistent_url(
            base,
            f"/collections/{encoded_collection}/points/count",
        ),
        api_key=api_key,
        json_body={"exact": True},
        timeout=60,
    )
    result = payload.get("result")
    count = result.get("count") if isinstance(result, dict) else None
    if not _is_nonnegative_int(count):
        raise StorageAttestationError("Qdrant returned an invalid exact point count")
    return count


def _qdrant_point_manifest(
    base: str,
    encoded_collection: str,
    *,
    api_key: str,
) -> dict[str, Any]:
    """Hash every logical point while emitting no point data or identifier.

    Qdrant's default scroll order is point-id order.  The read-consistency
    contract is explicit on every count and scroll request.  Exact counts on
    both sides of the traversal prevent a partial page sequence from being
    accepted; the deployment write barrier is what makes the multi-request
    traversal a stable logical snapshot.
    """

    count_before = _qdrant_exact_count(
        base,
        encoded_collection,
        api_key=api_key,
    )
    digest = hashlib.sha256()
    digest.update(b"agentium-qdrant-point-manifest-v1\0")
    scanned = 0
    offset: Any = None
    last_point_key: tuple[int, int] | None = None
    seen_offsets: set[str] = set()

    for _page in range(MAX_QDRANT_SCROLL_PAGES):
        body: dict[str, Any] = {
            "limit": QDRANT_SCROLL_PAGE_SIZE,
            "with_payload": True,
            "with_vector": True,
        }
        if offset is not None:
            body["offset"] = offset
        payload = _http_json(
            _qdrant_consistent_url(
                base,
                f"/collections/{encoded_collection}/points/scroll",
            ),
            api_key=api_key,
            json_body=body,
            timeout=120,
        )
        result = payload.get("result")
        points = result.get("points") if isinstance(result, dict) else None
        if not isinstance(points, list) or len(points) > QDRANT_SCROLL_PAGE_SIZE:
            raise StorageAttestationError("Qdrant returned an invalid scroll page")
        for point in points:
            if not isinstance(point, dict):
                raise StorageAttestationError("Qdrant returned an invalid point")
            point_key = _qdrant_point_id_sort_key(point.get("id"))
            if last_point_key is not None and point_key <= last_point_key:
                raise StorageAttestationError(
                    "Qdrant scroll is not strictly ordered by point ID"
                )
            last_point_key = point_key
            logical_point = {
                "id": point["id"],
                "payload": {
                    "present": "payload" in point,
                    "value": point.get("payload"),
                },
                "vector": {
                    "present": "vector" in point,
                    "value": point.get("vector"),
                },
            }
            try:
                encoded_point = json.dumps(
                    logical_point,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise StorageAttestationError(
                    "Qdrant returned a non-canonical point"
                ) from exc
            digest.update(len(encoded_point).to_bytes(8, byteorder="big"))
            digest.update(encoded_point)
            scanned += 1
            if scanned > count_before:
                raise StorageAttestationError(
                    "Qdrant scroll exceeds the exact point count"
                )

        next_offset = result.get("next_page_offset")
        if next_offset is None:
            break
        if not points or not _qdrant_point_id_is_valid(next_offset):
            raise StorageAttestationError("Qdrant returned an invalid scroll offset")
        offset_identity = _canonical_json_sha256(
            {"type": type(next_offset).__name__, "value": next_offset}
        )
        if offset_identity in seen_offsets:
            raise StorageAttestationError("Qdrant scroll offset did not progress")
        seen_offsets.add(offset_identity)
        offset = next_offset
    else:
        raise StorageAttestationError("Qdrant scroll exceeded the page safety limit")

    count_after = _qdrant_exact_count(
        base,
        encoded_collection,
        api_key=api_key,
    )
    if count_before != scanned or count_after != scanned:
        raise StorageAttestationError(
            "Qdrant changed or returned an incomplete point traversal"
        )
    return {
        "points_count_exact": scanned,
        "point_manifest_sha256": digest.hexdigest(),
    }


def _qdrant_snapshot(base_url: str, *, api_key: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    collection_payload = _http_json(f"{base}/collections", api_key=api_key)
    collections = collection_payload.get("result", {}).get("collections", [])
    if not isinstance(collections, list):
        raise StorageAttestationError("Qdrant collection list is invalid")
    rows = []
    for collection in collections:
        name = collection.get("name") if isinstance(collection, dict) else None
        if not isinstance(name, str) or not name:
            raise StorageAttestationError("Qdrant returned a collection without a name")
        encoded = urllib.parse.quote(name, safe="")
        detail = _http_json(f"{base}/collections/{encoded}", api_key=api_key).get(
            "result"
        )
        if not isinstance(detail, dict):
            raise StorageAttestationError(
                "Qdrant returned an invalid collection detail"
            )
        if detail.get("status") != "green":
            raise StorageAttestationError(
                f"Qdrant collection {_identifier_sha256(name)[:12]} is not green"
            )
        config = detail.get("config")
        payload_schema = detail.get("payload_schema", {})
        if not isinstance(config, dict) or not isinstance(payload_schema, dict):
            raise StorageAttestationError(
                "Qdrant returned an invalid collection contract"
            )
        point_manifest = _qdrant_point_manifest(
            base,
            encoded,
            api_key=api_key,
        )
        rows.append(
            {
                "collection_id_sha256": _identifier_sha256(name),
                "status": detail.get("status"),
                "optimizer_status_sha256": _canonical_json_sha256(
                    detail.get("optimizer_status")
                ),
                "points_count": detail.get("points_count"),
                "vectors_count": detail.get("vectors_count"),
                "indexed_vectors_count": detail.get("indexed_vectors_count"),
                "segments_count": detail.get("segments_count"),
                "config_sha256": _canonical_json_sha256(config),
                "payload_schema_sha256": _canonical_json_sha256(payload_schema),
                **point_manifest,
            }
        )
    alias_payload = _http_json(f"{base}/aliases", api_key=api_key)
    aliases = alias_payload.get("result", {}).get("aliases", [])
    if not isinstance(aliases, list):
        raise StorageAttestationError("Qdrant alias list is invalid")
    normalized_aliases = []
    for alias in aliases:
        if not isinstance(alias, dict):
            raise StorageAttestationError("Qdrant returned an invalid alias")
        alias_name = alias.get("alias_name")
        collection_name = alias.get("collection_name")
        if (
            not isinstance(alias_name, str)
            or not alias_name
            or not isinstance(collection_name, str)
            or not collection_name
        ):
            raise StorageAttestationError("Qdrant returned an invalid alias")
        normalized_aliases.append(
            {
                "alias_id_sha256": _identifier_sha256(alias_name),
                "collection_id_sha256": _identifier_sha256(collection_name),
            }
        )
    sorted_rows = sorted(rows, key=lambda row: row["collection_id_sha256"])
    sorted_aliases = sorted(
        normalized_aliases,
        key=lambda row: (row["alias_id_sha256"], row["collection_id_sha256"]),
    )
    inventory = {
        "point_manifest_algorithm": QDRANT_POINT_MANIFEST_ALGORITHM,
        "point_manifest_fields": QDRANT_POINT_MANIFEST_FIELDS,
        "read_consistency": QDRANT_READ_CONSISTENCY,
        "points_count_exact": sum(row["points_count_exact"] for row in sorted_rows),
        "collections": sorted_rows,
        "aliases": sorted_aliases,
    }
    return {**inventory, "inventory_sha256": _canonical_json_sha256(inventory)}


def capture_snapshot(
    *,
    secure_deposit: Path,
    data_root: Path,
    qdrant_url: str,
    qdrant_env: Path,
    containers: Iterable[str],
    object_store: Path | None = None,
    minio_url: str = DEFAULT_MINIO_URL,
    minio_bucket: str = DEFAULT_MINIO_BUCKET,
    minio_env: Path | None = None,
    expected_data_source: str = DEFAULT_DATA_SOURCE,
    expected_secure_deposit_source: str = DEFAULT_SECURE_DEPOSIT_SOURCE,
    require_minio_versioning: bool = True,
) -> dict[str, Any]:
    api_key = _dotenv_value(qdrant_env, "QDRANT__SERVICE__API_KEY") or _dotenv_value(
        qdrant_env, "QDRANT_API_KEY"
    )
    return {
        "schema_version": 1,
        "profile": SNAPSHOT_PROFILE,
        "captured_at": _utc_now(),
        "mounts": {
            "root": _mount(Path("/")),
            "data": _mount(data_root, expected_source=expected_data_source),
            "secure_deposit": _mount(
                secure_deposit,
                expected_source=expected_secure_deposit_source,
            ),
        },
        "secure_deposit": _secure_deposit_aggregate(secure_deposit),
        "object_store": _object_store_snapshot(
            object_store or data_root / "object_store"
        ),
        "faiss": _faiss_snapshot(),
        "object_store_bindings": _object_store_bindings(),
        "minio": _minio_snapshot(
            minio_url,
            bucket=minio_bucket,
            env_path=minio_env,
            require_versioning=require_minio_versioning,
        ),
        "qdrant": _qdrant_snapshot(qdrant_url, api_key=api_key),
        "container_mounts": {
            name: _container_mounts(name) for name in sorted(set(containers))
        },
    }


def _require_digest(value: Any, *, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise StorageAttestationError(f"{label} digest is missing")
    try:
        int(value, 16)
    except ValueError as exc:
        raise StorageAttestationError(f"{label} digest is invalid") from exc


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_object_store_inventory(value: Mapping[str, Any], *, label: str) -> None:
    entries = value.get("entries")
    if (
        value.get("algorithm") != "sha256-merkle-v1"
        or value.get("entry_fields") != ["path_sha256", "size", "content_sha256"]
        or not isinstance(entries, list)
    ):
        raise StorageAttestationError(f"{label} ObjectStore inventory is invalid")
    identities: list[str] = []
    total_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path_sha256",
            "size",
            "content_sha256",
        }:
            raise StorageAttestationError(f"{label} ObjectStore entry is invalid")
        _require_digest(entry.get("path_sha256"), label=f"{label} ObjectStore path")
        _require_digest(
            entry.get("content_sha256"), label=f"{label} ObjectStore content"
        )
        if not _is_nonnegative_int(entry.get("size")):
            raise StorageAttestationError(f"{label} ObjectStore size is invalid")
        identities.append(entry["path_sha256"])
        total_bytes += entry["size"]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise StorageAttestationError(f"{label} ObjectStore identities are invalid")
    if value.get("files") != len(entries) or value.get("bytes") != total_bytes:
        raise StorageAttestationError(f"{label} ObjectStore aggregates are invalid")
    expected_digest = _canonical_json_sha256(entries)
    _require_digest(value.get("content_manifest_sha256"), label=f"{label} ObjectStore")
    if value.get("content_manifest_sha256") != expected_digest:
        raise StorageAttestationError(f"{label} ObjectStore digest is inconsistent")


def _validate_minio_inventory(value: Mapping[str, Any], *, label: str) -> None:
    entries = value.get("entries")
    expected_fields = [
        "object_id_sha256",
        "version_id_sha256",
        "size",
        "etag_sha256",
        "last_modified",
        "is_latest",
        "delete_marker",
    ]
    if (
        value.get("versioning_status") != "enabled"
        or value.get("algorithm") != "s3-version-inventory-sha256-v1"
        or value.get("entry_fields") != expected_fields
        or not isinstance(entries, list)
    ):
        raise StorageAttestationError(f"{label} MinIO inventory is invalid")
    identities: list[str] = []
    total_bytes = 0
    latest_versions = 0
    delete_markers = 0
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != len(expected_fields):
            raise StorageAttestationError(f"{label} MinIO entry is invalid")
        (
            object_identity,
            version_identity,
            size,
            etag_digest,
            last_modified,
            is_latest,
            is_delete_marker,
        ) = entry
        _require_digest(object_identity, label=f"{label} MinIO object")
        if version_identity is not None:
            _require_digest(version_identity, label=f"{label} MinIO version")
        _require_digest(etag_digest, label=f"{label} MinIO ETag")
        if (
            not _is_nonnegative_int(size)
            or not isinstance(last_modified, str)
            or not last_modified
            or not isinstance(is_latest, bool)
            or not isinstance(is_delete_marker, bool)
            or (is_delete_marker and size != 0)
        ):
            raise StorageAttestationError(f"{label} MinIO entry metadata is invalid")
        identity = f"{object_identity}:{version_identity or ''}"
        identities.append(identity)
        if not is_delete_marker:
            total_bytes += size
        latest_versions += int(is_latest)
        delete_markers += int(is_delete_marker)
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise StorageAttestationError(f"{label} MinIO identities are invalid")
    if (
        value.get("versions") != len(entries)
        or value.get("bytes") != total_bytes
        or value.get("latest_versions") != latest_versions
        or value.get("delete_markers") != delete_markers
    ):
        raise StorageAttestationError(f"{label} MinIO aggregates are invalid")
    _require_digest(value.get("bucket_id_sha256"), label=f"{label} MinIO bucket")
    _require_digest(value.get("inventory_sha256"), label=f"{label} MinIO")
    if value.get("inventory_sha256") != _canonical_json_sha256(entries):
        raise StorageAttestationError(f"{label} MinIO digest is inconsistent")


def _validate_qdrant_inventory(value: Mapping[str, Any], *, label: str) -> None:
    inventory_fields = {
        "point_manifest_algorithm",
        "point_manifest_fields",
        "read_consistency",
        "points_count_exact",
        "collections",
        "aliases",
    }
    if set(value) != inventory_fields | {"inventory_sha256"}:
        raise StorageAttestationError(f"{label} Qdrant inventory is invalid")
    collections = value.get("collections")
    aliases = value.get("aliases")
    if (
        value.get("point_manifest_algorithm")
        != QDRANT_POINT_MANIFEST_ALGORITHM
        or value.get("point_manifest_fields") != QDRANT_POINT_MANIFEST_FIELDS
        or value.get("read_consistency") != QDRANT_READ_CONSISTENCY
        or not isinstance(collections, list)
        or not isinstance(aliases, list)
    ):
        raise StorageAttestationError(f"{label} Qdrant inventory is invalid")

    collection_fields = {
        "collection_id_sha256",
        "status",
        "optimizer_status_sha256",
        "points_count",
        "vectors_count",
        "indexed_vectors_count",
        "segments_count",
        "config_sha256",
        "payload_schema_sha256",
        "points_count_exact",
        "point_manifest_sha256",
    }
    collection_ids: list[str] = []
    total_points = 0
    for collection in collections:
        if not isinstance(collection, dict) or set(collection) != collection_fields:
            raise StorageAttestationError(f"{label} Qdrant collection is invalid")
        collection_id = collection.get("collection_id_sha256")
        _require_digest(collection_id, label=f"{label} Qdrant collection")
        for field in (
            "optimizer_status_sha256",
            "config_sha256",
            "payload_schema_sha256",
            "point_manifest_sha256",
        ):
            _require_digest(
                collection.get(field),
                label=f"{label} Qdrant {field}",
            )
        if collection.get("status") != "green":
            raise StorageAttestationError(f"{label} Qdrant collection is not green")
        for field in (
            "points_count",
            "vectors_count",
            "indexed_vectors_count",
            "segments_count",
        ):
            if collection.get(field) is not None and not _is_nonnegative_int(
                collection.get(field)
            ):
                raise StorageAttestationError(
                    f"{label} Qdrant collection statistics are invalid"
                )
        exact_count = collection.get("points_count_exact")
        if not _is_nonnegative_int(exact_count):
            raise StorageAttestationError(
                f"{label} Qdrant point manifest aggregate is invalid"
            )
        collection_ids.append(collection_id)
        total_points += exact_count
    if collection_ids != sorted(collection_ids) or len(collection_ids) != len(
        set(collection_ids)
    ):
        raise StorageAttestationError(f"{label} Qdrant collection identities are invalid")

    alias_fields = {"alias_id_sha256", "collection_id_sha256"}
    alias_identities: list[tuple[str, str]] = []
    alias_names: list[str] = []
    collection_id_set = set(collection_ids)
    for alias in aliases:
        if not isinstance(alias, dict) or set(alias) != alias_fields:
            raise StorageAttestationError(f"{label} Qdrant alias is invalid")
        alias_id = alias.get("alias_id_sha256")
        collection_id = alias.get("collection_id_sha256")
        _require_digest(alias_id, label=f"{label} Qdrant alias")
        _require_digest(collection_id, label=f"{label} Qdrant alias collection")
        if collection_id not in collection_id_set:
            raise StorageAttestationError(
                f"{label} Qdrant alias target is not inventoried"
            )
        alias_names.append(alias_id)
        alias_identities.append((alias_id, collection_id))
    if (
        alias_identities != sorted(alias_identities)
        or len(alias_names) != len(set(alias_names))
    ):
        raise StorageAttestationError(f"{label} Qdrant alias identities are invalid")

    if value.get("points_count_exact") != total_points:
        raise StorageAttestationError(f"{label} Qdrant aggregates are invalid")
    inventory = {field: value.get(field) for field in inventory_fields}
    _require_digest(value.get("inventory_sha256"), label=f"{label} Qdrant")
    if value.get("inventory_sha256") != _canonical_json_sha256(inventory):
        raise StorageAttestationError(f"{label} Qdrant digest is inconsistent")


def _validate_object_store_bindings(value: Any, *, label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"backend", "worker_cpu"}:
        raise StorageAttestationError(f"{label} ObjectStore bindings are invalid")
    if value["backend"] != value["worker_cpu"]:
        raise StorageAttestationError(f"{label} ObjectStore bindings differ")
    binding = value["backend"]
    if not isinstance(binding, dict) or set(binding) != {
        "backend",
        "local_path_id_sha256",
        "s3_bucket_id_sha256",
        "s3_endpoint_id_sha256",
    }:
        raise StorageAttestationError(f"{label} ObjectStore binding is invalid")
    if binding.get("backend") == "local":
        _require_digest(
            binding.get("local_path_id_sha256"), label=f"{label} local ObjectStore path"
        )
        if (
            binding.get("s3_bucket_id_sha256") is not None
            or binding.get("s3_endpoint_id_sha256") is not None
        ):
            raise StorageAttestationError(
                f"{label} local ObjectStore binding is invalid"
            )
    elif binding.get("backend") == "s3":
        _require_digest(binding.get("s3_bucket_id_sha256"), label=f"{label} S3 bucket")
        _require_digest(
            binding.get("s3_endpoint_id_sha256"), label=f"{label} S3 endpoint"
        )
        if binding.get("local_path_id_sha256") is not None:
            raise StorageAttestationError(f"{label} S3 ObjectStore binding is invalid")
    else:
        raise StorageAttestationError(f"{label} ObjectStore backend is invalid")


def _validate_snapshot_shape(snapshot: Mapping[str, Any], *, label: str) -> None:
    if (
        snapshot.get("schema_version") != 1
        or snapshot.get("profile") != SNAPSHOT_PROFILE
    ):
        raise StorageAttestationError(
            f"{label} storage snapshot profile is unsupported"
        )
    secure = snapshot.get("secure_deposit")
    object_store = snapshot.get("object_store")
    faiss = snapshot.get("faiss")
    minio = snapshot.get("minio")
    qdrant = snapshot.get("qdrant")
    if not all(
        isinstance(item, dict) for item in (secure, object_store, faiss, minio, qdrant)
    ):
        raise StorageAttestationError(f"{label} storage snapshot is incomplete")
    _require_digest(secure.get("manifest_sha256"), label=f"{label} Secure Deposit")
    _validate_object_store_inventory(object_store, label=label)
    _validate_object_store_inventory(faiss, label=f"{label} FAISS")
    _require_digest(faiss.get("source_id_sha256"), label=f"{label} FAISS source")
    if not _is_nonnegative_int(faiss.get("device_id")) or not _is_nonnegative_int(
        faiss.get("inode")
    ):
        raise StorageAttestationError(f"{label} FAISS filesystem identity is invalid")
    _validate_object_store_bindings(snapshot.get("object_store_bindings"), label=label)
    _validate_minio_inventory(minio, label=label)
    binding = snapshot["object_store_bindings"]["backend"]
    if (
        binding.get("backend") == "s3"
        and binding.get("s3_bucket_id_sha256") != minio.get("bucket_id_sha256")
    ):
        raise StorageAttestationError(
            f"{label} MinIO inventory does not attest the runtime S3 bucket"
        )
    _validate_qdrant_inventory(qdrant, label=label)
    mounts = snapshot.get("mounts")
    if not isinstance(mounts, dict):
        raise StorageAttestationError(f"{label} mount contract is missing")
    for mount_name in ("data", "secure_deposit"):
        mount = mounts.get(mount_name)
        if (
            not isinstance(mount, dict)
            or not mount.get("expected_source")
            or mount.get("source_matches_expected") is not True
        ):
            raise StorageAttestationError(
                f"{label} {mount_name} backing device is unverified"
            )


def _validation_mount_transition_allowed(before: Any, after: Any) -> bool:
    """Allow only the deliberate FAISS RW→RO validation hardening.

    Source, destination, mount type/name, container set, and every unrelated
    read/write bit remain exact.  The reverse transition is intentionally not
    accepted by the closed-boundary comparator.
    """

    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    if set(before) != set(after):
        return False
    allowed_transitions = {
        "agentium-backend": {
            "/data/object_store",
            "/data/secure_deposit",
            "/data/faiss_db",
        },
        "agentium-worker-cpu": {
            "/data/object_store",
            "/data/secure_deposit",
            "/data/faiss_db",
        },
        "agentium-p4-maintenance": {
            "/data/object_store",
            "/data/secure_deposit",
            "/data/faiss_db",
        },
        "agentium-sftp": {"/data/secure_deposit"},
    }
    for container in before:
        before_rows = before[container]
        after_rows = after[container]
        if not isinstance(before_rows, list) or not isinstance(after_rows, list):
            return False
        if len(before_rows) != len(after_rows):
            return False
        for left, right in zip(before_rows, after_rows, strict=True):
            if not isinstance(left, dict) or not isinstance(right, dict):
                return False
            if set(left) != {"type", "source", "destination", "rw", "name"}:
                return False
            if set(right) != set(left):
                return False
            if any(left[field] != right[field] for field in left if field != "rw"):
                return False
            if left["rw"] == right["rw"]:
                continue
            if not (
                left["destination"] in allowed_transitions.get(container, set())
                and left["rw"] is True
                and right["rw"] is False
            ):
                return False
    return True


def compare_snapshots(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    _validate_snapshot_shape(before, label="before")
    _validate_snapshot_shape(after, label="after")
    checks: list[dict[str, Any]] = []

    def check(name: str, left: Any, right: Any) -> None:
        checks.append(
            {
                "name": name,
                "passed": left == right,
                "before": left,
                "after": right,
            }
        )

    check(
        "secure_deposit.aggregate",
        before.get("secure_deposit"),
        after.get("secure_deposit"),
    )
    check(
        "object_store_bindings",
        before.get("object_store_bindings"),
        after.get("object_store_bindings"),
    )
    check("faiss", before.get("faiss"), after.get("faiss"))
    for section, fields in (
        (
            "object_store",
            ("algorithm", "files", "bytes", "content_manifest_sha256"),
        ),
        (
            "minio",
            (
                "versioning_status",
                "algorithm",
                "bucket_id_sha256",
                "versions",
                "latest_versions",
                "delete_markers",
                "bytes",
                "inventory_sha256",
            ),
        ),
    ):
        for field in fields:
            check(
                f"{section}.{field}",
                before.get(section, {}).get(field),
                after.get(section, {}).get(field),
            )
    check(
        "qdrant.collections",
        before.get("qdrant", {}).get("collections"),
        after.get("qdrant", {}).get("collections"),
    )
    check(
        "qdrant.aliases",
        before.get("qdrant", {}).get("aliases"),
        after.get("qdrant", {}).get("aliases"),
    )
    check(
        "qdrant.inventory",
        before.get("qdrant", {}).get("inventory_sha256"),
        after.get("qdrant", {}).get("inventory_sha256"),
    )
    before_mounts = before.get("container_mounts")
    after_mounts = after.get("container_mounts")
    mount_transition_ok = _validation_mount_transition_allowed(
        before_mounts, after_mounts
    )
    checks.append(
        {
            "name": "container_mounts.validation_boundary",
            "passed": mount_transition_ok,
            "before": before_mounts,
            "after": after_mounts,
        }
    )
    for key in ("data", "secure_deposit"):
        before_mount = before.get("mounts", {}).get(key, {})
        after_mount = after.get("mounts", {}).get(key, {})
        for field in (
            "source",
            "normalized_source",
            "expected_source",
            "source_matches_expected",
            "target",
            "fstype",
            "device_id",
        ):
            check(
                f"mounts.{key}.{field}", before_mount.get(field), after_mount.get(field)
            )
    failed = [item["name"] for item in checks if not item["passed"]]
    return {
        "schema_version": 1,
        "profile": EXACT_COMPARISON_PROFILE,
        "result": "passed" if not failed else "failed",
        "failed_checks": failed,
        "checks": checks,
    }


def compare_canary_snapshots(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    """Prove preservation of every object while permitting only new objects."""

    _validate_snapshot_shape(before, label="before")
    _validate_snapshot_shape(after, label="after")
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, left: Any, right: Any) -> None:
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "before": left,
                "after": right,
            }
        )

    def exact(name: str, left: Any, right: Any) -> None:
        check(name, left == right, left, right)

    exact(
        "secure_deposit.aggregate",
        before.get("secure_deposit"),
        after.get("secure_deposit"),
    )
    exact(
        "object_store_bindings",
        before.get("object_store_bindings"),
        after.get("object_store_bindings"),
    )
    exact("faiss", before.get("faiss"), after.get("faiss"))
    exact("qdrant.inventory", before.get("qdrant"), after.get("qdrant"))
    exact(
        "container_mounts",
        before.get("container_mounts"),
        after.get("container_mounts"),
    )
    for key in ("data", "secure_deposit"):
        before_mount = before.get("mounts", {}).get(key, {})
        after_mount = after.get("mounts", {}).get(key, {})
        for field in (
            "source",
            "normalized_source",
            "expected_source",
            "source_matches_expected",
            "target",
            "fstype",
            "device_id",
        ):
            exact(
                f"mounts.{key}.{field}",
                before_mount.get(field),
                after_mount.get(field),
            )

    before_object = before["object_store"]
    after_object = after["object_store"]
    for field in ("algorithm", "entry_fields"):
        exact(
            f"object_store.{field}", before_object.get(field), after_object.get(field)
        )
    before_object_entries = {
        entry["path_sha256"]: entry for entry in before_object["entries"]
    }
    after_object_entries = {
        entry["path_sha256"]: entry for entry in after_object["entries"]
    }
    object_deletions = [
        entry
        for identity, entry in before_object_entries.items()
        if identity not in after_object_entries
    ]
    object_modifications = [
        [
            identity,
            _canonical_json_sha256(entry),
            _canonical_json_sha256(after_object_entries[identity]),
        ]
        for identity, entry in before_object_entries.items()
        if identity in after_object_entries and after_object_entries[identity] != entry
    ]
    object_entries_preserved = not object_deletions and not object_modifications
    check(
        "object_store.preexisting_entries_preserved",
        object_entries_preserved,
        len(before_object_entries),
        len(before_object_entries) - len(object_deletions) - len(object_modifications),
    )
    object_additions = [
        entry
        for identity, entry in after_object_entries.items()
        if identity not in before_object_entries
    ]

    before_minio = before["minio"]
    after_minio = after["minio"]
    for field in (
        "bucket_id_sha256",
        "versioning_status",
        "algorithm",
        "entry_fields",
    ):
        exact(f"minio.{field}", before_minio.get(field), after_minio.get(field))
    before_minio_entries = {
        (entry[0], entry[1]): entry for entry in before_minio["entries"]
    }
    after_minio_entries = {
        (entry[0], entry[1]): entry for entry in after_minio["entries"]
    }
    minio_deletions = [
        entry
        for identity, entry in before_minio_entries.items()
        if identity not in after_minio_entries
    ]
    minio_modifications = [
        [
            identity[0],
            identity[1],
            _canonical_json_sha256(entry),
            _canonical_json_sha256(after_minio_entries[identity]),
        ]
        for identity, entry in before_minio_entries.items()
        if identity in after_minio_entries and after_minio_entries[identity] != entry
    ]
    minio_entries_preserved = not minio_deletions and not minio_modifications
    check(
        "minio.preexisting_entries_preserved",
        minio_entries_preserved,
        len(before_minio_entries),
        len(before_minio_entries) - len(minio_deletions) - len(minio_modifications),
    )
    minio_additions = [
        entry
        for identity, entry in after_minio_entries.items()
        if identity not in before_minio_entries
    ]
    before_minio_object_ids = {entry[0] for entry in before_minio["entries"]}
    reversioned_object_ids = sorted(
        {entry[0] for entry in minio_additions if entry[0] in before_minio_object_ids}
    )
    check(
        "minio.preexisting_object_keys_not_reversioned",
        not reversioned_object_ids,
        0,
        len(reversioned_object_ids),
    )
    no_delete_marker_additions = not any(entry[6] for entry in minio_additions)
    check(
        "minio.no_delete_marker_additions",
        no_delete_marker_additions,
        before_minio.get("delete_markers"),
        after_minio.get("delete_markers"),
    )
    exact(
        "minio.delete_markers_unchanged",
        before_minio.get("delete_markers"),
        after_minio.get("delete_markers"),
    )

    def entries_summary(
        entries: Sequence[Any],
        *,
        entry_fields: Sequence[str],
        size: Any,
    ) -> dict[str, Any]:
        normalized_entries = sorted(entries, key=_canonical_json_sha256)
        return {
            "count": len(entries),
            "bytes": sum(size(entry) for entry in entries),
            "entry_fields": list(entry_fields),
            "entries": normalized_entries,
            "digest": _canonical_json_sha256(normalized_entries),
        }

    additions = {
        "object_store": entries_summary(
            object_additions,
            entry_fields=before_object["entry_fields"],
            size=lambda entry: entry["size"],
        ),
        "minio": entries_summary(
            minio_additions,
            entry_fields=before_minio["entry_fields"],
            size=lambda entry: 0 if entry[6] else entry[2],
        ),
    }
    deletions = {
        "object_store": entries_summary(
            object_deletions,
            entry_fields=before_object["entry_fields"],
            size=lambda entry: entry["size"],
        ),
        "minio": entries_summary(
            minio_deletions,
            entry_fields=before_minio["entry_fields"],
            size=lambda entry: 0 if entry[6] else entry[2],
        ),
    }

    def modifications_summary(
        entries: Sequence[Any], *, entry_fields: Sequence[str]
    ) -> dict[str, Any]:
        normalized_entries = sorted(entries, key=_canonical_json_sha256)
        return {
            "count": len(entries),
            "entry_fields": list(entry_fields),
            "entries": normalized_entries,
            "digest": _canonical_json_sha256(normalized_entries),
        }

    modifications = {
        "object_store": modifications_summary(
            object_modifications,
            entry_fields=("path_sha256", "before_entry_sha256", "after_entry_sha256"),
        ),
        "minio": modifications_summary(
            minio_modifications,
            entry_fields=(
                "object_id_sha256",
                "version_id_sha256",
                "before_entry_sha256",
                "after_entry_sha256",
            ),
        ),
    }

    failed = [item["name"] for item in checks if not item["passed"]]
    return {
        "schema_version": 1,
        "profile": ADDITIONS_COMPARISON_PROFILE,
        "assurance": "cryptographic_entry_inclusion",
        "result": "passed" if not failed else "failed",
        "failed_checks": failed,
        "checks": checks,
        "additions": additions,
        "deletions": deletions,
        "modifications": modifications,
    }


def compare_release_a_versioning_adoption(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    """Allow only the one-way unversioned -> enabled MinIO control change.

    Every object/version entry, Qdrant collection, Secure Deposit aggregate,
    FAISS artifact, local ObjectStore entry and mount identity remains subject
    to the exact comparator.  Unlike the canary comparator, this gate never
    permits an object addition.
    """

    before_copy = json.loads(json.dumps(before))
    after_copy = json.loads(json.dumps(after))
    before_status = before_copy.get("minio", {}).get("versioning_status")
    after_status = after_copy.get("minio", {}).get("versioning_status")
    if before_status not in {"unversioned", "enabled"} or after_status != "enabled":
        raise StorageAttestationError(
            "Release A MinIO versioning transition is not one-way to enabled"
        )
    # Shape validation and the exact comparison intentionally know only the
    # steady-state enabled contract. Normalize the sole authorized control
    # field, then retain the observed transition as a separate closed check.
    before_copy["minio"]["versioning_status"] = "enabled"
    result = compare_snapshots(before_copy, after_copy)
    transition = {
        "name": "minio.versioning_release_a_transition",
        "passed": True,
        "before": before_status,
        "after": after_status,
    }
    checks = [transition, *result["checks"]]
    failed = [item["name"] for item in checks if not item["passed"]]
    return {
        "schema_version": 1,
        "profile": "agentium-storage-release-a-versioning-comparison-v1",
        "result": "passed" if not failed else "failed",
        "failed_checks": failed,
        "checks": checks,
    }


def compare_release_a_opening_transition(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    """Allow only the declared application bind RO -> historical RW opening."""

    _validate_snapshot_shape(before, label="before")
    _validate_snapshot_shape(after, label="after")
    before_copy = json.loads(json.dumps(before))
    after_copy = json.loads(json.dumps(after))
    transition_ok = _validation_mount_transition_allowed(
        after_copy["container_mounts"], before_copy["container_mounts"]
    )
    after_copy["container_mounts"] = before_copy["container_mounts"]
    result = compare_snapshots(before_copy, after_copy)
    transition = {
        "name": "container_mounts.release_a_opening_transition",
        "passed": transition_ok,
        "before": "validation_read_only",
        "after": "historical_read_write",
    }
    checks = [transition, *result["checks"]]
    failed = [item["name"] for item in checks if not item["passed"]]
    return {
        "schema_version": 1,
        "profile": "agentium-storage-release-a-opening-comparison-v1",
        "result": "passed" if not failed else "failed",
        "failed_checks": failed,
        "checks": checks,
    }


def _load(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageAttestationError(f"cannot load attestation: {path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise StorageAttestationError(f"unsupported attestation: {path}")
    return value


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, separators=(",", ":"), sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(
            path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument("--secure-deposit", type=Path, required=True)
    snapshot.add_argument("--data-root", type=Path, required=True)
    snapshot.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    snapshot.add_argument("--qdrant-env", type=Path, required=True)
    snapshot.add_argument(
        "--object-store",
        type=Path,
        help="Local ObjectStore root (defaults to <data-root>/object_store)",
    )
    snapshot.add_argument(
        "--minio-url",
        default=os.environ.get("AGENTIUM_MINIO_ATTESTATION_URL", DEFAULT_MINIO_URL),
    )
    snapshot.add_argument(
        "--minio-bucket",
        default=os.environ.get("AGENTIUM_MINIO_BUCKET", DEFAULT_MINIO_BUCKET),
    )
    snapshot.add_argument(
        "--minio-env",
        type=Path,
        help="Optional root-only env file; otherwise credentials come from Docker inspect",
    )
    snapshot.add_argument(
        "--expected-data-source",
        default=os.environ.get(
            "AGENTIUM_SAFE_EXPECTED_DATA_SOURCE", DEFAULT_DATA_SOURCE
        ),
    )
    snapshot.add_argument(
        "--expected-secure-deposit-source",
        default=os.environ.get(
            "AGENTIUM_SAFE_EXPECTED_SECURE_SOURCE",
            DEFAULT_SECURE_DEPOSIT_SOURCE,
        ),
    )
    snapshot.add_argument(
        "--container",
        action="append",
        default=["agentium-pg", "qdrant", "agentium-minio", "agentium-sftp"],
    )
    snapshot.add_argument(
        "--allow-unversioned-release-a-baseline",
        action="store_true",
        help="Capture a pre-adoption unversioned inventory; never valid as an output gate",
    )
    compare = subparsers.add_parser("compare")
    compare.add_argument("--before", type=Path, required=True)
    compare.add_argument("--after", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument(
        "--allow-object-additions",
        action="store_true",
        help="Permit only cryptographically proven new ObjectStore/MinIO entries",
    )
    compare.add_argument(
        "--release-a-versioning-adoption",
        action="store_true",
        help="Allow only unversioned->enabled while requiring exact data equality",
    )
    compare.add_argument(
        "--release-a-opening-transition",
        action="store_true",
        help="Allow only application bind RO->historical RW at the opening boundary",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            value = capture_snapshot(
                secure_deposit=args.secure_deposit,
                data_root=args.data_root,
                qdrant_url=args.qdrant_url,
                qdrant_env=args.qdrant_env,
                containers=args.container,
                object_store=args.object_store,
                minio_url=args.minio_url,
                minio_bucket=args.minio_bucket,
                minio_env=args.minio_env,
                expected_data_source=args.expected_data_source,
                expected_secure_deposit_source=args.expected_secure_deposit_source,
                require_minio_versioning=not args.allow_unversioned_release_a_baseline,
            )
        elif args.command == "compare":
            modes = sum(
                map(
                    int,
                    (
                        args.allow_object_additions,
                        args.release_a_versioning_adoption,
                        args.release_a_opening_transition,
                    ),
                )
            )
            if modes > 1:
                raise StorageAttestationError("comparison modes are mutually exclusive")
            if args.release_a_opening_transition:
                comparator = compare_release_a_opening_transition
            elif args.release_a_versioning_adoption:
                comparator = compare_release_a_versioning_adoption
            elif args.allow_object_additions:
                comparator = compare_canary_snapshots
            else:
                comparator = compare_snapshots
            value = comparator(_load(args.before), _load(args.after))
        else:  # pragma: no cover - argparse rejects unknown commands.
            raise StorageAttestationError("unsupported storage attestation command")
        _write_atomic(args.output, value)
    except StorageAttestationError as exc:
        print(f"XX  {exc}", file=sys.stderr)
        return 1
    if value.get("result") == "failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
