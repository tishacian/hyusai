"""Inbound webhook HMAC verification + emission helpers (Phase 3)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session as DBSession

from app.models.webhook_hook import WebhookHook


SIGNATURE_HEADER = "X-Agentium-Signature"


def generate_hook_secret() -> str:
    return secrets.token_urlsafe(32)


def parse_signature_header(header_value: Optional[str]) -> str:
    """Normalize ``sha256=<hex>`` or bare hex into lowercase hex digest."""
    raw = (header_value or "").strip()
    if raw.lower().startswith("sha256="):
        raw = raw.split("=", 1)[1].strip()
    return raw.lower()


def compute_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_hmac_signature(secret: str, body: bytes, signature_header: Optional[str]) -> bool:
    """Constant-time compare of the request signature against ``secret``."""
    provided = parse_signature_header(signature_header)
    if not provided or not secret:
        return False
    expected = compute_signature(secret, body)
    return hmac.compare_digest(expected, provided)


def serialize_hook(hook: WebhookHook, *, include_secret: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": hook.id,
        "workspace_id": hook.workspace_id,
        "system_id": hook.system_id,
        "name": hook.name,
        "event_type": hook.event_type,
        "enabled": bool(hook.enabled),
        "created_at": hook.created_at.isoformat() if hook.created_at else None,
        "updated_at": hook.updated_at.isoformat() if hook.updated_at else None,
        "path": f"/api/v1/hooks/{hook.id}",
    }
    if include_secret:
        payload["secret"] = hook.secret
    return payload


def lookup_enabled_hook(db: DBSession, hook_id: str) -> Optional[WebhookHook]:
    return (
        db.query(WebhookHook)
        .filter(WebhookHook.id == hook_id, WebhookHook.enabled.is_(True))
        .first()
    )


def authenticate_hook(
    db: DBSession,
    hook_id: str,
    *,
    body: bytes,
    signature_header: Optional[str],
) -> Tuple[Optional[WebhookHook], Optional[str]]:
    """Return ``(hook, None)`` on success or ``(None, reason)`` on failure."""
    hook = db.query(WebhookHook).filter(WebhookHook.id == hook_id).first()
    if hook is None:
        return None, "not_found"
    if not hook.enabled:
        return None, "disabled"
    if not verify_hmac_signature(hook.secret, body, signature_header):
        return None, "invalid_signature"
    return hook, None
