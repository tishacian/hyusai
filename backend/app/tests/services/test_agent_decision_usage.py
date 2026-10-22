"""Real decision routing and durable admission, with only the OpenAI wire mocked."""

import json
import sys
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.model_usage import ModelUsageCall, UsageBudgetBucket, UsageReservation
from app.services import model_usage as usage
from app.services.model_clients.openai_client import OpenAIClient
from app.services.model_plane.execution import ModelExecution
from app.services.model_usage_transport import usage_scope
from app.services.skills_registry import wrappers
from app.tests.services import test_model_usage

scope = test_model_usage.scope


def setup_decision(s, *, token_limit=100000):
    usage.create_tariff(
        s.db,
        s.workspace,
        s.user,
        provider="openai",
        model="gpt-5",
        currency="USD",
        input_per_million="1.25",
        output_per_million="10",
    )
    test_model_usage.policy(s, tokens=token_limit, amount="1")
    return {
        "workspace_id": s.workspace.id,
        "run_id": s.run.id,
        "user_id": s.user.id,
        "_model_execution": ModelExecution(
            "openai", "gpt-5", "workspace", "workspace", _api_key="mock-only"
        ),
        "_model_policy_check": lambda execution: None,
    }


def decision_payload():
    return {
        "goal": {"objective": "Find the proof in the permitted source"},
        "visible_skills": [{"slug": "semantic_search_v1", "purpose": "Read relevant passages"}],
    }


@pytest.mark.parametrize("finish_reason", ["stop", "length"])
async def test_gpt5_decision_reserves_before_wire_and_never_acts_on_truncated_json(
    scope, monkeypatch, finish_reason
):
    s = scope
    ctx = setup_decision(s)
    requests = []

    async def create(**request):
        requests.append(request)
        assert request["max_completion_tokens"] == 4096 and "max_tokens" not in request
        s.db.expire_all()
        row = s.db.query(ModelUsageCall).one()
        allocation = s.db.query(UsageReservation).one()
        assert row.status == "dispatched" and row.purpose == "agent_decision"
        # The admitted input bound includes the whole prompt plus framing. The
        # reservation exists before provider dispatch and includes output headroom.
        bound = row.reserved_tokens - request["max_completion_tokens"]
        assert bound >= len(request["messages"][0]["content"].encode()) + 4096
        expected = (Decimal(bound) * Decimal("1.25") + Decimal(4096) * 10) / 1000000
        assert row.reserved_amount == expected and allocation.reserved_amount == expected
        return SimpleNamespace(
            id="mock-decision",
            model="gpt-5",
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "next_skill": "semantic_search_v1",
                                "confidence": 0.9,
                                "needs_human": False,
                                "done": False,
                            }
                        )
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=120,
                completion_tokens=80,
                total_tokens=200,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=30),
            ),
        )

    monkeypatch.setattr(
        OpenAIClient,
        "_sdk_client",
        lambda self: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    with usage_scope(replace(s.ctx, purpose="agent_decision"), key=str(uuid4())):
        output = await wrappers._decide_next_v1(decision_payload(), ctx)
    s.db.expire_all()
    row = s.db.query(ModelUsageCall).one()
    bucket = s.db.query(UsageBudgetBucket).one()
    assert len(requests) == 1 and row.total_tokens == 200 and row.reasoning_tokens == 30
    assert row.amount == Decimal("0.00095")
    assert bucket.consumed_tokens == 200 and bucket.reserved_tokens == 0
    assert Decimal(bucket.reserved_amounts["USD"]) == 0
    if finish_reason == "length":
        assert output["next_skill"] is None and output["needs_human"] is True
        assert (
            ctx["_agent_loop_decision_evidence"]["normalization_reasons"][0] == "output_truncated"
        )
    else:
        assert output["next_skill"] == "semantic_search_v1" and output["needs_human"] is False


async def test_decision_budget_refusal_opens_no_provider_or_fallback(scope, monkeypatch):
    s = scope
    ctx = setup_decision(s, token_limit=1)
    ctx["_model_execution"] = replace(
        ctx["_model_execution"],
        _fallbacks=(ModelExecution("openai", "different", "workspace", "workspace"),),
    )

    def forbidden_sdk(self):
        pytest.fail("An exhausted shared budget must not open the provider connection")

    monkeypatch.setattr(OpenAIClient, "_sdk_client", forbidden_sdk)
    with usage_scope(replace(s.ctx, purpose="agent_decision"), key=str(uuid4())):
        output = await wrappers._decide_next_v1(decision_payload(), ctx)
    s.db.expire_all()
    row = s.db.query(ModelUsageCall).one()
    assert row.status == "blocked" and row.diagnostic == "USAGE_BUDGET_EXHAUSTED"
    assert row.dispatched_at is None and s.db.query(UsageReservation).count() == 0
    assert len(ctx["_model_resolution_evidence"]["attempts"]) == 1
    assert output["next_skill"] is None and output["needs_human"] is True
    assert (
        ctx["_agent_loop_decision_evidence"]["normalization_reasons"][0]
        == "usage_admission_refused"
    )


async def test_anthropic_output_limit_also_blocks_a_complete_json_prefix(monkeypatch):
    requests = []

    async def create(**request):
        requests.append(request)
        return SimpleNamespace(
            content=[SimpleNamespace(text='{"next_skill":"semantic_search_v1","confidence":0.9}')],
            model="claude-sonnet",
            stop_reason="max_tokens",
            usage=SimpleNamespace(input_tokens=10, output_tokens=4096),
        )

    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        SimpleNamespace(
            AsyncAnthropic=lambda **options: SimpleNamespace(
                messages=SimpleNamespace(create=create)
            )
        ),
    )
    ctx = {
        "_model_execution": ModelExecution(
            "anthropic", "claude-sonnet", "workspace", "workspace", _api_key="mock-only"
        ),
        "_model_policy_check": lambda execution: None,
    }
    output = await wrappers._decide_next_v1(decision_payload(), ctx)
    assert len(requests) == 1 and requests[0]["max_tokens"] == 4096
    assert output["next_skill"] is None and output["needs_human"] is True
    assert ctx["_agent_loop_decision_evidence"]["normalization_reasons"][0] == "output_truncated"
