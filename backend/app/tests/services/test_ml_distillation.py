"""Distillation is reviewed-label learning plus independent held-out evidence."""
from __future__ import annotations

from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest
from sklearn.model_selection import train_test_split

from app.core.config import settings
from app.models.tabular import MLModel
from app.resources import ml_distillation
from app.services import ml_registry, tabular_ml
from app.services.ml.families import SpecInvalid, TABULAR
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_registry import registry  # noqa: F401
from app.tests.services.test_llm_label_review import (  # noqa: F401
    confirm, object_store_root, review_body, review_case,
)
from app.tests.services.test_ml_training import (  # noqa: F401
    dataset, enabled, store, workspace, _run_harness, _stub_harness,
)


def provenance(labels, **overrides):
    return {
        "version": 1,
        "source_dataset_id": "teacher-dataset",
        "source_version": 1,
        "reviewed_dataset_id": "reviewed-dataset",
        "decision_id": "human-review",
        "label_column": "label",
        "labels": ["normal", "urgent"],
        "rows_reviewed": len(labels),
        "corrected_rows": 2,
        "teacher_labels": list(labels),
        "llm_estimated_cost_usd": 0.012,
        "llm_labeled_rows": len(labels),
        "unknown_attempts": 0,
        "teacher_model": {"provider": "openai", "model": "gpt-4o-mini"},
        **overrides,
    }


def test_human_accuracy_and_teacher_agreement_have_separate_test_denominators():
    data = provenance(["urgent", "normal", "urgent", "normal", "urgent"])
    card = ml_distillation.evaluate(
        data, indices=[4, 1, 3], predicted=["urgent", "urgent", "normal"],
        reviewed=["urgent", "normal", "urgent"],
    )
    assert card["test_rows"] == 3
    assert card["agreement"] == pytest.approx(2 / 3)
    assert card["reviewed_accuracy"] == pytest.approx(1 / 3)
    assert card["teacher_accuracy_on_reviewed"] == pytest.approx(2 / 3)
    assert card["llm_estimated_cost_per_1000"] == pytest.approx(2.4)
    assert card["inference_cost_per_1000"] is None
    assert card["inference_cost_basis"] == "unavailable"
    assert "teacher_labels" not in card
    json.dumps(card, allow_nan=False)


@pytest.mark.parametrize("value", [0, 0.002, 1000])
def test_explicit_inference_cost_preserves_zero_and_never_uses_latency(value):
    data = provenance(["urgent", "normal"], unknown_attempts=1)
    card = ml_distillation.evaluate(
        data, indices=[1], predicted=["normal"], reviewed=["normal"], inference_cost=value,
    )
    assert card["inference_cost_per_1000"] == value
    assert card["inference_cost_basis"] == "declared"
    assert card["unknown_attempts"] == 1
    assert card["llm_cost_basis"] == "declared_tariff"


@pytest.mark.parametrize("value", [-1, 1001, True, "0.1", float("nan"), float("inf")])
def test_declared_cost_spec_rejects_unbounded_or_non_numeric_values(value):
    with pytest.raises(SpecInvalid):
        TABULAR.parse_spec({"distillation_inference_cost_per_1000": value}, task="classification")


def test_cost_spec_is_optional_and_classification_only():
    key = "distillation_inference_cost_per_1000"
    assert key not in TABULAR.parse_spec({}, task="classification")
    assert TABULAR.parse_spec({key: 0}, task="classification")[key] == 0
    assert key not in TABULAR.parse_spec({key: 0.01}, task="regression")


def test_snapshot_hashes_teacher_labels_without_returning_them_in_model_details():
    data = provenance(["urgent", "normal"])
    frozen = ml_distillation.snapshot(data)
    assert "teacher_labels" not in frozen
    assert len(frozen["teacher_labels_sha256"]) == 64
    data["teacher_labels"].reverse()
    assert frozen != ml_distillation.snapshot(data)


