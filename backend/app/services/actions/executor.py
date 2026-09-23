"""Flow-node action executors and awaiting-state handling for Agentium registry."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session as DBSession

from app.models.system import System
from app.models.user import User
from app.models.workspace import Workspace
from app.services.actions.contracts import ActionPack
from app.services.actions.registry import (
    ActionManifest,
    ActionResolution,
    effective_action_manifests,
    resolve_action,
)
from app.services.audit_logger import emit_audit_event
from app.services.iam.app_entitlements import (
    lock_workspace_for_app_entitlement_mutation,
)
from app.services.iam.decision_plane import resolve_manifest_permission
from app.services.mission_room import present_payload_for_workspace
from app.services.skills_registry import wrappers as skill_wrappers

_SENTINEL_ACTION_PACKS = frozenset(
    {
        ActionPack.sentinel_ci_aya_v1.value,
        ActionPack.sentinel_ci_aya_security_v1.value,
    }
)
_OCTAVE_ACTION_PACKS = frozenset(
    {
        ActionPack.octave_mission_room_v1.value,
        ActionPack.octave_security_v1.value,
    }
)


def _effective_action_pack_ids(
    workspace: Workspace,
    *,
    surface: str = "chat",
    assistant_profile: Optional[str] = None,
) -> frozenset[str]:
    return frozenset(
        manifest.pack
        for manifest in effective_action_manifests(
            workspace,
            surface=surface,
            assistant_profile=assistant_profile,
        )
    )


def _uses_octave_action_contract(
    workspace: Workspace,
    *,
    surface: str = "chat",
    assistant_profile: Optional[str] = None,
) -> bool:
    packs = _effective_action_pack_ids(
        workspace,
        surface=surface,
        assistant_profile=assistant_profile,
    )
    has_sentinel = bool(packs.intersection(_SENTINEL_ACTION_PACKS))
    has_octave = bool(packs.intersection(_OCTAVE_ACTION_PACKS))
    return has_octave and not has_sentinel


def _has_mission_room_action_contract(
    workspace: Workspace,
    *,
    surface: str = "chat",
    assistant_profile: Optional[str] = None,
) -> bool:
    packs = _effective_action_pack_ids(
        workspace,
        surface=surface,
        assistant_profile=assistant_profile,
    )
    has_sentinel = bool(packs.intersection(_SENTINEL_ACTION_PACKS))
    has_octave = bool(packs.intersection(_OCTAVE_ACTION_PACKS))
    # A mixed Sentinel/Octave workspace is a configuration error. Do not let
    # either business executor choose a brand opportunistically.
    return has_sentinel != has_octave


def _is_octave_manifest(manifest: ActionManifest) -> bool:
    return manifest.pack in _OCTAVE_ACTION_PACKS


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
    workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
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
    workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
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
    workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
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
    workspace = lock_workspace_for_app_entitlement_mutation(db, workspace.id)
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
        resolved = resolve_action(
            workspace, text=text, surface=surface, assistant_profile=assistant_profile
        )
        if (
            resolved.matched
            and resolved.action_id == "voice.confirm_yes"
            and awaiting.get("action_on_yes")
        ):
            action_on_yes = str(awaiting["action_on_yes"])
            if _uses_octave_action_contract(
                workspace,
                surface=surface,
                assistant_profile=assistant_profile,
            ) and action_on_yes in {
                "aya.recommend_cacao",
                "octave.recommend_cacao",
                "octave.recommend_bio-composites",
            }:
                action_on_yes = "octave.recommend_diversification"
            return ActionResolution(
                True,
                action_id=action_on_yes,
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
    return resolve_action(
        workspace, text=text, surface=surface, assistant_profile=assistant_profile
    )


def _action_effect(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"chunk_type": "action_effect", "effect": kind, **payload}


def _assistant_label(manifest: ActionManifest) -> str:
    return "OCTAVE" if _is_octave_manifest(manifest) else "AYA"


def _atlantic_trader_webcam_payload() -> Optional[dict[str, Any]]:
    from app.services.webcam_proxy import (
        get_spec as _get_webcam_spec,
    )
    from app.services.webcam_proxy import (
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
                "label": (
                    _get_webcam_spec(candidate).label if _get_webcam_spec(candidate) else candidate
                ),
                "proxy_url": f"/api/v1/mission-room/webcams/proxy?source_id={candidate}",
            }
            for candidate in cycle_ids
        ],
    }


def _manifest_by_id(
    workspace: Workspace, action_id: str, *, surface: str, assistant_profile: Optional[str]
) -> Optional[ActionManifest]:
    from app.services.actions.registry import effective_action_manifests

    return next(
        (
            item
            for item in effective_action_manifests(
                workspace, surface=surface, assistant_profile=assistant_profile
            )
            if item.action_id == action_id
        ),
        None,
    )


from app.services.actions.packs.mission_room import (  # noqa: E402 - after the helpers it binds
    MISSION_ROOM_HANDLERS,
    _resolve_agenda_item_from_prompt,  # noqa: F401 - re-exported, bound at call time
    run_mission_room_handler,
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
    system_id: Optional[str] = None,
) -> dict[str, Any]:
    denied = _flow_action_permission_denial(
        db,
        workspace,
        user,
        manifest=manifest,
        system_id=system_id,
    )
    if denied is not None:
        return denied
    ctx = _skill_ctx(db, workspace, user)
    handler = manifest.handler.name
    effects: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    content = ""
    octave_contract = _is_octave_manifest(manifest)
    extra: dict[str, Any] = {
        "action_id": manifest.action_id,
        "handler": "managed" if octave_contract else handler,
    }
    awaiting_to_set: Optional[dict[str, Any]] = None
    awaiting_to_clear = False

    if handler == "voice_loop_stop":
        content = "Session vocale en pause."
    elif handler == "voice_repeat":
        content = "Je repete ma derniere reponse."
    elif handler == "voice_rephrase":
        content = "Je reformule ma derniere reponse de facon plus concise."
    elif handler in MISSION_ROOM_HANDLERS:
        content, sources, awaiting_to_set, awaiting_to_clear = await run_mission_room_handler(
            handler,
            db=db,
            workspace=workspace,
            user=user,
            manifest=manifest,
            text=text,
            knowledge_scope=knowledge_scope,
            ctx=ctx,
            octave_contract=octave_contract,
            effects=effects,
            sources=sources,
            content=content,
            extra=extra,
            awaiting_to_set=awaiting_to_set,
            awaiting_to_clear=awaiting_to_clear,
        )
    elif handler == "voice_navigate_view":
        view = (manifest.input_schema or {}).get("default_view") or "cockpit"
        effects.append(
            _action_effect("assistant-navigate", {"route": f"/hypervisor/mission-room/{view}"})
        )
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
        awaiting_to_set = present_payload_for_workspace(workspace, awaiting_to_set)
        set_awaiting_state(db, workspace, awaiting_to_set, session_id=session_id)

    emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type=manifest.audit_event,
        actor=ctx["actor"],
        details={
            "action_id": manifest.action_id,
            "text": text,
            "effects": [e.get("effect") for e in effects if e.get("effect")],
        },
    )

    result = {
        "action": manifest.action_id,
        "applied": True,
        "content": content,
        "sources": sources,
        "action_effects": effects,
        "requires_confirmation": False,
        "action_manifest_id": manifest.action_id,
        **extra,
    }
    return present_payload_for_workspace(workspace, result)


async def handle_registry_chat_action(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    query: str,
    assistant_profile: Optional[str] = None,
    session_id: Optional[str] = None,
    knowledge_scope: Optional[str] = None,
    system_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Resolve and execute registry flow-node actions (non-legacy)."""
    if not _has_mission_room_action_contract(
        workspace,
        surface="chat",
        assistant_profile=assistant_profile,
    ):
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

    manifest = _manifest_by_id(
        workspace, resolution.action_id, surface="chat", assistant_profile=assistant_profile
    )
    if not manifest:
        return None
    if manifest.handler.kind == "legacy_adapter":
        return None
    if manifest.handler.kind != "flow_node":
        return None

    if resolution.reason == "awaiting_declined":
        denied = _flow_action_permission_denial(
            db,
            workspace,
            user,
            manifest=manifest,
            system_id=system_id,
        )
        if denied is not None:
            return denied
        set_awaiting_state(db, workspace, None, session_id=session_id)
        return {
            "action": "awaiting_declined",
            "applied": True,
            "content": "Tres bien, je n'applique pas cette proposition pour le moment.",
            "action_effects": [],
        }

    return await execute_flow_action(
        db,
        workspace,
        user,
        manifest=manifest,
        text=query,
        session_id=session_id,
        knowledge_scope=knowledge_scope,
        system_id=system_id,
    )


