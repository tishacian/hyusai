from types import SimpleNamespace

import numpy as np
import pytest

from app.services.embedding import embedder as embedder_module
from app.services.embedding.embedder import Embedder


class FakeEmbeddings:
    def __init__(self, *, fail_above: int | None = None, always_fail: bool = False):
        self.calls: list[list[str]] = []
        self.fail_above = fail_above
        self.always_fail = always_fail

    def create(self, *, input: list[str], model: str):
        self.calls.append(list(input))
        if self.always_fail or (
            self.fail_above is not None and len(input) > self.fail_above
        ):
            raise RuntimeError("embedding request too large")
        return SimpleNamespace(
            data=[
                SimpleNamespace(
                    index=index, embedding=[float(len(text)), float(index), 1.0]
                )
                for index, text in enumerate(input)
            ]
        )


def make_embedder(fake_embeddings: FakeEmbeddings) -> Embedder:
    embedder = Embedder.__new__(Embedder)
    embedder.model_name = "text-embedding-3-small"
    embedder._client = SimpleNamespace(embeddings=fake_embeddings)
    embedder._local_model = None
    embedder._dimension = 3
    return embedder


@pytest.mark.asyncio
async def test_openai_embed_splits_large_batches_by_count(monkeypatch):
    monkeypatch.setattr(embedder_module, "_OPENAI_EMBEDDING_MAX_BATCH_INPUTS", 2)
    monkeypatch.setattr(
        embedder_module, "_OPENAI_EMBEDDING_MAX_BATCH_ESTIMATED_TOKENS", 1000
    )
    fake_embeddings = FakeEmbeddings()
    embedder = make_embedder(fake_embeddings)

    result = await embedder.embed_batch(["one", "two", "three", "four", "five"])

    assert [len(call) for call in fake_embeddings.calls] == [2, 2, 1]
    assert result.shape == (5, 3)


@pytest.mark.asyncio
async def test_openai_embed_retries_failed_batch_before_fallback(monkeypatch):
    monkeypatch.setattr(embedder_module, "_OPENAI_EMBEDDING_MAX_BATCH_INPUTS", 10)
    monkeypatch.setattr(
        embedder_module, "_OPENAI_EMBEDDING_MAX_BATCH_ESTIMATED_TOKENS", 1000
    )
    fake_embeddings = FakeEmbeddings(fail_above=1)
    embedder = make_embedder(fake_embeddings)

    result = await embedder.embed_batch(["alpha", "beta", "gamma"])

    assert [len(call) for call in fake_embeddings.calls] == [3, 1, 2, 1, 1]
    assert np.array_equal(
        result,
        np.array(
            [
                [5.0, 0.0, 1.0],
                [4.0, 0.0, 1.0],
                [5.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        ),
    )


@pytest.mark.asyncio
async def test_openai_embed_fallback_is_limited_to_single_failed_input():
    fake_embeddings = FakeEmbeddings(always_fail=True)
    embedder = make_embedder(fake_embeddings)

    result = await embedder.embed_batch(["alpha"])

    assert [len(call) for call in fake_embeddings.calls] == [1]
    assert result.shape == (1, 3)
    assert np.isclose(np.linalg.norm(result[0]), 1.0)


def test_describe_reports_real_provider_and_dimension():
    embedder = make_embedder(FakeEmbeddings())
    embedder.provider = "openai"

    info = embedder.describe()

    assert info == {
        "provider": "openai",
        "model_name": "text-embedding-3-small",
        "dimension": 3,
        "degraded": False,
    }


@pytest.mark.asyncio
async def test_hash_fallback_marks_embedder_degraded():
    embedder = make_embedder(FakeEmbeddings(always_fail=True))
    embedder.provider = "openai"

    assert not embedder.is_degraded()
    await embedder.embed_batch(["alpha"])

    assert embedder.is_degraded()
    assert embedder.describe()["degraded"] is True


def test_hash_provider_is_degraded_from_init():
    embedder = make_embedder(FakeEmbeddings())
    embedder.provider = "hash"

    assert embedder.is_degraded()
