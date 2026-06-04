from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import sessions, workspace_jobs
from app.models.audit import AuditLog
from app.models.user import Message, Session as ChatSession, User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(sessions.router, prefix="/api/v1/sessions")
    app.include_router(workspace_jobs.router, prefix="/api/v1/workspace-jobs")
    app.dependency_overrides[sessions.get_current_workspace] = lambda: workspace
    app.dependency_overrides[sessions.get_current_user] = lambda: user
    app.dependency_overrides[sessions.get_db] = lambda: db_session
    app.dependency_overrides[workspace_jobs.get_current_workspace] = lambda: workspace
    app.dependency_overrides[workspace_jobs.get_current_user] = lambda: user
    app.dependency_overrides[workspace_jobs.get_db] = lambda: db_session
    return TestClient(app)


def _seed_workspace_users(db_session):
    workspace = Workspace(id="workspace-chat", slug="workspace-chat", name="Workspace Chat", mode="standard")
    owner = User(id="user-owner", username="owner", email="owner@example.test", is_active=True)
    other = User(id="user-other", username="other", email="other@example.test", is_active=True)
    admin = User(id="user-admin", username="admin", email="admin@example.test", role="admin", is_active=True)
    db_session.add_all(
        [
            workspace,
            owner,
            other,
            admin,
            WorkspaceMember(user_id=owner.id, workspace_id=workspace.id, role="member"),
            WorkspaceMember(user_id=other.id, workspace_id=workspace.id, role="member"),
            WorkspaceMember(user_id=admin.id, workspace_id=workspace.id, role="admin", role_template="workspace_admin"),
        ]
    )
    db_session.commit()
    return workspace, owner, other, admin


def test_sessions_are_private_to_current_user(db_session):
    workspace, owner, other, _admin = _seed_workspace_users(db_session)
    owner_session = ChatSession(
        id="session-owner",
        workspace_id=workspace.id,
        user_id=owner.id,
        title="Owner chat",
        status="active",
    )
    other_session = ChatSession(
        id="session-other",
        workspace_id=workspace.id,
        user_id=other.id,
        title="Other chat",
        status="active",
    )
    db_session.add_all([owner_session, other_session])
    db_session.commit()

    client = _client(db_session, workspace, owner)
    listed = client.get("/api/v1/sessions")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["sessions"]] == ["session-owner"]

    hidden = client.get("/api/v1/sessions/session-other")
    assert hidden.status_code == 404


def test_session_detail_returns_only_attached_messages_and_jobs(db_session):
    workspace, owner, _other, _admin = _seed_workspace_users(db_session)
    first_session = ChatSession(
        id="session-first",
        workspace_id=workspace.id,
        user_id=owner.id,
        title="First chat",
        status="active",
    )
    second_session = ChatSession(
        id="session-second",
        workspace_id=workspace.id,
        user_id=owner.id,
        title="Second chat",
        status="active",
    )
    db_session.add_all([first_session, second_session])
    db_session.flush()
    db_session.add_all(
        [
            Message(id="message-user-1", session_id=first_session.id, role="user", content="question"),
            Message(id="message-assistant-1", session_id=first_session.id, role="assistant", content="answer"),
            Message(id="message-other", session_id=second_session.id, role="assistant", content="other answer"),
            WorkspaceJob(
                id="job-first",
                workspace_id=workspace.id,
                session_id=first_session.id,
                message_id="message-assistant-1",
                kind="rag_deep_retrieval",
                title="Deep Search first",
                status="completed",
                progress=100,
                stage="deep_completed",
                input_ref={"request": {"query": "first"}},
                result={"answer": "first final answer"},
                created_by_user_id=owner.id,
            ),
            WorkspaceJob(
                id="job-second",
                workspace_id=workspace.id,
                session_id=second_session.id,
                message_id="message-other",
                kind="rag_deep_retrieval",
                title="Deep Search second",
                status="completed",
                progress=100,
                stage="deep_completed",
                input_ref={"request": {"query": "second"}},
                result={"answer": "second final answer"},
                created_by_user_id=owner.id,
            ),
        ]
    )
    db_session.commit()

    client = _client(db_session, workspace, owner)
    detail = client.get("/api/v1/sessions/session-first?include_messages=true&include_jobs=true")
    assert detail.status_code == 200
    body = detail.json()
    assert [message["id"] for message in body["messages"]] == ["message-user-1", "message-assistant-1"]
    assert [job["id"] for job in body["jobs"]] == ["job-first"]
    assert "job-second" not in str(body)
    assert "message-other" not in str(body)


