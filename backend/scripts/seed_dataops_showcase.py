"""Reconcile real DataOps Showcase drafts; activate only explicitly ready services."""

from __future__ import annotations

import argparse
import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.models.capability import Capability
from app.models.service_contract import ServiceContract
from app.models.skill import Skill
from app.models.system import System
from app.models.system_flow_draft import SystemFlowDraft
from app.models.tabular import MLModel
from app.models.workspace import Workspace
from app.schemas.narration import NarrationSourceUnit
from app.schemas.service_contract import ServiceBudget, ServiceDefinition
from app.schemas.typed_evaluation import TypedEvaluationInput
from app.services import governed_assets as assets
from app.services import service_promises as promises
from app.services.catalog_visibility import skill_is_visible, workspace_catalog_policy
from app.services.run_engine.execution_contract import canonical_flow_sha256
from app.services.seed_catalog_safety import (
    owned_capability_for_seed,
    require_showcase_workspace_for_seed,
)
from app.services.systems import flow_publication
from app.services.tabular_datasets import TabularError, resolve_dataset_ref
from app.services.tabular_predict import contract_fields, serving_version

ACTOR = "dataops-showcase-seed:v1"
WORKLOADS = (("scoring-2m", 2_000_000), ("scoring-3m", 3_000_000), ("narration-500", 500))


def _node(identifier, slug, skills, *, params=None, inputs=None):
    config = {"skill_slug": slug, "skill_id": skills[slug].id, "params": params or {}}
    if inputs:
        config["inputs_map"] = inputs
    return {"id": identifier, "kind": "task", "label": identifier, "config": config}


def _flow(nodes):
    nodes = [
        {
            "id": "source",
            "kind": "source",
            "label": "Service input",
            "config": {"ingress_kind": "schedule"},
        },
        *nodes,
        {"id": "sink", "kind": "sink", "label": "Candidate for review"},
    ]
    return {
        "schema_version": 3,
        "io_mode": "strict",
        "nodes": nodes,
        "edges": [
            {"from": first["id"], "to": second["id"]} for first, second in zip(nodes, nodes[1:])
        ],
    }


def scoring_flow(skills, key, dataset, model):
    # The next daily input may carry new context columns. Preparation starts
    # as a pass-through; the predictor projects its own feature contract.
    prep = {
        "spec": {
            "operation": "prepare",
            "steps": [],
            "outputs": [{"port": "out", "name": f"Showcase {key} prepared"}],
        },
        "inputs": {},
    }
    return _flow(
        [
            _node("prepare", "data_prep_v1", skills, params={"data_prep": prep}),
            _node(
                "score",
                "ml_batch_score_v1",
                skills,
                params={
                    "model_id": model.id,
                    "pinned_version": model.version,
                    "output_name": f"Showcase {key} scored",
                }
                if model
                else {},
                inputs={"dataset_id": {"node_id": "prepare", "path": ["dataset_id"]}},
            ),
        ]
    )


def narration_flow(
    skills, source_ref, engine_revision, judge_config, judge_profile, vision_route=None
):
    narration = {
        "engine_revision": engine_revision or "unconfigured",
        "budgets": {"max_pages": 500, "max_images": 500},
    }
    if source_ref:
        narration["source_ref"] = source_ref
    typed = dict(judge_config or {})
    if judge_profile:
        typed["profile_ref"] = judge_profile
    if vision_route:
        typed["vision_route_ref"] = vision_route
    return _flow(
        [
            _node(
                "narrate",
                "narration_run_v1",
                skills,
                params={"narration": narration},
                inputs={"asset_ref": {"node_id": "source", "path": ["asset_ref"]}},
            ),
            _node(
                "judge",
                "evaluate_v2",
                skills,
                params={"typed_evaluation": typed},
                inputs={"asset_ref": {"node_id": "narrate", "path": ["asset_ref"]}},
            ),
        ]
    )


def narration_enabled(workspace):
    features = (workspace.settings or {}).get("features", {})
    return settings.narration_enabled or features.get("narration_enabled") is True


def _catalog(db, workspace):
    slugs = {"data_prep_v1", "ml_batch_score_v1"}
    if narration_enabled(workspace):
        slugs.update({"narration_run_v1", "evaluate_v2"})
    rows = db.query(Skill).filter(Skill.slug.in_(slugs)).all()
    policy = workspace_catalog_policy(workspace)
    by_slug = {
        row.slug: row
        for row in rows
        if row.workspace_id in {None, workspace.id}
        and skill_is_visible(row, workspace, {item.id for item in rows}, policy)
    }
    if set(by_slug) != slugs:
        raise ValueError("SHOWCASE_CANONICAL_SKILLS_UNAVAILABLE")
    return by_slug


