"""Hybrid retrieval combining dense (vector) and sparse (BM25) search"""
from typing import List, Dict, Optional
import numpy as np
from app.services.retrieval.bm25_retriever import BM25Retriever
from app.services.retrieval.rrf_retriever import RRFRetriever
from app.core.logging import get_logger

logger = get_logger(__name__)


class HybridRetriever:
    """Hybrid retriever combining vector search and BM25 using RRF (Reciprocal Rank Fusion)"""
    
    def __init__(self, vector_weight: float = 0.7, bm25_weight: float = 0.3, use_rrf: bool = True, rrf_k: int = 60):
        """
        Initialize hybrid retriever
        
        Args:
            vector_weight: Weight for vector search scores (0-1) - used when RRF is disabled
            bm25_weight: Weight for BM25 scores (0-1) - used when RRF is disabled
            use_rrf: Whether to use Reciprocal Rank Fusion (default: True)
            rrf_k: RRF constant (default: 60)
        """
        if not use_rrf and abs(vector_weight + bm25_weight - 1.0) > 0.01:
            raise ValueError("Weights must sum to 1.0 when not using RRF")
        
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight
        self.use_rrf = use_rrf
        self.rrf_retriever = RRFRetriever(k=rrf_k) if use_rrf else None
        self.bm25_retriever = BM25Retriever()
        self.documents: List[str] = []
        self._bm25_fitted = False
    
    def fit(self, documents: List[str]):
        """Fit both retrievers on documents"""
        self.documents = documents
        self.bm25_retriever.fit(documents)
        self._bm25_fitted = True
    
    async def search(
        self,
        query: str,
        vector_search_fn,
        top_k: int = 10,
        rerank: bool = True
    ) -> List[Dict]:
        """
        Perform hybrid search using RRF (Reciprocal Rank Fusion) or weighted combination
        
        Args:
            query: Search query
            vector_search_fn: Async function that performs vector search and returns results
            top_k: Number of results to return
            rerank: Whether to rerank results (ignored when using RRF, as RRF inherently reranks)
            
        Returns:
            List of results with combined scores
        """
        # Perform both searches - get more results for better fusion
        search_k = top_k * 3 if self.use_rrf else top_k * 2
        
        vector_results = await vector_search_fn(query, search_k)
        bm25_results = self.bm25_retriever.search(query, search_k)
        
        if self.use_rrf:
            # Use Reciprocal Rank Fusion
            ranked_lists = [vector_results, bm25_results]
            combined_results = self.rrf_retriever.fuse_with_scores(
                ranked_lists,
                score_keys=["score", "vector_score", "bm25_score"],
                top_k=top_k
            )
            
            # Rename rrf_score to combined_score for consistency
            for result in combined_results:
                result["combined_score"] = result.pop("rrf_score", 0.0)
                # Ensure vector_score and bm25_score are set
                if "vector_score" not in result:
                    result["vector_score"] = result.get("score", 0.0)
                if "bm25_score" not in result:
                    result["bm25_score"] = 0.0
            
            return combined_results
        else:
            # Use weighted combination (legacy method)
            # Normalize scores to [0, 1] range
            vector_results = self._normalize_scores(vector_results, "score")
            bm25_results = self._normalize_scores(bm25_results, "score")
            
            # Combine results
            combined_results = self._combine_results(
                vector_results,
                bm25_results,
                top_k if not rerank else top_k * 2
            )
            
            # Rerank if requested
            if rerank:
                combined_results = self._rerank(combined_results, query, top_k)
            
            return combined_results[:top_k]
    
    def _normalize_scores(self, results: List[Dict], score_key: str) -> List[Dict]:
        """Normalize scores to [0, 1] range"""
        if not results:
            return results
        
        scores = [r[score_key] for r in results]
        min_score = min(scores)
        max_score = max(scores)
        
        if max_score == min_score:
            # All scores are the same, set to 0.5
            for r in results:
                r[score_key] = 0.5
        else:
            # Normalize to [0, 1]
            for r in results:
                r[score_key] = (r[score_key] - min_score) / (max_score - min_score)
        
        return results
    
    def _combine_results(
        self,
        vector_results: List[Dict],
        bm25_results: List[Dict],
        top_k: int
    ) -> List[Dict]:
        """Combine vector and BM25 results"""
        # Create a map of content to combined result
        combined_map: Dict[str, Dict] = {}
        
        # Add vector results
        for result in vector_results:
            # Extract content from metadata (where ChromaDB stores it)
            metadata = result.get("metadata", {})
            content = result.get("content", "") or metadata.get("content", "")
            if content:
                combined_map[content] = {
                    "content": content,
                    "vector_score": result.get("score", 0.0),
                    "bm25_score": 0.0,
                    "combined_score": result.get("score", 0.0) * self.vector_weight,
                    "metadata": metadata,
                    "id": result.get("id", ""),
                }
        
        # Add/update with BM25 results
        for result in bm25_results:
            content = result.get("content", "")
            if content and content in combined_map:
                combined_map[content]["bm25_score"] = result.get("score", 0.0)
                combined_map[content]["combined_score"] = (
                    combined_map[content]["vector_score"] * self.vector_weight +
                    result.get("score", 0.0) * self.bm25_weight
                )
            elif content:
                # BM25 result not in vector results - add it
                combined_map[content] = {
                    "content": content,
                    "vector_score": 0.0,
                    "bm25_score": result.get("score", 0.0),
                    "combined_score": result.get("score", 0.0) * self.bm25_weight,
                    "metadata": {},
                    "id": "",
                }
        
        # Convert to list and sort by combined score
        combined_list = list(combined_map.values())
        combined_list.sort(key=lambda x: x["combined_score"], reverse=True)
        
        return combined_list[:top_k]
    
    def _rerank(self, results: List[Dict], query: str, top_k: int) -> List[Dict]:
        """Rerank results using a simple heuristic"""
        # Simple reranking: boost results that appear in both searches
        for result in results:
            if result["vector_score"] > 0 and result["bm25_score"] > 0:
                # Boost if present in both
                result["combined_score"] *= 1.2
        
        # Sort again
        results.sort(key=lambda x: x["combined_score"], reverse=True)
        return results

