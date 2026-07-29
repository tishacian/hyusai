"""Behavioral proof for authoritative MembraneSpec v2 in the DAG runtime."""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.models.decision import Decision
from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.services.membrane.enforcement import (
    MeasurementCoverage,
    MembraneEnforcementError,
    ProvenanceArtifact,
    collect_valve_usage,
)
from app.services.run_engine import dag as dag_module
from app.services.run_engine import engine as engine_module
from app.services.run_engine.dag import execute_run_dag, resume_run_dag


@pytest.fixture(autouse=True)
def _no_background_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.evaluation import auto_eval

    monkeypatch.setattr(auto_eval, "schedule_eval", lambda _run_id: None)


def _install_skill(monkeypatch: pytest.MonkeyPatch, slug: str, fn) -> None:
    monkeypatch.setattr(
        engine_module,
        "resolve_skill",
        lambda requested: fn
        if requested == slug
        else (_ for _ in ()).throw(NotImplementedError(requested)),
    )


def _create_contract(
    db,
    *,
    slug: str,
    membrane_spec: dict[str, Any],
    default_model: str = "gpt-test",
    retry: bool = False,
) -> tuple[System, Run]:
    skill = Skill(
        id=str(uuid.uuid4()),
        slug=slug,
        version="v1",
        name=slug,
        description="membrane test skill",
        input_schema={},
        output_schema={},
        pricing={"unit_price": 0.25},
        execution={"mode": "sync", "idempotent": True},
        certification_level="basic",
    )
    node = {
        "id": "work",
        "kind": "retry" if retry else "task",
        "config": {
            "skill_slug": slug,
            **({"max_attempts": 5, "backoff_ms": 0} if retry else {}),
        },
    }
    flow = {
        "schema_version": 2,
        "nodes": [
            {"id": "source", "kind": "source"},
            node,
            {"id": "sink", "kind": "sink"},
        ],
        "edges": [
            {"from": "source", "to": "work"},
            {"from": "work", "to": "sink"},
        ],
    }
    system = System(
        id=str(uuid.uuid4()),
        name="Membrane v2 system",
        objective="prove fail-closed runtime enforcement",
        skill_ids=[skill.id],
        flow_definition=flow,
        default_model=default_model,
    )
    policy = ControlPolicy(
        id=str(uuid.uuid4()),
        workspace_id=None,
        name="Membrane v2 enforce",
        scope="system",
        target_id=system.id,
        allowed_skills=[slug],
        allowed_models=[default_model],
        extra={"membrane_spec": membrane_spec},
    )
    system.control_policy_id = policy.id
    run = Run(
        id=str(uuid.uuid4()),
        system_id=system.id,
        input_ref={"query": "contract risk"},
        output_ref={},
        status="pending",
    )
    db.add_all([skill, system, policy, run])
    db.commit()
    return system, run


def _spec(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "version": 2,
        "enforcement_mode": "enforce",
        "outbound": {"expert_review_required": False},
        "capabilities": {
            "allowed_skills": ["answer_v1"],
            "allowed_models": ["gpt-test"],
            "allowed_actions": ["system.engine.run"],
        },
        "provenance": {"require_citations": True},
    }
    payload.update(overrides)
    return payload


def _fake_artifact(*_args: Any, **_kwargs: Any) -> ProvenanceArtifact:
    return ProvenanceArtifact(
        uri="object://membrane/run/provenance.json",
        key="membrane/run/provenance.json",
        sha256="a" * 64,
        size_bytes=123,
        created_at="2026-07-20T00:00:00Z",
    )


def test_subflow_without_invocation_ledger_is_a_parent_measurement_gap(db_session) -> None:
    parent = Run(
        id=str(uuid.uuid4()),
        workspace_id=None,
        input_ref={},
        output_ref={},
        status="running",
        trigger="manual",
    )
    child = Run(
        id=str(uuid.uuid4()),
        workspace_id=None,
        parent_run_id=parent.id,
        input_ref={},
        output_ref={},
        status="completed",
        trigger="subflow",
    )
    measured_parent_work = SkillInvocation(
        id=str(uuid.uuid4()),
        run_id=parent.id,
        status="completed",
        cost=0,
        cost_measured=True,
        metrics={"total_tokens": 0},
        latency_ms=0,
    )
    db_session.add_all([parent, child, measured_parent_work])
    db_session.commit()

    ledger, gaps = engine_module._valve_invocation_ledger(db_session, parent)
    usage = collect_valve_usage(ledger, measurement_gaps=gaps)

    assert gaps == 1
    assert usage.cost == 0
    assert usage.tokens == 0
    assert usage.invocation_count == 1
    assert usage.measurement_gap_count == 1
    assert usage.cost_coverage is MeasurementCoverage.PARTIAL
    assert usage.token_coverage is MeasurementCoverage.PARTIAL


