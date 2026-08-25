"""No-code sklearn training over workspace datasets.

What "no-code" means here
-------------------------
Three decisions are taken away from the author, and they are the three that
usually cost the most and buy the least:

* **preprocessing** — skrub's ``TableVectorizer`` reads the frame and decides
  per column (numeric, low-cardinality categorical, free text, datetime). So a
  raw churn extract with an MSISDN, a plan code and a last-topup date trains
  without a feature-engineering step;
* **the estimator zoo** — a curated catalog of four families, each declared with
  the knobs that matter and their bounds, so the UI can render a form instead of
  asking for a class name;
* **the evidence** — every run computes the same metric set, curves, class
  balance and permutation importances, because a model card that only sometimes
  has a ROC curve is not a model card.

Where a run executes
--------------------
On the **application interpreter**, as a supervised subprocess (see
:mod:`app.resources.ml_train_harness`). Not a managed venv, unlike the transform
nodes: those run author-written code, where isolation is the point and version
drift is harmless. Here the code is ours and the serving path deserializes what
training serialized, so the two sides must be the same install. What the
subprocess buys is the rest of the posture — a killable process group (a fit
ignores signals from inside), rlimits, and a scrubbed environment.

Where a model lives
-------------------
The artifact is an MLflow model directory in the ObjectStore, addressed by
``model_uri``; the ``ml_models`` row is the registry (``slug``/``version`` for
the retrain lineage, ``is_champion`` for the one that serves). Keeping the format
MLflow's means the artifact is loadable by anything that speaks
``mlflow.pyfunc``; keeping the registry in Postgres means no tracking server has
to be operated for facts this table already holds.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.skill import Skill
from app.models.tabular import (
    MODEL_TERMINAL_STATUSES,
    MLModel,
    MLModelApiKey,
    TabularDataset,
)
from app.services import ml_registry
from app.services.object_store import get_object_store
from app.services.recipe_executions import supervise_harness
from app.services.tabular_datasets import (
    NUMERIC_KINDS,
    TabularError,
    materialize,
    next_version,
    resolve_dataset_ref,
    slugify,
)

logger = get_logger(__name__)

ML_TRAIN_SKILL_SLUG = "ml_train_sklearn_v1"
ML_TRAIN_TASK = "agentium.ml_train"

# The steps a training row reports through ``status_detail``, in order. Codes
# rather than sentences for the same reason as the ingest plane: two locales poll
# the same row. The last three are claimed by the harness itself — only the child
# knows when a fit ends and its scoring begins — which is why it writes them to
# ``progress.txt`` and the worker republishes what it reads there.
TRAIN_STEPS: tuple[str, ...] = ("queued", "reading", "fitting", "scoring", "saving")
_HARNESS_STEPS = frozenset(TRAIN_STEPS)
# The file the harness appends its current step to, inside the run's scratch.
_PROGRESS_FILE = "progress.txt"

_HARNESS_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "ml_train_harness.py"
)

# Machine reasons the harness exits with, mapped to the codes the UI translates.
_EXIT_CODES = {
    1: "ML_FIT_FAILED",
    2: "ML_TARGET_UNUSABLE",
    3: "ML_ROWS_INSUFFICIENT",
    4: "ML_ARTIFACT_UNWRITABLE",
    5: "ML_HARNESS_ERROR",
}

CLASSIFICATION = "classification"
REGRESSION = "regression"
TASKS = (CLASSIFICATION, REGRESSION)


def harness_path() -> Path:
    return _HARNESS_PATH


# ---------------------------------------------------------------------------
# Algorithm catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Knob:
    """One tunable of an algorithm, with the bounds the UI renders as a field.

    Bounds are part of the contract, not a UI convenience: they are what keeps
    a no-code form from producing a fit that runs for an hour.
    """

    key: str
    kind: str  # int | float
    default: float
    minimum: float
    maximum: float
    step: float = 1.0
    # Sentinel meaning "let the estimator decide" (sklearn's ``None``).
    auto_at: float | None = None

    def coerce(self, value: Any) -> Any:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float(self.default)
        number = max(self.minimum, min(self.maximum, number))
        if self.auto_at is not None and number == self.auto_at:
            return None
        return int(round(number)) if self.kind == "int" else round(number, 6)

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "key": self.key,
            "kind": self.kind,
            "default": self.default,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
        }
        if self.auto_at is not None:
            body["auto_at"] = self.auto_at
        return body


@dataclass(frozen=True, slots=True)
class Algo:
    """One estimator family, addressable by a task-neutral key.

    Task-neutral on purpose: switching a node from churn to ARPU keeps
    "gradient boosting" selected instead of resetting the form, because
    ``estimators`` holds one class per task behind the same key.
    """

    key: str
    estimators: dict[str, str]
    knobs: tuple[Knob, ...] = ()
    # Linear and distance-based models need comparable scales; trees do not care.
    scale: bool = False
    # Ranked for the picker: the first algo of a task is the sane default.
    rank: int = 0
    tags: tuple[str, ...] = ()
    # Whether the estimator takes a ``random_state``. A seeded fit is what makes
    # "v2 beats v1" a comparison rather than a coin toss.
    seeded: bool = True

    def supports(self, task: str) -> bool:
        return task in self.estimators

    def estimator_for(self, task: str) -> str:
        return self.estimators[task]

    def resolve(self, knobs: Any) -> dict[str, Any]:
        chosen = knobs if isinstance(knobs, dict) else {}
        return {
            knob.key: knob.coerce(chosen.get(knob.key, knob.default))
            for knob in self.knobs
        }

    def payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "tasks": sorted(self.estimators),
            "estimators": dict(self.estimators),
            "scale": self.scale,
            "tags": list(self.tags),
            "knobs": [knob.payload() for knob in self.knobs],
        }


ALGOS: tuple[Algo, ...] = (
    Algo(
        key="gradient_boosting",
        estimators={
            CLASSIFICATION: "sklearn.ensemble.HistGradientBoostingClassifier",
            REGRESSION: "sklearn.ensemble.HistGradientBoostingRegressor",
        },
        knobs=(
            Knob("max_iter", "int", 150, 20, 600, 10),
            Knob("learning_rate", "float", 0.1, 0.01, 0.5, 0.01),
            Knob("max_leaf_nodes", "int", 31, 4, 127, 1),
        ),
        rank=0,
        tags=("tabular", "fast", "robust"),
    ),
    Algo(
        key="random_forest",
        estimators={
            CLASSIFICATION: "sklearn.ensemble.RandomForestClassifier",
            REGRESSION: "sklearn.ensemble.RandomForestRegressor",
        },
        knobs=(
            Knob("n_estimators", "int", 200, 50, 600, 10),
            # 0 means "grow until the leaves are pure", i.e. sklearn's None.
            Knob("max_depth", "int", 0, 0, 40, 1, auto_at=0),
            Knob("min_samples_leaf", "int", 1, 1, 50, 1),
        ),
        rank=1,
        tags=("tabular", "explainable"),
    ),
    Algo(
        key="linear",
        estimators={
            CLASSIFICATION: "sklearn.linear_model.LogisticRegression",
            REGRESSION: "sklearn.linear_model.Ridge",
        },
        knobs=(
            Knob("max_iter", "int", 500, 100, 3000, 50),
            Knob("alpha", "float", 1.0, 0.001, 20.0, 0.01),
        ),
        scale=True,
        rank=2,
        tags=("baseline", "interpretable"),
    ),
    Algo(
        key="knn",
        estimators={
            CLASSIFICATION: "sklearn.neighbors.KNeighborsClassifier",
            REGRESSION: "sklearn.neighbors.KNeighborsRegressor",
        },
        knobs=(Knob("n_neighbors", "int", 15, 1, 100, 1),),
        scale=True,
        rank=3,
        tags=("baseline",),
        seeded=False,
    ),
)

ALGO_BY_KEY = {algo.key: algo for algo in ALGOS}

# The one place the catalog's vocabulary and sklearn's disagree: a logistic
# regression's ``C`` is the INVERSE of a regularization strength, so the shared
# "alpha" knob has to be inverted, not merely renamed.
_INVERTED_ALPHA = frozenset({("linear", CLASSIFICATION)})


def estimator_params(algo: Algo, task: str, knobs: dict[str, Any]) -> dict[str, Any]:
    """Translate catalog knobs into the estimator's own keyword arguments.

    The catalog is the vocabulary the form speaks, and it is task-neutral by
    design; sklearn's is neither. Translating here keeps that mismatch out of
    both the UI and the harness.
    """

    params: dict[str, Any] = dict(knobs)
    if (algo.key, task) in _INVERTED_ALPHA and "alpha" in params:
        strength = float(params.pop("alpha")) or 1.0
        params["C"] = round(1.0 / strength, 6)
    if algo.seeded:
        params.setdefault("random_state", int(settings.ml_train_random_state))
    if algo.key == "random_forest":
        # One fit already owns the worker slot; a nested thread pool under
        # RLIMIT_AS buys nothing and costs address space.
        params.setdefault("n_jobs", 1)
    return params


def catalog_payload() -> dict[str, Any]:
    """What the training form renders: algorithms, knobs and platform limits."""

    return {
        "enabled": bool(settings.ml_train_enabled and settings.tabular_data_enabled),
        "tasks": list(TASKS),
        "algos": [algo.payload() for algo in sorted(ALGOS, key=lambda a: a.rank)],
        "limits": {
            "min_rows": int(settings.ml_train_min_rows),
            "max_rows": int(settings.ml_train_max_rows),
            "max_features": int(settings.ml_train_max_features),
            "max_classes": int(settings.ml_train_max_classes),
            "timeout_s": float(settings.ml_train_timeout_s),
        },
        "defaults": {
            "task": CLASSIFICATION,
            "algo": ALGOS[0].key,
            "test_size": 0.25,
            "cross_validation": 0,
        },
    }


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TrainingSpec:
    """A validated training request: everything the worker needs, nothing else."""

    dataset: TabularDataset
    task: str
    target: str
    features: list[str]
    algo: Algo
    knobs: dict[str, Any]
    test_size: float
    cross_validation: int
    name: str
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _schema_kinds(dataset: TabularDataset) -> dict[str, str]:
    return {
        str(column.get("name")): str(column.get("kind") or "other")
        for column in (dataset.schema_json or [])
        if column.get("name")
    }


def _distinct(dataset: TabularDataset, column: str) -> int:
    stats = (dataset.stats_json or {}).get(column) or {}
    try:
        return int(stats.get("distinct") or 0)
    except (TypeError, ValueError):
        return 0


def infer_task(dataset: TabularDataset, target: str) -> str:
    """The task a target implies, so the form opens on the right one.

    A float column is a regression; anything else with few distinct values is a
    classification. Deliberately simple: the author can override it, and being
    wrong here costs a click, not a run.
    """

    kinds = _schema_kinds(dataset)
    kind = kinds.get(target, "other")
    distinct = _distinct(dataset, target)
    if kind in NUMERIC_KINDS:
        if kind == "integer" and 0 < distinct <= int(settings.ml_train_max_classes):
            return CLASSIFICATION
        return REGRESSION
    return CLASSIFICATION


def validate_training(
    dataset: TabularDataset,
    *,
    task: Any,
    target: Any,
    features: Any = None,
    algo: Any = None,
    knobs: Any = None,
    test_size: Any = None,
    cross_validation: Any = None,
    name: Any = None,
) -> TrainingSpec:
    """Refuse everything a fit could only discover the expensive way.

    Every refusal here is one the author can act on from the form: a target that
    is not in the dataset, a regression on a text column, a class that appears
    once. What is left for the harness is what only fitting can tell.
    """

    if not settings.ml_train_enabled:
        raise TabularError(
            code="ML_TRAIN_DISABLED",
            message="Model training is not enabled on this deployment.",
            status_code=409,
        )
    if dataset.status != "ready":
        raise TabularError(
            code="DATASET_NOT_READY",
            message="The dataset is still being prepared.",
            status_code=409,
            details={"status": dataset.status},
        )

    kinds = _schema_kinds(dataset)
    if not kinds:
        raise TabularError(
            code="ML_DATASET_UNPROFILED",
            message="The dataset has no column profile yet.",
            status_code=409,
        )

    label = str(target or "").strip()
    if not label:
        raise TabularError(
            code="ML_TARGET_REQUIRED",
            message="Choose the column the model has to predict.",
        )
    if label not in kinds:
        raise TabularError(
            code="ML_TARGET_UNKNOWN",
            message=f"'{label}' is not a column of this dataset.",
            details={"target": label},
        )

    chosen_task = str(task or "").strip() or infer_task(dataset, label)
    if chosen_task not in TASKS:
        raise TabularError(
            code="ML_TASK_UNKNOWN",
            message="A model is either a classification or a regression.",
            details={"task": chosen_task[:40]},
        )
    target_kind = kinds[label]
    if chosen_task == REGRESSION and target_kind not in NUMERIC_KINDS:
        raise TabularError(
            code="ML_TARGET_NOT_NUMERIC",
            message=(
                f"'{label}' is not numeric, so it cannot be regressed. Train a "
                "classification instead."
            ),
            details={"target": label, "kind": target_kind},
        )
    if chosen_task == CLASSIFICATION:
        distinct = _distinct(dataset, label)
        max_classes = int(settings.ml_train_max_classes)
        if distinct > max_classes:
            raise TabularError(
                code="ML_TARGET_TOO_MANY_CLASSES",
                message=(
                    f"'{label}' holds {distinct:,} distinct values — too many to "
                    f"classify (limit {max_classes})."
                ),
                details={"target": label, "distinct": distinct},
            )
        if 0 < distinct < 2:
            raise TabularError(
                code="ML_TARGET_SINGLE_CLASS",
                message=f"'{label}' holds one value only: there is nothing to separate.",
                details={"target": label},
            )

    requested = [
        str(item).strip()
        for item in (features or [])
        if str(item or "").strip()
    ]
    if requested:
        unknown = [name_ for name_ in requested if name_ not in kinds]
        if unknown:
            raise TabularError(
                code="ML_FEATURE_UNKNOWN",
                message=f"'{unknown[0]}' is not a column of this dataset.",
                details={"features": unknown[:8]},
            )
        selected = [name_ for name_ in dict.fromkeys(requested) if name_ != label]
    else:
        selected = [name_ for name_ in kinds if name_ != label]
    if not selected:
        raise TabularError(
            code="ML_FEATURES_REQUIRED",
            message="A model needs at least one feature besides its target.",
        )
    max_features = int(settings.ml_train_max_features)
    if len(selected) > max_features:
        raise TabularError(
            code="ML_TOO_MANY_FEATURES",
            message=f"Select at most {max_features} features (got {len(selected)}).",
            details={"count": len(selected)},
        )

    rows = int(dataset.row_count or 0)
    if rows < int(settings.ml_train_min_rows):
        raise TabularError(
            code="ML_ROWS_INSUFFICIENT",
            message=(
                f"The dataset has {rows:,} rows; training needs at least "
                f"{int(settings.ml_train_min_rows):,}."
            ),
            details={"rows": rows},
        )
    if rows > int(settings.ml_train_max_rows):
        raise TabularError(
            code="ML_ROWS_TOO_MANY",
            message=(
                f"The dataset has {rows:,} rows, above the "
                f"{int(settings.ml_train_max_rows):,} training ceiling."
            ),
            details={"rows": rows},
        )

    algo_key = str(algo or "").strip() or ALGOS[0].key
    resolved = ALGO_BY_KEY.get(algo_key)
    if resolved is None:
        raise TabularError(
            code="ML_ALGO_UNKNOWN",
            message=f"'{algo_key}' is not an offered algorithm.",
            details={"algos": sorted(ALGO_BY_KEY)},
        )
    if not resolved.supports(chosen_task):
        raise TabularError(
            code="ML_ALGO_TASK_MISMATCH",
            message=f"'{algo_key}' does not do {chosen_task}.",
            details={"algo": algo_key, "task": chosen_task},
        )

    try:
        split = float(test_size) if test_size is not None else 0.25
    except (TypeError, ValueError):
        split = 0.25
    split = min(0.5, max(0.05, split))
    try:
        folds = int(cross_validation) if cross_validation is not None else 0
    except (TypeError, ValueError):
        folds = 0
    folds = 0 if folds < 2 else min(10, folds)

    # Identifier-like columns train fine and generalize not at all, so they are
    # surfaced as a warning rather than silently dropped or refused.
    warnings: list[dict[str, Any]] = []
    for name_ in selected:
        if kinds.get(name_) == "string" and rows and _distinct(dataset, name_) >= rows:
            warnings.append({"code": "ML_FEATURE_IDENTIFIER", "feature": name_})

    default_name = f"{dataset.name} · {label}"
    return TrainingSpec(
        dataset=dataset,
        task=chosen_task,
        target=label,
        features=selected,
        algo=resolved,
        knobs=resolved.resolve(knobs),
        test_size=round(split, 4),
        cross_validation=folds,
        name=(str(name or "").strip() or default_name)[:200],
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def model_prefix(workspace_id: str, model_id: str) -> str:
    store = get_object_store()
    return store.key("workspaces", workspace_id, "ml", "models", model_id, "model")


def upload_model_dir(local: Path, *, workspace_id: str, model_id: str) -> tuple[str, int]:
    """Publish an MLflow model directory file by file, and return (uri, bytes).

    File by file rather than as one archive: the artifact stays a *readable*
    MLflow directory in the bucket (``MLmodel`` inspectable, ``requirements.txt``
    diffable), which is the whole point of not inventing a format.
    """

    store = get_object_store()
    prefix = model_prefix(workspace_id, model_id)
    total = 0
    for path in sorted(local.rglob("*")):
        if not path.is_file():
            continue
        payload = path.read_bytes()
        total += len(payload)
        store.write_bytes(f"{prefix}/{path.relative_to(local).as_posix()}", payload)
    if not total:
        raise TabularError(
            code="ML_ARTIFACT_EMPTY",
            message="The training run produced no artifact.",
        )
    return prefix, total


def download_model_dir(model: MLModel, destination: Path) -> Path:
    """Materialize a model's MLflow directory locally (serving side)."""

    if not model.model_uri:
        raise TabularError(
            code="ML_MODEL_NOT_READY",
            message="The model has no artifact yet.",
            status_code=409,
        )
    store = get_object_store()
    keys = store.list_keys(model.model_uri)
    if not keys:
        raise TabularError(
            code="ML_ARTIFACT_MISSING",
            message="The model artifact is not in the object store.",
            status_code=409,
        )
    destination.mkdir(parents=True, exist_ok=True)
    prefix = model.model_uri.rstrip("/") + "/"
    for key in keys:
        relative = key[len(prefix):] if key.startswith(prefix) else Path(key).name
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        store.copy_to_local(key, target)
    return destination