def _system(db, workspace, owner, key, flow, slugs, skills, reasons, publish):
    capability_slug = f"dataops_showcase_{key.replace('-', '_')}_{workspace.id[:8]}"
    capability = owned_capability_for_seed(db, workspace=workspace, slug=capability_slug)
    if capability is None:
        capability = Capability(
            workspace_id=workspace.id,
            slug=capability_slug,
            name=f"Showcase {key}",
            tier="client",
            description="Configured workload; no synthetic outcomes.",
            input_unit="window",
            output_unit="reviewed_delivery",
            is_seeded="N",
        )
        db.add(capability)
    capability.skill_ids = [skills[slug].id for slug in slugs]
    db.flush()
    identity = f"dataops-showcase:{key}"
    system = (
        db.query(System).filter_by(workspace_id=workspace.id, blueprint_key=identity).one_or_none()
    )
    if system is None:
        system = System(
            workspace_id=workspace.id,
            blueprint_key=identity,
            name=f"Showcase {key}",
            objective="Deliver a versioned candidate within its service window, then require human review.",
            capability_id=capability.id,
            skill_ids=capability.skill_ids,
            status="draft",
            created_by=ACTOR,
            execution_mode="batch_processing",
            coordination_pattern="graph",
            flow_definition=flow,
            settings={},
        )
        db.add(system)
        db.flush()
        # An incomplete authoring draft must not create an executable baseline.
        db.add(
            SystemFlowDraft(
                system_id=system.id,
                workspace_id=workspace.id,
                flow_definition=copy.deepcopy(flow),
                flow_sha256=canonical_flow_sha256(flow),
                revision=1,
                updated_by=ACTOR,
            )
        )
        db.flush()
    elif system.created_by != ACTOR:
        raise ValueError("SHOWCASE_SYSTEM_NOT_OWNED")
    system.capability_id = capability.id
    system.skill_ids = capability.skill_ids
    system.settings = {
        **system.settings,
        "dataops_showcase": {
            "key": key,
            "ready": not reasons,
            "not_ready_reasons": reasons,
            "owner_user_id": owner.id,
            "synthetic_outcomes": False,
        },
    }
    # Canonical draft helpers refresh their locked parent; persist these owned
    # catalog/readiness fields before that refresh can discard pending changes.
    db.flush()
    draft = db.get(SystemFlowDraft, system.id)
    if draft.updated_by != ACTOR and draft.flow_sha256 != canonical_flow_sha256(flow):
        reasons.append("OPERATOR_DRAFT_PRESERVED")
        system.settings = {
            **system.settings,
            "dataops_showcase": {
                **system.settings["dataops_showcase"],
                "ready": False,
                "not_ready_reasons": list(reasons),
            },
        }
        return system
    if system.published_flow_version_id:
        result = flow_publication.reconcile_system_flow(
            db,
            system=system,
            workspace=workspace,
            flow_definition=flow,
            actor=ACTOR,
            publish_if_owned=publish and not reasons,
            ownership_prefix=ACTOR,
            message="Configured DataOps Showcase workload",
        )
        if result.status == "operator_draft_preserved":
            reasons.append("OPERATOR_DRAFT_PRESERVED")
    else:
        flow_publication.save_draft(
            db,
            system_id=system.id,
            workspace=workspace,
            flow_definition=flow,
            expected_revision=draft.revision,
            actor=ACTOR,
        )
        # Before the first publication the mirror is just unpublished authoring
        # state. The canonical initializer compiles and freezes it atomically.
        system.flow_definition = copy.deepcopy(flow)
        if publish and not reasons:
            db.flush()
            flow_publication.initialize_new_system_publication_if_enabled(
                db, system=system, workspace=workspace, actor=ACTOR
            )
    if publish and not reasons:
        system.status = "active"
    elif not system.published_flow_version_id:
        system.status = "draft"
    system.settings = {
        **system.settings,
        "dataops_showcase": {
            **system.settings["dataops_showcase"],
            "ready": not reasons,
            "not_ready_reasons": list(reasons),
        },
    }
    db.flush()
    return system


