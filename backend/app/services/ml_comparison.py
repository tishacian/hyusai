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

New models carry a recorded partition: compare the intersection of their test
rows, excluding every row content seen in either training partition. Changed
datasets or incomplete proofs are refused. Legacy pairs retain reconstructed
splits with an explicit unverified warning; they cannot prove absence of leakage.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.models.tabular import MLModel, TabularDataset
from app.resources.ml_skore_adapter import comparison_metrics
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


def _pick_dataset(db, *, left: MLModel, right: MLModel) -> tuple[TabularDataset, list[str]]:
    """The dataset that can host both models, and the columns it would be missing.

    Prefers the *right* (newer) model's dataset, because the split is
    reconstructed from that model's knobs and reproducing its own test rows is
    the closest thing to a fair reading available.
    """

    wanted = set(_features(left)) | set(_features(right)) | {str(right.target)}
    for model in (left, right):
        wanted.update(((model.metrics_json or {}).get("evaluation") or {}).get("columns") or [])
    shortfall: list[str] = []
    for candidate_id in (right.dataset_id, left.dataset_id):
        if not candidate_id:
            continue
        dataset = db.query(TabularDataset).filter(TabularDataset.id == candidate_id).first()
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
        from app.resources.ml_classification_extensions import label_name

        selected = ((model.metrics_json or {}).get("metric_semantics") or {}).get(
            "positive_class", classes[-1]
        )
        # The label as the fitted pipeline spells it, not as JSON stored it.
        matching = [
            value
            for value in getattr(entry.pipeline, "classes_", [])
            if label_name(value) == selected or str(value)[:120] == selected
        ]
        if len(matching) != 1:
            raise ValueError("Stored positive class is absent from the fitted model")
        positive = matching[0]
    return EstimatorReport(
        entry.pipeline,
        X_test=x_test,
        y_test=y_test,
        **({"pos_label": positive} if positive is not None else {}),
    )


def _comparison_frame(dataset, columns, *, recorded):
    if not recorded:
        return read_frame(dataset, columns=columns).to_pandas()
    # Same Parquet reader as training, preserving date/nullable cell semantics.
    import tempfile
    from pathlib import Path

    import pandas as pd

    from app.services.tabular_datasets import materialize

    with tempfile.TemporaryDirectory(prefix="ml-comparison-") as scratch:
        path = materialize(dataset, Path(scratch) / "dataset.parquet")
        return pd.read_parquet(path, columns=columns).reset_index(drop=True)


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
                "These versions do not answer the same question, so one table cannot rank them."
            ),
            status_code=409,
            details={
                "left": {"task": left.task, "target": left.target},
                "right": {"task": right.task, "target": right.target},
            },
        )

    positives = [
        (
            ((model.metrics_json or {}).get("metric_semantics") or {}).get(
                "positive_class", (model.classes_json or [None])[-1]
            )
            if len(model.classes_json or []) == 2
            else None
        )
        for model in (left, right)
    ]
    if left.task == "classification" and positives[0] != positives[1]:
        raise TabularError(
            code="ML_COMPARE_DIFFERENT_POSITIVE_CLASS",
            message="These models use different positive classes.",
            status_code=409,
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
    columns = sorted(
        set(columns)
        | {
            column
            for model in (left, right)
            for column in ((model.metrics_json or {}).get("evaluation") or {}).get("columns", [])
        }
    )
    evidence = [(model.metrics_json or {}).get("evaluation") for model in (left, right)]
    frame = _comparison_frame(dataset, columns, recorded=any(evidence))
    frame = frame.dropna(subset=[target])
    if right.task == "regression":
        import pandas as pd

        frame = frame[pd.to_numeric(frame[target], errors="coerce").notna()]

    verified = False
    partitions = []
    if any(evidence):
        from app.resources.ml_evaluation import read_partition, shared_holdout
        from app.services.object_store import get_object_store
        from app.services.tabular_ml import evaluation_partition_key

        try:
            for model, metadata in zip((left, right), evidence, strict=True):
                expected = evaluation_partition_key(model.workspace_id, model.id)
                if (
                    not metadata
                    or metadata.get("status") != "stored"
                    or metadata.get("key") != expected
                ):
                    raise ValueError("A model lacks its recorded evaluation partition")
                partition = read_partition(
                    get_object_store().read_bytes(expected), sha256=metadata["sha256"]
                )
                source = partition.get("dataset") or {}
                if (
                    source.get("id") != dataset.id
                    or source.get("id") != model.dataset_id
                    or source.get("version") != dataset.version
                    or partition.get("target") != target
                ):
                    raise ValueError("Partitions refer to different dataset versions or targets")
                partitions.append(partition)
            holdout = shared_holdout(frame, partitions)
            verified = True
        except Exception as exc:
            raise TabularError(
                code="ML_COMPARE_UNVERIFIED_PARTITION",
                message="The recorded partitions cannot prove a shared unseen test set.",
                status_code=409,
                details={"reason": str(exc)[:200]},
            ) from exc

    from sklearn.model_selection import train_test_split

    test_size = float(right.test_size or 0.25)
    stratify = frame[target] if right.task == "classification" else None
    if not verified:
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
        rows = comparison_metrics(ComparisonReport(reports).metrics.summarize(), names=names)
    except TabularError:
        raise
    except Exception as exc:  # noqa: BLE001 - one code for "these two do not line up"
        logger.warning("ml_comparison: failed", left=left.id, right=right.id, error=str(exc)[:200])
        raise TabularError(
            code="ML_COMPARE_FAILED",
            message="These two versions could not be scored on the same rows.",
            status_code=409,
            details={"reason": str(exc)[:200]},
        ) from exc

    warnings: list[dict[str, str]] = []
    if not verified:
        warnings.append({"code": "LEGACY_PARTITION_UNVERIFIED"})
    for model in (left, right):
        if model.dataset_id and model.dataset_id != dataset.id:
            # Some of these rows may have been in that model's training set, so
            # its column can read better than it would on unseen data.
            warnings.append({"code": "TRAINED_ON_ANOTHER_DATASET", "model_id": model.id})
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
            "random_state": (
                partitions[0]["random_state"]
                if verified and partitions[0]["random_state"] == partitions[1]["random_state"]
                else None
                if verified
                else int(settings.ml_train_random_state)
            ),
            "recorded_seeds": [part["random_state"] for part in partitions],
            "verified": verified,
            "strategy": "recorded_unseen_intersection" if verified else "legacy_reconstructed",
            "role": "final_test",
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
