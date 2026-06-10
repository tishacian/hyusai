"""Embedding generation service -- OpenAI-first for demo."""
import asyncio

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_OPENAI_EMBEDDING_MAX_BATCH_INPUTS = 256
_OPENAI_EMBEDDING_MAX_BATCH_ESTIMATED_TOKENS = 240_000


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
        if settings.embedding_provider == "openai" and settings.openai_api_key:
            try:
                from openai import OpenAI

                self._client = OpenAI(api_key=settings.openai_api_key)
                self._dimension = 1536 if "small" in self.model_name else 3072
                self.provider = "openai"
                logger.info("Using OpenAI embeddings", model=self.model_name)
                return
            except Exception as e:
                logger.warning("OpenAI embeddings init failed", error=str(e))

        try:
            from sentence_transformers import SentenceTransformer

            self._local_model = SentenceTransformer(
                self.model_name or "all-MiniLM-L6-v2"
            )
            self._dimension = self._local_model.get_sentence_embedding_dimension()
            self.provider = "local"
            logger.info("Using local embeddings", model=self.model_name)
            return
        except ImportError:
            pass

        # Hash pseudo-embeddings keep the pipeline running but carry no
        # semantics: retrieval silently degrades to noise. Make it loud.
        logger.error(
            "No embedding provider available, using hash fallback — "
            "retrieval quality is degraded to lexical noise",
            model=self.model_name,
        )
        self.provider = "hash"
        self._dimension = 1536

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
        return np.array([self._fallback_embed(t) for t in texts])

    async def _openai_embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.get_dimension()), dtype=np.float32)

        loop = asyncio.get_running_loop()

        async def embed_openai_batch(batch: list[str]) -> np.ndarray:
            def _call() -> np.ndarray:
                response = self._client.embeddings.create(
                    input=batch, model=self.model_name
                )
                ordered = sorted(
                    response.data, key=lambda item: getattr(item, "index", 0)
                )
                return np.array([item.embedding for item in ordered], dtype=np.float32)

            try:
                return await loop.run_in_executor(None, _call)
            except Exception as e:
                if len(batch) > 1:
                    mid = max(1, len(batch) // 2)
                    logger.warning(
                        "OpenAI embedding batch failed, retrying smaller batches",
                        error=str(e),
                        batch_size=len(batch),
                        estimated_tokens=sum(
                            self._estimate_tokens(text) for text in batch
                        ),
                    )
                    left = await embed_openai_batch(batch[:mid])
                    right = await embed_openai_batch(batch[mid:])
                    return np.vstack([left, right])
                logger.error(
                    "OpenAI embedding error for single input, using fallback",
                    error=str(e),
                )
                return np.array([self._fallback_embed(batch[0])], dtype=np.float32)

        embeddings = [
            await embed_openai_batch(batch) for batch in self._openai_batches(texts)
        ]
        return (
            np.vstack(embeddings)
            if embeddings
            else np.empty((0, self.get_dimension()), dtype=np.float32)
        )

    @classmethod
    def _openai_batches(cls, texts: list[str]) -> list[list[str]]:
        batches: list[list[str]] = []
        current: list[str] = []
        current_tokens = 0

        for text in texts:
            token_estimate = cls._estimate_tokens(text)
            would_exceed_count = len(current) >= _OPENAI_EMBEDDING_MAX_BATCH_INPUTS
            would_exceed_tokens = (
                current_tokens + token_estimate
                > _OPENAI_EMBEDDING_MAX_BATCH_ESTIMATED_TOKENS
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
            return self._local_model.encode(
                texts, convert_to_numpy=True, show_progress_bar=False
            )

        return await loop.run_in_executor(None, _encode)

    def _fallback_embed(self, text: str) -> np.ndarray:
        import hashlib

        self._hash_fallback_count = getattr(self, "_hash_fallback_count", 0) + 1
        if self._hash_fallback_count == 1 or self._hash_fallback_count % 100 == 0:
            logger.error(
                "Hash pseudo-embedding emitted — vectors are not semantic",
                provider=getattr(self, "provider", "unknown"),
                model=self.model_name,
                count=self._hash_fallback_count,
            )
        hash_bytes = hashlib.sha256(text.encode()).digest()
        embedding = np.frombuffer(hash_bytes * 48, dtype=np.uint8)[
            : self._dimension
        ].astype(np.float32)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding

    def get_dimension(self) -> int:
        return self._dimension or 1536


_shared_embedder: "Embedder | None" = None


def get_shared_embedder() -> "Embedder":
    """Process-wide default Embedder (stateless apart from provider init)."""
    global _shared_embedder
    if _shared_embedder is None:
        _shared_embedder = Embedder()
    return _shared_embedder
