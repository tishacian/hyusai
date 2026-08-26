from __future__ import annotations

import pytest

from app.models.workspace import Workspace
from app.models.workspace_map import (
    WorkspaceMap,
    WorkspaceMapScore,
    WorkspaceMapSignal,
    WorkspaceMapZone,
)
from app.services.skills_registry import wrappers
from app.services.skills_registry.seed import SEED_SKILLS
from app.services.workspace_maps import OCTOCITY_MAP_SLUG, SENTINEL_MAP_SLUG


@pytest.mark.asyncio
async def test_semantic_search_wrapper_uses_planned_rag_context(monkeypatch):
    seen: dict = {}

    async def fake_retrieve_rag_context(request):
        seen.update(request)
        return {
            "chunks": ["planned evidence"],
            "scores": [0.91],
            "metadatas": [{"document_filename": "manual.pdf"}],
            "pipeline": "hybrid",
            "label": "hybrid_rrf",
            "reason": "planned retrieval",
            "detail": "bounded by planner",
            "metrics": {
                "retrieval_scope": {"filters": {"project_code": "ACJ100"}},
                "scope_confidence": 0.82,
                "scope_reason": "Project code inferred",
                "dense_policy": "fast_scoped_dense",
                "fallback_reason": None,
                "latency_budget": {"profile": "balanced", "candidate_pool_k": 80},
            },
        }

    monkeypatch.setattr(
        "app.services.rag.context.retrieve_rag_context",
        fake_retrieve_rag_context,
    )

    result = await wrappers._semantic_search_v1(
        {
            "query": "cherche la procedure ACJ100",
            "top_k": 12,
            "candidate_pool_k": 20,
            "source_display_k": 4,
            "mode": "chah",
            "deep_retrieval": True,
            "collection": "andritz-notices-techniques-spl-pilot",
            "retrieval_filters": {"project_code": "ACJ100"},
        },
        {
            "workspace_id": "ws-1",
            "workspace_slug": "andritz",
            "latency_profile": "balanced",
        },
    )

    assert seen["query"] == "cherche la procedure ACJ100"
    assert seen["workspace_id"] == "ws-1"
    assert seen["workspace_slug"] == "andritz"
    assert seen["context_collection"] == "andritz-notices-techniques-spl-pilot"
    assert seen["rag_pipeline_mode"] == "chah"
    assert seen["latency_profile"] == "deep"
    assert seen["candidate_pool_k"] == 20
    assert seen["source_display_k"] == 4
    assert seen["deep_retrieval"] is True
    assert seen["latency_budget"]["profile"] == "deep"
    assert seen["retrieval_filters"] == {"project_code": "ACJ100"}
    assert result["results"] == [
        {
            "content": "planned evidence",
            "score": 0.91,
            "metadata": {"document_filename": "manual.pdf"},
        }
    ]
    assert result["retrieval_scope"] == {"filters": {"project_code": "ACJ100"}}
    assert result["scope_confidence"] == 0.82
    assert result["dense_policy"] == "fast_scoped_dense"
    assert result["latency_budget"] == {"profile": "balanced", "candidate_pool_k": 80}


def test_seed_rag_skills_expose_retrieval_policy_contract():
    by_slug = {entry["slug"]: entry for entry in SEED_SKILLS}
    expected_slugs = {
        "llm_rag_answer_v1",
        "semantic_search_v1",
        "chain_naive_v1",
        "chain_hybrid_v1",
        "chain_mixed_hah_v1",
    }
    expected_properties = {
        "top_k",
        "candidate_pool_k",
        "synthesis_k",
        "source_display_k",
        "rag_pipeline_mode",
        "latency_profile",
        "retrieval_profile",
        "deep_retrieval",
        "knowledge_scope",
        "collection",
        "collection_name",
        "context_collection",
        "retrieval_filters",
    }

    for slug in expected_slugs:
        properties = by_slug[slug]["input_schema"]["properties"]
        assert expected_properties <= set(properties)

    assert by_slug["semantic_search_v1"]["execution"]["timeout_ms"] == 8_000
    assert "sparse+dense" in by_slug["semantic_search_v1"]["description"]


