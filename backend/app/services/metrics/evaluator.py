"""Response quality metrics — adapted from src/metrics.py (Evaluatrix).

Uses the existing OpenAI embedder so no extra model is loaded.
All scores are cosine-similarity based and computed per-query.
"""
import asyncio
import numpy as np
from typing import Dict, List
from app.core.logging import get_logger

logger = get_logger(__name__)


def _cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a).flatten(), np.asarray(b).flatten()
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


class ResponseEvaluator:
    """Lightweight RAG quality evaluator reusing the platform embedder."""

    def __init__(self):
        self._embedder = None

    def _get_embedder(self):
        if self._embedder is None:
            from app.services.embedding.embedder import Embedder
            self._embedder = Embedder()
        return self._embedder

    async def evaluate(
        self,
        query: str,
        response: str,
        source_chunks: List[str],
    ) -> Dict[str, float]:
        if not response.strip():
            return self._empty()

        try:
            embedder = self._get_embedder()

            texts = [query, response] + (source_chunks or [])
            embeddings = await embedder.embed_batch(texts)

            emb_array = np.array(embeddings)
            q_emb = emb_array[0]
            r_emb = emb_array[1]
            src_embs = emb_array[2:] if len(emb_array) > 2 else np.array([])

            relevance = _cos_sim(q_emb, r_emb)

            if len(src_embs) > 0:
                sims = [_cos_sim(r_emb, s) for s in src_embs]
                factuality = float(max(sims))
                mean_sim = float(np.mean(sims))
            else:
                factuality = 0.0
                mean_sim = 0.0

            sentences = [s.strip() for s in response.replace("\n", ". ").split(". ") if len(s.strip()) > 10]
            if len(sentences) >= 2:
                sent_array = np.array(await embedder.embed_batch(sentences[:10]))
                coh_scores = [_cos_sim(sent_array[i], sent_array[i + 1]) for i in range(len(sent_array) - 1)]
                coherence = float(np.mean(coh_scores))
            else:
                coherence = 1.0

            # HHEM: (mean_sim * factuality) / (1 + mean_sim * factuality + eps)
            mf = mean_sim * factuality
            hhem = mf / (1 + mf + 1e-8)

            # Advance_HHEM: (mean_sim * factuality * coherence * relevance) / (1 + mean_sim * factuality + eps)
            adv_hhem = (mf * coherence * relevance) / (1 + mf + 1e-8)

            return {
                "relevance": round(relevance, 4),
                "factuality": round(factuality, 4),
                "coherence": round(coherence, 4),
                "hhem": round(hhem, 4),
                "adv_hhem": round(adv_hhem, 4),
            }
        except Exception as e:
            logger.warning("Metrics evaluation failed", error=str(e))
            return self._empty()

    @staticmethod
    def _empty() -> Dict[str, float]:
        return {"relevance": 0.0, "factuality": 0.0, "coherence": 0.0, "hhem": 0.0, "adv_hhem": 0.0}
