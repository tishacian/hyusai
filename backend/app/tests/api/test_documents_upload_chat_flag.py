"""API tests for the chat drop-and-ask upload feature gate.

``POST /api/v1/documents/upload-batch`` must reject ``source=chat_drop_and_ask``
uploads when the per-workspace ``chat_document_upload`` flag is off (default on),
while leaving Knowledge Base uploads (no ``source``) untouched.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import documents
from app.core.config import settings
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    # Uploading needs a writing member since L35 (viewers and non-members never write).
    db_session.add(
        WorkspaceMember(
            user_id=user.id,
            workspace_id=workspace.id,
            role="member",
            role_template="workspace_contributor",
        )
    )
    db_session.commit()
    app = FastAPI()
    app.include_router(documents.router, prefix="/documents")
    app.dependency_overrides[documents.get_current_workspace] = lambda: workspace
    app.dependency_overrides[documents.get_current_user] = lambda: user
    app.dependency_overrides[documents.get_db] = lambda: db_session
    return TestClient(app)


def _stub_ingest(monkeypatch) -> None:
    """Short-circuit the heavy ingest path so we only assert the feature gate."""
    monkeypatch.setattr(settings, "document_ingest_async_enabled", True)
    monkeypatch.setattr(
        documents,
        "create_or_get_collection",
        lambda *args, **kwargs: SimpleNamespace(id="col-1", slug="documents", status="queued"),
    )

    async def _fake_queue(*, db, workspace, collection, files):
        return {
            "status": "queued",
            "collection_id": collection.id,
            "collection_slug": collection.slug,
            "job_id": "job-1",
            "files": [f.filename for f in files],
        }

    monkeypatch.setattr(documents, "_queue_collection_ingest", _fake_queue)


def _upload(client: TestClient, *, source: str | None):
    files = {"files": ("note.txt", b"hello world", "text/plain")}
    data = {"collection_name": "documents"}
    if source is not None:
        data["source"] = source
    return client.post("/documents/upload-batch", files=files, data=data)


def test_chat_drop_upload_blocked_when_flag_off(db_session):
    workspace = Workspace(
        id="ws-off",
        name="Off",
        slug="off",
        settings={"features": {"chat_document_upload": False}},
    )
    user = User(id="user-off", email="off@datategy.net", username="off")
    db_session.add_all([workspace, user])
    db_session.commit()

    response = _upload(_client(db_session, workspace, user), source="chat_drop_and_ask")

    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()


def test_chat_drop_upload_allowed_when_flag_on(db_session, monkeypatch):
    _stub_ingest(monkeypatch)
    # Flag absent => default-on (opt-out semantics).
    workspace = Workspace(id="ws-on", name="On", slug="on", settings={})
    user = User(id="user-on", email="on@datategy.net", username="on")
    db_session.add_all([workspace, user])
    db_session.commit()

    response = _upload(_client(db_session, workspace, user), source="chat_drop_and_ask")

    assert response.status_code != 403
    assert response.status_code == 200


def test_knowledge_base_upload_never_blocked_by_flag(db_session, monkeypatch):
    _stub_ingest(monkeypatch)
    # Flag explicitly OFF, but the KB upload sends no ``source`` and must pass.
    workspace = Workspace(
        id="ws-kb",
        name="KB",
        slug="kb",
        settings={"features": {"chat_document_upload": False}},
    )
    user = User(id="user-kb", email="kb@datategy.net", username="kb")
    db_session.add_all([workspace, user])
    db_session.commit()

    response = _upload(_client(db_session, workspace, user), source=None)

    assert response.status_code != 403
    assert response.status_code == 200
