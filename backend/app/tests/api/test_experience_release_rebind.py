"""Refresh immutable Work release bindings without publishing a pending draft."""

from __future__ import annotations

import copy

import pytest

from app.api.v1.endpoints import experiences as endpoint
from app.models.audit import AuditLog
from app.models.experience import ExperienceRelease
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.flow_contracts import canonical_sha256
from app.tests.api.test_experiences_api import (
    _bound_form_pages,
    _client,
    _create_body,
    _draft_body,
    _pages,
    _release_body,
    _seed,
)


@pytest.fixture
def released_app(db_session, monkeypatch):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    schema = {"type": "object", "properties": {}}
    binding = {
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
    issues = []

    def resolved(_db, *, workspace, key):
        del _db, workspace
        if issues:
            return None, issues[0]
        return {
            "status": "ok",
            "binding": {**binding, "binding_key": key},
            "input_schema": schema,
            "reasons": [],
        }, None

    monkeypatch.setattr(endpoint.experience_service, "_resolve_referenced", resolved)
    experience_id = client.post("/experiences", json=_create_body()).json()["id"]
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_bound_form_pages("demo.submit", schema), ["demo.submit"]),
    )
    assert saved.status_code == 200, saved.text
    released = client.post(
        f"/experiences/{experience_id}/releases",
        json=_release_body(client, experience_id, "source content"),
    )
    assert released.status_code == 201, released.text
    return workspace, user, client, experience_id, released.json(), binding, issues


def _rebind_path(experience_id, source):
    return f"/experiences/{experience_id}/releases/{source['id']}"


def _rebind_body(client, experience_id, source):
    ready = client.get(_rebind_path(experience_id, source) + "/rebind-ready-check")
    assert ready.status_code == 200, ready.text
    check = ready.json()
    return {
        "notes": "Refresh the reviewed release bindings only",
        "expected_source_release_sha256": check["source_release_sha256"],
        "expected_content_sha256": check["source_content_sha256"],
        "expected_experience_updated_at": check["experience_updated_at"],
        "expected_bindings_sha256": check["bindings_sha256"],
    }


def test_rebind_preserves_pending_draft_metadata_and_source_release(released_app, db_session):
    _workspace, _user, client, experience_id, source, binding, _issues = released_app
    detail = client.get(f"/experiences/{experience_id}").json()
    saved = client.put(
        f"/experiences/{experience_id}/draft",
        json=_draft_body(_pages("callout"), revision=detail["draft"]["revision"]),
    )
    assert saved.status_code == 200, saved.text
    changed = client.patch(
        f"/experiences/{experience_id}",
        json={
            "name": "Pending new name",
            "theme": {"mode": "new-pending-theme"},
            "access_policy": {"roles": ["workspace_admin"]},
            "expected_updated_at": detail["updated_at"],
        },
    )
    assert changed.status_code == 200, changed.text
    before = client.get(f"/experiences/{experience_id}").json()
    binding.update(published_flow_version_id="version-2", flow_sha256="b" * 64)
    body = _rebind_body(client, experience_id, source)
    response = client.post(_rebind_path(experience_id, source) + "/rebind", json=body)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["id"] != source["id"]
    assert result["release_number"] == source["release_number"] + 1
    for field in (
        "pages",
        "content_sha256",
        "identity_snapshot",
        "access_snapshot",
        "languages",
        "theme",
        "renderer_version",
    ):
        assert result[field] == source[field], field
    assert result["bindings_snapshot"][0]["published_flow_version_id"] == "version-2"
    assert client.get(f"/experiences/{experience_id}").json() == before
    old = client.get(f"/experiences/{experience_id}/releases").json()["releases"][1]
    assert old == source
    retry = client.post(_rebind_path(experience_id, source) + "/rebind", json=body)
    assert retry.json()["id"] == result["id"]
    assert db_session.query(ExperienceRelease).count() == 2
    audits = db_session.query(AuditLog).filter(AuditLog.event_type == "experience.released").all()
    assert len(audits) == 2
    assert audits[-1].details["source_release_id"] == source["id"]
    assert audits[-1].details["draft_preserved"] is True


