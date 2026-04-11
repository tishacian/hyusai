"""Semantic analyzer — relevance filtering, LLM analysis, safety checks"""
import json
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

ANALYSIS_PROMPT = """Analyze this news article for intelligence purposes.

## Article
Title: {title}
Content (truncated): {content}

## Semantic Target
{target_description}

## Instructions
Extract:
1. Key entities (people, organizations, locations, events)
2. Sentiment (positive / negative / neutral / mixed)
3. Risk level (low / medium / high / critical)
4. Key findings (2-3 bullet points)
5. Geopolitical relevance (if applicable)

Return ONLY valid JSON:
{{
  "entities": ["entity1", "entity2"],
  "sentiment": "neutral",
  "risk_level": "low",
  "key_findings": ["finding1", "finding2"],
  "geopolitical_relevance": "brief note or null"
}}"""

SAFETY_CHECK_PROMPT = """You are a content safety filter for a geopolitical intelligence platform.

## Content to check
{content_summary}

## Safety filter rules
{filter_rules}

## Instructions
Evaluate if this content is safe to include in the intelligence dashboard.
Consider the configured geopolitical alignment and sensitivity rules.

Return ONLY valid JSON:
{{
  "safe": true/false,
  "flag": "clear|flagged|blocked",
  "reason": "brief explanation"
}}"""


class SemanticAnalyzer:
    def __init__(self):
        self._llm = None
        self._embedder = None

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
            emb_target = await embedder.embed(target_description)
            dot = sum(a * b for a, b in zip(emb_article, emb_target))
            norm_a = sum(a ** 2 for a in emb_article) ** 0.5
            norm_b = sum(b ** 2 for b in emb_target) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)
        except Exception as e:
            logger.error(f"Relevance computation failed: {e}")
            return 0.0

    async def analyze_article(self, title: str, content: str, target_description: str) -> dict:
        llm = self._get_llm()
        prompt = ANALYSIS_PROMPT.format(
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

    async def check_safety(self, content_summary: str, filter_rules: str) -> dict:
        llm = self._get_llm()
        prompt = SAFETY_CHECK_PROMPT.format(
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
