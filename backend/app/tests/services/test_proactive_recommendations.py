from datetime import datetime
from uuid import uuid4

from app.models.decision import Decision
from app.models.evaluation import EvaluationScore
from app.models.run import Run
from app.models.system import System
from app.models.workspace import Workspace
from app.services.recommendations.proactive_service import (
    generate_proactive_recommendations,
)


def _seed_workspace_system(db_session):
    ws = Workspace(id=str(uuid4()), slug=f"e5-{uuid4().hex[:6]}", name="E5")
    system = System(id=str(uuid4()), workspace_id=ws.id, name="E5 System")
    db_session.add_all([ws, system])
    db_session.commit()
    return ws, system


def _seed_eval(db_session, ws, system, *, failed_components, composite=42.0):
    run = Run(
        id=str(uuid4()),
        workspace_id=ws.id,
        system_id=system.id,
        status="completed",
        trigger="chat",
        input_ref={"query": "Ignore this unrelated text, what is the SLA?"},
        output_ref={"response": "bad"},
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    score = EvaluationScore(
        id=str(uuid4()),
        workspace_id=ws.id,
        run_id=run.id,
        session_id=run.id,
        agent_id=system.id,
        query=run.input_ref["query"],
        scores={"hallucination": 30, "relevance": 40},
        composite_score=composite,
        hallucination_rate=0.5,
        question_type="distracting",
        failed_components=failed_components,
        created_at=datetime.utcnow(),
    )
    db_session.add_all([run, score])
    db_session.commit()
    return run, score


def test_generate_proactive_recommendation_from_component_breaches(db_session):
    ws, system = _seed_workspace_system(db_session)
    for _ in range(3):
        _seed_eval(db_session, ws, system, failed_components=["retriever", "generator"])

    result = generate_proactive_recommendations(
        db_session,
        workspace_id=ws.id,
        min_evaluations=3,
        min_breaches=2,
        min_breach_rate=0.5,
        actor="test",
    )

    assert result["evaluations_scanned"] == 3
    assert result["created"]
    decision = db_session.query(Decision).filter(Decision.id == result["created"][0]["id"]).first()
    assert decision is not None
    assert decision.kind == "recommendation"
    assert decision.status == "proposed"
    assert decision.scope == "system"
    assert decision.target_id == system.id
    assert decision.rationale["source"] == "proactive_eval"
    assert decision.rationale["component"] in {"retriever", "generator"}
    assert decision.rationale["breaches"] == 3


def test_generate_proactive_recommendation_is_idempotent(db_session):
    ws, system = _seed_workspace_system(db_session)
    for _ in range(3):
        _seed_eval(db_session, ws, system, failed_components=["retriever"])

    first = generate_proactive_recommendations(db_session, workspace_id=ws.id)
    second = generate_proactive_recommendations(db_session, workspace_id=ws.id)

    assert len(first["created"]) == 1
    assert second["created"] == []
    assert second["skipped"]
    assert db_session.query(Decision).filter(Decision.kind == "recommendation").count() == 1


def test_generate_proactive_recommendation_dry_run_does_not_persist(db_session):
    ws, system = _seed_workspace_system(db_session)
    for _ in range(3):
        _seed_eval(db_session, ws, system, failed_components=["knowledge_base"])

    result = generate_proactive_recommendations(
        db_session,
        workspace_id=ws.id,
        dry_run=True,
    )

    assert result["preview"]
    assert result["created"] == []
    assert db_session.query(Decision).filter(Decision.kind == "recommendation").count() == 0
