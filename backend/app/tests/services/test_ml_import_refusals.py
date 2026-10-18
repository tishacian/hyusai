"""M4.3 refusals: every unsafe format, bad archive or bad validation is refused,
with its reason, before or instead of registration — and every attempt is
audited. The bundles are produced by real MLflow/sklearn calls where possible.
"""

# Fixtures imported from the import suite are re-declared as test arguments.
# ruff: noqa: F811

from __future__ import annotations

import functools
import io
import json
import zipfile
from uuid import uuid4

import mlflow.pyfunc
import numpy as np
import pytest
import yaml

from app.core.config import settings
from app.models.tabular import MLModel
from app.services import ml_import
from app.services.tabular_datasets import TabularError
from app.tests.services.test_ml_import import (  # noqa: F401
    audits,
    case,
    estimator,
    post_import,
    save,
    validation,
    zipped,
)


def _double(values):
    """An importer's own function: code the reader would have to import."""
    return values * 2


class Echo(mlflow.pyfunc.PythonModel):
    def predict(self, context, model_input, params=None):
        return model_input


def _refused(case, response, status, code, reason=None):
    assert response.status_code == status, response.json()
    detail = response.json()["detail"]
    assert detail["code"] == code
    if reason:
        assert detail["reason"] == reason
    last = audits_of(case)[-1]
    assert last["verdict"] == "refused" and last["code"] == code
    if reason:
        assert last["reason"] == reason
    return detail


def audits_of(case):
    from app.db.base import SessionLocal

    with SessionLocal() as db:
        return audits(db, case.workspace)


def _bundle(case, **options):
    pipeline, data = estimator("forest")
    directory = save(pipeline, data, case.tmp / f"b-{uuid4().hex[:6]}", **options)
    return pipeline, data, directory


def _edit_mlmodel(directory, change):
    path = directory / "MLmodel"
    config = yaml.safe_load(path.read_text())
    change(config)
    path.write_text(yaml.safe_dump(config))


@pytest.mark.parametrize(
    "serialization,reason",
    [("pickle", "pickle_serialization"), ("cloudpickle", "cloudpickle_serialization")],
)
def test_formats_that_run_code_at_load_are_refused(case, serialization, reason):
    pipeline, data, directory = _bundle(case, serialization=serialization)
    response = post_import(case, zipped(directory), validation(pipeline, data))
    _refused(case, response, 422, "ML_IMPORT_REJECTED", reason)


def test_joblib_and_other_flavors_are_refused(case):
    pipeline, data, directory = _bundle(case)
    _edit_mlmodel(
        directory, lambda c: c["flavors"]["sklearn"].update(serialization_format="joblib")
    )
    response = post_import(case, zipped(directory), validation(pipeline, data))
    _refused(case, response, 422, "ML_IMPORT_REJECTED", "joblib_serialization")
    pipeline, data, directory = _bundle(case)
    _edit_mlmodel(directory, lambda c: c["flavors"].update(onnx={"onnx_version": "1.0"}))
    response = post_import(case, zipped(directory), validation(pipeline, data))
    _refused(case, response, 422, "ML_IMPORT_REJECTED", "flavor_unsupported")


def test_a_custom_pyfunc_is_refused(case):
    from mlflow.models import infer_signature

    _, data = estimator("forest")
    directory = case.tmp / "pyfunc"
    mlflow.pyfunc.save_model(
        path=str(directory),
        python_model=Echo(),
        signature=infer_signature(data.head(5), data.head(5)[["tenure"]]),
    )
    pipeline, _ = estimator("forest")
    response = post_import(case, zipped(directory), validation(pipeline, data))
    _refused(case, response, 422, "ML_IMPORT_REJECTED", "custom_pyfunc")


def test_code_paths_are_refused(case):
    helper = case.tmp / "helper_code.py"
    helper.write_text("VALUE = 1\n")
    pipeline, data, directory = _bundle(case, code_paths=[str(helper)])
    response = post_import(case, zipped(directory), validation(pipeline, data))
    _refused(case, response, 422, "ML_IMPORT_REJECTED", "code_paths")


