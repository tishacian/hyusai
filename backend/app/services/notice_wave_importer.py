"""Controlled, incremental promotion of transverse Andritz notice sources.

Unlike the historical SPL importer, this service never copies Secure Deposit
originals into the collection object store.  It writes a small, canonical
manifest containing a validated ``secure_deposit_file`` locator and lets the
document worker materialise the source from its read-only deposit mount.

Planning is deliberately deterministic.  An operator must first inspect the
plan and then pass its exact SHA-256 hash to execution; a new upload or a
metadata change invalidates the approval instead of silently joining a wave.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import stat
import unicodedata
import zipfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.knowledge_collection import (
    KnowledgeCollection,
    KnowledgeCollectionSource,
    WorkerJob,
)
from app.models.secure_deposit import DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.knowledge_collections import (
    create_worker_job,
    document_manifest_key,
    update_job,
    upsert_collection_source,
)
from app.services.notice_wave_state import (
    NoticeWaveBaselineError,
    notice_wave_baseline,
    restore_notice_wave_baseline,
)
from app.services.object_store import get_object_store
from app.services.rag.project_references import derive_project_reference
from app.services.worker_dispatch import dispatch_worker_job

DEFAULT_NOTICE_COLLECTION = "andritz-notices-techniques-spl-pilot"
NEEDLEPUNCH_PREFIX = "Notices_Techniques_Needlepunch/"

MAX_SOURCES_PER_WAVE = 100
MAX_BYTES_PER_WAVE = 2 * 1024 * 1024 * 1024
# ``KnowledgeCollectionSource.size_bytes`` is a PostgreSQL INTEGER. Keep each
# individual source representable even though a wave's aggregate byte budget is
# expressed as 2 GiB.
MAX_SOURCE_SIZE_BYTES = (2**31) - 1
LARGE_SOURCE_BYTES = 100 * 1024 * 1024
MAX_LOGICAL_NAME_LENGTH = 220
MAX_ZIP_MEMBER_BYTES = 512 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 500.0
MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
MAX_ZIP_MEMBER_COUNT = 10_000
NOTICE_CAMPAIGNS = ("direct", "legacy", "zip")

_DIRECT_EXTENSIONS = frozenset(
    {
        "pdf",
        "doc",
        "docx",
        "html",
        "htm",
        "txt",
        "xlsx",
        "jpg",
        "jpeg",
        "png",
        "bmp",
        "tif",
        "tiff",
        "webp",
    }
)
_LEGACY_EXTENSIONS = frozenset({"xls"})
_UNVALIDATED_LEGACY_EXTENSIONS = frozenset({"ppt"})
_RANGE_RE = re.compile(r"^(\d{5})\s*-\s*(\d{5})$")
_SAFE_STEM_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class NoticePlanDriftError(ValueError):
    """Raised when execution no longer matches the operator-approved plan."""


@dataclass(frozen=True)
class NoticeSourceProfile:
    slug: str
    prefix: str
    direct_extensions: frozenset[str]


NOTICE_SOURCE_PROFILES: dict[str, NoticeSourceProfile] = {
    "needlepunch": NoticeSourceProfile(
        slug="needlepunch",
        prefix=NEEDLEPUNCH_PREFIX,
        direct_extensions=_DIRECT_EXTENSIONS,
    )
}


@dataclass(frozen=True)
class NoticeWaveItem:
    deposit_file_id: str
    filename: str
    size_bytes: int
    deposit_size_bytes: int
    sha256: str
    deposit_status: str
    content_type: str
    extension: str
    disposition: str
    reason: str | None
    logical_name: str | None
    member_path: str | None = None
    member_size_bytes: int | None = None
    member_sha256: str | None = None
    project_metadata: dict[str, str] = field(default_factory=dict)

    @property
    def deposit_identity(self) -> str:
        return f"{self.deposit_file_id}:{self.sha256.lower()}"

    @property
    def source_identity(self) -> str:
        if self.member_path:
            return (
                f"{self.deposit_identity}:{self.member_path}:"
                f"{str(self.member_sha256 or '').lower()}"
            )
        return self.deposit_identity

    @property
    def content_sha256(self) -> str:
        return str(self.member_sha256 or self.sha256 or "").lower()

    def canonical_dict(self) -> dict[str, Any]:
        """Hash input; mutable processing status is intentionally excluded."""

        return {
            "deposit_file_id": self.deposit_file_id,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "deposit_size_bytes": self.deposit_size_bytes,
            "sha256": self.sha256.lower(),
            "content_type": self.content_type,
            "extension": self.extension,
            "disposition": self.disposition,
            "reason": self.reason,
            "logical_name": self.logical_name,
            "member_path": self.member_path,
            "member_size_bytes": self.member_size_bytes,
            "member_sha256": (
                str(self.member_sha256).lower() if self.member_sha256 else None
            ),
            "project_metadata": dict(sorted(self.project_metadata.items())),
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.canonical_dict(), "deposit_status": self.deposit_status}


@dataclass(frozen=True)
class NoticeWave:
    index: int
    items: tuple[NoticeWaveItem, ...]

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "source_count": len(self.items),
            "total_bytes": self.total_bytes,
            "large_source_isolated": bool(
                len(self.items) == 1 and self.items[0].size_bytes > LARGE_SOURCE_BYTES
            ),
            "deposit_file_ids": [item.deposit_file_id for item in self.items],
            "document_names": [item.logical_name for item in self.items],
        }


@dataclass(frozen=True)
class NoticeWavePlan:
    workspace_id: str
    workspace_slug: str
    collection_slug: str
    profile_slug: str
    campaign: str
    source_prefix: str
    projects: tuple[str, ...]
    project_range: tuple[int, int] | None
    items: tuple[NoticeWaveItem, ...]
    waves: tuple[NoticeWave, ...]

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "workspace_id": self.workspace_id,
            "workspace_slug": self.workspace_slug,
            "collection_slug": self.collection_slug,
            "profile_slug": self.profile_slug,
            "campaign": self.campaign,
            "source_prefix": self.source_prefix,
            "projects": list(self.projects),
            "project_range": list(self.project_range) if self.project_range else None,
            "items": [item.canonical_dict() for item in self.items],
            "waves": [
                {
                    "index": wave.index,
                    "deposit_file_ids": [item.deposit_file_id for item in wave.items],
                }
                for wave in self.waves
            ],
        }

    @property
    def plan_hash(self) -> str:
        payload = json.dumps(
            self.canonical_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @property
    def disposition_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(item.disposition for item in self.items).items()))

    def as_dict(self, *, include_items: bool = True) -> dict[str, Any]:
        deposit_ids = {item.deposit_file_id for item in self.items}
        payload: dict[str, Any] = {
            "version": 1,
            "plan_hash": self.plan_hash,
            "workspace_slug": self.workspace_slug,
            "collection_slug": self.collection_slug,
            "profile_slug": self.profile_slug,
            "campaign": self.campaign,
            "source_prefix": self.source_prefix,
            "projects": list(self.projects),
            "project_range": (
                f"{self.project_range[0]:05d}-{self.project_range[1]:05d}"
                if self.project_range
                else None
            ),
            "source_count": len(self.items),
            "deposit_count": len(deposit_ids),
            "eligible_source_count": sum(
                1 for item in self.items if item.disposition == "eligible"
            ),
            "disposition_counts": self.disposition_counts,
            "wave_count": len(self.waves),
            "waves": [wave.as_dict() for wave in self.waves],
        }
        if include_items:
            payload["items"] = [item.as_dict() for item in self.items]
        return payload


def parse_project_range(value: str | tuple[int, int] | None) -> tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, tuple):
        lower, upper = int(value[0]), int(value[1])
    else:
        match = _RANGE_RE.fullmatch(str(value).strip())
        if not match:
            raise ValueError("project range must use the 60000-69999 form")
        lower, upper = int(match.group(1)), int(match.group(2))
    if lower > upper or lower < 0 or upper > 99999:
        raise ValueError("project range is invalid")
    return lower, upper


def _normalise_projects(projects: Iterable[str] | None) -> tuple[str, ...]:
    values = {str(value or "").strip() for value in projects or ()}
    if any(not re.fullmatch(r"\d{5}", value) for value in values):
        raise ValueError("Needlepunch project codes must contain exactly five digits")
    return tuple(sorted(values))


def _safe_like_prefix(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


def _normalise_source_prefix(
    value: str | None,
    *,
    profile: NoticeSourceProfile,
) -> str:
    """Return a safe SFTP prefix confined to the selected source profile.

    Operators may narrow a campaign to a range directory, but cannot make the
    Needlepunch profile scan another deposit tree.  Keeping the exact prefix in
    the canonical plan also means that changing the selector invalidates the
    dry-run approval hash.
    """

    raw = str(value or profile.prefix).strip().replace("\\", "/")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("source prefix must be a safe relative deposit path")
    normalised = "/".join(parts) + "/"
    root = profile.prefix.strip("/") + "/"
    if not normalised.casefold().startswith(root.casefold()):
        raise ValueError(f"source prefix must stay under {profile.prefix}")
    return normalised


def _source_range(filename: str, *, prefix: str) -> tuple[int, int] | None:
    parts = [part for part in str(filename or "").replace("\\", "/").split("/") if part]
    prefix_name = prefix.strip("/")
    try:
        prefix_index = next(
            index for index, part in enumerate(parts) if part.casefold() == prefix_name.casefold()
        )
    except StopIteration:
        return None
    if len(parts) <= prefix_index + 1:
        return None
    match = _RANGE_RE.fullmatch(parts[prefix_index + 1].strip())
    if not match:
        return None
    lower, upper = int(match.group(1)), int(match.group(2))
    return (lower, upper) if lower <= upper else None


def _selected(
    *,
    project_metadata: dict[str, str],
    filename: str,
    profile: NoticeSourceProfile,
    projects: tuple[str, ...],
    project_range: tuple[int, int] | None,
) -> bool:
    code = str(project_metadata.get("project_code") or "")
    if projects:
        return code in projects
    if project_range is None:
        return False
    if code.isdigit() and project_range[0] <= int(code) <= project_range[1]:
        return True
    # Preserve invalid-path files in broad range reports.  A malformed project
    # folder cannot be attributed to a narrow sub-range, but it must not vanish
    # when the operator audits an entire SFTP range directory.
    parent_range = _source_range(filename, prefix=profile.prefix)
    return bool(
        parent_range
        and project_range[0] <= parent_range[0]
        and parent_range[1] <= project_range[1]
    )


def logical_document_name(
    deposit_file: DepositFile,
    *,
    project_code: str,
    source_name: str | None = None,
    content_sha256: str | None = None,
) -> str:
    """Return a deterministic, collision-resistant name capped at 220 chars."""

    raw_name = str(source_name or deposit_file.filename or "source").replace("\\", "/")
    if source_name is None:
        leaf = PurePosixPath(raw_name).name
    else:
        # Retain member directory information to avoid collisions between
        # common names such as ``manual.pdf`` inside the same archive.
        leaf = "__".join(
            part for part in PurePosixPath(raw_name).parts if part not in {"/", ""}
        )
    suffix = PurePosixPath(leaf).suffix.lower()
    extension = suffix[1:] if suffix.startswith(".") else suffix
    raw_stem = leaf[: -len(suffix)] if suffix else leaf
    folded = unicodedata.normalize("NFKD", raw_stem)
    ascii_stem = "".join(char for char in folded if not unicodedata.combining(char))
    safe_stem = _SAFE_STEM_RE.sub("_", ascii_stem).strip("._-") or "document"
    id_token = re.sub(r"[^a-zA-Z0-9]", "", str(deposit_file.id or ""))[:8] or "source"
    hash_token = str(content_sha256 or deposit_file.sha256 or "").lower()[:12] or "nohash"
    prefix = f"needlepunch__{project_code}__"
    identity_token = hashlib.sha256(
        f"{deposit_file.id}\0{raw_name}\0{content_sha256 or deposit_file.sha256 or ''}".encode(
            "utf-8", errors="surrogatepass"
        )
    ).hexdigest()[:16]
    tail = f"__{id_token}-{hash_token}-{identity_token}"
    ext_tail = f".{extension}" if extension else ""
    stem_budget = MAX_LOGICAL_NAME_LENGTH - len(prefix) - len(tail) - len(ext_tail)
    safe_stem = safe_stem[: max(1, stem_budget)].rstrip("._-") or "d"
    result = f"{prefix}{safe_stem}{tail}{ext_tail}"
    if len(result) > MAX_LOGICAL_NAME_LENGTH:  # defensive for future prefix changes
        raise ValueError("logical document name exceeds safety bound")
    return result


def _classify_deposit(
    deposit_file: DepositFile,
    *,
    profile: NoticeSourceProfile,
    project_metadata: dict[str, str],
    campaign: str,
) -> list[NoticeWaveItem]:
    extension = PurePosixPath(str(deposit_file.filename or "")).suffix.lower().lstrip(".")
    status = str(deposit_file.status or "")
    size_bytes = max(0, int(deposit_file.size_bytes or 0))
    disposition = "eligible"
    reason: str | None = None
    logical_name: str | None = None

    if not project_metadata:
        disposition, reason = "unsupported", "invalid_needlepunch_project_path"
    elif status not in {"received", "promoted"}:
        disposition, reason = "unsupported", f"deposit_status_{status or 'missing'}"
    elif size_bytes <= 0:
        disposition, reason = "unsupported", "empty_file"
    elif not re.fullmatch(r"[0-9a-fA-F]{64}", str(deposit_file.sha256 or "")):
        disposition, reason = "unsupported", "invalid_sha256"
    elif campaign == "direct" and extension == "zip":
        disposition, reason = "deferred_zip", "zip_requires_safe_member_campaign"
    elif campaign == "direct" and extension in _LEGACY_EXTENSIONS:
        disposition, reason = "deferred_legacy", "legacy_campaign_required"
    elif campaign == "direct" and extension in _UNVALIDATED_LEGACY_EXTENSIONS:
        disposition, reason = "deferred_legacy", "legacy_parser_fixture_required"
    elif campaign == "legacy" and extension == "zip":
        disposition, reason = "deferred_zip", "zip_requires_safe_member_campaign"
    elif campaign == "legacy" and extension in profile.direct_extensions:
        disposition, reason = "deferred_direct", "direct_campaign_required"
    elif campaign == "legacy" and extension in _UNVALIDATED_LEGACY_EXTENSIONS:
        disposition, reason = "unsupported", "legacy_parser_fixture_required"
    elif campaign == "zip" and extension != "zip":
        if extension in _LEGACY_EXTENSIONS:
            disposition, reason = "deferred_legacy", "legacy_campaign_required"
        elif extension in profile.direct_extensions:
            disposition, reason = "deferred_direct", "direct_campaign_required"
        elif extension in _UNVALIDATED_LEGACY_EXTENSIONS:
            disposition, reason = "unsupported", "legacy_parser_fixture_required"
        else:
            disposition, reason = "unsupported", f"unsupported_extension:{extension or 'none'}"
    elif campaign == "legacy" and extension not in _LEGACY_EXTENSIONS:
        disposition, reason = "unsupported", f"unsupported_extension:{extension or 'none'}"
    elif campaign == "direct" and extension not in profile.direct_extensions:
        disposition, reason = "unsupported", f"unsupported_extension:{extension or 'none'}"
    elif size_bytes > MAX_SOURCE_SIZE_BYTES and not (
        campaign == "zip" and extension == "zip"
    ):
        disposition, reason = "unsupported", "source_exceeds_source_ledger_limit"
    else:
        logical_name = logical_document_name(
            deposit_file,
            project_code=project_metadata["project_code"],
        )

    base = NoticeWaveItem(
        deposit_file_id=str(deposit_file.id),
        filename=str(deposit_file.filename or ""),
        size_bytes=size_bytes,
        deposit_size_bytes=size_bytes,
        sha256=str(deposit_file.sha256 or ""),
        deposit_status=status,
        content_type=str(deposit_file.content_type or ""),
        extension=extension,
        disposition=disposition,
        reason=reason,
        logical_name=logical_name,
        project_metadata=dict(project_metadata),
    )
    if campaign != "zip" or extension != "zip" or disposition != "eligible":
        return [base]
    return _inspect_zip_members(
        deposit_file,
        profile=profile,
        project_metadata=project_metadata,
    )


def _staged_path(deposit_file: DepositFile):
    # Lazy import avoids the secure_deposit -> worker_dispatch -> worker_ingest
    # import chain while the CLI module is being collected.
    from app.services.secure_deposit import staged_file_path

    return staged_file_path(deposit_file)


def _safe_zip_member_path(raw: str) -> str | None:
    # Store the exact central-directory key used by ``ZipFile.getinfo``. Paths
    # that would require normalisation are rejected rather than accepted under
    # a spelling that can no longer be read during worker/preview resolution.
    value = str(raw or "")
    if "\\" in value or "//" in value or value != value.strip():
        return None
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(part in {"", ".", ".."} or ":" in part for part in path.parts)
        or path.as_posix() != value
    ):
        return None
    return path.as_posix()


def _zip_placeholder(
    deposit_file: DepositFile,
    *,
    project_metadata: dict[str, str],
    disposition: str,
    reason: str,
    member_path: str | None = None,
    member_size_bytes: int | None = None,
    extension: str = "zip",
) -> NoticeWaveItem:
    return NoticeWaveItem(
        deposit_file_id=str(deposit_file.id),
        filename=str(deposit_file.filename or ""),
        size_bytes=max(0, int(member_size_bytes or deposit_file.size_bytes or 0)),
        deposit_size_bytes=max(0, int(deposit_file.size_bytes or 0)),
        sha256=str(deposit_file.sha256 or ""),
        deposit_status=str(deposit_file.status or ""),
        content_type="",
        extension=extension,
        disposition=disposition,
        reason=reason,
        logical_name=None,
        member_path=member_path,
        member_size_bytes=member_size_bytes,
        project_metadata=dict(project_metadata),
    )


def _inspect_zip_members(
    deposit_file: DepositFile,
    *,
    profile: NoticeSourceProfile,
    project_metadata: dict[str, str],
) -> list[NoticeWaveItem]:
    """Inspect and hash safe document members without extracting the archive."""

    try:
        archive_path = _staged_path(deposit_file)
        archive_digest = hashlib.sha256()
        with open(archive_path, "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                archive_digest.update(block)
        if archive_digest.hexdigest() != str(deposit_file.sha256 or "").lower():
            return [
                _zip_placeholder(
                    deposit_file,
                    project_metadata=project_metadata,
                    disposition="unsupported",
                    reason="secure_deposit_source_sha_mismatch",
                )
            ]
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if not infos:
                return [
                    _zip_placeholder(
                        deposit_file,
                        project_metadata=project_metadata,
                        disposition="unsupported",
                        reason="empty_zip_archive",
                    )
                ]
            if len(infos) > MAX_ZIP_MEMBER_COUNT:
                return [
                    _zip_placeholder(
                        deposit_file,
                        project_metadata=project_metadata,
                        disposition="unsupported",
                        reason="zip_member_count_exceeded",
                    )
                ]
            total_uncompressed = sum(max(0, int(info.file_size or 0)) for info in infos)
            total_compressed = sum(max(0, int(info.compress_size or 0)) for info in infos)
            if total_uncompressed > MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES:
                return [
                    _zip_placeholder(
                        deposit_file,
                        project_metadata=project_metadata,
                        disposition="unsupported",
                        reason="zip_total_uncompressed_size_exceeded",
                    )
                ]
            if total_uncompressed / max(1, total_compressed) > MAX_ZIP_COMPRESSION_RATIO:
                return [
                    _zip_placeholder(
                        deposit_file,
                        project_metadata=project_metadata,
                        disposition="unsupported",
                        reason="zip_total_compression_ratio_exceeded",
                    )
                ]
            paths = [str(info.filename or "") for info in infos]
            if len(paths) != len(set(paths)):
                return [
                    _zip_placeholder(
                        deposit_file,
                        project_metadata=project_metadata,
                        disposition="unsupported",
                        reason="duplicate_zip_member_path",
                    )
                ]

            items: list[NoticeWaveItem] = []
            for info in infos:
                raw_member_path = str(info.filename or "")
                member_path = _safe_zip_member_path(raw_member_path)
                extension = PurePosixPath(raw_member_path).suffix.lower().lstrip(".")
                member_size = max(0, int(info.file_size or 0))
                disposition = "eligible"
                reason: str | None = None
                if member_path is None:
                    disposition, reason = "unsupported", "unsafe_zip_member_path"
                elif info.flag_bits & 0x1:
                    disposition, reason = "unsupported", "encrypted_zip_member"
                elif stat.S_ISLNK((int(info.external_attr or 0) >> 16) & 0xFFFF):
                    disposition, reason = "unsupported", "symlink_zip_member"
                elif member_size <= 0:
                    disposition, reason = "unsupported", "empty_zip_member"
                elif member_size > MAX_ZIP_MEMBER_BYTES:
                    disposition, reason = "unsupported", "zip_member_size_exceeded"
                elif member_size / max(1, int(info.compress_size or 0)) > MAX_ZIP_COMPRESSION_RATIO:
                    disposition, reason = "unsupported", "zip_member_compression_ratio_exceeded"
                elif extension == "zip":
                    disposition, reason = "unsupported", "nested_archive_not_recursed"
                elif extension in _UNVALIDATED_LEGACY_EXTENSIONS:
                    disposition, reason = "unsupported", "legacy_parser_fixture_required"
                elif extension not in profile.direct_extensions | _LEGACY_EXTENSIONS:
                    disposition, reason = (
                        "unsupported",
                        f"unsupported_zip_member_extension:{extension or 'none'}",
                    )

                member_sha: str | None = None
                logical_name: str | None = None
                if disposition == "eligible" and member_path:
                    digest = hashlib.sha256()
                    try:
                        with archive.open(info, "r") as source:
                            while True:
                                block = source.read(1024 * 1024)
                                if not block:
                                    break
                                digest.update(block)
                    except (OSError, RuntimeError, zipfile.BadZipFile):
                        disposition, reason = "unsupported", "zip_member_read_failed"
                    else:
                        member_sha = digest.hexdigest()
                        logical_name = logical_document_name(
                            deposit_file,
                            project_code=project_metadata["project_code"],
                            source_name=member_path,
                            content_sha256=member_sha,
                        )

                items.append(
                    NoticeWaveItem(
                        deposit_file_id=str(deposit_file.id),
                        filename=str(deposit_file.filename or ""),
                        size_bytes=member_size,
                        deposit_size_bytes=max(0, int(deposit_file.size_bytes or 0)),
                        sha256=str(deposit_file.sha256 or ""),
                        deposit_status=str(deposit_file.status or ""),
                        content_type=mimetypes.guess_type(member_path or raw_member_path)[0]
                        or "",
                        extension=extension,
                        disposition=disposition,
                        reason=reason,
                        logical_name=logical_name,
                        member_path=member_path or raw_member_path,
                        member_size_bytes=member_size,
                        member_sha256=member_sha,
                        project_metadata=dict(project_metadata),
                    )
                )
            return items
    except (OSError, zipfile.BadZipFile, ValueError):
        return [
            _zip_placeholder(
                deposit_file,
                project_metadata=project_metadata,
                disposition="unsupported",
                reason="invalid_or_missing_zip_archive",
            )
        ]


def _build_waves(items: Iterable[NoticeWaveItem]) -> tuple[NoticeWave, ...]:
    waves: list[NoticeWave] = []
    pending: list[NoticeWaveItem] = []
    pending_bytes = 0

    def flush() -> None:
        nonlocal pending, pending_bytes
        if pending:
            waves.append(NoticeWave(index=len(waves) + 1, items=tuple(pending)))
        pending = []
        pending_bytes = 0

    active_zip_deposit: str | None = None
    for item in (row for row in items if row.disposition == "eligible"):
        if item.member_path:
            # Never mix members from two archives in one wave. This keeps the
            # single DepositFile ownership boundary explicit while still
            # allowing one large safe archive to span several bounded waves.
            if active_zip_deposit != item.deposit_file_id:
                flush()
                active_zip_deposit = item.deposit_file_id
        elif active_zip_deposit is not None:
            flush()
            active_zip_deposit = None
        if item.size_bytes > LARGE_SOURCE_BYTES:
            flush()
            waves.append(NoticeWave(index=len(waves) + 1, items=(item,)))
            continue
        if pending and (
            len(pending) >= MAX_SOURCES_PER_WAVE
            or pending_bytes + item.size_bytes > MAX_BYTES_PER_WAVE
        ):
            flush()
        pending.append(item)
        pending_bytes += item.size_bytes
    flush()
    return tuple(waves)


def build_notice_wave_plan(
    db: DBSession,
    *,
    workspace: Workspace,
    collection_slug: str = DEFAULT_NOTICE_COLLECTION,
    profile_slug: str = "needlepunch",
    campaign: str = "direct",
    source_prefix: str | None = None,
    projects: Iterable[str] | None = None,
    project_range: str | tuple[int, int] | None = None,
) -> NoticeWavePlan:
    """Build a deterministic classification and batching plan."""

    try:
        profile = NOTICE_SOURCE_PROFILES[profile_slug]
    except KeyError as exc:
        raise ValueError(f"unknown notice source profile: {profile_slug}") from exc
    if collection_slug != DEFAULT_NOTICE_COLLECTION:
        raise ValueError(
            "Needlepunch promotion is restricted to the authoritative collection "
            f"{DEFAULT_NOTICE_COLLECTION}"
        )
    selected_campaign = str(campaign or "").strip().lower()
    if selected_campaign not in NOTICE_CAMPAIGNS:
        raise ValueError(
            f"unknown notice campaign: {campaign}; expected one of {NOTICE_CAMPAIGNS}"
        )
    selected_prefix = _normalise_source_prefix(source_prefix, profile=profile)
    selected_projects = _normalise_projects(projects)
    selected_range = parse_project_range(project_range)
    if bool(selected_projects) == bool(selected_range):
        raise ValueError("select exactly one of projects or project_range")

    deposits = (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace.id,
            DepositFile.filename.like(_safe_like_prefix(selected_prefix), escape="\\"),
        )
        .all()
    )
    deposits.sort(
        key=lambda row: (
            str(row.filename or "").casefold(),
            row.uploaded_at or datetime.min,
            str(row.id),
        )
    )
    items: list[NoticeWaveItem] = []
    seen_deposit_identities: set[str] = set()
    for deposit in deposits:
        project_metadata = derive_project_reference(str(deposit.filename or ""))
        if not _selected(
            project_metadata=project_metadata,
            filename=str(deposit.filename or ""),
            profile=profile,
            projects=selected_projects,
            project_range=selected_range,
        ):
            continue
        deposit_identity = f"{deposit.id}:{str(deposit.sha256 or '').lower()}"
        if deposit_identity in seen_deposit_identities:
            continue
        seen_deposit_identities.add(deposit_identity)
        classified = _classify_deposit(
            deposit,
            profile=profile,
            project_metadata=project_metadata,
            campaign=selected_campaign,
        )
        items.extend(classified)

    item_tuple = tuple(items)
    return NoticeWavePlan(
        workspace_id=str(workspace.id),
        workspace_slug=str(workspace.slug),
        collection_slug=str(collection_slug),
        profile_slug=profile.slug,
        campaign=selected_campaign,
        source_prefix=selected_prefix,
        projects=selected_projects,
        project_range=selected_range,
        items=item_tuple,
        waves=_build_waves(item_tuple),
    )


def _read_manifest(collection: KnowledgeCollection) -> dict[str, Any]:
    store = get_object_store()
    key = document_manifest_key(collection)
    if not store.exists(key):
        return {}
    loaded = json.loads(store.read_bytes(key).decode("utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("collection document manifest is not an object")
    return loaded


def _metadata_for_item(
    item: NoticeWaveItem,
    *,
    wave_id: str,
    campaign: str,
    deposit_expected_document_count: int,
) -> dict[str, Any]:
    locator = {
        "kind": "secure_deposit_zip_member"
        if item.member_path
        else "secure_deposit_file",
        "deposit_file_id": item.deposit_file_id,
        "size_bytes": item.deposit_size_bytes,
        "sha256": item.sha256.lower(),
    }
    if item.member_path:
        locator.update(
            {
                "member_path": item.member_path,
                "member_size_bytes": int(item.member_size_bytes or 0),
                "member_sha256": str(item.member_sha256 or "").lower(),
            }
        )
    metadata = {
        **item.project_metadata,
        "origin": "secure_deposit",
        "source_profile": "needlepunch",
        "source_campaign": campaign,
        "source_deposit_path": item.filename,
        "source_deposit_file_id": item.deposit_file_id,
        "source_identity": item.source_identity,
        "content_sha256": item.content_sha256,
        "deposit_expected_document_count": deposit_expected_document_count,
        "wave_id": wave_id,
        "source_locator": locator,
    }
    if item.member_path:
        metadata.update(
            {
                "archive_name": PurePosixPath(item.filename).name,
                "archive_member_path": item.member_path,
            }
        )
    return metadata


def _source_identity(row: KnowledgeCollectionSource) -> str:
    metadata = dict(row.source_metadata or {})
    identity = str(metadata.get("source_identity") or "")
    if identity:
        return identity
    locator = metadata.get("source_locator") or {}
    if isinstance(locator, dict):
        file_id = str(locator.get("deposit_file_id") or "")
        sha256 = str(locator.get("sha256") or "").lower()
        if file_id and sha256:
            member_path = str(locator.get("member_path") or "")
            member_sha = str(locator.get("member_sha256") or "").lower()
            if member_path:
                return f"{file_id}:{sha256}:{member_path}:{member_sha}"
            return f"{file_id}:{sha256}"
    return ""


def _plan_report_key(collection: KnowledgeCollection, plan: NoticeWavePlan) -> str:
    return get_object_store().key(
        collection.artifact_prefix,
        "notice-wave-plans",
        f"{plan.plan_hash}.json",
    )


def _persist_plan_classification(
    db: DBSession,
    *,
    collection: KnowledgeCollection,
    plan: NoticeWavePlan,
) -> str:
    """Persist the full classification report and reference it from deposits."""

    store = get_object_store()
    report_key = _plan_report_key(collection, plan)
    if not store.exists(report_key):
        report = plan.as_dict(include_items=False)
        report["items"] = [item.canonical_dict() for item in plan.items]
        store.write_text(
            report_key,
            json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True),
        )
    grouped: dict[str, list[NoticeWaveItem]] = {}
    for item in plan.items:
        grouped.setdefault(item.deposit_file_id, []).append(item)
    rows = (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == plan.workspace_id,
            DepositFile.id.in_(list(grouped)),
        )
        .all()
        if grouped
        else []
    )
    classified_at = datetime.utcnow().isoformat()
    for row in rows:
        items = grouped.get(str(row.id), [])
        base = dict(row.promotion_result or {})
        base["notice_classification"] = {
            "plan_hash": plan.plan_hash,
            "report_key": report_key,
            "profile": plan.profile_slug,
            "campaign": plan.campaign,
            "source_prefix": plan.source_prefix,
            "collection_slug": plan.collection_slug,
            "classified_at": classified_at,
            "source_count": len(items),
            "eligible_source_count": sum(
                1 for item in items if item.disposition == "eligible"
            ),
            "disposition_counts": dict(
                sorted(Counter(item.disposition for item in items).items())
            ),
            "reason_counts": dict(
                sorted(Counter(item.reason for item in items if item.reason).items())
            ),
        }
        row.promotion_result = base
    return report_key


def execute_notice_wave_plan(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    plan: NoticeWavePlan,
    expected_plan_hash: str,
    wave_index: int | None = None,
    dispatch: bool = True,
) -> dict[str, Any]:
    """Queue one approved incremental no-copy wave.

    The plan is rebuilt from the database before any mutation.  Re-executing
    an unchanged wave is a terminal no-op once its source identities exist in
    ``KnowledgeCollectionSource``.
    """

    fresh = build_notice_wave_plan(
        db,
        workspace=workspace,
        collection_slug=plan.collection_slug,
        profile_slug=plan.profile_slug,
        campaign=plan.campaign,
        source_prefix=plan.source_prefix,
        projects=plan.projects,
        project_range=plan.project_range,
    )
    approved_hash = str(expected_plan_hash or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", approved_hash):
        raise ValueError("expected_plan_hash must be a full SHA-256 hex digest")
    if fresh.plan_hash != approved_hash:
        raise NoticePlanDriftError(
            f"notice plan drift: approved={approved_hash} current={fresh.plan_hash}"
        )
    if fresh.waves:
        if wave_index is None:
            if len(fresh.waves) != 1:
                raise ValueError(
                    "wave_index is required when a plan contains multiple waves"
                )
            wave_index = 1
        if wave_index < 1 or wave_index > len(fresh.waves):
            raise ValueError(f"wave_index must be between 1 and {len(fresh.waves)}")

    collection = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace.id,
            KnowledgeCollection.slug == fresh.collection_slug,
        )
        .with_for_update()
        .first()
    )
    if not collection:
        raise ValueError(
            f"authoritative collection not found in workspace: {fresh.collection_slug}"
        )
    if collection.status != "ready":
        raise ValueError(
            "authoritative collection must be ready before incremental promotion"
        )
    baseline_document_names = [str(name) for name in (collection.document_names or [])]
    baseline_document_count = int(collection.document_count or 0)
    baseline_chunk_count = int(collection.chunk_count or 0)
    report_key = _persist_plan_classification(
        db,
        collection=collection,
        plan=fresh,
    )
    if not fresh.waves:
        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="notice.plan.classified",
            actor=user.email or user.username or user.id,
            details={
                "collection_slug": collection.slug,
                "profile": fresh.profile_slug,
                "campaign": fresh.campaign,
                "plan_hash": fresh.plan_hash,
                "report_key": report_key,
                "disposition_counts": fresh.disposition_counts,
            },
        )
        db.commit()
        return {
            "status": "noop",
            "reason": "no_eligible_sources",
            "collection_slug": collection.slug,
            "plan_hash": fresh.plan_hash,
            "report_key": report_key,
            "disposition_counts": fresh.disposition_counts,
        }

    wave = fresh.waves[int(wave_index) - 1]
    wave_id = (
        f"{fresh.profile_slug}-{fresh.campaign}-"
        f"{fresh.plan_hash[:12]}-{wave.index:03d}"
    )

    pending_postflight_jobs = [
        row
        for row in (
            db.query(WorkerJob)
            .filter(
                WorkerJob.collection_id == collection.id,
                WorkerJob.kind == "document_ingest_index",
                WorkerJob.status == "completed",
            )
            .all()
        )
        if bool((row.result or {}).get("postflight_required"))
        and str((row.result or {}).get("postflight_status") or "") == "pending"
    ]
    if pending_postflight_jobs:
        same_wave = next(
            (
                row
                for row in pending_postflight_jobs
                if str(
                    ((row.result or {}).get("ingest_options") or {}).get("wave_id")
                    or ""
                )
                == wave_id
            ),
            None,
        )
        if same_wave is None or len(pending_postflight_jobs) != 1:
            raise ValueError(
                "a completed Needlepunch wave is awaiting postflight verification: "
                + ", ".join(str(row.id) for row in pending_postflight_jobs)
            )
        options = dict((same_wave.result or {}).get("ingest_options") or {})
        db.commit()
        return {
            "status": "noop",
            "reason": "wave_awaiting_postflight",
            "collection_slug": collection.slug,
            "plan_hash": fresh.plan_hash,
            "report_key": report_key,
            "wave_id": wave_id,
            "wave_index": wave.index,
            "job_id": same_wave.id,
            "document_names": [
                str(name)
                for name in (options.get("document_names") or [])
                if str(name or "").strip()
            ],
            "already_known": [
                {
                    "document_name": str(name),
                    "status": "already_known",
                }
                for name in (options.get("already_known_document_names") or [])
                if str(name or "").strip()
            ],
        }

    active_jobs = (
        db.query(WorkerJob)
        .filter(
            WorkerJob.collection_id == collection.id,
            WorkerJob.kind == "document_ingest_index",
            WorkerJob.status.in_(("queued", "running")),
        )
        .all()
    )
    if active_jobs:
        same_wave = next(
            (
                row
                for row in active_jobs
                if str(((row.result or {}).get("ingest_options") or {}).get("wave_id") or "")
                == wave_id
            ),
            None,
        )
        if same_wave is not None and len(active_jobs) == 1:
            same_wave_options = dict(
                (same_wave.result or {}).get("ingest_options") or {}
            )
            db.commit()
            return {
                "status": "noop",
                "reason": "wave_already_active",
                "collection_slug": collection.slug,
                "plan_hash": fresh.plan_hash,
                "report_key": report_key,
                "wave_id": wave_id,
                "wave_index": wave.index,
                "job_id": same_wave.id,
                "document_names": [
                    str(name)
                    for name in (same_wave_options.get("document_names") or [])
                    if str(name or "").strip()
                ],
                "already_known": [
                    {
                        "document_name": str(name),
                        "status": "already_known",
                    }
                    for name in (
                        same_wave_options.get("already_known_document_names") or []
                    )
                    if str(name or "").strip()
                ],
            }
        raise ValueError(
            "another document ingestion job is already active for the authoritative "
            f"collection: {', '.join(str(row.id) for row in active_jobs)}"
        )

    logical_names = [str(item.logical_name) for item in wave.items if item.logical_name]
    if len(logical_names) != len(set(logical_names)):
        raise ValueError("approved wave contains colliding logical document names")
    source_rows = (
        db.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.normalized_name.in_(logical_names),
        )
        .all()
        if logical_names
        else []
    )
    by_name = {row.normalized_name: row for row in source_rows}
    deposit_ids = sorted({item.deposit_file_id for item in wave.items})
    deposit_rows = (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace.id,
            DepositFile.id.in_(deposit_ids),
        )
        .all()
    )
    deposits_by_id = {str(row.id): row for row in deposit_rows}
    job_ids = {str(row.worker_job_id) for row in deposit_rows if row.worker_job_id}
    active_job_ids = {
        str(row.id)
        for row in (
            db.query(WorkerJob)
            .filter(
                WorkerJob.id.in_(job_ids),
                WorkerJob.status.in_(("queued", "running")),
            )
            .all()
            if job_ids
            else []
        )
    }
    pending: list[tuple[NoticeWaveItem, DepositFile]] = []
    already_known: list[dict[str, str]] = []
    for item in wave.items:
        if not item.logical_name:
            raise ValueError(f"eligible item has no logical name: {item.deposit_file_id}")
        deposit = deposits_by_id.get(item.deposit_file_id)
        if not deposit:
            raise NoticePlanDriftError(f"deposit disappeared: {item.deposit_file_id}")
        if (
            str(deposit.filename or "") != item.filename
            or int(deposit.size_bytes or 0) != item.deposit_size_bytes
            or str(deposit.sha256 or "").lower() != item.sha256.lower()
        ):
            raise NoticePlanDriftError(f"deposit changed: {item.deposit_file_id}")
        if deposit.status not in {"received", "promoted"}:
            raise NoticePlanDriftError(
                f"deposit status is no longer promotable: {item.deposit_file_id}"
            )
        if (
            deposit.status == "promoted"
            and deposit.promoted_collection_slug != collection.slug
        ):
            raise ValueError(
                f"deposit already promoted to another collection: {item.deposit_file_id}"
            )

        existing = by_name.get(item.logical_name)
        if existing:
            existing_identity = _source_identity(existing)
            if existing_identity != item.source_identity:
                raise ValueError(
                    "logical name collision for distinct source identity: "
                    f"{item.logical_name}"
                )
            terminal = existing.status in {"ready", "indexed", "deduplicated"}
            inflight = existing.status in {"queued", "ingesting"} and str(
                deposit.worker_job_id or ""
            ) in active_job_ids
        else:
            terminal = False
            inflight = False
        if existing and (terminal or inflight):
            already_known.append(
                {
                    "deposit_file_id": item.deposit_file_id,
                    "document_name": existing.normalized_name,
                    "status": existing.status,
                }
            )
            continue
        pending.append((item, deposit))

    if not pending:
        completed_for_wave = [
            row
            for row in (
                db.query(WorkerJob)
                .filter(
                    WorkerJob.collection_id == collection.id,
                    WorkerJob.kind == "document_ingest_index",
                    WorkerJob.status == "completed",
                )
                .all()
            )
            if str(
                ((row.result or {}).get("ingest_options") or {}).get("wave_id")
                or ""
            )
            == wave_id
        ]
        if completed_for_wave:
            terminal_job = max(
                completed_for_wave,
                key=lambda row: row.completed_at or row.updated_at,
            )
        else:
            terminal_job = create_worker_job(
                db,
                workspace_id=workspace.id,
                collection_id=collection.id,
                kind="document_ingest_index",
            )
            update_job(
                db,
                terminal_job.id,
                status="completed",
                progress=100,
                result={
                    "ingest_options": {
                        "mode": "incremental",
                        "document_names": [],
                        "already_known_document_names": [
                            item["document_name"] for item in already_known
                        ],
                        "baseline_document_names": baseline_document_names,
                        "baseline_document_count": baseline_document_count,
                        "baseline_chunk_count": baseline_chunk_count,
                        "wave_id": wave_id,
                        "source_profile": fresh.profile_slug,
                        "source_campaign": fresh.campaign,
                    },
                    "notice_wave": {
                        "status": "already_registered",
                        "plan_hash": fresh.plan_hash,
                        "wave_id": wave_id,
                        "wave_index": wave.index,
                        "source_count": len(already_known),
                    },
                },
                stage="ready_already_registered",
            )
            emit_audit_event(
                db=db,
                workspace_id=workspace.id,
                event_type="notice.wave.already_registered",
                actor=user.email or user.username or user.id,
                details={
                    "collection_slug": collection.slug,
                    "plan_hash": fresh.plan_hash,
                    "wave_id": wave_id,
                    "wave_index": wave.index,
                    "job_id": terminal_job.id,
                    "source_count": len(already_known),
                },
            )
        db.commit()
        return {
            "status": "noop",
            "reason": "wave_already_registered",
            "collection_slug": collection.slug,
            "plan_hash": fresh.plan_hash,
            "report_key": report_key,
            "wave_id": wave_id,
            "wave_index": wave.index,
            "job_id": terminal_job.id,
            "document_names": [],
            "already_known": already_known,
        }

    manifest = _read_manifest(collection)
    document_names = list(collection.document_names or [])
    document_name_set = set(document_names)
    metadata_by_name: dict[str, dict[str, Any]] = {}
    expected_by_deposit = Counter(
        item.deposit_file_id for item in fresh.items if item.disposition == "eligible"
    )
    for item, _deposit in pending:
        metadata = _metadata_for_item(
            item,
            wave_id=wave_id,
            campaign=fresh.campaign,
            deposit_expected_document_count=expected_by_deposit[item.deposit_file_id],
        )
        metadata_by_name[item.logical_name] = metadata
        manifest[item.logical_name] = metadata
        if item.logical_name not in document_name_set:
            document_names.append(item.logical_name)
            document_name_set.add(item.logical_name)
        upsert_collection_source(
            db,
            collection=collection,
            filename=item.logical_name,
            status="queued",
            mime_type=item.content_type
            or mimetypes.guess_type(item.logical_name)[0]
            or "",
            origin="secure_deposit",
            size_bytes=item.size_bytes,
            source_metadata=metadata,
            replace_source_metadata=True,
        )

    collection.document_names = document_names
    collection.document_count = len(document_names)
    job = create_worker_job(
        db,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    job.result = {
        "ingest_options": {
            "mode": "incremental",
            "document_names": list(metadata_by_name),
            "already_known_document_names": [
                item["document_name"] for item in already_known
            ],
            "baseline_document_names": baseline_document_names,
            "baseline_document_count": baseline_document_count,
            "baseline_chunk_count": baseline_chunk_count,
            "wave_id": wave_id,
            "source_profile": fresh.profile_slug,
            "source_campaign": fresh.campaign,
        },
        "notice_wave": {
            "plan_hash": fresh.plan_hash,
            "wave_id": wave_id,
            "wave_index": wave.index,
            "wave_count": len(fresh.waves),
            "campaign": fresh.campaign,
            "report_key": report_key,
            "source_count": len(metadata_by_name),
            "total_bytes": sum(item.size_bytes for item, _ in pending),
            "disposition_counts": fresh.disposition_counts,
            "sources": [
                {
                    "deposit_file_id": item.deposit_file_id,
                    "document_name": item.logical_name,
                    "source_identity": item.source_identity,
                    "member_path": item.member_path,
                }
                for item, _ in pending
            ],
        },
    }
    pending_by_deposit: dict[str, list[NoticeWaveItem]] = {}
    for item, _deposit in pending:
        pending_by_deposit.setdefault(item.deposit_file_id, []).append(item)
    for deposit_id, items in pending_by_deposit.items():
        deposit = deposits_by_id[deposit_id]
        deposit.worker_job_id = job.id
        base = dict(deposit.promotion_result or {})
        for stale_key in ("dispatch_status", "dispatch_error", "failed_at"):
            base.pop(stale_key, None)
        base.update({
            "status": "queued",
            "indexing_status": "queued",
            "mode": "needlepunch_notice_wave",
            "campaign": fresh.campaign,
            "collection_slug": collection.slug,
            "job_id": job.id,
            "wave_id": wave_id,
            "plan_hash": fresh.plan_hash,
            "report_key": report_key,
            "logical_document_names": [item.logical_name for item in items],
            "source_locators": [
                metadata_by_name[str(item.logical_name)]["source_locator"]
                for item in items
            ],
            "deposit_expected_document_count": expected_by_deposit[deposit_id],
        })
        if len(items) == 1:
            base["logical_document_name"] = items[0].logical_name
            base["source_locator"] = metadata_by_name[str(items[0].logical_name)][
                "source_locator"
            ]
        deposit.promotion_result = base
        # Deliberately do not mark promoted here.  The worker owns the atomic
        # transition after size/SHA validation and successful indexing.

    store = get_object_store()
    store.write_text(
        document_manifest_key(collection),
        json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True),
    )
    db.commit()

    celery_task_id: str | None = None
    if dispatch:
        celery_task_id = dispatch_worker_job(db, job, allow_inline_fallback=False)
        if celery_task_id is None:
            # ``dispatch_worker_job(..., allow_inline_fallback=False)`` records
            # the broker failure as ``dispatch_pending`` and returns ``None``.
            # No task owns this job, so leaving it queued would permanently
            # block the collection lock and every retry of the approved wave.
            dispatch_result = dict(job.result or {})
            dispatch_error = str(
                dispatch_result.get("dispatch_error")
                or dispatch_result.get("dispatch_warning")
                or "worker_dispatch_unavailable"
            )
            failed_at = datetime.utcnow().isoformat()
            update_job(
                db,
                job.id,
                status="failed",
                progress=100,
                error=dispatch_error,
                result={
                    **dispatch_result,
                    "dispatch_warning": "worker_dispatch_unavailable",
                    "dispatch_error": dispatch_error,
                    "dispatch_failed_at": failed_at,
                },
                stage="dispatch_failed",
            )
            failed_names = set(metadata_by_name)
            failed_sources = (
                db.query(KnowledgeCollectionSource)
                .filter(
                    KnowledgeCollectionSource.collection_id == collection.id,
                    KnowledgeCollectionSource.normalized_name.in_(failed_names),
                )
                .all()
                if failed_names
                else []
            )
            for source in failed_sources:
                source.status = "error"
                source.last_error = dispatch_error
            for deposit_id in pending_by_deposit:
                deposit = deposits_by_id[deposit_id]
                deposit.status = "received"
                failure = dict(deposit.promotion_result or {})
                failure.update(
                    {
                        "status": "dispatch_failed",
                        "indexing_status": "failed",
                        "dispatch_status": "failed",
                        "dispatch_error": dispatch_error,
                        "failed_at": failed_at,
                        "job_id": job.id,
                        "wave_id": wave_id,
                    }
                )
                deposit.promotion_result = failure
            try:
                restore_notice_wave_baseline(
                    collection,
                    dict((job.result or {}).get("ingest_options") or {}),
                )
            except NoticeWaveBaselineError as baseline_exc:
                collection.status = "error"
                collection.last_error = str(baseline_exc)
            db.commit()
            raise RuntimeError(
                f"notice wave dispatch failed for job {job.id}: {dispatch_error}"
            )
        db.commit()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="notice.wave.queued",
        actor=user.email or user.username or user.id,
        details={
            "collection_slug": collection.slug,
            "profile": fresh.profile_slug,
            "campaign": fresh.campaign,
            "plan_hash": fresh.plan_hash,
            "report_key": report_key,
            "wave_id": wave_id,
            "wave_index": wave.index,
            "job_id": job.id,
            "source_count": len(metadata_by_name),
            "total_bytes": sum(item.size_bytes for item, _ in pending),
        },
    )
    db.commit()
    return {
        "status": "queued",
        "collection_slug": collection.slug,
        "plan_hash": fresh.plan_hash,
        "report_key": report_key,
        "campaign": fresh.campaign,
        "wave_id": wave_id,
        "wave_index": wave.index,
        "job_id": job.id,
        "celery_task_id": celery_task_id,
        "source_count": len(metadata_by_name),
        "total_bytes": sum(item.size_bytes for item, _ in pending),
        "already_known": already_known,
        "document_names": list(metadata_by_name),
    }


def fail_queued_notice_job(
    db: DBSession,
    *,
    workspace: Workspace,
    collection: KnowledgeCollection,
    job_id: str,
    wave_id: str,
    actor: str,
    reason: str,
) -> bool:
    """Atomically rearm a timed-out job that no worker ever claimed.

    A delayed duplicate Celery message is harmless after this transition: the
    worker claims only rows still in ``queued``.  Running jobs are never
    cancelled by this helper.
    """

    job = (
        db.query(WorkerJob)
        .filter(
            WorkerJob.id == job_id,
            WorkerJob.workspace_id == workspace.id,
            WorkerJob.collection_id == collection.id,
            WorkerJob.kind == "document_ingest_index",
        )
        .first()
    )
    if job is None or job.status != "queued":
        return False
    options = dict((job.result or {}).get("ingest_options") or {})
    if (
        str(options.get("mode") or "") != "incremental"
        or str(options.get("source_profile") or "") != "needlepunch"
        or str(options.get("wave_id") or "") != wave_id
    ):
        return False
    document_names = {
        str(name)
        for name in (options.get("document_names") or [])
        if str(name or "").strip()
    }
    if not document_names:
        return False
    try:
        baseline_names, baseline_document_count, baseline_chunk_count = (
            notice_wave_baseline(options)
        )
    except NoticeWaveBaselineError:
        return False

    now = datetime.utcnow()
    failed_result = {
        **dict(job.result or {}),
        "dispatch_error": reason,
        "dispatch_failed_at": now.isoformat(),
        "dispatch_status": "timed_out_unclaimed",
        "stage": "dispatch_timeout_rearmed",
    }
    claimed = (
        db.query(WorkerJob)
        .filter(WorkerJob.id == job.id, WorkerJob.status == "queued")
        .update(
            {
                WorkerJob.status: "failed",
                WorkerJob.progress: 100,
                WorkerJob.error: reason,
                WorkerJob.result: failed_result,
                WorkerJob.completed_at: now,
                WorkerJob.updated_at: now,
            },
            synchronize_session=False,
        )
    )
    if claimed != 1:
        db.rollback()
        return False

    sources = (
        db.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.normalized_name.in_(sorted(document_names)),
        )
        .all()
    )
    if {source.normalized_name for source in sources} != document_names:
        db.rollback()
        return False
    expected_deposit_ids: set[str] = set()
    for source in sources:
        metadata = dict(source.source_metadata or {})
        if str(metadata.get("wave_id") or "") != wave_id:
            db.rollback()
            return False
        deposit_id = str(metadata.get("source_deposit_file_id") or "").strip()
        if not deposit_id:
            db.rollback()
            return False
        expected_deposit_ids.add(deposit_id)
        source.status = "error"
        source.last_error = reason

    deposits = (
        db.query(DepositFile)
        .filter(
            DepositFile.workspace_id == workspace.id,
            DepositFile.id.in_(sorted(expected_deposit_ids)),
        )
        .all()
    )
    if {str(deposit.id) for deposit in deposits} != expected_deposit_ids or any(
        str(deposit.worker_job_id or "") != str(job.id) for deposit in deposits
    ):
        db.rollback()
        return False
    for deposit in deposits:
        promotion = dict(deposit.promotion_result or {})
        promotion.update(
            {
                "status": "dispatch_failed",
                "indexing_status": "failed",
                "dispatch_status": "timed_out_unclaimed",
                "dispatch_error": reason,
                "failed_at": now.isoformat(),
                "job_id": job.id,
                "wave_id": wave_id,
            }
        )
        deposit.status = "received"
        deposit.promotion_result = promotion
    collection.document_names = baseline_names
    collection.document_count = baseline_document_count
    collection.chunk_count = baseline_chunk_count
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="notice.wave.dispatch_timeout_rearmed",
        actor=actor,
        severity="warning",
        details={
            "collection_slug": collection.slug,
            "job_id": job.id,
            "wave_id": wave_id,
            "reason": reason,
            "source_count": len(document_names),
        },
    )
    db.commit()
    return True


__all__ = [
    "DEFAULT_NOTICE_COLLECTION",
    "LARGE_SOURCE_BYTES",
    "MAX_BYTES_PER_WAVE",
    "MAX_LOGICAL_NAME_LENGTH",
    "MAX_SOURCES_PER_WAVE",
    "NEEDLEPUNCH_PREFIX",
    "NOTICE_SOURCE_PROFILES",
    "NoticePlanDriftError",
    "NoticeWavePlan",
    "build_notice_wave_plan",
    "execute_notice_wave_plan",
    "fail_queued_notice_job",
    "logical_document_name",
    "parse_project_range",
]
