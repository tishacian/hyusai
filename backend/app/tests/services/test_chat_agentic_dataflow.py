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
from app.models.workspace import Workspace
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


@pytest.fixture(autouse=True)
def _andritz_workspace(db_session):
    workspace = Workspace(
        id="ws-andritz",
        name="Andritz dataflow test",
        slug="andritz",
        settings={"family": "andritz"},
    )
    db_session.add(workspace)
    db_session.commit()
    return workspace


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
            workspace_id="ws-andritz",
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


def _flow_skill_ids(db, flow: Dict[str, Any]) -> List[str]:
    """Bind every executable branch, including branches inactive in a test."""

    slugs = sorted(
        {
            str((node.get("config") or {}).get("skill_slug"))
            for node in (flow.get("nodes") or [])
            if node.get("kind") in {"task", "retry", "loop"}
            and (node.get("config") or {}).get("skill_slug")
        }
    )
    existing = {
        row.slug: row
        for row in db.query(Skill).filter(Skill.slug.in_(slugs)).all()
    }
    for slug in slugs:
        if slug not in existing:
            _mk_skill(db, slug)
    return [
        row.id
        for row in db.query(Skill).filter(Skill.slug.in_(slugs)).all()
    ]


@pytest.mark.asyncio
async def test_agentic_dag_dataflow_grounds_generate_and_self_correct(db_session, monkeypatch):
    flow = _load_flow_definition()

    # ----- record every skill call: slug -> list of (payload, ctx) ----------
    calls: Dict[str, List[Dict[str, Any]]] = {}

    def _record(slug: str):
        async def _fn(payload: Dict[str, Any], ctx: Dict[str, Any] | None = None):
            calls.setdefault(slug, []).append(
                {"payload": dict(payload or {}), "ctx": dict(ctx or {})}
            )
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
        "eval_radar_v1": {
            "axes": {},
            "overall": 0.6,
            "hallucination_rate": 0.2,
            "drift_rate": 0.0,
            "note": "",
        },
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
        workspace_id="ws-andritz",
        name="Andritz Chat Agentic (dataflow test)",
        objective="test",
        skill_ids=_flow_skill_ids(db_session, flow),
        flow_definition=flow,
        default_model="gpt-4o-mini",
    )
    db_session.add(system)
    db_session.commit()

    run = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id="ws-andritz",
        input_ref={"query": _QUERY, "workspace_slug": "andritz"},
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
    # Phase 2 (p2-binding), flag OFF (default): the asset-sourced ``collection``
    # VariableRef is GATED — retrieval keeps implicit workspace resolution, so the
    # bound collection slug must NOT reach the retrieval skill (iso Phase 1).
    assert "collection" not in search_payload, (
        "flag OFF must not pass the asset-bound collection (implicit workspace "
        "resolution); the gate seam in dag.py leaked the asset ref"
    )

    # ----- C1: task.generate CONSUMES join.retrieval.results ----------------
    gen_payload = calls["llm_rag_answer_v1"][0]["payload"]
    assert gen_payload["query"] == _QUERY
    assert (
        isinstance(gen_payload.get("context"), list) and gen_payload["context"]
    ), "task.generate received an EMPTY context — join.retrieval.results not wired"
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
    assert (
        isinstance(sc_payload.get("context"), list) and sc_payload["context"]
    ), "self_correct did not receive join.retrieval.results as context"
    assert sc_payload["context"][0]["content"] == _RETRIEVED[0]["content"]

    # Production chat Runs snapshot the tenant slug so every retrieval hop and
    # retry keeps the same physical collection namespace.
    any_ctx = calls["llm_rag_answer_v1"][0]["ctx"]
    assert any_ctx.get("workspace_id") == "ws-andritz"
    assert any_ctx.get("workspace_slug") == "andritz"


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
        "llm_rag_answer_v1": {
            "answer": "ne devrait pas etre appele",
            "citations": [],
            "decision_steps": [],
        },
        "eval_radar_v1": {
            "axes": {},
            "overall": 0.0,
            "hallucination_rate": 0.0,
            "drift_rate": 0.0,
            "note": "",
        },
        "claim_audit_v1": {"claims": [], "verdict": "ok", "supported": 0, "unsupported": 0},
        "response_eval_v1": {
            "composite": 80.0,
            "hallucination_rate": 0.0,
            "context_count": 1,
            "hhem": 0.0,
            "factuality": 1.0,
            "coherence": 1.0,
        },
        "chat_self_correct_v1": {"answer": "", "citations": [], "action_taken": "declare_partial"},
    }
    slugs = list(outputs)
    _install_fake_registry(monkeypatch, {s: _record(s, outputs[s]) for s in slugs})
    for slug in slugs:
        _mk_skill(db_session, slug)

    system = System(
        id=str(uuid.uuid4()),
        workspace_id="ws-andritz",
        name="Andritz Chat Agentic (clarify test)",
        objective="test",
        skill_ids=_flow_skill_ids(db_session, flow),
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
        "llm_rag_answer_v1": {
            "answer": "Das QMS-12 misst Flächengewicht [1].",
            "citations": [{"index": 1, "source_id": "50a149bf-chunk_0"}],
            "decision_steps": [],
        },
        "eval_radar_v1": {
            "axes": {},
            "overall": 0.8,
            "hallucination_rate": 0.0,
            "drift_rate": 0.0,
            "note": "",
        },
        "claim_audit_v1": {"claims": [], "verdict": "ok", "supported": 1, "unsupported": 0},
        # context_count > 0 -> deliver context gate suppresses reject_oos.
        "response_eval_v1": {
            "composite": 85.0,
            "hallucination_rate": 0.0,
            "context_count": 1,
            "hhem": 0.0,
            "factuality": 1.0,
            "coherence": 1.0,
        },
        "chat_self_correct_v1": {"answer": "", "citations": [], "action_taken": "declare_partial"},
    }
    slugs = list(outputs)
    _install_fake_registry(monkeypatch, {s: _record(s, outputs[s]) for s in slugs})
    for slug in slugs:
        _mk_skill(db_session, slug)

    system = System(
        id=str(uuid.uuid4()),
        workspace_id="ws-andritz",
        name="Andritz Chat Agentic (oos backstop test)",
        objective="test",
        skill_ids=_flow_skill_ids(db_session, flow),
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


# ---------------------------------------------------------------------------
# Phase 2 — latency: LLM judges decoupled from the verdict / egress path.
# ---------------------------------------------------------------------------
def _static_ancestors(flow: Dict[str, Any], node_id: str) -> set:
    """Backward-reachable node set over ALL edges (static graph, ignores
    runtime pruning) — mirrors the DAG validator's ancestor semantics."""
    rev: Dict[str, List[str]] = {}
    for edge in flow.get("edges") or []:
        rev.setdefault(edge["to"], []).append(edge["from"])
    seen: set = set()
    stack = list(rev.get(node_id, []))
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(rev.get(cur, []))
    return seen


def test_flow_valid_and_judges_removed_from_online_serving_dag():
    """Phase A latency proof (structural): the two LLM judges (eval_radar /
    claim_audit) are GONE from the online serving DAG entirely — no node, no edge.
    The verdict/egress path depends ONLY on task.response_eval (embeddings). The
    fork.self_eval -> join.eval scaffold is retained as an instant terminal
    telemetry no-op. P0.3 deliberately stopped balancing forks/joins by global
    counts, so this overlay flow may expose its genuine topology debt as warnings
    while remaining executable and error-free."""
    from app.services.chains.dag_validator import has_errors, validate_flow

    flow = _load_flow_definition()

    issues = validate_flow(flow)
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warn"]
    assert not has_errors(issues), errors
    assert errors == []
    assert {item.code for item in warnings} <= {
        "fork_fanout_invalid",
        "join_fanin_invalid",
        "branch_label_invalid",
        "join_without_matching_fork",
    }, [i.to_dict() for i in issues]

    node_ids = {n["id"] for n in flow["nodes"]}
    # The LLM judge nodes were removed from the online serving DAG.
    assert "task.eval_radar" not in node_ids
    assert "task.claim_audit" not in node_ids
    # No edge anywhere references the removed judge nodes.
    for e in flow["edges"]:
        assert e["from"] not in ("task.eval_radar", "task.claim_audit")
        assert e["to"] not in ("task.eval_radar", "task.claim_audit")

    edges = {(e["from"], e["to"]) for e in flow["edges"]}
    # Critical path: generate -> response_eval -> verdict (direct, embeddings only).
    assert ("task.generate", "task.response_eval") in edges
    assert ("task.response_eval", "decision.verdict") in edges
    # join.eval is a terminal telemetry sink fed ONLY by the instant fork scaffold.
    assert ("join.eval", "decision.verdict") not in edges
    assert not any(src == "join.eval" for src, _ in edges), "join.eval must be terminal"
    assert ("fork.self_eval", "join.eval") in edges

    egress_nodes = [
        "decision.verdict",
        "task.self_correct",
        "decision.egress_gate",
        "decision.deliver",
        "sink.final_answer",
    ]
    for node_id in egress_nodes:
        ancestors = _static_ancestors(flow, node_id)
        assert (
            "task.response_eval" in ancestors
        ), f"{node_id} must depend on response_eval (embeddings barrier)"
        assert (
            "task.eval_radar" not in ancestors
        ), f"{node_id} still depends on the eval_radar LLM judge (egress blocked)"
        assert (
            "task.claim_audit" not in ancestors
        ), f"{node_id} still depends on the claim_audit LLM judge (egress blocked)"

    # The retained scaffold: join.eval's only ancestors are the instant fork and
    # its generate feed — never an LLM judge.
    judge_ancestors = _static_ancestors(flow, "join.eval")
    assert "fork.self_eval" in judge_ancestors
    assert "task.eval_radar" not in judge_ancestors
    assert "task.claim_audit" not in judge_ancestors
    # decision.verdict still reads the response_eval composite via inputs_map.
    verdict = next(n for n in flow["nodes"] if n["id"] == "decision.verdict")
    vmap = verdict["config"]["inputs_map"]
    assert vmap["composite"]["node_id"] == "task.response_eval"
    assert vmap["context_count"]["node_id"] == "task.response_eval"


@pytest.mark.asyncio
async def test_agentic_dag_answer_egresses_without_llm_judges(db_session, monkeypatch):
    """Phase A latency runtime proof: the answer is delivered from the
    response_eval-driven (embeddings) verdict path WITHOUT the two LLM judges
    ever being invoked — they were removed from the online serving DAG, so they
    can no longer sit on the run's wall-clock critical path. Even if the fake
    registry could resolve them, no node references them so they never fire; and
    to make the "does not block egress" guarantee concrete, the judge skills are
    wired to a slow coroutine that would time out the run if it were ever awaited
    on the answer path."""
    import asyncio

    flow = _load_flow_definition()
    calls: Dict[str, int] = {}

    def _record(slug: str, output: Dict[str, Any]):
        async def _fn(payload, ctx=None):
            calls[slug] = calls.get(slug, 0) + 1
            return output

        return _fn

    def _slow_judge(slug: str):
        async def _fn(payload, ctx=None):
            calls[slug] = calls.get(slug, 0) + 1
            await asyncio.sleep(30)  # would blow any latency budget if awaited
            return {}

        return _fn

    plan_out = {
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
        "sub_queries": [],
    }
    outputs = {
        "chat_agentic_plan_v1": plan_out,
        "semantic_search_v1": {"results": _RETRIEVED},
        "llm_rag_answer_v1": {
            "answer": "Largeur 0.3 m [1].",
            "citations": [{"index": 1, "source_id": "50a149bf-chunk_0"}],
            "decision_steps": [],
        },
        # strong verdict (composite >= 50) -> self_correct skipped.
        "response_eval_v1": {
            "composite": 82.0,
            "hallucination_rate": 0.1,
            "context_count": 1,
            "hhem": 0.1,
            "factuality": 0.9,
            "coherence": 0.9,
        },
        "chat_self_correct_v1": {
            "answer": "should not run",
            "citations": [],
            "action_taken": "declare_partial",
        },
    }
    slugs = list(outputs)
    registry = {s: _record(s, outputs[s]) for s in slugs}
    # The judge skills are still registered (they remain available), but wired to
    # a 30s sleep: if any surviving edge put them on the answer path the run would
    # not complete promptly. They must simply never be invoked.
    registry["eval_radar_v1"] = _slow_judge("eval_radar_v1")
    registry["claim_audit_v1"] = _slow_judge("claim_audit_v1")
    _install_fake_registry(monkeypatch, registry)
    for slug in list(registry):
        _mk_skill(db_session, slug)

    system = System(
        id=str(uuid.uuid4()),
        workspace_id="ws-andritz",
        name="Andritz Chat Agentic (latency test)",
        objective="test",
        skill_ids=_flow_skill_ids(db_session, flow),
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

    # If a judge were still on the critical path the 30s sleep would trip this.
    summary = await asyncio.wait_for(execute_run_dag(run.id), timeout=10)
    assert summary["status"] == "completed", summary

    # The answer was delivered from the (strong) response_eval verdict path.
    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).first()
    assert run.output_ref.get("answer") == "Largeur 0.3 m [1]."
    # Strong verdict: self_correct was NOT invoked (verdict read response_eval).
    assert "chat_self_correct_v1" not in calls
    # The LLM judges NEVER ran: they are no longer wired into the serving DAG.
    assert "eval_radar_v1" not in calls
    assert "claim_audit_v1" not in calls


@pytest.mark.asyncio
async def test_agentic_dag_multihop_lane_selected_when_sub_queries(db_session, monkeypatch):
    """Phase 4 proof: when the plan emits sub_queries, route_mode selects the
    multi_hop_retrieve lane (single active lane) and task.generate consumes its
    merged results; the single-lane semantic_search retrievers do NOT fire."""
    flow = _load_flow_definition()
    calls: Dict[str, List[Dict[str, Any]]] = {}

    def _record(slug: str, output: Dict[str, Any]):
        async def _fn(payload, ctx=None):
            calls.setdefault(slug, []).append(dict(payload or {}))
            return output

        return _fn

    _MERGED = [
        {"content": "Wilo NOLH pump spec.", "metadata": {"chunk_id": "w-1"}, "score": 0.9},
        {"content": "KSB Etanorm pump spec.", "metadata": {"chunk_id": "k-1"}, "score": 0.88},
    ]
    plan_out = {
        "action": "answer",
        "mode": "balanced",
        "answer_profile": "comparison",
        "scope_hint": "pompes",
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
        "sub_queries": ["Wilo NOLH pump", "KSB Etanorm pump"],
    }
    outputs = {
        "chat_agentic_plan_v1": plan_out,
        "semantic_search_v1": {"results": _RETRIEVED},  # should NOT be called
        "multi_hop_retrieve_v1": {
            "results": _MERGED,
            "raw_chunks_retrieved": 4,
            "sub_queries": ["Wilo NOLH pump", "KSB Etanorm pump"],
            "hop_count": 3,
        },
        "llm_rag_answer_v1": {
            "answer": "Wilo vs KSB [1][2].",
            "citations": [{"index": 1, "source_id": "w-1"}, {"index": 2, "source_id": "k-1"}],
            "decision_steps": [],
        },
        "eval_radar_v1": {
            "axes": {},
            "overall": 0.8,
            "hallucination_rate": 0.1,
            "drift_rate": 0.0,
            "note": "",
        },
        "claim_audit_v1": {"claims": [], "verdict": "ok", "supported": 2, "unsupported": 0},
        "response_eval_v1": {
            "composite": 80.0,
            "hallucination_rate": 0.1,
            "context_count": 2,
            "hhem": 0.1,
            "factuality": 0.9,
            "coherence": 0.9,
        },
        "chat_self_correct_v1": {"answer": "", "citations": [], "action_taken": "declare_partial"},
    }
    slugs = list(outputs)
    _install_fake_registry(monkeypatch, {s: _record(s, outputs[s]) for s in slugs})
    for slug in slugs:
        _mk_skill(db_session, slug)

    system = System(
        id=str(uuid.uuid4()),
        workspace_id="ws-andritz",
        name="Andritz Chat Agentic (multihop test)",
        objective="test",
        skill_ids=_flow_skill_ids(db_session, flow),
        flow_definition=flow,
        default_model="gpt-4o-mini",
    )
    db_session.add(system)
    db_session.commit()
    run = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        workspace_id="ws-andritz",
        input_ref={"query": "compare Wilo NOLH and KSB Etanorm"},
        status="pending",
    )
    db_session.add(run)
    db_session.commit()

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed", summary

    # The multi-hop lane fired with the planner's sub_queries wired through.
    assert "multi_hop_retrieve_v1" in calls, "route_mode did not select the multihop lane"
    mh_payload = calls["multi_hop_retrieve_v1"][0]
    assert mh_payload["sub_queries"] == ["Wilo NOLH pump", "KSB Etanorm pump"]
    assert mh_payload["query"] == "compare Wilo NOLH and KSB Etanorm"
    # Single-active-lane: the plain semantic_search retrievers did NOT run.
    assert "semantic_search_v1" not in calls
    # task.generate consumed the MERGED multi-hop results (join.retrieval.results).
    gen_payload = calls["llm_rag_answer_v1"][0]
    assert [c["content"] for c in gen_payload["context"]] == [c["content"] for c in _MERGED]

    db_session.expire_all()
    run = db_session.query(Run).filter(Run.id == run.id).first()
    assert run.output_ref.get("answer") == "Wilo vs KSB [1][2]."


