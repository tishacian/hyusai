"""Retrieval services"""
from app.services.retrieval.fusion_method import FusionMethod
from app.services.retrieval.ensemble_config import EnsembleConfig
from app.services.retrieval.ensemble_retriever import EnsembleRetriever
from app.services.retrieval.retrieval_plan import QueryAnalysis, RetrievalPlan, RetrievalContext, ReasoningType
from app.services.retrieval.bm25_retriever import BM25Retriever

try:
    from app.services.retrieval.flash_reranker import FlashReranker, RerankerConfig
except ImportError:
    FlashReranker = None  # type: ignore
    RerankerConfig = None  # type: ignore

try:
    from app.services.retrieval.contextual_compression import ContextualCompressionRetriever, ContextualConfig
except ImportError:
    ContextualCompressionRetriever = None  # type: ignore
    ContextualConfig = None  # type: ignore

__all__ = [
    "FusionMethod",
    "EnsembleConfig",
    "EnsembleRetriever",
    "FlashReranker",
    "RerankerConfig",
    "ContextualCompressionRetriever",
    "ContextualConfig",
    "QueryAnalysis",
    "RetrievalPlan",
    "RetrievalContext",
    "ReasoningType",
    "BM25Retriever",
]
