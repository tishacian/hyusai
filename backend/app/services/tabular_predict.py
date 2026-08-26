"""The serving plane: one trained model answering, three ways.

A model that cannot be called is a report, not a model. This module is the one
place that turns an ``ml_models`` row into an answer, and it does so for three
callers that differ in who they are, not in what they get:

* the **playground** on the model card — a workspace session, one row at a time,
  used to convince a human that the fit means something;
* a **customer's system** — the same endpoint, authenticated by an
  ``MLModelApiKey`` in ``X-API-Key`` instead of a session, with MLflow's own
  ``{"inputs": [...]}`` request shape so the cURL looks like what the audience
  already knows from ``mlflow models serve``;
* the **Flow plane** — ``ml_predict_v1`` for a record (which is also what a
  published model's Skill runs) and ``ml_batch_score_v1`` for a whole dataset.

Three properties are worth stating because they are decisions, not accidents.

**What serves is the lineage, not the row.** A caller addresses a model and gets
the version its lineage promoted (:func:`serving_version`), and the answer says
which one that was. That is the whole point of a champion alias: promoting v2
changes what answers without anyone reissuing a key or editing a URL. Pinning to
one exact version stays available, explicitly, per request.

**The contract is strict at the door and generous in the form.** The endpoint
refuses an unknown field and a missing one, because a typo that silently scores
a median is worse than an error. The playground, meanwhile, opens pre-filled
from the same contract, so a human never types forty fields. The strictness and
the convenience live in different layers on purpose.

**A loaded pipeline is cached, keyed by what would invalidate it.** Loading an
MLflow directory means an object-store round trip and a skops deserialization —
tens to hundreds of milliseconds, which is the difference between a playground
that feels alive and one that feels broken. The cache key carries the artifact
identity, so a retrain cannot be answered by its predecessor.

Where it runs: in-process, unlike training. Training is minutes of uninterruptible
CPU that must be killable, so it is a supervised subprocess; a prediction is
milliseconds over an artifact this platform serialized itself, under an allowlist
the fit computed. Paying process-spawn latency per prediction would buy nothing.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.skill import Skill
from app.models.tabular import MLModel, MLModelApiKey, TabularDataset
from app.services.skills_registry.binding import (
    SkillBindingError,
    workspace_skill_slug,
)
from app.services.tabular_datasets import (
    TabularError,
    dataset_reference,
    read_frame,
    register_frame,
)
from app.services.tabular_ml import (
    CLASSIFICATION,
    REGRESSION,
    champion_for,
    download_model_dir,
    model_reference,
)

logger = get_logger(__name__)

ML_PREDICT_SKILL_SLUG = "ml_predict_v1"
ML_SCORE_SKILL_SLUG = "ml_batch_score_v1"

# The header a customer's system authenticates with. Named for what it is rather
# than for this platform, because the cURL on the slide is read by people who
# have seen this header in every serving stack they already run.
API_KEY_HEADER = "X-API-Key"

# MLflow's signature vocabulary. Every numeric feature reaches here as a double
# because the training harness casts integer columns before fitting — an integer
# column cannot carry a hole, and the signature it writes is enforced later.
_NUMERIC_TYPES = frozenset({"double", "float", "long", "integer"})
_TRUE = frozenset({"true", "1", "yes", "y", "t"})
_FALSE = frozenset({"false", "0", "no", "n", "f"})

# Predicting a large dataset is one pass, but materializing every probability
# vector for it at once is not. Chunked so peak memory follows the chunk.
_SCORE_CHUNK_ROWS = 50_000

# How many fields a single-row explanation perturbs. Each one costs a row in one
# extra batched predict, so the ceiling is about how much a human can read, not
# about compute.
_EXPLAIN_FIELDS = 6


def preload_deserializer() -> None:
    """Import the reader MLflow reaches for, before a prediction waits on it.

    ``skops.io`` builds its trusted-type tables at import time, and it builds
    them by asking every module already in ``sys.modules`` whether it owns a
    name — the same walk ``pickle.whichmodule`` does. In this process that walk
    reaches ``transformers``, whose lazy ``__getattr__`` answers by importing
    the module a name lives in, so the walk imports a pile of image processors
    on the way past: ten seconds on the demo host, against six in a process
    that has never heard of transformers. Either way it is ten seconds that
    would land inside the *first* prediction of every backend worker, which is
    the one a demo makes.

    Warmed for the same reason the cross-encoder is, and silent about failure
    for a different one: a deployment that cannot read artifacts should refuse
    the predict route with the reason, which it already does, rather than
    refuse to boot.
    """

    try:
        import mlflow.pyfunc  # noqa: F401
        import skops.io  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - a warm failure is not a boot failure
        logger.warning("tabular_predict: deserializer preload failed", error=str(exc)[:300])


# ---------------------------------------------------------------------------
# The loaded-model cache
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LoadedModel:
    """One deserialized pipeline, plus the directory it was read from."""

    model_id: str
    fingerprint: str
    pipeline: Any
    classes: list[str]
    directory: Path
    loaded_at: float
    load_ms: float


_cache: "OrderedDict[str, LoadedModel]" = OrderedDict()
# One lock for the whole cache rather than per entry: entries are cheap to
# describe and expensive to build, and two requests racing for the same cold
# model should load it once.
_cache_lock = threading.RLock()


def _fingerprint(model: MLModel) -> str:
    """What must change for a cached pipeline to be the wrong answer.

    The artifact URI and the row's last write. A retrain publishes under a new
    model id, so this is belt and braces — but the belt is what keeps a promoted
    v2 from being answered by v1's resident pipeline.
    """

    stamp = model.trained_at or model.updated_at
    return "|".join(
        (
            str(model.model_uri or ""),
            stamp.isoformat() if stamp else "",
            str(model.status or ""),
        )
    )


def _evict(entry: LoadedModel) -> None:
    shutil.rmtree(entry.directory, ignore_errors=True)


def load_pipeline(model: MLModel) -> LoadedModel:
    """Return the model's pipeline, from cache when the artifact is unchanged."""

    entry, _ = load_pipeline_traced(model)
    return entry


