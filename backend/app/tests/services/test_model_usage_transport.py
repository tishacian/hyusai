"""Transport contracts with synthetic responses and provider-free IPC."""

import json
import subprocess
import sys

import pytest

from app.services import model_usage as ledger
from app.services.model_usage_transport import (
    ProviderCall,
    context_from_execution,
    current_scope,
    response_usage,
    usage_scope,
)


@pytest.fixture
def capture(monkeypatch):
    events = []

    def prepare(context, **kwargs):
        identity = str(len([x for x in events if x[0] == "prepare"]) + 1)
        events.append(("prepare", context, kwargs))
        if kwargs.get("admission_hook"):
            kwargs["admission_hook"]("transaction", {"id": identity})
        return {"id": identity, "status": "prepared"}

    monkeypatch.setattr(ledger, "prepare_call", prepare)
    monkeypatch.setattr(
        ledger, "mark_dispatched", lambda identity: events.append(("dispatch", identity)) or True
    )
    monkeypatch.setattr(
        ledger,
        "settle_call",
        lambda identity, **kwargs: events.append(("settle", identity, kwargs)),
    )
    monkeypatch.setattr(
        ledger, "cancel_before_dispatch", lambda identity: events.append(("cancel", identity))
    )
    return events


def test_reported_cache_reasoning_and_unknown_counters():
    assert response_usage(
        {
            "usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": 5,
                "output_tokens": 6,
            }
        },
        provider="anthropic",
    ) == {
        "prompt_tokens": 45,
        "completion_tokens": 6,
        "total_tokens": 51,
        "cached_tokens": 30,
        "cache_write_tokens": 5,
    }
    assert response_usage(
        {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 7,
                "total_tokens": 17,
                "prompt_tokens_details": {"cached_tokens": 4},
                "completion_tokens_details": {"reasoning_tokens": 6},
            }
        }
    ) == {
        "prompt_tokens": 10,
        "completion_tokens": 7,
        "total_tokens": 17,
        "cached_tokens": 4,
        "reasoning_tokens": 6,
    }
    assert response_usage({"usage": {"total_tokens": 9}}) == {"total_tokens": 9}
    assert response_usage({"usage": {"prompt_tokens": 9, "total_tokens": 9}}, embedding=True) == {
        "prompt_tokens": 9,
        "completion_tokens": 0,
        "total_tokens": 9,
    }
    assert (
        response_usage({"usage": {"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 8}})
        is None
    )
    assert response_usage({"content": "private answer"}) is None


def test_nested_wrappers_and_stream_final_usage_settle_once(capture):
    with usage_scope(ledger.UsageContext(workspace_id="ws"), key="server-call"):
        with ProviderCall(
            "openai", "model", {"prompt": "private"}, output_token_bound=100
        ) as owner:
            with ProviderCall("openai", "model", {}, output_token_bound=100) as nested:
                nested.observe({"usage": {"total_tokens": 999}})
            owner.observe({"usage": {"prompt_tokens": 3, "completion_tokens": 1}})
            owner.observe(
                {
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4},
                    "model": "returned",
                    "id": "request",
                }
            )
    assert [event[0] for event in capture] == ["prepare", "dispatch", "settle"]
    assert capture[0][2]["input_token_bound"] > len("private")
    assert "private" not in json.dumps(capture[0][2])
    assert capture[-1][2]["usage"]["total_tokens"] == 7
    assert capture[-1][2]["returned_model"] == "returned"
    assert capture[-1][2]["provider_request_id"] == "request"
    assert current_scope() is None


def test_interrupt_keeps_unknown_usage_and_safe_diagnostic(capture):
    with pytest.raises(TimeoutError), usage_scope(ledger.UsageContext(workspace_id="ws")):
        with ProviderCall("openai", "model", {}, output_token_bound=10):
            raise TimeoutError("private provider body")
    assert capture[-1][2] == {
        "usage": None,
        "returned_model": None,
        "provider_request_id": None,
        "status": "failed",
        "diagnostic": "TimeoutError",
    }


def test_local_and_global_admission_share_transaction_before_send(capture):
    order = []
    with usage_scope(ledger.UsageContext(workspace_id="ws")):
        with ProviderCall(
            "openai",
            "model",
            {},
            output_token_bound=10,
            admission_hook=lambda db, record: order.append((db, len(capture))),
            after_admission=lambda record: order.append(("committed", len(capture))),
        ):
            pass
    assert order == [("transaction", 1), ("committed", 1)]
    assert [event[0] for event in capture] == ["prepare", "dispatch", "settle"]


def test_admission_refusal_cannot_send_or_settle(capture):
    def refuse(db, record):
        raise ledger.UsageError("JUDGE_BUDGET_EXHAUSTED")

    with usage_scope(ledger.UsageContext(workspace_id="ws")), pytest.raises(ledger.UsageError):
        with ProviderCall("openai", "model", {}, output_token_bound=10, admission_hook=refuse):
            pytest.fail("Provider must not run")
    assert [event[0] for event in capture] == ["prepare"]


def test_durable_cas_prevents_resend(capture, monkeypatch):
    monkeypatch.setattr(ledger, "mark_dispatched", lambda _: False)
    with (
        usage_scope(ledger.UsageContext(workspace_id="ws")),
        pytest.raises(ledger.UsageError, match="RECONCILIATION"),
    ):
        with ProviderCall("openai", "model", {}, output_token_bound=10):
            pytest.fail("Duplicate provider send")
    assert [event[0] for event in capture] == ["prepare"]


def test_schema_type_arrays_are_textual_but_images_and_unbounded_output_unqualified(capture):
    with usage_scope(ledger.UsageContext(workspace_id="ws")):
        for body, bound in [
            ({"schema": {"type": ["object", "null"]}}, 12),
            ({"type": "image_url"}, 12),
            ({}, None),
        ]:
            with ProviderCall("openai", "model", body, output_token_bound=bound):
                pass
    assert [event[2]["admission_qualified"] for event in capture if event[0] == "prepare"] == [
        True,
        False,
        False,
    ]


def test_model_fallbacks_and_successive_calls_have_distinct_keys(capture):
    ctx = {"workspace_id": "ws", "run_id": "run", "_model_usage_evaluation_id": "evaluation"}
    for model in ("first", "fallback", "first"):
        with context_from_execution(ctx):
            with ProviderCall("openai", model, {}, output_token_bound=10):
                pass
    keys = [event[2]["request_key"] for event in capture if event[0] == "prepare"]
    assert len(set(keys)) == 3
    assert all("evaluation" in key for key in keys)


def _synthetic_child(monkeypatch, script):
    original = subprocess.Popen
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda args, **kwargs: original([sys.executable, "-c", script], **kwargs),
    )


def test_giskard_parent_admits_and_settles_each_child_attempt(monkeypatch, capture):
    from app.services.evaluation.giskard_adapter import generate_isolated

    _synthetic_child(
        monkeypatch,
        """import json,sys
payload=json.loads(sys.stdin.readline())
assert "usage_context" not in payload
for n,operation in [(1,"completion"),(2,"embedding")]:
 print("AGENTIUM_USAGE_V1: "+json.dumps({"id":n,"action":"admit","operation":operation,"input_bound":100,"output_bound":10 if n==1 else 0,"sha256":"a"*64,"qualified":True}),flush=True)
 assert json.loads(sys.stdin.readline())["ok"]
 print("AGENTIUM_USAGE_V1: "+json.dumps({"id":n,"action":"settle","usage":{"prompt_tokens":3,"completion_tokens":2 if n==1 else 0,"total_tokens":5 if n==1 else 3},"model":"returned","request_id":str(n)}),flush=True)
 assert json.loads(sys.stdin.readline())["ok"]
print('AGENTIUM_RAGET_V1: {"cases":[]}')
""",
    )
    result = generate_isolated(
        rows=[],
        model="openai/gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        api_key="fixture-secret",
        num_questions=1,
        language="fr",
        usage_context={"workspace_id": "ws", "job_id": "job", "request_key": "job:candidate:2"},
    )
    assert result["cases"] == []
    prepared = [event for event in capture if event[0] == "prepare"]
    assert [event[1].purpose for event in prepared] == ["test_generation", "embedding"]
    assert all(event[1].traffic == "evaluation" for event in prepared)
    assert [event[2]["request_key"] for event in prepared] == [
        "giskard:job:candidate:2:1",
        "giskard:job:candidate:2:2",
    ]
    assert [event[0] for event in capture] == [
        "prepare",
        "dispatch",
        "settle",
        "prepare",
        "dispatch",
        "settle",
    ]
    assert "fixture-secret" not in str(capture)


def test_giskard_child_crash_retains_unknown_attempt(monkeypatch, capture):
    from app.services.evaluation.giskard_adapter import GiskardUnavailable, generate_isolated

    _synthetic_child(
        monkeypatch,
        """import json,sys
json.loads(sys.stdin.readline())
print('AGENTIUM_USAGE_V1: {"id":1,"action":"admit","operation":"completion","input_bound":100,"output_bound":10,"qualified":true}',flush=True)
assert json.loads(sys.stdin.readline())["ok"]
sys.exit(1)
""",
    )
    with pytest.raises(GiskardUnavailable):
        generate_isolated(
            rows=[],
            model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            api_key="fixture",
            num_questions=1,
            language="fr",
            usage_context={"workspace_id": "ws", "job_id": "job"},
        )
    assert capture[-1][0] == "settle"
    assert capture[-1][2]["usage"] is None
    assert capture[-1][2]["diagnostic"] == "GiskardWorkerInterrupted"


async def test_direct_openai_client_disables_sdk_retries_and_captures_final_counters(
    capture, monkeypatch
):
    from types import SimpleNamespace

    from app.services.model_clients.openai_client import OpenAIClient

    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            id="sdk-id",
            model="model",
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="answer"), finish_reason="stop")
            ],
            usage=SimpleNamespace(
                prompt_tokens=5,
                completion_tokens=2,
                total_tokens=7,
                prompt_tokens_details=SimpleNamespace(cached_tokens=3),
            ),
        )

    def sdk(**kwargs):
        assert kwargs["max_retries"] == 0
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr("openai.AsyncOpenAI", sdk)
    with usage_scope(ledger.UsageContext(workspace_id="ws")):
        await OpenAIClient(api_key="fixture", max_retries=9).generate(
            "model", "prompt", max_tokens=12
        )
    assert len(calls) == 1
    assert [event[0] for event in capture] == ["prepare", "dispatch", "settle"]
    assert capture[-1][2]["usage"]["cached_tokens"] == 3
    assert capture[-1][2]["provider_request_id"] == "sdk-id"


