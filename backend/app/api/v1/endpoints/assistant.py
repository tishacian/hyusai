"""HTTP surface of the conversational assistant engine.

One route, one turn. Everything the front needs to render an answer — text,
citations, the tools that were called with their results, and the conversation
id — comes back in a single response. The engine holds the behaviour; this
module only translates transport and errors.
"""
from __future__ import annotations

import json
import hashlib
from uuid import uuid4
from sqlalchemy.exc import IntegrityError
from app.models.assistant_request import AssistantRequest
from app.services.assistant.tools import (
    ToolContext,
    KNOWN_TOOLS,
    visible_system,
    execute_tool,
    AssistantToolError,
    _list_systems,
)
from app.services.assistant.config import resolve_assistant_config
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

    request_id: str | None = Field(default=None, min_length=8, max_length=64)
    system_ids: list[str] | None = Field(default=None, max_length=10)
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


def scope_context(db, user, workspace, system_ids, *, surface="pilot"):
    config = resolve_assistant_config(workspace, known_tools=KNOWN_TOOLS)
    scope = tuple(sorted(set(system_ids))) if system_ids is not None else None
    ctx = ToolContext(db, user, workspace, config, "", surface, {}, system_ids=scope)
    for identifier in scope or ():
        if not isinstance(identifier, str) or len(identifier) > 64:
            raise HTTPException(422, "Invalid System identifier")
        try:
            visible_system(ctx, identifier)
        except AssistantToolError as exc:
            raise HTTPException(404, exc.as_result()) from exc
    return ctx


@router.get("/systems")
async def discover_systems(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    ctx = scope_context(db, user, workspace, [])
    return await _list_systems(ctx, {})


@router.post("/turns")
async def create_assistant_turn(
    body: AssistantTurnRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> dict[str, Any]:
    # Validate every identifier before claiming a request or returning cached content.
    scope_context(db, user, workspace, body.system_ids, surface=body.surface)
    if body.surface == "pilot" and (body.request_id is None or body.system_ids is None):
        raise HTTPException(422, "The pilot requires request_id and explicit System scope")
    receipt = None
    if body.request_id:
        fingerprint = hashlib.sha256(
            body.model_dump_json(exclude={"request_id"}).encode()
        ).hexdigest()
        receipt = AssistantRequest(
            id=str(uuid4()),
            workspace_id=workspace.id,
            user_id=user.id,
            request_id=body.request_id,
            fingerprint=fingerprint,
            state="pending",
        )
        db.add(receipt)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            receipt = (
                db.query(AssistantRequest)
                .filter_by(workspace_id=workspace.id, user_id=user.id, request_id=body.request_id)
                .one()
            )
            if receipt.fingerprint != fingerprint:
                raise HTTPException(
                    409,
                    {"code": "request_id_conflict", "message": "Use the original request body."},
                )
            if receipt.state == "completed":
                # A scope-free legacy answer may contain run data; never replay it after access changes.
                from app.services.assistant.tools import _visible_run

                ctx = scope_context(db, user, workspace, body.system_ids)
                for call in (receipt.response or {}).get("tool_calls", []):
                    result = call.get("result") or {}
                    for item in [result, *(result.get("runs") or [])]:
                        if item.get("run_id"):
                            try:
                                _visible_run(ctx, item["run_id"])
                            except AssistantToolError as exc:
                                raise HTTPException(403, "Run access changed") from exc
                return receipt.response
            raise HTTPException(
                409,
                {
                    "code": "request_" + receipt.state,
                    "message": "This request was already accepted. Inspect its Runs before starting another action.",
                },
            )
    try:
        kwargs = dict(
            user=user,
            workspace=workspace,
            text=body.text,
            session_id=body.session_id,
            surface=body.surface,
            session_context=body.session_context,
        )
        if body.system_ids is not None:
            kwargs["system_ids"] = body.system_ids
        result = await answer_assistant_turn(db, **kwargs)
        payload = result.as_payload()
        if receipt:
            receipt.state, receipt.response = "completed", payload
            receipt.session_id = result.session_id
            db.commit()
        return payload
    except Exception as exc:
        db.rollback()
        if receipt:
            receipt.state = "failed"
            db.add(receipt)
            db.commit()
        if isinstance(exc, AssistantEngineError):
            raise HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)}) from exc
        raise


class AssistantDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_ids: list[str] = Field(min_length=1, max_length=10)
    run_id: str = Field(min_length=1, max_length=64)
    decision_id: str = Field(min_length=1, max_length=64)
    decision: str = Field(pattern="^(accept|reject)$")
    note: str = Field(default="", max_length=1000)


@router.post("/decisions")
async def answer_assistant_decision(
    body: AssistantDecisionRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    ctx = scope_context(db, user, workspace, body.system_ids)
    ctx.expected_decision_id = body.decision_id
    result = await execute_tool(ctx, "answer_hitl_gate", body.model_dump())
    if not result.get("ok"):
        raise HTTPException(
            409
            if result.get("error") in {"gate_stale", "gate_not_pending", "gate_transition_invalid"}
            else 403,
            result,
        )
    return result
