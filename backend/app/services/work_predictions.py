"""Explicit display contracts for model advice in Work, independent of a business case.

A probability is tied to its positive class; a cluster is never a confidence or
an ordered priority. Presentation bands are authored rules, not model thresholds.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any


def number(value: Any) -> bool:
    try:
        return (
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        )
    except OverflowError:
        return False


def validate_contract(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("PREDICTION_CONTRACT_INVALID")
    contract = dict(raw)
    task = contract.get("task")
    if (
        type(contract.get("schema_version")) is not int
        or contract.get("schema_version") != 1
        or task not in ("classification", "regression", "clustering")
        or not isinstance(contract.get("model_id"), str)
        or not contract["model_id"].strip()
        or type(contract.get("model_version")) is not int
        or contract["model_version"] < 1
        or not isinstance(contract.get("label"), str)
        or not contract["label"].strip()
        or not isinstance(contract.get("value_column"), str)
        or not contract["value_column"].strip()
        or type(contract.get("max_age_seconds")) is not int
        or not 1 <= contract["max_age_seconds"] <= 604800
        or contract.get("order", "none") not in ("ascending", "descending", "none")
    ):
        raise ValueError("PREDICTION_CONTRACT_INVALID")
    if task != "clustering" and (
        not isinstance(contract.get("target"), str) or not contract["target"].strip()
    ):
        raise ValueError("PREDICTION_TARGET_REQUIRED")
    if task == "classification":
        if not all(
            isinstance(contract.get(key), str) and contract[key]
            for key in ("positive_label", "score_column")
        ):
            raise ValueError("PREDICTION_CLASS_REQUIRED")
        if contract.get("unit") != "probability":
            raise ValueError("PREDICTION_PROBABILITY_UNIT_REQUIRED")
    elif contract.get("positive_label") or contract.get("score_column"):
        raise ValueError("PREDICTION_SCORE_NOT_APPLICABLE")
    if task == "clustering" and (
        contract.get("bands")
        or contract.get("order", "none") != "none"
        or contract.get("unit") != "segment"
    ):
        raise ValueError("PREDICTION_SEGMENT_NOT_ORDERED")
    if task == "regression" and (not isinstance(contract.get("unit"), str) or not contract["unit"]):
        raise ValueError("PREDICTION_UNIT_REQUIRED")
    low, high = contract.get("lower_column"), contract.get("upper_column")
    if (
        any(value is not None and (not isinstance(value, str)) for value in (low, high))
        or bool(low) != bool(high)
        or ((low or high) and task != "regression")
    ):
        raise ValueError("PREDICTION_INTERVAL_INVALID")
    bands = contract.get("bands", [])
    if not isinstance(bands, list) or len(bands) > 12:
        raise ValueError("PREDICTION_BANDS_INVALID")
    seen_keys, seen_limits = set(), set()
    for band in bands:
        if (
            not isinstance(band, dict)
            or not all(isinstance(band.get(k), str) and band[k] for k in ("key", "label"))
            or not number(band.get("min"))
        ):
            raise ValueError("PREDICTION_BANDS_INVALID")
        if (
            band["key"] in seen_keys
            or band["min"] in seen_limits
            or (task == "classification" and not 0 <= band["min"] <= 1)
        ):
            raise ValueError("PREDICTION_BANDS_INVALID")
        seen_keys.add(band["key"])
        seen_limits.add(band["min"])
    return contract


def validate_model(model, contract: dict) -> None:
    contract = validate_contract(contract)
    if (
        model.id != contract["model_id"]
        or model.version != contract["model_version"]
        or model.task != contract["task"]
        or (model.task != "clustering" and model.target != contract["target"])
        or (
            model.task == "classification"
            and contract["positive_label"] not in [str(c) for c in (model.classes_json or [])]
        )
    ):
        raise ValueError("PREDICTION_MODEL_MISMATCH")


def validate_dataset_contract(dataset, model, contract: dict) -> None:
    """Distinguish generated predictions from identically named input columns."""
    validate_model(model, contract)
    lineage = dataset.lineage_json if isinstance(dataset.lineage_json, dict) else {}
    pinned = lineage.get("model") if isinstance(lineage.get("model"), dict) else {}
    if pinned.get("model_id") != model.id or pinned.get("version") != model.version:
        raise ValueError("PREDICTION_MODEL_MISMATCH")
    added = lineage.get("added_columns")
    if not isinstance(added, list) or not all(isinstance(name, str) for name in added):
        raise ValueError("PREDICTION_COLUMN_PROVENANCE_MISMATCH")
    output = lineage.get("prediction_output")
    if not isinstance(output, dict):
        # Older scoring artifacts have names and model evidence but no column map.
        classes = [str(value) for value in (model.classes_json or [])]
        metrics = model.metrics_json if isinstance(model.metrics_json, dict) else {}
        target = metrics.get("target") if isinstance(metrics.get("target"), dict) else {}
        positive = target.get("positive")
        if positive not in classes:
            positive = classes[-1] if len(classes) == 2 else None
        output = {
            "task": model.task,
            "target": model.target,
            "positive_label": positive,
            "value_column": "prediction",
            "score_column": f"score_{positive}",
            "lower_column": f"{model.target}_lower",
            "upper_column": f"{model.target}_upper",
        }
    if (
        output.get("task") != contract["task"]
        or (model.task != "clustering" and output.get("target") != contract["target"])
        or (
            model.task == "classification"
            and output.get("positive_label") != contract["positive_label"]
        )
    ):
        raise ValueError("PREDICTION_SEMANTICS_MISMATCH")
    keys = ["value_column"]
    if model.task == "classification":
        keys.append("score_column")
    if contract.get("lower_column"):
        keys.extend(["lower_column", "upper_column"])
    if any(contract.get(key) not in added or contract.get(key) != output.get(key) for key in keys):
        raise ValueError("PREDICTION_COLUMN_PROVENANCE_MISMATCH")


def band_for(value: float, contract: dict) -> dict | None:
    eligible = [b for b in contract.get("bands", []) if value >= b["min"]]
    return max(eligible, key=lambda b: b["min"]) if eligible else None


def project_row(
    row: dict,
    contract: dict,
    *,
    captured_at: datetime,
    provenance: dict,
    now: datetime | None = None,
) -> dict:
    """Project an already-authorized row; this function never fetches or infers data."""
    contract = validate_contract(contract)
    task = contract["task"]
    value = row.get(contract["value_column"])
    score = None
    if task == "classification":
        score = row.get(contract["score_column"])
        if not number(score) or not 0 <= score <= 1:
            raise ValueError("PREDICTION_SCORE_INVALID")
        if value is not None and not (isinstance(value, str) or number(value)):
            raise ValueError("PREDICTION_VALUE_INVALID")
    elif task == "regression":
        if not number(value):
            raise ValueError("PREDICTION_VALUE_INVALID")
    elif value is None or isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("PREDICTION_SEGMENT_INVALID")
    interval = None
    if contract.get("lower_column"):
        low, high = row.get(contract["lower_column"]), row.get(contract["upper_column"])
        if not number(low) or not number(high) or not low <= value <= high:
            raise ValueError("PREDICTION_INTERVAL_INVALID")
        interval = {"lower": low, "upper": high}
    captured = (
        captured_at.replace(tzinfo=UTC)
        if captured_at.tzinfo is None
        else captured_at.astimezone(UTC)
    )
    age = ((now or datetime.now(UTC)) - captured).total_seconds()
    fresh = 0 <= age <= contract["max_age_seconds"]
    band = (
        band_for(score if task == "classification" else value, contract)
        if task != "clustering"
        else None
    )
    return {
        "schema_version": 1,
        "status": "ready" if fresh else "stale",
        "task": task,
        "target": contract.get("target"),
        "positive_label": contract.get("positive_label"),
        "model": {"id": contract["model_id"], "version": contract["model_version"]},
        "label": contract["label"],
        "unit": contract["unit"],
        "value": value if fresh else None,
        "score": score if fresh else None,
        "interval": interval if fresh else None,
        "band": band if fresh else None,
        "captured_at": captured.isoformat(),
        "provenance": provenance,
    }


def configuration_issues(pages: dict) -> list[dict]:
    """Publication gate only: editors may save incomplete drafts."""
    issues = []
    for page in pages.get("pages") or []:
        if not isinstance(page, dict):
            continue
        for component in page.get("components") or []:
            if not isinstance(component, dict) or component.get("type") != "prediction":
                continue
            props = component.get("props") or {}
            try:
                validate_contract(props.get("predictionContract"))
                if not props.get("dataBinding") and not props.get("queryBinding"):
                    raise ValueError("PREDICTION_BINDING_REQUIRED")
            except (ValueError, TypeError, AttributeError) as exc:
                issues.append(
                    {
                        "code": "PREDICTION_CONFIGURATION_INVALID",
                        "message": "Configure a model prediction contract and an authorized runtime data binding.",
                        "page_id": page.get("id"),
                        "component_id": component.get("id"),
                        "detail": str(exc),
                    }
                )
    return issues
