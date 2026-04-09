"""Embedding generation service -- OpenAI-first for demo"""
import asyncio
from typing import List
import numpy as np
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class Embedder:
    """Embedding generation using OpenAI API (demo) or sentence-transformers (on-prem)."""

    def __init__(self, model_name: str = None):
        self.model_name = model_name or settings.embedding_model
        self._client = None
        self._local_model = None
        self._dimension = None
        self._init_provider()

    def _init_provider(self):
        if settings.embedding_provider == "openai" and settings.openai_api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=settings.openai_api_key)
                self._dimension = 1536 if "small" in self.model_name else 3072
                logger.info("Using OpenAI embeddings", model=self.model_name)
                return
            except Exception as e:
                logger.warning("OpenAI embeddings init failed", error=str(e))

        try:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer(self.model_name or "all-MiniLM-L6-v2")
            self._dimension = self._local_model.get_sentence_embedding_dimension()
            logger.info("Using local embeddings", model=self.model_name)
            return
        except ImportError:
            pass

        logger.warning("No embedding provider available, using hash fallback")
        self._dimension = 1536

    async def embed(self, text: str) -> np.ndarray:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: List[str]) -> np.ndarray:
        if self._client:
            return await self._openai_embed(texts)
        if self._local_model:
            return await self._local_embed(texts)
        return np.array([self._fallback_embed(t) for t in texts])

    async def _openai_embed(self, texts: List[str]) -> np.ndarray:
        loop = asyncio.get_event_loop()

        def _call():
            response = self._client.embeddings.create(input=texts, model=self.model_name)
            return np.array([item.embedding for item in response.data], dtype=np.float32)

        try:
            return await loop.run_in_executor(None, _call)
        except Exception as e:
            logger.error("OpenAI embedding error, using fallback", error=str(e))
            return np.array([self._fallback_embed(t) for t in texts])

    async def _local_embed(self, texts: List[str]) -> np.ndarray:
        loop = asyncio.get_event_loop()

        def _encode():
            return self._local_model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

        return await loop.run_in_executor(None, _encode)

    def _fallback_embed(self, text: str) -> np.ndarray:
        import hashlib
        hash_bytes = hashlib.sha256(text.encode()).digest()
        embedding = np.frombuffer(hash_bytes * 48, dtype=np.uint8)[:self._dimension].astype(np.float32)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding

    def get_dimension(self) -> int:
        return self._dimension or 1536
