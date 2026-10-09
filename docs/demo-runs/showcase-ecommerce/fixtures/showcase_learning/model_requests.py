"""Public API training payloads, without submitting jobs or promoting versions."""

from __future__ import annotations

import argparse
import json
from datetime import date

from generate import FEATURES, NUMERIC_FEATURES


def training_requests(
    *,
    sla_dataset_id: str,
    volume_dataset_id: str,
    regression_dataset_id: str,
    segmentation_dataset_id: str,
    sla_model_name: str = "Luma — Risque de résolution >72h",
    anchor: str = "2026-10-09",
) -> dict:
    date.fromisoformat(anchor)
    description = (
        f"Données synthétiques Luma, ancrage {anchor}. Labels générés, non revus par un humain. "
        "Les métriques ne sont pas une performance métier observée ni un ROI réalisé."
    )
    supervised = {
        "features": FEATURES,
        "algo": "linear",
        "knobs": {"alpha": 1, "max_iter": 1000},
        "test_size": 0.25,
        "cross_validation": 3,
        "description": description,
    }
    sla = {
        **supervised,
        "dataset_id": sla_dataset_id,
        "name": sla_model_name,
        "task": "classification",
        "target": "resolution_over_72h",
        "spec": {
            "calibration": "sigmoid",
            "threshold": "youden",
            "explain": "pack",
            "fairness_columns": ["language"],
        },
    }
    forecast_spec = {
        "time_column": "observed_at",
        "shape": "single",
        "horizon": 28,
        "frequency": "D",
        "backtest_folds": 3,
        "fill": "refuse",
        "interval_level": 0.8,
    }
    forecast = {
        "dataset_id": volume_dataset_id,
        "task": "forecasting",
        "target": "claim_count",
        "features": [],
        "description": description,
    }
    return {
        "sla_calibrated": sla,
        "sla_challenger_tuned": {
            **sla,
            "spec": {
                **sla["spec"],
                "tuning": "budget",
                "tuning_trials": 5,
                "tuning_budget_s": 60,
            },
        },
        "resolution_duration": {
            **supervised,
            "dataset_id": regression_dataset_id,
            "name": "Luma — Durée calendaire de résolution",
            "task": "regression",
            "target": "resolution_hours",
            "spec": {"intervals": "conformal"},
        },
        "numeric_segments": {
            "dataset_id": segmentation_dataset_id,
            "name": "Luma — Profils numériques SAV",
            "task": "clustering",
            "target": "",
            "features": NUMERIC_FEATURES,
            "algo": "kmeans",
            "knobs": {"n_clusters": 4, "max_iter": 300},
            "cross_validation": 0,
            "spec": {},
            "description": description,
        },
        "volume_seasonal_naive": {
            **forecast,
            "name": "Luma — Charge SAV · naïf saisonnier",
            "algo": "seasonal_naive",
            "spec": {**forecast_spec, "calendar": False},
        },
        "volume_classical": {
            **forecast,
            "name": "Luma — Charge SAV · classique",
            "algo": "linear",
            "knobs": {"alpha": 1},
            "spec": {**forecast_spec, "calendar": False, "lags": [1, 2, 7, 14, 28, 56]},
        },
        "volume_chronos": {
            **forecast,
            "name": "Luma — Charge SAV · Chronos",
            "algo": "chronos_zero_shot",
            "spec": forecast_spec,
        },
    }


def reviewed_text_requests(dataset_id: str, target: str = "label") -> dict:
    """Only call after the canonical human review produced this dataset."""
    common = {
        "dataset_id": dataset_id,
        "task": "classification",
        "target": target,
        "features": ["initial_message"],
        "algo": "linear",
        "knobs": {"alpha": 1, "max_iter": 1000},
        "test_size": 0.25,
        "cross_validation": 0,
        "description": "Messages synthétiques Luma ; dataset issu de la revue humaine canonique. Vérifier sa provenance avant le fit.",
    }
    return {
        "reviewed_text_classical": {
            **common,
            "name": "Luma — Qualification de demande · texte",
            "spec": {"text_encoder": "minhash"},
        },
        "reviewed_text_minilm": {
            **common,
            "name": "Luma — Qualification de demande · MiniLM",
            "spec": {
                "text_encoder": "embedding",
                "embedding_columns": ["initial_message"],
                "embedding_components": 30,
            },
        },
    }


def plan_body(request: dict) -> dict:
    """/plan has a smaller schema than POST /ml-models; never send extra keys."""
    return {
        key: value
        for key, value in request.items()
        if key
        in {
            "dataset_id",
            "dataset_slug",
            "target",
            "task",
            "features",
            "algo",
            "knobs",
            "spec",
        }
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("sla", "volume", "regression", "segmentation"):
        parser.add_argument(f"--{key}-dataset-id", required=True)
    parser.add_argument("--sla-model-name", default="Luma — Risque de résolution >72h")
    parser.add_argument(
        "--anchor",
        default="2026-10-09",
        help="Must match the imported dataset manifest",
    )
    args = parser.parse_args()
    requests = training_requests(**vars(args))
    print(
        json.dumps(
            {
                name: {"plan": plan_body(body), "train": body}
                for name, body in requests.items()
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
