"""Model-training tasks, importable without the rest of the worker's task list.

``app.workers.tasks`` imports the RAG, OCR and visual-capture planes at module
scope; an image built to train one model family has none of their libraries
and no business loading them. So the ML tasks live here, as shared tasks: the
general worker registers them through ``tasks`` (which re-exports them) and a
family image through ``celery_ml``, which includes this module alone.
"""

from __future__ import annotations

from celery import shared_task


@shared_task(
    name="agentium.ml_train",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def ml_train(self, model_id: str) -> dict:
    """Fit one model and publish it in the MLflow model format.

    Unlike the transform tasks this one runs no author code, so it needs no
    managed venv — but it still runs as a supervised subprocess, because a fit
    cannot be cancelled from inside and a redelivery must not publish a second
    artifact for one version. The queue the task arrived on is the model
    family's, so the interpreter running this is the family's image.
    """

    from app.services.tabular_ml import run_training

    result = run_training(model_id)
    return {**result, "task_id": str(self.request.id)}


@shared_task(name="agentium.ml_forecast", acks_late=False, ignore_result=False)
def ml_forecast(model_id: str, *, horizon=None, level=None, inputs=None, explain=False) -> dict:
    """Answer one forecast request the API is waiting for.

    Runs in the ml-ts serving worker, whose threads share one cache of loaded
    models. Not acks_late: a forecast lost with its worker is retried by the
    caller, not redelivered to answer a request that already timed out. A
    refusal comes back as data, so the API can render it as a code.
    """

    from app.services.ml.forecast_serving import answer_for

    return answer_for(model_id, horizon=horizon, level=level, inputs=list(inputs or []), explain=bool(explain))


@shared_task(name="agentium.ml_forecast_batch", acks_late=True, reject_on_worker_lost=True)
def ml_forecast_batch(output_id: str, served_id: str, **kwargs) -> dict:
    """Write a whole forecast into the dataset row a Flow node reserved.

    acks_late, unlike the interactive forecast: nobody is waiting on this
    task's result, a node is polling the row, so a forecast lost with its
    worker is redelivered — and settling is idempotent on the row's status.
    """

    from app.services.ml.forecast_serving import forecast_into

    return forecast_into(output_id, served_id, **kwargs)


@shared_task(name="agentium.ml_retraining_recovery", ignore_result=True)
def ml_retraining_recovery() -> dict:
    from app.services.ml_retraining import recover_retraining
    return recover_retraining()

@shared_task(name="agentium.ml_shadow", acks_late=True, reject_on_worker_lost=True)
def ml_shadow(job_id: str) -> dict:
    from app.services.ml_shadow import run_shadow

    return run_shadow(job_id)


@shared_task(name="agentium.ml_shadow_recover")
def ml_shadow_recover() -> dict:
    from app.services.ml_shadow import recover

    return recover()


@shared_task(name="agentium.ml_deep_predict", acks_late=False, ignore_result=False)
def ml_deep_predict(model_id: str, rows: list[dict], *, explain=False, interval_level=None) -> dict:
    from app.services.ml.deep_serving import answer_for
    return answer_for(model_id, rows, explain=explain, interval_level=interval_level)
