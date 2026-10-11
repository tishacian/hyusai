"""Storage backend contract and the name -> backend registry.

A backend stores one immutable version of one secret. The registry owns the
rows; backends only turn a ``SecretValue`` into a ``StoredVersion`` (what is
persisted on ``secret_versions``) and back.

    class SecretBackend(Protocol):
        name: str
        def put(self, secret: Secret, version: int, value: SecretValue) -> StoredVersion
        def get(self, secret: Secret, version: SecretVersion) -> SecretValue
        def destroy(self, secret: Secret, version: SecretVersion) -> None
        def health(self) -> dict  # {"ok": bool, ...}, never raises

``put``/``get``/``destroy`` raise ``SecretRegistryError`` (typically
``SECRET_BACKEND_UNAVAILABLE`` or ``SECRET_KEY_NOT_CONFIGURED``); they never
fall back to another backend. ``register_backend(name, factory)`` lets a
backend module plug itself in; ``get_backend(name)`` returns a cached
instance or raises ``SECRET_BACKEND_UNAVAILABLE``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.models.secret import Secret, SecretVersion
from app.services.secrets.values import SecretRegistryError, SecretValue


@dataclass(frozen=True)
class StoredVersion:
    ciphertext: str | None = None
    backend_ref: str | None = None


@runtime_checkable
class SecretBackend(Protocol):
    name: str

    def put(self, secret: Secret, version: int, value: SecretValue) -> StoredVersion:
        ...

    def get(self, secret: Secret, version: SecretVersion) -> SecretValue:
        ...

    def destroy(self, secret: Secret, version: SecretVersion) -> None:
        ...

    def health(self) -> dict:
        ...


_FACTORIES: dict[str, Callable[[], SecretBackend]] = {}
_INSTANCES: dict[str, SecretBackend] = {}


def register_backend(name: str, factory: Callable[[], SecretBackend]) -> None:
    _FACTORIES[name] = factory
    _INSTANCES.pop(name, None)


def get_backend(name: str) -> SecretBackend:
    _ensure_builtin()
    if name not in _INSTANCES:
        factory = _FACTORIES.get(name)
        if factory is None:
            raise SecretRegistryError("SECRET_BACKEND_UNAVAILABLE", f"unknown backend {name!r}")
        _INSTANCES[name] = factory()
    return _INSTANCES[name]


def reset_backends() -> None:
    """Drop cached instances (tests, settings reload)."""
    _INSTANCES.clear()


def _ensure_builtin() -> None:
    if "db" not in _FACTORIES:
        from app.services.secrets.backends.db import DbSecretBackend

        _FACTORIES["db"] = DbSecretBackend
    if "openbao" not in _FACTORIES:
        from app.services.secrets.backends.openbao import OpenBaoSecretBackend

        _FACTORIES["openbao"] = OpenBaoSecretBackend
