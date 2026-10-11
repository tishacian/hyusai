from __future__ import annotations

import base64
import hashlib
import json
import time

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import livekit
from app.core.config import settings
from app.core.iam.dependencies import PermissionContext
from app.models.expert_capture import ExpertCaptureSession
from app.models.user import User
from app.models.workspace import Workspace
from app.services.iam.engine import Decision
from app.services.livekit_service import LiveKitService


def _enable_livekit(monkeypatch) -> None:
    monkeypatch.setattr(settings, "livekit_enabled", True)
    monkeypatch.setattr(settings, "livekit_url", "wss://livekit.example.test")
    monkeypatch.setattr(settings, "livekit_internal_url", "http://agentium-livekit:7880")
    monkeypatch.setattr(settings, "livekit_api_key", "test-api-key")
    monkeypatch.setattr(settings, "livekit_api_secret", "x" * 40)
    monkeypatch.setattr(settings, "livekit_webhook_api_key", "test-webhook-key")
    monkeypatch.setattr(settings, "livekit_default_room_ttl_seconds", 3600)


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(livekit.router, prefix="/api/v1/livekit")
    app.dependency_overrides[livekit.livekit_permission] = lambda: PermissionContext(
        user=user,
        workspace=workspace,
        membership=None,
        decision=Decision(True, "allowed", "test.livekit"),
    )
    app.dependency_overrides[livekit.get_db] = lambda: db_session
    return TestClient(app)


def _decode_send_data(body: dict) -> dict:
    return json.loads(base64.b64decode(body["data"]).decode("utf-8"))