@pytest.mark.asyncio
async def test_translation_suite_skills_are_cataloged_and_stubbed():
    translation_slugs = {
        "translation_archive_ingest_v1",
        "translation_memory_retrieve_v1",
        "translation_label_index_resolve_v1",
        "translation_pivot_normalize_v1",
        "translation_fanout_v1",
        "translation_j2450_qa_v1",
        "translation_post_guard_v1",
        "translation_cdt_gate_v1",
        "translation_package_delivery_v1",
    }
    by_slug = {entry["slug"]: entry for entry in SEED_SKILLS}

    assert translation_slugs <= set(by_slug)
    assert by_slug["translation_j2450_qa_v1"]["certification_level"] == "enterprise"
    assert by_slug["translation_archive_ingest_v1"]["input_schema"]["required"] == [
        "archive_ref",
        "manifest_sha256",
    ]
    assert {slug: wrappers.runtime_status(slug) for slug in translation_slugs} == {
        slug: "stub" for slug in translation_slugs
    }

    result = await wrappers.resolve("translation_j2450_qa_v1")(
        {"agent_identity": "agent.translation.qa_supervisor", "expected_verdict": "ACCEPT_4D"},
        {"workspace_id": "ws-pmi", "skill_slug": "translation_j2450_qa_v1"},
    )
    assert result["status"] == "simulated"
    assert result["agent_identity"] == "agent.translation.qa_supervisor"
    assert result["sovereignty"]["external_llm_egress"] is False


@pytest.mark.asyncio
async def test_semantic_search_wrapper_defaults_to_balanced_latency(monkeypatch):
    # Recall-parity fix (f31204da7): the wrapper deliberately defaults an
    # unpinned latency_profile to "balanced" (never hardcode "fast") so factual
    # lookups get a real candidate pool, matching the classic pipeline.
    seen: dict = {}

    async def fake_retrieve_rag_context(request):
        seen.update(request)
        return {
            "chunks": [],
            "scores": [],
            "metadatas": [],
            "pipeline": "none",
            "label": "none",
            "reason": "empty",
            "detail": "empty",
            "metrics": {},
        }

    monkeypatch.setattr(
        "app.services.rag.context.retrieve_rag_context",
        fake_retrieve_rag_context,
    )

    await wrappers._semantic_search_v1({"query": "de quelles donnees disposes-tu ?"}, {})

    assert seen["latency_profile"] == "balanced"
    assert seen["rag_pipeline_mode"] == "auto"


@pytest.mark.asyncio
async def test_semantic_search_bound_collection_falls_back_to_workspace(monkeypatch):
    """Phase 2 grounding safety: when an authoritative bound collection returns
    ZERO context, the wrapper retries at workspace scope (drops context_collection)
    rather than surfacing a silently empty retrieval (lesson 2026-06-26)."""
    requests: list[dict] = []

    async def fake_retrieve_rag_context(request):
        requests.append(dict(request))
        # First attempt (scoped to the bound collection) returns nothing;
        # the workspace-scope retry (no context_collection) finds the chunk.
        if request.get("context_collection"):
            return {"chunks": [], "scores": [], "metadatas": [], "metrics": {}}
        return {
            "chunks": ["workspace evidence"],
            "scores": [0.77],
            "metadatas": [{"document_filename": "fallback.pdf"}],
            "metrics": {"raw_chunks_retrieved": 1},
        }

    monkeypatch.setattr(
        "app.services.rag.context.retrieve_rag_context",
        fake_retrieve_rag_context,
    )

    result = await wrappers._semantic_search_v1(
        {"query": "largeur AKK200", "collection": "andritz-notices-techniques-spl-pilot"},
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )

    assert len(requests) == 2, "empty bound-collection retrieval did not fall back"
    assert requests[0].get("context_collection") == "andritz-notices-techniques-spl-pilot"
    assert "context_collection" not in requests[1], "fallback must drop the collection scope"
    assert result["results"] == [
        {"content": "workspace evidence", "score": 0.77, "metadata": {"document_filename": "fallback.pdf"}}
    ]


