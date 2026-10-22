"""Retained decision comparisons never follow the selected business tool."""

import copy
from uuid import uuid4

import pytest

from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.services.flow_contracts import canonical_sha256
from app.services.model_plane.decision_comparison import decision_input
from app.tests.api.test_model_portal_api import portal  # noqa: F401


@pytest.fixture
def decision(portal, db_session, monkeypatch):
    from app.services.run_engine import dispatch_outbox
    from app.services.run_engine.agent_loop import build_decision_context

    client, workspace, user, system, *_ = portal
    monkeypatch.setattr(dispatch_outbox, "reconcile_dispatch_outbox", lambda: None)
    native = Skill(
        id=str(uuid4()),
        slug="decide_next_v1",
        name="Choose a verification",
        is_seeded="Y",
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "additionalProperties": True},
    )
    db_session.add(native)
    system.skill_ids = [*system.skill_ids, native.id]
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        initiated_by_user_id=user.id,
        status="hitl_pending",
        input_ref={"claim_id": "SYNTHETIC"},
    )
    context, context_evidence = build_decision_context(
        {"decision_context": {"keys": ["priority"]}, "inputs_map": {"priority": "source.priority"}},
        {"priority": "high"},
    )
    invocation = SkillInvocation(
        id=str(uuid4()),
        run_id=run.id,
        skill_id=native.id,
        skill_slug=native.slug,
        status="completed",
        input_ref={
            "goal": {"objective": "Verify the supplied evidence"},
            "observations": [{"skill": "read_case", "output": {"lost": True}}],
            "visible_skills": [{"slug": "propose", "side_effect_class": "read"}],
            "budget": {"turns_left": 3},
            "confidence_floor": 0.55,
            "agent_loop_node_id": "loop",
            "context": context,
            "context_evidence": context_evidence,
            "model": "old-provider:old-model",
        },
        output_ref={"next_skill": "propose", "rationale": "The evidence is complete"},
        trace={"model_execution": {"provider": "openai", "model": "gpt-5"}},
    )
    db_session.add_all([run, invocation])
    db_session.commit()
    return client, workspace, user, system, run, invocation


def body(invocation):
    return {
        "invocation_id": invocation.id,
        "expected_input_sha256": canonical_sha256(decision_input(invocation)),
        "request_key": str(uuid4()),
        "candidates": [
            {"provider": "openai", "model": "gpt-5"},
            {"provider": "openai", "model": "gpt-4o-mini"},
        ],
        "acknowledge_generation_cost": True,
    }


def test_comparison_replays_one_retained_decision_not_the_loop(decision, db_session):
    from app.models.run_dispatch_outbox import RunDispatchOutbox
    from app.services.run_engine.dispatch_outbox import (
        durable_initial_dispatch_source,
        repair_dispatch_gaps,
    )

    client, workspace, user, system, source_run, invocation = decision
    before_flow = copy.deepcopy(system.flow_definition)
    request = body(invocation)
    response = client.post("/models/decision-comparisons", json=request)
    assert response.status_code == 201, response.text
    rows = [db_session.get(Run, item["id"]) for item in response.json()["runs"]]
    assert len(rows) == 2
    for row in rows:
        tasks = [node for node in row.flow_snapshot["nodes"] if node["kind"] == "task"]
        assert len(tasks) == 1 and tasks[0]["config"]["skill_slug"] == "decide_next_v1"
        assert all(node["kind"] != "agent_loop" for node in row.flow_snapshot["nodes"])
        assert row.input_ref["context"] == {"priority": "high"}
        assert row.input_ref["observations"] == invocation.input_ref["observations"]
        assert (
            row.input_ref["execution"]["decision_comparison"]["input_sha256"]
            == request["expected_input_sha256"]
        )
        assert row.execution_surface == "node_preview"
        assert row.input_ref["execution"]["decision_comparison"]["quality_qualified"] is False
        assert durable_initial_dispatch_source(row) == row.trigger_dedup_key
    assert rows[0].input_ref["model"] == "openai:gpt-5"
    assert rows[1].input_ref["model"] == "openai:gpt-4o-mini"
    assert system.flow_definition == before_flow and source_run.status == "hitl_pending"
    again = client.post("/models/decision-comparisons", json=request)
    assert again.status_code == 201
    assert [row["id"] for row in again.json()["runs"]] == [row.id for row in rows]
    # A committed comparison remains recoverable if its dispatch row disappears.
    db_session.query(RunDispatchOutbox).filter(
        RunDispatchOutbox.run_id.in_([row.id for row in rows])
    ).delete(synchronize_session=False)
    db_session.commit()
    assert repair_dispatch_gaps(db_session)["trigger_run"] == 2
    assert (
        db_session.query(RunDispatchOutbox)
        .filter(RunDispatchOutbox.run_id.in_([row.id for row in rows]))
        .count()
        == 2
    )
    # Never authorize an AgentLoop or any tool from these generation-only claims.
    changed = copy.deepcopy(rows[0].flow_snapshot)
    next(node for node in changed["nodes"] if node["kind"] == "task")["config"]["skill_slug"] = (
        "refund_v1"
    )
    rows[0].flow_snapshot = changed
    assert durable_initial_dispatch_source(rows[0]) is None


