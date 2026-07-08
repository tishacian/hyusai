"""Data-flow simulation of the ``andritz_chat_agentic_v3`` DAG.

This is the runtime proof requested by the grounding audit
(``docs/chat-recherche-agentic-grounding-audit-2026-06-26.md``): it walks the
*real* pinned flow definition through ``execute_run_dag`` with the skills
mocked at the registry level (NO OpenAI / Qdrant), and asserts the
``inputs_map`` wiring actually delivers the right payloads:

  * C1 — ``task.generate`` (llm_rag_answer_v1) receives ``context`` populated
    from ``join.retrieval.results`` (the retrieved chunks), instead of an empty
    payload that would force an in-skill (historically empty) re-retrieval.
  * C1 — ``task.retrieve_*`` (semantic_search_v1) receives the query + the
    plan's budgets (latency_profile / retrieval_profile / top_k / scope).
  * C2 — ``task.self_correct`` receives ``scope_hint`` / ``lang_target`` /
    ``answer_profile`` (the inputs its escalate_deep re-retrieval needs).
  * Root cause — the run-engine ctx exposes ``workspace_id`` but NOT
    ``workspace_slug`` (which is exactly why the skills must resolve the slug
    themselves to hit the tenant-scoped Qdrant collection).

The skill behaviours themselves are unit-tested in
``test_chat_agentic_skills.py``; here we only pin the graph wiring.
"""
from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any, Callable, Dict, List

import pytest

from app.models.run import Run
from app.models.skill import Skill
from app.models.system import System
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import execute_run_dag


_FLOW_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "resources"
    / "flows"
    / "andritz_chat_agentic_v3.json"
)

_QUERY = "Quelle est la largeur de travail de l'AKK200 ?"

# The single grounding chunk every retrieve lane returns (mirrors the real
# AKK200 carrier chunk the audit tracks).
_RETRIEVED = [
    {
        "content": "Working width 0.3 m, line speed 10 to 20 m/min.",
        "metadata": {"chunk_id": "50a149bf-chunk_0", "document_filename": "AKK200.pdf"},
        "score": 0.91,
    }
]


def _load_flow_definition() -> Dict[str, Any]:
    with _FLOW_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)["flow_definition"]


def _install_fake_registry(monkeypatch, skills: Dict[str, Callable]) -> None:
    def _resolve(slug: str):
        fn = skills.get(slug)
        if fn is None:
            raise NotImplementedError(f"fake registry has no {slug!r}")
        return fn

    monkeypatch.setattr(engine_module, "resolve_skill", _resolve)


def _mk_skill(db, slug: str) -> None:
    db.add(
        Skill(
            id=str(uuid.uuid4()),
            slug=slug,
            version="v1",
            name=slug,
            description=f"test {slug}",
            input_schema={},
            output_schema={},
            pricing={"unit_price": 0.0},
            execution={"mode": "sync", "timeout_ms": 1000, "retryable": True, "idempotent": True},
            certification_level="basic",
        )
    )
    db.commit()


