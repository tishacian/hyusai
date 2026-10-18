"""M4.3 with real external models: import, serve, journal, export, requalify.

The external models are built here with plain scikit-learn — ColumnTransformer,
OneHotEncoder, StandardScaler and a RandomForest, a LogisticRegression or a
regressor — and saved by MLflow with skops and a column signature, exactly as
an importer would. Validation runs in the real isolated reader (eager worker).
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import ml_imports as import_api
from app.api.v1.endpoints import ml_models as models_api
from app.core.config import settings
from app.models.audit import AuditLog
from app.models.tabular import MLModel, MLPrediction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services import ml_requalification as requalification
from app.services import tabular_predict
from app.services.tabular_datasets import TabularError

pytest.importorskip("mlflow.sklearn")
pytest.importorskip("skops")


def frame(rows: int = 90, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "plan": rng.choice(["prepaid", "postpaid", "family"], rows),
            "tenure": rng.integers(1, 90, rows),
            "arpu": rng.normal(40.0, 8.0, rows).round(2),
        }
    )


def estimator(kind: str):
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    data = frame()
    prepare = ColumnTransformer(
        [
            ("cat", OneHotEncoder(handle_unknown="ignore"), ["plan"]),
            ("num", StandardScaler(), ["tenure", "arpu"]),
        ]
    )
    if kind == "forest":
        target = np.where(data.tenure < 30, "churn", np.where(data.arpu > 45, "upsell", "stay"))
        model = RandomForestClassifier(n_estimators=12, random_state=0)
    elif kind == "logistic":
        target = (data.tenure < 30).astype(int)
        model = LogisticRegression(max_iter=500)
    else:
        target = data.arpu * 3 + data.tenure + np.where(data.plan == "family", 5.0, 0.0)
        model = RandomForestRegressor(n_estimators=12, random_state=0)
    return Pipeline([("prepare", prepare), ("model", model)]).fit(data, target), data


def save(
    pipeline,
    data,
    directory: Path,
    *,
    serialization="skops",
    signature="columns",
    trusted=None,
    **extra,
) -> Path:
    import mlflow.sklearn
    import skops.io as sio
    from mlflow.models import infer_signature

    sample = data.head(40)
    declared = None
    if serialization == "skops":
        declared = (
            trusted if trusted is not None else sio.get_untrusted_types(data=sio.dumps(pipeline))
        )
    model_signature = None
    if signature == "columns":
        model_signature = infer_signature(sample, pipeline.predict(sample))
    elif signature == "tensor":
        model_signature = infer_signature(
            sample[["tenure", "arpu"]].to_numpy(dtype=float), pipeline.predict(sample)
        )
    mlflow.sklearn.save_model(
        pipeline,
        path=str(directory),
        serialization_format=serialization,
        skops_trusted_types=declared,
        signature=model_signature,
        input_example=data.head(3),
        pip_requirements=["scikit-learn", "skops"],
        **extra,
    )
    return directory


def zipped(directory: Path, *, prefix: str = "model/") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, prefix + path.relative_to(directory).as_posix())
    return buffer.getvalue()


def validation(pipeline, data, *, rows: int = 30, probabilities: bool = True) -> bytes:
    sample = data.tail(rows).reset_index(drop=True)
    records = json.loads(sample.to_json(orient="records"))
    predicted = pipeline.predict(sample)
    if hasattr(pipeline, "classes_"):
        expected = {
            "labels": [item.item() if hasattr(item, "item") else item for item in predicted],
            "classes": [
                item.item() if hasattr(item, "item") else item for item in pipeline.classes_
            ],
        }
        if probabilities:
            expected["probabilities"] = pipeline.predict_proba(sample).tolist()
    else:
        expected = {"values": [float(value) for value in predicted]}
    return json.dumps({"rows": records, "expected": expected}).encode()


@pytest.fixture()
def case(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    monkeypatch.setattr(settings, "worker_eager_mode", True)
    monkeypatch.setattr(settings, "ml_import_enabled", True)
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    monkeypatch.setattr(settings, "tabular_data_enabled", True)
    monkeypatch.setattr(settings, "ml_registry_enabled", False)
    monkeypatch.setattr(settings, "ml_rbac_enforced", False)
    tabular_predict.reset_cache()
    workspace = Workspace(name="Import", slug="import-" + uuid4().hex)
    admin = User(
        id=str(uuid4()),
        username="import-" + uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
        is_active=True,
    )
    db_session.add_all([workspace, admin])
    db_session.flush()
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=admin.id,
        role="admin",
        role_template="workspace_admin",
    )
    db_session.add(member)
    db_session.commit()
    app = FastAPI()
    app.include_router(import_api.router, prefix="/ml-models")
    app.include_router(models_api.router, prefix="/ml-models")
    current = {"user": admin}
    for module in (import_api, models_api):
        app.dependency_overrides[module.get_current_workspace] = lambda: workspace
        app.dependency_overrides[module.get_current_user] = lambda: current["user"]
        app.dependency_overrides[module.get_db] = lambda: db_session
    app.dependency_overrides[models_api.predict_caller] = lambda: models_api.PredictCaller(
        workspace_id=workspace.id, kind="session", user_id=current["user"].id
    )
    yield type(
        "Case",
        (),
        {
            "client": TestClient(app),
            "workspace": workspace,
            "admin": admin,
            "member": member,
            "current": current,
            "tmp": tmp_path,
        },
    )
    tabular_predict.reset_cache()


def post_import(case, archive: bytes, checks: bytes, **form):
    fields = {"task": "classification", "name": "Churn import", "target": "churn", **form}
    return case.client.post(
        "/ml-models/import",
        files={
            "archive": ("model.zip", archive, "application/zip"),
            "validation": ("validation.json", checks, "application/json"),
        },
        data=fields,
    )


def imported(case, kind="forest", **form):
    pipeline, data = estimator(kind)
    directory = save(pipeline, data, case.tmp / f"bundle-{uuid4().hex[:6]}")
    task = "regression" if kind == "regressor" else "classification"
    response = post_import(case, zipped(directory), validation(pipeline, data), task=task, **form)
    assert response.status_code == 202, response.json()
    job = response.json()["job"]
    status = case.client.get(f"/ml-models/import/{job['id']}").json()["job"]
    return pipeline, data, status


def audits(db, workspace):
    return [
        event.details["after"]
        for event in db.query(AuditLog)
        .filter_by(event_type="ml.model.import", workspace_id=workspace.id)
        .order_by(AuditLog.timestamp)
        .all()
    ]


@pytest.mark.parametrize("kind", ["forest", "logistic", "regressor"])
def test_an_imported_model_serves_journals_exports_and_requalifies(
    db_session, case, monkeypatch, kind
):
    from app.services.ml_exports import build_export
    from app.tests.services.test_ml_requalification import _upgrade

    pipeline, data, status = imported(case, kind)
    assert status["status"] == "completed", status
    assert status["result"]["verdict"] == "accepted"
    model = db_session.get(MLModel, status["result"]["model_id"])
    assert (model.family, model.status, model.is_champion, model.version) == (
        "external",
        "ready",
        True,
        1,
    )
    provenance = model.params_json["import"]
    assert provenance["archive_sha256"] and provenance["uploaded_by"] == case.admin.id
    assert provenance["estimator"] in {
        "RandomForestClassifier",
        "LogisticRegression",
        "RandomForestRegressor",
    }
    artifact = model.metrics_json["artifact"]
    assert artifact["family"] == "external"
    assert artifact["trust_profile"] == "external-sklearn-skops-v1"
    assert artifact["runtime"] == requalification.reader_runtime(model)
    assert model.metrics_json["runtime_reference"]["source"] == "import_validation"
    assert all(
        field["hint_source"] == "import_validation" for field in model.signature_json["inputs"]
    )
    # Served through /predict, journalled, with the estimator's own answers.
    row = json.loads(data.tail(1).to_json(orient="records"))[0]
    answer = case.client.post(f"/ml-models/{model.id}/predict", json={"inputs": [row]})
    assert answer.status_code == 200, answer.json()
    body = answer.json()
    expected = pipeline.predict(data.tail(1))[0]
    if kind == "regressor":
        assert body["predictions"][0]["prediction"] == pytest.approx(float(expected))
    else:
        assert body["predictions"][0]["prediction"] == str(expected)
        assert len(body["predictions"][0]["probabilities"]) == len(pipeline.classes_)
    assert db_session.get(MLPrediction, body["prediction_id"]).served_id == model.id
    # M4.1 export is unchanged for an imported model.
    archive, metadata = build_export(model, case.tmp / f"export-{kind}")
    assert metadata["artifact_fingerprint"] and archive.exists()
    # M4.2: a simulated upgrade refuses, the stored rows requalify it.
    tabular_predict.reset_cache()
    _upgrade(monkeypatch, case.tmp)
    refused = case.client.post(f"/ml-models/{model.id}/predict", json={"inputs": [row]})
    assert refused.json()["detail"]["code"] == "ML_ARTIFACT_RUNTIME_MISMATCH"
    outcome = requalification.requalify(db_session, model, actor=case.admin.id)
    assert outcome["attestation"]["verdict"] == "qualified", outcome
    assert outcome["attestation"]["rows_compared"] == 30
    again = case.client.post(f"/ml-models/{model.id}/predict", json={"inputs": [row]})
    assert again.status_code == 200
    accepted = [
        entry for entry in audits(db_session, case.workspace) if entry["verdict"] == "accepted"
    ]
    assert len(accepted) == 1 and accepted[0]["archive_sha256"] == provenance["archive_sha256"]
    # Sizes, hashes and gaps only: no validation value reaches the audit.
    recorded = json.dumps(accepted[0])
    assert not any(plan in recorded for plan in ("prepaid", "postpaid", "family"))
    assert accepted[0]["validation_rows"] == 30


def test_a_new_version_joins_an_external_lineage_without_taking_over(db_session, case):
    _, _, first = imported(case, "logistic")
    base = first["result"]["model_id"]
    _, _, second = imported(case, "logistic", lineage_model_id=base)
    assert second["result"]["verdict"] == "accepted", second
    newer = db_session.get(MLModel, second["result"]["model_id"])
    assert (newer.version, newer.is_champion) == (2, False)
    assert db_session.get(MLModel, base).is_champion is True
    # A name already used is refused instead of silently joining a lineage.
    pipeline, data = estimator("logistic")
    directory = save(pipeline, data, case.tmp / "taken")
    response = post_import(case, zipped(directory), validation(pipeline, data))
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "lineage_name_taken"


def test_what_does_not_apply_to_an_imported_model_is_refused_with_a_reason(
    db_session, case, monkeypatch
):
    from app.services import ml_retraining
    from app.services.tabular_monitoring import data_drift

    pipeline, data, status = imported(case, "logistic")
    model = db_session.get(MLModel, status["result"]["model_id"])
    row = json.loads(data.tail(1).to_json(orient="records"))[0]
    explain = case.client.post(
        f"/ml-models/{model.id}/predict", json={"inputs": [row], "explain": True}
    )
    assert explain.status_code == 409
    assert explain.json()["detail"]["code"] == "ML_EXTERNAL_UNSUPPORTED"
    with pytest.raises(TabularError) as refused:
        tabular_predict.predict_rows(db_session, model, [row], explain=True)
    assert refused.value.code == "ML_EXTERNAL_UNSUPPORTED"
    assert data_drift(model, [], None)["reason"] == "no_training_distribution"
    with pytest.raises(TabularError) as refused:
        ml_retraining._require_supported(model)
    assert refused.value.details["reason"] == "scheduled_monitoring"
    assert requalification.capture_reference(db_session, model, actor="x")["action"] == (
        "already_captured"
    )
    # Without its import reference nothing can be re-derived: no dataset.
    model.metrics_json = {
        key: value for key, value in model.metrics_json.items() if key != "runtime_reference"
    }
    with pytest.raises(TabularError) as refused:
        requalification.capture_reference(db_session, model, actor="x")
    assert refused.value.details["reason"] == "import_validation_only"
    db_session.rollback()
    db_session.expire_all()
    model = db_session.get(MLModel, status["result"]["model_id"])
    state = requalification.runtime_status(db_session, model)
    assert state["status"] == "current" and state["reference"]["source"] == "import_validation"
    assert state["can_capture"] is False
    from app.services.tabular_ml import catalog_payload

    assert "external" not in {family["key"] for family in catalog_payload()["families"]}


def test_training_cannot_join_an_imported_lineage(db_session, case, monkeypatch):
    import polars as pl

    from app.services.tabular_datasets import register_frame
    from app.services.tabular_ml import create_model, validate_training

    _, _, status = imported(case, "logistic")
    model = db_session.get(MLModel, status["result"]["model_id"])
    monkeypatch.setattr(settings, "ml_train_enabled", True)
    monkeypatch.setattr(settings, "ml_train_min_rows", 10)
    dataset = register_frame(
        db_session,
        workspace_id=case.workspace.id,
        name="Churn",
        frame=pl.from_pandas(frame().assign(churn=lambda d: (d.tenure < 30).astype(int))),
        source="upload",
    )
    db_session.commit()
    spec = validate_training(dataset, task="classification", target="churn", name=model.name)
    with pytest.raises(TabularError) as refused:
        create_model(db_session, workspace_id=case.workspace.id, spec=spec)
    assert refused.value.code == "ML_EXTERNAL_LINEAGE"


def test_deleting_an_imported_model_removes_its_stored_validation_rows(db_session, case):
    from app.services.object_store import get_object_store
    from app.services.tabular_ml import delete_model

    _, _, status = imported(case, "logistic")
    model = db_session.get(MLModel, status["result"]["model_id"])
    key = model.metrics_json["runtime_reference"]["key"]
    assert get_object_store().exists(key)
    delete_model(db_session, model)
    assert not get_object_store().exists(key)
    staged = get_object_store().list_keys(
        get_object_store().key("workspaces", case.workspace.id, "ml", "imports")
    )
    assert staged == []
