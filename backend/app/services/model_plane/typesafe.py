"""TypeSafe System One transport: native decisions, without text generation.

Wire contract: https://docs.typesafe.ai/api/system-one and the public OpenAPI
schema, checked 2026-10-22. Credentials are accepted only for the fixed TypeSafe
endpoint. Usage is provider-reported; absent counters remain unknown.
"""

from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

import httpx

API_URL = "https://api.typesafe.ai/v1/systemone"
PINNED_MONETARY_MODELS = frozenset({"jev-1.13.0", "jev-1.14.0"})
MAX_BODY_BYTES = 32 * 1024 * 1024
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}\Z")


class TypeSafeError(ValueError):
    """Safe refusal with observed counters, never provider text or credentials."""

    def __init__(self, code: str, *, usage=None, returned_model=None):
        super().__init__(code)
        self.code = code
        self.usage = _usage(usage)
        self.returned_model = _model(returned_model)


def _model(value):
    return value if isinstance(value, str) and _MODEL.fullmatch(value) else None


def _usage(value):
    value = value if isinstance(value, dict) else {}
    return {
        key: number if type(number := value.get(key)) is int and number >= 0 else None
        for key in ("input_tokens", "output_tokens")
    }


def _json_value(value: Any, depth=0):
    if depth > 64:
        raise TypeSafeError("TYPESAFE_REQUEST_INVALID")
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeSafeError("TYPESAFE_REQUEST_INVALID")
        for child in value.values():
            _json_value(child, depth + 1)
        return
    if isinstance(value, list):
        for child in value:
            _json_value(child, depth + 1)
        return
    raise TypeSafeError("TYPESAFE_REQUEST_INVALID")


def _content(value, *, nullable=True):
    return (nullable and value is None) or isinstance(value, (str, dict, list))


def validate_request(*, model: str, state: Any, questions: dict) -> dict:
    """Validate the supported text-only wire contract before admission or send."""
    if not _model(model) or not _content(state, nullable=False):
        raise TypeSafeError("TYPESAFE_REQUEST_INVALID")
    if not isinstance(questions, dict) or not questions:
        raise TypeSafeError("TYPESAFE_REQUEST_INVALID")
    for name, question in questions.items():
        if not isinstance(name, str) or not name or not isinstance(question, dict):
            raise TypeSafeError("TYPESAFE_REQUEST_INVALID")
        if set(question) - {"type", "instructions", "criteria"}:
            raise TypeSafeError("TYPESAFE_REQUEST_INVALID")
        if not _content(question.get("instructions")):
            raise TypeSafeError("TYPESAFE_REQUEST_INVALID")
        kind, criteria = question.get("type"), question.get("criteria")
        if kind == "noul":
            if criteria is not None and (
                not isinstance(criteria, dict)
                or set(criteria) - {"true", "false"}
                or any(not _content(value) for value in criteria.values())
            ):
                raise TypeSafeError("TYPESAFE_REQUEST_INVALID")
        elif kind == "choice":
            if (
                not isinstance(criteria, dict)
                or not 1 <= len(criteria) <= 255
                or any(not isinstance(key, str) or not key for key in criteria)
                or any(not _content(value) for value in criteria.values())
            ):
                raise TypeSafeError("TYPESAFE_REQUEST_INVALID")
        elif kind == "score":
            if (
                not isinstance(criteria, list)
                or not 1 <= len(criteria) <= 10
                or any(not _content(value, nullable=False) for value in criteria)
            ):
                raise TypeSafeError("TYPESAFE_REQUEST_INVALID")
        else:
            raise TypeSafeError("TYPESAFE_QUESTION_UNSUPPORTED")
    payload = {"model": model, "state": state, "questions": questions}
    for field in (state, questions):
        _json_value(field)
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise TypeSafeError("TYPESAFE_REQUEST_INVALID") from None
    if len(encoded) > MAX_BODY_BYTES:
        raise TypeSafeError("TYPESAFE_REQUEST_TOO_LARGE")
    return copy.deepcopy(payload)


def _number(value, low=0, high=1):
    return type(value) in (int, float) and low <= value <= high and math.isfinite(value)


