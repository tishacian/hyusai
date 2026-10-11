"""Read-only review suggestions: development evidence never executes a change."""

from __future__ import annotations

import math

from app.services.tabular_ml import get_model

# A code selects a hypothesis to review, never a score to optimize on final test.
HYPOTHESES = {
    "SKD001": "regularization",
    "SKD002": "capacity",
    "SKD004": "class_balance",
    "SKD008": "correlated_features",
    "SKD012": "feature_selection",
    "SKD013": "temporal_split",
    "SKD016": "estimator_settings",
}


def _number(value):
    try:
        return value if type(value) in {int, float} and math.isfinite(value) else None
    except OverflowError:
        return None


def _rows(value, limit):
    return value[:limit] if isinstance(value, list) else []


def _development_evidence(metrics, *, qualified):
    """The persisted CV contract uses development rows; never read scores/primary.

    Profile distributions and final-test curves are deliberately absent. Names
    and structural preprocessing facts are already authorized model metadata.
    """
    result = {
        "status": "insufficient_evidence",
        "role": "development",
        "cv": None,
        "preprocessing": None,
    }
    if not qualified:
        return result
    cv = metrics.get("cv")
    if isinstance(cv, dict) and cv.get("role") in (None, "development") and not cv.get("error"):
        folds = cv.get("folds")
        rows = []
        for row in _rows(cv.get("metrics"), 32):
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("key"), str)
                or row.get("key")
                not in {
                    "accuracy",
                    "balanced_accuracy",
                    "roc_auc",
                    "f1",
                    "precision",
                    "recall",
                    "log_loss",
                    "brier_score",
                    "r2",
                    "mae",
                    "rmse",
                    "mape",
                }
            ):
                continue
            if _number(row.get("mean")) is not None:
                rows.append(
                    {
                        "key": row["key"],
                        "mean": _number(row["mean"]),
                        "std": _number(row.get("std")),
                    }
                )
        if type(folds) is int and 2 <= folds <= 10 and rows:
            result["cv"] = {"folds": folds, "metrics": rows}
            result["status"] = "available"
    preprocessing = metrics.get("preprocessing")
    if (
        isinstance(preprocessing, dict)
        and preprocessing.get("schema") == 1
        and preprocessing.get("status") == "available"
        and preprocessing.get("learning_scope") == "training_folds"
    ):
        columns = []
        for row in _rows(preprocessing.get("columns"), 32):
            if not isinstance(row, dict):
                continue
            columns.append(
                {
                    "name": str(row.get("name") or "")[:160],
                    "kind": str(row.get("kind") or "")[:40],
                    "transformers": [str(item)[:160] for item in _rows(row.get("transformers"), 8)],
                    "output_count": _number(row.get("output_count")),
                    "excluded": row.get("excluded") is True,
                    "reason": str(row.get("reason") or "")[:80],
                }
            )
        result["preprocessing"] = {
            "schema": 1,
            "learning_scope": "training_folds",
            "columns": columns,
            "input_count": _number(preprocessing.get("input_count")),
            "output_count": _number(preprocessing.get("output_count")),
            "truncated": bool(preprocessing.get("truncated"))
            or len(_rows(preprocessing.get("columns"), 33)) > 32,
        }
    return result


def review(db, *, model_id: str, workspace_id: str):
    from app.services.ml_methodology import require_enabled

    require_enabled()
    model = get_model(db, model_id=model_id, workspace_id=workspace_id)
    metrics = model.metrics_json if isinstance(model.metrics_json, dict) else {}
    provenance = metrics.get("evaluation") if isinstance(metrics.get("evaluation"), dict) else {}
    diagnostics = metrics.get("diagnostics") if isinstance(metrics.get("diagnostics"), dict) else {}
    qualified = (
        model.status == "ready"
        and (model.family or "tabular") == "tabular"
        and provenance.get("schema") == 1
        and provenance.get("status") == "stored"
    )
    supported = (
        qualified
        and diagnostics.get("schema") == 1
        and diagnostics.get("engine") == "skore"
        and diagnostics.get("role") == "development"
        and diagnostics.get("scope") == "development_base_estimator"
        and diagnostics.get("served_model") is False
        and diagnostics.get("status") == "completed"
    )
    suggestions = []
    if supported:
        for row in _rows(diagnostics.get("checks"), 64):
            if not isinstance(row, dict):
                continue
            code = row.get("code")
            if (
                row.get("section") not in ("issue", "tip")
                or not isinstance(code, str)
                or code not in HYPOTHESES
            ):
                continue
            suggestions.append(
                {
                    "code": code,
                    "hypothesis": HYPOTHESES[code],
                    "evidence_anchor": f"evaluation-check-{code}",
                    "scope": "development_base_estimator",
                    "dataset": provenance.get("dataset"),
                    "requires": [
                        "review_flow_plan",
                        "explicit_training",
                        "independent_evaluation",
                        "explicit_promotion",
                    ],
                }
            )
    return {
        "schema": 1,
        "model_id": model.id,
        "mode": "proposal_only",
        "status": "available" if supported else "insufficient_evidence",
        "proposals": suggestions,
        "development": _development_evidence(metrics, qualified=qualified),
        "training_skill": "ml_train_sklearn_v1",
        "reviewed_retraining_skill": "ml_retrain_model_v1",
        "constraints": [
            "development_only",
            "no_final_test_optimization",
            "no_automatic_training",
            "no_automatic_promotion",
        ],
    }
