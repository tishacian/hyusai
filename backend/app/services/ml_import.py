"""M4.3 — import an external model, safe formats only.

Accepted: a zipped MLflow model directory with the ``sklearn`` flavor,
``serialization_format: skops``, ``loader_module: mlflow.sklearn``, no code
path, no ``python_model``, and a column-based signature. Everything that can
run code while loading — pickle, cloudpickle, joblib, custom pyfunc, code
paths, other flavors — is refused with its reason. Those formats need an
isolated serving pool (deferred as M4.3b), not this in-process plane.

The upload is checked synchronously (archive, MLmodel, signature, skops types,
validation shape) so a wrong file is refused at once. Then a background job,
executed by the reader that will serve the model, predicts the importer's
validation rows in the M4.2 isolated harness and compares them with the
importer's expected outputs and the serving budgets. Only then is a version
registered, with an artifact contract whose runtime is that reader, and the
validation set becomes its M4.2 reference. Every attempt is audited; the
audit of an accepted import shares its transaction.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logging import get_logger
from app.models.tabular import MLModel
from app.models.workspace_job import WorkspaceJob
from app.resources.ml_artifact_contract import (
    MAX_BUNDLE_FILES,
    build_artifact_contract,
    runtime_versions,
    safe_relative,
)
from app.resources.ml_classification_extensions import label_name
from app.services.ml.artifacts import runtime_digest
from app.services.tabular_datasets import TabularError, slugify

logger = get_logger(__name__)

KIND = "ml_model_import"
TASK = "agentium.ml_model_import"
FAMILY = "external"
SERIALIZATION = "skops"
TASKS = frozenset({"classification", "regression"})
MODEL_FILE = "model.skops"
# MLflow writes these beside the estimator; nothing else may travel with it.
_METADATA_FILES = frozenset(
    {
        "MLmodel",
        "conda.yaml",
        "python_env.yaml",
        "requirements.txt",
        "input_example.json",
        "serving_input_example.json",
        "registered_model_meta",
    }
)
# A file that betrays a format this lot refuses names the precise reason.
_FORBIDDEN_SUFFIXES = {
    ".pkl": "pickle_serialization",
    ".pickle": "pickle_serialization",
    ".joblib": "joblib_serialization",
    ".cloudpickle": "cloudpickle_serialization",
    ".py": "code_paths",
    ".pyc": "code_paths",
    ".so": "native_library",
    ".dylib": "native_library",
    ".dll": "native_library",
}
_SIGNATURE_TYPES = frozenset(
    {"double", "float", "long", "integer", "boolean", "string", "datetime"}
)
_NUMERIC_TYPES = frozenset({"double", "float", "long", "integer"})
_MAX_CHOICES = 12
_CODE = re.compile(r"ML_[A-Z0-9_]{2,60}")


def _reject(reason: str, message: str, *, status: int = 422, **details) -> None:
    raise TabularError(
        code="ML_IMPORT_REJECTED",
        message=message,
        status_code=status,
        details={"reason": reason, **details},
    )


def _invalid_validation(reason: str, message: str, **details) -> None:
    raise TabularError(
        code="ML_IMPORT_VALIDATION_INVALID",
        message=message,
        status_code=422,
        details={"reason": reason, **details},
    )


def _artifact_budget() -> int:
    return int(settings.ml_train_artifact_limit_mb) * 1024 * 1024


# ---------------------------------------------------------------------------
# Archive: bounded, link-free, unencrypted, extracted by streaming
# ---------------------------------------------------------------------------


def extract_archive(path: Path, destination: Path) -> Path:
    """Expand the uploaded zip into ``destination`` and return the bundle root.

    Same posture as the skops archive check: the end record is read before
    ZipFile allocates its directory, every entry is a safe relative path, no
    link, no encryption, no duplicate, and the bytes actually written — not
    the sizes the archive declares — are counted against the artifact budget.
    """
    budget = _artifact_budget()
    try:
        with path.open("rb") as stream:
            end = zipfile._EndRecData(stream)
        if end is None:
            _reject("archive_invalid", "The upload is not a zip archive.")
        if end[zipfile._ECD_ENTRIES_TOTAL] > MAX_BUNDLE_FILES:
            _reject("archive_too_many_entries", "The archive has too many entries.")
        if end[zipfile._ECD_SIZE] > min(budget, 16 * 1024 * 1024):
            _reject("archive_too_large", "The archive directory exceeds the budget.", status=413)
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_BUNDLE_FILES:
                _reject("archive_too_many_entries", "The archive has too many entries.")
            names: set[str] = set()
            declared = 0
            for item in members:
                if item.flag_bits & 0x1:
                    _reject("archive_encrypted", "Encrypted archive entries are refused.")
                if (item.external_attr >> 16) & 0o170000 == 0o120000:
                    _reject("archive_symlink", "Links inside the archive are refused.")
                if item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    _reject("archive_compression", "Only stored or deflated entries are accepted.")
                name = item.filename[:-1] if item.is_dir() else item.filename
                if not safe_relative(name):
                    _reject("archive_path_unsafe", "An archive path escapes the bundle.")
                if name in names:
                    _reject("archive_duplicate", "The archive names an entry twice.")
                names.add(name)
                declared += item.file_size
                if declared > budget:
                    _reject(
                        "archive_too_large", "The expanded archive exceeds the budget.", status=413
                    )
            files = [item for item in members if not item.is_dir()]
            file_names = {item.filename for item in files}
            if "MLmodel" in file_names:
                prefix = ""
            else:
                roots = {name.split("/", 1)[0] for name in file_names}
                prefix = f"{next(iter(roots))}/" if len(roots) == 1 else None
                if prefix is None or f"{prefix}MLmodel" not in file_names:
                    _reject("mlmodel_missing", "The archive holds no MLflow model directory.")
            written = 0
            for item in files:
                if not item.filename.startswith(prefix):
                    _reject("archive_layout", "Files sit outside the MLflow model directory.")
                target = destination / item.filename[len(prefix) :]
                target.parent.mkdir(parents=True, exist_ok=True)
                copied = 0
                with archive.open(item) as source, target.open("xb") as sink:
                    while block := source.read(1024 * 1024):
                        copied += len(block)
                        written += len(block)
                        # A bomb lies about its sizes; the bytes cannot.
                        if copied > item.file_size or written > budget:
                            _reject(
                                "archive_too_large",
                                "The expanded archive exceeds the budget.",
                                status=413,
                            )
                        sink.write(block)
    except (OSError, EOFError, zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError):
        _reject("archive_invalid", "The archive is corrupt or unreadable.")
    return destination


# ---------------------------------------------------------------------------
# Bundle: MLmodel, signature and skops types, read before any load
# ---------------------------------------------------------------------------


def _read_metadata(path: Path) -> str:
    if path.stat().st_size > int(settings.ml_import_max_metadata_bytes):
        _reject("metadata_too_large", f"{path.name} exceeds its size limit.")
    return path.read_text(encoding="utf-8", errors="replace")


def inspect_bundle(root: Path) -> dict:
    """What the bundle declares, refused with a reason unless it is safe to load.

    Nothing here deserializes the estimator: YAML and JSON are inert, and
    skops lists a file's types from its schema without building objects.
    """
    import yaml

    try:
        config = yaml.safe_load(_read_metadata(root / "MLmodel"))
    except yaml.YAMLError:
        config = None
    if not isinstance(config, dict) or not isinstance(config.get("flavors"), dict):
        _reject("mlmodel_invalid", "The MLmodel file is unreadable.")
    flavors = config["flavors"]
    pyfunc = (
        flavors.get("python_function") if isinstance(flavors.get("python_function"), dict) else {}
    )
    if "python_model" in pyfunc or pyfunc.get("loader_module") == "mlflow.pyfunc.model":
        _reject("custom_pyfunc", "Custom pyfunc models run code at load time and are refused.")
    if (
        pyfunc.get("code")
        or "model_code_path" in pyfunc
        or pyfunc.get("loader_module") == "mlflow.pyfunc.loaders.code_model"
        or any(isinstance(flavor, dict) and flavor.get("code") for flavor in flavors.values())
    ):
        _reject("code_paths", "Models shipping code paths are refused.")
    sklearn = flavors.get("sklearn")
    if not isinstance(sklearn, dict) or set(flavors) - {"python_function", "sklearn"}:
        _reject(
            "flavor_unsupported",
            "Only the MLflow sklearn flavor is accepted.",
            flavors=sorted(str(name)[:40] for name in flavors)[:8],
        )
    serialization = sklearn.get("serialization_format")
    if serialization != SERIALIZATION:
        reason = {
            "pickle": "pickle_serialization",
            "cloudpickle": "cloudpickle_serialization",
            "joblib": "joblib_serialization",
        }.get(str(serialization), "serialization_unsupported")
        _reject(reason, "Only skops serialization is accepted; this format runs code at load time.")
    if (
        pyfunc.get("loader_module") != "mlflow.sklearn"
        or pyfunc.get("model_path") != MODEL_FILE
        or sklearn.get("pickled_model") != MODEL_FILE
    ):
        _reject("loader_unsupported", "The MLflow loader does not match the accepted format.")
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            continue
        reason = _FORBIDDEN_SUFFIXES.get(PurePosixPath(relative).suffix.lower())
        if reason:
            _reject(
                reason, "The bundle carries a file this format cannot accept.", file=relative[:120]
            )
        allowed = (
            relative == MODEL_FILE
            or relative in _METADATA_FILES
            or (
                relative.startswith("metadata/") and relative[len("metadata/") :] in _METADATA_FILES
            )
        )
        if not allowed:
            _reject(
                "unexpected_file", "The bundle carries an unexpected file.", file=relative[:120]
            )
    signature = config.get("signature")
    raw_inputs = signature.get("inputs") if isinstance(signature, dict) else None
    if not raw_inputs:
        _reject("signature_missing", "The model needs a column-based MLflow signature.")
    try:
        inputs = json.loads(raw_inputs) if isinstance(raw_inputs, str) else raw_inputs
    except ValueError:
        inputs = None
    if not isinstance(inputs, list) or not inputs:
        _reject("signature_missing", "The model needs a column-based MLflow signature.")
    if any(isinstance(item, dict) and item.get("type") == "tensor" for item in inputs):
        _reject("signature_tensor", "Tensor signatures are refused; declare named columns.")
    names: list[str] = []
    for item in inputs:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name or len(name) > 200 or name in names:
            _reject("signature_unnamed", "Every input column needs a unique name.")
        if item.get("type") not in _SIGNATURE_TYPES:
            _reject(
                "signature_type_unsupported",
                "An input column type cannot be served.",
                column=name[:120],
                type=str(item.get("type"))[:40],
            )
        names.append(name)
    if len(names) > int(settings.ml_train_max_features):
        _reject("signature_too_wide", "The signature declares too many columns.")
    from app.services.ml.artifact_trust import TRUSTED_PROFILES
    from app.services.ml.artifacts import _check_skops_archive

    _check_skops_archive(root / MODEL_FILE, max_bytes=_artifact_budget())
    import skops.io as sio

    actual = set(sio.get_untrusted_types(file=str(root / MODEL_FILE)))
    outside = actual - TRUSTED_PROFILES["external-sklearn-skops-v1"]
    if outside:
        _reject(
            "untrusted_types",
            "The model contains types this reader does not trust, such as custom functions.",
            types=sorted(name[:120] for name in outside)[:16],
        )
    declared = sklearn.get("skops_trusted_types") or []
    if not isinstance(declared, list) or set(declared) != actual:
        _reject(
            "trusted_types_undeclared",
            "MLmodel must declare exactly the skops types the file contains.",
        )
    requirements = []
    if (root / "requirements.txt").is_file():
        requirements = [
            line.strip()[:200]
            for line in _read_metadata(root / "requirements.txt").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ][:64]
    return {
        "inputs": [
            {
                "name": item["name"],
                "type": item["type"],
                "required": item.get("required", True) is not False,
            }
            for item in inputs
        ],
        "trusted_types": sorted(actual),
        "requirements": requirements,
        "mlflow_version": str(config.get("mlflow_version") or "")[:40] or None,
    }


# ---------------------------------------------------------------------------
# Validation set: rows plus the outputs the importer's environment produced
# ---------------------------------------------------------------------------


def parse_validation(raw: bytes, *, task: str, inputs: list[dict]) -> dict:
    """Bounded rows that fit the signature, and expected outputs of that task.

    Format: ``{"rows": [{column: value}], "expected": {...}}`` where
    ``expected`` is ``{"labels": [...], "classes": [...]?, "probabilities":
    [[...]]?}`` for a classifier and ``{"values": [...]}`` for a regressor.
    """
    from app.services.ml_requalification import validate_outputs
    from app.services.tabular_predict import coerce_rows

    if len(raw) > int(settings.ml_import_validation_max_bytes):
        _invalid_validation("too_large", "The validation file exceeds its size limit.")
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        _invalid_validation(
            "format", "The validation file must be JSON with rows and expected outputs."
        )
    rows = payload["rows"]
    minimum = int(settings.ml_import_min_validation_rows)
    maximum = int(settings.ml_import_max_validation_rows)
    if not minimum <= len(rows) <= maximum:
        _invalid_validation(
            "rows_out_of_bounds",
            f"Provide between {minimum} and {maximum} validation rows.",
            rows=len(rows),
            min=minimum,
            max=maximum,
        )
    contract = SimpleNamespace(signature_json={"inputs": inputs})
    coerced = []
    ceiling = max(1, int(settings.ml_predict_max_rows))
    try:
        for offset in range(0, len(rows), ceiling):
            coerced.extend(coerce_rows(contract, rows[offset : offset + ceiling]))
    except TabularError as exc:
        _invalid_validation(
            "rows_do_not_match_signature",
            "A validation row does not match the model signature.",
            error_code=exc.code,
            **{
                key: (exc.details or {}).get(key)
                for key in ("row", "field", "fields")
                if (exc.details or {}).get(key) is not None
            },
        )
    expected = payload.get("expected")
    if not isinstance(expected, dict):
        _invalid_validation("expected_missing", "The expected outputs are missing.")
    try:
        if task == "regression":
            outputs = validate_outputs(task, {"values": expected.get("values")}, len(rows))
        else:
            labels = expected.get("labels")
            if not isinstance(labels, list) or any(
                not isinstance(item, (str, int, float, bool)) for item in labels
            ):
                raise ValueError("labels")
            classes = expected.get("classes")
            if classes is not None and (
                not isinstance(classes, list)
                or any(not isinstance(item, (str, int, float, bool)) for item in classes)
            ):
                raise ValueError("classes")
            normalized = [label_name(item) for item in labels]
            outputs = validate_outputs(
                task,
                {
                    "labels": normalized,
                    "classes": [label_name(item) for item in classes]
                    if classes is not None
                    else sorted(set(normalized)),
                    "probabilities": expected.get("probabilities"),
                },
                len(rows),
            )
            if expected.get("probabilities") is not None and classes is None:
                raise ValueError("probabilities need their class order")
            outputs["declared_classes"] = classes is not None
    except ValueError:
        _invalid_validation(
            "expected_invalid", "The expected outputs do not match the task and the row count."
        )
    return {"rows": coerced, "expected": outputs}


def contract_from(inputs: list[dict], rows: list[dict]) -> list[dict]:
    """The serving contract: signature types, plus hints labelled as such.

    Ranges, defaults and choices are estimated from the importer's validation
    rows only, to prefill the playground; ``hint_source`` says so, and nothing
    statistical (drift, explanations) is derived from them.
    """
    import statistics

    contract = []
    for item in inputs:
        name, declared = item["name"], item["type"]
        values = [row.get(name) for row in rows if row.get(name) is not None]
        field: dict[str, Any] = {
            "name": name,
            "type": declared,
            "required": item["required"],
            "hint_source": "import_validation",
        }
        if declared in _NUMERIC_TYPES:
            numbers = [float(value) for value in values if isinstance(value, (int, float))]
            field["kind"] = "number"
            if numbers:
                field.update(min=min(numbers), max=max(numbers), default=statistics.median(numbers))
        elif declared == "boolean":
            field["kind"] = "category"
            field["choices"] = ["true", "false"]
            field["default"] = label_name(values[0]) if values else None
        elif declared == "datetime":
            field["kind"] = "datetime"
            field["default"] = max(str(value) for value in values) if values else None
        else:
            field["kind"] = "category"
            counts: dict[str, int] = {}
            for value in values:
                counts[str(value)] = counts.get(str(value), 0) + 1
            ranked = sorted(counts, key=lambda key: (-counts[key], key))
            if 0 < len(ranked) <= _MAX_CHOICES:
                field["choices"] = ranked
            field["default"] = ranked[0] if ranked else None
        contract.append(field)
    return contract


def _align(expected: dict, observed: dict) -> dict:
    """Read the importer's probabilities in this estimator's class order."""
    if "classes" not in expected:
        return expected
    aligned = {key: value for key, value in expected.items() if key != "declared_classes"}
    observed_classes = observed.get("classes") or []
    if not expected.get("declared_classes"):
        aligned["classes"] = observed_classes
        return aligned
    if set(aligned["classes"]) == set(observed_classes) and aligned["classes"] != observed_classes:
        order = [aligned["classes"].index(name) for name in observed_classes]
        if aligned.get("probabilities") is not None:
            aligned["probabilities"] = [
                [row[index] for index in order] for row in aligned["probabilities"]
            ]
        aligned["classes"] = list(observed_classes)
    return aligned


# ---------------------------------------------------------------------------
# Request: synchronous checks, staging and one background job
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_lineage(db, *, workspace_id: str, name: str, task: str, lineage_model_id: str | None):
    """A new external lineage, or a new version of an existing external one."""
    if lineage_model_id:
        base = db.query(MLModel).filter_by(id=lineage_model_id, workspace_id=workspace_id).first()
        if base is None:
            raise TabularError(
                code="ML_MODEL_NOT_FOUND",
                message="The model does not exist in this workspace.",
                status_code=404,
            )
        if base.family != FAMILY or base.task != task:
            _reject(
                "lineage_not_external",
                "A new version must extend an imported model of the same task.",
                status=409,
            )
        return base.slug, base.name
    slug = slugify(name, fallback="model")
    if db.query(MLModel.id).filter_by(workspace_id=workspace_id, slug=slug).first():
        _reject(
            "lineage_name_taken",
            "A model already uses this name. Choose another name, or import a new version of an imported model.",
            status=409,
        )
    return slug, name


def audit_attempt(db, *, workspace_id: str, actor: str, after: dict, model=None, ip=None) -> None:
    """``ml.model.import`` for every attempt; flushed in the caller's transaction."""
    from app.services.ml_permissions import audit

    audit(
        db,
        action="import",
        workspace_id=workspace_id,
        actor=actor,
        model=model,
        after=after,
        ip=ip,
    )


