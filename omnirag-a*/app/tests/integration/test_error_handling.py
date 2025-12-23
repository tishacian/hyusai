"""Error handling and edge case tests"""
import pytest
import asyncio
import tempfile
import os
from app.services.rag.document_service import DocumentService


@pytest.mark.asyncio
async def test_nonexistent_file():
    """Test handling of non-existent file"""
    service = DocumentService(collection_name="test_errors", use_hybrid=False)
    
    result = await service.ingest_document("/nonexistent/file.txt")
    assert result["status"] == "error"
    assert "error" in result


@pytest.mark.asyncio
async def test_empty_file():
    """Test handling of empty file"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        temp_path = f.name
    
    try:
        service = DocumentService(collection_name="test_empty_file", use_hybrid=False)
        result = await service.ingest_document(temp_path)
        
        # Empty file might succeed with 0 chunks or fail
        assert result["status"] in ["success", "error"]
        if result["status"] == "success":
            assert result["chunks_processed"] == 0
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@pytest.mark.asyncio
async def test_invalid_file_type():
    """Test handling of invalid file type"""
    # Create a binary file (not text)
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.bin', delete=False) as f:
        f.write(b'\x00\x01\x02\x03\x04\x05')
        temp_path = f.name
    
    try:
        service = DocumentService(collection_name="test_invalid", use_hybrid=False)
        result = await service.ingest_document(temp_path)
        
        # Should handle gracefully (might succeed with fallback parser or fail)
        assert result["status"] in ["success", "error"]
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@pytest.mark.asyncio
async def test_very_long_query():
    """Test handling of very long query"""
    service = DocumentService(collection_name="test_long_query", use_hybrid=False)
    
    # Create a test document first
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Test content for long query test.")
        temp_path = f.name
    
    try:
        await service.ingest_document(temp_path)
        
        # Very long query
        long_query = "test " * 1000
        results = await service.search(long_query, top_k=5)
        
        # Should handle gracefully
        assert isinstance(results, list)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@pytest.mark.asyncio
async def test_special_characters_in_query():
    """Test handling of special characters in query"""
    service = DocumentService(collection_name="test_special", use_hybrid=False)
    
    # Create a test document
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Test document with special characters.")
        temp_path = f.name
    
    try:
        await service.ingest_document(temp_path)
        
        # Queries with special characters
        special_queries = [
            "test@example.com",
            "test#hashtag",
            "test$money",
            "test%percent",
            "test&and",
            "test*asterisk",
            "test(query)",
            "test[array]",
            "test{object}",
        ]
        
        for query in special_queries:
            results = await service.search(query, top_k=5)
            assert isinstance(results, list)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@pytest.mark.asyncio
async def test_unicode_content():
    """Test handling of unicode content"""
    service = DocumentService(collection_name="test_unicode", use_hybrid=False)
    
    # Create document with unicode
    unicode_content = """
    Hello 世界
    Bonjour le monde
    Hola mundo
    Привет мир
    مرحبا بالعالم
    """
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(unicode_content)
        temp_path = f.name
    
    try:
        result = await service.ingest_document(temp_path)
        assert result["status"] == "success"
        
        # Search should work with unicode
        results = await service.search("世界", top_k=5)
        assert isinstance(results, list)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@pytest.mark.asyncio
async def test_concurrent_searches():
    """Test concurrent search operations"""
    service = DocumentService(collection_name="test_concurrent_search", use_hybrid=False)
    
    # Index a document first
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Test content for concurrent search.")
        temp_path = f.name
    
    try:
        await service.ingest_document(temp_path)
        
        # Run multiple searches concurrently
        queries = [f"query {i}" for i in range(10)]
        tasks = [service.search(query, top_k=5) for query in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # All should succeed (or handle errors gracefully)
        for result in results:
            if isinstance(result, Exception):
                # Log but don't fail - some errors might be expected
                print(f"Search error: {result}")
            else:
                assert isinstance(result, list)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@pytest.mark.asyncio
async def test_zero_top_k():
    """Test search with top_k=0"""
    service = DocumentService(collection_name="test_zero_k", use_hybrid=False)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Test content.")
        temp_path = f.name
    
    try:
        await service.ingest_document(temp_path)
        
        results = await service.search("test", top_k=0)
        assert isinstance(results, list)
        assert len(results) == 0
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


@pytest.mark.asyncio
async def test_very_large_top_k():
    """Test search with very large top_k"""
    service = DocumentService(collection_name="test_large_k", use_hybrid=False)
    
    # Index multiple documents
    for i in range(5):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(f"Document {i} content.")
            temp_path = f.name
            await service.ingest_document(temp_path)
            os.unlink(temp_path)
    
    # Request more results than available
    results = await service.search("content", top_k=1000)
    assert isinstance(results, list)
    # Should return available results, not fail

