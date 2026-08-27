"""The serving contract over HTTP: who may call, in what shape, and what returns.

One route answers predictions — ``POST /ml-models/{id}/predict`` — and it accepts
two ways of proving who you are: the workspace session the Playground already
has, or a model-scoped ``X-API-Key`` a customer's system holds. These tests are
about that seam, plus the shape of the request: MLflow's ``{"inputs": [...]}``,
because the cURL on the demo slide has to be the one that actually runs.

The model is fitted for real, once for the module, so the request path is
exercised end to end rather than against a stub that would agree with anything.
See :mod:`app.tests.ml_artifacts`.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ml_models as ml_models_api
from app.core.config import settings
from app.models.skill import Skill
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import Workspace
from app.services import tabular_predict
from app.services.tabular_ml import upload_model_dir
from app.tests.ml_artifacts import CHURN_FEATURES, CHURN_ROWS, fit_churn_artifact

pytest.importorskip("polars")
pytest.importorskip("skrub")
pytest.importorskip("mlflow.sklearn")

FEATURES = [name for name in CHURN_FEATURES if name != "churn"]


@pytest.fixture(scope="module")
def churn_artifact(tmp_path_factory) -> tuple[Path, dict]:
    return fit_churn_artifact(tmp_path_factory.mktemp("serving-api-fit"))


@pytest.fixture()
def workspace(db_session) -> Workspace:
    row = Workspace(
        id=str(uuid4()),
        name="Serving API",
        slug=f"serving-api-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def user(db_session) -> User:
    token = uuid4().hex[:8]
    row = User(
        id=str(uuid4()),
        username=f"serving-{token}",
        email=f"serving-{token}@example.invalid",
        role="user",
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def app_and_client(db_session, tmp_path, monkeypatch):
    """The router with only the database wired: authentication stays real.

    Deliberately no auth overrides here, so the tests below can tell a caller
    that proved something from one that proved nothing — which is the whole
    subject of this module.
    """

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    tabular_predict.reset_cache()
    app = FastAPI()
    app.include_router(ml_models_api.router, prefix="/ml-models")
    app.dependency_overrides[ml_models_api.get_db] = lambda: db_session
    yield app, TestClient(app)
    tabular_predict.reset_cache()


@pytest.fixture()
def session_client(app_and_client, workspace, user) -> TestClient:
    """A client whose caller is a workspace session, as the Playground's is.

    ``predict_caller`` is overridden alongside the two session dependencies,
    because it resolves them itself in order to be able to fall back to a key.
    """

    app, client = app_and_client
    app.dependency_overrides[ml_models_api.get_current_workspace] = lambda: workspace
    app.dependency_overrides[ml_models_api.get_current_user] = lambda: user
    app.dependency_overrides[ml_models_api.predict_caller] = (
        lambda: ml_models_api.PredictCaller(
            workspace_id=workspace.id, kind="session", user_id=user.id
        )
    )
    return client


@pytest.fixture()
def key_client(app_and_client) -> TestClient:
    """A client with no session at all: whatever authenticates must be the key."""

    return app_and_client[1]


@pytest.fixture()
def model(db_session, workspace, churn_artifact, app_and_client) -> MLModel:
    directory, summary = churn_artifact
    row = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Churn risk",
        slug="churn-risk",
        version=1,
        task="classification",
        algo="gradient_boosting",
        target="churn",
        features=FEATURES,
        params_json={"knobs": {"max_iter": 25}},
        status="ready",
        dataset_slug="churn-features",
        row_count=CHURN_ROWS,
        test_size=0.25,
        cross_validation=0,
        metrics_json=summary["metrics"],
        signature_json=summary["signature"],
        input_example_json=summary["input_example"],
        classes_json=summary["classes"],
        is_champion=True,
    )
    db_session.add(row)
    db_session.flush()
    uri, size = upload_model_dir(
        directory, workspace_id=workspace.id, model_id=row.id
    )
    row.model_uri = uri
    row.artifact_bytes = size
    db_session.commit()
    return row


def _row(**overrides) -> dict:
    body = {"plan": "prepaid", "tenure_months": 6, "arpu": 41.5, "support_tickets": 3}
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# The request shape
# ---------------------------------------------------------------------------


def test_the_mlflow_serving_shape_is_what_the_endpoint_takes(session_client, model):
    response = session_client.post(
        f"/ml-models/{model.id}/predict", json={"inputs": [_row()]}
    )

    assert response.status_code == 200
    body = response.json()
    # `predictions` is MLflow's response key too, so a client written against
    # `mlflow models serve` reads this answer without a translation layer.
    assert body["predictions"][0]["prediction"] in {"0", "1"}
    assert 0.0 <= body["predictions"][0]["confidence"] <= 1.0
    assert body["served"]["model_id"] == model.id
    assert body["served"]["version"] == 1


@pytest.mark.parametrize("field", ["inputs", "dataframe_records", "rows"])
def test_every_accepted_spelling_of_the_batch_reaches_the_model(
    session_client, model, field
):
    response = session_client.post(
        f"/ml-models/{model.id}/predict", json={field: [_row()]}
    )

    assert response.status_code == 200
    assert response.json()["rows"] == 1


def test_an_unknown_body_field_is_refused_rather_than_ignored(session_client, model):
    response = session_client.post(
        f"/ml-models/{model.id}/predict",
        json={"inputs": [_row()], "temperature": 0.7},
    )

    assert response.status_code == 422


def test_a_field_the_model_never_saw_is_a_422_that_names_it(session_client, model):
    response = session_client.post(
        f"/ml-models/{model.id}/predict",
        json={"inputs": [{**_row(), "roaming": True}]},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "ML_PREDICT_FIELD_UNKNOWN"
    assert "roaming" in detail["message"]


def test_a_missing_field_is_refused_instead_of_being_scored_as_a_hole(
    session_client, model
):
    response = session_client.post(
        f"/ml-models/{model.id}/predict", json={"inputs": [{"plan": "prepaid"}]}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ML_PREDICT_FIELD_MISSING"


@pytest.fixture(scope="module")
def narrow_artifact(tmp_path_factory) -> tuple[Path, dict]:
    """A second fit of the same lineage on two of the four columns.

    Versions of a model are not obliged to agree on a feature list — a later fit
    is often exactly a different one — and that disagreement is what makes the
    difference between the alias and a named version observable.
    """

    return fit_churn_artifact(
        tmp_path_factory.mktemp("serving-api-narrow"),
        features=["plan", "tenure_months", "churn"],
    )


@pytest.fixture()
def challenger(db_session, workspace, narrow_artifact, model) -> MLModel:
    """A v2 of ``model``'s lineage, not champion, fitted on fewer columns."""

    directory, summary = narrow_artifact
    row = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Churn risk",
        slug=model.slug,
        version=2,
        task="classification",
        algo="gradient_boosting",
        target="churn",
        features=["plan", "tenure_months"],
        params_json={"knobs": {"max_iter": 25}},
        status="ready",
        dataset_slug="churn-features",
        row_count=CHURN_ROWS,
        test_size=0.25,
        cross_validation=0,
        metrics_json=summary["metrics"],
        signature_json=summary["signature"],
        input_example_json=summary["input_example"],
        classes_json=summary["classes"],
        is_champion=False,
    )
    db_session.add(row)
    db_session.flush()
    uri, size = upload_model_dir(directory, workspace_id=workspace.id, model_id=row.id)
    row.model_uri = uri
    row.artifact_bytes = size
    db_session.commit()
    return row


