"""Auth and workspace management endpoints — backend proxy to Keycloak"""
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session as DBSession

from app.core.auth import (
    _get_token_url,
    _get_admin_url,
    _get_logout_url,
    _kc_base_internal,
    decode_token,
    get_current_user,
    _extract_roles,
)
from app.core.iam.roles import (
    WORKSPACE_ADMIN,
    WORKSPACE_CONTRIBUTOR,
    WORKSPACE_OWNER,
    legacy_role_for_template,
    normalize_role_template,
)
from app.core.config import settings
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.mfa import MfaChallenge
from app.services.email import send_email, render_mfa_email

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


class MfaChallengeResponse(BaseModel):
    mfa_required: bool = True
    mfa_token: str
    email_hint: str
    ttl_seconds: int


class VerifyMfaRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=4, max_length=10)
    remember_me: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class ProfileUpdateRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class MfaToggleRequest(BaseModel):
    enabled: bool


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
    mfa_enabled: bool = False
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    job_title: Optional[str] = None
    workspaces: list[dict] = []


class WorkspaceCreate(BaseModel):
    name: str
    slug: Optional[str] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    settings: Optional[dict] = None
    mode: Optional[str] = None


class WorkspaceModeUpdate(BaseModel):
    mode: str  # builder | operator | executive | demo


class MemberInvite(BaseModel):
    email: EmailStr
    role: str = "member"
    role_template: Optional[str] = None
    custom_labels: list[str] = []


class MemberUpdate(BaseModel):
    role: str
    role_template: Optional[str] = None
    custom_labels: Optional[list[str]] = None


class TransferOwnershipRequest(BaseModel):
    new_owner_user_id: str


class WorkspaceDeleteRequest(BaseModel):
    confirm_name: str  # user must type the workspace name


class WorkspaceDetail(BaseModel):
    id: str
    name: str
    slug: str
    role: str  # role of the current user
    role_template: Optional[str] = None
    is_active: bool
    member_count: int
    created_at: datetime
    deleted_at: Optional[datetime] = None
    settings: dict = {}
    mode: str = "executive"


class MemberDetail(BaseModel):
    user_id: str
    email: Optional[str]
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    role_template: Optional[str] = None
    custom_labels: list[str] = []
    joined_at: datetime
    is_current_user: bool


# ---------------------------------------------------------------------------
# Auth endpoints (proxy to Keycloak)
# ---------------------------------------------------------------------------


def _mask_email(email: Optional[str]) -> str:
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        visible = local[0]
    else:
        visible = local[0] + local[1]
    return f"{visible}{'*' * max(3, len(local) - 2)}@{domain}"


def _smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


async def _issue_tokens(tokens: dict, db: DBSession, remember_me: bool) -> TokenResponse:
    """Provision/refresh local User row from KC token payload and return TokenResponse."""
    payload = decode_token(tokens["access_token"])
    keycloak_sub = payload.get("sub")
    preferred_username = payload.get("preferred_username", keycloak_sub)

    user = db.query(User).filter(User.keycloak_sub == keycloak_sub).first()
    if not user:
        user = db.query(User).filter(User.username == preferred_username).first()
    if not user:
        user = User(
            id=str(uuid4()),
            keycloak_sub=keycloak_sub,
            username=preferred_username,
            email=payload.get("email"),
            role="admin" if "organization_admin" in _extract_roles(payload) else "user",
            is_active=True,
        )
        db.add(user)
    if not user.keycloak_sub:
        user.keycloak_sub = keycloak_sub
    user.last_login = datetime.utcnow()
    db.commit()

    return TokenResponse(
        token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token") if remember_me else None,
        expires_in=tokens.get("expires_in", 7200),
    )


