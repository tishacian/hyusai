"""Cross-encoder reranking on ONNX Runtime, without torch or transformers.

The cross-encoders the RAG path uses publish an official ONNX export next to
their PyTorch weights (``onnx/model.onnx`` in the Hugging Face repository), so
the same network runs here on ``onnxruntime`` with the model's own
``tokenizer.json`` read by ``tokenizers``. That pair is a few tens of MB of
wheels against several hundred for torch, torchvision and transformers, and it
is what lets the API image stop carrying those.

The files are baked into the image at build time from a pinned manifest
(``backend/rag_models.lock.json``, fetched by ``scripts/fetch_rag_models.py``):
nothing is downloaded when a worker starts, and an air-gapped host runs the
same bytes the release qualified.

Scores match ``FlashReranker``: the sigmoid of the single logit, in input
order for ``score``, sorted and thresholded for ``rerank``.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np

from app.core.logging import get_logger
from app.services.retrieval.reranker_config import RerankerConfig

logger = get_logger(__name__)

MODEL_FILE = Path("onnx") / "model.onnx"
TOKENIZER_FILE = "tokenizer.json"


def model_directory(models_dir: str | Path, model_name: str) -> Path:
    """Where a model's files live: ``<models_dir>/<org>/<name>``."""
    return Path(models_dir) / model_name


def has_model_files(models_dir: str | Path, model_name: str) -> bool:
    directory = model_directory(models_dir, model_name)
    return (directory / MODEL_FILE).is_file() and (directory / TOKENIZER_FILE).is_file()


class OnnxReranker:
    """Drop-in for ``FlashReranker`` on ONNX Runtime (CPU)."""

    _sessions: dict[tuple[str, int, bool], tuple[Any, Any]] = {}
    _lock = threading.Lock()

    def __init__(
        self,
        config: RerankerConfig | None = None,
        *,
        models_dir: str | Path,
        model_bytes: bytes | None = None,
    ):
        self.config = config or RerankerConfig()
        self.device = "cpu"
        self.models_dir = Path(models_dir)
        self.directory = model_directory(self.models_dir, self.config.model_name)
        self.model_bytes = model_bytes
        self.session, self.tokenizer = self._load()

    def _load(self) -> tuple[Any, Any]:
        key = (str(self.directory), int(self.config.max_length), self.model_bytes is not None)
        with OnnxReranker._lock:
            cached = OnnxReranker._sessions.get(key)
            if cached is not None:
                return cached
            import onnxruntime
            from tokenizers import Tokenizer

            if not has_model_files(self.models_dir, self.config.model_name):
                raise FileNotFoundError(f"ONNX reranker files missing under {self.directory}")
            options = onnxruntime.SessionOptions()
            options.intra_op_num_threads = max(1, int(self.config.num_threads))
            session = onnxruntime.InferenceSession(
                self.model_bytes
                if self.model_bytes is not None
                else str(self.directory / MODEL_FILE),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            tokenizer = Tokenizer.from_file(str(self.directory / TOKENIZER_FILE))
            # Keep the repository's own truncation strategy and padding token,
            # but the reranker's max_length is the one that counts — the same
            # bound transformers applies with truncation=True.
            truncation = tokenizer.truncation or {}
            tokenizer.enable_truncation(
                max_length=int(self.config.max_length),
                stride=int(truncation.get("stride", 0)),
                strategy=truncation.get("strategy", "longest_first"),
            )
            if tokenizer.padding is None:
                tokenizer.enable_padding()
            OnnxReranker._sessions[key] = (session, tokenizer)
            logger.info("Loaded ONNX reranker", model=self.config.model_name)
            return session, tokenizer

    def _feeds(self, query: str, passages: list[str]) -> dict[str, np.ndarray]:
        encodings = self.tokenizer.encode_batch([(query, passage) for passage in passages])
        names = {inp.name for inp in self.session.get_inputs()}
        feeds = {
            "input_ids": np.asarray([e.ids for e in encodings], dtype=np.int64),
            "attention_mask": np.asarray([e.attention_mask for e in encodings], dtype=np.int64),
            "token_type_ids": np.asarray([e.type_ids for e in encodings], dtype=np.int64),
        }
        return {name: value for name, value in feeds.items() if name in names}

    def _batch_scores(self, query: str, passages: list[str]) -> list[float]:
        (logits,) = self.session.run(["logits"], self._feeds(query, passages))
        logits = np.asarray(logits, dtype=np.float64).reshape(len(passages), -1)[:, 0]
        return (1.0 / (1.0 + np.exp(-logits))).tolist()

    def _batch_size(self) -> int:
        # FlashReranker's CPU batch: a quarter of the configured size.
        return max(1, int(self.config.batch_size) // 4)

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Relevance scores aligned to the input passage order (no sorting)."""
        if not passages:
            return []
        size = self._batch_size()
        scores: list[float] = []
        for start in range(0, len(passages), size):
            batch = passages[start : start + size]
            try:
                scores.extend(self._batch_scores(query, batch))
            except Exception as exc:  # noqa: BLE001 - same degraded answer as FlashReranker
                logger.error("ONNX reranker batch failed", error=str(exc))
                scores.extend([0.0] * len(batch))
        return scores

    def rerank(
        self, query: str, passages: list[str], return_scores: bool = False
    ) -> list[str] | tuple[list[str], list[float]]:
        scored = sorted(
            zip(passages, self.score(query, passages)), key=lambda pair: pair[1], reverse=True
        )
        kept = [pair for pair in scored if pair[1] >= self.config.threshold] or scored
        ranked = [passage for passage, _ in kept]
        if return_scores:
            return ranked, [value for _, value in kept]
        return ranked

    def __call__(
        self, query: str, passages: list[str], return_scores: bool = False
    ) -> list[str] | tuple[list[str], list[float]]:
        return self.rerank(query, passages, return_scores)
