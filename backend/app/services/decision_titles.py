"""Decision titles as people read them.

The engine names the human approval it pauses on with a technical prefix
("HITL approval — <step label>", see run_engine/dag.py). Stored titles are
evidence and stay as they are; readers are shown the step label alone.
"""

from __future__ import annotations

from typing import Optional

_ENGINE_PREFIXES = ("HITL approval — ",)


def display_title(title: Optional[str]) -> Optional[str]:
    if not isinstance(title, str):
        return title
    for prefix in _ENGINE_PREFIXES:
        if title.startswith(prefix) and title[len(prefix):].strip():
            return title[len(prefix):].strip()
    return title
