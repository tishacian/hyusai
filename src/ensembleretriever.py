# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 16:07:22 2025

@author: kennethezukwoke
"""

import asyncio
import logging
import re
import sys
import warnings
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch

warnings.simplefilter(action="ignore", category=FutureWarning)
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class FusionMethod(Enum):
    RRF = "rrf"
    WEIGHTED_LINEAR = "weighted_linear"
    QUERY_ADAPTIVE = "query_adaptive"
    SCORE_ADAPTIVE = "score_adaptive"
    HARMONIC_MEAN = "harmonic_mean"
    GEOMETRIC_MEAN = "geometric_mean"
    MIN_MAX_FUSION = "min_max_fusion"
    RANK_FUSION = "rank_fusion"
    COMBSUM = "combsum"
    COMBMNZ = "combmnz"


@dataclass
class EnsembleConfig:
    k: int = 20
    bm25_weight: float = 0.4
    dense_weight: float = 0.6
    rrf_k: int = 60
    batch_size: int = 64
    use_gpu: bool = True
    normalize_scores: bool = True
    fusion_method: FusionMethod = FusionMethod.SCORE_ADAPTIVE
    adaptive_alpha: float = 0.1


class EnsembleRetriever:
    def __init__(
        self,
        bm25_retriever: Any,
        dense_retriever: Any,
        embedding_model: Any,
        texts: List[str],
        config: Optional[EnsembleConfig] = None,
    ):
        """Ensemble retriever

        Parameters
        ----------
        bm25_retriever : Any
            BM25 retriever.
        dense_retriever : Any
            Dense (usually FAISS) retriever.
        embedding_model : embedding
            Embedding model.
        texts : List[str]
            Text corpus for retrieving passages.
        config : Optional[EnsembleConfig], optional
            Ensemble reranking config. The default is None.

        Returns
        -------
        None.
        """
        self.config = config or EnsembleConfig()
        self.bm25_retriever = bm25_retriever
        self.dense_retriever = dense_retriever
        self.embedding_model = embedding_model
        self.texts = texts
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() and self.config.use_gpu else "cpu"
        )

        # Validate weights sum to 1 for linear methods
        total_weight = self.config.bm25_weight + self.config.dense_weight
        if abs(total_weight - 1.0) > 1e-6:
            logging.warning(
                f"Weights don't sum to 1.0 ({total_weight}). Normalizing..."
            )
            self.config.bm25_weight /= total_weight
            self.config.dense_weight /= total_weight

        # Initialize adaptive weight history for learning
        self.adaptive_weights_history = []
        self.query_characteristics_cache = {}

    async def _get_bm25_scores(
        self, query: str, k: int
    ) -> Tuple[List[str], Dict[str, float], List[int]]:
        """BM25 retriever scores with ranking

        Parameters
        ----------
        query (str): Query
        k (int): Number of documents to retrieve

        Returns
        -------
        (Tuple[List[str], Dict[str, float], List[int]])
            Retrieved passages, their scores, and original ranks.
        """
        try:
            scores = self.bm25_retriever.get_scores(query)
            top_k_indices = np.argsort(scores)[-k:][::-1]
            passages = [self.bm25_retriever.documents[idx] for idx in top_k_indices]
            scores_dict = {
                passage: float(scores[idx])
                for passage, idx in zip(passages, top_k_indices)
            }
            ranks = list(range(1, len(passages) + 1))
            return passages, scores_dict, ranks
        except Exception as e:
            logging.error(f"BM25 retrieval error: {e}")
            return [], {}, []

    async def _get_dense_scores(
        self, query: str, k: int
    ) -> Tuple[List[str], Dict[str, float], List[int]]:
        """Dense retriever scores with ranking

        Parameters
        ----------
        query (str): Query
        k (int): Number of documents to retrieve

        Returns
        -------
        (Tuple[List[str], Dict[str, float], List[int]])
            Retrieved passages, their scores, and original ranks.
        """
        try:
            with torch.no_grad():
                query_embedding = self.embedding_model.encode(
                    [query],
                    convert_to_tensor=True,
                    show_progress_bar=False,
                    device=self.device,
                )
                query_embedding = query_embedding.cpu().numpy()

            if len(query_embedding.shape) == 2:
                query_embedding = query_embedding.astype("float32")
            else:
                query_embedding = query_embedding.reshape(1, -1).astype("float32")

            # FAISS Search
            D, i_var = self.dense_retriever.search(query_embedding, k)
            passages = [self.texts[idx] for idx in i_var[0]]
            similarities = 1.0 / (1.0 + D[0])  # Convert distance to similarity
            scores_dict = {
                passage: float(score) for passage, score in zip(passages, similarities)
            }
            ranks = list(range(1, len(passages) + 1))

            return passages, scores_dict, ranks

        except Exception as e:
            logging.error(f"Dense retrieval error: {e}")
            return [], {}, []

    def _analyze_query_characteristics(self, query: str) -> Dict[str, float]:
        """Analyze query characteristics for adaptive weighting

        Parameters
        ----------
        query : str
            Input query

        Returns
        -------
        Dict[str, float]
            Dictionary of query characteristics
        """
        if query in self.query_characteristics_cache:
            return self.query_characteristics_cache[query]

        characteristics = {}
        words = query.split()
        characteristics["length"] = len(query)
        characteristics["word_count"] = len(words)
        characteristics["avg_word_length"] = (
            np.mean([len(w) for w in words]) if words else 0
        )
        characteristics["is_question"] = 1.0 if query.strip().endswith("?") else 0.0
        characteristics["has_wh_words"] = (
            1.0
            if bool(re.search(r"\b(what|when|where|who|why|how)\b", query.lower()))
            else 0.0
        )
        characteristics["has_numbers"] = 1.0 if bool(re.search(r"\d", query)) else 0.0
        characteristics["has_quotes"] = 1.0 if '"' in query or "'" in query else 0.0
        characteristics["has_boolean"] = (
            1.0 if bool(re.search(r"\b(and|or|not)\b", query.lower())) else 0.0
        )
        technical_words = [
            w for w in words if len(w) >= 6 and any(c.isupper() for c in w)
        ]
        characteristics["technical_ratio"] = (
            len(technical_words) / len(words) if words else 0.0
        )
        proper_nouns = [w for i, w in enumerate(words) if i > 0 and w[0].isupper()]
        characteristics["proper_noun_ratio"] = (
            len(proper_nouns) / len(words) if words else 0.0
        )
        self.query_characteristics_cache[query] = characteristics
        return characteristics

    def _normalize_scores(self, scores: Dict[str, float]) -> Dict[str, float]:
        """Normalize scores to [0, 1] range using min-max normalization

        Parameters
        ----------
        scores : Dict[str, float]
            scores.

        Returns
        -------
        Dict[str, float]
            normalized scores.
        """
        if not scores:
            return scores

        score_values = list(scores.values())
        min_score = min(score_values)
        max_score = max(score_values)
        if max_score == min_score:
            return {passage: 1.0 for passage in scores}

        normalized_scores = {}
        for passage, score in scores.items():
            normalized_scores[passage] = (score - min_score) / (max_score - min_score)

        return normalized_scores

    def _compute_rrf_scores(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute Reciprocal Rank Fusion scores

        Parameters
        ----------
        bm25_scores : Dict[str, float]
            bm25 scores.
        dense_scores : Dict[str, float]
            dense scores.

        Returns
        -------
        Dict[str, float]
            rrf scores.
        """
        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        rrf_scores = {}
        bm25_ranked = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
        dense_ranked = sorted(dense_scores.items(), key=lambda x: x[1], reverse=True)
        bm25_ranks = {passage: rank for rank, (passage, _) in enumerate(bm25_ranked, 1)}
        dense_ranks = {
            passage: rank for rank, (passage, _) in enumerate(dense_ranked, 1)
        }

        for passage in all_passages:
            bm25_rrf = 1 / (
                self.config.rrf_k + bm25_ranks.get(passage, len(bm25_ranked) + 1)
            )
            dense_rrf = 1 / (
                self.config.rrf_k + dense_ranks.get(passage, len(dense_ranked) + 1)
            )
            rrf_scores[passage] = bm25_rrf + dense_rrf

        return rrf_scores

    def _compute_weighted_linear(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute weighted linear combination

        Parameters
        ----------
        bm25_scores : Dict[str, float]
            bm25 scores.
        dense_scores : Dict[str, float]
            dense scores.

        Returns
        -------
        Dict[str, float]
            combined weighted linear scores.
        """
        if self.config.normalize_scores:
            bm25_scores = self._normalize_scores(bm25_scores)
            dense_scores = self._normalize_scores(dense_scores)

        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        combined_scores = {}

        for passage in all_passages:
            bm25_score = bm25_scores.get(passage, 0.0)
            dense_score = dense_scores.get(passage, 0.0)
            combined_scores[passage] = (
                self.config.bm25_weight * bm25_score
                + self.config.dense_weight * dense_score
            )

        return combined_scores

    def _compute_query_adaptive_weights(
        self,
        query: str,
        bm25_scores: Dict[str, float],
        dense_scores: Dict[str, float],
    ) -> Dict[str, float]:
        """Compute scores using query-adaptive weights

        Parameters
        ----------
        query : str
            input query.
        bm25_scores : Dict[str, float]
            bm25 scores.
        dense_scores : Dict[str, float]
            dense scores.

        Returns
        -------
        Dict[str, float]
            query adaptive weights.

        """
        characteristics = self._analyze_query_characteristics(query)
        base_bm25_weight = self.config.bm25_weight
        if (
            characteristics["has_proper_nouns"]
            or characteristics["technical_ratio"] > 0.3
        ):
            bm25_weight = min(0.7, base_bm25_weight + 0.2)
        elif characteristics["word_count"] > 15 or characteristics["has_wh_words"]:
            bm25_weight = max(0.2, base_bm25_weight - 0.2)
        elif characteristics["word_count"] < 5:
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
            combined_scores[passage] = (
                bm25_weight * bm25_score + dense_weight * dense_score
            )

        return combined_scores

    def _compute_score_adaptive_weights(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute scores using score-based adaptive weights

        Parameters
        ----------
        bm25_scores : Dict[str, float]
            bm25 scores.
        dense_scores : Dict[str, float]
            dense scores.

        Returns
        -------
        Dict[str, float]
            score adaptive weights.
        """
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
            # dense_confidence = dense_var / total_confidence
        else:
            bm25_confidence = 0.5
            # dense_confidence = 0.5

        bm25_weight = 0.6 * bm25_confidence + 0.4 * (
            bm25_mean / (bm25_mean + dense_mean)
        )
        dense_weight = 1.0 - bm25_weight
        if hasattr(self, "adaptive_weights_history"):
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
            combined_scores[passage] = (
                bm25_weight * bm25_score + dense_weight * dense_score
            )

        return combined_scores

    def _compute_harmonic_mean(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute harmonic mean of scores

        Parameters
        ----------
        bm25_scores : Dict[str, float]
            bm25 scores.
        dense_scores : Dict[str, float]
            dense scores.

        Returns
        -------
        Dict[str, float]
            harmonic mean.
        """
        if self.config.normalize_scores:
            bm25_scores = self._normalize_scores(bm25_scores)
            dense_scores = self._normalize_scores(dense_scores)

        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        combined_scores = {}

        for passage in all_passages:
            bm25_score = bm25_scores.get(passage, 0.0)
            dense_score = dense_scores.get(passage, 0.0)
            if bm25_score == 0 or dense_score == 0:
                combined_scores[passage] = 0.0
            else:
                combined_scores[passage] = (
                    2 * (bm25_score * dense_score) / (bm25_score + dense_score)
                )

        return combined_scores

    def _compute_geometric_mean(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute geometric mean of scores

        Parameters
        ----------
        bm25_scores : Dict[str, float]
            bm25_scores.
        dense_scores : Dict[str, float]
            dense scores.

        Returns
        -------
        Dict[str, float]
            geometric mean.

        """
        if self.config.normalize_scores:
            bm25_scores = self._normalize_scores(bm25_scores)
            dense_scores = self._normalize_scores(dense_scores)

        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        combined_scores = {}

        for passage in all_passages:
            bm25_score = bm25_scores.get(passage, 0.0)
            dense_score = dense_scores.get(passage, 0.0)
            combined_scores[passage] = np.sqrt(bm25_score * dense_score)

        return combined_scores

    def _compute_min_max_fusion(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute min-max fusion (take max of normalized scores)

        Parameters
        ----------
        bm25_scores : Dict[str, float]
            bm25 scores.
        dense_scores : Dict[str, float]
            dense scores.

        Returns
        -------
        Dict[str, float]
            min-max fusion scores.

        """
        bm25_scores_norm = self._normalize_scores(bm25_scores)
        dense_scores_norm = self._normalize_scores(dense_scores)
        all_passages = set(bm25_scores_norm.keys()) | set(dense_scores_norm.keys())
        combined_scores = {}

        for passage in all_passages:
            bm25_score = bm25_scores_norm.get(passage, 0.0)
            dense_score = dense_scores_norm.get(passage, 0.0)
            combined_scores[passage] = max(bm25_score, dense_score)

        return combined_scores

    def _compute_rank_fusion(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute rank-based fusion

        Parameters
        ----------
        bm25_scores : Dict[str, float]
            DESCRIPTION.
        dense_scores : Dict[str, float]
            DESCRIPTION.

        Returns
        -------
        Dict[str, float]
            rank fusion scores.
        """
        bm25_ranked = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
        dense_ranked = sorted(dense_scores.items(), key=lambda x: x[1], reverse=True)
        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        combined_scores = {}

        max_rank = max(len(bm25_ranked), len(dense_ranked))

        for passage in all_passages:
            bm25_rank = next(
                (i + 1 for i, (p, _) in enumerate(bm25_ranked) if p == passage),
                max_rank + 1,
            )
            dense_rank = next(
                (i + 1 for i, (p, _) in enumerate(dense_ranked) if p == passage),
                max_rank + 1,
            )
            bm25_rank_score = 1.0 / bm25_rank
            dense_rank_score = 1.0 / dense_rank

            combined_scores[passage] = bm25_rank_score + dense_rank_score

        return combined_scores

    def _compute_combsum(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute CombSUM (normalized sum)

        Parameters
        ----------
        bm25_scores : Dict[str, float]
            bm25 scores.
        dense_scores : Dict[str, float]
            dense scores.

        Returns
        -------
        Dict[str, float]
            additive scores.

        """
        bm25_scores_norm = self._normalize_scores(bm25_scores)
        dense_scores_norm = self._normalize_scores(dense_scores)

        all_passages = set(bm25_scores_norm.keys()) | set(dense_scores_norm.keys())
        combined_scores = {}

        for passage in all_passages:
            bm25_score = bm25_scores_norm.get(passage, 0.0)
            dense_score = dense_scores_norm.get(passage, 0.0)
            combined_scores[passage] = bm25_score + dense_score

        return combined_scores

    def _compute_combmnz(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """Compute CombMNZ


        Parameters
        ----------
        bm25_scores : Dict[str, float]
            bm25 scores.
        dense_scores : Dict[str, float]
            dense scores.

        Returns
        -------
        Dict[str, float]
            combines non-zero scores.

        """
        bm25_scores_norm = self._normalize_scores(bm25_scores)
        dense_scores_norm = self._normalize_scores(dense_scores)

        all_passages = set(bm25_scores_norm.keys()) | set(dense_scores_norm.keys())
        combined_scores = {}

        for passage in all_passages:
            bm25_score = bm25_scores_norm.get(passage, 0.0)
            dense_score = dense_scores_norm.get(passage, 0.0)
            non_zero_count = sum(
                [1 for score in [bm25_score, dense_score] if score > 0]
            )
            combined_scores[passage] = (bm25_score + dense_score) * non_zero_count

        return combined_scores

    def _fuse_scores(
        self,
        query: str,
        bm25_scores: Dict[str, float],
        dense_scores: Dict[str, float],
    ) -> Dict[str, float]:
        """Fuse scores using the selected method

        Parameters
        ----------
        query : str
            input query.
        bm25_scores : Dict[str, float]
            bm25 scores.
        dense_scores : Dict[str, float]
            dense scores.

        Returns
        -------
        Dict[str, float]
            fused scores.

        """
        method = self.config.fusion_method

        if method == FusionMethod.RRF:
            return self._compute_rrf_scores(bm25_scores, dense_scores)
        elif method == FusionMethod.WEIGHTED_LINEAR:
            return self._compute_weighted_linear(bm25_scores, dense_scores)
        elif method == FusionMethod.QUERY_ADAPTIVE:
            return self._compute_query_adaptive_weights(
                query, bm25_scores, dense_scores
            )
        elif method == FusionMethod.SCORE_ADAPTIVE:
            return self._compute_score_adaptive_weights(bm25_scores, dense_scores)
        elif method == FusionMethod.HARMONIC_MEAN:
            return self._compute_harmonic_mean(bm25_scores, dense_scores)
        elif method == FusionMethod.GEOMETRIC_MEAN:
            return self._compute_geometric_mean(bm25_scores, dense_scores)
        elif method == FusionMethod.MIN_MAX_FUSION:
            return self._compute_min_max_fusion(bm25_scores, dense_scores)
        elif method == FusionMethod.RANK_FUSION:
            return self._compute_rank_fusion(bm25_scores, dense_scores)
        elif method == FusionMethod.COMBSUM:
            return self._compute_combsum(bm25_scores, dense_scores)
        elif method == FusionMethod.COMBMNZ:
            return self._compute_combmnz(bm25_scores, dense_scores)
        else:
            # -- absolute default
            return self._compute_score_adaptive_weights(bm25_scores, dense_scores)

    async def retrieve(
        self, query: str, k: Optional[int] = None
    ) -> Tuple[List[str], List[float]]:
        """Retrieve passages using the selected fusion method

        Parameters
        ----------
        query (str): Input query
        k : Optional[int], optional
            Number of passages to retrieve. The default is None.

        Returns
        -------
        (Tuple[List[str], List[float]])
            Retrieved passages and their combined scores.
        """
        k = k or self.config.k

        try:
            candidate_k = k * 2
            bm25_future = asyncio.create_task(self._get_bm25_scores(query, candidate_k))
            dense_future = asyncio.create_task(
                self._get_dense_scores(query, candidate_k)
            )

            (
                (bm25_passages, bm25_scores, bm25_ranks),
                (
                    dense_passages,
                    dense_scores,
                    dense_ranks,
                ),
            ) = await asyncio.gather(bm25_future, dense_future)
            if not bm25_scores and not dense_scores:
                logging.warning("Both retrievers failed")
                return [], []

            if not bm25_scores:
                logging.warning("BM25 retriever returned no results, using dense only")
                sorted_results = sorted(
                    dense_scores.items(), key=lambda x: x[1], reverse=True
                )
                passages, scores = zip(*sorted_results[:k])
                return list(passages), list(scores)

            if not dense_scores:
                logging.warning("Dense retriever returned no results, using BM25 only")
                sorted_results = sorted(
                    bm25_scores.items(), key=lambda x: x[1], reverse=True
                )
                passages, scores = zip(*sorted_results[:k])
                return list(passages), list(scores)

            # -- fuse scores
            combined_scores = self._fuse_scores(query, bm25_scores, dense_scores)
            sorted_results = sorted(
                combined_scores.items(), key=lambda x: x[1], reverse=True
            )
            passages, scores = zip(*sorted_results[:k])
            return list(passages), list(scores)

        except Exception as e:
            logging.error(f"Ensemble retrieval error: {e}")
            return [], []

    async def abatch_retrieve(
        self, queries: List[str], k: Optional[int] = None
    ) -> List[Tuple[List[str], List[float]]]:
        """Asyn batch retrieval

        Parameters
        ----------
        queries : List[str]
            List of input queries
        k : Optional[int], optional
            Number of passages to retrieve per query. The default is None.

        Returns
        -------
        (List[Tuple[List[str], List[float]]])
            List of (passages, scores) tuples for each query.
        """
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(self.retrieve(query, k)) for query in queries]
        return [task.result() for task in tasks]

    def set_fusion_method(self, method: FusionMethod):
        """Change fusion method

        Parameters
        ----------
        method : FusionMethod
            The fusion method to use
        """
        self.config.fusion_method = method
        logging.info(f"Fusion method changed to: {method.value}")

    def get_adaptive_weights_statistics(self) -> Dict[str, float]:
        """Statistics about adaptive weight decisions

        Returns
        -------
        Dict[str, float]
            Weight statistics
        """
        if (
            not hasattr(self, "adaptive_weights_history")
            or not self.adaptive_weights_history
        ):
            return {}

        bm25_weights = [w[0] for w in self.adaptive_weights_history]
        dense_weights = [w[1] for w in self.adaptive_weights_history]

        return {
            "avg_bm25_weight": np.mean(bm25_weights),
            "avg_dense_weight": np.mean(dense_weights),
            "std_bm25_weight": np.std(bm25_weights),
            "std_dense_weight": np.std(dense_weights),
            "decisions_count": len(self.adaptive_weights_history),
        }
