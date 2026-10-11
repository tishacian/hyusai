"""Assemble a reviewable activation plan from authenticated read-only snapshots.

No requests, database connections or activation. Run with PYTHONPATH=backend
and DATABASE_URL=sqlite:///:memory: to load the product's pure validators.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflow_configuration import build_configuration

ROOT = Path(__file__).resolve().parent
MODELS = {
    "sla_calibrated": ("Priorité SLA calibrée", "Calibrated SLA priority"),
    "sla_challenger_tuned": (
        "Challenger SLA — recherche bornée",
        "SLA challenger — bounded tuning",
    ),
    "resolution_duration": (
        "Durée calendaire et intervalles",
        "Calendar duration and intervals",
    ),
    "numeric_segments": ("Profils numériques des dossiers", "Numeric case profiles"),
    "volume_seasonal_naive": (
        "Charge — référence saisonnière",
        "Workload — seasonal baseline",
    ),
    "volume_classical": ("Charge — modèle classique", "Workload — classical model"),
    "volume_chronos": ("Charge — Chronos figé", "Workload — frozen Chronos"),
}


def snapshot(directory, name):
    record = json.loads((directory / f"{name}.json").read_text())
    if record.get("status") != 200:
        raise ValueError(f"Successful read-only snapshot required: {name}")
    return record["body"]


def build_plan(directory: Path) -> tuple[dict, dict]:
    # Product imports here keep the fixture module importable without an app
    # runtime. These validators do not query or mutate a database.
    from app.services.chains.dag_validator import validate_flow
    from app.services.ecommerce_composition import compose
    from app.services.ecommerce_composition_upgrade import work_pages
    from app.services.ecommerce_flow_sources import (
        reviewed_source_base,
        with_data_sources,
    )
    from app.services.ecommerce_triage import get_prediction_contract
    from app.services.experience.lifecycle import validate_pages_document
    from app.services.run_engine.execution_contract import canonical_flow_sha256

    plan = json.loads((ROOT.parent / "dataops/live_composition_plan.json").read_text())
    flow = snapshot(directory, "flow-before")
    work = snapshot(directory, "work-before")
    if flow["system_id"] != plan["system_id"]:
        raise ValueError("Snapshot belongs to a different business System")
    loaded = {key: snapshot(directory, f"model-{key}")["model"] for key in MODELS}
    if any(model["status"] != "ready" for model in loaded.values()):
        raise ValueError("Every linked model must be ready in the snapshot")
    sla, forecast = loaded["sla_calibrated"], loaded["volume_chronos"]
    if sla["task"] != "classification" or forecast["task"] != "forecasting":
        raise ValueError("Unexpected task for the pinned SLA or forecast model")
    contract = get_prediction_contract(
        {"model_id": sla["id"], "model_version": sla["version"]}
    )
    base = reviewed_source_base(
        flow["published"]["flow_definition"], flow["draft"]["flow_definition"]
    )
    collections = [
        node["config"]["collection_slug"]
        for node in base["nodes"]
        if node.get("type") == "source.collection"
    ]
    composed = compose(
        with_data_sources(base, collections),
        sla["id"],
        sla["version"],
        model_slug=sla["slug"],
    )
    models = [
        {
            "id": model["id"],
            "label_fr": MODELS[key][0],
            "label_en": MODELS[key][1],
            "description_fr": f"Version {model['version']} · données synthétiques",
            "description_en": f"Version {model['version']} · synthetic data",
        }
        for key, model in loaded.items()
    ]
    configuration = build_configuration(
        composed,
        work_pages(work["release"]["pages"]),
        forecast["id"],
        forecast["slug"],
        forecast["version"],
        forecast["dataset_id"],
        contract,
        models,
    )
    pages = configuration["pages"]
    title = {
        "$i18n": "luma_learning_case_prediction",
        "fallback": "Conseil de priorité du modèle",
    }
    pages["i18n"]["fr"][title["$i18n"]] = title["fallback"]
    pages["i18n"]["en"][title["$i18n"]] = "Model priority advice"
    dossier = next(page for page in pages["pages"] if page["id"] == "dossier")
    insertion = (
        next(
            index
            for index, node in enumerate(dossier["components"])
            if node["id"] == "state"
        )
        + 1
    )
    dossier["components"].insert(
        insertion,
        {
            "id": "case_prediction",
            "type": "prediction",
            "props": {
                "title": title,
                "density": "compact",
                "predictionContract": contract,
                "dataBinding": {
                    "source": "run-output",
                    "componentId": "investigation",
                    "nodeId": "sav.context",
                    "selector": "model_advice",
                },
            },
        },
    )
    plan.update(
        {
            "expected_flow_sha256": flow["published"]["flow_sha256"],
            "expected_release_id": work["release"]["id"],
            "model_id": sla["id"],
            "model_version": sla["version"],
            "training_history_model_id": "67ee9f56-0a79-4ad6-b550-a932fa0d6e78",
            "training_history_model_version": 1,
            "configuration": configuration,
        }
    )
    retirement_snapshots = {}
    for item, name in zip(
        plan["retire"], ("flow-training-before", "flow-scoring-before"), strict=True
    ):
        state = snapshot(directory, name)
        if state["system_id"] != item["system_id"]:
            raise ValueError("Retirement snapshot does not match the expected System")
        item["expected_flow_sha256"] = state["published"]["flow_sha256"]
        item["expected_draft_sha256"] = state["draft"]["flow_sha256"]
        retirement_snapshots[item["system_id"]] = {
            "published_version_id": state["published"]["version_id"],
            "draft_revision": state["draft"]["revision"],
            **{key: value for key, value in item.items() if key != "system_id"},
        }
    issues = validate_flow(configuration["flow_definition"])
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        raise ValueError(f"Flow validation failed: {errors}")
    validate_pages_document(pages)
    review = {
        "kind": "local_configuration_validation",
        "applied": False,
        "workspace_slug": "agentium-showcase",
        "system_id": plan["system_id"],
        "observed_published_version_id": flow["published"]["version_id"],
        "observed_published_flow_sha256": flow["published"]["flow_sha256"],
        "observed_draft_revision": flow["draft"]["revision"],
        "observed_draft_sha256": flow["draft"]["flow_sha256"],
        "observed_work_release_id": work["release"]["id"],
        "target_flow_sha256": canonical_flow_sha256(configuration["flow_definition"]),
        "nodes": len(configuration["flow_definition"]["nodes"]),
        "edges": len(configuration["flow_definition"]["edges"]),
        "pages": [page["id"] for page in pages["pages"]],
        "bindings": [
            "showcase.claims.investigate",
            "showcase.claims.refresh_queue",
            "showcase.claims.forecast",
        ],
        "flow_validation_errors": 0,
        "flow_validation_warning_codes": [
            issue.code for issue in issues if issue.level != "error"
        ],
        "retirement_snapshots": retirement_snapshots,
        "models": {
            key: {
                field: model.get(field)
                for field in (
                    "id",
                    "name",
                    "slug",
                    "version",
                    "status",
                    "task",
                    "family",
                    "dataset_id",
                    "system_id",
                )
            }
            for key, model in loaded.items()
        },
        "composition_sha256": None,
        "composition_review": "Run the read-only activation CLI against the deployed database; no composition hash is invented offline.",
    }
    return plan, review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "live_learning_plan.json")
    args = parser.parse_args()
    plan, review = build_plan(args.snapshots)
    args.output.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    review_path = args.output.with_name(args.output.stem + ".review.json")
    review_path.write_text(
        json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "plan": str(args.output),
                "review": str(review_path),
                "nodes": review["nodes"],
                "edges": review["edges"],
                "target_flow_sha256": review["target_flow_sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
