"""M4.2 contracts that need no training: tolerances, gate, rights, audit, bounds."""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.ml_requalification import MLRuntimeAttestation
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.resources.ml_artifact_contract import runtime_versions
from app.services import ml_permissions
from app.services import ml_requalification as service
from app.services.ml.artifacts import (
    artifact_fingerprint,
    runtime_digest,
    validate_model_runtime,
    verify_model_bundle,
)
from app.services.tabular_datasets import TabularError

LIMITS = {
    "max_label_disagreements": 0,
    "proba_atol": 1e-6,
    "regression_atol": 1e-9,
    "regression_rtol": 1e-6,
}


def _classification(labels=("a", "b"), probabilities=((0.9, 0.1), (0.2, 0.8))):
    return {
        "classes": ["a", "b"],
        "labels": list(labels),
        "probabilities": [list(row) for row in probabilities],
    }


# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------


def test_classification_qualifies_identical_labels_within_probability_tolerance():
    observed = _classification(probabilities=((0.9 + 4e-7, 0.1 - 4e-7), (0.2, 0.8)))
    result = service.compare("classification", _classification(), observed, LIMITS)
    assert result["verdict"] == "qualified"
    assert result["rows_compared"] == 2
    assert result["metrics"]["label_agreement"] == 1
    assert result["metrics"]["max_abs_proba_diff"] == pytest.approx(4e-7)


@pytest.mark.parametrize(
    "observed,code",
    [
        (_classification(labels=("b", "b")), "ML_REQUALIFICATION_OUTPUT_MISMATCH"),
        (
            _classification(probabilities=((0.9 + 2e-6, 0.1 - 2e-6), (0.2, 0.8))),
            "ML_REQUALIFICATION_OUTPUT_MISMATCH",
        ),
        ({**_classification(), "classes": ["b", "a"]}, "ML_REQUALIFICATION_CLASS_ORDER_CHANGED"),
        ({**_classification(), "probabilities": None}, "ML_REQUALIFICATION_OUTPUT_MISMATCH"),
        ({**_classification(), "labels": ["a"]}, "ML_REQUALIFICATION_OUTPUT_MISMATCH"),
        (
            _classification(probabilities=((None, 0.1), (0.2, 0.8))),
            "ML_REQUALIFICATION_OUTPUT_MISMATCH",
        ),
    ],
)
def test_classification_fails_on_any_label_probability_or_shape_change(observed, code):
    result = service.compare("classification", _classification(), observed, LIMITS)
    assert result["verdict"] == "failed"
    assert result["error_code"] == code


def test_allowed_label_disagreements_is_a_setting_not_a_free_pass():
    observed = _classification(labels=("b", "b"))
    loose = {**LIMITS, "max_label_disagreements": 1}
    assert service.compare("classification", _classification(), observed, loose)["verdict"] == (
        "qualified"
    )
    result = service.compare("classification", _classification(), observed, LIMITS)
    assert result["metrics"]["label_disagreements"] == 1
    assert result["metrics"]["label_agreement"] == 0.5


def test_regression_uses_absolute_plus_relative_tolerance():
    reference = {"values": [0.0, 1000.0, None]}
    inside = {"values": [5e-10, 1000.0 + 9e-4, None]}
    result = service.compare("regression", reference, inside, LIMITS)
    assert result["verdict"] == "qualified"
    assert result["metrics"]["out_of_tolerance"] == 0
    for outside in ([2e-9, 1000.0, None], [0.0, 1000.0 + 2e-3, None], [0.0, 1000.0, 1.0]):
        result = service.compare("regression", reference, {"values": outside}, LIMITS)
        assert result["verdict"] == "failed"
        assert result["metrics"]["out_of_tolerance"] == 1


def test_clustering_labels_must_be_identical():
    reference = {"labels": [0, 1, 1]}
    assert service.compare("clustering", reference, {"labels": [0, 1, 1]}, LIMITS)["verdict"] == (
        "qualified"
    )
    assert service.compare("clustering", reference, {"labels": [0, 1, 0]}, LIMITS)["verdict"] == (
        "failed"
    )


