from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.rag import context as rag_context
from app.services.rag import corpus_planner
from app.services.skills_registry import wrappers

AUTHORITATIVE = "andritz-notices-techniques-spl-pilot"
OUTSIDE = "andritz-unrelated-workspace-collection"


def _planner_profile(*, latency_profile: str = "balanced") -> dict:
    return {
        "collection": AUTHORITATIVE,
        "collections": [AUTHORITATIVE],
        "workspace_id": "workspace-andritz",
        "latency_profile": latency_profile,
        "rag_mode": "chah",
        "top_k": 8,
        "candidate_pool_k": 40,
        "synthesis_k": 16,
        "source_display_k": 8,
    }


def _collection(slug: str, *, suffix: str, large: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"collection-{suffix}",
        slug=slug,
        workspace_id="workspace-andritz",
        document_count=6_000 if large else 10,
        chunk_count=60_000 if large else 100,
        updated_at=None,
    )


def test_get_retrieval_profile_preserves_authoritative_collection(monkeypatch):
    monkeypatch.setattr(
        rag_context,
        "get_resolved_settings",
        lambda **_kwargs: {
            "ragCollectionName": OUTSIDE,
            "ragVectorDBType": "qdrant",
            "ragPipelineMode": "chah",
            "ragTopK": 5,
        },
    )
    monkeypatch.setattr(
        rag_context,
        "resolve_knowledge_scope",
        lambda **_kwargs: {
            "key": "workspace-wide",
            "label": "Workspace wide",
            "collection_slugs": [OUTSIDE],
            "default_mode": "chah",
        },
    )

    def _must_not_union(*_args, **_kwargs):
        raise AssertionError("authoritative collection must bypass additive expert overlays")

    monkeypatch.setattr(rag_context, "_include_expert_fiche_collection", _must_not_union)

    profile = rag_context.get_retrieval_profile(
        {
            "query": "resume BAO100",
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "knowledge_scope": "workspace-wide",
            "source_policy": {"expert_fiche_correction_enabled": True},
            "authoritative_collections": [AUTHORITATIVE, AUTHORITATIVE],
        }
    )

    assert profile["collection"] == AUTHORITATIVE
    assert profile["collections"] == [AUTHORITATIVE]


def test_corpus_planner_authoritative_scope_never_expands_or_selects_outside_table(
    db_session,
    monkeypatch,
):
    calls: list[list[str]] = []
    allowed = _collection(AUTHORITATIVE, suffix="allowed")

    def _rows_for_collections(_db, collections, _workspace_id, **_kwargs):
        calls.append(list(collections))
        return [], [allowed]

    monkeypatch.setattr(corpus_planner, "_rows_for_collections", _rows_for_collections)
    monkeypatch.setattr(
        corpus_planner,
        "_workspace_collections",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("authoritative planning must not enumerate workspace collections")
        ),
    )
    monkeypatch.setattr(corpus_planner, "_infer_filters", lambda *_args: ({}, 0.0, ""))
    monkeypatch.setattr(
        corpus_planner,
        "_infer_ledger_document_scope",
        lambda *_args, **_kwargs: ({}, 0.0, "", []),
    )
    # Even a buggy/over-broad table detector must be intersected with the hard
    # contract before a second collection lookup is attempted.
    monkeypatch.setattr(
        corpus_planner,
        "_spreadsheet_collection_refs",
        lambda _rows: [OUTSIDE, AUTHORITATIVE],
    )

    plan = corpus_planner.plan_corpus(
        db=db_session,
        profile=_planner_profile(latency_profile="fast"),
        query="Que vaut le label B dans la table Def strips ?",
        request={"authoritative_collections": [AUTHORITATIVE]},
    )

    assert plan.retrieval_scope["collections"] == [AUTHORITATIVE]
    assert calls and all(call == [AUTHORITATIVE] for call in calls)


def test_corpus_planner_discards_ledger_filter_owned_by_outside_collection(
    db_session,
    monkeypatch,
):
    allowed = _collection(AUTHORITATIVE, suffix="allowed")
    monkeypatch.setattr(
        corpus_planner,
        "_rows_for_collections",
        lambda *_args, **_kwargs: ([], [allowed]),
    )
    monkeypatch.setattr(corpus_planner, "_infer_filters", lambda *_args: ({}, 0.0, ""))
    monkeypatch.setattr(
        corpus_planner,
        "_infer_ledger_document_scope",
        lambda *_args, **_kwargs: (
            {"document_filename": ["outside-project-only.pdf"]},
            0.98,
            "outside ledger match",
            [OUTSIDE],
        ),
    )

    plan = corpus_planner.plan_corpus(
        db=db_session,
        profile=_planner_profile(latency_profile="fast"),
        query="resume BAO100",
        request={"authoritative_collections": [AUTHORITATIVE]},
    )

    assert plan.retrieval_scope["collections"] == [AUTHORITATIVE]
    assert "outside-project-only.pdf" not in str(plan.filters)


