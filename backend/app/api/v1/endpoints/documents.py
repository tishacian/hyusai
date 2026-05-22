"""Document management endpoints"""

import os
import shutil
import tempfile
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_resolved_settings
from app.db.base import get_db
from app.models.knowledge_collection import KnowledgeCollection, WorkerJob
from app.models.knowledge_document_fact import KnowledgeDocumentFact
from app.models.user import User
from app.models.workspace import Workspace
from app.services.knowledge_collections import (
    create_or_get_collection,
    create_collection as create_knowledge_collection,
    create_worker_job,
    get_collection_or_404,
    original_key,
    serialize_collection,
    serialize_job,
    update_collection_status,
)
from app.services.object_store import get_object_store
from app.services.rag.document_service import DocumentService
from app.services.worker_dispatch import dispatch_worker_job

logger = get_logger(__name__)
router = APIRouter()

UPLOADS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))),
    "uploads",
)
os.makedirs(UPLOADS_DIR, exist_ok=True)


class DocumentSearchRequest(BaseModel):
    """Document search request"""

    query: str
    top_k: int = 10
    filters: Optional[dict] = None
    collection_name: str = "documents"
    use_hybrid: bool = True  # Enable hybrid search by default


class DocumentSearchResponse(BaseModel):
    """Document search response"""

    results: list[dict]
    total: int


class CollectionCreateRequest(BaseModel):
    name: str
    description: str = ""
    slug: str | None = None


class CollectionPatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None


def _resolve_document_vector_db_type(
    workspace: Workspace,
    requested_type: Optional[str] = None,
) -> str:
    app_settings = get_resolved_settings(workspace_id=workspace.id)
    return (
        requested_type
        or app_settings.get("ragVectorDBType")
        or settings.default_vector_db_type
        or "faiss"
    )


