from __future__ import annotations

import asyncio

import pytest

from app.models.knowledge_collection import WorkerJob
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, create_worker_job
from app.services.knowledge_collections import serialize_job
from app.services.worker_deep_retrieval import (
    _compact_deep_retrieval_sources,
    _extractive_deep_answer,
    _run_deep_retrieval_async,
    _summarize_deep_retrieval_context,
)


def test_summarize_deep_retrieval_context_compacts_sources_and_metrics():
    summary = _summarize_deep_retrieval_context(
        {
            "chunks": ["a", "b", "c"],
            "scores": [0.98765, 0.75, 0.5],
            "pipeline": "chah_backend",
            "collection": "documents",
            "metadatas": [
                {"document_title": "Manual A"},
                {"document_filename": "Manual B.pdf"},
                {"document_title": "Manual A"},
            ],
            "metrics": {
                "duration_ms": 1234,
                "dense_policy": "deep_hierarchical_dense",
                "scope_confidence": 0.8,
                "retrieval_plan": {"profile": "deep", "layers": {"dense_qdrant": {"enabled": True}}},
            },
        }
    )

    assert summary["chunks_retrieved"] == 3
    assert summary["sources_returned"] == 2
    assert summary["top_score"] == 0.9877
    assert summary["pipeline"] == "chah_backend"
    assert summary["collection"] == "documents"
    assert summary["dense_policy"] == "deep_hierarchical_dense"
    assert summary["retrieval_plan"]["profile"] == "deep"
    assert summary["scope_confidence"] == 0.8
    assert summary["duration_ms"] == 1234
    assert summary["top_sources"] == [
        {"label": "Manual A", "chunks": 2},
        {"label": "Manual B.pdf", "chunks": 1},
    ]
    assert summary["sources_preview_count"] == 3


def test_compact_deep_retrieval_sources_limits_payload_without_vectors():
    preview = _compact_deep_retrieval_sources(
        {
            "collection": "documents",
            "chunks": ["Long   passage " * 200],
            "scores": [0.87654],
            "metadatas": [
                {
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "document_title": "Manual A",
                    "document_filename": "manual.html",
                    "collection": "documents",
                    "source_kind": "markup",
                    "embedding": [1, 2, 3],
                }
            ],
        }
    )

    assert preview[0]["id"] == "chunk-1"
    assert preview[0]["document_id"] == "doc-1"
    assert preview[0]["score"] == 0.8765
    assert len(preview[0]["snippet"]) <= 1200
    assert "embedding" not in preview[0]["metadata"]


def test_extractive_deep_answer_provides_readable_fallback():
    answer = _extractive_deep_answer(
        "Comment nettoyer une pompe ?",
        [
            {
                "title": "Maintenance manual.pdf",
                "snippet": "Nettoyer le filtre, verifier les joints, puis remonter les composants.",
            }
        ],
        warning="llm_unavailable",
    )

    assert "Maintenance manual.pdf" in answer
    assert "Nettoyer le filtre" in answer
    assert "llm_unavailable" in answer


def test_serialize_deep_retrieval_job_omits_heavy_context_by_default():
    job = WorkerJob(
        id="job-deep",
        workspace_id="ws",
        collection_id="col",
        kind="rag_deep_retrieval",
        status="completed",
        progress=100,
        result={
            "stage": "deep_completed",
            "answer": "Refined answer",
            "answer_status": "llm_synthesized",
            "summary": {"chunks_retrieved": 2},
            "sources_preview": [{"id": "chunk-1"}],
            "retrieval_context": {"chunks": ["large", "payload"]},
        },
    )

    compact = serialize_job(job)
    detailed = serialize_job(job, include_retrieval_context=True)

    assert compact["result"]["summary"] == {"chunks_retrieved": 2}
    assert compact["result"]["answer"] == "Refined answer"
    assert compact["result"]["sources_preview"] == [{"id": "chunk-1"}]
    assert compact["result"]["retrieval_context_omitted"] is True
    assert "retrieval_context" not in compact["result"]
    assert detailed["result"]["retrieval_context"]["chunks"] == ["large", "payload"]