@router.post("/login")
async def login(body: LoginRequest, db: DBSession = Depends(get_db)):
    """Proxy login to Keycloak direct access grant.

    If the user has MFA enabled and SMTP is configured, this returns an MFA
    challenge instead of tokens. The client must call /verify-mfa with the
    emailed code to obtain the actual tokens.
    """
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
    preferred_username = payload.get("preferred_username", keycloak_sub)
    email = payload.get("email")

    user = db.query(User).filter(User.keycloak_sub == keycloak_sub).first()
    if not user:
        user = db.query(User).filter(User.username == preferred_username).first()

    # MFA gate: only if user exists, has MFA enabled, has an email, and SMTP works
    if user and user.mfa_enabled and email and _smtp_configured():
        code = f"{random.randint(0, 999999):06d}"
        challenge = MfaChallenge(
            id=str(uuid4()),
            user_id=user.id,
            code=code,
            expires_at=datetime.utcnow() + timedelta(seconds=settings.mfa_code_ttl_seconds),
            kc_payload=json.dumps(tokens),
        )
        db.add(challenge)
        db.commit()

        full_name = " ".join(filter(None, [payload.get("given_name"), payload.get("family_name")]))
        subject, html, text = render_mfa_email(
            code=code,
            full_name=full_name or None,
            ttl_minutes=settings.mfa_code_ttl_seconds // 60,
        )
        sent = await send_email(email, subject, html, text)
        if not sent:
            db.delete(challenge)
            db.commit()
            logger.error("MFA email failed to send for user %s; falling back to direct login", user.id)
            return await _issue_tokens(tokens, db, body.remember_me)

        return MfaChallengeResponse(
            mfa_token=challenge.id,
            email_hint=_mask_email(email),
            ttl_seconds=settings.mfa_code_ttl_seconds,
        )

    return await _issue_tokens(tokens, db, body.remember_me)


@router.post("/verify-mfa", response_model=TokenResponse)
async def verify_mfa(body: VerifyMfaRequest, db: DBSession = Depends(get_db)):
    """Complete MFA challenge and release stored KC tokens."""
    challenge = db.query(MfaChallenge).filter(MfaChallenge.id == body.mfa_token).first()
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if challenge.used_at is not None:
        raise HTTPException(status_code=410, detail="Challenge already used")

    if challenge.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Challenge expired")

    if (challenge.attempts or 0) >= settings.mfa_max_attempts:
        raise HTTPException(status_code=429, detail="Too many attempts")

    if body.code.strip() != challenge.code:
        challenge.attempts = (challenge.attempts or 0) + 1
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid code")

    try:
        tokens = json.loads(challenge.kc_payload)
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupted challenge payload")

    challenge.used_at = datetime.utcnow()
    db.commit()

    return await _issue_tokens(tokens, db, body.remember_me)


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


def _select_password_reset_user(users: list[dict], email: str) -> Optional[dict]:
    """Pick the safest Keycloak user for a password reset email.

    Keycloak may return disabled historical users when several rows share the
    same email. Reset should target an enabled exact username/email match first
    so old disabled bootstrap accounts cannot steal the action email.
    """
    target = email.strip().lower()

    def is_exact(user: dict) -> bool:
        return (
            str(user.get("username") or "").strip().lower() == target
            or str(user.get("email") or "").strip().lower() == target
        )

    for user in users:
        if user.get("enabled", True) and is_exact(user):
            return user
    for user in users:
        if user.get("enabled", True):
            return user
    for user in users:
        if is_exact(user):
            return user
    return users[0] if users else None


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

    kc_user = _select_password_reset_user(users, body.email)
    if kc_user:
        kc_user_id = kc_user["id"]
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
    """Get current user profile with workspaces and Keycloak attributes."""
    memberships = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).all()
    workspaces = []
    for m in memberships:
        ws = db.query(Workspace).filter(Workspace.id == m.workspace_id).first()
        if ws and ws.is_active:
            workspaces.append({
                "id": ws.id,
                "name": ws.name,
                "slug": ws.slug,
                "role": m.role,
                "mode": getattr(ws, "mode", "executive") or "executive",
            })

    kc_data = await _get_kc_user(user.keycloak_sub) if user.keycloak_sub else {}
    attrs = kc_data.get("attributes") or {}

    def _attr(key: str) -> Optional[str]:
        v = attrs.get(key)
        return v[0] if isinstance(v, list) and v else (v if isinstance(v, str) else None)

    return UserProfile(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        mfa_enabled=user.mfa_enabled,
        first_name=kc_data.get("firstName"),
        last_name=kc_data.get("lastName"),
        phone=_attr("phone_number"),
        company=_attr("company"),
        job_title=_attr("job_title"),
        workspaces=workspaces,
    )


# ---------------------------------------------------------------------------
# Account management endpoints
# ---------------------------------------------------------------------------


