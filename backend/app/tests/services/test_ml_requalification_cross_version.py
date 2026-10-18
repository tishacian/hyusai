"""Opt-in evidence: a model fitted by another scikit-learn, requalified by this one.

Set ``MLOPS_SKLEARN_OVERLAY`` to a directory holding only another
scikit-learn (``pip install --target DIR --no-deps scikit-learn==X``). Prepended
to PYTHONPATH it shadows the venv's scikit-learn, so:

* the training harness really fits and serializes with version X;
* the reference capture child really loads and predicts with version X;
* requalification and serving then really run this venv's version.

The only stand-in is the capture *parent's* metadata check: this test process
is not the producer image, so during capture it reports version X the way the
producer image would. Every output compared was computed by real code.
"""

# Fixtures imported from the training suite are re-declared as test arguments.
# ruff: noqa: F811

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.tabular import MLModel
from app.resources import ml_artifact_contract
from app.services import ml_requalification as service
from app.services import tabular_ml, tabular_predict
from app.services.tabular_datasets import TabularError, materialize_dataset, register_frame
from app.tests.services.test_ml_requalification import admin, serving  # noqa: F401
from app.tests.services.test_ml_training import _frame, enabled, store, workspace  # noqa: F401

OVERLAY = os.environ.get("MLOPS_SKLEARN_OVERLAY")
pytestmark = pytest.mark.skipif(not OVERLAY, reason="MLOPS_SKLEARN_OVERLAY is not set")
BACKEND = Path(__file__).resolve().parents[3]
FEATURES = ["plan", "region", "tenure_months", "arpu", "support_tickets"]


def _producer_version() -> str:
    completed = subprocess.run(
        [sys.executable, "-c", "import importlib.metadata as m; print(m.version('scikit-learn'))"],
        env={**os.environ, "PYTHONPATH": f"{OVERLAY}:{BACKEND}"},
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _fit_with_overlay(db, workspace, tmp_path, estimator, params):
    dataset = register_frame(
        db, workspace_id=workspace.id, name="Cross version", frame=_frame(84), source="upload"
    )
    db.commit()
    data = materialize_dataset(dataset, tmp_path / "data")
    manifest = {
        "data_paths": [str(path) for path in data] if isinstance(data, list) else [str(data)],
        "model_dir": str(tmp_path / "model"),
        "task": "classification",
        "target": "churn",
        "features": FEATURES,
        "estimator": estimator,
        "params": params,
        "test_size": 0.25,
        "cv": 0,
        "random_state": 42,
        "min_rows": 10,
        "curve_points": 20,
        "importance_rows": 100,
        "evaluation_path": str(tmp_path / "report" / "evaluation.json.gz"),
        "dataset": {"id": dataset.id, "version": dataset.version},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    completed = subprocess.run(
        [
            sys.executable,
            str(tabular_ml.harness_path()),
            str(tmp_path / "manifest.json"),
            str(tmp_path / "result.json"),
        ],
        env={**os.environ, "PYTHONPATH": f"{OVERLAY}:{BACKEND}"},
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    summary = json.loads((tmp_path / "result.json").read_text())
    model = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Cross version",
        slug="cross-version",
        version=1,
        task="classification",
        family="tabular",
        algo="gradient_boosting",
        target="churn",
        features=FEATURES,
        dataset_id=dataset.id,
        status="ready",
        is_champion=True,
        test_size=0.25,
        cross_validation=0,
    )
    db.add(model)
    db.flush()
    uri, size = tabular_ml.upload_model_dir(
        tmp_path / "model", workspace_id=workspace.id, model_id=model.id
    )
    evaluation = summary["metrics"]["evaluation"]
    key = tabular_ml.evaluation_partition_key(workspace.id, model.id)
    from app.services.object_store import get_object_store

    get_object_store().write_bytes(key, Path(manifest["evaluation_path"]).read_bytes())
    evaluation.update(key=key, status="stored")
    tabular_ml._apply_summary(model, {**summary, "model_uri": uri, "artifact_bytes": size})
    model.trained_at = datetime.utcnow()
    db.commit()
    return model


@pytest.mark.parametrize(
    "estimator,params",
    [
        ("sklearn.ensemble.HistGradientBoostingClassifier", {"max_iter": 20, "random_state": 42}),
        ("sklearn.linear_model.LogisticRegression", {"max_iter": 500}),
    ],
)
def test_a_scikit_learn_minor_upgrade_is_requalified_on_real_outputs(
    db_session, workspace, admin, serving, monkeypatch, tmp_path, capsys, estimator, params
):
    """Whatever the verdict, it is coherent: qualified serves, anything else stays refused."""
    producer = _producer_version()
    real = ml_artifact_contract.version
    current = real("scikit-learn")
    assert producer != current, "the overlay must hold another scikit-learn"
    model = _fit_with_overlay(db_session, workspace, tmp_path, estimator, params)
    assert model.metrics_json["artifact"]["runtime"]["scikit-learn"] == producer

    with monkeypatch.context() as producer_image:
        producer_image.setattr(
            ml_artifact_contract,
            "version",
            lambda name: producer if name == "scikit-learn" else real(name),
        )
        environment = service._child_environment

        def overlay(scratch):
            values = environment(scratch)
            values["PYTHONPATH"] = f"{OVERLAY}:{values['PYTHONPATH']}"
            return values

        producer_image.setattr(service, "_child_environment", overlay)
        captured = service.capture_reference(db_session, model, actor="producer-image")
    assert captured["action"] == "captured"

    model = db_session.get(MLModel, model.id)
    _, rows, _ = service.reference_rows(db_session, model)
    with pytest.raises(TabularError) as refused:
        tabular_predict.predict_rows(db_session, model, rows[:2], version=1)
    assert refused.value.code == "ML_ARTIFACT_RUNTIME_MISMATCH"

    outcome = service.requalify(db_session, model, actor=admin.id, user=admin)
    attestation = outcome["attestation"]
    with capsys.disabled():
        print(
            "\ncross-version requalification:",
            json.dumps(
                {
                    "estimator": estimator.rsplit(".", 1)[-1],
                    "producer": producer,
                    "reader": current,
                    "verdict": attestation["verdict"],
                    "rows_compared": attestation["rows_compared"],
                    "metrics": attestation["metrics"],
                    "error_code": attestation["error_code"],
                },
                sort_keys=True,
            ),
        )
    assert attestation["reader_runtime"]["scikit-learn"] == current
    assert attestation["producer_runtime"]["scikit-learn"] == producer
    model = db_session.get(MLModel, model.id)
    if attestation["verdict"] == "qualified":
        answer = tabular_predict.predict_rows(db_session, model, rows[:2], version=1)
        assert answer["rows"] == 2
    else:
        with pytest.raises(TabularError):
            tabular_predict.predict_rows(db_session, model, rows[:2], version=1)
