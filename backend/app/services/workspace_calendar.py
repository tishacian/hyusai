"""Workspace calendar service used by Mission Room and the executive assistant profile."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.calendar import WorkspaceCalendarEvent
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.calendar_intelligence import analyze_calendar
from app.services.demo_time_context import resolve_demo_date, resolve_demo_time
from app.seeds.sentinel_calendar import SENTINEL_CALENDAR_ANCHOR_DATE, SENTINEL_CALENDAR_SEED  # noqa: F401


DEFAULT_TIMEZONE = "Africa/Abidjan"
DEFAULT_SOURCE_LABEL = "Agenda institutionnel"


def _actor(user: Optional[User]) -> str:
    if not user:
        return "system"
    return user.email or user.username or user.id


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _is_sentinel_seed(event: WorkspaceCalendarEvent) -> bool:
    metadata = event.meta_data or {}
    return metadata.get("seed") == "sentinel-ci" or str(metadata.get("seed_id") or "").startswith("evt-")


def _display_window(
    event: WorkspaceCalendarEvent,
    workspace: Optional[Workspace] = None,
) -> tuple[datetime, datetime, int]:
    if workspace is None or not _is_sentinel_seed(event):
        return event.start_at, event.end_at, 0
    delta = resolve_demo_date(workspace) - SENTINEL_CALENDAR_ANCHOR_DATE
    if not delta.days:
        return event.start_at, event.end_at, 0
    return event.start_at + delta, event.end_at + delta, delta.days


def _event_for_analysis(event: WorkspaceCalendarEvent, workspace: Workspace) -> Any:
    start_at, end_at, _ = _display_window(event, workspace)
    return SimpleNamespace(
        id=event.id,
        title=event.title,
        description=event.description,
        start_at=start_at,
        end_at=end_at,
        timezone=event.timezone,
        location=event.location,
        participants=event.participants or [],
        category=event.category,
        priority=event.priority,
        status=event.status,
        source_kind=event.source_kind,
        source_label=event.source_label,
        meta_data=event.meta_data or {},
    )


def _calendar_settings(workspace: Workspace) -> dict[str, Any]:
    return dict((workspace.settings or {}).get("calendar") or {})


def calendar_write_policy(workspace: Workspace) -> str:
    return str(_calendar_settings(workspace).get("write_policy") or "approval_required")


def ensure_calendar_seed(db: DBSession, workspace: Workspace) -> int:
    """Seed demo calendar events once for a workspace."""
    if db.query(WorkspaceCalendarEvent).filter(WorkspaceCalendarEvent.workspace_id == workspace.id).first():
        return 0
    added = 0
    for item in SENTINEL_CALENDAR_SEED:
        seed_meta = {
            "seed": "sentinel-ci",
            "connector_id": "institutional_calendar",
            "seed_id": item.get("id"),
        }
        if item.get("context_ref"):
            seed_meta["context_ref"] = item["context_ref"]
        event = WorkspaceCalendarEvent(
            id=str(uuid4()),
            workspace_id=workspace.id,
            title=item["title"],
            description=item["description"],
            start_at=_parse_dt(item["start_at"]),
            end_at=_parse_dt(item["end_at"]),
            timezone=DEFAULT_TIMEZONE,
            location=item["location"],
            participants=item["participants"],
            category=item["category"],
            priority=item["priority"],
            status="scheduled",
            source_kind="internal_shared",
            source_label=DEFAULT_SOURCE_LABEL,
            meta_data=seed_meta,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(event)
        added += 1
    db.flush()
    return added


def serialize_event(event: WorkspaceCalendarEvent, *, workspace: Optional[Workspace] = None) -> dict[str, Any]:
    start_at, end_at, shift_days = _display_window(event, workspace)
    metadata = dict(event.meta_data or {})
    if shift_days:
        metadata["simulation_date_shift_days"] = shift_days
        metadata["simulated_from_date"] = event.start_at.date().isoformat()
        metadata["simulated_to_date"] = start_at.date().isoformat()
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "date": start_at.date().isoformat(),
        "time": start_at.strftime("%H:%M"),
        "end_time": end_at.strftime("%H:%M"),
        "timezone": event.timezone,
        "location": event.location,
        "participants": event.participants or [],
        "category": event.category,
        "priority": event.priority,
        "tone": _tone_for(event),
        "status": event.status,
        "source_kind": event.source_kind,
        "source_label": event.source_label,
        "metadata": metadata,
    }


def _tone_for(event: WorkspaceCalendarEvent) -> str:
    if event.status == "cancelled":
        return "muted"
    return {
        "critical": "critical",
        "high": "watch",
        "medium": "info",
        "low": "stable",
    }.get(event.priority, "info")


def list_events(
    db: DBSession,
    workspace: Workspace,
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    status: Optional[str] = None,
) -> list[WorkspaceCalendarEvent]:
    query = db.query(WorkspaceCalendarEvent).filter(WorkspaceCalendarEvent.workspace_id == workspace.id)
    if status:
        query = query.filter(WorkspaceCalendarEvent.status == status)
    rows = query.order_by(WorkspaceCalendarEvent.start_at.asc()).all()
    start_value = start.replace(tzinfo=None) if start else None
    end_value = end.replace(tzinfo=None) if end else None
    if start_value or end_value:
        filtered: list[WorkspaceCalendarEvent] = []
        for event in rows:
            display_start, display_end, _ = _display_window(event, workspace)
            if start_value and display_end < start_value:
                continue
            if end_value and display_start > end_value:
                continue
            filtered.append(event)
        rows = filtered
    return sorted(rows, key=lambda event: _display_window(event, workspace)[0])


def create_event(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    title: str,
    start_at: datetime,
    end_at: Optional[datetime] = None,
    location: str = "",
    description: str = "",
    participants: Optional[list[str]] = None,
    category: str = "ministerial",
    priority: str = "medium",
    status: str = "scheduled",
    metadata: Optional[dict[str, Any]] = None,
) -> WorkspaceCalendarEvent:
    start_at = start_at.replace(tzinfo=None)
    end_at = (end_at or (start_at + timedelta(hours=1))).replace(tzinfo=None)
    if end_at <= start_at:
        raise ValueError("end_at must be after start_at")
    event = WorkspaceCalendarEvent(
        id=str(uuid4()),
        workspace_id=workspace.id,
        title=title.strip() or "Evenement agenda",
        description=description.strip(),
        start_at=start_at,
        end_at=end_at,
        timezone=DEFAULT_TIMEZONE,
        location=location.strip(),
        participants=participants or [],
        category=category,
        priority=priority if priority in {"critical", "high", "medium", "low"} else "medium",
        status=status if status in {"scheduled", "tentative", "completed", "cancelled"} else "scheduled",
        source_kind="internal_shared",
        source_label=DEFAULT_SOURCE_LABEL,
        meta_data=metadata or {},
        created_by_user_id=user.id if user else None,
        updated_by_user_id=user.id if user else None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(event)
    db.flush()
    _audit(db, workspace, user, "calendar.event.created", event)
    return event


def update_event(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    event_id: str,
    *,
    updates: dict[str, Any],
) -> WorkspaceCalendarEvent:
    event = _get_event(db, workspace, event_id)
    for key in ("title", "description", "location", "category", "priority", "status"):
        if key in updates and updates[key] is not None:
            setattr(event, key, str(updates[key]).strip())
    if "participants" in updates and updates["participants"] is not None:
        event.participants = list(updates["participants"] or [])
    if "start_at" in updates and updates["start_at"] is not None:
        event.start_at = _parse_dt(updates["start_at"])
    if "end_at" in updates and updates["end_at"] is not None:
        event.end_at = _parse_dt(updates["end_at"])
    if event.end_at <= event.start_at:
        raise ValueError("end_at must be after start_at")
    metadata_changes: dict[str, Any] | None = None
    if "metadata" in updates and isinstance(updates["metadata"], dict):
        metadata_changes = _apply_metadata_update(event, updates["metadata"], user)
    event.updated_by_user_id = user.id if user else None
    event.updated_at = datetime.utcnow()
    db.flush()
    audit_details = {"updates": sorted(updates.keys())}
    if metadata_changes:
        audit_details["metadata_changes"] = metadata_changes
    _audit(db, workspace, user, "calendar.event.updated", event, details=audit_details)
    return event


def _apply_metadata_update(
    event: WorkspaceCalendarEvent,
    metadata_patch: dict[str, Any],
    user: Optional[User],
) -> dict[str, Any]:
    """Merge ``metadata_patch`` into ``event.meta_data`` with versioning.

    Phase H: agenda items merged with a stable ``id`` key and the prior
    version pushed into ``meta_data['history']`` for an auditable trail.
    """
    current = dict(event.meta_data or {})
    history = list(current.get("history") or [])
    changes: dict[str, Any] = {}

    if "agenda_items" in metadata_patch:
        prior_items = list(current.get("agenda_items") or [])
        incoming_items = list(metadata_patch.get("agenda_items") or [])
        merged: list[dict[str, Any]] = list(prior_items)
        by_id = {str(item.get("id")): idx for idx, item in enumerate(merged) if isinstance(item, dict) and item.get("id")}
        for item in incoming_items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or "")
            if key and key in by_id:
                merged[by_id[key]] = {**merged[by_id[key]], **item}
            else:
                merged.append(item)
                if key:
                    by_id[key] = len(merged) - 1
        history.append(
            {
                "kind": "agenda_items",
                "applied_at": datetime.utcnow().isoformat(),
                "applied_by": (user.email or user.username or user.id) if user else "system",
                "previous": prior_items,
                "next": merged,
            }
        )
        current["agenda_items"] = merged
        changes["agenda_items"] = {"added_or_updated": len(incoming_items)}

    for key, value in metadata_patch.items():
        if key in {"agenda_items", "history"}:
            continue
        current[key] = value
        changes[key] = True

    current["history"] = history[-25:]
    event.meta_data = current
    return changes


def cancel_event(db: DBSession, workspace: Workspace, user: Optional[User], event_id: str, reason: str = "") -> WorkspaceCalendarEvent:
    event = _get_event(db, workspace, event_id)
    event.status = "cancelled"
    event.updated_by_user_id = user.id if user else None
    event.updated_at = datetime.utcnow()
    metadata = dict(event.meta_data or {})
    if reason:
        metadata["cancel_reason"] = reason
    event.meta_data = metadata
    db.flush()
    _audit(db, workspace, user, "calendar.event.cancelled", event, details={"reason": reason})
    return event


def _get_event(db: DBSession, workspace: Workspace, event_id: str) -> WorkspaceCalendarEvent:
    event = (
        db.query(WorkspaceCalendarEvent)
        .filter(WorkspaceCalendarEvent.id == event_id, WorkspaceCalendarEvent.workspace_id == workspace.id)
        .first()
    )
    if not event:
        raise LookupError("calendar_event_not_found")
    return event


def summary_payload(db: DBSession, workspace: Workspace, *, day: Optional[date] = None) -> dict[str, Any]:
    day = day or resolve_demo_date(workspace)
    start = datetime.combine(day, time(0, 0))
    end = start + timedelta(days=1)
    events = list_events(db, workspace, start=start, end=end)
    active = [event for event in events if event.status != "cancelled"]
    active_for_analysis = [_event_for_analysis(event, workspace) for event in active]
    try:
        from app.services.action_plans import list_action_items

        action_items = list_action_items(db, workspace, include_cancelled=False)
    except Exception:
        action_items = []
    analysis = analyze_calendar(active_for_analysis, action_items=action_items, day=day)
    conflicts = analysis["conflicts"]
    now_time = resolve_demo_time(workspace)
    next_event = next(
        (event for event in active if _display_window(event, workspace)[0].time() >= now_time),
        active[0] if active else None,
    )
    payload = {
        "date": day.isoformat(),
        "connector": {
            "id": "institutional_calendar",
            "label": DEFAULT_SOURCE_LABEL,
            "mode": _calendar_settings(workspace).get("mode", "internal_shared"),
            "status": "connected",
            "write_policy": calendar_write_policy(workspace),
        },
        "events": [serialize_event(event, workspace=workspace) for event in events],
        "count": len(active),
        "conflicts": conflicts,
        "free_slots": _clean_slots(analysis["free_slots"]),
        "available_windows": _clean_slots(analysis["available_windows"]),
        "recommended_moves": analysis["recommended_moves"],
        "decision_deadlines": analysis["decision_deadlines"],
        "conflict_score": analysis["conflict_score"],
        "status": analysis["status"],
        "next_event": serialize_event(next_event, workspace=workspace) if next_event else None,
        "summary": _summary_text(active_for_analysis, conflicts),
    }
    return payload


def calendar_context_for_chat(db: DBSession, workspace: Workspace) -> str:
    payload = summary_payload(db, workspace)
    lines = [f"Agenda institutionnel ({payload['date']}) : {payload['summary']}"]
    for item in payload["events"]:
        if item["status"] == "cancelled":
            continue
        lines.append(
            f"- {item['time']}-{item['end_time']} · {item['title']} · {item['location']} · priorite {item['priority']}"
        )
    if payload["conflicts"]:
        lines.append(f"Conflits detectes: {len(payload['conflicts'])}")
    if payload.get("recommended_moves"):
        lines.append("Recommandations agenda: " + "; ".join(move["title"] + " -> " + move["to"] for move in payload["recommended_moves"][:3]))
    return "\n".join(lines)


def handle_calendar_chat_action(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    query: str,
    assistant_profile: Optional[str],
) -> Optional[dict[str, Any]]:
    if assistant_profile not in {"vigie_executive", "octave_executive"}:
        return None
    text = query.strip()
    lower = text.lower()
    if not any(word in lower for word in ("agenda", "reunion", "réunion", "rdv", "rendez-vous", "point presse", "calendrier")):
        return None
    write_policy = calendar_write_policy(workspace)
    if any(word in lower for word in ("ajoute", "ajouter", "planifie", "planifier", "crée", "creer", "organise")):
        start_at = _infer_datetime(lower)
        title = _infer_title(text, fallback="Reunion ajoutee par AYA")
        if write_policy == "approval_required":
            return {
                "action": "calendar_create_event",
                "applied": False,
                "requires_validation": True,
                "proposal": {"title": title, "start_at": start_at.isoformat()},
                "content": f"Je prepare l'ajout de **{title}** le {start_at.strftime('%d/%m a %H:%M')}. Validation requise avant ecriture agenda.",
            }
        event = create_event(
            db,
            workspace,
            user,
            title=title,
            start_at=start_at,
            location=_infer_location(text),
            description=f"Ajoute via AYA depuis la demande : {text}",
            participants=["Monsieur le Vice Premier Ministre", "Cabinet"],
            category="cabinet",
            priority="medium",
            metadata={"created_from": "vigie_chat", "raw_query": text},
        )
        db.commit()
        return {
            "action": "calendar_create_event",
            "applied": True,
            "event": serialize_event(event, workspace=workspace),
            "content": f"Evenement ajoute a l'agenda institutionnel : **{event.title}**, {event.start_at.strftime('%d/%m a %H:%M')}, {event.location or 'lieu a confirmer'}.",
        }
    if any(word in lower for word in ("deplace", "déplace", "reprogramme", "modifie", "avance", "repousse")):
        event = _match_event(db, workspace, lower)
        if not event:
            return {
                "action": "calendar_update_event",
                "applied": False,
                "content": "Je n'ai pas identifie l'evenement a modifier. Indique son intitule ou son horaire.",
            }
        new_start = _infer_datetime(lower, default_date=event.start_at.date())
        if write_policy == "approval_required":
            return {
                "action": "calendar_update_event",
                "applied": False,
                "requires_validation": True,
                "proposal": {"event_id": event.id, "start_at": new_start.isoformat()},
                "content": f"Je prepare le deplacement de **{event.title}** a {new_start.strftime('%H:%M')}. Validation requise avant ecriture agenda.",
            }
        duration = event.end_at - event.start_at
        updated = update_event(
            db,
            workspace,
            user,
            event.id,
            updates={"start_at": new_start, "end_at": new_start + duration},
        )
        db.commit()
        return {
            "action": "calendar_update_event",
            "applied": True,
            "event": serialize_event(updated, workspace=workspace),
            "content": f"Agenda mis a jour : **{updated.title}** est maintenant positionne a {updated.start_at.strftime('%H:%M')}.",
        }
    if any(word in lower for word in ("annule", "annuler", "supprime", "retire")):
        event = _match_event(db, workspace, lower)
        if not event:
            return {"action": "calendar_cancel_event", "applied": False, "content": "Je n'ai pas identifie l'evenement a annuler."}
        if write_policy == "approval_required":
            return {
                "action": "calendar_cancel_event",
                "applied": False,
                "requires_validation": True,
                "proposal": {"event_id": event.id},
                "content": f"Je prepare l'annulation de **{event.title}**. Validation requise avant ecriture agenda.",
            }
        cancelled = cancel_event(db, workspace, user, event.id, reason=f"Demande AYA: {text}")
        db.commit()
        return {
            "action": "calendar_cancel_event",
            "applied": True,
            "event": serialize_event(cancelled, workspace=workspace),
            "content": f"Evenement annule : **{cancelled.title}**.",
        }
    if any(word in lower for word in ("resume", "résume", "synthese", "synthèse", "conflit", "journee", "journée")):
        payload = summary_payload(db, workspace)
        _audit_summary(db, workspace, user, payload)
        return {
            "action": "calendar_daily_summary",
            "applied": False,
            "summary": payload,
            "content": _assistant_summary(payload),
        }
    return None


def _audit(db: DBSession, workspace: Workspace, user: Optional[User], event_type: str, event: WorkspaceCalendarEvent, details: Optional[dict[str, Any]] = None) -> None:
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=event_type,
        actor=_actor(user),
        details={
            "event_id": event.id,
            "title": event.title,
            "start_at": event.start_at.isoformat(),
            "status": event.status,
            "connector_id": "institutional_calendar",
            **(details or {}),
        },
    )


def _audit_summary(db: DBSession, workspace: Workspace, user: Optional[User], payload: dict[str, Any]) -> None:
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="calendar.summary.generated",
        actor=_actor(user),
        details={"date": payload["date"], "events": payload["count"], "conflicts": len(payload["conflicts"])},
    )


def _clean_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in slot.items() if key not in {"start_dt", "end_dt"}} for slot in slots]


def _conflicts(events: list[WorkspaceCalendarEvent]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    ordered = sorted(events, key=lambda event: event.start_at)
    for current, nxt in zip(ordered, ordered[1:]):
        if current.end_at > nxt.start_at:
            conflicts.append({"event_ids": [current.id, nxt.id], "label": f"{current.title} / {nxt.title}"})
    return conflicts


def _free_slots(events: list[WorkspaceCalendarEvent], day: date) -> list[dict[str, str]]:
    slots: list[dict[str, str]] = []
    cursor = datetime.combine(day, time(8, 0))
    end_day = datetime.combine(day, time(18, 30))
    for event in sorted(events, key=lambda item: item.start_at):
        if event.start_at > cursor and (event.start_at - cursor) >= timedelta(minutes=30):
            slots.append({"start": cursor.strftime("%H:%M"), "end": event.start_at.strftime("%H:%M")})
        cursor = max(cursor, event.end_at)
    if cursor < end_day:
        slots.append({"start": cursor.strftime("%H:%M"), "end": end_day.strftime("%H:%M")})
    return slots[:3]


def _summary_text(events: list[WorkspaceCalendarEvent], conflicts: list[dict[str, Any]]) -> str:
    if not events:
        return "Aucun evenement ministeriel consolide pour cette journee."
    critical = sum(1 for event in events if event.priority in {"critical", "high"})
    conflict_text = " Aucun conflit detecte." if not conflicts else f" {len(conflicts)} conflit(s) a arbitrer."
    return f"{len(events)} rendez-vous consolides, dont {critical} prioritaire(s).{conflict_text}"


def _assistant_summary(payload: dict[str, Any]) -> str:
    lines = [f"**Synthese agenda** — {payload['summary']}"]
    if payload.get("next_event"):
        nxt = payload["next_event"]
        lines.append(f"Prochaine echeance : **{nxt['title']}** a {nxt['time']}, {nxt['location']}.")
    if payload["free_slots"]:
        slots = ", ".join(f"{slot['start']}-{slot['end']}" for slot in payload["free_slots"])
        lines.append(f"Creneaux disponibles : {slots}.")
    return "\n".join(lines)


def _infer_datetime(text: str, default_date: Optional[date] = None) -> datetime:
    base = default_date or (date.today() + timedelta(days=1) if "demain" in text else date.today())
    if "15 avril" in text or "15/04" in text:
        base = date(2026, 4, 15)
    hour = 9
    minute = 0
    match = re.search(r"(\d{1,2})\s*(?:h|:)\s*(\d{2})?", text)
    if match:
        hour = max(0, min(23, int(match.group(1))))
        minute = int(match.group(2) or 0)
    return datetime.combine(base, time(hour, minute))


def _infer_title(text: str, fallback: str) -> str:
    cleaned = re.sub(r"\b(ajoute|ajouter|planifie|planifier|crée|creer|organise|une|un|le|la|demain|a|à|[0-9]{1,2}\s*h\s*[0-9]{0,2})\b", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-")
    if not cleaned:
        return fallback
    return cleaned[:100]


def _infer_location(text: str) -> str:
    match = re.search(r"(?:a|à|au|en)\s+([A-Z][\w' -]{2,40})", text)
    if match:
        return match.group(1).strip()
    return "Cabinet ministeriel"


def _match_event(db: DBSession, workspace: Workspace, text: str) -> Optional[WorkspaceCalendarEvent]:
    events = list_events(db, workspace, status="scheduled")
    tokens = [token for token in re.findall(r"[\w']+", text.lower()) if len(token) >= 4]
    best: tuple[int, WorkspaceCalendarEvent] | None = None
    for event in events:
        haystack = f"{event.title} {event.location}".lower()
        score = sum(1 for token in tokens if token in haystack)
        if score and (best is None or score > best[0]):
            best = (score, event)
    return best[1] if best else (events[0] if len(events) == 1 else None)
