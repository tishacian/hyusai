"""Declared Skill prices do not masquerade as the cost of LLM providers."""

import asyncio
from uuid import uuid4

import pytest

from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.services.model_plane import execution as model_runtime
from app.services.model_plane.execution import ModelExecution
from app.services.run_engine import engine


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("kind", ["native_planner", "authored_prompt", "nested_model"])
@pytest.mark.parametrize("configured_price", [True, False])
async def test_model_catalog_cost_is_preserved_but_provider_cost_stays_unknown(
    db_session,
    monkeypatch,
    outcome,
    kind,
    configured_price,
):
    slug = "decide_next_v1" if kind == "native_planner" else "qualified-model-tool"
    skill = Skill(
        id=str(uuid4()),
        slug=slug,
        name=slug,
        version="v1",
        input_schema={},
        output_schema={},
        pricing={"unit_price": 0.003, "currency": "USD", "unit": "per_call"}
        if configured_price
        else {},
        execution={"mode": "sync"},
    )
    run = Run(id=str(uuid4()), status="running", input_ref={})
    db_session.add_all([skill, run])
    db_session.commit()
    model = None if kind == "nested_model" else ModelExecution("openai", "gpt-test", "test", "test")
    monkeypatch.setattr(
        model_runtime, "resolve_skill_model_execution", lambda *_args, **_kwargs: model
    )

    async def invoke(_payload, ctx):
        pending = db_session.query(SkillInvocation).filter_by(run_id=run.id).one()
        assert pending.provider_cost_usd is None
        ctx["_provider_usage_v1"] = {
            "calls": [{"provider": "openai", "model": "gpt-test", "reported": False}],
        }
        if outcome == "failed":
            raise RuntimeError("Provider usage unavailable after dispatch")
        if outcome == "cancelled":
            raise asyncio.CancelledError()
        # Prices returned by arbitrary tool/model output are not authoritative.
        return {"provider_cost_usd": 999, "cost": {"amount": 999, "currency": "USD"}}

    monkeypatch.setattr(engine, "resolve_skill", lambda _slug: invoke)
    if outcome == "cancelled":
        with pytest.raises(asyncio.CancelledError):
            await engine._execute_task_node(db_session, run, {}, slug, control=None, last_output={})
        invocation = db_session.query(SkillInvocation).filter_by(run_id=run.id).one()
    else:
        invocation = await engine._execute_task_node(
            db_session, run, {}, slug, control=None, last_output={}
        )
    assert invocation.status == outcome
    assert invocation.cost == (0.003 if configured_price else 0.0)
    assert invocation.cost_measured is configured_price
    if configured_price:
        assert invocation.metrics["cost_evidence"]["method"] == "catalog_unit_price"
    else:
        assert invocation.metrics["cost_evidence"]["state"] == "not_measured"
    assert invocation.provider_cost_usd is None
    assert invocation.metrics["provider_cost_evidence"] == {
        "state": "not_measured",
        "reason": "llm_provider_tariff_not_configured"
        if configured_price
        else "unit_price_not_configured",
        "declared_skill_cost_preserved": configured_price,
    }


@pytest.mark.parametrize("known_subtotal", [0.0, 0.25])
def test_run_provider_total_stays_unknown_when_one_model_has_no_tariff(
    db_session,
    monkeypatch,
    known_subtotal,
):
    monkeypatch.setattr("app.services.evaluation.auto_eval.schedule_eval", lambda _id: None)
    system = System(id=str(uuid4()), name="Cost qualification", objective="Preserve unknown costs")
    run = Run(id=str(uuid4()), system_id=system.id, status="running", input_ref={})
    calls = [
        SkillInvocation(
            id=str(uuid4()),
            run_id=run.id,
            skill_slug="known_call",
            status="completed",
            cost=known_subtotal,
            cost_measured=True,
            provider_cost_usd=known_subtotal,
            output_ref={},
            metrics={"cost_evidence": {"currency": "USD"}},
        ),
        SkillInvocation(
            id=str(uuid4()),
            run_id=run.id,
            skill_slug="model_call",
            status="completed",
            cost=0.003,
            cost_measured=True,
            provider_cost_usd=None,
            output_ref={},
            metrics={"provider_cost_evidence": {"state": "not_measured"}},
        ),
    ]
    db_session.add_all([system, run, *calls])
    db_session.commit()

    engine._finalize_run(
        db_session,
        run,
        system=system,
        capability=None,
        control=None,
        invocations=calls,
        duration_ms=20,
        last_output={"completed": True},
    )

    db_session.refresh(run)
    assert run.status == "completed"
    assert run.provider_cost_usd is None
    assert calls[0].provider_cost_usd == known_subtotal  # known subtotal remains inspectable
