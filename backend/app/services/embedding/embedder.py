"""Embedding generation service -- OpenAI-first for demo."""

import asyncio
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.services.evaluation.judge import (
    new_provider_usage_accumulator,
    normalize_provider_usage,
)

logger = get_logger(__name__)

_OPENAI_EMBEDDING_MAX_BATCH_INPUTS = 256
_OPENAI_EMBEDDING_MAX_BATCH_ESTIMATED_TOKENS = 240_000
_OPENAI_USAGE_FIELDS = (
    "prompt_tokens",
    "input_tokens",
    "completion_tokens",
    "output_tokens",
    "total_tokens",
)
_EMBEDDING_PROVIDER_USAGE: ContextVar[dict[str, Any] | None] = ContextVar(
    "embedding_provider_usage",
    default=None,
)


@contextmanager
def capture_embedding_provider_usage() -> Iterator[dict[str, Any]]:
    """Capture real embedding-provider attempts in the current async context.

    The Embedder API intentionally keeps returning only vectors.  Retrieval can
    open this request-local scope around the complete pipeline and receive one
    provider-call ledger without putting mutable telemetry on the shared
    Embedder instance.  Child asyncio tasks inherit the scope; concurrent
    retrieval requests remain isolated by ``ContextVar``.
    """

    accumulator = new_provider_usage_accumulator()
    token = _EMBEDDING_PROVIDER_USAGE.set(accumulator)
    try:
        yield accumulator
    finally:
        _EMBEDDING_PROVIDER_USAGE.reset(token)


def _openai_usage_payload(response: Any) -> dict[str, Any] | None:
    """Project native OpenAI embedding usage without deriving any counter."""

    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, Mapping):
        raw = dict(usage)
    elif callable(getattr(usage, "model_dump", None)):
        raw = dict(usage.model_dump())
    elif callable(getattr(usage, "dict", None)):
        raw = dict(usage.dict())
    else:
        raw = {
            field: value
            for field in _OPENAI_USAGE_FIELDS
            if (value := getattr(usage, field, None)) is not None
        }
    counters = {
        field: raw[field]
        for field in _OPENAI_USAGE_FIELDS
        if field in raw and raw[field] is not None
    }
    return {"usage": counters} if counters else None


def _openai_retry_count(source: Any) -> int:
    """Read the SDK's final request retry counter without retaining headers."""

    request = getattr(source, "http_request", None) or getattr(source, "request", None)
    if request is None:
        http_response = getattr(source, "http_response", None)
        request = getattr(http_response, "request", None)
    headers = getattr(request, "headers", None)
    if headers is None:
        return 0
    try:
        return max(0, int(headers.get("x-stainless-retry-count", 0)))
    except (TypeError, ValueError):
        return 0


class EmbeddingUnavailable(RuntimeError):
    """The selected embedding space cannot currently be served."""

    code = "RAG_EMBEDDING_UNAVAILABLE"


