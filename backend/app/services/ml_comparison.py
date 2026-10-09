"""Two model versions compared on the same rows, by skore's ComparisonReport.

Why this is not a client-side subtraction
-----------------------------------------
Every version already stores its own metric table, so the cheap comparison is to
put two of them side by side and subtract. The model card does exactly that for
its delta tiles, and it is honest *there*, because a delta against the previous
version is explicitly a comparison of two recorded results.

It stops being honest as soon as it is presented as "which model is better".
Those two tables were computed on two test splits, and if the versions were
trained on different datasets — which is the normal case here, since a Flow
pipeline derives features before fitting — the numbers were never measured on the
same rows. A 0.004 AUC gap between two splits means nothing at all.

So this module scores both pipelines over **one** test split and hands the two
reports to ``skore.ComparisonReport``, which produces the joint table. Same rows,
same labels, one column per estimator: the difference is then a property of the
models rather than of the sampling.

Choosing the rows
-----------------
The comparison dataset has to carry every feature *both* models need, so it is
picked from the two training datasets rather than assumed: whichever covers both
feature sets wins, and when neither does the request is refused with a code that
names the missing columns instead of silently comparing on a subset.

The split is reconstructed with the newer model's ``test_size`` and the fixed
training seed, which reproduces that model's own test rows exactly. For the other
model this is only leak-free if it was trained on the same dataset with the same
knobs; when it was not, the response carries a warning naming it. That is
deliberate: refusing would make the interesting comparison — a Flow-trained
version against the baseline it is meant to beat — impossible, and a silent
answer would be worse than either.
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.tabular import MLModel, TabularDataset
from app.services.tabular_datasets import TabularError, read_frame

logger = get_logger(__name__)

# The comparison scores two pipelines inline, in the request. The training
# ceiling is for a background fit and is far too generous for that.
_MAX_ROWS = 200_000


def _ready(model: MLModel, *, side: str) -> None:
    if model.status != "ready" or not model.model_uri:
        raise TabularError(
            code="ML_MODEL_NOT_READY",
            message="Only a trained model can be compared.",
            status_code=409,
            details={"side": side, "status": model.status},
        )


def _features(model: MLModel) -> list[str]:
    return [str(name) for name in (model.features or [])]


def _pick_dataset(
    db, *, left: MLModel, right: MLModel
) -> tuple[TabularDataset, list[str]]:
    """The dataset that can host both models, and the columns it would be missing.

    Prefers the *right* (newer) model's dataset, because the split is
    reconstructed from that model's knobs and reproducing its own test rows is
    the closest thing to a fair reading available.
    """

    wanted = set(_features(left)) | set(_features(right)) | {str(right.target)}
    shortfall: list[str] = []
    for candidate_id in (right.dataset_id, left.dataset_id):
        if not candidate_id:
            continue
        dataset = (
            db.query(TabularDataset)
            .filter(TabularDataset.id == candidate_id)
            .first()
        )
        if dataset is None or dataset.status != "ready":
            continue
        held = {
            str(column.get("name"))
            for column in (dataset.schema_json or [])
            if isinstance(column, dict)
        }
        missing = sorted(wanted - held)
        if not missing:
            return dataset, []
        if not shortfall or len(missing) < len(shortfall):
            shortfall = missing
    raise TabularError(
        code="ML_COMPARE_NO_COMMON_DATASET",
        message=(
            "Neither training dataset carries every column the two models need, "
            "so they cannot be scored on the same rows."
        ),
        status_code=409,
        details={"missing": shortfall[:12]},
    )


def _report(model: MLModel, frame, *, target: str):
    """One skore report for a stored pipeline over a prepared test frame."""

    from skore import EstimatorReport

    from app.services.tabular_predict import load_pipeline

    entry = load_pipeline(model)
    columns = _features(model)
    x_test = frame[columns].copy()
    for column in columns:
        # Same cast the harness makes: an integer column cannot carry the hole
        # the signature says is allowed.
        if str(x_test[column].dtype).startswith("int"):
            x_test[column] = x_test[column].astype("float64")
    y_test = frame[target]
    classes = [str(value) for value in (model.classes_json or [])]
    binary = model.task == "classification" and len(classes) == 2
    positive = None
    if binary:
        # The label as the fitted pipeline spells it, not as JSON stored it.
        for value in getattr(entry.pipeline, "classes_", []):
            if str(value) == classes[-1]:
                positive = value
    return EstimatorReport(
        entry.pipeline,
        X_test=x_test,
        y_test=y_test,
        **({"pos_label": positive} if positive is not None else {}),
    )


def compare(db, *, left: MLModel, right: MLModel) -> dict[str, Any]:
    """The joint metric table for two versions, measured on one test split."""

    if not settings.ml_predict_enabled:
        raise TabularError(
            code="ML_PREDICT_DISABLED",
            message="Model serving is disabled on this deployment.",
            status_code=503,
        )
    _ready(left, side="left")
    _ready(right, side="right")
    families = {str(getattr(side, "family", None) or "tabular") for side in (left, right)}
    if families != {"tabular"}:
        # Re-scoring on one random split is a tabular measurement; a forecast
        # is ranked by its backtest, which the card's recorded scores already
        # compare version to version.
        raise TabularError(
            code="ML_COMPARE_NOT_TABULAR",
            message="Only supervised tabular models can be re-scored on a shared test split.",
            status_code=409,
            details={"families": sorted(families)},
        )
    if left.id == right.id:
        raise TabularError(
            code="ML_COMPARE_SAME_VERSION",
            message="A version cannot be compared with itself.",
            status_code=422,
        )
    if left.workspace_id != right.workspace_id:
        raise TabularError(
            code="ML_COMPARE_CROSS_WORKSPACE",
            message="Two models from different workspaces cannot be compared.",
            status_code=403,
        )
    if left.task != right.task or str(left.target) != str(right.target):
        raise TabularError(
            code="ML_COMPARE_DIFFERENT_QUESTION",
            message=(
                "These versions do not answer the same question, so one table "
                "cannot rank them."
            ),
            status_code=409,
            details={
                "left": {"task": left.task, "target": left.target},
                "right": {"task": right.task, "target": right.target},
            },
        )

    dataset, _ = _pick_dataset(db, left=left, right=right)
    if int(dataset.row_count or 0) > _MAX_ROWS:
        raise TabularError(
            code="ML_COMPARE_DATASET_TOO_LARGE",
            message="This dataset is over the row ceiling allowed for a comparison.",
            status_code=422,
            details={"rows": int(dataset.row_count or 0), "limit": _MAX_ROWS},
        )

    target = str(right.target)
    columns = sorted(set(_features(left)) | set(_features(right)) | {target})
    frame = read_frame(dataset, columns=columns).to_pandas()
    frame = frame.dropna(subset=[target])

    from sklearn.model_selection import train_test_split

    test_size = float(right.test_size or 0.25)
    stratify = frame[target] if right.task == "classification" else None
    try:
        _, holdout = train_test_split(
            frame,
            test_size=test_size,
            random_state=int(settings.ml_train_random_state),
            stratify=stratify,
        )
    except ValueError as exc:
        raise TabularError(
            code="ML_COMPARE_SPLIT_FAILED",
            message="The comparison split could not be rebuilt on this dataset.",
            status_code=409,
            details={"reason": str(exc)[:200]},
        ) from exc

    from skore import ComparisonReport

    names = {
        left.id: f"v{left.version}",
        right.id: f"v{right.version}",
    }
    try:
        reports = {
            names[left.id]: _report(left, holdout, target=target),
            names[right.id]: _report(right, holdout, target=target),
        }
        table = ComparisonReport(reports).metrics.summarize().frame()
    except TabularError:
        raise
    except Exception as exc:  # noqa: BLE001 - one code for "these two do not line up"
        logger.warning(
            "ml_comparison: failed", left=left.id, right=right.id, error=str(exc)[:200]
        )
        raise TabularError(
            code="ML_COMPARE_FAILED",
            message="These two versions could not be scored on the same rows.",
            status_code=409,
            details={"reason": str(exc)[:200]},
        ) from exc

    rows = []
    for metric in table.index:
        if str(metric).endswith("_time"):
            # A predict timing is a property of this machine, not of the model.
            continue
        entry = {"key": str(metric)}
        for model_id, name in names.items():
            if name in table.columns:
                value = table.loc[metric, name]
                entry[model_id] = None if value is None else float(value)
        rows.append(entry)

    warnings: list[dict[str, str]] = []
    for model in (left, right):
        if model.dataset_id and model.dataset_id != dataset.id:
            # Some of these rows may have been in that model's training set, so
            # its column can read better than it would on unseen data.
            warnings.append(
                {"code": "TRAINED_ON_ANOTHER_DATASET", "model_id": model.id}
            )
        elif float(model.test_size or 0.25) != test_size:
            warnings.append({"code": "DIFFERENT_SPLIT_SIZE", "model_id": model.id})

    return {
        "task": right.task,
        "target": target,
        "dataset": {
            "id": dataset.id,
            "name": dataset.name,
            "slug": dataset.slug,
            "version": dataset.version,
        },
        "split": {
            "rows": int(len(holdout)),
            "test_size": test_size,
            "random_state": int(settings.ml_train_random_state),
        },
        "models": [
            {
                "model_id": model.id,
                "column": names[model.id],
                "version": model.version,
                "algo": model.algo,
                "is_champion": bool(model.is_champion),
            }
            for model in (left, right)
        ],
        "metrics": rows,
        "warnings": warnings,
    }


__all__ = ["compare"]
