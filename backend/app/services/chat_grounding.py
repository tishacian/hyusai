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
from app.services.workspace_features import workspace_family

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

_DOCUMENTARY_STRICT_TERMS = (
    "combien",
    "chiffre",
    "chiffré",
    "chiffree",
    "valeur",
    "valeurs",
    "mesure",
    "mesures",
    "paramètre",
    "parametre",
    "diamètre",
    "diametre",
    "vitesse",
    "pression",
    "température",
    "temperature",
    "référence",
    "reference",
    "références",
    "references",
    "source",
    "sources",
    "citation",
    "cite",
    "citer",
    "preuve",
    "preuves",
    "document",
    "documents",
    "pdf",
    "article",
    "notice",
    "notices",
    "manuel",
    "manual",
    "page",
    "section",
    "chapitre",
    "extrait",
    "liste",
    "lister",
    "ouvre",
    "résume",
    "resume",
    "montre",
    "affiche",
)

_STATE_TERMS = (
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

_SENTINEL_FACT_TERMS = (
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

_ANDRITZ_FACT_TERMS = (
    "andritz",
    "spl",
    "non-wovens",
    "non wovens",
    "nonwoven",
    "bba",
    "aco",
    "akk",
    "ara",
    "ava",
    "dci",
    "projet",
    "project",
    "ligne",
    "machine",
    "équipement",
    "equipement",
    "jetlace",
    "injector",
    "injecteur",
    "strip-carrier",
    "strip carrier",
    "pompe",
    "pump",
    "uraca",
    "kd724",
    "capteur",
    "sensor",
    "o-ring",
    "spare parts",
    "pièce",
    "piece",
)



def _workspace_fact_terms(workspace: Workspace | None) -> tuple[str, ...]:
    """The vocabulary that marks a question as being about this workspace.

    The Andritz list used to apply to every tenant, and matching is by
    substring, so its three-letter series codes fired inside ordinary words:
    "ara" in "caractère", "ava" in "avancement". Paired with any evidence or
    state term, that forced a turn into strict source-bound grounding, and a
    tenant with no matching corpus got "insufficient context" where a balanced
    answer was expected. The list is that customer's nomenclature, so it
    applies only to the workspace stamped with that family. Passed explicitly
    rather than read from ambient state, because the workspace is in hand here.
    """

    if workspace is not None and workspace_family(workspace) == "andritz":
        return _SENTINEL_FACT_TERMS + _ANDRITZ_FACT_TERMS
    return _SENTINEL_FACT_TERMS


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


def _contains_any(normalized: str, terms: tuple[str, ...]) -> bool:
    return any(term in normalized for term in terms)


def _query_requires_workspace_grounding(
    query: str, fact_terms: tuple[str, ...] = _SENTINEL_FACT_TERMS
) -> bool:
    """Return whether a turn should remain source-bound."""
    normalized = _normalise_chat_text(query)
    if not normalized:
        return False

    has_general_assist = _contains_any(normalized, _GENERAL_ASSIST_TERMS)
    has_evidence_or_state = _contains_any(normalized, _DOCUMENTARY_STRICT_TERMS + _STATE_TERMS)
    has_workspace_fact = _contains_any(normalized, fact_terms)

    if has_general_assist and not has_evidence_or_state:
        return False
    return has_evidence_or_state and has_workspace_fact


def _query_requires_documentary_grounding(query: str) -> bool:
    """Return whether the user is asking for a source-bound documentary answer."""
    normalized = _normalise_chat_text(query)
    if not normalized:
        return False
    return _contains_any(normalized, _DOCUMENTARY_STRICT_TERMS + _STATE_TERMS)


def _strict_guard_override_reason(
    *,
    query: str,
    strict_guard: str,
    context_id: str | None,
    fact_terms: tuple[str, ...] = _SENTINEL_FACT_TERMS,
) -> str | None:
    guard = (strict_guard or "default").strip().lower()
    if guard == "default":
        if context_id:
            return "selected_context_requires_sources"
        if _query_requires_workspace_grounding(query, fact_terms):
            return "workspace_fact_or_sensitive_state"
        return None

    if guard in {"business_interpretation", "workspace_preferred"}:
        if _query_requires_documentary_grounding(query):
            return "documentary_question_requires_sources"
        return None

    if guard in {"documentary", "workspace_documents"}:
        if context_id:
            return "selected_context_requires_sources"
        if _query_requires_documentary_grounding(query):
            return "documentary_question_requires_sources"
        return None

    return None


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

    override_reason = _strict_guard_override_reason(
        query=query,
        strict_guard=strict_guard,
        context_id=context_id,
        fact_terms=_workspace_fact_terms(workspace),
    )
    if override_reason:
        mode = "strict"
        reason = override_reason

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
