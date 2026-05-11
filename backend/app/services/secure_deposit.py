"""Secure Deposit service.

This module backs both the public web drop portal and the future SFTP
subsystem. A deposit link is workspace-bound, password-protected, and writes
only to staging until an authorized Agentium user promotes a file to Knowledge.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import shutil
import tempfile
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
from app.services.rag.document_service import DocumentService

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


def _copy_staged_to_local(key: str, destination: Path) -> Path:
    source = _storage_path(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


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
        allowed_extensions=allowed_extensions or default_allowed_extensions(),
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

    content = await upload.read()
    max_bytes = int(link.max_file_size_mb or settings.secure_deposit_default_max_file_size_mb) * 1024 * 1024
    if len(content) > max_bytes:
        emit_audit_event(
            workspace_id=link.workspace_id,
            event_type="deposit.file.rejected",
            actor=f"deposit:{link.access_id}",
            severity="warning",
            details={"access_id": link.access_id, "filename": filename, "reason": "file_too_large"},
        )
        raise HTTPException(status_code=413, detail="File is too large")

    sha256 = hashlib.sha256(content).hexdigest()
    file = DepositFile(
        workspace_id=link.workspace_id,
        access_link_id=link.id,
        filename=filename,
        content_type=upload.content_type,
        object_key="pending",
        size_bytes=len(content),
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
        filename,
    )
    _write_staged_bytes(object_key, content)
    file.object_key = object_key
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

    collection_slug = (collection_slug or "andritz-secure-deposit").strip() or "andritz-secure-deposit"
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
