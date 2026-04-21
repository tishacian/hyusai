"""Mini DSL for ``decision`` node predicates.

Built on ``ast.parse`` with a strict whitelist walker — never ``eval``.

Supported grammar
-----------------
* Boolean ops: ``and``, ``or``, ``not``
* Comparisons: ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``, ``in``, ``not in``
* Literals: numbers, quoted strings, ``True`` / ``False`` / ``None``, lists,
  tuples (parsed as lists).
* References:
    - Top-level ctx keys as bare names (``answer``, ``confidence``, ...).
    - Dotted path starting with ``ctx.`` (``ctx.confidence``) for disambiguation.
* Parentheses for grouping.

Anything else — function calls, attribute chains beyond a single ``ctx.key``,
subscripting, lambdas, comprehensions, imports — raises :class:`ConditionError`.

Examples
--------
>>> evaluate("confidence > 0.8", {"confidence": 0.92})
True
>>> evaluate("answer == 'approved' and not failed", {"answer": "approved", "failed": False})
True
>>> evaluate("status in ['ok', 'partial']", {"status": "partial"})
True
"""
from __future__ import annotations

import ast
from typing import Any, Dict


class ConditionError(ValueError):
    """Raised when a condition expression is invalid or unsafe."""


_ALLOWED_BOOL_OPS = (ast.And, ast.Or)
_ALLOWED_CMP_OPS = (
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
)
_ALLOWED_UNARY_OPS = (ast.Not, ast.USub, ast.UAdd)


def evaluate(expression: str, ctx: Dict[str, Any]) -> bool:
    """Safely evaluate ``expression`` against ``ctx``.

    Returns a boolean. Empty / whitespace-only expressions evaluate to
    ``True`` (conventionally "no guard, fall through").
    """
    if expression is None:
        return True
    text = str(expression).strip()
    if not text:
        return True
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"invalid condition syntax: {exc.msg}") from exc
    value = _walk(tree.body, ctx)
    return bool(value)


def _walk(node: ast.AST, ctx: Dict[str, Any]) -> Any:
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, _ALLOWED_BOOL_OPS):
            raise ConditionError(f"unsupported boolean op {type(node.op).__name__}")
        values = [_walk(v, ctx) for v in node.values]
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in values:
                result = v
                if not v:
                    return False
            return result
        last: Any = False
        for v in values:
            last = v
            if v:
                return v
        return last

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARY_OPS):
            raise ConditionError(f"unsupported unary op {type(node.op).__name__}")
        operand = _walk(node.operand, ctx)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        return +operand

    if isinstance(node, ast.Compare):
        left = _walk(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, _ALLOWED_CMP_OPS):
                raise ConditionError(f"unsupported comparison {type(op).__name__}")
            right = _walk(comparator, ctx)
            if not _cmp(op, left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        raise ConditionError(f"unsupported literal of type {type(node.value).__name__}")

    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_walk(e, ctx) for e in node.elts]

    if isinstance(node, ast.Name):
        return _lookup(ctx, node.id)

    if isinstance(node, ast.Attribute):
        # Only ``ctx.<key>`` — no deeper attribute chains.
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in ("ctx", "context")
            and isinstance(node.attr, str)
        ):
            return _lookup(ctx, node.attr)
        raise ConditionError(
            "only top-level ctx.<key> attribute access is allowed"
        )

    raise ConditionError(f"unsupported expression node {type(node).__name__}")


def _cmp(op: ast.cmpop, left: Any, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    if isinstance(op, ast.Lt):
        return left < right
    if isinstance(op, ast.LtE):
        return left <= right
    if isinstance(op, ast.Gt):
        return left > right
    if isinstance(op, ast.GtE):
        return left >= right
    if isinstance(op, ast.In):
        return left in (right or [])
    if isinstance(op, ast.NotIn):
        return left not in (right or [])
    raise ConditionError(f"unsupported comparison {type(op).__name__}")


def _lookup(ctx: Dict[str, Any], name: str) -> Any:
    """Look up ``name`` in the ctx, then fall back to the nested ``input``.

    Returning ``None`` on miss is intentional — comparisons like
    ``score > 0.8`` against a missing key should cleanly yield False after
    the type-error boundary below.
    """
    if not isinstance(ctx, dict):
        return None
    if name in ctx:
        return ctx[name]
    inner = ctx.get("input")
    if isinstance(inner, dict) and name in inner:
        return inner[name]
    return None
