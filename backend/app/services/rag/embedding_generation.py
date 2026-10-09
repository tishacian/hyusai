"""Bind an embedding space to one immutable physical collection generation.

The collection row is the publication pointer. Rebuilds never mutate it until
every vector has been written and checked; request-scoped readers capture it
once so an in-flight request cannot combine two generations.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from functools import wraps
from typing import Any
from uuid import uuid4

import numpy as np
from fastapi import HTTPException

from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.models.workspace import Workspace


def binding_for(collection: KnowledgeCollection) -> dict[str, Any]:
    return {
        "collection_id": collection.id,
        "workspace_id": collection.workspace_id,
        "vector_collection_name": collection.vector_collection_name,
        "artifact_id": collection.embedding_artifact_id,
        "model_name": collection.embedding_model,
        "dimension": collection.embedding_dimension,
        "parameters": dict(collection.embedding_params or {}),
        "generation": collection.active_generation,
    }


def resolve_binding(collection_name: str, workspace_slug: str | None) -> dict | None:
    if not workspace_slug:
        return None
    with SessionLocal() as db:
        row = (
            db.query(KnowledgeCollection)
            .join(Workspace, Workspace.id == KnowledgeCollection.workspace_id)
            .filter(Workspace.slug == workspace_slug)
            .filter(
                (KnowledgeCollection.slug == collection_name)
                | (KnowledgeCollection.id == collection_name)
            )
            .first()
        )
        return binding_for(row) if row else None


def authorize_binding(binding: dict | None) -> None:
    if binding and binding.get("artifact_id"):
        from app.services.huggingface.registry import require_artifact

        with SessionLocal() as db:
            require_artifact(db, binding["workspace_id"], binding["artifact_id"], usage="embedding")


def authorized_cache_bindings(workspace_slug: str | None, collection_refs: list[str]) -> list[dict]:
    """Authorize high-level cached retrieval and bind it to model generations."""
    from app.services.huggingface.registry import require_artifact

    if not workspace_slug:
        return []
    with SessionLocal() as db:
        rows = (
            db.query(KnowledgeCollection)
            .join(Workspace, Workspace.id == KnowledgeCollection.workspace_id)
            .filter(
                Workspace.slug == workspace_slug,
                (KnowledgeCollection.slug.in_(collection_refs))
                | (KnowledgeCollection.id.in_(collection_refs)),
            )
            .order_by(KnowledgeCollection.id)
            .all()
        )
        tokens = []
        for row in rows:
            if row.embedding_artifact_id:
                require_artifact(db, row.workspace_id, row.embedding_artifact_id, usage="embedding")
            if row.reranker_artifact_id:
                require_artifact(db, row.workspace_id, row.reranker_artifact_id, usage="reranker")
            tokens.append({**binding_for(row), "reranker_artifact_id": row.reranker_artifact_id})
        return tokens


def generation_write(method):
    """Serialize vector mutations with rebuild reservation/publication.

    Hold a row lock for the external write, including across awaits. PostgreSQL
    enqueues a rebuild only after the write completes. A stale service cannot
    mutate a retired generation, and a pending rebuild freezes its source.
    """

    @wraps(method)
    async def guarded(self, *args, **kwargs):
        binding = getattr(self, "embedding_binding", None)
        if not binding:
            return await method(self, *args, **kwargs)
        with SessionLocal() as db:
            row = (
                db.query(KnowledgeCollection)
                .filter(
                    KnowledgeCollection.id == binding["collection_id"],
                    KnowledgeCollection.workspace_id == binding["workspace_id"],
                )
                .with_for_update(key_share=True)
                .first()
            )
            if not row or row.pending_generation or binding_for(row) != binding:
                raise HTTPException(409, detail={"code": "RAG_GENERATION_BUSY"})
            authorize_binding(binding)
            return await method(self, *args, **kwargs)

    return guarded


def queue_embedding_reindex(
    db, *, collection, artifact_id: str, parameters: dict | None = None
) -> WorkerJob:
    from app.services.huggingface.registry import require_artifact
    from app.services.knowledge_collections import create_worker_job

    require_artifact(db, collection.workspace_id, artifact_id, usage="embedding")
    row = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.id == collection.id)
        .with_for_update()
        .populate_existing()
        .one()
    )
    if row.pending_generation:
        raise HTTPException(409, detail={"code": "RAG_REINDEX_IN_PROGRESS"})
    if (
        db.query(WorkerJob.id)
        .filter(
            WorkerJob.collection_id == row.id,
            WorkerJob.status.in_(["queued", "running"]),
            WorkerJob.kind.in_(
                ["document_ingest_index", "vector_reindex", "qdrant_sparse_reindex"]
            ),
        )
        .first()
    ):
        raise HTTPException(409, detail={"code": "RAG_COLLECTION_JOB_ACTIVE"})
    generation = str(uuid4())
    # Compare-and-set also prevents two reservations on SQLite test/dev installs.
    changed = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.id == row.id,
            KnowledgeCollection.pending_generation.is_(None),
        )
        .update({KnowledgeCollection.pending_generation: generation}, synchronize_session=False)
    )
    if changed != 1:
        raise HTTPException(409, detail={"code": "RAG_REINDEX_IN_PROGRESS"})
    job = create_worker_job(
        db, workspace_id=row.workspace_id, collection_id=row.id, kind="vector_reindex"
    )
    job.result = {
        "reindex": {
            "source": binding_for(row),
            "generation": generation,
            "vector_collection_name": f"hfgen_{row.id.replace('-', '')}_{generation.replace('-', '')}",
            "artifact_id": artifact_id,
            "parameters": parameters or {},
            "estimated_chunks": row.chunk_count or 0,
        },
        "stage": "queued",
    }
    db.expire(row)
    return job


async def _run_embedding_reindex(job_id: str) -> dict:
    from app.core.settings_manager import get_resolved_settings
    from app.services.huggingface.adapters import ArtifactEmbedder
    from app.services.huggingface.registry import register_usage, require_artifact
    from app.services.rag.vector_store_config import resolve_vector_db_type
    from app.services.vector_db.factory import VectorDBFactory

    embedder = None
    target = None
    spec = None
    with SessionLocal() as db:
        claimed = (
            db.query(WorkerJob)
            .filter(
                WorkerJob.id == job_id,
                WorkerJob.kind == "vector_reindex",
                WorkerJob.status == "queued",
            )
            .update(
                {WorkerJob.status: "running", WorkerJob.started_at: datetime.utcnow()},
                synchronize_session=False,
            )
        )
        db.commit()
        if claimed != 1:
            return {"status": "skipped", "reason": "worker_job_not_claimable"}
        job = db.query(WorkerJob).filter(WorkerJob.id == job_id).one()
        try:
            spec = dict((job.result or {})["reindex"])
            source = spec["source"]
            row = (
                db.query(KnowledgeCollection)
                .filter(KnowledgeCollection.id == job.collection_id)
                .one()
            )
            if row.pending_generation != spec["generation"] or binding_for(row) != source:
                raise RuntimeError("RAG_GENERATION_CHANGED")
            db_type = resolve_vector_db_type(get_resolved_settings(workspace_id=job.workspace_id))
            if db_type not in {"qdrant", "faiss"}:
                raise RuntimeError("RAG_REINDEX_BACKEND_UNSUPPORTED")
            # Rebuilding may repair a revoked source embedding: only chunk text
            # is read from the old index. The new artifact must remain allowed.
            embedder = ArtifactEmbedder(
                workspace_id=job.workspace_id,
                artifact_id=spec["artifact_id"],
                parameters=spec["parameters"],
                db=db,
            )
            dimension = embedder.get_dimension()
            old = VectorDBFactory.get_db(source["vector_collection_name"], db_type=db_type)
            target = VectorDBFactory.get_db(spec["vector_collection_name"], db_type=db_type)
            await target.create_index(dimension)
            expected_count = await old.get_count()
            if expected_count != int(row.chunk_count or 0):
                raise RuntimeError("RAG_SOURCE_COUNT_MISMATCH")
            count = 0
            seen_ids: set[str] = set()
            async for batch in old.iter_payload_batches(batch_size=256):
                texts = [str(payload.get("content") or "") for payload in batch]
                ids = [
                    str(payload.get("chunk_id") or payload.get("point_id") or "")
                    for payload in batch
                ]
                if any(not text.strip() for text in texts) or any(not point for point in ids):
                    raise RuntimeError("RAG_SOURCE_PAYLOAD_INVALID")
                if len(set(ids)) != len(ids) or any(point in seen_ids for point in ids):
                    raise RuntimeError("RAG_SOURCE_DUPLICATE_IDS")
                seen_ids.update(ids)
                vectors = np.asarray(await embedder.embed_batch(texts))
                if vectors.shape != (len(batch), dimension) or not np.isfinite(vectors).all():
                    raise RuntimeError("RAG_EMBEDDING_SHAPE_INVALID")
                await target.add_vectors(vectors, batch, ids)
                count += len(batch)
                job.progress = min(95, int(95 * count / max(1, expected_count)))
                db.commit()
            if (
                count != expected_count
                or await target.get_count() != expected_count
                or await old.get_count() != expected_count
            ):
                raise RuntimeError("RAG_REINDEX_COUNT_MISMATCH")
            # Exercise the completed index before publishing, including empty
            # collections (the adapter has already run its real load probe).
            if expected_count:
                probe = await embedder.embed("validation")
                if not await target.search(probe, top_k=1):
                    raise RuntimeError("RAG_REINDEX_SEARCH_PROBE_FAILED")
            row = (
                db.query(KnowledgeCollection)
                .filter(KnowledgeCollection.id == job.collection_id)
                .with_for_update()
                .populate_existing()
                .one()
            )
            db.refresh(job)
            if (
                job.status != "running"
                or row.pending_generation != spec["generation"]
                or binding_for(row) != source
            ):
                raise RuntimeError("RAG_GENERATION_CHANGED")
            artifact = require_artifact(
                db, job.workspace_id, spec["artifact_id"], usage="embedding"
            )
            row.embedding_artifact_id = spec["artifact_id"]
            row.embedding_model = artifact.repo_id
            row.embedding_dimension = dimension
            row.embedding_params = dict(embedder.parameters)
            row.active_generation = spec["generation"]
            row.vector_collection_name = spec["vector_collection_name"]
            row.pending_generation = None
            row.status = "ready"
            row.last_error = None
            register_usage(
                db,
                job.workspace_id,
                spec["artifact_id"],
                "embedding",
                row.id,
                details=binding_for(row),
            )
            job.status, job.progress = "completed", 100
            job.completed_at = datetime.utcnow()
            result = {
                "reindex": spec,
                "stage": "ready",
                "binding": binding_for(row),
                "chunks": count,
            }
            job.result = result
            db.commit()
            return result
        except Exception as exc:
            db.rollback()
            # Only unpublished, private generation data may be discarded.
            # Preserve the old index and its authorization-dependent availability.
            job = db.query(WorkerJob).filter(WorkerJob.id == job_id).one()
            row = (
                db.query(KnowledgeCollection)
                .filter(KnowledgeCollection.id == job.collection_id)
                .with_for_update()
                .first()
            )
            if job.status == "completed" or (
                row
                and spec
                and row.active_generation == spec.get("generation")
                and row.vector_collection_name == spec.get("vector_collection_name")
            ):
                # A commit acknowledgement may fail after publication. Never
                # erase a generation which has become visible to readers.
                return dict(job.result or {})
            if row and spec and row.pending_generation == spec.get("generation"):
                row.pending_generation = None
                row.last_error = "Embedding reindex failed; previous generation retained"
            if job.status != "cancelled":
                job.status = "failed"
            job.error = str(exc)
            job.completed_at = datetime.utcnow()
            job.result = {**(job.result or {}), "stage": job.status}
            db.commit()
            if target is not None:
                try:
                    await target.clear_collection()
                except Exception:
                    # Retained abandoned index is private and not published.
                    pass
            raise
        finally:
            if embedder is not None:
                embedder.close()


def run_embedding_reindex(job_id: str) -> dict:
    return asyncio.run(_run_embedding_reindex(job_id))


def fail_embedding_preparation(job_id: str) -> dict:
    """Release the reservation when the preceding cache-preparation task fails."""
    with SessionLocal() as db:
        job = db.query(WorkerJob).filter(WorkerJob.id == job_id).with_for_update().first()
        if (
            not job
            or job.kind not in {"vector_reindex", "rag_reranker_activate"}
            or job.status != "queued"
        ):
            return {"status": "skipped"}
        generation = ((job.result or {}).get("reindex") or {}).get("generation")
        row = (
            db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.id == job.collection_id)
            .with_for_update()
            .first()
        )
        if row and generation and row.pending_generation == generation:
            row.pending_generation = None
        job.status = "failed"
        job.error = "HF_CACHE_PREPARATION_FAILED"
        job.completed_at = datetime.utcnow()
        db.commit()
        return {"status": "failed", "code": job.error}


def cancel_model_job(db, *, workspace_id: str, collection_id: str, job_id: str):
    """Release an interrupted build; a still-running worker cannot publish it."""
    row = (
        db.query(KnowledgeCollection)
        .filter_by(id=collection_id, workspace_id=workspace_id)
        .with_for_update()
        .first()
    )
    job = (
        db.query(WorkerJob)
        .filter_by(id=job_id, workspace_id=workspace_id, collection_id=collection_id)
        .with_for_update()
        .first()
    )
    if not row or not job or job.kind not in {"vector_reindex", "rag_reranker_activate"}:
        raise HTTPException(404, detail={"code": "RAG_MODEL_JOB_NOT_FOUND"})
    if job.status in {"queued", "running"}:
        generation = ((job.result or {}).get("reindex") or {}).get("generation")
        if generation and row.pending_generation == generation:
            row.pending_generation = None
        job.status = "cancelled"
        job.completed_at = datetime.utcnow()
        job.result = {
            **(job.result or {}),
            "stage": "cancelled",
            "execution": "draining_if_started",
        }
    return job
