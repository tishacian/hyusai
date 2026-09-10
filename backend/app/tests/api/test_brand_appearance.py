import pytest
from pydantic import ValidationError

from app.models.audit import AuditLog
from app.models.experience import ExperienceRelease
from app.models.workspace import WorkspaceMember
from app.schemas.brand_appearance import validate_appearance
from app.tests.api.test_adoption_roadmap import auth_client
from app.tests.api.test_experiences_api import (
    _client,
    _create_body,
    _draft_body,
    _pages,
    _release_body,
    _seed,
)


@pytest.mark.parametrize("appearance", [
    {"accent": "url(evil)"}, {"palette": "nawa"}, {"corners": "1000px"},
    {"css": "body{}"}, {"logo": "javascript:alert(1)"},
    {"logo": "//example.test/logo"}, {"logo": "data:image/svg+xml;base64,AAAA"},
    {"logo": "data:image/png;base64,AAAA"},
])
def test_rejects_unbounded_or_invalid_brand_input(appearance):
    with pytest.raises((ValueError, ValidationError)):
        validate_appearance(appearance)


def test_workspace_brand_is_atomic_scoped_and_admin_only(db_session):
    workspace, user = _seed(db_session)
    workspace.settings = {**workspace.settings, "unrelated": {"keep": True}, "workspace_app_brand": {"style": "sentinel"}}
    db_session.commit()
    client = auth_client(db_session, workspace, user)
    url = f"/auth/workspaces/{workspace.slug}"
    brand = {"label": "NorthForge", "emblem": "/assets/logo.png", "appearance": {"palette": "graphite", "accent": "#e8543a"}}
    response = client.patch(url, json={"platform_brand": brand, "expected_platform_brand": None})
    assert response.status_code == 200, response.text
    audit = db_session.query(AuditLog).filter_by(event_type="workspace.brand.updated").one()
    assert audit.actor == user.id
    assert "emblem" in audit.details["changed_fields"]
    assert "data:image" not in str(audit.details)
    assert response.json()["settings"]["unrelated"] == {"keep": True}
    assert response.json()["settings"]["workspace_app_brand"] == {"style": "sentinel"}
    assert client.patch(url, json={"platform_brand": None, "expected_platform_brand": None}).status_code == 409
    assert client.patch(url, json={"platform_brand": brand}).status_code == 422
    bad = {**brand, "appearance": {"accent": "red; color: white"}}
    assert client.patch(url, json={"settings": {"platform_brand": bad}}).status_code == 422
    assert client.patch("/auth/workspaces/other", json={"platform_brand": brand, "expected_platform_brand": None}).status_code == 404
    member = db_session.query(WorkspaceMember).filter_by(workspace_id=workspace.id, user_id=user.id).one()
    member.role = "member"
    member.role_template = "workspace_viewer"
    user.role = "member"
    db_session.commit()
    assert client.patch(url, json={"platform_brand": None, "expected_platform_brand": brand}).status_code == 403
    assert workspace.settings["platform_brand"] == brand


def test_application_brand_is_validated_and_frozen_in_release(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    theme = {"mode": "dark", "appearance": {"palette": "graphite", "accent": "#e8543a", "logo": "/brand.png"}}
    created = client.post('/experiences', json=_create_body(theme=theme))
    assert created.status_code == 201, created.text
    identifier = created.json()['id']
    assert client.put(f'/experiences/{identifier}/draft', json=_draft_body(_pages('header'))).status_code == 200
    release = client.post(f'/experiences/{identifier}/releases', json=_release_body(client, identifier, 'Brand preview accepted'))
    assert release.status_code == 201, release.text
    detail = client.get(f'/experiences/{identifier}').json()
    updated = client.patch(f'/experiences/{identifier}', json={"theme": {"mode": "light", "appearance": {}}, "expected_updated_at": detail['updated_at']})
    assert updated.status_code == 200, updated.text
    frozen = db_session.get(ExperienceRelease, release.json()['id'])
    assert frozen.theme == theme
    invalid = client.patch(f'/experiences/{identifier}', json={"theme": {"appearance": {"palette": "nawa"}}, "expected_updated_at": updated.json()['updated_at']})
    assert invalid.status_code == 422