def _flow_action_permission_denial(
    db: DBSession,
    workspace: Workspace,
    user: Optional[User],
    *,
    manifest: ActionManifest,
    system_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Authorize at the executor boundary shared by every flow-node caller."""

    if user is None:
        mode = "enforce"
        reason = "authenticated_subject_required"
        policy_id = None
    else:
        bound_system = (
            db.query(System)
            .filter(
                System.id == system_id,
                System.workspace_id == workspace.id,
            )
            .one_or_none()
            if system_id
            else None
        )
        permission = resolve_manifest_permission(
            db,
            user=user,
            workspace=workspace,
            required_permission=manifest.required_permission,
            legacy_allowed=True,
            capability_manifest=manifest.capability_template,
            action_id=manifest.action_id,
            resource_attrs={
                "workspace_id": workspace.id,
                "system_id": bound_system.id if bound_system else None,
                "capability_id": bound_system.capability_id if bound_system else None,
                "capability": manifest.capability_template,
                "action_id": manifest.action_id,
            },
        )
        if permission.effective_allowed:
            return None
        mode = permission.mode
        reason = permission.reason
        policy_id = permission.policy_id

    actor = (user.email or user.username or user.id) if user else "system:action_executor"
    audit_id = emit_audit_event(
        db=db,
        workspace_id=workspace.id,
        event_type="action.denied",
        actor=actor,
        details={
            "action_id": manifest.action_id,
            "surface": "chat",
            "reason": reason,
            "mode": mode,
            "policy_id": policy_id,
            "system_id": system_id,
        },
    )
    return present_payload_for_workspace(
        workspace,
        {
            "action": "action_denied",
            "applied": False,
            "content": "Cette action n'est pas autorisée dans ce workspace.",
            "action_effects": [],
            "requires_confirmation": False,
            "action_manifest_id": manifest.action_id,
            "authorization": {
                "mode": mode,
                "reason": reason,
                "policy_id": policy_id,
            },
            "audit_id": audit_id,
        },
    )
