"""Unit tests for the ``decision`` mini DSL (run_engine.condition)."""
from __future__ import annotations

import pytest

from app.services.run_engine.condition import ConditionError, evaluate, validate


@pytest.mark.parametrize("expression", ["", "   ", None])
def test_empty_and_none_are_invalid(expression: str | None) -> None:
    with pytest.raises(ConditionError) as captured:
        evaluate(expression, {})  # type: ignore[arg-type]
    assert captured.value.code == "condition_empty"


def test_comparison_bare_name() -> None:
    ctx = {"confidence": 0.92}
    assert evaluate("confidence > 0.8", ctx) is True
    assert evaluate("confidence < 0.5", ctx) is False
    assert evaluate("confidence == 0.92", ctx) is True


def test_ctx_attribute_access() -> None:
    ctx = {"confidence": 0.3}
    assert evaluate("ctx.confidence < 0.5", ctx) is True
    assert evaluate("ctx.confidence >= 0.5", ctx) is False


def test_boolean_combinations() -> None:
    ctx = {"approved": True, "score": 0.9}
    assert evaluate("approved and score > 0.8", ctx) is True
    assert evaluate("approved and score > 0.95", ctx) is False
    assert evaluate("not approved or score > 0.8", ctx) is True


def test_in_operator_with_list_literal() -> None:
    ctx = {"status": "partial"}
    assert evaluate("status in ['ok', 'partial']", ctx) is True
    assert evaluate("status not in ['ok']", ctx) is True
    assert evaluate("status in ['ok']", ctx) is False


def test_fallback_to_input_bag() -> None:
    ctx = {"input": {"query": "hello"}}
    assert evaluate("query == 'hello'", ctx) is True


def test_missing_key_comparison_raises_structured_condition_error() -> None:
    with pytest.raises(ConditionError) as captured:
        evaluate("missing_key > 0.5", {})
    assert captured.value.code == "condition_evaluation_error"
    assert captured.value.to_dict() == {
        "code": "condition_evaluation_error",
        "message": "condition evaluation failed: TypeError",
    }


def test_boolean_ops_short_circuit_runtime_evaluation() -> None:
    assert evaluate("False and missing_key > 0.5", {}) is False
    assert evaluate("True or missing_key > 0.5", {}) is True


def test_static_validation_checks_a_short_circuited_unsafe_operand() -> None:
    with pytest.raises(ConditionError) as captured:
        evaluate("False and len(answer) > 0", {"answer": "secret"})
    assert captured.value.code == "condition_unsupported"


def test_validate_checks_without_reading_runtime_values() -> None:
    assert validate("approved and score > 0.8") is None
    with pytest.raises(ConditionError) as captured:
        validate("approved and ctx.payload.value == 1")
    assert captured.value.code == "condition_unsupported"


def test_rejects_function_calls() -> None:
    with pytest.raises(ConditionError):
        evaluate("len(answer) > 0", {"answer": "x"})


def test_rejects_attribute_chain() -> None:
    with pytest.raises(ConditionError):
        evaluate("ctx.foo.bar == 1", {"foo": {"bar": 1}})


def test_rejects_imports_and_unsafe_literals() -> None:
    with pytest.raises(ConditionError):
        evaluate("__import__('os')", {})
    with pytest.raises(ConditionError):
        evaluate("a + b", {"a": 1, "b": 2})  # arithmetic ops not allowed


def test_invalid_syntax_raises_condition_error() -> None:
    with pytest.raises(ConditionError) as captured:
        evaluate("status ==", {"status": "ok"})
    assert captured.value.code == "condition_syntax_error"
