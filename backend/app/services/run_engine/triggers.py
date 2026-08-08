"""Event-trigger registry and dispatch — Flow Builder sources DAG, Phase 3.

This module makes ``source`` trigger nodes (e.g. ``source.sftp_arrival``,
``source.deposit_promoted``) *executable*: an emission hook fires an
``event_kind`` for a workspace, this service resolves which System(s) declared a
matching trigger node in their ``flow_definition`` and, subject to the
non-negotiable governance invariant, either JOURNALS a ``simulated`` Run
(dry-run, Phase 3a) or dispatches a REAL Run via ``schedule_run`` (live,
Phase 3b).

Master switch: ``settings.enable_event_triggers`` (default OFF). When OFF this
module is completely inert — ``emit_event`` returns ``[]`` before touching the
DB, so deploy behaviour is byte-identical to Phase 2.

GOVERNANCE INVARIANT (docs/adr-flow-source-nodes.md §6 — enforced in code):

* SFTP promotion stays an EXPLICIT operator action. ``sftp.file_arrived`` may
  ONLY trigger analysis / notification runs — NEVER ingestion (a side effect).
* Only ``deposit.promoted`` (already human-validated) may feed a downstream run
  that produces a side effect, and any such side effect MUST be gated by an
  ``hitl`` node (pause + ``proposed`` Decision) on its path.
* This is encoded as a per-``event_kind`` allowlist (:data:`_GOVERNANCE`):
  each event declares the effect classes it permits downstream and whether a
  side effect requires an ``hitl`` gate. Anything outside the allowlist is
  rejected/skipped — the flag cannot relax it.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import SessionLocal
from app.models.decision import Decision
from app.models.run import Run
from app.models.system import System
from app.models.trigger_event_claim import TriggerEventClaim
from app.models.workspace import Workspace
from app.services.system_catalog_bindings import (
    SystemCatalogBindingError,
    resolve_persisted_system_catalog_bindings,
)
from app.services.systems import flow_ingress, flow_publication

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Trigger taxonomy
# ---------------------------------------------------------------------------
EVENT_SFTP_FILE_ARRIVED = "sftp.file_arrived"
EVENT_DEPOSIT_PROMOTED = "deposit.promoted"
EVENT_WEBHOOK_RECEIVED = "webhook.received"
EVENT_SCHEDULE_FIRED = "schedule.fired"

# A ``kind == 'source'`` node is an ACTIVE trigger when its ``type`` is one of
# these; the value is the ``event_kind`` it listens for. ``source.chat_request``
# / ``input`` sources are NOT triggers (they are reasoning-plane entry points),
# so they never appear here and are ignored by the registry.
# ``source.schedule`` is registered for graph/visibility parity; cron firing is
# table-driven via ``run_schedules`` + ``scheduler_tick`` (not ``emit_event``).
TRIGGER_TYPE_TO_EVENT: Dict[str, str] = {
    "source.sftp_arrival": EVENT_SFTP_FILE_ARRIVED,
    "source.deposit_promoted": EVENT_DEPOSIT_PROMOTED,
    "source.webhook": EVENT_WEBHOOK_RECEIVED,
    "source.schedule": EVENT_SCHEDULE_FIRED,
}


# ---------------------------------------------------------------------------
# Governance allowlist (per event_kind)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EventGovernance:
    """Per-``event_kind`` allowlist that encodes the ADR governance invariant.

    ``permitted_effects`` are the node *effect classes* an auto-triggered run of
    this event may contain (see :func:`_node_effect`). ``require_hitl_for_side_effects``
    forces any permitted side effect to sit downstream of an ``hitl`` node.
    """

    event_kind: str
    permitted_effects: Set[str]
    require_hitl_for_side_effects: bool


# Effect classes. ``ingestion`` is the only SIDE EFFECT (it writes data into a
# collection); ``analysis`` / ``notification`` are read-only.
_EFFECT_INGESTION = "ingestion"
_EFFECT_ANALYSIS = "analysis"
_EFFECT_NOTIFICATION = "notification"

_GOVERNANCE: Dict[str, EventGovernance] = {
    # SFTP arrival is NOT human-validated → analysis / notification ONLY, never
    # ingestion. This is the hard invariant: an SFTP arrival can never, by
    # itself, cause data to enter a collection.
    EVENT_SFTP_FILE_ARRIVED: EventGovernance(
        event_kind=EVENT_SFTP_FILE_ARRIVED,
        permitted_effects={_EFFECT_ANALYSIS, _EFFECT_NOTIFICATION},
        require_hitl_for_side_effects=True,
    ),
    # A promoted file has already passed an explicit operator validation, so a
    # downstream run MAY carry a side effect — but only when it is gated by an
    # ``hitl`` node (pause + proposed Decision) before the effect is applied.
    EVENT_DEPOSIT_PROMOTED: EventGovernance(
        event_kind=EVENT_DEPOSIT_PROMOTED,
        permitted_effects={_EFFECT_ANALYSIS, _EFFECT_NOTIFICATION, _EFFECT_INGESTION},
        require_hitl_for_side_effects=True,
    ),
    # Generic inbound webhook (incl. RPA job callbacks). Side effects remain
    # HITL-gated — same posture as a human-validated deposit promotion.
    EVENT_WEBHOOK_RECEIVED: EventGovernance(
        event_kind=EVENT_WEBHOOK_RECEIVED,
        permitted_effects={_EFFECT_ANALYSIS, _EFFECT_NOTIFICATION, _EFFECT_INGESTION},
        require_hitl_for_side_effects=True,
    ),
    # Declared for registry completeness; cron uses ``scheduler_tick`` directly.
    EVENT_SCHEDULE_FIRED: EventGovernance(
        event_kind=EVENT_SCHEDULE_FIRED,
        permitted_effects={_EFFECT_ANALYSIS, _EFFECT_NOTIFICATION, _EFFECT_INGESTION},
        require_hitl_for_side_effects=True,
    ),
}

# Node signals that mark a WRITE / ingestion side effect.
_INGESTION_NODE_TYPES = {"ingest", "ingestion", "index", "promote", "write"}
_INGESTION_SKILL_PREFIXES = ("document_ingest", "ingest", "collection_index", "promote")
_INGESTION_EFFECT_TOKENS = {"ingestion", "write", "side_effect"}
_NOTIFICATION_EFFECT_TOKENS = {"notification", "notify"}


def _node_effect(node: Dict[str, Any]) -> str:
    """Classify a node's effect: ``ingestion`` (side effect), ``notification``
    or ``analysis`` (default, read-only).

    Precedence: an explicit ``config.effect`` / ``effect`` marker wins, then the
    node ``type``, then a bound ingestion skill slug. Everything else is
    read-only ``analysis`` — retrieval, generation, evaluation, routing.
    """
    if not isinstance(node, dict):
        return _EFFECT_ANALYSIS
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    explicit = str(config.get("effect") or node.get("effect") or "").lower()
    if explicit in _INGESTION_EFFECT_TOKENS:
        return _EFFECT_INGESTION
    if explicit in _NOTIFICATION_EFFECT_TOKENS:
        return _EFFECT_NOTIFICATION
    if explicit in ("analysis", "read", "read_only"):
        return _EFFECT_ANALYSIS
    ntype = str(node.get("type") or "").lower()
    if ntype in _INGESTION_NODE_TYPES:
        return _EFFECT_INGESTION
    slug = str(config.get("skill_slug") or "").lower()
    if any(slug.startswith(prefix) for prefix in _INGESTION_SKILL_PREFIXES):
        return _EFFECT_INGESTION
    return _EFFECT_ANALYSIS


# ---------------------------------------------------------------------------
# Flow inspection helpers
# ---------------------------------------------------------------------------
def _flow_nodes(flow: Any) -> List[Dict[str, Any]]:
    if not isinstance(flow, dict):
        return []
    nodes = flow.get("nodes")
    return [n for n in nodes if isinstance(n, dict)] if isinstance(nodes, list) else []


def _flow_edges(flow: Any) -> List[Dict[str, Any]]:
    if not isinstance(flow, dict):
        return []
    edges = flow.get("edges")
    return [e for e in edges if isinstance(e, dict)] if isinstance(edges, list) else []


def _trigger_nodes(flow: Any) -> List[Dict[str, Any]]:
    """Return the ACTIVE trigger source nodes of a flow.

    A node is an active trigger when ``kind == 'source'``, its ``type`` is a
    known trigger type, and it is not explicitly disabled
    (``config.trigger_enabled == False``). The Phase-1 ``data.declarative``
    marker is UI provenance only and does NOT disable the trigger — execution
    is governed by the master flag + per-System mode, not by that marker.
    """
    out: List[Dict[str, Any]] = []
    for node in _flow_nodes(flow):
        if node.get("kind") != "source":
            continue
        if str(node.get("type") or "") not in TRIGGER_TYPE_TO_EVENT:
            continue
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        if config.get("trigger_enabled") is False:
            continue
        out.append(node)
    return out


def _trigger_event_kinds(flow: Any) -> Set[str]:
    return {TRIGGER_TYPE_TO_EVENT[str(n.get("type"))] for n in _trigger_nodes(flow)}


def dispatch_trigger_ingresses(flow: Any) -> Dict[str, List[str]]:
    """Map each ``event_kind`` to the active trigger node ids listening for it.

    A trigger node id doubles as the published ingress id a delivery may name,
    so the dispatch path and the readiness read model resolve one candidate set.
    """
    out: Dict[str, List[str]] = defaultdict(list)
    for node in _trigger_nodes(flow):
        node_id = str(node.get("id") or "")
        if node_id:
            out[TRIGGER_TYPE_TO_EVENT[str(node.get("type"))]].append(node_id)
    return dict(out)


def ingress_kind_for_event(event_kind: str) -> str:
    """The published-ingress kind an event delivery presents at the boundary."""
    return "http" if event_kind == EVENT_WEBHOOK_RECEIVED else "event"


def _edge_endpoints(edge: Dict[str, Any]) -> Tuple[str, str]:
    src = str(edge.get("from") or edge.get("source") or "")
    dst = str(edge.get("to") or edge.get("target") or "")
    return src, dst


def _reachable_from(start_ids: List[str], edges: List[Dict[str, Any]]) -> Set[str]:
    """Node ids reachable (descendants) from any of ``start_ids`` — excludes the
    start ids themselves unless they form a cycle."""
    adj: Dict[str, List[str]] = defaultdict(list)
    for edge in edges:
        src, dst = _edge_endpoints(edge)
        if src and dst:
            adj[src].append(dst)
    seen: Set[str] = set()
    stack = list(start_ids)
    while stack:
        current = stack.pop()
        for succ in adj.get(current, []):
            if succ not in seen:
                seen.add(succ)
                stack.append(succ)
    return seen


def _ancestors_of(target: str, edges: List[Dict[str, Any]]) -> Set[str]:
    rev: Dict[str, List[str]] = defaultdict(list)
    for edge in edges:
        src, dst = _edge_endpoints(edge)
        if src and dst:
            rev[dst].append(src)
    seen: Set[str] = set()
    stack = [target]
    while stack:
        current = stack.pop()
        for pred in rev.get(current, []):
            if pred not in seen:
                seen.add(pred)
                stack.append(pred)
    return seen


# ---------------------------------------------------------------------------
# Governance verdict
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GovernanceVerdict:
    eligible: bool
    reason: str


def evaluate_governance(event_kind: str, flow: Any) -> GovernanceVerdict:
    """Decide whether ``event_kind`` may trigger a run of ``flow``.

    Enforces the ADR invariant in code: the flow must contain an active trigger
    node for the event, and every node reachable from that trigger must carry an
    effect the event permits; a permitted side effect must additionally be gated
    by an ``hitl`` ancestor.
    """
    gov = _GOVERNANCE.get(event_kind)
    if gov is None:
        return GovernanceVerdict(False, "unknown_event_kind")

    nodes = _flow_nodes(flow)
    node_by_id = {str(n.get("id")): n for n in nodes if n.get("id")}
    trigger_ids = [
        str(n.get("id"))
        for n in _trigger_nodes(flow)
        if TRIGGER_TYPE_TO_EVENT[str(n.get("type"))] == event_kind and n.get("id")
    ]
    if not trigger_ids:
        return GovernanceVerdict(False, "no_active_trigger_node")

    edges = _flow_edges(flow)
    downstream_ids = _reachable_from(trigger_ids, edges)
    hitl_ids = {nid for nid, n in node_by_id.items() if n.get("kind") == "hitl"}

    for nid in downstream_ids:
        node = node_by_id.get(nid)
        if node is None:
            continue
        effect = _node_effect(node)
        if effect not in gov.permitted_effects:
            # SFTP arrival hitting an ingestion node is the canonical rejection.
            return GovernanceVerdict(False, f"effect_not_permitted:{effect}:{nid}")
        if effect == _EFFECT_INGESTION and gov.require_hitl_for_side_effects:
            if not hitl_ids:
                return GovernanceVerdict(False, f"side_effect_without_hitl:{nid}")
            if not (_ancestors_of(nid, edges) & hitl_ids):
                return GovernanceVerdict(False, f"side_effect_not_gated_by_hitl:{nid}")

    return GovernanceVerdict(True, "eligible")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def build_registry(
    db: DBSession, *, workspace_id: Optional[str] = None
) -> Dict[Tuple[str, Optional[str]], List[str]]:
    """Map ``(event_kind, workspace_id) -> [system_id]`` for every System whose
    ``flow_definition`` declares an active trigger node.

    Only ``active`` Systems are registered (a draft/paused/retired System never
    fires). Optionally scoped to a single ``workspace_id`` to keep the scan
    small on the emission hot path.
    """
    query = db.query(System).filter(System.status == "active")
    if workspace_id is not None:
        query = query.filter(System.workspace_id == workspace_id)
    registry: Dict[Tuple[str, Optional[str]], List[str]] = defaultdict(list)
    for system in query.all():
        for event_kind in _trigger_event_kinds(system.flow_definition or {}):
            key = (event_kind, system.workspace_id)
            if system.id not in registry[key]:
                registry[key].append(system.id)
    return dict(registry)


# ---------------------------------------------------------------------------
# Idempotence (dedup)
# ---------------------------------------------------------------------------
_TRIGGER_META_KEY = "_event_trigger"


@dataclass(frozen=True)
class _PublishedTriggerEvidence:
    """Published identity accepted under the locked System row."""

    flow: Dict[str, Any]
    version_id: str
    flow_sha256: str


class _TriggerDeliveryDuplicate(RuntimeError):
    """Internal control flow carrying a durable prior delivery result."""

    def __init__(self, result: Dict[str, Any]):
        super().__init__("trigger delivery already claimed")
        self.result = result


def _payload_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dedup_key(system_id: str, event_kind: str, payload: Any) -> str:
    """Idempotence key ``(system_id, event_kind, payload_hash)`` — a promoted
    file (same payload) triggers at most one run per System."""
    return f"{system_id}:{event_kind}:{_payload_hash(payload)}"


def _find_run_by_dedup(db: DBSession, system_id: str, dedup_key: str) -> Optional[Run]:
    """Return the durable claimant for one event-trigger idempotency key."""

    claimed = (
        db.query(Run)
        .filter(
            Run.system_id == system_id,
            Run.trigger_dedup_key == dedup_key,
        )
        .one_or_none()
    )
    if claimed is not None:
        return claimed

    # Rolling-upgrade compatibility only. Migration 079 backfills one
    # canonical claimant per historical key; the JSON scan keeps a mixed
    # binary window from replaying an older, not-yet-backfilled delivery.
    candidates = (
        db.query(Run)
        .filter(
            Run.system_id == system_id,
            Run.trigger == "webhook",
            Run.trigger_dedup_key.is_(None),
        )
        .all()
    )
    for run in candidates:
        meta = (run.input_ref or {}).get(_TRIGGER_META_KEY) or {}
        if meta.get("dedup_key") == dedup_key:
            return run
    return None


def _duplicate_delivery_result(
    db: DBSession,
    *,
    system_id: str,
    dedup_key: str,
) -> Dict[str, Any] | None:
    claim = (
        db.query(TriggerEventClaim)
        .filter(
            TriggerEventClaim.system_id == system_id,
            TriggerEventClaim.dedup_key == dedup_key,
        )
        .one_or_none()
    )
    if claim is not None:
        result: Dict[str, Any] = {
            "system_id": system_id,
            "status": "duplicate",
            "dedup_key": dedup_key,
            "claim_outcome": claim.outcome,
        }
        if claim.run_id:
            result["run_id"] = claim.run_id
        if claim.inbox_id:
            result["inbox_id"] = claim.inbox_id
        return result
    # Rolling upgrade compatibility for claims produced by migration 079 or
    # an older binary before migration 080 is applied.
    run = _find_run_by_dedup(db, system_id, dedup_key)
    if run is None:
        return None
    return {
        "system_id": system_id,
        "status": "duplicate",
        "run_id": run.id,
        "dedup_key": dedup_key,
        "claim_outcome": "simulated" if run.status == "simulated" else "run",
    }


def _trigger_input_ref(
    event_kind: str, dedup_key: str, payload: Any, *, mode: str, simulated: bool
) -> Dict[str, Any]:
    return {
        _TRIGGER_META_KEY: {
            "event_kind": event_kind,
            "dedup_key": dedup_key,
            "payload": payload,
            "mode": mode,
            "simulated": simulated,
            "emitted_at": datetime.utcnow().isoformat(),
        }
    }


def _commit_or_flush(db: DBSession, owns_session: bool) -> None:
    if owns_session:
        db.commit()
    else:
        db.flush()


def _journal_simulated_run(
    db: DBSession,
    system: System,
    event_kind: str,
    workspace_id: Optional[str],
    payload: Any,
    dedup_key: str,
    *,
    owns_session: bool,
) -> tuple[Run, bool]:
    """Persist a DRY-RUN Run: ``status='simulated'``, ``trigger='webhook'``, a
    visible ``trigger_simulated`` checkpoint and a ``simulated`` marker in
    ``input_ref``. The run is NEVER executed."""
    run = Run(
        id=str(uuid4()),
        workspace_id=workspace_id or system.workspace_id,
        system_id=system.id,
        capability_id=system.capability_id,
        input_ref=_trigger_input_ref(
            event_kind, dedup_key, payload, mode="dry_run", simulated=True
        ),
        status="simulated",
        trigger="webhook",
        trigger_dedup_key=dedup_key,
        checkpoints=[
            {
                "kind": "trigger_simulated",
                "t": datetime.utcnow().isoformat(),
                "event_kind": event_kind,
                "dedup_key": dedup_key,
            }
        ],
    )
    claim = TriggerEventClaim(
        id=str(uuid4()),
        workspace_id=workspace_id or system.workspace_id,
        system_id=system.id,
        dedup_key=dedup_key,
        outcome="simulated",
        run_id=run.id,
    )
    try:
        with db.begin_nested():
            db.add_all([run, claim])
            db.flush()
    except IntegrityError:
        result = _duplicate_delivery_result(
            db,
            system_id=system.id,
            dedup_key=dedup_key,
        )
        if result is None:
            raise
        existing_id = result.get("run_id")
        existing = db.get(Run, existing_id) if existing_id else None
        if existing is not None:
            return existing, False
        raise _TriggerDeliveryDuplicate(result) from None

    _commit_or_flush(db, owns_session)
    logger.info(
        "triggers: journaled simulated run",
        system_id=system.id,
        event_kind=event_kind,
        run_id=run.id,
    )
    return run, True


# ---------------------------------------------------------------------------
# Per-System execution mode + guards (Phase 3b: live execution)
# ---------------------------------------------------------------------------
TRIGGER_MODE_DRY_RUN = "dry_run"
TRIGGER_MODE_LIVE = "live"

# Rate limit: max REAL triggered runs per System per rolling hour. Overridable
# per System via ``ControlPolicy.extra['event_trigger_max_runs_per_hour']`` so
# no new table is needed.
DEFAULT_MAX_TRIGGERED_RUNS_PER_HOUR = 10
# Circuit breaker: this many CONSECUTIVE triggered-run failures trip the breaker
# (disable the trigger + file a proposed Decision).
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3

_SETTINGS_TRIGGER_KEY = "event_trigger"


def _system_trigger_settings(system: System) -> Dict[str, Any]:
    blob = system.settings if isinstance(system.settings, dict) else {}
    et = blob.get(_SETTINGS_TRIGGER_KEY)
    return et if isinstance(et, dict) else {}


def trigger_mode(system: System) -> str:
    """Per-System execution mode: ``dry_run`` (default) or ``live``.

    Read from ``system.settings['event_trigger']['mode']`` — a plain JSON
    setting so no migration is required. Anything other than the literal
    ``live`` (including absent/typo) resolves to ``dry_run`` (fail-safe).
    """
    mode = str(_system_trigger_settings(system).get("mode") or TRIGGER_MODE_DRY_RUN).lower()
    return TRIGGER_MODE_LIVE if mode == TRIGGER_MODE_LIVE else TRIGGER_MODE_DRY_RUN


def _trigger_disabled(system: System) -> bool:
    """True once the circuit breaker has disabled this System's trigger."""
    return bool(_system_trigger_settings(system).get("disabled"))