def test_generated_labels_require_review_but_other_targets_and_regression_still_work(dataset, enabled):
    dataset.produced_by = "llm_label_dataset_v1"
    dataset.lineage_json = {"labeling": {"label_column": "churn"}}
    with pytest.raises(TabularError) as error:
        tabular_ml.validate_training(dataset, task="classification", target="churn")
    assert error.value.code == "ML_LABEL_REVIEW_REQUIRED"
    assert tabular_ml.validate_training(dataset, task="classification", target="plan").target == "plan"
    assert tabular_ml.validate_training(dataset, task="regression", target="arpu").task == "regression"


def test_inference_cost_is_refused_when_the_training_cannot_produce_distillation(dataset, enabled):
    cost = {"distillation_inference_cost_per_1000": 0}
    with pytest.raises(TabularError) as error:
        tabular_ml.validate_training(dataset, task="classification", target="churn", spec=cost)
    assert error.value.code == "ML_DISTILLATION_SOURCE_REQUIRED"
    dataset.produced_by = "llm_label_review_v1"
    dataset.lineage_json = {"label_review": {"label_column": "churn"}}
    with pytest.raises(TabularError) as other_target:
        tabular_ml.validate_training(dataset, task="classification", target="plan", spec=cost)
    assert other_target.value.code == "ML_DISTILLATION_SOURCE_REQUIRED"
    assert tabular_ml.validate_training(
        dataset, task="classification", target="churn", spec=cost
    ).spec["distillation_inference_cost_per_1000"] == 0


def test_submit_and_worker_revalidate_review_but_model_api_has_no_teacher_rows(
    db_session, dataset, enabled, monkeypatch
):
    data = provenance(["normal", "urgent"] * 30, label_column="churn", reviewed_dataset_id=dataset.id)
    dataset.produced_by = "llm_label_review_v1"
    dataset.lineage_json = {"label_review": {"label_column": "churn"}}
    db_session.commit()
    seen = []

    def resolve(db, source, task, target):
        seen.append((source.id, task, target))
        return deepcopy(data)

    monkeypatch.setattr(tabular_ml, "_distillation_provenance", resolve)
    captured = _stub_harness(monkeypatch)
    model = tabular_ml.submit_training(
        db_session, workspace_id=dataset.workspace_id, dataset_ref={"dataset_id": dataset.id},
        task="classification", target="churn", spec={"distillation_inference_cost_per_1000": 0.01},
    )
    assert model.status == "ready", model.error
    assert seen == [(dataset.id, "classification", "churn")] * 2
    assert captured["manifest"]["distillation"] == data
    detail = tabular_ml.serialize_model(model, include_detail=True)
    assert "teacher_labels" not in detail["params"]["distillation"]
    assert detail["params"]["distillation"] == ml_distillation.snapshot(data)


def test_a_changed_review_stops_worker_before_any_fit(db_session, dataset, enabled, monkeypatch):
    data = provenance(["normal", "urgent"] * 30, label_column="churn")
    dataset.produced_by = "llm_label_review_v1"
    monkeypatch.setattr(tabular_ml, "_distillation_provenance", lambda *_: deepcopy(data))
    spec = tabular_ml.validate_training(dataset, task="classification", target="churn")
    model = tabular_ml.create_model(db_session, workspace_id=dataset.workspace_id, spec=spec)
    db_session.commit()
    data["teacher_labels"][0] = "urgent"
    captured = _stub_harness(monkeypatch)
    result = tabular_ml.run_training(model.id)
    db_session.expire_all()
    assert result["status"] == "failed"
    assert "ML_LABEL_REVIEW_CHANGED" in db_session.get(MLModel, model.id).error
    assert not captured


