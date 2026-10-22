"""RunFollowUp: one derived follow-up state for every Run projection.

The stored ``Run.status`` keeps its engine semantics (an evaluation that
reached its human boundary is ``cancelled`` so nothing can approve it). Every
surface that shows a Run — detail, lists, Flow observation, quality — reads
this projection instead of re-interpreting ``status`` and ``error`` on its own,
so a planned stop at a review boundary is never presented as a failure.

Shape (additive, stable):
    {
        "native_status": <Run.status>,
        "business_state": <one of BUSINESS_STATES>,
        "cause": None | {"code": str, "boundary"?: str, "node_id"?: str,
                         "decision_id"?: str},
        "attempt": None | {"index": int | None, "previous_run_id": str | None},
    }

``attempt`` links a replay or an evaluation retry to the Run it repeats, so a
new attempt is shown next to the earlier one instead of replacing it.
"""

from __future__ import annotations

from typing import Any, Optional

EVALUATION_STOPPED_AT_HUMAN_GATE = "EVALUATION_STOPPED_AT_HUMAN_GATE"

BUSINESS_STATES = (
    "in_progress",
    "awaiting_human_decision",
    "paused_for_debug",
    "stopped_at_review_boundary",
    "completed",
    "failed",
    "cancelled",
    "unknown",
)

_IN_PROGRESS = {"pending", "queued", "running", "waiting_subflows"}


def _last_checkpoint(run: Any, kind: str) -> Optional[dict[str, Any]]:
    for checkpoint in reversed(list(getattr(run, "checkpoints", None) or [])):
        if isinstance(checkpoint, dict) and checkpoint.get("kind") == kind:
            return checkpoint
    return None


def _text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _cause(code: str, checkpoint: Optional[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    cause: dict[str, Any] = {"code": code}
    for key, value in extra.items():
        if value is not None:
            cause[key] = value
    if checkpoint:
        for key in ("node_id", "decision_id"):
            value = _text(checkpoint.get(key))
            if value:
                cause[key] = value
    return cause


def run_follow_up(run: Any, *, payload_visible: bool = True) -> dict[str, Any]:
    """Project a Run onto its follow-up state.

    ``payload_visible`` mirrors the Run serializer: when the caller may not see
    the Run payload, the business state stays exact but the cause only carries
    its code, never node or decision identifiers.
    """
    status = _text(getattr(run, "status", None)) or "unknown"
    error = _text(getattr(run, "error", None))

    business_state = "unknown"
    cause: Optional[dict[str, Any]] = None

    boundary = _last_checkpoint(run, "evaluation_boundary")
    if status == "cancelled" and (boundary or error == EVALUATION_STOPPED_AT_HUMAN_GATE):
        business_state = "stopped_at_review_boundary"
        boundary_kind = _text((boundary or {}).get("boundary")) or "human_gate"
        cause = _cause("evaluation_stopped_at_review_boundary", boundary, boundary=boundary_kind)
    elif status == "hitl_pending":
        business_state = "awaiting_human_decision"
        cause = _cause("human_decision_required", _last_checkpoint(run, "hitl_pause"))
    elif status == "debug_pending":
        business_state = "paused_for_debug"
        cause = _cause("debug_breakpoint", _last_checkpoint(run, "debug_pause"))
    elif status in _IN_PROGRESS:
        business_state = "in_progress"
    elif status == "completed":
        business_state = "completed"
    elif status == "failed":
        business_state = "failed"
        cause = {"code": "execution_failed"}
    elif status == "cancelled":
        business_state = "cancelled"

    if cause and not payload_visible:
        cause = {"code": cause["code"]}
    return {
        "native_status": status,
        "business_state": business_state,
        "cause": cause,
        "attempt": _attempt(run) if payload_visible else None,
    }


def _attempt(run: Any) -> Optional[dict[str, Any]]:
    binding = getattr(run, "evaluation_binding", None)
    index = binding.get("attempt_index") if isinstance(binding, dict) else None
    index = index if type(index) is int and index > 0 else None
    previous = _text(getattr(run, "parent_run_id", None))
    if index is None and previous is None:
        return None
    return {"index": index, "previous_run_id": previous}
