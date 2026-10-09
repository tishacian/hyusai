"""Workspace-first, write-only encrypted Hub connections.

Allowed enterprise origins are operator-owned (HF_ALLOWED_ENDPOINTS). A
workspace cannot turn a connector into an arbitrary HTTP proxy. Secrets never
use the generic connector's development plaintext fallback.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.services.huggingface.errors import HFError

DEFAULT_ENDPOINT = "https://huggingface.co"
INFERENCE_ENDPOINT = "https://router.huggingface.co/v1"


def normalize_endpoint(value: str | None) -> str:
    if value is not None and not isinstance(value, str):
        raise HFError("HF_ENDPOINT_INVALID", "The Hub endpoint must be an HTTPS origin string.")
    raw = (value or DEFAULT_ENDPOINT).strip()
    try:
        url = urlsplit(raw)
        port = url.port
    except ValueError:
        raise HFError("HF_ENDPOINT_INVALID", "Configure a valid HTTPS Hub origin.") from None
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
        or any(c.isspace() for c in raw)
        or "\\" in raw
    ):
        raise HFError(
            "HF_ENDPOINT_INVALID", "Configure an HTTPS Hub origin without a path or credentials."
        )
    host = url.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    else:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise HFError("HF_ENDPOINT_INVALID", "Configure a valid HTTPS Hub hostname.") from None
    return f"https://{host}" + (f":{port}" if port and port != 443 else "")


def validate_endpoint(value: str | None) -> str:
    endpoint = normalize_endpoint(value)
    allowed = {DEFAULT_ENDPOINT}
    for item in os.getenv("HF_ALLOWED_ENDPOINTS", "").split(","):
        if item.strip():
            allowed.add(normalize_endpoint(item))
    if endpoint not in allowed:
        raise HFError(
            "HF_ENDPOINT_FORBIDDEN", "This Hub endpoint is not permitted by the platform.", 403
        )
    return endpoint


def encrypt_token(token: str) -> str:
    from app.services.connectors.generic import service

    token = token.strip()
    if (
        not token
        or len(token) > 4096
        or any(character.isspace() or ord(character) < 32 for character in token)
    ):
        raise HFError("HF_CONFIG_INVALID", "The Hub token must be a nonempty single-line value.")
    try:
        if service._fernet_from_env() is None:
            raise HFError(
                "HF_ENCRYPTION_REQUIRED",
                "Configure CONNECTOR_SECRETS_FERNET_KEY before saving a Hub token.",
                503,
            )
        return service._encrypt_secret(token)
    except service.EncryptionNotConfigured:
        raise HFError(
            "HF_ENCRYPTION_REQUIRED", "The connector encryption key is invalid.", 503
        ) from None


def decrypt_token(blob: str | None) -> str | None:
    if not blob:
        return None
    from app.services.connectors.generic import service

    try:
        envelope = json.loads(blob)
        if (
            not isinstance(envelope, dict)
            or not envelope.get("ciphertext")
            or "plaintext" in envelope
        ):
            raise ValueError("Encrypted envelope required")
        return service._decrypt_secret(blob)
    except Exception:
        raise HFError(
            "HF_CREDENTIAL_UNREADABLE",
            "Reconnect Hugging Face: the stored token cannot be decrypted.",
            503,
        ) from None


@dataclass(frozen=True)
class Connection:
    endpoint: str = DEFAULT_ENDPOINT
    token: str | None = field(default=None, repr=False)
    source: str = "public"
    workspace_id: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "endpoint", validate_endpoint(self.endpoint))

    @classmethod
    def resolve(cls, db: Any, workspace: Any = None) -> "Connection":
        if workspace is not None and (
            not getattr(workspace, "is_active", True) or getattr(workspace, "deleted_at", None)
        ):
            raise HFError("HF_WORKSPACE_UNAVAILABLE", "The workspace is disabled or deleted.", 403)
        settings = getattr(workspace, "settings", None) or {}
        entries = settings.get("generic_connectors", {})
        workspace_id = getattr(workspace, "id", None)
        # Presence matters: an explicitly anonymous workspace never inherits
        # the platform's more privileged credential.
        if "huggingface" in entries:
            entry = entries["huggingface"] or {}
            return cls(
                (entry.get("values") or {}).get("endpoint") or DEFAULT_ENDPOINT,
                decrypt_token((entry.get("secrets") or {}).get("token")),
                "workspace",
                workspace_id,
            )
        platform = get_platform_config(db)
        config = (platform.connection or {}) if platform else {}
        if config:
            return cls(
                config.get("endpoint") or DEFAULT_ENDPOINT,
                decrypt_token(config.get("token_encrypted")),
                "platform",
                workspace_id,
            )
        return cls(workspace_id=workspace_id)

    def public(self) -> dict:
        return {"endpoint": self.endpoint, "token_set": bool(self.token), "source": self.source}


def get_platform_config(db):
    if db is None:
        return None
    from app.models.huggingface import HFPlatformConfig

    return (
        db.query(HFPlatformConfig)
        .populate_existing()
        .filter(HFPlatformConfig.id == "default")
        .first()
    )


def set_platform_connection(db, values: dict, *, actor: str) -> dict:
    from app.models.huggingface import HFPlatformConfig
    from app.services.audit_logger import emit_audit_event

    unknown = set(values) - {"endpoint", "token", "clear_token"}
    if unknown:
        raise HFError("HF_CONFIG_INVALID", "Unknown connection fields.")
    if "clear_token" in values and not isinstance(values["clear_token"], bool):
        raise HFError("HF_CONFIG_INVALID", "clear_token must be a boolean.")
    config = get_platform_config(db)
    if config is None:
        config = HFPlatformConfig(id="default", connection={}, policy={})
        db.add(config)
    previous = dict(config.connection or {})
    endpoint = validate_endpoint(values.get("endpoint", previous.get("endpoint")))
    if (
        endpoint != previous.get("endpoint", DEFAULT_ENDPOINT)
        and previous.get("token_encrypted")
        and not values.get("token")
        and not values.get("clear_token")
    ):
        raise HFError(
            "HF_TOKEN_ENDPOINT_CHANGED",
            "Replace or clear the token when changing its Hub endpoint.",
        )
    previous["endpoint"] = endpoint
    if values.get("clear_token"):
        previous.pop("token_encrypted", None)
    if values.get("token"):
        token = values["token"]
        if not isinstance(token, str) or len(token) > 4096:
            raise HFError(
                "HF_CONFIG_INVALID", "The Hub token must be text of at most 4096 characters."
            )
        previous["token_encrypted"] = encrypt_token(token.strip())
    config.connection = previous
    emit_audit_event(
        workspace_id=None,
        event_type="hf.connection.updated",
        actor=actor,
        details={"scope": "platform", "fields": sorted(values)},
        db=db,
    )
    db.commit()
    return {
        "endpoint": endpoint,
        "token_set": bool(previous.get("token_encrypted")),
        "source": "platform",
    }


resolve_connection = Connection.resolve


def public_platform_config(db) -> dict:
    config = get_platform_config(db)
    connection = (config.connection or {}) if config else {}
    return {
        "connection": {
            "endpoint": connection.get("endpoint", DEFAULT_ENDPOINT),
            "token_set": bool(connection.get("token_encrypted")),
            "source": "platform",
        },
        "policy": (config.policy or {}) if config else {},
        "limits": (config.limits or {}) if config else {},
    }


def resolve_for_workspace(workspace=None) -> Connection:
    """Resolve from the request's session when available, otherwise a short read."""
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import object_session
    from sqlalchemy.orm.exc import UnmappedInstanceError

    from app.db.base import SessionLocal

    try:
        db = object_session(workspace) if workspace is not None else None
    except UnmappedInstanceError:
        db = None
    try:
        if db is not None:
            return Connection.resolve(db, workspace)
        with SessionLocal() as session:
            return Connection.resolve(session, workspace)
    except SQLAlchemyError:
        raise HFError(
            "HF_CONFIG_UNAVAILABLE", "The Hub connection configuration is unavailable.", 503
        ) from None
