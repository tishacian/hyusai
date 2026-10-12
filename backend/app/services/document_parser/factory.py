"""Historical import path of ``app.services.rag.ingest.parser.factory`` (ADR 0004, phase 3).

Aliased in ``sys.modules`` so imports, string references and patches made
through this path reach the real module.
"""

import sys

from app.services.rag.ingest.parser import factory as _module

sys.modules[__name__] = _module
