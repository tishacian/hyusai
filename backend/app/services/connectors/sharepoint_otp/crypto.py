"""At-rest encryption for SharePoint connector secrets (storage_state, token
caches). One symmetric master key, derived per-tenant via HKDF so that
compromising one tenant's persisted state does not automatically compromise
another tenant's. The master key is expected in the environment variable
``SHAREPOINT_CONNECTOR_FERNET_KEY`` (a base64 urlsafe 32-byte Fernet key).

If the env var is missing, behaviour depends on the
``SHAREPOINT_CONNECTOR_REQUIRE_ENCRYPTION`` env flag:

- ``1`` / ``true``: raise ``RuntimeError`` so staging/prod refuses to start.
- anything else (dev default): fall back to plaintext storage, with a loud
  warning in the logs.

Callers should treat blobs produced here as opaque. The on-disk layout is a
JSON envelope ``{"v": 1, "tenant": "...", "ciphertext": "..."}`` so operators
can tell encrypted files apart from legacy plaintext ones.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ENV_MASTER_KEY = "SHAREPOINT_CONNECTOR_FERNET_KEY"
ENV_REQUIRE_ENCRYPTION = "SHAREPOINT_CONNECTOR_REQUIRE_ENCRYPTION"
ENVELOPE_VERSION = 1


class EncryptionNotConfigured(RuntimeError):
    """The operator required encryption but no master key is configured."""


def _require_encryption() -> bool:
    return os.environ.get(ENV_REQUIRE_ENCRYPTION, "").lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class EncryptionConfig:
    master_key: bytes | None

    @classmethod
    def from_env(cls) -> "EncryptionConfig":
        raw = os.environ.get(ENV_MASTER_KEY)
        if not raw:
            if _require_encryption():
                raise EncryptionNotConfigured(
                    f"{ENV_MASTER_KEY} is not set but "
                    f"{ENV_REQUIRE_ENCRYPTION} is enabled."
                )
            return cls(master_key=None)
        try:
            key = raw.encode("ascii")
            # Validate it is a 32-byte urlsafe b64 payload (Fernet's format).
            if len(base64.urlsafe_b64decode(key)) != 32:
                raise ValueError("expected 32 bytes after base64 decode")
        except Exception as exc:
            raise EncryptionNotConfigured(
                f"{ENV_MASTER_KEY} is not a valid urlsafe base64 Fernet key: {exc}"
            ) from exc
        return cls(master_key=key)


def _derive_tenant_fernet(master_key: bytes, tenant: str):
    """Return a :class:`cryptography.fernet.Fernet` bound to ``tenant``."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    raw_master = base64.urlsafe_b64decode(master_key)
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"sharepoint_otp:v1",
        info=f"tenant={tenant}".encode("utf-8"),
    ).derive(raw_master)
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_blob(payload: bytes, tenant: str) -> bytes:
    """Encrypt a payload for ``tenant``; returns a JSON envelope (bytes).

    When no master key is configured (dev), returns a plaintext envelope so
    the on-disk format is stable and detectable by :func:`decrypt_blob`.
    """
    cfg = EncryptionConfig.from_env()
    if cfg.master_key is None:
        logger.warning(
            "%s not set; persisting SharePoint connector state in PLAINTEXT. "
            "Set %s to a urlsafe-base64 Fernet key before going to production.",
            ENV_MASTER_KEY,
            ENV_MASTER_KEY,
        )
        envelope = {
            "v": ENVELOPE_VERSION,
            "tenant": tenant,
            "plaintext": base64.b64encode(payload).decode("ascii"),
        }
        return json.dumps(envelope).encode("utf-8")
    fernet = _derive_tenant_fernet(cfg.master_key, tenant)
    envelope = {
        "v": ENVELOPE_VERSION,
        "tenant": tenant,
        "ciphertext": fernet.encrypt(payload).decode("ascii"),
    }
    return json.dumps(envelope).encode("utf-8")


def decrypt_blob(blob: bytes, tenant: str) -> bytes:
    """Reverse of :func:`encrypt_blob`. Validates the envelope's tenant.

    Also accepts the legacy unwrapped format (a raw JSON payload) so upgrades
    do not invalidate sessions captured by previous versions of the connector.
    """
    try:
        envelope = json.loads(blob.decode("utf-8"))
    except Exception:
        # Legacy plaintext JSON: return as-is.
        return blob
    if not isinstance(envelope, dict) or "v" not in envelope:
        return blob
    stored_tenant = envelope.get("tenant")
    if stored_tenant and stored_tenant != tenant:
        raise ValueError(
            f"Encrypted blob belongs to tenant {stored_tenant!r}, not {tenant!r}"
        )
    if "plaintext" in envelope:
        return base64.b64decode(envelope["plaintext"])
    if "ciphertext" in envelope:
        cfg = EncryptionConfig.from_env()
        if cfg.master_key is None:
            raise EncryptionNotConfigured(
                f"Envelope {ENV_MASTER_KEY} required to decrypt but is not set."
            )
        fernet = _derive_tenant_fernet(cfg.master_key, tenant)
        return fernet.decrypt(envelope["ciphertext"].encode("ascii"))
    raise ValueError(f"Unknown envelope shape: keys={sorted(envelope)}")


def generate_master_key() -> str:
    """Utility to mint a fresh master key for operators."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")
