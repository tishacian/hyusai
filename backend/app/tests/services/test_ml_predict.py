"""The serving plane: what answers, what it refuses, and what it writes down.

These tests deliberately use a **real artifact** — see
:mod:`app.tests.ml_artifacts` for why — loaded through the same code path
production uses.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.skill import Skill
from app.models.tabular import MLModel, MLModelApiKey, MLPrediction
from app.models.workspace import Workspace
from app.services import tabular_predict
from app.services.tabular_datasets import TabularError, register_frame
from app.services.tabular_ml import set_champion, upload_model_dir
from app.tests.ml_artifacts import (
    CHURN_FEATURES,
    CHURN_ROWS,
    fit_churn_artifact,
)

pl = pytest.importorskip("polars")
pytest.importorskip("skrub")
pytest.importorskip("mlflow.sklearn")

ROWS = CHURN_ROWS
FEATURES = CHURN_FEATURES


# ---------------------------------------------------------------------------
# One real fit, reused by the whole module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def churn_artifact(tmp_path_factory) -> tuple[Path, dict]:
    return fit_churn_artifact(tmp_path_factory.mktemp("churn-fit"))


@pytest.fixture(scope="module")
def arpu_artifact(tmp_path_factory) -> tuple[Path, dict]:
    return fit_churn_artifact(
        tmp_path_factory.mktemp("arpu-fit"), task="regression", target="arpu"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(db_session) -> Workspace:
    row = Workspace(
        id=uuid4().hex,
        name="Serving",
        slug=f"serving-{uuid4().hex[:8]}",
        settings={},
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    tabular_predict.reset_cache()
    yield
    tabular_predict.reset_cache()


def _register(
    db_session,
    workspace: Workspace,
    artifact: tuple[Path, dict],
    *,
    task: str = "classification",
    target: str = "churn",
    slug: str = "churn-risk",
    version: int = 1,
    champion: bool = True,
    status: str = "ready",
) -> MLModel:
    """A registry row pointing at the module's real artifact."""

    directory, summary = artifact
    model = MLModel(
        id=uuid4().hex,
        workspace_id=workspace.id,
        name=f"Churn risk v{version}",
        slug=slug,
        version=version,
        task=task,
        algo="gradient_boosting",
        target=target,
        features=[name for name in FEATURES if name != target],
        params_json={"knobs": {"max_iter": 25}},
        status=status,
        dataset_slug="churn-features",
        row_count=ROWS,
        test_size=0.25,
        cross_validation=0,
        metrics_json=summary["metrics"],
        signature_json=summary["signature"],
        input_example_json=summary["input_example"],
        classes_json=summary["classes"],
        is_champion=champion,
    )
    db_session.add(model)
    db_session.flush()
    if status == "ready":
        uri, size = upload_model_dir(
            directory, workspace_id=workspace.id, model_id=model.id
        )
        model.model_uri = uri
        model.artifact_bytes = size
        model.trained_at = datetime(2026, 8, 1, 9, 30) + timedelta(days=version)
    db_session.commit()
    return model


@pytest.fixture()
def model(db_session, workspace, churn_artifact) -> MLModel:
    return _register(db_session, workspace, churn_artifact)


def _row(**overrides) -> dict:
    body = {
        "plan": "prepaid",
        "tenure_months": 6,
        "arpu": 41.5,
        "support_tickets": 3,
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


def test_a_classification_answers_with_a_label_a_confidence_and_a_named_vector(
    db_session, model
):
    answer = tabular_predict.predict_rows(db_session, model, [_row()])

    assert answer["task"] == "classification"
    assert answer["classes"] == ["0", "1"]
    # A single number is only meaningful once it is clear which class it is about.
    assert answer["positive_label"] == "1"
    assert answer["rows"] == 1
    prediction = answer["predictions"][0]
    assert prediction["prediction"] in {"0", "1"}
    assert 0.0 <= prediction["confidence"] <= 1.0
    assert {entry["label"] for entry in prediction["probabilities"]} == {"0", "1"}
    assert sum(entry["value"] for entry in prediction["probabilities"]) == pytest.approx(
        1.0, abs=1e-6
    )
    assert prediction["score"] == next(
        entry["value"] for entry in prediction["probabilities"] if entry["label"] == "1"
    )
    # The answer names the version that produced it, always.
    assert answer["served"]["model_id"] == model.id
    assert answer["served"]["version"] == 1
    # JSON that Postgres and an HTTP client will both accept.
    json.dumps(answer, allow_nan=False)


def test_a_high_risk_row_scores_above_a_low_risk_one(db_session, model):
    risky = tabular_predict.predict_rows(
        db_session, model, [_row(tenure_months=2, support_tickets=5, arpu=25.0)]
    )
    safe = tabular_predict.predict_rows(
        db_session, model, [_row(tenure_months=84, support_tickets=0, arpu=140.0)]
    )

    # Not an accuracy claim: the point is that the served pipeline is the fitted
    # one and reads its inputs, rather than returning a constant.
    assert risky["predictions"][0]["score"] > safe["predictions"][0]["score"]


def test_a_regression_answers_with_a_number_and_no_probability_vector(
    db_session, workspace, arpu_artifact
):
    model = _register(
        db_session,
        workspace,
        arpu_artifact,
        task="regression",
        target="arpu",
        slug="arpu-forecast",
    )

    answer = tabular_predict.predict_rows(
        db_session,
        model,
        [{"plan": "postpaid", "tenure_months": 30, "support_tickets": 1}],
    )

    assert answer["task"] == "regression"
    assert answer["positive_label"] is None
    prediction = answer["predictions"][0]
    assert isinstance(prediction["prediction"], float)
    assert "probabilities" not in prediction and "confidence" not in prediction


def test_a_hole_in_a_numeric_field_still_scores(db_session, model):
    answer = tabular_predict.predict_rows(db_session, model, [_row(arpu=None)])

    assert answer["predictions"][0]["prediction"] in {"0", "1"}


def test_a_batch_answers_one_prediction_per_row_in_order(db_session, model):
    rows = [
        _row(tenure_months=2, support_tickets=6),
        _row(tenure_months=90, support_tickets=0),
        _row(tenure_months=40, support_tickets=1),
    ]

    answer = tabular_predict.predict_rows(db_session, model, rows)

    assert answer["rows"] == 3 and len(answer["predictions"]) == 3


def test_numbers_arriving_as_strings_are_accepted_because_forms_send_strings(
    db_session, model
):
    answer = tabular_predict.predict_rows(
        db_session, model, [_row(arpu="41.5", tenure_months="6", support_tickets="3")]
    )

    assert answer["predictions"][0]["prediction"] in {"0", "1"}


def test_predictions_are_counted_on_the_row_so_a_model_is_visibly_in_use(
    db_session, model
):
    tabular_predict.predict_rows(db_session, model, [_row(), _row()])
    tabular_predict.predict_rows(db_session, model, [_row()])

    db_session.refresh(model)
    # Predictions, not requests: three rows were scored.
    assert model.predict_count == 3
    assert model.last_predict_at is not None


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        ([], "ML_PREDICT_ROWS_REQUIRED"),
        (None, "ML_PREDICT_ROWS_REQUIRED"),
        (["not-an-object"], "ML_PREDICT_ROW_NOT_OBJECT"),
        ([{**_row(), "mystery": 1}], "ML_PREDICT_FIELD_UNKNOWN"),
        ([{"plan": "prepaid"}], "ML_PREDICT_FIELD_MISSING"),
        ([_row(arpu="quarante")], "ML_PREDICT_FIELD_NOT_NUMERIC"),
    ],
)
def test_every_shape_the_caller_can_fix_is_refused_by_name(
    db_session, model, rows, code
):
    with pytest.raises(TabularError) as raised:
        tabular_predict.predict_rows(db_session, model, rows)

    assert raised.value.code == code


