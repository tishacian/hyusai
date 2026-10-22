"""Optional declared evidence for a versioned provider tariff."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TariffConversion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_currency: str = Field(pattern="^[A-Z]{3}$")
    source_rates: dict[str, str] = Field(min_length=2, max_length=4)
    rate: str = Field(min_length=1, max_length=80)
    reference: str = Field(min_length=1, max_length=500)
    observed_on: date
    convention: Literal["target_per_source"] = "target_per_source"
    rounding: Literal["half_even_12dp"] = "half_even_12dp"


class TariffProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=1, max_length=500)
    observed_on: date
    conversion: TariffConversion | None = None