def normalize_response(payload: Any, *, questions: dict) -> dict:
    """Validate decisions and retain native confidence separately from calibration."""
    payload = payload if isinstance(payload, dict) else {}
    usage = _usage(payload.get("usage"))
    model = _model(payload.get("model"))

    def invalid():
        raise TypeSafeError("TYPESAFE_RESPONSE_INVALID", usage=usage, returned_model=model)

    source = payload.get("answers")
    if model is None or not isinstance(source, dict) or set(source) != set(questions):
        invalid()
    answers = {}
    for name, question in questions.items():
        answer = source[name]
        kind = question["type"]
        if not isinstance(answer, dict) or answer.get("type") != kind:
            invalid()
        if kind == "noul":
            if not _number(answer.get("noul")):
                invalid()
            answers[name] = {"type": kind, "noul": answer["noul"]}
            continue
        criteria = question["criteria"]
        keys = set(criteria) if kind == "choice" else {str(i) for i in range(len(criteria))}
        probabilities = answer.get("probabilities")
        if (
            not _number(answer.get("confidence"))
            or not isinstance(probabilities, dict)
            or set(probabilities) != keys
            or any(not _number(value) for value in probabilities.values())
            # The API promises an approximately normalized distribution.
            or not math.isclose(sum(probabilities.values()), 1, abs_tol=0.01)
        ):
            invalid()
        normalized = {
            "type": kind,
            "confidence": answer["confidence"],
            "probabilities": copy.deepcopy(probabilities),
        }
        if kind == "choice":
            choice = answer.get("choice")
            if (
                not isinstance(choice, str)
                or choice not in keys
                or probabilities[choice] < max(probabilities.values())
            ):
                invalid()
            normalized["choice"] = choice
        elif kind == "score":
            legend = {str(i): value for i, value in enumerate(criteria)}
            if not _number(answer.get("score"), 0, len(criteria) - 1):
                invalid()
            if answer.get("legend") != legend:
                invalid()
            normalized["score"] = answer["score"]
            normalized["legend"] = copy.deepcopy(legend)
        else:
            invalid()
        answers[name] = normalized
    return {
        "model": model,
        "answers": answers,
        "usage": usage,
        "returned_model_reported": True,
    }


async def evaluate(
    *,
    api_key: str,
    model: str,
    state: Any,
    questions: dict,
    timeout_s: float = 60,
    client: httpx.AsyncClient | None = None,
) -> dict:
    """Send one native evaluation; never follow redirects or retry a paid call."""
    payload = validate_request(model=model, state=state, questions=questions)
    if (
        not isinstance(api_key, str)
        or not api_key
        or any(not 33 <= ord(char) <= 126 for char in api_key)
    ):
        raise TypeSafeError("TYPESAFE_CREDENTIAL_REQUIRED")
    if not _number(timeout_s, 0.001, 900):
        raise TypeSafeError("TYPESAFE_TIMEOUT_INVALID")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as owned:
                response = await owned.post(API_URL, json=payload, headers=headers)
        else:
            response = await client.post(
                API_URL,
                json=payload,
                headers=headers,
                timeout=timeout_s,
                follow_redirects=False,
            )
    except httpx.TimeoutException:
        raise TypeSafeError("TYPESAFE_TIMEOUT") from None
    except httpx.HTTPError:
        raise TypeSafeError("TYPESAFE_CONNECTION_FAILED") from None
    if response.status_code != 200:
        # Error bodies can echo submitted state; do not copy them into diagnostics.
        code = {
            401: "TYPESAFE_AUTHENTICATION_FAILED",
            403: "TYPESAFE_ACCESS_DENIED",
            429: "TYPESAFE_RATE_LIMITED",
            529: "TYPESAFE_OVERLOADED",
        }.get(response.status_code, "TYPESAFE_REQUEST_FAILED")
        raise TypeSafeError(code)
    try:
        body = response.json()
    except (ValueError, UnicodeError, RecursionError):
        raise TypeSafeError("TYPESAFE_RESPONSE_INVALID") from None
    result = normalize_response(body, questions=questions)
    if model in PINNED_MONETARY_MODELS and result["model"] != model:
        # A pinned request cannot silently become another model whose tariff
        # and context bounds were not admitted. Keep its counters for the
        # ledger, but do not return the decision as a qualified result.
        raise TypeSafeError(
            "TYPESAFE_RETURNED_MODEL_MISMATCH",
            usage=result["usage"],
            returned_model=result["model"],
        )
    return result
