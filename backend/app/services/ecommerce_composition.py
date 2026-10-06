"""One Luma System: PostgreSQL datasets, model scoring and document-led inquiry."""

from __future__ import annotations

import copy
import math
from datetime import UTC, datetime

from app.models.run import Run
from app.models.system import System
from app.models.tabular import TabularDataset
from app.models.workspace import Workspace
from app.services import ecommerce_claims as claims
from app.services.connectors.generic import postgresql_claims as pg
from app.services.ecommerce_install import BLUEPRINT
from app.services.ecommerce_triage import FEATURES, MAX_AGE, TARGET, feature_row, validate_model
from app.services.ecommerce_triage_flows import _task

DATASET_SKILL = "ecommerce_sav_dataset_v1"
CONTEXT_SKILL = "ecommerce_sav_context_v1"
CASE_INGRESS = "source.request"
QUEUE_INGRESS = "source.queue"
FEATURE_NODE = "sav.features"
PREPARE_NODE = "sav.prepare"
SCORE_NODE = "sav.score"
CONTEXT_NODE = "sav.context"
MODE = "composed_v1"
PREPARE_SQL = (
    "SELECT claim_id, "
    + ", ".join(FEATURES)
    + ", case_documents = 0 AS evidence_gap, already_refunded = 1 AS duplicate_refund_check"
    + " FROM input ORDER BY claim_id"
)


def _ref(node_id, key):
    return {"node_id": node_id, "path": [key], "required": True}