async def test_anthropic_stream_combines_start_and_final_usage_once(capture, monkeypatch):
    from types import SimpleNamespace as N

    from app.services.model_clients.anthropic_client import AnthropicClient

    async def events():
        yield N(
            type="message_start",
            message=N(
                model="returned",
                usage=N(input_tokens=5, output_tokens=1, cache_read_input_tokens=10),
            ),
        )
        yield N(type="content_block_delta", delta=N(text="answer"))
        yield N(type="message_delta", usage=N(output_tokens=4))
        yield N(type="message_stop")

    async def create(**kwargs):
        return events()

    def sdk(**kwargs):
        assert kwargs["max_retries"] == 0
        return N(messages=N(create=create))

    monkeypatch.setitem(sys.modules, "anthropic", N(AsyncAnthropic=sdk))
    with usage_scope(ledger.UsageContext(workspace_id="ws")):
        chunks = [
            chunk
            async for chunk in AnthropicClient(api_key="fixture").stream(
                "model", "prompt", max_tokens=12
            )
        ]
    assert [c["content"] for c in chunks if c.get("content")] == ["answer"]
    assert capture[-1][2]["usage"] == {
        "prompt_tokens": 15,
        "completion_tokens": 4,
        "total_tokens": 19,
        "cached_tokens": 10,
    }
    assert [event[0] for event in capture] == ["prepare", "dispatch", "settle"]