def test_a_field_refusal_names_the_field_and_the_row_it_came_from(db_session, model):
    with pytest.raises(TabularError) as raised:
        tabular_predict.predict_rows(
            db_session, model, [_row(), _row(support_tickets="beaucoup")]
        )

    details = raised.value.details or {}
    assert details["field"] == "support_tickets" and details["row"] == 1


def test_a_batch_above_the_inline_ceiling_says_to_score_a_dataset_instead(
    db_session, model, monkeypatch
):
    monkeypatch.setattr(settings, "ml_predict_max_rows", 2)

    with pytest.raises(TabularError) as raised:
        tabular_predict.predict_rows(db_session, model, [_row()] * 3)

    assert raised.value.code == "ML_PREDICT_TOO_MANY_ROWS"
    assert "dataset" in raised.value.message.lower()


def test_an_untrained_version_cannot_answer(db_session, workspace, churn_artifact):
    pending = _register(
        db_session, workspace, churn_artifact, status="pending", champion=False
    )

    with pytest.raises(TabularError) as raised:
        tabular_predict.predict_rows(db_session, pending, [_row()], version=1)

    assert raised.value.code == "ML_MODEL_NOT_READY"


def test_serving_refuses_while_the_plane_is_disabled(db_session, model, monkeypatch):
    monkeypatch.setattr(settings, "ml_predict_enabled", False)

    with pytest.raises(TabularError) as raised:
        tabular_predict.predict_rows(db_session, model, [_row()])

    assert raised.value.code == "ML_PREDICT_DISABLED"


def test_a_model_without_an_input_contract_says_so_instead_of_failing_a_fit(
    db_session, model
):
    model.signature_json = {}
    db_session.commit()

    with pytest.raises(TabularError) as raised:
        tabular_predict.predict_rows(db_session, model, [_row()])

    assert raised.value.code == "ML_CONTRACT_MISSING"


# ---------------------------------------------------------------------------
# What serves
# ---------------------------------------------------------------------------


def test_a_prediction_is_answered_by_the_champion_even_when_addressed_at_another_version(
    db_session, workspace, churn_artifact
):
    first = _register(db_session, workspace, churn_artifact, version=1, champion=False)
    second = _register(db_session, workspace, churn_artifact, version=2, champion=True)

    answer = tabular_predict.predict_rows(db_session, first, [_row()])

    # The point of an alias: an integration written against v1 follows the
    # promotion to v2 without being rewritten.
    assert answer["served"]["model_id"] == second.id
    assert answer["served"]["version"] == 2
    assert answer["served"]["is_champion"] is True


def test_a_caller_that_needs_reproducibility_can_pin_a_version(
    db_session, workspace, churn_artifact
):
    first = _register(db_session, workspace, churn_artifact, version=1, champion=False)
    _register(db_session, workspace, churn_artifact, version=2, champion=True)

    answer = tabular_predict.predict_rows(db_session, first, [_row()], version=1)

    assert answer["served"]["version"] == 1


def test_pinning_a_version_that_does_not_exist_is_a_coded_404(db_session, model):
    with pytest.raises(TabularError) as raised:
        tabular_predict.predict_rows(db_session, model, [_row()], version=9)

    assert raised.value.code == "ML_VERSION_UNKNOWN"
    assert raised.value.status_code == 404


def test_a_lineage_with_nothing_trained_says_nothing_serves(
    db_session, workspace, churn_artifact
):
    pending = _register(
        db_session, workspace, churn_artifact, status="pending", champion=False
    )

    with pytest.raises(TabularError) as raised:
        tabular_predict.predict_rows(db_session, pending, [_row()])

    assert raised.value.code == "ML_NOTHING_SERVES"


# ---------------------------------------------------------------------------
# The loaded-model cache
# ---------------------------------------------------------------------------


def test_the_second_prediction_reuses_the_resident_pipeline(db_session, model):
    first = tabular_predict.load_pipeline(model)
    second = tabular_predict.load_pipeline(model)

    assert first is second
    assert tabular_predict.cache_state()["size"] == 1