def compose(flow, model_id, version, *, model_slug):
    """Share the data/model lane between two frozen ingresses, then route the case."""
    result = copy.deepcopy(flow)
    nodes = {node["id"]: node for node in result["nodes"]}
    if FEATURE_NODE in nodes or QUEUE_INGRESS in nodes:
        raise ValueError("CLAIMS_COMPOSITION_ALREADY_INSTALLED")
    # Upgrade either the original inquiry or the preceding inline-predict release.
    legacy = {"sla_features", "sla_risk"}
    if legacy & nodes.keys():
        if (
            not legacy <= nodes.keys()
            or nodes["sla_features"]["config"].get("skill_slug") != "ecommerce_sla_features_v1"
            or nodes["sla_risk"]["config"].get("skill_slug") != "ml_predict_v1"
            or nodes["sla_risk"]["config"].get("params", {}).get("model_id") != model_id
            or nodes["sla_risk"]["config"].get("params", {}).get("pinned_version") != version
        ):
            raise ValueError("CLAIMS_COMPOSITION_INLINE_FLOW_EDITED")
    result["nodes"] = [node for node in result["nodes"] if node["id"] not in legacy]
    result["edges"] = [
        edge
        for edge in result["edges"]
        if edge["from"] not in legacy
        and edge["to"] not in legacy
        and not (edge["from"] == CASE_INGRESS and edge["to"] == "loop.investigate")
    ]
    result["nodes"].extend(
        [
            {
                "id": QUEUE_INGRESS,
                "type": "source",
                "kind": "source",
                "label": "Actualiser la file SAV",
                "config": {
                    "ingress_kind": "manual",
                    "input_schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {},
                    },
                },
            },
            _task(FEATURE_NODE, "Lire les faits SAV dans PostgreSQL", DATASET_SKILL),
            _task(
                PREPARE_NODE,
                "Préparer le dataset et les contrôles SAV",
                "sql_transform_v1",
                params={"sql": PREPARE_SQL, "output_name": "Luma — Données SAV préparées"},
                inputs_map={"dataset_id": _ref(FEATURE_NODE, "dataset_id")},
            ),
            _task(
                SCORE_NODE,
                "Prioriser avec le modèle SLA v1",
                "ml_batch_score_v1",
                params={
                    "model_id": model_id,
                    "model_slug": model_slug,
                    "pinned_version": version,
                    "output_name": "Luma — Dossiers SAV priorisés",
                },
                inputs_map={"dataset_id": _ref(PREPARE_NODE, "dataset_id")},
            ),
            {
                "id": "decision.operation",
                "type": "decision",
                "kind": "decision",
                "label": "File ou dossier ?",
                "config": {
                    "inputs_map": {
                        "operation": _ref(FEATURE_NODE, "operation"),
                        "claim_id": _ref(FEATURE_NODE, "claim_id"),
                        "dataset_id": _ref(SCORE_NODE, "dataset_id"),
                    },
                    "passthrough_inputs": ["operation", "claim_id", "dataset_id"],
                    "branches": [
                        {"label": "case", "condition": "operation == 'case'"},
                        {"label": "queue", "condition": "operation == 'queue'"},
                        {
                            "label": "blocked",
                            "condition": "operation != 'case' and operation != 'queue'",
                        },
                    ],
                    "default_branch": "blocked",
                },
            },
            _task(
                CONTEXT_NODE,
                "Combiner faits préparés et prédiction",
                CONTEXT_SKILL,
                inputs_map={"dataset_id": _ref(SCORE_NODE, "dataset_id")},
            ),
            {
                "id": "sink.queue",
                "type": "sink",
                "kind": "sink",
                "label": "File priorisée dans Luma",
            },
        ]
    )
    result["edges"].extend(
        [
            {"from": CASE_INGRESS, "to": FEATURE_NODE, "kind": "data"},
            {"from": QUEUE_INGRESS, "to": FEATURE_NODE, "kind": "data"},
            {"from": "asset.postgresql", "to": FEATURE_NODE, "kind": "data", "from_port": "source"},
            {"from": FEATURE_NODE, "to": PREPARE_NODE, "kind": "data"},
            {"from": PREPARE_NODE, "to": SCORE_NODE, "kind": "data"},
            {"from": SCORE_NODE, "to": "decision.operation", "kind": "data"},
            {
                "from": "decision.operation",
                "to": CONTEXT_NODE,
                "kind": "branch",
                "branch_label": "case",
            },
            {
                "from": "decision.operation",
                "to": "sink.queue",
                "kind": "branch",
                "branch_label": "queue",
            },
            {
                "from": "decision.operation",
                "to": "sink.blocked",
                "kind": "branch",
                "branch_label": "blocked",
            },
            {"from": CONTEXT_NODE, "to": "loop.investigate", "kind": "data"},
        ]
    )
    loop = nodes["loop.investigate"]["config"]
    loop["inputs_map"] = {
        **loop.get("inputs_map", {}),
        "claim_id": _ref("run", "claim_id"),
        "sla_prediction": _ref(CONTEXT_NODE, "predictions"),
        "sla_model": _ref(CONTEXT_NODE, "served"),
        "sav_facts": _ref(CONTEXT_NODE, "facts"),
        "data_quality": _ref(CONTEXT_NODE, "quality"),
    }
    loop["goal"]["objective"] += (
        " Le dataset SAV préparé et le score du modèle sont fournis dans le contexte."
        " Utiliser les contrôles de données pour orienter les recherches de preuves manquantes"
        " et de remboursement antérieur. Le score de traitement long conseille la priorité ;"
        " les faits relus, la politique et les documents cités déterminent la résolution."
    )
    positions = {
        CASE_INGRESS: (80, 260),
        QUEUE_INGRESS: (80, 440),
        "asset.postgresql": (80, 80),
        FEATURE_NODE: (420, 260),
        PREPARE_NODE: (740, 260),
        SCORE_NODE: (1060, 260),
        "decision.operation": (1380, 260),
        "sink.queue": (1700, 80),
        CONTEXT_NODE: (1700, 390),
        "loop.investigate": (2020, 390),
        "decision.ready": (2340, 390),
        "hitl.review": (2660, 240),
        "task.simulate": (2980, 240),
        "sink.receipt": (3300, 240),
        "sink.blocked": (2660, 520),
    }
    collections = [node for node in result["nodes"] if node.get("type") == "source.collection"]
    for index, node in enumerate(collections):
        positions[node["id"]] = (2020, -460 + index * 140)
    for node in result["nodes"]:
        if node["id"] in {FEATURE_NODE, PREPARE_NODE, SCORE_NODE, CONTEXT_NODE}:
            node["config"]["on_error"] = "fail"
        if node["id"] in positions:
            x, y = positions[node["id"]]
            node["position"] = {"x": x, "y": y}
    result.setdefault("runtime_contract", {}).update(
        {
            "ecommerce_composition_v1": True,
            "requires_postgresql_source": True,
            "postgresql_consumers": [
                {"node_id": FEATURE_NODE, "resources": copy.deepcopy(pg.CLAIM_RESOURCES)}
            ],
        }
    )
    return result


