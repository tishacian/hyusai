"""Flow-node action executors and awaiting-state handling for Agentium registry."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.models.user import User
from app.models.workspace import Workspace
from app.services.actions.registry import ActionManifest, ActionResolution, resolve_action
from app.services.audit_logger import emit_audit_event
from app.services.demo_time_context import resolve_demo_date
from app.services.skills_registry import wrappers as skill_wrappers


def _skill_ctx(db: DBSession, workspace: Workspace, user: Optional[User]) -> dict[str, Any]:
    return {
        "db": db,
        "workspace_id": workspace.id,
        "workspace_slug": workspace.slug,
        "actor": (user.email or user.username or user.id) if user else "system:action_executor",
    }


def _last_focus(workspace: Workspace) -> Optional[str]:
    settings = workspace.settings or {}
    actions = settings.get("actions") or {}
    value = actions.get("last_focus")
    return str(value) if value else None


def set_last_focus(db: DBSession, workspace: Workspace, node_id: Optional[str]) -> None:
    settings = dict(workspace.settings or {})
    actions = dict(settings.get("actions") or {})
    if node_id:
        actions["last_focus"] = str(node_id)
    else:
        actions.pop("last_focus", None)
    settings["actions"] = actions
    workspace.settings = settings
    db.add(workspace)
    db.flush()


def _current_meeting(workspace: Workspace) -> Optional[str]:
    settings = workspace.settings or {}
    actions = settings.get("actions") or {}
    value = actions.get("current_meeting")
    return str(value) if value else None


def set_current_meeting(db: DBSession, workspace: Workspace, event_id: Optional[str]) -> None:
    settings = dict(workspace.settings or {})
    actions = dict(settings.get("actions") or {})
    if event_id:
        actions["current_meeting"] = str(event_id)
    else:
        actions.pop("current_meeting", None)
    settings["actions"] = actions
    workspace.settings = settings
    db.add(workspace)
    db.flush()


async def _invoke_skill(slug: str, payload: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    return await skill_wrappers.resolve(slug)(payload, ctx)


def get_awaiting_state(
    db: DBSession,
    workspace: Workspace,
    *,
    session_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    settings = workspace.settings or {}
    bucket = (settings.get("actions") or {}).get("awaiting") or {}
    if session_id and bucket.get(session_id):
        candidate = bucket.get(session_id)
        return candidate if _awaiting_valid(candidate) else None
    if bucket.get("_workspace"):
        candidate = bucket.get("_workspace")
        return candidate if _awaiting_valid(candidate) else None
    return None


def _awaiting_valid(awaiting: dict[str, Any]) -> bool:
    expires_at = awaiting.get("expires_at")
    if not expires_at:
        return True
    try:
        return datetime.fromisoformat(str(expires_at)) > datetime.utcnow()
    except ValueError:
        return True


def set_awaiting_state(
    db: DBSession,
    workspace: Workspace,
    awaiting: Optional[dict[str, Any]],
    *,
    session_id: Optional[str] = None,
) -> None:
    settings = dict(workspace.settings or {})
    actions = dict(settings.get("actions") or {})
    bucket = dict(actions.get("awaiting") or {})
    key = session_id or "_workspace"
    if awaiting:
        bucket[key] = awaiting
    else:
        bucket.pop(key, None)
    actions["awaiting"] = bucket
    settings["actions"] = actions
    workspace.settings = settings
    db.add(workspace)
    db.flush()


def resolve_action_with_awaiting(
    workspace: Workspace,
    *,
    text: str,
    surface: str = "chat",
    assistant_profile: Optional[str] = None,
    awaiting: Optional[dict[str, Any]] = None,
) -> ActionResolution:
    if awaiting:
        resolved = resolve_action(workspace, text=text, surface=surface, assistant_profile=assistant_profile)
        if resolved.matched and resolved.action_id == "voice.confirm_yes" and awaiting.get("action_on_yes"):
            return ActionResolution(
                True,
                action_id=str(awaiting["action_on_yes"]),
                confidence=resolved.confidence,
                requires_confirmation=False,
                reason="awaiting_yes",
                manifest=None,
            )
        if resolved.matched and resolved.action_id == "voice.confirm_no":
            return ActionResolution(
                True,
                action_id="voice.confirm_no",
                confidence=resolved.confidence,
                requires_confirmation=False,
                reason="awaiting_declined",
                manifest=None,
            )
    return resolve_action(workspace, text=text, surface=surface, assistant_profile=assistant_profile)


def _action_effect(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"chunk_type": "action_effect", "effect": kind, **payload}


def _manifest_by_id(workspace: Workspace, action_id: str, *, surface: str, assistant_profile: Optional[str]) -> Optional[ActionManifest]:
    from app.services.actions.registry import effective_action_manifests

    return next(
        (item for item in effective_action_manifests(workspace, surface=surface, assistant_profile=assistant_profile) if item.action_id == action_id),
        None,
    )


async def execute_flow_action(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    manifest: ActionManifest,
    text: str = "",
    session_id: Optional[str] = None,
    knowledge_scope: Optional[str] = None,
) -> dict[str, Any]:
    ctx = _skill_ctx(db, workspace, user)
    handler = manifest.handler.name
    effects: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    content = ""
    extra: dict[str, Any] = {"action_id": manifest.action_id, "handler": handler}
    awaiting_to_set: Optional[dict[str, Any]] = None
    awaiting_to_clear = False

    if handler == "voice_loop_stop":
        content = "Session vocale en pause."
    elif handler == "voice_repeat":
        content = "Je repete ma derniere reponse."
    elif handler == "voice_rephrase":
        content = "Je reformule ma derniere reponse de facon plus concise."
    elif handler == "briefing_priorities_v1":
        result = await _invoke_skill("briefing_priorities_v1", {"knowledge_scope": knowledge_scope}, ctx)
        priorities = result.get("priorities") or []
        lines = ["M. le Vice President, voici les sujets prioritaires :"]
        for idx, item in enumerate(priorities[:3], start=1):
            lines.append(f"{idx}. {item.get('title')} — {item.get('summary')}")
        content = "\n".join(lines)
        sources = [{"title": "Cockpit SENTINEL-CI", "kind": "cockpit", "source_id": item.get("id")} for item in priorities[:3]]
        extra["priorities"] = priorities
    elif handler == "map_focus_zone_with_project":
        from app.services.workspace_maps import build_map_command, ensure_workspace_map_seed

        ensure_workspace_map_seed(db, workspace)
        command = build_map_command(
            db,
            workspace,
            intent="focus_zone",
            target="zone-nord",
            layers=["territorial-risk", "open-intelligence", "maritime-traffic", "preventive-actions"],
            user=user,
        )
        db.commit()
        effects.append(
            _action_effect(
                "assistant-navigate",
                {"route": "/hypervisor/mission-room/strategie", "queryParams": {"focus": "zone-nord"}, "highlight": "proj-drone-centre-napie"},
            )
        )
        effects.append({"chunk_type": "map_command", **command})
        content = (
            "M. le Vice President, j'affiche la region Nord avec le Centre International "
            "de Formation aux Métiers des Drones de Napié (Poro) : composants importés "
            "Aerostar Dynamics bloqués au dedouanement Abidjan, chantier en retard de l'ordre "
            "de 120 jours sur un investissement de 100 M USD."
        )
        extra["map_command"] = command
        extra["highlight_project"] = "proj-drone-centre-napie"
    elif handler == "show_maritime_traffic":
        from app.services.workspace_maps import build_map_command, ensure_workspace_map_seed

        ensure_workspace_map_seed(db, workspace)
        command = build_map_command(
            db,
            workspace,
            intent="show_vessel_snapshot",
            target="port-abidjan",
            layers=["territorial-risk", "open-intelligence", "maritime-traffic"],
            user=user,
        )
        db.commit()
        effects.append(
            _action_effect(
                "assistant-navigate",
                {"route": "/hypervisor/mission-room/strategie", "queryParams": {"mode": "live", "layers": "maritime"}},
            )
        )
        effects.append({"chunk_type": "map_command", **command})
        maritime = await _invoke_skill("maritime_snapshot_read_v1", {}, ctx)
        cargo = next((e for e in (maritime.get("events") or []) if e.get("id") == "cargo-abidjan-supply-001"), None)
        cargo_line = cargo.get("summary") if cargo else "Trafic maritime Abidjan actif avec vigilance douaniere."
        content = f"M. le Vice President, trafic maritime a destination d'Abidjan : {cargo_line}"
        extra["maritime_snapshot"] = maritime
        awaiting_to_set = {
            "key": "customs_email",
            "action_on_yes": "aya.draft_customs_email",
            "action_on_no": "voice.confirm_no",
            "expires_at": (datetime.utcnow() + timedelta(minutes=15)).isoformat(),
            "proposal_id": "propose-customs-email",
        }
        effects.append(
            _action_effect(
                "assistant-propose",
                {
                    "proposal_id": "propose-customs-email",
                    "label": "Preparer un courrier de priorisation dedouanement ?",
                    "prompt": "Souhaitez-vous que je prepare le courrier de priorisation dedouanement pour la cargaison Nord ?",
                    "confirm_action": "aya.draft_customs_email",
                    "decline_action": "voice.confirm_no",
                },
            )
        )
        content += "\n\nSouhaitez-vous que je prepare un courrier de priorisation dedouanement pour la cargaison liee au projet Nord ?"
    elif handler == "propose_customs_email":
        awaiting_to_set = {
            "key": "customs_email",
            "action_on_yes": "aya.draft_customs_email",
            "action_on_no": "voice.confirm_no",
            "expires_at": (datetime.utcnow() + timedelta(minutes=15)).isoformat(),
            "proposal_id": "propose-customs-email",
        }
        effects.append(
            _action_effect(
                "assistant-propose",
                {
                    "proposal_id": "propose-customs-email",
                    "label": "Courrier dedouanement",
                    "confirm_action": "aya.draft_customs_email",
                    "decline_action": "voice.confirm_no",
                },
            )
        )
        content = "Je peux preparer un courrier de priorisation dedouanement pour la cargaison Nord. Confirmez-vous ?"
    elif handler == "draft_customs_email":
        draft = await _invoke_skill(
            "draft_email_v1",
            {
                "template_kind": "customs_derogation",
                "target_id": "cargo-abidjan-supply-001",
                "context_refs": [
                    "proj-drone-centre-napie",
                    "cargo-abidjan-supply-001",
                    "customs-record-non-conformite-2026-05",
                ],
            },
            ctx,
        )
        effects.append(
            _action_effect(
                "assistant-draft-open",
                {"target_type": "customs_email", "target_id": "cargo-abidjan-supply-001", "draft_payload": draft},
            )
        )
        content = f"M. le Vice President, brouillon pret : **{draft.get('subject')}**. Validation advisory requise."
        sources = draft.get("sources") or []
        awaiting_to_clear = True
        extra["draft"] = draft
    elif handler == "show_vessel_evidence":
        from app.services.workspace_maps import build_map_command, ensure_workspace_map_seed

        ensure_workspace_map_seed(db, workspace)
        command = build_map_command(
            db,
            workspace,
            intent="show_vessel_snapshot",
            target="cargo-abidjan-supply-001",
            layers=["maritime-traffic", "open-intelligence"],
            user=user,
        )
        db.commit()
        effects.append(
            _action_effect(
                "assistant-navigate",
                {
                    "route": "/hypervisor/mission-room/strategie",
                    "queryParams": {"mode": "live", "panel": "maritime", "vessel": "mv-atlantic-trader"},
                    "highlight": "cargo-abidjan-supply-001",
                },
            )
        )
        effects.append({"chunk_type": "map_command", **command})
        set_last_focus(db, workspace, "cargo-abidjan-supply-001")
        awaiting_to_set = {
            "key": "customs_pdf_show",
            "action_on_yes": "aya.show_customs_record",
            "action_on_no": "voice.confirm_no",
            "expires_at": (datetime.utcnow() + timedelta(minutes=15)).isoformat(),
            "proposal_id": "propose-customs-pdf-show",
        }
        effects.append(
            _action_effect(
                "assistant-propose",
                {
                    "proposal_id": "propose-customs-pdf-show",
                    "label": "Voir le PV douanes lie ?",
                    "prompt": "Souhaitez-vous que je vous montre le proces-verbal douanes lie a ce cargo ?",
                    "confirm_action": "aya.show_customs_record",
                    "decline_action": "voice.confirm_no",
                },
            )
        )
        content = (
            "M. le Vice President, MV Atlantic Trader (IMO 9876543) en attente de dedouanement a Vridi. "
            "Souhaitez-vous voir le PV douanes lie ?"
        )
        extra["vessel"] = {
            "id": "cargo-abidjan-supply-001",
            "name": "MV Atlantic Trader",
            "imo": "9876543",
            "mmsi": "627012345",
        }
        extra["map_command"] = command
    elif handler == "show_customs_record":
        from app.services.mission_room import SENTINEL_WORKSPACE_SLUG  # noqa: F401 — used for slug check

        document_id = "proces-verbal-douanes-non-conformite-2026-05-18"
        signed_url = f"/api/v1/mission-room/customs-records/{document_id}.pdf"
        effects.append(
            _action_effect(
                "assistant-navigate",
                {
                    "route": "/hypervisor/mission-room/strategie",
                    "queryParams": {"panel": "maritime", "document": document_id},
                },
            )
        )
        effects.append(
            _action_effect(
                "assistant-draft-open",
                {
                    "target_type": "document_preview",
                    "target_id": document_id,
                    "draft_payload": {
                        "kind": "document_preview",
                        "title": "PV douanes - non conformite declarative",
                        "date": "2026-05-18",
                        "page": 2,
                        "download_url": signed_url,
                        "highlight": "Cargo non conforme distinct du cargo MV Atlantic Trader",
                        "citation": "Page 2 du PV douanes du 18 mai 2026 - cargo non conforme distinct.",
                        "affected_cargo_ids": ["cargo-abidjan-supply-001"],
                    },
                },
            )
        )
        set_last_focus(db, workspace, "customs-record-non-conformite-2026-05")
        awaiting_to_set = {
            "key": "customs_email",
            "action_on_yes": "aya.draft_customs_email",
            "action_on_no": "voice.confirm_no",
            "expires_at": (datetime.utcnow() + timedelta(minutes=15)).isoformat(),
            "proposal_id": "propose-customs-derogation",
        }
        effects.append(
            _action_effect(
                "assistant-propose",
                {
                    "proposal_id": "propose-customs-derogation",
                    "label": "Preparer un email de derogation au chef des douanes ?",
                    "confirm_action": "aya.draft_customs_email",
                    "decline_action": "voice.confirm_no",
                },
            )
        )
        content = (
            "M. le Vice President, page 2 du PV douanes du 18 mai : la non conformite vise un autre cargo. "
            "La cargaison Nord (MV Atlantic Trader) est bloquee par effet collateral. "
            "Souhaitez-vous que je redige une derogation pour le chef des douanes ?"
        )
        sources = [
            {
                "title": "PV douanes - non conformite declarative (18 mai)",
                "kind": "customs_pv",
                "source_id": "customs-record-non-conformite-2026-05",
                "page": 2,
            }
        ]
        extra["customs_record"] = {
            "document_id": document_id,
            "page": 2,
            "download_url": signed_url,
        }
    elif handler == "explain_why":
        from app.services.mission_room import evidence_graph_trace

        last_focus = _last_focus(workspace) or "zone-nord"
        trace = evidence_graph_trace(workspace, from_node=last_focus, relation="caused_by", depth=2, db=db)
        path = trace.get("path") or []
        first_step = path[0] if path else None
        next_step = path[1] if len(path) > 1 else None
        next_node = (next_step or {}).get("node") or {}
        narrative = next_node.get("narrative_short") or "Aucun cause causale plus profonde identifiee."
        explanation = ((first_step or {}).get("edge") or {}).get("explanation") or narrative
        next_focus = next_node.get("id") or last_focus
        set_last_focus(db, workspace, next_focus)
        next_surface = next_node.get("next_surface") or {}
        if next_surface.get("route"):
            navigate_payload: dict[str, Any] = {"route": next_surface["route"]}
            if next_surface.get("queryParams"):
                navigate_payload["queryParams"] = next_surface["queryParams"]
            if next_surface.get("highlight"):
                navigate_payload["highlight"] = next_surface["highlight"]
            effects.append(_action_effect("assistant-navigate", navigate_payload))
        content = (
            f"M. le Vice President, {explanation} {narrative}"
            if next_node
            else "M. le Vice President, je n'ai pas de cause causale plus profonde a citer pour cette focale."
        )
        sources = [
            {
                "title": str(next_node.get("label") or next_focus),
                "kind": str(next_node.get("kind") or "evidence_node"),
                "source_id": next_focus,
            }
        ]
        for ref in next_node.get("evidence_refs") or []:
            sources.append({"title": str(ref), "kind": "evidence_ref", "source_id": str(ref)})
        extra["causal_trace"] = trace
        extra["last_focus"] = next_focus
        if next_focus == "cargo-abidjan-supply-001":
            awaiting_to_set = {
                "key": "customs_pdf_show",
                "action_on_yes": "aya.show_customs_record",
                "action_on_no": "voice.confirm_no",
                "expires_at": (datetime.utcnow() + timedelta(minutes=15)).isoformat(),
                "proposal_id": "propose-customs-pdf-show",
            }
            effects.append(
                _action_effect(
                    "assistant-propose",
                    {
                        "proposal_id": "propose-customs-pdf-show",
                        "label": "Voir le PV douanes lie ?",
                        "confirm_action": "aya.show_customs_record",
                        "decline_action": "voice.confirm_no",
                    },
                )
            )
        elif next_focus == "customs-record-non-conformite-2026-05":
            awaiting_to_set = {
                "key": "customs_email",
                "action_on_yes": "aya.draft_customs_email",
                "action_on_no": "voice.confirm_no",
                "expires_at": (datetime.utcnow() + timedelta(minutes=15)).isoformat(),
                "proposal_id": "propose-customs-derogation",
            }
            effects.append(
                _action_effect(
                    "assistant-propose",
                    {
                        "proposal_id": "propose-customs-derogation",
                        "label": "Preparer un email de derogation au chef des douanes ?",
                        "confirm_action": "aya.draft_customs_email",
                        "decline_action": "voice.confirm_no",
                    },
                )
            )
    elif handler == "update_meeting_agenda":
        from app.services.workspace_calendar import list_events, serialize_event

        event_id = _current_meeting(workspace)
        event = None
        if event_id:
            event = next((row for row in list_events(db, workspace) if row.id == event_id), None)
        if event is None:
            for row in list_events(db, workspace, status="scheduled"):
                meta = row.meta_data or {}
                if meta.get("seed_id") == "evt-prefet-nawa" or meta.get("context_ref") == "report-prefet-nawa-2026-05-10":
                    event = row
                    break
            if event is None:
                events = list_events(db, workspace, status="scheduled")
                event = events[0] if events else None
        if event is None:
            content = "M. le Vice President, aucun rendez-vous courant identifie pour mettre a jour l'ordre du jour."
        else:
            proposed_items = list((manifest.input_schema or {}).get("agenda_items") or []) or [
                {
                    "id": "agenda-cacao-diversification",
                    "title": "Point cacao - diversification anacarde (proposition AYA)",
                    "order": 99,
                    "priority": "high",
                    "owner_proposer": "AYA",
                    "decision_required": True,
                    "source_refs": ["report-prefet-nawa-2026-05-10", "sentinel-ci-anacarde-diversification-v1"],
                }
            ]
            set_current_meeting(db, workspace, event.id)
            effects.append(
                _action_effect(
                    "assistant-draft-open",
                    {
                        "target_type": "calendar_agenda_patch",
                        "target_id": event.id,
                        "draft_payload": {
                            "event_id": event.id,
                            "event_title": event.title,
                            "metadata": {"agenda_items": proposed_items},
                            "requires_validation": True,
                            "audit_event": "calendar.event.agenda_items.proposed",
                        },
                    },
                )
            )
            content = (
                f"M. le Vice President, je propose d'ajouter le point cacao a l'ordre du jour de **{event.title}**. "
                "Validation advisory requise avant ecriture agenda."
            )
            sources = [serialize_event(event)]
            extra["event_id"] = event.id
            extra["proposed_agenda_items"] = proposed_items
    elif handler == "start_meeting":
        from app.services.workspace_calendar import list_events, serialize_event

        event = None
        for row in list_events(db, workspace, status="scheduled"):
            meta = row.meta_data or {}
            if meta.get("seed_id") == "evt-prefet-nawa" or meta.get("context_ref") == "report-prefet-nawa-2026-05-10":
                event = row
                break
        if event is None:
            events = list_events(db, workspace, status="scheduled")
            event = events[0] if events else None
        if event is None:
            content = "M. le Vice President, aucun rendez-vous courant identifie pour demarrer une reunion."
        else:
            set_current_meeting(db, workspace, event.id)
            effects.append(
                _action_effect(
                    "assistant-navigate",
                    {
                        "route": f"/hypervisor/mission-room/agenda/meeting/{event.id}",
                        "queryParams": {"highlight": event.id},
                    },
                )
            )
            content = (
                f"M. le Vice President, je demarre la reunion **{event.title}**. "
                "Mode meeting live - chaque arbitrage sera logge dans le registre des decisions."
            )
            sources = [serialize_event(event)]
            extra["event_id"] = event.id
    elif handler == "log_decision":
        from app.services.meeting_decisions import log_decision_for_workspace, serialize_decision

        event_id = _current_meeting(workspace)
        if not event_id:
            content = "M. le Vice President, aucune reunion active. Demarrez d'abord la reunion."
        else:
            input_schema = manifest.input_schema or {}
            decision_payload = {
                "agenda_item_ref": str(input_schema.get("agenda_item_ref") or "agenda-cacao-diversification"),
                "options_offered": list(input_schema.get("options_offered") or [
                    {"key": "A", "label": "Statu quo"},
                    {"key": "B", "label": "Diversification anacarde - PPP transformation"},
                    {"key": "C", "label": "Plan mixte cooperative renforcee"},
                ]),
                "chosen_option": str(input_schema.get("chosen_option") or "B"),
                "rationale": str(input_schema.get("rationale") or "Diversification anacarde - alignement Banque mondiale, EUDR."),
                "source_refs": list(input_schema.get("source_refs") or [
                    "sentinel-ci-anacarde-diversification-v1",
                    "report-prefet-nawa-2026-05-10",
                ]),
            }
            decision = log_decision_for_workspace(
                db,
                workspace,
                user,
                calendar_event_id=event_id,
                **decision_payload,
            )
            db.commit()
            effects.append(
                _action_effect(
                    "assistant-navigate",
                    {
                        "route": f"/hypervisor/mission-room/agenda/meeting/{event_id}",
                        "queryParams": {"decision": decision.id},
                    },
                )
            )
            content = (
                f"Decision loggee : option {decision.chosen_option} - {decision_payload['rationale']}."
            )
            sources = [{"title": "Registre des decisions de reunion", "kind": "meeting_decision", "source_id": decision.id}]
            extra["decision"] = serialize_decision(decision)
    elif handler == "recall_past_decisions":
        from app.services.meeting_decisions import list_decisions_for_workspace, serialize_decision

        topic = (manifest.input_schema or {}).get("topic") or "cacao"
        decisions = list_decisions_for_workspace(db, workspace, topic=str(topic))
        serialized = [serialize_decision(item) for item in decisions[:5]]
        if not serialized:
            content = (
                f"M. le Vice President, aucune decision passee enregistree sur le theme {topic} pour le moment."
            )
        else:
            lines = [f"M. le Vice President, decisions passees liees a {topic} :"]
            for item in serialized:
                lines.append(
                    f"- {item.get('decided_at')[:16]} - option {item.get('chosen_option')} : {item.get('rationale')}"
                )
            content = "\n".join(lines)
            sources = [
                {"title": "Registre des decisions de reunion", "kind": "meeting_decision", "source_id": item.get("id")}
                for item in serialized
            ]
        extra["decisions"] = serialized
    elif handler == "open_next_meeting":
        cal = await _invoke_skill("calendar_daily_summary_v1", {"day": resolve_demo_date(workspace).isoformat()}, ctx)
        nxt = cal.get("next_event") or {}
        highlight = nxt.get("metadata", {}).get("seed_id") or nxt.get("id") or "evt-prefet-nawa"
        effects.append(
            _action_effect(
                "assistant-navigate",
                {"route": "/hypervisor/mission-room/agenda", "queryParams": {"highlight": highlight}},
            )
        )
        content = (
            f"M. le Vice President, prochain rendez-vous : **{nxt.get('title') or 'Rencontre Prefet Nawa'}** "
            f"a {nxt.get('time') or '11:00'} — {nxt.get('location') or 'Soubre'}."
        )
        sources = [{"title": "Agenda institutionnel", "kind": "calendar", "source_id": highlight}]
        extra["next_event"] = nxt
    elif handler == "summarize_last_exchanges":
        summary = await _invoke_skill(
            "summarize_long_document_v1",
            {
                "document_id": "report-prefet-nawa-2026-05-10",
                "query": "derniers echanges prefet nawa cacao",
                "focus_topics": ["cacao", "diversification", "infrastructures"],
                "length": "medium",
            },
            ctx,
        )
        content = summary.get("summary_markdown") or "Synthese indisponible."
        sources = summary.get("citations") or []
        extra["summary"] = summary
        awaiting_to_set = {
            "key": "cacao_summary",
            "action_on_yes": "aya.recommend_cacao",
            "action_on_no": "voice.confirm_no",
            "expires_at": (datetime.utcnow() + timedelta(minutes=20)).isoformat(),
            "proposal_id": "propose-cacao-recommendations",
        }
        effects.append(
            _action_effect(
                "assistant-propose",
                {
                    "proposal_id": "propose-cacao-recommendations",
                    "label": "Preconisations cacao",
                    "confirm_action": "aya.recommend_cacao",
                    "decline_action": "voice.confirm_no",
                },
            )
        )
        content += "\n\nSouhaitez-vous que je detaille les preconisations sur la filiere cacao ?"
    elif handler == "recommend_cacao":
        recs = await _invoke_skill(
            "generate_recommendations_v1",
            {"topic": "cacao_diversification", "chiffrage": True, "context_collection": "sentinel-ci-ministerial-briefs"},
            ctx,
        )
        options = recs.get("options") or []
        lines = ["M. le Vice President, preconisations cacao (chiffrage indicatif) :"]
        for idx, opt in enumerate(options[:3], start=1):
            lines.append(
                f"{idx}. {opt.get('label')} — {opt.get('summary')} "
                f"(~{opt.get('cost_estimate') or 'n/a'} ; confiance {int(float(opt.get('confidence') or 0.7) * 100)}%)"
            )
        content = "\n".join(lines)
        sources = recs.get("sources") or []
        extra["recommendations"] = recs
        effects.append(
            _action_effect(
                "assistant-navigate",
                {"route": "/hypervisor/mission-room/decisions", "queryParams": {"focus": "package-cacao-diversification"}},
            )
        )
        awaiting_to_set = {
            "key": "strategic_report",
            "action_on_yes": "aya.draft_strategic_report",
            "action_on_no": "voice.confirm_no",
            "expires_at": (datetime.utcnow() + timedelta(minutes=20)).isoformat(),
            "proposal_id": "propose-strategic-report",
        }
    elif handler == "draft_strategic_report":
        draft = await _invoke_skill(
            "draft_email_v1",
            {
                "template_kind": "strategic_report_long",
                "target_id": "package-cacao-diversification",
                "context_refs": ["report-prefet-nawa-2026-05-10", "proj-cacao-transformation-nawa"],
                "length": "long",
            },
            ctx,
        )
        effects.append(
            _action_effect(
                "assistant-draft-open",
                {"target_type": "strategic_report", "target_id": "package-cacao-diversification", "draft_payload": draft},
            )
        )
        content = "M. le Vice President, rapport de diversification cacao pret pour validation advisory."
        sources = draft.get("sources") or []
        awaiting_to_clear = True
        extra["draft"] = draft
    elif handler == "schedule_meeting":
        slot = await _invoke_skill(
            "schedule_meeting_v1",
            {
                "participant_role": "ministre Economie",
                "topic": "Diversification cacao — arbitrage cabinet",
                "urgency": "high",
                "duration_min": 45,
            },
            ctx,
        )
        effects.append(
            _action_effect(
                "assistant-draft-open",
                {"target_type": "calendar_slot", "target_id": slot.get("calendar_event_draft_id"), "draft_payload": slot},
            )
        )
        proposed = slot.get("proposed_slot") or {}
        content = (
            f"M. le Vice President, creneau propose avec le ministre de l'Economie : "
            f"{proposed.get('date')} a {proposed.get('time')} — {proposed.get('location') or 'Plateau'}."
        )
        extra["schedule"] = slot
        awaiting_to_clear = True
    elif handler == "voice_navigate_view":
        view = (manifest.input_schema or {}).get("default_view") or "cockpit"
        effects.append(_action_effect("assistant-navigate", {"route": f"/hypervisor/mission-room/{view}"}))
        content = f"J'ouvre la vue {view}."
    elif handler == "awaiting_declined":
        content = "Tres bien, je n'applique pas cette proposition pour le moment."
        awaiting_to_clear = True
    else:
        content = f"Action {manifest.label} — execution demo en attente de binding complet."

    if awaiting_to_clear:
        set_awaiting_state(db, workspace, None, session_id=session_id)
    elif awaiting_to_set:
        set_awaiting_state(db, workspace, awaiting_to_set, session_id=session_id)

    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=manifest.audit_event,
        actor=ctx["actor"],
        details={"action_id": manifest.action_id, "text": text, "effects": [e.get("effect") for e in effects if e.get("effect")]},
    )

    return {
        "action": manifest.action_id,
        "applied": True,
        "content": content,
        "sources": sources,
        "action_effects": effects,
        "requires_confirmation": False,
        "action_manifest_id": manifest.action_id,
        **extra,
    }


async def handle_registry_chat_action(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    query: str,
    assistant_profile: Optional[str] = None,
    session_id: Optional[str] = None,
    knowledge_scope: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Resolve and execute registry flow-node actions (non-legacy)."""
    if assistant_profile != "vigie_executive" and "sentinel" not in (workspace.slug or "").lower():
        return None

    awaiting = get_awaiting_state(db, workspace, session_id=session_id)
    resolution = resolve_action_with_awaiting(
        workspace,
        text=query,
        surface="chat",
        assistant_profile=assistant_profile,
        awaiting=awaiting,
    )
    if not resolution.matched or not resolution.action_id:
        return None

    if resolution.reason == "awaiting_declined":
        set_awaiting_state(db, workspace, None, session_id=session_id)
        return {
            "action": "awaiting_declined",
            "applied": True,
            "content": "Tres bien, je n'applique pas cette proposition pour le moment.",
            "action_effects": [],
        }

    manifest = _manifest_by_id(workspace, resolution.action_id, surface="chat", assistant_profile=assistant_profile)
    if not manifest:
        return None
    if manifest.handler.kind == "legacy_adapter":
        return None
    if manifest.handler.kind != "flow_node":
        return None

    return await execute_flow_action(
        db,
        workspace,
        user,
        manifest=manifest,
        text=query,
        session_id=session_id,
        knowledge_scope=knowledge_scope,
    )
