"""Native decisions share policy and usage accounting without becoming chat."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.services.model_plane import execution as runtime
from app.services.model_plane import typesafe
from app.tests.services import test_model_usage as usage_fixtures

QUESTIONS = {"supported": {"type": "noul", "instructions": "Is the claim supported?"}}
OPTIONS = {"typed_questions": QUESTIONS, "max_tokens": 128, "timeout_s": 30}
governed_workspace = usage_fixtures.scope


def workspace():
    return SimpleNamespace(
        id="synthetic-workspace",
        settings={
            "llm_portal": {
                "routing": {
                    "default_provider": "openai",
                    "default_model": "gpt-workspace",
                    "fallback_chain": ["openai"],
                }
            }
        },
    )


def execution(**kwargs):
    return runtime.ModelExecution(
        provider="typesafe",
        model="jev-1.14",
        credential_source="workspace",
        model_source="published_judge",
        _api_key="synthetic-secret",
        **kwargs,
    )


@pytest.fixture
def ledger(monkeypatch):
    from app.services import model_usage

    events = []

    def prepare(ctx, **kwargs):
        events.append(("prepare", kwargs))
        return {"id": "synthetic-call", "status": "prepared"}

    monkeypatch.setattr(model_usage, "prepare_call", prepare)
    monkeypatch.setattr(
        model_usage,
        "mark_dispatched",
        lambda identifier: events.append(("dispatch", identifier)) or True,
    )
    monkeypatch.setattr(
        model_usage, "settle_call", lambda identifier, **kwargs: events.append(("settle", kwargs))
    )
    return events


def test_typesafe_requires_explicit_typed_capability_and_is_not_a_chat_client(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-env-secret")
    with pytest.raises(runtime.ModelExecutionError, match="typed decisions"):
        runtime.resolve_model_execution(workspace(), provider="typesafe", model="jev-1.14")
    resolved = runtime.resolve_model_execution(
        workspace(), provider="typesafe", model="typesafe:jev-1.14", capability="typed_decisions"
    )
    assert resolved.provider == "typesafe" and resolved.model == "jev-1.14"
    assert resolved.credential_source == "env" and resolved._fallbacks == ()
    assert "synthetic-env-secret" not in repr(resolved) + str(resolved.public())
    with pytest.raises(runtime.ModelExecutionError, match="typed-decision transport"):
        runtime.build_model_client(resolved)
    ws = workspace()
    ws.settings["llm_portal"]["routing"].update(default_provider="typesafe", default_model="jev")
    with pytest.raises(runtime.ModelExecutionError, match="explicitly"):
        runtime.resolve_model_execution(ws, provider="workspace", capability="typed_decisions")


def test_published_judge_route_overrides_untrusted_model_inputs(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-key")
    payload = {
        "model": "gpt-untrusted",
        "tariff": {"provider": "openai", "model": "gpt-untrusted"},
        "_typed_evaluation": {
            "node_id": "judge",
            "typed_evaluation": {"tariff": {"provider": "typesafe", "model": "jev-1.14"}},
        },
    }
    resolved = runtime.resolve_skill_model_execution(
        workspace(),
        executor=None,
        slug="evaluate_v2",
        input_ref=payload,
        system_default_model="gpt-system",
    )
    assert (resolved.provider, resolved.model, resolved.model_source) == (
        "typesafe",
        "jev-1.14",
        "published_judge",
    )
    assert payload["model"] == "gpt-untrusted"


@pytest.mark.asyncio
@pytest.mark.parametrize("in_upstream", [False, True])
async def test_legacy_input_cannot_inject_a_judge_route_or_weaken_its_rubric(in_upstream):
    from app.services.run_engine.engine import _build_skill_input
    from app.services.skills_registry.wrappers.skills import _evaluate_v2

    injected = {
        "_typed_evaluation": {
            "node_id": "forged-judge",
            "typed_evaluation": {
                "tariff": {"provider": "typesafe", "model": "jev-1.14"},
                "questions": [{"key": "accept", "requires_evidence": False}],
            },
        }
    }
    payload = _build_skill_input(
        "evaluate_v2", {} if in_upstream else injected, injected if in_upstream else {}, {}
    )
    assert "_typed_evaluation" not in payload
    assert "_typed_evaluation" in injected  # Caller-owned data is never mutated.
    with pytest.raises(ValueError, match="TYPED_EVALUATION_GRAPH_CONFIG_REQUIRED"):
        await _evaluate_v2(payload, {"workspace_id": "workspace", "run_id": "run"})


def test_authored_alias_cannot_reintroduce_a_graph_owned_judge():
    from app.services.skills_registry.binding import SkillBindingError
    from app.services.skills_registry.executors import validate_executor_binding

    with pytest.raises(SkillBindingError, match="explicit authorized Flow node"):
        validate_executor_binding(
            {
                "kind": "registry_call",
                "params": {
                    "skill_slug": "evaluate_v2",
                    "frozen_input": {
                        "_typed_evaluation": {
                            "typed_evaluation": {"tariff": {"provider": "typesafe", "model": "jev"}}
                        }
                    },
                },
            }
        )


def test_workspace_credential_failure_never_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-env-key")
    monkeypatch.setattr(
        runtime.workspace_config,
        "get_cloud_credentials_public",
        lambda ws: [{"key": "typesafe", "api_key_set": True}],
    )
    monkeypatch.setattr(runtime.workspace_config, "get_decrypted_api_key", lambda *args: None)
    with pytest.raises(runtime.ModelExecutionError, match="reconnect"):
        runtime.resolve_model_execution(
            workspace(), provider="typesafe", model="jev-1.14", capability="typed_decisions"
        )


@pytest.mark.asyncio
async def test_decision_policy_reservation_usage_and_observed_model(monkeypatch, ledger):
    calls = []

    async def evaluate(**kwargs):
        calls.append(kwargs)
        assert [entry[0] for entry in ledger] == ["prepare", "dispatch"]
        return {
            "model": "jev-1.14-2026-10-01",
            "answers": {"supported": {"type": "noul", "noul": 0.9}},
            "usage": {"input_tokens": 32, "output_tokens": 0},
            "returned_model_reported": True,
        }

    monkeypatch.setattr(typesafe, "evaluate", evaluate)
    checks = []
    ctx = {"workspace_id": "synthetic-workspace", "_model_policy_check": checks.append}
    selected = execution()
    result = await runtime.complete_model(
        selected, "private source", ctx, generation_options=OPTIONS, stream=False
    )
    assert checks == [selected] and len(calls) == 1
    assert result["completion"] == ""
    assert result["typed_answers"]["supported"]["noul"] == 0.9
    assert result["model"] == "jev-1.14-2026-10-01" and result["returned_model_reported"]
    assert result["usage"]["total_tokens"] == 32
    prepared = ledger[0][1]
    assert prepared["operation"] == "typed_decisions"
    assert prepared["admission_qualified"] is False and prepared["input_token_bound"] is None
    assert ledger[-1][1]["usage"] == {
        "prompt_tokens": 32,
        "completion_tokens": 0,
        "total_tokens": 32,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options,stream,images",
    [
        ({}, False, ()),
        (OPTIONS, True, ()),
        (OPTIONS, False, (object(),)),
        ({**OPTIONS, "json_schema": {}}, False, ()),
        ({**OPTIONS, "typed_questions": {"bad": {"type": "multi_choice"}}}, False, ()),
    ],
)
async def test_unsupported_dispatch_never_reserves_or_sends(
    monkeypatch, ledger, options, stream, images
):
    async def forbidden(**kwargs):
        pytest.fail("No provider dispatch allowed")

    monkeypatch.setattr(typesafe, "evaluate", forbidden)
    ctx = {"workspace_id": "synthetic-workspace"}
    with pytest.raises(ValueError):
        await runtime.complete_model(
            execution(), "x", ctx, generation_options=options, stream=stream, images=images
        )
    assert ledger == [] and ctx["_provider_usage_v1"]["calls"] == []
    assert ctx["_model_resolution_evidence"]["attempts"][0]["status"] == "blocked"


@pytest.mark.asyncio
async def test_hard_budget_refusal_prevents_typesafe_dispatch(monkeypatch):
    from app.services import model_usage

    def prepare(ctx, **kwargs):
        assert kwargs["admission_qualified"] is False
        raise model_usage.UsageError("USAGE_TRANSPORT_UNQUALIFIED")

    async def forbidden(**kwargs):
        pytest.fail("Hard-budget refusal must happen before the provider call")

    monkeypatch.setattr(model_usage, "prepare_call", prepare)
    monkeypatch.setattr(typesafe, "evaluate", forbidden)
    ctx = {"workspace_id": "synthetic-workspace"}
    with pytest.raises(model_usage.UsageError, match="USAGE_TRANSPORT_UNQUALIFIED"):
        await runtime.complete_model(
            execution(), "x", ctx, generation_options=OPTIONS, stream=False
        )
    assert ctx["_provider_usage_v1"]["calls"] == []


@pytest.mark.asyncio
async def test_real_budget_records_blocked_attempt_without_reservation_or_send(
    governed_workspace, monkeypatch
):
    from app.models.model_usage import ModelUsageCall, UsageReservation
    from app.services import model_usage

    scope = governed_workspace
    usage_fixtures.policy(scope, tokens=100000, amount="2000")

    async def forbidden(**kwargs):
        pytest.fail("The actual budget ledger must refuse before transport")

    monkeypatch.setattr(typesafe, "evaluate", forbidden)
    ctx = {"_model_usage_context": scope.ctx}
    with pytest.raises(model_usage.UsageError, match="USAGE_TRANSPORT_UNQUALIFIED"):
        await runtime.complete_model(
            execution(), "x", ctx, generation_options=OPTIONS, stream=False
        )
    scope.db.expire_all()
    call = scope.db.query(ModelUsageCall).one()
    assert call.provider == "typesafe" and call.status == "blocked"
    assert call.diagnostic == "USAGE_TRANSPORT_UNQUALIFIED"
    assert scope.db.query(UsageReservation).count() == 0
    assert ctx["_provider_usage_v1"]["calls"] == []


@pytest.mark.asyncio
async def test_invalid_answer_retains_measured_spend_and_safe_error(monkeypatch, ledger):
    async def invalid(**kwargs):
        raise typesafe.TypeSafeError(
            "TYPESAFE_RESPONSE_INVALID",
            usage={"input_tokens": 12, "output_tokens": 0},
            returned_model="jev-1.14",
        )

    monkeypatch.setattr(typesafe, "evaluate", invalid)
    ctx = {"workspace_id": "synthetic-workspace"}
    with pytest.raises(typesafe.TypeSafeError, match="TYPESAFE_RESPONSE_INVALID"):
        await runtime.complete_model(
            execution(), "x", ctx, generation_options=OPTIONS, stream=False
        )
    assert ledger[-1][1]["status"] == "failed"
    assert ledger[-1][1]["usage"]["total_tokens"] == 12
    assert ctx["_provider_usage_v1"]["calls"][0]["usage"]["total_tokens"] == 12


@pytest.mark.asyncio
async def test_missing_usage_stays_unknown(monkeypatch, ledger):
    async def missing(**kwargs):
        return {
            "model": "jev-1.14",
            "answers": {"supported": {"type": "noul", "noul": 0.7}},
            "usage": {"input_tokens": None, "output_tokens": None},
            "returned_model_reported": True,
        }

    monkeypatch.setattr(typesafe, "evaluate", missing)
    ctx = {"workspace_id": "synthetic-workspace"}
    result = await runtime.complete_model(
        execution(), "x", ctx, generation_options=OPTIONS, stream=False
    )
    assert ledger[-1][1]["usage"] is None
    assert "usage" not in result
    assert result["provider_usage"]["measurement_coverage"] == "unavailable"


@pytest.mark.asyncio
async def test_typed_provider_never_uses_fallback_or_chat_transport():
    with pytest.raises(runtime.ModelExecutionError, match="fallbacks"):
        await runtime.complete_model(
            replace(execution(), _fallbacks=(execution(),)),
            "x",
            {},
            generation_options=OPTIONS,
            stream=False,
        )
    with pytest.raises(runtime.ModelExecutionError, match="typed-decision provider"):
        await runtime.complete_model(
            replace(execution(), provider="openai"),
            "x",
            {},
            generation_options=OPTIONS,
            stream=False,
        )