def test_the_artifact_is_read_through_the_door_any_mlflow_stack_has(
    db_session, model, monkeypatch
):
    """The MLmodel is loaded as an MLmodel, not by reaching past the format.

    ``mlflow.pyfunc.load_model`` is the portable door: it reads the ``MLmodel``
    file, honours the flavor recorded in it, and is what makes "this artifact
    runs anywhere MLflow runs" a demonstrated claim rather than a slide. The
    estimator is unwrapped afterwards because a churn answer of "1" without
    "0.87" does not land — but the reading is the format's own.
    """

    import mlflow.pyfunc

    opened: list[str] = []
    real = mlflow.pyfunc.load_model

    def watched(uri, *args, **kwargs):
        opened.append(str(uri))
        return real(uri, *args, **kwargs)

    monkeypatch.setattr(mlflow.pyfunc, "load_model", watched)
    tabular_predict.drop_from_cache(model.id)

    entry = tabular_predict.load_pipeline(model)

    assert opened, "the artifact was not read through pyfunc"
    assert opened[0] == str(entry.directory)
    # And what came back out of it can still answer with a probability, which is
    # the reason the facade is unwrapped rather than called.
    assert hasattr(entry.pipeline, "predict_proba")
    answered = tabular_predict.predict_rows(db_session, model, [_row()])
    assert answered["predictions"][0]["probabilities"]


def test_an_answer_says_whether_it_paid_to_load_the_model(db_session, model):
    """The cache's whole claim, in the field a caller reads.

    ``LoadedModel.load_ms`` is what building that entry cost once. Reporting it
    on every answer told an operator each request spent seconds loading a model
    that had been resident for hours — so the response carries what *this* call
    paid, and says plainly whether it was served from memory.
    """

    cold = tabular_predict.predict_rows(db_session, model, [_row()])
    warm = tabular_predict.predict_rows(db_session, model, [_row()])

    assert cold["cached"] is False
    assert cold["load_ms"] > 0

    assert warm["cached"] is True
    assert warm["load_ms"] == 0.0
    # Same answer either way: the cache is an optimisation, not a code path.
    assert warm["predictions"] == cold["predictions"]


def test_a_retrained_artifact_is_never_answered_by_its_predecessor(db_session, model):
    resident = tabular_predict.load_pipeline(model)
    directory = resident.directory

    # What a retrain of the same row looks like from the cache's side: same id,
    # new fit. The cache key has to notice, or a promoted retrain would keep
    # being answered by the pipeline it replaced.
    model.trained_at = model.trained_at + timedelta(minutes=5)
    db_session.commit()
    reloaded = tabular_predict.load_pipeline(model)

    assert reloaded is not resident
    assert not directory.exists()  # the stale copy's bytes went with it


def test_the_cache_stays_within_its_capacity_and_reclaims_what_it_drops(
    db_session, workspace, churn_artifact, monkeypatch
):
    monkeypatch.setattr(settings, "ml_predict_cache_size", 2)
    models = [
        _register(db_session, workspace, churn_artifact, slug=f"lineage-{index}")
        for index in range(3)
    ]

    oldest = tabular_predict.load_pipeline(models[0])
    for row in models[1:]:
        tabular_predict.load_pipeline(row)

    state = tabular_predict.cache_state()
    assert state["size"] == 2
    assert {entry["model_id"] for entry in state["models"]} == {
        models[1].id,
        models[2].id,
    }
    assert not oldest.directory.exists()


def test_deleting_a_model_forgets_its_resident_pipeline(db_session, model):
    from app.services.tabular_ml import delete_model

    resident = tabular_predict.load_pipeline(model)

    delete_model(db_session, model)

    assert tabular_predict.cache_state()["size"] == 0
    assert not resident.directory.exists()


def test_an_artifact_that_is_not_in_the_store_is_a_coded_refusal(
    db_session, workspace, churn_artifact
):
    row = _register(db_session, workspace, churn_artifact)
    row.model_uri = "workspaces/nope/ml/models/nope/model"
    db_session.commit()

    with pytest.raises(TabularError) as raised:
        tabular_predict.load_pipeline(row)

    assert raised.value.code == "ML_ARTIFACT_MISSING"


# ---------------------------------------------------------------------------
# Batch scoring
# ---------------------------------------------------------------------------


@pytest.fixture()
def scoring_dataset(db_session, workspace):
    frame = pl.DataFrame(
        {
            "msisdn": [f"2126{index:07d}" for index in range(30)],
            "plan": ["prepaid", "postpaid", "hybrid"] * 10,
            "tenure_months": [1 + (index * 7) % 90 for index in range(30)],
            "arpu": [30.0 + (index % 17) * 4.5 for index in range(30)],
            "support_tickets": [index % 4 for index in range(30)],
        }
    )
    row = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Active base",
        frame=frame,
        source="upload",
    )
    db_session.commit()
    return row


def test_scoring_a_dataset_writes_a_new_one_that_keeps_every_input_column(
    db_session, model, scoring_dataset
):
    from app.services.tabular_datasets import get_dataset, read_frame

    result = tabular_predict.score_dataset(
        db_session, model=model, dataset=scoring_dataset
    )

    assert result["scored_rows"] == 30
    assert result["model"]["model_id"] == model.id
    assert result["prediction_id"]
    output = get_dataset(
        db_session, dataset_id=result["dataset_id"], workspace_id=model.workspace_id
    )
    # ``score``, not ``transform``: the data plane has to be able to tell a
    # scored table from a derived one.
    assert output.source == "score"
    assert output.produced_by == "ml_batch_score_v1"
    assert output.parent_ids == [scoring_dataset.id]
    frame = read_frame(output)
    # Every input column survives, or the scores cannot be joined to a customer.
    assert set(frame.columns) >= {"msisdn", "plan", "arpu"}
    assert result["added_columns"] == ["prediction", "confidence", "score_1"]
    assert frame["prediction"].to_list()[0] in {"0", "1"}
    assert all(0.0 <= value <= 1.0 for value in frame["score_1"].to_list())
    # The lineage says which model wrote those columns.
    assert output.lineage_json["model"]["model_id"] == model.id
    journal = (
        db_session.query(MLPrediction)
        .filter(MLPrediction.id == result["prediction_id"])
        .one()
    )
    assert journal.payload_json, "feature PSI is blind if a batch score journals no rows"
    assert "plan" in journal.payload_json[0]
    assert "arpu" in journal.payload_json[0]
    assert len(journal.payload_json) == 30