def _load_mlflow_model(directory: Path) -> Any:
    """Read an MLmodel directory and return the estimator inside it.

    Through ``mlflow.pyfunc.load_model``, which is the portable door: it reads
    the ``MLmodel`` file, honours the flavor recorded there and fails loudly on
    an artifact this stack cannot serve — none of which is true of reaching past
    it into the flavor module. That is the whole "no lock-in" claim of the
    format, and it is worth exercising rather than asserting.

    Then unwrapped, because the pyfunc facade answers ``predict`` and a churn
    model whose answer is "1" without "0.87" is a demo that does not land. The
    facade knows this and offers ``get_raw_model()`` for exactly that; the
    fallbacks below are for older wheels that only expose the attribute the
    method reads. Nothing is given up by unwrapping: the object is the estimator
    the flavor loaded either way.
    """

    import mlflow.pyfunc

    served = mlflow.pyfunc.load_model(str(directory))
    for reach in (
        lambda: served.get_raw_model(),
        lambda: served._model_impl.get_raw_model(),
        lambda: served._model_impl.sklearn_model,
    ):
        try:
            estimator = reach()
        except Exception:  # noqa: BLE001 - try the next shape of the same facade
            continue
        if estimator is not None and hasattr(estimator, "predict"):
            return estimator
    raise TabularError(
        code="ML_ARTIFACT_UNLOADABLE",
        message=(
            "The model artifact loaded, but no estimator could be read out of "
            "it — probabilities and per-row contributions need the estimator, "
            "not the serving facade."
        ),
        status_code=409,
    )


def load_pipeline_traced(model: MLModel) -> tuple[LoadedModel, bool]:
    """As ``load_pipeline``, plus whether the pipeline was already resident.

    The residency flag exists because callers report timings. ``load_ms`` on the
    entry is what building *that entry* cost, so quoting it on a hit tells an
    operator a request spent five seconds loading a model it never loaded — and
    the whole claim of this cache is that the second call does not pay that.
    """

    if not settings.ml_predict_enabled:
        raise TabularError(
            code="ML_PREDICT_DISABLED",
            message="Prediction is not enabled on this deployment.",
            status_code=409,
        )
    if model.status != "ready":
        raise TabularError(
            code="ML_MODEL_NOT_READY",
            message="The model is not trained yet.",
            status_code=409,
            details={"status": model.status},
        )

    fingerprint = _fingerprint(model)
    with _cache_lock:
        cached = _cache.get(model.id)
        if cached is not None and cached.fingerprint == fingerprint:
            _cache.move_to_end(model.id)
            return cached, True
        if cached is not None:
            _cache.pop(model.id, None)
            _evict(cached)

        started = time.monotonic()
        directory = Path(tempfile.mkdtemp(prefix="ml-serve-"))
        try:
            download_model_dir(model, directory)
            pipeline = _load_mlflow_model(directory)
        except TabularError:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        except Exception as exc:  # noqa: BLE001 - a load failure is an answer
            shutil.rmtree(directory, ignore_errors=True)
            logger.warning(
                "tabular_predict: artifact unloadable",
                model_id=model.id,
                error=str(exc)[:300],
            )
            raise TabularError(
                code="ML_ARTIFACT_UNLOADABLE",
                message="The model artifact could not be loaded.",
                status_code=409,
                details={"reason": f"{type(exc).__name__}: {exc}"[:300]},
            ) from exc

        entry = LoadedModel(
            model_id=model.id,
            fingerprint=fingerprint,
            pipeline=pipeline,
            classes=_classes_of(model, pipeline),
            directory=directory,
            loaded_at=time.time(),
            load_ms=round((time.monotonic() - started) * 1000, 1),
        )
        _cache[model.id] = entry
        while len(_cache) > int(settings.ml_predict_cache_size):
            _, dropped = _cache.popitem(last=False)
            _evict(dropped)
        return entry, False


def _classes_of(model: MLModel, pipeline: Any) -> list[str]:
    """Class labels in ``predict_proba`` column order.

    The row's copy is authoritative because it is what the model card and the
    published Skill's schema already promised; the pipeline is the fallback for
    a row written before that column existed.
    """

    stored = [str(value) for value in (model.classes_json or [])]
    if stored:
        return stored
    raw = getattr(pipeline, "classes_", None)
    return [_label(value) for value in list(raw)] if raw is not None else []


def drop_from_cache(model_id: str) -> bool:
    """Forget a model, e.g. because its row (and bytes) were deleted."""

    with _cache_lock:
        entry = _cache.pop(model_id, None)
    if entry is None:
        return False
    _evict(entry)
    return True


def cache_state() -> dict[str, Any]:
    """What is resident, for the operator surfaces and the tests."""

    with _cache_lock:
        return {
            "size": len(_cache),
            "capacity": int(settings.ml_predict_cache_size),
            "models": [
                {
                    "model_id": entry.model_id,
                    "loaded_at": entry.loaded_at,
                    "load_ms": entry.load_ms,
                }
                for entry in _cache.values()
            ],
        }


def reset_cache() -> None:
    """Drop everything resident. Used by tests and by a workspace teardown."""

    with _cache_lock:
        entries = list(_cache.values())
        _cache.clear()
    for entry in entries:
        _evict(entry)


# ---------------------------------------------------------------------------
# The input contract
# ---------------------------------------------------------------------------