# ---------------------------------------------------------------------------
# Lifecycle (caller side)
# ---------------------------------------------------------------------------


def create_model(
    db: DBSession,
    *,
    workspace_id: str,
    spec: TrainingSpec,
    description: str | None = None,
    created_by: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
) -> MLModel:
    """Stage one training run as a ``pending`` model row (not yet dispatched)."""

    slug = slugify(spec.name, fallback="model")
    model = MLModel(
        id=str(uuid4()),
        workspace_id=workspace_id,
        name=spec.name,
        slug=slug,
        version=_next_model_version(db, workspace_id=workspace_id, slug=slug),
        description=(description or None),
        task=spec.task,
        algo=spec.algo.key,
        target=spec.target,
        features=list(spec.features),
        params_json={
            "knobs": dict(spec.knobs),
            "estimator": spec.algo.estimator_for(spec.task),
            "estimator_params": estimator_params(spec.algo, spec.task, spec.knobs),
            "scale": bool(spec.algo.scale),
            "warnings": list(spec.warnings),
        },
        status="pending",
        status_detail=TRAIN_STEPS[0],
        dataset_id=spec.dataset.id,
        dataset_slug=spec.dataset.slug,
        row_count=int(spec.dataset.row_count or 0),
        test_size=spec.test_size,
        cross_validation=spec.cross_validation,
        metrics_json={},
        signature_json={},
        input_example_json={},
        classes_json=[],
        mlflow_model_name=f"{workspace_id[:8]}.{slug}",
        run_id=run_id,
        node_id=node_id,
        created_by=created_by,
    )
    db.add(model)
    db.flush()
    return model


