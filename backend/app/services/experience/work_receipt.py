"""L33 — one-line receipts for the Work home, read only from what a Run recorded.

Each field is either measured on the Run (checkpoints, invocations, output) or
``None``. The home omits a ``None`` field; it never estimates one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping, Optional

_SEALED_WRITE_SKILLS = frozenset({"sap_create_po_v1"})
_PASSAGE_SKILLS = frozenset({"semantic_search_v1"})


def _checkpoint_time(value: Any) -> Optional[datetime]:
    """Walker checkpoints stamp ``t`` as naive UTC ISO; anything else is unknown."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1]
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _checkpoints(run: Any) -> list[Mapping[str, Any]]:
    return [item for item in list(getattr(run, "checkpoints", None) or []) if isinstance(item, Mapping)]


def steps_done(run: Any, invocations: Iterable[Any] = ()) -> Optional[int]:
    """Distinct steps the walker closed; else the skill calls recorded; else unknown."""
    ended = {
        str(item.get("node_id"))
        for item in _checkpoints(run)
        if item.get("kind") == "node_end" and item.get("node_id")
    }
    if ended:
        return len(ended)
    count = sum(1 for _ in invocations)
    return count or None


def agent_work_ms(run: Any) -> Optional[int]:
    """Agent working time: first → last stamped checkpoint, human waits excluded.

    A wait is a ``hitl_pause`` up to the ``hitl_resume`` that follows it. Without
    stamps, the Run's own duration counts only when no human wait happened.
    """
    rows = [(item, _checkpoint_time(item.get("t"))) for item in _checkpoints(run)]
    stamped = [(item, at) for item, at in rows if at is not None]
    waited = any(item.get("kind") in {"hitl_pause", "hitl_resume"} for item, _ in rows)
    if len(stamped) >= 2:
        total = (stamped[-1][1] - stamped[0][1]).total_seconds() * 1000
        paused_at: Optional[datetime] = None
        for item, at in stamped:
            if item.get("kind") == "hitl_pause":
                paused_at = at
            elif item.get("kind") == "hitl_resume" and paused_at is not None:
                total -= max(0.0, (at - paused_at).total_seconds() * 1000)
                paused_at = None
        if paused_at is not None:
            total -= max(0.0, (stamped[-1][1] - paused_at).total_seconds() * 1000)
        return int(total) if total > 0 else None
    duration = getattr(run, "duration_ms", None)
    if not waited and isinstance(duration, (int, float)) and duration > 0:
        return int(duration)
    return None


def _output(invocation: Any) -> Mapping[str, Any]:
    output = getattr(invocation, "output_ref", None)
    return output if isinstance(output, Mapping) else {}


def write_outcome(invocations: Iterable[Any]) -> Optional[str]:
    """``sealed`` when the write was held by the workspace seal, ``done`` when called."""
    outcome: Optional[str] = None
    for invocation in invocations:
        if getattr(invocation, "skill_slug", None) not in _SEALED_WRITE_SKILLS:
            continue
        output = _output(invocation)
        if output.get("sealed") is True:
            outcome = "sealed"
        elif output.get("called") is True and outcome is None:
            outcome = "done"
    return outcome


def passages_read(invocations: Iterable[Any]) -> Optional[int]:
    total: Optional[int] = None
    for invocation in invocations:
        if getattr(invocation, "skill_slug", None) not in _PASSAGE_SKILLS:
            continue
        results = _output(invocation).get("results")
        if isinstance(results, list):
            total = (total or 0) + len(results)
    return total


def passages_cited(run: Any) -> Optional[int]:
    output = getattr(run, "output_ref", None)
    if not isinstance(output, Mapping):
        return None
    citations = output.get("citations")
    return len(citations) if isinstance(citations, list) else None


def run_receipt(run: Any, invocations: Iterable[Any] = ()) -> dict[str, Any]:
    calls = list(invocations)
    return {
        "steps": steps_done(run, calls),
        "agent_ms": agent_work_ms(run),
        "write": write_outcome(calls),
        "passages_read": passages_read(calls),
        "passages_cited": passages_cited(run),
    }
