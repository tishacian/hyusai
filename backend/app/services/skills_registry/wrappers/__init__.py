"""Callable wrappers for canonical Skills.

Each wrapper translates a typed canonical-skill input into a real call
against the existing OmniRAG service layer. Wrappers are intentionally
thin — they never introduce new business logic.

Runtime status (returned by `bound_slugs()`) is tri-state:
 - ``bound``     : an actual implementation module is resolvable and will be invoked.
 - ``stub``      : a placeholder that logs + returns a degraded payload (no hard-fail).
 - ``unbound``   : no wrapper declared for that slug (`resolve()` refuses it).

The check happens lazily on first use, cached in
``_RESOLVED_STATUS`` so the admin `/skills/runtime-health` endpoint is
cheap to call. Imports of the underlying services stay lazy to avoid
pulling heavy deps at registry introspection time.
"""

from app.services.skills_registry.wrappers import registry, skills

__all__ = ["bound_slugs", "ctx_secret", "registry_snapshot", "resolve", "runtime_status"]


def __getattr__(name):
    # Resolved on every access: readers of the package see a patch made on the
    # defining submodule (``skills`` for the wrappers, ``registry`` for the
    # registry and its state). The submodules bind each other's names at import,
    # so a patch meant for them targets the submodule that uses the name.
    for module in (registry, skills):
        if name in vars(module):
            return vars(module)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
