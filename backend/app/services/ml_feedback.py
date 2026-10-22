"""Resolve labels using a server-owned prediction/sample association.

Historical single-row labels remain meaningful. Historical batch labels do not
identify a row and are deliberately excluded from statistics and training.
"""

import hashlib
import math
from datetime import datetime

from sqlalchemy.orm import object_session

from app.models.ml_feedback import MLPredictionFeedback
from app.models.tabular import MLPrediction
from app.services.tabular_datasets import TabularError


def refuse(code, message, status=422):
    raise TabularError(code=code, message=message, status_code=status)


def sample_id(row, index):
    return hashlib.sha256(f"agentium-ml-sample-v1:{row.id}:{index}".encode()).hexdigest()


def persisted_samples(row):
    if not getattr(row, "input_storage_allowed", True):
        return []
    payloads = row.payload_json if isinstance(row.payload_json, list) else []
    outputs = row.output_json if isinstance(row.output_json, list) else []
    scores = (row.scores_json or {}).get("scores") or []
    result = []
    for index, payload in enumerate(payloads[: max(0, int(row.row_count or 0))]):
        if not isinstance(payload, dict):
            continue
        output = outputs[index] if index < len(outputs) and isinstance(outputs[index], dict) else {}
        result.append(
            {
                "sample_id": sample_id(row, index),
                "index": index,
                "payload": payload,
                "output": output,
                "score": output.get("score", scores[index] if index < len(scores) else None),
            }
        )
    return result


def iter_labeled_samples(row):
    samples = persisted_samples(row)
    db = object_session(row)
    feedback = (
        {
            value.sample_index: value
            for value in row.feedback_samples
            if value.prediction_id == row.id and value.workspace_id == row.workspace_id
        }
        if db is not None
        else {}
    )
    for sample in samples:
        item = feedback.get(sample["index"])
        if item:
            yield {**sample, "label": item.label, "labeled_at": item.labeled_at}
        elif row.row_count == 1 and row.label is not None:
            yield {**sample, "label": row.label, "labeled_at": row.labeled_at}


def attach(db, *, model, prediction_id, label, labeled_by=None, sample_id=None):
    row = (
        db.query(MLPrediction)
        .filter_by(id=prediction_id, workspace_id=model.workspace_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    if row is None:
        refuse("ML_PREDICTION_NOT_FOUND", "That prediction is not in this workspace.", 404)
    if row.evaluation_campaign_id is not None:
        refuse(
            "ML_EVALUATION_FEEDBACK_SEPARATE", "Campaign samples are not production outcomes.", 409
        )
    if row.slug != model.slug:
        refuse("ML_PREDICTION_WRONG_MODEL", "That prediction belongs to another model.", 409)
    if not getattr(row, "input_storage_allowed", True) or not row.payload_json:
        refuse("ML_FEEDBACK_NOT_STORED", "Feedback requires a persisted input sample.", 409)
    samples = persisted_samples(row)
    if sample_id is None:
        if row.row_count != 1:
            refuse("ML_FEEDBACK_SAMPLE_REQUIRED", "Select the individual sample being labelled.")
        selected = samples[0] if samples else None
    else:
        selected = next((value for value in samples if value["sample_id"] == sample_id), None)
    if selected is None:
        refuse("ML_FEEDBACK_SAMPLE_INVALID", "The sample is not retained in this prediction.")
    if model.task == "regression":
        try:
            number = float(label) if not isinstance(label, bool) else float("nan")
        except (TypeError, ValueError, OverflowError):
            number = float("nan")
        if not math.isfinite(number):
            refuse("ML_FEEDBACK_NOT_NUMERIC", "Regression ground truth must be a finite number.")
        text = str(number)
    else:
        text = str(label).strip() if label is not None else ""
    if not text or len(text) > 200:
        refuse("ML_FEEDBACK_LABEL_MISSING", "A label of at most 200 characters is required.")
    now = datetime.utcnow()
    item = db.get(MLPredictionFeedback, selected["sample_id"])
    if item is None:
        item = MLPredictionFeedback(
            sample_id=selected["sample_id"],
            prediction_id=row.id,
            workspace_id=row.workspace_id,
            sample_index=selected["index"],
        )
        db.add(item)
    item.label, item.labeled_by, item.labeled_at = text, labeled_by, now
    # Existing single-row callers retain their response. Never assign a batch
    # label that could later be mistaken for labels on its other samples.
    if row.row_count == 1:
        row.label, row.labeled_by = text, labeled_by
    row.labeled_at = now
    db.commit()
    return row


def samples_metadata(row):
    labeled = {value["sample_id"]: value for value in iter_labeled_samples(row)}
    return [
        {
            "sample_id": value["sample_id"],
            "index": value["index"],
            "label": labeled.get(value["sample_id"], {}).get("label"),
            "labeled_at": labeled[value["sample_id"]]["labeled_at"].isoformat()
            if value["sample_id"] in labeled and labeled[value["sample_id"]]["labeled_at"]
            else None,
        }
        for value in persisted_samples(row)
    ]
