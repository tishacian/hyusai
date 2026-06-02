"""Base vector database interface"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
import numpy as np


class VectorDBBase(ABC):
    """Base class for vector database implementations"""
    
    @abstractmethod
    async def create_index(self, dimension: int, index_type: str = "default"):
        """Create vector index"""
        pass
    
    @abstractmethod
    async def add_vectors(self, vectors: np.ndarray, metadatas: List[Dict], ids: List[str]):
        """Add vectors to index"""
        pass
    
    @abstractmethod
    async def search(self, query_vector: np.ndarray, top_k: int = 10, filters: Optional[Dict] = None) -> List[Dict]:
        """Search similar vectors"""
        pass
    
    @abstractmethod
    async def delete(self, ids: List[str]):
        """Delete vectors by IDs"""
        pass
    
    @abstractmethod
    async def update(self, ids: List[str], vectors: np.ndarray, metadatas: List[Dict]):
        """Update vectors"""
        pass
    
    @abstractmethod
    async def get_count(self) -> int:
        """Get total number of vectors"""
        pass

    async def list_payloads(
        self,
        filters: Optional[Dict] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        """List payload metadata without vector search.

        Implementations may override this for diagnostic/admin UIs. The
        default keeps legacy vector stores compatible.
        """
        return []

    async def sample_chunk_vectors(
        self,
        limit: int = 200,
        filters: Optional[Dict] = None,
    ) -> List[Dict]:
        """Return a sample of points with their raw vectors + payload.

        Powers the embedding-map visualization (projection + similarity
        graph). Each item is ``{"id", "vector": list[float], "payload": dict}``.
        Default returns nothing for stores that cannot expose vectors.
        """
        return []
