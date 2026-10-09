from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection, create_worker_job
from app.services.rag import embedding_generation as generations


@pytest.fixture
def collection(db_session):
    workspace = Workspace(id="hf-rag-ws", slug="hf-rag", name="HF RAG")
    db_session.add(workspace)
    db_session.flush()
    row = create_collection(db_session, workspace=workspace, name="Manuals")
    row.status = "ready"
    row.chunk_count = 2
    row.embedding_artifact_id = "old-artifact"
    row.embedding_dimension = 3
    row.embedding_params = {"normalize_embeddings": True, "batch_size": 32}
    row.active_generation = "old-generation"
    db_session.commit()
    return row


@pytest.fixture
def registry(monkeypatch):
    # Isolate only the HF registry boundary: generation state is persisted in
    # the real SQLAlchemy database; vector writes and runtime are test doubles.
    state = {"denied": set(), "calls": []}

    def require_artifact(db, workspace_id, artifact_id, usage=None):
        state["calls"].append((workspace_id, artifact_id, usage))
        if artifact_id in state["denied"]:
            raise HTTPException(403, detail={"code": "HF_ARTIFACT_FORBIDDEN"})
        return SimpleNamespace(id=artifact_id, repo_id="test/" + artifact_id)

    monkeypatch.setattr("app.services.huggingface.registry.require_artifact", require_artifact)
    return state


class MemoryVectors:
    def __init__(self, payloads=None):
        self.payloads = payloads or []
        self.vectors = []
        self.cleared = False

    async def create_index(self, dimension):
        self.dimension = dimension

    async def get_count(self):
        return len(self.payloads)

    async def iter_payload_batches(self, batch_size=256):
        for offset in range(0, len(self.payloads), batch_size):
            yield self.payloads[offset : offset + batch_size]

    async def add_vectors(self, vectors, metadatas, ids):
        self.payloads.extend(metadatas)
        self.vectors.extend(vectors)

    async def search(self, query, top_k):
        return self.payloads[:top_k]

    async def clear_collection(self):
        self.cleared = True
        self.payloads.clear()


@pytest.fixture
def runtime(monkeypatch, collection):
    from app.services.huggingface import adapters
    from app.services.vector_db.factory import VectorDBFactory

    old = MemoryVectors(
        [{"chunk_id": "a", "content": "first"}, {"chunk_id": "b", "content": "second"}]
    )
    new = MemoryVectors()
    state = {"old": old, "new": new, "fail": False, "before_publish": None}

    class Embedder:
        def __init__(self, **kwargs):
            self.parameters = {"normalize_embeddings": True, "batch_size": 32}

        def get_dimension(self):
            # Same dimension intentionally does not imply the same space.
            return 3

        async def embed_batch(self, texts):
            if state["fail"]:
                raise RuntimeError("embedding worker unavailable")
            return np.ones((len(texts), 3))

        async def embed(self, text):
            if state["before_publish"]:
                state["before_publish"]()
            return np.ones(3)

        def close(self):
            state["closed"] = True

    monkeypatch.setattr(adapters, "ArtifactEmbedder", Embedder)
    monkeypatch.setattr(
        VectorDBFactory,
        "get_db",
        lambda name, **kwargs: old if name == collection.vector_collection_name else new,
    )
    monkeypatch.setattr(
        "app.services.rag.vector_store_config.resolve_vector_db_type", lambda settings: "qdrant"
    )
    return state


def test_success_switches_complete_model_index_pair(db_session, collection, registry, runtime):
    before = generations.binding_for(collection)
    job = generations.queue_embedding_reindex(
        db_session, collection=collection, artifact_id="new-artifact"
    )
    db_session.commit()
    db_session.refresh(collection)
    assert generations.binding_for(collection) == before
    assert collection.pending_generation

    def during_rebuild():
        db_session.refresh(collection)
        assert generations.binding_for(collection) == before

    runtime["before_publish"] = during_rebuild
    result = generations.run_embedding_reindex(job.id)
    db_session.refresh(collection)
    assert result["stage"] == "ready"
    assert collection.embedding_artifact_id == "new-artifact"
    assert collection.embedding_dimension == 3
    assert collection.vector_collection_name != before["vector_collection_name"]
    assert collection.active_generation != before["generation"]
    assert collection.pending_generation is None
    assert len(runtime["old"].payloads) == len(runtime["new"].payloads) == 2
    assert registry["calls"][-1] == (collection.workspace_id, "new-artifact", "embedding")


