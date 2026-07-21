"""Public inbound webhook receiver — ``POST /api/v1/hooks/{hook_id}``.

Auth is HMAC (``X-Agentium-Signature``), not the workspace JWT. Management
CRUD lives under ``/systems/{id}/hooks``.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from app.db.base import SessionLocal
from app.services.run_engine import triggers
from app.services.run_engine.webhooks import SIGNATURE_HEADER, authenticate_hook

router = APIRouter()


@router.post("/{hook_id}")
async def receive_webhook(
    hook_id: str,
    request: Request,
    x_agentium_signature: Optional[str] = Header(default=None, alias=SIGNATURE_HEADER),
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
):
    """Accept an HMAC-signed payload and emit the hook's event for its System."""
    body = await request.body()
    signature = x_agentium_signature or x_hub_signature_256

    db = SessionLocal()
    try:
        hook, reason = authenticate_hook(db, hook_id, body=body, signature_header=signature)
        if hook is None:
            status = 404 if reason == "not_found" else 401 if reason == "invalid_signature" else 403
            raise HTTPException(status_code=status, detail=reason or "unauthorized")

        try:
            payload: Any = json.loads(body.decode("utf-8") or "{}") if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="invalid_json_body") from exc
        if not isinstance(payload, dict):
            payload = {"value": payload}

        event_kind = (hook.event_type or triggers.EVENT_WEBHOOK_RECEIVED).strip() or triggers.EVENT_WEBHOOK_RECEIVED
        enriched = {
            **payload,
            "_webhook": {
                "hook_id": hook.id,
                "system_id": hook.system_id,
                "event_type": event_kind,
            },
        }
        results = triggers.emit_event(
            event_kind,
            hook.workspace_id,
            enriched,
            db=db,
            system_id=hook.system_id,
        )
        return {
            "status": "accepted",
            "hook_id": hook.id,
            "event_type": event_kind,
            "results": results,
        }
    finally:
        db.close()
