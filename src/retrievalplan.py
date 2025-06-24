# -*- coding: utf-8 -*-
"""
Created on Sun May 25 19:12:35 2025

@author: kennethezukwoke
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np

from src.ensembleretriever import FusionMethod
from src.globalvariables import ReasoningType


@dataclass
class RetrievalContext:
    text: str
    score: float = 0.0
    relevance_score: float = 0.0
    diversity_score: float = 0.0
    reasoning_score: float = 0.0
    embedding: Optional[np.ndarray] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    token_count: int = 0

    def __lt__(self, other):
        """For priority queue operations

        Parameters
        ----------
        other : RetrievalContext
            Other context to compare

        Returns
        -------
        bool
            True if this context has higher score
        """
        return self.score > other.score


@dataclass
class QueryAnalysis:
    complexity: float = 0.0
    k_value: int = 5
    lambda_param: float = 0.5
    has_multiple_questions: bool = False
    word_count: int = 0
    query_characteristics: Dict[str, float] = field(default_factory=dict)
    reasoning_type: Optional[ReasoningType] = None
    reasoning_confidence: float = 0.0
    embedding: Optional[np.ndarray] = None


@dataclass
class RetrievalPlan:
    primary_k: int = 5
    secondary_k: int = 12
    reranking_threshold: float = 0.6
    fusion_method: FusionMethod = FusionMethod.SCORE_ADAPTIVE
    use_semantic_chunking: bool = False
    use_query_expansion: bool = False
    relevance_weight: float = 0.7
    diversity_weight: float = 0.3
    reasoning_weight: float = 0.0
    conversation_weight: float = 0.0

    @classmethod
    def from_query_analysis(
        cls, query_analysis: QueryAnalysis, is_large_model: bool = True
    ):
        """Retrieval plan based on query analysis

        Parameters
        ----------
        query_analysis : QueryAnalysis
            Analysis of the query
        is_large_model : bool, optional
            Whether using a large model, by default True

        Returns
        -------
        RetrievalPlan
            Configured retrieval plan
        """
        plan = cls()
        plan.primary_k = (
            query_analysis.k_value * 13 if is_large_model else query_analysis.k_value
        )
        plan.secondary_k = 5 if is_large_model else 12

        if query_analysis.reasoning_type == ReasoningType.ANALYTICAL:
            plan.relevance_weight = 0.8
            plan.diversity_weight = 0.2
            plan.reasoning_weight = 0.6
        elif query_analysis.reasoning_type == ReasoningType.FACTUAL:
            plan.relevance_weight = 0.9
            plan.diversity_weight = 0.1
            plan.reasoning_weight = 0.3
        elif query_analysis.reasoning_type == ReasoningType.COMPARATIVE:
            plan.relevance_weight = 0.7
            plan.diversity_weight = 0.3
            plan.reasoning_weight = 0.5
        elif query_analysis.reasoning_type == ReasoningType.CAUSAL:
            plan.relevance_weight = 0.7
            plan.diversity_weight = 0.3
            plan.reasoning_weight = 0.6
        elif query_analysis.reasoning_type == ReasoningType.HYPOTHETICAL:
            plan.relevance_weight = 0.6
            plan.diversity_weight = 0.4
            plan.reasoning_weight = 0.4
        else:
            plan.relevance_weight = 0.7
            plan.diversity_weight = 0.3
            plan.reasoning_weight = 0.4

        if query_analysis.query_characteristics.get("has_proper_nouns", 0) > 0.5:
            plan.fusion_method = FusionMethod.QUERY_ADAPTIVE
        elif query_analysis.query_characteristics.get("technical_ratio", 0) > 0.3:
            plan.fusion_method = FusionMethod.QUERY_ADAPTIVE
        elif (
            query_analysis.word_count > 15
            and query_analysis.query_characteristics.get("has_wh_words", 0) > 0
        ):
            plan.fusion_method = FusionMethod.HARMONIC_MEAN
        elif query_analysis.query_characteristics.get("has_boolean", 0) > 0:
            plan.fusion_method = FusionMethod.COMBMNZ
        else:
            plan.fusion_method = FusionMethod.SCORE_ADAPTIVE

        if query_analysis.complexity > 0.7:
            plan.use_semantic_chunking = True

        if query_analysis.query_characteristics.get("technical_ratio", 0) > 0.2:
            plan.use_query_expansion = True

        return plan