def test_a_regression_scores_a_dataset_with_one_added_column(
    db_session, workspace, arpu_artifact, scoring_dataset
):
    from app.services.tabular_datasets import read_frame

    model = _register(
        db_session,
        workspace,
        arpu_artifact,
        task="regression",
        target="arpu",
        slug="arpu-forecast",
    )

    result = tabular_predict.score_dataset(
        db_session, model=model, dataset=scoring_dataset, output_name="ARPU forecast"
    )

    assert result["added_columns"] == ["prediction"]
    assert result["name"] == "ARPU forecast"
    frame = read_frame(
        __import__(
            "app.services.tabular_datasets", fromlist=["get_dataset"]
        ).get_dataset(
            db_session,
            dataset_id=result["dataset_id"],
            workspace_id=workspace.id,
        )
    )
    assert frame["prediction"].dtype == pl.Float64


def test_a_dataset_missing_a_required_column_is_refused_by_name(
    db_session, model, workspace
):
    thin = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Thin",
        frame=pl.DataFrame({"plan": ["prepaid"] * 5, "arpu": [10.0] * 5}),
        source="upload",
    )
    db_session.commit()

    with pytest.raises(TabularError) as raised:
        tabular_predict.score_dataset(db_session, model=model, dataset=thin)

    assert raised.value.code == "ML_SCORE_COLUMN_MISSING"
    assert "tenure_months" in str(raised.value.details["columns"])


def test_a_prediction_column_that_would_collide_is_renamed_not_overwritten(
    db_session, model, workspace, scoring_dataset
):
    from app.services.tabular_datasets import read_frame

    frame = read_frame(scoring_dataset).with_columns(
        pl.lit("kept").alias("prediction")
    )
    collided = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="With a prediction column",
        frame=frame,
        source="upload",
    )
    db_session.commit()

    result = tabular_predict.score_dataset(
        db_session, model=model, dataset=collided
    )

    assert result["added_columns"][0] == "prediction_2"


def test_a_dataset_above_the_scoring_ceiling_is_refused(
    db_session, model, scoring_dataset, monkeypatch
):
    from app.models.tabular import TabularDataset

    monkeypatch.setattr(settings, "ml_score_max_rows", 5)
    before = db_session.query(TabularDataset).count()

    with pytest.raises(TabularError) as raised:
        tabular_predict.score_dataset(
            db_session, model=model, dataset=scoring_dataset
        )

    assert raised.value.code == "ML_SCORE_TOO_MANY_ROWS"
    # A refusal leaves nothing behind. The output row is reserved *after* every
    # check, so the Data page never shows a table for work that never started.
    assert db_session.query(TabularDataset).count() == before


def test_a_score_says_where_it_has_got_to_while_it_is_getting_there(
    db_session, model, scoring_dataset
):
    """The third of the three long tasks that owed a reader a progress line.

    Ingest and training each publish their step into ``status_detail`` and the
    page draws a check-list from it. Scoring published nothing, because its
    output row did not exist until the work was over — so thirteen seconds of a
    seeded demo were a spinner. The row is reserved first now, and the steps it
    passes through are recorded in the order a reader sees them.
    """

    from app.services.tabular_datasets import get_dataset

    seen: list[tuple[str, str | None]] = []
    original = tabular_predict.mark_step

    def record(session, dataset, step, **kwargs):
        seen.append((step, dataset.status))
        return original(session, dataset, step, **kwargs)

    tabular_predict.mark_step = record
    try:
        result = tabular_predict.score_dataset(
            db_session, model=model, dataset=scoring_dataset
        )
    finally:
        tabular_predict.mark_step = original

    steps = [step.split(":", 1)[0] for step, _ in seen]
    # In order, and only the codes the vocabulary names: a surface renders these
    # as a list and translates each one.
    assert steps == ["reading", "scoring", "writing"]
    assert set(steps) <= set(tabular_predict.SCORE_STEPS)
    # Every one of them was published while the row was still unsettled.
    assert {status for _, status in seen} == {"ingesting"}
    # The scoring line carries how far it got, not merely that it is scoring.
    scoring = next(step for step, _ in seen if step.startswith("scoring"))
    assert scoring == "scoring:0/30"

    # And the row a reader watched is the row they end up with: same identity,
    # settled rather than replaced.
    output = get_dataset(
        db_session, dataset_id=result["dataset_id"], workspace_id=model.workspace_id
    )
    assert output.status == "ready"
    assert output.status_detail is None
    assert output.source == "score"


def test_a_score_that_breaks_does_not_leave_a_table_claiming_to_be_working(
    db_session, model, scoring_dataset, monkeypatch
):
    """The cost of reserving the row early, paid rather than ignored.

    A row that exists before the work is a row that outlives a crash, and left
    in ``ingesting`` it would sit on the Data page pretending to make progress
    for as long as the deployment lasts — worse than the silence reserving it
    removed.
    """

    from app.models.tabular import TabularDataset

    def explode(*args, **kwargs):
        raise RuntimeError("the pipeline died mid-batch")

    monkeypatch.setattr(tabular_predict, "_predict_frame", explode)

    with pytest.raises(RuntimeError):
        tabular_predict.score_dataset(
            db_session, model=model, dataset=scoring_dataset
        )

    row = (
        db_session.query(TabularDataset)
        .filter(TabularDataset.source == "score")
        .order_by(TabularDataset.created_at.desc())
        .first()
    )
    assert row is not None
    assert row.status == "failed"
    assert row.status_detail is None
    assert "died mid-batch" in (row.error or "")


# ---------------------------------------------------------------------------
# Scoped API keys
# ---------------------------------------------------------------------------


def test_a_minted_key_is_returned_once_and_stored_only_as_a_digest(db_session, model):
    row, secret = tabular_predict.mint_api_key(db_session, model=model, name="CRM")

    assert secret.startswith(tabular_predict.KEY_PREFIX)
    assert row.name == "CRM" and row.key_prefix == secret[:12]
    # The secret is not in the row, in any form a lookup could reverse.
    assert secret not in json.dumps(
        {"prefix": row.key_prefix, "digest": row.key_sha256}
    )
    assert tabular_predict.serialize_api_key(row).get("secret") is None
    assert tabular_predict.serialize_api_key(row, secret=secret)["secret"] == secret


