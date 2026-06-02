"""Worker-owned BM25 sidecar rebuild workflow."""
from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.models.workspace import Workspace
from app.services.knowledge_collections import update_job
from app.services.object_store import get_object_store
from app.services.rag.bm25_store import rebuild_bm25_artifact
from app.services.rag.document_service import DocumentService
from app.services.rag.vector_store_config import resolve_vector_db_type

logger = get_logger(__name__)


async def _run_bm25_rebuild_async(job_id: str) -> dict:
    db = SessionLocal()
    try:
        job = update_job(db, job_id, status="running", progress=5, stage="bm25_prepare")
        if not job or not job.collection_id:
            db.commit()
            raise ValueError(f"BM25 worker job {job_id!r} not found or not linked to a collection")

        collection = (
            db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.id == job.collection_id)
            .first()
        )
        if not collection:
            db.commit()
            raise ValueError(f"Collection for BM25 worker job {job_id!r} not found")

        workspace = db.query(Workspace).filter(Workspace.id == job.workspace_id).first()
        if not workspace:
            db.commit()
            raise ValueError(f"Workspace for BM25 worker job {job_id!r} not found")

        db_type = resolve_vector_db_type(get_resolved_settings(workspace_id=workspace.id))
        update_job(db, job_id, progress=20, stage="bm25_load_vectors")
        db.commit()

        doc_service = DocumentService(
            collection_name=collection.slug,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )

        update_job(db, job_id, progress=45, stage="bm25_build")
        db.commit()
        bm25 = await rebuild_bm25_artifact(
            collection=collection,
            vector_db=doc_service.vector_db,
            store=get_object_store(),
            force=True,
        )
        result = {
            "stage": "bm25_ready",
            "bm25": bm25,
            "vector_db_type": db_type,
            "collection_slug": collection.slug,
        }
        update_job(db, job_id, status="completed", progress=100, result=result)
        db.commit()
        return result
    except Exception as exc:
        logger.exception("bm25 rebuild worker failed", job_id=job_id, error=str(exc))
        db.rollback()
        update_job(db, job_id, status="failed", progress=100, error=str(exc), stage="bm25_failed")
        db.commit()
        raise
    finally:
        db.close()


def run_bm25_rebuild(job_id: str) -> dict:
    """Synchronous entrypoint used by Celery and eager-mode tests."""
    return asyncio.run(_run_bm25_rebuild_async(job_id))
