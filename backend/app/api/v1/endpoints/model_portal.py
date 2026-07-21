"""Models & Providers portal (workspace-gated beta, read-only).

Reports which LLM providers the platform can route to, based purely on
config/env presence — no network calls. Adapters live in two places:
``app.services.model_router`` (ollama/openai/anthropic runtime clients) and
``app.llm.providers`` (azure_openai, openrouter, gemini, ...).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user, get_current_workspace
from app.core.config import settings
from app.models.user import User
from app.models.workspace import Workspace
from app.services.workspace_features import feature_enabled

router = APIRouter()

FEATURE_FLAG = "model_portal_beta"


def _require_enabled(workspace: Workspace) -> None:
    if not feature_enabled(workspace, FEATURE_FLAG, csv_fallback="agentium-showcase"):
        raise HTTPException(
            status_code=403,
            detail="Model portal is not enabled for this workspace",
        )


def _env_set(*names: str) -> bool:
    return all(bool(os.getenv(name)) for name in names)


def _providers() -> List[Dict[str, Any]]:
    """Config-presence snapshot of every provider adapter the code supports."""
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    return [
        {
            "key": "ollama",
            "label": "Ollama",
            "kind": "local",
            "status": "configured" if settings.ollama_base_url else "available",
            "models": [settings.ollama_default_model],
            "notes": "Local / sovereign serving",
        },
        {
            "key": "openai",
            "label": "OpenAI",
            "kind": "cloud",
            "status": "configured" if _env_set("OPENAI_API_KEY") else "available",
            "models": ["gpt-5"],
            "notes": "OpenAI API (chat completions, streaming)",
        },
        {
            "key": "azure_openai",
            "label": "Azure OpenAI / AI Foundry",
            "kind": "cloud",
            "status": "configured"
            if _env_set("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT")
            else "available",
            "models": [azure_deployment] if azure_deployment else ["gpt-5 (deployment)"],
            "notes": "Azure-hosted OpenAI deployments, incl. AI Foundry endpoints",
        },
        {
            "key": "openrouter",
            "label": "OpenRouter",
            "kind": "cloud",
            "status": "configured" if _env_set("OPENROUTER_API_KEY") else "available",
            "models": [os.getenv("OPENROUTER_DEFAULT_MODEL", "z-ai/glm-4.5")],
            "notes": "Multi-provider gateway (Anthropic, Meta, Mistral, ...)",
        },
        {
            "key": "anthropic",
            "label": "Anthropic",
            "kind": "cloud",
            "status": "configured" if _env_set("ANTHROPIC_API_KEY") else "available",
            "models": ["claude-3-4-sonnet"],
            "notes": "Claude models via the Anthropic API",
        },
        {
            "key": "gemini",
            "label": "Google Gemini",
            "kind": "cloud",
            "status": "configured" if _env_set("GEMINI_API_KEY") else "available",
            "models": [os.getenv("GEMINI_DEFAULT_MODEL", "gemini-2.0-flash-exp")],
            "notes": "Gemini models via the Google AI API",
        },
    ]


@router.get("/providers")
async def list_model_providers(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
):
    _require_enabled(workspace)
    return {"providers": _providers()}