def contract_fields(model: MLModel) -> list[dict[str, Any]]:
    """The fields a prediction must supply, in the order the fit saw them.

    Order is not cosmetic: skrub's vectorizer refuses a frame whose columns
    arrive in a different order than at fit time, so the contract *is* the
    column order. It also excludes what the fit dropped, which is why it is the
    truth here rather than ``MLModel.features``.
    """

    signature = model.signature_json if isinstance(model.signature_json, dict) else {}
    fields = [
        entry
        for entry in (signature.get("inputs") or [])
        if isinstance(entry, dict) and entry.get("name")
    ]
    if not fields:
        raise TabularError(
            code="ML_CONTRACT_MISSING",
            message="The model has no input contract, so it cannot be called.",
            status_code=409,
        )
    return fields


def _label(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)[:120]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _coerce_cell(field_spec: dict[str, Any], value: Any) -> Any:
    """One value, in the type the fit was given, or a coded refusal.

    ``None`` survives on purpose: a hole is a legitimate production value, and
    the pipeline was built to take one. What is refused is a value that is not
    of the declared kind at all — a word where a number belongs — because
    silently coercing that to a hole would turn a caller's bug into a plausible
    prediction.
    """

    name = str(field_spec.get("name"))
    declared = str(field_spec.get("type") or "string")
    if value is None or value == "":
        return None
    if declared in _NUMERIC_TYPES:
        number = _finite(value)
        if number is None:
            raise TabularError(
                code="ML_PREDICT_FIELD_NOT_NUMERIC",
                message=f"'{name}' expects a number.",
                details={"field": name, "value": str(value)[:80]},
            )
        return number
    if declared == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise TabularError(
            code="ML_PREDICT_FIELD_NOT_BOOLEAN",
            message=f"'{name}' expects true or false.",
            details={"field": name, "value": str(value)[:80]},
        )
    if declared == "datetime":
        return str(value)[:64]
    return str(value)[:500]


def coerce_rows(model: MLModel, rows: Any) -> list[dict[str, Any]]:
    """Validate a prediction batch against the contract, or refuse it.

    Every refusal names the field, because the caller here is a form or a
    customer's integration and both can act on a name.
    """

    fields = contract_fields(model)
    if not isinstance(rows, list) or not rows:
        raise TabularError(
            code="ML_PREDICT_ROWS_REQUIRED",
            message="Send at least one row of feature values.",
        )
    ceiling = int(settings.ml_predict_max_rows)
    if len(rows) > ceiling:
        raise TabularError(
            code="ML_PREDICT_TOO_MANY_ROWS",
            message=(
                f"An inline prediction takes at most {ceiling} rows (got "
                f"{len(rows)}). Score a dataset with a Flow instead."
            ),
            details={"rows": len(rows), "limit": ceiling},
        )

    known = {str(spec.get("name")) for spec in fields}
    coerced: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TabularError(
                code="ML_PREDICT_ROW_NOT_OBJECT",
                message=f"Row {index + 1} is not an object of feature values.",
                details={"row": index},
            )
        unknown = sorted(str(key) for key in row if str(key) not in known)
        if unknown:
            raise TabularError(
                code="ML_PREDICT_FIELD_UNKNOWN",
                message=f"'{unknown[0]}' is not an input of this model.",
                details={"row": index, "fields": unknown[:8]},
            )
        missing = sorted(name for name in known if name not in row)
        if missing:
            raise TabularError(
                code="ML_PREDICT_FIELD_MISSING",
                message=(
                    f"'{missing[0]}' is required by this model's input contract."
                ),
                details={"row": index, "fields": missing[:8]},
            )
        try:
            coerced.append(
                {
                    str(spec["name"]): _coerce_cell(spec, row.get(str(spec["name"])))
                    for spec in fields
                }
            )
        except TabularError as exc:
            details = dict(exc.details or {})
            details["row"] = index
            raise TabularError(
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                details=details,
            ) from exc
    return coerced


def build_frame(fields: list[dict[str, Any]], rows: list[dict[str, Any]]) -> Any:
    """A pandas frame the fitted pipeline recognizes: same columns, same order."""

    import pandas as pd

    ordered = [str(spec["name"]) for spec in fields]
    frame = pd.DataFrame(
        {name: [row.get(name) for row in rows] for name in ordered},
        columns=ordered,
    )
    for spec in fields:
        name = str(spec["name"])
        declared = str(spec.get("type") or "string")
        if declared in _NUMERIC_TYPES:
            frame[name] = pd.to_numeric(frame[name], errors="coerce").astype("float64")
        elif declared == "boolean":
            frame[name] = frame[name].astype("boolean")
        elif declared == "datetime":
            frame[name] = pd.to_datetime(frame[name], errors="coerce")
        else:
            frame[name] = frame[name].astype("string")
    return frame


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


def serving_version(
    db: DBSession, model: MLModel, *, version: Any = None
) -> MLModel:
    """The version that answers for a lineage, or one pinned explicitly.

    Default is the champion, so an integration written against a model follows
    promotions without being rewritten. A caller that needs reproducibility
    names a version and gets exactly it.
    """

    if version is not None:
        try:
            wanted = int(version)
        except (TypeError, ValueError) as exc:
            raise TabularError(
                code="ML_VERSION_UNKNOWN",
                message="A pinned version must be a number.",
                details={"version": str(version)[:20]},
            ) from exc
        if wanted == int(model.version or 1):
            pinned = model
        else:
            pinned = (
                db.query(MLModel)
                .filter(
                    MLModel.workspace_id == model.workspace_id,
                    MLModel.slug == model.slug,
                    MLModel.version == wanted,
                )
                .first()
            )
        if pinned is None:
            raise TabularError(
                code="ML_VERSION_UNKNOWN",
                message=f"Version {wanted} does not exist in this lineage.",
                status_code=404,
                details={"version": wanted},
            )
        if pinned.status != "ready":
            raise TabularError(
                code="ML_MODEL_NOT_READY",
                message=f"Version {wanted} is not trained.",
                status_code=409,
                details={"status": pinned.status, "version": wanted},
            )
        return pinned

    serving = champion_for(
        db, workspace_id=model.workspace_id, slug=model.slug
    )
    if serving is None:
        raise TabularError(
            code="ML_NOTHING_SERVES",
            message="No trained version of this model can serve yet.",
            status_code=409,
        )
    return serving


