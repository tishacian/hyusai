"""Counterfactual search (M5): planted rules, minimality, budget, refusals, rights.

The models are fitted by the production harness on frames whose label is a
known rule, so "what flips the answer" has a right answer to check against.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.ml_governance import MLAdmissionCounter
from app.models.run import Run
from app.models.tabular import MLModel, MLPrediction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import tabular_predict
from app.services.ml import counterfactuals
from app.services.tabular_datasets import TabularError
from app.services.tabular_ml import upload_model_dir
from app.tests.ml_artifacts import churn_frame, fit_churn_artifact

pytest.importorskip("polars")
pytest.importorskip("skrub")
pytest.importorskip("mlflow.sklearn")

ROWS = 600


def _and_rule():
    """Churn exactly when prepaid AND tenure under four years: one change flips it."""

    frame = churn_frame(ROWS)
    frame["churn"] = ((frame["plan"] == "prepaid") & (frame["tenure_months"] < 48)).astype(int)
    return frame


def _or_rule():
    """Churn when prepaid OR tenure under four years: only both changes flip it."""

    frame = churn_frame(ROWS)
    frame["churn"] = ((frame["plan"] == "prepaid") | (frame["tenure_months"] < 48)).astype(int)
    return frame


def _linear_value():
    frame = churn_frame(ROWS)
    frame["arpu"] = 50.0 + 2.0 * frame["tenure_months"]
    return frame


@pytest.fixture(scope="module")
def and_model(tmp_path_factory):
    return fit_churn_artifact(tmp_path_factory.mktemp("cf-and"), frame=_and_rule())


@pytest.fixture(scope="module")
def or_model(tmp_path_factory):
    return fit_churn_artifact(tmp_path_factory.mktemp("cf-or"), frame=_or_rule())


@pytest.fixture(scope="module")
def value_model(tmp_path_factory):
    return fit_churn_artifact(
        tmp_path_factory.mktemp("cf-value"), task="regression", target="arpu", frame=_linear_value()
    )


def _user(db_session, workspace, role_template):
    user = User(
        id=str(uuid4()),
        username="cf-" + uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    if role_template:
        db_session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role="member",
                role_template=role_template,
            )
        )
    db_session.commit()
    return user


@pytest.fixture()
def workspace(db_session) -> Workspace:
    row = Workspace(id=uuid4().hex, name="CF", slug=f"cf-{uuid4().hex[:8]}", settings={})
    db_session.add(row)
    db_session.commit()
    actor = _user(db_session, row, "workspace_contributor")
    db_session.add(Run(id=row.id, workspace_id=row.id, initiated_by_user_id=actor.id))
    db_session.commit()
    return row


@pytest.fixture(autouse=True)
def serving(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    tabular_predict.reset_cache()
    yield
    tabular_predict.reset_cache()


def _register(db_session, workspace, artifact, *, task="classification", target="churn"):
    directory, summary = artifact
    model = MLModel(
        id=uuid4().hex,
        workspace_id=workspace.id,
        name="Counterfactual",
        slug=f"cf-{uuid4().hex[:6]}",
        version=1,
        task=task,
        algo="gradient_boosting",
        target=target,
        features=[spec["name"] for spec in summary["signature"]["inputs"]],
        params_json={},
        status="ready",
        row_count=ROWS,
        metrics_json=summary["metrics"],
        signature_json=summary["signature"],
        input_example_json=summary["input_example"],
        classes_json=summary["classes"],
        is_champion=True,
    )
    db_session.add(model)
    db_session.flush()
    uri, size = upload_model_dir(directory, workspace_id=workspace.id, model_id=model.id)
    model.model_uri, model.artifact_bytes = uri, size
    model.trained_at = datetime(2026, 9, 1, 9, 30)
    db_session.commit()
    return model


ROW = {"plan": "prepaid", "tenure_months": 6.0, "arpu": 80.0, "support_tickets": 1.0}


def _bounds(model, name):
    spec = next(item for item in model.signature_json["inputs"] if item["name"] == name)
    return spec["min"], spec["max"]


def test_one_change_flips_a_planted_and_rule_nearest_first(db_session, workspace, and_model):
    model = _register(db_session, workspace, and_model)
    result = counterfactuals.search(db_session, model, ROW, fields=["plan", "tenure_months"])

    assert result["current"]["prediction"] == "1"
    # Binary: "anything else" is the other class, named so its probability reads.
    assert result["target"] == {"class": "0"}
    assert result["status"] == "found"
    results = result["results"]
    assert 1 <= len(results) <= settings.ml_counterfactual_max_results
    assert all(item["changed_fields"] == 1 for item in results)
    assert all(item["prediction"] == "0" and item["probability"] > 0.5 for item in results)
    distances = [item["distance"] for item in results]
    assert distances == sorted(distances)
    # Diverse: both declared fields appear, not three neighbouring tenures.
    assert {item["changes"][0]["field"] for item in results} == {"plan", "tenure_months"}
    tenure = next(item for item in results if item["changes"][0]["field"] == "tenure_months")
    assert tenure["changes"][0]["from"] == 6.0
    assert tenure["changes"][0]["to"] >= 40  # the learned boundary sits near 48
    plan = next(item for item in results if item["changes"][0]["field"] == "plan")
    assert plan["changes"][0]["to"] in {"hybrid", "postpaid"}
    # The nearest tenure change is closer than any categorical change (1.0).
    assert results[0]["changes"][0]["field"] == "tenure_months"


def test_a_planted_or_rule_needs_both_changes_and_never_a_superset(db_session, workspace, or_model):
    model = _register(db_session, workspace, or_model)
    result = counterfactuals.search(
        db_session, model, ROW, fields=["plan", "tenure_months", "support_tickets"]
    )
    assert result["status"] == "found"
    for item in result["results"]:
        fields = {change["field"] for change in item["changes"]}
        # Neither change alone flips an OR rule, and tickets are irrelevant, so
        # every minimal answer changes exactly plan and tenure.
        assert fields == {"plan", "tenure_months"}
        assert item["changed_fields"] == 2
        assert item["prediction"] == "0"
    distances = [item["distance"] for item in result["results"]]
    assert distances == sorted(distances)


def test_numbers_proposed_never_leave_the_training_range(db_session, workspace, and_model):
    model = _register(db_session, workspace, and_model)
    result = counterfactuals.search(
        db_session, model, {**ROW, "arpu": 150.0}, fields=["tenure_months", "arpu"]
    )
    for item in result["results"]:
        for change in item["changes"]:
            low, high = _bounds(model, change["field"])
            assert low <= change["to"] <= high
    spec = next(item for item in model.signature_json["inputs"] if item["name"] == "tenure_months")
    values, scale, reason = counterfactuals.candidate_values(spec, 6.0)
    assert reason is None and scale == {"low": spec["min"], "high": spec["max"]}
    assert all(spec["min"] <= value <= spec["max"] for value in values)
    # Months were whole numbers at fit time; the grid stays whole.
    assert all(float(value).is_integer() for value in values)
    assert 6.0 not in values


def test_the_candidate_budget_is_a_hard_ceiling(db_session, workspace, or_model, monkeypatch):
    monkeypatch.setattr(settings, "ml_counterfactual_max_candidates", 5)
    monkeypatch.setattr(settings, "ml_counterfactual_batch_rows", 2)
    model = _register(db_session, workspace, or_model)
    result = counterfactuals.search(db_session, model, ROW, fields=["plan", "tenure_months"])
    assert result["evaluated"] == 5
    assert result["exhausted"] is True
    assert result["budget"] == 5


def test_a_regression_reaches_a_value_range(db_session, workspace, value_model):
    model = _register(db_session, workspace, value_model, task="regression", target="arpu")
    row = {"plan": "hybrid", "tenure_months": 6.0, "support_tickets": 1.0}
    result = counterfactuals.search(
        db_session, model, row, fields=["tenure_months"], target={"min": 150.0}
    )
    assert result["status"] == "found"
    assert result["current"]["prediction"] < 150.0
    for item in result["results"]:
        assert item["prediction"] >= 150.0
        assert item["changes"][0]["to"] >= 45  # arpu = 50 + 2 × tenure


def test_an_answer_already_on_target_is_said_so(db_session, workspace, and_model):
    model = _register(db_session, workspace, and_model)
    result = counterfactuals.search(db_session, model, ROW, fields=["plan"], target={"class": "1"})
    assert result["status"] == "already_reached"
    assert result["results"] == [] and result["evaluated"] == 0


def test_fields_without_training_facts_are_refused_with_their_reason():
    assert counterfactuals.candidate_values({"name": "at", "type": "datetime"}, None)[2] == (
        "unsupported_kind"
    )
    assert counterfactuals.candidate_values({"name": "n", "type": "double"}, 1.0)[2] == "no_range"
    assert (
        counterfactuals.candidate_values({"name": "n", "type": "double", "min": 3, "max": 3}, 3)[2]
        == "constant"
    )
    assert (
        counterfactuals.candidate_values(
            {"name": "note", "type": "string", "kind": "category"}, "x"
        )[2]
        == "no_levels"
    )
    values, _, reason = counterfactuals.candidate_values({"name": "b", "type": "boolean"}, True)
    assert reason is None and values == [False]


def test_a_search_with_no_usable_field_is_refused(db_session, workspace, and_model):
    model = _register(db_session, workspace, and_model)
    contract = dict(model.signature_json)
    contract["inputs"] = [
        {key: value for key, value in spec.items() if key not in {"min", "max", "choices"}}
        for spec in contract["inputs"]
    ]
    model.signature_json = contract
    db_session.commit()
    with pytest.raises(TabularError) as raised:
        counterfactuals.search(db_session, model, ROW, fields=["plan", "arpu"])
    assert raised.value.code == "ML_COUNTERFACTUAL_FIELDS_UNSUPPORTED"
    assert raised.value.details == {
        "refused": [
            {"field": "plan", "reason": "no_levels"},
            {"field": "arpu", "reason": "no_range"},
        ]
    }


@pytest.mark.parametrize(
    ("fields", "target", "code"),
    [
        (
            ["plan", "arpu", "tenure_months", "support_tickets"],
            None,
            "ML_COUNTERFACTUAL_FIELDS_INVALID",
        ),
        (["plan", "plan"], None, "ML_COUNTERFACTUAL_FIELDS_INVALID"),
        (["zip_code"], None, "ML_COUNTERFACTUAL_FIELD_UNKNOWN"),
        (["plan"], {"class": "maybe"}, "ML_COUNTERFACTUAL_TARGET_INVALID"),
    ],
)
def test_malformed_searches_are_refused_with_a_code(
    db_session, workspace, and_model, fields, target, code
):
    model = _register(db_session, workspace, and_model)
    with pytest.raises(TabularError) as raised:
        counterfactuals.search(db_session, model, ROW, fields=fields, target=target)
    assert raised.value.code == code


def test_a_regression_without_a_range_is_refused(db_session, workspace, value_model):
    model = _register(db_session, workspace, value_model, task="regression", target="arpu")
    row = {"plan": "hybrid", "tenure_months": 6.0, "support_tickets": 1.0}
    with pytest.raises(TabularError) as raised:
        counterfactuals.search(db_session, model, row, fields=["tenure_months"])
    assert raised.value.code == "ML_COUNTERFACTUAL_TARGET_INVALID"


def test_candidates_are_never_journalled_and_cost_one_admitted_row(
    db_session, workspace, and_model
):
    model = _register(db_session, workspace, and_model)
    result = counterfactuals.search(db_session, model, ROW, fields=["plan", "tenure_months"])
    assert result["evaluated"] > 1
    assert db_session.query(MLPrediction).count() == 0
    counters = db_session.query(MLAdmissionCounter).all()
    assert [(row.requests, row.rows) for row in counters] == [(1, 1)]


def test_admission_still_applies(db_session, workspace, and_model, monkeypatch):
    monkeypatch.setattr(settings, "ml_predict_rate_per_minute", 1)
    model = _register(db_session, workspace, and_model)
    counterfactuals.search(db_session, model, ROW, fields=["plan"])
    with pytest.raises(TabularError) as raised:
        counterfactuals.search(db_session, model, ROW, fields=["plan"])
    assert raised.value.code == "ML_RATE_LIMITED" and raised.value.status_code == 429


# ---------------------------------------------------------------------------
# Rights, through HTTP
# ---------------------------------------------------------------------------


@pytest.fixture()
def api(db_session, monkeypatch):
    from app.api.v1.endpoints import ml_explanations

    monkeypatch.setattr(settings, "ml_rbac_enforced", True)
    app = FastAPI()
    app.include_router(ml_explanations.router, prefix="/ml-models")
    app.dependency_overrides[ml_explanations.get_db] = lambda: db_session
    return app, ml_explanations


def _as(api, workspace, user):
    app, module = api
    app.dependency_overrides[module.get_current_workspace] = lambda: workspace
    app.dependency_overrides[module.get_current_user] = lambda: user
    return TestClient(app)


def test_a_viewer_may_ask_and_an_outsider_may_not(db_session, workspace, and_model, api):
    model = _register(db_session, workspace, and_model)
    body = {"row": ROW, "fields": ["plan"], "target": {"class": "0"}}

    viewer = _user(db_session, workspace, "workspace_viewer")
    answer = _as(api, workspace, viewer).post(f"/ml-models/{model.id}/counterfactuals", json=body)
    assert answer.status_code == 200, answer.text
    assert answer.json()["status"] == "found"

    outsider = _user(db_session, workspace, None)
    refused = _as(api, workspace, outsider).post(
        f"/ml-models/{model.id}/counterfactuals", json=body
    )
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "ML_FORBIDDEN_ACTION"


def test_the_route_validates_its_shape_and_takes_no_api_key(db_session, workspace, and_model, api):
    model = _register(db_session, workspace, and_model)
    viewer = _user(db_session, workspace, "workspace_viewer")
    client = _as(api, workspace, viewer)
    too_many = client.post(
        f"/ml-models/{model.id}/counterfactuals",
        json={"row": ROW, "fields": ["plan", "arpu", "tenure_months", "support_tickets"]},
    )
    assert too_many.status_code == 422
    app, module = api
    app.dependency_overrides.pop(module.get_current_user)
    app.dependency_overrides.pop(module.get_current_workspace)
    keyed = TestClient(app).post(
        f"/ml-models/{model.id}/counterfactuals",
        json={"row": ROW, "fields": ["plan"]},
        headers={"X-API-Key": "agpk_not-a-session"},
    )
    assert keyed.status_code in {401, 403}
