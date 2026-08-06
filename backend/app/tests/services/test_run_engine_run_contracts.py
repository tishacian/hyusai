from types import SimpleNamespace

import pytest

from app.services.run_engine.dag import _apply_runtime_output_contract
from app.services.run_engine.run_contracts import (
    RuntimeContractError,
    validate_ingress_payload,
    validate_node_invocation_output,
    validate_node_output,
    validate_sink_output,
    validation_mode,
)


def _contract(mode: str = "enforce") -> dict:
    text_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
        "additionalProperties": False,
    }
    return {
        "validation_mode": mode,
        "ingresses": [
            {
                "ingress_id": "input.manual",
                "kind": "manual",
                "input_schema": text_schema,
            }
        ],
        "nodes": {"task.answer": {"output_schema": text_schema}},
        "outputs": [{"node_id": "sink.answer", "schema": text_schema}],
    }


def test_ingress_is_kind_and_schema_bound_before_run_creation() -> None:
    contract = _contract()
    selected = validate_ingress_payload(
        contract,
        ingress_id="input.manual",
        kind="manual",
        payload={"answer": "ok"},
    )
    assert selected["source_node_id"] if "source_node_id" in selected else selected["ingress_id"]

    with pytest.raises(RuntimeContractError) as invalid:
        validate_ingress_payload(
            contract,
            ingress_id="input.manual",
            kind="manual",
            payload={"answer": 42},
        )
    assert invalid.value.code == "ingress_payload_invalid"

    with pytest.raises(RuntimeContractError) as wrong_kind:
        validate_ingress_payload(
            contract,
            ingress_id="input.manual",
            kind="http",
            payload={"answer": "ok"},
        )
    assert wrong_kind.value.code == "ingress_kind_mismatch"


def test_node_and_sink_outputs_use_only_frozen_contract() -> None:
    run = SimpleNamespace(execution_contract=_contract())
    assert validate_node_output(run, node_id="task.answer", payload={"answer": "ok"}) is None
    assert validate_sink_output(run, node_id="sink.answer", payload={"answer": "ok"}) is None

    node_error = validate_node_output(run, node_id="task.answer", payload={"answer": 7})
    sink_error = validate_sink_output(run, node_id="sink.answer", payload={})
    assert node_error is not None and node_error.code == "node_output_invalid"
    assert sink_error is not None and sink_error.code == "sink_output_invalid"
    assert node_error.terminal_error() == "execution_contract:node_output_invalid:task.answer"


def test_missing_contract_is_legacy_compatible_and_mode_is_pinned() -> None:
    legacy = SimpleNamespace(execution_contract=None)
    strict = SimpleNamespace(execution_contract=_contract("enforce"))
    overlay = SimpleNamespace(execution_contract=_contract("observe"))
    assert validation_mode(legacy) is None
    assert validation_mode(strict) == "enforce"
    assert validation_mode(overlay) == "observe"
    assert validate_node_output(legacy, node_id="anything", payload=object()) is None


def test_runtime_contract_preserves_falsy_output_for_schema_validation() -> None:
    run = SimpleNamespace(
        execution_contract={
            "validation_mode": "enforce",
            "nodes": {"boolean.task": {"output_schema": {"type": "boolean"}}},
            "outputs": [],
        }
    )
    node = SimpleNamespace(id="boolean.task", kind="task")

    outcome = _apply_runtime_output_contract(None, run, node, {"output": False})

    assert outcome == {"output": False}


def test_control_invocation_contract_fails_closed_when_schema_is_missing() -> None:
    run = SimpleNamespace(
        execution_contract={
            "validation_mode": "enforce",
            "nodes": {"retry": {"output_adapter": "retry.v1"}},
            "outputs": [],
        }
    )

    error = validate_node_invocation_output(
        run,
        node_id="retry",
        payload={"answer": "ok"},
    )

    assert error is not None
    assert error.code == "node_invocation_output_schema_missing"
    assert error.terminal_error() == (
        "execution_contract:node_invocation_output_schema_missing:retry"
    )
