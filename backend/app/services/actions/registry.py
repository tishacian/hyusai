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

    best: tuple[float, ActionManifest] | None = None
    for manifest in effective_action_manifests(
        workspace,
        surface=surface,
        assistant_profile=assistant_profile,
        system=system,
    ):
        score = _score_manifest(normalized, manifest)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, manifest)

    if not best or best[0] < min_confidence:
        return ActionResolution(False, confidence=best[0] if best else 0.0, reason="no_match")

    score, manifest = best
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
            best = max(best, 0.98)
        elif phrase_norm in text:
            best = max(best, 0.86)
        else:
            phrase_terms = set(phrase_norm.split())
            text_terms = set(text.split())
            if phrase_terms:
                overlap = len(phrase_terms.intersection(text_terms)) / len(phrase_terms)
                if overlap >= 0.75:
                    best = max(best, 0.72 + overlap * 0.1)
    return best


def _normalize(value: str) -> str:
    value = value.lower()
    replacements = str.maketrans("àâäéèêëîïôöùûüç’", "aaaeeeeiioouuuc'")
    value = value.translate(replacements)
    value = re.sub(r"[^a-z0-9\s'-]+", " ", value)
    value = value.replace("'", " ").replace("-", " ")
    return re.sub(r"\s+", " ", value).strip()


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
