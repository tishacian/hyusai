from __future__ import annotations

from scripts import seed_showcase_workspace as seed

from app.api.v1.endpoints.runs import _invocation
from app.models.audit import AuditLog
from app.models.context import Context
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob


def test_ensure_workspace_reconciles_portfolio_contract_idempotently(db_session):
    slug = "agentium-showcase-portfolio-contract-test"

    created = seed.ensure_workspace(db_session, slug, "Agentium Showcase Portfolio Contract")

    assert created.mode == "portfolio"
    assert created.settings == {
        "showcase_seed": True,
        "persona_nav": "full",
        "features": {"cockpit_router_axes_v3": True},
    }

    workspace_id = created.id
    created.mode = "builder"
    created.settings = {
        "showcase_seed": False,
        "persona_nav": "operator-override",
        "features": {"chat_document_upload": False},
        "operator_preferences": {"density": "compact"},
        "custom_flag": "preserve-me",
    }
    db_session.commit()

    reconciled = seed.ensure_workspace(db_session, slug, "Agentium Showcase Reconciled")

    assert reconciled.id == workspace_id
    assert reconciled.name == "Agentium Showcase Reconciled"
    assert reconciled.mode == "portfolio"
    assert reconciled.settings == {
        "showcase_seed": True,
        "persona_nav": "full",
        "features": {
            "chat_document_upload": False,
            "cockpit_router_axes_v3": True,
        },
        "operator_preferences": {"density": "compact"},
        "custom_flag": "preserve-me",
    }

    expected_settings = dict(reconciled.settings)
    db_session.expire_all()
    reconciled_again = seed.ensure_workspace(db_session, slug, "Agentium Showcase Reconciled")

    assert reconciled_again.id == workspace_id
    assert reconciled_again.mode == "portfolio"
    assert reconciled_again.settings == expected_settings
    assert db_session.query(Workspace).filter(Workspace.slug == slug).count() == 1

    reconciled_again.settings = {"features": "malformed", "custom_flag": "keep"}
    db_session.commit()
    malformed = seed.ensure_workspace(db_session, slug, "Agentium Showcase Reconciled")
    assert malformed.settings == {
        "showcase_seed": True,
        "persona_nav": "full",
        "features": {"cockpit_router_axes_v3": True},
        "custom_flag": "keep",
    }


def test_showcase_seed_builds_pmi_translation_suite_story(db_session):
    workspace = seed.ensure_workspace(db_session, "agentium-showcase-test", "Agentium Showcase Test")
    owner = seed.ensure_member(db_session, workspace, "owner@example.test", role="owner")
    seed.seed_skills_and_capabilities(db_session)
    seed.ensure_eval_preset(db_session, workspace)
    policies = seed.ensure_policies(db_session, workspace)
    capabilities = seed.ensure_capabilities(db_session, workspace)
    systems = seed.ensure_systems(db_session, workspace, capabilities, policies)
    seed.ensure_context(db_session, workspace, systems)

    result = seed.seed_story(db_session, workspace, owner, systems, capabilities)

    translation_system = systems["translation"]
    translation_capability = capabilities["showcase_translation_suite"]
    translation_context = (
        db_session.query(Context)
        .filter(Context.workspace_id == workspace.id, Context.system_id == translation_system.id)
        .one()
    )
    translation_runs = (
        db_session.query(Run)
        .filter(Run.workspace_id == workspace.id, Run.system_id == translation_system.id)
        .all()
    )
    blocked = next(run for run in translation_runs if run.decision == "BLOCK_RELEASE")
    replay = next(run for run in translation_runs if run.parent_run_id == blocked.id)
    accepted = next(
        run
        for run in translation_runs
        if run.decision == "ACCEPT_4D" and run.parent_run_id is None
    )

    assert result["runs"] >= 14
    assert translation_system.flow_definition["variant"] == "translation_suite"
    assert "trans_sys_prompt_agent_2_only.txt" in (
        translation_system.flow_definition["prompt_contract"]["system_prompt_builder"]["source_files"][1]
    )
    flow_nodes = {node["id"]: node for node in translation_system.flow_definition["nodes"]}
    prompt_owned_nodes = [
        node
        for node in translation_system.flow_definition["nodes"]
        if node["kind"] in {"task", "decision", "hitl"}
    ]
    assert all(node["data"]["prompt_contract"]["system_prompt"] for node in prompt_owned_nodes)

    fanout_prompt_contract = flow_nodes["fanout"]["data"]["prompt_contract"]
    assert "CDC E1 STRICT" in fanout_prompt_contract["system_prompt"]
    assert "{target_lang}" in fanout_prompt_contract["system_prompt"]
    assert "trans_sys_prompt_agent_2_only.txt" in fanout_prompt_contract["system_prompt_builder"]["source_files"][0]
    assert "Output only translated DITA XML for the target locale." in fanout_prompt_contract["answer_shaping_instructions"]

    qa_prompt_contract = flow_nodes["qa_loop"]["data"]["prompt_contract"]
    assert "Compare source and target XML line by line" in qa_prompt_contract["system_prompt"]
    assert "check_sys_prompt.txt" in qa_prompt_contract["system_prompt_builder"]["source_files"][0]
    assert translation_system.context_id == translation_context.id
    assert translation_system.control_policy_id == policies["translation_control"].id
    assert translation_system.adaptive_policy_id == policies["translation_adaptive"].id
    assert translation_system.settings["translation_suite"]["security"]["sovereignty"]["external_llm_egress"] is False
    assert translation_capability.confidence_threshold == 0.94
    assert len(translation_runs) == 4
    assert replay.replay_overrides["preserve_conkeyref_byte_equal"] is True
    assert replay.output_ref["topics_replayed"] == 3
    assert "translation_memory:renault_kangoo3_reviewed" in translation_context.memory_refs

    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == accepted.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    assert [row.skill_slug for row in invocations[:3]] == [
        "translation_archive_ingest_v1",
        "translation_memory_retrieve_v1",
        "translation_label_index_resolve_v1",
    ]
    assert invocations[-1].skill_slug == "audit_log_v1"
    assert invocations[0].trace["agent_identity"] == "agent.translation.ingest"

    api_payload = _invocation(invocations[0])
    assert api_payload["input_ref"]["agent_identity"] == "agent.translation.ingest"
    assert api_payload["output_ref"]["showcase_seed"] is True
    assert api_payload["trace"]["source_architecture_ref"] == "project-mt/OM/generic_code"

    job_kinds = {
        row.kind
        for row in db_session.query(WorkspaceJob).filter(WorkspaceJob.workspace_id == workspace.id).all()
    }
    assert {
        "translation_suite_batch",
        "translation_suite_guardrail",
        "translation_suite_replay",
        "translation_suite_delivery",
    } <= job_kinds

    decisions = (
        db_session.query(Decision)
        .filter(Decision.workspace_id == workspace.id, Decision.target_id.in_([blocked.id, replay.id]))
        .all()
    )
    assert any(decision.kind == "guardrail_block" for decision in decisions)

    event_types = {
        row.event_type
        for row in db_session.query(AuditLog).filter(AuditLog.workspace_id == workspace.id).all()
    }
    assert "translation_suite.guardrail.blocked" in event_types
    assert "translation_suite.delivery.accepted" in event_types
