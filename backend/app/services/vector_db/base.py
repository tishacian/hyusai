"""Base vector database interface"""

from abc import ABC, abstractmethod
from typing import Any, Optional

import numpy as np


class VectorDBBase(ABC):
    """Base class for vector database implementations"""

    @abstractmethod
    async def create_index(self, dimension: int, index_type: str = "default"):
        """Create vector index"""
        pass

    @abstractmethod
    async def add_vectors(self, vectors: np.ndarray, metadatas: list[dict], ids: list[str]):
        """Add vectors to index"""
        pass

    @abstractmethod
    async def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 10,
        filters: Optional[dict] = None,
        search_params: Optional[dict] = None,
    ) -> list[dict]:
        """Search similar vectors"""
        pass

    @abstractmethod
    async def delete(self, ids: list[str]):
        """Delete vectors by IDs"""
        pass

    async def delete_by_metadata(self, filters: Optional[dict[str, Any]] = None) -> bool:
        """Delete vectors matching exact payload filters when supported.

        Backends without a native filtered delete return ``False`` so callers
        can fall back to an explicit, already-recorded point-id list.
        """
        return False

    @abstractmethod
    async def update(self, ids: list[str], vectors: np.ndarray, metadatas: list[dict]):
        """Update vectors"""
        pass

    @abstractmethod
    async def get_count(self) -> int:
        """Get total number of vectors"""
        pass

    async def count_payloads(self, filters: Optional[dict] = None) -> Optional[int]:
        """Count vectors matching payload filters when the store can do so cheaply."""
        if filters:
            return None
        return await self.get_count()

    async def list_payloads(
        self,
        filters: Optional[dict] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List payload metadata without vector search.

        Implementations may override this for diagnostic/admin UIs. The
        default keeps legacy vector stores compatible.
        """
        return []

    async def iter_payload_batches(self, batch_size: int = 256):
        """Iterate stored chunk payloads for an explicitly frozen generation."""
        offset = 0
        while True:
            batch = await self.list_payloads(limit=batch_size, offset=offset)
            if not batch:
                break
            yield batch
            offset += len(batch)

    async def search_exact_metadata(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[dict] = None,
        lexical_config: Optional[object] = None,
    ) -> list[dict]:
        """Return candidates from exact/metadata lexical payload indexes."""
        return []

    async def parent_contexts_for_hits(
        self,
        metadatas: list[dict],
        *,
        max_parents: int = 3,
        max_chars: int = 2500,
    ) -> list[dict]:
        """Return parent/coarse contexts for already retrieved child hits."""
        return []

    async def sample_chunk_vectors(
        self,
        limit: int = 200,
        filters: Optional[dict] = None,
    ) -> list[dict]:
        """Return a sample of points with their raw vectors + payload.

        Powers the embedding-map visualization (projection + similarity
        graph). Each item is ``{"id", "vector": list[float], "payload": dict}``.
        Default returns nothing for stores that cannot expose vectors.
        """
        return []

    async def reindex_sparse_vectors(self, batch_size: Optional[int] = None) -> dict:
        """Backfill store-native sparse vectors when the implementation supports it."""
        return {"status": "skipped", "configured": False, "reason": "unsupported_vector_db"}
