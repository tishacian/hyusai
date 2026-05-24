"""Provider-neutral action manifests and resolution.

V1 intentionally keeps manifests in code and workspace/profile overrides in
``workspace.settings.actions``. This gives Agentium a transverse action model
without a migration and keeps AYA legacy handlers intact behind adapters.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any, Callable, Dict, Iterable, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.action_plans import handle_action_plan_chat_action
from app.services.audit_logger import emit_audit_event


Surface = str
HandlerKind = str


@dataclass(frozen=True)
class ActionHandler:
    kind: HandlerKind
    name: str
    route: Optional[str] = None


@dataclass(frozen=True)
class ActionManifest:
    action_id: str
    label: str
    description: str
    surfaces: tuple[Surface, ...]
    phrases: tuple[str, ...] = ()
    input_schema: Dict[str, Any] = field(default_factory=dict)
    required_permission: str = "action.execute"
    confirmation_policy: str = "confirm"
    handler: ActionHandler = field(default_factory=lambda: ActionHandler("flow_node", "noop"))
    audit_event: str = "action.executed"
    pack: str = "global_default_v1"
    capability_template: Optional[str] = None
    direct_safe: bool = False

    def to_payload(self, *, visible: bool = True, inherited_from: Optional[str] = None, demo_safe: bool = False) -> dict[str, Any]:
        payload = asdict(self)
        payload["visible"] = visible
        payload["inherited_from"] = inherited_from or self.pack
        payload["requires_confirmation"] = self.requires_confirmation
        if demo_safe:
            payload["handler"] = {"kind": "managed", "name": "managed"}
        return payload

    @property
    def requires_confirmation(self) -> bool:
        return not self.direct_safe and self.confirmation_policy != "direct_safe"


@dataclass(frozen=True)
class ActionResolution:
    matched: bool
    action_id: Optional[str] = None
    confidence: float = 0.0
    requires_confirmation: bool = False
    proposal: Optional[dict[str, Any]] = None
    reason: str = "no_match"
    manifest: Optional[ActionManifest] = None

    def to_payload(self, *, include_manifest: bool = True, demo_safe: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "matched": self.matched,
            "action_id": self.action_id,
            "confidence": self.confidence,
            "requires_confirmation": self.requires_confirmation,
            "proposal": self.proposal,
            "reason": self.reason,
        }
        if include_manifest and self.manifest:
            payload["manifest"] = self.manifest.to_payload(demo_safe=demo_safe)
        return payload


GLOBAL_VOICE_ACTIONS = (
    ActionManifest(
        action_id="voice.stop",
        label="Stop voice loop",
        description="Pause the active voice conversation loop.",
        surfaces=("voice", "chat"),
        phrases=("stop", "arrête", "on peut s'arrêter là", "fin de session"),
        required_permission="voice_runtime.read",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "voice_loop_stop"),
        audit_event="voice.command.stop",
        pack="global_voice_v1",
        capability_template="voice2voice_interaction",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="voice.repeat",
        label="Repeat last answer",
        description="Replay the last assistant answer through the selected voice output.",
        surfaces=("voice", "chat"),
        phrases=("répète", "repeat", "redis la réponse"),
        required_permission="voice_runtime.read",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "voice_repeat"),
        audit_event="voice.command.repeat",
        pack="global_voice_v1",
        capability_template="voice2voice_interaction",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="voice.rephrase",
        label="Rephrase last answer",
        description="Ask the assistant to rephrase its last answer.",
        surfaces=("voice", "chat"),
        phrases=("reformule", "rephrase", "plus court"),
        required_permission="voice_runtime.read",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "voice_rephrase"),
        audit_event="voice.command.rephrase",
        pack="global_voice_v1",
        capability_template="voice2voice_interaction",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="voice.confirm_yes",
        label="Confirm proposal",
        description="Confirm the active assistant proposal.",
        surfaces=("voice", "chat"),
        phrases=("oui", "yes", "valide", "d'accord", "daccord", "confirme", "confirmes", "ok", "vas y", "vas-y", "allons y"),
        required_permission="voice_runtime.read",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "voice_confirm_yes"),
        audit_event="voice.command.confirm_yes",
        pack="global_voice_v1",
        capability_template="voice2voice_interaction",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="voice.confirm_no",
        label="Decline proposal",
        description="Decline the active assistant proposal.",
        surfaces=("voice", "chat"),
        phrases=("non", "no", "annule", "annuler", "pas maintenant", "later", "stop", "laisse tomber"),
        required_permission="voice_runtime.read",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "awaiting_declined"),
        audit_event="voice.command.confirm_no",
        pack="global_voice_v1",
        capability_template="voice2voice_interaction",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="voice.navigate_view",
        label="Navigate workspace view",
        description="Navigate to a mission-room or workspace view.",
        surfaces=("voice", "chat", "ui"),
        phrases=("ouvre le cockpit", "ouvre la carte", "ouvre l'agenda", "ouvre la presse", "ouvre les arbitrages", "go cockpit", "go map"),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "voice_navigate_view"),
        audit_event="voice.command.navigate",
        pack="global_voice_v1",
        capability_template="voice2voice_interaction",
        direct_safe=True,
    ),
)


ANDRITZ_ACTIONS = (
    ActionManifest(
        action_id="andritz.find_parameter_value",
        label="Find a value",
        description="Find a sourced business parameter value in Andritz Knowledge.",
        surfaces=("chat", "voice", "flow"),
        phrases=("trouve la valeur", "retrouve le diamètre", "retrouver le diamètre", "à combien correspond", "find the value"),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "rag_find_parameter_value"),
        audit_event="action.andritz.find_parameter_value",
        pack="andritz_industrial_v1",
        capability_template="expert_knowledge_capture",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="andritz.locate_evidence_table",
        label="Locate the table",
        description="Locate the source file, sheet, row or section that supports an answer.",
        surfaces=("chat", "voice", "flow"),
        phrases=("localise la table", "retrouve la feuille", "cite la ligne", "locate the table"),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "rag_locate_evidence_table"),
        audit_event="action.andritz.locate_evidence_table",
        pack="andritz_industrial_v1",
        capability_template="expert_knowledge_capture",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="andritz.flag_evidence_gap",
        label="Flag evidence gap",
        description="Create a reviewable note that the current answer lacks enough evidence.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=("preuve insuffisante", "manque de preuve", "evidence gap", "signale un manque"),
        required_permission="action.execute",
        confirmation_policy="confirm",
        handler=ActionHandler("flow_node", "flag_evidence_gap"),
        audit_event="action.andritz.evidence_gap.flagged",
        pack="andritz_industrial_v1",
        capability_template="expert_knowledge_capture",
    ),
    ActionManifest(
        action_id="andritz.start_capture_session",
        label="Start capture session",
        description="Open or start an Expert Knowledge Capture session.",
        surfaces=("chat", "voice", "ui", "knowledge_capture", "flow"),
        phrases=("démarre une capture", "lance une session de capture", "start capture session"),
        required_permission="capture_session.create",
        confirmation_policy="confirm",
        handler=ActionHandler("backend_route", "knowledge_capture_start", "/api/v1/knowledge-capture"),
        audit_event="action.andritz.capture.start_requested",
        pack="andritz_industrial_v1",
        capability_template="expert_knowledge_capture",
    ),
    ActionManifest(
        action_id="andritz.next_capture_question",
        label="Next capture question",
        description="Move to the next planned Knowledge Capture question.",
        surfaces=("voice", "knowledge_capture", "flow"),
        phrases=("question suivante", "suivant", "next question"),
        required_permission="capture_session.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "knowledge_capture_next_question"),
        audit_event="action.andritz.capture.next_question",
        pack="andritz_industrial_v1",
        capability_template="expert_knowledge_capture",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="andritz.validate_capture_answer",
        label="Validate capture answer",
        description="Validate the current Knowledge Capture answer.",
        surfaces=("voice", "knowledge_capture", "flow"),
        phrases=("valider", "valide la réponse", "confirm answer"),
        required_permission="capture_session.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "knowledge_capture_validate_answer"),
        audit_event="action.andritz.capture.answer_validated",
        pack="andritz_industrial_v1",
        capability_template="expert_knowledge_capture",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="andritz.promote_deposit_file",
        label="Promote deposit file",
        description="Promote a staged Secure Deposit file into Knowledge.",
        surfaces=("ui", "flow"),
        phrases=("promouvoir le fichier", "promote deposit file"),
        required_permission="deposit_file.promote",
        confirmation_policy="confirm",
        handler=ActionHandler("backend_route", "secure_deposit_promote", "/api/v1/sftp/deposits/{file_id}/promote"),
        audit_event="action.andritz.deposit.promote_requested",
        pack="andritz_industrial_v1",
        capability_template="secure_deposit",
    ),
)


SENTINEL_AYA_ACTIONS = (
    ActionManifest(
        action_id="aya.acknowledge_presence",
        label="Acknowledge presence",
        description="Reply to a bare AYA wake word with a short presence acknowledgement.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "aya",
            "aya tu m entends",
            "aya tu es la",
            "aya presente",
            "aya ecoute",
            "aya tu es presente",
            "ok aya",
            "hey aya",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "acknowledge_presence"),
        audit_event="action.aya.acknowledge_presence",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.action_plan_status",
        label="Action plan status",
        description="List active cabinet action items for AYA.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=("liste les actions", "statut des actions", "suivi cabinet", "résume les actions"),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("legacy_adapter", "action_plans"),
        audit_event="action.aya.action_plan.status",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.action_plan_create",
        label="Create cabinet action",
        description="Create or propose a cabinet action item using AYA's existing action-plan handler.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=("crée une action", "ajoute une action", "planifie une action", "prépare une action"),
        required_permission="action.execute",
        confirmation_policy="confirm",
        handler=ActionHandler("legacy_adapter", "action_plans"),
        audit_event="action.aya.action_plan.create",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
    ),
    ActionManifest(
        action_id="aya.action_plan_cancel",
        label="Cancel cabinet action",
        description="Cancel a cabinet action item using AYA's existing action-plan handler.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=("annule l'action", "annuler action", "cancel action"),
        required_permission="action.execute",
        confirmation_policy="confirm",
        handler=ActionHandler("legacy_adapter", "action_plans"),
        audit_event="action.aya.action_plan.cancel",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
    ),
    ActionManifest(
        action_id="aya.action_plan_complete",
        label="Complete cabinet action",
        description="Mark a cabinet action item complete using AYA's existing action-plan handler.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=("termine l'action", "marque l'action terminée", "complete action"),
        required_permission="action.execute",
        confirmation_policy="confirm",
        handler=ActionHandler("legacy_adapter", "action_plans"),
        audit_event="action.aya.action_plan.complete",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
    ),
    ActionManifest(
        action_id="aya.map_focus",
        label="Focus map",
        description="Focus the Sentinel-CI mission map on a layer, zone or evidence object.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=("filtre la carte", "ouvre la carte", "focus carte", "active la couche"),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "mission_room_map_focus"),
        audit_event="action.aya.map.focus",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.evidence_explain",
        label="Explain evidence",
        description="Explain the active Sentinel-CI evidence with sources.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=("explique cette preuve", "origine rumeur", "preuve active"),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "mission_room_evidence_explain"),
        audit_event="action.aya.evidence.explain",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.priority_summary",
        label="Priority briefing",
        description="Summarize cockpit priorities for the Vice-President.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "resume des priorites",
            "résumé des priorités",
            "resume sujets prioritaires",
            "résumé sujets prioritaires",
            "fais moi un resume des sujets prioritaires",
            "fais-moi un résumé des sujets prioritaires",
            "quels sont les sujets prioritaires",
            "priorites du jour",
            "priorités du jour",
            "briefing priorites",
            # Cockpit 60-secondes voice/chat openers (previously hardcoded
            # under ``is_cockpit`` in chat.py — moved here so the resolver
            # owns the route into the briefing skill).
            "cockpit 60 secondes",
            "lecture 60 secondes",
            "lecture en 60 secondes",
            "donne moi le cockpit",
            "donne-moi le cockpit",
            "donne moi le cockpit 60 secondes",
            "donne-moi le cockpit 60 secondes",
            "que dois je faire",
            "que dois-je faire",
            "quoi faire ce matin",
            # Briefing matin / nom-propre Napié — sans avaler les briefs
            # opérationnels qui ciblent un projet (focus_zone_with_project).
            "brief matinal",
            "point matinal",
            "point matinal napie",
            "point matinal napié",
            "qu est ce qui touche napie",
            "qu'est-ce qui touche napié",
            # Anglicisme layer (briefing executive bilingue).
            "morning briefing",
            "daily briefing",
            "give me the briefing",
            "give me my morning briefing",
            "give me the cockpit",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "briefing_priorities_v1"),
        audit_event="action.aya.priority_summary",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.focus_zone_with_project",
        label="Focus zone with project",
        description="Focus the map on Nord and highlight the delayed public project.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "zoom nord",
            "zoom sur la region nord",
            "zoom sur la région nord",
            "projet public en retard",
            "composants importes",
            "composants importés",
            "focus zone nord projet",
            "pointe un projet public en retard",
            # "Brief opérationnel · Projet sensible Nord" card prompts —
            # route to the project-focused map drill so the cockpit shows
            # Centre Drones Napié + cargo Aerostar + 120 j de retard.
            "brief operationnel projet",
            "brief opérationnel projet",
            "brief operationnel projet nord",
            "brief opérationnel projet nord",
            "brief operationnel pour projet nord",
            "brief opérationnel pour projet nord",
            "brief operationnel projet sensible",
            "brief opérationnel projet sensible",
            "brief operationnel projet sensible nord",
            "brief opérationnel projet sensible nord",
            "projet sensible nord",
            "projet sensible · nord",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "map_focus_zone_with_project"),
        audit_event="action.aya.focus_zone_with_project",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.show_maritime_traffic",
        label="Show maritime traffic",
        description="Show Abidjan maritime traffic and linked cargo.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "trafic maritime abidjan",
            "trafic maritime à abidjan",
            "trafic maritime a destination d'abidjan",
            "montre le trafic maritime",
            "navires abidjan",
            "cargaison abidjan",
            "maritime abidjan",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "show_maritime_traffic"),
        audit_event="action.aya.show_maritime_traffic",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.show_vessel_evidence",
        label="Show vessel evidence",
        description="Focus the maritime panel on the MV Atlantic Trader cargo and propose the customs PV preview.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "montre le navire",
            "montre le cargo",
            "voir flux entree port",
            "ouvre la webcam port",
            "voir le navire mv",
            "voir le navire mv atlantic trader",
            "montre le navire mv atlantic trader",
            # NB: bare "atlantic trader" is intentionally absent so the
            # tie-breaker in ``resolve_action`` can route customs queries
            # mentioning the vessel name to ``aya.show_customs_record`` /
            # ``aya.draft_customs_email``. The verb+vessel forms below
            # still cover the AIS pin path.
            "ouvre le cargo mv",
            "trafic mv atlantic trader",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "show_vessel_evidence"),
        audit_event="action.aya.show_vessel_evidence",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.show_customs_record",
        label="Show customs record",
        description="Open the customs PV (OCR cited) and surface AYA citation page.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "montre le pv",
            "montre le pv douanes",
            "voir le pv des douanes",
            "ouvre le pv douanes",
            "document douanes",
            "proces verbal douanes",
            "pv 18 mai",
            "c est quoi le pv des douanes",
            "qu est ce que dit le pv douanes",
            # Ultra-courts (≤ 4 mots).
            "voir pv",
            "voir le pv",
            "pv douanes",
            "pv",
            "le pv",
            # Anglicismes critiques.
            "show me the customs report",
            "show the customs pv",
            "customs report",
            "show customs record",
            # Tie-breaker — quand la requête mentionne explicitement le
            # navire MV Atlantic Trader avec un verbe douanes, on garde
            # ``aya.show_customs_record`` plutôt que de router vers
            # ``aya.show_vessel_evidence``.
            "atlantic trader pv",
            "pv atlantic trader",
            "pv mv atlantic trader",
            "pv du 18 mai sur atlantic trader",
            "le pv du 18 mai sur atlantic trader",
            "pv atlantic trader 18 mai",
            "atlantic trader proces verbal",
            "atlantic trader procès verbal",
            "proces verbal atlantic trader",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "show_customs_record"),
        audit_event="action.aya.show_customs_record",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.explain_why",
        label="Explain why (causal drill)",
        description="Chain a causal explanation by following caused_by edges in the evidence graph.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "pourquoi",
            "explique pourquoi",
            "explique moi pourquoi",
            "qu'est ce qui cause",
            "qu'est-ce qui cause",
            "pourquoi cette tension",
            "pourquoi la situation est tendue",
            "pourquoi la situation est-elle tendue",
            "pourquoi la situation nord est tendue",
            "pourquoi la situation nord est-elle tendue",
            "pourquoi ce projet est en retard",
            "pourquoi ce projet est-il en retard",
            "pourquoi cette cargaison est bloquee",
            "pourquoi cette cargaison est-elle bloquee",
            "pourquoi cette cargaison est bloquée",
            "pourquoi cette cargaison est-elle bloquée",
            "pourquoi le nord",
            "pourquoi le nord est tendu",
            # Non-"pourquoi" Nord situational queries — drill into the
            # causal chain (zone-nord → Napié → cargo → PV douanes) so AYA
            # stays on the Napié narrative instead of falling back to a
            # generic 3-signals reply.
            "quelle est la situation au nord",
            "quelle est la situation au nord en ce moment",
            "situation au nord",
            "situation au nord en ce moment",
            "que se passe t il au nord",
            "que se passe-t-il au nord",
            "etat de la zone nord",
            "état de la zone nord",
            # Ultra-courts ≤ 4 mots et formes orales familières.
            "pourquoi nord",
            "pourquoi situation nord",
            "pourquoi le nord tendu",
            "pourquoi nord tendu",
            "c est quoi qui cloche au nord",
            "c'est quoi qui cloche au nord",
            "qu est ce qui cloche au nord",
            "qu'est-ce qui cloche au nord",
            "qu est ce qui ne va pas dans le nord",
            "qu'est-ce qui ne va pas dans le nord",
            "c est quoi le souci au nord",
            "c'est quoi le souci au nord",
            # Anglicisme layer.
            "why north",
            "why is the north tense",
            "why is the north situation tense",
            "why is the situation tense",
            "why is the north",
            "what is happening in the north",
            "what s wrong in the north",
            "what's wrong in the north",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "explain_why"),
        audit_event="action.aya.explain_why",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.update_meeting_agenda",
        label="Update meeting agenda",
        description="Propose adding or updating agenda items on the next institutional meeting.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "ajoute a l'ordre du jour",
            "ajoute à l'ordre du jour",
            "ajoute le point cacao au meeting",
            "ajoute le point cacao",
            "mets a jour le rdv",
            "mets à jour le rdv",
            "mets a jour l'ordre du jour",
            "mets à jour l'ordre du jour",
            "propose cet arbitrage au prefet",
            "propose cet arbitrage au préfet",
        ),
        required_permission="action.execute",
        confirmation_policy="confirm",
        handler=ActionHandler("flow_node", "update_meeting_agenda"),
        audit_event="action.aya.update_meeting_agenda",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
    ),
    ActionManifest(
        action_id="aya.confirm_agenda_patch",
        label="Confirm pending agenda patch",
        description="Apply the pending calendar agenda items patch staged by AYA.",
        surfaces=("chat", "voice", "flow"),
        phrases=(
            "valide la mise a jour de l'ordre du jour",
            "valide la mise à jour de l'ordre du jour",
            "applique l'ordre du jour",
            "patch agenda",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "confirm_agenda_patch"),
        audit_event="action.aya.confirm_agenda_patch",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.start_meeting",
        label="Start meeting",
        description="Navigate to the live meeting view of the next scheduled institutional event.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "demarre la reunion",
            "démarre la réunion",
            "demarrer la reunion",
            "démarrer la réunion",
            "commence la reunion",
            "commence la réunion",
            "ouvre le meeting",
            "lance la reunion",
            "lance la réunion",
            # Ultra-courts ≤ 4 mots + formes orales familières.
            "on commence",
            "on commence le meeting",
            "on commence la reunion",
            "on commence la réunion",
            "on y va",
            "c est parti",
            "c'est parti",
            "go meeting",
            # Anglicisme layer.
            "start meeting",
            "start the meeting",
            "kick off the meeting",
            "kickoff the meeting",
            "let s start the meeting",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "start_meeting"),
        audit_event="action.aya.start_meeting",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.log_decision",
        label="Log meeting decision",
        description="Persist an arbitration decision on the currently active meeting.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "valide l'option",
            "valide option",
            "choisis l'option",
            "choisir l'option",
            "decide option",
            "décide option",
            "j'arbitre option",
            "arbitre option",
            "log la decision",
            "log la décision",
        ),
        required_permission="action.execute",
        confirmation_policy="confirm",
        handler=ActionHandler("flow_node", "log_decision"),
        audit_event="action.aya.log_decision",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
    ),
    ActionManifest(
        action_id="aya.recall_past_decisions",
        label="Recall past meeting decisions",
        description="Recall past arbitration decisions logged on meetings (RAG over meeting_decisions).",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "qu'avons nous decide",
            "qu'avons-nous décidé",
            "que avons nous decide",
            "qu'avons nous decide la derniere fois",
            "qu'avons-nous décidé la dernière fois",
            "rappelle moi nos decisions",
            "rappelle-moi nos décisions",
            "decisions passees",
            "décisions passées",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "recall_past_decisions"),
        audit_event="action.aya.recall_past_decisions",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.propose_customs_email",
        label="Propose customs email",
        description="Propose drafting a customs prioritization email.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "propose un mail dedouanement",
            "proposer courrier dedouanement",
            "mail douanes",
            # Forme orale familière.
            "on prepare un email aux douanes",
            "on prépare un email aux douanes",
            "on prepare un mail douanes",
            "on prépare un mail douanes",
            "il faut un courrier douanes",
            "prepare un courrier douanes",
            "prépare un courrier douanes",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "propose_customs_email"),
        audit_event="action.aya.propose_customs_email",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.draft_customs_email",
        label="Draft customs email",
        description="Draft the customs prioritization email for Nord cargo.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "redige le mail dedouanement",
            "rédige le mail dédouanement",
            "brouillon douanes",
            # Ultra-courts ≤ 4 mots.
            "email derogation",
            "email dérogation",
            "mail derogation",
            "mail dérogation",
            "courrier derogation",
            "courrier dérogation",
            "redige courrier dedouanement",
            "rédige courrier dédouanement",
            "redige un courrier dedouanement",
            "rédige un courrier de dédouanement",
            # Anglicisme layer.
            "draft a customs email",
            "draft a customs clearance email",
            "customs clearance email",
            "draft customs email",
            # Tie-breaker explicite — quand la requête mentionne le navire.
            "atlantic trader email",
            "atlantic trader derogation",
            "atlantic trader dérogation",
            "courrier dedouanement atlantic trader",
            "courrier de dedouanement pour atlantic trader",
            "courrier de dédouanement pour atlantic trader",
            "redige un courrier de dedouanement pour atlantic trader",
            "rédige un courrier de dédouanement pour atlantic trader",
            "email derogation atlantic trader",
            "email dérogation atlantic trader",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "draft_customs_email"),
        audit_event="action.aya.draft_customs_email",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.open_next_meeting",
        label="Open next meeting",
        description="Navigate to agenda and highlight the next meeting.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "prochain rdv",
            "prochain rendez-vous",
            "quel est mon prochain rdv",
            "mon prochain rendez vous",
            "prochaine reunion",
            "prochaine réunion",
            "ok aya quel est mon prochain rdv",
            "c est quoi mon prochain rendez vous",
            "c'est quoi mon prochain rendez-vous",
            # Ultra-courts ≤ 4 mots.
            "rdv",
            "quoi maintenant",
            "et apres",
            "et après",
            "what s next",
            "what's next",
            # Anglicisme layer.
            "next meeting",
            "what s my next meeting",
            "what's my next meeting",
            "what is my next meeting",
            "whats my next meeting",
            "my next meeting",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "open_next_meeting"),
        audit_event="action.aya.open_next_meeting",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.summarize_last_exchanges",
        label="Summarize last exchanges",
        description="Summarize the Prefet Nawa report and recent exchanges.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "derniers echanges",
            "derniers échanges",
            "quels ont ete les derniers echanges",
            "quels ont été les derniers échanges",
            "resume du rapport prefet",
            "résumé du rapport préfet",
            "rapport prefet nawa",
            "résume-moi le rapport du préfet",
            "resume moi le rapport du prefet",
            # Ultra-courts ≤ 4 mots.
            "resume prefet",
            "résume préfet",
            "resume nawa",
            "résume nawa",
            "resume prefet nawa",
            "résume préfet nawa",
            "resume le prefet",
            "résume le préfet",
            "resume du prefet",
            "résume du préfet",
            "resume rapport",
            "résume rapport",
            "résumé prefet nawa",
            "résumé nawa",
            # Anglicisme layer.
            "summarize the prefect s report",
            "summarize the prefect report",
            "summarize the prefet report",
            "summarize prefect nawa",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "summarize_last_exchanges"),
        audit_event="action.aya.summarize_last_exchanges",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.recommend_cacao",
        label="Recommend cacao options",
        description="Generate sourced cacao diversification recommendations.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "preconisations cacao",
            "préconisations cacao",
            "recommandations cacao",
            "donne moi des preconisations sur le cacao",
            "donne-moi des préconisations sur le cacao",
            "diversification cacao",
            "options de diversification cacao",
            # Ultra-courts ≤ 4 mots et formes orales familières.
            "preco cacao",
            "préco cacao",
            "cacao",
            "diversifier cacao",
            "diversifier le cacao",
            "t as des idees pour diversifier le cacao",
            "t'as des idées pour diversifier le cacao",
            # Anglicisme layer.
            "cacao diversification recommendations",
            "cocoa diversification recommendations",
            "cocoa recommendations",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "recommend_cacao"),
        audit_event="action.aya.recommend_cacao",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.draft_strategic_report",
        label="Draft strategic report",
        description="Draft the long-form cacao diversification report.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "rapport diversification",
            "rapport strategique cacao",
            "rapport stratégique cacao",
            "rapport complet",
            "le rapport complet",
            "genere le rapport",
            "génère le rapport",
            "genere le rapport complet",
            "génère le rapport complet",
            "prepare le rapport complet",
            "prépare le rapport complet",
            "genere le rapport strategique",
            "génère le rapport stratégique",
            "produit le rapport",
            "produis le rapport",
            "donne moi le rapport complet",
            "donne-moi le rapport complet",
        ),
        required_permission="action.execute",
        confirmation_policy="direct_safe",
        handler=ActionHandler("flow_node", "draft_strategic_report"),
        audit_event="action.aya.draft_strategic_report",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
        direct_safe=True,
    ),
    ActionManifest(
        action_id="aya.schedule_meeting",
        label="Schedule meeting",
        description="Propose a calendar slot with the Economy minister.",
        surfaces=("chat", "voice", "ui", "flow"),
        phrases=(
            "cale un rdv",
            "caler rdv ministre economie",
            "caler rdv ministre économie",
            "rdv ministre de l'economie",
            "rdv ministre de l'économie",
            "planifier reunion ministre",
        ),
        required_permission="action.execute",
        confirmation_policy="confirm",
        handler=ActionHandler("flow_node", "schedule_meeting"),
        audit_event="action.aya.schedule_meeting",
        pack="sentinel_ci_aya_v1",
        capability_template="aya_voice_command",
    ),
)


PACKS: Dict[str, tuple[ActionManifest, ...]] = {
    "global_voice_v1": GLOBAL_VOICE_ACTIONS,
    "andritz_industrial_v1": ANDRITZ_ACTIONS,
    "sentinel_ci_aya_v1": SENTINEL_AYA_ACTIONS,
}


def all_action_manifests() -> list[ActionManifest]:
    manifests: list[ActionManifest] = []
    for pack in PACKS.values():
        manifests.extend(pack)
    return manifests


def effective_action_manifests(
    workspace: Workspace,
    *,
    surface: Optional[str] = None,
    assistant_profile: Optional[str] = None,
    system: Optional[System] = None,
) -> list[ActionManifest]:
    settings = workspace.settings or {}
    action_settings = _as_dict(settings.get("actions"))
    packs = ["global_voice_v1"]
    packs.extend(_capability_template_packs(settings))
    packs.extend(_workspace_default_packs(workspace))
    packs.extend(_list(action_settings.get("enabled_packs")))
    packs.extend(_assistant_profile_packs(settings, assistant_profile))
    packs.extend(_system_action_packs(system))

    hidden_packs = set(_list(action_settings.get("hidden_packs")))
    hidden_actions = set(_list(action_settings.get("hidden_actions")))
    explicit_actions = set(_list(action_settings.get("enabled_actions")))

    resolved: dict[str, ActionManifest] = {}
    for pack_name in packs:
        if pack_name in hidden_packs:
            continue
        for manifest in PACKS.get(pack_name, ()):
            if manifest.action_id in hidden_actions:
                continue
            resolved[manifest.action_id] = manifest

    for manifest in all_action_manifests():
        if manifest.action_id in explicit_actions and manifest.action_id not in hidden_actions:
            resolved[manifest.action_id] = manifest

    manifests = list(resolved.values())
    if surface:
        manifests = [manifest for manifest in manifests if surface in manifest.surfaces]
    return sorted(manifests, key=lambda item: (item.pack, item.label))


def resolve_action(
    workspace: Workspace,
    *,
    text: str,
    surface: str = "chat",
    assistant_profile: Optional[str] = None,
    system: Optional[System] = None,
    min_confidence: float = 0.78,
) -> ActionResolution:
    normalized = _normalize(text)
    if not normalized:
        return ActionResolution(False, reason="empty_text")
    # Strip the AYA wake-word at the start or end so phrases like
    # "AYA, donne-moi le brief" match exactly the same actions as the
    # raw "donne-moi le brief". The bare wake-word ("aya", "aya ?",
    # "aya tu m'entends") still resolves through the dedicated
    # ``aya.acknowledge_presence`` phrase set.
    normalized = _strip_wake_word(normalized)
    if not normalized:
        return ActionResolution(False, reason="empty_text")

    scored: list[tuple[float, ActionManifest]] = []
    for manifest in effective_action_manifests(
        workspace,
        surface=surface,
        assistant_profile=assistant_profile,
        system=system,
    ):
        score = _score_manifest(normalized, manifest)
        if score <= 0:
            continue
        scored.append((score, manifest))

    if not scored:
        return ActionResolution(False, confidence=0.0, reason="no_match")

    scored.sort(key=lambda item: item[0], reverse=True)
    score, manifest = _apply_tie_breakers(normalized, scored)

    if score < min_confidence:
        return ActionResolution(False, confidence=score, reason="no_match")

    return ActionResolution(
        True,
        action_id=manifest.action_id,
        confidence=round(score, 3),
        requires_confirmation=manifest.requires_confirmation,
        proposal={
            "action_id": manifest.action_id,
            "label": manifest.label,
            "description": manifest.description,
            "surface": surface,
            "text": text,
        },
        reason="matched",
        manifest=manifest,
    )


_CUSTOMS_HINT_RE = re.compile(
    r"\b(?:pv|proces\s*verbal|dedouanement|derogation|courrier|email|mail|douanes|customs)\b"
)


def _apply_tie_breakers(
    normalized: str,
    scored: list[tuple[float, ActionManifest]],
) -> tuple[float, ActionManifest]:
    """Apply small priority rules on top of the raw score ranking.

    Rule 1 — vessel vs customs disambiguation: if the top-scoring action
    is ``aya.show_vessel_evidence`` but the query contains an explicit
    customs verb (PV, procès-verbal, dédouanement, dérogation, courrier,
    email, mail, douanes, customs) and a customs action also matched
    above the same threshold, prefer the customs action so the demo
    stays on the douanes narrative.
    """

    if not scored:
        raise ValueError("scored must contain at least one element")
    top_score, top_manifest = scored[0]
    if top_manifest.action_id != "aya.show_vessel_evidence":
        return top_score, top_manifest
    if not _CUSTOMS_HINT_RE.search(normalized):
        return top_score, top_manifest
    customs_action_ids = {"aya.show_customs_record", "aya.draft_customs_email", "aya.propose_customs_email"}
    for score, manifest in scored:
        if manifest.action_id in customs_action_ids:
            return score, manifest
    return top_score, top_manifest


def execute_action(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    action_id: str,
    text: str = "",
    surface: str = "chat",
    assistant_profile: Optional[str] = None,
    confirm: bool = False,
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    manifest = next((item for item in effective_action_manifests(workspace, surface=surface, assistant_profile=assistant_profile) if item.action_id == action_id), None)
    if not manifest:
        audit_id = _audit(db, workspace, user, "action.denied", {"action_id": action_id, "surface": surface, "reason": "not_visible"})
        return {
            "matched": False,
            "action_id": action_id,
            "confidence": 0.0,
            "requires_confirmation": False,
            "proposal": None,
            "result": None,
            "audit_id": audit_id,
            "reason": "not_visible",
        }

    proposal = {
        "action_id": manifest.action_id,
        "label": manifest.label,
        "description": manifest.description,
        "surface": surface,
        "payload": payload or {},
    }
    if manifest.requires_confirmation and not confirm:
        audit_id = _audit(db, workspace, user, "action.proposed", proposal)
        return {
            "matched": True,
            "action_id": manifest.action_id,
            "confidence": 1.0,
            "requires_confirmation": True,
            "proposal": proposal,
            "result": None,
            "audit_id": audit_id,
            "reason": "confirmation_required",
        }

    if manifest.handler.kind == "legacy_adapter" and manifest.handler.name == "action_plans":
        result = handle_action_plan_chat_action(
            db,
            workspace,
            user,
            query=text,
            assistant_profile=assistant_profile or "vigie_executive",
        )
        audit_id = _audit(db, workspace, user, manifest.audit_event, {"action_id": manifest.action_id, "result": result})
        return {
            "matched": bool(result),
            "action_id": manifest.action_id,
            "confidence": 1.0,
            "requires_confirmation": manifest.requires_confirmation,
            "proposal": proposal if not result else result.get("proposal"),
            "result": result,
            "audit_id": audit_id,
            "reason": "executed" if result else "legacy_adapter_no_result",
        }

    audit_id = _audit(db, workspace, user, manifest.audit_event, {"action_id": manifest.action_id, "payload": payload or {}, "surface": surface})
    return {
        "matched": True,
        "action_id": manifest.action_id,
        "confidence": 1.0,
        "requires_confirmation": manifest.requires_confirmation,
        "proposal": proposal,
        "result": {
            "action": manifest.action_id,
            "applied": False,
            "content": f"Action proposée : {manifest.label}.",
            "handler": asdict(manifest.handler),
        },
        "audit_id": audit_id,
        "reason": "proposed",
    }


def handle_transverse_chat_action(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    query: str,
    assistant_profile: Optional[str],
) -> Optional[dict[str, Any]]:
    """Resolve chat actions while preserving AYA's legacy behavior.

    Only legacy adapters return a chat response in V1. Knowledge-oriented
    actions are exposed for UI/Voice/Flow and still let normal RAG answer.
    """

    resolution = resolve_action(workspace, text=query, surface="chat", assistant_profile=assistant_profile)
    if resolution.matched and resolution.manifest and resolution.manifest.handler.kind == "legacy_adapter":
        result = execute_action(
            db,
            workspace,
            user,
            action_id=resolution.manifest.action_id,
            text=query,
            surface="chat",
            assistant_profile=assistant_profile,
            confirm=not resolution.manifest.requires_confirmation,
        )
        if result.get("reason") == "confirmation_required":
            proposal = result.get("proposal") or {}
            return {
                "action": "action_plan_proposal",
                "applied": False,
                "content": (
                    f"Action proposée : {proposal.get('label') or resolution.manifest.label}. "
                    "Validation requise avant application."
                ),
                "proposal": proposal,
                "requires_confirmation": True,
                "action_manifest_id": resolution.manifest.action_id,
                "action_confidence": resolution.confidence,
            }
        legacy_result = result.get("result")
        if legacy_result:
            legacy_result.setdefault("action_manifest_id", resolution.manifest.action_id)
            legacy_result.setdefault("action_confidence", resolution.confidence)
            return legacy_result

    # Compatibility fallback for exact AYA behavior while actions roll out.
    return handle_action_plan_chat_action(
        db,
        workspace,
        user,
        query=query,
        assistant_profile=assistant_profile,
    )


def _workspace_default_packs(workspace: Workspace) -> list[str]:
    slug = (workspace.slug or "").lower()
    name = (workspace.name or "").lower()
    settings = workspace.settings or {}
    catalog = _as_dict(settings.get("catalog") or settings.get("capability_catalog"))
    enabled_caps = set(_list(catalog.get("enabled_capabilities")))
    packs: list[str] = []
    if "andritz" in slug or "andritz" in name:
        packs.append("andritz_industrial_v1")
    if "sentinel" in slug or "sentinel" in name or "aya_voice_command" in enabled_caps:
        packs.append("sentinel_ci_aya_v1")
    return packs


def _capability_template_packs(settings: dict[str, Any]) -> list[str]:
    catalog = _as_dict(settings.get("catalog") or settings.get("capability_catalog"))
    enabled_caps = set(_list(catalog.get("enabled_capabilities")))
    packs: list[str] = []
    if "voice2voice_interaction" in enabled_caps:
        packs.append("global_voice_v1")
    if "aya_voice_command" in enabled_caps:
        packs.append("sentinel_ci_aya_v1")
    if "expert_knowledge_capture" in enabled_caps or "secure_deposit" in enabled_caps:
        packs.append("andritz_industrial_v1")
    return packs


def _assistant_profile_packs(settings: dict[str, Any], assistant_profile: Optional[str]) -> list[str]:
    if not assistant_profile:
        return []
    profiles = settings.get("assistant_profiles")
    if not isinstance(profiles, list):
        return []
    for profile in profiles:
        if not isinstance(profile, dict) or profile.get("key") != assistant_profile:
            continue
        actions = _as_dict(profile.get("actions"))
        packs = _list(actions.get("enabled_packs") or profile.get("action_packs"))
        return packs
    return []


def _system_action_packs(system: Optional[System]) -> list[str]:
    if not system:
        return []
    profile = system.execution_profile if isinstance(system.execution_profile, dict) else {}
    actions = _as_dict(profile.get("actions"))
    return _list(actions.get("enabled_packs") or actions.get("action_packs"))


def _score_manifest(text: str, manifest: ActionManifest) -> float:
    best = 0.0
    for phrase in manifest.phrases:
        phrase_norm = _normalize(phrase)
        if not phrase_norm:
            continue
        if text == phrase_norm:
            score = 0.98
        elif phrase_norm in text:
            if len(phrase_norm.split()) == 1 and len(phrase_norm) <= 3:
                if not re.search(rf"(?<![a-z0-9]){re.escape(phrase_norm)}(?![a-z0-9])", text):
                    continue
            score = 0.86
        else:
            phrase_terms = set(phrase_norm.split())
            text_terms = set(text.split())
            if phrase_terms:
                overlap = len(phrase_terms.intersection(text_terms)) / len(phrase_terms)
                if overlap >= 0.75:
                    score = 0.72 + overlap * 0.1
                else:
                    continue
            else:
                continue
        score += min(len(phrase_norm.split()) * 0.015, 0.08)
        best = max(best, score)
    return best


def _normalize(value: str) -> str:
    value = value.lower()
    replacements = str.maketrans("àâäéèêëîïôöùûüç’", "aaaeeeeiioouuuc'")
    value = value.translate(replacements)
    value = re.sub(r"[^a-z0-9\s'-]+", " ", value)
    value = value.replace("'", " ").replace("-", " ")
    return re.sub(r"\s+", " ", value).strip()


_WAKE_WORD_ACK_PHRASES = frozenset(
    {
        "aya",
        "aya tu m entends",
        "aya tu es la",
        "aya presente",
        "aya ecoute",
        "aya tu es presente",
        "ok aya",
        "hey aya",
    }
)


def _strip_wake_word(text: str) -> str:
    """Strip the AYA wake word anywhere in the normalized query.

    The bare acknowledgements ("aya", "aya tu m entends", ...) are kept
    intact so the dedicated ``aya.acknowledge_presence`` manifest still
    matches them. Otherwise every standalone "aya" token (and the
    optional "ok"/"hey" leading particles) is dropped so phrases like
    ``aya donne moi le brief``, ``donne moi le brief aya`` and
    ``pourquoi aya situation nord`` score like the raw query without
    polluting the matching pipeline.
    """

    if not text:
        return text
    if text in _WAKE_WORD_ACK_PHRASES:
        return text
    stripped = re.sub(r"\b(?:ok|hey)\s+aya\b", " ", text)
    stripped = re.sub(r"\baya\b", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip(" ,.:!?-")
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped or text


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    return []


def _audit(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    event_type: str,
    details: dict[str, Any],
) -> Optional[str]:
    return emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=event_type,
        actor=(user.email or user.username or user.id) if user else "system",
        details=details,
    )