def operation_for_run(run):
    """Use the engine's immutable ingress evidence; payload cannot select a cohort."""
    from app.services.run_engine.dag import DagGraph, _contract_ingress_selection

    if (run.flow_snapshot or {}).get("runtime_contract", {}).get(
        "ecommerce_composition_v1"
    ) is not True:
        raise ValueError("CLAIMS_COMPOSITION_FLOW_REQUIRED")
    selection = _contract_ingress_selection(run, DagGraph.from_flow_definition(run.flow_snapshot))
    if selection is None or selection[0] not in {CASE_INGRESS, QUEUE_INGRESS}:
        raise ValueError("CLAIMS_COMPOSITION_INGRESS_REQUIRED")
    return "queue" if selection[0] == QUEUE_INGRESS else "case"


def _context(db, ctx):
    from app.models.claim_trial import ClaimTrial

    workspace = db.query(Workspace).filter(Workspace.id == ctx.get("workspace_id")).one_or_none()
    run = (
        db.query(Run)
        .filter(Run.id == ctx.get("run_id"), Run.workspace_id == ctx.get("workspace_id"))
        .one_or_none()
    )
    system = (
        db.query(System)
        .filter(System.id == run.system_id, System.workspace_id == workspace.id)
        .one_or_none()
        if workspace and run
        else None
    )
    if system is None or system.blueprint_key != BLUEPRINT:
        raise ValueError("CLAIMS_COMPOSITION_SYSTEM_REQUIRED")
    if (
        run.initiated_by_user_id
        and db.query(ClaimTrial.id)
        .filter(
            ClaimTrial.workspace_id == workspace.id,
            ClaimTrial.operator_id == run.initiated_by_user_id,
            ClaimTrial.condition == "manual",
            ClaimTrial.state.in_(["active", "paused"]),
        )
        .first()
    ):
        raise ValueError("CLAIMS_COMPOSITION_MANUAL_TRIAL_ACTIVE")
    config = claims._config(workspace)
    operation = operation_for_run(run)
    claim_id = (run.input_ref or {}).get("claim_id")
    if operation == "case" and claim_id not in config["allowed_claim_ids"]:
        raise ValueError("CLAIM_OUTSIDE_DEMO_SCOPE")
    return workspace, run, config, operation, claim_id


async def invoke_dataset(payload, ctx=None):
    import asyncio

    return await asyncio.to_thread(_dataset, ctx or {})


def _dataset(ctx):
    import polars as pl

    from app.db.base import SessionLocal
    from app.services.evaluation.judge import contractual_zero_token_usage
    from app.services.flow_data_sources import require_postgresql_binding
    from app.services.tabular_datasets import dataset_reference, register_frame

    owns = ctx.get("db") is None
    db = ctx.get("db") or SessionLocal()
    try:
        workspace, run, config, operation, claim_id = _context(db, ctx)
        cohort = config["allowed_claim_ids"] if operation == "queue" else [claim_id]
        binding = require_postgresql_binding(
            run, ctx.get("_flow_data_sources", []), resources=pg.CLAIM_RESOURCES
        )
        if binding is None:
            raise ValueError("CLAIMS_COMPOSITION_POSTGRESQL_REQUIRED")
        result = pg.features(workspace, cohort)
        rows = [
            {"claim_id": row["claim_id"], **feature_row(row)} for row in result["data"]["features"]
        ]
        provenance = {
            **result["provenance"],
            "flow_data_source": binding,
            "feature_contract": FEATURES,
        }
        dataset = register_frame(
            db,
            workspace_id=workspace.id,
            name="Luma — Faits SAV PostgreSQL",
            frame=pl.DataFrame(rows),
            source="postgresql",
            produced_by=DATASET_SKILL,
            run_id=run.id,
            node_id=FEATURE_NODE,
            created_by=run.initiated_by_user_id,
            description="Snapshot SAV borné du parcours Luma ; données synthétiques de démonstration.",
            lineage={
                "engine": "postgresql",
                "provenance": provenance,
                "operation": operation,
                "postgresql": {
                    "schema": "showcase_ecommerce",
                    "table": "claims",
                    "mode": "snapshot",
                    "resources": provenance["resources_read"],
                    "captured_at": provenance["captured_at"],
                    "snapshot_sha256": provenance["snapshot_sha256"],
                    "row_count": len(rows),
                    "truncated": False,
                },
            },
        )
        if owns:
            db.commit()
        return {
            **dataset_reference(dataset),
            "operation": operation,
            "claim_id": claim_id if operation == "case" else None,
            "provenance": provenance,
            **contractual_zero_token_usage("postgresql:sav_dataset"),
        }
    finally:
        if owns:
            db.close()


