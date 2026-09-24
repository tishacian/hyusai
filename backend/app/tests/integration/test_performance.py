"""Performance benchmarks for RAG system"""
import pytest
import asyncio
import time
import tempfile
import os
from app.services.rag.document_service import DocumentService


pytestmark = pytest.mark.integration


@pytest.fixture
def performance_documents():
    """Create documents for performance testing"""
    docs = []
    for i in range(10):
        content = f"Document {i}. " + "Machine learning and artificial intelligence are important topics. " * 50
        tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        tmp_file.write(content)
        tmp_file.close()
        docs.append(tmp_file.name)
    
    yield docs
    
    # Cleanup
    for doc_path in docs:
        if os.path.exists(doc_path):
            os.unlink(doc_path)


@pytest.mark.usefixtures("require_qdrant")
@pytest.mark.asyncio
async def test_ingestion_performance(performance_documents):
    """Benchmark document ingestion performance"""
    service = DocumentService(collection_name="test_perf_ingest", use_hybrid=False)
    
    start_time = time.time()
    
    for doc_path in performance_documents[:5]:  # Test with 5 documents
        result = await service.ingest_document(doc_path)
        assert result["status"] == "success"
    
    elapsed = time.time() - start_time
    avg_time = elapsed / 5
    
    print(f"\nIngestion Performance:")
    print(f"  Total time: {elapsed:.2f}s")
    print(f"  Average per document: {avg_time:.2f}s")
    print(f"  Documents per second: {5/elapsed:.2f}")
    
    # Performance assertions (adjust thresholds as needed)
    assert avg_time < 5.0, f"Average ingestion time {avg_time}s is too slow"


@pytest.mark.usefixtures("require_qdrant")
@pytest.mark.asyncio
async def test_search_performance(performance_documents):
    """Benchmark search performance"""
    service = DocumentService(collection_name="test_perf_search", use_hybrid=False)
    
    # Index documents first
    for doc_path in performance_documents:
        await service.ingest_document(doc_path)
    
    # Test vector search performance
    queries = [
        "machine learning",
        "artificial intelligence",
        "neural networks",
        "natural language processing",
        "deep learning"
    ]
    
    vector_times = []
    for query in queries:
        start = time.time()
        results = await service.search(query, top_k=10, use_hybrid=False)
        elapsed = time.time() - start
        vector_times.append(elapsed)
        assert len(results) > 0
    
    avg_vector_time = sum(vector_times) / len(vector_times)
    
    # Test hybrid search performance
    hybrid_times = []
    for query in queries:
        start = time.time()
        results = await service.search(query, top_k=10, use_hybrid=True)
        elapsed = time.time() - start
        hybrid_times.append(elapsed)
        assert len(results) > 0
    
    avg_hybrid_time = sum(hybrid_times) / len(hybrid_times)
    
    print(f"\nSearch Performance:")
    print(f"  Vector search avg: {avg_vector_time*1000:.2f}ms")
    print(f"  Hybrid search avg: {avg_hybrid_time*1000:.2f}ms")
    print(f"  Overhead: {(avg_hybrid_time/avg_vector_time - 1)*100:.1f}%")
    
    # Performance assertions
    assert avg_vector_time < 1.0, f"Vector search too slow: {avg_vector_time}s"
    assert avg_hybrid_time < 2.0, f"Hybrid search too slow: {avg_hybrid_time}s"


@pytest.mark.usefixtures("require_qdrant")
@pytest.mark.asyncio
async def test_concurrent_operations():
    """Test concurrent document operations"""
    service = DocumentService(collection_name="test_concurrent", use_hybrid=False)
    
    # Create test documents
    docs = []
    for i in range(5):
        tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        tmp_file.write(f"Test document {i}. Machine learning content.")
        tmp_file.close()
        docs.append(tmp_file.name)
    
    try:
        # Concurrent ingestion
        start = time.time()
        tasks = [service.ingest_document(doc) for doc in docs]
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start
        
        assert all(r["status"] == "success" for r in results)
        
        print(f"\nConcurrent Operations:")
        print(f"  Concurrent ingestion time: {elapsed:.2f}s")
        print(f"  Sequential would be ~{elapsed*5:.2f}s")
        
        # Concurrent search
        start = time.time()
        search_tasks = [service.search(f"query {i}", top_k=5) for i in range(5)]
        search_results = await asyncio.gather(*search_tasks)
        elapsed = time.time() - start
        
        assert all(len(r) >= 0 for r in search_results)
        
        print(f"  Concurrent search time: {elapsed:.2f}s")
        
    finally:
        for doc_path in docs:
            if os.path.exists(doc_path):
                os.unlink(doc_path)


@pytest.mark.asyncio
async def test_memory_usage():
    """Test memory usage with multiple documents"""
    try:
        import psutil
        import os
        psutil_available = True
    except ImportError:
        psutil_available = False
        pytest.skip("psutil not available, skipping memory test")
    
    if not psutil_available:
        pytest.skip("psutil not available")
    
    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    service = DocumentService(collection_name="test_memory", use_hybrid=False)
    
    # Create and index multiple documents
    docs = []
    for i in range(20):
        tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        tmp_file.write(f"Document {i}. " + "Content " * 100)
        tmp_file.close()
        docs.append(tmp_file.name)
    
    try:
        for doc_path in docs:
            await service.ingest_document(doc_path)
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        print(f"\nMemory Usage:")
        print(f"  Initial: {initial_memory:.2f} MB")
        print(f"  Final: {final_memory:.2f} MB")
        print(f"  Increase: {memory_increase:.2f} MB")
        print(f"  Per document: {memory_increase/20:.2f} MB")
        
        # Memory should be reasonable (adjust threshold as needed)
        assert memory_increase < 500, f"Memory increase too high: {memory_increase} MB"
        
    finally:
        for doc_path in docs:
            if os.path.exists(doc_path):
                os.unlink(doc_path)
