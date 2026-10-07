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
