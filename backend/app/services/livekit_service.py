"""LiveKit control-plane helpers for Agentium realtime voice sessions.

The LiveKit server itself is deployed as a Docker service. Agentium only owns
room naming, scoped access tokens, and small RoomService calls through LiveKit's
Twirp API.
"""
from __future__ import annotations

import hashlib
import base64
import hmac
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx
import jwt
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.expert_capture import ExpertCaptureSession

_ROOM_SAFE_RE = re.compile(r"[^a-zA-Z0-9_-]+")


class LiveKitServiceError(RuntimeError):
    """Base error for LiveKit control-plane failures."""

    code = "livekit_error"


class LiveKitNotConfiguredError(LiveKitServiceError):
    code = "livekit_not_configured"


class LiveKitAuthError(LiveKitServiceError):
    code = "livekit_auth_error"


class LiveKitUpstreamError(LiveKitServiceError):
    code = "livekit_upstream_error"


@dataclass(frozen=True)
class LiveKitRoomResult:
    room_name: str
    metadata: Dict[str, Any]
    existed: bool
    room: Dict[str, Any]


@dataclass(frozen=True)
class LiveKitAgentDispatchResult:
    status: str
    mode: str
    agent_identity: str
    response: Dict[str, Any]
    fallback_reason: Optional[str] = None


def _compact_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _safe_segment(value: str, *, fallback: str) -> str:
    cleaned = _ROOM_SAFE_RE.sub("-", value.strip()).strip("-_").lower()
    return cleaned[:48] or fallback


