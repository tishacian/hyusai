"""Where a model goes wrong in production, and for whom (M5).

The training-time explanation pack (``resources/ml_explanation_extensions``)
answers "where does the model fail on its test set". This module asks the same
question of production: the samples a **given model version** served, that were
later labelled through M2's per-sample feedback, and whose inputs were retained.

What is measured is the answer that was **actually served** — read from the
journal — against the label, never a re-prediction: a re-score would explain a
model that answered nobody. The same ``error_tree`` and ``fairness`` the training
pack uses read those served answers (their ``predicted=`` hook); the error tree
splits on the pipeline's own transformed columns, so it reads like the one on
the Evidence tab.

Runs as a Celery task on the general worker (inline in eager mode), on demand
(an audited WRITE action) or from the scheduled monitoring cycle, at most once
per ``ML_PRODUCTION_DEBUG_INTERVAL_MINUTES`` and only when new labels arrived.
A report is aggregated only: rules, node counts, group metrics, counts of used
and excluded samples. It never stores a production row.

Fairness monitoring is the report's per-group metric gap with a badge
(``ok | watch | alert``). A badge change raises an M3 alert
(``ml_alerts.emit_alert``, event ``fairness_gap``) in the report's own
transaction, so the report and its alert are committed together or not at all,
with M3's flag, throttling and source deduplication.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logging import get_logger
from app.models.ml_explanations import MLProductionExplanation
from app.models.ml_feedback import MLPredictionFeedback
from app.models.tabular import MLModel, MLPrediction
from app.services.tabular_datasets import TabularError

logger = get_logger(__name__)

TASK = "agentium.ml_production_debug"
ACTIVE = ("queued", "running")
FINISHED = ("completed", "insufficient_data")
BADGES = ("ok", "watch", "alert")
# Failures that analysed nothing; the same labels may be analysed again.
TRANSIENT = ("ML_PRODUCTION_DEBUG_DISPATCH_FAILED", "ML_PRODUCTION_DEBUG_STALE")
_PAGE = 200


def supported(model: MLModel) -> bool:
    """The in-process tabular family: its pipeline loads on the general worker."""

    return (model.family or "tabular") == "tabular" and model.task in {
        "classification",
        "regression",
    }


def _digest(*parts: Any) -> str:
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _window_filters(since: datetime | None, until: datetime | None) -> list[Any]:
    filters = []
    if since is not None:
        filters.append(MLPrediction.created_at >= since)
    if until is not None:
        filters.append(MLPrediction.created_at <= until)
    return filters


def _has_feedback():
    return exists().where(
        MLPredictionFeedback.prediction_id == MLPrediction.id,
        MLPredictionFeedback.workspace_id == MLPrediction.workspace_id,
    )


def _legacy_label():
    # A pre-M2 label on a one-row call names its only sample (ml_feedback).
    return and_(MLPrediction.label.isnot(None), MLPrediction.row_count == 1, ~_has_feedback())


def _served_by(model: MLModel, since=None, until=None) -> list[Any]:
    return [
        MLPrediction.workspace_id == model.workspace_id,
        MLPrediction.served_id == model.id,
        *_window_filters(since, until),
    ]


def labelled_watermark(db, model: MLModel, *, since=None, until=None) -> tuple[int, str]:
    """How many labels this version has, and a digest that moves when one changes.

    Two aggregate queries, no row read: cheap enough for every monitoring cycle.
    """

    feedback = (
        db.query(
            func.count(MLPredictionFeedback.sample_id), func.max(MLPredictionFeedback.labeled_at)
        )
        .join(
            MLPrediction,
            and_(
                MLPrediction.id == MLPredictionFeedback.prediction_id,
                MLPrediction.workspace_id == MLPredictionFeedback.workspace_id,
            ),
        )
        .filter(*_served_by(model, since, until))
        .one()
    )
    legacy = (
        db.query(func.count(MLPrediction.id), func.max(MLPrediction.labeled_at))
        .filter(*_served_by(model, since, until), _legacy_label())
        .one()
    )
    total = int(feedback[0] or 0) + int(legacy[0] or 0)
    return total, _digest(model.id, total, feedback[1], legacy[1])


def _labels_of(row: MLPrediction) -> dict[int, str]:
    labels = {
        item.sample_index: item.label
        for item in row.feedback_samples
        if item.prediction_id == row.id and item.workspace_id == row.workspace_id
    }
    if not labels and row.row_count == 1 and row.label is not None:
        labels[0] = row.label
    return labels


def collect(db, model: MLModel, *, since=None, until=None) -> dict[str, Any]:
    """The labelled production samples of this version, most recent first.

    Deterministic and bounded: journal rows are read newest first (creation
    time, then id) until ``ML_PRODUCTION_DEBUG_MAX_ROWS`` samples are usable.
    Excluded samples are counted by reason; labels beyond the ceiling are
    counted as ``beyond_max_rows`` without being read.
    """

    from app.services.ml_feedback import persisted_samples

    total, watermark = labelled_watermark(db, model, since=since, until=until)
    ceiling = int(settings.ml_production_debug_max_rows)
    excluded: Counter[str] = Counter()
    used: list[dict[str, Any]] = []
    examined = 0
    query = (
        db.query(MLPrediction)
        .options(selectinload(MLPrediction.feedback_samples))
        .filter(*_served_by(model, since, until), or_(_has_feedback(), _legacy_label()))
        .order_by(MLPrediction.created_at.desc(), MLPrediction.id.desc())
    )
    offset = 0
    while len(used) < ceiling:
        rows = query.offset(offset).limit(_PAGE).all()
        if not rows:
            break
        offset += len(rows)
        for row in rows:
            labels = _labels_of(row)
            retained = {sample["index"]: sample for sample in persisted_samples(row)}
            for index in sorted(labels):
                if len(used) >= ceiling:
                    break
                examined += 1
                sample = retained.get(index)
                if sample is None:
                    # store=false, a workspace policy refusing inputs, or a
                    # sample past the journal's per-call cap: no input to read.
                    excluded["inputs_not_retained"] += 1
                    continue
                served = sample["output"].get("prediction")
                if served is None:
                    excluded["answer_missing"] += 1
                    continue
                label = labels[index]
                if model.task == "regression":
                    served, label = _float(served), _float(label)
                    if served is None or label is None:
                        excluded["label_invalid"] += 1
                        continue
                else:
                    served, label = str(served), str(label)
                used.append({"payload": sample["payload"], "served": served, "label": label})
    if total > examined:
        excluded["beyond_max_rows"] += total - examined
    return {
        "labeled": total,
        "used": used,
        "excluded": dict(sorted(excluded.items())),
        "watermark": watermark,
    }


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value: Any) -> float | None:
    number = _float(value)
    return round(number, 6) if number is not None else None


def overall_metrics(task: str, served: list[Any], labels: list[Any]) -> dict[str, Any]:
    if not served:
        return {}
    if task == "regression":
        errors = [abs(a - b) for a, b in zip(served, labels)]
        return {
            "mae": _round(sum(errors) / len(errors)),
            "rmse": _round(math.sqrt(sum(error * error for error in errors) / len(errors))),
            "rows": len(errors),
        }
    hits = sum(int(a == b) for a, b in zip(served, labels))
    return {"accuracy": _round(hits / len(served)), "rows": len(served)}


def badge_for(gap: float | None) -> str | None:
    if gap is None:
        return None
    if gap >= float(settings.ml_fairness_alert_gap):
        return "alert"
    if gap >= float(settings.ml_fairness_watch_gap):
        return "watch"
    return "ok"


def fairness_gaps(sections: list[dict[str, Any]], *, task: str, binary: bool, overall: dict):
    """Per sensitive column: the metric gap between supported groups, and a badge.

    The same metric family as the training fairness view: equalized-odds
    difference (largest TPR or FPR gap, absolute) for a binary model, the
    accuracy gap for a multiclass one, and the MAE gap relative to the overall
    MAE for a regression. Groups smaller than ``ML_FAIRNESS_MIN_GROUP_ROWS``
    are reported but excluded from the gap: a tiny group's rate is noise.
    """

    minimum = int(settings.ml_fairness_min_group_rows)
    result = []
    for section in sections:
        groups = section.get("groups") if isinstance(section.get("groups"), list) else None
        if groups is None:
            result.append({"column": section.get("column"), "reason": section.get("error")})
            continue
        supported = [group for group in groups if int(group.get("n") or 0) >= minimum]
        entry: dict[str, Any] = {
            "column": section.get("column"),
            "groups": len(groups),
            "small_groups": len(groups) - len(supported),
        }
        gap = None
        if len(supported) < 2:
            entry["reason"] = "insufficient_groups"
        elif task == "regression":
            entry["metric"] = "mae_gap_ratio"
            maes = [group["mae"] for group in supported if group.get("mae") is not None]
            if len(maes) >= 2 and overall.get("mae"):
                gap = (max(maes) - min(maes)) / overall["mae"]
        elif binary:
            entry["metric"] = "equalized_odds_difference"
            gaps = []
            for key in ("tpr", "fpr"):
                rates = [group[key] for group in supported if group.get(key) is not None]
                if len(rates) >= 2:
                    gaps.append(max(rates) - min(rates))
            gap = max(gaps) if gaps else None
        else:
            entry["metric"] = "accuracy_gap"
            rates = [group["accuracy"] for group in supported if group.get("accuracy") is not None]
            gap = max(rates) - min(rates) if len(rates) >= 2 else None
        entry["gap"] = _round(gap)
        entry["badge"] = badge_for(gap)
        result.append(entry)
    ranked = [BADGES.index(entry["badge"]) for entry in result if entry.get("badge")]
    return result, (BADGES[max(ranked)] if ranked else None)


def _bounded(report: dict[str, Any]) -> dict[str, Any]:
    limit = int(settings.ml_production_debug_max_report_bytes)

    def size(value):
        return len(json.dumps(value, allow_nan=False, default=str).encode())

    if size(report) <= limit:
        return report
    tree = report.get("error_tree")
    if isinstance(tree, dict) and isinstance(tree.get("tree"), dict):
        # The rules stay; the drawable tree is the part that grows with depth.
        report = {**report, "error_tree": {**tree, "tree": {"error": "too_large"}}}
    return report if size(report) <= limit else {"error": "too_large"}


def numeric_matrix(pipeline: Any, x: Any) -> tuple[Any, list[str]]:
    """The pipeline's transformed columns, with categorical ones one-hot encoded.

    The error tree splits where the model's own preprocessing put the data, so
    its rules read like the training-time tree. skrub hands a boosting model
    its low-cardinality columns as pandas categoricals, which a decision tree
    cannot split; they become ``<column>_<level>`` indicators, skrub's own
    one-hot naming. A missing value is the absence of every indicator.
    """

    import pandas as pd

    from app.resources import ml_explanation_extensions as extensions

    values, names = extensions._matrix(pipeline, x)
    frame = (
        values.reset_index(drop=True)
        if isinstance(values, pd.DataFrame)
        else pd.DataFrame(values, columns=names)
    )
    frame.columns = names
    parts = []
    for name in names:
        column = frame[name]
        numeric = pd.api.types.is_numeric_dtype(column) and not isinstance(
            column.dtype, pd.CategoricalDtype
        )
        if numeric:
            parts.append(column.astype("float64").rename(name))
            continue
        parts.append(
            pd.get_dummies(column.astype("object"), prefix=name, prefix_sep="_", dtype="float64")
        )
    encoded = pd.concat(parts, axis=1) if parts else frame
    return encoded, [str(column) for column in encoded.columns]


def analyse(model: MLModel, collected: dict[str, Any]) -> dict[str, Any]:
    """Build the aggregated report from collected samples (no database access)."""

    import pandas as pd

    from app.resources import ml_explanation_extensions as extensions
    from app.services.tabular_predict import (
        _positive_label,
        build_frame,
        contract_fields,
        load_pipeline,
    )

    samples = collected["used"]
    served = [item["served"] for item in samples]
    labels = [item["label"] for item in samples]
    task = str(model.task)
    overall = overall_metrics(task, served, labels)
    entry = load_pipeline(model)
    fields = contract_fields(model)
    x = build_frame(fields, [item["payload"] for item in samples])
    y = pd.Series(labels)
    seed = int(settings.ml_train_random_state)
    report: dict[str, Any] = {"error_measure": "served_answer_vs_label", "rows": len(samples)}
    try:
        report["error_tree"] = extensions.error_tree(
            entry.pipeline,
            x,
            y,
            task=task,
            seed=seed,
            predicted=served,
            matrix=numeric_matrix(entry.pipeline, x),
        )
    except Exception as exc:  # noqa: BLE001 - each section is expendable evidence
        report["error_tree"] = {"error": type(exc).__name__}

    declared = [str(column) for column in ((model.spec_json or {}).get("fairness_columns") or [])]
    if not declared:
        report["fairness"] = {"reason": "no_sensitive_columns"}
        return {"metrics": overall, "report": _bounded(report), "badge": None}
    present = [column for column in declared if column in x.columns]
    sections: list[dict[str, Any]] = [
        {"column": column, "error": "not_in_inputs"}
        for column in declared
        if column not in x.columns
    ]
    classes = [str(value) for value in (model.classes_json or entry.classes or [])]
    positive = _positive_label(model, classes) if task == "classification" else None
    ordered = [label for label in classes if label != positive] + ([positive] if positive else [])
    if present:
        try:
            sections = (
                extensions.fairness(
                    entry.pipeline,
                    x,
                    y,
                    x[present],
                    task=task,
                    predicted=served,
                    classes=ordered or None,
                )
                + sections
            )
        except Exception as exc:  # noqa: BLE001
            sections = [
                {"column": column, "error": type(exc).__name__} for column in present
            ] + sections
    gaps, badge = fairness_gaps(
        sections, task=task, binary=task == "classification" and len(classes) == 2, overall=overall
    )
    report["fairness"] = {
        "columns": sections,
        "gaps": gaps,
        "badge": badge,
        "positive": positive,
        "thresholds": {
            "watch": float(settings.ml_fairness_watch_gap),
            "alert": float(settings.ml_fairness_alert_gap),
            "min_group_rows": int(settings.ml_fairness_min_group_rows),
        },
    }
    return {"metrics": overall, "report": _bounded(report), "badge": badge}


# ---------------------------------------------------------------------------
# Lifecycle: stage, dispatch, run
# ---------------------------------------------------------------------------


def _latest(db, model: MLModel, *, statuses=None) -> MLProductionExplanation | None:
    query = db.query(MLProductionExplanation).filter(MLProductionExplanation.model_id == model.id)
    if statuses:
        query = query.filter(MLProductionExplanation.status.in_(statuses))
    return query.order_by(
        MLProductionExplanation.created_at.desc(), MLProductionExplanation.id.desc()
    ).first()


def _expire_stale(db, model: MLModel, now: datetime) -> MLProductionExplanation | None:
    """An analysis queued or running past twice its time limit is lost, not busy."""

    active = _latest(db, model, statuses=ACTIVE)
    if active is None:
        return None
    limit = timedelta(seconds=2 * int(settings.ml_production_debug_time_limit_s))
    if (active.started_at or active.created_at) > now - limit:
        return active
    active.status, active.error_code, active.completed_at = (
        "failed",
        "ML_PRODUCTION_DEBUG_STALE",
        now,
    )
    db.flush()
    return None


def _refuse_unsupported(model: MLModel) -> None:
    if not supported(model):
        raise TabularError(
            code="ML_PRODUCTION_DEBUG_UNSUPPORTED",
            message="Production debugging covers ready tabular classification and regression models.",
            status_code=409,
            details={"family": model.family, "task": model.task},
        )
    if model.status != "ready":
        raise TabularError(
            code="ML_MODEL_NOT_READY",
            message="The model is not trained yet.",
            status_code=409,
            details={"status": model.status},
        )


def request_manual(db, *, model: MLModel, workspace, user, since=None, until=None):
    """Stage an on-demand analysis, audited in the same transaction, then dispatch it.

    The caller has already passed ``ml_permissions.require(..., "score", ...)``.
    An audit failure raises before commit, so nothing is queued unaudited.
    """

    from app.services.ml_permissions import audit

    _refuse_unsupported(model)
    if since is not None and until is not None and until < since:
        raise TabularError(
            code="ML_PRODUCTION_DEBUG_WINDOW_INVALID",
            message="The window ends before it starts.",
        )
    locked = db.query(MLModel).filter_by(id=model.id).with_for_update().one()
    now = datetime.utcnow()
    if _expire_stale(db, locked, now) is not None:
        raise TabularError(
            code="ML_PRODUCTION_DEBUG_RUNNING",
            message="An analysis of this version is already running.",
            status_code=409,
        )
    row = MLProductionExplanation(
        id=str(uuid4()),
        workspace_id=model.workspace_id,
        model_id=model.id,
        version=int(model.version or 1),
        trigger="manual",
        status="queued",
        window_from=since,
        window_until=until,
        excluded_json={},
        metrics_json={},
        report_json={},
        created_by=getattr(user, "id", None),
        created_at=now,
    )
    db.add(row)
    db.flush()
    audit(
        db,
        action="production_debug",
        workspace_id=workspace.id,
        actor=getattr(user, "id", None),
        model=model,
        after={
            "report_id": row.id,
            "window_from": since.isoformat() if since else None,
            "window_until": until.isoformat() if until else None,
        },
    )
    db.commit()
    dispatch(db, row.id)
    db.refresh(row)
    return row


def stage_scheduled(db, *, model: MLModel, now: datetime | None = None) -> dict[str, Any]:
    """Called by ``ml_retraining.monitor_cycle`` inside its transaction; never commits.

    Returns ``{"report_id": …}`` when an analysis was staged, else the reason
    it was not. Throttled to one per interval, only when the labelled-sample
    watermark moved, and idempotent: the id derives from that watermark.
    """

    if not supported(model) or model.status != "ready":
        return {"skipped": "unsupported"}
    now = now or datetime.utcnow()
    total, watermark = labelled_watermark(db, model)
    if total == 0:
        return {"skipped": "no_labels"}
    if _expire_stale(db, model, now) is not None:
        return {"skipped": "in_progress"}
    settled = (
        db.query(MLProductionExplanation)
        .filter(
            MLProductionExplanation.model_id == model.id,
            or_(
                MLProductionExplanation.status.in_(FINISHED),
                and_(
                    MLProductionExplanation.status == "failed",
                    MLProductionExplanation.error_code.notin_(TRANSIENT),
                ),
            ),
        )
        .order_by(MLProductionExplanation.created_at.desc(), MLProductionExplanation.id.desc())
        .first()
    )
    if settled is not None and settled.source_digest == watermark:
        return {"skipped": "no_new_labels"}
    latest = _latest(db, model, statuses=(*FINISHED, "failed"))
    interval = timedelta(minutes=int(settings.ml_production_debug_interval_minutes))
    if latest is not None and latest.created_at > now - interval:
        return {"skipped": "throttled"}
    report_id = _digest("ml-production-debug", model.id, "scheduled", watermark)
    existing = db.get(MLProductionExplanation, report_id)
    if existing is not None:
        if existing.status != "failed" or existing.error_code not in TRANSIENT:
            return {"skipped": "replayed"}
        # A broker refusal or a lost worker analysed nothing: same labels, retry.
        existing.status, existing.error_code, existing.created_at = "queued", None, now
        existing.started_at = existing.completed_at = None
        db.flush()
        return {"report_id": report_id}
    db.add(
        MLProductionExplanation(
            id=report_id,
            workspace_id=model.workspace_id,
            model_id=model.id,
            version=int(model.version or 1),
            trigger="scheduled",
            status="queued",
            excluded_json={},
            metrics_json={},
            report_json={},
            source_digest=watermark,
            created_at=now,
        )
    )
    db.flush()
    return {"report_id": report_id}


def dispatch(db, report_id: str) -> None:
    """Hand the staged analysis to the general worker (inline in eager mode).

    Called after the staging transaction committed, so the worker reads the
    row. A broker that refuses the message marks the row failed with a code
    rather than leaving it queued; the next cycle or a new request retries.
    """

    if settings.worker_eager_mode:
        run(report_id)
        return
    try:
        from app.workers.celery_app import celery_app

        celery_app.send_task(
            TASK,
            args=[report_id],
            queue=settings.celery_ml_tabular_queue or settings.celery_task_default_queue,
            retry=False,
        )
    except Exception:  # noqa: BLE001 - the staged row records the failure
        logger.warning("ml_production_debug: dispatch failed", report_id=report_id)
        db.query(MLProductionExplanation).filter_by(id=report_id, status="queued").update(
            {
                "status": "failed",
                "error_code": "ML_PRODUCTION_DEBUG_DISPATCH_FAILED",
                "completed_at": datetime.utcnow(),
            },
            synchronize_session=False,
        )
        db.commit()


def _claim(db, report_id: str) -> MLProductionExplanation | None:
    now = datetime.utcnow()
    changed = (
        db.query(MLProductionExplanation)
        .filter_by(id=report_id, status="queued")
        .update({"status": "running", "started_at": now}, synchronize_session=False)
    )
    db.commit()
    return db.get(MLProductionExplanation, report_id) if changed else None


def _raise_transition(db, model: MLModel, row: MLProductionExplanation) -> None:
    """An M3 alert when the fairness badge changes, in the report's transaction.

    The previous badge is the last finished report of this version that had
    one. A first observation alerts only when it is not ``ok``, like
    ``monitor_transition``; M3 throttling and source deduplication apply.
    """

    if row.fairness_badge is None:
        return
    previous = (
        db.query(MLProductionExplanation)
        .filter(
            MLProductionExplanation.model_id == model.id,
            MLProductionExplanation.id != row.id,
            MLProductionExplanation.status == "completed",
            MLProductionExplanation.fairness_badge.isnot(None),
        )
        .order_by(MLProductionExplanation.completed_at.desc(), MLProductionExplanation.id.desc())
        .first()
    )
    changed = (
        previous.fairness_badge != row.fairness_badge if previous else row.fairness_badge != "ok"
    )
    if not changed:
        return
    from app.services.ml_alerts import emit_alert

    emit_alert(
        db, model=model, event_type="fairness_gap", state=row.fairness_badge, source_id=row.id
    )


def _trim_history(db, model: MLModel) -> None:
    keep = int(settings.ml_production_debug_history)
    old = (
        db.query(MLProductionExplanation)
        .filter(
            MLProductionExplanation.model_id == model.id,
            MLProductionExplanation.status.notin_(ACTIVE),
        )
        .order_by(MLProductionExplanation.created_at.desc(), MLProductionExplanation.id.desc())
        .offset(keep)
        .all()
    )
    for row in old:
        db.delete(row)


def run(report_id: str) -> dict[str, Any]:
    """The task body: claim the staged row, analyse, persist report and alert."""

    from app.db.base import SessionLocal

    with SessionLocal() as db:
        row = _claim(db, report_id)
        if row is None:
            return {"status": "not_claimed", "report_id": report_id}
        model = db.get(MLModel, row.model_id)
        status, error, result = "completed", None, None
        collected = {"labeled": 0, "used": [], "excluded": {}, "watermark": row.source_digest}
        try:
            if model is None or model.workspace_id != row.workspace_id:
                raise TabularError(
                    code="ML_MODEL_NOT_FOUND", message="The model is gone.", status_code=404
                )
            _refuse_unsupported(model)
            collected = collect(db, model, since=row.window_from, until=row.window_until)
            if len(collected["used"]) < int(settings.ml_production_debug_min_rows):
                status = "insufficient_data"
            else:
                result = analyse(model, collected)
        except TabularError as exc:
            status, error = "failed", exc.code
        except Exception:  # noqa: BLE001 - the row records a code, never a message
            logger.exception("ml_production_debug: analysis failed", report_id=report_id)
            status, error = "failed", "ML_PRODUCTION_DEBUG_FAILED"
        db.rollback()  # nothing read above may hold a lock while the report is written
        row = db.get(MLProductionExplanation, report_id)
        if row is None or row.status != "running":
            return {"status": "lost", "report_id": report_id}
        row.status, row.error_code, row.completed_at = status, error, datetime.utcnow()
        row.labeled_count = int(collected["labeled"])
        row.used_count = len(collected["used"])
        row.excluded_json = collected["excluded"]
        row.source_digest = row.source_digest or collected.get("watermark")
        if result is not None:
            row.metrics_json = result["metrics"]
            row.report_json = result["report"]
            row.fairness_badge = result["badge"]
        elif status == "insufficient_data":
            row.report_json = {"minimum": int(settings.ml_production_debug_min_rows)}
        db.flush()  # the session does not autoflush; the queries below read this row
        model = db.get(MLModel, row.model_id)
        if model is not None and status == "completed":
            _raise_transition(db, model, row)
        if model is not None:
            _trim_history(db, model)
        db.commit()
        return {"status": status, "report_id": report_id, "error": error}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize(row: MLProductionExplanation | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "model_id": row.model_id,
        "version": row.version,
        "trigger": row.trigger,
        "status": row.status,
        "window": {"from": _iso(row.window_from), "until": _iso(row.window_until)},
        "counts": {
            "labeled": row.labeled_count,
            "used": row.used_count,
            "excluded": row.excluded_json or {},
        },
        "metrics": row.metrics_json or {},
        "report": row.report_json or {},
        "fairness_badge": row.fairness_badge,
        "error_code": row.error_code,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
    }


def view(db, model: MLModel) -> dict[str, Any]:
    """The Evidence and Monitor read: latest analysis and the fairness series."""

    rows = (
        db.query(MLProductionExplanation)
        .filter(MLProductionExplanation.model_id == model.id)
        .order_by(MLProductionExplanation.created_at.desc(), MLProductionExplanation.id.desc())
        .limit(int(settings.ml_production_debug_history))
        .all()
    )
    series = [
        {
            "report_id": row.id,
            "at": _iso(row.completed_at or row.created_at),
            "badge": row.fairness_badge,
            "gaps": [
                {"column": gap.get("column"), "metric": gap.get("metric"), "gap": gap.get("gap")}
                for gap in ((row.report_json or {}).get("fairness") or {}).get("gaps") or []
                if isinstance(gap, dict)
            ],
        }
        for row in reversed(rows)
        if row.status == "completed"
    ]
    return {
        "supported": supported(model),
        "latest": serialize(rows[0]) if rows else None,
        "series": series,
        "fairness_columns": list((model.spec_json or {}).get("fairness_columns") or []),
        "limits": {
            "min_rows": int(settings.ml_production_debug_min_rows),
            "max_rows": int(settings.ml_production_debug_max_rows),
            "interval_minutes": int(settings.ml_production_debug_interval_minutes),
            "watch_gap": float(settings.ml_fairness_watch_gap),
            "alert_gap": float(settings.ml_fairness_alert_gap),
            "min_group_rows": int(settings.ml_fairness_min_group_rows),
        },
    }


__all__ = [
    "TASK",
    "analyse",
    "badge_for",
    "collect",
    "dispatch",
    "fairness_gaps",
    "labelled_watermark",
    "request_manual",
    "run",
    "serialize",
    "stage_scheduled",
    "supported",
    "view",
]
