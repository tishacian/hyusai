from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.chains.dag_validator import validate_flow
from app.services.rag import context as rag_context
from app.services.rag.context import (
    _authoritative_filters_for_collection,
    _enforce_authoritative_document_evidence,
    _recall_floor_active,
)
from app.services.rag.corpus_planner import CorpusPlan
from app.services.run_engine.dag import DagNode, _apply_retrieval_node_scope
from app.services.skills_registry import wrappers
from app.services.skills_registry.wrappers import _rag_runtime_kwargs
from app.services.vector_db.chroma_db import _filters_to_chroma_where
from app.services.vector_db.faiss_db import _metadata_matches_filters


def _flow(config: dict) -> dict:
    return {
        "schema_version": 3,
        "nodes": [
            {"id": "source", "type": "source", "kind": "source", "outputs": []},
            {
                "id": "retrieve",
                "type": "retrieve",
                "kind": "task",
                "config": config,
            },
            {"id": "sink", "type": "sink", "kind": "sink", "inputs": []},
        ],
        "edges": [
            {"from": "source", "to": "retrieve", "kind": "data"},
            {"from": "retrieve", "to": "sink", "kind": "data"},
        ],
    }


def test_retrieval_scope_validation_accepts_owned_collection_document_refs():
    issues = validate_flow(
        _flow(
            {
                "collection_slugs": ["manuals", "tickets"],
                "document_refs": [
                    {"collection_slug": "manuals", "document_id": "doc-1"},
                    {"collection_slug": "tickets", "document_id": "doc-2"},
                ],
            }
        )
    )

    assert not [issue for issue in issues if issue.code.startswith("retrieval_")]


def test_retrieval_scope_validation_rejects_document_outside_selected_collections():
    issues = validate_flow(
        _flow(
            {
                "collection_slugs": ["manuals"],
                "document_refs": [
                    {"collection_slug": "other", "document_id": "doc-1"},
                ],
            }
        )
    )

    assert "retrieval_documents_invalid" in {issue.code for issue in issues}


def test_retrieval_scope_validation_accepts_explicit_palette_category():
    flow = _flow(
        {
            "skill_category": "Retrieval",
            "collection_slugs": ["manuals"],
            "document_refs": [],
        }
    )
    flow["nodes"][1]["type"] = "custom_bound_skill"

    issues = validate_flow(flow)

    assert "retrieval_scope_node_invalid" not in {issue.code for issue in issues}


def test_runtime_retrieval_scope_overrides_caller_collection_and_document_scope():
    node = DagNode(
        id="retrieve",
        type="retrieve",
        kind="task",
        label="Retrieve",
        config={
            "collection_slugs": ["manuals", "tickets"],
            "document_refs": [
                {"collection_slug": "manuals", "document_id": "doc-1"},
                {"collection_slug": "tickets", "document_id": "doc-2"},
            ],
        },
        skill_slug="semantic_search_v1",
        data={},
    )
    payload = {
        "authoritative_collections": ["attacker-scope"],
        "retrieval_filters": {"document_id": ["attacker-doc"], "language": "fr"},
    }

    _apply_retrieval_node_scope(node, payload)

    assert payload["authoritative_collections"] == ["manuals", "tickets"]
    assert payload["retrieval_filters"] == {
        "document_id": ["doc-1", "doc-2"],
        "language": "fr",
    }
    assert payload["authoritative_document_scope"] is True
    assert payload["authoritative_document_refs"] == {
        "manuals": ["doc-1"],
        "tickets": ["doc-2"],
    }


def test_rag_runtime_kwargs_forwards_bounded_authoritative_collections():
    kwargs = _rag_runtime_kwargs(
        {
            "authoritative_collections": ["manuals", "manuals", "tickets"],
            "authoritative_document_scope": True,
            "authoritative_document_refs": {
                "manuals": ["doc-1", "doc-1"],
                "tickets": ["doc-2"],
                "outside": ["attacker-doc"],
            },
        },
        {},
    )

    assert kwargs["authoritative_collections"] == ["manuals", "tickets"]
    assert kwargs["authoritative_document_scope"] is True
    assert kwargs["authoritative_document_refs"] == {
        "manuals": ["doc-1"],
        "tickets": ["doc-2"],
    }