def seed(
    db,
    *,
    workspace_id,
    owner_user_id,
    dataset_id=None,
    high_dataset_id=None,
    model_id=None,
    model_version=None,
    source_ref=None,
    engine_revision=None,
    judge_config=None,
    judge_profile=None,
    vision_route=None,
    publish_services=False,
    starts_on=None,
    timezone="Europe/Paris",
    deadline="17:00",
    service_budget=None,
):
    workspace = (
        db.query(Workspace).filter_by(id=workspace_id, is_active=True).with_for_update().one()
    )
    require_showcase_workspace_for_seed(workspace)
    owner = promises.require_member(db, workspace.id, owner_user_id, admin=True)
    if not flow_publication.flow_publication_enabled(workspace):
        raise ValueError("SHOWCASE_FLOW_PUBLICATION_REQUIRED")
    skills = _catalog(db, workspace)
    budget = ServiceBudget.model_validate(
        service_budget
        or {
            "max_attempts": 2,
            "max_cost": 10,
            "max_tokens": 100000,
            "max_seconds": 900,
        }
    ).model_dump(mode="json")
    model, model_reasons = None, []
    if model_id:
        requested = (
            db.query(MLModel).filter_by(id=model_id, workspace_id=workspace.id).one_or_none()
        )
        if requested is None:
            raise ValueError("SHOWCASE_MODEL_SCOPE_DENIED")
        try:
            model = serving_version(db, requested, version=model_version or requested.version)
            if model.family not in {"tabular", "clustering"} or not model.model_uri:
                model_reasons.append("SCORING_MODEL_UNQUALIFIED")
        except TabularError:
            model_reasons.append("SCORING_MODEL_NOT_READY")
    else:
        model_reasons.append("SCORING_MODEL_REQUIRED")
    source, typed, profile = None, None, None
    if source_ref:
        source = assets.resolve_asset_ref(
            db, workspace.id, source_ref, authorize=assets.native_authorizer(db, workspace, owner)
        )
        source_ref = assets.asset_ref(source)
    if judge_config is not None:
        typed = TypedEvaluationInput.model_validate(
            {key: value for key, value in judge_config.items() if key != "batch_mode"}
        ).model_dump(mode="json")
        typed["batch_mode"] = "per_unit"
    if judge_profile:
        profile = assets.resolve_asset_ref(
            db,
            workspace.id,
            judge_profile,
            authorize=assets.native_authorizer(db, workspace, owner),
        )
        assets.validate_qualification(
            assets.current_qualification(db, workspace.id, profile.id), profile
        )
        if profile.manifest_json.get("type") != "typed_calibration_profile":
            raise ValueError("SHOWCASE_JUDGE_PROFILE_INVALID")
        if typed and (
            profile.manifest_json.get("rubric_sha256") != assets.content_digest(typed["questions"])
            or profile.manifest_json.get("rubric_id") != typed["rubric_id"]
            or profile.manifest_json.get("rubric_version") != typed["rubric_version"]
        ):
            raise ValueError("SHOWCASE_JUDGE_RUBRIC_MISMATCH")
    if vision_route:
        route = assets.resolve_asset_ref(
            db, workspace.id, vision_route, authorize=assets.native_authorizer(db, workspace, owner)
        )
        assets.validate_qualification(
            assets.current_qualification(db, workspace.id, route.id), route
        )
        if route.manifest_json.get("type") != "typed_judge_vision_route":
            raise ValueError("SHOWCASE_VISION_ROUTE_INVALID")
    results = []
    for key, expected in WORKLOADS:
        if key.startswith("narration") and not narration_enabled(workspace):
            continue
        source_bindings = []
        if key.startswith("scoring"):
            reasons = list(model_reasons)
            identifier = dataset_id if key == "scoring-2m" else high_dataset_id
            dataset = (
                resolve_dataset_ref(db, workspace_id=workspace.id, ref={"dataset_id": identifier})
                if identifier
                else None
            )
            if dataset is None:
                reasons.append("SCORING_DATASET_REQUIRED")
            elif dataset.status != "ready" or dataset.row_count != expected:
                reasons.append(f"SCORING_{expected}_READY_ROWS_REQUIRED")
            if not settings.dataops_enabled or not settings.ml_score_streaming_enabled:
                reasons.append("SCORING_WORKER_FEATURES_DISABLED")
            if (
                dataset
                and model
                and {f["name"] for f in contract_fields(model)}
                - {f["name"] for f in dataset.schema_json}
            ):
                reasons.append("SCORING_FEATURE_COLUMNS_MISSING")
            flow = scoring_flow(skills, key, dataset, model)
            input_payload = {"dataset_id": dataset.id} if dataset else {}
            if dataset and dataset.status == "ready" and dataset.storage_key:
                from app.services.dataops.asset_lineage import dataset_manifest

                source_asset = assets.register_asset(
                    db,
                    workspace.id,
                    "dataset",
                    f"showcase:input:{key}",
                    dataset_manifest(dataset),
                    run_id=dataset.run_id,
                )
                qualification = assets.current_qualification(db, workspace.id, source_asset.id)
                if qualification is None:
                    qualification = assets.record_qualification(
                        db,
                        workspace.id,
                        assets.asset_ref(source_asset),
                        status="qualified",
                        policy={"authority": "storage_ingest", "purpose": "source_integrity"},
                        evidence={
                            "dataset_id": dataset.id,
                            "status": dataset.status,
                            "rows": dataset.row_count,
                            "source_ingested_at": dataset.ingested_at.isoformat()
                            if dataset.ingested_at
                            else None,
                        },
                    )
                if qualification.status != "qualified":
                    reasons.append("SCORING_SOURCE_REQUALIFICATION_REQUIRED")
                source_bindings = [
                    {
                        "payload_key": "dataset_id",
                        "kind": "dataset",
                        "logical_key": source_asset.logical_key,
                        "max_age_seconds": 86400,
                        "require_qualified": True,
                        "representation": "native_id",
                    }
                ]
            else:
                reasons.append("SCORING_SOURCE_BYTES_REQUIRED")
            slugs = ["data_prep_v1", "ml_batch_score_v1"]
        else:
            reasons = []
            if not narration_enabled(workspace):
                reasons.append("NARRATION_DEFERRED")
            if source is None:
                reasons.append("NARRATION_SOURCE_REQUIRED")
            elif (
                not isinstance(source.manifest_json.get("units"), list)
                or len(source.manifest_json["units"]) != expected
            ):
                reasons.append("NARRATION_500_SOURCE_UNITS_REQUIRED")
            if (
                not settings.narration_endpoint
                or not settings.narration_allowed_hosts
                or not engine_revision
            ):
                reasons.append("NARRATION_ENGINE_NOT_CONFIGURED")
            if typed is None:
                reasons.append("JUDGE_CONFIG_REQUIRED")
            if profile is None:
                reasons.append("JUDGE_PROFILE_REQUIRED")
            if typed and typed["budget"]["max_calls"] < expected:
                reasons.append("JUDGE_BATCH_BUDGET_TOO_SMALL")
            if typed and (
                typed["budget"]["max_tokens"] > budget["max_tokens"]
                or typed["budget"]["max_cost_usd"] > budget["max_cost"]
            ):
                reasons.append("JUDGE_BUDGET_EXCEEDS_SERVICE_BUDGET")
            if source:
                try:
                    units = [
                        NarrationSourceUnit.model_validate(unit)
                        for unit in source.manifest_json.get("units", [])
                    ]
                except (ValueError, TypeError):
                    units = []
                    reasons.append("NARRATION_SOURCE_UNITS_INVALID")
                expected_ids = {unit.id for unit in units}
                evidence_entries = source.manifest_json.get("evidence")
                if not isinstance(evidence_entries, list):
                    evidence_entries = []
                evidence_ids = {
                    entry.get("id") for entry in evidence_entries if isinstance(entry, dict)
                }
                if (
                    not expected_ids
                    or len(expected_ids) != len(units)
                    or not expected_ids <= evidence_ids
                ):
                    reasons.append("JUDGE_SOURCE_UNIT_EVIDENCE_REQUIRED")
                if not vision_route and any(
                    isinstance(entry, dict) and entry.get("kind") == "image"
                    for entry in evidence_entries
                ):
                    reasons.append("JUDGE_IMAGE_VISION_ROUTE_REQUIRED")
            if (
                profile
                and source
                and any(
                    not source.manifest_json.get(field)
                    for field in ("document_family", "source", "language", "task")
                )
            ):
                reasons.append("JUDGE_SOURCE_CONTEXT_REQUIRED")
            if profile:
                context = profile.manifest_json.get("context")
                if source and (
                    not isinstance(context, dict)
                    or any(
                        context.get(field) != source.manifest_json.get(field)
                        for field in ("source", "language", "task")
                    )
                ):
                    reasons.append("JUDGE_PROFILE_CONTEXT_MISMATCH")
                calibrated_model = profile.manifest_json.get("model")
                if typed and (
                    not isinstance(calibrated_model, dict)
                    or any(
                        calibrated_model.get(field) != typed["tariff"][field]
                        for field in ("provider", "model")
                    )
                ):
                    reasons.append("JUDGE_PROFILE_MODEL_MISMATCH")
            flow = narration_flow(
                skills, source_ref, engine_revision, typed, judge_profile, vision_route
            )
            input_payload = {"asset_ref": source_ref} if source_ref else {}
            slugs = ["narration_run_v1", "evaluate_v2"]
        system = _system(db, workspace, owner, key, flow, slugs, skills, reasons, publish_services)
        latest = (
            db.query(ServiceContract)
            .filter_by(workspace_id=workspace.id, system_id=system.id, logical_key=key)
            .order_by(ServiceContract.version.desc())
            .first()
        )
        start = starts_on or (
            latest.definition_json["starts_on"]
            if latest
            else datetime.now(ZoneInfo(timezone)).date().isoformat()
        )
        definition = ServiceDefinition.model_validate(
            {
                "starts_on": start,
                "timezone": timezone,
                "deadline": deadline,
                "input_payload": input_payload,
                "inputs": source_bindings,
                "budget": budget,
                "output_policy": {"require_human_review": True, "destination": "work"},
                "output_schema": {
                    "type": "object",
                    "required": ["technical_status", "coverage"],
                    "properties": {
                        "technical_status": {"const": "completed"},
                        "coverage": {
                            "type": "object",
                            "required": ["expected", "processed", "failed"],
                            "properties": {
                                "expected": {"const": expected},
                                "processed": {"const": expected},
                                "failed": {"const": 0},
                            },
                        },
                    },
                },
            }
        ).model_dump(mode="json")
        contract = (
            latest
            if latest and latest.owner_user_id == owner.id and latest.definition_json == definition
            else promises.create_contract(
                db,
                workspace.id,
                system.id,
                owner.id,
                definition,
                created_by=owner.id,
                logical_key=key,
            )
        )
        if publish_services and not reasons:
            promises.publish_contract(db, workspace.id, contract.id, user_id=owner.id)
        results.append(
            {
                "key": key,
                "system_id": system.id,
                "contract_id": contract.id,
                "contract_version": contract.version,
                "ready": not reasons,
                "published": contract.published_at is not None,
                "reasons": reasons,
                "flow_sha256": canonical_flow_sha256(flow),
            }
        )
    if any(result["published"] and result["ready"] for result in results):
        current = copy.deepcopy(workspace.settings)
        current.setdefault("features", {})["service_contracts"] = True
        workspace.settings = current
    db.commit()
    return {
        "workspace_id": workspace.id,
        "owner_user_id": owner.id,
        "workloads": results,
        "deferred_workloads": [
            key
            for key, _ in WORKLOADS
            if key.startswith("narration") and not narration_enabled(workspace)
        ],
        "runs_created": 0,
        "decisions_created": 0,
        "observed_at": datetime.now(UTC).isoformat(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-slug", default="agentium-showcase")
    parser.add_argument("--owner-user-id", required=True)
    parser.add_argument("--dataset-id")
    parser.add_argument("--high-dataset-id")
    parser.add_argument("--model-id")
    parser.add_argument("--model-version", type=int)
    parser.add_argument("--source-ref", type=Path)
    parser.add_argument("--engine-revision")
    parser.add_argument("--judge-config", type=Path)
    parser.add_argument("--judge-profile", type=Path)
    parser.add_argument("--vision-route", type=Path)
    parser.add_argument("--service-budget", type=Path)
    parser.add_argument("--publish-services", action="store_true")
    parser.add_argument("--starts-on")
    parser.add_argument("--timezone", default="Europe/Paris")
    parser.add_argument("--deadline", default="17:00")
    args = parser.parse_args(argv)
    import app.models  # noqa: F401
    from app.db.base import SessionLocal

    with SessionLocal() as db:
        workspace = db.query(Workspace).filter_by(slug=args.workspace_slug).one()
        values = vars(args).copy()
        values.pop("workspace_slug")
        for name in (
            "source_ref",
            "judge_config",
            "judge_profile",
            "vision_route",
            "service_budget",
        ):
            values[name] = json.loads(values[name].read_text()) if values[name] else None
        result = seed(db, workspace_id=workspace.id, **values)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
