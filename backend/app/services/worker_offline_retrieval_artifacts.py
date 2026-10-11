"""Manual-only offline retrieval artifact workers.

These job kinds reserve the production control plane for sparse/summary/Qdrant
sparse backfills. They do not auto-run heavy indexing until the corresponding
backend is configured.
"""
from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.knowledge_collection import KnowledgeCollection
from app.models.workspace import Workspace
from app.services.knowledge_collections import update_job
from app.services.object_store import get_object_store
from app.services.rag.opensearch_sparse_index import rebuild_opensearch_sparse_index
from app.services.rag.summary_artifacts import rebuild_summary_index_artifact

logger = get_logger(__name__)

SUPPORTED_KINDS = {"sparse_index_rebuild", "summary_index_rebuild", "qdrant_sparse_reindex"}


def run_offline_retrieval_artifact_job(job_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        try:
            job = update_job(db, job_id, status="running", progress=5, stage="offline_prepare")
            if not job:
                db.commit()
                raise ValueError(f"Offline retrieval artifact job {job_id!r} not found")
            if job.kind not in SUPPORTED_KINDS:
                db.commit()
                raise ValueError(f"Unsupported offline retrieval artifact job kind: {job.kind}")

            if not job.collection_id:
                db.commit()
                raise ValueError(f"Offline retrieval artifact job {job_id!r} is not linked to a collection")
            collection = db.query(KnowledgeCollection).filter(KnowledgeCollection.id == job.collection_id).first()
            if not collection:
                db.commit()
                raise ValueError(f"Collection for offline retrieval artifact job {job_id!r} not found")

            if job.kind == "qdrant_sparse_reindex":
                if not settings.rag_qdrant_sparse_enabled:
                    result = {
                        **(job.result or {}),
                        "status": "skipped",
                        "configured": False,
                        "launch_policy": "manual_only",
                        "stage": "not_configured",
                        "reason": "qdrant_sparse_disabled",
                        "collection_slug": collection.slug,
                    }
                    update_job(db, job_id, status="completed", progress=100, result=result, stage="not_configured")
                    db.commit()
                    logger.info("Qdrant sparse reindex skipped", job_id=job_id, collection=collection.slug)
                    return result

                workspace = db.query(Workspace).filter(Workspace.id == collection.workspace_id).first()
                if not workspace:
                    db.commit()
                    raise ValueError(f"Workspace for offline retrieval artifact job {job_id!r} not found")
                update_job(db, job_id, progress=20, stage="qdrant_sparse_reindex")
                db.commit()
                from app.services.vector_db.factory import VectorDBFactory

                vector_db = VectorDBFactory.get_db(collection.slug, db_type="qdrant", workspace_slug=workspace.slug)
                import asyncio

                reindex = asyncio.run(vector_db.reindex_sparse_vectors())
                result = {
                    **(job.result or {}),
                    "status": reindex.get("status") or "ready",
                    "configured": bool(reindex.get("configured")),
                    "launch_policy": "manual_only",
                    "stage": "qdrant_sparse_ready" if reindex.get("status") == "ready" else "not_configured",
                    "qdrant_sparse_reindex": reindex,
                    "collection_slug": collection.slug,
                }
                update_job(
                    db,
                    job_id,
                    status="completed",
                    progress=100,
                    result=result,
                    stage=result["stage"],
                )
                db.commit()
                logger.info(
                    "Qdrant sparse reindex completed",
                    job_id=job_id,
                    collection=collection.slug,
                    points=reindex.get("points_reindexed"),
                    recreated=reindex.get("recreated_collection"),
                )
                return result

            if job.kind == "sparse_index_rebuild":
                update_job(db, job_id, progress=20, stage="sparse_summary_index")
                db.commit()
                sparse = rebuild_opensearch_sparse_index(
                    db=db,
                    collection=collection,
                    store=get_object_store(),
                )
                stage = "sparse_ready" if sparse.get("status") == "ready" else "not_configured"
                result = {
                    **(job.result or {}),
                    "status": sparse.get("status") or "skipped",
                    "configured": bool(sparse.get("configured")),
                    "launch_policy": "manual_only",
                    "stage": stage,
                    "sparse_index": sparse,
                    "collection_slug": collection.slug,
                }
                update_job(db, job_id, status="completed", progress=100, result=result, stage=stage)
                db.commit()
                logger.info(
                    "sparse retrieval artifact job completed",
                    job_id=job_id,
                    collection=collection.slug,
                    status=sparse.get("status"),
                    backend=sparse.get("backend"),
                    documents=sparse.get("documents_indexed"),
                )
                return result

            update_job(db, job_id, progress=25, stage="summary_collect")
            db.commit()
            summary = rebuild_summary_index_artifact(
                db=db,
                collection=collection,
                store=get_object_store(),
            )
            result = {
                **(job.result or {}),
                "status": "ready",
                "configured": True,
                "launch_policy": "manual_only",
                "stage": "summary_ready",
                "summary_index": summary,
                "collection_slug": collection.slug,
            }
            update_job(db, job_id, status="completed", progress=100, result=result, stage="summary_ready")
            db.commit()
            logger.info(
                "summary retrieval artifact job completed",
                job_id=job_id,
                collection=collection.slug,
                documents=summary.get("document_summaries"),
            )
            return result
        except Exception as exc:
            logger.exception("offline retrieval artifact job failed", job_id=job_id, error=str(exc))
            db.rollback()
            update_job(db, job_id, status="failed", progress=100, error=str(exc), stage="offline_failed")
            db.commit()
            raise