def audit_refusal(db, *, workspace_id: str, actor: str, error: TabularError, facts: dict, ip=None):
    """Record a refused attempt after its rollback; the refusal stands either way."""
    db.rollback()
    try:
        audit_attempt(
            db,
            workspace_id=workspace_id,
            actor=actor,
            ip=ip,
            after={
                **facts,
                "verdict": "refused",
                "code": error.code,
                **{
                    key: value
                    for key, value in (error.details or {}).items()
                    if key
                    in {
                        "reason",
                        "error_code",
                        "rows",
                        "min",
                        "max",
                        "types",
                        "file",
                        "metrics",
                        "measurements",
                    }
                },
            },
        )
        db.commit()
    except Exception:  # noqa: BLE001 - an unaudited refusal is logged, never accepted
        db.rollback()
        logger.warning("ml_import: refusal audit unavailable", code=error.code)


def staging_key(workspace_id: str, job_id: str, name: str) -> str:
    from app.services.object_store import get_object_store

    return get_object_store().key("workspaces", workspace_id, "ml", "imports", job_id, name)


def request_import(
    db,
    *,
    workspace,
    user,
    archive: Path,
    validation: bytes,
    task: str,
    target: str,
    name: str,
    lineage_model_id: str | None,
    description: str | None,
    facts: dict,
) -> WorkspaceJob:
    """Check everything that needs no model load, stage the upload, queue it."""
    from app.services.object_store import get_object_store

    if task not in TASKS:
        _reject("task_unsupported", "Only classification and regression models can be imported.")
    if not name or len(name) > 200 or len(target) > 200:
        _reject("name_invalid", "Give the model a name of at most 200 characters.")
    with tempfile.TemporaryDirectory(prefix="ml-import-check-") as folder:
        root = extract_archive(archive, Path(folder) / "bundle")
        inspection = inspect_bundle(root)
    parsed = parse_validation(validation, task=task, inputs=inspection["inputs"])
    slug, _ = resolve_lineage(
        db, workspace_id=workspace.id, name=name, task=task, lineage_model_id=lineage_model_id
    )
    job_id = str(uuid4())
    store = get_object_store()
    archive_key = staging_key(workspace.id, job_id, "archive.zip")
    validation_key = staging_key(workspace.id, job_id, "validation.json")
    store.write_file(archive_key, archive)
    store.write_bytes(validation_key, validation)
    now = datetime.utcnow()
    job = WorkspaceJob(
        id=job_id,
        workspace_id=workspace.id,
        kind=KIND,
        title="Model import",
        status="queued",
        stage="queued",
        queued_at=now,
        updated_at=now,
        created_by_user_id=user.id,
        input_ref={
            "archive_key": archive_key,
            "archive_sha256": facts["archive_sha256"],
            "archive_bytes": facts["archive_bytes"],
            "validation_key": validation_key,
            "validation_sha256": hashlib.sha256(validation).hexdigest(),
            "validation_rows": len(parsed["rows"]),
            "task": task,
            "target": target or "prediction",
            "name": name,
            "slug": slug,
            "description": (description or "")[:2000] or None,
            "lineage_model_id": lineage_model_id,
            "reader_digest": runtime_digest(runtime_versions(FAMILY, SERIALIZATION)),
            "actor": str(user.id)[:64],
            "ip": facts.get("ip"),
        },
        result={},
    )
    db.add(job)
    db.commit()
    return job