class Embedder:
    """Embedding generation using OpenAI API (demo) or sentence-transformers (on-prem)."""

    def __init__(self, model_name: str = None):
        self.model_name = model_name or settings.embedding_model
        self.provider: str = "hash"
        self._client = None
        self._local_model = None
        self._dimension = None
        self._hash_fallback_count = 0
        self._init_provider()

    def _init_provider(self):
        # A collection's vectors belong to exactly one embedding space. A
        # provider outage must never silently change the space used by queries
        # or newly ingested chunks (even when both spaces share a dimension).
        if settings.embedding_provider == "openai":
            if not settings.openai_api_key:
                raise EmbeddingUnavailable(
                    "The configured OpenAI embedding credential is unavailable."
                )
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=settings.openai_api_key)
                self._dimension = 1536 if "small" in self.model_name else 3072
                self.provider = "openai"
                return
            except Exception as exc:
                raise EmbeddingUnavailable(
                    "The configured OpenAI embedding provider is unavailable."
                ) from exc
        try:
            from sentence_transformers import SentenceTransformer

            self._local_model = SentenceTransformer(
                self.model_name or "all-MiniLM-L6-v2",
                local_files_only=True,
                trust_remote_code=False,
            )
            self._dimension = self._local_model.get_sentence_embedding_dimension()
            self.provider = "local"
        except Exception as exc:
            raise EmbeddingUnavailable(
                "The configured local embedding model is unavailable."
            ) from exc

    def describe(self) -> dict:
        """Real embedder telemetry for decision steps and diagnostics."""
        return {
            "provider": getattr(self, "provider", "unknown"),
            "model_name": self.model_name,
            "dimension": self.get_dimension(),
            "degraded": self.is_degraded(),
        }

    def is_degraded(self) -> bool:
        return (
            getattr(self, "provider", "hash") == "hash"
            or getattr(self, "_hash_fallback_count", 0) > 0
        )

    async def embed(self, text: str) -> np.ndarray:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> np.ndarray:
        if self._client:
            return await self._openai_embed(texts)
        if self._local_model:
            return await self._local_embed(texts)
        raise EmbeddingUnavailable("The selected embedding model is unavailable.")

    async def _openai_embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.get_dimension()), dtype=np.float32)

        loop = asyncio.get_running_loop()

        async def embed_openai_batch(batch: list[str]) -> np.ndarray:
            def _call() -> tuple[Any, int]:
                embeddings = self._client.embeddings
                raw_embeddings = getattr(embeddings, "with_raw_response", None)
                raw_create = getattr(raw_embeddings, "create", None)
                if callable(raw_create):
                    raw_response = raw_create(input=batch, model=self.model_name)
                    return raw_response.parse(), _openai_retry_count(raw_response)
                return (
                    embeddings.create(input=batch, model=self.model_name),
                    0,
                )

            attempt = self._begin_openai_attempt()
            try:
                response, retry_count = await loop.run_in_executor(None, _call)
                final_attempt = attempt
                # The OpenAI SDK retries inside one ``create`` call.  Its final
                # request carries the exact retry count.  Every preceding HTTP
                # attempt lacks usage and therefore remains explicitly
                # unreported; only the final response can complete a row.
                for _ in range(retry_count):
                    final_attempt = self._begin_openai_attempt()
                self._complete_openai_attempt(final_attempt, response)
                ordered = sorted(response.data, key=lambda item: getattr(item, "index", 0))
                return np.array([item.embedding for item in ordered], dtype=np.float32)
            except Exception as e:
                for _ in range(_openai_retry_count(e)):
                    self._begin_openai_attempt()
                if len(batch) > 1:
                    mid = max(1, len(batch) // 2)
                    logger.warning(
                        "OpenAI embedding batch failed, retrying smaller batches",
                        error=str(e),
                        batch_size=len(batch),
                        estimated_tokens=sum(self._estimate_tokens(text) for text in batch),
                    )
                    left = await embed_openai_batch(batch[:mid])
                    right = await embed_openai_batch(batch[mid:])
                    return np.vstack([left, right])
                raise EmbeddingUnavailable(
                    "The selected embedding provider failed to produce a vector."
                ) from e

        embeddings = [await embed_openai_batch(batch) for batch in self._openai_batches(texts)]
        return (
            np.vstack(embeddings)
            if embeddings
            else np.empty((0, self.get_dimension()), dtype=np.float32)
        )

    def _begin_openai_attempt(self) -> dict[str, Any] | None:
        accumulator = _EMBEDDING_PROVIDER_USAGE.get()
        if accumulator is None:
            return None
        attempt = {
            "provider": "openai",
            "model": self.model_name,
            "reported": False,
        }
        accumulator.setdefault("calls", []).append(attempt)
        return attempt

    def _complete_openai_attempt(
        self,
        attempt: dict[str, Any] | None,
        response: Any,
    ) -> None:
        if attempt is None:
            return
        try:
            usage = normalize_provider_usage(_openai_usage_payload(response))
            if usage is not None:
                attempt["reported"] = True
                attempt["usage"] = usage
        except Exception as exc:  # noqa: BLE001 - telemetry cannot break embeddings.
            logger.warning("OpenAI embedding usage capture failed", error=str(exc))

    @classmethod
    def _openai_batches(cls, texts: list[str]) -> list[list[str]]:
        batches: list[list[str]] = []
        current: list[str] = []
        current_tokens = 0

        for text in texts:
            token_estimate = cls._estimate_tokens(text)
            would_exceed_count = len(current) >= _OPENAI_EMBEDDING_MAX_BATCH_INPUTS
            would_exceed_tokens = (
                current_tokens + token_estimate > _OPENAI_EMBEDDING_MAX_BATCH_ESTIMATED_TOKENS
            )
            if current and (would_exceed_count or would_exceed_tokens):
                batches.append(current)
                current = []
                current_tokens = 0
            current.append(text)
            current_tokens += token_estimate

        if current:
            batches.append(current)
        return batches

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        content = str(text or "")
        return max(1, max(len(content) // 3, len(content.split())))

    async def _local_embed(self, texts: list[str]) -> np.ndarray:
        loop = asyncio.get_event_loop()

        def _encode():
            return self._local_model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

        return await loop.run_in_executor(None, _encode)

    def _fallback_embed(self, text: str) -> np.ndarray:
        raise EmbeddingUnavailable("Embedding fallback is forbidden for an existing vector space.")

    def get_dimension(self) -> int:
        return self._dimension or 1536


_shared_embedder: "Embedder | None" = None


def get_shared_embedder() -> "Embedder":
    """Process-wide default Embedder (stateless apart from provider init)."""
    global _shared_embedder
    if _shared_embedder is None:
        _shared_embedder = Embedder()
    return _shared_embedder
