"""Per-workspace configuration of the conversational assistant engine.

The engine holds no tenant knowledge. Everything that makes an assistant
specific to a workspace — its persona, the knowledge it may read, the tools it
may call, the model it runs on — is resolved here from
``Workspace.settings["assistant"]``.

Absence of that block is a valid configuration: the engine then runs with a
neutral persona, the workspace default Knowledge Scope and a **read-only** tool
allowlist. Every tool that mutates state (starting a Run, answering a HITL gate)
requires an explicit opt-in, so a workspace nobody configured can never be
driven into an execution by a model.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.services.rag.knowledge_scopes import normalize_knowledge_scopes, select_scope

SETTINGS_KEY = "assistant"

DEFAULT_PERSONA = (
    "You are the workspace assistant. Answer from the workspace knowledge and the "
    "tools you are given. Never invent a fact, a document, a service or an "
    "identifier: call a tool instead. When a tool returns nothing usable, say so "
    "plainly and ask for the missing detail."
)

# Tools a workspace gets without configuring anything. Read-only by construction.
DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    "search_knowledge",
    "list_systems",
    "get_run_status",
    "list_services",
    "preview_service",
    "inspect_system",
    "compare_runs",
    "read_operational_metrics",
    "read_automation_proof",
)

DEFAULT_MAX_TOOL_TURNS = 4
MAX_TOOL_TURNS_CEILING = 8
DEFAULT_HISTORY_TURNS = 12
DEFAULT_TOP_K = 8
DEFAULT_LATENCY_PROFILE = "balanced"
_LATENCY_PROFILES = frozenset({"fast", "balanced", "deep"})


@dataclass(frozen=True)
class AssistantConfig:
    """Resolved, sanitized assistant configuration for one workspace."""

    workspace_id: str
    workspace_slug: str
    persona: str
    provider: str
    model: str
    knowledge_scope: str | None
    collection_slugs: tuple[str, ...]
    allowed_tools: frozenset[str]
    max_tool_turns: int
    history_turns: int
    top_k: int
    latency_profile: str
    locale: str | None
    configured: bool
    extra: Mapping[str, Any] = field(default_factory=dict)

    def allows(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _clean_text(value: Any, *, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _clean_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _clean_tool_names(value: Any, *, known_tools: frozenset[str]) -> frozenset[str] | None:
    """Return the requested allowlist restricted to tools the engine knows.

    ``None`` means "not configured" so the caller can apply the read-only
    default. An explicitly empty list is honoured as "no tools at all".
    """
    if not isinstance(value, list | tuple):
        return None
    names = {str(item or "").strip() for item in value}
    return frozenset(name for name in names if name in known_tools)


def resolve_assistant_config(
    workspace: Any,
    *,
    known_tools: frozenset[str],
    fallback_collection: str = "documents",
) -> AssistantConfig:
    """Build the effective assistant configuration for ``workspace``.

    ``known_tools`` is injected by the tool registry so an unknown tool name in
    the workspace settings is dropped instead of failing the turn, and so this
    module never imports the registry (which imports authorization, which
    imports the ORM).
    """
    workspace_settings = _as_mapping(getattr(workspace, "settings", None))
    raw = _as_mapping(workspace_settings.get(SETTINGS_KEY))

    scopes = normalize_knowledge_scopes(workspace_settings.get("knowledge_scopes"))
    requested_scope_key = _clean_text(raw.get("knowledge_scope"), limit=120) or None
    scope = select_scope(scopes, requested_scope_key, fallback_collection)
    collection_slugs = tuple(scope.get("collection_slugs") or ())
    scope_key = scope.get("key") if requested_scope_key or scopes else None

    configured_tools = _clean_tool_names(raw.get("allowed_tools"), known_tools=known_tools)

    return AssistantConfig(
        workspace_id=str(getattr(workspace, "id", "") or ""),
        workspace_slug=str(getattr(workspace, "slug", "") or ""),
        persona=_clean_text(raw.get("persona"), limit=8000) or DEFAULT_PERSONA,
        provider=_clean_text(raw.get("provider"), limit=40) or settings.default_provider,
        model=_clean_text(raw.get("model"), limit=120) or settings.default_model,
        knowledge_scope=scope_key,
        collection_slugs=collection_slugs,
        allowed_tools=(
            configured_tools
            if configured_tools is not None
            else frozenset(name for name in DEFAULT_ALLOWED_TOOLS if name in known_tools)
        ),
        max_tool_turns=_clean_int(
            raw.get("max_tool_turns"),
            default=DEFAULT_MAX_TOOL_TURNS,
            minimum=1,
            maximum=MAX_TOOL_TURNS_CEILING,
        ),
        history_turns=_clean_int(
            raw.get("history_turns"),
            default=DEFAULT_HISTORY_TURNS,
            minimum=0,
            maximum=50,
        ),
        top_k=_clean_int(raw.get("top_k"), default=DEFAULT_TOP_K, minimum=1, maximum=25),
        latency_profile=(
            _clean_text(raw.get("latency_profile"), limit=20)
            if _clean_text(raw.get("latency_profile"), limit=20) in _LATENCY_PROFILES
            else DEFAULT_LATENCY_PROFILE
        ),
        locale=_clean_text(raw.get("locale"), limit=12) or None,
        configured=bool(raw),
        extra=raw,
    )