@pytest.mark.parametrize(
    "function,listed",
    [(_double, "_double"), (functools.partial(np.clip, a_min=0, a_max=None), "functools.partial")],
)
def test_functions_outside_the_reader_profile_are_refused(case, function, listed):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import FunctionTransformer

    _, data = estimator("logistic")
    numeric = data[["tenure", "arpu"]]
    pipeline = Pipeline(
        [("f", FunctionTransformer(function)), ("m", LogisticRegression(max_iter=500))]
    ).fit(numeric, (numeric.tenure < 30).astype(int))
    directory = save(pipeline, numeric, case.tmp / f"fn-{uuid4().hex[:6]}")
    response = post_import(case, zipped(directory), validation(pipeline, numeric))
    detail = _refused(case, response, 422, "ML_IMPORT_REJECTED", "untrusted_types")
    assert any(listed in name for name in detail["types"])


def test_undeclared_skops_types_are_refused(case):
    # MLflow itself refuses to save these undeclared; an edited MLmodel can.
    pipeline, data, directory = _bundle(case)
    _edit_mlmodel(directory, lambda c: c["flavors"]["sklearn"].pop("skops_trusted_types"))
    response = post_import(case, zipped(directory), validation(pipeline, data))
    _refused(case, response, 422, "ML_IMPORT_REJECTED", "trusted_types_undeclared")


@pytest.mark.parametrize(
    "signature,reason", [(None, "signature_missing"), ("tensor", "signature_tensor")]
)
def test_signatures_must_name_columns(case, signature, reason):
    pipeline, data, directory = _bundle(case, signature=signature)
    if signature is None:
        # MLflow infers a signature from the input example; drop it as an
        # importer's older or hand-written MLmodel would.
        _edit_mlmodel(directory, lambda c: c.pop("signature", None))
    response = post_import(case, zipped(directory), validation(pipeline, data))
    _refused(case, response, 422, "ML_IMPORT_REJECTED", reason)


def test_wrong_expected_outputs_fail_validation_with_the_measured_gaps(db_session, case):
    pipeline, data, directory = _bundle(case)
    payload = json.loads(validation(pipeline, data))
    classes = payload["expected"]["classes"]
    payload["expected"]["labels"][0] = next(
        item for item in classes if item != payload["expected"]["labels"][0]
    )
    response = post_import(case, zipped(directory), json.dumps(payload).encode())
    assert response.status_code == 202
    job = case.client.get(f"/ml-models/import/{response.json()['job']['id']}").json()["job"]
    assert job["status"] == "failed" and job["error"] == "ML_IMPORT_VALIDATION_FAILED"
    assert job["result"]["reason"] == "outputs_differ"
    assert job["result"]["metrics"]["label_disagreements"] == 1
    assert "load_ms" in job["result"]["measurements"]
    assert not db_session.query(MLModel).filter_by(workspace_id=case.workspace.id).count()
    last = audits_of(case)[-1]
    assert last["verdict"] == "refused" and last["metrics"]["label_disagreements"] == 1


def test_shifted_probabilities_fail_validation(case):
    pipeline, data, directory = _bundle(case)
    payload = json.loads(validation(pipeline, data))
    payload["expected"]["probabilities"][0] = [
        value + (0.01 if index == 0 else -0.01 if index == 1 else 0.0)
        for index, value in enumerate(payload["expected"]["probabilities"][0])
    ]
    response = post_import(case, zipped(directory), json.dumps(payload).encode())
    job = case.client.get(f"/ml-models/import/{response.json()['job']['id']}").json()["job"]
    assert job["result"]["reason"] == "outputs_differ"
    assert job["result"]["metrics"]["max_abs_proba_diff"] == pytest.approx(0.01, abs=1e-9)


def test_too_few_validation_rows_are_refused(case):
    pipeline, data, directory = _bundle(case)
    response = post_import(case, zipped(directory), validation(pipeline, data, rows=5))
    detail = _refused(case, response, 422, "ML_IMPORT_VALIDATION_INVALID", "rows_out_of_bounds")
    assert detail["min"] == settings.ml_import_min_validation_rows


