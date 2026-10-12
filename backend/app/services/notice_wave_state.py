"""Historical import path of ``app.services.notices.wave_state`` (ADR 0004, phase 3).

Aliased in ``sys.modules`` so imports, string references and patches made
through this path reach the real module.
"""

import sys

from app.services.notices import wave_state as _module

sys.modules[__name__] = _module
