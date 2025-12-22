"""Embedding service for generating text embeddings"""
from typing import List
from app.core.logging import get_logger
from app.core.cache import cache
from sentence_transformers import SentenceTransformer
import numpy as np

logger = get_logger(__name__)


class EmbeddingService:
    """Service for generating text embeddings"""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self.logger = get_logger(__name__)
    
    def _load_model(self):
        """Lazy load the embedding model"""
        if self.model is None:
            self.logger.info("Loading embedding model", model=self.model_name)
            self.model = SentenceTransformer(self.model_name)
            self.logger.info("Embedding model loaded")
    
    def embed(self, text: str, use_cache: bool = True) -> List[float]:
        """Generate embedding for a single text"""
        # Check cache first
        if use_cache:
            cache_key = cache._generate_key("embed", text, self.model_name)
            cached = cache.get(cache_key)
            if cached:
                self.logger.debug("Embedding cache hit")
                return cached
        
        # Generate embedding
        self._load_model()
        embedding = self.model.encode(text, convert_to_numpy=True)
        embedding_list = embedding.tolist()
        
        # Cache result
        if use_cache:
            cache.set(cache_key, embedding_list, ttl_seconds=86400)  # 24 hours
        
        return embedding_list
    
    def embed_batch(self, texts: List[str], use_cache: bool = True) -> List[List[float]]:
        """Generate embeddings for multiple texts"""
        self._load_model()
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()
    
    @property
    def dimension(self) -> int:
        """Get embedding dimension"""
        self._load_model()
        return self.model.get_sentence_embedding_dimension()

