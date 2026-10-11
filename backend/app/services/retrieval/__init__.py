"""Retrieval services"""
from app.services.retrieval.fusion_method import FusionMethod
from app.services.retrieval.ensemble_config import EnsembleConfig
from app.services.retrieval.ensemble_retriever import EnsembleRetriever
from app.services.retrieval.retrieval_plan import QueryAnalysis, RetrievalPlan, RetrievalContext, ReasoningType
from app.services.retrieval.bm25_retriever import BM25Retriever
from app.services.retrieval.reranker_config import RerankerConfig

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


def __getattr__(name: str):
    # FlashReranker imports torch and transformers at module scope. Resolving it
    # only when asked keeps every importer of this package — the API process
    # among them — free of torch unless the torch engine is actually used.
    if name == "FlashReranker":
        try:
            from app.services.retrieval.flash_reranker import FlashReranker
        except ImportError:
            return None
        return FlashReranker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
