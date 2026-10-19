from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ml_models, workspace_jobs
from app.core.config import settings
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.tests.services import test_ml_shadow

pair = test_ml_shadow.pair


@pytest.fixture
def api(db_session, pair):
    user = User(
        id=str(uuid4()),
        username="shadow-" + uuid4().hex,
        email=uuid4().hex + "@example.test",
        role="user",
    )
    db_session.add(user)
    db_session.flush()
    member = WorkspaceMember(
        workspace_id=pair[0].id,
        user_id=user.id,
        role="member",
        role_template="workspace_contributor",
    )
    db_session.add(member)
    db_session.commit()
    app = FastAPI()
    app.include_router(ml_models.router, prefix="/models")
    app.include_router(workspace_jobs.router, prefix="/jobs")
    for module in (ml_models, workspace_jobs):
        app.dependency_overrides[module.get_current_workspace] = lambda: pair[0]
        app.dependency_overrides[module.get_current_user] = lambda: user
        app.dependency_overrides[module.get_db] = lambda: db_session
    with TestClient(app) as client:
        yield client, user, member


def test_config_is_explicit_preserves_train_params_and_visible_without_predictions(
    api, pair, db_session
):
    client, _, _ = api
    model = pair[1]
    model.params_json = {"knobs": {"max_iter": 20}, "mlops": {"monitoring": {"enabled": True}}}
    db_session.commit()
    result = client.get(f"/models/{model.id}/monitoring").json()["monitoring"]
    assert result["window"]["predictions"] == 0
    assert (
        result["shadow"]["config"]["enabled"] is False and result["shadow"]["can_configure"] is True
    )
    response = client.post(f"/models/{model.id}/shadow", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["shadow"]["config"] == {
        "enabled": True,
        "sample_percent": 10,
        "timeout_s": 15,
    }
    db_session.refresh(model)
    assert model.params_json["knobs"] == {"max_iter": 20}
    assert model.params_json["mlops"]["monitoring"] == {"enabled": True}


def test_legacy_source_exposes_readiness_refuses_enable_and_allows_disable(api, pair, db_session):
    client, _, _ = api
    model = pair[1]
    model.metrics_json = {"primary": {"key": "roc_auc", "value": 0.8}}
    db_session.commit()
    block = client.get(f"/models/{model.id}/monitoring").json()["monitoring"]["shadow"]
    assert block["readiness"] == {"can_enable": False, "reason": "ML_ARTIFACT_LEGACY_UNSUPPORTED"}
    assert block["can_configure"] is True
    response = client.post(f"/models/{model.id}/shadow", json={"enabled": True})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ML_ARTIFACT_LEGACY_UNSUPPORTED"
    assert client.post(f"/models/{model.id}/shadow", json={"enabled": False}).status_code == 200
    assert model.metrics_json == {"primary": {"key": "roc_auc", "value": 0.8}}
    assert model.is_champion


def test_shadow_api_explains_selection_while_registry_keeps_its_score_rank(api, pair, db_session):
    from copy import deepcopy

    client, _, _ = api
    primary, legacy = pair[1:]
    candidate = test_ml_shadow.add_candidate(db_session, legacy)
    metadata = deepcopy(legacy.metrics_json)
    metadata["artifact"].pop("contract_version")
    legacy.metrics_json = metadata
    db_session.commit()
    response = client.post(f"/models/{primary.id}/shadow", json={"enabled": True})
    assert response.status_code == 200
    block = response.json()["shadow"]
    assert block["challenger"] == {"id": candidate.id, "version": 3}
    assert block["selection"]["excluded"] == [
        {"id": legacy.id, "version": 2, "reason": "ML_ARTIFACT_LEGACY_UNSUPPORTED"}
    ]
    assert block["readiness"]["can_enable"] is True
    from app.services.tabular_ml import runner_up

    assert runner_up(db_session, primary).id == legacy.id
    assert primary.is_champion


@pytest.mark.parametrize("role", ["workspace_viewer", "viewer"])
def test_read_only_roles_cannot_configure(api, pair, db_session, role):
    client, _, member = api
    member.role_template, member.role = (
        (role, "member") if role.startswith("workspace_") else (None, role)
    )
    db_session.commit()
    response = client.post(f"/models/{pair[1].id}/shadow", json={"enabled": True})
    assert response.status_code == 403
    assert (
        client.get(f"/models/{pair[1].id}/monitoring").json()["monitoring"]["shadow"][
            "can_configure"
        ]
        is False
    )


@pytest.mark.parametrize("enforced", [False, True])
def test_reviewer_can_configure_shadow_under_m1_role_contract(
    api, pair, db_session, monkeypatch, enforced
):
    # M1's explicit role matrix grants shadow configuration to reviewers,
    # independently of the report/enforcement rollout switch.
    monkeypatch.setattr(settings, "ml_rbac_enforced", enforced)
    client, _, member = api
    member.role_template, member.role = "workspace_reviewer", "member"
    db_session.commit()
    body = {"enabled": True, "sample_percent": 25, "timeout_s": 20}
    response = client.post(f"/models/{pair[1].id}/shadow", json=body)
    assert response.status_code == 200
    assert response.json()["shadow"]["can_configure"] is True
    assert response.json()["shadow"]["config"] == body
    db_session.expire(pair[1])
    assert pair[1].params_json["mlops"]["shadow"] == body
    shadow = client.get(f"/models/{pair[1].id}/monitoring").json()["monitoring"]["shadow"]
    assert shadow["can_configure"] is True
    assert shadow["config"] == body


@pytest.mark.parametrize(
    "body",
    [
        {"enabled": "true"},
        {"enabled": True, "sample_percent": 0},
        {"enabled": True, "sample_percent": 101},
        {"enabled": True, "timeout_s": 61},
        {"enabled": True, "timeout_s": True},
        {"enabled": True, "challenger_id": "forged"},
    ],
)
def test_limits_and_extra_authority_fields_are_rejected(api, pair, body):
    assert api[0].post(f"/models/{pair[1].id}/shadow", json=body).status_code == 422


def test_cross_workspace_and_non_tabular_model_are_refused(api, pair, db_session):
    client, _, _ = api
    other = Workspace(id=str(uuid4()), slug=uuid4().hex, name="Private")
    db_session.add(other)
    db_session.flush()
    pair[2].workspace_id = other.id
    db_session.commit()
    assert client.post(f"/models/{pair[2].id}/shadow", json={"enabled": True}).status_code == 404
    pair[1].family, pair[1].task = "forecasting", "forecasting"
    db_session.commit()
    assert client.post(f"/models/{pair[1].id}/shadow", json={"enabled": True}).status_code == 409


def test_shadow_job_is_not_forgeable_or_mutable_via_generic_api(api, pair, db_session):
    client, user, _ = api
    assert client.post("/jobs/", json={"kind": "ml_shadow", "title": "Forged"}).status_code == 403
    job = WorkspaceJob(
        workspace_id=pair[0].id,
        kind="ml_shadow",
        title="Real",
        created_by_user_id=user.id,
        status="queued",
    )
    db_session.add(job)
    db_session.commit()
    assert (
        client.post(
            f"/jobs/{job.id}/transition",
            json={"status": "completed", "result": {"predictions": []}},
        ).status_code
        == 403
    )
