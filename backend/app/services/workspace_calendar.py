"""Workspace calendar service used by Mission Room and the executive assistant profile."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.calendar import WorkspaceCalendarEvent
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.calendar_intelligence import analyze_calendar
from app.services.demo_time_context import resolve_demo_date, resolve_demo_time


DEFAULT_TIMEZONE = "Africa/Abidjan"
DEFAULT_SOURCE_LABEL = "Agenda institutionnel"


SENTINEL_CALENDAR_SEED = [
    {
        "id": "evt-conseil-defense",
        "title": "Conseil Defense restreint",
        "description": "Point de coordination securitaire et arbitrages cabinet.",
        "start_at": "2026-05-25T08:30:00",
        "end_at": "2026-05-25T09:30:00",
        "location": "Salle du Conseil - Plateau",
        "participants": ["Ministre", "Directeur de cabinet", "Conseiller securite"],
        "category": "cabinet",
        "priority": "critical",
    },
    {
        "id": "evt-prefet-nawa",
        "title": "Rencontre Prefet de la region de Nawa",
        "description": "Suite au rapport du 10 mai : filiere cacao, infrastructures et diversification regionale.",
        "start_at": "2026-05-25T11:00:00",
        "end_at": "2026-05-25T12:00:00",
        "location": "Soubre (capitale regionale)",
        "participants": ["VP", "Prefet de Nawa", "AYA"],
        "category": "territorial",
        "priority": "high",
        "context_ref": "report-prefet-nawa-2026-05-10",
    },
    {
        "id": "evt-point-presse",
        "title": "Point presse hebdomadaire",
        "description": "Preparation des elements de langage et suivi image publique.",
        "start_at": "2026-05-25T11:45:00",
        "end_at": "2026-05-25T12:30:00",
        "location": "Salle presse ministere",
        "participants": ["Ministre", "Communication", "Porte-parole"],
        "category": "press",
        "priority": "high",
    },
    {
        "id": "evt-dejeuner-france",
        "title": "Dejeuner Ambassadeur de France",
        "description": "Cooperation FR-CI, perception publique et projets frontaliers.",
        "start_at": "2026-05-25T13:00:00",
        "end_at": "2026-05-25T14:15:00",
        "location": "Residence officielle",
        "participants": ["Ministre", "Ambassadeur de France", "Conseiller cooperation"],
        "category": "diplomacy",
        "priority": "medium",
    },
    {
        "id": "evt-revue-sahel",
        "title": "Revue operations Sahel",
        "description": "Synthese signaux regionaux et implications non militaires.",
        "start_at": "2026-05-25T15:00:00",
        "end_at": "2026-05-25T16:00:00",
        "location": "Centre de commandement",
        "participants": ["Ministre", "Cellule veille", "Strategie"],
        "category": "strategy",
        "priority": "high",
    },
    {
        "id": "evt-audience-parlement",
        "title": "Audience parlementaire",
        "description": "Reponses institutionnelles et suivi des questions sensibles.",
        "start_at": "2026-05-25T17:40:00",
        "end_at": "2026-05-25T18:30:00",
        "location": "Assemblee Nationale",
        "participants": ["Ministre", "Cabinet parlementaire"],
        "category": "institutional",
        "priority": "medium",
    },
    {
        "id": "evt-comite-nord",
        "title": "Comite projets sociaux Nord",
        "description": "Arbitrage des retards terrain et communication preventive.",
        "start_at": "2026-05-26T09:00:00",
        "end_at": "2026-05-26T10:00:00",
        "location": "Salon cabinet",
        "participants": ["Ministre", "Dircab", "Pilotage projets"],
        "category": "projects",
        "priority": "critical",
    },
    {
        "id": "evt-brief-ao",
        "title": "Brief veille Afrique de l'Ouest",
        "description": "Lecture des signaux faibles presse et diplomatie regionale.",
        "start_at": "2026-05-26T14:00:00",
        "end_at": "2026-05-26T14:45:00",
        "location": "Bureau Ministre",
        "participants": ["M. le Vice-President", "AYA", "Cellule veille"],
        "category": "intelligence",
        "priority": "high",
    },
]

def _actor(user: Optional[User]) -> str:
    if not user:
        return "system"
    return user.email or user.username or user.id


def _parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


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


def serialize_event(event: WorkspaceCalendarEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "start_at": event.start_at.isoformat(),
        "end_at": event.end_at.isoformat(),
        "date": event.start_at.date().isoformat(),
        "time": event.start_at.strftime("%H:%M"),
        "end_time": event.end_at.strftime("%H:%M"),
        "timezone": event.timezone,
        "location": event.location,
        "participants": event.participants or [],
        "category": event.category,
        "priority": event.priority,
        "tone": _tone_for(event),
        "status": event.status,
        "source_kind": event.source_kind,
        "source_label": event.source_label,
        "metadata": event.meta_data or {},
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
    if start:
        query = query.filter(WorkspaceCalendarEvent.end_at >= start.replace(tzinfo=None))
    if end:
        query = query.filter(WorkspaceCalendarEvent.start_at <= end.replace(tzinfo=None))
    if status:
        query = query.filter(WorkspaceCalendarEvent.status == status)
    return query.order_by(WorkspaceCalendarEvent.start_at.asc()).all()


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
    try:
        from app.services.action_plans import list_action_items

        action_items = list_action_items(db, workspace, include_cancelled=False)
    except Exception:
        action_items = []
    analysis = analyze_calendar(active, action_items=action_items, day=day)
    conflicts = analysis["conflicts"]
    now_time = resolve_demo_time(workspace)
    next_event = next((event for event in active if event.start_at.time() >= now_time), active[0] if active else None)
    payload = {
        "date": day.isoformat(),
        "connector": {
            "id": "institutional_calendar",
            "label": DEFAULT_SOURCE_LABEL,
            "mode": _calendar_settings(workspace).get("mode", "internal_shared"),
            "status": "connected",
            "write_policy": calendar_write_policy(workspace),
        },
        "events": [serialize_event(event) for event in events],
        "count": len(active),
        "conflicts": conflicts,
        "free_slots": _clean_slots(analysis["free_slots"]),
        "available_windows": _clean_slots(analysis["available_windows"]),
        "recommended_moves": analysis["recommended_moves"],
        "decision_deadlines": analysis["decision_deadlines"],
        "conflict_score": analysis["conflict_score"],
        "status": analysis["status"],
        "next_event": serialize_event(next_event) if next_event else None,
        "summary": _summary_text(active, conflicts),
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
    if assistant_profile != "vigie_executive":
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
            participants=["M. le Vice-President", "Cabinet"],
            category="cabinet",
            priority="medium",
            metadata={"created_from": "vigie_chat", "raw_query": text},
        )
        db.commit()
        return {
            "action": "calendar_create_event",
            "applied": True,
            "event": serialize_event(event),
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
            "event": serialize_event(updated),
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
            "event": serialize_event(cancelled),
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
