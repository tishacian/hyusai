"""Resolve collection documents backed by immutable Secure Deposit sources.

Knowledge collections historically copy every original into their object-store
``original/`` prefix.  Large governed corpora can instead keep the received
Secure Deposit object as the immutable original and persist a small
``source_locator`` in the collection document manifest.  This module is the
single validation boundary used by workers and preview/download endpoints.

Supported locator shapes::

    {"kind": "secure_deposit_file", "deposit_file_id": "...", ...}
    {"kind": "secure_deposit_zip_member", "deposit_file_id": "...",
     "member_path": "manual/chapter.pdf", ...}

The database row remains authoritative for workspace ownership and the storage
path.  Locator hashes/sizes are assertions, never paths supplied by a client.
"""
from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.secure_deposit import DepositFile

SECURE_DEPOSIT_FILE = "secure_deposit_file"
SECURE_DEPOSIT_ZIP_MEMBER = "secure_deposit_zip_member"
_SUPPORTED_KINDS = {SECURE_DEPOSIT_FILE, SECURE_DEPOSIT_ZIP_MEMBER}
_ZIP_MEMBER_MAX_BYTES = 512 * 1024 * 1024
_ZIP_MEMBER_MAX_RATIO = 500.0


class SourceBackingError(ValueError):
    """A source locator is invalid, stale, unsafe, or no longer readable."""


def _staged_file_path(row: DepositFile) -> Path:
    # Lazy import avoids secure_deposit -> worker_dispatch -> worker_ingest ->
    # source_backing import cycles during Celery/API module initialisation.
    from app.services.secure_deposit import staged_file_path

    return staged_file_path(row)


