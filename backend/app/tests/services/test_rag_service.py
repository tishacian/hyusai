"""Tests for RAG service"""
import pytest
import asyncio
import tempfile
import os
from app.services.rag.document_service import DocumentService


@pytest.fixture
def sample_text_file():
    """Create a sample text file for testing"""
    content = """Machine learning is a subset of artificial intelligence.
It involves training algorithms on data to make predictions.
Deep learning uses neural networks with multiple layers.
Natural language processing helps computers understand human language."""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(content)
        temp_path = f.name
    
    yield temp_path
    
    # Cleanup
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.mark.asyncio
async def test_document_ingestion(sample_text_file):
    """Test document ingestion"""
    service = DocumentService(collection_name="test_collection")
    result = await service.ingest_document(sample_text_file)
    
    assert result["status"] == "success"
    assert "document_id" in result
    assert result["chunks_processed"] > 0


@pytest.mark.asyncio
async def test_document_search(sample_text_file):
    """Test document search"""
    service = DocumentService(collection_name="test_collection")
    
    # First ingest document
    await service.ingest_document(sample_text_file)
    
    # Then search
    results = await service.search("machine learning", top_k=5)
    
    assert len(results) > 0
    assert "id" in results[0]
    assert "score" in results[0]
    assert "metadata" in results[0]


@pytest.mark.asyncio
async def test_list_documents_normalizes_chunk_count_fields():
    """Document listings expose the singular field used by the Knowledge UI."""

    class FakeVectorDb:
        async def list_documents(self):
            return [
                {"document_id": "doc-1", "filename": "one.md", "document_type": "markdown"},
                {"document_id": "doc-2", "filename": "two.md", "chunks_count": 1},
            ]

        async def get_by_document_id(self, document_id):
            return ["a", "b", "c"] if document_id == "doc-1" else ["z"]

    service = object.__new__(DocumentService)
    service.vector_db = FakeVectorDb()

    documents = await service.list_documents()

    assert documents[0]["chunk_count"] == 3
    assert documents[0]["chunks_count"] == 3
    assert documents[1]["chunk_count"] == 1
    assert documents[1]["chunks_count"] == 1
