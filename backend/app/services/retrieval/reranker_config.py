"""Cross-encoder reranker configuration, importable without torch.

Kept apart from ``flash_reranker`` so that naming a reranker's settings does not
load torch and transformers: the API process picks its engine at run time
(``rerankers.make_reranker``) and only the torch engine needs them.
"""
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RerankerMode(Enum):
    """Reranking modes"""
    PAIRWISE = "pairwise"
    POINTWISE = "pointwise"
    LISTWISE = "listwise"


@dataclass
class RerankerConfig:
    """Configuration for flash reranker"""
    batch_size: int = min(64, (os.cpu_count() or 4) * 4)
    max_length: int = 512
    mode: RerankerMode = RerankerMode.POINTWISE
    num_threads: int = 8
    threshold: float = 0.5
    device: Optional[str] = None
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"