@pytest.mark.asyncio
async def test_semantic_search_bound_collection_no_fallback_when_grounded(monkeypatch):
    """The fallback is a safety net: a bound collection that DOES ground stays
    scoped (single retrieval, no workspace widening)."""
    requests: list[dict] = []

    async def fake_retrieve_rag_context(request):
        requests.append(dict(request))
        return {
            "chunks": ["scoped evidence"],
            "scores": [0.9],
            "metadatas": [{"document_filename": "scoped.pdf"}],
            "metrics": {"raw_chunks_retrieved": 1},
        }

    monkeypatch.setattr(
        "app.services.rag.context.retrieve_rag_context",
        fake_retrieve_rag_context,
    )

    result = await wrappers._semantic_search_v1(
        {"query": "largeur AKK200", "collection": "andritz-notices-techniques-spl-pilot"},
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )

    assert len(requests) == 1, "a grounded bound collection must not trigger a fallback"
    assert requests[0].get("context_collection") == "andritz-notices-techniques-spl-pilot"
    assert result["results"][0]["content"] == "scoped evidence"


@pytest.mark.asyncio
async def test_llm_rag_answer_wrapper_forwards_scope_and_budget(monkeypatch):
    captured: dict = {}

    class FakeOrchestrator:
        async def process_request(self, request):
            captured.update(request)
            yield {
                "chunk_type": "retrieval",
                "phase": "completed",
                "details": {
                    "dense_policy": "fast_scoped_dense",
                    "fallback_reason": "sparse_unavailable",
                    "retrieval_scope": {"filters": {"project_code": "ACJ100"}},
                    "scope_confidence": 0.87,
                    "latency_budget": {"profile": "balanced", "candidate_pool_k": 80},
                },
                "rag_context": {"chunks": ["evidence"], "scores": [0.8], "metadatas": []},
                "is_final": False,
            }
            yield {"chunk_type": "text", "content": "answer", "is_final": False}
            yield {"chunk_type": "text", "content": "", "is_final": True}

    monkeypatch.setattr(
        "app.services.rag.rag_service._get_orchestrator",
        lambda: FakeOrchestrator(),
    )

    result = await wrappers._llm_rag_answer_v1(
        {
            "query": "Explique la procedure ACJ100",
            "rag_pipeline_mode": "chah",
            "top_k": 99,
            "candidate_pool_k": 999,
            "latency_profile": "balanced",
            "retrieval_profile": "chat",
            "collection": "andritz-notices-techniques-spl-pilot",
            "retrieval_filters": {"project_code": "ACJ100"},
        },
        {
            "workspace_id": "ws-1",
            "workspace_slug": "andritz",
        },
    )

    assert result["answer"] == "answer"
    assert captured["workspace_id"] == "ws-1"
    assert captured["workspace_slug"] == "andritz"
    assert captured["rag_pipeline_mode"] == "chah"
    assert captured["top_k"] == 12
    assert captured["candidate_pool_k"] == 80
    assert captured["latency_profile"] == "balanced"
    assert captured["retrieval_profile"] == "chat"
    assert captured["latency_budget"]["profile"] == "balanced"
    assert captured["latency_budget"]["candidate_pool_k"] == 80
    assert captured["context_collection"] == "andritz-notices-techniques-spl-pilot"
    assert captured["retrieval_filters"] == {"project_code": "ACJ100"}
    assert result["meta"]["dense_policy"] == "fast_scoped_dense"
    assert result["meta"]["fallback_reason"] == "sparse_unavailable"
    assert result["meta"]["retrieval_scope"] == {"filters": {"project_code": "ACJ100"}}
    assert result["meta"]["latency_budget"] == {"profile": "balanced", "candidate_pool_k": 80}
    assert result["meta"]["rag_context"]["chunks"] == ["evidence"]