def test_livekit_token_endpoint_returns_scoped_browser_token(db_session, monkeypatch):
    _enable_livekit(monkeypatch)
    workspace = Workspace(id="workspace-livekit-api-token", name="Andritz", slug="andritz", settings={})
    user = User(id="user-livekit-api-token", username="expert", email="expert@example.test", is_active=True)
    client = _client(db_session, workspace, user)
    calls = []

    async def fake_twirp(self, method, body, *, room_name=None):  # noqa: ANN001
        calls.append((method, body, room_name))
        if method == "ListRooms":
            return {"rooms": []}
        if method == "CreateRoom":
            return {"name": body["name"], "sid": "RM_created", "metadata": body["metadata"]}
        raise AssertionError(method)

    monkeypatch.setattr(LiveKitService, "_twirp", fake_twirp)

    response = client.post(
        "/api/v1/livekit/token",
        json={"session_id": "capture-token-1", "surface": "knowledge_capture", "mode": "conversation_only"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["url"] == "wss://livekit.example.test"
    assert body["room_existed"] is False
    assert body["room_name"].startswith("agentium-andritz-knowledge_capture-")
    assert body["identity"].startswith("expert-")
    assert "api_secret" not in json.dumps(body).lower()
    assert calls[0][0] == "ListRooms"
    assert calls[1][0] == "CreateRoom"
    created_metadata = json.loads(calls[1][1]["metadata"])
    assert created_metadata["agentium_session_id"] == "capture-token-1"
    assert created_metadata["workspace_slug"] == "andritz"

    claims = jwt.decode(body["token"], settings.livekit_api_secret, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["iss"] == "test-api-key"
    assert claims["sub"] == body["identity"]
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["room"] == body["room_name"]
    assert claims["video"]["canPublish"] is True
    assert claims["video"]["canSubscribe"] is True
    assert claims["video"]["canPublishData"] is True
    assert json.loads(claims["metadata"])["agentium_session_id"] == "capture-token-1"


def test_livekit_dispatch_endpoint_keeps_data_only_fallback_when_sidecar_missing(db_session, monkeypatch):
    _enable_livekit(monkeypatch)
    monkeypatch.setattr(settings, "livekit_agent_dispatch_url", None)
    workspace = Workspace(id="workspace-livekit-api-dispatch", name="Andritz", slug="andritz", settings={})
    user = User(id="user-livekit-api-dispatch", username="expert", email="expert@example.test", is_active=True)
    client = _client(db_session, workspace, user)
    calls = []

    async def fake_twirp(self, method, body, *, room_name=None):  # noqa: ANN001
        calls.append((method, body, room_name))
        if method == "ListRooms":
            return {"rooms": [{"name": room_name, "sid": "RM_existing"}]}
        if method == "SendData":
            return {}
        raise AssertionError(method)

    monkeypatch.setattr(LiveKitService, "_twirp", fake_twirp)

    response = client.post(
        "/api/v1/livekit/sessions/capture-dispatch-1/agent/dispatch",
        json={"surface": "knowledge_capture", "destination_identity": "expert-destination"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dispatched"
    assert body["mode"] == "data_only_fallback"
    assert body["room_existed"] is True
    assert "LIVEKIT_AGENT_DISPATCH_URL" in body["fallback_reason"]
    send_data_calls = [call for call in calls if call[0] == "SendData"]
    assert len(send_data_calls) == 2
    ready_event = _decode_send_data(send_data_calls[0][1])
    metric_event = _decode_send_data(send_data_calls[1][1])
    assert ready_event["type"] == "session.ready"
    assert metric_event["type"] == "runtime.metric"
    assert metric_event["payload"]["metric"] == "livekit_agent_dispatched"
    assert metric_event["payload"]["audio_bridge"] == "pending"
    assert metric_event["payload"]["sidecar_status"] == "not_configured"
    assert metric_event["payload"]["connect_attempts"] is None
    assert send_data_calls[0][1]["destinationIdentities"] == ["expert-destination"]


def test_livekit_dispatch_endpoint_reports_voice_gateway_bridge_ready(db_session, monkeypatch):
    _enable_livekit(monkeypatch)
    monkeypatch.setattr(settings, "livekit_agent_dispatch_url", "http://agentium-livekit-agent:8090/dispatch")
    monkeypatch.setattr(settings, "livekit_voice_gateway_ws_url", "ws://agentium-backend:8000/api/v1/voice/sessions")
    workspace = Workspace(id="workspace-livekit-api-bridge", name="Andritz", slug="andritz", settings={})
    user = User(id="user-livekit-api-bridge", username="expert", email="expert@example.test", is_active=True)
    client = _client(db_session, workspace, user)
    twirp_calls = []
    dispatch_bodies = []

    async def fake_twirp(self, method, body, *, room_name=None):  # noqa: ANN001
        twirp_calls.append((method, body, room_name))
        if method == "ListRooms":
            return {"rooms": [{"name": room_name, "sid": "RM_existing"}]}
        if method == "SendData":
            return {}
        raise AssertionError(method)

    async def fake_post_agent_dispatch(self, url, body):  # noqa: ANN001
        dispatch_bodies.append((url, body))
        return {
            "status": "accepted",
            "mode": "voice_gateway_bridge",
            "session_id": body["session_id"],
            "room_name": body["room_name"],
            "agent_identity": body["agent_identity"],
            "connect_attempts": 2,
        }

    monkeypatch.setattr(LiveKitService, "_twirp", fake_twirp)
    monkeypatch.setattr(LiveKitService, "_post_agent_dispatch", fake_post_agent_dispatch)

    response = client.post(
        "/api/v1/livekit/sessions/capture-bridge-1/agent/dispatch",
        json={"surface": "knowledge_capture", "destination_identity": "expert-destination"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dispatched"
    assert body["mode"] == "voice_gateway_bridge"
    assert body["fallback_reason"] is None
    assert body["sidecar"]["mode"] == "voice_gateway_bridge"

    assert len(dispatch_bodies) == 1
    dispatch_url, dispatch_body = dispatch_bodies[0]
    assert dispatch_url == "http://agentium-livekit-agent:8090/dispatch"
    assert dispatch_body["livekit_url"] == "ws://agentium-livekit:7880"
    assert dispatch_body["livekit_public_url"] == "wss://livekit.example.test"
    assert dispatch_body["destination_identity"] == "expert-destination"
    assert dispatch_body["voice_gateway"]["url"] == "ws://agentium-backend:8000/api/v1/voice/sessions"
    assert dispatch_body["voice_gateway"]["session_start"]["transport"] == "livekit"
    assert dispatch_body["voice_gateway"]["session_start"]["codec"]["input"] == "pcm_wav"

    send_data_calls = [call for call in twirp_calls if call[0] == "SendData"]
    assert len(send_data_calls) == 1
    metric_event = _decode_send_data(send_data_calls[0][1])
    assert metric_event["type"] == "runtime.metric"
    assert metric_event["payload"]["metric"] == "livekit_agent_dispatched"
    assert metric_event["payload"]["agent_mode"] == "voice_gateway_bridge"
    assert metric_event["payload"]["sidecar_status"] == "accepted"
    assert metric_event["payload"]["connect_attempts"] == 2
    assert metric_event["payload"]["audio_bridge"] == "voice_gateway_ready"
    assert send_data_calls[0][1]["topic"] == "agentium.voice.metric"
    assert send_data_calls[0][1]["destinationIdentities"] == ["expert-destination"]


def test_livekit_webhook_endpoint_persists_capture_metrics(db_session, monkeypatch):
    _enable_livekit(monkeypatch)
    workspace = Workspace(id="workspace-livekit-api-webhook", name="Andritz", slug="andritz", settings={})
    user = User(id="user-livekit-api-webhook", username="expert", email="expert@example.test", is_active=True)
    session = ExpertCaptureSession(
        id="capture-webhook-1",
        workspace_id=workspace.id,
        title="LiveKit webhook capture",
        objective="Capture LiveKit webhook telemetry.",
        created_by_user_id=user.id,
        metrics={},
    )
    db_session.add_all([workspace, user, session])
    db_session.commit()
    client = _client(db_session, workspace, user)
    metadata = LiveKitService().room_metadata(
        workspace_id=workspace.id,
        workspace_slug=workspace.slug,
        session_id=session.id,
        surface="knowledge_capture",
        mode="conversation_only",
        created_by_user_id=user.id,
    )
    payload = {
        "event": "participant_joined",
        "room": {"name": "agentium-andritz-kc", "sid": "RM_1", "metadata": json.dumps(metadata)},
        "participant": {"identity": "expert-1", "sid": "PA_1", "name": "Expert"},
    }
    raw_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    token = jwt.encode(
        {
            "iss": settings.livekit_webhook_api_key,
            "nbf": int(time.time()) - 1,
            "exp": int(time.time()) + 60,
            "sha256": base64.b64encode(hashlib.sha256(raw_payload).digest()).decode("ascii"),
        },
        settings.livekit_api_secret,
        algorithm="HS256",
    )

    response = client.post(
        "/api/v1/livekit/webhooks",
        headers={"Authorization": token, "Content-Type": "application/webhook+json"},
        content=raw_payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["record"]["recorded"] is True
    db_session.refresh(session)
    livekit_metrics = session.metrics["livekit"]
    assert livekit_metrics["event_counts"]["participant_joined"] == 1
    assert livekit_metrics["participants"]["expert-1"]["status"] == "joined"
    assert livekit_metrics["room_name"] == "agentium-andritz-kc"


def test_livekit_webhook_endpoint_rejects_missing_bearer(db_session, monkeypatch):
    _enable_livekit(monkeypatch)
    workspace = Workspace(id="workspace-livekit-api-auth", name="Andritz", slug="andritz", settings={})
    user = User(id="user-livekit-api-auth", username="expert", email="expert@example.test", is_active=True)
    client = _client(db_session, workspace, user)

    response = client.post("/api/v1/livekit/webhooks", json={"event": "room_started"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "livekit_auth_error"
