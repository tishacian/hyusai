"""M4.2 with real artifacts: capture, simulated upgrade, requalification, refusals.

A real tiny model is trained through the production harness (eager worker).
The runtime upgrade is simulated, not faked at the gate: the parent's package
metadata reports another scikit-learn version, and the isolated reader child
gets the same report through a ``sitecustomize`` on its PYTHONPATH. Every
other check — hashes, trust profile, skops allowlist, loader — runs for real.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.ml_requalification import MLRuntimeAttestation
from app.models.tabular import MLModel
from app.models.user import User
from app.models.workspace import WorkspaceMember
from app.models.workspace_job import WorkspaceJob
from app.resources import ml_artifact_contract
from app.services import ml_requalification as service
from app.services import tabular_predict
from app.services.tabular_datasets import TabularError, register_frame
from app.tests.services.test_ml_training import _frame, enabled, store, workspace  # noqa: F401

pytest.importorskip("skrub")
pytest.importorskip("mlflow.sklearn")
pl = pytest.importorskip("polars")

UPGRADED = "9.9.9"


@pytest.fixture()
def admin(db_session, workspace):  # noqa: F811
    user = User(
        id=str(uuid4()),
        username="requalify-" + uuid4().hex,
        email=uuid4().hex + "@example.invalid",
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role="admin",
            role_template="workspace_admin",
        )
    )
    db_session.commit()
    return user


@pytest.fixture()
def serving(monkeypatch, enabled, store):  # noqa: F811
    monkeypatch.setattr(settings, "ml_predict_enabled", True)
    monkeypatch.setattr(settings, "ml_registry_enabled", False)
    monkeypatch.setattr(settings, "ml_reference_capture_on_train", True)
    tabular_predict.reset_cache()
    yield
    tabular_predict.reset_cache()


def _train(db, workspace, *, task="classification", target="churn", frame=None):  # noqa: F811
    from app.services.tabular_ml import submit_training

    dataset = register_frame(
        db,
        workspace_id=workspace.id,
        name=f"Churn {uuid4().hex[:6]}",
        frame=frame if frame is not None else _frame(84),
        source="upload",
    )
    db.commit()
    model = submit_training(
        db,
        workspace_id=workspace.id,
        dataset_ref={"dataset_id": dataset.id},
        task=task,
        target=target,
        features=["plan", "region", "tenure_months", "arpu", "support_tickets"]
        if target == "churn"
        else ["plan", "region", "tenure_months", "support_tickets"],
        algo="gradient_boosting",
        knobs={"max_iter": 20},
    )
    db.expire_all()
    model = db.get(MLModel, model.id)
    assert model.status == "ready", model.error
    return model, dataset


def _inputs(db, model):
    """One serving row taken from the reference rows (a real final-test row)."""
    _, rows, _ = service.reference_rows(db, model)
    return rows[:2]


def _upgrade(monkeypatch, tmp_path, *, perturb=False):
    """Report another scikit-learn to this process and to the isolated reader."""
    real = ml_artifact_contract.version

    def upgraded(name):
        return UPGRADED if name == "scikit-learn" else real(name)

    monkeypatch.setattr(ml_artifact_contract, "version", upgraded)
    site = tmp_path / f"site-{uuid4().hex[:6]}"
    site.mkdir()
    lines = [
        "import importlib.metadata as _metadata",
        "_real = _metadata.version",
        f"_metadata.version = lambda name: {UPGRADED!r} if name == 'scikit-learn' else _real(name)",
    ]
    if perturb:
        # A reader whose probabilities drift by 1e-3: a real behavioral change.
        lines += [
            "import sklearn.pipeline as _pipeline",
            "_proba = _pipeline.Pipeline.predict_proba",
            "def _shifted(self, X, **kw):",
            "    p = _proba(self, X, **kw)",
            "    p[:, 0] = p[:, 0] + 1e-3",
            "    p[:, -1] = p[:, -1] - 1e-3",
            "    return p",
            "_pipeline.Pipeline.predict_proba = _shifted",
        ]
    (site / "sitecustomize.py").write_text("\n".join(lines) + "\n")
    environment = service._child_environment

    def child_environment(scratch):
        values = environment(scratch)
        values["PYTHONPATH"] = f"{site}:{values['PYTHONPATH']}"
        return values

    monkeypatch.setattr(service, "_child_environment", child_environment)


def _predict(db, model, rows):
    return tabular_predict.predict_rows(db, model, rows, version=model.version)


def _refusal(call):
    with pytest.raises(TabularError) as refused:
        call()
    return refused.value


def test_a_fit_captures_its_reference_under_the_producer_runtime(db_session, workspace, serving):  # noqa: F811
    model, dataset = _train(db_session, workspace)
    summary = service.reference_summary(model)
    assert summary is not None, model.metrics_json.get("runtime_reference")
    assert summary["captured_by"] == service.SYSTEM
    assert summary["rows"] == min(settings.ml_reference_rows, model.metrics_json["rows"]["test"])
    reference = service.read_reference(model, summary)
    # Only content-addressed row ids and outputs are stored; never the rows.
    assert len(reference["row_ids"]) == summary["rows"]
    assert set(reference) >= {"row_ids", "outputs", "producer_runtime", "artifact_fingerprint"}
    assert "plan" not in json.dumps(reference)
    assert reference["outputs"]["classes"] == model.classes_json
    assert len(reference["outputs"]["probabilities"][0]) == len(model.classes_json)
    audit = db_session.query(AuditLog).filter_by(event_type="ml.model.reference_capture").one()
    assert audit.details["after"]["sha256"] == summary["sha256"]
    state = service.runtime_status(db_session, model)
    assert state["status"] == "current"
    assert state["reference"]["status"] == "stored"
    # The serving path is unchanged while reader == producer.
    assert _predict(db_session, model, _inputs(db_session, model))["rows"] == 2


def test_upgrade_refuses_then_requalification_attests_and_serves(
    db_session, workspace, admin, serving, monkeypatch, tmp_path
):
    model, _ = _train(db_session, workspace)
    rows = _inputs(db_session, model)
    before = _predict(db_session, model, rows)["predictions"]
    tabular_predict.reset_cache()
    _upgrade(monkeypatch, tmp_path)

    refused = _refusal(lambda: _predict(db_session, model, rows))
    assert refused.code == "ML_ARTIFACT_RUNTIME_MISMATCH"
    readiness = tabular_predict.serving_readiness(db_session, model)
    assert readiness["readiness"]["action"] == "requalify"
    state = service.runtime_status(db_session, model)
    assert state["status"] == "requalification_required"
    assert state["differences"] == [
        {
            "package": "scikit-learn",
            "producer": model.metrics_json["artifact"]["runtime"]["scikit-learn"],
            "reader": UPGRADED,
        }
    ]

    outcome = service.request(db_session, kind=service.REQUALIFY, model=model, user=admin)
    assert outcome["started"] is True
    db_session.expire_all()
    job = db_session.get(WorkspaceJob, outcome["job"]["id"])
    assert job.status == "completed", job.error
    attestation = db_session.query(MLRuntimeAttestation).filter_by(model_id=model.id).one()
    assert attestation.verdict == "qualified"
    assert attestation.reader_runtime["scikit-learn"] == UPGRADED
    assert attestation.producer_runtime == model.metrics_json["artifact"]["runtime"]
    assert attestation.rows_compared == service.reference_summary(model)["rows"]
    assert attestation.metrics["label_disagreements"] == 0
    assert attestation.metrics["max_abs_proba_diff"] <= settings.ml_requalify_proba_atol
    assert attestation.actor == admin.id
    assert db_session.query(AuditLog).filter_by(event_type="ml.model.requalify").count() == 1

    model = db_session.get(MLModel, model.id)
    after = _predict(db_session, model, rows)["predictions"]
    assert after == before
    assert service.runtime_status(db_session, model)["status"] == "attested"
    assert tabular_predict.serving_readiness(db_session, model)["callable"] is True

    # Idempotent per (model, artifact, reader runtime): nothing new is started.
    again = service.request(db_session, kind=service.REQUALIFY, model=model, user=admin)
    assert again["started"] is False
    assert db_session.query(MLRuntimeAttestation).filter_by(model_id=model.id).count() == 1

    # Revocation evicts the resident pipeline: the very next call is refused.
    assert tabular_predict.cache_state()["size"] == 1
    service.revoke(db_session, model=model, attestation_id=attestation.id, actor=admin.id, user=admin)
    assert _refusal(lambda: _predict(db_session, model, rows)).code == "ML_ARTIFACT_RUNTIME_MISMATCH"
    assert db_session.query(AuditLog).filter_by(event_type="ml.model.attestation_revoke").count() == 1
    assert service.runtime_status(db_session, model)["status"] == "requalification_required"


def test_revocation_in_another_process_evicts_on_the_next_call(
    db_session, workspace, admin, serving, monkeypatch, tmp_path
):
    """No in-process drop: the cache key alone must change."""
    model, _ = _train(db_session, workspace)
    rows = _inputs(db_session, model)
    _upgrade(monkeypatch, tmp_path)
    service.requalify(db_session, model, actor=admin.id, user=admin)
    model = db_session.get(MLModel, model.id)
    assert _predict(db_session, model, rows)["rows"] == 2
    row = db_session.query(MLRuntimeAttestation).filter_by(model_id=model.id).one()
    row.revoked_at = row.created_at
    row.revoked_by = "elsewhere"
    db_session.commit()
    assert tabular_predict.cache_state()["size"] == 1
    assert _refusal(lambda: _predict(db_session, model, rows)).code == "ML_ARTIFACT_RUNTIME_MISMATCH"


def test_a_perturbed_reader_fails_and_stays_refused(
    db_session, workspace, admin, serving, monkeypatch, tmp_path
):
    model, _ = _train(db_session, workspace)
    rows = _inputs(db_session, model)
    _upgrade(monkeypatch, tmp_path, perturb=True)
    outcome = service.requalify(db_session, model, actor=admin.id, user=admin)
    assert outcome["action"] == "failed"
    attestation = outcome["attestation"]
    assert attestation["verdict"] == "failed"
    assert attestation["error_code"] == "ML_REQUALIFICATION_OUTPUT_MISMATCH"
    assert attestation["metrics"]["max_abs_proba_diff"] == pytest.approx(1e-3, rel=1e-3)
    assert _refusal(lambda: _predict(db_session, model, rows)).code == "ML_ARTIFACT_RUNTIME_MISMATCH"
    state = service.runtime_status(db_session, model)
    assert state["status"] == "requalification_required"
    assert state["attestations"][0]["verdict"] == "failed"


def test_tampered_reference_outputs_fail_and_a_broken_digest_is_invalid(
    db_session, workspace, admin, serving, monkeypatch, tmp_path
):
    from app.services.object_store import get_object_store

    model, _ = _train(db_session, workspace)
    summary = service.reference_summary(model)
    payload = json.loads(gzip.decompress(get_object_store().read_bytes(summary["key"])))
    flipped = {label: other for label, other in zip(payload["outputs"]["classes"], reversed(payload["outputs"]["classes"]), strict=True)}
    payload["outputs"]["labels"][0] = flipped[payload["outputs"]["labels"][0]]
    # A consistently re-hashed reference that disagrees with the model.
    encoded = service.encode_reference(payload)
    sha256 = hashlib.sha256(encoded).hexdigest()
    key = service.reference_key(model.workspace_id, model.id, sha256)
    get_object_store().write_bytes(key, encoded)
    model.metrics_json = {
        **model.metrics_json,
        "runtime_reference": {**summary, "sha256": sha256, "key": key, "bytes": len(encoded)},
    }
    db_session.commit()
    _upgrade(monkeypatch, tmp_path)
    outcome = service.requalify(db_session, model, actor=admin.id, user=admin)
    assert outcome["attestation"]["verdict"] == "failed"
    assert outcome["attestation"]["metrics"]["label_disagreements"] == 1
    assert service.attested_runtimes(db_session, model) == []

    # Bytes that no longer match the recorded digest are refused outright.
    get_object_store().write_bytes(key, encoded[:-1] + bytes([encoded[-1] ^ 1]))
    assert _refusal(lambda: service.requalify(db_session, model, actor=admin.id)).code == "ML_REFERENCE_INVALID"


def test_a_missing_or_changed_dataset_is_an_explicit_refusal(db_session, workspace, serving, monkeypatch):
    monkeypatch.setattr(settings, "ml_reference_capture_on_train", False)
    model, dataset = _train(db_session, workspace)
    assert service.reference_summary(model) is None
    dataset_id = dataset.id
    model.dataset_id = None
    db_session.commit()
    refused = _refusal(lambda: service.capture_reference(db_session, model, actor="test"))
    assert refused.code == "ML_REFERENCE_SOURCE_UNAVAILABLE"
    assert refused.details == {"reason": "dataset_missing", "action": "retrain"}
    # Another version of the same name is not the recorded source.
    model.dataset_id = dataset_id
    db_session.get(type(dataset), dataset_id).version = 2
    db_session.commit()
    refused = _refusal(lambda: service.capture_reference(db_session, model, actor="test"))
    assert refused.code == "ML_REFERENCE_SOURCE_UNAVAILABLE"
    assert refused.details["reason"] == "source_changed"
    assert service.reference_summary(db_session.get(MLModel, model.id)) is None


def test_without_a_reference_an_upgraded_model_stays_refused(
    db_session, workspace, admin, serving, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "ml_reference_capture_on_train", False)
    model, _ = _train(db_session, workspace)
    _upgrade(monkeypatch, tmp_path)
    assert service.runtime_status(db_session, model)["status"] == "reference_missing"
    assert _refusal(
        lambda: service.request(db_session, kind=service.REQUALIFY, model=model, user=admin)
    ).code == "ML_REFERENCE_MISSING"
    # A reference cannot be captured under the new runtime either.
    assert _refusal(
        lambda: service.capture_reference(db_session, model, actor="test")
    ).code == "ML_REFERENCE_PRODUCER_RUNTIME_REQUIRED"
    assert tabular_predict.serving_readiness(db_session, model)["readiness"]["action"] == "retrain"


def test_regression_requalifies_within_tolerance(db_session, workspace, admin, serving, monkeypatch, tmp_path):
    model, _ = _train(db_session, workspace, task="regression", target="arpu")
    reference = service.read_reference(model, service.reference_summary(model))
    assert "values" in reference["outputs"]
    _upgrade(monkeypatch, tmp_path)
    outcome = service.requalify(db_session, model, actor=admin.id, user=admin)
    assert outcome["attestation"]["verdict"] == "qualified", outcome
    assert outcome["attestation"]["metrics"]["out_of_tolerance"] == 0
    assert outcome["attestation"]["metrics"]["max_abs_diff"] <= settings.ml_requalify_regression_atol
    rows = _inputs(db_session, model)
    assert _predict(db_session, db_session.get(MLModel, model.id), rows)["rows"] == 2


def _cli_lines(capsys):
    """The CLI's JSON lines; training logs may share the captured stdout."""
    lines = []
    for text in capsys.readouterr().out.splitlines():
        try:
            value = json.loads(text)
        except ValueError:
            continue
        if isinstance(value, dict) and "model_id" in value:
            lines.append(value)
    return lines