def test_the_serving_block_offers_this_versions_contract_and_names_the_champion(
    session_client, model, challenger
):
    """Why a card off the alias has to name itself: the block it renders is its own.

    The Playground builds its form from ``fields``, and on v2's card those are
    v2's two columns while the version that answers by default is still v1 with
    four. A form the plane would refuse is the money shot of the demo failing.
    """

    block = session_client.get(f"/ml-models/{challenger.id}").json()["serving"]

    assert [field["name"] for field in block["fields"]] == ["plan", "tenure_months"]
    assert block["is_serving"] is False
    assert block["serving_version"] == 1
    assert block["serving_model_id"] == model.id


def test_a_row_for_a_version_off_the_alias_is_refused_unless_that_version_is_named(
    session_client, challenger
):
    row = {"plan": "prepaid", "tenure_months": 6}

    # Unpinned the alias answers, and the alias is v1, which was fitted on four
    # columns: v2's row is missing two of them and is rightly refused.
    unpinned = session_client.post(
        f"/ml-models/{challenger.id}/predict", json={"inputs": [row]}
    )
    assert unpinned.status_code == 422
    assert unpinned.json()["detail"]["code"] == "ML_PREDICT_FIELD_MISSING"

    # Named, the version the card is about answers, and its own contract is the
    # one the row is judged against.
    pinned = session_client.post(
        f"/ml-models/{challenger.id}/predict", json={"inputs": [row], "version": 2}
    )
    assert pinned.status_code == 200
    body = pinned.json()
    assert body["served"]["version"] == 2
    assert body["served"]["model_id"] == challenger.id
    assert body["predictions"][0]["prediction"] in {"0", "1"}