def test_a_key_authenticates_to_its_model_and_counts_its_uses(db_session, model):
    _row_, secret = tabular_predict.mint_api_key(db_session, model=model)

    key, resolved = tabular_predict.authenticate_key(db_session, secret)

    assert resolved.id == model.id
    assert key.use_count == 1 and key.last_used_at is not None
    tabular_predict.authenticate_key(db_session, secret)
    assert (
        db_session.query(MLModelApiKey).filter(MLModelApiKey.id == key.id).one().use_count
        == 2
    )


@pytest.mark.parametrize("presented", ["", None, "agpk_nope", "not-even-a-key"])
def test_a_secret_that_was_never_minted_is_a_401(db_session, model, presented):
    with pytest.raises(TabularError) as raised:
        tabular_predict.authenticate_key(db_session, presented)

    assert raised.value.status_code == 401


def test_a_revoked_key_stops_working_and_stays_visible_as_revoked(db_session, model):
    row, secret = tabular_predict.mint_api_key(db_session, model=model)

    tabular_predict.revoke_api_key(db_session, model=model, key_id=row.id)

    with pytest.raises(TabularError) as raised:
        tabular_predict.authenticate_key(db_session, secret)
    assert raised.value.code == "ML_KEY_REVOKED"
    # Revocation is history, not deletion: the card still shows what was used.
    listed = tabular_predict.list_api_keys(db_session, model=model)
    assert [entry.revoked_at is not None for entry in listed] == [True]


def test_a_key_of_another_model_cannot_be_revoked_through_this_one(
    db_session, workspace, churn_artifact, model
):
    other = _register(db_session, workspace, churn_artifact, slug="other-lineage")
    row, _secret = tabular_predict.mint_api_key(db_session, model=other)

    with pytest.raises(TabularError) as raised:
        tabular_predict.revoke_api_key(db_session, model=model, key_id=row.id)

    assert raised.value.code == "ML_KEY_NOT_FOUND"


def test_the_key_ceiling_counts_only_live_keys(db_session, model, monkeypatch):
    monkeypatch.setattr(settings, "ml_predict_max_keys", 2)
    first, _ = tabular_predict.mint_api_key(db_session, model=model)
    tabular_predict.mint_api_key(db_session, model=model)

    with pytest.raises(TabularError) as raised:
        tabular_predict.mint_api_key(db_session, model=model)
    assert raised.value.code == "ML_KEY_LIMIT"

    tabular_predict.revoke_api_key(db_session, model=model, key_id=first.id)
    assert tabular_predict.mint_api_key(db_session, model=model)[1]


def test_an_untrained_model_cannot_hold_keys(db_session, workspace, churn_artifact):
    pending = _register(
        db_session, workspace, churn_artifact, status="pending", champion=False
    )

    with pytest.raises(TabularError) as raised:
        tabular_predict.mint_api_key(db_session, model=pending)

    assert raised.value.code == "ML_MODEL_NOT_READY"


def test_deleting_a_model_takes_its_keys_with_it(db_session, model):
    from app.services.tabular_ml import delete_model

    tabular_predict.mint_api_key(db_session, model=model)

    delete_model(db_session, model)

    # A credential that still authenticates against a model nobody can audit is
    # the one leak this plane must not have.
    assert db_session.query(MLModelApiKey).count() == 0


# ---------------------------------------------------------------------------
# Publishing a model as a Skill
# ---------------------------------------------------------------------------


def test_publishing_binds_a_verified_executor_with_the_model_pinned(db_session, model):
    published = tabular_predict.publish_as_skill(db_session, model=model)

    assert published["slug"] == f"ws.{model.workspace_id}.predict_churn_risk"
    row = db_session.query(Skill).filter(Skill.slug == published["slug"]).one()
    assert row.workspace_id == model.workspace_id
    assert row.category == "Models" and row.is_seeded == "N"
    # No new executor kind and no code path: the model rides in frozen input,
    # which a run cannot substitute.
    assert row.executor["kind"] == "registry_call"
    assert row.executor["params"]["skill_slug"] == "ml_predict_v1"
    assert row.executor["params"]["frozen_input"]["_predict"]["model_id"] == model.id
    # And the binding is executable, not merely well shaped.
    from app.services.skills_registry.executors import bind_executor

    assert callable(bind_executor(row.executor))


def test_the_published_schema_is_typed_from_the_model_own_contract(db_session, model):
    published = tabular_predict.publish_as_skill(db_session, model=model)

    schema = published["input_schema"]
    assert set(schema["required"]) == set(FEATURES) - {"churn"}
    assert schema["properties"]["arpu"]["type"] == "number"
    assert "minimum" in schema["properties"]["arpu"]
    # A low-cardinality column offers its actual values, which is what makes the
    # published Skill usable by an agent rather than merely callable.
    assert set(schema["properties"]["plan"]["enum"]) == {
        "prepaid",
        "postpaid",
        "hybrid",
    }
    assert published["output_schema"]["properties"]["confidence"]["type"] == "number"
    # Catalog descriptions render verbatim: no markup.
    assert "`" not in published["description"]


def test_publishing_names_the_lineage_so_every_version_reports_it(
    db_session, workspace, churn_artifact
):
    first = _register(db_session, workspace, churn_artifact, version=1, champion=False)
    second = _register(db_session, workspace, churn_artifact, version=2, champion=True)

    tabular_predict.publish_as_skill(db_session, model=second)

    db_session.refresh(first)
    db_session.refresh(second)
    assert first.published_skill_slug == second.published_skill_slug
    # The link is the Skill row itself, not only its name: the registry can
    # join on it, and a Skill withdrawn from the registry nulls it.
    skill = db_session.query(Skill).one()
    assert first.published_skill_id == second.published_skill_id == skill.id
    assert tabular_predict.published_skill(db_session, first)["id"] == skill.id
    # Republishing is an update, not a second Skill.
    tabular_predict.publish_as_skill(db_session, model=first)
    assert db_session.query(Skill).count() == 1


def test_a_version_born_after_publication_inherits_the_skill_link(
    db_session, workspace, churn_artifact
):
    from app.services.tabular_ml import _lineage_publication

    first = _register(db_session, workspace, churn_artifact, version=1)
    tabular_predict.publish_as_skill(db_session, model=first)
    skill = db_session.query(Skill).one()

    assert _lineage_publication(
        db_session, workspace_id=workspace.id, slug=first.slug
    ) == (skill.id, skill.slug)


