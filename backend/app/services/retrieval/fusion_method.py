"""Fusion methods for combining multiple retrieval results"""
from enum import Enum


class FusionMethod(Enum):
    """Fusion methods for combining BM25 and dense retrieval results"""
    RRF = "rrf"  # Reciprocal Rank Fusion
    WEIGHTED_LINEAR = "weighted_linear"
    QUERY_ADAPTIVE = "query_adaptive"
    SCORE_ADAPTIVE = "score_adaptive"
    HARMONIC_MEAN = "harmonic_mean"
    GEOMETRIC_MEAN = "geometric_mean"
    MIN_MAX_FUSION = "min_max_fusion"
    RANK_FUSION = "rank_fusion"
    COMBSUM = "combsum"
    COMBMNZ = "combmnz"