@pytest.mark.parametrize(
    "change,expected",
    [("changed", 409), ("foreign", 404), ("unfinished", 409), ("ack", 422), ("duplicate", 422)],
)
def test_rejected_comparison_creates_no_runs(decision, db_session, change, expected):
    client, workspace, user, system, source_run, invocation = decision
    request = body(invocation)
    if change == "changed":
        request["expected_input_sha256"] = "0" * 64
    if change == "foreign":
        source_run.workspace_id = "other"
    if change == "unfinished":
        invocation.status = "running"
    if change == "ack":
        request["acknowledge_generation_cost"] = 1
    if change == "duplicate":
        request["candidates"][1] = request["candidates"][0]
    db_session.commit()
    before = db_session.query(Run).count()
    response = client.post("/models/decision-comparisons", json=request)
    assert response.status_code == expected, response.text
    assert db_session.query(Run).count() == before


def test_samples_hide_raw_observations_and_require_authority(decision):
    client, workspace, user, system, source_run, invocation = decision
    response = client.get("/models/decision-samples")
    assert response.status_code == 200
    sample = response.json()["samples"][0]
    assert sample["invocation_id"] == invocation.id and sample["observations_count"] == 1
    assert "observations" not in sample and "input_ref" not in sample
    user.role = "user"
    assert client.get("/models/decision-samples").json()["samples"] == []
    assert client.post("/models/decision-comparisons", json=body(invocation)).status_code == 403


def test_samples_exclude_unsettled_and_comparison_invocations(decision, db_session):
    client, _, _, _, source_run, invocation = decision
    invocation.status = "running"
    db_session.commit()
    assert client.get("/models/decision-samples").json()["samples"] == []
    invocation.status = "completed"
    source_run.input_ref = {"execution": {"decision_comparison": {"generation_only": True}}}
    db_session.commit()
    assert client.get("/models/decision-samples").json()["samples"] == []


@pytest.mark.asyncio
async def test_retained_context_reaches_native_planner_without_executing_selected_tool(
    decision, monkeypatch
):
    from app.services.skills_registry.wrappers import skills

    client, workspace, user, system, source_run, invocation = decision
    prompts = []

    async def generation(prompt, model, context):
        prompts.append(prompt)
        return '{"next_skill":"propose","rationale":"The evidence is complete","confidence":0.9,"needs_human":false,"done":false,"exit":null}'

    monkeypatch.setattr(skills, "_route_llm_complete", generation)
    output = await skills._decide_next_v1(
        {**decision_input(invocation), "model": "openai:gpt-5"}, {}
    )
    assert output["next_skill"] == "propose"
    assert len(prompts) == 1 and "priority" in prompts[0] and "high" in prompts[0]


