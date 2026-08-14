"""Experience draft / release / deploy — gated by experience_v1."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import experiences as endpoint
from app.models.audit import AuditLog
from app.models.experience import Experience, ExperienceDeployment, ExperienceRelease
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
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
        "slug": "password-reset",
        "pattern": "form_result",
        "languages": ["en"],
        "theme": {},
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


def _draft_body(pages: dict, binding_keys: list[str] | None = None, *, revision: int = 1) -> dict:
    return {
        "pages": pages,
        "binding_keys": binding_keys or [],
        "expected_revision": revision,
    }


def _release_body(client: TestClient, experience_id: str, notes: str) -> dict:
    draft = client.get(f"/experiences/{experience_id}").json()["draft"]
    return {
        "notes": notes,
        "expected_draft_revision": draft["revision"],
        "expected_content_sha256": draft["content_sha256"],
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


def test_experience_audit_lists_prefix_and_delete_emits(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("form")),
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
        json=_draft_body(_pages("form")),
    ).status_code == 200
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "live"),
    )
    assert released.status_code == 201, released.text
    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "live", "release_id": released.json()["id"]},
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


def test_release_does_not_deploy(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("form", "action_button")),
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
    assert released.json()["renderer_version"] == "certified-components-0.1.0"
    assert listed.json()["releases"][0]["id"] == released.json()["id"]
    assert detail.json()["deployments"] == []
    assert db_session.query(ExperienceDeployment).count() == 0
    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.released")
        .one()
    )
    assert audit.details["release_id"] == released.json()["id"]


def test_deploy_pilot_and_rollback(db_session) -> None:
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    created = client.post("/experiences", json=_create_body())
    experience_id = created.json()["id"]
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("form")),
    ).status_code == 200
    first = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "r1"),
    )
    assert first.status_code == 201, first.text
    assert client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("form", "result"), revision=2),
    ).status_code == 200
    second = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "r2"),
    )
    assert second.status_code == 201, second.text

    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "pilot", "release_id": first.json()["id"]},
    )
    updated = client.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "pilot", "release_id": second.json()["id"]},
    )
    rolled = client.post(f"/experiences/{experience_id}/deployments/pilot/rollback")

    assert deployed.status_code == 201, deployed.text
    assert deployed.json()["channel"] == "pilot"
    assert deployed.json()["release_id"] == first.json()["id"]
    assert updated.status_code == 201
    assert updated.json()["release_id"] == second.json()["id"]
    assert updated.json()["previous_release_id"] == first.json()["id"]
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["release_id"] == first.json()["id"]
    assert db_session.query(ExperienceDeployment).count() == 1
    assert (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.deployed")
        .count()
        == 2
    )
    rollback_audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.event_type == "experience.rolled_back")
        .one()
    )
    assert rollback_audit.details["release_id"] == first.json()["id"]


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
        json=_draft_body(_pages("form")),
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
        json=_draft_body(_pages("form")),
    )
    stale_save = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("result")),
    )
    stale_release = client.post(
        f"/experiences/{experience_id}/releases",
        json={
            "notes": "stale",
            "expected_draft_revision": 1,
            "expected_content_sha256": saved.json()["content_sha256"],
        },
    )
    wrong_hash = client.post(
        f"/experiences/{experience_id}/releases",
        json={
            "notes": "wrong hash",
            "expected_draft_revision": saved.json()["revision"],
            "expected_content_sha256": "0" * 64,
        },
    )

    assert stale_save.status_code == 409
    assert stale_save.json()["detail"]["code"] == "EXPERIENCE_DRAFT_REVISION_CONFLICT"
    assert stale_release.status_code == 409
    assert stale_release.json()["detail"]["current_revision"] == saved.json()["revision"]
    assert wrong_hash.status_code == 409
    assert wrong_hash.json()["detail"]["code"] == "EXPERIENCE_DRAFT_CONTENT_CONFLICT"


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
        json=_draft_body(_pages("form")),
    )
    release = client.post(
        f"/experiences/{experience_id}/releases",
        json={
            "notes": "pilot",
            "expected_draft_revision": saved.json()["revision"],
            "expected_content_sha256": saved.json()["content_sha256"],
        },
    )
    assert client.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "pilot", "release_id": release.json()["id"]},
    ).status_code == 201

    assert client.delete(f"/experiences/{experience_id}").json()["detail"]["code"] == "EXPERIENCE_DEPLOYED"
    blocked_pilot_slug = client.patch(
        f"/experiences/{experience_id}", json={"slug": "new-password-reset"}
    )
    assert blocked_pilot_slug.status_code == 409
    assert blocked_pilot_slug.json()["detail"]["code"] == "EXPERIENCE_DEPLOYED_SLUG_IMMUTABLE"
    assert client.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "live", "release_id": release.json()["id"]},
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
        json={
            "notes": "old URL",
            "expected_draft_revision": saved.json()["revision"],
            "expected_content_sha256": saved.json()["content_sha256"],
        },
    )
    assert release.json()["identity_snapshot"] == {
        "name": "Password reset",
        "slug": "password-reset",
        "pattern": "form_result",
    }
    assert client.patch(
        f"/experiences/{experience_id}", json={"slug": "renamed-reset"}
    ).status_code == 200

    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "pilot", "release_id": release.json()["id"]},
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
        json={
            "notes": "access frozen",
            "expected_draft_revision": saved.json()["revision"],
            "expected_content_sha256": saved.json()["content_sha256"],
        },
    )
    deployed = client.post(
        f"/experiences/{experience_id}/deployments",
        json={"channel": "live", "release_id": released.json()["id"]},
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
                    {"id": " action ", "type": "form"},
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
        json=_draft_body(pages, ["missing.query"]),
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

    pages["pages"][0]["components"][1]["props"]["dataBinding"] = {
        "source": "system-binding",
        "componentId": "action",
        "selector": "__proto__.value",
    }
    pages["pages"][0]["components"][2]["props"]["queryBinding"]["source"] = "run-output"
    pages["pages"][0]["components"][2]["props"]["sourceComponentId"] = "missing"
    malformed = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(pages, ["missing.query"], revision=2),
    )
    assert malformed.status_code == 200, malformed.text
    invalid_codes = {
        item["code"]
        for item in client.get(f"/experiences/{experience_id}/ready-check").json()["blockers"]
    }
    assert {"QUERY_BINDING_INVALID", "DATA_BINDING_INVALID", "SOURCE_COMPONENT_INVALID"} <= invalid_codes


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
    assert {item["code"] for item in check["blockers"]} == {
        "AFTER_SUCCESS_INVALID",
        "AFTER_SUCCESS_PAGE_MISSING",
    }
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
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "valid navigation"),
    )
    assert released.status_code == 201, released.text
