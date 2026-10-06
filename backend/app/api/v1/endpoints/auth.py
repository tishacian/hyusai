"""Auth and workspace management endpoints — backend proxy to Keycloak"""

import json
import logging
import random
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import not_, or_
from sqlalchemy.orm import Session as DBSession

from app.core.auth import (
    _extract_roles,
    _get_admin_url,
    _get_logout_url,
    _get_token_url,
    decode_token,
    get_current_user,
)
from app.core.config import settings
from app.core.iam.roles import (
    CANONICAL_WORKSPACE_ROLES,
    WORKSPACE_ADMIN,
    WORKSPACE_OWNER,
    legacy_role_for_template,
    normalize_role_template,
)
from app.db.base import get_db
from app.models.mfa import MfaChallenge
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.adoption import ExperienceProgressUpdate
from app.schemas.brand_appearance import PlatformBrand
from app.schemas.canonical import WorkspaceFamily, WorkspaceMode
from app.services.actions.contracts import normalize_workspace_action_pack_settings
from app.services.connectors.generic import SETTINGS_KEY as GENERIC_CONNECTORS_KEY
from app.services.email import render_mfa_email, send_email
from app.services.iam.app_entitlements import (
    APP_ENTITLEMENTS_FEATURE,
    WorkspaceEntitlementMutationConflictError,
    app_entitlements_enabled,
    list_member_app_entitlements,
    lock_workspace_for_app_entitlement_mutation,
    normalize_app_entitlements,
    replace_member_app_entitlements,
)
from app.services.projection_gate import (
    FEATURE_BY_PROJECTION,
    WORKSPACE_GATE_KEY,
    authoritative_projection_enabled,
)
from app.services.value_loop_gate import FEATURE_KEY as VALUE_LOOP_FEATURE_KEY
from app.services.workspace_app_runtime import (
    WORKSPACE_APP_CANARY_MARKER,
    WORKSPACE_APP_PLATFORM_FEATURE,
    WORKSPACE_APP_ROLLOUT_STATE_KEY,
    safe_workspace_app_runtime_payload,
)
from app.services.workspace_secrets import (
    public_workspace_settings,
    secret_paths,
    with_stored_secrets,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/workspaces/{slug}/me/experience")
async def get_member_experience(
    slug: str, user: User = Depends(get_current_user), db: DBSession = Depends(get_db),
):
    from app.schemas.adoption import ExperienceProgress, with_first_seen
    workspace, member = _resolve_workspace_and_role(db, user, slug)
    progress = ExperienceProgress.model_validate(member.experience_progress or {})
    if progress.first_seen_at is None:
        # First read by this member in this workspace: record it once, under
        # the row lock, so a concurrent first read cannot move it. It starts
        # at the membership's join date when there is one.
        member = db.query(WorkspaceMember).filter(WorkspaceMember.id == member.id).populate_existing().with_for_update().one()
        progress, created = with_first_seen(member.experience_progress or {}, joined_at=member.joined_at)
        if created:
            member.experience_progress = progress.model_dump(mode="json")
        db.commit()
    return _experience_payload(db, workspace, member, progress)


def _experience_payload(db: DBSession, workspace: Workspace, member: WorkspaceMember, progress) -> dict:
    """The member's progress for the journey this workspace offers, and whether it can run.

    Showcase keeps the NorthForge example (available once its corpus is
    indexed); every other workspace walks its own collections, available only
    when the member can read or fill one of them. Never a Showcase redirect.
    """
    from app.models.knowledge_collection import KnowledgeCollection
    from app.schemas.adoption import SHOWCASE_WORKSPACE_SLUG, for_journey, journey_for_workspace
    journey = journey_for_workspace(workspace.slug)
    progress = for_journey(progress.model_dump(mode="json"), journey)
    example_row = (
        db.query(KnowledgeCollection).filter_by(
            workspace_id=workspace.id,
            slug="agentium-showcase-notices",
            status="ready",
        ).filter(KnowledgeCollection.document_count > 0, KnowledgeCollection.chunk_count > 0).first()
        if workspace.slug == SHOWCASE_WORKSPACE_SLUG
        else None
    )
    from app.services.collection_access import can_read_collection
    example_available = example_row is not None and can_read_collection(member, example_row)
    payload = {**progress.model_dump(mode="json"), "example_available": example_available}
    if journey == "northforge_sources":
        return {**payload, "available": example_available}
    from app.services.adoption_sources import member_sources
    return {**payload, **member_sources(db, workspace=workspace, member=member, chosen_collection_id=progress.collection_id)}


# Server-side evidence that a member decided on an answer: the chat feedback
# (saved through ``/audit`` before the client records the step) and the chat
# correction (written by ``/knowledge-capture/chat-correction``).
_CLIENT_DECISION_EVENTS = ("chat_feedback", "kc.chat_correction.created")


def _client_journey_started_at(db: DBSession, *, workspace: Workspace, user: User, progress) -> Optional[datetime]:
    """When the member started ``client_sources``: their first recorded step,
    else their first sighting in the workspace (naive UTC, like audit rows)."""
    from app.models.audit import AuditLog

    rows = (
        db.query(AuditLog.timestamp, AuditLog.details)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == "adoption.progress",
            AuditLog.actor == user.id,
        )
        .order_by(AuditLog.timestamp.asc())
        .limit(200)
        .all()
    )
    for row in rows:
        if isinstance(row.details, dict) and row.details.get("journey") == "client_sources":
            return row.timestamp
    first_seen = getattr(progress, "first_seen_at", None)
    if first_seen is None:
        return None
    if first_seen.tzinfo is not None:
        first_seen = first_seen.astimezone(timezone.utc).replace(tzinfo=None)
    return first_seen


