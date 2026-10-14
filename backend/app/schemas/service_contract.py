"""Closed contracts for governed assets and service promises."""

import json
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AssetRef(ClosedModel):
    asset_id: str = Field(min_length=1, max_length=36)
    workspace_id: str = Field(min_length=1, max_length=36)
    kind: Literal["dataset", "model", "document_set", "reference"]
    version: int = Field(ge=1)
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ServiceStageBudget(ClosedModel):
    max_cost: float = Field(ge=0, le=1_000_000)
    max_tokens: int = Field(ge=0, le=1_000_000_000)
    max_seconds: float = Field(ge=0, le=604_800)


class ServiceBudget(ClosedModel):
    max_attempts: int = Field(default=3, ge=1, le=100)
    max_cost: float = Field(default=10, ge=0, le=1_000_000)
    max_tokens: int = Field(default=100_000, ge=0, le=1_000_000_000)
    max_seconds: float = Field(default=3600, gt=0, le=604_800)
    stages: dict[Literal["narration", "judge"], ServiceStageBudget] = Field(default_factory=dict)

    @model_validator(mode="after")
    def stage_allocations(self):
        for unit in ("cost", "tokens", "seconds"):
            if sum(
                Decimal(str(getattr(stage, "max_" + unit))) for stage in self.stages.values()
            ) > Decimal(str(getattr(self, "max_" + unit))):
                raise ValueError("SERVICE_STAGE_ALLOCATIONS_EXCEED_WINDOW")
        return self


class ServiceOutputPolicy(ClosedModel):
    require_human_review: bool = True
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    qualification_policy_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    destination: str = Field(default="work", pattern=r"^work(?::[A-Za-z0-9_-]{1,120})?$")


class ServiceInput(ClosedModel):
    payload_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    kind: Literal["dataset", "model", "document_set", "reference"]
    logical_key: str = Field(min_length=1, max_length=200)
    max_age_seconds: int = Field(default=86400, ge=1, le=31536000)
    require_qualified: bool = True
    representation: Literal["asset_ref", "native_id"] = "asset_ref"
    qualification_policy_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ServiceDefinition(ClosedModel):
    timezone: str = "UTC"
    cadence: Literal["daily", "weekly"] = "daily"
    days: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    deadline: str = Field(default="17:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    starts_on: date
    ends_on: date | None = None
    budget: ServiceBudget = Field(default_factory=ServiceBudget)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    output_policy: ServiceOutputPolicy = Field(default_factory=ServiceOutputPolicy)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    inputs: list[ServiceInput] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def valid_calendar(self):
        if len({i.payload_key for i in self.inputs}) != len(self.inputs):
            raise ValueError("SERVICE_INPUT_BINDING_DUPLICATE")
        if (
            len(
                json.dumps(
                    self.input_payload, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            )
            > 64_000
        ):
            raise ValueError("SERVICE_INPUT_PAYLOAD_TOO_LARGE")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("SERVICE_TIMEZONE_INVALID") from None
        if any(day not in range(7) for day in self.days) or len(set(self.days)) != len(self.days):
            raise ValueError("SERVICE_DAYS_INVALID")
        if self.cadence == "weekly" and len(self.days) != 1:
            raise ValueError("SERVICE_WEEKLY_REQUIRES_ONE_DAY")
        if self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("SERVICE_DATE_RANGE_INVALID")
        # Validate the JSON Schema itself; unresolved external schemas cannot
        # later turn a publication into an outbound HTTP request.
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(self.output_schema)

        def refs(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {"$ref", "$dynamicRef"} and (
                        not isinstance(child, str) or not child.startswith("#")
                    ):
                        raise ValueError("SERVICE_EXTERNAL_SCHEMA_REF_FORBIDDEN")
                    refs(child)
            elif isinstance(value, list):
                for child in value:
                    refs(child)

        refs(self.output_schema)
        return self


class ContractCreate(ClosedModel):
    system_id: str
    logical_key: str = Field(default="default", min_length=1, max_length=200)
    owner_user_id: str
    definition: ServiceDefinition


class AssetRegister(ClosedModel):
    kind: Literal["dataset", "model", "document_set", "reference"]
    logical_key: str = Field(min_length=1, max_length=200)
    manifest: dict[str, Any]
    parents: list[AssetRef] = Field(default_factory=list)
    run_id: str | None = None


class ReviewDelivery(ClosedModel):
    accept: bool
    expected_fence: int = Field(ge=1)
    expected_asset_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_qualification_digest: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = Field(default="", max_length=2000)
    qualify_candidate: bool = False


class PublishDelivery(ClosedModel):
    decision_id: str
    fence: int = Field(ge=1)
