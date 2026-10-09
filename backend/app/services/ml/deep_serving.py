"""Row inference in ml-deep; API-side journaling stays in tabular_predict."""
from __future__ import annotations

from app.core.config import settings
from app.services.tabular_datasets import TabularError

TASK = "agentium.ml_deep_predict"


def answer_for(model_id: str, rows: list[dict], *, explain=False, interval_level=None) -> dict:
    from app.db.base import SessionLocal
    from app.models.tabular import MLModel
    from app.services.tabular_predict import _prediction_payload, coerce_rows

    try:
        if settings.ml_runtime != "ml-deep" and not settings.worker_eager_mode:
            raise TabularError(code="ML_RUNTIME_MISSING", message="This task requires the deep runtime.", status_code=409)
        with SessionLocal() as db:
            model = db.get(MLModel, model_id)
            if model is None or model.family != "tabular_deep" or model.status != "ready":
                raise TabularError(code="ML_MODEL_NOT_READY", message="The embedding model is not ready.", status_code=409)
            return _prediction_payload(model, coerce_rows(model, rows), explain=explain, interval_level=interval_level)
    except TabularError as exc:
        return {"error": exc.payload(), "status": exc.status_code}


def request_rows(db, model, rows, *, explain=False, interval_level=None):
    from app.services.ml.families import get_family
    from app.services.ml.runtime import serving_availability
    family = get_family(model.family)
    ready, reason = serving_availability(family, db)
    if not ready:
        raise TabularError(code="ML_FAMILY_UNAVAILABLE", message="The embedding runtime is not listening.",
                           status_code=409, details={"reason": reason})
    kwargs = {"explain": explain, "interval_level": interval_level}
    if settings.worker_eager_mode:
        result = answer_for(model.id, rows, **kwargs)
    else:
        from celery.exceptions import TimeoutError as CeleryTimeout

        from app.workers.celery_app import celery_app
        timeout = float(settings.ml_predict_timeout_s)
        pending = celery_app.send_task(TASK, args=[model.id, rows], kwargs=kwargs, queue=family.serve_queue(), expires=timeout)
        try:
            result = pending.get(timeout=timeout, propagate=False)
        except CeleryTimeout as exc:
            raise TabularError(code="ML_PREDICT_TIMEOUT", message="The embedding runtime did not answer in time.", status_code=504) from exc
        finally:
            if hasattr(pending, "forget"):
                pending.forget()
    if not isinstance(result, dict):
        raise TabularError(code="ML_PREDICT_FAILED", message="The embedding runtime failed.", status_code=500)
    if result.get("error"):
        from app.services.ml.forecast_serving import _raise_from
        _raise_from(result)
    return result