def _next_model_version(db: DBSession, *, workspace_id: str, slug: str) -> int:
    rows = (
        db.query(MLModel.version)
        .filter(MLModel.workspace_id == workspace_id, MLModel.slug == slug)
        .all()
    )
    return max((int(row[0] or 0) for row in rows), default=0) + 1


def dispatch_training(db: DBSession, model: MLModel) -> str:
    """Enqueue the worker task; eager mode trains inline (dev/tests)."""

    if settings.worker_eager_mode:
        model.celery_task_id = f"eager:{model.id}"
        db.commit()
        run_training(model.id)
        return str(model.celery_task_id)
    from app.workers.celery_app import celery_app

    async_result = celery_app.send_task(
        ML_TRAIN_TASK,
        args=(model.id,),
        queue=settings.celery_task_default_queue,
    )
    model.celery_task_id = async_result.id
    db.commit()
    return async_result.id


def submit_training(
    db: DBSession,
    *,
    workspace_id: str,
    dataset_ref: Any,
    task: Any = None,
    target: Any = None,
    features: Any = None,
    algo: Any = None,
    knobs: Any = None,
    test_size: Any = None,
    cross_validation: Any = None,
    name: Any = None,
    description: str | None = None,
    created_by: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
) -> MLModel:
    """Resolve the dataset, validate the request, stage the row and dispatch it."""

    dataset = resolve_dataset_ref(db, workspace_id=workspace_id, ref=dataset_ref)
    spec = validate_training(
        dataset,
        task=task,
        target=target,
        features=features,
        algo=algo,
        knobs=knobs,
        test_size=test_size,
        cross_validation=cross_validation,
        name=name,
    )
    model = create_model(
        db,
        workspace_id=workspace_id,
        spec=spec,
        description=description,
        created_by=created_by,
        run_id=run_id,
        node_id=node_id,
    )
    db.commit()
    dispatch_training(db, model)
    db.expire_all()
    return db.query(MLModel).filter(MLModel.id == model.id).first() or model