def _served_block(model: MLModel) -> dict[str, Any]:
    return {
        **model_reference(model),
        "row_count": int(model.row_count or 0),
        "trained_at": model.trained_at.isoformat() if model.trained_at else None,
    }


def _positive_label(model: MLModel, classes: list[str]) -> str | None:
    """The class a single number is about: churned, not retained.

    Read off the training evidence when it is there, else the last class, which
    is the convention the harness's binary metrics already use.
    """

    metrics = model.metrics_json if isinstance(model.metrics_json, dict) else {}
    target = metrics.get("target") if isinstance(metrics.get("target"), dict) else {}
    declared = target.get("positive")
    if isinstance(declared, str) and declared in classes:
        return declared
    return classes[-1] if len(classes) == 2 else None


def _predict_frame(
    entry: LoadedModel, model: MLModel, frame: Any
) -> tuple[list[Any], Any]:
    """Run the pipeline once, with probabilities when the task has them."""

    try:
        predicted = entry.pipeline.predict(frame)
    except Exception as exc:  # noqa: BLE001 - the pipeline's refusal is the answer
        raise TabularError(
            code="ML_PREDICT_FAILED",
            message="The model could not score these values.",
            status_code=409,
            details={"reason": f"{type(exc).__name__}: {exc}"[:300]},
        ) from exc
    proba = None
    if model.task == CLASSIFICATION and hasattr(entry.pipeline, "predict_proba"):
        try:
            proba = entry.pipeline.predict_proba(frame)
        except Exception:  # noqa: BLE001 - a class score is decoration
            proba = None
    return list(predicted), proba


def _rows_from(
    model: MLModel,
    classes: list[str],
    positive: str | None,
    predicted: list[Any],
    proba: Any,
) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    for index, raw in enumerate(predicted):
        if model.task == CLASSIFICATION:
            label = _label(raw)
            answer: dict[str, Any] = {"prediction": label}
            if proba is not None and index < len(proba):
                vector = [
                    {
                        "label": classes[position] if position < len(classes) else str(position),
                        "value": round(float(value), 6),
                    }
                    for position, value in enumerate(proba[index])
                ]
                answer["probabilities"] = vector
                confident = max(vector, key=lambda item: item["value"], default=None)
                if confident is not None:
                    answer["confidence"] = confident["value"]
                if positive is not None:
                    answer["score"] = next(
                        (
                            item["value"]
                            for item in vector
                            if item["label"] == positive
                        ),
                        None,
                    )
        else:
            answer = {"prediction": _finite(raw)}
        answers.append(answer)
    return answers


def _ranked_names(model: MLModel, fields: list[dict[str, Any]]) -> list[str]:
    """Field names worth perturbing, most explanatory first.

    Permutation importance from the fit is the ranking when it exists, because
    perturbing the sixth-most-useful column tells a viewer nothing.
    """

    metrics = model.metrics_json if isinstance(model.metrics_json, dict) else {}
    known = [str(spec["name"]) for spec in fields]
    ranked = [
        str(entry.get("feature"))
        for entry in (metrics.get("importances") or [])
        if isinstance(entry, dict) and str(entry.get("feature")) in known
    ]
    return ranked + [name for name in known if name not in ranked]


def _measure_of(answer: dict[str, Any], task: str) -> float | None:
    """The one number an explanation moves: the positive score, or the value."""

    if task == CLASSIFICATION:
        value = answer.get("score")
        return _finite(value) if value is not None else _finite(answer.get("confidence"))
    return _finite(answer.get("prediction"))


def explain_row(
    entry: LoadedModel,
    model: MLModel,
    fields: list[dict[str, Any]],
    row: dict[str, Any],
    *,
    base: dict[str, Any],
    classes: list[str],
    positive: str | None,
) -> list[dict[str, Any]]:
    """What this row's own values did to its answer, by counterfactual.

    For each of the top fields, the row is re-scored with that one field set to
    the value the training set considers typical — the median of a numeric
    column, the most frequent level of a categorical one, both computed at fit
    time and carried in the contract. The reported effect is the movement that
    substitution costs: "being on a month-to-month contract is worth +0.21 of
    churn probability, holding everything else at this customer's values".

    This is a local explanation, not a Shapley value, and the UI says so. It is
    honest about what it measures, costs one batched predict of at most six rows,
    and needs no extra dependency — which is what makes it shippable on a model
    card that has to answer in under a second.
    """

    reference = _measure_of(base, str(model.task))
    if reference is None:
        return []
    by_name = {str(spec["name"]): spec for spec in fields}
    variants: list[tuple[str, Any, dict[str, Any]]] = []
    for name in _ranked_names(model, fields)[:_EXPLAIN_FIELDS]:
        spec = by_name.get(name)
        if spec is None:
            continue
        try:
            neutral = _coerce_cell(spec, spec.get("default"))
        except TabularError:
            continue
        if neutral == row.get(name):
            # Already typical: there is nothing this field is doing to the score.
            continue
        variants.append((name, neutral, {**row, name: neutral}))
    if not variants:
        return []

    frame = build_frame(fields, [variant for _, _, variant in variants])
    predicted, proba = _predict_frame(entry, model, frame)
    answers = _rows_from(model, classes, positive, predicted, proba)
    contributions: list[dict[str, Any]] = []
    for (name, neutral, _), answer in zip(variants, answers):
        counterfactual = _measure_of(answer, str(model.task))
        if counterfactual is None:
            continue
        contributions.append(
            {
                "field": name,
                "value": row.get(name),
                "typical": neutral,
                "effect": round(reference - counterfactual, 6),
            }
        )
    contributions.sort(key=lambda item: abs(item["effect"]), reverse=True)
    return contributions


