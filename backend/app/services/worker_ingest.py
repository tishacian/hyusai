"""Worker-owned document ingestion and indexing workflows."""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.models.workspace import Workspace
from app.services.document_parser.factory import DocumentParserFactory
from app.services.knowledge_collections import (
    ingested_key,
    original_key,
    update_collection_status,
    update_job,
)
from app.services.object_store import get_object_store
from app.services.rag.bm25_store import rebuild_bm25_artifact
from app.services.rag.document_service import DocumentService

logger = get_logger(__name__)


async def _materialize_ingested_text(
    *,
    collection: KnowledgeCollection,
    local_path: Path,
) -> None:
    parser = DocumentParserFactory.get_parser(str(local_path))
    parsed = await parser.parse(str(local_path))
    text = "\n\n".join(str(chunk.get("content", "")) for chunk in parsed.chunks if chunk.get("content"))
    get_object_store().write_text(ingested_key(collection, local_path.name), text)


async def _run_document_ingest_index_async(job_id: str) -> dict:
    db = SessionLocal()
    temp_dir = Path(tempfile.mkdtemp(prefix="agentium-ingest-"))
    try:
        job = update_job(db, job_id, status="running", progress=5)
        if not job or not job.collection_id:
            db.commit()
            raise ValueError(f"Worker job {job_id!r} not found or not linked to a collection")

        collection = (
            db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.id == job.collection_id)
            .first()
        )
        if not collection:
            db.commit()
            raise ValueError(f"Collection for worker job {job_id!r} not found")

        workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first()
        if not workspace:
            db.commit()
            raise ValueError(f"Workspace for worker job {job_id!r} not found")

        update_collection_status(db, collection.id, status="ingesting")
        db.commit()

        store = get_object_store()
        file_names = list(collection.document_names or [])
        if not file_names:
            prefix = store.key(collection.artifact_prefix, "original")
            file_names = [Path(k).name for k in store.list_keys(prefix)]
        if not file_names:
            raise ValueError(f"No original documents found for collection {collection.id}")

        local_paths: list[str] = []
        for name in file_names:
            dest = temp_dir / Path(name).name
            store.copy_to_local(original_key(collection, name), dest)
            local_paths.append(str(dest))

        update_job(db, job_id, progress=25)
        db.commit()

        for path in local_paths:
            await _materialize_ingested_text(collection=collection, local_path=Path(path))

        app_settings = get_resolved_settings(workspace_id=workspace.id)
        collection.embedding_model = settings.embedding_model
        collection.chunking_method = app_settings.get("ragChunkingMethod", "recursive_character")
        collection.chunking_params = {
            "chunk_size": app_settings.get("ragChunkSize", 1000),
            "chunk_overlap": app_settings.get("ragChunkOverlap", 200),
        }
        update_collection_status(db, collection.id, status="embedding")
        update_job(db, job_id, progress=45)
        db.commit()

        db_type = app_settings.get("ragVectorDBType") or settings.default_vector_db_type or "faiss"
        doc_service = DocumentService(
            collection_name=collection.slug,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        # Worker jobs ingest the full collection snapshot. Clear stale vectors
        # first so a reindex cannot accumulate duplicate chunks with fresh temp
        # file-derived IDs.
        await doc_service.clear_all_documents()
        ingest_result = await doc_service.ingest_documents_batch(local_paths)
        chunk_count = await doc_service.get_document_count()
        documents = await doc_service.list_documents()
        bm25 = await rebuild_bm25_artifact(
            collection=collection,
            vector_db=doc_service.vector_db,
            store=store,
        )

        result = {
            "ingest": ingest_result,
            "bm25": bm25,
            "vector_db_type": db_type,
            "collection_slug": collection.slug,
            "chunk_count": chunk_count,
            "document_count": len(documents),
        }
        update_collection_status(
            db,
            collection.id,
            status="ready",
            document_count=len(documents),
            chunk_count=chunk_count,
            document_names=file_names,
        )
        update_job(db, job_id, status="completed", progress=100, result=result)
        db.commit()
        return result
    except Exception as exc:
        logger.exception("document ingest worker failed", job_id=job_id, error=str(exc))
        db.rollback()
        job = db.query(WorkerJob).filter(WorkerJob.id == job_id).first()
        if job and job.collection_id:
            update_collection_status(db, job.collection_id, status="error", last_error=str(exc))
        update_job(db, job_id, status="failed", progress=100, error=str(exc))
        db.commit()
        raise
    finally:
        db.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_document_ingest_index(job_id: str) -> dict:
    """Synchronous entrypoint used by Celery and eager-mode tests."""
    return asyncio.run(_run_document_ingest_index_async(job_id))
