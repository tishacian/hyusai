"""The BRD import endpoint: who may read a document, and what reading yields.

The endpoint parses and returns. It is behind the authoring boundary because
its only use is drafting a Skill, and it creates nothing at all -- the two
properties the tests below hold in place.
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
