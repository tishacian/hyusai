"""Configuration for ensemble retrieval"""
from dataclasses import dataclass
from app.services.retrieval.fusion_method import FusionMethod


@dataclass
class EnsembleConfig:
    """Configuration for ensemble retriever"""
    k: int = 20  # Number of candidates to retrieve
    bm25_weight: float = 0.4  # Weight for BM25 scores
    dense_weight: float = 0.6  # Weight for dense scores
    rrf_k: int = 60  # RRF constant
    batch_size: int = 64  # Batch size for processing
    use_gpu: bool = True  # Use GPU if available
    normalize_scores: bool = True  # Normalize scores before fusion
    fusion_method: FusionMethod = FusionMethod.SCORE_ADAPTIVE  # Default fusion method
    adaptive_alpha: float = 0.1  # Alpha for adaptive methods

