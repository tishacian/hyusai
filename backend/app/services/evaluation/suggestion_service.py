"""Active eval suggestions — E1.5.5.

Suggestions are stored on ``Decision.rationale.active_suggestion``. They
are concrete operator actions, not prose-only tips: in the MVP the main
action is a replay with carefully chosen overrides.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.models.run import Run


logger = get_logger(__name__)


def _fallback_suggestion(
    *,
    question_type: str,
    failed_components: List[str],
    reasons: List[Dict[str, Any]],
) -> Dict[str, Any]:
    components = set(failed_components or [])
    overrides: Dict[str, Any] = {}
    if {"retriever", "knowledge_base"} & components:
        overrides.update({"rag_pipeline_mode": "hybrid", "top_k": 8})
    if "rewriter" in components:
        overrides["prompt_type"] = "analytical"
    if "generator" in components or not overrides:
        overrides["system_prompt"] = (
            "Answer strictly from the retrieved context. If the context is "
            "insufficient, say exactly what is missing instead of guessing."
        )
        overrides.setdefault("temperature", 0.1)

    reason_labels = ", ".join(str(r.get("metric", "?")) for r in (reasons or [])[:3])
    return {
        "version": 1,
        "source": "fallback",
        "action_type": "rerun_with_overrides",
        "title": "Re-run with stricter grounding",
        "rationale": (
            f"Question type {question_type or 'unknown'} breached {reason_labels or 'quality thresholds'}; "
            "retry with tighter grounding and retrieval settings."
        ),
        "overrides": overrides,
        "expected_effect": "Reduce hallucination risk and produce a comparable scored replay.",
        "confidence": 0.62,
    }


async def generate_active_suggestion(
    *,
    run: Run,
    query: str,
    response: str,
    scores: Dict[str, float],
    composite_score: float,
    hallucination_rate: float,
    question_type: str,
    failed_components: List[str],
    reasons: List[Dict[str, Any]],
) -> Dict[str, Any]:
    fallback = _fallback_suggestion(
        question_type=question_type,
        failed_components=failed_components,
        reasons=reasons,
    )
    prompt = f"""You are an AI quality engineer for a RAG agent.

Return one concrete remediation suggestion as JSON. The operator can apply it
from a review queue. Prefer action_type="rerun_with_overrides" unless a
canonical answer is obviously safe.

Allowed JSON shape:
{{
  "action_type": "rerun_with_overrides",
  "title": "short title",
  "rationale": "why this action helps",
  "overrides": {{
    "query": "optional rewritten query",
    "rag_pipeline_mode": "hybrid|chah|hah|naive|auto",
    "model": "optional model",
    "system_prompt": "optional stricter prompt",
    "temperature": 0.1,
    "top_k": 8,
    "prompt_type": "factual|analytical|comparative|causal|hypothetical|trivial|auto"
  }},
  "expected_effect": "one sentence",
  "confidence": 0.0
}}

Context:
- run_id: {run.id}
- question_type: {question_type}
- failed_components: {failed_components}
- composite_score: {composite_score}
- hallucination_rate: {hallucination_rate}
- scores: {scores}
- breach_reasons: {reasons}
- query: {query[:1200]}
- response: {response[:1600]}

Return ONLY valid JSON."""
    try:
        from app.llm.llm import LLM

        llm = LLM(provider=settings.default_provider, api_key=settings.openai_api_key)
        text = await llm.complete(
            prompt=prompt,
            model="gpt-4o-mini",
            temperature=0.2,
            max_tokens=700,
        )
        text = (text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(text)
        if not isinstance(data, dict):
            return fallback
        action_type = data.get("action_type")
        if action_type != "rerun_with_overrides":
            return fallback
        overrides = data.get("overrides") if isinstance(data.get("overrides"), dict) else {}
        suggestion = {
            **fallback,
            "source": "llm",
            "title": str(data.get("title") or fallback["title"])[:120],
            "rationale": str(data.get("rationale") or fallback["rationale"])[:1000],
            "overrides": {k: v for k, v in overrides.items() if v not in (None, "")},
            "expected_effect": str(data.get("expected_effect") or fallback["expected_effect"])[:500],
            "confidence": float(data.get("confidence") or fallback["confidence"]),
        }
        if not suggestion["overrides"]:
            suggestion["overrides"] = fallback["overrides"]
        return suggestion
    except Exception as exc:  # noqa: BLE001
        logger.warning("active_suggestion: LLM generation failed, using fallback", error=str(exc))
        return fallback