def test_real_harness_and_export_evaluate_the_served_classifier_on_untouched_rows(tmp_path):
    import mlflow.sklearn
    from sklearn.model_selection import FixedThresholdClassifier

    rows = 1500
    data = pd.DataFrame({
        "signal": np.arange(rows) % 2,
        "label": ["urgent" if index % 2 else "normal" for index in range(rows)],
    })
    original = data["label"].tolist()
    data.loc[[7, 500], "label"] = None
    surviving = data.dropna(subset=["label"])
    _, test = train_test_split(
        surviving, test_size=0.25, random_state=42, stratify=surviving["label"]
    )
    # The teacher is wrong only on held-out rows; fitting on teacher/test labels
    # would reverse the intended distinction between agreement and accuracy.
    for index in test.index:
        original[index] = "normal" if original[index] == "urgent" else "urgent"
    evidence = provenance(original, corrected_rows=len(test))
    # Source parquet indices are not stable row identities.
    data.index = [0] * rows
    path = tmp_path / "reviewed.parquet"
    data.to_parquet(path)
    manifest = {
        "data_path": str(path), "model_dir": str(tmp_path / "student"),
        "task": "classification", "target": "label", "features": ["signal"],
        "estimator": "sklearn.linear_model.LogisticRegression",
        "params": {"max_iter": 100, "random_state": 42},
        "random_state": 42, "min_rows": 40, "test_size": 0.25, "cv": 0,
        "importance_rows": 30,
        "spec": {"calibration": "sigmoid", "threshold": "f1"},
        "distillation": evidence,
    }
    code, summary, stderr = _run_harness(tmp_path / "distilled", manifest)
    assert code == 0, stderr
    card = summary["metrics"]["distillation"]
    assert card["test_rows"] == len(test)
    assert card["reviewed_accuracy"] == 1
    assert card["agreement"] == card["teacher_accuracy_on_reviewed"] == 0
    assert card["inference_cost_per_1000"] is None
    assert [column["name"] for column in summary["signature"]["inputs"]] == ["signal"]

    student = mlflow.sklearn.load_model(manifest["model_dir"])
    assert isinstance(student, FixedThresholdClassifier)
    predictions = student.predict(test[["signal"]].astype(float))
    assert np.mean(predictions == test["label"]) == card["reviewed_accuracy"]

    # Distillation adds evidence only: omitting it leaves the actual artifact's
    # decisions unchanged, including calibration and the persisted threshold.
    ordinary = {key: value for key, value in manifest.items() if key != "distillation"}
    ordinary["model_dir"] = str(tmp_path / "ordinary")
    code, baseline, stderr = _run_harness(tmp_path / "baseline", ordinary)
    assert code == 0, stderr
    assert "distillation" not in baseline["metrics"]
    loaded = mlflow.sklearn.load_model(ordinary["model_dir"])
    assert loaded.threshold == student.threshold
    np.testing.assert_array_equal(loaded.predict(test[["signal"]].astype(float)), predictions)


def test_mlflow_records_distillation_without_turning_unknown_cost_into_zero(registry):
    card = ml_distillation.evaluate(
        provenance(["urgent", "normal"]), indices=[0, 1],
        predicted=["normal", "normal"], reviewed=["urgent", "normal"],
    )
    published = ml_registry.publish(
        model_name="distillation.evidence", source_uri="file:///tmp/test-model",
        metrics={"distillation": card},
    )
    assert published is not None
    metrics = ml_registry._client().get_run(published["run_id"]).data.metrics
    assert metrics["distillation.agreement"] == 0.5
    assert metrics["distillation.reviewed_accuracy"] == 0.5
    assert metrics["distillation.teacher_accuracy_on_reviewed"] == 1
    assert metrics["distillation.test_rows"] == 2
    assert metrics["distillation.llm_estimated_cost_per_1000"] == 6
    assert "distillation.inference_cost_per_1000" not in metrics


