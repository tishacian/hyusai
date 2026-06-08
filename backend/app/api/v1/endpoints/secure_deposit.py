"""Secure Deposit public portal and internal workspace APIs."""
from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from starlette.background import BackgroundTask

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import enforce_permission, evaluate_permission
from app.db.base import get_db
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.secure_deposit import (
    authenticate_link,
    build_indexing_assist_snapshot,
    assert_link_usable,
    build_deposit_archive,
    create_link,
    default_allowed_extensions,
    extract_deposit_zip_member_to_temp,
    get_link_by_access_id,
    is_workspace_enabled,
    list_deposit_zip_archive,
    promote_files_to_collection_batch,
    promote_file_to_collection,
    preview_deposit_file,
    preview_deposit_zip_member,
    receive_file,
    revoke_link,
    rotate_link_password,
    serialize_file,
    serialize_link,
    serialize_public_file,
    serialize_public_link,
    staged_file_download_name,
    staged_file_media_type,
    staged_file_path,
    verify_session_token,
)
from app.services.secure_deposit_operations import (
    SFTP_DEFAULT_STALE_AFTER_HOURS,
    SFTP_RECONCILIATION_JOB_KIND,
    get_sftp_operations_snapshot,
)
from app.services.audit_logger import emit_audit_event
from app.services.workspace_jobs import create_workspace_job, dispatch_workspace_job, serialize_job

public_router = APIRouter()
internal_router = APIRouter()

CAPABILITY_ATTRS = {"capability": "secure_deposit"}
MAX_DEPOSIT_FILE_SIZE_MB = 30 * 1024


class PublicSessionRequest(BaseModel):
    password: str = Field(min_length=1)


class DepositLinkCreateRequest(BaseModel):
    label: str = Field(default="External deposit", max_length=255)
    expires_at: Optional[datetime] = None
    max_file_size_mb: Optional[int] = Field(default=None, ge=1, le=MAX_DEPOSIT_FILE_SIZE_MB)
    allowed_extensions: Optional[list[str]] = None


class DepositLinkPatchRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=255)
    expires_at: Optional[datetime] = None
    max_file_size_mb: Optional[int] = Field(default=None, ge=1, le=MAX_DEPOSIT_FILE_SIZE_MB)
    allowed_extensions: Optional[list[str]] = None


class DepositPromoteRequest(BaseModel):
    collection_slug: Optional[str] = Field(default=None, max_length=120)


class DepositBulkPromoteRequest(BaseModel):
    collection_slug: Optional[str] = Field(default=None, max_length=120)
    file_ids: list[str] = Field(default_factory=list)


class DepositIndexingAssistRequest(BaseModel):
    collection_slug: Optional[str] = Field(default=None, max_length=120)
    file_ids: list[str] = Field(default_factory=list)


class SftpReconcileRequest(BaseModel):
    mode: str = Field(default="dry_run", pattern="^(dry_run|quarantine)$")
    stale_after_hours: int = Field(default=SFTP_DEFAULT_STALE_AFTER_HOURS, ge=1, le=720)
    confirm_from_job_id: Optional[str] = Field(default=None, max_length=80)


def _bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing deposit session")
    return authorization.split(" ", 1)[1].strip()


def _public_link_from_session(
    db: DBSession,
    *,
    access_id: str,
    authorization: str | None,
) -> DepositAccessLink:
    verify_session_token(_bearer_token(authorization), access_id)
    link = get_link_by_access_id(db, access_id)
    assert_link_usable(db, link)
    return link


def _workspace_link(db: DBSession, workspace: Workspace, link_id: str) -> DepositAccessLink:
    link = (
        db.query(DepositAccessLink)
        .filter(DepositAccessLink.id == link_id, DepositAccessLink.workspace_id == workspace.id)
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Deposit link not found")
    return link


def _workspace_file(db: DBSession, workspace: Workspace, file_id: str) -> DepositFile:
    file = (
        db.query(DepositFile)
        .filter(DepositFile.id == file_id, DepositFile.workspace_id == workspace.id)
        .first()
    )
    if not file:
        raise HTTPException(status_code=404, detail="Deposit file not found")
    return file


def _workspace_file_link(
    db: DBSession,
    workspace: Workspace,
    file: DepositFile,
) -> DepositAccessLink:
    return _workspace_link(db, workspace, file.access_link_id)


def _can_read_all(db: DBSession, *, user: User, workspace: Workspace, resource_kind: str) -> bool:
    decision = evaluate_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind=resource_kind,
        action="read_all",
        resource_attrs=CAPABILITY_ATTRS,
        audit_prefix="deposit",
        audit_denials=False,
    )
    return decision.allowed


