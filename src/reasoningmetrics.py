#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 14 16:58:25 2025

@author: kennethezukwoke
"""
import re
import sys
import logging
import warnings
import numpy as np
from enum import Enum
from typing import List, Tuple

warnings.simplefilter(action="ignore", category=FutureWarning)
# --
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class ReasoningType(Enum):
    """Defines different types of reasoning for the LLM"""

    FACTUAL = "factual"
    ANALYTICAL = "analytical"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    HYPOTHETICAL = "hypothetical"


class ReasoningMetrics:
    """Enhanced reasoning detection and scoring during search"""

    def __init__(self, embedding_model):
        self.embedding_model = embedding_model

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

        # Store reasoning patterns from parent class
        self.reasoning_patterns = {
            ReasoningType.FACTUAL: [
                "what",
                "who",
                "where",
                "when",
                "which",
                "list",
                "describe",
                "define",
            ],
            ReasoningType.ANALYTICAL: [
                "how",
                "analyze",
                "examine",
                "explain",
                "evaluate",
                "assess",
            ],
            ReasoningType.COMPARATIVE: [
                "compare",
                "contrast",
                "differ",
                "similar",
                "better",
                "worse",
                "versus",
                "vs",
            ],
            ReasoningType.CAUSAL: [
                "why",
                "because",
                "cause",
                "effect",
                "lead to",
                "result",
                "impact",
            ],
            ReasoningType.HYPOTHETICAL: [
                "if",
                "would",
                "could",
                "might",
                "assume",
                "suppose",
                "predict",
            ],
        }

    def compute_cosine_similarity(
        self, vec1: np.ndarray, vec2: np.ndarray
    ) -> float:
        """Compute cosine similarity"""
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        return dot_product / (norm1 * norm2) if norm1 * norm2 != 0 else 0.0

    def compute_pattern_entropy(self, text: str, patterns: List[str]) -> float:
        """Compute entropy of reasoning patterns in text using Shannon entropy"""
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

    def compute_semantic_coherence(
        self, text: str, reasoning_type: ReasoningType
    ) -> float:
        """Compute semantic coherence score using embedding similarity"""
        text_embedding = self.embedding_model.encode([text])[0]
        type_embedding = self.embedding_model.encode(
            [str(reasoning_type.value)]
        )[0]

        return self.compute_cosine_similarity(text_embedding, type_embedding)

    def bayesian_reasoning_detection(
        self, question: str
    ) -> Tuple[ReasoningType, float]:
        """Reasoning type detection using Bayesian inference"""
        # Prior probabilities
        priors = {rtype: 1 / len(ReasoningType) for rtype in ReasoningType}

        # Evidence scores
        evidence = {}
        for rtype in ReasoningType:
            # Pattern entropy score
            entropy = self.compute_pattern_entropy(
                question, self.reasoning_patterns[rtype]
            )
            entropy_score = (
                1.0 if entropy >= self.entropy_thresholds[rtype] else 0.5
            )
            coherence_score = self.compute_semantic_coherence(question, rtype)
            pattern_score = sum(
                1
                for pattern in self.reasoning_patterns[rtype]
                if pattern in question.lower()
            ) / len(self.reasoning_patterns[rtype])

            # Combine evidence using weighted geometric mean
            evidence[rtype] = (
                entropy_score * 0.7
                + coherence_score * 0.2
                + pattern_score * 0.1
            ) * self.reasoning_weights[rtype]

        # Compute posterior probabilities
        total_evidence = sum(evidence.values())
        if total_evidence == 0:
            return ReasoningType.ANALYTICAL, 0.5

        posteriors = {
            rtype: (evidence[rtype] / total_evidence) * priors[rtype]
            for rtype in ReasoningType
        }

        # Select type with highest posterior probability
        best_type = max(posteriors.items(), key=lambda x: x[1])
        return best_type[0], best_type[1]

    def compute_reasoning_score(
        self, question: str, context: str, reasoning_type: ReasoningType
    ) -> float:
        """Compute reasoning score during search phase"""
        # Entropy-based coherence
        entropy_score = self.compute_pattern_entropy(
            context, self.reasoning_patterns[reasoning_type]
        )

        # Semantic similarity
        semantic_score = self.compute_semantic_coherence(
            question + " " + context, reasoning_type
        )

        # Pattern coverage
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
