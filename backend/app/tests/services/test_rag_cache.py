from __future__ import annotations

from app.services.rag.cache import RAGCache


def test_rag_cache_namespace_prevents_cross_collection_hits():
    cache = RAGCache()

    cache.set(
        "signaux cabinet",
        6,
        [{"id": "news", "content": "news result"}],
        use_hybrid=True,
        namespace="sentinel-ci:qdrant:sentinel-ci-open-intelligence",
    )

    assert cache.get(
        "signaux cabinet",
        6,
        use_hybrid=True,
        namespace="sentinel-ci:qdrant:sentinel-ci-open-intelligence",
    ) == [{"id": "news", "content": "news result"}]

    assert cache.get(
        "signaux cabinet",
        6,
        use_hybrid=True,
        namespace="sentinel-ci:qdrant:sentinel-ci-visual-intelligence",
    ) is None

