"""Provider-free qualification of the execution harness, not model quality.

The planner and source are explicit test doubles. These cases prove runtime
boundaries and recovery semantics; they cannot measure an LLM's accuracy, cost
or benefit over a deterministic workflow.
"""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.decision import Decision
from app.models.policy import ControlPolicy
from app.models.skill import Skill
from app.services.control_policy_snapshot import freeze_control_policy
from app.services.flow_contracts import canonical_sha256, compile_execution_contract
from app.services.run_engine import dag
from app.tests.services.test_agent_loop_runtime import (
    _install,
    _mk_run,
    _mk_system,
    _reload,
    _slugs,
    _turns,
)
from app.tests.services.test_run_engine_membrane_v2 import _fake_artifact


@pytest.fixture(autouse=True)
def no_external_jobs(monkeypatch):
    monkeypatch.setattr("app.services.evaluation.auto_eval.schedule_eval", lambda _id: None)
    monkeypatch.setattr(dag, "persist_provenance_artifact", _fake_artifact)


def flow(**config):
    return {
        "schema_version": 2,
        "nodes": [
            {"id": "source", "kind": "source"},
            {
                "id": "investigate",
                "kind": "agent_loop",
                "config": {
                    "skill_slug": "decide_next_v1",
                    "skill_allowlist": ["semantic_search_v1"],
                    "privilege_tier": "recommend",
                    "confidence_floor": 0.55,
                    "budget": {"max_turns": 6},
                    "on_budget": "exit",
                    "goal": {
                        "objective": "Investigate from evidence",
                        "done_when": ["resolution_ready"],
                    },
                    **config,
                },
            },
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [{"from": "source", "to": "investigate"}, {"from": "investigate", "to": "sink"}],
    }


def choose(skill="semantic_search_v1", **extra):
    return {"next_skill": skill, "confidence": 0.9, "needs_human": False, "done": False, **extra}


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["cost", "deadline"])
async def test_budget_exit_prevents_a_second_planner_and_source_call(
    db_session, monkeypatch, limit
):
    clock = {"seconds": 0.0}
    monkeypatch.setattr(dag, "time", SimpleNamespace(monotonic=lambda: clock["seconds"]))

    async def decide(_payload, _ctx):
        return choose()

    async def read(_payload, _ctx):
        clock["seconds"] += 2
        return {"summary": "waiting_information"}

    _install(monkeypatch, {"decide_next_v1": decide, "semantic_search_v1": read})
    # The fixture catalog prices each invocation at 0.01. This proves the
    # runtime accumulator, not a provider-currency charge or pre-dispatch cap.
    budget = {"max_turns": 6, **({"max_cost": 0.015} if limit == "cost" else {"deadline_ms": 1000})}
    system = _mk_system(db_session, flow(budget=budget), ["decide_next_v1", "semantic_search_v1"])
    for skill in db_session.query(Skill).filter(Skill.id.in_(system.skill_ids)):
        skill.pricing = {"unit_price": 0.01, "currency": "USD", "unit": "per_call"}
    db_session.commit()
    run = _mk_run(db_session, system)

    await dag.execute_run_dag(run.id)

    run = _reload(db_session, run)
    assert run.output_ref["exit"] == "budget"
    assert run.output_ref["goal"]["status"] == "blocked"
    assert _slugs(db_session, run) == ["decide_next_v1", "semantic_search_v1"]
    assert len(_turns(run)) == 1
    assert db_session.query(Decision).filter_by(target_id=run.id).count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("decision_status", ["accepted", "rejected"])
async def test_missing_information_requires_human_and_fresh_evidence_on_resume(
    db_session,
    monkeypatch,
    decision_status,
):
    reads = []

    async def decide(payload, _ctx):
        observations = payload.get("observations", [])
        if not observations or any(row.get("skill") == "human" for row in observations):
            return choose()
        return choose(
            None,
            needs_human=True,
            exit="ask_human",
            human_prompt="Provide the missing carrier proof",
        )

    async def read(_payload, _ctx):
        reads.append("source-read")
        return {"summary": "waiting_information" if len(reads) == 1 else "resolution_ready"}

    _install(monkeypatch, {"decide_next_v1": decide, "semantic_search_v1": read})
    system = _mk_system(db_session, flow(), ["decide_next_v1", "semantic_search_v1"])
    run = _mk_run(db_session, system)
    paused = await dag.execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending"
    assert reads == ["source-read"]
    decision = db_session.get(Decision, paused["awaiting_decision"])
    decision.status = decision_status
    db_session.commit()

    await dag.resume_run_dag(run.id, decision_id=decision.id)

    run = _reload(db_session, run)
    assert reads == ["source-read"] * (2 if decision_status == "accepted" else 1)
    assert run.output_ref["goal"]["status"] == (
        "complete" if decision_status == "accepted" else "blocked"
    )
    assert set(_slugs(db_session, run)) <= {"decide_next_v1", "semantic_search_v1"}
    assert db_session.query(Decision).filter_by(target_id=run.id).count() == 1


@pytest.mark.asyncio
async def test_frozen_policy_removes_a_tool_from_the_prompt_and_rejects_its_selection(
    db_session,
    monkeypatch,
):
    visible = []

    async def decide(payload, _ctx):
        visible.extend(row["slug"] for row in payload["visible_skills"])
        return choose("semantic_search_v1")  # hostile or stale planner output

    async def forbidden(_payload, _ctx):
        pytest.fail("A tool removed by the accepted policy must never execute")

    _install(monkeypatch, {"decide_next_v1": decide, "semantic_search_v1": forbidden})
    system = _mk_system(db_session, flow(), ["decide_next_v1", "semantic_search_v1"])
    system.default_model = "gpt-test"
    policy = ControlPolicy(
        id=str(uuid4()),
        name="Only planner",
        scope="system",
        target_id=system.id,
        allowed_skills=["decide_next_v1"],
        allowed_models=["gpt-test"],
        extra={
            "membrane_spec": {
                "version": 2,
                "enforcement_mode": "enforce",
                "capabilities": {
                    "allowed_skills": ["decide_next_v1"],
                    "allowed_models": ["gpt-test"],
                    "allowed_actions": ["system.engine.run"],
                },
                "outbound": {"expert_review_required": False},
            }
        },
    )
    system.control_policy_id = policy.id
    db_session.add(policy)
    db_session.commit()
    run = _mk_run(db_session, system)
    contract = compile_execution_contract(
        db_session,
        flow=run.flow_snapshot,
        workspace_id=None,
        runtime_mode="dag_overlay",
    )
    contract["control_policy_snapshot"] = freeze_control_policy(
        policy, workspace_id=None, system_id=system.id
    )
    contract.pop("contract_sha256")
    contract["contract_sha256"] = canonical_sha256(contract)
    run.execution_contract = deepcopy(contract)
    db_session.commit()

    await dag.execute_run_dag(run.id)

    run = _reload(db_session, run)
    assert visible == []
    assert run.output_ref["exit"] == "policy_block"
    assert _slugs(db_session, run) == ["decide_next_v1"]