def test_tolerances_come_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "ml_requalify_proba_atol", 1e-4)
    monkeypatch.setattr(settings, "ml_requalify_max_label_disagreements", 2)
    assert service.tolerances()["proba_atol"] == 1e-4
    assert service.tolerances()["max_label_disagreements"] == 2


# ---------------------------------------------------------------------------
# The serving gate
# ---------------------------------------------------------------------------


def _artifact(**runtime):
    return {
        "contract_version": 1,
        "family": "tabular",
        "serialization": "skops",
        "trust_profile": "tabular-skops-v1",
        "runtime": {"python": "3.12", "scikit-learn": "1.9.0", **runtime},
        "trusted_types": [],
        "files": {"MLmodel": "0" * 64},
        "file_sizes": {"MLmodel": 1},
        "total_bytes": 1,
    }


def _attestation(artifact, reader, **overrides):
    return {
        "id": "a1",
        "artifact_fingerprint": artifact_fingerprint(artifact),
        "producer_runtime": artifact["runtime"],
        "reader_runtime": reader,
        **overrides,
    }


def test_gate_accepts_producer_runtime_without_any_attestation():
    artifact = _artifact()
    validate_model_runtime(artifact, dict(artifact["runtime"]))


def test_gate_accepts_only_a_fully_bound_attestation():
    artifact = _artifact()
    reader = {**artifact["runtime"], "scikit-learn": "1.10.0"}
    with pytest.raises(TabularError) as refused:
        validate_model_runtime(artifact, reader)
    assert refused.value.code == "ML_ARTIFACT_RUNTIME_MISMATCH"
    assert refused.value.details["action"] == "requalify_or_retrain"
    validate_model_runtime(artifact, reader, [_attestation(artifact, reader)])
    for wrong in (
        _attestation(artifact, reader, artifact_fingerprint="f" * 64),
        _attestation(artifact, reader, producer_runtime={**artifact["runtime"], "numpy": "1"}),
        _attestation(artifact, {**reader, "pandas": "3.0.0"}),
        "not-a-mapping",
    ):
        with pytest.raises(TabularError) as refused:
            validate_model_runtime(artifact, reader, [wrong])
        assert refused.value.code == "ML_ARTIFACT_RUNTIME_MISMATCH"


def test_gate_never_accepts_a_reader_missing_a_package_even_if_attested():
    artifact = _artifact()
    reader = {**artifact["runtime"], "scikit-learn": "missing"}
    with pytest.raises(TabularError):
        validate_model_runtime(artifact, reader, [_attestation(artifact, reader)])


def test_an_attestation_for_another_artifact_does_not_follow_a_retrain(tmp_path):
    from app.resources.ml_train_harness import _make_pipeline
    from app.tests.services.test_ml_artifact_contract import _data, _export

    frame, y = _data()
    estimator = _make_pipeline("sklearn.ensemble.HistGradientBoostingClassifier", {"max_iter": 2})
    estimator.fit(frame, y)
    root = tmp_path / "model"
    artifact = _export(root, estimator, frame)
    current = runtime_versions("tabular", "skops")
    upgraded = copy.deepcopy(artifact)
    upgraded["runtime"]["scikit-learn"] = "0.0.0"  # recorded by an older producer
    with pytest.raises(TabularError):
        verify_model_bundle(root, upgraded, family="tabular")
    verify_model_bundle(
        root, upgraded, family="tabular", attested=[_attestation(upgraded, current)]
    )
    with pytest.raises(TabularError):
        verify_model_bundle(
            root, upgraded, family="tabular", attested=[_attestation(artifact, current)]
        )