def _set_trigger_settings(system: System, **updates: Any) -> None:
    """Merge ``updates`` into ``system.settings['event_trigger']``.

    Reassigns ``system.settings`` to a NEW dict so SQLAlchemy flags the JSON
    column dirty (in-place mutation of a plain JSON dict is not tracked).
    """
    blob = dict(system.settings) if isinstance(system.settings, dict) else {}
    et = dict(blob.get(_SETTINGS_TRIGGER_KEY) or {})
    et.update(updates)
    blob[_SETTINGS_TRIGGER_KEY] = et
    system.settings = blob


def _max_runs_per_hour(db: DBSession, system: System) -> int:
    try:
        from app.services.run_engine.engine import _load_control_policy  # noqa: WPS433

        cp = _load_control_policy(db, system)
    except Exception:  # noqa: BLE001
        cp = None
    if cp is not None and isinstance(cp.extra, dict):
        val = cp.extra.get("event_trigger_max_runs_per_hour")
        if isinstance(val, (int, float)) and val > 0:
            return int(val)
    return DEFAULT_MAX_TRIGGERED_RUNS_PER_HOUR


def _count_recent_triggered_runs(db: DBSession, system_id: str, since: datetime) -> int:
    """Count REAL (non-simulated) triggered runs since ``since`` — the rate
    limit denominator. Simulated dry-run journals are excluded."""
    return (
        db.query(Run)
        .filter(
            Run.system_id == system_id,
            Run.trigger == "webhook",
            Run.status != "simulated",
            Run.started_at >= since,
        )
        .count()
    )


