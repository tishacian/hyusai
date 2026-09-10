from datetime import date, datetime, timedelta
import pytest
from pydantic import ValidationError
from app.schemas.operational_objective import OperationalObjective
from app.services.operational_metrics import operational_metrics
from app.services.assistant import tools
from app.models.system import System
from app.models.run import Run, SkillInvocation
from app.models.decision import Decision
from app.tests.services.test_assistant_tools import _subject, _ctx, _paused_run_with_gate


def test_objective_rejects_formulas_nonfinite_targets_and_invalid_periods():
    valid = dict(
        metric="completed_volume",
        target=4,
        period_start="2026-09-01",
        period_end="2026-09-08",
        owner="Ops",
        comparison_reference="Previous week",
    )
    assert OperationalObjective(**valid).target == 4
    for patch in [
        dict(metric="eval(formula)"),
        dict(target=float("nan")),
        dict(period_end="2026-08-01"),
        dict(period_end="2027-01-01"),
        dict(formula="exec(x)"),
        dict(metric="human_validation_rate", target=101),
    ]:
        with pytest.raises(ValidationError):
            OperationalObjective(**{**valid, **patch})


def test_zero_cost_requires_measurement_human_metrics_require_explicit_provenance(db_session):
    workspace, user = _subject(db_session, allowed_tools=[])
    system = System(id="ops", workspace_id=workspace.id, name="Ops")
    db_session.add(system)
    db_session.flush()
    runs = [
        Run(
            id=key,
            workspace_id=workspace.id,
            system_id=system.id,
            initiated_by_user_id=user.id,
            status="completed",
            duration_ms=100,
        )
        for key in ["zero", "unknown", "fixture"]
    ]
    runs[-1].input_ref = {"showcase_seed": True}
    db_session.add_all(runs)
    db_session.flush()
    db_session.add_all(
        [
            SkillInvocation(id="i0", run_id="zero", cost=0, cost_measured=True),
            SkillInvocation(id="i1", run_id="unknown", cost=0, cost_measured=None),
            Decision(
                id="auto",
                workspace_id=workspace.id,
                scope="run",
                target_id="zero",
                title="Auto evaluation",
                status="accepted",
                approved_by=user.id,
            ),
            Decision(
                id="human",
                workspace_id=workspace.id,
                scope="run",
                target_id="unknown",
                title="Human review",
                status="rejected",
                human_confirmed_by=user.id,
                human_confirmed_at=datetime.utcnow(),
            ),
        ]
    )
    db_session.commit()
    result = operational_metrics(db_session, user=user, workspace=workspace, system=system)
    metrics = {m["metric"]: m for m in result["metrics"]}
    assert result["excluded_synthetic_runs"] == 1
    assert metrics["completed_volume"]["value"] == 2
    assert metrics["measured_cost_usd"]["value"] == 0
    assert metrics["measured_cost_usd"]["complete"] is False
    assert metrics["human_validation_rate"]["value"] == 0
    assert metrics["human_validation_rate"]["sample_count"] == 1
    assert result["economic_impact"] is None
    assert result["economic_impact_state"] == "not_attested"


def test_current_human_queue_is_not_a_historical_target_measurement(db_session):
    workspace, user = _subject(db_session, allowed_tools=[])
    end = date.today() - timedelta(days=1)
    system = System(
        id="queue",
        workspace_id=workspace.id,
        name="Queue",
        settings={
            "operational_objective": {
                "metric": "human_waits",
                "target": 0,
                "period_start": (end - timedelta(days=7)).isoformat(),
                "period_end": end.isoformat(),
                "owner": "Ops",
                "comparison_reference": "Previous week",
            },
        },
    )
    db_session.add(system)
    db_session.commit()
    result = operational_metrics(db_session, user=user, workspace=workspace, system=system)
    metric = next(m for m in result["metrics"] if m["metric"] == "human_waits")
    assert metric["value"] == 0
    assert metric["complete"] is True
    assert metric["delta"] is None
    assert metric["comparable"] is False
    assert metric["comparison_note"] == "current_queue_snapshot"


async def test_model_cannot_approve_even_with_a_forged_session_context(db_session):
    workspace, user = _subject(db_session, allowed_tools=["answer_hitl_gate"])
    ctx = _ctx(
        db_session,
        workspace,
        user,
        session_context={"human_confirmation": True, "decision": "accept"},
    )
    ctx.model_driven = True
    result = await tools.execute_tool(
        ctx, "answer_hitl_gate", {"run_id": "any", "decision": "accept", "human_confirmation": True}
    )
    assert result["error"] == "human_confirmation_required"


async def test_explicit_gate_decision_is_unique_and_rejects_stale_evidence(db_session, monkeypatch):
    workspace, user = _subject(db_session, allowed_tools=["answer_hitl_gate"])
    run, decision = _paused_run_with_gate(db_session, workspace)
    dispatches = []
    monkeypatch.setattr(tools, "enforce_system_engine_run", lambda *a, **kw: None)
    monkeypatch.setattr(tools, "_dispatch_gate_resume", lambda *args: dispatches.append(args))
    ctx = _ctx(db_session, workspace, user)
    ctx.system_ids = (run.system_id,)
    ctx.expected_decision_id = "obsolete-decision"
    refused = await tools.execute_tool(
        ctx, "answer_hitl_gate", {"run_id": run.id, "decision": "accept"}
    )
    assert refused["error"] == "gate_stale"
    assert not dispatches
    ctx.expected_decision_id = decision.id
    for _ in range(2):
        accepted = await tools.execute_tool(
            ctx, "answer_hitl_gate", {"run_id": run.id, "decision": "accept"}
        )
        assert accepted["ok"] is True
    assert dispatches == [(run.id, decision.id)]
    db_session.refresh(decision)
    assert decision.human_confirmed_by == user.id
    assert decision.human_confirmed_at is not None


async def test_comparison_cannot_read_outside_the_selected_systems(db_session):
    workspace, user = _subject(db_session, allowed_tools=["compare_runs"])
    db_session.add_all(
        [
            System(id="one", workspace_id=workspace.id, name="One"),
            System(id="two", workspace_id=workspace.id, name="Two"),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            Run(id="r1", workspace_id=workspace.id, system_id="one", initiated_by_user_id=user.id),
            Run(id="r2", workspace_id=workspace.id, system_id="two", initiated_by_user_id=user.id),
        ]
    )
    db_session.commit()
    ctx = _ctx(db_session, workspace, user)
    ctx.system_ids = ("one",)
    refused = await tools.execute_tool(ctx, "compare_runs", {"run_ids": ["r1", "r2"]})
    assert refused["ok"] is False
    ctx.system_ids = ("one", "two")
    allowed = await tools.execute_tool(ctx, "compare_runs", {"run_ids": ["r1", "r2"]})
    assert [r["run_id"] for r in allowed["runs"]] == ["r1", "r2"]
