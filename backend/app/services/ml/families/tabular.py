"""The tabular family: scikit-learn pipelines over skrub, judged by skore.

Declares what already existed before families did — classification and
regression trained by ``ml_train_harness.py`` on the general worker and served
inside the API process — so routing through the registry changes nothing for
it. Its lifecycle code stays in ``tabular_ml``.
"""

from __future__ import annotations

from pathlib import Path

from app.services.ml.families.base import Family, SpecField

CLASSIFICATION = "classification"
REGRESSION = "regression"

TABULAR = Family(
    key="tabular",
    tasks=(CLASSIFICATION, REGRESSION),
    runtime="worker",
    queue_setting="celery_ml_tabular_queue",
    serving="in_process",
    required_modules=("sklearn", "skrub", "skore", "mlflow", "skops"),
    spec_fields=(
        SpecField("calibration", "enum", default="off", choices=("off", "auto", "sigmoid", "isotonic"), when=(("task", (CLASSIFICATION,)),)),
        SpecField("threshold", "enum", default="default", choices=("default", "f1", "youden"), when=(("task", (CLASSIFICATION,)),)),
    ),
    harness=Path(__file__).resolve().parents[3] / "resources" / "ml_train_harness.py",
    spec_fields=(
        SpecField("intervals", "enum", default="off", choices=("off", "conformal"),
                  when=(("task", (REGRESSION,)),)),
    ),
)