def _recent_triggered_run_statuses(db: DBSession, system_id: str, limit: int) -> List[str]:
    rows = (
        db.query(Run)
        .filter(Run.system_id == system_id, Run.trigger == "webhook", Run.status != "simulated")
        .order_by(Run.started_at.desc())
        .limit(limit)
        .all()
    )
    return [r.status for r in rows]


def _trip_circuit_breaker(
    db: DBSession,
    system: System,
    *,
    owns_session: bool,
) -> None:
    """Disable this System's trigger and file a ``proposed`` Decision.

    The setting and Decision share one savepoint and the caller retains
    ownership of the surrounding transaction.
    """
    try:
        with db.begin_nested():
            _set_trigger_settings(
                system,
                disabled=True,
                disabled_reason="circuit_breaker",
                disabled_at=datetime.utcnow().isoformat(),
            )
            db.add(
                Decision(
                    id=str(uuid4()),
                    workspace_id=system.workspace_id,
                    scope="system",
                    target_id=system.id,
                    kind="trigger_circuit_open",
                    status="proposed",
                    title="Event trigger disabled after repeated failures",
                    rationale={
                        "system_id": system.id,
                        "reason": "circuit_breaker",
                        "consecutive_failures": CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                    },
                    impact_estimate={},
                )
            )
            db.flush()
        _commit_or_flush(db, owns_session)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "triggers: circuit breaker decision log failed", system_id=system.id, error=str(exc)
        )
    logger.warning("triggers: circuit breaker tripped", system_id=system.id)