def test_archive_and_delete_remove_sessions_from_default_list(db_session):
    workspace, owner, _other, _admin = _seed_workspace_users(db_session)
    session = ChatSession(
        id="session-to-archive",
        workspace_id=workspace.id,
        user_id=owner.id,
        title="To archive",
        status="active",
    )
    db_session.add(session)
    db_session.commit()

    client = _client(db_session, workspace, owner)
    archived = client.patch("/api/v1/sessions/session-to-archive", json={"status": "archived"})
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.get("/api/v1/sessions").json()["sessions"] == []
    assert client.get("/api/v1/sessions?status=archived").json()["sessions"][0]["id"] == "session-to-archive"

    deleted = client.delete("/api/v1/sessions/session-to-archive")
    assert deleted.status_code == 200
    assert client.get("/api/v1/sessions?status=all").json()["sessions"] == []


def test_admin_can_read_other_user_session_with_audit_event(db_session):
    workspace, _owner, other, admin = _seed_workspace_users(db_session)
    session = ChatSession(
        id="session-audited",
        workspace_id=workspace.id,
        user_id=other.id,
        title="Audited chat",
        status="active",
    )
    db_session.add(session)
    db_session.commit()

    client = _client(db_session, workspace, admin)
    detail = client.get("/api/v1/sessions/session-audited?include_messages=true")
    assert detail.status_code == 200
    assert detail.json()["id"] == "session-audited"

    audit = db_session.query(AuditLog).filter(AuditLog.event_type == "chat.session.admin_read").one()
    assert audit.workspace_id == workspace.id
    assert audit.details["session_id"] == "session-audited"
    assert audit.details["owner_user_id"] == other.id


def test_workspace_jobs_are_filtered_by_session_and_owner(db_session):
    workspace, owner, other, _admin = _seed_workspace_users(db_session)
    owner_session = ChatSession(
        id="session-owner-jobs",
        workspace_id=workspace.id,
        user_id=owner.id,
        title="Owner jobs",
        status="active",
    )
    other_session = ChatSession(
        id="session-other-jobs",
        workspace_id=workspace.id,
        user_id=other.id,
        title="Other jobs",
        status="active",
    )
    db_session.add_all(
        [
            owner_session,
            other_session,
            WorkspaceJob(
                id="job-owner-visible",
                workspace_id=workspace.id,
                session_id=owner_session.id,
                kind="rag_deep_retrieval",
                title="Owner job",
                status="running",
                progress=40,
                stage="deep_retrieve",
                input_ref={},
                result={},
                created_by_user_id=owner.id,
            ),
            WorkspaceJob(
                id="job-other-hidden",
                workspace_id=workspace.id,
                session_id=other_session.id,
                kind="rag_deep_retrieval",
                title="Other job",
                status="running",
                progress=40,
                stage="deep_retrieve",
                input_ref={},
                result={},
                created_by_user_id=other.id,
            ),
            WorkspaceJob(
                id="job-owner-session-system",
                workspace_id=workspace.id,
                session_id=owner_session.id,
                kind="rag_deep_retrieval",
                title="Owner session system job",
                status="running",
                progress=20,
                stage="deep_retrieve",
                input_ref={},
                result={},
                created_by_user_id=None,
            ),
            WorkspaceJob(
                id="job-ownerless-hidden",
                workspace_id=workspace.id,
                session_id=None,
                kind="rag_deep_retrieval",
                title="Ownerless job",
                status="running",
                progress=20,
                stage="deep_retrieve",
                input_ref={},
                result={},
                created_by_user_id=None,
            ),
        ]
    )
    db_session.commit()

    client = _client(db_session, workspace, owner)
    listed = client.get("/api/v1/workspace-jobs/?session_id=session-owner-jobs")
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()["jobs"]} == {"job-owner-visible", "job-owner-session-system"}

    other_list = client.get("/api/v1/workspace-jobs/?session_id=session-other-jobs")
    assert other_list.status_code == 200
    assert other_list.json()["jobs"] == []

    all_visible = client.get("/api/v1/workspace-jobs/")
    assert all_visible.status_code == 200
    assert {item["id"] for item in all_visible.json()["jobs"]} == {"job-owner-visible", "job-owner-session-system"}

    hidden_detail = client.get("/api/v1/workspace-jobs/job-other-hidden")
    assert hidden_detail.status_code == 404
    ownerless_detail = client.get("/api/v1/workspace-jobs/job-ownerless-hidden")
    assert ownerless_detail.status_code == 404
