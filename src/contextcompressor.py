#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 7 15:48:53 2025

@author: kennethezukwoke
"""
import os
import sys
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from src.flashreranker import FlashReranker
from src.ensembleretriever import EnsembleRetriever
from concurrent.futures import ThreadPoolExecutor

# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


@dataclass
class ContextualConfig:
    k: int = 10
    rerank_batch_size: int = 64
    compression_ratio: float = 0.7
    use_threading: bool = True
    max_concurrent_tasks: int = min(64, os.cpu_count() * 4)


class ContextualCompressionRetriever:
    def __init__(
        self,
        base_retriever: "EnsembleRetriever",
        reranker: "FlashReranker",
        config: Optional[ContextualConfig] = None,
    ):
        """
        Context Compression Retriever

        Parameters
        ----------
        base_retriever : "EnsembleRetriever"
            base retriever uses Recriprocal Rank Fusion (RRF).
        reranker : "FlashReranker"
            Flash reranker.
        config : Optional[ContextualConfig], optional
            Context config. The default is None.

        Returns
        -------
        None.

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
        self._executor.shutdown(wait=False)

    async def _process_batch(
        self, query: str, passages: list[str]
    ) -> tuple[list[str], list[float]]:
        """Batch processing

        Parameters
        ----------
        query (str): input query
        passages : list[str]
            context.

        Returns
        -------
        (tuple[list[str], list[float]])
            context/passages.
        """
        try:
            reranked_passages, scores = self.reranker.rerank(
                query, passages, return_scores=True
            )
            return reranked_passages, scores
        except Exception as e:
            logging.error(f"Reranking error in batch processing: {e}")
            return passages, [0.0] * len(passages)

    async def _compress_results(
        self, passages: list[str], scores: list[float]
    ) -> tuple[list[str], list[float]]:
        """Compressing context

        Parameters
        ----------
        passages : list[str]
            context.
        scores : list[float]
            relevance scores.

        Returns
        -------
        (tuple[list[str], list[float]])
            contexts w/ scores.

        """
        if not passages:
            return [], []

        k = max(1, int(len(passages) * self.config.compression_ratio))
        return passages[:k], scores[:k]

    async def retrieve_and_compress(
        self, query: str, k: Optional[int] = None, meta_filter: dict | None = None
    ) -> tuple[list[str], list[float], list[dict]]:
        """Retrieve and compress

        Parameters
        ----------
        query : str
            input query.
        k : Optional[int], optional
            context size. The default is None.

        Returns
        -------
        (tuple[list[str], list[float], list[dict]])
            contexts w/ scores and metadata.

        """
        try:
            base_passages, base_scores, base_metadatas = await self.base_retriever.retrieve(
                query, k, meta_filter
            )

            if not base_passages:
                return [], [], []

            # -- rerank results
            if self.config.use_threading:
                loop = asyncio.get_event_loop()
                reranked_passages, scores = await loop.run_in_executor(
                    self._executor,
                    self.reranker.rerank,
                    query,
                    base_passages,
                    True,
                )
            else:
                reranked_passages, scores = await self._process_batch(
                    query, base_passages
                )

            # --  compressed contexts and preserve metadata order
            final_passages, final_scores = await self._compress_results(
                reranked_passages, scores
            )
            
            # Preserve metadata aligned with reranked/compressed passages
            passage_to_meta = {passage: meta for passage, meta in zip(base_passages, base_metadatas)}
            final_metadatas = [passage_to_meta.get(passage, {}) for passage in final_passages]

            # Debug: log preserved metadata
            logging.debug(f"ContextualCompressionRetriever: Preserved {len(final_metadatas)} metadata entries")
            for i, meta in enumerate(final_metadatas[:1]):  # Log first 1 for debugging
                logging.debug(f"  Preserved Meta {i}: {meta}")

            return final_passages, final_scores, final_metadatas

        except Exception as e:
            logging.error(f"Error in retrieve_and_compress: {e}")
            return [], [], []

    async def abatch_retrieve_and_compress(
        self, queries: list[str], k: Optional[int] = None, meta_filter: dict | None = None
    ) -> list[tuple[list[str], list[float], list[dict]]]:
        """Asynchronous retrieving and compressing

        Parameters
        ----------
        queries : list[str]
            queries.
        k : Optional[int], optional
            context size. The default is None.

        Returns
        -------
        (list[tuple[list[str], list[float], list[dict]]])
            k-queries, scores, and metadata.

        """
        try:
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(self.retrieve_and_compress(query, k, meta_filter))
                    for query in queries
                ]
            return [task.result() for task in tasks]

        except Exception as e:
            logging.error(f"Batch retrieval error: {e}")
            return [([], [], []) for _ in queries]

    def run_async(self, coro):
        """Asynchronous run

        Parameters
        ----------
        coro : co-routine
            co-routine.

        Returns
        -------
        coro
            asynchronous co-routine.

        """
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def retrieve(
        self, query: str, k: Optional[int] = None, meta_filter: dict | None = None
    ) -> tuple[list[str], list[float], list[dict]]:
        """Retrieval

        Parameters
        ----------
        query (str): query
        k : Optional[int], optional
            k-context. The default is None.

        Returns
        -------
        (tuple[list[str], list[float], list[dict]])
            contexts, scores, and metadata.

        """
        return self.run_async(self.retrieve_and_compress(query, k, meta_filter))

    def batch_retrieve(
        self, queries: list[str], k: Optional[int] = None, meta_filter: dict | None = None
    ) -> list[tuple[list[str], list[float], list[dict]]]:
        """Batch retrieval

        Parameters
        ----------
        queries : list[str]
            k-queries.
        k : Optional[int], optional
            context size. The default is None.

        Returns
        -------
        (list[tuple[list[str], list[float], list[dict]]])
            k-retrievals with metadata.

        """
        return self.run_async(self.abatch_retrieve_and_compress(queries, k, meta_filter))
