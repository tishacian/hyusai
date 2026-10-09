import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from app.services.embedding import embedder as embedder_module
from app.services.embedding.embedder import (
    Embedder,
    EmbeddingUnavailable,
    capture_embedding_provider_usage,
)
from app.services.evaluation.judge import provider_usage_evidence


class FakeEmbeddings:
    def __init__(
        self,
        *,
        fail_above: int | None = None,
        always_fail: bool = False,
        report_usage: bool = False,
    ):
        self.calls: list[list[str]] = []
        self.fail_above = fail_above
        self.always_fail = always_fail
        self.report_usage = report_usage

    def create(self, *, input: list[str], model: str):
        self.calls.append(list(input))
        if self.always_fail or (self.fail_above is not None and len(input) > self.fail_above):
            raise RuntimeError("embedding request too large")
        response = {
            "data": [
                SimpleNamespace(index=index, embedding=[float(len(text)), float(index), 1.0])
                for index, text in enumerate(input)
            ]
        }
        if self.report_usage:
            response["usage"] = SimpleNamespace(
                prompt_tokens=len(input),
                total_tokens=len(input),
            )
        return SimpleNamespace(**response)


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
    monkeypatch.setattr(embedder_module, "_OPENAI_EMBEDDING_MAX_BATCH_ESTIMATED_TOKENS", 1000)
    fake_embeddings = FakeEmbeddings()
    embedder = make_embedder(fake_embeddings)

    result = await embedder.embed_batch(["one", "two", "three", "four", "five"])

    assert [len(call) for call in fake_embeddings.calls] == [2, 2, 1]
    assert result.shape == (5, 3)


@pytest.mark.asyncio
async def test_openai_embed_retries_smaller_batches_without_changing_model(monkeypatch):
    monkeypatch.setattr(embedder_module, "_OPENAI_EMBEDDING_MAX_BATCH_INPUTS", 10)
    monkeypatch.setattr(embedder_module, "_OPENAI_EMBEDDING_MAX_BATCH_ESTIMATED_TOKENS", 1000)
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
async def test_openai_embed_failed_input_does_not_change_vector_space():
    fake_embeddings = FakeEmbeddings(always_fail=True)
    embedder = make_embedder(fake_embeddings)

    with pytest.raises(EmbeddingUnavailable):
        await embedder.embed_batch(["alpha"])
    assert [len(call) for call in fake_embeddings.calls] == [1]


@pytest.mark.asyncio
async def test_openai_embed_captures_native_usage_for_every_batch(monkeypatch):
    monkeypatch.setattr(embedder_module, "_OPENAI_EMBEDDING_MAX_BATCH_INPUTS", 2)
    fake_embeddings = FakeEmbeddings(report_usage=True)
    embedder = make_embedder(fake_embeddings)

    with capture_embedding_provider_usage() as accumulator:
        await embedder.embed_batch(["one", "two", "three"])

    evidence = provider_usage_evidence(accumulator)
    assert evidence["usage"]["total_tokens"] == 3
    assert evidence["usage"]["prompt_tokens"] == 3
    assert evidence["usage"]["provider_calls"] == 2
    assert [call["total_tokens"] for call in evidence["usage"]["calls"]] == [2, 1]


@pytest.mark.asyncio
async def test_openai_embed_failed_split_attempt_keeps_coverage_partial(monkeypatch):
    monkeypatch.setattr(embedder_module, "_OPENAI_EMBEDDING_MAX_BATCH_INPUTS", 10)
    fake_embeddings = FakeEmbeddings(fail_above=1, report_usage=True)
    embedder = make_embedder(fake_embeddings)

    with capture_embedding_provider_usage() as accumulator:
        await embedder.embed_batch(["alpha", "beta", "gamma"])

    evidence = provider_usage_evidence(accumulator)["provider_usage"]
    assert evidence["measurement_coverage"] == "partial"
    assert evidence["provider_calls"] == 5
    assert evidence["reported_calls"] == 3
    assert evidence["unreported_calls"] == 2
    assert evidence["reported_total"] == 3


@pytest.mark.asyncio
async def test_openai_embed_response_without_usage_is_unavailable():
    embedder = make_embedder(FakeEmbeddings())

    with capture_embedding_provider_usage() as accumulator:
        await embedder.embed_batch(["alpha"])

    evidence = provider_usage_evidence(accumulator)["provider_usage"]
    assert evidence["measurement_coverage"] == "unavailable"
    assert evidence["provider_calls"] == 1
    assert evidence["unreported_calls"] == 1


@pytest.mark.asyncio
async def test_openai_embedding_usage_scopes_are_concurrency_isolated():
    embedder = make_embedder(FakeEmbeddings(report_usage=True))

    async def scoped(texts: list[str]) -> dict:
        with capture_embedding_provider_usage() as accumulator:
            await embedder.embed_batch(texts)
        return provider_usage_evidence(accumulator)["usage"]

    one, three = await asyncio.gather(
        scoped(["one"]),
        scoped(["one", "two", "three"]),
    )

    assert one["total_tokens"] == 1
    assert one["provider_calls"] == 1
    assert three["total_tokens"] == 3
    assert three["provider_calls"] == 1


@pytest.mark.asyncio
async def test_openai_sdk_internal_retries_are_explicit_unreported_attempts():
    response = SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[1.0, 0.0, 0.5])],
        usage=SimpleNamespace(prompt_tokens=1, total_tokens=1),
    )

    class RawResponse:
        http_request = SimpleNamespace(headers={"x-stainless-retry-count": "2"})

        @staticmethod
        def parse():
            return response

    class RawEmbeddings:
        with_raw_response = None

        def __init__(self):
            self.with_raw_response = self

        @staticmethod
        def create(*, input: list[str], model: str):
            return RawResponse()

    embedder = make_embedder(RawEmbeddings())

    with capture_embedding_provider_usage() as accumulator:
        await embedder.embed_batch(["alpha"])

    evidence = provider_usage_evidence(accumulator)["provider_usage"]
    assert evidence["measurement_coverage"] == "partial"
    assert evidence["provider_calls"] == 3
    assert evidence["reported_calls"] == 1
    assert evidence["unreported_calls"] == 2
    assert evidence["reported_total"] == 1


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
async def test_provider_failure_never_emits_hash_vector():
    embedder = make_embedder(FakeEmbeddings(always_fail=True))
    embedder.provider = "openai"

    assert not embedder.is_degraded()
    with pytest.raises(EmbeddingUnavailable):
        await embedder.embed_batch(["alpha"])
    assert not embedder.is_degraded()
    assert embedder.describe()["provider"] == "openai"


def test_hash_provider_is_degraded_from_init():
    embedder = make_embedder(FakeEmbeddings())
    embedder.provider = "hash"

    assert embedder.is_degraded()