def predict_rows(
    db: DBSession,
    model: MLModel,
    rows: Any,
    *,
    version: Any = None,
    caller: str = "session",
    explain: bool = False,
) -> dict[str, Any]:
    """Answer an inline batch, and say which version answered."""

    served = serving_version(db, model, version=version)
    coerced = coerce_rows(served, rows)
    entry, resident = load_pipeline_traced(served)
    started = time.monotonic()
    fields = contract_fields(served)
    frame = build_frame(fields, coerced)
    predicted, proba = _predict_frame(entry, served, frame)
    classes = entry.classes
    positive = _positive_label(served, classes)
    answers = _rows_from(served, classes, positive, predicted, proba)
    if explain and len(answers) == 1:
        answers[0]["contributions"] = explain_row(
            entry,
            served,
            fields,
            coerced[0],
            base=answers[0],
            classes=classes,
            positive=positive,
        )
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    record_usage(db, served, rows=len(answers))
    logger.info(
        "tabular_predict: answered",
        model_id=served.id,
        rows=len(answers),
        duration_ms=elapsed_ms,
        caller=caller,
    )
    return {
        "served": _served_block(served),
        "task": served.task,
        "target": served.target,
        "classes": classes,
        "positive_label": positive,
        "predictions": answers,
        "rows": len(answers),
        "duration_ms": elapsed_ms,
        # What *this* request paid to get a pipeline in memory. Zero on a hit,
        # which is the number the cache exists to produce.
        "load_ms": 0.0 if resident else entry.load_ms,
        "cached": resident,
    }


def record_usage(db: DBSession, model: MLModel, *, rows: int) -> None:
    """Count predictions, not requests: what makes a model visibly in use."""

    model.predict_count = int(model.predict_count or 0) + max(1, int(rows))
    model.last_predict_at = datetime.utcnow()
    db.commit()


# ---------------------------------------------------------------------------
# Batch scoring (the Flow node)
# ---------------------------------------------------------------------------


def _unique_name(base: str, taken: Iterable[str]) -> str:
    existing = set(taken)
    if base not in existing:
        return base
    for suffix in range(2, 100):
        candidate = f"{base}_{suffix}"
        if candidate not in existing:
            return candidate
    return f"{base}_{secrets.token_hex(3)}"


