"""The value contract of an automation (ADR 0003 lot 3).

Who answers for it, what it must reach over which period, what one unit is
worth and where that comes from. A proposal is validated here; the named owner
approves it. The indicators are the operational measures Agentium computes
from its own evidence, so the gap is measured, never typed in.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.operational_objective import UNITS

# ``human_waits`` is a snapshot of the current queue: it can never be compared
# with a past period, so it cannot carry a target.
Indicator = Literal[
    "completed_volume",
    "mean_duration_ms",
    "human_validation_rate",
    "measured_cost_usd",
]
INDICATORS: tuple[str, ...] = Indicator.__args__  # type: ignore[attr-defined]
SourceKind = Literal["agreement", "document", "measurement", "estimate"]
MAX_PERIOD_DAYS = 90


class ValueConvention(BaseModel):
    """What one business unit of the automation is worth, as agreed."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)
    value_per_unit: float = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    unit: str = Field(min_length=1, max_length=40)


class ValueSource(BaseModel):
    """Where the target and the convention come from."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: SourceKind
    reference: str = Field(min_length=1, max_length=500)


class ValueContractTerms(BaseModel):
    """The terms a revision freezes and its content hash covers."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)
    owner_user_id: str = Field(min_length=1, max_length=36)
    indicator: Indicator
    target: float = Field(ge=0)
    period_start: date
    period_end: date
    convention: ValueConvention
    source: ValueSource

    @model_validator(mode="after")
    def validate_period(self):
        if not 0 < (self.period_end - self.period_start).days <= MAX_PERIOD_DAYS:
            raise ValueError(
                f"period_end is exclusive and must be 1–{MAX_PERIOD_DAYS} days after period_start"
            )
        if self.indicator == "human_validation_rate" and self.target > 100:
            raise ValueError("a percentage target cannot exceed 100")
        return self

    @property
    def unit(self) -> str:
        return UNITS[self.indicator]


class ValueContractProposal(ValueContractTerms):
    """A proposal names the revision it was written against (compare-and-set)."""

    expected_revision: int = Field(ge=0)


class ValueContractDecision(BaseModel):
    """The owner decides on exactly the terms they read."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=500)