# ---------------------------------------------------------------------------
# Phase 2 — authoritative asset -> collection binding (flag-gated).
# ---------------------------------------------------------------------------
_ASSET_COLLECTION_SLUG = "andritz-notices-techniques-spl-pilot"


async def _run_binding_probe(db_session, monkeypatch) -> Dict[str, Any]:
    """Walk the real flow with mocked skills and return the balanced retrieve
    lane's payload. Shared by the flag OFF / ON binding tests below."""
    flow = _load_flow_definition()
    calls: Dict[str, List[Dict[str, Any]]] = {}

    def _record(slug: str, output: Dict[str, Any]):
        async def _fn(payload, ctx=None):
            calls.setdefault(slug, []).append(dict(payload or {}))
            return output

        return _fn

    plan_out = {
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
        "sub_queries": [],
    }
    outputs = {
        "chat_agentic_plan_v1": plan_out,
        "semantic_search_v1": {"results": _RETRIEVED},
        "llm_rag_answer_v1": {
            "answer": "Largeur 0.3 m [1].",
            "citations": [{"index": 1, "source_id": "50a149bf-chunk_0"}],
            "decision_steps": [],
        },
        "response_eval_v1": {
            "composite": 82.0,
            "hallucination_rate": 0.1,
            "context_count": 1,
            "hhem": 0.1,
            "factuality": 0.9,
            "coherence": 0.9,
        },
        "chat_self_correct_v1": {"answer": "", "citations": [], "action_taken": "declare_partial"},
    }
    slugs = list(outputs)
    _install_fake_registry(monkeypatch, {s: _record(s, outputs[s]) for s in slugs})
    for slug in slugs:
        _mk_skill(db_session, slug)

    system = System(
        id=str(uuid.uuid4()),
        workspace_id="ws-andritz",
        name="Andritz Chat Agentic (binding test)",
        objective="test",
        skill_ids=_flow_skill_ids(db_session, flow),
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
    assert "semantic_search_v1" in calls, "the balanced retrieve lane never fired"
    return calls["semantic_search_v1"][0]


@pytest.mark.asyncio
async def test_asset_binding_flag_off_is_iso_phase1_no_collection(db_session, monkeypatch):
    """Flag OFF (default): the DAG completes AND the asset-bound collection is NOT
    passed to the retrieval skill — implicit workspace resolution, iso Phase 1."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "flow_asset_binding_authoritative", False)
    search_payload = await _run_binding_probe(db_session, monkeypatch)
    assert (
        "collection" not in search_payload
    ), "flag OFF leaked the asset-bound collection into the retrieval payload"
    # The rest of the payload is unchanged (the non-asset inputs_map still wires).
    assert search_payload["query"] == _QUERY
    assert search_payload["top_k"] == 8


@pytest.mark.asyncio
async def test_asset_binding_flag_on_passes_bound_collection(db_session, monkeypatch):
    """Flag ON: the retrieve lane receives the asset node's collection slug via
    the inputs_map VariableRef (authoritative binding)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "flow_asset_binding_authoritative", True)
    search_payload = await _run_binding_probe(db_session, monkeypatch)
    assert (
        search_payload.get("collection") == _ASSET_COLLECTION_SLUG
    ), "flag ON must pass the asset-bound collection to semantic_search_v1"
    # Binding is additive: the non-asset inputs_map is still wired through.
    assert search_payload["query"] == _QUERY
    assert search_payload["top_k"] == 8
