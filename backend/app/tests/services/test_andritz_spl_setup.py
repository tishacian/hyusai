from __future__ import annotations

from app.models.workspace import Workspace
from scripts.setup_andritz_notices_spl import ANDRITZ_SPL_ADVISOR_PROFILE, _upsert_chat_profiles


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
