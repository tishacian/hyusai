"""Bounded metadata accounting, with mergeable latency distributions.

No payloads or outputs are copied here. Quantiles are histogram upper bounds,
never averages of per-window percentiles. Unknown cost is not zero cost.
"""

import hashlib
import math
import re
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.ml_operations import MLInferenceUsage, MLUsageRollup
from app.models.tabular import MLModel

# Fixed upper bounds in milliseconds make both memory and error explicit.
LATENCY_BOUNDS = tuple(
    float(x)
    for x in (
        1,
        2,
        5,
        10,
        20,
        50,
        100,
        200,
        500,
        1000,
        2000,
        5000,
        10000,
        20000,
        50000,
        100000,
        200000,
        500000,
        1000000,
        2000000,
        5000000,
    )
)
CALLERS = frozenset({"session", "api_key", "score", "skill", "flow", "forecast", "unknown"})
logger = get_logger(__name__)


@contextmanager
def _failure_accounting_session(db):
    """Bound optional telemetry without changing the caller's SQL timeouts.

    A refused inference must not wait for a concurrent model publication or
    alert transaction. SET LOCAL lasts only until this independent transaction
    commits or rolls back; closing the session also rolls back failed writes.
    """
    with Session(bind=db.get_bind()) as audit_db:
        if audit_db.get_bind().dialect.name == "postgresql":
            audit_db.execute(text("SET LOCAL lock_timeout = '250ms'"))
            audit_db.execute(text("SET LOCAL statement_timeout = '1s'"))
        yield audit_db


def record_exposure_refusal(db, model):
    """Preserve an exposure-quota alert after the rejected key/publication write."""
    if not bool(getattr(settings, "ml_alerts_enabled", False)):
        return
    model_id, workspace_id = model.id, model.workspace_id
    db.rollback()
    try:
        from app.services.ml_alerts import emit_alert

        with _failure_accounting_session(db) as audit_db:
            requested = audit_db.get(MLModel, model_id)
            if requested and requested.workspace_id == workspace_id:
                emit_alert(
                    audit_db,
                    model=requested,
                    event_type="quota_reached",
                    state="ML_EXPOSURE_QUOTA_EXCEEDED",
                    source_id=str(uuid4()),
                )
                audit_db.commit()
    except Exception:
        logger.warning("ml_operations: quota accounting unavailable", model_id=model_id)


@contextmanager
def inference_attempt(db, *, model, caller):
    """Record refused/failed serving attempts after their transaction is rolled back.

    Serving owns its transaction (admission and journals already commit). Success
    is recorded by the journal, in its transaction. Failure metadata gets a fresh
    transaction so the caller's subsequent rollback cannot erase an alert. No
    request values or exception messages enter this accounting.
    """
    active = enabled() or bool(getattr(settings, "ml_alerts_enabled", False))
    if not active:
        yield {}
        return
    model_id, workspace_id = model.id, model.workspace_id
    observation = {"served_id": model_id}
    started = time.monotonic()
    try:
        yield observation
    except Exception as exc:
        duration_ms = (time.monotonic() - started) * 1000
        code = getattr(exc, "code", "ML_INFERENCE_FAILED")
        # Release any failed reservation/row lock before the independent write.
        db.rollback()
        try:
            with _failure_accounting_session(db) as audit_db:
                requested = audit_db.get(MLModel, model_id)
                served = audit_db.get(MLModel, observation["served_id"])
                if requested and served and requested.workspace_id == workspace_id:
                    record_inference(
                        audit_db,
                        requested=requested,
                        served=served,
                        caller=caller,
                        row_count=0,
                        duration_ms=duration_ms,
                        error_code=code,
                    )
                    if code == "ML_RATE_LIMITED":
                        from app.services.ml_alerts import emit_alert

                        emit_alert(
                            audit_db,
                            model=requested,
                            event_type="quota_reached",
                            state=code,
                            source_id=str(uuid4()),
                        )
                    audit_db.commit()
        except Exception:
            # Do not replace the original serving error with a telemetry error.
            logger.warning("ml_operations: failure accounting unavailable", model_id=model_id)
        raise


