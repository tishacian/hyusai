"""Transverse Agentium action registry.

Exports are resolved lazily so dependency-free contracts such as
``actions.contracts`` can be imported by the Workspace App manifest compiler
without eagerly constructing the whole action/IAM/runtime graph.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "ActionManifest",
    "ActionResolution",
    "effective_action_manifests",
    "execute_action",
    "handle_registry_chat_action",
    "handle_transverse_chat_action",
    "resolve_action",
]

_REGISTRY_EXPORTS = frozenset(
    {
        "ActionManifest",
        "ActionResolution",
        "effective_action_manifests",
        "execute_action",
        "handle_transverse_chat_action",
        "resolve_action",
    }
)


def __getattr__(name: str) -> Any:
    if name in _REGISTRY_EXPORTS:
        module = import_module("app.services.actions.registry")
    elif name == "handle_registry_chat_action":
        module = import_module("app.services.actions.executor")
    else:
        raise AttributeError(name)
    value = getattr(module, name)
    globals()[name] = value
    return value
