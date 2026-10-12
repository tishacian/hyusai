import asyncio
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from alembic.config import Config
from alembic.script import ScriptDirectory
from pathlib import Path

from app.api.v1.endpoints import evaluation as api
from app.models.retrieval_bench_run import RetrievalBenchRun
from app.models.workspace import Workspace
from app.services.rag import public_bench
from app.workers.celery_app import celery_app


def test_frozen_subset_is_complete_and_self_consistent():
    cases = public_bench.load_public_bench_cases()
    documents = public_bench.paragraph_documents()
    assert len(cases) == 200
    assert len(documents) == 1991
    assert all(re.fullmatch(r"[a-z0-9._-]+\.md", name) for name in documents)
    for case in cases:
        assert case.supporting_files and set(case.supporting_files) <= set(documents)
        assert case.supporting_sentences
    assert (public_bench.PUBLIC_BENCH_PATH.parent / "ATTRIBUTION.md").read_text().count("CC BY-SA 4.0")


def test_score_case_measures_recall_and_supporting_sentences():
    case = public_bench.load_public_bench_cases()[0]
    documents = public_bench.paragraph_documents()
    first = case.supporting_files[0]
    context = {
        "chunks": [documents[first], "unrelated text"],
        "metadatas": [{"document_filename": first}, {"document_filename": "other.md"}],
    }
    score = public_bench.score_case(case, context, k=10)
    assert score["recall"] == 1 / len(case.supporting_files)
    assert 0 < score["supporting_fact_rate"] < 1
    assert public_bench.score_case(case, context, k=0)["recall"] == 0


def test_summarise_excludes_errors_and_groups_by_type():
    summary = public_bench.summarise(
        [
            {"type": "bridge", "recall": 1.0, "supporting_fact_rate": 0.5, "latency_ms": 10.0},
            {"type": "comparison", "recall": 0.5, "supporting_fact_rate": 0.0, "latency_ms": 30.0},
            {"type": "bridge", "error": "boom"},
        ]
    )
    assert summary["recall_at_k"] == 0.75
    assert summary["mean_latency_ms"] == 20.0
    assert summary["error_count"] == 1
    assert summary["by_type"]["bridge"]["cases"] == 1


def test_run_is_skipped_until_the_workspace_is_seeded(db_session):
    db_session.query(Workspace).filter_by(slug=public_bench.PUBLIC_BENCH_WORKSPACE_SLUG).delete()
    db_session.commit()
    run = asyncio.run(public_bench.run_public_bench(db_session, limit=1))
    assert run.status == "skipped"
    assert run.error == "workspace_not_seeded"


def test_run_scores_cases_and_persists_metrics(db_session, monkeypatch):
    public_bench.public_bench_workspace(db_session, create=True)
    db_session.commit()
    documents = public_bench.paragraph_documents()

    async def fake_retrieve(request):
        assert request["context_collection"] == public_bench.PUBLIC_BENCH_COLLECTION_SLUG
        case = next(c for c in public_bench.load_public_bench_cases() if c.question == request["query"])
        return {
            "chunks": [documents[f] for f in case.supporting_files],
            "metadatas": [{"document_filename": f} for f in case.supporting_files],
        }

    monkeypatch.setattr("app.services.rag.context.retrieve_rag_context", fake_retrieve)
    run = asyncio.run(public_bench.run_public_bench(db_session, limit=3))
    assert run.status == "completed"
    assert run.case_count == 3
    assert run.recall_at_k == 1.0
    assert run.supporting_fact_rate == 1.0


def test_public_bench_api_lists_runs_newest_first(db_session):
    db_session.query(RetrievalBenchRun).delete()
    for recall in (0.4, 0.6):
        db_session.add(
            RetrievalBenchRun(bench=public_bench.PUBLIC_BENCH_NAME, status="completed", k=10, recall_at_k=recall, metrics={})
        )
        db_session.commit()
    app = FastAPI()
    app.include_router(api.router, prefix="/evaluation")
    app.dependency_overrides[api.get_db] = lambda: db_session
    app.dependency_overrides[api.get_current_user] = lambda: object()
    body = TestClient(app).get("/evaluation/public-bench/runs").json()
    assert body["bench"] == public_bench.PUBLIC_BENCH_NAME
    assert len(body["runs"]) == 2


def test_nightly_task_is_scheduled_by_beat():
    import app.workers.tasks  # noqa: F401

    entry = celery_app.conf.beat_schedule["public-retrieval-bench-24h"]
    assert entry["task"] == "agentium.public_retrieval_bench"
    assert entry["schedule"] == 24 * 60 * 60
    assert "agentium.public_retrieval_bench" in celery_app.tasks


def test_migration_125_extends_the_single_head():
    root = Path(__file__).resolve().parents[3]
    script = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))
    assert script.get_heads() == ["125_retrieval_bench_runs"]
    assert len("125_retrieval_bench_runs") <= 32
