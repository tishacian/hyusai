"""L34 — a client workspace walks its own sources; Showcase keeps NorthForge.

The journey and its availability are decided server-side: available only when
the member can read a collection of *this* workspace (ready or indexing) or
fill one, never by redirecting to the Showcase example.
"""
from app.models.audit import AuditLog
from app.models.knowledge_collection import KnowledgeCollection
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.tests.api.test_adoption_roadmap import auth_client
from app.tests.api.test_assistant_turns_api import _seed

URL = "/auth/workspaces/assistant-api/me/experience"


def _collection(db, workspace_id, cid, name, status, documents=0, chunks=0, slug=None):
    row = KnowledgeCollection(
        id=cid,
        workspace_id=workspace_id,
        slug=slug or cid,
        name=name,
        status=status,
        document_count=documents,
        chunk_count=chunks,
        vector_collection_name=f"vec-{cid}",
        artifact_prefix=f"artifacts/{cid}",
    )
    db.add(row)
    return row


def _seed_sources(db, workspace):
    # Created first but empty: the ready collection with passages still leads.
    _collection(db, workspace.id, "c-empty", "Brouillons", "created")
    _collection(db, workspace.id, "c-failed", "Archives", "error", documents=2)
    _collection(db, workspace.id, "c-indexing", "Procédures", "ingesting", documents=3, chunks=40)
    _collection(db, workspace.id, "c-ready", "Contrats fournisseurs", "ready", documents=14, chunks=3480)
    _collection(db, workspace.id, "c-internal", "Internal", "ready", documents=1, chunks=5, slug="_internal")
    db.commit()


def _set_role(db, user, template, legacy="member"):
    member = db.query(WorkspaceMember).filter_by(user_id=user.id).one()
    member.role = legacy
    member.role_template = template
    db.commit()
    return member


def test_a_contributor_gets_the_client_journey_on_this_workspace_sources(db_session):
    workspace, user = _seed(db_session)
    _seed_sources(db_session, workspace)
    body = auth_client(db_session, workspace, user).get(URL).json()

    assert body["journey"] == "client_sources"
    assert body["available"] is True
    assert body["example_available"] is False
    assert body["can_add_documents"] is True
    ids = [source["id"] for source in body["sources"]]
    # Ready with passages, then indexing, then the ones a contributor can fill.
    assert ids[:2] == ["c-ready", "c-indexing"]
    assert set(ids) == {"c-ready", "c-indexing", "c-empty", "c-failed"}
    assert "c-internal" not in ids
    assert body["candidate_collection_id"] == "c-ready"
    ready = body["sources"][0]
    assert ready == {
        "id": "c-ready",
        "slug": "c-ready",
        "name": "Contrats fournisseurs",
        "status": "ready",
        "document_count": 14,
        "chunk_count": 3480,
    }


def test_a_viewer_only_sees_what_they_can_read_and_nothing_else_makes_it_available(db_session):
    workspace, user = _seed(db_session)
    _set_role(db_session, user, "workspace_viewer")
    _seed_sources(db_session, workspace)
    client = auth_client(db_session, workspace, user)
    body = client.get(URL).json()
    assert body["can_add_documents"] is False
    assert [source["id"] for source in body["sources"]] == ["c-ready", "c-indexing"]

    # Only empty or failed collections: nothing to read, nothing they may fill.
    for cid in ("c-ready", "c-indexing", "c-internal"):
        db_session.query(KnowledgeCollection).filter_by(id=cid).delete()
    db_session.commit()
    body = client.get(URL).json()
    assert body["available"] is False
    assert body["sources"] == []
    assert body["candidate_collection_id"] is None


def test_an_indexing_collection_is_enough_for_a_viewer(db_session):
    workspace, user = _seed(db_session)
    _set_role(db_session, user, "workspace_viewer")
    _collection(db_session, workspace.id, "c-indexing", "Procédures", "embedding", documents=3)
    db_session.commit()
    body = auth_client(db_session, workspace, user).get(URL).json()
    assert body["available"] is True
    assert body["candidate_collection_id"] == "c-indexing"


def test_no_collection_means_no_journey_even_for_an_admin(db_session):
    workspace, user = _seed(db_session)
    _set_role(db_session, user, "workspace_admin", legacy="admin")
    body = auth_client(db_session, workspace, user).get(URL).json()
    assert body["journey"] == "client_sources"
    assert body["available"] is False
    assert body["sources"] == []