def test_giskard_budget_refusal_precedes_child_provider_send(monkeypatch, capture):
    from app.services.evaluation.giskard_adapter import GiskardUnavailable, generate_isolated

    def refuse(*args, **kwargs):
        raise ledger.UsageError("USAGE_BUDGET_EXHAUSTED")

    monkeypatch.setattr(ledger, "prepare_call", refuse)
    _synthetic_child(
        monkeypatch,
        """import json,sys
json.loads(sys.stdin.readline())
print('AGENTIUM_USAGE_V1: {"id":1,"action":"admit","operation":"completion","input_bound":100,"output_bound":10,"qualified":true}',flush=True)
ack=json.loads(sys.stdin.readline())
assert ack == {"id":1,"ok":False,"code":"USAGE_BUDGET_EXHAUSTED"}
sys.exit(1)
""",
    )
    with pytest.raises(GiskardUnavailable):
        generate_isolated(
            rows=[],
            model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            api_key="fixture",
            num_questions=1,
            language="fr",
            usage_context={"workspace_id": "ws", "job_id": "job"},
        )
    assert capture == []


async def test_parallel_judge_scopes_share_attempt_sequence_without_cross_attribution(capture):
    import asyncio

    async def unit(identity):
        with context_from_execution(
            {"_model_usage_evaluation_id": identity, "_model_usage_purpose": "judge"}
        ):
            await asyncio.sleep(0)
            with ProviderCall("openai", "model", {}, output_token_bound=10):
                pass

    with usage_scope(ledger.UsageContext(workspace_id="ws", run_id="run"), key="invocation"):
        await asyncio.gather(unit("eval-a"), unit("eval-b"))
    prepared = [event for event in capture if event[0] == "prepare"]
    assert len(set(event[2]["request_key"] for event in prepared)) == 2
    assert {event[1].evaluation_id for event in prepared} == {"eval-a", "eval-b"}
