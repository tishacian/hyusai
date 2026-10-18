"""M4.2 — requalify a model for a new reader runtime, without weakening trust.

Serving refuses a bundle whose recorded producer runtime differs from the
reader's (``validate_model_runtime``), so upgrading scikit-learn, skrub, numpy,
pandas, MLflow or skops in the image would retire every model. This module
replaces "refuse forever" with "requalify, then allow — for this exact
artifact and this exact reader runtime":

1. **Reference predictions.** While the reader still is the producer, the
   model predicts the first ``ML_REFERENCE_ROWS`` rows (by sorted row id) of
   its recorded M2 final test. Only the row ids and the outputs are stored, as
   a bounded gzip JSON object beside the evaluation partition. The rows are
   re-derived from the source dataset, which must still match the recorded
   partition fingerprint; a model without one is refused, never given rows.
2. **Requalification.** Under the current reader, an isolated subprocess loads
   the exact verified bundle with every serving check except runtime equality,
   predicts the same rows through the serving plane's own code, and returns
   the outputs. The parent — not the child — compares them with the reference
   under the tolerances in settings.
3. **Attestation.** Each attempt is a row. Only a qualified, unrevoked one,
   bound to the artifact fingerprint and both runtimes, lets the serving gate
   accept that reader for that artifact.

Scope: families served in the API process (``tabular``). Remote families and
clustering (no recorded final test) are refused with their reason. The reader
is whoever executes the job, so a remote runtime could later run the same job
on its own queue.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import get_logger
from app.models.ml_requalification import MLRuntimeAttestation
from app.models.tabular import MLModel, TabularDataset
from app.models.workspace_job import WorkspaceJob
from app.resources.ml_artifact_contract import CONTRACT_VERSION, PROFILES, runtime_versions
from app.services.ml.artifacts import artifact_fingerprint, runtime_digest
from app.services.mlops_jobs import operational_job_id
from app.services.tabular_datasets import TabularError

logger = get_logger(__name__)

CAPTURE = "ml_reference_capture"
REQUALIFY = "ml_requalification"
KINDS = frozenset({CAPTURE, REQUALIFY})
TASK = "agentium.ml_runtime_requalification"
SCHEMA = 1
FORMAT = "agentium-runtime-reference-v1"
SUPPORTED_FAMILIES = frozenset({"tabular", "external"})
# Where a reference's rows come from: re-derived from the recorded final test
# (tabular), or stored with the reference because an imported model has no
# source dataset (M4.3). Only the latter keeps input rows, bounded.
FINAL_TEST = "final_test"
IMPORT_VALIDATION = "import_validation"
SUPPORTED_TASKS = frozenset({"classification", "regression"})
SYSTEM = "system:training"
OPERATOR = "operator-cli"
_HEX = re.compile(r"[0-9a-f]{64}")
_CODE = re.compile(r"ML_[A-Z0-9_]{2,60}")
_REASONS = {
    "remote_family": "Models of this family load in their own runtime; this version requalifies families served by the API only.",
    "no_evaluation_partition": "Clustering models record no final-test partition to replay.",
    "family_unsupported": "This model family cannot be requalified.",
    "task_unsupported": "This task cannot be requalified.",
    "legacy_artifact": "This artifact has no versioned producer contract to requalify.",
    "format_unsupported": "This artifact format cannot be requalified.",
    "reader_incomplete": "This reader lacks a package the artifact's runtime records.",
}


def _refuse(code: str, message: str, *, status: int = 409, **details) -> None:
    raise TabularError(code=code, message=message, status_code=status, details=details or None)


def _unavailable(reason: str) -> None:
    _refuse(
        "ML_REFERENCE_SOURCE_UNAVAILABLE",
        "The model's recorded final test cannot be re-derived from its source dataset. Retrain it to requalify it later.",
        reason=reason,
        action="retrain",
    )


def _artifact(model) -> dict:
    artifact = (getattr(model, "metrics_json", None) or {}).get("artifact")
    return artifact if isinstance(artifact, dict) else {}


def _family(model) -> str:
    return getattr(model, "family", None) or "tabular"


def reader_runtime(model) -> dict:
    """What this process would record as the reader of this model."""
    return runtime_versions(_family(model), _artifact(model).get("serialization"))


def support(model) -> str | None:
    """``None`` when requalification applies to this model, else why not."""
    from app.services.ml.families import get_family

    family = _family(model)
    try:
        definition = get_family(family)
    except Exception:  # noqa: BLE001 - an unknown family is simply unsupported
        return "family_unsupported"
    if definition.serving != "in_process":
        return "remote_family"
    if family == "clustering":
        return "no_evaluation_partition"
    if family not in SUPPORTED_FAMILIES:
        return "family_unsupported"
    if model.task not in SUPPORTED_TASKS:
        return "task_unsupported"
    artifact = _artifact(model)
    if artifact.get("contract_version") != CONTRACT_VERSION or not isinstance(
        artifact.get("runtime"), dict
    ):
        return "legacy_artifact"
    if (family, artifact.get("serialization")) not in PROFILES:
        return "format_unsupported"
    return None


def require_support(model) -> None:
    reason = support(model)
    if reason:
        _refuse(
            "ML_REQUALIFICATION_UNSUPPORTED",
            _REASONS[reason],
            reason=reason,
            action="retrain",
        )
    if model.status != "ready":
        _refuse("ML_MODEL_NOT_READY", "The model is not ready.", status=409)


# ---------------------------------------------------------------------------
# Attestations as the serving gate reads them
# ---------------------------------------------------------------------------


def _active(db, model):
    artifact = _artifact(model)
    return db.query(MLRuntimeAttestation).filter(
        MLRuntimeAttestation.model_id == model.id,
        MLRuntimeAttestation.workspace_id == model.workspace_id,
        MLRuntimeAttestation.artifact_fingerprint == artifact_fingerprint(artifact),
        MLRuntimeAttestation.verdict == "qualified",
        MLRuntimeAttestation.revoked_at.is_(None),
    )


def attested_runtimes(db, model) -> list[dict]:
    """Active qualified attestations for this row's current artifact.

    Passed to ``verify_model_bundle``/``require_artifact_runtime``, which
    re-check every binding; the ids also enter the serving cache key so a
    revocation evicts a resident pipeline on its next request.
    """
    if db is None or not getattr(model, "id", None) or not _artifact(model):
        return []
    rows = _active(db, model).order_by(MLRuntimeAttestation.created_at, MLRuntimeAttestation.id)
    return [
        {
            "id": row.id,
            "artifact_fingerprint": row.artifact_fingerprint,
            "producer_runtime": row.producer_runtime,
            "reader_runtime": row.reader_runtime,
        }
        for row in rows.all()
    ]


# ---------------------------------------------------------------------------
# The reference object
# ---------------------------------------------------------------------------


def reference_key(workspace_id: str, model_id: str, sha256: str) -> str:
    """Content-addressed, beside the evaluation partition.

    A concurrent capture never overwrites the bytes another one committed.
    """
    from app.services.object_store import get_object_store

    return get_object_store().key(
        "workspaces",
        workspace_id,
        "ml",
        "models",
        model_id,
        "report",
        f"runtime-reference-{sha256[:24]}.json.gz",
    )


def reference_summary(model) -> dict | None:
    """The stored reference's metadata, only while bound to this exact artifact."""
    metrics = getattr(model, "metrics_json", None) or {}
    summary = metrics.get("runtime_reference")
    artifact = _artifact(model)
    if (
        not isinstance(summary, dict)
        or summary.get("status") != "stored"
        or summary.get("schema") != SCHEMA
        or not isinstance(summary.get("sha256"), str)
        or not _HEX.fullmatch(summary["sha256"])
        or summary.get("key") != reference_key(model.workspace_id, model.id, summary["sha256"])
        or not artifact
        or summary.get("artifact_fingerprint") != artifact_fingerprint(artifact)
        or summary.get("producer_runtime") != artifact.get("runtime")
        or summary.get("partition_sha256") != (metrics.get("evaluation") or {}).get("sha256")
        or summary.get("source", FINAL_TEST) not in {FINAL_TEST, IMPORT_VALIDATION}
        or (summary.get("source") == IMPORT_VALIDATION) != (_family(model) == "external")
    ):
        return None
    return summary


