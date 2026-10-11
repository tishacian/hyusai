from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth as auth_endpoint
from app.api.v1.endpoints.chat import ChatRequest, _apply_workspace_chat_flow_defaults
from app.core.iam.roles import WORKSPACE_CONTRIBUTOR
from app.models.capability import Capability
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.chains.dag_validator import validate_flow
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.skills_registry.wrappers import runtime_status
from app.services.systems.bootstrap import (
    WORKSPACE_CHAT_CAPABILITY_SLUG,
    WORKSPACE_CHAT_VARIANT,
    ensure_client360_pdr_system_default,
    ensure_expert_capture_system_default,
    ensure_fse_report_system,
    ensure_intelligence_system_default,
    ensure_workspace_chat_system_default,
    resolve_workspace_chat_source_policy,
    sync_chat_system_expert_correction_policy,
    workspace_chat_system_id,
)
from app.services.systems.flow_manifest import serialize_flow_manifest


def test_workspace_chat_capability_and_system_are_seeded(db_session):
    workspace = Workspace(
        id="ws-workspace-chat", name="Operator Workspace", slug="operator-workspace"
    )
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
    assert (
        system.flow_definition["runtime_contract"]["source_of_truth"]
        == "backend/app/api/v1/endpoints/chat.py"
    )
    assert system.flow_definition["prompt_contract"]["base_system_prompt"]
    assert workspace_chat_system_id(db_session, workspace.id) == system.id
    assert [
        issue for issue in validate_flow(system.flow_definition) if issue.level == "error"
    ] == []
    assert [
        issue for issue in validate_flow(system.flow_definition) if issue.code == "task_no_skill"
    ] == []
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
    prompt_node = next(
        node for node in system.flow_definition["nodes"] if node["id"] == "runtime.prompt_assembly"
    )
    assert "base_system_prompt" in prompt_node["data"]["prompt_contract"]
    assert "procurement_agent._build_rag_user_prompt" in prompt_node["data"]["runtime_ref"]

    capability = (
        db_session.query(Capability).filter(Capability.slug == WORKSPACE_CHAT_CAPABILITY_SLUG).one()
    )
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


def test_feature_on_workspace_chat_seed_initializes_publication_state(db_session):
    workspace = Workspace(
        id="ws-workspace-chat-publication",
        name="Published chat workspace",
        slug="published-chat-workspace",
        settings={"features": {"flow_publication_v1": True}},
    )
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    system = ensure_workspace_chat_system_default(db_session, workspace.id)

    assert system is not None
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one()
    version = (
        db_session.query(SystemVersion)
        .filter_by(system_id=system.id, id=system.published_flow_version_id)
        .one()
    )
    assert draft.base_published_version_id == version.id
    assert draft.flow_sha256 == version.flow_sha256
    assert version.execution_contract is not None
    assert db_session.query(SystemVersion).filter_by(system_id=system.id).count() == 1


def test_feature_on_bootstrap_factories_initialize_every_new_system(db_session):
    workspace = Workspace(
        id="ws-bootstrap-publication",
        name="Published bootstrap workspace",
        slug="published-bootstrap-workspace",
        settings={
            "family": "andritz",
            "features": {"flow_publication_v1": True},
        },
    )
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    systems = [
        ensure_workspace_chat_system_default(db_session, workspace.id),
        ensure_client360_pdr_system_default(db_session, workspace.id),
        ensure_intelligence_system_default(db_session, workspace.id),
        ensure_expert_capture_system_default(db_session, workspace.id),
        ensure_fse_report_system(db_session, workspace.id),
    ]
    initial_ids = [system.id for system in systems if system is not None]
    reconciled = [
        ensure_workspace_chat_system_default(db_session, workspace.id),
        ensure_client360_pdr_system_default(db_session, workspace.id),
        ensure_intelligence_system_default(db_session, workspace.id),
        ensure_expert_capture_system_default(db_session, workspace.id),
        ensure_fse_report_system(db_session, workspace.id),
    ]

    assert all(system is not None for system in systems)
    assert len({system.id for system in systems if system is not None}) == len(systems)
    assert [system.id for system in reconciled if system is not None] == initial_ids
    for system in systems:
        assert system is not None
        draft = db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one()
        published = (
            db_session.query(SystemVersion)
            .filter_by(system_id=system.id, id=system.published_flow_version_id)
            .one()
        )
        assert draft.base_published_version_id == published.id
        assert system.flow_definition == published.flow_definition
        assert published.execution_contract is not None


