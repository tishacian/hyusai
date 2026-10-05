"""Secret-free source references pinned by a Flow, resolved by its consumers.

An asset emits a reference, never a dataset or a successful connection verdict.
Readers still own authorization, bounded reads and credential resolution in the
Run's workspace. Bindings come exclusively from the immutable Run graph.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

from app.services.connectors.generic.service import CONNECTORS

CONNECTOR_SOURCE_TYPE = "source.connector"


def connector_reference(node: Mapping[str, Any]) -> dict[str, Any]:
    config = node.get("config") or {}
    if node.get("kind") != "asset" or not isinstance(config, Mapping):
        raise ValueError("DATA_SOURCE_INVALID")
    if set(config) - {"connector_id", "read_mode", "resources"}:
        raise ValueError("DATA_SOURCE_CONFIG_INVALID")
    connector_id = config.get("connector_id")
    if not isinstance(connector_id, str) or connector_id not in CONNECTORS:
        raise ValueError("DATA_SOURCE_CONNECTOR_INVALID")
    mode = config.get("read_mode", "reference")
    if (
        not isinstance(mode, str)
        or mode not in {"reference", "live"}
        or (mode == "live" and connector_id != "postgresql")
    ):
        raise ValueError("DATA_SOURCE_MODE_INVALID")
    resources = config.get("resources", [])
    if not isinstance(resources, list) or len(resources) > 64:
        raise ValueError("DATA_SOURCE_RESOURCES_INVALID")
    clean = []
    for resource in resources:
        if not isinstance(resource, Mapping) or set(resource) != {"schema", "table"}:
            raise ValueError("DATA_SOURCE_RESOURCES_INVALID")
        if not all(
            isinstance(resource[key], str)
            and 0 < len(resource[key]) <= 128
            and "\x00" not in resource[key]
            for key in ("schema", "table")
        ):
            raise ValueError("DATA_SOURCE_RESOURCES_INVALID")
        item = {"schema": resource["schema"], "table": resource["table"]}
        if item not in clean:
            clean.append(item)
    return {
        "node_id": str(node.get("id") or ""),
        "connector_id": connector_id,
        "read_mode": mode,
        "resources": clean,
    }


def bound_data_sources(flow: Any, consumer_id: str | None) -> list[dict[str, Any]]:
    if not isinstance(flow, Mapping) or not consumer_id:
        return []
    nodes = {node.get("id"): node for node in flow.get("nodes", []) if isinstance(node, Mapping)}
    consumer = nodes.get(consumer_id) or {}
    config = consumer.get("config") or {}
    refs = config.get("data_sources") if isinstance(config, Mapping) else None
    edges = flow.get("edges", [])
    if refs is None:
        refs = [
            edge["from"]
            for edge in edges
            if isinstance(edge, Mapping)
            and edge.get("to") == consumer_id
            and edge.get("kind", "data") == "data"
            and edge.get("from") in nodes
            and (
                nodes[edge["from"]].get("type") == CONNECTOR_SOURCE_TYPE
                or (
                    nodes[edge["from"]].get("kind") == "asset"
                    and (nodes[edge["from"]].get("config") or {}).get("collection_slug")
                )
            )
        ]
    if (
        not isinstance(refs, list)
        or len(refs) > 64
        or any(not isinstance(ref, str) for ref in refs)
    ):
        raise ValueError("DATA_SOURCE_BINDING_INVALID")
    result = []
    for ref in refs:
        source = nodes.get(ref)
        if source is None or not any(
            isinstance(edge, Mapping)
            and edge.get("from") == ref
            and edge.get("to") == consumer_id
            and edge.get("kind", "data") == "data"
            for edge in edges
        ):
            raise ValueError("DATA_SOURCE_BINDING_DISCONNECTED")
        if source.get("type") == CONNECTOR_SOURCE_TYPE:
            item = connector_reference(source)
        elif source.get("kind") == "asset" and (source.get("config") or {}).get("collection_slug"):
            item = {
                "node_id": ref,
                "collection_slug": source["config"]["collection_slug"],
                "read_mode": "retrieval",
            }
        else:
            raise ValueError("DATA_SOURCE_BINDING_INVALID")
        if item not in result:
            result.append(item)
    return result


def data_source_issues(flow: Mapping[str, Any]) -> list[tuple[str, str]]:
    issues = []
    for node in flow.get("nodes", []):
        if not isinstance(node, Mapping):
            continue
        try:
            if node.get("type") == CONNECTOR_SOURCE_TYPE:
                connector_reference(node)
            bound_data_sources(flow, node.get("id"))
        except ValueError as exc:
            issues.append((str(node.get("id") or ""), str(exc)))
    if (flow.get("runtime_contract") or {}).get("requires_postgresql_source") is True:
        from app.services.connectors.generic.postgresql_claims import CLAIM_RESOURCES

        for consumer_id in ("loop.investigate", "task.simulate"):
            try:
                require_postgresql_binding(
                    SimpleNamespace(flow_snapshot=flow),
                    bound_data_sources(flow, consumer_id),
                    resources=CLAIM_RESOURCES,
                )
            except ValueError as exc:
                issues.append((consumer_id, str(exc)))
    return issues


def require_postgresql_binding(
    run: Any, sources: list[dict[str, Any]], *, resources: list[dict[str, str]]
) -> dict[str, Any] | None:
    """Legacy graphs retain implicit reads; declared connector graphs fail closed."""
    flow = getattr(run, "flow_snapshot", None) or {}
    declared = any(
        node.get("type") == CONNECTOR_SOURCE_TYPE
        and (node.get("config") or {}).get("connector_id") == "postgresql"
        for node in flow.get("nodes", [])
        if isinstance(node, Mapping)
    )
    refs = [source for source in sources if source.get("connector_id") == "postgresql"]
    required = (flow.get("runtime_contract") or {}).get("requires_postgresql_source") is True
    if not refs and not declared and not required:
        return None
    if len(refs) != 1 or refs[0].get("read_mode") != "live":
        raise ValueError("CLAIM_DATA_SOURCE_BINDING_REQUIRED")
    if any(resource not in refs[0]["resources"] for resource in resources):
        raise ValueError("CLAIM_DATA_SOURCE_RESOURCE_MISSING")
    return refs[0]
