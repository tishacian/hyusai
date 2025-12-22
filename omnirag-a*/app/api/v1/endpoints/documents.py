"""Document management endpoints for RAG"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.core.logging import get_logger
from app.db.base import get_db
from app.models.document import Document, Chunk
from app.services.vector_store import VectorStore
from datetime import datetime
import uuid

logger = get_logger(__name__)
router = APIRouter()
vector_store = VectorStore()


class DocumentCreate(BaseModel):
    """Document creation request"""
    title: str
    content: str
    content_type: str = "text"
    source: Optional[str] = None
    source_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}


class DocumentResponse(BaseModel):
    """Document response"""
    id: str
    title: str
    content: str
    content_type: str
    source: Optional[str]
    source_url: Optional[str]
    created_at: datetime


@router.post("")
async def create_document(
    document: DocumentCreate,
    db: Session = Depends(get_db)
):
    """Create and index a document"""
    try:
        # Create document in database
        db_document = Document(
            id=str(uuid.uuid4()),
            title=document.title,
            content=document.content,
            content_type=document.content_type,
            source=document.source,
            source_url=document.source_url,
            meta_data=document.metadata or {}
        )
        db.add(db_document)
        db.commit()
        db.refresh(db_document)
        
        # Add to vector store
        await vector_store.add_documents([{
            "id": db_document.id,
            "content": document.content,
            "metadata": {
                "title": document.title,
                "content_type": document.content_type,
                "source": document.source,
                "source_url": document.source_url,
                **document.metadata
            }
        }])
        
        # Update indexed_at
        db_document.indexed_at = datetime.utcnow()
        db.commit()
        
        return DocumentResponse(
            id=db_document.id,
            title=db_document.title,
            content=db_document.content,
            content_type=db_document.content_type,
            source=db_document.source,
            source_url=db_document.source_url,
            created_at=db_document.created_at
        )
    except Exception as e:
        logger.error("Failed to create document", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_documents(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """List documents"""
    try:
        documents = db.query(Document).offset(skip).limit(limit).all()
        return {
            "documents": [
                {
                    "id": doc.id,
                    "title": doc.title,
                    "content_type": doc.content_type,
                    "source": doc.source,
                    "created_at": doc.created_at.isoformat() if doc.created_at else None
                }
                for doc in documents
            ],
            "total": db.query(Document).count()
        }
    except Exception as e:
        logger.error("Failed to list documents", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    db: Session = Depends(get_db)
):
    """Get a document by ID"""
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        return DocumentResponse(
            id=document.id,
            title=document.title,
            content=document.content,
            content_type=document.content_type,
            source=document.source,
            source_url=document.source_url,
            created_at=document.created_at
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get document", document_id=document_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    db: Session = Depends(get_db)
):
    """Delete a document"""
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Delete from vector store
        await vector_store.delete_document(document_id)
        
        # Delete from database
        db.delete(document)
        db.commit()
        
        return {"message": "Document deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete document", document_id=document_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{document_id}/index")
async def index_document(
    document_id: str,
    db: Session = Depends(get_db)
):
    """Re-index a document"""
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # Add to vector store
        await vector_store.add_documents([{
            "id": document.id,
            "content": document.content,
            "metadata": {
                "title": document.title,
                "content_type": document.content_type,
                "source": document.source,
                "source_url": document.source_url,
                **(document.meta_data or {})
            }
        }])
        
        # Update indexed_at
        document.indexed_at = datetime.utcnow()
        db.commit()
        
        return {"message": "Document indexed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to index document", document_id=document_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_documents(
    query: str,
    top_k: int = 5
):
    """Search documents"""
    try:
        results = await vector_store.search(query, top_k=top_k)
        return {
            "query": query,
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        logger.error("Failed to search documents", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