def _client_decision_recorded(db: DBSession, *, workspace: Workspace, user: User, progress) -> bool:
    """Step 4 proof: a decision by this member, in this workspace, since the
    journey started — a chat feedback or correction, or a Work gate/HITL
    decision they confirmed."""
    from app.models.audit import AuditLog
    from app.models.decision import Decision

    started = _client_journey_started_at(db, workspace=workspace, user=user, progress=progress)
    actors = sorted({value for value in (user.email, user.username, user.id) if value})
    events = db.query(AuditLog.id).filter(
        AuditLog.workspace_id == workspace.id,
        AuditLog.event_type.in_(_CLIENT_DECISION_EVENTS),
        AuditLog.actor.in_(actors),
    )
    if started is not None:
        events = events.filter(AuditLog.timestamp >= started)
    if events.first() is not None:
        return True
    decisions = db.query(Decision.id).filter(
        Decision.workspace_id == workspace.id,
        Decision.human_confirmed_by == user.id,
        Decision.human_confirmed_at.isnot(None),
    )
    if started is not None:
        decisions = decisions.filter(Decision.human_confirmed_at >= started)
    return decisions.first() is not None


@router.patch("/workspaces/{slug}/me/experience")
async def update_member_experience(
    slug: str, body: "ExperienceProgressUpdate",
    user: User = Depends(get_current_user), db: DBSession = Depends(get_db),
):
    from app.schemas.adoption import update_progress
    from app.services.audit_logger import emit_audit_event
    workspace, member = _resolve_workspace_and_role(db, user, slug)
    member = db.query(WorkspaceMember).filter(WorkspaceMember.id == member.id).populate_existing().with_for_update().one()
    if body.session_id:
        from app.models.user import Session as ChatSession
        if not db.query(ChatSession).filter_by(id=body.session_id, workspace_id=workspace.id, user_id=user.id, status="active").first():
            raise HTTPException(404, "Conversation unavailable")
    if body.run_id:
        from app.models.run import Run
        from app.services.run_access import run_is_visible
        run = db.query(Run).filter_by(id=body.run_id, workspace_id=workspace.id, initiated_by_user_id=user.id).first()
        if run is None or not run_is_visible(db, run=run, user=user, workspace=workspace):
            raise HTTPException(404, "Run unavailable")
    if body.collection_id:
        from app.services.adoption_sources import usable_collection
        if usable_collection(db, workspace=workspace, member=member, collection_id=body.collection_id) is None:
            raise HTTPException(404, "Source unavailable")
    from app.schemas.adoption import for_journey, journey_for_workspace
    journey = journey_for_workspace(workspace.slug)
    if journey == "client_sources" and body.completed_step == "decision":
        current = for_journey(member.experience_progress or {}, journey)
        if "decision" not in current.completed_steps and not _client_decision_recorded(
            db, workspace=workspace, user=user, progress=current
        ):
            raise HTTPException(
                409,
                {
                    "code": "ADOPTION_DECISION_NOT_RECORDED",
                    "message": "No decision by this member since the journey started: "
                    "rate or correct an answer, or decide on agent work, first.",
                },
            )
    try:
        progress = update_progress(member.experience_progress or {}, body, journey)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # JSON mode: ``first_seen_at`` is a datetime and the column is plain JSON.
    member.experience_progress = progress.model_dump(mode="json")
    emit_audit_event(
        event_type="adoption.progress", workspace_id=workspace.id, actor=user.id,
        details={"journey": progress.journey, **body.model_dump(exclude_none=True)}, db=db,
    )
    db.commit()
    return progress.model_dump(mode="json")


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
    platform_brand: PlatformBrand | None = None
    expected_platform_brand: dict | None = None
    name: Optional[str] = None
    settings: Optional[dict] = None
    mode: Optional[WorkspaceMode] = None

    @field_validator("settings")
    @classmethod
    def _validate_settings_contract(cls, value: Optional[dict]) -> Optional[dict]:
        if value is not None:
            normalized = dict(value)
            brand = normalized.get("platform_brand")
            if isinstance(brand, dict) and "appearance" in brand:
                normalized["platform_brand"] = PlatformBrand.model_validate(brand).model_dump(exclude_none=True)
            if "family" in normalized:
                raw_family = normalized["family"]
                if not isinstance(raw_family, str):
                    raise ValueError("settings.family must be a canonical workspace family")
                try:
                    normalized["family"] = WorkspaceFamily(raw_family.strip().lower()).value
                except ValueError as exc:
                    raise ValueError(
                        f"Unknown workspace family: {raw_family.strip() or '<empty>'}"
                    ) from exc
            return normalize_workspace_action_pack_settings(normalized)
        return None


class WorkspaceModeUpdate(BaseModel):
    mode: WorkspaceMode


class MemberInvite(BaseModel):
    email: EmailStr
    role: Optional[str] = None
    role_template: Optional[str] = None
    custom_labels: list[str] = []
    app_entitlements: Optional[list[str]] = None


class MemberUpdate(BaseModel):
    role: Optional[str] = None
    role_template: Optional[str] = None
    custom_labels: Optional[list[str]] = None
    app_entitlements: Optional[list[str]] = None


def _resolve_member_role_template(
    *,
    role: Optional[str],
    role_template: Optional[str],
) -> str:
    """Accept ``role_template`` alone, or legacy ``admin``/``member`` role."""
    if role_template is not None:
        cleaned = role_template.strip()
        if cleaned not in CANONICAL_WORKSPACE_ROLES:
            raise HTTPException(status_code=400, detail="Unknown role_template")
        template = cleaned
    elif role in ("admin", "member"):
        template = normalize_role_template(None, role)
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide role_template or role ('admin'|'member')",
        )
    if template == WORKSPACE_OWNER:
        raise HTTPException(status_code=400, detail="Use transfer ownership to assign owner")
    return template


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
    effective_features: dict[str, bool] = Field(default_factory=dict)
    mode: str = "executive"
    app_entitlements: list[str] = Field(default_factory=list)
    workspace_app_runtime: dict = Field(default_factory=dict)