def test_workspace_chat_dedupe_retires_concurrent_duplicates(db_session):
    """Anti-double-seed: a check-then-act race row is archived, keeping one chat."""
    workspace = Workspace(id="ws-chat-dedupe", name="Chat Dedupe", slug="chat-dedupe")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    first = ensure_workspace_chat_system_default(db_session, workspace.id)
    dupe = System(
        workspace_id=workspace.id,
        name=first.name,
        objective=first.objective,
        capability_id=first.capability_id,
        flow_definition=dict(first.flow_definition or {}),
        settings=dict(first.settings or {}),
        status="active",
        created_by="system:workspace_chat_seed",
    )
    db_session.add(dupe)
    db_session.commit()

    kept = ensure_workspace_chat_system_default(db_session, workspace.id)

    active = (
        db_session.query(System)
        .filter(System.workspace_id == workspace.id, System.status != "retired")
        .all()
    )
    chat_active = [
        s for s in active if (s.flow_definition or {}).get("variant") == WORKSPACE_CHAT_VARIANT
    ]
    assert len(chat_active) == 1
    assert kept.id == chat_active[0].id
    # Deterministic keep: the oldest row survives, the racing duplicate is retired.
    assert kept.id == first.id
    db_session.refresh(dupe)
    assert dupe.status == "retired"


def test_operator_renamed_chat_is_preserved_on_reconcile(db_session):
    # The NAWA workspace chat was renamed by hand; reconciliation must not
    # clobber a deliberate operator rename with the computed generic name.
    workspace = Workspace(id="ws-nawa-chat", name="Nawa", slug="nawa")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    system = ensure_workspace_chat_system_default(db_session, workspace.id)
    assert system.name == "Agentium Workspace Chat"

    system.name = "NAWA Workspace Chat"
    db_session.commit()

    reconciled = ensure_workspace_chat_system_default(db_session, workspace.id)
    assert reconciled is not None
    assert reconciled.id == system.id
    assert reconciled.name == "NAWA Workspace Chat"


def test_declared_chat_system_name_setting_is_applied_and_restored(db_session):
    workspace = Workspace(
        id="ws-branded-chat",
        name="Nawa",
        slug="nawa-branded",
        settings={"chat_system_name": "NAWA Workspace Chat"},
    )
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)

    system = ensure_workspace_chat_system_default(db_session, workspace.id)
    assert system is not None
    assert system.name == "NAWA Workspace Chat"

    # A declared name is configuration: reconciliation restores it even after
    # an accidental manual rename.
    system.name = "Accidental Rename"
    db_session.commit()

    reconciled = ensure_workspace_chat_system_default(db_session, workspace.id)
    assert reconciled is not None
    assert reconciled.name == "NAWA Workspace Chat"


