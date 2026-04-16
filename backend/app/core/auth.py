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
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

_jwks_cache: dict = {}
_jwks_cache_ts: float = 0
_JWKS_TTL = 3600


def _get_jwks_url() -> str:
    return f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/certs"


def _get_token_url() -> str:
    return f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"


def _get_admin_url() -> str:
    return f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}"


def _get_logout_url() -> str:
    return f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/logout"


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

    expected_issuer = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"

    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256", "RS384", "RS512"],
            audience=settings.keycloak_client_id,
            issuer=expected_issuer,
            options={"verify_exp": True, "verify_aud": True},
        )
    except jwt.exceptions.MissingRequiredClaimError:
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

    return payload


def _extract_roles(payload: dict) -> list[str]:
    """Extract client roles from resource_access or app_roles claim."""
    roles = payload.get("app_roles", [])
    if roles:
        return roles
    resource_access = payload.get("resource_access", {})
    client_roles = resource_access.get(settings.keycloak_client_id, {})
    return client_roles.get("roles", [])


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
    user.email = payload.get("email") or user.email
    user.username = payload.get("preferred_username") or user.username

    roles = _extract_roles(payload)
    if "organization_admin" in roles:
        user.role = "admin"

    db.commit()
    db.refresh(user)
    return user


async def get_current_workspace(
    user: User = Depends(get_current_user),
    x_workspace_slug: Optional[str] = Header(None, alias="X-Workspace-Slug"),
    db: DBSession = Depends(get_db),
) -> Optional[Workspace]:
    """Resolve workspace from header and verify membership."""
    if not x_workspace_slug:
        return None

    workspace = db.query(Workspace).filter(Workspace.slug == x_workspace_slug, Workspace.is_active == True).first()
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Workspace '{x_workspace_slug}' not found")

    membership = db.query(WorkspaceMember).filter(
        WorkspaceMember.user_id == user.id,
        WorkspaceMember.workspace_id == workspace.id,
    ).first()
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this workspace")

    return workspace


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
