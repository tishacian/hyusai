"""Imported sklearn pipelines (M4.3): served like tabular, never trained here.

An external model arrives as an MLflow sklearn/skops bundle validated against
its importer's own expected outputs in the isolated reader. It answers in the
API process with the tabular serving code, but nothing in this platform can
fit it again: there is no training data, so training, retraining proposals,
explanations and input drift are refused with a reason instead of offered.
"""

from __future__ import annotations

from pathlib import Path

from app.services.ml.families.base import Family

EXTERNAL = Family(
    key="external",
    tasks=("classification", "regression"),
    runtime="worker",
    queue_setting="celery_ml_tabular_queue",
    serving="in_process",
    required_modules=("sklearn", "mlflow", "skops"),
    # No training harness exists; the import validation reuses the M4.2
    # isolated reader. Declared only because every family names one.
    harness=Path(__file__).resolve().parents[3] / "resources" / "ml_requalify_harness.py",
    trainable=False,
)
