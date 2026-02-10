"""
Created on Fri Feb 7 15:48:53 2025

@author: kennethezukwoke
"""

import asyncio
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from src.ensembleretriever import EnsembleRetriever
from src.flashreranker import FlashReranker

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
        passages : List[str]
            context.

        Returns
        -------
        (Tuple[List[str], List[float]])
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
        passages : List[str]
            context.
        scores : List[float]
            relevance scores.

        Returns
        -------
        (Tuple[List[str], List[float]])
            contexts w/ scores.

        """
        if not passages:
            return [], []

        k = max(1, int(len(passages) * self.config.compression_ratio))
        return passages[:k], scores[:k]

    async def retrieve_and_compress(
        self, query: str, k: Optional[int] = None
    ) -> tuple[list[str], list[float]]:
        """Retrieve and compress

        Parameters
        ----------
        query : str
            input query.
        k : Optional[int], optional
            context size. The default is None.

        Returns
        -------
        (Tuple[List[str], List[float]])
            contexts w/ scores.

        """
        try:
            base_passages, base_scores = await self.base_retriever.retrieve(query, k)

            if not base_passages:
                return [], []

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

            # --  compressed contxets
            final_passages, final_scores = await self._compress_results(
                reranked_passages, scores
            )

            return final_passages, final_scores

        except Exception as e:
            logging.error(f"Error in retrieve_and_compress: {e}")
            return [], []

    async def abatch_retrieve_and_compress(
        self, queries: list[str], k: Optional[int] = None
    ) -> list[tuple[list[str], list[float]]]:
        """Asynchronous retrieving and compressing

        Parameters
        ----------
        queries : List[str]
            queries.
        k : Optional[int], optional
            context size. The default is None.

        Returns
        -------
        (List[Tuple[List[str], List[float]]])
            k-queries and scores.

        """
        try:
            async with asyncio.TaskGroup() as tg:
                tasks = [
                    tg.create_task(self.retrieve_and_compress(query, k))
                    for query in queries
                ]
            return [task.result() for task in tasks]

        except Exception as e:
            logging.error(f"Batch retrieval error: {e}")
            return [([], []) for _ in queries]

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
        self, query: str, k: Optional[int] = None
    ) -> tuple[list[str], list[float]]:
        """Retrieval

        Parameters
        ----------
        query (str): query
        k : Optional[int], optional
            k-context. The default is None.

        Returns
        -------
        (Tuple[List[str], List[float]])
            contexts.

        """
        return self.run_async(self.retrieve_and_compress(query, k))

    def batch_retrieve(
        self, queries: list[str], k: Optional[int] = None
    ) -> list[tuple[list[str], list[float]]]:
        """Batch retrieval

        Parameters
        ----------
        queries : List[str]
            k-queries.
        k : Optional[int], optional
            context size. The default is None.

        Returns
        -------
        (List[Tuple[List[str], List[float]]])
            k-retrievals.

        """
        return self.run_async(self.abatch_retrieve_and_compress(queries, k))
