#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 16:58:25 2025

@author: kennethezukwoke
"""

import re
import sys
import logging
import numpy as np
import asyncio
from typing import Tuple
from functools import lru_cache
from globalvariables import ReasoningType, ReasoningPatterns

# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class ReasoningMetrics:
    """Enhanced reasoning detection and scoring during search"""

    def __init__(self, embedding_model):
        """
        Parameters
            embedding_model (model): embedding model

        Returns
            None.
        """
        self.embedding_model = embedding_model
        self.reasoning_patterns = ReasoningPatterns
        # TF-IDF weights for reasoning patterns
        self.reasoning_weights = {
            ReasoningType.FACTUAL: 1.4,
            ReasoningType.ANALYTICAL: 1.25,
            ReasoningType.COMPARATIVE: 1.0,
            ReasoningType.CAUSAL: 1.2,
            ReasoningType.HYPOTHETICAL: 0.8,
        }

        self.entropy_thresholds = {
            ReasoningType.FACTUAL: 0.25,
            ReasoningType.ANALYTICAL: 0.35,
            ReasoningType.COMPARATIVE: 0.45,
            ReasoningType.CAUSAL: 0.3,
            ReasoningType.HYPOTHETICAL: 0.5,
        }

        self.quality_multipliers = {
            "coherence": {
                ReasoningType.FACTUAL: 1.3,
                ReasoningType.ANALYTICAL: 1.25,
                ReasoningType.COMPARATIVE: 1.1,
                ReasoningType.CAUSAL: 1.2,
                ReasoningType.HYPOTHETICAL: 1.0,
            },
            "factuality": {
                ReasoningType.FACTUAL: 1.4,
                ReasoningType.ANALYTICAL: 1.2,
                ReasoningType.COMPARATIVE: 1.1,
                ReasoningType.CAUSAL: 1.15,
                ReasoningType.HYPOTHETICAL: 0.9,
            },
            "relevance": {
                ReasoningType.FACTUAL: 1.25,
                ReasoningType.ANALYTICAL: 1.2,
                ReasoningType.COMPARATIVE: 1.15,
                ReasoningType.CAUSAL: 1.1,
                ReasoningType.HYPOTHETICAL: 1.0,
            },
        }

        self._embedding_cache = {}
        self._pattern_cache = {}
        self._reasoning_type_cache = {}
        # -- precompute reasoning embedding
        self._precompute_reasoning_embeddings()

    def _precompute_reasoning_embeddings(self):
        """Precompute and cache embeddings for reasoning types"""
        self._reasoning_type_embeddings = {}
        reasoning_texts = [str(rtype.value) for rtype in ReasoningType]

        try:
            embeddings = self.embedding_model.encode(reasoning_texts)
            for i, rtype in enumerate(ReasoningType):
                self._reasoning_type_embeddings[rtype] = embeddings[i]
        except Exception as e:
            logging.error(f"Error precomputing reasoning embeddings: {e}")

    @lru_cache(maxsize=128)
    def compute_cosine_similarity(self, vec1_key: str, vec2_key: str) -> float:
        """Compute cosine similarity using cached vectors

        Parameters
        ----------
        vec1_key : str
            Key for vector 1 in cache
        vec2_key : str
            Key for vector 2 in cache

        Returns
        -------
        float
            Cosine similarity
        """
        vec1 = self._embedding_cache.get(vec1_key)
        vec2 = self._embedding_cache.get(vec2_key)

        if vec1 is None or vec2 is None:
            return 0.0

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        return dot_product / (norm1 * norm2) if norm1 * norm2 != 0 else 0.0

    @lru_cache(maxsize=128)
    def compute_pattern_entropy(
        self, text_hash: str, pattern_type: ReasoningType
    ) -> float:
        """Compute entropy of reasoning patterns in text using Shannon entropy

        Parameters
        ----------
        text_hash (str): hash of input text for caching
        pattern_type : ReasoningType
            reasoning pattern type

        Returns
        -------
        float
            entropy.
        """
        text = self._pattern_cache.get(text_hash)  # from cache
        if text is None:
            return 0.0

        patterns = self.reasoning_patterns[pattern_type]
        pattern_counts = np.zeros(len(patterns))
        total_patterns = 0

        for i, pattern in enumerate(patterns):
            count = len(re.findall(r"\b" + pattern + r"\b", text.lower()))
            pattern_counts[i] = count
            total_patterns += count

        if total_patterns == 0:
            return 0.0

        probabilities = pattern_counts / total_patterns
        probabilities = probabilities[probabilities > 0]

        return -np.sum(probabilities * np.log2(probabilities))

    async def get_text_embedding_async(self, text: str) -> np.ndarray:
        """Get text embedding with caching

        Parameters
        ----------
        text : str
            Input text

        Returns
        -------
        np.ndarray
            Text embedding
        """
        text_hash = hash(text)
        if text_hash in self._embedding_cache:
            return self._embedding_cache[text_hash]

        try:
            self._pattern_cache[text_hash] = text
            embedding = await asyncio.to_thread(
                self.embedding_model.encode, [text]
            )
            result = embedding[0]
            self._embedding_cache[text_hash] = result
            return result
        except Exception as e:
            logging.error(f"Error getting text embedding: {e}")
            return np.zeros(
                self.embedding_model.get_sentence_embedding_dimension()
            )

    async def compute_semantic_coherence_async(
        self, text: str, reasoning_type: ReasoningType
    ) -> float:
        """Compute semantic coherence score using embedding similarity

        Parameters
        ----------
        text (str): Input text.
        reasoning_type : ReasoningType
            reasoning type.

        Returns
        -------
        float
            coherence.
        """
        text_hash = hash(text)
        if text_hash not in self._embedding_cache:
            await self.get_text_embedding_async(text)
        # --
        type_embedding = self._reasoning_type_embeddings.get(reasoning_type)
        if type_embedding is None:
            type_text = str(reasoning_type.value)
            type_embedding = await asyncio.to_thread(
                self.embedding_model.encode, [type_text]
            )
            type_embedding = type_embedding[0]
            self._reasoning_type_embeddings[reasoning_type] = type_embedding

        # Compute similarity
        return self.compute_cosine_similarity(
            text_hash, hash(str(reasoning_type.value))
        )

    async def bayesian_reasoning_detection_async(
        self, question: str
    ) -> Tuple[ReasoningType, float]:
        """Reasoning type detection w/ Bayesian inference

        Parameters
        ----------
        question (str): Input prompt

        Returns
        -------
        Tuple[ReasoningType, float]
            reasoning type and confidence score
        """
        question_hash = hash(question)
        if question_hash in self._reasoning_type_cache:
            return self._reasoning_type_cache[question_hash]

        self._pattern_cache[question_hash] = question
        question_embedding = await self.get_text_embedding_async(question)
        self._embedding_cache[question_hash] = question_embedding
        priors = {rtype: 1 / len(ReasoningType) for rtype in ReasoningType}
        evidence = {}
        tasks = []
        for rtype in ReasoningType:
            task = self._compute_evidence_for_type(
                question, question_hash, rtype
            )
            tasks.append(task)
        # -- score
        evidence_results = await asyncio.gather(*tasks)
        for rtype, score in evidence_results:
            evidence[rtype] = score

        # Calculate posterior prob
        total_evidence = sum(evidence.values())
        if total_evidence == 0:
            result = (ReasoningType.ANALYTICAL, 0.5)
            self._reasoning_type_cache[question_hash] = result
            return result

        posteriors = {
            rtype: (evidence[rtype] / total_evidence) * priors[rtype]
            for rtype in ReasoningType
        }
        best_type = max(posteriors.items(), key=lambda x: x[1])
        result = (best_type[0], best_type[1])
        self._reasoning_type_cache[question_hash] = result
        return result

    async def _compute_evidence_for_type(
        self, question: str, question_hash: int, rtype: ReasoningType
    ):
        """Compute evidence score for a single reasoning type

        Parameters
        ----------
        question : str
            Input question
        question_hash : int
            Hash of the question for cache lookup
        rtype : ReasoningType
            Reasoning type to evaluate

        Returns
        -------
        Tuple[ReasoningType, float]
            Reasoning type and its evidence score
        """
        entropy = self.compute_pattern_entropy(question_hash, rtype)
        entropy_score = (
            1.0 if entropy >= self.entropy_thresholds[rtype] else 0.5
        )

        coherence_score = await self.compute_semantic_coherence_async(
            question, rtype
        )
        pattern_score = sum(
            1
            for pattern in self.reasoning_patterns[rtype]
            if pattern in question.lower()
        ) / len(self.reasoning_patterns[rtype])

        # -- evidence using weighted geometric mean
        evidence_score = (
            entropy_score * 0.7 + coherence_score * 0.2 + pattern_score * 0.1
        ) * self.reasoning_weights[rtype]

        return (rtype, evidence_score)

    def bayesian_reasoning_detection(
        self, question: str
    ) -> Tuple[ReasoningType, float]:
        """Synchronous wrapper for bayesian_reasoning_detection_async

        Parameters
        ----------
        question (str): Input prompt

        Returns
        -------
        Tuple[ReasoningType, float]
            reasoning type and confidence
        """
        question_hash = hash(question)
        if question_hash in self._reasoning_type_cache:
            return self._reasoning_type_cache[question_hash]

        priors = {rtype: 1 / len(ReasoningType) for rtype in ReasoningType}
        evidence = {}
        self._pattern_cache[question_hash] = question
        for rtype in ReasoningType:
            entropy = self.compute_pattern_entropy(question_hash, rtype)
            entropy_score = (
                1.0 if entropy >= self.entropy_thresholds[rtype] else 0.5
            )
            text_embedding = self.embedding_model.encode([question])[0]
            self._embedding_cache[question_hash] = text_embedding
            if rtype in self._reasoning_type_embeddings:
                type_embedding = self._reasoning_type_embeddings[rtype]
            else:
                type_embedding = self.embedding_model.encode(
                    [str(rtype.value)]
                )[0]
                self._reasoning_type_embeddings[rtype] = type_embedding
            # -- compute cosine
            dot_product = np.dot(text_embedding, type_embedding)
            norm1 = np.linalg.norm(text_embedding)
            norm2 = np.linalg.norm(type_embedding)
            coherence_score = (
                dot_product / (norm1 * norm2) if norm1 * norm2 != 0 else 0.0
            )
            pattern_score = sum(
                1
                for pattern in self.reasoning_patterns[rtype]
                if pattern in question.lower()
            ) / len(self.reasoning_patterns[rtype])
            # -- evidence using weighted geometric mean
            evidence[rtype] = (
                entropy_score * 0.7
                + coherence_score * 0.2
                + pattern_score * 0.1
            ) * self.reasoning_weights[rtype]

        # -- compute posterior prob
        total_evidence = sum(evidence.values())
        if total_evidence == 0:
            result = (ReasoningType.ANALYTICAL, 0.5)
            self._reasoning_type_cache[question_hash] = result
            return result

        posteriors = {
            rtype: (evidence[rtype] / total_evidence) * priors[rtype]
            for rtype in ReasoningType
        }
        best_type = max(posteriors.items(), key=lambda x: x[1])
        result = (best_type[0], best_type[1])
        self._reasoning_type_cache[question_hash] = result
        return result

    async def compute_reasoning_score_async(
        self, question: str, context: str, reasoning_type: ReasoningType
    ) -> float:
        """Compute reasoning score during search phase asynchronously

        Parameters
        ----------
        question (str): Input question
        context (str): Context
        reasoning_type : ReasoningType
            Reasoning type.

        Returns
        -------
        float
            Reasoning score.
        """
        context_hash = hash(context)
        combined_hash = hash(question + " " + context)
        if context_hash not in self._pattern_cache:
            self._pattern_cache[context_hash] = context

        entropy_score = self.compute_pattern_entropy(
            context_hash, reasoning_type
        )
        combined_text = question + " " + context
        if combined_hash not in self._embedding_cache:
            await self.get_text_embedding_async(combined_text)

        semantic_score = await self.compute_semantic_coherence_async(
            combined_text, reasoning_type
        )
        patterns = self.reasoning_patterns[reasoning_type]
        coverage = sum(1 for p in patterns if p in context.lower()) / len(
            patterns
        )

        # Type-specific weights
        weights = {
            ReasoningType.FACTUAL: [0.4, 0.4, 0.2],
            ReasoningType.ANALYTICAL: [0.3, 0.4, 0.3],
            ReasoningType.COMPARATIVE: [0.2, 0.4, 0.4],
            ReasoningType.CAUSAL: [0.3, 0.3, 0.4],
            ReasoningType.HYPOTHETICAL: [0.2, 0.5, 0.3],
        }
        w = weights[reasoning_type]
        score = w[0] * entropy_score + w[1] * semantic_score + w[2] * coverage

        return score