@router.patch("/me")
async def update_me(
    body: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
):
    """Update Keycloak user profile (firstName/lastName + custom attributes)."""
    if not user.keycloak_sub:
        raise HTTPException(status_code=400, detail="User has no Keycloak link")

    admin_token = await _get_admin_token()
    if not admin_token:
        raise HTTPException(status_code=503, detail="Cannot reach Keycloak admin API")

    existing = await _get_kc_user(user.keycloak_sub) or {}
    existing_attrs = existing.get("attributes") or {}

    def _set_attr(key: str, value: Optional[str]):
        if value is None:
            return
        existing_attrs[key] = [value] if value else []

    _set_attr("phone_number", body.phone)
    _set_attr("company", body.company)
    _set_attr("job_title", body.job_title)

    update_body = {"attributes": existing_attrs}
    if body.first_name is not None:
        update_body["firstName"] = body.first_name
    if body.last_name is not None:
        update_body["lastName"] = body.last_name

    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{_get_admin_url()}/users/{user.keycloak_sub}",
            json=update_body,
            headers=headers,
            timeout=15,
        )
    if resp.status_code not in (200, 204):
        logger.error("KC profile update failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=500, detail="Failed to update profile")

    return {"status": "ok"}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
):
    """Validate current password against Keycloak, then reset to the new one."""
    if not user.email:
        raise HTTPException(status_code=400, detail="User has no email")

    verify_data = {
        "grant_type": "password",
        "client_id": settings.keycloak_client_id,
        "username": user.email,
        "password": body.current_password,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(_get_token_url(), data=verify_data, timeout=15)
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    admin_token = await _get_admin_token()
    if not admin_token:
        raise HTTPException(status_code=503, detail="Cannot reach Keycloak admin API")

    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    reset_body = {"type": "password", "value": body.new_password, "temporary": False}
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{_get_admin_url()}/users/{user.keycloak_sub}/reset-password",
            json=reset_body,
            headers=headers,
            timeout=15,
        )
    if resp.status_code not in (200, 204):
        logger.error("KC reset-password failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=500, detail="Failed to update password")

    return {"status": "ok"}


@router.post("/logout-all")
async def logout_everywhere(user: User = Depends(get_current_user)):
    """Invalidate all Keycloak sessions for the current user."""
    if not user.keycloak_sub:
        raise HTTPException(status_code=400, detail="User has no Keycloak link")

    admin_token = await _get_admin_token()
    if not admin_token:
        raise HTTPException(status_code=503, detail="Cannot reach Keycloak admin API")

    headers = {"Authorization": f"Bearer {admin_token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_get_admin_url()}/users/{user.keycloak_sub}/logout",
            headers=headers,
            timeout=10,
        )
    if resp.status_code not in (200, 204):
        logger.error("KC logout-all failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=500, detail="Failed to logout all sessions")

    return {"status": "ok"}


@router.get("/sessions")
async def list_sessions(user: User = Depends(get_current_user)):
    """List active Keycloak sessions for the current user."""
    if not user.keycloak_sub:
        return []

    admin_token = await _get_admin_token()
    if not admin_token:
        raise HTTPException(status_code=503, detail="Cannot reach Keycloak admin API")

    headers = {"Authorization": f"Bearer {admin_token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_get_admin_url()}/users/{user.keycloak_sub}/sessions",
            headers=headers,
            timeout=10,
        )
    if resp.status_code != 200:
        return []

    sessions = []
    for s in resp.json():
        sessions.append({
            "id": s.get("id"),
            "ip_address": s.get("ipAddress"),
            "start": s.get("start"),
            "last_access": s.get("lastAccess"),
            "clients": list((s.get("clients") or {}).values()),
        })
    return sessions


@router.delete("/me")
async def delete_me(
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Delete the current user from Keycloak and the local DB."""
    if not user.keycloak_sub:
        raise HTTPException(status_code=400, detail="User has no Keycloak link")

    admin_token = await _get_admin_token()
    if not admin_token:
        raise HTTPException(status_code=503, detail="Cannot reach Keycloak admin API")

    headers = {"Authorization": f"Bearer {admin_token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{_get_admin_url()}/users/{user.keycloak_sub}",
            headers=headers,
            timeout=10,
        )
    if resp.status_code not in (200, 204, 404):
        logger.error("KC user delete failed: %s %s", resp.status_code, resp.text)
        raise HTTPException(status_code=500, detail="Failed to delete account")

    db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).delete()
    db.query(MfaChallenge).filter(MfaChallenge.user_id == user.id).delete()
    db.delete(user)
    db.commit()

    return {"status": "ok"}


@router.post("/mfa/toggle")
async def toggle_mfa(
    body: MfaToggleRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Enable or disable email-based 2FA for the current user."""
    if body.enabled and not _smtp_configured():
        raise HTTPException(status_code=503, detail="SMTP not configured on server")
    if body.enabled and not user.email:
        raise HTTPException(status_code=400, detail="Account has no email, cannot enable MFA")

    user.mfa_enabled = body.enabled
    db.commit()
    return {"status": "ok", "mfa_enabled": user.mfa_enabled}


# ---------------------------------------------------------------------------
# Workspace endpoints
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    import re
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:100]


def _resolve_workspace_and_role(db: DBSession, user: User, slug: str) -> tuple[Workspace, WorkspaceMember]:
    """Fetch a workspace by slug (non-deleted) and ensure the caller is a member.

    Returns (workspace, membership). Raises 404 if workspace missing, 403 if not a member.
    """
    workspace = db.query(Workspace).filter(
        Workspace.slug == slug,
        Workspace.deleted_at.is_(None),
    ).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    membership = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == workspace.id,
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    return workspace, membership


def _require_admin(membership: WorkspaceMember) -> None:
    if normalize_role_template(getattr(membership, "role_template", None), membership.role) not in (
        WORKSPACE_OWNER,
        WORKSPACE_ADMIN,
    ):
        raise HTTPException(status_code=403, detail="Admin access required")


def _require_owner(membership: WorkspaceMember) -> None:
    if normalize_role_template(getattr(membership, "role_template", None), membership.role) != WORKSPACE_OWNER:
        raise HTTPException(status_code=403, detail="Owner access required")


@router.post("/workspaces", status_code=201, response_model=WorkspaceDetail)
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

    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="owner",
        role_template=WORKSPACE_OWNER,
        custom_labels=[],
    )
    db.add(membership)

    db.commit()
    db.refresh(workspace)
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role="owner",
        role_template=WORKSPACE_OWNER,
        is_active=workspace.is_active,
        member_count=1,
        created_at=workspace.created_at,
        settings=workspace.settings or {},
        mode=getattr(workspace, "mode", "executive") or "executive",
    )


