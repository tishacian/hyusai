from __future__ import annotations

import copy
import json

import pytest

from app.api.v1.endpoints.runs import _invocation
from app.core.config import settings
from app.models.audit import AuditLog
from app.models.context import Context
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from scripts import seed_showcase_workspace as seed


def test_ensure_workspace_reconciles_portfolio_contract_idempotently(db_session):
    slug = "agentium-showcase-portfolio-contract-test"

    created = seed.ensure_workspace(db_session, slug, "Agentium Showcase Portfolio Contract")

    assert created.mode == "portfolio"
    assert created.settings == {
        "showcase_seed": True,
        "persona_nav": "full",
        "features": {
            "cockpit_router_axes_v3": True,
            "cockpit_router_axes_v4": False,
            "system_360_projection_v1": False,
            "capability_360_projection_v1": False,
            "run_360_projection_v1": False,
            "skill_invocation_360_projection_v1": False,
            "value_loop_v1": False,
            "flow_v3_dag_authoritative": False,
            "sap_hana_connector": True,
            "rpa_bridge": True,
            "model_portal_beta": True,
            "enable_event_triggers": True,
        },
        "event_triggers": {"enabled": True, "showcase_seed": True},
        "catalog": {"enabled_skills": ["sap_hana_query_v1", "rpa_dispatch_v1"]},
        "apps": {"enabled": ["rpa_bridge"]},
    }

    workspace_id = created.id
    created.mode = "builder"
    created.settings = {
        "showcase_seed": True,
        "persona_nav": "operator-override",
        "features": {
            "chat_document_upload": False,
            "cockpit_router_axes_v4": True,
            "system_360_projection_v1": True,
            "flow_v3_dag_authoritative": True,
        },
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
            "cockpit_router_axes_v4": True,
            "system_360_projection_v1": True,
            "capability_360_projection_v1": False,
            "run_360_projection_v1": False,
            "skill_invocation_360_projection_v1": False,
            "value_loop_v1": False,
            "flow_v3_dag_authoritative": True,
            "sap_hana_connector": True,
            "rpa_bridge": True,
            "model_portal_beta": True,
            "enable_event_triggers": True,
        },
        "event_triggers": {"enabled": True, "showcase_seed": True},
        "catalog": {"enabled_skills": ["sap_hana_query_v1", "rpa_dispatch_v1"]},
        "apps": {"enabled": ["rpa_bridge"]},
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

    reconciled_again.settings = {
        "showcase_seed": True,
        "features": "malformed",
        "custom_flag": "keep",
    }
    db_session.commit()
    malformed = seed.ensure_workspace(db_session, slug, "Agentium Showcase Reconciled")
    assert malformed.settings == {
        "showcase_seed": True,
        "persona_nav": "full",
        "features": {
            "capability_360_projection_v1": False,
            "run_360_projection_v1": False,
            "skill_invocation_360_projection_v1": False,
            "value_loop_v1": False,
            "cockpit_router_axes_v3": True,
            "sap_hana_connector": True,
            "rpa_bridge": True,
            "model_portal_beta": True,
            "enable_event_triggers": True,
        },
        "event_triggers": {"enabled": True, "showcase_seed": True},
        "catalog": {"enabled_skills": ["sap_hana_query_v1", "rpa_dispatch_v1"]},
        "apps": {"enabled": ["rpa_bridge"]},
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
    contract_system = systems["contract"]
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
    assert capabilities["video_contract_risk"].id == contract_system.capability_id
    assert contract_system.settings["experience"] == {
        "system_360_canary": "v1",
        "value_loop_canary": "v1",
    }
    assert contract_system.settings["steering_model"]["version"] == "contract-risk-v1"
    assert contract_system.flow_definition["schema_version"] == 3
    assert contract_system.flow_definition["io_mode"] == "strict"
    assert [node["config"]["skill_slug"] for node in contract_system.flow_definition["nodes"]] == [
        "semantic_search_v1",
        "llm_rag_answer_v1",
        "claim_audit_v1",
        "audit_log_v1",
    ]
    assert contract_system.context_id is not None
    assert contract_system.control_policy_id == policies["contract_control"].id
    membrane = policies["contract_control"].extra["membrane_spec"]
    assert policies["contract_control"].target_id == contract_system.id
    assert membrane["version"] == 2
    assert membrane["enforcement_mode"] == "shadow"
    assert membrane["provenance"]["object_store_prefix"] == f"system-360/{contract_system.id}"
    assert "control_policy.guardrails.patch.v1" in membrane["capabilities"]["allowed_actions"]
    assert workspace.settings["features"]["value_loop_v1"] is False
    actuator = contract_system.settings["value_loop"]["actuators"][
        "control_policy.guardrails.patch.v1"
    ]
    assert actuator["enabled"] is True
    canaries = [
        row
        for row in db_session.query(System).filter(System.workspace_id == workspace.id).all()
        if ((row.settings or {}).get("experience") or {}).get("system_360_canary") == "v1"
    ]
    assert [row.id for row in canaries] == [contract_system.id]
    versions = (
        db_session.query(SystemVersion)
        .filter(SystemVersion.system_id == contract_system.id)
        .order_by(SystemVersion.version_number.asc())
        .all()
    )
    assert versions[-1].flow_definition == contract_system.flow_definition
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

    before_runs = db_session.query(Run).filter(Run.workspace_id == workspace.id).count()
    before_evals = result["evals"]
    repeated = seed.seed_story(db_session, workspace, owner, systems, capabilities)
    assert repeated["runs"] == before_runs
    assert repeated["evals"] == before_evals
    assert db_session.query(Run).filter(Run.workspace_id == workspace.id).count() == before_runs


def test_showcase_reconciliation_versions_configuration_append_only_without_data_loss(
    db_session,
    monkeypatch,
):
    workspace = seed.ensure_workspace(
        db_session,
        "agentium-showcase-append-only-test",
        "Agentium Showcase Append-only Test",
    )
    seed.seed_skills_and_capabilities(db_session)
    policies = seed.ensure_policies(db_session, workspace)
    capabilities = seed.ensure_capabilities(db_session, workspace)
    systems = seed.ensure_systems(db_session, workspace, capabilities, policies)
    seed.ensure_context(db_session, workspace, systems)

    contract = systems["contract"]
    compliance = systems["compliance"]
    policy = policies["contract_control"]
    contract_context = db_session.get(Context, contract.context_id)
    assert contract_context is not None
    historical_versions = (
        db_session.query(SystemVersion)
        .filter(SystemVersion.workspace_id == workspace.id)
        .order_by(SystemVersion.system_id, SystemVersion.version_number)
        .all()
    )
    historical_state = {
        row.id: {
            "system_id": row.system_id,
            "version_number": row.version_number,
            "flow_definition": copy.deepcopy(row.flow_definition),
            "configuration_snapshot": copy.deepcopy(row.configuration_snapshot),
            "message": row.message,
            "created_by": row.created_by,
        }
        for row in historical_versions
    }

    preserved_run = Run(
        id="showcase-append-only-run",
        workspace_id=workspace.id,
        system_id=contract.id,
        status="completed",
        input_ref={"query": "preserve this Run"},
        output_ref={"answer": "preserve this result"},
    )
    preserved_decision = Decision(
        id="showcase-append-only-decision",
        workspace_id=workspace.id,
        scope="system",
        target_id=contract.id,
        kind="recommendation",
        status="proposed",
        title="Preserve this Decision",
    )
    preserved_audit = AuditLog(
        id="showcase-append-only-audit",
        workspace_id=workspace.id,
        event_type="showcase.test.preserved",
        actor="test",
        details={"must_survive": True},
    )
    preserved_evaluation = EvaluationScore(
        id="showcase-append-only-evaluation",
        workspace_id=workspace.id,
        run_id=preserved_run.id,
        query="preserve this evaluation",
        scores={"groundedness": 1.0},
        composite_score=100.0,
    )
    db_session.add_all(
        [
            preserved_run,
            preserved_decision,
            preserved_audit,
            preserved_evaluation,
        ]
    )

    # Manufacture values that the normal, non-reset seed will actually repair.
    # Their distinctive content lets the assertions prove that audits and
    # snapshots never persist the values themselves.
    policy.max_cost_per_decision = 47.5
    policy.allowed_models = ["must-never-appear-in-audit-model"]
    contract.objective = "must-never-appear-in-audit-objective"
    contract_context.data_refs = ["must-never-appear-in-audit-context"]
    contract_settings = copy.deepcopy(contract.settings)
    contract_settings["experience"] = {}
    contract_settings["steering_model"] = {
        "private_seed_value": "must-never-appear-in-audit-setting"
    }
    contract.settings = contract_settings
    compliance_settings = copy.deepcopy(compliance.settings)
    compliance_settings["experience"] = {
        "system_360_canary": "v1",
        "value_loop_canary": "v1",
    }
    compliance.settings = compliance_settings
    db_session.commit()

    version_ids_before = set(historical_state)
    audit_ids_before = {
        row.id
        for row in db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .all()
    }
    monkeypatch.setattr(settings, "custom_chain_version_window", 1)
    recorded_transitions = []
    real_append = seed._append_showcase_configuration_version

    def _recording_append(db, *, system, control_policy, context=None, before):
        recorded_transitions.append(
            (
                system.id,
                copy.deepcopy(dict(before)),
                seed._tracked_showcase_configuration(
                    system,
                    control_policy=control_policy,
                    context=context,
                ),
            )
        )
        return real_append(
            db,
            system=system,
            control_policy=control_policy,
            context=context,
            before=before,
        )

    monkeypatch.setattr(seed, "_append_showcase_configuration_version", _recording_append)

    reconciled_policies = seed.ensure_policies(db_session, workspace)
    reconciled_systems = seed.ensure_systems(
        db_session,
        workspace,
        capabilities,
        reconciled_policies,
    )
    seed.ensure_context(db_session, workspace, reconciled_systems)

    all_versions = (
        db_session.query(SystemVersion)
        .filter(SystemVersion.workspace_id == workspace.id)
        .order_by(SystemVersion.system_id, SystemVersion.version_number)
        .all()
    )
    versions_by_id = {row.id: row for row in all_versions}
    assert version_ids_before < set(versions_by_id)
    # ``purge=False`` is part of the seed contract: even a window of one cannot
    # remove or rewrite an older version.
    for version_id, expected in historical_state.items():
        row = versions_by_id[version_id]
        assert {
            "system_id": row.system_id,
            "version_number": row.version_number,
            "flow_definition": row.flow_definition,
            "configuration_snapshot": row.configuration_snapshot,
            "message": row.message,
            "created_by": row.created_by,
        } == expected

    new_versions = [row for row in all_versions if row.id not in version_ids_before]
    assert new_versions
    assert all(row.configuration_snapshot is not None for row in new_versions)
    for row in new_versions:
        snapshot = row.configuration_snapshot
        assert set(snapshot) == {"schema_version", "bindings", "transition"}
        assert set(snapshot["bindings"]) <= {
            "control_policy_id",
            "adaptive_policy_id",
            "context_id",
        }
        assert set(snapshot["transition"]) == {
            "kind",
            "previous_control_policy_id",
            "enforcement_mode",
            "source_contract_sha256",
            "target_contract_sha256",
        }
        assert snapshot["transition"]["kind"] == "showcase_seed_reconcile"
    contract_transitions = sorted(
        (row for row in new_versions if row.system_id == contract.id),
        key=lambda row: row.version_number,
    )
    assert len(contract_transitions) == 3
    effective_contract_states = [
        (before, after)
        for system_id, before, after in recorded_transitions
        if system_id == contract.id and before != after
    ]
    assert len(effective_contract_states) == 3
    for previous, following in zip(
        effective_contract_states,
        effective_contract_states[1:],
    ):
        assert previous[1] == following[0]
    assert [
        (
            row.configuration_snapshot["transition"]["source_contract_sha256"],
            row.configuration_snapshot["transition"]["target_contract_sha256"],
        )
        for row in contract_transitions
    ] == [
        (
            seed._seed_configuration_sha256(before),
            seed._seed_configuration_sha256(after),
        )
        for before, after in effective_contract_states
    ]
    for previous, following in zip(contract_transitions, contract_transitions[1:]):
        assert (
            previous.configuration_snapshot["transition"]["target_contract_sha256"]
            == following.configuration_snapshot["transition"][
                "source_contract_sha256"
            ]
        )

    new_configuration_audits = [
        row
        for row in db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == seed.SHOWCASE_CONFIGURATION_AUDIT_EVENT,
        )
        .all()
        if row.id not in audit_ids_before
    ]
    assert new_configuration_audits
    assert {row.id for row in new_versions} == {
        row.details["version_id"] for row in new_configuration_audits
    }
    changed_fields = {
        field
        for row in new_configuration_audits
        for field in row.details["changed_fields"]
    }
    assert {
        "control_policy.max_cost_per_decision",
        "control_policy.allowed_models",
        "system.objective",
        "system.settings.experience.system_360_canary",
        "system.settings.experience.value_loop_canary",
        "system.settings.steering_model",
        "context.data_refs",
    } <= changed_fields
    for row in new_configuration_audits:
        assert set(row.details) == {
            "system_id",
            "version_id",
            "version_number",
            "changed_fields",
            "changed_field_count",
        }
        assert row.details["changed_fields"] == sorted(row.details["changed_fields"])
        assert row.details["changed_field_count"] == len(row.details["changed_fields"])

    all_new_audit_details = [
        row.details
        for row in db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .all()
        if row.id not in audit_ids_before
    ]
    serialized_evidence = json.dumps(
        {
            "snapshots": [row.configuration_snapshot for row in new_versions],
            "audits": all_new_audit_details,
        },
        sort_keys=True,
    )
    assert "must-never-appear-in-audit-model" not in serialized_evidence
    assert "must-never-appear-in-audit-objective" not in serialized_evidence
    assert "must-never-appear-in-audit-context" not in serialized_evidence
    assert "must-never-appear-in-audit-setting" not in serialized_evidence

    assert db_session.get(Run, preserved_run.id) is not None
    assert db_session.get(EvaluationScore, preserved_evaluation.id) is not None
    assert db_session.get(Decision, preserved_decision.id) is not None
    assert db_session.get(AuditLog, preserved_audit.id) is not None
    assert audit_ids_before <= {
        row.id
        for row in db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .all()
    }
    assert all(
        workspace.settings["features"][flag] is False
        for flag in (
            "cockpit_router_axes_v4",
            "system_360_projection_v1",
            "capability_360_projection_v1",
            "run_360_projection_v1",
            "skill_invocation_360_projection_v1",
            "value_loop_v1",
            "flow_v3_dag_authoritative",
        )
    )

    version_count = len(all_versions)
    system_updated_at_before = {
        row.id: row.updated_at
        for row in db_session.query(System)
        .filter(System.workspace_id == workspace.id)
        .all()
    }
    configuration_audit_count = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == seed.SHOWCASE_CONFIGURATION_AUDIT_EVENT,
        )
        .count()
    )
    repeated_policies = seed.ensure_policies(db_session, workspace)
    repeated_systems = seed.ensure_systems(
        db_session,
        workspace,
        capabilities,
        repeated_policies,
    )
    seed.ensure_context(db_session, workspace, repeated_systems)
    assert (
        db_session.query(SystemVersion)
        .filter(SystemVersion.workspace_id == workspace.id)
        .count()
        == version_count
    )
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.workspace_id == workspace.id,
            AuditLog.event_type == seed.SHOWCASE_CONFIGURATION_AUDIT_EVENT,
        )
        .count()
        == configuration_audit_count
    )
    assert {
        row.id: row.updated_at
        for row in db_session.query(System)
        .filter(System.workspace_id == workspace.id)
        .all()
    } == system_updated_at_before


