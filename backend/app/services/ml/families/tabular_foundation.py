"""Experimental frozen TabICL family, isolated from ordinary sklearn recipes."""

from pathlib import Path

from app.services.ml.families.base import Family, SpecField


def require_qualified_profile(task, spec):
    """Keep a failed development profile out of training and serving."""
    from app.services.tabular_datasets import TabularError

    if task == "regression" and (spec or {}).get("kv_cache") is not True:
        raise TabularError(
            code="ML_TABICL_PROFILE_UNQUALIFIED",
            message="TabICL regression without cache failed reload parity; explicitly select kv_cache=true.",
            status_code=409,
            details={
                "task": "regression",
                "kv_cache": False,
                "required_kv_cache": True,
                "reason": "reload_parity",
            },
        )


def validate_tabicl(
    dataset, *, task, target, features, algo, knobs, test_size, cross_validation, name, spec
):
    from app.services.tabular_datasets import TabularError
    from app.services.tabular_ml import ALGO_BY_KEY, validate_training

    require_qualified_profile(task, spec)
    if knobs not in (None, {}) or cross_validation not in (None, 0, 1):
        raise TabularError(
            code="ML_DEEP_OPTION_UNSUPPORTED",
            message="TabICL pilot has fixed weights and one recorded holdout; no free tuning or CV.",
        )
    result = validate_training(
        dataset,
        task=task,
        target=target,
        features=features,
        algo="gradient_boosting",
        knobs={},
        test_size=test_size,
        cross_validation=0,
        name=name,
        spec={},
    )
    if len(result.features) > 100 or int(dataset.row_count or 0) > 10_000:
        raise TabularError(
            code="ML_SPEC_INVALID",
            message="TabICL pilot supports at most 10000 rows and 100 features.",
        )
    result.family = "tabular_foundation"
    result.algo = ALGO_BY_KEY["tabicl_v2"]
    result.knobs = {}
    result.spec = spec
    result.warnings.append({"code": "ML_TABICL_EXPERIMENTAL", "reason": "value_not_qualified"})
    return result


TABULAR_FOUNDATION = Family(
    key="tabular_foundation",
    tasks=("classification", "regression"),
    runtime="ml-deep",
    serving="remote",
    queue_setting="celery_ml_deep_queue",
    serve_queue_setting="celery_ml_deep_serve_queue",
    required_modules=("torch", "tabicl", "safetensors", "mlflow"),
    harness=Path(__file__).resolve().parents[3] / "resources" / "ml_tabicl_harness.py",
    spec_fields=(
        SpecField("artifact_id", "artifact", required=True),
        SpecField("kv_cache", "bool", default=False),
    ),
    validator=validate_tabicl,
)
