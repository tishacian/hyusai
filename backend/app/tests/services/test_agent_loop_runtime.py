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