@pytest.mark.asyncio
async def test_chain_wrappers_forward_retrieval_policy_fields(monkeypatch):
    captured: dict = {}

    class FakeOrchestrator:
        async def process_request(self, request):
            captured.update(request)
            yield {"chunk_type": "text", "content": "chain answer", "is_final": True}

    monkeypatch.setattr(
        "app.services.rag.rag_service._get_orchestrator",
        lambda: FakeOrchestrator(),
    )

    result = await wrappers._chain_mixed_hah_v1(
        {
            "query": "Audit SPL",
            "top_k": 12,
            "candidate_pool_k": 80,
            "latency_profile": "deep",
            "deep_retrieval": True,
            "collection_name": "andritz-notices-techniques-spl-pilot",
            "retrieval_filters": {"source_kind": "markup"},
        },
        {"workspace_id": "ws-1", "workspace_slug": "andritz"},
    )

    assert result["answer"] == "chain answer"
    assert captured["rag_pipeline_mode"] == "chah"
    assert captured["top_k"] == 12
    assert captured["candidate_pool_k"] == 80
    assert captured["latency_profile"] == "deep"
    assert captured["deep_retrieval"] is True
    assert captured["context_collection"] == "andritz-notices-techniques-spl-pilot"
    assert captured["retrieval_filters"] == {"source_kind": "markup"}


@pytest.mark.asyncio
async def test_map_wrappers_default_to_each_workspaces_own_map(db_session, monkeypatch):
    monkeypatch.setattr("app.services.workspace_maps.fetch_vessels_in_bbox", lambda **_kwargs: [])
    sentinel = Workspace(
        id="workspace-wrapper-sentinel",
        slug="wrapper-sentinel",
        name="Wrapper Sentinel",
        mode="demo",
        settings={},
    )
    octocity = Workspace(
        id="workspace-wrapper-octocity",
        slug="octocity-mission-room",
        name="Wrapper Octocity",
        mode="demo",
        settings={"mission_room": {"profile": "octocity_institutional_v1"}},
    )
    db_session.add_all([sentinel, octocity])
    db_session.commit()

    for workspace, expected_slug in (
        (sentinel, SENTINEL_MAP_SLUG),
        (octocity, OCTOCITY_MAP_SLUG),
    ):
        context = {"db": db_session, "workspace_id": workspace.id}
        scored = await wrappers._map_zone_score_v1({}, context)
        commanded = await wrappers._map_command_apply_v1(
            {"intent": "reset_view"},
            context,
        )

        assert scored["job"]["input_ref"]["slug"] == expected_slug
        assert scored["result"]["map_id"] == commanded["map_id"]
        assert commanded["map_slug"] == expected_slug

    octocity_default = await wrappers._map_layer_read_v1(
        {},
        {"db": db_session, "workspace_id": octocity.id},
    )
    assert octocity_default["map_system"]["slug"] == OCTOCITY_MAP_SLUG

    operator_map = WorkspaceMap(
        id="wrapper-operator-map-id",
        workspace_id=octocity.id,
        slug="wrapper-operator-map",
        name="Wrapper operator map",
        description="A second map used to verify explicit wrapper bindings.",
        country="France",
        projection="wrapper_operator_v1",
        view_box="0 0 100 100",
        center={"x": 50, "y": 50},
        settings={"renderer_config": {"bounds": [[0.0, 42.0], [6.0, 50.0]]}},
    )
    operator_zone = WorkspaceMapZone(
        id="wrapper-operator-zone-id",
        map_id=operator_map.id,
        zone_key="wrapper-operator-zone",
        name="Wrapper operator zone",
        level=87,
        tone="critical",
        polygon="10,10 90,10 90,90 10,90",
        centroid={"x": 50, "y": 50},
        meta_data={
            "signals": ["Wrapper operator signal"],
            "recommendations": ["Wrapper operator recommendation"],
        },
        source_refs=["wrapper-operator-source"],
    )
    operator_score = WorkspaceMapScore(
        id="wrapper-operator-score-id",
        map_id=operator_map.id,
        zone_id=operator_zone.id,
        score=87,
        level_label="critical",
        drivers=["Wrapper operator signal"],
        recommendations=[{"title": "Wrapper explicit recommendation"}],
        recommended_windows=[],
    )
    db_session.add_all([operator_map, operator_zone, operator_score])
    db_session.commit()
    explicit_payload = {"map_slug": operator_map.slug}
    octocity_context = {"db": db_session, "workspace_id": octocity.id}

    explicit_layer = await wrappers._map_layer_read_v1(
        explicit_payload,
        octocity_context,
    )
    explicit_recommendations = await wrappers._map_recommendation_generate_v1(
        explicit_payload,
        octocity_context,
    )
    explicit_signal = await wrappers._map_signal_attach_v1(
        {
            **explicit_payload,
            "zone_key": operator_zone.zone_key,
            "title": "Explicit wrapper attachment",
        },
        octocity_context,
    )

    assert explicit_layer["map_system"]["id"] == operator_map.id
    assert {zone["id"] for zone in explicit_layer["zones"]} == {
        operator_zone.zone_key,
    }
    assert explicit_recommendations["recommendations"] == [
        {"title": "Wrapper explicit recommendation"},
    ]
    assert explicit_recommendations["score_summary"]["top_zone"]["id"] == (
        operator_zone.zone_key
    )
    assert explicit_signal["map_id"] == operator_map.id
    assert explicit_signal["map_slug"] == operator_map.slug
    attached = db_session.query(WorkspaceMapSignal).filter_by(
        id=explicit_signal["signal"]["id"]
    ).one()
    assert attached.map_id == operator_map.id

    default_signal = await wrappers._map_signal_attach_v1(
        {"zone_key": "zone-nord", "title": "Default Octocity attachment"},
        octocity_context,
    )
    assert default_signal["map_slug"] == OCTOCITY_MAP_SLUG


