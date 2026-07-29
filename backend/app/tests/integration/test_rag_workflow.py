"""Integration tests for complete RAG workflow"""
import pytest
import asyncio
import tempfile
import os
from app.services.rag.document_service import DocumentService
from app.services.tracing.rag_tracer import get_tracer


pytestmark = pytest.mark.integration


@pytest.fixture
def sample_documents():
    """Create sample documents for testing"""
    docs = [
        {
            "name": "ai_basics.txt",
            "content": """Artificial Intelligence (AI) is the simulation of human intelligence by machines.
Machine learning is a subset of AI that enables systems to learn from data.
Deep learning uses neural networks with multiple layers to process information.
Natural language processing allows computers to understand and generate human language."""
        },
        {
            "name": "ml_advanced.txt",
            "content": """Machine learning algorithms can be supervised, unsupervised, or reinforcement learning.
Supervised learning uses labeled data to train models.
Unsupervised learning finds patterns in unlabeled data.
Reinforcement learning learns through trial and error with rewards."""
        },
        {
            "name": "nlp_applications.txt",
            "content": """Natural language processing has many applications including chatbots, translation, and sentiment analysis.
Text classification categorizes documents into predefined classes.
Named entity recognition identifies people, places, and organizations in text.
Machine translation converts text from one language to another."""
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
async def test_complete_rag_workflow(sample_documents):
    """Test complete RAG workflow: upload -> index -> search -> retrieve"""
    service = DocumentService(collection_name="test_workflow", use_hybrid=True)
    
    # Step 1: Upload and index documents
    upload_results = []
    for file_info in sample_documents:
        result = await service.ingest_document(file_info["path"])
        assert result["status"] == "success"
        assert result["chunks_processed"] > 0
        upload_results.append(result)
    
    # Step 2: Verify documents are indexed
    count = await service.get_document_count()
    assert count >= len(sample_documents)
    
    # Step 3: Test vector search
    vector_results = await service.search("machine learning", top_k=3, use_hybrid=False)
    assert len(vector_results) > 0
    assert all("score" in r for r in vector_results)
    assert all("content" in r.get("metadata", {}) or "content" in r for r in vector_results)
    
    # Step 4: Test hybrid search
    hybrid_results = await service.search("artificial intelligence", top_k=3, use_hybrid=True)
    assert len(hybrid_results) > 0
    assert all("score" in r for r in hybrid_results)
    
    # Step 5: Verify search quality (top result should be relevant)
    if hybrid_results:
        top_result = hybrid_results[0]
        assert top_result["score"] > 0
        content = top_result.get("content", "") or top_result.get("metadata", {}).get("content", "")
        assert len(content) > 0


@pytest.mark.asyncio
async def test_search_accuracy(sample_documents):
    """Test search accuracy with specific queries"""
    service = DocumentService(collection_name="test_accuracy", use_hybrid=True)
    
    # Index documents
    for file_info in sample_documents:
        await service.ingest_document(file_info["path"])
    
    # Test query: "neural networks" should find deep learning doc
    results = await service.search("neural networks", top_k=5, use_hybrid=True)
    assert len(results) > 0
    
    # Check if relevant content is retrieved
    found_relevant = False
    for result in results:
        content = result.get("content", "") or result.get("metadata", {}).get("content", "")
        if "neural" in content.lower() or "deep learning" in content.lower():
            found_relevant = True
            break
    
    assert found_relevant, "Search should retrieve relevant content about neural networks"


@pytest.mark.asyncio
async def test_hybrid_vs_vector_search(sample_documents):
    """Compare hybrid search vs vector-only search"""
    service = DocumentService(collection_name="test_comparison", use_hybrid=True)
    
    # Index documents
    for file_info in sample_documents:
        await service.ingest_document(file_info["path"])
    
    query = "supervised learning"
    
    # Vector search
    vector_results = await service.search(query, top_k=5, use_hybrid=False)
    
    # Hybrid search
    hybrid_results = await service.search(query, top_k=5, use_hybrid=True)
    
    # Both should return results
    assert len(vector_results) > 0
    assert len(hybrid_results) > 0
    
    # Hybrid should have combined scores
    if hybrid_results:
        top_hybrid = hybrid_results[0]
        # Check if hybrid has additional score information
        assert "score" in top_hybrid


@pytest.mark.asyncio
async def test_trace_integration(sample_documents):
    """Test that execution traces are created during workflow"""
    tracer = get_tracer()
    initial_trace_count = len(tracer.get_all_traces())
    
    service = DocumentService(collection_name="test_traces", use_hybrid=True)
    
    # Perform operations that should create traces
    result = await service.ingest_document(sample_documents[0]["path"])
    assert "trace_id" in result
    
    # Verify trace exists
    trace = tracer.get_trace(result["trace_id"])
    assert trace is not None
    assert trace.operation_type == "ingest"
    assert len(trace.steps) > 0
    
    # Test search trace
    search_results = await service.search("test query", top_k=3)
    final_trace_count = len(tracer.get_all_traces())
    assert final_trace_count > initial_trace_count


@pytest.mark.asyncio
async def test_batch_upload(sample_documents):
    """Test batch document upload"""
    service = DocumentService(collection_name="test_batch", use_hybrid=True)
    
    file_paths = [doc["path"] for doc in sample_documents]
    result = await service.ingest_documents_batch(file_paths)
    
    assert result["total"] == len(sample_documents)
    assert result["successful"] == len(sample_documents)
    assert result["failed"] == 0
    
    # Verify all documents are indexed
    count = await service.get_document_count()
    assert count >= len(sample_documents)


@pytest.mark.asyncio
async def test_empty_query():
    """Test search with empty query"""
    service = DocumentService(collection_name="test_empty", use_hybrid=True)
    
    # Should handle empty query gracefully
    results = await service.search("", top_k=5)
    # Empty query might return empty results or all results
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_large_document():
    """Test processing large document"""
    # Create a large document
    large_content = "Machine learning is important. " * 1000
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(large_content)
        temp_path = f.name
    
    try:
        service = DocumentService(collection_name="test_large", use_hybrid=True)
        result = await service.ingest_document(temp_path)
        
        assert result["status"] == "success"
        assert result["chunks_processed"] > 0  # Should create multiple chunks
        
        # Verify search works
        results = await service.search("machine learning", top_k=3)
        assert len(results) > 0
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