def _circuit_open(db: DBSession, system: System, *, owns_session: bool) -> bool:
    """Return True when the breaker is open — already disabled, OR the last
    :data:`CIRCUIT_BREAKER_FAILURE_THRESHOLD` triggered runs all failed (which
    also TRIPS it here)."""
    if _trigger_disabled(system):
        return True
    statuses = _recent_triggered_run_statuses(db, system.id, CIRCUIT_BREAKER_FAILURE_THRESHOLD)
    if len(statuses) >= CIRCUIT_BREAKER_FAILURE_THRESHOLD and all(s == "failed" for s in statuses):
        _trip_circuit_breaker(db, system, owns_session=owns_session)
        return True
    return False


def _create_triggered_run(
    db: DBSession,
    system: System,
    event_kind: str,
    workspace_id: Optional[str],
    payload: Any,
    dedup_key: str,
    *,
    published_evidence: _PublishedTriggerEvidence | None = None,
) -> Run:
    """Insert a REAL pending Run and its dispatch in the caller transaction."""
    workspace = (
        db.query(Workspace).filter(Workspace.id == (workspace_id or system.workspace_id)).first()
        if workspace_id or system.workspace_id
        else None
    )
    try:
        with db.begin_nested():
            if workspace is not None and flow_publication.flow_publication_enabled(workspace):
                if published_evidence is None:
                    raise flow_ingress.FlowIngressError(
                        "PUBLISHED_TRIGGER_EVIDENCE_REQUIRED",
                        "Published trigger evidence must be accepted before Run creation.",
                    )
                trigger_ids = dispatch_trigger_ingresses(published_evidence.flow).get(
                    event_kind, []
                )
                ingress_kind = ingress_kind_for_event(event_kind)
                run = flow_ingress.create_published_ingress_run(
                    db,
                    system_id=system.id,
                    workspace=workspace,
                    ingress_id=trigger_ids[0] if len(trigger_ids) == 1 else None,
                    kind=ingress_kind,
                    payload=payload if isinstance(payload, dict) else {"value": payload},
                    expected_published_version_id=published_evidence.version_id,
                    expected_flow_sha256=published_evidence.flow_sha256,
                    adapter_evidence={
                        "event_kind": event_kind,
                        "dedup_key": dedup_key,
                    },
                    trigger="webhook",
                    trigger_dedup_key=dedup_key,
                )
                trigger_meta = _trigger_input_ref(
                    event_kind,
                    dedup_key,
                    payload,
                    mode=TRIGGER_MODE_LIVE,
                    simulated=False,
                )[_TRIGGER_META_KEY]
                run.input_ref = {**(run.input_ref or {}), _TRIGGER_META_KEY: trigger_meta}
                run.checkpoints = [
                    *(run.checkpoints or []),
                    {
                        "kind": "trigger_dispatched",
                        "t": datetime.utcnow().isoformat(),
                        "event_kind": event_kind,
                        "dedup_key": dedup_key,
                    },
                ]
                db.flush()
            else:
                run = Run(
                    id=str(uuid4()),
                    workspace_id=workspace_id or system.workspace_id,
                    system_id=system.id,
                    capability_id=system.capability_id,
                    input_ref=_trigger_input_ref(
                        event_kind,
                        dedup_key,
                        payload,
                        mode=TRIGGER_MODE_LIVE,
                        simulated=False,
                    ),
                    status="pending",
                    trigger="webhook",
                    trigger_dedup_key=dedup_key,
                    checkpoints=[
                        {
                            "kind": "trigger_dispatched",
                            "t": datetime.utcnow().isoformat(),
                            "event_kind": event_kind,
                            "dedup_key": dedup_key,
                        }
                    ],
                )
                db.add(run)
                db.flush()
            claim = TriggerEventClaim(
                id=str(uuid4()),
                workspace_id=workspace_id or system.workspace_id,
                system_id=system.id,
                dedup_key=dedup_key,
                outcome="run",
                run_id=run.id,
            )
            db.add(claim)
            from app.services.run_engine.dispatch_outbox import (  # noqa: WPS433
                TRIGGER_RUN,
                enqueue_dispatch,
            )

            enqueue_dispatch(
                db,
                event_type=TRIGGER_RUN,
                workspace_id=str(workspace_id or system.workspace_id),
                run_id=run.id,
                source_id=dedup_key,
            )
            db.flush()
    except IntegrityError:
        result = _duplicate_delivery_result(
            db,
            system_id=system.id,
            dedup_key=dedup_key,
        )
        if result is None:
            raise
        raise _TriggerDeliveryDuplicate(result) from None
    return run


