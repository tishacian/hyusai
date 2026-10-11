"""Read-only review suggestions: development evidence never executes a change."""

from __future__ import annotations

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


def review(db, *, model_id: str, workspace_id: str):
    model = get_model(db, model_id=model_id, workspace_id=workspace_id)
    metrics = model.metrics_json or {}
    provenance = metrics.get("evaluation") or {}
    diagnostics = metrics.get("diagnostics") or {}
    supported = (
        model.status == "ready"
        and (model.family or "tabular") == "tabular"
        and provenance.get("schema") == 1
        and provenance.get("status") == "stored"
        and diagnostics.get("schema") == 1
        and diagnostics.get("engine") == "skore"
        and diagnostics.get("role") == "development"
        and diagnostics.get("scope") == "development_base_estimator"
        and diagnostics.get("served_model") is False
        and diagnostics.get("status") == "completed"
    )
    suggestions = []
    if supported:
        for row in (diagnostics.get("checks") or [])[:64]:
            code = row.get("code")
            if row.get("section") not in {"issue", "tip"} or code not in HYPOTHESES:
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
        "training_skill": "ml_train_sklearn_v1",
        "reviewed_retraining_skill": "ml_retrain_model_v1",
        "constraints": [
            "development_only",
            "no_final_test_optimization",
            "no_automatic_training",
            "no_automatic_promotion",
        ],
    }
