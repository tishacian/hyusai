"""Unit tests for the ``decision`` mini DSL (run_engine.condition)."""
from __future__ import annotations

import pytest

from app.services.run_engine.condition import ConditionError, evaluate


def test_empty_and_none_are_truthy() -> None:
    assert evaluate("", {}) is True
    assert evaluate("   ", {"foo": 1}) is True
    assert evaluate(None, {}) is True  # type: ignore[arg-type]


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


def test_missing_key_yields_none_and_comparisons_raise_type_error() -> None:
    # Missing key resolves to None; comparisons with None < number raise
    # TypeError in Python 3 — the condition module surfaces that as a
    # ConditionError from the caller's perspective, but we keep the walker
    # behaviour clean by catching it upstream (see _run_decision).
    with pytest.raises(TypeError):
        evaluate("missing_key > 0.5", {})


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
    with pytest.raises(ConditionError):
        evaluate("status ==", {"status": "ok"})
