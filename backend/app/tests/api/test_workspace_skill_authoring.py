"""Authoring a Skill inside a workspace, and the boundary it sits behind.

12 skills in the registry are claimed by no capability at all, so the only lever
that ever reached them was ``enabled_skills`` -- borrowing a global row rather
than owning one. A workspace can now define its own, which is why every
constraint below is about what it still cannot do.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import skills
from app.models.capability import Capability
from app.models.run import Run, SkillInvocation
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


def _seed(db, *, role_template: str = "workspace_admin"):
    workspace = Workspace(id="ws-author", slug="author", name="Author", settings={})
    user = User(id="author-user", username="author-user")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="member",
        role_template=role_template,
    )
    seeded = Skill(
        id="skill-seeded",
        slug="causal_drill_v1",
        name="Causal drill",
        type="analysis",
        category="Analysis",
        is_seeded="Y",
    )
    db.add_all([workspace, user, member, seeded])
    db.commit()
    return workspace, user


def _create(client, **overrides):
    body = {
        "local_name": "reset_ticket",
        "name": "Reset a ticket",
        "description": "Records the reset in the ledger.",
        "category": "Automation",
        "input_schema": {"type": "object", "properties": {"details": {"type": "object"}}},
        "output_schema": {"type": "object"},
        "executor": AUDIT_BINDING,
    }
    body.update(overrides)
    return client.post("/skills", json=body)


def test_an_admin_authors_a_skill_the_workspace_immediately_sees(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    created = _create(client)

    assert created.status_code == 200
    row = created.json()
    assert row["slug"] == "ws.ws-author.reset_ticket"
    assert row["workspace_scope"] == "workspace"
    assert row["is_seeded"] is False
    assert row["executor"] == AUDIT_BINDING
    # It has a runtime, so reporting it as awaiting a wrapper would be a lie.
    assert row["runtime_status"] == "bound"

    listing = client.get("/skills").json()
    authored = next(item for item in listing["skills"] if item["slug"] == row["slug"])
    # Visible with no capability binding and no override: ownership is the reason.
    assert authored["visibility"]["reason"] == "workspace_owned"
    # And it did not need the ``enabled_skills`` escape hatch to get there.
    assert listing["catalog"]["policy"]["enabled_skills"] == []


def test_the_platform_owns_what_the_workspace_does_not_decide(db_session):
    """A row cannot assert a certification nobody granted it, claim to be seeded,
    or name its own slug."""

    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    created = _create(
        client,
        slug="causal_drill_v1",
        is_seeded=True,
        certification_level="enterprise",
        workspace_id="ws-victim",
        metrics={"calls": 9_999},
    ).json()

    assert created["slug"] == "ws.ws-author.reset_ticket"
    assert created["certification_level"] == "basic"
    assert created["is_seeded"] is False
    assert created["metrics"] == {}
    stored = db_session.query(Skill).filter(Skill.slug == created["slug"]).one()
    assert stored.workspace_id == "ws-author"


def test_a_seeded_row_is_not_editable_through_this_path(db_session):
    """Not "should not" -- the query cannot reach it, so a future caller that
    forgets the check still cannot edit the catalog every workspace shares."""

    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    assert client.patch("/skills/causal_drill_v1", json={"name": "Hijacked"}).status_code == 404
    assert client.delete("/skills/causal_drill_v1").status_code == 404
    assert db_session.query(Skill).filter(Skill.slug == "causal_drill_v1").one().name == (
        "Causal drill"
    )


def test_a_member_reads_the_catalog_but_cannot_author_in_it(db_session):
    workspace, user = _seed(db_session, role_template="workspace_contributor")
    client = _client(db_session, workspace, user)

    read = client.get("/skills")
    write = _create(client)

    assert read.status_code == 200
    assert write.status_code == 403
    assert write.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
    assert db_session.query(Skill).filter(Skill.workspace_id == workspace.id).count() == 0
    # The gate is the candidate rule even in compat, so promoting `skill.admin`
    # out of compat changes the audit trail rather than the answer.
    assert client.get("/skills/executors").json()["editable"] is False


def test_an_unusable_schema_is_refused_at_authoring_time(db_session):
    """A Skill whose contract only fails at publication is a Skill an author has
    already built a Flow on."""

    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    invalid = _create(client, input_schema={"type": "not-a-json-schema-type"})
    remote = _create(
        client,
        local_name="remote_ref",
        output_schema={"$ref": "https://example.test/schema.json"},
    )

    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "schema_invalid"
    assert remote.status_code == 400
    assert remote.json()["detail"]["code"] == "schema_remote_ref_forbidden"
    assert db_session.query(Skill).filter(Skill.workspace_id == workspace.id).count() == 0


def test_an_unverifiable_runtime_binding_is_refused_at_authoring_time(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    for executor, code in (
        ({"kind": "python_path", "params": {"path": "os.system"}}, "executor_kind_unknown"),
        ({"kind": "registry_call", "params": {}}, "executor_params_invalid"),
        (
            {"kind": "registry_call", "params": {"skill_slug": "audit_log_v1", "extra": 1}},
            "executor_params_invalid",
        ),
        (
            {"kind": "registry_call", "params": {"skill_slug": "no_such_skill_v1"}},
            "executor_target_unbound",
        ),
    ):
        response = _create(client, executor=executor)
        assert response.status_code == 400, executor
        assert response.json()["detail"]["code"] == code, executor

    assert db_session.query(Skill).filter(Skill.workspace_id == workspace.id).count() == 0


def test_a_private_taxonomy_cannot_fragment_the_palette(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    refused = _create(client, category="Our Own Section")

    assert refused.status_code == 422
    assert "Automation" in client.get("/skills/executors").json()["categories"]


def test_a_duplicate_name_is_a_conflict_rather_than_a_second_dispatch_key(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    assert _create(client).status_code == 200
    assert _create(client, name="Different display name").status_code == 409
    assert db_session.query(Skill).filter(Skill.workspace_id == workspace.id).count() == 1


def test_an_edit_changes_the_contract_but_never_the_dispatch_key(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    slug = _create(client).json()["slug"]

    updated = client.patch(
        f"/skills/{slug}",
        json={
            "name": "Reset a ticket (v2)",
            "output_schema": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
            "executor": {
                "kind": "prompt_template",
                "params": {"provider": "ollama", "template": "Draft a reply to {ticket}."},
            },
            "slug": "causal_drill_v1",
        },
    )

    assert updated.status_code == 200
    assert updated.json()["slug"] == slug
    assert updated.json()["name"] == "Reset a ticket (v2)"
    assert updated.json()["executor"]["kind"] == "prompt_template"
    assert updated.json()["output_schema"]["required"] == ["id"]


def test_an_edit_cannot_replace_a_verified_binding_with_an_unverified_one(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    slug = _create(client).json()["slug"]

    refused = client.patch(f"/skills/{slug}", json={"executor": {"kind": "shell"}})

    assert refused.status_code == 400
    assert db_session.query(Skill).filter(Skill.slug == slug).one().executor == AUDIT_BINDING


def test_a_mistake_is_deletable_and_history_is_not(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    slug = _create(client).json()["slug"]
    skill_id = _create(client, local_name="invoked_op").json()["id"]

    assert client.delete(f"/skills/{slug}").status_code == 200
    assert db_session.query(Skill).filter(Skill.slug == slug).first() is None

    run = Run(id="run-authored", workspace_id=workspace.id, status="completed")
    db_session.add_all(
        [
            run,
            SkillInvocation(
                id="invocation-authored",
                run_id=run.id,
                skill_id=skill_id,
                skill_slug="ws.ws-author.invoked_op",
                status="completed",
                cost_measured=False,
            ),
        ]
    )
    db_session.commit()

    refused = client.delete("/skills/ws.ws-author.invoked_op")
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "skill_has_run_history"


def test_a_claimed_skill_names_the_capability_holding_it(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = _create(client).json()
    db_session.add(
        Capability(
            id="cap-author",
            workspace_id=workspace.id,
            slug="ticket_operations",
            name="Ticket operations",
            skill_ids=[created["id"]],
        )
    )
    db_session.commit()

    refused = client.delete(f"/skills/{created['slug']}")

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "skill_claimed_by_capability"
    assert "ticket_operations" in refused.json()["detail"]["message"]


def test_runtime_health_reports_the_authored_runtime_it_will_actually_use(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    bound = _create(client).json()["slug"]
    db_session.add(
        Skill(
            id="skill-unbindable",
            workspace_id=workspace.id,
            slug="ws.ws-author.unbindable_op",
            name="Unbindable",
            type="generic",
            executor={"kind": "retired_kind", "params": {}},
            is_seeded="N",
        )
    )
    db_session.commit()

    payload = client.get("/skills/runtime-health").json()

    assert payload["skills"][bound]["status"] == "bound"
    assert payload["skills"][bound]["declared_status"] == "workspace_executor"
    assert payload["skills"]["ws.ws-author.unbindable_op"]["status"] == "unbound"
    assert payload["summary"]["catalog_only"] == 0