def test_a_model_over_a_serving_budget_is_refused(case, monkeypatch):
    monkeypatch.setattr(settings, "ml_import_max_load_ms", 0.0001)
    pipeline, data, directory = _bundle(case)
    response = post_import(case, zipped(directory), validation(pipeline, data))
    job = case.client.get(f"/ml-models/import/{response.json()['job']['id']}").json()["job"]
    assert job["error"] == "ML_IMPORT_BUDGET_EXCEEDED"
    assert job["result"]["reason"] == "load_time"
    assert job["result"]["measurements"]["load_ms"] > 0


def _zip(entries, *, mutate=None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for info, content in entries:
            archive.writestr(info, content)
    data = buffer.getvalue()
    return mutate(data) if mutate else data


def _encrypt_flag(data: bytes) -> bytes:
    """Set the 'encrypted' general-purpose bit in local and central headers."""
    patched = bytearray(data)
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while (position := patched.find(signature, start)) != -1:
            patched[position + offset] |= 0x1
            start = position + 4
    return bytes(patched)


def _symlink(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.external_attr = 0o120777 << 16
    return info


@pytest.mark.parametrize(
    "entries,mutate,reason",
    [
        ([("model/MLmodel", "x"), ("../evil.txt", "x")], None, "archive_path_unsafe"),
        ([("model/MLmodel", "x"), (_symlink("model/alias"), "MLmodel")], None, "archive_symlink"),
        ([("model/MLmodel", "x")], _encrypt_flag, "archive_encrypted"),
        ([("model/MLmodel", "x"), ("model/MLmodel", "y")], None, "archive_duplicate"),
        ([("model/README.txt", "x")], None, "mlmodel_missing"),
    ],
)
def test_archive_attacks_are_refused_before_extraction(case, entries, mutate, reason):
    pipeline, data = estimator("forest")
    with pytest.warns(UserWarning) if reason == "archive_duplicate" else _nothing():
        archive = _zip(entries, mutate=mutate)
    response = post_import(case, archive, validation(pipeline, data))
    _refused(case, response, 422, "ML_IMPORT_REJECTED", reason)
    assert not (case.tmp / "evil.txt").exists()


class _nothing:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_oversize_uploads_and_zip_bombs_are_refused(case, monkeypatch):
    pipeline, data = estimator("forest")
    monkeypatch.setattr(settings, "ml_import_max_mb", 1)
    stored = io.BytesIO()
    with zipfile.ZipFile(stored, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("model/MLmodel", "x")
        archive.writestr("model/blob.json", np.random.default_rng(0).bytes(2 * 1024 * 1024))
    response = post_import(case, stored.getvalue(), validation(pipeline, data))
    _refused(case, response, 413, "ML_IMPORT_REJECTED", "archive_too_large")
    monkeypatch.setattr(settings, "ml_import_max_mb", 128)
    monkeypatch.setattr(settings, "ml_train_artifact_limit_mb", 1)
    bomb = _zip([("model/MLmodel", "x"), ("model/blob.json", b"\0" * (8 * 1024 * 1024))])
    assert len(bomb) < 100 * 1024
    response = post_import(case, bomb, validation(pipeline, data))
    _refused(case, response, 413, "ML_IMPORT_REJECTED", "archive_too_large")


def test_a_directory_understating_its_sizes_cannot_expand_beyond_them(case, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ml_train_artifact_limit_mb", 1)
    archive = tmp_path / "liar.zip"
    archive.write_bytes(_zip([("model/MLmodel", b"x" * 10), ("model/blob.json", b"\0" * 4096)]))
    real = zipfile.ZipFile.infolist

    def understated(self):
        members = real(self)
        for item in members:
            item.file_size = 1  # The directory claims tiny files.
        return members

    monkeypatch.setattr(zipfile.ZipFile, "infolist", understated)
    with pytest.raises(TabularError) as refused:
        ml_import.extract_archive(archive, tmp_path / "out")
    # zipfile reads no more than the declared size, then the CRC fails.
    assert refused.value.details["reason"] == "archive_invalid"
    blob = tmp_path / "out" / "blob.json"
    assert not blob.exists() or blob.stat().st_size <= 1


@pytest.mark.parametrize("enforced", [True, False])
@pytest.mark.parametrize(
    "role", ["workspace_contributor", "workspace_reviewer", "workspace_viewer"]
)
def test_import_is_admin_only_even_in_report_mode(db_session, case, monkeypatch, enforced, role):
    monkeypatch.setattr(settings, "ml_rbac_enforced", enforced)
    case.member.role_template = role
    db_session.commit()
    pipeline, data, directory = _bundle(case)
    response = post_import(case, zipped(directory), validation(pipeline, data))
    _refused(case, response, 403, "ML_FORBIDDEN_ACTION")
    assert not db_session.query(MLModel).filter_by(workspace_id=case.workspace.id).count()


def test_the_flag_off_refuses_and_is_audited(case, monkeypatch):
    monkeypatch.setattr(settings, "ml_import_enabled", False)
    pipeline, data, directory = _bundle(case)
    response = post_import(case, zipped(directory), validation(pipeline, data))
    _refused(case, response, 409, "ML_IMPORT_DISABLED")


def test_an_import_that_cannot_be_audited_registers_nothing(db_session, case, monkeypatch):
    from app.services.object_store import get_object_store

    real = ml_import.audit_attempt

    def fail_on_accept(db, **kwargs):
        if kwargs["after"].get("verdict") == "accepted":
            raise TabularError(code="ML_AUDIT_UNAVAILABLE", message="down", status_code=503)
        return real(db, **kwargs)

    monkeypatch.setattr(ml_import, "audit_attempt", fail_on_accept)
    pipeline, data, directory = _bundle(case)
    response = post_import(case, zipped(directory), validation(pipeline, data))
    job = case.client.get(f"/ml-models/import/{response.json()['job']['id']}").json()["job"]
    assert job["status"] == "failed" and job["error"] == "ML_AUDIT_UNAVAILABLE"
    assert not db_session.query(MLModel).filter_by(workspace_id=case.workspace.id).count()
    store = get_object_store()
    root = store.key("workspaces", case.workspace.id, "ml")
    assert store.list_keys(root) == []


def test_a_crafted_tree_is_refused_before_any_prediction(case):
    """skops restores out-of-range node indices; predicting would read out of bounds."""
    import skops.io as sio

    pipeline, data, directory = _bundle(case)
    path = directory / "model.skops"
    trusted = sio.get_untrusted_types(file=str(path))
    model = sio.load(str(path), trusted=trusted)
    tree = model.named_steps["model"].estimators_[0].tree_
    state = tree.__getstate__()
    nodes = state["nodes"].copy()
    nodes["left_child"][0] = 10**6
    tree.__setstate__({**state, "nodes": nodes})
    sio.dump(model, str(path))
    response = post_import(case, zipped(directory), validation(pipeline, data))
    job = case.client.get(f"/ml-models/import/{response.json()['job']['id']}").json()["job"]
    assert job["error"] == "ML_IMPORT_VALIDATION_FAILED"
    assert job["result"]["reason"] == "reader_refused"
    assert job["result"]["error_code"] == "ML_IMPORT_TREE_INVALID"


def test_histogram_gradient_boosting_waits_for_its_structural_check(case):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.pipeline import Pipeline

    _, data = estimator("logistic")
    numeric = data[["tenure", "arpu"]]
    pipeline = Pipeline([("m", HistGradientBoostingClassifier(max_iter=5))]).fit(
        numeric, (numeric.tenure < 30).astype(int)
    )
    directory = save(pipeline, numeric, case.tmp / "hgb")
    response = post_import(case, zipped(directory), validation(pipeline, numeric))
    detail = _refused(case, response, 422, "ML_IMPORT_REJECTED", "untrusted_types")
    assert any("TreePredictor" in name for name in detail["types"])
