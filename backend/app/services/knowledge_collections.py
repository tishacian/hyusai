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
    replace_source_metadata: bool = False,
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
    if replace_source_metadata:
        row.source_metadata = dict(source_metadata or {})
    elif source_metadata:
        merged = dict(row.source_metadata or {})
        merged.update(source_metadata)
        row.source_metadata = merged
    return row


def record_ingested_sources(
    db: DBSession,
    *,
    collection: KnowledgeCollection,
    ingest_result: dict[str, Any] | None,
    document_names: list[str] | None = None,
    origin: str = "sync",
) -> int:
    """Write one ledger row per ingested document from a DocumentService batch.

    Direct-sync indexing paths (intelligence/mission-room knowledge sync) push
    chunks straight into Qdrant via ``ingest_documents_batch`` and set
    ``collection.document_names`` but historically skipped
    ``knowledge_collection_sources``. That leaves the planner relying on the
    metadata-less ``document_names`` fallback. This mirrors the worker_ingest
    ledger pass so those collections keep the ledger in step with Qdrant.
    """
    results = (ingest_result or {}).get("results") or []
    names = list(document_names or [])
    written = 0
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            continue
        filename = names[index] if index < len(names) else (item.get("filename") or "")
        filename = filename or Path(str(item.get("document_id") or "")).name
        if not filename:
            continue
        status = "ready" if item.get("status") == "success" else "error"
        upsert_collection_source(
            db,
            collection=collection,
            filename=str(filename),
            status=status,
            origin=origin,
            chunk_count=int(item.get("chunks_processed") or 0),
            source_metadata={"document_id": item.get("document_id")},
            last_error=item.get("error"),
        )
        written += 1
    return written


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
    source_limit: int | None = None,
    source_offset: int = 0,
    q: str | None = None,
    source_kind: str | None = None,
    extension: str | None = None,
    status: str | None = None,
    project_code: str | None = None,
    archive_name: str | None = None,
    document_id: str | list[str] | None = None,
    document_filename: str | list[str] | None = None,
    language: str | None = None,
    sort: str = "filename",
    sort_dir: str = "asc",
) -> dict[str, Any]:
    rows = collection_source_rows(db, collection=collection)
    by_kind = Counter(row.source_kind or "document" for row in rows)
    by_extension = Counter((row.extension or "unknown") for row in rows)
    by_status = Counter(row.status or "unknown" for row in rows)
    filtered_rows = list(rows)
    needle = (q or "").strip().lower()
    if needle:
        filtered_rows = [
            row
            for row in filtered_rows
            if needle in str(row.filename or "").lower()
            or needle in str(row.normalized_name or "").lower()
            or needle in str(row.mime_type or "").lower()
            or needle in str(row.source_kind or "").lower()
            or needle in str(row.extension or "").lower()
        ]
    if source_kind:
        wanted = source_kind.strip().lower()
        filtered_rows = [row for row in filtered_rows if str(row.source_kind or "").lower() == wanted]
    if extension:
        wanted = extension.strip().lower().lstrip(".")
        filtered_rows = [row for row in filtered_rows if str(row.extension or "").lower().lstrip(".") == wanted]
    if status:
        wanted = status.strip().lower()
        filtered_rows = [row for row in filtered_rows if str(row.status or "").lower() == wanted]
    if project_code:
        wanted = project_code.strip().lower()

        def matches_project_code(row: KnowledgeCollectionSource) -> bool:
            metadata = row.source_metadata or {}
            metadata_values = {
                str(metadata.get(key) or "").strip().lower()
                for key in ("project_code", "project", "machine", "line")
                if str(metadata.get(key) or "").strip()
            }
            if metadata_values:
                return wanted in metadata_values

            # A Needlepunch numeric identifier is authoritative only when it is
            # carried by source metadata derived from the validated deposit
            # path.  Searching it as an arbitrary filename substring turns
            # part/material references such as ``1298561035`` into project
            # matches.  Keep the historical filename fallback for SPL's
            # alpha-numeric project references and keep ``q`` as the generic
            # filename-search filter.
            is_numeric5 = bool(re.fullmatch(r"\d{5}", wanted))
            is_needlepunch_source = (
                str(metadata.get("project_code_scheme") or "").strip().lower()
                == "needlepunch_numeric5"
                or str(metadata.get("business_scope") or "").strip().lower()
                == "needlepunch"
            )
            if is_numeric5 or is_needlepunch_source:
                return False
            return wanted in str(row.filename or "").lower()

        filtered_rows = [
            row
            for row in filtered_rows
            if matches_project_code(row)
        ]
    if archive_name:
        wanted = archive_name.strip().lower()
        filtered_rows = [
            row
            for row in filtered_rows
            if wanted == str((row.source_metadata or {}).get("archive_name") or "").lower()
            or wanted in str(row.filename or "").lower()
        ]

    def _wanted_values(value: str | list[str] | None) -> set[str]:
        if value is None:
            return set()
        raw_values = value if isinstance(value, list) else [value]
        return {str(item).strip().lower() for item in raw_values if str(item).strip()}

    wanted_document_ids = _wanted_values(document_id)
    if wanted_document_ids:
        filtered_rows = [
            row
            for row in filtered_rows
            if str((row.source_metadata or {}).get("document_id") or "").lower() in wanted_document_ids
        ]
    wanted_filenames = _wanted_values(document_filename)
    if wanted_filenames:
        filtered_rows = [
            row
            for row in filtered_rows
            if str(row.filename or "").lower() in wanted_filenames
            or str(row.normalized_name or "").lower() in wanted_filenames
        ]
    if language:
        wanted = language.strip().lower()
        filtered_rows = [
            row
            for row in filtered_rows
            if str((row.source_metadata or {}).get("language") or "").lower() == wanted
        ]

    sort_key = (sort or "filename").strip().lower()
    reverse = (sort_dir or "asc").strip().lower() == "desc"
    if sort_key == "chunk_count":
        key_fn = lambda row: (int(row.chunk_count or 0), str(row.filename or "").lower())
    elif sort_key == "indexed_at":
        key_fn = lambda row: (row.indexed_at or datetime.min, str(row.filename or "").lower())
    elif sort_key == "status":
        key_fn = lambda row: (str(row.status or ""), str(row.filename or "").lower())
    elif sort_key == "source_kind":
        key_fn = lambda row: (str(row.source_kind or ""), str(row.filename or "").lower())
    else:
        key_fn = lambda row: str(row.filename or "").lower()
    filtered_rows = sorted(filtered_rows, key=key_fn, reverse=reverse)

    safe_offset = max(0, int(source_offset or 0))
    safe_limit = None if source_limit is None else max(0, int(source_limit))
    source_rows = (
        filtered_rows[safe_offset:]
        if safe_limit is None
        else filtered_rows[safe_offset : safe_offset + safe_limit]
    )
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
        for row in source_rows
    ]
    total_chunks = sum(int(row.chunk_count or 0) for row in rows) or (collection.chunk_count or 0)
    top_sources = [
        {
            "id": row.id,
            "filename": row.filename,
            "source_kind": row.source_kind,
            "extension": row.extension,
            "chunk_count": int(row.chunk_count or 0),
            "status": row.status,
            "metadata": row.source_metadata or {},
        }
        for row in sorted(rows, key=lambda item: int(item.chunk_count or 0), reverse=True)[:20]
    ]
    buckets = {
        "0": {"sources": 0, "chunks": 0},
        "1-5": {"sources": 0, "chunks": 0},
        "6-50": {"sources": 0, "chunks": 0},
        "51-200": {"sources": 0, "chunks": 0},
        "201-1000": {"sources": 0, "chunks": 0},
        ">1000": {"sources": 0, "chunks": 0},
    }
    chunk_counts = sorted(int(row.chunk_count or 0) for row in rows)
    for count in chunk_counts:
        if count == 0:
            bucket = "0"
        elif count <= 5:
            bucket = "1-5"
        elif count <= 50:
            bucket = "6-50"
        elif count <= 200:
            bucket = "51-200"
        elif count <= 1000:
            bucket = "201-1000"
        else:
            bucket = ">1000"
        buckets[bucket]["sources"] += 1
        buckets[bucket]["chunks"] += count

    def percentile(value: float) -> int:
        if not chunk_counts:
            return 0
        index = min(len(chunk_counts) - 1, max(0, round((len(chunk_counts) - 1) * value)))
        return int(chunk_counts[index])

    return {
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "collection_name": collection.name,
        "status": collection.status,
        "source_count": len(rows),
        "sources_total": len(filtered_rows),
        "document_count": len(rows) or (collection.document_count or len(collection.document_names or [])),
        "chunk_count": total_chunks,
        "by_kind": dict(sorted(by_kind.items())),
        "by_extension": dict(sorted(by_extension.items())),
        "by_status": dict(sorted(by_status.items())),
        "top_sources": top_sources,
        "chunk_buckets": buckets,
        "chunk_percentiles": {
            "p50": percentile(0.50),
            "p90": percentile(0.90),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
        },
        "zero_chunk_sources": sum(1 for row in rows if int(row.chunk_count or 0) == 0),
        "error_sources": sum(1 for row in rows if str(row.status or "").lower() == "error"),
        "heavy_sources": sum(1 for row in rows if int(row.chunk_count or 0) > 1000),
        "source_filters": {
            "q": q or "",
            "source_kind": source_kind or "",
            "extension": extension or "",
            "status": status or "",
            "project_code": project_code or "",
            "archive_name": archive_name or "",
            "document_id": sorted(wanted_document_ids),
            "document_filename": sorted(wanted_filenames),
            "language": language or "",
            "sort": sort_key,
            "sort_dir": "desc" if reverse else "asc",
        },
        "sources": sources if include_sources else [],
        "sources_offset": safe_offset,
        "sources_limit": safe_limit,
        "sources_returned": len(sources) if include_sources else 0,
        "sources_has_more": include_sources and (safe_offset + len(sources) < len(filtered_rows)),
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
        if job.kind == "document_ingest_index":
            # Keep attempt provenance on every exit, including duplicate-only waves.
            result = {
                **{key: value for key, value in (job.result or {}).items()
                   if key in {"retry_history", "retry_request_id"}},
                **result,
            }
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


def serialize_job(job: WorkerJob, *, include_retrieval_context: bool = False) -> dict[str, Any]:
    result = dict(job.result or {})
    if (
        job.kind == "rag_deep_retrieval"
        and not include_retrieval_context
        and "retrieval_context" in result
    ):
        result.pop("retrieval_context", None)
        result["retrieval_context_omitted"] = True
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
        "poll_url": f"/documents/jobs/{job.id}",
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
    include_document_names: bool = False,
    include_source_facets: bool = False,
    store: ObjectStore | None = None,
) -> dict[str, Any]:
    if include_source_facets:
        try:
            source_rows = [row for row in (collection.sources or []) if row.status != "deleted"]
        except Exception:
            source_rows = []
    else:
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
    if include_document_names:
        payload["document_names"] = collection.document_names or []
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
