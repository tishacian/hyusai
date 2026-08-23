"""Canonical Flow execution-mode and hashing contract.

This module is deliberately dependency-light so API creation, manifests and
workers all make the same DAG/legacy decision.  A Run may pin the resolved
mode alongside its immutable flow snapshot; that pin wins over later Workspace
feature changes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

RuntimeMode = Literal["dag_strict", "dag_overlay", "sequential_legacy"]

RUNTIME_MODES: frozenset[str] = frozenset(
    {"dag_strict", "dag_overlay", "sequential_legacy"}
)
CONTROL_KINDS: frozenset[str] = frozenset(
    {"decision", "fork", "join", "retry", "hitl", "subflow", "loop", "agent_loop"}
)
WORKBENCH_EXECUTION_SURFACES: frozenset[str] = frozenset(
    {"builder_preview", "node_preview", "golden_preview"}
)
NON_PUBLISHED_EXECUTION_SURFACES: frozenset[str] = frozenset(
    {"draft_test", *WORKBENCH_EXECUTION_SURFACES}
)


@dataclass(frozen=True, slots=True)
class FlowExecutionResolution:
    runtime_mode: RuntimeMode
    reason: str

    @property
    def uses_dag(self) -> bool:
        return self.runtime_mode in {"dag_strict", "dag_overlay"}

    @property
    def strict_authoritative(self) -> bool:
        return self.runtime_mode == "dag_strict"

    @property
    def debug_supported(self) -> bool:
        return self.uses_dag


def canonical_flow(flow: Any) -> dict[str, Any]:
    """Return the only canonical persisted Flow shape.

    Historical ``NULL`` is the empty Flow.  Other JSON shapes are corruption,
    not alternate spellings of an empty graph.
    """

    if flow is None:
        return {}
    if not isinstance(flow, dict):
        raise ValueError("flow_definition must be a JSON object")
    return flow


def canonical_flow_sha256(flow: Any) -> str:
    """Hash semantic JSON while retaining meaningful array ordering."""

    encoded = json.dumps(
        canonical_flow(flow),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def workspace_strict_dag_enabled(workspace: Any) -> bool:
    raw_settings = getattr(workspace, "settings", None)
    features = raw_settings.get("features") if isinstance(raw_settings, dict) else None
    return bool(
        isinstance(features, dict)
        and features.get("flow_v3_dag_authoritative") is True
    )


def _schema_version(flow: Mapping[str, Any]) -> int:
    raw = flow.get("schema_version")
    if isinstance(raw, bool):
        return 0
    try:
        return int(raw or 0)
    except (OverflowError, TypeError, ValueError):
        return 0


def execution_runtime_mode(input_ref: Any) -> RuntimeMode | None:
    if not isinstance(input_ref, Mapping):
        return None
    execution = input_ref.get("execution")
    if not isinstance(execution, Mapping):
        return None
    value = execution.get("runtime_mode")
    return value if isinstance(value, str) and value in RUNTIME_MODES else None


def resolve_flow_execution(
    flow: Any,
    workspace: Any = None,
    *,
    pinned_runtime_mode: str | None = None,
) -> FlowExecutionResolution:
    """Resolve the actual walker and strictness for one immutable Flow.

    ``pinned_runtime_mode`` is accepted only from a server-owned Run execution
    envelope.  It keeps an accepted Run stable if the Workspace feature gate
    changes before its worker starts.
    """

    if pinned_runtime_mode in RUNTIME_MODES:
        return FlowExecutionResolution(
            runtime_mode=cast(RuntimeMode, pinned_runtime_mode),
            reason="pinned_run_execution_contract",
        )

    try:
        canonical = canonical_flow(flow)
    except ValueError:
        return FlowExecutionResolution(
            runtime_mode="sequential_legacy",
            reason="invalid_flow_shape_fails_to_legacy",
        )

    schema_version = _schema_version(canonical)
    nodes = canonical.get("nodes")
    nodes = nodes if isinstance(nodes, list) else []
    strict = bool(
        schema_version >= 3
        and canonical.get("io_mode") == "strict"
        and workspace_strict_dag_enabled(workspace)
    )
    if strict:
        return FlowExecutionResolution(
            runtime_mode="dag_strict",
            reason="flow_v3_strict_workspace_authoritative",
        )

    has_control_node = bool(
        schema_version >= 2
        and any(
            isinstance(node, Mapping) and node.get("kind") in CONTROL_KINDS
            for node in nodes
        )
    )
    if has_control_node:
        return FlowExecutionResolution(
            runtime_mode="dag_overlay",
            reason="control_node_requires_compatibility_dag",
        )

    return FlowExecutionResolution(
        runtime_mode="sequential_legacy",
        reason="legacy_or_task_only_flow",
    )


def resolve_run_flow_execution(
    run: Any,
    system: Any,
    workspace: Any = None,
) -> FlowExecutionResolution:
    """Resolve a Run from its snapshot, falling back only for legacy rows."""

    snapshot = getattr(run, "flow_snapshot", None)
    has_snapshot = isinstance(snapshot, dict)
    flow = snapshot if has_snapshot else getattr(system, "flow_definition", None)
    pinned_mode = (
        execution_runtime_mode(getattr(run, "input_ref", None))
        if has_snapshot
        else None
    )
    return resolve_flow_execution(
        flow,
        workspace,
        pinned_runtime_mode=pinned_mode,
    )