def test_showcase_reconciliation_fails_closed_before_mutation_when_system_is_ambiguous(
    db_session,
):
    workspace = seed.ensure_workspace(
        db_session,
        "agentium-showcase-ambiguous-test",
        "Agentium Showcase Ambiguous Test",
    )
    seed.seed_skills_and_capabilities(db_session)
    policies = seed.ensure_policies(db_session, workspace)
    capabilities = seed.ensure_capabilities(db_session, workspace)
    systems = seed.ensure_systems(db_session, workspace, capabilities, policies)
    seed.ensure_context(db_session, workspace, systems)

    contract = systems["contract"]
    attacked_settings = copy.deepcopy(contract.settings)
    attacked_settings["steering_model"] = {"operator_value": "must-survive"}
    contract.settings = attacked_settings
    duplicate = System(
        id="showcase-ambiguous-contract-system",
        workspace_id=workspace.id,
        name=seed.CONTRACT_RISK_SYSTEM_NAME,
        objective="Deliberate duplicate used to prove fail-closed selection.",
        settings={"showcase_seed": False},
    )
    db_session.add(duplicate)
    db_session.commit()

    version_ids_before = {
        row.id
        for row in db_session.query(SystemVersion)
        .filter(SystemVersion.workspace_id == workspace.id)
        .all()
    }
    audit_ids_before = {
        row.id
        for row in db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .all()
    }

    with pytest.raises(
        seed.ShowcaseSeedAmbiguityError,
        match="found 2 Contract Risk Copilot System rows",
    ):
        seed.ensure_systems(db_session, workspace, capabilities, policies)
    db_session.rollback()

    assert (
        db_session.query(System)
        .filter(
            System.workspace_id == workspace.id,
            System.name == seed.CONTRACT_RISK_SYSTEM_NAME,
        )
        .count()
        == 2
    )
    assert db_session.get(System, contract.id).settings == attacked_settings
    assert {
        row.id
        for row in db_session.query(SystemVersion)
        .filter(SystemVersion.workspace_id == workspace.id)
        .all()
    } == version_ids_before
    assert {
        row.id
        for row in db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .all()
    } == audit_ids_before


