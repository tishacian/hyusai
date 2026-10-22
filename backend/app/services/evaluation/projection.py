"""Server-owned campaign projections. Never save or repair the author's graph.

Only the selected ingress and paths before the first human boundary execute.
Incoming declarative assets remain part of the graph and its source evidence.
Other executable dependencies are refused rather than silently substituted.
"""

from __future__ import annotations

import copy
from collections import Counter

from app.services import flow_contracts
from app.services.flow_data_sources import edge_ends
from app.services.flow_node_kind import flow_node_kind
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.systems import flow_workbench


def _error(code, message, **details):
    return flow_workbench.FlowWorkbenchError(code, message, 422, details or None)


def select_source(flow, *, ingress_id, ingress_kind):
    """Resolve only entry identity before compiling the projected executors."""
    if (ingress_id is None) != (ingress_kind is None):
        raise _error("WORKBENCH_INGRESS_INCOMPLETE", "Select an ingress and its kind together.")
    sources = [node for node in flow["nodes"] if flow_node_kind(node) == "source"]
    if ingress_id is not None:
        sources = [node for node in sources if node["id"] == ingress_id]
    if len(sources) != 1:
        raise _error("EVALUATION_INGRESS_REQUIRED", "Select exactly one execution ingress.")
    source = sources[0]
    try:
        kind = flow_contracts._ingress_kind(source)
    except flow_contracts.FlowContractError as exc:
        raise _error(exc.code.upper(), exc.message, path=exc.path) from exc
    if ingress_kind is not None and kind != ingress_kind:
        raise _error("WORKBENCH_INGRESS_NOT_FOUND", "The selected ingress kind changed.")
    return {"ingress_id": source["id"], "source_node_id": source["id"], "kind": kind}


