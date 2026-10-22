from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.model_usage import UsageBudgetPolicy
from app.models.workspace import Workspace
from app.services import model_usage_guard as guard


@pytest.mark.parametrize("scope", ["workspace", "system:private-app"])
def test_any_active_budget_blocks_unqualified_voice_without_provider_calls(db_session, scope):
    workspace = Workspace(id=str(uuid4()), name="Voice budget", slug="voice-" + uuid4().hex)
    db_session.add(workspace)
    db_session.commit()
    assert not guard.unqualified_voice_blocked(workspace.id)
    policy = UsageBudgetPolicy(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope_key=scope,
        revision=1,
        enabled=True,
        max_tokens=100,
        currency_limits={},
        timezone="UTC",
    )
    db_session.add(policy)
    db_session.commit()
    assert guard.unqualified_voice_blocked(workspace.id)
    assert guard.unqualified_voice_blocked(workspace_slug=workspace.slug)
    policy.enabled = False
    db_session.commit()
    assert not guard.unqualified_voice_blocked(workspace.id)


async def test_livekit_dispatch_and_token_block_before_network_or_credential(monkeypatch):
    from app.services.livekit_service import LiveKitService, LiveKitUsageUnqualifiedError

    monkeypatch.setattr(guard, "unqualified_voice_blocked", lambda *a, **kw: True)
    service = LiveKitService()
    with pytest.raises(LiveKitUsageUnqualifiedError, match="model usage budgets"):
        service.issue_participant_token(
            room_name="room", identity="actor", metadata={"workspace_id": "ws"}
        )
    with pytest.raises(LiveKitUsageUnqualifiedError):
        await service.dispatch_agent_sidecar(
            room_name="room",
            session_id="session",
            agent_identity="agent",
            metadata={"workspace_id": "ws"},
            workspace=SimpleNamespace(id="ws"),
        )


async def test_realtime_client_secret_and_webrtc_fail_before_external_send(monkeypatch):
    from app.services.voice_runtime import (
        VoiceProviderNotAllowed,
        create_openai_realtime_call,
        create_openai_realtime_client_secret,
    )

    monkeypatch.setattr(guard, "unqualified_voice_blocked", lambda *a, **kw: True)
    for function, extra in [
        (create_openai_realtime_client_secret, {}),
        (create_openai_realtime_call, {"sdp": "unused"}),
    ]:
        with pytest.raises(VoiceProviderNotAllowed) as exc:
            await function(
                workspace_slug="ws", session={}, workspace=SimpleNamespace(id="ws"), **extra
            )
        assert exc.value.code == "USAGE_TRANSPORT_UNQUALIFIED"
