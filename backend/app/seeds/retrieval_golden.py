"""The golden retrieval batch the evaluation scripts read by default.

It is the Andritz SPL dense set, shipped under ``app/resources``; a script or a
test names another batch explicitly (the showcase notices batch is opt-in).
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_GOLDEN_BATCH = (
    Path(__file__).resolve().parents[1] / "resources" / "retrieval_golden" / "andritz_spl_dense.json"
)
