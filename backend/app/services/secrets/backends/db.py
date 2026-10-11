"""Fernet-in-database backend (default).

The Fernet key is derived with HKDF-SHA256 (salt ``secret_registry:v1``) from
``SECRET_REGISTRY_FERNET_KEY``, or ``CONNECTOR_SECRETS_FERNET_KEY`` when the
former is unset. The derivation binds nothing per secret, but each ciphertext
is a fresh Fernet token. With no key configured every operation fails closed
with ``SECRET_KEY_NOT_CONFIGURED``: there is no plaintext dev envelope.
"""

from __future__ import annotations

import base64
import os

from app.core.config import settings
from app.core.logging import get_logger
from app.models.secret import Secret, SecretVersion
from app.services.secrets.backends.base import StoredVersion
from app.services.secrets.values import SecretRegistryError, SecretValue

logger = get_logger(__name__)

ENV_MASTER_KEY = "SECRET_REGISTRY_FERNET_KEY"
ENV_MASTER_KEY_FALLBACK = "CONNECTOR_SECRETS_FERNET_KEY"
HKDF_SALT = b"secret_registry:v1"
HKDF_INFO = b"secret_registry"


def _master_key() -> str:
    return (
        os.environ.get(ENV_MASTER_KEY)
        or settings.secret_registry_fernet_key
        or os.environ.get(ENV_MASTER_KEY_FALLBACK)
        or ""
    ).strip()


def _fernet():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    raw = _master_key()
    if not raw:
        raise SecretRegistryError("SECRET_KEY_NOT_CONFIGURED", f"{ENV_MASTER_KEY} is not set")
    try:
        master = base64.urlsafe_b64decode(raw)
    except Exception as exc:  # noqa: BLE001
        raise SecretRegistryError("SECRET_KEY_NOT_CONFIGURED", "master key is not base64") from exc
    if len(master) < 32:
        raise SecretRegistryError("SECRET_KEY_NOT_CONFIGURED", "master key is too short")
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=HKDF_SALT, info=HKDF_INFO).derive(
        master
    )
    return Fernet(base64.urlsafe_b64encode(derived))


class DbSecretBackend:
    name = "db"

    def put(self, secret: Secret, version: int, value: SecretValue) -> StoredVersion:
        token = _fernet().encrypt(value.reveal().encode("utf-8"))
        return StoredVersion(ciphertext=token.decode("ascii"))

    def get(self, secret: Secret, version: SecretVersion) -> SecretValue:
        from cryptography.fernet import InvalidToken

        if not version.ciphertext:
            raise SecretRegistryError("SECRET_VERSION_DESTROYED", f"version {version.version}")
        try:
            clear = _fernet().decrypt(version.ciphertext.encode("ascii"))
        except InvalidToken as exc:
            logger.warning("secret_registry.decrypt_failed", secret_id=secret.id)
            raise SecretRegistryError(
                "SECRET_KEY_NOT_CONFIGURED", "ciphertext does not match the configured key"
            ) from exc
        return SecretValue(clear.decode("utf-8"))

    def destroy(self, secret: Secret, version: SecretVersion) -> None:
        version.ciphertext = None

    def health(self) -> dict:
        try:
            _fernet()
        except SecretRegistryError as exc:
            return {"ok": False, "backend": self.name, "error": exc.code}
        return {"ok": True, "backend": self.name}
