"""LiveKit control-plane endpoints for realtime Agentium voice sessions."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.db.base import get_db
from app.core.iam.dependencies import PermissionContext, require_permission
from app.core.logging import get_logger
from app.services.livekit_service import LiveKitService, LiveKitServiceError, LiveKitUpstreamError

logger = get_logger(__name__)

router = APIRouter()

livekit_permission = require_permission(
    "voice_runtime",
    "read",
    static_attrs={"capability": "voice2voice_interaction", "transport": "livekit"},
    audit_prefix="livekit",
)


class LiveKitRoomRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    surface: str = Field(default="knowledge_capture", min_length=1)
    mode: str = Field(default="conversation_only", min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LiveKitTokenRequest(LiveKitRoomRequest):
    room_name: Optional[str] = None
    participant_name: Optional[str] = None
    participant_role: str = "expert"
    ensure_room: bool = True
    ttl_seconds: Optional[int] = Field(default=None, ge=30, le=24 * 3600)


class LiveKitAgentDispatchRequest(BaseModel):
    surface: str = Field(default="knowledge_capture", min_length=1)
    mode: str = Field(default="conversation_only", min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    destination_identity: Optional[str] = None
    mock_partial_text: Optional[str] = None


@router.get("/config")
async def livekit_config(permission: PermissionContext = Depends(livekit_permission)) -> Dict[str, Any]:
    del permission
    return LiveKitService().public_config()


@router.post("/rooms")
async def livekit_room(
    req: LiveKitRoomRequest,
    permission: PermissionContext = Depends(livekit_permission),
) -> Dict[str, Any]:
    service = LiveKitService()
    room_name = service.build_room_name(
        workspace_slug=permission.workspace.slug,
        session_id=req.session_id,
        surface=req.surface,
    )
    metadata = service.room_metadata(
        workspace_id=permission.workspace.id,
        workspace_slug=permission.workspace.slug,
        session_id=req.session_id,
        surface=req.surface,
        mode=req.mode,
        created_by_user_id=permission.user.id,
        extra=req.metadata,
    )
    try:
        result = await service.ensure_room(room_name=room_name, metadata=metadata)
    except LiveKitServiceError as exc:
        raise _livekit_http_error(exc) from exc
    return {
        "enabled": service.public_config()["enabled"],
        "configured": service.configured,
        "room_name": result.room_name,
        "existed": result.existed,
        "metadata": result.metadata,
        "room": result.room,
    }


@router.post("/token")
async def livekit_token(
    req: LiveKitTokenRequest,
    permission: PermissionContext = Depends(livekit_permission),
) -> Dict[str, Any]:
    service = LiveKitService()
    room_name = req.room_name or service.build_room_name(
        workspace_slug=permission.workspace.slug,
        session_id=req.session_id,
        surface=req.surface,
    )
    metadata = service.room_metadata(
        workspace_id=permission.workspace.id,
        workspace_slug=permission.workspace.slug,
        session_id=req.session_id,
        surface=req.surface,
        mode=req.mode,
        created_by_user_id=permission.user.id,
        extra=req.metadata,
    )
    try:
        existed: Optional[bool] = None
        if req.ensure_room:
            room = await service.ensure_room(room_name=room_name, metadata=metadata)
            existed = room.existed
        identity = service.build_participant_identity(
            user_id=permission.user.id,
            session_id=req.session_id,
            role=req.participant_role,
        )
        token = service.issue_participant_token(
            room_name=room_name,
            identity=identity,
            name=req.participant_name or permission.user.email or permission.user.username,
            metadata={
                **metadata,
                "attributes": {
                    "workspace_id": permission.workspace.id,
                    "workspace_slug": permission.workspace.slug,
                    "agentium_session_id": req.session_id,
                    "surface": req.surface,
                },
            },
            ttl_seconds=req.ttl_seconds,
        )
    except LiveKitServiceError as exc:
        raise _livekit_http_error(exc) from exc
    return {
        "enabled": service.public_config()["enabled"],
        "configured": service.configured,
        "url": service.public_config()["url"],
        "room_name": room_name,
        "room_existed": existed,
        "identity": identity,
        "token": token,
        "metadata": metadata,
    }


@router.post("/sessions/{session_id}/agent/dispatch")
async def livekit_agent_dispatch(
    session_id: str,
    req: LiveKitAgentDispatchRequest,
    permission: PermissionContext = Depends(livekit_permission),
) -> Dict[str, Any]:
    service = LiveKitService()
    room_name = service.build_room_name(
        workspace_slug=permission.workspace.slug,
        session_id=session_id,
        surface=req.surface,
    )
    metadata = service.room_metadata(
        workspace_id=permission.workspace.id,
        workspace_slug=permission.workspace.slug,
        session_id=session_id,
        surface=req.surface,
        mode=req.mode,
        created_by_user_id=permission.user.id,
        extra=req.metadata,
    )
    try:
        room = await service.ensure_room(room_name=room_name, metadata=metadata)
        agent_identity = service.build_agent_identity(session_id=session_id)
        sidecar = await service.dispatch_agent_sidecar(
            room_name=room_name,
            session_id=session_id,
            agent_identity=agent_identity,
            metadata=metadata,
            destination_identity=req.destination_identity,
        )
        events = []
        if sidecar.mode == "data_only_fallback":
            events.append(
                await service.send_agentium_event(
                    room_name=room_name,
                    session_id=session_id,
                    event_type="session.ready",
                    payload={
                        "agent_identity": agent_identity,
                        "room_name": room_name,
                        "room_existed": room.existed,
                        "fallback_reason": sidecar.fallback_reason,
                    },
                    destination_identity=req.destination_identity,
                )
            )
        events.append(
            await service.send_agentium_event(
                room_name=room_name,
                session_id=session_id,
                event_type="runtime.metric",
                payload={
                    "metric": "livekit_agent_dispatched",
                    "agent_mode": sidecar.mode,
                    "sidecar_status": sidecar.status,
                    "connect_attempts": sidecar.response.get("connect_attempts"),
                    "audio_bridge": _audio_bridge_status(sidecar.mode),
                    "fallback_reason": sidecar.fallback_reason,
                },
                sequence=1,
                topic="agentium.voice.metric",
                destination_identity=req.destination_identity,
            )
        )
        if req.mock_partial_text:
            events.append(
                await service.send_agentium_event(
                    room_name=room_name,
                    session_id=session_id,
                    event_type="text.partial",
                    payload={
                        "text": req.mock_partial_text,
                        "transcript_state": "partial",
                        "agent_mode": "data_only",
                    },
                    sequence=2,
                    destination_identity=req.destination_identity,
                )
            )
    except LiveKitServiceError as exc:
        raise _livekit_http_error(exc) from exc
    return {
        "status": "dispatched",
        "mode": sidecar.mode,
        "room_name": room_name,
        "room_existed": room.existed,
        "agent_identity": agent_identity,
        "sidecar": sidecar.response,
        "fallback_reason": sidecar.fallback_reason,
        "events": events,
    }


@router.post("/webhooks")
async def livekit_webhook(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: DBSession = Depends(get_db),
) -> Dict[str, Any]:
    service = LiveKitService()
    try:
        claims = service.validate_webhook_authorization(authorization)
    except LiveKitServiceError as exc:
        raise _livekit_http_error(exc) from exc
    try:
        raw_payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "invalid_livekit_webhook_payload", "message": "Invalid JSON payload"}) from exc
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    record = service.record_webhook_event(db, payload)
    logger.info(
        "livekit.webhook.accepted",
        livekit_event=payload.get("event"),
        room=payload.get("room", {}).get("name") if isinstance(payload.get("room"), dict) else None,
        issuer=claims.get("iss"),
        recorded=record.get("recorded"),
    )
    return {"status": "accepted", "event": payload.get("event"), "record": record}


def _livekit_http_error(exc: LiveKitServiceError) -> HTTPException:
    status_code = 502 if isinstance(exc, LiveKitUpstreamError) else 503
    if exc.code == "livekit_not_configured":
        status_code = 503
    if exc.code == "livekit_auth_error":
        status_code = 401
    return HTTPException(status_code=status_code, detail={"code": exc.code, "message": str(exc)})


def _audio_bridge_status(mode: str) -> str:
    if mode == "voice_gateway_bridge":
        return "voice_gateway_ready"
    if mode == "media_observer":
        return "media_observer_ready"
    return "pending"