def request_cancel(db: DBSession, model: MLModel) -> MLModel:
    """Cooperative cancel; a still-queued task is also revoked best-effort."""

    if model.status in MODEL_TERMINAL_STATUSES:
        return model
    model.cancel_requested = True
    if model.status == "pending":
        task_id = model.celery_task_id
        if task_id and not str(task_id).startswith("eager:"):
            try:
                from app.workers.celery_app import celery_app

                celery_app.control.revoke(task_id)
            except Exception:  # noqa: BLE001 - the DB flag stays authoritative
                logger.warning("tabular_ml: revoke failed", model_id=model.id)
        _finalize(model, status="cancelled", error="cancel_requested")
    db.commit()
    return model


def set_champion(db: DBSession, model: MLModel) -> MLModel:
    """Promote one version to the serving alias of its lineage.

    The alias is per ``slug``, so promoting version 3 demotes whichever version
    was serving — one champion per lineage is the invariant the predict path
    resolves against.
    """

    if model.status != "ready":
        raise TabularError(
            code="ML_MODEL_NOT_READY",
            message="Only a trained model can serve.",
            status_code=409,
            details={"status": model.status},
        )
    (
        db.query(MLModel)
        .filter(
            MLModel.workspace_id == model.workspace_id,
            MLModel.slug == model.slug,
            MLModel.id != model.id,
        )
        .update({MLModel.is_champion: False}, synchronize_session=False)
    )
    model.is_champion = True
    model.updated_at = datetime.utcnow()
    db.commit()
    # Move the registry alias with the row. Two names for one fact would be worse
    # than one: an operator who promotes here and then resolves
    # ``models:/<name>@champion`` elsewhere must get the version they just chose.
    if model.mlflow_model_name and model.mlflow_run_id:
        ml_registry.set_alias(
            model_name=model.mlflow_model_name,
            version=ml_registry.version_of_run(
                model_name=model.mlflow_model_name, run_id=model.mlflow_run_id
            ),
        )
    return model