def test_withdrawing_removes_the_skill_and_clears_the_lineage(db_session, model):
    tabular_predict.publish_as_skill(db_session, model=model)

    withdrawn = tabular_predict.unpublish_skill(db_session, model=model)

    db_session.refresh(model)
    assert withdrawn and model.published_skill_slug is None
    assert model.published_skill_id is None
    assert db_session.query(Skill).count() == 0
    assert tabular_predict.unpublish_skill(db_session, model=model) is None


def test_deleting_the_last_version_withdraws_the_skill_it_was_published_as(
    db_session, model
):
    from app.services.tabular_ml import delete_model

    tabular_predict.publish_as_skill(db_session, model=model)

    delete_model(db_session, model)

    # Leaving it would put a Skill in the catalog whose every call is an error.
    assert db_session.query(Skill).count() == 0


def test_deleting_one_version_keeps_the_lineage_skill_the_others_serve(
    db_session, workspace, churn_artifact
):
    from app.services.tabular_ml import delete_model

    first = _register(db_session, workspace, churn_artifact, version=1, champion=False)
    second = _register(db_session, workspace, churn_artifact, version=2, champion=True)
    tabular_predict.publish_as_skill(db_session, model=second)

    delete_model(db_session, first)

    assert db_session.query(Skill).count() == 1


def test_the_catalog_can_name_the_model_a_published_skill_answers_from(
    db_session, model
):
    """The provenance chip's data, read off the executor the run dispatches.

    A published Skill in a catalog of forty is indistinguishable from a hand
    written one unless it says where its answer comes from. That claim has to be
    derived from the binding rather than from a second field somebody remembered
    to fill in.
    """

    published = tabular_predict.publish_as_skill(db_session, model=model)
    row = db_session.query(Skill).filter(Skill.slug == published["slug"]).one()

    provenance = tabular_predict.skill_provenance(db_session, [row])[row.slug]

    assert provenance["model_id"] == model.id
    assert provenance["name"] == model.name
    assert provenance["version"] == 1
    assert provenance["target"] == "churn"
    assert provenance["metric"]["key"] == "roc_auc"
    assert 0.0 <= provenance["metric"]["value"] <= 1.0


def test_the_provenance_follows_a_promotion_instead_of_freezing_on_publication(
    db_session, workspace, churn_artifact
):
    """Promoting v2 must move the chip, because it moves the answer.

    The Skill is bound to a lineage, so what it replies with changes the moment
    another version is promoted. A provenance copied at publication would go on
    claiming v1 — a chip that lies is worse than no chip, because it is quoted.
    """

    first = _register(db_session, workspace, churn_artifact, version=1, champion=True)
    tabular_predict.publish_as_skill(db_session, model=first)
    row = db_session.query(Skill).one()
    assert tabular_predict.skill_provenance(db_session, [row])[row.slug]["version"] == 1

    second = _register(db_session, workspace, churn_artifact, version=2, champion=False)
    set_champion(db_session, second)

    provenance = tabular_predict.skill_provenance(db_session, [row])[row.slug]
    assert provenance["version"] == 2
    assert provenance["model_id"] == second.id


def _with_contract_mark(model_row, db_session) -> None:
    """Give one version a contract detail the others do not have.

    A recognizable ceiling on ``arpu``: whichever schema carries it was derived
    from this version and no other, which is what the two tests below need to
    tell apart "the card's version" and "the version that serves".
    """

    signature = json.loads(json.dumps(model_row.signature_json))
    for entry in signature.get("inputs") or []:
        if entry.get("name") == "arpu":
            entry["max"] = 999.0
    model_row.signature_json = signature
    db_session.commit()


def test_the_published_contract_describes_the_version_that_serves(
    db_session, workspace, churn_artifact
):
    """Publishing from an old card must not freeze that card's fields.

    The Skill answers with the champion, so an agent reading its input schema
    is preparing a call to the champion's pipeline. A schema copied from
    whichever version's card the publish button was on would describe fields
    the serving pipeline may refuse.
    """

    first = _register(db_session, workspace, churn_artifact, version=1, champion=False)
    second = _register(db_session, workspace, churn_artifact, version=2, champion=True)
    _with_contract_mark(second, db_session)

    published = tabular_predict.publish_as_skill(db_session, model=first)

    assert published["input_schema"]["properties"]["arpu"]["maximum"] == 999.0
    assert "version 2" in published["description"]


def test_a_promotion_moves_the_published_contract_with_the_answer(
    db_session, workspace, churn_artifact
):
    """The chip already follows a promotion; the schemas must follow the same way.

    Promoting v2 changes what the Skill replies with, so the fields a caller is
    told to send have to be v2's — otherwise the catalog documents a contract
    the serving pipeline no longer honours.
    """

    first = _register(db_session, workspace, churn_artifact, version=1, champion=True)
    tabular_predict.publish_as_skill(db_session, model=first)
    row = db_session.query(Skill).one()
    assert "maximum" not in row.input_schema["properties"]["arpu"] or (
        row.input_schema["properties"]["arpu"].get("maximum") != 999.0
    )

    second = _register(db_session, workspace, churn_artifact, version=2, champion=False)
    _with_contract_mark(second, db_session)
    set_champion(db_session, second)

    db_session.refresh(row)
    assert row.input_schema["properties"]["arpu"]["maximum"] == 999.0
    assert "version 2" in row.description
    # And a lineage that published nothing promotes in silence, refreshing
    # nothing — the guard the promotion path relies on.
    other = _register(
        db_session, workspace, churn_artifact, slug="other", version=1, champion=True
    )
    assert tabular_predict.refresh_published_skill(db_session, model=other) is False