class MemberDetail(BaseModel):
    user_id: str
    email: Optional[str]
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    role_template: Optional[str] = None
    custom_labels: list[str] = []
    app_entitlements: list[str] = Field(default_factory=list)
    joined_at: datetime
    is_current_user: bool
    # Invitation lifecycle: "active" once onboarding is complete, "pending"
    # while the invitee still has to set a password / verify their email.
    status: str = "active"
    last_login: Optional[datetime] = None


def _validated_app_entitlements(value: Optional[list[str]]) -> Optional[list[str]]:
    if value is None:
        return None
    try:
        return normalize_app_entitlements(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_APP_ENTITLEMENT",
                "message": str(exc),
            },
        ) from exc


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
            logger.error(
                "MFA email failed to send for user %s; falling back to direct login", user.id
            )
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
        resp = await client.post(
            f"{_get_admin_url()}/users", json=kc_user, headers=headers, timeout=15
        )

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

    verification_email_sent = False
    if keycloak_sub:
        verification_email_sent = await _send_signup_verification_email(keycloak_sub, admin_token)

    message = (
        "User created. Check email for confirmation."
        if verification_email_sent
        else "User created, but the confirmation email could not be sent. Contact an administrator."
    )
    return {
        "status": "ok",
        "message": message,
        "verification_email_sent": verification_email_sent,
    }


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
            workspaces.append(
                {
                    "id": ws.id,
                    "name": ws.name,
                    "slug": ws.slug,
                    "role": m.role,
                    "mode": getattr(ws, "mode", "executive") or "executive",
                    "app_entitlements": list_member_app_entitlements(db, m),
                    "workspace_app_runtime": safe_workspace_app_runtime_payload(ws, db=db),
                }
            )

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
        sessions.append(
            {
                "id": s.get("id"),
                "ip_address": s.get("ipAddress"),
                "start": s.get("start"),
                "last_access": s.get("lastAccess"),
                "clients": list((s.get("clients") or {}).values()),
            }
        )
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


def _resolve_workspace_and_role(
    db: DBSession, user: User, slug: str
) -> tuple[Workspace, WorkspaceMember]:
    """Fetch a workspace by slug (non-deleted) and ensure the caller is a member.

    Returns (workspace, membership). Raises 404 if workspace missing, 403 if not a member.
    """
    workspace = (
        db.query(Workspace)
        .filter(
            Workspace.slug == slug,
            Workspace.deleted_at.is_(None),
        )
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    return workspace, membership


def _effective_workspace_features(
    db: DBSession,
    workspace: Workspace,
) -> dict[str, bool]:
    """Return server-resolved managed flags without mutating persisted settings."""

    revision = str(settings.agentium_image_revision or "").strip().lower()
    return {
        feature: authoritative_projection_enabled(
            db,
            workspace,
            projection,
            runtime_revision=revision,
        )
        for projection, feature in FEATURE_BY_PROJECTION.items()
    }


def _lock_workspace_and_role_for_membership_mutation(
    db: DBSession,
    user: User,
    workspace: Workspace,
) -> tuple[Workspace, WorkspaceMember]:
    """Acquire the Blueprint-shared row lock and refresh caller authority."""

    try:
        locked_workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
    except WorkspaceEntitlementMutationConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKSPACE_MEMBERSHIP_MUTATION_CONFLICT",
                "message": str(exc),
            },
        ) from exc
    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == locked_workspace.id,
        )
        .populate_existing()
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    return locked_workspace, membership


def _invitee_identity_changed_exception() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "INVITEE_IDENTITY_CHANGED",
            "message": (
                "Invitee identity changed or became ambiguous while the workspace lock "
                "was pending; retry"
            ),
        },
    )


def _require_admin(membership: WorkspaceMember) -> None:
    if normalize_role_template(getattr(membership, "role_template", None), membership.role) not in (
        WORKSPACE_OWNER,
        WORKSPACE_ADMIN,
    ):
        raise HTTPException(status_code=403, detail="Admin access required")


def _require_owner(membership: WorkspaceMember) -> None:
    if (
        normalize_role_template(getattr(membership, "role_template", None), membership.role)
        != WORKSPACE_OWNER
    ):
        raise HTTPException(status_code=403, detail="Owner access required")


