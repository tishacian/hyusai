"""Flow-node action executors and awaiting-state handling for Agentium registry."""
from __future__ import annotations

import asyncio
import re
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


def _pending_agenda_patch(workspace: Workspace) -> Optional[dict[str, Any]]:
    settings = workspace.settings or {}
    actions = settings.get("actions") or {}
    pending = actions.get("pending_agenda_patch")
    return dict(pending) if isinstance(pending, dict) else None


def set_pending_agenda_patch(
    db: DBSession, workspace: Workspace, payload: Optional[dict[str, Any]]
) -> None:
    settings = dict(workspace.settings or {})
    actions = dict(settings.get("actions") or {})
    if payload:
        actions["pending_agenda_patch"] = dict(payload)
    else:
        actions.pop("pending_agenda_patch", None)
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


def _atlantic_trader_webcam_payload() -> Optional[dict[str, Any]]:
    from app.services.webcam_proxy import (
        get_spec as _get_webcam_spec,
        recommended_webcam_for_vessel,
        webcam_cycle_for_vessel,
    )

    webcam_source_id = recommended_webcam_for_vessel(
        mmsi="627012345",
        cargo_id="cargo-abidjan-supply-001",
    )
    if not webcam_source_id:
        return None
    spec_for_webcam = _get_webcam_spec(webcam_source_id)
    cycle_ids = webcam_cycle_for_vessel(
        mmsi="627012345",
        cargo_id="cargo-abidjan-supply-001",
    )
    return {
        "source_id": webcam_source_id,
        "vessel_mmsi": "627012345",
        "vessel_name": "MV Atlantic Trader",
        "cargo_id": "cargo-abidjan-supply-001",
        "label": spec_for_webcam.label if spec_for_webcam else None,
        "attribution": spec_for_webcam.attribution if spec_for_webcam else None,
        "label_disclaimer": spec_for_webcam.label_disclaimer if spec_for_webcam else None,
        "proxy_url": f"/api/v1/mission-room/webcams/proxy?source_id={webcam_source_id}",
        "cycle": [
            {
                "source_id": candidate,
                "label": (_get_webcam_spec(candidate).label if _get_webcam_spec(candidate) else candidate),
                "proxy_url": f"/api/v1/mission-room/webcams/proxy?source_id={candidate}",
            }
            for candidate in cycle_ids
        ],
    }


_DEFAULT_CACAO_AGENDA_ITEM: dict[str, Any] = {
    "id": "agenda-cacao-diversification",
    "title": "Point cacao - diversification anacarde (proposition AYA)",
    "order": 99,
    "priority": "high",
    "owner_proposer": "AYA",
    "decision_required": True,
    "source_refs": ["report-prefet-nawa-2026-05-10", "sentinel-ci-anacarde-diversification-v1"],
}

_DEROGATION_AGENDA_ITEM: dict[str, Any] = {
    "id": "agenda-derogation-douanes",
    "title": "Derogation douanes — cargo MV Atlantic Trader / Centre Napie",
    "order": 99,
    "priority": "high",
    "owner_proposer": "AYA",
    "decision_required": True,
    "source_refs": ["proces-verbal-douanes-non-conformite-2026-05-18", "cargo-abidjan-supply-001"],
}

_AGENDA_SUBJECT_RE = re.compile(
    r"(?:"
    r"mets?\s+a\s+jour\s+l\s*'?odj\s*:?\s*"
    r"|mets?\s+a\s+jour\s+l\s*'?ordre\s+du\s+jour\s*:?\s*"
    r"|ajoute\s+le\s+point\s+"
    r"|ajoute\s+a\s+l\s*'?ordre\s+du\s+jour\s*:?\s*"
    r"|patch\s+l\s*'?agenda\s*:?\s*"
    r")(.+)$",
    re.IGNORECASE,
)


