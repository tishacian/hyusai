"""Read model: which Systems still reach their published Flow ingress.

``flow_publication_v1`` refuses a Run whose System carries no valid published
execution contract. The operator-facing surfaces answer that refusal out loud —
a manual run returns 409, the Flow Runner shows the message — but the scheduler
and the event/webhook path absorb it per delivery. A System the contract
backfill has not repaired therefore keeps its schedules and its hooks, reports
nothing, and dispatches nothing.

This module replays the ingress predicate against every declared dispatch
surface, creating no Run and mutating nothing. A refusal is a standing property
of the System's publication state rather than an event, so it is recomputed on
demand instead of journaled: repair the contract and the report goes green
without anything having to retract a stale record.

Scope is the published-ingress boundary alone. A surface reported ready can
still be held by a gate above it — ``enable_event_triggers``, a tripped circuit
breaker, a disabled schedule — and each of those already has its own signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.run_schedule import RunSchedule
from app.models.system import System
from app.services.run_engine import triggers
from app.services.systems import flow_ingress


@dataclass(frozen=True, slots=True)
class _Surface:
    """A declared dispatch surface and the ingress its adapter asks for."""

    kind: str
    ingress_id: str | None
    described: dict[str, Any]


def _refusal(exc: flow_ingress.FlowIngressError) -> dict[str, str]:
    return {"code": exc.code, "message": exc.message}


def _schedule_surfaces(db: DBSession, system: System) -> list[_Surface]:
    rows = (
        db.query(RunSchedule)
        .filter(
            RunSchedule.system_id == system.id,
            RunSchedule.workspace_id == system.workspace_id,
        )
        .order_by(RunSchedule.created_at.asc())
        .all()
    )
    return [
        _Surface(
            kind="schedule",
            # ``_fire_schedule`` names no ingress; it takes the published one.
            ingress_id=None,
            described={
                "kind": "schedule",
                "surface_id": row.id,
                "name": row.name,
                "enabled": bool(row.enabled),
                "next_fire_at": row.next_fire_at.isoformat() if row.next_fire_at else None,
            },
        )
        for row in rows
    ]


def _event_surfaces(flow: Any) -> list[_Surface]:
    declared = triggers.dispatch_trigger_ingresses(flow)
    surfaces: list[_Surface] = []
    for event_kind in sorted(declared):
        # Cron is table-driven through ``run_schedules``, so a source.schedule
        # node is graph parity rather than a delivery surface of its own.
        if event_kind == triggers.EVENT_SCHEDULE_FIRED:
            continue
        node_ids = declared[event_kind]
        kind = triggers.ingress_kind_for_event(event_kind)
        surfaces.append(
            _Surface(
                kind=kind,
                ingress_id=node_ids[0] if len(node_ids) == 1 else None,
                described={
                    "kind": kind,
                    "surface_id": event_kind,
                    "name": event_kind,
                    "enabled": True,
                    "next_fire_at": None,
                },
            )
        )
    return surfaces


def system_dispatch_readiness(
    db: DBSession,
    *,
    system: System,
    workspace: Any,
) -> dict[str, Any]:
    """Report whether each of ``system``'s dispatch surfaces would be served."""

    published: dict[str, Any] = {}
    refusal: dict[str, str] | None = None
    # Enumerating from the mirror keeps the surfaces named even when the
    # published pointer is the thing that is broken.
    flow: Any = system.flow_definition or {}
    try:
        published = flow_ingress.assert_dispatchable(
            db,
            system_id=system.id,
            workspace=workspace,
        )
    except flow_ingress.FlowIngressError as exc:
        refusal = _refusal(exc)
    else:
        flow = published["flow"]

    surfaces: list[dict[str, Any]] = []
    for surface in _schedule_surfaces(db, system) + _event_surfaces(flow):
        item = dict(surface.described)
        item["ingress_id"] = None
        blocked = refusal
        if blocked is None:
            try:
                item["ingress_id"] = flow_ingress.resolve_published_ingress_id(
                    published["execution_contract"],
                    kind=surface.kind,
                    requested_ingress_id=surface.ingress_id,
                )
            except flow_ingress.FlowIngressError as exc:
                blocked = _refusal(exc)
        item["ready"] = blocked is None
        item["blocked"] = blocked
        surfaces.append(item)

    return {
        "system_id": system.id,
        "system_name": system.name,
        "system_status": system.status,
        "published_flow_version_id": published.get("published_flow_version_id"),
        "flow_sha256": published.get("flow_sha256"),
        "ready": all(item["ready"] for item in surfaces),
        "blocked": refusal,
        "surfaces": surfaces,
    }


def workspace_dispatch_readiness(db: DBSession, *, workspace: Any) -> dict[str, Any]:
    """Every System in ``workspace`` that declares a dispatch surface.

    Systems without one are omitted: they dispatch nothing by design, and the
    question this answers is which of the ones that should are inert.
    """

    systems = (
        db.query(System)
        .filter(
            System.workspace_id == workspace.id,
            # ``retired`` is the archive state; its surfaces are inert on purpose.
            System.status != "retired",
        )
        .order_by(System.name.asc(), System.id.asc())
        .all()
    )
    reports = [
        report
        for report in (
            system_dispatch_readiness(db, system=system, workspace=workspace)
            for system in systems
        )
        if report["surfaces"]
    ]
    blocked = [report for report in reports if not report["ready"]]
    return {
        "workspace_id": workspace.id,
        "summary": {
            "dispatching_systems": len(reports),
            "ready": len(reports) - len(blocked),
            "blocked": len(blocked),
        },
        "systems": reports,
    }