def score_dataset(
    db: DBSession,
    *,
    model: MLModel,
    dataset: TabularDataset,
    output_name: str | None = None,
    version: Any = None,
    run_id: str | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Score a whole dataset and persist the result as a new versioned dataset.

    The output keeps every input column and appends the answer, because a score
    sheet whose rows cannot be joined back to a customer is not actionable. It
    is registered with ``source="score"``, which is what lets the data plane
    tell a scored table apart from a transformed one in lineage.
    """

    served = serving_version(db, model, version=version)
    fields = contract_fields(served)
    if dataset.status != "ready":
        raise TabularError(
            code="DATASET_NOT_READY",
            message="The dataset to score is still being prepared.",
            status_code=409,
            details={"status": dataset.status},
        )
    rows = int(dataset.row_count or 0)
    ceiling = int(settings.ml_score_max_rows)
    if rows > ceiling:
        raise TabularError(
            code="ML_SCORE_TOO_MANY_ROWS",
            message=(
                f"The dataset has {rows:,} rows, above the {ceiling:,} scoring "
                "ceiling."
            ),
            details={"rows": rows, "limit": ceiling},
        )

    import polars as pl

    started = time.monotonic()
    frame = read_frame(dataset)
    present = set(frame.columns)
    wanted = [str(spec["name"]) for spec in fields]
    absent = [name for name in wanted if name not in present]
    if absent:
        raise TabularError(
            code="ML_SCORE_COLUMN_MISSING",
            message=(
                f"The dataset has no '{absent[0]}' column, which this model "
                "requires."
            ),
            status_code=409,
            details={"columns": absent[:8]},
        )

    entry = load_pipeline(served)
    classes = entry.classes
    positive = _positive_label(served, classes)
    features = frame.select(wanted).to_pandas()

    predictions: list[Any] = []
    confidences: list[float | None] = []
    scores: list[float | None] = []
    for offset in range(0, max(len(features), 1), _SCORE_CHUNK_ROWS):
        chunk = features.iloc[offset : offset + _SCORE_CHUNK_ROWS]
        if chunk.empty:
            break
        typed = build_frame(fields, chunk.to_dict(orient="records"))
        predicted, proba = _predict_frame(entry, served, typed)
        answers = _rows_from(served, classes, positive, predicted, proba)
        for answer in answers:
            predictions.append(answer.get("prediction"))
            confidences.append(answer.get("confidence"))
            scores.append(answer.get("score"))

    columns = {
        _unique_name("prediction", frame.columns): pl.Series(
            predictions,
            dtype=pl.Utf8 if served.task == CLASSIFICATION else pl.Float64,
        )
    }
    if served.task == CLASSIFICATION and any(
        value is not None for value in confidences
    ):
        columns[_unique_name("confidence", [*frame.columns, *columns])] = pl.Series(
            confidences, dtype=pl.Float64
        )
        if positive is not None and any(value is not None for value in scores):
            columns[
                _unique_name(f"score_{positive}", [*frame.columns, *columns])
            ] = pl.Series(scores, dtype=pl.Float64)
    scored = frame.with_columns(
        [series.alias(name) for name, series in columns.items()]
    )

    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    output = register_frame(
        db,
        workspace_id=served.workspace_id,
        name=output_name or f"{dataset.name} · scored",
        frame=scored,
        source="score",
        produced_by=ML_SCORE_SKILL_SLUG,
        parent_ids=[dataset.id],
        run_id=run_id,
        node_id=node_id,
        lineage={
            "engine": "sklearn",
            "model": {
                "model_id": served.id,
                "slug": served.slug,
                "version": int(served.version or 1),
                "task": served.task,
                "algo": served.algo,
                "target": served.target,
            },
            "added_columns": list(columns),
            "sources": [{"dataset_id": dataset.id, "slug": dataset.slug}],
            "duration_ms": elapsed_ms,
        },
    )
    record_usage(db, served, rows=len(predictions))
    logger.info(
        "tabular_predict: dataset scored",
        model_id=served.id,
        dataset_id=output.id,
        rows=len(predictions),
        duration_ms=elapsed_ms,
    )
    return {
        **dataset_reference(output),
        "model": _served_block(served),
        "scored_rows": len(predictions),
        "added_columns": list(columns),
        "duration_ms": elapsed_ms,
    }


# ---------------------------------------------------------------------------
# Scoped API keys
# ---------------------------------------------------------------------------

KEY_PREFIX = "agpk_"
_KEY_LOOKUP_CHARS = 12


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def mint_api_key(
    db: DBSession,
    *,
    model: MLModel,
    name: Any = None,
    created_by: str | None = None,
) -> tuple[MLModelApiKey, str]:
    """Create a key for this model's lineage and return it once, in the clear.

    Only the digest is kept, so a leaked database is not a leaked key and this
    platform cannot show a secret twice — which is the property that makes
    rotation the answer to "I lost it" rather than a support request.
    """

    if model.status != "ready":
        raise TabularError(
            code="ML_MODEL_NOT_READY",
            message="Only a trained model can be called, so only one can hold keys.",
            status_code=409,
            details={"status": model.status},
        )
    live = (
        db.query(MLModelApiKey)
        .filter(
            MLModelApiKey.model_id == model.id,
            MLModelApiKey.revoked_at.is_(None),
        )
        .count()
    )
    ceiling = int(settings.ml_predict_max_keys)
    if live >= ceiling:
        raise TabularError(
            code="ML_KEY_LIMIT",
            message=f"This model already has {ceiling} active keys. Revoke one first.",
            status_code=409,
            details={"limit": ceiling},
        )
    secret = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    row = MLModelApiKey(
        workspace_id=model.workspace_id,
        model_id=model.id,
        name=(str(name or "").strip() or "Prediction key")[:200],
        key_prefix=secret[:_KEY_LOOKUP_CHARS],
        key_sha256=_hash_secret(secret),
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, secret


def list_api_keys(db: DBSession, *, model: MLModel) -> list[MLModelApiKey]:
    return (
        db.query(MLModelApiKey)
        .filter(MLModelApiKey.model_id == model.id)
        .order_by(MLModelApiKey.created_at.desc())
        .limit(100)
        .all()
    )


def revoke_api_key(db: DBSession, *, model: MLModel, key_id: str) -> MLModelApiKey:
    row = (
        db.query(MLModelApiKey)
        .filter(
            MLModelApiKey.id == key_id,
            MLModelApiKey.model_id == model.id,
        )
        .first()
    )
    if row is None:
        raise TabularError(
            code="ML_KEY_NOT_FOUND",
            message="That key does not belong to this model.",
            status_code=404,
        )
    if row.revoked_at is None:
        row.revoked_at = datetime.utcnow()
        db.commit()
    return row


def serialize_api_key(
    row: MLModelApiKey, *, secret: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "name": row.name,
        "prefix": row.key_prefix,
        "revoked": row.revoked_at is not None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "use_count": int(row.use_count or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if secret is not None:
        # Shown exactly once, at mint time. Never re-derivable from the row.
        payload["secret"] = secret
    return payload


def authenticate_key(db: DBSession, presented: Any) -> tuple[MLModelApiKey, MLModel]:
    """Resolve a presented secret to its key row and the model it addresses."""

    secret = str(presented or "").strip()
    if not secret:
        raise TabularError(
            code="ML_KEY_REQUIRED",
            message="This endpoint requires a model API key.",
            status_code=401,
        )
    digest = _hash_secret(secret)
    row = (
        db.query(MLModelApiKey)
        .filter(MLModelApiKey.key_sha256 == digest)
        .first()
    )
    # Compared again in constant time so a partial-index match cannot be turned
    # into an oracle by timing the lookup.
    if row is None or not hmac.compare_digest(str(row.key_sha256), digest):
        raise TabularError(
            code="ML_KEY_INVALID",
            message="That key is not valid.",
            status_code=401,
        )
    if row.revoked_at is not None:
        raise TabularError(
            code="ML_KEY_REVOKED",
            message="That key was revoked.",
            status_code=401,
        )
    model = db.query(MLModel).filter(MLModel.id == row.model_id).first()
    if model is None:
        raise TabularError(
            code="ML_MODEL_NOT_FOUND",
            message="The model this key addresses no longer exists.",
            status_code=404,
        )
    row.last_used_at = datetime.utcnow()
    row.use_count = int(row.use_count or 0) + 1
    db.commit()
    return row, model


# ---------------------------------------------------------------------------
# Publishing a model as a Skill
# ---------------------------------------------------------------------------


def _local_name(model: MLModel) -> str:
    """A namespace-legal local name derived from the lineage slug."""

    cleaned = "".join(
        character if character.isalnum() else "_"
        for character in str(model.slug or "model").lower()
    ).strip("_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"m_{cleaned}" if cleaned else "model"
    return f"predict_{cleaned}"[:64].rstrip("_")


def predict_input_schema(model: MLModel) -> dict[str, Any]:
    """A JSON Schema for one prediction, typed from the model's own contract.

    This is what makes a published model usable by an agent rather than merely
    callable: the tool the model becomes declares its fields, their ranges and,
    for a low-cardinality column, its actual choices.
    """

    properties: dict[str, Any] = {}
    required: list[str] = []
    for spec in contract_fields(model):
        name = str(spec["name"])
        declared = str(spec.get("type") or "string")
        entry: dict[str, Any] = {}
        if declared in _NUMERIC_TYPES:
            entry["type"] = "number"
            for source, target in (("min", "minimum"), ("max", "maximum")):
                value = _finite(spec.get(source))
                if value is not None:
                    entry[target] = value
        elif declared == "boolean":
            entry["type"] = "boolean"
        else:
            entry["type"] = "string"
            choices = spec.get("choices")
            if isinstance(choices, list) and choices:
                entry["enum"] = [str(choice) for choice in choices][:24]
        properties[name] = entry
        required.append(name)
    return {
        "type": "object",
        "required": required,
        "properties": properties,
    }


def predict_output_schema(model: MLModel) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prediction": {
                "type": "string" if model.task == CLASSIFICATION else "number"
            },
            "served": {"type": "object"},
        },
    }
    if model.task == CLASSIFICATION:
        body["properties"]["confidence"] = {"type": "number"}
        body["properties"]["probabilities"] = {"type": "array"}
    return body


def _skill_description(model: MLModel) -> str:
    """Plain text, because catalog descriptions render verbatim in the UI."""

    metric = (model.metrics_json or {}).get("primary") or {}
    key = str(metric.get("key") or "")
    value = _finite(metric.get("value"))
    evidence = f" Test {key} {value:.3f}." if key and value is not None else ""
    verb = "Classifies" if model.task == CLASSIFICATION else "Estimates"
    return (
        f"{verb} '{model.target}' for one record using the trained model "
        f"{model.name} (version {int(model.version or 1)}, {model.algo}). The "
        "version that answers is whichever one currently serves this lineage."
        f"{evidence}"
    )


def publish_as_skill(
    db: DBSession, *, model: MLModel, created_by: str | None = None
) -> dict[str, Any]:
    """Expose one model lineage as a workspace Skill an agent can call.

    The Skill binds to the verified ``registry_call`` executor with the model
    pinned in ``frozen_input``: no new executor kind, no workspace-supplied code
    path, and a run cannot substitute a different model for the pinned one. The
    slug names the lineage, not the version, so promoting a retrain changes what
    the Skill answers without republishing it.
    """

    from app.services.skills_registry.executors import validate_executor_binding

    if model.status != "ready":
        raise TabularError(
            code="ML_MODEL_NOT_READY",
            message="Only a trained model can be published.",
            status_code=409,
            details={"status": model.status},
        )
    try:
        identity = workspace_skill_slug(
            workspace_id=model.workspace_id, local_name=_local_name(model)
        )
    except SkillBindingError as exc:
        raise TabularError(
            code="ML_PUBLISH_NAME_INVALID",
            message=exc.message,
            status_code=409,
        ) from exc

    existing = db.query(Skill).filter(Skill.slug == identity.slug).first()
    if existing is not None and existing.workspace_id != model.workspace_id:
        raise TabularError(
            code="ML_PUBLISH_NAME_TAKEN",
            message="A Skill with this name already exists outside this workspace.",
            status_code=409,
        )

    executor = validate_executor_binding(
        {
            "kind": "registry_call",
            "params": {
                "skill_slug": ML_PREDICT_SKILL_SLUG,
                "frozen_input": {
                    "_predict": {
                        "model_id": model.id,
                        "model_slug": model.slug,
                        "workspace_id": model.workspace_id,
                    }
                },
            },
        }
    )
    row = existing or Skill(workspace_id=model.workspace_id, slug=identity.slug)
    row.name = f"Predict · {model.name}"[:200]
    row.description = _skill_description(model)
    row.type = "workflow"
    row.category = "Models"
    row.executor = executor
    row.input_schema = predict_input_schema(model)
    row.output_schema = predict_output_schema(model)
    row.execution = {
        "mode": "sync",
        "timeout_ms": int(float(settings.ml_predict_timeout_s) * 1000),
        "retryable": True,
        "idempotent": True,
    }
    row.pricing = {"unit": "per_prediction", "unit_price": 0.0, "currency": "USD"}
    row.certification_level = "basic"
    row.is_seeded = "N"
    row.provider = "internal"
    if existing is None:
        db.add(row)

    # Every version of the lineage points at the one Skill, so the card of a
    # retired version still says the lineage is published.
    (
        db.query(MLModel)
        .filter(
            MLModel.workspace_id == model.workspace_id,
            MLModel.slug == model.slug,
        )
        .update({MLModel.published_skill_slug: identity.slug}, synchronize_session=False)
    )
    db.commit()
    db.refresh(row)
    logger.info(
        "tabular_predict: model published",
        model_id=model.id,
        skill_slug=identity.slug,
    )
    return serialize_published_skill(row)


def unpublish_skill(db: DBSession, *, model: MLModel) -> str | None:
    """Withdraw the Skill a lineage was published as."""

    slug = model.published_skill_slug
    if not slug:
        return None
    (
        db.query(Skill)
        .filter(Skill.slug == slug, Skill.workspace_id == model.workspace_id)
        .delete(synchronize_session=False)
    )
    (
        db.query(MLModel)
        .filter(
            MLModel.workspace_id == model.workspace_id,
            MLModel.slug == model.slug,
        )
        .update({MLModel.published_skill_slug: None}, synchronize_session=False)
    )
    db.commit()
    return slug


def serialize_published_skill(row: Skill) -> dict[str, Any]:
    return {
        "slug": row.slug,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "input_schema": dict(row.input_schema or {}),
        "output_schema": dict(row.output_schema or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def published_skill(db: DBSession, model: MLModel) -> dict[str, Any] | None:
    if not model.published_skill_slug:
        return None
    row = (
        db.query(Skill)
        .filter(
            Skill.slug == model.published_skill_slug,
            Skill.workspace_id == model.workspace_id,
        )
        .first()
    )
    return serialize_published_skill(row) if row is not None else None


def pinned_lineage(executor: Any) -> tuple[str, str] | None:
    """The ``(workspace_id, model_slug)`` a published Skill froze, if it froze one.

    Read off the executor rather than off a marker column: the frozen input IS
    the binding a run dispatches through, so anything derived from it describes
    what the Skill actually calls rather than what a second field claims it does.
    """

    if not isinstance(executor, dict) or executor.get("kind") != "registry_call":
        return None
    params = executor.get("params")
    if not isinstance(params, dict) or params.get("skill_slug") != ML_PREDICT_SKILL_SLUG:
        return None
    frozen = params.get("frozen_input")
    spec = frozen.get("_predict") if isinstance(frozen, dict) else None
    if not isinstance(spec, dict):
        return None
    workspace_id = spec.get("workspace_id")
    slug = spec.get("model_slug")
    if not isinstance(workspace_id, str) or not isinstance(slug, str):
        return None
    return (workspace_id, slug) if workspace_id and slug else None


def skill_provenance(
    db: DBSession, skills: Sequence[Skill]
) -> dict[str, dict[str, Any]]:
    """The model each published Skill answers from, keyed by Skill slug.

    Derived on read rather than copied at publication, and that is the whole
    point. The Skill is bound to a *lineage*, not to a version, so the chip has
    to name whichever version currently serves it — a snapshot taken when the
    Skill was created would still claim v3 the morning v4 was promoted, and a
    provenance chip that lies is worse than no chip.

    One query per distinct lineage, and none at all for a catalog that publishes
    no model, so the list endpoint pays only for what it shows.
    """

    wanted: dict[str, tuple[str, str]] = {}
    for row in skills:
        lineage = pinned_lineage(row.executor)
        if lineage is not None:
            wanted[row.slug] = lineage
    if not wanted:
        return {}

    champions: dict[tuple[str, str], MLModel | None] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for skill_slug, lineage in wanted.items():
        if lineage not in champions:
            workspace_id, model_slug = lineage
            champions[lineage] = champion_for(
                db, workspace_id=workspace_id, slug=model_slug
            )
        model = champions[lineage]
        if model is None:
            continue
        metric = (model.metrics_json or {}).get("primary") or {}
        value = _finite(metric.get("value"))
        provenance[skill_slug] = {
            "model_id": model.id,
            "model_slug": model.slug,
            "name": model.name,
            "version": int(model.version or 1),
            "task": model.task,
            "target": model.target,
            "metric": (
                {"key": str(metric.get("key")), "value": value}
                if metric.get("key") and value is not None
                else None
            ),
        }
    return provenance


# ---------------------------------------------------------------------------
# Projection for the model card
# ---------------------------------------------------------------------------


def public_predict_path(model: MLModel) -> str:
    """The path a key is used against, for the card's copy-ready snippet.

    The same route the Playground calls: one endpoint, two ways to prove who you
    are. A separate machine-only path would have to be documented, versioned and
    kept honest against this one for no gain — and an integration that survives a
    retrain is already handled, because the model addressed here answers with
    whichever version its lineage promoted.
    """

    return f"{settings.api_v1_prefix}/ml-models/{model.id}/predict"


def serving_block(db: DBSession, model: MLModel) -> dict[str, Any]:
    """Everything the Playground and the key panel need in one read."""

    champion = champion_for(db, workspace_id=model.workspace_id, slug=model.slug)
    try:
        fields = contract_fields(model)
    except TabularError:
        fields = []
    return {
        "enabled": bool(settings.ml_predict_enabled and settings.tabular_data_enabled),
        "callable": bool(
            settings.ml_predict_enabled and model.status == "ready" and fields
        ),
        "serving_version": int(champion.version) if champion is not None else None,
        "serving_model_id": champion.id if champion is not None else None,
        "is_serving": bool(champion is not None and champion.id == model.id),
        "max_rows": int(settings.ml_predict_max_rows),
        "fields": fields,
        "classes": [str(value) for value in (model.classes_json or [])],
        "positive_label": _positive_label(
            model, [str(value) for value in (model.classes_json or [])]
        ),
        "predict_count": int(model.predict_count or 0),
        "last_predict_at": (
            model.last_predict_at.isoformat() if model.last_predict_at else None
        ),
        "published_skill": published_skill(db, model),
        "keys": [serialize_api_key(row) for row in list_api_keys(db, model=model)],
        "endpoint": public_predict_path(model),
        "key_header": API_KEY_HEADER,
    }


__all__ = [
    "API_KEY_HEADER",
    "KEY_PREFIX",
    "ML_PREDICT_SKILL_SLUG",
    "ML_SCORE_SKILL_SLUG",
    "LoadedModel",
    "authenticate_key",
    "build_frame",
    "cache_state",
    "coerce_rows",
    "contract_fields",
    "drop_from_cache",
    "explain_row",
    "list_api_keys",
    "load_pipeline",
    "load_pipeline_traced",
    "mint_api_key",
    "predict_input_schema",
    "predict_output_schema",
    "predict_rows",
    "public_predict_path",
    "publish_as_skill",
    "published_skill",
    "record_usage",
    "reset_cache",
    "revoke_api_key",
    "score_dataset",
    "serialize_api_key",
    "serialize_published_skill",
    "serving_block",
    "serving_version",
    "unpublish_skill",
]
