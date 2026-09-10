"""Bounded operational targets. No expressions, code or user-selected units."""
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Metric = Literal[
    "completed_volume",
    "mean_duration_ms",
    "human_waits",
    "human_validation_rate",
    "measured_cost_usd",
]
UNITS = {
    "completed_volume": "runs",
    "mean_duration_ms": "ms",
    "human_waits": "runs",
    "human_validation_rate": "%",
    "measured_cost_usd": "USD",
}


class OperationalObjective(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)
    metric: Metric
    target: float = Field(ge=0, strict=True)
    period_start: date
    period_end: date
    owner: str = Field(min_length=1, max_length=160)
    comparison_reference: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_period(self):
        if not 0 < (self.period_end - self.period_start).days <= 90:
            raise ValueError("period_end is exclusive and must be 1–90 days after period_start")
        if self.metric == "human_validation_rate" and self.target > 100:
            raise ValueError("a percentage target cannot exceed 100")
        return self


def validate_objective_settings(settings):
    if settings is not None and settings.get("operational_objective") is not None:
        return {
            **settings,
            "operational_objective": OperationalObjective.model_validate(
                settings["operational_objective"]
            ).model_dump(mode="json"),
        }
    return settings