def test_operator_cli_is_idempotent_around_an_upgrade(
    db_session, workspace, serving, monkeypatch, tmp_path, capsys
):
    from app.cli import ml_runtime_requalification as cli

    monkeypatch.setattr(settings, "ml_reference_capture_on_train", False)
    model, _ = _train(db_session, workspace)
    capsys.readouterr()
    args = ["--workspace", workspace.id]
    assert cli.main(["capture", *args, "--dry-run"]) == 0
    assert _cli_lines(capsys)[0]["action"] == "would_capture"
    assert service.reference_summary(db_session.get(MLModel, model.id)) is None
    assert cli.main(["capture", *args, "--apply"]) == 0
    assert _cli_lines(capsys)[0]["action"] == "captured"
    assert cli.main(["capture", *args, "--apply"]) == 0
    assert _cli_lines(capsys)[0]["action"] == "already_captured"

    _upgrade(monkeypatch, tmp_path)
    assert cli.main(["requalify", *args, "--dry-run"]) == 0
    assert _cli_lines(capsys)[0]["action"] == "would_requalify"
    assert cli.main(["requalify", *args, "--apply"]) == 0
    (line,) = _cli_lines(capsys)
    assert line["action"] == "requalified" and line["verdict"] == "qualified"
    assert cli.main(["requalify", *args, "--apply"]) == 0
    assert _cli_lines(capsys)[0]["action"] == "attested"
    db_session.expire_all()
    row = db_session.query(MLRuntimeAttestation).filter_by(model_id=model.id).one()
    assert row.actor == service.OPERATOR
