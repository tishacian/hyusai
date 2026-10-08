"""Runtime-owned HITL ports, shared by validation and the Flow manifest."""
from collections.abc import Mapping
from typing import Any


def hitl_ports(node: Mapping[str, Any], direction: str) -> dict[str, str] | None:
    if node.get("kind") != "hitl":
        return None
    config = node.get("config")
    review = isinstance(config, Mapping) and config.get("prompt_kind") == "review_dataset_labels"
    if direction == "inputs":
        # Keep the legacy whole-envelope input while offering a typed dataset id.
        return {"dataset_id": "string", "in": "object"} if review else {"in": "object"}
    ports = {"approved": "boolean", "rejected": "boolean", "decision_id": "string",
             "decision_status": "string", "decided_by": "string"}
    if review:
        ports.update({"dataset_id": "string", "name": "string", "slug": "string",
                      "version": "integer", "rows": "integer", "columns": "integer", "schema": "array"})
    return ports


def hitl_schema(node: Mapping[str, Any], direction: str) -> dict[str, Any] | None:
    ports = hitl_ports(node, direction)
    if ports is None:
        return None
    properties: dict[str, Any] = {name: {"type": primitive} for name, primitive in ports.items()}
    if direction == "outputs":
        properties["decided_by"] = {"type": ["string", "null"]}
    return {"type": "object", "properties": properties}