@pytest.mark.parametrize("failure", ["runtime", "revoke", "count", "probe"])
def test_failed_rebuild_preserves_old_pair(db_session, collection, registry, runtime, failure):
    before = generations.binding_for(collection)
    job = generations.queue_embedding_reindex(
        db_session, collection=collection, artifact_id="new-artifact"
    )
    db_session.commit()
    if failure == "runtime":
        runtime["fail"] = True
    elif failure == "revoke":
        runtime["before_publish"] = lambda: registry["denied"].add("new-artifact")
    elif failure == "count":
        runtime["old"].payloads.pop()
    else:

        async def empty_search(*args, **kwargs):
            return []

        runtime["new"].search = empty_search
    with pytest.raises((RuntimeError, HTTPException)):
        generations.run_embedding_reindex(job.id)
    db_session.refresh(collection)
    db_session.refresh(job)
    assert generations.binding_for(collection) == before
    assert collection.pending_generation is None
    assert job.status == "failed"
    assert runtime["old"].cleared is False
    assert runtime["closed"] is True


def test_pending_generation_excludes_ingest_and_other_rebuild(db_session, collection, registry):
    generations.queue_embedding_reindex(
        db_session, collection=collection, artifact_id="new-artifact"
    )
    db_session.commit()
    with pytest.raises(HTTPException) as denied:
        create_worker_job(
            db_session, workspace_id=collection.workspace_id, collection_id=collection.id
        )
    assert denied.value.status_code == 409
    with pytest.raises(HTTPException):
        generations.queue_embedding_reindex(
            db_session, collection=collection, artifact_id="second-artifact"
        )


def test_ingest_job_excludes_rebuild(db_session, collection, registry):
    create_worker_job(db_session, workspace_id=collection.workspace_id, collection_id=collection.id)
    db_session.commit()
    with pytest.raises(HTTPException) as denied:
        generations.queue_embedding_reindex(
            db_session, collection=collection, artifact_id="new-artifact"
        )
    assert denied.value.detail["code"] == "RAG_COLLECTION_JOB_ACTIVE"


def test_cache_preparation_failure_releases_reservation(db_session, collection, registry):
    job = generations.queue_embedding_reindex(
        db_session, collection=collection, artifact_id="new-artifact"
    )
    db_session.commit()
    generations.fail_embedding_preparation(job.id)
    db_session.refresh(collection)
    db_session.refresh(job)
    assert collection.pending_generation is None
    assert collection.embedding_artifact_id == "old-artifact"
    assert job.status == "failed"


def test_lost_publication_ack_never_clears_visible_generation(
    db_session, collection, registry, runtime, monkeypatch
):
    from app.models.knowledge_collection import WorkerJob

    job = generations.queue_embedding_reindex(
        db_session, collection=collection, artifact_id="new-artifact"
    )
    db_session.commit()
    session_factory = generations.SessionLocal

    def faulted_session():
        session = session_factory()
        real_commit = session.commit

        def commit():
            published = any(
                isinstance(row, WorkerJob) and row.status == "completed"
                for row in session.identity_map.values()
            )
            real_commit()
            if published:
                raise ConnectionError("commit acknowledgement lost")

        session.commit = commit
        return session

    monkeypatch.setattr(generations, "SessionLocal", faulted_session)
    result = generations.run_embedding_reindex(job.id)
    db_session.refresh(collection)
    assert result["stage"] == "ready"
    assert collection.embedding_artifact_id == "new-artifact"
    assert runtime["new"].cleared is False


def test_cancelled_running_build_cannot_publish(db_session, collection, registry, runtime):
    before = generations.binding_for(collection)
    job = generations.queue_embedding_reindex(
        db_session, collection=collection, artifact_id="new-artifact"
    )
    db_session.commit()

    def cancel_before_publication():
        generations.cancel_model_job(
            db_session,
            workspace_id=collection.workspace_id,
            collection_id=collection.id,
            job_id=job.id,
        )
        db_session.commit()

    runtime["before_publish"] = cancel_before_publication
    with pytest.raises(RuntimeError, match="RAG_GENERATION_CHANGED"):
        generations.run_embedding_reindex(job.id)
    db_session.refresh(collection)
    db_session.refresh(job)
    assert generations.binding_for(collection) == before
    assert collection.pending_generation is None
    assert job.status == "cancelled"
    assert runtime["new"].cleared is True


def test_request_snapshot_and_revocation_are_checked(db_session, collection, registry):
    binding = generations.resolve_binding(collection.slug, "hf-rag")
    assert binding == generations.binding_for(collection)
    registry["denied"].add("old-artifact")
    with pytest.raises(HTTPException):
        generations.authorize_binding(binding)


def test_context_cache_key_tracks_generation_and_denies_revoked_model(
    db_session, collection, registry, monkeypatch
):
    from app.core.config import settings
    from app.services.rag.context import _retrieval_context_cache_key

    monkeypatch.setattr(settings, "rag_context_cache_enabled", True)
    args = {
        "profile": {"workspace_slug": "hf-rag", "collection": collection.slug},
        "query": "cached",
        "retrieval_filters": {},
        "guides": [],
        "metrics": {"retrieval_scope": {"corpus_version": "unchanged-documents"}},
    }
    first = _retrieval_context_cache_key(**args)
    collection.active_generation = "replacement-generation"
    db_session.commit()
    second = _retrieval_context_cache_key(**args)
    assert first and second and first != second
    registry["denied"].add("old-artifact")
    assert _retrieval_context_cache_key(**args) is None
    assert (
        args["metrics"]["retrieval_context_cache_skipped_reason"]
        == "model_authorization_unavailable"
    )


