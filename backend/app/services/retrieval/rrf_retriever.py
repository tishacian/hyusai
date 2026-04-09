"""Reciprocal Rank Fusion (RRF) for combining multiple retrieval results"""
from typing import List, Dict, Optional
from collections import defaultdict
from app.core.logging import get_logger

logger = get_logger(__name__)


class RRFRetriever:
    """Reciprocal Rank Fusion retriever for combining multiple ranked lists"""
    
    def __init__(self, k: int = 60):
        """
        Initialize RRF retriever
        
        Args:
            k: RRF constant (typically 60). Higher values give more weight to top-ranked items
        """
        self.k = k
    
    def fuse(
        self,
        ranked_lists: List[List[Dict]],
        top_k: int = 10
    ) -> List[Dict]:
        """
        Fuse multiple ranked lists using Reciprocal Rank Fusion
        
        Args:
            ranked_lists: List of ranked result lists, each containing dicts with at least 'id' or 'content' key
            top_k: Number of top results to return
            
        Returns:
            Fused and reranked results sorted by RRF score
        """
        if not ranked_lists or all(not lst for lst in ranked_lists):
            return []
        
        # Calculate RRF scores for each unique document
        rrf_scores = defaultdict(float)
        doc_map = {}  # Map unique identifier to full document dict
        
        for rank_list in ranked_lists:
            if not rank_list:
                continue
            
            for rank, doc in enumerate(rank_list, start=1):
                # Use content as unique identifier (most reliable)
                doc_id = doc.get("id", "")
                content = doc.get("content", "")
                
                # Create unique key from content or id
                if content:
                    unique_key = content
                elif doc_id:
                    unique_key = doc_id
                else:
                    # Fallback: use hash of entire doc
                    unique_key = str(hash(str(doc)))
                
                # Calculate RRF score: 1 / (k + rank)
                rrf_score = 1.0 / (self.k + rank)
                rrf_scores[unique_key] += rrf_score
                
                # Store document if not already stored
                if unique_key not in doc_map:
                    doc_map[unique_key] = doc.copy()
                    # Add RRF score to document
                    doc_map[unique_key]["rrf_score"] = rrf_score
                else:
                    # Update RRF score
                    doc_map[unique_key]["rrf_score"] = rrf_scores[unique_key]
        
        # Sort by RRF score (descending) and return top_k
        fused_results = []
        for key, score in sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True):
            doc = doc_map[key].copy()
            doc["rrf_score"] = score
            doc["combined_score"] = score  # Also set combined_score for consistency
            fused_results.append(doc)
        
        return fused_results[:top_k]
    
    def fuse_with_scores(
        self,
        ranked_lists: List[List[Dict]],
        score_keys: Optional[List[str]] = None,
        top_k: int = 10
    ) -> List[Dict]:
        """
        Fuse ranked lists and preserve original scores
        
        Args:
            ranked_lists: List of ranked result lists
            score_keys: Optional list of score keys to preserve (e.g., ['score', 'vector_score', 'bm25_score'])
            top_k: Number of top results to return
            
        Returns:
            Fused results with RRF score and original scores preserved
        """
        fused = self.fuse(ranked_lists, top_k)
        
        # Preserve original scores if provided
        if score_keys:
            for result in fused:
                # Try to find original scores from ranked lists
                for rank_list in ranked_lists:
                    for doc in rank_list:
                        if (doc.get("content") == result.get("content") or 
                            doc.get("id") == result.get("id")):
                            for key in score_keys:
                                if key in doc:
                                    result[key] = doc[key]
                            break
        
        return fused