@router.get("/workspaces")
async def list_workspaces(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    memberships = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).all()
    result = []
    for m in memberships:
        ws = db.query(Workspace).filter(
            Workspace.id == m.workspace_id,
            Workspace.is_active == True,  # noqa: E712
            Workspace.deleted_at.is_(None),
        ).first()
        if ws:
            member_count = db.query(WorkspaceMember).filter(
                WorkspaceMember.workspace_id == ws.id
            ).count()
            result.append({
                "id": ws.id,
                "name": ws.name,
                "slug": ws.slug,
                "role": m.role,
                "role_template": normalize_role_template(getattr(m, "role_template", None), m.role),
                "member_count": member_count,
                "created_at": ws.created_at.isoformat() if ws.created_at else None,
                "settings": ws.settings or {},
                "mode": getattr(ws, "mode", "executive") or "executive",
            })
    return result


@router.get("/workspaces/{slug}", response_model=WorkspaceDetail)
async def get_workspace(
    slug: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    member_count = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace.id
    ).count()
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=membership.role,
        role_template=normalize_role_template(getattr(membership, "role_template", None), membership.role),
        is_active=workspace.is_active,
        member_count=member_count,
        created_at=workspace.created_at,
        deleted_at=workspace.deleted_at,
        settings=workspace.settings or {},
        mode=getattr(workspace, "mode", "executive") or "executive",
    )


@router.patch("/workspaces/{slug}", response_model=WorkspaceDetail)
async def update_workspace(
    slug: str,
    body: WorkspaceUpdate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)

    if body.name is not None:
        workspace.name = body.name
    if body.settings is not None:
        workspace.settings = body.settings
    if body.mode is not None:
        if body.mode not in ("builder", "operator", "executive", "demo"):
            raise HTTPException(status_code=422, detail="Invalid workspace mode")
        workspace.mode = body.mode

    db.commit()
    db.refresh(workspace)
    member_count = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace.id
    ).count()
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=membership.role,
        role_template=normalize_role_template(getattr(membership, "role_template", None), membership.role),
        is_active=workspace.is_active,
        member_count=member_count,
        created_at=workspace.created_at,
        settings=workspace.settings or {},
        mode=getattr(workspace, "mode", "executive") or "executive",
    )


