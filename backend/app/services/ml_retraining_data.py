"""Freeze retraining inputs without turning the original final test into training.

All three modes retain the recorded source holdout. Feedback-only changes the
training population, not the evaluation population. A legacy model without a
verified partition must first be trained with recorded evaluation evidence.
"""

import math
import tempfile
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.models.tabular import TabularDataset
from app.resources.ml_evaluation import fingerprint, read_partition, row_ids
from app.services.ml_feedback import iter_labeled_samples
from app.services.object_store import get_object_store
from app.services.tabular_datasets import (
    TabularError,
    dataset_digest,
    materialize_dataset,
    register_frame,
)


class RetrainingDataPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    mode: Literal["original_plus_feedback", "feedback_only", "latest_dataset_version"] = (
        "original_plus_feedback"
    )
    max_feedback_fraction: float = Field(
        default_factory=lambda: float(
            getattr(settings, "ml_retraining_max_feedback_fraction", 0.25)
        ),
        gt=0,
        le=1,
    )
    feedback_window_days: int | None = Field(default=None, ge=1, le=3650)


def refuse(code, message):
    raise TabularError(code=code, message=message, status_code=409)


def limits():
    return int(getattr(settings, "ml_retraining_max_rows", 100000)), int(
        getattr(settings, "ml_retraining_max_bytes", 32 * 1024**2)
    )


def read_source(dataset, columns):
    import polars as pl

    rows, size = limits()
    if (
        dataset.status != "ready"
        or (dataset.row_count or 0) > rows
        or (dataset.size_bytes or 0) > size
    ):
        refuse(
            "ML_RETRAIN_SOURCE_TOO_LARGE",
            "The source is unavailable or exceeds the retraining budget.",
        )
    names = {value.get("name") for value in dataset.schema_json or []}
    if not set(columns) <= names:
        refuse(
            "ML_RETRAINING_DATA_INCOMPATIBLE", "The source lacks required model inputs or target."
        )
    try:
        with tempfile.TemporaryDirectory(prefix="ml-retraining-") as folder:
            paths = materialize_dataset(dataset, Path(folder), max_bytes=size)
            frame = pl.scan_parquet(paths).select(columns).head(rows + 1).collect()
    except (ValueError, OSError, pl.exceptions.PolarsError):
        refuse(
            "ML_RETRAIN_SOURCE_UNAVAILABLE",
            "The source bytes are unavailable, incompatible or exceed the byte budget.",
        )
    if len(frame) > rows or frame.estimated_size() > size:
        refuse("ML_RETRAIN_SOURCE_TOO_LARGE", "The decoded source exceeds the retraining budget.")
    return frame.to_pandas()


def partition_for(model, dataset, frame):
    from app.services.tabular_ml import evaluation_partition_key

    metadata = (model.metrics_json or {}).get("evaluation") or {}
    key = evaluation_partition_key(model.workspace_id, model.id)
    if metadata.get("status") != "stored" or metadata.get("key") != key:
        refuse(
            "ML_RETRAIN_HOLDOUT_UNVERIFIED",
            "The source model needs its recorded evaluation partition.",
        )
    try:
        with tempfile.TemporaryDirectory(prefix="ml-retrain-partition-") as folder:
            local = get_object_store().copy_to_local(
                key, Path(folder) / "partition.gz", max_bytes=limits()[1]
            )
            partition = read_partition(local.read_bytes(), sha256=metadata["sha256"])
        if (
            partition.get("dataset") != {"id": dataset.id, "version": dataset.version}
            or partition.get("target") != model.target
        ):
            raise ValueError("source mismatch")
        usable = frame.dropna(subset=[model.target])
        if model.task == "regression":
            import pandas as pd

            usable = usable[pd.to_numeric(usable[model.target], errors="coerce").notna()]
        if fingerprint(row_ids(usable, partition["columns"])) != partition["fingerprint"]:
            raise ValueError("source changed")
        return partition, usable
    except (KeyError, ValueError, OSError):
        refuse(
            "ML_RETRAIN_HOLDOUT_UNVERIFIED",
            "The source dataset does not match its recorded evaluation partition.",
        )