@pytest.mark.asyncio
async def test_deep_retrieval_worker_preserves_initial_job_metadata(db_session, monkeypatch):
    async def fake_retrieve(payload):
        assert payload["latency_profile"] == "deep"
        assert payload["deep_retrieval"] is True
        return {
            "chunks": ["deep context"],
            "scores": [0.8],
            "metadatas": [{"document_filename": "manual.html"}],
            "pipeline": "chah_backend",
            "collection": "documents",
            "metrics": {"duration_ms": 42, "dense_policy": "deep_hierarchical_dense"},
        }

    async def fake_llm_answer(_payload, _prompt):
        return {"answer": "Reponse approfondie fondee sur deep context.", "provider": "test", "model": "test-model"}

    monkeypatch.setattr("app.services.worker_deep_retrieval.retrieve_rag_context", fake_retrieve)
    monkeypatch.setattr("app.services.worker_deep_retrieval._llm_deep_answer", fake_llm_answer)
    workspace = Workspace(id="ws-deep-worker", name="Deep Worker", slug="deep-worker")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="documents")
    job = create_worker_job(
        db_session,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="rag_deep_retrieval",
    )
    job.result = {
        "stage": "queued",
        "trigger": "auto_fast_refinement",
        "dense_policy": "fast_scoped_dense_auto",
        "scope_confidence": 0.2,
        "fallback_reason": "retrieval_deadline_exceeded",
        "request": {"query": "Analyse SPL", "latency_profile": "fast"},
    }
    db_session.commit()

    result = await _run_deep_retrieval_async(job.id)

    db_session.expire_all()
    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert refreshed.status == "completed"
    assert result["trigger"] == "auto_fast_refinement"
    assert result["dense_policy"] == "fast_scoped_dense_auto"
    assert result["scope_confidence"] == 0.2
    assert result["fallback_reason"] == "retrieval_deadline_exceeded"
    assert result["request"]["latency_profile"] == "deep"
    assert result["summary"]["chunks_retrieved"] == 1
    assert result["answer"] == "Reponse approfondie fondee sur deep context."
    assert result["answer_status"] == "llm_synthesized"
    assert result["answer_model"] == "test-model"
    assert result["sources_preview"][0]["filename"] == "manual.html"
    assert refreshed.result["trigger"] == "auto_fast_refinement"


@pytest.mark.asyncio
async def test_deep_retrieval_timeout_completes_with_partial_result(db_session, monkeypatch):
    async def slow_retrieve(_payload):
        await asyncio.sleep(0.05)
        return {"chunks": ["too late"]}

    monkeypatch.setattr("app.services.worker_deep_retrieval.retrieve_rag_context", slow_retrieve)
    monkeypatch.setattr("app.services.worker_deep_retrieval.settings.rag_deep_retrieval_deadline_seconds", 0.01)
    workspace = Workspace(id="ws-deep-timeout", name="Deep Timeout", slug="deep-timeout")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="documents")
    job = create_worker_job(
        db_session,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="rag_deep_retrieval",
    )
    job.result = {
        "stage": "queued",
        "trigger": "auto_fast_refinement",
        "partial_result": {
            "answer_preview": "fast answer",
            "sources_preview": [{"id": "source-1"}],
            "retrieval_summary": {
                "chunks_retrieved": 0,
                "dense_policy": "fast_scoped_dense_auto",
                "scope_confidence": 0.2,
            },
        },
        "request": {"query": "Analyse SPL", "latency_profile": "fast"},
    }
    db_session.commit()

    result = await _run_deep_retrieval_async(job.id)

    db_session.expire_all()
    refreshed = db_session.query(WorkerJob).filter(WorkerJob.id == job.id).one()
    assert refreshed.status == "completed"
    assert refreshed.progress == 100
    assert refreshed.error is None
    assert result["stage"] == "deep_timeout"
    assert result["status"] == "completed_partial"
    assert result["retrieval_context_available"] is False
    assert result["summary"]["partial"] is True
    assert result["summary"]["fallback_reason"] == "deep_retrieval_deadline_exceeded"
    assert result["summary"]["dense_policy"] == "fast_scoped_dense_auto"
    assert result["sources_preview"] == [{"id": "source-1"}]
    assert result["answer"] == "fast answer"
    assert result["answer_status"] == "partial_fast_answer"
