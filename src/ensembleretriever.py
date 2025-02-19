#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 16:07:22 2025

@author: kennethezukwoke
"""

import sys
import torch
import numpy as np

# --
import warnings
import asyncio
import logging

# --
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

warnings.simplefilter(action="ignore", category=FutureWarning)
# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


@dataclass
class EnsembleConfig:
    k: int = 10
    bm25_weight: float = 0.4
    dense_weight: float = 0.6
    rrf_k: int = 60
    batch_size: int = 32
    use_gpu: bool = True


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
            DESCRIPTION.
        config : Optional[EnsembleConfig], optional
            Ensemble reranking config. The default is None.

        Returns
        -------
        None.

        """
        self.config = config or EnsembleConfig()
        self.bm25_retriever = bm25_retriever
        self.dense_retriever = dense_retriever
        self.embedding_model = embedding_model  # Store embedding model
        self.texts = texts  # Store texts
        self.device = torch.device(
            "cuda" if torch.cuda.is_available() and self.config.use_gpu else "cpu"
        )

    async def _get_bm25_scores(
        self, query: str, k: int
    ) -> Tuple[List[str], Dict[str, float]]:
        """BM25 retriever scores

        Parameters
        ----------
        query (str): Query
        k (int): context size

        Returns
        -------
        (Tuple[List[str], Dict[str, float]])
            context w/ scores.

        """
        try:
            scores = self.bm25_retriever.get_scores(query)
            top_k_indices = np.argsort(scores)[-k:][::-1]
            passages = [self.bm25_retriever.documents[idx] for idx in top_k_indices]
            scores_dict = {
                passage: float(scores[idx])
                for passage, idx in zip(passages, top_k_indices)
            }
            return passages, scores_dict
        except Exception as e:
            logging.error(f"BM25 retrieval error: {e}")
            return [], {}

    async def _get_dense_scores(
        self, query: str, k: int
    ) -> Tuple[List[str], Dict[str, float]]:
        """Dense retriever score

        Parameters
        ----------
        query (str): Query
        k (int): context size

        Returns
        -------
        (Tuple[List[str], Dict[str, float]])
            context w/ scores.

        """
        try:
            # Create query embedding using the class's embedding model
            with torch.no_grad():
                query_embedding = self.embedding_model.encode(
                    [query],
                    convert_to_tensor=True,
                    show_progress_bar=False,
                    device=self.device,
                )
                # Convert to numpy and ensure proper shape
                query_embedding = query_embedding.cpu().numpy()

            if len(query_embedding.shape) == 2:
                query_embedding = query_embedding.astype("float32")
            else:
                query_embedding = query_embedding.reshape(1, -1).astype("float32")

            # Perform FAISS search
            D, I = self.dense_retriever.search(query_embedding, k)

            # Get passages and scores
            passages = [self.texts[idx] for idx in I[0]]
            scores_dict = {
                passage: float(score) for passage, score in zip(passages, D[0])
            }

            return passages, scores_dict

        except Exception as e:
            logging.error(f"Dense retrieval error: {e}")
            logging.error(
                f"Query embedding shape: {query_embedding.shape if 'query_embedding' in locals() else 'Not created'}"
            )
            return [], {}

    def _compute_rrf_scores(
        self, bm25_scores: Dict[str, float], dense_scores: Dict[str, float]
    ) -> Dict[str, float]:
        """


        Parameters
        ----------
        bm25_scores : Dict[str, float]
            BM25 scores.
        dense_scores : Dict[str, float]
            Dense (ex. FAISS) score .

        Returns
        -------
        Dict[str, float]
            RRF scores.

        """
        all_passages = set(bm25_scores.keys()) | set(dense_scores.keys())
        rrf_scores = {}

        for passage in all_passages:
            bm25_rank = (
                1 / (self.config.rrf_k + list(bm25_scores.keys()).index(passage) + 1)
                if passage in bm25_scores
                else 0
            )
            dense_rank = (
                1 / (self.config.rrf_k + list(dense_scores.keys()).index(passage) + 1)
                if passage in dense_scores
                else 0
            )

            rrf_scores[passage] = (
                self.config.bm25_weight * bm25_rank
                + self.config.dense_weight * dense_rank
            )

        return rrf_scores

    async def retrieve(
        self, query: str, k: Optional[int] = None
    ) -> Tuple[List[str], List[float]]:
        """Flash reranker retrieval


        Parameters
        ----------
        query (str): Input query
        k : Optional[int], optional
            context size. The default is None.

        Returns
        -------
        (Tuple[List[str], List[float]])
            context w/ scores.
        """
        k = k or self.config.k

        try:
            bm25_future = asyncio.create_task(self._get_bm25_scores(query, k))
            dense_future = asyncio.create_task(self._get_dense_scores(query, k))
            (
                (bm25_passages, bm25_scores),
                (dense_passages, dense_scores),
            ) = await asyncio.gather(bm25_future, dense_future)

            if not bm25_scores and not dense_scores:
                logging.warning("Both retrievers failed")
                return [], []

            # Compute RRF scores
            rrf_scores = self._compute_rrf_scores(bm25_scores, dense_scores)

            # Sort by RRF scores
            sorted_results = sorted(
                rrf_scores.items(), key=lambda x: x[1], reverse=True
            )

            passages, scores = zip(*sorted_results[:k])
            return list(passages), list(scores)

        except Exception as e:
            logging.error(f"Ensemble retrieval error: {e}")
            return [], []

    async def abatch_retrieve(
        self, queries: List[str], k: Optional[int] = None
    ) -> List[Tuple[List[str], List[float]]]:
        """Asynchrnous batch retrieval

        Parameters
        ----------
        queries : List[str]
            Input query.
        k : Optional[int], optional
            context size. The default is None.

        Returns
        -------
        (List[Tuple[List[str], List[float]]])
            context w/ scores.

        """
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(self.retrieve(query, k)) for query in queries]
        return [task.result() for task in tasks]