def test_andritz_workspace_chat_inherits_industrial_profile(db_session):
    workspace = Workspace(
        id="ws-andritz-chat",
        name="Andritz",
        slug="andritz",
        settings={
            "family": "andritz",
            "assistant_profile_default": "andritz_spl_advisor",
            "knowledge_scopes": [
                {
                    "key": "andritz-spl-knowledge-experiment",
                    "collection_slugs": [
                        "andritz-secure-deposit",
                        "andritz-notices-techniques-spl-pilot",
                    ],
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
    resolved_id = _apply_workspace_chat_flow_defaults(
        db_session, workspace=workspace, request=request
    )
    assert resolved_id == system.id
    assert request.agent_id == system.id
    assert request.assistant_profile == "andritz_spl_advisor"
    assert request.knowledge_scope == "andritz-spl-knowledge-experiment"
    assert request.rag_pipeline_mode == "chah"
    assert request.top_k == 6
    assert request.system_prompt and "curated knowledge base" in request.system_prompt
    assert request.answer_policy and request.answer_policy["key"] == "industrial_answer_profile_v1"
    assert request.answer_profile == "precise_fact"
    assert request.answer_profile_decision["profile"] == "precise_fact"

    inventory_request = ChatRequest(query="Quels projets utilisent une pompe Uraca ?")
    _apply_workspace_chat_flow_defaults(db_session, workspace=workspace, request=inventory_request)
    assert inventory_request.answer_profile == "transversal_inventory"
    assert inventory_request.deep_retrieval is True
    assert inventory_request.latency_profile == "deep"
    assert inventory_request.retrieval_profile == "deep_async"

    manifest = serialize_flow_manifest(db_session, system)
    assert manifest["runtime_mode"] in {
        "dag_strict",
        "dag_overlay",
        "sequential_legacy",
    }
    assert manifest["runtime_mode_reason"]
    assert len(manifest["flow_sha256"]) == 64
    assert manifest["runtime_surface"] == "chat_runtime"
    effective = manifest["effective_config"]
    assert (
        effective["retrieval_config"]["runtime_read_path"]
        == "nodes.runtime.settings_budget.data.retrieval_defaults"
    )
    assert effective["grounding_policy"]["node_id"] == "skill.grounding_policy"
    assert effective["source_policy_config"]["value"]["mode"] == "industrial_grounding"

    prompt_stack = effective["prompt_stack"]
    assert "curated knowledge base" in prompt_stack["system_prompt"]
    assert prompt_stack["answer_policy"]["key"] == "industrial_answer_profile_v1"
    assert "transversal_inventory" in prompt_stack["answer_profiles"]
    assert prompt_stack["default_answer_profile"] == "precise_fact"
    assert prompt_stack["selected_reasoning_template"]["key"] == "factual"
    assert prompt_stack["selected_reasoning_template"]["template"]
    assert any(row["key"] == "trivial" for row in prompt_stack["available_reasoning_templates"])
    assert "citation_instructions" in prompt_stack["rag_user_prompt_contract"]

    builders = effective["runtime_builders"]
    assert builders["chat_defaults"].endswith("_apply_workspace_chat_flow_defaults")
    assert builders["rag_user_prompt_builder"].endswith("_build_rag_user_prompt")


def test_explicit_business_system_does_not_inherit_workspace_chat_branding_or_budgets(
    db_session,
):
    workspace = Workspace(
        id="ws-explicit-business-system",
        name="Showcase",
        slug="showcase-explicit-system",
        settings={"family": "showcase"},
    )
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    surface = ensure_workspace_chat_system_default(db_session, workspace.id)
    surface.flow_definition = {
        **surface.flow_definition,
        "chat": {
            "assistant_profile": "surface-only-profile",
            "knowledge_scope": "surface-only-scope",
            "retrieval_defaults": {"top_k": 99, "mode": "deep"},
        },
    }
    business = System(
        id="sys-explicit-business",
        workspace_id=workspace.id,
        name="Video Contract Risk",
        objective="Showcase business experience",
        status="active",
        settings={"system_type": "showcase_contract_risk"},
        flow_definition={"variant": "video_contract_risk", "nodes": []},
    )
    db_session.add(business)
    db_session.commit()
    request = ChatRequest(
        query="Analyse ce contrat",
        agent_id=business.id,
    )

    resolved_id = _apply_workspace_chat_flow_defaults(
        db_session,
        workspace=workspace,
        request=request,
    )

    assert resolved_id == business.id
    assert request.agent_id == business.id
    assert request.assistant_profile is None
    assert request.knowledge_scope is None
    assert request.top_k is None
    assert request.rag_pipeline_mode is None
    assert request.system_prompt is None


def test_sentinel_workspace_chat_reuses_aya_profile(db_session):
    workspace = Workspace(
        id="ws-sentinel-chat",
        name="SENTINEL-CI",
        slug="sentinel-ci",
        settings={
            "family": "sentinel_ci",
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


# ---------------------------------------------------------------------------
# Admin expert-correction toggle — authoritative through the precedence merge
# ---------------------------------------------------------------------------


def _set_workspace_source_policy(db_session, workspace, policy):
    workspace.settings = {**(workspace.settings or {}), "source_policy": policy}
    db_session.commit()
    db_session.refresh(workspace)


def _workspace_auth_client(db_session, user):
    app = FastAPI()
    app.include_router(auth_endpoint.router, prefix="/api/v1/auth")
    app.dependency_overrides[auth_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[auth_endpoint.get_db] = lambda: db_session
    return TestClient(app)


def test_workspace_member_cannot_edit_chat_source_policy_settings(db_session, monkeypatch):
    workspace = Workspace(
        id="ws-member-settings-denied",
        name="Member Settings Denied",
        slug="member-settings-denied",
        settings={
            "chat": {"title": "Stable chat settings"},
            "source_policy": {
                "expert_fiche_correction_enabled": False,
                "expert_review_required": True,
            },
        },
    )
    contributor = User(
        id="user-member-settings-denied",
        username="member-settings-denied",
        email="member-settings-denied@example.test",
    )
    db_session.add_all(
        [
            workspace,
            contributor,
            WorkspaceMember(
                user_id=contributor.id,
                workspace_id=workspace.id,
                role="member",
                role_template=WORKSPACE_CONTRIBUTOR,
            ),
        ]
    )
    seed_skills_and_capabilities(db_session)
    system = ensure_workspace_chat_system_default(db_session, workspace.id)
    before_workspace_settings = dict(workspace.settings or {})
    before_system_settings = dict(system.settings or {})
    db_session.commit()

    def _unexpected_sync(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("workspace settings sync must not run for denied members")

    monkeypatch.setattr(
        "app.services.systems.bootstrap.sync_chat_system_expert_correction_policy",
        _unexpected_sync,
    )

    response = _workspace_auth_client(db_session, contributor).patch(
        f"/api/v1/auth/workspaces/{workspace.slug}",
        json={
            "settings": {
                "source_policy": {
                    "expert_fiche_correction_enabled": True,
                    "expert_review_required": False,
                }
            }
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"
    db_session.refresh(workspace)
    db_session.refresh(system)
    assert workspace.settings == before_workspace_settings
    assert system.settings == before_system_settings
    resolved = resolve_workspace_chat_source_policy(db_session, workspace)
    assert resolved.get("expert_fiche_correction_enabled") is False
    assert resolved.get("expert_review_required") is True


def test_expert_correction_toggle_is_authoritative_through_resolver(db_session):
    """The admin toggle must survive the chat System SHADOWING the workspace.

    ``resolve_workspace_chat_source_policy`` merges the chat System policy OVER
    the workspace one, so a workspace-only write can be silently overridden by a
    System-level flag (the Andritz state produced by migration 042). Syncing the
    two layers (``sync_chat_system_expert_correction_policy``) makes the toggle
    authoritative end-to-end, for both ON and OFF.
    """
    workspace = Workspace(id="ws-expert-toggle", name="Toggle WS", slug="toggle-ws")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    system = ensure_workspace_chat_system_default(db_session, workspace.id)
    assert system is not None

    # Baseline: neither layer sets the expert flag.
    assert "expert_fiche_correction_enabled" not in resolve_workspace_chat_source_policy(
        db_session, workspace
    )

    # Reproduce the precedence trap: System shadows with the flag OFF while the
    # workspace tries to turn it ON.
    system.settings = {
        **(system.settings or {}),
        "source_policy": {
            **((system.settings or {}).get("source_policy") or {}),
            "expert_fiche_correction_enabled": False,
        },
    }
    db_session.commit()
    _set_workspace_source_policy(db_session, workspace, {"expert_fiche_correction_enabled": True})
    trapped = resolve_workspace_chat_source_policy(db_session, workspace)
    assert trapped.get("expert_fiche_correction_enabled") is False  # trap reproduced

    # Sync converges the layers (mirrors migration 042) -> ON is honoured.
    sync_chat_system_expert_correction_policy(db_session, workspace)
    resolved_on = resolve_workspace_chat_source_policy(db_session, workspace)
    assert resolved_on.get("expert_fiche_correction_enabled") is True

    # Toggle OFF: workspace False + sync -> resolver returns False.
    _set_workspace_source_policy(db_session, workspace, {"expert_fiche_correction_enabled": False})
    sync_chat_system_expert_correction_policy(db_session, workspace)
    resolved_off = resolve_workspace_chat_source_policy(db_session, workspace)
    assert resolved_off.get("expert_fiche_correction_enabled") is False


def test_sync_only_touches_keys_present_in_workspace_policy(db_session):
    """Unrelated settings saves must not clobber an existing System-level flag.

    The sync only mirrors the expert-correction keys that are explicitly present
    in the workspace ``source_policy``, so e.g. an Andritz workspace whose flag
    lives on the chat System keeps it after a save that omits ``source_policy``.
    """
    workspace = Workspace(id="ws-expert-keep", name="Keep WS", slug="keep-ws")
    db_session.add(workspace)
    seed_skills_and_capabilities(db_session)
    system = ensure_workspace_chat_system_default(db_session, workspace.id)
    system.settings = {
        **(system.settings or {}),
        "source_policy": {
            **((system.settings or {}).get("source_policy") or {}),
            "expert_fiche_correction_enabled": True,
        },
    }
    db_session.commit()

    # Workspace settings carry no source_policy at all -> sync is a no-op.
    workspace.settings = {"chat": {"title": "Hello"}}
    db_session.commit()
    db_session.refresh(workspace)
    sync_chat_system_expert_correction_policy(db_session, workspace)

    resolved = resolve_workspace_chat_source_policy(db_session, workspace)
    assert resolved.get("expert_fiche_correction_enabled") is True


# ---------------------------------------------------------------------------
# Capture endpoint 403/accept driven by the REAL resolved policy
# ---------------------------------------------------------------------------


def _chat_correction_client(db_session, workspace, user, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.endpoints import knowledge_capture as kc_endpoint

    app = FastAPI()
    app.include_router(kc_endpoint.router, prefix="/api/v1/knowledge-capture")
    app.dependency_overrides[kc_endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[kc_endpoint.get_current_user] = lambda: user
    app.dependency_overrides[kc_endpoint.get_db] = lambda: db_session
    monkeypatch.setattr(kc_endpoint, "enforce_permission", lambda *a, **k: None)
    return TestClient(app)


def test_chat_correction_endpoint_403_when_toggle_off(db_session, monkeypatch):
    from app.models.user import User

    workspace = Workspace(id="ws-cc-toggle-off", name="Andritz", slug="andritz")
    user = User(id="user-cc-toggle-off", username="reviewer", email="rev-off@demo.test")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)
    ensure_workspace_chat_system_default(db_session, workspace.id)

    # Toggle OFF (write workspace + sync the chat System).
    _set_workspace_source_policy(db_session, workspace, {"expert_fiche_correction_enabled": False})
    sync_chat_system_expert_correction_policy(db_session, workspace)

    client = _chat_correction_client(db_session, workspace, user, monkeypatch)
    response = client.post(
        "/api/v1/knowledge-capture/chat-correction",
        json={"query": "q", "answer": "a", "correction": "c précise."},
    )
    assert response.status_code == 403


def test_chat_correction_endpoint_accepts_when_toggle_on(db_session, monkeypatch):
    from app.models.user import User

    workspace = Workspace(id="ws-cc-toggle-on", name="Andritz", slug="andritz")
    user = User(id="user-cc-toggle-on", username="reviewer", email="rev-on@demo.test")
    db_session.add_all([workspace, user])
    seed_skills_and_capabilities(db_session)
    system = ensure_workspace_chat_system_default(db_session, workspace.id)

    # Precedence trap: the chat System shadows with the flag OFF.
    system.settings = {
        **(system.settings or {}),
        "source_policy": {
            **((system.settings or {}).get("source_policy") or {}),
            "expert_fiche_correction_enabled": False,
        },
    }
    db_session.commit()

    # Toggle ON (review still required by default) + sync -> overrides the shadow.
    _set_workspace_source_policy(
        db_session,
        workspace,
        {"expert_fiche_correction_enabled": True, "expert_review_required": True},
    )
    sync_chat_system_expert_correction_policy(db_session, workspace)

    client = _chat_correction_client(db_session, workspace, user, monkeypatch)
    response = client.post(
        "/api/v1/knowledge-capture/chat-correction",
        json={
            "query": "Quelle est la pression nominale ?",
            "answer": "5 bar",
            "correction": "La pression nominale est 7 bar, pas 5 bar.",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending_review"