@pytest.mark.asyncio
async def test_agentic_dag_dataflow_grounds_generate_and_self_correct(db_session, monkeypatch):
    flow = _load_flow_definition()

    # ----- record every skill call: slug -> list of (payload, ctx) ----------
    calls: Dict[str, List[Dict[str, Any]]] = {}

    def _record(slug: str):
        async def _fn(payload: Dict[str, Any], ctx: Dict[str, Any] | None = None):
            calls.setdefault(slug, []).append({"payload": dict(payload or {}), "ctx": dict(ctx or {})})
            return _OUTPUTS[slug]
        return _fn

    _OUTPUTS: Dict[str, Dict[str, Any]] = {
        "chat_agentic_plan_v1": {
            "action": "answer",
            "mode": "balanced",
            "answer_profile": "technical",
            "scope_hint": "AKK200",
            "clarifying_question": "",
            "oos_reason": "",
            "lang_target": "fr",
            "confidence": 0.8,
            "retrieval": {
                "latency_profile": "balanced",
                "retrieval_profile": "chat",
                "top_k": 8,
                "synthesis_k": 16,
                "candidate_pool_k": 40,
                "rag_pipeline_mode": "chah",
                "deep_retrieval": False,
            },
        },
        # All retrieve lanes share one mock; only the balanced lane should fire.
        "semantic_search_v1": {"results": _RETRIEVED},
        "llm_rag_answer_v1": {
            "answer": "Largeur de travail 0.3 m [1].",
            "citations": [{"index": 1, "source_id": "50a149bf-chunk_0"}],
            "decision_steps": [],
        },
        "eval_radar_v1": {"axes": {}, "overall": 0.6, "hallucination_rate": 0.2, "drift_rate": 0.0, "note": ""},
        "claim_audit_v1": {"claims": [], "verdict": "ok", "supported": 1, "unsupported": 0},
        # composite 45 < 50 -> decision.verdict routes to the WEAK branch so
        # self_correct fires; composite >= 40 keeps the egress gate on "ok"
        # (no HITL pause), action=answer -> deliver -> final_answer sink.
        # NB: hallucination_rate is no longer in the verdict (parity fix) — the
        # gate is purely composite + context_count, so the WEAK branch needs a
        # composite below the 50 quality floor.
        "response_eval_v1": {
            "composite": 45.0,
            "hallucination_rate": 0.2,
            "context_count": 1,
            "hhem": 0.2,
            "factuality": 0.8,
            "coherence": 0.8,
        },
        "chat_self_correct_v1": {
            "answer": "Largeur de travail corrigee: 0.3 m [1].",
            "citations": [{"index": 1, "source_id": "50a149bf-chunk_0"}],
            "action_taken": "escalate_deep",
        },
    }

    slugs = list(_OUTPUTS)
    _install_fake_registry(monkeypatch, {slug: _record(slug) for slug in slugs})
    for slug in slugs:
        _mk_skill(db_session, slug)

    system = System(
        id=str(uuid.uuid4()),
        name="Andritz Chat Agentic (dataflow test)",
        objective="test",
        skill_ids=[r.id for r in db_session.query(Skill).filter(Skill.slug.in_(slugs)).all()],
        flow_definition=flow,
        default_model="gpt-4o-mini",
    )
    db_session.add(system)
    db_session.commit()

    run = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id="ws-andritz",
        input_ref={"query": _QUERY},
        status="pending",
    )
    db_session.add(run)
    db_session.commit()

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary

    # ----- C1: retrieve lane got the query + the plan's budgets -------------
    assert "semantic_search_v1" in calls, "the balanced retrieve lane never fired"
    search_payload = calls["semantic_search_v1"][0]["payload"]
    assert search_payload["query"] == _QUERY
    assert search_payload["latency_profile"] == "balanced"
    assert search_payload["retrieval_profile"] == "chat"
    assert search_payload["top_k"] == 8
    assert search_payload["knowledge_scope"] == "AKK200"
    # Recall-parity: the full balanced budget triple is wired through inputs_map.
    assert search_payload["synthesis_k"] == 16
    assert search_payload["candidate_pool_k"] == 40

    # ----- C1: task.generate CONSUMES join.retrieval.results ----------------
    gen_payload = calls["llm_rag_answer_v1"][0]["payload"]
    assert gen_payload["query"] == _QUERY
    assert isinstance(gen_payload.get("context"), list) and gen_payload["context"], (
        "task.generate received an EMPTY context — join.retrieval.results not wired"
    )
    assert gen_payload["context"][0]["content"] == _RETRIEVED[0]["content"]
    assert gen_payload["answer_profile"] == "technical"
    assert gen_payload["lang_target"] == "fr"

    # ----- C2: self_correct got the scope/lang/profile its escalate needs ---
    assert "chat_self_correct_v1" in calls, "weak verdict did not route to self_correct"
    sc_payload = calls["chat_self_correct_v1"][0]["payload"]
    assert sc_payload["scope_hint"] == "AKK200"
    assert sc_payload["lang_target"] == "fr"
    assert sc_payload["answer_profile"] == "technical"
    assert sc_payload["query"] == _QUERY
    assert sc_payload["draft_answer"] == _OUTPUTS["llm_rag_answer_v1"]["answer"]
    # Parity fix: self_correct receives the ORIGINAL retrieval context so
    # escalate_deep can MERGE (never lose carrier chunks) with the deep re-search.
    assert isinstance(sc_payload.get("context"), list) and sc_payload["context"], (
        "self_correct did not receive join.retrieval.results as context"
    )
    assert sc_payload["context"][0]["content"] == _RETRIEVED[0]["content"]

    # ----- Root cause: ctx carries workspace_id but NOT workspace_slug ------
    any_ctx = calls["llm_rag_answer_v1"][0]["ctx"]
    assert any_ctx.get("workspace_id") == "ws-andritz"
    assert "workspace_slug" not in any_ctx, (
        "if the engine ever starts seeding workspace_slug, the skill-side "
        "resolver can be simplified — but today it must resolve it itself"
    )


