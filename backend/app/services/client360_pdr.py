"""Historical import path of ``app.tenants.andritz.client360.pdr`` (ADR 0004, phase 3).

Aliased in ``sys.modules`` so imports, string references and patches made
through this path reach the real module.
"""

import sys

from app.tenants.andritz.client360 import pdr as _module

sys.modules[__name__] = _module
