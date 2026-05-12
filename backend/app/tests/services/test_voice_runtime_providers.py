from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.capability import Capability
from app.models.skill import Skill
from app.services.skills_registry.seed import seed_skills_and_capabilities
from app.services.skills_registry.wrappers import runtime_status
from app.services.voice_runtime import (
    CascadeVoiceRuntime,
    OpenAIRealtimeVoiceRuntime,
    VoiceProviderCapabilityUnsupported,
    VoiceProviderNotAllowed,
    get_voice_runtime_provider,
    list_voice_runtime_providers,
    resolve_voice_runtime_slug,
)


def test_voice_provider_resolution_priority_and_aliases(monkeypatch):
    monkeypatch.setattr(settings, "voice_runtime_allowed_providers", "cascade_openai,local_stt")
    monkeypatch.setattr(settings, "voice_runtime_default_provider", "cascade_openai")

    workspace_settings = {"voice_runtime": {"default_provider": "local_stt"}}

    assert resolve_voice_runtime_slug("cascade", workspace_settings=workspace_settings) == "cascade_openai"
    assert resolve_voice_runtime_slug(None, workspace_settings=workspace_settings) == "local_stt"
    assert (
        resolve_voice_runtime_slug(
            None,
            workspace_settings=workspace_settings,
            system_voice={"provider": "cascade"},
            node_config={"provider": "local_stt"},
        )
        == "local_stt"
    )

    with pytest.raises(VoiceProviderNotAllowed):
        resolve_voice_runtime_slug("openai_realtime", workspace_settings=workspace_settings)


def test_voice_provider_catalog_exposes_capabilities(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    workspace = SimpleNamespace(
        slug="andritz",
        settings={
            "voice_runtime": {
                "allowed_providers": ["cascade", "openai_realtime"],
                "default_provider": "cascade",
                "fallback_providers": ["cascade"],
            }
        },
    )

    catalog = list_voice_runtime_providers(workspace=workspace)
    providers = {item["slug"]: item for item in catalog["providers"]}

    assert catalog["default_provider"] == "cascade_openai"
    assert providers["cascade_openai"]["capabilities"]["batch_transcription"] is True
    assert providers["cascade_openai"]["capabilities"]["speech_to_speech"] is False
    assert providers["openai_realtime"]["capabilities"]["speech_to_speech"] is True
    assert "runtime.metric" in catalog["events"]


@pytest.mark.asyncio
async def test_unsupported_capability_is_clean(monkeypatch):
    monkeypatch.setattr(settings, "voice_runtime_allowed_providers", "local_stt")
    provider = get_voice_runtime_provider("local_stt")

    with pytest.raises(VoiceProviderCapabilityUnsupported) as exc:
        await provider.create_speech("hello")

    assert exc.value.code == "provider_capability_unsupported"


@pytest.mark.asyncio
async def test_openai_realtime_batch_calls_fallback_to_cascade(monkeypatch):
    async def fake_transcribe(self, *args, **kwargs):
        return {"text": "hello", "transcript": "hello", "model": "fake-stt", "provider": self.slug}

    monkeypatch.setattr(CascadeVoiceRuntime, "transcribe", fake_transcribe)

    result = await OpenAIRealtimeVoiceRuntime().transcribe(b"audio")

    assert result["provider"] == "cascade_openai"
    assert result["requested_provider"] == "openai_realtime"
    assert result["fallback"] is True


def test_voice_skills_and_capability_seed_are_idempotent(db_session):
    seed_skills_and_capabilities(db_session)
    seed_skills_and_capabilities(db_session)

    assert runtime_status("voice_realtime_session_v1") == "bound"
    assert runtime_status("voice_realtime_transcribe_v1") == "bound"
    assert runtime_status("voice_realtime_speak_v1") == "bound"
    assert runtime_status("voice_realtime_translate_v1") == "bound"
    assert runtime_status("voice_oracle_turn_v1") == "bound"

    skills_by_id = {skill.id: skill.slug for skill in db_session.query(Skill).all()}
    voice_capability = db_session.query(Capability).filter(Capability.slug == "voice2voice_interaction").one()
    expert_capability = db_session.query(Capability).filter(Capability.slug == "expert_knowledge_capture").one()

    assert "voice_realtime_session_v1" in [skills_by_id[item] for item in voice_capability.skill_ids]
    assert "voice_oracle_turn_v1" in [skills_by_id[item] for item in expert_capability.skill_ids]
