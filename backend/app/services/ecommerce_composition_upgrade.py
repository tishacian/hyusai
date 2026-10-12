"""Historical import path of ``app.services.ecommerce.composition_upgrade`` (ADR 0004, phase 3).

Aliased in ``sys.modules`` so imports, string references and patches made
through this path reach the real module.
"""

import sys

from app.services.ecommerce import composition_upgrade as _module

sys.modules[__name__] = _module