def _artifacts(db, workspace, run, model, scored):
    if (
        scored is None
        or scored.workspace_id != workspace.id
        or scored.run_id != run.id
        or scored.node_id != SCORE_NODE
        or scored.source != "score"
        or scored.status != "ready"
    ):
        raise ValueError("CLAIMS_COMPOSITION_SCORE_REQUIRED")
    pinned = (scored.lineage_json or {}).get("model") or {}
    if pinned.get("model_id") != model.id or pinned.get("version") != model.version:
        raise ValueError("CLAIM_TRIAGE_MODEL_MISMATCH")
    parents = scored.parent_ids or []
    prepared = db.get(TabularDataset, parents[0]) if len(parents) == 1 else None
    if (
        prepared is None
        or prepared.workspace_id != workspace.id
        or prepared.run_id != run.id
        or prepared.node_id != PREPARE_NODE
        or prepared.source != "transform"
        or prepared.status != "ready"
    ):
        raise ValueError("CLAIMS_COMPOSITION_PREPARATION_REQUIRED")
    return prepared


def _reference(dataset):
    return {
        "id": dataset.id,
        "name": dataset.name,
        "version": dataset.version,
        "rows": dataset.row_count,
    }


async def invoke_context(payload, ctx=None):
    import asyncio

    return await asyncio.to_thread(_case_context, payload, ctx or {})


def _case_context(payload, ctx):
    from app.db.base import SessionLocal
    from app.services.evaluation.judge import contractual_zero_token_usage
    from app.services.tabular_datasets import read_rows

    owns = ctx.get("db") is None
    db = ctx.get("db") or SessionLocal()
    try:
        workspace, run, _, operation, claim_id = _context(db, ctx)
        if operation != "case":
            raise ValueError("CLAIMS_COMPOSITION_CASE_REQUIRED")
        node = next(node for node in run.flow_snapshot["nodes"] if node["id"] == SCORE_NODE)
        pin = node["config"]["params"]
        model, _ = validate_model(db, workspace, pin["model_id"], pin["pinned_version"])
        scored = db.get(TabularDataset, payload.get("dataset_id"))
        prepared = _artifacts(db, workspace, run, model, scored)
        records = read_rows(scored, limit=2)
        if len(records) != 1 or records[0].get("claim_id") != claim_id:
            raise ValueError("CLAIMS_COMPOSITION_CASE_DATASET_MISMATCH")
        row = records[0]
        risk = row.get("score_1")
        if not isinstance(risk, (int, float)) or not math.isfinite(risk) or not 0 <= risk <= 1:
            raise ValueError("CLAIM_TRIAGE_SCORE_INVALID")
        facts = feature_row(row)
        quality = {key: row.get(key) for key in ("evidence_gap", "duplicate_refund_check")}
        if not all(isinstance(flag, bool) for flag in quality.values()):
            raise ValueError("CLAIMS_COMPOSITION_DATA_QUALITY_REQUIRED")
        prediction = {"score": risk, "prediction": row["prediction"], "positive_label": "1"}
        return {
            "claim_id": claim_id,
            "facts": facts,
            "quality": quality,
            "served": {"model_id": model.id, "version": model.version},
            "target": TARGET,
            "positive_label": "1",
            "score": risk,
            "predictions": [prediction],
            "prepared_dataset": _reference(prepared),
            "scored_dataset": _reference(scored),
            **contractual_zero_token_usage("postgresql:model_context"),
        }
    finally:
        if owns:
            db.close()