def test_showcase_policy_reconciliation_rolls_back_mutation_version_and_audits_together(
    db_session,
    monkeypatch,
):
    workspace = seed.ensure_workspace(
        db_session,
        "agentium-showcase-atomic-test",
        "Agentium Showcase Atomic Test",
    )
    seed.seed_skills_and_capabilities(db_session)
    policies = seed.ensure_policies(db_session, workspace)
    capabilities = seed.ensure_capabilities(db_session, workspace)
    systems = seed.ensure_systems(db_session, workspace, capabilities, policies)
    seed.ensure_context(db_session, workspace, systems)

    policy = policies["contract_control"]
    policy.max_cost_per_decision = 47.5
    db_session.commit()
    version_ids_before = {
        row.id
        for row in db_session.query(SystemVersion)
        .filter(SystemVersion.workspace_id == workspace.id)
        .all()
    }
    audit_ids_before = {
        row.id
        for row in db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .all()
    }

    class _AuditWriteFailure:
        def __init__(self, **_kwargs):
            raise RuntimeError("synthetic audit write failure")

    monkeypatch.setattr(seed, "AuditLog", _AuditWriteFailure)
    with pytest.raises(RuntimeError, match="synthetic audit write failure"):
        seed.ensure_policies(db_session, workspace)
    db_session.rollback()

    assert db_session.get(type(policy), policy.id).max_cost_per_decision == 47.5
    assert {
        row.id
        for row in db_session.query(SystemVersion)
        .filter(SystemVersion.workspace_id == workspace.id)
        .all()
    } == version_ids_before
    assert {
        row.id
        for row in db_session.query(AuditLog)
        .filter(AuditLog.workspace_id == workspace.id)
        .all()
    } == audit_ids_before