@router.patch("/workspaces/{slug}/mode", response_model=WorkspaceDetail)
async def update_workspace_mode(
    slug: str,
    body: WorkspaceModeUpdate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Canonical endpoint to toggle workspace persona surface.

    - `builder`   → System Builder focused, hides Hypervisor/ROI.
    - `operator`  → Runs + steering focused, Hypervisor visible but reduced.
    - `executive` → Full portfolio view (default).
    - `demo`      → Operator-safe surface, hides provider/model implementation details.
    The underlying data never changes; only the shell surface adapts.
    """
    if body.mode not in ("builder", "operator", "executive", "demo"):
        raise HTTPException(status_code=422, detail="Invalid workspace mode")
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)
    workspace.mode = body.mode
    db.commit()
    db.refresh(workspace)
    member_count = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace.id
    ).count()
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=membership.role,
        role_template=normalize_role_template(getattr(membership, "role_template", None), membership.role),
        is_active=workspace.is_active,
        member_count=member_count,
        created_at=workspace.created_at,
        settings=workspace.settings or {},
        mode=workspace.mode or "executive",
    )


@router.delete("/workspaces/{slug}")
async def delete_workspace(
    slug: str,
    body: WorkspaceDeleteRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Soft-delete a workspace. Only the owner can delete it.

    The workspace name must match the provided confirm_name. The workspace is
    marked deleted_at=now; data is preserved for 30 days and then hard-purged
    by a scheduled task. Use /restore to undo within the grace period.
    """
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_owner(membership)

    if body.confirm_name != workspace.name:
        raise HTTPException(
            status_code=400,
            detail="Workspace name does not match. Delete cancelled.",
        )

    workspace.is_active = False
    workspace.deleted_at = datetime.utcnow()
    db.commit()

    return {
        "status": "ok",
        "message": f"Workspace '{workspace.name}' archived. It will be permanently deleted in 30 days.",
        "deleted_at": workspace.deleted_at.isoformat(),
    }


@router.post("/workspaces/{slug}/restore")
async def restore_workspace(
    slug: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Restore a soft-deleted workspace (within the 30-day grace period)."""
    workspace = db.query(Workspace).filter(Workspace.slug == slug).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    membership = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == workspace.id,
    ).first()
    if not membership or normalize_role_template(getattr(membership, "role_template", None), membership.role) != WORKSPACE_OWNER:
        raise HTTPException(status_code=403, detail="Only the owner can restore")

    if workspace.deleted_at is None:
        return {"status": "ok", "message": "Workspace is already active"}

    workspace.is_active = True
    workspace.deleted_at = None
    db.commit()
    return {"status": "ok", "message": "Workspace restored"}


@router.post("/workspaces/{slug}/transfer-ownership")
async def transfer_ownership(
    slug: str,
    body: TransferOwnershipRequest,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Transfer workspace ownership to another existing member."""
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_owner(membership)

    if body.new_owner_user_id == user.id:
        raise HTTPException(status_code=400, detail="You are already the owner")

    new_owner_membership = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == body.new_owner_user_id,
        WorkspaceMember.workspace_id == workspace.id,
    ).first()
    if not new_owner_membership:
        raise HTTPException(status_code=404, detail="Target user is not a member of this workspace")

    new_owner_membership.role = "owner"
    new_owner_membership.role_template = WORKSPACE_OWNER
    membership.role = "admin"
    membership.role_template = WORKSPACE_ADMIN
    db.commit()
    return {"status": "ok", "message": "Ownership transferred"}


@router.post("/workspaces/{slug}/leave")
async def leave_workspace(
    slug: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Leave a workspace. Owners must transfer ownership first."""
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    if normalize_role_template(getattr(membership, "role_template", None), membership.role) == WORKSPACE_OWNER:
        raise HTTPException(
            status_code=400,
            detail="Owner cannot leave. Transfer ownership first, or delete the workspace.",
        )

    db.delete(membership)
    db.commit()
    return {"status": "ok"}


@router.get("/workspaces/{slug}/members", response_model=list[MemberDetail])
async def list_members(
    slug: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List all members of a workspace (members can see this list)."""
    workspace, _ = _resolve_workspace_and_role(db, user, slug)

    members = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace.id
    ).order_by(WorkspaceMember.joined_at.asc()).all()

    result: list[MemberDetail] = []
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        if not u:
            continue
        kc_data = await _get_kc_user(u.keycloak_sub) if u.keycloak_sub else {}
        result.append(MemberDetail(
            user_id=u.id,
            email=u.email,
            username=u.username,
            first_name=kc_data.get("firstName"),
            last_name=kc_data.get("lastName"),
            role=m.role,
            role_template=normalize_role_template(getattr(m, "role_template", None), m.role),
            custom_labels=m.custom_labels or [],
            joined_at=m.joined_at,
            is_current_user=(u.id == user.id),
        ))
    return result


async def _find_or_create_kc_user(
    email: str, admin_token: str
) -> tuple[str, bool]:
    """Look up a Keycloak user by email, provisioning one with the
    ``UPDATE_PASSWORD`` + ``VERIFY_EMAIL`` required actions when missing.

    Returns ``(keycloak_sub, was_created)``. Raises ``HTTPException`` on
    hard failures (bad admin token, 5xx from Keycloak).
    """
    headers = {"Authorization": f"Bearer {admin_token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_get_admin_url()}/users",
            params={"email": email, "exact": "true"},
            headers=headers,
            timeout=10,
        )
    if resp.status_code == 200:
        existing = resp.json() or []
        if existing:
            return existing[0]["id"], False

    kc_user = {
        "username": email,
        "email": email,
        "enabled": True,
        "emailVerified": False,
        "requiredActions": ["UPDATE_PASSWORD", "VERIFY_EMAIL"],
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_get_admin_url()}/users",
            json=kc_user,
            headers={**headers, "Content-Type": "application/json"},
            timeout=15,
        )
    if resp.status_code not in (201, 204):
        logger.error(
            "Keycloak invite provisioning failed: %s %s",
            resp.status_code,
            resp.text,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to provision the invitee in Keycloak",
        )
    location = resp.headers.get("Location", "")
    kc_sub = location.rsplit("/", 1)[-1] if location else ""
    if not kc_sub:
        raise HTTPException(
            status_code=502,
            detail="Keycloak did not return the newly created user id",
        )
    return kc_sub, True


