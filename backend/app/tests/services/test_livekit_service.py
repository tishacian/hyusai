import json
import base64
import hashlib

import jwt
import pytest

from app.core.config import settings
from app.models.expert_capture import ExpertCaptureSession
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.livekit_service import LiveKitNotConfiguredError, LiveKitService, LiveKitServiceError
from app.services.voice_session_gateway import VoiceSessionGateway


def _enable_livekit(monkeypatch):
    monkeypatch.setattr(settings, "livekit_enabled", True)
    monkeypatch.setattr(settings, "livekit_url", "wss://livekit.example.test")
    monkeypatch.setattr(settings, "livekit_internal_url", "http://agentium-livekit:7880")
    monkeypatch.setattr(settings, "livekit_api_key", "test-api-key")
    monkeypatch.setattr(settings, "livekit_api_secret", "x" * 40)
    monkeypatch.setattr(settings, "livekit_default_room_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "livekit_redis_address", None)
    monkeypatch.setattr(settings, "livekit_turn_mode", "external_or_none")
    monkeypatch.setattr(settings, "livekit_agents_mode", "sidecar_http_bridge")
    monkeypatch.setattr(settings, "livekit_egress_enabled", False)
    monkeypatch.setattr(settings, "livekit_recording_allowed_workspace_slugs", "")


def test_livekit_public_config_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "livekit_enabled", False)

    config = LiveKitService().public_config()

    assert config["enabled"] is False
    assert config["configured"] is False
    assert config["url"] is None
    assert config["fallback_transport"] == "backend_ws"
    assert config["scale"] == {"mode": "single_node", "redis_configured": False}
    assert config["agents"]["mode"] == "sidecar_http_bridge"
    assert config["governance"]["egress_enabled"] is False
    assert config["governance"]["raw_audio_retention"] == "disabled"


def test_livekit_public_config_exposes_p3_scale_and_governance_without_secrets(monkeypatch):
    _enable_livekit(monkeypatch)
    monkeypatch.setattr(settings, "livekit_redis_address", "agentium-livekit-redis:6379")
    monkeypatch.setattr(settings, "livekit_turn_mode", "turn_tls_required")
    monkeypatch.setattr(settings, "livekit_agents_mode", "native_agents_planned")
    monkeypatch.setattr(settings, "livekit_egress_enabled", True)
    monkeypatch.setattr(settings, "livekit_recording_allowed_workspace_slugs", "andritz, sentinel-ci, andritz")

    config = LiveKitService().public_config()

    assert config["scale"] == {"mode": "multi_node_redis", "redis_configured": True}
    assert config["turn"]["mode"] == "turn_tls_required"
    assert config["agents"]["mode"] == "native_agents_planned"
    assert config["governance"]["egress_enabled"] is True
    assert config["governance"]["recording_default"] == "disabled"
    assert config["governance"]["recording_allowed_workspace_slugs"] == ["andritz", "sentinel-ci"]
    assert "agentium-livekit-redis" not in json.dumps(config)


def test_livekit_room_name_is_sanitized_and_stable(monkeypatch):
    _enable_livekit(monkeypatch)
    service = LiveKitService()

    first = service.build_room_name(
        workspace_slug="ANDRITZ France / Non Wovens",
        session_id="capture-session-123",
        surface="knowledge capture",
    )
    second = service.build_room_name(
        workspace_slug="ANDRITZ France / Non Wovens",
        session_id="capture-session-123",
        surface="knowledge capture",
    )

    assert first == second
    assert first.startswith("agentium-andritz-france-non-wovens-knowledge-capture-")
    assert "/" not in first
    assert " " not in first


