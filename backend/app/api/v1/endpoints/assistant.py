"""HTTP surface of the conversational assistant engine.

One route, one turn. Everything the front needs to render an answer — text,
citations, the tools that were called with their results, and the conversation
id — comes back in a single response. The engine holds the behaviour; this
module only translates transport and errors.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session as DBSession

from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.user import User
from app.models.workspace import Workspace
from app.services.assistant import (
    MAX_SESSION_CONTEXT_CHARS,
    SURFACE_TEXT,
    AssistantEngineError,
    answer_assistant_turn,
)

router = APIRouter()

MAX_TEXT_CHARS = 8000


class AssistantTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    session_id: str | None = Field(
        default=None,
        max_length=64,
        description="Conversation thread to continue. Omit it to open a new thread.",
    )
    surface: str = Field(
        default=SURFACE_TEXT,
        max_length=32,
        description="Calling surface, used for prompt shaping and telemetry.",
    )
    session_context: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Context owned by the surface, for example the service catalogue asset "
            "under 'service_catalog' or a client-side routing hint. Bounded to "
            f"{MAX_SESSION_CONTEXT_CHARS} characters of JSON, as on the voice lane."
        ),
    )

    @field_validator("session_context")
    @classmethod
    def _bounded_session_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Refuse a context this deployment would not accept over the voice lane.

        The voice gateway drops a push past the same ceiling, so a catalogue a
        surface can speak is a catalogue it can type. Compact separators are
        used because what the surface actually sent is ``JSON.stringify`` output,
        which is what the voice lane measures too. Only bytes are bounded here;
        the 40-entry catalogue cap stays in the engine.
        """
        size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))
        if size > MAX_SESSION_CONTEXT_CHARS:
            raise ValueError(
                f"session_context is {size} characters of JSON; "
                f"the limit is {MAX_SESSION_CONTEXT_CHARS}"
            )
        return value


@router.post("/turns")
async def create_assistant_turn(
    body: AssistantTurnRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    """Answer one user utterance with the workspace-configured assistant."""
    try:
        result = await answer_assistant_turn(
            db,
            user=user,
            workspace=workspace,
            text=body.text,
            session_id=body.session_id,
            surface=body.surface,
            session_context=body.session_context,
        )
    except AssistantEngineError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return result.as_payload()