def test_incompatible_context_is_refused_before_any_run_is_queued(decision, db_session):
    client, workspace, user, system, source_run, invocation = decision
    request = body(invocation)
    inputs = copy.deepcopy(invocation.input_ref)
    inputs.pop("context_evidence")
    invocation.input_ref = inputs
    db_session.commit()
    before = db_session.query(Run).count()
    assert client.get("/models/decision-samples").json()["samples"] == []
    assert client.post("/models/decision-comparisons", json=request).status_code == 409
    assert db_session.query(Run).count() == before


def test_comparison_captures_effective_system_policy_without_client_override(decision, db_session):
    from app.models.policy import ControlPolicy
    from app.models.system_flow_draft import SystemFlowDraft
    from app.models.system_version import SystemVersion
    from app.services.control_policy_snapshot import freeze_control_policy
    from app.services.run_engine.engine import _load_control_policy

    client, workspace, user, system, source_run, invocation = decision
    workspace.settings = {
        **workspace.settings,
        "llm_portal": {
            "routing": {
                "default_provider": "openai",
                "default_model": "gpt-5",
                "named_routes": {"qualification": {"provider": "openai", "model": "gpt-4o-mini"}},
            }
        },
    }
    policy = ControlPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope="system",
        target_id=system.id,
        name="Model qualification",
        allowed_models=["openai:gpt-5", "openai:gpt-4o-mini"],
        allowed_skills=["decide_next_v1"],
        extra={"enforcement_mode": "enforce"},
    )
    db_session.add(policy)
    system.control_policy_id = policy.id
    db_session.flush()
    published = db_session.get(SystemVersion, system.published_flow_version_id)
    contract = copy.deepcopy(published.execution_contract)
    contract["control_policy_snapshot"] = freeze_control_policy(
        policy, workspace_id=workspace.id, system_id=system.id
    )
    contract.pop("contract_sha256", None)
    contract["contract_sha256"] = canonical_sha256(contract)
    published.execution_contract = contract
    # A draft with no mandate must not relax the qualification's permissions.
    draft = db_session.query(SystemFlowDraft).filter_by(system_id=system.id).one()
    draft.control_policy_snapshot = freeze_control_policy(
        None, workspace_id=workspace.id, system_id=system.id
    )
    db_session.commit()
    response = client.post("/models/decision-comparisons", json=body(invocation))
    assert response.status_code == 201, response.text
    runs = [db_session.get(Run, item["id"]) for item in response.json()["runs"]]
    for run in runs:
        effective = _load_control_policy(db_session, system, run=run)
        assert effective.id == policy.id
        assert effective.allowed_models == policy.allowed_models
        assert effective.allowed_skills == ["decide_next_v1"]
        assert run.execution_contract["control_policy_snapshot"] is not None
    # This fixture's cleanup predates ControlPolicy and does not delete its rows.
    db_session.delete(policy)
    db_session.commit()


def test_comparison_cannot_bypass_system_or_invocation_authority(decision, db_session, monkeypatch):
    from fastapi import HTTPException

    from app.api.v1.endpoints import flow_workbench
    from app.services.model_plane import decision_comparison

    client, workspace, user, system, source_run, invocation = decision
    before = db_session.query(Run).count()

    def deny(*args, **kwargs):
        raise HTTPException(403, detail="System denied")

    monkeypatch.setattr(flow_workbench, "_enforce_system_admin", deny)
    assert client.post("/models/decision-comparisons", json=body(invocation)).status_code == 403
    monkeypatch.setattr(
        decision_comparison, "readable_skill_invocations_for_runs", lambda *args, **kwargs: []
    )
    assert client.get("/models/decision-samples").json()["samples"] == []
    assert client.post("/models/decision-comparisons", json=body(invocation)).status_code == 404
    assert db_session.query(Run).count() == before
