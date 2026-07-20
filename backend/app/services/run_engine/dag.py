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
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.capability import Capability
from app.models.context import Context
from app.models.decision import Decision
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.workspace import Workspace
from app.services.membrane.enforcement import (
    EgressDisposition,
    MembraneEnforcementError,
    decide_egress,
    persist_provenance_artifact,
)
from app.services.membrane.spec import resolve_membrane_spec
from app.services.outcome.derive import derive_outcome

from .condition import ConditionError
from .condition import evaluate as evaluate_condition
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
from .variable_pool import (
    VariablePool,
    VariableResolutionError,
    apply_inputs_map,
    apply_outputs_map,
    resolve_selector,
    selector_segments,
)

logger = get_logger(__name__)


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
_CONTROL_KINDS: Tuple[str, ...] = (
    "decision",
    "fork",
    "join",
    "retry",
    "hitl",
    "subflow",
    "loop",
)


def _workspace_strict_dag_enabled(workspace: Optional[Workspace]) -> bool:
    raw_settings = getattr(workspace, "settings", None)
    features = raw_settings.get("features") if isinstance(raw_settings, dict) else None
    return bool(
        isinstance(features, dict)
        and features.get("flow_v3_dag_authoritative") is True
    )


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
    flow = getattr(system, "flow_definition", None) or {}
    if not isinstance(flow, dict):
        return False
    if int(flow.get("schema_version") or 0) < 2:
        return False
    nodes = flow.get("nodes") or []
    if not isinstance(nodes, list):
        return False
    if any((isinstance(n, dict) and (n.get("kind") in _CONTROL_KINDS)) for n in nodes):
        return True
    return (
        int(flow.get("schema_version") or 0) >= 3
        and flow.get("io_mode") == "strict"
        and _workspace_strict_dag_enabled(workspace)
    )


