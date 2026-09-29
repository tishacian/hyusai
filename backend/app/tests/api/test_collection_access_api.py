from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import chat, documents, knowledge
from app.models.knowledge_collection import KnowledgeCollection
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.knowledge_collections import create_collection


def _client(db_session, workspace: Workspace, user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(documents.router, prefix="/documents")
    app.dependency_overrides[documents.get_current_workspace] = lambda: workspace
    app.dependency_overrides[documents.get_current_user] = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[documents.get_db] = lambda: db_session
    return TestClient(app)


def _knowledge_client(db_session, workspace: Workspace, user_id: str) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/knowledge")
    app.dependency_overrides[knowledge.get_current_workspace] = lambda: workspace
    app.dependency_overrides[knowledge.get_current_user] = lambda: SimpleNamespace(id=user_id)
    app.dependency_overrides[knowledge.get_db] = lambda: db_session
    return TestClient(app)


def _member(db_session, workspace: Workspace, *, user_id: str, role_template: str, labels=None) -> User:
    user = User(id=user_id, username=user_id, email=f"{user_id}@example.test")
    db_session.add(user)
    db_session.add(
        WorkspaceMember(
            user_id=user_id,
            workspace_id=workspace.id,
            role="member",
            role_template=role_template,
            custom_labels=labels or [],
        )
    )
    return user


def test_collection_access_filters_lists_and_denies_reads(db_session):
    workspace = Workspace(id="ws-access", name="Access", slug="access")
    db_session.add(workspace)
    _member(
        db_session,
        workspace,
        user_id="viewer",
        role_template="workspace_viewer",
        labels=["suppliers"],
    )
    open_collection = create_collection(db_session, workspace=workspace, name="Open")
    hidden = create_collection(db_session, workspace=workspace, name="Hidden")
    hidden.access = {"read": ["role:workspace_admin"], "write": ["role:workspace_admin"]}
    visible = create_collection(db_session, workspace=workspace, name="Suppliers")
    visible.access = {"read": ["group:suppliers"], "write": ["group:buyers"]}
    db_session.commit()
    client = _client(db_session, workspace, "viewer")

    listed = client.get("/documents/collections")
    assert listed.status_code == 200
    assert set(listed.json()["collections"]) == {open_collection.slug, visible.slug}

    assert client.get(f"/documents/collections/{hidden.id}/inventory").status_code == 403
    assert client.get("/documents/list", params={"collection_name": hidden.slug}).status_code == 403
    assert client.post("/documents/search", json={"query": "secret", "collection_name": hidden.slug}).status_code == 403


def test_collection_access_blocks_viewer_upload_even_when_read_is_granted(db_session):
    workspace = Workspace(id="ws-upload", name="Upload", slug="upload")
    db_session.add(workspace)
    _member(
        db_session,
        workspace,
        user_id="viewer",
        role_template="workspace_viewer",
        labels=["suppliers"],
    )
    collection = create_collection(db_session, workspace=workspace, name="Readable")
    collection.access = {"read": ["group:suppliers"], "write": ["group:suppliers"]}
    db_session.commit()
    client = _client(db_session, workspace, "viewer")

    response = client.post(
        f"/documents/collections/{collection.id}/documents",
        files={"files": ("note.txt", b"read me", "text/plain")},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "COLLECTION_WRITE_DENIED"


def test_knowledge_scopes_and_structured_queries_follow_collection_access(db_session):
    workspace = Workspace(
        id="ws-knowledge-access",
        name="Knowledge Access",
        slug="knowledge-access",
        settings={"knowledge_scopes": []},
    )
    db_session.add(workspace)
    viewer = _member(
        db_session,
        workspace,
        user_id="scope-viewer",
        role_template="workspace_viewer",
    )
    open_collection = create_collection(db_session, workspace=workspace, name="Open")
    hidden = create_collection(db_session, workspace=workspace, name="Hidden")
    hidden.access = {"read": ["role:workspace_admin"], "write": ["role:workspace_admin"]}
    workspace.settings = {
        "knowledge_scopes": [
            {
                "key": "mixed",
                "label": "Mixed",
                "collection_slugs": [open_collection.slug, hidden.slug],
                "is_default": True,
            }
        ]
    }
    db_session.commit()
    client = _knowledge_client(db_session, workspace, viewer.id)

    scopes = client.get("/knowledge/scopes")
    assert scopes.status_code == 200
    assert [item["slug"] for item in scopes.json()["scopes"][0]["collections"]] == [open_collection.slug]

    direct = client.post("/knowledge/table-query", json={
        "collection_or_scope": hidden.slug,
        "question": "What is hidden?",
    })
    assert direct.status_code == 403


def test_admin_can_restrict_collections_and_open_collections_stay_unchanged(db_session):
    workspace = Workspace(id="ws-admin", name="Admin", slug="admin")
    db_session.add(workspace)
    _member(db_session, workspace, user_id="admin", role_template="workspace_admin")
    collection = create_collection(db_session, workspace=workspace, name="Contracts")
    db_session.commit()
    client = _client(db_session, workspace, "admin")

    patched = client.patch(
        f"/documents/collections/{collection.id}",
        json={"access": {"read": ["user:admin"], "write": ["user:admin"]}},
    )

    assert patched.status_code == 200
    assert patched.json()["access"] == {
        "read": ["user:admin"],
        "write": ["user:admin"],
    }
    assert patched.json()["permissions"]["can_manage"] is True

    response = _client(db_session, workspace, "admin").get("/documents/collections")
    assert response.status_code == 200
    assert response.json()["collections"] == [collection.slug]


def test_chat_retrieval_scope_follows_collection_access(db_session):
    workspace = Workspace(id="ws-chat-access", name="Chat Access", slug="chat-access")
    db_session.add(workspace)
    viewer = _member(
        db_session,
        workspace,
        user_id="chat-viewer",
        role_template="workspace_viewer",
    )
    open_collection = create_collection(db_session, workspace=workspace, name="Open")
    hidden = create_collection(db_session, workspace=workspace, name="Hidden")
    hidden.access = {"read": ["role:workspace_admin"], "write": ["role:workspace_admin"]}
    db_session.commit()

    request_dict = {"retrieval_filters": {"collection_slug": hidden.slug}}
    with pytest.raises(HTTPException) as denied:
        chat._apply_collection_access(
            db_session,
            workspace=workspace,
            user=SimpleNamespace(id=viewer.id),
            request_dict=request_dict,
        )
    assert denied.value.status_code == 403

    request_dict = {}
    chat._apply_collection_access(
        db_session,
        workspace=workspace,
        user=SimpleNamespace(id=viewer.id),
        request_dict=request_dict,
    )
    assert hidden.slug not in request_dict["accessible_collection_refs"]
    assert open_collection.slug in request_dict["accessible_collection_refs"]
