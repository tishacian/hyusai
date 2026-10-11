"""Generic secret registry. See ``registry`` for the public API and references."""

from app.services.secrets.backends.base import SecretBackend, get_backend, register_backend
from app.services.secrets.registry import (
    SecretConsumer,
    SecretRef,
    create,
    destroy,
    disable,
    get_metadata,
    list_metadata,
    parse_ref,
    ref_for,
    resolve,
    rotate,
)
from app.services.secrets.values import SecretRegistryError, SecretValue

__all__ = [
    "SecretBackend",
    "SecretConsumer",
    "SecretRef",
    "SecretRegistryError",
    "SecretValue",
    "create",
    "destroy",
    "disable",
    "get_backend",
    "get_metadata",
    "list_metadata",
    "parse_ref",
    "ref_for",
    "register_backend",
    "resolve",
    "rotate",
]
