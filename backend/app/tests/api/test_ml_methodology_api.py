"""UI and Skill methods share contracts without another orchestration API."""

from app.models.tabular import MLModel
from app.tests.api.test_ml_models_api import client, dataset, user, workspace  # noqa: F401
from app.tests.services.test_ml_methodology import complete_frame


def test_method_routes_validate_and_never_train(client, dataset, db_session):
    payload = complete_frame(dataset)
    for path in ("problem-frame", "experiment-plan"):
        response = client.post(f"/ml-models/methodology/{path}", json=payload)
        assert response.status_code == 200, response.text
        assert response.json()["mode"] == "proposal_only"
        assert db_session.query(MLModel).count() == 0
        forbidden = client.post(
            f"/ml-models/methodology/{path}", json={**payload, "workspace_id": "foreign"}
        )
        assert forbidden.status_code == 422


def test_method_routes_refuse_unknown_or_wrong_dataset_version(client, dataset):
    payload = complete_frame(dataset)
    payload["dataset"]["version"] += 1
    response = client.post("/ml-models/methodology/problem-frame", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ML_METHOD_DATASET_VERSION_MISMATCH"
    payload["dataset"]["id"] = "foreign"
    response = client.post("/ml-models/methodology/experiment-plan", json=payload)
    assert response.status_code == 404


def test_method_routes_honor_rollout_switch(client, dataset, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ml_methodology_enabled", False)
    for path in ("problem-frame", "experiment-plan"):
        response = client.post(f"/ml-models/methodology/{path}", json=complete_frame(dataset))
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "ML_METHODOLOGY_DISABLED"