def _public_reference(summary: dict | None) -> dict:
    if summary is None:
        return {"status": "missing"}
    return {
        "status": "stored",
        "source": summary.get("source", FINAL_TEST),
        "rows": summary.get("rows"),
        "sha256": summary.get("sha256"),
        "captured_at": summary.get("captured_at"),
        "captured_by": summary.get("captured_by"),
    }


def _labels(value, rows, *, kind=str):
    if not isinstance(value, list) or len(value) != rows:
        raise ValueError("label count")
    for item in value:
        if kind is int:
            if type(item) is not int:
                raise ValueError("cluster label")
        elif not isinstance(item, str) or len(item) > 500:
            raise ValueError("class label")
    return value


def _numbers(value, rows):
    if not isinstance(value, list) or len(value) != rows:
        raise ValueError("value count")
    for item in value:
        if item is not None and (
            isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
        ):
            raise ValueError("value")
    return [float(item) if item is not None else None for item in value]


def validate_outputs(task: str, outputs: Any, rows: int) -> dict:
    """Shape-check outputs from a reference object or the isolated reader."""
    if not isinstance(outputs, dict) or rows < 1:
        raise ValueError("outputs")
    if task == "regression":
        return {"values": _numbers(outputs.get("values"), rows)}
    if task == "clustering":
        return {"labels": _labels(outputs.get("labels"), rows, kind=int)}
    classes = outputs.get("classes")
    if (
        not isinstance(classes, list)
        or not classes
        or len(classes) > 1000
        or len(set(classes)) != len(classes)
        or any(not isinstance(item, str) for item in classes)
    ):
        raise ValueError("classes")
    probabilities = outputs.get("probabilities")
    if probabilities is not None:
        if not isinstance(probabilities, list) or len(probabilities) != rows:
            raise ValueError("probability rows")
        probabilities = [_numbers(row, len(classes)) for row in probabilities]
    return {
        "classes": classes,
        "labels": _labels(outputs.get("labels"), rows),
        "probabilities": probabilities,
    }


def encode_reference(payload: dict) -> bytes:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    encoded = gzip.compress(raw, mtime=0)
    if max(len(raw), len(encoded)) > int(settings.ml_reference_max_bytes):
        _refuse(
            "ML_REFERENCE_TOO_LARGE",
            "The reference predictions exceed their byte ceiling.",
            action="lower_reference_rows",
        )
    return encoded


def decode_reference(encoded: bytes, *, sha256: str) -> dict:
    """Bounded, digest-checked JSON; never pickle."""
    limit = int(settings.ml_reference_max_bytes)
    if len(encoded) > limit or hashlib.sha256(encoded).hexdigest() != sha256:
        raise ValueError("reference digest/size mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(encoded)) as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("reference expands beyond its ceiling")
    payload = json.loads(raw)
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != SCHEMA
        or payload.get("format") != FORMAT
    ):
        raise ValueError("unsupported reference schema")
    ids = payload.get("row_ids")
    if (
        not isinstance(ids, list)
        or not ids
        or len(set(ids)) != len(ids)
        or any(not isinstance(key, str) or not _HEX.fullmatch(key) for key in ids)
    ):
        raise ValueError("reference row ids")
    payload["outputs"] = validate_outputs(payload.get("task"), payload.get("outputs"), len(ids))
    if payload.get("source", FINAL_TEST) == IMPORT_VALIDATION:
        rows = payload.get("rows")
        if (
            not isinstance(rows, list)
            or len(rows) != len(ids)
            or len(rows) > int(settings.ml_import_max_validation_rows)
            or any(
                not isinstance(row, dict) or row_digest(row) != key for row, key in zip(rows, ids)
            )
        ):
            raise ValueError("stored reference rows")
    elif "rows" in payload:
        raise ValueError("a final-test reference never stores rows")
    return payload


