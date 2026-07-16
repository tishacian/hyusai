from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import observability
from app.models.capability import Capability
from app.models.evaluation import EvaluationScore
from app.models.run import Run, SkillInvocation
from app.models.skill import Skill
from app.models.system import System
from app.models.workspace import Workspace
from app.models.workspace_job import WorkspaceJob
from app.services.chat_run_ledger import enrich_chat_run_ledger


def _client(db_session, workspace: Workspace) -> TestClient:
    app = FastAPI()
    app.include_router(observability.router, prefix="/api/v1/observability")
    app.dependency_overrides[observability.get_current_workspace] = lambda: workspace
    app.dependency_overrides[observability.get_db] = lambda: db_session
    return TestClient(app)


def _seed_chat_capability(db_session, workspace: Workspace) -> System:
    capability = Capability(
        id="cap-workspace-assistant",
        slug="workspace_assistant",
        name="Workspace Assistant",
        tier="universal",
        pricing={"unit": "per_outcome", "unit_price": 0.06, "currency": "USD"},
        value_per_outcome=1.50,
        roi_model={"type": "time_saved_plus_decision_quality"},
    )
    skills = [
        Skill(
            id="skill-search",
            slug="semantic_search_v1",
            name="Search",
            pricing={"unit": "per_call", "unit_price": 0.02, "currency": "USD"},
        ),
        Skill(
            id="skill-answer",
            slug="llm_rag_answer_v1",
            name="Answer",
            pricing={"unit": "per_call", "unit_price": 0.04, "currency": "USD"},
        ),
        Skill(
            id="skill-audit",
            slug="audit_log_v1",
            name="Audit",
            pricing={"unit": "per_call", "unit_price": 0.001, "currency": "USD"},
        ),
    ]
    system = System(
        id="system-chat",
        workspace_id=workspace.id,
        name="Agentium Workspace Chat",
        objective="Chat",
        capability_id=capability.id,
        status="active",
        settings={"system_type": "workspace_chat", "surface": "chat"},
    )
    db_session.add_all([capability, *skills, system])
    db_session.commit()
    return system


def test_chat_run_ledger_enriches_capability_outcome_and_invocations(db_session):
    workspace = Workspace(id="ws-obs", slug="andritz", name="Andritz")
    db_session.add(workspace)
    db_session.commit()
    system = _seed_chat_capability(db_session, workspace)
    run = Run(
        id="run-chat",
        workspace_id=workspace.id,
        system_id=system.id,
        status="completed",
        trigger="chat",
        input_ref={"query": "AKK200"},
        output_ref={"response": "Answer", "sources": [{"id": "1"}]},
        started_at=datetime.utcnow() - timedelta(seconds=2),
        completed_at=datetime.utcnow(),
        duration_ms=2000,
    )
    db_session.add(run)
    db_session.flush()

    result = enrich_chat_run_ledger(
        db_session,
        run,
        sources=run.output_ref["sources"],
        reasoning_trace=None,
        extra_output=run.output_ref,
    )
    db_session.commit()

    assert result["capability_slug"] == "workspace_assistant"
    assert run.capability_id == "cap-workspace-assistant"
    assert run.decision == "approved"
    assert run.value_source == "auto"
    assert run.value_estimated and run.value_estimated > 0
    assert run.cost_internal and run.cost_internal > 0
    assert db_session.query(SkillInvocation).filter(SkillInvocation.run_id == run.id).count() >= 2


