from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import knowledge
from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/knowledge")
    app.dependency_overrides[knowledge.get_current_workspace] = lambda: workspace
    app.dependency_overrides[knowledge.get_current_user] = lambda: user
    app.dependency_overrides[knowledge.get_db] = lambda: db_session
    return TestClient(app)


def _seed_workspace(db_session) -> tuple[Workspace, User, KnowledgeCollection]:
    user = User(id="user-guide", username="guide@datategy.test", email="guide@datategy.test")
    workspace = Workspace(
        id="ws-guide",
        name="Guide",
        slug="guide",
        settings={
            "knowledge_scopes": [
                {
                    "key": "excel_pilot",
                    "label": "Excel pilot",
                    "collection_slugs": ["excel-pilot"],
                    "default_mode": "chah",
                    "top_k": 5,
                    "is_default": True,
                }
            ]
        },
    )
    collection = KnowledgeCollection(
        id="collection-guide",
        workspace_id=workspace.id,
        slug="excel-pilot",
        name="Excel Pilot",
        vector_collection_name="guide_excel_pilot",
        artifact_prefix="knowledge/ws-guide/excel-pilot",
    )
    db_session.add_all(
        [
            user,
            workspace,
            collection,
            WorkspaceMember(
                user_id=user.id,
                workspace_id=workspace.id,
                role="admin",
                role_template="workspace_admin",
            ),
        ]
    )
    db_session.commit()
    return workspace, user, collection


def _add_member(
    db_session,
    workspace: Workspace,
    *,
    user_id: str,
    role: str = "member",
    role_template: str | None = "workspace_contributor",
) -> User:
    user = User(id=user_id, username=f"{user_id}@datategy.test", email=f"{user_id}@datategy.test")
    db_session.add(user)
    db_session.add(
        WorkspaceMember(
            user_id=user.id,
            workspace_id=workspace.id,
            role=role,
            role_template=role_template,
        )
    )
    db_session.commit()
    return user


