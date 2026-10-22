"""Native Jev wire compatibility, accounting truth and secret-safe failures."""

import copy
import json

import httpx
import pytest

from app.services.model_plane import typesafe

QUESTIONS = {
    "policy": {"type": "noul", "instructions": "Does the proposal follow the policy?"},
    "route": {
        "type": "choice",
        "instructions": "Which review is needed?",
        "criteria": {"sav": "Customer service review", "finance": "Finance review"},
    },
    "urgency": {
        "type": "score",
        "instructions": "How urgent is the case?",
        "criteria": ["Can wait", "This week", "Today"],
    },
}
RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "policy": {"type": "noul", "noul": 0.91},
        "route": {
            "type": "choice",
            "choice": "sav",
            "confidence": 0.71,
            "probabilities": {"sav": 0.8, "finance": 0.2},
        },
        "urgency": {
            "type": "score",
            "score": 1.7,
            "confidence": 0.55,
            "legend": {"0": "Can wait", "1": "This week", "2": "Today"},
            "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8},
        },
    },
    "usage": {"input_tokens": 120, "output_tokens": 12},
}


@pytest.mark.asyncio
async def test_native_request_and_alias_preserve_reported_model_and_counters():
    requests = []

    def handle(request):
        requests.append(request)
        assert str(request.url) == typesafe.API_URL
        assert request.headers["authorization"] == "Bearer synthetic-key"
        assert json.loads(request.content) == {
            "model": "jev-latest",
            "state": {"case": "synthetic case"},
            "questions": QUESTIONS,
        }
        return httpx.Response(200, json=RESPONSE)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await typesafe.evaluate(
            api_key="synthetic-key",
            model="jev-latest",
            state={"case": "synthetic case"},
            questions=QUESTIONS,
            client=client,
        )
    assert len(requests) == 1
    assert result["model"] == "jev-1.13.0"
    assert result["returned_model_reported"] is True
    assert result["usage"] == RESPONSE["usage"]
    assert result["answers"] == RESPONSE["answers"]
    assert "completion" not in result and "confidence" not in result
    assert all(
        "explanation" not in answer and "evidence" not in answer
        for answer in result["answers"].values()
    )


@pytest.mark.parametrize(
    "usage", [None, {}, {"input_tokens": None}, {"input_tokens": -1, "output_tokens": True}]
)
def test_missing_or_invalid_counters_remain_unknown(usage):
    response = {**RESPONSE, "usage": usage}
    result = typesafe.normalize_response(response, questions=QUESTIONS)
    assert result["usage"] == {"input_tokens": None, "output_tokens": None}


def test_partial_usage_is_preserved_without_manufactured_zero():
    response = {**RESPONSE, "usage": {"input_tokens": 120}}
    assert typesafe.normalize_response(response, questions=QUESTIONS)["usage"] == {
        "input_tokens": 120,
        "output_tokens": None,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.pop("model"),
        lambda r: r["answers"].pop("policy"),
        lambda r: r["answers"].update(extra={"type": "noul", "noul": 1}),
        lambda r: r["answers"]["policy"].update(type="choice"),
        lambda r: r["answers"]["policy"].update(noul=True),
        lambda r: r["answers"]["policy"].update(noul=float("nan")),
        lambda r: r["answers"]["policy"].update(noul=10**1000),
        lambda r: r["answers"]["route"].update(choice="other"),
        lambda r: r["answers"]["route"].update(choice="finance"),
        lambda r: r["answers"]["route"].update(confidence=1.1),
        lambda r: r["answers"]["route"]["probabilities"].update(finance=0.8),
        lambda r: r["answers"]["route"]["probabilities"].pop("finance"),
        lambda r: r["answers"]["urgency"].update(score=3),
        lambda r: r["answers"]["urgency"]["legend"].update({"2": "Changed criteria"}),
    ],
)
def test_invalid_decisions_keep_measured_usage_for_settlement(mutation):
    response = copy.deepcopy(RESPONSE)
    mutation(response)
    with pytest.raises(typesafe.TypeSafeError, match="TYPESAFE_RESPONSE_INVALID") as caught:
        typesafe.normalize_response(response, questions=QUESTIONS)
    assert caught.value.usage == RESPONSE["usage"]
    assert str(caught.value) == "TYPESAFE_RESPONSE_INVALID"


@pytest.mark.parametrize(
    "questions",
    [
        {},
        {"q": {"type": "box", "instructions": "Locate something"}},
        {"q": {"type": "multi_choice", "criteria": ["a", "b"]}},
        {"q": {"type": "choice", "criteria": {}}},
        {"q": {"type": "choice", "criteria": {str(i): "x" for i in range(256)}}},
        {"q": {"type": "score", "criteria": ["x"] * 11}},
        {"q": {"type": "score", "criteria": {"0": "x"}}},
        {"q": {"type": "noul", "criteria": {"other": "x"}}},
        {"q": {"type": "noul", "assets": {"url": "https://example.org"}}},
    ],
)
def test_unsupported_or_malformed_question_refused_before_send(questions):
    with pytest.raises(typesafe.TypeSafeError):
        typesafe.validate_request(model="jev-latest", state="case", questions=questions)


def test_request_has_finite_json_content_and_bounded_size(monkeypatch):
    with pytest.raises(typesafe.TypeSafeError, match="TYPESAFE_REQUEST_INVALID"):
        typesafe.validate_request(
            model="jev-latest", state={"x": float("inf")}, questions=QUESTIONS
        )
    with pytest.raises(typesafe.TypeSafeError, match="TYPESAFE_REQUEST_INVALID"):
        typesafe.validate_request(model="jev-latest", state={1: "bad key"}, questions=QUESTIONS)
    monkeypatch.setattr(typesafe, "MAX_BODY_BYTES", 10)
    with pytest.raises(typesafe.TypeSafeError, match="TYPESAFE_REQUEST_TOO_LARGE"):
        typesafe.validate_request(model="jev-latest", state="case", questions=QUESTIONS)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 422, 429, 500, 529])
async def test_no_redirect_retry_or_provider_error_body_leak(status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"location": "https://other.invalid/collect"},
            json={"detail": "private case and synthetic-key must not escape"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=True
    ) as client:
        with pytest.raises(typesafe.TypeSafeError) as caught:
            await typesafe.evaluate(
                api_key="synthetic-key",
                model="jev-latest",
                state="private case",
                questions=QUESTIONS,
                client=client,
            )
    assert len(calls) == 1
    assert "private" not in str(caught.value) and "synthetic-key" not in str(caught.value)
    assert caught.value.usage == {"input_tokens": None, "output_tokens": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("exception", [httpx.ReadTimeout, httpx.ConnectError])
async def test_transport_errors_are_safe_and_not_retried(exception):
    calls = []

    def handle(request):
        calls.append(request)
        raise exception("private state and synthetic-key", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(typesafe.TypeSafeError) as caught:
            await typesafe.evaluate(
                api_key="synthetic-key",
                model="jev-latest",
                state="private state",
                questions=QUESTIONS,
                client=client,
            )
    assert len(calls) == 1
    assert "synthetic-key" not in str(caught.value) and "private" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_malformed_json_does_not_echo_response():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="private-state"))
    ) as client:
        with pytest.raises(typesafe.TypeSafeError, match="TYPESAFE_RESPONSE_INVALID"):
            await typesafe.evaluate(
                api_key="synthetic-key",
                model="jev-latest",
                state="case",
                questions=QUESTIONS,
                client=client,
            )
