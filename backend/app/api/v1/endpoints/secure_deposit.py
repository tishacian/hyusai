"""Secure Deposit public portal and internal workspace APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.iam.dependencies import enforce_permission, evaluate_permission
from app.db.base import get_db
from app.models.secure_deposit import DepositAccessLink, DepositFile
from app.models.user import User
from app.models.workspace import Workspace
from app.services.secure_deposit import (
    authenticate_link,
    assert_link_usable,
    create_link,
    default_allowed_extensions,
    get_link_by_access_id,
    is_workspace_enabled,
    promote_file_to_collection,
    receive_file,
    revoke_link,
    rotate_link_password,
    serialize_file,
    serialize_link,
    serialize_public_file,
    serialize_public_link,
    verify_session_token,
)

public_router = APIRouter()
internal_router = APIRouter()

CAPABILITY_ATTRS = {"capability": "secure_deposit"}


class PublicSessionRequest(BaseModel):
    password: str = Field(min_length=1)


class DepositLinkCreateRequest(BaseModel):
    label: str = Field(default="External deposit", max_length=255)
    expires_at: Optional[datetime] = None
    max_file_size_mb: Optional[int] = Field(default=None, ge=1, le=2048)
    allowed_extensions: Optional[list[str]] = None


class DepositLinkPatchRequest(BaseModel):
    label: Optional[str] = Field(default=None, max_length=255)
    expires_at: Optional[datetime] = None
    max_file_size_mb: Optional[int] = Field(default=None, ge=1, le=2048)
    allowed_extensions: Optional[list[str]] = None


class DepositPromoteRequest(BaseModel):
    collection_slug: str = Field(default="andritz-secure-deposit", max_length=120)


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
    return {"links": [serialize_link(link) for link in links]}


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
