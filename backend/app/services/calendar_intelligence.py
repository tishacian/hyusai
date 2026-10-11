"""Deterministic calendar heuristics for operational workspaces."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Optional

from app.models.action_plan import WorkspaceActionItem
from app.models.calendar import WorkspaceCalendarEvent


WORKDAY_START = time(8, 0)
WORKDAY_END = time(18, 30)


def analyze_calendar(
    events: Iterable[WorkspaceCalendarEvent],
    *,
    action_items: Optional[Iterable[WorkspaceActionItem]] = None,
    day: Optional[date] = None,
) -> dict[str, Any]:
    """Return conflict, free-slot and decision-pressure heuristics.

    The goal is not to pretend to be a calendar AI. It is to produce stable,
    explainable signals the executive assistant can cite: overlaps, tight transitions, missing
    decision slots and clear move recommendations.
    """

    active = sorted([event for event in events if event.status != "cancelled"], key=lambda item: item.start_at)
    day = day or (active[0].start_at.date() if active else datetime.utcnow().date())
    actions = sorted(
        [item for item in (action_items or []) if item.status not in {"completed", "cancelled"}],
        key=lambda item: (item.due_at is None, item.due_at or datetime.max),
    )
    free_slots = _free_slots(active, day, min_minutes=30)
    available_windows = _free_slots(active, day, min_minutes=15)
    conflicts = _overlap_conflicts(active) + _tight_transitions(active) + _decision_conflicts(active, actions)
    recommended_moves = _recommended_moves(active, conflicts, free_slots)
    decision_deadlines = _decision_deadlines(actions, available_windows)
    pressure = min(100, sum(_severity_points(item["severity"]) for item in conflicts) + len(decision_deadlines) * 8)
    return {
        "conflicts": conflicts,
        "free_slots": free_slots[:4],
        "available_windows": available_windows[:6],
        "recommended_moves": recommended_moves[:4],
        "decision_deadlines": decision_deadlines[:5],
        "conflict_score": pressure,
        "status": "attention_required" if pressure >= 55 else ("watch" if pressure >= 25 else "clear"),
    }


def _overlap_conflicts(events: list[WorkspaceCalendarEvent]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for idx, current in enumerate(events):
        for other in events[idx + 1 :]:
            if other.start_at >= current.end_at:
                break
            shared = sorted(set(current.participants or []) & set(other.participants or []))
            severity = "critical" if "critical" in {current.priority, other.priority} else "high"
            conflicts.append(
                {
                    "type": "participant_overlap" if shared else "overlap",
                    "severity": severity,
                    "event_ids": [current.id, other.id],
                    "label": f"{current.title} / {other.title}",
                    "reason": "Chevauchement horaire sur des sequences ministerielles.",
                    "participants": shared,
                    "suggestion": "Deplacer l'evenement le moins prioritaire sur un creneau disponible.",
                }
            )
    return conflicts


def _tight_transitions(events: list[WorkspaceCalendarEvent]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for current, nxt in zip(events, events[1:]):
        if current.end_at > nxt.start_at:
            continue
        gap = nxt.start_at - current.end_at
        if timedelta(0) <= gap < timedelta(minutes=15) and {current.priority, nxt.priority} & {"critical", "high"}:
            conflicts.append(
                {
                    "type": "tight_transition",
                    "severity": "medium",
                    "event_ids": [current.id, nxt.id],
                    "label": f"{current.title} -> {nxt.title}",
                    "reason": f"Transition de {int(gap.total_seconds() // 60)} min entre deux sequences sensibles.",
                    "suggestion": "Prevoir un tampon cabinet ou basculer la preparation en amont.",
                }
            )
    return conflicts


def _decision_conflicts(events: list[WorkspaceCalendarEvent], actions: list[WorkspaceActionItem]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for event in events:
        if event.priority not in {"critical", "high"}:
            continue
        matching = [
            item
            for item in actions
            if item.calendar_event_id == event.id
            or _mentions(item.title, event.title)
            or _mentions(item.target_label, event.title)
        ]
        if not matching:
            conflicts.append(
                {
                    "type": "critical_without_action",
                    "severity": "medium",
                    "event_ids": [event.id],
                    "label": event.title,
                    "reason": "Sequence prioritaire sans action cabinet explicitement rattachee.",
                    "suggestion": "Creer une action de preparation ou d'arbitrage avant la reunion.",
                }
            )
    for action in actions:
        if not action.due_at or action.priority not in {"critical", "high"}:
            continue
        related = next((event for event in events if event.start_at <= action.due_at <= event.end_at), None)
        if related:
            conflicts.append(
                {
                    "type": "deadline_inside_meeting",
                    "severity": "high" if action.priority == "critical" else "medium",
                    "event_ids": [related.id],
                    "action_id": action.id,
                    "label": action.title,
                    "reason": "Echeance d'action pendant une reunion deja planifiee.",
                    "suggestion": "Avancer l'echeance sur un creneau libre avant la sequence.",
                }
            )
    return conflicts


def _recommended_moves(
    events: list[WorkspaceCalendarEvent],
    conflicts: list[dict[str, Any]],
    slots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    moves: list[dict[str, Any]] = []
    by_id = {event.id: event for event in events}
    for conflict in conflicts:
        ids = conflict.get("event_ids") or []
        candidates = [by_id[event_id] for event_id in ids if event_id in by_id]
        if not candidates:
            continue
        target = sorted(candidates, key=lambda event: _priority_rank(event.priority))[0]
        duration = max(15, int((target.end_at - target.start_at).total_seconds() // 60))
        slot = next((slot for slot in slots if slot.get("duration_min", 0) >= duration), None)
        if not slot:
            continue
        moves.append(
            {
                "event_id": target.id,
                "title": target.title,
                "from": target.start_at.strftime("%H:%M"),
                "to": f"{slot['start']}-{slot['end']}",
                "duration_min": duration,
                "why": conflict["suggestion"],
                "severity": conflict["severity"],
            }
        )
    return moves


def _decision_deadlines(actions: list[WorkspaceActionItem], windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deadlines: list[dict[str, Any]] = []
    for action in actions:
        if not action.due_at:
            continue
        window = next((slot for slot in windows if slot["start_dt"] <= action.due_at), None)
        deadlines.append(
            {
                "action_id": action.id,
                "title": action.title,
                "priority": action.priority,
                "due_at": action.due_at.isoformat(),
                "due_label": action.due_at.strftime("%H:%M"),
                "suggested_window": _clean_slot(window) if window else None,
            }
        )
    return deadlines


def _free_slots(events: list[WorkspaceCalendarEvent], day: date, *, min_minutes: int) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    cursor = datetime.combine(day, WORKDAY_START)
    end_day = datetime.combine(day, WORKDAY_END)
    for event in sorted(events, key=lambda item: item.start_at):
        if event.end_at <= cursor:
            continue
        if event.start_at > cursor and (event.start_at - cursor) >= timedelta(minutes=min_minutes):
            slots.append(_slot(cursor, event.start_at))
        cursor = max(cursor, event.end_at)
    if cursor < end_day and (end_day - cursor) >= timedelta(minutes=min_minutes):
        slots.append(_slot(cursor, end_day))
    return slots


def _slot(start: datetime, end: datetime) -> dict[str, Any]:
    return {
        "start": start.strftime("%H:%M"),
        "end": end.strftime("%H:%M"),
        "start_dt": start,
        "end_dt": end,
        "duration_min": int((end - start).total_seconds() // 60),
        "label": f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}",
    }


def _clean_slot(slot: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not slot:
        return None
    return {key: value for key, value in slot.items() if key not in {"start_dt", "end_dt"}}


def _severity_points(severity: str) -> int:
    return {"critical": 35, "high": 25, "medium": 12, "low": 5}.get(severity, 8)


def _priority_rank(priority: str) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(priority, 1)


def _mentions(left: str, right: str) -> bool:
    l_words = {word for word in (left or "").lower().replace("-", " ").split() if len(word) > 4}
    r_words = {word for word in (right or "").lower().replace("-", " ").split() if len(word) > 4}
    return bool(l_words & r_words)
