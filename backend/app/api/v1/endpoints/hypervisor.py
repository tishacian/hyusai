"""Canonical /hypervisor endpoints — Balance Sheet, Recommendations, What-If.

Composes data from `impact`, `runs`, `capabilities` and `decisions` to feed
the executive cockpit. Designed to be a single roundtrip per surface.
"""
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.v1.endpoints.capabilities import serialize_value_basis
from app.api.v1.endpoints.impact import _period_start
from app.core.auth import get_current_user, get_current_workspace
from app.db.base import get_db
from app.models.capability import Capability
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.evaluation_feedback import FEEDBACK_LABELS
from app.models.run import Run
from app.models.system import System
from app.models.user import User
from app.models.value_loop import ValueMeasurement, ValueScenario
from app.models.workspace import Workspace
from app.services.catalog_visibility import visible_capabilities, workspace_catalog_policy
from app.services.decision_access import readable_decisions
from app.services.decisions import InvalidTransition
from app.services.decisions import (
    accept as sm_accept,
)
from app.services.decisions import (
    reject as sm_reject,
)
from app.services.evaluation.feedback_service import (
    InvalidFeedback,
    record_feedback,
    serialize_feedback,
)
from app.services.iam.decision_plane import enforce_action
from app.services.iam.legacy_authority import legacy_workspace_admin
from app.services.object_perspective import FACT_STATES, WINDOW_DAYS
from app.services.recommendations.proactive_service import (
    generate_proactive_recommendations,
)
from app.services.run_access import readable_runs
from app.services.value_loop_gate import value_loop_enabled, value_loop_requested
from app.services.value_scenario_access import readable_value_scenarios

router = APIRouter()

HYPERVISOR_VIEWS_KEY = "hypervisor_views"
OUTCOME_DECISIONS = frozenset({"approved", "partial"})
SERIES_RUN_SCOPE = {
    "resource": "run",
    "action": "read",
    "aggregation": "post_authorization_filter",
    "counts_include_only_readable_runs": True,
}
DEFAULT_HYPERVISOR_VIEWS: List[Dict[str, Any]] = [
    {
        "id": "direction",
        "label": "Direction",
        "denominator": "hours",
        "period": "90d",
        "strata": {
            "comprendre": [
                "monument",
                "provenance",
                "cadran",
                "sankey",
                "rivers",
                "hors_denominateur",
            ],
            "detailler": ["registre"],
            "decider": ["signal", "decisions"],
        },
        "register_columns": ["unit", "spark", "cost", "basis", "value"],
        "sort": "value",
    },
    {
        "id": "operations",
        "label": "Operations",
        "denominator": "runs",
        "period": "30d",
        "strata": {
            "comprendre": ["monument", "cadran", "rivers", "signal"],
            "detailler": ["registre"],
            "decider": [],
        },
        "register_columns": ["unit", "spark"],
        "sort": "days_since_last_run",
    },
    {
        "id": "conformite",
        "label": "Conformite",
        "denominator": "runs",
        "period": "90d",
        "strata": {
            "comprendre": ["unites", "couverture", "decisions"],
            "detailler": ["registre"],
            "decider": [],
        },
        "register_columns": ["unit", "basis"],
        "sort": "name",
    },
]


def _visible_completed_runs(
    db: DBSession,
    workspace: Workspace,
    user: User,
    *,
    start: datetime | None = None,
) -> List[Run]:
    run_query = db.query(Run).filter(
        Run.workspace_id == workspace.id,
        Run.status == "completed",
    )
    if start is not None:
        run_query = run_query.filter(Run.completed_at >= start)
    return readable_runs(
        db,
        runs=run_query.order_by(Run.completed_at.desc(), Run.id.asc()).all(),
        user=user,
        workspace=workspace,
    )


def _visible_workspace_capabilities(
    db: DBSession,
    workspace: Workspace,
) -> List[Capability]:
    caps: List[Capability] = (
        db.query(Capability)
        .filter((Capability.workspace_id == workspace.id) | (Capability.workspace_id.is_(None)))
        .order_by(Capability.tier, Capability.name)
        .all()
    )
    return visible_capabilities(caps, workspace, workspace_catalog_policy(workspace))


