"""SENTINEL-CI demo mission-room fixtures and bootstrap helpers.

The mission room is intentionally implemented as an Agentium workspace pattern,
not as a tenant-special case. Runtime surfaces read the current workspace, while
this module provides a portable demo seed and deterministic advisory payloads.
"""

from app.services.mission_room import (  # noqa: F401
    fixtures,
    payloads,
    profile,
    provisioning,
)

_MODULES = (profile, fixtures, payloads, provisioning)


def __getattr__(name):
    # Resolved on every access: readers of the package see a patch made on the
    # submodule that defines a name. The submodules bind each other's names at
    # import, so a patch meant for them targets the submodule that uses it.
    for module in _MODULES:
        if name in vars(module):
            return vars(module)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
