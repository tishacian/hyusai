#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 7 15:48:53 2025

@author: kennethezukwoke
"""
import warnings
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sys
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple
from flashreranker import FlashReranker
from ensembleretriever import EnsembleRetriever

warnings.simplefilter(action="ignore", category=FutureWarning)
# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# %% Context Compression Retriever


@dataclass
class ContextualConfig:
    k: int = 10
    rerank_batch_size: int = 32
    compression_ratio: float = 0.7
    use_threading: bool = True
    max_concurrent_tasks: int = 5


class ContextualCompressionRetriever:
    def __init__(
        self,
        base_retriever: "EnsembleRetriever",
        reranker: "FlashReranker",
        config: Optional[ContextualConfig] = None,
    ):
        self.base_retriever = base_retriever
        self.reranker = reranker
        self.config = config or ContextualConfig()
        self._executor = ThreadPoolExecutor(
            max_workers=self.config.max_concurrent_tasks
        )

    def __del__(self):
        self._executor.shutdown(wait=False)

    async def _process_batch(
        self, query: str, passages: List[str]
    ) -> Tuple[List[str], List[float]]:
        try:
            reranked_passages, scores = self.reranker.rerank(
                query, passages, return_scores=True
            )
            return reranked_passages, scores
        except Exception as e:
            logging.error(f"Reranking error in batch processing: {e}")
            return passages, [0.0] * len(passages)

    async def _compress_results(
        self, passages: List[str], scores: List[float]
    ) -> Tuple[List[str], List[float]]:
        if not passages:
            return [], []

        k = max(1, int(len(passages) * self.config.compression_ratio))
        return passages[:k], scores[:k]

    async def retrieve_and_compress(
        self, query: str, k: Optional[int] = None
    ) -> Tuple[List[str], List[float]]:
        try:
            # Get initial results from ensemble retriever
            base_passages, base_scores = await self.base_retriever.retrieve(
                query, k
            )

            if not base_passages:
                return [], []

            # Rerank results
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

            # Compress results
            final_passages, final_scores = await self._compress_results(
                reranked_passages, scores
            )

            return final_passages, final_scores

        except Exception as e:
            logging.error(f"Error in retrieve_and_compress: {e}")
            return [], []

    async def abatch_retrieve_and_compress(
        self, queries: List[str], k: Optional[int] = None
    ) -> List[Tuple[List[str], List[float]]]:
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
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def retrieve(
        self, query: str, k: Optional[int] = None
    ) -> Tuple[List[str], List[float]]:
        return self.run_async(self.retrieve_and_compress(query, k))

    def batch_retrieve(
        self, queries: List[str], k: Optional[int] = None
    ) -> List[Tuple[List[str], List[float]]]:
        return self.run_async(self.abatch_retrieve_and_compress(queries, k))