def _enforce(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    resource_kind: str,
    action: str,
    resource_attrs: Optional[dict] = None,
) -> None:
    attrs = {**CAPABILITY_ATTRS, **(resource_attrs or {})}
    enforce_permission(
        db,
        user=user,
        workspace=workspace,
        resource_kind=resource_kind,
        action=action,
        resource_attrs=attrs,
        audit_prefix="deposit",
    )


def _enforce_file_read(
    db: DBSession,
    *,
    user: User,
    workspace: Workspace,
    file: DepositFile,
    link: DepositAccessLink,
) -> None:
    if _can_read_all(db, user=user, workspace=workspace, resource_kind="deposit_file"):
        return
    _enforce(
        db,
        user=user,
        workspace=workspace,
        resource_kind="deposit_file",
        action="read",
        resource_attrs={
            "file_id": file.id,
            "link_id": link.id,
            "created_by_user_id": link.created_by_user_id,
        },
    )


def _cleanup_archive(path: Path) -> None:
    path.unlink(missing_ok=True)


@public_router.post("/{access_id}/session")
def create_public_deposit_session(
    access_id: str,
    body: PublicSessionRequest,
    db: DBSession = Depends(get_db),
):
    link, token, expires_at = authenticate_link(db, access_id=access_id, password=body.password)
    db.commit()
    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "link": serialize_public_link(link),
        "files": [serialize_public_file(file) for file in link.files],
    }


@public_router.get("/{access_id}/files")
def list_public_deposit_files(
    access_id: str,
    authorization: str | None = Header(None, alias="Authorization"),
    db: DBSession = Depends(get_db),
):
    link = _public_link_from_session(db, access_id=access_id, authorization=authorization)
    files = (
        db.query(DepositFile)
        .filter(DepositFile.access_link_id == link.id)
        .order_by(DepositFile.uploaded_at.desc())
        .all()
    )
    return {"link": serialize_public_link(link), "files": [serialize_public_file(file) for file in files]}


@public_router.post("/{access_id}/files")
async def upload_public_deposit_file(
    access_id: str,
    authorization: str | None = Header(None, alias="Authorization"),
    file: UploadFile = File(...),
    db: DBSession = Depends(get_db),
):
    link = _public_link_from_session(db, access_id=access_id, authorization=authorization)
    row = await receive_file(db, link=link, upload=file)
    db.commit()
    db.refresh(row)
    return {"file": serialize_public_file(row)}


@internal_router.get("/health")
def secure_deposit_health(
    workspace: Workspace = Depends(get_current_workspace),
):
    return {
        "status": "ok",
        "workspace": workspace.slug,
        "enabled": is_workspace_enabled(workspace),
        "default_allowed_extensions": default_allowed_extensions(),
    }


