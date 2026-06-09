from app.models.capability import Capability
from app.models.system import System
from app.models.workspace import Workspace
from app.api.v1.endpoints.chat import ChatRequest, _apply_workspace_chat_flow_defaults
from app.services.chains.dag_validator import validate_flow
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.skills_registry.wrappers import runtime_status
from app.services.systems.bootstrap import (
    WORKSPACE_CHAT_CAPABILITY_SLUG,
    WORKSPACE_CHAT_VARIANT,
    ensure_workspace_chat_system_default,
    workspace_chat_system_id,
)
from app.services.systems.flow_manifest import serialize_flow_manifest


def test_workspace_chat_capability_and_system_are_seeded(db_session):
    workspace = Workspace(id="ws-workspace-chat", name="Operator Workspace", slug="operator-workspace")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    system = ensure_workspace_chat_system_default(db_session, workspace.id)

    assert system is not None
    assert system.name == "Agentium Workspace Chat"
    assert system.status == "active"
    assert system.execution_mode == "real_time_decision"
    assert system.settings["system_type"] == "workspace_chat"
    assert system.settings["always_on"] is True
    assert system.flow_definition["variant"] == WORKSPACE_CHAT_VARIANT
    assert system.flow_definition["ui"]["entry_route"] == "chat"
    assert system.flow_definition["template_id"] == WORKSPACE_CHAT_VARIANT
    assert system.flow_definition["runtime_contract"]["source_of_truth"] == "backend/app/api/v1/endpoints/chat.py"
    assert system.flow_definition["prompt_contract"]["base_system_prompt"]
    assert workspace_chat_system_id(db_session, workspace.id) == system.id
    assert [issue for issue in validate_flow(system.flow_definition) if issue.level == "error"] == []
    assert [issue for issue in validate_flow(system.flow_definition) if issue.code == "task_no_skill"] == []
    node_ids = {node["id"] for node in system.flow_definition["nodes"]}
    assert {
        "router.fast_exit",
        "skill.grounding_policy",
        "runtime.prompt_assembly",
        "skill.fast_answer",
        "runtime.deep_router",
        "skill.answer_audit",
        "chat.response",
    }.issubset(node_ids)
    prompt_node = next(node for node in system.flow_definition["nodes"] if node["id"] == "runtime.prompt_assembly")
    assert "base_system_prompt" in prompt_node["data"]["prompt_contract"]
    assert "procurement_agent._build_rag_user_prompt" in prompt_node["data"]["runtime_ref"]

    capability = db_session.query(Capability).filter(Capability.slug == WORKSPACE_CHAT_CAPABILITY_SLUG).one()
    assert system.capability_id == capability.id
    assert runtime_status("chat_trivial_bypass_v1") == "bound"
    assert runtime_status("chat_grounding_policy_v1") == "stub"
    assert runtime_status("chat_action_resolver_v1") == "stub"

    again = ensure_workspace_chat_system_default(db_session, workspace.id)
    count = (
        db_session.query(System)
        .filter(System.workspace_id == workspace.id)
        .filter(System.name == "Agentium Workspace Chat")
        .count()
    )
    assert again.id == system.id
    assert count == 1