def delete_model(db: DBSession, model: MLModel) -> str:
    """Drop a model version and, where the store allows it, its bytes.

    Hard-deleted, unlike a dataset: a dataset is a fact other rows are lineage
    of, whereas a retired model version is only reachable through the row that
    is being removed — and leaving a serving alias pointing at a retired version
    would be worse than losing it.

    Three things must not outlive the row, and all three are deleted here rather
    than left to a foreign key: a credential that still authenticates, a resident
    pipeline that still answers, and — once the last version of a lineage is
    gone — a published Skill whose every call would now fail. A cascade would
    cover the first only, and only on a backend that enforces it.
    """

    model_id = model.id
    workspace_id = model.workspace_id
    slug = model.slug
    published = model.published_skill_slug
    store = get_object_store()
    if store.backend == "local":
        try:
            store.delete_prefix(model_prefix(model.workspace_id, model.id))
        except Exception:  # noqa: BLE001 - the row delete stays authoritative
            logger.debug("tabular_ml: local artifact delete skipped", model_id=model.id)
    (
        db.query(MLModelApiKey)
        .filter(MLModelApiKey.model_id == model_id)
        .delete(synchronize_session=False)
    )
    db.delete(model)
    db.commit()

    survivors = (
        db.query(MLModel)
        .filter(MLModel.workspace_id == workspace_id, MLModel.slug == slug)
        .count()
    )
    if published and survivors == 0:
        (
            db.query(Skill)
            .filter(Skill.slug == published, Skill.workspace_id == workspace_id)
            .delete(synchronize_session=False)
        )
        db.commit()
        logger.info(
            "tabular_ml: published skill withdrawn with its last version",
            skill_slug=published,
        )

    # Deferred import: the serving plane reads this module, so the dependency
    # only points one way at import time.
    from app.services.tabular_predict import drop_from_cache

    # A resident pipeline outliving its row would keep answering as something
    # nobody can audit any more.
    drop_from_cache(model_id)
    return model_id