def test_workspace_overview_aggregates_workspace_runs_jobs_and_alerts(db_session):
    workspace = Workspace(id="ws-obs", slug="andritz", name="Andritz")
    other = Workspace(id="ws-other", slug="other", name="Other")
    db_session.add_all([workspace, other])
    db_session.commit()
    system = _seed_chat_capability(db_session, workspace)
    now = datetime.utcnow()
    db_session.add_all(
        [
            Run(
                id="run-ok",
                workspace_id=workspace.id,
                system_id=system.id,
                status="completed",
                trigger="chat",
                input_ref={"query": "AKK200"},
                output_ref={
                    "response": "Answer",
                    "sources": [],
                    "retrieval_decision_trace": {
                        "version": 1,
                        "selected_route": "chah_backend",
                        "query_type": "exact_reference",
                        "quality_controls": {
                            "sparse_status": "applied",
                            "cross_encoder_status": "applied",
                        },
                        "deep_search": {"recommended": True, "launched": False},
                    },
                },
                started_at=now - timedelta(minutes=5),
                completed_at=now - timedelta(minutes=4),
                duration_ms=1200,
                capability_id="cap-workspace-assistant",
            ),
            Run(
                id="run-other",
                workspace_id=other.id,
                status="failed",
                started_at=now - timedelta(minutes=2),
            ),
            WorkspaceJob(
                id="job-sftp",
                workspace_id=workspace.id,
                kind="sftp_reconciliation",
                title="SFTP check",
                status="failed",
                progress=10,
                stage="scan",
                error="disk warning",
                updated_at=now - timedelta(minutes=1),
                created_at=now - timedelta(minutes=2),
            ),
            EvaluationScore(
                id="eval-low",
                workspace_id=workspace.id,
                run_id="run-ok",
                agent_id=system.id,
                composite_score=42.0,
                hallucination_rate=0.4,
                created_at=now - timedelta(minutes=3),
            ),
        ]
    )
    db_session.commit()

    response = _client(db_session, workspace).get(
        "/api/v1/observability/workspace-overview?window=24h"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["runs_total"] == 1
    assert body["summary"]["jobs_failed"] == 1
    assert body["evaluations"]["breaches"] == 1
    assert body["summary"]["retrieval_traces_total"] == 1
    assert body["summary"]["deep_recommended"] == 1
    assert body["retrieval_decisions"]["routes"][0]["route"] == "chah_backend"
    assert any(item["kind"] == "run_without_sources" for item in body["alerts"])
    assert "run-other" not in str(body)


def test_agentic_chat_runs_share_chat_retrieval_observability_contract():
    run = Run(
        id="run-chat-agentic",
        workspace_id="ws-obs",
        status="completed",
        trigger="chat_agentic",
        output_ref={"response": "No grounded result", "sources": []},
    )

    assert observability._run_expects_retrieval_trace(run) is True
    assert observability._is_unsourced_chat_run(run) is True

    run.output_ref = {
        "response": "Grounded result",
        "sources": [{"id": "source-1"}],
        "retrieval_decision_trace": {"selected_route": "agentic_dag"},
    }
    assert observability._run_retrieval_decision_trace(run) == {"selected_route": "agentic_dag"}
    assert observability._is_unsourced_chat_run(run) is False


@pytest.mark.parametrize(
    "output",
    [
        {
            "action": "clarify",
            "clarifying_question": "Quel équipement ?",
            "answer": "Quel équipement ?",
            "sources": [],
        },
        {
            "action": "reject_oos",
            "reason": "Cette demande est hors du périmètre Andritz.",
            "answer": "Cette demande est hors du périmètre Andritz.",
            "sources": [],
        },
        {"oos_reason": "Hors périmètre", "sources": []},
        {"route": "agentic_review", "answer": "Validation requise", "sources": []},
        {
            "route": "agentic_review_rejected",
            "fallback_reason": "hitl_rejected",
            "answer": "La réponse a été rejetée lors de la validation experte.",
            "sources": [],
        },
        {"route": "agentic_blocked", "answer": "Réponse bloquée", "sources": []},
        {
            "meta": {"route": "agentic_review"},
            "answer": "Validation requise",
            "sources": [],
        },
    ],
)
def test_agentic_governed_or_clarifying_terminals_are_not_unsourced_alerts(output):
    run = Run(
        id="run-chat-agentic-abstention",
        workspace_id="ws-obs",
        status="completed",
        trigger="chat_agentic",
        output_ref=output,
    )

    assert observability._is_unsourced_chat_run(run) is False


def test_agentic_real_answer_with_no_sources_still_alerts_even_with_other_reason():
    run = Run(
        id="run-chat-agentic-uncited",
        workspace_id="ws-obs",
        status="completed",
        trigger="chat_agentic",
        output_ref={
            "answer": "La pompe principale est P-101.",
            "reason": "generated_answer",
            "sources": [],
        },
    )

    assert observability._is_unsourced_chat_run(run) is True
