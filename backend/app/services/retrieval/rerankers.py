"""Pick the cross-encoder engine: torch or ONNX Runtime, by setting and image.

Callers ask for a reranker by configuration and get an object with
``score``/``rerank``; which engine answers is a deployment fact, not theirs to
know. An ``ImportError`` means no engine can run here, which callers already
turn into an "unavailable" rerank stage.
"""
from __future__ import annotations

from importlib.util import find_spec
from typing import Any

from app.core.config import settings
from app.services.retrieval.reranker_config import RerankerConfig

BACKENDS = ("auto", "onnx", "torch")


def _onnx_runnable(model_name: str) -> bool:
    from app.services.retrieval.onnx_reranker import has_model_files

    return (
        find_spec("onnxruntime") is not None
        and find_spec("tokenizers") is not None
        and has_model_files(settings.rag_models_dir, model_name)
    )


def _torch_installed() -> bool:
    return find_spec("torch") is not None and find_spec("transformers") is not None


def reranker_backend(model_name: str) -> str:
    """The engine ``make_reranker`` would use for this model: onnx or torch.

    ``auto`` runs ONNX wherever its files and runtime are present — every image
    since they are baked in — and torch only where ONNX cannot run. ONNX was
    qualified against torch on the serving host's CPU
    (``scripts/bench_rerank_engines.py``: same order, scores within 6e-7), which
    is what let the API image stop installing torch. ``torch`` forces the
    fallback engine on an image that still has it (the worker).
    """
    requested = (settings.rag_reranker_backend or "auto").strip().lower()
    if requested not in BACKENDS:
        raise ValueError(f"rag_reranker_backend must be one of {BACKENDS}, got {requested!r}")
    if requested == "torch":
        return "torch"
    if _onnx_runnable(model_name):
        return "onnx"
    if requested == "auto" and _torch_installed():
        return "torch"
    onnx_missing = (
        f"ONNX needs onnxruntime, tokenizers and the model files under {settings.rag_models_dir}"
    )
    if requested == "onnx":
        raise ImportError(f"No cross-encoder engine for {model_name}: {onnx_missing}")
    raise ImportError(
        f"No cross-encoder engine for {model_name}: {onnx_missing}, and torch/transformers "
        "are not installed"
    )


def make_reranker(config: RerankerConfig | None = None) -> Any:
    config = config or RerankerConfig()
    if reranker_backend(config.model_name) == "onnx":
        from app.services.retrieval.onnx_reranker import OnnxReranker

        return OnnxReranker(config, models_dir=settings.rag_models_dir)
    # Raises ImportError where torch/transformers are not installed.
    from app.services.retrieval.flash_reranker import FlashReranker

    return FlashReranker(config)