def test_client_steps_are_idempotent_resume_on_the_chosen_source_and_are_audited(db_session):
    workspace, user = _seed(db_session)
    _seed_sources(db_session, workspace)
    client = auth_client(db_session, workspace, user)

    for _ in range(2):
        response = client.patch(URL, json={"completed_step": "source", "collection_id": "c-indexing"})
        assert response.status_code == 200, response.text
    for step in ["documents", "question", "decision", "decision"]:
        assert client.patch(URL, json={"completed_step": step}).status_code == 200

    body = client.get(URL).json()
    assert body["completed_steps"] == ["source", "documents", "question", "decision"]
    assert body["collection_id"] == "c-indexing"
    # The member's choice wins over the first ready collection when resuming.
    assert body["candidate_collection_id"] == "c-indexing"

    # NorthForge steps are not part of this journey.
    for foreign_step in ["example", "result"]:
        assert client.patch(URL, json={"completed_step": foreign_step}).status_code == 422
    assert client.patch(URL, json={"completed_step": "approve"}).status_code == 422
    assert client.get(URL).json()["completed_steps"] == ["source", "documents", "question", "decision"]

    audited = [row.details for row in db_session.query(AuditLog).filter_by(event_type="adoption.progress")]
    assert audited and all(row["journey"] == "client_sources" for row in audited)
    assert audited[0]["collection_id"] == "c-indexing"


def test_a_source_must_belong_to_this_workspace_and_be_usable_by_the_member(db_session):
    workspace, user = _seed(db_session)
    _seed_sources(db_session, workspace)
    foreign = Workspace(id="ws-foreign", slug="foreign", name="Foreign")
    db_session.add(foreign)
    db_session.commit()
    _collection(db_session, foreign.id, "c-foreign", "Leur corpus", "ready", documents=9, chunks=90)
    db_session.commit()
    client = auth_client(db_session, workspace, user)

    for cid in ("c-foreign", "c-internal", "missing"):
        response = client.patch(URL, json={"completed_step": "source", "collection_id": cid})
        assert response.status_code == 404, cid
    body = client.get(URL).json()
    assert body["completed_steps"] == []
    assert body["collection_id"] is None
    assert "c-foreign" not in [source["id"] for source in body["sources"]]

    # A viewer cannot pick a collection they could only fill.
    _set_role(db_session, user, "workspace_viewer")
    assert client.patch(URL, json={"collection_id": "c-empty"}).status_code == 404
    assert client.patch(URL, json={"collection_id": "c-ready"}).status_code == 200

    # A member of another workspace sees none of this one's sources.
    stranger = User(id="stranger", username="stranger@example.test")
    db_session.add_all([stranger, WorkspaceMember(user_id=stranger.id, workspace_id=foreign.id, role="member")])
    db_session.commit()
    assert auth_client(db_session, foreign, stranger).get(URL).status_code == 403


def test_a_northforge_record_left_in_a_client_workspace_does_not_count(db_session):
    workspace, user = _seed(db_session)
    _seed_sources(db_session, workspace)
    member = db_session.query(WorkspaceMember).filter_by(user_id=user.id).one()
    member.experience_progress = {
        "journey": "northforge_sources",
        "completed_steps": ["example", "question", "source"],
        "dismissed": True,
        "persona": "builder",
        "rail_labels": "shown",
    }
    db_session.commit()
    client = auth_client(db_session, workspace, user)

    body = client.get(URL).json()
    assert body["journey"] == "client_sources"
    assert body["completed_steps"] == [], "« source » and « question » there meant the example"
    assert body["dismissed"] is False, "hiding the example did not hide the member's own sources"
    assert body["persona"] == "builder" and body["rail_labels"] == "shown"

    assert client.patch(URL, json={"completed_step": "source", "collection_id": "c-ready"}).status_code == 200
    stored = db_session.query(WorkspaceMember).filter_by(user_id=user.id).one().experience_progress
    assert stored["journey"] == "client_sources"
    assert stored["completed_steps"] == ["source"]


def test_showcase_keeps_the_northforge_journey_unchanged(db_session):
    showcase = Workspace(id="ws-showcase", slug="agentium-showcase", name="Agentium Showcase")
    user = User(id="user-showcase", username="showcase@example.test")
    db_session.add_all(
        [
            showcase,
            user,
            WorkspaceMember(
                user_id=user.id, workspace_id=showcase.id, role="member", role_template="workspace_contributor"
            ),
        ]
    )
    db_session.commit()
    client = auth_client(db_session, showcase, user)
    url = "/auth/workspaces/agentium-showcase/me/experience"

    body = client.get(url).json()
    assert body["journey"] == "northforge_sources"
    assert body["available"] is False and body["example_available"] is False
    assert "sources" not in body

    _collection(
        db_session, showcase.id, "c-notices", "Notices", "ready", documents=12, chunks=300,
        slug="agentium-showcase-notices",
    )
    db_session.commit()
    body = client.get(url).json()
    assert body["available"] is True and body["example_available"] is True

    for step in ["example", "question", "source", "result", "result"]:
        assert client.patch(url, json={"completed_step": step}).status_code == 200
    assert client.patch(url, json={"completed_step": "documents"}).status_code == 422
    assert client.patch(url, json={"completed_step": "decision"}).status_code == 422
    assert client.get(url).json()["completed_steps"] == ["example", "question", "source", "result"]
