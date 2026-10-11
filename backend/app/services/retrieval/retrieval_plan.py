"""Query analysis and retrieval planning"""
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Optional
from enum import Enum

from app.services.retrieval.fusion_method import FusionMethod


class ReasoningType(Enum):
    """Types of reasoning"""
    FACTUAL = "factual"
    ANALYTICAL = "analytical"
    COMPARATIVE = "comparative"
    CAUSAL = "causal"
    HYPOTHETICAL = "hypothetical"


@dataclass
class RetrievalContext:
    """Context retrieved from documents"""
    text: str
    score: float = 0.0
    relevance_score: float = 0.0
    diversity_score: float = 0.0
    reasoning_score: float = 0.0
    embedding: Optional[np.ndarray] = None
    metadata: Dict = field(default_factory=dict)
    token_count: int = 0
    
    def __lt__(self, other):
        """For priority queue operations"""
        return self.score > other.score


@dataclass
class QueryAnalysis:
    """Analysis of a query"""
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
    """Plan for retrieval based on query analysis"""
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
    ) -> "RetrievalPlan":
        """Create retrieval plan from query analysis"""
        plan = cls()
        plan.primary_k = (
            query_analysis.k_value * 13
            if is_large_model
            else query_analysis.k_value
        )
        plan.secondary_k = 5 if is_large_model else 12
        
        # Set weights based on reasoning type
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
        
        # Set fusion method based on query characteristics
        if query_analysis.query_characteristics.get("proper_noun_ratio", 0) > 0.5:
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