def _dispatch_live_run(run_id: str) -> None:
    """Hand the run to the engine (``schedule_run`` manages its own loop).

    Module-level so tests can monkeypatch it to observe dispatch without
    actually executing a flow.
    """
    from app.services.run_engine.engine import schedule_run  # noqa: WPS433

    schedule_run(run_id)


def _process_live(
    db: DBSession,
    system: System,
    event_kind: str,
    workspace_id: Optional[str],
    payload: Dict[str, Any],
    dedup_key: str,
    *,
    published_evidence: _PublishedTriggerEvidence | None = None,
    owns_session: bool,
) -> Dict[str, Any]:
    """Live guards followed by one transactional, durable Run handoff."""
    if _circuit_open(db, system, owns_session=owns_session):
        logger.warning("triggers: circuit open, skipping dispatch", system_id=system.id)
        return {"system_id": system.id, "status": "circuit_open", "dedup_key": dedup_key}

    since = datetime.utcnow() - timedelta(hours=1)
    if _count_recent_triggered_runs(db, system.id, since) >= _max_runs_per_hour(db, system):
        logger.warning("triggers: rate limited", system_id=system.id, event_kind=event_kind)
        return {"system_id": system.id, "status": "rate_limited", "dedup_key": dedup_key}

    try:
        run = _create_triggered_run(
            db,
            system,
            event_kind,
            workspace_id,
            payload,
            dedup_key,
            published_evidence=published_evidence,
        )
    except flow_ingress.FlowIngressError as exc:
        logger.warning(
            "triggers: published ingress rejected before run creation",
            system_id=system.id,
            event_kind=event_kind,
            reason=exc.code,
        )
        return {
            "system_id": system.id,
            "status": "rejected",
            "reason": exc.code.lower(),
            "dedup_key": dedup_key,
        }
    except _TriggerDeliveryDuplicate as duplicate:
        return duplicate.result
    _commit_or_flush(db, owns_session)
    logger.info(
        "triggers: queued durable live run",
        system_id=system.id,
        event_kind=event_kind,
        run_id=run.id,
    )
    return {
        "system_id": system.id,
        "status": "queued",
        "run_id": run.id,
        "dedup_key": dedup_key,
    }


