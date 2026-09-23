"""Customer adapters, selected by the stamped workspace family.

Generic code never names a customer (docs/adr/0003-generalisation-frontieres.md).
When a family needs its own wording, rules or content, the generic code asks
for a hook by name and the family's package under ``app.tenants.<family>``
provides it. A family without that hook, and every ``generic`` workspace,
gets the generic behaviour.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

from app.services.workspace_features import KNOWN_FAMILIES

_GENERIC = "generic"


def _family_module(family: str | None, module: str) -> ModuleType | None:
    family = str(family or "").strip().lower()
    if family not in KNOWN_FAMILIES or family == _GENERIC:
        return None
    qualified = f"{__name__}.{family}.{module}"
    try:
        return importlib.import_module(qualified)
    except ModuleNotFoundError as exc:
        # Only a missing adapter means "no hook"; a broken one must surface.
        if exc.name in {qualified, f"{__name__}.{family}"}:
            return None
        raise


def family_hook(family: str | None, module: str, name: str, default: Any = None) -> Any:
    """The ``name`` a family's ``module`` adapter provides, else ``default``."""

    adapter = _family_module(family, module)
    if adapter is None:
        return default
    return getattr(adapter, name, default)
