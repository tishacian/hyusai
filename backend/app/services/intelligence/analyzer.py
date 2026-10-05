"""Semantic analyzer — relevance filtering, LLM analysis, safety checks"""
import json
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger

# The neutral prompts. A family adapter may word its own
# (``profile.analysis_prompt`` / ``profile.safety_prompt``), passed per call.
from app.services.intelligence.profile import ANALYSIS_PROMPT, SAFETY_CHECK_PROMPT

logger = get_logger(__name__)


class SemanticAnalyzer:
    def __init__(self):
        self._llm = None
        self._embedder = None
        self._target_embedding_cache: dict[str, list[float]] = {}

    def _get_llm(self):
        if self._llm is None:
            from app.llm.llm import LLM
            self._llm = LLM(provider=settings.default_provider, api_key=settings.openai_api_key)
        return self._llm

    def _get_embedder(self):
        if self._embedder is None:
            from app.services.embedding.embedder import Embedder
            self._embedder = Embedder()
        return self._embedder

    async def compute_relevance(self, article_text: str, target_description: str) -> float:
        """Cosine similarity between article and semantic target."""
        try:
            embedder = self._get_embedder()
            emb_article = await embedder.embed(article_text[:1000])
            emb_target = self._target_embedding_cache.get(target_description)
            if emb_target is None:
                emb_target = await embedder.embed(target_description)
                self._target_embedding_cache[target_description] = emb_target
            dot = sum(a * b for a, b in zip(emb_article, emb_target))
            norm_a = sum(a ** 2 for a in emb_article) ** 0.5
            norm_b = sum(b ** 2 for b in emb_target) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)
        except Exception as e:
            logger.error(f"Relevance computation failed: {e}")
            return 0.0

    async def analyze_article(
        self,
        title: str,
        content: str,
        target_description: str,
        prompt_template: Optional[str] = None,
    ) -> dict:
        llm = self._get_llm()
        prompt = (prompt_template or ANALYSIS_PROMPT).format(
            title=title,
            content=content[:2000],
            target_description=target_description,
        )
        try:
            result = await llm.complete(prompt=prompt, model="gpt-4o-mini", temperature=0.3, max_tokens=800)
            text = result.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except Exception as e:
            logger.error(f"Article analysis failed: {e}")
            return {"entities": [], "sentiment": "unknown", "risk_level": "unknown", "key_findings": []}

    async def check_safety(
        self,
        content_summary: str,
        filter_rules: str,
        prompt_template: Optional[str] = None,
    ) -> dict:
        llm = self._get_llm()
        prompt = (prompt_template or SAFETY_CHECK_PROMPT).format(
            content_summary=content_summary[:1000],
            filter_rules=filter_rules,
        )
        try:
            result = await llm.complete(prompt=prompt, model="gpt-4o-mini", temperature=0.1, max_tokens=300)
            text = result.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(text)
        except Exception as e:
            logger.error(f"Safety check failed: {e}")
            return {"safe": True, "flag": "clear", "reason": "check failed — defaulting to safe"}


_analyzer = None

def get_analyzer() -> SemanticAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SemanticAnalyzer()
    return _analyzer
