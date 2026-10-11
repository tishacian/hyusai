"""Advanced ensemble retriever with multiple fusion methods"""
import asyncio
import numpy as np
import re
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass
from collections import defaultdict

from app.services.retrieval.fusion_method import FusionMethod
from app.services.retrieval.ensemble_config import EnsembleConfig
from app.services.retrieval.bm25_retriever import BM25Retriever
from app.core.logging import get_logger

logger = get_logger(__name__)


class EnsembleRetriever:
    """Advanced ensemble retriever combining BM25 and dense search with multiple fusion methods"""
    
    def __init__(
        self,
        bm25_retriever: BM25Retriever,
        dense_retriever_fn,  # Function that performs dense search
        embedding_model: Any,
        texts: List[str],
        config: Optional[EnsembleConfig] = None,
    ):
        """
        Initialize ensemble retriever
        
        Args:
            bm25_retriever: BM25 retriever instance
            dense_retriever_fn: Async function that performs dense search: (query_embedding, k) -> List[Dict]
            embedding_model: Embedding model for query encoding
            texts: List of document texts
            config: Ensemble configuration
        """
        self.config = config or EnsembleConfig()
        self.bm25_retriever = bm25_retriever
        self.dense_retriever_fn = dense_retriever_fn
        self.embedding_model = embedding_model
        self.texts = texts
        self.query_characteristics_cache = {}
        self.adaptive_weights_history = []
        
        # Validate weights
        total_weight = self.config.bm25_weight + self.config.dense_weight
        if abs(total_weight - 1.0) > 1e-6:
            logger.warning(f"Weights don't sum to 1.0 ({total_weight}). Normalizing...")
            self.config.bm25_weight /= total_weight
            self.config.dense_weight /= total_weight
    
    async def _get_bm25_scores(
        self, query: str, k: int
    ) -> Tuple[List[str], Dict[str, float], List[int]]:
        """Get BM25 scores with ranking"""
        try:
            scores = self.bm25_retriever.get_scores(query)
            top_k_indices = np.argsort(scores)[-k:][::-1]
            passages = [self.texts[idx] for idx in top_k_indices if idx < len(self.texts)]
            scores_dict = {
                passage: float(scores[idx])
                for passage, idx in zip(passages, top_k_indices)
                if idx < len(scores)
            }
            ranks = list(range(1, len(passages) + 1))
            return passages, scores_dict, ranks
        except Exception as e:
            logger.error(f"BM25 retrieval error: {e}")
            return [], {}, []
    
    async def _get_dense_scores(
        self, query: str, k: int
    ) -> Tuple[List[str], Dict[str, float], List[int]]:
        """Get dense (vector) scores with ranking"""
        try:
            # Encode query
            if hasattr(self.embedding_model, 'encode'):
                query_embedding = self.embedding_model.encode(
                    [query],
                    convert_to_tensor=False,
                    show_progress_bar=False,
                )
            else:
                query_embedding = await self.embedding_model.embed(query)
            
            if isinstance(query_embedding, np.ndarray):
                if len(query_embedding.shape) == 1:
                    query_embedding = query_embedding.reshape(1, -1)
                query_embedding = query_embedding.astype("float32")
            else:
                query_embedding = np.array(query_embedding).reshape(1, -1).astype("float32")
            
            # Perform dense search
            results = await self.dense_retriever_fn(query_embedding[0] if len(query_embedding.shape) == 2 else query_embedding, k)
            
            # Format results
            passages = []
            scores_dict = {}
            for r in results:
                # Extract content - prioritize direct content, then metadata
                content = r.get("content", "")
                if not content:
                    content = r.get("metadata", {}).get("content", "")
                
                if content:
                    passages.append(content)
                    score = r.get("score", 0.0)
                    # Ensure score is positive (cosine similarity should be 0-1)
                    if score < 0:
                        score = max(0.0, 1.0 / (1.0 + abs(score)))
                    elif score > 1.0:
                        score = 1.0
                    scores_dict[content] = float(score)
            
            ranks = list(range(1, len(passages) + 1))
            return passages, scores_dict, ranks
            
        except Exception as e:
            logger.error(f"Dense retrieval error: {e}", exc_info=True)
            return [], {}, []
    
    def _analyze_query_characteristics(self, query: str) -> Dict[str, float]:
        """Analyze query characteristics for adaptive weighting"""
        if query in self.query_characteristics_cache:
            return self.query_characteristics_cache[query]
        
        words = query.split()
        characteristics = {
            "length": len(query),
            "word_count": len(words),
            "avg_word_length": np.mean([len(w) for w in words]) if words else 0,
            "is_question": 1.0 if query.strip().endswith("?") else 0.0,
            "has_wh_words": 1.0 if bool(re.search(r"\b(what|when|where|who|why|how)\b", query.lower())) else 0.0,
            "has_numbers": 1.0 if bool(re.search(r"\d", query)) else 0.0,
            "has_quotes": 1.0 if '"' in query or "'" in query else 0.0,
            "has_boolean": 1.0 if bool(re.search(r"\b(and|or|not)\b", query.lower())) else 0.0,
        }
        
        technical_words = [w for w in words if len(w) >= 6 and any(c.isupper() for c in w)]
        characteristics["technical_ratio"] = len(technical_words) / len(words) if words else 0.0
        
        proper_nouns = [w for i, w in enumerate(words) if i > 0 and w[0].isupper()]
        characteristics["proper_noun_ratio"] = len(proper_nouns) / len(words) if words else 0.0
        
        self.query_characteristics_cache[query] = characteristics
        return characteristics
    
    def _normalize_scores(self, scores: Dict[str, float]) -> Dict[str, float]:
        """Normalize scores to [0, 1] range"""
        if not scores:
            return scores
        
        score_values = list(scores.values())
        min_score = min(score_values)
        max_score = max(score_values)
        
        if max_score == min_score:
            return {passage: 1.0 for passage in scores}
        
        return {
            passage: (score - min_score) / (max_score - min_score)
            for passage, score in scores.items()
        }
    
    def _compute_rrf_scores(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute Reciprocal Rank Fusion scores"""
        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        rrf_scores = {}
        
        bm25_ranked = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
        dense_ranked = sorted(dense_scores.items(), key=lambda x: x[1], reverse=True)
        
        bm25_ranks = {passage: rank for rank, (passage, _) in enumerate(bm25_ranked, 1)}
        dense_ranks = {passage: rank for rank, (passage, _) in enumerate(dense_ranked, 1)}
        
        for passage in all_passages:
            bm25_rrf = 1.0 / (self.config.rrf_k + bm25_ranks.get(passage, len(bm25_ranked) + 1))
            dense_rrf = 1.0 / (self.config.rrf_k + dense_ranks.get(passage, len(dense_ranked) + 1))
            rrf_scores[passage] = bm25_rrf + dense_rrf
        
        return rrf_scores
    
    def _compute_score_adaptive_weights(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute scores using score-based adaptive weights"""
        if not bm25_scores or not dense_scores:
            return self._compute_weighted_linear(bm25_scores, dense_scores)
        
        bm25_values = list(bm25_scores.values())
        dense_values = list(dense_scores.values())
        bm25_var = np.var(bm25_values) if len(bm25_values) > 1 else 0
        dense_var = np.var(dense_values) if len(dense_values) > 1 else 0
        bm25_mean = np.mean(bm25_values)
        dense_mean = np.mean(dense_values)
        total_confidence = bm25_var + dense_var
        
        if total_confidence > 0:
            bm25_confidence = bm25_var / total_confidence
            dense_confidence = dense_var / total_confidence
        else:
            bm25_confidence = 0.5
            dense_confidence = 0.5
        
        bm25_weight = 0.6 * bm25_confidence + 0.4 * (bm25_mean / (bm25_mean + dense_mean) if (bm25_mean + dense_mean) > 0 else 0.5)
        dense_weight = 1.0 - bm25_weight
        
        self.adaptive_weights_history.append((bm25_weight, dense_weight))
        if len(self.adaptive_weights_history) > 100:
            self.adaptive_weights_history.pop(0)
        
        if self.config.normalize_scores:
            bm25_scores = self._normalize_scores(bm25_scores)
            dense_scores = self._normalize_scores(dense_scores)
        
        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        combined_scores = {}
        
        for passage in all_passages:
            bm25_score = bm25_scores.get(passage, 0.0)
            dense_score = dense_scores.get(passage, 0.0)
            combined_scores[passage] = bm25_weight * bm25_score + dense_weight * dense_score
        
        return combined_scores
    
    def _compute_query_adaptive_weights(
        self, query: str, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute scores using query-adaptive weights"""
        characteristics = self._analyze_query_characteristics(query)
        base_bm25_weight = self.config.bm25_weight
        
        if characteristics.get("proper_noun_ratio", 0) > 0.3 or characteristics.get("technical_ratio", 0) > 0.3:
            bm25_weight = min(0.7, base_bm25_weight + 0.2)
        elif characteristics.get("word_count", 0) > 15 or characteristics.get("has_wh_words", 0) > 0:
            bm25_weight = max(0.2, base_bm25_weight - 0.2)
        elif characteristics.get("word_count", 0) < 5:
            bm25_weight = min(0.6, base_bm25_weight + 0.1)
        else:
            bm25_weight = base_bm25_weight
        
        dense_weight = 1.0 - bm25_weight
        
        if self.config.normalize_scores:
            bm25_scores = self._normalize_scores(bm25_scores)
            dense_scores = self._normalize_scores(dense_scores)
        
        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        combined_scores = {}
        
        for passage in all_passages:
            bm25_score = bm25_scores.get(passage, 0.0)
            dense_score = dense_scores.get(passage, 0.0)
            combined_scores[passage] = bm25_weight * bm25_score + dense_weight * dense_score
        
        return combined_scores
    
    def _compute_weighted_linear(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute weighted linear combination"""
        if self.config.normalize_scores:
            bm25_scores = self._normalize_scores(bm25_scores)
            dense_scores = self._normalize_scores(dense_scores)
        
        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        combined_scores = {}
        
        for passage in all_passages:
            bm25_score = bm25_scores.get(passage, 0.0)
            dense_score = dense_scores.get(passage, 0.0)
            combined_scores[passage] = (
                self.config.bm25_weight * bm25_score +
                self.config.dense_weight * dense_score
            )
        
        return combined_scores
    
    def _fuse_scores(
        self, query: str, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Fuse scores using the selected method"""
        method = self.config.fusion_method
        
        if method == FusionMethod.RRF:
            return self._compute_rrf_scores(bm25_scores, dense_scores)
        elif method == FusionMethod.WEIGHTED_LINEAR:
            return self._compute_weighted_linear(bm25_scores, dense_scores)
        elif method == FusionMethod.QUERY_ADAPTIVE:
            return self._compute_query_adaptive_weights(query, bm25_scores, dense_scores)
        elif method == FusionMethod.SCORE_ADAPTIVE:
            return self._compute_score_adaptive_weights(bm25_scores, dense_scores)
        else:
            # Default to score adaptive
            return self._compute_score_adaptive_weights(bm25_scores, dense_scores)
    
    async def retrieve(
        self, query: str, k: Optional[int] = None
    ) -> Tuple[List[str], List[float]]:
        """Retrieve passages using ensemble fusion"""
        k = k or self.config.k
        
        try:
            candidate_k = k * 2  # Get more candidates for better fusion
            
            # Run both retrievers in parallel
            bm25_future = asyncio.create_task(self._get_bm25_scores(query, candidate_k))
            dense_future = asyncio.create_task(self._get_dense_scores(query, candidate_k))
            
            (bm25_passages, bm25_scores, _), (dense_passages, dense_scores, _) = await asyncio.gather(
                bm25_future, dense_future
            )
            
            if not bm25_scores and not dense_scores:
                logger.warning("Both retrievers failed")
                return [], []
            
            if not bm25_scores:
                logger.warning("BM25 returned no results, using dense only")
                sorted_results = sorted(dense_scores.items(), key=lambda x: x[1], reverse=True)
                passages, scores = zip(*sorted_results[:k]) if sorted_results else ([], [])
                return list(passages), list(scores)
            
            if not dense_scores:
                logger.warning("Dense returned no results, using BM25 only")
                sorted_results = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
                passages, scores = zip(*sorted_results[:k]) if sorted_results else ([], [])
                return list(passages), list(scores)
            
            # Fuse scores
            combined_scores = self._fuse_scores(query, bm25_scores, dense_scores)
            sorted_results = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
            passages, scores = zip(*sorted_results[:k]) if sorted_results else ([], [])
            return list(passages), list(scores)
            
        except Exception as e:
            logger.error(f"Ensemble retrieval error: {e}")
            return [], []
    
    def set_fusion_method(self, method: FusionMethod):
        """Change fusion method dynamically"""
        self.config.fusion_method = method
        logger.info(f"Fusion method changed to: {method.value}")

