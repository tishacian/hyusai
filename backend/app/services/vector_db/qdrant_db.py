"""Historical import path of ``app.services.rag.index.qdrant_db`` (ADR 0004, phase 3).

Aliased in ``sys.modules`` so imports, string references and patches made
through this path reach the real module.
"""

import sys

from app.services.rag.index import qdrant_db as _module

sys.modules[__name__] = _module