def test_naming_the_champions_own_version_is_accepted_too(
    session_client, model, challenger
):
    """So the pin is not a special case the serving card has to avoid."""

    response = session_client.post(
        f"/ml-models/{model.id}/predict", json={"inputs": [_row()], "version": 1}
    )

    assert response.status_code == 200
    assert response.json()["served"]["version"] == 1


def test_an_explanation_is_returned_only_when_the_caller_asks_for_one(
    session_client, model
):
    plain = session_client.post(
        f"/ml-models/{model.id}/predict", json={"inputs": [_row()]}
    ).json()
    explained = session_client.post(
        f"/ml-models/{model.id}/predict",
        json={"inputs": [_row(support_tickets=6, tenure_months=2)], "explain": True},
    ).json()

    assert "contributions" not in plain["predictions"][0]
    contributions = explained["predictions"][0]["contributions"]
    assert contributions and contributions[0]["field"] in FEATURES


# ---------------------------------------------------------------------------
# Who may call
# ---------------------------------------------------------------------------


def test_a_scoped_key_calls_the_endpoint_without_any_workspace_session(
    db_session, key_client, model
):
    _key, secret = tabular_predict.mint_api_key(db_session, model=model, name="CRM")

    response = key_client.post(
        f"/ml-models/{model.id}/predict",
        json={"inputs": [_row()]},
        headers={"X-API-Key": secret},
    )

    assert response.status_code == 200
    assert response.json()["predictions"][0]["prediction"] in {"0", "1"}


def test_no_credential_at_all_is_a_401(key_client, model):
    response = key_client.post(
        f"/ml-models/{model.id}/predict", json={"inputs": [_row()]}
    )

    assert response.status_code == 401


