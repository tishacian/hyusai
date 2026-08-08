"""Runtime enforcement for the immutable executable contract pinned on a Run.

The helpers in this module never resolve mutable Skill rows.  A published or
draft-test Run carries the exact schemas accepted at its creation boundary;
legacy Runs without that evidence remain compatible and are not retrofitted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.services.flow_contracts import (
    FlowContractError,
    contract_ingress,
    validate_payload,
)

from .condition import ConditionError
from .condition import references as condition_references

ValidationMode = Literal["enforce", "observe"]


@dataclass(frozen=True, slots=True)
class RuntimeContractError(ValueError):
    code: str
    message: str
    path: str | None = None
    node_id: str | None = None

    def checkpoint(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "execution_contract_violation",
            "code": self.code,
            "message": self.message,
        }
        if self.path:
            payload["path"] = self.path
        if self.node_id:
            payload["node_id"] = self.node_id
        return payload

    def terminal_error(self) -> str:
        suffix = f":{self.node_id}" if self.node_id else ""
        return f"execution_contract:{self.code}{suffix}"


def _contract(run: Any) -> Mapping[str, Any] | None:
    value = getattr(run, "execution_contract", None)
    return value if isinstance(value, Mapping) else None


def validation_mode(run: Any) -> ValidationMode | None:
    contract = _contract(run)
    if contract is None:
        return None
    return "enforce" if contract.get("validation_mode") == "enforce" else "observe"


def _translate(exc: FlowContractError, *, node_id: str | None = None) -> RuntimeContractError:
    return RuntimeContractError(
        code=exc.code,
        message=exc.message,
        path=exc.path,
        node_id=node_id,
    )


def validate_ingress_payload(
    execution_contract: Mapping[str, Any],
    *,
    ingress_id: str,
    kind: str,
    payload: Any,
) -> Mapping[str, Any]:
    """Resolve and validate one normalized ingress before a Run can exist."""

    try:
        ingress = contract_ingress(execution_contract, ingress_id)
        if ingress.get("kind") != kind:
            raise FlowContractError(
                code="ingress_kind_mismatch",
                message="The requested ingress kind does not match the published contract.",
                path=f"ingresses/{ingress_id}/kind",
            )
        schema = ingress.get("input_schema")
        if not isinstance(schema, Mapping):
            raise FlowContractError(
                code="ingress_schema_missing",
                message="The published ingress has no executable input schema.",
                path=f"ingresses/{ingress_id}/input_schema",
            )
        validate_payload(
            payload,
            schema,
            code="ingress_payload_invalid",
            subject="Ingress payload",
        )
        return ingress
    except FlowContractError as exc:
        raise _translate(exc, node_id=ingress_id) from exc


def validate_node_output(run: Any, *, node_id: str, payload: Any) -> RuntimeContractError | None:
    """Validate a Skill node result using only its frozen Run contract."""

    contract = _contract(run)
    if contract is None:
        return None
    nodes = contract.get("nodes")
    node_contract = nodes.get(node_id) if isinstance(nodes, Mapping) else None
    if not isinstance(node_contract, Mapping):
        return None
    schema = node_contract.get("output_schema")
    if not isinstance(schema, Mapping):
        return RuntimeContractError(
            code="node_output_schema_missing",
            message="The frozen node contract has no executable output schema.",
            path=f"nodes/{node_id}/output_schema",
            node_id=node_id,
        )
    try:
        validate_payload(
            payload,
            schema,
            code="node_output_invalid",
            subject="Node output",
        )
    except FlowContractError as exc:
        return _translate(exc, node_id=node_id)
    return None


def validate_node_invocation_output(
    run: Any,
    *,
    node_id: str,
    payload: Any,
) -> RuntimeContractError | None:
    """Validate a raw Skill result before a control node adapts its shape.

    Retry and loop nodes expose stable control envelopes rather than the raw
    Skill output.  Their frozen contract therefore carries a second schema for
    the invocation boundary.  Older/non-adapted contracts have no such surface
    and retain their historical node-only validation behaviour.
    """

    contract = _contract(run)
    if contract is None:
        return None
    nodes = contract.get("nodes")
    node_contract = nodes.get(node_id) if isinstance(nodes, Mapping) else None
    if not isinstance(node_contract, Mapping):
        return None
    adapter = node_contract.get("output_adapter")
    if adapter not in {"retry.v1", "loop.v1"}:
        return None
    schema = node_contract.get("invocation_output_schema")
    if not isinstance(schema, Mapping):
        return RuntimeContractError(
            code="node_invocation_output_schema_missing",
            message="The frozen control-node contract has no invocation output schema.",
            path=f"nodes/{node_id}/invocation_output_schema",
            node_id=node_id,
        )
    try:
        validate_payload(
            payload,
            schema,
            code="node_invocation_output_invalid",
            subject="Skill invocation output",
        )
    except FlowContractError as exc:
        return _translate(exc, node_id=node_id)
    return None


def unbound_decision_inputs(
    *,
    branches: Any,
    resolved_input: Mapping[str, Any] | None,
) -> list[str]:
    """Names the branch conditions read that the resolved input never binds.

    ``condition.evaluate`` resolves an unknown name to ``None``, so a Decision
    fed a differently-shaped upstream payload routes on ``None`` comparisons
    instead of failing.  Listing the names here lets the walker surface the
    real cause before the first predicate runs.  An invalid expression is left
    to the existing condition validation and reported as bound.
    """

    if not isinstance(branches, list):
        return []
    bound = set(resolved_input or {})
    inner = (resolved_input or {}).get("input")
    if isinstance(inner, Mapping):
        bound |= set(inner)
    unbound: set[str] = set()
    for branch in branches:
        if not isinstance(branch, Mapping):
            continue
        try:
            unbound |= condition_references(str(branch.get("condition") or "")) - bound
        except ConditionError:
            continue
    return sorted(unbound)


def decision_input_error(*, node_id: str, unbound: list[str]) -> RuntimeContractError:
    named = ", ".join(repr(name) for name in unbound)
    return RuntimeContractError(
        code="decision_input_unbound",
        message=f"The Decision reads {named}, which its resolved input does not bind.",
        path=f"nodes/{node_id}/config/branches",
        node_id=node_id,
    )


def validate_sink_output(run: Any, *, node_id: str, payload: Any) -> RuntimeContractError | None:
    """Validate a terminal sink before the Run result becomes visible."""

    contract = _contract(run)
    if contract is None:
        return None
    outputs = contract.get("outputs")
    if not isinstance(outputs, list):
        return None
    output_contract = next(
        (
            item
            for item in outputs
            if isinstance(item, Mapping) and item.get("node_id") == node_id
        ),
        None,
    )
    if not isinstance(output_contract, Mapping):
        return None
    schema = output_contract.get("schema")
    if not isinstance(schema, Mapping):
        return RuntimeContractError(
            code="sink_output_schema_missing",
            message="The frozen sink contract has no executable output schema.",
            path=f"outputs/{node_id}/schema",
            node_id=node_id,
        )
    try:
        validate_payload(
            payload,
            schema,
            code="sink_output_invalid",
            subject="Flow output",
        )
    except FlowContractError as exc:
        return _translate(exc, node_id=node_id)
    return None
