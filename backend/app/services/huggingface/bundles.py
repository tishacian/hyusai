"""Stream verified, signed offline artifacts without contacting the Hub.

The wire format is an uncompressed USTAR archive: ``manifest.json``, then
``attestation.json``, then exactly ``files/<path>`` for the durable files.
All bundles require a trusted signature, including public repositories: otherwise
an attacker could remove the private/gated flags or replace license evidence.

This module does not create workspace grants. The caller must apply the same
compatibility, quota and license policy as online imports and create a grant
only after ``import_bundle`` succeeds. Export callers must discard the output
on failure; an output stream may already contain partial bytes.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
from collections.abc import Callable, Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .errors import HFError

_CHUNK_SIZE = 1024 * 1024
_METADATA_LIMIT = 4 * 1024 * 1024
_MAX_FILES = 10_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_CONTEXT = b"agentium-huggingface-offline-bundle-v1\x00"


def _fail(message: str, *, code: str = "HF_BUNDLE_INVALID") -> HFError:
    return HFError(code, message)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise _fail("Bundle metadata must be canonical JSON") from exc


def _json_object(data: bytes) -> dict:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise _fail("Bundle metadata contains duplicate keys")
            result[key] = value
        return result

    try:
        result = json.loads(data, object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise _fail("Bundle metadata is not valid JSON") from exc
    if not isinstance(result, dict):
        raise _fail("Bundle metadata must be a JSON object")
    # Reject non-finite numbers accepted by Python's JSON decoder.
    _canonical(result)
    return result


def _safe_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise _fail("Bundle contains an unsafe file path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or ":" in parts[0]:
        raise _fail("Bundle contains an unsafe file path")
    return value


def durable_files(manifest: Mapping) -> dict[str, dict]:
    """Return the exact retained bytes, excluding temporary dataset sources.

    Datasets retain a single ``dataset_result`` with ``path``, ``size_bytes``
    and ``sha256``. A ``files`` mapping inside ``dataset_result`` also supports
    sharded materializations. Models use the top-level ``files`` mapping.
    """
    if not isinstance(manifest.get("artifact_id"), str) or not manifest["artifact_id"]:
        raise _fail("Bundle manifest has no artifact identity")
    for flag in ("private", "gated"):
        if flag in manifest and not isinstance(manifest[flag], bool):
            raise _fail("Bundle access flags must be booleans")
    if manifest.get("kind") == "dataset":
        result = manifest.get("dataset_result")
        if not isinstance(result, Mapping):
            raise _fail("Dataset bundles require the retained dataset result")
        entries = result.get("files")
        if entries is None:
            entries = {result.get("path", "dataset/result.parquet"): result}
    else:
        entries = manifest.get("files")
    if not isinstance(entries, Mapping) or not entries or len(entries) > _MAX_FILES:
        raise _fail("Bundle manifest has an invalid durable file set")
    files = {}
    for path, entry in entries.items():
        path = _safe_path(path)
        if not isinstance(entry, Mapping):
            raise _fail("Bundle file metadata must be an object")
        size, digest = entry.get("size_bytes"), entry.get("sha256")
        if type(size) is not int or size < 0:
            raise _fail("Bundle file size must be a non-negative integer")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise _fail("Bundle file SHA-256 is missing or invalid")
        # A file cannot also be the parent directory of another file.
        files[path] = {"size_bytes": size, "sha256": digest}
    paths = set(files)
    for path in paths:
        parts = path.split("/")
        if any("/".join(parts[:n]) in paths for n in range(1, len(parts))):
            raise _fail("Bundle file paths overlap")
    return files


def _check_license_digest(manifest: Mapping, digest: Any) -> str:
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise _fail("Bundle license evidence requires a SHA-256 digest")
    if manifest.get("license_digest") not in (None, digest):
        raise _fail("Bundle license evidence does not match the manifest")
    text = manifest.get("license_text")
    if text is not None:
        from .policy import license_digest

        if not isinstance(text, str) or license_digest(dict(manifest), text) != digest:
            raise _fail("Bundle license text does not match its digest")
    return digest


def _utc(value: datetime | None) -> datetime:
    value = value or datetime.now(UTC)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _fail("Bundle timestamps must include a timezone")
    return value.astimezone(UTC)


def _private_key(key: Ed25519PrivateKey | bytes) -> Ed25519PrivateKey:
    if isinstance(key, Ed25519PrivateKey):
        return key
    try:
        parsed = (
            serialization.load_pem_private_key(key, password=None)
            if key.startswith(b"-----BEGIN")
            else Ed25519PrivateKey.from_private_bytes(key)
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise _fail("Bundle exporter has an invalid signing key") from exc
    if not isinstance(parsed, Ed25519PrivateKey):
        raise _fail("Bundle exporter requires an Ed25519 signing key")
    return parsed


def _public_key(key: Ed25519PublicKey | bytes) -> Ed25519PublicKey:
    if isinstance(key, Ed25519PublicKey):
        return key
    try:
        parsed = (
            serialization.load_pem_public_key(key)
            if key.startswith(b"-----BEGIN")
            else Ed25519PublicKey.from_public_bytes(key)
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise _fail("Bundle exporter has an invalid trust key") from exc
    if not isinstance(parsed, Ed25519PublicKey):
        raise _fail("Bundle exporter requires an Ed25519 trust key")
    return parsed


def _attestation(
    manifest: dict,
    *,
    target_workspace_id: str,
    license_digest: str,
    key_id: str,
    signing_key: Ed25519PrivateKey | bytes,
    issued_at: datetime,
    expires_at: datetime,
) -> dict:
    if not target_workspace_id or not key_id or expires_at <= issued_at:
        raise _fail("Bundle attestation requires a workspace, exporter and future expiry")
    payload = {
        "version": 1,
        "workspace_id": target_workspace_id,
        "artifact_id": manifest["artifact_id"],
        "manifest_digest": hashlib.sha256(_canonical(manifest)).hexdigest(),
        "license_digest": _check_license_digest(manifest, license_digest),
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "key_id": key_id,
    }
    signature = _private_key(signing_key).sign(_SIGNATURE_CONTEXT + _canonical(payload))
    return {"payload": payload, "signature": base64.b64encode(signature).decode("ascii")}


def verify_attestation(
    attestation: Mapping,
    manifest: Mapping,
    *,
    target_workspace_id: str,
    trust_keys: Mapping[str, Ed25519PublicKey | bytes],
    now: datetime | None = None,
) -> str:
    """Verify scope and freshness; return the authenticated license digest."""
    payload = attestation.get("payload")
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise _fail(
            "Bundle access attestation is missing or unsupported", code="HF_BUNDLE_PROOF_INVALID"
        )
    key_id = payload.get("key_id")
    if not isinstance(key_id, str) or key_id not in trust_keys:
        raise _fail("Bundle exporter is not trusted", code="HF_BUNDLE_PROOF_INVALID")
    try:
        signature = base64.b64decode(attestation.get("signature", ""), validate=True)
        _public_key(trust_keys[key_id]).verify(signature, _SIGNATURE_CONTEXT + _canonical(payload))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise _fail("Bundle access signature is invalid", code="HF_BUNDLE_PROOF_INVALID") from exc
    if (
        not target_workspace_id
        or payload.get("workspace_id") != target_workspace_id
        or payload.get("artifact_id") != manifest.get("artifact_id")
        or payload.get("manifest_digest") != hashlib.sha256(_canonical(manifest)).hexdigest()
    ):
        raise _fail(
            "Bundle proof does not cover this workspace and artifact",
            code="HF_BUNDLE_PROOF_INVALID",
        )
    try:
        issued_at = _utc(datetime.fromisoformat(payload["issued_at"]))
        expires_at = _utc(datetime.fromisoformat(payload["expires_at"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise _fail("Bundle proof has invalid timestamps", code="HF_BUNDLE_PROOF_INVALID") from exc
    current = _utc(now)
    if issued_at > current or expires_at <= current or expires_at <= issued_at:
        raise _fail("Bundle proof is expired or not yet valid", code="HF_BUNDLE_PROOF_EXPIRED")
    return _check_license_digest(manifest, payload.get("license_digest"))


class _HashingReader:
    def __init__(self, source: BinaryIO):
        self.source = source
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        chunk = self.source.read(size)
        self.digest.update(chunk)
        return chunk


def export_bundle(
    destination: BinaryIO,
    *,
    manifest: Mapping,
    open_file: Callable[[str], BinaryIO],
    target_workspace_id: str,
    license_digest: str,
    signing_key: Ed25519PrivateKey | bytes,
    key_id: str,
    authorize: Callable[[dict, str], None],
    verify_hub_access: Callable[[dict, str], None] | None = None,
    expires_at: datetime | None = None,
    now: datetime | None = None,
    max_total_bytes: int = 20 * 1024**3,
    max_file_bytes: int = 20 * 1024**3,
) -> dict:
    """Write a signed bundle after current grant and restricted Hub checks.

    Authorization callbacks must raise on refusal. ``verify_hub_access`` must
    use the target workspace's own token, never a platform fallback. ``open_file``
    returns a fresh stream for a durable file path; this function closes it.
    """
    manifest = _json_object(_canonical(dict(manifest)))
    files = durable_files(manifest)
    if (
        type(max_total_bytes) is not int
        or type(max_file_bytes) is not int
        or min(max_total_bytes, max_file_bytes) < 0
        or sum(entry["size_bytes"] for entry in files.values()) > max_total_bytes
        or any(entry["size_bytes"] > max_file_bytes for entry in files.values())
    ):
        raise _fail("Bundle exceeds the configured export limits", code="HF_BUNDLE_TOO_LARGE")
    if not callable(authorize):
        raise _fail("Bundle export requires workspace authorization")
    if authorize(manifest, target_workspace_id) is False:
        raise _fail("Workspace is not authorized to export this artifact")
    if manifest.get("private") or manifest.get("gated"):
        if not callable(verify_hub_access):
            raise _fail("Restricted exports require a current target workspace Hub access check")
        if verify_hub_access(manifest, target_workspace_id) is False:
            raise _fail("Target workspace cannot access this restricted Hub repository")
    issued_at = _utc(now)
    proof = _attestation(
        manifest,
        target_workspace_id=str(target_workspace_id),
        license_digest=license_digest,
        key_id=key_id,
        signing_key=signing_key,
        issued_at=issued_at,
        expires_at=_utc(expires_at) if expires_at is not None else issued_at + timedelta(days=1),
    )
    with tarfile.open(fileobj=destination, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in (
            ("manifest.json", _canonical(manifest)),
            ("attestation.json", _canonical(proof)),
        ):
            if len(data) > _METADATA_LIMIT:
                raise _fail("Bundle metadata exceeds the size limit")
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o600
            archive.addfile(info, io.BytesIO(data))
        for path, entry in sorted(files.items()):
            info = tarfile.TarInfo(f"files/{path}")
            info.size, info.mode = entry["size_bytes"], 0o600
            with closing(open_file(path)) as source:
                reader = _HashingReader(source)
                archive.addfile(info, reader)
                if source.read(1) or reader.digest.hexdigest() != entry["sha256"]:
                    raise _fail(
                        "Artifact content differs from its immutable manifest",
                        code="HF_BUNDLE_CONTENT_MISMATCH",
                    )
    return proof


def _read_exact(source: BinaryIO, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        part = source.read(size - len(chunks))
        if not part:
            raise _fail("Bundle archive is truncated")
        chunks.extend(part)
    return bytes(chunks)


def _header(source: BinaryIO) -> tarfile.TarInfo | None:
    block = _read_exact(source, tarfile.BLOCKSIZE)
    if block == bytes(tarfile.BLOCKSIZE):
        if _read_exact(source, tarfile.BLOCKSIZE) != bytes(tarfile.BLOCKSIZE):
            raise _fail("Bundle archive has an invalid end marker")
        # USTAR writers may pad their last 10 KiB record. Reject concatenated
        # archives and all hidden payload after the first end marker.
        remaining = tarfile.RECORDSIZE
        while remaining:
            padding = source.read(min(remaining, _CHUNK_SIZE))
            if not padding:
                return None
            if any(padding):
                raise _fail("Bundle contains trailing payload")
            remaining -= len(padding)
        if source.read(1):
            raise _fail("Bundle has excessive trailing padding")
        return None
    try:
        info = tarfile.TarInfo.frombuf(block, "utf-8", "strict")
    except (tarfile.HeaderError, UnicodeError, ValueError) as exc:
        raise _fail("Bundle is not a valid uncompressed USTAR archive") from exc
    if info.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or info.size < 0:
        raise _fail("Bundle permits only regular files, without archive extensions")
    _safe_path(info.name)
    return info


def _padding(source: BinaryIO, size: int) -> None:
    padding = (tarfile.BLOCKSIZE - size % tarfile.BLOCKSIZE) % tarfile.BLOCKSIZE
    if padding and any(_read_exact(source, padding)):
        raise _fail("Bundle file padding contains unexpected content")


def _metadata(source: BinaryIO, name: str) -> dict:
    info = _header(source)
    if info is None or info.name != name or info.size > _METADATA_LIMIT:
        raise _fail(f"Bundle must contain bounded {name} metadata first")
    result = _json_object(_read_exact(source, info.size))
    _padding(source, info.size)
    return result


def import_bundle(
    source: BinaryIO,
    *,
    destination_dir: Path | str,
    target_workspace_id: str,
    trust_keys: Mapping[str, Ed25519PublicKey | bytes],
    accept_license: Callable[[dict, str], bool],
    max_total_bytes: int,
    max_file_bytes: int,
    now: datetime | None = None,
) -> dict:
    """Verify a stream and publish its directory only after license acceptance.

    The destination must not exist. Byte limits apply to durable files and are
    enforced from signed metadata before extraction, then again for every tar
    header. The callback must return ``True`` only after policy verification and
    recorded acceptance for the target workspace. It must not create a grant.
    """
    if not callable(accept_license):
        raise _fail("Offline import requires workspace license acceptance")
    if (
        type(max_total_bytes) is not int
        or type(max_file_bytes) is not int
        or min(max_total_bytes, max_file_bytes) < 0
    ):
        raise _fail("Offline import requires non-negative byte limits")
    manifest = _metadata(source, "manifest.json")
    files = durable_files(manifest)
    proof = _metadata(source, "attestation.json")
    license_digest = verify_attestation(
        proof,
        manifest,
        target_workspace_id=str(target_workspace_id),
        trust_keys=trust_keys,
        now=now,
    )
    total = sum(entry["size_bytes"] for entry in files.values())
    if total > max_total_bytes or any(
        entry["size_bytes"] > max_file_bytes for entry in files.values()
    ):
        raise _fail("Bundle exceeds the configured storage limits", code="HF_BUNDLE_TOO_LARGE")
    destination = Path(destination_dir)
    if destination.exists() or destination.is_symlink():
        raise _fail("Bundle destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".hf-bundle-", dir=destination.parent))
    try:
        seen = set()
        while (info := _header(source)) is not None:
            if not info.name.startswith("files/"):
                raise _fail("Bundle contains a file outside its declared file set")
            path = info.name[len("files/") :]
            if path not in files or path in seen:
                raise _fail("Bundle contains duplicate or undeclared files")
            entry = files[path]
            if info.size != entry["size_bytes"] or info.size > max_file_bytes:
                raise _fail(
                    "Bundle file size differs from its manifest", code="HF_BUNDLE_CONTENT_MISMATCH"
                )
            seen.add(path)
            output = staging / "files" / path
            output.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with output.open("xb") as target:
                remaining = info.size
                while remaining:
                    chunk = _read_exact(source, min(remaining, _CHUNK_SIZE))
                    target.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            _padding(source, info.size)
            if digest.hexdigest() != entry["sha256"]:
                raise _fail(
                    "Bundle file SHA-256 differs from its manifest",
                    code="HF_BUNDLE_CONTENT_MISMATCH",
                )
        if seen != set(files):
            raise _fail("Bundle is missing files declared by its manifest")
        if accept_license(manifest, license_digest) is not True:
            raise _fail(
                "Workspace license acceptance was not recorded",
                code="HF_LICENSE_ACCEPTANCE_REQUIRED",
            )
        (staging / "manifest.json").write_bytes(_canonical(manifest))
        # Keep bundle metadata outside the namespace of retained source files.
        os.rename(staging, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest
