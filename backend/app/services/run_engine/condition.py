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
from typing import Any, Dict, NoReturn, Optional, Set


class ConditionError(ValueError):
    """Raised when a condition expression is invalid, unsafe or cannot run.

    ``code`` is intentionally stable so validators and runtime checkpoints can
    expose a machine-readable reason without leaking condition inputs.  The
    human-readable ``message`` remains the exception string for backwards
    compatibility with existing logs.
    """

    def __init__(self, message: str, *, code: str = "condition_invalid") -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message}


# Reserved namespaces a predicate may address as ``<namespace>.<key>`` when a
# variable pool is supplied (e.g. ``run.approved``, ``system.default_model``).
# Mirrors ``variable_pool.RESERVED_NAMESPACES`` but kept local to avoid an
# import cycle (condition.py is imported by dag.py alongside variable_pool).
_POOL_NAMESPACES = ("workspace", "system", "run", "node")


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


def validate(expression: str) -> None:
    """Validate the complete condition AST without evaluating any operands.

    This pass is deliberately separate from evaluation.  A forbidden node in
    the right-hand side of ``False and ...`` must still be rejected even though
    correct boolean evaluation never visits that operand.
    """

    _parse_and_validate(expression)


def references(expression: str) -> Set[str]:
    """Bare names a validated expression reads from the evaluation ctx.

    Namespaced accesses (``ctx.x``, ``run.x``) resolve outside the node payload
    and are excluded, so callers can check exactly the names a node's resolved
    input has to supply. Raises :class:`ConditionError` on an invalid
    expression, like :func:`validate`.
    """

    names: Set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Attribute):
            return
        if isinstance(node, ast.Name):
            names.add(node.id)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(_parse_and_validate(expression).body)
    return names


def evaluate(expression: str, ctx: Dict[str, Any], *, pool: Optional[Any] = None) -> bool:
    """Safely evaluate ``expression`` against ``ctx``.

    Returns a boolean. Empty / whitespace-only expressions are invalid: a
    branch without a predicate must be represented by ``default_branch``.

    ``pool`` (P1, optional) is a :class:`~app.services.run_engine.variable_pool.VariablePool`.
    When supplied, ``<namespace>.<key>`` attribute references against the
    reserved namespaces resolve through the pool, so decision predicates can
    read namespaced selectors (e.g. ``run.approved``). When ``pool`` is ``None``
    only the legacy ``ctx.<key>`` form is accepted — behaviour is unchanged.
    """
    tree = _parse_and_validate(expression)
    try:
        value = _walk(tree.body, ctx, pool)
        return bool(value)
    except ConditionError:
        raise
    except Exception as exc:  # noqa: BLE001 - runtime predicates fail closed.
        # Predicate failures must not escape as raw Python exceptions: they
        # become stable Decision runtime failures upstream. Never include
        # operand reprs here because ctx can carry sensitive values.
        raise ConditionError(
            f"condition evaluation failed: {type(exc).__name__}",
            code="condition_evaluation_error",
        ) from exc


def _parse_and_validate(expression: str) -> ast.Expression:
    text = "" if expression is None else str(expression).strip()
    if not text:
        raise ConditionError(
            "condition expression must not be empty",
            code="condition_empty",
        )
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(
            f"invalid condition syntax: {exc.msg}",
            code="condition_syntax_error",
        ) from exc
    _validate_node(tree.body)
    return tree


def _unsupported(node: ast.AST, *, message: Optional[str] = None) -> NoReturn:
    raise ConditionError(
        message or f"unsupported expression node {type(node).__name__}",
        code="condition_unsupported",
    )


def _validate_node(node: ast.AST) -> None:
    """Recursively validate every child of an expression node."""

    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, _ALLOWED_BOOL_OPS):
            _unsupported(node, message=f"unsupported boolean op {type(node.op).__name__}")
        for value in node.values:
            _validate_node(value)
        return

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARY_OPS):
            _unsupported(node, message=f"unsupported unary op {type(node.op).__name__}")
        _validate_node(node.operand)
        return

    if isinstance(node, ast.Compare):
        _validate_node(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, _ALLOWED_CMP_OPS):
                _unsupported(node, message=f"unsupported comparison {type(op).__name__}")
            _validate_node(comparator)
        return

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return
        _unsupported(
            node,
            message=f"unsupported literal of type {type(node.value).__name__}",
        )

    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for element in node.elts:
            _validate_node(element)
        return

    if isinstance(node, ast.Name):
        return

    if isinstance(node, ast.Attribute):
        if (
            isinstance(node.value, ast.Name)
            and isinstance(node.attr, str)
            and node.value.id in ("ctx", "context", *_POOL_NAMESPACES)
        ):
            return
        _unsupported(
            node,
            message=(
                "only top-level ctx.<key> or reserved namespace.<key> "
                "attribute access is allowed"
            ),
        )

    _unsupported(node)


def _walk(node: ast.AST, ctx: Dict[str, Any], pool: Optional[Any] = None) -> Any:
    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, _ALLOWED_BOOL_OPS):
            _unsupported(node, message=f"unsupported boolean op {type(node.op).__name__}")
        if isinstance(node.op, ast.And):
            result: Any = True
            for value_node in node.values:
                result = _walk(value_node, ctx, pool)
                if not result:
                    return result
            return result
        last: Any = False
        for value_node in node.values:
            last = _walk(value_node, ctx, pool)
            if last:
                return last
        return last

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARY_OPS):
            _unsupported(node, message=f"unsupported unary op {type(node.op).__name__}")
        operand = _walk(node.operand, ctx, pool)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        return +operand

    if isinstance(node, ast.Compare):
        left = _walk(node.left, ctx, pool)
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, _ALLOWED_CMP_OPS):
                _unsupported(node, message=f"unsupported comparison {type(op).__name__}")
            right = _walk(comparator, ctx, pool)
            if not _cmp(op, left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        _unsupported(
            node,
            message=f"unsupported literal of type {type(node.value).__name__}",
        )

    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_walk(e, ctx, pool) for e in node.elts]

    if isinstance(node, ast.Name):
        return _lookup(ctx, node.id)

    if isinstance(node, ast.Attribute):
        if (
            isinstance(node.value, ast.Name)
            and isinstance(node.attr, str)
        ):
            base = node.value.id
            # ``ctx.<key>`` / ``context.<key>`` — legacy ctx access.
            if base in ("ctx", "context"):
                return _lookup(ctx, node.attr)
            # ``<namespace>.<key>`` — pool-backed namespaced selector (P1).
            if pool is not None and base in _POOL_NAMESPACES:
                return pool.get([base, node.attr])
            if base in _POOL_NAMESPACES:
                raise ConditionError(
                    f"condition namespace {base!r} is unavailable",
                    code="condition_namespace_unavailable",
                )
        _unsupported(
            node,
            message=(
                "only top-level ctx.<key> or reserved namespace.<key> "
                "attribute access is allowed"
            ),
        )

    _unsupported(node)


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
    raise ConditionError(
        f"unsupported comparison {type(op).__name__}",
        code="condition_unsupported",
    )


def _lookup(ctx: Dict[str, Any], name: str) -> Any:
    """Look up ``name`` in the ctx, then fall back to the nested ``input``.

    Returning ``None`` on miss is intentional. Equality checks can test for a
    missing value explicitly; ordered comparisons against it become a
    structured ``condition_evaluation_error`` at the public boundary.
    """
    if not isinstance(ctx, dict):
        return None
    if name in ctx:
        return ctx[name]
    inner = ctx.get("input")
    if isinstance(inner, dict) and name in inner:
        return inner[name]
    return None
