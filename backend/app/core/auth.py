"""Keycloak OIDC authentication — JWT validation and FastAPI dependencies"""
import time
import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.iam.roles import WORKSPACE_OWNER
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

_jwks_cache: dict = {}
_jwks_cache_ts: float = 0
_JWKS_TTL = 3600


def _kc_base_internal() -> str:
    """URL used for server-to-server calls (JWKS, token, admin). Defaults to public."""
    return (settings.keycloak_url_internal or settings.keycloak_url).rstrip("/")


def _kc_base_public() -> str:
    """URL used for iss validation and user-facing flows."""
    return settings.keycloak_url.rstrip("/")


def _get_jwks_url() -> str:
    return f"{_kc_base_internal()}/realms/{settings.keycloak_realm}/protocol/openid-connect/certs"


def _get_token_url() -> str:
    return f"{_kc_base_internal()}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"


def _get_admin_url() -> str:
    return f"{_kc_base_internal()}/admin/realms/{settings.keycloak_realm}"


def _get_logout_url() -> str:
    return f"{_kc_base_internal()}/realms/{settings.keycloak_realm}/protocol/openid-connect/logout"


def _fetch_jwks() -> dict:
    global _jwks_cache, _jwks_cache_ts
    now = time.time()
    if _jwks_cache and (now - _jwks_cache_ts) < _JWKS_TTL:
        return _jwks_cache
    try:
        resp = httpx.get(_get_jwks_url(), timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_cache_ts = now
    except Exception as e:
        logger.warning("Failed to fetch JWKS: %s", e)
        if _jwks_cache:
            return _jwks_cache
        raise HTTPException(status_code=503, detail="Auth service unavailable")
    return _jwks_cache


def decode_token(token: str) -> dict:
    """Validate and decode a Keycloak JWT using RS512 JWKS."""
    jwks_data = _fetch_jwks()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError:
        raise HTTPException(status_code=401, detail="Invalid token")

    kid = header.get("kid")
    public_key = None
    for key_data in jwks_data.get("keys", []):
        if key_data.get("kid") == kid:
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
            break

    if not public_key:
        _jwks_cache.clear()
        jwks_data = _fetch_jwks()
        for key_data in jwks_data.get("keys", []):
            if key_data.get("kid") == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)
                break

    if not public_key:
        raise HTTPException(status_code=401, detail="Unknown signing key")

    expected_issuer = f"{_kc_base_public()}/realms/{settings.keycloak_realm}"

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256", "RS384", "RS512"],
            issuer=expected_issuer,
            options={"verify_exp": True, "verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

    # Keycloak direct-access tokens store the issuing client in "azp", not "aud"
    # (aud is typically "account"). We accept either.
    expected_client = settings.keycloak_client_id
    azp = payload.get("azp")
    aud = payload.get("aud")
    aud_list = aud if isinstance(aud, list) else ([aud] if aud else [])
    if azp != expected_client and expected_client not in aud_list:
        raise HTTPException(
            status_code=401,
            detail=f"Token not issued for this client (azp={azp}, aud={aud_list})",
        )

    return payload


def _extract_roles(payload: dict) -> list[str]:
    """Extract client roles from resource_access or app_roles claim."""
    roles = payload.get("app_roles", [])
    if roles:
        return roles
    resource_access = payload.get("resource_access", {})
    client_roles = resource_access.get(settings.keycloak_client_id, {})
    return client_roles.get("roles", [])


def _ensure_personal_workspace(db: DBSession, user: User, display_name: Optional[str] = None) -> None:
    """If the user has no workspace memberships, create a Personal workspace.

    Idempotent: if the user already belongs to any workspace (even as member),
    no new workspace is created.
    """
    has_any = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).first()
    if has_any:
        return

    label = display_name or (user.email.split("@")[0] if user.email else user.username)
    name = f"{label}'s workspace" if label else "Personal"
    # Unique slug: personal-<first8 of user id>
    slug = f"personal-{user.id[:8]}"

    workspace = Workspace(
        id=str(uuid4()),
        name=name[:255],
        slug=slug,
        settings={"kind": "personal"},
    )
    db.add(workspace)
    db.flush()

    membership = WorkspaceMember(
        user_id=user.id,
        workspace_id=workspace.id,
        role="owner",
        role_template=WORKSPACE_OWNER,
    )
    db.add(membership)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: DBSession = Depends(get_db),
) -> User:
    """Validate JWT and return or auto-create the User."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(credentials.credentials)

    keycloak_sub = payload.get("sub")
    if not keycloak_sub:
        raise HTTPException(status_code=401, detail="Invalid token: no sub")

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
        db.flush()

    if not user.keycloak_sub:
        user.keycloak_sub = keycloak_sub
    user.last_login = datetime.utcnow()
    user.email = payload.get("email") or user.email
    user.username = payload.get("preferred_username") or user.username

    roles = _extract_roles(payload)
    if "organization_admin" in roles:
        user.role = "admin"

    # Auto-provision a personal workspace on first appearance
    display_name = payload.get("given_name") or payload.get("preferred_username")
    _ensure_personal_workspace(db, user, display_name)

    db.commit()
    db.refresh(user)
    return user


async def get_current_workspace(
    user: User = Depends(get_current_user),
    x_workspace_slug: Optional[str] = Header(None, alias="X-Workspace-Slug"),
    db: DBSession = Depends(get_db),
) -> Workspace:
    """Resolve the active workspace for the current user.

    Policy:
    - If ``X-Workspace-Slug`` header is set, it must point to an active
      workspace the user is a member of (else 404/403).
    - Otherwise, fall back to the user's first available workspace
      (ordered by joined_at).
    - If the user has no workspaces at all, 409 Conflict (auto-provisioning
      should have created a personal workspace; absence means something went
      wrong or the user was fully removed).
    """
    if x_workspace_slug:
        workspace = db.query(Workspace).filter(
            Workspace.slug == x_workspace_slug,
            Workspace.is_active == True,  # noqa: E712
            Workspace.deleted_at.is_(None),
        ).first()
        if not workspace:
            raise HTTPException(status_code=404, detail=f"Workspace '{x_workspace_slug}' not found")

        membership = db.query(WorkspaceMember).filter(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.workspace_id == workspace.id,
        ).first()
        if not membership:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "WORKSPACE_ACCESS_DENIED",
                    "message": "Not a member of this workspace",
                },
            )

        return workspace

    # Fallback: first workspace where the user is a member
    membership = (
        db.query(WorkspaceMember)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .filter(
            WorkspaceMember.user_id == user.id,
            Workspace.is_active == True,  # noqa: E712
            Workspace.deleted_at.is_(None),
        )
        .order_by(WorkspaceMember.joined_at.asc())
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=409,
            detail="No workspace available. Please create one.",
        )
    workspace = db.query(Workspace).filter(Workspace.id == membership.workspace_id).first()
    return workspace  # type: ignore[return-value]


async def get_optional_workspace(
    user: User = Depends(get_current_user),
    x_workspace_slug: Optional[str] = Header(None, alias="X-Workspace-Slug"),
    db: DBSession = Depends(get_db),
) -> Optional[Workspace]:
    """Same as get_current_workspace but returns None instead of raising when
    no workspace is available (useful for read-mostly/cross-workspace endpoints)."""
    try:
        return await get_current_workspace(user=user, x_workspace_slug=x_workspace_slug, db=db)
    except HTTPException as e:
        if e.status_code == 409:
            return None
        raise


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: DBSession = Depends(get_db),
) -> Optional[User]:
    """Return user if authenticated, None otherwise (for open endpoints during transition)."""
    if not credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None