def _parse_metadata(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _csv_slugs(value: str) -> list[str]:
    return sorted({item.strip().lower() for item in (value or "").split(",") if item.strip()})


class LiveKitService:
    """Small LiveKit API facade that avoids importing the Go server repo."""

    @property
    def configured(self) -> bool:
        return bool(
            settings.livekit_enabled
            and settings.livekit_url
            and settings.livekit_internal_url
            and settings.livekit_api_key
            and settings.livekit_api_secret
        )

    def public_config(self) -> Dict[str, Any]:
        recording_allowed_workspaces = _csv_slugs(settings.livekit_recording_allowed_workspace_slugs)
        redis_configured = bool((settings.livekit_redis_address or "").strip())
        return {
            "enabled": bool(settings.livekit_enabled),
            "configured": self.configured,
            "url": settings.livekit_url if settings.livekit_enabled else None,
            "transport": "livekit",
            "fallback_transport": "backend_ws",
            "room_ttl_seconds": settings.livekit_default_room_ttl_seconds,
            "scale": {
                "mode": "multi_node_redis" if redis_configured else "single_node",
                "redis_configured": redis_configured,
            },
            "turn": {
                "mode": settings.livekit_turn_mode,
            },
            "agents": {
                "mode": settings.livekit_agents_mode,
            },
            "governance": {
                "egress_enabled": bool(settings.livekit_egress_enabled),
                "recording_default": "disabled",
                "recording_allowed_workspace_slugs": recording_allowed_workspaces,
                "raw_audio_retention": "disabled",
            },
            "topics": {
                "events": "agentium.voice.event",
                "control": "agentium.voice.control",
                "metrics": "agentium.voice.metric",
                "chat": "agentium.chat.event",
            },
        }

    def sidecar_livekit_url(self) -> str:
        """Return the LiveKit URL a backend participant should use inside Docker."""
        self.require_configured()
        internal = (settings.livekit_internal_url or "").strip()
        parsed = urlsplit(internal)
        if parsed.scheme in {"ws", "wss"}:
            return internal.rstrip("/")
        if parsed.scheme == "http":
            return urlunsplit(("ws", parsed.netloc, parsed.path.rstrip("/"), parsed.query, parsed.fragment))
        if parsed.scheme == "https":
            return urlunsplit(("wss", parsed.netloc, parsed.path.rstrip("/"), parsed.query, parsed.fragment))
        public = (settings.livekit_url or "").strip()
        return public.rstrip("/")

    def require_configured(self) -> None:
        if not self.configured:
            raise LiveKitNotConfiguredError(
                "LiveKit is disabled or missing LIVEKIT_URL, LIVEKIT_INTERNAL_URL, LIVEKIT_API_KEY, or LIVEKIT_API_SECRET"
            )

    def build_room_name(self, *, workspace_slug: str, session_id: str, surface: str = "voice") -> str:
        prefix = _safe_segment(settings.livekit_room_prefix or "agentium", fallback="agentium")
        workspace = _safe_segment(workspace_slug or "workspace", fallback="workspace")
        surface_slug = _safe_segment(surface or "voice", fallback="voice")
        digest = hashlib.sha256(f"{workspace_slug}:{session_id}:{surface}".encode("utf-8")).hexdigest()[:16]
        return f"{prefix}-{workspace}-{surface_slug}-{digest}"

    def build_participant_identity(self, *, user_id: str, session_id: str, role: str = "expert") -> str:
        role_slug = _safe_segment(role or "expert", fallback="expert")
        digest = hashlib.sha256(f"{user_id}:{session_id}:{role}".encode("utf-8")).hexdigest()[:12]
        return f"{role_slug}-{digest}"

    def build_agent_identity(self, *, session_id: str) -> str:
        prefix = _safe_segment(settings.livekit_agent_identity_prefix or "agentium-agent", fallback="agentium-agent")
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
        return f"{prefix}-{digest}"

    def room_metadata(
        self,
        *,
        workspace_id: str,
        workspace_slug: str,
        session_id: str,
        surface: str,
        mode: str,
        created_by_user_id: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "agentium_session_id": session_id,
            "workspace_id": workspace_id,
            "workspace_slug": workspace_slug,
            "surface": surface,
            "mode": mode,
            "created_by_user_id": created_by_user_id,
            "transport": "livekit",
        }
        if extra:
            metadata["extra"] = extra
        return metadata

    def issue_participant_token(
        self,
        *,
        room_name: str,
        identity: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[int] = None,
        hidden: bool = False,
        agent: bool = False,
    ) -> str:
        self.require_configured()
        video_grants: Dict[str, Any] = {
            "roomJoin": True,
            "room": room_name,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        }
        if hidden:
            video_grants["hidden"] = True
        if agent:
            video_grants["agent"] = True
        return self._issue_token(
            identity=identity,
            name=name,
            video_grants=video_grants,
            metadata=metadata,
            ttl_seconds=ttl_seconds,
        )

    def issue_room_admin_token(self, *, room_name: Optional[str] = None, ttl_seconds: int = 60) -> str:
        self.require_configured()
        video_grants: Dict[str, Any] = {
            "roomCreate": True,
            "roomList": True,
            "roomAdmin": True,
            "canPublish": False,
            "canSubscribe": False,
            "canPublishData": False,
        }
        if room_name:
            video_grants["room"] = room_name
        return self._issue_token(
            identity="agentium-livekit-control-plane",
            video_grants=video_grants,
            ttl_seconds=ttl_seconds,
        )

    def issue_voice_bridge_token(
        self,
        *,
        session_id: str,
        workspace_id: str,
        workspace_slug: str,
        user_id: str,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """Issue a short-lived internal token for the LiveKit sidecar -> voice gateway bridge."""
        self.require_configured()
        now = int(time.time())
        ttl = ttl_seconds or settings.livekit_voice_bridge_token_ttl_seconds
        payload: Dict[str, Any] = {
            "iss": settings.livekit_api_key,
            "sub": user_id,
            "typ": "agentium.livekit.voice_bridge",
            "nbf": now - 1,
            "exp": now + max(1, int(ttl)),
            "session_id": session_id,
            "workspace_id": workspace_id,
            "workspace_slug": workspace_slug,
            "user_id": user_id,
        }
        return jwt.encode(payload, settings.livekit_api_secret or "", algorithm="HS256")

    def decode_voice_bridge_token(self, token: str, *, session_id: Optional[str] = None) -> Dict[str, Any]:
        self.require_configured()
        try:
            claims = jwt.decode(
                token,
                settings.livekit_api_secret or "",
                algorithms=["HS256"],
                issuer=settings.livekit_api_key,
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise LiveKitServiceError("Invalid LiveKit voice bridge token") from exc
        if claims.get("typ") != "agentium.livekit.voice_bridge":
            raise LiveKitServiceError("Invalid LiveKit voice bridge token type")
        if session_id and claims.get("session_id") != session_id:
            raise LiveKitServiceError("LiveKit voice bridge token does not match the requested session")
        return claims

    def validate_webhook_authorization(self, authorization: Optional[str], raw_body: bytes | str) -> Dict[str, Any]:
        self.require_configured()
        if not authorization:
            raise LiveKitAuthError("Missing LiveKit webhook authorization token")
        token = authorization.strip()
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()
        if not token:
            raise LiveKitAuthError("Missing LiveKit webhook authorization token")
        try:
            issuer = settings.livekit_webhook_api_key or settings.livekit_api_key
            api_secret = settings.livekit_webhook_api_secret or settings.livekit_api_secret or ""
            claims = jwt.decode(
                token,
                api_secret,
                algorithms=["HS256"],
                issuer=issuer,
                leeway=10,
                options={"verify_aud": False},
            )
            encoded_hash = claims.get("sha256")
            if not encoded_hash:
                raise LiveKitAuthError("Missing LiveKit webhook payload hash")
            body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
            expected_hash = base64.b64decode(str(encoded_hash), validate=True)
            actual_hash = hashlib.sha256(body_bytes).digest()
            if not hmac.compare_digest(actual_hash, expected_hash):
                raise LiveKitAuthError("Invalid LiveKit webhook payload hash")
            return claims
        except LiveKitAuthError:
            raise
        except (ValueError, TypeError) as exc:
            raise LiveKitAuthError("Invalid LiveKit webhook payload hash") from exc
        except jwt.PyJWTError as exc:
            raise LiveKitAuthError("Invalid LiveKit webhook bearer token") from exc

    def record_webhook_event(self, db: DBSession, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist LiveKit lifecycle telemetry on the linked capture session metrics."""
        event_type = str(payload.get("event") or "unknown")
        room = payload.get("room") if isinstance(payload.get("room"), dict) else {}
        metadata = _parse_metadata(room.get("metadata"))
        session_id = str(metadata.get("agentium_session_id") or "")
        workspace_id = str(metadata.get("workspace_id") or "")
        room_name = str(room.get("name") or "")
        session = None
        if session_id and workspace_id:
            session = (
                db.query(ExpertCaptureSession)
                .filter(ExpertCaptureSession.id == session_id, ExpertCaptureSession.workspace_id == workspace_id)
                .first()
            )
        if not session and room_name:
            candidates = (
                db.query(ExpertCaptureSession)
                .filter(ExpertCaptureSession.metrics.isnot(None))
                .order_by(ExpertCaptureSession.updated_at.desc())
                .limit(200)
                .all()
            )
            for candidate in candidates:
                livekit_metrics = (candidate.metrics or {}).get("livekit") or {}
                if isinstance(livekit_metrics, dict) and livekit_metrics.get("room_name") == room_name:
                    session = candidate
                    session_id = candidate.id
                    workspace_id = candidate.workspace_id
                    break
        if not session_id or not workspace_id:
            return {
                "recorded": False,
                "reason": "missing_agentium_metadata",
                "event": event_type,
                "room_name": room_name or None,
            }
        if not session:
            return {
                "recorded": False,
                "reason": "capture_session_not_found",
                "event": event_type,
                "session_id": session_id,
                "workspace_id": workspace_id,
            }

        now = datetime.utcnow().isoformat()
        metrics = dict(session.metrics or {})
        livekit = dict(metrics.get("livekit") or {})
        counts = dict(livekit.get("event_counts") or {})
        counts[event_type] = int(counts.get(event_type) or 0) + 1
        livekit.update(
            {
                "room_name": room.get("name") or livekit.get("room_name"),
                "room_sid": room.get("sid") or livekit.get("room_sid"),
                "last_event": event_type,
                "last_event_at": now,
                "event_counts": counts,
            }
        )
        if event_type in {"room_started", "room_created"}:
            livekit["room_status"] = "active"
            livekit.setdefault("room_started_at", now)
        if event_type in {"room_finished", "room_deleted"}:
            livekit["room_status"] = "closed"
            livekit["room_finished_at"] = now

        participant = payload.get("participant") if isinstance(payload.get("participant"), dict) else {}
        self._record_webhook_participant(livekit, event_type=event_type, participant=participant, now=now)
        track = payload.get("track") if isinstance(payload.get("track"), dict) else {}
        self._record_webhook_track(livekit, event_type=event_type, participant=participant, track=track, now=now)
        events = list(livekit.get("events") or [])
        events.append(
            {
                "event": event_type,
                "at": now,
                "room": {"name": room.get("name"), "sid": room.get("sid")},
                "participant_identity": participant.get("identity"),
                "track_sid": track.get("sid"),
            }
        )
        livekit["events"] = events[-25:]
        metrics["livekit"] = livekit
        session.metrics = metrics
        db.commit()
        return {
            "recorded": True,
            "event": event_type,
            "session_id": session_id,
            "workspace_id": workspace_id,
            "room_name": livekit.get("room_name"),
        }

    @staticmethod
    def _record_webhook_participant(
        livekit: Dict[str, Any],
        *,
        event_type: str,
        participant: Dict[str, Any],
        now: str,
    ) -> None:
        identity = participant.get("identity")
        if not identity:
            return
        participants = dict(livekit.get("participants") or {})
        record = dict(participants.get(identity) or {})
        record.update(
            {
                "identity": identity,
                "sid": participant.get("sid") or record.get("sid"),
                "name": participant.get("name") or record.get("name"),
                "kind": participant.get("kind") or record.get("kind"),
                "last_event": event_type,
                "last_seen_at": now,
            }
        )
        if event_type in {"participant_joined", "participant_connected"}:
            record["status"] = "joined"
            record.setdefault("joined_at", now)
        if event_type in {"participant_left", "participant_disconnected"}:
            record["status"] = "left"
            record["left_at"] = now
        participants[str(identity)] = record
        livekit["participants"] = participants

    @staticmethod
    def _record_webhook_track(
        livekit: Dict[str, Any],
        *,
        event_type: str,
        participant: Dict[str, Any],
        track: Dict[str, Any],
        now: str,
    ) -> None:
        sid = track.get("sid") or track.get("trackSid")
        if not sid:
            return
        tracks = dict(livekit.get("tracks") or {})
        record = dict(tracks.get(sid) or {})
        record.update(
            {
                "sid": sid,
                "name": track.get("name") or record.get("name"),
                "type": track.get("type") or record.get("type"),
                "source": track.get("source") or record.get("source"),
                "participant_identity": participant.get("identity") or record.get("participant_identity"),
                "last_event": event_type,
                "last_seen_at": now,
            }
        )
        if event_type in {"track_published", "track_subscribed"}:
            record["status"] = "active"
            record.setdefault("started_at", now)
        if event_type in {"track_unpublished", "track_unsubscribed"}:
            record["status"] = "ended"
            record["ended_at"] = now
        tracks[str(sid)] = record
        livekit["tracks"] = tracks

    async def ensure_room(
        self,
        *,
        room_name: str,
        metadata: Dict[str, Any],
        empty_timeout_seconds: Optional[int] = None,
        departure_timeout_seconds: Optional[int] = None,
    ) -> LiveKitRoomResult:
        self.require_configured()
        listed = await self._twirp("ListRooms", {"names": [room_name]}, room_name=room_name)
        rooms = listed.get("rooms") or []
        if rooms:
            room = rooms[0]
            return LiveKitRoomResult(room_name=room_name, metadata=metadata, existed=True, room=room)

        created = await self._twirp(
            "CreateRoom",
            {
                "name": room_name,
                "emptyTimeout": empty_timeout_seconds or settings.livekit_room_empty_timeout_seconds,
                "departureTimeout": departure_timeout_seconds or settings.livekit_room_departure_timeout_seconds,
                "metadata": _compact_json(metadata),
            },
            room_name=room_name,
        )
        return LiveKitRoomResult(room_name=room_name, metadata=metadata, existed=False, room=created)

    async def send_agentium_event(
        self,
        *,
        room_name: str,
        session_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        topic: str = "agentium.voice.event",
        sequence: int = 0,
        destination_identity: Optional[str] = None,
    ) -> Dict[str, Any]:
        event = {
            "id": f"lk-evt-{uuid4()}",
            "session_id": session_id,
            "type": event_type,
            "ts_ms": int(time.time() * 1000),
            "sequence": sequence,
            "payload": {
                "transport": "livekit",
                "provider": "livekit_agent",
                **(payload or {}),
            },
        }
        request: Dict[str, Any] = {
            "room": room_name,
            "data": base64.b64encode(_compact_json(event).encode("utf-8")).decode("ascii"),
            "kind": 0,
            "topic": topic,
            "nonce": base64.b64encode(uuid4().bytes).decode("ascii"),
        }
        if destination_identity:
            request["destinationIdentities"] = [destination_identity]
        await self._twirp("SendData", request, room_name=room_name)
        return event

    async def dispatch_agent_sidecar(
        self,
        *,
        room_name: str,
        session_id: str,
        agent_identity: str,
        metadata: Dict[str, Any],
        destination_identity: Optional[str] = None,
        voice_session_start: Optional[Dict[str, Any]] = None,
    ) -> LiveKitAgentDispatchResult:
        if not settings.livekit_agent_dispatch_url:
            return LiveKitAgentDispatchResult(
                status="not_configured",
                mode="data_only_fallback",
                agent_identity=agent_identity,
                response={},
                fallback_reason="LIVEKIT_AGENT_DISPATCH_URL is not configured",
            )
        token = self.issue_participant_token(
            room_name=room_name,
            identity=agent_identity,
            name="Agentium LiveKit Agent",
            metadata={
                **metadata,
                "attributes": {
                    "lk.agent_name": "agentium-livekit-agent",
                    "agentium_session_id": session_id,
                    "agentium_role": "voice_agent",
                },
            },
            hidden=True,
            agent=True,
        )
        body = {
            "livekit_url": self.sidecar_livekit_url(),
            "livekit_public_url": settings.livekit_url,
            "token": token,
            "room_name": room_name,
            "session_id": session_id,
            "agent_identity": agent_identity,
            "destination_identity": destination_identity,
            "topics": self.public_config()["topics"],
            "metadata": metadata,
        }
        if settings.livekit_voice_gateway_ws_url:
            requested_start = dict(voice_session_start or {})
            if not requested_start:
                maybe_metadata_start = metadata.get("voice_session_start") if isinstance(metadata, dict) else None
                requested_start = dict(maybe_metadata_start) if isinstance(maybe_metadata_start, dict) else {}
            session_start = {
                "runtime": "cascade_openai",
                "provider": "cascade_openai",
                "transport": "livekit",
                "mode": metadata.get("mode") or "conversation_only",
                "capability": "voice2voice_interaction",
                "tandem_oracle": True,
                "codec": {"input": "pcm_wav", "channels": 1},
            }
            session_start.update({key: value for key, value in requested_start.items() if value is not None})
            session_start["transport"] = "livekit"
            if not isinstance(session_start.get("codec"), dict):
                session_start["codec"] = {"input": "pcm_wav", "channels": 1}
            body["voice_gateway"] = {
                "url": settings.livekit_voice_gateway_ws_url,
                "token": self.issue_voice_bridge_token(
                    session_id=session_id,
                    workspace_id=str(metadata.get("workspace_id") or ""),
                    workspace_slug=str(metadata.get("workspace_slug") or ""),
                    user_id=str(metadata.get("created_by_user_id") or ""),
                ),
                "workspace_slug": metadata.get("workspace_slug"),
                "session_start": session_start,
                "realtime_stt": self.realtime_stt_payload(session_start, metadata),
            }
        try:
            payload = await self._post_agent_dispatch(settings.livekit_agent_dispatch_url, body)
            return LiveKitAgentDispatchResult(
                status=str(payload.get("status") or "accepted"),
                mode=str(payload.get("mode") or "media_observer"),
                agent_identity=agent_identity,
                response=payload,
            )
        except httpx.HTTPError as exc:
            return LiveKitAgentDispatchResult(
                status="fallback",
                mode="data_only_fallback",
                agent_identity=agent_identity,
                response={},
                fallback_reason=str(exc),
            )

    def realtime_stt_enabled(self, workspace_slug: Optional[str]) -> bool:
        """Whether the LiveKit sidecar should stream STT via gpt-realtime-whisper.

        Gated by the dedicated master switch and an optional workspace allowlist.
        An empty allowlist means every LiveKit-capable workspace is eligible once
        the master switch is on.
        """
        if not settings.voice_realtime_stt_enabled:
            return False
        allow = _csv_slugs(settings.voice_realtime_stt_workspace_slugs)
        if allow and str(workspace_slug or "").strip().lower() not in allow:
            return False
        return True

    def realtime_stt_payload(
        self,
        session_start: Optional[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Realtime STT config carried to the sidecar in the dispatch body.

        A per-session ``session_start.realtime_stt`` boolean overrides the
        settings-derived default (so a workspace can force it on/off without an
        env change); otherwise the master switch + allowlist decide.
        """
        start = session_start if isinstance(session_start, dict) else {}
        meta = metadata if isinstance(metadata, dict) else {}
        requested = start.get("realtime_stt")
        if isinstance(requested, bool):
            enabled = requested
        else:
            enabled = self.realtime_stt_enabled(meta.get("workspace_slug"))
        if not enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "model": settings.openai_realtime_transcribe_model,
            "language": start.get("language") or start.get("input_language") or "fr",
            "api_base": settings.openai_realtime_api_base,
            "delay": settings.voice_realtime_stt_delay or "low",
            # Sidecar silence-VAD tuning (gpt-realtime-whisper commits manually).
            "silence_ms": settings.voice_realtime_stt_silence_ms,
            "vad_threshold": settings.voice_realtime_stt_vad_threshold,
            "max_turn_ms": settings.voice_realtime_stt_max_turn_ms,
        }

    async def _post_agent_dispatch(self, url: str, body: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=settings.livekit_http_timeout_seconds) as client:
            response = await client.post(url, json=body)
        response.raise_for_status()
        return response.json() if response.content else {}

    def _issue_token(
        self,
        *,
        identity: str,
        video_grants: Dict[str, Any],
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[int] = None,
    ) -> str:
        now = int(time.time())
        ttl = ttl_seconds or settings.livekit_default_room_ttl_seconds
        payload: Dict[str, Any] = {
            "iss": settings.livekit_api_key,
            "sub": identity,
            "nbf": now - 1,
            "exp": now + max(1, int(ttl)),
            "video": video_grants,
        }
        if name:
            payload["name"] = name
        if metadata:
            payload["metadata"] = _compact_json(metadata)
            attributes = metadata.get("attributes")
            if isinstance(attributes, dict):
                payload["attributes"] = {str(key): str(value) for key, value in attributes.items()}
        return jwt.encode(payload, settings.livekit_api_secret or "", algorithm="HS256")

    async def _twirp(self, method: str, body: Dict[str, Any], *, room_name: Optional[str] = None) -> Dict[str, Any]:
        token = self.issue_room_admin_token(room_name=room_name)
        base_url = (settings.livekit_internal_url or "").rstrip("/")
        url = f"{base_url}/twirp/livekit.RoomService/{method}"
        try:
            async with httpx.AsyncClient(timeout=settings.livekit_http_timeout_seconds) as client:
                response = await client.post(
                    url,
                    json=body,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
            response.raise_for_status()
            return response.json() if response.content else {}
        except httpx.HTTPStatusError as exc:
            raise LiveKitUpstreamError(
                f"LiveKit RoomService {method} failed with HTTP {exc.response.status_code}: {exc.response.text[:240]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LiveKitUpstreamError(f"LiveKit RoomService {method} failed: {exc}") from exc
