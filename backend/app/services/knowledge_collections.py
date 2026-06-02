"""Service helpers for canonical knowledge collections and worker jobs."""
from __future__ import annotations

import mimetypes
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource, WorkerJob
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


def normalize_source_name(filename: str) -> str:
    return Path(str(filename or "source").replace("\\", "/")).name.strip()


def source_kind_for(filename: str, mime_type: str | None = None) -> str:
    ext = Path(filename or "").suffix.lower().lstrip(".")
    mime = str(mime_type or "").lower()
    if ext in {"xlsx", "xls", "xlsm", "xltx", "xltm", "csv", "tsv"}:
        return "spreadsheet"
    if ext in {"pdf"}:
        return "pdf"
    if ext in {"docx", "doc", "odt", "rtf"}:
        return "document"
    if ext in {"md", "markdown", "txt", "text", "log"}:
        return "text"
    if ext in {"html", "htm", "xml"}:
        return "markup"
    if ext in {"json", "yaml", "yml"}:
        return "structured_data"
    if ext in {"png", "jpg", "jpeg", "webp", "gif", "svg", "tif", "tiff"}:
        return "image"
    if mime.startswith("image/"):
        return "image"
    if "spreadsheet" in mime or "excel" in mime or "csv" in mime:
        return "spreadsheet"
    if "pdf" in mime:
        return "pdf"
    if "html" in mime or "xml" in mime:
        return "markup"
    if mime.startswith("text/"):
        return "text"
    return "document"


def upsert_collection_source(
    db: DBSession,
    *,
    collection: KnowledgeCollection,
    filename: str,
    status: str = "queued",
    mime_type: str | None = None,
    origin: str = "upload",
    size_bytes: int | None = None,
    chunk_count: int | None = None,
    source_metadata: dict[str, Any] | None = None,
    last_error: str | None = None,
) -> KnowledgeCollectionSource:
    normalized = normalize_source_name(filename)
    guessed_mime = mime_type or mimetypes.guess_type(normalized)[0] or ""
    extension = Path(normalized).suffix.lower().lstrip(".")
    row = (
        db.query(KnowledgeCollectionSource)
        .filter(
            KnowledgeCollectionSource.collection_id == collection.id,
            KnowledgeCollectionSource.normalized_name == normalized,
        )
        .first()
    )
    now = datetime.utcnow()
    if row is None:
        row = KnowledgeCollectionSource(
            id=str(uuid4()),
            workspace_id=collection.workspace_id,
            collection_id=collection.id,
            filename=normalized,
            normalized_name=normalized,
            created_at=now,
        )
        db.add(row)
    row.filename = normalized
    row.source_kind = source_kind_for(normalized, guessed_mime)
    row.extension = extension
    row.mime_type = guessed_mime
    row.origin = origin or row.origin or "upload"
    if size_bytes is not None:
        row.size_bytes = int(size_bytes)
    if chunk_count is not None:
        row.chunk_count = max(0, int(chunk_count))
    row.status = status
    row.last_error = last_error
    row.updated_at = now
    if status in {"indexed", "ready"}:
        row.indexed_at = now
    if source_metadata:
        merged = dict(row.source_metadata or {})
        merged.update(source_metadata)
        row.source_metadata = merged
    return row


def collection_source_rows(
    db: DBSession,
    *,
    collection: KnowledgeCollection,
    include_deleted: bool = False,
) -> list[KnowledgeCollectionSource]:
    query = db.query(KnowledgeCollectionSource).filter(KnowledgeCollectionSource.collection_id == collection.id)
    if not include_deleted:
        query = query.filter(KnowledgeCollectionSource.status != "deleted")
    rows = query.order_by(KnowledgeCollectionSource.filename.asc()).all()
    if rows:
        return rows
    # Backward-compatible fallback for pre-ledger collections. Do not commit:
    # callers may use this in read paths where side effects would be surprising.
    fallback: list[KnowledgeCollectionSource] = []
    for name in collection.document_names or []:
        normalized = normalize_source_name(str(name))
        fallback.append(
            KnowledgeCollectionSource(
                id=f"fallback-{collection.id}-{len(fallback)}",
                workspace_id=collection.workspace_id,
                collection_id=collection.id,
                filename=normalized,
                normalized_name=normalized,
                source_kind=source_kind_for(normalized),
                extension=Path(normalized).suffix.lower().lstrip("."),
                mime_type=mimetypes.guess_type(normalized)[0] or "",
                origin="legacy_document_names",
                size_bytes=None,
                chunk_count=0,
                status=collection.status or "ready",
                source_metadata={"fallback": True},
            )
        )
    return fallback


def collection_inventory(
    db: DBSession,
    *,
    collection: KnowledgeCollection,
    include_sources: bool = True,
) -> dict[str, Any]:
    rows = collection_source_rows(db, collection=collection)
    by_kind = Counter(row.source_kind or "document" for row in rows)
    by_extension = Counter((row.extension or "unknown") for row in rows)
    by_status = Counter(row.status or "unknown" for row in rows)
    sources = [
        {
            "id": row.id,
            "filename": row.filename,
            "source_kind": row.source_kind,
            "extension": row.extension,
            "mime_type": row.mime_type,
            "origin": row.origin,
            "size_bytes": row.size_bytes,
            "chunk_count": row.chunk_count,
            "status": row.status,
            "indexed_at": row.indexed_at.isoformat() if row.indexed_at else None,
            "last_error": row.last_error,
            "metadata": row.source_metadata or {},
        }
        for row in rows
    ]
    total_chunks = sum(int(row.chunk_count or 0) for row in rows) or (collection.chunk_count or 0)
    return {
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "collection_name": collection.name,
        "status": collection.status,
        "source_count": len(rows),
        "document_count": len(rows) or (collection.document_count or len(collection.document_names or [])),
        "chunk_count": total_chunks,
        "by_kind": dict(sorted(by_kind.items())),
        "by_extension": dict(sorted(by_extension.items())),
        "by_status": dict(sorted(by_status.items())),
        "sources": sources if include_sources else [],
    }


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
    try:
        source_rows = [row for row in (collection.sources or []) if row.status != "deleted"]
    except Exception:
        source_rows = []
    source_count = len(source_rows) or (collection.document_count or len(collection.document_names or []))
    source_kind_counts = Counter(row.source_kind or "document" for row in source_rows)
    source_extension_counts = Counter((row.extension or "unknown") for row in source_rows)
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
        "source_count": source_count,
        "source_kind_counts": dict(sorted(source_kind_counts.items())),
        "source_extension_counts": dict(sorted(source_extension_counts.items())),
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
