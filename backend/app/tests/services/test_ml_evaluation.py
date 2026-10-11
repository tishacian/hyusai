"""Evaluation evidence proves holdout membership independently of row order."""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sklearn.dummy import DummyClassifier
from sklearn.model_selection import train_test_split
from skore import EstimatorReport

from app.core.config import settings
from app.resources import ml_evaluation as evaluation
from app.services import ml_comparison, tabular_ml
from app.services.object_store import get_object_store
from app.services.tabular_datasets import TabularError, read_frame, register_frame
from app.tests.services.test_ml_comparison import two_fits  # noqa: F401
from app.tests.services.test_ml_training import (  # noqa: F401
    _stub_harness,
    dataset,
    enabled,
    store,
    workspace,
)


def partition(frame, seed=42, **extra):
    train, test = train_test_split(frame.index, random_state=seed, test_size=0.3)
    return evaluation.prepare(
        frame,
        columns=list(frame.columns),
        train_indices=train,
        test_indices=test,
        dataset={"id": "source", "version": 1},
        target=frame.columns[-1],
        seed=seed,
        test_size=0.3,
        **extra,
    )


def test_reordered_rows_and_different_seeds_keep_only_shared_unseen_contents():
    frame = pd.DataFrame({"x": range(100), "target": [index % 2 for index in range(100)]})
    left, right = partition(frame), partition(frame, seed=9)
    reordered = frame.sample(frac=1, random_state=7).reset_index(drop=True)
    answer = evaluation.shared_holdout(reordered, [left, right])
    ids = evaluation.row_ids(answer, left["columns"])
    assert set(ids) == (set(left["test_ids"]) & set(right["test_ids"]))
    assert not set(ids) & (set(left["train_ids"]) | set(right["train_ids"]))
    assert answer.x.tolist() == evaluation.shared_holdout(frame, [left, right]).x.tolist()


def test_identical_contents_in_training_and_test_are_excluded():
    frame = pd.DataFrame({"x": [1, 1, 2, 3], "target": [0, 0, 1, 1]})
    state = evaluation.prepare(
        frame,
        columns=list(frame.columns),
        train_indices=[0, 2],
        test_indices=[1, 3],
        dataset={},
        target="target",
        seed=0,
        test_size=0.5,
    )
    assert state["duplicate_overlap"] == 1
    assert evaluation.shared_holdout(frame, [state]).x.tolist() == [3]


def test_changed_contents_and_corrupt_artifacts_are_refused(tmp_path):
    frame = pd.DataFrame({"x": range(10), "target": range(10)})
    state = partition(frame)
    path = tmp_path / evaluation.FILENAME
    metadata = evaluation.write_partition(state, path)
    assert evaluation.read_partition(path.read_bytes(), sha256=metadata["sha256"]) == state
    with pytest.raises(ValueError, match="digest"):
        evaluation.read_partition(path.read_bytes() + b"changed", sha256=metadata["sha256"])
    frame.loc[0, "x"] = -1
    with pytest.raises(ValueError, match="changed"):
        evaluation.shared_holdout(frame, [state])


def test_comparison_reader_preserves_the_training_parquet_date_cells(db_session, workspace, store):
    import polars as pl

    source = register_frame(
        db_session,
        workspace_id=workspace.id,
        name="Dates",
        source="qualification",
        frame=pl.DataFrame({"day": [date(2026, 1, 1), date(2026, 1, 2)], "target": [0, 1]}),
    )
    restored = ml_comparison._comparison_frame(source, ["day", "target"], recorded=True)
    original = pd.DataFrame({"day": [date(2026, 1, 1), date(2026, 1, 2)], "target": [0, 1]})
    assert evaluation.row_ids(restored, ["day", "target"]) == evaluation.row_ids(
        original, ["day", "target"]
    )


def store_partition(model, dataset, frame, tmp_path):
    state = partition(frame)
    state["dataset"] = {"id": dataset.id, "version": dataset.version}
    state["target"] = model.target
    path = tmp_path / model.id / evaluation.FILENAME
    metadata = evaluation.write_partition(state, path)
    key = tabular_ml.evaluation_partition_key(model.workspace_id, model.id)
    get_object_store().write_bytes(key, path.read_bytes())
    model.metrics_json = {
        **model.metrics_json,
        "evaluation": {**metadata, "key": key, "status": "stored"},
    }
    return state


def test_comparison_uses_evidence_after_seed_and_source_order_change(
    db_session,
    two_fits,
    dataset,
    tmp_path,
    monkeypatch,
):
    left, right = two_fits
    columns = sorted(set(left.features) | set(right.features) | {right.target})
    frame = read_frame(dataset, columns=columns).to_pandas()
    states = [store_partition(model, dataset, frame, tmp_path) for model in (left, right)]
    db_session.commit()
    expected = evaluation.shared_holdout(frame, states)
    monkeypatch.setattr(settings, "ml_train_random_state", 999)
    monkeypatch.setattr(ml_comparison, "_comparison_frame", lambda *a, **kw: frame.sample(frac=1))
    seen = []

    def report(model, holdout, *, target):
        seen.append(holdout)
        pipeline = DummyClassifier().fit(frame, frame[target])
        return EstimatorReport(pipeline, X_test=holdout, y_test=holdout[target], pos_label=1)

    monkeypatch.setattr(ml_comparison, "_report", report)
    answer = ml_comparison.compare(db_session, left=left, right=right)
    assert answer["split"]["verified"] is True
    assert seen[0].to_dict("records") == expected.to_dict("records") == seen[1].to_dict("records")
    metadata = right.metrics_json["evaluation"]
    right.metrics_json = {**right.metrics_json, "evaluation": {**metadata, "sha256": "corrupt"}}
    with pytest.raises(TabularError) as error:
        ml_comparison.compare(db_session, left=left, right=right)
    assert error.value.code == "ML_COMPARE_UNVERIFIED_PARTITION"


def test_worker_publishes_partition_to_existing_object_store(
    db_session,
    workspace,
    dataset,
    enabled,
    store,
    monkeypatch,
):
    _stub_harness(monkeypatch)
    stub = tabular_ml.supervise_harness

    def with_partition(argv, **kwargs):
        answer = stub(argv, **kwargs)
        manifest = json.loads(Path(argv[2]).read_text())
        frame = pd.read_parquet(
            manifest["data_path"], columns=[*manifest["features"], manifest["target"]]
        )
        state = partition(frame)
        state["dataset"] = manifest["dataset"]
        state["target"] = manifest["target"]
        metadata = evaluation.write_partition(state, manifest["evaluation_path"])
        result = Path(argv[3])
        body = json.loads(result.read_text())
        body["metrics"]["evaluation"] = metadata
        result.write_text(json.dumps(body))
        return answer

    monkeypatch.setattr(tabular_ml, "supervise_harness", with_partition)
    model = tabular_ml.submit_training(
        db_session,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        target="churn",
        algo="linear",
    )
    db_session.refresh(model)
    metadata = model.metrics_json["evaluation"]
    assert metadata["status"] == "stored"
    assert metadata["key"] == tabular_ml.evaluation_partition_key(workspace.id, model.id)
    assert tabular_ml.evaluation_partition_uri(model) == get_object_store().uri(metadata["key"])
    assert metadata["key"] not in get_object_store().list_keys(model.model_uri)
    assert (
        evaluation.read_partition(
            get_object_store().read_bytes(metadata["key"]), sha256=metadata["sha256"]
        )["dataset"]["id"]
        == dataset.id
    )