def read_queue(db, workspace, triage):
    from app.services.systems import flow_publication
    from app.services.tabular_datasets import TabularError, read_rows

    try:
        config = claims._config(workspace)
        model, training = validate_model(
            db, workspace, triage.get("model_id"), triage.get("model_version")
        )
        system = (
            db.query(System)
            .filter(
                System.id == triage.get("scoring_system_id"), System.workspace_id == workspace.id
            )
            .one_or_none()
        )
        if system is None or system.blueprint_key != BLUEPRINT:
            raise ValueError("CLAIMS_COMPOSITION_SYSTEM_REQUIRED")
        published = flow_publication.flow_state(db, system=system, workspace=workspace)["published"]
        if published["version_id"] != triage.get("scoring_version_id") or published[
            "flow_sha256"
        ] != triage.get("scoring_flow_sha256"):
            raise ValueError("CLAIM_TRIAGE_FLOW_CHANGED")
        base = {
            "system": {"id": system.id, "name": system.name},
            "model": {"id": model.id, "name": model.name, "version": model.version},
            "training_dataset": _reference(training),
            "training_system_id": model.system_id,
            "scoring": {
                "system_id": system.id,
                "version_id": published["version_id"],
                "flow_sha256": published["flow_sha256"],
                "ingress_id": QUEUE_INGRESS,
            },
            "thresholds": {"high": 0.6, "medium": 0.35},
            "sla_hours": 72,
            "evidence_kind": "synthetic_demo",
            "use": "queue_ordering_only",
            "composition": MODE,
        }
        scored = (
            db.query(TabularDataset)
            .join(Run, Run.id == TabularDataset.run_id)
            .filter(
                TabularDataset.workspace_id == workspace.id,
                TabularDataset.system_id == system.id,
                TabularDataset.source == "score",
                TabularDataset.node_id == SCORE_NODE,
                TabularDataset.status == "ready",
                Run.workspace_id == workspace.id,
                Run.status == "completed",
                Run.flow_sha256 == published["flow_sha256"],
                Run.input_ref["_ingress"]["ingress_id"].as_string() == QUEUE_INGRESS,
            )
            .order_by(TabularDataset.created_at.desc())
            .first()
        )
        if scored is None:
            return {**base, "status": "not_scored", "rows": []}
        run = db.get(Run, scored.run_id)
        if operation_for_run(run) != "queue":
            raise ValueError("CLAIMS_COMPOSITION_QUEUE_REQUIRED")
        prepared = _artifacts(db, workspace, run, model, scored)
        records = read_rows(scored, columns=["claim_id", "score_1"], limit=pg.MAX_ROWS + 1)
        ids = [row["claim_id"] for row in records]
        if len(ids) != len(set(ids)) or set(ids) != set(config["allowed_claim_ids"]):
            raise ValueError("CLAIM_TRIAGE_COHORT_MISMATCH")
        advice = []
        for row in records:
            risk = row["score_1"]
            if not isinstance(risk, (int, float)) or not math.isfinite(risk) or not 0 <= risk <= 1:
                raise ValueError("CLAIM_TRIAGE_SCORE_INVALID")
            advice.append(
                {
                    "claim_id": row["claim_id"],
                    "risk": risk,
                    "priority": "high" if risk >= 0.6 else "medium" if risk >= 0.35 else "low",
                }
            )
        captured = scored.ingested_at.replace(tzinfo=UTC)
        stale = datetime.now(UTC) - captured > MAX_AGE
        return {
            **base,
            "status": "stale" if stale else "ready",
            "rows": [] if stale else advice,
            "prepared_dataset": _reference(prepared),
            "scored_dataset": _reference(scored),
            "captured_at": captured.isoformat(),
            "run_id": run.id,
            "max_age_minutes": 60,
        }
    except (ValueError, TabularError, flow_publication.FlowPublicationError):
        return {"status": "unavailable", "rows": []}
