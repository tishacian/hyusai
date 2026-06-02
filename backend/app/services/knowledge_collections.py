"""Service helpers for canonical knowledge collections and worker jobs."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.models.workspace import Workspace
from app.services.object_store import ObjectStore, get_object_store
from app.services.rag.bm25_store import bm25_artifact_key
from app.services.vector_db.factory import VectorDBFactory


def slugify(value: str, fallback: str = "collection") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-_")
    return (slug or fallback)[:100]


def _unique_slug(db: DBSession, workspace_id: str, base_slug: str) -> str:
    slug = base_slug[:100]
    index = 2
    while (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace_id, KnowledgeCollection.slug == slug)
        .first()
    ):
        suffix = f"-{index}"
        slug = f"{base_slug[:100 - len(suffix)]}{suffix}"
        index += 1
    return slug


def get_collection_or_404(
    db: DBSession,
    *,
    workspace_id: str,
    collection_ref: str,
) -> KnowledgeCollection:
    row = (
        db.query(KnowledgeCollection)
        .filter(
            KnowledgeCollection.workspace_id == workspace_id,
            (KnowledgeCollection.id == collection_ref) | (KnowledgeCollection.slug == collection_ref),
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Collection not found")
    return row


def create_collection(
    db: DBSession,
    *,
    workspace: Workspace,
    name: str,
    description: str = "",
    created_by_user_id: str | None = None,
    slug: str | None = None,
) -> KnowledgeCollection:
    collection_id = str(uuid4())
    base_slug = slugify(slug or name, fallback=f"collection-{collection_id[:8]}")
    unique_slug = _unique_slug(db, workspace.id, base_slug)
    vector_collection_name = VectorDBFactory.scoped_name(unique_slug, workspace.slug)
    store = get_object_store()
    row = KnowledgeCollection(
        id=collection_id,
        workspace_id=workspace.id,
        slug=unique_slug,
        name=name,
        description=description or "",
        status="created",
        document_names=[],
        vector_collection_name=vector_collection_name,
        artifact_prefix=store.collection_prefix(workspace.id, collection_id),
        embedding_model=settings.embedding_model,
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    db.flush()
    return row


def create_or_get_collection(
    db: DBSession,
    *,
    workspace: Workspace,
    name: str,
    description: str = "",
    created_by_user_id: str | None = None,
    slug: str | None = None,
) -> KnowledgeCollection:
    requested_slug = slugify(slug or name)
    existing = (
        db.query(KnowledgeCollection)
        .filter(KnowledgeCollection.workspace_id == workspace.id, KnowledgeCollection.slug == requested_slug)
        .first()
    )
    if existing:
        return existing
    return create_collection(
        db,
        workspace=workspace,
        name=name,
        description=description,
        created_by_user_id=created_by_user_id,
        slug=requested_slug,
    )


def create_worker_job(
    db: DBSession,
    *,
    workspace_id: str,
    collection_id: str | None,
    kind: str = "document_ingest_index",
) -> WorkerJob:
    job = WorkerJob(
        id=str(uuid4()),
        workspace_id=workspace_id,
        collection_id=collection_id,
        kind=kind,
        status="queued",
        progress=0,
        result={},
    )
    db.add(job)
    db.flush()
    return job


def set_job_task_id(db: DBSession, job_id: str, celery_task_id: str | None) -> None:
    job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
    if job:
        job.celery_task_id = celery_task_id
        job.updated_at = datetime.utcnow()


def update_job(
    db: DBSession,
    job_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
    stage: str | None = None,
) -> WorkerJob | None:
    job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
    if not job:
        return None
    now = datetime.utcnow()
    if status:
        job.status = status
        if status == "running" and not job.started_at:
            job.started_at = now
        if status in ("completed", "failed", "cancelled"):
            job.completed_at = now
    if progress is not None:
        job.progress = max(0, min(100, int(progress)))
    if error is not None:
        job.error = error
    if result is not None:
        job.result = result
    if stage is not None:
        merged = dict(job.result or {})
        merged["stage"] = stage
        job.result = merged
    job.updated_at = now
    return job


def update_collection_status(
    db: DBSession,
    collection_id: str,
    *,
    status: str,
    last_error: str | None = None,
    document_names: list[str] | None = None,
    document_count: int | None = None,
    chunk_count: int | None = None,
) -> KnowledgeCollection | None:
    row = db.query(KnowledgeCollection).filter(KnowledgeCollection.id == collection_id).first()
    if not row:
        return None
    row.status = status
    row.last_error = last_error
    if document_names is not None:
        row.document_names = document_names
    if document_count is not None:
        row.document_count = document_count
    if chunk_count is not None:
        row.chunk_count = chunk_count
    row.updated_at = datetime.utcnow()
    return row


def original_key(collection: KnowledgeCollection, filename: str) -> str:
    return get_object_store().key(collection.artifact_prefix, "original", Path(filename).name)


def resolve_original_key(
    collection: KnowledgeCollection,
    filename: str,
    *,
    legacy_name: str | None = None,
    store=None,
) -> str:
    """Return the object key for an original, tolerating the legacy flat scheme.

    Document originals are stored under ``original_key`` keyed by the *stored*
    document name. New SPL-wave ingests use a source-namespaced name while the
    pre-existing corpus keeps its flat (un-namespaced) name; in both cases the
    stored name matches its key, so the primary lookup resolves directly and no
    re-keying is ever required.

    ``legacy_name`` is an *explicit, known* fallback (e.g. the
    ``legacy_document_name`` recorded in the manifest). It is only used when the
    primary key is absent and is verified to exist before being returned, so a
    namespaced document can still be located if it was written under its legacy
    flat name. We never blindly strip a namespace prefix, because that could
    mis-resolve to a different archive's identically named file.
    """
    store = store or get_object_store()
    primary = original_key(collection, filename)
    if store.exists(primary):
        return primary
    if legacy_name:
        legacy = original_key(collection, legacy_name)
        if legacy != primary and store.exists(legacy):
            return legacy
    return primary


def ingested_key(collection: KnowledgeCollection, filename: str) -> str:
    safe_name = Path(filename).name.replace("/", "_").replace("\\", "_")
    text_name = safe_name if safe_name.lower().endswith(".txt") else f"{safe_name}.txt"
    return get_object_store().key(collection.artifact_prefix, "ingested", text_name)


def document_manifest_key(collection: KnowledgeCollection) -> str:
    return get_object_store().key(collection.artifact_prefix, "metadata", "document-manifest.json")


def serialize_job(job: WorkerJob) -> dict[str, Any]:
    result = job.result or {}
    return {
        "id": job.id,
        "workspace_id": job.workspace_id,
        "collection_id": job.collection_id,
        "kind": job.kind,
        "celery_task_id": job.celery_task_id,
        "status": job.status,
        "progress": job.progress,
        "error": job.error,
        "stage": result.get("stage"),
        "result": result,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


async def serialize_collection(
    collection: KnowledgeCollection,
    *,
    vector_db_type: str,
    workspace_slug: str,
    include_metrics: bool = False,
    store: ObjectStore | None = None,
) -> dict[str, Any]:
    payload = {
        "id": collection.id,
        "uuid": collection.id,
        "slug": collection.slug,
        "name": collection.name,
        "description": collection.description,
        "status": collection.status,
        "created_at": collection.created_at.isoformat() if collection.created_at else None,
        "updated_at": collection.updated_at.isoformat() if collection.updated_at else None,
        "created_by_user_id": collection.created_by_user_id,
        "document_names": collection.document_names or [],
        "document_count": collection.document_count or 0,
        "chunk_count": collection.chunk_count or 0,
        "embedding_model": collection.embedding_model,
        "chunking_method": collection.chunking_method,
        "chunking_params": collection.chunking_params,
        "vector_collection_name": collection.vector_collection_name,
        "artifact_prefix": collection.artifact_prefix,
        "last_error": collection.last_error,
        "is_embedded": collection.status == "ready",
    }
    if include_metrics:
        store = store or get_object_store()
        original_key_prefix = store.key(collection.artifact_prefix, "original")
        ingested_key_prefix = store.key(collection.artifact_prefix, "ingested")
        derived_key_prefix = store.key(collection.artifact_prefix, "derived")
        original_size = store.size(original_key_prefix)
        ingested_size = store.size(ingested_key_prefix)
        derived_size = store.size(derived_key_prefix)
        payload["uploaded_docs_size"] = original_size
        payload["original_docs_size"] = original_size
        payload["ingested_docs_size"] = ingested_size
        payload["derived_docs_size"] = derived_size
        payload["storage"] = {
            "original_bytes": original_size,
            "ingested_bytes": ingested_size,
            "derived_bytes": derived_size,
        }
        bm25_key = bm25_artifact_key(collection, store=store)
        bm25_size = store.size(bm25_key)
        payload["bm25"] = {
            "status": "ready" if bm25_size is not None else "missing",
            "path": bm25_key if bm25_size is not None else None,
            "size_bytes": bm25_size,
            "inline_threshold": settings.bm25_rebuild_inline_max_chunks,
        }
        try:
            vector_db = VectorDBFactory.get_db(
                collection.slug,
                db_type=vector_db_type,
                workspace_slug=workspace_slug,
            )
            payload["nb_chunks"] = await vector_db.get_count()
            payload["qdrant_collection_size"] = payload["nb_chunks"] if vector_db_type == "qdrant" else None
            payload["vector_metrics"] = {
                "type": vector_db_type,
                "collection": collection.vector_collection_name,
                "points": payload["nb_chunks"],
            }
        except Exception:
            payload["nb_chunks"] = None
            payload["qdrant_collection_size"] = None
            payload["vector_metrics"] = {
                "type": vector_db_type,
                "collection": collection.vector_collection_name,
                "points": None,
            }
    return payload
