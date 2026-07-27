from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_startup_reconciliation_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError, match="startup_reconciliation"):
        Settings(_env_file=None, startup_reconciliation="best_effort")


class _ReadOnlyQuery:
    def filter(self, *_args: Any, **_kwargs: Any) -> _ReadOnlyQuery:
        return self

    def order_by(self, *_args: Any, **_kwargs: Any) -> _ReadOnlyQuery:
        return self

    def first(self) -> None:
        return None

    def all(self) -> list:
        return []


class _ReadOnlySession:
    def __init__(self) -> None:
        self.closed = False

    def query(self, *_args: Any, **_kwargs: Any) -> _ReadOnlyQuery:
        return _ReadOnlyQuery()

    def add(self, *_args: Any, **_kwargs: Any) -> None:
        pytest.fail("read-only settings initialization must not add a row")

    def commit(self) -> None:
        pytest.fail("read-only settings initialization must not commit")

    def refresh(self, *_args: Any, **_kwargs: Any) -> None:
        pytest.fail("read-only settings initialization must not refresh a new row")

    def close(self) -> None:
        self.closed = True


def test_settings_manager_read_only_does_not_create_missing_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import settings_manager as settings_manager_module

    session = _ReadOnlySession()
    monkeypatch.setattr(settings_manager_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(settings_manager_module.SettingsManager, "_instance", None)
    monkeypatch.setattr(settings_manager_module.SettingsManager, "_initialized", False)
    monkeypatch.setattr(settings_manager_module.SettingsManager, "_settings", {})

    manager = settings_manager_module.SettingsManager(create_if_missing=False)

    assert session.closed is True
    assert manager.get("defaultModel") == settings_manager_module.app_config.default_model


def test_preset_resolution_without_a_preset_is_pure_after_legacy_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import settings_manager as settings_manager_module
    from app.services.rag_preset_service import RagPresetService

    monkeypatch.setattr(
        settings_manager_module,
        "get_settings_manager",
        lambda **_kwargs: pytest.fail(
            "read-only preset fallback must not reuse the legacy singleton"
        ),
    )
    monkeypatch.setattr(
        settings_manager_module.SettingsManager,
        "_instance",
        SimpleNamespace(_create_if_missing=True),
    )

    resolved = RagPresetService.resolve_for(
        _ReadOnlySession(),
        workspace_id="workspace-without-preset",
    )

    assert resolved["defaultModel"] == settings_manager_module.app_config.default_model


class _FakeAgent:
    async def initialize(self) -> None:
        return None

    async def cleanup(self) -> None:
        return None


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.agents: dict[str, _FakeAgent] = {}

    def register_agent(self, agent: _FakeAgent) -> None:
        self.agents["test"] = agent


def _record_forbidden_call(calls: list[str], name: str) -> Callable[..., None]:
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        calls.append(name)

    return forbidden


@pytest.mark.asyncio
async def test_disabled_startup_does_not_reconcile_or_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main
    from app.services import mission_room, skills_registry
    from app.services.systems import bootstrap

    forbidden_calls: list[str] = []
    settings_manager_modes: list[bool] = []

    monkeypatch.setattr(main.settings, "startup_reconciliation", "disabled")
    monkeypatch.setattr(main.settings, "rag_cross_encoder_enabled", False)
    monkeypatch.setattr(main.settings, "intelligence_scheduler_enabled", True)
    monkeypatch.setattr(
        main.Base.metadata,
        "create_all",
        _record_forbidden_call(forbidden_calls, "Base.metadata.create_all"),
    )

    async def forbidden_knowledge_seed() -> None:
        forbidden_calls.append("seed_knowledge_base")

    monkeypatch.setattr(main, "seed_knowledge_base", forbidden_knowledge_seed)
    monkeypatch.setattr(
        skills_registry,
        "seed_skills_and_capabilities",
        _record_forbidden_call(forbidden_calls, "seed_skills_and_capabilities"),
    )
    for name in (
        "ensure_client360_pdr_system_for_all_workspaces",
        "ensure_expert_capture_system_for_all_workspaces",
        "ensure_fse_report_system_for_andritz",
        "ensure_intelligence_system_for_all_workspaces",
        "ensure_workspace_chat_system_for_all_workspaces",
    ):
        monkeypatch.setattr(
            bootstrap,
            name,
            _record_forbidden_call(forbidden_calls, name),
        )
    monkeypatch.setattr(
        mission_room,
        "ensure_sentinel_ci_workspace",
        _record_forbidden_call(forbidden_calls, "ensure_sentinel_ci_workspace"),
    )

    def settings_manager_probe(*, create_if_missing: bool = True) -> object:
        settings_manager_modes.append(create_if_missing)
        return object()

    monkeypatch.setattr(main, "get_settings_manager", settings_manager_probe)
    monkeypatch.setattr(main, "AgentOrchestrator", _FakeOrchestrator)
    monkeypatch.setattr(main, "OmniRAGAgent", _FakeAgent)
    monkeypatch.setattr(main, "set_orchestrator", lambda _orchestrator: None)

    async with main.lifespan(main.app):
        pass

    assert settings_manager_modes == [False]
    assert forbidden_calls == []


@pytest.mark.asyncio
async def test_settings_get_resolves_without_creating_a_workspace_preset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import settings as endpoint

    workspace = SimpleNamespace(id="workspace-id")
    database = object()
    calls: list[tuple[object, str | None]] = []

    def resolve(db: object, *, workspace_id: str | None = None, **_kwargs: Any) -> dict[str, Any]:
        calls.append((db, workspace_id))
        return {"defaultModel": "read-only-model"}

    def forbidden_create(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("GET /settings must not create a workspace preset")

    monkeypatch.setattr(endpoint.RagPresetService, "resolve_for", resolve)
    monkeypatch.setattr(
        endpoint.RagPresetService,
        "get_or_create_workspace_default",
        forbidden_create,
    )

    response = await endpoint.get_settings(workspace=workspace, db=database)

    assert response.settings == {"defaultModel": "read-only-model"}
    assert calls == [(database, "workspace-id")]


@pytest.mark.asyncio
async def test_settings_get_legacy_fallback_never_creates_app_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1.endpoints import settings as endpoint

    def unavailable(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("preset unavailable")

    observed: list[bool] = []

    def legacy_read(
        _db: object,
        _ignore_missing_columns: bool = False,
        *,
        create_if_missing: bool = True,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        observed.append(create_if_missing)
        return {"temperature": 0.2}

    monkeypatch.setattr(endpoint.RagPresetService, "resolve_for", unavailable)
    monkeypatch.setattr(endpoint.SettingsService, "get_settings", legacy_read)
    monkeypatch.setattr(endpoint, "get_app_settings", lambda: {"defaultModel": "fallback"})

    response = await endpoint.get_settings(
        workspace=SimpleNamespace(id="workspace-id"),
        db=object(),
    )

    assert response.settings == {"defaultModel": "fallback", "temperature": 0.2}
    assert observed == [False]