@pytest.mark.parametrize("field", ["expected_content_sha256", "expected_source_release_sha256"])
def test_rebind_refuses_unreviewed_source(released_app, db_session, field):
    _workspace, _user, client, experience_id, source, _binding, _issues = released_app
    body = _rebind_body(client, experience_id, source)
    body[field] = "0" * 64
    response = client.post(_rebind_path(experience_id, source) + "/rebind", json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EXPERIENCE_SOURCE_RELEASE_CONFLICT"
    assert db_session.query(ExperienceRelease).count() == 1


def test_rebind_refuses_binding_changed_after_review(released_app, db_session):
    _workspace, _user, client, experience_id, source, binding, _issues = released_app
    body = _rebind_body(client, experience_id, source)
    binding.update(published_flow_version_id="version-2", flow_sha256="b" * 64)
    response = client.post(_rebind_path(experience_id, source) + "/rebind", json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EXPERIENCE_BINDINGS_CONFLICT"
    assert db_session.query(ExperienceRelease).count() == 1


def test_rebind_runs_same_readiness_validation(released_app, db_session):
    _workspace, _user, client, experience_id, source, _binding, issues = released_app
    body = _rebind_body(client, experience_id, source)
    issues.append({"code": "BINDING_DRIFT", "message": "Published version changed."})
    ready = client.get(_rebind_path(experience_id, source) + "/rebind-ready-check").json()
    assert ready["ready"] is False
    response = client.post(_rebind_path(experience_id, source) + "/rebind", json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EXPERIENCE_NOT_READY"
    assert db_session.query(ExperienceRelease).count() == 1


def test_rebind_refuses_metadata_changed_after_review(released_app, db_session):
    _workspace, _user, client, experience_id, source, _binding, _issues = released_app
    body = _rebind_body(client, experience_id, source)
    response = client.patch(
        f"/experiences/{experience_id}",
        json={"name": "New name", "expected_updated_at": body["expected_experience_updated_at"]},
    )
    assert response.status_code == 200
    response = client.post(_rebind_path(experience_id, source) + "/rebind", json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "EXPERIENCE_METADATA_CONFLICT"
    assert db_session.query(ExperienceRelease).count() == 1


def test_rebind_refuses_source_from_another_experience(released_app):
    _workspace, _user, client, experience_id, source, _binding, _issues = released_app
    other = client.post("/experiences", json=_create_body(slug="other-app")).json()["id"]
    body = _rebind_body(client, experience_id, source)
    for suffix, request in (("/rebind-ready-check", client.get), ("/rebind", client.post)):
        kwargs = {"json": body} if suffix == "/rebind" else {}
        response = request(_rebind_path(other, source) + suffix, **kwargs)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "EXPERIENCE_RELEASE_NOT_FOUND"


def test_rebind_refuses_cross_workspace_source(released_app, db_session):
    _workspace, user, client, experience_id, source, _binding, _issues = released_app
    other = Workspace(
        id="other-workspace",
        name="Other",
        slug="other",
        settings={"features": {"experience_v1": True}},
    )
    db_session.add(other)
    db_session.add(
        WorkspaceMember(
            workspace_id=other.id, user_id=user.id, role="admin", role_template="workspace_admin"
        )
    )
    db_session.commit()
    other_client = _client(db_session, other, user)
    own_id = other_client.post("/experiences", json=_create_body()).json()["id"]
    body = _rebind_body(client, experience_id, source)
    response = other_client.post(_rebind_path(own_id, source) + "/rebind", json=body)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "EXPERIENCE_RELEASE_NOT_FOUND"


def test_rebind_enforces_release_role_and_rejects_content_override(released_app, db_session):
    workspace, _user, client, experience_id, source, _binding, _issues = released_app
    user = User(
        id="contributor", username="contributor", email="contributor@example.invalid", role="member"
    )
    db_session.add(user)
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="member",
            role_template="workspace_contributor",
        )
    )
    db_session.commit()
    body = _rebind_body(client, experience_id, source)
    response = _client(db_session, workspace, user).post(
        _rebind_path(experience_id, source) + "/rebind", json=body
    )
    assert response.status_code == 403
    forged = copy.deepcopy(body)
    forged["pages"] = _pages("callout")
    assert (
        client.post(_rebind_path(experience_id, source) + "/rebind", json=forged).status_code == 422
    )
    assert db_session.query(ExperienceRelease).count() == 1
