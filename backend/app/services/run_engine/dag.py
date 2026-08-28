"""DAG walker for canonical Flows authored in the Orchestration editor.

Extends the sequential walker (``engine.execute_run``) to the richer
vocabulary introduced by FlowSerializer v2:

* ``source`` / ``sink``              — explicit I/O anchors
* ``task``                           — Skill invocation (delegated to
                                       :func:`engine._execute_task_node`)
* ``decision``                       — branch on condition DSL
                                       (:mod:`condition`)
* ``fork`` / ``join``                — parallel fan-out / fan-in
* ``retry``                          — retry wrapper around a Skill
* ``subflow``                        — nested execution of another System
* ``hitl``                           — pause the run, await operator
                                       ``accept`` / ``reject`` on a Decision
* ``loop``                           — iterate a Skill over a context list
* ``agent_loop``                     — bounded think → gate → act → observe loop

The walker is a Kahn-style ready queue: a node becomes ready once every
incoming edge has been "delivered". Fan-out is materialised by firing
:func:`asyncio.gather` on the ready set on each tick.

HITL pauses persist the walker state (``node_outputs``, ``done`` set,
``pending_counts``, ``ctx_snapshot``) into ``Run.checkpoints`` so the
``POST /runs/:id/resume`` endpoint can rehydrate and continue without
re-executing completed nodes.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace
from app.services.context_bindings import ContextBindingError, context_in_workspace
from app.services.flow_node_kind import flow_node_kind
from app.services.flow_skill_binding import resolve_flow_skill_binding
from app.services.membrane.enforcement import (
    EgressDisposition,
    MembraneEnforcementError,
    decide_egress,
    persist_provenance_artifact,
)
from app.services.membrane.spec import resolve_membrane_spec
from app.services.outcome.derive import derive_outcome
from app.services.system_catalog_bindings import (
    ResolvedSystemCatalogBindings,
    SystemCatalogBindingError,
    resolve_run_system_catalog_bindings,
)

from .condition import ConditionError
from .condition import evaluate as evaluate_condition
from .condition import validate as validate_condition
from .debug_contract import DebugContractError, normalize_debug_config
from .engine import (
    _attach_authoritative_membrane,
    _build_initial_ctx,
    _evaluate_run_capability,
    _execute_task_node,
    _fail,
    _finalize_run,
    _load_adaptive_policy,
    _load_control_policy,
    _log_decision,
    _record_capability_block,
    _record_capability_shadow,
    _runtime_valves_blocked,
    _snapshot_run_flow,
    execute_run,
)
from .events import bus as event_bus
from .execution_contract import (
    NON_PUBLISHED_EXECUTION_SURFACES,
    resolve_flow_execution,
    resolve_run_flow_execution,
    workspace_strict_dag_enabled,
)
from .run_contracts import (
    RuntimeContractError,
    decision_input_error,
    unbound_decision_inputs,
    validate_node_invocation_output,
    validate_node_output,
    validate_sink_output,
    validation_mode,
)
from .variable_pool import (
    VariablePool,
    VariableResolutionError,
    apply_inputs_map,
    apply_outputs_map,
    resolve_selector,
    selector_segments,
)

logger = get_logger(__name__)


def _system_for_run(db: DBSession, run: Run) -> Optional[System]:
    """Resolve a Run's System without ever crossing its workspace boundary."""

    return (
        db.query(System)
        .filter(
            System.id == run.system_id,
            System.workspace_id == run.workspace_id,
        )
        .first()
    )


def resolve_hitl_decision_for_run(
    db: DBSession,
    *,
    run: Run,
    decision_id: str,
    lock: bool = False,
) -> Optional[Decision]:
    """Resolve a Decision owned by this Run or any scoped descendant.

    Nested in-process subflows propagate the deepest child's Decision to each
    ancestor.  Requiring only the immediate child breaks A -> B -> C, while a
    lineage walk remains fail-closed on workspace drift, missing parents and
    cycles.
    """

    decision_query = db.query(Decision).filter(
        Decision.id == decision_id,
        Decision.scope == "run",
        or_(
            Decision.workspace_id == run.workspace_id,
            Decision.workspace_id.is_(None),
        ),
    )
    if lock:
        decision_query = decision_query.with_for_update()
    decision = decision_query.first()
    if decision is None or not decision.target_id:
        return None
    current = (
        db.query(Run)
        .filter(
            Run.id == decision.target_id,
            Run.workspace_id == run.workspace_id,
        )
        .first()
    )
    visited: Set[str] = set()
    while current is not None and current.id not in visited:
        if current.id == run.id:
            return decision
        visited.add(current.id)
        if not current.parent_run_id:
            return None
        current = (
            db.query(Run)
            .filter(
                Run.id == current.parent_run_id,
                Run.workspace_id == run.workspace_id,
            )
            .first()
        )
    return None


def subflow_celery_enabled(system: System) -> bool:
    """True only when both the deployment and System explicitly opt in."""
    features = ((system.settings or {}).get("features") or {}) if isinstance(system.settings, dict) else {}
    return bool(settings.enable_subflow_celery and features.get("subflow_celery") is True)


def delegation_key(parent_id: str, node_id: str, iteration: Any = 0, branch: str = "default") -> str:
    raw = f"{parent_id}\0{node_id}\0{iteration}\0{branch}".encode()
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Public dispatch helper
# ---------------------------------------------------------------------------
def _workspace_strict_dag_enabled(workspace: Optional[Workspace]) -> bool:
    """Compatibility wrapper for callers that imported the old helper."""

    return workspace_strict_dag_enabled(workspace)


def should_use_dag(system: System, workspace: Optional[Workspace] = None) -> bool:
    """Return True when ``system.flow_definition`` is a v2+ DAG with real
    control nodes. Accepts ``schema_version >= 2`` (v2 *and* the v3
    variable-membrane shape — the typed-port / ``VariableRef`` extensions
    are additive and parse identically here). v1 / legacy / empty flows
    fall through to the sequential walker so behaviour is unchanged for
    pre-C6 Systems. A v3 strict task-only graph routes to this walker only
    when its Workspace explicitly enables ``features.flow_v3_dag_authoritative``;
    an absent/off flag preserves the sequential legacy path.
    """
    return resolve_flow_execution(
        getattr(system, "flow_definition", None),
        workspace,
    ).uses_dag


# ---------------------------------------------------------------------------
# Graph model
# ---------------------------------------------------------------------------
@dataclass
class DagNode:
    id: str
    type: str
    kind: str
    label: Optional[str]
    config: Dict[str, Any]
    skill_slug: Optional[str]
    data: Dict[str, Any]


@dataclass
class DagEdge:
    source: str
    target: str
    kind: str  # 'data' | 'control' | 'branch'
    branch_label: Optional[str]
    from_port: Optional[str]
    to_port: Optional[str]


@dataclass
class DagGraph:
    nodes: Dict[str, DagNode]
    edges: List[DagEdge]
    io_mode: str = "overlay"
    variable_namespaces: Set[str] = field(default_factory=set)
    strict_authoritative: bool = False
    out_edges: Dict[str, List[DagEdge]] = field(default_factory=dict)
    in_edges: Dict[str, List[DagEdge]] = field(default_factory=dict)

    @classmethod
    def from_flow_definition(cls, flow: Dict[str, Any]) -> "DagGraph":
        raw_nodes = flow.get("nodes") or []
        raw_edges = flow.get("edges") or []
        nodes: Dict[str, DagNode] = {}
        for n in raw_nodes:
            if not isinstance(n, dict):
                continue
            nid = str(n.get("id") or "").strip()
            if not nid:
                continue
            kind = flow_node_kind(n)
            data = n.get("data") or {}
            config = n.get("config") or {}
            skill_slug = resolve_flow_skill_binding(n).skill_slug
            nodes[nid] = DagNode(
                id=nid,
                type=str(n.get("type") or ""),
                kind=str(kind),
                label=(n.get("label") or data.get("title") or None),
                config=dict(config) if isinstance(config, dict) else {},
                skill_slug=skill_slug,
                data=dict(data) if isinstance(data, dict) else {},
            )

        edges: List[DagEdge] = []
        for e in raw_edges:
            if not isinstance(e, dict):
                continue
            src = str(e.get("from") or e.get("source") or "").strip()
            dst = str(e.get("to") or e.get("target") or "").strip()
            if not src or not dst or src not in nodes or dst not in nodes:
                continue
            edges.append(
                DagEdge(
                    source=src,
                    target=dst,
                    kind=str(e.get("kind") or "data"),
                    branch_label=e.get("branch_label") or e.get("label") or None,
                    from_port=e.get("from_port") or None,
                    to_port=e.get("to_port") or None,
                )
            )

        raw_namespaces = flow.get("variable_namespaces") or []
        graph = cls(
            nodes=nodes,
            edges=edges,
            io_mode="strict" if flow.get("io_mode") == "strict" else "overlay",
            variable_namespaces={
                str(item)
                for item in raw_namespaces
                if isinstance(item, str) and item.strip()
            }
            if isinstance(raw_namespaces, list)
            else set(),
        )
        for nid in nodes:
            graph.out_edges[nid] = []
            graph.in_edges[nid] = []
        for edge in edges:
            graph.out_edges[edge.source].append(edge)
            graph.in_edges[edge.target].append(edge)
        return graph

    def roots(self) -> List[str]:
        return [nid for nid, ins in self.in_edges.items() if not ins]


_SKILL_EXECUTING_NODE_KINDS = frozenset({"task", "retry", "loop", "agent_loop"})


def validate_graph_skill_bindings(
    graph: DagGraph,
    catalog_bindings: ResolvedSystemCatalogBindings,
) -> None:
    """Prove every executable node is part of the resolved System contract.

    The in-memory skill registry is an implementation mechanism, not an
    authority source.  A flow snapshot can outlive (or be edited independently
    from) ``System.skill_ids``; accepting its free-form ``skill_slug`` would
    otherwise let task, retry and loop nodes invoke a catalog entry which the
    workspace/System resolver did not authorise.

    Skill-less authoring stubs and legacy pass-through nodes remain valid.  A
    node that *does* name a skill must match one, and only one, visible Skill
    already returned by ``resolve_run_system_catalog_bindings``.
    """

    bound_by_slug: Dict[str, int] = {}
    for skill in catalog_bindings.skills:
        slug = skill.slug
        if isinstance(slug, str):
            bound_by_slug[slug] = bound_by_slug.get(slug, 0) + 1

    for node in graph.nodes.values():
        if node.kind not in _SKILL_EXECUTING_NODE_KINDS:
            continue
        slug = node.skill_slug
        if slug is None or slug == "":
            # Portless/legacy non-skill nodes are intentional pass-throughs.
            continue
        field = f"flow_definition.nodes.{node.id}.config.skill_slug"
        if not isinstance(slug, str) or not slug.strip():
            raise SystemCatalogBindingError(
                "Executable DAG node has an invalid Skill slug",
                code="flow_skill_binding_invalid",
                field=field,
            )
        matches = bound_by_slug.get(slug, 0)
        if matches == 0:
            raise SystemCatalogBindingError(
                "Executable DAG node Skill is not bound to the System",
                code="flow_skill_not_bound",
                field=field,
            )
        if matches != 1:
            raise SystemCatalogBindingError(
                "Executable DAG node Skill binding is ambiguous",
                code="flow_skill_binding_ambiguous",
                field=field,
            )
        if node.kind == "agent_loop":
            allowlist = (node.config or {}).get("skill_allowlist") or []
            if not isinstance(allowlist, list):
                continue
            for item in allowlist:
                extra = str(item or "").strip()
                if not extra:
                    continue
                extra_field = f"flow_definition.nodes.{node.id}.config.skill_allowlist"
                extra_matches = bound_by_slug.get(extra, 0)
                if extra_matches == 0:
                    raise SystemCatalogBindingError(
                        "AgentLoop allowlist Skill is not bound to the System",
                        code="flow_skill_not_bound",
                        field=extra_field,
                    )
                if extra_matches != 1:
                    raise SystemCatalogBindingError(
                        "AgentLoop allowlist Skill binding is ambiguous",
                        code="flow_skill_binding_ambiguous",
                        field=extra_field,
                    )


# ---------------------------------------------------------------------------
# Walker state
# ---------------------------------------------------------------------------
@dataclass
class WalkerState:
    """Serialisable DAG walker state — persisted at every HITL pause."""

    # Node outputs are arbitrary JSON, not necessarily objects.  In
    # particular, published JSON Schemas may accept ``false``, ``0`` or an
    # empty string as the complete result of a node.
    node_outputs: Dict[str, Any] = field(default_factory=dict)
    done: Set[str] = field(default_factory=set)
    pending_counts: Dict[str, int] = field(default_factory=dict)
    # Edges that a decision / fork declared inactive — consumed by the
    # dependency-count ticker so downstream nodes can still schedule.
    dead_edges: Set[Tuple[str, str, Optional[str]]] = field(default_factory=set)
    ctx: Dict[str, Any] = field(default_factory=dict)
    invocation_ids: List[str] = field(default_factory=list)
    start_monotonic: float = 0.0
    accumulated_ms: float = 0.0
    total_cost: float = 0.0

    # P1 — typed variable pool. Seeded at run start with the reserved
    # namespaces (run / system / workspace) and grown by ``apply_outputs_map``
    # as nodes settle, so downstream ``inputs_map`` selectors can read it.
    # Serialised in ``to_payload`` so HITL / debug resume rehydrates it.
    pool: VariablePool = field(default_factory=VariablePool)

    # Debugger state (C8). ``debug_mode`` is one of:
    #   * None         → no debugger, walker runs freely.
    #   * "step"       → pause after every non-source/sink node.
    #   * "breakpoints"→ pause only when a settled node id is in
    #                     ``breakpoints``.
    # ``breakpoints`` is shared across modes — operators can preset
    # breakpoints even when starting in ``step`` mode so Continue jumps
    # directly to the next flag.
    debug_mode: Optional[str] = None
    breakpoints: Set[str] = field(default_factory=set)

    # P4 follow-up — subflow resume bookkeeping. Maps a ``subflow`` node id to
    # the child ``Run.id`` it delegated to. Persisted in ``to_payload`` so that
    # when a child run pauses for HITL (gating the parent), a parent resume can
    # find the *existing* child and resume / reuse it instead of spawning a
    # duplicate. Empty dict for flows without subflows; absent in pre-P4
    # checkpoints (``from_payload`` tolerates the omission).
    subflow_children: Dict[str, str] = field(default_factory=dict)
    # A synthetic terminal Membrane HOLD is not a graph node.  Persist its
    # approval bit so resume can publish the already-computed output without
    # re-running a task or asking for approval a second time.
    membrane_egress_approved: bool = False

    def to_payload(self) -> Dict[str, Any]:
        return {
            "node_outputs": self.node_outputs,
            "done": sorted(self.done),
            "pending_counts": self.pending_counts,
            "dead_edges": [list(e) for e in self.dead_edges],
            "ctx": self.ctx,
            "invocation_ids": list(self.invocation_ids),
            "accumulated_ms": self.accumulated_ms,
            "total_cost": self.total_cost,
            "debug_mode": self.debug_mode,
            "breakpoints": sorted(self.breakpoints),
            "pool": self.pool.to_dict(),
            "subflow_children": dict(self.subflow_children),
            "membrane_egress_approved": self.membrane_egress_approved,
        }

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "WalkerState":
        state = cls()
        state.node_outputs = dict(payload.get("node_outputs") or {})
        state.done = set(payload.get("done") or [])
        state.pending_counts = dict(payload.get("pending_counts") or {})
        state.dead_edges = {
            tuple(e) if isinstance(e, list) else e for e in (payload.get("dead_edges") or [])
        }
        state.ctx = dict(payload.get("ctx") or {})
        state.invocation_ids = list(payload.get("invocation_ids") or [])
        state.accumulated_ms = float(payload.get("accumulated_ms") or 0.0)
        state.total_cost = float(payload.get("total_cost") or 0.0)
        state.debug_mode = payload.get("debug_mode") or None
        state.breakpoints = set(payload.get("breakpoints") or [])
        state.pool = VariablePool.from_dict(payload.get("pool") or {})
        # Backward-compatible: pre-P4-follow-up checkpoints have no
        # ``subflow_children`` key — default to an empty mapping so old
        # paused runs still rehydrate and resume.
        state.subflow_children = dict(payload.get("subflow_children") or {})
        state.membrane_egress_approved = bool(payload.get("membrane_egress_approved"))
        return state


class ContractIngressSelectionError(ValueError):
    """The server-owned ingress evidence does not match the frozen graph."""