def _settings_with_managed_workspace_fields_preserved(
    current: object,
    requested: dict,
) -> dict:
    """Keep resolver/IAM-owned settings out of the generic workspace PATCH.

    ``settings`` remains a replacement payload for every ordinary key.  The
    workspace family and entitlement-enforcement flag are different: the
    resolver and Blueprint application own those transitions, respectively.
    Omitting them from a replacement payload must therefore not erase them.
    """

    current_settings = dict(current) if isinstance(current, Mapping) else {}
    next_settings = dict(requested)
    managed_top_level_fields = (
        ("family", "WORKSPACE_EXPERIENCE_SETTING_MANAGED"),
        ("showcase_seed", "SHOWCASE_SEED_MARKER_MANAGED"),
        ("chat_execution", "CHAT_EXECUTION_POLICY_MANAGED"),
        (
            "_migration_058_canonical_contracts_state",
            "WORKSPACE_MIGRATION_STATE_MANAGED",
        ),
        (
            "_migration_059_andritz_agentic_default_state",
            "WORKSPACE_MIGRATION_STATE_MANAGED",
        ),
        (WORKSPACE_GATE_KEY, "LOT7_PROJECTION_ROLLOUT_STATE_MANAGED"),
        (WORKSPACE_APP_ROLLOUT_STATE_KEY, "LOT9_WORKSPACE_APP_ROLLOUT_STATE_MANAGED"),
        (GENERIC_CONNECTORS_KEY, "GENERIC_CONNECTORS_MANAGED"),
    )
    for field, code in managed_top_level_fields:
        current_has_field = field in current_settings
        requested_has_field = field in next_settings
        if requested_has_field and (
            not current_has_field or next_settings[field] != current_settings[field]
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": code,
                    "message": f"workspace.settings.{field} is managed internally",
                },
            )
        if current_has_field:
            next_settings[field] = current_settings[field]

    current_experience_raw = current_settings.get("experience")
    current_experience = (
        dict(current_experience_raw)
        if isinstance(current_experience_raw, Mapping)
        else {}
    )
    requested_has_experience = "experience" in next_settings
    requested_experience_raw = next_settings.get("experience")
    requested_experience = (
        dict(requested_experience_raw)
        if isinstance(requested_experience_raw, Mapping)
        else {}
    )
    current_has_app_canary = WORKSPACE_APP_CANARY_MARKER in current_experience
    requested_has_app_canary = WORKSPACE_APP_CANARY_MARKER in requested_experience
    if requested_has_app_canary and (
        not current_has_app_canary
        or requested_experience[WORKSPACE_APP_CANARY_MARKER]
        != current_experience[WORKSPACE_APP_CANARY_MARKER]
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LOT9_WORKSPACE_APP_CANARY_MANAGED",
                "message": (
                    f"workspace.settings.experience.{WORKSPACE_APP_CANARY_MARKER} "
                    "is managed by the Lot 9 rollout service"
                ),
            },
        )
    if (
        requested_has_experience
        and not isinstance(requested_experience_raw, Mapping)
        and current_has_app_canary
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LOT9_WORKSPACE_APP_CANARY_MANAGED",
                "message": (
                    f"workspace.settings.experience.{WORKSPACE_APP_CANARY_MARKER} "
                    "cannot be removed by replacing workspace experience"
                ),
            },
        )
    if current_has_app_canary:
        requested_experience[WORKSPACE_APP_CANARY_MARKER] = current_experience[
            WORKSPACE_APP_CANARY_MARKER
        ]
        next_settings["experience"] = requested_experience

    current_features = current_settings.get("features")
    requested_features = next_settings.get("features")
    current_has_entitlement_flag = isinstance(current_features, Mapping) and (
        APP_ENTITLEMENTS_FEATURE in current_features
    )
    requested_has_entitlement_flag = isinstance(requested_features, Mapping) and (
        APP_ENTITLEMENTS_FEATURE in requested_features
    )

    if requested_has_entitlement_flag:
        requested_value = requested_features[APP_ENTITLEMENTS_FEATURE]
        current_value = (
            current_features[APP_ENTITLEMENTS_FEATURE] if current_has_entitlement_flag else None
        )
        if not current_has_entitlement_flag or requested_value != current_value:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "APP_ENTITLEMENTS_SETTING_MANAGED",
                    "message": (
                        "features.app_entitlements_v1 is managed by workspace Blueprint application"
                    ),
                },
            )
    elif (
        current_has_entitlement_flag
        and "features" in next_settings
        and not isinstance(requested_features, Mapping)
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "APP_ENTITLEMENTS_SETTING_MANAGED",
                "message": (
                    "features.app_entitlements_v1 cannot be removed by replacing workspace features"
                ),
            },
        )

    if current_has_entitlement_flag:
        preserved_features = (
            dict(requested_features) if isinstance(requested_features, Mapping) else {}
        )
        preserved_features[APP_ENTITLEMENTS_FEATURE] = current_features[APP_ENTITLEMENTS_FEATURE]
        next_settings["features"] = preserved_features

    managed_projection_flags = frozenset(FEATURE_BY_PROJECTION.values())
    for flag in managed_projection_flags:
        current_has_flag = isinstance(current_features, Mapping) and flag in current_features
        requested_has_flag = (
            isinstance(requested_features, Mapping) and flag in requested_features
        )
        if requested_has_flag and (
            not current_has_flag or requested_features[flag] != current_features[flag]
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "LOT7_PROJECTION_ROLLOUT_STATE_MANAGED",
                    "message": f"features.{flag} is managed by the Lot 7 rollout service",
                },
            )
        if current_has_flag:
            preserved_features = (
                dict(next_settings.get("features"))
                if isinstance(next_settings.get("features"), Mapping)
                else {}
            )
            preserved_features[flag] = current_features[flag]
            next_settings["features"] = preserved_features

    current_has_value_loop_flag = isinstance(current_features, Mapping) and (
        VALUE_LOOP_FEATURE_KEY in current_features
    )
    requested_has_value_loop_flag = isinstance(requested_features, Mapping) and (
        VALUE_LOOP_FEATURE_KEY in requested_features
    )
    if requested_has_value_loop_flag and (
        not current_has_value_loop_flag
        or requested_features[VALUE_LOOP_FEATURE_KEY]
        != current_features[VALUE_LOOP_FEATURE_KEY]
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LOT8_VALUE_LOOP_ROLLOUT_STATE_MANAGED",
                "message": (
                    f"features.{VALUE_LOOP_FEATURE_KEY} is managed by the Lot 8 "
                    "rollout service"
                ),
            },
        )
    if current_has_value_loop_flag:
        preserved_features = (
            dict(next_settings.get("features"))
            if isinstance(next_settings.get("features"), Mapping)
            else {}
        )
        preserved_features[VALUE_LOOP_FEATURE_KEY] = current_features[
            VALUE_LOOP_FEATURE_KEY
        ]
        next_settings["features"] = preserved_features

    current_has_workspace_app_flag = isinstance(current_features, Mapping) and (
        WORKSPACE_APP_PLATFORM_FEATURE in current_features
    )
    requested_has_workspace_app_flag = isinstance(requested_features, Mapping) and (
        WORKSPACE_APP_PLATFORM_FEATURE in requested_features
    )
    if requested_has_workspace_app_flag and (
        not current_has_workspace_app_flag
        or requested_features[WORKSPACE_APP_PLATFORM_FEATURE]
        != current_features[WORKSPACE_APP_PLATFORM_FEATURE]
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LOT9_WORKSPACE_APP_ROLLOUT_STATE_MANAGED",
                "message": (
                    f"features.{WORKSPACE_APP_PLATFORM_FEATURE} is managed by the Lot 9 "
                    "rollout service"
                ),
            },
        )
    if current_has_workspace_app_flag:
        preserved_features = (
            dict(next_settings.get("features"))
            if isinstance(next_settings.get("features"), Mapping)
            else {}
        )
        preserved_features[WORKSPACE_APP_PLATFORM_FEATURE] = current_features[
            WORKSPACE_APP_PLATFORM_FEATURE
        ]
        next_settings["features"] = preserved_features
    return next_settings


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

    workspace = Workspace(
        id=str(uuid4()),
        name=body.name,
        slug=slug,
        settings={"family": WorkspaceFamily.generic.value},
    )
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
        settings=public_workspace_settings(workspace.settings),
        effective_features=_effective_workspace_features(db, workspace),
        mode=getattr(workspace, "mode", "executive") or "executive",
        app_entitlements=list_member_app_entitlements(db, membership),
        workspace_app_runtime=safe_workspace_app_runtime_payload(workspace, db=db),
    )