# ---------------------------------------------------------------------------
# Master switch (global OR per-workspace opt-in)
# ---------------------------------------------------------------------------
def is_event_triggers_enabled(
    workspace_id: Optional[str] = None,
    *,
    db: Optional[DBSession] = None,
) -> bool:
    """True when the global flag is ON, or the workspace opted in.

    Global ``settings.enable_event_triggers`` stays OFF by default so other
    workspaces are untouched. Showcase (and any workspace) can opt in via
    ``workspace.settings.features.enable_event_triggers = true`` or
    ``workspace.settings.event_triggers.enabled = true`` without flipping the
    deployment-wide switch.
    """
    if settings.enable_event_triggers:
        return True
    if not workspace_id:
        return False

    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        from app.models.workspace import Workspace  # noqa: WPS433
        from app.services.workspace_features import feature_enabled  # noqa: WPS433

        workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
        if workspace is None:
            return False
        if feature_enabled(workspace, "enable_event_triggers"):
            return True
        blob = workspace.settings if isinstance(workspace.settings, dict) else {}
        et = blob.get("event_triggers")
        return isinstance(et, dict) and et.get("enabled") is True
    finally:
        if owns_session:
            db.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
#: Per-target outcomes that took durable custody of the delivery. ``duplicate``
#: belongs here: the claim it collides with was itself an acceptance.
ACCEPTED_DELIVERY_STATUSES = frozenset(
    {"queued", "dispatched", "simulated", "buffered", "duplicate"}
)


def delivery_status(results: List[Dict[str, Any]]) -> str:
    """Collapse per-target outcomes into one verdict for the inbound caller.

    ``ignored`` when nothing listened (triggers off, or no registered target),
    ``accepted`` when every target took the delivery, ``rejected`` when none
    did, ``partial`` in between. ``ignored`` is deliberately distinct from
    ``rejected``: nothing refused the delivery, nothing was waiting for it.
    """
    if not results or all(item.get("status") == "no_target" for item in results):
        return "ignored"
    accepted = sum(1 for item in results if item.get("status") in ACCEPTED_DELIVERY_STATUSES)
    if accepted == len(results):
        return "accepted"
    return "partial" if accepted else "rejected"


