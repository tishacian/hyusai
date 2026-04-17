"""Document management endpoints"""

import os
import shutil
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.auth import get_current_workspace
from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_manager import get_app_settings
from app.models.workspace import Workspace
from app.services.rag.document_service import DocumentService

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


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    collection_name: str = Form("documents"),
    vector_db_type: Optional[str] = Form(None),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Upload and index a document"""
    try:
        app_settings = get_app_settings()
        db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)

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
):
    """Upload and index multiple documents"""
    app_settings = get_app_settings()
    db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)

    temp_files = []

    try:
        file_paths = []
        for file in files:
            tmp_file = tempfile.NamedTemporaryFile(
                delete=False, suffix=os.path.splitext(file.filename)[1]
            )
            shutil.copyfileobj(file.file, tmp_file)
            tmp_file.close()
            temp_files.append(tmp_file.name)
            file_paths.append(tmp_file.name)

        doc_service = DocumentService(
            collection_name=collection_name,
            vector_db_type=db_type,
            workspace_slug=workspace.slug,
        )
        result = await doc_service.ingest_documents_batch(file_paths)

        return {
            "status": "success",
            "total": result["total"],
            "successful": result["successful"],
            "failed": result["failed"],
        }

    except Exception as e:
        logger.error(f"Error uploading documents batch: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Clean up temp files
        for tmp_path in temp_files:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


@router.post("/search")
async def search_documents(
    request: DocumentSearchRequest,
    workspace: Workspace = Depends(get_current_workspace),
):
    """Search documents"""
    try:
        app_settings = get_app_settings()
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
        doc_service = DocumentService(collection_name=collection_name, workspace_slug=workspace.slug)
        count = await doc_service.get_document_count()

        # Get cache stats if available
        cache_stats = None
        if doc_service.cache:
            cache_stats = doc_service.cache.get_stats()

        vector_dim = getattr(doc_service.vector_db, "dimension", None)

        return {
            "collection_name": collection_name,
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
        app_settings = get_app_settings()
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
        app_settings = get_app_settings()
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
):
    """List collections for the current workspace."""
    try:
        from app.services.vector_db.factory import VectorDBFactory

        app_settings = get_app_settings()
        db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)

        collection_names = VectorDBFactory.list_collections_for_workspace(
            db_type=db_type, workspace_slug=workspace.slug
        )
        collection_names = [name for name in collection_names if not name.startswith("_")]

        return {
            "collections": collection_names if collection_names else [],
            "default": collection_names[0] if collection_names else None,
            "vector_db_type": db_type,
        }

    except Exception as e:
        logger.error(f"Error listing collections: {e}", exc_info=True)
        # Return empty list on error, let frontend handle it
        return {
            "collections": [],
            "default": None,
            "vector_db_type": vector_db_type or settings.default_vector_db_type,
        }


@router.post("/collections")
async def create_collection(
    collection_name: str = Query(...),
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Create a new collection in the current workspace."""
    try:
        from app.services.vector_db.factory import VectorDBFactory

        app_settings = get_app_settings()
        db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)

        scoped = VectorDBFactory.scoped_name(collection_name, workspace.slug)
        existing_collections = VectorDBFactory.list_collections(db_type=db_type)
        if scoped in existing_collections:
            logger.info(f"Collection '{collection_name}' already exists in workspace {workspace.slug}")
            return {
                "status": "success",
                "collection_name": collection_name,
                "vector_db_type": db_type,
                "total_chunks": 0,
                "message": "Collection already exists",
            }

        vector_db = VectorDBFactory.get_db(collection_name, db_type=db_type, workspace_slug=workspace.slug)

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

        updated_collections = VectorDBFactory.list_collections_for_workspace(
            db_type=db_type, workspace_slug=workspace.slug
        )
        if collection_name not in updated_collections:
            logger.warning(f"Collection '{collection_name}' created but not found in listings")

        return {
            "status": "success",
            "collection_name": collection_name,
            "vector_db_type": db_type,
            "total_chunks": count,
            "collections": updated_collections,
        }

    except Exception as e:
        logger.error(f"Error creating collection: {e}", exc_info=True)
        error_msg = str(e)
        # Provide more helpful error messages
        if "already exists" in error_msg.lower() or "different settings" in error_msg.lower():
            raise HTTPException(
                status_code=409,
                detail=f"Collection '{collection_name}' already exists or there's a conflict. Please try a different name or clear existing collections.",
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/collections/{collection_name}")
async def delete_collection(
    collection_name: str,
    vector_db_type: Optional[str] = Query(None),
    workspace: Workspace = Depends(get_current_workspace),
):
    """Delete a collection in the current workspace."""
    try:
        from urllib.parse import unquote

        from app.services.vector_db.factory import VectorDBFactory

        collection_name = unquote(collection_name)

        app_settings = get_app_settings()
        db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)

        scoped_coll = VectorDBFactory.scoped_name(collection_name, workspace.slug)
        collections = VectorDBFactory.list_collections(db_type=db_type)
        collection_exists = scoped_coll in collections

        if not collection_exists:
            raise HTTPException(
                status_code=404, detail=f"Collection '{collection_name}' not found in {db_type}"
            )

        try:
            vector_db = VectorDBFactory.get_db(
                collection_name, db_type=db_type, workspace_slug=workspace.slug
            )
            await vector_db.clear_collection()
        except Exception as e:
            logger.warning(f"Error clearing collection before deletion: {e}")

        try:
            VectorDBFactory.clear_instance(
                collection_name, db_type=db_type, workspace_slug=workspace.slug
            )
        except Exception as cache_error:
            logger.warning(f"Could not clear cached instance: {cache_error}")

        try:
            if db_type == "chroma":
                import chromadb

                from app.core.config import settings

                client = chromadb.PersistentClient(path=settings.chroma_persist_directory)
                client.delete_collection(name=scoped_coll)
            elif db_type == "faiss":
                import os

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

            logger.info(f"Successfully deleted collection: {collection_name} (type: {db_type})")
            return {
                "status": "success",
                "message": f"Collection '{collection_name}' deleted successfully",
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
        app_settings = get_app_settings()
        db_type = vector_db_type or app_settings.get("ragVectorDBType", settings.default_vector_db_type)

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
