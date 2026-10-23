"""Review sets API: gate, reviewer restriction, decide flow, export, isolation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import auth, review_sets
from app.core.auth import get_current_workspace
from app.core.config import settings
from app.core.iam.roles import WORKSPACE_OWNER
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(settings, "review_sets_enabled", True)


@pytest.fixture()
def seed(db_session):
    def user():
        row = User(
            id=str(uuid4()),
            username=f"rv-{uuid4().hex[:8]}",
            email=f"rv-{uuid4().hex[:8]}@example.test",
            role="user",
        )
        db_session.add(row)
        return row

    ws = Workspace(id=str(uuid4()), name="Review", slug=f"rv-{uuid4().hex[:8]}", settings={})
    other = Workspace(id=str(uuid4()), name="Other", slug=f"rv-{uuid4().hex[:8]}", settings={})
    db_session.add_all([ws, other])
    owner, reviewer, outsider = user(), user(), user()
    db_session.flush()
    db_session.add_all(
        [
            WorkspaceMember(
                workspace_id=ws.id, user_id=owner.id, role="owner", role_template=WORKSPACE_OWNER
            ),
            WorkspaceMember(workspace_id=ws.id, user_id=reviewer.id, role="member"),
            WorkspaceMember(workspace_id=ws.id, user_id=outsider.id, role="member"),
            WorkspaceMember(
                workspace_id=other.id, user_id=owner.id, role="owner", role_template=WORKSPACE_OWNER
            ),
        ]
    )
    db_session.commit()
    return {"ws": ws, "other": other, "owner": owner, "reviewer": reviewer, "outsider": outsider}


def _client(db_session, workspace, user):
    app = FastAPI()
    app.include_router(review_sets.router, prefix="/review-sets")
    app.dependency_overrides[auth.get_current_user] = lambda: user
    app.dependency_overrides[get_current_workspace] = lambda: workspace
    app.dependency_overrides[auth.get_db] = lambda: db_session
    return TestClient(app)


def _open(client, reviewers):
    return client.post(
        "/review-sets",
        json={
            "namespace": "translation.segment",
            "group_key": "lot-7:it",
            "group_labels": {"lot": "lot-7", "language": "it"},
            "title": "Lot 7 Italian",
            "reviewers": reviewers,
            "taxonomy": {
                "categories": [{"key": "SP", "severities": ["minor", "major"]}],
                "comment_required_for": ["major"],
            },
            "items": [
                {"item_ref": "s1", "subject": {"source": "Roue", "candidate": "Ruota"}},
                {"item_ref": "s2", "subject": {"source": "Pneu", "candidate": "Pneumatico"}},
            ],
        },
    )


def test_disabled_feature_has_no_routes(db_session, seed, monkeypatch):
    monkeypatch.setattr(settings, "review_sets_enabled", False)
    assert _client(db_session, seed["ws"], seed["owner"]).get("/review-sets").status_code == 404


def test_reviewer_flow_and_restriction(db_session, seed):
    owner = _client(db_session, seed["ws"], seed["owner"])
    opened = _open(owner, [seed["reviewer"].id])
    assert opened.status_code == 201, opened.text
    set_id = opened.json()["id"]
    reviewer = _client(db_session, seed["ws"], seed["reviewer"])
    outsider = _client(db_session, seed["ws"], seed["outsider"])
    assert [s["id"] for s in reviewer.get("/review-sets").json()] == [set_id]
    assert outsider.get("/review-sets").json() == []
    assert outsider.get(f"/review-sets/{set_id}").status_code == 403
    items = reviewer.get(f"/review-sets/{set_id}/items").json()["items"]
    first = items[0]
    assert reviewer.post(f"/review-sets/items/{first['id']}/claim").status_code == 200
    missing_comment = reviewer.post(
        f"/review-sets/items/{first['id']}/decide",
        json={
            "revision": 0,
            "decision": "correct",
            "value": "Ruota anteriore",
            "annotations": [{"category": "SP", "severity": "major"}],
        },
    )
    assert missing_comment.json()["detail"]["code"] == "REVIEW_COMMENT_REQUIRED"
    done = reviewer.post(
        f"/review-sets/items/{first['id']}/decide",
        json={
            "revision": 0,
            "decision": "correct",
            "value": "Ruota anteriore",
            "comment": "ok",
            "annotations": [{"category": "SP", "severity": "major"}],
            "duration_ms": 1500,
        },
    )
    assert done.json()["status"] == "correct"
    history = reviewer.get(f"/review-sets/items/{first['id']}").json()["history"]
    assert history[0]["value"] == "Ruota anteriore"
    bulk = reviewer.post(f"/review-sets/{set_id}/bulk-approve", json={"item_ids": [items[1]["id"]]})
    assert bulk.json()["approved"] == [items[1]["id"]]
    summary = owner.get(f"/review-sets/{set_id}").json()
    assert (summary["decided_count"], summary["completed_at"] is not None) == (2, True)
    assert reviewer.get(f"/review-sets/{set_id}/export.csv").status_code == 403
    exported = owner.get(f"/review-sets/{set_id}/export.csv")
    assert exported.status_code == 200 and "Ruota anteriore" in exported.text


def test_other_workspace_sees_nothing(db_session, seed):
    owner = _client(db_session, seed["ws"], seed["owner"])
    set_id = _open(owner, None).json()["id"]
    foreign = _client(db_session, seed["other"], seed["owner"])
    assert foreign.get(f"/review-sets/{set_id}").status_code == 404
    assert foreign.get("/review-sets").json() == []
    item_id = owner.get(f"/review-sets/{set_id}/items").json()["items"][0]["id"]
    assert foreign.post(f"/review-sets/items/{item_id}/claim").status_code == 404