@pytest.mark.parametrize("ticket_rows,inference_cost", [(48, 0), (240, 0.01)])
def test_confirmed_review_trains_and_serves_a_real_model_with_portable_evidence(
    db_session, review_case, enabled, registry, monkeypatch, tmp_path, ticket_rows, inference_cost
):
    import mlflow.pyfunc
    import polars as pl

    from app.services import llm_label_review as review
    from app.services.tabular_datasets import register_frame
    from app.services.tabular_predict import predict_rows

    case = review_case
    if ticket_rows != 48:
        # Qualify text on enough training rows for skrub's high-cardinality
        # encoder, while retaining the small fixture as an honest counterexample.
        register_frame(
            db_session, workspace_id=case.workspace.id, name=case.source.name, into=case.source,
            frame=pl.DataFrame({
                "ticket": [f"{'invoice' if i % 2 else 'network'} ticket {i}" for i in range(ticket_rows)],
                "private_note": ["retained, not review context"] * ticket_rows,
                "topic": ["billing" if i % 2 else "technical" for i in range(ticket_rows)],
            }),
        )
        case.job.result = {**case.job.result, "rows_total": ticket_rows,
                           "estimated_cost_usd": 0.5 * ticket_rows / 1000}
        db_session.flush()
        case.binding = review.make_binding(db_session, workspace_id=case.workspace.id, dataset_id=case.source.id)
        case.decision.rationale = {**case.decision.rationale, "label_review": case.binding}
        case.run.checkpoints = [{**row, "label_review": case.binding} for row in case.run.checkpoints]
        db_session.commit()
    output = review.apply_review(
        db_session, case.decision, reviewer_id=case.owner.id,
        body=review_body(case, [{"row_id": 0, "label": "billing"}]),
    )
    confirm(db_session, case, output)
    monkeypatch.setattr(settings, "ml_train_memory_limit_mb", 4096)
    monkeypatch.setattr(settings, "ml_train_report_state_limit_mb", 0)
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    model = tabular_ml.submit_training(
        db_session, workspace_id=case.workspace.id, dataset_ref={"dataset_id": output.id},
        task="classification", target="topic", features=["ticket"], algo="linear",
        spec={"text_encoder": "minhash", "distillation_inference_cost_per_1000": inference_cost},
        run_id=case.run.id, created_by=case.owner.id,
    )
    assert model.status == "ready", model.error
    card = tabular_ml.serialize_model(model, include_detail=True)["metrics"]["distillation"]
    assert card["source_dataset_id"] == case.source.id
    assert card["reviewed_dataset_id"] == output.id
    assert card["decision_id"] == case.decision.id
    assert card["test_rows"] == ticket_rows // 4 and card["rows_reviewed"] == ticket_rows
    assert card["corrected_rows"] == 1
    assert card["llm_estimated_cost_per_1000"] == 0.5
    assert card["inference_cost_per_1000"] == inference_cost
    assert card["inference_cost_basis"] == "declared"
    assert model.features == ["ticket"]
    example = [{"ticket": "invoice ticket 100"}]
    result = predict_rows(db_session, model, example)
    assert result["rows"] == 1 and result["classes"] == ["billing", "technical"]
    tracked = ml_registry._client().get_run(model.mlflow_run_id).data
    assert tracked.metrics["distillation.inference_cost_per_1000"] == inference_cost
    assert tracked.metrics["distillation.agreement"] == card["agreement"]
    assert tracked.tags["agentium.distillation.decision_id"] == case.decision.id
    assert tracked.tags["agentium.distillation.inference_cost_basis"] == "declared"
    version = ml_registry._client().get_model_version_by_alias(model.mlflow_model_name, "champion")
    portable = mlflow.pyfunc.load_model(version.source).predict(pd.DataFrame(example)).tolist()
    assert portable == [row["prediction"] for row in result["predictions"]]
    # Keep the synthetic qualification evidence available without another fit.
    (tmp_path / "distillation-proof.json").write_text(json.dumps({
        "fixture": f"{ticket_rows} synthetic invoice/network tickets, one human label correction",
        "metrics": {"distillation": card},
        "signature": model.signature_json,
        "inputs": example,
        "predictions": result["predictions"],
        "portable_predictions": portable,
        "portable_equality": True,
        "mlflow_run_id": model.mlflow_run_id,
        "mlflow_metrics": tracked.metrics,
        "mlflow_tags": tracked.tags,
        "cost_note": "LLM cost is the declared tariff estimate; student cost is an explicit test declaration, not a measured saving.",
    }, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