@internal_router.get("/operations")
def sftp_operations(
    stale_after_hours: int = Query(default=SFTP_DEFAULT_STALE_AFTER_HOURS, ge=1, le=720),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    _enforce(db, user=user, workspace=workspace, resource_kind="deposit_file", action="read_all")
    return get_sftp_operations_snapshot(db, workspace=workspace, stale_after_hours=stale_after_hours)


@internal_router.post("/operations/reconcile")
def run_sftp_reconciliation(
    body: SftpReconcileRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    _enforce(db, user=user, workspace=workspace, resource_kind="deposit_file", action="operate")
    if body.mode == "quarantine" and not body.confirm_from_job_id:
        raise HTTPException(status_code=422, detail="confirm_from_job_id is required for quarantine")
    actor = user.email or user.username or user.id
    job = create_workspace_job(
        db,
        workspace,
        user,
        kind=SFTP_RECONCILIATION_JOB_KIND,
        title="SFTP reconciliation",
        input_ref={
            "mode": body.mode,
            "stale_after_hours": body.stale_after_hours,
            "confirm_from_job_id": body.confirm_from_job_id,
            "actor": actor,
        },
        status="queued",
    )
    dispatch_workspace_job(db, workspace, job, allow_inline_fallback=False)
    db.commit()
    return {"job": serialize_job(job)}


@internal_router.get("/links")
def list_deposit_links(
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    query = db.query(DepositAccessLink).filter(DepositAccessLink.workspace_id == workspace.id)
    if not _can_read_all(db, user=user, workspace=workspace, resource_kind="deposit_link"):
        query = query.filter(DepositAccessLink.created_by_user_id == user.id)
    links = query.order_by(DepositAccessLink.created_at.desc()).all()
    creators = {
        row.id: row.email or row.username or row.id
        for row in db.query(User)
        .filter(User.id.in_([link.created_by_user_id for link in links] or ["__none__"]))
        .all()
    }
    payload = []
    for link in links:
        item = serialize_link(link)
        item["created_by"] = creators.get(link.created_by_user_id, link.created_by_user_id)
        payload.append(item)
    return {"links": payload}


@internal_router.post("/links")
def create_deposit_link(
    body: DepositLinkCreateRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    _enforce(db, user=user, workspace=workspace, resource_kind="deposit_link", action="create")
    link, password = create_link(
        db,
        workspace=workspace,
        user=user,
        label=body.label,
        expires_at=body.expires_at,
        max_file_size_mb=body.max_file_size_mb,
        allowed_extensions=body.allowed_extensions,
    )
    db.commit()
    db.refresh(link)
    return {"link": serialize_link(link, reveal_password=password)}


@internal_router.patch("/links/{link_id}")
def update_deposit_link(
    link_id: str,
    body: DepositLinkPatchRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    link = _workspace_link(db, workspace, link_id)
    _enforce(
        db,
        user=user,
        workspace=workspace,
        resource_kind="deposit_link",
        action="update",
        resource_attrs={"created_by_user_id": link.created_by_user_id},
    )
    if body.label is not None:
        link.label = body.label
    if body.expires_at is not None:
        link.expires_at = body.expires_at
    if body.max_file_size_mb is not None:
        link.max_file_size_mb = body.max_file_size_mb
    if body.allowed_extensions is not None:
        link.allowed_extensions = [item.lower().lstrip(".") for item in body.allowed_extensions]
    db.commit()
    db.refresh(link)
    return {"link": serialize_link(link)}


@internal_router.post("/links/{link_id}/rotate")
def rotate_deposit_link(
    link_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    link = _workspace_link(db, workspace, link_id)
    _enforce(
        db,
        user=user,
        workspace=workspace,
        resource_kind="deposit_link",
        action="update",
        resource_attrs={"created_by_user_id": link.created_by_user_id},
    )
    password = rotate_link_password(db, link=link, user=user)
    db.commit()
    db.refresh(link)
    return {"link": serialize_link(link, reveal_password=password)}


@internal_router.post("/links/{link_id}/revoke")
def revoke_deposit_link(
    link_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    link = _workspace_link(db, workspace, link_id)
    _enforce(
        db,
        user=user,
        workspace=workspace,
        resource_kind="deposit_link",
        action="revoke",
        resource_attrs={"created_by_user_id": link.created_by_user_id},
    )
    revoke_link(db, link=link, user=user)
    db.commit()
    db.refresh(link)
    return {"link": serialize_link(link)}


@internal_router.get("/deposits")
def list_deposit_files(
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    query = db.query(DepositFile).filter(DepositFile.workspace_id == workspace.id)
    if not _can_read_all(db, user=user, workspace=workspace, resource_kind="deposit_file"):
        owned_link_ids = [
            row.id
            for row in db.query(DepositAccessLink.id)
            .filter(
                DepositAccessLink.workspace_id == workspace.id,
                DepositAccessLink.created_by_user_id == user.id,
            )
            .all()
        ]
        query = query.filter(DepositFile.access_link_id.in_(owned_link_ids or ["__none__"]))
    files = query.order_by(DepositFile.uploaded_at.desc()).all()
    return {"files": [serialize_file(file) for file in files]}


@internal_router.get("/deposits/archive")
def download_deposit_files_archive(
    link_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, pattern="^(received|rejected|promoted)$"),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    _enforce(db, user=user, workspace=workspace, resource_kind="deposit_file", action="download_archive")
    query = db.query(DepositFile).filter(DepositFile.workspace_id == workspace.id)
    selected_link: DepositAccessLink | None = None
    if link_id:
        selected_link = _workspace_link(db, workspace, link_id)
        query = query.filter(DepositFile.access_link_id == selected_link.id)
    if status:
        query = query.filter(DepositFile.status == status)
    else:
        query = query.filter(DepositFile.status != "rejected")
    files = query.order_by(DepositFile.uploaded_at.desc()).all()
    link_ids = [file.access_link_id for file in files]
    links_by_id = {
        link.id: link
        for link in db.query(DepositAccessLink)
        .filter(
            DepositAccessLink.workspace_id == workspace.id,
            DepositAccessLink.id.in_(link_ids or ["__none__"]),
        )
        .all()
    }
    archive_path, archive_filename = build_deposit_archive(
        files,
        links_by_id=links_by_id,
        workspace_slug=workspace.slug,
    )
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="deposit.queue.downloaded",
        actor=user.email or user.username or user.id,
        details={
            "file_count": len(files),
            "link_id": selected_link.id if selected_link else None,
            "access_id": selected_link.access_id if selected_link else None,
            "status": status,
            "archive_filename": archive_filename,
        },
    )
    db.commit()
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=archive_filename,
        background=BackgroundTask(_cleanup_archive, archive_path),
    )


@internal_router.get("/deposits/{file_id}/preview")
def preview_deposit_staged_file(
    file_id: str,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    file = _workspace_file(db, workspace, file_id)
    link = _workspace_file_link(db, workspace, file)
    _enforce_file_read(db, user=user, workspace=workspace, file=file, link=link)
    payload = preview_deposit_file(file)
    payload["file"] = serialize_file(file)
    return payload


@internal_router.get("/deposits/{file_id}/archive")
def browse_deposit_zip_archive(
    file_id: str,
    path: str = Query(default=""),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    file = _workspace_file(db, workspace, file_id)
    link = _workspace_file_link(db, workspace, file)
    _enforce_file_read(db, user=user, workspace=workspace, file=file, link=link)
    payload = list_deposit_zip_archive(file, path=path)
    payload["file"] = serialize_file(file)
    return payload


@internal_router.get("/deposits/{file_id}/archive/member/preview")
def preview_deposit_zip_archive_member(
    file_id: str,
    path: str = Query(min_length=1),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    file = _workspace_file(db, workspace, file_id)
    link = _workspace_file_link(db, workspace, file)
    _enforce_file_read(db, user=user, workspace=workspace, file=file, link=link)
    payload = preview_deposit_zip_member(file, member_path=path)
    payload["file"] = serialize_file(file)
    payload["archive_path"] = path
    return payload


@internal_router.get("/deposits/{file_id}/archive/member/download")
def download_deposit_zip_archive_member(
    file_id: str,
    path: str = Query(min_length=1),
    disposition: str = Query(default="attachment", pattern="^(attachment|inline)$"),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    file = _workspace_file(db, workspace, file_id)
    link = _workspace_file_link(db, workspace, file)
    _enforce_file_read(db, user=user, workspace=workspace, file=file, link=link)
    temp_path, info, filename = extract_deposit_zip_member_to_temp(file, member_path=path)
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="deposit.archive_member.downloaded",
        actor=user.email or user.username or user.id,
        details={
            "file_id": file.id,
            "link_id": link.id,
            "access_id": link.access_id,
            "filename": file.filename,
            "archive_path": info.filename,
            "size_bytes": info.file_size,
            "disposition": disposition,
        },
    )
    db.commit()
    return FileResponse(
        temp_path,
        media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
        filename=filename,
        content_disposition_type=disposition,
        background=BackgroundTask(_cleanup_archive, temp_path),
    )


@internal_router.get("/deposits/{file_id}/download")
def download_deposit_staged_file(
    file_id: str,
    disposition: str = Query(default="attachment", pattern="^(attachment|inline)$"),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    file = _workspace_file(db, workspace, file_id)
    link = _workspace_file_link(db, workspace, file)
    _enforce_file_read(db, user=user, workspace=workspace, file=file, link=link)
    path = staged_file_path(file)
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="deposit.file.downloaded",
        actor=user.email or user.username or user.id,
        details={
            "file_id": file.id,
            "link_id": link.id,
            "access_id": link.access_id,
            "filename": file.filename,
            "size_bytes": file.size_bytes,
            "disposition": disposition,
        },
    )
    db.commit()
    return FileResponse(
        path,
        media_type=staged_file_media_type(file),
        filename=staged_file_download_name(file),
        content_disposition_type=disposition,
    )


@internal_router.post("/deposits/indexing-assist")
def get_deposit_indexing_assist(
    body: DepositIndexingAssistRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    file_ids = [file_id for file_id in body.file_ids if file_id]
    if not _can_read_all(db, user=user, workspace=workspace, resource_kind="deposit_file"):
        owned_link_ids = [
            row.id
            for row in db.query(DepositAccessLink.id)
            .filter(
                DepositAccessLink.workspace_id == workspace.id,
                DepositAccessLink.created_by_user_id == user.id,
            )
            .all()
        ]
        visible_file_ids = {
            row.id
            for row in db.query(DepositFile.id)
            .filter(
                DepositFile.workspace_id == workspace.id,
                DepositFile.id.in_(file_ids or ["__none__"]),
                DepositFile.access_link_id.in_(owned_link_ids or ["__none__"]),
            )
            .all()
        }
        file_ids = [file_id for file_id in file_ids if file_id in visible_file_ids]
    return build_indexing_assist_snapshot(
        db,
        workspace=workspace,
        file_ids=file_ids,
        collection_slug=body.collection_slug,
    )


@internal_router.post("/deposits/{file_id}/promote")
async def promote_deposit_file(
    file_id: str,
    body: DepositPromoteRequest = Body(default_factory=DepositPromoteRequest),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    _enforce(db, user=user, workspace=workspace, resource_kind="deposit_file", action="promote")
    file = _workspace_file(db, workspace, file_id)
    row = await promote_file_to_collection(
        db,
        deposit_file=file,
        workspace=workspace,
        user=user,
        collection_slug=body.collection_slug,
    )
    db.commit()
    db.refresh(row)
    return {"file": serialize_file(row)}


@internal_router.post("/deposits/promote-bulk")
def promote_deposit_files_bulk(
    body: DepositBulkPromoteRequest,
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    _enforce(db, user=user, workspace=workspace, resource_kind="deposit_file", action="promote")
    file_ids = [file_id for file_id in body.file_ids if file_id]
    if not file_ids:
        raise HTTPException(status_code=422, detail="file_ids is required")
    if len(file_ids) > 50:
        raise HTTPException(status_code=422, detail="Bulk promotion is limited to 50 files")

    rows = (
        db.query(DepositFile)
        .filter(DepositFile.workspace_id == workspace.id, DepositFile.id.in_(file_ids))
        .all()
    )
    rows_by_id = {row.id: row for row in rows}
    missing = [file_id for file_id in file_ids if file_id not in rows_by_id]
    if missing:
        raise HTTPException(status_code=404, detail={"message": "Some deposit files were not found", "file_ids": missing})

    payload = promote_files_to_collection_batch(
        db,
        deposit_files=[rows_by_id[file_id] for file_id in file_ids],
        workspace=workspace,
        user=user,
        collection_slug=body.collection_slug or "",
    )
    db.commit()
    for row in payload["promoted_files"]:
        db.refresh(row)
    return {
        "files": [serialize_file(row) for row in payload["promoted_files"]],
        "skipped": payload["skipped"],
        "result": payload["result"],
    }