def emit_event(
    event_kind: str,
    workspace_id: Optional[str],
    payload: Dict[str, Any],
    *,
    db: Optional[DBSession] = None,
    system_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Emit ``event_kind`` for ``workspace_id`` and process every target System.

    Returns a list of per-target result dicts. ``status`` is one of:
    ``simulated`` (dry-run journal), ``dispatched`` (live run scheduled),
    ``buffered`` (correlated ``hitl_pending`` run inbox), ``duplicate``
    (dedup hit), ``rejected`` (governance), ``rate_limited``,
    ``circuit_open``, ``dispatch_failed`` or ``no_target``. No-op returning
    ``[]`` when neither the global master switch nor the workspace opt-in is
    enabled.

    Per-System mode decides dry-run vs live: only a System whose
    ``settings.event_trigger.mode == 'live'`` (and only while triggers are
    enabled and the event is governance-eligible) dispatches a real run; the
    default ``dry_run`` merely journals a ``simulated`` run.

    ``system_id`` — when set (webhook hooks), only that System is considered.
    ``db`` — reuse the caller's session when provided; every trigger outcome is
    flushed into that surrounding transaction without committing or rolling it
    back. Otherwise a private session is opened and owned here.
    """
    owns_session = db is None
    if owns_session:
        db = SessionLocal()
    try:
        if not is_event_triggers_enabled(workspace_id, db=db):
            return []

        registry = build_registry(db, workspace_id=workspace_id)
        system_ids = list(registry.get((event_kind, workspace_id), []))
        if system_id is not None:
            if system_id not in system_ids:
                return [
                    {
                        "status": "no_target",
                        "event_kind": event_kind,
                        "workspace_id": workspace_id,
                        "system_id": system_id,
                    }
                ]
            system_ids = [system_id]
        if not system_ids:
            return [{"status": "no_target", "event_kind": event_kind, "workspace_id": workspace_id}]
        results: List[Dict[str, Any]] = []
        for target_id in system_ids:
            system = (
                db.query(System)
                .filter(
                    System.id == target_id,
                    System.workspace_id == workspace_id,
                )
                .first()
            )
            if not system:
                continue
            results.append(
                _process_target(
                    db,
                    system,
                    event_kind,
                    workspace_id,
                    payload,
                    owns_session=owns_session,
                )
            )
        return results
    finally:
        if owns_session:
            db.close()


def _process_target(
    db: DBSession,
    system: System,
    event_kind: str,
    workspace_id: Optional[str],
    payload: Dict[str, Any],
    *,
    owns_session: bool,
) -> Dict[str, Any]:
    """Governance → dedup → (live dispatch | dry-run journal) for one System.

    The mode gate is the ONLY difference between Phase 3a and 3b: a target in
    ``live`` mode dispatches a real run through the guarded live path; every
    other case (default ``dry_run``) journals a ``simulated`` run. Governance
    and dedup are enforced identically in both modes.
    """
    if system.workspace_id != workspace_id:
        return {
            "system_id": system.id,
            "status": "rejected",
            "reason": "catalog_binding_invalid:system_workspace_mismatch",
        }
    workspace = (
        db.query(Workspace).filter(Workspace.id == workspace_id).first() if workspace_id else None
    )
    if workspace_id and workspace is None:
        return {
            "system_id": system.id,
            "status": "rejected",
            "reason": "catalog_binding_invalid:workspace_not_found",
        }

    published_evidence: _PublishedTriggerEvidence | None = None
    governance_flow = system.flow_definition or {}
    if workspace is not None and flow_publication.flow_publication_enabled(workspace):
        # Publication and trigger acceptance serialize on the same System row.
        # Governance, ingress selection and the Run snapshot below therefore
        # all refer to one locked published pointer.
        locked_system = (
            db.query(System)
            .filter(
                System.id == system.id,
                System.workspace_id == workspace.id,
            )
            .populate_existing()
            .with_for_update(of=System)
            .one_or_none()
        )
        if locked_system is None:
            return {
                "system_id": system.id,
                "status": "rejected",
                "reason": "published_system_not_found",
            }
        system = locked_system
        if system.status != "active":
            return {
                "system_id": system.id,
                "status": "rejected",
                "reason": "published_system_inactive",
            }
        try:
            (
                version,
                published_flow,
                published_hash,
                _contract,
            ) = flow_publication.published_run_evidence(
                db,
                system=system,
                workspace=workspace,
            )
        except flow_publication.FlowPublicationError as exc:
            logger.warning(
                "triggers: published evidence rejected before governance",
                system_id=system.id,
                event_kind=event_kind,
                reason=exc.code,
            )
            return {
                "system_id": system.id,
                "status": "rejected",
                "reason": exc.code.lower(),
            }
        version_id = str(getattr(version, "id", "") or "")
        if not version_id:
            return {
                "system_id": system.id,
                "status": "rejected",
                "reason": "published_flow_version_missing",
            }
        governance_flow = published_flow
        published_evidence = _PublishedTriggerEvidence(
            flow=published_flow,
            version_id=version_id,
            flow_sha256=published_hash,
        )
    try:
        resolve_persisted_system_catalog_bindings(
            db,
            workspace=workspace,
            system=system,
        )
    except SystemCatalogBindingError as exc:
        logger.warning(
            "triggers: catalog binding rejected before journaling",
            system_id=system.id,
            event_kind=event_kind,
            reason=exc.code,
        )
        return {
            "system_id": system.id,
            "status": "rejected",
            "reason": f"catalog_binding_invalid:{exc.code}",
        }

    verdict = evaluate_governance(event_kind, governance_flow)
    if not verdict.eligible:
        logger.info(
            "triggers: governance rejected",
            system_id=system.id,
            event_kind=event_kind,
            reason=verdict.reason,
        )
        return {"system_id": system.id, "status": "rejected", "reason": verdict.reason}

    dedup_key = _dedup_key(system.id, event_kind, payload)
    existing = _duplicate_delivery_result(
        db,
        system_id=system.id,
        dedup_key=dedup_key,
    )
    if existing is not None:
        return existing

    # Phase 4 — while a correlated Run is ``hitl_pending``, buffer inbound
    # transactions into ``run_inbox`` (+ SystemMemory) instead of starting a
    # parallel run. Applies in both dry-run and live modes.
    try:
        from app.services.run_engine.inbox import try_buffer_event  # noqa: WPS433

        try:
            with db.begin_nested():
                buffered = try_buffer_event(
                    db,
                    system_id=system.id,
                    event_kind=event_kind,
                    payload=payload if isinstance(payload, dict) else {},
                )
                if buffered is not None:
                    db.add(
                        TriggerEventClaim(
                            id=str(uuid4()),
                            workspace_id=workspace_id or system.workspace_id,
                            system_id=system.id,
                            dedup_key=dedup_key,
                            outcome="inbox",
                            inbox_id=str(buffered["inbox_id"]),
                        )
                    )
                    db.flush()
            if buffered is not None:
                _commit_or_flush(db, owns_session)
                buffered["dedup_key"] = dedup_key
                return buffered
        except IntegrityError:
            duplicate = _duplicate_delivery_result(
                db,
                system_id=system.id,
                dedup_key=dedup_key,
            )
            if duplicate is None:
                raise
            return duplicate
    except Exception as exc:  # noqa: BLE001 — storage failures must fail closed.
        logger.warning(
            "triggers: inbox buffer failed",
            system_id=system.id,
            event_kind=event_kind,
            error=str(exc),
        )
        # Never turn an inbox/storage failure into a parallel execution while a
        # matching HITL gate may still be waiting. The savepoint above has
        # already removed partial inbox/memory/claim rows; leaving the delivery
        # unclaimed lets a later redelivery retry safely.
        return {
            "system_id": system.id,
            "status": "rejected",
            "reason": "inbox_buffer_failed",
            "dedup_key": dedup_key,
        }

    # Live execution is opt-in per System AND still gated by the master flag
    # (already asserted in ``emit_event``). Everything else stays dry-run.
    if trigger_mode(system) == TRIGGER_MODE_LIVE:
        return _process_live(
            db,
            system,
            event_kind,
            workspace_id,
            payload,
            dedup_key,
            published_evidence=published_evidence,
            owns_session=owns_session,
        )

    try:
        run, created = _journal_simulated_run(
            db, system, event_kind, workspace_id, payload, dedup_key, owns_session=owns_session
        )
    except _TriggerDeliveryDuplicate as duplicate:
        return duplicate.result
    if not created:
        duplicate = _duplicate_delivery_result(
            db,
            system_id=system.id,
            dedup_key=dedup_key,
        )
        if duplicate is not None:
            return duplicate
    return {
        "system_id": system.id,
        "status": "simulated",
        "run_id": run.id,
        "dedup_key": dedup_key,
    }


# ---------------------------------------------------------------------------
# Convenience emission hooks (flag-guarded, exception-safe)
# ---------------------------------------------------------------------------
def emit_deposit_promoted(
    db: DBSession,
    *,
    workspace_id: Optional[str],
    collection_slug: Optional[str],
    file_ids: List[str],
) -> List[Dict[str, Any]]:
    """Hook fired AFTER an operator promotes deposit file(s) to a collection.

    ``deposit.promoted`` is the only event allowed to feed a side-effecting
    downstream run (still HITL-gated). Flag-guarded and exception-safe: a
    trigger failure never breaks the promotion.
    """
    if not is_event_triggers_enabled(workspace_id, db=db):
        return []
    file_ids = [fid for fid in (file_ids or []) if fid]
    payload = {
        "collection_slug": collection_slug,
        "file_ids": file_ids,
        "file_id": file_ids[0] if len(file_ids) == 1 else None,
        "workspace_id": workspace_id,
    }
    try:
        return emit_event(EVENT_DEPOSIT_PROMOTED, workspace_id, payload, db=db)
    except Exception as exc:  # noqa: BLE001 — never break promotion.
        logger.warning(
            "triggers: emit deposit.promoted failed",
            workspace_id=workspace_id,
            collection_slug=collection_slug,
            error=str(exc),
        )
        return []


def emit_sftp_file_arrived(
    db: DBSession,
    *,
    workspace_id: Optional[str],
    payload: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Hook fired on SFTP staging close and/or reconciliation file arrival.

    Governance-restricted to analysis / notification runs only (NEVER
    ingestion). Flag/workspace-opt-in gated and exception-safe.
    """
    if not is_event_triggers_enabled(workspace_id, db=db):
        return []
    try:
        return emit_event(EVENT_SFTP_FILE_ARRIVED, workspace_id, payload or {}, db=db)
    except Exception as exc:  # noqa: BLE001 — never break staging/reconciliation.
        logger.warning(
            "triggers: emit sftp.file_arrived failed",
            workspace_id=workspace_id,
            error=str(exc),
        )
        return []
