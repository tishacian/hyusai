"""The "record_follow_up" Studio block: catalog 0.3.0, chosen only when used."""

from app.models.experience import DEFAULT_RENDERER_VERSION, RENDERER_VERSION_0_3, renderer_version_for
from app.models.experience import ExperienceRelease
from app.services.experience import lifecycle
from app.tests.api import test_work_api as helpers


def _form(component_id="reset-form", key="work.reset"):
    return {"type": "form", "id": component_id, "props": {"bindingKey": key, "schema": helpers._input_schema()}}


def _follow_up(**props):
    base = {"followBindingKey": "work.reset", "recordField": "query", "recordSource": {"kind": "url"}}
    return {"type": "record_follow_up", "id": "follow-up", "props": {**base, **props}}


def _pages_with(*components):
    return {"pages": [{"id": "home", "title": "Home", "components": list(components)}]}


def test_only_a_release_using_the_block_is_pinned_to_catalog_0_3():
    assert renderer_version_for(_pages_with(_form())) == DEFAULT_RENDERER_VERSION
    assert renderer_version_for(_pages_with(_form(), _follow_up())) == RENDERER_VERSION_0_3
    assert renderer_version_for(None) == DEFAULT_RENDERER_VERSION


def test_a_published_follow_up_block_releases_on_catalog_0_3(db_session, monkeypatch):
    workspace, user = helpers._seed(db_session)
    helpers._seed_binding(db_session, workspace, user)
    studio = helpers._experiences_client(db_session, workspace, user)
    with monkeypatch.context() as patch:
        patch.setattr(helpers, "_pages", lambda key: _pages_with(_form(key=key), _follow_up()))
        _, release_id = helpers._publish(studio, binding_key="work.reset")
    assert db_session.get(ExperienceRelease, release_id).renderer_version == RENDERER_VERSION_0_3


def test_an_app_without_the_block_keeps_catalog_0_2(db_session, monkeypatch):
    workspace, user = helpers._seed(db_session)
    helpers._seed_binding(db_session, workspace, user)
    studio = helpers._experiences_client(db_session, workspace, user)
    _, release_id = helpers._publish(studio, binding_key="work.reset")
    assert db_session.get(ExperienceRelease, release_id).renderer_version == DEFAULT_RENDERER_VERSION


def test_the_block_is_configured_by_selection_only():
    issues = lambda *components: [i["message"] for i in lifecycle._record_follow_up_issues(_pages_with(*components))]
    assert issues(_form(), _follow_up()) == []
    assert issues(_form(), _follow_up(recordSource={"kind": "action", "componentId": "reset-form"})) == []
    assert issues(_follow_up()) == ["followBindingKey must name an action of this application."]
    assert issues(_form(), _follow_up(followBindingKey="other.key")) == ["followBindingKey must name an action of this application."]
    assert issues(_form(), _follow_up(recordField="not_an_input")) == ["recordField must be an input field of the followed action."]
    assert issues(_form(), _follow_up(recordSource={"kind": "free_json"})) == [
        "recordSource must be the page address or an action of this application."
    ]
    assert issues(_form(), _follow_up(recordSource={"kind": "action", "componentId": "elsewhere"})) == [
        "recordSource must name a form or action on the followed binding."
    ]
    fixed = {"type": "action_button", "id": "go", "props": {"bindingKey": "work.reset", "input": {"query": "x"}}}
    assert issues(fixed, _follow_up(recordSource={"kind": "action", "componentId": "go"})) == []