def project_flow(source, *, expected_sha256, ingress_id=None, ingress_kind=None):
    flow, source_sha = flow_workbench._canonical_request_flow(
        source, expected_flow_sha256=expected_sha256, require_executable=False
    )
    # Identity must be unambiguous even outside the selected path. Do not let a
    # dict overwrite hide a second executable with the same id.
    counts = Counter(node["id"] for node in flow.get("nodes", []))
    if any(count != 1 for count in counts.values()):
        raise _error("EVALUATION_GRAPH_IDENTITY_INVALID", "Node ids must be unique.")
    selected = select_source(flow, ingress_id=ingress_id, ingress_kind=ingress_kind)
    nodes = {node["id"]: node for node in flow["nodes"]}
    edges = flow.get("edges", [])
    reached, boundaries = set(), set()
    pending = [selected["source_node_id"]]
    while pending:
        key = pending.pop()
        if key in reached:
            continue
        if key not in nodes:
            raise _error("EVALUATION_NODE_MISSING", "A reachable node is missing.", node_id=key)
        reached.add(key)
        if flow_node_kind(nodes[key]) == "hitl":
            boundaries.add(key)
            continue
        pending.extend(
            target for edge in edges for origin, target in [edge_ends(edge)] if origin == key
        )

    # Sources are alternative entry points. Assets are required context; their
    # entire incoming asset dependency chain must be retained. Executable
    # producers outside the prefix cannot be pulled in without qualification.
    retained = set(reached)
    pending = list(reached)
    while pending:
        key = pending.pop()
        for edge in edges:
            origin, target = edge_ends(edge)
            if target != key or origin in retained:
                continue
            producer = nodes.get(origin)
            if producer is None:
                raise _error(
                    "EVALUATION_NODE_MISSING", "A required source is missing.", node_id=origin
                )
            kind = flow_node_kind(producer)
            if kind == "source":
                continue
            if kind != "asset" or edge.get("kind", "data") != "data":
                raise _error(
                    "EVALUATION_DEPENDENCY_OUTSIDE_PREFIX",
                    "The selected path depends on execution outside its human boundary.",
                    node_id=key,
                    dependency_node_id=origin,
                )
            retained.add(origin)
            pending.append(origin)

    def check_refs(value, consumer):
        if isinstance(value, dict):
            owner = value.get("node_id")
            if (
                "path" in value
                and isinstance(owner, str)
                and owner in nodes
                and owner not in retained
            ):
                raise _error(
                    "EVALUATION_DEPENDENCY_OUTSIDE_PREFIX",
                    "An input selector depends on a node excluded from this execution.",
                    node_id=consumer,
                    dependency_node_id=owner,
                )
            for child in value.values():
                check_refs(child, consumer)
        elif isinstance(value, list):
            for child in value:
                check_refs(child, consumer)

    for key in retained:
        config = nodes[key].get("config") or {}
        check_refs(config, key)
        mappings = config.get("inputs_map") if isinstance(config, dict) else None
        for value in mappings.values() if isinstance(mappings, dict) else ():
            if isinstance(value, str) and any(
                value == excluded or value.startswith(excluded + ".")
                for excluded in nodes.keys() - retained
            ):
                raise _error(
                    "EVALUATION_DEPENDENCY_OUTSIDE_PREFIX",
                    "An input selector depends on a node excluded from this execution.",
                    node_id=key,
                )
    flow["nodes"] = [node for node in flow["nodes"] if node["id"] in retained]
    flow["edges"] = [
        edge
        for edge in edges
        if (ends := edge_ends(edge))[0] in retained
        and ends[1] in retained
        and ends[0] not in boundaries
    ]
    requirements = (flow.get("runtime_contract") or {}).get("postgresql_consumers")
    if requirements is not None:
        if not isinstance(requirements, list) or any(
            not isinstance(item, dict) or item.get("node_id") not in nodes for item in requirements
        ):
            raise _error(
                "EVALUATION_SOURCE_REQUIREMENT_INVALID", "Source requirements are malformed."
            )
        scoped = [item for item in requirements if item["node_id"] in retained]
        if not scoped and flow["runtime_contract"].get("requires_postgresql_source"):
            raise _error(
                "EVALUATION_SOURCE_REQUIREMENT_UNQUALIFIED",
                "This entry does not contain any declared PostgreSQL consumer.",
            )
        flow["runtime_contract"]["postgresql_consumers"] = scoped

    if (flow.get("runtime_contract") or {}).get("ecommerce_composition_v1") is True:
        from app.services.ecommerce.composition import _ingress_operations

        # Preserve the adapter's trusted operation for this entry, including
        # its legacy default. A payload must never be able to choose a cohort.
        try:
            operations = _ingress_operations(source)
        except ValueError as exc:
            raise _error("EVALUATION_INGRESS_OPERATIONS_INVALID", str(exc)) from exc
        flow["runtime_contract"]["ecommerce_ingress_operations"] = {
            key: value for key, value in operations.items() if key in retained
        }

    # Strict contracts need an output declaration. This inert terminal is never
    # reached: the campaign runtime closes at HITL and refuses every resume.
    synthetic_sink = None
    if (
        flow.get("io_mode") == "strict"
        and boundaries
        and not any(flow_node_kind(node) == "sink" for node in flow["nodes"])
    ):
        synthetic_sink = "__evaluation_boundary_output__"
        while synthetic_sink in nodes:
            synthetic_sink += "_"
        flow["nodes"].append(
            {
                "id": synthetic_sink,
                "kind": "sink",
                "config": {"output_schema": {"type": "object", "additionalProperties": True}},
            }
        )
        flow["edges"].extend(
            {"from": key, "to": synthetic_sink, "kind": "data"} for key in sorted(boundaries)
        )
    projected_sha = canonical_flow_sha256(flow)
    flow_workbench._canonical_request_flow(
        flow, expected_flow_sha256=projected_sha, require_executable=True
    )
    evidence = {
        "schema_version": 1,
        "source_flow_sha256": source_sha,
        "projected_flow_sha256": projected_sha,
        "retained_node_ids": sorted(retained),
        "excluded_node_ids": sorted(nodes.keys() - retained),
        "human_boundary_node_ids": sorted(boundaries),
        "asset_node_ids": sorted(key for key in retained if flow_node_kind(nodes[key]) == "asset"),
        "synthetic_output_node_id": synthetic_sink,
    }
    return flow, selected, evidence