def source_locator(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Return a normalised supported locator from document metadata."""
    if not isinstance(metadata, Mapping) or "source_locator" not in metadata:
        return None
    raw = metadata.get("source_locator")
    if not isinstance(raw, Mapping):
        raise SourceBackingError("invalid_secure_deposit_source_locator")
    kind = str(raw.get("kind") or "").strip()
    deposit_file_id = str(raw.get("deposit_file_id") or "").strip()
    if kind not in _SUPPORTED_KINDS or not deposit_file_id:
        raise SourceBackingError("invalid_secure_deposit_source_locator")
    locator = {str(key): value for key, value in raw.items()}
    locator["kind"] = kind
    locator["deposit_file_id"] = deposit_file_id
    return locator


def _load_deposit_file(
    db: DBSession,
    *,
    workspace_id: str,
    locator: Mapping[str, Any],
    expected_worker_job_id: str | None = None,
    expected_collection_slug: str | None = None,
    allowed_statuses: set[str] | frozenset[str] | None = None,
) -> DepositFile:
    deposit_file_id = str(locator.get("deposit_file_id") or "").strip()
    row = (
        db.query(DepositFile)
        .filter(
            DepositFile.id == deposit_file_id,
            DepositFile.workspace_id == str(workspace_id),
        )
        .first()
    )
    if not row:
        raise SourceBackingError("secure_deposit_source_not_found")

    status = str(row.status or "")
    if allowed_statuses is not None and status not in allowed_statuses:
        raise SourceBackingError("secure_deposit_source_status_invalid")
    if expected_worker_job_id is not None and str(row.worker_job_id or "") != str(
        expected_worker_job_id
    ):
        raise SourceBackingError("secure_deposit_source_job_mismatch")
    assigned_collection = str(row.promoted_collection_slug or "").strip()
    if (
        expected_collection_slug is not None
        and assigned_collection
        and assigned_collection != str(expected_collection_slug)
    ):
        raise SourceBackingError("secure_deposit_source_collection_mismatch")

    expected_sha = str(locator.get("sha256") or "").strip().lower()
    actual_sha = str(row.sha256 or "").strip().lower()
    if expected_sha and actual_sha != expected_sha:
        raise SourceBackingError("secure_deposit_source_sha_mismatch")

    expected_size = locator.get("size_bytes")
    if expected_size not in (None, ""):
        try:
            if int(expected_size) != int(row.size_bytes or 0):
                raise SourceBackingError("secure_deposit_source_size_mismatch")
        except (TypeError, ValueError) as exc:
            raise SourceBackingError("secure_deposit_source_size_invalid") from exc

    return row


def _validate_staged_source(
    row: DepositFile,
    locator: Mapping[str, Any],
) -> Path:
    """Resolve the immutable staged object and validate its physical size.

    The database row is authoritative for ownership and path selection, but a
    bind mount can still be truncated or replaced underneath a long-running
    worker.  Checking the actual stat here makes every consumer fail closed
    before it parses or serves the object.  The worker/read paths additionally
    verify the content digest below.
    """

    source = _staged_file_path(row)
    try:
        actual_size = int(source.stat().st_size)
    except OSError as exc:
        raise SourceBackingError("secure_deposit_source_unreadable") from exc
    expected_size = int(row.size_bytes or 0)
    locator_size = locator.get("size_bytes")
    if locator_size not in (None, ""):
        try:
            expected_size = int(locator_size)
        except (TypeError, ValueError) as exc:
            raise SourceBackingError("secure_deposit_source_size_invalid") from exc
    if actual_size != expected_size:
        raise SourceBackingError("secure_deposit_source_physical_size_mismatch")
    return source


def _verify_digest(data: bytes, expected: Any, *, error: str) -> None:
    digest = str(expected or "").strip().lower()
    if digest and hashlib.sha256(data).hexdigest() != digest:
        raise SourceBackingError(error)


@lru_cache(maxsize=512)
def _physical_sha256(
    path: str,
    size: int,
    mtime_ns: int,
    ctime_ns: int,
    inode: int,
) -> str:
    """Hash an immutable mounted source once per physical file revision."""

    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_physical_source_digest(
    source: Path,
    locator: Mapping[str, Any],
    row: DepositFile,
) -> None:
    expected = str(locator.get("sha256") or row.sha256 or "").strip().lower()
    if not expected:
        return
    try:
        stat_result = source.stat()
        actual = _physical_sha256(
            str(source),
            int(stat_result.st_size),
            int(stat_result.st_mtime_ns),
            int(stat_result.st_ctime_ns),
            int(stat_result.st_ino),
        )
    except OSError as exc:
        raise SourceBackingError("secure_deposit_source_unreadable") from exc
    if actual != expected:
        raise SourceBackingError("secure_deposit_source_content_changed")


def _safe_member_path(raw: Any) -> PurePosixPath:
    value = str(raw or "")
    if "\\" in value or "//" in value or value != value.strip():
        raise SourceBackingError("unsafe_secure_deposit_zip_member")
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(part in {"", ".", ".."} or ":" in part for part in path.parts)
        or path.as_posix() != value
    ):
        raise SourceBackingError("unsafe_secure_deposit_zip_member")
    return path


def _zip_member_info(archive: zipfile.ZipFile, locator: Mapping[str, Any]) -> zipfile.ZipInfo:
    member_path = _safe_member_path(locator.get("member_path"))
    try:
        info = archive.getinfo(member_path.as_posix())
    except KeyError as exc:
        raise SourceBackingError("secure_deposit_zip_member_not_found") from exc
    if info.is_dir() or info.flag_bits & 0x1:
        raise SourceBackingError("secure_deposit_zip_member_not_readable")
    if int(info.file_size or 0) > _ZIP_MEMBER_MAX_BYTES:
        raise SourceBackingError("secure_deposit_zip_member_too_large")
    compressed = max(1, int(info.compress_size or 0))
    if int(info.file_size or 0) / compressed > _ZIP_MEMBER_MAX_RATIO:
        raise SourceBackingError("secure_deposit_zip_member_ratio_exceeded")
    expected_size = locator.get("member_size_bytes")
    if expected_size not in (None, "") and int(expected_size) != int(info.file_size or 0):
        raise SourceBackingError("secure_deposit_zip_member_size_mismatch")
    return info


def backing_source_meta(
    db: DBSession,
    *,
    workspace_id: str,
    locator: Mapping[str, Any],
    expected_collection_slug: str | None = None,
    allowed_statuses: set[str] | frozenset[str] | None = None,
) -> tuple[bool, int]:
    """Resolve existence and logical byte size without loading source bytes."""
    try:
        row = _load_deposit_file(
            db,
            workspace_id=workspace_id,
            locator=locator,
            expected_collection_slug=expected_collection_slug,
            allowed_statuses=allowed_statuses,
        )
        source = _validate_staged_source(row, locator)
        if str(locator.get("kind") or "") == SECURE_DEPOSIT_FILE:
            return True, int(source.stat().st_size)
        with zipfile.ZipFile(source, "r") as archive:
            info = _zip_member_info(archive, locator)
            return True, int(info.file_size or 0)
    except (OSError, zipfile.BadZipFile, SourceBackingError):
        return False, 0


def read_backing_source_bytes(
    db: DBSession,
    *,
    workspace_id: str,
    locator: Mapping[str, Any],
    expected_collection_slug: str | None = None,
    allowed_statuses: set[str] | frozenset[str] | None = None,
) -> bytes:
    """Read direct source or one validated ZIP member for preview/download."""
    row = _load_deposit_file(
        db,
        workspace_id=workspace_id,
        locator=locator,
        expected_collection_slug=expected_collection_slug,
        allowed_statuses=allowed_statuses,
    )
    source = _validate_staged_source(row, locator)
    if str(locator.get("kind") or "") == SECURE_DEPOSIT_FILE:
        try:
            data = source.read_bytes()
        except OSError as exc:
            raise SourceBackingError("secure_deposit_source_unreadable") from exc
        _verify_digest(
            data,
            locator.get("sha256") or row.sha256,
            error="secure_deposit_source_content_changed",
        )
        return data
    _verify_physical_source_digest(source, locator, row)
    with zipfile.ZipFile(source, "r") as archive:
        info = _zip_member_info(archive, locator)
        data = archive.read(info)
        _verify_digest(
            data,
            locator.get("member_sha256"),
            error="secure_deposit_zip_member_sha_mismatch",
        )
        return data


def materialize_backing_source(
    db: DBSession,
    *,
    workspace_id: str,
    locator: Mapping[str, Any],
    destination: Path,
    verify_direct_digest: bool = False,
    expected_worker_job_id: str | None = None,
    expected_collection_slug: str | None = None,
    allowed_statuses: set[str] | frozenset[str] | None = None,
) -> Path:
    """Expose a source at ``destination`` for parsers without persistent copy.

    Direct files use a symlink into the worker's read-only Secure Deposit mount.
    A ZIP member must be streamed into the bounded job temp directory.
    """
    row = _load_deposit_file(
        db,
        workspace_id=workspace_id,
        locator=locator,
        expected_worker_job_id=expected_worker_job_id,
        expected_collection_slug=expected_collection_slug,
        allowed_statuses=allowed_statuses,
    )
    source = _validate_staged_source(row, locator)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    if str(locator.get("kind") or "") == SECURE_DEPOSIT_FILE:
        if verify_direct_digest:
            _verify_physical_source_digest(source, locator, row)
        destination.symlink_to(source)
        return destination

    _verify_physical_source_digest(source, locator, row)
    with zipfile.ZipFile(source, "r") as archive:
        info = _zip_member_info(archive, locator)
        digest = hashlib.sha256()
        with archive.open(info, "r") as reader, destination.open("wb") as writer:
            while True:
                block = reader.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                writer.write(block)
        expected_member_sha = str(locator.get("member_sha256") or "").strip().lower()
        if expected_member_sha and digest.hexdigest() != expected_member_sha:
            destination.unlink(missing_ok=True)
            raise SourceBackingError("secure_deposit_zip_member_sha_mismatch")
    return destination


def copy_or_materialize_collection_source(
    db: DBSession,
    *,
    workspace_id: str,
    metadata: Mapping[str, Any] | None,
    destination: Path,
    copy_object_store_source,
    expected_worker_job_id: str | None = None,
    expected_collection_slug: str | None = None,
    allowed_statuses: set[str] | frozenset[str] | None = None,
) -> Path:
    """Use source backing when present, otherwise invoke legacy copy callback."""
    # A present-but-malformed governed locator is never a licence to fall back
    # to a same-named object-store original.  Such a fallback could silently
    # index stale or cross-provenance bytes.
    locator = source_locator(metadata)
    if locator is not None:
        return materialize_backing_source(
            db,
            workspace_id=workspace_id,
            locator=locator,
            destination=destination,
            expected_worker_job_id=expected_worker_job_id,
            expected_collection_slug=expected_collection_slug,
            allowed_statuses=allowed_statuses,
        )
    copy_object_store_source(destination)
    return destination
