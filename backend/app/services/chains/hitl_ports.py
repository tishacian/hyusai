"""Runtime-owned HITL ports, shared by validation and the Flow manifest."""
from collections.abc import Mapping
from typing import Any


def hitl_ports(node: Mapping[str, Any], direction: str) -> dict[str, str | None] | None:
    if node.get("kind") != "hitl":
        return None
    config = node.get("config")
    review = isinstance(config, Mapping) and config.get("prompt_kind") == "review_dataset_labels"
    if direction == "inputs":
        # Inputs describe the authored context shown to the reviewer. Unlike
        # the verdict envelope, they are not owned by the HITL runtime.
        inputs: dict[str, str | None] = {}
        declared = node.get("inputs")
        for port in declared if isinstance(declared, list) else []:
            if isinstance(port, Mapping) and isinstance(port.get("name"), str) and port["name"]:
                inputs[port["name"]] = port.get("schema") if isinstance(port.get("schema"), str) else None
        if review:
            inputs["dataset_id"] = "string"
        return inputs
    ports = {"approved": "boolean", "rejected": "boolean", "decision_id": "string",
             "decision_status": "string", "decided_by": "string"}
    if review:
        ports.update({"dataset_id": "string", "name": "string", "slug": "string",
                      "version": "integer", "rows": "integer", "columns": "integer", "schema": "array"})
    if isinstance(config, Mapping) and config.get("prompt_kind") == "approve_model_retraining":
        ports["proposal_id"] = "string"
    return ports


def hitl_schema(node: Mapping[str, Any], direction: str) -> dict[str, Any] | None:
    ports = hitl_ports(node, direction)
    if ports is None:
        return None
    primitives = {"string", "number", "integer", "boolean", "object", "array", "null"}
    properties: dict[str, Any] = {
        name: {"type": primitive} if primitive in primitives else {}
        for name, primitive in ports.items()
    }
    if direction == "outputs":
        properties["decided_by"] = {"type": ["string", "null"]}
    return {"type": "object", "properties": properties}
