"""Answer grounding policy resolution for chat turns.

The policy decides whether an assistant may answer from general model
knowledge when workspace retrieval is empty. It is intentionally resolved on
the backend so clients can request a mode, but cannot bypass source-required
guards for documents, current workspace state, actions, or sensitive claims.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from app.models.workspace import Workspace

GroundingMode = Literal["strict", "balanced"]

DEFAULT_FALLBACK_DISCLAIMER = (
    "Je n'ai pas de source workspace sur ce point ; analyse générale à valider :"
)

_GENERAL_ASSIST_TERMS = (
    "aide",
    "explique",
    "expliquer",
    "comment",
    "méthode",
    "methode",
    "stratégie",
    "strategie",
    "plan",
    "trame",
    "structure",
    "structurer",
    "propose",
    "proposer",
    "prépare",
    "prepare",
    "rédige",
    "redige",
    "draft",
    "reformule",
    "reformuler",
)

_EVIDENCE_OR_STATE_TERMS = (
    "combien",
    "chiffre",
    "chiffré",
    "chiffree",
    "source",
    "citation",
    "preuve",
    "document",
    "pdf",
    "article",
    "ouvre",
    "résume",
    "resume",
    "montre",
    "affiche",
    "situation",
    "état",
    "etat",
    "actuel",
    "actuelle",
    "aujourd'hui",
    "maintenant",
    "dernier",
    "dernière",
    "derniere",
    "prochain",
    "prochaine",
)

_WORKSPACE_FACT_TERMS = (
    "workspace",
    "sentinel",
    "s3",
    "nord",
    "sahel",
    "frontière",
    "frontiere",
    "rumeur",
    "troupes",
    "mouvement",
    "incursion",
    "ads-b",
    "adsb",
    "osint",
    "sécurité",
    "securite",
    "agenda",
    "réunion",
    "reunion",
    "décision",
    "decision",
    "nawa",
    "cacao",
    "port",
    "cargo",
    "navire",
    "carte",
    "prod",
    "run",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _normalise_mode(value: Any) -> GroundingMode | None:
    mode = str(value or "").strip().lower()
    if mode in {"strict", "balanced"}:
        return mode  # type: ignore[return-value]
    return None


def _normalise_modes(value: Any, fallback: set[GroundingMode]) -> set[GroundingMode]:
    if not isinstance(value, list):
        return set(fallback)
    modes = {_normalise_mode(item) for item in value}
    return {mode for mode in modes if mode} or set(fallback)


def _profile_for(settings: dict[str, Any], assistant_profile: str | None) -> dict[str, Any]:
    if not assistant_profile:
        return {}
    profiles = settings.get("assistant_profiles")
    if not isinstance(profiles, list):
        return {}
    for item in profiles:
        profile = _as_dict(item)
        if profile.get("key") == assistant_profile:
            return profile
    return {}


def _normalise_chat_text(value: str) -> str:
    return " ".join(value.lower().replace("’", "'").split())


def _query_requires_workspace_grounding(query: str) -> bool:
    """Return whether a turn should remain source-bound."""
    normalized = _normalise_chat_text(query)
    if not normalized:
        return False

    has_general_assist = any(term in normalized for term in _GENERAL_ASSIST_TERMS)
    has_evidence_or_state = any(term in normalized for term in _EVIDENCE_OR_STATE_TERMS)
    has_workspace_fact = any(term in normalized for term in _WORKSPACE_FACT_TERMS)

    if has_general_assist and not has_evidence_or_state:
        return False
    return has_evidence_or_state and has_workspace_fact


def _apply_grounding_config(
    *,
    config: dict[str, Any],
    inherited_from: str,
    mode: GroundingMode,
    allowed_modes: set[GroundingMode],
    fallback_disclaimer: str,
    strict_guard: str,
) -> tuple[GroundingMode, set[GroundingMode], str, str, str]:
    if not config:
        return mode, allowed_modes, fallback_disclaimer, strict_guard, inherited_from

    next_allowed = _normalise_modes(config.get("allowed_modes"), allowed_modes)
    next_mode = _normalise_mode(config.get("default_mode")) or mode
    if next_mode not in next_allowed:
        next_mode = "strict"
    next_disclaimer = str(config.get("fallback_disclaimer") or fallback_disclaimer)
    next_guard = str(config.get("strict_guard") or strict_guard or "default")
    return next_mode, next_allowed, next_disclaimer, next_guard, inherited_from


def resolve_grounding_policy(
    *,
    query: str,
    workspace: Workspace,
    assistant_profile: str | None = None,
    requested_mode: str | None = None,
    context_id: str | None = None,
) -> dict[str, Any]:
    """Resolve effective grounding from platform, workspace, profile, request.

    Platform default is strict. ``balanced`` must be enabled by workspace or
    profile config, except for the temporary SENTINEL-CI AYA compatibility shim
    that preserves the earlier behaviour for existing demo workspaces.
    """
    settings = _as_dict(workspace.settings)
    chat_settings = _as_dict(settings.get("chat"))
    workspace_grounding = _as_dict(chat_settings.get("grounding"))
    profile = _profile_for(settings, assistant_profile)
    profile_grounding = _as_dict(profile.get("grounding"))

    mode: GroundingMode = "strict"
    allowed_modes: set[GroundingMode] = {"strict"}
    fallback_disclaimer = DEFAULT_FALLBACK_DISCLAIMER
    strict_guard = "default"
    inherited_from = "platform"
    reason = "platform_default"

    if workspace_grounding:
        mode, allowed_modes, fallback_disclaimer, strict_guard, inherited_from = _apply_grounding_config(
            config=workspace_grounding,
            inherited_from="workspace",
            mode=mode,
            allowed_modes=allowed_modes,
            fallback_disclaimer=fallback_disclaimer,
            strict_guard=strict_guard,
        )
        reason = "workspace_default"

    if profile_grounding:
        mode, allowed_modes, fallback_disclaimer, strict_guard, inherited_from = _apply_grounding_config(
            config=profile_grounding,
            inherited_from="assistant_profile",
            mode=mode,
            allowed_modes=allowed_modes,
            fallback_disclaimer=fallback_disclaimer,
            strict_guard=strict_guard,
        )
        reason = "profile_default"
    elif assistant_profile == "vigie_executive" and not workspace_grounding:
        # Backward compatibility for already-seeded SENTINEL-CI workspaces.
        mode = "balanced"
        allowed_modes = {"strict", "balanced"}
        inherited_from = "compat"
        reason = "vigie_chat_first"

    requested = _normalise_mode(requested_mode)
    requested_label = requested or mode
    if requested == "strict":
        mode = "strict"
        inherited_from = "request"
        reason = "request_override"
    elif requested == "balanced":
        if "balanced" in allowed_modes:
            mode = "balanced"
            inherited_from = "request"
            reason = "request_override"
        else:
            mode = "strict"
            reason = "requested_mode_not_allowed"

    if strict_guard == "default":
        if context_id:
            mode = "strict"
            reason = "selected_context_requires_sources"
        elif _query_requires_workspace_grounding(query):
            mode = "strict"
            reason = "workspace_fact_or_sensitive_state"

    return {
        "requested_mode": requested_label,
        "mode": mode,
        "inherited_from": inherited_from,
        "reason": reason,
        "allow_foundational_fallback": mode == "balanced",
        "source_requirement": "workspace_required" if mode == "strict" else "workspace_preferred",
        "assistant_profile": assistant_profile,
        "workspace_slug": workspace.slug,
        "fallback_disclaimer": fallback_disclaimer,
        "strict_guard": strict_guard,
        "allowed_modes": sorted(allowed_modes),
    }
