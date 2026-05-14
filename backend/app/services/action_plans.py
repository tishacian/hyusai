"""Workspace action planner for ministerial and operational workspaces."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.action_plan import WorkspaceActionItem
from app.models.user import User
from app.models.workspace import Workspace
from app.services.audit_logger import emit_audit_event
from app.services.scenario_engine import generate_scenarios


VALID_STATUSES = {"planned", "in_progress", "completed", "cancelled"}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}


DEFAULT_SCENARIOS = generate_scenarios(target_kind="cabinet", risk_level="medium")


SENTINEL_ACTION_SEED = [
    {
        "title": "Arbitrer la reponse publique Nord",
        "description": "Qualifier les signaux presse et valider une ligne de communication preventive.",
        "target_kind": "zone",
        "target_id": "zone-nord",
        "target_label": "Nord",
        "priority": "critical",
        "due_at": "2026-04-15T10:30:00",
        "owner_label": "Cabinet communication",
        "source_kind": "news_lab",
        "source_id": "signal-north-delay",
        "confidence": "high",
        "recommended_window": {
            "label": "Avant point presse hebdomadaire",
            "start": "10:00",
            "end": "10:45",
            "why": "Dernier creneau utile avant prise de parole publique.",
        },
    },
    {
        "title": "Relancer projet social Nord",
        "description": "Demander au Directeur de cabinet un point cause/delai/action sur le projet rouge.",
        "target_kind": "project",
        "target_id": "proj-health-north",
        "target_label": "Projet sante Nord",
        "priority": "high",
        "due_at": "2026-04-15T16:30:00",
        "owner_label": "Directeur de cabinet",
        "source_kind": "mission_room",
        "source_id": "proj-health-north",
        "confidence": "medium",
        "recommended_window": {
            "label": "Apres revue operations Sahel",
            "start": "16:10",
            "end": "16:45",
            "why": "Fenetre courte pour arbitrage avant audience parlementaire.",
        },
    },
    {
        "title": "Preparer elements de langage cooperation FR-CI",
        "description": "Stabiliser un message positif et prudent avant dejeuner diplomatique.",
        "target_kind": "decision",
        "target_id": "decision-press-lines",
        "target_label": "Elements de langage",
        "priority": "medium",
        "due_at": "2026-04-15T12:15:00",
        "owner_label": "Cellule presse",
        "source_kind": "briefing",
        "source_id": "src-cabinet-brief-001",
        "confidence": "high",
        "recommended_window": {
            "label": "Entre point presse et dejeuner",
            "start": "11:50",
            "end": "12:20",
            "why": "Creneau disponible avant sequence diplomatique.",
        },
    },
]


def _actor(user: Optional[User]) -> str:
    if not user:
        return "system"
    return user.email or user.username or user.id


def _parse_dt(value: str | datetime | None) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def action_planner_write_policy(workspace: Workspace) -> str:
    settings = dict((workspace.settings or {}).get("action_planner") or {})
    return str(settings.get("write_policy") or "approval_required")


def serialize_action_item(item: WorkspaceActionItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "target_kind": item.target_kind,
        "target_id": item.target_id,
        "target_label": item.target_label,
        "priority": item.priority,
        "status": item.status,
        "due_at": item.due_at.isoformat() if item.due_at else None,
        "due_label": item.due_at.strftime("%H:%M") if item.due_at else "a planifier",
        "owner_label": item.owner_label,
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "calendar_event_id": item.calendar_event_id,
        "run_id": item.run_id,
        "confidence": item.confidence,
        "recommended_window": item.recommended_window or {},
        "scenario_options": item.scenario_options or [],
        "metadata": item.meta_data or {},
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def list_action_items(
    db: DBSession,
    workspace: Workspace,
    *,
    status: Optional[str] = None,
    target_kind: Optional[str] = None,
    include_cancelled: bool = True,
) -> list[WorkspaceActionItem]:
    query = db.query(WorkspaceActionItem).filter(WorkspaceActionItem.workspace_id == workspace.id)
    if status:
        query = query.filter(WorkspaceActionItem.status == status)
    elif not include_cancelled:
        query = query.filter(WorkspaceActionItem.status != "cancelled")
    if target_kind:
        query = query.filter(WorkspaceActionItem.target_kind == target_kind)
    return query.order_by(WorkspaceActionItem.due_at.is_(None), WorkspaceActionItem.due_at.asc(), WorkspaceActionItem.created_at.asc()).all()


def create_action_item(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    title: str,
    description: str = "",
    target_kind: str = "cabinet",
    target_id: str = "",
    target_label: str = "",
    priority: str = "medium",
    due_at: str | datetime | None = None,
    owner_label: str = "Cabinet",
    source_kind: str = "assistant",
    source_id: str = "",
    calendar_event_id: Optional[str] = None,
    run_id: Optional[str] = None,
    confidence: str = "medium",
    recommended_window: Optional[dict[str, Any]] = None,
    scenario_options: Optional[list[dict[str, Any]]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> WorkspaceActionItem:
    item = WorkspaceActionItem(
        id=str(uuid4()),
        workspace_id=workspace.id,
        title=(title or "").strip() or "Action cabinet",
        description=(description or "").strip(),
        target_kind=(target_kind or "cabinet").strip(),
        target_id=(target_id or "").strip(),
        target_label=(target_label or "").strip(),
        priority=priority if priority in VALID_PRIORITIES else "medium",
        status="planned",
        due_at=_parse_dt(due_at),
        owner_label=(owner_label or "Cabinet").strip(),
        source_kind=(source_kind or "assistant").strip(),
        source_id=(source_id or "").strip(),
        calendar_event_id=calendar_event_id,
        run_id=run_id,
        confidence=(confidence or "medium").strip(),
        recommended_window=recommended_window or {},
        scenario_options=scenario_options
        or generate_scenarios(
            target_kind=target_kind,
            target_id=target_id,
            risk_level=priority,
            source_refs=[source_id] if source_id else [],
            signal_strength=70 if priority in {"critical", "high"} else 45,
        ),
        meta_data=metadata or {},
        created_by_user_id=user.id if user else None,
        updated_by_user_id=user.id if user else None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(item)
    db.flush()
    _audit(db, workspace, user, "action_plan.item.created", item)
    return item


def update_action_item(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    item_id: str,
    updates: dict[str, Any],
) -> WorkspaceActionItem:
    item = _get_action_item(db, workspace, item_id)
    for key in ("title", "description", "target_kind", "target_id", "target_label", "owner_label", "source_kind", "source_id", "confidence"):
        if key in updates and updates[key] is not None:
            setattr(item, key, str(updates[key]).strip())
    if "priority" in updates and updates["priority"] is not None:
        item.priority = str(updates["priority"]) if str(updates["priority"]) in VALID_PRIORITIES else item.priority
    if "status" in updates and updates["status"] is not None:
        item.status = str(updates["status"]) if str(updates["status"]) in VALID_STATUSES else item.status
    if "due_at" in updates:
        item.due_at = _parse_dt(updates.get("due_at"))
    if "calendar_event_id" in updates:
        item.calendar_event_id = updates.get("calendar_event_id")
    if "recommended_window" in updates and updates["recommended_window"] is not None:
        item.recommended_window = dict(updates["recommended_window"] or {})
    if "scenario_options" in updates and updates["scenario_options"] is not None:
        item.scenario_options = list(updates["scenario_options"] or [])
    if "metadata" in updates and updates["metadata"] is not None:
        item.meta_data = dict(updates["metadata"] or {})
    item.updated_by_user_id = user.id if user else item.updated_by_user_id
    item.updated_at = datetime.utcnow()
    db.flush()
    _audit(db, workspace, user, "action_plan.item.updated", item, details={"updates": sorted(updates.keys())})
    return item


def cancel_action_item(db: DBSession, workspace: Workspace, user: Optional[User], item_id: str, reason: str = "") -> WorkspaceActionItem:
    item = update_action_item(db, workspace, user, item_id, {"status": "cancelled"})
    _audit(db, workspace, user, "action_plan.item.cancelled", item, details={"reason": reason})
    return item


def complete_action_item(db: DBSession, workspace: Workspace, user: Optional[User], item_id: str) -> WorkspaceActionItem:
    item = update_action_item(db, workspace, user, item_id, {"status": "completed"})
    _audit(db, workspace, user, "action_plan.item.completed", item)
    return item


def ensure_action_plan_seed(db: DBSession, workspace: Workspace) -> int:
    if db.query(WorkspaceActionItem).filter(WorkspaceActionItem.workspace_id == workspace.id).first():
        return 0
    added = 0
    for item in SENTINEL_ACTION_SEED:
        create_action_item(
            db,
            workspace,
            None,
            title=item["title"],
            description=item["description"],
            target_kind=item["target_kind"],
            target_id=item["target_id"],
            target_label=item["target_label"],
            priority=item["priority"],
            due_at=item["due_at"],
            owner_label=item["owner_label"],
            source_kind=item["source_kind"],
            source_id=item["source_id"],
            confidence=item["confidence"],
            recommended_window=item["recommended_window"],
            metadata={"seed": "sentinel-ci"},
        )
        added += 1
    return added


def summary_payload(db: DBSession, workspace: Workspace) -> dict[str, Any]:
    rows = list_action_items(db, workspace, include_cancelled=True)
    active = [row for row in rows if row.status not in {"completed", "cancelled"}]
    critical = [row for row in active if row.priority == "critical"]
    next_due = next((row for row in active if row.due_at), None)
    return {
        "count": len(rows),
        "active": len(active),
        "critical": len(critical),
        "completed": sum(1 for row in rows if row.status == "completed"),
        "cancelled": sum(1 for row in rows if row.status == "cancelled"),
        "next_due": serialize_action_item(next_due) if next_due else None,
        "write_policy": action_planner_write_policy(workspace),
    }


def action_context_for_chat(db: DBSession, workspace: Workspace) -> str:
    rows = list_action_items(db, workspace, include_cancelled=False)[:6]
    if not rows:
        return "Actions cabinet: aucune action active."
    lines = ["Actions cabinet actives:"]
    for item in rows:
        due = item.due_at.strftime("%d/%m %H:%M") if item.due_at else "a planifier"
        lines.append(f"- {item.title} [{item.priority}/{item.status}] avant {due}; responsable {item.owner_label}; cible {item.target_label or item.target_id}")
    return "\n".join(lines)


def handle_action_plan_chat_action(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    query: str,
    assistant_profile: Optional[str],
) -> Optional[dict[str, Any]]:
    if assistant_profile != "vigie_executive":
        return None
    text = (query or "").strip()
    lower = text.lower()
    action_terms = ("action", "tache", "tâche", "suivi", "cabinet", "arbitrage", "instruction")
    if not any(term in lower for term in action_terms):
        return None
    if any(term in lower for term in ("liste", "statut", "etat", "état", "suivi", "resume", "résume")) and not _has_action_verb(
        lower,
        ("ajoute", "ajouter", "cree", "crée", "creer", "créer", "planifie", "annule", "termine"),
    ):
        rows = [serialize_action_item(row) for row in list_action_items(db, workspace, include_cancelled=False)[:6]]
        return {
            "action": "action_plan_status",
            "applied": False,
            "items": rows,
            "content": _format_action_status(rows),
        }
    if _has_action_verb(lower, ("annule", "annuler", "cancel")):
        item = _match_action_item(db, workspace, lower)
        if not item:
            return _proposal_response("action_plan_cancel", text, "Je n'ai pas identifie l'action a annuler. Precisez son titre ou sa cible.")
        if action_planner_write_policy(workspace) == "approval_required":
            return {"action": "action_plan_cancel", "applied": False, "proposal": serialize_action_item(item), "content": f"Proposition prete : annuler {item.title}."}
        item = cancel_action_item(db, workspace, user, item.id, reason="Demande AYA explicite")
        return {"action": "action_plan_cancel", "applied": True, "item": serialize_action_item(item), "content": f"Action annulee : {item.title}."}
    if _has_action_verb(lower, ("termine", "terminer", "complete", "complète", "fait")):
        item = _match_action_item(db, workspace, lower)
        if not item:
            return _proposal_response("action_plan_complete", text, "Je n'ai pas identifie l'action a cloturer. Precisez son titre ou sa cible.")
        item = complete_action_item(db, workspace, user, item.id)
        return {"action": "action_plan_complete", "applied": True, "item": serialize_action_item(item), "content": f"Action marquee comme terminee : {item.title}."}
    if _has_action_verb(lower, ("ajoute", "ajouter", "cree", "crée", "creer", "créer", "planifie", "prepare", "prépare")):
        title = _title_from_query(text)
        priority = "critical" if any(term in lower for term in ("urgent", "critique", "prioritaire")) else "high" if "important" in lower else "medium"
        due_at = _due_from_query(lower)
        if action_planner_write_policy(workspace) == "approval_required":
            return _proposal_response("action_plan_create", text, f"Proposition prete : {title}. Validation humaine requise avant creation.")
        item = create_action_item(
            db,
            workspace,
            user,
            title=title,
            description=f"Action creee par AYA depuis la demande : {text}",
            target_kind="cabinet",
            target_label="Cabinet",
            priority=priority,
            due_at=due_at,
            owner_label="Cabinet",
            source_kind="assistant",
            confidence="medium",
            metadata={"created_from": "vigie_chat", "raw_query": text},
        )
        return {
            "action": "action_plan_create",
            "applied": True,
            "item": serialize_action_item(item),
            "content": f"Action cabinet creee : {item.title}. Echeance : {serialize_action_item(item)['due_label']}.",
        }
    return None


def _has_action_verb(text: str, terms: tuple[str, ...]) -> bool:
    """Match explicit action verbs without treating "a planifier" as a create command."""
    normalized = text.replace("à", "a")
    if "a planifier" in normalized:
        return False
    return any(re.search(rf"(^|[^a-zA-ZÀ-ÿ]){re.escape(term)}([^a-zA-ZÀ-ÿ]|$)", text) for term in terms)


def _get_action_item(db: DBSession, workspace: Workspace, item_id: str) -> WorkspaceActionItem:
    item = (
        db.query(WorkspaceActionItem)
        .filter(WorkspaceActionItem.id == item_id, WorkspaceActionItem.workspace_id == workspace.id)
        .first()
    )
    if not item:
        raise LookupError("action_item_not_found")
    return item


def _audit(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    event_type: str,
    item: WorkspaceActionItem,
    *,
    details: Optional[dict[str, Any]] = None,
) -> None:
    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=event_type,
        actor=_actor(user),
        details={
            "item_id": item.id,
            "target_kind": item.target_kind,
            "target_id": item.target_id,
            "priority": item.priority,
            "status": item.status,
            **(details or {}),
        },
    )


def _format_action_status(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Aucune action cabinet active."
    bullets = [f"- {row['title']} ({row['priority']}, {row['status']}) avant {row.get('due_label') or 'a planifier'}" for row in rows]
    return "Actions cabinet actives :\n" + "\n".join(bullets)


def _proposal_response(action: str, raw: str, content: str) -> dict[str, Any]:
    return {"action": action, "applied": False, "proposal": {"raw_query": raw}, "content": content}


def _title_from_query(text: str) -> str:
    cleaned = re.sub(r"^(ajoute|crée|cree|planifie|prépare|prepare)\s+(une?|l')?\s*", "", text.strip(), flags=re.I)
    cleaned = cleaned.strip(" .")
    if len(cleaned) > 92:
        cleaned = cleaned[:89].rstrip() + "..."
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Action cabinet"


def _due_from_query(lower: str) -> Optional[datetime]:
    base = datetime(2026, 4, 15, 9, 0)
    match = re.search(r"(\d{1,2})h(?:(\d{2}))?", lower)
    if match:
        hour = min(max(int(match.group(1)), 0), 23)
        minute = int(match.group(2) or 0)
        return base.replace(hour=hour, minute=minute)
    if "demain" in lower:
        return base + timedelta(days=1, hours=8)
    if "aujourd" in lower:
        return base.replace(hour=16, minute=0)
    return None


def _match_action_item(db: DBSession, workspace: Workspace, lower: str) -> Optional[WorkspaceActionItem]:
    rows = list_action_items(db, workspace, include_cancelled=False)
    best: tuple[int, WorkspaceActionItem] | None = None
    for row in rows:
        haystack = f"{row.title} {row.target_label} {row.target_id}".lower()
        score = sum(1 for token in re.findall(r"[a-zA-ZÀ-ÿ0-9_-]{4,}", lower) if token in haystack)
        if score and (best is None or score > best[0]):
            best = (score, row)
    return best[1] if best else (rows[0] if len(rows) == 1 else None)