async def _send_invitation_email(kc_sub: str, admin_token: str) -> None:
    """Trigger the ``UPDATE_PASSWORD``/``VERIFY_EMAIL`` action email.

    Fails silent (logged warning) because the membership has already been
    created at this point — the operator can re-trigger via the password
    reset endpoint if SMTP is unavailable.
    """
    headers = {
        "Authorization": f"Bearer {admin_token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{_get_admin_url()}/users/{kc_sub}/execute-actions-email",
                json=["UPDATE_PASSWORD", "VERIFY_EMAIL"],
                headers=headers,
                timeout=10,
            )
        if resp.status_code not in (200, 204):
            logger.warning(
                "Keycloak invitation email not sent (status=%s, body=%s)",
                resp.status_code,
                resp.text,
            )
    except Exception:
        logger.warning("Keycloak invitation email delivery failed", exc_info=True)


@router.post("/workspaces/{slug}/members")
async def invite_member(
    slug: str,
    body: MemberInvite,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Invite a teammate into the workspace.

    Resolution order:
      1. Local ``User`` row exists → just add the membership.
      2. Keycloak user exists (by email) but no local row → stub a local
         ``User`` linked to that ``keycloak_sub`` + add the membership.
      3. Neither → provision a fresh Keycloak user with
         ``UPDATE_PASSWORD`` + ``VERIFY_EMAIL`` required actions, trigger
         the onboarding email, then create the local stub + membership.

    The caller must be ``owner`` or ``admin`` of the workspace.
    """
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)

    if body.role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'member'")
    role_template = normalize_role_template(body.role_template, body.role)
    if role_template == WORKSPACE_OWNER:
        raise HTTPException(status_code=400, detail="Use transfer ownership to assign owner")

    email = body.email.lower()
    target_user = db.query(User).filter(User.email == email).first()
    created_in_kc = False

    if not target_user:
        admin_token = await _get_admin_token()
        if not admin_token:
            raise HTTPException(
                status_code=503,
                detail="Cannot reach Keycloak admin API to provision the invitee",
            )
        kc_sub, created_in_kc = await _find_or_create_kc_user(email, admin_token)
        if created_in_kc:
            await _send_invitation_email(kc_sub, admin_token)

        target_user = db.query(User).filter(User.keycloak_sub == kc_sub).first()
        if not target_user:
            target_user = User(
                id=str(uuid4()),
                keycloak_sub=kc_sub,
                username=email,
                email=email,
                role="user",
                is_active=True,
            )
            db.add(target_user)
            db.flush()

    existing = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == target_user.id,
        WorkspaceMember.workspace_id == workspace.id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="User is already a member")

    new_member = WorkspaceMember(
        user_id=target_user.id,
        workspace_id=workspace.id,
        role=legacy_role_for_template(role_template),
        role_template=role_template,
        custom_labels=body.custom_labels or [],
    )
    db.add(new_member)
    db.commit()
    logger.info(
        "Invited teammate to workspace",
        workspace_id=workspace.id,
        target_user=target_user.id,
        role=body.role,
        provisioned_in_keycloak=created_in_kc,
    )
    return {
        "status": "ok",
        "user_id": target_user.id,
        "role": legacy_role_for_template(role_template),
        "role_template": role_template,
        "invitation_email_sent": created_in_kc,
    }


@router.patch("/workspaces/{slug}/members/{user_id}")
async def update_member_role(
    slug: str,
    user_id: str,
    body: MemberUpdate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)

    target = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.workspace_id == workspace.id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == "owner":
        raise HTTPException(
            status_code=400,
            detail="Cannot change the owner's role. Transfer ownership first.",
        )
    if body.role == "owner":
        raise HTTPException(
            status_code=400,
            detail="Use the transfer-ownership endpoint to promote someone to owner.",
        )
    if body.role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'member'")

    role_template = normalize_role_template(body.role_template, body.role)
    if role_template == WORKSPACE_OWNER:
        raise HTTPException(status_code=400, detail="Use transfer ownership to assign owner")
    target.role_template = role_template
    target.role = legacy_role_for_template(role_template)
    if body.custom_labels is not None:
        target.custom_labels = body.custom_labels
    db.commit()
    return {"status": "ok"}


@router.delete("/workspaces/{slug}/members/{user_id}")
async def remove_member(
    slug: str,
    user_id: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)

    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself. Use /leave instead.")

    target = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user_id,
        WorkspaceMember.workspace_id == workspace.id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == "owner":
        raise HTTPException(status_code=400, detail="Cannot remove the owner. Transfer ownership first.")

    db.delete(target)
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Internal helper: get admin service account token
# ---------------------------------------------------------------------------


async def _get_kc_user(kc_sub: Optional[str]) -> dict:
    """Fetch the Keycloak user representation (for profile attributes)."""
    if not kc_sub:
        return {}
    admin_token = await _get_admin_token()
    if not admin_token:
        return {}
    headers = {"Authorization": f"Bearer {admin_token}"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{_get_admin_url()}/users/{kc_sub}",
                headers=headers,
                timeout=10,
            )
        if resp.status_code == 200:
            return resp.json() or {}
    except Exception:
        logger.exception("Failed to fetch KC user %s", kc_sub)
    return {}


async def _get_admin_token() -> Optional[str]:
    """Get a Keycloak admin token using the resource server client credentials.

    The legacy fallback to ``admin/admin`` via admin-cli has been
    removed: in prod we rotate the master-realm admin away from the
    default, so silently falling back would either fail in a
    hard-to-diagnose way or, worse, keep working against an
    un-rotated cluster and hide a misconfiguration. If the
    resource-server client secret is missing, this function now
    returns ``None`` and logs a clear error — callers already handle
    that as a 503.
    """
    if not settings.keycloak_client_secret:
        logger.error(
            "Keycloak client_secret not configured — admin API calls "
            "(signup, password reset, user management) are disabled. "
            "Set KEYCLOAK_CLIENT_SECRET in backend/.env."
        )
        return None

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
        logger.error(
            "Admin token request returned %s: %s",
            resp.status_code,
            resp.text[:200],
        )
    except Exception as e:
        logger.error("Failed to get admin token: %s", e)
    return None