async def test_invalid_explicit_v2_fails_closed_before_first_invocation(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def answer(_payload, _ctx):
        raise AssertionError("an invalid v2 membrane must block before invocation")

    invalid_spec = _spec(capabilities=["not-an-object"])
    _install_skill(monkeypatch, "answer_v1", answer)
    system, run = _create_contract(
        db_session,
        slug="answer_v1",
        membrane_spec=invalid_spec,
    )
    control = (
        db_session.query(ControlPolicy)
        .filter(ControlPolicy.id == system.control_policy_id)
        .one()
    )

    with pytest.raises(MembraneEnforcementError, match="^membrane_spec_invalid:"):
        engine_module._safe_membrane(control)

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "failed"
    assert "membrane_spec_invalid:" in summary["error"]
    assert (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .count()
        == 0
    )


async def test_citations_from_typed_pool_are_persisted_as_provenance(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def answer(_payload, ctx):
        assert ctx["source_policy"]["membrane_spec"]["version"] == 2
        return {
            "answer": "risk found",
            "confidence": 0.92,
            "citations": [{"id": "clause-7"}],
            "usage": {"total_tokens": 21},
        }

    _install_skill(monkeypatch, "answer_v1", answer)
    monkeypatch.setattr(dag_module, "persist_provenance_artifact", _fake_artifact)
    _, run = _create_contract(db_session, slug="answer_v1", membrane_spec=_spec())

    summary = await execute_run_dag(run.id)
    assert summary["status"] == "completed"

    db_session.expire_all()
    stored = db_session.query(Run).filter(Run.id == run.id).one()
    assert stored.output_ref["answer"] == "risk found"
    assert stored.output_ref["_membrane_provenance"]["sha256"] == "a" * 64
    invocation = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .one()
    )
    assert invocation.metrics["total_tokens"] == 21
    assert invocation.trace["membrane_provenance"]["uri"].startswith("object://")


async def test_low_confidence_egress_holds_without_publishing_then_resumes_once(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    async def answer(_payload, _ctx):
        calls["count"] += 1
        return {
            "answer": "needs review",
            "confidence": 0.4,
            "citations": [{"id": "clause-2"}],
        }

    spec = _spec(outbound={"expert_review_required": False, "gate_if_confidence_below": 0.8})
    _install_skill(monkeypatch, "answer_v1", answer)
    monkeypatch.setattr(dag_module, "persist_provenance_artifact", _fake_artifact)
    _, run = _create_contract(db_session, slug="answer_v1", membrane_spec=spec)

    paused = await execute_run_dag(run.id)
    assert paused["status"] == "hitl_pending"
    assert calls["count"] == 1
    db_session.expire_all()
    stored = db_session.query(Run).filter(Run.id == run.id).one()
    assert stored.output_ref == {}
    checkpoint = next(
        cp for cp in reversed(stored.checkpoints or []) if cp.get("kind") == "hitl_pause"
    )
    assert checkpoint["membrane_egress"] is True
    from app.api.v1.endpoints.runs import _invocation, _row

    public_run = _row(stored, db=db_session)
    public_pause = next(
        cp
        for cp in reversed(public_run["checkpoints"])
        if cp.get("kind") == "hitl_pause"
    )
    assert public_run["result_held"] is True
    assert "state" not in public_pause
    held_invocation = (
        db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).one()
    )
    assert _invocation(held_invocation, redact_io=True)["output_ref"] == {}

    decision = (
        db_session.query(Decision)
        .filter(Decision.id == paused["awaiting_decision"])
        .one()
    )
    decision.status = "accepted"
    db_session.commit()
    resumed = await resume_run_dag(run.id, decision_id=decision.id)
    assert resumed["status"] == "completed"
    assert calls["count"] == 1
    assert (
        db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).count()
        == 1
    )


