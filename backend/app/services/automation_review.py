"""Result, reservation, reread correction, comparison. The system stays the object."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.automation_edit import AutomationEditRefusal, read_draft


class AutomationReviewRefusal(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _text(note: str) -> str:
    text = note.strip()
    if not text:
        raise AutomationReviewRefusal("empty_note", "A reservation needs a note")
    if len(text) > 500:
        raise AutomationReviewRefusal("note_too_long", "The reservation note is too long")
    return text


def reserve(system_id: str, run: Mapping[str, Any], note: str) -> dict[str, Any]:
    """Attach a note to this result. Another automation's result is refused."""

    if run.get("system_id") != system_id or not run.get("id"):
        raise AutomationReviewRefusal(
            "object_lost",
            "The result does not belong to this automation",
        )
    return {
        "system_id": system_id,
        "run_id": run["id"],
        "note": _text(note),
        "status": "reserved",
        "draft_hash": None,
        "correction_hash": None,
        "later_run_id": None,
    }


def reread(reservation: Mapping[str, Any], flow: Mapping[str, Any] | None) -> dict[str, Any]:
    """Read the draft again. The reservation keeps its system and its result."""

    seen = read_draft(flow if isinstance(flow, Mapping) else {})
    if not reservation.get("system_id") or not reservation.get("run_id"):
        raise AutomationReviewRefusal("object_lost", "The reservation has no automation")
    return {
        "system_id": reservation["system_id"],
        "run_id": reservation["run_id"],
        "note": reservation.get("note"),
        "status": "reread",
        "draft_hash": seen["hash"],
        "correction_hash": None,
        "later_run_id": None,
        "nodes": seen["nodes"],
    }


def confirm_correction(
    reservation: Mapping[str, Any],
    flow: Mapping[str, Any] | None,
    expected_hash: str,
) -> dict[str, Any]:
    """Accept the correction only against the draft hash just read."""

    if reservation.get("draft_hash") != expected_hash or not expected_hash:
        raise AutomationReviewRefusal(
            "stale_reread",
            "Read the draft again before confirming the correction",
        )
    try:
        seen = read_draft(flow if isinstance(flow, Mapping) else {})
    except AutomationEditRefusal:
        raise
    if seen["hash"] != expected_hash:
        raise AutomationReviewRefusal(
            "stale_reread",
            "The draft changed after it was read; read it again",
        )
    if seen["hash"] != reservation.get("draft_hash"):
        raise AutomationReviewRefusal(
            "read_back_mismatch",
            "The reread does not match the draft just read",
        )
    return {
        "system_id": reservation["system_id"],
        "run_id": reservation["run_id"],
        "note": reservation.get("note"),
        "status": "corrected",
        "draft_hash": seen["hash"],
        "correction_hash": seen["hash"],
        "later_run_id": None,
        "nodes": seen["nodes"],
    }


def compare(reservation: Mapping[str, Any], later: Mapping[str, Any]) -> dict[str, Any]:
    """Two results of the same automation. A different automation is refused."""

    if not reservation.get("correction_hash"):
        raise AutomationReviewRefusal(
            "not_corrected",
            "Confirm the reread correction before comparing",
        )
    if later.get("system_id") != reservation.get("system_id") or not later.get("id"):
        raise AutomationReviewRefusal(
            "object_lost",
            "The later result does not belong to this automation",
        )
    if later["id"] == reservation.get("run_id"):
        raise AutomationReviewRefusal(
            "same_result",
            "Choose a later result of the same automation",
        )
    return {
        "system_id": reservation["system_id"],
        "same_object": True,
        "run_id": reservation["run_id"],
        "later_run_id": later["id"],
        "later_status": later.get("status"),
        "note": reservation.get("note"),
    }
