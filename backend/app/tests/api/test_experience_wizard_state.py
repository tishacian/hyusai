from app.models.experience import ExperienceWizardState
from app.models.system_binding import SystemBinding
from app.tests.api.test_experiences_api import _client, _create_body, _seed

STAGED = {
    "binding_key": "procedures.ask",
    "system_id": "system-procedures",
    "published_flow_version_id": "version-1",
    "ingress_id": "ask",
    "confirmation_policy": "confirm",
    "on_unavailable": "unavailable",
}


def _created(client):
    created = client.post("/experiences", json=_create_body(slug="procedures"))
    assert created.status_code == 201, created.text
    return created.json()


def test_wizard_progress_survives_a_reload_without_creating_bindings(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience = _created(client)
    url = f"/experiences/{experience['id']}/wizard"

    assert client.get(url).json() == {"wizard": None}
    saved = client.put(
        url,
        json={
            "step": 2,
            "staged_bindings": [STAGED],
            "audience": {"roles": ["workspace_viewer"], "groups": [], "whole_workspace": False},
        },
    )
    assert saved.status_code == 200, saved.text
    wizard = client.get(url).json()["wizard"]
    assert wizard["step"] == 2
    assert wizard["staged_bindings"] == [STAGED]
    assert wizard["audience"] == {
        "roles": ["workspace_viewer"],
        "groups": [],
        "whole_workspace": False,
    }
    assert db_session.query(SystemBinding).count() == 0
    listed = client.get("/experiences").json()["experiences"]
    assert [(row["id"], row["wizard_step"]) for row in listed] == [(experience["id"], 2)]
    # The wizard's own write does not move the application's concurrency stamp.
    assert (
        client.get(f"/experiences/{experience['id']}").json()["updated_at"]
        == experience["updated_at"]
    )


def test_finalizing_the_draft_clears_the_wizard_progress(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience = _created(client)
    url = f"/experiences/{experience['id']}/wizard"
    assert client.put(url, json={"step": 3}).status_code == 200
    body = {
        "pages": {
            "pages": [
                {"id": "home", "title": "Home", "components": [{"type": "header", "id": "h"}]}
            ]
        },
        "binding_keys": [],
        "expected_revision": 1,
        "bindings": [],
        "languages": ["en"],
        "theme": {},
        "access_policy": {"roles": []},
        "expected_experience_updated_at": experience["updated_at"],
    }
    finalized = client.put(f"/experiences/{experience['id']}/draft/finalize", json=body)
    assert finalized.status_code == 200, finalized.text
    assert client.get(url).json() == {"wizard": None}
    assert db_session.query(ExperienceWizardState).count() == 0


def test_invalid_progress_is_refused(db_session):
    workspace, user = _seed(db_session)
    client = _client(db_session, workspace, user)
    experience = _created(client)
    url = f"/experiences/{experience['id']}/wizard"
    assert client.put(url, json={"step": 4}).status_code == 422
    assert client.put(url, json={"step": 2, "staged_bindings": [STAGED, STAGED]}).status_code == 422
    assert client.put(url, json={"step": 2, "audience": {"roles": [""]}}).status_code == 422
    assert client.put(url, json={"step": 2, "extra": True}).status_code == 422
    assert client.put("/experiences/missing/wizard", json={"step": 1}).status_code == 404


def test_a_viewer_can_neither_read_nor_write_wizard_progress(db_session):
    workspace, user = _seed(db_session, role_template="workspace_viewer")
    client = _client(db_session, workspace, user)
    assert client.get("/experiences/any/wizard").status_code == 403
    assert client.put("/experiences/any/wizard", json={"step": 1}).status_code == 403