def test_rag_runtime_kwargs_preserves_explicit_empty_pair_map_as_fail_closed_signal():
    kwargs = _rag_runtime_kwargs(
        {
            "authoritative_collections": ["manuals"],
            "authoritative_document_scope": True,
            "authoritative_document_refs": {},
            "retrieval_filters": {"document_id": ["legacy-doc"]},
        },
        {},
    )

    assert kwargs["authoritative_document_refs"] == {}


def test_authoritative_document_filters_preserve_collection_document_pairs():
    profile = {
        "authoritative_document_scope": True,
        "authoritative_document_refs": {
            "manuals": ["shared-id", "manual-only"],
            "tickets": ["ticket-only"],
        },
    }
    base = {"document_id": ["shared-id", "manual-only", "ticket-only"], "language": "fr"}

    assert _authoritative_filters_for_collection(profile, "manuals", base) == {
        "document_id": ["shared-id", "manual-only"],
        "language": "fr",
    }
    assert _authoritative_filters_for_collection(profile, "tickets", base) == {
        "document_id": ["ticket-only"],
        "language": "fr",
    }
    assert _authoritative_filters_for_collection(profile, "outside", base) is None

    assert _authoritative_filters_for_collection(
        {
            "authoritative_document_scope": True,
            "authoritative_document_refs": {},
            "authoritative_document_refs_provided": True,
        },
        "manuals",
        base,
    ) is None


def test_legacy_flat_document_scope_is_only_accepted_when_effectively_bounded():
    bounded_profile = {
        "authoritative_document_scope": True,
        "collection": "manuals",
        "collections": ["manuals"],
    }

    assert _authoritative_filters_for_collection(
        bounded_profile,
        "manuals",
        {"document_id": ["doc-1"], "language": "fr"},
    ) == {"document_id": ["doc-1"], "language": "fr"}
    assert _authoritative_filters_for_collection(
        bounded_profile,
        "manuals",
        {"document_id": ["doc-1", "doc-1"]},
    ) == {"document_id": ["doc-1"]}
    assert _authoritative_filters_for_collection(
        bounded_profile,
        "manuals",
        {},
    ) is None
    assert _authoritative_filters_for_collection(
        {**bounded_profile, "collections": ["manuals", "tickets"]},
        "manuals",
        {"document_id": ["doc-1"]},
    ) is None


def test_backend_evidence_is_revalidated_by_collection_document_pair():
    profile = {
        "authoritative_document_scope": True,
        "authoritative_document_refs": {
            "manuals": ["shared-id"],
            "tickets": ["ticket-only"],
        },
        "authoritative_document_refs_provided": True,
        "retrieval_filters": {"document_id": ["shared-id", "ticket-only"]},
    }

    chunks, scores, metadatas, dropped = _enforce_authoritative_document_evidence(
        ["manual", "collision", "ticket", "missing metadata"],
        [1.0, 0.9, 0.8, 0.7],
        [
            {"collection_slug": "manuals", "document_id": "shared-id"},
            {"collection_slug": "tickets", "document_id": "shared-id"},
            {"collection_slug": "tickets", "document_id": "ticket-only"},
            {},
        ],
        profile=profile,
    )

    assert chunks == ["manual", "ticket"]
    assert scores == [1.0, 0.8]
    assert [item["document_id"] for item in metadatas] == ["shared-id", "ticket-only"]
    assert dropped == 2

    assert _enforce_authoritative_document_evidence(
        ["contradictory lane"],
        [1.0],
        [{"collection": "tickets", "document_id": "ticket-only"}],
        profile=profile,
        collection="manuals",
    )[0] == []


