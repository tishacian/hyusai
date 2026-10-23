"""Record identity of a Work action: which record a Run started from it treats.

The released binding may declare it (``record_identity`` in the release
snapshot). A specialised business reader may also supply it from its own
active configuration, through a provider registered here, so an app gains its
attempt history without being republished. The core never names a business
domain; providers do.

A reader ships its provider as ``app/services/<reader>/record_identity.py``
exposing ``record_identity_provider``. Providers are loaded on first
resolution, so the API, workers and offline scripts see the same ones.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from app.services.experience.bindings import BindingError, validate_record_identity

# (workspace, experience_slug, binding_key) -> {"namespace", "input_field"} | None
RecordIdentityProvider = Callable[[Any, str, str], Optional[Mapping[str, Any]]]

_PROVIDERS: list[RecordIdentityProvider] = []
_PROVIDER_MODULE = "record_identity"
_loaded = False


def register_record_identity_provider(provider: RecordIdentityProvider) -> None:
    """Register a business reader's provider once (idempotent)."""
    if provider not in _PROVIDERS:
        _PROVIDERS.append(provider)


def load_record_identity_providers() -> None:
    """Register the provider of every business reader that ships one (once).

    Readers are found on disk, so a reader without a provider is never
    imported. A provider module that fails to import surfaces its error.
    """
    global _loaded
    if _loaded:
        return
    import app.services as services

    own_package = __name__.rsplit(".", 2)[-2]
    for root in services.__path__:
        for reader in sorted(Path(root).iterdir()):
            if reader.name == own_package or not (reader / f"{_PROVIDER_MODULE}.py").is_file():
                continue
            module = importlib.import_module(f"{services.__name__}.{reader.name}.{_PROVIDER_MODULE}")
            provider = getattr(module, "record_identity_provider", None)
            if callable(provider):
                register_record_identity_provider(provider)
    _loaded = True


def resolve_record_identity(
    snapshot_item: Optional[Mapping[str, Any]],
    *,
    workspace: Any,
    experience_slug: Optional[str],
) -> Optional[dict[str, str]]:
    """The released contract when declared, otherwise a provider's, validated."""
    if not isinstance(snapshot_item, Mapping):
        return None
    try:
        declared = validate_record_identity(snapshot_item.get("record_identity"))
    except BindingError:
        declared = None
    if declared:
        return declared
    binding_key = snapshot_item.get("binding_key")
    if not experience_slug or not isinstance(binding_key, str):
        return None
    load_record_identity_providers()
    for provider in list(_PROVIDERS):
        try:
            candidate = provider(workspace, experience_slug, binding_key)
            identity = validate_record_identity(candidate) if candidate else None
        except (BindingError, ValueError):
            identity = None
        if identity:
            return identity
    return None