def test_corpus_planner_clamps_soft_scope_collections(db_session, monkeypatch):
    allowed = _collection(AUTHORITATIVE, suffix="allowed", large=True)
    outside = _collection(OUTSIDE, suffix="outside", large=True)
    monkeypatch.setattr(
        corpus_planner,
        "_rows_for_collections",
        lambda *_args, **_kwargs: ([], [allowed, outside]),
    )
    monkeypatch.setattr(corpus_planner, "_infer_filters", lambda *_args: ({}, 0.0, ""))
    monkeypatch.setattr(
        corpus_planner,
        "_infer_ledger_document_scope",
        lambda *_args, **_kwargs: ({}, 0.0, "", []),
    )
    monkeypatch.setattr(
        corpus_planner,
        "_infer_fact_document_scope",
        lambda *_args, **_kwargs: (
            {"document_filename": ["fact-backed.pdf"]},
            0.9,
            "fact scope",
        ),
    )

    plan = corpus_planner.plan_corpus(
        db=db_session,
        profile=_planner_profile(latency_profile="balanced"),
        query="pression hydraulique pompe",
        request={"authoritative_collections": [AUTHORITATIVE]},
    )

    assert plan.retrieval_scope["collections"] == [AUTHORITATIVE]
    assert plan.soft_scope_collections == [AUTHORITATIVE]
    assert OUTSIDE not in plan.soft_scope_collections
    assert outside.id not in plan.soft_scope_collections


def test_corpus_planner_clamps_recall_floor_collections(db_session, monkeypatch):
    allowed = _collection(AUTHORITATIVE, suffix="allowed", large=True)
    outside = _collection(OUTSIDE, suffix="outside", large=True)
    monkeypatch.setattr(
        corpus_planner,
        "_rows_for_collections",
        lambda *_args, **_kwargs: ([], [allowed, outside]),
    )
    monkeypatch.setattr(corpus_planner, "_infer_filters", lambda *_args: ({}, 0.0, ""))
    monkeypatch.setattr(
        corpus_planner,
        "_infer_ledger_document_scope",
        lambda *_args, **_kwargs: (
            {"document_filename": ["allowed-project.pdf"]},
            0.9,
            "allowed ledger scope",
            [AUTHORITATIVE],
        ),
    )

    plan = corpus_planner.plan_corpus(
        db=db_session,
        profile=_planner_profile(latency_profile="balanced"),
        query="resume BAO100",
        request={"authoritative_collections": [AUTHORITATIVE]},
    )

    assert plan.retrieval_scope["collections"] == [AUTHORITATIVE]
    assert plan.recall_floor_collections == [AUTHORITATIVE]
    assert OUTSIDE not in plan.recall_floor_collections
    assert outside.id not in plan.recall_floor_collections


@pytest.mark.asyncio
async def test_semantic_search_strict_contract_never_retries_workspace(monkeypatch):
    requests: list[dict] = []

    async def _empty_retrieve(request):
        requests.append(dict(request))
        return {
            "chunks": [],
            "scores": [],
            "metadatas": [],
            "metrics": {"raw_chunks_retrieved": 0},
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", _empty_retrieve)
    monkeypatch.setattr(
        "app.services.rag.context.apply_retrieval_profile_to_request",
        lambda request: request,
    )

    result = await wrappers._semantic_search_v1(
        {"query": "resume BAO100", "collection": OUTSIDE},
        {
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "retrieval_contract": {
                "collection": AUTHORITATIVE,
                "asset_binding": "authoritative",
                "empty_bound_collection": "abstain",
                "allow_workspace_fallback": False,
            },
        },
    )

    assert len(requests) == 1
    assert requests[0]["context_collection"] == AUTHORITATIVE
    assert requests[0]["authoritative_collections"] == [AUTHORITATIVE]
    assert requests[0]["context_mode"] == "replace"
    assert "knowledge_scope" not in requests[0]
    assert result["results"] == []


@pytest.mark.asyncio
async def test_semantic_search_strict_contract_preserves_contradictory_proof(monkeypatch):
    requests: list[dict] = []

    async def _grounded_retrieve(request):
        requests.append(dict(request))
        return {
            "chunks": ["BAO100 pump evidence"],
            "scores": [0.91],
            "metadatas": [{"document_filename": "BAO100-pumps.pdf"}],
            "metrics": {
                "raw_chunks_retrieved": 0,
                "collections_touched": [OUTSIDE],
            },
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", _grounded_retrieve)
    monkeypatch.setattr(
        "app.services.rag.context.apply_retrieval_profile_to_request",
        lambda request: request,
    )

    result = await wrappers._semantic_search_v1(
        {"query": "quelles pompes BAO100 ?"},
        {
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "retrieval_contract": {
                "collection": AUTHORITATIVE,
                "asset_binding": "authoritative",
                "empty_bound_collection": "abstain",
                "allow_workspace_fallback": False,
            },
        },
    )

    assert len(requests) == 1
    assert result["raw_chunks_retrieved"] == 0
    assert result["collections_touched"] == [OUTSIDE]
    assert "collection" not in result["results"][0]["metadata"]


@pytest.mark.asyncio
async def test_multi_hop_all_backend_failures_remain_technical(monkeypatch):
    async def _unavailable(*_args, **_kwargs):
        raise ConnectionError("vector backend unavailable")

    monkeypatch.setattr(wrappers, "_semantic_search_v1", _unavailable)

    result = await wrappers._multi_hop_retrieve_v1(
        {
            "query": "resume BCX200",
            "sub_queries": ["pompes BCX200", "moteurs BCX200"],
        },
        {
            "workspace_id": "workspace-andritz",
            "workspace_slug": "andritz",
            "retrieval_contract": {
                "collection": AUTHORITATIVE,
                "asset_binding": "authoritative",
                "empty_bound_collection": "abstain",
                "allow_workspace_fallback": False,
            },
        },
    )

    assert result["results"] == []
    assert result["raw_chunks_retrieved"] == 0
    assert result["collections_touched"] == []
    assert result["hop_count"] == 3
    assert result["fallback_reason"] == "retrieval_backend_error"
