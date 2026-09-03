"""Every workspace owns an agentic chat System; Andritz keeps the one it has."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.models.policy import ControlPolicy
from app.models.system import System
from app.models.workspace import Workspace
from app.services import chat_execution_policy as policy
from app.services.chat_agentic_contract import (
    ANDRITZ_MIGRATION_FLOW_REVISION,
    EXPECTED_FLOW_CONTRACT_SHA256,
    TEMPLATE_FLOW_REVISION,
    agentic_flow_contract_digest,
    is_expected_agentic_flow,
)
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.systems import agentic_chat_bootstrap as boot
from app.services.systems import agentic_chat_template as tpl


@pytest.fixture(autouse=True)
def _agentic_master_switch_on(monkeypatch):
    monkeypatch.setattr(policy.settings, "enable_agentic_chat", True)


def _workspace(db_session, *, slug: str, settings: dict | None = None) -> Workspace:
    workspace = Workspace(id=f"ws-{slug}", name=slug.upper(), slug=slug, settings=settings or {})
    db_session.add(workspace)
    db_session.flush()
    return workspace


def _agentic_systems(db_session, workspace_id: str) -> list[System]:
    rows = (
        db_session.query(System)
        .filter(System.workspace_id == workspace_id, System.status != "retired")
        .all()
    )
    return [r for r in rows if (r.settings or {}).get("system_type") == "chat_agentic"]


def test_a_generic_workspace_gets_the_template_a_membrane_and_an_inert_policy(db_session):
    workspace = _workspace(db_session, slug="acme")
    seed_skills_and_capabilities(db_session)

    system = boot.ensure_workspace_agentic_chat_system_default(db_session, workspace.id)

    assert system is not None
    assert system.name == boot.WORKSPACE_AGENTIC_CHAT_SYSTEM_NAME
    assert system.created_by == boot.AGENTIC_CHAT_SEED_ACTOR
    assert system.default_model is None
    assert system.settings["system_type"] == "chat_agentic"
    assert system.settings["flow_revision"] == TEMPLATE_FLOW_REVISION
    assert system.settings["chat_profile"]["slug"] == "acme"
    assert system.settings["chat_profile"]["industrial"] is False
    assert system.settings["retrieval_contract"] == {
        "asset_binding": "workspace",
        "allow_workspace_fallback": True,
    }
    assert system.flow_definition["variant"] == "chat_agentic_thinking_v1"
    assert system.execution_profile["max_runtime_s"] == 40
    # The contract module recognises the template revision from the profile.
    assert is_expected_agentic_flow(system.settings, system.flow_definition)

    # Every skill the graph names is bound to the System and to its node.
    slugs = tpl.flow_skill_slugs(system.flow_definition)
    assert len(system.skill_ids) == len(slugs) >= 6
    for node in system.flow_definition["nodes"]:
        config = node.get("config") or {}
        if config.get("skill_slug"):
            assert config["skill_id"] in system.skill_ids
    assert "andritz" not in json.dumps(
        [n.get("config") for n in system.flow_definition["nodes"]]
    ).lower()

    membrane = db_session.query(ControlPolicy).filter(ControlPolicy.id == system.control_policy_id).one()
    assert membrane.scope == "system" and membrane.target_id == system.id
    assert membrane.extra["membrane_origin"] == boot.AGENTIC_CHAT_SEED_ACTOR
    assert membrane.extra["membrane_spec"]["inbound"]["industrial_grounding"] is False
    assert membrane.extra["membrane_spec"]["provenance"]["object_store_prefix"] == (
        "membrane/acme/chat-agentic/"
    )
    assert membrane.allowed_skills == membrane.extra["membrane_spec"]["capabilities"]["allowed_skills"]
    assert membrane.max_latency_ms == 45000

    db_session.refresh(workspace)
    assert workspace.settings["chat_execution"] == boot.default_chat_execution_policy()
    assert workspace.settings["chat_execution"]["mode"] == "hybrid"
    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 0

    # Behaviour is unchanged: a plain turn stays classic, but the target now
    # exists and is what an operator canary would force.
    decision = policy.resolve_chat_execution(
        db_session,
        workspace=workspace,
        requested_system_id=None,
        session_id="s1",
        answer_profile="precise_fact",
    )
    assert decision.route == "classic"
    assert decision.reason == "hybrid_profile_classic"
    assert decision.executor_system.id == system.id
    niche = policy.resolve_chat_execution(
        db_session,
        workspace=workspace,
        requested_system_id=None,
        session_id="s1",
        answer_profile="comparison",
    )
    assert (niche.route, niche.reason) == ("classic", "rollout_cohort_classic")
    forced = policy.resolve_chat_execution(
        db_session,
        workspace=workspace,
        requested_system_id=system.id,
        session_id="s1",
        answer_profile="precise_fact",
        allow_forced_agentic=True,
    )
    assert forced.route == "agentic" and forced.forced is True
    assert forced.retrieval_contract == system.settings["retrieval_contract"]


def test_the_seed_is_idempotent_and_never_duplicates(db_session):
    workspace = _workspace(db_session, slug="acme-twice")
    seed_skills_and_capabilities(db_session)

    first = boot.ensure_workspace_agentic_chat_system_default(db_session, workspace.id)
    workspace.settings = {
        **workspace.settings,
        "chat_execution": {**workspace.settings["chat_execution"], "rollout": {"percentage": 25, "salt": "x"}},
    }
    db_session.flush()
    second = boot.ensure_workspace_agentic_chat_system_default(db_session, workspace.id)

    assert first.id == second.id
    assert len(_agentic_systems(db_session, workspace.id)) == 1
    assert (
        db_session.query(ControlPolicy).filter(ControlPolicy.target_id == first.id).count() == 1
    )
    # An operator-tuned policy is left alone.
    db_session.refresh(workspace)
    assert workspace.settings["chat_execution"]["rollout"]["percentage"] == 25

    report = boot.ensure_workspace_agentic_chat_system_for_all_workspaces(db_session)
    assert report["created"] == 0
    assert report["adopted"] >= 1


def test_an_industrial_workspace_with_one_collection_binds_it_authoritatively(db_session):
    workspace = _workspace(
        db_session,
        slug="hydro",
        settings={
            "family": "industrial",
            "knowledge_scopes": [
                {"key": "docs", "is_default": True, "collection_slugs": ["hydro-manuals"]}
            ],
        },
    )
    seed_skills_and_capabilities(db_session)

    system = boot.ensure_workspace_agentic_chat_system_default(db_session, workspace.id)

    assert system.settings["chat_profile"]["industrial"] is True
    assert system.settings["chat_profile"]["collection_slug"] == "hydro-manuals"
    assert system.settings["retrieval_contract"]["collection"] == "hydro-manuals"
    assert system.settings["retrieval_contract"]["asset_binding"] == "authoritative"
    membrane = db_session.query(ControlPolicy).filter(ControlPolicy.id == system.control_policy_id).one()
    assert membrane.extra["membrane_spec"]["inbound"]["collection_allowlist"] == ["hydro-manuals"]
    assert membrane.extra["membrane_spec"]["inbound"]["industrial_grounding"] is True


def _andritz_fixture(db_session) -> tuple[Workspace, System, ControlPolicy]:
    """The state migrations 048..078 leave behind, minus nothing that matters."""
    artifact = json.load(open(tpl.ARTIFACT_PATH, encoding="utf-8"))
    system = System(
        id="874211ee-0000-0000-0000-000000000000",
        workspace_id="ws-andritz",
        name="Andritz Chat Agentic",
        objective="Chat agentique Andritz",
        skill_ids=[],
        flow_definition=deepcopy(artifact["flow_definition"]),
        settings={
            "seed_origin": "048_andritz_chat_agentic",
            "system_type": "chat_agentic",
            "variant": "chat_agentic_thinking_v1",
            "flow_revision": ANDRITZ_MIGRATION_FLOW_REVISION,
            "retrieval_contract": deepcopy(policy.ANDRITZ_RETRIEVAL_CONTRACT),
        },
        execution_profile={"max_runtime_s": 40},
        status="active",
        created_by="migration",
        default_model="gpt-4o-mini",
    )
    membrane = ControlPolicy(
        id="cp-andritz",
        workspace_id="ws-andritz",
        name="Andritz Chat Agentic Membrane",
        scope="system",
        target_id=system.id,
        extra={"membrane_origin": "048_andritz_chat_agentic", "membrane_spec": artifact["membrane_spec"]},
    )
    system.control_policy_id = membrane.id
    chat_execution = {
        "version": 1,
        "mode": "agentic_default",
        "target": {"system_type": "chat_agentic", "variant": "chat_agentic_thinking_v1"},
        "fallback": "classic",
        "rollout": {"percentage": 0, "salt": "andritz-agentic-v1"},
    }
    workspace = Workspace(
        id="ws-andritz",
        name="Andritz",
        slug="andritz",
        settings={
            "family": "andritz",
            "chat_execution": chat_execution,
            policy.ANDRITZ_MIGRATION_MARKER: {
                "revision": policy.ANDRITZ_MIGRATION_REVISION,
                "schema": 1,
                "system_id": system.id,
                "control_policy": {"id": membrane.id},
            },
        },
    )
    db_session.add_all([workspace, membrane, system])
    db_session.flush()
    return workspace, system, membrane


def test_andritz_is_adopted_never_duplicated_and_its_migration_state_is_untouched(db_session):
    workspace, system, membrane = _andritz_fixture(db_session)
    seed_skills_and_capabilities(db_session)
    before_flow = deepcopy(system.flow_definition)
    before_policy = deepcopy(workspace.settings["chat_execution"])
    before_membrane = deepcopy(membrane.extra)

    adopted = boot.ensure_workspace_agentic_chat_system_default(db_session, workspace.id)

    assert adopted.id == system.id
    assert len(_agentic_systems(db_session, workspace.id)) == 1
    # The profile the skills read is recorded ...
    assert adopted.settings["chat_profile"]["key"] == "andritz"
    assert adopted.settings["chat_profile"]["collection_slug"] == tpl.ANDRITZ_NOTICES_COLLECTION
    assert adopted.settings["family"] == "andritz"
    # ... and everything the 059/078 markers own is byte-for-byte what it was.
    assert adopted.flow_definition == before_flow
    assert agentic_flow_contract_digest(adopted.flow_definition) == EXPECTED_FLOW_CONTRACT_SHA256
    assert adopted.settings["flow_revision"] == ANDRITZ_MIGRATION_FLOW_REVISION
    assert adopted.settings["retrieval_contract"] == policy.ANDRITZ_RETRIEVAL_CONTRACT
    assert adopted.default_model == "gpt-4o-mini"
    assert adopted.control_policy_id == membrane.id
    db_session.refresh(membrane)
    assert membrane.extra == before_membrane
    db_session.refresh(workspace)
    assert workspace.settings["chat_execution"] == before_policy
    assert is_expected_agentic_flow(adopted.settings, adopted.flow_definition)

    report = boot.ensure_workspace_agentic_chat_system_for_all_workspaces(db_session)
    assert report["created"] == 0
    assert len(_agentic_systems(db_session, workspace.id)) == 1


def test_the_seed_skips_without_the_catalog_instead_of_writing_a_half_system(db_session):
    workspace = _workspace(db_session, slug="bare")

    assert boot.ensure_workspace_agentic_chat_system_default(db_session, workspace.id) is None
    assert _agentic_systems(db_session, workspace.id) == []
    db_session.refresh(workspace)
    assert "chat_execution" not in (workspace.settings or {})
