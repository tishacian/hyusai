"""Contextual compression retriever"""
import asyncio
import os
from typing import List, Tuple, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

from app.services.retrieval.ensemble_retriever import EnsembleRetriever
from app.services.retrieval.flash_reranker import FlashReranker, RerankerConfig
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ContextualConfig:
    """Configuration for contextual compression"""
    k: int = 10
    rerank_batch_size: int = 64
    compression_ratio: float = 0.7
    use_threading: bool = True
    max_concurrent_tasks: int = min(64, (os.cpu_count() or 4) * 4)


class ContextualCompressionRetriever:
    """Context compression retriever that wraps ensemble retriever and reranker"""
    
    def __init__(
        self,
        base_retriever: EnsembleRetriever,
        reranker: FlashReranker,
        config: Optional[ContextualConfig] = None,
    ):
        """
        Initialize contextual compression retriever
        
        Args:
            base_retriever: Ensemble retriever (uses RRF or other fusion)
            reranker: Flash reranker
            config: Contextual configuration
        """
        self.base_retriever = base_retriever
        self.reranker = reranker
        self.config = config or ContextualConfig()
        self._executor = (
            ThreadPoolExecutor(max_workers=self.config.max_concurrent_tasks)
            if self.config.use_threading
            else None
        )
    
    def __del__(self):
        """Cleanup executor"""
        if hasattr(self, '_executor') and self._executor:
            self._executor.shutdown(wait=False)
    
    async def _process_batch(
        self, query: str, passages: List[str]
    ) -> Tuple[List[str], List[float]]:
        """Batch processing for reranking"""
        try:
            reranked_passages, scores = self.reranker.rerank(
                query, passages, return_scores=True
            )
            return reranked_passages, scores
        except Exception as e:
            logger.error(f"Reranking error in batch processing: {e}")
            return passages, [0.0] * len(passages)
    
    async def _compress_results(
        self, passages: List[str], scores: List[float]
    ) -> Tuple[List[str], List[float]]:
        """Compress results based on compression ratio"""
        if not passages:
            return [], []
        
        k = max(1, int(len(passages) * self.config.compression_ratio))
        return passages[:k], scores[:k]
    
    async def retrieve_and_compress(
        self, query: str, k: Optional[int] = None
    ) -> Tuple[List[str], List[float]]:
        """Retrieve and compress results"""
        try:
            # Retrieve from base retriever
            base_passages, base_scores = await self.base_retriever.retrieve(query, k)
            
            if not base_passages:
                return [], []
            
            # Rerank results
            if self.config.use_threading and self._executor:
                loop = asyncio.get_event_loop()
                reranked_passages, scores = await loop.run_in_executor(
                    self._executor,
                    self.reranker.rerank,
                    query,
                    base_passages,
                    True,  # return_scores
                )
            else:
                reranked_passages, scores = await self._process_batch(query, base_passages)
            
            # Compress contexts
            final_passages, final_scores = await self._compress_results(
                reranked_passages, scores
            )
            
            return final_passages, final_scores
            
        except Exception as e:
            logger.error(f"Error in retrieve_and_compress: {e}")
            return [], []