def test_a_skill_that_answers_from_no_model_claims_no_provenance(db_session, model):
    """Absent, not empty: a hand-written Skill has nothing to attribute."""

    hand_written = Skill(
        id=uuid4().hex,
        workspace_id=model.workspace_id,
        slug=f"ws.{model.workspace_id}.hand_written",
        name="Hand written",
        type="workflow",
        executor={"kind": "http_call", "params": {}},
    )
    db_session.add(hand_written)
    db_session.commit()

    assert tabular_predict.skill_provenance(db_session, [hand_written]) == {}
    # A lineage whose every version was deleted is the same answer: the Skill is
    # gone with it, and until it is there is nothing true to say.
    published = tabular_predict.publish_as_skill(db_session, model=model)
    row = db_session.query(Skill).filter(Skill.slug == published["slug"]).one()
    model.status = "pending"
    db_session.commit()
    assert tabular_predict.skill_provenance(db_session, [row]) == {}


def test_an_untrained_model_cannot_be_published(db_session, workspace, churn_artifact):
    pending = _register(
        db_session, workspace, churn_artifact, status="pending", champion=False
    )

    with pytest.raises(TabularError) as raised:
        tabular_predict.publish_as_skill(db_session, model=pending)

    assert raised.value.code == "ML_MODEL_NOT_READY"


def test_the_published_skill_answers_a_record_through_the_registry_executor(
    db_session, model
):
    import asyncio

    from app.services.skills_registry.executors import bind_executor

    published = tabular_predict.publish_as_skill(db_session, model=model)
    row = db_session.query(Skill).filter(Skill.slug == published["slug"]).one()
    call = bind_executor(row.executor)

    answer = asyncio.run(call(_row(), {"workspace_id": model.workspace_id}))

    # One record in, one flattened answer out: an agent reading a tool result
    # should not have to index into a list of one.
    assert answer["prediction"] in {"0", "1"}
    assert 0.0 <= answer["confidence"] <= 1.0
    assert answer["served"]["model_id"] == model.id


def test_a_payload_cannot_redirect_a_published_skill_to_another_model(
    db_session, workspace, churn_artifact, model
):
    import asyncio

    from app.services.skills_registry.executors import bind_executor

    other = _register(db_session, workspace, churn_artifact, slug="other-lineage")
    published = tabular_predict.publish_as_skill(db_session, model=model)
    row = db_session.query(Skill).filter(Skill.slug == published["slug"]).one()
    call = bind_executor(row.executor)

    answer = asyncio.run(
        call(
            {**_row(), "_predict": {"model_id": other.id}},
            {"workspace_id": model.workspace_id},
        )
    )

    assert answer["served"]["model_id"] == model.id


# ---------------------------------------------------------------------------
# The Flow node
# ---------------------------------------------------------------------------


def test_the_score_node_scores_the_dataset_on_its_wire(
    db_session, model, scoring_dataset
):
    import asyncio

    from app.services.skills_registry.wrappers import resolve

    node = resolve("ml_batch_score_v1")

    answer = asyncio.run(
        node(
            {
                "upstream": {"dataset_id": scoring_dataset.id},
                "_predict": {"model_slug": model.slug, "node_id": "score-1"},
            },
            {"workspace_id": model.workspace_id, "run_id": "run-1"},
        )
    )

    assert answer["scored_rows"] == 30
    assert answer["dataset_id"] and answer["model"]["model_id"] == model.id


def test_the_predict_node_answers_one_record_from_its_named_inputs(db_session, model):
    import asyncio

    from app.services.skills_registry.wrappers import resolve

    answer = asyncio.run(
        resolve("ml_predict_v1")(
            {"rows": [_row()], "_predict": {"model_slug": model.slug}},
            {"workspace_id": model.workspace_id},
        )
    )

    assert answer["prediction"] in {"0", "1"}
    assert answer["served"]["model_id"] == model.id


def test_the_score_node_scores_the_dataset_it_pins_when_nothing_is_wired(
    db_session, model, scoring_dataset
):
    """A pinned node is a runnable node: no upstream edge required.

    The pin is written the way the builder writes it (``dataset_slug``), which
    is the spelling that used to be dropped on the floor — a node configured in
    the UI then refused at run time for lack of an input it had been given.
    """
    import asyncio

    from app.services.skills_registry.wrappers import resolve

    answer = asyncio.run(
        resolve("ml_batch_score_v1")(
            {
                "_predict": {
                    "model_slug": model.slug,
                    "sources": [{"dataset_slug": scoring_dataset.slug}],
                }
            },
            {"workspace_id": model.workspace_id},
        )
    )

    assert answer["scored_rows"] == 30
    assert answer["model"]["model_id"] == model.id


def test_the_score_node_says_a_dataset_is_missing_rather_than_scoring_nothing(
    db_session, model
):
    import asyncio

    from app.services.skills_registry.wrappers import resolve

    with pytest.raises(ValueError, match="ML_SCORE_DATASET_REQUIRED"):
        asyncio.run(
            resolve("ml_batch_score_v1")(
                {"_predict": {"model_slug": model.slug, "sources": []}},
                {"workspace_id": model.workspace_id},
            )
        )


@pytest.mark.parametrize("slug", ["ml_predict_v1", "ml_batch_score_v1"])
def test_neither_serving_node_runs_without_graph_configuration(db_session, slug):
    import asyncio

    from app.services.skills_registry.wrappers import resolve

    with pytest.raises(ValueError, match="predict_config_missing"):
        asyncio.run(resolve(slug)({"dataset_id": "x"}, {}))


def test_the_node_says_which_model_is_missing_rather_than_guessing(db_session, workspace):
    import asyncio

    from app.services.skills_registry.wrappers import resolve

    with pytest.raises(ValueError, match="ML_MODEL_NOT_FOUND"):
        asyncio.run(
            resolve("ml_predict_v1")(
                {"rows": [_row()], "_predict": {"model_slug": "nope"}},
                {"workspace_id": workspace.id},
            )
        )


def test_the_dag_projects_the_model_reference_as_graph_configuration():
    from app.services.run_engine.dag import DagNode, _apply_predict_node_config

    node = DagNode(
        id="score",
        type="task",
        kind="task",
        label="Score",
        config={
            "skill_slug": "ml_batch_score_v1",
            "params": {
                "model_slug": "churn-risk",
                "pinned_version": 2,
                "output_name": "Scored base",
                "sources": [{"dataset_id": "abc"}],
            },
        },
        skill_slug="ml_batch_score_v1",
        data={},
    )
    node_input = {"dataset_id": "abc", "model_slug": "attacker-model"}

    _apply_predict_node_config(node, node_input)

    assert node_input["_predict"]["model_slug"] == "churn-risk"
    assert node_input["_predict"]["pinned_version"] == 2
    assert node_input["_predict"]["node_id"] == "score"
    # The raw keys never stay as data inputs, so a payload cannot shadow them.
    assert "model_slug" not in node_input and "output_name" not in node_input