def row_digest(row: dict) -> str:
    """Content identity of a stored validation row (import references)."""
    return hashlib.sha256(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def read_reference(model, summary: dict) -> dict:
    from app.services.object_store import get_object_store

    try:
        with tempfile.TemporaryDirectory(prefix="ml-reference-") as folder:
            local = get_object_store().copy_to_local(
                summary["key"],
                Path(folder) / "reference.gz",
                max_bytes=int(settings.ml_reference_max_bytes),
            )
            payload = decode_reference(local.read_bytes(), sha256=summary["sha256"])
        artifact = _artifact(model)
        if (
            payload.get("model_id") != model.id
            or payload.get("workspace_id") != model.workspace_id
            or payload.get("version") != model.version
            or payload.get("task") != model.task
            or payload.get("artifact_fingerprint") != artifact_fingerprint(artifact)
            or payload.get("producer_runtime") != artifact.get("runtime")
            or payload.get("partition_sha256") != summary.get("partition_sha256")
            or len(payload["row_ids"]) != summary.get("rows")
        ):
            raise ValueError("reference binding")
        return payload
    except (KeyError, ValueError, OSError):
        _refuse(
            "ML_REFERENCE_INVALID",
            "The stored reference predictions are unreadable or no longer bound to this artifact.",
            action="retrain",
        )


# ---------------------------------------------------------------------------
# Reference rows: re-derived from the recorded final test, never copied
# ---------------------------------------------------------------------------


def _plain(value):
    """A dataset cell as the JSON value a serving caller would send."""
    import numpy as np
    import pandas as pd

    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def reference_rows(db, model, *, wanted: list[str] | None = None):
    """Rows of the recorded final test, by sorted row id, as serving inputs.

    Reuses the M2 partition verification: the source dataset must be the same
    id and version, and its usable rows must reproduce the recorded partition
    fingerprint. A row id is a content hash of every partition column, so a
    row found by id is the row that was captured.
    """
    from app.resources.ml_evaluation import row_ids
    from app.services.ml_retraining_data import partition_for, read_source
    from app.services.tabular_predict import contract_fields

    evaluation = (model.metrics_json or {}).get("evaluation") or {}
    if evaluation.get("status") != "stored":
        _unavailable("partition_missing")
    dataset = (
        db.query(TabularDataset)
        .filter_by(id=model.dataset_id, workspace_id=model.workspace_id)
        .first()
        if model.dataset_id
        else None
    )
    if dataset is None:
        _unavailable("dataset_missing")
    try:
        names = [str(field["name"]) for field in contract_fields(model)]
    except TabularError:
        _unavailable("contract_missing")
    columns = sorted(set(evaluation.get("columns") or [*(model.features or []), model.target]))
    if not set(names) <= set(columns):
        _unavailable("contract_outside_partition")
    budget = (
        int(settings.ml_reference_source_max_rows),
        int(settings.ml_reference_source_max_bytes),
    )
    try:
        frame = read_source(dataset, columns, budget=budget)
        partition, usable = partition_for(model, dataset, frame, max_bytes=budget[1])
    except TabularError as exc:
        _unavailable(
            "source_too_large" if exc.code == "ML_RETRAIN_SOURCE_TOO_LARGE" else "source_changed"
        )
    identities = row_ids(usable, partition["columns"])
    clean = set(partition["test_ids"]) - set(partition["train_ids"])
    if wanted is None:
        chosen = sorted(clean)[: int(settings.ml_reference_rows)]
    else:
        chosen = list(wanted)
        if not set(chosen) <= clean:
            _unavailable("reference_rows_missing")
    if not chosen:
        _unavailable("no_final_test_rows")
    selected = set(chosen)
    first: dict[str, int] = {}
    for position, key in enumerate(identities):
        if key in selected and key not in first:
            first[key] = position
    if len(first) != len(selected):
        _unavailable("reference_rows_missing")
    records = usable.iloc[[first[key] for key in chosen]][names]
    rows = [
        {name: _plain(value) for name, value in zip(names, values, strict=True)}
        for values in records.itertuples(index=False, name=None)
    ]
    return chosen, rows, {"id": dataset.id, "version": dataset.version}


# ---------------------------------------------------------------------------
# The isolated reader
# ---------------------------------------------------------------------------


def _snapshot(model) -> dict:
    return {
        "id": model.id,
        "workspace_id": model.workspace_id,
        "slug": model.slug,
        "version": model.version,
        "task": model.task,
        "target": model.target,
        "family": _family(model),
        "model_uri": model.model_uri,
        "signature_json": model.signature_json or {},
        "classes_json": model.classes_json or [],
        # The registry's producer anchor, never a manifest found in the bundle.
        "metrics_json": {
            "target": (model.metrics_json or {}).get("target") or {},
            "artifact": _artifact(model),
        },
    }


def _child_environment(scratch: Path) -> dict[str, str]:
    """No database, object store or provider credential reaches the child."""
    backend = Path(__file__).resolve().parents[2]
    threads = str(int(settings.ml_train_threads))
    return {
        "PYTHONPATH": str(backend),
        "OMP_NUM_THREADS": threads,
        "OPENBLAS_NUM_THREADS": threads,
        "MKL_NUM_THREADS": threads,
        "ML_PREDICT_ENABLED": "true",
        "ML_PREDICT_MAX_ROWS": str(int(settings.ml_predict_max_rows)),
        # Keep MLflow from discovering an ambient tracking store.
        "MLFLOW_TRACKING_URI": str(scratch / "mlruns"),
    }


def replay(model, rows: list[dict], *, mode: str, bundle: Path | None = None) -> dict:
    """Predict the reference rows in a killable, credential-free subprocess.

    The parent downloads the bundle through the authorized inventory and
    checks its hashes; the child re-verifies right before loading. Child
    refusals come back as codes only. An import (M4.3) hands over the bundle
    it just extracted instead: there is nothing stored to download yet.
    """
    from app.services.ml.artifacts import validate_inventory, verify_bundle
    from app.services.recipe_executions import supervise_harness
    from app.services.tabular_ml import download_model_dir

    artifact = _artifact(model)
    budget = int(settings.ml_train_artifact_limit_mb) * 1024 * 1024
    output_limit = 4 * int(settings.ml_reference_max_bytes)
    timeout_s = float(settings.ml_requalify_timeout_s)
    harness = Path(__file__).resolve().parents[1] / "resources" / "ml_requalify_harness.py"
    with tempfile.TemporaryDirectory(prefix="ml-requalify-") as directory:
        scratch = Path(directory)
        validate_inventory(artifact, max_bytes=budget)
        if bundle is None:
            bundle = scratch / "artifact"
            download_model_dir(model, bundle)
        verify_bundle(bundle, artifact, max_bytes=budget)
        manifest, output = scratch / "input.json", scratch / "result.json"
        manifest.write_text(
            json.dumps(
                {
                    "mode": mode,
                    "parent_pid": os.getpid(),
                    "bundle": str(bundle),
                    "model": _snapshot(model),
                    "rows": rows,
                    "max_artifact_bytes": budget,
                },
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        outcome = supervise_harness(
            [sys.executable, str(harness), str(manifest), str(output)],
            venv_python=Path(sys.executable),
            scratch=scratch,
            timeout_s=timeout_s,
            memory_limit_mb=int(settings.ml_requalify_memory_limit_mb),
            cpu_limit_s=int(timeout_s) + 5,
            fsize_limit_mb=max(64, output_limit // (1024 * 1024) + 1),
            extra_env=_child_environment(scratch),
            timeout_error="ML_REQUALIFICATION_TIMEOUT",
        )
        if outcome.status == "timed_out":
            _refuse("ML_REQUALIFICATION_TIMEOUT", "The isolated reader exceeded its time budget.")
        if not output.is_file() or output.stat().st_size > output_limit:
            _refuse("ML_REQUALIFICATION_HARNESS_FAILED", "The isolated reader returned no result.")
        try:
            value = json.loads(output.read_text(encoding="utf-8"))
        except ValueError:
            value = None
        if not isinstance(value, dict):
            _refuse("ML_REQUALIFICATION_HARNESS_FAILED", "The isolated reader returned no result.")
        if outcome.exit_code != 0:
            code = (value.get("error") or {}).get("code") if outcome.exit_code == 3 else None
            if not isinstance(code, str) or not _CODE.fullmatch(code):
                code = "ML_REQUALIFICATION_HARNESS_FAILED"
            _refuse(code, "The isolated reader refused or could not load this artifact.")
        reader = value.get("reader_runtime")
        if not isinstance(reader, dict) or any(
            not isinstance(key, str) or not isinstance(item, str) for key, item in reader.items()
        ):
            _refuse(
                "ML_REQUALIFICATION_HARNESS_FAILED", "The isolated reader did not report itself."
            )
        try:
            outputs = validate_outputs(model.task, value.get("outputs"), len(rows))
        except ValueError:
            _refuse(
                "ML_REQUALIFICATION_HARNESS_FAILED",
                "The isolated reader returned malformed outputs.",
            )
        return {
            "reader_runtime": reader,
            "outputs": outputs,
            "load_ms": _measure(value.get("load_ms")),
            "predict_ms": _measure(value.get("predict_ms")),
            "single_row_ms": _measure(value.get("single_row_ms")),
            "estimator": str(value.get("estimator") or "")[:80] or None,
            "model_memory_mb": _measure(value.get("model_memory_mb")),
        }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _measure(value) -> float | None:
    """A child-reported cost, kept only when it is a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def tolerances() -> dict:
    return {
        "max_label_disagreements": int(settings.ml_requalify_max_label_disagreements),
        "proba_atol": float(settings.ml_requalify_proba_atol),
        "regression_atol": float(settings.ml_requalify_regression_atol),
        "regression_rtol": float(settings.ml_requalify_regression_rtol),
    }


def _finite_or_none(value):
    return value if value is not None and math.isfinite(value) else None


def compare(task: str, reference: dict, observed: dict, limits: dict) -> dict:
    """Pure: verdict and measured gaps. Any shape difference fails outright.

    classification — identical labels (up to ``max_label_disagreements``) and
    ``max |Δp| ≤ proba_atol`` over every row and class; regression —
    ``|Δ| ≤ atol + rtol·|ref|`` on every row; clustering — identical labels.
    """
    rows = len(reference.get("labels") or reference.get("values") or [])
    metrics: dict[str, Any] = {"rows": rows}

    def failed(code="ML_REQUALIFICATION_OUTPUT_MISMATCH"):
        return {"verdict": "failed", "error_code": code, "metrics": metrics, "rows_compared": rows}

    if task == "regression":
        expected, actual = reference.get("values") or [], observed.get("values") or []
        if not rows or len(actual) != rows:
            return failed()
        worst_abs, worst_rel, outside = 0.0, 0.0, 0
        for ref, obs in zip(expected, actual, strict=True):
            if ref is None or obs is None:
                outside += ref is not obs
                continue
            gap = abs(obs - ref)
            worst_abs = max(worst_abs, gap)
            if ref:
                worst_rel = max(worst_rel, gap / abs(ref))
            if not gap <= limits["regression_atol"] + limits["regression_rtol"] * abs(ref):
                outside += 1
        metrics.update(
            max_abs_diff=_finite_or_none(worst_abs),
            max_rel_diff=_finite_or_none(worst_rel),
            out_of_tolerance=outside,
        )
        return (
            failed()
            if outside
            else {
                "verdict": "qualified",
                "error_code": None,
                "metrics": metrics,
                "rows_compared": rows,
            }
        )

    expected, actual = reference.get("labels") or [], observed.get("labels") or []
    if not rows or len(actual) != rows:
        return failed()
    disagreements = sum(1 for ref, obs in zip(expected, actual, strict=True) if ref != obs)
    metrics.update(
        label_agreement=(rows - disagreements) / rows,
        label_disagreements=disagreements,
    )
    passed = disagreements <= limits["max_label_disagreements"]
    if task == "classification":
        if observed.get("classes") != reference.get("classes"):
            metrics["class_order_changed"] = True
            return failed("ML_REQUALIFICATION_CLASS_ORDER_CHANGED")
        expected_p, actual_p = reference.get("probabilities"), observed.get("probabilities")
        if expected_p is not None:
            if actual_p is None:
                return failed()
            worst = 0.0
            for ref_row, obs_row in zip(expected_p, actual_p, strict=True):
                for ref, obs in zip(ref_row, obs_row, strict=True):
                    if ref is None or obs is None:
                        worst = math.inf if ref is not obs else worst
                    else:
                        worst = max(worst, abs(obs - ref))
            metrics["max_abs_proba_diff"] = _finite_or_none(worst)
            passed = passed and worst <= limits["proba_atol"]
    if not passed:
        return failed()
    return {"verdict": "qualified", "error_code": None, "metrics": metrics, "rows_compared": rows}


# ---------------------------------------------------------------------------
# Capture, requalify, revoke — the mutations, each audited in its transaction
# ---------------------------------------------------------------------------


def _lock(db, model):
    return (
        db.query(MLModel)
        .filter_by(id=model.id, workspace_id=model.workspace_id)
        .populate_existing()
        .with_for_update()
        .first()
    )


def _reauthorize(db, model, user) -> None:
    """A user-requested job re-checks the requester's current role at commit."""
    if user is None:
        return
    from app.models.workspace import Workspace
    from app.services.ml_permissions import require

    db.refresh(user)
    require(db, "requalify", db.get(Workspace, model.workspace_id, populate_existing=True), user)


def _delete_object(key: str) -> None:
    from app.services.object_store import get_object_store

    try:
        # A content-addressed key names exactly one object, never a folder.
        get_object_store().delete_prefix(key)
    except Exception:  # noqa: BLE001 - an orphaned object is unreferenced, not trusted
        logger.warning("ml_requalification: orphan reference not deleted", key=key)


def capture_reference(db, model, *, actor: str, user=None, job_id: str | None = None) -> dict:
    """Record reference predictions while the reader still is the producer."""
    from app.services.ml_permissions import audit

    require_support(model)
    existing = reference_summary(model)
    if existing is not None:
        return {"action": "already_captured", "reference": _public_reference(existing)}
    if _family(model) == "external":
        # Its reference is the importer's validation set, stored at import.
        _unavailable("import_validation_only")
    artifact = _artifact(model)
    reader = reader_runtime(model)
    if artifact.get("runtime") != reader or "missing" in reader.values():
        _refuse(
            "ML_REFERENCE_PRODUCER_RUNTIME_REQUIRED",
            "Reference predictions can only be captured under the model's producer runtime. Capture before upgrading the image, or retrain.",
            action="retrain",
        )
    fingerprint = artifact_fingerprint(artifact)
    ids, rows, dataset = reference_rows(db, model)
    result = replay(model, rows, mode="capture")
    if result["reader_runtime"] != reader:
        _refuse(
            "ML_REFERENCE_PRODUCER_RUNTIME_REQUIRED",
            "The isolated reader does not run the producer runtime.",
            action="retrain",
        )
    evaluation = (model.metrics_json or {}).get("evaluation") or {}
    captured_at = datetime.utcnow().isoformat()
    payload = {
        "schema": SCHEMA,
        "format": FORMAT,
        "model_id": model.id,
        "workspace_id": model.workspace_id,
        "version": model.version,
        "task": model.task,
        "family": _family(model),
        "artifact_fingerprint": fingerprint,
        "producer_runtime": artifact.get("runtime"),
        "partition_sha256": evaluation.get("sha256"),
        "dataset": dataset,
        "row_ids": ids,
        "outputs": result["outputs"],
        "captured_at": captured_at,
        "captured_by": actor,
    }
    encoded = encode_reference(payload)
    sha256 = hashlib.sha256(encoded).hexdigest()
    key = reference_key(model.workspace_id, model.id, sha256)
    from app.services.object_store import get_object_store

    get_object_store().write_bytes(key, encoded)
    committed = False
    try:
        current = _lock(db, model)
        if (
            current is None
            or current.status != "ready"
            or artifact_fingerprint(_artifact(current)) != fingerprint
            or (current.metrics_json or {}).get("evaluation", {}).get("sha256")
            != evaluation.get("sha256")
        ):
            _refuse("ML_REFERENCE_SOURCE_CHANGED", "The model changed during capture. Try again.")
        concurrent = reference_summary(current)
        if concurrent is not None:
            db.rollback()
            # Identical bytes share the key: never delete what another committed.
            committed = concurrent.get("key") == key
            return {"action": "already_captured", "reference": _public_reference(concurrent)}
        _reauthorize(db, current, user)
        summary = {
            "status": "stored",
            "schema": SCHEMA,
            "key": key,
            "sha256": sha256,
            "bytes": len(encoded),
            "rows": len(ids),
            "task": current.task,
            "artifact_fingerprint": fingerprint,
            "producer_runtime": artifact.get("runtime"),
            "partition_sha256": evaluation.get("sha256"),
            "captured_at": captured_at,
            "captured_by": actor,
        }
        current.metrics_json = {**(current.metrics_json or {}), "runtime_reference": summary}
        audit(
            db,
            action="reference_capture",
            workspace_id=current.workspace_id,
            actor=actor,
            model=current,
            after={
                "sha256": sha256,
                "rows": len(ids),
                "artifact_fingerprint": fingerprint,
                "job_id": job_id,
            },
        )
        db.commit()
        committed = True
        return {"action": "captured", "reference": _public_reference(summary)}
    except BaseException:
        db.rollback()
        raise
    finally:
        if not committed:
            _delete_object(key)


def _public_attestation(row: MLRuntimeAttestation, reader: dict | None = None) -> dict:
    return {
        "id": row.id,
        "verdict": row.verdict,
        "error_code": row.error_code,
        "active": row.verdict == "qualified" and row.revoked_at is None,
        "applies_to_reader": reader is not None and row.reader_runtime == reader,
        "artifact_fingerprint": row.artifact_fingerprint,
        "producer_runtime": row.producer_runtime,
        "reader_runtime": row.reader_runtime,
        "reference_sha256": row.reference_sha256,
        "rows_compared": row.rows_compared,
        "metrics": row.metrics or {},
        "tolerances": row.tolerances or {},
        "actor": row.actor,
        "job_id": row.job_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "revoked_by": row.revoked_by,
    }


# Failures of the attempt itself: recorded as a failed attestation. A refusal
# before any load (no reference, not needed, wrong worker) records nothing.
_ATTEMPT_FAILURES = re.compile(
    r"ML_(ARTIFACT_[A-Z_]+|PREDICT_[A-Z_]+|REQUALIFICATION_(TIMEOUT|HARNESS_FAILED))"
)


def requalify(
    db,
    model,
    *,
    actor: str,
    user=None,
    job_id: str | None = None,
    expected_reader: str | None = None,
) -> dict:
    """Replay the reference under this reader and record the attempt."""
    from app.services.ml_permissions import audit

    require_support(model)
    artifact = _artifact(model)
    recorded = artifact.get("runtime")
    reader = reader_runtime(model)
    digest = runtime_digest(reader)
    if expected_reader is not None and digest != expected_reader:
        _refuse(
            "ML_REQUALIFICATION_READER_CHANGED",
            "The worker that ran this job does not have the reader runtime that requested it. Align the API and worker images, then retry.",
        )
    if "missing" in reader.values():
        _refuse(
            "ML_REQUALIFICATION_UNSUPPORTED",
            _REASONS["reader_incomplete"],
            reason="reader_incomplete",
            action="retrain",
        )
    if recorded == reader:
        _refuse(
            "ML_REQUALIFICATION_NOT_REQUIRED",
            "This reader is the model's producer runtime; nothing to requalify.",
        )
    fingerprint = artifact_fingerprint(artifact)
    existing = _active(db, model).filter(MLRuntimeAttestation.reader_digest == digest).first()
    if existing is not None:
        return {"action": "already_attested", "attestation": _public_attestation(existing, reader)}
    summary = reference_summary(model)
    if summary is None:
        _refuse(
            "ML_REFERENCE_MISSING",
            "This model has no reference predictions captured under its producer runtime. It stays refused under this runtime; retrain it.",
            action="retrain",
        )
    reference = read_reference(model, summary)
    if reference.get("source") == IMPORT_VALIDATION:
        # An imported model has no source dataset: its rows travel with it.
        rows = reference["rows"]
    else:
        _, rows, _ = reference_rows(db, model, wanted=reference["row_ids"])
    limits = tolerances()
    try:
        result = replay(model, rows, mode="requalify")
        if result["reader_runtime"] != reader:
            _refuse(
                "ML_REQUALIFICATION_READER_CHANGED",
                "The isolated reader does not run this worker's runtime.",
            )
        verdict = compare(model.task, reference["outputs"], result["outputs"], limits)
    except TabularError as exc:
        if not _ATTEMPT_FAILURES.fullmatch(exc.code or ""):
            raise
        verdict = {"verdict": "failed", "error_code": exc.code, "metrics": {}, "rows_compared": 0}
    try:
        current = _lock(db, model)
        if (
            current is None
            or current.status != "ready"
            or artifact_fingerprint(_artifact(current)) != fingerprint
            or (reference_summary(current) or {}).get("sha256") != summary["sha256"]
        ):
            _refuse(
                "ML_REFERENCE_SOURCE_CHANGED",
                "The model changed during requalification. Try again.",
            )
        _reauthorize(db, current, user)
        if verdict["verdict"] == "qualified":
            concurrent = (
                _active(db, current).filter(MLRuntimeAttestation.reader_digest == digest).first()
            )
            if concurrent is not None:
                db.rollback()
                return {
                    "action": "already_attested",
                    "attestation": _public_attestation(concurrent, reader),
                }
        row = MLRuntimeAttestation(
            workspace_id=current.workspace_id,
            model_id=current.id,
            artifact_fingerprint=fingerprint,
            producer_runtime=recorded,
            reader_runtime=reader,
            reader_digest=digest,
            reference_sha256=summary["sha256"],
            rows_compared=int(verdict["rows_compared"]),
            metrics=verdict["metrics"],
            tolerances=limits,
            verdict=verdict["verdict"],
            error_code=verdict["error_code"],
            job_id=job_id,
            actor=str(actor)[:64],
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.flush()
        audit(
            db,
            action="requalify",
            workspace_id=current.workspace_id,
            actor=actor,
            model=current,
            after={
                "attestation_id": row.id,
                "verdict": row.verdict,
                "error_code": row.error_code,
                "reader_digest": digest,
                "rows_compared": row.rows_compared,
                "metrics": row.metrics,
                "job_id": job_id,
            },
        )
        db.commit()
    except IntegrityError:
        # The partial unique index lost a race to another qualified attempt.
        db.rollback()
        concurrent = _active(db, model).filter(MLRuntimeAttestation.reader_digest == digest).first()
        if concurrent is None:
            raise
        return {
            "action": "already_attested",
            "attestation": _public_attestation(concurrent, reader),
        }
    except BaseException:
        db.rollback()
        raise
    if row.verdict == "qualified":
        _evict(model.id)
    return {
        "action": "requalified" if row.verdict == "qualified" else "failed",
        "attestation": _public_attestation(row, reader),
    }


def _evict(model_id: str) -> None:
    from app.services.tabular_predict import drop_from_cache

    drop_from_cache(model_id)


def revoke(db, *, model, attestation_id: str, actor: str, user=None) -> dict:
    from app.services.ml_permissions import audit

    try:
        current = _lock(db, model)
        if current is None:
            _refuse("ML_MODEL_NOT_FOUND", "Model not found.", status=404)
        row = (
            db.query(MLRuntimeAttestation)
            .filter_by(id=attestation_id, model_id=current.id, workspace_id=current.workspace_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if row is None:
            _refuse("ML_ATTESTATION_NOT_FOUND", "Attestation not found.", status=404)
        if row.verdict != "qualified":
            _refuse("ML_ATTESTATION_NOT_ACTIVE", "A failed attempt grants nothing to revoke.")
        if row.revoked_at is not None:
            db.rollback()
            return _public_attestation(row, reader_runtime(current))
        _reauthorize(db, current, user)
        row.revoked_at = datetime.utcnow()
        row.revoked_by = str(actor)[:64]
        audit(
            db,
            action="attestation_revoke",
            workspace_id=current.workspace_id,
            actor=actor,
            model=current,
            before={"attestation_id": row.id, "active": True},
            after={"attestation_id": row.id, "active": False, "reader_digest": row.reader_digest},
        )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    # This process forgets now; others miss their cache key on the next call.
    _evict(model.id)
    return _public_attestation(row, reader_runtime(model))


def write_import_reference(model, *, rows: list[dict], outputs: dict, actor: str) -> dict:
    """Store an imported model's validation rows and reader outputs (M4.3).

    No source dataset exists to re-derive rows from, so this variant keeps
    them, bounded by ``ML_IMPORT_MAX_VALIDATION_ROWS``. The outputs are the
    ones this reader just produced: the reference is what the model answered
    under its qualified runtime, like a final-test reference. Identical rows
    are kept once. The caller commits the summary or deletes the object.
    """
    artifact = _artifact(model)
    keep: dict[str, int] = {}
    for position, row in enumerate(rows):
        keep.setdefault(row_digest(row), position)
    positions = sorted(keep.values())
    # Per-row outputs follow the kept rows; the class order is not per row.
    picked = {
        key: [value[index] for index in positions]
        if key in {"labels", "values", "probabilities"} and isinstance(value, list)
        else value
        for key, value in outputs.items()
    }
    captured_at = datetime.utcnow().isoformat()
    payload = {
        "schema": SCHEMA,
        "format": FORMAT,
        "source": IMPORT_VALIDATION,
        "model_id": model.id,
        "workspace_id": model.workspace_id,
        "version": model.version,
        "task": model.task,
        "family": _family(model),
        "artifact_fingerprint": artifact_fingerprint(artifact),
        "producer_runtime": artifact.get("runtime"),
        "partition_sha256": None,
        "dataset": None,
        "row_ids": [row_digest(rows[index]) for index in positions],
        "rows": [rows[index] for index in positions],
        "outputs": picked,
        "captured_at": captured_at,
        "captured_by": actor,
    }
    encoded = encode_reference(payload)
    sha256 = hashlib.sha256(encoded).hexdigest()
    key = reference_key(model.workspace_id, model.id, sha256)
    from app.services.object_store import get_object_store

    get_object_store().write_bytes(key, encoded)
    return {
        "status": "stored",
        "schema": SCHEMA,
        "source": IMPORT_VALIDATION,
        "key": key,
        "sha256": sha256,
        "bytes": len(encoded),
        "rows": len(positions),
        "task": model.task,
        "artifact_fingerprint": artifact_fingerprint(artifact),
        "producer_runtime": artifact.get("runtime"),
        "partition_sha256": None,
        "captured_at": captured_at,
        "captured_by": actor,
    }


def delete_reference(model) -> None:
    """Remove a model's stored reference with its row; never fails the delete.

    Import references hold the importer's rows, so they go on every object
    store backend, not only where model bytes are removed.
    """
    summary = (getattr(model, "metrics_json", None) or {}).get("runtime_reference")
    key = summary.get("key") if isinstance(summary, dict) else None
    if isinstance(key, str) and isinstance(summary.get("sha256"), str):
        if key == reference_key(model.workspace_id, model.id, summary["sha256"]):
            _delete_object(key)


# ---------------------------------------------------------------------------
# Status read model
# ---------------------------------------------------------------------------


def _jobs(db, model) -> dict:
    from app.services.mlops_jobs import operational_job_id as job_id

    fingerprint = artifact_fingerprint(_artifact(model))
    ids = {
        CAPTURE: job_id(CAPTURE, model.workspace_id, model.id, fingerprint),
    }
    if support(model) is None:
        ids[REQUALIFY] = job_id(
            REQUALIFY,
            model.workspace_id,
            model.id,
            fingerprint,
            runtime_digest(reader_runtime(model)),
        )
    rows = {
        row.id: row
        for row in db.query(WorkspaceJob)
        .filter(
            WorkspaceJob.workspace_id == model.workspace_id, WorkspaceJob.id.in_(list(ids.values()))
        )
        .populate_existing()
        .all()
    }
    return {kind: _public_job(rows.get(identifier)) for kind, identifier in ids.items()}


def _public_job(job: WorkspaceJob | None) -> dict | None:
    if job is None:
        return None
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "error": (job.error or "").split(":", 1)[0] or None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "result": {
            key: value
            for key, value in (job.result or {}).items()
            if key in {"action", "verdict", "attestation_id", "rows"}
        },
    }


def _diff(producer: dict | None, reader: dict | None) -> list[dict]:
    if not isinstance(producer, dict) or not isinstance(reader, dict):
        return []
    return [
        {"package": name, "producer": producer.get(name), "reader": reader.get(name)}
        for name in sorted(set(producer) | set(reader))
        if producer.get(name) != reader.get(name)
    ]


def runtime_status(db, model) -> dict:
    """Producer vs reader, reference and attestations; no rows, keys or secrets."""
    reason = support(model)
    artifact = _artifact(model)
    producer = artifact.get("runtime") if isinstance(artifact.get("runtime"), dict) else None
    in_process = reason not in {"remote_family", "family_unsupported"}
    reader = reader_runtime(model) if in_process and artifact.get("serialization") else None
    summary = reference_summary(model) if artifact else None
    attestations: list[dict] = []
    status = "unsupported"
    if artifact and getattr(model, "id", None):
        history = int(settings.ml_requalify_history_limit)
        fingerprint = artifact_fingerprint(artifact)
        active = _active(db, model).order_by(MLRuntimeAttestation.created_at.desc()).all()
        recent = (
            db.query(MLRuntimeAttestation)
            .filter(
                MLRuntimeAttestation.model_id == model.id,
                MLRuntimeAttestation.workspace_id == model.workspace_id,
                MLRuntimeAttestation.artifact_fingerprint == fingerprint,
            )
            .order_by(MLRuntimeAttestation.created_at.desc(), MLRuntimeAttestation.id.desc())
            .limit(history)
            .all()
        )
        seen = {row.id for row in active}
        attestations = [_public_attestation(row, reader) for row in active] + [
            _public_attestation(row, reader) for row in recent if row.id not in seen
        ]
    current = (
        reader is not None
        and producer is not None
        and producer == reader
        and "missing" not in reader.values()
    )
    if current:
        status = "current"
    elif reason is not None:
        status = "unsupported"
    elif any(item["active"] and item["applies_to_reader"] for item in attestations):
        status = "attested"
    elif summary is None:
        status = "reference_missing"
    else:
        status = "requalification_required"
    return {
        "model_id": model.id,
        "version": model.version,
        "status": status,
        "supported": reason is None,
        "reason": reason,
        "producer_runtime": producer,
        "reader_runtime": reader,
        "differences": _diff(producer, reader) if reader is not None else [],
        "reference": _public_reference(summary),
        "can_capture": reason is None
        and current
        and summary is None
        and _family(model) != "external",
        "can_requalify": reason is None
        and not current
        and summary is not None
        and status != "attested",
        "attestations": attestations,
        "jobs": _jobs(db, model) if artifact else {},
        "tolerances": tolerances(),
    }


# ---------------------------------------------------------------------------
# Jobs: idempotent per (model, artifact[, reader]) and dispatched after commit
# ---------------------------------------------------------------------------


def _lease_seconds() -> float:
    return float(settings.ml_requalify_timeout_s) + 120.0


def _job_identity(kind: str, model) -> tuple[str, dict]:
    fingerprint = artifact_fingerprint(_artifact(model))
    data = {"model_id": model.id, "artifact_fingerprint": fingerprint}
    parts = [model.workspace_id, model.id, fingerprint]
    if kind == REQUALIFY:
        data["reader_digest"] = runtime_digest(reader_runtime(model))
        parts.append(data["reader_digest"])
    return operational_job_id(kind, *parts), data


def _upsert_job(
    db, *, kind: str, model, actor: str, user_id: str | None
) -> tuple[WorkspaceJob, bool]:
    """The one job for this key; re-armed when terminal or abandoned."""
    identifier, data = _job_identity(kind, model)
    now = datetime.utcnow()
    job = (
        db.query(WorkspaceJob)
        .filter_by(id=identifier)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if job is not None and job.workspace_id != model.workspace_id:
        _refuse("ML_REQUALIFICATION_JOB_CONFLICT", "Job identity conflict.")
    if job is not None and job.status in {"queued", "running"}:
        age = (now - (job.updated_at or now)).total_seconds()
        stale = age > (30.0 if job.status == "queued" else _lease_seconds())
        if not stale:
            return job, False
    if job is None:
        job = WorkspaceJob(id=identifier, workspace_id=model.workspace_id, kind=kind)
        db.add(job)
    job.title = "Runtime reference capture" if kind == CAPTURE else "Runtime requalification"
    job.status = job.stage = "queued"
    job.progress = 0
    job.error = None
    job.queued_at = job.updated_at = now
    job.started_at = job.completed_at = None
    job.created_by_user_id = user_id
    job.input_ref = {**data, "actor": str(actor)[:64]}
    job.result = {}
    db.flush()
    return job, True


def _dispatch(job_id: str, model) -> None:
    if settings.worker_eager_mode:
        run_job(job_id)
        return
    from app.services.ml.families import get_family
    from app.workers.celery_app import celery_app

    # The reader is whoever executes the job: an in-process family's reader is
    # the image of the general worker that trains it (the API's own image).
    celery_app.send_task(
        TASK, args=[job_id], queue=get_family(_family(model)).train_queue(), retry=False
    )


def request(db, *, kind: str, model, user) -> dict:
    """API entry: synchronous refusals, then one idempotent background job."""
    require_support(model)
    artifact = _artifact(model)
    reader = reader_runtime(model)
    if kind == CAPTURE:
        if reference_summary(model) is not None:
            return {"job": _jobs(db, model).get(CAPTURE), "started": False}
        if _family(model) == "external":
            _unavailable("import_validation_only")
        if artifact.get("runtime") != reader or "missing" in reader.values():
            _refuse(
                "ML_REFERENCE_PRODUCER_RUNTIME_REQUIRED",
                "Reference predictions can only be captured under the model's producer runtime. Capture before upgrading the image, or retrain.",
                action="retrain",
            )
        if ((model.metrics_json or {}).get("evaluation") or {}).get("status") != "stored":
            _unavailable("partition_missing")
    else:
        if artifact.get("runtime") == reader:
            _refuse(
                "ML_REQUALIFICATION_NOT_REQUIRED",
                "This reader is the model's producer runtime; nothing to requalify.",
            )
        if (
            _active(db, model)
            .filter(MLRuntimeAttestation.reader_digest == runtime_digest(reader))
            .first()
        ):
            return {"job": _jobs(db, model).get(REQUALIFY), "started": False}
        if reference_summary(model) is None:
            _refuse(
                "ML_REFERENCE_MISSING",
                "This model has no reference predictions captured under its producer runtime. It stays refused under this runtime; retrain it.",
                action="retrain",
            )
    try:
        job, started = _upsert_job(db, kind=kind, model=model, actor=user.id, user_id=user.id)
        db.commit()
    except IntegrityError:
        # Two first requests raced on the deterministic job id; one job exists.
        db.rollback()
        identifier, _ = _job_identity(kind, model)
        return {"job": _public_job(db.get(WorkspaceJob, identifier)), "started": False}
    if started:
        try:
            _dispatch(job.id, model)
        except Exception:  # noqa: BLE001 - a queued job is re-dispatched by the next request
            logger.warning("ml_requalification: dispatch deferred", job_id=job.id)
    db.expire_all()
    return {"job": _public_job(db.get(WorkspaceJob, job.id)), "started": started}


def capture_after_training(db, model) -> None:
    """Queue a capture for a fit that just became ready. Never fails the fit."""
    if not settings.ml_reference_capture_on_train:
        return
    try:
        if (
            support(model) is not None
            or model.status != "ready"
            or ((model.metrics_json or {}).get("evaluation") or {}).get("status") != "stored"
            or _artifact(model).get("runtime") != reader_runtime(model)
            or reference_summary(model) is not None
        ):
            return
        job, started = _upsert_job(db, kind=CAPTURE, model=model, actor=SYSTEM, user_id=None)
        db.commit()
        if started:
            _dispatch(job.id, model)
    except Exception:  # noqa: BLE001 - the operator CLI can capture it later
        db.rollback()
        logger.warning("ml_requalification: capture after training skipped", model_id=model.id)


def _claim(db, job_id: str, now: datetime, kinds=KINDS) -> WorkspaceJob | None:
    """Compare-and-swap lease on one server-managed job (also used by M4.3)."""
    from datetime import timedelta

    job = (
        db.query(WorkspaceJob)
        .filter(WorkspaceJob.id == job_id, WorkspaceJob.kind.in_(list(kinds)))
        .populate_existing()
        .first()
    )
    if job is None or job.status not in {"queued", "running"}:
        return None
    if job.status == "running" and job.updated_at > now - timedelta(seconds=_lease_seconds()):
        return None
    changed = (
        db.query(WorkspaceJob)
        .filter_by(id=job.id, status=job.status, updated_at=job.updated_at)
        .update(
            {
                "status": "running",
                "stage": "running",
                "started_at": now,
                "updated_at": now,
                "error": None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if not changed:
        return None
    db.refresh(job)
    return job


def run_job(job_id: str) -> dict:
    """Celery entry point; the executing process is the reader."""
    from app.db.base import SessionLocal
    from app.models.user import User

    with SessionLocal() as db:
        job = _claim(db, job_id, datetime.utcnow())
        if job is None:
            return {"status": "not_claimed", "job_id": job_id}
        stamp = job.updated_at
        status, error, result = "completed", None, {}
        try:
            data = dict(job.input_ref or {})
            model = (
                db.query(MLModel)
                .filter_by(id=data.get("model_id"), workspace_id=job.workspace_id)
                .populate_existing()
                .first()
            )
            if model is None or artifact_fingerprint(_artifact(model)) != data.get(
                "artifact_fingerprint"
            ):
                _refuse("ML_REFERENCE_SOURCE_CHANGED", "The model changed since the request.")
            actor = str(data.get("actor") or SYSTEM)
            user = (
                db.get(User, job.created_by_user_id, populate_existing=True)
                if job.created_by_user_id
                else None
            )
            if job.created_by_user_id and user is None:
                _refuse("ML_FORBIDDEN_ACTION", "The requester no longer exists.", status=403)
            _reauthorize(db, model, user)
            if job.kind == CAPTURE:
                outcome = capture_reference(db, model, actor=actor, user=user, job_id=job.id)
                result = {"action": outcome["action"], "rows": outcome["reference"].get("rows")}
            else:
                outcome = requalify(
                    db,
                    model,
                    actor=actor,
                    user=user,
                    job_id=job.id,
                    expected_reader=data.get("reader_digest"),
                )
                attestation = outcome["attestation"]
                result = {
                    "action": outcome["action"],
                    "verdict": attestation["verdict"],
                    "attestation_id": attestation["id"],
                }
                if attestation["verdict"] != "qualified":
                    status = "failed"
                    error = f"{attestation['error_code'] or 'ML_REQUALIFICATION_FAILED'}: reference predictions differ under this runtime"
        except TabularError as exc:
            db.rollback()
            status, error = "failed", f"{exc.code}: {exc.message}"[:500]
        except Exception as exc:  # noqa: BLE001 - the job row is the error channel
            db.rollback()
            logger.exception("ml_requalification: job crashed", job_id=job_id)
            status, error = "failed", f"ML_REQUALIFICATION_HARNESS_FAILED: {type(exc).__name__}"
        now = datetime.utcnow()
        changed = (
            db.query(WorkspaceJob)
            .filter_by(id=job_id, status="running", updated_at=stamp)
            .update(
                {
                    "status": status,
                    "stage": status,
                    "progress": 100 if status == "completed" else 0,
                    "result": result,
                    "error": error,
                    "completed_at": now,
                    "updated_at": now,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return {"status": status if changed else "lease_lost", "job_id": job_id, "error": error}
