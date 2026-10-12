from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.industrial_answer_profile import is_multi_hop_query
from app.services.rag.mode_selector import AUTO_CHAH_LABEL, resolve_retrieval_mode


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


@pytest.mark.asyncio
async def test_mode_selector_auto_deep_multi_hop_runs_chah(monkeypatch):
    monkeypatch.setattr(settings, "rag_hah_chah_enabled", True)
    query = "Which machines also use the same drive as line 3, then how many are installed?"
    assert is_multi_hop_query(query)

    use_hybrid, label, reason = await resolve_retrieval_mode(
        CountService(1000),
        query,
        "auto",
        latency_profile="deep",
        multi_hop=is_multi_hop_query(query),
    )

    assert use_hybrid is True
    assert label == AUTO_CHAH_LABEL
    assert "multi-hop" in reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "multi_hop", "chah_enabled"),
    [("balanced", True, True), ("deep", False, True), ("deep", True, False)],
)
async def test_mode_selector_auto_stays_hybrid_without_deep_multi_hop(
    monkeypatch, profile, multi_hop, chah_enabled
):
    monkeypatch.setattr(settings, "rag_hah_chah_enabled", chah_enabled)

    _, label, _ = await resolve_retrieval_mode(
        CountService(1000),
        "question",
        "auto",
        latency_profile=profile,
        multi_hop=multi_hop,
    )

    assert label == "hybrid_rrf (auto)"


def test_single_hop_question_is_not_multi_hop():
    assert not is_multi_hop_query("What is the rated power of pump P-101?")