async def test_rejected_egress_never_publishes_result(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def answer(_payload, _ctx):
        return {"answer": "private", "confidence": 0.3, "citations": [{"id": "c"}]}

    spec = _spec(outbound={"expert_review_required": True})
    _install_skill(monkeypatch, "answer_v1", answer)
    _, run = _create_contract(db_session, slug="answer_v1", membrane_spec=spec)
    paused = await execute_run_dag(run.id)
    decision = db_session.query(Decision).filter(Decision.id == paused["awaiting_decision"]).one()
    decision.status = "rejected"
    db_session.commit()

    rejected = await resume_run_dag(run.id, decision_id=decision.id)
    assert rejected["status"] == "failed"
    db_session.expire_all()
    stored = db_session.query(Run).filter(Run.id == run.id).one()
    assert stored.output_ref == {}
    assert stored.error == "membrane_egress_rejected"


async def test_required_citations_block_terminal_output(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def answer(_payload, _ctx):
        return {"answer": "unsupported", "confidence": 0.9}

    _install_skill(monkeypatch, "answer_v1", answer)
    _, run = _create_contract(db_session, slug="answer_v1", membrane_spec=_spec())
    summary = await execute_run_dag(run.id)
    assert summary["status"] == "failed"
    assert "citations_required" in summary["error"]
    db_session.expire_all()
    assert db_session.query(Run).filter(Run.id == run.id).one().output_ref == {}


async def test_usage_priced_invocation_without_quantity_blocks_cost_budget(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def answer(_payload, _ctx):
        return {
            "answer": "priced by usage",
            "citations": [{"id": "c"}],
            "usage": {"total_tokens": 0},
        }

    _install_skill(monkeypatch, "answer_v1", answer)
    _, run = _create_contract(
        db_session,
        slug="answer_v1",
        membrane_spec=_spec(
            provenance={"require_citations": False},
            valves={"max_cost_per_decision": 1},
        ),
    )
    skill = db_session.query(Skill).filter(Skill.slug == "answer_v1").one()
    skill.pricing = {
        "currency": "USD",
        "unit": "per_1k_tokens",
        "unit_price": 0.25,
    }
    db_session.commit()

    summary = await execute_run_dag(run.id)

    assert summary["status"] == "failed"
    assert "cost_measurement_unavailable" in summary["error"]
    invocation = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .one()
    )
    assert invocation.cost == 0
    assert invocation.cost_measured is False
    assert invocation.metrics["cost_evidence"]["reason"] == "pricing_quantity_not_measured"


async def test_missing_token_measurement_blocks(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def missing(_payload, _ctx):
        return {"answer": "missing usage", "citations": [{"id": "c"}]}

    _install_skill(monkeypatch, "answer_v1", missing)
    _, missing_run = _create_contract(
        db_session,
        slug="answer_v1",
        membrane_spec=_spec(
            provenance={"require_citations": False},
            valves={"token_budget": 1},
        ),
    )
    missing_summary = await execute_run_dag(missing_run.id)
    assert missing_summary["status"] == "failed"
    assert "token_measurement_unavailable" in missing_summary["error"]


async def test_explicit_zero_token_measurement_completes(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def zero(_payload, _ctx):
        return {
            "answer": "zero usage",
            "citations": [{"id": "c"}],
            "usage": {"total_tokens": 0},
        }

    _install_skill(monkeypatch, "answer_v1", zero)
    _, zero_run = _create_contract(
        db_session,
        slug="answer_v1",
        membrane_spec=_spec(
            provenance={"require_citations": False},
            valves={"token_budget": 1},
        ),
    )
    zero_summary = await execute_run_dag(zero_run.id)
    assert zero_summary["status"] == "completed"
    zero_invocation = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == zero_run.id)
        .one()
    )
    assert zero_invocation.metrics["total_tokens"] == 0


async def test_shadow_records_missing_token_measurement_without_blocking(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def answer(_payload, _ctx):
        return {"answer": "shadow", "citations": [{"id": "c"}]}

    _install_skill(monkeypatch, "answer_v1", answer)
    _, run = _create_contract(
        db_session,
        slug="answer_v1",
        membrane_spec=_spec(
            enforcement_mode="shadow",
            provenance={"require_citations": False},
            valves={"token_budget": 1},
        ),
    )

    summary = await execute_run_dag(run.id)

    assert summary["status"] == "completed"
    breach = (
        db_session.query(Decision)
        .filter(
            Decision.target_id == run.system_id,
            Decision.kind == "policy_breach",
        )
        .order_by(Decision.created_at.desc())
        .first()
    )
    assert breach is not None
    assert breach.rationale["breaches"] == ["token_measurement_unavailable"]
    assert breach.rationale["hard_abort"] is False
    assert breach.rationale["usage"]["coverage"]["tokens"] == "unavailable"


async def test_disallowed_model_blocks_before_first_invocation(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def answer(_payload, _ctx):
        raise AssertionError("the skill must not be invoked")

    spec = _spec(
        capabilities={
            "allowed_skills": ["answer_v1"],
            "allowed_models": ["gpt-allowed"],
            "allowed_actions": ["system.engine.run"],
        }
    )
    _install_skill(monkeypatch, "answer_v1", answer)
    _, run = _create_contract(db_session, slug="answer_v1", membrane_spec=spec)
    summary = await execute_run_dag(run.id)
    assert summary["status"] == "failed"
    assert summary["error"] == "membrane_capability_block:system.engine.run"
    assert (
        db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).count()
        == 0
    )


async def test_retry_failures_trip_circuit_breaker_without_extra_attempt(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"count": 0}

    async def broken(_payload, _ctx):
        calls["count"] += 1
        raise RuntimeError("boom")

    spec = _spec(
        capabilities={
            "allowed_skills": ["broken_v1"],
            "allowed_models": ["gpt-test"],
            "allowed_actions": ["system.engine.run"],
        },
        provenance={"require_citations": False},
        valves={"circuit_breaker": {"failure_threshold": 2, "max_attempts": 5}},
    )
    _install_skill(monkeypatch, "broken_v1", broken)
    _, run = _create_contract(
        db_session,
        slug="broken_v1",
        membrane_spec=spec,
        retry=True,
    )
    summary = await execute_run_dag(run.id)
    assert summary["status"] == "failed"
    assert "circuit_breaker_failures" in summary["error"]
    assert calls["count"] == 2
    invocations = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id)
        .order_by(SkillInvocation.started_at.asc())
        .all()
    )
    assert len(invocations) == 2
    assert invocations[0].trace["membrane_attempt_kind"] == "task"
    assert invocations[1].trace["membrane_attempt_kind"] == "retry"
