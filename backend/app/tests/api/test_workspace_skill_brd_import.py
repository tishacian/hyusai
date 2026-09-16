"""The BRD import endpoint: who may read a document, and what reading yields.

The endpoint parses and returns. It is behind the authoring boundary because
its only use is drafting a Skill, and retention is opt-in. It creates no executable objects.
"""
from __future__ import annotations

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import skills
from app.models.skill import Skill
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

docx = pytest.importorskip("docx")


def _client(db, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(skills.router, prefix="/skills")
    app.dependency_overrides[skills.get_current_workspace] = lambda: workspace
    app.dependency_overrides[skills.get_current_user] = lambda: user
    app.dependency_overrides[skills.get_db] = lambda: db
    return TestClient(app)


def _seed(db, *, role_template: str = "workspace_admin"):
    workspace = Workspace(id="ws-brd", slug="brd", name="Brd", settings={})
    user = User(id="brd-user", username="brd-user")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template=role_template,
    )
    db.add_all([workspace, user, member])
    db.commit()
    return workspace, user


def _brd() -> bytes:
    document = docx.Document()
    table = document.add_table(rows=2, cols=4)
    for column, text in enumerate(["ID", "Requirement", "Priority (M/S/C/W)", "Maps to capability"]):
        table.cell(0, column).text = text
    for column, text in enumerate(["FR-1", "Draft a reply", "M", "Ticket triage"]):
        table.cell(1, column).text = text
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _upload(client, data: bytes, name: str = "brd.docx"):
    return client.post(
        "/skills/import/business-requirements",
        files={"file": (name, data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )


def test_an_admin_reads_the_requirements_and_nothing_is_created(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = _upload(client, _brd())

    assert response.status_code == 200
    body = response.json()
    assert body["requirements"] == [
        {
            "id": "FR-1",
            "requirement": "Draft a reply",
            "priority": "M",
            "capability": "Ticket triage",
        }
    ]
    assert db_session.query(Skill).count() == 0


def test_a_member_who_cannot_author_cannot_read_either(db_session):
    workspace, user = _seed(db_session, role_template="workspace_viewer")
    client = _client(db_session, workspace, user)

    assert _upload(client, _brd()).status_code == 403


def test_a_file_that_is_not_a_document_is_refused_with_a_reason(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = _upload(client, b"not a docx at all", name="notes.txt")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "brd_document_unreadable"


def test_an_oversized_upload_is_refused_before_it_is_parsed(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    response = _upload(client, b"0" * (5 * 1024 * 1024 + 1))

    assert response.status_code == 413


def test_retained_original_round_trip_replay_and_workspace_boundary(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.brd_document import BrdDocument
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    data = _brd()
    def upload():
        return client.post("/skills/import/business-requirements?retain=true",
                           files={"file": ("../requirements.docx", data)})
    first = upload()
    assert first.status_code == 200
    document = first.json()["document"]
    assert document["filename"] == "requirements.docx"
    document_id = document["id"]
    assert upload().json()["document"]["id"] == document_id
    assert db_session.query(BrdDocument).count() == 1
    assert db_session.query(Skill).count() == 0
    path = f"/skills/imports/business-requirements/{document_id}"
    assert client.get(path).json()["requirements"] == first.json()["requirements"]
    assert client.get(path + "/original").content == data

    other = Workspace(id="other-brd", slug="other-brd", name="Other", settings={})
    db_session.add(other)
    db_session.add(WorkspaceMember(workspace_id=other.id, user_id=user.id,
                                   role="member", role_template="workspace_admin"))
    db_session.commit()
    other_client = _client(db_session, other, user)
    assert other_client.get(path).status_code == 404
    assert other_client.get(path + "/original").status_code == 404

    member = db_session.query(WorkspaceMember).filter_by(workspace_id=workspace.id).one()
    member.role_template = "workspace_viewer"
    db_session.commit()
    assert client.get(path).status_code == 403
    assert client.get(path + "/original").status_code == 403
    assert upload().status_code == 403


def test_retained_original_missing_or_modified_is_not_presented_as_evidence(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.brd_document import BrdDocument
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    response = client.post("/skills/import/business-requirements?retain=true",
                           files={"file": ("requirements.docx", _brd())})
    assert response.status_code == 200
    row = db_session.query(BrdDocument).one()
    path = f"/skills/imports/business-requirements/{row.id}/original"
    original = tmp_path / row.storage_key
    original.write_bytes(b"changed")
    assert client.get(path).json()["detail"]["code"] == "brd_original_integrity_error"
    original.unlink()
    assert client.get(path).status_code == 410


def test_proposal_preserves_uncovered_requirements_and_never_creates_system(db_session, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.models.system import System
    from app.models.brd_proposal import BrdProposal
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path))
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    document_id = client.post("/skills/import/business-requirements?retain=true",
                             files={"file": ("brd.docx", _brd())}).json()["document"]["id"]
    path = f"/skills/imports/business-requirements/{document_id}/proposals"
    body = {
        "request_key": "first-proposal", "name": "Ticket draft",
        "flow_definition": {"schema_version": 3, "nodes": [
            {"id": "input", "type": "source", "kind": "source"},
            {"id": "result", "type": "sink", "kind": "sink"},
        ], "edges": [{"from": "input", "to": "result", "kind": "data"}]},
    }
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["proposal"]["coverage"][0]["status"] == "uncovered"
    assert first["proposal"]["coverage"][0]["test_verdict"] == "not_run"
    assert first["proposal"]["execution_readiness"] == "not_validated"
    assert client.post(path, json=body).json()["id"] == first["id"]
    assert client.get(path + "/" + first["id"]).json() == first
    assert db_session.query(BrdProposal).count() == 1
    assert db_session.query(System).count() == 0
    assert db_session.query(Skill).count() == 0
    assert client.post(path, json={**body, "name": "Changed"}).status_code == 409

    mapped = {**body, "request_key": "second-proposal", "mappings": [
        {"table": 1, "row": 2, "node_ids": ["result"], "case_ids": ["t1"]}],
        "cases": [{"id": "t1", "input_ref": {}, "assertions": []}]}
    second = client.post(path, json=mapped)
    assert second.status_code == 200, second.text
    assert second.json()["proposal"]["coverage"][0]["status"] == "proposed"
    assert second.json()["proposal"]["coverage"][0]["test_verdict"] == "not_run"
    mapped["mappings"][0]["node_ids"] = ["invented"]
    assert client.post(path, json=mapped).status_code == 422
    mapped["mappings"][0]["node_ids"] = ["result"]
    mapped["mappings"][0]["row"] = 99
    assert client.post(path, json=mapped).status_code == 422
