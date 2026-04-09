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