def prepare_candidate(
    db, *, system_id, workspace, source, expected_sha256, ingress_id, ingress_kind
):
    system = flow_workbench._locked_system(db, system_id=system_id, workspace=workspace)
    flow, selected, evidence = project_flow(
        source, expected_sha256=expected_sha256, ingress_id=ingress_id, ingress_kind=ingress_kind
    )
    contract, reason = flow_workbench._compile(db, flow=flow, workspace=workspace, system=system)
    if contract.get("runtime_mode") == "sequential_legacy":
        raise _error("WORKBENCH_DAG_REQUIRED", "Campaign projections require the DAG runtime.")
    ingress = flow_workbench._select_ingress(
        contract, ingress_id=selected["ingress_id"], ingress_kind=selected["kind"]
    )
    return flow_workbench.PreparedPreview(
        system=system,
        flow=flow,
        flow_sha256=evidence["projected_flow_sha256"],
        source_flow_sha256=evidence["source_flow_sha256"],
        contract=contract,
        runtime_reason=reason,
        ingress=ingress,
    ), evidence


def prepare_baseline(*, baseline, system, ingress_id, ingress_kind):
    # Validate the historical binding before reducing it. A fresh compilation
    # here would replace the baseline's Skills/prompts with today's catalog.
    try:
        frozen = flow_contracts.validate_execution_contract(baseline.execution_contract)
    except flow_contracts.FlowContractError as exc:
        raise _error(exc.code.upper(), exc.message, path=exc.path) from exc
    selected = flow_workbench._select_ingress(
        frozen, ingress_id=ingress_id, ingress_kind=ingress_kind
    )
    flow, _, evidence = project_flow(
        baseline.flow_snapshot,
        expected_sha256=baseline.flow_sha256,
        ingress_id=selected["ingress_id"],
        ingress_kind=selected["kind"],
    )
    ids = {node["id"] for node in flow["nodes"]}
    from app.services.flow_skill_binding import resolve_flow_skill_binding

    for node in flow["nodes"]:
        binding = resolve_flow_skill_binding(node)
        if binding.skill_id is None and binding.skill_slug is None:
            continue
        pinned = frozen["nodes"].get(node["id"])
        if (
            not pinned
            or (binding.skill_id is not None and binding.skill_id != pinned.get("skill_id"))
            or (binding.skill_slug is not None and binding.skill_slug != pinned.get("skill_slug"))
        ):
            raise _error(
                "EVALUATION_BASELINE_BINDING_INVALID",
                "A retained executor is not bound by the frozen baseline contract.",
                node_id=node["id"],
            )
    frozen["nodes"] = {key: value for key, value in frozen["nodes"].items() if key in ids}
    frozen["ingresses"] = [copy.deepcopy(selected)]
    frozen["outputs"] = [output for output in frozen["outputs"] if output["node_id"] in ids]
    if evidence["synthetic_output_node_id"]:
        schema = {"type": "object", "additionalProperties": True}
        frozen["outputs"].append(
            {
                "node_id": evidence["synthetic_output_node_id"],
                "schema": schema,
                "schema_sha256": flow_contracts.canonical_sha256(schema),
            }
        )
    frozen.pop("contract_sha256")
    frozen["contract_sha256"] = flow_contracts.canonical_sha256(frozen)
    frozen = flow_contracts.validate_execution_contract(frozen)
    return flow_workbench.PreparedPreview(
        system=system,
        flow=flow,
        flow_sha256=evidence["projected_flow_sha256"],
        source_flow_sha256=evidence["source_flow_sha256"],
        contract=frozen,
        runtime_reason="evaluation_frozen_baseline_projection",
        ingress=selected,
    ), evidence