def _contract_ingress_selection(
    run: Run,
    graph: DagGraph,
) -> tuple[str, list[str]] | None:
    """Resolve the one ingress source authorised for a normalized Run.

    Legacy Runs have neither of the two server-owned evidence blocks and keep
    their historical all-roots behaviour.  Once either block is present, the
    pair must be complete and agree with the immutable execution contract,
    execution surface and graph before any node can run.
    """

    input_ref = run.input_ref if isinstance(run.input_ref, dict) else {}
    raw_ingress = input_ref.get("_ingress")
    ingress_evidence = raw_ingress if isinstance(raw_ingress, dict) else None
    raw_execution = input_ref.get("execution")
    execution = raw_execution if isinstance(raw_execution, dict) else {}
    execution_ingress_id = execution.get("ingress_id")
    selection_version = execution.get("ingress_selection_version")
    has_selection_evidence = (
        raw_ingress is not None
        or execution_ingress_id is not None
        or selection_version is not None
    )
    if not has_selection_evidence:
        return None
    if ingress_evidence is None or selection_version != 1:
        raise ContractIngressSelectionError("contract_ingress_evidence_incomplete")

    ingress_id = ingress_evidence.get("ingress_id")
    source_node_id = ingress_evidence.get("source_node_id")
    kind = ingress_evidence.get("kind")
    if not all(isinstance(value, str) and value.strip() for value in (ingress_id, source_node_id, kind)):
        raise ContractIngressSelectionError("contract_ingress_evidence_invalid")
    if execution_ingress_id != ingress_id:
        raise ContractIngressSelectionError("contract_ingress_identity_mismatch")
    expected_surface = (
        run.execution_surface
        if run.execution_surface in NON_PUBLISHED_EXECUTION_SURFACES
        else f"published_{kind}"
    )
    if run.execution_surface != expected_surface:
        raise ContractIngressSelectionError("contract_ingress_surface_mismatch")
    if execution.get("execution_surface") != run.execution_surface:
        raise ContractIngressSelectionError("contract_ingress_execution_surface_mismatch")
    if run.execution_surface not in NON_PUBLISHED_EXECUTION_SURFACES and (
        execution.get("published_flow_version_id") != run.published_flow_version_id
    ):
        raise ContractIngressSelectionError("contract_ingress_version_mismatch")

    contract = run.execution_contract if isinstance(run.execution_contract, dict) else None
    raw_contract_ingresses = contract.get("ingresses") if contract is not None else None
    if not isinstance(raw_contract_ingresses, list):
        raise ContractIngressSelectionError("contract_ingress_contract_missing")
    contract_ingresses = [
        item for item in raw_contract_ingresses if isinstance(item, dict)
    ]
    matches = [item for item in contract_ingresses if item.get("ingress_id") == ingress_id]
    if len(matches) != 1:
        raise ContractIngressSelectionError("contract_ingress_contract_mismatch")
    selected_contract = matches[0]
    if (
        selected_contract.get("source_node_id") != source_node_id
        or selected_contract.get("kind") != kind
    ):
        raise ContractIngressSelectionError("contract_ingress_contract_mismatch")

    selected_node = graph.nodes.get(source_node_id)
    if selected_node is None or selected_node.kind != "source" or graph.in_edges[source_node_id]:
        raise ContractIngressSelectionError("contract_ingress_source_invalid")

    inactive_sources: list[str] = []
    for item in contract_ingresses:
        candidate = item.get("source_node_id")
        if not isinstance(candidate, str) or not candidate or candidate == source_node_id:
            continue
        node = graph.nodes.get(candidate)
        if node is None or node.kind != "source" or graph.in_edges[candidate]:
            raise ContractIngressSelectionError("contract_ingress_source_invalid")
        if candidate not in inactive_sources:
            inactive_sources.append(candidate)
    return source_node_id, sorted(inactive_sources)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
async def execute_run_dag(run_id: str) -> Dict[str, Any]:
    """Walk a v2 DAG flow, executing nodes as their dependencies settle."""
    db: DBSession = SessionLocal()
    run: Optional[Run] = None
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            logger.warning("dag_engine: unknown run_id", run_id=run_id)
            return {"error": "run_not_found"}

        system = _system_for_run(db, run)
        if not system:
            return _fail(db, run, "system_not_found")

        workspace = (
            db.query(Workspace).filter(Workspace.id == (system.workspace_id or run.workspace_id)).first()
            if (system.workspace_id or run.workspace_id)
            else None
        )
        if run.workspace_id and workspace is None:
            return _fail(
                db,
                run,
                "system_catalog_binding_invalid:workspace_not_found",
            )
        try:
            catalog_bindings = resolve_run_system_catalog_bindings(
                db,
                workspace=workspace,
                system=system,
                run=run,
            )
        except SystemCatalogBindingError as exc:
            return _fail(db, run, f"system_catalog_binding_invalid:{exc.code}")
        if run.capability_id is None:
            run.capability_id = system.capability_id

        # Prefer a pre-existing immutable snapshot (replay/retry); a new Run
        # falls back to the current System graph and snapshots it below.
        flow = (
            run.flow_snapshot
            if isinstance(run.flow_snapshot, dict)
            else system.flow_definition or {}
        )
        graph = DagGraph.from_flow_definition(flow)
        graph.strict_authoritative = resolve_run_flow_execution(
            run,
            system,
            workspace,
        ).strict_authoritative
        if not graph.nodes:
            return _fail(db, run, "empty_flow")
        try:
            ingress_selection = _contract_ingress_selection(run, graph)
        except ContractIngressSelectionError as exc:
            return _fail(db, run, str(exc))
        try:
            validate_graph_skill_bindings(graph, catalog_bindings)
        except SystemCatalogBindingError as exc:
            return _fail(db, run, f"system_catalog_binding_invalid:{exc.code}")

        capability = catalog_bindings.capability
        control = _load_control_policy(db, system)
        adaptive = _load_adaptive_policy(db, system)

        run_gate = _evaluate_run_capability(control, system)
        if not run_gate.allowed:
            _record_capability_block(
                db,
                run,
                system_id=system.id,
                violations=list(run_gate.violations),
            )
            return _fail(db, run, "membrane_capability_block:system.engine.run")
        if run_gate.would_block and run_gate.mode == "shadow":
            _record_capability_shadow(
                db,
                run,
                system_id=system.id,
                violations=list(run_gate.violations),
                action="system.engine.run",
            )

        first_start = run.status == "pending"
        run.status = "running"
        run.started_at = run.started_at or datetime.utcnow()
        _snapshot_run_flow(
            db,
            run,
            system,
            first_start=first_start,
            control=control,
        )
        db.commit()

        initial_ctx = _build_initial_ctx(db, run, system, capability)
        _attach_authoritative_membrane(initial_ctx, control)
        state = WalkerState(
            ctx=initial_ctx,
            pending_counts={nid: len(graph.in_edges[nid]) for nid in graph.nodes},
            start_monotonic=time.monotonic(),
        )
        _seed_pool(db, state.pool, run, system, workspace=workspace)
        selected_ingress_source: str | None = None
        inactive_ingress_sources: list[str] = []
        if ingress_selection is not None:
            selected_ingress_source, inactive_ingress_sources = ingress_selection
            for node_id in inactive_ingress_sources:
                _settle_node(
                    graph,
                    state,
                    node_id,
                    {"output": {}, "skipped_reason": "ingress_not_selected"},
                )
        # Pick up optional debugger config from the run input. Shape:
        #   run.input_ref["_debug"] = {"mode": "step"|"breakpoints",
        #                              "breakpoints": ["n1", "n3"]}
        debug_cfg = (run.input_ref or {}).get("_debug") if isinstance(run.input_ref, dict) else None
        if isinstance(debug_cfg, dict):
            mode = debug_cfg.get("mode")
            if mode in ("step", "breakpoints"):
                state.debug_mode = mode
            bps = debug_cfg.get("breakpoints") or []
            if isinstance(bps, list):
                state.breakpoints = {str(b) for b in bps if b}
        _append_checkpoint(
            db,
            run,
            {
                "kind": "run_start",
                "nodes": len(graph.nodes),
                "debug_mode": state.debug_mode,
                "breakpoints": sorted(state.breakpoints) if state.breakpoints else [],
                **(
                    {
                        "ingress_source_node_id": selected_ingress_source,
                        "inactive_ingress_source_node_ids": inactive_ingress_sources,
                    }
                    if selected_ingress_source is not None
                    else {}
                ),
            },
        )

        return await _walk(
            db,
            run,
            graph,
            state,
            system=system,
            capability=capability,
            control=control,
            adaptive=adaptive,
        )
    except asyncio.CancelledError:
        if run is not None:
            _terminate_interrupted_run(db, run, status="cancelled", error="execution_cancelled")
        raise
    except Exception as exc:  # noqa: BLE001 - a Run must never remain live on engine failure.
        logger.exception("dag_engine: unhandled execution failure", run_id=run_id, error=str(exc))
        if run is not None:
            try:
                db.rollback()
                run = db.query(Run).filter(Run.id == run_id).first() or run
                _terminate_interrupted_run(
                    db,
                    run,
                    status="failed",
                    error=f"dag_execution_error:{str(exc)[:400]}",
                )
                return {"id": run.id, "status": "failed", "error": run.error}
            except Exception as terminal_exc:  # noqa: BLE001
                logger.exception(
                    "dag_engine: failed to persist terminal state",
                    run_id=run_id,
                    error=str(terminal_exc),
                )
                try:
                    event_bus.close(run_id)
                except Exception:  # noqa: BLE001
                    pass
                return {"id": run_id, "status": "failed", "error": str(exc)[:400]}
        return {"error": "run_not_found"}
    finally:
        db.close()


