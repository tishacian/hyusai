"""The assistant is a workspace configuration, not a hardcoded tenant."""
from __future__ import annotations

from app.core.config import settings
from app.models.workspace import Workspace
from app.services.assistant.config import (
    DEFAULT_ALLOWED_TOOLS,
    DEFAULT_PERSONA,
    MAX_TOOL_TURNS_CEILING,
    resolve_assistant_config,
)
from app.services.assistant.tools import KNOWN_TOOLS, TOOLS


def _workspace(settings_blob: dict | None = None) -> Workspace:
    return Workspace(
        id="ws-assistant",
        name="Assistant",
        slug="assistant",
        settings=settings_blob if settings_blob is not None else {},
    )


def test_unconfigured_workspace_gets_a_read_only_assistant() -> None:
    config = resolve_assistant_config(_workspace(), known_tools=KNOWN_TOOLS)

    assert config.configured is False
    assert config.persona == DEFAULT_PERSONA
    assert config.model == settings.default_model
    assert config.allowed_tools == frozenset(DEFAULT_ALLOWED_TOOLS)
    mutating = {name for name, tool in TOOLS.items() if tool.mutating}
    assert config.allowed_tools & mutating == frozenset()


def test_workspace_settings_drive_persona_scope_model_and_tools() -> None:
    workspace = _workspace(
        {
            "knowledge_scopes": [
                {
                    "key": "itsd",
                    "label": "ITSD",
                    "collection_slugs": ["itsd-knowledge"],
                    "is_default": True,
                }
            ],
            "assistant": {
                "persona": "Tu es l'assistant ITSD.",
                "knowledge_scope": "itsd",
                "allowed_tools": ["search_knowledge", "list_systems", "start_system_run"],
                "model": "gpt-4o-mini",
                "max_tool_turns": 3,
                "locale": "fr",
                "top_k": 5,
                "latency_profile": "fast",
            },
        }
    )

    config = resolve_assistant_config(workspace, known_tools=KNOWN_TOOLS)

    assert config.configured is True
    assert config.persona == "Tu es l'assistant ITSD."
    assert config.knowledge_scope == "itsd"
    assert config.collection_slugs == ("itsd-knowledge",)
    assert config.model == "gpt-4o-mini"
    assert config.locale == "fr"
    assert config.top_k == 5
    assert config.latency_profile == "fast"
    assert config.max_tool_turns == 3
    assert config.allows("start_system_run") is True
    assert config.allows("answer_hitl_gate") is False


def test_unknown_tool_names_are_dropped_instead_of_breaking_the_turn() -> None:
    config = resolve_assistant_config(
        _workspace({"assistant": {"allowed_tools": ["search_knowledge", "rm_rf_slash"]}}),
        known_tools=KNOWN_TOOLS,
    )

    assert config.allowed_tools == frozenset({"search_knowledge"})


def test_an_explicitly_empty_allowlist_disables_every_tool() -> None:
    config = resolve_assistant_config(
        _workspace({"assistant": {"allowed_tools": []}}),
        known_tools=KNOWN_TOOLS,
    )

    assert config.allowed_tools == frozenset()


def test_out_of_range_and_invalid_values_fall_back_to_safe_bounds() -> None:
    config = resolve_assistant_config(
        _workspace(
            {
                "assistant": {
                    "max_tool_turns": 999,
                    "top_k": -4,
                    "latency_profile": "hyperspeed",
                    "allowed_tools": "search_knowledge",
                }
            }
        ),
        known_tools=KNOWN_TOOLS,
    )

    assert config.max_tool_turns == MAX_TOOL_TURNS_CEILING
    assert config.top_k > 0
    assert config.latency_profile == "balanced"
    # A malformed allowlist is "not configured", so the read-only default applies.
    assert config.allowed_tools == frozenset(DEFAULT_ALLOWED_TOOLS)


def test_scope_falls_back_to_the_workspace_default_scope() -> None:
    workspace = _workspace(
        {
            "knowledge_scopes": [
                {"key": "primary", "collection_slugs": ["docs"], "is_default": True},
                {"key": "secondary", "collection_slugs": ["other"]},
            ],
            "assistant": {},
        }
    )

    config = resolve_assistant_config(workspace, known_tools=KNOWN_TOOLS)

    assert config.knowledge_scope == "primary"
    assert config.collection_slugs == ("docs",)
