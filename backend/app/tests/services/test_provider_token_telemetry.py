"""Honest provider-token telemetry for the Contract Risk vertical slice."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.context import Context
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.services.embedding.embedder import Embedder
from app.services.evaluation.judge import (
    DIMENSIONS,
    provider_usage_evidence,
)
from app.services.membrane.enforcement import (
    MeasurementCoverage,
    collect_valve_usage,
    evaluate_valves,
)
from app.services.membrane.spec import MembraneSpec
from app.services.rag import context as rag_context
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import execute_run_dag
from app.services.skills_registry import wrappers


def _install_sequence_router(monkeypatch: pytest.MonkeyPatch, results: list[dict]) -> None:
    queue = list(results)

    class FakeClient:
        async def generate(self, model, prompt, **kwargs):
            assert queue, "unexpected provider call"
            return queue.pop(0)

    class FakeRouter:
        async def get_client(self, preferences):
            return FakeClient()

    monkeypatch.setattr("app.services.model_router.ModelRouter", FakeRouter)


def _install_openai_embedding_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    *,
    native_usage: object | None,
    cache_key: str | None = None,
) -> list[dict]:
    """Run the canonical retrieval wrapper around a provider-shaped response."""

    class FakeEmbeddings:
        def create(self, *, input: list[str], model: str):
            response = {
                "data": [
                    SimpleNamespace(index=index, embedding=[1.0, float(index), 0.5])
                    for index, _text in enumerate(input)
                ]
            }
            if native_usage is not None:
                response["usage"] = native_usage
            return SimpleNamespace(**response)

    embedder = Embedder.__new__(Embedder)
    embedder.model_name = "text-embedding-3-small"
    embedder.provider = "openai"
    embedder._client = SimpleNamespace(embeddings=FakeEmbeddings())
    embedder._local_model = None
    embedder._dimension = 3
    embedder._hash_fallback_count = 0
    observed_results: list[dict] = []

    async def retrieve_impl(_request, *, doc_svc=None, fallback_reason=None):
        cached = (
            rag_context._get_cached_retrieval_context(cache_key, started=time.time())
            if cache_key
            else None
        )
        if cached is not None:
            observed_results.append(cached)
            return cached
        await embedder.embed("contract risk")
        result = {
            "chunks": ["Clause 7 transfers unlimited liability."],
            "scores": [0.91],
            "metadatas": [{"chunk_id": "clause-7"}],
            "metrics": {
                "embedding_provider": "openai",
                "embedding_model": embedder.model_name,
                "raw_chunks_retrieved": 1,
            },
        }
        observed_results.append(result)
        if cache_key:
            rag_context._set_cached_retrieval_context(cache_key, result)
        return result

    monkeypatch.setattr(rag_context, "_retrieve_rag_context", retrieve_impl)
    monkeypatch.setattr(
        rag_context,
        "apply_retrieval_profile_to_request",
        lambda request: request,
    )
    return observed_results


async def _execute_semantic_search_invocation(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> SkillInvocation:
    slug = f"embedding_semantic_search_{uuid4().hex}"
    skill = Skill(
        id=str(uuid4()),
        slug=slug,
        version="1",
        name=slug,
        pricing={"unit": "per_call", "unit_price": 0, "currency": "USD"},
    )
    system = System(
        id=str(uuid4()),
        name="Embedding telemetry canary",
        objective="prove native embedding usage",
        skill_ids=[skill.id],
    )
    run = Run(
        id=str(uuid4()),
        system_id=system.id,
        status="running",
        input_ref={"query": "Which clause is risky?"},
    )
    db_session.add_all([skill, system, run])
    db_session.commit()
    monkeypatch.setattr(
        engine_module,
        "resolve_skill",
        lambda _slug: wrappers._semantic_search_v1,
    )

    invocation = await engine_module._execute_task_node(
        db_session,
        run,
        {"system_id": system.id},
        slug,
        control=None,
        last_output={},
        resolved_input={"query": "Which clause is risky?"},
    )
    assert invocation is not None
    return invocation


@pytest.mark.parametrize(
    ("model", "result"),
    [
        (
            "openai:gpt-test",
            {
                "content": "ok",
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
            },
        ),
        (
            "anthropic:claude-test",
            {
                "content": "ok",
                "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
            },
        ),
        (
            "ollama:qwen-test",
            {"response": "ok", "prompt_eval_count": 3, "eval_count": 4},
        ),
    ],
)
async def test_route_normalizes_real_provider_usage(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    result: dict,
) -> None:
    _install_sequence_router(monkeypatch, [result])
    ctx: dict = {}

    assert await wrappers._route_llm_complete("prompt", model, ctx) == "ok"
    evidence = provider_usage_evidence(ctx[wrappers._PROVIDER_USAGE_CTX_KEY])

    assert evidence["usage"]["total_tokens"] == 7
    assert evidence["usage"]["provider_calls"] == 1
    assert evidence["usage"]["measurement_coverage"] == "complete"


async def test_llm_rag_answer_accumulates_generation_and_review_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_sequence_router(
        monkeypatch,
        [
            {
                "content": "Grounded answer [1].",
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
            {
                "content": "reviewed",
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        ],
    )

    async def review(*, draft, model, ctx, **kwargs):
        await wrappers._route_llm_complete("review", model, ctx)
        return str(draft), {"status": "reviewed"}

    monkeypatch.setattr(wrappers, "_review_inventory_answer_coverage", review)
    ctx = {"default_model": "openai:gpt-test"}
    output = await wrappers._llm_rag_answer_v1(
        {
            "query": "Which clause is risky?",
            "context": [
                {
                    "content": "Clause 7 transfers unlimited liability.",
                    "metadata": {"chunk_id": "clause-7"},
                }
            ],
        },
        ctx,
    )

    assert output["usage"]["total_tokens"] == 11
    assert output["usage"]["prompt_tokens"] == 7
    assert output["usage"]["completion_tokens"] == 4
    assert output["usage"]["provider_calls"] == 2
    assert [call["total_tokens"] for call in output["usage"]["calls"]] == [6, 5]
    assert len(ctx[wrappers._PROVIDER_USAGE_CTX_KEY]["calls"]) == 2


async def test_missing_llm_provider_usage_stays_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_sequence_router(monkeypatch, [{"content": "Grounded answer [1]."}])
    output = await wrappers._llm_rag_answer_v1(
        {
            "query": "risk?",
            "context": [{"content": "Clause 7 risk.", "metadata": {"chunk_id": "c7"}}],
        },
        {"default_model": "openai:gpt-test"},
    )

    assert "usage" not in output
    assert output["provider_usage"]["measurement_coverage"] == "unavailable"
    assert output["provider_usage"]["unreported_calls"] == 1
    usage = collect_valve_usage([{"output_ref": output, "metrics": {}}])
    assert usage.token_coverage is MeasurementCoverage.UNAVAILABLE


async def test_one_sided_provider_counter_never_becomes_a_complete_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_sequence_router(
        monkeypatch,
        [{"content": "Grounded answer [1].", "usage": {"prompt_tokens": 10}}],
    )
    output = await wrappers._llm_rag_answer_v1(
        {
            "query": "risk?",
            "context": [{"content": "Clause 7 risk.", "metadata": {"chunk_id": "c7"}}],
        },
        {"default_model": "openai:gpt-test"},
    )

    assert "usage" not in output
    assert output["provider_usage"]["measurement_coverage"] == "unavailable"
    assert output["provider_usage"]["unreported_calls"] == 1
    usage = collect_valve_usage([{"output_ref": output, "metrics": {}}])
    assert usage.tokens == 0
    assert usage.token_coverage is MeasurementCoverage.UNAVAILABLE


async def test_claim_audit_carries_real_judge_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    completion = json.dumps(
        {
            "scores": {dimension: 90 for dimension in DIMENSIONS},
            "claims": [{"claim": "Clause 7 is risky", "supported": True}],
            "question_type": "simple",
            "overall_note": "grounded",
        }
    )
    _install_sequence_router(
        monkeypatch,
        [
            {
                "content": completion,
                "usage": {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14},
            }
        ],
    )

    output = await wrappers._claim_audit_v1(
        {
            "query": "risk?",
            "answer": "Clause 7 is risky",
            "citations": ["Clause 7 transfers liability"],
        }
    )

    assert output["verdict"] == "supported"
    assert output["usage"]["total_tokens"] == 14
    assert output["usage"]["measurement_source"] == "provider_reported"


async def test_eval_radar_accepts_structured_citations_as_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict = {}

    class FakeJudge:
        async def evaluate(self, **kwargs):
            observed.update(kwargs)
            return {
                "scores": {dimension: 90 for dimension in DIMENSIONS},
                "composite_score": 90.0,
                "hallucination_rate": 0.0,
                "drift_rate": 0.0,
                "overall_note": "grounded",
                "claim_audit": {
                    "supported": 1,
                    "unsupported": 0,
                    "claims": [{"claim": "safe", "supported": True}],
                },
            }

    monkeypatch.setattr(
        "app.services.evaluation.judge.get_judge_service",
        lambda: FakeJudge(),
    )
    citations = [{"text": "Restart is prohibited above 7.1 mm/s RMS."}]

    await wrappers._eval_radar_v1(
        {"query": "Can it restart?", "answer": "No.", "citations": citations},
        {"workspace_id": "workspace-1"},
    )

    assert observed["context_chunks"] == citations
    assert observed["workspace_id"] == "workspace-1"


async def test_claim_audit_does_not_invent_missing_judge_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = json.dumps(
        {
            "scores": {dimension: 90 for dimension in DIMENSIONS},
            "claims": [{"claim": "No risk was found", "supported": False}],
            "question_type": "simple",
            "overall_note": "no usage returned",
        }
    )
    _install_sequence_router(monkeypatch, [{"content": completion}])

    output = await wrappers._claim_audit_v1({"query": "risk?", "answer": "none"})

    assert "usage" not in output
    assert output["provider_usage"]["measurement_coverage"] == "unavailable"
    assert (
        collect_valve_usage([{"output_ref": output, "metrics": {}}]).token_coverage
        is MeasurementCoverage.UNAVAILABLE
    )


async def test_semantic_search_propagates_reported_retrieval_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def retrieve(_request):
        return {
            "chunks": ["clause"],
            "scores": [0.9],
            "metadatas": [{}],
            "metrics": {
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-test",
                "usage": {"prompt_tokens": 6, "completion_tokens": 0, "total_tokens": 6},
            },
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", retrieve)
    monkeypatch.setattr(
        "app.services.rag.context.apply_retrieval_profile_to_request", lambda request: request
    )

    output = await wrappers._semantic_search_v1({"query": "risk?"}, {})
    assert output["usage"]["total_tokens"] == 6
    assert output["usage"]["provider_calls"] == 1


async def test_semantic_search_accumulates_bound_collection_fallback_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = [
        {
            "chunks": [],
            "scores": [],
            "metadatas": [],
            "metrics": {
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-test",
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        },
        {
            "chunks": ["workspace clause"],
            "scores": [0.8],
            "metadatas": [{}],
            "metrics": {
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-test",
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
            },
        },
    ]

    async def retrieve(_request):
        return results.pop(0)

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", retrieve)
    monkeypatch.setattr(
        "app.services.rag.context.apply_retrieval_profile_to_request",
        lambda request: request,
    )

    output = await wrappers._semantic_search_v1(
        {"query": "risk?", "context_collection": "contracts"},
        {},
    )
    assert output["usage"]["total_tokens"] == 5
    assert output["usage"]["prompt_tokens"] == 5
    assert output["usage"]["provider_calls"] == 2


async def test_semantic_search_fallback_is_partial_when_one_embedding_call_is_unreported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = [
        {
            "chunks": [],
            "scores": [],
            "metadatas": [],
            "metrics": {
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-test",
                "provider_usage": {
                    "measurement_coverage": "unavailable",
                    "provider_calls": 1,
                    "reported_calls": 0,
                    "unreported_calls": 1,
                    "reported_total": 0,
                    "calls": [
                        {
                            "provider": "openai",
                            "model": "text-embedding-test",
                            "reported": False,
                        }
                    ],
                },
            },
        },
        {
            "chunks": ["workspace clause"],
            "scores": [0.8],
            "metadatas": [{}],
            "metrics": {
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-test",
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
            },
        },
    ]

    async def retrieve(_request):
        return results.pop(0)

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", retrieve)
    monkeypatch.setattr(
        "app.services.rag.context.apply_retrieval_profile_to_request",
        lambda request: request,
    )

    output = await wrappers._semantic_search_v1(
        {"query": "risk?", "context_collection": "contracts"},
        {},
    )
    assert "usage" not in output
    assert output["provider_usage"]["measurement_coverage"] == "partial"
    assert output["provider_usage"]["provider_calls"] == 2
    assert output["provider_usage"]["reported_calls"] == 1
    assert output["provider_usage"]["reported_total"] == 3


async def test_openai_embedding_usage_reaches_retrieval_wrapper_and_enforce_ledger(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = _install_openai_embedding_retrieval(
        monkeypatch,
        native_usage=SimpleNamespace(prompt_tokens=4, total_tokens=4),
    )

    invocation = await _execute_semantic_search_invocation(db_session, monkeypatch)

    retrieval_usage = observed[0]["metrics"]["usage"]
    assert retrieval_usage["total_tokens"] == 4
    assert retrieval_usage["prompt_tokens"] == 4
    assert retrieval_usage["provider_calls"] == 1
    assert invocation.output_ref["usage"]["total_tokens"] == 4
    assert invocation.metrics["total_tokens"] == 4
    assert invocation.metrics["token_evidence"]["measurement_coverage"] == "complete"

    usage = collect_valve_usage([invocation])
    spec = MembraneSpec.from_dict(
        {
            "version": 2,
            "enforcement_mode": "enforce",
            "valves": {"token_budget": 10},
        },
        authoritative=True,
    )
    decision = evaluate_valves(spec, usage)
    assert usage.tokens == 4
    assert usage.token_coverage is MeasurementCoverage.COMPLETE
    assert decision.allowed is True
    assert decision.breaches == ()


async def test_openai_embedding_missing_usage_blocks_enforce_without_false_zero(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = _install_openai_embedding_retrieval(
        monkeypatch,
        native_usage=None,
    )

    invocation = await _execute_semantic_search_invocation(db_session, monkeypatch)

    retrieval_evidence = observed[0]["metrics"]["provider_usage"]
    assert retrieval_evidence["measurement_coverage"] == "unavailable"
    assert retrieval_evidence["provider_calls"] == 1
    assert "usage" not in invocation.output_ref
    assert invocation.output_ref["provider_usage"]["measurement_coverage"] == "unavailable"
    assert "total_tokens" not in invocation.metrics

    usage = collect_valve_usage([invocation])
    spec = MembraneSpec.from_dict(
        {
            "version": 2,
            "enforcement_mode": "enforce",
            "valves": {"token_budget": 10},
        },
        authoritative=True,
    )
    decision = evaluate_valves(spec, usage)
    assert usage.tokens == 0
    assert usage.token_coverage is MeasurementCoverage.UNAVAILABLE
    assert decision.allowed is False
    assert decision.breaches == ("token_measurement_unavailable",)


async def test_openai_embedding_cache_hit_is_non_token_without_replaying_cold_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_key = f"embedding-telemetry-{uuid4().hex}"
    observed = _install_openai_embedding_retrieval(
        monkeypatch,
        native_usage=SimpleNamespace(prompt_tokens=4, total_tokens=4),
        cache_key=cache_key,
    )

    cold = await wrappers._semantic_search_v1({"query": "risk?"}, {})
    warm = await wrappers._semantic_search_v1({"query": "risk?"}, {})

    assert cold["usage"]["total_tokens"] == 4
    assert cold["usage"]["measurement_source"] == "provider_reported"
    assert observed[1]["metrics"]["retrieval_context_cache_hit"] is True
    assert observed[1]["metrics"]["embedding_provider_usage_scope"] == "canonical_request_v1"
    assert observed[1]["metrics"]["embedding_provider_calls"] == 0
    assert "usage" not in observed[1]["metrics"]
    assert warm["usage"]["total_tokens"] == 0
    assert warm["usage"]["measurement_source"] == "contractual_non_token_path"
    assert warm["usage"]["reason"] == "semantic_search:retrieval_without_provider_call"

    spec = MembraneSpec.from_dict(
        {
            "version": 2,
            "enforcement_mode": "enforce",
            "valves": {"token_budget": 10},
        },
        authoritative=True,
    )
    cold_decision = evaluate_valves(
        spec,
        collect_valve_usage([{"output_ref": cold, "metrics": {}}]),
    )
    warm_decision = evaluate_valves(
        spec,
        collect_valve_usage([{"output_ref": warm, "metrics": {}}]),
    )
    assert cold_decision.allowed is True
    assert warm_decision.allowed is True


@pytest.mark.parametrize(
    ("embedding_provider", "expected_coverage"),
    [("local", "complete"), ("hash", "complete"), ("openai", "unavailable")],
)
async def test_semantic_search_zero_requires_non_token_retrieval_contract(
    monkeypatch: pytest.MonkeyPatch,
    embedding_provider: str,
    expected_coverage: str,
) -> None:
    async def retrieve(_request):
        return {
            "chunks": [],
            "scores": [],
            "metadatas": [],
            "metrics": {"embedding_provider": embedding_provider},
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", retrieve)
    monkeypatch.setattr(
        "app.services.rag.context.apply_retrieval_profile_to_request", lambda request: request
    )

    output = await wrappers._semantic_search_v1({"query": "risk?"}, {})
    if expected_coverage == "complete":
        assert output["usage"]["total_tokens"] == 0
        assert output["usage"]["measurement_source"] == "contractual_non_token_path"
    else:
        assert "usage" not in output
        assert output["provider_usage"]["measurement_coverage"] == "unavailable"


async def test_audit_log_declares_explicit_non_token_zero(db_session) -> None:
    # The wrapper persists through emit_audit_event and fails closed without a
    # workspace to attribute the record to (audit rows are read by workspace).
    workspace = Workspace(id=str(uuid4()), name="Telemetry", slug="telemetry")
    db_session.add(workspace)
    db_session.commit()
    output = await wrappers._audit_log_v1(
        {"event_type": "claim.audited", "details": {}, "workspace_id": workspace.id}
    )

    assert output["status"] == "recorded"
    assert output["usage"]["total_tokens"] == 0
    assert output["usage"]["provider_calls"] == 0
    assert output["usage"]["reason"] == "audit_log:structured_logger_only"


async def test_engine_does_not_promote_partial_provider_totals(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unmetered_llm(_payload, _ctx):
        return {
            "answer": "provider returned text without complete usage",
            "provider_usage": {
                "measurement_coverage": "partial",
                "provider_calls": 2,
                "reported_calls": 1,
                "unreported_calls": 1,
                "reported_total": 9,
                "providers": ["openai"],
            },
        }

    slug = f"unmetered_llm_{uuid4().hex}"
    skill = Skill(
        id=str(uuid4()),
        slug=slug,
        version="1",
        name=slug,
        pricing={"unit": "per_call", "unit_price": 0, "currency": "USD"},
    )
    system = System(
        id=str(uuid4()),
        name="Unmetered provider",
        objective="prove unavailable coverage",
        skill_ids=[skill.id],
    )
    run = Run(id=str(uuid4()), system_id=system.id, status="running", input_ref={})
    db_session.add_all([skill, system, run])
    db_session.commit()
    monkeypatch.setattr(engine_module, "resolve_skill", lambda _slug: unmetered_llm)

    invocation = await engine_module._execute_task_node(
        db_session,
        run,
        {"system_id": system.id},
        slug,
        control=None,
        last_output={},
    )

    assert invocation is not None
    assert "total_tokens" not in invocation.metrics
    assert invocation.metrics["token_evidence"]["measurement_coverage"] == "partial"
    assert invocation.metrics["token_evidence"]["reported_total"] == 9
    usage = collect_valve_usage([invocation])
    assert usage.tokens == 0
    assert usage.token_coverage is MeasurementCoverage.UNAVAILABLE


async def test_contract_risk_four_skill_flow_persists_complete_token_ledger(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the real four-Skill canary graph with deterministic provider evidence."""

    from scripts.seed_showcase_workspace import flow_contract_risk_system360

    async def semantic(_payload, _ctx):
        return {
            "results": [{"content": "Clause 7 risk", "metadata": {"chunk_id": "c7"}}],
            "usage": {"total_tokens": 0, "measurement_source": "contractual_non_token_path"},
        }

    async def answer(_payload, _ctx):
        return {
            "answer": "Clause 7 is risky [1].",
            "citations": [{"id": "c7"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
        }

    async def claim(_payload, _ctx):
        return {
            "claims": [{"claim": "Clause 7 is risky", "supported": True}],
            "verdict": "supported",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }

    async def audit(_payload, _ctx):
        return {
            "id": str(uuid4()),
            "status": "recorded",
            "usage": {"total_tokens": 0, "measurement_source": "contractual_non_token_path"},
        }

    registry = {
        "semantic_search_v1": semantic,
        "llm_rag_answer_v1": answer,
        "claim_audit_v1": claim,
        "audit_log_v1": audit,
    }
    monkeypatch.setattr(engine_module, "resolve_skill", lambda slug: registry[slug])
    monkeypatch.setattr("app.services.evaluation.auto_eval.schedule_eval", lambda _run_id: None)

    workspace = Workspace(
        id=str(uuid4()),
        name="Token telemetry",
        slug=f"token-telemetry-{uuid4().hex[:8]}",
        settings={"features": {"flow_v3_dag_authoritative": True}},
    )
    context = Context(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Contract Risk context",
        environment_state={"audit_event_type": "contract_risk.claim_audited"},
    )
    skills = [
        Skill(
            id=str(uuid4()),
            workspace_id=workspace.id,
            slug=slug,
            version="1",
            name=slug,
            pricing={"unit": "per_call", "unit_price": 0, "currency": "USD"},
        )
        for slug in registry
    ]
    system = System(
        id=str(uuid4()),
        workspace_id=workspace.id,
        context_id=context.id,
        name="Contract Risk token canary",
        objective="prove an honest token ledger",
        skill_ids=[skill.id for skill in skills],
        flow_definition=flow_contract_risk_system360(),
        default_model="openai:gpt-test",
    )
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace.id,
        system_id=system.id,
        status="pending",
        input_ref={"query": "Which clause is risky?"},
        output_ref={},
    )
    db_session.add_all([workspace, context, *skills, system, run])
    db_session.commit()

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"
    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    assert [row.skill_slug for row in invocations] == list(registry)
    assert [row.metrics.get("total_tokens") for row in invocations] == [0, 13, 7, 0]
    usage = collect_valve_usage(invocations)
    assert usage.tokens == 20
    assert usage.token_coverage is MeasurementCoverage.COMPLETE
