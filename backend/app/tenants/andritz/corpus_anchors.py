"""Named ANDRITZ machines, systems and brands that anchor a question in its corpus.

The RAG planner over-rejects valid questions as out of scope, notably in German
("Wozu dient das Qualiscan QMS-12 System…"). A question that names one of these
is never rejected (fix 2026-06-26). The names are ANDRITZ's nomenclature: in any
other workspace "KSB" or "Wilo" must not override the planner (ADR 0003, D6).
"""

from __future__ import annotations

import re

KNOWN_ENTITY_RE = re.compile(
    r"\b(qualiscan|qms[\s-]?\d+|uraca|etachrom|sinamics|simotics|jetlace|servo\s*x|"
    r"pollrich|continental\s*gvjs|wilo|ksb|geotex|excelle|starter|kd724)\b",
    re.IGNORECASE,
)