def _resolve_agenda_item_from_prompt(text: str) -> dict[str, Any]:
    """Extract a demo-safe agenda item from a free-form update_meeting_agenda prompt."""

    from app.services.actions.registry import _normalize, _strip_wake_word

    normalized = _strip_wake_word(_normalize(text))
    subject = ""
    match = _AGENDA_SUBJECT_RE.search(normalized)
    if match:
        subject = match.group(1).strip(" .,:;!?")
        subject = re.sub(r"\s+au\s+meeting$", "", subject).strip()

    if not subject or subject in {"l ordre du jour", "ordre du jour", "l odj", "odj"}:
        return dict(_DEFAULT_CACAO_AGENDA_ITEM)

    if re.search(r"\bderogation\b", subject):
        return dict(_DEROGATION_AGENDA_ITEM)

    if re.search(r"\bcacao\b", subject):
        return dict(_DEFAULT_CACAO_AGENDA_ITEM)

    slug = re.sub(r"[^a-z0-9]+", "-", subject).strip("-")[:40] or "custom"
    display = subject[:1].upper() + subject[1:] if subject else subject
    return {
        "id": f"agenda-{slug}",
        "title": f"Point {display} (proposition AYA)",
        "order": 99,
        "priority": "high",
        "owner_proposer": "AYA",
        "decision_required": True,
        "source_refs": [],
    }


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
    elif handler == "acknowledge_presence":
        content = "Je suis là, Monsieur le Vice Premier Ministre, à votre écoute."
        effects.append(_action_effect("assistant-acknowledge", {"assistant": "AYA"}))
    elif handler == "briefing_priorities_v1":
        result = await _invoke_skill("briefing_priorities_v1", {"knowledge_scope": knowledge_scope}, ctx)
        priorities = result.get("priorities") or []
        lines = ["Monsieur le Vice Premier Ministre, voici les sujets prioritaires :"]
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
            "Monsieur le Vice Premier Ministre, j'affiche la region Nord avec le Centre International "
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
                {
                    "route": "/hypervisor/mission-room/strategie",
                    "queryParams": {"mode": "live", "panel": "maritime", "vessel": "mv-atlantic-trader"},
                    "highlight": "cargo-abidjan-supply-001",
                },
            )
        )
        effects.append({"chunk_type": "map_command", **command})
        webcam_payload = _atlantic_trader_webcam_payload()
        if webcam_payload:
            effects.append(_action_effect("assistant-show-webcam", webcam_payload))
            extra["webcam"] = webcam_payload
        maritime = await _invoke_skill("maritime_snapshot_read_v1", {}, ctx)
        cargo = next((e for e in (maritime.get("events") or []) if e.get("id") == "cargo-abidjan-supply-001"), None)
        cargo_line = cargo.get("summary") if cargo else "Trafic maritime Abidjan actif avec vigilance douaniere."
        content = f"Monsieur le Vice Premier Ministre, trafic maritime a destination d'Abidjan : {cargo_line}"
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
        content = f"Monsieur le Vice Premier Ministre, brouillon pret : **{draft.get('subject')}**. Validation advisory requise."
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
        # Auto-select port webcam vignette next to the AIS marker.
        webcam_payload = _atlantic_trader_webcam_payload()
        if webcam_payload:
            effects.append(_action_effect("assistant-show-webcam", webcam_payload))
            extra["webcam"] = webcam_payload
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
            "Monsieur le Vice Premier Ministre, MV Atlantic Trader (IMO 9876543) en attente de dedouanement a Vridi. "
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
            "Monsieur le Vice Premier Ministre, page 2 du PV douanes du 18 mai : la non conformite vise un autre cargo. "
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

        # Lightweight text-based focus reset: if the operator references a
        # high-level entity (zone, projet, cargaison, port, etc.) we restart
        # the causal drill from that node rather than continuing from a
        # leaf left over from a previous run. This keeps the demo robust
        # against repeated runs and polluted ``last_focus`` state.
        text_lower = (text or "").lower()
        text_focus: Optional[str] = None
        if any(token in text_lower for token in ("nord", "zone nord", "tendu")):
            text_focus = "zone-nord"
        elif any(token in text_lower for token in ("projet", "napie", "napié", "centre drone", "centre drones", "retard")):
            text_focus = "proj-drone-centre-napie"
        elif any(token in text_lower for token in ("cargo", "cargaison", "cargaisons", "navire", "bateau", "atlantic trader", "bloquee", "bloquée")):
            text_focus = "cargo-abidjan-supply-001"
        elif any(token in text_lower for token in ("douanes", "pv douanes", "non conformite", "non conformité")):
            text_focus = "customs-record-non-conformite-2026-05"
        last_focus = text_focus or _last_focus(workspace) or "zone-nord"
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
            f"Monsieur le Vice Premier Ministre, {explanation} {narrative}"
            if next_node
            else "Monsieur le Vice Premier Ministre, je n'ai pas de cause causale plus profonde a citer pour cette focale."
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
            # Cargo drill: emit the port-webcam vignette auto-select effect
            # so the UI surfaces the live snapshot next to the AIS marker
            # without waiting for an explicit ``show_vessel_evidence`` call.
            from app.services.webcam_proxy import (
                get_spec as _get_webcam_spec,
                recommended_webcam_for_vessel,
                webcam_cycle_for_vessel,
            )

            webcam_source_id = recommended_webcam_for_vessel(
                mmsi="627012345",
                cargo_id="cargo-abidjan-supply-001",
            )
            if webcam_source_id:
                spec_for_webcam = _get_webcam_spec(webcam_source_id)
                cycle_ids = webcam_cycle_for_vessel(
                    mmsi="627012345",
                    cargo_id="cargo-abidjan-supply-001",
                )
                webcam_payload = {
                    "source_id": webcam_source_id,
                    "vessel_mmsi": "627012345",
                    "vessel_name": "MV Atlantic Trader",
                    "cargo_id": "cargo-abidjan-supply-001",
                    "label": spec_for_webcam.label if spec_for_webcam else None,
                    "attribution": spec_for_webcam.attribution if spec_for_webcam else None,
                    "label_disclaimer": spec_for_webcam.label_disclaimer if spec_for_webcam else None,
                    "proxy_url": f"/api/v1/mission-room/webcams/proxy?source_id={webcam_source_id}",
                    "cycle": [
                        {
                            "source_id": candidate,
                            "label": (
                                _get_webcam_spec(candidate).label
                                if _get_webcam_spec(candidate)
                                else candidate
                            ),
                            "proxy_url": f"/api/v1/mission-room/webcams/proxy?source_id={candidate}",
                        }
                        for candidate in cycle_ids
                    ],
                }
                effects.append(_action_effect("assistant-show-webcam", webcam_payload))
                extra["webcam"] = webcam_payload
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

        # Prefer to target the Prefet Nawa meeting when available so that the
        # S2 trame stays coherent even when ``current_meeting`` points at a
        # different event (eg. Conseil Defense restreint). Fall back to the
        # explicit ``current_meeting`` then to the first scheduled event.
        event = None
        for row in list_events(db, workspace, status="scheduled"):
            meta = row.meta_data or {}
            if meta.get("seed_id") == "evt-prefet-nawa" or meta.get("context_ref") == "report-prefet-nawa-2026-05-10":
                event = row
                break
        if event is None:
            event_id = _current_meeting(workspace)
            if event_id:
                event = next((row for row in list_events(db, workspace) if row.id == event_id), None)
        if event is None:
            events = list_events(db, workspace, status="scheduled")
            event = events[0] if events else None
        if event is None:
            content = "Monsieur le Vice Premier Ministre, aucun rendez-vous courant identifie pour mettre a jour l'ordre du jour."
        else:
            schema_items = list((manifest.input_schema or {}).get("agenda_items") or [])
            proposed_items = schema_items or [_resolve_agenda_item_from_prompt(text)]
            agenda_label = str(proposed_items[0].get("title") or "point agenda")
            set_current_meeting(db, workspace, event.id)
            # Stage the patch so a follow-up "oui" triggers
            # ``aya.confirm_agenda_patch`` which applies the calendar PATCH.
            set_pending_agenda_patch(
                db,
                workspace,
                {
                    "event_id": event.id,
                    "agenda_items": proposed_items,
                    "proposed_at": datetime.utcnow().isoformat(),
                },
            )
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
                            "confirm_action": "aya.confirm_agenda_patch",
                            "decline_action": "voice.confirm_no",
                        },
                    },
                )
            )
            effects.append(
                _action_effect(
                    "assistant-propose",
                    {
                        "proposal_id": "propose-calendar-agenda-patch",
                        "label": "Valider la mise a jour de l'ordre du jour ?",
                        "confirm_action": "aya.confirm_agenda_patch",
                        "decline_action": "voice.confirm_no",
                    },
                )
            )
            content = (
                f"Monsieur le Vice Premier Ministre, je propose d'ajouter **{agenda_label}** a l'ordre du jour de **{event.title}**. "
                "Validation advisory requise avant ecriture agenda."
            )
            sources = [serialize_event(event, workspace=workspace)]
            extra["event_id"] = event.id
            extra["proposed_agenda_items"] = proposed_items
            awaiting_to_set = {
                "key": "calendar_agenda_patch",
                "action_on_yes": "aya.confirm_agenda_patch",
                "action_on_no": "voice.confirm_no",
                "expires_at": (datetime.utcnow() + timedelta(minutes=20)).isoformat(),
                "proposal_id": "propose-calendar-agenda-patch",
                "event_id": event.id,
            }
    elif handler == "confirm_agenda_patch":
        from app.services.workspace_calendar import list_events, serialize_event, update_event

        pending = _pending_agenda_patch(workspace)
        if not pending:
            content = (
                "Monsieur le Vice Premier Ministre, aucune mise a jour d'ordre du jour en attente. "
                "Faites une proposition avant validation."
            )
        else:
            event_id = str(pending.get("event_id") or "")
            agenda_items = list(pending.get("agenda_items") or [])
            event = next((row for row in list_events(db, workspace) if row.id == event_id), None)
            if event is None:
                content = "Monsieur le Vice Premier Ministre, je n'ai pas retrouve le rendez-vous cible pour appliquer la mise a jour."
                set_pending_agenda_patch(db, workspace, None)
            else:
                try:
                    updated = update_event(
                        db,
                        workspace,
                        user,
                        event.id,
                        updates={"metadata": {"agenda_items": agenda_items}},
                    )
                    db.commit()
                except LookupError:
                    db.rollback()
                    content = "Monsieur le Vice Premier Ministre, le rendez-vous cible n'existe plus."
                    set_pending_agenda_patch(db, workspace, None)
                    updated = None
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    content = f"Monsieur le Vice Premier Ministre, erreur en appliquant l'ordre du jour : {exc}."
                    updated = None
                else:
                    set_pending_agenda_patch(db, workspace, None)
                    effects.append(
                        _action_effect(
                            "assistant-navigate",
                            {
                                "route": f"/hypervisor/mission-room/agenda",
                                "queryParams": {"highlight": updated.id},
                            },
                        )
                    )
                    content = (
                        f"Ordre du jour mis a jour pour **{updated.title}** : "
                        f"{len(agenda_items)} point(s) ajoute(s) avec tracabilite advisory."
                    )
                    sources = [serialize_event(updated, workspace=workspace)]
                    extra["event_id"] = updated.id
                    extra["applied_agenda_items"] = agenda_items
                awaiting_to_clear = True
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
            content = "Monsieur le Vice Premier Ministre, aucun rendez-vous courant identifie pour demarrer une reunion."
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
                f"Monsieur le Vice Premier Ministre, je demarre la reunion **{event.title}**. "
                "Mode meeting live - chaque arbitrage sera logge dans le registre des decisions."
            )
            sources = [serialize_event(event, workspace=workspace)]
            extra["event_id"] = event.id
    elif handler == "log_decision":
        from app.services.meeting_decisions import log_decision_for_workspace, serialize_decision

        event_id = _current_meeting(workspace)
        if not event_id:
            content = "Monsieur le Vice Premier Ministre, aucune reunion active. Demarrez d'abord la reunion."
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
                f"Monsieur le Vice Premier Ministre, aucune decision passee enregistree sur le theme {topic} pour le moment."
            )
        else:
            lines = [f"Monsieur le Vice Premier Ministre, decisions passees liees a {topic} :"]
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
            f"Monsieur le Vice Premier Ministre, prochain rendez-vous : **{nxt.get('title') or 'Rencontre Prefet Nawa'}** "
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
        lines = ["Monsieur le Vice Premier Ministre, preconisations cacao (chiffrage indicatif) :"]
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
        from app.services.sentinel_ci_reports import generate_strategic_report

        input_schema = manifest.input_schema or {}
        topic = str(input_schema.get("topic") or "cacao_diversification")
        context_refs = list(
            input_schema.get("context_refs")
            or ["report-prefet-nawa-2026-05-10", "proj-cacao-transformation-nawa"]
        )
        target_id = str(input_schema.get("target_id") or "package-cacao-diversification")

        # Generate the real PDF via the same path as POST /reports/generate so
        # the drawer receives an ``object_key`` + ``download_url`` that resolves
        # to the freshly-written PDF in the workspace object store.
        try:
            report = generate_strategic_report(
                db,
                workspace,
                user,
                topic=topic,
                context_refs=context_refs,
                target_id=target_id,
                length="long",
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - degrade gracefully for demo
            report = {
                "report_id": None,
                "topic": topic,
                "object_key": None,
                "download_url": None,
                "total_pages": None,
                "title": f"Rapport strategique - {topic}",
                "context_refs": context_refs,
                "advisory_only": True,
                "requires_validation": True,
                "error": str(exc),
            }

        # Best-effort headline used by the drawer in ``document_preview`` mode.
        draft_payload = {
            "kind": "document_preview",
            "title": report.get("title") or f"Rapport strategique - {topic}",
            "topic": topic,
            "report_id": report.get("report_id"),
            "object_key": report.get("object_key"),
            "download_url": report.get("download_url"),
            "signed_url": report.get("download_url"),
            "total_pages": report.get("total_pages"),
            "context_refs": report.get("context_refs") or context_refs,
            "advisory_only": True,
            "requires_validation": True,
            "audit_event": "report.strategic.generated",
            "citation": "Synthèse des préconisations cacao – diversification anacarde, base rapport Préfet Nawa.",
            "page": 1,
        }
        effects.append(
            _action_effect(
                "assistant-draft-open",
                {
                    "target_type": "strategic_report",
                    "target_id": report.get("report_id") or target_id,
                    "draft_payload": draft_payload,
                },
            )
        )
        if report.get("download_url"):
            content = (
                "Monsieur le Vice Premier Ministre, rapport de diversification cacao genere "
                f"({report.get('total_pages')} pages) — pret pour validation advisory."
            )
        else:
            content = (
                "Monsieur le Vice Premier Ministre, rapport de diversification cacao prepare. "
                "Le PDF est temporairement indisponible — la synthese reste consultable."
            )
        sources = [
            {"title": "Rapport Prefet Nawa - 10 mai 2026", "kind": "ministerial_brief", "source_id": "report-prefet-nawa-2026-05-10"},
            {"title": "Guide Anacarde - diversification cacao", "kind": "knowledge_guide", "source_id": "sentinel-ci-anacarde-diversification-v1"},
        ]
        awaiting_to_clear = True
        extra["report"] = report
        extra["draft"] = draft_payload
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
            f"Monsieur le Vice Premier Ministre, creneau propose avec le ministre de l'Economie : "
            f"{proposed.get('date')} a {proposed.get('time')} — {proposed.get('location') or 'Plateau'}."
        )
        extra["schedule"] = slot
        awaiting_to_clear = True
    elif handler == "show_security_posture":
        # S3.1 — pivot the cockpit on the dual-axis security posture block and
        # set the focus on the package-securite-dual decision package so the
        # whole UI converges on the Conseil Defense 15h00 narrative.
        from app.services.mission_room import SECURITY_POSTURE, _clone

        posture = _clone(SECURITY_POSTURE)
        set_last_focus(db, workspace, "package-securite-dual")
        effects.append(
            _action_effect(
                "assistant-navigate",
                {
                    "route": "/hypervisor/mission-room/securite",
                    "queryParams": {"focus": "security_posture"},
                    "highlight": "package-securite-dual",
                },
            )
        )
        interior = posture.get("interior") or {}
        exterior = posture.get("exterior") or {}
        next_council = posture.get("next_council") or {}
        content = (
            "Monsieur le Vice Premier Ministre, la posture du jour est en vigilance intérieure "
            f"et élevée sur l'axe Sahel. {interior.get('headline', '')} "
            f"Je prépare la lecture pour le {next_council.get('label', 'Conseil Défense')} "
            f"de {next_council.get('time', '15:00')}."
        )
        sources = [
            {
                "title": "Note posture sécurité Sahel — 25 mai 2026",
                "kind": "security_brief",
                "source_id": "src-note-posture-sahel-2026-05-25",
            },
            {
                "title": "Synthèse Conseil Défense restreint — 08h30",
                "kind": "security_brief",
                "source_id": "src-conseil-defense-2026-05-25-am",
            },
        ]
        extra["security_posture"] = posture
        extra["next_council"] = next_council
    elif handler == "show_social_pulse":
        # S3.2 — surface the social-geo map layer + open the demo-safe Twitter
        # snapshot drawer. We reuse the press article drawer (Option rapide
        # v1) by emitting a document_preview draft_payload that the existing
        # drawer can render as a list/detail of tweets with sentiment badges.
        from app.services.mission_room import SOCIAL_SNAPSHOT, _clone
        from app.services.workspace_maps import build_map_command, ensure_workspace_map_seed

        snapshot = _clone(SOCIAL_SNAPSHOT)
        ensure_workspace_map_seed(db, workspace)
        command = build_map_command(
            db,
            workspace,
            intent="set_layers",
            target="port-abidjan",
            layers=["territorial-risk", "open-intelligence", "social-geo"],
            user=user,
        )
        db.commit()
        effects.append(
            _action_effect(
                "assistant-navigate",
                {
                    "route": "/hypervisor/mission-room/veille-sociale",
                    "queryParams": {"panel": "social", "snapshot": "abidjan"},
                },
            )
        )
        effects.append({"chunk_type": "map_command", **command})
        # Build a markdown body block so the generic assistant-draft-drawer
        # can render the snapshot as a list (Option rapide: reuse the existing
        # drawer without a dedicated tweet component). Tweets are grouped by
        # bucket (officiel / citoyen / rumeur) with sentiment badges in text.
        totals = snapshot.get("totals", {}) or {}
        tweets = snapshot.get("tweets") or []

        def _bucket_label(kind: str) -> str:
            return {
                "officiel": "Canaux vérifiés",
                "citoyen": "Comptes citoyens (pseudonymisés)",
                "rumeur": "Rumeur frontière Nord (pseudonymisée)",
            }.get(kind, kind.title())

        body_lines = [
            "## Pulsation sociale — Abidjan, 14h25",
            "",
            (
                f"Snapshot demo-safe : {totals.get('tweets', 0)} tweets sur la séquence du jour — "
                f"{totals.get('officiel', 0)} canaux vérifiés, {totals.get('citoyen', 0)} citoyens "
                f"pseudonymisés, {totals.get('rumeur', 0)} signaux rumeur frontière Nord."
            ),
            "",
        ]
        for bucket in ("officiel", "citoyen", "rumeur"):
            grouped = [tweet for tweet in tweets if tweet.get("kind") == bucket]
            if not grouped:
                continue
            body_lines.append(f"### {_bucket_label(bucket)} ({len(grouped)})")
            for tweet in grouped[:6]:
                sentiment = (tweet.get("sentiment") or "neutral").upper()
                handle = tweet.get("handle") or ""
                engagement = tweet.get("engagement") or 0
                geo = (tweet.get("geo") or {}).get("label") or ""
                body_lines.append(
                    f"- [{sentiment}] {handle} — {tweet.get('text', '')} "
                    f"({engagement} eng. · {geo})"
                )
            body_lines.append("")
        body_lines.append("Démentis officiels visibles · advisory only — démo Sentinel-CI.")

        effects.append(
            _action_effect(
                "assistant-draft-open",
                {
                    "target_type": "social_pulse_snapshot",
                    "target_id": "social-snapshot-2026-05-25",
                    "draft_payload": {
                        # `kind` + `mode` both carry the dedicated drawer key so the
                        # frontend renders <app-vp-social-pulse-drawer> instead of
                        # the generic markdown draft drawer (no more `## ##` dump).
                        "kind": "social_pulse_snapshot",
                        "mode": "social_pulse_snapshot",
                        "target_type": "social_pulse_snapshot",
                        "target_id": "social-snapshot-2026-05-25",
                        "title": "Pulsation sociale — snapshot Abidjan 14h25",
                        "subject": "Pulsation sociale Abidjan — snapshot demo-safe",
                        # body_markdown stays as a fallback for backend tests and
                        # for clients that haven't shipped the dedicated drawer.
                        "body_markdown": "\n".join(body_lines),
                        "summary": (
                            f"{totals.get('tweets', 0)} tweets — "
                            f"{totals.get('officiel', 0)} canaux vérifiés, "
                            f"{totals.get('citoyen', 0)} citoyens, "
                            f"{totals.get('rumeur', 0)} rumeurs frontière."
                        ),
                        "snapshot": snapshot,
                        "sources": [
                            {"title": "Snapshot social Abidjan — 14h25", "id": "src-social-snapshot-2026-05-25"},
                        ],
                        "advisory_only": True,
                    },
                },
            )
        )
        content = (
            "Monsieur le Vice Premier Ministre, j'affiche "
            f"{snapshot.get('totals', {}).get('tweets', 0)} signaux publics sur la séquence du jour : "
            f"{snapshot.get('totals', {}).get('officiel', 0)} canaux vérifiés, "
            f"{snapshot.get('totals', {}).get('citoyen', 0)} citoyens pseudonymisés et "
            f"{snapshot.get('totals', {}).get('rumeur', 0)} signaux rumeur frontière Nord. "
            "Le volume reste maîtrisé après les démentis officiels."
        )
        sources = [
            {
                "title": "Snapshot social Abidjan — 14h25",
                "kind": "social_snapshot",
                "source_id": "src-social-snapshot-2026-05-25",
            },
        ]
        extra["social_snapshot"] = snapshot
        extra["map_command"] = command
    elif handler == "trace_rumor_origin":
        # S3.3 — drill the evidence chain for the Nord border rumor and zoom
        # the map on the Northern frontier (border-tension layer + zone-nord
        # focus). Reuses the rumor_origin_trace_v1 skill envelope if present,
        # otherwise falls back to the deterministic seed in mission_room.
        from app.services.mission_room import RUMOR_FRONTIER_TRACE, _clone
        from app.services.workspace_maps import build_map_command, ensure_workspace_map_seed

        trace = _clone(RUMOR_FRONTIER_TRACE)
        ensure_workspace_map_seed(db, workspace)
        command = build_map_command(
            db,
            workspace,
            intent="focus_zone",
            target="zone-nord",
            layers=["territorial-risk", "open-intelligence", "border-tension", "social-geo"],
            user=user,
        )
        db.commit()
        set_last_focus(db, workspace, "src-rumor-frontier-nord-2026-05-25")
        effects.append(
            _action_effect(
                "assistant-navigate",
                {
                    "route": "/hypervisor/mission-room/strategie",
                    "queryParams": {"focus": "rumor_frontier_nord"},
                    "highlight": "zone-nord",
                },
            )
        )
        effects.append({"chunk_type": "map_command", **command})
        chain_lines = ["## Trace OSINT — rumeur frontière Nord", "", trace.get("summary", ""), ""]
        chain_lines.append(f"Origine : {trace.get('origin', '—')}")
        chain_lines.append("")
        chain_lines.append("### Chaîne de propagation")
        for step in trace.get("chain") or []:
            chain_lines.append(
                f"- Étape {step.get('step', '?')} · {step.get('time', '—')} · {step.get('channel', '—')} — "
                f"{step.get('signal', '')} (acteur : {step.get('actor', '—')}, "
                f"confiance {round(float(step.get('confidence', 0)) * 100)}%)"
            )
        chain_lines.append("")
        chain_lines.append("Démentis officiels FANCI + Préfecture Nord publiés à 13h46 et 13h52.")
        chain_lines.append("Advisory only — démo Sentinel-CI.")

        effects.append(
            _action_effect(
                "assistant-draft-open",
                {
                    "target_type": "rumor_trace_timeline",
                    "target_id": "rumor-frontier-nord-2026-05-25",
                    "draft_payload": {
                        # `kind` + `mode` both carry the dedicated drawer key so the
                        # frontend renders <app-vp-rumor-trace-timeline> with the
                        # vertical chronology + verdict bar instead of a markdown
                        # chain dump. Aliases (rumor_trace_dossier, rumor_origin)
                        # are still accepted by the drawer router for compat.
                        "kind": "rumor_trace_timeline",
                        "mode": "rumor_trace_timeline",
                        "target_type": "rumor_trace_timeline",
                        "target_id": "rumor-frontier-nord-2026-05-25",
                        "title": trace.get("headline"),
                        "subject": "Rumeur frontière Nord — chaîne OSINT et démenti officiel",
                        "body_markdown": "\n".join(chain_lines),
                        "summary": trace.get("summary"),
                        "origin": trace.get("origin"),
                        "chain": trace.get("chain") or [],
                        "recommended_action": trace.get("recommended_action"),
                        "aya_sentence": trace.get("aya_sentence"),
                        "verdict_label": "DÉMENTI OFFICIEL FANCI",
                        "sources": [
                            {"title": "Dossier rumeur frontière Nord", "id": "src-rumor-frontier-nord-2026-05-25"},
                        ],
                        "advisory_only": True,
                    },
                },
            )
        )
        awaiting_to_set = {
            "key": "security_communique",
            "action_on_yes": "aya.draft_security_communique",
            "action_on_no": "voice.confirm_no",
            "expires_at": (datetime.utcnow() + timedelta(minutes=15)).isoformat(),
            "proposal_id": "propose-security-communique",
        }
        effects.append(
            _action_effect(
                "assistant-propose",
                {
                    "proposal_id": "propose-security-communique",
                    "label": "Rédiger un communiqué souverain démentant la rumeur ?",
                    "prompt": "Souhaitez-vous que je rédige le communiqué cabinet citant le démenti FANCI ?",
                    "confirm_action": "aya.draft_security_communique",
                    "decline_action": "voice.confirm_no",
                },
            )
        )
        content = (
            "Monsieur le Vice Premier Ministre, la rumeur part d'un tweet citoyen à 11h42, "
            "puis circule via Telegram et un blog avant le démenti FANCI de 13h46. "
            "La Préfecture Nord confirme à 13h52 ; je peux préparer le communiqué."
        )
        sources = [
            {
                "title": "Dossier rumeur frontière Nord — OSINT et démentis",
                "kind": "rumor_dossier",
                "source_id": "src-rumor-frontier-nord-2026-05-25",
            },
        ]
        extra["rumor_trace"] = trace
        extra["map_command"] = command
    elif handler == "show_troops_movement":
        # S3.4 — activate military-air + border-tension map layers and surface
        # the ADS-B advisory snapshot of the Sahel theater. The disclaimer
        # « ADS-B advisory only » is also carried by the map layer legend.
        from app.services.mission_room import TROOPS_SAHEL, _clone
        from app.services.workspace_maps import build_map_command, ensure_workspace_map_seed

        snapshot = _clone(TROOPS_SAHEL)
        ensure_workspace_map_seed(db, workspace)
        command = build_map_command(
            db,
            workspace,
            intent="set_layers",
            target=None,
            layers=["territorial-risk", "regional-context", "military-air", "border-tension"],
            user=user,
        )
        db.commit()
        effects.append(
            _action_effect(
                "assistant-navigate",
                {
                    "route": "/hypervisor/mission-room/securite/monitor",
                    "queryParams": {"focus": "sahel", "layers": "military-air,border-tension"},
                },
            )
        )
        effects.append({"chunk_type": "map_command", **command})
        body_lines = [
            f"## {snapshot.get('theater_label', 'Théâtre Sahel')} — snapshot ADS-B advisory",
            "",
            snapshot.get("disclaimer", "ADS-B advisory only — démo Sentinel-CI."),
            "",
            "### Traces ADS-B (snapshot 14h30)",
        ]
        for track in (snapshot.get("tracks") or [])[:12]:
            body_lines.append(
                f"- {track.get('callsign', '—')} ({track.get('kind', '—')}, "
                f"{track.get('operator', '—')}) · alt {track.get('altitude_ft', '—')} ft · "
                f"vitesse {track.get('speed_kt', '—')} kt · {track.get('origin', '—')} → "
                f"{track.get('destination', '—')}"
            )
        if snapshot.get("watch_zones"):
            body_lines.append("")
            body_lines.append("### Zones de surveillance")
            for zone in snapshot.get("watch_zones") or []:
                body_lines.append(
                    f"- {zone.get('label') or zone.get('name', '—')} : {zone.get('summary', '')}"
                )
        if snapshot.get("cedeao_bases"):
            body_lines.append("")
            body_lines.append("### Bases CEDEAO en alerte standard")
            for base in snapshot.get("cedeao_bases") or []:
                body_lines.append(
                    f"- {base.get('label') or base.get('name', '—')} — {base.get('status') or base.get('role', 'alerte standard')}"
                )

        effects.append(
            _action_effect(
                "assistant-draft-open",
                {
                    "target_type": "troops_sahel_snapshot",
                    "target_id": "troops-sahel-2026-05-25",
                    "draft_payload": {
                        # `kind` + `mode` both carry the dedicated drawer key so the
                        # frontend renders <app-vp-troops-theater-drawer> (table +
                        # cards) instead of a markdown ADS-B list dump.
                        "kind": "troops_sahel_snapshot",
                        "mode": "troops_sahel_snapshot",
                        "target_type": "troops_sahel_snapshot",
                        "target_id": "troops-sahel-2026-05-25",
                        "title": snapshot.get("theater_label"),
                        "subject": "Snapshot ADS-B advisory — théâtre Sahel",
                        "body_markdown": "\n".join(body_lines),
                        "disclaimer": snapshot.get("disclaimer"),
                        "theater_label": snapshot.get("theater_label"),
                        "captured_at": snapshot.get("captured_at"),
                        "tracks": snapshot.get("tracks") or [],
                        "watch_zones": snapshot.get("watch_zones") or [],
                        "cedeao_bases": snapshot.get("cedeao_bases") or [],
                        "sources": [
                            {"title": "Snapshot ADS-B advisory Sahel — 14h30", "id": "src-troops-sahel-2026-05-25"},
                            {"title": "Note posture sécurité Sahel — 25 mai 2026", "id": "src-note-posture-sahel-2026-05-25"},
                        ],
                        "advisory_only": True,
                    },
                },
            )
        )
        content = (
            "Monsieur le Vice Premier Ministre, j'affiche uniquement un snapshot ADS-B advisory : "
            f"{len(snapshot.get('tracks') or [])} traces publiques sur Bamako, Ouagadougou, "
            "Niamey et Abidjan. Aucun élément affiché ne constitue une donnée classifiée "
            "ni une confirmation opérationnelle."
        )
        sources = [
            {
                "title": "Snapshot ADS-B advisory Sahel — 14h30",
                "kind": "ads_b_advisory",
                "source_id": "src-troops-sahel-2026-05-25",
            },
            {
                "title": "Note posture sécurité Sahel — 25 mai 2026",
                "kind": "security_brief",
                "source_id": "src-note-posture-sahel-2026-05-25",
            },
        ]
        extra["troops_sahel"] = snapshot
        extra["map_command"] = command
    elif handler == "show_reputation_drill":
        # S3.5 — open the reputation view with the 2+ / 1- drill. The critical
        # item is the existing L'Inter critique (attention-inter-budget) so we
        # do not invent a press item.
        # The frontend mission-room shell scrolls to the element whose `id`
        # matches the `highlight` query param, so we anchor it on the
        # `reputation-drill` panel id and add `drill=open` for explicit intent.
        from app.services.mission_room import REPUTATION_DRILL, _clone

        drill = _clone(REPUTATION_DRILL)
        effects.append(
            _action_effect(
                "assistant-navigate",
                {
                    "route": "/hypervisor/mission-room/reputation",
                    "queryParams": {
                        "focus": "drill",
                        "drill": "open",
                    },
                    "highlight": "reputation-drill",
                    "workspace": workspace.slug or "sentinel-ci",
                },
            )
        )
        items = drill.get("items") or []
        positive_items = [item for item in items if item.get("kind") == "positif"]
        critical_items = [item for item in items if item.get("kind") == "critique"]
        positive_lines = [f"{item.get('title')}" for item in positive_items]
        critical_lines = [f"{item.get('title')}" for item in critical_items]
        content = (
            f"Monsieur le Vice Premier Ministre, le score réputation est à {drill.get('score')}/100 "
            f"cette semaine ({'+' if (drill.get('delta') or 0) >= 0 else ''}{drill.get('delta')} pts). "
            "Deux lectures sont favorables, sur la séquence Nord et la réponse Nawa ; "
            "la critique à surveiller porte sur le budget défense."
        )
        sources = [
            {
                "title": item.get("source_label") or item.get("title"),
                "kind": "press_article" if item.get("kind") == "positif" else "press_attention",
                "source_id": item.get("source_id"),
            }
            for item in items
        ]
        extra["reputation_drill"] = drill
    elif handler == "draft_security_communique":
        # S3.6 — draft a sovereign communique citing the FANCI / Prefecture
        # Nord démentis. Reuses the draft_email_v1 skill envelope so the
        # drawer renders the brouillon identically to S1.7 (Atlantic Trader).
        try:
            draft = await _invoke_skill(
                "draft_email_v1",
                {
                    "template_kind": "security_communique",
                    "target_id": "rumor-frontier-nord-2026-05-25",
                    "context_refs": [
                        "src-rumor-frontier-nord-2026-05-25",
                        "src-conseil-defense-2026-05-25-am",
                        "src-note-posture-sahel-2026-05-25",
                    ],
                },
                ctx,
            )
        except Exception:  # noqa: BLE001 - degrade gracefully for demo
            draft = None
        if isinstance(draft, dict):
            draft_content = " ".join(
                str(draft.get(key) or "")
                for key in ("subject", "body_markdown", "body", "recipient")
            ).lower()
            if not (
                any(token in draft_content for token in ("securite", "security", "rumeur", "frontiere", "fanci"))
                and not any(token in draft_content for token in ("cacao", "nawa", "diversification"))
            ):
                draft = None
        if not draft or not isinstance(draft, dict):
            draft = {
                "subject": "Communiqué de sécurité — frontière Nord, démenti officiel",
                "to": ["Direction de la communication présidentielle", "Cellule veille SENTINEL-CI"],
                "body_markdown": (
                    "Le Cabinet du Vice Premier Ministre confirme que les informations circulant depuis "
                    "la fin de matinée au sujet d'une incursion à la frontière Nord ont été "
                    "officiellement démenties par la FANCI à 13h46, puis par la Préfecture Nord "
                    "à 13h52. Les postes mixtes Bouna-Kong-Téhini sont signalés comme nominaux "
                    "dans le cadre de la coordination habituelle.\n\n"
                    "Le Cabinet appelle chacun à ne pas relayer de contenus non vérifiés et "
                    "rappelle que la transparence institutionnelle reste la ligne de conduite : "
                    "tout signal sérieux sera communiqué par les canaux publics compétents.\n\n"
                    "Dans la perspective du Conseil Défense restreint de 15h00, une coordination "
                    "CEDEAO demeure active sur le corridor Korhogo-Bamako. Cette note est un "
                    "brouillon advisory soumis à validation humaine avant toute diffusion.\n\n"
                    "Sources : État-Major FANCI ; Préfecture Nord ; Cellule veille SENTINEL-CI."
                ),
                "sources": [
                    {"title": "Démenti officiel FANCI", "source_id": "tweet-off-002"},
                    {"title": "Mise au point Préfecture Nord", "source_id": "tweet-off-005"},
                    {
                        "title": "Dossier rumeur frontière Nord",
                        "source_id": "src-rumor-frontier-nord-2026-05-25",
                    },
                ],
                "advisory_only": True,
                "requires_validation": True,
            }
        effects.append(
            _action_effect(
                "assistant-draft-open",
                {
                    "target_type": "security_communique",
                    "target_id": "rumor-frontier-nord-2026-05-25",
                    "draft_payload": draft,
                },
            )
        )
        subject = (draft or {}).get("subject") or "Communiqué de sécurité frontière Nord"
        content = (
            f"Monsieur le Vice Premier Ministre, je prépare un brouillon cabinet : **{subject}**. "
            "Il cite le démenti FANCI, la mise au point de la Préfecture Nord et reste soumis "
            "à validation humaine avant diffusion."
        )
        sources = (draft or {}).get("sources") or [
            {
                "title": "Dossier rumeur frontière Nord",
                "kind": "rumor_dossier",
                "source_id": "src-rumor-frontier-nord-2026-05-25",
            },
        ]
        awaiting_to_clear = True
        extra["draft"] = draft
    elif handler == "voice_navigate_view":
        view = (manifest.input_schema or {}).get("default_view") or "cockpit"
        effects.append(_action_effect("assistant-navigate", {"route": f"/hypervisor/mission-room/{view}"}))
        content = f"J'ouvre la vue {view}."
    elif handler == "voice_confirm_yes":
        # Reached when ``voice.confirm_yes`` resolves but no awaiting
        # proposal is pending (the resolver swap only fires when an
        # ``awaiting`` bucket exists). Return a graceful no-op instead of
        # the stub "execution demo en attente de binding" placeholder so
        # the assistant stays demo-safe.
        content = "Monsieur le Vice Premier Ministre, je n'ai aucune proposition en attente. Que souhaitez-vous valider ?"
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