def dispatch(job_id: str) -> None:
    if settings.worker_eager_mode:
        run_import_job(job_id)
        return
    from app.services.ml.families import get_family
    from app.workers.celery_app import celery_app

    # The executing worker is the reader whose runtime the contract records.
    celery_app.send_task(TASK, args=[job_id], queue=get_family(FAMILY).train_queue(), retry=False)


def public_job(job: WorkspaceJob) -> dict:
    result = job.result or {}
    return {
        "id": job.id,
        "status": job.status,
        "error": (job.error or "").split(":", 1)[0] or None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "result": {
            key: result.get(key)
            for key in (
                "verdict",
                "model_id",
                "code",
                "reason",
                "error_code",
                "metrics",
                "measurements",
                "budgets",
            )
            if key in result
        },
    }


def _lease_seconds() -> float:
    return float(settings.ml_requalify_timeout_s) + 120.0


def expire_abandoned(db, job: WorkspaceJob) -> WorkspaceJob:
    """A job whose worker vanished is failed and its staged rows removed."""
    if job.status not in {"queued", "running"}:
        return job
    age = (datetime.utcnow() - (job.updated_at or datetime.utcnow())).total_seconds()
    if age <= _lease_seconds():
        return job
    changed = (
        db.query(WorkspaceJob)
        .filter_by(id=job.id, status=job.status, updated_at=job.updated_at)
        .update(
            {
                "status": "failed",
                "stage": "failed",
                "error": "ML_IMPORT_ABANDONED: the validation worker did not finish",
                "result": {"verdict": "refused", "code": "ML_IMPORT_ABANDONED"},
                "completed_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if changed:
        _delete_staging(job)
    db.refresh(job)
    return job


def _delete_staging(job: WorkspaceJob) -> None:
    from app.services.object_store import get_object_store

    data = job.input_ref or {}
    for key in (data.get("archive_key"), data.get("validation_key")):
        if isinstance(key, str) and key == staging_key(
            job.workspace_id, job.id, PurePosixPath(key).name
        ):
            try:
                get_object_store().delete_prefix(key)
            except Exception:  # noqa: BLE001 - logged; the job outcome stands
                logger.warning("ml_import: staging not deleted", job_id=job.id)


# ---------------------------------------------------------------------------
# The job: isolated validation, budgets, registration
# ---------------------------------------------------------------------------


def _budgets() -> dict:
    return {
        "max_load_ms": float(settings.ml_import_max_load_ms),
        "max_predict_ms": float(settings.ml_import_max_predict_ms),
        "max_memory_mb": float(settings.ml_import_max_memory_mb),
    }


def _measurements(result: dict) -> dict:
    return {
        key: result.get(key)
        for key in ("load_ms", "predict_ms", "single_row_ms", "model_memory_mb")
    }


def validate_staged(job: WorkspaceJob, work: Path) -> dict:
    """Re-check the staged upload and replay it in the isolated reader."""
    from app.services import ml_requalification as requalification
    from app.services.ml.artifacts import artifact_fingerprint
    from app.services.object_store import get_object_store

    data = job.input_ref or {}
    store = get_object_store()
    archive = store.copy_to_local(
        data["archive_key"],
        work / "archive.zip",
        max_bytes=int(settings.ml_import_max_mb) * 1024 * 1024,
    )
    validation = store.copy_to_local(
        data["validation_key"],
        work / "validation.json",
        max_bytes=int(settings.ml_import_validation_max_bytes),
    )
    if (
        _sha256(archive) != data["archive_sha256"]
        or _sha256(validation) != data["validation_sha256"]
    ):
        raise TabularError(
            code="ML_IMPORT_SOURCE_CHANGED",
            message="The staged upload changed after it was checked.",
            status_code=409,
        )
    reader = runtime_versions(FAMILY, SERIALIZATION)
    if runtime_digest(reader) != data["reader_digest"]:
        raise TabularError(
            code="ML_IMPORT_READER_CHANGED",
            message="The worker validating this import does not run the reader runtime that will serve it. Align the API and worker images, then retry.",
            status_code=409,
        )
    root = extract_archive(archive, work / "bundle")
    inspection = inspect_bundle(root)
    parsed = parse_validation(
        validation.read_bytes(), task=data["task"], inputs=inspection["inputs"]
    )
    contract = contract_from(inspection["inputs"], parsed["rows"])
    artifact = build_artifact_contract(
        root, family=FAMILY, serialization=SERIALIZATION, trusted_types=inspection["trusted_types"]
    )
    candidate = SimpleNamespace(
        id=str(uuid4()),
        workspace_id=job.workspace_id,
        slug=data["slug"],
        version=0,
        task=data["task"],
        target=data["target"],
        family=FAMILY,
        model_uri=None,
        signature_json={"inputs": contract},
        classes_json=parsed["expected"].get("classes") or [],
        metrics_json={"artifact": artifact},
    )
    try:
        result = requalification.replay(candidate, parsed["rows"], mode="import", bundle=root)
    except TabularError as exc:
        raise TabularError(
            code="ML_IMPORT_VALIDATION_FAILED",
            message="The isolated reader refused or could not run this model.",
            status_code=422,
            details={"reason": "reader_refused", "error_code": exc.code},
        ) from exc
    measurements = _measurements(result)
    expected = _align(parsed["expected"], result["outputs"])
    limits = requalification.tolerances()
    verdict = requalification.compare(data["task"], expected, result["outputs"], limits)
    if verdict["verdict"] != "qualified":
        raise TabularError(
            code="ML_IMPORT_VALIDATION_FAILED",
            message="The model's outputs in this environment differ from the expected outputs.",
            status_code=422,
            details={
                "reason": "outputs_differ",
                "error_code": verdict["error_code"],
                "metrics": verdict["metrics"],
                "measurements": measurements,
            },
        )
    budgets = _budgets()
    for reason, measured, limit in (
        ("load_time", measurements["load_ms"], budgets["max_load_ms"]),
        ("predict_latency", measurements["single_row_ms"], budgets["max_predict_ms"]),
        ("memory", measurements["model_memory_mb"], budgets["max_memory_mb"]),
    ):
        if measured is None or measured > limit:
            raise TabularError(
                code="ML_IMPORT_BUDGET_EXCEEDED",
                message="The model exceeds a serving budget of this platform.",
                status_code=422,
                details={
                    "reason": reason,
                    "metrics": verdict["metrics"],
                    "measurements": measurements,
                    "budgets": budgets,
                },
            )
    return {
        "root": root,
        "inspection": inspection,
        "rows": parsed["rows"],
        "contract": contract,
        "artifact": artifact,
        "fingerprint": artifact_fingerprint(artifact),
        "outputs": result["outputs"],
        "verdict": verdict,
        "tolerances": limits,
        "measurements": measurements,
        "budgets": budgets,
        "estimator": result.get("estimator"),
    }


def register(db, job: WorkspaceJob, validated: dict, *, user) -> MLModel:
    """Create the version, its bytes and its reference; audit in the same transaction."""
    from app.services import ml_requalification as requalification
    from app.services.ml.runtime import runtime_fingerprint
    from app.services.ml_permissions import require
    from app.services.object_store import get_object_store
    from app.services.tabular_ml import (
        _lineage_publication,
        _next_model_version,
        model_prefix,
        upload_model_dir,
    )

    data = job.input_ref or {}
    workspace_id = job.workspace_id
    if user is not None:
        from app.models.workspace import Workspace

        db.refresh(user)
        require(db, "import", db.get(Workspace, workspace_id, populate_existing=True), user)
    slug, _ = resolve_lineage(
        db,
        workspace_id=workspace_id,
        name=data["name"],
        task=data["task"],
        lineage_model_id=data.get("lineage_model_id"),
    )
    if slug != data["slug"]:
        raise TabularError(
            code="ML_IMPORT_SOURCE_CHANGED", message="The lineage changed.", status_code=409
        )
    outputs = validated["outputs"]
    classes = list(outputs.get("classes") or [])
    binary = data["task"] == "classification" and len(classes) == 2
    published_id, published_slug = _lineage_publication(db, workspace_id=workspace_id, slug=slug)
    first = not db.query(MLModel.id).filter_by(workspace_id=workspace_id, slug=slug).first()
    model = MLModel(
        id=str(uuid4()),
        workspace_id=workspace_id,
        name=data["name"],
        slug=slug,
        version=_next_model_version(db, workspace_id=workspace_id, slug=slug),
        description=data.get("description"),
        task=data["task"],
        family=FAMILY,
        algo="external",
        target=data["target"],
        features=[field["name"] for field in validated["contract"]],
        spec_json={},
        params_json={
            "import": {
                "origin": "import",
                "estimator": validated.get("estimator"),
                "archive_sha256": data["archive_sha256"],
                "requirements": validated["inspection"]["requirements"],
                "mlflow_version": validated["inspection"]["mlflow_version"],
                "uploaded_by": data.get("actor"),
                "job_id": job.id,
            }
        },
        status="ready",
        is_champion=first,
        test_size=None,
        cross_validation=0,
        signature_json={
            "inputs": validated["contract"],
            "output": {"task": data["task"], "target": data["target"], "classes": classes},
        },
        input_example_json=validated["rows"][:3],
        classes_json=classes,
        mlflow_model_name=f"{workspace_id[:8]}.{slug}",
        published_skill_id=published_id,
        published_skill_slug=published_slug,
        created_by=data.get("actor"),
        runtime_json=runtime_fingerprint(),
        trained_at=datetime.utcnow(),
        train_duration_ms=None,
    )
    uri, size = upload_model_dir(validated["root"], workspace_id=workspace_id, model_id=model.id)
    model.model_uri, model.artifact_bytes = uri, size
    model.metrics_json = {
        "task": data["task"],
        "artifact": validated["artifact"],
        "target": {
            "name": data["target"],
            "classes": classes,
            "positive": classes[-1] if binary else None,
        },
        "import": {
            "origin": "import",
            "contract_hints": "import_validation",
            "validation": {
                "rows": len(validated["rows"]),
                "metrics": validated["verdict"]["metrics"],
                "tolerances": validated["tolerances"],
                "measurements": validated["measurements"],
                "budgets": validated["budgets"],
            },
        },
    }
    summary = None
    committed = False
    try:
        summary = requalification.write_import_reference(
            model, rows=validated["rows"], outputs=outputs, actor=data.get("actor") or "system"
        )
        model.metrics_json = {**model.metrics_json, "runtime_reference": summary}
        db.add(model)
        db.flush()
        audit_attempt(
            db,
            workspace_id=workspace_id,
            actor=data.get("actor") or "system",
            model=model,
            ip=data.get("ip"),
            after={
                "verdict": "accepted",
                "job_id": job.id,
                "archive_sha256": data["archive_sha256"],
                "archive_bytes": data["archive_bytes"],
                "validation_rows": len(validated["rows"]),
                "artifact_fingerprint": validated["fingerprint"],
                "trusted_types": validated["inspection"]["trusted_types"],
                "metrics": validated["verdict"]["metrics"],
                "measurements": validated["measurements"],
            },
        )
        db.commit()
        committed = True
    except IntegrityError as exc:
        db.rollback()
        raise TabularError(
            code="ML_IMPORT_LINEAGE_CONFLICT",
            message="Another version of this lineage was registered at the same time. Retry.",
            status_code=409,
        ) from exc
    except BaseException:
        db.rollback()
        raise
    finally:
        if not committed:
            store = get_object_store()
            for key in (model_prefix(workspace_id, model.id), (summary or {}).get("key")):
                if key:
                    try:
                        store.delete_prefix(key)
                    except Exception:  # noqa: BLE001 - unreferenced bytes, logged
                        logger.warning("ml_import: orphan not deleted", key=key)
    from app.services.tabular_ml import _register_version, sync_challenger

    _register_version(model)
    db.commit()
    sync_challenger(db, model)
    return model


def run_import_job(job_id: str) -> dict:
    """Celery entry point; the executing process is the reader being qualified."""
    from app.db.base import SessionLocal
    from app.models.user import User
    from app.services.ml_requalification import _claim

    with SessionLocal() as db:
        job = _claim(db, job_id, datetime.utcnow(), kinds={KIND})
        if job is None:
            return {"status": "not_claimed", "job_id": job_id}
        stamp = job.updated_at
        data = dict(job.input_ref or {})
        facts = {
            "job_id": job.id,
            "archive_sha256": data.get("archive_sha256"),
            "archive_bytes": data.get("archive_bytes"),
            "validation_rows": data.get("validation_rows"),
        }
        actor = str(data.get("actor") or "system")
        status, error, result = "completed", None, {}
        work = Path(tempfile.mkdtemp(prefix="ml-import-"))
        try:
            user = (
                db.get(User, job.created_by_user_id, populate_existing=True)
                if job.created_by_user_id
                else None
            )
            if job.created_by_user_id and user is None:
                raise TabularError(
                    code="ML_FORBIDDEN_ACTION",
                    message="The importer no longer exists.",
                    status_code=403,
                )
            validated = validate_staged(job, work)
            model = register(db, job, validated, user=user)
            result = {
                "verdict": "accepted",
                "model_id": model.id,
                "metrics": validated["verdict"]["metrics"],
                "measurements": validated["measurements"],
            }
        except TabularError as exc:
            status = "failed"
            error = f"{exc.code}: {exc.message}"[:500]
            details = exc.details or {}
            result = {
                "verdict": "refused",
                "code": exc.code,
                **{
                    key: details[key]
                    for key in ("reason", "error_code", "metrics", "measurements", "budgets")
                    if key in details
                },
            }
            if exc.code != "ML_AUDIT_UNAVAILABLE":
                audit_refusal(
                    db,
                    workspace_id=job.workspace_id,
                    actor=actor,
                    error=exc,
                    facts=facts,
                    ip=data.get("ip"),
                )
        except Exception as exc:  # noqa: BLE001 - the job row is the error channel
            db.rollback()
            logger.exception("ml_import: job crashed", job_id=job_id)
            status = "failed"
            error = f"ML_IMPORT_FAILED: {type(exc).__name__}"
            result = {"verdict": "refused", "code": "ML_IMPORT_FAILED"}
            audit_refusal(
                db,
                workspace_id=job.workspace_id,
                actor=actor,
                error=TabularError(code="ML_IMPORT_FAILED", message="crashed", status_code=500),
                facts=facts,
                ip=data.get("ip"),
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)
            _delete_staging(job)
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


__all__ = [
    "KIND",
    "TASK",
    "contract_from",
    "dispatch",
    "extract_archive",
    "inspect_bundle",
    "parse_validation",
    "public_job",
    "request_import",
    "run_import_job",
]
