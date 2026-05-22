from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import knowledge
from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.knowledge_table_fact import KnowledgeTableFact
from app.models.user import User
from app.models.workspace import Workspace


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
    db_session.add_all([user, workspace, collection])
    db_session.commit()
    return workspace, user, collection


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
