"""Regression checks for unavailable scores, durable commands and evidence ACL."""
import asyncio
import json
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import evaluation
from app.models.evaluation import EvaluationScore
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.services.evaluation import auto_eval, lifecycle
from app.services.evaluation.judge import JudgeService, DIMENSIONS
from app.tests.services.test_auto_eval import _seed_minimal_run


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"scores": {"relevance": 90}, "claims": []}, {"scores": {d: 90 for d in DIMENSIONS}, "claims": []}, {"scores": {"relevance": float("nan")}, "claims": None}])
async def test_missing_coverage_never_becomes_success(monkeypatch, payload):
    async def complete(self, prompt):
        return json.dumps(payload), {}
    monkeypatch.setattr(JudgeService, "_complete_with_usage", complete)
    result = await JudgeService().evaluate("pressure?", "6 bar", context_chunks=["6 bar"])
    assert result["hallucination_rate"] is None
    assert result["status"] in {"partial", "failed"}
    assert "drift" not in result["scores"] or result["drift_rate"] == 0.1


def test_sampling_is_persisted_and_not_recomputed(db_session, monkeypatch):
    run = _seed_minimal_run(db_session)
    monkeypatch.setattr(auto_eval.random, "random", lambda: 0.5)
    result = asyncio.run(auto_eval.evaluate_run_async(run.id, preset_override={"enabled": True, "sample_rate": 0}))
    db_session.refresh(run)
    assert result["reason"] == "sampling_excluded"
    assert run.evaluation_scores["status"] == "skipped"


def test_failed_scores_persist_null_not_orm_defaults(db_session, monkeypatch):
    run = _seed_minimal_run(db_session)
    class Judge:
        async def evaluate(self, **kwargs):
            return {"id": str(uuid4()), "status": "failed", "scores": {}, "composite_score": None, "hallucination_rate": None, "drift_rate": None}
    monkeypatch.setattr(auto_eval, "get_judge_service", lambda: Judge())
    result = asyncio.run(auto_eval.evaluate_run_async(run.id, preset_override={"enabled": True}))
    row = db_session.query(EvaluationScore).filter(EvaluationScore.run_id == run.id).one()
    assert result["status"] == "failed"
    assert row.composite_score is None and row.hallucination_rate is None and row.drift_rate is None


def test_enqueue_deduplicates_committed_command(db_session, monkeypatch):
    run = _seed_minimal_run(db_session)
    dispatched = []
    monkeypatch.setattr(lifecycle, "dispatch_workspace_job", lambda db, ws, job, **kw: dispatched.append(job.id) or "task")
    first = lifecycle.enqueue_run_evaluation(db_session, run, user=None, idempotency_key="same")
    second = lifecycle.enqueue_run_evaluation(db_session, run, user=None, idempotency_key="same")
    assert first.id == second.id and dispatched == [first.id]
    assert db_session.query(WorkspaceJob).filter(WorkspaceJob.run_id == run.id).count() == 1


def test_deleted_or_foreign_source_is_not_returned(db_session):
    run = _seed_minimal_run(db_session)
    workspace = db_session.get(Workspace, run.workspace_id)
    user = User(id=str(uuid4()), username=str(uuid4()), role="admin")
    db_session.add(user)
    db_session.commit()
    public = lifecycle.public_evaluation_snapshot(db_session, {"metadata": {"context_examined": "SECRET", "excerpts": [{"id": "1", "text": "SECRET", "source_id": "deleted"}]}}, workspace=workspace, user=user, run=run)
    assert "SECRET" not in json.dumps(public)
    assert public["metadata"]["excerpts"][0]["availability"] == "source_unavailable"