@pytest.mark.parametrize("presented", ["agpk_not-a-real-key", "garbage"])
def test_a_secret_that_was_never_minted_is_a_401(key_client, model, presented):
    response = key_client.post(
        f"/ml-models/{model.id}/predict",
        json={"inputs": [_row()]},
        headers={"X-API-Key": presented},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "ML_KEY_INVALID"


def test_a_revoked_key_stops_answering_immediately(db_session, key_client, model):
    key, secret = tabular_predict.mint_api_key(db_session, model=model)
    tabular_predict.revoke_api_key(db_session, model=model, key_id=key.id)

    response = key_client.post(
        f"/ml-models/{model.id}/predict",
        json={"inputs": [_row()]},
        headers={"X-API-Key": secret},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "ML_KEY_REVOKED"


def test_a_key_is_scoped_to_its_own_model_and_cannot_call_a_sibling(
    db_session, key_client, workspace, model, churn_artifact
):
    """The property that makes minting one key per model mean anything."""

    directory, summary = churn_artifact
    other = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="ARPU forecast",
        slug="arpu-forecast",
        version=1,
        task="classification",
        algo="gradient_boosting",
        target="churn",
        features=FEATURES,
        status="ready",
        metrics_json=summary["metrics"],
        signature_json=summary["signature"],
        classes_json=summary["classes"],
        is_champion=True,
    )
    db_session.add(other)
    db_session.flush()
    uri, _size = upload_model_dir(
        directory, workspace_id=workspace.id, model_id=other.id
    )
    other.model_uri = uri
    db_session.commit()
    _key, secret = tabular_predict.mint_api_key(db_session, model=model)

    response = key_client.post(
        f"/ml-models/{other.id}/predict",
        json={"inputs": [_row()]},
        headers={"X-API-Key": secret},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ML_KEY_WRONG_MODEL"


def test_a_key_only_opens_the_predict_route_and_nothing_else(
    db_session, key_client, model
):
    _key, secret = tabular_predict.mint_api_key(db_session, model=model)
    headers = {"X-API-Key": secret}

    # No other route on this API reads the header, so a leaked prediction key
    # cannot list the registry or mint itself a second credential.
    assert key_client.get("/ml-models", headers=headers).status_code == 401
    assert key_client.get(f"/ml-models/{model.id}", headers=headers).status_code == 401
    assert (
        key_client.post(f"/ml-models/{model.id}/keys", json={}, headers=headers)
    ).status_code == 401


def test_a_session_cannot_predict_with_a_model_of_another_workspace(
    db_session, session_client, churn_artifact
):
    other = Workspace(
        id=str(uuid4()), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={}
    )
    db_session.add(other)
    db_session.commit()
    foreign = MLModel(
        id=str(uuid4()),
        workspace_id=other.id,
        name="Foreign",
        slug="foreign",
        version=1,
        task="classification",
        algo="linear",
        target="churn",
        features=FEATURES,
        status="ready",
        signature_json=churn_artifact[1]["signature"],
    )
    db_session.add(foreign)
    db_session.commit()

    response = session_client.post(
        f"/ml-models/{foreign.id}/predict", json={"inputs": [_row()]}
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ML_MODEL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Keys, from the card
# ---------------------------------------------------------------------------


def test_minting_returns_the_secret_once_and_never_again(session_client, model):
    minted = session_client.post(
        f"/ml-models/{model.id}/keys", json={"name": "Demo cURL"}
    )

    assert minted.status_code == 200
    body = minted.json()
    secret = body["key"]["secret"]
    assert secret.startswith(tabular_predict.KEY_PREFIX)
    assert body["serving"]["endpoint"].endswith(f"/ml-models/{model.id}/predict")
    assert body["serving"]["key_header"] == "X-API-Key"

    listed = session_client.get(f"/ml-models/{model.id}/keys").json()["serving"]
    assert [entry["name"] for entry in listed["keys"]] == ["Demo cURL"]
    # Only the prefix survives, which is what makes rotation the answer to a
    # lost key rather than a support request.
    assert all("secret" not in entry for entry in listed["keys"])
    assert listed["keys"][0]["prefix"] == secret[:12]


def test_revoking_a_key_from_the_card_keeps_it_visible_as_revoked(
    session_client, model
):
    key = session_client.post(f"/ml-models/{model.id}/keys", json={}).json()["key"]

    response = session_client.delete(f"/ml-models/{model.id}/keys/{key['id']}")

    assert response.status_code == 200
    keys = response.json()["serving"]["keys"]
    assert [entry["revoked"] for entry in keys] == [True]


def test_a_key_of_another_model_cannot_be_revoked_through_this_one(
    db_session, session_client, workspace, model, churn_artifact
):
    other = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Other lineage",
        slug="other-lineage",
        version=1,
        task="classification",
        algo="linear",
        target="churn",
        features=FEATURES,
        status="ready",
        signature_json=churn_artifact[1]["signature"],
    )
    db_session.add(other)
    db_session.commit()
    key, _secret = tabular_predict.mint_api_key(db_session, model=other)

    response = session_client.delete(f"/ml-models/{model.id}/keys/{key.id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ML_KEY_NOT_FOUND"


# ---------------------------------------------------------------------------
# Publish as a Skill
# ---------------------------------------------------------------------------


def test_publishing_from_the_card_returns_the_skill_and_marks_the_lineage(
    db_session, session_client, model
):
    response = session_client.post(f"/ml-models/{model.id}/publish")

    assert response.status_code == 200
    body = response.json()
    skill = body["skill"]
    assert skill["slug"].endswith("predict_churn_risk")
    assert set(skill["input_schema"]["required"]) == set(FEATURES)
    # The card needs to know, on the same response, that it is now published.
    assert body["model"]["published_skill_slug"] == skill["slug"]
    assert body["serving"]["published_skill"]["slug"] == skill["slug"]
    assert db_session.query(Skill).filter(Skill.slug == skill["slug"]).count() == 1


def test_withdrawing_from_the_card_removes_it_from_the_catalog(
    db_session, session_client, model
):
    slug = session_client.post(f"/ml-models/{model.id}/publish").json()["skill"]["slug"]

    response = session_client.delete(f"/ml-models/{model.id}/publish")

    assert response.status_code == 200
    body = response.json()
    assert body["withdrawn"] == slug
    assert body["model"]["published_skill_slug"] is None
    assert db_session.query(Skill).filter(Skill.slug == slug).count() == 0


def test_serving_is_reported_as_off_when_the_plane_is_disabled(
    session_client, model, monkeypatch
):
    monkeypatch.setattr(settings, "ml_predict_enabled", False)

    block = session_client.get(f"/ml-models/{model.id}/keys").json()["serving"]

    # The card has to know before it renders a Predict button.
    assert block["enabled"] is False and block["callable"] is False
    response = session_client.post(
        f"/ml-models/{model.id}/predict", json={"inputs": [_row()]}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ML_PREDICT_DISABLED"