async def resume_run_dag(
    run_id: str,
    *,
    decision_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Resume a run paused at a ``hitl`` node.

    The frontend is expected to have called
    :func:`app.services.decisions.state_machine.accept` or ``reject`` before
    invoking this endpoint; we read the final Decision status and inject it
    into the walker ctx (``hitl_decision``, ``hitl_approved``) so downstream
    decision nodes can branch on it.
    """
    db: DBSession = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            return {"error": "run_not_found"}
        if run.status != "hitl_pending":
            return {"error": "run_not_paused", "status": run.status}

        checkpoints = list(run.checkpoints or [])
        pause_cp = next(
            (cp for cp in reversed(checkpoints) if cp.get("kind") == "hitl_pause"),
            None,
        )
        if not pause_cp:
            return _fail(db, run, "no_hitl_checkpoint")

        system = _system_for_run(db, run)
        if not system:
            return _fail(db, run, "system_not_found")

        workspace = (
            db.query(Workspace).filter(Workspace.id == (system.workspace_id or run.workspace_id)).first()
            if (system.workspace_id or run.workspace_id)
            else None
        )
        if run.workspace_id and workspace is None:
            return _fail(
                db,
                run,
                "system_catalog_binding_invalid:workspace_not_found",
            )
        try:
            catalog_bindings = resolve_run_system_catalog_bindings(
                db,
                workspace=workspace,
                system=system,
                run=run,
            )
        except SystemCatalogBindingError as exc:
            return _fail(db, run, f"system_catalog_binding_invalid:{exc.code}")
        if run.capability_id is None:
            run.capability_id = system.capability_id

        # HITL resumes obey the immutable execution contract.
        flow = (
            run.flow_snapshot
            if isinstance(run.flow_snapshot, dict)
            else system.flow_definition or {}
        )
        graph = DagGraph.from_flow_definition(flow)
        graph.strict_authoritative = resolve_run_flow_execution(
            run,
            system,
            workspace,
        ).strict_authoritative
        try:
            validate_graph_skill_bindings(graph, catalog_bindings)
        except SystemCatalogBindingError as exc:
            return _fail(db, run, f"system_catalog_binding_invalid:{exc.code}")
        state = WalkerState.from_payload(pause_cp.get("state") or {})
        state.start_monotonic = time.monotonic()

        capability = catalog_bindings.capability
        control = _load_control_policy(db, system)
        adaptive = _load_adaptive_policy(db, system)

        run_gate = _evaluate_run_capability(control, system)
        if not run_gate.allowed:
            _record_capability_block(
                db,
                run,
                system_id=system.id,
                violations=list(run_gate.violations),
            )
            return _fail(db, run, "membrane_capability_block:system.engine.run")
        if run_gate.would_block and run_gate.mode == "shadow":
            _record_capability_shadow(
                db,
                run,
                system_id=system.id,
                violations=list(run_gate.violations),
                action="system.engine.run",
            )

        hitl_node_id = pause_cp.get("node_id")
        paused_node = graph.nodes.get(hitl_node_id) if hitl_node_id else None
        # A subflow node pauses the parent when its *child* run hits a HITL.
        # That pause must NOT be settled here as if it were a plain ``hitl``
        # node: the operator's verdict belongs to the child run. Instead we
        # leave the subflow node un-settled (its pending count is still 0 and
        # it is not in ``done``) so the walker re-reaches it; the resume-aware
        # ``_run_subflow`` then drives the recorded child to completion rather
        # than spawning a duplicate child Run.
        is_subflow_pause = paused_node is not None and paused_node.kind == "subflow"
        is_agent_loop_pause = paused_node is not None and paused_node.kind == "agent_loop"

        dec = None
        checkpoint_decision_id = pause_cp.get("decision_id")
        target_decision_id = checkpoint_decision_id
        if decision_id and decision_id != checkpoint_decision_id:
            return {
                "id": run.id,
                "status": "hitl_pending",
                "awaiting_decision": checkpoint_decision_id,
                "error": "hitl_decision_mismatch",
            }
        if target_decision_id:
            dec = resolve_hitl_decision_for_run(
                db,
                run=run,
                decision_id=target_decision_id,
            )
        approved = bool(dec and dec.status in ("accepted", "applied"))
        rejected = bool(dec and dec.status == "rejected")

        # A durable pause is an authority boundary. Internal re-entry (for
        # example while resolving an any/race subflow join) must never settle
        # the HITL node while its Decision is still proposed or missing.
        if not approved and not rejected:
            return {
                "id": run.id,
                "status": "hitl_pending",
                "awaiting_decision": target_decision_id,
            }

        is_membrane_egress = bool(pause_cp.get("membrane_egress"))
        if is_membrane_egress:
            if rejected:
                return _fail(db, run, "membrane_egress_rejected")
            if not approved:
                # A proposed/missing decision is not authority to publish.
                return {
                    "id": run.id,
                    "status": "hitl_pending",
                    "awaiting_decision": target_decision_id,
                }
            state.membrane_egress_approved = True

        if is_membrane_egress:
            # Synthetic gate: every real graph node is already settled.
            pass
        elif is_subflow_pause:
            # Nothing to settle for the parent — the child resume (driven by
            # ``_run_subflow`` on re-entry) owns the decision and its own ctx.
            pass
        elif is_agent_loop_pause:
            # Intra-loop HumanGate: the agent_loop node is still unfinished.
            # Re-entry continues turns from ``ctx._agent_loop`` + this verdict.
            state.ctx["hitl_approved"] = approved
            state.ctx["hitl_decision"] = dec.status if dec else None
            loops = dict(state.ctx.get("_agent_loop") or {})
            loop_state = dict(loops.get(hitl_node_id) or {})
            loop_state["human"] = {
                "approved": approved,
                "rejected": rejected,
                "decision_id": target_decision_id,
                "decision_status": dec.status if dec else None,
            }
            loops[hitl_node_id] = loop_state
            state.ctx["_agent_loop"] = loops
        elif hitl_node_id and hitl_node_id in graph.nodes:
            hitl_output = {
                "approved": approved,
                "rejected": rejected,
                "decision_id": target_decision_id,
                "decision_status": dec.status if dec else None,
            }
            state.ctx["hitl_approved"] = approved
            state.ctx["hitl_decision"] = dec.status if dec else None
            # Reuse the single settlement path: HITL resume must publish the
            # node namespace and outputs_map exactly like a normal completion.
            _settle_node(graph, state, hitl_node_id, {"output": hitl_output})

        # Durable SystemMemory → variable pool ``memory.*`` so the delivered
        # node sees transactions collected while the gate was waiting.
        from app.services.run_engine.inbox import reinject_memory_into_state  # noqa: WPS433

        memory_payload = reinject_memory_into_state(db, run, state)

        run.status = "running"
        db.commit()
        _append_checkpoint(
            db,
            run,
            {
                "kind": "hitl_resume",
                "node_id": hitl_node_id,
                "decision_status": dec.status if dec else None,
                **(
                    {
                        "memory_version": memory_payload.get("version"),
                        "memory_event_count": memory_payload.get("event_count"),
                    }
                    if memory_payload
                    else {}
                ),
            },
        )

        return await _walk(
            db,
            run,
            graph,
            state,
            system=system,
            capability=capability,
            control=control,
            adaptive=adaptive,
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Core walker
# ---------------------------------------------------------------------------
async def _walk(
    db: DBSession,
    run: Run,
    graph: DagGraph,
    state: WalkerState,
    *,
    system: System,
    capability: Optional[Capability],
    control,
    adaptive,
) -> Dict[str, Any]:
    """Drive the ready queue until the DAG settles or a HITL pause fires."""
    # Seed ready queue with all nodes whose pending count is 0 and that
    # haven't been executed yet. On resume this naturally picks up the
    # successors of the HITL node.
    ready = [
        nid
        for nid, pending in state.pending_counts.items()
        if pending == 0 and nid not in state.done
    ]

    while ready:
        # Fan out independent tasks in parallel; hitl / subflow are
        # inherently sequential so we isolate them to preserve ordering
        # guarantees.
        parallel: List[str] = []
        serial: List[str] = []
        for nid in ready:
            kind = graph.nodes[nid].kind
            serial_kind = kind in ("hitl", "loop", "agent_loop") or (
                kind == "subflow" and not subflow_celery_enabled(system)
            )
            (serial if serial_kind else parallel).append(nid)

        if parallel:
            results = await asyncio.gather(
                *[
                    _execute_node(db, run, graph.nodes[nid], graph, state, control=control)
                    for nid in parallel
                ],
                return_exceptions=False,
            )
            for nid, outcome in zip(parallel, results):
                outcome = _apply_runtime_output_contract(
                    db,
                    run,
                    graph.nodes[nid],
                    outcome,
                )
                if outcome.get("membrane_blocked"):
                    return _fail(db, run, run.error or "membrane_policy_block")
                if outcome.get("terminal_error"):
                    run.output_ref = {}
                    return _fail(db, run, str(outcome["terminal_error"]))
                _settle_node(graph, state, nid, outcome)
                if outcome.get("pause"):
                    if outcome.get("wait_subflow"):
                        return _emit_subflow_pause(db, run, state, outcome)
                    return _emit_hitl_pause(db, run, state, outcome)
                if _should_debug_pause(graph, state, nid):
                    return _emit_debug_pause(db, run, state, nid)

        for nid in serial:
            outcome = await _execute_node(db, run, graph.nodes[nid], graph, state, control=control)
            outcome = _apply_runtime_output_contract(
                db,
                run,
                graph.nodes[nid],
                outcome,
            )
            if outcome.get("membrane_blocked"):
                return _fail(db, run, run.error or "membrane_policy_block")
            if outcome.get("terminal_error"):
                run.output_ref = {}
                return _fail(db, run, str(outcome["terminal_error"]))
            _settle_node(graph, state, nid, outcome)
            if outcome.get("pause"):
                if outcome.get("wait_subflow"):
                    return _emit_subflow_pause(db, run, state, outcome)
                return _emit_hitl_pause(db, run, state, outcome)
            if _should_debug_pause(graph, state, nid):
                return _emit_debug_pause(db, run, state, nid)

        # Adaptive hard-stop across the whole DAG.
        if adaptive and adaptive.enabled and _dag_should_stop(adaptive, state):
            _log_decision(
                db,
                workspace_id=run.workspace_id,
                scope="system",
                target_id=system.id,
                kind="adaptive_stop",
                rationale={"total_cost": state.total_cost},
            )
            break

        ready = [
            nid
            for nid, pending in state.pending_counts.items()
            if pending == 0 and nid not in state.done
        ]

    # Normal termination — build the final output and finalise.
    duration_ms = state.accumulated_ms + (time.monotonic() - state.start_monotonic) * 1000
    invocations = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    last_output = _collect_terminal_output(graph, state)

    membrane_result = _enforce_terminal_membrane(
        db,
        run,
        state,
        system=system,
        capability=capability,
        control=control,
        invocations=invocations,
        duration_ms=duration_ms,
        last_output=last_output,
    )
    if membrane_result is not None:
        return membrane_result

    summary = _finalize_run(
        db,
        run,
        system=system,
        capability=capability,
        control=control,
        invocations=invocations,
        duration_ms=duration_ms,
        last_output=last_output,
    )
    _append_checkpoint(
        db,
        run,
        {
            "kind": "run_end",
            "status": summary["status"],
            "nodes_executed": len(state.done),
        },
    )
    # Let live SSE subscribers know no further events will arrive for
    # this run. Replayers (connecting after the fact) still get the full
    # checkpoint list from the DB.
    try:
        event_bus.close(run.id)
    except Exception:  # noqa: BLE001
        pass
    logger.info(
        "dag_engine: done",
        run_id=run.id,
        status=summary["status"],
        nodes=len(graph.nodes),
        executed=len(state.done),
        duration_ms=duration_ms,
    )
    return summary


def _enforce_terminal_membrane(
    db: DBSession,
    run: Run,
    state: WalkerState,
    *,
    system: System,
    capability: Optional[Capability],
    control,
    invocations: List[SkillInvocation],
    duration_ms: float,
    last_output: Any,
) -> Optional[Dict[str, Any]]:
    """Apply the authoritative v2 egress/provenance contract before publish.

    The graph is already fully settled at this point, but ``Run.output_ref`` is
    intentionally still empty.  HOLD persists a synthetic HITL checkpoint;
    resume rehydrates the walker and skips directly back here.
    """

    try:
        spec = resolve_membrane_spec(control=control)
    except Exception as exc:  # noqa: BLE001 - malformed v2 cannot fail open.
        raw = (
            (getattr(control, "extra", None) or {}).get("membrane_spec")
            if control is not None and isinstance(getattr(control, "extra", None), dict)
            else None
        )
        if isinstance(raw, dict) and int(raw.get("version") or 0) >= 2:
            return _fail(db, run, f"membrane_spec_invalid:{str(exc)[:240]}")
        return None
    if not spec.authoritative or spec.version < 2:
        return None

    derived = derive_outcome(
        invocations=invocations,
        capability=capability,
        control_hitl_threshold=None,
        duration_ms=duration_ms,
    )
    citations = _collect_membrane_citations(
        {
            "output": last_output,
            "pool": state.pool.to_dict(),
            "nodes": state.node_outputs,
        }
    )
    decision = decide_egress(
        spec,
        confidence=derived.confidence,
        citations=citations,
        legacy_review_required=False,
    )
    _append_checkpoint(
        db,
        run,
        {
            "kind": "membrane_egress_evaluated",
            "mode": decision.mode,
            "disposition": decision.disposition.value,
            "would_disposition": decision.would_disposition.value,
            "reasons": list(decision.reasons),
            "citation_count": len(citations),
            "confidence": derived.confidence,
        },
    )

    if decision.disposition is EgressDisposition.BLOCK:
        _log_decision(
            db,
            workspace_id=run.workspace_id,
            scope="run",
            target_id=run.id,
            kind="policy_block",
            rationale={
                "run_id": run.id,
                "facet": "outbound",
                "reasons": list(decision.reasons),
                "mode": decision.mode,
            },
        )
        run.output_ref = {}
        db.commit()
        return _fail(db, run, f"membrane_egress_block:{','.join(decision.reasons)}")

    if (
        decision.disposition is EgressDisposition.HOLD
        and not state.membrane_egress_approved
    ):
        approval = _log_decision(
            db,
            workspace_id=run.workspace_id,
            scope="run",
            target_id=run.id,
            kind="hitl_approval",
            rationale={
                "run_id": run.id,
                "facet": "outbound",
                "reasons": list(decision.reasons),
                "confidence": derived.confidence,
                "citation_count": len(citations),
            },
            status="proposed",
            title="Membrane egress approval",
        )
        if approval is not None:
            from app.services.run_engine.gate_ttl import stamp_decision_ttl  # noqa: WPS433
            from app.services.run_engine.inbox import extract_correlation_key  # noqa: WPS433

            # Membrane HOLD reuses the same TTL machinery as explicit hitl nodes.
            # Optional override via ControlPolicy.extra["membrane_gate_ttl"].
            ttl_cfg: Dict[str, Any] = {}
            if control is not None and isinstance(getattr(control, "extra", None), dict):
                raw_ttl = control.extra.get("membrane_gate_ttl")
                if isinstance(raw_ttl, dict):
                    ttl_cfg = raw_ttl
            stamp_decision_ttl(approval, ttl_cfg)
            corr = extract_correlation_key(
                run.input_ref if isinstance(run.input_ref, dict) else {}
            )
            if corr:
                rationale = dict(approval.rationale or {})
                rationale["correlation_key"] = corr
                approval.rationale = rationale
            db.commit()
        run.output_ref = {}
        db.commit()
        return _emit_hitl_pause(
            db,
            run,
            state,
            {
                "pause": True,
                "membrane_egress": True,
                "node_id": "__membrane_egress__",
                "decision_id": approval.id if approval else None,
                "prompt": "Approval required before this result can be published",
                "expires_at": approval.expires_at.isoformat() if approval and approval.expires_at else None,
                "expiry_action": approval.expiry_action if approval else None,
                "correlation_key": (approval.rationale or {}).get("correlation_key") if approval else None,
            },
        )

    try:
        artifact = persist_provenance_artifact(
            spec,
            workspace_id=str(run.workspace_id or system.workspace_id or ""),
            system_id=system.id,
            run_id=run.id,
            payload={
                "identity": {
                    "workspace_id": run.workspace_id or system.workspace_id,
                    "system_id": system.id,
                    "run_id": run.id,
                    "capability_id": system.capability_id,
                },
                "egress": {
                    "disposition": decision.disposition.value,
                    "reasons": list(decision.reasons),
                    "confidence": derived.confidence,
                    "citations": citations,
                },
                "output": last_output,
            },
        )
    except MembraneEnforcementError as exc:
        run.output_ref = {}
        db.commit()
        return _fail(db, run, str(exc))

    if artifact is not None:
        evidence = artifact.to_dict()
        # Record the immutable URI/SHA both in the final output contract and
        # in the invocation ledger that emitted the terminal audit event.
        # The terminal business output has already passed its frozen JSON
        # Schema.  Provenance is server metadata and must never be injected
        # afterwards (a closed ``additionalProperties: false`` schema would
        # otherwise be violated).  The typed checkpoint and invocation trace
        # below remain the canonical evidence ledger.
        audit_invocation = next(
            (item for item in reversed(invocations) if item.skill_slug == "audit_log_v1"),
            invocations[-1] if invocations else None,
        )
        if audit_invocation is not None:
            trace = dict(audit_invocation.trace or {})
            trace["membrane_provenance"] = evidence
            audit_invocation.trace = trace
        _append_checkpoint(
            db,
            run,
            {
                "kind": "membrane_provenance",
                "uri": artifact.uri,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
            },
        )
    return None


def _collect_membrane_citations(value: Any) -> List[Any]:
    """Find typed ``citations`` fields in terminal output and VariablePool."""

    found: List[Any] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            citations = item.get("citations")
            if isinstance(citations, list):
                found.extend(citations)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    deduped: List[Any] = []
    seen: Set[str] = set()
    for citation in found:
        try:
            key = repr(sorted(citation.items())) if isinstance(citation, dict) else repr(citation)
        except Exception:  # noqa: BLE001 - a citation is still evidence.
            key = repr(citation)
        if key not in seen:
            seen.add(key)
            deduped.append(citation)
    return deduped


def _settle_node(
    graph: DagGraph, state: WalkerState, node_id: str, outcome: Dict[str, Any]
) -> None:
    """Record the node output, mark as done, decrement successor pending
    counts (skipping edges declared dead by a decision / fork)."""
    if outcome.get("pause"):
        return
    state.done.add(node_id)
    node_output = outcome["output"] if "output" in outcome else {}
    state.node_outputs[node_id] = node_output
    # P1 — publish this node's output into the typed pool. We always expose
    # the node's own output under its node id (so downstream selectors of the
    # form ``{node_id, path}`` resolve) and, when the node declared an
    # ``outputs_map``, also write the mapped namespaced slices. Both are no-ops
    # for downstream behaviour on legacy flows (nothing reads the pool unless
    # a node has an ``inputs_map``).
    node = graph.nodes.get(node_id)
    if node is not None:
        pool_output = node_output if isinstance(node_output, dict) else {"value": node_output}
        state.pool.set_namespace(node_id, pool_output)
        apply_outputs_map(node.config, node_output, state.pool)
    inactive = set(outcome.get("inactive_branches") or [])
    propagate_dead = outcome.get("skipped_reason") in {
        "all_inputs_dead",
        "ingress_not_selected",
    }
    prunes_to_branch = "active_branch_label" in outcome
    active_branch = outcome.get("active_branch_label")
    for edge in graph.out_edges.get(node_id, []):
        label = edge.branch_label or ""
        edge_is_dead = (
            propagate_dead
            or (
                prunes_to_branch
                and not (
                    edge.kind == "branch"
                    and edge.branch_label == active_branch
                )
            )
            or (label and label in inactive)
        )
        if edge_is_dead:
            state.dead_edges.add((edge.source, edge.target, edge.branch_label))
            # Kill the successor entirely by propagating the dead edge
            # through its pending count: we still need to decrement so the
            # counter reaches 0, otherwise the branch's tail would dangle
            # forever. Downstream nodes whose only inputs come from dead
            # edges therefore become "ready" but execute as no-ops (the
            # `_execute_node` dispatcher checks edge activity).
            state.pending_counts[edge.target] = max(0, state.pending_counts.get(edge.target, 0) - 1)
            continue
        state.pending_counts[edge.target] = max(0, state.pending_counts.get(edge.target, 0) - 1)


def _apply_runtime_output_contract(
    db: DBSession,
    run: Run,
    node: DagNode,
    outcome: Dict[str, Any],
) -> Dict[str, Any]:
    """Observe or enforce the immutable schema pinned on the accepted Run."""

    if outcome.get("pause") or outcome.get("skipped_reason"):
        return outcome
    mode = validation_mode(run)
    if mode is None:
        return outcome
    payload = outcome["output"] if "output" in outcome else {}
    violation: RuntimeContractError | None = validate_node_output(
        run,
        node_id=node.id,
        payload=payload,
    )
    if violation is None and node.kind == "sink":
        violation = validate_sink_output(
            run,
            node_id=node.id,
            payload=payload,
        )
    if violation is None:
        return outcome

    checkpoint = violation.checkpoint()
    checkpoint["validation_mode"] = mode
    checkpoint["disposition"] = "failed" if mode == "enforce" else "observed"
    _append_checkpoint(db, run, checkpoint)
    if mode == "observe":
        return outcome
    return {
        **outcome,
        "output": {},
        "terminal_error": violation.terminal_error(),
    }


def _should_debug_pause(graph: DagGraph, state: WalkerState, node_id: str) -> bool:
    """Decide whether to pause the walker right after ``node_id`` settled.

    Source and sink nodes are elided from step mode because they carry
    no user-observable behaviour — stepping over them would just burn
    two clicks on every run. Breakpoints always fire, even on source /
    sink, so power users can pause at the very first / last event.
    """
    if state.debug_mode == "breakpoints" and node_id in state.breakpoints:
        return True
    if state.debug_mode == "step":
        if node_id in state.breakpoints:
            return True
        kind = graph.nodes[node_id].kind if node_id in graph.nodes else None
        if kind in ("source", "sink"):
            return False
        return True
    return False


def _emit_debug_pause(db: DBSession, run: Run, state: WalkerState, node_id: str) -> Dict[str, Any]:
    """Freeze the walker for debugger inspection and flip Run status.

    The payload schema mirrors :func:`_emit_hitl_pause` so the SSE /
    resume machinery can treat both pause types uniformly. The key
    differences: no Decision row is created and the resume path is the
    dedicated ``resume_run_dag_debug`` which understands step vs
    continue semantics.
    """
    terminal = _terminal_run_before_pause(db, run)
    if terminal is not None:
        return terminal
    state.accumulated_ms += (time.monotonic() - state.start_monotonic) * 1000
    # Per-node ctx snapshot — only the fields that changed since the
    # last pause would be ideal, but walker ctx is small enough (RAG
    # payloads, not entire documents) that shipping the whole thing is
    # fine and saves the client a fetch.
    checkpoint = {
        "kind": "debug_pause",
        "t": datetime.utcnow().isoformat(),
        "node_id": node_id,
        "debug_mode": state.debug_mode,
        "breakpoints": sorted(state.breakpoints),
        "ctx_snapshot": _sanitize(state.ctx),
        "last_output": (
            state.node_outputs[node_id] if node_id in state.node_outputs else {}
        ),
        "state": state.to_payload(),
    }
    # Status and resume checkpoint are one authoritative transition.  A
    # coordinator cancellation cannot land between two commits and then be
    # resurrected as a debugger pause.
    run.checkpoints = [*(run.checkpoints or []), checkpoint]
    run.status = "debug_pending"
    db.commit()
    try:
        event_bus.publish(run.id, checkpoint)
    except Exception:  # noqa: BLE001 - persisted state is authoritative.
        pass
    try:
        event_bus.close(run.id)
    except Exception:  # noqa: BLE001
        pass
    logger.info(
        "dag_engine: debug pause",
        run_id=run.id,
        node_id=node_id,
        mode=state.debug_mode,
    )
    return {
        "id": run.id,
        "status": "debug_pending",
        "node_id": node_id,
        "debug_mode": state.debug_mode,
    }


async def resume_run_dag_debug(
    run_id: str, *, action: str, breakpoints: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Resume a Run paused by the step debugger.

    ``action`` controls what happens after resume:
        * ``"step"``       → run until the next non-source/sink node, pause again.
        * ``"continue"``   → run until the next breakpoint or natural end.
        * ``"stop"``       → finalise the run as cancelled here.

    ``breakpoints`` optionally replaces the current breakpoint set
    before resume so operators can toggle flags from the UI without
    scheduling a brand new run.
    """
    db: DBSession = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            return {"error": "run_not_found"}
        if run.status != "debug_pending":
            return {"error": "run_not_paused", "status": run.status}

        checkpoints = list(run.checkpoints or [])
        pause_cp = next(
            (cp for cp in reversed(checkpoints) if cp.get("kind") == "debug_pause"),
            None,
        )
        if not pause_cp:
            return _fail(db, run, "no_debug_checkpoint")

        system = _system_for_run(db, run)
        if not system:
            return _fail(db, run, "system_not_found")

        workspace = (
            db.query(Workspace).filter(Workspace.id == (system.workspace_id or run.workspace_id)).first()
            if (system.workspace_id or run.workspace_id)
            else None
        )

        # Debug resumes obey the immutable graph captured at first execution.
        flow = (
            run.flow_snapshot
            if isinstance(run.flow_snapshot, dict)
            else system.flow_definition or {}
        )
        graph = DagGraph.from_flow_definition(flow)
        graph.strict_authoritative = resolve_run_flow_execution(
            run,
            system,
            workspace,
        ).strict_authoritative
        state = WalkerState.from_payload(pause_cp.get("state") or {})
        state.start_monotonic = time.monotonic()

        try:
            normalized_debug = normalize_debug_config(
                {
                    "mode": "step",
                    "breakpoints": (
                        breakpoints
                        if breakpoints is not None
                        else list(state.breakpoints)
                    ),
                }
            )
        except DebugContractError as exc:
            return _fail(db, run, f"{exc.code.lower()}:{exc.path}")
        state.breakpoints = set(normalized_debug["breakpoints"])

        if action == "continue":
            state.debug_mode = "breakpoints" if state.breakpoints else None
        elif action == "step":
            state.debug_mode = "step"
        elif action == "stop":
            _terminate_interrupted_run(
                db,
                run,
                status="cancelled",
                error="debugger_stopped",
            )
            return {
                "id": run.id,
                "status": run.status,
                "error": run.error,
            }
        else:
            return {"error": "invalid_action", "action": action}

        if run.workspace_id and workspace is None:
            return _fail(
                db,
                run,
                "system_catalog_binding_invalid:workspace_not_found",
            )
        try:
            catalog_bindings = resolve_run_system_catalog_bindings(
                db,
                workspace=workspace,
                system=system,
                run=run,
            )
        except SystemCatalogBindingError as exc:
            return _fail(db, run, f"system_catalog_binding_invalid:{exc.code}")
        if run.capability_id is None:
            run.capability_id = system.capability_id
        try:
            validate_graph_skill_bindings(graph, catalog_bindings)
        except SystemCatalogBindingError as exc:
            return _fail(db, run, f"system_catalog_binding_invalid:{exc.code}")

        capability = catalog_bindings.capability
        control = _load_control_policy(db, system)
        adaptive = _load_adaptive_policy(db, system)

        run_gate = _evaluate_run_capability(control, system)
        if not run_gate.allowed:
            _record_capability_block(
                db,
                run,
                system_id=system.id,
                violations=list(run_gate.violations),
            )
            return _fail(db, run, "membrane_capability_block:system.engine.run")
        if run_gate.would_block and run_gate.mode == "shadow":
            _record_capability_shadow(
                db,
                run,
                system_id=system.id,
                violations=list(run_gate.violations),
                action="system.engine.run",
            )

        run.status = "running"
        db.commit()
        _append_checkpoint(
            db,
            run,
            {
                "kind": "debug_resume",
                "node_id": pause_cp.get("node_id"),
                "action": action,
                "debug_mode": state.debug_mode,
                "breakpoints": sorted(state.breakpoints),
            },
        )
        return await _walk(
            db,
            run,
            graph,
            state,
            system=system,
            capability=capability,
            control=control,
            adaptive=adaptive,
        )
    finally:
        db.close()


def _emit_hitl_pause(
    db: DBSession, run: Run, state: WalkerState, outcome: Dict[str, Any]
) -> Dict[str, Any]:
    """Persist the walker state as a HITL checkpoint and flip Run status."""
    terminal = _terminal_run_before_pause(db, run)
    if terminal is not None:
        return terminal
    state.accumulated_ms += (time.monotonic() - state.start_monotonic) * 1000
    checkpoint = {
        "kind": "hitl_pause",
        "t": datetime.utcnow().isoformat(),
        "node_id": outcome.get("node_id"),
        "decision_id": outcome.get("decision_id"),
        "prompt": outcome.get("prompt"),
        "state": state.to_payload(),
        "membrane_egress": bool(outcome.get("membrane_egress")),
        "expires_at": outcome.get("expires_at"),
        "expiry_action": outcome.get("expiry_action"),
        "correlation_key": outcome.get("correlation_key"),
    }
    if checkpoint["membrane_egress"]:
        # The full walker state is durable resume data and may contain the
        # held result.  Persist it, but never mirror it onto the live SSE bus.
        # The public event carries only the approval envelope.
        run.checkpoints = [*(run.checkpoints or []), checkpoint]
        run.status = "hitl_pending"
        run.output_ref = {}
        db.commit()
        public_checkpoint = {key: value for key, value in checkpoint.items() if key != "state"}
        public_checkpoint["result_held"] = True
        try:
            event_bus.publish(run.id, public_checkpoint)
        except Exception:  # noqa: BLE001 - persisted state is authoritative.
            pass
    else:
        # The checkpoint and status form one transaction. Publishing happens
        # only after that durable state is visible.
        run.checkpoints = [*(run.checkpoints or []), checkpoint]
        run.status = "hitl_pending"
        db.commit()
        try:
            event_bus.publish(run.id, checkpoint)
        except Exception:  # noqa: BLE001 - persisted state is authoritative.
            pass
    # Close the current live stream — resume will spin up a fresh run
    # that SSE clients can re-subscribe to on reconnect.
    try:
        event_bus.close(run.id)
    except Exception:  # noqa: BLE001
        pass
    logger.info(
        "dag_engine: hitl pause",
        run_id=run.id,
        node_id=outcome.get("node_id"),
        decision_id=outcome.get("decision_id"),
    )
    return {
        "id": run.id,
        "status": "hitl_pending",
        "awaiting_decision": outcome.get("decision_id"),
        "prompt": outcome.get("prompt"),
    }


def _emit_subflow_pause(
    db: DBSession, run: Run, state: WalkerState, outcome: Dict[str, Any]
) -> Dict[str, Any]:
    """Persist a broker wait separately from a human approval pause."""
    terminal = _terminal_run_before_pause(db, run)
    if terminal is not None:
        return terminal
    state.accumulated_ms += (time.monotonic() - state.start_monotonic) * 1000
    checkpoint = {
        "kind": "subflow_wait",
        "t": datetime.utcnow().isoformat(),
        "node_id": outcome.get("node_id"),
        "child_run_id": outcome.get("child_run_id"),
        "state": state.to_payload(),
    }
    # Checkpoint and status are one transaction. A very fast child callback
    # must never observe the checkpoint while the parent still says running.
    run.checkpoints = [*(run.checkpoints or []), checkpoint]
    run.status = "waiting_subflows"
    db.commit()
    # Fast path: publish newly committed outbox rows only after the parent
    # checkpoint/status are visible.  A crash or broker outage here is safe;
    # the dedicated reconciler owns the durable retry.
    try:
        from .dispatch_outbox import reconcile_dispatch_outbox

        reconcile_dispatch_outbox(
            batch_size=max(50, min(len(run.waiting_subflows or {}), 1000)),
            lease_seconds=settings.p4_maintenance_lease_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - persisted outbox is authoritative.
        logger.warning(
            "dag_engine: immediate subflow outbox reconciliation deferred",
            run_id=run.id,
            error_type=type(exc).__name__,
        )
    try:
        event_bus.publish(run.id, checkpoint)
    except Exception:  # noqa: BLE001
        pass
    try:
        event_bus.close(run.id)
    except Exception:  # noqa: BLE001
        pass
    return {
        "id": run.id,
        "status": "waiting_subflows",
        "child_run_id": outcome.get("child_run_id"),
    }


def _terminal_run_before_pause(db: DBSession, run: Run) -> Optional[Dict[str, Any]]:
    """Serialize durable pauses with coordinator-owned terminal states.

    A race/any coordinator can cancel a branch while that branch is still
    unwinding into HITL, debugger or nested-subflow pause.  Re-read the Run
    under a row lock before publishing the pause so a late worker can never
    resurrect an authoritative terminal state.
    """
    locked = (
        db.query(Run)
        .filter(Run.id == run.id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is None or locked.status not in {"completed", "failed", "cancelled"}:
        return None
    return {
        "id": locked.id,
        "status": locked.status,
        "error": locked.error,
    }


# ---------------------------------------------------------------------------
# Phase 2 — authoritative asset -> collection binding (flag-gated)
# ---------------------------------------------------------------------------
def _asset_node_ids(graph: DagGraph) -> Set[str]:
    """Node ids whose kind is ``asset`` (declarative collection sources)."""
    return {nid for nid, node in graph.nodes.items() if node.kind == "asset"}


def _selector_targets_asset(selector: Any, asset_ids: Set[str]) -> bool:
    """True when ``selector`` is a VariableRef/dot-path whose HEAD is an asset."""
    segs = selector_segments(selector)
    return bool(segs) and segs[0] in asset_ids


def _effective_inputs_map(node: DagNode, graph: DagGraph) -> Optional[Dict[str, Any]]:
    """Return the node's ``inputs_map`` with asset-sourced refs gated by the flag.

    GATE SEAM (Phase 2 ``p2-binding``): a ``VariableRef`` whose SOURCE node has
    ``kind == 'asset'`` is an authoritative collection binding and is honoured
    ONLY when ``settings.flow_asset_binding_authoritative`` is ON. When OFF the
    ref is dropped so the consuming retrieve node falls back to implicit
    workspace resolution — byte-identical to Phase 1 (whose retrieve nodes carry
    the SAME non-asset inputs_map, so dropping the lone asset ref reduces the map
    to its Phase-1 shape). Non-asset VariableRefs are NEVER gated.

    Returns ``None`` when there is no usable map so the caller stays on the
    pre-P1 flat-merge path (``maps_present`` False).
    """
    raw = node.config.get("inputs_map") if isinstance(node.config, dict) else None
    if not isinstance(raw, dict) or not raw:
        return None
    if settings.flow_asset_binding_authoritative:
        return raw
    asset_ids = _asset_node_ids(graph)
    if not asset_ids:
        return raw
    filtered = {
        port: selector
        for port, selector in raw.items()
        if not _selector_targets_asset(selector, asset_ids)
    }
    return filtered or None


def _apply_retrieval_node_scope(node: DagNode, node_input: Dict[str, Any]) -> None:
    """Project a Builder-authored Retrieval scope into canonical RAG input.

    Graph configuration is authoritative: caller input and upstream nodes cannot
    widen the selected collections or documents. ``dag_validator`` rejects the
    same malformed shapes during authoring; these checks keep historical or
    directly-created Runs fail-closed at the execution boundary.
    """

    config = node.config if isinstance(node.config, dict) else {}
    raw_collections = config.get("collection_slugs")
    raw_documents = config.get("document_refs")
    if raw_collections is None and raw_documents is None:
        # This marker is graph-owned. An ingress/upstream payload cannot arm it.
        node_input.pop("authoritative_document_scope", None)
        return
    identity = f"{node.type or ''} {node.skill_slug or ''}".lower()
    declared_category = str(config.get("skill_category") or "").strip().lower()
    if declared_category != "retrieval" and not any(
        token in identity
        for token in ("retriev", "semantic_search", "rag_search", "vector_search", "lookup")
    ):
        raise ValueError("retrieval_scope_node_invalid")
    if (
        not isinstance(raw_collections, list)
        or len(raw_collections) > 32
        or any(
            not isinstance(item, str) or not item.strip() or item != item.strip()
            for item in raw_collections
        )
        or len(set(raw_collections)) != len(raw_collections)
    ):
        raise ValueError("retrieval_collections_invalid")
    if not isinstance(raw_documents, list) or len(raw_documents) > 1000:
        raise ValueError("retrieval_documents_invalid")

    allowed = set(raw_collections)
    document_ids: list[str] = []
    document_refs_by_collection: dict[str, list[str]] = {}
    seen_refs: set[tuple[str, str]] = set()
    for raw in raw_documents:
        if not isinstance(raw, dict):
            raise ValueError("retrieval_documents_invalid")
        collection = raw.get("collection_slug")
        document_id = raw.get("document_id")
        if (
            not isinstance(collection, str)
            or collection not in allowed
            or not isinstance(document_id, str)
            or not document_id.strip()
            or document_id != document_id.strip()
            or (collection, document_id) in seen_refs
        ):
            raise ValueError("retrieval_documents_invalid")
        seen_refs.add((collection, document_id))
        document_refs_by_collection.setdefault(collection, []).append(document_id)
        if document_id not in document_ids:
            document_ids.append(document_id)

    if raw_collections:
        node_input["authoritative_collections"] = list(raw_collections)
    else:
        node_input.pop("authoritative_collections", None)
    filters = (
        dict(node_input.get("retrieval_filters"))
        if isinstance(node_input.get("retrieval_filters"), dict)
        else {}
    )
    if document_ids:
        filters["document_id"] = document_ids
        node_input["authoritative_document_scope"] = True
        # Keep the pair relationship intact. A flat document-id union applied
        # to every collection creates a cartesian scope and can admit an
        # identically-named document from a collection where it was not chosen.
        node_input["authoritative_document_refs"] = document_refs_by_collection
    else:
        filters.pop("document_id", None)
        node_input.pop("authoritative_document_scope", None)
        node_input.pop("authoritative_document_refs", None)
    if filters:
        node_input["retrieval_filters"] = filters
    else:
        node_input.pop("retrieval_filters", None)


_RECIPE_SKILL_SLUG = "python_recipe_v1"
# ``sources`` for the same reason the transform nodes carry it: which tables a
# script may read is a property of the graph, not of the payload that triggered
# it. A recipe reads only what its author pinned, and an ingress cannot add a
# table to that list.
_RECIPE_PARAM_KEYS = (
    "code",
    "requirements_text",
    "index_url",
    "extra_index_urls",
    "timeout_s",
    "sources",
)


_SQL_TRANSFORM_SKILL_SLUG = "sql_transform_v1"
_POLARS_TRANSFORM_SKILL_SLUG = "polars_transform_v1"
_DBT_TRANSFORM_SKILL_SLUG = "dbt_transform_v1"
# Every param a transform node may carry, whatever its engine: the block is
# projected whole so each wrapper reads only the keys it knows.
_TRANSFORM_PARAM_KEYS = (
    "sql",
    "code",
    "models",
    "tests_yml",
    "output_model",
    "requirements_text",
    "timeout_s",
    "output_name",
    "sources",
)
_TRANSFORM_SKILL_SLUGS = frozenset(
    {
        _SQL_TRANSFORM_SKILL_SLUG,
        _POLARS_TRANSFORM_SKILL_SLUG,
        _DBT_TRANSFORM_SKILL_SLUG,
    }
)

_ML_TRAIN_SKILL_SLUG = "ml_train_sklearn_v1"
# A training node is configured, not scripted: what makes it graph-owned is the
# same argument as for a statement — the target of a model must not be something
# an ingress payload can rewrite between two runs.
_TRAIN_PARAM_KEYS = (
    "task",
    "target",
    "features",
    "algo",
    "knobs",
    "test_size",
    "cross_validation",
    "model_name",
    "sources",
)
_TRAIN_SKILL_SLUGS = frozenset({_ML_TRAIN_SKILL_SLUG})

_ML_PREDICT_SKILL_SLUG = "ml_predict_v1"
_ML_SCORE_SKILL_SLUG = "ml_batch_score_v1"
# Which model answers is the graph's decision for the same reason a target is:
# a payload that could redirect a scoring node to another model would make the
# published Flow's output mean something different without the Flow changing.
# One block for both serving nodes, as with the three transform engines: the keys
# are a union, and `output_name` is simply unread by the single-record node.
_PREDICT_PARAM_KEYS = (
    "model_id",
    "model_slug",
    "pinned_version",
    "output_name",
    "explain",
    "sources",
)
_PREDICT_SKILL_SLUGS = frozenset({_ML_PREDICT_SKILL_SLUG, _ML_SCORE_SKILL_SLUG})

# The reserved keys a node's graph configuration travels under. Written once as
# data because the invariant is the same for all of them, and repeating it is how
# one eventually stops being stripped on the other nodes.
_GRAPH_OWNED_BLOCKS: tuple[tuple[str, frozenset, tuple[str, ...]], ...] = (
    ("_recipe", frozenset({_RECIPE_SKILL_SLUG}), _RECIPE_PARAM_KEYS),
    ("_transform", _TRANSFORM_SKILL_SLUGS, _TRANSFORM_PARAM_KEYS),
    ("_train", _TRAIN_SKILL_SLUGS, _TRAIN_PARAM_KEYS),
    ("_predict", _PREDICT_SKILL_SLUGS, _PREDICT_PARAM_KEYS),
)


def _passthrough_without_recipe(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Task failure envelopes pass upstream data through; the graph-owned
    ``_recipe``, ``_transform``, ``_train`` and ``_predict`` blocks are
    configuration (the full script, statement text, training spec or model
    reference), not data, so they never ride a ``_error``/``_status`` envelope
    into run outputs."""

    passthrough = dict(data or {})
    for key, _slugs, _params in _GRAPH_OWNED_BLOCKS:
        passthrough.pop(key, None)
    return passthrough


def _apply_graph_owned_config(
    node: DagNode,
    node_input: Dict[str, Any],
    *,
    key: str,
    slugs: frozenset,
    param_keys: tuple[str, ...],
) -> None:
    """Project one graph-owned configuration block into the skill input.

    The block is authoritative graph configuration: caller input and upstream
    nodes can never inject or alter the executable script, the statement or the
    training spec. On every other node the reserved key is stripped, so an
    ingress payload cannot smuggle one toward a downstream node that would read
    it.
    """

    if node.skill_slug not in slugs:
        node_input.pop(key, None)
        return
    config = node.config if isinstance(node.config, dict) else {}
    params = config.get("params") if isinstance(config.get("params"), dict) else {}
    node_input[key] = {
        **{name: params.get(name) for name in param_keys},
        "node_id": node.id,
    }
    # In strict mode the palette-params merge may also have seeded the raw config
    # keys as plain input defaults; drop them so the node's data inputs stay
    # data only.
    for name in param_keys:
        node_input.pop(name, None)


def _apply_recipe_node_config(node: DagNode, node_input: Dict[str, Any]) -> None:
    _apply_graph_owned_config(
        node,
        node_input,
        key="_recipe",
        slugs=frozenset({_RECIPE_SKILL_SLUG}),
        param_keys=_RECIPE_PARAM_KEYS,
    )


def _apply_transform_node_config(node: DagNode, node_input: Dict[str, Any]) -> None:
    _apply_graph_owned_config(
        node,
        node_input,
        key="_transform",
        slugs=_TRANSFORM_SKILL_SLUGS,
        param_keys=_TRANSFORM_PARAM_KEYS,
    )


def _apply_train_node_config(node: DagNode, node_input: Dict[str, Any]) -> None:
    _apply_graph_owned_config(
        node,
        node_input,
        key="_train",
        slugs=_TRAIN_SKILL_SLUGS,
        param_keys=_TRAIN_PARAM_KEYS,
    )


def _apply_predict_node_config(node: DagNode, node_input: Dict[str, Any]) -> None:
    _apply_graph_owned_config(
        node,
        node_input,
        key="_predict",
        slugs=_PREDICT_SKILL_SLUGS,
        param_keys=_PREDICT_PARAM_KEYS,
    )


# ---------------------------------------------------------------------------
# Per-node dispatcher
# ---------------------------------------------------------------------------
async def _execute_node(
    db: DBSession,
    run: Run,
    node: DagNode,
    graph: DagGraph,
    state: WalkerState,
    *,
    control,
) -> Dict[str, Any]:
    """Return ``{output, inactive_branches?, pause?, decision_id?, ...}``.

    Each handler returns a dict so the walker can uniformly settle the node
    or raise a pause.
    """
    _append_checkpoint(
        db,
        run,
        {
            "kind": "node_start",
            "t": datetime.utcnow().isoformat(),
            "node_id": node.id,
            "node_kind": node.kind,
            "label": node.label,
            "skill_slug": node.skill_slug,
        },
    )

    # Short-circuit: if every incoming edge was killed by an upstream
    # decision/fork, the node sits on a dead branch and must not fire
    # its handler. `_settle_node` already decremented the pending count
    # so the walker can still make progress downstream; we just refuse
    # to run the handler here. Without this guard, tasks on inactive
    # decision branches would execute with empty input — the exact
    # behaviour the comment in `_settle_node` promised *not* to happen.
    # We emit the matching `node_end` inline (skipping the shared
    # summary block) so the UI gets one clean skipped marker.
    in_edges = graph.in_edges.get(node.id, [])
    # Declarative ``asset`` sources are pass-throughs: their (data) edges never
    # gate whether a downstream node fires. When deciding if this node sits on a
    # fully-dead branch we therefore consider ONLY non-asset inbound edges —
    # otherwise a declarative ``asset -> retrieve`` edge would revive a lane a
    # decision just killed (breaking the single-active-lane pruning). A node fed
    # exclusively by asset edges has no gating edges and always runs.
    gating_edges = [
        e
        for e in in_edges
        if not (graph.nodes.get(e.source) is not None and graph.nodes[e.source].kind == "asset")
    ]
    if gating_edges and all(
        (e.source, e.target, e.branch_label) in state.dead_edges for e in gating_edges
    ):
        _append_checkpoint(
            db,
            run,
            {
                "kind": "node_end",
                "t": datetime.utcnow().isoformat(),
                "node_id": node.id,
                "node_kind": node.kind,
                "status": "skipped",
                "skipped_reason": "all_inputs_dead",
            },
        )
        return {"output": {}, "skipped_reason": "all_inputs_dead"}

    # Phase 2 gate (merge path): asset nodes are declarative pass-throughs whose
    # ``{collection: <slug>}`` output must only reach a consumer when the
    # authoritative-binding flag is ON. With the flag OFF we exclude asset data
    # edges from the predecessor merge so the collection never leaks into the
    # retrieve payload (nor the ctx) — implicit workspace resolution, iso Phase 1.
    merged_input = _merge_predecessor_outputs(
        graph,
        state,
        node.id,
        include_assets=settings.flow_asset_binding_authoritative,
    )
    # Expose the merged upstream output to the ctx so downstream decision
    # nodes can reference fields produced by any ancestor (e.g.
    # ``confidence`` from a task node).
    if merged_input:
        state.ctx.update({k: v for k, v in merged_input.items() if v is not None})

    # ``node`` is a real built-in namespace, but it is local to this handler.
    # Independent ready nodes execute concurrently, therefore it must never be
    # written into the shared pool where one task could observe another task's
    # scope.
    node_pool = state.pool.with_namespace(
        "node",
        {
            "id": node.id,
            "kind": node.kind,
            "label": node.label,
            "config": _without_secret_values(node.config),
        },
    )

    # P1 — resolve ``config.inputs_map`` selectors against the typed pool.
    # When the map is empty/absent ``node_input`` is the same object as
    # ``merged_input`` and ``maps_present`` is False, so every handler stays
    # byte-identical to the pre-P1 flat-merge path. Phase 2 gate (inputs_map
    # path): ``_effective_inputs_map`` drops asset-sourced VariableRefs when the
    # flag is OFF (see its docstring), so a retrieve node whose only asset ref is
    # ``collection`` reverts to its Phase-1 map shape.
    effective_map = _effective_inputs_map(node, graph)
    maps_present = bool(effective_map)
    strict = graph.strict_authoritative
    input_config = {
        "inputs_map": effective_map or {},
        "passthrough_inputs": node.config.get("passthrough_inputs") or [],
    }
    try:
        node_input = (
            apply_inputs_map(
                input_config,
                node_pool,
                merged_input,
                io_mode="strict" if strict else "overlay",
            )
            if maps_present or strict
            else merged_input
        )
    except VariableResolutionError as exc:
        _append_checkpoint(
            db,
            run,
            {
                "kind": "variable_resolution_error",
                "node_id": node.id,
                "port": exc.port,
                "selector": _sanitize(exc.selector),
            },
        )
        raise

    # Palette-dropped skill nodes carry their inspector-edited literals in
    # ``config.params`` but an empty ``inputs_map`` (the UI seeds it empty),
    # and in strict mode an empty map resolves to an empty payload. Merge the
    # params as defaults so an inspector edit reaches the skill; explicit
    # ``inputs_map`` selectors keep precedence (setdefault never clobbers).
    if node.kind == "task" and strict and node.skill_slug:
        config_params = (
            node.config.get("params") if isinstance(node.config, dict) else None
        )
        if isinstance(config_params, dict):
            for param_key, param_value in _without_secret_values(
                config_params
            ).items():
                node_input.setdefault(param_key, param_value)

    try:
        _apply_retrieval_node_scope(node, node_input)
    except ValueError as exc:
        _append_checkpoint(
            db,
            run,
            {
                "kind": "retrieval_scope_error",
                "node_id": node.id,
                "reason": str(exc),
            },
        )
        return {"output": {}, "terminal_error": str(exc)}

    for _block_key, _block_slugs, _block_params in _GRAPH_OWNED_BLOCKS:
        _apply_graph_owned_config(
            node,
            node_input,
            key=_block_key,
            slugs=_block_slugs,
            param_keys=_block_params,
        )

    invocations_before = len(state.invocation_ids)
    result: Dict[str, Any] = {}
    try:
        if node.kind == "source":
            output = dict(state.ctx.get("input") or run.input_ref or {})
            result = {"output": output}
            return result

        if node.kind == "sink":
            # A sink is the run's result collector. In strict mode a sink
            # without an explicit inputs_map/passthrough resolves to an empty
            # payload, which made ``_collect_terminal_output`` fall back to an
            # arbitrary "last done" node (``done`` is a set). Default to the
            # merged predecessor outputs so Run.output_ref is deterministic.
            # With one live predecessor and no explicit mapping, a sink is a
            # transparent collector.  Preserve primitive/falsy JSON outputs
            # exactly instead of coercing them through the object-only merge.
            live_predecessors = [
                edge
                for edge in graph.in_edges.get(node.id, [])
                if (edge.source, edge.target, edge.branch_label) not in state.dead_edges
                and edge.source in state.node_outputs
            ]
            if not maps_present and len(live_predecessors) == 1:
                result = {"output": state.node_outputs[live_predecessors[0].source]}
            else:
                result = {"output": node_input if node_input else merged_input}
            return result

        if node.kind == "task":
            result = await _run_task(
                db,
                run,
                node,
                state,
                control=control,
                upstream=node_input,
                resolved=maps_present or strict,
            )
            return result

        if node.kind == "decision":
            unbound = unbound_decision_inputs(
                branches=(node.config or {}).get("branches"),
                resolved_input=_decision_ctx(state, node_input, strict=strict),
            )
            enforced = bool(unbound) and validation_mode(run) == "enforce"
            if unbound:
                _append_checkpoint(
                    db,
                    run,
                    {
                        "kind": "decision_input_unbound",
                        "node_id": node.id,
                        "names": unbound,
                        "disposition": "failed" if enforced else "observed",
                    },
                )
            result = _run_decision(
                node,
                graph,
                state,
                node_input,
                pool=node_pool,
                strict=strict,
                unbound_inputs=unbound if enforced else None,
            )
            _append_checkpoint(db, run, _decision_resolution_checkpoint(node, result))
            return result

        if node.kind == "fork":
            result = _run_fork(node, graph, state, node_input)
            return result

        if node.kind == "join":
            result = _run_join(node, graph, state)
            return result

        if node.kind == "retry":
            result = await _run_retry(
                db,
                run,
                node,
                state,
                control=control,
                upstream=node_input,
                resolved=maps_present or strict,
            )
            return result

        if node.kind == "loop":
            result = await _run_loop(
                db,
                run,
                node,
                state,
                control=control,
                upstream=node_input,
                resolved=maps_present or strict,
                pool=node_pool,
            )
            return result

        if node.kind == "agent_loop":
            result = await _run_agent_loop(
                db,
                run,
                node,
                state,
                control=control,
                upstream=node_input,
            )
            return result

        if node.kind == "hitl":
            result = _run_hitl(db, run, node, state, control=control, upstream=node_input)
            return result

        if node.kind == "subflow":
            result = await _run_subflow(db, run, node, state, control=control, upstream=node_input)
            return result

        if node.kind == "asset":
            # Declarative source asset (Phase 1). A silent pass-through that
            # merely NAMES the collection it stands for — the walker does not
            # read it yet (retrieval keeps its implicit workspace resolution);
            # the graph edge becomes authoritative only in Phase 2. Read the
            # slug from ``config`` like the other handlers (cf. _run_decision).
            # No unknown-kind warning: an asset node is expected, not a mistake.
            collection_slug = (node.config or {}).get("collection_slug")
            result = {"output": {"collection": collection_slug}}
            return result

        # Unknown kind → treat as pass-through with a warning.
        logger.warning(
            "dag_engine: unknown node kind", run_id=run.id, node_id=node.id, kind=node.kind
        )
        result = {"output": node_input}
        return result
    finally:
        # Enrich node_end with whatever we learned during execution so
        # the SSE consumer can render informative terminal lines without
        # fetching /runs/:id for each event.
        summary = _summarise_node_execution(
            db,
            run,
            node,
            result,
            state,
            invocations_before,
            node_input=node_input if isinstance(node_input, dict) else None,
        )
        _append_checkpoint(
            db,
            run,
            {
                "kind": "node_end",
                "t": datetime.utcnow().isoformat(),
                "node_id": node.id,
                "node_kind": node.kind,
                **summary,
            },
        )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def _run_task(
    db: DBSession,
    run: Run,
    node: DagNode,
    state: WalkerState,
    *,
    control,
    upstream: Optional[Dict[str, Any]] = None,
    resolved: bool = False,
) -> Dict[str, Any]:
    slug = node.skill_slug
    if not slug:
        # Task with no bound skill is a frontend authoring stub; pass through
        # the merged upstream output so downstream nodes still receive data.
        return {"output": upstream or {}}
    last_output = upstream or {}
    # When the node declared an ``inputs_map`` the upstream has already been
    # resolved against the pool — pass it explicitly so the engine uses it
    # verbatim instead of re-deriving via ``_build_skill_input``.
    invocation = await _execute_task_node(
        db,
        run,
        state.ctx,
        slug,
        control=control,
        last_output=last_output,
        node_id=node.id,
        resolved_input=last_output if resolved else None,
        attempt_kind="task",
        attempt_index=1,
    )
    if invocation is None:
        # Blocked by allowed_skills — keep passthrough so the DAG can still
        # settle; the policy_block Decision is already persisted.
        return {
            "output": last_output,
            "membrane_blocked": bool(resolve_membrane_spec(control=control).enforcement_active),
        }
    state.invocation_ids.append(invocation.id)
    state.total_cost += invocation.cost or 0.0
    if _runtime_valves_blocked(db, run, control):
        return {"output": {}, "membrane_blocked": True}
    if invocation.status == "completed":
        return {
            "output": (
                invocation.output_ref if invocation.output_ref is not None else {}
            )
        }
    # On failure / skipped: pass through upstream data but preserve the error
    # in the ctx for downstream decision nodes.
    err_output = {
        **_passthrough_without_recipe(last_output),
        "_error": invocation.error,
        "_status": invocation.status,
    }
    return {"output": err_output}


def _decision_ctx(
    state: WalkerState,
    merged_input: Optional[Dict[str, Any]],
    *,
    strict: bool,
) -> Dict[str, Any]:
    """Names a Decision predicate can read.

    Strict conditions are evaluated from the node's typed payload; built-in and
    declared namespaces remain addressable through the pool. Overlay preserves
    the historical flat ctx merge.
    """

    return dict(merged_input or {}) if strict else {**state.ctx, **(merged_input or {})}


def _run_decision(
    node: DagNode,
    graph: DagGraph,
    state: WalkerState,
    merged_input: Dict[str, Any],
    *,
    pool: Optional[VariablePool] = None,
    strict: bool = False,
    unbound_inputs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Resolve one Decision route, failing closed on every ambiguous outcome.

    Every predicate is validated before the first one is evaluated, so an
    unsafe expression cannot hide behind an earlier match.  Runtime evaluation
    itself remains first-match and short-circuited.

    ``unbound_inputs`` are predicate names the caller proved the payload never
    bound. They resolve to null and would route the run on a comparison against
    nothing, so an enforcing contract refuses to route before evaluating.
    """
    config = node.config or {}
    branches = config.get("branches") or []
    default_label = str(config.get("default_branch") or "").strip()
    if unbound_inputs:
        violation = decision_input_error(node_id=node.id, unbound=unbound_inputs)
        return {
            "output": {
                "chosen_branch": None,
                "decision_resolution": "error",
                "evaluations": [],
            },
            "decision_resolution": "error",
            "terminal_error": violation.terminal_error(),
        }
    ctx_with_input = _decision_ctx(state, merged_input, strict=strict)

    branch_specs: List[Tuple[int, str, str]] = []
    evaluations: List[Dict[str, Any]] = []
    for index, branch in enumerate(branches):
        if not isinstance(branch, dict):
            continue
        label = str(branch.get("label") or "").strip()
        condition = str(branch.get("condition") or "").strip()
        branch_specs.append((index, label, condition))
        try:
            validate_condition(condition)
        except ConditionError as exc:
            condition_error = {
                **exc.to_dict(),
                "branch_index": index,
                "branch_label": label,
            }
            return {
                "output": {
                    "chosen_branch": None,
                    "decision_resolution": "error",
                    "evaluations": evaluations,
                },
                "decision_resolution": "error",
                "condition_error": condition_error,
                "terminal_error": f"decision_condition_error:{node.id}",
            }

    chosen: Optional[str] = None
    for position, (index, label, condition) in enumerate(branch_specs):
        if chosen is not None:
            evaluations.append(
                {
                    "label": label,
                    "branch_index": index,
                    "evaluated": False,
                    "reason": "first_match",
                }
            )
            continue
        try:
            value = evaluate_condition(
                condition,
                ctx_with_input,
                pool=pool or state.pool,
            )
        except ConditionError as exc:
            condition_error = {
                **exc.to_dict(),
                "branch_index": index,
                "branch_label": label,
            }
            evaluations.append(
                {
                    "label": label,
                    "branch_index": index,
                    "evaluated": True,
                    "error": exc.code,
                }
            )
            for later_index, later_label, _ in branch_specs[position + 1 :]:
                evaluations.append(
                    {
                        "label": later_label,
                        "branch_index": later_index,
                        "evaluated": False,
                        "reason": "condition_error",
                    }
                )
            return {
                "output": {
                    "chosen_branch": None,
                    "decision_resolution": "error",
                    "evaluations": evaluations,
                },
                "decision_resolution": "error",
                "condition_error": condition_error,
                "terminal_error": f"decision_condition_error:{node.id}",
            }
        evaluations.append(
            {
                "label": label,
                "branch_index": index,
                "evaluated": True,
                "value": bool(value),
            }
        )
        if value:
            chosen = label

    resolution = "matched"
    if chosen is None and default_label:
        chosen = default_label
        resolution = "defaulted"

    if chosen is None:
        return {
            "output": {
                "chosen_branch": None,
                "decision_resolution": "no_match",
                "evaluations": evaluations,
            },
            "decision_resolution": "no_match",
            "terminal_error": f"decision_no_match:{node.id}",
        }

    matching_routes = [
        edge
        for edge in graph.out_edges.get(node.id, [])
        if edge.kind == "branch" and edge.branch_label == chosen
    ]
    configured_labels = {label for _, label, _ in branch_specs if label}
    if not matching_routes or chosen not in configured_labels:
        return {
            "output": {
                "chosen_branch": chosen,
                "decision_resolution": "unroutable",
                "evaluations": evaluations,
            },
            "decision_resolution": "unroutable",
            "terminal_error": f"decision_branch_unroutable:{node.id}",
            "chosen_branch": chosen,
            "matching_routes": len(matching_routes),
        }

    # All outgoing branch edge labels that are NOT chosen become inactive.
    out_branch_labels: Set[str] = set()
    for edge in graph.out_edges.get(node.id, []):
        if edge.kind == "branch" and edge.branch_label:
            out_branch_labels.add(edge.branch_label)
    inactive = sorted(out_branch_labels - {chosen}) if chosen else sorted(out_branch_labels)
    return {
        "output": {
            "chosen_branch": chosen,
            "decision_resolution": resolution,
            "evaluations": evaluations,
        },
        "decision_resolution": resolution,
        "chosen_branch": chosen,
        "matching_routes": len(matching_routes),
        "active_branch_label": chosen,
        "inactive_branches": inactive,
    }


def _decision_resolution_checkpoint(
    node: DagNode,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the explicit, secret-free checkpoint for one Decision result."""

    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    entry: Dict[str, Any] = {
        "kind": "decision_resolution",
        "node_id": node.id,
        "resolution": result.get("decision_resolution") or "error",
        "chosen_branch": output.get("chosen_branch"),
        "evaluations": output.get("evaluations") or [],
    }
    if result.get("matching_routes") is not None:
        entry["matching_routes"] = int(result["matching_routes"])
    if isinstance(result.get("condition_error"), dict):
        entry["condition_error"] = dict(result["condition_error"])
    if result.get("terminal_error"):
        entry["error"] = str(result["terminal_error"])
    return entry


def _run_fork(
    node: DagNode, graph: DagGraph, state: WalkerState, payload: Dict[str, Any]
) -> Dict[str, Any]:
    """Fan the fork input out to each outgoing branch (P4).

    Beyond the legacy pass-through, we publish a *branch-scoped* pool namespace
    (``<fork_id>.<branch_label>``) per outgoing edge so a branch can address its
    own slice with a typed selector, and surface the branch labels on the
    output. Backward-compatible: the merged payload still flows downstream, so a
    fork with no branch labels behaves exactly as before.
    """
    payload = payload or {}
    branch_labels: List[str] = []
    for edge in graph.out_edges.get(node.id, []):
        label = edge.branch_label or edge.target
        if label not in branch_labels:
            branch_labels.append(label)
        state.pool.set([node.id, str(label)], payload)
    return {"output": {**payload, "_fork_branches": branch_labels}}


def _run_join(node: DagNode, graph: DagGraph, state: WalkerState) -> Dict[str, Any]:
    """Typed merge of the join's live predecessors, keyed by ``branch_label`` (P4).

    The dependency counter still gates *when* the join fires (once its pending
    predecessors settle). Strategies now diverge on the OUTPUT:

    * ``all`` (default): deep merge of every live branch output (legacy shape,
      plus a ``_branches`` map so consumers can read a single branch).
    * ``any`` / ``race``: the first non-empty live branch wins (no longer a
      silent degrade to ``all``).

    Dead branches (killed by an upstream decision/fork) are excluded.
    """
    config = node.config or {}
    strategy = config.get("strategy") or "all"
    branch_outputs: Dict[str, Any] = {}
    merged: Dict[str, Any] = {}
    for edge in graph.in_edges.get(node.id, []):
        if (edge.source, edge.target, edge.branch_label) in state.dead_edges:
            continue
        out = state.node_outputs.get(edge.source) or {}
        label = edge.branch_label or edge.source
        branch_outputs[str(label)] = out
        if isinstance(out, dict):
            merged.update(out)
    if strategy in ("any", "race"):
        primary = next((v for v in branch_outputs.values() if v), {})
        body = dict(primary) if isinstance(primary, dict) else {"value": primary}
        return {"output": {**body, "_join_strategy": strategy, "_branches": branch_outputs}}
    return {"output": {**merged, "_join_strategy": strategy, "_branches": branch_outputs}}


def _control_invocation_contract_violation(
    db: DBSession,
    run: Run,
    node: DagNode,
    payload: Any,
) -> RuntimeContractError | None:
    """Record a raw Skill-output violation and enforce the pinned mode."""

    violation = validate_node_invocation_output(
        run,
        node_id=node.id,
        payload=payload,
    )
    if violation is None:
        return None
    mode = validation_mode(run)
    if mode is None:
        return None
    checkpoint = violation.checkpoint()
    checkpoint["validation_mode"] = mode
    checkpoint["disposition"] = "failed" if mode == "enforce" else "observed"
    _append_checkpoint(db, run, checkpoint)
    return violation if mode == "enforce" else None


def _retry_node_output(raw_output: Any, attempt: int) -> dict[str, Any]:
    """Adapt arbitrary JSON to the stable retry.v1 public object."""

    output = dict(raw_output) if isinstance(raw_output, dict) else {"value": raw_output}
    output["_retry_attempts"] = attempt
    output["_status"] = "completed"
    return output


def _runtime_positive_int(value: Any, *, default: int, field: str) -> int:
    """Resolve a loop/retry budget without truncating floats or booleans."""

    resolved = default if value is None else value
    if (
        not isinstance(resolved, int)
        or isinstance(resolved, bool)
        or resolved <= 0
    ):
        raise ValueError(f"{field}_must_be_a_positive_integer")
    return resolved


async def _run_retry(
    db: DBSession,
    run: Run,
    node: DagNode,
    state: WalkerState,
    *,
    control,
    upstream: Optional[Dict[str, Any]] = None,
    resolved: bool = False,
) -> Dict[str, Any]:
    config = node.config or {}
    max_attempts = _runtime_positive_int(
        config.get("max_attempts"),
        default=3,
        field="max_attempts",
    )
    backoff_ms = float(config.get("backoff_ms") or 200)
    slug = node.skill_slug or config.get("skill_slug")
    if not slug:
        return {"output": upstream or {}}
    last_output = upstream or {}
    last_error: Optional[str] = None
    for attempt in range(1, max_attempts + 1):
        invocation = await _execute_task_node(
            db,
            run,
            state.ctx,
            slug,
            control=control,
            last_output=last_output,
            node_id=node.id,
            resolved_input=last_output if resolved else None,
            attempt_kind="task" if attempt == 1 else "retry",
            attempt_index=attempt,
        )
        if invocation is None:
            return {
                "output": last_output,
                "membrane_blocked": bool(resolve_membrane_spec(control=control).enforcement_active),
            }
        state.invocation_ids.append(invocation.id)
        state.total_cost += invocation.cost or 0.0
        if _runtime_valves_blocked(db, run, control):
            return {"output": {}, "membrane_blocked": True}
        if invocation.status == "completed":
            raw_output = (
                invocation.output_ref if invocation.output_ref is not None else {}
            )
            output = _retry_node_output(raw_output, attempt)
            violation = _control_invocation_contract_violation(
                db,
                run,
                node,
                raw_output,
            )
            if violation is not None:
                return {
                    "output": output,
                    "terminal_error": violation.terminal_error(),
                }
            return {"output": output}
        last_error = invocation.error
        if attempt < max_attempts and backoff_ms > 0:
            await asyncio.sleep(backoff_ms / 1000.0)
    return {
        "output": {
            **_passthrough_without_recipe(last_output),
            "_error": last_error,
            "_status": "failed",
            "_retry_attempts": max_attempts,
        }
    }


async def _run_loop(
    db: DBSession,
    run: Run,
    node: DagNode,
    state: WalkerState,
    *,
    control,
    upstream: Optional[Dict[str, Any]] = None,
    resolved: bool = False,
    pool: Optional[VariablePool] = None,
) -> Dict[str, Any]:
    config = node.config or {}
    max_iterations = _runtime_positive_int(
        config.get("max_iterations"),
        default=1,
        field="max_iterations",
    )
    iterator_key = config.get("iterator")
    break_on = config.get("break_on")
    slug = node.skill_slug or config.get("skill_slug")
    merged = upstream or {}
    base_ctx = {**state.ctx, **merged}
    items: List[Any] = []
    if iterator_key:
        src = base_ctx.get(iterator_key) if isinstance(iterator_key, str) else None
        if src is None:
            src = resolve_selector(iterator_key, pool or state.pool, default=None)
        if isinstance(src, list):
            items = list(src)
    if not items and max_iterations > 0 and not iterator_key:
        items = [None] * max_iterations

    iterations: List[Dict[str, Any]] = []
    for idx, item in enumerate(items[:max_iterations]):
        iter_ctx = {**state.ctx, "_loop_index": idx, "_loop_item": item}
        iter_input = {**(merged or {}), "item": item}
        if slug:
            invocation = await _execute_task_node(
                db,
                run,
                iter_ctx,
                slug,
                control=control,
                last_output=iter_input,
                node_id=node.id,
                resolved_input=iter_input if resolved else None,
                attempt_kind="loop",
                attempt_index=idx + 1,
            )
            if invocation is not None:
                state.invocation_ids.append(invocation.id)
                state.total_cost += invocation.cost or 0.0
                if _runtime_valves_blocked(db, run, control):
                    return {"output": {}, "membrane_blocked": True}
                iteration_output = (
                    invocation.output_ref if invocation.output_ref is not None else {}
                )
                if invocation.status == "completed":
                    violation = _control_invocation_contract_violation(
                        db,
                        run,
                        node,
                        iteration_output,
                    )
                    if violation is not None:
                        return {
                            "output": {"iterations": [], "count": 0},
                            "terminal_error": violation.terminal_error(),
                        }
                iterations.append(
                    {
                        "index": idx,
                        "status": invocation.status,
                        "output": iteration_output,
                    }
                )
                # Publish every completed iteration immediately. A subsequent
                # iteration/break condition and a later HITL checkpoint both
                # observe the same settled variable state.
                state.pool.set([node.id, "iterations", str(idx)], iteration_output)
                apply_outputs_map(node.config, iteration_output, state.pool)
                if pool is not None and pool is not state.pool:
                    pool.set([node.id, "iterations", str(idx)], iteration_output)
                    apply_outputs_map(node.config, iteration_output, pool)
            else:
                if resolve_membrane_spec(control=control).enforcement_active:
                    return {"output": {}, "membrane_blocked": True}
                iterations.append({"index": idx, "status": "blocked", "output": {}})
        else:
            iterations.append({"index": idx, "status": "noop", "output": iter_input})
        # Break condition evaluated after each iteration against the merged ctx.
        if break_on:
            try:
                if evaluate_condition(
                    break_on,
                    {**iter_ctx, **(iterations[-1]["output"] or {})},
                    pool=pool or state.pool,
                ):
                    break
            except ConditionError:
                pass
    return {
        "output": {
            "iterations": iterations,
            "count": len(iterations),
        }
    }


async def _run_agent_loop(
    db: DBSession,
    run: Run,
    node: DagNode,
    state: WalkerState,
    *,
    control,
    upstream: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Bounded think → gate → act loop. Does not call ``_run_loop``."""

    from app.services.run_engine.agent_loop import (
        DECIDE_SKILL,
        DEFAULT_CONFIDENCE_FLOOR,
        apply_steer,
        budget_exhausted,
        clamp_max_turns,
        coerce_decide_output,
        coerce_privilege_tier,
        compile_mandate_view,
        evaluate_done_when,
        gate_skill,
    )
    from app.services.skills_registry.workspace_skills import workspace_skill_purposes

    config = node.config or {}
    merged = dict(upstream or {})
    goal = dict(config.get("goal") or merged.get("goal") or {})
    if not goal.get("objective"):
        goal["objective"] = str(merged.get("objective") or goal.get("objective") or "")
    goal.setdefault("done_when", list(config.get("done_when") or goal.get("done_when") or []))
    goal.setdefault("status", "active")
    allowlist = list(config.get("skill_allowlist") or merged.get("skill_allowlist") or [])
    decide_slug = (
        config.get("decide_skill") or node.skill_slug or DECIDE_SKILL
    )
    try:
        floor = float(config.get("confidence_floor") if config.get("confidence_floor") is not None else DEFAULT_CONFIDENCE_FLOOR)
    except (TypeError, ValueError):
        floor = DEFAULT_CONFIDENCE_FLOOR
    budget_cfg = config.get("budget") if isinstance(config.get("budget"), dict) else {}
    max_turns = clamp_max_turns(budget_cfg.get("max_turns") or config.get("max_turns"))
    try:
        max_cost = float(budget_cfg["max_cost"]) if budget_cfg.get("max_cost") is not None else None
    except (TypeError, ValueError):
        max_cost = None
    try:
        deadline_ms = float(budget_cfg["deadline_ms"]) if budget_cfg.get("deadline_ms") is not None else None
    except (TypeError, ValueError):
        deadline_ms = None
    on_budget = str(config.get("on_budget") or "exit")
    privilege = coerce_privilege_tier(config.get("privilege_tier"))
    if merged.get("_fork_branches") or config.get("worker_read_only"):
        privilege = "recommend"

    steer_raw = {}
    if isinstance(run.input_ref, dict):
        steer_raw = dict(run.input_ref.get("_steer") or {})
    if steer_raw:
        steered = apply_steer(
            {"privilege_tier": privilege, "skill_allowlist": allowlist},
            op=str(steer_raw.get("op") or "set_tier"),
            privilege_tier=steer_raw.get("privilege_tier"),
            skill_allowlist=steer_raw.get("skill_allowlist"),
            note=steer_raw.get("note"),
            escalate_to=steer_raw.get("escalate_to"),
        )
        privilege = coerce_privilege_tier(steered.get("privilege_tier"), default=privilege)
        if steered.get("skill_allowlist"):
            allowlist = list(steered["skill_allowlist"])

    loops = dict(state.ctx.get("_agent_loop") or {})
    resume = dict(loops.get(node.id) or {})
    observations: List[Dict[str, Any]] = list(resume.get("observations") or [])
    if steer_raw.get("note"):
        observations.append(
            {
                "turn": int(resume.get("next_turn") or 1),
                "skill": "steer",
                "ok": True,
                "summary": str(steer_raw.get("note")),
            }
        )
    start_turn = int(resume.get("next_turn") or 1)
    pending_write = resume.get("pending_write")
    human = resume.get("human") if isinstance(resume.get("human"), dict) else {}
    if human and not pending_write:
        observations.append(
            {
                "turn": max(start_turn - 1, 1),
                "skill": "human",
                "ok": bool(human.get("approved")),
                "summary": "human_approved" if human.get("approved") else "human_rejected",
            }
        )
        if human.get("rejected"):
            goal["status"] = "blocked"
            loops[node.id] = {
                "observations": observations,
                "next_turn": start_turn,
                "goal": goal,
                "pending_write": None,
            }
            state.ctx["_agent_loop"] = loops
            return {
                "output": {
                    "goal": goal,
                    "observations": observations,
                    "exit": "blocked",
                    "turns": start_turn,
                    "privilege_tier": privilege,
                    "visible_skills": [],
                }
            }

    mandate = compile_mandate_view(
        allowlist,
        control=control,
        privilege_tier=privilege,
        purposes=workspace_skill_purposes(
            db, workspace_id=run.workspace_id, slugs=allowlist
        ),
    )
    visible = [item.to_dict() for item in mandate.visible]
    start_ms = state.accumulated_ms

    async def _invoke(slug: str, payload: Dict[str, Any], *, turn: int, kind: str):
        invocation = await _execute_task_node(
            db,
            run,
            {**state.ctx, **merged},
            slug,
            control=control,
            last_output=payload,
            node_id=node.id,
            resolved_input=payload,
            attempt_kind=kind,
            attempt_index=turn,
        )
        if invocation is not None:
            state.invocation_ids.append(invocation.id)
            state.total_cost += invocation.cost or 0.0
        return invocation

    def _persist_resume(next_turn: int, extra: Optional[Dict[str, Any]] = None) -> None:
        loops[node.id] = {
            "observations": observations,
            "next_turn": next_turn,
            "goal": goal,
            "pending_write": pending_write,
            **(extra or {}),
        }
        state.ctx["_agent_loop"] = loops

    def _output(*, exit_value: Optional[str]) -> Dict[str, Any]:
        return {
            "goal": goal,
            "observations": observations,
            "exit": exit_value,
            "turns": start_turn,
            "privilege_tier": privilege,
            "visible_skills": [row["slug"] for row in visible],
        }

    if pending_write:
        if human.get("approved"):
            invocation = await _invoke(
                str(pending_write),
                {**merged, "observations": observations, "goal": goal},
                turn=max(start_turn - 1, 1),
                kind="agent_loop_act",
            )
            ok = bool(invocation is not None and invocation.status == "completed")
            observations.append(
                {
                    "turn": max(start_turn - 1, 1),
                    "skill": pending_write,
                    "ok": ok,
                    "summary": "human_approved_write" if ok else "write_failed",
                }
            )
            pending_write = None
            _persist_resume(start_turn)
            if evaluate_done_when(goal.get("done_when") or [], observations=observations, claimed=True):
                goal["status"] = "complete"
                return {"output": _output(exit_value="complete")}
        else:
            goal["status"] = "blocked"
            observations.append(
                {
                    "turn": max(start_turn - 1, 1),
                    "skill": pending_write,
                    "ok": False,
                    "summary": "human_rejected_write",
                }
            )
            pending_write = None
            _persist_resume(start_turn)
            return {"output": _output(exit_value="blocked")}

    for turn in range(start_turn, max_turns + 1):
        elapsed = state.accumulated_ms - start_ms + (time.monotonic() - state.start_monotonic) * 1000
        if budget_exhausted(
            turn=turn,
            max_turns=max_turns,
            total_cost=state.total_cost,
            max_cost=max_cost,
            elapsed_ms=elapsed,
            deadline_ms=deadline_ms,
        ) or turn > max_turns:
            goal["status"] = "blocked" if on_budget != "ask_human" else "needs_approval"
            if on_budget == "ask_human":
                _persist_resume(turn)
                return await _pause_agent_loop_for_human(
                    db,
                    run,
                    node,
                    state,
                    control=control,
                    prompt="Loop budget exhausted. Continue or stop?",
                    upstream=merged,
                )
            return {"output": _output(exit_value="budget")}

        remaining = {
            "turns_left": max_turns - turn + 1,
            "cost_left": None if max_cost is None else max(0.0, max_cost - state.total_cost),
            "deadline_ms_left": None if deadline_ms is None else max(0.0, deadline_ms - elapsed),
        }
        decide_payload = {
            "goal": goal,
            "observations": observations,
            "visible_skills": visible,
            "budget": remaining,
            "confidence_floor": floor,
            "agent_loop_node_id": node.id,
        }
        invocation = await _invoke(
            str(decide_slug),
            decide_payload,
            turn=turn,
            kind="agent_loop_decide",
        )
        raw = (
            invocation.output_ref
            if invocation is not None and isinstance(invocation.output_ref, dict)
            else {}
        )
        decide = coerce_decide_output(raw, visible, confidence_floor=floor)
        _append_checkpoint(
            db,
            run,
            {
                "kind": "agent_loop_turn",
                "t": datetime.utcnow().isoformat(),
                "node_id": node.id,
                "turn": turn,
                "decide": decide,
                "skill": decide.get("next_skill"),
                "cost": state.total_cost,
            },
        )

        if decide.get("needs_human") or decide.get("exit") == "ask_human":
            goal["status"] = "needs_approval"
            _persist_resume(turn + 1)
            return await _pause_agent_loop_for_human(
                db,
                run,
                node,
                state,
                control=control,
                prompt=decide.get("human_prompt") or "The agent needs a human decision.",
                upstream=merged,
            )

        if decide.get("exit") in {"blocked", "policy_block", "budget"}:
            goal["status"] = "blocked"
            return {"output": _output(exit_value=decide.get("exit"))}

        claimed_done = bool(decide.get("done") or decide.get("exit") == "complete")
        if claimed_done and evaluate_done_when(
            goal.get("done_when") or [],
            observations=observations,
            claimed=True,
        ):
            goal["status"] = "complete"
            return {"output": _output(exit_value="complete")}

        next_skill = decide.get("next_skill")
        if not next_skill:
            if claimed_done:
                goal["status"] = "active"
            else:
                goal["status"] = "blocked"
            return {"output": _output(exit_value=decide.get("exit") or "blocked")}

        gate = gate_skill(str(next_skill), mandate)
        if not gate.allowed:
            _append_checkpoint(
                db,
                run,
                {
                    "kind": "agent_loop_policy_block",
                    "node_id": node.id,
                    "turn": turn,
                    "skill": next_skill,
                    "reason": gate.reason,
                },
            )
            if gate.needs_human:
                pending_write = str(next_skill)
                goal["status"] = "needs_approval"
                _persist_resume(turn + 1)
                return await _pause_agent_loop_for_human(
                    db,
                    run,
                    node,
                    state,
                    control=control,
                    prompt=f"Approve write skill {next_skill}?",
                    upstream=merged,
                    prompt_kind="approve_write",
                )
            goal["status"] = "blocked"
            return {"output": _output(exit_value="policy_block")}

        invocation = await _invoke(
            str(next_skill),
            {**merged, "goal": goal, "observations": observations, "decide": decide},
            turn=turn,
            kind="agent_loop_act",
        )
        ok = bool(invocation is not None and invocation.status == "completed")
        summary = ""
        if invocation is not None and isinstance(invocation.output_ref, dict):
            summary = str(
                invocation.output_ref.get("summary")
                or invocation.output_ref.get("completion")
                or invocation.output_ref.get("status")
                or ""
            )
        observations.append(
            {"turn": turn, "skill": next_skill, "ok": ok, "summary": summary}
        )
        if evaluate_done_when(
            goal.get("done_when") or [],
            observations=observations,
            claimed=bool(decide.get("done")),
        ):
            goal["status"] = "complete"
            return {"output": _output(exit_value="complete")}

    goal["status"] = "blocked"
    return {"output": _output(exit_value="budget")}


async def _pause_agent_loop_for_human(
    db: DBSession,
    run: Run,
    node: DagNode,
    state: WalkerState,
    *,
    control,
    prompt: str,
    upstream: Dict[str, Any],
    prompt_kind: str = "choice",
) -> Dict[str, Any]:
    """HITL pause owned by the agent_loop node so resume re-enters the loop."""

    hitl_node = DagNode(
        id=node.id,
        type=node.type,
        kind="hitl",
        label=node.label,
        config={
            "prompt": prompt,
            "prompt_kind": prompt_kind,
            "approvers": (node.config or {}).get("approvers") or [],
        },
        skill_slug=None,
        data=node.data,
    )
    return _run_hitl(db, run, hitl_node, state, control=control, upstream=upstream)


def _run_hitl(
    db: DBSession,
    run: Run,
    node: DagNode,
    state: WalkerState,
    *,
    control=None,
    upstream: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Persist a ``proposed`` Decision, then ask the walker to pause.

    Membrane outbound facet (P3): the resolved outbound gate (read-through —
    derived from ``source_policy`` / control when no explicit spec) is recorded
    on the Decision rationale so the gate verdict is auditable. This is purely
    additive — a ``hitl`` node always pauses regardless.
    """
    config = node.config or {}
    prompt = config.get("prompt") or f"Approval required for step {node.label or node.id}"
    approvers = config.get("approvers") or []
    merged = upstream or {}
    membrane_gate: Dict[str, Any] = {}
    try:
        from app.services.membrane.spec import resolve_membrane_spec

        spec = resolve_membrane_spec(control=control)
        membrane_gate = {
            "authoritative": spec.authoritative,
            "expert_review_required": spec.outbound.expert_review_required,
            "gate_if_confidence_below": spec.outbound.gate_if_confidence_below,
        }
    except Exception:  # noqa: BLE001 — provenance only, never block the gate.
        membrane_gate = {}
    rationale = {
        "node_id": node.id,
        "node_label": node.label,
        "prompt": prompt,
        "prompt_kind": config.get("prompt_kind") or "approve_write",
        "approvers": approvers,
        "membrane_gate": membrane_gate,
        "ctx_snapshot": _sanitize(state.ctx),
        "upstream": _sanitize(merged),
    }
    decision = _log_decision(
        db,
        workspace_id=run.workspace_id,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        rationale=rationale,
        status="proposed",
        title=f"HITL approval — {node.label or node.id}",
    )
    if decision is not None:
        from app.services.run_engine.gate_ttl import stamp_decision_ttl  # noqa: WPS433
        from app.services.run_engine.inbox import extract_correlation_key  # noqa: WPS433

        stamp_decision_ttl(decision, config)
        # Prefer explicit node config, then upstream / run input correlation.
        corr = (
            config.get("correlation_key")
            or extract_correlation_key(merged)
            or extract_correlation_key(run.input_ref if isinstance(run.input_ref, dict) else {})
        )
        if corr:
            rationale = dict(decision.rationale or {})
            rationale["correlation_key"] = corr
            decision.rationale = rationale
        db.commit()
    return {
        "pause": True,
        "node_id": node.id,
        "decision_id": decision.id if decision else None,
        "prompt": prompt,
        "expires_at": decision.expires_at.isoformat() if decision and decision.expires_at else None,
        "expiry_action": decision.expiry_action if decision else None,
        "correlation_key": (decision.rationale or {}).get("correlation_key") if decision else None,
    }


def _build_subflow_input(
    config: Dict[str, Any], upstream: Dict[str, Any], pool: VariablePool
) -> Dict[str, Any]:
    """Map ``config.input_map`` selectors into the child run's ``input_ref``.

    ``input_map`` maps ``child_input_key → selector`` (dot-path / VariableRef /
    list), resolved against the parent pool with the upstream merge as fallback.
    When absent, the whole upstream merge becomes the child input (so a plain
    subflow still forwards its inputs).
    """
    input_map = config.get("input_map") or config.get("inputs_map") or {}
    upstream = upstream or {}
    if not isinstance(input_map, dict) or not input_map:
        # Run-control namespaces belong to the parent execution boundary.
        # They must never silently attach a debugger or impersonate ingress
        # evidence on the delegated child.
        return {
            key: value
            for key, value in upstream.items()
            if key not in {"_debug", "_ingress", "execution"}
        }
    resolved: Dict[str, Any] = {}
    for key, selector in input_map.items():
        value = resolve_selector(selector, pool, default=None)
        if value is None:
            value = upstream.get(str(key))
        resolved[str(key)] = value
    return resolved


def _delegation_acl(control, target: System, branch: str, payload: Dict[str, Any]):
    """Resolve the authoritative typed delegation edge, fail-closed in v2 enforce."""
    from .subflow_orchestration import delegation_acl_result

    try:
        spec = resolve_membrane_spec(control=control)
    except Exception as exc:  # malformed enforce contracts are not an allow-all
        extra = getattr(control, "extra", None)
        raw = (extra.get("membrane_spec") or {}) if isinstance(extra, dict) else {}
        enforce = isinstance(raw, dict) and raw.get("version") == 2 and raw.get("enforcement_mode") == "enforce"
        return (not enforce, "invalid_membrane_spec", None, enforce, str(exc))
    allowed, reason, output_contract, enforced = delegation_acl_result(
        spec,
        target_system_id=target.id,
        branch=branch,
        input_payload=payload,
    )
    return allowed, reason, output_contract, enforced, None


async def _run_subflow(
    db: DBSession,
    run: Run,
    node: DagNode,
    state: WalkerState,
    *,
    control,
    upstream: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Delegate to the target System as a real child ``Run`` (P4).

    Creates ``Run(parent_run_id=run.id)`` for the target System, maps
    ``config.input_map`` into its ``input_ref`` (stamping ``delegation_node_id``
    there so provenance needs no DDL), executes it IN-PROCESS as its own DAG (or
    the sequential walker), and merges the child output back at this node. If the
    child pauses for HITL, the pause surfaces to the parent so the join is gated.

    Resume-aware / idempotent (P4 follow-up): the child ``Run.id`` is recorded
    in ``state.subflow_children[node.id]`` *before* execution so it survives the
    parent's HITL pause. On a parent resume the walker re-reaches this node and
    we reuse the recorded child — resuming it if it is still ``hitl_pending`` or
    settling with its output if it already completed — instead of spawning a
    brand-new child Run.
    """
    config = node.config or {}
    target_id = config.get("system_id")
    if not target_id:
        return {"output": {}}

    # Resume / replay: a child was already spawned for this node on a prior
    # pass. Continue it rather than delegating from scratch.
    recorded_child_id = state.subflow_children.get(node.id)
    if recorded_child_id:
        outcome = await _continue_subflow_child(db, node, state, recorded_child_id, target_id)
        if outcome is not None:
            return outcome
        # Recorded child vanished (should not happen) — drop the stale mapping
        # and fall through to recreate so the run can still make progress.
        state.subflow_children.pop(node.id, None)

    target = db.query(System).filter(System.id == target_id, System.workspace_id == run.workspace_id).first()
    if not target:
        logger.warning(
            "dag_engine: subflow system missing",
            run_id=run.id,
            node_id=node.id,
            system_id=target_id,
        )
        return {"output": {"_error": "subflow_system_not_found"}}

    target_workspace = (
        db.query(Workspace).filter(Workspace.id == target.workspace_id).first()
        if target.workspace_id
        else None
    )
    published_target_evidence: tuple[Any, dict[str, Any], str, dict[str, Any]] | None = None
    target_flow = target.flow_definition or {}
    if target_workspace is not None:
        from app.services.systems import flow_publication as subflow_publication

        if subflow_publication.flow_publication_enabled(target_workspace):
            # Publication and delegation acceptance share this row lock.  The
            # child can never be authorised against one target graph and then
            # execute a newer pointer accepted in the gap.
            target = (
                db.query(System)
                .filter(
                    System.id == target_id,
                    System.workspace_id == run.workspace_id,
                )
                .populate_existing()
                .with_for_update(of=System)
                .one()
            )
            (
                target_version,
                target_flow,
                target_flow_sha256,
                target_execution_contract,
            ) = subflow_publication.published_run_evidence(
                db,
                system=target,
                workspace=target_workspace,
            )
            published_target_evidence = (
                target_version,
                target_flow,
                target_flow_sha256,
                target_execution_contract,
            )

    parent_system = (
        db.query(System)
        .filter(System.id == run.system_id, System.workspace_id == run.workspace_id)
        .first()
    )
    target_nodes = (
        (target_flow or {}).get("nodes")
        if isinstance(target_flow, dict)
        else []
    )
    target_has_delegation = any(
        isinstance(candidate, dict) and candidate.get("kind") == "subflow"
        for candidate in (target_nodes or [])
    )
    if (
        target_has_delegation
        and subflow_celery_enabled(target)
        and (parent_system is None or not subflow_celery_enabled(parent_system))
    ):
        # A child cannot silently switch its descendants to the durable plane
        # while its own parent remains in-process: no persisted parent wait
        # envelope would exist to wake that outer run. Require an explicit
        # opt-in at every ancestor and fail before creating an orphan child.
        raise RuntimeError("mixed_subflow_execution_plane_requires_parent_opt_in")

    child_input = _build_subflow_input(config, upstream or {}, state.pool)
    timeout_seconds = config.get("timeout_seconds")
    deadline_at: Optional[str] = None
    if timeout_seconds is not None:
        try:
            timeout_seconds = float(timeout_seconds)
        except (TypeError, ValueError):
            return {"output": {"_error": "invalid_subflow_timeout"}}
        if timeout_seconds <= 0 or timeout_seconds > 86400:
            return {"output": {"_error": "invalid_subflow_timeout"}}
        deadline_at = (datetime.utcnow() + timedelta(seconds=timeout_seconds)).isoformat()
    branch = str(
        config.get("branch")
        or (upstream or {}).get("_delegation_branch")
        or "default"
    )
    allowed, acl_reason, output_contract, contract_enforced, acl_error = _delegation_acl(
        control, target, branch, child_input
    )
    if not allowed:
        _log_decision(
            db,
            workspace_id=run.workspace_id,
            scope="run",
            target_id=run.id,
            kind="policy_block",
            rationale={
                "delegation": target_id,
                "node_id": node.id,
                "reason": acl_reason or "delegation_not_in_membrane_acl",
                "error": acl_error,
            },
        )
        return {"output": {"_error": "delegation_blocked", "subflow_system_id": target_id}}
    if acl_reason:
        _log_decision(
            db,
            workspace_id=run.workspace_id,
            scope="run",
            target_id=run.id,
            kind="policy_shadow",
            rationale={"delegation": target_id, "node_id": node.id, "reason": acl_reason},
        )

    # Provenance: carry the delegating node id inside the child input_ref to
    # avoid a DDL migration (Run already has parent_run_id).
    target_contract = (
        (target_flow or {}).get("output_contract")
        if isinstance(target_flow, dict)
        else None
    )
    if not isinstance(target_contract, dict):
        target_contract = config.get("output_contract")
    delegation_evidence = {
        "parent_run_id": run.id,
        "delegation_node_id": node.id,
        "branch": branch,
        "output_contract": output_contract,
        "target_output_contract": target_contract if isinstance(target_contract, dict) else None,
        "contract_enforced": contract_enforced,
        "timeout_seconds": timeout_seconds,
        "deadline_at": deadline_at,
    }

    iteration = config.get(
        "iteration",
        (upstream or {}).get("_loop_iteration", (upstream or {}).get("iteration", 0)),
    )
    logical_key = delegation_key(run.id, node.id, iteration, branch)
    celery_plane = parent_system is not None and subflow_celery_enabled(parent_system)
    child = db.query(Run).filter(Run.delegation_key == logical_key).first()
    if child is None:
        try:
            # A savepoint lets a concurrent redelivery converge on the unique
            # logical child without rolling back unrelated parent state.  The
            # outer transaction is committed only after the parent wait
            # envelope and its outbox event have been persisted as well.
            with db.begin_nested():
                if published_target_evidence is not None:
                    from app.services.systems import flow_ingress as subflow_ingress

                    (
                        target_version,
                        _target_flow,
                        target_flow_sha256,
                        _target_contract,
                    ) = published_target_evidence
                    try:
                        child = subflow_ingress.create_published_ingress_run(
                            db,
                            system_id=target_id,
                            workspace=target_workspace,
                            ingress_id=config.get("subflow_ingress_id"),
                            kind=str(config.get("subflow_ingress_kind") or "manual"),
                            payload=child_input,
                            expected_published_version_id=target_version.id,
                            expected_flow_sha256=target_flow_sha256,
                            adapter_evidence={
                                "surface": "subflow",
                                "parent_run_id": run.id,
                                "delegation_node_id": node.id,
                            },
                            trigger="subflow",
                        )
                    except subflow_ingress.FlowIngressError as exc:
                        raise RuntimeError(
                            f"subflow_ingress_rejected:{exc.code}"
                        ) from exc
                    child.parent_run_id = run.id
                    accepted_child_input = dict(child.input_ref or {})
                    accepted_child_input["_delegation"] = delegation_evidence
                    child.input_ref = accepted_child_input
                else:
                    child = Run(
                        workspace_id=run.workspace_id,
                        system_id=target_id,
                        parent_run_id=run.id,
                        input_ref={**child_input, "_delegation": delegation_evidence},
                        status="pending",
                        trigger="subflow",
                    )
                    db.add(child)
                child.delegation_key = logical_key
                child.delegation_node_id = node.id
                child.delegation_branch = branch
                child.delegation_deadline_at = (
                    datetime.fromisoformat(deadline_at) if deadline_at else None
                )
                db.flush()
        except IntegrityError:
            child = db.query(Run).filter(Run.delegation_key == logical_key).one()
    persisted_delegation = (
        ((child.input_ref or {}).get("_delegation") or {})
        if isinstance(child.input_ref, dict)
        else {}
    )
    if isinstance(persisted_delegation, dict):
        deadline_at = persisted_delegation.get("deadline_at")
    if child.delegation_deadline_at is None and deadline_at:
        try:
            child.delegation_deadline_at = datetime.fromisoformat(
                str(deadline_at).replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except (TypeError, ValueError):
            # The worker deadline parser already fails malformed persisted
            # values closed; keep the indexed projection empty rather than
            # inventing a different deadline.
            pass
    child_id = child.id
    # Record the mapping BEFORE executing so that if the child pauses for HITL
    # the parent's serialised checkpoint already carries the child run id and a
    # later resume can find it (rather than spawning a duplicate).
    state.subflow_children[node.id] = child_id

    if celery_plane:
        from .dispatch_outbox import SUBFLOW_RUN, enqueue_dispatch
        from .subflow_orchestration import _wave_ids_equal

        persisted_input = dict(child.input_ref or {})
        persisted_child_delegation = dict(persisted_input.get("_delegation") or {})
        persisted_child_delegation["execution_plane"] = "celery"
        persisted_input["_delegation"] = persisted_child_delegation
        child.input_ref = persisted_input
        waiting = dict(run.waiting_subflows or {})
        strategy = str(config.get("join_strategy") or config.get("strategy") or "all").lower()
        if strategy not in {"all", "any", "race"}:
            return {"output": {"_error": "invalid_subflow_join_strategy", "strategy": strategy}}
        meta = dict(waiting.get("_meta") or {})
        current_strategy = meta.get("strategy")
        current_state = str(meta.get("state") or "")
        if current_state != "waiting":
            previous_wave = meta.get("wave_id")
            if previous_wave is not None and not _wave_ids_equal(
                previous_wave,
                previous_wave,
            ):
                return {"output": {"_error": "invalid_subflow_wave_id"}}
            meta["wave_id"] = (previous_wave or 0) + 1
            current_strategy = None
        elif meta.get("wave_id") is None:
            # Checkpoints written before wave scoping are still resumable.
            # Adopt their active entries into the first explicit wave rather
            # than raising on ``meta[\"wave_id\"]`` or silently ignoring them.
            meta["wave_id"] = 1
            for legacy_key, legacy_entry in waiting.items():
                if legacy_key != "_meta" and isinstance(legacy_entry, dict):
                    legacy_entry.setdefault("wave_id", meta["wave_id"])
        if current_strategy and current_strategy != strategy:
            return {"output": {"_error": "mixed_subflow_join_strategies"}}
        if not _wave_ids_equal(meta.get("wave_id"), meta.get("wave_id")):
            return {"output": {"_error": "invalid_subflow_wave_id"}}
        meta.update({"strategy": strategy, "state": "waiting", "execution_plane": "celery"})
        waiting["_meta"] = meta
        entry = dict(waiting.get(logical_key) or {})
        entry.update({"child_run_id": child_id, "node_id": node.id, "branch": branch,
                      "iteration": iteration, "strategy": strategy,
                      "status": child.status, "dispatch_state": "outbox_pending",
                      "deadline_at": deadline_at, "wave_id": meta["wave_id"]})
        waiting[logical_key] = entry
        run.waiting_subflows = waiting
        enqueue_dispatch(
            db,
            event_type=SUBFLOW_RUN,
            workspace_id=str(run.workspace_id),
            run_id=child_id,
            source_id=logical_key,
            wave_id=meta["wave_id"],
        )
        # Do not commit here. Every parallel branch shares this Session, and
        # ``_emit_subflow_pause`` atomically commits all children, parent wait
        # state/checkpoint and outbox rows before any broker publication.
        return {"pause": True, "wait_subflow": True, "node_id": node.id, "child_run_id": child_id,
                "prompt": "Subflow dispatched; awaiting durable completion"}

    # Execute the child as its own graph (in-process). Celery fan-out is wired
    # through the durable outbox; this synchronous path still needs the child
    # committed before the nested walker opens its own session.
    db.commit()
    target_workspace = (
        db.query(Workspace).filter(Workspace.id == target.workspace_id).first()
        if target.workspace_id
        else None
    )
    if resolve_run_flow_execution(child, target, target_workspace).uses_dag:
        child_summary = await execute_run_dag(child_id)
    else:
        child_summary = await execute_run(child_id)

    return _subflow_outcome(db, node, state, child_id, target_id, child_summary)


async def _continue_subflow_child(
    db: DBSession,
    node: DagNode,
    state: WalkerState,
    child_id: str,
    target_id: str,
) -> Optional[Dict[str, Any]]:
    """Resume or reuse an already-spawned subflow child (idempotent replay).

    Returns the node outcome dict, or ``None`` when the recorded child run no
    longer exists so the caller can recreate it. Never spawns a new child and
    never re-runs a child that already produced a terminal output.
    """
    # The child ran/committed in its own session; force a fresh read of status.
    child = db.query(Run).filter(Run.id == child_id).first()
    if child is None:
        return None
    db.refresh(child)
    status = child.status

    if status == "hitl_pending":
        # Drive the existing child forward via its OWN resume path. The child
        # reads the decision id from its own pause checkpoint, so the operator
        # approval recorded against that Decision is what unblocks it.
        child_summary = await resume_run_dag(child_id)
        return _subflow_outcome(db, node, state, child_id, target_id, child_summary)

    if status in ("running", "pending"):
        if child.celery_task_id or child.delegation_key:
            return {"pause": True, "wait_subflow": True, "node_id": node.id, "child_run_id": child_id,
                    "prompt": "Subflow execution is still pending"}
        # Defensive: a synchronous in-process child should already be terminal
        # or paused. If we somehow re-enter while it is mid-flight, continue it
        # rather than creating a duplicate.
        target = (
            db.query(System)
            .filter(
                System.id == child.system_id,
                System.workspace_id == child.workspace_id,
            )
            .first()
        )
        target_workspace = (
            db.query(Workspace).filter(Workspace.id == target.workspace_id).first()
            if target is not None and target.workspace_id
            else None
        )
        if (
            target is not None
            and resolve_run_flow_execution(child, target, target_workspace).uses_dag
        ):
            child_summary = await execute_run_dag(child_id)
        else:
            child_summary = await execute_run(child_id)
        return _subflow_outcome(db, node, state, child_id, target_id, child_summary)

    # completed / failed / cancelled → reuse the terminal output. Never re-run.
    return _settle_subflow_output(db, state, child_id, target_id)


def _subflow_outcome(
    db: DBSession,
    node: DagNode,
    state: WalkerState,
    child_id: str,
    target_id: str,
    child_summary: Any,
) -> Dict[str, Any]:
    """Translate a child run summary into a subflow node outcome.

    A child still awaiting HITL surfaces as a parent pause (gating the join);
    otherwise the child's merged output settles the subflow node.
    """
    if isinstance(child_summary, dict) and child_summary.get("status") == "hitl_pending":
        return {
            "pause": True,
            "node_id": node.id,
            "decision_id": child_summary.get("awaiting_decision"),
            "prompt": child_summary.get("prompt") or f"Subflow {target_id} awaiting approval",
            "child_run_id": child_id,
        }
    return _settle_subflow_output(db, state, child_id, target_id)


def _settle_subflow_output(
    db: DBSession,
    state: WalkerState,
    child_id: str,
    target_id: str,
) -> Dict[str, Any]:
    """Read the committed child output (in its own session) and merge it back."""
    # The child ran in its OWN session; expire the stale identity-mapped row so
    # we read the committed output_ref / cost rather than the pending snapshot.
    fresh = db.query(Run).filter(Run.id == child_id).first()
    if fresh is not None:
        db.refresh(fresh)
    child_output = (fresh.output_ref if fresh else None) or {}
    delegation = (
        ((fresh.input_ref or {}).get("_delegation") or {})
        if fresh is not None and isinstance(fresh.input_ref, dict)
        else {}
    )
    contract_warning = None
    if isinstance(delegation, dict):
        from .subflow_orchestration import validate_contract

        contracts = [
            value
            for value in (
                delegation.get("output_contract"),
                delegation.get("target_output_contract"),
            )
            if isinstance(value, dict) and value
        ]
        if contracts and not all(validate_contract(child_output, contract) for contract in contracts):
            contract_warning = "delegation_output_contract_mismatch"
            if delegation.get("contract_enforced") and fresh is not None:
                fresh.status = "failed"
                fresh.error = fresh.error or contract_warning
                fresh.output_ref = {}
                child_output = {}
                db.commit()
    state.total_cost += float(fresh.cost_internal or 0.0) if fresh else 0.0
    return {
        "output": {
            "subflow_system_id": target_id,
            "child_run_id": child_id,
            "child_status": fresh.status if fresh else "failed",
            **({"_error": fresh.error} if fresh is not None and fresh.error else {}),
            **({"_contract_warning": contract_warning} if contract_warning else {}),
            **(child_output if isinstance(child_output, dict) else {}),
        }
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def _seed_pool(
    db: DBSession,
    pool: VariablePool,
    run: Run,
    system: System,
    *,
    workspace: Optional[Workspace] = None,
) -> None:
    """Seed all built-ins with real, tenant-scoped runtime values.

    ``inputs_map`` selectors such as ``run.query`` or
    ``system.voice_runtime.provider`` resolve against these. Node-output
    buckets (e.g. ``capture.gaps``) are filled later by ``apply_outputs_map``.
    Workspace/System/Context configuration is recursively stripped of
    credential-shaped fields before entering the pool.
    """
    input_ref = run.input_ref if isinstance(run.input_ref, dict) else {}
    pool.set_namespace("run", {**input_ref, "id": run.id, "input": input_ref})
    system_settings = system.settings if isinstance(getattr(system, "settings", None), dict) else {}
    pool.set_namespace(
        "system",
        {
            **_without_secret_values(system_settings),
            "id": system.id,
            "default_model": getattr(system, "default_model", None),
            "default_prompt_type": getattr(system, "default_prompt_type", None),
            "retrieval_mode_default": getattr(system, "retrieval_mode_default", None),
        },
    )
    workspace_settings = (
        workspace.settings
        if workspace is not None and isinstance(getattr(workspace, "settings", None), dict)
        else {}
    )
    pool.set_namespace(
        "workspace",
        {
            "id": run.workspace_id,
            "slug": getattr(workspace, "slug", None),
            "name": getattr(workspace, "name", None),
            "mode": getattr(workspace, "mode", None),
            "settings": _without_secret_values(workspace_settings),
        },
    )

    if system.workspace_id != run.workspace_id:
        raise RuntimeError("run_system_workspace_mismatch")
    try:
        context = (
            context_in_workspace(
                db,
                workspace_id=run.workspace_id,
                context_id=system.context_id,
            )
            if system.context_id
            else None
        )
    except ContextBindingError as exc:
        raise RuntimeError("system_context_binding_invalid") from exc
    context_payload: Dict[str, Any] = {
        "id": getattr(context, "id", None),
        "name": getattr(context, "name", None),
        "version": getattr(context, "version", None),
        "data_refs": getattr(context, "data_refs", None) or [],
        "memory_refs": getattr(context, "memory_refs", None) or [],
        "history_refs": getattr(context, "history_refs", None) or [],
        "environment_state": getattr(context, "environment_state", None) or {},
        "business_constraints": getattr(context, "business_constraints", None) or {},
        "permissions": getattr(context, "permissions", None) or {},
    }
    pool.set_namespace("context", _without_secret_values(context_payload))
    # Seeded for contract completeness; each handler overlays its real local
    # scope on an isolated pool copy before resolving inputs.
    pool.set_namespace("node", {})


_SECRET_KEYS = {
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "auth_token",
    "id_token",
    "session_token",
    "private_key",
    "authorization",
    "bearer",
    "credential",
    "credentials",
    "dsn",
    "token",
}
_SECRET_SUFFIXES = tuple(f"_{key}" for key in _SECRET_KEYS)


def _without_secret_values(value: Any) -> Any:
    """Copy JSON-like runtime config while dropping credential fields."""
    if isinstance(value, dict):
        clean: Dict[str, Any] = {}
        for key, item in value.items():
            name = str(key).strip().lower()
            if name in _SECRET_KEYS or name.endswith(_SECRET_SUFFIXES):
                continue
            clean[str(key)] = _without_secret_values(item)
        return clean
    if isinstance(value, list):
        return [_without_secret_values(item) for item in value]
    if isinstance(value, tuple):
        return [_without_secret_values(item) for item in value]
    return value


def _merge_predecessor_outputs(
    graph: DagGraph, state: WalkerState, node_id: str, *, include_assets: bool = True
) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for edge in graph.in_edges.get(node_id, []):
        if (edge.source, edge.target, edge.branch_label) in state.dead_edges:
            continue
        # Phase 2 gate: with authoritative binding OFF, an ``asset`` node's
        # output does not contribute to the merge (the collection reaches a
        # consumer only via a flag-ON inputs_map VariableRef) — so retrieval
        # keeps its implicit workspace resolution, byte-identical to Phase 1.
        if not include_assets:
            src_node = graph.nodes.get(edge.source)
            if src_node is not None and src_node.kind == "asset":
                continue
        if edge.source not in state.node_outputs:
            continue
        upstream = state.node_outputs[edge.source]
        if isinstance(upstream, dict):
            merged.update(upstream)
        else:
            # Object-input handlers can still address a primitive predecessor
            # explicitly as ``value``; transparent sinks bypass this adapter.
            merged["value"] = upstream
    return merged


def _collect_terminal_output(graph: DagGraph, state: WalkerState) -> Any:
    """Output = merge of every ``sink`` node; if no sink, last executed
    node's output; if empty, the accumulated ctx input.
    """
    sinks = [nid for nid, n in graph.nodes.items() if n.kind == "sink"]
    if sinks:
        settled_sinks = [sid for sid in sinks if sid in state.node_outputs]
        if len(settled_sinks) == 1:
            return state.node_outputs[settled_sinks[0]]
        out: Dict[str, Any] = {}
        saw_output = False
        for sid in settled_sinks:
            payload = state.node_outputs[sid]
            saw_output = True
            if isinstance(payload, dict):
                out.update(payload)
            else:
                # Multiple primitive sinks cannot be losslessly merged as a
                # flat object.  Keep each value under its stable node id.
                out[sid] = payload
        if saw_output:
            return out
    # Fall back to last done node's output.
    for nid in reversed(list(state.done)):
        if nid in state.node_outputs:
            return state.node_outputs[nid]
    return dict(state.ctx.get("input") or {})


def _envelope_rows(payload: Any) -> Optional[int]:
    """Row count of the first dataset envelope in a payload, if there is one.

    Datasets travel by reference (``{dataset_id, rows, schema}``), so the size
    of what a node read and of what it wrote is already on the wire — this only
    finds it, one level deep, the same way the serving wrappers find their
    input dataset.
    """

    def _rows(candidate: Any) -> Optional[int]:
        if not isinstance(candidate, dict) or not candidate.get("dataset_id"):
            return None
        rows = candidate.get("rows")
        if isinstance(rows, bool) or not isinstance(rows, (int, float)):
            return None
        return int(rows)

    direct = _rows(payload)
    if direct is not None:
        return direct
    if not isinstance(payload, dict):
        return None
    for key, value in payload.items():
        if isinstance(key, str) and key.startswith("_"):
            continue
        nested = _rows(value)
        if nested is not None:
            return nested
    return None


def _metric_block(payload: Any) -> Optional[Dict[str, Any]]:
    """A ``{key, value}`` primary metric, as a model reference carries it."""

    if not isinstance(payload, dict):
        return None
    metric = payload.get("metric")
    if not isinstance(metric, dict):
        return None
    key = metric.get("key")
    value = metric.get("value")
    if not isinstance(key, str) or not key:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return {"key": key, "value": float(value)}


def _node_data_badge(
    node_input: Optional[Dict[str, Any]], result: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """What the canvas badges a settled node with, read off its envelopes.

    The numbers are not computed here and they are not new: a transform node
    already receives a dataset envelope and returns one, a training node returns
    its model reference with the primary metric, a serving node names the
    version that answered. This only lifts them into the ``node_end``
    checkpoint, so the badge is one SSE frame rather than a fetch per node —
    which is what lets the figures land on the graph as the run walks it.
    """

    output = result.get("output")
    badge: Dict[str, Any] = {}
    rows_in = _envelope_rows(node_input)
    if rows_in is not None:
        badge["rows_in"] = rows_in
    rows_out = _envelope_rows(output)
    if rows_out is not None:
        badge["rows_out"] = rows_out
    if isinstance(output, dict):
        # The dataset a node WROTE, so the surface reading the badge can open it
        # without another walk of the graph. Datasets travel by reference here,
        # which is exactly why the reference is worth lifting: the canvas can
        # then show a transform's or a score's actual rows.
        written = output.get("dataset_id")
        if isinstance(written, str) and written:
            badge["dataset_id"] = written
        # A training node's own metric; a serving node reports the model that
        # answered under ``model``/``served``, and its metric is that version's.
        metric = _metric_block(output)
        served = output.get("model") or output.get("served")
        if metric is not None:
            badge["metric"] = metric
        if isinstance(output.get("model_id"), str) and output["model_id"]:
            badge["model_id"] = output["model_id"]
        if isinstance(served, dict):
            slug = served.get("slug") or served.get("name")
            version = served.get("version")
            if isinstance(slug, str) and slug:
                badge["model"] = {
                    "slug": slug,
                    **(
                        {"version": int(version)}
                        if isinstance(version, (int, float))
                        and not isinstance(version, bool)
                        else {}
                    ),
                }
        predictions = output.get("predictions")
        if isinstance(predictions, list):
            badge["predictions"] = len(predictions)
    return badge or None


def _summarise_node_execution(
    db: DBSession,
    run: Run,
    node: DagNode,
    result: Dict[str, Any],
    state: WalkerState,
    invocations_before: int,
    node_input: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Distil whatever the handler returned into a few SSE-friendly fields.

    Returned fields are merged into the ``node_end`` checkpoint and are
    all optional — the frontend never panics on missing keys.

    * Task nodes surface ``skill_slug``, ``status``, ``latency_ms``, ``cost``
      pulled from the invocation(s) that this handler produced.
    * Decision nodes surface ``chosen_branch``.
    * Any handler that signalled a pause propagates ``pause=True``.
    * Data-plane nodes surface ``data``: rows read, rows written, the metric a
      fit produced, the model version that answered.
    """
    summary: Dict[str, Any] = {}
    if not isinstance(result, dict):
        return summary
    badge = _node_data_badge(node_input, result)
    if badge is not None:
        summary["data"] = badge
    if result.get("pause"):
        summary["pause"] = True
    if node.kind == "decision":
        out = result.get("output") or {}
        if isinstance(out, dict):
            if "chosen_branch" in out:
                summary["chosen_branch"] = out.get("chosen_branch")
            if out.get("decision_resolution"):
                summary["decision_resolution"] = out.get("decision_resolution")
        if result.get("terminal_error"):
            summary["status"] = "failed"
            summary["error"] = str(result["terminal_error"])
    new_invocations = state.invocation_ids[invocations_before:]
    if new_invocations:
        summary["invocation_id"] = new_invocations[-1]
        inv = (
            db.query(SkillInvocation).filter(SkillInvocation.id == new_invocations[-1]).first()
            if db is not None
            else None
        )
        if inv is not None:
            summary["skill_slug"] = inv.skill_slug
            summary["status"] = inv.status
            if inv.latency_ms is not None:
                summary["latency_ms"] = float(inv.latency_ms)
            if inv.cost is not None:
                summary["cost"] = float(inv.cost)
            if inv.error:
                summary["error"] = inv.error[:240]
            trace = inv.trace if isinstance(inv.trace, dict) else {}
            for key in ("effective_model", "provider", "credential_source"):
                value = trace.get(key)
                if isinstance(value, str) and value.strip():
                    summary[key] = value.strip()
    if node.kind == "agent_loop":
        summary["decide_skill"] = "decide_next_v1"
        out = result.get("output") if isinstance(result.get("output"), dict) else {}
        observations = out.get("observations") if isinstance(out.get("observations"), list) else []
        last_obs = observations[-1] if observations and isinstance(observations[-1], dict) else {}
        chosen = last_obs.get("skill")
        if isinstance(chosen, str) and chosen.strip():
            summary["chosen_skill"] = chosen.strip()
    return summary


def _append_checkpoint(db: DBSession, run: Run, entry: Dict[str, Any]) -> None:
    cps = list(run.checkpoints or [])
    entry.setdefault("t", datetime.utcnow().isoformat())
    cps.append(entry)
    run.checkpoints = cps
    db.commit()
    # Mirror to the live event bus so SSE subscribers see the event
    # within one tick of it being persisted.
    try:
        event_bus.publish(run.id, entry)
    except Exception:  # noqa: BLE001
        pass


def _terminate_interrupted_run(
    db: DBSession,
    run: Run,
    *,
    status: str,
    error: str,
) -> None:
    """Make cancellation/engine failure terminal and close live subscribers."""

    locked = (
        db.query(Run)
        .filter(Run.id == run.id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is not None:
        run = locked
    if run.status in {"completed", "failed", "cancelled"}:
        return
    now = datetime.utcnow()
    for invocation in (
        db.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id, SkillInvocation.status == "running")
        .all()
    ):
        invocation.status = "cancelled" if status == "cancelled" else "failed"
        invocation.error = invocation.error or error
        invocation.completed_at = now
    run.status = status
    run.error = run.error or error
    run.completed_at = now
    if run.started_at is not None:
        run.duration_ms = max(0.0, (now - run.started_at).total_seconds() * 1000.0)
    checkpoint = {
        "kind": "run_end",
        "t": now.isoformat(),
        "status": status,
        "error": error,
        "interrupted": True,
    }
    run.checkpoints = [*(run.checkpoints or []), checkpoint]
    db.commit()
    if run.waiting_subflows and status in {"failed", "cancelled"}:
        from .subflow_orchestration import cancel_waiting_children

        cancel_waiting_children(run.id, reason=f"parent_{status}:{error}"[:400])
    try:
        event_bus.publish(run.id, checkpoint)
        event_bus.close(run.id)
    except Exception:  # noqa: BLE001 - DB terminal state is authoritative.
        pass


def _dag_should_stop(adaptive, state: WalkerState) -> bool:
    triggers = getattr(adaptive, "triggers", None) or {}
    cost_cap = triggers.get("cost_above")
    if cost_cap is not None and state.total_cost > float(cost_cap):
        return True
    return False


def _sanitize(payload: Any, depth: int = 0) -> Any:
    """Shrink oversized ctx snapshots before persisting in a Decision row.

    Strings above 1 KiB get truncated; nested structures past depth 4 are
    summarised so a runaway ctx doesn't blow up the Decision.rationale JSON
    column.
    """
    if depth >= 4:
        return f"<truncated:{type(payload).__name__}>"
    if isinstance(payload, str):
        return payload if len(payload) <= 1024 else payload[:1024] + "…"
    if isinstance(payload, dict):
        return {k: _sanitize(v, depth + 1) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_sanitize(v, depth + 1) for v in payload[:32]]
    if isinstance(payload, (int, float, bool)) or payload is None:
        return payload
    return str(payload)[:256]