def test_livekit_participant_token_contains_scoped_video_grants(monkeypatch):
    _enable_livekit(monkeypatch)
    service = LiveKitService()

    token = service.issue_participant_token(
        room_name="agentium-andritz-kc-123",
        identity="expert-123",
        name="Expert Andritz",
        metadata={"agentium_session_id": "session-1", "attributes": {"workspace_slug": "andritz"}},
        ttl_seconds=600,
    )

    claims = jwt.decode(token, settings.livekit_api_secret, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["iss"] == settings.livekit_api_key
    assert claims["sub"] == "expert-123"
    assert claims["name"] == "Expert Andritz"
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["room"] == "agentium-andritz-kc-123"
    assert claims["video"]["canPublish"] is True
    assert claims["video"]["canSubscribe"] is True
    assert claims["video"]["canPublishData"] is True
    assert json.loads(claims["metadata"])["agentium_session_id"] == "session-1"
    assert claims["attributes"]["workspace_slug"] == "andritz"


def test_livekit_sidecar_url_uses_internal_websocket_endpoint(monkeypatch):
    _enable_livekit(monkeypatch)
    service = LiveKitService()

    assert service.sidecar_livekit_url() == "ws://agentium-livekit:7880"

    monkeypatch.setattr(settings, "livekit_internal_url", "https://livekit-internal.example.test/live")
    assert service.sidecar_livekit_url() == "wss://livekit-internal.example.test/live"


def test_livekit_voice_bridge_token_is_session_scoped(monkeypatch):
    _enable_livekit(monkeypatch)
    service = LiveKitService()

    token = service.issue_voice_bridge_token(
        session_id="session-1",
        workspace_id="workspace-1",
        workspace_slug="andritz",
        user_id="user-1",
        ttl_seconds=300,
    )

    claims = service.decode_voice_bridge_token(token, session_id="session-1")
    assert claims["typ"] == "agentium.livekit.voice_bridge"
    assert claims["session_id"] == "session-1"
    assert claims["workspace_id"] == "workspace-1"
    assert claims["workspace_slug"] == "andritz"
    assert claims["user_id"] == "user-1"
    with pytest.raises(LiveKitServiceError):
        service.decode_voice_bridge_token(token, session_id="session-2")


def test_livekit_webhook_authorization_uses_dedicated_secret_when_configured(monkeypatch):
    _enable_livekit(monkeypatch)
    monkeypatch.setattr(settings, "livekit_webhook_api_key", "webhook-key")
    monkeypatch.setattr(settings, "livekit_webhook_api_secret", "y" * 40)
    raw_body = b'{"event":"room_started"}'
    payload_hash = base64.b64encode(hashlib.sha256(raw_body).digest()).decode("ascii")
    token = jwt.encode(
        {"iss": "webhook-key", "nbf": 1, "exp": 4_102_444_800, "sha256": payload_hash},
        settings.livekit_webhook_api_secret,
        algorithm="HS256",
    )
    wrong_secret_token = jwt.encode(
        {"iss": "webhook-key", "nbf": 1, "exp": 4_102_444_800, "sha256": payload_hash},
        settings.livekit_api_secret,
        algorithm="HS256",
    )

    claims = LiveKitService().validate_webhook_authorization(f"Bearer {token}", raw_body)

    assert claims["iss"] == "webhook-key"
    with pytest.raises(LiveKitServiceError):
        LiveKitService().validate_webhook_authorization(f"Bearer {wrong_secret_token}", raw_body)
    with pytest.raises(LiveKitServiceError):
        LiveKitService().validate_webhook_authorization(f"Bearer {token}", b'{"event":"tampered"}')


def test_voice_gateway_authenticates_livekit_bridge_token(monkeypatch, db_session):
    _enable_livekit(monkeypatch)
    user = User(id="user-bridge", username="bridge@example.test", email="bridge@example.test", is_active=True)
    workspace = Workspace(id="workspace-bridge", name="Andritz", slug="andritz", settings={})
    membership = WorkspaceMember(user_id=user.id, workspace_id=workspace.id, role="member")
    db_session.add_all([user, workspace, membership])
    db_session.commit()
    token = LiveKitService().issue_voice_bridge_token(
        session_id="session-bridge",
        workspace_id=workspace.id,
        workspace_slug=workspace.slug,
        user_id=user.id,
    )

    auth = VoiceSessionGateway()._authenticate(
        db_session,
        token=token,
        workspace_slug="andritz",
        session_id="session-bridge",
    )

    assert auth is not None
    assert auth[0].id == user.id
    assert auth[1].id == workspace.id
    assert (
        VoiceSessionGateway()._authenticate(
            db_session,
            token=token,
            workspace_slug="andritz",
            session_id="other-session",
        )
        is None
    )


def test_livekit_record_webhook_event_updates_capture_metrics(monkeypatch, db_session):
    _enable_livekit(monkeypatch)
    session = ExpertCaptureSession(
        id="capture-livekit-1",
        workspace_id="workspace-livekit-1",
        title="LiveKit capture",
        objective="Capture LiveKit telemetry.",
        created_by_user_id="user-1",
        metrics={},
    )
    db_session.add(session)
    db_session.commit()
    metadata = LiveKitService().room_metadata(
        workspace_id=session.workspace_id,
        workspace_slug="andritz",
        session_id=session.id,
        surface="knowledge_capture",
        mode="conversation_only",
        created_by_user_id="user-1",
    )

    result = LiveKitService().record_webhook_event(
        db_session,
        {
            "event": "track_published",
            "room": {"name": "agentium-andritz-kc", "sid": "RM_1", "metadata": json.dumps(metadata)},
            "participant": {"identity": "expert-1", "sid": "PA_1", "name": "Expert"},
            "track": {"sid": "TR_1", "name": "microphone", "type": "audio", "source": "microphone"},
        },
    )

    assert result["recorded"] is True
    db_session.refresh(session)
    livekit = session.metrics["livekit"]
    assert livekit["room_name"] == "agentium-andritz-kc"
    assert livekit["room_sid"] == "RM_1"
    assert livekit["last_event"] == "track_published"
    assert livekit["event_counts"]["track_published"] == 1
    assert livekit["participants"]["expert-1"]["sid"] == "PA_1"
    assert livekit["tracks"]["TR_1"]["status"] == "active"
    assert livekit["tracks"]["TR_1"]["participant_identity"] == "expert-1"
    assert livekit["events"][-1]["track_sid"] == "TR_1"


def test_livekit_record_webhook_event_ignores_unlinked_room(monkeypatch, db_session):
    _enable_livekit(monkeypatch)

    result = LiveKitService().record_webhook_event(
        db_session,
        {"event": "room_started", "room": {"name": "foreign-room", "metadata": "{}"}},
    )

    assert result["recorded"] is False
    assert result["reason"] == "missing_agentium_metadata"


def test_livekit_token_requires_full_configuration(monkeypatch):
    monkeypatch.setattr(settings, "livekit_enabled", True)
    monkeypatch.setattr(settings, "livekit_url", None)

    with pytest.raises(LiveKitNotConfiguredError):
        LiveKitService().issue_participant_token(room_name="room", identity="user")


@pytest.mark.asyncio
async def test_livekit_ensure_room_creates_missing_room(monkeypatch):
    _enable_livekit(monkeypatch)
    calls = []

    class FakeLiveKitService(LiveKitService):
        async def _twirp(self, method, body, *, room_name=None):  # noqa: ANN001
            calls.append((method, body, room_name))
            if method == "ListRooms":
                return {"rooms": []}
            if method == "CreateRoom":
                return {"name": body["name"], "metadata": body["metadata"]}
            raise AssertionError(method)

    metadata = {"agentium_session_id": "session-1", "workspace_slug": "andritz"}
    result = await FakeLiveKitService().ensure_room(room_name="agentium-andritz-kc-123", metadata=metadata)

    assert result.existed is False
    assert result.room_name == "agentium-andritz-kc-123"
    assert calls[0] == ("ListRooms", {"names": ["agentium-andritz-kc-123"]}, "agentium-andritz-kc-123")
    assert calls[1][0] == "CreateRoom"
    assert calls[1][1]["name"] == "agentium-andritz-kc-123"
    assert json.loads(calls[1][1]["metadata"]) == metadata


@pytest.mark.asyncio
async def test_livekit_ensure_room_reuses_existing_room(monkeypatch):
    _enable_livekit(monkeypatch)
    calls = []

    class FakeLiveKitService(LiveKitService):
        async def _twirp(self, method, body, *, room_name=None):  # noqa: ANN001
            calls.append(method)
            return {"rooms": [{"name": room_name, "sid": "RM_existing"}]}

    result = await FakeLiveKitService().ensure_room(room_name="agentium-room", metadata={})

    assert result.existed is True
    assert result.room["sid"] == "RM_existing"
    assert calls == ["ListRooms"]


@pytest.mark.asyncio
async def test_livekit_send_agentium_event_uses_roomservice_send_data(monkeypatch):
    _enable_livekit(monkeypatch)
    calls = []

    class FakeLiveKitService(LiveKitService):
        async def _twirp(self, method, body, *, room_name=None):  # noqa: ANN001
            calls.append((method, body, room_name))
            return {}

    event = await FakeLiveKitService().send_agentium_event(
        room_name="agentium-room",
        session_id="session-1",
        event_type="text.partial",
        payload={"text": "bonjour"},
        topic="agentium.voice.event",
        destination_identity="expert-1",
    )

    assert event["type"] == "text.partial"
    assert event["payload"]["transport"] == "livekit"
    assert event["payload"]["text"] == "bonjour"
    method, body, room_name = calls[0]
    assert method == "SendData"
    assert room_name == "agentium-room"
    assert body["room"] == "agentium-room"
    assert body["kind"] == 0
    assert body["topic"] == "agentium.voice.event"
    assert body["destinationIdentities"] == ["expert-1"]
    assert len(base64.b64decode(body["nonce"])) == 16
    decoded = json.loads(base64.b64decode(body["data"]).decode("utf-8"))
    assert decoded["session_id"] == "session-1"
    assert decoded["type"] == "text.partial"
    assert decoded["payload"]["provider"] == "livekit_agent"


@pytest.mark.asyncio
async def test_livekit_agent_dispatch_posts_sidecar_payload(monkeypatch):
    _enable_livekit(monkeypatch)
    monkeypatch.setattr(settings, "livekit_agent_dispatch_url", "http://agentium-livekit-agent:8090/dispatch")
    monkeypatch.setattr(settings, "livekit_voice_gateway_ws_url", "ws://agentium-backend:8000/api/v1/voice/sessions")
    posts = []

    class FakeLiveKitService(LiveKitService):
        async def _post_agent_dispatch(self, url, body):  # noqa: ANN001
            posts.append((url, body))
            return {"status": "accepted", "mode": "media_observer", "agent_identity": body["agent_identity"]}

    result = await FakeLiveKitService().dispatch_agent_sidecar(
        room_name="agentium-room",
        session_id="session-1",
        agent_identity="agentium-agent-1",
        metadata={"workspace_id": "workspace-1", "workspace_slug": "andritz", "created_by_user_id": "user-1"},
        destination_identity="expert-1",
    )

    assert result.status == "accepted"
    assert result.mode == "media_observer"
    assert result.agent_identity == "agentium-agent-1"
    url, body = posts[0]
    assert url == "http://agentium-livekit-agent:8090/dispatch"
    assert body["livekit_url"] == "ws://agentium-livekit:7880"
    assert body["livekit_public_url"] == settings.livekit_url
    assert body["room_name"] == "agentium-room"
    assert body["session_id"] == "session-1"
    assert body["destination_identity"] == "expert-1"
    assert body["voice_gateway"]["url"] == settings.livekit_voice_gateway_ws_url
    assert body["voice_gateway"]["workspace_slug"] == "andritz"
    assert body["voice_gateway"]["session_start"]["transport"] == "livekit"
    bridge_claims = LiveKitService().decode_voice_bridge_token(body["voice_gateway"]["token"], session_id="session-1")
    assert bridge_claims["workspace_id"] == "workspace-1"
    assert bridge_claims["user_id"] == "user-1"
    claims = jwt.decode(body["token"], settings.livekit_api_secret, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["sub"] == "agentium-agent-1"
    assert claims["video"]["room"] == "agentium-room"
    assert claims["video"]["hidden"] is True
    assert claims["video"]["agent"] is True


@pytest.mark.asyncio
async def test_livekit_agent_dispatch_falls_back_when_url_missing(monkeypatch):
    _enable_livekit(monkeypatch)
    monkeypatch.setattr(settings, "livekit_agent_dispatch_url", None)

    result = await LiveKitService().dispatch_agent_sidecar(
        room_name="agentium-room",
        session_id="session-1",
        agent_identity="agentium-agent-1",
        metadata={},
    )

    assert result.status == "not_configured"
    assert result.mode == "data_only_fallback"
    assert "LIVEKIT_AGENT_DISPATCH_URL" in (result.fallback_reason or "")
