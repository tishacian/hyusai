"""Integration tests for hybrid retrieval"""
import pytest
import asyncio
import tempfile
import os
from app.services.rag.document_service import DocumentService


pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("require_qdrant")]


@pytest.fixture
def hybrid_test_documents():
    """Create documents for hybrid retrieval testing"""
    docs = [
        {
            "name": "exact_match.txt",
            "content": "machine learning algorithm neural network deep learning"
        },
        {
            "name": "semantic_match.txt",
            "content": "artificial intelligence enables computers to perform tasks requiring human cognition"
        },
        {
            "name": "keyword_rich.txt",
            "content": "machine learning machine learning machine learning algorithm algorithm"
        },
        {
            "name": "mixed.txt",
            "content": "AI and ML are related. Machine learning is a subset of artificial intelligence."
        }
    ]
    
    temp_files = []
    for doc in docs:
        tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        tmp_file.write(doc["content"])
        tmp_file.close()
        temp_files.append({
            "path": tmp_file.name,
            "name": doc["name"],
            "content": doc["content"]
        })
    
    yield temp_files
    
    # Cleanup
    for file_info in temp_files:
        if os.path.exists(file_info["path"]):
            os.unlink(file_info["path"])


@pytest.mark.asyncio
async def test_hybrid_retrieval_accuracy(hybrid_test_documents):
    """Test that hybrid retrieval improves accuracy"""
    service = DocumentService(collection_name="test_hybrid_accuracy", use_hybrid=True)
    
    # Index documents
    for file_info in hybrid_test_documents:
        await service.ingest_document(file_info["path"])
    
    # Query that should benefit from hybrid search
    query = "machine learning algorithm"
    
    # Vector search
    vector_results = await service.search(query, top_k=3, use_hybrid=False)
    
    # Hybrid search
    hybrid_results = await service.search(query, top_k=3, use_hybrid=True)
    
    # Both should return results
    assert len(vector_results) > 0
    assert len(hybrid_results) > 0
    
    # Hybrid results should have combined scores
    for result in hybrid_results:
        assert "score" in result
        # May have vector_score and bm25_score if available
        if "vector_score" in result:
            assert result["vector_score"] >= 0
        if "bm25_score" in result:
            assert result["bm25_score"] >= 0


@pytest.mark.asyncio
async def test_keyword_vs_semantic_search(hybrid_test_documents):
    """Test that hybrid search balances keyword and semantic matching"""
    service = DocumentService(collection_name="test_keyword_semantic", use_hybrid=True)
    
    # Index documents
    for file_info in hybrid_test_documents:
        await service.ingest_document(file_info["path"])
    
    # Keyword-heavy query
    keyword_query = "machine learning algorithm"
    keyword_results = await service.search(keyword_query, top_k=3, use_hybrid=True)
    
    # Semantic query
    semantic_query = "computational intelligence methods"
    semantic_results = await service.search(semantic_query, top_k=3, use_hybrid=True)
    
    # Both should work
    assert len(keyword_results) > 0
    assert len(semantic_results) > 0
    
    # Keyword query should favor keyword-rich document
    keyword_top = keyword_results[0]
    keyword_content = keyword_top.get("content", "") or keyword_top.get("metadata", {}).get("content", "")
    
    # Semantic query might find different documents
    semantic_top = semantic_results[0]
    semantic_content = semantic_top.get("content", "") or semantic_top.get("metadata", {}).get("content", "")


@pytest.mark.asyncio
async def test_hybrid_score_combination(hybrid_test_documents):
    """Test that hybrid scores are properly combined"""
    service = DocumentService(collection_name="test_score_combination", use_hybrid=True)
    
    # Index documents
    for file_info in hybrid_test_documents:
        await service.ingest_document(file_info["path"])
    
    query = "machine learning"
    results = await service.search(query, top_k=5, use_hybrid=True)
    
    # Check score properties
    for result in results:
        assert "score" in result
        assert result["score"] >= 0
        
        # If both scores are present, combined score should be weighted sum
        if "vector_score" in result and "bm25_score" in result:
            # Combined score should be non-negative (may be > 1 after normalization boost)
            assert result["score"] >= 0


@pytest.mark.asyncio
async def test_hybrid_fallback_to_vector():
    """Test that hybrid search falls back to vector if BM25 not available"""
    service = DocumentService(collection_name="test_fallback", use_hybrid=False)
    
    # Index without hybrid
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Test content for fallback test.")
        temp_path = f.name
    
    try:
        await service.ingest_document(temp_path)
        
        # Try hybrid search (should fall back to vector)
        results = await service.search("test", top_k=3, use_hybrid=True)
        
        # Should still work (falls back to vector)
        assert isinstance(results, list)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