@router.get("/balance-sheet")
async def balance_sheet(
    period: str = Query("qtd"),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    start = _period_start(period)
    completed_runs = _visible_completed_runs(db, workspace, user, start=start)
    portfolio = _aggregate_visible_runs(completed_runs)
    caps = _visible_workspace_capabilities(db, workspace)
    capability_rows = []
    for c in caps:
        agg = _aggregate_visible_runs(
            [run for run in completed_runs if run.capability_id == c.id]
        )
        if agg["runs_count"] == 0:
            continue
        capability_rows.append({
            "capability_id": c.id,
            "slug": c.slug,
            "name": c.name,
            "tier": c.tier,
            "trend": [],  # Phase 3 wires real sparkline values from Impact rows.
            **agg,
        })

    return {
        "period": period,
        "portfolio": portfolio,
        "capabilities": capability_rows,
        "signals": _signals(
            readable_runs(
                db,
                runs=(
                    db.query(Run)
                    .filter(Run.workspace_id == workspace.id)
                    .order_by(Run.started_at.desc(), Run.id.asc())
                    .limit(100)
                    .all()
                ),
                user=user,
                workspace=workspace,
            )[:20]
        ),
        "authorization_scope": dict(SERIES_RUN_SCOPE),
    }


class HypervisorViewStrata(BaseModel):
    comprendre: List[str] = []
    detailler: List[str] = []
    decider: List[str] = []


class HypervisorView(BaseModel):
    id: str
    label: str
    denominator: Literal["hours", "runs", "value", "units"]
    period: str
    strata: HypervisorViewStrata
    register_columns: List[str] = []
    sort: str = "name"


class HypervisorViewsUpdate(BaseModel):
    views: List[HypervisorView]


def _require_workspace_admin(db: DBSession, user: User, workspace: Workspace) -> None:
    if not legacy_workspace_admin(db, user=user, workspace=workspace):
        raise HTTPException(
            status_code=403,
            detail={"code": "WORKSPACE_PERMISSION_DENIED"},
        )


def _pricing_currency(capability: Capability | None) -> str | None:
    if capability is None or not isinstance(capability.pricing, dict):
        return None
    currency = capability.pricing.get("currency")
    return str(currency) if currency else None


def _series_fact(
    *,
    state: str,
    value: Any = None,
    unit: str | None = None,
) -> dict[str, Any]:
    if state not in FACT_STATES:
        raise ValueError(f"unknown fact state {state!r}")
    if state != "available":
        value = None
    payload: dict[str, Any] = {"state": state, "value": value}
    if unit is not None:
        payload["unit"] = unit
    return payload


def _run_at(run: Run) -> datetime | None:
    return run.completed_at or run.started_at


def _hours_per_unit(basis: dict[str, Any] | None) -> float | None:
    if not basis or basis.get("status") == "none":
        return None
    return _optional_rate(basis.get("hours_per_unit"))


def _value_per_unit(basis: dict[str, Any] | None) -> float | None:
    if not basis or basis.get("status") == "none":
        return None
    return _optional_rate(basis.get("value_per_unit"))


def _optional_rate(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _days_since(moment: datetime | None, *, now: datetime) -> dict[str, Any]:
    if moment is None:
        return _series_fact(state="not_measured")
    delta = now - moment
    days = max(0, int(delta.total_seconds() // 86400))
    return _series_fact(state="available", value=days)


def _bucket_metrics(
    runs: List[Run],
    *,
    output_unit: str | None,
    hours_per_unit: float | None,
    value_per_unit: float | None,
) -> dict[str, Any]:
    outcomes = len([run for run in runs if (run.decision or "") in OUTCOME_DECISIONS])
    costs = [float(run.cost_internal) for run in runs if run.cost_internal is not None]
    return {
        "runs": _series_fact(state="available", value=len(runs)),
        "outcomes": _series_fact(state="available", value=outcomes, unit=output_unit),
        "cost": _series_fact(
            state="available" if costs else "not_measured",
            value=float(sum(costs)) if costs else None,
        ),
        "hours": _series_fact(
            state="available" if hours_per_unit is not None else "not_configured",
            value=(outcomes * hours_per_unit) if hours_per_unit is not None else None,
        ),
        "value_declared": _series_fact(
            state="available" if value_per_unit is not None else "not_configured",
            value=(outcomes * value_per_unit) if value_per_unit is not None else None,
        ),
    }


def _coerce_view_denominator(value: Any) -> str:
    return "runs" if value == "units" else str(value or "hours")


def _normalize_view(view: dict[str, Any]) -> dict[str, Any]:
    next_view = dict(view)
    next_view["denominator"] = _coerce_view_denominator(view.get("denominator"))
    return next_view


def _views_payload(workspace: Workspace, *, can_edit: bool) -> dict[str, Any]:
    stored = (workspace.settings or {}).get(HYPERVISOR_VIEWS_KEY)
    raw = stored if isinstance(stored, list) else DEFAULT_HYPERVISOR_VIEWS
    views = [_normalize_view(view) if isinstance(view, dict) else view for view in raw]
    return {"views": views, "can_edit": can_edit}


@router.get("/value-bases")
async def list_value_bases(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    caps = _visible_workspace_capabilities(db, workspace)
    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id)
        .order_by(System.name.asc(), System.id.asc())
        .all()
    )
    systems_by_cap: dict[str, list[dict[str, str]]] = defaultdict(list)
    for system in systems:
        if system.capability_id:
            systems_by_cap[system.capability_id].append(
                {"system_id": system.id, "name": system.name}
            )
    return {
        "items": [
            {
                "capability_id": capability.id,
                "slug": capability.slug,
                "name": capability.name,
                "tier": capability.tier,
                "industry": capability.industry,
                "input_unit": capability.input_unit,
                "output_unit": capability.output_unit,
                "value_per_outcome": capability.value_per_outcome,
                "value_basis": serialize_value_basis(
                    capability.value_basis,
                    default_unit=capability.output_unit,
                    default_currency=_pricing_currency(capability),
                ),
                "systems": systems_by_cap.get(capability.id, []),
            }
            for capability in caps
        ]
    }


@router.get("/series")
async def hypervisor_series(
    window: Literal["30d", "90d"] = Query("30d"),
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    now = datetime.utcnow()
    start = now - timedelta(days=WINDOW_DAYS[window])
    completed_runs = _visible_completed_runs(db, workspace, user, start=start)
    runs_by_system: dict[str, list[Run]] = defaultdict(list)
    for run in completed_runs:
        if run.system_id:
            runs_by_system[run.system_id].append(run)
    system_ids = list(runs_by_system)
    systems = (
        db.query(System)
        .filter(System.id.in_(system_ids), System.workspace_id == workspace.id)
        .order_by(System.name.asc(), System.id.asc())
        .all()
        if system_ids
        else []
    )
    cap_ids = {
        system.capability_id
        for system in systems
        if system.capability_id
    }
    capabilities = (
        {
            capability.id: capability
            for capability in db.query(Capability).filter(Capability.id.in_(cap_ids)).all()
        }
        if cap_ids
        else {}
    )
    items = []
    for system in systems:
        capability = capabilities.get(system.capability_id) if system.capability_id else None
        basis = serialize_value_basis(
            capability.value_basis if capability is not None else None,
            default_unit=capability.output_unit if capability is not None else None,
            default_currency=_pricing_currency(capability),
        )
        hours_per_unit = _hours_per_unit(basis)
        value_per_unit = _value_per_unit(basis)
        output_unit = (
            (basis or {}).get("unit")
            or (capability.output_unit if capability is not None else None)
        )
        system_runs = runs_by_system[system.id]
        last_at = max(
            (moment for moment in (_run_at(run) for run in system_runs) if moment is not None),
            default=None,
        )
        by_day: dict[str, list[Run]] = defaultdict(list)
        for run in system_runs:
            moment = _run_at(run)
            if moment is None:
                continue
            by_day[moment.date().isoformat()].append(run)
        items.append(
            {
                "system_id": system.id,
                "capability_id": system.capability_id,
                "name": system.name,
                "output_unit": output_unit,
                "value_basis": basis,
                "days_since_last_run": _days_since(last_at, now=now),
                "buckets": [
                    {
                        "date": day,
                        **_bucket_metrics(
                            by_day[day],
                            output_unit=output_unit,
                            hours_per_unit=hours_per_unit,
                            value_per_unit=value_per_unit,
                        ),
                    }
                    for day in sorted(by_day)
                ],
            }
        )
    return {
        "window": window,
        "from": start.isoformat(),
        "to": now.isoformat(),
        "authorization_scope": dict(SERIES_RUN_SCOPE),
        "systems": items,
    }


@router.get("/views")
async def get_hypervisor_views(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    return _views_payload(
        workspace,
        can_edit=legacy_workspace_admin(db, user=user, workspace=workspace),
    )


@router.put("/views")
async def put_hypervisor_views(
    body: HypervisorViewsUpdate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    _require_workspace_admin(db, user, workspace)
    settings = dict(workspace.settings or {})
    settings[HYPERVISOR_VIEWS_KEY] = [_normalize_view(view.model_dump()) for view in body.views]
    workspace.settings = settings
    flag_modified(workspace, "settings")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return _views_payload(workspace, can_edit=True)


@router.get("/value-loop")
async def portfolio_value_loop(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Aggregate only persisted System value loops at Portfolio scope."""

    systems = (
        db.query(System)
        .filter(System.workspace_id == workspace.id, System.status == "active")
        .order_by(System.name.asc(), System.id.asc())
        .all()
    )
    selected_systems = [
        system
        for system in systems
        if value_loop_requested(db, workspace=workspace, system=system)
    ]
    for system in selected_systems:
        enforce_action(
            db,
            user=user,
            workspace=workspace,
            resource_kind="system",
            action="read",
            legacy_allowed=True,
            resource_attrs={
                "system_id": system.id,
                "capability_id": system.capability_id,
                "scope": "portfolio_value_loop",
            },
        )
    system_ids = [system.id for system in selected_systems]
    raw_scenarios = (
        db.query(ValueScenario)
        .filter(
            ValueScenario.workspace_id == workspace.id,
            ValueScenario.system_id.in_(system_ids),
        )
        .order_by(ValueScenario.created_at.desc(), ValueScenario.id.desc())
        .all()
        if system_ids
        else []
    )
    scenarios = readable_value_scenarios(
        db,
        scenarios=raw_scenarios,
        user=user,
        workspace=workspace,
    )
    scenario_projection_state = (
        "available"
        if scenarios
        else "restricted"
        if raw_scenarios
        else "not_measured"
    )
    raw_scenario_system_ids = {row.system_id for row in raw_scenarios}
    scenario_ids = [scenario.id for scenario in scenarios]
    measurements = (
        db.query(ValueMeasurement)
        .filter(
            ValueMeasurement.workspace_id == workspace.id,
            ValueMeasurement.system_id.in_(system_ids),
            ValueMeasurement.scenario_id.in_(scenario_ids),
        )
        .order_by(ValueMeasurement.measured_at.desc(), ValueMeasurement.id.desc())
        .all()
        if scenario_ids
        else []
    )
    decisions = (
        db.query(Decision)
        .filter(
            Decision.workspace_id == workspace.id,
            Decision.kind == "value_loop",
            Decision.scope == "system",
            Decision.target_id.in_(system_ids),
            Decision.scenario_id.in_(scenario_ids),
        )
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .all()
        if scenario_ids
        else []
    )
    raw_decisions = decisions
    decisions = readable_decisions(
        db,
        decisions=decisions,
        user=user,
        workspace=workspace,
    )
    measured = [row for row in measurements if row.status == "measured"]
    measured_value_deltas = [
        float(row.delta["value"])
        for row in measured
        if isinstance(row.delta, dict)
        and isinstance(row.delta.get("value"), (int, float))
        and not isinstance(row.delta.get("value"), bool)
    ]
    scenario_by_system: dict[str, list[ValueScenario]] = {}
    measurement_by_system: dict[str, list[ValueMeasurement]] = {}
    measurement_by_scenario: dict[str, ValueMeasurement] = {}
    decision_by_scenario: dict[str, Decision] = {}
    raw_decision_scenario_ids = {
        row.scenario_id for row in raw_decisions if row.scenario_id
    }
    for row in scenarios:
        scenario_by_system.setdefault(row.system_id, []).append(row)
    for row in measurements:
        measurement_by_system.setdefault(row.system_id, []).append(row)
        measurement_by_scenario.setdefault(row.scenario_id, row)
    for row in decisions:
        if row.scenario_id:
            decision_by_scenario[row.scenario_id] = row

    forecast_verdict_counts = {
        verdict: len(
            [row for row in measured if row.assumption_verdict == verdict]
        )
        for verdict in ("confirmed", "partially_confirmed", "not_confirmed")
    }
    risk_items: list[dict[str, Any]] = []
    for scenario in scenarios:
        measurement = measurement_by_scenario.get(scenario.id)
        if scenario.status in {"approved", "acted"}:
            risk_items.append(
                {
                    "kind": "open_governed_change",
                    "system_id": scenario.system_id,
                    "scenario_id": scenario.id,
                    "state": "available",
                    "source": "value_scenarios.status",
                    "detail": scenario.status,
                }
            )
        if measurement is not None and measurement.status == "not_measured":
            risk_items.append(
                {
                    "kind": "outcome_not_measured",
                    "system_id": scenario.system_id,
                    "scenario_id": scenario.id,
                    "state": "available",
                    "source": "value_measurements.status,reason",
                    "detail": measurement.reason,
                }
            )
        if measurement is not None and measurement.assumption_verdict in {
            "partially_confirmed",
            "not_confirmed",
        }:
            risk_items.append(
                {
                    "kind": "forecast_assumption_gap",
                    "system_id": scenario.system_id,
                    "scenario_id": scenario.id,
                    "state": "available",
                    "source": "value_measurements.assumption_verdict",
                    "detail": measurement.assumption_verdict,
                }
            )
    system_by_id = {system.id: system for system in selected_systems}
    scenario_items = []
    for scenario in scenarios:
        measurement = measurement_by_scenario.get(scenario.id)
        decision = decision_by_scenario.get(scenario.id)
        scenario_items.append(
            {
                "id": scenario.id,
                "system_id": scenario.system_id,
                "capability_id": getattr(
                    system_by_id.get(scenario.system_id),
                    "capability_id",
                    None,
                ),
                "status": scenario.status,
                "objective": scenario.objective,
                "created_at": (
                    scenario.created_at.isoformat() if scenario.created_at else None
                ),
                "decision": (
                    {
                        "id": decision.id,
                        "status": decision.status,
                        "title": decision.title,
                    }
                    if decision is not None
                    else None
                ),
                "decision_state": (
                    "available"
                    if decision is not None
                    else "restricted"
                    if scenario.id in raw_decision_scenario_ids
                    else "not_configured"
                ),
                "outcome": {
                    "state": (
                        "available"
                        if measurement is not None and measurement.status == "measured"
                        else "not_measured"
                    ),
                    "measurement_id": measurement.id if measurement is not None else None,
                    "delta": (
                        dict(measurement.delta)
                        if measurement is not None
                        and isinstance(measurement.delta, Mapping)
                        else None
                    ),
                    "forecast_delta": (
                        dict(measurement.forecast_delta)
                        if measurement is not None
                        and isinstance(measurement.forecast_delta, Mapping)
                        else None
                    ),
                    "assumption_verdict": (
                        measurement.assumption_verdict
                        if measurement is not None
                        else "not_evaluable"
                    ),
                },
            }
        )
    return {
        "schema_version": 1,
        "scope": "portfolio",
        "state": "available" if selected_systems else "not_configured",
        "systems": [
            {
                "system_id": system.id,
                "capability_id": system.capability_id,
                "name": system.name,
                "scenario_count": len(scenario_by_system.get(system.id, [])),
                "open_count": len(
                    [
                        row
                        for row in scenario_by_system.get(system.id, [])
                        if row.status != "measured"
                    ]
                ),
                "measured_count": len(
                    [
                        row
                        for row in measurement_by_system.get(system.id, [])
                        if row.status == "measured"
                    ]
                ),
                "scenario_state": (
                    "available"
                    if scenario_by_system.get(system.id)
                    else "restricted"
                    if system.id in raw_scenario_system_ids
                    else "not_measured"
                ),
                "actuator_state": (
                    "available"
                    if value_loop_enabled(
                        db,
                        workspace=workspace,
                        system=system,
                    )
                    else "not_configured"
                ),
            }
            for system in selected_systems
        ],
        "status_counts": {
            status: len([row for row in scenarios if row.status == status])
            for status in (
                "decision_proposed",
                "simulated",
                "approved",
                "acted",
                "measured",
            )
        },
        "observed_value_delta": {
            "state": (
                "available"
                if measured_value_deltas
                else "restricted"
                if scenario_projection_state == "restricted"
                else "not_measured"
            ),
            "value": sum(measured_value_deltas) if measured_value_deltas else None,
            "source": "value_measurements.delta.value",
            "sample_count": len(measured_value_deltas),
        },
        "outcomes": {
            "state": (
                "available"
                if measured
                else "restricted"
                if scenario_projection_state == "restricted"
                else "not_measured"
            ),
            "observed_value_delta": {
                "state": (
                    "available"
                    if measured_value_deltas
                    else "restricted"
                    if scenario_projection_state == "restricted"
                    else "not_measured"
                ),
                "value": sum(measured_value_deltas) if measured_value_deltas else None,
                "source": "value_measurements.delta.value",
                "sample_count": len(measured_value_deltas),
            },
            "measured_scenarios": {
                "state": scenario_projection_state,
                "value": len(measured) if scenarios else None,
                "source": "value_measurements.status",
                "sample_count": len(scenarios),
            },
            "forecast_verdict_counts": {
                "state": (
                    "available"
                    if measured
                    else "restricted"
                    if scenario_projection_state == "restricted"
                    else "not_measured"
                ),
                "value": forecast_verdict_counts if measured else None,
                "source": "value_measurements.assumption_verdict",
                "sample_count": len(measured),
            },
        },
        "risks": {
            "state": scenario_projection_state,
            "count": len(risk_items) if scenarios else None,
            "items": risk_items,
            "source": (
                "value_scenarios.status,value_measurements.status,reason,"
                "assumption_verdict"
            ),
        },
        "arbitrations": {
            "state": (
                "available"
                if decisions
                else "restricted"
                if raw_decisions or scenario_projection_state == "restricted"
                else "not_measured"
            ),
            "items": [
                {
                    "id": row.id,
                    "scenario_id": row.scenario_id,
                    "system_id": row.target_id,
                    "status": row.status,
                    "title": row.title,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in decisions
            ],
            "source": "decisions.kind=value_loop,scope=system",
        },
        "scenarios": {
            "state": scenario_projection_state,
            "items": scenario_items,
            "source": "value_scenarios",
        },
        "simulation_is_measurement": False,
    }


def _signals(recent_runs: List[Run]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in recent_runs:
        tone = "neutral"
        roi = _signal_roi(r)
        if r.status == "failed":
            tone = "neg"
        elif r.confidence is not None and r.confidence < 0.6:
            tone = "warn"
        elif roi is not None and roi > 1.0:
            tone = "pos"
        out.append({
            "id": r.id,
            "tone": tone,
            "kind": r.status,
            "system_id": r.system_id,
            "timestamp": r.started_at.isoformat() if r.started_at else None,
            "label": _signal_label(r),
        })
    return out


def _aggregate_visible_runs(runs: List[Run]) -> Dict[str, Any]:
    def _sum(values: List[float]) -> float | None:
        return float(sum(values)) if values else None

    def _average(values: List[float]) -> float | None:
        return float(sum(values) / len(values)) if values else None

    costs = [float(run.cost_internal) for run in runs if run.cost_internal is not None]
    values = [
        float(run.value_estimated)
        for run in runs
        if run.value_estimated is not None
        and str(run.value_source or "unset") in {"auto", "operator"}
    ]
    revenues = [
        float(run.revenue_allocated)
        for run in runs
        if run.revenue_allocated is not None
    ]
    confidences = [float(run.confidence) for run in runs if run.confidence is not None]
    efficiencies = [float(run.efficiency) for run in runs if run.efficiency is not None]
    total_cost = _sum(costs)
    estimated_value = _sum(values)
    total_revenue = _sum(revenues)
    roi = (
        (estimated_value - total_cost) / total_cost
        if total_cost not in {None, 0.0} and estimated_value is not None
        else None
    )
    return {
        "runs_count": len(runs),
        "capabilities_count": len(
            {run.capability_id for run in runs if run.capability_id is not None}
        ),
        "total_cost": total_cost,
        "estimated_value": estimated_value,
        "total_revenue": total_revenue,
        "roi": roi,
        "avg_confidence": _average(confidences),
        "avg_efficiency": _average(efficiencies),
        "measurement_states": {
            "total_cost": "available" if total_cost is not None else "not_measured",
            "estimated_value": (
                "available" if estimated_value is not None else "not_measured"
            ),
            "total_revenue": (
                "available" if total_revenue is not None else "not_measured"
            ),
        },
    }


# A ratio is only a claim about yield when its denominator is a real cost.
# Several seeded skills are priced at 0.0, so a run that cost a fraction of a
# cent turned any value at all into a four-digit percentage ("ROI 1462400.0%").
# Below this floor the run is reported as completed, without a yield claim.
MIN_SIGNAL_COST = 0.01
# Past this ratio the exact figure tells an operator nothing more than "much
# more than it cost", and printing it in full reads as a defect.
MAX_SIGNAL_ROI_RATIO = 10.0


def _signal_roi(r: Run) -> float | None:
    """The ROI ratio of one run, or ``None`` when no real cost backs it.

    Same convention as ``_aggregate_visible_runs``: a ratio, not percent
    points, so ``0.5`` means the run returned 1.5x what it cost.
    """

    if r.value_estimated is None or r.cost_internal is None:
        return None
    cost = float(r.cost_internal)
    if cost < MIN_SIGNAL_COST:
        return None
    return (float(r.value_estimated) - cost) / cost


def _format_roi(ratio: float) -> str:
    """Render a ROI ratio as percent, converting exactly once and capping."""

    if ratio > MAX_SIGNAL_ROI_RATIO:
        return f"> {MAX_SIGNAL_ROI_RATIO * 100:.0f}%"
    return f"{ratio * 100:.1f}%"


def _signal_label(r: Run) -> str:
    if r.status == "failed":
        return f"Run failed · {r.error or 'unknown error'}"
    if r.status == "completed":
        roi = _signal_roi(r)
        if roi is not None and roi > 1.5:
            return f"High-yield outcome · ROI {_format_roi(roi)}"
        return f"Run completed · decision {r.decision or '—'}"
    return f"Run {r.status}"


# ---- Recommendations + What-If ----
class WhatIfRequest(BaseModel):
    scope: Literal["portfolio", "capability", "system"] = "capability"
    target_id: Optional[str] = None
    levers: Dict[str, Any] = {}

    @model_validator(mode="after")
    def _require_system_target(self):
        if self.scope == "system" and not self.target_id:
            raise ValueError("target_id is required when scope=system")
        return self


class ProactiveRecommendationRequest(BaseModel):
    since_days: int = 7
    min_evaluations: int = 3
    min_breaches: int = 2
    min_breach_rate: float = 0.5
    dry_run: bool = False


@router.get("/recommendations")
async def list_recommendations(
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    rows = (
        db.query(Decision)
        .filter(Decision.workspace_id == workspace.id, Decision.kind == "recommendation")
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .all()
    )
    rows = readable_decisions(
        db,
        decisions=rows,
        user=user,
        workspace=workspace,
    )[:50]
    return {"items": [{
        "id": d.id,
        "scope": d.scope,
        "target_id": d.target_id,
        "title": d.title,
        "rationale": d.rationale or {},
        "impact_estimate": d.impact_estimate or {},
        "status": d.status,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    } for d in rows]}


@router.post("/recommendations/generate")
async def generate_recommendations(
    body: Optional[ProactiveRecommendationRequest] = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """E5 — Generate proactive Decisions from aggregated E1 eval signals."""
    body = body or ProactiveRecommendationRequest()
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="decision",
        action="admin",
        legacy_allowed=True,
        resource_attrs={"scope": "proactive_recommendation_generation"},
    )
    return generate_proactive_recommendations(
        db,
        workspace_id=workspace.id,
        since_days=body.since_days,
        min_evaluations=body.min_evaluations,
        min_breaches=body.min_breaches,
        min_breach_rate=body.min_breach_rate,
        actor=_actor_label(user),
        dry_run=body.dry_run,
    )


@router.post("/what-if")
async def simulate_what_if(
    body: WhatIfRequest,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Retired decorative preview; authoritative simulation lives in Lot 8."""

    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="value_scenario",
        action="read",
        legacy_allowed=True,
        resource_attrs={"scope": body.scope, "target_id": body.target_id},
    )
    return {
        "kind": "simulation",
        "state": "not_configured",
        "measured": False,
        "scope": body.scope,
        "target_id": body.target_id,
        "model": None,
        "assumptions": None,
        "provenance": None,
        "confidence": None,
        "base": None,
        "projected": None,
        "reason": "authoritative_value_loop_required",
        "replacement": "/systems/{system_id}/value-loop",
    }


def _serialize_decision(d: Decision, *, full: bool = False) -> dict:
    base = {
        "id": d.id,
        "scope": d.scope,
        "target_id": d.target_id,
        "kind": d.kind,
        "status": d.status,
        "title": d.title,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "approved_by": d.approved_by,
        "applied_at": d.applied_at.isoformat() if getattr(d, "applied_at", None) else None,
    }
    if full:
        base.update({
            "rationale": d.rationale or {},
            "impact_estimate": d.impact_estimate or {},
            "notes": d.notes or "",
            "approved_at": d.approved_at.isoformat() if d.approved_at else None,
            "applied_by": getattr(d, "applied_by", None),
            "applied_patch": getattr(d, "applied_patch", None) or {},
        })
    return base


class DecisionTransition(BaseModel):
    note: Optional[str] = None
    actor: Optional[str] = None
    # E1.5.1 — when the Decision is a `review_required` filed by the
    # auto-eval loop, accept/reject can carry the reviewer's verdict
    # so we persist a row in `evaluation_feedback`. All three fields
    # are optional: the existing UI (which doesn't ship feedback yet)
    # keeps working unchanged.
    feedback_label: Optional[str] = None
    feedback_corrected_output: Optional[Dict[str, Any]] = None


class DecisionApplyRequest(BaseModel):
    actor: Optional[str] = None
    enact: bool = True
    patch: Optional[Dict[str, Any]] = None


class ActiveSuggestionApplyRequest(BaseModel):
    actor: Optional[str] = None


class DecisionCreate(BaseModel):
    scope: Literal["portfolio", "capability", "system", "run"] = "capability"
    target_id: Optional[str] = None
    kind: str = "recommendation"
    title: str
    status: Literal["proposed"] = "proposed"
    rationale: Dict[str, Any] = {}
    impact_estimate: Dict[str, Any] = {}
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _validate_target(self):
        if self.scope == "portfolio" and self.target_id is not None:
            raise ValueError("target_id must be null for a portfolio Decision")
        if self.scope != "portfolio" and not self.target_id:
            raise ValueError(f"target_id is required for scope={self.scope}")
        return self


def _actor_label(user: User) -> str:
    return user.email or user.username or user.id


@router.get("/decisions")
async def list_decisions(
    status: Optional[str] = None,
    scope: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Paginated feed of decisions, newest first.

    The Hypervisor cockpit uses this to render the Decisions stream.
    `limit` is clamped to 200 and `offset` supports incremental paging.
    """
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    q = db.query(Decision).filter(Decision.workspace_id == workspace.id)
    if status:
        q = q.filter(Decision.status == status)
    if scope:
        q = q.filter(Decision.scope == scope)
    if kind:
        q = q.filter(Decision.kind == kind)
    rows = q.order_by(Decision.created_at.desc(), Decision.id.desc()).all()
    rows = readable_decisions(
        db,
        decisions=rows,
        user=user,
        workspace=workspace,
    )
    total = len(rows)
    page = rows[offset : offset + limit]
    return {
        "items": [_serialize_decision(d) for d in page],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/decisions", status_code=201)
async def create_decision(
    body: DecisionCreate,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Create a Decision record — used by cockpit CTAs (Scale, Adjust, …)
    to surface a proposal that an operator can then Accept/Reject/Apply.
    """
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="decision",
        action="admin",
        legacy_allowed=True,
        resource_attrs={"target_id": body.target_id},
    )
    row = Decision(
        id=str(uuid4()),
        workspace_id=workspace.id,
        scope=body.scope,
        target_id=body.target_id,
        kind=body.kind,
        status=body.status or "proposed",
        title=body.title,
        rationale=body.rationale or {},
        impact_estimate=body.impact_estimate or {},
        notes=body.notes or "",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize_decision(row, full=True)


@router.get("/decisions/{decision_id}")
async def get_decision(
    decision_id: str,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    d = (
        db.query(Decision)
        .filter(Decision.id == decision_id, Decision.workspace_id == workspace.id)
        .first()
    )
    visible = (
        readable_decisions(
            db,
            decisions=[d],
            user=user,
            workspace=workspace,
        )
        if d is not None
        else []
    )
    if not visible:
        raise HTTPException(404, "Decision not found")
    return _serialize_decision(visible[0], full=True)


def _get_decision_or_404(db: DBSession, workspace_id: str, decision_id: str) -> Decision:
    from fastapi import HTTPException
    d = (
        db.query(Decision)
        .filter(Decision.id == decision_id, Decision.workspace_id == workspace_id)
        .first()
    )
    if not d:
        raise HTTPException(404, "Decision not found")
    return d


def _lock_decision_or_404(db: DBSession, workspace_id: str, decision_id: str) -> Decision:
    d = (
        db.query(Decision)
        .filter(Decision.id == decision_id, Decision.workspace_id == workspace_id)
        .with_for_update(of=Decision)
        .one_or_none()
    )
    if not d:
        raise HTTPException(404, "Decision not found")
    return d


def _maybe_record_eval_feedback(
    db: DBSession,
    *,
    decision: Decision,
    body: Optional[DecisionTransition],
    default_label: str,
    actor: str,
) -> Optional[Dict[str, Any]]:
    """Persist an `EvaluationFeedback` row when the Decision is a
    review-queue triage item.

    Returns the serialized feedback row when written, ``None`` otherwise.
    Silently no-op for non-eval Decisions (no scope=run, no target_id,
    or kind != review_required) so generic Hypervisor recommendations
    keep their existing accept/reject semantics.

    Default label maps the reviewer's transition to a feedback verdict
    (accept = "false_positive", reject = "true_breach"). An explicit
    ``body.feedback_label`` overrides — useful for the
    ``correct_with_fix`` case once the UI ships a correction textarea.
    """
    if decision.kind != "review_required":
        return None
    if (decision.scope or "") != "run":
        return None
    run_id = decision.target_id
    if not run_id:
        return None

    label = (body.feedback_label if body else None) or default_label
    if label not in FEEDBACK_LABELS:
        from fastapi import HTTPException
        raise HTTPException(
            400,
            f"unknown feedback_label {label!r}; expected one of {list(FEEDBACK_LABELS)}",
        )

    score = (
        db.query(EvaluationScore)
        .filter(
            EvaluationScore.run_id == run_id,
            EvaluationScore.workspace_id == decision.workspace_id,
        )
        .order_by(EvaluationScore.created_at.desc())
        .first()
    )

    try:
        fb = record_feedback(
            db,
            workspace_id=decision.workspace_id,
            run_id=run_id,
            label=label,
            decision_id=decision.id,
            evaluation_score_id=score.id if score else None,
            notes=(body.note if body else None),
            corrected_output=(body.feedback_corrected_output if body else None),
            actor=actor,
        )
    except InvalidFeedback as exc:
        from fastapi import HTTPException
        raise HTTPException(400, str(exc))
    return serialize_feedback(fb)


@router.post("/decisions/{decision_id}/accept")
async def accept_decision(
    decision_id: str,
    body: Optional[DecisionTransition] = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    from fastapi import HTTPException
    d = _lock_decision_or_404(db, workspace.id, decision_id)
    if getattr(d, "scenario_id", None):
        raise HTTPException(
            409,
            "Value-loop Decisions must be approved through the value-loop orchestrator",
        )
    actor = _actor_label(user)
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="decision",
        action="approve",
        legacy_allowed=True,
        resource_attrs={"decision_id": d.id, "owner_user_id": None},
    )
    try:
        sm_accept(db, d, actor=actor, note=(body.note if body else None))
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    feedback = _maybe_record_eval_feedback(
        db, decision=d, body=body, default_label="false_positive", actor=actor
    )
    db.commit()
    payload = _serialize_decision(d, full=True)
    if feedback:
        payload["feedback"] = feedback
    return payload


@router.post("/decisions/{decision_id}/reject")
async def reject_decision(
    decision_id: str,
    body: Optional[DecisionTransition] = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    from fastapi import HTTPException
    d = _lock_decision_or_404(db, workspace.id, decision_id)
    if getattr(d, "scenario_id", None):
        raise HTTPException(
            409,
            "Value-loop Decisions must be rejected through the value-loop orchestrator",
        )
    actor = _actor_label(user)
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="decision",
        action="approve",
        legacy_allowed=True,
        resource_attrs={"decision_id": d.id, "owner_user_id": None},
    )
    try:
        sm_reject(db, d, actor=actor, note=(body.note if body else None))
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc))
    feedback = _maybe_record_eval_feedback(
        db, decision=d, body=body, default_label="true_breach", actor=actor
    )
    db.commit()
    payload = _serialize_decision(d, full=True)
    if feedback:
        payload["feedback"] = feedback
    return payload


@router.post("/decisions/{decision_id}/apply")
async def apply_decision_endpoint(
    decision_id: str,
    body: Optional[DecisionApplyRequest] = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    from fastapi import HTTPException
    d = _lock_decision_or_404(db, workspace.id, decision_id)
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="decision",
        action="approve",
        legacy_allowed=True,
        resource_attrs={"decision_id": d.id},
    )
    if getattr(d, "scenario_id", None):
        raise HTTPException(
            409,
            "Value-loop Decisions must be acted through the value-loop orchestrator",
        )
    if (d.status or "proposed") != "accepted":
        raise HTTPException(409, "Decision must be accepted before it can be applied")
    if body and body.patch is not None:
        raise HTTPException(400, "Client-supplied applied patches are not authoritative")
    if body and not body.enact:
        raise HTTPException(400, "A Decision cannot be applied without a real enactment")
    raise HTTPException(
        409,
        detail={
            "code": "LEGACY_DECISION_ACTUATOR_DISABLED",
            "state": "not_configured",
            "message": (
                "Generic Decision enactment is disabled; use the authoritative "
                "Value Scenario → Simulate → Approve → Act workflow"
            ),
        },
    )


@router.post("/decisions/{decision_id}/apply-active-suggestion")
async def apply_active_suggestion(
    decision_id: str,
    body: Optional[ActiveSuggestionApplyRequest] = None,
    workspace: Workspace = Depends(get_current_workspace),
    user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Retired non-idempotent replay shortcut; manual replay remains available."""
    d = _get_decision_or_404(db, workspace.id, decision_id)
    enforce_action(
        db,
        user=user,
        workspace=workspace,
        resource_kind="decision",
        action="approve",
        legacy_allowed=True,
        resource_attrs={"decision_id": d.id},
    )
    raise HTTPException(
        409,
        detail={
            "code": "ACTIVE_SUGGESTION_ACTUATOR_DISABLED",
            "state": "not_configured",
            "message": (
                "Use the authorized Run replay workflow; automatic suggestion "
                "actuation is not idempotent and remains disabled"
            ),
        },
    )
