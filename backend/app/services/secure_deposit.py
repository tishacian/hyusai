"""Secure Deposit service.

This module backs both the public web drop portal and the future SFTP
subsystem. A deposit link is workspace-bound, password-protected, and writes
only to staging until an authorized Agentium user promotes a file to Knowledge.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Optional

import jwt
from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.settings_manager import get_resolved_settings
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.knowledge_collections import (
    create_or_get_collection,
    create_worker_job,
    document_manifest_key,
    original_key,
    update_collection_status,
)
from app.services.object_store import get_object_store
from app.services.rag.document_service import DocumentService
from app.services.worker_dispatch import dispatch_worker_job

try:  # pragma: no cover - exercised when dependency is installed.
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    _ARGON2 = PasswordHasher()
except Exception:  # noqa: BLE001 - dev/test fallback when deps are stale.
    PasswordHasher = None  # type: ignore
    VerifyMismatchError = Exception  # type: ignore
    _ARGON2 = None


_PBKDF2_PREFIX = "pbkdf2_sha256"
_TOKEN_ALGORITHM = "HS256"
_UPLOAD_CHUNK_BYTES = 1024 * 1024
_TEXT_PREVIEW_BYTES = 1024 * 1024
_STRUCTURED_PREVIEW_MAX_BYTES = 25 * 1024 * 1024
_INLINE_PREVIEW_MAX_BYTES = 25 * 1024 * 1024
_TEXT_EXTENSIONS = {
    "csv",
    "json",
    "log",
    "md",
    "rst",
    "txt",
    "xml",
    "yaml",
    "yml",
}
_SPREADSHEET_EXTENSIONS = {"xlsx", "xlsm", "xltx", "xltm"}
_LEGACY_SPREADSHEET_EXTENSIONS = {"xls"}
_DOCX_EXTENSIONS = {"docx"}
_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "bmp", "tif", "tiff", "webp"}
_DOCX_PREVIEW_MAX_BYTES = 25 * 1024 * 1024
_DOCX_PREVIEW_MAX_CHARS = 200_000
_ARCHIVE_PROMOTION_EXTENSIONS = {"csv", "html", "htm", "md", "pdf", "txt"} | _DOCX_EXTENSIONS | _IMAGE_EXTENSIONS
_WORKER_PROMOTION_EXTENSIONS = (
    _ARCHIVE_PROMOTION_EXTENSIONS
    | _SPREADSHEET_EXTENSIONS
    | _TEXT_EXTENSIONS
    | _DOCX_EXTENSIONS
    | _IMAGE_EXTENSIONS
    | {"log", "markdown", "rst"}
)
_BULK_PROMOTION_MAX_FILES = 50
_BULK_PROMOTION_MAX_DOCUMENTS = 200
_ANDRITZ_PROJECT_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{3})[\s_-]?(\d{2,4})(?![A-Z0-9])", re.IGNORECASE)


def enabled_workspace_slugs() -> set[str]:
    return {
        item.strip().lower()
        for item in (settings.secure_deposit_enabled_workspace_slugs or "").split(",")
        if item.strip()
    }


def is_workspace_enabled(workspace: Workspace) -> bool:
    return workspace.slug.lower() in enabled_workspace_slugs()


def default_allowed_extensions() -> list[str]:
    return [
        item.strip().lower().lstrip(".")
        for item in (settings.secure_deposit_allowed_extensions or "").split(",")
        if item.strip()
    ]


def generate_access_id() -> str:
    return secrets.token_urlsafe(14).replace("_", "-")


def generate_deposit_password() -> str:
    return secrets.token_urlsafe(18)


def hash_password(password: str) -> str:
    if _ARGON2 is not None:
        return _ARGON2.hash(password)
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return f"{_PBKDF2_PREFIX}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password_hash: str, password: str) -> bool:
    if password_hash.startswith(f"{_PBKDF2_PREFIX}$"):
        try:
            _, salt_raw, digest_raw = password_hash.split("$", 2)
            salt = base64.b64decode(salt_raw.encode())
            expected = base64.b64decode(digest_raw.encode())
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
            return hmac.compare_digest(actual, expected)
        except Exception:  # noqa: BLE001
            return False
    if _ARGON2 is None:
        return False
    try:
        return bool(_ARGON2.verify(password_hash, password))
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001
        return False


def safe_filename(filename: str | None) -> str:
    name = PurePosixPath(str(filename or "upload").replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return (name or "upload")[:180]


def safe_relative_path(path: str | None) -> str:
    """Sanitize a user-provided relative path while preserving folders."""

    raw = str(path or "upload").replace("\\", "/").strip()
    clean_parts: list[str] = []
    for part in PurePosixPath(raw).parts:
        if part in {"", "/", ".", ".."}:
            continue
        safe_part = re.sub(r"[^A-Za-z0-9._ -]+", "_", part).strip(" .")
        if safe_part:
            clean_parts.append(safe_part[:96])
    if not clean_parts:
        clean_parts = [safe_filename(path)]
    relative = "/".join(clean_parts)
    if len(relative) <= 240:
        return relative
    tail = safe_filename(clean_parts[-1])
    budget = max(1, 240 - len(tail) - 1)
    prefix = "/".join(clean_parts[:-1])[:budget].rstrip("/")
    return f"{prefix}/{tail}" if prefix else tail[:240]


def _storage_root() -> Path:
    root = Path(settings.secure_deposit_storage_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _storage_key(*parts: object) -> str:
    path = PurePosixPath("/".join(str(part).strip("/") for part in parts if str(part).strip("/")))
    clean_parts = [part for part in path.parts if part not in ("", "/", ".")]
    if any(part == ".." for part in clean_parts):
        raise ValueError("Invalid secure deposit storage key")
    return "/".join(clean_parts)


def _storage_path(key: str) -> Path:
    root = _storage_root()
    path = (root / _storage_key(key)).resolve()
    if root not in path.parents and path != root:
        raise ValueError("Secure deposit storage key escapes root")
    return path


def _write_staged_bytes(key: str, content: bytes) -> None:
    path = _storage_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


async def _write_staged_upload(key: str, upload: UploadFile, max_bytes: int) -> tuple[int, str]:
    path = _storage_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".upload-", suffix=".part", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    size = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as handle:
            while True:
                chunk = await upload.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail="File is too large")
                digest.update(chunk)
                handle.write(chunk)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return size, digest.hexdigest()


def _copy_staged_to_local(key: str, destination: Path) -> Path:
    source = _storage_path(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def staged_file_path(file: DepositFile) -> Path:
    path = _storage_path(file.object_key)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=409, detail=f"Staged file is missing: {file.filename}")
    return path


def staged_file_media_type(file: DepositFile) -> str:
    guessed, _ = mimetypes.guess_type(file.filename or "")
    if guessed:
        return guessed
    return file.content_type or "application/octet-stream"


def staged_file_download_name(file: DepositFile) -> str:
    return safe_filename(PurePosixPath(file.filename or "deposit-file").name)


def _hash_local_file(path: Path) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _cell_preview(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)[:240]


def _spreadsheet_preview(path: Path) -> dict[str, Any]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook[workbook.sheetnames[0]]
        rows: list[list[str]] = []
        max_rows = 40
        max_cols = 12
        for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            if row_index > max_rows:
                break
            rows.append([_cell_preview(value) for value in row[:max_cols]])
        return {
            "kind": "spreadsheet",
            "sheet_name": sheet.title,
            "rows": rows,
            "truncated": bool((sheet.max_row or 0) > max_rows or (sheet.max_column or 0) > max_cols),
        }
    finally:
        workbook.close()


def _docx_preview(path: Path) -> dict[str, Any]:
    from docx import Document

    document = Document(path)
    blocks: list[str] = []
    truncated = False

    def append_block(text: str) -> None:
        nonlocal truncated
        clean = text.strip()
        if not clean or truncated:
            return
        current = sum(len(block) for block in blocks) + max(0, len(blocks) - 1) * 2
        remaining = _DOCX_PREVIEW_MAX_CHARS - current
        if remaining <= 0:
            truncated = True
            return
        if len(clean) > remaining:
            blocks.append(clean[:remaining].rstrip())
            truncated = True
        else:
            blocks.append(clean)

    for paragraph in document.paragraphs:
        append_block(paragraph.text)

    for table in document.tables:
        rows: list[str] = []
        for row in table.rows[:40]:
            cells = [_cell_preview(cell.text.replace("\n", " ")) for cell in row.cells[:12]]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            append_block("\n".join(rows))
        if truncated:
            break

    content = "\n\n".join(blocks).strip()
    return {
        "kind": "text",
        "source_kind": "docx",
        "content": content or "No textual content found in this DOCX.",
        "truncated": truncated,
    }


def preview_deposit_file(file: DepositFile) -> dict[str, Any]:
    path = staged_file_path(file)
    media_type = staged_file_media_type(file)
    ext = extension_for(file.filename)
    base: dict[str, Any] = {
        "filename": file.filename,
        "content_type": media_type,
        "size_bytes": int(file.size_bytes or 0),
        "download_url": f"/api/v1/sftp/deposits/{file.id}/download",
    }

    if ext in _SPREADSHEET_EXTENSIONS and int(file.size_bytes or 0) <= _STRUCTURED_PREVIEW_MAX_BYTES:
        return {**base, **_spreadsheet_preview(path)}

    if ext in _DOCX_EXTENSIONS and int(file.size_bytes or 0) <= _DOCX_PREVIEW_MAX_BYTES:
        return {**base, **_docx_preview(path)}

    if ext in _TEXT_EXTENSIONS or media_type.startswith("text/"):
        if int(file.size_bytes or 0) > _TEXT_PREVIEW_BYTES:
            return {**base, "kind": "binary", "reason": "text_preview_too_large"}
        data = path.read_bytes()
        truncated = len(data) > _TEXT_PREVIEW_BYTES
        data = data[:_TEXT_PREVIEW_BYTES]
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                content = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            content = data.decode("utf-8", errors="replace")
        return {**base, "kind": "text", "content": content, "truncated": truncated}

    if int(file.size_bytes or 0) <= _INLINE_PREVIEW_MAX_BYTES:
        if media_type.startswith("image/"):
            return {**base, "kind": "image"}
        if media_type == "application/pdf":
            return {**base, "kind": "pdf"}

    return {**base, "kind": "binary"}


def _archive_component(value: str | None, fallback: str) -> str:
    component = safe_filename(value or fallback).replace(" ", "_")
    return component[:96] or fallback


def _unique_archive_name(path: str, used: set[str]) -> str:
    if path not in used:
        used.add(path)
        return path
    stem, dot, suffix = path.rpartition(".")
    base = stem if dot else path
    ext = f".{suffix}" if dot else ""
    index = 2
    while f"{base}-{index}{ext}" in used:
        index += 1
    unique = f"{base}-{index}{ext}"
    used.add(unique)
    return unique


def _validated_archive_member_path(info: zipfile.ZipInfo) -> PurePosixPath | None:
    raw_name = str(info.filename or "").replace("\\", "/").strip()
    if not raw_name or info.is_dir():
        return None
    path = PurePosixPath(raw_name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HTTPException(status_code=422, detail=f"Unsafe ZIP member path: {info.filename}")
    if any(":" in part for part in path.parts):
        raise HTTPException(status_code=422, detail=f"Unsafe ZIP member path: {info.filename}")
    return path


def _archive_document_name(member_path: PurePosixPath, used: set[str]) -> str:
    safe_path = safe_relative_path(member_path.as_posix())
    flattened = safe_path.replace("/", "__")
    return _unique_archive_name(flattened, used)


def _extract_andritz_project_reference(*values: str | None) -> dict[str, str]:
    for value in values:
        for match in _ANDRITZ_PROJECT_RE.finditer(str(value or "")):
            buyer = match.group(1).upper()
            position = match.group(2)
            return {
                "project_code": f"{buyer}{position}",
                "initial_buyer_code": buyer,
                "project_position": position,
                "project_reference_kind": "andritz_project",
            }
    return {}


def _classify_archive_source_family(path: str, extension: str | None = None) -> str:
    haystack = path.replace("_", " ").replace("-", " ").lower()
    ext = (extension or PurePosixPath(path).suffix.lstrip(".")).lower()
    if any(token in haystack for token in ("spare part", "parts list", "spareparts")):
        return "spare_parts_list"
    if any(token in haystack for token in ("commissioning", "check list", "checklist")):
        return "commissioning"
    if any(token in haystack for token in ("safety", "declaration of conformity", "certif", "conformity")):
        return "safety"
    if any(token in haystack for token in ("annex", "annexe", "annexes")):
        return "annex"
    if any(token in haystack for token in ("maintenance", "service manual", "manuel de service")):
        return "maintenance"
    if any(token in haystack for token in ("operating manual", "operator manual", "user manual", "users manual", "user's manual", "manual")):
        return "operating_manual"
    if ext in {"html", "htm"}:
        return "html_manual"
    return "unknown"


def _archive_document_metadata(
    *,
    deposit_filename: str | None,
    archive_path: str | None,
    document_name: str,
    extension: str | None,
) -> dict[str, Any]:
    archive_name = PurePosixPath(str(deposit_filename or "")).name if deposit_filename else None
    metadata: dict[str, Any] = {
        "source_origin": "secure_deposit",
        "source_family": _classify_archive_source_family(" ".join([archive_path or "", document_name]), extension),
        "archive_name": archive_name,
        "source_deposit_path": deposit_filename,
        "inner_document_path": archive_path,
    }
    if archive_path:
        metadata.update(_extract_andritz_project_reference(deposit_filename, archive_path, document_name))
    return {key: value for key, value in metadata.items() if value is not None}


def _read_supported_archive_documents(
    path: Path,
    *,
    deposit_filename: str | None = None,
    max_files: int | None = None,
    max_uncompressed_bytes: int | None = None,
    on_limit: str = "error",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    limit_files = max(1, int(max_files or settings.secure_deposit_archive_promotion_max_files or 50))
    limit_bytes = int(max_uncompressed_bytes) if max_uncompressed_bytes else None
    documents: list[dict[str, Any]] = []
    used_names: set[str] = set()
    truncated_files = 0
    skipped_uncompressed_bytes = 0

    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=422, detail="Archive is not a valid ZIP file") from exc

    with archive:
        for info in archive.infolist():
            member_path = _validated_archive_member_path(info)
            if member_path is None:
                continue
            ext = extension_for(member_path.name)
            if ext not in _ARCHIVE_PROMOTION_EXTENSIONS:
                continue
            if info.flag_bits & 0x1:
                raise HTTPException(status_code=422, detail=f"Encrypted ZIP member is not supported: {info.filename}")
            file_size = int(info.file_size or 0)
            if len(documents) >= limit_files:
                if on_limit == "truncate":
                    truncated_files += 1
                    continue
                raise HTTPException(
                    status_code=413,
                    detail=f"Archive contains more than {limit_files} supported documents",
                )
            if limit_bytes is not None and sum(int(doc.get("size_bytes") or 0) for doc in documents) + file_size > limit_bytes:
                if on_limit == "truncate":
                    truncated_files += 1
                    skipped_uncompressed_bytes += file_size
                    continue
                raise HTTPException(
                    status_code=413,
                    detail=f"Archive uncompressed payload exceeds {limit_bytes} bytes",
                )
            document_name = _archive_document_name(member_path, used_names)
            archive_path = member_path.as_posix()
            documents.append(
                {
                    "archive_path": archive_path,
                    "filename": document_name,
                    "extension": ext,
                    "size_bytes": file_size,
                    "metadata": _archive_document_metadata(
                        deposit_filename=deposit_filename or path.name,
                        archive_path=archive_path,
                        document_name=document_name,
                        extension=ext,
                    ),
                    "content": archive.read(info),
                }
            )

    if not documents:
        raise HTTPException(status_code=422, detail="Archive contains no supported documents")
    stats = {
        "truncated_files": truncated_files,
        "skipped_uncompressed_bytes": skipped_uncompressed_bytes,
        "max_files": limit_files,
        "max_uncompressed_bytes": limit_bytes,
    }
    return documents, stats


def build_deposit_archive(
    files: list[DepositFile],
    *,
    links_by_id: dict[str, DepositAccessLink],
    workspace_slug: str,
) -> tuple[Path, str]:
    if not files:
        raise HTTPException(status_code=404, detail="No staged files to archive")

    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    archive_filename = f"{_archive_component(workspace_slug, 'workspace')}-secure-deposit-{stamp}.zip"
    archive_dir = _storage_root() / "_archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".secure-deposit-", suffix=".zip.part", dir=str(archive_dir))
    os.close(fd)
    archive_path = Path(tmp_name)

    manifest: list[dict[str, Any]] = []
    used_names: set[str] = set()
    try:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for file in files:
                source = _storage_path(file.object_key)
                if not source.exists():
                    raise HTTPException(status_code=409, detail=f"Staged file is missing: {file.filename}")
                link = links_by_id.get(file.access_link_id)
                link_label = _archive_component(link.label if link else None, "deposit-link")
                link_access = _archive_component(link.access_id if link else file.access_link_id, file.access_link_id)
                filename = safe_relative_path(file.filename)
                archive_name = _unique_archive_name(
                    f"{link_label}-{link_access}/{file.status}/{filename}",
                    used_names,
                )
                archive.write(source, archive_name)
                manifest.append(
                    {
                        "archive_path": archive_name,
                        "file_id": file.id,
                        "filename": file.filename,
                        "status": file.status,
                        "size_bytes": file.size_bytes,
                        "sha256": file.sha256,
                        "uploaded_at": file.uploaded_at.isoformat() if file.uploaded_at else None,
                        "access_link_id": file.access_link_id,
                        "access_id": link.access_id if link else None,
                        "deposit_link_label": link.label if link else None,
                    }
                )
            archive.writestr(
                "_manifest.json",
                json.dumps(
                    {
                        "workspace": workspace_slug,
                        "generated_at": datetime.utcnow().isoformat() + "Z",
                        "file_count": len(manifest),
                        "files": manifest,
                    },
                    indent=2,
                    sort_keys=True,
                ),
            )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise

    final_path = archive_dir / archive_filename
    if final_path.exists():
        final_path = archive_dir / f"{archive_filename.removesuffix('.zip')}-{secrets.token_hex(4)}.zip"
        archive_filename = final_path.name
    archive_path.replace(final_path)
    return final_path, archive_filename


def extension_for(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def public_url(access_id: str) -> str:
    base = (settings.secure_deposit_public_base_url or "").rstrip("/")
    return f"{base}/deposit/{access_id}" if base else f"/deposit/{access_id}"


def _session_secret() -> str:
    return (
        settings.secure_deposit_session_secret
        or settings.keycloak_client_secret
        or "agentium-dev-secure-deposit-secret"
    )


def issue_session_token(link: DepositAccessLink) -> tuple[str, datetime]:
    expires_at = datetime.utcnow() + timedelta(seconds=settings.secure_deposit_session_ttl_seconds)
    token = jwt.encode(
        {
            "typ": "deposit_session",
            "sub": link.access_id,
            "link_id": link.id,
            "workspace_id": link.workspace_id,
            "exp": expires_at,
            "iat": datetime.utcnow(),
            "jti": secrets.token_urlsafe(10),
        },
        _session_secret(),
        algorithm=_TOKEN_ALGORITHM,
    )
    return token, expires_at


def verify_session_token(token: str, access_id: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, _session_secret(), algorithms=[_TOKEN_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Deposit session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid deposit session")
    if payload.get("typ") != "deposit_session" or payload.get("sub") != access_id:
        raise HTTPException(status_code=401, detail="Invalid deposit session")
    return payload


def serialize_link(link: DepositAccessLink, *, reveal_password: str | None = None) -> dict[str, Any]:
    return {
        "id": link.id,
        "workspace_id": link.workspace_id,
        "created_by_user_id": link.created_by_user_id,
        "label": link.label,
        "access_id": link.access_id,
        "public_url": public_url(link.access_id),
        "status": link.status,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "max_file_size_mb": link.max_file_size_mb,
        "allowed_extensions": link.allowed_extensions or [],
        "created_at": link.created_at.isoformat() if link.created_at else None,
        "updated_at": link.updated_at.isoformat() if link.updated_at else None,
        "generated_password": reveal_password,
    }


def serialize_public_link(link: DepositAccessLink) -> dict[str, Any]:
    return {
        "label": link.label,
        "access_id": link.access_id,
        "public_url": public_url(link.access_id),
        "status": link.status,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "max_file_size_mb": link.max_file_size_mb,
        "allowed_extensions": link.allowed_extensions or [],
    }


def serialize_file(file: DepositFile) -> dict[str, Any]:
    return {
        "id": file.id,
        "access_link_id": file.access_link_id,
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": file.size_bytes,
        "sha256": file.sha256,
        "status": file.status,
        "uploaded_at": file.uploaded_at.isoformat() if file.uploaded_at else None,
        "promoted_at": file.promoted_at.isoformat() if file.promoted_at else None,
        "promoted_collection_slug": file.promoted_collection_slug,
        "worker_job_id": file.worker_job_id,
        "promotion_result": file.promotion_result,
        "rejection_reason": file.rejection_reason,
    }


def serialize_public_file(file: DepositFile) -> dict[str, Any]:
    return {
        "id": file.id,
        "filename": file.filename,
        "content_type": file.content_type,
        "size_bytes": file.size_bytes,
        "sha256": file.sha256,
        "status": file.status,
        "uploaded_at": file.uploaded_at.isoformat() if file.uploaded_at else None,
        "promoted_at": file.promoted_at.isoformat() if file.promoted_at else None,
    }


def get_link_by_access_id(db: DBSession, access_id: str) -> DepositAccessLink:
    link = db.query(DepositAccessLink).filter(DepositAccessLink.access_id == access_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Deposit link not found")
    return link


def assert_link_usable(db: DBSession, link: DepositAccessLink) -> None:
    if link.status != "active":
        raise HTTPException(status_code=403, detail="Deposit link is not active")
    if link.expires_at and link.expires_at < datetime.utcnow():
        link.status = "expired"
        db.flush()
        raise HTTPException(status_code=403, detail="Deposit link has expired")


def create_link(
    db: DBSession,
    *,
    workspace: Workspace,
    user: User,
    label: str,
    expires_at: Optional[datetime],
    max_file_size_mb: Optional[int],
    allowed_extensions: Optional[list[str]],
) -> tuple[DepositAccessLink, str]:
    if not is_workspace_enabled(workspace):
        raise HTTPException(status_code=403, detail="Secure Deposit is not enabled for this workspace")

    password = generate_deposit_password()
    access_id = generate_access_id()
    while db.query(DepositAccessLink).filter(DepositAccessLink.access_id == access_id).first():
        access_id = generate_access_id()

    link = DepositAccessLink(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        label=(label or "External deposit")[:255],
        access_id=access_id,
        password_hash=hash_password(password),
        expires_at=expires_at,
        max_file_size_mb=max_file_size_mb or settings.secure_deposit_default_max_file_size_mb,
        allowed_extensions=(
            default_allowed_extensions()
            if allowed_extensions is None
            else [item.lower().lstrip(".") for item in allowed_extensions if item]
        ),
    )
    db.add(link)
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="deposit.link.created",
        actor=user.email or user.username or user.id,
        details={"access_id": link.access_id, "link_id": link.id, "label": link.label},
    )
    return link, password


def rotate_link_password(
    db: DBSession,
    *,
    link: DepositAccessLink,
    user: User,
) -> str:
    password = generate_deposit_password()
    link.password_hash = hash_password(password)
    link.updated_at = datetime.utcnow()
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=link.workspace_id,
        event_type="deposit.link.password_rotated",
        actor=user.email or user.username or user.id,
        details={"access_id": link.access_id, "link_id": link.id},
    )
    return password


def revoke_link(db: DBSession, *, link: DepositAccessLink, user: User) -> None:
    link.status = "revoked"
    link.updated_at = datetime.utcnow()
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=link.workspace_id,
        event_type="deposit.link.revoked",
        actor=user.email or user.username or user.id,
        details={"access_id": link.access_id, "link_id": link.id},
    )


def authenticate_link(db: DBSession, *, access_id: str, password: str) -> tuple[DepositAccessLink, str, datetime]:
    link = get_link_by_access_id(db, access_id)
    workspace = db.query(Workspace).filter(Workspace.id == link.workspace_id).first()
    if not workspace or not is_workspace_enabled(workspace):
        raise HTTPException(status_code=403, detail="Secure Deposit is not enabled")
    try:
        assert_link_usable(db, link)
    except HTTPException:
        emit_audit_event(
            workspace_id=link.workspace_id,
            event_type="deposit.auth.failed",
            actor=f"deposit:{access_id}",
            severity="warning",
            details={"access_id": access_id, "reason": "inactive_or_expired"},
        )
        raise

    if not verify_password(link.password_hash, password):
        emit_audit_event(
            workspace_id=link.workspace_id,
            event_type="deposit.auth.failed",
            actor=f"deposit:{access_id}",
            severity="warning",
            details={"access_id": access_id, "reason": "bad_password"},
        )
        raise HTTPException(status_code=401, detail="Invalid deposit password")

    token, expires_at = issue_session_token(link)
    emit_audit_event(
        db=db,
        workspace_id=link.workspace_id,
        event_type="deposit.auth.success",
        actor=f"deposit:{access_id}",
        details={"access_id": access_id, "link_id": link.id},
    )
    return link, token, expires_at


async def receive_file(
    db: DBSession,
    *,
    link: DepositAccessLink,
    upload: UploadFile,
) -> DepositFile:
    assert_link_usable(db, link)
    filename = safe_filename(upload.filename)
    allowed = [item.lower().lstrip(".") for item in (link.allowed_extensions or []) if item]
    ext = extension_for(filename)
    if allowed and ext not in allowed:
        emit_audit_event(
            workspace_id=link.workspace_id,
            event_type="deposit.file.rejected",
            actor=f"deposit:{link.access_id}",
            severity="warning",
            details={"access_id": link.access_id, "filename": filename, "reason": "extension_not_allowed"},
        )
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="File extension is not allowed")

    max_bytes = int(link.max_file_size_mb or settings.secure_deposit_default_max_file_size_mb) * 1024 * 1024
    file = DepositFile(
        workspace_id=link.workspace_id,
        access_link_id=link.id,
        filename=filename,
        content_type=upload.content_type,
        object_key="pending",
        size_bytes=0,
        sha256="",
        status="received",
    )
    db.add(file)
    db.flush()
    object_key = _storage_key(
        "workspaces",
        link.workspace_id,
        "secure-deposit",
        link.access_id,
        file.id,
        filename,
    )
    try:
        size_bytes, sha256 = await _write_staged_upload(object_key, upload, max_bytes)
    except HTTPException as exc:
        if exc.status_code == 413:
            emit_audit_event(
                workspace_id=link.workspace_id,
                event_type="deposit.file.rejected",
                actor=f"deposit:{link.access_id}",
                severity="warning",
                details={"access_id": link.access_id, "filename": filename, "reason": "file_too_large"},
            )
        raise
    file.object_key = object_key
    file.size_bytes = size_bytes
    file.sha256 = sha256
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=link.workspace_id,
        event_type="deposit.file.received",
        actor=f"deposit:{link.access_id}",
        details={
            "access_id": link.access_id,
            "link_id": link.id,
            "file_id": file.id,
            "filename": filename,
            "size_bytes": file.size_bytes,
            "sha256": sha256,
        },
    )
    return file


def record_staged_file_from_path(
    db: DBSession,
    *,
    link: DepositAccessLink,
    source_path: Path,
    filename: str,
    content_type: str | None = None,
    actor: str | None = None,
    transport: str = "sftp",
) -> DepositFile:
    """Persist an already-written upload into the Secure Deposit staging store."""

    assert_link_usable(db, link)
    safe_name = safe_relative_path(filename)
    allowed = [item.lower().lstrip(".") for item in (link.allowed_extensions or []) if item]
    ext = extension_for(safe_name)
    audit_actor = actor or f"deposit:{link.access_id}"
    if allowed and ext not in allowed:
        emit_audit_event(
            workspace_id=link.workspace_id,
            event_type="deposit.file.rejected",
            actor=audit_actor,
            severity="warning",
            details={
                "access_id": link.access_id,
                "filename": safe_name,
                "reason": "extension_not_allowed",
                "transport": transport,
            },
        )
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="File extension is not allowed")

    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=400, detail="Uploaded file is missing")

    size_bytes, sha256 = _hash_local_file(source_path)
    max_bytes = int(link.max_file_size_mb or settings.secure_deposit_default_max_file_size_mb) * 1024 * 1024
    if size_bytes > max_bytes:
        emit_audit_event(
            workspace_id=link.workspace_id,
            event_type="deposit.file.rejected",
            actor=audit_actor,
            severity="warning",
            details={
                "access_id": link.access_id,
                "filename": safe_name,
                "reason": "file_too_large",
                "transport": transport,
            },
        )
        raise HTTPException(status_code=413, detail="File is too large")

    file = DepositFile(
        workspace_id=link.workspace_id,
        access_link_id=link.id,
        filename=safe_name,
        content_type=content_type,
        object_key="pending",
        size_bytes=size_bytes,
        sha256=sha256,
        status="received",
    )
    db.add(file)
    db.flush()
    object_key = _storage_key(
        "workspaces",
        link.workspace_id,
        "secure-deposit",
        link.access_id,
        file.id,
        safe_name,
    )
    destination = _storage_path(object_key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), destination)
    file.object_key = object_key
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=link.workspace_id,
        event_type="deposit.file.received",
        actor=audit_actor,
        details={
            "access_id": link.access_id,
            "link_id": link.id,
            "file_id": file.id,
            "filename": safe_name,
            "size_bytes": file.size_bytes,
            "sha256": sha256,
            "transport": transport,
        },
    )
    return file


async def promote_file_to_collection(
    db: DBSession,
    *,
    deposit_file: DepositFile,
    workspace: Workspace,
    user: User,
    collection_slug: str,
) -> DepositFile:
    if deposit_file.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Deposit file not found")
    if deposit_file.status != "received":
        raise HTTPException(status_code=409, detail="Deposit file is not pending promotion")

    default_collection_slug = f"{workspace.slug}-secure-deposit"
    collection_slug = (collection_slug or default_collection_slug).strip() or default_collection_slug
    extension = extension_for(deposit_file.filename or "")
    if extension == "zip":
        return _promote_archive_file_to_collection(
            db,
            deposit_file=deposit_file,
            workspace=workspace,
            user=user,
            collection_slug=collection_slug,
        )
    if extension in _LEGACY_SPREADSHEET_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail="Legacy .xls spreadsheets are not supported for Knowledge promotion yet",
        )
    if extension in _SPREADSHEET_EXTENSIONS:
        return _promote_single_worker_file_to_collection(
            db,
            deposit_file=deposit_file,
            workspace=workspace,
            user=user,
            collection_slug=collection_slug,
            mode="spreadsheet",
        )

    app_settings = get_resolved_settings(workspace_id=workspace.id)
    db_type = (
        app_settings.get("ragVectorDBType")
        or settings.default_vector_db_type
        or "faiss"
    )
    tmp_dir = tempfile.mkdtemp()
    try:
        tmp_path = Path(tmp_dir) / deposit_file.filename
        _copy_staged_to_local(deposit_file.object_key, tmp_path)
        doc_service = DocumentService(
            collection_name=collection_slug,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        result = await doc_service.ingest_document(str(tmp_path))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    deposit_file.status = "promoted"
    deposit_file.promoted_at = datetime.utcnow()
    deposit_file.promoted_by_user_id = user.id
    deposit_file.promoted_collection_slug = collection_slug
    deposit_file.promotion_result = result
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="deposit.file.promoted",
        actor=user.email or user.username or user.id,
        details={
            "file_id": deposit_file.id,
            "filename": deposit_file.filename,
            "collection_slug": collection_slug,
            "result": result,
        },
    )
    return deposit_file


def _single_document_name(deposit_file: DepositFile) -> str:
    raw_name = str(deposit_file.filename or "upload").replace("\\", "/")
    safe_path = safe_relative_path(raw_name)
    return safe_path.replace("/", "__")


def _promote_single_worker_file_to_collection(
    db: DBSession,
    *,
    deposit_file: DepositFile,
    workspace: Workspace,
    user: User,
    collection_slug: str,
    mode: str,
) -> DepositFile:
    source_path = staged_file_path(deposit_file)
    document_name = _single_document_name(deposit_file)
    collection = create_or_get_collection(
        db,
        workspace=workspace,
        name=collection_slug,
        description=f"Secure Deposit {mode} promotion from {deposit_file.filename}",
        created_by_user_id=user.id,
        slug=collection_slug,
    )
    store = get_object_store()
    existing_names = list(collection.document_names or [])
    if document_name not in existing_names:
        existing_names.append(document_name)
    store.write_bytes(original_key(collection, document_name), source_path.read_bytes())

    update_collection_status(
        db,
        collection.id,
        status="queued",
        document_names=existing_names,
        document_count=len(existing_names),
    )
    job = create_worker_job(
        db,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    db.commit()
    db.refresh(job)
    db.refresh(collection)

    celery_task_id = dispatch_worker_job(db, job)
    db.commit()
    db.refresh(job)
    db.refresh(collection)

    result = {
        "status": "queued",
        "mode": mode,
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "job_id": job.id,
        "celery_task_id": job.celery_task_id or celery_task_id,
        mode: {
            "filename": deposit_file.filename,
            "document_name": document_name,
            "extension": extension_for(deposit_file.filename or ""),
            "size_bytes": deposit_file.size_bytes,
        },
    }
    deposit_file.status = "promoted"
    deposit_file.promoted_at = datetime.utcnow()
    deposit_file.promoted_by_user_id = user.id
    deposit_file.promoted_collection_slug = collection.slug
    deposit_file.worker_job_id = job.id
    deposit_file.promotion_result = result
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="deposit.file.promoted",
        actor=user.email or user.username or user.id,
        details={
            "file_id": deposit_file.id,
            "filename": deposit_file.filename,
            "collection_slug": collection.slug,
            "worker_job_id": job.id,
            "mode": mode,
            "result": result,
        },
    )
    return deposit_file


def promote_files_to_collection_batch(
    db: DBSession,
    *,
    deposit_files: list[DepositFile],
    workspace: Workspace,
    user: User,
    collection_slug: str,
) -> dict[str, Any]:
    """Promote several Knowledge-supported deposit files with one worker job.

    Qdrant itself supports incremental upserts. The single-job constraint comes
    from Agentium's current canonical worker: ``document_ingest_index`` reloads
    ``collection.document_names`` and ingests that full collection snapshot.
    Dispatching one job per deposit file would therefore re-ingest the same
    growing collection repeatedly.
    """
    if len(deposit_files) > _BULK_PROMOTION_MAX_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"Bulk promotion is limited to {_BULK_PROMOTION_MAX_FILES} files",
        )

    default_collection_slug = f"{workspace.slug}-secure-deposit"
    collection_slug = (collection_slug or default_collection_slug).strip() or default_collection_slug
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    document_total = 0

    for deposit_file in deposit_files:
        if deposit_file.id in seen_ids:
            continue
        seen_ids.add(deposit_file.id)
        reason = ""
        extension = extension_for(deposit_file.filename or "")
        source_path: Path | None = None
        if deposit_file.workspace_id != workspace.id:
            reason = "wrong_workspace"
        elif deposit_file.status != "received":
            reason = f"status_{deposit_file.status}"
        else:
            source_path = staged_file_path(deposit_file)
            if extension in _LEGACY_SPREADSHEET_EXTENSIONS:
                reason = "legacy_xls_unsupported"
            elif extension != "zip" and extension not in _WORKER_PROMOTION_EXTENSIONS:
                reason = "unsupported_for_knowledge_bulk"
            else:
                if not source_path.exists():
                    reason = "staged_file_missing"
                elif (deposit_file.size_bytes or 0) <= 0:
                    reason = "empty_file"
                elif extension in _SPREADSHEET_EXTENSIONS and not zipfile.is_zipfile(source_path):
                    reason = "invalid_office_spreadsheet"

        if reason:
            skipped.append({"file_id": deposit_file.id, "filename": deposit_file.filename or "", "reason": reason})
            continue

        if source_path is None:
            source_path = staged_file_path(deposit_file)

        if extension == "zip":
            try:
                archive_documents, _archive_stats = _read_supported_archive_documents(
                    source_path,
                    deposit_filename=deposit_file.filename,
                )
            except HTTPException as exc:
                skipped.append(
                    {
                        "file_id": deposit_file.id,
                        "filename": deposit_file.filename or "",
                        "reason": f"archive_{exc.detail}",
                    }
                )
                continue
            document_total += len(archive_documents)
            selected.append(
                {
                    "deposit_file": deposit_file,
                    "mode": "archive",
                    "extension": extension,
                    "documents": archive_documents,
                }
            )
        else:
            document_total += 1
            selected.append(
                {
                    "deposit_file": deposit_file,
                    "mode": "document",
                    "extension": extension,
                    "documents": [
                        {
                            "filename": _single_document_name(deposit_file),
                            "extension": extension,
                            "size_bytes": int(deposit_file.size_bytes or 0),
                            "metadata": _archive_document_metadata(
                                deposit_filename=deposit_file.filename,
                                archive_path=None,
                                document_name=_single_document_name(deposit_file),
                                extension=extension,
                            ),
                            "source_path": source_path,
                        }
                    ],
                }
            )

        if document_total > _BULK_PROMOTION_MAX_DOCUMENTS:
            raise HTTPException(
                status_code=413,
                detail=f"Bulk promotion is limited to {_BULK_PROMOTION_MAX_DOCUMENTS} extracted documents",
            )

    if not selected:
        raise HTTPException(status_code=422, detail={"message": "No promotable Knowledge documents found", "skipped": skipped})

    collection = create_or_get_collection(
        db,
        workspace=workspace,
        name=collection_slug,
        description=f"Secure Deposit bulk promotion ({len(selected)} files)",
        created_by_user_id=user.id,
        slug=collection_slug,
    )
    store = get_object_store()
    document_names = list(collection.document_names or [])
    document_name_set = set(document_names)
    manifest_key = document_manifest_key(collection)
    document_manifest: dict[str, Any] = {}
    if store.exists(manifest_key):
        try:
            loaded_manifest = json.loads(store.read_bytes(manifest_key).decode("utf-8"))
            if isinstance(loaded_manifest, dict):
                document_manifest = loaded_manifest
        except Exception:
            document_manifest = {}

    promoted_payload: list[dict[str, Any]] = []
    for item in selected:
        deposit_file: DepositFile = item["deposit_file"]
        item_documents: list[dict[str, Any]] = []
        for document in item["documents"]:
            document_name = str(document["filename"])
            if "content" in document:
                store.write_bytes(original_key(collection, document_name), document["content"])
            else:
                store.write_bytes(original_key(collection, document_name), Path(document["source_path"]).read_bytes())
            if document_name not in document_name_set:
                document_names.append(document_name)
                document_name_set.add(document_name)
            document_metadata = dict(document.get("metadata") or {})
            if document_metadata:
                document_manifest[document_name] = document_metadata
            item_documents.append(
                {
                    "document_name": document_name,
                    "archive_path": document.get("archive_path"),
                    "extension": document.get("extension") or item["extension"],
                    "size_bytes": int(document.get("size_bytes") or deposit_file.size_bytes or 0),
                    "metadata": document_metadata,
                }
            )
        promoted_payload.append(
            {
                "file_id": deposit_file.id,
                "filename": deposit_file.filename,
                "mode": item["mode"],
                "extension": item["extension"],
                "size_bytes": deposit_file.size_bytes,
                "documents": item_documents,
            }
        )
    store.write_text(manifest_key, json.dumps(document_manifest, ensure_ascii=True, indent=2, sort_keys=True))

    update_collection_status(
        db,
        collection.id,
        status="queued",
        document_names=document_names,
        document_count=len(document_names),
    )
    job = create_worker_job(
        db,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    db.commit()
    db.refresh(job)
    db.refresh(collection)

    celery_task_id = dispatch_worker_job(db, job)
    db.commit()
    db.refresh(job)
    db.refresh(collection)

    result = {
        "status": "queued",
        "mode": "document_bulk",
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "job_id": job.id,
        "celery_task_id": job.celery_task_id or celery_task_id,
        "promoted_count": len(selected),
        "document_count": document_total,
        "skipped": skipped,
        "files": promoted_payload,
    }

    for item in selected:
        deposit_file: DepositFile = item["deposit_file"]
        file_payload = next((payload for payload in promoted_payload if payload["file_id"] == deposit_file.id), {})
        file_result = {
            **result,
            "file": file_payload,
        }
        deposit_file.status = "promoted"
        deposit_file.promoted_at = datetime.utcnow()
        deposit_file.promoted_by_user_id = user.id
        deposit_file.promoted_collection_slug = collection.slug
        deposit_file.worker_job_id = job.id
        deposit_file.promotion_result = file_result
        emit_audit_event(
            db=db,
            workspace_id=workspace.id,
            event_type="deposit.file.promoted",
            actor=user.email or user.username or user.id,
            details={
                "file_id": deposit_file.id,
                "filename": deposit_file.filename,
                "collection_slug": collection.slug,
                "worker_job_id": job.id,
                "mode": "document_bulk",
                "result": file_result,
            },
        )

    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="deposit.bulk_promote.created",
        actor=user.email or user.username or user.id,
        details={
            "collection_slug": collection.slug,
            "worker_job_id": job.id,
            "promoted_count": len(selected),
            "document_count": document_total,
            "skipped_count": len(skipped),
        },
    )
    db.flush()
    return {
        "collection": collection,
        "job": job,
        "promoted_files": [item["deposit_file"] for item in selected],
        "skipped": skipped,
        "result": result,
    }


def promote_spreadsheet_files_to_collection(
    db: DBSession,
    *,
    deposit_files: list[DepositFile],
    workspace: Workspace,
    user: User,
    collection_slug: str,
) -> dict[str, Any]:
    """Backward-compatible wrapper for older callers/tests."""
    return promote_files_to_collection_batch(
        db,
        deposit_files=deposit_files,
        workspace=workspace,
        user=user,
        collection_slug=collection_slug,
    )


def _promote_archive_file_to_collection(
    db: DBSession,
    *,
    deposit_file: DepositFile,
    workspace: Workspace,
    user: User,
    collection_slug: str,
) -> DepositFile:
    archive_path = staged_file_path(deposit_file)
    documents, _archive_stats = _read_supported_archive_documents(archive_path, deposit_filename=deposit_file.filename)

    collection = create_or_get_collection(
        db,
        workspace=workspace,
        name=collection_slug,
        description=f"Secure Deposit archive promotion from {deposit_file.filename}",
        created_by_user_id=user.id,
        slug=collection_slug,
    )
    store = get_object_store()
    existing_names = list(collection.document_names or [])
    extracted_manifest: list[dict[str, Any]] = []
    manifest_key = document_manifest_key(collection)
    document_manifest: dict[str, Any] = {}
    if store.exists(manifest_key):
        try:
            loaded_manifest = json.loads(store.read_bytes(manifest_key).decode("utf-8"))
            if isinstance(loaded_manifest, dict):
                document_manifest = loaded_manifest
        except Exception:
            document_manifest = {}
    for document in documents:
        filename = str(document["filename"])
        store.write_bytes(original_key(collection, filename), document["content"])
        if filename not in existing_names:
            existing_names.append(filename)
        document_metadata = dict(document.get("metadata") or {})
        if document_metadata:
            document_manifest[filename] = document_metadata
        extracted_manifest.append(
            {
                "archive_path": document["archive_path"],
                "filename": filename,
                "extension": document["extension"],
                "size_bytes": document["size_bytes"],
                "metadata": document_metadata,
            }
        )
    store.write_text(manifest_key, json.dumps(document_manifest, ensure_ascii=True, indent=2, sort_keys=True))

    update_collection_status(
        db,
        collection.id,
        status="queued",
        document_names=existing_names,
        document_count=len(existing_names),
    )
    job = create_worker_job(
        db,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    db.commit()
    db.refresh(job)
    db.refresh(collection)

    celery_task_id = dispatch_worker_job(db, job)
    db.commit()
    db.refresh(job)
    db.refresh(collection)

    result = {
        "status": "queued",
        "mode": "archive",
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "job_id": job.id,
        "celery_task_id": job.celery_task_id or celery_task_id,
        "archive": {
            "filename": deposit_file.filename,
            "supported_extensions": sorted(_ARCHIVE_PROMOTION_EXTENSIONS),
            "max_files": int(settings.secure_deposit_archive_promotion_max_files or 50),
            "extracted_count": len(extracted_manifest),
            "documents": extracted_manifest,
        },
    }
    deposit_file.status = "promoted"
    deposit_file.promoted_at = datetime.utcnow()
    deposit_file.promoted_by_user_id = user.id
    deposit_file.promoted_collection_slug = collection.slug
    deposit_file.worker_job_id = job.id
    deposit_file.promotion_result = result
    db.flush()
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="deposit.file.promoted",
        actor=user.email or user.username or user.id,
        details={
            "file_id": deposit_file.id,
            "filename": deposit_file.filename,
            "collection_slug": collection.slug,
            "worker_job_id": job.id,
            "archive_extracted_count": len(extracted_manifest),
            "result": result,
        },
    )
    db.commit()
    db.refresh(deposit_file)
    return deposit_file
