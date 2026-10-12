"""Historical import path of ``app.services.rag.index`` (ADR 0004, phase 3).

Attributes resolve on the real package; each submodule left here is an
alias of its new location.
"""

import app.services.rag.index as _package


def __getattr__(name):
    return getattr(_package, name)
