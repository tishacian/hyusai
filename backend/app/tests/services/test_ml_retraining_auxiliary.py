"""Audit columns survive retraining without entering predictive identity."""

import polars as pl
import pytest

from app.models.tabular import MLPrediction, TabularDataset
from app.resources.ml_evaluation import fingerprint, read_partition, row_ids
from app.services import ml_retraining as service
from app.services.ml_retraining_data import RetrainingDataPolicy, materialize
from app.services.tabular_datasets import TabularError, read_frame, register_frame
from app.tests.services.test_ml_retraining import (  # noqa: F401
    case,
    enabled,
    propose,
    record_partition,
    store,
)


def fairness_source(db, case, groups=("fr", "en")):
    source = register_frame(
        db,
        workspace_id=case.workspace.id,
        name="Source with audit groups",
        frame=pl.DataFrame(
            {
                "x": list(range(80)),
                "label": [str(i % 2) for i in range(80)],
                "language": [groups[i % len(groups)] for i in range(80)],
            }
        ),
    )
    case.data = source
    case.model.dataset_id = source.id
    case.model.spec_json = {"explain": "pack", "fairness_columns": ["language"]}
    record_partition(case.model, source)
    db.commit()
    return source


def test_monitor_preserves_fairness_outside_the_predictive_contract(
    db_session,
    case,
    monkeypatch,
):
    source = fairness_source(db_session, case)
    predictions = db_session.query(MLPrediction).filter_by(served_id=case.model.id).all()
    for row in predictions[64:]:
        row.label = None
    db_session.commit()
    _, job = propose(db_session, case, monkeypatch)
    training = job.input_ref["training"]
    assert training["features"] == ["x"]
    assert training["spec"]["fairness_columns"] == ["language"]
    dataset = db_session.get(TabularDataset, job.input_ref["dataset_id"])
    frame = read_frame(dataset)
    assert frame.tail(20)["language"].to_list() == read_frame(source).tail(20)["language"].to_list()
    assert (
        frame.filter(pl.col("x") >= 200)["language"].null_count() == job.input_ref["labeled_rows"]
    )
    coverage = job.input_ref["retraining_data"]["auxiliary_coverage"]["language"]
    assert coverage["source"] == {"known": 80, "missing": 0}
    assert coverage["holdout"] == {"known": 20, "missing": 0}
    assert coverage["feedback"] == {"known": 0, "missing": 20}


def materialize_case(db, case, mode="original_plus_feedback"):
    rows = db.query(MLPrediction).filter_by(served_id=case.model.id).order_by(MLPrediction.id).all()
    return materialize(
        db,
        model=case.model,
        rows=rows,
        features=["x"],
        policy=RetrainingDataPolicy(mode=mode),
    )


@pytest.mark.parametrize("groups", [("fr", "en"), (1, 2), (False, True)])
@pytest.mark.parametrize(
    "mode", ["original_plus_feedback", "feedback_only", "latest_dataset_version"]
)
def test_auxiliary_nulls_roundtrip_without_altering_holdout_or_inputs(
    db_session, case, groups, mode
):
    from app.services.tabular_ml import validate_training

    source = fairness_source(db_session, case, groups)
    dataset, ids, evidence, partition = materialize_case(db_session, case, mode)
    frame = read_frame(dataset)
    assert frame.tail(20)["language"].to_list() == read_frame(source).tail(20)["language"].to_list()
    assert frame.head(partition["train_rows"])["x"].is_in(list(range(60, 80))).sum() == 0
    feedback = frame.filter(pl.col("x") >= 200)
    assert feedback["language"].null_count() == len(ids)
    assert set(frame["language"].drop_nulls().to_list()) == set(groups)
    assert evidence["auxiliary_coverage"]["language"]["feedback"] == {
        "known": 0,
        "missing": len(ids),
    }
    # This is the representation the harness reads from the frozen parquet.
    assert fingerprint(row_ids(frame.to_pandas(), partition["columns"])) == partition["fingerprint"]
    spec = validate_training(dataset, db=db_session, **service._training_options(case.model))
    assert spec.features == ["x"]


def test_auxiliary_values_never_change_deduplication_or_admit_a_heldout_row(db_session, case):
    fairness_source(db_session, case)
    rows = (
        db_session.query(MLPrediction)
        .filter_by(served_id=case.model.id)
        .order_by(MLPrediction.id)
        .all()
    )
    rows[0].payload_json, rows[0].label = [{"x": 65, "language": "different"}], "0"
    rows[1].payload_json = [{**rows[2].payload_json[0], "language": "different"}]
    rows[1].label = rows[2].label
    rows[3].payload_json, rows[3].label = [{"x": 1, "language": "different"}], "1"
    db_session.commit()
    dataset, ids, evidence, partition = materialize_case(db_session, case)
    frame = read_frame(dataset).head(partition["train_rows"])
    assert 65 not in frame["x"].to_list()
    assert frame.filter(pl.col("x") == 1).height == 1
    assert frame.select(["x", "label"]).n_unique() == len(frame)
    assert evidence["excluded_holdout"] >= 21
    assert len(ids) == 20  # The original 25% cap remains unchanged.


@pytest.mark.parametrize(
    "groups,bad", [((False, True), "False"), ((1, 2), 1.5), ((1, 2), True), ((1, 2, None), 1.5)]
)
def test_auxiliary_types_are_not_silently_coerced(db_session, case, groups, bad):
    fairness_source(db_session, case, groups)
    row = db_session.query(MLPrediction).filter_by(served_id=case.model.id).first()
    row.payload_json = [{**row.payload_json[0], "language": bad}]
    db_session.commit()
    with pytest.raises(TabularError) as error:
        materialize_case(db_session, case)
    assert error.value.code == "ML_RETRAINING_DATA_INCOMPATIBLE"