@router.get("/workspaces")
async def list_workspaces(user: User = Depends(get_current_user), db: DBSession = Depends(get_db)):
    memberships = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).all()
    result = []
    for m in memberships:
        ws = (
            db.query(Workspace)
            .filter(
                Workspace.id == m.workspace_id,
                Workspace.is_active == True,  # noqa: E712
                Workspace.deleted_at.is_(None),
            )
            .first()
        )
        if ws:
            member_count = (
                db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == ws.id).count()
            )
            result.append(
                {
                    "id": ws.id,
                    "name": ws.name,
                    "slug": ws.slug,
                    "role": m.role,
                    "role_template": normalize_role_template(
                        getattr(m, "role_template", None), m.role
                    ),
                    "member_count": member_count,
                    "created_at": ws.created_at.isoformat() if ws.created_at else None,
                    "settings": public_workspace_settings(ws.settings),
                    "effective_features": _effective_workspace_features(db, ws),
                    "mode": getattr(ws, "mode", "executive") or "executive",
                    "app_entitlements": list_member_app_entitlements(db, m),
                    "workspace_app_runtime": safe_workspace_app_runtime_payload(ws, db=db),
                }
            )
    return result


@router.get("/workspaces/{slug}", response_model=WorkspaceDetail)
async def get_workspace(
    slug: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    member_count = (
        db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace.id).count()
    )
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=membership.role,
        role_template=normalize_role_template(
            getattr(membership, "role_template", None), membership.role
        ),
        is_active=workspace.is_active,
        member_count=member_count,
        created_at=workspace.created_at,
        deleted_at=workspace.deleted_at,
        settings=public_workspace_settings(workspace.settings),
        effective_features=_effective_workspace_features(db, workspace),
        mode=getattr(workspace, "mode", "executive") or "executive",
        app_entitlements=list_member_app_entitlements(db, membership),
        workspace_app_runtime=safe_workspace_app_runtime_payload(workspace, db=db),
    )


