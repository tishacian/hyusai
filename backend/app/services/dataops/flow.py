"""Pure publication checks for graph-owned preparation specifications and ports.

No dataset is resolved here: workspace authority, schema compatibility and the
immutable input versions remain the responsibility of preparation execution.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from app.schemas.data_prep import DataPrepSpec
from app.services.flow_skill_binding import FlowSkillBindingError, resolve_flow_skill_binding
from app.services.tabular_datasets import slugify

_UNION_PORT = re.compile(r"in_([1-9]|1[0-6])\Z")


def _port_names(node: Mapping[str, Any], field: str) -> set[str] | None:
    """Absent visual ports are inferred for existing authored Flows."""
    if field not in node:
        return None
    ports = node[field]
    if not isinstance(ports, list) or any(
        not isinstance(port, Mapping)
        or not isinstance(port.get("name"), str)
        or not port["name"]
        or port["name"] != port["name"].strip()
        for port in ports
    ):
        raise ValueError("DATAPREP_PORTS_INVALID")
    names = [port["name"] for port in ports]
    if len(names) != len(set(names)):
        raise ValueError("DATAPREP_PORT_DUPLICATE")
    return set(names)


def _prep_config(node: Mapping[str, Any]) -> Mapping[str, Any]:
    config = node.get("config") or {}
    if not isinstance(config, Mapping):
        raise ValueError("DATAPREP_CONFIG_INVALID")
    params = config.get("params") or {}
    if not isinstance(params, Mapping):
        raise ValueError("DATAPREP_CONFIG_INVALID")
    if (
        "data_prep" in config
        and "data_prep" in params
        and config["data_prep"] != params["data_prep"]
    ):
        raise ValueError("GRAPH_CONFIG_CONFLICT")
    prep = config.get("data_prep") or params.get("data_prep")
    if not isinstance(prep, Mapping):
        raise ValueError("DATAPREP_CONFIG_REQUIRED")
    if any("inputs_map" in holder for holder in (node, config, params, prep)):
        raise ValueError("DATAPREP_INPUTS_MAP_FORBIDDEN")
    return prep


def _edge_end(edge: Mapping[str, Any], primary: str, alias: str) -> Any:
    value = edge.get(primary) or edge.get(alias)
    return value.strip() if isinstance(value, str) else None


def data_prep_issues(flow: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return stable node/reason diagnostics without mutation or database reads."""
    issues: list[tuple[str, str]] = []
    nodes = flow.get("nodes") or []
    edges = flow.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return issues  # The generic graph-shape validator owns malformed containers.
    data_edges = [
        edge
        for edge in edges
        if isinstance(edge, Mapping) and (edge.get("kind") or "data") == "data"
    ]
    preps: dict[str, tuple[Mapping[str, Any], DataPrepSpec]] = {}
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        try:
            binding = resolve_flow_skill_binding(node)
        except FlowSkillBindingError:
            continue  # The canonical binding validator reports ambiguous Skill identities.
        if binding.skill_slug != "data_prep_v1":
            continue
        node_id = str(node.get("id") or "")
        try:
            config = _prep_config(node)
            try:
                spec = DataPrepSpec.model_validate(config.get("spec"))
            except (TypeError, ValueError) as exc:
                raise ValueError("DATAPREP_SPEC_INVALID") from exc
            preps[node_id] = (node, spec)
            slugs = [slugify(output.name) for output in spec.outputs]
            if any(not output.name.strip() for output in spec.outputs):
                raise ValueError("DATAPREP_OUTPUT_NAME_REQUIRED")
            if len(slugs) != len(set(slugs)):
                raise ValueError("DATAPREP_OUTPUT_NAME_DUPLICATE")

            pins = config.get("inputs", {})
            if not isinstance(pins, Mapping) or any(
                not isinstance(port, str)
                or not isinstance(ref, Mapping)
                or not any(
                    isinstance(ref.get(key), str) and ref[key].strip()
                    for key in ("dataset_id", "id", "dataset_slug", "slug", "asset_id")
                )
                for port, ref in pins.items()
            ):
                raise ValueError("DATAPREP_INPUTS_INVALID")
            incoming = [edge for edge in data_edges if _edge_end(edge, "to", "target") == node_id]
            wired: list[str] = []
            for edge in incoming:
                port = edge.get("to_port")
                if port is None and spec.operation not in {"join", "union", "split"}:
                    port = "in"
                if not isinstance(port, str) or not port or port != port.strip():
                    raise ValueError("DATAPREP_PORT_UNNAMED")
                wired.append(port)
            occupied = set(pins) | set(wired)
            declared = _port_names(node, "inputs")
            if spec.operation == "union":
                required = declared if declared is not None else occupied
                if not 2 <= len(required) <= 16 or any(
                    _UNION_PORT.fullmatch(port) is None for port in required
                ):
                    raise ValueError("DATAPREP_INPUT_PORTS_INVALID")
            else:
                required = {"left", "right"} if spec.operation == "join" else {"in"}
                if declared is not None and declared != required:
                    raise ValueError("DATAPREP_INPUT_PORTS_INVALID")
            if occupied - required:
                raise ValueError("DATAPREP_PORT_UNKNOWN")
            if set(pins) & set(wired) or any(count > 1 for count in Counter(wired).values()):
                raise ValueError("DATAPREP_INPUT_PORT_DUPLICATE")
            if required - occupied:
                raise ValueError("DATAPREP_PORT_MISSING")
            outputs = _port_names(node, "outputs")
            if outputs is not None and outputs != {output.port for output in spec.outputs}:
                raise ValueError("DATAPREP_OUTPUT_PORTS_INVALID")
        except ValueError as exc:
            issues.append((node_id, str(exc)))

    # The predecessor merge transports outputs on control/branch routes too.
    # Every consumer must therefore select a branch, including ML and sinks
    # that never run the preparation input adapter themselves.
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        source = _edge_end(edge, "from", "source")
        if source not in preps:
            continue
        _, spec = preps[source]
        port = edge.get("from_port")
        if port is None and spec.operation != "split":
            continue
        if port is None or port == "":
            issues.append((source, "DATAPREP_SOURCE_PORT_REQUIRED"))
        elif not isinstance(port, str) or port not in {output.port for output in spec.outputs}:
            issues.append((source, "DATAPREP_SOURCE_PORT_UNKNOWN"))
    return list(dict.fromkeys(issues))
