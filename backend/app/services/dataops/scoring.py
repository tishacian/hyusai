"""Durable batch inference: one model version, bounded memory, immutable output."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import update

from app.core.config import settings
from app.models.recipe import RECIPE_EXECUTION_TERMINAL_STATUSES, RecipeExecution
from app.models.tabular import MLModel, MLPrediction, TabularDataset
from app.services.dataops.storage import (
    dataset_digest,
    dataset_digest_matches,
    iter_dataset_batches,
    settle_files,
    write_batches,
)
from app.services.recipe_executions import cancel_requested, finalize_execution
from app.services.tabular_datasets import (
    dataset_reference,
    reserve_frame,
    resolve_dataset_ref,
)


def submit_score(
    db,
    *,
    workspace_id,
    model_id,
    dataset_ref,
    version=None,
    output_name=None,
    run_id=None,
    node_id=None,
):
    from app.services.dataops.rollout import enabled
    from app.services.tabular_predict import contract_fields, serving_version

    if not enabled(db, workspace_id, "ml_score_streaming_enabled"):
        raise ValueError("ML_SCORE_STREAMING_DISABLED")
    requested = db.query(MLModel).filter_by(id=model_id, workspace_id=workspace_id).first()
    if requested is None:
        raise ValueError("ML_MODEL_NOT_FOUND")
    served = serving_version(db, requested, version=version)
    if served.family not in {"tabular", "clustering"}:
        raise ValueError("ML_SCORE_FAMILY_NOT_QUALIFIED")
    dataset = resolve_dataset_ref(db, workspace_id=workspace_id, ref=dataset_ref)
    from app.services.evaluation.isolation import validate_inputs

    evaluation_campaign_id = validate_inputs(
        db, run_id=run_id, workspace_id=workspace_id, datasets=[dataset]
    )
    if dataset.status != "ready":
        raise ValueError("DATASET_NOT_READY")
    if int(dataset.row_count or 0) > settings.ml_score_streaming_max_rows:
        raise ValueError("ML_SCORE_TOO_MANY_ROWS")
    fields = contract_fields(served)
    missing = {f["name"] for f in fields} - {f["name"] for f in dataset.schema_json}
    if missing:
        raise ValueError("ML_SCORE_COLUMN_MISSING")
    digest = dataset_digest(dataset)
    identity = (
        hashlib.sha256(
            json.dumps([workspace_id, run_id, node_id, served.id, dataset.id, digest]).encode()
        ).hexdigest()[:36]
        if run_id
        else str(uuid4())
    )
    existing = db.get(RecipeExecution, identity)
    if existing:
        return existing
    output = reserve_frame(
        db,
        workspace_id=workspace_id,
        name=output_name or f"{dataset.name} · scored",
        source="score",
        produced_by="ml_batch_score_v1",
        parent_ids=[dataset.id],
        run_id=run_id,
        node_id=node_id,
        commit=False,
    )
    execution = RecipeExecution(
        id=identity,
        workspace_id=workspace_id,
        evaluation_campaign_id=evaluation_campaign_id,
        run_id=run_id,
        node_id=node_id,
        status="queued",
        code_sha256=digest,
        timeout_s=settings.dataops_t0_max_timeout_s,
        input_json={
            "kind": "ml_stream_score",
            "requested_id": requested.id,
            "served_id": served.id,
            "dataset_id": dataset.id,
            "dataset_digest": digest,
            "output_id": output.id,
            "model_artifact": served.model_uri,
            "model_reader": served.runtime_json,
        },
    )
    db.add(execution)
    from app.services.dataops.compute_registry import register as register_compute

    register_compute(db, execution)
    db.commit()
    if settings.worker_eager_mode:
        run_score(execution.id)
    elif not execution.celery_task_id:
        from app.workers.celery_app import celery_app

        result = celery_app.send_task(
            "agentium.dataops_score",
            args=[execution.id],
            queue=settings.celery_dataops_queue,
            task_id=execution.id,
        )
        execution.celery_task_id = result.id
        db.commit()
    db.refresh(execution)
    return execution


def score_batches(
    batches,
    *,
    predict_batch,
    task,
    target=None,
    positive_label=None,
    interval_band=None,
    should_cancel=lambda: False,
    max_rows=None,
):
    """A generator with a bounded journal and aggregate cardinality evidence."""
    import pyarrow as pa

    evidence = {
        "input_rows": 0,
        "scored_rows": 0,
        "excluded_rows": 0,
        "exclusions": {},
        "sample_inputs": [],
        "sample_answers": [],
        "added_columns": None,
        "prediction_output": {},
        "sum": 0.0,
        "numeric_n": 0,
        "min": None,
        "max": None,
        "classes": {},
    }

    def generate():
        for batch in batches:
            if should_cancel():
                raise ValueError("ML_SCORE_CANCELLED")
            evidence["input_rows"] += batch.num_rows
            if max_rows and evidence["input_rows"] > max_rows:
                raise ValueError("ML_SCORE_TOO_MANY_ROWS")
            answers = predict_batch(batch)
            if len(answers) != batch.num_rows:
                raise ValueError("ML_SCORE_CARDINALITY_MISMATCH")
            from app.services.tabular_predict import _add_intervals

            _add_intervals(answers, interval_band)
            names = list(batch.schema.names)
            if evidence["added_columns"] is None:
                from app.services.tabular_predict import _unique_name

                prediction = _unique_name("prediction", names)
                confidence = _unique_name("confidence", [*names, prediction])
                score = _unique_name(
                    f"score_{positive_label}" if positive_label is not None else "score",
                    [*names, prediction, confidence],
                )
                evidence["added_columns"] = [prediction, confidence, score]
                evidence["prediction_output"] = {
                    "task": task,
                    "target": target,
                    "positive_label": positive_label,
                    "value_column": prediction,
                    "score_column": score,
                }
                if interval_band is not None:
                    for suffix in ("lower", "upper", "level"):
                        column = _unique_name(
                            f"{target or 'prediction'}_{suffix}",
                            [*names, *evidence["added_columns"]],
                        )
                        evidence["added_columns"].append(column)
                        evidence["prediction_output"][f"{suffix}_column"] = column
                    evidence["prediction_output"]["level"] = interval_band[0]
            predictions = [a.get("prediction") for a in answers]
            if any(v is None for v in predictions):
                raise ValueError("ML_SCORE_PREDICTION_MISSING")
            source = batch
            dtype = (
                pa.string()
                if task == "classification"
                else pa.int64()
                if task == "clustering"
                else pa.float64()
            )
            if task == "classification":
                predictions = [str(v) for v in predictions]
            values_by_column = [
                predictions,
                [a.get("confidence") for a in answers],
                [a.get("score") for a in answers],
            ]
            column_types = [dtype, pa.float64(), pa.float64()]
            if interval_band is not None:
                for suffix in ("lower", "upper", "level"):
                    values_by_column.append([a.get(suffix) for a in answers])
                    column_types.append(pa.float64())
            for name, values, kind in zip(
                evidence["added_columns"], values_by_column, column_types, strict=True
            ):
                source = source.append_column(name, pa.array(values, type=kind))
            remaining = max(0, 64 - len(evidence["sample_answers"]))
            evidence["sample_answers"].extend(answers[:remaining])
            evidence["sample_inputs"].extend(batch.slice(0, remaining).to_pylist())
            for answer in answers:
                value = answer.get("score")
                if value is None and task == "regression":
                    value = answer.get("prediction")
                if type(value) in {float, int}:
                    import math

                    if not math.isfinite(value):
                        raise ValueError("ML_SCORE_NONFINITE_PREDICTION")
                    evidence["sum"] += value
                    evidence["numeric_n"] += 1
                    evidence["min"] = (
                        value if evidence["min"] is None else min(evidence["min"], value)
                    )
                    evidence["max"] = (
                        value if evidence["max"] is None else max(evidence["max"], value)
                    )
                if task == "classification":
                    label = str(answer["prediction"])
                    if label not in evidence["classes"] and len(evidence["classes"]) >= 512:
                        raise ValueError("ML_SCORE_CLASS_BUDGET_EXCEEDED")
                    evidence["classes"][label] = evidence["classes"].get(label, 0) + 1
            evidence["scored_rows"] += batch.num_rows
            yield source

    return generate(), evidence


def run_score(execution_id):
    from app.db.base import SessionLocal
    from app.services.tabular_predict import (
        _interval_band,
        _positive_label,
        _predict_frame,
        _rows_from,
        _served_block,
        build_frame,
        contract_fields,
        load_pipeline,
    )

    with SessionLocal() as db:
        row = db.get(RecipeExecution, execution_id)
        if row is None or row.status in RECIPE_EXECUTION_TERMINAL_STATUSES:
            return {"id": execution_id, "status": row.status if row else "missing"}
        from app.services.dataops.compute_registry import start as start_compute
        from app.services.evaluation.isolation import campaign_for_run

        if not start_compute(db, row):
            return {"id": execution_id, "status": row.status}
        claimed = db.execute(
            update(RecipeExecution)
            .where(RecipeExecution.id == execution_id, RecipeExecution.status == "queued")
            .values(status="running", started_at=datetime.utcnow())
        )
        db.commit()
        if claimed.rowcount != 1:
            return {"id": execution_id, "status": "running"}
        db.refresh(row)
        spec = dict(row.input_json)
        started = time.monotonic()
        try:
            if campaign_for_run(db, row.run_id, row.workspace_id) != row.evaluation_campaign_id:
                raise ValueError("EVALUATION_RECIPE_SCOPE_INVALID")
            served = (
                db.query(MLModel)
                .filter_by(id=spec["served_id"], workspace_id=row.workspace_id, status="ready")
                .one()
            )
            if (
                served.model_uri != spec["model_artifact"]
                or served.runtime_json != spec["model_reader"]
            ):
                raise ValueError("ML_SCORE_MODEL_CHANGED")
            requested = db.get(MLModel, spec["requested_id"])
            dataset = resolve_dataset_ref(
                db, workspace_id=row.workspace_id, ref={"dataset_id": spec["dataset_id"]}
            )
            if not dataset_digest_matches(dataset, spec["dataset_digest"]):
                raise ValueError("ML_SCORE_INPUT_CHANGED")
            output = db.get(TabularDataset, spec["output_id"])
            from app.services.execution.io_lease import maintain

            with maintain(
                RecipeExecution, row.id, getattr(row, "_native_lease_token", None), status="running"
            ):
                entry = load_pipeline(served)
            fields = contract_fields(served)
            positive = _positive_label(served, entry.classes)
            band = _interval_band(served)

            def predict(batch):
                if time.monotonic() - started > row.timeout_s:
                    raise ValueError("ML_SCORE_TIMEOUT")
                frame = build_frame(fields, batch.select([f["name"] for f in fields]).to_pylist())
                predicted, probabilities = _predict_frame(entry, served, frame)
                return _rows_from(served, entry.classes, positive, predicted, probabilities)

            batches, evidence = score_batches(
                iter_dataset_batches(dataset),
                predict_batch=predict,
                task=served.task,
                target=served.target,
                positive_label=positive,
                interval_band=band,
                should_cancel=lambda: cancel_requested(db, execution_id),
                max_rows=settings.ml_score_streaming_max_rows,
            )
            iterator = iter(batches)
            with maintain(
                RecipeExecution, row.id, getattr(row, "_native_lease_token", None), status="running"
            ):
                first = next(iterator, None)
            if first is None:
                raise ValueError("ML_SCORE_EMPTY_DATASET")
            import itertools

            with tempfile.TemporaryDirectory(prefix="stream-score-") as tmp:
                root = Path(tmp)
                with maintain(
                    RecipeExecution,
                    row.id,
                    getattr(row, "_native_lease_token", None),
                    status="running",
                ):
                    paths = write_batches(
                        root,
                        itertools.chain([first], iterator),
                        schema=first.schema,
                        delta=settings.dataops_write_delta_enabled,
                    )
                if (
                    evidence["input_rows"] != int(dataset.row_count or 0)
                    or evidence["scored_rows"] + evidence["excluded_rows"] != evidence["input_rows"]
                ):
                    raise ValueError("ML_SCORE_CARDINALITY_MISMATCH")
                # The watchdog/cancellation path owns the same row lock. Refresh
                # its authority before the first output mutation or ready flush,
                # then hold it through settlement, journaling and the final commit.
                from app.services.dataops.compute_registry import begin_settlement

                begin_settlement(db, row)
                row = (
                    db.query(RecipeExecution)
                    .filter_by(id=execution_id)
                    .with_for_update()
                    .populate_existing()
                    .one()
                )
                if row.status != "running":
                    raise ValueError("ML_SCORE_FENCE_LOST")
                if row.cancel_requested:
                    raise ValueError("ML_SCORE_CANCELLED")
                output.lineage_json = {
                    "engine": "sklearn",
                    "placement": "local",
                    "model": {
                        "model_id": served.id,
                        "slug": served.slug,
                        "version": served.version,
                        "task": served.task,
                        "algo": served.algo,
                        "target": served.target,
                    },
                    "prediction_output": evidence["prediction_output"],
                    "added_columns": evidence["added_columns"],
                    "cardinality": {
                        "input_rows": evidence["input_rows"],
                        "scored_rows": evidence["scored_rows"],
                        "excluded_rows": evidence["excluded_rows"],
                    },
                }
                if campaign_for_run(db, row.run_id, row.workspace_id) != row.evaluation_campaign_id:
                    raise ValueError("EVALUATION_RECIPE_SCOPE_INVALID")
                settle_files(
                    db,
                    output,
                    paths,
                    delta_root=root if settings.dataops_write_delta_enabled else None,
                )
            elapsed = round((time.monotonic() - started) * 1000, 1)
            summary = {
                "n": evidence["scored_rows"],
                "mean": evidence["sum"] / evidence["numeric_n"] if evidence["numeric_n"] else None,
                "min": evidence["min"],
                "max": evidence["max"],
                "predictions": evidence["classes"],
            }
            from app.services.ml_governance import inputs_allowed
            from app.services.ml_operations import record_inference

            persist_inputs = inputs_allowed(db, row.workspace_id, True)
            journal = MLPrediction(
                evaluation_campaign_id=row.evaluation_campaign_id,
                workspace_id=row.workspace_id,
                model_id=requested.id,
                served_id=served.id,
                served_version=served.version,
                slug=served.slug,
                caller="score",
                row_count=evidence["scored_rows"],
                payload_json=evidence["sample_inputs"] if persist_inputs else [],
                input_storage_allowed=persist_inputs,
                output_json=evidence["sample_answers"],
                scores_json=summary,
                duration_ms=elapsed,
                dataset_id=output.id if persist_inputs else None,
            )
            db.add(journal)
            db.flush()
            if row.evaluation_campaign_id is None:
                record_inference(
                    db,
                    requested=requested,
                    served=served,
                    caller="score",
                    row_count=evidence["scored_rows"],
                    duration_ms=elapsed,
                    event_id=journal.id,
                )
                served.predict_count = int(served.predict_count or 0) + evidence["scored_rows"]
                served.last_predict_at = datetime.utcnow()
            row.output_json = {
                **dataset_reference(output),
                "model": _served_block(served),
                "scored_rows": evidence["scored_rows"],
                "excluded_rows": 0,
                "added_columns": evidence["added_columns"],
                "duration_ms": elapsed,
                "prediction_id": journal.id,
            }
            finalize_execution(row, status="succeeded", exit_code=0)
            db.commit()
        except Exception as exc:
            db.rollback()
            row = (
                db.query(RecipeExecution)
                .filter_by(id=execution_id)
                .with_for_update()
                .populate_existing()
                .one()
            )
            if row.status not in RECIPE_EXECUTION_TERMINAL_STATUSES or getattr(
                row, "_native_lease_token", None
            ):
                finalize_execution(
                    row,
                    status="cancelled" if row.cancel_requested else "failed",
                    error=str(exc)[:480],
                )
            output = db.get(TabularDataset, spec["output_id"])
            if output and output.status == "ingesting":
                output.status, output.error = "failed", str(exc)[:480]
            if row.status in {"failed", "cancelled"}:
                from app.services.ml_operations import record_inference

                requested = (
                    db.query(MLModel)
                    .filter_by(
                        id=spec.get("requested_id"),
                        workspace_id=row.workspace_id,
                    )
                    .first()
                )
                served = (
                    db.query(MLModel)
                    .filter_by(
                        id=spec.get("served_id"),
                        workspace_id=row.workspace_id,
                    )
                    .first()
                )
                if (
                    requested is not None
                    and served is not None
                    and row.evaluation_campaign_id is None
                ):
                    record_inference(
                        db,
                        requested=requested,
                        served=served,
                        caller="score",
                        row_count=0,
                        duration_ms=round((time.monotonic() - started) * 1000, 1),
                        error_code="ML_SCORE_CANCELLED" if row.status == "cancelled" else str(exc),
                        event_id=f"stream-score-failure:{row.id}",
                    )
            db.commit()
        return {"id": row.id, "status": row.status, "output": row.output_json}