def test_the_relaxed_check_is_reachable_only_from_the_isolated_harness():
    backend = Path(__file__).resolve().parents[3]
    callers = {
        path.relative_to(backend).as_posix()
        for path in (backend / "app").rglob("*.py")
        if "/tests/" not in path.as_posix()
        and re.search(r"\bverify_requalification_candidate\b", path.read_text(encoding="utf-8"))
    }
    assert callers == {
        "app/services/ml/artifacts.py",
        "app/resources/ml_requalify_harness.py",
    }


def test_the_cache_key_carries_active_attestations_and_is_unchanged_without():
    from app.services.tabular_predict import _fingerprint

    model = SimpleNamespace(
        model_uri="m",
        status="ready",
        trained_at=None,
        updated_at=None,
        metrics_json={"artifact": _artifact()},
    )
    plain = _fingerprint(model)
    assert _fingerprint(model, []) == plain
    attested = _fingerprint(model, [{"id": "b"}, {"id": "a"}])
    assert attested != plain
    assert attested == _fingerprint(model, [{"id": "a"}, {"id": "b"}])
    assert _fingerprint(model, [{"id": "a"}]) != attested


# ---------------------------------------------------------------------------
# Rows in the database
# ---------------------------------------------------------------------------


@pytest.fixture()
def case(db_session):
    workspace = Workspace(name="Requalify", slug="requalify-" + uuid4().hex)
    user = User(
        id=str(uuid4()),
        username="rq-" + uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
        is_active=True,
    )
    db_session.add_all([workspace, user])
    db_session.flush()
    member = WorkspaceMember(
        workspace_id=workspace.id, user_id=user.id, role="admin", role_template="workspace_admin"
    )
    artifact = _artifact()
    artifact["runtime"] = runtime_versions("tabular", "skops")
    model = MLModel(
        id=str(uuid4()),
        workspace_id=workspace.id,
        name="Requalify",
        slug="requalify",
        version=1,
        task="classification",
        family="tabular",
        algo="gradient_boosting",
        target="y",
        status="ready",
        metrics_json={"artifact": artifact, "evaluation": {"status": "stored", "sha256": "e" * 64}},
        signature_json={"inputs": [{"name": "x", "type": "double"}]},
        classes_json=["a", "b"],
    )
    db_session.add_all([member, model])
    db_session.commit()
    return SimpleNamespace(workspace=workspace, user=user, member=member, model=model)


def _row(case, *, reader, verdict="qualified", revoked=False, fingerprint=None):
    artifact = case.model.metrics_json["artifact"]
    row = MLRuntimeAttestation(
        workspace_id=case.workspace.id,
        model_id=case.model.id,
        artifact_fingerprint=fingerprint or artifact_fingerprint(artifact),
        producer_runtime=artifact["runtime"],
        reader_runtime=reader,
        reader_digest=runtime_digest(reader),
        reference_sha256="r" * 64,
        rows_compared=3,
        metrics={},
        tolerances=LIMITS,
        verdict=verdict,
        actor="test",
        created_at=datetime.utcnow(),
        revoked_at=datetime.utcnow() if revoked else None,
    )
    return row


def test_only_active_qualified_attestations_of_this_artifact_reach_the_gate(db_session, case):
    reader = {**case.model.metrics_json["artifact"]["runtime"], "scikit-learn": "9.9.9"}
    active = _row(case, reader=reader)
    db_session.add_all(
        [
            active,
            _row(case, reader={**reader, "numpy": "0"}, revoked=True),
            _row(case, reader={**reader, "pandas": "0"}, verdict="failed"),
            _row(case, reader={**reader, "scipy": "0"}, fingerprint="f" * 64),
        ]
    )
    db_session.commit()
    assert [item["id"] for item in service.attested_runtimes(db_session, case.model)] == [active.id]