# ---------------------------------------------------------------------------
# Graph model
# ---------------------------------------------------------------------------
@dataclass
class DagNode:
    id: str
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
            kind = n.get("kind") or "task"
            data = n.get("data") or {}
            config = n.get("config") or {}
            skill_slug: Optional[str] = None
            if isinstance(config, dict):
                skill_slug = (
                    config.get("skill_slug") or config.get("skill", {}).get("slug")
                    if isinstance(config.get("skill"), dict)
                    else config.get("skill_slug")
                )
            if not skill_slug and isinstance(data, dict):
                # Builder-authored task nodes carry the bound skill under
                # data.bound_skill_slug (see workflow-editor.component).
                skill_slug = data.get("bound_skill_slug") or data.get("skill_slug")
            nodes[nid] = DagNode(
                id=nid,
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


# ---------------------------------------------------------------------------
# Walker state
# ---------------------------------------------------------------------------
@dataclass
class WalkerState:
    """Serialisable DAG walker state — persisted at every HITL pause."""

    node_outputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
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

        system = db.query(System).filter(System.id == run.system_id).first()
        if not system:
            return _fail(db, run, "system_not_found")

        workspace = (
            db.query(Workspace).filter(Workspace.id == (system.workspace_id or run.workspace_id)).first()
            if (system.workspace_id or run.workspace_id)
            else None
        )

        # Prefer a pre-existing immutable snapshot (replay/retry); a new Run
        # falls back to the current System graph and snapshots it below.
        flow = run.flow_snapshot or system.flow_definition or {}
        graph = DagGraph.from_flow_definition(flow)
        graph.strict_authoritative = (
            graph.io_mode == "strict" and _workspace_strict_dag_enabled(workspace)
        )
        if not graph.nodes:
            return _fail(db, run, "empty_flow")

        capability = (
            db.query(Capability).filter(Capability.id == system.capability_id).first()
            if system.capability_id
            else None
        )
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
        run.started_at = run.started_at or datetime.utcnow()
        _snapshot_run_flow(db, run, system)
        db.commit()

        initial_ctx = _build_initial_ctx(db, run, system, capability)
        _attach_authoritative_membrane(initial_ctx, control)
        state = WalkerState(
            ctx=initial_ctx,
            pending_counts={nid: len(graph.in_edges[nid]) for nid in graph.nodes},
            start_monotonic=time.monotonic(),
        )
        _seed_pool(db, state.pool, run, system, workspace=workspace)
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


async def resume_run_dag(run_id: str, *, decision_id: Optional[str] = None) -> Dict[str, Any]:
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

        system = db.query(System).filter(System.id == run.system_id).first()
        if not system:
            return _fail(db, run, "system_not_found")

        workspace = (
            db.query(Workspace).filter(Workspace.id == (system.workspace_id or run.workspace_id)).first()
            if (system.workspace_id or run.workspace_id)
            else None
        )

        # HITL resumes obey the immutable execution contract.
        flow = run.flow_snapshot or system.flow_definition or {}
        graph = DagGraph.from_flow_definition(flow)
        graph.strict_authoritative = (
            graph.io_mode == "strict" and _workspace_strict_dag_enabled(workspace)
        )
        state = WalkerState.from_payload(pause_cp.get("state") or {})
        state.start_monotonic = time.monotonic()

        capability = (
            db.query(Capability).filter(Capability.id == system.capability_id).first()
            if system.capability_id
            else None
        )
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

        dec = None
        target_decision_id = decision_id or pause_cp.get("decision_id")
        if target_decision_id:
            dec = db.query(Decision).filter(Decision.id == target_decision_id).first()
        approved = bool(dec and dec.status in ("accepted", "applied"))
        rejected = bool(dec and dec.status == "rejected")

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

        run.status = "running"
        db.commit()
        _append_checkpoint(
            db,
            run,
            {
                "kind": "hitl_resume",
                "node_id": hitl_node_id,
                "decision_status": dec.status if dec else None,
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
            serial_kind = kind in ("hitl", "loop") or (
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
                if outcome.get("membrane_blocked"):
                    return _fail(db, run, run.error or "membrane_policy_block")
                _settle_node(graph, state, nid, outcome)
                if outcome.get("pause"):
                    if outcome.get("wait_subflow"):
                        return _emit_subflow_pause(db, run, state, outcome)
                    return _emit_hitl_pause(db, run, state, outcome)
                if _should_debug_pause(graph, state, nid):
                    return _emit_debug_pause(db, run, state, nid)

        for nid in serial:
            outcome = await _execute_node(db, run, graph.nodes[nid], graph, state, control=control)
            if outcome.get("membrane_blocked"):
                return _fail(db, run, run.error or "membrane_policy_block")
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
    last_output: Dict[str, Any],
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
        last_output["_membrane_provenance"] = evidence
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
    node_output = outcome.get("output") or {}
    state.node_outputs[node_id] = node_output
    # P1 — publish this node's output into the typed pool. We always expose
    # the node's own output under its node id (so downstream selectors of the
    # form ``{node_id, path}`` resolve) and, when the node declared an
    # ``outputs_map``, also write the mapped namespaced slices. Both are no-ops
    # for downstream behaviour on legacy flows (nothing reads the pool unless
    # a node has an ``inputs_map``).
    node = graph.nodes.get(node_id)
    if node is not None:
        state.pool.set_namespace(node_id, node_output if isinstance(node_output, dict) else {})
        apply_outputs_map(node.config, node_output, state.pool)
    inactive = set(outcome.get("inactive_branches") or [])
    for edge in graph.out_edges.get(node_id, []):
        label = edge.branch_label or ""
        if label and label in inactive:
            state.dead_edges.add((edge.source, edge.target, label))
            # Kill the successor entirely by propagating the dead edge
            # through its pending count: we still need to decrement so the
            # counter reaches 0, otherwise the branch's tail would dangle
            # forever. Downstream nodes whose only inputs come from dead
            # edges therefore become "ready" but execute as no-ops (the
            # `_execute_node` dispatcher checks edge activity).
            state.pending_counts[edge.target] = max(0, state.pending_counts.get(edge.target, 0) - 1)
            continue
        state.pending_counts[edge.target] = max(0, state.pending_counts.get(edge.target, 0) - 1)


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
        "last_output": state.node_outputs.get(node_id) or {},
        "state": state.to_payload(),
    }
    _append_checkpoint(db, run, checkpoint)
    run.status = "debug_pending"
    db.commit()
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

        system = db.query(System).filter(System.id == run.system_id).first()
        if not system:
            return _fail(db, run, "system_not_found")

        workspace = (
            db.query(Workspace).filter(Workspace.id == (system.workspace_id or run.workspace_id)).first()
            if (system.workspace_id or run.workspace_id)
            else None
        )

        # Debug resumes obey the immutable graph captured at first execution.
        flow = run.flow_snapshot or system.flow_definition or {}
        graph = DagGraph.from_flow_definition(flow)
        graph.strict_authoritative = (
            graph.io_mode == "strict" and _workspace_strict_dag_enabled(workspace)
        )
        state = WalkerState.from_payload(pause_cp.get("state") or {})
        state.start_monotonic = time.monotonic()

        if breakpoints is not None:
            state.breakpoints = {str(b) for b in breakpoints if b}

        if action == "continue":
            state.debug_mode = "breakpoints" if state.breakpoints else None
        elif action == "step":
            state.debug_mode = "step"
        elif action == "stop":
            _fail(db, run, reason="debugger_stopped")
            return {"id": run.id, "status": "cancelled"}
        else:
            return {"error": "invalid_action", "action": action}

        capability = (
            db.query(Capability).filter(Capability.id == system.capability_id).first()
            if system.capability_id
            else None
        )
        control = _load_control_policy(db, system)
        adaptive = _load_adaptive_policy(db, system)

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
    state.accumulated_ms += (time.monotonic() - state.start_monotonic) * 1000
    checkpoint = {
        "kind": "hitl_pause",
        "t": datetime.utcnow().isoformat(),
        "node_id": outcome.get("node_id"),
        "decision_id": outcome.get("decision_id"),
        "prompt": outcome.get("prompt"),
        "state": state.to_payload(),
        "membrane_egress": bool(outcome.get("membrane_egress")),
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
        _append_checkpoint(db, run, checkpoint)
        run.status = "hitl_pending"
        db.commit()
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

    invocations_before = len(state.invocation_ids)
    result: Dict[str, Any] = {}
    try:
        if node.kind == "source":
            output = dict(state.ctx.get("input") or run.input_ref or {})
            result = {"output": output}
            return result

        if node.kind == "sink":
            result = {"output": node_input}
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
            result = _run_decision(
                node,
                graph,
                state,
                node_input,
                pool=node_pool,
                strict=strict,
            )
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
        summary = _summarise_node_execution(db, run, node, result, state, invocations_before)
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
        return {"output": invocation.output_ref or {}}
    # On failure / skipped: pass through upstream data but preserve the error
    # in the ctx for downstream decision nodes.
    err_output = {
        **(last_output or {}),
        "_error": invocation.error,
        "_status": invocation.status,
    }
    return {"output": err_output}


def _run_decision(
    node: DagNode,
    graph: DagGraph,
    state: WalkerState,
    merged_input: Dict[str, Any],
    *,
    pool: Optional[VariablePool] = None,
    strict: bool = False,
) -> Dict[str, Any]:
    """Evaluate each branch condition; return the list of inactive branch
    labels so the walker can kill the corresponding out-edges.
    """
    config = node.config or {}
    branches = config.get("branches") or []
    default_label = config.get("default_branch")
    # Strict conditions are evaluated from the node's typed payload. Built-in
    # and declared namespaces remain addressable through the pool. Overlay
    # preserves the historical flat ctx merge.
    ctx_with_input = (
        dict(merged_input or {})
        if strict
        else {**state.ctx, **(merged_input or {})}
    )

    chosen: Optional[str] = None
    evaluations: List[Dict[str, Any]] = []
    for b in branches:
        if not isinstance(b, dict):
            continue
        label = b.get("label") or ""
        cond = b.get("condition") or ""
        try:
            value = evaluate_condition(cond, ctx_with_input, pool=pool or state.pool)
        except ConditionError as exc:
            evaluations.append({"label": label, "error": str(exc), "value": False})
            value = False
        else:
            evaluations.append({"label": label, "value": bool(value)})
        if value and chosen is None:
            chosen = label

    if chosen is None and default_label:
        chosen = default_label

    # All outgoing branch edge labels that are NOT chosen become inactive.
    out_branch_labels: Set[str] = set()
    for edge in graph.out_edges.get(node.id, []):
        if edge.kind == "branch" and edge.branch_label:
            out_branch_labels.add(edge.branch_label)
    inactive = sorted(out_branch_labels - {chosen}) if chosen else sorted(out_branch_labels)
    return {
        "output": {"chosen_branch": chosen, "evaluations": evaluations},
        "inactive_branches": inactive,
    }


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
    max_attempts = int(config.get("max_attempts") or 3)
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
            return {
                "output": {
                    **(invocation.output_ref or {}),
                    "_retry_attempts": attempt,
                }
            }
        last_error = invocation.error
        if attempt < max_attempts and backoff_ms > 0:
            await asyncio.sleep(backoff_ms / 1000.0)
    return {
        "output": {
            **(last_output or {}),
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
    max_iterations = int(config.get("max_iterations") or 1)
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
                iteration_output = invocation.output_ref or {}
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
        "approvers": approvers,
        "membrane_gate": membrane_gate,
        "ctx_snapshot": _sanitize(state.ctx),
        "upstream": _sanitize(merged),
    }
    decision = _log_decision(
        db,
        scope="run",
        target_id=run.id,
        kind="hitl_approval",
        rationale=rationale,
        status="proposed",
        title=f"HITL approval — {node.label or node.id}",
    )
    return {
        "pause": True,
        "node_id": node.id,
        "decision_id": decision.id if decision else None,
        "prompt": prompt,
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
        return dict(upstream)
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

    child_input = _build_subflow_input(config, upstream or {}, state.pool)
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
            scope="run",
            target_id=run.id,
            kind="policy_shadow",
            rationale={"delegation": target_id, "node_id": node.id, "reason": acl_reason},
        )

    # Provenance: carry the delegating node id inside the child input_ref to
    # avoid a DDL migration (Run already has parent_run_id).
    target_contract = (
        (target.flow_definition or {}).get("output_contract")
        if isinstance(target.flow_definition, dict)
        else None
    )
    if not isinstance(target_contract, dict):
        target_contract = config.get("output_contract")
    child_input["_delegation"] = {
        "parent_run_id": run.id,
        "delegation_node_id": node.id,
        "branch": branch,
        "output_contract": output_contract,
        "target_output_contract": target_contract if isinstance(target_contract, dict) else None,
        "contract_enforced": contract_enforced,
    }

    iteration = config.get(
        "iteration",
        (upstream or {}).get("_loop_iteration", (upstream or {}).get("iteration", 0)),
    )
    logical_key = delegation_key(run.id, node.id, iteration, branch)
    child = db.query(Run).filter(Run.delegation_key == logical_key).first()
    if child is None:
        child = Run(
            workspace_id=run.workspace_id,
            system_id=target_id,
            parent_run_id=run.id,
            input_ref=child_input,
            status="pending",
            trigger="subflow",
            delegation_key=logical_key,
            delegation_node_id=node.id,
            delegation_branch=branch,
        )
        db.add(child)
        try:
            db.commit()  # payload and logical key are durable before broker dispatch
        except IntegrityError:
            # Concurrent redelivery: the unique logical key owns exactly one
            # child. Recover that row instead of creating a second execution.
            db.rollback()
            child = db.query(Run).filter(Run.delegation_key == logical_key).one()
    child_id = child.id
    # Record the mapping BEFORE executing so that if the child pauses for HITL
    # the parent's serialised checkpoint already carries the child run id and a
    # later resume can find it (rather than spawning a duplicate).
    state.subflow_children[node.id] = child_id

    parent_system = db.query(System).filter(System.id == run.system_id).first()
    if parent_system is not None and subflow_celery_enabled(parent_system):
        from .engine import schedule_subflow_run

        waiting = dict(run.waiting_subflows or {})
        strategy = str(config.get("join_strategy") or config.get("strategy") or "all").lower()
        if strategy not in {"all", "any", "race"}:
            return {"output": {"_error": "invalid_subflow_join_strategy", "strategy": strategy}}
        meta = dict(waiting.get("_meta") or {})
        current_strategy = meta.get("strategy")
        if current_strategy and current_strategy != strategy:
            return {"output": {"_error": "mixed_subflow_join_strategies"}}
        meta.update({"strategy": strategy, "state": "waiting"})
        waiting["_meta"] = meta
        entry = dict(waiting.get(logical_key) or {})
        entry.update({"child_run_id": child_id, "node_id": node.id, "branch": branch,
                      "iteration": iteration, "strategy": strategy,
                      "status": child.status, "dispatch_state": "persisted"})
        waiting[logical_key] = entry
        run.waiting_subflows = waiting
        db.commit()
        if not child.celery_task_id:
            try:
                child.celery_task_id = schedule_subflow_run(child_id)
                entry["celery_task_id"] = child.celery_task_id
                entry["dispatch_state"] = "dispatched"
                waiting[logical_key] = entry
                run.waiting_subflows = waiting
                db.commit()
            except RuntimeError:
                entry["dispatch_state"] = "ambiguous"
                waiting[logical_key] = entry
                run.waiting_subflows = waiting
                db.commit()
        return {"pause": True, "wait_subflow": True, "node_id": node.id, "child_run_id": child_id,
                "prompt": "Subflow dispatched; awaiting durable completion"}

    # Execute the child as its own graph (in-process). Celery fan-out is wired
    # via ``schedule_subflow_run`` but the synchronous path is what merges back.
    target_workspace = (
        db.query(Workspace).filter(Workspace.id == target.workspace_id).first()
        if target.workspace_id
        else None
    )
    if should_use_dag(target, target_workspace):
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
        target = db.query(System).filter(System.id == child.system_id).first()
        target_workspace = (
            db.query(Workspace).filter(Workspace.id == target.workspace_id).first()
            if target is not None and target.workspace_id
            else None
        )
        if target is not None and should_use_dag(target, target_workspace):
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

    context = (
        db.query(Context).filter(Context.id == system.context_id).first()
        if system.context_id
        else None
    )
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
        upstream = state.node_outputs.get(edge.source)
        if upstream:
            merged.update(upstream)
    return merged


def _collect_terminal_output(graph: DagGraph, state: WalkerState) -> Dict[str, Any]:
    """Output = merge of every ``sink`` node; if no sink, last executed
    node's output; if empty, the accumulated ctx input.
    """
    sinks = [nid for nid, n in graph.nodes.items() if n.kind == "sink"]
    if sinks:
        out: Dict[str, Any] = {}
        for sid in sinks:
            payload = state.node_outputs.get(sid) or {}
            out.update(payload)
        if out:
            return out
    # Fall back to last done node's output.
    for nid in reversed(list(state.done)):
        payload = state.node_outputs.get(nid)
        if payload:
            return payload
    return dict(state.ctx.get("input") or {})


def _summarise_node_execution(
    db: DBSession,
    run: Run,
    node: DagNode,
    result: Dict[str, Any],
    state: WalkerState,
    invocations_before: int,
) -> Dict[str, Any]:
    """Distil whatever the handler returned into a few SSE-friendly fields.

    Returned fields are merged into the ``node_end`` checkpoint and are
    all optional — the frontend never panics on missing keys.

    * Task nodes surface ``skill_slug``, ``status``, ``latency_ms``, ``cost``
      pulled from the invocation(s) that this handler produced.
    * Decision nodes surface ``chosen_branch``.
    * Any handler that signalled a pause propagates ``pause=True``.
    """
    summary: Dict[str, Any] = {}
    if not isinstance(result, dict):
        return summary
    if result.get("pause"):
        summary["pause"] = True
    if node.kind == "decision":
        out = result.get("output") or {}
        if isinstance(out, dict) and out.get("chosen_branch"):
            summary["chosen_branch"] = out.get("chosen_branch")
    new_invocations = state.invocation_ids[invocations_before:]
    if new_invocations:
        inv = db.query(SkillInvocation).filter(SkillInvocation.id == new_invocations[-1]).first()
        if inv is not None:
            summary["skill_slug"] = inv.skill_slug
            summary["status"] = inv.status
            if inv.latency_ms is not None:
                summary["latency_ms"] = float(inv.latency_ms)
            if inv.cost is not None:
                summary["cost"] = float(inv.cost)
            if inv.error:
                summary["error"] = inv.error[:240]
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