def get_model(
    db: DBSession, *, model_id: str, workspace_id: str, ready_only: bool = False
) -> MLModel:
    model = (
        db.query(MLModel)
        .filter(MLModel.id == model_id, MLModel.workspace_id == workspace_id)
        .first()
    )
    if model is None:
        raise TabularError(
            code="ML_MODEL_NOT_FOUND",
            message="The model does not exist in this workspace.",
            status_code=404,
        )
    if ready_only and model.status != "ready":
        raise TabularError(
            code="ML_MODEL_NOT_READY",
            message="The model is not trained yet.",
            status_code=409,
            details={"status": model.status},
        )
    return model


def champion_for(db: DBSession, *, workspace_id: str, slug: str) -> MLModel | None:
    """The version serving a lineage: the champion, else the latest ready one."""

    query = db.query(MLModel).filter(
        MLModel.workspace_id == workspace_id,
        MLModel.slug == slug,
        MLModel.status == "ready",
    )
    champion = query.filter(MLModel.is_champion.is_(True)).first()
    return champion or query.order_by(MLModel.version.desc()).first()


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


def serialize_model(
    model: MLModel, *, include_detail: bool = False
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": model.id,
        "name": model.name,
        "slug": model.slug,
        "version": int(model.version or 1),
        "description": model.description,
        "task": model.task,
        "algo": model.algo,
        "target": model.target,
        "features": list(model.features or []),
        "status": model.status,
        "status_detail": model.status_detail,
        "error": model.error,
        "cancel_requested": bool(model.cancel_requested),
        "is_champion": bool(model.is_champion),
        "dataset_id": model.dataset_id,
        "dataset_slug": model.dataset_slug,
        "row_count": int(model.row_count) if model.row_count is not None else None,
        "test_size": model.test_size,
        "cross_validation": model.cross_validation,
        "primary_metric": _primary_metric(model),
        "artifact_bytes": (
            int(model.artifact_bytes) if model.artifact_bytes is not None else None
        ),
        "predict_count": int(model.predict_count or 0),
        "last_predict_at": (
            model.last_predict_at.isoformat() if model.last_predict_at else None
        ),
        "published_skill_slug": model.published_skill_slug,
        "run_id": model.run_id,
        "node_id": model.node_id,
        "created_at": model.created_at.isoformat() if model.created_at else None,
        "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        "trained_at": model.trained_at.isoformat() if model.trained_at else None,
        "train_duration_ms": model.train_duration_ms,
    }
    if include_detail:
        payload["metrics"] = dict(model.metrics_json or {})
        payload["signature"] = dict(model.signature_json or {})
        payload["input_example"] = model.input_example_json or []
        payload["classes"] = list(model.classes_json or [])
        payload["params"] = dict(model.params_json or {})
        payload["model_uri"] = model.model_uri
    return payload


def _primary_metric(model: MLModel) -> dict[str, Any] | None:
    """The one number a list row shows, lifted out of the metric block."""

    primary = (model.metrics_json or {}).get("primary")
    if isinstance(primary, dict) and primary.get("key"):
        return {"key": str(primary["key"]), "value": primary.get("value")}
    return None


def model_reference(model: MLModel) -> dict[str, Any]:
    """The envelope a trained model travels as inside the DAG."""

    return {
        "model_id": model.id,
        "name": model.name,
        "slug": model.slug,
        "version": int(model.version or 1),
        "task": model.task,
        "algo": model.algo,
        "target": model.target,
        "metric": _primary_metric(model),
        "is_champion": bool(model.is_champion),
    }


# ---------------------------------------------------------------------------
# Worker side
# ---------------------------------------------------------------------------


def _finalize(
    model: MLModel, *, status: str, error: str | None = None
) -> None:
    model.status = status
    model.error = error
    model.status_detail = None
    model.updated_at = datetime.utcnow()


def cancel_requested(db: DBSession, model_id: str) -> bool:
    """Re-read the cooperative cancel flag (the supervisor's stop condition)."""

    db.expire_all()
    return bool(
        db.query(MLModel.cancel_requested).filter(MLModel.id == model_id).scalar()
    )


def mark_step(db: DBSession, model: MLModel, step: str) -> None:
    """Publish which training step the run is on, as a :data:`TRAIN_STEPS` code.

    Idempotent by design: the worker republishes whatever the harness last wrote
    on every poll tick, and committing the same value once a second for the
    length of a fit would be a write per second for nothing.
    """

    if model.status_detail == step:
        return
    model.status_detail = step[:300]
    model.updated_at = datetime.utcnow()
    db.commit()


def clamp_timeout(value: Any) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = float(settings.ml_train_timeout_s)
    if timeout <= 0:
        timeout = float(settings.ml_train_timeout_s)
    return min(timeout, float(settings.ml_train_timeout_s))


