#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 16:07:22 2025

@author: kennethezukwoke
"""
import sys
import torch
import numpy as np
import faiss
import warnings
import asyncio
import logging
import re
from src.utils import filter_by_metadata
from dataclasses import dataclass
from typing import Any, Optional
from enum import Enum

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
        texts: list[str],
        metadatas: Optional[list[dict]] = None,
        doc_metadatas: Optional[dict[Any, dict]] = None,
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
        texts : list[str]
            Text corpus for retrieving passages.
        metadatas : Optional[list[dict]], optional
            Metadata for each passage. The default is None.
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
        self.metadatas = metadatas or [{} for _ in texts]
        # Document-level metadata collection (keyed by doc_id)
        self.doc_metadatas = doc_metadatas or {}
        self.device = torch.device(
            "cuda"
            if torch.cuda.is_available() and self.config.use_gpu
            else "cpu"
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

    # ------------------------------------------------------------------
    # Metadata utilities
    # ------------------------------------------------------------------
    def _merge_chunk_and_document_metadata(self, chunk_meta: dict) -> dict:
        """Merge chunk-level metadata with the corresponding document-level metadata.

        In reference mode, chunk metadata contains only minimal information like 
        ``doc_id`` and ``chunk_id``. This method looks up the full document metadata 
        using the doc_id and merges it with the chunk metadata, with chunk-level 
        data taking precedence over document-level data when keys overlap.

        Parameters
        ----------
        chunk_meta : dict
            Chunk-level metadata containing at least a ``doc_id`` key

        Returns
        -------
        dict
            Merged metadata combining document-level and chunk-level information
        """
        if not chunk_meta:
            return {}

        doc_id = chunk_meta.get("doc_id")
        if doc_id is None or not self.doc_metadatas:
            return chunk_meta

        doc_meta = self.doc_metadatas.get(doc_id, {})
        # Chunk-level data should take precedence when keys overlap
        return {**doc_meta, **chunk_meta}

    async def _get_bm25_scores(
        self, query: str, k: int, meta_filter: dict | None = None
    ) -> tuple[list[str], dict[str, float], list[dict]]:
        """BM25 retriever scores with ranking

        Parameters
        ----------
        query (str): Query
        k (int): Number of documents to retrieve

        Returns
        -------
        (tuple[list[str], dict[str, float], list[dict]])
            Retrieved passages, their scores, and original ranks.
        """
        try:
            scores = self.bm25_retriever.get_scores(query)

            # If a filter is provided, restrict BM25 strictly to allowed indices
            candidate_indices = None
            if meta_filter:
                allowed = [i for i in self._compute_allowed_indices(meta_filter) if 0 <= i < len(scores)]
                if not allowed:
                    return [], {}, []
                candidate_indices = allowed
            else:
                candidate_indices = list(range(len(scores)))

            # Select top-k among candidate_indices only
            pairs = [(idx, float(scores[idx])) for idx in candidate_indices]
            pairs.sort(key=lambda t: t[1], reverse=True)
            top_k_indices = [idx for idx, _ in pairs[:k]]
            passages = [
                self.bm25_retriever.documents[idx] for idx in top_k_indices
            ]
            scores_dict = {
                passage: float(scores[idx])
                for passage, idx in zip(passages, top_k_indices)
            }
            meta_list = [self.metadatas[idx] if idx < len(self.metadatas) else {} for idx in top_k_indices]
            return passages, scores_dict, meta_list
        except Exception as e:
            logging.error(f"BM25 retrieval error: {e}")
            return [], {}, []

    def _faiss_search(
        self,
        index,
        query_embedding,
        k: int,
        texts: list[str],
        metas: list[dict],
    ) -> tuple[list[str], dict[str, float], list[dict]]:
        """Run FAISS search and format results consistently."""
        D, I = index.search(query_embedding, k)
        ids = I[0]
        passages = [texts[idx] for idx in ids]
        similarities = 1.0 / (1.0 + D[0])
        scores_dict = {p: float(s) for p, s in zip(passages, similarities)}
        meta_list = [metas[idx] if idx < len(metas) else {} for idx in ids]
        return passages, scores_dict, meta_list

    async def _get_dense_scores(
        self, query: str, k: int, meta_filter: dict | None = None
    ) -> tuple[list[str], dict[str, float], list[dict]]:
        """Dense retriever scores with ranking

        Parameters
        ----------
        query (str): Query
        k (int): Number of documents to retrieve

        Returns
        -------
        (tuple[list[str], dict[str, float], list[dict]])
            Retrieved passages, their scores, and original ranks.
        """
        try:
            if hasattr(self.dense_retriever, "search"):
                # # Path 1: FAISS index (has .search method)
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
                    query_embedding = query_embedding.reshape(1, -1).astype(
                        "float32"
                    )

                # If a meta_filter is provided, always restrict FAISS search to that subset
                if meta_filter:
                    allowed_indices = self._compute_allowed_indices(meta_filter)
                    if not allowed_indices:
                        return [], {}, []

                    subset_idx, subset_texts, subset_metas = self._get_or_build_subset_index(
                        allowed_indices, meta_filter
                    )
                    return self._faiss_search(
                        subset_idx, query_embedding, k, subset_texts, subset_metas
                    )

                # FAISS Search on full index (no filter)
                return self._faiss_search(
                    self.dense_retriever, query_embedding, k, self.texts, self.metadatas
                )

            # Path 2: Chroma (LangChain VectorStore) – use similarity_search_with_score
            if hasattr(self.dense_retriever, "similarity_search_with_score"):
                results = await asyncio.to_thread(
                    self.dense_retriever.similarity_search_with_score,
                    query,
                    k,
                )
                passages = [doc.page_content for doc, _ in results]
                scores_dict = {
                    doc.page_content: float(score) for doc, score in results
                }
                meta_list = [doc.metadata for doc, _ in results]
                return passages, scores_dict, meta_list

            logging.warning(
                "Dense retriever object lacks known retrieval interfaces; returning empty result."
            )
            return [], {}, []

        except Exception as e:
            logging.error(f"Dense retrieval error: {e}")
            return [], {}, []

    def _analyze_query_characteristics(self, query: str) -> dict[str, float]:
        """Analyze query characteristics for adaptive weighting

        Parameters
        ----------
        query : str
            Input query

        Returns
        -------
        dict[str, float]
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
        characteristics["is_question"] = (
            1.0 if query.strip().endswith("?") else 0.0
        )
        characteristics["has_wh_words"] = (
            1.0
            if bool(
                re.search(r"\b(what|when|where|who|why|how)\b", query.lower())
            )
            else 0.0
        )
        characteristics["has_numbers"] = (
            1.0 if bool(re.search(r"\d", query)) else 0.0
        )
        characteristics["has_quotes"] = (
            1.0 if '"' in query or "'" in query else 0.0
        )
        characteristics["has_boolean"] = (
            1.0 if bool(re.search(r"\b(and|or|not)\b", query.lower())) else 0.0
        )
        technical_words = [
            w for w in words if len(w) >= 6 and any(c.isupper() for c in w)
        ]
        characteristics["technical_ratio"] = (
            len(technical_words) / len(words) if words else 0.0
        )
        proper_nouns = [
            w for i, w in enumerate(words) if i > 0 and w[0].isupper()
        ]
        characteristics["proper_noun_ratio"] = (
            len(proper_nouns) / len(words) if words else 0.0
        )
        self.query_characteristics_cache[query] = characteristics
        return characteristics

    def _normalize_scores(self, scores: dict[str, float]) -> dict[str, float]:
        """Normalize scores to [0, 1] range using min-max normalization

        Parameters
        ----------
        scores : dict[str, float]
            scores.

        Returns
        -------
        dict[str, float]
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
            normalized_scores[passage] = (score - min_score) / (
                max_score - min_score
            )

        return normalized_scores

    def _compute_rrf_scores(
        self, bm25_scores: dict[str, float], dense_scores: dict[str, float]
    ) -> dict[str, float]:
        """Compute Reciprocal Rank Fusion scores

        Parameters
        ----------
        bm25_scores : dict[str, float]
            bm25 scores.
        dense_scores : dict[str, float]
            dense scores.

        Returns
        -------
        dict[str, float]
            rrf scores.
        """
        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        rrf_scores = {}
        bm25_ranked = sorted(
            bm25_scores.items(), key=lambda x: x[1], reverse=True
        )
        dense_ranked = sorted(
            dense_scores.items(), key=lambda x: x[1], reverse=True
        )
        bm25_ranks = {
            passage: rank for rank, (passage, _) in enumerate(bm25_ranked, 1)
        }
        dense_ranks = {
            passage: rank for rank, (passage, _) in enumerate(dense_ranked, 1)
        }

        for passage in all_passages:
            bm25_rrf = 1 / (
                self.config.rrf_k
                + bm25_ranks.get(passage, len(bm25_ranked) + 1)
            )
            dense_rrf = 1 / (
                self.config.rrf_k
                + dense_ranks.get(passage, len(dense_ranked) + 1)
            )
            rrf_scores[passage] = bm25_rrf + dense_rrf

        return rrf_scores

    def _compute_weighted_linear(
        self, bm25_scores: dict[str, float], dense_scores: dict[str, float]
    ) -> dict[str, float]:
        """Compute weighted linear combination

        Parameters
        ----------
        bm25_scores : dict[str, float]
            bm25 scores.
        dense_scores : dict[str, float]
            dense scores.

        Returns
        -------
        dict[str, float]
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
        bm25_scores: dict[str, float],
        dense_scores: dict[str, float],
    ) -> dict[str, float]:
        """Compute scores using query-adaptive weights

        Parameters
        ----------
        query : str
            input query.
        bm25_scores : dict[str, float]
            bm25 scores.
        dense_scores : dict[str, float]
            dense scores.

        Returns
        -------
        dict[str, float]
            query adaptive weights.

        """
        characteristics = self._analyze_query_characteristics(query)
        base_bm25_weight = self.config.bm25_weight
        if (
            characteristics["has_proper_nouns"]
            or characteristics["technical_ratio"] > 0.3
        ):
            bm25_weight = min(0.7, base_bm25_weight + 0.2)
        elif (
            characteristics["word_count"] > 15
            or characteristics["has_wh_words"]
        ):
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
        self, bm25_scores: dict[str, float], dense_scores: dict[str, float]
    ) -> dict[str, float]:
        """Compute scores using score-based adaptive weights

        Parameters
        ----------
        bm25_scores : dict[str, float]
            bm25 scores.
        dense_scores : dict[str, float]
            dense scores.

        Returns
        -------
        dict[str, float]
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
            dense_confidence = dense_var / total_confidence
        else:
            bm25_confidence = 0.5
            dense_confidence = 0.5

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
        self, bm25_scores: dict[str, float], dense_scores: dict[str, float]
    ) -> dict[str, float]:
        """Compute harmonic mean of scores

        Parameters
        ----------
        bm25_scores : dict[str, float]
            bm25 scores.
        dense_scores : dict[str, float]
            dense scores.

        Returns
        -------
        dict[str, float]
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
        self, bm25_scores: dict[str, float], dense_scores: dict[str, float]
    ) -> dict[str, float]:
        """Compute geometric mean of scores

        Parameters
        ----------
        bm25_scores : dict[str, float]
            bm25_scores.
        dense_scores : dict[str, float]
            dense scores.

        Returns
        -------
        dict[str, float]
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
        self, bm25_scores: dict[str, float], dense_scores: dict[str, float]
    ) -> dict[str, float]:
        """Compute min-max fusion (take max of normalized scores)

        Parameters
        ----------
        bm25_scores : dict[str, float]
            bm25 scores.
        dense_scores : dict[str, float]
            dense scores.

        Returns
        -------
        dict[str, float]
            min-max fusion scores.

        """
        bm25_scores_norm = self._normalize_scores(bm25_scores)
        dense_scores_norm = self._normalize_scores(dense_scores)
        all_passages = set(bm25_scores_norm.keys()) | set(
            dense_scores_norm.keys()
        )
        combined_scores = {}

        for passage in all_passages:
            bm25_score = bm25_scores_norm.get(passage, 0.0)
            dense_score = dense_scores_norm.get(passage, 0.0)
            combined_scores[passage] = max(bm25_score, dense_score)

        return combined_scores

    def _compute_rank_fusion(
        self, bm25_scores: dict[str, float], dense_scores: dict[str, float]
    ) -> dict[str, float]:
        """Compute rank-based fusion

        Parameters
        ----------
        bm25_scores : dict[str, float]
            DESCRIPTION.
        dense_scores : dict[str, float]
            DESCRIPTION.

        Returns
        -------
        dict[str, float]
            rank fusion scores.
        """
        bm25_ranked = sorted(
            bm25_scores.items(), key=lambda x: x[1], reverse=True
        )
        dense_ranked = sorted(
            dense_scores.items(), key=lambda x: x[1], reverse=True
        )
        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        combined_scores = {}

        max_rank = max(len(bm25_ranked), len(dense_ranked))

        for passage in all_passages:
            bm25_rank = next(
                (
                    i + 1
                    for i, (p, _) in enumerate(bm25_ranked)
                    if p == passage
                ),
                max_rank + 1,
            )
            dense_rank = next(
                (
                    i + 1
                    for i, (p, _) in enumerate(dense_ranked)
                    if p == passage
                ),
                max_rank + 1,
            )
            bm25_rank_score = 1.0 / bm25_rank
            dense_rank_score = 1.0 / dense_rank

            combined_scores[passage] = bm25_rank_score + dense_rank_score

        return combined_scores

    def _compute_combsum(
        self, bm25_scores: dict[str, float], dense_scores: dict[str, float]
    ) -> dict[str, float]:
        """Compute CombSUM (normalized sum)

        Parameters
        ----------
        bm25_scores : dict[str, float]
            bm25 scores.
        dense_scores : dict[str, float]
            dense scores.

        Returns
        -------
        dict[str, float]
            additive scores.

        """
        bm25_scores_norm = self._normalize_scores(bm25_scores)
        dense_scores_norm = self._normalize_scores(dense_scores)

        all_passages = set(bm25_scores_norm.keys()) | set(
            dense_scores_norm.keys()
        )
        combined_scores = {}

        for passage in all_passages:
            bm25_score = bm25_scores_norm.get(passage, 0.0)
            dense_score = dense_scores_norm.get(passage, 0.0)
            combined_scores[passage] = bm25_score + dense_score

        return combined_scores

    def _compute_combmnz(
        self, bm25_scores: dict[str, float], dense_scores: dict[str, float]
    ) -> dict[str, float]:
        """Compute CombMNZ


        Parameters
        ----------
        bm25_scores : dict[str, float]
            bm25 scores.
        dense_scores : dict[str, float]
            dense scores.

        Returns
        -------
        dict[str, float]
            combines non-zero scores.

        """
        bm25_scores_norm = self._normalize_scores(bm25_scores)
        dense_scores_norm = self._normalize_scores(dense_scores)

        all_passages = set(bm25_scores_norm.keys()) | set(
            dense_scores_norm.keys()
        )
        combined_scores = {}

        for passage in all_passages:
            bm25_score = bm25_scores_norm.get(passage, 0.0)
            dense_score = dense_scores_norm.get(passage, 0.0)
            non_zero_count = sum(
                [1 for score in [bm25_score, dense_score] if score > 0]
            )
            combined_scores[passage] = (
                bm25_score + dense_score
            ) * non_zero_count

        return combined_scores

    def _fuse_scores(
        self,
        query: str,
        bm25_scores: dict[str, float],
        dense_scores: dict[str, float],
    ) -> dict[str, float]:
        """Fuse scores using the selected method

        Parameters
        ----------
        query : str
            input query.
        bm25_scores : dict[str, float]
            bm25 scores.
        dense_scores : dict[str, float]
            dense scores.

        Returns
        -------
        dict[str, float]
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
            return self._compute_score_adaptive_weights(
                bm25_scores, dense_scores
            )
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
            return self._compute_score_adaptive_weights(
                bm25_scores, dense_scores
            )

    async def retrieve(
        self, query: str, k: Optional[int] = None, meta_filter: dict | None = None
    ) -> tuple[list[str], list[float], list[dict]]:
        """Retrieve passages using the selected fusion method

        Parameters
        ----------
        query (str): Input query
        k : Optional[int], optional
            Number of passages to retrieve. The default is None.

        Returns
        -------
        (tuple[list[str], list[float], list[dict]])
            Retrieved passages and their combined scores.
        """
        k = k or self.config.k

        # Log: pre-filter corpus snapshot and allowed subset summary
        if meta_filter:
            total = len(self.texts)
            pre_sample = []
            for m in (self.metadatas[: min(10, len(self.metadatas))] or []):
                if isinstance(m, dict):
                    pre_sample.append({
                        'doc_id': m.get('doc_id'),
                        'chunk_id': m.get('chunk_id'),
                    })
            logging.info(
                "MetaFilter pre: corpus_size=%d sample(doc_id,chunk_id)=%s",
                total,
                pre_sample,
            )

            allowed_dbg = self._compute_allowed_indices(meta_filter)
            allowed_sample = []
            for i in allowed_dbg[: min(10, len(allowed_dbg))]:
                m = self.metadatas[i] if i < len(self.metadatas) else {}
                if isinstance(m, dict):
                    allowed_sample.append({
                        'index': i,
                        'doc_id': m.get('doc_id'),
                        'chunk_id': m.get('chunk_id'),
                    })
            logging.info(
                "MetaFilter post: allowed_size=%d sample(index,doc_id,chunk_id)=%s",
                len(allowed_dbg),
                allowed_sample,
            )

        try:
            candidate_k = k * 2
            bm25_future = asyncio.create_task(
                self._get_bm25_scores(query, candidate_k, meta_filter)
            )
            dense_future = asyncio.create_task(
                self._get_dense_scores(query, candidate_k, meta_filter)
            )

            (bm25_passages, bm25_scores, bm25_meta_list), (
                dense_passages,
                dense_scores,
                dense_meta_list,
            ) = await asyncio.gather(bm25_future, dense_future)
            if not bm25_scores and not dense_scores:
                logging.warning("Both retrievers failed")
                return [], [], []

            if not bm25_scores:
                logging.warning(
                    "BM25 retriever returned no results, using dense only"
                )
                sorted_results = sorted(
                    dense_scores.items(), key=lambda x: x[1], reverse=True
                )
                passages, scores = zip(*sorted_results[:k])
                metas = dense_meta_list[: len(passages)]
                return list(passages), list(scores), metas

            if not dense_scores:
                logging.warning(
                    "Dense retriever returned no results, using BM25 only"
                )
                sorted_results = sorted(
                    bm25_scores.items(), key=lambda x: x[1], reverse=True
                )
                passages, scores = zip(*sorted_results[:k])
                metas = bm25_meta_list[: len(passages)]
                return list(passages), list(scores), metas

            # -- fuse scores
            combined_scores = self._fuse_scores(
                query, bm25_scores, dense_scores
            )
            sorted_results = sorted(
                combined_scores.items(), key=lambda x: x[1], reverse=True
            )
            passages, scores = zip(*sorted_results[:k])
            metas = []
            meta_lookup = {text: meta for text, meta in zip(self.texts, self.metadatas)}
            for p in passages:
                if p in meta_lookup:
                    metas.append(meta_lookup[p])
                elif p in bm25_passages:
                    idx = bm25_passages.index(p)
                    metas.append(bm25_meta_list[idx])
                elif p in dense_passages:
                    idx = dense_passages.index(p)
                    metas.append(dense_meta_list[idx])
                else:
                    metas.append({})

            # Merge chunk-level metadata with document-level metadata
            metas = [self._merge_chunk_and_document_metadata(m) for m in metas]
            
            # Debug: log merged metadata
            if self.doc_metadatas:
                logging.debug(f"EnsembleRetriever: Merged {len(metas)} chunk+document metadata entries")
                for i, meta in enumerate(metas[:1]):  # Log first 1 for debugging
                    logging.debug(f"  Merged Meta {i}: {meta}")
            else:
                logging.debug("EnsembleRetriever: No doc_metadatas available for metadata merging")
                
            return list(passages), list(scores), metas

        except Exception as e:
            logging.error(f"Ensemble retrieval error: {e}")
            return [], [], []

    # -------------------------------
    # Filtering helpers and caching
    # -------------------------------
    def _canonicalize_filter(self, meta_filter: dict) -> str:
        items: list[str] = []
        for k in sorted(meta_filter.keys()):
            v = meta_filter[k]
            if isinstance(v, (list, set, tuple)):
                vals = ",".join(sorted(map(str, v)))
            else:
                vals = str(v)
            items.append(f"{k}={vals}")
        return "|".join(items)

    def _compute_allowed_indices(self, meta_filter: dict) -> list[int]:
        """Return list of indices in self.texts that satisfy meta_filter.

        Merges chunk metadata with document-level metadata (if available).
        """
        items = []
        for idx, chunk_meta in enumerate(self.metadatas):
            if not isinstance(chunk_meta, dict):
                chunk_meta = {}
            # Merge document-level metadata if present
            merged = self._merge_chunk_and_document_metadata(chunk_meta) if "doc_id" in chunk_meta else chunk_meta
            merged = dict(merged)
            merged["__index__"] = idx
            items.append((None, merged))

        filtered = filter_by_metadata(items, meta_filter)
        allowed: list[int] = []
        for _, meta in filtered:
            idx = meta.get("__index__") if isinstance(meta, dict) else None
            if isinstance(idx, int):
                allowed.append(idx)
        return allowed

    def _get_or_build_subset_index(self, allowed_indices: list[int], meta_filter: dict):
        """Build or fetch a cached FAISS index over the subset defined by allowed_indices."""
        if not hasattr(self, "_subset_cache"):
            self._subset_cache = {}
            self._subset_order = []
            self._subset_capacity = 4

        sig = self._canonicalize_filter(meta_filter)
        if sig in self._subset_cache:
            # LRU touch
            if sig in self._subset_order:
                self._subset_order.remove(sig)
            self._subset_order.append(sig)
            entry = self._subset_cache[sig]
            return entry["index"], entry["texts"], entry["metas"]

        # Build subset arrays
        subset_texts = [self.texts[i] for i in allowed_indices if 0 <= i < len(self.texts)]
        subset_metas = [self.metadatas[i] if i < len(self.metadatas) else {} for i in allowed_indices]

        # Compute embeddings
        with torch.no_grad():
            emb = self.embedding_model.encode(
                subset_texts,
                convert_to_tensor=True,
                show_progress_bar=False,
                device=self.device,
            )
            emb = emb.cpu().numpy().astype("float32")
        faiss.normalize_L2(emb)
        sub_index = faiss.IndexFlatL2(emb.shape[1])
        sub_index.add(emb)

        # Cache with LRU policy
        self._subset_cache[sig] = {"index": sub_index, "texts": subset_texts, "metas": subset_metas}
        self._subset_order.append(sig)
        if len(self._subset_order) > self._subset_capacity:
            evict = self._subset_order.pop(0)
            self._subset_cache.pop(evict, None)

        return sub_index, subset_texts, subset_metas

    async def abatch_retrieve(
        self, queries: list[str], k: Optional[int] = None
    ) -> list[tuple[list[str], list[float], list[dict]]]:
        """Asyn batch retrieval

        Parameters
        ----------
        queries : list[str]
            List of input queries
        k : Optional[int], optional
            Number of passages to retrieve per query. The default is None.

        Returns
        -------
        (list[tuple[list[str], list[float], list[dict]]])
            List of (passages, scores, metadata) tuples for each query.
        """
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self.retrieve(query, k)) for query in queries
            ]
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

    def get_adaptive_weights_statistics(self) -> dict[str, float]:
        """Statistics about adaptive weight decisions

        Returns
        -------
        dict[str, float]
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
