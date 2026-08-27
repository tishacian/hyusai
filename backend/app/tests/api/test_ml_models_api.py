"""API surface for /ml-models: the catalog, the plan, training and the registry.

The fit itself is stubbed. What is under test here is the contract the Models
page and the training studio poll: that a bad choice is a *form* answer and not
a failed job, that a training request comes back as a row the UI can render
immediately, and that promoting or retiring a version is one call whose response
already carries the new lineage.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ml_models as ml_models_api
from app.core.config import settings
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import Workspace
from app.services import tabular_ml
from app.services.recipe_executions import SupervisedRun

pl = pytest.importorskip("polars")


@pytest.fixture()
def workspace(db_session) -> Workspace:
    ws = Workspace(
        id=str(uuid4()),
        name="Models API",
        slug=f"models-api-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(ws)
    db_session.commit()
    return ws


@pytest.fixture()
def user(db_session) -> User:
    token = uuid4().hex[:8]
    row = User(
        id=str(uuid4()),
        username=f"models-{token}",
        email=f"models-{token}@example.invalid",
        role="user",
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def client(db_session, workspace, user, tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    # Eager mode settles the run inline, so the API test observes the trained row.
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "ml_train_enabled", True)
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "ml_train_min_rows", 10)
    app = FastAPI()
    app.include_router(ml_models_api.router, prefix="/ml-models")
    app.dependency_overrides[ml_models_api.get_current_workspace] = lambda: workspace
    app.dependency_overrides[ml_models_api.get_current_user] = lambda: user
    app.dependency_overrides[ml_models_api.get_db] = lambda: db_session
    return TestClient(app)


def _frame(rows: int = 60):
    return pl.DataFrame(
        {
            "msisdn": [f"2126{index:07d}" for index in range(rows)],
            "plan": ["prepaid" if index % 3 else "postpaid" for index in range(rows)],
            "region": ["casablanca", "rabat", "tanger"] * (rows // 3),
            "tenure_months": [1 + (index * 7) % 90 for index in range(rows)],
            "arpu": [30.0 + (index % 17) * 4.5 for index in range(rows)],
            "churn": [1 if index % 4 == 0 else 0 for index in range(rows)],
        }
    )


@pytest.fixture()
def dataset(db_session, workspace, client):
    """A ready dataset in the workspace the client speaks for.

    Depends on ``client`` so the object store is already redirected at tmp_path
    when the Parquet is written.
    """

    from app.services.tabular_datasets import register_frame

    row = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Churn features",
        frame=_frame(),
        source="upload",
    )
    db_session.commit()
    return row


def _stub_harness(monkeypatch, *, exit_code: int = 0, status: str | None = None):
    """Stand in for the fit: write the artifact and the evidence a real run would."""

    summary = {
        "metrics": {
            "task": "classification",
            "primary": {"key": "roc_auc", "value": 0.88},
            "scores": [{"key": "roc_auc", "value": 0.88}],
            "confusion": {"labels": ["0", "1"], "matrix": [[9, 1], [2, 3]]},
            "curves": {"roc": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]},
            "rows": {"total": 60, "train": 45, "test": 15},
            "columns": {"used": ["arpu"], "dropped": []},
            "importances": [{"feature": "arpu", "value": 0.31}],
            "target": {"name": "churn", "classes": ["0", "1"], "positive": "1"},
        },
        "signature": {
            "inputs": [{"name": "arpu", "type": "double", "kind": "number"}],
            "output": {"task": "classification", "target": "churn"},
        },
        "classes": ["0", "1"],
        "input_example": [{"arpu": 42.0}],
    }

    def fake(argv, **kwargs):
        manifest = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        if exit_code == 0 and status is None:
            model_dir = Path(manifest["model_dir"])
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "MLmodel").write_text("flavors:\n  sklearn: {}\n", "utf-8")
            (model_dir / "model.skops").write_text("x" * 512, "utf-8")
            Path(argv[3]).write_text(json.dumps(summary), encoding="utf-8")
        return SupervisedRun(
            status=status,
            error=None,
            exit_code=exit_code,
            stdout_tail="",
            stderr_tail="" if exit_code == 0 else "ml_fit_failed: ValueError: nope",
        )

    monkeypatch.setattr(tabular_ml, "supervise_harness", fake)


def _train(client, dataset, **overrides):
    body = {"dataset_id": dataset.id, "target": "churn"}
    body.update(overrides)
    return client.post("/ml-models", json=body)


# ---------------------------------------------------------------------------
# Catalog and plan
# ---------------------------------------------------------------------------


def test_the_catalog_carries_the_algorithms_their_knobs_and_the_platform_limits(client):
    response = client.get("/ml-models/catalog")

    assert response.status_code == 200
    catalog = response.json()["catalog"]
    assert catalog["enabled"] is True
    assert catalog["tasks"] == ["classification", "regression"]
    # Ranked, so the first entry is the default the form opens on.
    assert catalog["algos"][0]["key"] == catalog["defaults"]["algo"]
    boosting = next(row for row in catalog["algos"] if row["key"] == "gradient_boosting")
    assert boosting["tasks"] == ["classification", "regression"]
    knob = next(row for row in boosting["knobs"] if row["key"] == "learning_rate")
    assert (knob["min"], knob["max"]) == (0.01, 0.5)
    # Bounds are the contract: a form field cannot be rendered without them.
    assert all({"min", "max", "default", "kind"} <= set(row) for row in boosting["knobs"])
    assert catalog["limits"]["max_classes"] >= 2


def test_plan_without_a_target_answers_with_the_candidate_columns(client, dataset):
    response = client.post("/ml-models/plan", json={"dataset_id": dataset.id})

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is None and body["refusal"] is None
    assert body["dataset"]["id"] == dataset.id
    columns = {row["name"]: row for row in body["columns"]}
    assert set(columns) == {
        "msisdn",
        "plan",
        "region",
        "tenure_months",
        "arpu",
        "churn",
    }
    # Each column already says which task it suggests, so the first click is informed.
    assert columns["churn"]["suggested_task"] == "classification"
    assert columns["arpu"]["suggested_task"] == "regression"
    assert columns["region"]["distinct"] == 3


def test_plan_columns_carry_the_profile_the_picker_draws(client, dataset):
    """Choosing a target is a judgement about a distribution, so it travels.

    The picker draws the same sparkline as the dataset page. Without the profile
    on the plan it would have to fetch the dataset a second time on every
    keystroke, or show typed names with no shape behind them.
    """

    body = client.post("/ml-models/plan", json={"dataset_id": dataset.id}).json()
    columns = {row["name"]: row for row in body["columns"]}

    # Numeric column: the histogram is what a sparkline is drawn from.
    arpu = columns["arpu"]["profile"]
    assert arpu["kind"] == "float"
    assert arpu["histogram"] and all(
        {"upper", "count"} <= set(bin_) for bin_ in arpu["histogram"]
    )
    assert arpu["min"] is not None and arpu["max"] is not None
    assert arpu["mean"] is not None

    # Categorical column: top values instead, same as the table header draws.
    region = columns["region"]["profile"]
    assert region["kind"] == "string"
    assert [entry["value"] for entry in region["top_values"]]
    assert sum(entry["count"] for entry in region["top_values"]) <= 60

    # And the flat fields the picker already showed stay where they were.
    assert columns["region"]["distinct"] == region["distinct"]
    assert columns["region"]["nulls"] == region["nulls"]


def test_a_plan_survives_a_dataset_whose_profile_was_never_computed(client, dataset, db_session):
    """A dataset ingested before profiling, or one the profiler gave up on.

    The picker must still list its columns: an empty profile draws no sparkline,
    which is the correct outcome, whereas a 500 here would take the whole
    training form down with it.
    """

    dataset.stats_json = None
    db_session.commit()

    response = client.post("/ml-models/plan", json={"dataset_id": dataset.id})

    assert response.status_code == 200
    columns = response.json()["columns"]
    assert len(columns) == 6
    assert all(row["profile"] == {} for row in columns)
    assert all(row["distinct"] == 0 and row["nulls"] == 0 for row in columns)
    # The suggestion comes from the schema, so it survives a missing profile.
    assert {row["name"]: row["suggested_task"] for row in columns}["arpu"] == "regression"


def test_plan_with_a_target_resolves_the_run_without_fitting_anything(client, dataset):
    response = client.post(
        "/ml-models/plan",
        json={"dataset_id": dataset.id, "target": "churn"},
    )

    assert response.status_code == 200
    plan = response.json()["plan"]
    assert plan["task"] == "classification"
    assert plan["target"] == "churn" and "churn" not in plan["features"]
    assert plan["estimator"].endswith("HistGradientBoostingClassifier")
    assert plan["knobs"]["max_iter"] == 150
    assert plan["rows"] == 60
    assert plan["name"] == "Churn features · churn"
    # An MSISDN is unique per row: it trains and generalizes not at all.
    assert [row["feature"] for row in plan["warnings"]] == ["msisdn"]
    # A plan is a dry run: nothing was staged.
    assert client.get("/ml-models").json()["models"] == []


def test_plan_renders_a_refusal_inline_instead_of_failing_the_request(client, dataset):
    response = client.post(
        "/ml-models/plan",
        json={"dataset_id": dataset.id, "target": "region", "task": "regression"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] is None
    assert body["refusal"]["code"] == "ML_TARGET_NOT_NUMERIC"
    assert "region" in body["refusal"]["message"]
    # The columns stay in the payload, so the form can keep offering alternatives.
    assert body["columns"]


def test_plan_on_an_unknown_dataset_is_a_coded_404(client):
    response = client.post("/ml-models/plan", json={"dataset_id": str(uuid4())})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DATASET_NOT_FOUND"


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def test_training_returns_the_settled_model_card_in_one_call(
    client, dataset, monkeypatch
):
    _stub_harness(monkeypatch)

    response = _train(client, dataset, algo="random_forest", cross_validation=3)

    assert response.status_code == 200
    model = response.json()["model"]
    assert model["status"] == "ready"
    assert model["version"] == 1 and model["slug"] == "churn-features-churn"
    assert model["task"] == "classification" and model["algo"] == "random_forest"
    assert model["is_champion"] is True  # nothing else serves this lineage
    assert model["primary_metric"] == {"key": "roc_auc", "value": 0.88}
    assert model["dataset_id"] == dataset.id
    # The detail projection carries what the card renders; the list one does not.
    assert model["metrics"]["confusion"]["labels"] == ["0", "1"]
    assert model["signature"]["inputs"][0]["name"] == "arpu"
    assert model["input_example"] == [{"arpu": 42.0}]
    assert model["classes"] == ["0", "1"]
    assert model["artifact_bytes"] > 0


def test_a_refused_training_request_is_a_form_error_and_stages_no_row(client, dataset):
    response = _train(client, dataset, target="msisdn", task="regression")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ML_TARGET_NOT_NUMERIC"
    assert client.get("/ml-models").json()["models"] == []


def test_a_failed_fit_settles_the_row_with_the_harness_reason(
    client, dataset, monkeypatch
):
    _stub_harness(monkeypatch, exit_code=1)

    model = _train(client, dataset).json()["model"]

    assert model["status"] == "failed"
    assert model["error"].startswith("ML_FIT_FAILED")
    assert model["is_champion"] is False
    assert model["model_uri"] is None


def test_the_list_is_workspace_scoped_filterable_and_carries_the_catalog(
    client, dataset, db_session, workspace, monkeypatch
):
    _stub_harness(monkeypatch)
    mine = _train(client, dataset).json()["model"]
    other = Workspace(
        id=str(uuid4()), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={}
    )
    db_session.add(other)
    db_session.commit()
    db_session.add(
        MLModel(
            id=str(uuid4()),
            workspace_id=other.id,
            name="Foreign",
            slug="foreign",
            version=1,
            task="classification",
            algo="linear",
            target="churn",
            features=["arpu"],
            status="ready",
        )
    )
    db_session.commit()

    listed = client.get("/ml-models").json()
    assert [row["id"] for row in listed["models"]] == [mine["id"]]
    # The list renders the studio too, so it ships the catalog with the rows.
    assert listed["catalog"]["algos"]
    # List rows stay light: the card's blocks are a detail read.
    assert "metrics" not in listed["models"][0]

    assert client.get("/ml-models?task=regression").json()["models"] == []
    assert client.get("/ml-models?status=failed").json()["models"] == []
    assert len(client.get(f"/ml-models?dataset_id={dataset.id}").json()["models"]) == 1


def test_the_detail_read_carries_the_dataset_and_every_version_of_the_lineage(
    client, dataset, monkeypatch
):
    _stub_harness(monkeypatch)
    first = _train(client, dataset).json()["model"]
    second = _train(client, dataset).json()["model"]

    response = client.get(f"/ml-models/{second['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["model"]["version"] == 2
    assert [row["version"] for row in body["versions"]] == [2, 1]
    assert body["dataset"]["id"] == dataset.id
    # A retrain does not take the alias from the version that was serving.
    assert body["model"]["is_champion"] is False
    assert next(row for row in body["versions"] if row["id"] == first["id"])[
        "is_champion"
    ]
    # Upload → this version. No transform hop, no scored children yet.
    assert body["provenance"]["dataset"]["id"] == dataset.id
    assert body["provenance"]["transform"] is None
    assert body["provenance"]["model"]["id"] == second["id"]
    assert body["provenance"]["scored"] == []


def test_the_detail_read_walks_dataset_transform_model_and_scored_tables(
    client, db_session, workspace, dataset, monkeypatch
):
    from app.services.tabular_datasets import register_frame

    features = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Churn features",
        frame=_frame(),
        source="transform",
        parent_ids=[dataset.id],
        lineage={"engine": "sql"},
    )
    db_session.commit()
    _stub_harness(monkeypatch)
    model = _train(client, features).json()["model"]
    scored = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Churn scored",
        frame=_frame(),
        source="score",
        parent_ids=[features.id],
        lineage={
            "engine": "sklearn",
            "model": {"model_id": model["id"]},
            "added_columns": ["prediction"],
        },
    )
    db_session.commit()

    body = client.get(f"/ml-models/{model['id']}").json()["provenance"]
    assert body["dataset"]["id"] == dataset.id
    assert body["transform"]["id"] == features.id
    assert body["transform"]["engine"] == "sql"
    assert body["model"]["id"] == model["id"]
    assert [row["id"] for row in body["scored"]] == [scored.id]
    assert body["scored"][0]["added_columns"] == ["prediction"]


def test_every_version_on_a_card_carries_the_scores_the_card_compares(
    client, dataset, monkeypatch
):
    """The comparison table and the deltas are drawn from the sibling rows.

    They were serialized without a metric block, so both read an empty list of
    scores: on the deployed demo every version's Comparison tab said there was
    nothing to compare, beside a Versions tab listing three. `primary_metric` is
    one number and the table needs all of them.
    """

    _stub_harness(monkeypatch)
    _train(client, dataset)
    second = _train(client, dataset).json()["model"]

    body = client.get(f"/ml-models/{second['id']}").json()

    for row in body["versions"]:
        scores = (row.get("metrics") or {}).get("scores") or []
        assert scores, f"v{row['version']} carries no scores to compare"
        assert {entry["key"] for entry in scores} >= {"roc_auc"}
        # Only the scores: the open version's charts are the ones on screen, and
        # fifty versions' curves would be a payload nobody draws.
        assert set(row["metrics"]) == {"scores"}
    assert "curves" in body["model"]["metrics"]


def test_an_unknown_or_foreign_model_is_a_coded_404(client, db_session):
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
        features=["arpu"],
        status="ready",
    )
    db_session.add(foreign)
    db_session.commit()

    assert client.get(f"/ml-models/{uuid4()}").status_code == 404
    response = client.get(f"/ml-models/{foreign.id}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ML_MODEL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Registry actions
# ---------------------------------------------------------------------------


def test_promoting_a_version_moves_the_alias_and_returns_the_new_lineage(
    client, dataset, monkeypatch
):
    _stub_harness(monkeypatch)
    first = _train(client, dataset).json()["model"]
    second = _train(client, dataset).json()["model"]

    response = client.post(f"/ml-models/{second['id']}/champion")

    assert response.status_code == 200
    body = response.json()
    assert body["model"]["is_champion"] is True
    serving = {row["version"]: row["is_champion"] for row in body["versions"]}
    assert serving == {2: True, 1: False}
    # The card shows champion *and* challenger, so promotion has to hand back
    # both halves: the version just displaced is now the contender.
    assert body["challenger_id"] == first["id"]
    assert client.get(f"/ml-models/{first['id']}").json()["model"]["is_champion"] is (
        False
    )


def test_the_card_names_the_challenger_as_the_best_loser_not_the_newest(
    client, dataset, monkeypatch
):
    """The badge mirrors the registry alias, and both mean "what promotion would serve".

    Version order would nominate the newest fit, which is frequently the worse
    one — the whole reason promotion is a human decision. So the contender is
    ranked by score, and here the middle version wins.
    """

    def _score(value: float):
        _stub_harness(monkeypatch)
        from app.services import tabular_ml

        original = tabular_ml._apply_summary

        def scored(model, summary):
            original(model, summary)
            model.metrics_json = {
                **(model.metrics_json or {}),
                "primary": {"key": "roc_auc", "value": value},
            }

        monkeypatch.setattr(tabular_ml, "_apply_summary", scored)
        return _train(client, dataset).json()["model"]

    champion = _score(0.83)
    best_loser = _score(0.88)
    _score(0.85)

    body = client.get(f"/ml-models/{champion['id']}").json()
    assert body["model"]["is_champion"] is True
    assert body["challenger_id"] == best_loser["id"]


def test_the_comparison_route_refuses_a_version_against_itself(
    client, dataset, monkeypatch
):
    """The refusal codes reach the page as codes, not as a 500.

    Scoring two real pipelines needs real artifacts, which this module stubs; the
    table itself is covered in the service tests. What the route owes the card is
    that a mismatch arrives as something the UI can translate.
    """

    _stub_harness(monkeypatch)
    model = _train(client, dataset).json()["model"]

    response = client.get(f"/ml-models/{model['id']}/comparison?against={model['id']}")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ML_COMPARE_SAME_VERSION"


def test_the_comparison_route_is_workspace_scoped_on_both_sides(
    client, dataset, monkeypatch, db_session
):
    _stub_harness(monkeypatch)
    model = _train(client, dataset).json()["model"]
    other = Workspace(
        id=str(uuid4()), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={}
    )
    db_session.add(other)
    foreign = MLModel(
        id=str(uuid4()),
        workspace_id=other.id,
        name="Foreign",
        slug="foreign",
        version=1,
        task="classification",
        algo="linear",
        target="churn",
        features=["arpu"],
        status="ready",
    )
    db_session.add(foreign)
    db_session.commit()

    # The other side is read through the same scoped lookup, so a foreign id is
    # not merely refused by the comparison — it is not found at all.
    response = client.get(f"/ml-models/{model['id']}/comparison?against={foreign.id}")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ML_MODEL_NOT_FOUND"


def test_an_untrained_version_cannot_be_promoted(client, dataset, monkeypatch):
    _stub_harness(monkeypatch, exit_code=1)
    failed = _train(client, dataset).json()["model"]

    response = client.post(f"/ml-models/{failed['id']}/champion")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ML_MODEL_NOT_READY"


def test_cancel_settles_a_queued_run_and_is_idempotent_on_a_terminal_one(
    client, dataset, db_session, workspace, monkeypatch
):
    queued = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Queued",
        slug="queued",
        version=1,
        task="classification",
        algo="linear",
        target="churn",
        features=["arpu"],
        status="pending",
        dataset_id=dataset.id,
    )
    db_session.add(queued)
    db_session.commit()

    response = client.post(f"/ml-models/{queued.id}/cancel")

    assert response.status_code == 200
    assert response.json()["model"]["status"] == "cancelled"
    assert response.json()["model"]["cancel_requested"] is True
    # Asking twice is not an error, and does not resurrect the row.
    again = client.post(f"/ml-models/{queued.id}/cancel")
    assert again.status_code == 200 and again.json()["model"]["status"] == "cancelled"


def test_deleting_a_version_removes_it_from_the_registry(
    client, dataset, monkeypatch, db_session
):
    _stub_harness(monkeypatch)
    model = _train(client, dataset).json()["model"]

    response = client.delete(f"/ml-models/{model['id']}")

    assert response.status_code == 200
    assert response.json()["deleted"] == model["id"]
    assert client.get(f"/ml-models/{model['id']}").status_code == 404
    assert client.get("/ml-models").json()["models"] == []


def test_training_refuses_while_the_plane_is_disabled(client, dataset, monkeypatch):
    monkeypatch.setattr(settings, "ml_train_enabled", False)

    response = _train(client, dataset)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ML_TRAIN_DISABLED"
    # And the studio knows before it renders a submit button.
    assert client.get("/ml-models/catalog").json()["catalog"]["enabled"] is False


def test_an_unknown_body_field_is_rejected_rather_than_silently_ignored(
    client, dataset
):
    response = client.post(
        "/ml-models",
        json={"dataset_id": dataset.id, "target": "churn", "estimator": "xgboost"},
    )

    assert response.status_code == 422


def test_a_knob_outside_its_bounds_is_clamped_rather_than_refused(
    client, dataset, monkeypatch
):
    _stub_harness(monkeypatch)

    model = _train(
        client,
        dataset,
        algo="gradient_boosting",
        knobs={"max_iter": 99_999, "learning_rate": 0.0001},
    ).json()["model"]

    knobs = model["params"]["knobs"]
    assert knobs["max_iter"] == 600 and knobs["learning_rate"] == 0.01
