"""Chat/completion endpoints.

Every successful chat turn persists a canonical :class:`Run` so the
auto-eval loop (``schedule_eval → evaluate_run_async``) fires on the
reply. See ``docs/vague-e-plan.md`` 2026-04-25 journal for the product
decision: chat is not a second-class surface, its traffic is the main
driver of Impact + quality metrics, so it must participate in the
same Run ledger as explicit ``/runs/launch`` triggers.
"""

# Importing the route modules registers their endpoints on ``common.router``,
# in the order the single module used to declare them.
from app.api.v1.endpoints.chat import (  # noqa: F401
    agentic,
    common,
    completion,
    retrieval,
    sessions,
    stream,
)

_MODULES = (common, sessions, retrieval, agentic, completion, stream)


def __getattr__(name):
    # Resolved on every access: readers of the package see a patch made on the
    # submodule that defines a name. The submodules bind each other's names at
    # import, so a patch meant for them targets the submodule that uses it.
    for module in _MODULES:
        if name in vars(module):
            return vars(module)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