@pytest.mark.asyncio
async def test_single_collection_runtime_drops_backend_filter_bypass_before_context(
    monkeypatch,
):
    profile = {
        "query": "pump",
        "rag_mode": "naive",
        "retrieval_profile": "oracle_fast",
        "retrieval_profile_contract": {},
        "top_k": 5,
        "candidate_pool_k": 20,
        "synthesis_k": 10,
        "source_display_k": 5,
        "collection": "manuals",
        "collections": ["manuals"],
        "knowledge_scope": "selected",
        "scope_label": "Selected documents",
        "vector_db": "qdrant",
        "workspace_id": "workspace-1",
        "workspace_slug": "workspace",
        "latency_profile": "fast",
        "deep_retrieval": False,
        "deadline_seconds": 2.0,
        "latency_budget": {"allow_cross_encoder": False},
        "authoritative_document_scope": True,
        "authoritative_document_refs": {"manuals": ["doc-1"]},
        "authoritative_document_refs_provided": True,
        "retrieval_filters": {"document_id": ["doc-1"]},
    }

    async def _resolve(*_args, **_kwargs):
        return False, "dense", "test"

    async def _retrieve(*_args, **_kwargs):
        return SimpleNamespace(
            chunks=["selected", "outside", "missing metadata"],
            scores=[0.9, 0.8, 0.7],
            metadatas=[
                {"document_id": "doc-1", "collection_slug": "manuals"},
                {"document_id": "doc-2", "collection_slug": "manuals"},
                {},
            ],
            pipeline="naive",
            label="vector_only",
            reason="test",
            detail="test",
            diagnostics={},
        )

    monkeypatch.setattr(rag_context, "get_retrieval_profile", lambda _request: dict(profile))
    monkeypatch.setattr(rag_context, "_effective_guides_for_profile", lambda _profile: [])
    monkeypatch.setattr(rag_context, "_native_qdrant_sparse_hybrid_available", lambda: True)
    monkeypatch.setattr(rag_context, "resolve_retrieval_mode", _resolve)
    monkeypatch.setattr(rag_context, "retrieve_for_mode", _retrieve)
    monkeypatch.setattr(rag_context, "_retrieval_context_cache_key", lambda **_kwargs: None)

    result = await rag_context._retrieve_rag_context(
        {
            "authoritative_collections": ["manuals"],
            "authoritative_document_scope": True,
        },
        doc_svc=object(),
    )

    assert result["chunks"] == ["selected"]
    assert result["metrics"]["authoritative_document_evidence_dropped"] == 2


def test_faiss_and_chroma_translate_document_id_allowlists_without_widening():
    filters = {"document_id": ["doc-1", "doc-2"], "language": "fr"}

    assert _metadata_matches_filters(
        {"document_id": "doc-2", "language": "fr"},
        filters,
    )
    assert not _metadata_matches_filters(
        {"document_id": "outside", "language": "fr"},
        filters,
    )
    assert not _metadata_matches_filters({"document_id": "doc-1"}, {"document_id": []})
    assert _filters_to_chroma_where(filters) == {
        "$and": [
            {"document_id": {"$in": ["doc-1", "doc-2"]}},
            {"language": "fr"},
        ]
    }


def test_retrieval_cache_key_separates_membranes_and_expected_projects():
    metrics = {"retrieval_scope": {"corpus_version": "corpus-v1"}}
    profile = {
        "workspace_id": "workspace-1",
        "workspace_slug": "workspace",
        "collection": "manuals",
        "collections": ["manuals"],
        "_membrane_spec": {
            "version": 2,
            "inbound": {"reference_type_filters": ["manual"]},
        },
        "_membrane_expected_project": "PROJECT-A",
    }

    def _key(
        overrides: dict,
        retrieval_policy: rag_context.RetrievalPolicy | None = None,
    ) -> str | None:
        return rag_context._retrieval_context_cache_key(
            profile={**profile, **overrides},
            query="pump",
            retrieval_filters={},
            metrics=metrics,
            guides=[],
            retrieval_policy=retrieval_policy,
        )

    base = _key({})
    assert base is not None
    assert base != _key({"_membrane_expected_project": "PROJECT-B"})
    assert base != _key(
        {
            "_membrane_spec": {
                "version": 2,
                "inbound": {"reference_type_filters": ["ticket"]},
            }
        }
    )
    assert base != _key(
        {},
        rag_context.RetrievalPolicy(
            require_project_code_match=True,
            cross_project_log_only=False,
        ),
    )


