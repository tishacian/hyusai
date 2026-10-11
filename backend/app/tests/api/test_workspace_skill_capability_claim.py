"""Naming a Capability while authoring a Skill, and what happens when it fails.

A workspace-authored Skill is always visible in the catalog -- ownership is
reason enough -- but until a Capability carries it, the Flow palette files it
under "no capability" and nothing explains why. Naming the carrier at creation
is the missing link.

The rule the tests below pin down is that the link is a bonus, never a gate:
whatever the claim does, the Skill exists afterwards.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import skills
from app.models.capability import Capability
from app.models.skill import Skill
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

AUDIT_BINDING = {
    "kind": "registry_call",
    "params": {"skill_slug": "audit_log_v1", "frozen_input": {"event_type": "reset"}},
}


def _client(db, workspace, user) -> TestClient:
    app = FastAPI()
    app.include_router(skills.router, prefix="/skills")
    app.dependency_overrides[skills.get_current_workspace] = lambda: workspace
    app.dependency_overrides[skills.get_current_user] = lambda: user
    app.dependency_overrides[skills.get_db] = lambda: db
    return TestClient(app)


def _seed(db):
    workspace = Workspace(id="ws-claim", slug="claim", name="Claim", settings={})
    user = User(id="claim-user", username="claim-user")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template="workspace_admin",
    )
    owned = Capability(
        id="cap-owned",
        workspace_id=workspace.id,
        slug="ticket-triage",
        name="Ticket triage",
        skill_ids=[],
        is_seeded="N",
    )
    shared = Capability(
        id="cap-shared",
        workspace_id=None,
        slug="universal-answer",
        name="Universal answer",
        skill_ids=[],
        is_seeded="Y",
    )
    db.add_all([workspace, user, member, owned, shared])
    db.commit()
    return workspace, user


def _create(client, **overrides):
    body = {
        "local_name": "reset_ticket",
        "name": "Reset a ticket",
        "category": "Automation",
        "executor": AUDIT_BINDING,
    }
    body.update(overrides)
    return client.post("/skills", json=body)


def test_a_named_capability_carries_the_new_skill(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    created = _create(client, capability_id="cap-owned")

    assert created.status_code == 200
    row = created.json()
    assert row["capability_claim"] == {
        "attached": True,
        "capability_name": "Ticket triage",
        "reason": None,
    }
    carrier = db_session.query(Capability).filter(Capability.id == "cap-owned").one()
    assert carrier.skill_ids == [
        db_session.query(Skill).filter(Skill.slug == row["slug"]).one().id
    ]


def test_no_capability_named_leaves_the_answer_silent_on_the_subject(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    created = _create(client).json()

    assert "capability_claim" not in created


def test_the_shared_catalog_is_not_a_candidate_and_the_skill_survives(db_session):
    """A seeded Capability belongs to every workspace at once; appending to it
    here would append to it for all of them."""

    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    created = _create(client, capability_id="cap-shared")

    assert created.status_code == 200
    claim = created.json()["capability_claim"]
    assert claim["attached"] is False
    assert "id" in claim["reason"]
    # The definition was not thrown away because the link could not be made.
    assert db_session.query(Skill).filter(Skill.slug == created.json()["slug"]).one()
    shared = db_session.query(Capability).filter(Capability.id == "cap-shared").one()
    assert shared.skill_ids == []


def test_an_unknown_capability_is_refused_by_name_not_by_a_500(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    created = _create(client, capability_id="cap-nowhere")

    assert created.status_code == 200
    assert created.json()["capability_claim"]["attached"] is False


def test_claiming_twice_does_not_duplicate_the_skill_id(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    first = _create(client, capability_id="cap-owned").json()
    second = _create(client, local_name="reset_ticket_2", capability_id="cap-owned").json()

    carrier = db_session.query(Capability).filter(Capability.id == "cap-owned").one()
    by_slug = {
        row.slug: row.id
        for row in db_session.query(Skill).filter(
            Skill.slug.in_([first["slug"], second["slug"]])
        )
    }
    assert sorted(carrier.skill_ids) == sorted(by_slug.values())