@pytest.mark.asyncio
async def test_private_run_not_exposed_by_any_evaluation_feed(db_session):
    run = _seed_minimal_run(db_session)
    workspace = db_session.get(Workspace, run.workspace_id)
    user = User(id=str(uuid4()), username=str(uuid4()), role="user")
    db_session.add(user)
    db_session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member", role_template="workspace_contributor"))
    run.trigger = "chat_agentic"
    run.initiated_by_user_id = str(uuid4())
    db_session.add(EvaluationScore(id=str(uuid4()), workspace_id=workspace.id, run_id=run.id, scores={"relevance": 99}, composite_score=99))
    db_session.commit()
    with pytest.raises(HTTPException):
        await evaluation.evaluation_by_run(run.id, workspace=workspace, user=user, db=db_session)
    history = await evaluation.evaluation_history(agent_id=None, limit=20, since=None, workspace=workspace, user=user, db=db_session)
    assert history["evaluations"] == []
    latest = await evaluation.latest_evaluation(agent_id=None, workspace=workspace, user=user, db=db_session)
    assert latest["evaluation"] is None
    trend = await evaluation.eval_trend(since="7d", group_by="day", workspace=workspace, user=user, db=db_session)
    assert trend["totals"]["runs_evaluated"] == 0


@pytest.mark.asyncio
async def test_sse_reads_worker_checkpoint_without_local_bus_event(db_session):
    from app.api.v1.endpoints.runs import _run_event_stream
    run = _seed_minimal_run(db_session, status="running")
    class Request:
        async def is_disconnected(self):
            return False
    stream = _run_event_stream(run.id, Request(), run.workspace_id)
    first = await anext(stream)
    assert 'event: snapshot' in first
    run.checkpoints = [{"kind": "node_end", "t": "new", "node_id": "summary"}]
    run.status = "completed"
    db_session.commit()
    frames = [frame async for frame in stream]
    assert sum('event: node_end' in frame for frame in frames) == 1
    assert any('polled_terminal' in frame for frame in frames)


def test_completed_job_redelivery_does_not_call_judge(db_session, monkeypatch):
    run = _seed_minimal_run(db_session)
    monkeypatch.setattr(lifecycle, "dispatch_workspace_job", lambda *args, **kwargs: "task")
    job = lifecycle.enqueue_run_evaluation(db_session, run, user=None, idempotency_key="once")
    run.evaluation_scores = {"status": "partial", "job_id": job.id, "evaluation_id": "persisted"}
    db_session.commit()
    async def forbidden(*args, **kwargs):
        raise AssertionError("redelivery must reuse persisted result")
    monkeypatch.setattr(auto_eval, "evaluate_run_async", forbidden)
    result = lifecycle.run_evaluation_job(job.id)
    db_session.refresh(job)
    assert result["evaluation_id"] == "persisted"
    assert job.status == "completed"
    assert job.result == {"status": "partial", "evaluation_id": "persisted"}


