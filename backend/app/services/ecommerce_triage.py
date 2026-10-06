"""Native model advice for Luma queue ordering, separate from financial authority."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from app.models.run import Run
from app.models.system import System
from app.models.tabular import MLModel, TabularDataset
from app.models.workspace import Workspace
from app.services import ecommerce_claims as claims
from app.services.connectors.generic import postgresql_claims as pg
from app.services.ecommerce_install import BLUEPRINT

FEATURE_SKILL = "ecommerce_sla_features_v1"
FEATURE_DATASET_SKILL = "ecommerce_sla_dataset_v1"
FEATURES = [
    "claim_reason",
    "paid_amount",
    "shipment_status",
    "already_refunded",
    "case_documents",
    "item_quantity",
]
TARGET = "resolution_over_72h"
SCORE_ROLE = "luma-sla-scoring-v1"
MAX_AGE = timedelta(hours=1)


def feature_row(row):
    """Reject missing facts; share the training schema with online and batch scoring."""
    try:
        features = {key: row[key] for key in FEATURES}
        features["claim_reason"] = str(features["claim_reason"]).strip().lower()
        features["shipment_status"] = str(features["shipment_status"]).strip().lower()
        features["paid_amount"] = float(features["paid_amount"])
        for key in ("already_refunded", "case_documents", "item_quantity"):
            number = float(features[key])
            if not math.isfinite(number) or not number.is_integer():
                raise ValueError()
            features[key] = int(number)
        if (
            features["claim_reason"] not in {"delivery_disputed", "parcel_lost", "refund_requested"}
            or features["shipment_status"] not in {"delivered", "lost", "in_transit"}
            or not math.isfinite(features["paid_amount"])
            or features["paid_amount"] < 0
            or features["already_refunded"] not in {0, 1}
            or features["case_documents"] < 0
            or features["item_quantity"] < 1
        ):
            raise ValueError()
        return features
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("CLAIM_TRIAGE_FEATURES_INVALID") from None


def validate_model(db, workspace, model_id, version):
    model = (
        db.query(MLModel)
        .filter(
            MLModel.workspace_id == workspace.id,
            MLModel.id == model_id,
        )
        .one_or_none()
    )
    if (
        model is None
        or model.status != "ready"
        or model.version != version
        or model.task != "classification"
        or model.target != TARGET
        or list(model.features or []) != FEATURES
        or list(model.classes_json or []) != ["0", "1"]
    ):
        raise ValueError("CLAIM_TRIAGE_MODEL_MISMATCH")
    dataset = (
        db.query(TabularDataset)
        .filter(
            TabularDataset.workspace_id == workspace.id,
            TabularDataset.id == model.dataset_id,
            TabularDataset.status == "ready",
        )
        .one_or_none()
    )
    if dataset is None:
        raise ValueError("CLAIM_TRIAGE_TRAINING_DATASET_UNAVAILABLE")
    return model, dataset


async def invoke(payload, ctx=None, *, batch=False):
    """The persisted Run owns the claim/cohort, never payload or agent arguments."""
    import asyncio

    return await asyncio.to_thread(_extract, ctx or {}, batch=batch)


def _extract(ctx, *, batch=None):
    from app.db.base import SessionLocal
    from app.services.evaluation.judge import contractual_zero_token_usage
    from app.services.flow_data_sources import require_postgresql_binding
    from app.services.tabular_datasets import dataset_reference, register_frame

    owns_db = ctx.get("db") is None
    db = ctx.get("db") or SessionLocal()
    try:
        workspace = (
            db.query(Workspace).filter(Workspace.id == ctx.get("workspace_id")).one_or_none()
        )
        run = (
            db.query(Run)
            .filter(Run.id == ctx.get("run_id"), Run.workspace_id == ctx.get("workspace_id"))
            .one_or_none()
        )
        if workspace is None or run is None:
            raise ValueError("CLAIM_TRIAGE_RUN_REQUIRED")
        config = claims._config(workspace)
        triage = config.get("triage") or {}
        system = (
            db.query(System)
            .filter(System.id == run.system_id, System.workspace_id == workspace.id)
            .one_or_none()
        )
        is_batch = run.system_id == triage.get("scoring_system_id")
        if batch is not None and is_batch != batch:
            raise ValueError("CLAIM_TRIAGE_SKILL_SHAPE_MISMATCH")
        if system is None or (not is_batch and system.blueprint_key != BLUEPRINT):
            raise ValueError("CLAIM_TRIAGE_SYSTEM_MISMATCH")
        if is_batch:
            if (system.settings or {}).get("demo_role") != SCORE_ROLE:
                raise ValueError("CLAIM_TRIAGE_SYSTEM_MISMATCH")
            cohort = config["allowed_claim_ids"]
        else:
            claim_id = (run.input_ref or {}).get("claim_id")
            if claim_id not in config["allowed_claim_ids"]:
                raise ValueError("CLAIM_OUTSIDE_DEMO_SCOPE")
            cohort = [claim_id]
        source = require_postgresql_binding(
            run, ctx.get("_flow_data_sources", []), resources=pg.CLAIM_RESOURCES
        )
        if source is None:
            raise ValueError("CLAIM_TRIAGE_POSTGRESQL_BINDING_REQUIRED")
        result = pg.features(workspace, cohort)
        rows = [
            {"claim_id": row["claim_id"], **feature_row(row)} for row in result["data"]["features"]
        ]
        provenance = {
            **result["provenance"],
            "flow_data_source": source,
            "feature_contract": FEATURES,
        }
        if not is_batch:
            return {
                "claim_id": cohort[0],
                "rows": [{key: rows[0][key] for key in FEATURES}],
                "provenance": provenance,
                **contractual_zero_token_usage("postgresql:triage_features"),
            }
        import polars as pl

        dataset = register_frame(
            db,
            workspace_id=workspace.id,
            name="Luma — Variables de priorisation SAV",
            frame=pl.DataFrame(rows),
            source="postgresql",
            produced_by=FEATURE_DATASET_SKILL,
            run_id=run.id,
            node_id=ctx.get("node_id") or "features",
            created_by=run.initiated_by_user_id,
            description="Variables SAV calculées depuis PostgreSQL, avant toute résolution. Démonstration synthétique.",
            lineage={
                "engine": "postgresql",
                "provenance": provenance,
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
        if owns_db:
            db.commit()
        return {
            **dataset_reference(dataset),
            "provenance": provenance,
            **contractual_zero_token_usage("postgresql:triage_features"),
        }
    finally:
        if owns_db:
            db.close()


def read_triage(db, workspace):
    """Read persisted batch predictions; a Work page load never runs inference."""
    from app.services.systems import flow_publication
    from app.services.tabular_datasets import TabularError, read_rows

    config = claims._config(workspace)
    triage = config.get("triage") or {}
    if not triage:
        return {"status": "not_configured", "rows": []}
    if triage.get("composition") == "composed_v1":
        from app.services.ecommerce_composition import read_queue

        return read_queue(db, workspace, triage)
    try:
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
        if system is None or (system.settings or {}).get("demo_role") != SCORE_ROLE:
            raise ValueError("CLAIM_TRIAGE_SYSTEM_MISMATCH")
        state = flow_publication.flow_state(db, system=system, workspace=workspace)
        published = state["published"]
        if published["version_id"] != triage.get("scoring_version_id") or published[
            "flow_sha256"
        ] != triage.get("scoring_flow_sha256"):
            raise ValueError("CLAIM_TRIAGE_FLOW_CHANGED")
        base = {
            "model": {
                "id": model.id,
                "name": model.name,
                "version": model.version,
                "target": model.target,
                "features": model.features,
            },
            "training_dataset": {
                "id": training.id,
                "name": training.name,
                "rows": training.row_count,
            },
            "training_system_id": triage.get("training_system_id"),
            "scoring": {
                "system_id": system.id,
                "version_id": published["version_id"],
                "flow_sha256": published["flow_sha256"],
                "ingress_id": "start",
            },
            "thresholds": {"high": 0.6, "medium": 0.35},
            "sla_hours": 72,
            "evidence_kind": "synthetic_demo",
            "use": "queue_ordering_only",
        }
        scored = (
            db.query(TabularDataset)
            .join(Run, Run.id == TabularDataset.run_id)
            .filter(
                TabularDataset.workspace_id == workspace.id,
                TabularDataset.system_id == system.id,
                TabularDataset.source == "score",
                TabularDataset.node_id == "score",
                TabularDataset.status == "ready",
                Run.workspace_id == workspace.id,
                Run.status == "completed",
                Run.flow_sha256 == published["flow_sha256"],
            )
            .order_by(TabularDataset.created_at.desc())
            .first()
        )
        if scored is None:
            return {**base, "status": "not_scored", "rows": []}
        pinned = (scored.lineage_json or {}).get("model") or {}
        if pinned.get("model_id") != model.id or pinned.get("version") != model.version:
            raise ValueError("CLAIM_TRIAGE_MODEL_MISMATCH")
        records = read_rows(scored, columns=["claim_id", "score_1"], limit=pg.MAX_ROWS + 1)
        ids = [row["claim_id"] for row in records]
        if len(ids) != len(set(ids)) or set(ids) != set(config["allowed_claim_ids"]):
            raise ValueError("CLAIM_TRIAGE_COHORT_MISMATCH")
        advice = []
        for row in records:
            score = row["score_1"]
            if (
                not isinstance(score, (float, int))
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise ValueError("CLAIM_TRIAGE_SCORE_INVALID")
            advice.append(
                {
                    "claim_id": row["claim_id"],
                    "risk": score,
                    "priority": "high" if score >= 0.6 else "medium" if score >= 0.35 else "low",
                }
            )
        captured = scored.ingested_at.replace(tzinfo=UTC)
        stale = datetime.now(UTC) - captured > MAX_AGE
        return {
            **base,
            "status": "stale" if stale else "ready",
            "rows": [] if stale else advice,
            "captured_at": captured.isoformat(),
            "run_id": scored.run_id,
            "scored_dataset": {
                "id": scored.id,
                "name": scored.name,
                "version": scored.version,
                "rows": scored.row_count,
            },
            "max_age_minutes": 60,
        }
    except (ValueError, TabularError, flow_publication.FlowPublicationError):
        return {"status": "unavailable", "rows": []}