def test_summary_artifact_uses_the_authoritative_collection_document_pair(monkeypatch):
    captured: dict = {}

    class _Query:
        def filter(self, *_args):
            return self

        def first(self):
            return object()

    class _Db:
        def query(self, *_args):
            return _Query()

        def close(self):
            return None

    def _load(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "records": []}

    monkeypatch.setattr(rag_context, "SessionLocal", _Db)
    monkeypatch.setattr(rag_context, "load_summary_index_records", _load)

    result = rag_context._summary_artifact_for_profile(
        {
            "workspace_id": "workspace-1",
            "collection": "manuals",
            "collections": ["manuals"],
            "authoritative_document_scope": True,
            "authoritative_document_refs": {"manuals": ["doc-1"]},
            "authoritative_document_refs_provided": True,
            "retrieval_filters": {
                "document_id": ["doc-1", "attacker-doc"],
                "language": "fr",
            },
        },
        metrics={
            "retrieval_plan": {"layers": {"summaries": {"enabled": True}}},
            "retrieval_scope": {"filters": {"document_id": ["attacker-doc"]}},
        },
        query="pump",
    )

    assert result == {"status": "ready", "records": []}
    assert captured["filters"] == {"document_id": ["doc-1"], "language": "fr"}


@pytest.mark.asyncio
async def test_planner_never_reexpands_collections_removed_by_membrane(monkeypatch):
    profile = {
        "query": "pump",
        "rag_mode": "naive",
        "retrieval_profile": "classic",
        "retrieval_profile_contract": {},
        "top_k": 5,
        "candidate_pool_k": 20,
        "synthesis_k": 10,
        "source_display_k": 5,
        "collection": "allowed-a",
        "collections": ["allowed-a", "allowed-b"],
        "knowledge_scope": "selected",
        "scope_label": "Selected documents",
        "vector_db": "qdrant",
        "workspace_id": "workspace-1",
        "workspace_slug": "workspace",
        "latency_profile": "fast",
        "deep_retrieval": False,
        "deadline_seconds": 2.0,
        "latency_budget": {"allow_cross_encoder": False},
        "authoritative_document_scope": True,
        "authoritative_document_refs": {
            "allowed-a": ["doc-a"],
            "allowed-b": ["doc-b"],
        },
        "authoritative_document_refs_provided": True,
        "retrieval_filters": {"document_id": ["doc-a", "doc-b"]},
    }
    plan = CorpusPlan(
        intent="search",
        dense=True,
        source_count=1,
        chunk_count=1,
        latency_profile="fast",
        deadline_seconds=2.0,
        top_k=5,
        candidate_pool_k=20,
        synthesis_k=10,
        source_display_k=5,
        retrieval_scope={"collections": ["forbidden"]},
        filters={"document_id": ["planner-doc"]},
    )
    captured: dict = {}

    class _PlannerDb:
        def close(self):
            return None

    async def _multi(_request, **kwargs):
        captured["collections"] = list(kwargs["profile"]["collections"])
        return {"chunks": [], "metrics": kwargs["metrics"]}

    monkeypatch.setattr(rag_context, "get_retrieval_profile", lambda _request: dict(profile))
    monkeypatch.setattr(rag_context, "_effective_guides_for_profile", lambda _profile: [])
    monkeypatch.setattr(rag_context, "_native_qdrant_sparse_hybrid_available", lambda: False)
    monkeypatch.setattr(rag_context, "SessionLocal", _PlannerDb)
    monkeypatch.setattr(rag_context, "plan_corpus", lambda **_kwargs: plan)
    monkeypatch.setattr(rag_context, "_retrieval_context_cache_key", lambda **_kwargs: None)
    monkeypatch.setattr(rag_context, "_retrieve_multi_collection_context", _multi)

    await rag_context._retrieve_rag_context(
        {
            "authoritative_collections": ["allowed-a", "forbidden", "allowed-b"],
            "authoritative_document_scope": True,
        }
    )

    assert captured["collections"] == ["allowed-a", "allowed-b"]