@pytest.mark.asyncio
async def test_document_service_pairs_artifact_and_physical_index_and_rechecks_cached_access(
    db_session, collection, registry, runtime, monkeypatch
):
    from app.services.rag.document_service import DocumentService
    from app.services.vector_db.factory import VectorDBFactory

    names = []

    def vector_db(name, **kwargs):
        names.append(name)
        return runtime["old"]

    monkeypatch.setattr(VectorDBFactory, "get_db", vector_db)
    monkeypatch.setattr(
        "app.services.rag.document_service.Embedder",
        lambda **kwargs: pytest.fail("an imported index must never use the default embedding"),
    )
    service = DocumentService(
        collection_name=collection.slug,
        workspace_slug="hf-rag",
        use_reranker=False,
        use_hybrid=False,
    )
    assert names == [collection.vector_collection_name]
    service.cache.set(
        "cached query",
        1,
        [{"content": "cached"}],
        use_hybrid=False,
        namespace=service.cache_namespace,
    )
    registry["denied"].add("old-artifact")
    with pytest.raises(HTTPException):
        await service.search("cached query", top_k=1, use_hybrid=False)


@pytest.mark.asyncio
async def test_stale_writer_cannot_mutate_new_generation(db_session, collection, registry):
    class Writer:
        embedding_binding = generations.binding_for(collection)

        @generations.generation_write
        async def write(self):
            pytest.fail("stale index must not be written")

    collection.active_generation = "new-generation"
    db_session.commit()
    with pytest.raises(HTTPException) as denied:
        await Writer().write()
    assert denied.value.status_code == 409


@pytest.mark.parametrize("fail_probe", [False, True])
def test_reranker_activation_keeps_previous_until_probe_succeeds(
    db_session, collection, registry, monkeypatch, fail_probe
):
    from app.services.rag.reranker_artifacts import (
        queue_reranker_activation,
        run_reranker_activation,
    )

    collection.reranker_artifact_id = "old-reranker"
    db_session.commit()
    job = queue_reranker_activation(db_session, collection=collection, artifact_id="new-reranker")
    db_session.commit()

    class Reranker:
        def __init__(self, **kwargs):
            db_session.refresh(collection)
            assert collection.reranker_artifact_id == "old-reranker"
            if fail_probe:
                raise RuntimeError("incompatible ONNX output")

        def close(self):
            pass

    monkeypatch.setattr("app.services.huggingface.adapters.ArtifactReranker", Reranker)
    if fail_probe:
        with pytest.raises(RuntimeError):
            run_reranker_activation(job.id)
    else:
        run_reranker_activation(job.id)
    db_session.refresh(collection)
    db_session.refresh(job)
    assert collection.reranker_artifact_id == ("old-reranker" if fail_probe else "new-reranker")
    assert job.status == ("failed" if fail_probe else "completed")


def test_selected_reranker_failure_never_calls_builtin(
    db_session, collection, registry, monkeypatch
):
    from app.services.rag.reranker_artifacts import score_collection_passages

    collection.reranker_artifact_id = "selected-reranker"
    db_session.commit()

    def fail_selected(**kwargs):
        raise RuntimeError("selected model unavailable")

    monkeypatch.setattr("app.services.huggingface.adapters.ArtifactReranker", fail_selected)
    monkeypatch.setattr(
        "app.services.rag.cross_encoder_stage._score_passages",
        lambda *args, **kwargs: pytest.fail("implicit reranker fallback"),
    )
    with pytest.raises(RuntimeError, match="selected model unavailable"):
        score_collection_passages(
            "query",
            ["text"],
            [{}],
            workspace_slug="hf-rag",
            collection_ref=collection.slug,
            model_name="builtin",
            max_length=64,
        )


def test_multi_collection_reranker_provenance(db_session, collection, registry, monkeypatch):
    from app.services.rag.reranker_artifacts import score_collection_passages

    collection.reranker_artifact_id = "selected-reranker"
    db_session.commit()

    class Reranker:
        def __init__(self, **kwargs):
            assert kwargs["artifact_id"] == "selected-reranker"

        def score(self, query, texts):
            return [0.9] * len(texts)

        def close(self):
            pass

    monkeypatch.setattr("app.services.huggingface.adapters.ArtifactReranker", Reranker)
    monkeypatch.setattr(
        "app.services.rag.cross_encoder_stage._score_passages", lambda *args, **kwargs: [0.4]
    )
    scores, provenance = score_collection_passages(
        "query",
        ["selected", "default"],
        [{"collection": collection.slug}, {"collection": "legacy"}],
        workspace_slug="hf-rag",
        collection_ref=None,
        model_name="builtin",
        max_length=64,
    )
    assert scores == [0.9, 0.4]
    assert provenance == {collection.slug: "selected-reranker", "legacy": "builtin"}
