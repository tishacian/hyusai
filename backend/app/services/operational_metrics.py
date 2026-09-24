"""Operational measures from authorized canonical evidence, not model verdicts."""
from datetime import datetime, timedelta, time
from statistics import mean
from app.models.run import Run, SkillInvocation
from app.models.decision import Decision
from app.schemas.operational_objective import OperationalObjective, UNITS
from app.services.run_access import readable_runs, readable_skill_invocations_for_runs
from app.services.decision_access import readable_decisions
from app.services.projection_integrity import invocation_cost_is_measured
from app.services.system_perspective import _is_showcase_seed_payload


def operational_metrics(db, *, user, workspace, system, objective=None, now=None):
    """Measures over the objective's period; ``objective`` defaults to the System's.

    A value contract passes its own indicator, target and period (and a clock
    in tests); the System's operational objective stays the default.
    """
    if objective is None:
        objective = (system.settings or {}).get("operational_objective")
    target = OperationalObjective.model_validate(objective) if objective else None
    now = now or datetime.utcnow()
    start = datetime.combine(target.period_start, time.min) if target else now - timedelta(days=30)
    end = datetime.combine(target.period_end, time.min) if target else now
    rows = (
        db.query(Run)
        .filter(
            Run.workspace_id == workspace.id,
            Run.system_id == system.id,
            Run.started_at >= start,
            Run.started_at < end,
        )
        .order_by(Run.started_at.desc())
        .limit(10001)
        .all()
    )
    truncated = len(rows) > 10000
    runs = readable_runs(db, runs=rows[:10000], user=user, workspace=workspace)
    restricted = len(runs) != min(len(rows), 10000)
    excluded = {
        r.id
        for r in runs
        if _is_showcase_seed_payload(r.input_ref) or _is_showcase_seed_payload(r.output_ref)
    }
    all_ids = [r.id for r in runs]
    all_invocations = (
        db.query(SkillInvocation).filter(SkillInvocation.run_id.in_(all_ids)).all()
        if all_ids
        else []
    )
    invocations = readable_skill_invocations_for_runs(
        db, invocations=all_invocations, runs=runs, user=user, workspace=workspace
    )
    restricted = restricted or len(invocations) != len(all_invocations)
    excluded.update(
        i.run_id
        for i in invocations
        if any(_is_showcase_seed_payload(v) for v in (i.metrics, i.trace, i.output_ref))
    )
    runs = [r for r in runs if r.id not in excluded]
    invocations = [i for i in invocations if i.run_id not in excluded]
    ids = [r.id for r in runs]
    all_decisions = (
        db.query(Decision)
        .filter(
            Decision.workspace_id == workspace.id,
            Decision.scope == "run",
            Decision.target_id.in_(ids),
        )
        .all()
        if ids
        else []
    )
    decisions = readable_decisions(db, decisions=all_decisions, user=user, workspace=workspace)
    restricted = restricted or len(decisions) != len(all_decisions)
    human = [
        d
        for d in decisions
        if d.human_confirmed_by
        and d.human_confirmed_at
        and d.status in ("accepted", "rejected", "applied")
    ]
    durations = [
        r.duration_ms for r in runs if r.status == "completed" and r.duration_ms is not None
    ]
    costs = [i.cost for i in invocations if invocation_cost_is_measured(i)]
    complete = not truncated and not restricted
    demo = (system.settings or {}).get("showcase_seed") is True

    def fact(metric, value, count, source, sufficient=True):
        # A current queue snapshot cannot reconstruct the queue at a past
        # period boundary. Never present it as a historical target comparison.
        comparable = complete and sufficient and now >= end and metric != "human_waits"
        return {
            "metric": metric,
            "value": value,
            "unit": UNITS[metric],
            "sample_count": count,
            "state": "measured" if value is not None else "not_measured",
            "source": source,
            "delta": value - target.target
            if target and target.metric == metric and value is not None and comparable
            else None,
            "comparable": comparable,
            "complete": complete and sufficient,
            "comparison_note": "current_queue_snapshot" if metric == "human_waits" else None,
        }

    metrics = [
        fact(
            "completed_volume", sum(r.status == "completed" for r in runs), len(runs), "runs.status"
        ),
        fact(
            "mean_duration_ms",
            mean(durations) if durations else None,
            len(durations),
            "runs.duration_ms",
            len(durations) == sum(r.status == "completed" for r in runs),
        ),
        fact(
            "human_waits",
            sum(r.status == "hitl_pending" for r in runs),
            len(runs),
            "runs.status:hitl_pending",
        ),
        fact(
            "human_validation_rate",
            100 * sum(d.status in ("accepted", "applied") for d in human) / len(human)
            if human
            else None,
            len(human),
            "decisions.human_confirmed_by,human_confirmed_at,status",
            len(human) == len(decisions),
        ),
        fact(
            "measured_cost_usd",
            sum(costs) if costs else None,
            len(costs),
            "skill_invocations.cost,cost_measured",
            len(costs) == len(invocations) and bool(costs),
        ),
    ]
    return {
        "system_id": system.id,
        "objective": objective,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "generated_at": now.isoformat(),
        "demonstration": demo,
        "excluded_synthetic_runs": len(excluded),
        "complete": complete,
        "metrics": metrics,
        "run_ids": ids[:20],
        "decision_ids": [d.id for d in human][:20],
        "economic_impact": None,
        "economic_impact_state": "not_attested",
        "next_action": "Open the canonical value-loop scenario and measurement evidence to assess economic impact.",
    }
