"""Search must hide names as well as content when the principal cannot open them."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import navigation_search
from app.models.connector_connection import ConnectorConnection
from app.models.knowledge_collection import KnowledgeCollection, KnowledgeCollectionSource
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def seed_workspace(db):
    workspace = Workspace(id="search-a", slug="search-a", name="Workspace A", is_active=True)
    other = Workspace(id="search-b", slug="search-b", name="Workspace B", is_active=True)
    user = User(
        id="search-reader", username="search-reader", email="search@example.test", is_active=True
    )
    db.add_all([workspace, other, user])
    db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="member",
            role_template="workspace_viewer",
        )
    )
    db.commit()
    return workspace, other, user


def collection(db, workspace, row_id, name, access=None):
    row = KnowledgeCollection(
        id=row_id,
        workspace_id=workspace.id,
        name=name,
        slug=row_id,
        vector_collection_name=row_id,
        artifact_prefix=f"local/{row_id}",
        access=access,
    )
    db.add(row)
    db.flush()
    return row


def search(db, workspace, user, q="needle", limit=30):
    return navigation_search.search(q=q, limit=limit, workspace=workspace, user=user, db=db)


def test_search_hides_private_and_cross_workspace_names_before_limit(db_session):
    workspace, other, user = seed_workspace(db_session)
    private = collection(
        db_session, workspace, "private", "A needle private", {"read": ["role:workspace_admin"]}
    )
    public = collection(db_session, workspace, "public", "Z needle public")
    collection(db_session, other, "other", "needle other workspace")
    db_session.add(
        KnowledgeCollectionSource(
            workspace_id=workspace.id,
            collection_id=private.id,
            filename="needle-secret.pdf",
            normalized_name="needle-secret.pdf",
            status="ready",
        )
    )
    db_session.commit()
    result = search(db_session, workspace, user, limit=1)
    assert [row["id"] for row in result["results"]] == [public.id]
    assert result["has_more"] is False, "hidden matches cannot leak through a count"
    assert search(db_session, workspace, user, q="needle-secret.pdf")["results"] == []


def test_document_result_uses_parent_access_and_encoded_destination(db_session):
    workspace, _, user = seed_workspace(db_session)
    row = collection(db_session, workspace, "public", "Team material")
    db_session.add(
        KnowledgeCollectionSource(
            id="doc-1",
            workspace_id=workspace.id,
            collection_id=row.id,
            filename="needle & notes.pdf",
            normalized_name="needle-notes.pdf",
            status="ready",
        )
    )
    db_session.commit()
    result = search(db_session, workspace, user)["results"]
    assert len(result) == 1
    assert result[0]["kind"] == "document"
    assert result[0]["workspace"]["slug"] == workspace.slug
    assert result[0]["route"] == "/knowledge/public?facet=sources&q=needle+%26+notes.pdf"


def test_connection_result_exposes_no_configuration_or_secret(db_session, monkeypatch):
    workspace, _, user = seed_workspace(db_session)
    monkeypatch.setattr(navigation_search.settings, "connector_framework_enabled", True)
    db_session.add(
        ConnectorConnection(
            id="conn-1",
            workspace_id=workspace.id,
            name="needle connection",
            profile_key="postgresql",
            profile_version=1,
            created_by=user.id,
            values={"host": "internal.example"},
            secret_refs={"password": "secret-ref"},
        )
    )
    db_session.commit()
    result = search(db_session, workspace, user)
    assert result["results"][0]["route"] == "/connectors/connections?connection_id=conn-1"
    assert "internal.example" not in str(result)
    assert "secret-ref" not in str(result)
    monkeypatch.setattr(navigation_search.settings, "connector_framework_enabled", False)
    assert search(db_session, workspace, user)["results"] == []


def test_nonmember_has_no_search_access_and_wildcards_are_literal(db_session):
    workspace, other, user = seed_workspace(db_session)
    collection(db_session, workspace, "public", "needle ordinary")
    db_session.commit()
    assert search(db_session, workspace, user, q="%_")["results"] == []
    with pytest.raises(HTTPException) as failed:
        search(db_session, other, user)
    assert failed.value.status_code == 403
