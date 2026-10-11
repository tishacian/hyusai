"""Experience draft / release / deploy — gated by experience_v1."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import experiences as endpoint
from app.models.audit import AuditLog
from app.models.experience import Experience, ExperienceDeployment, ExperienceRelease
from app.models.system_binding import SystemBinding
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.flow_contracts import canonical_sha256
from app.services.iam.manifest import (
    ALL_CAPTURE_ROLES,
    CONTRIBUTOR_OR_ADMIN,
    EXPERIENCE_STUDIO_ROLES,
    REVIEW_ROLES,
    get_manifest,
)


def _seed(db_session, *, enabled: bool = True, role_template: str = "workspace_admin"):
    workspace = Workspace(
        id="ws-experience-api",
        slug="experience-api",
        name="Experience API",
        settings={"features": {"experience_v1": enabled}},
    )
    user = User(
        id="user-experience-admin",
        username="experience-admin@example.invalid",
        email="experience-admin@example.invalid",
        role="admin" if role_template == "workspace_admin" else "member",
    )
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role="admin" if role_template == "workspace_admin" else "member",
        role_template=role_template,
    )
    db_session.add_all([workspace, user, member])
    db_session.commit()
    return workspace, user


def _client(db_session, workspace: Workspace, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/experiences")
    app.dependency_overrides[endpoint.get_current_workspace] = lambda: workspace
    app.dependency_overrides[endpoint.get_current_user] = lambda: user
    app.dependency_overrides[endpoint.get_db] = lambda: db_session
    return TestClient(app)


def _create_body(**overrides):
    body = {
        "name": "Password reset",
        "description": None,
        "emblem": None,
        "slug": "password-reset",
        "pattern": "form_result",
        "languages": ["en"],
        "theme": {},
        "access_policy": {"roles": []},
    }
    body.update(overrides)
    return body


def _pages(*component_types: str) -> dict:
    components = [
        {"type": item, "id": f"component-{index}"}
        for index, item in enumerate(component_types)
    ] or [{"type": "header", "id": "component-0"}]
    return {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": components,
            }
        ]
    }


def _bound_form_pages(binding_key: str, schema: dict | None = None) -> dict:
    return {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": [
                    {
                        "type": "form",
                        "id": "form",
                        "props": {
                            "bindingKey": binding_key,
                            "schema": schema or {"type": "object", "properties": {}},
                        },
                    }
                ],
            }
        ]
    }


def _draft_body(pages: dict, binding_keys: list[str] | None = None, *, revision: int = 1) -> dict:
    return {
        "pages": pages,
        "binding_keys": binding_keys or [],
        "expected_revision": revision,
    }


def _release_body(client: TestClient, experience_id: str, notes: str) -> dict:
    detail = client.get(f"/experiences/{experience_id}").json()
    draft = detail["draft"]
    ready = client.get(f"/experiences/{experience_id}/ready-check").json()
    return {
        "notes": notes,
        "expected_draft_revision": draft["revision"],
        "expected_content_sha256": draft["content_sha256"],
        "expected_experience_updated_at": detail["updated_at"],
        "expected_bindings_sha256": ready["bindings_sha256"],
    }


def test_experience_actions_are_declared_on_the_object_actions_manifest() -> None:
    rules = {
        (rule.resource_kind, rule.action): rule
        for rule in get_manifest("agentium_object_actions", strict=True).permissions
    }
    assert rules[("experience", "view")].roles == EXPERIENCE_STUDIO_ROLES
    assert rules[("experience", "consume")].roles == ALL_CAPTURE_ROLES
    assert rules[("experience", "edit")].roles == CONTRIBUTOR_OR_ADMIN
    assert rules[("experience", "release")].roles == REVIEW_ROLES
    assert rules[("experience", "deploy")].roles == REVIEW_ROLES


def test_experiences_are_feature_gated(db_session) -> None:
    workspace, user = _seed(db_session, enabled=False)
    client = _client(db_session, workspace, user)

    listed = client.get("/experiences")
    created = client.post("/experiences", json=_create_body())

    assert listed.status_code == 404
    assert listed.json()["detail"]["code"] == "EXPERIENCE_V1_DISABLED"
    assert created.status_code == 404
    assert db_session.query(Experience).count() == 0


def test_studio_can_be_disabled_without_disabling_experience_runtime(db_session) -> None:
    workspace, user = _seed(db_session)
    workspace.settings = {
        "features": {"experience_v1": True, "experience_studio_v1": False}
    }
    db_session.add(workspace)
    db_session.commit()
    client = _client(db_session, workspace, user)

    listed = client.get("/experiences")
    audit = client.get("/experiences/audit")
    created = client.post("/experiences", json=_create_body())

    assert listed.status_code == 200
    assert listed.json() == {"experiences": []}
    assert audit.status_code == 200
    assert audit.json() == {"logs": [], "total": 0}
    assert created.status_code == 404
    assert created.json()["detail"]["code"] == "EXPERIENCE_STUDIO_V1_DISABLED"
    assert db_session.query(Experience).count() == 0


def test_create_and_list_experiences(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    created = client.post("/experiences", json=_create_body())
    listed = client.get("/experiences")
    fetched = client.get(f"/experiences/{created.json()['id']}")

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["slug"] == "password-reset"
    assert body["pattern"] == "form_result"
    assert body["draft"]["revision"] == 1
    assert body["draft"]["pages"] == {"pages": []}
    assert body["deployments"] == []
    assert listed.status_code == 200
    listed_row = listed.json()["experiences"][0]
    assert listed_row["slug"] == "password-reset"
    assert listed_row["binding_keys"] == []
    assert listed_row["draft_revision"] == 1
    assert listed_row["latest_release_number"] is None
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]
    assert fetched.json()["draft"]["content_sha256"] == body["draft"]["content_sha256"]
    created_audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.created")
        .one()
    )
    assert created_audit.details["slug"] == "password-reset"


def test_safe_brand_fields_are_authorable_clearable_and_audited(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    created = client.post(
        "/experiences",
        json=_create_body(
            description="  Front-line operator cockpit  ",
            emblem="🧭",
        ),
    )
    rejected = client.post(
        "/experiences",
        json=_create_body(slug="unsafe-emblem", emblem="https://example.test/x.svg"),
    )
    cleared = client.patch(
        f"/experiences/{created.json()['id']}",
        json={
            "description": None,
            "emblem": None,
            "expected_updated_at": created.json()["updated_at"],
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["description"] == "Front-line operator cockpit"
    assert created.json()["emblem"] == "🧭"
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "EXPERIENCE_EMBLEM_INVALID"
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["description"] is None
    assert cleared.json()["emblem"] is None
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.updated")
        .one()
    )
    assert audit.actor == user.email
    assert audit.details["changed_fields"] == ["description", "emblem"]


def test_draft_history_is_append_only_and_restore_uses_cas(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    first_pages = _pages("header")
    second_pages = _pages("header", "callout")
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(first_pages),
    ).status_code == 200
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(second_pages, revision=2),
    ).status_code == 200

    history = client.get(f"/experiences/{experience_id}/draft/revisions")
    restored = client.post(
        f"/experiences/{experience_id}/draft/revisions/2/restore",
        json={"expected_revision": 3},
    )
    retried = client.post(
        f"/experiences/{experience_id}/draft/revisions/2/restore",
        json={"expected_revision": 3},
    )
    stale = client.post(
        f"/experiences/{experience_id}/draft/revisions/3/restore",
        json={"expected_revision": 3},
    )
    restored_again = client.post(
        f"/experiences/{experience_id}/draft/revisions/2/restore",
        json={"expected_revision": 4},
    )
    final_history = client.get(f"/experiences/{experience_id}/draft/revisions")

    assert history.status_code == 200, history.text
    assert [item["revision"] for item in history.json()["revisions"]] == [3, 2, 1]
    assert restored.status_code == 200, restored.text
    assert restored.json()["revision"] == 4
    assert restored.json()["pages"] == first_pages
    assert retried.status_code == 409
    assert retried.json()["detail"]["code"] == "EXPERIENCE_DRAFT_REVISION_CONFLICT"
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "EXPERIENCE_DRAFT_REVISION_CONFLICT"
    assert restored_again.status_code == 200, restored_again.text
    assert restored_again.json()["revision"] == 5
    assert [item["revision"] for item in final_history.json()["revisions"]] == [
        5,
        4,
        3,
        2,
        1,
    ]
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.draft_restored")
        .count()
        == 2
    )


def test_wizard_finalize_is_atomic_for_draft_access_and_staged_bindings(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    body = {
        "pages": _bound_form_pages("missing.submit"),
        "binding_keys": ["missing.submit"],
        "expected_revision": 1,
        "bindings": [
            {
                "binding_key": "missing.submit",
                "system_id": "missing-system",
                "published_flow_version_id": "missing-version",
                "ingress_id": "submit",
                "confirmation_policy": "confirm",
                "on_unavailable": "unavailable",
            }
        ],
        "languages": ["fr"],
        "description": "Wizard-authored cockpit",
        "emblem": "spark",
        "theme": {"mode": "dark"},
        "access_policy": {"roles": ["workspace_viewer"]},
        "expected_experience_updated_at": created.json()["updated_at"],
    }

    failed = client.put(f"/experiences/{experience_id}/draft/finalize", json=body)
    unchanged = client.get(f"/experiences/{experience_id}").json()

    assert failed.status_code == 404, failed.text
    assert unchanged["draft"]["revision"] == 1
    assert unchanged["draft"]["pages"] == {"pages": []}
    assert unchanged["languages"] == ["en"]
    assert unchanged["description"] is None
    assert unchanged["emblem"] is None
    assert unchanged["theme"] == {}
    assert unchanged["access_policy"] == {"roles": []}
    assert db_session.query(SystemBinding).count() == 0

    body["bindings"] = []
    body["binding_keys"] = []
    body["pages"] = _pages("header")
    finalized = client.put(f"/experiences/{experience_id}/draft/finalize", json=body)
    detail = client.get(f"/experiences/{experience_id}").json()

    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["revision"] == 2
    assert detail["languages"] == ["fr"]
    assert detail["description"] == "Wizard-authored cockpit"
    assert detail["emblem"] == "spark"
    assert detail["theme"] == {"mode": "dark"}
    assert detail["access_policy"] == {"roles": ["workspace_viewer"]}

    retried = client.put(f"/experiences/{experience_id}/draft/finalize", json=body)
    assert retried.status_code == 200, retried.text
    assert retried.json()["revision"] == 2


def test_create_finalize_rolls_back_the_whole_application_on_failure(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    body = {
        **_create_body(slug="atomic-home"),
        "pages": _bound_form_pages("missing.submit"),
        "binding_keys": ["missing.submit"],
        "bindings": [
            {
                "binding_key": "missing.submit",
                "system_id": "missing-system",
                "published_flow_version_id": "missing-version",
                "ingress_id": "submit",
                "confirmation_policy": "confirm",
                "on_unavailable": "unavailable",
            }
        ],
    }

    failed = client.post("/experiences/finalize", json=body)
    assert failed.status_code == 404, failed.text
    assert db_session.query(Experience).count() == 0
    assert db_session.query(SystemBinding).count() == 0

    body["binding_keys"] = []
    body["bindings"] = []
    body["pages"] = _pages("header")
    created = client.post("/experiences/finalize", json=body)
    assert created.status_code == 201, created.text
    assert created.json()["draft"]["revision"] == 2
    assert created.json()["draft"]["pages"] == _pages("header")


def test_finalize_rejects_unused_staged_binding_before_mutating(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    body = {
        **_create_body(slug="unused-stage"),
        "pages": _pages("header"),
        "binding_keys": ["unused.submit"],
        "bindings": [
            {
                "binding_key": "unused.submit",
                "system_id": "missing-system",
                "published_flow_version_id": "missing-version",
                "ingress_id": "submit",
            }
        ],
    }

    response = client.post("/experiences/finalize", json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "STAGED_BINDING_UNUSED"
    assert db_session.query(Experience).count() == 0
    assert db_session.query(SystemBinding).count() == 0


def test_wizard_finalize_rejects_concurrent_access_change(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body()).json()
    changed = client.patch(
        f"/experiences/{created['id']}",
        json={"access_policy": {"groups": ["finance"]}},
    )
    assert changed.status_code == 200, changed.text

    response = client.put(
        f"/experiences/{created['id']}/draft/finalize",
        json={
            "pages": _pages("header"),
            "binding_keys": [],
            "expected_revision": 1,
            "bindings": [],
            "languages": ["fr"],
            "theme": {},
            "access_policy": {"roles": ["workspace_viewer"]},
            "expected_experience_updated_at": created["updated_at"],
        },
    )
    detail = client.get(f"/experiences/{created['id']}").json()

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EXPERIENCE_METADATA_CONFLICT"
    assert detail["draft"]["revision"] == 1
    assert detail["access_policy"] == {"groups": ["finance"]}


def test_metadata_patch_uses_updated_at_as_an_optimistic_precondition(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body()).json()
    first = client.patch(
        f"/experiences/{created['id']}",
        json={
            "access_policy": {"groups": ["finance"]},
            "expected_updated_at": created["updated_at"],
        },
    )
    assert first.status_code == 200, first.text

    stale = client.patch(
        f"/experiences/{created['id']}",
        json={
            "access_policy": {"roles": ["workspace_viewer"]},
            "expected_updated_at": created["updated_at"],
        },
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "EXPERIENCE_METADATA_CONFLICT"
    assert client.get(f"/experiences/{created['id']}").json()["access_policy"] == {
        "groups": ["finance"]
    }
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.updated")
        .one()
    )
    assert audit.actor == user.email
    assert audit.details["changed_fields"] == ["access_policy"]
    assert audit.details["access_policy"] == {
        "from": {"roles": []},
        "to": {"groups": ["finance"]},
    }


def test_experience_languages_are_limited_to_unique_fr_en(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)

    unsupported = client.post(
        "/experiences", json=_create_body(slug="spanish", languages=["es"])
    )
    duplicate = client.post(
        "/experiences", json=_create_body(slug="duplicate", languages=["fr", "fr"])
    )

    assert unsupported.status_code == 422
    assert unsupported.json()["detail"]["code"] == "EXPERIENCE_LANGUAGES_INVALID"
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"]["code"] == "EXPERIENCE_LANGUAGES_INVALID"


def test_experience_audit_lists_prefix_and_delete_emits(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    )
    assert saved.status_code == 200, saved.text
    deleted = client.delete(f"/experiences/{experience_id}")
    listed = client.get("/experiences/audit")

    assert deleted.status_code == 204
    assert db_session.query(Experience).count() == 0
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.draft_saved")
        .count()
        == 1
    )
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.deleted")
        .one()
        .details["experience_id"]
        == experience_id
    )
    assert listed.status_code == 200, listed.text
    types = {item["event_type"] for item in listed.json()["logs"]}
    assert types == {
        "experience.created",
        "experience.draft_saved",
        "experience.deleted",
    }


def test_live_experience_cannot_be_deleted(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    ).status_code == 200
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "live"),
    )
    assert released.status_code == 201, released.text
    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": released.json()["id"],
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    )
    assert deployed.status_code == 201, deployed.text

    deleted = client.delete(f"/experiences/{experience_id}")

    assert deleted.status_code == 409
    assert deleted.json()["detail"]["code"] == "EXPERIENCE_DEPLOYED"
    assert db_session.query(Experience).count() == 1
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.deleted")
        .count()
        == 0
    )

def test_draft_rejects_unknown_component_type(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    assert created.status_code == 201, created.text

    response = client.put(
        f"/experiences/{created.json()['id']}/draft",
        json=_draft_body(_pages("fancy_chart")),
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "DRAFT_COMPONENT_TYPE_INVALID"
    draft = client.get(f"/experiences/{created.json()['id']}")
    assert draft.json()["draft"]["revision"] == 1


def test_ready_check_blocks_missing_binding(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("form"), ["missing.submit"]),
    )
    assert saved.status_code == 200, saved.text

    check = client.get(f"/experiences/{experience_id}/ready-check")
    blocked = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "should not release"),
    )

    assert check.status_code == 200
    assert check.json()["ready"] is False
    assert any(item["code"] == "BINDING_MISSING" for item in check.json()["blockers"])
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "EXPERIENCE_NOT_READY"
    assert db_session.query(ExperienceRelease).count() == 0


def test_ready_check_blocks_an_implicit_open_audience(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post(
        "/experiences",
        json=_create_body(access_policy={}),
    )
    experience_id = created.json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    )

    check = client.get(f"/experiences/{experience_id}/ready-check")
    blocked = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "must choose access first"),
    )

    assert check.status_code == 200
    assert any(
        item["code"] == "ACCESS_POLICY_REQUIRED"
        for item in check.json()["blockers"]
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "EXPERIENCE_NOT_READY"
    assert db_session.query(ExperienceRelease).count() == 0


def test_ready_check_blocks_a_missing_language(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post(
        "/experiences",
        json=_create_body(languages=[]),
    )
    experience_id = created.json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    )

    check = client.get(f"/experiences/{experience_id}/ready-check")
    blocked = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "must choose a language first"),
    )

    assert any(item["code"] == "LANGUAGES_REQUIRED" for item in check.json()["blockers"])
    assert blocked.status_code == 409
    assert db_session.query(ExperienceRelease).count() == 0


def test_release_does_not_deploy(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header", "callout")),
    ).status_code == 200

    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "first certified snapshot"),
    )
    listed = client.get(f"/experiences/{experience_id}/releases")
    detail = client.get(f"/experiences/{experience_id}")

    assert released.status_code == 201, released.text
    assert released.json()["release_number"] == 1
    assert released.json()["notes"] == "first certified snapshot"
    assert released.json()["renderer_version"] == "certified-components-0.2.0"
    assert listed.json()["releases"][0]["id"] == released.json()["id"]
    assert detail.json()["deployments"] == []
    assert db_session.query(ExperienceDeployment).count() == 0
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.released")
        .one()
    )
    assert audit.details["release_id"] == released.json()["id"]


def test_undeployed_release_prevents_destructive_experience_delete(db_session) -> None:
    workspace, admin = _seed(db_session)
    contributor = User(
        id="user-experience-contributor",
        username="experience-contributor@example.invalid",
        email="experience-contributor@example.invalid",
        role="member",
    )
    db_session.add_all(
        [
            contributor,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=contributor.id,
                role="member",
                role_template="workspace_contributor",
            ),
        ]
    )
    db_session.commit()
    admin_client = _client(db_session, workspace, admin)
    contributor_client = _client(db_session, workspace, contributor)
    experience_id = admin_client.post("/experiences", json=_create_body()).json()["id"]
    assert admin_client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    ).status_code == 200
    release = admin_client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(admin_client, experience_id, "immutable evidence"),
    )
    assert release.status_code == 201, release.text

    deleted = contributor_client.delete(f"/experiences/{experience_id}")

    assert deleted.status_code == 409
    assert deleted.json()["detail"]["code"] == "EXPERIENCE_RELEASED"
    assert db_session.get(Experience, experience_id) is not None
    assert db_session.get(ExperienceRelease, release.json()["id"]) is not None
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.deleted")
        .count()
        == 0
    )


def test_deploy_pilot_and_rollback(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    ).status_code == 200
    first = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "r1"),
    )
    assert first.status_code == 201, first.text
    detail = client.get(f"/experiences/{experience_id}").json()
    assert client.patch(
        f"/experiences/{experience_id}",
        json={
            "access_policy": {"roles": ["workspace_admin"]},
            "expected_updated_at": detail["updated_at"],
        },
    ).status_code == 200
    second_pages = _pages("header", "section")
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(second_pages, revision=2),
    ).status_code == 200
    second = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "r2"),
    )
    assert second.status_code == 201, second.text
    third = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "r3"),
    )
    assert third.status_code == 201, third.text

    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": first.json()["id"],
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    )
    narrow_body = {
        "channel": "pilot",
        "release_id": first.json()["id"],
        "expected_current_release_id": first.json()["id"],
        "expected_deployment_updated_at": deployed.json()["updated_at"],
        "audience": {"roles": ["workspace_admin"]},
    }
    narrowed = client.post(
        f"/experiences/{experience_id}/deployments", json=narrow_body
    )
    retried_narrow = client.post(
        f"/experiences/{experience_id}/deployments", json=narrow_body
    )
    update_body = {
        "channel": "pilot",
        "release_id": second.json()["id"],
        "expected_current_release_id": first.json()["id"],
        "expected_deployment_updated_at": narrowed.json()["updated_at"],
    }
    updated = client.post(
        f"/experiences/{experience_id}/deployments",
        json=update_body,
    )
    retried_update = client.post(
        f"/experiences/{experience_id}/deployments",
        json=update_body,
    )
    moved_to_third = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": third.json()["id"],
            "expected_current_release_id": second.json()["id"],
            "expected_deployment_updated_at": updated.json()["updated_at"],
        },
    )
    moved_back_to_second = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": second.json()["id"],
            "expected_current_release_id": third.json()["id"],
            "expected_deployment_updated_at": moved_to_third.json()["updated_at"],
        },
    )
    late_update = client.post(
        f"/experiences/{experience_id}/deployments",
        json=update_body,
    )
    stale_deploy = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": first.json()["id"],
            "expected_current_release_id": first.json()["id"],
            "expected_deployment_updated_at": deployed.json()["updated_at"],
        },
    )
    rollback_body = {
        "release_id": first.json()["id"],
        "expected_current_release_id": second.json()["id"],
        "expected_deployment_updated_at": moved_back_to_second.json()["updated_at"],
    }
    rolled = client.post(
        f"/experiences/{experience_id}/deployments/pilot/rollback",
        json=rollback_body,
    )
    retried = client.post(
        f"/experiences/{experience_id}/deployments/pilot/rollback",
        json=rollback_body,
    )
    redeployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": second.json()["id"],
            "expected_current_release_id": first.json()["id"],
            "expected_deployment_updated_at": rolled.json()["updated_at"],
        },
    )
    late_rollback = client.post(
        f"/experiences/{experience_id}/deployments/pilot/rollback",
        json=rollback_body,
    )

    assert deployed.status_code == 201, deployed.text
    assert deployed.json()["channel"] == "pilot"
    assert deployed.json()["release_id"] == first.json()["id"]
    assert narrowed.status_code == 201, narrowed.text
    assert narrowed.json()["audience"] == {"roles": ["workspace_admin"]}
    assert retried_narrow.status_code == 201, retried_narrow.text
    assert retried_narrow.json()["updated_at"] == narrowed.json()["updated_at"]
    assert updated.status_code == 201
    assert updated.json()["release_id"] == second.json()["id"]
    assert updated.json()["previous_release_id"] == first.json()["id"]
    assert updated.json()["previous_audience"] == {
        "roles": ["workspace_admin"]
    }
    assert updated.json()["audience"] == {"roles": ["workspace_admin"]}
    assert retried_update.status_code == 201
    assert retried_update.json()["release_id"] == second.json()["id"]
    assert moved_to_third.status_code == 201, moved_to_third.text
    assert moved_back_to_second.status_code == 201, moved_back_to_second.text
    assert late_update.status_code == 409
    assert late_update.json()["detail"]["code"] == "EXPERIENCE_DEPLOYMENT_CONFLICT"
    assert stale_deploy.status_code == 409
    assert stale_deploy.json()["detail"]["code"] == "EXPERIENCE_DEPLOYMENT_CONFLICT"
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["release_id"] == first.json()["id"]
    assert rolled.json()["audience"] == {"roles": ["workspace_admin"]}
    assert retried.status_code == 200, retried.text
    assert retried.json()["release_id"] == first.json()["id"]
    assert redeployed.status_code == 201, redeployed.text
    assert redeployed.json()["release_id"] == second.json()["id"]
    assert late_rollback.status_code == 409
    assert late_rollback.json()["detail"]["code"] == "EXPERIENCE_DEPLOYMENT_CONFLICT"
    assert db_session.query(ExperienceDeployment).count() == 1
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.deployed")
        .count()
        == 6
    )
    rollback_audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.rolled_back")
        .one()
    )
    assert rollback_audit.details["release_id"] == first.json()["id"]


def test_legacy_pilot_rollback_intersects_audience_instead_of_widening(
    db_session,
) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body()).json()
    experience_id = created["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    ).status_code == 200
    first = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "open release"),
    ).json()
    detail = client.get(f"/experiences/{experience_id}").json()
    assert client.patch(
        f"/experiences/{experience_id}",
        json={
            "access_policy": {"roles": ["workspace_admin"]},
            "expected_updated_at": detail["updated_at"],
        },
    ).status_code == 200
    second = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "restricted release"),
    ).json()
    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": first["id"],
            "audience": {"roles": ["workspace_admin"]},
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    ).json()
    moved = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": second["id"],
            "expected_current_release_id": first["id"],
            "expected_deployment_updated_at": deployed["updated_at"],
        },
    )
    assert moved.status_code == 201, moved.text
    deployment = db_session.query(ExperienceDeployment).one()
    deployment.previous_audience = None
    db_session.commit()
    db_session.refresh(deployment)

    rolled = client.post(
        f"/experiences/{experience_id}/deployments/pilot/rollback",
        json={
            "release_id": first["id"],
            "expected_current_release_id": second["id"],
            "expected_deployment_updated_at": deployment.updated_at.isoformat(),
        },
    )

    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["audience"] == {"roles": ["workspace_admin"]}


def test_viewer_cannot_release(db_session) -> None:
    workspace, admin = _seed(db_session)
    viewer = User(
        id="user-experience-viewer",
        username="experience-viewer@example.invalid",
        email="experience-viewer@example.invalid",
        role="member",
    )
    db_session.add_all(
        [
            viewer,
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=viewer.id,
                role="member",
                role_template="workspace_viewer",
            ),
        ]
    )
    db_session.commit()
    admin_client = _client(db_session, workspace, admin)
    created = admin_client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    assert admin_client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    ).status_code == 200

    viewer_client = _client(db_session, workspace, viewer)
    listed = viewer_client.get("/experiences")
    release_body = _release_body(admin_client, experience_id, "viewer must not release")
    released = viewer_client.post(
        f"/experiences/{experience_id}/releases",
        json=release_body,
    )

    assert listed.status_code == 403
    assert released.status_code == 403
    assert released.json()["detail"]["code"] == "WORKSPACE_PERMISSION_DENIED"
    assert db_session.query(ExperienceRelease).count() == 0


def test_draft_save_and_release_require_exact_revision_and_content(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    )
    stale_save = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("result")),
    )
    stale_body = _release_body(client, experience_id, "stale")
    stale_body["expected_draft_revision"] = 1
    stale_release = client.post(
        f"/experiences/{experience_id}/releases",
        json=stale_body,
    )
    wrong_hash_body = _release_body(client, experience_id, "wrong hash")
    wrong_hash_body["expected_content_sha256"] = "0" * 64
    wrong_hash = client.post(
        f"/experiences/{experience_id}/releases",
        json=wrong_hash_body,
    )

    assert stale_save.status_code == 409
    assert stale_save.json()["detail"]["code"] == "EXPERIENCE_DRAFT_REVISION_CONFLICT"
    assert stale_release.status_code == 409
    assert stale_release.json()["detail"]["current_revision"] == saved.json()["revision"]
    assert wrong_hash.status_code == 409
    assert wrong_hash.json()["detail"]["code"] == "EXPERIENCE_DRAFT_CONTENT_CONFLICT"


def test_release_rejects_metadata_changed_after_review(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    ).status_code == 200
    reviewed = _release_body(client, experience_id, "reviewed audience")
    detail = client.get(f"/experiences/{experience_id}").json()
    changed = client.patch(
        f"/experiences/{experience_id}",
        json={
            "access_policy": {"roles": ["workspace_admin"]},
            "expected_updated_at": detail["updated_at"],
        },
    )
    assert changed.status_code == 200, changed.text

    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=reviewed,
    )

    assert released.status_code == 409
    assert released.json()["detail"]["code"] == "EXPERIENCE_METADATA_CONFLICT"
    assert db_session.query(ExperienceRelease).count() == 0


def test_release_rejects_binding_changed_after_review(db_session, monkeypatch) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    schema = {"type": "object", "properties": {}}
    evidence = {
        "binding_key": "demo.submit",
        "system_id": "system-demo",
        "published_flow_version_id": "version-1",
        "flow_sha256": "a" * 64,
        "ingress_id": "manual.input",
        "input_schema_sha256": canonical_sha256(schema),
        "output_schema_sha256": None,
        "confirmation_policy": "direct-safe",
        "on_unavailable": "unavailable",
    }

    def resolved(_db, *, workspace, key):
        del _db, workspace
        return (
            {
                "status": "ok",
                "binding": {**evidence, "binding_key": key},
                "input_schema": schema,
                "reasons": [],
            },
            None,
        )

    monkeypatch.setattr(endpoint.experience_service, "_resolve_referenced", resolved)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_bound_form_pages("demo.submit", schema), ["demo.submit"]),
    ).status_code == 200
    reviewed = _release_body(client, experience_id, "reviewed binding")
    evidence["published_flow_version_id"] = "version-2"
    evidence["flow_sha256"] = "b" * 64

    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=reviewed,
    )

    assert released.status_code == 409
    assert released.json()["detail"]["code"] == "EXPERIENCE_BINDINGS_CONFLICT"
    assert db_session.query(ExperienceRelease).count() == 0


def test_identical_release_retry_is_idempotent(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    ).status_code == 200
    body = _release_body(client, experience_id, "one reviewed intent")

    first = client.post(f"/experiences/{experience_id}/releases", json=body)
    retried = client.post(f"/experiences/{experience_id}/releases", json=body)

    assert first.status_code == 201, first.text
    assert retried.status_code == 201, retried.text
    assert retried.json()["id"] == first.json()["id"]
    assert db_session.query(ExperienceRelease).count() == 1
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.released")
        .count()
        == 1
    )


def test_delayed_release_retry_returns_original_after_intervening_release(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    ).status_code == 200
    first_body = _release_body(client, experience_id, "first intent")
    second_body = {**first_body, "notes": "second intent"}

    first = client.post(f"/experiences/{experience_id}/releases", json=first_body)
    second = client.post(f"/experiences/{experience_id}/releases", json=second_body)
    detail = client.get(f"/experiences/{experience_id}").json()
    assert client.patch(
        f"/experiences/{experience_id}",
        json={
            "description": "metadata changed after both receipts",
            "expected_updated_at": detail["updated_at"],
        },
    ).status_code == 200
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header", "callout"), revision=2),
    ).status_code == 200
    delayed_retry = client.post(
        f"/experiences/{experience_id}/releases", json=first_body
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["release_number"] == 2
    assert delayed_retry.status_code == 201, delayed_retry.text
    assert delayed_retry.json()["id"] == first.json()["id"]
    assert db_session.query(ExperienceRelease).count() == 2


def test_ready_check_blocks_unlisted_component_and_query_bindings(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    pages = {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": [
                    {
                        "type": "form",
                        "id": "submit",
                        "props": {"bindingKey": "missing.submit"},
                    },
                    {
                        "type": "table",
                        "id": "orders",
                        "props": {
                            "queryBinding": {
                                "source": "system-binding",
                                "bindingKey": "missing.orders",
                                "input": {},
                            }
                        },
                    },
                ],
            }
        ]
    }
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages),
    ).status_code == 200

    check = client.get(f"/experiences/{experience_id}/ready-check")
    codes = [item["code"] for item in check.json()["blockers"]]

    assert check.json()["ready"] is False
    assert codes.count("COMPONENT_BINDING_UNLISTED") == 2
    assert codes.count("BINDING_MISSING") == 2


def test_live_slug_and_any_deployed_experience_are_protected(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    )
    release = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "pilot"),
    )
    assert client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": release.json()["id"],
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    ).status_code == 201

    assert client.delete(f"/experiences/{experience_id}").json()["detail"]["code"] == "EXPERIENCE_DEPLOYED"
    blocked_pilot_slug = client.patch(
        f"/experiences/{experience_id}", json={"slug": "new-password-reset"}
    )
    assert blocked_pilot_slug.status_code == 409
    assert blocked_pilot_slug.json()["detail"]["code"] == "EXPERIENCE_DEPLOYED_SLUG_IMMUTABLE"
    assert client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": release.json()["id"],
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    ).status_code == 201
    blocked_slug = client.patch(
        f"/experiences/{experience_id}", json={"slug": "another-password-reset"}
    )
    assert blocked_slug.status_code == 409
    assert blocked_slug.json()["detail"]["code"] == "EXPERIENCE_DEPLOYED_SLUG_IMMUTABLE"


def test_release_with_old_slug_cannot_be_deployed_after_draft_identity_rename(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    )
    release = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "old URL"),
    )
    assert release.json()["identity_snapshot"] == {
        "name": "Password reset",
        "description": None,
        "emblem": None,
        "slug": "password-reset",
        "pattern": "form_result",
    }
    assert client.patch(
        f"/experiences/{experience_id}", json={"slug": "renamed-reset"}
    ).status_code == 200

    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "pilot",
            "release_id": release.json()["id"],
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    )

    assert deployed.status_code == 409
    assert deployed.json()["detail"]["code"] == "EXPERIENCE_RELEASE_IDENTITY_STALE"


def test_access_policy_is_separate_frozen_and_defaulted_on_deploy(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post(
        "/experiences",
        json=_create_body(
            theme={"mode": "light"},
            access_policy={"role_templates": ["workspace_viewer"], "groups": ["pilot-a"]},
        ),
    )
    experience_id = created.json()["id"]
    assert created.json()["theme"] == {"mode": "light"}
    assert created.json()["access_policy"] == {
        "roles": ["workspace_viewer"],
        "groups": ["pilot-a"],
    }
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    )
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "access frozen"),
    )
    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={
            "channel": "live",
            "release_id": released.json()["id"],
            "expected_current_release_id": None,
            "expected_deployment_updated_at": None,
        },
    )

    assert released.json()["access_snapshot"] == created.json()["access_policy"]
    assert deployed.json()["audience"] == created.json()["access_policy"]


def test_ready_check_blocks_incomplete_i18n_references(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post(
        "/experiences", json=_create_body(languages=["fr", "en"])
    )
    experience_id = created.json()["id"]
    pages = {
        "i18n": {"fr": {"home.title": "Accueil"}, "en": {}},
        "pages": [
            {
                "id": "home",
                "title": {"$i18n": "home.title", "fallback": "Home"},
                "components": [
                    {
                        "type": "header",
                        "id": "header",
                        "props": {
                            "title": {"$i18n": "", "fallback": ""}
                        },
                    }
                ],
            }
        ],
    }
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages),
    ).status_code == 200

    check = client.get(f"/experiences/{experience_id}/ready-check").json()
    codes = {item["code"] for item in check["blockers"]}
    assert "I18N_REFERENCE_INVALID" in codes
    assert "I18N_TRANSLATION_MISSING" in codes


def test_ready_check_blocks_multiple_languages_without_i18n_map(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post(
        "/experiences", json=_create_body(languages=["fr", "en"])
    )
    experience_id = created.json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    ).status_code == 200

    check = client.get(f"/experiences/{experience_id}/ready-check").json()
    release = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "missing translations"),
    )

    assert check["ready"] is False
    assert "MISSING_I18N" in {item["code"] for item in check["blockers"]}
    assert release.status_code == 409


def test_ready_check_certifies_multilingual_form_presentation_only(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    schema = {
        "type": "object",
        "properties": {
            "requester": {
                "type": "string",
                "title": "Requester",
                "description": "Person asking for help",
            },
            "priority": {
                "type": "string",
                "enum": ["normal", "urgent"],
            },
        },
    }
    experience_id = client.post(
        "/experiences", json=_create_body(languages=["fr", "en"])
    ).json()["id"]
    incomplete = _bound_form_pages("missing.submit", schema)
    incomplete["i18n"] = {
        "fr": {"home.title": "Accueil"},
        "en": {"home.title": "Home"},
    }
    incomplete["pages"][0]["title"] = {
        "$i18n": "home.title",
        "fallback": "Home",
    }
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(incomplete, ["missing.submit"]),
    ).status_code == 200
    incomplete_codes = {
        item["code"]
        for item in client.get(
            f"/experiences/{experience_id}/ready-check"
        ).json()["blockers"]
    }
    assert "FORM_COPY_INCOMPLETE" in incomplete_codes

    complete = _bound_form_pages("missing.submit", schema)
    complete["pages"][0]["title"] = {
        "$i18n": "home.title",
        "fallback": "Home",
    }
    complete["pages"][0]["components"][0]["props"]["fieldPresentation"] = {
        "requester": {
            "label": {"$i18n": "requester.label", "fallback": "Requester"},
            "description": {
                "$i18n": "requester.description",
                "fallback": "Person asking for help",
            },
        },
        "priority": {
            "label": {"$i18n": "priority.label", "fallback": "Priority"},
            "options": {
                "normal": {"$i18n": "priority.normal", "fallback": "Normal"},
                "urgent": {"$i18n": "priority.urgent", "fallback": "Urgent"},
            },
        },
    }
    complete["i18n"] = {
        language: {
            "home.title": "Accueil" if language == "fr" else "Home",
            "requester.label": "Demandeur" if language == "fr" else "Requester",
            "requester.description": "Personne à aider" if language == "fr" else "Person asking for help",
            "priority.label": "Priorité" if language == "fr" else "Priority",
            "priority.normal": "Normale" if language == "fr" else "Normal",
            "priority.urgent": "Urgente" if language == "fr" else "Urgent",
        }
        for language in ("fr", "en")
    }
    complete["i18n"]["en"].pop("priority.urgent")
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(complete, ["missing.submit"], revision=2),
    ).status_code == 200
    missing_translation_codes = {
        item["code"]
        for item in client.get(
            f"/experiences/{experience_id}/ready-check"
        ).json()["blockers"]
    }
    assert "FORM_COPY_INCOMPLETE" not in missing_translation_codes
    assert "I18N_TRANSLATION_MISSING" in missing_translation_codes

    complete["i18n"]["en"]["priority.urgent"] = "Urgent"
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(complete, ["missing.submit"], revision=3),
    ).status_code == 200
    complete_codes = {
        item["code"]
        for item in client.get(
            f"/experiences/{experience_id}/ready-check"
        ).json()["blockers"]
    }
    assert "FORM_COPY_INCOMPLETE" not in complete_codes
    assert "I18N_TRANSLATION_MISSING" not in complete_codes

    mono_id = client.post(
        "/experiences", json=_create_body(name="Mono", slug="mono", languages=["en"])
    ).json()["id"]
    assert client.put(
        f"/experiences/{mono_id}/draft",
        json=_draft_body(_bound_form_pages("missing.submit", schema), ["missing.submit"]),
    ).status_code == 200
    mono_codes = {
        item["code"]
        for item in client.get(f"/experiences/{mono_id}/ready-check").json()["blockers"]
    }
    assert "FORM_COPY_INCOMPLETE" not in mono_codes


def test_ready_check_rejects_an_unused_i18n_map_without_localized_content(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post(
        "/experiences", json=_create_body(languages=["fr", "en"])
    ).json()["id"]
    pages = _pages("header")
    pages["i18n"] = {"fr": {"unused": "x"}, "en": {"unused": "x"}}
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages),
    ).status_code == 200

    check = client.get(f"/experiences/{experience_id}/ready-check").json()

    assert check["ready"] is False
    codes = {item["code"] for item in check["blockers"]}
    assert "MISSING_I18N" in codes
    assert "I18N_VISIBLE_TEXT_UNLOCALIZED" in codes


def test_ready_check_blocks_missing_queue_or_approval_empty_state(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post(
        "/experiences", json=_create_body(pattern="approval")
    ).json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("header")),
    ).status_code == 200

    check = client.get(f"/experiences/{experience_id}/ready-check").json()

    assert "MISSING_EMPTY_STATE" in {
        item["code"] for item in check["blockers"]
    }
    assert "MISSING_EMPTY_STATE" not in {
        item["code"] for item in check["warnings"]
    }


def test_draft_ids_are_stable_unique_and_absolute_positioning_is_rejected(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    normalized = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(
            {
                "pages": [
                    {
                        "id": " home ",
                        "title": "Home",
                        "components": [{"id": " header ", "type": "header"}],
                    }
                ]
            }
        ),
    )
    assert normalized.status_code == 200, normalized.text
    assert normalized.json()["pages"]["pages"][0]["id"] == "home"
    assert normalized.json()["pages"]["pages"][0]["components"][0]["id"] == "header"

    duplicate = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(
            {
                "pages": [
                    {
                        "id": "one",
                        "title": "One",
                        "components": [{"id": "same", "type": "header"}],
                    },
                    {
                        "id": "two",
                        "title": "Two",
                        "components": [{"id": "same", "type": "result"}],
                    },
                ]
            },
            revision=2,
        ),
    )
    positioned = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(
            {
                "pages": [
                    {
                        "id": "home",
                        "title": "Home",
                        "components": [
                            {"id": "header", "type": "header", "position": "absolute"}
                        ],
                    }
                ]
            },
            revision=2,
        ),
    )
    unsafe_page = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(
            {
                "pages": [
                    {
                        "id": "admin/settings",
                        "title": "Unsafe",
                        "components": [{"id": "header", "type": "header"}],
                    }
                ]
            },
            revision=2,
        ),
    )
    unsafe_component = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(
            {
                "pages": [
                    {
                        "id": "home",
                        "title": "Unsafe",
                        "components": [{"id": "9-header", "type": "header"}],
                    }
                ]
            },
            revision=2,
        ),
    )

    assert duplicate.status_code == 422
    assert duplicate.json()["detail"]["code"] == "DRAFT_COMPONENT_ID_DUPLICATE"
    assert positioned.status_code == 422
    assert positioned.json()["detail"]["code"] == "DRAFT_ABSOLUTE_POSITIONING"
    assert unsafe_page.status_code == 422
    assert unsafe_page.json()["detail"]["code"] == "DRAFT_PAGE_ID_INVALID"
    assert unsafe_component.status_code == 422
    assert unsafe_component.json()["detail"]["code"] == "DRAFT_COMPONENT_ID_INVALID"


def test_ready_check_certifies_closed_query_and_run_output_bindings(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    pages = {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": [
                    {
                        "id": " action ",
                        "type": "form",
                        "props": {"bindingKey": "missing.action"},
                    },
                    {
                        "id": "result",
                        "type": "result",
                        "props": {
                            "dataBinding": {
                                "source": "run-output",
                                "componentId": " action ",
                                "selector": " result.value ",
                            }
                        },
                    },
                    {
                        "id": "query",
                        "type": "table",
                        "props": {
                            "queryBinding": {
                                "source": "system-binding",
                                "bindingKey": "missing.query",
                                "input": {},
                                "selector": " rows ",
                            }
                        },
                    },
                ],
            }
        ]
    }
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages, ["missing.action", "missing.query"]),
    )
    assert saved.status_code == 200, saved.text
    props = saved.json()["pages"]["pages"][0]["components"][1]["props"]
    assert props["dataBinding"]["componentId"] == "action"
    assert props["dataBinding"]["selector"] == "result.value"
    valid_codes = {
        item["code"]
        for item in client.get(f"/experiences/{experience_id}/ready-check").json()["blockers"]
    }
    assert "QUERY_BINDING_INVALID" not in valid_codes
    assert "DATA_BINDING_INVALID" not in valid_codes

    pages["pages"][0]["components"][0]["props"] = {}
    pages["pages"][0]["components"][1]["props"]["dataBinding"] = {
        "source": "system-binding",
        "componentId": "action",
        "selector": "__proto__.value",
    }
    pages["pages"][0]["components"][1]["props"]["queryBinding"] = {
        "source": "system-binding",
        "bindingKey": "missing.query",
        "input": {},
    }
    pages["pages"][0]["components"][2]["props"]["queryBinding"]["source"] = "run-output"
    pages["pages"][0]["components"][2]["props"]["sourceComponentId"] = "missing"
    malformed = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages, ["missing.action", "missing.query"], revision=2),
    )
    assert malformed.status_code == 200, malformed.text
    invalid_codes = {
        item["code"]
        for item in client.get(f"/experiences/{experience_id}/ready-check").json()["blockers"]
    }
    assert {
        "QUERY_BINDING_INVALID",
        "DATA_BINDING_INVALID",
        "DATA_SOURCE_CONFLICT",
        "SOURCE_COMPONENT_INVALID",
    } <= invalid_codes


def test_work_forms_preserve_and_certify_brd_text_length_constraints():
    import pytest

    from app.services.flow_contracts import FlowContractError, validate_payload

    schema = {
        "type": "object",
        "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 3}},
        "additionalProperties": False,
    }
    service = endpoint.experience_service
    assert service._form_schema_supported(schema)
    pages = {"pages": [{"components": [{"type": "form", "id": "request", "props": {
        "bindingKey": "brd.request", "schema": schema,
    }}]}]}
    binding = {"brd.request": {"input_schema": schema, "binding": {
        "input_schema_sha256": canonical_sha256(schema),
    }}}
    assert service._binding_contract_issues(pages, binding) == []
    for query in ("ab", "abc", "😀😀", "😀😀😀"):
        validate_payload({"query": query}, schema, code="invalid", subject="Request")
    validate_payload({}, schema, code="invalid", subject="Request")
    for query in ("", "a", "abcd", "😀", 42):
        with pytest.raises(FlowContractError):
            validate_payload({"query": query}, schema, code="invalid", subject="Request")
    for spec in (
        {"type": "string", "minLength": -1}, {"type": "string", "maxLength": 1.5},
        {"type": "string", "minLength": True}, {"type": "string", "maxLength": None},
        {"type": "string", "minLength": 4, "maxLength": 2},
        {"type": "number", "minLength": 1},
        {"type": "string", "format": "binary", "minLength": 1},
        {"type": "string", "x-file": True, "maxLength": 12},
        {"type": "string", "maxLength": 2**53},
    ):
        assert not service._form_schema_supported({"type": "object", "properties": {"query": spec}})
    assert service._form_schema_supported({
        "type": "object", "properties": {"query": {"type": "string", "minLength": 1.0}},
    })


def test_ready_check_blocks_inputs_and_selectors_outside_published_contract(
    db_session, monkeypatch
) -> None:
    assert endpoint.experience_service._selector_matches_schema(
        {"type": "object"}, "event.id"
    )
    assert endpoint.experience_service._selector_matches_schema(
        {"type": "object", "additionalProperties": {"type": "object"}}, "event.id"
    )
    assert not endpoint.experience_service._selector_matches_schema(
        {"type": "object", "properties": {}, "additionalProperties": False}, "event"
    )
    assert not endpoint.experience_service._form_schema_supported(
        {
            "$ref": "#/$defs/Input",
            "$defs": {
                "Input": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                }
            },
        }
    )
    assert not endpoint.experience_service._form_schema_supported(
        {
            "type": "object",
            "properties": {"query": {"type": "string", "pattern": "^REQ-"}},
        }
    )
    assert not endpoint.experience_service._form_schema_supported(
        {
            "type": "object",
            "properties": {"when": {"type": "string", "format": "date-time"}},
        }
    )
    assert not endpoint.experience_service._form_schema_supported(
        {
            "type": "object",
            "properties": {"attachment": {"type": "boolean", "x-file": True}},
        }
    )
    assert not endpoint.experience_service._form_schema_supported(
        {
            "type": "object",
            "properties": {"priority": {"type": "integer", "enum": [1.5]}},
        }
    )
    assert not endpoint.experience_service._form_schema_supported(
        {
            "type": "object",
            "properties": {
                "attachment": {
                    "type": "string",
                    "format": "date",
                    "x-file": True,
                    "contentMediaType": "application/pdf",
                }
            },
        }
    )
    assert not endpoint.experience_service._form_schema_supported(
        {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "const": {"code": "A"},
        }
    )
    assert not endpoint.experience_service._form_schema_supported(
        {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "dependentSchemas": {"code": {"required": ["other"]}},
        }
    )
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    input_schema = {
        "type": "object",
        "required": ["query"],
        "properties": {"query": {"type": "string"}},
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "string"}},
            "rows": {"type": "array", "items": {"type": "object"}},
            "status": {"type": "string"},
        },
        "additionalProperties": False,
    }
    unsupported_form_schema = {
        "type": "object",
        "required": ["filters"],
        "properties": {"filters": {"type": "object"}},
    }

    def resolved(_db, *, workspace, key):
        del _db, workspace
        schema = unsupported_form_schema if key == "demo.unsupported" else input_schema
        return (
            {
                "status": "ok",
                "binding": {
                    "binding_key": key,
                    "system_id": "system-demo",
                    "published_flow_version_id": "version-demo",
                    "flow_sha256": "a" * 64,
                    "ingress_id": "manual.input",
                    "input_schema_sha256": canonical_sha256(schema),
                    "output_schema_sha256": canonical_sha256(output_schema),
                    "confirmation_policy": "direct-safe",
                    "on_unavailable": "unavailable",
                },
                "input_schema": schema,
                "output_schema": output_schema,
                "reasons": [],
            },
            None,
        )

    monkeypatch.setattr(endpoint.experience_service, "_resolve_referenced", resolved)
    pages = {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": [
                    {
                        "id": "form",
                        "type": "form",
                        "props": {
                            "bindingKey": "demo.form",
                            "schema": {"type": "object", "properties": {}},
                        },
                    },
                    {
                        "id": "action",
                        "type": "action_button",
                        "props": {"bindingKey": "demo.action", "input": {}},
                    },
                    {
                        "id": "unsupported",
                        "type": "form",
                        "props": {
                            "bindingKey": "demo.unsupported",
                            "schema": unsupported_form_schema,
                        },
                    },
                    {
                        "id": "table",
                        "type": "table",
                        "props": {
                            "queryBinding": {
                                "source": "system-binding",
                                "bindingKey": "demo.query",
                                "input": {},
                                "selector": "rowz",
                            }
                        },
                    },
                    {
                        "id": "table-wrong-type",
                        "type": "table",
                        "props": {
                            "queryBinding": {
                                "source": "system-binding",
                                "bindingKey": "demo.query",
                                "input": {},
                                "selector": "status",
                            }
                        },
                    },
                    {
                        "id": "table-wrong-collection",
                        "type": "table",
                        "props": {
                            "queryBinding": {
                                "source": "system-binding",
                                "bindingKey": "demo.query",
                                "input": {},
                                "selector": "",
                            }
                        },
                    },
                    {
                        "id": "evidence-wrong-type",
                        "type": "evidence",
                        "props": {
                            "queryBinding": {
                                "source": "system-binding",
                                "bindingKey": "demo.query",
                                "input": {},
                                "selector": "status",
                            }
                        },
                    },
                ],
            }
        ]
    }
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(
            pages, ["demo.form", "demo.action", "demo.unsupported", "demo.query"]
        ),
    )
    assert saved.status_code == 200, saved.text

    blockers = client.get(f"/experiences/{experience_id}/ready-check").json()["blockers"]
    codes = {item["code"] for item in blockers}

    assert "FORM_SCHEMA_MISMATCH" in codes
    assert "FORM_SCHEMA_UNSUPPORTED" in codes
    assert "ACTION_INPUT_SCHEMA_MISMATCH" in codes
    assert "QUERY_INPUT_SCHEMA_MISMATCH" in codes
    assert "SELECTOR_SCHEMA_MISMATCH" in codes
    assert "SELECTOR_TARGET_TYPE_MISMATCH" in codes
    assert {
        item.get("component_id")
        for item in blockers
        if item["code"] == "SELECTOR_TARGET_TYPE_MISMATCH"
    } == {"table-wrong-type", "table-wrong-collection", "evidence-wrong-type"}


def test_ready_check_blocks_implicit_output_from_an_unlinked_action(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("form", "runtime_status", "result", "evidence")),
    ).status_code == 200

    check = client.get(f"/experiences/{experience_id}/ready-check").json()

    assert check["ready"] is False
    assert "ACTION_BINDING_MISSING" in {item["code"] for item in check["blockers"]}


def test_ready_check_blocks_every_unlinked_action_even_with_static_output(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    pages = _pages("form", "result", "action_button")
    pages["pages"][0]["components"][1]["props"] = {"value": {"status": "static"}}
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages),
    ).status_code == 200

    blockers = client.get(f"/experiences/{experience_id}/ready-check").json()["blockers"]

    assert sum(item["code"] == "ACTION_BINDING_MISSING" for item in blockers) == 2


def test_ready_check_blocks_a_static_data_led_template(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post(
        "/experiences", json=_create_body(pattern="dashboard")
    ).json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("kpi", "table")),
    ).status_code == 200

    check = client.get(f"/experiences/{experience_id}/ready-check").json()

    assert check["ready"] is False
    assert "TEMPLATE_DATA_SOURCE_MISSING" in {
        item["code"] for item in check["blockers"]
    }


def test_ready_check_blocks_invalid_accent_and_warns_on_low_contrast(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    pages = {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "props": {"theme": "light"},
                "components": [
                    {"id": "header", "type": "header", "props": {"accent": "red"}}
                ],
            }
        ]
    }
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages),
    )
    assert saved.status_code == 200, saved.text
    invalid = client.get(f"/experiences/{experience_id}/ready-check").json()
    assert "ACCENT_COLOR_INVALID" in {item["code"] for item in invalid["blockers"]}
    blocked_release = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "invalid accent"),
    )
    assert blocked_release.status_code == 409

    pages["pages"][0]["components"][0]["props"]["accent"] = " #fff "
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages, revision=2),
    )
    assert saved.json()["pages"]["pages"][0]["components"][0]["props"]["accent"] == "#fff"
    warning = client.get(f"/experiences/{experience_id}/ready-check").json()
    assert warning["ready"] is True
    assert "ACCENT_CONTRAST_LOW" in {item["code"] for item in warning["warnings"]}
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "contrast warning reviewed"),
    )
    assert released.status_code == 201, released.text


def test_ready_check_blocks_invalid_or_missing_after_success_page(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    pages = {
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "components": [
                    {
                        "id": "submit",
                        "type": "form",
                        "props": {"afterSuccess": "page:../admin"},
                    },
                    {
                        "id": "next",
                        "type": "action_button",
                        "props": {"afterSuccess": "page:missing"},
                    },
                ],
            },
            {
                "id": "review",
                "title": "Review",
                "components": [
                    {
                        "id": "approve",
                        "type": "action_button",
                        "props": {"afterSuccess": "page:home"},
                    }
                ],
            },
        ]
    }
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages),
    )
    assert saved.status_code == 200, saved.text

    check = client.get(f"/experiences/{experience_id}/ready-check").json()
    assert {
        "AFTER_SUCCESS_INVALID",
        "AFTER_SUCCESS_PAGE_MISSING",
    } <= {item["code"] for item in check["blockers"]}
    blocked_release = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "invalid navigation"),
    )
    assert blocked_release.status_code == 409

    pages["pages"][0]["components"][0]["props"]["afterSuccess"] = "result"
    pages["pages"][0]["components"][1]["props"]["afterSuccess"] = "page:review"
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages, revision=2),
    )
    assert saved.status_code == 200, saved.text
    valid_codes = {
        item["code"]
        for item in client.get(f"/experiences/{experience_id}/ready-check").json()["blockers"]
    }
    assert "AFTER_SUCCESS_INVALID" not in valid_codes
    assert "AFTER_SUCCESS_PAGE_MISSING" not in valid_codes
    assert "ACTION_BINDING_MISSING" in valid_codes