def test_at_most_one_active_qualified_attestation_per_artifact_and_reader(db_session, case):
    from sqlalchemy.exc import IntegrityError

    reader = {**case.model.metrics_json["artifact"]["runtime"], "scikit-learn": "9.9.9"}
    db_session.add(_row(case, reader=reader))
    db_session.commit()
    # Failed and revoked attempts may accumulate as evidence.
    db_session.add_all(
        [_row(case, reader=reader, verdict="failed"), _row(case, reader=reader, revoked=True)]
    )
    db_session.commit()
    db_session.add(_row(case, reader=reader))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.parametrize(
    "role,allowed",
    [
        ("workspace_viewer", False),
        ("workspace_contributor", False),
        ("workspace_reviewer", False),
        ("workspace_admin", True),
        ("workspace_owner", True),
    ],
)
def test_requalify_is_admin_only_and_strict_even_in_report_mode(
    db_session, case, monkeypatch, role, allowed
):
    monkeypatch.setattr(settings, "ml_rbac_enforced", False)
    case.member.role_template = role
    db_session.commit()
    assert (
        ml_permissions.capabilities(db_session, case.workspace, case.user)["requalify"] is allowed
    )
    if allowed:
        ml_permissions.require(db_session, "requalify", case.workspace, case.user)
    else:
        with pytest.raises(TabularError, match="ML_FORBIDDEN_ACTION"):
            ml_permissions.require(db_session, "requalify", case.workspace, case.user)
        # Report mode never logs this as a would-deny pass.
        assert (
            not db_session.query(AuditLog)
            .filter_by(event_type="ml.model.permission_report")
            .count()
        )


def _failing_audit(monkeypatch):
    def fail(*args, **kwargs):
        raise TabularError(code="ML_AUDIT_UNAVAILABLE", message="down", status_code=503)

    monkeypatch.setattr(ml_permissions, "audit", fail)


def test_a_revocation_that_cannot_be_audited_does_not_happen(db_session, case, monkeypatch):
    reader = {**case.model.metrics_json["artifact"]["runtime"], "scikit-learn": "9.9.9"}
    row = _row(case, reader=reader)
    db_session.add(row)
    db_session.commit()
    _failing_audit(monkeypatch)
    with pytest.raises(TabularError, match="ML_AUDIT_UNAVAILABLE"):
        service.revoke(db_session, model=case.model, attestation_id=row.id, actor="admin")
    db_session.expire_all()
    assert db_session.get(MLRuntimeAttestation, row.id).revoked_at is None


def test_revoking_a_failed_attempt_or_another_models_row_is_refused(db_session, case):
    reader = {**case.model.metrics_json["artifact"]["runtime"], "scikit-learn": "9.9.9"}
    failed = _row(case, reader=reader, verdict="failed")
    db_session.add(failed)
    db_session.commit()
    with pytest.raises(TabularError) as refused:
        service.revoke(db_session, model=case.model, attestation_id=failed.id, actor="a")
    assert refused.value.code == "ML_ATTESTATION_NOT_ACTIVE"
    with pytest.raises(TabularError) as refused:
        service.revoke(db_session, model=case.model, attestation_id=str(uuid4()), actor="a")
    assert refused.value.status_code == 404


def _fake_capture(monkeypatch, case):
    monkeypatch.setattr(
        service, "reference_rows", lambda db, model, wanted=None: (["1" * 64], [{"x": 1.0}], {})
    )
    monkeypatch.setattr(
        service,
        "replay",
        lambda model, rows, mode: {
            "reader_runtime": service.reader_runtime(model),
            "outputs": {"classes": ["a", "b"], "labels": ["a"], "probabilities": [[0.6, 0.4]]},
        },
    )


def test_a_capture_that_cannot_be_audited_records_nothing(db_session, case, monkeypatch, tmp_path):
    from app.services.object_store import get_object_store

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    _fake_capture(monkeypatch, case)
    _failing_audit(monkeypatch)
    with pytest.raises(TabularError, match="ML_AUDIT_UNAVAILABLE"):
        service.capture_reference(db_session, case.model, actor="admin")
    db_session.expire_all()
    model = db_session.get(MLModel, case.model.id)
    assert "runtime_reference" not in model.metrics_json
    prefix = get_object_store().key("workspaces", case.workspace.id, "ml", "models", model.id)
    assert get_object_store().list_keys(prefix) == []


