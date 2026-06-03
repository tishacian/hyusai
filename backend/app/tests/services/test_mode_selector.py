from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.rag.mode_selector import resolve_retrieval_mode


class CountService:
    def __init__(self, count: int | None):
        self.count = count

    async def get_document_count(self) -> int:
        if self.count is None:
            raise RuntimeError("count unavailable")
        return self.count


@pytest.mark.asyncio
async def test_mode_selector_count_unknown_fails_closed_for_interactive_hybrid():
    use_hybrid, label, reason = await resolve_retrieval_mode(
        CountService(None),
        "question",
        "hybrid",
        latency_profile="fast",
    )

    assert use_hybrid is False
    assert label == "vector_only_count_unknown"
    assert "Vector count unavailable" in reason


@pytest.mark.asyncio
async def test_mode_selector_dense_quick_chah_is_bounded_vector_only():
    use_hybrid, label, reason = await resolve_retrieval_mode(
        CountService(settings.rag_dense_chunk_threshold + 1),
        "question",
        "chah",
        latency_profile="fast",
    )

    assert use_hybrid is False
    assert label == "fast_scoped_dense"
    assert "Dense corpus policy" in reason


@pytest.mark.asyncio
async def test_mode_selector_deep_chah_stays_chah_backend_on_dense_collection(monkeypatch):
    monkeypatch.setattr(settings, "rag_hah_chah_enabled", True)

    use_hybrid, label, reason = await resolve_retrieval_mode(
        CountService(settings.rag_dense_chunk_threshold + 1),
        "question",
        "chah",
        latency_profile="deep",
    )

    assert use_hybrid is True
    assert label == "chah_backend"
    assert "C-HAH backend pipeline" in reason


@pytest.mark.asyncio
async def test_mode_selector_deep_chah_not_downgraded_when_count_unknown(monkeypatch):
    monkeypatch.setattr(settings, "rag_hah_chah_enabled", True)

    use_hybrid, label, reason = await resolve_retrieval_mode(
        CountService(None),
        "question",
        "chah",
        latency_profile="deep",
    )

    assert use_hybrid is True
    assert label == "chah_backend"
    assert "C-HAH backend pipeline" in reason
