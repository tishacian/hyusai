"""Held-out teacher/student evidence; no fitting and no provider calls."""
from __future__ import annotations

import hashlib
import json
import math


def snapshot(provenance: dict) -> dict:
    """Freeze the review contract without exposing per-row labels in model APIs."""
    labels = provenance.get("teacher_labels")
    if (not isinstance(labels, list) or not labels
            or any(not isinstance(label, str) or not label for label in labels)):
        raise ValueError("Distillation requires the original teacher labels.")
    result = {key: value for key, value in provenance.items() if key != "teacher_labels"}
    result["teacher_labels_sha256"] = hashlib.sha256(
        json.dumps(labels, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return result


def validate(provenance: dict, *, rows: int, target: str, task: str) -> None:
    snapshot(provenance)
    if task != "classification" or provenance.get("label_column") != target:
        raise ValueError("Distillation must predict the reviewed classification target.")
    if (provenance.get("version") != 1
            or len(provenance["teacher_labels"]) != rows
            or provenance.get("rows_reviewed") != rows):
        raise ValueError("Distillation labels must cover the complete reviewed dataset.")


def _cost(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def evaluate(provenance: dict, *, indices, predicted, reviewed, inference_cost=None) -> dict:
    """Compare all three label vectors on the very same untouched test rows."""
    positions = list(indices)
    predictions, truth = list(predicted), list(reviewed)
    labels = provenance["teacher_labels"]
    if (not positions or len(positions) != len(predictions) or len(positions) != len(truth)
            or any(int(index) != index or not 0 <= index < len(labels) for index in positions)):
        raise ValueError("Distillation test rows are not aligned with the original labels.")
    teacher = [labels[int(index)] for index in positions]
    count = len(positions)
    llm_rows = provenance.get("llm_labeled_rows")
    llm_cost = _cost(provenance.get("llm_estimated_cost_usd"))
    llm_per_1000 = (
        llm_cost * 1000 / llm_rows
        if llm_cost is not None and isinstance(llm_rows, int) and not isinstance(llm_rows, bool) and llm_rows > 0
        else None
    )
    declared = _cost(inference_cost)
    return {
        "version": 1,
        "evaluation": "held_out",
        "test_rows": count,
        "rows_reviewed": provenance["rows_reviewed"],
        "corrected_rows": provenance["corrected_rows"],
        "agreement": sum(bool(a == b) for a, b in zip(predictions, teacher)) / count,
        "reviewed_accuracy": sum(bool(a == b) for a, b in zip(predictions, truth)) / count,
        "teacher_accuracy_on_reviewed": sum(bool(a == b) for a, b in zip(teacher, truth)) / count,
        **{key: provenance[key] for key in (
            "source_dataset_id", "source_version", "reviewed_dataset_id", "decision_id", "teacher_model"
        )},
        "llm_estimated_cost_per_1000": llm_per_1000,
        "llm_cost_basis": "declared_tariff",
        "llm_labeled_rows": llm_rows,
        "unknown_attempts": provenance.get("unknown_attempts", 0),
        "inference_cost_per_1000": declared,
        "inference_cost_basis": "declared" if declared is not None else "unavailable",
    }
