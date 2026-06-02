from __future__ import annotations

from types import SimpleNamespace

from app.models.workspace import Workspace
from app.services.rag.retrieval_policy import retrieval_policy_from_guides
from scripts.setup_andritz_notices_spl import ANDRITZ_SPL_ADVISOR_PROFILE, _guide_markdown, _upsert_chat_profiles


def test_upsert_chat_profiles_adds_andritz_spl_balanced_profile():
    workspace = Workspace(
        id="ws-andritz",
        name="Andritz",
        slug="andritz",
        settings={
            "assistant_profiles": [
                {
                    "key": "andritz_non_wovens_excel",
                    "label": "Andritz Knowledge Assistant",
                    "default_knowledge_scope": "andritz_non_wovens_france_excel_pilot",
                }
            ],
            "assistant_profile_default": "andritz_non_wovens_excel",
        },
    )

    _upsert_chat_profiles(workspace, scope_key="andritz-spl-knowledge-experiment", make_default=True)

    settings = workspace.settings
    profiles = {profile["key"]: profile for profile in settings["assistant_profiles"]}
    assert settings["assistant_profile_default"] == ANDRITZ_SPL_ADVISOR_PROFILE
    assert settings["voice_loop"]["default_mode"] == "session_loop"
    assert settings["voice_loop"]["enabled_default"] is True
    assert settings["chat"]["grounding"]["default_mode"] == "strict"
    assert settings["chat"]["grounding"]["strict_guard"] == "business_interpretation"
    assert profiles[ANDRITZ_SPL_ADVISOR_PROFILE]["default_knowledge_scope"] == "andritz-spl-knowledge-experiment"
    assert profiles[ANDRITZ_SPL_ADVISOR_PROFILE]["grounding"]["default_mode"] == "balanced"
    assert profiles[ANDRITZ_SPL_ADVISOR_PROFILE]["grounding"]["strict_guard"] == "business_interpretation"
    assert profiles["andritz_non_wovens_excel"]["default_knowledge_scope"] == "andritz_non_wovens_france_excel_pilot"
    assert profiles["andritz_non_wovens_excel"]["grounding"]["default_mode"] == "balanced"


def test_upsert_chat_profiles_can_preserve_current_default():
    workspace = Workspace(id="ws-andritz", name="Andritz", slug="andritz", settings={"assistant_profile_default": "custom"})

    _upsert_chat_profiles(workspace, scope_key="andritz-spl-knowledge-experiment", make_default=False)

    assert workspace.settings["assistant_profile_default"] == "custom"


def test_andritz_spl_guide_contains_retrieval_policy():
    guide = SimpleNamespace(markdown=_guide_markdown())

    policy = retrieval_policy_from_guides([guide])

    assert policy.enabled is True
    assert "BBA120" in policy.protected_terms
    assert any(term == "capteurs" for term, _expansions in policy.aliases)
    assert any(rule.source_families == ("spare_parts_list",) for rule in policy.source_family_rules)
