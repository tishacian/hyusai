"""Default chat-orchestration template: universal baseline vs industrial opt-in.

These tests pin the layering contract introduced when the proven Andritz RAG
orchestration was promoted into the default ``chat_transverse_v1`` template:

* A generic-family workspace inherits the domain-neutral ``default_answer_policy``
  and a source policy with NO "project" concept (no ``reject_cross_project_sources``,
  no ``project`` in ``preserve_reference_types``) and a neutral name/objective.
* ``andritz`` and ``industrial`` families still resolve to the SAME
  ``industrial_answer_policy`` + industrial source policy (incl.
  ``reject_cross_project_sources``) — the Andritz preservation guarantee.
"""

from app.models.system import System
from app.models.workspace import Workspace
from app.services.industrial_answer_profile import (
    default_answer_policy,
    industrial_answer_policy,
)
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.systems.bootstrap import (
    WORKSPACE_CHAT_SYSTEM_NAME,
    ensure_workspace_chat_system_default,
)


def _chat_system(db_session, workspace: Workspace) -> System:
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    system = ensure_workspace_chat_system_default(db_session, workspace.id)
    assert system is not None
    return system


# ---------------------------------------------------------------------------
# Policy builders (unit level)
# ---------------------------------------------------------------------------


def test_default_answer_policy_is_domain_neutral():
    policy = default_answer_policy()

    assert policy["key"] == "default_answer_profile_v1"
    assert policy["default_answer_profile"] == "precise_fact"
    assert set(policy["profiles"]) == {
        "precise_fact",
        "summary",
        "comparison",
        "insufficient_context",
    }
    # No industrial/project profiles leak into the universal default.
    assert "transversal_inventory" not in policy["profiles"]
    assert "project_summary" not in policy["profiles"]
    assert "equipment_detail" not in policy["profiles"]
    # No "project" string anywhere in the neutral profile instructions/principles.
    serialized = repr(policy).lower()
    assert "project" not in serialized
    # Reuses the shared post-hoc guard vocabulary (forbidden internal terms).
    assert "chunk" in policy["forbidden_internal_terms"]


def test_industrial_answer_policy_is_unchanged():
    policy = industrial_answer_policy()

    assert policy["key"] == "industrial_answer_profile_v1"
    assert policy["default_answer_profile"] == "precise_fact"
    assert "transversal_inventory" in policy["profiles"]
    assert "project_summary" in policy["profiles"]
    assert "equipment_detail" in policy["profiles"]


# ---------------------------------------------------------------------------
# (a) Generic-family workspace: universal default, no "project"
# ---------------------------------------------------------------------------


def test_generic_workspace_chat_uses_neutral_default_template(db_session):
    workspace = Workspace(
        id="ws-generic-default",
        name="Agentium Showcase",
        slug="agentium-showcase",
        settings={"family": "generic"},
    )
    system = _chat_system(db_session, workspace)

    # Neutral name + objective (no Andritz strings).
    assert system.name == WORKSPACE_CHAT_SYSTEM_NAME
    assert "andritz" not in (system.objective or "").lower()
    assert system.settings["family"] == "generic"

    source_policy = system.settings["source_policy"]
    assert source_policy["mode"] == "workspace_scoped"
    assert "reject_cross_project_sources" not in source_policy
    assert "prefer_exact_references" not in source_policy
    assert source_policy["preserve_reference_types"] == [
        "document_name",
        "part_number",
        "identifier",
    ]
    assert "project" not in source_policy["preserve_reference_types"]

    prompt_contract = system.flow_definition["prompt_contract"]
    assert prompt_contract["answer_policy"]["key"] == "default_answer_profile_v1"
    assert set(prompt_contract["answer_profiles"]) == {
        "precise_fact",
        "summary",
        "comparison",
        "insufficient_context",
    }
    # Answer shaping is generic: no Andritz boilerplate, no cross-project line.
    shaping = " ".join(prompt_contract["answer_shaping_instructions"]).lower()
    assert "andritz" not in shaping
    assert "cross-project" not in shaping


# ---------------------------------------------------------------------------
# (b) Andritz + industrial families: identical industrial layer
# ---------------------------------------------------------------------------


def _assert_industrial_layer(system: System, *, expected_family: str) -> None:
    assert system.settings["family"] == expected_family

    source_policy = system.settings["source_policy"]
    assert source_policy["mode"] == "industrial_grounding"
    assert source_policy["prefer_exact_references"] is True
    assert source_policy["reject_cross_project_sources"] is True
    assert "project" in source_policy["preserve_reference_types"]

    prompt_contract = system.flow_definition["prompt_contract"]
    assert prompt_contract["answer_policy"]["key"] == "industrial_answer_profile_v1"
    assert "transversal_inventory" in prompt_contract["answer_profiles"]
    shaping = " ".join(prompt_contract["answer_shaping_instructions"]).lower()
    assert "cross-project equipment inventories" in shaping


def test_andritz_workspace_chat_keeps_industrial_layer(db_session):
    workspace = Workspace(
        id="ws-andritz-default",
        name="Andritz",
        slug="andritz",
        settings={"family": "andritz"},
    )
    system = _chat_system(db_session, workspace)

    assert system.name == "Andritz Workspace Chat"
    _assert_industrial_layer(system, expected_family="andritz")


def test_industrial_family_workspace_chat_opts_into_industrial_layer(db_session):
    workspace = Workspace(
        id="ws-industrial-default",
        name="Acme Manufacturing",
        slug="acme-manufacturing",
        settings={"family": "industrial"},
    )
    system = _chat_system(db_session, workspace)

    # The industrial family reuses the universal name but the industrial policy.
    assert system.name == WORKSPACE_CHAT_SYSTEM_NAME
    _assert_industrial_layer(system, expected_family="industrial")
