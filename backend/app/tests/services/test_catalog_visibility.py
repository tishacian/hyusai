from app.models.capability import Capability
from app.models.skill import Skill
from app.models.workspace import Workspace
from app.services.catalog_visibility import (
    capability_is_visible,
    skill_is_visible,
    visible_capabilities,
    visible_skill_ids_from_capabilities,
    workspace_catalog_policy,
)


def _workspace(slug: str, *, settings: dict | None = None) -> Workspace:
    return Workspace(id=f"ws-{slug}", slug=slug, name=slug.title(), settings=settings or {})


def _cap(
    slug: str,
    *,
    tier: str = "universal",
    industry: str | None = None,
    workspace_id: str | None = None,
    skill_ids: list[str] | None = None,
) -> Capability:
    return Capability(
        id=f"cap-{slug}",
        slug=slug,
        name=slug.replace("_", " ").title(),
        tier=tier,
        industry=industry,
        workspace_id=workspace_id,
        skill_ids=skill_ids or [],
    )


def _skill(slug: str, *, id_: str | None = None, workspace_id: str | None = None) -> Skill:
    return Skill(
        id=id_ or f"skill-{slug}",
        slug=slug,
        name=slug.replace("_", " ").title(),
        workspace_id=workspace_id,
    )


def test_andritz_hides_government_industry_capabilities_by_default():
    workspace = _workspace("andritz", settings={"family": "andritz"})
    universal = _cap("expert_knowledge_capture")
    government = _cap("aya_voice_command", tier="industry", industry="government")
    legal = _cap("compliance_assistant", tier="industry", industry="legal")

    policy = workspace_catalog_policy(workspace)

    assert capability_is_visible(universal, workspace, policy) is True
    assert capability_is_visible(government, workspace, policy) is False
    assert capability_is_visible(legal, workspace, policy) is False


def test_sentinel_sees_government_industry_capabilities_by_default():
    workspace = _workspace("sentinel-ci", settings={"family": "sentinel_ci"})
    government = _cap("aya_voice_command", tier="industry", industry="government")
    finance = _cap("finance_brief", tier="industry", industry="finance")

    policy = workspace_catalog_policy(workspace)

    assert capability_is_visible(government, workspace, policy) is True
    assert capability_is_visible(finance, workspace, policy) is False


def test_catalog_overrides_can_enable_and_hide_capabilities():
    workspace = _workspace(
        "andritz",
        settings={
            "family": "andritz",
            "catalog": {
                "enabled_capabilities": ["aya_voice_command"],
                "hidden_capabilities": ["expert_knowledge_capture"],
            },
        },
    )
    expert_capture = _cap("expert_knowledge_capture")
    government = _cap("aya_voice_command", tier="industry", industry="government")

    policy = workspace_catalog_policy(workspace)

    assert capability_is_visible(expert_capture, workspace, policy) is False
    assert capability_is_visible(government, workspace, policy) is True


def test_skills_are_visible_only_when_bound_to_visible_capabilities():
    workspace = _workspace("andritz", settings={"family": "andritz"})
    universal_skill = _skill("expert_answer_evaluator_v1", id_="skill-visible")
    government_skill = _skill("mission_command_v1", id_="skill-hidden")
    universal_cap = _cap("expert_knowledge_capture", skill_ids=[universal_skill.id])
    government_cap = _cap(
        "aya_voice_command",
        tier="industry",
        industry="government",
        skill_ids=[government_skill.id],
    )

    policy = workspace_catalog_policy(workspace)
    visible_caps = visible_capabilities([universal_cap, government_cap], workspace, policy)
    visible_skill_ids = visible_skill_ids_from_capabilities(visible_caps)

    assert skill_is_visible(universal_skill, workspace, visible_skill_ids, policy) is True
    assert skill_is_visible(government_skill, workspace, visible_skill_ids, policy) is False


def test_workspace_specific_rows_are_visible_in_that_workspace_only():
    andritz = _workspace("andritz")
    sentinel = _workspace("sentinel-ci")
    cap = _cap("custom_andritz_review", workspace_id=andritz.id)
    skill = _skill("custom_andritz_skill_v1", workspace_id=andritz.id)

    assert capability_is_visible(cap, andritz) is True
    assert capability_is_visible(cap, sentinel) is False
    assert skill_is_visible(skill, andritz, set()) is True
    assert skill_is_visible(skill, sentinel, set()) is False