def test_a_requalification_that_cannot_be_audited_leaves_no_attestation(
    db_session, case, monkeypatch, tmp_path
):
    from app.resources import ml_artifact_contract

    monkeypatch.setattr(settings, "object_store_backend", "local")
    monkeypatch.setattr(settings, "object_store_base_path", str(tmp_path / "store"))
    _fake_capture(monkeypatch, case)
    service.capture_reference(db_session, case.model, actor="admin")
    real = ml_artifact_contract.version
    monkeypatch.setattr(
        ml_artifact_contract,
        "version",
        lambda name: "9.9.9" if name == "scikit-learn" else real(name),
    )
    _fake_capture(monkeypatch, case)
    _failing_audit(monkeypatch)
    with pytest.raises(TabularError, match="ML_AUDIT_UNAVAILABLE"):
        service.requalify(db_session, db_session.get(MLModel, case.model.id), actor="admin")
    assert db_session.query(MLRuntimeAttestation).count() == 0


def test_capture_requires_the_producer_runtime(db_session, case, monkeypatch):
    from app.resources import ml_artifact_contract

    real = ml_artifact_contract.version
    monkeypatch.setattr(
        ml_artifact_contract, "version", lambda name: "9.9.9" if name == "numpy" else real(name)
    )
    with pytest.raises(TabularError) as refused:
        service.capture_reference(db_session, case.model, actor="admin")
    assert refused.value.code == "ML_REFERENCE_PRODUCER_RUNTIME_REQUIRED"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"family": "forecasting", "task": "forecasting"}, "remote_family"),
        ({"family": "tabular_deep"}, "remote_family"),
        ({"family": "clustering", "task": "clustering"}, "no_evaluation_partition"),
        ({"metrics_json": {"artifact": {"files": {}}}}, "legacy_artifact"),
    ],
)
def test_unsupported_models_are_refused_with_their_reason(db_session, case, change, reason):
    for key, value in change.items():
        setattr(case.model, key, value)
    assert service.support(case.model) == reason
    with pytest.raises(TabularError) as refused:
        service.require_support(case.model)
    assert refused.value.code == "ML_REQUALIFICATION_UNSUPPORTED"
    assert refused.value.details["reason"] == reason
    state = service.runtime_status(db_session, case.model)
    assert state["supported"] is False and state["reason"] == reason


# ---------------------------------------------------------------------------
# Reference object bounds
# ---------------------------------------------------------------------------


def _payload(rows=2):
    return {
        "schema": service.SCHEMA,
        "format": service.FORMAT,
        "task": "classification",
        "row_ids": [hashlib.sha256(str(index).encode()).hexdigest() for index in range(rows)],
        "outputs": {
            "classes": ["a", "b"],
            "labels": ["a"] * rows,
            "probabilities": [[0.5, 0.5]] * rows,
        },
    }


