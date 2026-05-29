from __future__ import annotations

from app.models.workspace import Workspace
from app.services.chat_grounding import resolve_grounding_policy


def _workspace(settings: dict | None = None) -> Workspace:
    return Workspace(id="ws-grounding", name="Grounding", slug="grounding", settings=settings or {})


def test_grounding_platform_default_is_strict():
    policy = resolve_grounding_policy(query="Explain a method.", workspace=_workspace())

    assert policy["mode"] == "strict"
    assert policy["inherited_from"] == "platform"
    assert policy["allow_foundational_fallback"] is False


def test_grounding_workspace_balanced_is_inherited():
    policy = resolve_grounding_policy(
        query="Explain a method.",
        workspace=_workspace({"chat": {"grounding": {"default_mode": "balanced", "allowed_modes": ["strict", "balanced"]}}}),
    )

    assert policy["mode"] == "balanced"
    assert policy["inherited_from"] == "workspace"
    assert policy["reason"] == "workspace_default"


def test_grounding_assistant_profile_overrides_workspace_default():
    workspace = _workspace(
        {
            "chat": {"grounding": {"default_mode": "strict", "allowed_modes": ["strict", "balanced"]}},
            "assistant_profiles": [
                {
                    "key": "advisor",
                    "grounding": {"default_mode": "balanced", "allowed_modes": ["strict", "balanced"]},
                }
            ],
        }
    )

    policy = resolve_grounding_policy(query="Explain a method.", workspace=workspace, assistant_profile="advisor")

    assert policy["mode"] == "balanced"
    assert policy["inherited_from"] == "assistant_profile"
    assert policy["reason"] == "profile_default"


def test_grounding_request_strict_can_harden_balanced_profile():
    workspace = _workspace(
        {
            "assistant_profiles": [
                {
                    "key": "advisor",
                    "grounding": {"default_mode": "balanced", "allowed_modes": ["strict", "balanced"]},
                }
            ]
        }
    )

    policy = resolve_grounding_policy(
        query="Explain a method.",
        workspace=workspace,
        assistant_profile="advisor",
        requested_mode="strict",
    )

    assert policy["mode"] == "strict"
    assert policy["requested_mode"] == "strict"
    assert policy["inherited_from"] == "request"
    assert policy["reason"] == "request_override"


def test_grounding_request_balanced_is_rejected_when_not_allowed():
    policy = resolve_grounding_policy(
        query="Explain a method.",
        workspace=_workspace(),
        assistant_profile="plain",
        requested_mode="balanced",
    )

    assert policy["mode"] == "strict"
    assert policy["requested_mode"] == "balanced"
    assert policy["reason"] == "requested_mode_not_allowed"


def test_grounding_guard_forces_strict_for_context_and_workspace_facts():
    workspace = _workspace({"chat": {"grounding": {"default_mode": "balanced", "allowed_modes": ["strict", "balanced"]}}})

    context_policy = resolve_grounding_policy(
        query="Explain a method.",
        workspace=workspace,
        context_id="ctx-1",
    )
    fact_policy = resolve_grounding_policy(
        query="Combien de documents sécurité SENTINEL-CI sont indexés aujourd'hui ?",
        workspace=workspace,
    )

    assert context_policy["mode"] == "strict"
    assert context_policy["reason"] == "selected_context_requires_sources"
    assert fact_policy["mode"] == "strict"
    assert fact_policy["reason"] == "workspace_fact_or_sensitive_state"


def test_grounding_vigie_compat_without_config_remains_balanced():
    policy = resolve_grounding_policy(
        query="Explique la méthode pour structurer un brief cabinet.",
        workspace=_workspace(),
        assistant_profile="vigie_executive",
    )

    assert policy["mode"] == "balanced"
    assert policy["inherited_from"] == "compat"
    assert policy["reason"] == "vigie_chat_first"


def test_grounding_business_interpretation_guard_allows_advisory_context():
    workspace = _workspace(
        {
            "assistant_profiles": [
                {
                    "key": "andritz_spl_advisor",
                    "grounding": {
                        "default_mode": "balanced",
                        "allowed_modes": ["strict", "balanced"],
                        "strict_guard": "business_interpretation",
                    },
                }
            ]
        }
    )

    policy = resolve_grounding_policy(
        query="Interprète ce que le projet AKK200 implique pour la maintenance Jetlace.",
        workspace=workspace,
        assistant_profile="andritz_spl_advisor",
        context_id="ctx-andritz-spl",
    )

    assert policy["mode"] == "balanced"
    assert policy["source_requirement"] == "workspace_preferred"
    assert policy["reason"] == "profile_default"


def test_grounding_business_interpretation_guard_hardens_documentary_questions():
    workspace = _workspace(
        {
            "assistant_profiles": [
                {
                    "key": "andritz_spl_advisor",
                    "grounding": {
                        "default_mode": "balanced",
                        "allowed_modes": ["strict", "balanced"],
                        "strict_guard": "business_interpretation",
                    },
                }
            ]
        }
    )

    policy = resolve_grounding_policy(
        query="Cite la page source de la notice URACA KD724 qui donne la pression.",
        workspace=workspace,
        assistant_profile="andritz_spl_advisor",
        requested_mode="balanced",
    )

    assert policy["mode"] == "strict"
    assert policy["requested_mode"] == "balanced"
    assert policy["reason"] == "documentary_question_requires_sources"
    assert policy["allow_foundational_fallback"] is False


def test_grounding_business_interpretation_guard_does_not_treat_reformulation_as_reference():
    workspace = _workspace(
        {
            "assistant_profiles": [
                {
                    "key": "andritz_spl_advisor",
                    "grounding": {
                        "default_mode": "balanced",
                        "allowed_modes": ["strict", "balanced"],
                        "strict_guard": "business_interpretation",
                    },
                }
            ]
        }
    )

    policy = resolve_grounding_policy(
        query="Reformule cette explication métier pour un responsable maintenance.",
        workspace=workspace,
        assistant_profile="andritz_spl_advisor",
        context_id="ctx-andritz-spl",
    )

    assert policy["mode"] == "balanced"