# ---------------------------------------------------------------------------
# `model` is a collided key on the wire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_llm_node_downstream_of_a_scoring_node_still_calls_a_model(monkeypatch):
    """The defect this pins took the Nawa demo's closing node down.

    ``ml_batch_score_v1`` answers with a block under ``model`` saying which
    version scored the parc. The DAG walker merges an upstream output flat into
    the next node's payload, and in overlay mode that beats the node's own
    config — so the LLM node that writes the French retention brief read a
    *dict* out of the key it takes its model name from and handed it to the
    provider, which replied "could not parse the JSON body of your request".
    The run failed at the last node with an error that pointed at the prompt.
    """

    calls: list[dict] = []

    class _Client:
        api_key = "sk-test"

        async def generate(self, **kwargs):
            calls.append(kwargs)
            return {"content": "Trois segments concentrent le risque.", "model": kwargs["model"]}

    monkeypatch.setattr(
        "app.services.model_clients.openai_client.OpenAIClient", lambda *a, **k: _Client()
    )

    # Verbatim shape of a `score_dataset` envelope, minus the fields this node
    # does not read.
    envelope = {
        "dataset_id": "ds-scored",
        "slug": "subscriber-base-scored",
        "model": {
            "model_id": "mdl-1",
            "slug": "churn-radar",
            "version": 3,
            "task": "classification",
        },
        "scored_rows": 4000,
    }

    result = await wrappers._azure_llm_v1(
        {**envelope, "prompt": "Summarise the segments at risk."}
    )

    assert calls, "the provider was never called"
    assert calls[0]["model"] == "gpt-4o-mini", (
        "the scoring node's model block was passed off as a model name"
    )
    assert isinstance(calls[0]["model"], str)
    assert result["completion"].startswith("Trois segments")


@pytest.mark.asyncio
async def test_a_configured_model_name_is_still_honoured(monkeypatch):
    """The guard drops objects, not choices: a named model still reaches the client."""

    calls: list[dict] = []

    class _Client:
        api_key = "sk-test"

        async def generate(self, **kwargs):
            calls.append(kwargs)
            return {"content": "ok", "model": kwargs["model"]}

    monkeypatch.setattr(
        "app.services.model_clients.openai_client.OpenAIClient", lambda *a, **k: _Client()
    )

    await wrappers._azure_llm_v1({"prompt": "x", "model": "  gpt-4.1-mini  "})

    assert calls[0]["model"] == "gpt-4.1-mini", "a named model was dropped or left padded"


def test_the_model_name_guard_falls_through_objects_to_the_next_candidate():
    """Stated once, because eight call sites depend on this single rule."""

    assert wrappers._model_name({"model_id": "mdl-1", "version": 3}, "gpt-4o-mini") == (
        "gpt-4o-mini"
    )
    assert wrappers._model_name(["gpt-4o-mini"], "llama3") == "llama3"
    assert wrappers._model_name(None, None) is None
    assert wrappers._model_name("", "  ", "qwen2.5") == "qwen2.5"
    # A provider-prefixed name is a name: the router splits it, not this guard.
    assert wrappers._model_name("openai:gpt-4o") == "openai:gpt-4o"
