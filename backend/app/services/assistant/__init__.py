"""Workspace-configured conversational assistant engine.

Public surface, frozen as a contract for every calling surface:

* :func:`answer_assistant_turn` — the internal call contract (text + session and
  workspace context in, :class:`AssistantTurnResult` out). The LiveKit voice
  gateway calls this directly and never goes through HTTP.
* :class:`AssistantTurnResult` — the single response object; ``as_payload()``
  produces the JSON body served by ``POST /api/v1/assistant/turns`` and the
  payload of the ``assistant.answer`` voice event.
* the error classes, each carrying ``code`` and ``status_code`` so a surface can
  translate them without re-deriving a mapping.

See ``docs/ops/assistant-engine-contract.md``.
"""
from app.services.assistant.config import AssistantConfig, resolve_assistant_config
from app.services.assistant.engine import (
    MAX_SESSION_CONTEXT_CHARS,
    SURFACE_TEXT,
    SURFACE_VOICE,
    AssistantEngineError,
    AssistantInputInvalidError,
    AssistantModelFailedError,
    AssistantSessionNotFoundError,
    AssistantTurnResult,
    AssistantUnavailableError,
    ToolCallRecord,
    answer_assistant_turn,
    resolve_assistant_session,
)
from app.services.assistant.tools import KNOWN_TOOLS, TOOLS

__all__ = [
    "KNOWN_TOOLS",
    "MAX_SESSION_CONTEXT_CHARS",
    "SURFACE_TEXT",
    "SURFACE_VOICE",
    "TOOLS",
    "AssistantConfig",
    "AssistantEngineError",
    "AssistantInputInvalidError",
    "AssistantModelFailedError",
    "AssistantSessionNotFoundError",
    "AssistantTurnResult",
    "AssistantUnavailableError",
    "ToolCallRecord",
    "answer_assistant_turn",
    "resolve_assistant_config",
    "resolve_assistant_session",
]
