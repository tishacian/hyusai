"""AgentLoop walker — L1 budget, L2 resume, L3 privilege, L4 steer, L5 fan-out."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest

from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.services.chains.dag_validator import validate_flow
from app.services.flow_contracts import compile_execution_contract
from app.services.run_engine import engine as engine_module
from app.services.run_engine.agent_loop import (
    compile_mandate_view,
    merge_fanout_payloads,
    persist_steer,
    skill_search,
)
from app.services.run_engine.dag import execute_run_dag, resume_run_dag, should_use_dag
from app.services.skills_registry import wrappers

ARTIFACT = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "resources"
        / "flows"
        / "nawa_password_reset_agent_loop_v1.json"
    ).read_text(encoding="utf-8")
)

SkillFn = Callable[[Dict[str, Any], Dict[str, Any]], Any]


def _install(monkeypatch: pytest.MonkeyPatch, skills: Dict[str, SkillFn]) -> None:
    def _resolve(slug: str) -> SkillFn:
        fn = skills.get(slug)
        if fn is None:
            raise NotImplementedError(slug)
        return fn

    monkeypatch.setattr(engine_module, "resolve_skill", _resolve)


def _mk_skill(db, slug: str) -> Skill:
    row = Skill(
        id=str(uuid.uuid4()),
        slug=slug,
        version="1",
        name=slug,
        description=slug,
        input_schema={},
        output_schema={},
        pricing={"unit_price": 0.01},
        execution={"mode": "sync", "timeout_ms": 1000, "retryable": True, "idempotent": True},
        certification_level="production",
    )
    db.add(row)
    db.commit()
    return row


def _mk_system(db, flow: Dict[str, Any], slugs: List[str]) -> System:
    skills = [_mk_skill(db, slug) for slug in slugs]
    row = System(
        id=str(uuid.uuid4()),
        name="agent-loop-host",
        objective="test",
        skill_ids=[skill.id for skill in skills],
        flow_definition=flow,
        status="active",
    )
    db.add(row)
    db.commit()
    return row


def _mk_run(db, system: System, **extra: Any) -> Run:
    row = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        input_ref=extra or {},
        status="pending",
        flow_snapshot=system.flow_definition,
    )
    db.add(row)
    db.commit()
    return row


def _reload(db, run: Run) -> Run:
    db.expire_all()
    return db.query(Run).filter(Run.id == run.id).one()


def _slugs(db, run: Run) -> List[str]:
    rows = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    return [row.skill_slug for row in rows]


def _turns(run: Run) -> List[Dict[str, Any]]:
    return [cp for cp in (run.checkpoints or []) if cp.get("kind") == "agent_loop_turn"]


LOOP_FLOW = ARTIFACT["flow_definition"]
LOOP_SLUGS = ["decide_next_v1", "azure_llm_v1", "audit_log_v1", "semantic_search_v1"]


def test_agent_loop_flow_validates_and_uses_dag():
    errors = [i.to_dict() for i in validate_flow(LOOP_FLOW) if i.level == "error"]
    assert errors == [], errors
    assert should_use_dag(System(flow_definition=LOOP_FLOW)) is True


@pytest.mark.asyncio
async def test_happy_recommend_only_completes(db_session, monkeypatch):
    async def decide(inp, ctx):
        if not inp.get("observations"):
            return {
                "next_skill": "azure_llm_v1",
                "rationale": "classify",
                "confidence": 0.9,
                "needs_human": False,
                "done": False,
            }
        return {
            "next_skill": None,
            "rationale": "done",
            "confidence": 0.9,
            "needs_human": False,
            "done": True,
            "exit": "complete",
        }

    async def classify(inp, ctx):
        return {"summary": "password_reset", "completion": "password_reset"}

    _install(
        monkeypatch,
        {"decide_next_v1": decide, "azure_llm_v1": classify, "audit_log_v1": classify},
    )
    flow = json.loads(json.dumps(LOOP_FLOW))
    flow["nodes"][1]["config"]["skill_allowlist"] = ["azure_llm_v1"]
    flow["nodes"][1]["config"]["privilege_tier"] = "recommend"
    flow["nodes"][1]["config"]["goal"]["done_when"] = ["azure_llm_v1"]
    system = _mk_system(db_session, flow, ["decide_next_v1", "azure_llm_v1"])
    run = _mk_run(db_session, system)
    summary = await execute_run_dag(run.id)
    run = _reload(db_session, run)
    assert summary["status"] == "completed"
    assert run.output_ref["goal"]["status"] == "complete"
    assert "azure_llm_v1" in _slugs(db_session, run)
    assert "audit_log_v1" not in _slugs(db_session, run)
    assert _turns(run)


@pytest.mark.asyncio
async def test_write_requires_hitl_then_accept(db_session, monkeypatch):
    async def decide(inp, ctx):
        return {
            "next_skill": "audit_log_v1",
            "rationale": "commit ledger",
            "confidence": 0.9,
            "needs_human": False,
            "done": False,
        }

    async def audit(inp, ctx):
        return {"summary": "recorded", "status": "recorded"}

    _install(monkeypatch, {"decide_next_v1": decide, "audit_log_v1": audit, "azure_llm_v1": audit})
    system = _mk_system(db_session, LOOP_FLOW, LOOP_SLUGS)
    run = _mk_run(db_session, system)
    summary = await execute_run_dag(run.id)
    run = _reload(db_session, run)
    assert summary["status"] == "hitl_pending"
    assert "audit_log_v1" not in _slugs(db_session, run)
    decision = db_session.query(Decision).filter(Decision.id == summary["awaiting_decision"]).one()
    decision.status = "accepted"
    db_session.commit()
    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    run = _reload(db_session, run)
    assert resumed["status"] == "completed"
    assert "audit_log_v1" in _slugs(db_session, run)
    assert run.id == summary["id"]


@pytest.mark.asyncio
async def test_write_reject_has_zero_side_effect(db_session, monkeypatch):
    async def decide(inp, ctx):
        return {
            "next_skill": "audit_log_v1",
            "rationale": "commit ledger",
            "confidence": 0.9,
            "needs_human": False,
            "done": False,
        }

    called = {"audit": 0}

    async def audit(inp, ctx):
        called["audit"] += 1
        return {"summary": "recorded"}

    _install(monkeypatch, {"decide_next_v1": decide, "audit_log_v1": audit, "azure_llm_v1": audit})
    system = _mk_system(db_session, LOOP_FLOW, LOOP_SLUGS)
    run = _mk_run(db_session, system)
    summary = await execute_run_dag(run.id)
    decision = db_session.query(Decision).filter(Decision.id == summary["awaiting_decision"]).one()
    decision.status = "rejected"
    db_session.commit()
    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    run = _reload(db_session, run)
    assert resumed["status"] == "completed"
    assert called["audit"] == 0
    assert "audit_log_v1" not in _slugs(db_session, run)
    assert run.output_ref["goal"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_budget_exhaustion_blocks_writes(db_session, monkeypatch):
    async def decide(inp, ctx):
        return {
            "next_skill": "azure_llm_v1",
            "rationale": "again",
            "confidence": 0.9,
            "needs_human": False,
            "done": False,
        }

    async def classify(inp, ctx):
        return {"summary": "still working"}

    _install(
        monkeypatch,
        {"decide_next_v1": decide, "azure_llm_v1": classify, "audit_log_v1": classify},
    )
    flow = json.loads(json.dumps(LOOP_FLOW))
    flow["nodes"][1]["config"]["budget"] = {"max_turns": 2}
    flow["nodes"][1]["config"]["privilege_tier"] = "recommend"
    flow["nodes"][1]["config"]["skill_allowlist"] = ["azure_llm_v1"]
    flow["nodes"][1]["config"]["goal"]["done_when"] = ["never"]
    system = _mk_system(db_session, flow, ["decide_next_v1", "azure_llm_v1"])
    run = _mk_run(db_session, system)
    await execute_run_dag(run.id)
    run = _reload(db_session, run)
    assert run.output_ref["exit"] == "budget"
    assert run.output_ref["goal"]["status"] == "blocked"
    assert "audit_log_v1" not in _slugs(db_session, run)
    assert len(_turns(run)) <= 2


@pytest.mark.asyncio
async def test_model_cannot_invoke_unlisted_skill(db_session, monkeypatch):
    async def decide(inp, ctx):
        return {
            "next_skill": "rpa_dispatch_v1",
            "rationale": "pwn",
            "confidence": 0.99,
            "needs_human": False,
            "done": False,
        }

    async def rpa(inp, ctx):
        raise AssertionError("write skill must never run")

    _install(
        monkeypatch,
        {
            "decide_next_v1": decide,
            "rpa_dispatch_v1": rpa,
            "azure_llm_v1": rpa,
            "audit_log_v1": rpa,
        },
    )
    system = _mk_system(db_session, LOOP_FLOW, LOOP_SLUGS)
    run = _mk_run(db_session, system)
    await execute_run_dag(run.id)
    run = _reload(db_session, run)
    assert run.output_ref["exit"] == "policy_block"
    assert "rpa_dispatch_v1" not in _slugs(db_session, run)


def test_published_contract_freezes_allowlist(db_session):
    for slug in LOOP_SLUGS:
        _mk_skill(db_session, slug)
    contract = compile_execution_contract(
        db_session,
        flow=LOOP_FLOW,
        workspace_id=None,
        runtime_mode="dag_overlay",
        allowed_skill_ids=None,
    )
    loop_node = contract["nodes"]["loop.itsd"]
    assert loop_node["skill_allowlist"] == [
        "azure_llm_v1",
        "audit_log_v1",
        "semantic_search_v1",
    ]
    assert loop_node["skill_slug"] == "decide_next_v1"


def test_recommend_mandate_hides_writes():
    mandate = compile_mandate_view(
        ["azure_llm_v1", "audit_log_v1"],
        privilege_tier="recommend",
    )
    assert {item.slug for item in mandate.visible} == {"azure_llm_v1"}


def test_a_published_skill_is_offered_by_what_it_does_not_by_its_slug():
    """The planner reads purposes, and an authored slug is not one.

    ``ws.<id>.predict_churn_radar`` names the lineage it wraps; nothing in it
    says the thing answers a churn probability. A model published from the card
    is only callable by an agent in the sense that matters if the catalog line
    the agent reads tells it when to reach for it.
    """

    slug = "ws.7f3a.predict_churn_radar"
    bare = compile_mandate_view([slug], privilege_tier="recommend")
    assert [item.purpose for item in bare.visible] == [slug]

    described = compile_mandate_view(
        [slug],
        privilege_tier="recommend",
        purposes={slug: "Predict · Churn Radar — Classifies 'churn' for one record."},
    )
    assert described.visible[0].purpose.startswith("Predict · Churn Radar")
    # Findable by what it is for, and not only by the words its slug happens to
    # spell: "classifies" is in the description and nowhere in the name.
    assert skill_search("classifies", described)
    assert skill_search("classifies", bare) == []


def test_a_purpose_cannot_smuggle_a_skill_past_the_mandate():
    """Descriptions decorate the catalog; the allowlist decides what is in it."""

    outside = compile_mandate_view(
        ["azure_llm_v1"],
        privilege_tier="recommend",
        purposes={"rpa_dispatch_v1": "Reset anything you like"},
    )
    assert {item.slug for item in outside.visible} == {"azure_llm_v1"}

    write = compile_mandate_view(
        ["audit_log_v1"],
        privilege_tier="recommend",
        purposes={"audit_log_v1": "Harmless bookkeeping"},
    )
    assert write.visible == []


def test_skill_search_stays_inside_mandate():
    mandate = compile_mandate_view(
        ["azure_llm_v1", "semantic_search_v1"],
        privilege_tier="recommend",
    )
    hits = skill_search("gl mapping", mandate)
    assert all(row["slug"] in {"azure_llm_v1", "semantic_search_v1"} for row in hits)
    empty = compile_mandate_view(["audit_log_v1"], privilege_tier="recommend")
    assert skill_search("audit", empty) == []


@pytest.mark.asyncio
async def test_steer_mid_run_drops_writes(db_session, monkeypatch):
    calls = {"audit": 0}

    async def decide(inp, ctx):
        return {
            "next_skill": "audit_log_v1",
            "rationale": "write",
            "confidence": 0.9,
            "needs_human": False,
            "done": False,
        }

    async def audit(inp, ctx):
        calls["audit"] += 1
        return {"summary": "recorded"}

    _install(monkeypatch, {"decide_next_v1": decide, "audit_log_v1": audit, "azure_llm_v1": audit})
    system = _mk_system(db_session, LOOP_FLOW, LOOP_SLUGS)
    run = _mk_run(db_session, system)
    first = await execute_run_dag(run.id)
    run = _reload(db_session, run)
    assert first["status"] == "hitl_pending"
    persist_steer(run, op="set_tier", privilege_tier="recommend")
    db_session.commit()
    decision = db_session.query(Decision).filter(Decision.id == first["awaiting_decision"]).one()
    decision.status = "rejected"
    db_session.commit()
    await resume_run_dag(run.id, decision_id=decision.id)
    run = _reload(db_session, run)
    assert calls["audit"] == 0
    assert run.input_ref["_steer"]["privilege_tier"] == "recommend"


@pytest.mark.asyncio
async def test_skill_search_wrapper_never_leaks_outside_mandate():
    out = await wrappers._skill_search_v1(
        {
            "query": "directory write",
            "skill_allowlist": ["azure_llm_v1"],
            "privilege_tier": "recommend",
        },
        {},
    )
    assert out["count"] == 0 or all(row["slug"] == "azure_llm_v1" for row in out["skills"])
    assert all(row["slug"] != "rpa_dispatch_v1" for row in out["skills"])


@pytest.mark.asyncio
async def test_fanout_worker_write_is_isolated(db_session, monkeypatch):
    async def decide_write(inp, ctx):
        return {
            "next_skill": "audit_log_v1",
            "rationale": "worker write",
            "confidence": 0.9,
            "needs_human": False,
            "done": False,
        }

    async def decide_read(inp, ctx):
        if not inp.get("observations"):
            return {
                "next_skill": "azure_llm_v1",
                "rationale": "read",
                "confidence": 0.9,
                "needs_human": False,
                "done": False,
            }
        return {
            "next_skill": None,
            "rationale": "done",
            "confidence": 0.9,
            "done": True,
            "exit": "complete",
        }

    async def classify(inp, ctx):
        return {"summary": "ok", "bu": "finance"}

    async def audit(inp, ctx):
        raise AssertionError("worker must not write")

    def _resolve(slug: str):
        return {
            "decide_next_v1": decide_write,
            "azure_llm_v1": classify,
            "audit_log_v1": audit,
        }[slug]

    # Per-node decide: worker A tries write, worker B reads.
    async def decide(inp, ctx):
        if inp.get("agent_loop_node_id") == "loop.b":
            return await decide_read(inp, ctx)
        return await decide_write(inp, ctx)

    monkeypatch.setattr(engine_module, "resolve_skill", lambda slug: {
        "decide_next_v1": decide,
        "azure_llm_v1": classify,
        "audit_log_v1": audit,
    }[slug])

    flow = {
        "schema_version": 3,
        "nodes": [
            {"id": "source.request", "kind": "source", "type": "source"},
            {"id": "fork.bus", "kind": "fork", "type": "fork", "config": {"branches": ["a", "b"]}},
            {
                "id": "loop.a",
                "kind": "agent_loop",
                "type": "agent_loop",
                "config": {
                    "skill_slug": "decide_next_v1",
                    "skill_allowlist": ["azure_llm_v1", "audit_log_v1"],
                    "privilege_tier": "recommend",
                    "worker_read_only": True,
                    "budget": {"max_turns": 2},
                    "goal": {"objective": "read A", "done_when": ["never"], "status": "active"},
                },
            },
            {
                "id": "loop.b",
                "kind": "agent_loop",
                "type": "agent_loop",
                "config": {
                    "skill_slug": "decide_next_v1",
                    "skill_allowlist": ["azure_llm_v1"],
                    "privilege_tier": "recommend",
                    "worker_read_only": True,
                    "budget": {"max_turns": 2},
                    "goal": {"objective": "read B", "done_when": ["azure_llm_v1"], "status": "active"},
                },
            },
            {"id": "join.bus", "kind": "join", "type": "join", "config": {"strategy": "all"}},
            {"id": "sink.result", "kind": "sink", "type": "sink"},
        ],
        "edges": [
            {"from": "source.request", "to": "fork.bus", "kind": "data"},
            {"from": "fork.bus", "to": "loop.a", "kind": "branch", "branch_label": "a"},
            {"from": "fork.bus", "to": "loop.b", "kind": "branch", "branch_label": "b"},
            {"from": "loop.a", "to": "join.bus", "kind": "data"},
            {"from": "loop.b", "to": "join.bus", "kind": "data"},
            {"from": "join.bus", "to": "sink.result", "kind": "data"},
        ],
    }
    system = _mk_system(
        db_session, flow, ["decide_next_v1", "azure_llm_v1", "audit_log_v1"]
    )
    run = _mk_run(db_session, system)
    summary = await execute_run_dag(run.id)
    run = _reload(db_session, run)
    assert summary["status"] == "completed"
    assert "audit_log_v1" not in _slugs(db_session, run)
    assert "azure_llm_v1" in _slugs(db_session, run)


def test_join_merge_is_deterministic():
    left = {"bu": "finance", "items": 1, "nested": {"a": 1}}
    right = {"bu": "hr", "extra": True, "nested": {"b": 2}}
    assert merge_fanout_payloads([left, right]) == merge_fanout_payloads([left, right])
    assert merge_fanout_payloads([left, right])["nested"]["a"] == 1
    assert merge_fanout_payloads([left, right])["nested"]["b"] == 2


@pytest.mark.asyncio
async def test_retrieval_evidence_reaches_next_decision_and_persisted_output(db_session, monkeypatch):
    evidence = {"results": [{"content": "Continuous pressure: 700 bar.",
                            "metadata": {"document_id": "notice-700", "page": 2}}]}
    seen = []
    instructions = "Read-only investigation; report evidence gaps without inventing facts."

    async def decide(inp, ctx):
        assert inp["goal"]["instructions"] == instructions
        if inp["observations"]:
            seen.extend(inp["observations"])
            return {"confidence": 1, "done": True, "exit": "complete"}
        return {"next_skill": "semantic_search_v1", "confidence": 1}

    async def retrieve(inp, ctx):
        assert inp["query"] == "What is the PMP-700 continuous pressure limit?"
        assert inp["goal"]["objective"] == inp["query"]
        return evidence

    _install(monkeypatch, {"decide_next_v1": decide, "semantic_search_v1": retrieve})
    flow = json.loads(json.dumps(LOOP_FLOW))
    config = flow["nodes"][1]["config"]
    config.update(skill_allowlist=["semantic_search_v1"], privilege_tier="recommend")
    config["goal"] = {"done_when": [], "instructions": instructions}
    config["inputs_map"] = {
        name: {"node_id": "source.request", "path": ["request"], "required": True}
        for name in ("objective", "query")
    }
    system = _mk_system(db_session, flow, ["decide_next_v1", "semantic_search_v1"])
    run = _mk_run(db_session, system, request="What is the PMP-700 continuous pressure limit?")
    await execute_run_dag(run.id)
    run = _reload(db_session, run)
    assert run.status == "completed"
    assert run.output_ref["goal"]["instructions"] == instructions
    observation = run.output_ref["observations"][0]
    assert observation["output"]["results"] == evidence["results"]
    assert observation["output"]["evidence_view"]["passages_omitted"] == 0
    assert seen[0] == observation
    invocation = db_session.get(SkillInvocation, observation["invocation_id"])
    assert invocation.run_id == run.id
    assert invocation.skill_slug == "semantic_search_v1"
    assert invocation.output_ref == evidence


@pytest.mark.asyncio
async def test_frozen_tool_receives_declared_arguments_without_loop_envelope(db_session, monkeypatch):
    async def decide(inp, ctx):
        return {"next_skill": "azure_llm_v1", "confidence": 0.9, "done": False}
    seen = []
    async def tool(inp, ctx):
        seen.append(inp)
        return {"completion": "read"}
    _install(monkeypatch, {"decide_next_v1": decide, "azure_llm_v1": tool})
    flow = json.loads(json.dumps(LOOP_FLOW))
    flow["nodes"][1]["config"]["skill_allowlist"] = ["azure_llm_v1"]
    flow["nodes"][1]["config"]["privilege_tier"] = "recommend"
    flow["nodes"][1]["config"]["goal"]["done_when"] = ["azure_llm_v1"]
    system = _mk_system(db_session, flow, ["decide_next_v1", "azure_llm_v1"])
    row = db_session.query(Skill).filter_by(slug="azure_llm_v1").one()
    row.input_schema = {"type": "object", "properties": {"query": {"type": "string"}},
                        "required": ["query"], "additionalProperties": False}
    db_session.commit()
    run = _mk_run(db_session, system, query="operating limit")
    run.execution_contract = compile_execution_contract(db_session, flow=flow,
        workspace_id=None, runtime_mode="dag_overlay")
    db_session.commit()
    result = await execute_run_dag(run.id)
    assert result["status"] == "completed"
    assert seen == [{"query": "operating limit"}]


def test_retrieval_evidence_view_preserves_sources_and_raw_output():
    from copy import deepcopy
    from app.services.run_engine.agent_loop import retrieval_evidence_view
    output = {"results": [{"content": "full passage " * 1000, "metadata": {
        "document_id": "doc", "chunk_id": "chunk", "page": 2, "sheet": "Orders",
        "cell": "B4", "start_char": 0, "end_char": 13000, "custom_source_ref": "ref",
        "retrieval_role": "advisory_context", "retrieval_evidence_coverage": 0.5,
        "retrieval_evidence_terms_missing": ["cause"], "retrieval_terms": ["debug"],
        "content": "stored duplicate", "dense_elapsed_ms": 5,
    }}], "retrieval_scope": {"collection": "restricted"},
        "fallback_reason": "missing_index", "retrieval_decision_trace": {"verbose": "debug"}}
    original = deepcopy(output)
    view = retrieval_evidence_view(output)
    assert output == original
    assert view["results"][0]["content"] == original["results"][0]["content"]
    assert view["retrieval_scope"] == output["retrieval_scope"]
    assert view["fallback_reason"] == "missing_index"
    metadata = view["results"][0]["metadata"]
    for key in ("document_id", "chunk_id", "page", "sheet", "cell", "start_char",
                "end_char", "custom_source_ref", "retrieval_role", "retrieval_evidence_coverage",
                "retrieval_evidence_terms_missing"):
        assert metadata[key] == original["results"][0]["metadata"][key]
    assert "content" not in metadata and "dense_elapsed_ms" not in metadata
    assert view["evidence_view"]["passages_retained"] == 1
    assert view["evidence_view"]["passages_omitted"] == 0
    assert "retrieval_decision_trace" not in view
    malformed = {"results": ["unexpected"]}
    assert retrieval_evidence_view(malformed) is malformed
