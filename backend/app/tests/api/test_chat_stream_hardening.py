from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import chat
from app.core.config import settings
from app.models.context import Context
from app.models.knowledge_collection import WorkerJob
from app.models.run import Run, SkillInvocation
from app.models.workspace_job import WorkspaceJob
from app.models.workspace import Workspace
from app.services.knowledge_collections import create_collection
from app.services.workspace_maps import ensure_workspace_map_seed


def _client(db_session, workspace: Workspace, orchestrator, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(chat.router, prefix="/chat")
    app.dependency_overrides[chat.get_current_workspace] = lambda: workspace
    app.dependency_overrides[chat.get_current_user] = lambda: None
    app.dependency_overrides[chat.get_db] = lambda: db_session
    monkeypatch.setattr(chat, "get_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(chat, "schedule_eval", lambda _run_id: None)
    return TestClient(app)


class HappyOrchestrator:
    async def process_request(self, _request):
        yield {
            "chunk_type": "retrieval",
            "phase": "started",
            "content": "",
            "details": {
                "duration_ms": 0,
                "chunks_retrieved": 0,
                "collection": "documents",
                "vector_db": "faiss",
                "pipeline": "hybrid",
                "task_id": None,
            },
            "is_final": False,
        }
        yield {
            "chunk_type": "retrieval",
            "phase": "completed",
            "content": "",
            "details": {
                "duration_ms": 12,
                "chunks_retrieved": 1,
                "collection": "documents",
                "vector_db": "faiss",
                "pipeline": "hybrid",
                "task_id": "task-1",
                "fallback": False,
                "retrieval_plan": {
                    "profile": "fast",
                    "layers": {
                        "dense_qdrant": {"enabled": True},
                        "rerank": {"enabled": True},
                    },
                    "guardrails": {"user_scope_required": False},
                },
            },
            "rag_context": {
                "chunks": ["context"],
                "scores": [0.9],
                "metadatas": [{"document_title": "Manual"}],
                "metrics": {"duration_ms": 12, "chunks_retrieved": 1},
            },
            "is_final": False,
        }
        yield {
            "chunk_type": "text",
            "content": "answer",
            "sources": [{"title": "Manual"}],
            "is_final": False,
        }
        yield {
            "chunk_type": "retrieval",
            "phase": "observability",
            "content": "",
            "details": {
                "duration_ms": 12,
                "chunks_retrieved": 1,
                "collection": "documents",
                "vector_db": "faiss",
                "pipeline": "hybrid",
                "task_id": "task-1",
                "fallback": False,
                "stage_timings": {
                    "retrieval_ms": 12,
                    "llm_ms": 34,
                    "total_ms": 46,
                },
                "llm_ms": 34,
                "latency_budget": {"profile": "fast", "retrieval_profile": "chat", "candidate_pool_k": 20},
                "cross_encoder_status": "skipped_fast",
                "cross_encoder_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                "cross_encoder_scored": 0,
                "cross_encoder_filtered": 0,
                "sparse_status": "ok",
                "sparse_backend": "qdrant_sparse",
                "retrieval_plan": {
                    "profile": "fast",
                    "layers": {
                        "dense_qdrant": {"enabled": True},
                        "rerank": {"enabled": True},
                    },
                    "guardrails": {"user_scope_required": False},
                },
            },
            "is_final": False,
        }
        yield {"chunk_type": "text", "content": "", "is_final": True}


class SlowOrchestrator:
    async def process_request(self, _request):
        await asyncio.sleep(0.05)
        yield {"chunk_type": "text", "content": "too late", "is_final": True}


class CapturingOrchestrator:
    def __init__(self):
        self.last_request = None

    async def process_request(self, request):
        self.last_request = request
        yield {"chunk_type": "text", "content": "context answer", "is_final": False}
        yield {"chunk_type": "text", "content": "", "is_final": True}


class DeepRecommendedOrchestrator:
    async def process_request(self, _request):
        yield {
            "chunk_type": "retrieval",
            "phase": "completed",
            "content": "",
            "details": {
                "duration_ms": 8000,
                "chunks_retrieved": 0,
                "collection": "documents",
                "pipeline": "retrieval_timeout",
                "fallback": True,
                "fallback_reason": "retrieval_deadline_exceeded",
                "deep_retrieval_recommended": True,
                "dense_policy": "fast_scoped_dense_auto",
                "scope_confidence": 0.2,
                "scope_reason": "Dense corpus fast policy selected an internal scope.",
                "latency_budget": {"profile": "fast", "deadline_seconds": 8, "candidate_pool_k": 20},
                "retrieval_scope": {
                    "collections": ["documents"],
                    "filters": {
                        "collection_slug": "documents",
                        "project_code": "ACJ100",
                        "document_id": ["doc-1", "doc-2"],
                    },
                    "intent": "procedure",
                    "dense": True,
                    "confidence": 0.2,
                    "reason": "Dense corpus fast policy selected an internal scope.",
                },
            },
            "rag_context": {
                "chunks": [],
                "scores": [],
                "metadatas": [],
                "metrics": {
                    "chunks_retrieved": 0,
                    "no_context": True,
                    "fallback": True,
                    "fallback_reason": "retrieval_deadline_exceeded",
                    "deep_retrieval_recommended": True,
                },
            },
            "is_final": False,
        }
        yield {"chunk_type": "text", "content": "fast answer", "is_final": False}
        yield {"chunk_type": "text", "content": "", "is_final": True}


class ExplodingOrchestrator:
    async def process_request(self, _request):
        raise AssertionError("trivial bypass should not call orchestrator")


def test_chat_completion_trivial_bypasses_orchestrator(db_session, monkeypatch):
    workspace = Workspace(id="ws-trivial-completion", name="Trivial", slug="trivial")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, ExplodingOrchestrator(), monkeypatch).post(
        "/chat/completion",
        json={"query": "merci"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == "Avec plaisir."
    assert payload["sources"] == []
    assert payload["trivial_bypass"] is True
    assert payload["retrieval_metrics"]["bypassed"] is True
    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "trivial_bypass"
    assert run.output_ref["sources"] == []
    assert run.output_ref["trivial_bypass"] is True


def test_chat_stream_trivial_bypasses_retrieval(db_session, monkeypatch):
    workspace = Workspace(id="ws-trivial-stream", name="Trivial Stream", slug="trivial-stream")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, ExplodingOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={"query": "salut"},
    )

    assert response.status_code == 200
    body = response.text
    assert '"phase": "bypassed"' in body
    assert '"trivial_bypass": true' in body
    assert "Bonjour, je vous ecoute." in body
    assert '"phase": "started"' not in body
    assert '"chunk_type": "eval_pending"' not in body
    assert "data: [DONE]" in body
    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "trivial_bypass"
    assert run.output_ref["retrieval_metrics"]["bypassed"] is True


def test_chat_stream_domain_greeting_does_not_bypass(db_session, monkeypatch):
    workspace = Workspace(id="ws-domain-greeting", name="Domain Greeting", slug="domain-greeting")
    db_session.add(workspace)
    db_session.commit()
    orchestrator = CapturingOrchestrator()

    response = _client(db_session, workspace, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={"query": "Bonjour, retrouve la SPL AKK200"},
    )

    assert response.status_code == 200
    assert "context answer" in response.text
    assert orchestrator.last_request["query"] == "Bonjour, retrouve la SPL AKK200"


def test_chat_stream_emits_stable_retrieval_eval_and_persists_run(db_session, monkeypatch):
    workspace = Workspace(id="ws-chat", name="Chat", slug="chat")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={"query": "What is in the manual?"},
    )

    assert response.status_code == 200
    body = response.text
    assert '"chunk_type": "retrieval"' in body
    assert '"phase": "started"' in body
    assert '"phase": "completed"' in body
    assert '"phase": "observability"' in body
    assert '"chunk_type": "eval_pending"' in body
    assert "data: [DONE]" in body

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.output_ref["response"] == "answer"
    assert run.output_ref["retrieval_worker_task_id"] == "task-1"
    assert run.output_ref["retrieval_metrics"]["chunks_retrieved"] == 1
    assert run.output_ref["retrieval_metrics"]["llm_ms"] == 34
    assert run.output_ref["retrieval_metrics"]["stage_timings"]["llm_ms"] == 34
    assert run.output_ref["cross_encoder_status"] == "skipped_fast"
    assert run.output_ref["cross_encoder_model"] == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert run.output_ref["sparse_status"] == "ok"
    assert run.output_ref["sparse_backend"] == "qdrant_sparse"
    assert run.output_ref["retrieval_latency_profile"] == "fast"
    assert run.output_ref["retrieval_latency_scope"] == "direct_chat"
    assert run.output_ref["stage_timings"]["total_ms"] == 46
    assert run.output_ref["retrieval_plan"]["guardrails"]["user_scope_required"] is False
    assert run.output_ref["rag_context"]["chunks"] == ["context"]
    retrieval_invocation = (
        db_session.query(SkillInvocation)
        .filter(SkillInvocation.run_id == run.id, SkillInvocation.skill_slug == "semantic_search_v1")
        .one()
    )
    assert retrieval_invocation.metrics["cross_encoder_status"] == "skipped_fast"
    assert retrieval_invocation.metrics["retrieval_latency_profile"] == "fast"


def test_chat_stream_uses_selected_context_collection(db_session, monkeypatch):
    workspace = Workspace(id="ws-context-chat", name="Context Chat", slug="context-chat")
    db_session.add(workspace)
    db_session.add(
        Context(
            id="ctx-context-chat",
            workspace_id=workspace.id,
            name="NON-WOVENS France Excel pilot",
            environment_state={"collection": "andritz-non-wovens-france-excel-pilot"},
            data_refs=["andritz-non-wovens-france-excel-pilot"],
        )
    )
    db_session.commit()
    orchestrator = CapturingOrchestrator()

    response = _client(db_session, workspace, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={"query": "Diametre B ?", "context_id": "ctx-context-chat"},
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    assert orchestrator.last_request["context_collection"] == "andritz-non-wovens-france-excel-pilot"
    assert orchestrator.last_request["context"]["context_id"] == "ctx-context-chat"
    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.output_ref["context_id"] == "ctx-context-chat"


def test_chat_stream_clamps_untrusted_fast_retrieval_budget(db_session, monkeypatch):
    workspace = Workspace(id="ws-budget-chat", name="Budget Chat", slug="budget-chat")
    db_session.add(workspace)
    db_session.commit()
    orchestrator = CapturingOrchestrator()

    response = _client(db_session, workspace, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Analyse globale SPL",
            "top_k": 999,
            "candidate_pool_k": 999,
            "synthesis_k": 999,
            "source_display_k": 999,
        },
    )

    assert response.status_code == 200
    assert orchestrator.last_request["latency_profile"] == "fast"
    assert orchestrator.last_request["top_k"] == 8
    assert orchestrator.last_request["candidate_pool_k"] == 20
    assert orchestrator.last_request["synthesis_k"] == 12
    assert orchestrator.last_request["source_display_k"] == 8
    assert orchestrator.last_request["latency_budget"]["candidate_pool_k"] == 20


def test_retrieval_plan_preview_routes_catalogue_to_inventory(db_session, monkeypatch):
    monkeypatch.setattr(chat.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(chat.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-plan-catalogue", name="Plan Catalogue", slug="plan-catalogue")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="SPL")
    collection.document_count = 3
    collection.chunk_count = 150
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/retrieval-plan-preview",
        json={
            "query": "De quelles donnees disposes-tu ?",
            "retrieval_filters": {"collection_slug": collection.slug},
            "rag_pipeline_mode": "chah",
            "top_k": 999,
            "candidate_pool_k": 999,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["planner_only"] is True
    assert body["collection"] == collection.slug
    assert body["intent"] == "catalogue"
    assert body["dense"] is True
    assert body["dense_policy"] == "catalogue_inventory"
    assert body["candidate_pool_k"] <= 20
    assert body["retrieval_plan"]["layers"]["dense_qdrant"]["enabled"] is False
    assert body["retrieval_plan"]["guardrails"]["user_scope_required"] is False
    assert body["filters"] == {}


def test_retrieval_plan_preview_uses_sparse_direct_for_dense_quick_chah(db_session, monkeypatch):
    monkeypatch.setattr(chat.settings, "rag_dense_chunk_threshold", 100)
    monkeypatch.setattr(chat.settings, "rag_dense_source_threshold", 2)
    workspace = Workspace(id="ws-plan-dense", name="Plan Dense", slug="plan-dense")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="Dense SPL")
    collection.document_count = 3
    collection.chunk_count = 150
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/retrieval-plan-preview",
        json={
            "query": "Analyse les procedures de securite SPL",
            "retrieval_filters": {"collection_slug": collection.slug},
            "rag_pipeline_mode": "chah",
            "top_k": 999,
            "candidate_pool_k": 999,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["collection"] == collection.slug
    assert body["intent"] == "procedure"
    assert body["dense_policy"] == "fast_sparse_direct"
    assert body["use_hybrid"] is True
    assert body["allow_hah_chah"] is False
    assert body["allow_legacy_hybrid"] is False
    assert body["candidate_pool_k"] <= 20
    assert body["max_candidates"] <= 20
    assert body["retrieval_plan"]["layers"]["hah_chah"]["enabled"] is False
    assert body["retrieval_plan"]["layers"]["sparse"]["enabled"] is True
    assert body["retrieval_plan"]["guardrails"]["global_chunk_search_allowed"] is False
    assert body["retrieval_plan"]["guardrails"]["user_scope_required"] is False
    assert body["deep_retrieval_recommended"] is True
    assert body["filters"] == {}


def test_chat_deep_retrieval_job_queues_worker_payload(db_session, monkeypatch):
    workspace = Workspace(id="ws-deep-job", name="Deep Job", slug="deep-job")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="documents")
    db_session.commit()

    def fake_dispatch(_db, _workspace, job, **_kwargs):
        job.input_ref = {**(job.input_ref or {}), "celery_task_id": "task-deep"}
        return "task-deep"

    monkeypatch.setattr("app.services.workspace_jobs.dispatch_workspace_job", fake_dispatch)

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/deep-retrieval-jobs",
        json={
            "query": "Analyse les procédures",
            "knowledge_scope": None,
            "context_id": None,
            "context_mode": None,
            "rag_pipeline_mode": "chah",
            "retrieval_filters": {"source_kind": "html"},
            "top_k": 999,
            "candidate_pool_k": 999,
            "synthesis_k": 999,
            "source_display_k": 999,
            "previous_answer": "1. Premiere synthese\n2. Deuxieme point",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "rag_deep_retrieval"
    assert body["poll_url"] == f"/workspace-jobs/{body['id']}"
    job = db_session.query(WorkspaceJob).filter(WorkspaceJob.id == body["id"]).one()
    request = job.input_ref["request"]
    assert request["latency_profile"] == "deep"
    assert request["deep_retrieval"] is True
    assert request["top_k"] == 24
    assert request["candidate_pool_k"] == 200
    assert request["synthesis_k"] == 48
    assert request["source_display_k"] == 24
    assert request["previous_answer"] == "1. Premiere synthese 2. Deuxieme point"
    assert job.input_ref["partial_result"]["answer_preview"] == "1. Premiere synthese 2. Deuxieme point"
    assert request["retrieval_filters"] == {"source_kind": "html"}
    assert job.collection_id == collection.id
    assert job.session_id
    assert job.message_id


def test_dense_unscoped_guardrail_queues_auto_deep_retrieval():
    state = {
        "dense_policy": "fast_scoped_dense_auto",
        "retrieval_fallback": "dense_unscoped_fast_policy",
        "scope_confidence": 0.0,
        "retrieval_metrics": {
            "chunks_retrieved": 0,
            "no_context": True,
            "fallback_reason": "dense_unscoped_fast_policy",
        },
    }

    assert chat._should_queue_auto_deep_retrieval({"latency_profile": "fast"}, state) is True


def test_chat_stream_auto_queues_deep_job_for_degraded_retrieval(db_session, monkeypatch):
    workspace = Workspace(id="ws-auto-deep", name="Auto Deep", slug="auto-deep")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="documents")
    db_session.commit()

    def fake_dispatch(_db, _workspace, job, **_kwargs):
        job.input_ref = {**(job.input_ref or {}), "celery_task_id": "task-auto-deep"}
        return "task-auto-deep"

    monkeypatch.setattr("app.services.workspace_jobs.dispatch_workspace_job", fake_dispatch)

    response = _client(db_session, workspace, DeepRecommendedOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={"query": "Analyse complète des procédures SPL"},
    )

    assert response.status_code == 200
    body = response.text
    assert '"phase": "deep_queued"' in body
    assert '"deep_job_id"' in body
    # Strict grounding + degraded retrieval: the post-retrieval guard streams
    # the policy disclaimer instead of letting an ungrounded answer through.
    assert "fast answer" not in body
    assert "retrieval: retrieval_deadline_exceeded" in body

    job = db_session.query(WorkspaceJob).filter(WorkspaceJob.workspace_id == workspace.id).one()
    assert job.kind == "rag_deep_retrieval"
    assert job.collection_id == collection.id
    assert job.input_ref["trigger"] == "auto_fast_refinement"
    assert job.input_ref["request"]["latency_profile"] == "deep"
    assert job.input_ref["request"]["deep_retrieval"] is True
    assert job.input_ref["request"]["top_k"] == 8
    assert job.input_ref["request"]["candidate_pool_k"] == 80
    assert job.input_ref["request"]["synthesis_k"] == 24
    assert "retrieval: retrieval_deadline_exceeded" in job.input_ref["partial_result"]["answer_preview"]
    assert job.input_ref["request"]["retrieval_filters"] == {
        "collection_slug": "documents",
        "project_code": "ACJ100",
        "document_id": ["doc-1", "doc-2"],
    }
    assert job.input_ref["parent_retrieval"]["inferred_filters_forwarded"] is True
    assert sorted(job.input_ref["parent_retrieval"]["forwarded_filter_keys"]) == [
        "collection_slug",
        "document_id",
        "project_code",
    ]

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.output_ref["deep_job_id"] == job.id


def test_auto_deep_filter_merge_preserves_explicit_system_filters():
    request = {
        "retrieval_filters": {
            "source_kind": "pdf",
            "collection_slug": "documents",
        }
    }
    state = {
        "retrieval_scope": {
            "filters": {
                "source_kind": "html",
                "project_code": "ACJ100",
                "document_id": ["doc-1", "doc-1", "doc-2"],
                "ignored": "value",
            }
        }
    }

    merged, forwarded = chat._merge_inferred_retrieval_filters(request, state)

    assert merged == {
        "source_kind": "pdf",
        "collection_slug": "documents",
        "project_code": "ACJ100",
        "document_id": ["doc-1", "doc-2"],
    }
    assert request["retrieval_filters"] == merged
    assert forwarded == ["project_code", "document_id"]


def test_grounding_degraded_reply_fires_only_on_strict_and_empty_retrieval():
    policy = {"mode": "strict", "fallback_disclaimer": "Pas de source fiable."}
    empty_state = {"retrieval_metrics": {"chunks_retrieved": 0, "no_context": True}}

    reply = chat._grounding_degraded_reply(empty_state, policy)
    assert reply is not None
    assert reply.startswith("Pas de source fiable.")
    assert "no_grounded_context" in reply

    # Evidence present → no guard.
    grounded_state = {"retrieval_metrics": {"chunks_retrieved": 3}}
    assert chat._grounding_degraded_reply(grounded_state, policy) is None

    # Balanced mode → no hard guard (callers only annotate).
    assert chat._grounding_degraded_reply(empty_state, {"mode": "balanced"}) is None

    # Meta follow-ups legitimately answer without fresh retrieval.
    assert chat._grounding_degraded_reply(empty_state, policy, is_meta_followup=True) is None

    # No retrieval telemetry at all → never guess.
    assert chat._grounding_degraded_reply({}, policy) is None
    assert chat._grounding_degraded_reply({"retrieval_metrics": {}}, policy) is None


def test_grounding_degraded_reply_reports_fallback_reason():
    policy = {"mode": "strict", "fallback_disclaimer": "Pas de source fiable."}
    state = {
        "retrieval_metrics": {"chunks_retrieved": 0, "no_context": True},
        "retrieval_fallback": "worker_timeout",
    }

    reply = chat._grounding_degraded_reply(state, policy)
    assert reply is not None
    assert "retrieval: worker_timeout" in reply


def test_chat_completion_returns_degraded_retrieval_metadata(db_session, monkeypatch):
    workspace = Workspace(id="ws-completion-degraded", name="Completion Degraded", slug="completion-degraded")
    db_session.add(workspace)
    db_session.commit()
    collection = create_collection(db_session, workspace=workspace, name="documents")
    db_session.commit()

    def fake_dispatch(_db, _workspace, job, **_kwargs):
        job.input_ref = {**(job.input_ref or {}), "celery_task_id": "task-completion-deep"}
        return "task-completion-deep"

    monkeypatch.setattr("app.services.workspace_jobs.dispatch_workspace_job", fake_dispatch)

    response = _client(db_session, workspace, DeepRecommendedOrchestrator(), monkeypatch).post(
        "/chat/completion",
        json={"query": "Analyse complète des procédures SPL"},
    )

    assert response.status_code == 200
    body = response.json()
    # Strict grounding + degraded retrieval: the guard replaces the ungrounded
    # answer with the policy disclaimer and the retrieval failure reason.
    assert "retrieval: retrieval_deadline_exceeded" in body["content"]
    assert "fast answer" not in body["content"]
    assert body["dense_policy"] == "fast_scoped_dense_auto"
    assert body["retrieval_fallback"] == "retrieval_deadline_exceeded"
    assert body["fallback_reason"] == "retrieval_deadline_exceeded"
    assert body["deep_retrieval_recommended"] is True
    assert body["deep_job_id"]
    assert body["deep_job"]["deep_task_id"] == "task-completion-deep"

    job = db_session.query(WorkspaceJob).filter(WorkspaceJob.workspace_id == workspace.id).one()
    assert job.kind == "rag_deep_retrieval"
    assert job.collection_id == collection.id
    assert job.input_ref["parent_retrieval"]["fallback_reason"] == "retrieval_deadline_exceeded"

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.output_ref["fallback_reason"] == "retrieval_deadline_exceeded"
    assert run.output_ref["retrieval_fallback"] == "retrieval_deadline_exceeded"
    assert run.output_ref["deep_job_id"] == job.id


def test_worker_dispatch_queue_only_does_not_inline_deep_retrieval(db_session, monkeypatch):
    from app.services.knowledge_collections import create_worker_job
    from app.services.worker_dispatch import dispatch_worker_job

    workspace = Workspace(id="ws-dispatch-queue-only", name="Queue Only", slug="queue-only")
    db_session.add(workspace)
    db_session.commit()
    job = create_worker_job(
        db_session,
        workspace_id=workspace.id,
        collection_id=None,
        kind="rag_deep_retrieval",
    )
    db_session.commit()

    def fail_inline(_job_id):
        raise AssertionError("deep retrieval must not run inline")

    monkeypatch.setattr(settings, "worker_eager_mode", False)
    monkeypatch.setattr("app.services.worker_dispatch.run_deep_retrieval", fail_inline)

    task_id = dispatch_worker_job(db_session, job, allow_inline_fallback=False)

    db_session.refresh(job)
    assert task_id is None
    assert job.status == "queued"
    assert job.result["stage"] == "dispatch_pending"
    assert job.result["dispatch_warning"] == "worker_dispatch_unavailable"


def test_chat_stream_vigie_defaults_to_balanced_grounding(db_session, monkeypatch):
    workspace = Workspace(id="ws-vigie-grounding", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()
    orchestrator = CapturingOrchestrator()

    response = _client(db_session, workspace, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Explique la méthode pour structurer un brief cabinet.",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    assert orchestrator.last_request["grounding_mode"] == "balanced"
    assert orchestrator.last_request["grounding_policy"]["mode"] == "balanced"
    assert orchestrator.last_request["grounding_policy"]["allow_foundational_fallback"] is True

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.output_ref["grounding_mode"] == "balanced"
    assert run.output_ref["grounding_policy"]["reason"] == "vigie_chat_first"


def test_chat_stream_vigie_balanced_request_stays_strict_for_workspace_facts(db_session, monkeypatch):
    workspace = Workspace(id="ws-vigie-grounding-strict", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()
    orchestrator = CapturingOrchestrator()

    response = _client(db_session, workspace, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Combien de documents sécurité SENTINEL-CI sont indexés aujourd'hui ?",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
            "grounding_mode": "balanced",
        },
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    assert orchestrator.last_request["grounding_mode"] == "strict"
    assert orchestrator.last_request["grounding_policy"]["requested_mode"] == "balanced"
    assert orchestrator.last_request["grounding_policy"]["reason"] == "workspace_fact_or_sensitive_state"
    assert orchestrator.last_request["grounding_policy"]["allow_foundational_fallback"] is False


def test_chat_stream_generic_profile_can_inherit_balanced_grounding(db_session, monkeypatch):
    workspace = Workspace(
        id="ws-generic-grounding",
        name="Generic Grounding",
        slug="generic-grounding",
        settings={
            "assistant_profiles": [
                {
                    "key": "cabinet_advisor",
                    "grounding": {
                        "default_mode": "balanced",
                        "allowed_modes": ["strict", "balanced"],
                    },
                }
            ]
        },
    )
    db_session.add(workspace)
    db_session.commit()
    orchestrator = CapturingOrchestrator()

    response = _client(db_session, workspace, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Explique comment préparer une note cabinet courte.",
            "assistant_profile": "cabinet_advisor",
        },
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    assert orchestrator.last_request["grounding_mode"] == "balanced"
    assert orchestrator.last_request["grounding_policy"]["inherited_from"] == "assistant_profile"
    assert orchestrator.last_request["grounding_policy"]["reason"] == "profile_default"


def test_chat_stream_unconfigured_profile_remains_strict_when_balanced_requested(db_session, monkeypatch):
    workspace = Workspace(id="ws-plain-grounding", name="Plain Grounding", slug="plain-grounding")
    db_session.add(workspace)
    db_session.commit()
    orchestrator = CapturingOrchestrator()

    response = _client(db_session, workspace, orchestrator, monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Explique comment préparer une note cabinet courte.",
            "assistant_profile": "plain_advisor",
            "grounding_mode": "balanced",
        },
    )

    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    assert orchestrator.last_request["grounding_mode"] == "strict"
    assert orchestrator.last_request["grounding_policy"]["requested_mode"] == "balanced"
    assert orchestrator.last_request["grounding_policy"]["reason"] == "requested_mode_not_allowed"


def test_chat_stream_unknown_context_returns_controlled_error(db_session, monkeypatch):
    workspace = Workspace(id="ws-missing-context", name="Missing Context", slug="missing-context")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={"query": "Anything", "context_id": "ctx-does-not-exist"},
    )

    assert response.status_code == 200
    assert '"code": "CHAT_CONTEXT_NOT_FOUND"' in response.text
    assert "data: [DONE]" in response.text
    assert db_session.query(Run).filter(Run.workspace_id == workspace.id).count() == 0


def test_chat_stream_timeout_returns_controlled_error(db_session, monkeypatch):
    monkeypatch.setattr(settings, "chat_stream_timeout_seconds", 0.01)
    workspace = Workspace(id="ws-timeout", name="Timeout", slug="timeout")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, SlowOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={"query": "Will this timeout?"},
    )

    assert response.status_code == 200
    assert '"code": "CHAT_STREAM_TIMEOUT"' in response.text
    assert '"fallback_reason": "chat_stream_timeout"' in response.text
    assert '"partial_answer_chars"' in response.text
    assert "data: [DONE]" in response.text
    assert db_session.query(Run).filter(Run.workspace_id == workspace.id).count() == 0


def test_chat_stream_vigie_map_query_emits_map_command(db_session, monkeypatch):
    workspace = Workspace(id="ws-sentinel-map", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Montre-moi la zone nord sur la carte",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert '"chunk_type": "map_command"' in response.text
    assert '"target": "zone-nord"' in response.text
    assert '"chunk_type": "map_state_updated"' in response.text
    assert "data: [DONE]" in response.text

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "map_command"
    assert run.output_ref["map_command"]["target"] == "zone-nord"


def test_chat_stream_vigie_signals_uses_fast_mission_room_reply(db_session, monkeypatch):
    workspace = Workspace(id="ws-sentinel-vigie", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Quels signaux nécessitent une attention cabinet aujourd'hui ?",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert "attention cabinet" in response.text
    assert '"chunk_type": "text"' in response.text
    assert "data: [DONE]" in response.text
    assert '"chunk_type": "retrieval"' not in response.text

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "vigie_quick_brief"
    assert run.output_ref["knowledge_scope"] == "vigie"


def test_chat_stream_vigie_cockpit_60s_routes_to_priority_summary(db_session, monkeypatch):
    """``Donne-moi le cockpit 60 secondes`` must reach the registry resolver
    (``aya.priority_summary`` → ``briefing_priorities_v1``), not a hardcoded
    cockpit shortcut. The narrative comes from ``ATTENTION_REQUIRED`` so the
    Napié cause-racine wording propagates automatically.
    """
    workspace = Workspace(id="ws-sentinel-cockpit", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Donne-moi le cockpit 60 secondes",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert "prioritaires" in response.text.lower()
    assert '"chunk_type": "action_result"' in response.text
    assert '"aya.priority_summary"' in response.text
    assert '"chunk_type": "retrieval"' not in response.text
    assert "data: [DONE]" in response.text
    assert "Konate" not in response.text
    assert "Burkina" not in response.text

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "action_registry"


def test_chat_stream_vigie_north_situation_drills_to_napie(db_session, monkeypatch):
    """``Quelle est la situation au nord ?`` must drill the causal chain via
    ``aya.explain_why`` and surface the Centre Drones Napié narrative — the
    old hardcoded Konaté/Burkina/CEDEAO Mission Room reply is gone.
    """
    workspace = Workspace(id="ws-sentinel-north", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "AYA, quelle est la situation au nord ?",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert '"chunk_type": "action_result"' in response.text
    assert '"aya.explain_why"' in response.text
    assert ("Napi" in response.text) or ("proj-drone-centre-napie" in response.text)
    assert '"chunk_type": "map_command"' not in response.text
    assert '"chunk_type": "retrieval"' not in response.text
    assert "data: [DONE]" in response.text
    assert "Konate" not in response.text
    assert "Burkina" not in response.text


def test_chat_stream_vigie_brief_operationnel_projet_nord_focuses_napie(db_session, monkeypatch):
    """``Brief opérationnel · Projet sensible · Nord`` card prompt must focus
    the map on the Napié project via ``aya.focus_zone_with_project`` — no
    Konaté/Burkina fallback narrative."""
    workspace = Workspace(id="ws-sentinel-brief", name="SENTINEL-CI", slug="sentinel-ci", mode="demo")
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "AYA, donne-moi le brief opérationnel pour Projet sensible · Nord avec sources et action recommandée.",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert '"aya.focus_zone_with_project"' in response.text
    assert "Napi" in response.text
    assert "Aerostar" in response.text
    assert '"chunk_type": "map_command"' in response.text
    assert "data: [DONE]" in response.text
    assert "Konate" not in response.text
    assert "Burkina" not in response.text


def test_chat_stream_registry_priority_summary(db_session, monkeypatch):
    workspace = Workspace(
        id="ws-sentinel-priority",
        name="SENTINEL-CI",
        slug="sentinel-ci",
        mode="demo",
        settings={"actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]}},
    )
    db_session.add(workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "Aya, fais moi un résumé des sujets prioritaires",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert "prioritaires" in response.text.lower()
    assert '"chunk_type": "action_result"' in response.text
    assert '"chunk_type": "retrieval"' not in response.text
    assert "data: [DONE]" in response.text

    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "action_registry"


def test_chat_stream_registry_maritime_then_oui_draft(db_session, monkeypatch):
    workspace = Workspace(
        id="ws-sentinel-maritime",
        name="SENTINEL-CI",
        slug="sentinel-ci",
        mode="demo",
        settings={"actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]}},
    )
    db_session.add(workspace)
    db_session.commit()
    ensure_workspace_map_seed(db_session, workspace)
    db_session.commit()
    client = _client(db_session, workspace, HappyOrchestrator(), monkeypatch)

    maritime = client.post(
        "/chat/stream",
        json={
            "query": "Montre moi le trafic maritime à destination d'Abidjan",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )
    assert maritime.status_code == 200
    assert '"effect": "assistant-propose"' in maritime.text
    assert "data: [DONE]" in maritime.text

    confirm = client.post(
        "/chat/stream",
        json={
            "query": "oui",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )
    assert confirm.status_code == 200
    assert '"effect": "assistant-draft-open"' in confirm.text
    assert "dedouanement" in confirm.text.lower()
    assert "data: [DONE]" in confirm.text


def test_chat_stream_registry_next_meeting_navigates_agenda(db_session, monkeypatch):
    from app.services.workspace_calendar import ensure_calendar_seed

    workspace = Workspace(
        id="ws-sentinel-next",
        name="SENTINEL-CI",
        slug="sentinel-ci",
        mode="demo",
        settings={"actions": {"enabled_packs": ["global_voice_v1", "sentinel_ci_aya_v1"]}},
    )
    db_session.add(workspace)
    db_session.commit()
    ensure_calendar_seed(db_session, workspace)
    db_session.commit()

    response = _client(db_session, workspace, HappyOrchestrator(), monkeypatch).post(
        "/chat/stream",
        json={
            "query": "OK Aya, quel est mon prochain RDV ?",
            "assistant_profile": "vigie_executive",
            "knowledge_scope": "vigie",
        },
    )

    assert response.status_code == 200
    assert "prochain" in response.text.lower()
    assert "evt-" in response.text
    assert '"effect": "assistant-navigate"' in response.text
    assert "/hypervisor/mission-room/agenda" in response.text
    assert "data: [DONE]" in response.text
