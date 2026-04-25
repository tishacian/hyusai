"""E1 auto-eval tests — preset resolution, threshold breach, decision filing.

Scope: the service layer only. The HTTP endpoints are covered by a
separate smoke once the test harness has Keycloak mocked; here we
exercise the deterministic parts (preset merge, threshold math,
Decision creation) without touching the judge LLM.

We monkey-patch :class:`~app.services.evaluation.judge.JudgeService` to
return canned score dicts — calling real GPT in CI would be slow,
flaky, and expensive.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

import pytest

from app.models.capability import Capability
from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.evaluation_preset import EvaluationPreset
from app.models.run import Run
from app.models.system import System
from app.models.workspace import Workspace
from app.services.evaluation import auto_eval
from app.services.evaluation_preset_service import (
    DEFAULT_EVAL_CONFIG,
    get_evaluation_preset_service,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_minimal_run(
    db,
    *,
    query: str = "What is the capital of France?",
    response: str = "Paris is the capital of France.",
    status: str = "completed",
) -> Run:
    ws = Workspace(id=str(uuid4()), slug=f"ws-{uuid4().hex[:6]}", name="WS")
    db.add(ws)
    cap = Capability(
        id=str(uuid4()),
        slug=f"cap-{uuid4().hex[:6]}",
        name="Generic",
        workspace_id=ws.id,
    )
    db.add(cap)
    system = System(
        id=str(uuid4()),
        name="Sys",
        workspace_id=ws.id,
        capability_id=cap.id,
    )
    db.add(system)
    db.commit()

    run = Run(
        id=str(uuid4()),
        workspace_id=ws.id,
        system_id=system.id,
        capability_id=cap.id,
        input_ref={"query": query},
        output_ref={"answer": response},
        status=status,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    return run


class _StubJudge:
    """Returns whatever the test asked for, no network."""

    def __init__(self, *, scores, composite_score, hallucination_rate):
        self._scores = scores
        self._composite = composite_score
        self._halluc = hallucination_rate

    async def evaluate(self, **kwargs):
        return {
            "id": str(uuid4()),
            "scores": self._scores,
            "composite_score": self._composite,
            "hallucination_rate": self._halluc,
            "drift_rate": 0.0,
            "claim_audit": {"supported": 3, "unsupported": 0, "claims": []},
            "overall_note": "stub",
            "created_at": datetime.utcnow().isoformat(),
        }


# ---------------------------------------------------------------------------
# Preset resolver
# ---------------------------------------------------------------------------


def test_preset_resolver_returns_defaults_for_empty_workspace(db_session):
    """A workspace with no preset gets the built-in defaults."""
    ws = Workspace(id=str(uuid4()), slug=f"acme-{uuid4().hex[:6]}", name="Acme")
    db_session.add(ws)
    db_session.commit()

    service = get_evaluation_preset_service()
    resolved = service.resolve(db_session, workspace_id=ws.id)

    assert resolved["enabled"] is True
    assert resolved["composite_min"] == DEFAULT_EVAL_CONFIG["composite_min"]
    assert resolved["composite_min"] == 70.0
    assert resolved["dimension_min"]["safety"] == 80.0


def test_preset_resolver_merges_workspace_override_onto_defaults(db_session):
    """A partial workspace preset wins on overridden keys, falls back on the rest."""
    ws = Workspace(id=str(uuid4()), slug=f"acme2-{uuid4().hex[:6]}", name="Acme2")
    db_session.add(ws)
    db_session.commit()

    service = get_evaluation_preset_service()
    service.upsert_workspace_preset(
        db_session,
        workspace_id=ws.id,
        config={"enabled": True, "composite_min": 75.0},
    )

    resolved = service.resolve(db_session, workspace_id=ws.id)
    assert resolved["enabled"] is True
    assert resolved["composite_min"] == 75.0
    # Not overridden — should inherit from defaults
    assert resolved["hallucination_max"] == DEFAULT_EVAL_CONFIG["hallucination_max"]
    # dimension_min should merge, not replace
    assert resolved["dimension_min"]["safety"] == 80.0


def test_preset_resolver_supports_workspace_opt_out(db_session):
    """E1.5.4 auto-onboards by default, but workspace admins can opt out."""
    ws = Workspace(id=str(uuid4()), slug=f"optout-{uuid4().hex[:6]}", name="OptOut")
    db_session.add(ws)
    db_session.commit()

    service = get_evaluation_preset_service()
    service.upsert_workspace_preset(
        db_session,
        workspace_id=ws.id,
        config={"enabled": False},
        name="Workspace default",
    )

    resolved = service.resolve(db_session, workspace_id=ws.id)
    assert resolved["enabled"] is False
    assert resolved["composite_min"] == DEFAULT_EVAL_CONFIG["composite_min"]


def test_preset_system_scope_wins_over_workspace(db_session):
    ws = Workspace(id=str(uuid4()), slug=f"acme3-{uuid4().hex[:6]}", name="Acme3")
    db_session.add(ws)
    db_session.commit()
    system_id = str(uuid4())

    service = get_evaluation_preset_service()
    service.upsert_workspace_preset(
        db_session, workspace_id=ws.id, config={"composite_min": 60.0}
    )
    db_session.add(
        EvaluationPreset(
            id=str(uuid4()),
            name="strict system",
            scope="system",
            scope_id=system_id,
            workspace_id=ws.id,
            config={"composite_min": 90.0},
        )
    )
    db_session.commit()

    resolved = service.resolve(
        db_session, workspace_id=ws.id, system_id=system_id
    )
    assert resolved["composite_min"] == 90.0


# ---------------------------------------------------------------------------
# Threshold arithmetic (pure function)
# ---------------------------------------------------------------------------


def test_check_thresholds_no_breach():
    outcome = auto_eval._check_thresholds(
        scores={"safety": 95, "hallucination": 80},
        composite_score=85.0,
        hallucination_rate=0.05,
        config={
            "composite_min": 60.0,
            "hallucination_max": 0.3,
            "dimension_min": {"safety": 80.0},
        },
    )
    assert outcome["breach"] is False
    assert outcome["reasons"] == []


def test_check_thresholds_composite_breach():
    outcome = auto_eval._check_thresholds(
        scores={},
        composite_score=45.0,
        hallucination_rate=0.0,
        config={"composite_min": 60.0, "hallucination_max": 1.0, "dimension_min": {}},
    )
    assert outcome["breach"] is True
    assert len(outcome["reasons"]) == 1
    assert outcome["reasons"][0]["metric"] == "composite_score"
    assert outcome["reasons"][0]["observed"] == 45.0


def test_check_thresholds_multiple_breaches():
    outcome = auto_eval._check_thresholds(
        scores={"safety": 40, "hallucination": 30},
        composite_score=40.0,
        hallucination_rate=0.6,
        config={
            "composite_min": 60.0,
            "hallucination_max": 0.3,
            "dimension_min": {"safety": 80.0, "hallucination": 50.0},
        },
    )
    assert outcome["breach"] is True
    # composite, hallucination_rate, dimension.safety, dimension.hallucination
    assert len(outcome["reasons"]) == 4
    metrics = {r["metric"] for r in outcome["reasons"]}
    assert "composite_score" in metrics
    assert "hallucination_rate" in metrics
    assert "dimension.safety" in metrics
    assert "dimension.hallucination" in metrics


# ---------------------------------------------------------------------------
# End-to-end service (async with stubbed judge)
# ---------------------------------------------------------------------------


def test_evaluate_run_disabled_is_noop(db_session, monkeypatch):
    run = _seed_minimal_run(db_session)
    # E1.5.4 auto-onboards by default, so the no-op path is now the
    # explicit workspace opt-out preset.
    service = get_evaluation_preset_service()
    service.upsert_workspace_preset(
        db_session,
        workspace_id=run.workspace_id,
        config={"enabled": False},
        name="Workspace opt-out",
    )
    result = asyncio.run(
        auto_eval.evaluate_run_async(run.id)
    )
    assert result is None

    row = (
        db_session.query(EvaluationScore)
        .filter(EvaluationScore.run_id == run.id)
        .first()
    )
    assert row is None
    refreshed = db_session.query(Run).filter(Run.id == run.id).first()
    assert refreshed.evaluation_scores is None


def test_evaluate_run_passes_through_judge_no_breach(db_session, monkeypatch):
    run = _seed_minimal_run(db_session)

    stub = _StubJudge(
        scores={d: 90 for d in ["safety", "hallucination", "relevance"]},
        composite_score=88.0,
        hallucination_rate=0.05,
    )
    monkeypatch.setattr(
        "app.services.evaluation.auto_eval.get_judge_service",
        lambda: stub,
    )

    override = dict(DEFAULT_EVAL_CONFIG)
    override["enabled"] = True

    asyncio.run(
        auto_eval.evaluate_run_async(run.id, preset_override=override)
    )

    # Auto-eval uses its own SessionLocal — force this test session to
    # re-read from disk instead of serving cached identity-map rows.
    db_session.expire_all()

    row = (
        db_session.query(EvaluationScore)
        .filter(EvaluationScore.run_id == run.id)
        .first()
    )
    assert row is not None
    assert row.composite_score == 88.0
    assert row.hallucination_rate == 0.05

    refreshed = db_session.query(Run).filter(Run.id == run.id).first()
    assert refreshed.evaluation_scores is not None
    assert refreshed.evaluation_scores["threshold_breach"] is False

    decisions = (
        db_session.query(Decision)
        .filter(Decision.target_id == run.id)
        .all()
    )
    assert decisions == []


def test_evaluate_run_files_review_decision_on_breach(db_session, monkeypatch):
    run = _seed_minimal_run(db_session)

    stub = _StubJudge(
        scores={"safety": 40, "hallucination": 30, "relevance": 40},
        composite_score=40.0,
        hallucination_rate=0.6,
    )
    monkeypatch.setattr(
        "app.services.evaluation.auto_eval.get_judge_service",
        lambda: stub,
    )

    async def _suggestion(**kwargs):
        return {
            "action_type": "rerun_with_overrides",
            "title": "Retry with grounding",
            "overrides": {"rag_pipeline_mode": "hybrid"},
            "source": "test",
        }

    monkeypatch.setattr(
        "app.services.evaluation.auto_eval.generate_active_suggestion",
        _suggestion,
    )

    override = dict(DEFAULT_EVAL_CONFIG)
    override["enabled"] = True

    asyncio.run(
        auto_eval.evaluate_run_async(run.id, preset_override=override)
    )
    db_session.expire_all()

    refreshed = db_session.query(Run).filter(Run.id == run.id).first()
    assert refreshed.evaluation_scores["threshold_breach"] is True
    assert len(refreshed.evaluation_scores["reasons"]) >= 1

    decision = (
        db_session.query(Decision)
        .filter(
            Decision.target_id == run.id,
            Decision.kind == "review_required",
        )
        .first()
    )
    assert decision is not None
    assert decision.scope == "run"
    assert decision.status == "proposed"
    assert decision.workspace_id == refreshed.workspace_id
    assert "reasons" in decision.rationale
    assert decision.rationale["composite_score"] == 40.0
    assert decision.rationale["active_suggestion"]["action_type"] == "rerun_with_overrides"


def test_evaluate_run_skips_non_completed(db_session, monkeypatch):
    run = _seed_minimal_run(db_session, status="failed")
    called = {"n": 0}

    class _ShouldNotBeCalled:
        async def evaluate(self, **kwargs):
            called["n"] += 1
            return {}

    monkeypatch.setattr(
        "app.services.evaluation.auto_eval.get_judge_service",
        lambda: _ShouldNotBeCalled(),
    )

    asyncio.run(
        auto_eval.evaluate_run_async(run.id, preset_override={"enabled": True})
    )
    assert called["n"] == 0


def test_evaluate_run_no_response_skips_gracefully(db_session, monkeypatch):
    run = _seed_minimal_run(db_session)
    run.output_ref = {}  # No extractable response
    db_session.commit()

    class _ShouldNotBeCalled:
        async def evaluate(self, **kwargs):
            raise RuntimeError("judge should not be called when response is missing")

    monkeypatch.setattr(
        "app.services.evaluation.auto_eval.get_judge_service",
        lambda: _ShouldNotBeCalled(),
    )

    # Should not raise — the skip is silent and intentional.
    asyncio.run(
        auto_eval.evaluate_run_async(run.id, preset_override={"enabled": True})
    )


def test_evaluate_run_swallows_judge_exception(db_session, monkeypatch):
    run = _seed_minimal_run(db_session)

    class _ExplodingJudge:
        async def evaluate(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.services.evaluation.auto_eval.get_judge_service",
        lambda: _ExplodingJudge(),
    )

    # Should return None, not raise
    result = asyncio.run(
        auto_eval.evaluate_run_async(run.id, preset_override={"enabled": True})
    )
    assert result is None

    refreshed = db_session.query(Run).filter(Run.id == run.id).first()
    # No scores written (we fail before persisting)
    assert refreshed.evaluation_scores is None