def test_andritz_workspace_chat_inherits_industrial_profile(db_session):
    workspace = Workspace(
        id="ws-andritz-chat",
        name="Andritz",
        slug="andritz",
        settings={
            "assistant_profile_default": "andritz_spl_advisor",
            "knowledge_scopes": [
                {
                    "key": "andritz-spl-knowledge-experiment",
                    "collection_slugs": ["andritz-secure-deposit", "andritz-notices-techniques-spl-pilot"],
                    "default_mode": "chah",
                    "top_k": 6,
                    "is_default": True,
                }
            ],
            "assistant_profiles": [
                {
                    "key": "andritz_spl_advisor",
                    "label": "Andritz SPL Advisor",
                    "default_knowledge_scope": "andritz-spl-knowledge-experiment",
                    "grounding": {
                        "default_mode": "balanced",
                        "allowed_modes": ["strict", "balanced"],
                        "strict_guard": "business_interpretation",
                    },
                }
            ],
        },
    )
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    system = ensure_workspace_chat_system_default(db_session, workspace.id)

    assert system.name == "Andritz Workspace Chat"
    assert system.settings["family"] == "andritz"
    assert system.settings["assistant_profile"] == "andritz_spl_advisor"
    assert system.settings["knowledge_scope"] == "andritz-spl-knowledge-experiment"
    assert system.settings["source_policy"]["mode"] == "industrial_grounding"
    assert system.settings["source_policy"]["prefer_exact_references"] is True
    assert system.flow_definition["chat"]["collection_slugs"] == [
        "andritz-secure-deposit",
        "andritz-notices-techniques-spl-pilot",
    ]
    assert system.retrieval_mode_default == "chah"

    request = ChatRequest(query="quelle vitesse AKK200 ?")
    resolved_id = _apply_workspace_chat_flow_defaults(db_session, workspace=workspace, request=request)
    assert resolved_id == system.id
    assert request.agent_id == system.id
    assert request.assistant_profile == "andritz_spl_advisor"
    assert request.knowledge_scope == "andritz-spl-knowledge-experiment"
    assert request.rag_pipeline_mode == "chah"
    assert request.top_k == 6
    assert request.system_prompt and "curated knowledge base" in request.system_prompt

    manifest = serialize_flow_manifest(db_session, system)
    effective = manifest["effective_config"]
    assert effective["retrieval_config"]["runtime_read_path"] == "nodes.runtime.settings_budget.data.retrieval_defaults"
    assert effective["grounding_policy"]["node_id"] == "skill.grounding_policy"
    assert effective["source_policy_config"]["value"]["mode"] == "industrial_grounding"

    prompt_stack = effective["prompt_stack"]
    assert "curated knowledge base" in prompt_stack["system_prompt"]
    assert prompt_stack["selected_reasoning_template"]["key"] == "factual"
    assert prompt_stack["selected_reasoning_template"]["template"]
    assert any(row["key"] == "trivial" for row in prompt_stack["available_reasoning_templates"])
    assert "citation_instructions" in prompt_stack["rag_user_prompt_contract"]

    builders = effective["runtime_builders"]
    assert builders["chat_defaults"].endswith("_apply_workspace_chat_flow_defaults")
    assert builders["rag_user_prompt_builder"].endswith("_build_rag_user_prompt")


def test_sentinel_workspace_chat_reuses_aya_profile(db_session):
    workspace = Workspace(
        id="ws-sentinel-chat",
        name="SENTINEL-CI",
        slug="sentinel-ci",
        settings={
            "assistant_profile_default": "vigie_executive",
            "knowledge_scopes": [
                {
                    "key": "vigie",
                    "collection_slugs": ["sentinel-ci-open-intelligence"],
                    "default_mode": "chah",
                    "top_k": 8,
                    "is_default": True,
                }
            ],
            "assistant_profiles": [
                {
                    "key": "vigie_executive",
                    "label": "AYA",
                    "default_knowledge_scope": "vigie",
                    "grounding": {"default_mode": "balanced"},
                    "actions": {"enabled_packs": ["sentinel_ci_aya_v1"]},
                }
            ],
        },
    )
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    system = ensure_workspace_chat_system_default(db_session, workspace.id)

    assert system.name == "AYA Workspace Chat"
    assert system.settings["family"] == "sentinel_ci"
    assert system.settings["assistant_profile"] == "vigie_executive"
    assert system.settings["knowledge_scope"] == "vigie"
    assert system.settings["source_policy"]["mode"] == "executive_mission_grounding"
    assert system.flow_definition["chat"]["actions"]["enabled_packs"] == ["sentinel_ci_aya_v1"]
