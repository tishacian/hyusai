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

import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.decision_titles import display_title

EVALUATION_STOPPED_AT_HUMAN_GATE = "EVALUATION_STOPPED_AT_HUMAN_GATE"

BUSINESS_STATES = (
    "in_progress",
    "awaiting_human_decision",
    "decision_expired",
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


def _decision_expired(run: Any, *, now: Optional[datetime] = None, decision: Any = None) -> bool:
    """True when the Run's last human approval expired: the same rule as
    ``run_decision_state`` reporting ``expired``, so a list and the Situation
    never disagree about one Run."""
    state = run_decision_state(run, decision=decision, now=now)
    return bool(state) and state.get("state") == "expired"


def run_follow_up(
    run: Any,
    *,
    payload_visible: bool = True,
    now: Optional[datetime] = None,
    decision: Any = None,
) -> dict[str, Any]:
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
    elif status in {"hitl_pending", "failed", "cancelled"} and _decision_expired(run, now=now, decision=decision):
        # A human approval that ran out of time is not an execution failure.
        business_state = "decision_expired"
        cause = _cause("human_decision_expired", _last_checkpoint(run, "hitl_pause"))
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



_SUBJECT_KEY = re.compile(r"(^|_)(id|ref|reference|number)$", re.IGNORECASE)


def _instant(value: Any) -> Optional[datetime]:
    """Parse an ISO instant; naive values are UTC (the engine's convention)."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def run_subject(run: Any) -> Optional[dict[str, str]]:
    """The business object a Run treats, read from its input identifiers."""
    input_ref = getattr(run, "input_ref", None)
    if not isinstance(input_ref, dict):
        return None
    for key, value in input_ref.items():
        if key.startswith("_") or not _SUBJECT_KEY.search(key):
            continue
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
            return {"field": key, "value": str(value).strip()}
    return None


def run_decision_state(
    run: Any,
    *,
    decision: Any = None,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """State of the human decision a Run asked for, computed on the server.

    ``decision`` is the Decision row of the last pause when the caller could
    load it; its deadline wins over the checkpoint copy. Returns ``None`` when
    the Run never paused for a person.
    """
    pause = _last_checkpoint(run, "hitl_pause")
    if pause is None:
        return None
    now = now or datetime.now(timezone.utc)
    decision_id = _text(pause.get("decision_id"))
    expired = next(
        (
            cp
            for cp in reversed(list(getattr(run, "checkpoints", None) or []))
            if isinstance(cp, dict)
            and cp.get("kind") == "gate_ttl_expired"
            and (not decision_id or cp.get("decision_id") == decision_id)
        ),
        None,
    )
    deadline = _instant(getattr(decision, "expires_at", None)) or _instant(pause.get("expires_at"))
    expiry_action = _text(getattr(decision, "expiry_action", None)) or _text(pause.get("expiry_action"))
    state = {
        "decision_id": decision_id,
        "title": _text(getattr(decision, "title", None)),
        "expires_at": _iso(deadline),
        "expiry_action": expiry_action,
        "expired_at": None,
        "seconds_remaining": None,
    }
    status = _text(getattr(run, "status", None))
    if expired is not None:
        state["state"] = "expired"
        state["expired_at"] = _iso(_instant(expired.get("t")))
        state["expiry_action"] = _text(expired.get("expiry_action")) or expiry_action
    elif _last_checkpoint(run, "evaluation_boundary") is not None:
        state["state"] = "closed_by_evaluation"
    elif status == "hitl_pending":
        if deadline is not None and deadline <= now:
            # The sweep has not applied the expiry yet; never present it as open.
            state["state"] = "expired"
            state["seconds_remaining"] = 0
        else:
            state["state"] = "awaiting"
            if deadline is not None:
                state["seconds_remaining"] = int((deadline - now).total_seconds())
    else:
        decision_status = _text(getattr(decision, "status", None))
        state["state"] = decision_status or "closed"
    return state


def run_work_origin(run: Any, *, record_identity: Any = None) -> Optional[dict[str, Any]]:
    """Where a Run started in Work, so a reader can return to the case.

    Read from the Run's own ingress provenance; ``record_identity`` is the
    released binding contract (when the caller loaded it) that names the
    payload field carrying the record reference.
    """
    input_ref = getattr(run, "input_ref", None)
    ingress = input_ref.get("_ingress") if isinstance(input_ref, dict) else None
    adapter = ingress.get("adapter") if isinstance(ingress, dict) else None
    if not isinstance(adapter, dict) or adapter.get("surface") != "experience":
        return None
    slug = _text(adapter.get("experience_slug"))
    page_id = _text(adapter.get("page_id"))
    if not slug or not page_id:
        return None
    record_ref = None
    if isinstance(record_identity, dict):
        field = record_identity.get("input_field")
        value = input_ref.get(field) if isinstance(field, str) else None
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
            record_ref = str(value).strip()[:200]
    return {"experience_slug": slug, "page_id": page_id, "record_ref": record_ref}


def run_follow_up_detail(
    run: Any,
    *,
    payload_visible: bool,
    decision: Any = None,
    now: Optional[datetime] = None,
    record_identity: Any = None,
) -> dict[str, Any]:
    """The follow-up read model served by GET /runs/{id}/follow-up."""
    follow_up = run_follow_up(run, payload_visible=payload_visible, now=now, decision=decision)
    decision_state = run_decision_state(run, decision=decision, now=now)
    proposal = None
    if payload_visible:
        proposal = display_title(
            (decision_state or {}).get("title")
            or _text((_last_checkpoint(run, "hitl_pause") or {}).get("prompt"))
            or _text(getattr(run, "decision", None))
        )
    if decision_state is not None and not payload_visible:
        decision_state = {**decision_state, "title": None, "decision_id": None}
    return {
        "run_id": getattr(run, "id", None),
        **follow_up,
        "subject": run_subject(run) if payload_visible else None,
        "proposal": proposal,
        "decision": decision_state,
        "work_origin": run_work_origin(run, record_identity=record_identity) if payload_visible else None,
        "payload_unavailable_reason": None if payload_visible else "evidence_unavailable",
    }
