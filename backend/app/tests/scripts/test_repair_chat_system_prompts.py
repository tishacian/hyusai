"""The chat prompt repair republishes only untouched legacy prompts.

Before lot 1b every workspace chat System stored one system prompt that named a
customer, and a stored prompt wins over the family default. The repair replaces
that exact text, through a new published version, and leaves every
customisation, unstamped workspace and unreviewed draft alone.
"""

from __future__ import annotations

import copy
from uuid import uuid4

from app.agents.procurement_agent import default_system_prompt
from app.api.v1.endpoints.chat import ChatRequest, _apply_workspace_chat_flow_defaults
from app.models.system_flow_draft import SystemFlowDraft
from app.models.system_version import SystemVersion
from app.models.workspace import Workspace
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.systems import flow_publication
from app.services.systems.bootstrap import ensure_workspace_chat_system_default
from scripts import repair_chat_system_prompts as repair

SEED_ACTOR = "system:workspace_chat_seed"


def _with_legacy_prompt(flow: dict) -> dict:
    legacy = copy.deepcopy(flow)
    for _label, container, key in repair._prompt_slots(legacy):
        container[key] = repair.LEGACY_SYSTEM_PROMPT
    return legacy


def _chat_workspace(db_session, *, family: str | None, slug: str) -> tuple[Workspace, str]:
    settings = {"family": family} if family else {}
    workspace = Workspace(id=str(uuid4()), name=slug, slug=f"{slug}-{uuid4().hex[:6]}", settings=settings)
    db_session.add(workspace)
    db_session.commit()
    system = ensure_workspace_chat_system_default(db_session, workspace.id)
    db_session.commit()
    # Put the workspace back where the estate is: the legacy prompt published.
    draft = db_session.query(SystemFlowDraft).filter(SystemFlowDraft.system_id == system.id).one()
    draft, _ = flow_publication.save_draft(
        db_session,
        system_id=system.id,
        workspace=workspace,
        flow_definition=_with_legacy_prompt(system.flow_definition),
        expected_revision=draft.revision,
        actor=SEED_ACTOR,
    )
    flow_publication.publish_draft(
        db_session,
        system_id=system.id,
        workspace=workspace,
        expected_draft_revision=draft.revision,
        expected_published_version_id=system.published_flow_version_id,
        message="legacy prompt",
        breaking_change_intent="acknowledged",
        actor=SEED_ACTOR,
    )
    db_session.commit()
    return workspace, system.id


def _runtime_prompt(db_session, workspace: Workspace) -> str:
    request = ChatRequest(query="bonjour")
    _apply_workspace_chat_flow_defaults(db_session, workspace=workspace, request=request)
    return request.system_prompt or ""


def _by_slug(report: dict, workspace: Workspace) -> dict:
    return next(entry for entry in report["systems"] if entry["workspace_id"] == workspace.id)


def test_the_repair_republishes_only_what_it_should(db_session):
    seed_skills_and_capabilities(db_session)
    generic, generic_system = _chat_workspace(db_session, family="generic", slug="generic")
    andritz, _ = _chat_workspace(db_session, family="andritz", slug="andritz")
    unstamped, _ = _chat_workspace(db_session, family=None, slug="unstamped")
    ids = [generic.id, andritz.id, unstamped.id]
    assert "Andritz experts" in _runtime_prompt(db_session, generic)

    plan = repair.run(db_session, workspace_ids=ids, apply=False, actor=repair.ACTOR)
    assert _by_slug(plan, generic)["status"] == "publish"
    assert len(_by_slug(plan, generic)["changed_slots"]) == 3
    # The legacy text is that family's own wording: nothing to publish there.
    assert _by_slug(plan, andritz)["status"] == "nothing_to_replace"
    assert _by_slug(plan, unstamped)["status"] == "skipped_family_unstamped"
    assert "Andritz experts" in _runtime_prompt(db_session, generic)  # dry run wrote nothing

    versions_before = db_session.query(SystemVersion).filter(SystemVersion.system_id == generic_system).count()
    applied = repair.run(db_session, workspace_ids=ids, apply=True, actor=repair.ACTOR)
    assert _by_slug(applied, generic)["applied"] is True
    after = db_session.query(SystemVersion).filter(SystemVersion.system_id == generic_system).count()
    assert after == versions_before + 1  # one new published version, history kept

    runtime = _runtime_prompt(db_session, generic)
    assert "Andritz" not in runtime
    assert runtime.startswith(default_system_prompt("generic"))
    assert "Andritz experts" in _runtime_prompt(db_session, andritz)

    again = repair.run(db_session, workspace_ids=ids, apply=True, actor=repair.ACTOR)
    assert _by_slug(again, generic)["status"] == "nothing_to_replace"  # idempotent