def test_reference_decoding_checks_digest_size_schema_and_shapes(monkeypatch):
    encoded = service.encode_reference(_payload())
    digest = hashlib.sha256(encoded).hexdigest()
    assert service.decode_reference(encoded, sha256=digest)["row_ids"]
    with pytest.raises(ValueError):
        service.decode_reference(encoded, sha256="0" * 64)
    for mutate in (
        lambda p: p.update(schema=2),
        lambda p: p.update(row_ids=[p["row_ids"][0]] * 2),
        lambda p: p["outputs"].update(labels=["a"]),
        lambda p: p["outputs"].update(probabilities=[[0.5]] * 2),
    ):
        payload = _payload()
        mutate(payload)
        raw = gzip.compress(json.dumps(payload).encode(), mtime=0)
        with pytest.raises(ValueError):
            service.decode_reference(raw, sha256=hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(settings, "ml_reference_max_bytes", 64 * 1024)
    with pytest.raises(TabularError, match="ML_REFERENCE_TOO_LARGE"):
        service.encode_reference(_payload(rows=2000))
    bomb = gzip.compress(b" " * (65 * 1024), mtime=0)
    with pytest.raises(ValueError):
        service.decode_reference(bomb, sha256=hashlib.sha256(bomb).hexdigest())


def test_a_summary_is_bound_to_the_artifact_and_partition_it_was_captured_for(case):
    artifact = case.model.metrics_json["artifact"]
    summary = {
        "status": "stored",
        "schema": service.SCHEMA,
        "sha256": "a" * 64,
        "key": service.reference_key(case.workspace.id, case.model.id, "a" * 64),
        "artifact_fingerprint": artifact_fingerprint(artifact),
        "producer_runtime": artifact["runtime"],
        "partition_sha256": "e" * 64,
        "rows": 1,
    }
    case.model.metrics_json = {**case.model.metrics_json, "runtime_reference": summary}
    assert service.reference_summary(case.model) == summary
    for key, value in (
        ("artifact_fingerprint", "f" * 64),
        ("partition_sha256", "0" * 64),
        ("key", "elsewhere"),
    ):
        case.model.metrics_json = {
            **case.model.metrics_json,
            "runtime_reference": {**summary, key: value},
        }
        assert service.reference_summary(case.model) is None


# ---------------------------------------------------------------------------
# The isolated harness keeps every check but runtime equality
# ---------------------------------------------------------------------------


@pytest.fixture()
def bundle(tmp_path):
    from app.resources.ml_train_harness import _make_pipeline
    from app.tests.services.test_ml_artifact_contract import _data, _export

    frame, y = _data()
    estimator = _make_pipeline("sklearn.ensemble.HistGradientBoostingClassifier", {"max_iter": 2})
    estimator.fit(frame, y)
    root = tmp_path / "model"
    return root, _export(root, estimator, frame)


def _harness_input(root, artifact, mode):
    return {
        "mode": mode,
        "bundle": str(root),
        "max_artifact_bytes": 512 * 1024 * 1024,
        "rows": [{"number": 1.0}],
        "model": {
            "id": "m",
            "workspace_id": "w",
            "slug": "m",
            "version": 1,
            "task": "classification",
            "target": "y",
            "family": "tabular",
            "model_uri": "unused",
            "signature_json": {"inputs": [{"name": "number", "type": "double"}]},
            "classes_json": ["0", "1"],
            "metrics_json": {"artifact": artifact},
        },
    }


@pytest.mark.parametrize("mode", ["capture", "requalify"])
def test_the_harness_refuses_tampered_bytes_before_loading(bundle, monkeypatch, mode):
    from app.resources import ml_requalify_harness
    from app.services import tabular_predict

    root, artifact = bundle
    (root / "MLmodel").write_text("tampered")
    monkeypatch.setattr(
        tabular_predict, "_load_mlflow_model", lambda *_: pytest.fail("must refuse before MLflow")
    )
    with pytest.raises(TabularError) as refused:
        ml_requalify_harness.run(_harness_input(root, artifact, mode))
    assert refused.value.code == "ML_ARTIFACT_TAMPERED"


def test_the_harness_relaxes_runtime_equality_only_in_requalify_mode(bundle, monkeypatch, tmp_path):
    from app.resources import ml_requalify_harness
    from app.services import tabular_predict

    root, original = bundle
    artifact = copy.deepcopy(original)
    artifact["runtime"]["scikit-learn"] = "0.0.0"
    loads = []
    real = tabular_predict._load_mlflow_model
    monkeypatch.setattr(
        tabular_predict, "_load_mlflow_model", lambda path: loads.append(path) or real(path)
    )
    with pytest.raises(TabularError) as refused:
        ml_requalify_harness.run(_harness_input(root, artifact, "capture"))
    assert refused.value.code == "ML_ARTIFACT_RUNTIME_MISMATCH" and not loads
    # Requalification loads the same verified bytes and reports its own reader.
    data = _harness_input(root, artifact, "requalify")
    data["model"]["signature_json"] = {
        "inputs": [
            {"name": "number", "type": "double"},
            {"name": "category", "type": "string"},
            {"name": "text", "type": "string"},
            {"name": "date", "type": "datetime"},
            {"name": "constant", "type": "string"},
        ]
    }
    data["rows"] = [
        {"number": 1.0, "category": "a", "text": "x", "date": "2020-01-02", "constant": "known"}
    ]
    result = ml_requalify_harness.run(data)
    assert loads and result["reader_runtime"] == runtime_versions("tabular", "skops")
    assert result["outputs"]["classes"] == ["0", "1"]
    assert len(result["outputs"]["probabilities"][0]) == 2
    # Untrusted types stay refused under requalification too.
    import yaml

    config = yaml.safe_load((root / "MLmodel").read_text())
    config["flavors"]["sklearn"]["skops_trusted_types"].append("numpy.load")
    (root / "MLmodel").write_text(yaml.safe_dump(config))
    from app.resources.ml_artifact_contract import build_artifact_contract

    widened = build_artifact_contract(
        root,
        family="tabular",
        serialization="skops",
        trusted_types=[*original["trusted_types"], "numpy.load"],
    )
    with pytest.raises(TabularError) as refused:
        ml_requalify_harness.run(_harness_input(root, widened, "requalify"))
    assert refused.value.code == "ML_ARTIFACT_UNTRUSTED_TYPES"


def test_harness_failures_reach_the_parent_as_codes_only(tmp_path, monkeypatch):
    from app.resources import ml_requalify_harness

    source, destination = tmp_path / "in.json", tmp_path / "out.json"
    source.write_text(json.dumps({"mode": "requalify", "bundle": str(tmp_path / "none")}))
    monkeypatch.setattr(ml_requalify_harness, "sys", SimpleNamespace(platform="test"))
    assert ml_requalify_harness.main(source, destination) == 3
    assert json.loads(destination.read_text()) == {"error": {"code": "ML_ARTIFACT_UNLOADABLE"}}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def test_a_running_job_is_leased_and_reclaimed_only_when_abandoned(db_session, case):
    job = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=case.workspace.id,
        kind=service.REQUALIFY,
        status="running",
        stage="running",
        updated_at=datetime.utcnow(),
        input_ref={},
        result={},
    )
    db_session.add(job)
    db_session.commit()
    assert service._claim(db_session, job.id, datetime.utcnow()) is None
    later = datetime.utcnow() + timedelta(seconds=service._lease_seconds() + 1)
    assert service._claim(db_session, job.id, later).status == "running"
    other = WorkspaceJob(
        id=str(uuid4()),
        workspace_id=case.workspace.id,
        kind="ml_shadow",
        status="queued",
        input_ref={},
        result={},
    )
    db_session.add(other)
    db_session.commit()
    assert service._claim(db_session, other.id, datetime.utcnow()) is None


def test_requests_are_idempotent_and_refuse_what_is_not_needed(db_session, case, monkeypatch):
    dispatched = []
    monkeypatch.setattr(service, "_dispatch", lambda job_id, model: dispatched.append(job_id))
    with pytest.raises(TabularError) as refused:
        service.request(db_session, kind=service.REQUALIFY, model=case.model, user=case.user)
    assert refused.value.code == "ML_REQUALIFICATION_NOT_REQUIRED"
    first = service.request(db_session, kind=service.CAPTURE, model=case.model, user=case.user)
    second = service.request(db_session, kind=service.CAPTURE, model=case.model, user=case.user)
    assert first["started"] is True and second["started"] is False
    assert first["job"]["id"] == second["job"]["id"] and dispatched == [first["job"]["id"]]
    job = db_session.get(WorkspaceJob, first["job"]["id"])
    job.status = "failed"
    db_session.commit()
    assert (
        service.request(db_session, kind=service.CAPTURE, model=case.model, user=case.user)[
            "started"
        ]
        is True
    )
    assert db_session.get(WorkspaceJob, first["job"]["id"]).created_by_user_id == case.user.id