@router.patch("/workspaces/{slug}", response_model=WorkspaceDetail)
async def update_workspace(
    slug: str,
    body: WorkspaceUpdate,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    workspace, membership = _lock_workspace_and_role_for_membership_mutation(
        db,
        user,
        workspace,
    )
    _require_admin(membership)
    written_secrets = secret_paths(body.settings) if body.settings is not None else []
    if written_secrets:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "WORKSPACE_SECRET_WRITE_ONLY",
                "message": "A connector secret is set on its connector, not in workspace settings",
                "fields": written_secrets,
            },
        )

    if "platform_brand" in body.model_fields_set:
        # Narrow compare-and-set under the existing workspace lock. Branding
        # must not overwrite unrelated settings or a concurrent brand edit.
        if body.settings is not None or "expected_platform_brand" not in body.model_fields_set:
            raise HTTPException(status_code=422, detail="BRAND_EXPECTED_VALUE_REQUIRED")
        current_settings = dict(workspace.settings or {})
        if current_settings.get("platform_brand") != body.expected_platform_brand:
            raise HTTPException(status_code=409, detail="WORKSPACE_BRAND_CONFLICT")
        if body.platform_brand is None:
            current_settings.pop("platform_brand", None)
        else:
            current_settings["platform_brand"] = body.platform_brand.model_dump(exclude_none=True)
        workspace.settings = current_settings
        from app.services.audit_logger import emit_audit_event

        before = body.expected_platform_brand or {}
        after = current_settings.get("platform_brand") or {}
        emit_audit_event(
            event_type="workspace.brand.updated", workspace_id=workspace.id, actor=user.id,
            details={
                "enabled": bool(after),
                "changed_fields": sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key)),
            },
            db=db,
        )

    if body.name is not None:
        workspace.name = body.name
    if body.settings is not None:
        workspace.settings = _settings_with_managed_workspace_fields_preserved(
            workspace.settings,
            with_stored_secrets(workspace.settings, body.settings),
        )
    if body.mode is not None:
        workspace.mode = body.mode.value

    db.commit()
    db.refresh(workspace)

    # The chat source_policy is resolved with the chat System SHADOWING the
    # workspace settings, so an admin toggle on workspace settings must also be
    # mirrored onto the chat System or it would be silently overridden. Keep the
    # two layers converged for the expert-correction flags (no-op when absent).
    if body.settings is not None:
        try:
            from app.services.systems.bootstrap import (
                sync_chat_system_expert_correction_policy,
            )

            sync_chat_system_expert_correction_policy(db, workspace)
        except Exception:  # noqa: BLE001 — settings already saved; sync is best-effort.
            logging.getLogger(__name__).exception(
                "update_workspace.expert_correction_policy_sync_failed",
                extra={"workspace_slug": workspace.slug},
            )

    member_count = (
        db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace.id).count()
    )
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=membership.role,
        role_template=normalize_role_template(
            getattr(membership, "role_template", None), membership.role
        ),
        is_active=workspace.is_active,
        member_count=member_count,
        created_at=workspace.created_at,
        settings=public_workspace_settings(workspace.settings),
        effective_features=_effective_workspace_features(db, workspace),
        mode=getattr(workspace, "mode", "executive") or "executive",
        app_entitlements=list_member_app_entitlements(db, membership),
        workspace_app_runtime=safe_workspace_app_runtime_payload(workspace, db=db),
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
    - `portfolio` → Portfolio-first showcase surface; provisioned by automation, not the UI.
    The underlying data never changes; only the shell surface adapts.
    """
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    workspace, membership = _lock_workspace_and_role_for_membership_mutation(
        db,
        user,
        workspace,
    )
    _require_admin(membership)
    workspace.mode = body.mode.value
    db.commit()
    db.refresh(workspace)
    member_count = (
        db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace.id).count()
    )
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=membership.role,
        role_template=normalize_role_template(
            getattr(membership, "role_template", None), membership.role
        ),
        is_active=workspace.is_active,
        member_count=member_count,
        created_at=workspace.created_at,
        settings=public_workspace_settings(workspace.settings),
        effective_features=_effective_workspace_features(db, workspace),
        mode=workspace.mode or "executive",
        app_entitlements=list_member_app_entitlements(db, membership),
        workspace_app_runtime=safe_workspace_app_runtime_payload(workspace, db=db),
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
    workspace, membership = _lock_workspace_and_role_for_membership_mutation(
        db,
        user,
        workspace,
    )
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
    workspace, membership = _lock_workspace_and_role_for_membership_mutation(
        db,
        user,
        workspace,
    )
    if (
        normalize_role_template(getattr(membership, "role_template", None), membership.role)
        != WORKSPACE_OWNER
    ):
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

    workspace, membership = _lock_workspace_and_role_for_membership_mutation(
        db,
        user,
        workspace,
    )
    _require_owner(membership)

    if body.new_owner_user_id == user.id:
        raise HTTPException(status_code=400, detail="You are already the owner")

    new_owner_membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == body.new_owner_user_id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .populate_existing()
        .first()
    )
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
    workspace, membership = _lock_workspace_and_role_for_membership_mutation(
        db,
        user,
        workspace,
    )
    if (
        normalize_role_template(getattr(membership, "role_template", None), membership.role)
        == WORKSPACE_OWNER
    ):
        raise HTTPException(
            status_code=400,
            detail="Owner cannot leave. Transfer ownership first, or delete the workspace.",
        )

    db.delete(membership)
    db.commit()
    return {"status": "ok"}


def _member_invitation_status(kc_data: dict, last_login: Optional[datetime]) -> str:
    """Derive whether an invitee has finished onboarding.

    Invited users are provisioned in Keycloak with the
    ``UPDATE_PASSWORD``/``VERIFY_EMAIL`` required actions and an unverified
    email; they stay ``pending`` until they set a password or log in at least
    once. Anyone who has logged in, or whose Keycloak account has no pending
    onboarding action, resolves to ``active``.
    """
    if last_login is not None:
        return "active"
    required = set(kc_data.get("requiredActions") or [])
    if "UPDATE_PASSWORD" in required or kc_data.get("emailVerified") is False:
        return "pending"
    return "active"


@router.get("/workspaces/{slug}/members", response_model=list[MemberDetail])
async def list_members(
    slug: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List all members of a workspace (members can see this list)."""
    workspace, _ = _resolve_workspace_and_role(db, user, slug)

    members = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id)
        .order_by(WorkspaceMember.joined_at.asc())
        .all()
    )

    result: list[MemberDetail] = []
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        if not u:
            continue
        kc_data = await _get_kc_user(u.keycloak_sub) if u.keycloak_sub else {}
        result.append(
            MemberDetail(
                user_id=u.id,
                email=u.email,
                username=u.username,
                first_name=kc_data.get("firstName"),
                last_name=kc_data.get("lastName"),
                role=m.role,
                role_template=normalize_role_template(getattr(m, "role_template", None), m.role),
                custom_labels=m.custom_labels or [],
                app_entitlements=list_member_app_entitlements(db, m),
                joined_at=m.joined_at,
                is_current_user=(u.id == user.id),
                status=_member_invitation_status(kc_data, u.last_login),
                last_login=u.last_login,
            )
        )
    return result


async def _find_or_create_kc_user(email: str, admin_token: str) -> tuple[str, bool]:
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


def _action_email_redirect_params() -> dict:
    """Query params making Keycloak action emails link back to the app.

    Without ``client_id``/``redirect_uri`` the final "account updated" page is
    a dead end. ``redirect_uri`` must match a registered redirectUri of the
    client; when no public app URL is configured we keep the legacy behavior.
    """
    if not settings.app_public_url:
        return {}
    return {
        "client_id": settings.keycloak_client_id,
        "redirect_uri": settings.app_public_url.rstrip("/") + "/",
    }


