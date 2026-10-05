"""Which Systems of a workspace are its Intelligence (News Lab) watches.

A watch is marked by ``flow_definition.template_id``: the neutral
``intelligence`` marker for every System created from now on, and the legacy
template the mission-room seed stamped before the marker existed, which
persisted Systems still carry. Nothing else qualifies: a name containing
"intelligence" or a ``variant`` alone does not turn an unrelated System into a
watch on the Intelligence entry.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

INTELLIGENCE_TEMPLATE_ID = "intelligence"
# Stamped by the mission-room seed (``<prefix>-<variant>``) before the neutral
# marker existed. Persisted Systems keep it; it stays accepted and, where both
# exist, preferred, so a workspace that already had one keeps the same System.
LEGACY_INTELLIGENCE_TEMPLATE_IDS: tuple[str, ...] = ("sentinel-ci-intelligence",)
INTELLIGENCE_TEMPLATE_IDS: tuple[str, ...] = (
    *LEGACY_INTELLIGENCE_TEMPLATE_IDS,
    INTELLIGENCE_TEMPLATE_ID,
)


def template_id_of(system: Any) -> str:
    flow = getattr(system, "flow_definition", None)
    if not isinstance(flow, dict):
        return ""
    return str(flow.get("template_id") or "")


def is_intelligence_template(template_id: Optional[str]) -> bool:
    return str(template_id or "") in INTELLIGENCE_TEMPLATE_IDS


def is_intelligence_system(system: Any) -> bool:
    return is_intelligence_template(template_id_of(system))


def intelligence_systems(systems: Iterable[Any]) -> list[Any]:
    """The marked watches, legacy template first, in the given order otherwise."""

    rows = [system for system in systems if is_intelligence_system(system)]
    return sorted(rows, key=lambda system: INTELLIGENCE_TEMPLATE_IDS.index(template_id_of(system)))


def preferred_intelligence_system(systems: Iterable[Any]) -> Optional[Any]:
    rows = intelligence_systems(systems)
    return rows[0] if rows else None
