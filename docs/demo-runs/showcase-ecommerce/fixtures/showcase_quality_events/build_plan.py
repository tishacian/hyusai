"""Prepare a reviewed configuration from current API reads; never apply it.

Run with PYTHONPATH=backend and the backend virtual environment. Snapshot JSON
uses {status: 200, data: ...} (body is accepted too). No API token is read.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from workflow_configuration import JUDGE, SCHEDULE, WEBHOOK, build_flow, pin_work_model

ROOT = Path(__file__).resolve().parent
SYSTEM = "f3ea83de-df89-45ec-8a85-c00d676b2713"
BINDINGS = {
    "investigate": ("showcase.claims.investigate", "source.request"),
    "queue": ("showcase.claims.refresh_queue", "source.queue"),
    "forecast": ("showcase.claims.forecast", "source.forecast"),
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def snapshot(directory, name):
    value = json.loads((directory / f"{name}.json").read_text())
    if value.get("status") != 200:
        raise ValueError(f"SUCCESSFUL_FRESH_SNAPSHOT_REQUIRED: {name}")
    return value.get("body", value.get("data"))


def build_plan(directory, judge_settings, *, allow_blocked=False):
    from app.services.chains.dag_validator import validate_flow
    from app.services.ecommerce.triage import FEATURES, TARGET, get_prediction_contract
    from app.services.experience.lifecycle import validate_pages_document
    from app.services.run_engine.execution_contract import canonical_flow_sha256

    state = snapshot(directory, "flow-state")
    work = snapshot(directory, "work-live")
    experience = snapshot(directory, "experience")
    model_data = snapshot(directory, "model-sla")
    prediction = (
        snapshot(directory, "model-sla-prediction")
        if (directory / "model-sla-prediction.json").exists()
        else {}
    )
    collections = snapshot(directory, "collections")
    triage = snapshot(directory, "triage-settings")["triage"]
    model = model_data["model"]
    blockers = []
    published, draft = state["published"], state["draft"]
    if state["system_id"] != SYSTEM or experience["slug"] != "reclamations":
        raise ValueError("UNEXPECTED_BUSINESS_SCOPE")
    if work["experience"]["id"] != experience["id"]:
        raise ValueError("WORK_EXPERIENCE_MISMATCH")
    if draft["base_published_version_id"] != published["version_id"]:
        raise ValueError("DRAFT_BASE_CHANGED")
    if (
        draft["control_policy_snapshot_sha256"]
        != published["control_policy_snapshot_sha256"]
    ):
        raise ValueError("UNREVIEWED_DRAFT_CONTROL_POLICY")
    if work["release"]["pages"] != experience["draft"]["pages"]:
        raise ValueError("UNREVIEWED_WORK_DRAFT_CHANGES")
    if (
        model["task"] != "classification"
        or model["target"] != TARGET
        or model["features"] != FEATURES
    ):
        raise ValueError("SLA_MODEL_CONTRACT_MISMATCH")
    if model["status"] != "ready" or not model_data.get("serving", {}).get("callable"):
        blockers.append("SLA_SERVING_NOT_READY")
    served = prediction.get("served") or {}
    if (
        served.get("model_id") != model["id"]
        or served.get("version") != model["version"]
        or not prediction.get("prediction_id")
        or not prediction.get("predictions")
        or prediction.get("target") != TARGET
        or str(prediction.get("positive_label")) != "1"
    ):
        blockers.append("PINNED_SLA_INFERENCE_PROOF_REQUIRED")
    if blockers and not allow_blocked:
        raise ValueError(", ".join(blockers))
    if (
        triage.get("scoring_system_id") != SYSTEM
        or triage.get("scoring_version_id") != published["version_id"]
        or triage.get("scoring_flow_sha256") != published["flow_sha256"]
    ):
        raise ValueError("CURRENT_TRIAGE_CONFIGURATION_DRIFT")
    if isinstance(collections, dict):
        collections = collections.get("items", collections.get("collections", []))
    by_slug = {item["slug"]: item["id"] for item in collections}
    collection_slugs = [
        node["config"]["collection_slug"]
        for node in published["flow_definition"]["nodes"]
        if node.get("type") == "source.collection"
    ]
    try:
        collection_ids = [by_slug[slug] for slug in collection_slugs]
    except KeyError as exc:
        raise ValueError("PUBLISHED_COLLECTION_NOT_IN_AUTHORIZED_SNAPSHOT") from exc
    kwargs = {
        "judge_settings": judge_settings,
        "collection_ids": collection_ids,
        "sla_model": model,
    }
    candidate = build_flow(published["flow_definition"], **kwargs)
    preserved_draft = build_flow(draft["flow_definition"], **kwargs)
    errors = [issue for issue in validate_flow(candidate) if issue.level == "error"]
    if errors:
        raise ValueError(f"PUBLISHED_CANDIDATE_INVALID: {errors}")
    pages = pin_work_model(work["release"]["pages"], model)
    validate_pages_document(pages)
    bindings = []
    for filename, (key, ingress) in BINDINGS.items():
        binding = snapshot(directory, "binding-" + filename)
        if (
            binding["binding_key"] != key
            or binding["system_id"] != SYSTEM
            or binding["ingress_id"] != ingress
            or binding["published_flow_version_id"] != published["version_id"]
            or binding["flow_sha256"] != published["flow_sha256"]
            or binding["confirmation_policy"] != "confirm"
        ):
            raise ValueError("WORK_BINDING_DRIFT")
        bindings.append(copy.deepcopy(binding))
    deployments = [
        item for item in experience["deployments"] if item["channel"] == "live"
    ]
    if len(deployments) != 1 or deployments[0]["release_id"] != work["release"]["id"]:
        raise ValueError("LIVE_RELEASE_DRIFT")
    target_sha = canonical_flow_sha256(candidate)
    triage_after = {
        **copy.deepcopy(triage),
        "model_id": model["id"],
        "model_version": model["version"],
        "prediction_contract": get_prediction_contract(
            {"model_id": model["id"], "model_version": model["version"]}
        ),
        "training_system_id": model.get("system_id"),
        "scoring_version_id": "$published.version_id",
        "scoring_flow_sha256": target_sha,
    }
    plan = {
        "format": "reviewed-workflow-configuration-v1",
        "applied": False,
        "activation_ready": False,
        "activation_status": "blocked" if blockers else "awaiting_live_review",
        "model_pin_qualified": not blockers,
        "blockers": blockers,
        "workspace_slug": "agentium-showcase",
        "system_id": SYSTEM,
        "experience_id": experience["id"],
        "preconditions": {
            "published_version_id": published["version_id"],
            "flow_sha256": published["flow_sha256"],
            "draft_revision": draft["revision"],
            "draft_sha256": draft["flow_sha256"],
            "control_policy_sha256": draft["control_policy_snapshot_sha256"],
            "work_draft_revision": experience["draft"]["revision"],
            "work_content_sha256": experience["draft"]["content_sha256"],
            "experience_updated_at": experience["updated_at"],
            "deployment": deployments[0],
            "bindings": bindings,
            "triage": triage,
        },
        "backup": {"flow_draft": draft, "work_draft": experience["draft"]},
        "publication_candidate": candidate,
        "preserved_draft_candidate": preserved_draft,
        "work_pages": pages,
        "work_binding_keys": experience["draft"]["binding_keys"],
        "triage_after_publication": triage_after,
        "target_flow_sha256": target_sha,
        "sla_inference_proof": {
            "model_id": model["id"],
            "version": model["version"],
            "prediction_id": prediction.get("prediction_id"),
            "captured_at": prediction.get("captured_at"),
        },
        "triggers": {
            "hook": {
                "name": "Réclamation entrante",
                "event_type": "webhook.received",
                "enabled": False,
            },
            "schedule": {
                "name": "Actualisation de la file SAV",
                "cron_expr": "0 8 * * 1-5",
                "timezone": "Europe/Paris",
                "input_payload": {},
                "enabled": False,
            },
        },
        "monitoring": {
            "enabled": True,
            "propose_retraining": False,
            "interval_minutes": 60,
        },
        "shadow": {"enabled": True, "sample_percent": 10, "timeout_s": 15},
        "activation_gates": [
            "Deployed frontend, API and workers contain this delivery; catalog synchronized.",
            "PostgreSQL scoped read and pinned SLA inference succeed.",
            "Judge provider route matches the declared tariff; real call still requires qualification.",
            "Review the native Flow diff/execution contract before publishing.",
            "Preserve the operator draft with its additional node; never publish that orphan implicitly.",
            "Enable shadow only after a compatible actual challenger is ready and identified.",
            "Keep schedule disabled until one bounded real tick is observed; disable after qualification.",
        ],
    }
    review = {
        "applied": False,
        "activation_ready": False,
        "activation_status": "blocked" if blockers else "awaiting_live_review",
        "model_pin_qualified": not blockers,
        "blockers": blockers,
        "system_id": SYSTEM,
        "target_flow_sha256": target_sha,
        "configuration_sha256": digest(plan),
        "nodes": len(candidate["nodes"]),
        "edges": len(candidate["edges"]),
        "ingresses": [
            node["id"] for node in candidate["nodes"] if node.get("kind") == "source"
        ],
        "preserved_unpublished_node_ids": [
            node["id"]
            for node in draft["flow_definition"]["nodes"]
            if node["id"]
            not in {n["id"] for n in published["flow_definition"]["nodes"]}
        ],
        "judge_node": JUDGE,
        "event_ingresses": [WEBHOOK, SCHEDULE],
        "model_pin": plan["sla_inference_proof"],
        "human_review_required": True,
        "calibration_profile": None,
        "triggers_enabled": False,
        "model_promotion": False,
    }
    return plan, review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--judge-settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Write a blocked review candidate when SLA serving or pinned inference evidence is missing; never makes it activatable.",
    )
    args = parser.parse_args()
    plan, review = build_plan(
        args.snapshots,
        json.loads(args.judge_settings.read_text()),
        allow_blocked=args.allow_blocked,
    )
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    review_path = args.output.with_name(args.output.stem + ".review.json")
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(review, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
