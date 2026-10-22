"""Reloading Work reads a scoped result; it must never invoke an action."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.v1.endpoints import work as endpoint
from app.models.run import Run
from app.models.run_dispatch_outbox import RunDispatchOutbox
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.services import run_access
from app.services.experience import bindings as binding_service
from app.tests.api import test_work_api as helpers

PATH = "/work/password-reset/bindings/work.reset/runs"


def _action_pages(_key):
    return {
        "pages": [{
            "id": "home",
            "title": "Home",
            "components": [{
                "type": "action_button",
                "id": "reset-action",
                "props": {
                    "label": "Refresh",
                    "bindingKey": "work.reset",
                    "input": {"query": "prévision"},
                },
            }],
        }],
    }


@pytest.fixture()
def sample(db_session, monkeypatch):
    workspace, user = helpers._seed(db_session)
    system, version, binding = helpers._seed_binding(db_session, workspace, user)
    studio = helpers._experiences_client(db_session, workspace, user)
    with monkeypatch.context() as patch:
        patch.setattr(helpers, "_pages", _action_pages)
        experience_id, release_id = helpers._publish(studio, binding_key="work.reset")
    client = helpers._client(db_session, workspace, user, monkeypatch)
    return SimpleNamespace(
        workspace=workspace, user=user, system=system, version=version,
        binding=binding, studio=studio, client=client,
        experience_id=experience_id, release_id=release_id,
    )


def _invoke(sample, *, suffix="one", **changes):
    response = sample.client.post(
        PATH,
        json={
            "payload": {"query": "prévision"},
            "page_id": "home",
            "component_id": "reset-action",
            **changes,
        },
        headers={"Idempotency-Key": f"reload-action-{suffix}-0000001"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _latest(sample, **changes):
    return sample.client.get(
        PATH + "/latest",
        params={
            "page_id": "home",
            "component_id": "reset-action",
            "release_id": sample.release_id,
            **changes,
        },
    )


def test_reload_without_prior_action_is_empty_and_does_not_dispatch(sample, db_session):
    response = _latest(sample)
    assert response.status_code == 200, response.text
    assert response.json() == {"run": None}
    assert db_session.query(Run).count() == 0
    assert db_session.query(RunDispatchOutbox).count() == 0


@pytest.mark.parametrize(
    "status", ["pending", "running", "waiting_subflows", "hitl_pending", "completed", "failed", "cancelled"]
)
def test_reload_recovers_the_latest_status_instead_of_an_older_success(
    sample, db_session, monkeypatch, status
):
    older = db_session.get(Run, _invoke(sample, suffix="older"))
    newer = db_session.get(Run, _invoke(sample, suffix="newer"))
    older.status = "completed"
    older.started_at = datetime(2026, 1, 1)
    newer.status = status
    newer.started_at = older.started_at + timedelta(minutes=1)
    db_session.commit()
    before_dispatch = db_session.query(RunDispatchOutbox).count()
    monkeypatch.setattr(
        endpoint, "_ensure_work_dispatch", lambda *_: pytest.fail("GET dispatched a Run")
    )
    response = _latest(sample)
    assert response.status_code == 200, response.text
    assert response.json()["run"]["id"] == newer.id
    assert response.json()["run"]["status"] == status
    assert response.json()["run"]["experience_release_id"] == sample.release_id
    assert db_session.query(Run).count() == 2
    assert db_session.query(RunDispatchOutbox).count() == before_dispatch


@pytest.mark.parametrize(
    "field",
    [
        "surface", "experience_id", "experience_release_id", "channel", "binding_key",
        "page_id", "component_id", "request_sha256",
    ],
)
def test_reload_rejects_another_provenance_scope(sample, db_session, field):
    run = db_session.get(Run, _invoke(sample))
    changed = deepcopy(run.input_ref)
    changed["_ingress"]["adapter"][field] = "different"
    run.input_ref = changed
    db_session.commit()
    assert _latest(sample).json() == {"run": None}


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_id", "another-workspace"),
        ("system_id", None),
        ("published_flow_version_id", None),
        ("flow_sha256", None),
        ("execution_surface", "workbench"),
        ("initiated_by_user_id", None),
    ],
)
def test_reload_rejects_another_run_scope(sample, db_session, field, value):
    run = db_session.get(Run, _invoke(sample))
    setattr(run, field, value)
    db_session.commit()
    assert _latest(sample).json() == {"run": None}


def test_reload_requires_the_released_ingress(sample, db_session):
    run = db_session.get(Run, _invoke(sample))
    changed = deepcopy(run.input_ref)
    changed["_ingress"]["ingress_id"] = "another-source"
    run.input_ref = changed
    db_session.commit()
    assert _latest(sample).json() == {"run": None}


def test_a_teammates_result_is_the_teams_last_result(sample, db_session):
    run = db_session.get(Run, _invoke(sample))
    other = User(id="other-work-reader", username="other", email="other@example.invalid")
    db_session.add(other)
    db_session.add(WorkspaceMember(
        workspace_id=sample.workspace.id, user_id=other.id,
        role="member", role_template="workspace_contributor",
    ))
    db_session.flush()
    run.initiated_by_user_id = other.id
    db_session.commit()
    # The app's last result is shared with the team, and says who started it.
    body = _latest(sample).json()["run"]
    assert body["id"] == run.id
    assert body["started_by_reader"] is False
    assert body["started_by"] == "other"


def test_runtime_input_override_is_not_the_released_actions_result(sample, db_session):
    _invoke(sample, payload={"query": "another customer"})
    assert _latest(sample).json() == {"run": None}


def test_current_run_read_permission_is_rechecked(sample, monkeypatch):
    _invoke(sample)
    checks = []

    def deny(_db, **kwargs):
        checks.append(kwargs["run"].id)
        return SimpleNamespace(
            effective_allowed=False, legacy_allowed=False,
            v2_allowed=False, mode="compat", deny_reason="test",
        )

    monkeypatch.setattr(run_access, "resolve_run_read", deny)
    monkeypatch.setattr(run_access, "emit_shadow_diff_summary", lambda **_: None)
    assert _latest(sample).json() == {"run": None}
    assert len(checks) == 1


def test_release_race_is_explicit_and_does_not_return_other_results(sample):
    _invoke(sample)
    response = _latest(sample, release_id="different-release")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "WORK_RELEASE_CHANGED"


def test_fixed_action_lookup_does_not_resume_forms(db_session, monkeypatch):
    workspace, user = helpers._seed(db_session)
    helpers._seed_binding(db_session, workspace, user)
    _, release_id = helpers._publish(
        helpers._experiences_client(db_session, workspace, user), binding_key="work.reset"
    )
    client = helpers._client(db_session, workspace, user, monkeypatch)
    response = client.get(
        PATH + "/latest",
        params={"page_id": "home", "component_id": "reset-form", "release_id": release_id},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "WORK_RUN_RESUME_UNSUPPORTED"


def test_confirmation_is_derived_from_the_frozen_binding(db_session, monkeypatch):
    workspace, user = helpers._seed(db_session)
    helpers._seed_binding(db_session, workspace, user)
    binding_service.update_binding(
        db_session, workspace=workspace, binding_key="work.reset",
        confirmation_policy="confirm",
    )
    db_session.commit()
    studio = helpers._experiences_client(db_session, workspace, user)
    with monkeypatch.context() as patch:
        patch.setattr(helpers, "_pages", _action_pages)
        _, release_id = helpers._publish(studio, binding_key="work.reset")
    sample = SimpleNamespace(
        client=helpers._client(db_session, workspace, user, monkeypatch),
        release_id=release_id,
    )
    run_id = _invoke(sample, confirmed=True)
    response = _latest(sample)
    assert response.status_code == 200, response.text
    assert response.json()["run"]["id"] == run_id


def _member(db_session, workspace, user_id, template):
    user = User(id=user_id, username=user_id, email=f"{user_id}@example.invalid", role="member")
    db_session.add_all([
        user,
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member", role_template=template),
    ])
    db_session.commit()
    return user


def test_team_result_is_not_shown_outside_the_apps_audience(db_session, monkeypatch):
    workspace, admin = helpers._seed(db_session)
    helpers._seed_binding(db_session, workspace, admin)
    studio = helpers._experiences_client(db_session, workspace, admin)
    with monkeypatch.context() as patch:
        patch.setattr(helpers, "_pages", _action_pages)
        _experience_id, release_id = helpers._publish(
            studio, binding_key="work.reset", audience={"roles": ["workspace_admin"]}
        )
    admin_client = helpers._client(db_session, workspace, admin, monkeypatch)
    started = admin_client.post(
        PATH,
        json={"payload": {"query": "prévision"}, "page_id": "home", "component_id": "reset-action"},
        headers={"Idempotency-Key": "team-audience-000000001"},
    )
    assert started.status_code == 201, started.text
    outsider = _member(db_session, workspace, "work-outsider", "workspace_viewer")
    response = helpers._client(db_session, workspace, outsider, monkeypatch).get(
        PATH + "/latest",
        params={"page_id": "home", "component_id": "reset-action", "release_id": release_id},
    )
    assert response.status_code in {403, 404}
    assert "prévision" not in response.text


def test_team_result_never_crosses_workspaces(sample, db_session):
    run = db_session.get(Run, _invoke(sample))
    run.workspace_id = "another-workspace"
    db_session.commit()
    assert _latest(sample).json() == {"run": None}


def test_my_own_result_is_marked_as_mine(sample):
    run_id = _invoke(sample)
    body = _latest(sample).json()["run"]
    assert body["id"] == run_id
    assert body["started_by_reader"] is True