async def _send_invitation_email(kc_sub: str, admin_token: str) -> bool:
    """Trigger the ``UPDATE_PASSWORD``/``VERIFY_EMAIL`` action email.

    Delivery is best-effort and runs only after the local membership transaction
    commits, so no external call holds the Workspace row lock. A delivery
    failure is logged and reported to the caller without rolling back the
    already committed invitation.
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
                params=_action_email_redirect_params(),
                headers=headers,
                timeout=10,
            )
        if resp.status_code not in (200, 204):
            logger.warning(
                "Keycloak invitation email not sent (status=%s, body=%s)",
                resp.status_code,
                resp.text,
            )
            return False
        return True
    except Exception:
        logger.warning("Keycloak invitation email delivery failed", exc_info=True)
        return False


async def _send_signup_verification_email(kc_sub: str, admin_token: str) -> bool:
    """Trigger the verification email for a self-service signup user."""
    headers = {
        "Authorization": f"Bearer {admin_token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{_get_admin_url()}/users/{kc_sub}/execute-actions-email",
                json=["VERIFY_EMAIL"],
                params=_action_email_redirect_params(),
                headers=headers,
                timeout=10,
            )
        if resp.status_code in (200, 204):
            return True
        logger.warning(
            "Keycloak signup verification email not sent (status=%s, body=%s)",
            resp.status_code,
            resp.text,
        )
    except Exception:
        logger.warning("Keycloak signup verification email delivery failed", exc_info=True)
    return False


@router.get("/workspaces/{slug}/members/available")
async def available_members(
    slug: str,
    q: str = Query(default="", max_length=120),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)
    needle = q.strip().lower()
    if len(needle) < 2:
        return {"users": []}
    member_ids = (
        db.query(WorkspaceMember.user_id)
        .filter(WorkspaceMember.workspace_id == workspace.id)
        .subquery()
        .select()
    )
    pattern = f"%{needle}%"
    rows = (
        db.query(User.id, User.email, User.username)
        .filter(
            User.is_active.is_(True),
            User.email.isnot(None),
            not_(User.id.in_(member_ids)),
            or_(User.email.ilike(pattern), User.username.ilike(pattern)),
        )
        .order_by(User.email.asc())
        .limit(10)
        .all()
    )
    return {
        "users": [
            {"id": row.id, "email": row.email, "username": row.username}
            for row in rows
        ]
    }


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
         ``UPDATE_PASSWORD`` + ``VERIFY_EMAIL`` required actions, create the
         local stub + membership, commit, then trigger the onboarding email.

    The caller must be ``owner`` or ``admin`` of the workspace.

    Keycloak lookup/provisioning happens before the Workspace row lock. Once
    the lock is acquired, caller authority and freshly reloaded entitlement
    settings are checked again before any local User, membership or grant is
    written. A policy change can therefore reject the local invite after
    provisioning a reusable Keycloak identity, but it cannot send a misleading
    invitation email. Email delivery happens after commit and is best-effort;
    no external network call is held inside the database critical section.
    """
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)

    requested_app_entitlements = _validated_app_entitlements(body.app_entitlements)
    if app_entitlements_enabled(workspace) and requested_app_entitlements is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "APP_ENTITLEMENTS_REQUIRED",
                "message": (
                    "app_entitlements must be provided when workspace application "
                    "entitlements are enabled"
                ),
            },
        )

    role_template = _resolve_member_role_template(
        role=body.role,
        role_template=body.role_template,
    )

    email = body.email.lower()
    target_user = db.query(User).filter(User.email == email).first()
    kc_sub: str | None = None
    admin_token: str | None = None
    resolved_via_keycloak = False
    created_in_kc = False

    if not target_user:
        admin_token = await _get_admin_token()
        if not admin_token:
            raise HTTPException(
                status_code=503,
                detail="Cannot reach Keycloak admin API to provision the invitee",
            )
        kc_sub, created_in_kc = await _find_or_create_kc_user(email, admin_token)
        resolved_via_keycloak = True

    workspace, membership = _lock_workspace_and_role_for_membership_mutation(
        db,
        user,
        workspace,
    )
    _require_admin(membership)
    if app_entitlements_enabled(workspace) and requested_app_entitlements is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "APP_ENTITLEMENTS_REQUIRED",
                "message": (
                    "app_entitlements must be provided when workspace application "
                    "entitlements are enabled"
                ),
            },
        )

    target_user = db.query(User).filter(User.email == email).populate_existing().first()
    if target_user is not None and resolved_via_keycloak and target_user.keycloak_sub != kc_sub:
        raise _invitee_identity_changed_exception()
    if not target_user and resolved_via_keycloak and kc_sub:
        target_user = db.query(User).filter(User.keycloak_sub == kc_sub).populate_existing().first()
        if target_user is not None and (target_user.email or "").lower() != email:
            raise _invitee_identity_changed_exception()
    if not target_user and resolved_via_keycloak and kc_sub:
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
    if not target_user:
        raise _invitee_identity_changed_exception()

    existing = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == target_user.id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .populate_existing()
        .first()
    )
    if existing:
        current_template = normalize_role_template(
            getattr(existing, "role_template", None),
            existing.role,
        )
        current_entitlements = list_member_app_entitlements(db, existing)
        same_role = current_template == role_template and existing.role != "owner"
        same_labels = (body.custom_labels is None) or (
            list(body.custom_labels) == list(existing.custom_labels or [])
        )
        same_entitlements = (
            requested_app_entitlements is None
            or requested_app_entitlements == current_entitlements
        )
        if same_role and same_labels and same_entitlements:
            return {
                "status": "ok",
                "action": "unchanged",
                "user_id": target_user.id,
                "role": existing.role,
                "role_template": current_template,
                "app_entitlements": current_entitlements,
                "invitation_email_sent": False,
            }
        if existing.role == "owner":
            raise HTTPException(
                status_code=400,
                detail="Owner membership can only change through ownership transfer",
            )
        before_template = current_template
        existing.role_template = role_template
        existing.role = legacy_role_for_template(role_template)
        if body.custom_labels is not None:
            existing.custom_labels = body.custom_labels
        if requested_app_entitlements is not None:
            replace_member_app_entitlements(
                db,
                existing,
                requested_app_entitlements,
                granted_by_user_id=user.id,
                grant_source="workspace_invitation",
            )
        from app.services.audit_logger import emit_audit_event

        emit_audit_event(
            event_type="workspace.member.updated",
            workspace_id=workspace.id,
            actor=user.id,
            details={
                "target_user_id": target_user.id,
                "before_role_template": before_template,
                "after_role_template": role_template,
                "source": "workspace_invitation",
            },
            db=db,
        )
        db.commit()
        return {
            "status": "ok",
            "action": "updated",
            "user_id": target_user.id,
            "role": existing.role,
            "role_template": role_template,
            "app_entitlements": list_member_app_entitlements(db, existing),
            "invitation_email_sent": False,
        }

    new_member = WorkspaceMember(
        user_id=target_user.id,
        workspace_id=workspace.id,
        role=legacy_role_for_template(role_template),
        role_template=role_template,
        custom_labels=body.custom_labels or [],
    )
    db.add(new_member)
    db.flush()
    replace_member_app_entitlements(
        db,
        new_member,
        requested_app_entitlements or [],
        granted_by_user_id=user.id,
        grant_source="workspace_invitation",
    )
    from app.services.audit_logger import emit_audit_event

    emit_audit_event(
        event_type="workspace.member.added",
        workspace_id=workspace.id,
        actor=user.id,
        details={
            "target_user_id": target_user.id,
            "role_template": role_template,
            "provisioned_in_keycloak": created_in_kc,
        },
        db=db,
    )
    db.commit()
    invitation_email_sent = False
    if created_in_kc and kc_sub and admin_token:
        invitation_email_sent = await _send_invitation_email(kc_sub, admin_token)
    logger.info(
        "Invited teammate to workspace workspace_id=%s target_user=%s role=%s "
        "provisioned_in_keycloak=%s invitation_email_sent=%s",
        workspace.id,
        target_user.id,
        body.role,
        created_in_kc,
        invitation_email_sent,
    )
    return {
        "status": "ok",
        "action": "added",
        "user_id": target_user.id,
        "role": legacy_role_for_template(role_template),
        "role_template": role_template,
        "app_entitlements": list_member_app_entitlements(db, new_member),
        "invitation_email_sent": invitation_email_sent,
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

    requested_app_entitlements = _validated_app_entitlements(body.app_entitlements)

    workspace, membership = _lock_workspace_and_role_for_membership_mutation(
        db,
        user,
        workspace,
    )
    _require_admin(membership)

    target = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .populate_existing()
        .first()
    )
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
    role_template = _resolve_member_role_template(
        role=body.role,
        role_template=body.role_template,
    )
    before_template = normalize_role_template(
        getattr(target, "role_template", None),
        target.role,
    )
    before_labels = list(target.custom_labels or [])
    before_entitlements = list_member_app_entitlements(db, target)
    next_labels = body.custom_labels if body.custom_labels is not None else before_labels
    next_entitlements = (
        requested_app_entitlements
        if requested_app_entitlements is not None
        else before_entitlements
    )
    if (
        before_template == role_template
        and before_labels == next_labels
        and before_entitlements == next_entitlements
    ):
        return {
            "status": "ok",
            "action": "unchanged",
            "app_entitlements": before_entitlements,
        }
    target.role_template = role_template
    target.role = legacy_role_for_template(role_template)
    if body.custom_labels is not None:
        target.custom_labels = body.custom_labels
    if requested_app_entitlements is not None:
        replace_member_app_entitlements(
            db,
            target,
            requested_app_entitlements,
            granted_by_user_id=user.id,
            grant_source="workspace_member_update",
        )
    from app.services.audit_logger import emit_audit_event

    emit_audit_event(
        event_type="workspace.member.updated",
        workspace_id=workspace.id,
        actor=user.id,
        details={
            "target_user_id": target.user_id,
            "before_role_template": before_template,
            "after_role_template": role_template,
            "source": "workspace_member_update",
        },
        db=db,
    )
    db.commit()
    return {
        "status": "ok",
        "action": "updated",
        "app_entitlements": list_member_app_entitlements(db, target),
    }


@router.delete("/workspaces/{slug}/members/{user_id}")
async def remove_member(
    slug: str,
    user_id: str,
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    workspace, membership = _resolve_workspace_and_role(db, user, slug)
    _require_admin(membership)

    workspace, membership = _lock_workspace_and_role_for_membership_mutation(
        db,
        user,
        workspace,
    )
    _require_admin(membership)

    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself. Use /leave instead.")

    target = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.workspace_id == workspace.id,
        )
        .populate_existing()
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == "owner":
        raise HTTPException(
            status_code=400, detail="Cannot remove the owner. Transfer ownership first."
        )

    from app.services.audit_logger import emit_audit_event

    emit_audit_event(
        event_type="workspace.member.removed",
        workspace_id=workspace.id,
        actor=user.id,
        details={
            "target_user_id": target.user_id,
            "role_template": normalize_role_template(
                getattr(target, "role_template", None),
                target.role,
            ),
        },
        db=db,
    )
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