def enabled():
    return bool(getattr(settings, "ml_operations_enabled", False))


def digest(*parts):
    return hashlib.sha256("\x00".join(map(str, parts)).encode()).hexdigest()


def nonnegative(value):
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def record_inference(
    db,
    *,
    requested,
    served,
    caller,
    row_count,
    duration_ms,
    error_code=None,
    measured_cost_usd=None,
    cpu_seconds=None,
    tariff_cost_usd=None,
    event_id=None,
):
    if not enabled():
        return None
    if requested.workspace_id != served.workspace_id:
        raise ValueError("ML_USAGE_SCOPE_INVALID")
    row_id = digest(requested.workspace_id, event_id) if event_id else None
    if row_id and db.get(MLInferenceUsage, row_id):
        return row_id
    safe_code = (
        error_code
        if isinstance(error_code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", error_code)
        else "ML_INFERENCE_FAILED"
        if error_code
        else None
    )
    tariff = None
    if tariff_cost_usd is None and not error_code:
        from app.services.ml_inference_cost import inference_tariff

        tariff = inference_tariff(db, model=requested, row_count=row_count)
        tariff_cost_usd = tariff.cost if tariff.cost_measured else None
    row = MLInferenceUsage(
        **({"id": row_id} if row_id else {}),
        workspace_id=requested.workspace_id,
        model_id=requested.id,
        served_id=served.id,
        version=served.version,
        caller=caller if caller in CALLERS else "unknown",
        row_count=max(0, int(row_count)),
        duration_ms=nonnegative(duration_ms),
        error_code=safe_code,
        cpu_seconds=nonnegative(cpu_seconds),
        measured_cost_usd=nonnegative(measured_cost_usd),
        tariff_cost_usd=nonnegative(tariff_cost_usd),
        tariff_evidence=tariff.evidence if tariff else None,
    )
    if row_id:
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            # A replay may race another worker. Only the same event identity
            # can be accepted as an idempotent collision; other errors escape.
            if db.get(MLInferenceUsage, row_id) is None:
                raise
    else:
        db.add(row)
        db.flush()
    return row_id or row.id


def bucket(value):
    if value is None:
        return None
    return str(next((bound for bound in LATENCY_BOUNDS if value <= bound), "overflow"))


def quantile(histogram, q):
    count = sum(histogram.values())
    if not count:
        return None
    position, seen = math.ceil(count * q), 0
    for key in sorted(histogram, key=lambda x: math.inf if x == "overflow" else float(x)):
        seen += histogram[key]
        if seen >= position:
            return None if key == "overflow" else float(key)
    return None


def rollup_usage(db, *, limit=None, now=None):
    now = now or datetime.utcnow()
    limit = limit or int(getattr(settings, "ml_usage_rollup_batch_size", 10000))
    # Lock models in a stable order before their usage. A second worker cannot
    # create or amend the same aggregate concurrently; skipped work is retried.
    model_ids = [
        item[0]
        for item in db.query(MLInferenceUsage.model_id)
        .filter(MLInferenceUsage.rolled_up_at.is_(None))
        .distinct()
        .limit(100)
        .all()
    ]
    count = 0
    for model_id in sorted(model_ids):
        model = db.query(MLModel).filter_by(id=model_id).with_for_update(skip_locked=True).first()
        if model is None:
            continue
        events = (
            db.query(MLInferenceUsage)
            .filter_by(model_id=model_id, rolled_up_at=None)
            .order_by(MLInferenceUsage.created_at, MLInferenceUsage.id)
            .limit(limit - count)
            .with_for_update(skip_locked=True)
            .all()
        )
        for event in events:
            stamp = event.created_at.replace(
                minute=event.created_at.minute // 5 * 5, second=0, microsecond=0
            )
            identity = digest(
                event.model_id, event.served_id, event.version, event.caller, stamp.isoformat()
            )
            row = db.get(MLUsageRollup, identity)
            if row is None:
                row = MLUsageRollup(
                    id=identity,
                    workspace_id=event.workspace_id,
                    model_id=event.model_id,
                    served_id=event.served_id,
                    version=event.version,
                    caller=event.caller,
                    interval_start=stamp,
                )
                db.add(row)
                db.flush()
            row.requests += 1
            row.rows += event.row_count
            row.errors += int(event.error_code is not None)
            histogram = dict(row.latency_histogram)
            key = bucket(event.duration_ms)
            if key is not None:
                histogram[key] = histogram.get(key, 0) + 1
            row.latency_histogram = histogram
            if event.cpu_seconds is not None:
                row.cpu_seconds += event.cpu_seconds
                row.cpu_requests += 1
            if event.measured_cost_usd is not None:
                row.measured_cost_usd += event.measured_cost_usd
                row.measured_rows += event.row_count
                row.measured_requests += 1
            if event.tariff_cost_usd is not None:
                row.tariff_cost_usd += event.tariff_cost_usd
                row.tariff_requests += 1
                row.tariff_rows += event.row_count
            row.updated_at = event.rolled_up_at = now
            count += 1
        if count >= limit:
            break
    db.flush()
    return count


def summarize(rows):
    histogram = Counter()
    requests = lines = errors = measured_rows = measured_requests = tariff_requests = 0
    measured = tariff = cpu = 0.0
    cpu_requests = tariff_rows = 0
    as_of = None
    for row in rows:
        histogram.update(row.latency_histogram)
        requests += row.requests
        lines += row.rows
        errors += row.errors
        measured_rows += row.measured_rows
        measured_requests += row.measured_requests
        tariff_requests += row.tariff_requests
        tariff_rows += row.tariff_rows
        cpu_requests += row.cpu_requests
        measured += row.measured_cost_usd
        tariff += row.tariff_cost_usd
        cpu += row.cpu_seconds
        as_of = max(as_of, row.updated_at) if as_of else row.updated_at
    return {
        "requests": requests,
        "rows": lines,
        "errors": errors,
        "error_rate": errors / requests if requests else None,
        "p50_ms": quantile(histogram, 0.5),
        "p95_ms": quantile(histogram, 0.95),
        "quantile_method": "histogram_upper_bound",
        "latency_observations": sum(histogram.values()),
        "latency_overflow": histogram.get("overflow", 0),
        "cpu_seconds": cpu if cpu_requests else None,
        "cpu_requests": cpu_requests,
        "measured_cost_usd": measured if measured_requests else None,
        "measured_cost_per_1000_rows_usd": 1000 * measured / measured_rows
        if measured_rows
        else None,
        "measured_requests": measured_requests,
        "unknown_cost_requests": requests - measured_requests,
        "tariff_cost_usd": tariff if tariff_requests else None,
        "tariff_cost_per_1000_rows_usd": 1000 * tariff / tariff_rows if tariff_rows else None,
        "tariff_requests": tariff_requests,
        "tariff_rows": tariff_rows,
        "as_of": as_of.isoformat() if as_of else None,
    }


def model_metrics(db, model, *, now=None):
    now = now or datetime.utcnow()
    # Both windows are aligned to complete 5-minute boundaries, and return the
    # actual range rather than implying exact sliding-window precision.
    end = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0)
    rows = (
        db.query(MLUsageRollup)
        .filter(
            MLUsageRollup.workspace_id == model.workspace_id,
            MLUsageRollup.model_id == model.id,
            MLUsageRollup.interval_start >= end - timedelta(days=7),
            MLUsageRollup.interval_start < end,
        )
        .all()
    )
    return {
        name: {
            **summarize([row for row in rows if row.interval_start >= end - duration]),
            "from": (end - duration).isoformat(),
            "until": end.isoformat(),
        }
        for name, duration in (("24h", timedelta(days=1)), ("7d", timedelta(days=7)))
    }
