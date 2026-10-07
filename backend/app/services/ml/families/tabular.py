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
    spec_fields=(
        SpecField("tuning", "enum", default="off", choices=("off", "budget")),
        SpecField("tuning_trials", "int", default=30, minimum=5, maximum=100,
                  when=(("tuning", ("budget",)),)),
        SpecField("tuning_budget_s", "int", default=300, minimum=30, maximum=1500,
                  when=(("tuning", ("budget",)),)),
    ),
    required_modules=("sklearn", "skrub", "skore", "mlflow", "skops"),
    harness=Path(__file__).resolve().parents[3] / "resources" / "ml_train_harness.py",
)