def test_the_reserved_predict_key_is_stripped_on_every_other_node():
    from app.services.run_engine.dag import (
        DagNode,
        _apply_predict_node_config,
        _passthrough_without_recipe,
    )

    node = DagNode(
        id="answer",
        type="task",
        kind="task",
        label="Answer",
        config={"skill_slug": "llm_rag_answer_v1"},
        skill_slug="llm_rag_answer_v1",
        data={},
    )
    node_input = {"_predict": {"model_id": "smuggled"}, "question": "?"}

    _apply_predict_node_config(node, node_input)

    assert "_predict" not in node_input and node_input["question"] == "?"
    # Nor does a model reference ride a failure envelope into run outputs.
    assert _passthrough_without_recipe(
        {"dataset_id": "d", "_predict": {"model_id": "x"}}
    ) == {"dataset_id": "d"}


# ---------------------------------------------------------------------------
# The card's serving block
# ---------------------------------------------------------------------------


def test_the_serving_block_gives_the_card_everything_it_renders(db_session, model):
    tabular_predict.mint_api_key(db_session, model=model, name="CRM")

    block = tabular_predict.serving_block(db_session, model)

    assert block["enabled"] is True and block["callable"] is True
    assert block["is_serving"] is True and block["serving_version"] == 1
    assert [field["name"] for field in block["fields"]] == [
        name for name in FEATURES if name != "churn"
    ]
    assert block["classes"] == ["0", "1"] and block["positive_label"] == "1"
    # The card's cURL and its Playground hit the same route, which is the only
    # way the snippet on the slide can be trusted to be the one that runs.
    assert block["endpoint"].endswith(f"/ml-models/{model.id}/predict")
    assert block["key_header"] == "X-API-Key"
    assert [entry["name"] for entry in block["keys"]] == ["CRM"]
    assert all("secret" not in entry for entry in block["keys"])
    assert block["published_skill"] is None


def test_the_serving_block_of_an_untrained_version_is_not_callable(
    db_session, workspace, churn_artifact
):
    pending = _register(
        db_session, workspace, churn_artifact, status="pending", champion=False
    )

    block = tabular_predict.serving_block(db_session, pending)

    assert block["callable"] is False and block["is_serving"] is False


@pytest.mark.parametrize("slug", ["ml_predict_v1", "ml_batch_score_v1"])
def test_both_serving_skills_are_registered_bound_and_claimed(slug):
    from app.services.skills_registry.seed import (
        SEED_CAPABILITIES,
        SEED_SKILLS,
        skill_category,
    )
    from app.services.skills_registry.wrappers import _REGISTRY

    entry = next(row for row in SEED_SKILLS if row["slug"] == slug)
    assert entry["type"] == "workflow" and entry["provider"] == "internal"
    # Catalog descriptions render verbatim in the UI.
    assert "`" not in entry["description"]
    assert _REGISTRY[slug][2] == "bound"
    assert skill_category(slug) == "Models"
    carrier = next(
        row for row in SEED_CAPABILITIES if slug in (row.get("skill_slugs") or [])
    )
    # Without a claiming capability the catalog files a skill under `unclaimed`,
    # which greys its palette row in every workspace.
    assert carrier["tier"] == "universal"


# ---------------------------------------------------------------------------
# Why an answer came out that way
# ---------------------------------------------------------------------------


def test_an_explained_row_says_what_its_own_values_did_to_the_score(db_session, model):
    answer = tabular_predict.predict_rows(
        db_session,
        model,
        [_row(tenure_months=2, support_tickets=6, arpu=25.0)],
        explain=True,
    )

    contributions = answer["predictions"][0]["contributions"]
    assert contributions, "a churn row with extreme values must explain itself"
    # Sorted by how much each field moved the answer, largest first.
    effects = [abs(entry["effect"]) for entry in contributions]
    assert effects == sorted(effects, reverse=True)
    for entry in contributions:
        assert entry["field"] in FEATURES
        # Each row carries the counterfactual it was measured against, so the UI
        # can say "vs. a typical customer" rather than asserting causality.
        assert "typical" in entry and "value" in entry
    # A support-ticket count of six is not typical, so it must have an effect.
    tickets = next(
        entry for entry in contributions if entry["field"] == "support_tickets"
    )
    assert tickets["effect"] != 0.0
    json.dumps(answer, allow_nan=False)


def test_an_explanation_is_only_computed_when_it_was_asked_for(db_session, model):
    plain = tabular_predict.predict_rows(db_session, model, [_row()])

    assert "contributions" not in plain["predictions"][0]


def test_a_batch_is_never_explained_because_the_cost_is_per_row(db_session, model):
    answer = tabular_predict.predict_rows(
        db_session, model, [_row(), _row(plan="hybrid")], explain=True
    )

    assert all(
        "contributions" not in prediction for prediction in answer["predictions"]
    )


# ---------------------------------------------------------------------------
# The import a prediction should never wait for
# ---------------------------------------------------------------------------


def test_the_deserializer_is_resident_after_the_warm(monkeypatch):
    """The warm is only worth having if it actually leaves the reader loaded."""

    import sys

    monkeypatch.delitem(sys.modules, "skops.io", raising=False)
    tabular_predict.preload_deserializer()

    assert "skops.io" in sys.modules


def test_a_deployment_that_cannot_read_artifacts_still_boots(monkeypatch):
    """A warm that raises would turn an unreadable artifact into an outage.

    The predict route already refuses with the reason, which is an answer an
    operator can act on. A boot that dies in a lifespan hook is not. The error
    raised here is the one the demo host actually raised.
    """

    import builtins
    import sys

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "skops.io":
            raise ModuleNotFoundError("No module named 'torchvision'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "skops.io", raising=False)
    monkeypatch.setattr(builtins, "__import__", refuse)

    tabular_predict.preload_deserializer()  # must not raise