def _source_evidence(dataset):
    return {"dataset_id": dataset.id, "version": dataset.version, "sha256": dataset_digest(dataset)}


def materialize(db, *, model, rows, policy, features, created_by=None):
    import pandas as pd
    import polars as pl

    original = (
        db.query(TabularDataset)
        .filter_by(id=model.dataset_id, workspace_id=model.workspace_id)
        .first()
    )
    if original is None:
        refuse("ML_RETRAIN_SOURCE_UNAVAILABLE", "The original dataset is unavailable.")
    evaluation_columns = ((model.metrics_json or {}).get("evaluation") or {}).get("columns") or [
        *features,
        model.target,
    ]
    columns = sorted(set([*features, model.target, *evaluation_columns]))
    original_frame = read_source(original, columns)
    partition, original_frame = partition_for(model, original, original_frame)
    hashes = row_ids(original_frame, partition["columns"])
    clean_test = set(partition["test_ids"]) - set(partition["train_ids"])
    holdout = original_frame.loc[[key in clean_test for key in hashes]].copy()
    if holdout.empty:
        refuse(
            "ML_RETRAIN_HOLDOUT_UNVERIFIED",
            "No independent final-test rows remain in the source partition.",
        )
    # Exclude by feature identity, even when a revised label differs. The same
    # observation cannot become a training example and remain a held-out test.
    held_features = set(row_ids(holdout, sorted(features)))
    excluded_holdout = 0
    mode = policy.mode
    base = original
    if mode == "latest_dataset_version":
        base = (
            db.query(TabularDataset)
            .filter_by(workspace_id=model.workspace_id, slug=original.slug, status="ready")
            .order_by(TabularDataset.version.desc(), TabularDataset.id.desc())
            .first()
        )
    base_frame = read_source(base, columns) if base.id != original.id else original_frame
    base_frame = base_frame.dropna(subset=[model.target])
    base_features = row_ids(base_frame, sorted(features))
    keep = [key not in held_features for key in base_features]
    excluded_holdout += sum(not value for value in keep)
    train = base_frame.loc[keep].copy() if mode != "feedback_only" else base_frame.iloc[:0].copy()
    train = train.loc[
        ~pd.Series(row_ids(train, columns), index=train.index).duplicated()
    ].reset_index(drop=True)
    records, identifiers = [], []
    cutoff = (
        datetime.utcnow() - timedelta(days=policy.feedback_window_days)
        if policy.feedback_window_days
        else None
    )
    for row in rows:
        for value in iter_labeled_samples(row):
            if cutoff and (value["labeled_at"] is None or value["labeled_at"] < cutoff):
                continue
            if not all(name in value["payload"] for name in columns if name != model.target):
                continue
            label = value["label"]
            if model.task == "regression":
                try:
                    label = float(label)
                except (TypeError, ValueError, OverflowError):
                    continue
                if not math.isfinite(label):
                    continue
            records.append(
                {
                    **{name: value["payload"][name] for name in columns if name != model.target},
                    model.target: label,
                }
            )
            identifiers.append(value["sample_id"])
    feedback_count = len(records)
    accepted, ids = [], []
    seen = set(row_ids(train, columns))
    if records and mode != "latest_dataset_version":
        incoming = pd.DataFrame(records, columns=columns)
        # Preserve source target dtype: class labels are transported as strings.
        try:
            for column in columns:
                dtype = original_frame[column].dtype
                if (
                    column in features
                    and pd.api.types.is_numeric_dtype(dtype)
                    and not pd.api.types.is_bool_dtype(dtype)
                ):
                    # A serving contract may accept fractional values for an
                    # originally integer column. Never truncate these to int.
                    incoming[column] = pd.to_numeric(incoming[column], errors="raise")
                else:
                    incoming[column] = incoming[column].astype(dtype)
        except (ValueError, TypeError):
            refuse(
                "ML_RETRAINING_DATA_INCOMPATIBLE",
                "Feedback is incompatible with the source schema.",
            )
        content = row_ids(incoming, columns)
        identities = row_ids(incoming, sorted(features))
        for index, (key, identity) in enumerate(zip(content, identities, strict=True)):
            if identity in held_features:
                excluded_holdout += 1
                continue
            if key in seen:
                continue
            seen.add(key)
            accepted.append(incoming.iloc[index].to_dict())
            ids.append(identifiers[index])
        need = max(int(getattr(settings, "ml_retraining_min_feedback_rows", 40)), 1)
        if len(accepted) < need:
            refuse(
                "ML_RETRAIN_FEEDBACK_INSUFFICIENT",
                f"At least {need} distinct labelled samples outside the final test are required.",
            )
        if mode == "original_plus_feedback" and policy.max_feedback_fraction < 1:
            maximum = int(
                len(train) * policy.max_feedback_fraction / (1 - policy.max_feedback_fraction)
            )
            accepted, ids = accepted[:maximum], ids[:maximum]
        train = pd.concat([train, pd.DataFrame(accepted, columns=columns)], ignore_index=True)
    elif mode != "latest_dataset_version":
        refuse("ML_RETRAIN_FEEDBACK_INSUFFICIENT", "No retained labelled samples are available.")
    if len(train) < int(settings.ml_train_min_rows):
        refuse(
            "ML_RETRAIN_FEEDBACK_INSUFFICIENT",
            "The training population is too small after deduplication and capping.",
        )
    if model.task == "classification":
        counts = Counter(str(value) for value in train[model.target])
        expected = set(str(value) for value in original_frame[model.target])
        if set(counts) != expected or min(counts.values()) < 2:
            refuse(
                "ML_RETRAINING_DATA_INCOMPATIBLE",
                "Every source class needs at least two training samples.",
            )
    combined = pd.concat([train, holdout], ignore_index=True)
    maximum, size = limits()
    frame = pl.from_pandas(combined)
    if len(frame) > maximum or frame.estimated_size() > size:
        refuse("ML_RETRAIN_SOURCE_TOO_LARGE", "The combined dataset exceeds the retraining budget.")
    frozen_partition = {
        "version": 1,
        "source_partition_sha256": model.metrics_json["evaluation"]["sha256"],
        "columns": columns,
        "fingerprint": fingerprint(row_ids(combined, columns)),
        "train_rows": len(train),
        "test_rows": len(holdout),
    }
    evidence = {
        "mode": mode,
        "policy": policy.model_dump(),
        "sources": [_source_evidence(original)],
        "evaluation_sha256": model.metrics_json["evaluation"]["sha256"],
        "holdout_fingerprint": fingerprint(row_ids(holdout, columns)),
        "holdout_rows": len(holdout),
        "train_rows": len(train),
        "feedback_available": feedback_count,
        "feedback_used": len(ids),
        "excluded_holdout": excluded_holdout,
        "sample_ids": ids,
        "feedback_fraction": len(ids) / len(train) if len(train) else 0,
        "class_balance": dict(Counter(str(value) for value in train[model.target]))
        if model.task == "classification"
        else None,
    }
    if base.id != original.id:
        evidence["sources"].append(_source_evidence(base))
    dataset = register_frame(
        db,
        workspace_id=model.workspace_id,
        name=f"{model.name[:150]} · reviewed retraining",
        frame=frame,
        source="generated",
        produced_by="ml_feedback",
        created_by=created_by,
        parent_ids=list(dict.fromkeys([original.id, base.id])),
        lineage={
            "kind": "retraining",
            "model": {"model_id": model.id, "version": model.version},
            "retraining_data": evidence,
            "retraining_partition": frozen_partition,
        },
    )
    return dataset, ids, evidence, frozen_partition


def verify_sources(db, model, evidence):
    for source in evidence.get("sources", []):
        dataset = (
            db.query(TabularDataset)
            .filter_by(id=source["dataset_id"], workspace_id=model.workspace_id)
            .first()
        )
        if (
            dataset is None
            or dataset.status != "ready"
            or dataset.version != source["version"]
            or dataset_digest(dataset) != source["sha256"]
        ):
            refuse(
                "ML_RETRAIN_SOURCE_CHANGED",
                "A reviewed source dataset changed or is no longer available.",
            )
    if ((model.metrics_json or {}).get("evaluation") or {}).get("sha256") != evidence.get(
        "evaluation_sha256"
    ):
        refuse("ML_RETRAIN_SOURCE_CHANGED", "The source evaluation evidence changed.")
