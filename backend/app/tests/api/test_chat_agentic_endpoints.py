"""API contracts for the governed Agentic runtime behind ``/chat``.

These tests keep the DAG itself out of scope while exercising the production
endpoint boundary: workspace policy resolution, canonical Run creation,
append-only SSE mapping, chat-history persistence, and the narrow classic
fallback allowed for technical failures.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import chat
from app.models.knowledge_collection import KnowledgeCollection
from app.models.policy import ControlPolicy
from app.models.run import Run, SkillInvocation
from app.models.system import System
from app.models.user import Message
from app.models.user import Session as ChatSession
from app.models.workspace import Workspace
from app.services.evaluation.canonical_answer_service import create_canonical_answer

ANDRITZ_NOTICES = "andritz-notices-techniques-spl-pilot"
AGENTIC_FLOW = json.loads(
    (
        Path(__file__).resolve().parents[2] / "resources" / "flows" / "andritz_chat_agentic_v3.json"
    ).read_text(encoding="utf-8")
)["flow_definition"]


def _chat_execution_policy() -> dict[str, Any]:
    return {
        "version": 1,
        "mode": "agentic_default",
        "target": {
            "system_type": "chat_agentic",
            "variant": "chat_agentic_thinking_v1",
        },
        "fallback": "classic",
        "rollout": {"percentage": 100, "salt": "andritz-agentic-v1"},
    }


def _seed_agentic_workspace(db_session, *, suffix: str) -> tuple[Workspace, System, System]:
    executor_id = f"sys-agentic-chat-{suffix}"
    policy_id = f"policy-agentic-chat-{suffix}"
    workspace = Workspace(
        id=f"ws-agentic-api-{suffix}",
        name=f"Agentic API {suffix}",
        slug=f"agentic-api-{suffix}",
        settings={
            "family": "andritz",
            "chat_execution": _chat_execution_policy(),
            "_migration_059_andritz_agentic_default_state": {
                "revision": "059_andritz_agentic_default",
                "schema": 1,
                "system_id": executor_id,
                "control_policy": {"id": policy_id},
            },
        },
    )
    surface = System(
        id=f"sys-workspace-chat-{suffix}",
        workspace_id=workspace.id,
        name="Agentium Workspace Chat",
        objective="Own the public chat surface",
        settings={"system_type": "workspace_chat"},
        flow_definition={"variant": "chat_transverse_v1", "chat": {}},
        status="active",
    )
    executor = System(
        id=executor_id,
        workspace_id=workspace.id,
        name="Andritz Chat Agentic",
        objective="Execute grounded Andritz chat turns",
        settings={
            "system_type": "chat_agentic",
            "flow_revision": "056_andritz_chat_asset_binding",
            "retrieval_contract": {
                "collection": ANDRITZ_NOTICES,
                "asset_binding": "authoritative",
                "empty_bound_collection": "abstain",
                "allow_workspace_fallback": False,
            },
        },
        flow_definition=AGENTIC_FLOW,
        execution_profile={"max_runtime_s": 40},
        control_policy_id=policy_id,
        status="active",
    )
    control_policy = ControlPolicy(
        id=policy_id,
        workspace_id=workspace.id,
        name="Andritz Agentic test membrane",
        scope="system",
        target_id=executor.id,
        extra={"membrane_spec": {"inbound": {"collection_allowlist": [ANDRITZ_NOTICES]}}},
    )
    collection = KnowledgeCollection(
        id=f"collection-agentic-chat-{suffix}",
        workspace_id=workspace.id,
        slug=ANDRITZ_NOTICES,
        name="Andritz SPL notices",
        description="test",
        status="ready",
        vector_collection_name=f"{workspace.slug}__{ANDRITZ_NOTICES}",
        artifact_prefix=f"workspaces/{workspace.id}/collections/{ANDRITZ_NOTICES}",
        document_count=8,
        chunk_count=128,
    )
    db_session.add_all([workspace, surface, executor, control_policy, collection])
    db_session.commit()
    return workspace, surface, executor


def _seed_history(db_session, workspace: Workspace, *, suffix: str) -> ChatSession:
    started = datetime.utcnow() - timedelta(minutes=2)
    session = ChatSession(
        id=f"session-agentic-api-{suffix}",
        user_id=None,
        workspace_id=workspace.id,
        title="BCX200",
        status="active",
        context_signature="existing-agentic-test-session",
        created_at=started,
        last_activity=started,
        meta_data={},
    )
    db_session.add(session)
    db_session.flush()
    db_session.add_all(
        [
            Message(
                id=f"message-history-user-{suffix}",
                session_id=session.id,
                role="user",
                content="Tell me about project BCX200.",
                timestamp=started,
                meta_data={},
            ),
            Message(
                id=f"message-history-assistant-{suffix}",
                session_id=session.id,
                role="assistant",
                content="BCX200 is referenced by the indexed technical notices.",
                timestamp=started + timedelta(seconds=1),
                meta_data={"salient_entities": {"references": ["BCX200"], "documents": []}},
            ),
        ]
    )
    db_session.commit()
    return session


def _client(
    db_session,
    workspace: Workspace,
    monkeypatch,
    *,
    orchestrator: Any,
    scheduled: list[str],
) -> TestClient:
    app = FastAPI()
    app.include_router(chat.router, prefix="/chat")
    app.dependency_overrides[chat.get_current_workspace] = lambda: workspace
    app.dependency_overrides[chat.get_current_user] = lambda: None
    app.dependency_overrides[chat.get_db] = lambda: db_session
    monkeypatch.setattr(chat.settings, "enable_agentic_chat", True)
    monkeypatch.setattr(chat, "get_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(chat, "schedule_eval", scheduled.append)
    return TestClient(app)


def _install_terminal_agentic_execution(
    db_session,
    monkeypatch,
    *,
    status: str,
    answer: str | None = None,
    error: str | None = None,
) -> None:
    async def _events(run_id: str, *, timeout_seconds: float):
        assert timeout_seconds == 40
        yield {"kind": "run_start", "run_id": run_id, "status": "running"}
        yield {
            "kind": "node_start",
            "run_id": run_id,
            "node_id": "task.retrieve_fast",
            "skill_slug": "semantic_search_v1",
            "status": "running",
        }

        run = db_session.query(Run).filter(Run.id == run_id).one()
        run.status = status
        run.error = error
        run.completed_at = datetime.utcnow() if status in {"completed", "failed"} else None
        if answer is not None:
            run.output_ref = {
                "answer": answer,
                "citations": [
                    {
                        "id": "source-bcx200",
                        "title": "BCX200 operating manual",
                        "document_id": "doc-bcx200",
                        "collection": ANDRITZ_NOTICES,
                        "page": 12,
                    }
                ],
            }
            db_session.add_all(
                [
                    SkillInvocation(
                        run_id=run_id,
                        skill_slug="chat_agentic_plan_v1",
                        status="completed",
                        output_ref={
                            "mode": "fast",
                            "answer_profile": "equipment_detail",
                            "retrieval": {"lane": "fast"},
                        },
                        latency_ms=4,
                    ),
                    SkillInvocation(
                        run_id=run_id,
                        skill_slug="semantic_search_v1",
                        status="completed",
                        output_ref={
                            "raw_chunks_retrieved": 1,
                            "collections_touched": [ANDRITZ_NOTICES],
                            "retrieval_scope": {
                                "collections": [ANDRITZ_NOTICES],
                                "intent": "equipment_detail",
                            },
                            "results": [
                                {
                                    "content": "BCX200 pump P-101 is rated at 22 kW.",
                                    "metadata": {"collection_slug": ANDRITZ_NOTICES},
                                }
                            ],
                        },
                        latency_ms=9,
                    ),
                ]
            )
        db_session.commit()
        yield {
            "kind": "run_end",
            "run_id": run_id,
            "status": status,
            "error": error,
        }

    monkeypatch.setattr(chat, "iter_agentic_run_events", _events)


def _sse_payloads(response_text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for line in response_text.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        payloads.append(json.loads(line.removeprefix("data: ")))
    return payloads


def test_stream_agentic_default_works_without_classic_orchestrator_and_persists_history(
    db_session,
    monkeypatch,
):
    workspace, _surface, executor = _seed_agentic_workspace(db_session, suffix="success")
    session = _seed_history(db_session, workspace, suffix="success")
    scheduled: list[str] = []
    _install_terminal_agentic_execution(
        db_session,
        monkeypatch,
        status="completed",
        answer="Pump P-101 in project BCX200 is rated at 22 kW [1].",
    )
    client = _client(
        db_session,
        workspace,
        monkeypatch,
        orchestrator=None,
        scheduled=scheduled,
    )

    response = client.post(
        "/chat/stream",
        json={
            "query": "What is the rated power of pump P-101 in project BCX200?",
            "session_id": session.id,
        },
    )

    assert response.status_code == 200
    payloads = _sse_payloads(response.text)
    assert any(item.get("chunk_type") == "decision_step" for item in payloads)
    assert any(
        item.get("chunk_type") == "retrieval" and item.get("phase") == "started"
        for item in payloads
    )
    completed_retrieval = next(
        item
        for item in payloads
        if item.get("chunk_type") == "retrieval" and item.get("phase") == "completed"
    )
    assert completed_retrieval["details"]["collection"] == ANDRITZ_NOTICES
    final = next(item for item in payloads if item.get("chunk_type") == "text")
    assert final["route"] == "agentic"
    assert final["content"].startswith("Pump P-101")
    assert final["sources"][0]["collection"] == ANDRITZ_NOTICES
    assert any(item.get("chunk_type") == "eval_pending" for item in payloads)
    assert "ORCHESTRATOR_UNAVAILABLE" not in response.text
    assert response.text.rstrip().endswith("data: [DONE]")

    runs = db_session.query(Run).filter(Run.workspace_id == workspace.id).all()
    assert len(runs) == 1
    run = runs[0]
    assert run.trigger == "chat_agentic"
    assert run.system_id == executor.id
    assert run.input_ref["conversation_history"] == [
        {"role": "user", "content": "Tell me about project BCX200."},
        {
            "role": "assistant",
            "content": "BCX200 is referenced by the indexed technical notices.",
        },
    ]
    assert run.input_ref["salient_entities"]["references"] == ["BCX200"]
    assert run.input_ref["retrieval_contract"]["collection"] == ANDRITZ_NOTICES
    assert run.output_ref["route"] == "agentic"
    assert run.output_ref["retrieval_metrics"]["collections_touched"] == [ANDRITZ_NOTICES]
    assert scheduled == [run.id]

    new_messages = (
        db_session.query(Message)
        .filter(
            Message.session_id == session.id,
            Message.id.notin_(
                ["message-history-user-success", "message-history-assistant-success"]
            ),
        )
        .order_by(Message.timestamp.asc())
        .all()
    )
    assert [(item.role, item.content) for item in new_messages] == [
        ("user", "What is the rated power of pump P-101 in project BCX200?"),
        ("assistant", "Pump P-101 in project BCX200 is rated at 22 kW [1]."),
    ]
    assert new_messages[-1].meta_data["run_id"] == run.id


def test_stream_persistence_failure_never_generates_a_second_classic_answer(
    db_session,
    monkeypatch,
):
    workspace, _surface, _executor = _seed_agentic_workspace(
        db_session,
        suffix="persist-failure",
    )
    scheduled: list[str] = []
    _install_terminal_agentic_execution(
        db_session,
        monkeypatch,
        status="completed",
        answer="BCX200 pump P-101 is rated at 22 kW [1].",
    )
    monkeypatch.setattr(
        chat,
        "_persist_agentic_chat_turn",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("history unavailable")),
    )

    def _classic_must_not_be_resolved():
        raise AssertionError("persistence failure must not generate a classic answer")

    client = _client(
        db_session,
        workspace,
        monkeypatch,
        orchestrator=None,
        scheduled=scheduled,
    )
    monkeypatch.setattr(chat, "get_orchestrator", _classic_must_not_be_resolved)

    response = client.post(
        "/chat/stream",
        json={"query": "What is pump P-101 rated at for BCX200?"},
    )

    assert response.status_code == 200
    payloads = _sse_payloads(response.text)
    final = next(item for item in payloads if item.get("chunk_type") == "text")
    assert final["route"] == "agentic"
    assert final["content"].startswith("BCX200 pump P-101")
    runs = db_session.query(Run).filter(Run.workspace_id == workspace.id).all()
    assert len(runs) == 1
    assert runs[0].trigger == "chat_agentic"
    assert scheduled == [runs[0].id]


class _CapturingClassicOrchestrator:
    def __init__(self) -> None:
        self.request: dict[str, Any] | None = None

    async def process_request(self, request: dict[str, Any]):
        self.request = request
        yield {
            "chunk_type": "text",
            "content": "Classic fallback stayed inside the Andritz notices corpus.",
            "sources": [{"title": "BCX200 fallback notice"}],
            "is_final": False,
        }
        yield {"chunk_type": "text", "content": "", "is_final": True}


def test_zero_percent_classic_chat_endpoints_stay_on_authoritative_collection(
    db_session,
    monkeypatch,
):
    workspace, _surface, _executor = _seed_agentic_workspace(
        db_session,
        suffix="classic-zero",
    )
    workspace_settings = deepcopy(workspace.settings)
    workspace_settings["chat_execution"]["rollout"]["percentage"] = 0
    workspace.settings = workspace_settings
    create_canonical_answer(
        db_session,
        workspace_id=workspace.id,
        question="Quelles pompes sont documentées pour le projet BCX200 ?",
        answer="POISONED CANONICAL BYPASS",
        actor="trusted-test-reviewer",
    )
    db_session.commit()
    orchestrator = _CapturingClassicOrchestrator()
    client = _client(
        db_session,
        workspace,
        monkeypatch,
        orchestrator=orchestrator,
        scheduled=[],
    )

    for path in ("/chat/completion", "/chat/stream"):
        response = client.post(
            path,
            json={
                "query": "Quelles pompes sont documentées pour le projet BCX200 ?",
                "ui_locale": "fr",
            },
        )

        assert response.status_code == 200
        assert "POISONED CANONICAL BYPASS" not in response.text
        assert orchestrator.request is not None
        assert orchestrator.request["context_collection"] == ANDRITZ_NOTICES
        assert orchestrator.request["context_mode"] == "replace"
        assert orchestrator.request["authoritative_collections"] == [ANDRITZ_NOTICES]
        assert "knowledge_scope" not in orchestrator.request


def test_stream_technical_agentic_failure_falls_back_with_authoritative_collection(
    db_session,
    monkeypatch,
):
    workspace, _surface, _executor = _seed_agentic_workspace(db_session, suffix="fallback")
    orchestrator = _CapturingClassicOrchestrator()
    scheduled: list[str] = []
    _install_terminal_agentic_execution(
        db_session,
        monkeypatch,
        status="failed",
        error="agentic_runtime_unavailable",
    )
    client = _client(
        db_session,
        workspace,
        monkeypatch,
        orchestrator=orchestrator,
        scheduled=scheduled,
    )

    response = client.post(
        "/chat/stream",
        json={"query": "Which pumps are documented for project BCX200?"},
    )

    assert response.status_code == 200
    payloads = _sse_payloads(response.text)
    fallback_step = next(
        item
        for item in payloads
        if item.get("chunk_type") == "decision_step" and item.get("route") == "classic_fallback"
    )
    assert fallback_step["decision_step"]["metrics"]["collection"] == ANDRITZ_NOTICES
    assert "Classic fallback stayed inside" in response.text
    assert orchestrator.request is not None
    assert orchestrator.request["context_collection"] == ANDRITZ_NOTICES
    assert orchestrator.request["context_mode"] == "replace"
    assert orchestrator.request["authoritative_collections"] == [ANDRITZ_NOTICES]
    assert "knowledge_scope" not in orchestrator.request

    runs = db_session.query(Run).filter(Run.workspace_id == workspace.id).all()
    assert sorted(item.trigger for item in runs) == ["chat", "chat_agentic"]
    agentic_run = next(item for item in runs if item.trigger == "chat_agentic")
    classic_run = next(item for item in runs if item.trigger == "chat")
    assert agentic_run.output_ref["fallback_reason"] == "agentic_runtime_unavailable"
    assert classic_run.output_ref["agentic_attempt_run_id"] == agentic_run.id
    assert classic_run.output_ref["fallback_reason"] == "agentic_runtime_unavailable"


def test_stream_policy_terminal_emits_safe_final_without_classic_fallback_or_eval(
    db_session,
    monkeypatch,
):
    workspace, _surface, _executor = _seed_agentic_workspace(db_session, suffix="policy")
    session = _seed_history(db_session, workspace, suffix="policy")
    scheduled: list[str] = []
    _install_terminal_agentic_execution(
        db_session,
        monkeypatch,
        status="hitl_pending",
    )

    def _classic_must_not_be_resolved():
        raise AssertionError("policy terminals must not resolve the classic orchestrator")

    client = _client(
        db_session,
        workspace,
        monkeypatch,
        orchestrator=None,
        scheduled=scheduled,
    )
    monkeypatch.setattr(chat, "get_orchestrator", _classic_must_not_be_resolved)

    response = client.post(
        "/chat/stream",
        json={
            "query": "Give me the unvalidated safety conclusion for BCX200.",
            "session_id": session.id,
        },
    )

    assert response.status_code == 200
    payloads = _sse_payloads(response.text)
    final = next(item for item in payloads if item.get("chunk_type") == "text")
    assert final["route"] == "agentic_review"
    assert final["policy_terminal"] is True
    assert "validation experte" in final["content"]
    assert final["sources"] == []
    assert not any(item.get("chunk_type") == "eval_pending" for item in payloads)
    assert any(item.get("chunk_type") == "hitl_pending" and item.get("run_id") for item in payloads)
    assert not any(item.get("route") == "classic_fallback" for item in payloads)
    assert scheduled == []

    runs = db_session.query(Run).filter(Run.workspace_id == workspace.id).all()
    assert len(runs) == 1
    assert runs[0].trigger == "chat_agentic"
    assert runs[0].status == "hitl_pending"
    assert runs[0].output_ref["route"] == "agentic_review"
    new_messages = (
        db_session.query(Message)
        .filter(
            Message.session_id == session.id,
            Message.id.notin_(["message-history-user-policy", "message-history-assistant-policy"]),
        )
        .all()
    )
    assert sorted(item.role for item in new_messages) == ["assistant", "user"]


def test_completion_uses_the_same_agentic_policy_runtime_and_canonical_run(
    db_session,
    monkeypatch,
):
    workspace, _surface, executor = _seed_agentic_workspace(db_session, suffix="completion")
    scheduled: list[str] = []
    _install_terminal_agentic_execution(
        db_session,
        monkeypatch,
        status="completed",
        answer="BCX200 pump P-101 is rated at 22 kW [1].",
    )

    def _classic_must_not_be_resolved():
        raise AssertionError("successful Agentic completion must not resolve classic")

    client = _client(
        db_session,
        workspace,
        monkeypatch,
        orchestrator=None,
        scheduled=scheduled,
    )
    monkeypatch.setattr(chat, "get_orchestrator", _classic_must_not_be_resolved)

    response = client.post(
        "/chat/completion",
        json={"query": "What is pump P-101 rated at for project BCX200?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["route"] == "agentic"
    assert payload["status"] == "completed"
    assert payload["content"].startswith("BCX200 pump P-101")
    assert payload["sources"][0]["collection"] == ANDRITZ_NOTICES
    assert payload["retrieval_metrics"]["collection"] == ANDRITZ_NOTICES
    run = db_session.query(Run).filter(Run.workspace_id == workspace.id).one()
    assert run.trigger == "chat_agentic"
    assert run.system_id == executor.id
    assert scheduled == [run.id]
    assert (
        db_session.query(Message).filter(Message.session_id == run.input_ref["session_id"]).count()
        == 2
    )