def _write_manifest(scratch: Path, model: MLModel, data_path: Path) -> Path:
    params = dict(model.params_json or {})
    manifest = {
        "data_path": str(data_path),
        "model_dir": str(scratch / "model"),
        "task": model.task,
        "target": model.target,
        "features": list(model.features or []),
        "estimator": params.get("estimator"),
        "params": dict(params.get("estimator_params") or {}),
        "scale": bool(params.get("scale")),
        "test_size": float(model.test_size or 0.25),
        "cv": int(model.cross_validation or 0),
        "random_state": int(settings.ml_train_random_state),
        "min_rows": int(settings.ml_train_min_rows),
        "max_classes": int(settings.ml_train_max_classes),
        "curve_points": int(settings.ml_train_curve_points),
        "importance_rows": int(settings.ml_train_importance_rows),
        "progress_path": str(scratch / _PROGRESS_FILE),
    }
    path = scratch / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def read_progress(scratch: Path) -> str | None:
    """The last step the harness claimed, or ``None`` when it claimed nothing.

    Only a known code is returned: the file is written by a subprocess and a
    truncated or half-flushed line must not become a status the UI cannot name.
    """

    try:
        lines = (scratch / _PROGRESS_FILE).read_text(encoding="utf-8").split()
    except OSError:
        return None
    for step in reversed(lines):
        if step in _HARNESS_STEPS:
            return step
    return None


def _harness_failure(run: Any, timeout_s: float) -> str:
    """One error string carrying the code AND the harness's own last line."""

    if run.status == "timed_out":
        return f"ML_TIMEOUT: training exceeded {int(timeout_s)}s"
    code = _EXIT_CODES.get(int(run.exit_code or 0), "ML_HARNESS_ERROR")
    tail = (run.stderr_tail or "").strip().splitlines()
    detail = tail[-1][:300] if tail else "the training run failed"
    return f"{code}: {detail}"


