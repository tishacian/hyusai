"""Embedding generation service"""
import asyncio
from typing import List
import numpy as np
from app.core.logging import get_logger

logger = get_logger(__name__)


class Embedder:
    """Efficient embedding generation with GPU/CPU support"""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self.device = None
        self.batch_size = 8
        self._load_model()
    
    def _load_model(self):
        """Lazy load embedding model"""
        try:
            from sentence_transformers import SentenceTransformer
            import torch
            
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model = SentenceTransformer(self.model_name, device=self.device)
            self.batch_size = 32 if self.device == "cuda" else 8
            logger.info(f"Loaded embedding model {self.model_name} on {self.device}")
        except ImportError:
            logger.warning("sentence-transformers not installed. Using fallback.")
            self.model = None
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.model = None
    
    async def embed(self, text: str) -> np.ndarray:
        """Generate embedding for single text"""
        if not self.model:
            # Fallback: simple hash-based embedding (not recommended for production)
            return self._fallback_embed(text)
        
        results = await self.embed_batch([text])
        return results[0]
    
    async def embed_batch(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for batch of texts"""
        if not self.model:
            # Fallback
            return np.array([self._fallback_embed(text) for text in texts])
        
        loop = asyncio.get_event_loop()
        
        def _embed():
            try:
                embeddings = self.model.encode(
                    texts,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                    batch_size=self.batch_size,
                )
                return embeddings
            except Exception as e:
                logger.error(f"Embedding generation failed: {e}")
                # Fallback to individual embeddings
                return np.array([self._fallback_embed(text) for text in texts])
        
        return await loop.run_in_executor(None, _embed)
    
    def _fallback_embed(self, text: str) -> np.ndarray:
        """Fallback embedding (simple hash-based, 384 dimensions)"""
        import hashlib
        
        # Create a simple hash-based embedding
        hash_obj = hashlib.sha256(text.encode())
        hash_bytes = hash_obj.digest()
        
        # Convert to 384-dimensional vector (repeat hash bytes)
        embedding = np.frombuffer(hash_bytes * 12, dtype=np.uint8)[:384].astype(np.float32)
        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding
    
    def get_dimension(self) -> int:
        """Get embedding dimension"""
        if self.model:
            return self.model.get_sentence_embedding_dimension()
        return 384  # Fallback dimension