def test_a_customised_prompt_and_an_unreviewed_draft_are_left_alone(db_session):
    seed_skills_and_capabilities(db_session)
    customised, customised_id = _chat_workspace(db_session, family="generic", slug="custom")
    drafted, drafted_id = _chat_workspace(db_session, family="generic", slug="drafted")

    # An operator rewrote the prompt the runtime reads, and published it.
    from app.models.system import System

    system = db_session.get(System, customised_id)
    flow = copy.deepcopy(system.flow_definition)
    for node in flow["nodes"]:
        if node.get("id") == "skill.fast_answer":
            node["data"]["prompt_contract"]["system_prompt"] = "Our own prompt."
    draft = db_session.query(SystemFlowDraft).filter(SystemFlowDraft.system_id == customised_id).one()
    draft, _ = flow_publication.save_draft(
        db_session, system_id=customised_id, workspace=customised, flow_definition=flow,
        expected_revision=draft.revision, actor="operator@example.test",
    )
    flow_publication.publish_draft(
        db_session, system_id=customised_id, workspace=customised,
        expected_draft_revision=draft.revision, expected_published_version_id=system.published_flow_version_id,
        message="custom", breaking_change_intent="acknowledged", actor="operator@example.test",
    )
    # Another operator has unpublished work in progress.
    other = db_session.get(System, drafted_id)
    pending = copy.deepcopy(other.flow_definition)
    pending["description"] = "work in progress"
    draft = db_session.query(SystemFlowDraft).filter(SystemFlowDraft.system_id == drafted_id).one()
    flow_publication.save_draft(
        db_session, system_id=drafted_id, workspace=drafted, flow_definition=pending,
        expected_revision=draft.revision, actor="operator@example.test",
    )
    db_session.commit()

    report = repair.run(db_session, workspace_ids=[customised.id, drafted.id], apply=True, actor=repair.ACTOR)
    custom_entry = _by_slug(report, customised)
    assert custom_entry["status"] == "publish"
    assert "skill.fast_answer.system_prompt" not in custom_entry["changed_slots"]
    assert _runtime_prompt(db_session, customised).startswith("Our own prompt.")
    assert _by_slug(report, drafted)["status"] == "skipped_draft_ahead_of_published"
    assert "Andritz experts" in _runtime_prompt(db_session, drafted)


def test_repaired_flow_touches_only_exact_legacy_values():
    flow = {
        "prompt_contract": {"base_system_prompt": repair.LEGACY_SYSTEM_PROMPT},
        "nodes": [
            {"id": "runtime.prompt_assembly", "data": {"prompt_contract": {"base_system_prompt": repair.LEGACY_SYSTEM_PROMPT + " "}}},
            {"id": "skill.fast_answer", "data": {"prompt_contract": {"system_prompt": repair.LEGACY_SYSTEM_PROMPT}}},
        ],
    }
    repaired, changed = repair.repaired_flow(flow, "industrial")
    assert changed == ["prompt_contract.base_system_prompt", "skill.fast_answer.system_prompt"]
    assert repaired["nodes"][0]["data"]["prompt_contract"]["base_system_prompt"].endswith(" ")
    assert flow["prompt_contract"]["base_system_prompt"] == repair.LEGACY_SYSTEM_PROMPT  # input untouched