@pytest.mark.parametrize(
    "groups,value", [((False, True), False), ((1, 2), 1), (("fr", "en"), "fr")]
)
def test_known_and_missing_feedback_groups_keep_exact_values_and_coverage(
    db_session,
    case,
    groups,
    value,
):
    fairness_source(db_session, case, groups)
    row = db_session.query(MLPrediction).filter_by(served_id=case.model.id).first()
    x = row.payload_json[0]["x"]
    row.payload_json = [{"x": x, "language": value}]
    db_session.commit()
    dataset, _, evidence, partition = materialize_case(db_session, case, "feedback_only")
    frame = read_frame(dataset)
    assert frame.filter(pl.col("x") == x)["language"].to_list() == [value]
    assert frame.head(partition["train_rows"])["language"].null_count() == 79
    assert evidence["auxiliary_coverage"]["language"]["feedback"] == {"known": 1, "missing": 79}
    assert fingerprint(row_ids(frame.to_pandas(), partition["columns"])) == partition["fingerprint"]


def test_group_values_that_cannot_roundtrip_are_refused_without_rounding(db_session, case):
    fairness_source(db_session, case, (9007199254740993, None))
    with pytest.raises(TabularError) as error:
        materialize_case(db_session, case)
    assert error.value.code == "ML_RETRAINING_DATA_INCOMPATIBLE"


@pytest.mark.parametrize("enabled_pack", [True, False])
def test_an_older_partition_with_audit_columns_does_not_make_them_predictive_identity(
    db_session,
    case,
    tmp_path,
    enabled_pack,
):
    from app.resources.ml_evaluation import prepare, write_partition
    from app.services.object_store import get_object_store
    from app.services.tabular_ml import evaluation_partition_key, validate_training

    source = fairness_source(db_session, case)
    partition = prepare(
        read_frame(source).to_pandas(),
        columns=["x", "label", "language"],
        train_indices=range(60),
        test_indices=range(60, 80),
        dataset={"id": source.id, "version": source.version},
        target="label",
        seed=42,
        test_size=0.25,
    )
    local = tmp_path / "evaluation.json.gz"
    metadata = write_partition(partition, local)
    key = evaluation_partition_key(case.model.workspace_id, case.model.id)
    get_object_store().write_bytes(key, local.read_bytes())
    case.model.metrics_json = {
        **case.model.metrics_json,
        "evaluation": {**metadata, "status": "stored", "key": key},
    }
    if not enabled_pack:
        case.model.spec_json = {"explain": "off", "fairness_columns": ["language"]}
    db_session.commit()
    dataset, ids, _, frozen = materialize_case(db_session, case, "feedback_only")
    assert len(ids) == 80
    assert ("language" in frozen["columns"]) is enabled_pack
    assert read_frame(dataset).tail(20)["x"].to_list() == list(range(60, 80))
    if enabled_pack:
        spec = validate_training(dataset, db=db_session, **service._training_options(case.model))
        assert spec.features == ["x"]


def test_disabled_pack_does_not_add_unread_columns_to_the_frozen_partition(db_session, case):
    fairness_source(db_session, case)
    case.model.spec_json = {"explain": "off", "fairness_columns": ["language"]}
    db_session.commit()
    dataset, _, evidence, partition = materialize_case(db_session, case)
    assert "language" not in partition["columns"]
    assert "language" not in read_frame(dataset).columns
    assert "auxiliary_coverage" not in evidence


def test_missing_metadata_does_not_bypass_the_existing_group_limit(db_session, case):
    from app.services.tabular_ml import validate_training

    fairness_source(db_session, case, tuple(f"group-{i}" for i in range(12)))
    dataset, _, _, _ = materialize_case(db_session, case)
    with pytest.raises(TabularError) as error:
        validate_training(dataset, db=db_session, **service._training_options(case.model))
    assert error.value.code == "ML_SPEC_INVALID"
    assert error.value.details["field"] == "fairness_columns"


def test_real_retraining_reads_auxiliary_columns_and_retains_the_original_final_test(
    db_session,
    case,
    monkeypatch,
):
    from app.core.config import settings
    from app.models.tabular import MLModel
    from app.services.object_store import get_object_store
    from app.services.tabular_ml import run_training
    from app.tests.services.test_ml_retraining import approve

    fairness_source(db_session, case)
    monkeypatch.setattr(settings, "ml_registry_enabled", False)
    monkeypatch.setattr(settings, "ml_reference_capture_on_train", False)
    monkeypatch.setattr(settings, "ml_train_memory_limit_mb", 4096)
    monkeypatch.setattr(settings, "ml_train_report_state_limit_mb", 0)
    run, job = propose(db_session, case, monkeypatch)
    decision = approve(db_session, case, run, job)
    identifier = service.stage_retraining(
        db_session,
        proposal_id=job.id,
        decision_id=decision.id,
        run_id=run.id,
    )
    assert run_training(identifier)["status"] == "ready"
    db_session.expire_all()
    trained = db_session.get(MLModel, identifier)
    assert not trained.is_champion
    assert [field["name"] for field in trained.signature_json["inputs"]] == ["x"]
    pack = trained.metrics_json["explain"]
    groups = pack["fairness"][0]["groups"]
    assert {group["group"] for group in groups} == {"fr", "en"}
    assert sum(group["n"] for group in groups) == 20
    original = case.model.metrics_json["evaluation"]
    after = trained.metrics_json["evaluation"]
    store = get_object_store()
    original = read_partition(store.read_bytes(original["key"]), sha256=original["sha256"])
    after = read_partition(store.read_bytes(after["key"]), sha256=after["sha256"])
    assert after["test_ids"] == original["test_ids"]
    assert not set(after["train_ids"]) & set(original["test_ids"])