def test_knowledge_guide_collection_lifecycle_is_versioned_and_audited(db_session):
    workspace, user, _collection = _seed_workspace(db_session)
    client = _client(db_session, workspace, user)

    response = client.post(
        "/knowledge/guides",
        json={
            "target_type": "collection",
            "target_ref": "excel-pilot",
            "title": "Excel data dictionary",
            "markdown": "Column A contains labels. Column B contains values.",
            "status": "published",
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["version"] == 1
    assert created["status"] == "published"
    assert created["target_ref"] == "excel-pilot"

    effective = client.get("/knowledge/guides/effective?collection_slug=excel-pilot")
    assert effective.status_code == 200
    assert effective.json()["items"][0]["title"] == "Excel data dictionary"

    patched = client.patch(
        f"/knowledge/guides/{created['guide_key']}",
        json={"markdown": "Column A contains labels. Column B contains numeric values."},
    )
    assert patched.status_code == 200
    updated = patched.json()
    assert updated["guide_key"] == created["guide_key"]
    assert updated["version"] == 2
    assert updated["markdown"].endswith("numeric values.")

    all_versions = client.get("/knowledge/guides?current_only=false").json()["items"]
    assert [item["version"] for item in all_versions] == [1, 2]
    assert [item["is_current"] for item in all_versions] == [False, True]

    events = [row.event_type for row in db_session.query(AuditLog).order_by(AuditLog.timestamp).all()]
    assert "knowledge.guide.created" in events
    assert "knowledge.guide.updated" in events


def test_publishing_draft_knowledge_guide_updates_effective_guide(db_session):
    workspace, user, _collection = _seed_workspace(db_session)
    client = _client(db_session, workspace, user)

    created = client.post(
        "/knowledge/guides",
        json={
            "target_type": "collection",
            "target_ref": "excel-pilot",
            "title": "Draft guide",
            "markdown": "Draft interpretation.",
            "status": "draft",
        },
    )

    assert created.status_code == 200
    draft = created.json()
    assert draft["status"] == "draft"
    assert draft["published_at"] is None

    initial_effective = client.get("/knowledge/guides/effective?collection_slug=excel-pilot")
    assert initial_effective.status_code == 200
    assert initial_effective.json()["items"] == []

    published = client.patch(
        f"/knowledge/guides/{draft['guide_key']}",
        json={"status": "published", "markdown": "Published interpretation."},
    )

    assert published.status_code == 200
    published_body = published.json()
    assert published_body["status"] == "published"
    assert published_body["version"] == 2
    assert published_body["published_at"] is not None

    effective = client.get("/knowledge/guides/effective?collection_slug=excel-pilot")
    assert effective.status_code == 200
    items = effective.json()["items"]
    assert len(items) == 1
    assert items[0]["guide_key"] == draft["guide_key"]
    assert items[0]["markdown"] == "Published interpretation."


def test_knowledge_guide_scope_target_requires_existing_scope(db_session):
    workspace, user, _collection = _seed_workspace(db_session)
    client = _client(db_session, workspace, user)

    response = client.post(
        "/knowledge/guides",
        json={
            "target_type": "scope",
            "target_ref": "excel_pilot",
            "title": "Scope guide",
            "markdown": "Use this scope for Excel parameter lookups.",
            "status": "published",
        },
    )
    assert response.status_code == 200

    effective = client.get("/knowledge/guides/effective?knowledge_scope=excel_pilot")
    assert effective.status_code == 200
    assert effective.json()["items"][0]["target_type"] == "scope"

    missing = client.post(
        "/knowledge/guides",
        json={
            "target_type": "scope",
            "target_ref": "missing",
            "title": "Missing",
            "markdown": "Nope",
            "status": "draft",
        },
    )
    assert missing.status_code == 404


def test_contributor_cannot_create_or_patch_knowledge_guides(db_session):
    workspace, admin_user, _collection = _seed_workspace(db_session)
    contributor = _add_member(db_session, workspace, user_id="guide-contributor")
    admin_client = _client(db_session, workspace, admin_user)
    contributor_client = _client(db_session, workspace, contributor)

    created = admin_client.post(
        "/knowledge/guides",
        json={
            "target_type": "collection",
            "target_ref": "excel-pilot",
            "title": "Excel data dictionary",
            "markdown": "Column A contains labels.",
            "status": "published",
        },
    )
    assert created.status_code == 200
    guide_key = created.json()["guide_key"]

    denied_create = contributor_client.post(
        "/knowledge/guides",
        json={
            "target_type": "collection",
            "target_ref": "excel-pilot",
            "title": "Unauthorized guide",
            "markdown": "This should not be stored.",
            "status": "published",
        },
    )
    assert denied_create.status_code == 403

    denied_patch = contributor_client.patch(
        f"/knowledge/guides/{guide_key}",
        json={"markdown": "Unauthorized edit."},
    )
    assert denied_patch.status_code == 403

    versions = admin_client.get("/knowledge/guides?current_only=false").json()["items"]
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert versions[0]["markdown"] == "Column A contains labels."


def test_contributor_cannot_patch_knowledge_scopes(db_session):
    workspace, _admin_user, _collection = _seed_workspace(db_session)
    contributor = _add_member(db_session, workspace, user_id="scope-contributor")
    client = _client(db_session, workspace, contributor)
    original_scopes = list((workspace.settings or {}).get("knowledge_scopes") or [])

    response = client.patch(
        "/knowledge/scopes",
        json={
            "scopes": [
                {
                    "key": "unauthorized_scope",
                    "label": "Unauthorized",
                    "collection_slugs": ["excel-pilot"],
                    "is_default": True,
                }
            ]
        },
    )

    assert response.status_code == 403
    db_session.refresh(workspace)
    assert (workspace.settings or {}).get("knowledge_scopes") == original_scopes


def test_patch_knowledge_scopes_rejects_invalid_scope_without_mutation(db_session, monkeypatch):
    workspace, admin_user, _collection = _seed_workspace(db_session)
    client = _client(db_session, workspace, admin_user)
    original_scopes = list((workspace.settings or {}).get("knowledge_scopes") or [])

    def fail_if_system_refresh_runs(*args, **kwargs):
        raise AssertionError("invalid scopes must not refresh chat system defaults")

    monkeypatch.setattr(knowledge, "ensure_workspace_chat_system_default", fail_if_system_refresh_runs)

    response = client.patch(
        "/knowledge/scopes",
        json={
            "scopes": [
                {
                    "key": "invalid scope key",
                    "label": "Invalid",
                    "collection_slugs": ["excel-pilot"],
                    "is_default": True,
                }
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid knowledge scope"
    db_session.refresh(workspace)
    assert (workspace.settings or {}).get("knowledge_scopes") == original_scopes


def test_table_query_endpoint_returns_cell_evidence(db_session):
    workspace, user, collection = _seed_workspace(db_session)
    db_session.add(
        KnowledgeTableFact(
            id="fact-b",
            workspace_id=workspace.id,
            collection_id=collection.id,
            collection_slug=collection.slug,
            document_id="doc-xlsx",
            document_filename="labels.xlsx",
            sheet_name="Def strips",
            semantic_type="spreadsheet_cell_fact",
            row_index=2,
            cell_ref="B2",
            row_label="B",
            subject="B",
            measure="B",
            value_raw="85",
            value_numeric=85,
            content="sheet=Def strips | row_label=B | cell=B2 | value=85 | B = 85",
            confidence=0.8,
        )
    )
    db_session.commit()
    client = _client(db_session, workspace, user)

    response = client.post(
        "/knowledge/table-query",
        json={"collection_or_scope": "excel_pilot", "question": "Quelle est la valeur du label B ?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "lookup"
    assert body["answer_payload"]["value"] == "85"
    assert body["evidence_rows"][0]["sheet_name"] == "Def strips"
    assert body["evidence_rows"][0]["cell_ref"] == "B2"


def test_table_query_does_not_leak_hidden_workspace_collection(db_session):
    workspace, user, _collection = _seed_workspace(db_session)
    hidden_workspace = Workspace(id="ws-hidden-guide", name="Hidden", slug="hidden-guide")
    hidden_collection = KnowledgeCollection(
        id="collection-hidden-guide",
        workspace_id=hidden_workspace.id,
        slug="hidden-secret",
        name="Hidden Secret",
        vector_collection_name="hidden_secret",
        artifact_prefix="knowledge/ws-hidden-guide/hidden-secret",
    )
    db_session.add_all([hidden_workspace, hidden_collection])
    db_session.add(
        KnowledgeTableFact(
            id="fact-hidden-secret",
            workspace_id=hidden_workspace.id,
            collection_id=hidden_collection.id,
            collection_slug=hidden_collection.slug,
            document_id="hidden-xlsx",
            document_filename="hidden.xlsx",
            sheet_name="Secrets",
            semantic_type="spreadsheet_cell_fact",
            row_index=1,
            cell_ref="A1",
            row_label="Secret",
            subject="Secret",
            measure="Secret",
            value_raw="SECRET",
            content="SECRET cross-workspace value",
            confidence=0.99,
        )
    )
    db_session.commit()
    client = _client(db_session, workspace, user)

    response = client.post(
        "/knowledge/table-query",
        json={"collection_or_scope": "hidden-secret", "question": "Quelle est la valeur SECRET ?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer_payload"]["status"] == "no_evidence"
    assert body["evidence_rows"] == []
    assert "hidden.xlsx" not in str(body)
    assert "cross-workspace value" not in str(body)