@pytest.mark.asyncio
async def test_multi_hop_propagates_authoritative_scope_to_every_search(monkeypatch):
    calls: list[dict] = []

    async def _search(payload, _ctx):
        calls.append(payload)
        return {"results": [], "raw_chunks_retrieved": 0, "collections_touched": []}

    monkeypatch.setattr(wrappers, "_semantic_search_v1", _search)
    scope = {
        "retrieval_filters": {"document_id": ["doc-1", "doc-2"]},
        "authoritative_collections": ["manuals", "tickets"],
        "authoritative_document_scope": True,
        "authoritative_document_refs": {
            "manuals": ["doc-1"],
            "tickets": ["doc-2"],
        },
        "source_policy": {
            "membrane_spec": {
                "version": 2,
                "inbound": {"collection_allowlist": ["manuals", "tickets"]},
            }
        },
    }

    await wrappers._multi_hop_retrieve_v1(
        {"query": "pump", "sub_queries": ["motor", "valve"], **scope},
        {},
    )

    assert len(calls) == 3
    assert all(all(call.get(key) == value for key, value in scope.items()) for call in calls)


@pytest.mark.asyncio
async def test_hard_document_scope_skips_unscoped_auxiliary_lanes(monkeypatch):
    profile = {
        "query": "inventory of selected manuals",
        "rag_mode": "naive",
        "retrieval_profile": "oracle_fast",
        "retrieval_profile_contract": {},
        "top_k": 5,
        "candidate_pool_k": 20,
        "synthesis_k": 10,
        "source_display_k": 5,
        "collection": "manuals",
        "collections": ["manuals", "tickets"],
        "knowledge_scope": "selected",
        "scope_label": "Selected documents",
        "vector_db": "qdrant",
        "workspace_id": "workspace-1",
        "workspace_slug": "workspace",
        "latency_profile": "fast",
        "deep_retrieval": False,
        "deadline_seconds": 2.0,
        "latency_budget": {"allow_cross_encoder": False},
        "authoritative_document_scope": True,
        "authoritative_document_refs": {
            "manuals": ["doc-1"],
            "tickets": ["doc-2"],
        },
        "retrieval_filters": {"document_id": ["doc-1", "doc-2"]},
    }
    captured: dict = {}

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("an unscoped auxiliary retrieval lane was invoked")

    async def _multi(_request, **kwargs):
        captured.update(kwargs)
        return {"chunks": [], "metrics": kwargs["metrics"]}

    monkeypatch.setattr(rag_context, "get_retrieval_profile", lambda _request: dict(profile))
    monkeypatch.setattr(rag_context, "_effective_guides_for_profile", lambda _profile: [])
    monkeypatch.setattr(rag_context, "_native_qdrant_sparse_hybrid_available", lambda: True)
    monkeypatch.setattr(rag_context, "_table_analysis_for_profile", _must_not_run)
    monkeypatch.setattr(rag_context, "_document_analysis_for_profile", _must_not_run)
    monkeypatch.setattr(rag_context, "_should_build_project_inventory", _must_not_run)
    monkeypatch.setattr(rag_context, "is_collection_inventory_query", _must_not_run)
    monkeypatch.setattr(rag_context, "_retrieval_context_cache_key", lambda **_kwargs: None)
    monkeypatch.setattr(rag_context, "_retrieve_multi_collection_context", _multi)

    result = await rag_context._retrieve_rag_context(
        {
            "authoritative_collections": ["manuals", "tickets"],
            "authoritative_document_scope": True,
        }
    )

    assert result["chunks"] == []
    assert captured["table_analysis"] is None
    assert captured["document_analysis"] is None


def test_authoritative_document_scope_disables_unscoped_recall_floor():
    profile = {
        "authoritative_document_scope": True,
        "_corpus_plan_recall_floor_collections": ["manuals"],
    }

    assert not _recall_floor_active(
        profile,
        "manuals",
        {"document_filename": ["manual.pdf"]},
    )