@pytest.mark.asyncio
async def test_quality_surfaces_share_system_and_time_scope_before_limits(db_session):
    from datetime import datetime, timedelta
    from app.models.run import Run
    from app.models.system import System
    run = _seed_minimal_run(db_session)
    workspace = db_session.get(Workspace, run.workspace_id)
    user = User(id=str(uuid4()), username=str(uuid4()), role="admin")
    other_system = System(id=str(uuid4()), name="Other", workspace_id=workspace.id, capability_id=run.capability_id)
    db_session.add_all([user, other_system])
    db_session.flush()
    other_run = Run(id=str(uuid4()), workspace_id=workspace.id, system_id=other_system.id, status="completed")
    db_session.add(other_run)
    db_session.flush()
    for target, age, status in [(run, 1, "partial"), (run, 2, "completed"), (run, 20, "completed"), (other_run, 0, "failed")]:
        db_session.add(EvaluationScore(id=str(uuid4()), workspace_id=workspace.id, run_id=target.id,
            agent_id="legacy-name-is-not-a-system-id", created_at=datetime.utcnow()-timedelta(days=age),
            composite_score=80, hallucination_rate=0.1, metadata_={"status": status}))
    db_session.commit()
    kwargs = dict(workspace=workspace, user=user, db=db_session, system_id=run.system_id, since="7d")
    history = await evaluation.evaluation_history(limit=1, **kwargs)
    latest = await evaluation.latest_evaluation(**kwargs)
    trend = await evaluation.eval_trend(group_by="day", **kwargs)
    components = await evaluation.eval_component_health(**kwargs)
    for result in (history, latest, trend, components):
        assert result["total"] == 2
        assert result["state_counts"] == {"partial": 1, "completed": 1}
        assert result["scope"] == {"system_id": run.system_id, "since": "7d"}
    assert len(history["evaluations"]) == 1
    assert history["evaluations"][0]["system_id"] == run.system_id
    assert latest["evaluation"]["run_id"] == run.id
    assert trend["totals"]["runs_evaluated"] == components["totals"]["evaluations"] == 2
    longer = await evaluation.evaluation_history(limit=20, **{**kwargs, "since": "30d"})
    assert longer["total"] == 3
    absent = await evaluation.eval_trend(group_by="day", **{**kwargs, "system_id": str(uuid4())})
    assert absent["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("since", ["invalid", "0d", "366d", "999999999999999999999999999d"])
async def test_quality_scope_rejects_unbounded_or_invalid_period(db_session, since):
    run = _seed_minimal_run(db_session)
    workspace = db_session.get(Workspace, run.workspace_id)
    for endpoint in (evaluation.evaluation_history, evaluation.latest_evaluation, evaluation.eval_trend, evaluation.eval_component_health):
        with pytest.raises(HTTPException) as error:
            await endpoint(workspace=workspace, user=None, db=db_session, since=since)
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_review_queue_scope_and_count_are_applied_before_page_limit(db_session):
    from datetime import datetime, timedelta
    from app.models.decision import Decision
    from app.models.run import Run
    from app.models.system import System
    run = _seed_minimal_run(db_session)
    workspace = db_session.get(Workspace, run.workspace_id)
    admin = User(id=str(uuid4()), username=str(uuid4()), role="admin")
    other_system = System(id=str(uuid4()), name="Other", workspace_id=workspace.id, capability_id=run.capability_id)
    db_session.add_all([admin, other_system]); db_session.flush()
    other_run = Run(id=str(uuid4()), workspace_id=workspace.id, system_id=other_system.id, status="completed")
    db_session.add(other_run); db_session.flush()
    for target, days in [(run,1),(run,2),(run,20),(other_run,0)]:
        db_session.add(Decision(id=str(uuid4()), workspace_id=workspace.id, scope="run", target_id=target.id,
            kind="review_required", status="proposed", title="Review", rationale={}, created_at=datetime.utcnow()-timedelta(days=days)))
    db_session.commit()
    result = await evaluation.review_queue(status="proposed", component=None, limit=1, workspace=workspace,
        user=admin, db=db_session, system_id=run.system_id, since="7d")
    assert result["count"] == 2 and len(result["items"]) == 1
    assert result["items"][0]["run"]["system_id"] == run.system_id
    with pytest.raises(HTTPException) as error:
        await evaluation.review_queue(status="proposed", component=None, limit=1, workspace=workspace,
            user=admin, db=db_session, system_id=run.system_id, since="366d")
    assert error.value.status_code == 422


def test_chat_evaluation_reads_full_recorded_context_with_provenance():
    from types import SimpleNamespace
    run = SimpleNamespace(input_ref={"query": "pressure?"}, output_ref={
        "sources": [{"snippet": "Short preview"}],
        "rag_context": {"chunks": ["700 bar continuous; relief valve opens at 735 bar."],
            "metadatas": [{"document_id": "doc", "collection": "notices",
                "document_filename": "manual.md", "chunk_id": "doc-0"}]}})
    evidence = auto_eval._context_evidence(run, [])
    assert evidence == [{"text": "700 bar continuous; relief valve opens at 735 bar.",
        "invocation_id": None, "document_id": "doc", "collection": "notices",
        "filename": "manual.md", "chunk_id": "doc-0"}]


def test_unaligned_historic_context_does_not_invent_document_association():
    from types import SimpleNamespace
    run = SimpleNamespace(input_ref={}, output_ref={"rag_context": {
        "chunks": ["first", "second"], "metadatas": [{"document_id": "unknown-match"}]}})
    evidence = auto_eval._context_evidence(run, [])
    assert [row["text"] for row in evidence] == ["first", "second"]
    assert all("document_id" not in row for row in evidence)