def read_summary(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _publish_progress(db: DBSession, model: MLModel, scratch: Path) -> None:
    """Republish the harness's own step onto the polled row."""

    step = read_progress(scratch)
    if step is not None:
        mark_step(db, model, step)


def run_training(model_id: str) -> dict[str, Any]:  # noqa: C901 - one linear lifecycle
    """Worker entrypoint: settle one training run end-to-end.

    Same lifecycle guards as the transform planes (terminal short-circuit,
    ``acks_late`` redelivery fail-closed, cooperative cancel) because the row is
    polled the same way — a fit that a redelivery replays would publish a second
    artifact for one version.
    """

    from app.db.base import SessionLocal

    with SessionLocal() as db:
        model = db.query(MLModel).filter(MLModel.id == model_id).first()
        if model is None:
            return {"id": model_id, "status": "missing"}
        if model.status in MODEL_TERMINAL_STATUSES:
            return {"id": model_id, "status": model.status}
        if model.status == "training":
            _finalize(model, status="failed", error="ml_worker_lost_after_claim")
            db.commit()
            return {"id": model_id, "status": "failed"}
        if not settings.ml_train_enabled:
            _finalize(model, status="failed", error="ML_TRAIN_DISABLED")
            db.commit()
            return {"id": model_id, "status": "failed"}
        if model.cancel_requested:
            _finalize(model, status="cancelled", error="cancel_requested")
            db.commit()
            return {"id": model_id, "status": "cancelled"}

        dataset = (
            db.query(TabularDataset)
            .filter(TabularDataset.id == model.dataset_id)
            .first()
            if model.dataset_id
            else None
        )
        if dataset is None or dataset.status != "ready":
            _finalize(
                model,
                status="failed",
                error="ML_DATASET_UNAVAILABLE: the training dataset is gone or unready",
            )
            db.commit()
            return {"id": model_id, "status": "failed"}

        model.status = "training"
        model.error = None
        mark_step(db, model, "reading")

        timeout_s = clamp_timeout(settings.ml_train_timeout_s)
        scratch = Path(tempfile.mkdtemp(prefix="ml-train-"))
        started = time.monotonic()
        status = "failed"
        error: str | None = None
        summary: dict[str, Any] = {}
        run = None
        try:
            data_path = materialize(dataset, scratch / "data.parquet")
            manifest_path = _write_manifest(scratch, model, data_path)
            result_path = scratch / "result.json"
            interpreter = Path(sys.executable)
            threads = str(int(settings.ml_train_threads))
            run = supervise_harness(
                [
                    str(interpreter),
                    str(harness_path()),
                    str(manifest_path),
                    str(result_path),
                ],
                venv_python=interpreter,
                scratch=scratch,
                timeout_s=timeout_s,
                should_cancel=lambda: cancel_requested(db, model_id),
                # The three steps inside the fit are the child's to name, so the
                # worker republishes them rather than guessing at the boundaries.
                on_poll=lambda: _publish_progress(db, model, scratch),
                timeout_error=f"ML_TIMEOUT: exceeded {int(timeout_s)}s",
                memory_limit_mb=int(settings.ml_train_memory_limit_mb),
                cpu_limit_s=int(settings.ml_train_cpu_limit_s),
                fsize_limit_mb=int(settings.ml_train_artifact_limit_mb),
                extra_env={
                    # BLAS libraries spawn a pool per process by default, which
                    # under RLIMIT_AS is how a fit dies before it starts.
                    "OMP_NUM_THREADS": threads,
                    "OPENBLAS_NUM_THREADS": threads,
                    "MKL_NUM_THREADS": threads,
                    "NUMEXPR_NUM_THREADS": threads,
                    "MLFLOW_TRACKING_URI": str(scratch / "mlruns"),
                },
            )
            if run.status == "cancelled":
                status, error = "cancelled", "cancel_requested"
            elif run.status is not None or run.exit_code != 0:
                status, error = "failed", _harness_failure(run, timeout_s)
            else:
                summary = read_summary(result_path)
                if not summary.get("metrics"):
                    status, error = (
                        "failed",
                        "ML_SUMMARY_MISSING: the run produced no evidence",
                    )
                else:
                    mark_step(db, model, "saving")
                    uri, size = upload_model_dir(
                        scratch / "model",
                        workspace_id=model.workspace_id,
                        model_id=model.id,
                    )
                    status, error = "ready", None
                    summary["model_uri"] = uri
                    summary["artifact_bytes"] = size
        except TabularError as exc:
            status, error = "failed", f"{exc.code}: {exc.message}"
        except Exception as exc:  # noqa: BLE001 - the row is the error channel
            logger.exception("tabular_ml: training crashed", model_id=model_id)
            status, error = "failed", f"ML_HARNESS_ERROR: {exc}"[:480]
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        db.expire_all()
        model = db.query(MLModel).filter(MLModel.id == model_id).first()
        if model is None:  # pragma: no cover - deleted mid-run
            return {"id": model_id, "status": "missing"}
        if status == "ready":
            _apply_summary(model, summary)
            model.status = "ready"
            model.status_detail = None
            model.error = None
            model.trained_at = datetime.utcnow()
            model.train_duration_ms = round((time.monotonic() - started) * 1000, 1)
            # A lineage with nothing serving promotes its first trained version:
            # a model nobody promoted is still the only one that can answer. A
            # retrain does NOT take over from a promoted champion — deciding
            # what serves is the operator's call, not the trainer's.
            serving = (
                db.query(MLModel.id)
                .filter(
                    MLModel.workspace_id == model.workspace_id,
                    MLModel.slug == model.slug,
                    MLModel.id != model.id,
                    MLModel.is_champion.is_(True),
                    MLModel.status == "ready",
                )
                .first()
            )
            model.is_champion = serving is None
            _register_version(model)
        else:
            _finalize(model, status=status, error=error)
        db.commit()
        logger.info(
            "tabular_ml: settled",
            model_id=model_id,
            status=status,
            duration_ms=model.train_duration_ms,
        )
        return {"id": model_id, "status": status}


def _register_version(model: MLModel) -> None:
    """Mirror a ready model into the MLflow registry, and never fail over it.

    The bytes are already on the object store, so the version is created against
    that location rather than uploaded again — see ``ml_registry``. What this
    call adds to the row is ``mlflow_run_id``: the handle that ties our record to
    a run a foreign MLflow client can read.
    """

    if not model.model_uri or not model.mlflow_model_name:
        return
    published = ml_registry.publish(
        model_name=model.mlflow_model_name,
        source_uri=get_object_store().uri(model.model_uri),
        metrics=model.metrics_json or {},
        params={
            "algo": model.algo,
            "task": model.task,
            "target": model.target,
            "features": len(list(model.features or [])),
            "test_size": model.test_size,
            "cross_validation": model.cross_validation or 0,
            "agentium_version": model.version,
        },
        tags={
            "agentium.model_id": model.id,
            "agentium.workspace_id": model.workspace_id,
            "agentium.dataset_id": model.dataset_id or "",
            "agentium.version": model.version,
        },
    )
    if not published:
        return
    model.mlflow_run_id = published["run_id"]
    if model.is_champion:
        # The lineage had nothing serving, so this version is what answers —
        # the alias has to say the same thing the row does.
        ml_registry.set_alias(
            model_name=model.mlflow_model_name, version=published["version"]
        )


def _apply_summary(model: MLModel, summary: dict[str, Any]) -> None:
    metrics = dict(summary.get("metrics") or {})
    model.metrics_json = metrics
    model.signature_json = dict(summary.get("signature") or {})
    model.input_example_json = summary.get("input_example") or []
    model.classes_json = [str(value) for value in (summary.get("classes") or [])]
    model.model_uri = summary.get("model_uri")
    model.artifact_bytes = int(summary.get("artifact_bytes") or 0) or None
    rows = metrics.get("rows") or {}
    if isinstance(rows, dict) and rows.get("total"):
        model.row_count = int(rows["total"])


def training_summary(model: MLModel) -> dict[str, Any]:
    """The block a Flow node emits: enough to badge the canvas, not the card."""

    return {
        **model_reference(model),
        "status": model.status,
        "rows": int(model.row_count or 0),
        "features": len(list(model.features or [])),
        "duration_ms": model.train_duration_ms,
    }


__all__ = [
    "ALGOS",
    "ALGO_BY_KEY",
    "CLASSIFICATION",
    "ML_TRAIN_SKILL_SLUG",
    "ML_TRAIN_TASK",
    "REGRESSION",
    "TASKS",
    "TRAIN_STEPS",
    "Algo",
    "Knob",
    "TrainingSpec",
    "cancel_requested",
    "catalog_payload",
    "champion_for",
    "clamp_timeout",
    "create_model",
    "delete_model",
    "dispatch_training",
    "download_model_dir",
    "estimator_params",
    "get_model",
    "harness_path",
    "infer_task",
    "model_prefix",
    "model_reference",
    "read_progress",
    "read_summary",
    "request_cancel",
    "run_training",
    "serialize_model",
    "set_champion",
    "submit_training",
    "training_summary",
    "upload_model_dir",
    "validate_training",
]
