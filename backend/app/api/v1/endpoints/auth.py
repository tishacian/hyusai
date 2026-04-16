"""Auth and workspace management endpoints — backend proxy to Keycloak"""
import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session as DBSession

from app.core.auth import (
    _get_token_url,
    _get_admin_url,
    _get_logout_url,
    decode_token,
    get_current_user,
    _extract_roles,
)
from app.core.config import settings
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str
    remember_me: bool = False


class TokenResponse(BaseModel):
    token: str
    refresh_token: Optional[str] = None
    expires_in: int
    token_type: str = "Bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class SignupRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None


class PasswordResetRequest(BaseModel):
    email: EmailStr


class UserProfile(BaseModel):
    id: str
    username: str
    email: Optional[str]
    role: str
    is_active: bool
    workspaces: list[dict] = []


class WorkspaceCreate(BaseModel):
    name: str
    slug: Optional[str] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    settings: Optional[dict] = None


class MemberInvite(BaseModel):
    email: EmailStr
    role: str = "member"


class MemberUpdate(BaseModel):
    role: str


# ---------------------------------------------------------------------------
# Auth endpoints (proxy to Keycloak)
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DBSession = Depends(get_db)):
    """Proxy login to Keycloak direct access grant."""
    data = {
        "grant_type": "password",
        "client_id": settings.keycloak_client_id,
        "username": body.email,
        "password": body.password,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(_get_token_url(), data=data, timeout=15)

    if resp.status_code != 200:
        detail = "Invalid credentials"
        try:
            err = resp.json()
            detail = err.get("error_description", detail)
        except Exception:
            pass
        raise HTTPException(status_code=401, detail=detail)

    tokens = resp.json()

    payload = decode_token(tokens["access_token"])
    keycloak_sub = payload.get("sub")
    user = db.query(User).filter(User.keycloak_sub == keycloak_sub).first()
    if not user:
        user = User(
            id=str(uuid4()),
            keycloak_sub=keycloak_sub,
            username=payload.get("preferred_username", keycloak_sub),
            email=payload.get("email"),
            role="admin" if "organization_admin" in _extract_roles(payload) else "user",
            is_active=True,
        )
        db.add(user)
    user.last_login = datetime.utcnow()
    db.commit()

    return TokenResponse(
        token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token") if body.remember_me else None,
        expires_in=tokens.get("expires_in", 7200),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest):
    """Refresh access token via Keycloak."""
    data = {
        "grant_type": "refresh_token",
        "client_id": settings.keycloak_client_id,
        "refresh_token": body.refresh_token,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(_get_token_url(), data=data, timeout=15)

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Refresh failed")

    tokens = resp.json()
    return TokenResponse(
        token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        expires_in=tokens.get("expires_in", 7200),
    )


@router.post("/logout")
async def logout(body: Optional[RefreshRequest] = None):
    """Invalidate refresh token in Keycloak."""
    if body and body.refresh_token:
        data = {
            "client_id": settings.keycloak_client_id,
            "refresh_token": body.refresh_token,
        }
        async with httpx.AsyncClient() as client:
            await client.post(_get_logout_url(), data=data, timeout=10)
    return {"status": "ok"}


@router.post("/validate")
async def validate_token(user: User = Depends(get_current_user)):
    """Validate JWT and return user info."""
    return {"valid": True, "user_id": user.id, "email": user.email, "role": user.role}


@router.post("/signup")
async def signup(body: SignupRequest, db: DBSession = Depends(get_db)):
    """Create user in Keycloak via admin API, then in local DB."""
    admin_token = await _get_admin_token()
    if not admin_token:
        raise HTTPException(status_code=503, detail="Cannot reach Keycloak admin API")

    kc_user = {
        "username": body.email,
        "email": body.email,
        "firstName": body.first_name,
        "lastName": body.last_name,
        "enabled": True,
        "emailVerified": False,
        "credentials": [{"type": "password", "value": body.password, "temporary": False}],
        "attributes": {},
    }
    if body.phone:
        kc_user["attributes"]["phone_number"] = [body.phone]
    if body.company:
        kc_user["attributes"]["company"] = [body.company]
    if body.job_title:
        kc_user["attributes"]["job_title"] = [body.job_title]

    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{_get_admin_url()}/users", json=kc_user, headers=headers, timeout=15)

    if resp.status_code == 409:
        raise HTTPException(status_code=409, detail="User already exists")
    if resp.status_code not in (201, 204):
        logger.error("Keycloak signup failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=500, detail="Failed to create user in Keycloak")

    location = resp.headers.get("Location", "")
    keycloak_sub = location.rsplit("/", 1)[-1] if location else None

    user = User(
        id=str(uuid4()),
        keycloak_sub=keycloak_sub,
        username=body.email,
        email=body.email,
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()

    return {"status": "ok", "message": "User created. Check email for confirmation."}


@router.post("/password-reset")
async def password_reset(body: PasswordResetRequest):
    """Trigger password reset email via Keycloak admin API."""
    admin_token = await _get_admin_token()
    if not admin_token:
        raise HTTPException(status_code=503, detail="Cannot reach Keycloak admin API")

    headers = {"Authorization": f"Bearer {admin_token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_get_admin_url()}/users",
            params={"email": body.email, "exact": "true"},
            headers=headers,
            timeout=10,
        )
        users = resp.json() if resp.status_code == 200 else []

    if users:
        kc_user_id = users[0]["id"]
        async with httpx.AsyncClient() as client:
            await client.put(
                f"{_get_admin_url()}/users/{kc_user_id}/execute-actions-email",
                json=["UPDATE_PASSWORD"],
                headers={**headers, "Content-Type": "application/json"},
                timeout=10,
            )

    return {"status": "ok", "message": "If the email exists, a reset link has been sent."}


@router.get("/me", response_model=UserProfile)
async def get_me(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    """Get current user profile with workspaces."""
    memberships = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).all()
    workspaces = []
    for m in memberships:
        ws = db.query(Workspace).filter(Workspace.id == m.workspace_id).first()
        if ws and ws.is_active:
            workspaces.append({"id": ws.id, "name": ws.name, "slug": ws.slug, "role": m.role})

    return UserProfile(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        workspaces=workspaces,
    )


# ---------------------------------------------------------------------------
# Workspace endpoints
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:100]


@router.post("/workspaces", status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    slug = body.slug or _slugify(body.name)
    existing = db.query(Workspace).filter(Workspace.slug == slug).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Workspace slug '{slug}' already exists")

    workspace = Workspace(id=str(uuid4()), name=body.name, slug=slug)
    db.add(workspace)

    membership = WorkspaceMember(user_id=user.id, workspace_id=workspace.id, role="owner")
    db.add(membership)

    db.commit()
    db.refresh(workspace)
    return {"id": workspace.id, "name": workspace.name, "slug": workspace.slug}


@router.get("/workspaces")
async def list_workspaces(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    memberships = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).all()
    result = []
    for m in memberships:
        ws = db.query(Workspace).filter(Workspace.id == m.workspace_id, Workspace.is_active == True).first()
        if ws:
            result.append({"id": ws.id, "name": ws.name, "slug": ws.slug, "role": m.role})
    return result


@router.patch("/workspaces/{slug}")
async def update_workspace(
    slug: str,
    body: WorkspaceUpdate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace = db.query(Workspace).filter(Workspace.slug == slug).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    membership = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == workspace.id,
        WorkspaceMember.role.in_(["owner", "admin"]),
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Admin access required")

    if body.name is not None:
        workspace.name = body.name
    if body.settings is not None:
        workspace.settings = body.settings

    db.commit()
    return {"id": workspace.id, "name": workspace.name, "slug": workspace.slug}


@router.post("/workspaces/{slug}/members")
async def invite_member(
    slug: str,
    body: MemberInvite,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace = db.query(Workspace).filter(Workspace.slug == slug).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    admin_check = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == workspace.id,
        WorkspaceMember.role.in_(["owner", "admin"]),
    ).first()
    if not admin_check:
        raise HTTPException(status_code=403, detail="Admin access required")

    target_user = db.query(User).filter(User.email == body.email).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found. They must sign up first.")

    existing = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == target_user.id,
        WorkspaceMember.workspace_id == workspace.id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")

    membership = WorkspaceMember(user_id=target_user.id, workspace_id=workspace.id, role=body.role)
    db.add(membership)
    db.commit()
    return {"status": "ok", "user_id": target_user.id, "role": body.role}


@router.patch("/workspaces/{slug}/members/{user_id}")
async def update_member_role(
    slug: str,
    user_id: str,
    body: MemberUpdate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace = db.query(Workspace).filter(Workspace.slug == slug).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    admin_check = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == workspace.id,
        WorkspaceMember.role.in_(["owner", "admin"]),
    ).first()
    if not admin_check:
        raise HTTPException(status_code=403, detail="Admin access required")

    membership = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.workspace_id == workspace.id,
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")

    membership.role = body.role
    db.commit()
    return {"status": "ok"}


@router.delete("/workspaces/{slug}/members/{user_id}")
async def remove_member(
    slug: str,
    user_id: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace = db.query(Workspace).filter(Workspace.slug == slug).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    admin_check = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == workspace.id,
        WorkspaceMember.role.in_(["owner", "admin"]),
    ).first()
    if not admin_check:
        raise HTTPException(status_code=403, detail="Admin access required")

    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself")

    membership = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.workspace_id == workspace.id,
    ).first()
    if not membership:
        raise HTTPException(status_code=404, detail="Member not found")

    db.delete(membership)
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Internal helper: get admin service account token
# ---------------------------------------------------------------------------


async def _get_admin_token() -> Optional[str]:
    """Get a Keycloak admin token using the resource server client credentials."""
    if not settings.keycloak_client_secret:
        data = {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": "admin",
        }
        url = f"{settings.keycloak_url}/realms/master/protocol/openid-connect/token"
    else:
        data = {
            "grant_type": "client_credentials",
            "client_id": settings.keycloak_resource_server_id,
            "client_secret": settings.keycloak_client_secret,
        }
        url = _get_token_url()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=data, timeout=10)
        if resp.status_code == 200:
            return resp.json()["access_token"]
    except Exception as e:
        logger.error("Failed to get admin token: %s", e)
    return None
