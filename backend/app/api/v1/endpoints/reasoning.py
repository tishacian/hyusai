"""Reasoning templates endpoint.

Exposes the catalogue of reasoning templates declared in
``app.services.system_prompts`` so the cockpit can render a template
selector in the chat composer + Builder step Policy, and display a
badge in the reasoning trail.

Kept behind its own router to avoid polluting ``/chat`` with
introspection concerns.
"""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.services.system_prompts import SYSTEM_PROMPT_TEMPLATES, SystemPromptType

router = APIRouter(dependencies=[Depends(get_current_user)])


_DESCRIPTIONS: Dict[str, str] = {
    "factual":      "Direct factual answer grounded in the retrieved context.",
    "analytical":   "Multi-step analysis: goals, constraints, synthesis, conclusions.",
    "comparative":  "Weighs similarities and differences, returns a balanced verdict.",
    "causal":       "Maps cause-effect chains and their implications.",
    "hypothetical": "Explores scenarios from given conditions and their outcomes.",
    "trivial":      "Conversational small-talk / greetings / thanks — no retrieval.",
}


def _templates() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key in SYSTEM_PROMPT_TEMPLATES:
        slug = key.value if isinstance(key, SystemPromptType) else str(key)
        out.append(
            {
                "slug": slug,
                "label": slug.replace("_", " ").title(),
                "description": _DESCRIPTIONS.get(slug, ""),
            }
        )
    return out


@router.get("/templates")
async def list_reasoning_templates() -> Dict[str, Any]:
    """Return every registered reasoning template."""
    return {"templates": _templates()}