@pytest.mark.asyncio
async def test_agentic_dag_clarify_routes_to_ask_user(db_session, monkeypatch):
    """When the (already-gated) plan still returns clarify, the deliver
    decision must route to the ask_user sink and skip generation entirely."""
    flow = _load_flow_definition()
    calls: Dict[str, int] = {}

    def _record(slug: str, output: Dict[str, Any]):
        async def _fn(payload, ctx=None):
            calls[slug] = calls.get(slug, 0) + 1
            return output
        return _fn

    plan_out = {
        "action": "clarify",
        "mode": "balanced",
        "answer_profile": "technical",
        "scope_hint": "",
        "clarifying_question": "Quel equipement precisement ?",
        "oos_reason": "",
        "lang_target": "fr",
        "confidence": 0.3,
        "retrieval": {
            "latency_profile": "balanced",
            "retrieval_profile": "chat",
            "top_k": 6,
            "rag_pipeline_mode": "chah",
            "deep_retrieval": False,
        },
    }
    outputs = {
        "chat_agentic_plan_v1": plan_out,
        "semantic_search_v1": {"results": _RETRIEVED},
        "llm_rag_answer_v1": {"answer": "ne devrait pas etre appele", "citations": [], "decision_steps": []},
        "eval_radar_v1": {"axes": {}, "overall": 0.0, "hallucination_rate": 0.0, "drift_rate": 0.0, "note": ""},
        "claim_audit_v1": {"claims": [], "verdict": "ok", "supported": 0, "unsupported": 0},
        "response_eval_v1": {"composite": 80.0, "hallucination_rate": 0.0, "context_count": 1, "hhem": 0.0, "factuality": 1.0, "coherence": 1.0},
        "chat_self_correct_v1": {"answer": "", "citations": [], "action_taken": "declare_partial"},
    }
    slugs = list(outputs)
    _install_fake_registry(monkeypatch, {s: _record(s, outputs[s]) for s in slugs})
    for slug in slugs:
        _mk_skill(db_session, slug)

    system = System(
        id=str(uuid.uuid4()),
        name="Andritz Chat Agentic (clarify test)",
        objective="test",
        skill_ids=[r.id for r in db_session.query(Skill).filter(Skill.slug.in_(slugs)).all()],
        flow_definition=flow,
        default_model="gpt-4o-mini",
    )
    db_session.add(system)
    db_session.commit()
    run = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id="ws-andritz",
        input_ref={"query": "vague"},
        status="pending",
    )
    db_session.add(run)
    db_session.commit()

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary

    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).first()
    # The clarify branch surfaces the clarifying question, not a fabricated answer.
    assert run.output_ref.get("clarifying_question") == "Quel equipement precisement ?"
    assert "answer" not in run.output_ref


@pytest.mark.asyncio
async def test_agentic_dag_reject_oos_suppressed_when_context_found(db_session, monkeypatch):
    """OOS backstop: a plan that (wrongly) returns reject_oos but where retrieval
    DID find context (context_count > 0) must fall through to the final answer
    sink — never the oos refusal. Mirrors the QMS-12 German false-positive."""
    flow = _load_flow_definition()
    calls: Dict[str, int] = {}

    def _record(slug: str, output: Dict[str, Any]):
        async def _fn(payload, ctx=None):
            calls[slug] = calls.get(slug, 0) + 1
            return output
        return _fn

    plan_out = {
        "action": "reject_oos",  # planner false-positive
        "mode": "balanced",
        "answer_profile": "technical",
        "scope_hint": "QMS-12",
        "clarifying_question": "",
        "oos_reason": "hors perimetre",
        "lang_target": "de",
        "confidence": 0.5,
        "retrieval": {
            "latency_profile": "balanced",
            "retrieval_profile": "chat",
            "top_k": 8,
            "synthesis_k": 16,
            "candidate_pool_k": 40,
            "rag_pipeline_mode": "chah",
            "deep_retrieval": False,
        },
    }
    outputs = {
        "chat_agentic_plan_v1": plan_out,
        "semantic_search_v1": {"results": _RETRIEVED},
        "llm_rag_answer_v1": {"answer": "Das QMS-12 misst Flächengewicht [1].", "citations": [{"index": 1, "source_id": "50a149bf-chunk_0"}], "decision_steps": []},
        "eval_radar_v1": {"axes": {}, "overall": 0.8, "hallucination_rate": 0.0, "drift_rate": 0.0, "note": ""},
        "claim_audit_v1": {"claims": [], "verdict": "ok", "supported": 1, "unsupported": 0},
        # context_count > 0 -> deliver context gate suppresses reject_oos.
        "response_eval_v1": {"composite": 85.0, "hallucination_rate": 0.0, "context_count": 1, "hhem": 0.0, "factuality": 1.0, "coherence": 1.0},
        "chat_self_correct_v1": {"answer": "", "citations": [], "action_taken": "declare_partial"},
    }
    slugs = list(outputs)
    _install_fake_registry(monkeypatch, {s: _record(s, outputs[s]) for s in slugs})
    for slug in slugs:
        _mk_skill(db_session, slug)

    system = System(
        id=str(uuid.uuid4()),
        name="Andritz Chat Agentic (oos backstop test)",
        objective="test",
        skill_ids=[r.id for r in db_session.query(Skill).filter(Skill.slug.in_(slugs)).all()],
        flow_definition=flow,
        default_model="gpt-4o-mini",
    )
    db_session.add(system)
    db_session.commit()
    run = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id="ws-andritz",
        input_ref={"query": "Wozu dient das Qualiscan QMS-12 System?"},
        status="pending",
    )
    db_session.add(run)
    db_session.commit()

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary

    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).first()
    # reject_oos was suppressed (context found) -> grounded answer delivered.
    assert run.output_ref.get("answer") == "Das QMS-12 misst Flächengewicht [1]."
    assert "reason" not in run.output_ref