async def _queue_collection_ingest(
    *,
    db: DBSession,
    workspace: Workspace,
    collection: KnowledgeCollection,
    files: list[UploadFile],
) -> dict:
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required")

    store = get_object_store()
    existing = list(collection.document_names or [])
    uploaded_names: list[str] = []
    for file in files:
        safe_name = (file.filename or "upload").replace("/", "_").replace("\\", "_")
        content = await file.read()
        store.write_bytes(original_key(collection, safe_name), content)
        if safe_name not in existing:
            existing.append(safe_name)
        uploaded_names.append(safe_name)

    update_collection_status(
        db,
        collection.id,
        status="queued",
        document_names=existing,
        document_count=len(existing),
    )
    job = create_worker_job(
        db,
        workspace_id=workspace.id,
        collection_id=collection.id,
        kind="document_ingest_index",
    )
    db.commit()
    db.refresh(job)
    db.refresh(collection)

    dispatch_worker_job(db, job)
    db.commit()

    db.refresh(job)
    db.refresh(collection)
    return {
        "collection_id": collection.id,
        "collection_slug": collection.slug,
        "job_id": job.id,
        "celery_task_id": job.celery_task_id,
        "status": job.status,
        "collection_status": collection.status,
        "files": uploaded_names,
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    collection_name: str = Form("documents"),
    vector_db_type: Optional[str] = Form(None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Upload and index a document"""
    try:
        if settings.document_ingest_async_enabled:
            collection = create_or_get_collection(
                db,
                workspace=workspace,
                name=collection_name,
                created_by_user_id=user.id,
                slug=collection_name,
            )
            queued = await _queue_collection_ingest(
                db=db,
                workspace=workspace,
                collection=collection,
                files=[file],
            )
            return {
                "status": queued["status"],
                "collection_id": queued["collection_id"],
                "collection_name": queued["collection_slug"],
                "job_id": queued["job_id"],
                "filename": file.filename,
                "chunks_processed": 0,
            }

        app_settings = get_resolved_settings(workspace_id=workspace.id)
        # Keep symmetric with the RAG agent read path (`get("ragVectorDBType",
        # "faiss")`) so upload and retrieval never land in different backends.
        db_type = (
            vector_db_type
            or app_settings.get("ragVectorDBType")
            or settings.default_vector_db_type
            or "faiss"
        )

        safe_name = file.filename.replace("/", "_").replace("\\", "_")
        tmp_dir = tempfile.mkdtemp()
        tmp_path = os.path.join(tmp_dir, safe_name)
        try:
            with open(tmp_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            doc_service = DocumentService(
                collection_name=collection_name,
                vector_db_type=db_type,
                workspace_slug=workspace.slug,
            )
            result = await doc_service.ingest_document(tmp_path)
            doc_id = result.get("document_id", "")

            # Persist original file for preview
            if doc_id:
                persist_path = os.path.join(UPLOADS_DIR, f"{doc_id}_{safe_name}")
                shutil.copy2(tmp_path, persist_path)

            return {
                "status": "success",
                "document_id": doc_id,
                "chunks_processed": result.get("chunks_processed", 0),
                "filename": file.filename,
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        logger.error(f"Error uploading document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-batch")
async def upload_documents_batch(
    files: list[UploadFile] = File(...),
    collection_name: str = Form("documents"),
    vector_db_type: Optional[str] = Form(None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Upload and index multiple documents"""
    if settings.document_ingest_async_enabled:
        collection = create_or_get_collection(
            db,
            workspace=workspace,
            name=collection_name,
            created_by_user_id=user.id,
            slug=collection_name,
        )
        queued = await _queue_collection_ingest(
            db=db,
            workspace=workspace,
            collection=collection,
            files=files,
        )
        return {
            "status": queued["status"],
            "collection_id": queued["collection_id"],
            "collection_name": queued["collection_slug"],
            "job_id": queued["job_id"],
            "total": len(files),
            "successful": 0,
            "failed": 0,
            "documents": [
                {
                    "document_id": None,
                    "filename": filename,
                    "status": "queued",
                    "chunks_processed": 0,
                }
                for filename in queued["files"]
            ],
        }

    app_settings = get_resolved_settings(workspace_id=workspace.id)
    # Ultimate fallback is "faiss" to stay symmetric with the RAG agent retrieval
    # path. The per-workspace preset still wins and the env-level
    # `DEFAULT_VECTOR_DB_TYPE` can override it via the request param — but when
    # nothing is set, we no longer diverge from the read side.
    db_type = (
        vector_db_type
        or app_settings.get("ragVectorDBType")
        or settings.default_vector_db_type
        or "faiss"
    )

    # We write each upload into a fresh tmpdir using its *original* filename so
    # downstream parsers surface `slides_admin_cockpit.pdf` in chunk metadata
    # rather than `tmp73klgow9.pdf`. The drop-and-ask flow relies on this for
    # filename-based questions ("what is slides_admin_cockpit.pdf about?").
    temp_dirs: list[str] = []
    try:
        file_paths = []
        for file in files:
            safe_name = (file.filename or "upload").replace("/", "_").replace("\\", "_")
            tmp_dir = tempfile.mkdtemp()
            temp_dirs.append(tmp_dir)
            tmp_path = os.path.join(tmp_dir, safe_name)
            with open(tmp_path, "wb") as out:
                shutil.copyfileobj(file.file, out)
            file_paths.append(tmp_path)

        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        result = await doc_service.ingest_documents_batch(file_paths)

        # Surface per-document ids + filenames so the UI can request
        # docmeta for each (Doc-facts panel) without re-uploading or
        # re-listing the whole collection.
        documents = [
            {
                "document_id": r.get("document_id"),
                "filename": r.get("filename"),
                "status": r.get("status"),
                "chunks_processed": r.get("chunks_processed"),
            }
            for r in (result.get("results") or [])
        ]

        return {
            "status": "success",
            "total": result["total"],
            "successful": result["successful"],
            "failed": result["failed"],
            "documents": documents,
        }

    except Exception as e:
        logger.error(f"Error uploading documents batch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        for tmp_dir in temp_dirs:
            shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/search")
async def search_documents(
    request: DocumentSearchRequest,
    workspace: Workspace = Depends(get_current_workspace),
):
    """Search documents"""
    try:
        app_settings = get_resolved_settings(workspace_id=workspace.id)
        db_type = app_settings.get("ragVectorDBType", settings.default_vector_db_type)

        doc_service = DocumentService(
            collection_name=request.collection_name,
            vector_db_type=db_type,
            use_hybrid=request.use_hybrid,
            workspace_slug=workspace.slug,
        )
        results = await doc_service.search(
            query=request.query,
            top_k=request.top_k,
            filters=request.filters,
            use_hybrid=request.use_hybrid,
        )

        return DocumentSearchResponse(
            results=results,
            total=len(results),
        )

    except Exception as e:
        logger.error(f"Error searching documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/table-facts")
async def list_table_facts(
    collection_name: str = Query("documents"),
    semantic_type: Optional[str] = Query(None),
    sheet_name: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
):
    """List spreadsheet facts/chunks for Knowledge diagnostics."""
    try:
        db_type = _resolve_document_vector_db_type(workspace, vector_db_type)
        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        rows = await doc_service.list_table_facts(
            semantic_type=semantic_type,
            sheet_name=sheet_name,
            query=q,
            limit=limit,
            offset=offset,
        )
        items = [
            {
                "content": row.get("content"),
                "semantic_type": row.get("semantic_type"),
                "document_id": row.get("document_id"),
                "document_filename": row.get("document_filename"),
                "sheet_name": row.get("sheet_name"),
                "cell_ref": row.get("cell_ref"),
                "cell_range": row.get("cell_range"),
                "row_start": row.get("row_start"),
                "row_end": row.get("row_end"),
                "row_label": row.get("row_label"),
                "column_header": row.get("column_header"),
                "unit": row.get("unit"),
                "table_region_id": row.get("table_region_id"),
                "interpretation_note": row.get("interpretation_note"),
                "chunk_index": row.get("chunk_index"),
            }
            for row in rows
        ]
        return {
            "collection_name": collection_name,
            "vector_db_type": db_type,
            "items": items,
            "total_returned": len(items),
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error(f"Error listing table facts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/document-facts")
def list_document_facts(
    collection_name: str = Query("documents"),
    semantic_type: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List structured document facts for Knowledge diagnostics."""
    query = db.query(KnowledgeDocumentFact).filter(
        KnowledgeDocumentFact.workspace_id == workspace.id,
        KnowledgeDocumentFact.collection_slug == collection_name,
    )
    if semantic_type:
        query = query.filter(KnowledgeDocumentFact.semantic_type == semantic_type)
    if q:
        like = f"%{q}%"
        query = query.filter(
            KnowledgeDocumentFact.content.ilike(like)
            | KnowledgeDocumentFact.document_filename.ilike(like)
            | KnowledgeDocumentFact.subject.ilike(like)
            | KnowledgeDocumentFact.value_raw.ilike(like)
            | KnowledgeDocumentFact.section_path.ilike(like)
        )
    rows = (
        query.order_by(KnowledgeDocumentFact.document_filename, KnowledgeDocumentFact.page, KnowledgeDocumentFact.paragraph_index)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "collection_name": collection_name,
        "items": [
            {
                "id": row.id,
                "content": row.content,
                "semantic_type": row.semantic_type,
                "document_id": row.document_id,
                "document_filename": row.document_filename,
                "document_type": row.document_type,
                "subject": row.subject,
                "predicate": row.predicate,
                "value_raw": row.value_raw,
                "value_numeric": row.value_numeric,
                "unit": row.unit,
                "page": row.page,
                "section_path": row.section_path,
                "paragraph_index": row.paragraph_index,
                "table_index": row.table_index,
                "evidence_locator": row.evidence_locator or {},
                "confidence": row.confidence,
            }
            for row in rows
        ],
        "total_returned": len(rows),
        "limit": limit,
        "offset": offset,
    }


def _find_original_file(document_id: str, filename: str) -> Optional[str]:
    """Find the original file in uploads/ or sample_data/."""
    # 1) Check uploads/ (persisted uploaded files)
    for entry in os.listdir(UPLOADS_DIR):
        if entry.startswith(document_id):
            candidate = os.path.join(UPLOADS_DIR, entry)
            if os.path.isfile(candidate):
                return candidate

    # 2) Check sample_data/ (pre-loaded seed docs)
    sample_dir = os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            )
        ),
        "sample_data",
    )
    candidate = os.path.join(sample_dir, filename)
    if os.path.isfile(candidate):
        return candidate

    return None


@router.get("/{document_id}/metadata")
async def get_document_metadata(
    document_id: str,
    collection_name: str = Query("documents"),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Return docmeta-enriched metadata for a single document.

    Surfaces the ``document_*`` fields persisted at ingestion time (title,
    author, num_pages, token_count, TF-IDF keywords, language, ...). The
    UI's "Doc facts" panel calls this endpoint for every document it
    renders in the sources list; callers that only need the filename stay
    on the cheaper ``GET /documents`` listing.
    """
    try:
        app_settings = get_resolved_settings(workspace_id=workspace.id)
        db_type = (
            app_settings.get("ragVectorDBType")
            or settings.default_vector_db_type
            or "faiss"
        )
        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        metadata = await doc_service.get_document_metadata(document_id)
        if not metadata:
            raise HTTPException(status_code=404, detail="Document not found")
        return {
            "document_id": document_id,
            "metadata": metadata,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching document metadata: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/preview/{document_id}")
async def preview_document(
    document_id: str,
    collection_name: str = Query("documents"),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Return raw content of a document for preview (text) or redirect info for binary files."""
    try:
        doc_service = DocumentService(collection_name=collection_name, workspace_slug=workspace.slug)
        documents = await doc_service.list_documents()
        doc = next((d for d in documents if d.get("document_id") == document_id), None)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        filename = doc.get("filename", "")
        filepath = _find_original_file(document_id, filename)
        if not filepath:
            raise HTTPException(status_code=404, detail="Source file not found")

        ext = os.path.splitext(filepath)[1].lower()

        if ext == ".pdf":
            return {
                "document_id": document_id,
                "filename": filename,
                "content_type": "application/pdf",
                "download_url": f"/api/v1/documents/file/{document_id}",
                "size": os.path.getsize(filepath),
            }

        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        return {
            "document_id": document_id,
            "filename": filename,
            "content": content,
            "content_type": "text/plain",
            "size": len(content),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error previewing document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/file/{document_id}")
async def serve_document_file(
    document_id: str,
    collection_name: str = Query("documents"),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Serve the original uploaded file (PDF, DOCX, etc.) for in-browser viewing."""
    try:
        doc_service = DocumentService(collection_name=collection_name, workspace_slug=workspace.slug)
        documents = await doc_service.list_documents()
        doc = next((d for d in documents if d.get("document_id") == document_id), None)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        filename = doc.get("filename", "")
        filepath = _find_original_file(document_id, filename)
        if not filepath:
            raise HTTPException(status_code=404, detail="Source file not found")

        ext = os.path.splitext(filepath)[1].lower()
        media_types = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain",
            ".md": "text/markdown",
        }
        media_type = media_types.get(ext, "application/octet-stream")

        return FileResponse(
            filepath,
            media_type=media_type,
            filename=filename,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_document_stats(
    collection_name: str = "documents",
    workspace: Workspace = Depends(get_current_workspace),
):
    """Get document statistics"""
    try:
        db_type = _resolve_document_vector_db_type(workspace)
        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        count = await doc_service.get_document_count()

        # Get cache stats if available
        cache_stats = None
        if doc_service.cache:
            cache_stats = doc_service.cache.get_stats()

        vector_dim = getattr(doc_service.vector_db, "dimension", None)

        return {
            "collection_name": collection_name,
            "vector_db_type": db_type,
            "total_chunks": count,
            "vector_dim": vector_dim,
            "cache_stats": cache_stats,
        }

    except Exception as e:
        logger.error(f"Error getting stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/clear")
async def clear_all_documents(
    collection_name: str = Query("documents"),
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Clear all documents from a collection"""
    try:
        app_settings = get_resolved_settings(workspace_id=workspace.id)
        db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)

        doc_service = DocumentService(
            collection_name=collection_name, vector_db_type=db_type, workspace_slug=workspace.slug
        )
        success = await doc_service.clear_all_documents()

        if success:
            # Also clean up persisted upload files
            for entry in os.listdir(UPLOADS_DIR):
                try:
                    os.unlink(os.path.join(UPLOADS_DIR, entry))
                except OSError:
                    pass
            return {
                "status": "success",
                "message": f"All documents cleared from collection '{collection_name}'",
                "vector_db_type": db_type,
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to clear documents")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error clearing documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    collection_name: str = Query("documents"),
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Delete a document and its chunks"""
    try:
        app_settings = get_resolved_settings(workspace_id=workspace.id)
        db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)

        doc_service = DocumentService(
            collection_name=collection_name, vector_db_type=db_type, workspace_slug=workspace.slug
        )

        success = await doc_service.delete_document(document_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete document")

        # Clean up persisted upload file
        for entry in os.listdir(UPLOADS_DIR):
            if entry.startswith(document_id):
                try:
                    os.unlink(os.path.join(UPLOADS_DIR, entry))
                except OSError:
                    pass

        return {
            "status": "success",
            "message": f"Document {document_id} deleted",
            "vector_db_type": db_type,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collections")
async def list_collections(
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """List canonical collections for the current workspace.

    The legacy ``collections`` string list is kept for existing UI consumers;
    richer Agentium metadata is returned under ``items``.
    """
    try:
        from app.services.vector_db.factory import VectorDBFactory

        app_settings = get_resolved_settings(workspace_id=workspace.id)
        db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)

        rows = (
            db.query(KnowledgeCollection)
            .filter(KnowledgeCollection.workspace_id == workspace.id)
            .order_by(KnowledgeCollection.created_at.desc())
            .all()
        )
        items = [
            await serialize_collection(
                row,
                vector_db_type=db_type,
                workspace_slug=workspace.slug,
                include_metrics=False,
            )
            for row in rows
        ]

        legacy_names = VectorDBFactory.list_collections_for_workspace(
            db_type=db_type, workspace_slug=workspace.slug
        )
        ledger_slugs = {row.slug for row in rows}
        legacy_names = [
            name for name in legacy_names if not name.startswith("_") and name not in ledger_slugs
        ]
        collection_names = [item["slug"] for item in items] + legacy_names

        return {
            "collections": collection_names,
            "items": items,
            "legacy_collections": legacy_names,
            "default": collection_names[0] if collection_names else None,
            "vector_db_type": db_type,
        }

    except Exception as e:
        logger.error(f"Error listing collections: {e}", exc_info=True)
        # Return empty list on error, let frontend handle it
        return {
            "collections": [],
            "items": [],
            "legacy_collections": [],
            "default": None,
            "vector_db_type": vector_db_type or settings.default_vector_db_type,
        }


@router.post("/collections")
async def create_collection(
    payload: CollectionCreateRequest | None = Body(None),
    collection_name: Optional[str] = Query(None),
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create a workspace-scoped collection ledger row and vector collection."""
    try:
        from app.services.vector_db.factory import VectorDBFactory

        app_settings = get_resolved_settings(workspace_id=workspace.id)
        db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)
        requested_name = (payload.name if payload else collection_name) or ""
        if not requested_name.strip():
            raise HTTPException(status_code=422, detail="Collection name is required")

        if payload is None and collection_name:
            row = create_or_get_collection(
                db,
                workspace=workspace,
                name=requested_name,
                created_by_user_id=user.id,
                slug=collection_name,
            )
        else:
            row = create_knowledge_collection(
                db,
                workspace=workspace,
                name=requested_name,
                description=payload.description if payload else "",
                created_by_user_id=user.id,
                slug=payload.slug if payload else collection_name,
            )
        vector_db = VectorDBFactory.get_db(row.slug, db_type=db_type, workspace_slug=workspace.slug)

        # For FAISS, ensure the index is created and saved so it shows up in listings
        if db_type == "faiss":
            # Create index with default dimension (384 for all-MiniLM-L6-v2)
            await vector_db.create_index(384)
            # Save to disk immediately so it appears in listings
            if hasattr(vector_db, "_save"):
                vector_db._save()
        elif db_type == "qdrant":
            from app.services.embedding.embedder import Embedder

            dim = Embedder().get_dimension()
            await vector_db.create_index(dim)

        count = await vector_db.get_count()
        row.chunk_count = count
        db.commit()
        db.refresh(row)

        updated_collections = VectorDBFactory.list_collections_for_workspace(
            db_type=db_type, workspace_slug=workspace.slug
        )
        if row.slug not in updated_collections:
            logger.warning(f"Collection '{row.slug}' created but not found in listings")

        item = await serialize_collection(
            row,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
            include_metrics=True,
        )
        return {
            "status": "success",
            "collection_id": row.id,
            "collection_name": row.slug,
            "item": item,
            "vector_db_type": db_type,
            "total_chunks": count,
            "collections": updated_collections,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating collection: {e}", exc_info=True)
        error_msg = str(e)
        # Provide more helpful error messages
        if "already exists" in error_msg.lower() or "different settings" in error_msg.lower():
            raise HTTPException(
                status_code=409,
                detail="Collection already exists or there is a vector-store conflict. Please try a different name.",
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collections/{collection_id}")
async def get_collection_detail(
    collection_id: str,
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Return collection metadata enriched with storage/vector metrics."""
    db_type = _resolve_document_vector_db_type(workspace, vector_db_type)
    row = get_collection_or_404(
        db,
        workspace_id=workspace.id,
        collection_ref=collection_id,
    )
    jobs = (
        db.query(WorkerJob)
        .filter(WorkerJob.collection_id == row.id)
        .order_by(WorkerJob.created_at.desc())
        .limit(10)
        .all()
    )
    payload = await serialize_collection(
        row,
        vector_db_type=db_type,
        workspace_slug=workspace.slug,
        include_metrics=True,
    )
    payload["jobs"] = [serialize_job(job) for job in jobs]
    return payload


@router.patch("/collections/{collection_id}")
async def patch_collection(
    collection_id: str,
    payload: CollectionPatchRequest,
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Patch mutable collection presentation fields."""
    row = get_collection_or_404(
        db,
        workspace_id=workspace.id,
        collection_ref=collection_id,
    )
    if payload.name is not None:
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    db.commit()
    db.refresh(row)
    db_type = _resolve_document_vector_db_type(workspace, vector_db_type)
    return await serialize_collection(
        row,
        vector_db_type=db_type,
        workspace_slug=workspace.slug,
        include_metrics=True,
    )


@router.post("/collections/{collection_id}/documents")
async def upload_collection_documents(
    collection_id: str,
    files: list[UploadFile] = File(...),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Store originals and queue worker-owned parse/chunk/embed/index work."""
    row = get_collection_or_404(
        db,
        workspace_id=workspace.id,
        collection_ref=collection_id,
    )
    return await _queue_collection_ingest(
        db=db,
        workspace=workspace,
        collection=row,
        files=files,
    )


@router.get("/jobs/{job_id}")
async def get_worker_job(
    job_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    job = (
        db.query(WorkerJob)
        .filter(WorkerJob.id == job_id, WorkerJob.workspace_id == workspace.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Worker job not found")
    return serialize_job(job)


@router.delete("/collections/{collection_name}")
async def delete_collection(
    collection_name: str,
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
    db: DBSession = Depends(get_db),
):
    """Delete a collection in the current workspace."""
    try:
        from urllib.parse import unquote

        from app.services.vector_db.factory import VectorDBFactory

        collection_name = unquote(collection_name)

        app_settings = get_resolved_settings(workspace_id=workspace.id)
        db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)
        row = (
            db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.workspace_id == workspace.id,
                (KnowledgeCollection.id == collection_name)
                | (KnowledgeCollection.slug == collection_name),
            )
            .first()
        )
        logical_collection_name = row.slug if row else collection_name

        scoped_coll = VectorDBFactory.scoped_name(logical_collection_name, workspace.slug)
        collections = VectorDBFactory.list_collections(db_type=db_type)
        collection_exists = scoped_coll in collections

        if not collection_exists and row is None:
            raise HTTPException(
                status_code=404, detail=f"Collection '{collection_name}' not found in {db_type}"
            )

        try:
            vector_db = VectorDBFactory.get_db(
                logical_collection_name, db_type=db_type, workspace_slug=workspace.slug
            )
            await vector_db.clear_collection()
        except Exception as e:
            logger.warning(f"Error clearing collection before deletion: {e}")

        try:
            VectorDBFactory.clear_instance(
                logical_collection_name, db_type=db_type, workspace_slug=workspace.slug
            )
        except Exception as cache_error:
            logger.warning(f"Could not clear cached instance: {cache_error}")

        try:
            if db_type == "chroma":
                import chromadb

                client = chromadb.PersistentClient(path=settings.chroma_persist_directory)
                client.delete_collection(name=scoped_coll)
            elif db_type == "faiss":
                persist_dir = getattr(settings, "faiss_persist_directory", "./faiss_db")
                index_path = os.path.join(persist_dir, f"{scoped_coll}.index")
                metadata_path = os.path.join(persist_dir, f"{scoped_coll}.metadata.pkl")
                if os.path.exists(index_path):
                    os.remove(index_path)
                if os.path.exists(metadata_path):
                    os.remove(metadata_path)
            elif db_type == "qdrant":
                # Collection already removed by clear_collection on QdrantVectorDB
                pass

            if row is not None:
                row_id = row.id
                get_object_store().delete_prefix(row.artifact_prefix)
                db.delete(row)
                db.commit()
            else:
                row_id = None

            logger.info(f"Successfully deleted collection: {logical_collection_name} (type: {db_type})")
            return {
                "status": "success",
                "message": f"Collection '{logical_collection_name}' deleted successfully",
                "collection_id": row_id,
                "collection_name": logical_collection_name,
                "vector_db_type": db_type,
            }
        except ValueError as e:
            # Collection doesn't exist or already deleted
            error_msg = str(e)
            if "not found" in error_msg.lower() or "does not exist" in error_msg.lower():
                raise HTTPException(
                    status_code=404, detail=f"Collection '{collection_name}' not found"
                )
            else:
                logger.error(f"ValueError when deleting collection: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500, detail=f"Failed to delete collection: {error_msg}"
                )
        except Exception as delete_error:
            logger.error(
                f"Error deleting collection '{collection_name}': {delete_error}", exc_info=True
            )
            raise HTTPException(
                status_code=500, detail=f"Failed to delete collection: {str(delete_error)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error deleting collection '{collection_name}': {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=f"Failed to delete collection: {str(e)}")


@router.get("/list")
async def list_documents(
    collection_name: str = Query("documents"),
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
):
    """List all documents in a collection (scoped to current workspace)."""
    try:
        db_type = _resolve_document_vector_db_type(workspace, vector_db_type)

        doc_service = DocumentService(
            collection_name=collection_name, vector_db_type=db_type, workspace_slug=workspace.slug
        )
        documents = await doc_service.list_documents()

        # Filter out temporary files and system files
        filtered_documents = [
            doc
            for doc in documents
            if not doc.get("filename", "").startswith(".")  # Exclude hidden files
            and not doc.get("filename", "").endswith(".tmp")  # Exclude temp files
            and doc.get("document_id")  # Ensure document_id exists
        ]

        return {
            "collection_name": collection_name,
            "vector_db_type": db_type,
            "documents": filtered_documents,
            "total": len(filtered_documents),
        }

    except Exception as e:
        logger.error(f"Error listing documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
